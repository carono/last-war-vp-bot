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
    empty = {"read_at": 0, "dated_at": 0, "seasoned_at": 0, "servers": {}}
    try:
        with open(path or cache_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:                    # noqa: BLE001
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
        return empty
    data.setdefault("seasoned_at", 0)
    return data


def merge(saved: dict, servers=(), dates=None, seasons=None, now: float | None = None) -> dict:
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
           "seasoned_at": int(saved.get("seasoned_at") or 0),
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
    for server, fields in (seasons or {}).items():
        key = str(server)
        row = dict(out["servers"].get(key) or {"id": int(server), "name": "", "type": 0,
                                               "hot": False})
        # FOLDED, not replaced: the own-warzone read carries better numbers for three of
        # these fields and says nothing about the rest, and a plain assignment would drop
        # the calendar dates it does not mention.
        season = dict(row.get("season") or {})
        season.update(fields)
        row["season"] = season
        out["servers"][key] = row
    if seasons:
        out["seasoned_at"] = stamp
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
COLUMNS = (("servers.col.id", "id", 65, True),
           ("servers.col.name", "name", 110, False),
           ("servers.col.kind", "kind", 70, False),
           ("servers.col.opened", "opened", 95, False),
           ("servers.col.day", "day", 55, True),
           ("servers.col.season", "step", 60, False),
           ("servers.col.stage", "stage", 100, False),
           ("servers.col.until", "until", 95, False),
           # The star-secret-task day (#1467) — a state of its own next to the season's,
           # because it answers a different question on a different cycle: what the
           # warzone is doing TODAY rather than which month of the season it is in.
           ("servers.col.secret", "secret", 105, False),
           ("servers.col.secret_until", "secret_until", 95, False))


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


def view_rows(data: dict, needle: str = "", undated_only: bool = False,
              now_ms=None) -> list:
    """The cache as drawable rows — filtered, with the display fields filled in.

    `now_ms` is the GAME's clock (`tools/lib/game_clock.py`), which decides which stage of
    its season each warzone is standing in. Left out, the stage of every row reads as
    unknown rather than being judged against this machine's clock — the two are not the
    same clock and the panel has one place that knows the difference.
    """
    needle = str(needle or "").strip().lower()
    out = []
    for row in rows(data):
        if undated_only and row.get("open_ms"):
            continue
        if needle:
            hay = "%s %s" % (row.get("id"), row.get("name") or "")
            if needle not in hay.lower():
                continue
        season = row.get("season") or {}
        stage = stage_of(season, now_ms) if season else STAGE_UNKNOWN
        turns = next_change(season, now_ms) if season else None
        out.append({"id": row.get("id"), "name": row.get("name") or "",
                    "type": row.get("type", 0), "hot": bool(row.get("hot")),
                    "open_ms": row.get("open_ms"), "day": row.get("day"),
                    "opened": stamp(row.get("open_ms")),
                    "kind_key": kind_key(row.get("type")),
                    "season_id": season.get("season_id"),
                    "season_day": season.get("season_day"),
                    "step": season.get("step") or None,
                    "stage": stage,
                    "stage_key": "servers.stage.%s" % stage,
                    "until_ms": turns,
                    "until": stamp(turns)})
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
    seasoned = sum(1 for row in known if row.get("season"))
    return {"total": len(known), "dated": dated, "undated": len(known) - dated,
            "seasoned": seasoned,
            "read_at": int(data.get("read_at") or 0),
            "dated_at": int(data.get("dated_at") or 0),
            "seasoned_at": int(data.get("seasoned_at") or 0)}


# ---------------------------------------------------------------------------
# THE SEASON, and which stage of it a warzone is standing in (#1419).
#
# The client ships the whole season plan as a config table — `LW_Season`, 1 248 rows,
# held by `DataCenter.SeasonTemplateManager` — and it answers PER WARZONE:
# `GetConfigDataByServerId(<id>)` returns the row that names that warzone's current
# season, whichever warzone it is. So the seasons of every server in the list are read
# out of the client with NO message on the wire at all, which is what makes this
# affordable for 2 558 of them (docs/research/server-events.md).
#
# A row carries four moments as calendar strings — «pre_start_time», «start_time_str»,
# «settlement_time», «end_time» — plus `season_step`, the Roman numeral the game itself
# prints («V», «Ⅵ»), and the season's id. The four moments are what the stages are made
# of, and they are CALENDAR DATES: the config gives them to the day, the pair
# (`start_time` unix / `start_time_str` text) does not agree on the hour on any warzone
# checked, and nothing here pretends to a precision the table does not have. For the
# account's OWN warzone the client also holds exact milliseconds
# (`SeasonDataManager:GetSeasonStartTime` and friends) and those are read beside it.

#: The stages of a season, in the order a warzone passes through them.
STAGE_PRE = "pre"          # the pre-season is on: preparation, no war yet
STAGE_SEASON = "season"    # the season proper
STAGE_SETTLE = "settle"    # settlement: the scores are being counted
STAGE_OFF = "off"          # between seasons — the post-season lull
STAGE_UNKNOWN = "unknown"  # nothing read about this warzone yet

#: How many warzones are asked about in one chunk. This costs no wire traffic — it is a
#: table lookup per warzone — so the only limit is how long one answer line may be.
SEASON_BATCH = 100


def season_chunk(ids) -> str:
    """Read the season row of each of these warzones — `SRVLIST spage …` lines.

    Every field is taken with `getValue`, which is the accessor the row actually answers:
    a plain `row.pre_start_time` works on one call and is `nil` on the next, because the
    row fills itself lazily (measured live — the first probe read it, the second did not).
    """
    wanted = ",".join(str(int(i)) for i in ids)
    return (
        "local M = DataCenter.SeasonTemplateManager "
        "local out = {} "
        "local function val(row, name) "
        "  local v = nil "
        "  local ok = pcall(function() v = row:getValue(name) end) "
        "  if not ok or v == nil then pcall(function() v = row[name] end) end "
        "  if v == nil or type(v) == 'table' then return '' end "
        "  return tostring(v):gsub('[%(fs)s%(rs)s]', ' ') "
        "end "
        "for _, sid in ipairs({%(ids)s}) do "
        "  local row = nil "
        "  pcall(function() row = M:GetConfigDataByServerId(sid) end) "
        "  if row ~= nil then "
        "    out[#out+1] = sid .. '%(fs)s' .. tostring(val(row, 'id')) "
        "      .. '%(fs)s' .. val(row, 'season_step') "
        "      .. '%(fs)s' .. val(row, 'pre_start_time') "
        "      .. '%(fs)s' .. val(row, 'start_time_str') "
        "      .. '%(fs)s' .. val(row, 'settlement_time') "
        "      .. '%(fs)s' .. val(row, 'end_time') "
        "  end "
        "end "
        "if #out > 0 then CS.UnityEngine.Debug.LogError('%(m)s spage ' .. table.concat(out, '%(rs)s')) end "
        # …and, for the account's OWN warzone, the exact numbers the client holds beside
        # the plan: the config gives calendar dates, `SeasonDataManager` gives
        # milliseconds — including the START OF THE NEXT SEASON, which the table does not
        # carry at all (a warzone between seasons has no row for the one coming).
        "local own = tonumber(LuaEntry.Player.serverId) or 0 "
        "local D = DataCenter.SeasonDataManager "
        "local function num(f) local ok, v = pcall(f) if not ok or tonumber(v) == nil then return 0 end return math.floor(tonumber(v)) end "
        "if own > 0 then "
        "  CS.UnityEngine.Debug.LogError('%(m)s sown ' .. own .. '%(fs)s' .. num(function() return D:GetSeasonStartTime() end) "
        "    .. '%(fs)s' .. num(function() return D:GetSeasonEndTime() end) "
        "    .. '%(fs)s' .. num(function() return D.nextSeasonStartTime end) "
        "    .. '%(fs)s' .. num(function() return select(1, D:GetNowSeasonAndSeasonDay()) end) "
        "    .. '%(fs)s' .. num(function() return select(2, D:GetNowSeasonAndSeasonDay()) end)) "
        "end"
        % {"m": MARKER, "ids": wanted, "fs": FIELD, "rs": RECORD}
    )


def parse_own_season(lines) -> dict:
    """`{id: {…}}` for the account's own warzone — the exact numbers, not the calendar.

    Four of them are milliseconds the client holds (`start_ms`, `end_ms`,
    `next_start_ms`) and two are what the game itself prints on its season screen (which
    season, and which day of it). They overwrite the config's calendar dates for that one
    warzone because they are the same moments measured better.
    """
    out = {}
    for payload in _payloads(lines, "sown"):
        parts = payload.split(FIELD)
        if len(parts) < 6:
            continue
        try:
            server = int(parts[0])
            values = [int(float(p)) for p in parts[1:6]]
        except ValueError:
            continue
        start, over, nxt, number, day = values
        row = {}
        if start > 0:
            row["start_ms"] = start
        if over > 0:
            row["end_ms"] = over
        if nxt > 0:
            row["next_start_ms"] = nxt
        if number > 0:
            row["season_no"] = number
        if day > 0:
            row["season_day"] = day
        if row:
            out[server] = row
    return out


def parse_seasons(lines) -> dict:
    """`{id: {season_id, step, pre, start, settle, end}}` out of the season pages.

    The four moments come back as the config's own text and are turned into epoch
    milliseconds here — see :func:`_calendar_ms`, and the note above about precision.
    """
    out = {}
    for payload in _payloads(lines, "spage"):
        for record in payload.split(RECORD):
            parts = record.split(FIELD)
            if len(parts) < 7:
                continue
            try:
                server = int(parts[0])
            except ValueError:
                continue
            out[server] = {
                "season_id": int(parts[1]) if parts[1].strip().isdigit() else None,
                "step": parts[2].strip(),
                "pre_ms": _calendar_ms(parts[3]),
                "start_ms": _calendar_ms(parts[4]),
                "settle_ms": _calendar_ms(parts[5]),
                "end_ms": _calendar_ms(parts[6]),
            }
    return out


def _calendar_ms(text):
    """`2026/04/06 00:10:00` -> epoch milliseconds, or None when it is not a date.

    Read as UTC, deliberately and with its reason written down: the config's own pair of
    a unix `start_time` and a `start_time_str` disagree by a different amount on every
    warzone checked, so there is no offset to apply that would be true for all of them.
    A stage lasts weeks; being out by hours cannot move which one a warzone is in, and
    claiming minutes the table does not have would be a lie that looks precise.
    """
    text = (text or "").strip().replace("-", "/")
    if not text:
        return None
    date, _, clock = text.partition(" ")
    bits = [p for p in date.split("/") if p]
    if len(bits) != 3:
        return None
    try:
        year, month, day = (int(b) for b in bits)
        hour, minute, second = 0, 0, 0
        if clock:
            hms = (clock.split(":") + ["0", "0", "0"])[:3]
            hour, minute, second = (int(float(p)) for p in hms)
        import calendar as _cal
        return int(_cal.timegm((year, month, day, hour, minute, second, 0, 0, 0)) * 1000)
    except (TypeError, ValueError):
        return None


def stage_of(row: dict, now_ms) -> str:
    """Which stage this warzone is standing in at `now_ms` — one of the `STAGE_*` words.

    «Off» is both ends of the same lull: after a season has ended, and before the next
    one's pre-season opens. The table names one season per warzone at a time, so the two
    are the same state as far as anything here can tell, and calling the second one
    «unknown» would paint a warzone red for the fortnight between seasons.
    """
    if not row or now_ms is None:
        return STAGE_UNKNOWN
    pre, start = row.get("pre_ms"), row.get("start_ms")
    settle, over = row.get("settle_ms"), row.get("end_ms")
    if not any((pre, start, settle, over)):
        return STAGE_UNKNOWN
    now = int(now_ms)
    if over and now >= over:
        return STAGE_OFF
    if settle and now >= settle:
        return STAGE_SETTLE
    if start and now >= start:
        return STAGE_SEASON
    if pre and now >= pre:
        return STAGE_PRE
    return STAGE_OFF


def next_change(row: dict, now_ms):
    """When this warzone's stage turns over next — epoch ms, or None if nothing is known.

    `next_start_ms` is in the list because a warzone BETWEEN seasons has no moment left in
    its own row: the config names one season at a time and the next one's row does not
    mention this warzone yet. The client knows that date for the account's own warzone and
    for no other, so «—» in that column is «the game has not said», not «never».
    """
    if not row or now_ms is None:
        return None
    ahead = [row.get(key) for key in
             ("pre_ms", "start_ms", "settle_ms", "end_ms", "next_start_ms")]
    ahead = [ms for ms in ahead if ms and ms > int(now_ms)]
    return min(ahead) if ahead else None
