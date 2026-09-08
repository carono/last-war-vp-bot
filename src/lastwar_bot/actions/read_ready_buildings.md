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
# Who reads it: the «VS» tab's Tuesday. Opening them is `open_ready_buildings.md`, which
# holds the gate — this one never opens anything.

READ_LUA (function() local Q, M = DataCenter.QueueDataManager, DataCenter.BuildManager if Q == nil or M == nil or NewQueueType == nil or NewQueueState == nil then return '' end local out = {} pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state == NewQueueState.Finish then local uuid = tonumber(tostring(v.itemId)) or 0 local bid, lv, icon, name = 0, 0, '', '' pcall(function() local b = M:GetBuildingDataByUuid(uuid) bid = math.floor((b.itemId or 0) + 0) lv = math.floor((b.level or 0) + 0) end) pcall(function() local p = tostring(M:GetBuildIconPath(bid, lv) or '') icon = string.match(p, '([^/]+)$') or '' end) pcall(function() name = tostring(M:GetBuildingNameByUuid(uuid) or '') end) out[#out+1] = tostring(uuid) .. '|' .. bid .. '|' .. lv .. '|' .. icon .. '|' .. name end end end) return table.concat(out, ' ;; ') end)() INTO ready_builds
LOG "ready buildings: {ready_builds}"
