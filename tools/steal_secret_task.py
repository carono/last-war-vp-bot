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
    --targets U:S,U:S              rob exactly these, in this order — the caller has
                                   already chosen them and nothing here re-derives the
                                   choice. This is what the panel uses: its «Секретки»
                                   list is the one model the capture, the client's own
                                   tables and the pushes all fill, and the standing
                                   order picks out of THAT rather than re-reading the
                                   sources behind its back (#1256)
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
    (always, no flag)              never rob a tile standing on the player's OWN
                                   server — the neighbours you share a map (and an
                                   alliance politics) with. The own server is read
                                   live from the client; when it cannot be read
                                   nothing is robbed, because a prohibition that
                                   silently lapses is worse than a run that stops

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
import game_clock  # noqa: E402
import lua_actions  # noqa: E402
import lua_client  # noqa: E402

MARKER = "ACT"


class NotLoggedIn(RuntimeError):
    """The client answered, but it is not in a session yet.

    Raised by the VM reads rather than returned as an empty list, because an empty
    list is what a logged-in client with nothing to rob says — and telling those two
    apart is the whole point. A client at the login screen has no alliance tasks, an
    own server of `-1` and a full day's robberies still unspent, all without a single
    error (#1227). The clock is the one thing it cannot fake, and every one of these
    reads carries it.
    """

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
    """(robberies left today, targets queued).

    The line carries the game's clock as well (`NOW=`), because this is the one
    read every route into the robbery makes — including `--from-scan`, which
    never touches the tile list and would otherwise judge a checkpoint's
    timestamps against this machine's clock instead of the game's (#1227).
    """
    chunk = (lua_actions.game_server_time() + ' '
             'CS.UnityEngine.Debug.LogError("ACT status left="..tostring(%s)'
             '.." queued="..tostring(%s))'
             % (lua_actions.secret_task_steals_left(), lua_actions.secret_task_queue_len()))
    sent = time.time()
    lines = ev.run(chunk, MARKER, 1.0)
    back = time.time()
    server_ms = game_clock.parse_ms(lines)
    if server_ms is not None:
        game_clock.note(server_ms, sent, back)
    for ln in lines:
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
        # The REQUEST above is the server round trip and stays patient; this is the
        # client reading back what the reply landed in its own table, one line, so the
        # settle is a deadline rather than a sleep (#1282). Paid `DETAIL_TRIES` times
        # per coordinate.
        for ln in ev.run(read, MARKER, 0.4, early=True):
            if "detail uuid=" in ln:
                uuid = _num(ln, "uuid")
                if uuid:
                    return uuid
    return 0


def own_server(ev) -> int:
    """The server the PLAYER belongs to, live from the client (0 when unreadable).

    Not the server currently on screen: the camera walks into other servers all day
    (that is what a robbery run does), so `curServerId` would answer "wherever I am
    looking". `ChatInterface.getSelfServerId()` is the account's own one, which is what
    «не грабить на своём сервере» is about — the neighbours.

    A client that has not logged in answers **-1**, and that is not a server id:
    handed on as one it would make «не грабить на своём сервере» compare every
    tile against a server that cannot exist, so the prohibition would lapse
    silently and the neighbours would be robbed after all (#1227). Anything that
    is not a positive id is "unreadable", which the callers already refuse to act
    on.
    """
    import chat_share                          # tools/lib, already on sys.path
    try:
        server = int(chat_share.self_profile(ev).get("srv") or 0)
    except (TypeError, ValueError):
        return 0
    return server if server > 0 else 0


def _label(task) -> str:
    return ("%s%s lvl %d %d/3 looted"
            % ("*" if task.starred else " ",
               coords_fmt.fmt(task.x, task.y, task.server_id),
               task.level, task.loot_count))


def apply_cfg_rank(ev, tasks, say=print) -> int:
    """Re-rank checkpoint tasks against the CLIENT'S OWN config row. Returns how many.

    A capture decodes a pcap in a child process with no game in it, so the `starred` and
    `level` it writes into the checkpoint are the cfgId's digits — the documented
    fallback (`proto.starred_by_digits`). That is the right answer for a decoder and the
    WRONG one for the thing that spends one of five raids a day: the digits call a
    `60009903` template «level 99, starred» where the game calls it «level 7, not
    starred» (#1267), and a raid spent on a tile that is not a star does not fail, it
    just goes (#1099).

    We are not that child. Anything selecting a target here has a live client one round
    trip away, so it asks: one chunk for every DISTINCT template on the list — a handful,
    not one per tile — and `proto.task_rank` then applies the same precedence it applies
    to the VM feed. A template the client cannot answer for comes back `0/0`, which that
    function already reads as «the config said nothing» and answers from the digits, so
    an unknown id is exactly as good (and as bad) as it was before.
    """
    sys.path.insert(0, os.path.join(_HERE, "lib"))
    import lastwar_proto as proto
    import lua_actions

    ids = sorted({int(t.cfg_id) for t in tasks if t.cfg_id})
    if not ids or ev is None:
        return 0
    ranks: dict[int, tuple[int, int]] = {}
    for line in ev.run(lua_actions.dispatch_task_cfg_rank(ids), MARKER, 1.0):
        if " CFG cfg=" not in line:
            continue
        cfg, lvl, spec = _num(line, "cfg"), _num(line, "lvl"), _num(line, "spec")
        if cfg:
            ranks[cfg] = (lvl, spec)
    changed = 0
    for task in tasks:
        got = ranks.get(int(task.cfg_id or 0))
        if not got:
            continue
        lvl, spec = got
        if not lvl:                       # the client has no row — leave the digits be
            continue
        was = (task.level, task.starred)
        _family, task.level, _starred = proto.task_rank(task.cfg_id, lvl, spec)
        task.starred_cfg = bool(spec)
        if was != (task.level, task.starred):
            changed += 1
    if changed:
        say("the game's own config re-ranked %d of %d tile(s) the capture had guessed"
            % (changed, len(tasks)))
    return changed


def targets_from_scan(path: str, limit: int, star_max: bool = False,
                      level_min: int | None = None, level_max: int | None = None,
                      skip_server: int | None = None, ev=None,
                      say=print) -> list[tuple[int, int, str]]:
    """Raidable tasks from a capture checkpoint, as (uuid, server, label).

    Freshness and raidability are the checkpoint reader's own rules — `load_fresh_tasks`
    drops anything not re-seen in this scan window and recomputes `can_loot` against the
    current clock, so a file written an hour ago cannot smuggle a stale tile in here.

    `level_min` / `level_max` bound which levels may be robbed at all — the panel's
    «уровень от / до». They are applied FIRST, before `star_max` picks its target
    level, so the range is a hard gate and not a preference. Either end may be None.

    `skip_server` drops every tile standing on that server before anything is chosen —
    the panel's «не грабить на своём сервере». Before, not after, so the rule then picks
    the best target among the ones that ARE allowed instead of picking a forbidden one
    and coming back empty.

    `star_max` is the panel's auto-loot rule: **starred tasks only**, and only at ONE
    level — `level_max`, the top of the configured range. «от 1 до 7» means level 7
    and nothing else: a level-6 star is not robbed even when it is the only star on
    the map, because the day's five robberies are the scarce thing and one spent on a
    6 is one a 7 cannot have until the daily reset. Without `level_max` no target
    level is configured, so it falls back to the highest level actually found in
    range.

    No star at the target level means no target at all — the caller does nothing
    rather than settling for a lower one, which is the whole point of the rule.

    `starred` and `level` come out of the checkpoint as the DIGITS' reading, because the
    capture that wrote it had no client to ask. Pass `ev` and they are re-asked of the
    game's own `lw_dispatch_tasks` row before anything is chosen — see
    :func:`apply_cfg_rank`, and never select without it when a client is available
    (#1188).
    """
    sys.path.insert(0, os.path.join(_HERE, "lib"))
    import lastwar_proto as proto

    tasks = proto.load_fresh_tasks(path)
    apply_cfg_rank(ev, tasks, say=say)
    return _select_targets(tasks, limit, star_max=star_max,
                           level_min=level_min, level_max=level_max,
                           skip_server=skip_server, say=say)


def targets_from_vm(ev, limit: int, star_max: bool = False,
                    level_min: int | None = None, level_max: int | None = None,
                    skip_server: int | None = None,
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
                           level_min=level_min, level_max=level_max,
                           skip_server=skip_server, say=say)


def _vm_raidable_tasks(ev) -> list:
    """Parse the `ACT VT …` lines of `secret_task_raidable_alliance()` into SecretTasks.

    The exact loot slots (who has already robbed the tile) are not on the wire here —
    only the count is — so `looted_by` is filled with that many placeholder entries.
    That is enough for `loot_count` / `free_slots` / `can_loot`; whether *I* am already
    in the list is the server's call at steal time, the same as every other route.
    """
    return _read_vt(ev, lua_actions.secret_task_raidable_alliance())


def _vm_all_alliance_tasks(ev) -> list:
    """Every *live* alliance secret task, dispatch finished or still counting down.

    The wider read of `secret_task_all_alliance()` (not-expired, a slot free, but the
    dispatch need NOT be done yet) — what the panel's «Secret Tasks» tab lists so it can
    draw each tile's countdown to raidability and flip a row the moment its clock runs
    out. Same `ACT VT …` shape as the raidable read; `SecretTask.can_loot` / `.pending`
    tell the states apart against the local clock.
    """
    return _read_vt(ev, lua_actions.secret_task_all_alliance())


def _read_vt(ev, chunk: str) -> list:
    """Run one of the two alliance reads and parse it — setting the game's clock.

    Both chunks open by emitting `ACT NOW=<seconds>`, the game's own time, so
    every read of the tile list also re-measures how far the game's clock has
    drifted from this machine's (`game_clock`). It is the same round trip, and it
    is the clock the tiles' `done` / `exp` are stamped on, so a list is judged on
    the clock it was read with rather than on whatever this PC believes (#1227).

    AND THE SETTLE IS A DEADLINE, NOT A PAUSE (#1272). Both chunks END by printing
    `ACT VT_END n=<rows>`, so the answer is known to be complete the moment that line
    lands — typically inside one poll interval instead of the flat 1.1 s this used to
    sleep. It matters beyond this call: the daemon holds its lock for the whole settle,
    so every other thing the panel wanted to do — a lap of the map, a robbery, a jump —
    was queueing behind a read that had already answered.
    """
    sent = time.time()
    lines = ev.run(chunk, MARKER, 1.1, sentinel=lua_actions.VT_END)
    back = time.time()
    server_ms = game_clock.parse_ms(lines)
    if server_ms is None or not game_clock.plausible(server_ms):
        # The read came back without a usable clock: this client is not in a session
        # (or the VM did not answer at all). Its empty task table means "cannot say",
        # not "nothing to rob", and the two must not look the same to a caller.
        raise NotLoggedIn("the client cannot say what time it is")
    game_clock.note(server_ms, sent, back)
    return _parse_vt_lines(lines)


def _parse_vt_lines(lines) -> list:
    """The shared `ACT VT …` -> `SecretTask` parser for both alliance reads above.

    THE LEVEL AND THE STAR ARE THE GAME'S, not this id's digits (#1267). Both reads
    carry `lvl` / `spec` — the `level` and `is_special` columns of the client's own
    `lw_dispatch_tasks` row — and `proto.task_rank` is the same precedence the panel's
    read has applied since #1244. Until this line existed the two disagreed on the same
    live tile: `60009903` was «level 7, no star» to the tab and «level 99» here, and
    since targets are sorted by level, the mislabelled ones went first and spent the
    day's raids. A client too old to answer sends `lvl=0`, and then — and only then —
    the digits are used, exactly as they are for a pcap.
    """
    sys.path.insert(0, os.path.join(_HERE, "lib"))
    import lastwar_proto as proto

    out = []
    for ln in lines:
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
            family, level, starred = proto.task_rank(
                cfg_id, _int(rec.get("lvl")), _int(rec.get("spec")))
        except (ValueError, KeyError, TypeError):
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
            expires_at=exp or None, completed_at=done or None,
            # Only when the client actually answered: `None` means «not asked», and a
            # `False` there would tell every later reader the game had denied the star.
            starred_cfg=starred if _int(rec.get("lvl")) else None))
    return out


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _select_targets(tasks, limit: int, star_max: bool = False,
                    level_min: int | None = None, level_max: int | None = None,
                    skip_server: int | None = None,
                    say=print) -> list[tuple[int, int, str]]:
    """The auto-loot rule applied to a list of `SecretTask`s — the shared core.

    Both `targets_from_scan` (capture checkpoint) and `targets_from_vm` (live VM) feed
    the same rule here, so a target picked by one source is picked identically by the
    other. See `targets_from_scan` for the full description of `star_max` / the level
    gate and `skip_server` — the reasoning lives with it and is not repeated.
    """
    raidable = [t for t in tasks if t.can_loot]
    if skip_server:
        mine = [t for t in raidable if t.server_id == skip_server]
        if mine:
            say("own server %d: %d raidable task(s) left alone" % (skip_server, len(mine)))
        raidable = [t for t in raidable if t.server_id != skip_server]
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


