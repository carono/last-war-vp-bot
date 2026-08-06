#!/usr/bin/env python3
r"""Rob a ghost-recon squad — «Операция Призрак» — headless.

Not the same thing as `steal_secret_task.py`
--------------------------------------------
Two different robberies live in this game and they are easy to confuse:

* **«Секретка»** — a hero dispatch on a player's own tile, robbed with
  `hero.dispatch.steal`. That is `tools/steal_secret_task.py`.
* **«Операция Призрак»** — the weekly co-op event whose squads sit on `f2 = 29`
  map tiles, robbed with `ghost.recon.steal`. That is this script.

Separate commands, separate five-a-day budgets. See
docs/research/ghost-recon-steal.md.

What a robbery is
-----------------
One command, two fields, no march and no window:

    --> ghost.recon.steal  {uuid, ownerServer}
    <-- ghost.recon.steal  {reward[], recordUuid, stealTimes, ownerInfo, ...}

The client already knows which squads exist (`ghost.recon.get.task.list`), so a
target does not need a map scan — `--list` prints them with the game's own verdict
on each (`GhostreconPointStealType`).

Usage (run under the Windows Python so it can reach the warm daemon)
--------------------------------------------------------------------
    C:\Python312\python.exe tools\ghost_recon_steal.py --status
    C:\Python312\python.exe tools\ghost_recon_steal.py --list
    C:\Python312\python.exe tools\ghost_recon_steal.py --all
    C:\Python312\python.exe tools\ghost_recon_steal.py --uuid U --server S
    C:\Python312\python.exe tools\ghost_recon_steal.py --targets U:S,U:S
    C:\Python312\python.exe tools\ghost_recon_steal.py --all --queue-only

`--all` takes every squad the client says is robbable right now, newest-finished
first, up to the day's remaining budget. `--targets` robs exactly the «uuid:server»
pairs it is given, in that order, and re-derives nothing — that is what the panel's
standing order uses, because the choice belongs to the list the «Командный пункт»
page keeps and not to a second reading of the map (#1256). `--queue-only` parks the
targets in the game VM so `actions/steal_ghost_recon.md`
(`TAP steal_ghost_recon xall`) can spend them.

**Outside the event this does nothing and says so.** `IsOpenDay()` is false six
days a week, `taskList` is empty, and every press is gated on it.
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


def _num(text: str, key: str) -> int:
    if key + "=" not in text:
        return 0
    tail = text.split(key + "=", 1)[1].split()[0]
    try:
        return int(tail)
    except ValueError:
        return 0


def read_status(ev) -> dict:
    chunk = ('CS.UnityEngine.Debug.LogError("ACT status open="..tostring(%s)'
             '.." left="..tostring(%s).." queued="..tostring(%s))'
             % (lua_actions.ghost_recon_is_open(), lua_actions.ghost_recon_steals_left(),
                lua_actions.ghost_recon_queue_len()))
    for ln in ev.run(chunk, MARKER, 1.0):
        if "status open=" in ln:
            return {"open": bool(_num(ln, "open")), "left": _num(ln, "left"),
                    "queued": _num(ln, "queued")}
    return {"open": False, "left": 0, "queued": 0}


def read_targets(ev, refresh: bool = True) -> list[dict]:
    """Every ghost-recon squad the client knows, with the game's steal verdict.

    `refresh` asks the server for both task lists first; the reply needs a moment to
    land, which is why the read is a separate chunk after a settle.
    """
    return read_list(ev, refresh)[1]


def read_list(ev, refresh: bool = True) -> tuple[dict, list[dict]]:
    """`(status, targets)` — the event's state and its squads, from ONE dump.

    The dump's own first line already carries the open day and the robberies left
    (`ghost open=… left=… known=…`), so a caller that wants both — the panel's ghost
    page (#1251) — pays for one read rather than for `read_status` and then this. The
    per-squad fields are `read_targets`'s, unchanged.
    """
    if refresh:
        ev.run(lua_actions.ghost_recon_refresh(), MARKER, 0.4)
        time.sleep(1.2)
    status = {"open": False, "left": 0, "known": 0}
    out = []
    for ln in ev.run(lua_actions.ghost_recon_targets_dump(), MARKER, 2.0):
        if " ghost open=" in ln:
            status = {"open": "open=true" in ln, "left": _num(ln, "left"),
                      "known": _num(ln, "known")}
            continue
        if " G uuid=" not in ln:
            continue
        rec = {}
        for token in ln.split(" G ", 1)[1].split(" "):
            key, sep, value = token.partition("=")
            if sep:
                rec[key] = value
        rec["mine"] = rec.get("mine") == "true"
        for key in ("cfg", "srv", "tsrv", "x", "y", "done", "ends", "exp", "looted",
                    "state"):
            rec[key] = _int(rec.get(key))
        # The config's own answers — and `None` when the line does not carry them at
        # all (an OLDER dump). Zero is a meaningful value for every one of these, so
        # «absent» and «the config says 0» must not be the same thing: it is what
        # decides whether the cfgId's digits get a say (#1251).
        for key in ("lvl", "colour", "spec", "slots"):
            rec[key] = _int(rec[key]) if key in rec else None
        # The owner's nickname travels hex-encoded — it may hold spaces, and the dump
        # is space-separated.
        rec["name"] = _hexdec(rec.get("name"))
        # `raw` stays None when the line does not carry it — an OLDER dump, whose
        # squads must not all be read as empty slots (0 is a meaningful value here).
        rec["raw"] = _int(rec["raw"]) if "raw" in rec else None
        out.append(rec)
    return status, out


def _hexdec(value) -> str:
    try:
        return bytes.fromhex(str(value or "")).decode("utf-8", "replace")
    except ValueError:
        return ""


# `actEndTime` on a ghost-recon squad is the EVENT's end, and while the event has no
# announced end the client carries the int32 ceiling in milliseconds. It is not a
# deadline anybody can count down to, so a record wearing it says «no expiry» instead
# of a countdown of sixty-eight years (#1251).
NEVER_MS = 2147483647 * 1000


def roster(ev, refresh: bool = True) -> tuple[dict, list[dict]]:
    """`(status, records)` — the squads in the shape a panel list draws from.

    The same normalisation `dispatch_tasks.alliance_roster` does for the other
    robbery, and here for the same reason (#1251): the panel's ghost page must not
    have to know how a dump line is spelled, what the game's verdict enum means or
    where the level hides in a cfgId.

    **The level, the rarity and the star come from the event's OWN config row.** The
    client carries one per template (`GetTaskTemplate`) and it answers all three —
    `level`, `color`, `special` — plus how many robberies a tile allows at all
    (`stealMaxtimes`). The cfgId arithmetic (`ghost_recon_level`, `MM + 2`, task
    #1137) is kept as the FALLBACK for a template the client has not loaded, and
    nothing more: home-made arithmetic over an id is what invented a star and a «level
    99» on the other robbery (#1244), and this is the same mistake waiting to be made
    twice. `state` is the game's own `GhostreconPointStealType`, kept as it came so the
    caller can say it in words; `ready` is that verdict reaching «can steal».

    **The tile is on the OWNER's map.** A squad is sent abroad — `targetServer` says
    where — but the tile itself stands at home, which is where a camera has to go and
    where the robbery is addressed. Measured with the tile capture running: a lap of
    one server found 38 ghost tiles, all of them `owner_server` = that server, their
    `targetServer` scattered across a dozen others.

    **An empty dispatch slot is not a squad.** `taskList` holds my own three slots
    whether or not anything is out in them, and a slot with `state == 0` has no tile,
    no coordinate and no clock — while `GetPointStealType` still answers «robbable»
    for it. They are dropped here rather than drawn as targets at @[0,0] (#1251).

    **My own squads and my alliancemates' come out of the SAME read** and are told
    apart by `mine` — the client keeps both in one list once both lists have been
    asked for. The panel draws them as two tables (#1251) off this one answer rather
    than paying for a read each.

    A tile off a MAP SCAN is deliberately not in here. The client's list is my own
    alliance's — mine and my mates' — and that is what these two tables are about;
    somebody else's alliance's tiles are what a robbery is aimed at, and they are on
    the «Командный пункт» tab where the robbing happens (`GhostReconPane`).
    """
    import lastwar_proto as proto

    status, targets = read_list(ev, refresh)
    return status, [_as_record(t, proto) for t in targets
                    if t.get("raw") != proto.GHOST_STATE_EMPTY]


def alliance_roster(ev, seed_if_empty: bool = False) -> list[dict]:
    """Every ghost-recon squad the ALLIANCE has out, in the shape a panel list draws.

    A different list from :func:`roster` and a different question. That one is what
    THIS account is mixed up in — my own three slots and whatever else the client was
    told; this one is `ActGhostreconAllianceManager.allianceTaskList`, which is what
    the game's own «задания альянса» window draws: the whole alliance, all of it at
    once. Live, the two read 3 and 13 (#1251).

    **It asks the server nothing** — the list is already in the client and the
    `push.ghost.recon.alliance.single` stream keeps it current, so this is a read of
    local state, which is why the panel can afford it on every push. The single
    exception is `seed_if_empty`: a client whose event window has not been opened this
    session has never been SENT the list, and an empty table then means «never asked»
    rather than «nothing out». One request, only when the local list is empty, and
    never on a push.

    The level, the rarity, the star and the loot capacity are the event's own config
    row, as everywhere else here. Two things this list genuinely does not carry, and
    which are therefore left empty rather than invented:

    * **how many times the tile has been robbed** — there is no steal list on these
      records at all, so `loot_count` is None, not 0: «not answered» and «nobody has
      robbed it» are different facts, and a zero would be the wrong one;
    * **an expiry** — the record has no end time; what it has is when the squad set
      out (`teamStartTime`), and the config says how long one is out (`time`), so
      `completed_at` is those two added and `expires_at` stays None.
    """
    import lastwar_proto as proto

    rows = _alliance_lines(ev)
    if not rows and seed_if_empty:
        # An empty list is ambiguous on a client whose event window has never been
        # opened this session: the server has simply never sent it. One request — the
        # same one the game's own window makes on open — and then read again. Never on
        # a push, and never when the list already has something in it.
        ev.run(lua_actions.ghost_recon_alliance_request(), MARKER, 0.4)
        time.sleep(1.2)
        rows = _alliance_lines(ev)

    out = []
    for ln in rows:
        rec = {}
        for token in ln.split(" A ", 1)[1].split(" "):
            key, sep, value = token.partition("=")
            if sep:
                rec[key] = value
        for key in ("cfg", "srv", "x", "y", "start", "lvl", "colour", "spec",
                    "slots", "dur", "state", "members"):
            rec[key] = _int(rec.get(key))
        family, level = proto.ghost_recon_level(rec.get("cfg"))
        done = (rec["start"] + rec["dur"]) if rec["start"] and rec["dur"] else None
        out.append({
            "uuid": str(rec.get("uuid")),
            # Where the TILE is — the squad was sent there, and that is where a camera
            # goes. This list carries no owner server at all, so a robbery aimed from
            # here would have nothing to address; it is a reading, and says so.
            "server": rec["srv"],
            "x": rec["x"], "y": rec["y"],
            "cfg_id": rec["cfg"],
            "level": rec["lvl"] or level or 0,
            "starred": bool(rec["spec"]) if "spec" in rec else
                       family == proto.GHOST_STAR_FAMILY,
            "colour": rec["colour"],
            "loot_max": rec["slots"],
            # Not on this list at all — see the docstring. None, never 0.
            "loot_count": None,
            "completed_at": done,
            "expires_at": None,
            "owner_uid": str(rec.get("owner") or ""),
            "owner_name": _hexdec(rec.get("name")),
            "members": rec["members"],
            "mine": False,
            "state": rec["state"],
            "task_state": None,
            "ready": rec["state"] == lua_actions.GHOST_STEAL_CAN,
        })
    return out


def templates(ev) -> dict:
    """`{cfg_id: {level, colour, starred, loot_max, duration}}` — the event's config.

    One read of the client's own template table, which is what a tile found on the MAP
    has to be judged by: such a tile carries a cfgId and nothing else, and the digits
    of an id are exactly what must not be turned into a level (#1244, #1251).
    """
    out = {}
    for ln in ev.run(lua_actions.ghost_recon_templates_dump(), MARKER, 2.0):
        if " TPL cfg=" not in ln:
            continue
        rec = {}
        for token in ln.split(" TPL ", 1)[1].split(" "):
            key, sep, value = token.partition("=")
            if sep:
                rec[key] = _int(value)
        if rec.get("cfg"):
            out[rec["cfg"]] = {"level": rec.get("lvl", 0),
                               "colour": rec.get("colour", 0),
                               "starred": bool(rec.get("spec")),
                               "loot_max": rec.get("slots", 0),
                               "duration": rec.get("dur", 0)}
    return out


def map_roster(path, config=None) -> list[dict]:
    """The ghost-recon tiles a MAP SCAN found, in the shape a panel list draws from.

    THE OTHER SNIFFER, and not a substitute for either list read out of the client:
    those two hold my own squads and my own alliance's, while a lap of the map finds
    everybody's — which is the whole point, because a robbery is aimed at somebody
    else's alliance. «Это два разных снифа, чужие снифаем по карте, свои из списка.»

    ``path`` is the capture's checkpoint (`profiles.ghost_json`); ``config`` is
    :func:`templates`'s answer, so a tile says the level, the rarity and the star the
    GAME gives them rather than what its cfgId's digits spell. Without a config the
    arithmetic is the fallback, exactly as everywhere else here.

    EVERYTHING the checkpoint holds comes back, however long ago it was last seen
    (#1251). The capture only FILLS a list; what is kept and what is dropped is the
    list's own rule — a tile leaves it when its own clock says it is over, when it was
    robbed, or when a live read stops confirming it, and never merely because the map
    has not been driven past it lately. Each row carries `seen_at`, so a reader can say
    how old its information is rather than hide it for being old.
    """
    import lastwar_proto as proto

    config = config or {}
    out = []
    for m in proto.load_fresh_ghost_recon(path, max_age_seconds=None):
        if m.uuid is None or m.empty:
            continue
        cfg = config.get(m.cfg_id or 0, {})
        family, level = proto.ghost_recon_level(m.cfg_id)
        out.append({
            "uuid": str(m.uuid),
            # The tile stands on its owner's map — measured, see `_as_record`.
            "server": m.owner_server or 0,
            "owner_server": m.owner_server or 0,
            "target_server": m.target_server or 0,
            "x": m.x or 0, "y": m.y or 0,
            "cfg_id": m.cfg_id or 0,
            "level": cfg.get("level") or level or 0,
            "starred": cfg.get("starred", family == proto.GHOST_STAR_FAMILY),
            "colour": cfg.get("colour", 0),
            "loot_max": cfg.get("loot_max", 0),
            "loot_count": m.steal_count,
            "completed_at": m.completion_time or None,
            "expires_at": m.expire_time or None,
            "owner_uid": str(m.owner_id or ""),
            "alliance_id": str(m.alliance_id or ""),
            # A tile off the map carries no nickname at all: the wire has the owner's
            # uid and no name anywhere. Left empty rather than filled with a number.
            "owner_name": "",
            "members": m.member_count,
            # When the capture last saw this tile — the row says so when it is old,
            # instead of vanishing (#1251).
            "seen_at": getattr(m, "seen_at", None),
            "mine": False,
            # The game's per-tile gate only answers for squads in the client's own
            # list, so a tile off the map is judged by its clock — which is what
            # `GhostReconMission.can_loot` already worked out.
            "state": None,
            "task_state": None,
            "ready": bool(m.can_loot),
        })
    return out


def _alliance_lines(ev) -> list:
    """The dump's own `ACT A …` lines, unparsed."""
    return [ln for ln in ev.run(lua_actions.ghost_recon_alliance_dump(), MARKER, 2.5)
            if " A uuid=" in ln]


def _as_record(target: dict, proto) -> dict:
    """One dump line as a panel row record.

    The config's answers win wherever the client gave them; the cfgId is read only for
    what is left over — which, for a squad off a map scan, is everything.
    """
    family, level = proto.ghost_recon_level(target.get("cfg"))
    # A squad's tile really does expire — at the end of the event day — and that is
    # `taskExpireTime`. `actEndTime` is the EVENT's own end, which while none is
    # announced reads as the int32 ceiling; taking that for a deadline drew a countdown
    # of sixty-eight years, so the task's own answer is preferred and the ceiling only
    # fills in when there is nothing else (#1251).
    ends = _int(target.get("exp")) or _int(target.get("ends"))
    done = _int(target.get("done"))
    # The config row, when the client has it: level, rarity, star and how many
    # robberies the tile allows. Zero means «not answered», never «level zero».
    cfg_level = _int(target.get("lvl")) if target.get("lvl") is not None else 0
    colour = _int(target.get("colour")) if target.get("colour") is not None else 0
    slots = _int(target.get("slots")) if target.get("slots") is not None else 0
    starred = (bool(_int(target.get("spec"))) if target.get("spec") is not None
               else family == proto.GHOST_STAR_FAMILY)
    return {
        "uuid": str(target.get("uuid")),
        # WHERE THE TILE IS — the owner's own map, which is also where the robbery is
        # addressed (`ghost.recon.steal {uuid, ownerServer}`). Measured rather than
        # reasoned: a lap of server 935 with the tile capture running found 38 ghost
        # tiles and every one of them carried `owner_server` 935, while their
        # `target_server` was scattered across a dozen other worlds. An earlier guess
        # that the coordinate belonged to `targetServer` would have walked the camera
        # onto a stranger's map (#1251).
        "server": _int(target.get("srv")),
        "owner_server": _int(target.get("srv")),
        # Where the squad was SENT. Carried because it is what the game's own window
        # prints beside the coordinate, and not because a camera should go there.
        "target_server": _int(target.get("tsrv")),
        "x": _int(target.get("x")), "y": _int(target.get("y")),
        "cfg_id": _int(target.get("cfg")),
        "level": cfg_level or level or 0,
        "starred": starred,
        "colour": colour,
        # How many robberies the template allows — 3 live, but read rather than assumed.
        "loot_max": slots,
        "loot_count": _int(target.get("looted")),
        "completed_at": done or None,
        "expires_at": ends if 0 < ends < NEVER_MS else None,
        "owner_uid": str(target.get("owner") or ""),
        "alliance_id": str(target.get("al") or ""),
        # The owner's nickname, off the squad's own member list — the only place the
        # client keeps it. Empty when the squad carries no member list at all.
        "owner_name": str(target.get("name") or ""),
        "mine": bool(target.get("mine")),
        "state": _int(target.get("state")),
        # The task's OWN state — running or done (`GHOST_STATE_*`). What a reader says
        # about MY squad, which has a verdict about robbing it that means nothing.
        "task_state": target.get("raw"),
        # MY OWN squad is never «robbable», whatever the verdict says: the gate answers
        # about the tile, and `--all` skips my own separately (`robbable`). A row that
        # said «готово к сбору» on my own squad would be offering a press the server
        # refuses (#1251).
        "ready": (not target.get("mine")
                  and _int(target.get("state")) == lua_actions.GHOST_STEAL_CAN),
    }


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def describe(task: dict) -> str:
    state = lua_actions.GHOST_STEAL_NAMES.get(task.get("state"), "unknown")
    where = coords_fmt.fmt(task.get("x", 0), task.get("y", 0), task.get("srv", 0))
    return ("%-22s %-9s looted %s  cfg %-7s %s%s"
            % (where, state, task.get("looted"), task.get("cfg"),
               "own " if task.get("mine") else "", task.get("uuid")))


def robbable(ev, tasks: list[dict]) -> list[dict]:
    """Filter to what the client says may be robbed right now.

    The per-tile question is asked of the game itself (`ghost_recon_can_steal`), so
    this never second-guesses the client's own rules — it only skips the ones it has
    already been told to skip.
    """
    picked = []
    for task in tasks:
        uuid = task.get("uuid")
        if not uuid or task.get("mine"):
            continue
        chunk = ('CS.UnityEngine.Debug.LogError("ACT can uuid=%s v="..tostring(%s))'
                 % (uuid, lua_actions.ghost_recon_can_steal(int(uuid))))
        for ln in ev.run(chunk, MARKER, 0.6):
            if "can uuid=%s" % uuid in ln and _num(ln, "v") == 1:
                picked.append(task)
    picked.sort(key=lambda t: -t.get("done", 0))
    return picked


def _parse_targets(text: str) -> list[dict]:
    """``"uuid:ownerServer,…"`` as the target dicts the rest of this script passes round.

    A malformed pair raises rather than being skipped: "rob these four" quietly becoming
    "rob these three" is the kind of silence a five-a-day budget cannot afford.
    """
    out: list[dict] = []
    for chunk in str(text).replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        head, _sep, tail = chunk.partition(":")
        try:
            uuid, server = int(head), int(tail)
        except ValueError:
            raise ValueError("a target reads «uuid:server», not %r" % chunk) from None
        out.append({"uuid": str(uuid), "srv": server})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="event state and budget, then stop")
    ap.add_argument("--list", action="store_true", help="every known squad and its verdict")
    ap.add_argument("--all", action="store_true", help="take every robbable squad")
    ap.add_argument("--uuid", type=int, help="rob this squad uuid")
    ap.add_argument("--targets", metavar="U:S,U:S",
                    help="rob exactly these «uuid:ownerServer» pairs, in this order — "
                         "the caller chose them and nothing here re-derives the choice "
                         "(what the panel's standing order hands over from its list)")
    ap.add_argument("--server", type=int, help="the squad's ownerServer")
    ap.add_argument("--limit", type=int, default=5, help="most targets to take (default 5)")
    ap.add_argument("--queue-only", action="store_true",
                    help="park the targets in the game VM and stop (no robbery)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ev = lua_client.get_evaluator()
    status = read_status(ev)
    print("ghost recon: %s   robberies left today: %d   queued: %d"
          % ("open" if status["open"] else "CLOSED (not an event day)",
             status["left"], status["queued"]))
    if args.status:
        return 0

    if not status["open"]:
        # Not a failure — the event runs one day a week. Saying so beats a queue
        # full of targets that the server would refuse anyway.
        print("the event is not running today — nothing to rob")
        return 0

    if args.targets:
        # Somebody else's list decided (#1256). The event-day and the daily budget are
        # still this script's gates — they are the game's answer and belong here — but
        # WHICH squads are worth the five is the caller's, and re-filtering them against
        # a second reading of `taskList` is how the panel and its child disagree.
        try:
            targets = _parse_targets(args.targets)
        except ValueError as exc:
            ap.error(str(exc))
        if not targets:
            print("--targets named nothing — nothing to rob")
            return 0
        targets = targets[:min(args.limit, status["left"])]
    elif args.list or args.all:
        tasks = read_targets(ev)
        if args.list:
            print("%d known squad(s)" % len(tasks))
            for task in tasks:
                print("  " + describe(task))
            if not args.all:
                return 0
        targets = robbable(ev, tasks)[:min(args.limit, status["left"])]
        if not targets:
            print("nothing robbable right now (finished, unlooted, someone else's)")
            return 0
    elif args.uuid:
        if args.server is None:
            ap.error("--uuid needs --server")
        targets = [{"uuid": str(args.uuid), "srv": args.server}]
    else:
        ap.error("name a target: --uuid, --targets, --all "
                 "(or ask for --status / --list)")

    pairs = [(int(t["uuid"]), int(t.get("srv") or 0)) for t in targets]
    for uuid, server in pairs:
        print("  target uuid=%d srv=%d" % (uuid, server))
    ev.run(lua_actions.ghost_recon_queue_set(pairs), MARKER, 0.6)

    if args.queue_only:
        # THIS LINE IS A CONTRACT, not just a report — see the same note in
        # tools/steal_secret_task.py. «Командный пункт» runs this tool with
        # `--queue-only` and then plays `actions/steal_ghost_recon.md` itself (#1188);
        # «queued …» at the start of a line is how its reader tells «the targets are
        # parked» from a shut event or an empty list, neither of which touches the
        # queue (panel/tabs/command_post/ghost.py, QUEUED_MARK).
        print("queued %d target(s) — run actions/steal_ghost_recon.md to spend them"
              % len(pairs))
        return 0

    robbed, left = 0, status["left"]
    for _ in range(min(len(pairs), left)):
        ev.run(lua_actions.steal_next_ghost_recon(), MARKER, 2.0)
        now = read_status(ev)
        if now["left"] < left:
            robbed += 1
        left = now["left"]
        if not left or not now["queued"]:
            break

    if robbed:
        import game_buttons
        button = game_buttons.get("dismiss_ghost_recon_reward")
        if button is not None:
            ev.run(button.lua, MARKER, button.wait)

    print("sent %d robbery/robberies; %d left today" % (robbed, left))
    return 0 if robbed else 1


if __name__ == "__main__":
    raise SystemExit(main())
