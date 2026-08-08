#!/usr/bin/env python3
r"""The alliance duel («VS») read out of the running client — both sides, every day.

The duel is a week-long contest between two alliances on two servers. What people ask
of it is always the same three things: how the two sides stand, who scored what, and on
WHICH DAY — the week's total answers none of them on its own, because a day the alliance
lost by a hair and a day it was not playing look identical in a weekly sum.

All three are in the client, and none of them needed a new protocol:

* :data:`~DataCenter.AllianceCompeteDataManager` holds the ranking the duel screen draws.
  `dailyRank[day]` is one list per day of the week and `rankInfoDic[rankType]` the
  standing ones, and every list carries the players of **both** alliances — the row says
  which side it is on with `aid` (the alliance's id), `abbr` (its tag) and `serverId`.
  Asking for it is one message: `FetchRankList(type)` sends
  `MsgDefines.AllianceCompeteRankList` (`al.battle.rank.info`) with
  `AllyDuelRankType` — `Day` 0, `Week` 1, `Month` 2 — and a `Day` reply comes back with
  every day at once, each row stamped with its own `day`.
* :data:`~DataCenter.GetDuelScoreManager` holds the two alliances themselves:
  `duelInfos[2].scoreData.vsAllianceInfo` is one entry per side with its week score, its
  power, how many days it has won, its MVP — and `scoreHistory`, which is that side's
  score for each day so far. The enemy's daily numbers arrive with the friendly ones, in
  the same read.

Which side is «ours» is not a field. `scoreData.targetAllianceId` names the OPPONENT, so
the other entry is the player's own alliance — that is the whole derivation, and it is
made here once rather than left to whoever reads the table.

Nothing here presses anything or changes anything in the game: one request for a list
the duel screen requests anyway, and reads of memory the client has already filled.

This module is the reading. Writing it down is `tools/vs_rankings.py`, which puts it in
the profile's `leaderboard_history.db` beside the boards the passive collector catches.
"""
from __future__ import annotations

import json

#: The marker the Lua chunks tag their output with.
MARKER = "VSDUEL"

#: How many rows go on one line of output. The evaluator reads the client's log line by
#: line, and a whole day of a big duel is tens of kilobytes; small batches keep every
#: line comfortably short without making the read chatty (six days come back in about
#: thirty lines).
BATCH = 40

#: `AllyDuelRankType` in the client — the argument `FetchRankList` sends and the `type`
#: the reply carries back.
RANK_DAY = 0
RANK_WEEK = 1
RANK_MONTH = 2

#: What a board of each kind is filed under in the history. The player boards keep the
#: game's own command with its variant, exactly as the passive collector files the same
#: reply when it catches it on the wire, so a row read from memory and a row read off
#: the socket land in the same board and differ only in `source`.
BOARD_DAY = "al.battle.rank.info/type=0"
BOARD_WEEK = "al.battle.rank.info/type=1"
BOARD_MONTH = "al.battle.rank.info/type=2"
#: The two alliances themselves, with a row per side per day. Not a command: the client
#: assembles it out of the duel's score info, and no single reply carries it.
BOARD_SIDES = "al.battle.vs.alliances"

#: Send the ranking request the duel screen sends. One message, no window opened.
FETCH_LUA = """
local ok, err = pcall(function()
  DataCenter.AllianceCompeteDataManager:FetchRankList(%d)
end)
CS.UnityEngine.Debug.LogError('%s fetch=' .. tostring(ok) .. ' ' .. tostring(err))
"""

