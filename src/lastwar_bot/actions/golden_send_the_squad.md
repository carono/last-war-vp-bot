# Send the squad at the armed target — the only brick that gives an order.
# ru: Отправить отряд на выбранную цель — единственный кирпич, который отдаёт приказ.
#
# The ride (when it is on and has not been fused off), the march itself, and the proof
# that an order became a march. Everything that can refuse in silence is handled here and
# nowhere else, so there is one place to look when a hunt stops moving.
#
# Runnable on its own (#1702) — it will send the squad at whatever `golden_choose_a_target`
# last armed, which is exactly what a person debugging the send wants.

ARGS approach = 0
ARGS march_wait = 200
ARGS miss_limit = 6
ARGS breather = 90
ARGS wave_wait = 240

# NOTHING TO SEND AT IS THE SAME KIND OF PAUSE AS A REFUSED SEND (#1702). The chooser
# comes back empty when every zombie it can reach has been killed — by us or by the
# neighbours — and the invasion puts more there within a couple of minutes. Ending the
# run on it is what left thousands of energy unspent all morning, so it is marked as a
# stall and answered by the same wait as a streak of refusals below.
IF picked == 0
    TAP golden_stall_mark

IF picked == 1
    # THE INVARIANT, AND EVERYTHING ELSE HERE RESTS ON IT (#1702): never give an order to
    # a squad the game says cannot take one. Both of the operator's worst complaints are
    # this rule being broken.
    #
    #  * «залипание на шахте» — the ride is a GATHER order and a squad that lands on a
    #    mine works it: measured live, the squad not free with the march's own clock 109
    #    minutes out. Every attack sent into that window was refused in silence and cost
    #    ten seconds to prove, over and over, for as long as the run lasted.
    #  * «меняет маршрут, когда уже идёт на зомби» — an order that WAS accepted but whose
    #    march the client had not listed yet read as a refusal, so the chain wrote the
    #    target off and ordered the squad somewhere else, re-routing a squad mid-walk.
    #
    # One read, and it is the client's own answer about our own formation. A squad that
    # cannot march is RECALLED rather than shouted at — the recall is the same press that
    # takes a squad off dirty ground, because from here the two are the same thing.
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local function _ownmarch(p) if p.formation == nil then return nil end local m = nil pcall(function() local P = LuaEntry.Player m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if m ~= nil then return m end if p.own_march ~= nil then pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.own_march) end) if m ~= nil then return m end end local want = math.floor(tonumber(p.squad) or -1) if want < 0 then return nil end pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local x = nil pcall(function() x = ms[i] end) if x ~= nil then local slot = nil pcall(function() slot = math.floor(tonumber(x.armyInfo.f4) or -1) end) if slot == want then m = x end end end end) return m end local function _landed(m, p) if m == nil then return false end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return false end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 and (due == nil or due <= 0) then return true end if st == 3 and p ~= nil and p.own_march ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) return u ~= nil and u == tostring(p.own_march) end return false end local function _stand(p) local m = _ownmarch(p) if m == nil then return 'nomarch' end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return 'banner' end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 then if due == nil or due <= 0 then return 'station' end return 'station+clock' end if st == 3 then if p.own_march == nil then return 'mine-notours' end local u = nil pcall(function() u = tostring(m.uuid) end) if u == tostring(p.own_march) then return 'mine' end return 'mine-notours' end return 'status' .. tostring(st) end local function _origin(p) if p.anchor ~= nil and _landed(_ownmarch(p), p) then return p.anchor, 'anchor' end if p.home ~= nil then return p.home, 'home' end return p.anchor, 'anchor' end if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (function(f) local st = math.floor(tonumber(f.state) or -1) if st ~= 0 then return false end local ok, idle = pcall(function() return f:IsFree() end) if ok and idle ~= nil then return (idle and true or false) end return true end)(v) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if n <= 0 then return -2 end if can then return 1 end if _landed(_ownmarch(p), p) then return 1 end return 0 end)() INTO squad_free
    IF squad_free == 0
        LOG "the squad cannot take an order where it stands — recalling it instead of sending orders nobody can carry out"
        TAP golden_unstick
        READ_LUA (0) INTO picked
    # …and «no army loaded» is NOT «busy» (#1702): a squad the client is holding no
    # soldiers for is standing at home doing nothing, and it answers the gate exactly like
    # a free one — the soldier count is what tells them apart. One question puts the
    # soldiers back; only if that fails is the order withheld.
    #
    # THE GATE ASKS `state` AND `IsFree()`, NEVER `canMarch` (#1702). The flag is
    # recomputed by the real dispatch render and by nothing else, so a headless session
    # read `canMarch = false` over a squad standing at home with a full army — and the
    # panel said «ОТРЯД ЗАНЯТ» about a squad the person could see was not.
    IF squad_free == -2
        LOG "the client is holding no army for the squad — asking for it before giving any order"
        CALL fill_empty_squads
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local function _ownmarch(p) if p.formation == nil then return nil end local m = nil pcall(function() local P = LuaEntry.Player m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if m ~= nil then return m end if p.own_march ~= nil then pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.own_march) end) if m ~= nil then return m end end local want = math.floor(tonumber(p.squad) or -1) if want < 0 then return nil end pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local x = nil pcall(function() x = ms[i] end) if x ~= nil then local slot = nil pcall(function() slot = math.floor(tonumber(x.armyInfo.f4) or -1) end) if slot == want then m = x end end end end) return m end local function _landed(m, p) if m == nil then return false end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return false end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 and (due == nil or due <= 0) then return true end if st == 3 and p ~= nil and p.own_march ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) return u ~= nil and u == tostring(p.own_march) end return false end local function _stand(p) local m = _ownmarch(p) if m == nil then return 'nomarch' end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return 'banner' end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 then if due == nil or due <= 0 then return 'station' end return 'station+clock' end if st == 3 then if p.own_march == nil then return 'mine-notours' end local u = nil pcall(function() u = tostring(m.uuid) end) if u == tostring(p.own_march) then return 'mine' end return 'mine-notours' end return 'status' .. tostring(st) end local function _origin(p) if p.anchor ~= nil and _landed(_ownmarch(p), p) then return p.anchor, 'anchor' end if p.home ~= nil then return p.home, 'home' end return p.anchor, 'anchor' end if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (function(f) local st = math.floor(tonumber(f.state) or -1) if st ~= 0 then return false end local ok, idle = pcall(function() return f:IsFree() end) if ok and idle ~= nil then return (idle and true or false) end return true end)(v) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if n <= 0 then return -2 end if can then return 1 end if _landed(_ownmarch(p), p) then return 1 end return 0 end)() INTO squad_free
    IF squad_free == -2
        LOG "the squad still holds no army — no order is given"
        READ_LUA (0) INTO picked