def parse_targets(text: str) -> list[tuple[int, int, str]]:
    """``"uuid:server,uuid:server"`` as the target triples the rest of this script uses.

    The caller's own list, named outright. The panel picks its targets out of the model
    its «Секретки» tab keeps — the one the capture, the client's tables and the alliance
    pushes all fill, and the one every actuality check already runs against — so what it
    hands over here is a DECISION, not a hint to re-derive (#1256). Re-reading the
    sources under it is how the panel and the child it spawned came to two different
    answers about the same map.

    A malformed pair raises rather than being skipped: "rob these four" quietly becoming
    "rob these three" is the kind of silence that spends a day's budget in the wrong
    place.
    """
    out: list[tuple[int, int, str]] = []
    for chunk in str(text).replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        head, _sep, tail = chunk.partition(":")
        try:
            uuid, server = int(head), int(tail)
        except ValueError:
            raise ValueError("a target reads «uuid:server», not %r" % chunk) from None
        out.append((uuid, server, coords_fmt.fmt(0, 0, server).split()[0]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uuid", type=int, help="task uuid to rob")
    ap.add_argument("--targets", metavar="U:S,U:S",
                    help="rob exactly these «uuid:server» pairs, in this order — the "
                         "caller has chosen them and nothing here re-derives the choice "
                         "(what the panel's auto-loot hands over from its own list)")
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
    ap.add_argument("--skip-own-server", action="store_true",
                    help="accepted and ignored: skipping the player's own server is "
                         "what --from-vm / --from-scan always do now (#1188). Kept so "
                         "that older call sites keep working")
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

    # A client that has not finished logging in answers everything, and every answer
    # is a plausible-looking lie: no alliance task in the manager, own server -1, and
    # a daily budget of "all five left" because `GetTodayStealNum()` reads 0 out of an
    # empty manager. Nothing raises, so a run against it looks exactly like a quiet day
    # with nothing to rob — which is what «автолут не работает совершенно» was on the
    # second profile (#1227). The clock is the one question it cannot fake.
    if not game_clock.session_ready(ev):
        print("the client is not logged in (it cannot say what time it is) — nothing "
              "read and nothing robbed; log the game in and run this again")
        return 1

    if args.status:
        left, queued = read_status(ev)
        print("robberies left today: %d   targets queued: %d" % (left, queued))
        return 0

    # «На своём сервере не грабим вообще», resolved once and up front — and no longer
    # optional (#1188). It gates the SELECTION sources only (`--from-vm` / `--from-scan`);
    # `--targets`, `--uuid` and `--coords` name one tile by hand and are still obeyed
    # literally, because somebody typing a uuid has already made the decision.
    #
    # A prohibition that cannot be checked must stop the run rather than lapse quietly:
    # an unreadable own server would otherwise mean every neighbour is fair game again.
    skip = 0
    if args.from_vm or args.from_scan:
        skip = own_server(ev)
        if not skip:
            print("the player's own server could not be read — nothing robbed "
                  "(is the game running and logged in?)")
            return 1
        print("own server: %d — its tiles are not targets" % skip)

    targets: list[tuple[int, int, str]] = []
    if args.targets:
        # Somebody else's list decided. Nothing is re-read and nothing is re-filtered
        # here — the level rule, the star and «не грабить на своём сервере» were all
        # applied where the targets were chosen, and applying them twice against two
        # different readings of the map is how the two ends disagree (#1256).
        try:
            targets = parse_targets(args.targets)
        except ValueError as exc:
            ap.error(str(exc))
        if not targets:
            print("--targets named nothing — nothing to rob")
            return 0
        targets = targets[:args.limit]
    elif args.from_vm or args.from_scan:
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
                                 level_min=args.level_min, level_max=args.level_max,
                                 skip_server=skip or None))
        if args.from_scan:
            if os.path.exists(args.from_scan):
                _add(targets_from_scan(args.from_scan, args.limit, star_max=args.star_max,
                                       level_min=args.level_min, level_max=args.level_max,
                                       skip_server=skip or None, ev=ev))
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
        ap.error("name a target: --uuid, --targets, --coords, --from-vm or --from-scan "
                 "(or ask for --status)")

    # The last gate, over WHATEVER named the targets: the two source paths dropped the
    # own server before choosing, but a hand-named `--uuid`/`--coords` never went through
    # that rule and must obey the same prohibition.
    if skip:
        kept = [t for t in targets if t[1] != skip]
        if len(kept) != len(targets):
            print("own server %d: %d target(s) left alone"
                  % (skip, len(targets) - len(kept)))
        targets = kept
        if not targets:
            print("every target stood on the own server — nothing to rob")
            return 0

    left, _ = read_status(ev)
    print("robberies left today: %d" % left)
    for uuid, server, label in targets:
        print("  target %-28s uuid=%d srv=%d" % (label, uuid, server))

    # Parking the queue is an assignment inside the client that logs its own count —
    # `early`, so the settle is only the deadline for a line that never comes (#1282).
    ev.run(lua_actions.secret_task_queue_set([(u, s) for u, s, _ in targets]),
           MARKER, 0.6, early=True)
    if args.queue_only:
        _, queued = read_status(ev)
        # THIS LINE IS A CONTRACT, not just a report. The panel's auto-loot runs this
        # tool with `--queue-only` and then plays `actions/steal_secret_task.md` itself
        # (#1188), and «queued …» at the start of a line is how its reader tells «the
        # targets are parked» from every way this run can decline — none of which
        # touches the queue. Reword the opening word and the standing order silently
        # stops robbing (panel/tabs/secret_tasks/autoloot.py, QUEUED_MARK).
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
