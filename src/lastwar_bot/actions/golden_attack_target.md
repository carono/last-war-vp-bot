# Attack the fixed zombie with the panel's squad. ONE call to the game, then the answer.
# ru: Атаковать зафиксированную цель отрядом из панели. Один вызов игры — и ответ.
#
# «Всё равно долго, ещё уменьши» (#1702). What is left of this press is: read the link,
# and one call that resolves the squad, forgets the previous order, re-reads the target's
# uuid and schedules the march — with nothing in between for the world to change in.
#
# THE PROOF IS NOT WAITED FOR HERE, and that is the deliberate trade. Waiting for the
# client to show the march is five seconds of a person looking at a button that has
# already done its work. So the press answers at once and the panel checks a few seconds
# later (`golden_verify_order.md`): if the server never confirmed it, the phantom march
# is recalled and the row of buttons says so. The squad is brought back either way — the
# person simply learns about it a moment after, instead of waiting for the good news.
#
# «ОТРЯД ЗАНЯТ, НО ЭТО НЕ ТАК» (#1702). The gate below asks the game whether the squad
# may take an order, and for a while it asked the wrong field. `canMarch` is recomputed
# by the real dispatch window and by nothing else, so a headless session reads whatever
# it was left at — measured live, one press apart, on a squad standing at home with a
# full army:
#
#     squad=2 state=0 free=1 soldiers=2631 status=- march=- team=0    (read_squad_state)
#     squad2 state=0 canMarch=false soldiers=2631                     (the old gate)
#
# It asks `state == 0` together with the game's own `IsFree()` now — which is what
# `create_rally.md`, `read_squad_state.md` and the rally limits have always asked.

ARGS squad = 2

