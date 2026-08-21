# The re-target call, tried three ways at a squad that is already out in the field.
# ru: Вызов смены цели — три попытки на отряде, который уже стоит в поле.
#
# `OnChangeSingleFormation(formationUuid, targetMarchUuid, realPointId)` was given a MONSTER
# uuid in the middle slot and the server did nothing: the purse did not move and the march
# kept its old target. The name says «march», so either that slot wants something else, or
# the wrapper belongs to a screen and carries state a cold call has not got.
#
# The one that reaches the wire is `SendChangeMarchToServer` — its constants name the
# message (`world.march.change`) and every field of the payload: marchUuid, targetType,
# targetPoint, targetUuid, backHome, targetServerId, destroyTimeIndex, marchInfo{…},
# cardSkillUseInfoList. It builds marchInfo, the world id and the card list itself, so the
# arguments are the first seven at most.
#
# THE PROOF IS THE PURSE, as always: an attack costs ten, and a send returns cleanly
# whether or not the server honoured it.

ARGS squad = 1

READ_LUA (function() local out = {} for _, n in ipairs({'SendChangeMarchToServer', 'OnChangeSingleMarch', 'OnChangeSingleFormation'}) do local np, va = '?', '?' pcall(function() local i = debug.getinfo(MarchUtil[n], 'u') np = tostring(i.nparams) va = tostring(i.isvararg) end) out[#out + 1] = n .. '(nparams=' .. np .. ' vararg=' .. va .. ')' end return table.concat(out, ' | ') end)() INTO sig
LOG "arity: {sig}"

LUA DataCenter.__lw_chg = {squad = {squad}}

READ_LUA (function() local p = DataCenter.__lw_chg or {} pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == math.floor(tonumber(p.squad) or -1) then p.formation = tostring(v.uuid) p.state = math.floor(tonumber(v.state) or -1) end end end) local list = {} pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local f = nil pcall(function() f = tostring(m.formationUuid) end) if f == nil then pcall(function() f = tostring(m.formationId) end) end list[#list + 1] = 'uuid=' .. tostring(m.uuid) .. ' f=' .. tostring(f) .. ' st=' .. tostring(m.status) .. ' pos=' .. tostring(m.targetPos) .. ' end=' .. tostring(m.endTime) if (f ~= nil and f == p.formation) or ms.Count == 1 then p.march = tostring(m.uuid) p.pos = m.targetPos p.status = tostring(m.status) end end end end) pcall(function() p.server = math.floor(tonumber(LuaEntry.Player:GetSelfServerId()) or 0) end) DataCenter.__lw_chg = p return 'formation=' .. tostring(p.formation) .. ' state=' .. tostring(p.state) .. ' march=' .. tostring(p.march) .. ' pos=' .. tostring(p.pos) .. ' || marches[' .. tostring(#list) .. ']: ' .. table.concat(list, ' ; ') end)() INTO before
LOG "the squad as it stands: {before}"

LUA (function() local p = DataCenter.__lw_chg or {} if p.pos ~= nil then pcall(function() GoToUtil.MoveToWorldPoint(p.pos) end) end end)()
WAIT 4

READ_LUA (function() local p = DataCenter.__lw_chg or {} local ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) if ws == nil then return 'no-world' end local at = nil pcall(function() at = ws:IndexToTilePos(p.pos) end) if at == nil then return 'no-tile' end local best, bestd = nil, nil pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() ids:Add(1030000, 1) local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(at.x, at.y), 60, ids, res) local e = res:GetEnumerator() while e:MoveNext() do local uuid, tile = e.Current.Key, e.Current.Value local dx, dy = tile.x - at.x, tile.y - at.y local d = math.sqrt(dx * dx + dy * dy) if d > 0 and (bestd == nil or d < bestd) then local pid = nil pcall(function() pid = ws:TilePosToIndex(tile) end) if pid ~= nil then best, bestd = {key = tostring(uuid), pid = pid, x = tile.x, y = tile.y}, d end end end end) if best == nil then return 'nothing-near' end p.target = best DataCenter.__lw_chg = p return 'at=' .. tostring(best.x) .. ',' .. tostring(best.y) .. ' dist=' .. tostring(math.floor(bestd + 0.5)) .. ' pid=' .. tostring(best.pid) .. ' uuid=' .. best.key end)() INTO target
LOG "the nearest zombie to where the squad stands: {target}"

READ_LUA (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) return math.floor(v or 0) end)() INTO purse0
LOG "purse before any attempt: {purse0}"

