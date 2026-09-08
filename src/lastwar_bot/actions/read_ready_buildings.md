# Read which buildings have finished and are waiting to be opened.
# ru: Прочитать, какие здания достроились и ждут открытия.
#
# A READ, and nothing else: it presses nothing, opens nothing and spends nothing.
#
# WHAT «ГОТОВОЕ ЗДАНИЕ» IS, in the client's own terms. A construction runs in a slot of
# `QueueDataManager.queueDic` whose `type` is `NewQueueType.Default`; the slot's `state`
# walks `Free (0) -> Work (2) -> Finish (3)`, and `Finish` is the one this recipe is
# about — the timer has run out and the building is standing there with nothing taken
# yet. The slot's `itemId` is the BUILDING's uuid, not an item id, which is the one
# surprising thing about the shape (docs/research/ready-buildings.md).
#
# Everything else is asked of the building itself: its own id, the level it is at, the
# name in whatever language the client is in, and the sprite the game draws for it
# (`GetBuildIconPath`, which answers a full asset path — only its last part travels,
# because that is the stem the panel's picture route knows).
#
# What comes back in `ready_builds`, one entry per finished building, joined by `` ;; ``:
#
#     1000000000000001|10310000|12|UI_building_10310000|Фабрика кристаллов
#
# — the building's uuid, its building id, its level, the sprite stem and its name. An
# empty line is «nothing is waiting», which is a state and not a failure.
#
# AND WHEN THE NEXT ONE WILL BE READY, in `next_ready_sec`: how many seconds from now
# until the earliest slot that is still WORKING runs out its timer, or `-1` when nothing
# is building at all. The game's own clock answers it (`GetServerSeconds`), never the
# PC's — the two disagree and the PC is the one that lies (`tools/lib/game_clock.py`).
#
# It is here because the build queue is the one reading on the «VS» page with NO push
# behind it: the server sets the slot to `Finish` and announces nothing, so a panel that
# only listens would show yesterday's list for ever. The person's decision (#2633) was
# to move it by this number instead of by a clock — one alarm at the exact moment the
# nearest building is due, and no question asked in between.
#
# Who reads it: the «VS» tab's Tuesday. Opening them is `open_ready_buildings.md`, which
# holds the gate — this one never opens anything.

READ_LUA (function() local Q, M = DataCenter.QueueDataManager, DataCenter.BuildManager if Q == nil or M == nil or NewQueueType == nil or NewQueueState == nil then return '' end local out = {} pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state == NewQueueState.Finish then local uuid = tonumber(tostring(v.itemId)) or 0 local bid, lv, icon, name = 0, 0, '', '' pcall(function() local b = M:GetBuildingDataByUuid(uuid) bid = math.floor((b.itemId or 0) + 0) lv = math.floor((b.level or 0) + 0) end) pcall(function() local p = tostring(M:GetBuildIconPath(bid, lv) or '') icon = string.match(p, '([^/]+)$') or '' end) pcall(function() name = tostring(M:GetBuildingNameByUuid(uuid) or '') end) out[#out+1] = tostring(uuid) .. '|' .. bid .. '|' .. lv .. '|' .. icon .. '|' .. name end end end) return table.concat(out, ' ;; ') end)() INTO ready_builds
READ_LUA (function() local Q = DataCenter.QueueDataManager if Q == nil or NewQueueType == nil or NewQueueState == nil then return -1 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return -1 end local best = -1 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state ~= NewQueueState.Finish and v.state ~= NewQueueState.Free then local ends = math.floor(((v.endTime or 0) + 0) / 1000) if ends > 0 then local left = ends - now if left < 0 then left = 0 end if best < 0 or left < best then best = left end end end end end) return best end)() INTO next_ready_sec

LOG "ready buildings: {ready_builds} (next in {next_ready_sec}s)"
