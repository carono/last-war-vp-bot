# Attack the zombie that is fixed, with the squad the panel has chosen. One march.
# ru: Атаковать зафиксированную цель отрядом, выбранным в панели. Один марш.
#
# Step two of the hunt as a button (#1702), and the operator's own terms for it: «берём
# ВЫБРАННЫЙ ОТРЯД в панели и бьём ЗАФИКСИРОВАННУЮ цель». So:
#
#   * the squad is the tab's, read fresh at the press — it may have been changed since
#     the target was found, and `golden_use_squad` writes it without disturbing the
#     target the way a full re-arm would;
#   * the target is the one already parked. Nothing here picks, re-picks, or walks down
#     a queue: with nothing fixed it says so and stops;
#   * a squad that cannot march is said out loud and nothing is sent. «Отряд занят» is
#     an answer, not a reason to fire an order into silence.
#
# What goes to the game is printed first — squad, formation, tile, and the call itself —
# so a refusal afterwards is read against what was actually asked for.

ARGS squad = 2
ARGS march_wait = 200
ARGS miss_limit = 6
ARGS approach = 0

LUA DataCenter.__lw_gold_squad = {squad}
TAP golden_use_squad

READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO have_target
IF have_target == 0
    LOG "no zombie is fixed — press «найти ближайшего» first"
    STOP "nothing chosen"

READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
IF squad_free == -2
    LOG "the client is holding no army for this squad — asking for it"
    CALL fill_empty_squads
    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
IF squad_free == 0
    LOG "the chosen squad is busy — it takes no orders just now, so nothing was sent"
    STOP "squad busy"
IF squad_free == -1
    LOG "there is no such squad on this account — nothing was sent"
    STOP "no squad"

READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur local where = 'none' if c ~= nil then local srv = math.floor(tonumber(c.server or p.server) or 0) where = '#' .. tostring(srv) .. ' X:' .. tostring(math.floor(tonumber(c.x) or 0)) .. ' Y:' .. tostring(math.floor(tonumber(c.y) or 0)) .. ' pid=' .. tostring(c.pid) end return 'squad=' .. tostring(p.squad) .. ' formation=' .. tostring(p.formation) .. ' soldiers=' .. tostring(math.floor(tonumber(p.soldiers) or 0)) .. ' target=' .. where .. ' call=SendCreateMarchMessage/ATTACK_MONSTER' end)() INTO order
LOG "sending: {order}"
CALL golden_send_the_squad
READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local seen = p.march_before or {} local fresh = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and not seen[u] then fresh = fresh + 1 end end end end) if fresh > 0 then return 1 end local busy = false pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then busy = (v.canMarch ~= true) end end end) return busy and 1 or 0 end)() INTO launched
IF launched == 1
    LOG "the game took the order — the squad is marching"
IF launched == 0
    LOG "the game did not take the order — nothing is marching"
