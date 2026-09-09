# Read the science centres: what each is studying, and what closing one would cost.
# ru: Прочитать научные центры: что изучает каждый и во что обойдётся завершить.
#
# A READ, and nothing else: it collects nothing, opens nothing and spends nothing.
#
# WHAT «НАУЧНЫЙ ЦЕНТР» IS, in the client's own terms. A research runs in a slot of
# `QueueDataManager.queueDic` whose `type` is `NewQueueType.Science`; an account has one
# of those per queue it has unlocked (`ScienceManager:HasExtraQueue`), and the slot's
# `state` walks `Free (0) -> Work (2) -> Finish (3)`. Unlike a BUILD queue — which names
# the building it occupies — a science slot names ITSELF in `uuid`, and its `itemId` is
# the SCIENCE id: that is the whole difference between the two speed-up messages
# (docs/research/research-queues.md).
#
# **A SLOT WHOSE TIMER HAS RUN OUT COUNTS AS FINISHED, WHATEVER ITS `state` SAYS**, for
# the same reason the build queue's does (#2641): the flip is the client's own and the
# client can be behind. The arbiter of an actual claim stays the server —
# `collect_research.md` sends and reports what came back.
#
# The technology itself is asked of `ScienceManager`: its name in whatever language the
# client is in (`GetScienceName`), and the template row behind it, which carries the
# level being studied and the sprite the game draws for it.
#
# What comes back in `research_rows`, one entry per CENTRE — the idle ones included,
# because a list of centres that hides the empty ones is not a list of centres — joined
# by `` ;; ``:
#
#     1000000000000001|70010000|3|science_icon01|Fatal Strike III|4820|0|1|200221:16:300:1
#
# — the queue's own uuid, the science id, the level being studied, the sprite stem, the
# name, how many SECONDS are left, the state (`1` finished and waiting, `0` studying,
# `2` idle), whether the bag can close it (`1`/`0`), and the PARCEL that would close it:
# `<itemId>:<pieces>:<seconds each>:<specialised?>`, joined by `+`.
#
# The parcel is chosen the way the arms race chooses one (`arms_race_speedup.md`):
# **specialised research speed-ups (`speedUpType 6`, and the `200220…` ids when the
# client has not filled that field in yet) before universal, small denominations before
# large**, and the last piece may overshoot because a study is not closed by a parcel
# that stops short of it. **The plans of several centres do not spend the same piece
# twice**: the bag is walked down as the earliest slot takes from it. Nothing is spent by
# reading it; spending it is `speedup_research.md`, which works the same parcel out again
# for itself at the moment of the press.
#
# AND WHEN THE NEXT ONE IS DUE, in `next_research_sec`: how many seconds from now until
# the earliest slot that is still WORKING runs out its timer, or `-1` when nothing is
# being studied at all. The game's own clock answers it (`GetServerSeconds`), never the
# PC's — the two disagree and the PC is the one that lies (`tools/lib/game_clock.py`).
#
# Who reads it: the «VS» tab's Wednesday. Collecting is `collect_research.md`; closing
# one outright is `speedup_research.md`. This one never presses anything.

READ_LUA (function() local Q, S, I = DataCenter.QueueDataManager, DataCenter.ScienceManager, DataCenter.ItemData if Q == nil or S == nil or NewQueueType == nil or NewQueueState == nil then return '' end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local rows = {} pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Science then rows[#rows + 1] = v end end end) table.sort(rows, function(a, b) return math.floor((a.qid or 0) + 0) < math.floor((b.qid or 0) + 0) end) local pool = {} if I ~= nil then pcall(function() for _, it in pairs(I:GetItemsByType(2) or {}) do if type(it) == 'table' then local id = math.floor((it.itemId or 0) + 0) local st = 0 pcall(function() st = math.floor((it.speedUpType or 0) + 0) end) if st <= 0 then local fam = math.floor((id % 100) / 10) local byId = {[0] = 1, [1] = 7, [2] = 6, [3] = 3, [4] = 4} st = byId[fam] or 0 end local sec = math.floor((it.para3 or 0) + 0) local have = math.floor((it.count or 0) + 0) if sec > 0 and have > 0 and (st == 6 or st == 1) then pool[#pool + 1] = {id = id, sec = sec, have = have, own = (st == 6) and 1 or 0} end end end end) end table.sort(pool, function(a, b) if a.own ~= b.own then return a.own > b.own end return a.sec < b.sec end) local out = {} local running = {} for _, v in ipairs(rows) do local ends = math.floor(((v.endTime or 0) + 0) / 1000) local free = (v.state == NewQueueState.Free) local done = (not free) and (v.state == NewQueueState.Finish or (now > 0 and ends > 0 and ends <= now)) local state = free and 2 or (done and 1 or 0) local sid = tostring(v.itemId or '') local name, icon, lv = '', '', 0 if state ~= 2 and sid ~= '' then pcall(function() name = tostring(S:GetScienceName(v.itemId) or '') end) pcall(function() local t = S:GetScienceTemplate(v.itemId) if type(t) == 'table' then icon = tostring(t.icon or '') lv = math.floor(tonumber(t.level) or 0) end end) end local left = 0 if state == 0 and now > 0 and ends > now then left = ends - now end local covered, parts = 0, {} if state == 0 and left > 0 then local want = left for _, it in ipairs(pool) do if want > 0 and it.have > 0 and it.sec <= want then local n = math.floor(want / it.sec) if n > it.have then n = it.have end if n > 0 then it.have = it.have - n want = want - n * it.sec parts[#parts + 1] = tostring(it.id) .. ':' .. n .. ':' .. it.sec .. ':' .. it.own end end end if want > 0 then local pick = nil for _, it in ipairs(pool) do if it.have > 0 and (pick == nil or it.sec < pick.sec) then pick = it end end if pick ~= nil then pick.have = pick.have - 1 want = 0 local key = tostring(pick.id) .. ':' local hit = nil for i, s in ipairs(parts) do if string.sub(s, 1, #key) == key then hit = i end end if hit ~= nil then local a, b, c = string.match(parts[hit], '^(%d+):(%d+):(.+)$') parts[hit] = a .. ':' .. (tonumber(b) + 1) .. ':' .. c else parts[#parts + 1] = tostring(pick.id) .. ':1:' .. pick.sec .. ':' .. pick.own end end end covered = (want <= 0) and 1 or 0 end out[#out + 1] = tostring(v.uuid) .. '|' .. sid .. '|' .. lv .. '|' .. icon .. '|' .. name .. '|' .. left .. '|' .. state .. '|' .. covered .. '|' .. table.concat(parts, '+') end return table.concat(out, ' ;; ') end)() INTO research_rows

READ_LUA (function() local Q = DataCenter.QueueDataManager if Q == nil or NewQueueType == nil or NewQueueState == nil then return -1 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return -1 end local best = -1 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Science and v.state ~= NewQueueState.Finish and v.state ~= NewQueueState.Free then local ends = math.floor(((v.endTime or 0) + 0) / 1000) if ends > now then local left = ends - now if best < 0 or left < best then best = left end end end end end) return best end)() INTO next_research_sec

LOG "science centres: {research_rows}"
LOG "the next study is due in {next_research_sec}s"
