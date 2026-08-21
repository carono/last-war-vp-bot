# What the client's own march API looks like — a read, for #1702.
# ru: Что есть в march-API клиента — только чтение, задача #1702.
#
# The chain recalls a squad with `MarchUtil.OnBackHome(formation)`, and that shape was
# GUESSED: the code tries it with one argument and then with two, which is what code
# looks like when nobody knew. A guessed march primitive is exactly what this repository
# has been burned by before (docs/research/world-monsters.md, Findings 11 to 16) — it
# returns `true` and the server does nothing — and the operator has now seen a squad
# left in a state ordinary play never produces.
#
# So: what functions are there, and what does a march of ours actually carry? Nothing is
# sent from here.

READ_LUA (function() local out = {} local names = {} pcall(function() for k, v in pairs(MarchUtil) do if type(v) == 'function' then names[#names+1] = tostring(k) end end end) table.sort(names) out[#out+1] = 'MarchUtil: ' .. table.concat(names, ',') local mm = {} pcall(function() for k, v in pairs(DataCenter.WorldMarchDataManager) do if type(v) == 'function' and string.find(string.lower(tostring(k)), 'back') or string.find(string.lower(tostring(k)), 'recall') or string.find(string.lower(tostring(k)), 'return') then mm[#mm+1] = tostring(k) end end end) table.sort(mm) out[#out+1] = 'WorldMarchDataManager back/recall: ' .. table.concat(mm, ',') return table.concat(out, ' || ') end)() INTO march_api
LOG "march api: {march_api}"

READ_LUA (function() local out = {} pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then out[#out+1] = 'marches=nil' return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local fields = {} for _, f in ipairs({'uuid', 'endTime', 'startTime', 'state', 'marchType', 'targetType', 'targetUuid', 'pointId', 'targetPointId', 'formationUuid', 'armyUuid', 'backTime'}) do local v = nil pcall(function() v = m[f] end) if v ~= nil then fields[#fields+1] = f .. '=' .. tostring(v) end end out[#out+1] = 'm' .. tostring(i) .. ' ' .. table.concat(fields, ' ') end end end) return table.concat(out, ' || ') end)() INTO march_rows
LOG "march rows: {march_rows}"