#: The reading. Emits one `%s ...` line per batch of rows and one per side, as JSON.
READ_LUA = r"""
local MARK = '%s'
local BATCH = %d

local function esc(s)
  s = tostring(s)
  s = s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', ' '):gsub('\r', ' ')
  s = s:gsub('%%c', ' ')
  return s
end

local function val(v)
  local t = type(v)
  if v == nil then return 'null' end
  if t == 'number' then
    if v ~= v or v == math.huge or v == -math.huge then return 'null' end
    if v == math.floor(v) then return string.format('%%d', v) end
    return tostring(v)
  end
  if t == 'boolean' then return tostring(v) end
  return '"' .. esc(v) .. '"'
end

--- One row as a flat JSON object: every scalar field it has, whatever it is called.
--- Deliberately not a chosen list of names — the point of this read is that the fields
--- nobody has a column for yet are the ones worth keeping.
local function obj(t, extra)
  local parts = {}
  for k, v in pairs(t or {}) do
    if type(k) == 'string' and k ~= '_class_type' and k ~= 'getters' then
      local vt = type(v)
      if vt ~= 'table' and vt ~= 'function' and vt ~= 'userdata' then
        parts[#parts + 1] = '"' .. esc(k) .. '":' .. val(v)
      end
    end
  end
  for k, v in pairs(extra or {}) do
    parts[#parts + 1] = '"' .. esc(k) .. '":' .. val(v)
  end
  return '{' .. table.concat(parts, ',') .. '}'
end

local function emit(kind, key, rows)
  local buf, n = {}, 0
  for i = 1, #rows do
    buf[#buf + 1] = rows[i]
    n = n + 1
    if n >= BATCH then
      CS.UnityEngine.Debug.LogError(MARK .. ' rows ' .. kind .. ' ' .. tostring(key)
        .. ' [' .. table.concat(buf, ',') .. ']')
      buf, n = {}, 0
    end
  end
  if n > 0 then
    CS.UnityEngine.Debug.LogError(MARK .. ' rows ' .. kind .. ' ' .. tostring(key)
      .. ' [' .. table.concat(buf, ',') .. ']')
  end
end

local M = DataCenter.AllianceCompeteDataManager
local info = DataCenter.GetDuelScoreManager and DataCenter.GetDuelScoreManager.duelInfos
local ally = info and info[2]
local sd = ally and ally.scoreData

-- The head: what the duel itself is. `targetAllianceId` is the OPPONENT, which is the
-- only thing that says which of the two sides below is the player's own.
local head = {}
if sd then
  head = {
    target_alliance_id = sd.targetAllianceId, target_server_id = sd.targetServerId,
    cross_fight = sd.crossFight, is_bye = sd.isBye,
    fight_start_time = sd.fightStartTime, fight_end_time = sd.fightEndTime,
    week_end_time = sd.weekEndTime, start_time = sd.startTime, end_time = sd.endTime,
    min_day_score = sd.minDayScore, min_week_score = sd.minWeekScore,
    my_alliance_score = ally.curMyAlScore, enemy_alliance_score = ally.curEnemyAlScore,
    my_score = ally.curScore,
  }
end
local weekday = 0
pcall(function() weekday = UITimeManager:GetInstance():GetNowWeekdayIndex() end)
head.weekday_index = weekday
CS.UnityEngine.Debug.LogError(MARK .. ' head ' .. obj(nil, head))

-- The two sides, and each side's score on each day it has played.
if sd and sd.vsAllianceInfo then
  for _, side in pairs(sd.vsAllianceInfo) do
    local mvp = side.mvpPlayer or {}
    local key = tostring(side.allianceId or side.id or '?')
    emit('side', key, { obj(side, { mvp_uid = mvp.uid, mvp_name = mvp.name }) })
    local hist = {}
    for _, entry in pairs(side.scoreHistory or {}) do
      hist[#hist + 1] = obj(entry, {})
    end
    emit('sideday', key, hist)
  end
end

-- The rankings: one list per day, plus the standing ones.
for day, list in pairs(M.dailyRank or {}) do
  local rows = {}
  for index, row in ipairs(list) do
    rows[#rows + 1] = obj(row, { position = index, day = day })
  end
  emit('day', day, rows)
end
for rankType, list in pairs(M.rankInfoDic or {}) do
  local rows = {}
  for index, row in ipairs(list) do
    rows[#rows + 1] = obj(row, { position = index })
  end
  emit('rank', rankType, rows)
end

CS.UnityEngine.Debug.LogError(MARK .. ' done')
"""


