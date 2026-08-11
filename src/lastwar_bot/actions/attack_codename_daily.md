# Make the day's «Кодовое имя» attacks — as many as the day still owes, and no more.
# ru: Дневная норма атак по боссу «Кодовое имя» — сколько день ещё должен, и не больше.
#
# The errand a clock plays once a day. `attack_codename_boss.md` is ONE attack and is
# what a person presses; this is the whole day's credit in one run, and the difference
# between them is the only reason this file exists — a timer set to the single attack
# would send one march a day and earn a third of the reward for ever.
#
# **HOW MANY IS THE GAME'S ANSWER, NEVER A NUMBER WRITTEN HERE.** The day owes
# `rewardMaxTimes` attacks, three at the time of writing, and the server counts what has
# ALREADY been made — from this panel, from the phone, or by the person playing on the
# screen in front of them. So the run asks first and sends the difference: a day the
# person has already played by hand costs nothing, and a day nobody touched costs three
# marches. Attempts themselves are not rationed («кол-во попыток в день не ограничено» —
# the game's own rules), so the count is attacks MADE rather than an allowance spent, and
# stopping at the day's number is a decision about squads rather than about a quota.
#
# It ends as a SUCCESS and sends nothing on the two days there is nothing to do:
#
#   * Sunday, the one day the event does not run at all. A failure here would sit out
#     the retry hold and try again, all day, every retry period — ninety-odd logged
#     failures for a state that will not change until Monday;
#   * a day whose attacks are already made, by whatever hand made them.
#
# It ends as a FAILURE, and the clock therefore keeps its place and tries again after the
# errand's `retry_sec`, when the day still owes attacks and one could not be made: no
# squad standing in the base, the boss not in the list yet, the client no longer talking
# to the server. Every one of those is a state that mends itself within minutes — a squad
# comes home from the boss it was just sent to — so the retry is the whole design and not
# an afterthought. The next attempt re-asks the count and does only what is STILL owed,
# never the three again.
#
# Nothing here presses anything itself: each attack is `CALL attack_codename_boss`, which
# owns the whole of what an attack is — the ask, the boss out of the event's own list, the
# first squad standing in the base, the send, and the proof that the server's count moved.
# A failing call unwinds this run with it, which is exactly the wanted behaviour.
#
# The panel plays this from the Timers tab as the errand `attack_codename_daily`, switched
# off until the operator turns it on, at a period of a day. The reading behind the counts
# is actions/read_codename_event.md; the reverse-engineering is
# docs/research/codename-event.md.

# --- ask, then believe the answer -------------------------------------------------
# The manager is EMPTY until something asks the server, and it answers «no boss, event
# shut» until then — the trap that greyed the whole feature out for a day (#1259). Every
# gate below reads what this brings back.
TAP codename_fetch

READ_LUA ((type(DataCenter.ActBossDataManager.stageTimeList) == 'table') and 1 or 0) INTO cn_loaded

WHILE cn_loaded == 0 LIMIT 4
    WAIT 0.6
    READ_LUA ((type(DataCenter.ActBossDataManager.stageTimeList) == 'table') and 1 or 0) INTO cn_loaded

READ_LUA (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager:IsBossAvailable() end) if not ok then return nil end return (v and 1 or 0) end)() INTO cn_open

IF cn_open != 1
    LOG "«Кодовое имя» is not running today — nothing is owed"
    STOP "the event takes Sunday off"

# --- what the day still owes ------------------------------------------------------
# `-1` is «the counters could not be read», which is not «none left»: a client that has
# stopped answering would otherwise look exactly like a day already played, and the
# errand would write itself off as done until tomorrow.
READ_LUA ((function() local a = (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() local n = (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.rewardMaxTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() if a == nil or n == nil then return nil end local l = n - a if l < 0 then l = 0 end return l end)() or -1) INTO cn_left

IF cn_left < 0
    FAIL "the event's attack counters could not be read — check the client is still talking to the server"

IF cn_left < 1
    LOG "the day's «Кодовое имя» attacks are already made"
    STOP "nothing left to send today"

# --- send what is owed, re-asking the count after each ----------------------------
# The LIMIT is a safety rail rather than the rule: the loop leaves when the SERVER says
# nothing is owed, and the rail only matters if a future event ever asked for more
# attacks than a day's worth of squads could make.
WHILE cn_left > 0 LIMIT 6
    CALL attack_codename_boss
    READ_LUA ((function() local a = (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() local n = (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.rewardMaxTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() if a == nil or n == nil then return nil end local l = n - a if l < 0 then l = 0 end return l end)() or -1) INTO cn_left

IF cn_left != 0
    FAIL "the day's «Кодовое имя» attacks are not all made — the clock will try again"

LOG "The day's «Кодовое имя» attacks are made"
