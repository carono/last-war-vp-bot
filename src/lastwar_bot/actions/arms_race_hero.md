# «Гонка вооружений», фаза «Улучшение героя» — hire in the tavern until the top box.
# ru: «Гонка вооружений», фаза «Улучшение героя» — нанимать в таверне до верхней коробки.
#
# THIS SPENDS THE PLAYER'S RECRUIT TICKETS. It has two ceilings and it stops at
# whichever it reaches first — the phase's top point target, and `pulls`, the number of
# hires the person allowed. It never pays in diamonds: a hire the tickets will not cover
# is not made, and the run says so instead of quietly buying one.
#
# The phase pays 400 points for one hire (the game's `score` rule 122), and the top box
# of this phase wants 12 000 — so thirty hires is exactly the top box, which is the
# number the person named. The recipe does NOT write 400 or 12 000 down: both are read
# off the live event every round, because a phase whose numbers moved would otherwise be
# ground at with last week's arithmetic.
#
# It refuses politely rather than failing when there is nothing to do: a phase of
# another kind, an event that is not running, the top box already taken, or no tickets
# left all end the run with a line saying which.
#
# ## Arguments
#
#   pulls   the most hires this run may make. 30 is the top box exactly.
#   free    what to do with the banner's one free hire — `auto` spends it, `no` keeps
#           it, `only` makes the run cost nothing at all.
#
# The hire itself is actions/recruit_draw.md's press, parked and pressed here directly
# so that the ceiling is decided against the LIVE score between one hire and the next.
# The reading is actions/read_arms_race.md; the research is docs/research/arms-race.md.

ARGS pulls = 30
ARGS free = auto

CALL read_arms_race

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end return math.floor(tonumber(d.event_id) or 0) end)() INTO arms_event

IF arms_event != 120000
    STOP "not the hero phase — the event running now is {arms_event}"

# The counter this run spends its allowance out of. Parked in the VM beside the hire's
# own arguments, so the two are read in the same place and cannot drift apart.
LUA DataCenter.__lw_arms_spent = 0 DataCenter.__lw_arms_cap = tonumber("{pulls}") or 0 DataCenter.__lw_recruit_kind = "hero" DataCenter.__lw_recruit_free = "{free}" DataCenter.__lw_recruit_lottery = ""

# How big the next hire may be — 10, 1, or 0 for «stop». Everything the decision needs
# is read in ONE call: the points still owed, the allowance still unspent, and whether
# the bag can actually pay for what that comes to.
READ_LUA (function() local v = (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end local sc = math.floor(tonumber(d.sc) or 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor(tonumber(b.target) or 0) if t > top then top = t end end end) local per = 0 pcall(function() local inst = LocalController.instance() local n = inst:GetTableLength('score') for _, want in pairs(d.scoresList or {}) do local w = math.floor(tonumber(want) or 0) for i = 1, n do local row = inst:getLine('score', i) if row and math.floor(tonumber(row:getValue('id')) or 0) == w then local ty = math.floor(tonumber(row:getValue('type')) or 0) if ty == 42 then per = math.floor(tonumber(row:getValue('points')) or 0) end break end end if per > 0 then break end end end) if per <= 0 then per = 400 end local owed = top - sc if owed <= 0 then return 0 end local want = math.ceil(owed / per) local left = (math.floor(tonumber(DataCenter.__lw_arms_cap) or 0)) - (math.floor(tonumber(DataCenter.__lw_arms_spent) or 0)) if left < want then want = left end if want <= 0 then return 0 end local info = nil pcall(function() local L = DataCenter.LotteryDataManager for _, id in pairs(L.curRecruitIdList or {}) do local ok, v = pcall(function() return L:GetLotteryDataById(id) end) if ok and v ~= nil then info = v break end end end) if info == nil then return 0 end local freeNow = false pcall(function() freeNow = info:CanFreeRecruit() and true or false end) local function cost(size) local id, num = 0, 0 pcall(function() local list = info:GetCostItems() or {} local c = list[size + 1] if c ~= nil then id = math.floor(tonumber(c.itemId) or 0) num = math.floor(tonumber(c.itemNum) or 0) end end) return id, num end local id1, n1 = cost(0) local _, n10 = cost(1) local have = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(id1) have = math.floor(tonumber(it and it.count) or 0) end) if want >= 10 and n10 > 0 and have >= n10 then return 10 end if freeNow then return 1 end if n1 > 0 and have >= n1 then return 1 end return 0 end)() DataCenter.__lw_arms_step = v return v end)() INTO arms_step

IF arms_step == 0
    STOP "nothing to hire — the box is taken, the allowance is spent, or the tickets are out"

WHILE arms_step > 0 LIMIT 31
    LUA DataCenter.__lw_recruit_count = math.floor(tonumber(DataCenter.__lw_arms_step) or 1)
    TAP recruit_draw
    WAIT 1.5
    LUA DataCenter.__lw_arms_spent = (math.floor(tonumber(DataCenter.__lw_arms_spent) or 0)) + (math.floor(tonumber(DataCenter.__lw_recruit_count) or 0))
    READ_LUA (function() local v = (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end local sc = math.floor(tonumber(d.sc) or 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor(tonumber(b.target) or 0) if t > top then top = t end end end) local per = 400 local owed = top - sc if owed <= 0 then return 0 end local want = math.ceil(owed / per) local left = (math.floor(tonumber(DataCenter.__lw_arms_cap) or 0)) - (math.floor(tonumber(DataCenter.__lw_arms_spent) or 0)) if left < want then want = left end if want <= 0 then return 0 end local info = nil pcall(function() local L = DataCenter.LotteryDataManager for _, id in pairs(L.curRecruitIdList or {}) do local ok, v = pcall(function() return L:GetLotteryDataById(id) end) if ok and v ~= nil then info = v break end end end) if info == nil then return 0 end local function cost(size) local id, num = 0, 0 pcall(function() local list = info:GetCostItems() or {} local c = list[size + 1] if c ~= nil then id = math.floor(tonumber(c.itemId) or 0) num = math.floor(tonumber(c.itemNum) or 0) end end) return id, num end local id1, n1 = cost(0) local _, n10 = cost(1) local have = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(id1) have = math.floor(tonumber(it and it.count) or 0) end) if want >= 10 and n10 > 0 and have >= n10 then return 10 end if n1 > 0 and have >= n1 then return 1 end return 0 end)() DataCenter.__lw_arms_step = v return v end)() INTO arms_step

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = 0 if d ~= nil then sc = math.floor(tonumber(d.sc) or 0) end return 'hired=' .. math.floor(tonumber(DataCenter.__lw_arms_spent) or 0) .. ' score=' .. sc end)() INTO arms_hire_report

LOG "arms hero: {arms_hire_report}"
