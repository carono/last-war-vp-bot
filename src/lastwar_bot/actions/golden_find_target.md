# Find the nearest golden zombie in the registry, fix it, and show it. Three calls.
# ru: Найти в реестре ближайшего зомби, зафиксировать и показать. Три обращения к игре.
#
# The operator's own definition of the button: «посмотреть в реестр монстров, вычислить
# ближайшего до выбранного отряда или базы, зафиксировать его координаты» — and then
# «должно быть МГНОВЕННО».
#
# A round trip to the game's VM costs about a tenth of a second, and this used to make
# fourteen of them plus a fixed second of settling. Inside the VM the same work is free,
# so it is three now:
#
#   1. prepare — squad, formation, origin (the squad's tile when it is out, the base's
#      when it is home), radius, and the base tile remembered from last time;
#   2. scan — read the ground the client is holding into the registry;
#   3. pick — the arithmetic, the tile, and the line the log prints, in one answer.
#
# The only step that still costs real time is the camera, and it is paid ONLY when the
# squad is out in the field: the client answers `GetMonsterListInArea` out of the tiles
# it has been shown, so the ground around the squad has to be fetched before the sum.

ARGS squad = 2
ARGS radius = 2000

LUA DataCenter.__lw_gold_squad = {squad}
LUA DataCenter.__lw_gold_radius = {radius}
READ_LUA (function() local p = DataCenter.__lw_gold or {} local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return -1 end p.squad = math.floor(tonumber(DataCenter.__lw_gold_squad) or p.squad or 1) p.formation = nil p.soldiers = 0 local out = 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == p.squad then p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) if math.floor(tonumber(v.state) or 0) ~= 0 then out = 1 end end end end) if p.formation == nil then return 'nosquad' end if out == 1 then if p.anchor == nil then p.anchor = p.last_sent end else p.anchor = nil end if p.home == nil then p.home = DataCenter.__lw_gold_home end p.radius = math.floor(tonumber(DataCenter.__lw_gold_radius) or 2000) p.reach = 0 if p.targets == nil then p.targets = {} end if p.used == nil then p.used = {} end DataCenter.__lw_gold = p return out end)() INTO ready
IF ready == -2
    FAIL "the squad is not one this account has — nothing to hunt with"

IF ready == 1
    LOG "measuring from where the squad stands"
    TAP golden_scan
    TAP golden_look_from
    # NO FIXED SLEEP (#1702). The camera move is only worth waiting for until the client
    # has the ground, and it usually has it at once; polling costs a tenth of a second
    # per look instead of six tenths of doing nothing.
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return -1 end local n = 0 pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(ws.CurTilePos, math.floor(tonumber(p.radius) or 2000), ids, res) local e = res:GetEnumerator() while e:MoveNext() do n = n + 1 end end) return n end)() INTO seen_here
    WHILE seen_here == 0 LIMIT 6
        WAIT 0.1
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return -1 end local n = 0 pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(ws.CurTilePos, math.floor(tonumber(p.radius) or 2000), ids, res) local e = res:GetEnumerator() while e:MoveNext() do n = n + 1 end end) return n end)() INTO seen_here
IF ready == 0
    LOG "the squad is at home — measuring from the base"

TAP golden_scan
READ_LUA (function() local p = DataCenter.__lw_gold or {} local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end p.cur = nil local ox, oy, from = nil, nil, 'oracle' if p.anchor ~= nil then ox, oy, from = p.anchor.x, p.anchor.y, 'anchor' elseif p.home ~= nil then ox, oy, from = p.home.x, p.home.y, 'home' end local best, bestd = nil, nil for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then local d = nil if ox ~= nil then local dx, dy = (t.x - ox), (t.y - oy) d = math.sqrt(dx * dx + dy * dy) else pcall(function() d = tonumber(SceneUtils.TileDistanceToMyHome(t.pid, p.server)) end) end if d ~= nil and (bestd == nil or d < bestd) then best, bestd = t, d end end end if best == nil then local n = 0 pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() if ws ~= nil then ws:GetMonsterListInArea(ws.CurTilePos, math.floor(tonumber(p.radius) or 2000), ids, res) local e = res:GetEnumerator() while e:MoveNext() do n = n + 1 end end end) DataCenter.__lw_gold = p if n > 0 then return 'nonenear' end return 'noneseen' end p.cur = best p.curdist = math.floor(bestd + 0.5) p.curfrom = from DataCenter.__lw_gold = p local srv = math.floor(tonumber(best.server or p.server) or 0) local tile = 'X:' .. tostring(math.floor(best.x)) .. ' Y:' .. tostring(math.floor(best.y)) if srv > 0 then tile = '#' .. tostring(srv) .. ' ' .. tile end local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(best.pid, p.server)) end) local queued = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then queued = queued + 1 end end return tile .. '|at=' .. tostring(best.x) .. ',' .. tostring(best.y) .. ' dist=' .. tostring(p.curdist) .. ' from=' .. from .. ' origin=' .. tostring(ox) .. ',' .. tostring(oy) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' queued=' .. tostring(queued) end)() INTO found
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO picked
IF picked == 0
    LOG "the client can see no golden zombie from here — the wave is not up"
    STOP "no target"
IF ready == -1
    LOG "there are zombies in view but none the registry could take — press «обновить карту»"
    STOP "no target"
LOG "found a golden zombie: {found}"
TAP golden_look
