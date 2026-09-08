# Finish a construction outright, spending the speed-ups it takes to close it.
# ru: Завершить стройку, потратив ускорения, которых на это хватает.
#
# **THIS SPENDS THE PLAYER'S OWN SPEED-UPS, AND THEY DO NOT COME BACK.** So it is a
# press a person makes, never a schedule: nothing in the panel plays this file by itself,
# and what would leave the bag is drawn on the row BEFORE the button under it is touched
# («VS» → вторник, `read_ready_buildings.md` prices every running slot).
#
# ## What it spends, and in what order
#
# The parcel is chosen exactly the way the arms race chooses one
# (`arms_race_speedup.md`): **specialised building speed-ups before universal ones** —
# a universal minute is worth the same here and worth it everywhere else too — and
# **small denominations before large**, because a person counts what left the bag in
# PIECES and burning an hour-long one to buy five minutes is the dear way to the same
# second. The kind is `speedUpType` (7 building, 1 universal) and, when a freshly
# started client has not filled that field in yet, the item id: they run
# `2002<family><size>`, `200200…` universal and `200210…` building.
#
# **The last piece may overshoot, and that is deliberate.** A construction is not closed
# by a parcel that stops a minute short of it, so the plan tops up with the smallest
# piece still in the bag.
#
# ## What it refuses to do
#
# **A bag that cannot close the build spends NOTHING.** Minutes poured into a
# construction that stays open buy no finished building and cannot be taken back, so a
# run that comes up short stops with «the bag is N second(s) short» and the bag untouched.
# It also refuses a building that is not running (one already waiting to be opened is
# `open_ready_buildings.md`'s business, and it is gated on the arms race's building hour
# — this file opens nothing and holds no such gate: a construction may be closed at any
# hour, and what is done with the finished building afterwards is that recipe's decision).
#
# **It never spends diamonds.** `useGold` is false and the gold-for-time argument is `0`,
# as on every send this repository makes.
#
# ## The send
#
# `build.ccd.m.new` — the build queue's own speed-up, `{bUUID, isFixRuins, itemIDs,
# useGold}`, where `bUUID` is the BUILDING's uuid (a build queue names the building it
# occupies; every other queue names itself) and `itemIDs` is the game's own
# `"<itemId>;<count>"`. One send per denomination, and the proof is the queue: the slot
# either leaves `Work` for `Finish` or the run FAILS, because a send the server drops
# returns as cleanly as one it takes.
#
# ## Arguments
#
#   uuid  the BUILDING's uuid, as `read_ready_buildings.md` printed it in
#         `building_builds`. There is no «all of them»: an irreversible spend is named
#         one at a time.
#
# The research is docs/research/ready-buildings.md.

ARGS uuid =

LUA DataCenter.__lw_fin = {uuid = '{uuid}'}

