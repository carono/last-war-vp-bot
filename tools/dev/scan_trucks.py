#!/usr/bin/env python3
"""Truck scan with no Wireshark executables in the loop.

The sibling of `secret_task_capture.py`, and built the same way: scapy talks to
the npcap driver directly, so the only Wireshark-related thing needed is the
driver itself — no `dumpcap.exe`, no `tshark.exe`, nothing spawned and nothing
to leak. Protocol logic is imported from lastwar_proto.py, stream reassembly
from live_sniffer.py, and the transport plus the which-server-is-on-screen
election from map_capture.py. This module is a truck index, and nothing else.

    python tools/scan_trucks.py                          stream trucks, print them
                                                         (until Ctrl+C, no file written)
    python tools/scan_trucks.py --seconds 300            stop on a timer instead
    python tools/scan_trucks.py --json out.json          also checkpoint to a file
    python tools/scan_trucks.py --json out.json --interval 3
                                                         flush it every 3s, not 15
    python tools/scan_trucks.py --type gold,sled         only the two fat kinds
    python tools/scan_trucks.py --type 5 --can-loot      tier 5, still robbable
    python tools/scan_trucks.py --level 35               only level-35 trucks
    python tools/scan_trucks.py --not-alliance <id>      hide your own alliance's
    python tools/scan_trucks.py --dump traffic.jsonl     record every decoded
                                                         frame as JSONL too
    python tools/scan_trucks.py --list-ifaces            interfaces, then exit

**This must run under the Windows Python, not the WSL one.** WSL2 sits in a
NAT'd VM whose network namespace is not the host's, so an AF_PACKET socket
there sees WSL's own traffic and never a byte of the game's. From WSL, invoke
the Windows interpreter by path:

    /mnt/c/Python312/python.exe tools/scan_trucks.py --seconds 300

Requirements on that interpreter: npcap (ships with Wireshark), plus
`pip install scapy zstandard`. No Administrator prompt is needed when npcap
was installed with "allow non-administrator capture", which is Wireshark's
normal setup.

Unlike a secret-task scan, this one does **not** need the map to be moving.
Trucks ride the march stream, and the server pushes marches unprompted — so a
run that sits still still fills up, just more slowly and only with what is near
enough for the client to be told about. Panning still helps: it is what makes
the server volunteer the marches of the patch you pan over.

A run follows the player across servers. Every progress line names the server
currently on screen, and moving to another one prints a banner and drops
everything indexed for the old one — its trucks would otherwise keep being
interpolated along routes on a map nobody is looking at.

The colour names are an inference from the cargo ordering and have never been
checked against the screen; see TRUCK_TIER_NAMES in lastwar_proto.py before
trusting one. `--type` takes tier numbers too, which is what the wire actually
says.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, "tools/lib")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET  # noqa: E402
from map_capture import (  # noqa: E402
    MapIndex, add_capture_arguments, check_platform, diagnose,
    dump_records, human_size, level_set, start_capture,
)

# Freshness window for the index and its checkpoint. A truck is only as
# trustworthy as its last sighting: `Truck.position` interpolates along the leg
# the server last described, so one that stopped being re-sent goes on gliding
# down a route it may have left long ago. `arrive_at` catches the truck whose
# whole run has ended, but not the one that merely moved out of view, which is
# what this window is for.
STALE_AFTER_SECONDS = 15 * 60

# The commands that carry trucks. Kept as a set rather than tested one at a
# time so an unlisted command costs a lookup and not a decode: `on_response`
# sees every non-map response the server sends, which is most of the traffic.
TRUCK_COMMANDS = frozenset({
    "push.world.march.world.get.new",
    "push.world.march.new",
    "world.get.march.infos",
})

# ...and the one that takes them away. `push.world.march.del` is how the server
# says a march is over — the truck reached its destination, or was wiped. Both
# mean it is off the map, and without honouring it a finished truck sits in the
# index being announced until the freshness window expires.
MARCH_DEL = "push.world.march.del"

# There is deliberately no default sink. --json is opt-in so an unattended or
# exploratory run cannot quietly overwrite a checkpoint someone else is reading.


class TruckIndex(MapIndex):
    """MapIndex that keeps the trucks off the march stream.

    Trucks are keyed by `(server_id, uuid)`, not by march uuid: a truck is
    re-pushed as it hops from station to station and each hop is a new march,
    so keying on the march would accumulate one stale copy of every truck per
    leg it has travelled. The server id belongs in the key because a uuid is
    only unique within its server — keyed by uuid alone, a truck from the
    server you just left and one from the server you just joined overwrite
    each other.
    """

    def __init__(self, stale_after: float = STALE_AFTER_SECONDS) -> None:
        super().__init__()
        self.stale_after = stale_after
        self._trucks: dict[tuple, proto.Truck] = {}
        # Wall-clock of the last time the server re-sent each truck, so stale
        # ones can be evicted rather than served as if still live.
        self._seen_at: dict[tuple, float] = {}
        # march uuid -> index key, so a `push.world.march.del` naming a march
        # can find the truck riding it. A truck outlives its marches, so this
        # holds every leg seen for it, not just the current one.
        self._by_march: dict[int, tuple] = {}
        # A zero result is ambiguous without this: no march traffic at all
        # reads exactly like march traffic that held no trucks.
        self.marches_seen = 0

    def on_response(self, command, payload) -> None:  # MapIndex hook
        """Called with `_index_lock` held, for every non-map response."""
        if command == MARCH_DEL:
            self._forget_march(payload)
            return
        if command not in TRUCK_COMMANDS:
            return
        self.marches_seen += 1
        now = time.time()
        for truck in proto.trucks(payload or {}):
            key = (truck.server_id, truck.uuid)
            self._trucks[key] = truck
            self._seen_at[key] = now
            if truck.march_uuid:
                self._by_march[truck.march_uuid] = key

    def _forget_march(self, payload) -> None:
        """Drop the truck whose march the server just ended.

        The payload names a march, not a truck, which is why `_by_march`
        exists. A march this run never saw is the normal case — most marches
        are troops, not trucks — so an unknown uuid is silently ignored.
        """
        if not isinstance(payload, dict):
            return
        key = self._by_march.pop(payload.get("uuid"), None)
        if key is not None:
            self._drop(key)

    def on_server_left(self, server: int) -> None:
        """Drop everything indexed for the map nobody is looking at any more.

        Their legs keep interpolating, so those trucks would go on reading as
        robbable at plausible-looking coordinates for the rest of the
        freshness window and the run would keep announcing raids on a server
        the player has already left. Keyed off the *current* server rather than
        the one just left, so a stray third server's trucks go with them.
        """
        self._evict(lambda key: key[0] != self.current_server)

    def _evict(self, doomed) -> None:
        """Drop every indexed truck whose key `doomed(key)` accepts.

        Callers hold `_index_lock`.
        """
        for key in [k for k in self._seen_at if doomed(k)]:
            self._drop(key)

    def _drop(self, key) -> None:
        self._trucks.pop(key, None)
        self._seen_at.pop(key, None)
        for march, owner in [kv for kv in self._by_march.items() if kv[1] == key]:
            self._by_march.pop(march, None)

    @property
    def trucks(self) -> list:
        cutoff = time.time() - self.stale_after
        with self._index_lock:
            self._evict(lambda key: self._seen_at[key] < cutoff)
            return list(self._trucks.values())

    @property
    def current_trucks(self) -> list:
        """Fresh trucks on the server the player is currently looking at.

        Before the first unambiguous map response there is no current server
        yet, and everything seen so far is the best answer available.
        """
        server = self.current_server
        if server is None:
            return self.trucks
        return [t for t in self.trucks if t.server_id == server]

    def records(self) -> list:
        """Fresh trucks as serialisable dicts, each stamped with `seen_at`.

        `seen_at` (epoch seconds) is when the server last re-sent the truck, so
        a reader can drop records it no longer trusts — the same contract
        `proto.load_fresh_tasks` puts on a task checkpoint. Eviction runs here
        too, so the file never carries a truck already past the window.
        """
        cutoff = time.time() - self.stale_after
        with self._index_lock:
            self._evict(lambda key: self._seen_at[key] < cutoff)
            out = []
            for key, truck in self._trucks.items():
                record = truck.as_dict()
                record["seen_at"] = int(self._seen_at.get(key, 0))
                out.append(record)
            return out

    def find(self, **criteria) -> list:
        """Filter the *current* server's trucks — never the one just left."""
        return proto.filter_trucks(self.current_trucks, **criteria)