# A — the payload's own order, with the tile INDEX in targetPoint.
READ_LUA (function() local p = DataCenter.__lw_chg or {} if p.march == nil or p.target == nil then return 'nothing to try' end local ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local n = nil pcall(function() n = arr[i]:GetType().Name end) if n == 'WorldScene' then ws = arr[i] break end end end) local uuid = nil pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() ids:Add(1030000, 1) local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(p.target.x, p.target.y), 2, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == p.target.key then uuid = e.Current.Key end end end) if uuid == nil then return 'the target is gone' end local m = nil pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.march) end) local mu = (m ~= nil) and m.uuid or p.march TimerManager:GetInstance():DelayInvoke(function() local ok, err = pcall(function() MarchUtil.SendChangeMarchToServer(mu, MarchTargetType.ATTACK_MONSTER, p.target.pid, uuid, 0, p.server, 0) end) CS.UnityEngine.Debug.LogError('ACT chg_a ok=' .. tostring(ok) .. ' err=' .. tostring(err)) end, 0.1) return 'scheduled' end)() INTO try_a
LOG "A — SendChangeMarchToServer(march, ATTACK_MONSTER, pid, uuid, 0, server, 0): {try_a}"
WAIT 6
READ_LUA (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) local p = DataCenter.__lw_chg or {} local s = '' pcall(function() local m = DataCenter.WorldMarchDataManager:GetMarch(p.march) s = ' status=' .. tostring(m.status) .. ' target=' .. tostring(m.targetPos) end) return math.floor(v or 0) .. s end)() INTO after_a
LOG "after A: purse={after_a}"

# B — the same, with the TILE POSITION where A had the index.
READ_LUA (function() local p = DataCenter.__lw_chg or {} if p.march == nil or p.target == nil then return 'nothing to try' end local ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local n = nil pcall(function() n = arr[i]:GetType().Name end) if n == 'WorldScene' then ws = arr[i] break end end end) local uuid = nil pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() ids:Add(1030000, 1) local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(p.target.x, p.target.y), 2, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == p.target.key then uuid = e.Current.Key end end end) if uuid == nil then return 'the target is gone' end local m = nil pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.march) end) local mu = (m ~= nil) and m.uuid or p.march TimerManager:GetInstance():DelayInvoke(function() local ok, err = pcall(function() MarchUtil.SendChangeMarchToServer(mu, MarchTargetType.ATTACK_MONSTER, CS.UnityEngine.Vector2Int(p.target.x, p.target.y), uuid, 0, p.server, 0) end) CS.UnityEngine.Debug.LogError('ACT chg_b ok=' .. tostring(ok) .. ' err=' .. tostring(err)) end, 0.1) return 'scheduled' end)() INTO try_b
LOG "B — the same call with a tile position instead of an index: {try_b}"
WAIT 6
READ_LUA (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) local p = DataCenter.__lw_chg or {} local s = '' pcall(function() local m = DataCenter.WorldMarchDataManager:GetMarch(p.march) s = ' status=' .. tostring(m.status) .. ' target=' .. tostring(m.targetPos) end) return math.floor(v or 0) .. s end)() INTO after_b
LOG "after B: purse={after_b}"

# C — the march-flavoured wrapper, with the monster where it asks for a march.
READ_LUA (function() local p = DataCenter.__lw_chg or {} if p.march == nil or p.target == nil then return 'nothing to try' end local ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local n = nil pcall(function() n = arr[i]:GetType().Name end) if n == 'WorldScene' then ws = arr[i] break end end end) local uuid = nil pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() ids:Add(1030000, 1) local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(p.target.x, p.target.y), 2, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == p.target.key then uuid = e.Current.Key end end end) if uuid == nil then return 'the target is gone' end local m = nil pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.march) end) local mu = (m ~= nil) and m.uuid or p.march TimerManager:GetInstance():DelayInvoke(function() local ok, err = pcall(function() MarchUtil.OnChangeSingleMarch(mu, uuid, p.target.pid) end) CS.UnityEngine.Debug.LogError('ACT chg_c ok=' .. tostring(ok) .. ' err=' .. tostring(err)) end, 0.1) return 'scheduled' end)() INTO try_c
LOG "C — OnChangeSingleMarch(march, uuid, pid): {try_c}"
WAIT 6
READ_LUA (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) local p = DataCenter.__lw_chg or {} local s = '' pcall(function() local m = DataCenter.WorldMarchDataManager:GetMarch(p.march) s = ' status=' .. tostring(m.status) .. ' target=' .. tostring(m.targetPos) end) return math.floor(v or 0) .. s end)() INTO after_c
LOG "after C: purse={after_c}"
