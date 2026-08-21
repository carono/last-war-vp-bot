# Recall a squad by the MARCH's uuid, the way the game's own march panel does — #1702.
# ru: Отозвать отряд по uuid марша — так же, как это делает панель марша в игре.
#
# `MarchUtil.OnBackHome(formationUuid)` frees a squad that is merely walking, and does
# NOT free one that has landed on a resource point and started gathering: measured live,
# a gather with 24 762 seconds left survived it. In the game a person recalls that squad
# by tapping the MARCH and pressing «вернуть», so the argument is the march, not the
# formation. This tries that, on the longest-running march we own, and says what changed.

READ_LUA (function() local out = {} local now = 0 pcall(function() now = tonumber(UITimeManager.Instance:GetServerTime()) or 0 end) local best, bestleft = nil, nil pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local e, u = nil, nil pcall(function() e = tonumber(m.endTime) end) pcall(function() u = m.uuid end) if e ~= nil and e > 0 and u ~= nil then local left = (e - now) / 1000 if bestleft == nil or left > bestleft then best, bestleft = u, left end end end end end) if best == nil then return 'no-march' end DataCenter.__lw_gold_recall = best local f = nil pcall(function() local p = DataCenter.__lw_gold or {} f = p.formation end) TimerManager:GetInstance():DelayInvoke(function() local ok1, e1 = pcall(function() MarchUtil.OnBackHome(best) end) CS.UnityEngine.Debug.LogError('ACT recall-by-uuid ok=' .. tostring(ok1) .. ' err=' .. tostring(e1)) end, 0.5) return 'recalling uuid=' .. tostring(best) .. ' left=' .. tostring(math.floor(bestleft)) .. 's' end)() INTO asked
LOG "recall by march uuid: {asked}"
WAIT 8
READ_LUA (function() local out = {} pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do local i = math.floor(tonumber(v.index) or -1) out[#out+1] = 'squad' .. i .. ' state=' .. tostring(v.state) .. ' canMarch=' .. tostring(v.canMarch) end end) local n = -1 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms ~= nil then n = ms.Count end end) out[#out+1] = 'marches=' .. tostring(n) return table.concat(out, ' | ') end)() INTO after
LOG "after the recall by uuid: {after}"