IF picked == 1
    # THE RIDE. A gather order travels 2.5x faster than an attack one, so a long
    # haul is ridden to a mine beside the zombie and only the last few tiles are
    # paid at attack speed. Taken only when the arithmetic wins — a short hop
    # loses more to the extra stop than it saves.
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

    IF approach == 1
        # THE RIDE, AND ONLY THE RIDE, STILL FLIES THE CAMERA (#1702). The mine
        # hunt below asks `HasPointInfo` about the tiles around the target, and
        # the client can only answer for a district it holds — so this branch
        # fetches it. The chain itself does not: the pick works off the reaped
        # registry, and the flight used to be paid on every kill for a re-pick
        # that the reaping has made unnecessary.
        # THE SUMS FIRST, THE CAMERA ONLY IF THE SUMS ASK FOR IT (#1702). The planner
        # bails on «short» and «no-gain» without touching the map, so asking it first
        # costs a fifth of a second and answers most laps. It is only when it gets as far
        # as hunting for a mine and finds none — «no-mine», which on an unloaded corner of
        # the map means «nobody has shown me» — that the flight is worth its three
        # seconds. Measured: the flight ran on all twelve laps of one run, on hops of four
        # and six tiles the planner then called short.
        TAP golden_approach_arm
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (tostring(p.why or '') == 'no-mine') and 1 or 0 end)() INTO needs_mine_district
        IF needs_mine_district == 1
            # The district is already fetched above when the target was far; this is the
            # near-target case, where the mine hunt is the only thing that needs it.
            TAP golden_scan
            TAP golden_approach_arm
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (p.approach ~= nil) and 1 or 0 end)() INTO riding
        IF riding == 1
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return 'why=' .. tostring(p.why or '-') .. ' direct=' .. tostring(math.floor(tonumber(p.direct_sec) or 0)) .. ' via=' .. tostring(math.floor(tonumber(p.approach_sec) or 0)) .. ' rode=' .. tostring(math.floor(tonumber(p.rode) or 0)) .. ' atk=' .. string.format('%.3f', tonumber(p.speed_atk) or 0) .. ' col=' .. string.format('%.3f', tonumber(p.speed_col) or 0) end)() INTO ride_report
            LOG "riding to a mine beside the target — {ride_report}"
            TAP golden_ride
            TAP golden_eta
            # The march's OWN clock, never the squad's state: a squad
            # that has landed at a mine is gathering, and it goes on
            # reading «out» for as long as it works there.
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived
            WHILE arrived == 0 LIMIT {march_wait}
                WAIT 3
                # …AND THE RIDE IS ABANDONED THE MOMENT ITS ZOMBIE IS GONE (#1702). The
                # operator watched exactly this: the squad set off for a mine beside the
                # target, somebody else killed the target while it travelled, and the
                # squad arrived, started gathering and took no orders for the rest of the
                # day. A ride is only ever worth taking for a zombie that is still there,
                # so the tile is asked about on every beat and the recall goes the moment
                # it comes up empty — which costs the ride and saves the run.
                TAP golden_scan
                READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local t = p.hit if t == nil then return 1 end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return 1 end local want = tostring(t.key or t.uuid or 0) local there = false pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) return there and 0 or 1 end)() INTO target_gone
                IF target_gone == 1
                    LOG "the zombie died while we were riding to it — recalling rather than landing on the mine"
                    TAP golden_no_ride
                    TAP golden_unstick
                    READ_LUA (0) INTO picked
                    READ_LUA (1) INTO arrived
                READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived
            # …AND THEN THE FUSE (#1702). A ride that lands on a mine and starts
            # GATHERING has parked the squad — measured live, 109 minutes of a squad
            # that is not free, during which every attack is refused in silence.
            # One such ride per run is a mistake; two would be a policy. So the
            # first one switches the ride off for the rest of the run, recalls the
            # squad, and the hunt carries on at attack speed. The person's own
            # setting is untouched — this is a fuse inside one run.
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local function _ownmarch(p) if p.formation == nil then return nil end local m = nil pcall(function() local P = LuaEntry.Player m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if m ~= nil then return m end if p.own_march ~= nil then pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.own_march) end) if m ~= nil then return m end end local want = math.floor(tonumber(p.squad) or -1) if want < 0 then return nil end pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local x = nil pcall(function() x = ms[i] end) if x ~= nil then local slot = nil pcall(function() slot = math.floor(tonumber(x.armyInfo.f4) or -1) end) if slot == want then m = x end end end end) return m end local function _landed(m, p) if m == nil then return false end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return false end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 and (due == nil or due <= 0) then return true end if st == 3 and p ~= nil and p.own_march ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) return u ~= nil and u == tostring(p.own_march) end return false end local function _stand(p) local m = _ownmarch(p) if m == nil then return 'nomarch' end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return 'banner' end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 then if due == nil or due <= 0 then return 'station' end return 'station+clock' end if st == 3 then if p.own_march == nil then return 'mine-notours' end local u = nil pcall(function() u = tostring(m.uuid) end) if u == tostring(p.own_march) then return 'mine' end return 'mine-notours' end return 'status' .. tostring(st) end local function _origin(p) if p.anchor ~= nil and _landed(_ownmarch(p), p) then return p.anchor, 'anchor' end if p.home ~= nil then return p.home, 'home' end return p.anchor, 'anchor' end if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (function(f) local st = math.floor(tonumber(f.state) or -1) if st ~= 0 then return false end local ok, idle = pcall(function() return f:IsFree() end) if ok and idle ~= nil then return (idle and true or false) end return true end)(v) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if n <= 0 then return -2 end if can then return 1 end if _landed(_ownmarch(p), p) then return 1 end return 0 end)() INTO squad_free
            IF squad_free == 0
                LOG "the ride ended in a gather — the squad is working the mine and takes no orders; recalling it and hunting on foot for the rest of this run"
                TAP golden_no_ride
                TAP golden_unstick
                READ_LUA (0) INTO picked
    # The last march of the run is the one that brings the squad home; every one
    # before it deliberately leaves it standing where it killed.

