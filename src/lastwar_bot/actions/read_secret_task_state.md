# Say whether one secret-task tile is CONFIRMED to be there, by its coordinate.
# ru: Сказать, подтверждает ли игра конкретную секретку по координате.
#
# READ ONLY. Nothing is pressed, no window opens, no budget is touched and the camera
# stays where it is — this is one round trip of the request the client itself fires when
# a finger taps a marker (`world.get.detail.new {pointId, serverId, 0, 17, ""}`), asked
# about ONE point and answered into `WorldPointDetailManager`.
#
# **IT CAN ONLY EVER CONFIRM, NEVER DENY** (#2780, and #1484 before it — the first cut of
# this file got that wrong and it is written out here so nobody arrives at it twice). A
# point answers only when the CLIENT ALREADY HOLDS IT: its own alliance's tasks, and
# whatever the camera has loaded. Everything else stays silent however long it is given,
# and silence is not absence. Measured live on 2026-09-11, warzone 8128, one run each:
#
#   a point in the client's alliance table            answered
#   two tiles a camera walk had loaded 25 s earlier   answered
#   two tiles the walk had not reached                silent, asked twice, 25 s apart
#   five tiles the ★ list held, no walk               silent — and they were NOT gone
#
# So there are two answers here and no third:
#
#   exists=1        the game confirmed this tile: uuid, owner, alliance, its own warzone
#   exists=unknown  nothing came back, which says NOTHING about the tile
#
# **A caller may never take a row off a list on `unknown`** (THE_LIST_RULE clause 2,
# #1272). What removes a row is the MAP answering about the ground the tile stands on —
# `actions/verify_secret_tasks.md` walks the camera and the passive capture decodes what
# the server sends back — or the robbery being refused at the point of use.
#
# WHAT IT IS GOOD FOR: freshening «Сверено» on a row the game does confirm, and telling
# «the tile is there» from «I cannot tell» for one named coordinate — which is what the
# robbery already does before it presses.
#
# WHAT IT NEVER CARRIES: the loot count. `stealInfoList` is not among the 45 fields, so
# `n/3` still comes from the map tile and from the client's own alliance table
# (docs/research/secret-task-state-sources.md). `expireTime` came back 0 on every live
# tile measured, so the countdown is not here either.
#
# `pointId` is `y * 1000 + x`, server-local (docs/research/protocol.md §7), and it is
# packed here rather than asked for: `SceneUtils.TilePosToIndex` answers 0 while the
# client stands in its base, which is where a panel reading a list usually is.

# Windowless: it keeps the client only while it is talking to the game, so anything
# that wants the link outranks it and it parks at the first statement boundary.
SHARE

ARGS x = 0
ARGS y = 0
ARGS server = 0
# …and the tile's own packed pointId, when the caller already has it off the wire. A
# secret task's pointId is `y * 1000 + x`, server-local (docs/research/protocol.md §7);
# `SceneUtils.TilePosToIndex` answers 0 while the client stands in the base, which is why
# the packing is done here rather than asked for.
ARGS pid = 0
# How long to let the reply land. It is a round trip, so it is a settle, not a poll —
# nothing is asked twice, and asking twice was measured to change nothing (#2780).
ARGS settle = 8

IF server == 0
    FAIL "read_secret_task_state was given no warzone — name it in `server`"

LUA local M=DataCenter.ActDispatchTaskDataManager local pid=({pid} > 0) and {pid} or ({y}*1000+{x}) M.__lw_state={pid=pid} pcall(function() SFSNetwork.SendMessage("world.get.detail.new", pid, {server}, 0, 17, "") end)

WAIT {settle}

READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local D=DataCenter.WorldPointDetailManager local S=M.__lw_state or {} local out={} local function put(k,v) out[#out+1]=k..'='..tostring(v) end local ok,d=pcall(function() return D:GetDetailByPointId(S.pid) end) local got=(ok and d and (tonumber(d.uuid) or 0)>0) and true or false put('pid',S.pid) put('exists', got and 1 or 'unknown') if got then put('uuid',tostring(d.uuid)) put('expire',tostring(d.expireTime or 0)) put('uid',tostring(d.uid or '-')) put('owner',tostring(d.name or '-')) put('alliance',tostring(d.alAbbr or '-')) put('srv',tostring(d.srcServer or d.serverId or '-')) end return table.concat(out,' ') end)() INTO state

LOG "secret_state x={x} y={y} server={server} {state}"
