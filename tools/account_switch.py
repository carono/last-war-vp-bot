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

Switching
---------
:func:`switch_account` is the game's own character-screen route, run headless: the
«войти» press of the ``UIRoleLogin`` window (``UIRoleLoginView:OnClickLogin``)
writes the picked character's ``ip``/``port``/``zone``/``loginKey``/``gameUid`` over
the saved credentials and drops the session, and the client reconnects as that
character. All five fields come out of the same ``accountArr`` this tool reads, so
nothing has to be typed and no window is opened. The Lua is
``lua_actions.account_switch_press()``; the ability itself is the scenario
``actions/switch_account.md``, which is what the panel plays.

The earlier route reproduced the LOGIN screen's cell handler
(``UIAccountListCell.OnBtnSelectClick``) and is gone: it builds its message out of
``AccountManager.param``, a table only that screen fills, so from inside a session
it sent ``az.account.login`` with an empty ``userName`` and the server answered
``120618 email format error`` (#1190). It reported ``sent`` and switched nothing.

Usage (run under the Windows Python so it can reach the daemon)
--------------------------------------------------------------
    C:\Python312\python.exe tools\account_switch.py                 # list
    C:\Python312\python.exe tools\account_switch.py --cache         # the login cache instead
    C:\Python312\python.exe tools\account_switch.py --json          # list as JSON
    C:\Python312\python.exe tools\account_switch.py --switch 600   # switch to server 600
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

# Ask the server for the characters, and read back what it said. Both chunks live in
# `lua_actions` — the panel's tab and the recipe press the same ones.
_ASK_LUA = lua_actions.account_roles_request()
_ROLES_LUA = lua_actions.account_roles_dump()

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
                        if key in ("nick", "zone", "env", "alliance", "uuid", "pic")
                        else value)
        row = {
            "serverid": _num(rec.get("serverid")),
            "gameUid": rec.get("gameUid", "0"),
            "level": _num(rec.get("level")),
            "nickname": rec.get("nick", ""),
            "zone": rec.get("zone", ""),
        }
        for key, name in (("power", "power"), ("alliance", "alliance"),
                          ("uuid", "uuid"), ("pic", "pic"), ("picVer", "picVer"),
                          ("env", "env"), ("seq", "seq")):
            if key in rec:
                row[name] = (_num(rec[key]) if key in ("power", "seq", "picVer")
                             else rec[key])
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


def _read_num(ev, expr: str, tag: str) -> int:
    """Evaluate a Lua expression that returns a number, through the log marker."""
    lua = ('CS.UnityEngine.Debug.LogError("ACT %s="..tostring(%s))' % (tag, expr))
    for ln in ev.run(lua, MARKER, 1.0):
        body = ln[4:] if ln.startswith("ACT ") else ln
        if body.startswith(tag + "="):
            return _num(body[len(tag) + 1:].strip())
    return 0


def switch_account(ev, serverid: int, timeout: float = 6.0) -> str:
    """Switch the live client to the character on ``serverid``.

    Loads the character list first if the session has never asked for it, refuses
    when that server holds no character of this account or already holds the one in
    play, and otherwise fires the character screen's own login press (see the module
    docstring). Returns the outcome: ``sent`` (the client is reconnecting),
    ``already-current``, ``no-such-account`` or ``no-characters``.

    The panel does not call this — it plays ``actions/switch_account.md``, which is
    the same three steps written as a recipe. This is the command-line twin.
    """
    serverid = int(serverid)
    if not read_accounts(ev, timeout=timeout):
        return "no-characters"
    ev.run(lua_actions.account_switch_arm(serverid), MARKER, 0.3)
    state = _read_num(ev, lua_actions.account_switch_target(), "target")
    if state == 0:
        return "no-such-account"
    if state < 0:
        return "already-current"
    ev.run(lua_actions.account_switch_press(), MARKER, 1.5)
    return "sent"


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
        power = f"{r['power']:,}" if r.get("power") else "—"
        tail = f"  [{r['alliance']}]" if r.get("alliance") else ""
        print(f"{mark}srv {r['serverid']:<6} lvl {r['level']:<3} "
              f"{r['zone']:<10} {power:>14}  {r['nickname']}{tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
