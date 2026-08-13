# Read what the two recruit banners can do right now — heroes and survivors.
# ru: Прочитать состояние найма — герои и выжившие: бесплатная попытка и билеты.
#
# A READ, and nothing else: it presses nothing, opens nothing and changes nothing, so it
# is safe beside anything. One round trip answers everything a «Найм» press has to know:
#
#   * **is there a free pull, and when does the next one come?** Both banners have one
#     and they run on different clocks — the hero banner refreshes daily, the survivors'
#     one on a timer of its own. Both answers are the CLIENT'S OWN
#     (`IsSupportFreeRecruit` / `CanFreeRecruit`), never arithmetic of ours over a
#     timestamp: a copy of that comparison is one build away from disagreeing with what
#     the person sees on screen;
#   * **can a pull be paid for?** The ticket the banner takes, how many are held, and
#     what one, ten and a hundred pulls cost in it.
#
# The answer lands in ONE variable, `recruit`, as records separated by « | »:
#
#     now=<server seconds>
#     hero id=<banner> support=1 free=0 next=<epoch sec> item=<ticket> have=<n> \
#          c1=1 c10=10 c100=100 total=<pulls made> limit=<ceiling>
#     worker id=<banner> support=1 free=1 next=0 item=<ticket> have=<n> c1=1 c10=10 c100=100
#
# `free` is «available this moment», `next` is when it comes back (epoch seconds, `0`
# when it is available now). A banner the client cannot answer for is LEFT OUT of the
# line rather than reported as empty — that is how «the client is not logged in» tells
# itself apart from «no free pull today».
#
# Who reads it: the panel's «Найм» tab (`panel/tabs/recruit/`). The pull itself is
# actions/recruit_draw.md; the reverse-engineering is docs/research/recruit-draw.md.

READ_LUA (function() local function heroInfo() local M = DataCenter.LotteryDataManager local want = tostring(DataCenter.__lw_recruit_lottery or '') if want ~= '' then local ok, v = pcall(function() return M:GetLotteryDataById(want) end) if ok and v ~= nil then return v, want end ok, v = pcall(function() return M:GetLotteryDataById(tonumber(want)) end) if ok and v ~= nil then return v, want end return nil, want end for _, id in pairs(M.curRecruitIdList or {}) do local ok, v = pcall(function() return M:GetLotteryDataById(id) end) if ok and v ~= nil then return v, tostring(id) end end return nil, '' end local function workerInfo() local M = DataCenter.LotteryDataManager local cfg, wl = nil, nil pcall(function() cfg = M:GetOnlyWorkerLotteryData() end) pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) return wl, cfg end local function costOf(info, size) local id, num = 0, 0 pcall(function() if size == 2 then local c = info:GetHundredCost() if c ~= nil then id = tonumber(c.itemId) or 0 num = tonumber(c.itemNum) or 0 end else local list = info:GetCostItems() or {} local c = list[size + 1] if c ~= nil then id = tonumber(c.itemId) or 0 num = tonumber(c.itemNum) or 0 end end end) return id, num end local function have(itemId) local n = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(itemId) n = tonumber(it and it.count) or 0 end) return n end local function secs(v) local n = tonumber(v) or 0 if n > 100000000000 then n = n / 1000 end return math.floor(n) end local out = {} local now = 0 pcall(function() now = math.floor(tonumber(UITimeManager:GetInstance():GetServerSeconds()) or 0) end) out[#out+1] = 'now='..now local hi, hid = heroInfo() if hi ~= nil then local sup, free = 0, 0 pcall(function() sup = hi:IsSupportFreeRecruit() and 1 or 0 end) pcall(function() free = hi:CanFreeRecruit() and 1 or 0 end) local nxt = 0 if free == 0 and sup == 1 then nxt = secs(hi.dailyFreeNextFreshTime) end local id1, n1 = costOf(hi, 0) local _, n10 = costOf(hi, 1) local _, n100 = costOf(hi, 2) local total, limit = 0, 0 pcall(function() total = math.floor(tonumber(hi.totalLottery) or 0) end) pcall(function() limit = math.floor(tonumber(hi.totalLotteryLimit) or 0) end) out[#out+1] = 'hero id='..hid..' support='..sup..' free='..free..' next='..nxt..' item='..id1..' have='..have(id1)..' c1='..n1..' c10='..n10..' c100='..n100..' total='..total..' limit='..limit end local wl, wcfg = workerInfo() if wl ~= nil then local free = 0 pcall(function() free = wl:CanFreeRecruit() and 1 or 0 end) local nxt = 0 if free == 0 then nxt = secs(wl.nextFreeTime) end local id1, n1 = costOf(wl, 0) local _, n10 = costOf(wl, 1) local n100 = 0 pcall(function() local c = wcfg and wcfg.recruit100CostInfo if c ~= nil then n100 = tonumber(c.itemNum) or 0 end end) local wid = 0 pcall(function() wid = math.floor(tonumber(wcfg and wcfg.id) or 0) end) out[#out+1] = 'worker id='..wid..' support=1 free='..free..' next='..nxt..' item='..id1..' have='..have(id1)..' c1='..n1..' c10='..n10..' c100='..n100 end return table.concat(out, ' | ') end)() INTO recruit
