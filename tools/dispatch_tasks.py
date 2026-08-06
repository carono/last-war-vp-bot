#!/usr/bin/env python3
r"""List the secret tasks ("секретки" / hero dispatch) the client currently knows.

Where they come from
--------------------
Secret tasks ride the map as `world.get.block` tiles (`f2 = 17`,
`WorldPointType.HERO_DISPATCH`), so the pcap route needs the player to pan the map
(see docs/skills/sniff.md). The client, however, already keeps a parsed copy:

    DataCenter.ActDispatchTaskDataManager
        .singleTask     -- your own tasks (pointId 0: they sit in your base)
        .allianceTask   -- alliance members' tasks, placed on the world map

Both are read here straight out of the live Lua VM through the warm daemon — no
capture, no map panning, no pixels.

Each record carries `uuid`, `cfgId`, `pointId` (-> tile x/y via
`SceneUtils.IndexToTilePos`), `targetServer`, `completionTime` (dispatch done) and
`actEndTime` (expiry), plus an `avatar` with the owner's `name` and alliance
`abbr`.

Usage (run under the Windows Python so it can reach the daemon)
--------------------------------------------------------------
    C:\Python312\python.exe tools\dispatch_tasks.py
    C:\Python312\python.exe tools\dispatch_tasks.py --own
    C:\Python312\python.exe tools\dispatch_tasks.py --ready          # done, not expired
    C:\Python312\python.exe tools\dispatch_tasks.py --nearest --share-args

`--share-args` prints the ready `chat_send.py` arguments for the first listed task,
so a secret task can be forwarded into chat without hand-building the attachment:

    C:\Python312\python.exe tools\chat_send.py --to <peerUid> <those args>
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import chat_share  # noqa: E402
import coords as coords_fmt  # noqa: E402
import lua_client  # noqa: E402

MARKER = "ACT"

# The label the client itself puts on a shared secret task (attachment `oname`).
TASK_LABEL = chat_share.SECRET_TASK_LABEL

_DUMP_LUA = r"""
local function hex(s) return (tostring(s):gsub('.', function(c) return string.format('%02x', c:byte()) end)) end
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..s) end
pcall(function()
  local m = DataCenter.ActDispatchTaskDataManager
  L("now="..tostring(ChatInterface.getServerTime()))
  local function emit(kind, t)
    for _, v in pairs(t or {}) do
      local x, y = 0, 0
      pcall(function()
        local tp = SceneUtils.IndexToTilePos(v.pointId)
        x, y = tp.x, tp.y
      end)
      local av = v.avatar or {}
      -- The task's OWN config row, which is what the game draws the tile from:
      -- `lw_dispatch_tasks`, reached through `v.cfg` and read by column name. The
      -- cfgId cannot be decoded into these (task #1244, live report): `60009903`
      -- reads as "level 99" by its digits and is a LEVEL-7 task of another type,
      -- and the star is `is_special`, not a family. Absent config -> zeros, and
      -- the Python side falls back to the old arithmetic.
      local lvl, spec, colour, star = 0, 0, 0, 0
      pcall(function()
        lvl = tonumber(v.cfg:getValue("level")) or 0
        spec = tonumber(v.cfg:getValue("is_special")) or 0
        colour = tonumber(v.cfg:getValue("color")) or 0
        star = tonumber(v.cfg:getValue("task_star")) or 0
      end)
      L("T kind="..kind.." uuid="..tostring(v.uuid).." cfgId="..tostring(v.cfgId)
        .." pointId="..tostring(v.pointId).." x="..tostring(x).." y="..tostring(y)
        .." srv="..tostring(v.targetServer).." owner="..tostring(v.ownerId)
        .." done="..tostring(v.completionTime).." expires="..tostring(v.actEndTime)
        .." steals="..tostring(#(v.stealInfoList or {}))
        .." lvl="..tostring(lvl).." spec="..tostring(spec)
        .." colour="..tostring(colour).." tstar="..tostring(star)
        .." name="..hex(tostring(av.name or "")).." abbr="..hex(tostring(av.abbr or "")))
    end
  end
  emit("own", m.singleTask)
  emit("alliance", m.allianceTask)
end)
"""


def _hexdec(h: str) -> str:
    try:
        return bytes.fromhex(h).decode("utf-8", "replace")
    except ValueError:
        return ""


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def read_tasks(ev) -> tuple[list[dict], int]:
    """(tasks, server time in ms). `getServerTime()` returns seconds."""
    tasks, now_ms = [], 0
    for ln in ev.run(_DUMP_LUA, MARKER, 3.4):
        body = ln[4:] if ln.startswith("ACT ") else ln
        if body.startswith("now="):
            now_ms = _num(body[4:]) * 1000
            continue
        if not body.startswith("T "):
            continue
        rec = {}
        for tok in body[2:].split(" "):
            key, sep, value = tok.partition("=")
            if not sep:
                continue
            rec[key] = _hexdec(value) if key in ("name", "abbr") else value
        rec["uuid"] = rec.get("uuid", "0")
        for key in ("cfgId", "pointId", "x", "y", "srv", "done", "expires", "steals",
                    "lvl", "spec", "colour", "tstar"):
            rec[key] = _num(rec.get(key))
        tasks.append(rec)
    return tasks, now_ms


def alliance_roster(ev) -> list[dict]:
    """What the player's own alliance is running right now, one record per task.

    The same `allianceTask` read as :func:`read_tasks`, kept to the alliance half and
    normalised into the shape a list draws from: who dispatched it, what rank and level
    it is, when it finishes, when it disappears off the map and how many times it has
    been robbed already. The panel's «Секретки» tab draws exactly this in its second
    table (#1244) — hence a function rather than a second copy of the loop over there.

    **`level` and `starred` come from the GAME's own config row, not from the cfgId.**
    The digits lie about both, and a live report caught them doing it (#1244): the
    client's `lw_dispatch_tasks` row says `level = 7` for a `60009903` whose digits read
    as level 99, and the star is the `is_special` column rather than a family — a
    conclusion the wire could never reach, because it carries neither. The arithmetic
    stays as the fallback for a record whose config the client has not loaded, which is
    also all the pcap route has ever had.

    A record with no owner name — the client has the task but not the avatar behind it
    yet — keeps an empty string rather than inventing one.
    """
    import lastwar_proto as proto

    out = []
    for task in read_tasks(ev)[0]:
        if task.get("kind") != "alliance":
            continue
        cfg_id = task["cfgId"]
        try:
            family, level, _variant = proto.split_cfg_id(cfg_id)
        except (TypeError, ValueError):
            continue                       # shaped like a task, but no usable cfgId
        starred = (family in proto.STAR_TASK_FAMILIES
                   and level != proto.SPECIAL_TASK_LEVEL)
        if task.get("lvl"):                # the config answered — it outranks the digits
            level, starred = task["lvl"], bool(task.get("spec"))
        out.append({
            "uuid": task["uuid"], "server": task["srv"],
            "x": task["x"], "y": task["y"], "point_id": task["pointId"],
            "cfg_id": cfg_id, "family": family, "level": level, "starred": starred,
            # What the game colours the tile by (3/4/5 live) and which star tier the
            # task belongs to — carried because they are what tells one TYPE of
            # level-7 task from another, which is the whole of the «особое задание»
            # confusion this fixed.
            "colour": task.get("colour") or 0, "star_tier": task.get("tstar") or 0,
            "loot_count": task["steals"],
            "completed_at": task["done"] or None,
            "expires_at": task["expires"] or None,
            "owner_uid": task.get("owner", ""),
            "owner_name": task.get("name", ""),
            "alliance_abbr": task.get("abbr", ""),
        })
    return out


def share_extra(task: dict) -> dict:
    """The kind-specific half of a posType-22 attachment (see chat-coord-share.md).

    `chat_share.task_attachment(task)` builds the whole blob; this is only the tail,
    for printing ready `chat_send.py --coord-extra` arguments.
    """
    return {
        "uuid": int(task["uuid"]),
        "cfgId": task["cfgId"],
        "uname": task.get("name", ""),
        "abbr": task.get("abbr", ""),
        "dispatch": 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--own", action="store_true", help="only your own tasks")
    ap.add_argument("--alliance", action="store_true", help="only alliance tasks")
    ap.add_argument("--ready", action="store_true",
                    help="only tasks whose dispatch has completed and that have not expired")
    ap.add_argument("--nearest", action="store_true",
                    help="sort by distance from your own base (needs a placed task)")
    ap.add_argument("--limit", type=int, default=20, help="how many rows to print")
    ap.add_argument("--json", metavar="PATH", help="also write the full list as JSON")
    ap.add_argument("--share-args", action="store_true",
                    help="print ready chat_send.py arguments for the first row")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ev = lua_client.get_evaluator()
    tasks, now_ms = read_tasks(ev)

    if args.own:
        tasks = [t for t in tasks if t["kind"] == "own"]
    if args.alliance:
        tasks = [t for t in tasks if t["kind"] == "alliance"]
    if args.ready:
        tasks = [t for t in tasks
                 if t["done"] and t["done"] <= now_ms < (t["expires"] or 0)]

    if args.nearest:
        # Own tasks sit at pointId 0 (inside the base) and have no map position, so
        # they can never be "nearest" — they sort to the end.
        placed = [t for t in tasks if t["pointId"]]
        if placed:
            home_x, home_y = _self_base(ev)
            placed.sort(key=lambda t: max(abs(t["x"] - home_x), abs(t["y"] - home_y)))
        tasks = placed + [t for t in tasks if not t["pointId"]]

    print("%d task(s); server time %d" % (len(tasks), now_ms))
    for t in tasks[:args.limit]:
        state = "ready" if (t["done"] and t["done"] <= now_ms < (t["expires"] or 0)) else "-"
        where = coords_fmt.fmt(t["x"], t["y"], t["srv"]) if t["pointId"] else "(in base)"
        print("%-8s %-19s cfg=%-9d %-22s %-6s [%s] %s"
              % (t["kind"], t["uuid"], t["cfgId"], where, state,
                 t.get("abbr", ""), t.get("name", "")))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"now_ms": now_ms, "tasks": tasks}, fh, ensure_ascii=False, indent=2)
        print("json -> %s" % args.json)

    if args.share_args and tasks:
        t = tasks[0]
        if not t["pointId"]:
            print("first task has no map position (it sits in the base) — nothing to share")
            return 1
        print('\n--coords "%d,%d" --coord-server %d --coord-type 22 --coord-label "%s" '
              "--coord-extra '%s'"
              % (t["x"], t["y"], t["srv"], TASK_LABEL,
                 json.dumps(share_extra(t), ensure_ascii=False, separators=(",", ":"))))
    return 0


def _self_base(ev) -> tuple[int, int]:
    """Own base tile, for --nearest."""
    chunk = ('pcall(function() local tp = SceneUtils.IndexToTilePos('
             'ChatInterface.getPlayer().world_main_pos) '
             'CS.UnityEngine.Debug.LogError("ACT base="..tp.x..","..tp.y) end)')
    for ln in ev.run(chunk, MARKER, 1.2):
        if "base=" in ln:
            x, _, y = ln.split("base=", 1)[1].strip().partition(",")
            return _num(x), _num(y)
    return 0, 0


if __name__ == "__main__":
    raise SystemExit(main())
