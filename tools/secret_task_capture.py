#!/usr/bin/env python3
"""Secret-task capture with no Wireshark executables in the loop.

`live_tshark.py` drives `dumpcap.exe` as a subprocess and reads pcap off its
stdout. This module talks to the npcap driver directly through scapy, so the
only Wireshark-related thing it needs is the npcap driver itself — no
`dumpcap.exe`, no `tshark.exe`, nothing spawned and nothing to leak.

Protocol logic is imported from lastwar_proto.py, the stream reassembly from
live_sniffer.py, and the transport plus the which-server-is-on-screen election
from map_capture.py — none of it is reimplemented here.

This module is a secret-task index — and, since #1289, the process that CARRIES
the world one as well (`--world-json`): mines off the same map responses, player
trucks and alliance trains off the march stream. That is a second listener and
deliberately not a second capture: two npcap captures over one interface starve
each other, and the starved one reads exactly like a deaf client (044c19f). See
`world_index.py`.

    python tools/secret_task_capture.py                       stream tasks, print them
                                                              (until Ctrl+C, no file written)
    python tools/secret_task_capture.py --seconds 300         stop on a timer instead
    python tools/secret_task_capture.py --json out.json       also checkpoint to a file
    python tools/secret_task_capture.py --json out.json --interval 3
                                                              flush it every 3s, not 15
    python tools/secret_task_capture.py --world-json w.json    ALSO index the mines,
                                                              trucks and alliance trains
    python tools/secret_task_capture.py --level 7 --can-loot  only raidable level-7s
    python tools/secret_task_capture.py --level 7,8           level 7 or level 8
    python tools/secret_task_capture.py --dump traffic.jsonl  record every decoded
                                                              frame as JSONL too
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

_HERE = os.path.dirname(os.path.abspath(__file__))
# Absolute, not "tools/lib": the shared modules resolve the same no matter what
# cwd the launcher (panel, daemon, shell) started us in.
sys.path.insert(0, os.path.join(_HERE, "lib"))
sys.path.insert(0, _HERE)

import coords  # noqa: E402  (canonical #server X:x Y:y token — one format for every script)
import lastwar_proto as proto  # noqa: E402
import share_marks  # noqa: E402  (the «already shared» mark this capture also writes)
import world_index  # noqa: E402  (the second listener, in this process — see --world-json)
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET  # noqa: E402
from map_capture import (  # noqa: E402
    MapIndex, ProgressTicker, add_capture_arguments, check_platform, diagnose,
    dump_records as dump_tasks, human_size, level_set, start_capture,
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

    #: The second listener, off by default — a class attribute so an index built for a
    #: test (or by anything that does not go through `__init__`) is a plain task index
    #: rather than one that raises the first time the server says something.
    world = None

    def __init__(self, stale_after: float = STALE_AFTER_SECONDS,
                 shared_json: str | None = None, world=None) -> None:
        super().__init__()
        self.stale_after = stale_after
        #: THE SECOND LISTENER, IN THIS PROCESS (#1289). Mines, trucks and
        #: alliance trains are decoded off the very frames this index is already
        #: being handed — never off a second capture, which on one interface gets
        #: a trickle and reads exactly like a deaf client (044c19f). None when
        #: `--world-json` was not given, and then nothing here costs anything.
        self.world = world
        self._tasks: dict[tuple, proto.SecretTask] = {}
        # Wall-clock of the last time the map re-sent each task, so stale ones
        # can be evicted rather than served as if still live.
        self._seen_at: dict[tuple, float] = {}
        # Where to record «this task has already been shared with the alliance»
        # (#1245), or None to record nothing. See `on_response`.
        self._shared_json = shared_json
        self.shares_marked = 0

    def on_blocks(self, payload, blocks, now: float) -> None:
        for task in proto.secret_tasks(payload):
            key = (task.server_id, task.uuid)
            self._tasks[key] = task
            self._seen_at[key] = now
        if self.world is not None:
            self.world.on_blocks(payload, blocks, now)

    def on_response(self, command, payload) -> None:
        """Every non-map answer — which is where the game announces a share.

        A secret task is forwarded to the alliance from two places and this capture
        cannot tell them apart, which is exactly why it listens: the panel's own
        «Поделиться» and the client's share button both end as the same broadcast, so
        a tile shared by hand in the game is marked on the panel's list without the
        panel having done anything (#1245).

        Both share commands count. `push.alliance.share.mission.add` is the live
        broadcast; `get.alliance.share.mission.list` is the standing list the client
        pulls on login, and it is the only source for the shares that happened while
        nothing here was running. Neither is an event a robbery should replay — the
        auto-loot listener deliberately ignores the list for that reason — but as a
        record of «this one has been shared» the backlog is precisely what is wanted.

        `_index_lock` is held; the write is one appended line (`share_marks`).

        It is also where the world listener hears the MARCH stream, which is what
        trucks and alliance trains ride — they are not tiles and never appear in
        a map block (#1289).
        """
        if self.world is not None:
            self.world.on_response(command, payload)
        if not self._shared_json or command not in proto.SHARE_MISSION_COMMANDS:
            return
        self.shares_marked += share_marks.mark_missions(
            self._shared_json, proto.share_missions(command, payload))

    def on_server_left(self, server: int) -> None:
        """Drop everything indexed for the map nobody is looking at any more.

        Its dispatch timers keep ticking, so those tiles go on reading as
        LOOTABLE for the rest of the freshness window and the run keeps
        announcing raids on a server the player has already left. Keyed off
        the *current* server rather than the one just left, so a stray third
        server's tiles go with them.
        """
        self._evict(lambda key: key[0] != self.current_server)
        if self.world is not None:
            self.world.on_server_left(server, self.current_server)

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


def build_parser() -> argparse.ArgumentParser:
    """This capture's command line, on its own — so it can be read without running.

    A separate function because the panel spawns this child and the two sides drift:
    #1326 was a whole monitor that never started, because the caller had learned a flag
    the tool had not (`--shared-json`, on the ghost twin). A parser a test can build is
    what lets the spawn be checked against what the child really accepts.
    """
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
    ap.add_argument("--shared-json", default=None, metavar="PATH",
                    help="append a mark to this file for every secret task the "
                         "game says has been shared with the alliance — the "
                         "live broadcast and the list pulled on login alike "
                         "(default: shares are not recorded)")
    ap.add_argument("--world-json", default=None, metavar="PATH",
                    help="ALSO index the rest of the map into this file — the "
                         "resource mines off the same map responses, and the "
                         "player trucks and alliance trains off the march "
                         "stream. A second listener in THIS process: two "
                         "captures on one interface starve each other "
                         "(default: the world is not indexed)")
    ap.add_argument("--world-max", type=int, default=world_index.DEFAULT_MAX_PER_KIND,
                    metavar="N",
                    help=f"how many of each kind the world checkpoint may carry "
                         f"(default {world_index.DEFAULT_MAX_PER_KIND}); a whole-"
                         f"server lap finds about nine thousand mines. What is "
                         f"dropped is reported, never silently cut")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    # After parsing, so `--help` is readable from the WSL interpreter
    # rather than refused by a check about capturing packets.
    check_platform()

    # Redirected to a file, stdout is block-buffered, so a run watched with
    # `tail -f` shows nothing for minutes and reads as hung.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    world = (world_index.WorldIndex(max_per_kind=args.world_max)
             if args.world_json else None)
    index = TaskIndex(shared_json=args.shared_json, world=world)
    stop, bpf = start_capture(index, args)

    print("Last War direct capture — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    sink = f" -> {args.json} every {args.interval}s" if args.json else ""
    print(f"{C_DIM}listening {window}{sink} — pan the map, or nothing will "
          f"arrive{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    reported: set = set()
    # A secret tile is a one-shot steal target. The moment anyone raids a slot
    # its loot_count ticks up, and without this that higher count reads as a
    # brand-new world state and re-announces the tile as if freshly LOOTABLE —
    # the exact double-detection this guards against. `stolen` holds the
    # (server_id, uuid) of every tile whose count has risen since we first saw
    # it; once in here a tile is announced no more, even if a free slot remains
    # and `can_loot` still reads true. `first_loot` is that first-seen count,
    # the baseline a rise is measured against. Both deliberately outlive a
    # server switch (unlike `reported`, cleared below): a tile someone has
    # already stolen stays stolen on a return trip.
    stolen: set = set()
    first_loot: dict = {}
    # None means run until interrupted, so every deadline test has to tolerate
    # not having one.
    deadline = time.time() + args.seconds if args.seconds else None
    # One timer for the whole periodic tick. Everything that works on the
    # accumulated index rather than on a single freshly-arrived tile — the
    # progress line and the checkpoint flush — happens here, on the period the
    # user set. Splitting these apart is what made --interval look broken: the
    # file honoured it while the progress line stayed on its own hardcoded 10s.
    last_tick = time.time()
    # The progress line repeats every tick even when nothing moved, which is
    # pure noise in a log (and floods the panel). Print it only when the data
    # it reports actually changed — the countdown is deliberately NOT part of
    # the signature, since it changes every tick and would defeat the dedup —
    # plus the rare heartbeat `ProgressTicker` keeps, so an idle capture is
    # alive rather than silent. The checkpoint/transcript flushes below still
    # run every tick regardless; only the console line is suppressed.
    ticker = ProgressTicker()
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
                # Signature of the reported data, sans the countdown, so an
                # unchanged tick stays silent.
                changed = ticker.due((index.current_server, index.blocks_seen,
                                      index.tiles_seen, len(index.current_tasks),
                                      index.starred_awaiting, index.shares_marked))
                if changed:
                    left = (f"…{int(deadline - time.time())}s left"
                            if deadline is not None else "…running")
                    where = (f"server {index.current_server}"
                             if index.current_server is not None
                             else "server unknown yet")
                    # The share tally is only ever mentioned once there is one:
                    # a capture run without --shared-json must read exactly as
                    # it always did.
                    shares = (f", {index.shares_marked} share(s) marked"
                              if index.shares_marked else "")
                    print(f"{C_DIM}  {left} — {where}, "
                          f"{index.blocks_seen} map response(s), "
                          f"{index.tiles_seen} tile(s), "
                          f"{len(index.current_tasks)} task(s), "
                          f"{index.starred_awaiting} star(s) still on "
                          f"timer{shares}{C_RESET}")
                if args.json and not dump_tasks(index.records(), args.json):
                    print(f"{C_DIM}  (checkpoint locked, skipped this "
                          f"flush){C_RESET}")
                if world is not None:
                    held = world.counts()
                    if not dump_tasks(world.records(), args.world_json):
                        print(f"{C_DIM}  (world checkpoint locked, skipped this "
                              f"flush){C_RESET}")
                    elif changed:
                        # Said on the same tick as the task line, and only when
                        # that one is speaking, so a quiet capture stays quiet.
                        cut = ", ".join(f"{n} {k} dropped to the cap"
                                        for k, n in world.dropped.items() if n)
                        print(f"{C_DIM}  world: {held['mines']} mine(s), "
                              f"{held['trucks']} truck(s), "
                              f"{held['trains']} train(s), "
                              f"{held['players']} player(s)"
                              f"{' — ' + cut if cut else ''}{C_RESET}")
                if index.transcript is not None:
                    # Flushed here rather than per frame, so a reader tailing
                    # the transcript is one tick behind at worst and the
                    # sniffer thread is never blocked on the disk.
                    index.transcript.flush()
                    # Only report transcript growth when the progress line
                    # itself printed, so a quiet capture stays quiet.
                    if changed:
                        print(f"{C_DIM}  transcript: "
                              f"{index.transcript.frames} frame(s), "
                              f"{human_size(index.transcript.size())}{C_RESET}")
            for task in index.find(level=args.level, star_only=args.star,
                                   can_loot=args.can_loot, pending=args.pending):
                tile = (task.server_id, task.uuid)
                # A tile already retired as stolen never speaks again.
                if tile in stolen:
                    continue
                # A rise above the first-seen loot count means a slot was raided
                # while we watched — someone stole this tile. Retire it so the
                # higher count cannot re-announce the same tile as if new; the
                # earlier state was already reported once, which is enough.
                baseline = first_loot.setdefault(tile, task.loot_count)
                if task.loot_count > baseline:
                    stolen.add(tile)
                    continue
                # Keyed on what the line actually says, not on the uuid alone.
                # `can_loot` and `pending` are recomputed against the clock, so
                # a task walks PENDING -> LOOTABLE on its own; keying by uuid
                # printed it once while still PENDING and then suppressed the
                # LOOTABLE moment forever — the one line a raid decision needs.
                # Loot count is deliberately NOT in the key: a count that rose
                # means the tile was stolen, and that is handled above by
                # retiring it, not by re-announcing it. The server id is in the
                # key because a uuid only identifies a tile within its server.
                state = ("lootable" if task.can_loot
                         else "pending" if task.pending else "seen")
                key = (task.server_id, task.uuid, state)
                if key in reported:
                    continue
                reported.add(key)
                star = " *" if task.starred else "  "
                # NO OWNER UID ON THE LINE (#1293). It used to be printed for a
                # starred tile — «whose base you are about to raid» — and the panel
                # logs every line this child prints, so somebody else's account id
                # ended up in a file people send each other when something goes
                # wrong. It is still decoded and still written to the checkpoint,
                # which is what the tab and the robbery read; only the printed line
                # loses it, and the coordinate on that line is what a person acts on
                # anyway.
                if task.pending:
                    tag = f"  {C_OK}PENDING{C_RESET}"
                elif task.can_loot:
                    tag = f"  {C_OK}LOOTABLE{C_RESET}"
                else:
                    tag = ""
                print(f"{star} lvl {task.level:>2}  {coords.fmt(task.x, task.y, task.server_id)}"
                      f"  steal {task.loot_count}/3"
                      f"  family {task.family}  cfg {task.cfg_id}{tag}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    everything = index.tasks
    # reported holds (server_id, uuid, state), so one task can appear under
    # several keys as it walks PENDING -> LOOTABLE; the count is of distinct
    # tasks. It also survives a server switch, so it counts every task the run
    # ever announced — not just the ones still indexed for the current server.
    matched = len({(server, uuid) for server, uuid, _state in reported})
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

    if world is not None:
        held = world.counts()
        if dump_tasks(world.records(), args.world_json):
            print(f"{C_OK}wrote {held['mines']} mine(s), {held['trucks']} truck(s), "
                  f"{held['trains']} train(s) and {held['players']} player(s) to "
                  f"{args.world_json}{C_RESET}")
        else:
            print(f"{C_ERR}could not write {args.world_json} — the file is held "
                  f"by another process.{C_RESET}")

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
