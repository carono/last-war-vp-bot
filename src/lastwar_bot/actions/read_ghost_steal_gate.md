# Say why the game would refuse to rob one ghost-recon squad — one line, no press.
# ru: Сказать, почему игра откажет в краже конкретного отряда «Операции Призрак».
#
# READ ONLY. Nothing is sent, no window opens and no budget is touched — this is the
# diagnosis for «нажали пять раз, а stealTimes не сдвинулся» (#2010), which is the one
# question the ordinary logs cannot answer: the send is fire-and-forget, so a robbery the
# SERVER refuses looks exactly like one it accepted until the counter fails to move.
#
# It reads the same parts the client's own gate reads before it lights the in-game
# «украсть» button (`lua_actions.ghost_recon_can_steal`), one by one instead of as a
# single yes/no:
#
#   found       is this uuid in the CLIENT's own ghost lists at all (its `taskList` plus
#               the alliance one)? A tile that only a MAP SWEEP has seen is not, and the
#               gate below cannot answer for it — which is the first thing to rule out.
#   mine        my own squad; robbing it is refused outright.
#   looted      how many players have already taken this tile, of `stealMaxtimes`.
#   srv         the warzone the tile stands on, and…
#   in_range    …whether it is inside `dispatchStealRange`, the event's reachable set.
#               A tile outside it can be seen, walked to and pressed, and the server
#               will refuse every press.
#   point_type  `GetPointStealType`, the game's own verdict (2 = CanSteal).
#   left        ghost robberies still in hand today — the event's OWN five, counted
#               apart from the five secret-task ones.
#
# Run it on a uuid the panel has just pressed at:
#
#   run_action("read_ghost_steal_gate", variables={"uuid": "1409798000000000001"})

ARGS uuid = 0
# …and, when the caller knows WHERE the tile is, the coordinate to freshen it at first.
# `0,0` means «do not ask» — the gate is then read against whatever the client already
# holds. Asking is one `world.get.detail.new` for ONE point: the same round trip the game
# itself makes when a finger taps that tile, and no server jump (#2010).
ARGS x = 0
ARGS y = 0
ARGS server = 0

# 1. Freshen THIS ONE point, if the caller said where it is. Nothing is jumped to and
#    nothing else is asked for; the reply lands in `WorldPointDetailManager` and the
#    read below says whether it arrived (`detail=1`).
LUA if {x} > 0 and {y} > 0 then pcall(function() SFSNetwork.SendMessage("world.get.detail.new", SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int({x},{y})), {server}, 0, 29, "") end) end

WAIT 1.5

READ_LUA (function() local M=DataCenter.ActGhostreconManager local id=tostring({uuid}) local out={} local function put(k,v) out[#out+1]=k..'='..tostring(v) end local t=nil for _,list in ipairs({M.taskList or {}, M.allianceTaskList or {}}) do for _,x in ipairs(list) do if tostring(x.uuid)==id then t=x end end end put('found', t~=nil and 1 or 0) if t then local me=tostring(LuaEntry.Player.uid) put('mine', tostring(t.ownerId)==me and 1 or 0) local n=0 for _,s in ipairs(t.stealList or {}) do n=n+1 end put('looted', n) local tpl=M:GetTaskTemplate(t.cfgId) put('max', tpl and (tonumber(tpl.stealMaxtimes) or 3) or '-') local srv=t.ownerServer or t.targetServer put('srv', srv) put('in_range', (srv and (M.dispatchStealRange or {})[srv]==true) and 1 or 0) local ok,st=pcall(function() return M:GetPointStealType(t.cfgId, t.completionTime, {}) end) put('point_type', ok and tostring(st) or 'err') end local cfg=M:GetNowSettingCfg() local cap=tonumber(cfg and cfg.stealCount) or 0 local used=tonumber(M.stealTimes) or 0 put('left', cap-used) if {x} > 0 and {y} > 0 then local pid=SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int({x},{y})) local ok2,d=pcall(function() return DataCenter.WorldPointDetailManager:GetDetailByPointId(pid) end) put('detail', (ok2 and d) and 1 or 0) if ok2 and d then put('d_uuid', tostring(d.uuid or 0)) put('d_type', tostring(d.pointType or '-')) end end put('range_size', (function() local n=0 for _ in pairs(M.dispatchStealRange or {}) do n=n+1 end return n end)()) return table.concat(out,' ') end)() INTO gate

LOG "ghost_gate {gate}"
