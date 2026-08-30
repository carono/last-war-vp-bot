# «Гонка вооружений», фазы стройки / юнитов / технологий — очки набираются минутами ускорений.
# ru: «Гонка вооружений», фазы стройки, юнитов и технологий — очки набираются минутами ускорений.
#
# THIS SPENDS THE PLAYER'S OWN SPEED-UPS, and it stops at whichever ceiling it meets
# first, saying which one stopped it:
#
#   1. the phase's TOP CHEST. Points already scored are the server's own count, so the
#      run works out how many MINUTES are still missing and never spends past them.
#   2. `minutes` — a FUSE and never a target. «Не нужно хардкодить 3000 минут, нужно
#      читать текущий календарь»: what a phase costs is not a constant and not a number
#      anybody types in — the top chest's threshold depends on the player (a research
#      phase read 30 000 where an earlier hero phase read 12 000), so the minutes needed
#      are WORKED OUT every run from the live threshold and the live rate. This field
#      only says «whatever you worked out, do not spend more than this», and the log
#      prints both numbers so a fuse that bit is visible at once rather than a day later.
#      0 means no fuse at all, and then the chest is the only bound.
#   3. the QUEUE. A minute poured into a queue that has fifty seconds left is a minute
#      thrown away, so every send is cut to what the queue can still absorb, and the
#      run stops when no queue of the right kind is running.
#   4. the bag, under TWO rules that are not the same rule. **Specialised before
#      universal** — a universal one is worth the same minute here and worth it
#      everywhere else too. And **small denominations before large**: the person spends
#      600 five-minute speed-ups on a phase and counts them in PIECES, so a run that
#      burns the hour-long ones to reach the same minutes has spent something much
#      dearer for the same points. Ascending by what one piece is worth, specialised
#      first — both, in that order.
#
# And the log says both units, because they are read by different people and for
# different reasons: MINUTES are what the score is made of, PIECES are what leaves the
# bag. «speed-ups=600 minutes=3000 specialised=600pcs/3000min universal=0pcs/0min».
#
# It never spends diamonds. `useGold` is false and the gold-for-time argument is 0 on
# every send; a phase that could only be finished with diamonds is a phase this recipe
# leaves unfinished.
#
# ## The phase must be PAYING, and it is checked against the game, not against a memory
#
# The client carries a constant — `SpeedScoreValue`, 7 points a minute for building, 6
# for research, 4 for units — and it is WRONG. Measured live on a research phase, one
# minute paid **10**, not 6; and 30 000 (that phase's own top chest) at 10 a minute is
# exactly the 3 000 minutes the person spends by hand, where the constant would have
# asked for 5 000. So the constant is used only until the run has spent something, and
# from the first parcel onwards the rate is the run's OWN measurement: points scored
# since it started, divided by the minutes it has put in.
#
# The score is read before a send and again after it either way, and a send that moved
# nothing ends the run with «this phase did not pay for that» — a check the game itself
# answers, which survives the rules changing under us.
#
# **So the FIRST parcel of a run is ONE piece.** It is the person's own rule — «первый
# прогон минутным ускорителем, один раз, и сразу проверка, сдвинулись ли очки» — applied
# by the recipe to itself, on every phase, rather than by hand once. It is not caution
# for its own sake: the first real run spent 3 486 minutes where 3 000 were wanted,
# because the opening parcel was sized by the constant (4 999 minutes) and went out
# whole. One piece costs a minute and a round trip and buys the rate; everything after it
# is planned on a measured number.
#
# ## The bag names its own kind, and the client does not always fill that in
#
# A speed-up row carries `speedUpType` — 1 universal, 7 building, 6 research, 3 soldiers,
# 4 healing, the same keys as `ItemSpdMenu2SpeedScoreValue`. It is **not always there**:
# on a freshly started client every row reads `nil` until something in the client fills
# it in, and a pool built on that field alone comes back empty with «the bag holds no
# speed-up this phase could spend» over a bag holding thirty thousand of them.
#
# The ITEM ID does not have that problem. They run `2002<family><size>`, and the family
# digit is exactly the kind: `200200…` universal, `200210…` building, `200220…`
# research, `200230…` soldiers, `200240…` healing — checked against a client that HAD
# filled `speedUpType` in, and agreeing on every row. So the field is used when it is
# there and the id answers when it is not.
#
# `para3` — what one piece is worth, in SECONDS — arrives as a STRING. It is read
# through arithmetic rather than `tonumber`, which on a value out of the game can throw
# inside a `pcall` and be lost.
#
# ## Which queue, and which message
#
#   120001  «Строительство Города»     the build queues     `build.ccd.m.new`  bUUID
#   120003  «Исследование технологий»  the research queues  `queue.ccd.m.new`  qUUID
#
# A build queue names the BUILDING it is occupying, every other queue names itself —
# which is why the two messages exist and why they are not interchangeable. The kinds
# are `NewQueueType` (Default 0, Science 6).
#
# «Прогресс юнита» is NOT here. Its points are not bought with minutes: the design is
# to speed a training queue only far enough to FREE it, collect what is ready and then
# train as many level-9 soldiers as the barracks will take — a different ability, and
# one still waiting on the shape of the «start a training batch» send.
#
# ## Arguments
#
#   minutes  the most minutes of speed-up one run may spend. 0 = the top chest is the
#            only ceiling. The person's own number for a first live run is a small one.
#
# The reading is actions/read_arms_race.md; the research is docs/research/arms-race.md.

