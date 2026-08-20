# Choose the next golden zombie and make sure it is real — one brick of the chain.
# ru: Выбрать следующего золотого зомби и убедиться, что он есть, — кирпич цепочки.
#
# The nearest target to where the squad is standing, out of the registry the scans keep;
# then the two checks that stop an order being wasted — the live uuid, and «is it still on
# a piece of map we have actually read».
#
# Leaves `picked` at 1 with a target armed, or 0. Runnable on its own (#1702): pressing it
# is a safe, read-only «what would the chain go for next».

# THE THRESHOLD FIRST — the ground is redrawn only when it has been PROVEN stale, never
# on a clock (#1702). Below the threshold nothing flies anywhere; at it, one short ring
# around the origin of the next pick, and then the choice is made over the fresher queue.
READ_LUA (function() local p = DataCenter.__lw_gold or {} local n = math.floor(tonumber(p.since_refresh) or 0) local lim = math.floor(tonumber(DataCenter.__lw_gold_refresh_after) or 3) if lim <= 0 then return 0 end return (n >= lim) and 1 or 0 end)() INTO needs_refresh
IF needs_refresh == 1
    LOG "several targets in a row were gone — redrawing the ground before choosing"
    TAP golden_refresh
    READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
    WHILE refreshed == 0 LIMIT 12
        WAIT 1
        READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
    TAP golden_scan

# …AND THEN CHOOSE UNTIL A TARGET IS ONE THE CLIENT CAN STILL NAME (#1702).
#
# Measured live: of fifteen laps of a run, NINE ended in `dropped=stale` — the send itself
# discovered that the client had forgotten that uuid, and a whole lap had been spent
# getting there. The check is the same one; it just belongs here, where it costs a fifth
# of a second and the answer is «pick again» rather than «this lap is over».
#
# Strict, unlike the registry's own rule, and deliberately so: this is one target a march
# is about to be spent on, so «the client cannot name it» is reason enough to drop it,
# where for the REGISTRY it would not be (docs/research/golden-zombies.md §4b).
READ_LUA (1) INTO looking
WHILE looking == 1 LIMIT 6
    TAP golden_pick
    READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO picked
    IF picked == 0
        READ_LUA (0) INTO looking
    IF picked == 1
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick_report
        LOG "target: (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)()"
        READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.cur == nil then return 0 end return ((tonumber(p.cur.uuid) or 0) == 0) and 1 or 0 end)() INTO needs_uuid
        IF needs_uuid == 1
            TAP golden_touch
            TAP golden_grab
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local ws = _G.__LW_GOLD_WS local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) _G.__LW_GOLD_WS = ws end local function _freshuuid(ws, p, t) if ws == nil or t == nil then return nil end local want = tostring(t.key or t.uuid or 0) local found = nil pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 2, ids, res) local e = res:GetEnumerator() while e:MoveNext() do local k = e.Current.Key if tostring(k) == want then found = k end end end) return found end if ws == nil then return 1 end local t = p.cur if t == nil then return 0 end return (_freshuuid(ws, p, t) ~= nil) and 1 or 0 end)() INTO target_live
        IF target_live == 1
            READ_LUA (0) INTO looking
        IF target_live == 0
            LOG "the client cannot name that zombie any more — dropping it and choosing again"
            TAP golden_drop_target
            READ_LUA (0) INTO picked
