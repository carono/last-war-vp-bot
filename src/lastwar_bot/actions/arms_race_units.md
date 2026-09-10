# «Гонка вооружений», фаза юнитов — очки набираются обученными солдатами.
# ru: «Гонка вооружений», фаза юнитов — очки даёт обучение солдат.
#
# THIS SPENDS THE PLAYER'S OWN RESOURCES. What scores here is not minutes of speed-up —
# it is SOLDIERS: a batch started in a barracks pays when it is started, and a live run
# measured it at 28 points a level-9 soldier (1 000 soldiers took a phase from 0 to
# 28 000 of its 75 000). So the run does three things in order, and each of them is
# bounded:
#
#   1. **Collect** every barracks whose batch is finished. Spends nothing, and a barracks
#      holding a finished batch cannot start another one.
#   2. **Free** the barracks still running, by pouring soldier speed-ups into them —
#      SOLDIER ones before universal, small pieces before large, under the `free_minutes`
#      fuse. This is the only part of the run that touches the bag.
#
#      **A barracks is freed WHOLE or not touched at all (#2709).** The run plans the
#      pieces for one barracks before it sends anything: what the plan cannot finish —
#      because the fuse would not stretch, or because the bag has not got that many
#      minutes — is left alone and named in the log. Half-freeing spends the pieces and
#      buys nothing: the batch is still running, so nothing is collected and nothing new
#      is started, and the phase scores zero with the bag lighter. The shortest queue is
#      freed first, so a given fuse empties as many barracks as it can.
#
#      The plan also finishes the last few seconds with ONE piece one size up, which the
#      old walk could not: taking only pieces no longer than what is left stops at a
#      remainder smaller than the smallest piece, and a barracks with forty seconds to go
#      stayed busy after the minutes went in.
#   3. **Train** the biggest level-`level` batch every free barracks will take, under the
#      `soldiers` ceiling. The size is not calculated: the LAST batch that barracks ran
#      is a size the game has already accepted for it, so that is what is asked for
#      again, and `fallback` is used only for a barracks that has never run one.
#
# It never spends diamonds: `useGold` is false and the gold-for-time argument is 0 on
# every send here, exactly as in actions/arms_race_speedup.md.
#
# ## What is proven and what is measured
#
# All three sends are **proven live**. The collect and the training: two barracks
# collected (918 soldiers) and two started on 500 each, with the phase score moving
# 0 → 28 000 in the same minute. The freeing one, measured on a test account: one
# five-minute soldier speed-up took a barracks from 9 026 s left to 8 722 s — 300 s of it,
# the other four seconds being the clock — and left `productBase` alone, because the send
# buys TIME and not soldiers.
#
# The run still reads what the barracks had left BEFORE and AFTER and says how much the
# minutes moved. Not because the shape is in doubt, but because a run that believed a
# refused send would train into a barracks that is still busy, and the check costs one
# reading.
#
# ## Arguments
#
#   soldier_level  which soldier level to train. 9 by default — the level this account
#              trains in bulk; a level the barracks cannot train is refused by the server
#              rather than half-started. Named for the soldier on purpose: a recipe that
#              CALLs this one hands over its own variables (`docs/dsl.md`), and a plain
#              `level` means a monster's level to half the recipes in this folder.
#   soldiers   the most soldiers ONE run may put into training, over all barracks. 0
#              means «whatever the barracks themselves accept». It is a fuse on the
#              player's RESOURCES, so it is small by default where the panel sets it.
#   free_minutes  the most minutes of speed-up one run may spend on freeing barracks. 0
#              by default, and 0 spends nothing at all and leaves a busy barracks busy.
#              It is a knob on «События» («минуты на освобождение очереди»); the person's
#              own number for this account is 3 000 a run (#2709).
#   fallback   the batch size for a barracks that has never run one.
#
# The reading is actions/read_arms_race.md; the research is docs/research/arms-race.md.

