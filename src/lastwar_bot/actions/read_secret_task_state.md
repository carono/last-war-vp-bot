# Say whether one secret-task tile still exists, by its coordinate, without moving the camera.
# ru: Сказать, существует ли конкретная секретка по координате, не двигая камеру.
#
# READ ONLY. Nothing is pressed, no window opens, no budget is touched and the camera
# stays where it is — this is one round trip of the request the client itself fires when
# a finger taps a marker (`world.get.detail.new {pointId, serverId, 0, 17, ""}`), asked
# about ONE point and answered into `WorldPointDetailManager`.
#
# WHAT IT CAN AND CANNOT SAY. The detail carries 45 fields — `uuid`, `uid`, `serverId`,
# `expireTime`, the owner's name and alliance — and it does NOT carry `stealInfoList`, so
# **`n/3` is not in this answer** and never will be: the loot count rides on the map tile
# (`world.get.block`) and on the client's own alliance table, and nowhere else
# (docs/research/secret-task-state-sources.md). What this answers is the other question a
# stale row raises: **is the tile still there at all.**
#
# A NIL IS AMBIGUOUS ON ITS OWN, and that is THE_LIST_RULE clause 2 (#1272): a reply that
# never arrived looks exactly like «there is nothing there», and reading the first as the
# second is how a whole list gets deleted for a fault of its own link. So a CONTROL point
# is asked alongside — an alliance task the client is sure exists and whose detail is NOT
# already cached, preferring one on the same warzone — and the verdict is only spoken when
# that control answered:
#
#   exists=1        the server sent a detail for this point: the tile is there
#   exists=0        the control answered and this point did not: the tile is gone
#   exists=unknown  the control did not answer either: nothing may be concluded,
#                   and no caller may take a row off a list on this run
#
# COST: one request for the tile, plus one for the control per RUN — so checking N rows
# of one warzone is N+1 requests, not 2N. Measured live on 2026-09-11 (warzone 8128,
# five rows in one run): the control answered on all three runs, every one of the five
# tiles came back nil, and the whole run took about ten seconds of which eight are the
# settle below.

ARGS x = 0
ARGS y = 0
ARGS server = 0
# …and the tile's own packed pointId, when the caller already has it off the wire. A
# secret task's pointId is `y * 1000 + x`, server-local (docs/research/protocol.md §7);
# `SceneUtils.TilePosToIndex` answers 0 while the client stands in the base, which is why
# the packing is done here rather than asked for.
ARGS pid = 0
# How long to let the reply land. It is a round trip to the game server, so it is a
# settle, not a poll — nothing is asked twice.
ARGS settle = 8

IF server == 0
    FAIL "read_secret_task_state was given no warzone — name it in `server`"

LUA local M=DataCenter.ActDispatchTaskDataManager local D=DataCenter.WorldPointDetailManager local pid=({pid} > 0) and {pid} or ({y}*1000+{x}) local ctrl=nil local any=nil for _,v in pairs(M.allianceTask or {}) do local d=D:GetDetailByPointId(v.pointId) if not (d and (tonumber(d.uuid) or 0)>0) then if (tonumber(v.targetServer) or 0)=={server} then ctrl={p=v.pointId,s=v.targetServer} break end any=any or {p=v.pointId,s=v.targetServer} end end ctrl=ctrl or any M.__lw_state={pid=pid,ctrl=ctrl} pcall(function() SFSNetwork.SendMessage("world.get.detail.new", pid, {server}, 0, 17, "") end) if ctrl then pcall(function() SFSNetwork.SendMessage("world.get.detail.new", ctrl.p, ctrl.s, 0, 17, "") end) end

WAIT {settle}

READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local D=DataCenter.WorldPointDetailManager local S=M.__lw_state or {} local out={} local function put(k,v) out[#out+1]=k..'='..tostring(v) end local ok,d=pcall(function() return D:GetDetailByPointId(S.pid) end) local got=(ok and d and (tonumber(d.uuid) or 0)>0) and true or false local cok=false if S.ctrl then local c=D:GetDetailByPointId(S.ctrl.p) cok=(c and (tonumber(c.uuid) or 0)>0) and true or false end put('pid',S.pid) put('exists', got and 1 or (cok and 0 or 'unknown')) put('control', cok and 1 or 0) if got then put('uuid',tostring(d.uuid)) put('expire',tostring(d.expireTime or 0)) put('uid',tostring(d.uid or '-')) put('owner',tostring(d.name or '-')) put('alliance',tostring(d.alAbbr or '-')) put('srv',tostring(d.srcServer or d.serverId or '-')) end return table.concat(out,' ') end)() INTO state

LOG "secret_state x={x} y={y} server={server} {state}"
