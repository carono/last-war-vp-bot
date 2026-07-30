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
    --from-vm                      every raidable alliance task read straight from the
                                   live game VM (no capture, no map panning) — the
                                   panel's auto-loot source; combine with --from-scan
                                   to also take enemy tiles the sweep panned over
    --from-scan tasks.json         every raidable task in a capture checkpoint
                                   (tools/secret_task_capture.py --json), freshest
                                   first, already filtered by `can_loot`
    --from-scan … --star-max       the panel's auto-loot rule: starred tasks only,
                                   and only at ONE level — the top of the range
                                   below. No star there means nothing is robbed
    --from-scan … --level-min N    hard level gate («уровень от / до» in the panel):
                --level-max M      levels outside it are not targets at all, and
                                   with --star-max the target level IS --level-max
                                   («от 1 до 7» robs 7s and leaves a 6 alone)

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
                      level_min: int | None = None, level_max: int | None = None,
                      say=print) -> list[tuple[int, int, str]]:
    """Raidable tasks from a capture checkpoint, as (uuid, server, label).

    Freshness and raidability are the checkpoint reader's own rules — `load_fresh_tasks`
    drops anything not re-seen in this scan window and recomputes `can_loot` against the
    current clock, so a file written an hour ago cannot smuggle a stale tile in here.

    `level_min` / `level_max` bound which levels may be robbed at all — the panel's
    «уровень от / до». They are applied FIRST, before `star_max` picks its target
    level, so the range is a hard gate and not a preference. Either end may be None.

    `star_max` is the panel's auto-loot rule: **starred tasks only**, and only at ONE
    level — `level_max`, the top of the configured range. «от 1 до 7» means level 7
    and nothing else: a level-6 star is not robbed even when it is the only star on
    the map, because the day's five robberies are the scarce thing and one spent on a
    6 is one a 7 cannot have until the daily reset. Without `level_max` no target
    level is configured, so it falls back to the highest level actually found in
    range.

    No star at the target level means no target at all — the caller does nothing
    rather than settling for a lower one, which is the whole point of the rule.

    `starred` is `cfgId` family 6000 minus the `99` class — the rule and the evidence
    behind it live in `STAR_TASK_FAMILIES` (docs/research/protocol.md §7). It is the one
    property the game does not state outright, so a star here is the decoder's reading,
    not the game's word.
    """
    sys.path.insert(0, os.path.join(_HERE, "lib"))
    import lastwar_proto as proto

    tasks = proto.load_fresh_tasks(path)
    return _select_targets(tasks, limit, star_max=star_max,
                           level_min=level_min, level_max=level_max, say=say)


def targets_from_vm(ev, limit: int, star_max: bool = False,
                    level_min: int | None = None, level_max: int | None = None,
                    say=print) -> list[tuple[int, int, str]]:
    """Raidable alliance secret tasks read straight from the live Lua VM, freshest rule.

    Same result shape and same selection rule as `targets_from_scan`, but the source is
    `DataCenter.ActDispatchTaskDataManager.allianceTask` (see project_secret_task_list),
    read through the warm daemon — no pcap, no map panning, no checkpoint. A member's
    shared secret task is in that table the moment the push lands, so this is what lets
    the panel's auto-loot react to a new raidable star in a second or two instead of
    waiting for the map sweep to pan over the tile and the next capture flush.

    The VM already gives the raid-gate answer for the two conditions it can (dispatch
    finished, not expired, a slot free); `can_loot` is recomputed here against the local
    clock all the same, so a record that matured or expired between the read and now is
    re-judged rather than trusted frozen.
    """
    tasks = _vm_raidable_tasks(ev)
    return _select_targets(tasks, limit, star_max=star_max,
                           level_min=level_min, level_max=level_max, say=say)


