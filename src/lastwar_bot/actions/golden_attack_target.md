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

# NOTHING IS ORDERED INTO A LINK THE SERVER HAS HUNG UP ON (#1702). The chain re-reads
# it every lap; a button pressed by hand had no such check at all, and a press into a
# deaf client draws a march the server never confirmed — a squad painted mid-move that
# takes no orders afterwards. One reading, at the top, before anything is sent.
WAIT client == ready WITHIN 20s

LUA DataCenter.__lw_gold_squad = {squad}
# AND IT COMES HOME AFTERWARDS (#1702). The chain leaves the squad standing where it
# killed, because the next pick is measured from there and the next order is seconds
# away. A press is not a chain: the operator watched a squad arrive at a tile whose
# zombie somebody else had already killed and simply STAY there, which from the outside
# is «доехал и застрял». `back = 1` is the game's own «come home when you are done», the
# flag a player's own attack carries.
LUA DataCenter.__lw_gold_back = 1
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
# The send brick reads `picked` — the chain sets it in the lap above, and a button
# pressed on its own has to set it too (#1702). It is the same question either
# way: is there a zombie parked to send at.
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO picked
CALL golden_send_the_squad
READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local seen = p.march_before or {} local fresh = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and not seen[u] then fresh = fresh + 1 end end end end) if fresh > 0 then return 1 end local busy = false pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then busy = (v.canMarch ~= true) end end end) return busy and 1 or 0 end)() INTO launched
IF launched == 1
    LOG "the game took the order — the squad is marching"
    # …AND THE TARGET IS WATCHED WHILE IT WALKS (#1702). A zombie is a thing other
    # players are also hunting, and the march is minutes: if it dies on the way, walking
    # the rest of it buys an empty tile. So the tile is asked about on every beat, and
    # the moment it comes up empty the squad is recalled — the same recall «Вернуть
    # отряд» plays, because there is one way to do a thing here.
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local t = p.hit if t == nil then return 1 end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return 1 end local want = tostring(t.key or t.uuid or 0) local there = false pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) return there and 0 or 1 end)() INTO gone
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived
    WHILE gone == 0 LIMIT {march_wait}
        WAIT 3
        TAP golden_scan
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived
        IF arrived == 1
            READ_LUA (1) INTO gone
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local t = p.hit if t == nil then return 1 end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return 1 end local want = tostring(t.key or t.uuid or 0) local there = false pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) return there and 0 or 1 end)() INTO gone
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived
    IF arrived == 0
        LOG "the zombie died while the squad was walking to it — calling the march back"
        TAP golden_unstick
IF launched == 0
    LOG "the game did not take the order — nothing is marching"

# A MARCH WITH NO ARRIVAL TIME IS OURS TO TAKE BACK (#1702). `endTime = 0` beside a real
# start is the client drawing an order the server never confirmed: the squad stands
# painted mid-move and refuses everything after it, which is «отряд застрял в текстурах».
# Leaving it there is leaving a state in the game that ordinary play never makes, so the
# press cleans up after itself rather than reporting success and walking away.
WAIT 3
READ_LUA (function() local p = DataCenter.__lw_gold or {} local want = p.march_uuid local tgt = nil if p.pending ~= nil then tgt = p.pending.uuid end if want == nil and tgt == nil then return 0 end local n = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local e, u, t = nil, nil, nil pcall(function() e = tonumber(m.endTime) end) pcall(function() u = tostring(m.uuid) end) pcall(function() t = tostring(m.targetUuid) end) local ours = (want ~= nil and u == tostring(want)) or (tgt ~= nil and t ~= nil and t == tostring(tgt)) if ours and (e == nil or e <= 0) then n = n + 1 end end end end) return n end)() INTO phantoms
IF phantoms > 0
    LOG "the game drew {phantoms} march(es) with no arrival time — taking them back"
    TAP golden_unstick
    WAIT 6
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local want = p.march_uuid local tgt = nil if p.pending ~= nil then tgt = p.pending.uuid end if want == nil and tgt == nil then return 0 end local n = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local e, u, t = nil, nil, nil pcall(function() e = tonumber(m.endTime) end) pcall(function() u = tostring(m.uuid) end) pcall(function() t = tostring(m.targetUuid) end) local ours = (want ~= nil and u == tostring(want)) or (tgt ~= nil and t ~= nil and t == tostring(tgt)) if ours and (e == nil or e <= 0) then n = n + 1 end end end end) return n end)() INTO phantoms
    IF phantoms > 0
        FAIL "a march with no arrival time is still there — the client needs a restart"
