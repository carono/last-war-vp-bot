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
#      SOLDIER ones before universal, small pieces before large, under the `minutes`
#      fuse. This is the only part of the run that touches the bag.
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
#              by default, and 0 spends nothing at all and leaves a busy barracks busy —
#              the freeing send is the one shape here that has not been seen live, so it
#              is asked for rather than assumed. The panel does not offer it as a knob
#              yet for the same reason; run this recipe directly to try it.
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
LUA DataCenter.__lw_arms_un = {cap = (tonumber("{soldiers}") or 0), fuse = (tonumber("{free_minutes}") or 0) * 60, level = (tonumber("{soldier_level}") or 9), fallback = (tonumber("{fallback}") or 500), trained = 0, collected = 0, freed = 0, sp_num = 0, sp_sec = 0, sc0 = -1, why = ''}

# 1. Collect. A barracks holding a finished batch cannot start another one, so this comes
# first whatever else the run is allowed to do — and it spends nothing.
READ_LUA (function() local p = DataCenter.__lw_arms_un local B = DataCenter.BuildManager local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d ~= nil then p.sc0 = math.floor((d.sc or 0) + 0) end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local all = nil pcall(function() all = B:GetAllBuildUuid() end) if type(all) ~= 'table' then return 'no barracks list' end local sent, men, fail = 0, 0, 0 for _, u in pairs(all) do local b = nil pcall(function() b = B:GetBuildingDataByUuid(u) end) if type(b) == 'table' and math.floor((b.itemId or 0) + 0) == 10103000 then local base = math.floor((b.productBase or 0) + 0) local pe = math.floor(((b.productEndTime or 0) / 1000) + 0) if base > 0 and pe > 0 and pe <= now then local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.BuildingCampCollect, u) end) if ok then sent = sent + 1 men = men + base else fail = fail + 1 end end end end p.collected = men return 'collected ' .. men .. ' soldier(s) from ' .. sent .. ' barracks (' .. fail .. ' refused)' end)() INTO arms_un_collect

LOG "arms units: {arms_un_collect}"

WAIT 2

