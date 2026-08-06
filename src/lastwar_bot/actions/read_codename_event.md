# Read the state of «Кодовое имя» — the world-boss event, as the game holds it.
# ru: Прочитать состояние события «Кодовое имя» — как его держит игра.
#
# A READ, and nothing else: it presses nothing, opens nothing, sends nothing and
# changes nothing, so it is safe to run beside anything and as often as anybody
# likes.
#
# «Кодовое имя» (the game's own word — key `100086`, «Codename» in English) puts one
# boss on the world map for a few hours at a time: «Кодовое имя 87» on Mondays and
# Thursdays, «64» on Tuesdays and Fridays, «39» on Wednesdays and Saturdays, four
# windows a day. The day owes THREE attacks on it — attempts themselves are not
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
#   open      1 while the boss can be attacked RIGHT NOW. Not «is today a boss day»:
#             the boss comes and goes several times a day, and outside a window
#             there is nothing on the map to send a squad at. 0 is what the panel
#             draws grey, and every count beside it is then last window's.
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

READ_LUA (function() local out={} local function put(k,f) local ok,v=pcall(f) if not ok or v==nil then out[#out+1]=k..'=-' return end local n=tonumber(v) if n~=nil then v=math.floor(n) end out[#out+1]=k..'='..tostring(v) end put('open',function() return (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager:IsBossAvailable() end) if not ok then return nil end return (v and 1 or 0) end)() end) put('attacks',function() return (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() end) put('need',function() return (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.rewardMaxTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() end) put('left',function() return (function() local a = (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() local n = (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.rewardMaxTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() if a == nil or n == nil then return nil end local l = n - a if l < 0 then l = 0 end return l end)() end) put('maxdmg',function() return (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.maxDamage end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() end) put('targets',function() return (function() local ok, l = pcall(function() return DataCenter.ActBossDataManager:GetActBossDataList() end) if not ok or type(l) ~= 'table' then return nil end local n = 0 for _ in pairs(l) do n = n + 1 end return n end)() end) put('until',function() return (function() local ok, st = pcall(function() return DataCenter.ActBossDataManager:GetAttackStageData() end) if not ok or type(st) ~= 'table' then return nil end local e = tonumber(st.endTime) if e == nil then return nil end local now = tonumber(UITimeManager:GetInstance():GetServerTime()) or 0 local left = e - now if left < 0 then left = 0 end return math.floor(left) end)() end) return table.concat(out,' ') end)() INTO codename
