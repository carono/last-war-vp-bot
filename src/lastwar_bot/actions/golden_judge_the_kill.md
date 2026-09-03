# Judge whether the zombie we hit is gone — one brick of the golden-zombie chain.
# ru: Решить, исчез ли зомби, по которому били, — кирпич цепочки золотых зомби.
#
# Reads the map where the squad is standing and asks one question: is the target we sent
# an order at still there? Gone is the kill. Still standing is somebody else's kill or a
# fight still running, and costs the chain that one target rather than the run.
#
# Runnable on its own (#1702). Sends nothing, marches nothing.

# What is loaded right now, before the camera moves off it (#1702) …
TAP golden_scan
# … and then where the next pick is measured from — the last kill, or the base
# before the first one — so that district is loaded before it is asked about.
TAP golden_look_from
# …and the settle only when it really flew: a kill two tiles from the last one is
# inside the district the client is already holding (#1702).
READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.looked_moved) or 0) == 1) and 1 or 0 end)() INTO looked_moved
IF looked_moved == 1
    # 0.8, not 1.5 (#1702). This settle exists so the client has drawn the district the
    # camera flew to, and it is only paid when the origin really moved — measured, that
    # is a minority of laps. The whole gap between «the march landed» and «the next order
    # is out» was nine seconds and is being spent down one reading at a time; this is
    # three quarters of a second of it, and a district that is not ready in 0.8 s is not
    # ready in 1.5 either, because the reaping keeps the row rather than dropping it.
    WAIT 0.8
TAP golden_scan
# THE ATTACK IS OVER WHEN THE ZOMBIE IS GONE (#1702). The march is the order; the
# monster vanishing off the map is the fight. A zombie somebody else killed first
# answers the same way, which is right — the question is whether it is still there to
# be fought — and one that outlives the wait costs the chain nothing but the wait.
READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local t = (p.judgeq or {})[1] or p.judge if t == nil then return 1 end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return 1 end local want = tostring(t.key or t.uuid or 0) local there = false pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) return there and 0 or 1 end)() INTO gone
# THE FIGHT IS MINUTES, AND THIS WAIT WAS SIXTEEN SECONDS (#1702). The operator watched
# the hunt and said it «прыгает с монстра на монстра, не дожидается, когда атаку
# завершает» — and this loop is where that happened: the squad was still walking to the
# zombie when the wait ran out, the chain judged «still standing», dropped the target and
# chose another one, ordering over the top of a fight already paid for.
#
# The zombie leaving the map is the honest end of an attack, so this is the wait that
# matters and it is given the march's own budget. A monster that outlives even that costs
# the wait and nothing else — the target is dropped exactly as before.
WHILE gone == 0 LIMIT 90
    WAIT 1
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local t = (p.judgeq or {})[1] or p.judge if t == nil then return 1 end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return 1 end local want = tostring(t.key or t.uuid or 0) local there = false pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) return there and 0 or 1 end)() INTO gone
IF gone == 1
    TAP golden_kill
ELSE
    LOG "the zombie is still standing — another player's kill, or a fight still running; moving on"
    TAP golden_kill_drop
