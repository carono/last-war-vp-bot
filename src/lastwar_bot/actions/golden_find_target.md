# Find the nearest golden zombie and SAY WHERE IT IS. Nothing is sent.
# ru: Найти ближайшего золотого зомби и показать его. Ничего не отправляется.
#
# Step one of the hunt, as a button of its own (#1702). The operator asked for the chain
# taken apart: press «найти», look at what was chosen, and only then decide whether to
# send anything at it. So this arms the run exactly as the chain does — the squad, the
# purse, the price, the base's own tile — puts the camera where the next march would
# start from, asks the client about that ground, and picks the nearest.
#
# It leaves the choice PARKED (`DataCenter.__lw_gold.cur`), which is what «атаковать
# выбранного» then sends at. Pressing it again simply chooses again.

ARGS squad = 2
ARGS radius = 2000
ARGS reach = 200
ARGS refresh_after = 3

LUA DataCenter.__lw_gold_squad = {squad}
LUA DataCenter.__lw_gold_radius = {radius}
LUA DataCenter.__lw_gold_reach = {reach}
LUA DataCenter.__lw_gold_refresh_after = {refresh_after}
TAP golden_arm
READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end if (tonumber(p.soldiers) or 0) <= 0 then return -1 end return 1 end)() INTO armed
IF armed == 0
    FAIL "the squad is not one this account has — nothing to hunt with"

# Take what the client is holding first, then move the camera and take that too: the
# client answers only for ground it has been shown (#1702).
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
    LOG "nothing chosen — the client can name {seen_now} golden zombie(s) around the squad right now"
    STOP "no target"
READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick
LOG "chosen: {pick}"