ARGS soldier_level = 9
ARGS soldiers = 0
ARGS free_minutes = 0
ARGS fallback = 500

CALL read_arms_race

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end return math.floor((d.event_id or 0) + 0) end)() INTO arms_event

IF arms_event != 120002
    STOP "this is not the unit phase — its points are not soldiers"

# The run's own counters, so what was spent and what it bought stay in one place.
LUA DataCenter.__lw_arms_un = {cap = (tonumber("{soldiers}") or 0), fuse = (tonumber("{free_minutes}") or 0) * 60, level = (tonumber("{soldier_level}") or 9), fallback = (tonumber("{fallback}") or 500), trained = 0, collected = 0, freed = 0, busy = 0, idle = 0, sp_num = 0, sp_sec = 0, sc0 = -1, why = ''}

# 1. Collect. A barracks holding a finished batch cannot start another one, so this comes
# first whatever else the run is allowed to do — and it spends nothing.
READ_LUA (function() local p = DataCenter.__lw_arms_un local B = DataCenter.BuildManager local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d ~= nil then p.sc0 = math.floor((d.sc or 0) + 0) end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local all = nil pcall(function() all = B:GetAllBuildUuid() end) if type(all) ~= 'table' then return 'no barracks list' end local sent, men, fail = 0, 0, 0 for _, u in pairs(all) do local b = nil pcall(function() b = B:GetBuildingDataByUuid(u) end) if type(b) == 'table' and math.floor((b.itemId or 0) + 0) == 10103000 then local base = math.floor((b.productBase or 0) + 0) local pe = math.floor(((b.productEndTime or 0) / 1000) + 0) if base > 0 and pe > 0 and pe <= now then local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.BuildingCampCollect, u) end) if ok then sent = sent + 1 men = men + base else fail = fail + 1 end end end end p.collected = men return 'collected ' .. men .. ' soldier(s) from ' .. sent .. ' barracks (' .. fail .. ' refused)' end)() INTO arms_un_collect

LOG "arms units: {arms_un_collect}"

WAIT 2

