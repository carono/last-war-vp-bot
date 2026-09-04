# Fight the 3v3 arena until the day's wins are in — the game says how many are left.
# ru: Бои на арене 3 на 3, пока не набраны победы за день — сколько осталось, говорит игра.
#
# «Испытание» in the arena building: the server matches an opponent, the three squads
# already standing in the arena line-up go against theirs, and one press decides the
# battle. The day allows 30 challenges and the reward the person is after is FIVE WINS,
# so this errand fights until the wins are in, until the day's challenges run out, or
# until the event's window closes — whichever comes first. **A lost battle is a spent
# challenge and NOT a win, so the loop goes round again.**
#
# **HOW MANY WINS IS THE SERVER'S OWN COUNT, `winTimes`**, and it rides on the reply to a
# battle beside `battleTimes`, the challenges left. That is the number the reward is paid
# on, and it is the only one this errand believes.
#
# **The battle LOG is not that number, and mistaking one for the other is what #2081
# fixed.** The log holds a row for every battle the account was IN, and being attacked
# puts a row there as surely as attacking does — a defence costs no challenge and counts
# towards no reward. Measured on 2026-09-01: eleven rows and six wins in the log for a
# day that had spent six challenges and won four of them, so the errand read «five wins,
# nothing owed» over a day that was three wins in and stopped two short. The log is
# therefore used for one thing only — as a CEILING, since a real win always leaves a row
# in it, so «fewer than five rows won today» proves fewer than five wins.
#
# What that leaves, when the client has not been told `winTimes` yet (it is not sent
# unasked, and the arena's info ask goes unanswered when it is sent bare):
#
#   * the log's win count is under the target → wins are owed for certain, fight;
#   * the log's win count is at or over it → unknowable without asking the server, so
#     ONE battle is fought and its reply says how the day really stands. One challenge
#     out of thirty is the price of not leaving the day two wins short.
#
# A `winTimes` bigger than the log's ceiling is a leftover from yesterday in a client
# that has been up all night; it is thrown away and the day is treated as unknown.
#
# **What the server said is remembered in the CLIENT, beside the ear, under the day it
# belongs to.** The manager's own `winTimes` comes and goes — it was there one minute and
# gone the next on 2026-09-01, and a count that keeps vanishing would buy the same probing
# battle back every hour of the day. So the reply's number is parked in the game's own VM
# with the day's zero stamped on it, which is the same memory the ear lives in: it lasts
# as long as the client does, it dies with the client that would have to be asked again
# anyway, and a stamp from yesterday is ignored rather than believed.
#
# It ends as a SUCCESS and fights nothing when there is nothing to do: the event is not
# running, the day's challenges are spent, or the wins are already made. A failure there
# would sit out the retry hold and try again all day for a state that will not change.
#
# It ends as a FAILURE when a battle could not be made at all — no opponent came back,
# the send was refused, the client stopped answering. Every one of those mends itself in
# minutes, so the clock keeps its place and the next run re-asks both counts and does
# only what is STILL owed.
#
# **The squads are the person's own.** The arena keeps its own three-team line-up, the
# one edited on the arena screen, and this errand fights with whatever stands there —
# it never re-orders it and never touches the base's formations. The battle is started
# by the client's own 3v3 manager, which is what packs those three teams onto the wire.
#
# «Арена шторма» is a DIFFERENT event with different rules and is not this scenario.
#
# The wire, the managers and the measurements are docs/research/arena-3v3.md; the
# reading behind the counts is actions/read_arena_3v3.md.

ARGS wins = 5
ARGS cap = 30

# --- what the day has already had ---------------------------------------------
# The reading is its own recipe and this plays it: it installs the one guarded ear on
# the wire, asks the server for today's battle log, and says the line a person reads.
# Everything below is read out of what that ask brought back, so the server is asked
# once and not twice.
CALL read_arena_3v3

