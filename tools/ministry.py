#!/usr/bin/env python3
r"""Read the server's ministry board — and submit an application for a post.

What the ministry is
--------------------
The President of a server appoints eight "kingdom positions" (the in-game
«министерство»). A player asks for one by submitting an application; depending on
what the President has configured, the server either queues the applicant or grants
the post immediately.

Everything here is read straight out of the live Lua VM through the warm daemon
(tools/lua_daemon.py) — no capture, no window, no pixels:

    DataCenter.GovernmentManager
        :GetPositionInfoByPositionId(id)  -- who holds the post: name / abbr / uid /
                                             appointTime (epoch ms)
        .self_positionId                  -- the post YOU hold, if any
    DataCenter.OfficialApplyManager
        :GetApplyList(id)                 -- the applicant queue (server-fed, see below)
        :CheckCanApply(id)                -- the client's own pre-flight for applying
        :GetResignOfficeTime()            -- seconds before you may resign your post
    DataCenter.GovernmentTemplateManager
        :GetTemplateName(id)              -- the post's displayed name

Two things have to be asked for before they can be read, so this tool fires both
requests, waits one round trip and only then reads:

  * `get.kingdom.positions <your server>` — the position table holds whatever kingdom
    the client last looked at, and browsing another server (the cross-server world
    view) leaves ITS holders cached. Each row prints the server its holder's uid
    belongs to, so a stale board is visible rather than silently wrong. Several
    servers under one government is normal, not stale: a season merges a group of
    servers into one kingdom (935/972/1032 here). A board with nobody from your own
    server on it is the real stale case, and it is called out.
  * `kingdom.position.apply.list` — the applicant queues are never pushed.

Submitting an application is not affected by any of this: `kingdom.position.apply`
carries no server field and the server always applies it to your own kingdom.

The two numbers other scripts want are `queue` (how many are waiting) and `held_min`
(how many minutes the current holder has sat) — they are what a scheduling recipe
gates on when deciding *when* to apply. A recipe can read either without this tool:

    READ_LUA (function() local n=0 for _ in pairs(DataCenter.OfficialApplyManager:GetApplyList('10007') or {}) do n=n+1 end return n end)() INTO queue
    READ_LUA (DataCenter.OfficialApplyManager:CheckCanApply('10007') and 1 or 0) INTO can

Both are built by tools/lib/lua_actions.py (ministry_queue_len / ministry_can_apply /
ministry_held_minutes) so the expressions never drift. Note the QUOTES: position ids
are strings everywhere in the apply manager, and `CheckCanApply(10007)` answers a
confident, wrong `false`.

Usage (run under the Windows Python so it can reach the daemon)
--------------------------------------------------------------
    C:\Python312\python.exe tools\ministry.py
    C:\Python312\python.exe tools\ministry.py --no-refresh      # skip the server round trip
    C:\Python312\python.exe tools\ministry.py --json board.json
    C:\Python312\python.exe tools\ministry.py --apply minister_science
    C:\Python312\python.exe tools\ministry.py --apply 10007 --dry-run

Applying is the same press the DSL exposes as `TAP apply_<post>` and the
`submit_ministry.md` recipe runs; see docs/research/ministry.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import lua_actions  # noqa: E402
import lua_client  # noqa: E402

MARKER = "ACT"

# How long to give the server to answer the board requests before reading. One round
# trip; the replies are what repopulate the position table and the applicant queues.
BOARD_SETTLE = 1.6

_BOARD_LUA = r"""
local function hex(s) return (tostring(s):gsub('.', function(c) return string.format('%02x', c:byte()) end)) end
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..s) end
pcall(function()
  local M = DataCenter.OfficialApplyManager
  local G = DataCenter.GovernmentManager
  local T = DataCenter.GovernmentTemplateManager
  L("now="..tostring(UITimeManager.Instance:GetSocketTime()))
  local uid = tostring(select(2, pcall(function() return DataCenter.PlayerInfoDataManager:GetSelfUid() end)))
  L("self pos="..tostring(G.self_positionId or 0)
    .." home="..tostring(tonumber(uid:sub(-6)) or 0)
    .." viewing="..tostring(G.curDataServerId or 0)
    .." resign="..tostring(select(2, pcall(function() return M:GetResignOfficeTime() end))))
  for _, id in pairs(M:GetCanApplyGovernmentList() or {}) do
    local info = G:GetPositionInfoByPositionId(id)
    local queue, mine = 0, -1
    for _ in pairs(M:GetApplyList(id) or {}) do queue = queue + 1 end
    pcall(function() mine = M:GetApplyListOwnIndex(id) end)
    L("P id="..tostring(id)
      .." title="..hex(tostring(select(2, pcall(function() return T:GetTemplateName(id) end)) or ""))
      .." holder="..hex(tostring(info and info.name or ""))
      .." abbr="..hex(tostring(info and info.abbr or ""))
      .." uid="..tostring(info and info.uid or 0)
      .." since="..tostring(info and info.appointTime or 0)
      .." queue="..tostring(queue)
      .." myIndex="..tostring(mine)
      .." canApply="..tostring(M:CheckCanApply(id) and 1 or 0)
      .." lastApply="..tostring((M.ownApplyTimeList or {})[id] or 0))
  end
end)
"""


def _hexdec(h: str) -> str:
    try:
        return bytes.fromhex(h).decode("utf-8", "replace")
    except ValueError:
        return ""


def _num(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def read_board(ev, refresh: bool = True) -> dict:
    """The whole board: `{now_ms, self_position, resign_in, posts: [...]}`.

    `refresh` reloads our own kingdom's holders and asks for the applicant queues
    first. Without it the `queue` column reflects whatever the client had cached
    (usually nothing) and the holders may belong to a server the player was merely
    browsing — only turn it off when the caller has just refreshed by other means.
    """
    if refresh:
        ev.run(lua_actions.ministry_fetch_board(), MARKER, 0.2)
        time.sleep(BOARD_SETTLE)

    board = {"now_ms": 0, "self_position": 0, "home_server": 0, "viewing_server": 0,
             "resign_in": 0, "posts": []}
    for ln in ev.run(_BOARD_LUA, MARKER, 1.4):
        body = ln[4:] if ln.startswith("ACT ") else ln
        if body.startswith("now="):
            board["now_ms"] = _num(body[4:])
        elif body.startswith("self "):
            _keys = {"pos": "self_position", "home": "home_server",
                     "viewing": "viewing_server", "resign": "resign_in"}
            for tok in body[5:].split(" "):
                key, _, value = tok.partition("=")
                if key in _keys:
                    board[_keys[key]] = _num(value)
        elif body.startswith("P "):
            rec = {}
            for tok in body[2:].split(" "):
                key, sep, value = tok.partition("=")
                if not sep:
                    continue
                rec[key] = _hexdec(value) if key in ("title", "holder", "abbr") else _num(value)
            # A uid ends in its six-digit server number, so every row says out loud which
            # kingdom's holder it describes — the one check that catches a board left
            # over from browsing someone else's server.
            rec["srv"] = rec.get("uid", 0) % 1000000
            board["posts"].append(rec)
    board["posts"].sort(key=lambda p: p.get("id", 0))
    return board


def held_minutes(post: dict, now_ms: int) -> float:
    """Minutes the current holder has sat, or -1 for a vacant / unloaded post."""
    since = post.get("since", 0)
    if not since or not now_ms:
        return -1.0
    return max(0.0, (now_ms - since) / 60000.0)


def apply_for(ev, position_id: int) -> None:
    """Submit an application for `position_id` (gated by the client's CheckCanApply)."""
    ev.run(lua_actions.ministry_apply(position_id), MARKER, 1.2)


def resolve_post(token: str) -> int:
    """Accept either a numeric id (10007) or a slug (minister_interior)."""
    token = token.strip().lower()
    if token.isdigit():
        pid = int(token)
        if pid not in lua_actions.MINISTRY_POSTS:
            raise SystemExit("unknown position id %d (known: %s)"
                             % (pid, ", ".join(str(k) for k in lua_actions.MINISTRY_POSTS)))
        return pid
    token = token.removeprefix("apply_")
    if token not in lua_actions.MINISTRY_SLUGS:
        raise SystemExit("unknown post %r (known: %s)"
                         % (token, ", ".join(sorted(lua_actions.MINISTRY_SLUGS))))
    return lua_actions.MINISTRY_SLUGS[token]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", metavar="POST",
                    help="submit an application: a slug (minister_science) or an id (10006)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --apply: print the post and the gate, send nothing")
    ap.add_argument("--no-refresh", action="store_true",
                    help="do not ask the server for the applicant queues first")
    ap.add_argument("--json", metavar="PATH", help="also write the board as JSON")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ev = lua_client.get_evaluator()

    if args.apply:
        pid = resolve_post(args.apply)
        slug, en, ru = lua_actions.MINISTRY_POSTS[pid]
        board = read_board(ev, refresh=not args.no_refresh)
        post = next((p for p in board["posts"] if p.get("id") == pid), {})
        gate = post.get("canApply", 0)
        print("%d %s (%s) — canApply=%d, queue=%d, holder %s [%s]"
              % (pid, en, ru, gate, post.get("queue", 0),
                 post.get("holder", "") or "(vacant)", post.get("abbr", "")))
        if args.dry_run:
            print("dry run — nothing sent")
            return 0
        if not gate:
            print("the client refuses this application (already holding a post, on "
                  "cooldown, or the post is closed) — nothing sent")
            return 1
        apply_for(ev, pid)
        after = read_board(ev, refresh=False)
        print("self position now: %d (was %d)"
              % (after.get("self_position", 0), board.get("self_position", 0)))
        return 0

    board = read_board(ev, refresh=not args.no_refresh)
    now = board["now_ms"]
    print("server %d; your post: %s; resign lock %ds"
          % (board["home_server"], board["self_position"] or "-", board["resign_in"]))
    print("%-7s %-26s %-18s %-6s %-8s %-6s %-6s %s"
          % ("id", "post", "holder", "abbr", "held,min", "queue", "srv", "canApply"))
    seen = set()
    for p in board["posts"]:
        held = held_minutes(p, now)
        srv = p.get("srv", 0)
        if srv:
            seen.add(srv)
        print("%-7d %-26s %-18s %-6s %-8s %-6d %-6s %s"
              % (p.get("id", 0), p.get("title", ""), p.get("holder", "") or "(vacant)",
                 p.get("abbr", ""), "-" if held < 0 else "%.0f" % held,
                 p.get("queue", 0), srv or "-", "yes" if p.get("canApply") else "no"))
    # A season merges several servers into one kingdom group under a single government,
    # so holders from neighbouring servers are normal — what is NOT normal is a board
    # with nobody from our own server on it, which means we are looking at a kingdom
    # the player merely browsed (the cross-server world view leaves it cached).
    if seen and board["home_server"] not in seen:
        print("WARNING: no post on this board is held by anyone from server %d — this is "
              "another kingdom's ministry, left over from browsing it (viewing=%s). "
              "Applying is unaffected (kingdom.position.apply carries no server and "
              "always lands on your own), but the holder and queue columns are not yours."
              % (board["home_server"], board["viewing_server"]))
    elif len(seen) > 1:
        print("kingdom group: %s (a season merges servers under one government)"
              % ", ".join(str(s) for s in sorted(seen)))

    if args.json:
        for p in board["posts"]:
            p["held_min"] = held_minutes(p, now)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(board, fh, ensure_ascii=False, indent=2)
        print("json -> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
