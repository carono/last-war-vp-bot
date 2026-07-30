#!/usr/bin/env python3
r"""List the game characters this login can switch to, and switch between them.

Where they come from
--------------------
The game keeps every character you have logged into cached in

    DataCenter.AccountListManager:GetAccountInfos()

one ``AccountInfo`` per server login, carrying ``serverid``, ``nickname`` (the
character's in-game name), ``gameUid``, ``newLevel`` (HQ level), ``zone`` and the
connection routing. This is exactly the list the in-game «Account» screen shows
when you tap your avatar. The character you are playing right now is the one whose
``serverid`` equals the live ``curServerId``.

Switching
---------
Tapping a row on that screen runs the account-list cell's own select handler,
which builds an ``az.account.login`` message from the picked ``AccountInfo`` and
sends it — the client then reconnects to that server as that character. This tool
reproduces the tap faithfully by calling the game's own handler with the target
``AccountInfo`` (no hand-built payload):

    require("...UIAccountListCell").OnBtnSelectClick({data = <AccountInfo>})

Because a switch tears down the current game session and reconnects, it is a heavy,
one-way action: after it fires the warm daemon's client is on a different character.

Usage (run under the Windows Python so it can reach the daemon)
--------------------------------------------------------------
    C:\Python312\python.exe tools\account_switch.py                 # list
    C:\Python312\python.exe tools\account_switch.py --json          # list as JSON
    C:\Python312\python.exe tools\account_switch.py --switch 2105   # switch to server 2105
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import lua_client  # noqa: E402

MARKER = "ACT"

# The account-list cell module — its OnBtnSelectClick is the in-game "switch to this
# account" handler. Loaded on demand with require() so this works even when the
# account window has never been opened this session.
_CELL_MODULE = "UI.UIAccount2.UIAccountList.Component.UIAccountListCell"

_READ_LUA = r"""
local function hex(s) return (tostring(s):gsub('.', function(c) return string.format('%02x', c:byte()) end)) end
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..s) end
pcall(function()
  local cur = 0
  pcall(function() cur = DataCenter.WorldFavoDataManager.curServerId end)
  L("cur="..tostring(cur))
  local infos = DataCenter.AccountListManager:GetAccountInfos()
  if type(infos) ~= "table" then return end
  for _, v in pairs(infos) do
    L("A serverid="..tostring(v.serverid)
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


def read_accounts(ev) -> list[dict]:
    """The cached characters this login can switch to, current one flagged.

    Each record: ``serverid``, ``gameUid``, ``level`` (HQ), ``nickname``, ``zone``,
    ``env`` and ``is_current``. Returns ``[]`` when the game/daemon is unreachable or
    the manager is not loaded yet.
    """
    cur = 0
    rows: list[dict] = []
    for ln in ev.run(_READ_LUA, MARKER, 2.0):
        body = ln[4:] if ln.startswith("ACT ") else ln
        if body.startswith("cur="):
            cur = _num(body[4:])
            continue
        if not body.startswith("A "):
            continue
        rec: dict = {}
        for tok in body[2:].split(" "):
            key, sep, value = tok.partition("=")
            if not sep:
                continue
            rec[key] = _hexdec(value) if key in ("nick", "zone", "env") else value
        rows.append({
            "serverid": _num(rec.get("serverid")),
            "gameUid": rec.get("gameUid", "0"),
            "level": _num(rec.get("level")),
            "nickname": rec.get("nick", ""),
            "zone": rec.get("zone", ""),
            "env": rec.get("env", ""),
        })
    for r in rows:
        r["is_current"] = (r["serverid"] == cur and cur != 0)
    # Current first, then by level (strongest character next), then by server id.
    rows.sort(key=lambda r: (not r["is_current"], -r["level"], r["serverid"]))
    return rows


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
    ap.add_argument("--switch", type=int, metavar="SERVERID",
                    help="switch to the character on this server id (reconnects the client)")
    args = ap.parse_args()

    ev = lua_client.get_evaluator()

    if args.switch is not None:
        state = switch_account(ev, args.switch)
        print(json.dumps({"serverid": args.switch, "state": state}) if args.json
              else f"switch {args.switch}: {state or 'no response'}")
        return 0 if state == "sent" else 1

    rows = read_accounts(ev)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("no accounts (game/daemon unreachable, or the account manager is not loaded)")
        return 0
    for r in rows:
        mark = "* " if r["is_current"] else "  "
        print(f"{mark}srv {r['serverid']:<6} lvl {r['level']:<3} "
              f"{r['zone']:<10} {r['nickname']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