# `-1` is «the counts could not be read», which is not «nothing to do»: a client that
# has stopped answering would otherwise look exactly like a finished day.
READ_LUA (function() local ok, out = pcall(function() local m = DataCenter.LW3V3ArenaManager if m == nil then return -1 end local B = DataCenter.__lw_a3v3 local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local a = math.floor(((m.startTime or 0) + 0) / 1000) local z = math.floor(((m.endTime or 0) + 0) / 1000) if now <= 0 or a <= 0 or z <= 0 then return -1 end B.open = 0 if now >= a and now <= z then B.open = 1 end local left = -1 pcall(function() local has, n = m:GetChallengeRemainTimes() left = math.floor((n or 0) + 0) end) if left < 0 then return -1 end B.left = left local zero = 0 pcall(function() zero = math.floor(((UITimeManager:GetInstance():GetTomorrowZero() or 0) + 0) / 1000) end) if zero <= 0 then return -1 end local rec = B.records if type(rec) ~= 'table' or type(rec.logs) ~= 'table' then return -1 end local logged, ceiling = 0, 0 for _, r in pairs(rec.logs) do local t = math.floor((r.time or 0) + 0) if t >= zero - 86400 then logged = logged + 1 if math.floor((r.win or 0) + 0) == 1 then ceiling = ceiling + 1 end end end B.logged = logged B.ceiling = ceiling local won = -1 if type(m.winTimes) == 'number' then won = math.floor(m.winTimes + 0) end if won < 0 and math.floor((B.dayZero or 0) + 0) == zero and type(B.dayWon) == 'number' then won = math.floor(B.dayWon + 0) end if won > ceiling then won = -1 end B.won = won B.made = 0 B.mywins = 0 B.mylosses = 0 B.strikes = 0 return 1 end) if not ok then return -1 end return out end)() INTO arena_read

IF arena_read < 0
    FAIL "the arena's counters could not be read — check the client is still talking to the server"

READ_LUA (function() local B = DataCenter.__lw_a3v3 return math.floor((B.open or 0) + 0) end)() INTO arena_open

IF arena_open != 1
    LOG "the 3v3 arena is not running right now"
    STOP "the event is shut"

# --- how many battles are owed -------------------------------------------------
# The server's own `winTimes` when the client has been told it; otherwise the log's
# ceiling decides between «owed for certain» and «one battle to find out».
# ONE CALL, NOT ONE PER QUESTION (#2404). A read is a thread hijack into the
# client at half a second a time whatever it asks, and the machine can make about
# 1.4 of them a second in total (`docs/research/link-contention.md`), so a run of
# readings one statement at a time is that many seconds of everybody's budget for
# answers the game could hand over together. What each one is, and why it is asked,
# is on the comments and LOG lines that follow.
READ_LUA (function() local __v0 = (function() local B = DataCenter.__lw_a3v3 local target = {wins} local left = math.floor((B.left or 0) + 0) local want = 0 if left > 0 then local won = math.floor((B.won or -1) + 0) if won >= 0 then want = target - won if want < 0 then want = 0 end elseif math.floor((B.ceiling or 0) + 0) < target then want = target - math.floor((B.ceiling or 0) + 0) else want = 1 end if want > left then want = left end local cap = {cap} if want > cap then want = cap end end B.todo = want return want end)() local __v1 = (function() local B = DataCenter.__lw_a3v3 local won = math.floor((B.won or -1) + 0) local w = 'not said yet' if won >= 0 then w = tostring(won) end return 'wins today ' .. w .. ' of {wins}, challenges left ' .. math.floor((B.left or 0) + 0) .. ', battle log today ' .. math.floor((B.logged or 0) + 0) .. ' row(s) with ' .. math.floor((B.ceiling or 0) + 0) .. ' won' end)() return __v0, __v1 end)() INTO arena_todo, arena_state

LOG "3v3 arena: {arena_state} — {arena_todo} battle(s) to fight"

IF arena_todo < 1
    LOG "the day's 3v3 arena wins are already in, or the day's challenges are spent"
    STOP "nothing left to fight today"

