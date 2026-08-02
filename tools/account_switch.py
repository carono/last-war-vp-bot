#!/usr/bin/env python3
r"""List the game characters this login can switch to, and switch between them.

Where they come from
--------------------
The server is asked, and it answers with the characters the account actually has:

    SFSNetwork.SendMessage(MsgDefines.AccountLoginNew)      -- "account.login.new"

The reply lands as a ``push.account.login.new`` carrying ``accountArr``, which the
client parses into ``DataCenter.AccountManager.rolesList`` — one entry per
character with ``id`` (its server), ``gameUid``, ``gameUserName``,
``gameUserLevel`` (HQ), ``zone``, ``power`` and ``alAbbr`` (alliance tag). This is
the list the game's own «Персонажи» screen draws, and the request carries only
``airKey``/``deviceId``/``type`` — no credentials, and it opens no window.

The character in play is the one whose ``id`` equals the live ``curServerId``.

Why the login cache is NOT used
-------------------------------
``AccountListManager:GetAccountInfos()`` looks like the same list and is not: it
caches *logins*, keyed by ``gameUid`` + ``serverid`` + ``urlEnv``, so every server a
character has ever connected to — the one it was created on, the one it moved to,
each cross-server event server it was pulled into — stays behind as its own row,
and abandoned characters linger for good. On the live client it held **six** rows
for **two** characters, which is exactly the bug this tool was written to stop
(#1190). It is read only by ``--cache``, to show what the game keeps.

Switching — KNOWN BROKEN, do not trust it
-----------------------------------------
:func:`switch_account` calls the login screen's account-list cell handler:

    require("...UIAccountListCell").OnBtnSelectClick({data = <AccountInfo>})

It reports ``sent`` and it does send — but a capture of that send (#1190) shows the
message it builds is ``az.account.login`` with an **empty** ``userName``, because
the handler expects ``AccountManager:SetParam`` to have been filled by the screen
first. The server answers ``120618 email format error`` and nothing switches.

The game's own route is different: the character list's cell (``UIRolesCell``)
opens ``UIRoleLogin`` for the picked role, which logs in with that role's
``loginKey`` — the field the server hands out in ``accountArr``. Wiring that up is
its own task; until then the «Switch» button reports a send that the server drops.

Usage (run under the Windows Python so it can reach the daemon)
--------------------------------------------------------------
    C:\Python312\python.exe tools\account_switch.py                 # list
    C:\Python312\python.exe tools\account_switch.py --cache         # the login cache instead
    C:\Python312\python.exe tools\account_switch.py --json          # list as JSON
    C:\Python312\python.exe tools\account_switch.py --switch 2105   # switch to server 2105
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import lua_client  # noqa: E402

MARKER = "ACT"

# The account-list cell module — its OnBtnSelectClick is the in-game "switch to this
# account" handler. Loaded on demand with require() so this works even when the
# account window has never been opened this session.
_CELL_MODULE = "UI.UIAccount2.UIAccountList.Component.UIAccountListCell"

# Ask the server for the characters. Headless: no window is opened, and the request
# carries no credentials — the game builds it from the device id.
_ASK_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..tostring(s)) end
local ok, err = pcall(function() SFSNetwork.SendMessage(MsgDefines.AccountLoginNew) end)
L("ASK "..(ok and "sent" or ("error:"..tostring(err))))
"""

