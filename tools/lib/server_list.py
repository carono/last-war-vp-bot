#!/usr/bin/env python3
r"""Every warzone the game has, read out of the running client — and kept.

The game opens warzones continuously: the client that wrote this note was told about
**2 558** of them, and the number only ever goes up. The whole list is one question the
client already knows how to ask — `cross.server.ls` (`MsgDefines.CrossServerList`) — and
the reply is a flat list of

    {id = 3, name = "State#3", server_type = 0, hot = false}

and nothing else. No dates, no population, no state: those are separate questions, and
the only one of them that is cheap enough to ask about every warzone is the opening
moment (`get.other.server.info`, docs/research/server-info.md), which the client parks in
`LuaEntry.Player.otherServerOpenTimeDict` as the answers arrive.

**Asking for the dates is a batch, and it is fast.** Measured live on 2026-08-16: 50
requests came back inside two seconds and 300 inside three, with no error and no
throttling — so the whole list is a handful of batches rather than an afternoon. It is
still thousands of messages, so nothing here asks for them unless somebody presses for
them, and what comes back is written down (:func:`save`) so it is asked once.

**The cache is the MACHINE's, not an account's.** Which warzones exist is a fact about
the game, identical for every profile on the computer, so it lives beside the players'
faces in `game_paths.cache_dir()` rather than in a profile's directory (`CLAUDE.md`: ask
whether there is one of these per machine or per account — this is per machine).

Nothing in this module touches Tk, the panel or a profile: it is Lua text, a parser and a
JSON file, so it runs under any python and is tested without a game.
"""
from __future__ import annotations

import json
import os
import time

#: The marker every chunk here tags its output with.
MARKER = "SRVLIST"

#: How many warzones go on one line of output. The evaluator reads the answer line by
#: line; 120 entries of `id~name~type~hot` is a comfortable few kilobytes.
BATCH = 120

#: How many opening moments are asked for in one go. 300 was measured live and answered
#: in full inside three seconds; the batching exists so a run can be interrupted between
#: batches and so a slow answer is noticed while there is still something to wait for.
ASK_BATCH = 300

#: Field and record separators for the packed lines. A warzone's name is the game's own
#: (`State#<id>`) and has never contained either, but it is sanitised on the way out
#: anyway — a name that ate a separator would shift every field after it.
FIELD = "~"
RECORD = ";"

#: What `server_type` has been seen to be. The list is data, not a guess: `0` is the
#: ordinary warzone (2 497 of them on the read that wrote this), and `6` and `8` are the
#: two the same read carried without saying what they mean. They are passed through
#: untouched rather than translated, so a reader sees the game's own number.
TYPE_ORDINARY = 0


def fetch_chunk() -> str:
    """Ask the game for the whole list, the way the cross-server screen asks.

    One message. The reply lands in the client's own handler, and this module reads it
    back out of the manager the handler filled, so the chunk that ASKS and the chunk that
    READS are deliberately separate calls — the answer needs a moment on the wire.
    """
    return (
        "pcall(function() SFSNetwork.SendMessage(MsgDefines.CrossServerList) end) "
        'CS.UnityEngine.Debug.LogError("%s asked")' % MARKER
    )


def install_chunk() -> str:
    """Keep the next `cross.server.ls` reply where a read can find it.

    The client does not keep the list: `cross.server.ls` is drawn straight onto the
    screen that asked, and by the time anybody looks the reply is gone. So the answer is
    caught on its way past — one wrapper on `SFSNetwork.HandleMessage`, installed once
    per client and never wrapped twice, which parks the reply in `DataCenter` and hands
    it on untouched.

    `LW_ANSWER_VIA_GAME_LOG` is not needed here (nothing logs later); what matters is
    that the wrapper is idempotent, because a panel that re-armed it on every read would
    stack a new closure on the client every time.
    """
    return (
        "local D = DataCenter "
        "if not D.__lw_srvlist_hooked then "
        "  local orig = SFSNetwork.HandleMessage "
        "  D.__lw_srvlist_orig = orig "
        "  SFSNetwork.HandleMessage = function(cmd, obj, ...) "
        "    pcall(function() if cmd == 'cross.server.ls' then D.__lw_srvlist = obj end end) "
        "    return orig(cmd, obj, ...) "
        "  end "
        "  D.__lw_srvlist_hooked = true "
        "end "
        'CS.UnityEngine.Debug.LogError("%s armed")' % MARKER
    )