# --- fight, re-asking the counts after every battle -------------------------------
# The LIMIT is a safety rail rather than the rule: the loop leaves when the SERVER says
# the wins are in or the challenges are gone.
WHILE arena_todo > 0 LIMIT 30
    LUA pcall(function() local B = DataCenter.__lw_a3v3 B.match = nil B.battle = nil SFSNetwork.SendMessage(MsgDefines.Get3V3ArenaMatchInfo) end)
    WAIT 2
    READ_LUA (function() local ok, out = pcall(function() local B = DataCenter.__lw_a3v3 local m = DataCenter.LW3V3Manager local msg = B.match if type(msg) ~= 'table' or type(msg.otherInfo) ~= 'table' then return 'no opponent came back' end m:SetType(1) m:SetOpponentData(msg.otherInfo) m:StartBattle() return 'sent' end) if not ok then return 'the battle was refused by the client: ' .. tostring(out) end return out end)() INTO arena_sent
    WAIT 4
    READ_LUA (function() local ok, out = pcall(function() local B = DataCenter.__lw_a3v3 local r = B.battle if type(r) ~= 'table' then B.strikes = math.floor((B.strikes or 0) + 0) + 1 return 'the server said nothing about the battle' end if r.errorCode ~= nil then B.strikes = math.floor((B.strikes or 0) + 0) + 1 return 'the server refused the battle (' .. tostring(r.errorCode) .. ')' end B.strikes = 0 B.made = math.floor((B.made or 0) + 0) + 1 local win = (r.win == true) or (math.floor((r.win or 0) + 0) == 1) if win then B.mywins = math.floor((B.mywins or 0) + 0) + 1 else B.mylosses = math.floor((B.mylosses or 0) + 0) + 1 end if type(r.winTimes) == 'number' then B.won = math.floor(r.winTimes + 0) elseif math.floor((B.won or -1) + 0) >= 0 then if win then B.won = math.floor(B.won + 0) + 1 end else B.won = math.floor((B.mywins or 0) + 0) end local zero = 0 pcall(function() zero = math.floor(((UITimeManager:GetInstance():GetTomorrowZero() or 0) + 0) / 1000) end) if zero > 0 then B.dayZero = zero B.dayWon = math.floor((B.won or 0) + 0) end local left = -1 if type(r.battleTimes) == 'number' then left = math.floor(r.battleTimes + 0) end if left >= 0 then B.left = left end local score = math.floor((r.ownerNewScore or 0) + 0) local rank = math.floor((r.curRank or 0) + 0) return 'battle ' .. math.floor(B.made) .. ': ' .. (win and 'WON' or 'lost') .. ', wins today ' .. math.floor(B.won) .. ' of {wins}, challenges left ' .. math.floor(B.left) .. ', score ' .. score .. ' (rank ' .. rank .. ')' end) if not ok then return 'the battle result could not be read: ' .. tostring(out) end return out end)() INTO arena_round
    LOG "{arena_round}"
    READ_LUA (function() local B = DataCenter.__lw_a3v3 if math.floor((B.strikes or 0) + 0) >= 2 then B.todo = 0 return 0 end local target = {wins} local left = math.floor((B.left or 0) + 0) local want = 0 if left > 0 then local won = math.floor((B.won or -1) + 0) if won >= 0 then want = target - won if want < 0 then want = 0 end else want = 1 end if want > left then want = left end end B.todo = want return want end)() INTO arena_todo

READ_LUA (function() local B = DataCenter.__lw_a3v3 return 'fought ' .. math.floor((B.made or 0) + 0) .. ', won ' .. math.floor((B.mywins or 0) + 0) .. ', lost ' .. math.floor((B.mylosses or 0) + 0) .. ', wins today ' .. math.floor((B.won or 0) + 0) .. ' of {wins}, challenges left ' .. math.floor((B.left or 0) + 0) .. ', strikes ' .. math.floor((B.strikes or 0) + 0) end)() INTO arena_report

LOG "3v3 arena: {arena_report}"

READ_LUA (function() local B = DataCenter.__lw_a3v3 return math.floor((B.strikes or 0) + 0) end)() INTO arena_strikes

IF arena_strikes > 1
    FAIL "the 3v3 arena refused two battles in a row — the clock will try again"
