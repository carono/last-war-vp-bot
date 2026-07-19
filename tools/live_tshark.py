#!/usr/bin/env python3
"""Live protocol decoding from WSL, using Wireshark's capture engine.

Scapy's own sniffing does not work reliably against npcap from the Windows-side
Python, but Wireshark does — and WSL can execute Windows binaries. So this
tool drives ``dumpcap.exe`` (the capture engine Wireshark itself uses), reads
the pcap stream straight off its stdout and decodes it as it arrives.

Everything protocol-related is imported from lastwar_proto.py and
live_sniffer.py — no logic is duplicated here. This module is only a transport:
Windows capture engine in, decoded commands out.

    python3 tools/live_tshark.py --list          # interfaces, with a traffic probe
    python3 tools/live_tshark.py                 # capture on every real interface
    python3 tools/live_tshark.py --iface 2       # pin one
    python3 tools/live_tshark.py --discover      # show every TCP flow, decode nothing
    python3 tools/live_tshark.py --tasks         # only secret tasks, with filters
    python3 tools/live_tshark.py --tasks --families   # tally cfgId families

No Administrator prompt is needed as long as npcap was installed with the
"allow non-administrator capture" option, which is how Wireshark normally sets
it up.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import struct
import subprocess
import sys
import threading
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET, LiveDecoder  # noqa: E402

WIRESHARK_DIRS = (
    "/mnt/c/Program Files/Wireshark",
    "/mnt/c/Program Files (x86)/Wireshark",
)

# A tile the map has not re-sent for this long is dropped from the index: its
# cached state is no longer verifiable, so serving it as raidable is the stale
# false positive this guards against (a tile whose dispatch "completed" a day
# ago still read can_loot=True). The map re-sends on-screen tiles as you pan,
# so anything unseen for minutes is off-screen, not current.
STALE_AFTER_SECONDS = 600

PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),      # microsecond, little-endian
    b"\xa1\xb2\xc3\xd4": (">", 1_000_000),      # microsecond, big-endian
    b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),  # nanosecond, little-endian
    b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),  # nanosecond, big-endian
}


def find_binary(name: str, override: str | None = None) -> str | None:
    if override:
        return override if os.path.exists(override) else None
    for directory in WIRESHARK_DIRS:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return path
    return None


def list_interfaces(tshark: str) -> list[tuple[str, str]]:
    """Return [(number, label)] for real capture devices, skipping extcap ones."""
    try:
        out = subprocess.run([tshark, "-D"], capture_output=True, text=True,
                             timeout=30).stdout
    except Exception as exc:
        print(f"{C_ERR}could not list interfaces: {exc}{C_RESET}", file=sys.stderr)
        return []
    found = []
    for line in out.splitlines():
        match = re.match(r"\s*(\d+)\.\s+(\S+)\s*(?:\((.*)\))?", line)
        if not match:
            continue
        number, device, label = match.group(1), match.group(2), match.group(3) or ""
        if not device.startswith(r"\Device\NPF_"):
            continue  # ciscodump, randpkt, sshdump… are not live adapters
        found.append((number, label or device))
    return found


class PcapStream:
    """Incremental reader for the pcap byte stream dumpcap writes to stdout."""

    def __init__(self):
        self.buf = b""
        self.endian: str | None = None
        self.linktype: int | None = None

    def feed(self, chunk: bytes):
        self.buf += chunk
        if self.endian is None:
            if len(self.buf) < 24:
                return
            magic = self.buf[:4]
            if magic not in PCAP_MAGICS:
                raise ValueError(f"not a pcap stream (magic {magic.hex()})")
            self.endian, _ = PCAP_MAGICS[magic]
            self.linktype = struct.unpack(self.endian + "I", self.buf[20:24])[0]
            self.buf = self.buf[24:]
        while len(self.buf) >= 16:
            _ts, _us, incl, _orig = struct.unpack(self.endian + "IIII", self.buf[:16])
            if len(self.buf) < 16 + incl:
                return
            data = self.buf[16:16 + incl]
            self.buf = self.buf[16 + incl:]
            yield data


def capture(binary: str, iface: str, label: str, decoder: LiveDecoder,
            bpf: str | None, stop: threading.Event, verbose: bool,
            registry: list | None = None) -> None:
    cmd = [binary, "-i", iface, "-P", "-w", "-"]
    if bpf:
        cmd += ["-f", bpf]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception as exc:
        if verbose:
            print(f"{C_DIM}iface {iface}: {exc}{C_RESET}", file=sys.stderr)
        return

    # The loop below blocks in `proc.stdout.read()`, which on a silent
    # interface never returns — so setting `stop` cannot wake this thread and
    # the `finally` never runs. The threads are daemons, so the interpreter
    # exits anyway and leaves dumpcap.exe running on the Windows side, one per
    # interface per run. Handing the process to the caller lets it do what
    # probe_interfaces() already does: kill the capture engine to end the read.
    if registry is not None:
        registry.append(proc)

    from scapy.layers.l2 import Ether

    reader = PcapStream()
    try:
        while not stop.is_set():
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            try:
                for raw in reader.feed(chunk):
                    if reader.linktype != 1:  # only Ethernet is expected here
                        continue
                    try:
                        decoder.handle(Ether(raw), label)
                    except Exception:
                        pass  # a malformed packet must not stop the capture
            except ValueError as exc:
                if verbose:
                    print(f"{C_DIM}iface {iface}: {exc}{C_RESET}", file=sys.stderr)
                break
    finally:
        proc.kill()


class CaptureUnavailable(RuntimeError):
    """Wireshark, scapy or an interface is missing — nothing can be captured."""


class TaskListener:
    """Background capture that indexes secret tasks as they cross the wire.

    `world.get.block` fires while the map scrolls and its responses carry
    every task tile in view, so the bot can ask "any level-7 task with a free
    loot slot?" and get exact numbers instead of an OCR guess.

    Tasks are keyed by uuid: the client does not debounce, so dragging the
    map re-sends the same region, and a repeat refreshes a record rather than
    duplicating it. The loot list on a refreshed tile is the newer one, which
    is what a raid decision should use.

    This is the bot-facing entry point of the tools/ protocol stack — the
    reason `script_engine.SCAN_SECRET_MISSIONS` can reach it at all.
    """

    def __init__(self, interface: str | None = None,
                 tshark: str | None = None, dumpcap: str | None = None) -> None:
        self.interface = interface
        # Without these the --tshark/--dumpcap flags parse but do nothing in
        # --tasks mode, so a non-default Wireshark install reports "not found"
        # and there is no way to talk the tool out of it.
        self.tshark_path = tshark
        self.dumpcap_path = dumpcap
        self.stale_after = STALE_AFTER_SECONDS
        self._tasks: dict[int, object] = {}
        # Wall-clock of the last time the map re-sent each task, so stale ones
        # can be evicted rather than served as if still live.
        self._seen_at: dict[int, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._procs: list[subprocess.Popen] = []
        # Traffic counters. Without these a zero result is ambiguous — no map
        # data at all (the map was not scrolling) reads exactly the same as
        # map data that happened to contain no tasks, and the two call for
        # opposite responses from whoever is running the scan.
        self.blocks_seen = 0
        self.tiles_seen = 0
        self.tile_kinds: Counter = Counter()

    # ---- lifecycle ----

    def start(self) -> None:
        """Begin capturing. Raises CaptureUnavailable if it cannot."""
        try:
            import lastwar_proto as proto
            from live_sniffer import LiveDecoder
        except ImportError as exc:  # scapy / zstandard missing
            raise CaptureUnavailable(
                f"protocol stack unavailable: {exc} — pip install scapy zstandard"
            ) from exc

        tshark = find_binary("tshark.exe", self.tshark_path)
        dumpcap = find_binary("dumpcap.exe", self.dumpcap_path) or tshark
        if not dumpcap or not tshark:
            missing = "tshark.exe" if not tshark else "dumpcap.exe"
            override = "--tshark" if not tshark else "--dumpcap"
            looked = ", ".join(WIRESHARK_DIRS)
            # "not found" on its own sends people hunting for an install that
            # is usually already there — the useful facts are which binary was
            # missing, where it was looked for, and how to override that.
            raise CaptureUnavailable(
                f"{missing} not found. Looked in: {looked}. "
                f"If Wireshark lives elsewhere, pass {override} <path>. "
                f"Note this path is read from WSL, so it must be a /mnt/... "
                f"path visible to this user."
            )

        ifaces = list_interfaces(tshark)
        if not ifaces:
            raise CaptureUnavailable("no capture interfaces found")
        if self.interface:
            ifaces = [(self.interface, f"iface {self.interface}")]

        listener = self

        class _Collector(LiveDecoder):
            def emit(self, direction, env):  # LiveDecoder hook
                if direction != "down":
                    return
                if proto.envelope_command(env) != "world.get.block":
                    return
                listener._ingest(proto.envelope_payload(env))

        decoder = _Collector()
        self._stop.clear()
        self._procs = []
        # "tcp" is as narrow as the filter can safely go: the game endpoint is
        # not stable and is dialled without DNS, so the stream is recognised
        # by frame shape, not by address or port.
        self._threads = [
            threading.Thread(
                target=capture,
                args=(dumpcap, number, label, decoder, "tcp", self._stop, False,
                      self._procs),
                daemon=True,
            )
            for number, label in ifaces
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Kill the capture engines first: that is what unblocks the reader
        # threads. Joining before killing would just burn the timeout on
        # every interface that happened to be quiet.
        for proc in self._procs:
            try:
                proc.kill()
            except Exception:
                pass
        self._procs = []
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []

    def __enter__(self) -> "TaskListener":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()

    # ---- data ----

    def _ingest(self, payload: dict) -> None:
        import lastwar_proto as proto

        kinds = Counter(
            (point.get("_protobuf") or {}).get("f2")
            for block in payload.get("serverPointArr") or ()
            for point in block.get("points") or ()
        )
        found = list(proto.secret_tasks(payload))
        with self._lock:
            self.blocks_seen += 1
            self.tiles_seen += sum(kinds.values())
            self.tile_kinds.update(kinds)
            now = time.time()
            for task in found:
                self._tasks[task.uuid] = task
                self._seen_at[task.uuid] = now

    @property
    def tasks(self) -> list:
        cutoff = time.time() - self.stale_after
        with self._lock:
            for uuid in [u for u, seen in self._seen_at.items() if seen < cutoff]:
                self._tasks.pop(uuid, None)
                self._seen_at.pop(uuid, None)
            return list(self._tasks.values())

    def find(self, **criteria) -> list:
        """Filter what has been seen so far. See `lastwar_proto.filter_tasks`."""
        import lastwar_proto as proto

        return proto.filter_tasks(self.tasks, **criteria)

    def wait_for(self, timeout: float = 30.0, poll: float = 0.5,
                 **criteria) -> list:
        """Capture until something matches, or the timeout expires.

        Returns as soon as at least one match exists — the map is being panned
        while this runs, so waiting out the full timeout would only pile up
        tiles the caller did not ask about. An empty list on timeout is a
        legitimate answer, not an error.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = self.find(**criteria)
            if matches:
                return matches
            time.sleep(poll)
        return self.find(**criteria)


