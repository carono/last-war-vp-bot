# Read the arena building: which event is running in it, and how the account stands.
# ru: Прочитать арену: какое событие в ней идёт и как в нём стоят дела.
#
# A READ: it presses nothing and spends nothing. It does send the game's own ask for the
# running event's list — the battle log for the 3v3 challenge, the rank list for «Арена
# Шторма» — because the client is not told either until a screen asks, and one that was
# never asked answers exactly like an empty day.
#
# **The building runs ONE event at a time and swaps it when the old one ends.** Which is
# running is asked of the two managers' own windows and never of a date written down
# here, which is the same question `actions/arena_battles.md` asks before it plays one.
#
# The whole answer is ONE line in ONE variable, `arena`, as `key=value` pairs:
#
#     which=storm open=1 score=1039 rank=358 done=5 need=5 left=5 chest=1 until=379000
#     which=3v3 open=1 score=967 rank=430 done=- need=- left=24 chest=- until=470692
#     which=none open=0 score=- rank=- done=- need=- left=- chest=- until=-
#
#   which   `3v3`, `storm`, `none` — the event the building is running right now
#   open    1 while a battle could be made in it this second
#   score   the arena score, and `rank` the place it buys
#   done    what the day's reward is counted in: WINS for the 3v3 challenge, BATTLES
#           for the storm arena — the two are not the same thing and are not mixed
#   need    how many of those the biggest daily reward asks for. The storm arena's own
#           number, read off its ladder; a dash for the 3v3, whose target the server
#           does not carry — the errand's `wins` argument is what says it there
#   left    attempts the day still allows
#   chest   the storm arena's biggest daily box: 1 taken, 0 not; a dash for the 3v3
#   until   seconds left of the event — the moment the building swaps it
#
# **`done` is a dash on the 3v3 until a battle answers.** The count rides on the reply
# to a battle and the arena's info ask goes unanswered when it is sent bare, so a client
# that has not fought since it started has not been told the number. That is not zero
# (docs/research/arena-3v3.md §4).
#
# **A dash anywhere else means the game would not answer** — the manager not loaded, a
# client still at the login screen, an account that has not unlocked the arena.
#
# The wire and the managers are docs/research/arena-3v3.md and docs/research/storm-arena.md.

SHARE

# --- the ears, and the ask for whichever event is running -------------------------
# Both replies are parsed by the SCREENS rather than by a manager, so a panel with no
# window open has nowhere to read them from. The two hooks are the same guarded ones
# `read_arena_3v3.md` and `read_storm_arena.md` install, and a second run reuses them
# instead of stacking another wrapper on top.
READ_LUA (function() local ok, out = pcall(function() pcall(function() local B = DataCenter.__lw_a3v3 if B == nil or not B.armed then B = {armed = true} DataCenter.__lw_a3v3 = B local hm = SFSNetwork.HandleMessage SFSNetwork.HandleMessage = function(cmd, msg, more) local s = string.lower(tostring(cmd or '')) if s == 'score.challenge.match' then B.match = msg elseif s == 'score.arena.battle' then B.battle = msg elseif s == 'score.arena.log.record' then B.records = msg end return hm(cmd, msg, more) end end end) pcall(function() local B = DataCenter.__lw_storm if B == nil or not B.armed then B = {armed = true} DataCenter.__lw_storm = B local hm = SFSNetwork.HandleMessage SFSNetwork.HandleMessage = function(cmd, msg, more) local s = string.lower(tostring(cmd or '')) if string.find(s, 'new.arena', 1, true) then B[s] = msg end return hm(cmd, msg, more) end end end) local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return 0 end local function inside(a, z) a = math.floor((a or 0) / 1000) z = math.floor((z or 0) / 1000) if a <= 0 or z <= 0 then return false end return now >= a and now <= z end local three = false pcall(function() local m = DataCenter.LW3V3ArenaManager three = inside(m.startTime, m.endTime) end) if three then pcall(function() SFSNetwork.SendMessage(MsgDefines.Get3V3ArenaRecords) end) return 1 end local storm = false pcall(function() local m = DataCenter.NewPeakArenaManager storm = inside(m.info.startTime, m.info.endTime) end) if storm then pcall(function() SFSNetwork.SendMessage(MsgDefines.NewArenaRankList) end) return 2 end return 3 end) if not ok then return 0 end return out end)() INTO arena_asked

