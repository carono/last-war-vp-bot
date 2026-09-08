# Read the base's building queue: what has finished, and what is still building.
# ru: Прочитать очередь строек базы: что достроилось и что ещё строится.
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
# AND WHAT IS STILL BUILDING, in `building_builds` — one entry per slot that is running,
# the earliest first, joined by `` ;; ``:
#
#     1000000000000001|10310000|12|UI_building_10310000|Фабрика|4820|1|200211:16:300:1+200201:1:900:0
#
# — the same five fields as above, then how many SECONDS the slot still has to run, then
# whether the bag can close it (`1`/`0`), then the PARCEL that would close it: the
# speed-ups it would take, `<itemId>:<pieces>:<seconds each>:<specialised?>`, joined by
# `+`. Nothing is spent by reading it; spending it is `finish_building.md`, which works
# the same parcel out again for itself at the moment of the press.
#
# The parcel is chosen the way the arms race chooses one (`arms_race_speedup.md`):
# **specialised (`speedUpType 7`, and the `2002<family>` id when the client has not
# filled that field in yet) before universal, small denominations before large**, so what
# leaves the bag is the cheapest set that still closes the build; the last piece may
# overshoot, because a construction is not closed by a parcel that stops short of it.
# **The plans of several slots do not spend the same piece twice**: the bag is walked
# down as the earliest slot takes from it, so two constructions over one bag are priced
# honestly rather than each against the full bag.
#
# Who reads it: the «VS» tab's Tuesday. Opening them is `open_ready_buildings.md`, which
# holds the gate — this one never opens anything.

READ_LUA (function() local Q, M = DataCenter.QueueDataManager, DataCenter.BuildManager if Q == nil or M == nil or NewQueueType == nil or NewQueueState == nil then return '' end local out = {} pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state == NewQueueState.Finish then local uuid = tonumber(tostring(v.itemId)) or 0 local bid, lv, icon, name = 0, 0, '', '' pcall(function() local b = M:GetBuildingDataByUuid(uuid) bid = math.floor((b.itemId or 0) + 0) lv = math.floor((b.level or 0) + 0) end) pcall(function() local p = tostring(M:GetBuildIconPath(bid, lv) or '') icon = string.match(p, '([^/]+)$') or '' end) pcall(function() name = tostring(M:GetBuildingNameByUuid(uuid) or '') end) out[#out+1] = tostring(uuid) .. '|' .. bid .. '|' .. lv .. '|' .. icon .. '|' .. name end end end) return table.concat(out, ' ;; ') end)() INTO ready_builds
READ_LUA (function() local Q = DataCenter.QueueDataManager if Q == nil or NewQueueType == nil or NewQueueState == nil then return -1 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return -1 end local best = -1 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state ~= NewQueueState.Finish and v.state ~= NewQueueState.Free then local ends = math.floor(((v.endTime or 0) + 0) / 1000) if ends > 0 then local left = ends - now if left < 0 then left = 0 end if best < 0 or left < best then best = left end end end end end) return best end)() INTO next_ready_sec

READ_LUA (function() local Q, M, I = DataCenter.QueueDataManager, DataCenter.BuildManager, DataCenter.ItemData if Q == nil or M == nil or I == nil or NewQueueType == nil or NewQueueState == nil then return '' end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return '' end local pool = {} pcall(function() for _, it in pairs(I:GetItemsByType(2) or {}) do if type(it) == 'table' then local id = math.floor((it.itemId or 0) + 0) local st = 0 pcall(function() st = math.floor((it.speedUpType or 0) + 0) end) if st <= 0 then local fam = math.floor((id % 100) / 10) local byId = {[0] = 1, [1] = 7, [2] = 6, [3] = 3, [4] = 4} st = byId[fam] or 0 end local sec = math.floor((it.para3 or 0) + 0) local have = math.floor((it.count or 0) + 0) if sec > 0 and have > 0 and (st == 7 or st == 1) then pool[#pool + 1] = {id = id, sec = sec, have = have, own = (st == 7) and 1 or 0} end end end end) table.sort(pool, function(a, b) if a.own ~= b.own then return a.own > b.own end return a.sec < b.sec end) local rows = {} pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state ~= NewQueueState.Finish and v.state ~= NewQueueState.Free then rows[#rows + 1] = v end end end) table.sort(rows, function(a, b) return ((a.endTime or 0) + 0) < ((b.endTime or 0) + 0) end) local out = {} for _, v in ipairs(rows) do local uuid = tonumber(tostring(v.itemId)) or 0 local bid, lv, icon, name = 0, 0, '', '' pcall(function() local b = M:GetBuildingDataByUuid(uuid) bid = math.floor((b.itemId or 0) + 0) lv = math.floor((b.level or 0) + 0) end) pcall(function() local ip = tostring(M:GetBuildIconPath(bid, lv) or '') icon = string.match(ip, '([^/]+)$') or '' end) pcall(function() name = tostring(M:GetBuildingNameByUuid(uuid) or '') end) local left = math.floor(((v.endTime or 0) + 0) / 1000) - now if left < 0 then left = 0 end local want = left local parts = {} for _, it in ipairs(pool) do if want > 0 and it.have > 0 and it.sec <= want then local n = math.floor(want / it.sec) if n > it.have then n = it.have end if n > 0 then it.have = it.have - n want = want - n * it.sec parts[#parts + 1] = tostring(it.id) .. ':' .. n .. ':' .. it.sec .. ':' .. it.own end end end if want > 0 then local pick = nil for _, it in ipairs(pool) do if it.have > 0 and (pick == nil or it.sec < pick.sec) then pick = it end end if pick ~= nil then pick.have = pick.have - 1 want = 0 parts[#parts + 1] = tostring(pick.id) .. ':1:' .. pick.sec .. ':' .. pick.own end end local covered = (want <= 0) and 1 or 0 out[#out + 1] = tostring(uuid) .. '|' .. bid .. '|' .. lv .. '|' .. icon .. '|' .. name .. '|' .. left .. '|' .. covered .. '|' .. table.concat(parts, '+') end return table.concat(out, ' ;; ') end)() INTO building_builds

LOG "ready buildings: {ready_builds} (next in {next_ready_sec}s)"
LOG "under construction: {building_builds}"
