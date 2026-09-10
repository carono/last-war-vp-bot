# Read the state of «Кристальный босс» — the daily boss, as the game holds it.
# ru: Прочитать состояние события «Кристальный босс» — как его держит игра.
#
# A READ: it presses nothing, opens nothing and changes nothing, so it is safe to run
# beside anything. It does send ONE message — `red.boss.get.march`, the client's own
# get, the same one the game fires when it opens the event's screen — because without
# it there is nothing to read.
#
# THAT ASK IS THE FIRST STEP AND IT IS NOT OPTIONAL. The manager boots with no boss,
# no stage and no attack counter, and every getter beside them answers exactly as it
# would on a day the event were shut. That trap cost «Кодовое имя» a whole feature for
# a day (#1259) and it is the same trap here, with a different manager.
#
# «Кристальный босс» (the game's own word — key `red_world_boss_title1`, «Crystal Boss»
# in English) puts one boss on the world map for a window that covers the server day,
# and the day pays for THREE attacks on it. The client calls it the RED boss in code
# (`red.boss.*` on the wire) and the crystal one everywhere a person can see it.
#
# The whole answer is ONE line in ONE variable, `crystal`, as `key=value` pairs
# separated by spaces:
#
#     open=1 left=2 need=3 made=1 can=1 hp=100 targets=1 until=34133
#
# Every value is a whole number, and **`-` means the game would not answer** — a
# manager not loaded yet, a client still at the login screen, an account that has not
# unlocked the event. That is not the same as zero and must never be drawn as one:
# zero is «none», a dash is «nobody knows».
#
#   open      1 while the boss can be attacked at all right now: the activity is on,
#             the day's window is running and there is a boss standing in it.
#   left      attacks the day still owes. THE SERVER'S OWN NUMBER, so it counts an
#             attack made from anywhere — this panel, the phone, or the person playing
#             the game on the screen in front of them.
#   need      how many attacks the day pays for. Three, read out of the event rather
#             than written down here.
#   made      `need - left`, floored at zero. Derived, because the client keeps no
#             counter of its own for it — `transInfo.attackTimes` belongs to the
#             crystal TRANSPORT and read 0 on a day whose three attacks were all made.
#   can       what the client itself says about sending one right now.
#   hp        the boss's health, as a percentage of what it started the window with.
#   targets   how many boss instances the client has on the map. 0 with `open=1` means
#             the list has not arrived yet, not that there is none.
#   until     seconds left in the open window. A dash when no window is open.
#   bonus     CHESTS claimable right now, over both of the event's reward lists —
#             «Weekly Damage Rewards» (one per segment of the week's damage record)
#             and «Achievement Rewards» (one per achievement). One number, because a
#             person acts on one: there is something to take, or there is not.
#   wdone     damage segments of this week whose chest is already taken.
#   achdone   achievements whose chest is already taken.
#   achall    achievements the list holds in all.
#   daily     1 while the DAY'S chest can be claimed right now — the third reward the
#             event pays (#2702), whose whole gate is «the day's attacks are made». It
#             is the CLIENT'S own verdict, not a rule rebuilt here out of the two
#             numbers below it.
#   dtaken    1 when the day's chest has already been taken today. Not the opposite of
#             `daily`: a day whose attacks are not in yet is neither claimable nor
#             claimed, and both read 0.
#   dmade     attacks made toward the day's chest, as the CHEST'S own data counts them.
#   dneed     attacks the day's chest asks for. Three, read out of the event.
#
# Every field is read inside its own `pcall`, so a manager that is missing costs one
# dash rather than the whole line, and ONE round trip carries all of it — a VM call
# costs about 0.15 s and the work inside it is free.
#
# The expressions are the SAME ones `tools/lib/lua_actions.py` gates the attack on
# (`crystal_*`), copied here rather than re-invented. A count that said one thing to a
# board and another to the button would be worse than no count.
#
# The reading sends TWO gets, not one: `red.boss.get.march` for the boss and the day's
# attacks, and the event window's own panel get for the three chests. The second is why
# they can be counted at all — the lists and the day's chest are not there until
# something asks, exactly as the boss is not.
#
# The attack itself is actions/attack_crystal_boss.md, the day's worth of it is
# actions/attack_crystal_boss_daily.md, the chests are
# actions/collect_crystal_boss_rewards.md, and the reverse-engineering is
# docs/research/crystal-boss.md.

# --- ask first, then read ---------------------------------------------------------
# The wait is bounded rather than open-ended: a client that is not talking to the
# server has no reply to give, and running out of tries is itself an answer — the read
# below then honestly says `open=0` with dashes beside it.
TAP crystal_fetch

READ_LUA (function() local ok, st = pcall(function() return DataCenter.CrystalBossDataManager:GetMarchState() end) if not ok or type(st) ~= 'table' then return 0 end if st.activityId == nil then return 0 end return 1 end)() INTO cr_loaded

WHILE cr_loaded == 0 LIMIT 4
    WAIT 0.6
    READ_LUA (function() local ok, st = pcall(function() return DataCenter.CrystalBossDataManager:GetMarchState() end) if not ok or type(st) ~= 'table' then return 0 end if st.activityId == nil then return 0 end return 1 end)() INTO cr_loaded

