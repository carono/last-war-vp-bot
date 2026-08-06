# Read the state of «Кодовое имя» — the world-boss event, as the game holds it.
# ru: Прочитать состояние события «Кодовое имя» — как его держит игра.
#
# A READ: it presses nothing, opens nothing and changes nothing, so it is safe to run
# beside anything and as often as anybody likes. It does send ONE message — the
# server's own `user.get.act.boss.march` GET, the same one the game fires when it
# opens the event's screen — because without it there is nothing to read.
#
# THAT ASK IS THE WHOLE POINT OF THE FIRST STEP, and leaving it out is the bug this
# scenario was born with (#1257, fixed in #1259). The manager the reading comes from
# starts EMPTY: its stage list arrives only in the reply to that get, and
# `IsBossAvailable()` reads the stage list. A panel that never asked therefore drew
# «событие не идёт» over an event that was running all day, greyed the block out and
# disabled the button — and looked entirely reasonable doing it, because a shut event
# and an unasked client answer with the same zero. The client lies plausibly; the ask
# is what makes the answer true.
#
# «Кодовое имя» (the game's own word — key `100086`, «Codename» in English) puts one
# boss on the world map: «Кодовое имя 87» on Mondays and Thursdays, «64» on Tuesdays
# and Fridays, «39» on Wednesdays and Saturdays. It runs Monday to Saturday and it is
# open ALL DAY — one stage covering the whole server day — so the only day it is shut
# is Sunday. The four times the client keeps beside it are when the boss RESPAWNS
# during the day, not four separate windows. The day owes THREE attacks on it —
# attempts themselves are not
# rationed, the game's own rules say «кол-во попыток в день не ограничено», so what
# is counted is attacks MADE rather than an allowance spent. Beside the count, the
# thing worth showing is the biggest single hit: only the highest damage dealt in one
# attack goes into the daily ranking.
#
# The whole answer is ONE line in ONE variable, `codename`, as `key=value` pairs
# separated by spaces:
#
#     open=1 attacks=1 need=3 left=2 maxdmg=12607399171 targets=1 until=6042
#
# Every value is a whole number, and **`-` means the game would not answer** — a
# manager not loaded yet, a client still at the login screen, an account that has
# not unlocked the event. That is not the same as zero and must never be drawn as
# one: zero is «none», a dash is «nobody knows».
#
#   open      1 while the boss can be attacked RIGHT NOW — which, this event being
#             open all day from Monday to Saturday, is every day but Sunday. 0 is
#             what the panel draws grey, and every count beside it is then last
#             day's. It is only trustworthy AFTER the ask below has been answered.
#   attacks   attacks made in the current window. The SERVER owns this number, so it
#             counts an attack sent from anywhere — this panel, the phone, or the
#             person playing the game on the screen in front of them.
#   need      how many attacks earn the reward. Three, read out of the event's
#             config rather than written down here.
#   left      `need - attacks`, floored at zero — what the day still owes. Zero is
#             «the three are done», and further attacks are still allowed: they buy
#             a better damage ranking, not another tick.
#   maxdmg    the biggest single hit landed on the boss. This is the ranking's own
#             number, per the event's rules.
#   targets   how many boss instances the client currently has on the map. 0 with
#             `open=1` means the list has not arrived yet, not that there is none.
#   until     seconds left in the open window. A dash when no window is open.
#
# Every field is read inside its own `pcall`, so a manager that is missing costs one
# dash rather than the whole line, and ONE round trip carries all of it — a VM call
# costs about 0.15 s and the work inside it is free.
#
# The expressions are the SAME ones `tools/lib/lua_actions.py` gates the attack press
# on (`codename_*`), copied here rather than re-invented, and
# `tests/test_panel_events.py` fails if any of them stops matching. A count that said
# one thing to the board and another to the button would be worse than no count.
#
# Who reads it: the panel's «События» tab (`panel/tabs/events/`) and the «Кодовое
# имя» block on «Чеклист». The attack itself is actions/attack_codename_boss.md; the
# reverse-engineering is docs/research/codename-event.md.

# --- ask first, then read ---------------------------------------------------------
# The wait is bounded rather than open-ended because on a Sunday the reply carries no
# stage at all, and a read that hung waiting for one would never come back. Four
# tries is well past the round trip we measured; running out of them is itself an
# answer, and the read below then honestly says `open=0`.
TAP codename_fetch

READ_LUA ((type(DataCenter.ActBossDataManager.stageTimeList) == 'table') and 1 or 0) INTO cn_loaded

WHILE cn_loaded == 0 LIMIT 4
    WAIT 0.6
    READ_LUA ((type(DataCenter.ActBossDataManager.stageTimeList) == 'table') and 1 or 0) INTO cn_loaded

READ_LUA (function() local out={} local function put(k,f) local ok,v=pcall(f) if not ok or v==nil then out[#out+1]=k..'=-' return end local n=tonumber(v) if n~=nil then v=math.floor(n) end out[#out+1]=k..'='..tostring(v) end put('open',function() return (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager:IsBossAvailable() end) if not ok then return nil end return (v and 1 or 0) end)() end) put('attacks',function() return (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() end) put('need',function() return (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.rewardMaxTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() end) put('left',function() return (function() local a = (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() local n = (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.rewardMaxTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() if a == nil or n == nil then return nil end local l = n - a if l < 0 then l = 0 end return l end)() end) put('maxdmg',function() return (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.maxDamage end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() end) put('targets',function() return (function() local ok, l = pcall(function() return DataCenter.ActBossDataManager:GetActBossDataList() end) if not ok or type(l) ~= 'table' then return nil end local n = 0 for _ in pairs(l) do n = n + 1 end return n end)() end) put('until',function() return (function() local ok, st = pcall(function() return DataCenter.ActBossDataManager:GetAttackStageData() end) if not ok or type(st) ~= 'table' then return nil end local e = tonumber(st.endTime) if e == nil then return nil end local now = tonumber(UITimeManager:GetInstance():GetServerTime()) or 0 local left = e - now if left < 0 then left = 0 end return math.floor(left) end)() end) return table.concat(out,' ') end)() INTO codename