ARGS minutes = 0

CALL read_arms_race

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end return math.floor((d.event_id or 0) + 0) end)() INTO arms_event

IF arms_event == 120000
    STOP "the hero phase is running — its points are hires, not minutes"

IF arms_event == 120004
    STOP "the drone phase is running — its points are rallies, not minutes"

# The run's own plan and counters in one place, so the ceilings cannot drift apart from
# the numbers they are judged against. `sc0` is the score standing before the send about
# to go out; `paid` is whether the last one moved it.
LUA DataCenter.__lw_arms_sp = {cap = (tonumber("{minutes}") or 0) * 60, spent = 0, sends = 0, own_num = 0, own_sec = 0, uni_num = 0, uni_sec = 0, kinds = {}, sc0 = -1, sc_start = -1, rate_live = 0, need = 0, top = 0, paid = 1, why = 'nothing tried'}

# May another parcel of minutes go out, and what exactly is in it? Everything the answer
# needs is read in ONE call — the phase, the chest, the cap, the queues and the bag —
# and the parcel it settles on is parked in `p.next` for the send below.
READ_LUA (function() local p = DataCenter.__lw_arms_sp or {} p.next = nil if math.floor(tonumber(p.paid) or 1) == 0 then p.why = 'the score did not move for the last parcel' return 0 end local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then p.why = 'the game would not say which phase is running' return 0 end local ev = math.floor((d.event_id or 0) + 0) local plan = {[120001] = {kinds = {[0] = true}, rate = 'Build', spec = 7, build = true}, [120003] = {kinds = {[6] = true}, rate = 'Science', spec = 6}} local plan1 = plan[ev] if plan1 == nil then p.why = 'this phase is not paid for in minutes' return 0 end local rate = 0 pcall(function() rate = math.floor((SpeedScoreValue[plan1.rate] or 0) + 0) end) local live = tonumber(p.rate_live) or 0 if live > 0 then rate = live end if rate <= 0 then p.why = 'nothing prices a minute of ' .. plan1.rate .. ' speed-up — neither the client nor a parcel already sent' return 0 end p.rate = rate local sc = math.floor((d.sc or 0) + 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) if top <= 0 then top = math.floor((d.score_reward_max or 0) + 0) end if top > 0 and sc >= top then p.why = 'the top chest is already reached' return 0 end if math.floor(tonumber(p.sc_start) or -1) < 0 then p.sc_start = sc end p.top = top local want = 0 if top > 0 then want = math.ceil((top - sc) / rate) * 60 end p.need = want if want <= 0 then p.why = 'nothing left to score' return 0 end local cap = math.floor(tonumber(p.cap) or 0) local spent = math.floor(tonumber(p.spent) or 0) if cap > 0 then local room = cap - spent if room <= 0 then p.why = 'the safety ceiling of ' .. math.floor(cap / 60) .. ' minute(s) stopped the run before the chest did — the phase wanted ' .. math.ceil((tonumber(p.need) or 0) / 60) .. ' minute(s)' return 0 end if room < want then want = room end end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then p.why = 'the game would not say the time' return 0 end local Q = DataCenter.QueueDataManager local all = nil pcall(function() all = Q:GetAllQueue() end) if type(all) ~= 'table' then p.why = 'no queue list' return 0 end local best, bestLeft = nil, 0 for _, q in pairs(all) do if type(q) == 'table' then local t = math.floor((q.type or -1) + 0) local st = math.floor((q.state or 0) + 0) local ends = math.floor(((q.endTime or 0) / 1000) + 0) if plan1.kinds[t] and st == 2 and ends > now then local left = ends - now if left > bestLeft then best, bestLeft = q, left end end end end if best == nil then p.why = 'no queue of that kind is running — there is nothing to pour minutes into' return 0 end local room = bestLeft - 60 if room <= 0 then p.why = 'the longest queue has under a minute left' return 0 end if room < want then want = room end local I = DataCenter.ItemData local pool = {} pcall(function() for _, it in pairs(I:GetItemsByType(2) or {}) do if type(it) == 'table' then local id = math.floor((it.itemId or 0) + 0) local st = 0 pcall(function() st = math.floor((it.speedUpType or 0) + 0) end) if st <= 0 then local fam = math.floor((id % 100) / 10) local byId = {[0] = 1, [1] = 7, [2] = 6, [3] = 3, [4] = 4} st = byId[fam] or 0 end local sec = math.floor((it.para3 or 0) + 0) local have = math.floor((it.count or 0) + 0) if sec > 0 and have > 0 and (st == plan1.spec or st == 1) then pool[#pool + 1] = {id = id, sec = sec, have = have, own = (st == plan1.spec) and 1 or 0} end end end end) if #pool == 0 then p.why = 'the bag holds no speed-up this phase could spend' return 0 end table.sort(pool, function(a, b) if a.own ~= b.own then return a.own > b.own end return a.sec < b.sec end) local pick, num = nil, 0 for _, it in ipairs(pool) do if it.sec <= want then local n = math.floor(want / it.sec) if n > it.have then n = it.have end if n > 0 then pick, num = it, n break end end end if pick ~= nil and (tonumber(p.rate_live) or 0) <= 0 then num = 1 end if pick == nil then p.why = 'the smallest speed-up in the bag is worth more than the ' .. want .. ' second(s) still wanted' return 0 end p.sc0 = sc p.rate = rate p.next = {id = pick.id, num = num, each = pick.sec, own = pick.own, sec = pick.sec * num, build = plan1.build and 1 or 0, target = plan1.build and tostring(best.itemId or '') or tostring(best.uuid or '')} if p.next.target == '' or p.next.target == 'nil' then p.next = nil p.why = 'the queue would not name what to speed up' return 0 end p.why = '' return 1 end)() INTO arms_sp_go

IF arms_sp_go == 0
    READ_LUA (function() local p = DataCenter.__lw_arms_sp or {} return tostring(p.why or '') end)() INTO arms_sp_why
    LOG "arms speed-up: nothing sent — {arms_sp_why}"
    STOP "nothing to speed up"

WHILE arms_sp_go == 1 LIMIT 60
    # The parcel itself. `useGold = false` and the gold-for-time argument `0` are what
    # keep this off the player's diamonds; `itemIDs` is the game's own «<id>;<count>».
    LUA local p = DataCenter.__lw_arms_sp local n = p and p.next if n ~= nil then local ids = tostring(math.floor(n.id)) .. ';' .. tostring(math.floor(n.num)) local ok, why = pcall(function() if math.floor(n.build) == 1 then SFSNetwork.SendMessage(MsgDefines.BuildCcdMNew, {bUUID = n.target, isFixRuins = false, itemIDs = ids, useGold = false}, 0) else SFSNetwork.SendMessage(MsgDefines.QueueCcdMNew, {qUUID = n.target, itemIDs = ids, useGold = false}, 0) end end) p.sent_ok = ok and 1 or 0 p.sent_err = ok and '' or tostring(why) end

    WAIT 2

    # What that parcel cost and whether it paid. The score is the SERVER's, so a parcel
    # that moved nothing is a parcel this phase does not reward — and the next plan
    # refuses on `paid`.
    READ_LUA (function() local p = DataCenter.__lw_arms_sp or {} local n = p.next if n ~= nil and math.floor(tonumber(p.sent_ok) or 0) == 1 then p.spent = math.floor(tonumber(p.spent) or 0) + math.floor(n.sec) p.sends = math.floor(tonumber(p.sends) or 0) + 1 if math.floor(tonumber(n.own) or 0) == 1 then p.own_num = math.floor(tonumber(p.own_num) or 0) + math.floor(n.num) p.own_sec = math.floor(tonumber(p.own_sec) or 0) + math.floor(n.sec) else p.uni_num = math.floor(tonumber(p.uni_num) or 0) + math.floor(n.num) p.uni_sec = math.floor(tonumber(p.uni_sec) or 0) + math.floor(n.sec) end p.kinds = p.kinds or {} local key = tostring(math.floor(n.id)) .. '@' .. tostring(math.floor(n.each) / 60) .. 'm' p.kinds[key] = (math.floor(tonumber(p.kinds[key]) or 0)) + math.floor(n.num) end local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = -1 if d ~= nil then sc = math.floor((d.sc or 0) + 0) end local mins = (math.floor(tonumber(p.spent) or 0)) / 60 local st = math.floor(tonumber(p.sc_start) or -1) if mins > 0 and st >= 0 and sc > st then p.rate_live = (sc - st) / mins end local before = math.floor(tonumber(p.sc0) or -1) if math.floor(tonumber(p.sent_ok) or 0) == 0 then p.paid = 0 elseif before >= 0 and sc >= 0 and sc <= before then p.paid = 0 else p.paid = 1 end return p.paid end)() INTO arms_sp_paid

    IF arms_sp_paid == 0
        LOG "the score did not move for that parcel of minutes — nothing more is spent on this phase"

    READ_LUA (function() local p = DataCenter.__lw_arms_sp or {} p.next = nil if math.floor(tonumber(p.paid) or 1) == 0 then p.why = 'the score did not move for the last parcel' return 0 end local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then p.why = 'the game would not say which phase is running' return 0 end local ev = math.floor((d.event_id or 0) + 0) local plan = {[120001] = {kinds = {[0] = true}, rate = 'Build', spec = 7, build = true}, [120003] = {kinds = {[6] = true}, rate = 'Science', spec = 6}} local plan1 = plan[ev] if plan1 == nil then p.why = 'this phase is not paid for in minutes' return 0 end local rate = 0 pcall(function() rate = math.floor((SpeedScoreValue[plan1.rate] or 0) + 0) end) local live = tonumber(p.rate_live) or 0 if live > 0 then rate = live end if rate <= 0 then p.why = 'nothing prices a minute of ' .. plan1.rate .. ' speed-up — neither the client nor a parcel already sent' return 0 end p.rate = rate local sc = math.floor((d.sc or 0) + 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) if top <= 0 then top = math.floor((d.score_reward_max or 0) + 0) end if top > 0 and sc >= top then p.why = 'the top chest is reached' return 0 end if math.floor(tonumber(p.sc_start) or -1) < 0 then p.sc_start = sc end p.top = top local want = 0 if top > 0 then want = math.ceil((top - sc) / rate) * 60 end p.need = want if want <= 0 then p.why = 'nothing left to score' return 0 end local cap = math.floor(tonumber(p.cap) or 0) local spent = math.floor(tonumber(p.spent) or 0) if cap > 0 then local room = cap - spent if room <= 0 then p.why = 'the safety ceiling of ' .. math.floor(cap / 60) .. ' minute(s) stopped the run before the chest did — the phase wanted ' .. math.ceil((tonumber(p.need) or 0) / 60) .. ' minute(s)' return 0 end if room < want then want = room end end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then p.why = 'the game would not say the time' return 0 end local Q = DataCenter.QueueDataManager local all = nil pcall(function() all = Q:GetAllQueue() end) if type(all) ~= 'table' then p.why = 'no queue list' return 0 end local best, bestLeft = nil, 0 for _, q in pairs(all) do if type(q) == 'table' then local t = math.floor((q.type or -1) + 0) local st = math.floor((q.state or 0) + 0) local ends = math.floor(((q.endTime or 0) / 1000) + 0) if plan1.kinds[t] and st == 2 and ends > now then local left = ends - now if left > bestLeft then best, bestLeft = q, left end end end end if best == nil then p.why = 'no queue of that kind is running any more' return 0 end local room = bestLeft - 60 if room <= 0 then p.why = 'the longest queue has under a minute left' return 0 end if room < want then want = room end local I = DataCenter.ItemData local pool = {} pcall(function() for _, it in pairs(I:GetItemsByType(2) or {}) do if type(it) == 'table' then local id = math.floor((it.itemId or 0) + 0) local st = 0 pcall(function() st = math.floor((it.speedUpType or 0) + 0) end) if st <= 0 then local fam = math.floor((id % 100) / 10) local byId = {[0] = 1, [1] = 7, [2] = 6, [3] = 3, [4] = 4} st = byId[fam] or 0 end local sec = math.floor((it.para3 or 0) + 0) local have = math.floor((it.count or 0) + 0) if sec > 0 and have > 0 and (st == plan1.spec or st == 1) then pool[#pool + 1] = {id = id, sec = sec, have = have, own = (st == plan1.spec) and 1 or 0} end end end end) if #pool == 0 then p.why = 'the bag is out of speed-ups this phase could spend' return 0 end table.sort(pool, function(a, b) if a.own ~= b.own then return a.own > b.own end return a.sec < b.sec end) local pick, num = nil, 0 for _, it in ipairs(pool) do if it.sec <= want then local n = math.floor(want / it.sec) if n > it.have then n = it.have end if n > 0 then pick, num = it, n break end end end if pick ~= nil and (tonumber(p.rate_live) or 0) <= 0 then num = 1 end if pick == nil then p.why = 'the smallest speed-up left is worth more than the ' .. want .. ' second(s) still wanted' return 0 end p.sc0 = sc p.next = {id = pick.id, num = num, each = pick.sec, own = pick.own, sec = pick.sec * num, build = plan1.build and 1 or 0, target = plan1.build and tostring(best.itemId or '') or tostring(best.uuid or '')} if p.next.target == '' or p.next.target == 'nil' then p.next = nil p.why = 'the queue would not name what to speed up' return 0 end p.why = '' return 1 end)() INTO arms_sp_go

READ_LUA (function() local p = DataCenter.__lw_arms_sp or {} local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = -1 local top = 0 if d ~= nil then sc = math.floor((d.sc or 0) + 0) top = math.floor((d.score_reward_max or 0) + 0) end local bits = {} for k, v in pairs(p.kinds or {}) do bits[#bits+1] = tostring(k) .. 'x' .. tostring(v) end table.sort(bits) return 'speed-ups=' .. (math.floor(tonumber(p.own_num) or 0) + math.floor(tonumber(p.uni_num) or 0)) .. ' minutes=' .. math.floor((tonumber(p.spent) or 0) / 60) .. ' specialised=' .. math.floor(tonumber(p.own_num) or 0) .. 'pcs/' .. math.floor((tonumber(p.own_sec) or 0) / 60) .. 'min' .. ' universal=' .. math.floor(tonumber(p.uni_num) or 0) .. 'pcs/' .. math.floor((tonumber(p.uni_sec) or 0) / 60) .. 'min' .. ' by-kind=[' .. table.concat(bits, ' ') .. ']' .. ' parcels=' .. math.floor(tonumber(p.sends) or 0) .. ' score=' .. sc .. '/' .. top .. ' rate=' .. string.format('%.2f', tonumber(p.rate_live) or 0) .. '/min(measured, client says ' .. tostring(p.rate or '?') .. ')' .. ' wanted=' .. math.ceil((tonumber(p.need) or 0) / 60) .. 'min' .. ' stopped=' .. tostring(p.why or '') .. (tostring(p.sent_err or '') ~= '' and (' err=' .. tostring(p.sent_err)) or '') end)() INTO arms_sp_report

LOG "arms speed-up: {arms_sp_report}"
