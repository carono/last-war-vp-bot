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

Every run also writes what it decodes to its own timestamped JSONL file,
``results/traffic/YYYYMMDD_HHMMSS_traffic.jsonl`` — one object per message, so a
restart never overwrites the previous session or blends into it.

Options:
    --discover       list every TCP flow with its opening bytes, decode nothing
    --port PORT      narrow the capture filter to one port (default: all TCP)
    --iface NAME     pin an interface; omitted = auto-detect
    --list-ifaces    print interfaces and exit
    --raw            also dump the full payload of every message
    --out PATH       write the JSONL transcript here instead of the default
    --no-out         decode to the terminal only, write no transcript
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections import Counter
from datetime import datetime

sys.path.insert(0, "tools/lib")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402  (path must be set first)
import run_output  # noqa: E402

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
PROBE_KEEP = 2 << 10    # tail carried into the next round, so a frame boundary
                        # straddling the cut is not thrown away
PROBE_FRAMES = 8        # frames to inspect per candidate before giving up
PROBE_CANDIDATES = 32   # sync points to try per direction, per round
MAX_PROBE_ROUNDS = 64   # ~512 KB of unrecognised data before writing a stream off
READY_TIMEOUT = 5.0     # seconds to wait for every interface to open before
                        # announcing readiness with whatever came up

INTERESTING = (
    "x", "y", "viewLvl", "blockSize", "serverId", "worldId", "bigMap",
    "uid", "msg", "roomId", "senderName", "senderUid", "attachmentId",
    "uuid", "ownerUid", "targetServer", "arriveTime", "startPos", "targetPos",
    "success", "clientTime", "serverTime", "cfgId", "pointId", "level",
    "allianceId", "helpId", "count", "type",
)


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


# attachmentId is a JSON blob describing a shared map object; it is the one
# string worth showing in full, so it gets its own budget.
WIDE_FIELDS = {"attachmentId"}


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
    shown = [
        f"{k}={fmt_value(payload[k], 300 if k in WIDE_FIELDS else 48)}"
        for k in INTERESTING
        if k in payload
    ]
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


def sync_candidates(buf: bytes, direction: str, limit: int) -> list[int]:
    """Offsets in buf that could start a frame, cheapest first.

    iter_frames abandons a whole scan when a length field reads as garbage,
    which happens constantly while probing unrelated bytes. Feeding it each
    candidate offset separately means one bad guess no longer hides every
    real frame boundary behind it.
    """
    magics = proto.SERVER_MAGICS if direction == "down" else proto.CLIENT_MAGICS
    out: list[int] = []
    pos = -1
    while len(out) < limit:
        pos = proto._resync(buf, pos, magics)
        if pos < 0:
            break
        out.append(pos)
    return out


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
        # arrived.
        if len(self.buf) - self.probed_at < 256 and self.probed_at:
            return False
        self.probed_at = len(self.buf)
        saved = proto.unknown_tags.copy()
        try:
            # Deliberately no check on buf[0]: when the game is already running
            # the sniffer attaches mid-connection and the first byte is
            # arbitrary. iter_frames resyncs to the next valid flag byte, which
            # is the only way that case is ever recognised.
            # Scan the whole buffer, not a prefix of it. Server frames can be
            # tens of KB (the login init is 68 KB on the wire), so boundaries
            # are sparse and a fixed front window misses them — that is what
            # left the server direction unrecognised after a mid-session join.
            for direction in ("down", "up"):
                for start in sync_candidates(self.buf, direction, PROBE_CANDIDATES):
                    for seen, (env, _s, _e) in enumerate(
                        proto.iter_frames(self.buf[start:], direction)
                    ):
                        if looks_like_envelope(env):
                            self.state = "game"
                            self.direction = direction
                            # Drop the bytes before the boundary so drain()
                            # starts on a frame, not mid-frame.
                            self.buf = self.buf[start:]
                            return True
                        if seen + 1 >= PROBE_FRAMES:
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
            self.buf = self.buf[-PROBE_KEEP:]
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
        try:
            for env, _start, end in proto.iter_frames(self.buf, self.direction):
                consumed = end
                self.frames += 1
                yield env
        except IndexError:
            # iter_frames bounds its loop on a 3-byte header, but a client
            # header is 5, so a buffer ending inside one indexes past the end.
            # That is "need more data", not a failure — keep what we have and
            # retry when the next segment lands.
            pass
        if consumed:
            self.buf = self.buf[consumed:]


# --------------------------------------------------------------------------
# Sniffer
# --------------------------------------------------------------------------