def truck_types(text: str) -> set:
    """argparse adapter for `--type`, so a typo prints usage not a traceback."""
    try:
        return proto.truck_type_set(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def describe(truck: proto.Truck) -> str:
    """One report line: what it is, where it is, and whether it is worth it."""
    x, y = truck.position
    tag = f"  {C_OK}ROBBABLE{C_RESET}" if truck.can_loot else ""
    owner = truck.owner_name or truck.owner_uid or "?"
    abbr = f"[{truck.alliance_abbr}] " if truck.alliance_abbr else ""
    return (f"{truck.tier_name:>7} lvl {truck.level:>2}  ({x:>4},{y:>4})"
            f"  server {truck.server_id}"
            f"  robbed {truck.rob_times}/{proto.MAX_TRUCK_ROBS}"
            f"  cargo {truck.cargo / 1e6:.1f}M"
            f"  power {truck.power or 0:,}"
            f"  {abbr}{owner} ({truck.owner_uid}){tag}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_capture_arguments(ap)
    ap.add_argument("--json", default=None,
                    help="checkpoint every truck seen to this file, rewritten "
                         "on every tick (default: no file is written)")
    ap.add_argument("--interval", type=int, default=15,
                    help="seconds between processing ticks — each one prints "
                         "the progress line and rewrites --json if given "
                         "(default 15; lower it for tests)")
    ap.add_argument("--type", type=truck_types, metavar="T[,T...]",
                    help="only trucks of these types: white, green, blue, "
                         "purple, gold (aka yellow), sled — or a tier number "
                         "1-5. A comma-separated list matches any of them. "
                         "The colour names are inferred, the numbers are what "
                         "the wire says")
    ap.add_argument("--level", type=level_set, metavar="N[,N...]",
                    help="only trucks of this level; a comma-separated list "
                         "matches any of them (--level 34,35)")
    ap.add_argument("--can-loot", action="store_true",
                    help="only trucks robbable now (still running, and not "
                         "already robbed the full %d times)" % proto.MAX_TRUCK_ROBS)
    ap.add_argument("--not-alliance", metavar="ID", default=None,
                    help="hide trucks belonging to this allianceId — pass "
                         "your own, since you cannot rob your alliance's")
    args = ap.parse_args()
    # After parsing, so `--help` is readable from the WSL interpreter
    # rather than refused by a check about capturing packets.
    check_platform()

    # Redirected to a file, stdout is block-buffered, so a run watched with
    # `tail -f` shows nothing for minutes and reads as hung.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    index = TruckIndex()
    stop, bpf = start_capture(index, args)

    print("Last War truck scan — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    sink = f" -> {args.json} every {args.interval}s" if args.json else ""
    print(f"{C_DIM}listening {window}{sink} — trucks arrive on their own, "
          f"panning the map brings in more{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    reported: set = set()
    # None means run until interrupted, so every deadline test has to tolerate
    # not having one.
    deadline = time.time() + args.seconds if args.seconds else None
    # One timer for the whole periodic tick — the progress line and the
    # checkpoint flush both hang off it, so --interval moves both together.
    last_tick = time.time()
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(1.0)
            # Drained before anything is printed, so the banner separates the
            # old server's lines from the new one's instead of landing amid
            # them.
            for old, new in index.drain_server_changes():
                if old is None:
                    print(f"{C_OK}server {new}{C_RESET} — reading this map\n")
                else:
                    print(f"\n{C_OK}server {old} -> {new}{C_RESET} — dropped "
                          f"everything indexed for {old}; only server {new} "
                          f"is reported from here\n")
                    # The new server's trucks are a fresh set of lines, and a
                    # return trip to `old` has to re-announce what it finds
                    # rather than stay silent on keys reported before the move.
                    reported.clear()
            if time.time() - last_tick >= args.interval:
                last_tick = time.time()
                left = (f"…{int(deadline - time.time())}s left"
                        if deadline is not None else "…running")
                where = (f"server {index.current_server}"
                         if index.current_server is not None
                         else "server unknown yet")
                current = index.current_trucks
                robbable = sum(1 for t in current if t.can_loot)
                print(f"{C_DIM}  {left} — {where}, "
                      f"{index.marches_seen} march response(s), "
                      f"{index.blocks_seen} map response(s), "
                      f"{len(current)} truck(s), "
                      f"{robbable} robbable{C_RESET}")
                if args.json and not dump_records(index.records(), args.json):
                    print(f"{C_DIM}  (checkpoint locked, skipped this "
                          f"flush){C_RESET}")
                if index.transcript is not None:
                    # Flushed here rather than per frame, so a reader tailing
                    # the transcript is one tick behind at worst and the
                    # sniffer thread is never blocked on the disk.
                    index.transcript.flush()
                    print(f"{C_DIM}  transcript: "
                          f"{index.transcript.frames} frame(s), "
                          f"{human_size(index.transcript.size())}{C_RESET}")
            for truck in index.find(types=args.type, level=args.level,
                                    can_loot=args.can_loot,
                                    exclude_alliance=args.not_alliance):
                # Keyed on what the line actually claims, not on the uuid
                # alone. `can_loot` is recomputed against the clock and
                # `rob_times` is a claim about the world that goes stale, so a
                # truck robbed while the scan watches has to say so again
                # rather than be suppressed as already reported. The server id
                # is in the key because a uuid only identifies a truck within
                # its server.
                key = (truck.server_id, truck.uuid, truck.rob_times,
                       truck.can_loot)
                if key in reported:
                    continue
                reported.add(key)
                print(describe(truck))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    everything = index.trucks
    # reported holds (server_id, uuid, rob_times, can_loot), so one truck can
    # appear under several keys as it is robbed; the count is of distinct
    # trucks. It also survives a server switch, so it counts every truck the
    # run ever announced — not just the ones still indexed for the current one.
    matched = len({(server, uuid) for server, uuid, _robs, _loot in reported})
    where = (f" on server {index.current_server}"
             if index.current_server is not None else "")
    print(f"\n{len(everything)} truck(s) seen{where}, "
          f"{matched} matched the filter")
    print(f"traffic: {index.delivered} delivered / {index.packets} with payload, "
          f"{index.marches_seen} march response(s), "
          f"{index.blocks_seen} map response(s)")

    diagnose(index, len(everything),
             "March data arrived but held no trucks — everything on the move "
             "nearby was troops. Pan over an area with trucks on it, or wait: "
             "a truck is only pushed while it is somewhere the client is "
             "told about.")

    if args.json:
        records = index.records()
        if dump_records(records, args.json):
            print(f"{C_OK}wrote {len(records)} truck(s) to {args.json}{C_RESET}")
        else:
            print(f"{C_ERR}could not write {args.json} — the file is held by "
                  f"another process.{C_RESET} Close whatever has it open and "
                  f"re-run, or point --json somewhere else.")

    if index.transcript is not None:
        index.transcript.close()
        lost = (f", {index.transcript.failed} frame(s) could not be serialised"
                if index.transcript.failed else "")
        print(f"{C_OK}wrote {index.transcript.frames} frame(s) "
              f"({human_size(index.transcript.size())}) to "
              f"{index.transcript.path}{C_RESET}{lost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
