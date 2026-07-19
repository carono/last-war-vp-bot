#!/usr/bin/env python3
"""Secret-task capture with no Wireshark executables in the loop.

`live_tshark.py` drives `dumpcap.exe` as a subprocess and reads pcap off its
stdout. This module talks to the npcap driver directly through scapy, so the
only Wireshark-related thing it needs is the npcap driver itself — no
`dumpcap.exe`, no `tshark.exe`, nothing spawned and nothing to leak.

Protocol logic is imported from lastwar_proto.py and the stream reassembly
from live_sniffer.py — neither is reimplemented here. This module is a
transport plus a secret-task index, and nothing else.

    python tools/capture_direct.py                       stream tasks, print them
                                                         (until Ctrl+C, no file written)
    python tools/capture_direct.py --seconds 300         stop on a timer instead
    python tools/capture_direct.py --json out.json       also checkpoint to a file
    python tools/capture_direct.py --json out.json --interval 3
                                                         flush it every 3s, not 15
    python tools/capture_direct.py --level 7 --can-loot  only raidable level-7s
    python tools/capture_direct.py --list-ifaces         interfaces, then exit

**This must run under the Windows Python, not the WSL one.** WSL2 sits in a
NAT'd VM whose network namespace is not the host's, so an AF_PACKET socket
there sees WSL's own traffic and never a byte of the game's. From WSL, invoke
the Windows interpreter by path:

    /mnt/c/Python312/python.exe tools/capture_direct.py --seconds 300

Requirements on that interpreter: npcap (ships with Wireshark), plus
`pip install scapy zstandard`. No Administrator prompt is needed when npcap
was installed with "allow non-administrator capture", which is Wireshark's
normal setup.

The game only sends `world.get.block` while the map is moving, so a run that
reports zero map responses means nobody was panning — not that the capture
is broken. The counters below are there to tell those two apart.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET, LiveDecoder  # noqa: E402

GAME_PORT = 17935

# Freshness window for the task index and its checkpoint, shared with the
# reader (proto.load_fresh_tasks) so writer and reader agree on "current". See
# proto.TASK_FRESH_SECONDS for why a tile not re-sent within it is untrustworthy.
STALE_AFTER_SECONDS = proto.TASK_FRESH_SECONDS

# There is deliberately no default sink. --json is opt-in so an unattended or
# exploratory run cannot quietly overwrite a checkpoint someone else is reading.


def check_platform() -> None:
    """Refuse to run where capture cannot possibly work, and say why.

    Started under the WSL interpreter this would sniff happily and report
    nothing forever, which looks identical to "the map was not moving" — the
    one failure this tool is otherwise careful to distinguish.
    """
    if sys.platform == "win32":
        return
    print(f"{C_ERR}This is the {sys.platform} interpreter.{C_RESET} WSL2 runs "
          f"in a NAT'd VM whose network namespace is not the Windows host's, "
          f"so it cannot see the game's packets — a capture here would sit "
          f"silent forever rather than fail.\n\n"
          f"Run it under the Windows Python instead:\n"
          f"    /mnt/c/Python312/python.exe {' '.join(sys.argv)}\n",
          file=sys.stderr)
    raise SystemExit(2)


def dump_tasks(records: list, path: str) -> bool:
    """Write already-built task records to `path`. True if the write landed.

    Called while the capture is still running so a reader can poll the file
    mid-session. Records come from `TaskIndex.records()`, each carrying
    `seen_at` so `proto.load_fresh_tasks()` can drop stale ones.

    This writes the target directly rather than renaming a temp file over it.
    A rename is the atomic option and would spare a poller from ever seeing a
    half-written file, but on Windows `os.replace` raises PermissionError
    (WinError 5) whenever anything else holds the target open — an editor, a
    poller, the indexer — and that killed whole capture sessions. A capture
    that survives is worth more than a checkpoint that is never briefly
    inconsistent, so a locked file now costs one skipped flush instead of the
    run. The next flush rewrites it whole.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False)
        return True
    except PermissionError:
        return False


