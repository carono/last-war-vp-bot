#!/usr/bin/env python3
"""Secret-task capture with no Wireshark executables in the loop.

`live_tshark.py` drives `dumpcap.exe` as a subprocess and reads pcap off its
stdout. This module talks to the npcap driver directly through scapy, so the
only Wireshark-related thing it needs is the npcap driver itself — no
`dumpcap.exe`, no `tshark.exe`, nothing spawned and nothing to leak.

Protocol logic is imported from lastwar_proto.py, the stream reassembly from
live_sniffer.py, and the transport plus the which-server-is-on-screen election
from map_capture.py — none of it is reimplemented here. This module is a
secret-task index, and nothing else.

    python tools/secret_task_capture.py                       stream tasks, print them
                                                              (until Ctrl+C, no file written)
    python tools/secret_task_capture.py --seconds 300         stop on a timer instead
    python tools/secret_task_capture.py --json out.json       also checkpoint to a file
    python tools/secret_task_capture.py --json out.json --interval 3
                                                              flush it every 3s, not 15
    python tools/secret_task_capture.py --level 7 --can-loot  only raidable level-7s
    python tools/secret_task_capture.py --level 7,8           level 7 or level 8
    python tools/secret_task_capture.py --list-ifaces         interfaces, then exit

**This must run under the Windows Python, not the WSL one.** WSL2 sits in a
NAT'd VM whose network namespace is not the host's, so an AF_PACKET socket
there sees WSL's own traffic and never a byte of the game's. From WSL, invoke
the Windows interpreter by path:

    /mnt/c/Python312/python.exe tools/secret_task_capture.py --seconds 300

Requirements on that interpreter: npcap (ships with Wireshark), plus
`pip install scapy zstandard`. No Administrator prompt is needed when npcap
was installed with "allow non-administrator capture", which is Wireshark's
normal setup.

The game only sends `world.get.block` while the map is moving, so a run that
reports zero map responses means nobody was panning — not that the capture
is broken. The counters below are there to tell those two apart.

A run follows the player across servers. Every progress line names the server
currently on screen, and moving to another one prints a banner and drops
everything indexed for the old one — its dispatch timers would otherwise keep
running and go on announcing raids on a map nobody is looking at.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET  # noqa: E402
from map_capture import (  # noqa: E402
    MapIndex, add_capture_arguments, check_platform, diagnose,
    dump_records as dump_tasks, level_set, start_capture,
)

# Freshness window for the task index and its checkpoint, shared with the
# reader (proto.load_fresh_tasks) so writer and reader agree on "current". See
# proto.TASK_FRESH_SECONDS for why a tile not re-sent within it is untrustworthy.
STALE_AFTER_SECONDS = proto.TASK_FRESH_SECONDS

# There is deliberately no default sink. --json is opt-in so an unattended or
# exploratory run cannot quietly overwrite a checkpoint someone else is reading.


class TaskIndex(MapIndex):
    """MapIndex that keeps the secret tasks instead of printing commands.

    Tasks are keyed by `(server_id, uuid)` because the client does not
    debounce: panning the map re-sends regions it already asked about, so a
    repeat has to refresh a record rather than append a duplicate. The
    refreshed tile carries the newer loot list, which is the one a raid
    decision should use. The server id belongs in the key because a uuid is
    only unique within its server — keyed by uuid alone, a tile from the
    server you just left and one from the server you just joined overwrite
    each other.
    """

    def __init__(self, stale_after: float = STALE_AFTER_SECONDS) -> None:
        super().__init__()
        self.stale_after = stale_after
        self._tasks: dict[tuple, proto.SecretTask] = {}
        # Wall-clock of the last time the map re-sent each task, so stale ones
        # can be evicted rather than served as if still live.
        self._seen_at: dict[tuple, float] = {}

    def on_blocks(self, payload, blocks, now: float) -> None:
        for task in proto.secret_tasks(payload):
            key = (task.server_id, task.uuid)
            self._tasks[key] = task
            self._seen_at[key] = now

    def on_server_left(self, server: int) -> None:
        """Drop everything indexed for the map nobody is looking at any more.

        Its dispatch timers keep ticking, so those tiles go on reading as
        LOOTABLE for the rest of the freshness window and the run keeps
        announcing raids on a server the player has already left. Keyed off
        the *current* server rather than the one just left, so a stray third
        server's tiles go with them.
        """
        self._evict(lambda key: key[0] != self.current_server)

    def _evict(self, doomed) -> None:
        """Drop every indexed task whose key `doomed(key)` accepts.

        Callers hold `_index_lock`.
        """
        for key in [k for k in self._seen_at if doomed(k)]:
            self._tasks.pop(key, None)
            self._seen_at.pop(key, None)

    @property
    def tasks(self) -> list:
        cutoff = time.time() - self.stale_after
        with self._index_lock:
            self._evict(lambda key: self._seen_at[key] < cutoff)
            return list(self._tasks.values())

    @property
    def current_tasks(self) -> list:
        """Fresh tasks on the server the player is currently looking at.

        Before the first unambiguous map response there is no current server
        yet, and everything seen so far is the best answer available.
        """
        server = self.current_server
        if server is None:
            return self.tasks
        return [t for t in self.tasks if t.server_id == server]

    def records(self) -> list:
        """Fresh tasks as serialisable dicts, each stamped with `seen_at`.

        `seen_at` (epoch seconds) is when the map last re-sent the tile, so a
        reader can drop records it no longer trusts — see
        `proto.load_fresh_tasks`. Eviction runs here too, so the file never
        carries a tile already past the window.
        """
        cutoff = time.time() - self.stale_after
        with self._index_lock:
            self._evict(lambda key: self._seen_at[key] < cutoff)
            out = []
            for key, task in self._tasks.items():
                record = task.as_dict()
                # `steal_count` is what the live view and the task brief call
                # it; keep the `loot_count` alias too so nothing that reads
                # as_dict() breaks.
                record["steal_count"] = record["loot_count"]
                record["seen_at"] = int(self._seen_at.get(key, 0))
                out.append(record)
            return out

    def find(self, **criteria) -> list:
        """Filter the *current* server's tasks — never the one just left."""
        return proto.filter_tasks(self.current_tasks, **criteria)

    @property
    def starred_awaiting(self) -> int:
        """Starred tiles on the current server whose timer is not near done.

        Statistics only — nothing acts on these, they are too far out. It is
        the count that answers "how many stars is this map holding", which the
        LOOTABLE/PENDING lines cannot: those only ever mention a tile once its
        dispatch is within ten minutes of finishing, so a map full of fresh
        stars and a map with none look identical until the first one matures.
        """
        return sum(1 for task in self.current_tasks
                   if task.starred and task.awaiting)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_capture_arguments(ap)
    ap.add_argument("--json", default=None,
                    help="checkpoint every task seen to this file, rewritten "
                         "on every tick (default: no file is written)")
    ap.add_argument("--interval", type=int, default=15,
                    help="seconds between processing ticks — each one prints "
                         "the progress line and rewrites --json if given "
                         "(default 15; lower it for tests)")
    ap.add_argument("--level", type=level_set, metavar="N[,N...]",
                    help="only tasks of this level; a comma-separated list "
                         "matches any of them (--level 7,8)")
    ap.add_argument("--star", action="store_true",
                    help="only starred tasks (cfgId family 6000)")
    ap.add_argument("--can-loot", action="store_true",
                    help="only tasks raidable now (dispatch done, not expired, "
                         "slot free)")
    ap.add_argument("--pending", action="store_true",
                    help="only tasks about to become raidable (dispatch "
                         "finishing within ~10 min); combine with --can-loot "
                         "for either")
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

    index = TaskIndex()
    stop, bpf = start_capture(index, args)

    print("Last War direct capture — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    sink = f" -> {args.json} every {args.interval}s" if args.json else ""
    print(f"{C_DIM}listening {window}{sink} — pan the map, or nothing will "
          f"arrive{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    reported: set = set()
    # None means run until interrupted, so every deadline test has to tolerate
    # not having one.
    deadline = time.time() + args.seconds if args.seconds else None
    # One timer for the whole periodic tick. Everything that works on the
    # accumulated index rather than on a single freshly-arrived tile — the
    # progress line and the checkpoint flush — happens here, on the period the
    # user set. Splitting these apart is what made --interval look broken: the
    # file honoured it while the progress line stayed on its own hardcoded 10s.
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
                    # The new server's tasks are a fresh set of lines, and a
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
                print(f"{C_DIM}  {left} — {where}, "
                      f"{index.blocks_seen} map response(s), "
                      f"{index.tiles_seen} tile(s), "
                      f"{len(index.current_tasks)} task(s), "
                      f"{index.starred_awaiting} star(s) still on "
                      f"timer{C_RESET}")
                if args.json and not dump_tasks(index.records(), args.json):
                    print(f"{C_DIM}  (checkpoint locked, skipped this "
                          f"flush){C_RESET}")
            for task in index.find(level=args.level, star_only=args.star,
                                   can_loot=args.can_loot, pending=args.pending):
                # Keyed on what the line actually says, not on the uuid alone.
                # `can_loot` and `pending` are recomputed against the clock, so
                # a task walks PENDING -> LOOTABLE on its own; keying by uuid
                # printed it once while still PENDING and then suppressed the
                # LOOTABLE moment forever — the one line a raid decision needs.
                # Loot count is in the key for the same reason: "steal 0/3" is
                # a claim about the world that goes stale. The server id is in
                # it because a uuid only identifies a tile within its server.
                state = ("lootable" if task.can_loot
                         else "pending" if task.pending else "seen")
                key = (task.server_id, task.uuid, state, task.loot_count)
                if key in reported:
                    continue
                reported.add(key)
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
    # reported holds (server_id, uuid, state, loot_count), so one task can
    # appear under several keys as it changes; the count is of distinct tasks.
    # It also survives a server switch, so it counts every task the run ever
    # announced — not just the ones still indexed for the current server.
    matched = len({(server, uuid) for server, uuid, _state, _loot in reported})
    where = (f" on server {index.current_server}"
             if index.current_server is not None else "")
    # Read before the summary prints, so the count belongs to the same moment
    # as the task list rather than to a clock tick later.
    awaiting = index.starred_awaiting
    print(f"\n{len(everything)} task(s) seen{where}, "
          f"{matched} matched the filter, "
          f"{awaiting} starred task(s) still on timer (>10 min out)")
    print(f"traffic: {index.delivered} delivered / {index.packets} with payload, "
          f"{index.blocks_seen} map response(s), {index.tiles_seen} tile(s), "
          f"kinds {dict(index.tile_kinds)}")

    diagnose(index, len(everything),
             "Map data arrived but held no secret tasks (no f2=17 tiles) — "
             "pan over an area that has task markers.")

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
