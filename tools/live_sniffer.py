#!/usr/bin/env python3
"""Decode Last War traffic live, on the Windows side.

WSL2 sits behind a NAT and cannot see the Windows host's packets, so live
decoding has to run where the game runs. This script sniffs the game port,
reassembles the TCP streams and prints each decoded command as it happens.

The protocol logic is **imported from lastwar_proto.py**, not copied — the
framer, XOR mask, compression and TLV parser live in exactly one place. See
docs/research/protocol.md for the format.

Requirements (on Windows): npcap, plus
    pip install scapy colorama zstandard

Run from an **Administrator** PowerShell — npcap needs it to capture:
    python tools\\live_sniffer.py

Options:
    --port 17935     game port (default)
    --iface "Ethernet"   pin an interface; omitted = auto-detect
    --list-ifaces    print interfaces and exit
    --raw            also dump the full payload of every message
    --udp            include UDP on the same port in the capture filter
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402  (path must be set first)

# --------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------

try:
    from colorama import Fore, Style, just_fix_windows_console

    just_fix_windows_console()
    C_UP, C_DOWN, C_CHAT = Fore.GREEN, Fore.CYAN, Fore.YELLOW
    C_DIM, C_ERR, C_RESET = Style.DIM, Fore.RED, Style.RESET_ALL
except Exception:  # colorama missing — degrade to plain text
    C_UP = C_DOWN = C_CHAT = C_DIM = C_ERR = C_RESET = ""

MAX_BUFFER = 4 << 20  # drop a desynced stream rather than grow without bound

# Fields worth putting on the one-line summary, per command prefix.
INTERESTING = (
    "x", "y", "viewLvl", "blockSize", "serverId", "worldId", "bigMap",
    "uid", "msg", "roomId", "senderName", "senderUid",
    "uuid", "ownerUid", "targetServer", "arriveTime", "startPos", "targetPos",
    "success", "clientTime", "serverTime", "cfgId", "pointId", "level",
    "allianceId", "helpId", "count", "type",
)


def fmt_value(value, budget: int = 48) -> str:
    if isinstance(value, dict):
        if "_blob" in value:
            return f"<blob {len(value['_blob']) // 2}B>"
        return "{…}" if value else "{}"
    if isinstance(value, list):
        return f"[{len(value)}]"
    if isinstance(value, str):
        return repr(value if len(value) <= budget else value[:budget] + "…")
    return str(value)


def summarise(payload) -> str:
    """One compact line of the fields a human actually wants to see."""
    if not isinstance(payload, dict):
        return fmt_value(payload)
    shown = [f"{k}={fmt_value(payload[k])}" for k in INTERESTING if k in payload]
    if not shown:
        shown = [
            f"{k}={fmt_value(v)}"
            for k, v in list(payload.items())[:4]
            if not k.startswith("_")
        ]
    extra = len(payload) - len(shown)
    line = " ".join(shown[:8])
    if extra > 0:
        line += f" {C_DIM}(+{extra} fields){C_RESET}"
    return line


# --------------------------------------------------------------------------
# Per-flow streaming reassembly
# --------------------------------------------------------------------------


class Stream:
    """One direction of one TCP connection, decoded incrementally.

    Live capture differs from a pcap in two ways that matter: packets can
    arrive out of order or be retransmitted, and the sniffer usually attaches
    mid-connection, so the first bytes are not a frame boundary.
    """

    def __init__(self, direction: str):
        self.direction = direction
        self.buf = b""
        self.next_seq: int | None = None
        self.pending: dict[int, bytes] = {}
        self.frames = 0
        self.desynced = False

    def feed(self, seq: int, data: bytes) -> None:
        if self.next_seq is None:
            self.next_seq = seq  # attach wherever the first packet lands
        if seq_lt(seq, self.next_seq):
            # Retransmission or overlap — keep only the genuinely new tail.
            skip = self.next_seq - seq
            if skip >= len(data):
                return
            data, seq = data[skip:], self.next_seq
        if seq != self.next_seq:
            self.pending[seq] = data  # gap: hold until the hole is filled
            return
        self.buf += data
        self.next_seq = seq + len(data)
        while self.next_seq in self.pending:
            chunk = self.pending.pop(self.next_seq)
            self.buf += chunk
            self.next_seq += len(chunk)
        if len(self.buf) > MAX_BUFFER:
            self.buf = self.buf[-(MAX_BUFFER // 2):]
            self.desynced = True

    def drain(self):
        """Yield every complete frame, keeping the partial tail buffered."""
        if not self.buf:
            return
        consumed = 0
        for env, _start, end in proto.iter_frames(self.buf, self.direction):
            consumed = end
            self.frames += 1
            yield env
        if consumed:
            self.buf = self.buf[consumed:]


def seq_lt(a: int, b: int) -> bool:
    """TCP sequence comparison, wrap-around safe."""
    return ((a - b) & 0xFFFFFFFF) > 0x7FFFFFFF


# --------------------------------------------------------------------------
# Sniffer
# --------------------------------------------------------------------------


class LiveDecoder:
    def __init__(self, port: int, show_raw: bool = False):
        self.port = port
        self.show_raw = show_raw
        self.streams: dict[tuple, Stream] = {}
        self.counts: Counter[str] = Counter()
        self.locked_iface: str | None = None
        self.lock = threading.Lock()
        self.started = time.time()
        self.packets = 0
        self.udp_noted = False

    def handle(self, pkt, iface: str | None) -> None:
        from scapy.layers.inet import IP, TCP, UDP  # local import: fast startup

        if not pkt.haslayer(IP):
            return

        if pkt.haslayer(UDP):
            if not self.udp_noted:
                self.udp_noted = True
                print(f"{C_DIM}note: UDP seen on port {self.port}; the game "
                      f"protocol is TCP-only, not decoding it{C_RESET}")
            return

        if not pkt.haslayer(TCP):
            return
        tcp, ip = pkt[TCP], pkt[IP]
        data = bytes(tcp.payload)
        if not data:
            return

        with self.lock:
            # Auto-detect: whichever interface first carries game traffic wins.
            if self.locked_iface is None and iface is not None:
                self.locked_iface = iface
                print(f"{C_DIM}[{stamp()}] locked onto interface: {iface}{C_RESET}")
            elif iface is not None and iface != self.locked_iface:
                return
            self.packets += 1

            direction = "down" if tcp.sport == self.port else "up"
            key = (ip.src, tcp.sport, ip.dst, tcp.dport)
            stream = self.streams.get(key)
            if stream is None:
                stream = self.streams[key] = Stream(direction)
                peer = f"{ip.src}:{tcp.sport}" if direction == "down" else f"{ip.dst}:{tcp.dport}"
                print(f"{C_DIM}[{stamp()}] new {direction} stream — {peer}{C_RESET}")
            stream.feed(tcp.seq, data)

            for env in stream.drain():
                self.emit(direction, env)

    def emit(self, direction: str, env) -> None:
        command = proto.envelope_command(env) or "(keepalive)"
        payload = proto.envelope_payload(env)
        self.counts[command] += 1

        if "chat" in command.lower():
            colour, arrow = C_CHAT, "-->" if direction == "up" else "<--"
        elif direction == "up":
            colour, arrow = C_UP, "-->"
        else:
            colour, arrow = C_DOWN, "<--"

        print(f"{stamp()} {colour}{arrow} {command}{C_RESET}  {summarise(payload)}")
        if self.show_raw:
            import json

            print(f"        {C_DIM}{json.dumps(payload, ensure_ascii=False)[:1500]}{C_RESET}")

    def report(self) -> None:
        elapsed = time.time() - self.started
        total = sum(s.frames for s in self.streams.values())
        print(f"\n{C_DIM}{'-' * 64}{C_RESET}")
        print(f"captured {self.packets} packets / {total} frames in {elapsed:.0f}s "
              f"across {len(self.streams)} half-streams")
        if self.counts:
            print("\ntop commands:")
            for name, count in self.counts.most_common(20):
                print(f"  {count:<6} {name}")
        desynced = [k for k, s in self.streams.items() if s.desynced]
        if desynced:
            print(f"\n{C_ERR}{len(desynced)} stream(s) overflowed and were trimmed — "
                  f"the sniffer likely attached mid-connection.{C_RESET}")
        if proto.unknown_tags:
            print(f"\n{C_ERR}unknown TLV tags — the protocol has changed, "
                  f"update docs/research/protocol.md:{C_RESET}")
            for tag, count in proto.unknown_tags.most_common():
                print(f"  0x{tag:02x} x{count}")


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def list_ifaces() -> list:
    try:
        from scapy.interfaces import get_working_ifaces

        return list(get_working_ifaces())
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--port", type=int, default=17935, help="game port (default 17935)")
    ap.add_argument("--iface", help="interface name; omitted = auto-detect")
    ap.add_argument("--list-ifaces", action="store_true", help="list interfaces and exit")
    ap.add_argument("--raw", action="store_true", help="dump the full payload of each message")
    ap.add_argument("--udp", action="store_true", help="include UDP in the capture filter")
    args = ap.parse_args()

    try:
        from scapy.config import conf
        from scapy.sendrecv import sniff
    except ImportError:
        print(f"{C_ERR}scapy is missing — pip install scapy colorama zstandard{C_RESET}",
              file=sys.stderr)
        return 1
    conf.verb = 0

    if args.list_ifaces:
        for iface in list_ifaces():
            print(f"  {getattr(iface, 'name', iface)}")
        return 0

    try:
        import zstandard  # noqa: F401
    except ImportError:
        print(f"{C_ERR}zstandard is missing — compressed server frames (the big "
              f"ones, including init) will not decode.{C_RESET}")
        print(f"{C_ERR}  pip install zstandard{C_RESET}\n")

    bpf = f"tcp port {args.port}"
    if args.udp:
        bpf = f"(tcp or udp) port {args.port}"

    decoder = LiveDecoder(args.port, show_raw=args.raw)
    stop = threading.Event()

    # Deliberately no IP filter: the game address changes between sessions and
    # the client races several gateways at login, so pinning an IP loses them.
    targets = [args.iface] if args.iface else [
        getattr(i, "name", i) for i in list_ifaces()
    ] or [None]

    print(f"Last War live decoder — filter '{bpf}'")
    if args.iface:
        print(f"interface: {args.iface}")
    else:
        print(f"auto-detecting across {len(targets)} interface(s); "
              f"start or use the game to trigger traffic")
    print(f"{C_DIM}Ctrl+C to stop{C_RESET}\n")

    def run(iface):
        try:
            sniff(
                filter=bpf,
                iface=iface,
                prn=lambda p: decoder.handle(p, iface),
                store=False,
                stop_filter=lambda _p: stop.is_set(),
            )
        except Exception as exc:  # a single dead interface must not kill the run
            if not stop.is_set():
                print(f"{C_DIM}iface {iface}: {exc}{C_RESET}", file=sys.stderr)

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in targets]
    for thread in threads:
        thread.start()

    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        while not stop.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        stop.set()

    decoder.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