class TaskIndex(LiveDecoder):
    """LiveDecoder that keeps the secret tasks instead of printing commands.

    Tasks are keyed by uuid because the client does not debounce: panning the
    map re-sends regions it already asked about, so a repeat has to refresh a
    record rather than append a duplicate. The refreshed tile carries the
    newer loot list, which is the one a raid decision should use.
    """

    def __init__(self, stale_after: float = STALE_AFTER_SECONDS) -> None:
        super().__init__()
        self.stale_after = stale_after
        self._tasks: dict[int, proto.SecretTask] = {}
        # Wall-clock of the last time the map re-sent each task, so stale ones
        # can be evicted rather than served as if still live.
        self._seen_at: dict[int, float] = {}
        self._index_lock = threading.Lock()
        # A zero result is ambiguous without these: no map data at all reads
        # exactly like map data that held no tasks, and the two call for
        # opposite responses from whoever is running the scan.
        self.blocks_seen = 0
        self.tiles_seen = 0
        self.tile_kinds: Counter = Counter()
        # Counted before any filtering, unlike LiveDecoder.packets which only
        # counts TCP packets carrying a payload. The gap between the two is
        # the difference between "npcap delivered nothing" and "it delivered
        # packets this decoder threw away", which need opposite fixes.
        self.delivered = 0

    def feed_packet(self, pkt, iface) -> None:
        """Hand one sniffed packet to the decoder, as a parsed Ethernet frame.

        npcap reports linktype 1 on these adapters, but scapy fails to map it
        to a class ("Unable to guess datalink type … Using <member 'name' of
        'Packet' objects>") and hands back an unparsed Packet with no IP or
        TCP layer, which the decoder then discards — 144 delivered, 0 decoded.
        Re-parsing the raw bytes ourselves sidesteps the guess entirely; this
        is what live_tshark.py has always done with `Ether(raw)`, and is why
        the dumpcap path never hit this.
        """
        from scapy.layers.l2 import Ether
        from scapy.layers.inet import IP

        self.delivered += 1
        if not pkt.haslayer(IP):
            try:
                pkt = Ether(bytes(pkt))
            except Exception:
                return
        self.handle(pkt, iface)

    def emit(self, direction: str, env) -> None:  # LiveDecoder hook
        if direction != "down":
            return
        if proto.envelope_command(env) != "world.get.block":
            return
        payload = proto.envelope_payload(env)
        kinds = Counter(
            (point.get("_protobuf") or {}).get("f2")
            for block in payload.get("serverPointArr") or ()
            for point in block.get("points") or ()
        )
        found = list(proto.secret_tasks(payload))
        with self._index_lock:
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
        with self._index_lock:
            for uuid in [u for u, seen in self._seen_at.items() if seen < cutoff]:
                self._tasks.pop(uuid, None)
                self._seen_at.pop(uuid, None)
            return list(self._tasks.values())

    def records(self) -> list:
        """Fresh tasks as serialisable dicts, each stamped with `seen_at`.

        `seen_at` (epoch seconds) is when the map last re-sent the tile, so a
        reader can drop records it no longer trusts — see
        `proto.load_fresh_tasks`. Eviction runs here too, so the file never
        carries a tile already past the window.
        """
        cutoff = time.time() - self.stale_after
        with self._index_lock:
            for uuid in [u for u, seen in self._seen_at.items() if seen < cutoff]:
                self._tasks.pop(uuid, None)
                self._seen_at.pop(uuid, None)
            out = []
            for uuid, task in self._tasks.items():
                record = task.as_dict()
                # `steal_count` is what the live view and the task brief call
                # it; keep the `loot_count` alias too so nothing that reads
                # as_dict() breaks.
                record["steal_count"] = record["loot_count"]
                record["seen_at"] = int(self._seen_at.get(uuid, 0))
                out.append(record)
            return out

    def find(self, **criteria) -> list:
        return proto.filter_tasks(self.tasks, **criteria)


def sniff_forever(index: TaskIndex, iface, bpf: str, stop: threading.Event) -> None:
    from scapy.sendrecv import sniff

    try:
        sniff(
            filter=bpf,
            iface=iface,
            prn=lambda pkt: index.feed_packet(pkt, iface),
            store=False,
            # Checked per packet, so a silent interface stays parked here
            # until traffic arrives; the deadline is enforced by the caller,
            # which is why this thread is a daemon.
            stop_filter=lambda _p: stop.is_set(),
        )
    except Exception as exc:  # one dead interface must not end the run
        if not stop.is_set():
            print(f"{C_DIM}iface {iface}: {exc}{C_RESET}", file=sys.stderr)


