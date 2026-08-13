# One pull on a recruit banner — heroes or survivors, x1 / x10 / x100.
# ru: Один найм — герои или выжившие, x1 / x10 / x100.
#
#   run recruit_draw {"kind": "hero", "count": 10}
#   run recruit_draw {"kind": "worker", "count": 1, "free": "only"}
#
# ONE MESSAGE, NO WINDOW. The game's own recruit screen ends at a single send and this
# recipe sends the same one, read off the player pulling by hand (run 20260813_103441)
# and confirmed field by field in the client:
#
#     lottery.hero.card    {id, isTen, useFree}   + the ticket the pull is paid in
#     lottery.worker.card  {useFree, isTen, officerId}
#
# `isTen` IS A SIZE, NOT A FLAG — 0 for one, 1 for ten, 2 for a hundred. The recording
# only ever carried 0 and 1, so a x100 button had nothing to send; the value comes from
# the client's own `UIHeroMultiRecruitType = { Ten = 1, OneHundred = 2 }`, which is what
# the game's own view picks it with. Derived from the game's table, not guessed off two
# samples.

# Which banner: `hero` (герои) or `worker` (выжившие).
ARGS kind = hero

# How many pulls this press buys: 1, 10 or 100. Anything else is refused with a line
# saying so rather than sent as something else.
ARGS count = 1

# What to do about the FREE pull, which each banner has one of:
#
#   auto — spend it when there is one and `count` is 1 (a free pull is a single pull);
#   no   — never spend it, pay in tickets;
#   only — send NOTHING unless the pull would be free. This is the setting a standing
#          order wants: it can run every hour all day and only ever costs the free one.
ARGS free = auto

# Which hero banner, when the account is offered several. Empty means the one the client
# itself is showing — the first of its own current recruit ids that resolves.
ARGS lottery =

# The press carries no arguments of its own, so what this run is about is parked where
# the press reads it — the same shape `join_rally.md` parks its squads in.
LUA DataCenter.__lw_recruit_kind = "{kind}" DataCenter.__lw_recruit_count = tonumber("{count}") or 1 DataCenter.__lw_recruit_free = "{free}" DataCenter.__lw_recruit_lottery = "{lottery}"

# The pull. The button verifies itself: a paid pull moves the ticket count, a free one
# flips the banner's own free gate, and a press the server ignored moves neither and
# fails here rather than reporting a success nobody got heroes from.
TAP recruit_draw

# …and what it decided, in its own words — the banner, the size, whether the free pull
# was spent, what it cost and what was held. A refusal is a REPORT and not a silence:
# not enough tickets, «only free» with no free pull, a count that is not 1/10/100, a
# client with no banner loaded each say which of them it was.
READ_LUA (DataCenter.__lw_recruit_report or 'the pull left no report — the press did not run') INTO report

LOG "the line above is what the pull did"

READ_LUA (tonumber(DataCenter.__lw_recruit_sent) or 0) INTO sent

IF sent == 0
    FAIL "nothing was sent — the reason is on the «report» line above"

# …and, for a pull that DID leave, whether the game caught up with it. A send the server
# drops returns as cleanly as one it takes (`docs/skills/sniff.md` §8.0a), so the proof
# is the account's own state moving: the tickets go down, or the free pull's gate closes.
# Read only now, after `sent` — a press that refused on purpose has nothing to catch up
# with, and waiting on it would bury a refusal under «nothing moved».
READ_LUA ((DataCenter.__lw_recruit_before ~= nil and ((function() local function heroInfo() local M = DataCenter.LotteryDataManager local want = tostring(DataCenter.__lw_recruit_lottery or '') if want ~= '' then local ok, v = pcall(function() return M:GetLotteryDataById(want) end) if ok and v ~= nil then return v, want end ok, v = pcall(function() return M:GetLotteryDataById(tonumber(want)) end) if ok and v ~= nil then return v, want end return nil, want end for _, id in pairs(M.curRecruitIdList or {}) do local ok, v = pcall(function() return M:GetLotteryDataById(id) end) if ok and v ~= nil then return v, tostring(id) end end return nil, '' end local function workerInfo() local M = DataCenter.LotteryDataManager local cfg, wl = nil, nil pcall(function() cfg = M:GetOnlyWorkerLotteryData() end) pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) return wl, cfg end local function costOf(info, size) local id, num = '', 0 pcall(function() if size == 2 then local c = info:GetHundredCost() if c ~= nil then id = c.itemId num = tonumber(c.itemNum) or 0 end else local list = info:GetCostItems() or {} local c = list[size + 1] if c ~= nil then id = c.itemId num = tonumber(c.itemNum) or 0 end end end) return id, num end local function have(itemId) local n = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(itemId) n = tonumber(it and it.count) or 0 end) return n end local kind = tostring(DataCenter.__lw_recruit_kind or 'hero') local info = nil if kind == 'worker' then info = (workerInfo()) else info = (heroInfo()) end if info == nil then return -1 end local itemId = 0 pcall(function() itemId = (costOf(info, 0)) end) local free = 0 pcall(function() free = info:CanFreeRecruit() and 1 or 0 end) return have(itemId) * 2 + free end)()) ~= DataCenter.__lw_recruit_before) and 1 or 0) INTO moved

WHILE moved == 0 LIMIT 6
    WAIT 0.5
    READ_LUA ((DataCenter.__lw_recruit_before ~= nil and ((function() local function heroInfo() local M = DataCenter.LotteryDataManager local want = tostring(DataCenter.__lw_recruit_lottery or '') if want ~= '' then local ok, v = pcall(function() return M:GetLotteryDataById(want) end) if ok and v ~= nil then return v, want end ok, v = pcall(function() return M:GetLotteryDataById(tonumber(want)) end) if ok and v ~= nil then return v, want end return nil, want end for _, id in pairs(M.curRecruitIdList or {}) do local ok, v = pcall(function() return M:GetLotteryDataById(id) end) if ok and v ~= nil then return v, tostring(id) end end return nil, '' end local function workerInfo() local M = DataCenter.LotteryDataManager local cfg, wl = nil, nil pcall(function() cfg = M:GetOnlyWorkerLotteryData() end) pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) return wl, cfg end local function costOf(info, size) local id, num = '', 0 pcall(function() if size == 2 then local c = info:GetHundredCost() if c ~= nil then id = c.itemId num = tonumber(c.itemNum) or 0 end else local list = info:GetCostItems() or {} local c = list[size + 1] if c ~= nil then id = c.itemId num = tonumber(c.itemNum) or 0 end end end) return id, num end local function have(itemId) local n = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(itemId) n = tonumber(it and it.count) or 0 end) return n end local kind = tostring(DataCenter.__lw_recruit_kind or 'hero') local info = nil if kind == 'worker' then info = (workerInfo()) else info = (heroInfo()) end if info == nil then return -1 end local itemId = 0 pcall(function() itemId = (costOf(info, 0)) end) local free = 0 pcall(function() free = info:CanFreeRecruit() and 1 or 0 end) return have(itemId) * 2 + free end)()) ~= DataCenter.__lw_recruit_before) and 1 or 0) INTO moved

IF moved == 0
    FAIL "the pull was sent and nothing about the account changed — the game did not take it; the «report» line above says what went out"

LOG "the pull landed — the tickets or the free pull moved"