def read_chunk(offset: int = 0, limit: int = BATCH) -> str:
    """Read `limit` warzones from `offset` — `SRVLIST n=<total> …` then packed lines.

    The total comes first and on its own line, so a caller knows how many pages to ask
    for before it has read any of them. Each following line is up to `limit` records of
    `id~name~type~hot`, separated by `;`.
    """
    return (
        "local D = DataCenter "
        "local raw = D.__lw_srvlist "
        "local list = raw and raw.list "
        "if not list then CS.UnityEngine.Debug.LogError('%(m)s n=-1') return end "
        "local all = {} "
        "for _, e in pairs(list) do all[#all+1] = e end "
        "table.sort(all, function(a, b) return (tonumber(a.id) or 0) < (tonumber(b.id) or 0) end) "
        "CS.UnityEngine.Debug.LogError('%(m)s n=' .. #all) "
        "local out = {} "
        "for i = %(off)d + 1, math.min(#all, %(off)d + %(lim)d) do "
        "  local e = all[i] "
        "  local name = tostring(e.name or '') "
        "  name = name:gsub('[%(fs)s%(rs)s]', '_') "
        "  out[#out+1] = tostring(math.floor(tonumber(e.id) or 0)) .. '%(fs)s' .. name "
        "    .. '%(fs)s' .. tostring(math.floor(tonumber(e.server_type) or 0)) "
        "    .. '%(fs)s' .. (e.hot and '1' or '0') "
        "end "
        "if #out > 0 then CS.UnityEngine.Debug.LogError('%(m)s page ' .. table.concat(out, '%(rs)s')) end"
        % {"m": MARKER, "off": int(max(0, offset)), "lim": int(max(1, limit)),
           "fs": FIELD, "rs": RECORD}
    )


def ask_dates_chunk(ids) -> str:
    """Ask the server when each of these warzones opened. One message per warzone.

    The answers do not come back here — the client's own handler parks each one in
    `LuaEntry.Player.otherServerOpenTimeDict` (docs/research/server-info.md) — so a
    caller sends a batch, waits, and then reads the dictionary with :func:`read_dates_chunk`.
    """
    wanted = ",".join(str(int(i)) for i in ids)
    return (
        "local ids = {%s} "
        "for _, id in ipairs(ids) do "
        "  pcall(function() SFSNetwork.SendMessage(MsgDefines.GetOtherServerInfo, id) end) "
        "end "
        "CS.UnityEngine.Debug.LogError('%s asked=' .. #ids)" % (wanted, MARKER)
    )


def read_dates_chunk(ids=None, offset: int = 0, limit: int = BATCH) -> str:
    """Read the opening moments the client holds — `id~ms` records, and the day of each.

    The day number is the CLIENT's own arithmetic (`GetServerOpenDaysByTimeStamp`), so
    what the grid shows is what the game would draw. A warzone the client has no answer
    for is simply absent rather than reported as day zero.

    `ids` narrows the read to the warzones just asked about. Without it the whole
    dictionary is read back, which is right for one final sweep and quadratic when it is
    done after every batch — the dictionary keeps everything every earlier batch put in
    it, so a caller working through thousands asks only for what it just sent.
    """
    narrow = ""
    keep_open, keep_close = "", ""
    own_line = ("local mine = tonumber(P.openServerTime) or 0 "
                "if own > 0 and mine > 0 and d[own] == nil then "
                "all[#all+1] = {id = own, ms = math.floor(mine)} end ")
    if ids:
        narrow = ("local pick = {} for _, id in ipairs({%s}) do pick[id] = true end "
                  % ",".join(str(int(i)) for i in ids))
        keep_open = "if pick[tonumber(id) or 0] then "
        keep_close = "end "
        # The account's own warzone is only worth adding when the caller asked about it.
        own_line = ("local mine = tonumber(P.openServerTime) or 0 "
                    "if own > 0 and mine > 0 and pick[own] and d[own] == nil then "
                    "all[#all+1] = {id = own, ms = math.floor(mine)} end ")
    body = (
        "local P = LuaEntry.Player "
        "local T = UITimeManager:GetInstance() "
        "local d = P.otherServerOpenTimeDict or {} "
        "local own = tonumber(P.serverId) or 0 "
        + narrow +
        "local all = {} "
        "for id, ms in pairs(d) do "
        + keep_open +
        "local n = tonumber(ms) or 0 "
        "if n > 0 then all[#all+1] = {id = tonumber(id) or 0, ms = math.floor(n)} end "
        + keep_close +
        "end "
        + own_line +
        "table.sort(all, function(a, b) return a.id < b.id end) "
        "CS.UnityEngine.Debug.LogError('%(m)s dates=' .. #all) "
        "local out = {} "
        "for i = %(off)d + 1, math.min(#all, %(off)d + %(lim)d) do "
        "  local e = all[i] "
        "  local day = -1 "
        "  local ok, v = pcall(function() return T:GetServerOpenDaysByTimeStamp(e.ms) end) "
        "  if ok and tonumber(v) then day = math.floor(tonumber(v)) end "
        "  out[#out+1] = e.id .. '%(fs)s' .. e.ms .. '%(fs)s' .. day "
        "end "
        "if #out > 0 then CS.UnityEngine.Debug.LogError('%(m)s dpage ' .. table.concat(out, '%(rs)s')) end"
    )
    return body % {"m": MARKER, "off": int(max(0, offset)), "lim": int(max(1, limit)),
                   "fs": FIELD, "rs": RECORD}


