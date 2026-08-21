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
#
# IT ALSO PRINTS WHOSE MARCH EACH ONE IS (#1702). «canMarch=true with a march in flight»
# is a state the chain's launch proof does not expect, and telling it from «the order was
# refused» needs the march's own formation beside the hunt's — not the count.

READ_LUA (function() local out = {} local now = 0 pcall(function() now = tonumber(UITimeManager.Instance:GetServerTime()) or 0 end) local rows = {} pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do local idx = math.floor(tonumber(v.index) or -1) local can, st, n, uuid = '?', '?', '?', '?' pcall(function() can = tostring(v.canMarch) end) pcall(function() st = tostring(v.state) end) pcall(function() n = tostring(v.totalSoldierNum) end) pcall(function() uuid = tostring(v.uuid) end) rows[#rows+1] = {idx, 'squad' .. idx .. ' state=' .. st .. ' canMarch=' .. can .. ' soldiers=' .. n} end end) table.sort(rows, function(a, b) return a[1] < b[1] end) for _, r in ipairs(rows) do out[#out+1] = r[2] end local ms = nil pcall(function() ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() end) if ms == nil then out[#out+1] = 'marches=nil' else local parts = {} for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local left = '?' pcall(function() left = tostring(math.floor((tonumber(m.endTime) - now) / 1000)) end) local mu, mf, mt, mst = '?', '?', '?', '?' pcall(function() mu = tostring(m.uuid) end) pcall(function() if m.formationUuid ~= nil then mf = tostring(m.formationUuid) end end) pcall(function() if mf == '?' and m.armyInfo ~= nil then mf = tostring(m.armyInfo.f4 or m.armyInfo.formationUuid or '?') end end) pcall(function() mt = tostring(m.marchType or m.type or '?') end) pcall(function() mst = tostring(m.state or '?') end) parts[#parts+1] = 'left=' .. left .. 's uuid=' .. mu .. ' form=' .. mf .. ' type=' .. mt .. ' state=' .. mst end end out[#out+1] = 'marches=' .. tostring(ms.Count) .. ' [' .. table.concat(parts, ' ') .. ']' end local rally = '?' pcall(function() local t = DataCenter.__lw_rally_squads if type(t) == 'table' then local xs = {} for _, v in ipairs(t) do xs[#xs+1] = tostring(v) end rally = table.concat(xs, ',') end end) out[#out+1] = 'rally_squads=' .. rally local ours = '?' pcall(function() local g = DataCenter.__lw_gold or {} ours = tostring(g.formation or '-') end) out[#out+1] = 'hunt_formation=' .. ours return table.concat(out, ' || ') end)() INTO squad_state
LOG "golden squad state: {squad_state}"