def _vm_raidable_tasks(ev) -> list:
    """Parse the `ACT VT …` lines of `secret_task_raidable_alliance()` into SecretTasks.

    The exact loot slots (who has already robbed the tile) are not on the wire here —
    only the count is — so `looted_by` is filled with that many placeholder entries.
    That is enough for `loot_count` / `free_slots` / `can_loot`; whether *I* am already
    in the list is the server's call at steal time, the same as every other route.
    """
    sys.path.insert(0, os.path.join(_HERE, "lib"))
    import lastwar_proto as proto

    out = []
    for ln in ev.run(lua_actions.secret_task_raidable_alliance(), MARKER, 1.1):
        body = ln[4:] if ln.startswith("ACT ") else ln
        if not body.startswith("VT "):
            continue
        rec = {}
        for tok in body[3:].split(" "):
            key, sep, value = tok.partition("=")
            if sep:
                rec[key] = value
        try:
            cfg_id = int(rec.get("cfg", "0"))
            family, level, _variant = proto.split_cfg_id(cfg_id)
        except (ValueError, KeyError):
            continue                       # shaped like a task, but no usable cfgId
        steals = _int(rec.get("steals"))
        done = _int(rec.get("done"))
        exp = _int(rec.get("exp"))
        out.append(proto.SecretTask(
            uuid=_int(rec.get("uuid")), server_id=_int(rec.get("srv")),
            x=_int(rec.get("x")), y=_int(rec.get("y")), level=level,
            cfg_id=cfg_id, family=family,
            looted_by=tuple(str(i) for i in range(steals)),
            owner_uid=None, alliance_id=None,
            expires_at=exp or None, completed_at=done or None))
    return out


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _select_targets(tasks, limit: int, star_max: bool = False,
                    level_min: int | None = None, level_max: int | None = None,
                    say=print) -> list[tuple[int, int, str]]:
    """The auto-loot rule applied to a list of `SecretTask`s — the shared core.

    Both `targets_from_scan` (capture checkpoint) and `targets_from_vm` (live VM) feed
    the same rule here, so a target picked by one source is picked identically by the
    other. See `targets_from_scan` for the full description of `star_max` / the level
    gate — the reasoning lives with it and is not repeated.
    """
    raidable = [t for t in tasks if t.can_loot]
    if level_min is not None or level_max is not None:
        inside = [t for t in raidable
                  if (level_min is None or t.level >= level_min)
                  and (level_max is None or t.level <= level_max)]
        if len(inside) != len(raidable):
            say("level filter %s..%s: %d of %d raidable tasks left"
                % (level_min if level_min is not None else "",
                   level_max if level_max is not None else "",
                   len(inside), len(raidable)))
        raidable = inside
    if star_max:
        starred = [t for t in raidable if t.starred]
        if not starred:
            say("no starred task in the scan (%d raidable, none starred) — nothing to do"
                % len(raidable))
            return []
        # The target level is the FILTER's top, not the best thing lying around:
        # «от 1 до 7» means 7s are robbed and a 6 waits, however alone it is. Only
        # with no configured top does the best level found stand in for it.
        if level_max is not None:
            top, why = level_max, "the filter's top"
        else:
            top, why = max(t.level for t in starred), "the highest found, no «до» set"
        raidable = [t for t in starred if t.level == top]
        if not raidable:
            say("no starred task at level %d (%s) — nothing to do; %d starred lower "
                "in range are left alone" % (top, why, len(starred)))
            return []
        say("starred targets: %d at level %d (%s)" % (len(raidable), top, why))
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
    ap.add_argument("--from-vm", action="store_true",
                    help="read raidable alliance tasks straight from the live game VM "
                         "(no capture, no map panning); the panel's auto-loot uses this. "
                         "Combine with --from-scan to also take enemy tiles the sweep saw")
    ap.add_argument("--limit", type=int, default=5,
                    help="most targets to take from --from-scan/--from-vm (default 5)")
    ap.add_argument("--star-max", action="store_true",
                    help="with --from-scan: starred tasks only, and only at the top "
                         "level of --level-min/--level-max (the highest level found, "
                         "when no --level-max is given). Nothing there = nothing robbed")
    ap.add_argument("--level-min", type=int, metavar="N",
                    help="with --from-scan: never rob below level N (the panel's "
                         "«уровень от»)")
    ap.add_argument("--level-max", type=int, metavar="N",
                    help="with --from-scan: never rob above level N («уровень до») — "
                         "and with --star-max this IS the level robbed, nothing lower")
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
    if args.from_vm or args.from_scan:
        # Two sources, unioned: the live VM (alliance tasks, always current) and, when
        # given, a capture checkpoint (whatever the sweep panned over, enemy tiles too).
        # A uuid seen by both is kept once, VM copy first — it is the fresher of the two.
        seen_keys: set[tuple[int, int]] = set()

        def _add(rows):
            for uuid, server, label in rows:
                key = (uuid, server)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                targets.append((uuid, server, label))

        if args.from_vm:
            _add(targets_from_vm(ev, args.limit, star_max=args.star_max,
                                 level_min=args.level_min, level_max=args.level_max))
        if args.from_scan:
            if os.path.exists(args.from_scan):
                _add(targets_from_scan(args.from_scan, args.limit, star_max=args.star_max,
                                       level_min=args.level_min, level_max=args.level_max))
            elif not args.from_vm:
                print("no scan checkpoint at %s — run the capture (panel: «Мониторинг "
                      "секреток») while the map moves" % args.from_scan)
                return 1
        targets = targets[:args.limit]
        if not targets:
            # With --star-max this is the ordinary "no star raidable" answer, not a
            # failure: the button is supposed to do nothing rather than rob a plain
            # task. The source helpers have already said which case it was.
            if not args.star_max:
                where = "the game" if args.from_vm else args.from_scan
                print("no raidable task in %s — nothing to rob right now" % where)
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
        ap.error("name a target: --uuid, --coords, --from-vm or --from-scan "
                 "(or ask for --status)")

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

    if robbed:
        # Every success raises the loot window (UIDispatchTaskReward). Leaving it up
        # would sit on top of the map for whoever looks at the client next, so close
        # it with the same press the recipe uses.
        import game_buttons
        button = game_buttons.get("dismiss_steal_reward")
        if button is not None:
            ev.run(button.lua, MARKER, button.wait)

    print("sent %d robbery/robberies; %d left today" % (robbed, left))
    if robbed < len(targets):
        print("note: a target the server refused (expired, slots full, already robbed "
              "by you) leaves todayStealNum unchanged — the client shows the tip.")
    return 0 if robbed else 1


if __name__ == "__main__":
    raise SystemExit(main())
