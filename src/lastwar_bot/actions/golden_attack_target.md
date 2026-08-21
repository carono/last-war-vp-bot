# Attack the zombie «Найти ближайшего» chose — one march, and say what the game did.
# ru: Атаковать выбранного зомби — один марш, и что ответила игра.
#
# Step two, as a button of its own (#1702). It sends at the target ALREADY PARKED by
# `golden_find_target.md` and at nothing else: no picking, no re-choosing, no walking
# down the queue. If nothing is parked it says so and stops, because a button called
# «атаковать выбранного» must never invent a target for itself.

ARGS squad = 2
ARGS march_wait = 200
ARGS miss_limit = 6
ARGS approach = 0

READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO have_target
IF have_target == 0
    STOP "nothing chosen — press «найти ближайшего» first"

READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick
LOG "attacking: {pick}"
CALL golden_send_the_squad
READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local seen = p.march_before or {} local fresh = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and not seen[u] then fresh = fresh + 1 end end end end) if fresh > 0 then return 1 end local busy = false pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then busy = (v.canMarch ~= true) end end end) return busy and 1 or 0 end)() INTO launched
IF launched == 1
    LOG "the order was taken — the squad is on its way"
IF launched == 0
    LOG "the game did not take the order — nothing is marching"
