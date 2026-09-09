# Finish a research outright, spending the speed-ups it takes to close it.
# ru: Завершить исследование, потратив ускорения, которых на это хватает.
#
# **THIS SPENDS THE PLAYER'S OWN SPEED-UPS, AND THEY DO NOT COME BACK.** So it is a
# press a person makes, never a schedule: nothing in the panel plays this file by itself,
# and what would leave the bag is drawn on the row BEFORE the button under it is touched
# («VS» → среда, `read_research_queues.md` prices every running centre).
#
# It is the research twin of `finish_building.md` and it differs in exactly two places:
# the speed-ups it may spend are the RESEARCH ones (`speedUpType 6`, the `200220…` ids)
# before the universal ones, and the send is the one every non-build queue uses —
# `queue.ccd.m.new` with the QUEUE's own uuid. A build queue names the building it
# occupies; every other queue names itself (docs/research/arms-race.md).
#
# ## What it spends, and in what order
#
# **Specialised research speed-ups before universal ones** — a universal minute is worth
# the same here and worth it everywhere else too — and **small denominations before
# large**, because a person counts what left the bag in PIECES and burning an hour-long
# one to buy five minutes is the dear way to the same second. The kind is `speedUpType`
# (6 research, 1 universal) and, when a freshly started client has not filled that field
# in yet, the item id: they run `2002<family><size>`, `200200…` universal and `200220…`
# research.
#
# **The last piece may overshoot, and that is deliberate.** A study is not closed by a
# parcel that stops a minute short of it, so the plan tops up with the smallest piece
# still in the bag — folded into the entry of its own denomination, so one item id is one
# send and never two.
#
# ## What it refuses to do
#
# **A bag that cannot close the study spends NOTHING.** Minutes poured into a research
# that stays open buy no finished technology and cannot be taken back, so a run that
# comes up short stops with «the bag is N second(s) short» and the bag untouched. It also
# refuses a centre that is not studying — one already waiting to be collected is
# `collect_research.md`'s business.
#
# **It never spends diamonds.** `useGold` is false and the gold-for-time argument is `0`,
# as on every send this repository makes.
#
# ## Arguments
#
#   uuid  the QUEUE's own uuid, as `read_research_queues.md` printed it. There is no
#         «all of them»: an irreversible spend is named one at a time.

ARGS uuid =

LUA DataCenter.__lw_sci_sp = {uuid = '{uuid}'}