WAIT client == ready WITHIN 20s
LUA DataCenter.__lw_gold_squad = {squad}
# WHAT IS ABOUT TO GO, PRINTED BEFORE IT GOES (#1702). It used to be read after the
# send, and the send is the moment the run stops holding a target — live, the line came
# out as «target=none» about an order that had just left correctly.
READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local c = p.cur local where = 'none' if c ~= nil then local srv = math.floor(tonumber(c.server or p.server) or 0) where = '#' .. tostring(srv) .. ' X:' .. tostring(math.floor(tonumber(c.x) or 0)) .. ' Y:' .. tostring(math.floor(tonumber(c.y) or 0)) .. ' pid=' .. tostring(c.pid) end return 'squad=' .. tostring(p.squad) .. ' formation=' .. tostring(p.formation) .. ' soldiers=' .. tostring(math.floor(tonumber(p.soldiers) or 0)) .. ' target=' .. where .. ' call=SendCreateMarchMessage/ATTACK_MONSTER' end)() INTO order
LOG "sending: {order}"
READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end local function _freshuuid(ws, p, t) if ws == nil or t == nil then return nil end local want = tostring(t.key or t.uuid or 0) local found = nil pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 2, ids, res) local e = res:GetEnumerator() while e:MoveNext() do local k = e.Current.Key if tostring(k) == want then found = k end end end) return found end p.squad = math.floor(tonumber(DataCenter.__lw_gold_squad) or p.squad or 1) p.formation = nil p.soldiers = 0 local can = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == p.squad then p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) can = (function(f) local st = math.floor(tonumber(f.state) or -1) if st ~= 0 then return false end local ok, idle = pcall(function() return f:IsFree() end) if ok and idle ~= nil then return (idle and true or false) end return true end)(v) end end end) p.pending = nil p.hit = nil p.judge = nil p.judgeq = {} p.march_uuid = nil p.misses = 0 if p.cur ~= nil and p.used ~= nil then p.used[tostring(p.cur.pid)] = nil end DataCenter.__lw_gold = p if p.formation == nil then return -1 end if p.cur == nil then return -3 end if math.floor(tonumber(p.soldiers) or 0) <= 0 then return -2 end if not can then return 0 end local t = p.cur local uuid = _freshuuid(ws, p, t) if uuid == nil then local keep = {} for _, q in ipairs(p.targets or {}) do if tostring(q.pid) ~= tostring(t.pid) then keep[#keep + 1] = q end end p.targets = keep p.cur = nil DataCenter.__lw_gold = p return -4 end local srv = math.floor(tonumber(t.server or p.server) or 0) local kind = MarchTargetType.ATTACK_MONSTER if p.server ~= nil and srv ~= 0 and srv ~= p.server then kind = MarchTargetType.CROSS_ATTACK_MONSTER end local f, pid = p.formation, t.pid p.march_before = {} pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil then p.march_before[u] = true end end end end) p.pending = {pid = pid, uuid = uuid, key = tostring(uuid), x = t.x, y = t.y} p.hit = p.pending p.anchor = {x = t.x, y = t.y, pid = t.pid} p.last_sent = {x = t.x, y = t.y, pid = t.pid} p.attacks = p.attacks or 0 DataCenter.__lw_gold = p TimerManager:GetInstance():DelayInvoke(function() pcall(function() MarchUtil.SendCreateMarchMessage(f, kind, pid, uuid, 1, 1, false, srv, nil) end) end, 0.1) return 1 end)() INTO sent

IF sent == -1
    LOG "there is no such squad on this account — nothing was sent"
    STOP "no squad"
IF sent == -3
    LOG "no zombie is fixed — press «найти ближайшего» first"
    STOP "nothing chosen"
IF sent == -4
    LOG "that zombie is gone — the client cannot name it any more, so nothing was sent"
    STOP "target gone"
IF sent == -2
    # …AND THEN TRY AGAIN IN THE SAME PRESS (#1702). «No army» is the client not having
    # fetched the squad's soldiers yet, which one question cures — and telling a person
    # to press the button a second time for that is exactly the «работает через раз» this
    # whole day has been about. Ask, and send.
    LOG "the client was holding no army for this squad — asking for it and sending"
    CALL fill_empty_squads
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end local function _freshuuid(ws, p, t) if ws == nil or t == nil then return nil end local want = tostring(t.key or t.uuid or 0) local found = nil pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 2, ids, res) local e = res:GetEnumerator() while e:MoveNext() do local k = e.Current.Key if tostring(k) == want then found = k end end end) return found end p.squad = math.floor(tonumber(DataCenter.__lw_gold_squad) or p.squad or 1) p.formation = nil p.soldiers = 0 local can = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == p.squad then p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) can = (function(f) local st = math.floor(tonumber(f.state) or -1) if st ~= 0 then return false end local ok, idle = pcall(function() return f:IsFree() end) if ok and idle ~= nil then return (idle and true or false) end return true end)(v) end end end) p.pending = nil p.hit = nil p.judge = nil p.judgeq = {} p.march_uuid = nil p.misses = 0 if p.cur ~= nil and p.used ~= nil then p.used[tostring(p.cur.pid)] = nil end DataCenter.__lw_gold = p if p.formation == nil then return -1 end if p.cur == nil then return -3 end if math.floor(tonumber(p.soldiers) or 0) <= 0 then return -2 end if not can then return 0 end local t = p.cur local uuid = _freshuuid(ws, p, t) if uuid == nil then local keep = {} for _, q in ipairs(p.targets or {}) do if tostring(q.pid) ~= tostring(t.pid) then keep[#keep + 1] = q end end p.targets = keep p.cur = nil DataCenter.__lw_gold = p return -4 end local srv = math.floor(tonumber(t.server or p.server) or 0) local kind = MarchTargetType.ATTACK_MONSTER if p.server ~= nil and srv ~= 0 and srv ~= p.server then kind = MarchTargetType.CROSS_ATTACK_MONSTER end local f, pid = p.formation, t.pid p.march_before = {} pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil then p.march_before[u] = true end end end end) p.pending = {pid = pid, uuid = uuid, key = tostring(uuid), x = t.x, y = t.y} p.hit = p.pending p.anchor = {x = t.x, y = t.y, pid = t.pid} p.last_sent = {x = t.x, y = t.y, pid = t.pid} p.attacks = p.attacks or 0 DataCenter.__lw_gold = p TimerManager:GetInstance():DelayInvoke(function() pcall(function() MarchUtil.SendCreateMarchMessage(f, kind, pid, uuid, 1, 1, false, srv, nil) end) end, 0.1) return 1 end)() INTO sent
    IF sent == -2
        LOG "the squad still has no army after asking — nothing was sent"
        STOP "no army"
IF sent == 0
    LOG "the chosen squad is busy — it takes no orders just now, so nothing was sent"
    STOP "squad busy"
IF sent == 1
    LOG "the order is away"
