# Take EVERY free pull the recruit banners are offering — the survivor and each hero banner.
# ru: Таверна: забрать все бесплатные наймы — жителя и каждый баннер героев.
#
# It also books its own next turn: see step 4 below.
#
# «Найм» is the survivors' banner and EVERY hero banner the client is currently showing,
# and each of them has ONE free pull on a clock of its own: a hero banner's refreshes
# daily, the survivors' runs on a timer of its own (docs/research/recruit-draw.md §3).
# All of them are simply lost if nobody spends them, which is what makes this an errand
# for a clock rather than for a person.
#
# THERE IS MORE THAN ONE HERO BANNER, and that is what #2074 was about. The account this
# was read on shows three at once — the standing one and two seasonal ones, each with its
# own ticket and its own free pull — and this errand used to take «the first id of
# `curRecruitIdList` that resolves» and stop there, so two free pulls a day were lost
# every day while the run reported a clean success. Nothing about the account says how
# many there will be next season, so the recipe walks the client's own list rather than
# counting to three.
#
# Proven live (2026-09-02): three banners, the two seasonal free pulls taken in one run,
# `useFree = 1` and `cost = 0` on a banner the account held ZERO tickets for — so it was
# genuinely free and not quietly paid for out of something else — and each banner's own
# `CanFreeRecruit()` closed behind its pull.
#
# The whole ability is a reading, a send per waiting free pull and one number:
#
#   1. can the client answer for the banners at all — a client that is not logged in
#      answers «no free pull» to every question with a perfectly straight face
#      (a FAIL here, so the timer retries in minutes instead of sitting out an hour
#      over a reading nobody made);
#   2. EVERY hero banner's own `CanFreeRecruit()`, one pull each while one says yes;
#   3. the survivors' own `CanFreeRecruit()`, and its pull if it says yes;
#   4. WHEN THE NEXT FREE PULL IS, in seconds, taken as the NEAREST of all their clocks —
#      and left in `next_run_in`, which is what the panel's schedule books this errand's
#      next turn with (`panel/timers.py`, `NEXT_RUN_VAR`). An hourly row would look
#      fifty times for nothing and still be late; the game already knows the answer.
#
# The gate is never re-implemented here. Every `CanFreeRecruit()` call is the CLIENT'S
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

# The hero banners are walked from the client's own list, and a banner is MARKED as it is
# picked (`__lw_tavern_tried`, forgotten at the start of every run below). A pull the
# server ignores leaves the banner's own gate open, so without the mark this loop would
# offer the same banner its whole LIMIT and take the free pull off none of the others.
LUA DataCenter.__lw_tavern_tried = {}

READ_LUA (function() local M = DataCenter.LotteryDataManager local function banner(id) local v = nil pcall(function() v = M:GetLotteryDataById(id) end) if v == nil then pcall(function() v = M:GetLotteryDataById(tostring(id)) end) end return v end local function freeOf(v) local sup, free = 0, 0 pcall(function() sup = v:IsSupportFreeRecruit() and 1 or 0 end) pcall(function() free = v:CanFreeRecruit() and 1 or 0 end) return sup, free end local any = 0 pcall(function() for _, id in pairs(M.curRecruitIdList or {}) do if banner(id) ~= nil then any = 1 end end end) local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) return ((any == 1 or wl ~= nil) and 1 or 0) end)() INTO ready

IF ready == 0
    FAIL "the client cannot answer for the recruit banners — not logged in yet"