# 1. What would close it, worked out again HERE rather than trusted from the screen —
#    a plan a person read a minute ago is a plan the clock has already moved.
READ_LUA (function() local p = DataCenter.__lw_sci_sp or {} p.plan = nil p.why = '' local Q, I = DataCenter.QueueDataManager, DataCenter.ItemData if Q == nil or I == nil or NewQueueType == nil or NewQueueState == nil then p.why = 'the client would not open its own queues' return 0 end local want_uuid = tostring(p.uuid or '') if want_uuid == '' then p.why = 'no research was named' return 0 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then p.why = 'the game would not say the time' return 0 end local slot = nil pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Science and v.state ~= NewQueueState.Finish and v.state ~= NewQueueState.Free and tostring(v.uuid) == want_uuid then slot = v break end end end) if slot == nil then p.why = 'that centre is not studying anything' return 0 end local left = math.floor(((slot.endTime or 0) + 0) / 1000) - now if left <= 0 then p.why = 'that study has already run out its timer — it is waiting to be collected, not sped up' return 0 end p.left = left local pool = {} pcall(function() for _, it in pairs(I:GetItemsByType(2) or {}) do if type(it) == 'table' then local id = math.floor((it.itemId or 0) + 0) local st = 0 pcall(function() st = math.floor((it.speedUpType or 0) + 0) end) if st <= 0 then local fam = math.floor((id % 100) / 10) local byId = {[0] = 1, [1] = 7, [2] = 6, [3] = 3, [4] = 4} st = byId[fam] or 0 end local sec = math.floor((it.para3 or 0) + 0) local have = math.floor((it.count or 0) + 0) if sec > 0 and have > 0 and (st == 6 or st == 1) then pool[#pool + 1] = {id = id, sec = sec, have = have, own = (st == 6) and 1 or 0} end end end end) table.sort(pool, function(a, b) if a.own ~= b.own then return a.own > b.own end return a.sec < b.sec end) if #pool == 0 then p.why = 'the bag holds no research or universal speed-up' return 0 end local want, plan, num, sec = left, {}, 0, 0 for _, it in ipairs(pool) do if want > 0 and it.have > 0 and it.sec <= want then local n = math.floor(want / it.sec) if n > it.have then n = it.have end if n > 0 then it.have = it.have - n want = want - n * it.sec num = num + n sec = sec + n * it.sec plan[#plan + 1] = {id = it.id, num = n, sec = it.sec, own = it.own} end end end if want > 0 then local pick = nil for _, it in ipairs(pool) do if it.have > 0 and (pick == nil or it.sec < pick.sec) then pick = it end end if pick == nil then p.why = 'the bag is out of speed-ups ' .. want .. ' second(s) short of closing this study' return 0 end pick.have = pick.have - 1 want = 0 num = num + 1 sec = sec + pick.sec local hit = nil for _, it in ipairs(plan) do if it.id == pick.id then hit = it end end if hit ~= nil then hit.num = hit.num + 1 else plan[#plan + 1] = {id = pick.id, num = 1, sec = pick.sec, own = pick.own} end end p.plan = plan p.num = num p.sec = sec return 1 end)() INTO research_go
READ_LUA (function() local p = DataCenter.__lw_sci_sp or {} return tostring(p.why or '') end)() INTO research_why

IF research_go == 0
    LOG "speed up research: nothing sent — {research_why}"
    STOP "nothing was spent"

READ_LUA (function() local p = DataCenter.__lw_sci_sp or {} local bits = {} for _, it in ipairs(p.plan or {}) do bits[#bits + 1] = tostring(it.num) .. 'x' .. tostring(math.floor(it.sec / 60)) .. 'min#' .. tostring(it.id) .. (it.own == 1 and '(research)' or '(any)') end return 'left=' .. math.floor(tonumber(p.left) or 0) .. 's pieces=' .. math.floor(tonumber(p.num) or 0) .. ' minutes=' .. math.floor((tonumber(p.sec) or 0) / 60) .. ' parcel=[' .. table.concat(bits, ' ') .. ']' end)() INTO research_plan
LOG "speed up research: {research_plan}"

# 2. The parcel itself — one send per denomination, no diamonds.
LUA local p = DataCenter.__lw_sci_sp local ok, err = true, '' if p ~= nil and p.plan ~= nil then for _, it in ipairs(p.plan) do local ids = tostring(math.floor(it.id)) .. ';' .. tostring(math.floor(it.num)) local good, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.QueueCcdMNew, {qUUID = tostring(p.uuid), itemIDs = ids, useGold = false}, 0) end) if not good then ok = false err = tostring(why) end end end p.sent_ok = ok and 1 or 0 p.sent_err = err

WAIT 3

# 3. …and what the queue says now. Unlike a construction, a research queue IS moved by
#    the client when the server answers — so the slot's own timer is the verdict, and a
#    study whose timer has run out is one `collect_research.md` can take.
READ_LUA (function() local p = DataCenter.__lw_sci_sp or {} local Q = DataCenter.QueueDataManager if Q == nil or NewQueueType == nil then return -1 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return -1 end local left = -1 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Science and tostring(v.uuid) == tostring(p.uuid) then left = math.floor(((v.endTime or 0) + 0) / 1000) - now end end end) if left < 0 then left = 0 end return left end)() INTO research_left
READ_LUA (function() local p = DataCenter.__lw_sci_sp or {} return tostring(p.sent_err or '') end)() INTO research_err

IF research_left == -1
    LOG "speed up research: the parcel went out and the queue said nothing back {research_err}"
    FAIL "the speed-ups went out and the game did not answer"

LOG "speed up research: sent — {research_plan}, the study now has {research_left}s left {research_err}"