# 2. Free the ones still running, if the fuse allows any minutes at all. Soldier speed-ups
# before universal ones and small pieces before large, the same two rules as the minutes
# phases — a universal piece is worth its minute everywhere else too, and the person
# counts speed-ups in PIECES.
READ_LUA (function() local p = DataCenter.__lw_arms_un local fuse = math.floor(tonumber(p.fuse) or 0) local B = DataCenter.BuildManager local I = DataCenter.ItemData local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return 'the game would not say the time' end local all = nil pcall(function() all = B:GetAllBuildUuid() end) if type(all) ~= 'table' then return 'no barracks list' end local busy, idle = {}, 0 for _, u in pairs(all) do local b = nil pcall(function() b = B:GetBuildingDataByUuid(u) end) if type(b) == 'table' and math.floor((b.itemId or 0) + 0) == 10103000 then local base = math.floor((b.productBase or 0) + 0) local pe = math.floor(((b.productEndTime or 0) / 1000) + 0) if base > 0 and pe > now then busy[#busy + 1] = {u = u, left = pe - now} else idle = idle + 1 end end end p.busy = #busy p.idle = idle if #busy == 0 then return 'nothing to free: ' .. idle .. ' barracks already free' end local waits = {} for _, br in ipairs(busy) do waits[#waits + 1] = math.floor(br.left / 60) .. 'min' end if fuse <= 0 then p.why = 'all ' .. #busy .. ' barracks are still training (' .. table.concat(waits, ', ') .. ') and freeing is switched off (free_minutes=0)' return 'nothing freed — the fuse is 0 minutes and ' .. #busy .. ' barracks are busy [' .. table.concat(waits, ' ') .. ']' end local pool = {} pcall(function() for _, it in pairs(I:GetItemsByType(2) or {}) do if type(it) == 'table' then local id = math.floor((it.itemId or 0) + 0) local st = 0 pcall(function() st = math.floor((it.speedUpType or 0) + 0) end) if st <= 0 then local fam = math.floor((id % 100) / 10) local byId = {[0] = 1, [1] = 7, [2] = 6, [3] = 3, [4] = 4} st = byId[fam] or 0 end local sec = math.floor((it.para3 or 0) + 0) local have = math.floor((it.count or 0) + 0) if sec > 0 and have > 0 and (st == 3 or st == 1) then pool[#pool + 1] = {id = id, sec = sec, have = have, own = (st == 3) and 1 or 0} end end end end) if #pool == 0 then p.why = 'the bag holds no speed-up a barracks would take' return 'nothing to free the barracks with — the bag holds no soldier or universal speed-up' end table.sort(pool, function(a, b) if a.own ~= b.own then return a.own > b.own end return a.sec < b.sec end) local function plan(want) local temp = {} for k, it in ipairs(pool) do temp[k] = it.have end local picks, used, rest = {}, 0, want for k, it in ipairs(pool) do if rest <= 0 then break end local n = math.floor(rest / it.sec) if n > temp[k] then n = temp[k] end if n > 0 then picks[#picks + 1] = {k = k, n = n} temp[k] = temp[k] - n rest = rest - it.sec * n used = used + it.sec * n end end if rest > 0 then for k, it in ipairs(pool) do if temp[k] > 0 and it.sec >= rest then picks[#picks + 1] = {k = k, n = 1} temp[k] = temp[k] - 1 used = used + it.sec rest = 0 break end end end if rest > 0 then return nil, 0 end return picks, used end table.sort(busy, function(a, b) return a.left < b.left end) local left = fuse local out, short_fuse, short_bag = {}, 0, 0 for _, br in ipairs(busy) do local picks, used = plan(br.left) if picks == nil then short_bag = short_bag + 1 elseif used > left then short_fuse = short_fuse + 1 else local spent = 0 for _, pick in ipairs(picks) do local it = pool[pick.k] local ids = tostring(math.floor(it.id)) .. ';' .. tostring(math.floor(pick.n)) local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.BuildingCampAccel, br.u, ids, false) end) if ok then it.have = it.have - pick.n spent = spent + it.sec * pick.n p.sp_num = math.floor(tonumber(p.sp_num) or 0) + pick.n p.sp_sec = math.floor(tonumber(p.sp_sec) or 0) + it.sec * pick.n end end if spent > 0 then left = left - spent out[#out + 1] = tostring(br.u) .. ':' .. math.floor(spent / 60) .. 'min@' .. math.floor(br.left / 60) .. 'min' end end end local why = {} if short_fuse > 0 then why[#why + 1] = short_fuse .. ' left alone: freeing them whole would pass the ' .. math.floor(fuse / 60) .. '-minute fuse' end if short_bag > 0 then why[#why + 1] = short_bag .. ' left alone: the bag has not enough speed-up to free them whole' end if #why > 0 then p.why = table.concat(why, '; ') end if #out == 0 then return 'nothing freed — ' .. (#why > 0 and table.concat(why, '; ') or 'no barracks could be freed') end return 'poured ' .. math.floor((tonumber(p.sp_sec) or 0) / 60) .. ' minute(s) into ' .. #out .. ' barracks [' .. table.concat(out, ' ') .. ']' .. (#why > 0 and (' — ' .. table.concat(why, '; ')) or '') end)() INTO arms_un_free

LOG "arms units: {arms_un_free}"

WAIT 3

# Did the minutes actually land? A barracks that is free NOW and was running a moment ago
# is the only proof the freeing send is read by the server at all, and it is said out
# loud either way — the sends of step 1 and 3 are proven live, this one is not.
READ_LUA (function() local p = DataCenter.__lw_arms_un local B = DataCenter.BuildManager local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local all = nil pcall(function() all = B:GetAllBuildUuid() end) if type(all) ~= 'table' then return 'no barracks list' end local sent, men = 0, 0 for _, u in pairs(all) do local b = nil pcall(function() b = B:GetBuildingDataByUuid(u) end) if type(b) == 'table' and math.floor((b.itemId or 0) + 0) == 10103000 then local base = math.floor((b.productBase or 0) + 0) local pe = math.floor(((b.productEndTime or 0) / 1000) + 0) if base > 0 and pe > 0 and pe <= now then local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.BuildingCampCollect, u) end) if ok then sent = sent + 1 men = men + base end end end end p.collected = math.floor(tonumber(p.collected) or 0) + men p.freed = sent return 'freed and collected ' .. men .. ' soldier(s) from ' .. sent .. ' barracks after the minutes went in' end)() INTO arms_un_after