def dump_tasks(tasks: list, path: str) -> None:
    """Write the task list to `path`, atomically.

    Called repeatedly while the capture runs, so a reader can poll the file
    mid-session. Writing in place would let a reader catch a half-written
    file; writing to a sibling and renaming makes the swap atomic, and keeping
    the temp file in the same directory keeps the rename on one filesystem.
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump([t.as_dict() for t in tasks], fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def watch_tasks(args) -> int:
    """`--tasks` mode: stream secret tasks, optionally tally cfgId families.

    The family tally is the experiment that settles the star. Pan the map
    slowly over a patch with a handful of tasks, then compare the printed
    counts with the stars actually drawn on that patch. If they match family
    6000, the current reading holds; if they track a different family — or
    the loot count instead — update STAR_TASK_FAMILIES in lastwar_proto.py,
    which is the only place the assumption lives.
    """
    import lastwar_proto as proto

    # Redirected to a file, stdout is block-buffered, so a run that is watched
    # via `tail -f` shows nothing for minutes and reads as hung.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    try:
        listener = TaskListener(interface=args.iface, tshark=args.tshark,
                                dumpcap=args.dumpcap)
        listener.start()
    except CaptureUnavailable as exc:
        print(f"{C_ERR}cannot capture: {exc}{C_RESET}", file=sys.stderr)
        return 1

    print(f"listening {args.seconds}s for secret tasks — "
          f"{C_DIM}pan the map, or nothing will arrive{C_RESET}")
    print(f"{C_DIM}(the game sends map data only while the map scrolls){C_RESET}\n")

    reported: set = set()
    deadline = time.time() + args.seconds
    heartbeat = time.time()
    try:
        while time.time() < deadline:
            time.sleep(1.0)
            # A silent tool cannot be told apart from a stalled one, and the
            # operator needs to know *while panning* whether the panning is
            # producing anything.
            if time.time() - heartbeat >= 10:
                heartbeat = time.time()
                left = int(deadline - time.time())
                print(f"{C_DIM}  …{left}s left — {listener.blocks_seen} map "
                      f"response(s), {listener.tiles_seen} tile(s), "
                      f"{len(listener.tasks)} task(s){C_RESET}")
                # Checkpoint on the same beat. A long run used to hold every
                # task in memory until it ended, so killing it — the usual way
                # an hour-long capture is cut short — threw away the lot.
                if args.json:
                    dump_tasks(listener.tasks, args.json)
            for task in listener.find(level=args.level, star_only=args.star,
                                      can_loot=args.can_loot,
                                      pending=args.pending):
                if task.uuid in reported:
                    continue
                reported.add(task.uuid)
                star = " *" if task.starred else "  "
                # Owner uid matters most on starred tasks (whose base you are
                # about to raid), so show it there.
                owner = f"  owner {task.owner_uid}" if task.starred else ""
                if task.pending:
                    tag = f"  {C_OK}PENDING{C_RESET}"
                elif task.can_loot:
                    tag = f"  {C_OK}LOOTABLE{C_RESET}"
                else:
                    tag = ""
                print(f"{star} lvl {task.level:>2}  ({task.x:>4},{task.y:>4})"
                      f"  server {task.server_id}  steal {task.loot_count}/3"
                      f"  family {task.family}  cfg {task.cfg_id}{owner}{tag}")
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()

    everything = listener.tasks
    print(f"\n{len(everything)} task(s) seen, {len(reported)} matched the filter")
    print(f"traffic: {listener.blocks_seen} map response(s), "
          f"{listener.tiles_seen} tile(s), kinds {dict(listener.tile_kinds)}")
    if not listener.blocks_seen:
        print(f"{C_ERR}No map data arrived at all.{C_RESET} The game sends it "
              f"only while the map is scrolling — keep dragging the map for "
              f"the whole run, not just at the start.")
    elif not everything:
        print(f"{C_DIM}Map data arrived but held no secret tasks (no f2=17 "
              f"tiles) — pan over an area that has task markers.{C_RESET}")

    if args.families:
        print("\ncfgId families — compare these with the stars on screen:")
        tally = Counter(t.family for t in everything)
        for family, count in sorted(tally.items()):
            mark = ("  <- currently read as STARRED"
                    if family in proto.STAR_TASK_FAMILIES else "")
            print(f"  family {family:<5} {count:>4} task(s){mark}")
            spots = [f"({t.x},{t.y})" for t in everything if t.family == family]
            print(f"    at {' '.join(spots[:12])}{' …' if len(spots) > 12 else ''}")
        print(f"\nlevels seen: {dict(sorted(Counter(t.level for t in everything).items()))}")

    if args.json:
        dump_tasks(everything, args.json)
        print(f"\nwrote {len(everything)} task(s) to {args.json}")
    return 0


def probe_interfaces(dumpcap: str, ifaces, seconds: int) -> dict[str, int]:
    """Count packets per interface so the quiet ones can be reported as quiet."""
    counts: dict[str, int] = {}
    procs: list[subprocess.Popen] = []
    lock = threading.Lock()

    def run(number, label, proc):
        reader = PcapStream()
        seen = 0
        try:
            while True:
                # Blocks until dumpcap writes or is killed — an idle interface
                # never returns on its own, so the deadline is enforced by
                # killing the process, not by polling the clock here.
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                try:
                    seen += sum(1 for _ in reader.feed(chunk))
                except ValueError:
                    break
        except Exception:
            pass
        with lock:
            counts[f"{number}. {label}"] = seen

    threads = []
    for number, label in ifaces:
        try:
            proc = subprocess.Popen([dumpcap, "-i", number, "-P", "-w", "-"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception:
            continue
        procs.append(proc)
        thread = threading.Thread(target=run, args=(number, label, proc), daemon=True)
        thread.start()
        threads.append(thread)

    time.sleep(seconds)
    for proc in procs:
        proc.kill()
    for thread in threads:
        thread.join(2)
    return counts


def _terminate(_signum, _frame):
    """Turn SIGTERM into the exception the cleanup paths already handle.

    Python's default SIGTERM handling tears the interpreter down without
    unwinding, so the `finally` blocks that kill the capture engines never
    run — and a background run is normally stopped with exactly that signal.
    Raising in the main thread, which is always the one parked in the sleep
    loop, routes it through the same cleanup as Ctrl+C.
    """
    raise KeyboardInterrupt


def main() -> int:
    signal.signal(signal.SIGTERM, _terminate)

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--iface", help="interface number from --list; omitted = all of them")
    ap.add_argument("--list", action="store_true",
                    help="list interfaces and probe each for traffic")
    ap.add_argument("--discover", action="store_true",
                    help="show every TCP flow with its opening bytes, decode nothing")
    ap.add_argument("--filter", help="capture filter (BPF), e.g. 'tcp'")
    ap.add_argument("--raw", action="store_true", help="dump the full payload of each message")
    ap.add_argument("--probe-seconds", type=int, default=5, help="probe duration for --list")
    ap.add_argument("--tshark", help="path to tshark.exe")
    ap.add_argument("--dumpcap", help="path to dumpcap.exe")
    ap.add_argument("--verbose", action="store_true", help="report per-interface errors")
    ap.add_argument("--duration", type=int, default=0,
                    help="stop after N seconds instead of waiting for Ctrl+C "
                         "(needed for unattended runs — a piped stdin never "
                         "delivers a KeyboardInterrupt)")
    ap.add_argument("--tasks", action="store_true",
                    help="decode only secret tasks (hero dispatch) off the map")
    ap.add_argument("--families", action="store_true",
                    help="with --tasks: tally cfgId families — settles the star")
    ap.add_argument("--seconds", type=int, default=60,
                    help="with --tasks: how long to listen (default 60)")
    ap.add_argument("--level", type=int, help="with --tasks: only this task level")
    ap.add_argument("--star", action="store_true",
                    help="with --tasks: only starred tasks (cfgId family 6000)")
    ap.add_argument("--can-loot", action="store_true",
                    help="with --tasks: only tasks raidable now (dispatch done, "
                         "not expired, slot free)")
    ap.add_argument("--pending", action="store_true",
                    help="with --tasks: only tasks about to become raidable "
                         "(dispatch finishing within ~10 min)")
    ap.add_argument("--json", help="with --tasks: write every task seen to this file")
    args = ap.parse_args()

    if args.tasks:
        return watch_tasks(args)

    tshark = find_binary("tshark.exe", args.tshark)
    dumpcap = find_binary("dumpcap.exe", args.dumpcap) or tshark
    if not tshark or not dumpcap:
        print(f"{C_ERR}Wireshark not found. Looked in:{C_RESET}", file=sys.stderr)
        for directory in WIRESHARK_DIRS:
            print(f"  {directory}", file=sys.stderr)
        print("Pass --tshark / --dumpcap explicitly.", file=sys.stderr)
        return 1

    ifaces = list_interfaces(tshark)
    if not ifaces:
        print(f"{C_ERR}no capture interfaces found{C_RESET}", file=sys.stderr)
        return 1

    if args.list:
        print(f"probing {len(ifaces)} interface(s) for {args.probe_seconds}s…\n")
        counts = probe_interfaces(dumpcap, ifaces, args.probe_seconds)
        for number, label in ifaces:
            key = f"{number}. {label}"
            seen = counts.get(key, 0)
            mark = f"{C_OK}{seen:>6} pkts{C_RESET}" if seen else f"{C_DIM}     idle{C_RESET}"
            print(f"  {mark}  {key}")
        print("\nPick one with --iface N, or run with no --iface to capture on all.")
        return 0

    targets = ([(args.iface, f"iface {args.iface}")] if args.iface else ifaces)

    decoder = LiveDecoder(discover=args.discover, show_raw=args.raw)
    stop = threading.Event()

    mode = "DISCOVER — listing every TCP flow" if args.discover else "decoding by frame shape"
    print(f"Last War live decoder via {os.path.basename(dumpcap)} — {mode}")
    print(f"interfaces: {len(targets)}   filter: {args.filter or 'none'}")
    deadline = time.time() + args.duration if args.duration else 0
    stop_hint = f"stopping after {args.duration}s" if args.duration else "Ctrl+C to stop"
    print(f"{C_DIM}{stop_hint}{C_RESET}\n")

    procs: list[subprocess.Popen] = []
    threads = [
        threading.Thread(target=capture,
                         args=(dumpcap, number, label, decoder, args.filter, stop,
                               args.verbose, procs),
                         daemon=True)
        for number, label in targets
    ]
    for thread in threads:
        thread.start()

    try:
        while not stop.is_set():
            if deadline and time.time() >= deadline:
                break
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        # Without this the daemon threads die still blocked on a read and the
        # dumpcap.exe children outlive the interpreter — they accumulate on
        # the Windows side across runs until something kills them by name.
        for proc in procs:
            try:
                proc.kill()
            except Exception:
                pass
        for thread in threads:
            thread.join(timeout=2)

    decoder.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