WAIT 2

# --- one line, whichever event answered -------------------------------------------
# Which one is running is decided again here rather than carried over: the ask above may
# have been the last second of an event's window, and a line naming an event that has
# just closed is worse than one saying so.
READ_LUA (function() local ok, out = pcall(function() local function num(v) if v == nil or v < 0 then return '-' end return string.format('%d', math.floor(v + 0)) end local function line(w, open, score, rank, done, need, left, chest, rest) return 'which=' .. w .. ' open=' .. num(open) .. ' score=' .. num(score) .. ' rank=' .. num(rank) .. ' done=' .. num(done) .. ' need=' .. num(need) .. ' left=' .. num(left) .. ' chest=' .. num(chest) .. ' until=' .. num(rest) end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return line('unknown', -1, -1, -1, -1, -1, -1, -1, -1) end local function window(a, z) a = math.floor((a or 0) / 1000) z = math.floor((z or 0) / 1000) if a <= 0 or z <= 0 then return false, -1 end if now < a or now > z then return false, -1 end return true, z - now end local three, threeRest = false, -1 pcall(function() local m = DataCenter.LW3V3ArenaManager three, threeRest = window(m.startTime, m.endTime) end) if three then local m = DataCenter.LW3V3ArenaManager local left = -1 pcall(function() local has, n = m:GetChallengeRemainTimes() left = math.floor((n or 0) + 0) end) local can = false pcall(function() can = (m:CanChallange() == true) end) local open = 0 if can and left > 0 then open = 1 end local zero = 0 pcall(function() zero = math.floor(((UITimeManager:GetInstance():GetTomorrowZero() or 0) + 0) / 1000) end) local B = DataCenter.__lw_a3v3 local rec = B and B.records local score, rank, logWins = -1, -1, -1 if type(rec) == 'table' and type(rec.logs) == 'table' then logWins = 0 local newest = 0 for _, r in pairs(rec.logs) do local t = math.floor((r.time or 0) + 0) if zero > 0 and t >= zero - 86400 and math.floor((r.win or 0) + 0) == 1 then logWins = logWins + 1 end if t > newest then newest = t score = math.floor((r.ownerNewScore or 0) + 0) rank = math.floor((r.curRank or 0) + 0) end end end local won = -1 if type(m.winTimes) == 'number' then won = math.floor(m.winTimes + 0) end if won < 0 and B ~= nil and math.floor((B.dayZero or 0) + 0) == zero and type(B.dayWon) == 'number' then won = math.floor(B.dayWon + 0) end if won >= 0 and logWins >= 0 and won > logWins then won = -1 end return line('3v3', open, score, rank, won, -1, left, -1, threeRest) end local storm, stormRest = false, -1 local sm = DataCenter.NewPeakArenaManager pcall(function() storm, stormRest = window(sm.info.startTime, sm.info.endTime) end) if storm then local r = nil pcall(function() r = sm.rankData end) if type(r) ~= 'table' then return line('storm', -1, -1, -1, -1, -1, -1, -1, stormRest) end local left = math.floor((r.battleTimes or -1) + 0) local fought = math.floor((r.battleCount or -1) + 0) local need, chest = -1, -1 pcall(function() for _, row in pairs(r.dailyReward) do local n = math.floor((row.needCount or 0) + 0) if n > need then need = n chest = math.floor((row.rewarded or 0) + 0) end end end) local can = false pcall(function() can = (sm:CanChallenge() == true) end) local open = 0 if can and left > 0 then open = 1 end local score = math.floor((r.curScore or -1) + 0) local rank = math.floor((r.curRank or -1) + 0) return line('storm', open, score, rank, fought, need, left, chest, stormRest) end return line('none', 0, -1, -1, -1, -1, -1, -1, -1) end) if not ok then return 'which=unknown open=- score=- rank=- done=- need=- left=- chest=- until=-' end return out end)() INTO arena

LOG "arena: {arena}"
