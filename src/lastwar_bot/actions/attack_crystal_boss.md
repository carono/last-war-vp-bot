# Attack the «Кристальный босс» once, with a squad standing in the base.
# ru: Одна атака по кристальному боссу отрядом, стоящим в базе.
#
# The event puts one boss on the world map and the day pays for THREE attacks on it.
# This recipe is ONE attack: run it three times for the day's credit, or let
# actions/attack_crystal_boss_daily.md ask the server how many are still owed.
#
# It takes no arguments. «A free squad» is not a choice the person should have to make
# three times a day: the run finds the first squad standing in the base and sends that
# one. A squad already marching, gathering, standing in a rally or wiped cannot be sent
# at all, and there is nothing to choose between the ones that can.
#
# NO WINDOW IS OPENED AND THE CAMERA IS NOT MOVED. A person walks five screens for this
# — the event window, its «Атака» (which sends nothing, it only flies the camera to the
# boss), the boss on the map, «Атака» in its popup, then the squad screen — and all five
# end at ONE call, the same one «Кодовое имя» was recorded making (#1259) with this
# boss's own march type:
#
#     world.march.formation.new  <-  SendCreateMarchMessage(formation, 194, point, uuid,
#                                    1, 1, false, server, nil)
#
# 194 is `MarchTargetType.DIRECT_ATTACK_RED_BOSS`, out of the client's own table, and
# 196 (`CROSS_…`) when the boss stands on another server. The boss is addressed by its
# uuid, so none of the walk is load-bearing: there is no tile to wait for the client to
# stream in, and the server works the path out itself.
#
# Three steps, and each waits for the game to be in the next state rather than sleeping
# a guessed amount:
#
#   1. ASK. The manager boots empty and answers «no boss, event shut» until the reply
#      to `red.boss.get.march` lands. Every later step reads what this brings back;
#   2. arm — the boss out of the manager's own list, and the first squad standing in
#      the base, both before anything is sent;
#   3. send, and let the SERVER say whether an attack went out.
#
# Nothing is claimed from a press that returned cleanly. The run ends as a FAILURE,
# naming the step, when the event is not running, when the boss is not in the list yet,
# when no squad is standing in the base, when the day owes nothing more, and when
# everything was sent and the count did not move. A timer therefore keeps its place and
# tries again instead of counting an attack that never went out.
#
# **A count that does not move can also mean the client is no longer talking to the
# server** — a stranded client goes on answering every getter with yesterday's numbers
# and returning `true` from every send (docs/research/server-link-status.md). The
# panel's status strip is what says that, and it is worth a glance before believing the
# failure below.
#
# The presses live in tools/lib/game_buttons.py (`crystal_*`) and their engine calls in
# tools/lib/lua_actions.py; the reverse-engineering is docs/research/crystal-boss.md.

# --- 1. Ask, then believe the answer ----------------------------------------------
TAP crystal_fetch

READ_LUA (function() local ok, st = pcall(function() return DataCenter.CrystalBossDataManager:GetMarchState() end) if not ok or type(st) ~= 'table' then return 0 end if st.activityId == nil then return 0 end return 1 end)() INTO cr_loaded

WHILE cr_loaded == 0 LIMIT 4
    WAIT 0.6
    READ_LUA (function() local ok, st = pcall(function() return DataCenter.CrystalBossDataManager:GetMarchState() end) if not ok or type(st) ~= 'table' then return 0 end if st.activityId == nil then return 0 end return 1 end)() INTO cr_loaded

READ_LUA (function() local ok, v = pcall(function() return (DataCenter.CrystalBossDataManager:IsOpen() and DataCenter.CrystalBossDataManager:IsActivityTimeOpen() and DataCenter.CrystalBossDataManager:IsBossAvailable()) end) if not ok then return nil end return (v and 1 or 0) end)() INTO cr_open

IF cr_open != 1
    FAIL "«Кристальный босс» is not running — there is no boss to attack right now"

# --- 2. Is one owed at all --------------------------------------------------------
# The day's attacks are the SERVER's count, so a day already played by hand costs
# nothing here — and sending a fourth march at a boss that pays for three would spend a
# squad for no reward at all.
READ_LUA ((function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetRemainAttackCount() end) if not ok or v == nil then return nil end local n = math.floor((v or 0) + 0) if n < 0 then n = 0 end return n end)() or -1) INTO cr_left

IF cr_left < 0
    FAIL "the day's attack count could not be read — check the client is still talking to the server"
IF cr_left < 1
    FAIL "the day's «Кристальный босс» attacks are already made"

# --- 3. Which boss, and which squad -----------------------------------------------
# Both before anything is sent: a run that finds out at the send that there was no squad
# has already told the server it was coming.
TAP crystal_arm

READ_LUA (function() local p = DataCenter.__lw_crystal or {} if p.uuid == nil or p.point == nil then return 0 end if p.formation == nil then return -1 end return 1 end)() INTO armed

IF armed == 0
    FAIL "the event is running but its boss is not in the list yet — try again in a moment"
IF armed < 0
    FAIL "no squad is standing in the base — every one of them is already out"

# --- 4. Send, and let the game say whether an attack went out ---------------------
# The proof is the SERVER's own count going DOWN, not the send returning cleanly.
#
# EACH POLL ASKS AGAIN, and that is the whole reason this loop works: the count is the
# server's, and the client does not learn the new one on its own — the same lesson
# «Кодовое имя» cost an afternoon (#1259), where a run reported «the count did not move»
# over an attack that had already gone out and could be seen in the game.
TAP crystal_send

TAP crystal_fetch

READ_LUA (function() local cur = (function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetRemainAttackCount() end) if not ok or v == nil then return nil end local n = math.floor((v or 0) + 0) if n < 0 then n = 0 end return n end)() if cur == nil then return -1 end return ((DataCenter.__lw_crystal or {}).before or 0) - cur end)() INTO sent

# Twelve, not six: the server took eight seconds to own up to the first attack proven
# this way on the sister event, which is six asks — a limit that only just cleared it is
# a run that reports a false failure the first time the server is busy.
WHILE sent < 1 LIMIT 12
    TAP crystal_fetch
    READ_LUA (function() local cur = (function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetRemainAttackCount() end) if not ok or v == nil then return nil end local n = math.floor((v or 0) + 0) if n < 0 then n = 0 end return n end)() if cur == nil then return -1 end return ((DataCenter.__lw_crystal or {}).before or 0) - cur end)() INTO sent

IF sent < 1
    FAIL "the squad was sent and the day's attack count did not move — check the client is still talking to the server"

LOG "A squad is on its way to the «Кристальный босс»"