def main() -> int:
    check_platform()

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--iface", help="pin one interface; omitted = all of them")
    ap.add_argument("--list-ifaces", action="store_true",
                    help="print the interfaces scapy can see, then exit")
    ap.add_argument("--seconds", type=int, default=None,
                    help="how long to listen (default: until Ctrl+C)")
    ap.add_argument("--json", default=None,
                    help="checkpoint every task seen to this file, rewritten "
                         "every --interval seconds (default: no file is written)")
    ap.add_argument("--interval", type=int, default=15,
                    help="seconds between --json checkpoint flushes "
                         "(default 15; lower it to watch the file update)")
    ap.add_argument("--level", type=int, help="only tasks of this level")
    ap.add_argument("--star", action="store_true",
                    help="only starred tasks (cfgId family 6000)")
    ap.add_argument("--can-loot", action="store_true",
                    help="only tasks raidable now (dispatch done, not expired, "
                         "slot free)")
    ap.add_argument("--pending", action="store_true",
                    help="only tasks about to become raidable (dispatch "
                         "finishing within ~10 min)")
    ap.add_argument("--all-tcp", action="store_true",
                    help="capture every TCP port, not just %d — use if the "
                         "game ever moves off it" % GAME_PORT)
    args = ap.parse_args()

    # Redirected to a file, stdout is block-buffered, so a run watched with
    # `tail -f` shows nothing for minutes and reads as hung.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    try:
        from scapy.arch import get_if_list
    except ImportError as exc:
        print(f"{C_ERR}scapy is not installed on this interpreter: {exc}{C_RESET}\n"
              f"  {sys.executable} -m pip install scapy zstandard", file=sys.stderr)
        return 1

    if args.list_ifaces:
        for name in get_if_list():
            print(f"  {name}")
        return 0

    # The endpoint IP is not stable and is dialled without DNS (protocol.md
    # §1), so the port is the only durable narrowing available; --all-tcp is
    # the escape hatch if even that changes.
    bpf = "tcp" if args.all_tcp else f"tcp port {GAME_PORT}"
    targets = [args.iface] if args.iface else [None]

    index = TaskIndex()
    stop = threading.Event()

    print(f"Last War direct capture — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    sink = f" -> {args.json} every {args.interval}s" if args.json else ""
    print(f"{C_DIM}listening {window}{sink} — pan the map, or nothing will "
          f"arrive{C_RESET}\n")

    threads = [threading.Thread(target=sniff_forever,
                                args=(index, iface, bpf, stop), daemon=True)
               for iface in targets]
    for thread in threads:
        thread.start()

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    reported: set = set()
    # None means run until interrupted, so every deadline test has to tolerate
    # not having one.
    deadline = time.time() + args.seconds if args.seconds else None
    heartbeat = time.time()
    # Tracked apart from the heartbeat: the flush period is the user's to set
    # via --interval, while the progress line stays on its own 10s cadence.
    last_flush = time.time()
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(1.0)
            if time.time() - heartbeat >= 10:
                heartbeat = time.time()
                left = (f"…{int(deadline - time.time())}s left"
                        if deadline is not None else "…running")
                print(f"{C_DIM}  {left} — "
                      f"{index.blocks_seen} map response(s), "
                      f"{index.tiles_seen} tile(s), "
                      f"{len(index.tasks)} task(s){C_RESET}")
            if args.json and time.time() - last_flush >= args.interval:
                last_flush = time.time()
                if not dump_tasks(index.records(), args.json):
                    print(f"{C_DIM}  (checkpoint locked, skipped this "
                          f"flush){C_RESET}")
            for task in index.find(level=args.level, star_only=args.star,
                                   can_loot=args.can_loot, pending=args.pending):
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
        stop.set()

    everything = index.tasks
    print(f"\n{len(everything)} task(s) seen, {len(reported)} matched the filter")
    print(f"traffic: {index.delivered} delivered / {index.packets} with payload, "
          f"{index.blocks_seen} map response(s), {index.tiles_seen} tile(s), "
          f"kinds {dict(index.tile_kinds)}")

    if index.delivered and not index.packets:
        print(f"{C_ERR}npcap delivered {index.delivered} packet(s) but none "
              f"decoded as TCP-with-payload.{C_RESET} That is scapy failing to "
              f"map the datalink type — check for an 'Unable to guess datalink "
              f"type' warning above.")
    elif not index.delivered:
        print(f"{C_ERR}No packets at all.{C_RESET} Either the game is not "
              f"running, or npcap cannot see this interface — try "
              f"--list-ifaces and pin one with --iface.")
    elif not index.blocks_seen:
        print(f"{C_ERR}Packets arrived but no map data.{C_RESET} The game "
              f"sends it only while the map scrolls — keep dragging the map "
              f"for the whole run, not just at the start.")
    elif not everything:
        print(f"{C_DIM}Map data arrived but held no secret tasks (no f2=17 "
              f"tiles) — pan over an area that has task markers.{C_RESET}")

    if args.json:
        records = index.records()
        if dump_tasks(records, args.json):
            print(f"{C_OK}wrote {len(records)} task(s) to {args.json}{C_RESET}")
        else:
            print(f"{C_ERR}could not write {args.json} — the file is held by "
                  f"another process.{C_RESET} Close whatever has it open and "
                  f"re-run, or point --json somewhere else.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
