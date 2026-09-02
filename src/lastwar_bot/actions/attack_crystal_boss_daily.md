# Make the day's «Кристальный босс» attacks — as many as the day still owes, and no more.
# ru: Дневная норма атак по кристальному боссу — сколько день ещё должен, и не больше.
#
# The errand a clock plays once a day. `attack_crystal_boss.md` is ONE attack and is what
# a person presses; this is the whole day's credit in one run, and the difference between
# them is the only reason this file exists — a timer set to the single attack would send
# one march a day and earn a third of the reward for ever.
#
# **HOW MANY IS THE GAME'S ANSWER, NEVER A NUMBER WRITTEN HERE.** The day pays for three
# attacks at the time of writing, and the server counts what has already been made — from
# this panel, from the phone, or by the person playing on the screen in front of them. So
# the run asks first and sends the difference: a day the person has already played by
# hand costs nothing, and a day nobody touched costs three marches.
#
# It ends as a SUCCESS and sends nothing when there is nothing to do:
#
#   * the event is not running — no window open, no boss on the map. A failure here would
#     sit out the retry hold and try again, all day, every retry period, over a state
#     that will not change until the next window;
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
# Nothing here presses anything itself: each attack is `CALL attack_crystal_boss`, which
# owns the whole of what an attack is — the ask, the boss out of the manager's own list,
# the first squad standing in the base, the send, and the proof that the server's count
# moved. A failing call unwinds this run with it, which is exactly the wanted behaviour.
#
# The panel plays this as the errand `attack_crystal_boss_daily`, switched off until the
# operator turns it on, at a period of a day. The reading behind the counts is
# actions/read_crystal_boss.md; the reverse-engineering is docs/research/crystal-boss.md.

# --- ask, then believe the answer -------------------------------------------------
TAP crystal_fetch

READ_LUA (function() local ok, st = pcall(function() return DataCenter.CrystalBossDataManager:GetMarchState() end) if not ok or type(st) ~= 'table' then return 0 end if st.activityId == nil then return 0 end return 1 end)() INTO cr_loaded

WHILE cr_loaded == 0 LIMIT 4
    WAIT 0.6
    READ_LUA (function() local ok, st = pcall(function() return DataCenter.CrystalBossDataManager:GetMarchState() end) if not ok or type(st) ~= 'table' then return 0 end if st.activityId == nil then return 0 end return 1 end)() INTO cr_loaded

READ_LUA (function() local ok, v = pcall(function() return (DataCenter.CrystalBossDataManager:IsOpen() and DataCenter.CrystalBossDataManager:IsActivityTimeOpen() and DataCenter.CrystalBossDataManager:IsBossAvailable()) end) if not ok then return nil end return (v and 1 or 0) end)() INTO cr_open

IF cr_open != 1
    LOG "«Кристальный босс» is not running right now — nothing is owed"
    STOP "no window is open"

# --- what the day still owes ------------------------------------------------------
# `-1` is «the counter could not be read», which is not «none left»: a client that has
# stopped answering would otherwise look exactly like a day already played, and the
# errand would write itself off as done until tomorrow.
READ_LUA ((function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetRemainAttackCount() end) if not ok or v == nil then return nil end local n = math.floor((v or 0) + 0) if n < 0 then n = 0 end return n end)() or -1) INTO cr_left

IF cr_left < 0
    FAIL "the day's attack count could not be read — check the client is still talking to the server"

IF cr_left < 1
    LOG "the day's «Кристальный босс» attacks are already made"
    STOP "nothing left to send today"

# --- send what is owed, re-asking the count after each ----------------------------
# The LIMIT is a safety rail rather than the rule: the loop leaves when the SERVER says
# nothing is owed, and the rail only matters if the event ever paid for more attacks than
# a day's worth of squads could make.
WHILE cr_left > 0 LIMIT 6
    CALL attack_crystal_boss
    TAP crystal_fetch
    READ_LUA ((function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetRemainAttackCount() end) if not ok or v == nil then return nil end local n = math.floor((v or 0) + 0) if n < 0 then n = 0 end return n end)() or -1) INTO cr_left

IF cr_left != 0
    FAIL "the day's «Кристальный босс» attacks are not all made — the clock will try again"

LOG "The day's «Кристальный босс» attacks are made"
