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
READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local n = math.floor(tonumber(p.since_refresh) or 0) local lim = math.floor(tonumber(DataCenter.__lw_gold_refresh_after) or 3) if lim <= 0 then return 0 end return (n >= lim) and 1 or 0 end)() INTO needs_refresh
IF needs_refresh == 1
    LOG "several targets in a row were gone — redrawing the ground before choosing"
    TAP golden_refresh
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
    # A THIRD OF A SECOND, NOT A WHOLE ONE (#2390). The refresh is the game answering a
    # question it was just asked, and it lands in well under a second — but the beat waiting
    # for it was one, so the opening of every run paid half a second per beat for nothing.
    # Measured live: five beats, thirteen seconds, and the answer had been sitting there.
    # The ceiling is unchanged — the LIMIT is raised in the same proportion as the beat.
    WHILE refreshed == 0 LIMIT 36
        WAIT 0.3
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
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
# TWELVE TRIES, NOT SIX (#1702). Live, a lap dropped six dead rows and ended having
# sent nothing — the corner had been farmed out and the next live zombie was simply
# further down the queue. A try is a pick and one two-tile question, about half a
# second; a lap that ends without an order costs the whole lap.
WHILE looking == 1 LIMIT 12
    TAP golden_pick
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (p.cur ~= nil) and 1 or 0 end)() INTO picked
    IF picked == 0
        READ_LUA (0) INTO looking
    IF picked == 1
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local function _ownmarch(p) if p.formation == nil then return nil end local m = nil pcall(function() local P = LuaEntry.Player m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if m ~= nil then return m end if p.own_march ~= nil then pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.own_march) end) if m ~= nil then return m end end local want = math.floor(tonumber(p.squad) or -1) if want < 0 then return nil end pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local x = nil pcall(function() x = ms[i] end) if x ~= nil then local slot = nil pcall(function() slot = math.floor(tonumber(x.armyInfo.f4) or -1) end) if slot == want then m = x end end end end) return m end local function _landed(m, p) if m == nil then return false end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return false end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 and (due == nil or due <= 0) then return true end if st == 3 and p ~= nil and p.own_march ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) return u ~= nil and u == tostring(p.own_march) end return false end local function _reaim(m, p) if m == nil or p == nil then return nil end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return nil end local u = nil pcall(function() u = tostring(m.uuid) end) if u == nil or u == 'nil' then return nil end if p.own_march ~= nil and u == tostring(p.own_march) then return m.uuid end if _landed(m, p) then return m.uuid end return nil end local function _stand(p) local m = _ownmarch(p) if m == nil then return 'nomarch' end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return 'banner' end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 then if due == nil or due <= 0 then return 'station' end return 'station+clock' end if st == 3 then if p.own_march == nil then return 'mine-notours' end local u = nil pcall(function() u = tostring(m.uuid) end) if u == tostring(p.own_march) then return 'mine' end return 'mine-notours' end return 'status' .. tostring(st) end local function _origin(p) if p.anchor ~= nil then local m = _ownmarch(p) if _landed(m, p) then return p.anchor, 'anchor' end if m ~= nil then local team = nil pcall(function() team = tostring(m.teamUuid) end) if team == nil or team == '0' or team == 'nil' then return p.anchor, 'flying' end end end if p.home ~= nil then return p.home, 'home' end return p.anchor, 'anchor' end local c = p.cur if c == nil then return 'none' end local o = _origin(p) local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' stand=' .. _stand(p) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick_report
        LOG "target: {pick_report}"
        # …AND THE DISTRICT IS LOOKED AT HERE, WHILE THE SQUAD IS STILL FLYING (#2390). It
        # used to be the send's first act, which put a two-second camera flight between «the
        # march has landed» and «the next order is away». Nothing about it needs the squad to
        # be standing still — the camera is the panel's, not the army's.
        # THE CLIENT ONLY ANSWERS FOR GROUND IT IS HOLDING, AND THAT IS WHY A FAR TARGET
        # LOOKED DEAD (#1702). `GetMonsterListInArea` — the liveness check the send makes
        # before it orders anything — reads the tiles the camera has been shown. With the
        # camera back on the squad, every candidate in the invasion's own corner answered
        # «not there»: live, 144 queued rows, picks at 523 to 526 tiles, every one written
        # off as a ghost, and the operator meanwhile watching dozens of them go past on the
        # sweep. They were there; we were asking about ground the client had evicted.
        #
        # So a candidate further than forty tiles from the camera is LOOKED AT first, which
        # is what a person does before sending a march. One flight per far kill, none at all
        # for the near ones the chain is built around.
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 0 end local ws = DataCenter.__lw_gold_ws local cx, cy = nil, nil pcall(function() cx, cy = ws.CurTilePos.x, ws.CurTilePos.y end) if cx == nil then return 1 end local dx, dy = (c.x - cx), (c.y - cy) return (math.sqrt(dx * dx + dy * dy) > 40) and 1 or 0 end)() INTO needs_district
        IF needs_district == 1
            TAP golden_look
            WAIT 1
            TAP golden_scan
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end if p.cur == nil then return 0 end return ((tonumber(p.cur.uuid) or 0) == 0) and 1 or 0 end)() INTO needs_uuid
        IF needs_uuid == 1
            TAP golden_touch
            TAP golden_grab
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end local function _freshuuid(ws, p, t) if ws == nil or t == nil then return nil end local want = tostring(t.key or t.uuid or 0) local found = nil pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 2, ids, res) local e = res:GetEnumerator() while e:MoveNext() do local k = e.Current.Key if tostring(k) == want then found = k end end end) return found end if ws == nil then return 1 end local t0 = p.cur if t0 ~= nil then local cx, cy = nil, nil pcall(function() cx, cy = ws.CurTilePos.x, ws.CurTilePos.y end) if cx ~= nil then local dx, dy = (t0.x - cx), (t0.y - cy) if math.sqrt(dx * dx + dy * dy) > 40 then return 1 end end end local t = p.cur if t == nil then return 0 end return (_freshuuid(ws, p, t) ~= nil) and 1 or 0 end)() INTO target_live
        IF target_live == 1
            READ_LUA (0) INTO looking
        IF target_live == 0
            LOG "the client cannot name that zombie any more — dropping it and choosing again"
            TAP golden_drop_target
            READ_LUA (0) INTO picked
            # …AND IF THE GROUND HAS GONE BAD, REDRAW IT HERE RATHER THAN NEXT LAP (#1702).
            # Live, one lap dropped six stale rows and sent nothing at all: the corner the
            # chain was standing in had been farmed out while it was walking, and going
            # round again would only have found the next six. Each drop feeds the same
            # counter the reaping does, so this is the ordinary threshold — asked again
            # inside the loop, where it can still save the lap.
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local n = math.floor(tonumber(p.since_refresh) or 0) local lim = math.floor(tonumber(DataCenter.__lw_gold_refresh_after) or 3) if lim <= 0 then return 0 end return (n >= lim) and 1 or 0 end)() INTO needs_refresh
            IF needs_refresh == 1
                LOG "the ground here is stale — redrawing it before choosing again"
                TAP golden_refresh
                READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
                # A THIRD OF A SECOND, NOT A WHOLE ONE (#2390). The refresh is the game answering a
                # question it was just asked, and it lands in well under a second — but the beat waiting
                # for it was one, so the opening of every run paid half a second per beat for nothing.
                # Measured live: five beats, thirteen seconds, and the answer had been sitting there.
                # The ceiling is unchanged — the LIMIT is raised in the same proportion as the beat.
                WHILE refreshed == 0 LIMIT 36
                    WAIT 0.3
                    READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
                TAP golden_scan
