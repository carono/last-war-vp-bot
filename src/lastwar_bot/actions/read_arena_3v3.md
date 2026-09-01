# Read the state of the 3v3 arena — the window, the attempts and today's wins.
# ru: Прочитать состояние арены 3 на 3 — окно события, попытки и победы за день.
#
# A READ: it presses nothing and spends nothing. It does send the game's own ask for the
# battle log, because without it there is nothing to read: the client learns the log only
# when a screen asks for it, and a client that was never asked answers «no battles» in
# exactly the words an untouched day would use.
#
# The whole answer is ONE line in ONE variable, `arena3v3`, as `key=value` pairs:
#
#     open=1 left=24 used=6 wins=4 logged=11 score=1005 rank=388 until=470692
#
#   open    1 while the event is running and a challenge could be made right now
#   left    challenges the day still allows — the server's own count, 30 a day
#   used    challenges already spent today, which is `30 - left`
#   wins    **the day's arena wins the SERVER counts** — the five the reward is after
#   logged  rows in today's battle log, which is NOT the same number (below)
#   score   the account's arena score, and `rank` its place
#   until   seconds left of the event
#
# **`logged` counts the battles somebody else started too.** The log holds one row per
# battle the account was IN, and being attacked puts a row there as surely as attacking
# does — a defence costs no challenge and counts towards no reward. Measured on
# 2026-09-01: eleven rows and six wins in the log for a day that had spent six
# challenges and won four of them. So `logged` is what happened, `used` and `wins` are
# what the day's reward is made of, and the two are never assumed to agree.
#
# **`wins` is `-` until a battle answers.** The count rides on the reply to a battle,
# and the arena's own info ask goes unanswered when it is sent bare (measured: the
# manager's fields were untouched by it), so a client that has not fought since it
# started has not been told the number. That is not zero, and the errand knows what to
# do about it — `actions/arena_3v3_battles.md`.
#
# **A dash anywhere else means the game would not answer** — the manager not loaded, a
# client still at the login screen, an account that has not unlocked the arena.
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
LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.Get3V3ArenaRecords) end)

WAIT 2

READ_LUA (function() local ok, out = pcall(function() local m = DataCenter.LW3V3ArenaManager if m == nil then return 'open=- left=- used=- wins=- logged=- score=- rank=- until=-' end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local a = math.floor(((m.startTime or 0) + 0) / 1000) local z = math.floor(((m.endTime or 0) + 0) / 1000) local left = -1 pcall(function() local has, n = m:GetChallengeRemainTimes() left = math.floor((n or 0) + 0) end) local cap = math.floor((m.max_limit or 0) + 0) local used = -1 if left >= 0 and cap > 0 then used = cap - left end local can = false pcall(function() can = (m:CanChallange() == true) end) local open = 0 if now > 0 and a > 0 and z > 0 and now >= a and now <= z and can and left > 0 then open = 1 end local zero = 0 pcall(function() zero = math.floor(((UITimeManager:GetInstance():GetTomorrowZero() or 0) + 0) / 1000) end) local dayStart = zero - 86400 local B = DataCenter.__lw_a3v3 local rec = B and B.records local logged, logWins, score, rank = -1, -1, -1, -1 if type(rec) == 'table' and type(rec.logs) == 'table' then logged, logWins = 0, 0 local newest = 0 for _, r in pairs(rec.logs) do local t = math.floor((r.time or 0) + 0) if zero > 0 and t >= dayStart then logged = logged + 1 if math.floor((r.win or 0) + 0) == 1 then logWins = logWins + 1 end end if t > newest then newest = t score = math.floor((r.ownerNewScore or 0) + 0) rank = math.floor((r.curRank or 0) + 0) end end end local wins = -1 if type(m.winTimes) == 'number' then wins = math.floor(m.winTimes + 0) end if wins < 0 and B ~= nil and math.floor((B.dayZero or 0) + 0) == zero and type(B.dayWon) == 'number' then wins = math.floor(B.dayWon + 0) end if wins >= 0 and logWins >= 0 and wins > logWins then wins = -1 end local function num(v) if v == nil or v < 0 then return '-' end return string.format('%d', v) end local rest = -1 if now > 0 and z > now then rest = z - now end return 'open=' .. num(open) .. ' left=' .. num(left) .. ' used=' .. num(used) .. ' wins=' .. num(wins) .. ' logged=' .. num(logged) .. ' score=' .. num(score) .. ' rank=' .. num(rank) .. ' until=' .. num(rest) end) if not ok then return 'open=- left=- used=- wins=- logged=- score=- rank=- until=-' end return out end)() INTO arena3v3

LOG "arena 3v3: {arena3v3}"
