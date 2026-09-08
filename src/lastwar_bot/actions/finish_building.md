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
# piece still in the bag — folded into the entry of its own denomination, so one item id
# is one send and never two.
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
# ## The send, and what proves it
#
# `build.ccd.m.new` — the build queue's own speed-up, `{bUUID, isFixRuins, itemIDs,
# useGold}`, where `bUUID` is the BUILDING's uuid (a build queue names the building it
# occupies; every other queue names itself) and `itemIDs` is the game's own
# `"<itemId>;<count>"`. One send per denomination.
#
# **THE PROOF IS THE SERVER'S OWN REPLY, AND IT HAD TO BE (#2641).** It used to be the
# queue: the slot either left `Work` for `Finish` or the run failed. That reported a
# failure over a construction the server had already closed, because the CLIENT does not
# apply what it is told. Measured live: four minutes of speed-ups poured into one build
# over fourteen minutes moved `queueDic`'s `endTime` by nothing at all, while the server
# answered `push.build.queue.info` with the new `uT` every time. `GetAllQueue`,
# `GetQueueDatasByType` and `GetAllQueueByType` are the same stale table, and
# `CheckAllQueueTimeFinish` only compares it against the clock — there is no client-side
# reading that is fresher than the one the client dropped.
#
# So the run listens for its own answer instead: `build.ccd.m.new` comes back carrying
# `finished` and a `buildInfo` with the building's `uuid` and its new `uT`. `finished`
# is the whole verdict, and the ear is taken down again the moment it has one.
#
# **AND THE ANSWER IS THEN WRITTEN WHERE THE CLIENT KEEPS IT.** The slot's `endTime` and
# the building's `updateTime` are set to the `uT` the server just sent, and the client's
# own `CheckAllQueueTimeFinish` is asked to look again — so the slot flips to `Finish`
# and `read_ready_buildings.md` sees the finished building at once instead of in eight
# minutes' time. Nothing is invented: it is the server's number, in the field the client
# itself keeps it in, and it is only ever moved EARLIER. A building the server would
# refuse to hand over is refused by `open_ready_buildings.md` exactly as before.
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
READ_LUA (function() local p = DataCenter.__lw_fin or {} p.plan = nil p.why = '' local Q, I = DataCenter.QueueDataManager, DataCenter.ItemData if Q == nil or I == nil or NewQueueType == nil or NewQueueState == nil then p.why = 'the client would not open its own build queue' return 0 end local want_uuid = tostring(p.uuid or '') if want_uuid == '' then p.why = 'no building was named' return 0 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then p.why = 'the game would not say the time' return 0 end local slot = nil pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state ~= NewQueueState.Finish and v.state ~= NewQueueState.Free and tostring(v.itemId) == want_uuid then slot = v break end end end) if slot == nil then p.why = 'that building is not under construction' return 0 end local left = math.floor(((slot.endTime or 0) + 0) / 1000) - now if left <= 0 then p.why = 'that construction has already run out its timer — it is waiting to be opened, not sped up' return 0 end p.left = left local pool = {} pcall(function() for _, it in pairs(I:GetItemsByType(2) or {}) do if type(it) == 'table' then local id = math.floor((it.itemId or 0) + 0) local st = 0 pcall(function() st = math.floor((it.speedUpType or 0) + 0) end) if st <= 0 then local fam = math.floor((id % 100) / 10) local byId = {[0] = 1, [1] = 7, [2] = 6, [3] = 3, [4] = 4} st = byId[fam] or 0 end local sec = math.floor((it.para3 or 0) + 0) local have = math.floor((it.count or 0) + 0) if sec > 0 and have > 0 and (st == 7 or st == 1) then pool[#pool + 1] = {id = id, sec = sec, have = have, own = (st == 7) and 1 or 0} end end end end) table.sort(pool, function(a, b) if a.own ~= b.own then return a.own > b.own end return a.sec < b.sec end) if #pool == 0 then p.why = 'the bag holds no building or universal speed-up' return 0 end local want, plan, num, sec = left, {}, 0, 0 for _, it in ipairs(pool) do if want > 0 and it.have > 0 and it.sec <= want then local n = math.floor(want / it.sec) if n > it.have then n = it.have end if n > 0 then it.have = it.have - n want = want - n * it.sec num = num + n sec = sec + n * it.sec plan[#plan + 1] = {id = it.id, num = n, sec = it.sec, own = it.own} end end end if want > 0 then local pick = nil for _, it in ipairs(pool) do if it.have > 0 and (pick == nil or it.sec < pick.sec) then pick = it end end if pick == nil then p.why = 'the bag is out of speed-ups ' .. want .. ' second(s) short of closing this construction' return 0 end pick.have = pick.have - 1 want = 0 num = num + 1 sec = sec + pick.sec local hit = nil for _, it in ipairs(plan) do if it.id == pick.id then hit = it end end if hit ~= nil then hit.num = hit.num + 1 else plan[#plan + 1] = {id = pick.id, num = 1, sec = pick.sec, own = pick.own} end end p.plan = plan p.num = num p.sec = sec return 1 end)() INTO finish_go
READ_LUA (function() local p = DataCenter.__lw_fin or {} return tostring(p.why or '') end)() INTO finish_why

IF finish_go == 0
    LOG "finish building: nothing sent — {finish_why}"
    STOP "nothing was spent"

READ_LUA (function() local p = DataCenter.__lw_fin or {} local bits = {} for _, it in ipairs(p.plan or {}) do bits[#bits + 1] = tostring(it.num) .. 'x' .. tostring(math.floor(it.sec / 60)) .. 'min#' .. tostring(it.id) .. (it.own == 1 and '(build)' or '(any)') end return 'left=' .. math.floor(tonumber(p.left) or 0) .. 's pieces=' .. math.floor(tonumber(p.num) or 0) .. ' minutes=' .. math.floor((tonumber(p.sec) or 0) / 60) .. ' parcel=[' .. table.concat(bits, ' ') .. ']' end)() INTO finish_plan
LOG "finish building: {finish_plan}"

# 2. THE EAR, raised before the send — the reply is the only fresh word there is.
#    It takes itself down after 60 seconds even if the run dies, so a wrapper can never
#    outlive the scenario that put it there.
LUA local p = DataCenter.__lw_fin p.fin = -1 p.newT = 0 local orig = SFSNetwork.HandleMessage local until_at = os.time() + 60 SFSNetwork.HandleMessage = function(...) local a = {...} pcall(function() local nm = '' for i = 1, 3 do if type(a[i]) == 'string' then nm = a[i] break end end if nm == 'build.ccd.m.new' then for i = 1, #a do local m = a[i] if type(m) == 'table' and type(m.buildInfo) == 'table' then local b = m.buildInfo if tostring(b.uuid) == tostring(p.uuid) then p.fin = (m.finished == true) and 1 or 0 p.newT = math.floor((b.uT or 0) + 0) end end end end end) if os.time() > until_at then SFSNetwork.HandleMessage = orig end return orig(...) end p.unhook = function() SFSNetwork.HandleMessage = orig end

# 3. The parcel itself — one send per denomination, no diamonds.
LUA local p = DataCenter.__lw_fin local ok, err = true, '' if p ~= nil and p.plan ~= nil then for _, it in ipairs(p.plan) do local ids = tostring(math.floor(it.id)) .. ';' .. tostring(math.floor(it.num)) local good, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.BuildCcdMNew, {bUUID = tostring(p.uuid), isFixRuins = false, itemIDs = ids, useGold = false}, 0) end) if not good then ok = false err = tostring(why) end end end p.sent_ok = ok and 1 or 0 p.sent_err = err

# 4. …and the answer. `finished` is the verdict; `-1` is «the game has not spoken yet».
READ_LUA (function() local p = DataCenter.__lw_fin or {} return math.floor(tonumber(p.fin) or -1) end)() INTO finish_reply
WHILE finish_reply == -1 LIMIT 15
    WAIT 1
    READ_LUA (function() local p = DataCenter.__lw_fin or {} return math.floor(tonumber(p.fin) or -1) end)() INTO finish_reply

# 5. Down with the ear, and the server's own number into the field the client dropped it
#    from — never later than what is already there, and never without a `finished` yes.
READ_LUA (function() local p = DataCenter.__lw_fin or {} pcall(function() if type(p.unhook) == 'function' then p.unhook() end end) p.unhook = nil if math.floor(tonumber(p.fin) or -1) ~= 1 then return 0 end local newT = math.floor(tonumber(p.newT) or 0) if newT <= 0 then return 0 end local Q, M = DataCenter.QueueDataManager, DataCenter.BuildManager local moved = 0 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and tostring(v.itemId) == tostring(p.uuid) then if newT < math.floor((v.endTime or 0) + 0) then v.endTime = newT moved = 1 end end end end) pcall(function() local b = M:GetBuildingDataByUuid(tonumber(tostring(p.uuid)) or 0) if b ~= nil and newT < math.floor((b.updateTime or 0) + 0) then b.updateTime = newT end end) pcall(function() Q:CheckAllQueueTimeFinish() end) return moved end)() INTO finish_applied
READ_LUA (function() local p = DataCenter.__lw_fin or {} return tostring(p.sent_err or '') end)() INTO finish_err

IF finish_reply == -1
    LOG "finish building: the parcel went out and the game said nothing back {finish_err}"
    FAIL "the speed-ups went out and the game did not answer"

IF finish_reply == 0
    LOG "finish building: the game answered, and the construction is still running {finish_err}"
    FAIL "the speed-ups went out and the construction did not close"

LOG "finish building: closed — {finish_plan} (queue corrected: {finish_applied})"