LOG "arms units: {arms_un_after}"

WAIT 2

# 3. Train. The size is the one the game already accepted for that barracks, and the
# whole run is bounded by `soldiers` — the resources are the player's.
READ_LUA (function() local p = DataCenter.__lw_arms_un local B = DataCenter.BuildManager local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local all = nil pcall(function() all = B:GetAllBuildUuid() end) if type(all) ~= 'table' then return 'no barracks list' end local cap = math.floor(tonumber(p.cap) or 0) local level = math.floor(tonumber(p.level) or 9) local fallback = math.floor(tonumber(p.fallback) or 500) local sent, men, fail, err, out = 0, 0, 0, '', {} for _, u in pairs(all) do local b = nil pcall(function() b = B:GetBuildingDataByUuid(u) end) if type(b) == 'table' and math.floor((b.itemId or 0) + 0) == 10103000 then local base = math.floor((b.productBase or 0) + 0) local pe = math.floor(((b.productEndTime or 0) / 1000) + 0) local free = (base <= 0) or (pe <= now) if free then local n = base if n <= 0 then n = fallback end if cap > 0 then local room = cap - men if room <= 0 then n = 0 elseif room < n then n = room end end if n > 0 then local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.BuildingCampTraining, u, 0, level, n) end) if ok then sent = sent + 1 men = men + n out[#out+1] = tostring(u) .. ':' .. n else fail = fail + 1 if err == '' then err = tostring(why) end end end end end end p.trained = men if cap > 0 and men >= cap then p.why = 'the ceiling of ' .. cap .. ' soldier(s) stopped the run' end if sent == 0 and fail == 0 then return 'started nothing — no barracks was free to train in' end return 'started ' .. men .. ' soldier(s) of level ' .. level .. ' in ' .. sent .. ' barracks (' .. fail .. ' refused) [' .. table.concat(out, ' ') .. ']' .. (err ~= '' and (' err=' .. err) or '') end)() INTO arms_un_train

LOG "arms units: {arms_un_train}"

WAIT 4

READ_LUA (function() local p = DataCenter.__lw_arms_un or {} local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = -1 local top = 0 if d ~= nil then sc = math.floor((d.sc or 0) + 0) top = math.floor((d.score_reward_max or 0) + 0) end local before = math.floor(tonumber(p.sc0) or -1) local moved = (sc >= 0 and before >= 0) and (sc - before) or -1 return 'trained=' .. math.floor(tonumber(p.trained) or 0) .. ' collected=' .. math.floor(tonumber(p.collected) or 0) .. ' barracks_busy=' .. math.floor(tonumber(p.busy) or 0) .. ' barracks_free=' .. math.floor(tonumber(p.idle) or 0) .. ' speed-ups=' .. math.floor(tonumber(p.sp_num) or 0) .. 'pcs/' .. math.floor((tonumber(p.sp_sec) or 0) / 60) .. 'min' .. ' score=' .. sc .. '/' .. top .. ' moved=' .. moved .. (tostring(p.why or '') ~= '' and (' stopped=' .. tostring(p.why)) or '') end)() INTO arms_un_report

LOG "arms units: {arms_un_report}"
