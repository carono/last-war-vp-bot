# Spend the survivor recruit tickets in the tavern — the duel's Tuesday.
# ru: Потратить билеты выжившего в таверне — вторник дуэли.
#
# WHAT IT SPENDS, said plainly because it cannot be taken back: the account's SURVIVOR
# RECRUIT TICKETS, and the banner's free pull when one is waiting. Nothing else — no
# diamonds, no daily quota, no march. `keep` is how many tickets to leave untouched, and
# a run that would go below it stops instead.
#
# WHY: the duel's Tuesday pays for recruiting survivors, and a ticket held back on a
# Tuesday is a ticket that scores nothing (the person's words, #2632: «тратить билеты
# выжившего (это найм в таверне)»).
#
# HOW IT PULLS. The free pull first, because it is free and it is one pull; then tens
# while ten are affordable, then ones for the remainder. Each pull is the same single
# message `recruit_draw.md` sends (`lottery.worker.card` — the client's own recruit
# screen ends at exactly that one, docs/research/recruit-draw.md), so no window is
# opened at any point. Ten at a time rather than one is not cheaper in tickets — it is
# cheaper in PRESSES: a press is a thread hijack into the client and the machine makes
# about 1.4 of them a second in total (docs/research/link-contention.md).
#
# WHAT IT REPORTS. `tickets_before`, `tickets_after` and `tickets_spent` — the panel's
# «сколько потратили сегодня» is its own tally of that last number, because a ticket that
# is spent is gone and the count of them exists nowhere but in the panel.

# HOW MANY TO LEAVE. The tickets this run must not touch.
ARGS keep = 0

# HOW MANY PULLS A PAID PRESS BUYS while that many are affordable: 10 or 1.
ARGS batch = 10

# The banner is fixed: this recipe is about the survivors. `free = no` on the paid
# presses, because the free pull is taken once, deliberately, at the top.
LUA DataCenter.__lw_recruit_kind = 'worker' DataCenter.__lw_recruit_lottery = '' DataCenter.__lw_worker_keep = math.floor(tonumber('{keep}') or 0) DataCenter.__lw_worker_batch = math.floor(tonumber('{batch}') or 10)

READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return -1 end local n = -1 pcall(function() local c = (wl:GetCostItems() or {})[1] local it = DataCenter.ItemData:GetItemById(c.itemId) n = math.floor(tonumber(it and it.count) or 0) end) return n end)() INTO tickets_before
LOG "survivor tickets on hand: {tickets_before}"

IF tickets_before < 0
    FAIL "the client would not answer for the survivors' banner — nothing was sent"

PARK tickets_before INTO DataCenter.__lw_worker_before

# 1. The free pull, if the banner has one waiting. «only» sends nothing when it has not.
READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local free = 0 pcall(function() free = wl:CanFreeRecruit() and 1 or 0 end) return free end)() INTO free_pull

IF free_pull == 1
    LUA DataCenter.__lw_recruit_count = 1 DataCenter.__lw_recruit_free = 'only'
    TAP recruit_draw
    WAIT 1

# 2. The paid pulls, `batch` at a time while `batch` are still affordable above `keep`.
LUA DataCenter.__lw_recruit_free = 'no' DataCenter.__lw_recruit_count = DataCenter.__lw_worker_batch

READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local have, cost = 0, 0 pcall(function() local list = wl:GetCostItems() or {} local slot = (math.floor(tonumber(DataCenter.__lw_worker_batch) or 10) == 1) and 1 or 2 local c = list[slot] or list[1] cost = math.floor(tonumber(c.itemNum) or 0) local it = DataCenter.ItemData:GetItemById(c.itemId) have = math.floor(tonumber(it and it.count) or 0) end) local keep = math.floor(tonumber(DataCenter.__lw_worker_keep) or 0) if cost <= 0 then return 0 end if have - keep >= cost then return 1 end return 0 end)() INTO can_pull

WHILE can_pull == 1 LIMIT 20
    TAP recruit_draw
    WAIT 1
    READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local have, cost = 0, 0 pcall(function() local list = wl:GetCostItems() or {} local slot = (math.floor(tonumber(DataCenter.__lw_worker_batch) or 10) == 1) and 1 or 2 local c = list[slot] or list[1] cost = math.floor(tonumber(c.itemNum) or 0) local it = DataCenter.ItemData:GetItemById(c.itemId) have = math.floor(tonumber(it and it.count) or 0) end) local keep = math.floor(tonumber(DataCenter.__lw_worker_keep) or 0) if cost <= 0 then return 0 end if have - keep >= cost then return 1 end return 0 end)() INTO can_pull

# 3. …and the remainder, one at a time, when the batch was ten.
LUA DataCenter.__lw_recruit_count = 1 DataCenter.__lw_worker_batch = 1

READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local have, cost = 0, 0 pcall(function() local c = (wl:GetCostItems() or {})[1] cost = math.floor(tonumber(c.itemNum) or 0) local it = DataCenter.ItemData:GetItemById(c.itemId) have = math.floor(tonumber(it and it.count) or 0) end) local keep = math.floor(tonumber(DataCenter.__lw_worker_keep) or 0) if cost <= 0 then return 0 end if have - keep >= cost then return 1 end return 0 end)() INTO can_one

WHILE can_one == 1 LIMIT 9
    TAP recruit_draw
    WAIT 1
    READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local have, cost = 0, 0 pcall(function() local c = (wl:GetCostItems() or {})[1] cost = math.floor(tonumber(c.itemNum) or 0) local it = DataCenter.ItemData:GetItemById(c.itemId) have = math.floor(tonumber(it and it.count) or 0) end) local keep = math.floor(tonumber(DataCenter.__lw_worker_keep) or 0) if cost <= 0 then return 0 end if have - keep >= cost then return 1 end return 0 end)() INTO can_one

# 4. What the run cost, in the account's own numbers.
READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return -1 end local n = -1 pcall(function() local c = (wl:GetCostItems() or {})[1] local it = DataCenter.ItemData:GetItemById(c.itemId) n = math.floor(tonumber(it and it.count) or 0) end) return n end)() INTO tickets_after

READ_LUA (function() local before = math.floor(tonumber(DataCenter.__lw_worker_before) or 0) local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local n = before pcall(function() local c = (wl:GetCostItems() or {})[1] local it = DataCenter.ItemData:GetItemById(c.itemId) n = math.floor(tonumber(it and it.count) or 0) end) local spent = before - n if spent < 0 then spent = 0 end return spent end)() INTO tickets_spent

LOG "tickets: {tickets_before} -> {tickets_after}, spent {tickets_spent}"