# `lottery` is the banner the next pull is about — a banner id, or `0` when no hero
# banner has a free pull left. It is the very argument `recruit_draw` reads, so the
# `CALL` below carries it without a word (`CALL` passes the caller's variables and the
# sub-recipe's own `ARGS` only fill in what was left out).
READ_LUA (function() local M = DataCenter.LotteryDataManager local function banner(id) local v = nil pcall(function() v = M:GetLotteryDataById(id) end) if v == nil then pcall(function() v = M:GetLotteryDataById(tostring(id)) end) end return v end local function freeOf(v) local sup, free = 0, 0 pcall(function() sup = v:IsSupportFreeRecruit() and 1 or 0 end) pcall(function() free = v:CanFreeRecruit() and 1 or 0 end) return sup, free end DataCenter.__lw_tavern_tried = DataCenter.__lw_tavern_tried or {} local pick = 0 pcall(function() for _, id in pairs(M.curRecruitIdList or {}) do local key = tostring(id) if pick == 0 and not DataCenter.__lw_tavern_tried[key] then local v = banner(id) if v ~= nil then local sup, free = freeOf(v) if sup == 1 and free == 1 then DataCenter.__lw_tavern_tried[key] = 1 local n = 0 pcall(function() n = math.floor(key + 0) end) if n > 0 then pick = n end end end end end end) return pick end)() INTO lottery

WHILE lottery != 0 LIMIT 8
    LOG "hero banner {lottery} has its free pull — taking it"
    READ_LUA ('hero') INTO kind
    CALL recruit_draw
    READ_LUA (function() local M = DataCenter.LotteryDataManager local function banner(id) local v = nil pcall(function() v = M:GetLotteryDataById(id) end) if v == nil then pcall(function() v = M:GetLotteryDataById(tostring(id)) end) end return v end local function freeOf(v) local sup, free = 0, 0 pcall(function() sup = v:IsSupportFreeRecruit() and 1 or 0 end) pcall(function() free = v:CanFreeRecruit() and 1 or 0 end) return sup, free end DataCenter.__lw_tavern_tried = DataCenter.__lw_tavern_tried or {} local pick = 0 pcall(function() for _, id in pairs(M.curRecruitIdList or {}) do local key = tostring(id) if pick == 0 and not DataCenter.__lw_tavern_tried[key] then local v = banner(id) if v ~= nil then local sup, free = freeOf(v) if sup == 1 and free == 1 then DataCenter.__lw_tavern_tried[key] = 1 local n = 0 pcall(function() n = math.floor(key + 0) end) if n > 0 then pick = n end end end end end end) return pick end)() INTO lottery

READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local f = 0 pcall(function() f = wl:CanFreeRecruit() and 1 or 0 end) return f end)() INTO worker_free

IF worker_free == 1
    LOG "the survivor banner has its free pull — taking it"
    READ_LUA ('worker') INTO kind
    READ_LUA ('') INTO lottery
    CALL recruit_draw

# …and when to come back: the NEAREST of every banner's own next-free time, in seconds
# from now, with a minute's margin so a run that lands a heartbeat early does not read
# «not yet» and book itself another whole wait. `0` — nothing readable — leaves the row's
# own period to decide, which is the safe way for this to fail.
READ_LUA (function() local M = DataCenter.LotteryDataManager local function banner(id) local v = nil pcall(function() v = M:GetLotteryDataById(id) end) if v == nil then pcall(function() v = M:GetLotteryDataById(tostring(id)) end) end return v end local function freeOf(v) local sup, free = 0, 0 pcall(function() sup = v:IsSupportFreeRecruit() and 1 or 0 end) pcall(function() free = v:CanFreeRecruit() and 1 or 0 end) return sup, free end local function secs(v) local n = tonumber(v) or 0 if n > 100000000000 then n = n / 1000 end return math.floor(n) end local now = 0 pcall(function() now = math.floor(tonumber(UITimeManager:GetInstance():GetServerSeconds()) or 0) end) if now <= 0 then return 0 end local best = 0 local function want(d) if d > 0 and (best == 0 or d < best) then best = d end end pcall(function() for _, id in pairs(M.curRecruitIdList or {}) do local v = banner(id) if v ~= nil then local sup, free = freeOf(v) if sup == 1 and free == 0 then want(secs(v.dailyFreeNextFreshTime) - now) end end end end) local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl ~= nil then local free = 0 pcall(function() free = wl:CanFreeRecruit() and 1 or 0 end) if free == 0 then want(secs(wl.nextFreeTime) - now) end end if best == 0 then return 0 end return best + 60 end)() INTO next_run_in

LOG "the next free pull is what «next_run_in» says, in seconds (0 = the row's period stands)"
