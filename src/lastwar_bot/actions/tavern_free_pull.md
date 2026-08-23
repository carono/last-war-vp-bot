# Take the recruit banners' free pulls — the free hero and the free survivor.
# ru: Таверна: забрать бесплатного героя и бесплатного жителя.
#
# It also books its own next turn: see step 4 below.
#
# «Найм» is two banners and each has ONE free pull on a clock of its own: the hero
# banner's refreshes daily, the survivors' runs on a timer of its own
# (docs/research/recruit-draw.md §3). Both are simply lost if nobody spends them, which
# is what makes this an errand for a clock rather than for a person.
#
# The whole ability is a reading, at most two sends and one number:
#
#   1. can the client answer for the banners at all — a client that is not logged in
#      answers «no free pull» to every question with a perfectly straight face
#      (a FAIL here, so the timer retries in minutes instead of sitting out an hour
#      over a reading nobody made);
#   2. the hero banner's own `CanFreeRecruit()`, and its pull if it says yes;
#   3. the survivors' own `CanFreeRecruit()`, and its pull if it says yes;
#   4. WHEN THE NEXT FREE PULL IS, in seconds, taken as the NEARER of the two clocks —
#      and left in `next_run_in`, which is what the panel's schedule books this errand's
#      next turn with (`panel/timers.py`, `NEXT_RUN_VAR`). An hourly row would look
#      fifty times for nothing and still be late; the game already knows the answer.
#
# The gate is never re-implemented here. Both `CanFreeRecruit()` calls are the CLIENT'S
# OWN, in the client's own units — a copy of that arithmetic is one build away from
# disagreeing with what the person sees on the screen, and the panel's copy would be the
# wrong one of the two.
#
# The pull itself is actions/recruit_draw.md, played with `free = only`: it sends
# nothing unless the pull would be free, so a race with a person pulling by hand costs a
# refusal and not somebody's tickets.

# Which banner, and how it is paid for — the arguments recruit_draw reads. They are set
# here rather than passed, because `CALL` carries the caller's variables into the
# sub-recipe and its own `ARGS` fill in only what was left out.
READ_LUA ('only') INTO free

READ_LUA (function() local function heroInfo() local M = DataCenter.LotteryDataManager for _, id in pairs(M.curRecruitIdList or {}) do local ok, v = pcall(function() return M:GetLotteryDataById(id) end) if ok and v ~= nil then return v end end return nil end local function workerInfo() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) return wl end local hi, wl = heroInfo(), workerInfo() return ((hi ~= nil or wl ~= nil) and 1 or 0) end)() INTO ready

IF ready == 0
    FAIL "the client cannot answer for the recruit banners — not logged in yet"

READ_LUA (function() local function heroInfo() local M = DataCenter.LotteryDataManager for _, id in pairs(M.curRecruitIdList or {}) do local ok, v = pcall(function() return M:GetLotteryDataById(id) end) if ok and v ~= nil then return v end end return nil end local function workerInfo() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) return wl end local hi = heroInfo() if hi == nil then return 0 end local sup = 0 pcall(function() sup = hi:IsSupportFreeRecruit() and 1 or 0 end) if sup == 0 then return 0 end local f = 0 pcall(function() f = hi:CanFreeRecruit() and 1 or 0 end) return f end)() INTO hero_free

IF hero_free == 1
    LOG "the hero banner has its free pull — taking it"
    READ_LUA ('hero') INTO kind
    CALL recruit_draw

READ_LUA (function() local function heroInfo() local M = DataCenter.LotteryDataManager for _, id in pairs(M.curRecruitIdList or {}) do local ok, v = pcall(function() return M:GetLotteryDataById(id) end) if ok and v ~= nil then return v end end return nil end local function workerInfo() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) return wl end local wl = workerInfo() if wl == nil then return 0 end local f = 0 pcall(function() f = wl:CanFreeRecruit() and 1 or 0 end) return f end)() INTO worker_free

IF worker_free == 1
    LOG "the survivor banner has its free pull — taking it"
    READ_LUA ('worker') INTO kind
    CALL recruit_draw

# …and when to come back: the NEARER of the two banners' own next-free times, in seconds
# from now, with a minute's margin so a run that lands a heartbeat early does not read
# «not yet» and book itself another whole wait. `0` — nothing readable — leaves the row's
# own period to decide, which is the safe way for this to fail.
READ_LUA (function() local function heroInfo() local M = DataCenter.LotteryDataManager for _, id in pairs(M.curRecruitIdList or {}) do local ok, v = pcall(function() return M:GetLotteryDataById(id) end) if ok and v ~= nil then return v end end return nil end local function workerInfo() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) return wl end local function secs(v) local n = tonumber(v) or 0 if n > 100000000000 then n = n / 1000 end return math.floor(n) end local now = 0 pcall(function() now = math.floor(tonumber(UITimeManager:GetInstance():GetServerSeconds()) or 0) end) if now <= 0 then return 0 end local best = 0 local function want(d) if d > 0 and (best == 0 or d < best) then best = d end end local hi = heroInfo() if hi ~= nil then local sup = 0 pcall(function() sup = hi:IsSupportFreeRecruit() and 1 or 0 end) local free = 0 pcall(function() free = hi:CanFreeRecruit() and 1 or 0 end) if sup == 1 and free == 0 then want(secs(hi.dailyFreeNextFreshTime) - now) end end local wl = workerInfo() if wl ~= nil then local free = 0 pcall(function() free = wl:CanFreeRecruit() and 1 or 0 end) if free == 0 then want(secs(wl.nextFreeTime) - now) end end if best == 0 then return 0 end return best + 60 end)() INTO next_run_in

LOG "the next free pull is what «next_run_in» says, in seconds (0 = the row's period stands)"
