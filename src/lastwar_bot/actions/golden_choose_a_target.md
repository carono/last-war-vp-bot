# Choose the next golden zombie and make sure it is real — one brick of the chain.
# ru: Выбрать следующего золотого зомби и убедиться, что он есть, — кирпич цепочки.
#
# The nearest target to where the squad is standing, out of the registry the scans keep;
# then the two checks that stop an order being wasted — the live uuid, and «is it still on
# a piece of map we have actually read».
#
# Leaves `picked` at 1 with a target armed, or 0. Runnable on its own (#1702): pressing it
# is a safe, read-only «what would the chain go for next».

TAP golden_pick
READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick_report
LOG "first choice: {pick_report}"
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO picked
READ_LUA (function() local p = DataCenter.__lw_gold or {} local n = math.floor(tonumber(p.since_refresh) or 0) local lim = math.floor(tonumber(DataCenter.__lw_gold_refresh_after) or 3) if lim <= 0 then return 0 end return (n >= lim) and 1 or 0 end)() INTO needs_refresh

# A STALE PICTURE IS PAID FOR ONLY WHEN IT HAS BEEN PROVEN STALE (#1702). The
# camera stands on the kills, so the ordinary scan above is a current picture
# nearly all the time — and the operator's own rule is that the expensive redraw
# is worth it only «если 2–5 монстров пропали». So the counter of PROVEN
# disappearances drives it: below the threshold nothing flies anywhere, and at it
# the ground is redrawn once at the lap height, read again, and the choice is
# made over the fresher queue.
#
# This replaced a flight to the chosen target and a re-pick after EVERY kill.
# That existed because the queue only ever grew and a partial map could hide a
# nearer zombie; the queue is reaped now, so what it holds is what the map last
# said, and re-flying per kill buys a redraw nobody asked for.
IF picked == 1
    IF needs_refresh == 1
        LOG "several targets in a row were gone — redrawing the ground before choosing"
        TAP golden_refresh
        READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
        WHILE refreshed == 0 LIMIT 12
            WAIT 1
            READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
        TAP golden_scan
        TAP golden_pick
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick_report
    LOG "target: {pick_report}"
    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.cur == nil then return 0 end return ((tonumber(p.cur.uuid) or 0) == 0) and 1 or 0 end)() INTO needs_uuid
    IF needs_uuid == 1
        TAP golden_touch
        TAP golden_grab
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local t = p.cur if t == nil then return 1 end local ws = _G.__LW_GOLD_WS local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) _G.__LW_GOLD_WS = ws end if ws == nil then return 1 end local want = tostring(t.key or t.uuid or 0) local there = false local ok = pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) if there then return 1 end if not ok then return 1 end local known = nil pcall(function() known = ws:HasPointInfo(t.pid) end) if known ~= true then return 1 end return 0 end)() INTO here
    IF here == 0
        LOG "that zombie is not on the map any more — dropping it and picking another"
        TAP golden_drop_target
        READ_LUA (0) INTO picked
