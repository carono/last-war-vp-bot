#!/usr/bin/env python3
"""Decode Last War traffic live, on the Windows side.

WSL2 sits behind a NAT and cannot see the Windows host's packets, so live
decoding has to run where the game runs. This script sniffs TCP, finds the game
stream **by frame shape rather than by port**, and prints each decoded command
as it happens.

The protocol logic is **imported from lastwar_proto.py**, not copied — the
framer, XOR mask, compression and TLV parser live in exactly one place. See
docs/research/protocol.md for the format.

Requirements (on Windows): npcap, plus
    pip install scapy colorama zstandard

Run from an **Administrator** PowerShell — npcap needs it to capture:
    python tools\\live_sniffer.py               decode
    python tools\\live_sniffer.py --discover    show every TCP flow seen

Options:
    --discover       list every TCP flow with its opening bytes, decode nothing
    --port PORT      narrow the capture filter to one port (default: all TCP)
    --iface NAME     pin an interface; omitted = auto-detect
    --list-ifaces    print interfaces and exit
    --raw            also dump the full payload of every message
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from collections import Counter
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
    C_DIM, C_ERR, C_OK, C_RESET = Style.DIM, Fore.RED, Fore.MAGENTA, Style.RESET_ALL
except Exception:  # colorama missing — degrade to plain text
    C_UP = C_DOWN = C_CHAT = C_DIM = C_ERR = C_OK = C_RESET = ""

MAX_BUFFER = 4 << 20    # drop a desynced stream rather than grow without bound
PROBE_LIMIT = 8 << 10   # bytes per probe round before sliding the window
PROBE_WINDOW = 2 << 10  # only ever scan this far in for a sync point
MAX_PROBE_ROUNDS = 64   # ~512 KB of unrecognised data before writing a stream off

INTERESTING = (
    "x", "y", "viewLvl", "blockSize", "serverId", "worldId", "bigMap",
    "uid", "msg", "roomId", "senderName", "senderUid",
    "uuid", "ownerUid", "targetServer", "arriveTime", "startPos", "targetPos",
    "success", "clientTime", "serverTime", "cfgId", "pointId", "level",
    "allianceId", "helpId", "count", "type",
)


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


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


def looks_like_envelope(env) -> bool:
    """Signature of a game envelope: {"c": …, "a": …, "p": {…}}.

    All three keys are required. Resyncing through unrelated traffic can
    occasionally produce a parsable map, but not one with this exact shape.
    """
    return (
        isinstance(env, dict)
        and isinstance(env.get(proto.K_PARAMS), dict)
        and proto.K_COMMAND in env
        and "a" in env
    )


# --------------------------------------------------------------------------
# Per-flow streaming reassembly + game detection
# --------------------------------------------------------------------------


def seq_lt(a: int, b: int) -> bool:
    """TCP sequence comparison, wrap-around safe."""
    return ((a - b) & 0xFFFFFFFF) > 0x7FFFFFFF


class Stream:
    """One direction of one TCP connection, classified then decoded.

    Live capture differs from a pcap in two ways that matter: packets can
    arrive out of order or be retransmitted, and the sniffer usually attaches
    mid-connection, so the first bytes are not a frame boundary.
    """

    def __init__(self):
        self.state = "probing"        # probing | game | ignored
        self.direction: str | None = None
        self.buf = b""
        self.next_seq: int | None = None
        self.pending: dict[int, bytes] = {}
        self.frames = 0
        self.opening = b""            # first bytes, for --discover
        self.iface: str | None = None
        self.desynced = False
        self.probed_at = 0            # buffer length at the last classify attempt
        self.probe_rounds = 0

    def feed(self, seq: int, data: bytes) -> None:
        if self.state == "ignored":
            return
        if not self.opening:
            self.opening = data[:16]
        if self.next_seq is None:
            self.next_seq = seq  # attach wherever the first packet lands
        if seq_lt(seq, self.next_seq):
            skip = self.next_seq - seq  # retransmission: keep only the new tail
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

    def classify(self) -> bool:
        """Decide whether this stream is the game, by frame shape not by port.

        Returns True the moment it is recognised. Probing garbage raises
        BadTag by design, so the global tag counter is restored afterwards —
        otherwise every TLS stream on the box would show up as a protocol gap.
        """
        if self.state != "probing" or len(self.buf) < 8:
            return False
        # Re-probing on every packet is wasteful: resyncing through unrelated
        # traffic is the hot path. Only retry once meaningfully more data has
        # arrived, and never scan more than the first PROBE_WINDOW bytes.
        if len(self.buf) - self.probed_at < 256 and self.probed_at:
            return False
        self.probed_at = len(self.buf)
        window = self.buf[:PROBE_WINDOW]
        saved = proto.unknown_tags.copy()
        try:
            # Deliberately no check on buf[0]: when the game is already running
            # the sniffer attaches mid-connection and the first byte is
            # arbitrary. iter_frames resyncs to the next valid flag byte, which
            # is the only way that case is ever recognised.
            for direction in ("down", "up"):
                for env, _start, _end in proto.iter_frames(window, direction):
                    if looks_like_envelope(env):
                        self.state = "game"
                        self.direction = direction
                        return True
                    break
        except Exception:
            pass
        finally:
            proto.unknown_tags.clear()
            proto.unknown_tags.update(saved)

        if len(self.buf) > PROBE_LIMIT:
            # Sliding probe rather than a one-shot verdict. Attaching to a live
            # connection can land inside a huge frame — the 445 KB init sent at
            # login is 68 KB on the wire — and a single 8 KB look would write
            # the server direction off before the next frame boundary arrives.
            self.probe_rounds += 1
            self.buf = b""
            self.probed_at = 0
            if self.probe_rounds >= MAX_PROBE_ROUNDS:
                self.state = "ignored"
                self.pending.clear()
        return False

    def drain(self):
        """Yield every complete frame, keeping the partial tail buffered."""
        if self.state != "game" or not self.buf:
            return
        consumed = 0
        for env, _start, end in proto.iter_frames(self.buf, self.direction):
            consumed = end
            self.frames += 1
            yield env
        if consumed:
            self.buf = self.buf[consumed:]


# --------------------------------------------------------------------------
# Sniffer
# --------------------------------------------------------------------------


class LiveDecoder:
    def __init__(self, discover: bool = False, show_raw: bool = False):
        self.discover = discover
        self.show_raw = show_raw
        self.streams: dict[tuple, Stream] = {}
        self.counts: Counter[str] = Counter()
        self.endpoints: set[tuple] = set()
        self.locked_iface: str | None = None
        self.lock = threading.Lock()
        self.started = time.time()
        self.packets = 0

    def handle(self, pkt, iface: str | None) -> None:
        from scapy.layers.inet import IP, TCP  # local import keeps startup fast

        if not (pkt.haslayer(IP) and pkt.haslayer(TCP)):
            return
        tcp, ip = pkt[TCP], pkt[IP]
        data = bytes(tcp.payload)
        if not data:
            return

        with self.lock:
            self.packets += 1
            key = (ip.src, tcp.sport, ip.dst, tcp.dport)
            stream = self.streams.get(key)
            first_sight = stream is None
            if first_sight:
                stream = self.streams[key] = Stream()
                stream.iface = iface

            # Duplicate delivery across interfaces is absorbed by the sequence
            # check in feed(), so no interface locking is needed.
            stream.feed(tcp.seq, data)

            if self.discover:
                if first_sight:
                    self.report_flow(key, data)
                return

            if stream.state == "probing" and stream.classify():
                self.announce(key, stream)
            for env in stream.drain():
                self.emit(stream.direction, env)

    def report_flow(self, key, data: bytes) -> None:
        src, sport, dst, dport = key
        kind = proto.classify(data)
        colour = C_OK if kind == "GAME" else C_DIM
        mark = "GAME?" if kind == "GAME" else kind
        print(f"{stamp()} {colour}{mark:<8}{C_RESET} {src}:{sport} -> {dst}:{dport}"
              f"   {data[:8].hex(' ')}")

    def announce(self, key, stream: Stream) -> None:
        src, sport, dst, dport = key
        endpoint = (src, sport) if stream.direction == "down" else (dst, dport)
        if endpoint in self.endpoints:
            return
        self.endpoints.add(endpoint)
        where = f" on {stream.iface}" if stream.iface else ""
        print(f"\n{C_OK}[{stamp()}] GAME STREAM FOUND — {endpoint[0]}:{endpoint[1]}"
              f"{where}{C_RESET}")
        print(f"{C_OK}    port {endpoint[1]} — decoding from here{C_RESET}\n")

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
        print(f"{self.packets} packets / {total} frames in {elapsed:.0f}s "
              f"across {len(self.streams)} half-streams")

        if self.discover:
            kinds = Counter(proto.classify(s.opening) for s in self.streams.values())
            print(f"flows by shape: {dict(kinds)}")
            print("\nIf nothing says GAME, the traffic is not crossing this "
                  "interface — try --list-ifaces, or check whether the game is "
                  "running through a VPN adapter.")
            return

        if self.endpoints:
            print("game endpoints: " + ", ".join(f"{h}:{p}" for h, p in sorted(self.endpoints)))
        else:
            print(f"{C_ERR}no game stream detected.{C_RESET} Run with --discover to see "
                  f"what is actually crossing this interface.")
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
    ap.add_argument("--discover", action="store_true",
                    help="list every TCP flow with its opening bytes, decode nothing")
    ap.add_argument("--port", type=int,
                    help="narrow the capture filter to one port (default: all TCP)")
    ap.add_argument("--iface", help="interface name; omitted = auto-detect")
    ap.add_argument("--list-ifaces", action="store_true", help="list interfaces and exit")
    ap.add_argument("--raw", action="store_true", help="dump the full payload of each message")
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

    if not args.discover:
        try:
            import zstandard  # noqa: F401
        except ImportError:
            print(f"{C_ERR}zstandard is missing — compressed server frames (the big "
                  f"ones, including init) will not decode.{C_RESET}")
            print(f"{C_ERR}  pip install zstandard{C_RESET}\n")

    # No port and no IP filter by default: the game's address changes between
    # sessions and the client races several gateways at login, so anything
    # pinned loses traffic. The stream is found by frame shape instead.
    bpf = f"tcp port {args.port}" if args.port else "tcp"

    decoder = LiveDecoder(discover=args.discover, show_raw=args.raw)
    stop = threading.Event()

    targets = [args.iface] if args.iface else [
        getattr(i, "name", i) for i in list_ifaces()
    ] or [None]

    mode = "DISCOVER — listing every TCP flow" if args.discover else "decoding by frame shape"
    print(f"Last War live sniffer — {mode}")
    print(f"filter: '{bpf}'   interfaces: "
          f"{args.iface if args.iface else f'{len(targets)} (all)'}")
    if args.discover:
        print(f"{C_DIM}columns: shape  src -> dst  first 8 bytes{C_RESET}")
    else:
        print(f"{C_DIM}waiting for a stream whose frames match the protocol…{C_RESET}")
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
        except Exception as exc:  # one dead interface must not kill the run
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
