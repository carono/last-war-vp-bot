# Radar: read the board and change nothing (#1473).
# ru: Радар: снять показания доски, ничего не трогая.
#
# A READING, for proving one profile's radar is its own. `radar_full_cycle` prints the
# same numbers, but it also places, marches, helps and claims — so it cannot be used to
# watch a profile that is supposed to be standing still. This one sends nothing: every
# statement is a READ_LUA against `DataCenter.RadarCenterDataManager` and the client's
# own `detect_level` row, exactly as the cycle reads them.

READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, v = pcall(function() return M:GetDetectInfoLevel() end) return (ok and tonumber(v)) or 0 end)() INTO level
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_show_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() INTO capacity
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_max_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() INTO quota
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() INTO left
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() INTO onboard
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() INTO helpable
READ_LUA (function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)() INTO marches
READ_LUA (function() local ok, s = pcall(function() return tonumber(LuaEntry.Player.serverId) end) return (ok and tonumber(s)) or -1 end)() INTO server

LOG "radar-read: server {server} level {level} capacity {capacity} quota {quota} left {left} onboard {onboard} ripe {finished} helpable {helpable} marches {marches}"
