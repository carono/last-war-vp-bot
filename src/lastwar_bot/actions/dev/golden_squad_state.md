# What the hunt's squad and its marches look like right now — the debugging brick (#1702).
# ru: Что сейчас с отрядом охоты и его маршами — отладочный кирпич (задача #1702).
#
# A read and nothing else. It exists because every «залипание» this task chased turned out
# to be a squad that could not take an order, and the only way to tell WHY is to look at
# the formation and at the marches it is on. Live, this is what ended the guessing:
#
#   squad=2 state=1 canMarch=false soldiers=2631
#   marches=2  m0 endTime=…452468  m1 endTime=…929588  now=…393277
#
# — 109 minutes on the second clock, which is a mine being gathered.

ARGS squad = 2

READ_LUA (function() local want = math.floor(tonumber({squad}) or 1) local out = {} local f = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == want then f = v end end end) if f == nil then return 'no such squad' end local uuid, st, can, n = '?', '?', '?', '?' pcall(function() uuid = tostring(f.uuid) end) pcall(function() st = tostring(f.state) end) pcall(function() can = tostring(f.canMarch) end) pcall(function() n = tostring(f.totalSoldierNum) end) out[#out+1] = 'squad=' .. want .. ' uuid=' .. uuid .. ' state=' .. st .. ' canMarch=' .. can .. ' soldiers=' .. n local now = 0 pcall(function() now = tonumber(UITimeManager.Instance:GetServerTime()) or 0 end) local ms = nil pcall(function() ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() end) if ms == nil then out[#out+1] = 'marches=nil' else out[#out+1] = 'marches=' .. tostring(ms.Count) for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local left = '?' pcall(function() left = tostring(math.floor((tonumber(m.endTime) - now) / 1000)) end) local u = '?' pcall(function() u = tostring(m.uuid) end) out[#out+1] = '  m' .. i .. ' uuid=' .. u .. ' left=' .. left .. 's' end end end return table.concat(out, ' || ') end)() INTO squad_state
LOG "golden squad state: {squad_state}"