# Read what came back. `rolesList` is filled by the push handler, so this is polled
# until it lands rather than read once.
_ROLES_LUA = r"""
local function hex(s) return (tostring(s):gsub('.', function(c) return string.format('%02x', c:byte()) end)) end
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..s) end
pcall(function()
  -- Which character is in play. `WorldFavoDataManager.curServerId` is empty on a
  -- freshly logged-in client, so the player's own record is asked first.
  local cur = 0
  pcall(function() cur = LuaEntry.Player.serverId end)
  if not cur or cur == 0 then
    pcall(function() cur = DataCenter.WorldFavoDataManager.curServerId end)
  end
  L("cur="..tostring(cur))
  local roles = DataCenter.AccountManager.rolesList
  if type(roles) ~= "table" then return end
  for _, v in pairs(roles) do
    -- The screen puts an `isEmpty` placeholder first (its "add a character" slot);
    -- it is not a character and carries none of the fields below.
    if type(v) == "table" and not v.isEmpty then
      L("R serverid="..tostring(v.id)
        .." gameUid="..tostring(v.gameUid)
        .." level="..tostring(v.gameUserLevel or 0)
        .." power="..tostring(v.power or 0)
        .." nick="..hex(tostring(v.gameUserName or ""))
        .." zone="..hex(tostring(v.zone or ""))
        .." alliance="..hex(tostring(v.alAbbr or "")))
    end
  end
end)
"""

