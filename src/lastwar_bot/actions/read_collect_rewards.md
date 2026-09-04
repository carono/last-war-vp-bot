# What the special resource-collect watch has heard, and what the client still holds.
# ru: Что услышал караул спец-сбора ресурсов и что клиент ещё держит.
#
# The reading half of `watch_collect_rewards.md` (#2406): the ear's own ring, plus the
# client's list of points that are still standing. Nothing is asked of the server here —
# both come out of the game VM, and the list was filled by the same push the ear hears.
READ_LUA (function() local B = DataCenter.__lw_crw if B == nil then return 'караул не стоит' end if not B.on then return 'караул снят: ' .. tostring(B.err) end return 'услышал ' .. B.heard .. ', отправил ' .. B.sent .. ', пропустил ' .. B.skipped .. ', без координаты ' .. B.blind .. ', не смог ' .. B.failed .. ', снято сервером ' .. B.gone end)() INTO watch

READ_LUA (function() local B = DataCenter.__lw_crw if B == nil then return '-' end local rows = B.rows or {} local out = {} for i = math.max(1, #rows - 5), #rows do out[#out + 1] = rows[i] end if #out == 0 then return 'пока ничего' end return table.concat(out, '; ') end)() INTO recent

READ_LUA (function() local M = DataCenter.CollectRewardDataManager if type(M) ~= 'table' then return 'нет менеджера' end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerTime() or 0) + 0) end) local n, live = 0, 0 pcall(function() for _, r in pairs(M.collectRewardList or {}) do n = n + 1 local exp = math.floor((tonumber(tostring(r.expireTime or 0)) or 0) + 0) if exp == 0 or now == 0 or exp > now then live = live + 1 end end end) return 'точек в клиенте ' .. n .. ', из них живых ' .. live end)() INTO points

LOG "Спец-сбор: {watch}"
LOG "Спец-сбор: {points}"
LOG "Спец-сбор, последнее: {recent}"