IF picked == 1
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local left = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = math.floor(tonumber(p.cost) or 10) if cost <= 0 then cost = 10 end if left < cost * 2 then return 1 end local lim = math.floor(tonumber(p.limit) or 0) if lim > 0 and (tonumber(p.attacks) or 0) + 1 >= lim then return 1 end return ((function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() <= 1) and 1 or 0 end)() INTO last_one
    IF last_one == 1
        LUA DataCenter.__lw_gold_back = 1
        TAP golden_home
    ELSE
        TAP golden_send

    # THE PROOF THAT THE ATTACK IS UNDER WAY IS A MARCH OF OURS THAT WAS NOT
    # THERE A MOMENT AGO (#1702) — the operator's own model, and a fact about the
    # order rather than about what was paid for it. The purse decided this until
    # now, and it was wrong twice: the server does not always charge the price it
    # quotes (10 quoted, 8 taken, live), and the purse does not only go down — an
    # energy refill mid-chain made three marches that had all gone out look like
    # sends nobody received.
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local function _ownmarch(p) if p.formation == nil then return nil end local m = nil pcall(function() local P = LuaEntry.Player m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if m ~= nil then return m end if p.own_march ~= nil then pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.own_march) end) if m ~= nil then return m end end local want = math.floor(tonumber(p.squad) or -1) if want < 0 then return nil end pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local x = nil pcall(function() x = ms[i] end) if x ~= nil then local slot = nil pcall(function() slot = math.floor(tonumber(x.armyInfo.f4) or -1) end) if slot == want then m = x end end end end) return m end local function _landed(m, p) if m == nil then return false end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return false end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 and (due == nil or due <= 0) then return true end if st == 3 and p ~= nil and p.own_march ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) return u ~= nil and u == tostring(p.own_march) end return false end local function _stand(p) local m = _ownmarch(p) if m == nil then return 'nomarch' end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return 'banner' end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 then if due == nil or due <= 0 then return 'station' end return 'station+clock' end if st == 3 then if p.own_march == nil then return 'mine-notours' end local u = nil pcall(function() u = tostring(m.uuid) end) if u == tostring(p.own_march) then return 'mine' end return 'mine-notours' end return 'status' .. tostring(st) end local function _origin(p) if p.anchor ~= nil and _landed(_ownmarch(p), p) then return p.anchor, 'anchor' end if p.home ~= nil then return p.home, 'home' end return p.anchor, 'anchor' end if p.pending == nil then return 1 end if math.floor(tonumber(p.redeploy) or 0) == 1 then local m = _ownmarch(p) if m == nil then return 0 end local tp = nil pcall(function() tp = tostring(m.targetPos) end) if tp ~= nil and tp == tostring(p.pending.pid) then return 1 end return 0 end local seen = p.march_before or {} local mine = nil pcall(function() local P = LuaEntry.Player mine = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if mine ~= nil then local u, team = nil, '0' pcall(function() u = tostring(mine.uuid) end) pcall(function() team = tostring(mine.teamUuid) end) if u ~= nil and not seen[u] and (team == '0' or team == 'nil') then p.own_march = u DataCenter.__lw_gold = p return 1 end end local busy = false pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then busy = not (function(f) local st = math.floor(tonumber(f.state) or -1) if st ~= 0 then return false end local ok, idle = pcall(function() return f:IsFree() end) if ok and idle ~= nil then return (idle and true or false) end return true end)(v) end end end) return busy and 1 or 0 end)() INTO launched
    # 0.4 SECONDS, TWENTY-FIVE TIMES — the same ten seconds of patience, watched two and
    # a half times as closely (#1702). This poll is on the hot path: it is the last thing
    # between an order and the chain moving on, and every beat of it is dead time on a
    # send that was accepted at once. Nothing here is a timeout being shortened.
    # SIX SECONDS, NOT TEN (#1702). The proof is instant when the order was taken — the
    # squad goes busy the moment the game accepts it — so the whole of this poll is time
    # spent on orders that were REFUSED. Live, half the sends of a run were refusals at
    # zombies somebody else had already killed, and each cost the full ten seconds. Six is
    # still far longer than the server takes to answer; what it is not is a patience that
    # only ever pays out on failure.
    WHILE launched == 0 LIMIT 15
        WAIT 0.4
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local function _ownmarch(p) if p.formation == nil then return nil end local m = nil pcall(function() local P = LuaEntry.Player m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if m ~= nil then return m end if p.own_march ~= nil then pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.own_march) end) if m ~= nil then return m end end local want = math.floor(tonumber(p.squad) or -1) if want < 0 then return nil end pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local x = nil pcall(function() x = ms[i] end) if x ~= nil then local slot = nil pcall(function() slot = math.floor(tonumber(x.armyInfo.f4) or -1) end) if slot == want then m = x end end end end) return m end local function _landed(m, p) if m == nil then return false end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return false end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 and (due == nil or due <= 0) then return true end if st == 3 and p ~= nil and p.own_march ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) return u ~= nil and u == tostring(p.own_march) end return false end local function _stand(p) local m = _ownmarch(p) if m == nil then return 'nomarch' end local team = nil pcall(function() team = tostring(m.teamUuid) end) if team ~= nil and team ~= '0' and team ~= 'nil' then return 'banner' end local st, due = nil, nil pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) pcall(function() due = tonumber(m.endTime) end) if st == 0 then if due == nil or due <= 0 then return 'station' end return 'station+clock' end if st == 3 then if p.own_march == nil then return 'mine-notours' end local u = nil pcall(function() u = tostring(m.uuid) end) if u == tostring(p.own_march) then return 'mine' end return 'mine-notours' end return 'status' .. tostring(st) end local function _origin(p) if p.anchor ~= nil and _landed(_ownmarch(p), p) then return p.anchor, 'anchor' end if p.home ~= nil then return p.home, 'home' end return p.anchor, 'anchor' end if p.pending == nil then return 1 end if math.floor(tonumber(p.redeploy) or 0) == 1 then local m = _ownmarch(p) if m == nil then return 0 end local tp = nil pcall(function() tp = tostring(m.targetPos) end) if tp ~= nil and tp == tostring(p.pending.pid) then return 1 end return 0 end local seen = p.march_before or {} local mine = nil pcall(function() local P = LuaEntry.Player mine = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if mine ~= nil then local u, team = nil, '0' pcall(function() u = tostring(mine.uuid) end) pcall(function() team = tostring(mine.teamUuid) end) if u ~= nil and not seen[u] and (team == '0' or team == 'nil') then p.own_march = u DataCenter.__lw_gold = p return 1 end end local busy = false pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then busy = not (function(f) local st = math.floor(tonumber(f.state) or -1) if st ~= 0 then return false end local ok, idle = pcall(function() return f:IsFree() end) if ok and idle ~= nil then return (idle and true or false) end return true end)(v) end end end) return busy and 1 or 0 end)() INTO launched

    IF launched == 0
        # A ZOMBIE SOMEBODY ELSE KILLED FIRST, nearly always: the client's list is a
        # snapshot, and the server refuses an order at a monster that is not there. That
        # is worth another target, not the end of the run — but a client that has gone
        # deaf refuses everything, so a handful in a row stop it.
        #
        # THERE IS NO «IS THE SQUAD STUCK» BRANCH HERE ANY MORE (#1702), and its absence
        # is the fix rather than a simplification. It used to run AFTER a send had spent
        # ten seconds failing, and it read «cannot march» as «dirty ground». Two
        # things are wrong with that. A squad that cannot march is now caught BEFORE the
        # send by the gate at the top of this brick, so ten seconds are never spent on a
        # doomed order; and a squad that has stopped being free after a send is what an
        # ACCEPTED order looks like, which is why the launch proof reads it as success.
        # Asking the same
        # question in two places with two opposite meanings is how a chain ends up
        # re-routing a squad that was already walking.
        LOG "the send never became a march — that zombie is gone, or this squad has forgotten its army; trying the next one"
        TAP golden_miss
        # A SQUAD THE CLIENT HAS FORGOTTEN THE ARMY OF reads zero soldiers, and the
        # server refuses a march for an empty formation — silently, exactly like a dead
        # target (#1285, #1702). One question puts them back, and it costs a third of a
        # second.
        CALL fill_empty_squads
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return math.floor(tonumber(p.misses) or 0) end)() INTO misses
        IF misses > {miss_limit}
            # …and the chain decides what that means (#1702). It used to end the run
            # here, which over one morning is what ended nearly every one of them with
            # thousands of energy unspent. A streak of refusals is the ground being
            # farmed out; the caller waits and looks again, and only gives up when it
            # has run out of patience it was given.
            # A STREAK OF REFUSALS IS A PAUSE, NOT AN ENDING (#1702). Measured over one
            # morning, this line ended nearly every run of the day — the best of them
            # after 19 kills — with seven and a half THOUSAND energy still in the purse.
            # What it means is that the corner the squad is standing in has been farmed
            # out, which is a fact about the map two minutes from now rather than about
            # the client. So the hunt waits, asks the client about the district it is
            # standing in, and goes round again; the tiles it has already cleared stay
            # used, so a pause never walks it back round its own kills.
            #
            # It is BOUNDED, and that bound is what keeps the old ending honest: a
            # client that has genuinely gone deaf refuses everything for ever, and a
            # hunt that waits for ever in front of one is the bug this task began with.
            LOG "several sends in a row went nowhere — the ground here is farmed out"
            TAP golden_stall_mark
    ELSE
        # The tally moves HERE and nowhere else. What the attack COST is read off
        # the purse for the books, and cannot decide anything.
        TAP golden_confirm
        # …and when this march is due to land, so the next lap knows what to
        # wait for.
        TAP golden_eta
        # No scan here: the lap below re-asks the client after it has looked at the
        # origin of the next pick, and asking twice cost most of a second per kill
        # for a list that is thrown away and rebuilt anyway (#1702).

