# How the «Beneath the Ruins» autopilot is getting on, and its best depth.
# ru: Как идёт автопилот «Под руинами» и какая у него лучшая глубина.

READ_LUA (function() local ok, res = pcall(function() local t = __lw_gg if t == nil then return 'idle' end if t.off then for _, nd in ipairs(t.nodes or {}) do pcall(function() UpdateBeat:RemoveListener(nd) end) end t.nodes = {} end return 'rounds=' .. tostring(t.rounds) .. '/' .. tostring(t.want) .. ' best=' .. string.format('%.2f', -t.best) .. ' last=' .. string.format('%.2f', -(t.last or 0)) .. ' done=' .. tostring(t.off) .. ' err=' .. tostring(t.err) .. ' | ' .. table.concat(t.log, '; ') end) return tostring(ok) .. ' :: ' .. tostring(res) end)() INTO run
LOG "beneath-ruins: {run}"
