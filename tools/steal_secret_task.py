#!/usr/bin/env python3
r"""Rob another player's secret task — «кража секретки» — headless.

What a robbery is
-----------------
A finished hero-dispatch task ("секретка") sitting on someone else's tile can be
robbed three times before its loot slots are full. On the wire that is ONE command,
`hero.dispatch.steal {uuid, targetServer}`, and the account may send five a day
(`GetDispatchSetting("steal_count")`). No marker tap, no popup, no camera move — see
docs/research/secret-task-steal.md.

**The target is a uuid, not a coordinate.** Three ways to name one:

    --uuid U --server S            rob it directly (uuid straight off a map scan)
    --coords X,Y --server S        resolve the uuid first, the way a tap does:
                                   `world.get.detail.new` -> WorldPointDetailManager
    --from-scan tasks.json         every raidable task in a capture checkpoint
                                   (tools/secret_task_capture.py --json), freshest
                                   first, already filtered by `can_loot`
    --from-scan … --star-max       the panel's auto-loot rule: starred tasks only,
                                   and only the highest level among them. No star
                                   in the scan means nothing is robbed at all

Usage (run under the Windows Python so it can reach the warm daemon)
--------------------------------------------------------------------
    C:\Python312\python.exe tools\steal_secret_task.py --status
    C:\Python312\python.exe tools\steal_secret_task.py --coords 470,652 --server 999
    C:\Python312\python.exe tools\steal_secret_task.py --from-scan results\tasks.json
    C:\Python312\python.exe tools\steal_secret_task.py --from-scan results\tasks.json --queue-only

`--queue-only` parks the targets in the game VM and stops, so the panel's Scenarios
tab can then run `actions/steal_secret_task.md` (`TAP steal_secret_task xall`) over
them. Without it this script also presses, one robbery per target, re-reading the
budget between presses.

Nothing here forces a robbery the client would refuse: the daily budget is checked
before every send. The tile-side conditions (three loot slots, the `protect_times`
window, "I already robbed this one") are NOT answerable for an arbitrary uuid — those
stay the server's call and come back as an errorCode, so a refused robbery costs a
queue entry and shows up as an unchanged `todayStealNum` in `--status`.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import coords as coords_fmt  # noqa: E402
import lua_actions  # noqa: E402
import lua_client  # noqa: E402

MARKER = "ACT"

# How long to wait for the `world.get.detail.new` reply before giving up on a
# coordinate. The round trip ran ~0.2-1 s live; three tries at 0.7 s is generous
# without hanging a scripted run on a tile that simply has no task on it.
DETAIL_TRIES, DETAIL_PAUSE = 3, 0.7


def _num(line: str, key: str) -> int:
    """Pull `key=<int>` out of an `ACT …` log line (0 when absent)."""
    if key + "=" not in line:
        return 0
    tail = line.split(key + "=", 1)[1].split()[0]
    try:
        return int(tail)
    except ValueError:
        return 0


def read_status(ev) -> tuple[int, int]:
    """(robberies left today, targets queued)."""
    chunk = ('CS.UnityEngine.Debug.LogError("ACT status left="..tostring(%s)'
             '.." queued="..tostring(%s))'
             % (lua_actions.secret_task_steals_left(), lua_actions.secret_task_queue_len()))
    for ln in ev.run(chunk, MARKER, 1.0):
        if "status left=" in ln:
            return _num(ln, "left"), _num(ln, "queued")
    return 0, 0


def resolve_uuid(ev, x: int, y: int, server: int) -> int:
    """Coordinate -> task uuid, through the same request a marker tap fires.

    Returns 0 when the reply never brought a uuid — an empty tile, a tile the client
    may not query, or a server that did not answer. Deliberately not an exception:
    a sweep over several coordinates should skip the dead one and keep going.
    """
    ev.run(lua_actions.secret_task_request_detail(x, y, server), MARKER, 0.4)
    read = ('CS.UnityEngine.Debug.LogError("ACT detail uuid="..tostring(%s)'
            '.." owner="..tostring(%s))'
            % (lua_actions.secret_task_uuid_at(x, y), lua_actions.secret_task_owner_at(x, y)))
    for _ in range(DETAIL_TRIES):
        time.sleep(DETAIL_PAUSE)
        for ln in ev.run(read, MARKER, 0.4):
            if "detail uuid=" in ln:
                uuid = _num(ln, "uuid")
                if uuid:
                    return uuid
    return 0


def _label(task) -> str:
    return ("%s%s lvl %d %d/3 looted"
            % ("*" if task.starred else " ",
               coords_fmt.fmt(task.x, task.y, task.server_id),
               task.level, task.loot_count))


def targets_from_scan(path: str, limit: int, star_max: bool = False,
                      say=print) -> list[tuple[int, int, str]]:
    """Raidable tasks from a capture checkpoint, as (uuid, server, label).

    Freshness and raidability are the checkpoint reader's own rules — `load_fresh_tasks`
    drops anything not re-seen in this scan window and recomputes `can_loot` against the
    current clock, so a file written an hour ago cannot smuggle a stale tile in here.

    `star_max` is the panel's auto-loot rule: **starred tasks only**, and among those
    only the highest level actually found. No star in the scan means no target at all —
    the caller does nothing rather than settling for an ordinary task, which is the
    whole point of the button (a robbery spent on a level-5 plain tile is one that a
    level-7 star cannot have later that day).

    `starred` is `cfgId` family 6000 minus the `99` class — the rule and the evidence
    behind it live in `STAR_TASK_FAMILIES` (docs/research/protocol.md §7). It is the one
    property the game does not state outright, so a star here is the decoder's reading,
    not the game's word.
    """
    sys.path.insert(0, os.path.join(_HERE, "lib"))
    import lastwar_proto as proto

    tasks = proto.load_fresh_tasks(path)
    raidable = [t for t in tasks if t.can_loot]
    if star_max:
        starred = [t for t in raidable if t.starred]
        if not starred:
            say("no starred task in the scan (%d raidable, none starred) — nothing to do"
                % len(raidable))
            return []
        top = max(t.level for t in starred)
        raidable = [t for t in starred if t.level == top]
        say("starred targets: %d at level %d (the highest found)" % (len(raidable), top))
    raidable.sort(key=lambda t: (-t.free_slots, -t.level))
    return [(t.uuid, t.server_id, _label(t)) for t in raidable[:limit]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uuid", type=int, help="task uuid to rob")
    ap.add_argument("--coords", help="tile 'X,Y' whose task uuid should be resolved first")
    ap.add_argument("--server", type=int, help="the task's server (targetServer)")
    ap.add_argument("--from-scan", metavar="PATH",
                    help="capture checkpoint (tools/secret_task_capture.py --json)")
    ap.add_argument("--limit", type=int, default=5,
                    help="most targets to take from --from-scan (default 5)")
    ap.add_argument("--star-max", action="store_true",
                    help="with --from-scan: starred tasks only, and only the highest "
                         "level found. No star in the scan = nothing is robbed")
    ap.add_argument("--queue-only", action="store_true",
                    help="park the targets in the game VM and stop (no robbery)")
    ap.add_argument("--status", action="store_true",
                    help="print the daily budget and the queue, then stop")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ev = lua_client.get_evaluator()

    if args.status:
        left, queued = read_status(ev)
        print("robberies left today: %d   targets queued: %d" % (left, queued))
        return 0

    targets: list[tuple[int, int, str]] = []
    if args.from_scan:
        if not os.path.exists(args.from_scan):
            print("no scan checkpoint at %s — run the capture (panel: «Мониторинг "
                  "секреток») while the map moves" % args.from_scan)
            return 1
        targets = targets_from_scan(args.from_scan, args.limit, star_max=args.star_max)
        if not targets:
            # With --star-max this is the ordinary "no star on screen" answer, not a
            # failure: the button is supposed to do nothing rather than rob a plain
            # task. targets_from_scan has already said which case it was.
            if not args.star_max:
                print("no raidable task in %s — scan again while panning the map"
                      % args.from_scan)
            return 0 if args.star_max else 1
    elif args.coords:
        if args.server is None:
            ap.error("--coords needs --server")
        try:
            x_text, _, y_text = args.coords.partition(",")
            x, y = int(x_text), int(y_text)
        except ValueError:
            ap.error("--coords wants 'X,Y'")
        uuid = resolve_uuid(ev, x, y, args.server)
        if not uuid:
            print("no task uuid came back for %s — is there a secret task on that tile?"
                  % coords_fmt.fmt(x, y, args.server))
            return 1
        targets = [(uuid, args.server, coords_fmt.fmt(x, y, args.server))]
    elif args.uuid:
        if args.server is None:
            ap.error("--uuid needs --server")
        targets = [(args.uuid, args.server, "uuid %d" % args.uuid)]
    else:
        ap.error("name a target: --uuid, --coords or --from-scan (or ask for --status)")

    left, _ = read_status(ev)
    print("robberies left today: %d" % left)
    for uuid, server, label in targets:
        print("  target %-28s uuid=%d srv=%d" % (label, uuid, server))

    ev.run(lua_actions.secret_task_queue_set([(u, s) for u, s, _ in targets]), MARKER, 0.6)
    if args.queue_only:
        _, queued = read_status(ev)
        print("queued %d target(s) — run actions/steal_secret_task.md to spend them"
              % queued)
        return 0

    if not left:
        print("the day's robberies are spent — the queue keeps the targets for tomorrow")
        return 1

    robbed = 0
    for _ in range(min(len(targets), left)):
        ev.run(lua_actions.steal_next_secret_task(), MARKER, 2.0)
        now_left, queued = read_status(ev)
        if now_left < left:
            robbed += 1
        left = now_left
        if not left or not queued:
            break

    print("sent %d robbery/robberies; %d left today" % (robbed, left))
    if robbed < len(targets):
        print("note: a target the server refused (expired, slots full, already robbed "
              "by you) leaves todayStealNum unchanged — the client shows the tip.")
    return 0 if robbed else 1


if __name__ == "__main__":
    raise SystemExit(main())