# 2. Free the ones still running, if the fuse allows any minutes at all. Soldier speed-ups
# before universal ones and small pieces before large, the same two rules as the minutes
# phases — a universal piece is worth its minute everywhere else too, and the person
# counts speed-ups in PIECES.
READ_LUA (function() local p = DataCenter.__lw_arms_un local fuse = math.floor(tonumber(p.fuse) or 0) if fuse <= 0 then p.why = 'no minutes allowed, so a busy barracks stays busy' return 'no barracks freed — the fuse is 0 minutes' end local B = DataCenter.BuildManager local I = DataCenter.ItemData local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return 'the game would not say the time' end local all = nil pcall(function() all = B:GetAllBuildUuid() end) if type(all) ~= 'table' then return 'no barracks list' end local pool = {} pcall(function() for _, it in pairs(I:GetItemsByType(2) or {}) do if type(it) == 'table' then local id = math.floor((it.itemId or 0) + 0) local st = 0 pcall(function() st = math.floor((it.speedUpType or 0) + 0) end) if st <= 0 then local fam = math.floor((id % 100) / 10) local byId = {[0] = 1, [1] = 7, [2] = 6, [3] = 3, [4] = 4} st = byId[fam] or 0 end local sec = math.floor((it.para3 or 0) + 0) local have = math.floor((it.count or 0) + 0) if sec > 0 and have > 0 and (st == 3 or st == 1) then pool[#pool + 1] = {id = id, sec = sec, have = have, own = (st == 3) and 1 or 0} end end end end) if #pool == 0 then p.why = 'the bag holds no speed-up a barracks would take' return 'nothing to free the barracks with' end table.sort(pool, function(a, b) if a.own ~= b.own then return a.own > b.own end return a.sec < b.sec end) local left = fuse local out = {} for _, u in pairs(all) do local b = nil pcall(function() b = B:GetBuildingDataByUuid(u) end) if type(b) == 'table' and math.floor((b.itemId or 0) + 0) == 10103000 and left > 0 then local base = math.floor((b.productBase or 0) + 0) local pe = math.floor(((b.productEndTime or 0) / 1000) + 0) if base > 0 and pe > now then local want = pe - now if want > left then want = left end local before = pe - now local spent = 0 for _, it in ipairs(pool) do if want <= 0 then break end if it.sec <= want and it.have > 0 then local n = math.floor(want / it.sec) if n > it.have then n = it.have end if n > 0 then local ids = tostring(math.floor(it.id)) .. ';' .. tostring(math.floor(n)) local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.BuildingCampAccel, u, ids, false) end) if ok then it.have = it.have - n want = want - it.sec * n spent = spent + it.sec * n left = left - it.sec * n p.sp_num = math.floor(tonumber(p.sp_num) or 0) + n p.sp_sec = math.floor(tonumber(p.sp_sec) or 0) + it.sec * n end end end end if spent > 0 then out[#out+1] = tostring(u) .. ':' .. math.floor(spent / 60) .. 'min@' .. before .. 's' end end end end if #out == 0 then return 'no barracks needed freeing, or none could be' end return 'poured ' .. math.floor((tonumber(p.sp_sec) or 0) / 60) .. ' minute(s) into ' .. #out .. ' barracks [' .. table.concat(out, ' ') .. ']' end)() INTO arms_un_free

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
READ_LUA (function() local p = DataCenter.__lw_arms_un local B = DataCenter.BuildManager local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local all = nil pcall(function() all = B:GetAllBuildUuid() end) if type(all) ~= 'table' then return 'no barracks list' end local cap = math.floor(tonumber(p.cap) or 0) local level = math.floor(tonumber(p.level) or 9) local fallback = math.floor(tonumber(p.fallback) or 500) local sent, men, fail, err, out = 0, 0, 0, '', {} for _, u in pairs(all) do local b = nil pcall(function() b = B:GetBuildingDataByUuid(u) end) if type(b) == 'table' and math.floor((b.itemId or 0) + 0) == 10103000 then local base = math.floor((b.productBase or 0) + 0) local pe = math.floor(((b.productEndTime or 0) / 1000) + 0) local free = (base <= 0) or (pe <= now) if free then local n = base if n <= 0 then n = fallback end if cap > 0 then local room = cap - men if room <= 0 then n = 0 elseif room < n then n = room end end if n > 0 then local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.BuildingCampTraining, u, 0, level, n) end) if ok then sent = sent + 1 men = men + n out[#out+1] = tostring(u) .. ':' .. n else fail = fail + 1 if err == '' then err = tostring(why) end end end end end end p.trained = men if cap > 0 and men >= cap then p.why = 'the ceiling of ' .. cap .. ' soldier(s) stopped the run' end return 'started ' .. men .. ' soldier(s) of level ' .. level .. ' in ' .. sent .. ' barracks (' .. fail .. ' refused) [' .. table.concat(out, ' ') .. ']' .. (err ~= '' and (' err=' .. err) or '') end)() INTO arms_un_train

LOG "arms units: {arms_un_train}"

WAIT 4

READ_LUA (function() local p = DataCenter.__lw_arms_un or {} local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = -1 local top = 0 if d ~= nil then sc = math.floor((d.sc or 0) + 0) top = math.floor((d.score_reward_max or 0) + 0) end local before = math.floor(tonumber(p.sc0) or -1) local moved = (sc >= 0 and before >= 0) and (sc - before) or -1 return 'trained=' .. math.floor(tonumber(p.trained) or 0) .. ' collected=' .. math.floor(tonumber(p.collected) or 0) .. ' speed-ups=' .. math.floor(tonumber(p.sp_num) or 0) .. 'pcs/' .. math.floor((tonumber(p.sp_sec) or 0) / 60) .. 'min' .. ' score=' .. sc .. '/' .. top .. ' moved=' .. moved .. (tostring(p.why or '') ~= '' and (' stopped=' .. tostring(p.why)) or '') end)() INTO arms_un_report

LOG "arms units: {arms_un_report}"