# ---------------------------------------------------------------------------
# Parsing

def _payloads(lines, word: str):
    """The bodies of `MARKER <word> …` lines, in order."""
    head = "%s %s " % (MARKER, word)
    for line in lines or ():
        idx = line.find(head)
        if idx >= 0:
            yield line[idx + len(head):].strip()


def total(lines) -> int:
    """How many warzones the client says it has, or -1 when it never answered."""
    head = "%s n=" % MARKER
    for line in lines or ():
        idx = line.find(head)
        if idx >= 0:
            tail = line[idx + len(head):].split()[0]
            try:
                return int(tail)
            except ValueError:
                return -1
    return -1


def parse_page(lines) -> list:
    """`[{id, name, type, hot}, …]` out of whatever pages these lines carry."""
    out = []
    for payload in _payloads(lines, "page"):
        for record in payload.split(RECORD):
            parts = record.split(FIELD)
            if len(parts) < 4:
                continue
            try:
                server = int(parts[0])
            except ValueError:
                continue
            out.append({"id": server, "name": parts[1],
                        "type": int(parts[2]) if parts[2].lstrip("-").isdigit() else 0,
                        "hot": parts[3] == "1"})
    return out


def parse_dates(lines) -> dict:
    """`{id: {"open_ms": …, "day": …}}` out of whatever date pages these lines carry."""
    out = {}
    for payload in _payloads(lines, "dpage"):
        for record in payload.split(RECORD):
            parts = record.split(FIELD)
            if len(parts) < 3:
                continue
            try:
                server, ms, day = int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                continue
            if ms <= 0:
                continue
            out[server] = {"open_ms": ms, "day": day if day >= 0 else None}
    return out


# ---------------------------------------------------------------------------
# The cache

def cache_path() -> str:
    """Where the list is kept — one file for the machine, beside the other downloads."""
    try:
        import game_paths
        base = game_paths.cache_dir()
    except Exception:                    # noqa: BLE001 — a cache, never the read
        base = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "cache")
    return os.path.join(base, "servers.json")