def is_foreign(mine, sport: int, dport: int) -> bool:
    """Is this packet ANOTHER account's client? ``mine`` is what `own_ports()` said.

    THREE ANSWERS, NOT TWO (#1306), and this function exists so that the difference is
    stated once and can be read without a live capture:

    * ``None`` — «could not tell». Nothing is foreign; the separation is lost rather
      than the traffic.
    * a set of ports — ours. A packet on none of them is somebody else's.
    * the EMPTY set — «asked, and this account has no client running». Then every
      packet here is somebody else's, which is the case that used to be folded into
      «could not tell»: a profile whose client was down went on firing its triggers off
      a live account's pushes, at the same second, measured.
    """
    if mine is None:
        return False
    return sport not in mine and dport not in mine


class LiveDecoder:
    def __init__(self, discover: bool = False, show_raw: bool = False,
                 transcript=None):
        self.discover = discover
        self.show_raw = show_raw
        # Open file handle (or None). The subclasses in tools/ — chat_monitor,
        # rally_monitor, the map scanners — write their own domain records and
        # never pass one, so they are unaffected.
        self.transcript = transcript
        self.streams: dict[tuple, Stream] = {}
        self.counts: Counter[str] = Counter()
        self.endpoints: set[tuple] = set()
        self.locked_iface: str | None = None
        self.lock = threading.Lock()
        self.started = time.time()
        self.packets = 0
        # WHOSE CLIENT THIS CAPTURE IS FOR (map_capture.own_ports_watcher).
        #
        # `None` here — everybody's, which is what every capture did until now and is
        # what a capture run by hand still is. Otherwise a callable returning the LOCAL
        # tcp ports belonging to our own client, refreshed as it is asked, and a packet
        # on any other port is dropped before it is decoded at all. The CALLABLE has
        # three answers of its own — a set, the empty set («we have no client, so none
        # of this is ours») and `None` («could not tell, keep everything») — and
        # `map_capture.OwnPorts` is where they are spelled out.
        #
        # It is needed because the BPF filter cannot express it. The filter narrows by
        # the game's REMOTE port, and two clients of the same game dial the same
        # server port — so with a second account running, every capture on this machine
        # has been decoding both accounts' traffic and firing both profiles' triggers
        # off whichever arrived. The local port is the thing that differs, and it is
        # only knowable from the socket table, not from the packet.
        self.own_ports = None
        self.foreign = 0                 # packets dropped as another client's

    def feed_packet(self, pkt, iface: str | None) -> None:
        """Scapy sniffer entry point — hand it one captured packet.

        `map_capture.sniff_forever` calls this for every packet npcap delivers,
        so any LiveDecoder — not just MapIndex — can be driven by
        `map_capture.start_capture`. `handle` already re-parses the raw bytes as
        Ethernet when scapy fails to guess the datalink type, so there is
        nothing to add here; MapIndex overrides it only to count deliveries.
        """
        self.handle(pkt, iface)

    def handle(self, pkt, iface: str | None) -> None:
        from scapy.layers.inet import IP, TCP  # local import keeps startup fast
        from scapy.layers.l2 import Ether

        # npcap reports linktype 1 (Ethernet) but scapy sometimes fails to map
        # it and hands back an unparsed Packet with no IP/TCP layer, which would
        # be silently dropped here — the whole capture then decodes nothing.
        # Re-parse the raw bytes as Ethernet ourselves, exactly as the dumpcap
        # path in live_tshark.py already does with Ether(raw).
        if not pkt.haslayer(IP):
            try:
                pkt = Ether(bytes(pkt))
            except Exception:
                return
        if not (pkt.haslayer(IP) and pkt.haslayer(TCP)):
            return
        tcp, ip = pkt[TCP], pkt[IP]
        data = bytes(tcp.payload)
        if not data:
            return
        # Another account's client, if we know enough to tell. Before the stream
        # bookkeeping, so a foreign connection never even gets a Stream of its own.
        if self.own_ports is not None:
            if is_foreign(self.own_ports(), tcp.sport, tcp.dport):
                self.foreign += 1
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

    def record(self, obj: dict) -> None:
        """Append one JSON object to this run's transcript, if one is open.

        Called from `handle` under `self.lock`, so lines never interleave. A
        transcript that cannot be written (full disk, handle closed by a Stop
        racing the reader thread) is reported once and then dropped — losing the
        log must never take the capture down with it.
        """
        if self.transcript is None:
            return
        line = {"ts": datetime.now().isoformat(timespec="seconds")}
        line.update(obj)
        try:
            self.transcript.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            print(f"{C_ERR}transcript write failed ({exc}) — continuing without it{C_RESET}",
                  file=sys.stderr)
            self.transcript = None

    def close_transcript(self) -> None:
        handle, self.transcript = self.transcript, None
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass

    def report_flow(self, key, data: bytes) -> None:
        src, sport, dst, dport = key
        kind = proto.classify(data)
        colour = C_OK if kind == "GAME" else C_DIM
        mark = "GAME?" if kind == "GAME" else kind
        print(f"{stamp()} {colour}{mark:<8}{C_RESET} {src}:{sport} -> {dst}:{dport}"
              f"   {data[:8].hex(' ')}")
        self.record({"event": "flow", "shape": kind, "src": f"{src}:{sport}",
                     "dst": f"{dst}:{dport}", "opening": data[:8].hex(" ")})

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
            print(f"        {C_DIM}{json.dumps(payload, ensure_ascii=False)[:1500]}{C_RESET}")
        # The transcript keeps the FULL payload regardless of --raw: the terminal
        # line is a summary, the file is the record you go back to afterwards.
        self.record({"dir": direction, "cmd": command, "payload": payload})

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
    ap.add_argument("--out", help="JSONL transcript path (default: a new "
                                  "results/traffic/<timestamp>_traffic.jsonl per run)")
    ap.add_argument("--label", help="free-text session label folded into the default "
                                    "file name (spaces become underscores); ignored with --out")
    ap.add_argument("--no-out", action="store_true",
                    help="decode to the terminal only, write no transcript")
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

    # One fresh transcript per run: a restart must never overwrite the previous
    # session's capture, nor append into it (two sessions in one file cannot be
    # told apart afterwards).
    transcript = out_path = None
    if not args.no_out:
        try:
            if args.out:
                os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
                transcript, out_path = open(args.out, "w", encoding="utf-8", buffering=1), args.out
            else:
                transcript, out_path = run_output.open_run_file(
                    "traffic", "traffic.jsonl", label=args.label)
        except OSError as exc:
            print(f"{C_ERR}cannot open transcript ({exc}) — decoding to the terminal only{C_RESET}",
                  file=sys.stderr)

    decoder = LiveDecoder(discover=args.discover, show_raw=args.raw, transcript=transcript)
    stop = threading.Event()

    targets = [args.iface] if args.iface else [
        getattr(i, "name", i) for i in list_ifaces()
    ] or [None]

    mode = "DISCOVER — listing every TCP flow" if args.discover else "decoding by frame shape"
    print(f"Last War live sniffer — {mode}")
    print(f"filter: '{bpf}'   interfaces: "
          f"{args.iface if args.iface else f'{len(targets)} (all)'}")
    if out_path:
        print(f"transcript: {out_path}")
    if args.discover:
        print(f"{C_DIM}columns: shape  src -> dst  first 8 bytes{C_RESET}")
    else:
        print(f"{C_DIM}waiting for a stream whose frames match the protocol…{C_RESET}")
    print(f"{C_DIM}Ctrl+C to stop{C_RESET}\n")

    # Readiness bookkeeping. The banner above is printed before a single
    # interface is open — npcap needs a moment per handle — so anyone driving
    # the game from a script (or the panel) would start acting while nothing is
    # captured yet. Count the interfaces that actually reached the capture loop
    # and announce ONE readiness line once every target has settled either way.
    opened = {"live": 0, "dead": 0}
    opened_lock = threading.Lock()

    def note(key):
        with opened_lock:
            opened[key] += 1

    def run(iface):
        try:
            sniff(
                filter=bpf,
                iface=iface,
                prn=lambda p: decoder.handle(p, iface),
                store=False,
                started_callback=lambda: note("live"),
                stop_filter=lambda _p: stop.is_set(),
            )
        except Exception as exc:  # one dead interface must not kill the run
            note("dead")
            if not stop.is_set():
                print(f"{C_DIM}iface {iface}: {exc}{C_RESET}", file=sys.stderr)

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in targets]
    for thread in threads:
        thread.start()

    # Cap the wait: a wedged interface must not hold the readiness line back
    # forever — better to report "5/17 live" than to stay silent.
    deadline = time.time() + READY_TIMEOUT
    while time.time() < deadline:
        with opened_lock:
            if opened["live"] + opened["dead"] >= len(targets):
                break
        time.sleep(0.05)
    with opened_lock:
        live = opened["live"]
    if live:
        print(f"{C_OK}CAPTURE READY — {live}/{len(targets)} interface(s) live{C_RESET}\n",
              flush=True)
    else:
        print(f"{C_ERR}CAPTURE FAILED — no interface could be opened "
              f"(npcap missing, or not running as admin){C_RESET}\n", flush=True)

    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        while not stop.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        stop.set()

    decoder.report()
    decoder.close_transcript()
    if out_path:
        print(f"\ntranscript written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
