# Read the state of the 3v3 arena — the window, the attempts and today's wins.
# ru: Прочитать состояние арены 3 на 3 — окно события, попытки и победы за день.
#
# A READ: it presses nothing and spends nothing. It does send two of the game's own
# gets — the arena's info and its battle log — because without them there is nothing
# to read: the client learns both only when a screen asks for them, and a client that
# was never asked answers «no event, no battles» in exactly the words a shut event
# would use.
#
# The whole answer is ONE line in ONE variable, `arena3v3`, as `key=value` pairs:
#
#     open=1 left=29 fights=1 wins=0 score=958 rank=470 until=1046393
#
#   open    1 while the event is running and a challenge could be made right now
#   left    challenges the day still allows — the server's own count, 30 a day
#   fights  battles already fought today, by this panel or by the person
#   wins    …and how many of them were won
#   score   the account's arena score, and `rank` its place
#   until   seconds left of the event
#
# **`-` means the game would not answer** — the manager not loaded, a client still at
# the login screen, an account that has not unlocked the arena. That is not zero.
#
# The wire, the managers and what a battle costs are in docs/research/arena-3v3.md.

# --- an ear on the wire, installed once ------------------------------------------
# The replies are parsed by the SCREENS, not by a manager, so a panel with no window
# open has nowhere to read them from. One guarded hook keeps the last of each; a second
# run reuses it rather than stacking another wrapper on top.
READ_LUA (function() local ok, res = pcall(function() local B = DataCenter.__lw_a3v3 if B ~= nil and B.armed then return 1 end B = {armed = true} DataCenter.__lw_a3v3 = B local hm = SFSNetwork.HandleMessage SFSNetwork.HandleMessage = function(cmd, msg, more) local s = string.lower(tostring(cmd or '')) if s == 'score.challenge.match' then B.match = msg elseif s == 'score.arena.battle' then B.battle = msg elseif s == 'score.arena.log.record' then B.records = msg end return hm(cmd, msg, more) end return 1 end) if not ok then return 0 end return res end)() INTO arena_ear

IF arena_ear != 1
    FAIL "the arena's wire could not be listened to — the client is not answering"

# --- ask, then believe the answer -------------------------------------------------
LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.Get3V3ArenaInfo) end) pcall(function() SFSNetwork.SendMessage(MsgDefines.Get3V3ArenaRecords) end)

WAIT 2

READ_LUA (function() local ok, out = pcall(function() local m = DataCenter.LW3V3ArenaManager if m == nil then return 'open=- left=- fights=- wins=- score=- rank=- until=-' end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local a = math.floor(((m.startTime or 0) + 0) / 1000) local z = math.floor(((m.endTime or 0) + 0) / 1000) local left = -1 pcall(function() local has, n = m:GetChallengeRemainTimes() left = math.floor((n or 0) + 0) end) local can = false pcall(function() can = (m:CanChallange() == true) end) local open = 0 if now > 0 and a > 0 and z > 0 and now >= a and now <= z and can and left > 0 then open = 1 end local zero = 0 pcall(function() zero = math.floor(((UITimeManager:GetInstance():GetTomorrowZero() or 0) + 0) / 1000) end) local dayStart = zero - 86400 local B = DataCenter.__lw_a3v3 local rec = B and B.records local fights, wins, score, rank = -1, -1, -1, -1 if type(rec) == 'table' and type(rec.logs) == 'table' then fights, wins = 0, 0 local newest = 0 for _, r in pairs(rec.logs) do local t = math.floor((r.time or 0) + 0) if zero > 0 and t >= dayStart then fights = fights + 1 if math.floor((r.win or 0) + 0) == 1 then wins = wins + 1 end end if t > newest then newest = t score = math.floor((r.ownerNewScore or 0) + 0) rank = math.floor((r.curRank or 0) + 0) end end end local function num(v) if v == nil or v < 0 then return '-' end return string.format('%d', v) end local rest = -1 if now > 0 and z > now then rest = z - now end return 'open=' .. num(open) .. ' left=' .. num(left) .. ' fights=' .. num(fights) .. ' wins=' .. num(wins) .. ' score=' .. num(score) .. ' rank=' .. num(rank) .. ' until=' .. num(rest) end) if not ok then return 'open=- left=- fights=- wins=- score=- rank=- until=-' end return out end)() INTO arena3v3

LOG "arena 3v3: {arena3v3}"