# The login cache — NOT the character list (see the module docstring). Kept for
# `--cache`, which is how the six-rows-for-two-characters bug was demonstrated.
_CACHE_LUA = r"""
local function hex(s) return (tostring(s):gsub('.', function(c) return string.format('%02x', c:byte()) end)) end
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..s) end
pcall(function()
  -- Which character is in play. `WorldFavoDataManager.curServerId` is empty on a
  -- freshly logged-in client, so the player's own record is asked first.
  local cur = 0
  pcall(function() cur = LuaEntry.Player.serverId end)
  if not cur or cur == 0 then
    pcall(function() cur = DataCenter.WorldFavoDataManager.curServerId end)
  end
  L("cur="..tostring(cur))
  local infos = DataCenter.AccountListManager:GetAccountInfos()
  if type(infos) ~= "table" then return end
  for i, v in ipairs(infos) do
    L("R seq="..tostring(i)
      .." serverid="..tostring(v.serverid)
      .." gameUid="..tostring(v.gameUid)
      .." level="..tostring(v.newLevel or v.level or 0)
      .." nick="..hex(tostring(v.nickname or ""))
      .." zone="..hex(tostring(v.zone or ""))
      .." env="..hex(tostring(v.urlEnv or "")))
  end
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


def _parse_rows(lines) -> tuple[list[dict], int]:
    """The ``R``/``cur=`` lines either reader prints, as records."""
    cur = 0
    rows: list[dict] = []
    for ln in lines:
        body = ln[4:] if ln.startswith("ACT ") else ln
        if body.startswith("cur="):
            cur = _num(body[4:])
            continue
        if not body.startswith("R "):
            continue
        rec: dict = {}
        for tok in body[2:].split(" "):
            key, sep, value = tok.partition("=")
            if not sep:
                continue
            rec[key] = (_hexdec(value)
                        if key in ("nick", "zone", "env", "alliance") else value)
        row = {
            "serverid": _num(rec.get("serverid")),
            "gameUid": rec.get("gameUid", "0"),
            "level": _num(rec.get("level")),
            "nickname": rec.get("nick", ""),
            "zone": rec.get("zone", ""),
        }
        for key, name in (("power", "power"), ("alliance", "alliance"),
                          ("env", "env"), ("seq", "seq")):
            if key in rec:
                row[name] = _num(rec[key]) if key in ("power", "seq") else rec[key]
        rows.append(row)
    return rows, cur


def _sorted(rows: list[dict], cur: int) -> list[dict]:
    for r in rows:
        r["is_current"] = (r["serverid"] == cur and cur != 0)
    # Current first, then by level (strongest character next), then by server id.
    rows.sort(key=lambda r: (not r["is_current"], -r["level"], r["serverid"]))
    return rows


def read_accounts(ev, timeout: float = 6.0) -> list[dict]:
    """The characters this account has, as the server reports them.

    Sends ``account.login.new`` and waits for the push that answers it to fill
    ``rolesList`` — up to ``timeout`` seconds, since the reply is asynchronous. Each
    record: ``serverid``, ``gameUid``, ``level`` (HQ), ``nickname``, ``zone``,
    ``power``, ``alliance`` and ``is_current``. Returns ``[]`` when the game/daemon
    is unreachable, or when nothing came back inside the timeout — an empty tab is
    the honest answer there, and stale cache rows are not.
    """
    rows, cur = _parse_rows(ev.run(_ROLES_LUA, MARKER, 1.5))
    if rows:
        return _sorted(rows, cur)

    ev.run(_ASK_LUA, MARKER, 1.0)
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        time.sleep(0.5)
        rows, cur = _parse_rows(ev.run(_ROLES_LUA, MARKER, 1.5))
        if rows:
            return _sorted(rows, cur)
    return []


def read_login_cache(ev) -> list[dict]:
    """The client's cache of logins — what the tab used to draw, and why #1190.

    Not the character list: see the module docstring. One row per
    ``gameUid``+``serverid``+``urlEnv`` the client has ever connected as.
    """
    rows, cur = _parse_rows(ev.run(_CACHE_LUA, MARKER, 2.0))
    return _sorted(rows, cur)


def _switch_lua(serverid: int) -> str:
    """Lua that reconnects the client to the character on ``serverid``.

    Finds the matching ``AccountInfo`` and runs the account-list cell's own select
    handler on it. Refuses when that server is already the current one (the game
    itself blocks re-selecting the active account). Logs ``ACT SW <state>``.
    """
    return (
        'local function L(s) CS.UnityEngine.Debug.LogError("ACT SW "..tostring(s)) end '
        'local sid = %d '
        'local cur = 0 pcall(function() cur = DataCenter.WorldFavoDataManager.curServerId end) '
        'if tonumber(cur) == sid then L("already-current") return end '
        'local infos = DataCenter.AccountListManager:GetAccountInfos() '
        'local target '
        'if type(infos) == "table" then for _, v in pairs(infos) do '
        'if tonumber(v.serverid) == sid then target = v break end end end '
        'if target == nil then L("no-such-account") return end '
        'local ok, Cell = pcall(require, "%s") '
        'if not ok or type(Cell) ~= "table" or type(Cell.OnBtnSelectClick) ~= "function" then '
        'L("no-handler") return end '
        'local ok2, err = pcall(Cell.OnBtnSelectClick, {data = target, isCurrentAccount = false}) '
        'L(ok2 and "sent" or ("error:"..tostring(err)))'
        % (int(serverid), _CELL_MODULE)
    )


def switch_account(ev, serverid: int) -> str:
    """Switch the live client to the character on ``serverid``.

    Returns the outcome state logged by the game: ``sent`` (the reconnect message
    went out), ``already-current``, ``no-such-account``, ``no-handler``,
    ``error:<msg>`` or ``""`` when nothing came back.
    """
    for ln in ev.run(_switch_lua(int(serverid)), MARKER, 1.5):
        body = ln[4:] if ln.startswith("ACT ") else ln
        if body.startswith("SW "):
            return body[3:].strip()
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print the list as JSON")
    ap.add_argument("--cache", action="store_true",
                    help="print the client's login cache instead — not the character "
                         "list, and the reason this tool no longer reads it (#1190)")
    ap.add_argument("--switch", type=int, metavar="SERVERID",
                    help="switch to the character on this server id (reconnects the client)")
    args = ap.parse_args()

    ev = lua_client.get_evaluator()

    if args.switch is not None:
        state = switch_account(ev, args.switch)
        print(json.dumps({"serverid": args.switch, "state": state}) if args.json
              else f"switch {args.switch}: {state or 'no response'}")
        return 0 if state == "sent" else 1

    rows = read_login_cache(ev) if args.cache else read_accounts(ev)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("no characters (game/daemon unreachable, or the server did not answer)")
        return 0
    for r in rows:
        mark = "* " if r["is_current"] else "  "
        tail = f"  [{r['alliance']}]" if r.get("alliance") else ""
        print(f"{mark}srv {r['serverid']:<6} lvl {r['level']:<3} "
              f"{r['zone']:<10} {r['nickname']}{tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