# …and the second ask: the two reward lists. `RequestPanelData()` sends the progress
# get and the achievement get, and without them the chest counts read as «nothing to
# take» on an account with fifty-five waiting.
TAP crystal_rewards_fetch

READ_LUA (function() local out={} local function put(k,f) local ok,v=pcall(f) if not ok or v==nil then out[#out+1]=k..'=-' return end out[#out+1]=k..'='..tostring(math.floor(v+0)) end put('open',function() return (function() local ok, v = pcall(function() return (DataCenter.CrystalBossDataManager:IsOpen() and DataCenter.CrystalBossDataManager:IsActivityTimeOpen() and DataCenter.CrystalBossDataManager:IsBossAvailable()) end) if not ok then return nil end return (v and 1 or 0) end)() end) put('left',function() return (function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetRemainAttackCount() end) if not ok or v == nil then return nil end local n = math.floor((v or 0) + 0) if n < 0 then n = 0 end return n end)() end) put('need',function() return (function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetMaxAttackCount() end) if not ok or v == nil then return nil end return math.floor((v or 0) + 0) end)() end) put('made',function() return (function() local l = (function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetRemainAttackCount() end) if not ok or v == nil then return nil end local n = math.floor((v or 0) + 0) if n < 0 then n = 0 end return n end)() local n = (function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetMaxAttackCount() end) if not ok or v == nil then return nil end return math.floor((v or 0) + 0) end)() if l == nil or n == nil then return nil end local m = n - l if m < 0 then m = 0 end return m end)() end) put('can',function() return (function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:CanAttackBoss() end) if not ok then return nil end return (v and 1 or 0) end)() end) put('hp',function() return (function() local ok, b = pcall(function() return DataCenter.CrystalBossDataManager:GetCurrentBoss() end) if not ok or type(b) ~= 'table' then return nil end local h, full = b.armyHealth, b.armyInitHealth if h == nil or full == nil then return nil end h, full = h + 0, full + 0 if full <= 0 then return nil end return math.floor(h * 100 / full) end)() end) put('targets',function() return (function() local ok, n = pcall(function() return DataCenter.CrystalBossDataManager:GetBossDataCount() end) if not ok or n == nil then return nil end return math.floor((n or 0) + 0) end)() end) put('until',function() return (function() local ok, st = pcall(function() return DataCenter.CrystalBossDataManager:GetAttackStageData() end) if not ok or type(st) ~= 'table' then return nil end local e = st.endTime if e == nil then return nil end e = e + 0 local now = (UITimeManager:GetInstance():GetServerTime() or 0) + 0 local left = (e - now) / 1000 if left < 0 then left = 0 end return math.floor(left) end)() end) put('bonus',function() return (function() local w = nil local a = nil local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetClaimableCount() end) if ok and v ~= nil then w = math.floor(v + 0) end ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetAchievementClaimableCount() end) if ok and v ~= nil then a = math.floor(v + 0) end if w == nil and a == nil then return nil end return (w or 0) + (a or 0) end)() end) put('wdone',function() return (function() local ok, d = pcall(function() return DataCenter.CrystalBossDataManager:GetProgressData() end) if not ok or type(d) ~= 'table' then return nil end local v = d.claimedMax if v == nil then return nil end return math.floor(v + 0) end)() end) put('achdone',function() return (function() local ok, list = pcall(function() return DataCenter.CrystalBossDataManager:GetAchievementDisplayTasks() end) if not ok or type(list) ~= 'table' then return nil end local n, taken = 0, 0 for _, t in pairs(list) do n = n + 1 if type(t) == 'table' and (t.state or 0) + 0 == 2 then taken = taken + 1 end end return taken end)() end) put('achall',function() return (function() local ok, list = pcall(function() return DataCenter.CrystalBossDataManager:GetAchievementDisplayTasks() end) if not ok or type(list) ~= 'table' then return nil end local n, taken = 0, 0 for _, t in pairs(list) do n = n + 1 if type(t) == 'table' and (t.state or 0) + 0 == 2 then taken = taken + 1 end end return n end)() end) put('daily',function() return (function() local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:CanClaimDailyReward() end) if not ok or v == nil then return nil end return (v and 1 or 0) end)() end) put('dtaken',function() return (function() local ok, d = pcall(function() return DataCenter.CrystalBossDataManager:GetDailyRewardData() end) if not ok or type(d) ~= 'table' then return nil end local v = d.claimed if v == nil then return nil end return (v and 1 or 0) end)() end) put('dmade',function() return (function() local ok, d = pcall(function() return DataCenter.CrystalBossDataManager:GetDailyRewardData() end) if not ok or type(d) ~= 'table' then return nil end local v = d.attackCount if v == nil then return nil end return math.floor(v + 0) end)() end) put('dneed',function() return (function() local ok, d = pcall(function() return DataCenter.CrystalBossDataManager:GetDailyRewardData() end) if not ok or type(d) ~= 'table' then return nil end local v = d.target if v == nil then return nil end return math.floor(v + 0) end)() end) return table.concat(out,' ') end)() INTO crystal