# 1. What would close it, worked out again HERE rather than trusted from the screen —
#    a plan a person read a minute ago is a plan the clock has already moved.
READ_LUA (function() local p = DataCenter.__lw_fin or {} p.plan = nil p.why = '' local Q, I = DataCenter.QueueDataManager, DataCenter.ItemData if Q == nil or I == nil or NewQueueType == nil or NewQueueState == nil then p.why = 'the client would not open its own build queue' return 0 end local want_uuid = tostring(p.uuid or '') if want_uuid == '' then p.why = 'no building was named' return 0 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then p.why = 'the game would not say the time' return 0 end local slot = nil pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state ~= NewQueueState.Finish and v.state ~= NewQueueState.Free and tostring(v.itemId) == want_uuid then slot = v break end end end) if slot == nil then p.why = 'that building is not under construction' return 0 end local left = math.floor(((slot.endTime or 0) + 0) / 1000) - now if left <= 0 then p.why = 'that construction has already run out its timer — it is waiting to be opened, not sped up' return 0 end p.left = left local pool = {} pcall(function() for _, it in pairs(I:GetItemsByType(2) or {}) do if type(it) == 'table' then local id = math.floor((it.itemId or 0) + 0) local st = 0 pcall(function() st = math.floor((it.speedUpType or 0) + 0) end) if st <= 0 then local fam = math.floor((id % 100) / 10) local byId = {[0] = 1, [1] = 7, [2] = 6, [3] = 3, [4] = 4} st = byId[fam] or 0 end local sec = math.floor((it.para3 or 0) + 0) local have = math.floor((it.count or 0) + 0) if sec > 0 and have > 0 and (st == 7 or st == 1) then pool[#pool + 1] = {id = id, sec = sec, have = have, own = (st == 7) and 1 or 0} end end end end) table.sort(pool, function(a, b) if a.own ~= b.own then return a.own > b.own end return a.sec < b.sec end) if #pool == 0 then p.why = 'the bag holds no building or universal speed-up' return 0 end local want, plan, num, sec = left, {}, 0, 0 for _, it in ipairs(pool) do if want > 0 and it.have > 0 and it.sec <= want then local n = math.floor(want / it.sec) if n > it.have then n = it.have end if n > 0 then it.have = it.have - n want = want - n * it.sec num = num + n sec = sec + n * it.sec plan[#plan + 1] = {id = it.id, num = n, sec = it.sec, own = it.own} end end end if want > 0 then local pick = nil for _, it in ipairs(pool) do if it.have > 0 and (pick == nil or it.sec < pick.sec) then pick = it end end if pick == nil then p.why = 'the bag is out of speed-ups ' .. want .. ' second(s) short of closing this construction' return 0 end pick.have = pick.have - 1 want = 0 num = num + 1 sec = sec + pick.sec plan[#plan + 1] = {id = pick.id, num = 1, sec = pick.sec, own = pick.own} end p.plan = plan p.num = num p.sec = sec return 1 end)() INTO finish_go
READ_LUA (function() local p = DataCenter.__lw_fin or {} return tostring(p.why or '') end)() INTO finish_why

IF finish_go == 0
    LOG "finish building: nothing sent — {finish_why}"
    STOP "nothing was spent"

READ_LUA (function() local p = DataCenter.__lw_fin or {} local bits = {} for _, it in ipairs(p.plan or {}) do bits[#bits + 1] = tostring(it.num) .. 'x' .. tostring(math.floor(it.sec / 60)) .. 'min#' .. tostring(it.id) .. (it.own == 1 and '(build)' or '(any)') end return 'left=' .. math.floor(tonumber(p.left) or 0) .. 's pieces=' .. math.floor(tonumber(p.num) or 0) .. ' minutes=' .. math.floor((tonumber(p.sec) or 0) / 60) .. ' parcel=[' .. table.concat(bits, ' ') .. ']' end)() INTO finish_plan
LOG "finish building: {finish_plan}"

# 2. The parcel itself — one send per denomination, no diamonds.
LUA local p = DataCenter.__lw_fin local ok, err = true, '' if p ~= nil and p.plan ~= nil then for _, it in ipairs(p.plan) do local ids = tostring(math.floor(it.id)) .. ';' .. tostring(math.floor(it.num)) local good, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.BuildCcdMNew, {bUUID = tostring(p.uuid), isFixRuins = false, itemIDs = ids, useGold = false}, 0) end) if not good then ok = false err = tostring(why) end end end p.sent_ok = ok and 1 or 0 p.sent_err = err

WAIT 2

# 3. …and whether the game took it. The slot leaves `Work` when it did.
READ_LUA (function() local p = DataCenter.__lw_fin or {} if math.floor(tonumber(p.sent_ok) or 0) == 0 then p.after = -2 return 0 end local Q = DataCenter.QueueDataManager if Q == nil or NewQueueType == nil or NewQueueState == nil then p.after = -3 return 0 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local want_uuid = tostring(p.uuid or '') local slot = nil pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and tostring(v.itemId) == want_uuid and v.state ~= NewQueueState.Free then slot = v break end end end) if slot == nil then p.after = -1 return 1 end if math.floor((slot.state or 0) + 0) == math.floor((NewQueueState.Finish or 3) + 0) then p.after = 0 return 1 end local left = math.floor(((slot.endTime or 0) + 0) / 1000) - now if left < 0 then left = 0 end p.after = left if left <= 0 then return 1 end return 0 end)() INTO finish_done
READ_LUA (function() local p = DataCenter.__lw_fin or {} return math.floor(tonumber(p.after) or 0) end)() INTO finish_left
READ_LUA (function() local p = DataCenter.__lw_fin or {} return tostring(p.sent_err or '') end)() INTO finish_err

IF finish_done == 0
    LOG "finish building: the slot is still running, {finish_left}s left {finish_err}"
    FAIL "the speed-ups went out and the construction did not close"

LOG "finish building: closed — {finish_plan}"