# THE PAUSE, IN ONE PLACE, FOR BOTH WAYS A LAP CAN COME UP EMPTY (#1702) — no zombie the
# chooser could reach, or a streak of orders the server refused. Measured over one
# morning, those two lines ended nearly every run of the day, the best of them after 19
# kills, with seven and a half THOUSAND energy still in the purse. Both mean the corner
# the squad is standing in has been farmed out, which is a fact about the map two minutes
# from now rather than about the client — so the hunt waits, asks the client about the
# district it is standing in, and goes round again.
#
# The tiles already cleared stay used, so a pause never walks the hunt back round its own
# kills. And it is BOUNDED: a client that has genuinely gone deaf refuses everything for
# ever, and a hunt that waits for ever in front of one is the bug this task began with.
READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (p.stalled == 1) and 1 or 0 end)() INTO stalled
IF stalled == 1
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local lim = math.floor(tonumber(p.breather_limit) or 0) if lim <= 0 then return 0 end local used = math.floor(tonumber(p.breathers) or 0) local left = lim - used if left < 0 then left = 0 end return left end)() INTO breathers_left
    IF breathers_left == 0
        LOG "nothing to attack here and no pauses left — stopping"
        READ_LUA (0) INTO go
    IF breathers_left > 0
        LOG "nothing to attack here just now — waiting {breather}s and looking again ({breathers_left} pause(s) left)"
        TAP golden_breathe
        # THE CAMERA GOES BACK TO THE SQUAD FIRST, AND THAT IS THE WHOLE BUG (#1702).
        # `GetMonsterListInArea` answers out of the tiles the CLIENT HOLDS, and what it
        # holds is what the camera has been shown. After a lap of the map the camera is
        # parked in whatever far corner the sweep ended in — so the reading below said
        # «no golden zombie anywhere» while the operator watched dozens of them go past
        # on screen. Measured: camera at 535,442 and the client naming 62 of them, the
        # same client that had answered 0 with the camera left out at the edge.
        # …taking what is here BEFORE the camera moves, which is the rule the whole
        # chain follows: the client keeps what it has been shown, and a move evicts it.
        TAP golden_scan
        TAP golden_look_from
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.looked_moved) or 0) == 1) and 1 or 0 end)() INTO looked_moved
        IF looked_moved == 1
            WAIT 1
        # IS THERE ANYTHING ON THE MAP AT ALL? (#1702) The registry is what earlier
        # sweeps saw; this asks the client about the ground it is holding right now.
        # Measured live: 83 rows queued and the client naming ZERO of them, because the
        # invasion wave was not up and every row was a ghost. A lap then spent its twelve
        # picks proving that one at a time — which from the outside is a camera flying
        # about the map and nothing else happening, and is exactly what the operator saw.
        TAP golden_scan
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws == nil then return -1 end local n = 0 pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(ws.CurTilePos, math.floor(tonumber(p.radius) or 2000), ids, res) local e = res:GetEnumerator() while e:MoveNext() do n = n + 1 end end) return n end)() INTO seen_now
        IF seen_now == 0
            LOG "the client can see no golden zombie anywhere — the invasion wave is not up; forgetting the old list and waiting {wave_wait}s"
            TAP golden_forget_queue
            WAIT {wave_wait}
        IF seen_now > 0
            WAIT {breather}
            TAP golden_scan
        # …AND IF THE DROUGHT HAS GONE ON, WALK THE MAP AGAIN (#1702). The queue is what
        # one sweep saw, and a sweep goes stale: live, after three empty pauses the leash
        # went out to 700 tiles, found 139 rows in the invasion's own corner and dropped
        # every one of them as a ghost — they had been killed while the chain was hunting
        # beside the base. A lap of the map is eight seconds and it is the only thing that
        # can refill a corner nobody is standing in. Not per kill, and not per pause: only
        # while the ground the squad can reach has stayed empty.
        READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.dry) or 0) >= 3) and 1 or 0 end)() INTO drought
        IF drought == 1
            CALL scan_map