def fetch_chunk(rank_type: int = RANK_DAY) -> str:
    """The Lua that asks the server for one ranking — the duel screen's own request."""
    return FETCH_LUA % (int(rank_type), MARKER)


def read_chunk() -> str:
    """The Lua that reads the whole duel out of the client."""
    return READ_LUA % (MARKER, BATCH)


def parse(lines) -> dict:
    """Turn the emitted lines into ``{"head": {...}, "sides": [...], "players": [...]}``.

    Unknown line kinds are kept rather than dropped — a client that starts emitting
    something new should show up as an unread line, not as silence.
    """
    head: dict = {}
    sides: list = []
    side_days: list = []
    players: list = []
    unread: list = []
    for line in lines:
        body = line.split(MARKER, 1)[-1].strip() if MARKER in line else line.strip()
        if body.startswith("head "):
            head.update(_json(body[5:]) or {})
            continue
        if not body.startswith("rows "):
            if body and body != "done" and not body.startswith("fetch="):
                unread.append(body[:200])
            continue
        parts = body.split(" ", 3)
        if len(parts) < 4:
            unread.append(body[:200])
            continue
        _, kind, key, blob = parts
        rows = _json(blob)
        if not isinstance(rows, list):
            unread.append(body[:200])
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if kind == "side":
                sides.append(row)
            elif kind == "sideday":
                side_days.append(dict(row, alliance_id=key))
            elif kind == "day":
                players.append(dict(row, day=_int(key)))
            elif kind == "rank":
                players.append(dict(row, rank_type=_int(key)))
            else:
                unread.append(kind)
    return {"head": head, "sides": sides, "side_days": side_days,
            "players": players, "unread": unread}


def own_alliance_id(state: dict):
    """The player's own alliance id — the side that is not the named opponent.

    ``None`` when the duel has no opponent yet (a bye week) or when the read came back
    without the head, and then no row is marked with a side at all: a guess about which
    hundred players are «ours» is worse than the empty column, because it looks answered.
    """
    target = str(state.get("head", {}).get("target_alliance_id") or "")
    ids = [str(s.get("allianceId") or s.get("id") or "") for s in state.get("sides", [])]
    ids = [i for i in ids if i]
    if not target or len(ids) != 2 or target not in ids:
        return None
    return ids[0] if ids[1] == target else ids[1]


def side_of(state: dict, alliance_id) -> str | None:
    """``"own"`` / ``"enemy"`` for one alliance id, or None when it cannot be told."""
    own = own_alliance_id(state)
    if own is None or not alliance_id:
        return None
    return "own" if str(alliance_id) == own else "enemy"