def load(path: str | None = None) -> dict:
    """The saved list — `{"read_at": …, "dated_at": …, "servers": {id: {…}}}`.

    An unreadable or missing file is an EMPTY list and never an error: the panel opens
    on a machine that has never asked, and «nothing yet» is a state it draws.
    """
    try:
        with open(path or cache_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:                    # noqa: BLE001
        return {"read_at": 0, "dated_at": 0, "servers": {}}
    if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
        return {"read_at": 0, "dated_at": 0, "servers": {}}
    return data


def merge(saved: dict, servers=(), dates=None, now: float | None = None) -> dict:
    """Fold a fresh reading into the saved one. Nothing known is ever forgotten.

    Warzones only ever appear, so a read that brought fewer than are on file is a read
    that was interrupted — not a list that shrank — and dropping the missing ones would
    lose them until somebody re-read the lot. The same holds for the dates, which are
    asked for in batches and arrive over several runs: a warzone whose date is not in
    THIS batch keeps the one it had.
    """
    stamp = int(now if now is not None else time.time())
    out = {"read_at": int(saved.get("read_at") or 0),
           "dated_at": int(saved.get("dated_at") or 0),
           "servers": dict(saved.get("servers") or {})}
    for entry in servers or ():
        key = str(entry["id"])
        row = dict(out["servers"].get(key) or {})
        row.update({"id": entry["id"], "name": entry.get("name") or row.get("name") or "",
                    "type": entry.get("type", row.get("type", 0)),
                    "hot": bool(entry.get("hot", row.get("hot", False)))})
        out["servers"][key] = row
    if servers:
        out["read_at"] = stamp
    for server, fields in (dates or {}).items():
        key = str(server)
        row = dict(out["servers"].get(key) or {"id": int(server), "name": "", "type": 0,
                                               "hot": False})
        row["open_ms"] = fields.get("open_ms")
        if fields.get("day") is not None:
            row["day"] = fields["day"]
        out["servers"][key] = row
    if dates:
        out["dated_at"] = stamp
    return out


def save(data: dict, path: str | None = None) -> str:
    """Write the cache out, making its directory if this machine has never had one."""
    target = path or cache_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(tmp, target)
    return target


def rows(data: dict) -> list:
    """The cache as a list of rows, lowest warzone first — what a grid draws."""
    out = list((data.get("servers") or {}).values())
    out.sort(key=lambda row: int(row.get("id") or 0))
    return out


def undated(data: dict) -> list:
    """The warzones whose opening moment nobody has asked for yet, lowest id first."""
    return [int(row["id"]) for row in rows(data) if not row.get("open_ms")]


# ---------------------------------------------------------------------------
# How it is SHOWN. Here and not in the panel because both front-ends draw the same
# rows — the window's grid (`panel/runtime/servers_dialog.py`) and the phone's screen
# (`panel/web/api.py`) — and a view built twice is a view that drifts. The only panel
# thing in it is a locale KEY for the kind of warzone, which is a name for a number the
# game refuses to explain rather than a sentence.

#: The columns of the window's grid, in order: the locale key of the heading, the row's
#: field, the width in pixels, and whether it sorts as a number.
COLUMNS = (("servers.col.id", "id", 70, True),
           ("servers.col.name", "name", 150, False),
           ("servers.col.kind", "kind", 90, False),
           ("servers.col.opened", "opened", 150, False),
           ("servers.col.day", "day", 80, True))


def kind_key(kind) -> str:
    """The locale key for a `server_type`. The game gives a number and no word for it.

    Two of the three numbers seen live (`6` and `8`, against 2 497 ordinary ones) are the
    game's own and it says nothing about what they mean, so they share one word rather
    than being guessed at — and the NUMBER is still on the row for anyone who cares.
    """
    try:
        value = int(kind)
    except (TypeError, ValueError):
        return "servers.kind.other"
    return "servers.kind.ordinary" if value == 0 else "servers.kind.other"


def stamp(ms) -> str:
    """A game-clock millisecond as a date, or an em dash when there is none.

    The milliseconds are the GAME's (docs/research/game-clock.md); nothing here supplies
    a clock of its own, it only renders what the client said.
    """
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "—"
    return time.strftime("%Y-%m-%d", time.gmtime(value / 1000.0))


def view_rows(data: dict, needle: str = "", undated_only: bool = False) -> list:
    """The cache as drawable rows — filtered, with the display fields filled in."""
    needle = str(needle or "").strip().lower()
    out = []
    for row in rows(data):
        if undated_only and row.get("open_ms"):
            continue
        if needle:
            hay = "%s %s" % (row.get("id"), row.get("name") or "")
            if needle not in hay.lower():
                continue
        out.append({"id": row.get("id"), "name": row.get("name") or "",
                    "type": row.get("type", 0), "hot": bool(row.get("hot")),
                    "open_ms": row.get("open_ms"), "day": row.get("day"),
                    "opened": stamp(row.get("open_ms")),
                    "kind_key": kind_key(row.get("type"))})
    return out


def sorted_rows(rows, field: str = "id", down: bool = False) -> list:
    """`rows` in the order a column heading asks for. Missing values sort last — BOTH ways.

    «Last whichever way the column is turned» is the whole point, and it is why the
    unknowns are held out rather than given a sort key: a warzone nobody has asked a date
    for has `None`, and folding that into the key puts every unknown at the TOP the moment
    somebody clicks the heading twice — a grid that reads as «these opened most recently»
    about the ones the panel knows nothing about.
    """
    numeric = {name: is_num for _key, name, _width, is_num in COLUMNS}
    known = [row for row in rows if row.get(field) is not None]
    unknown = [row for row in rows if row.get(field) is None]

    def key(row):
        value = row.get(field)
        return value if numeric.get(field) else str(value).lower()

    return sorted(known, key=key, reverse=down) + unknown


def summary(data: dict) -> dict:
    """How many warzones are on file, how many are dated, and when it was last read."""
    known = rows(data)
    dated = sum(1 for row in known if row.get("open_ms"))
    return {"total": len(known), "dated": dated, "undated": len(known) - dated,
            "read_at": int(data.get("read_at") or 0),
            "dated_at": int(data.get("dated_at") or 0)}
