# Attack the fixed zombie with the squad the panel has chosen. Two calls, then the send.
# ru: Атаковать зафиксированную цель отрядом из панели. Два обращения и отправка.
#
# «Должно быть мгновенно» (#1702). What the press must do has not changed — the panel's
# squad, the fixed target, nothing invented — but it used to ask the VM for those facts
# one at a time: point at the squad, forget the last order, is there a target, is the
# squad free, and again after a wait. `golden_ready_to_send` answers all of it in one
# breath, and what is left costing time is the server's own answer.
#
# What is deliberately kept: the link is read before anything is ordered; the march is
# the one that comes home afterwards; and a march the server never confirmed is taken
# back rather than left standing in the game.

ARGS squad = 2
ARGS march_wait = 200
ARGS miss_limit = 6
ARGS approach = 0

WAIT client == ready WITHIN 20s
LUA DataCenter.__lw_gold_squad = {squad}
LUA DataCenter.__lw_gold_back = 1

READ_LUA (function() local p = DataCenter.__lw_gold or {} p.squad = math.floor(tonumber(DataCenter.__lw_gold_squad) or p.squad or 1) p.formation = nil p.soldiers = 0 local state = nil local can = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == p.squad then p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) state = math.floor(tonumber(v.state) or 0) can = (v.canMarch == true) end end end) p.pending = nil p.hit = nil p.march_uuid = nil p.misses = 0 if p.cur ~= nil and p.used ~= nil then p.used[tostring(p.cur.pid)] = nil end DataCenter.__lw_gold = p if p.formation == nil then return -2 end if p.cur == nil then return -3 end if can then return 1 end if math.floor(tonumber(p.soldiers) or 0) <= 0 then return -2 end return 0 end)() INTO ready
IF ready == -3
    LOG "no zombie is fixed — press «найти ближайшего» first"
    STOP "nothing chosen"
IF ready == -1
    LOG "there is no such squad on this account — nothing was sent"
    STOP "no squad"
IF ready == -2
    LOG "the client is holding no army for this squad — asking for it"
    CALL fill_empty_squads
    READ_LUA (function() local p = DataCenter.__lw_gold or {} p.squad = math.floor(tonumber(DataCenter.__lw_gold_squad) or p.squad or 1) p.formation = nil p.soldiers = 0 local state = nil local can = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == p.squad then p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) state = math.floor(tonumber(v.state) or 0) can = (v.canMarch == true) end end end) p.pending = nil p.hit = nil p.march_uuid = nil p.misses = 0 if p.cur ~= nil and p.used ~= nil then p.used[tostring(p.cur.pid)] = nil end DataCenter.__lw_gold = p if p.formation == nil then return -2 end if p.cur == nil then return -3 end if can then return 1 end if math.floor(tonumber(p.soldiers) or 0) <= 0 then return -2 end return 0 end)() INTO ready
IF ready == 0
    # A squad turned round a second ago is still walking home and reads «busy» for a
    # beat; refusing outright is what «второй раз не смог отправить» was.
    LOG "the squad is not free yet — giving it a few seconds"
    WHILE ready == 0 LIMIT 6
        WAIT 1
        READ_LUA (function() local p = DataCenter.__lw_gold or {} p.squad = math.floor(tonumber(DataCenter.__lw_gold_squad) or p.squad or 1) p.formation = nil p.soldiers = 0 local state = nil local can = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == p.squad then p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) state = math.floor(tonumber(v.state) or 0) can = (v.canMarch == true) end end end) p.pending = nil p.hit = nil p.march_uuid = nil p.misses = 0 if p.cur ~= nil and p.used ~= nil then p.used[tostring(p.cur.pid)] = nil end DataCenter.__lw_gold = p if p.formation == nil then return -2 end if p.cur == nil then return -3 end if can then return 1 end if math.floor(tonumber(p.soldiers) or 0) <= 0 then return -2 end return 0 end)() INTO ready
IF ready == 0
    LOG "the chosen squad is busy — it takes no orders just now, so nothing was sent"
    STOP "squad busy"

READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur local where = 'none' if c ~= nil then local srv = math.floor(tonumber(c.server or p.server) or 0) where = '#' .. tostring(srv) .. ' X:' .. tostring(math.floor(tonumber(c.x) or 0)) .. ' Y:' .. tostring(math.floor(tonumber(c.y) or 0)) .. ' pid=' .. tostring(c.pid) end return 'squad=' .. tostring(p.squad) .. ' formation=' .. tostring(p.formation) .. ' soldiers=' .. tostring(math.floor(tonumber(p.soldiers) or 0)) .. ' target=' .. where .. ' call=SendCreateMarchMessage/ATTACK_MONSTER' end)() INTO order
LOG "sending: {order}"
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO picked
CALL golden_send_the_squad
READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local seen = p.march_before or {} local fresh = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and not seen[u] then fresh = fresh + 1 end end end end) if fresh > 0 then return 1 end local busy = false pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then busy = (v.canMarch ~= true) end end end) return busy and 1 or 0 end)() INTO launched
IF launched == 1
    LOG "the game took the order — the squad is marching"
IF launched == 0
    LOG "the game did not take the order — nothing is marching"

# A march the server never gave an arrival time to is ours to take back — the squad
# painted mid-move, refusing everything after it. Narrow on purpose: a rally has no
# clock either, and recalling one would pull the account out of its alliance's sortie.
READ_LUA (function() local p = DataCenter.__lw_gold or {} local want = p.march_uuid local tgt = nil if p.pending ~= nil then tgt = p.pending.uuid end if want == nil and tgt == nil then return 0 end local n = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local e, u, t = nil, nil, nil pcall(function() e = tonumber(m.endTime) end) pcall(function() u = tostring(m.uuid) end) pcall(function() t = tostring(m.targetUuid) end) local ours = (want ~= nil and u == tostring(want)) or (tgt ~= nil and t ~= nil and t == tostring(tgt)) if ours and (e == nil or e <= 0) then n = n + 1 end end end end) return n end)() INTO phantoms
IF phantoms > 0
    LOG "the game drew {phantoms} march(es) with no arrival time — taking them back"
    TAP golden_unstick