def store_records(state: dict, seen_at: int) -> list:
    """The read, as rows `leaderboard_store.save_records` can write.

    Three boards come out of one read: the day ranking, the week ranking (and the month
    one where the client holds it) and the two alliances themselves, a row per side per
    day. Every row keeps the whole original in `raw`, so a field this function has no
    opinion about is still written down.
    """
    out: list = []
    for row in state.get("players", []):
        day = _int(row.get("day"))
        rank_type = _int(row.get("rank_type"))
        # A DAY IS ITS OWN BOARD, and that is what keeps the file from doubling on
        # every run: the store skips a board identical to its last snapshot, and
        # Monday's ranking stops moving on Tuesday. Filed as ONE board, the whole week
        # would be rewritten each time because the running day inside it had changed —
        # a thousand rows of already-recorded history for the sake of the two hundred
        # that actually moved.
        board = (f"{BOARD_DAY}/day={day}" if day is not None else
                 {RANK_WEEK: BOARD_WEEK, RANK_MONTH: BOARD_MONTH}.get(rank_type,
                                                                     BOARD_WEEK))
        alliance_id = row.get("aid") or row.get("allianceId")
        out.append({
            "leaderboard": board,
            "leaderboard_label": "alliance duel ranking",
            "entity": "player", "scope": "player",
            "uid": row.get("uid"), "name": row.get("name"),
            "server_id": row.get("serverId"),
            "position": _int(row.get("position")),
            "position_source": "order",
            "list_index": (_int(row.get("position")) or 1) - 1,
            "score": _int(row.get("score")), "score_field": "score",
            "power": _int(row.get("power")),
            "alliance": row.get("abbr") or row.get("alName"),
            "alliance_id": alliance_id,
            "side": side_of(state, alliance_id),
            "day": day, "source": "game", "seen_at": seen_at,
            "discovered": False, "raw": row,
        })
    # SORTED, because the store compares a board against its last snapshot row by row
    # and these come out of a Lua `pairs` loop, whose order is a property of the hash
    # table rather than of the data. Left unsorted, two identical reads hash differently
    # about as often as not, and every run rewrites six days of finished history.
    for row in sorted(state.get("side_days", []),
                      key=lambda r: (_int(r.get("day")) or 0,
                                     str(r.get("alliance_id") or ""))):
        alliance_id = row.get("alliance_id")
        out.append({
            "leaderboard": f"{BOARD_SIDES}/day={_int(row.get('day'))}",
            "leaderboard_label": "alliance duel — the two sides, day by day",
            "entity": "alliance", "scope": "alliance",
            "uid": alliance_id, "name": _side_name(state, alliance_id),
            "server_id": _side_field(state, alliance_id, "serverId"),
            "position": None, "position_source": None, "list_index": 0,
            "score": _int(row.get("score")), "score_field": "score",
            "power": _int(_side_field(state, alliance_id, "power")),
            "alliance": _side_field(state, alliance_id, "abbr"),
            "alliance_id": alliance_id,
            "side": side_of(state, alliance_id),
            "day": _int(row.get("day")), "source": "game", "seen_at": seen_at,
            "discovered": False, "raw": row,
        })
    today = _int(state.get("head", {}).get("weekday_index"))
    for side in sorted(state.get("sides", []),
                       key=lambda s: str(s.get("allianceId") or s.get("id") or "")):
        alliance_id = side.get("allianceId") or side.get("id")
        out.append({
            "leaderboard": f"{BOARD_SIDES}/day={today}",
            "leaderboard_label": "alliance duel — the two sides, day by day",
            "entity": "alliance", "scope": "alliance",
            "uid": alliance_id, "name": side.get("alName"),
            "server_id": _int(side.get("serverId")),
            "position": None, "position_source": None, "list_index": 0,
            # `alScore` IS TODAY'S, not the week's — measured, not assumed: on the day
            # this was written the six days of player rows summed to `scoreHistory`
            # exactly for days 1..5, and day 6's sum was `alScore` (still climbing
            # between two reads seconds apart). `scoreHistory` holds the days that have
            # FINISHED; the running day is only ever in this number. Filing it under
            # today's index is what makes the two agree instead of leaving a day that
            # is somehow both missing and counted twice.
            "score": _int(side.get("alScore")), "score_field": "alScore",
            "power": _int(side.get("power")), "alliance": side.get("abbr"),
            "alliance_id": alliance_id, "side": side_of(state, alliance_id),
            "day": today, "source": "game", "seen_at": seen_at,
            "discovered": False, "raw": side,
        })
    return out


def _side(state: dict, alliance_id):
    for side in state.get("sides", []):
        if str(side.get("allianceId") or side.get("id") or "") == str(alliance_id):
            return side
    return {}


def _side_name(state: dict, alliance_id):
    return _side(state, alliance_id).get("alName")


def _side_field(state: dict, alliance_id, field):
    return _side(state, alliance_id).get(field)


def _json(blob: str):
    try:
        return json.loads(blob)
    except ValueError:
        return None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
