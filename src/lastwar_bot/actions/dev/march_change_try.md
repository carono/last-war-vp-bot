# Re-target a squad that is STANDING in the field, with the call the game's own screen uses.
# ru: Переназначить отряд, который СТОИТ в поле, тем вызовом, которым пользуется игра.
#
# The operator: «я НИКОГДА не бью от базы, ухожу далеко, атакую СРАЗУ С ПОЛЯ, и когда отряд
# заканчивает атаку, у меня уже намечена цель — другой зомби или шахта — и лага нет».
#
# A bare `SendCreateMarchMessage` at such a squad is refused in silence. The client has
# another door, and `string.dump` named it:
#
#     MarchUtil.OnChangeSingleFormation(formationUuid, targetMarchUuid, realPointId)
#     MarchUtil.OnChangeSingleMarch(marchUuid, targetMarchUuid, realPointId)
#     MarchUtil.SendChangeMarchToServer  ->  SFSNetwork.SendMessage(MsgDefines.WorldMarchChange = "world.march.change",
#         {marchUuid, targetType, targetPoint, targetUuid, backHome, targetServerId,
#          destroyTimeIndex, marchInfo{posStart,status,startPos,endPos,startPointId,
#          endPointId,path,curWorldId}, cardSkillUseInfoList})
#
# «Другой зомби ИЛИ ШАХТА» is the same door: the sender picks the target type itself out of
# `MarchTargetType`, so this is «change what this army is doing», not an attack special case.
#
# THE PROOF IS THE PURSE. A send returns cleanly whether or not the server honoured it, so
# this reads the energy before and after: ten spent means the order was taken.

ARGS squad = 2

LUA DataCenter.__lw_chg = {squad = {squad}}

READ_LUA (function() local p = DataCenter.__lw_chg or {} local out = 'squad=' .. tostring(p.squad) pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == math.floor(tonumber(p.squad) or -1) then p.formation = v.uuid p.state = math.floor(tonumber(v.state) or -1) end end end) local m = nil pcall(function() local P = LuaEntry.Player m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if m ~= nil then pcall(function() p.march = tostring(m.uuid) p.status = tostring(m.status) p.pos = tostring(m.targetPos) end) end DataCenter.__lw_chg = p return out .. ' formation=' .. tostring(p.formation) .. ' state=' .. tostring(p.state) .. ' march=' .. tostring(p.march) .. ' status=' .. tostring(p.status) end)() INTO before
LOG "the squad as it stands: {before}"

# …AND THE CAMERA GOES THERE FIRST. The enumerator answers out of what the client has
# LOADED, and the client loads what the camera dwells on — the same rule the hunt's
# refresh ring is built on. Without this the reading is «nothing near» over ground full
# of zombies.
LUA (function() local p = DataCenter.__lw_chg or {} local pid = nil pcall(function() local m = DataCenter.WorldMarchDataManager:GetMarch(p.march) pid = m.targetPos end) if pid ~= nil then pcall(function() GoToUtil.MoveToWorldPoint(pid) end) end end)()
WAIT 3

# The nearest golden zombie to WHERE THE SQUAD IS — which is the whole point of doing this
# from the field: the client's own enumerator, centred on the squad's tile.
READ_LUA (function() local p = DataCenter.__lw_chg or {} local ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) if ws == nil then return 'no-world' end local at = nil pcall(function() local m = DataCenter.WorldMarchDataManager:GetMarch(p.march) at = ws:IndexToTilePos(m.targetPos) end) if at == nil then pcall(function() at = SceneUtils.IndexToTilePos(DataCenter.WorldMarchDataManager:GetMarch(p.march).targetPos) end) end if at == nil then pcall(function() at = ws.CurTilePos end) end local best, bestd = nil, nil pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() ids:Add(1030000, 1) local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(at.x, at.y), 60, ids, res) local e = res:GetEnumerator() while e:MoveNext() do local uuid, tile = e.Current.Key, e.Current.Value local dx, dy = tile.x - at.x, tile.y - at.y local d = math.sqrt(dx * dx + dy * dy) if d > 0 and (bestd == nil or d < bestd) then local pid = nil pcall(function() pid = ws:TilePosToIndex(tile) end) if pid ~= nil then best, bestd = {uuid = uuid, pid = pid, x = tile.x, y = tile.y}, d end end end end) if best == nil then return 'nothing-near' end p.target = best p.from = {x = at.x, y = at.y} DataCenter.__lw_chg = p return 'at=' .. tostring(best.x) .. ',' .. tostring(best.y) .. ' dist=' .. tostring(math.floor(bestd + 0.5)) .. ' uuid=' .. tostring(best.uuid) end)() INTO target
LOG "the nearest zombie to where the squad stands: {target}"

READ_LUA (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) return math.floor(v or 0) end)() INTO purse_before
LOG "purse before: {purse_before}"

# THE CALL. On the main thread through `DelayInvoke`, like every other send in this
# repository — a cold one from the hijack thread is created and dropped.
READ_LUA (function() local p = DataCenter.__lw_chg or {} if p.formation == nil or p.target == nil then return -1 end local ok = false TimerManager:GetInstance():DelayInvoke(function() local done, err = pcall(function() MarchUtil.OnChangeSingleFormation(p.formation, p.target.uuid, p.target.pid) end) CS.UnityEngine.Debug.LogError('ACT march_change ok=' .. tostring(done) .. ' err=' .. tostring(err)) end, 0.1) return 1 end)() INTO sent
LOG "the change was scheduled: {sent}"

WAIT 6

READ_LUA (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) return math.floor(v or 0) end)() INTO purse_after
LOG "purse after: {purse_after}"

READ_LUA (function() local p = DataCenter.__lw_chg or {} local m = nil pcall(function() local P = LuaEntry.Player m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, p.formation, P.allianceId) end) if m == nil then return 'no march' end local out = '' pcall(function() out = 'march=' .. tostring(m.uuid) .. ' status=' .. tostring(m.status) .. ' target=' .. tostring(m.targetPos) .. ' end=' .. tostring(m.endTime) end) return out end)() INTO after
LOG "the squad now: {after}"
