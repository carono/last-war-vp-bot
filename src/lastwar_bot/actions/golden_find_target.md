# Find the nearest golden zombie, FLY TO IT, and say where it is. Nothing is sent.
# ru: Найти ближайшего золотого зомби, перелететь к нему и показать координаты.
#
# Step one of the hunt, as a button of its own (#1702). The operator asked for the chain
# taken apart: press «найти», SEE the zombie that was chosen, and only then decide
# whether to send anything at it.
#
# Three things it does that the automatic chain does not, all three asked for:
#
#   * it takes NO leash. The chain refuses a target ten minutes' march away because it
#     is about to walk there; this button only looks, so the nearest is the nearest and
#     the distance is printed for the person to judge.
#   * it ENDS WITH THE CAMERA ON THE ZOMBIE, not back at the base. The camera going home
#     and the run stopping there is what «сценарий обрывается» was: the pick found
#     nothing inside the leash and halted with the map showing the house.
#   * it prints the tile in the panel's own coordinate token — `#server X:… Y:…` — which
#     the log turns into something a person can click to fly there (tools/lib/coords.py).
#
# The choice stays PARKED, and «Атаковать выбранного» sends at that and nothing else.

ARGS squad = 2
ARGS radius = 2000
ARGS refresh_after = 3

LUA DataCenter.__lw_gold_squad = {squad}
LUA DataCenter.__lw_gold_radius = {radius}
LUA DataCenter.__lw_gold_reach = 0
LUA DataCenter.__lw_gold_refresh_after = {refresh_after}
TAP golden_arm
READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end if (tonumber(p.soldiers) or 0) <= 0 then return -1 end return 1 end)() INTO armed
IF armed == 0
    FAIL "the squad is not one this account has — nothing to hunt with"

# Take what the client is holding, then look where the march would start from and take
# that too: the client answers only for ground it has been shown (#1702).
TAP golden_scan
TAP golden_look_from
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.looked_moved) or 0) == 1) and 1 or 0 end)() INTO looked_moved
IF looked_moved == 1
    WAIT 1
TAP golden_scan

CALL golden_choose_a_target
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO picked
IF picked == 0
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return -1 end local n = 0 pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(ws.CurTilePos, math.floor(tonumber(p.radius) or 2000), ids, res) local e = res:GetEnumerator() while e:MoveNext() do n = n + 1 end end) return n end)() INTO seen_now
    LOG "nothing chosen — the client can name {seen_now} golden zombie(s) from here"
    STOP "no target"

# …and the camera ends up ON IT. `golden_look` is the flight the ride uses to fetch a
# district; here it is the answer itself — the person pressed «найти», and finding
# something means being shown it.
TAP golden_look
WAIT 1
TAP golden_scan
READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return '' end local srv = math.floor(tonumber(c.server or p.server) or 0) local core = 'X:' .. tostring(math.floor(tonumber(c.x) or 0)) .. ' Y:' .. tostring(math.floor(tonumber(c.y) or 0)) if srv > 0 then return '#' .. tostring(srv) .. ' ' .. core end return core end)() INTO where
READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick
LOG "found a golden zombie at (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return '' end local srv = math.floor(tonumber(c.server or p.server) or 0) local core = 'X:' .. tostring(math.floor(tonumber(c.x) or 0)) .. ' Y:' .. tostring(math.floor(tonumber(c.y) or 0)) if srv > 0 then return '#' .. tostring(srv) .. ' ' .. core end return core end)() — {pick}"
