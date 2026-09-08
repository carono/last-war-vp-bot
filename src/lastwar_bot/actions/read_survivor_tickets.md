# Read the survivor recruit banner — tickets held, its price, and the free pull.
# ru: Прочитать баннер найма выживших — билеты на руках, цена и бесплатная попытка.
#
# A READ, and nothing else: it presses nothing, opens nothing and spends nothing, so it
# is safe beside anything. The whole of the survivors' banner in one round trip.
#
# It is the narrow half of `read_recruit_state.md`, which answers for BOTH banners: the
# «VS» tab's Tuesday is about the survivors' tickets alone, so it asks for those alone
# rather than reading the heroes' three banners it will not draw.
#
# What comes back:
#
#   * `worker_tickets` — how many recruit tickets the bag holds for that banner;
#   * `worker_free` — 1 while the banner's own free pull is waiting to be taken;
#   * `worker_c1` / `worker_c10` — what one and ten pulls cost in those tickets.
#
# A client that cannot answer for the banner reports `-1` tickets, which is «nobody
# knows» and must never be drawn as a zero.
#
# Who reads it: the «VS» tab's Tuesday. Spending them is `spend_survivor_tickets.md`.

READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return -1 end local n = -1 pcall(function() local c = (wl:GetCostItems() or {})[1] local it = DataCenter.ItemData:GetItemById(c.itemId) n = math.floor(tonumber(it and it.count) or 0) end) return n end)() INTO worker_tickets

READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local free = 0 pcall(function() free = wl:CanFreeRecruit() and 1 or 0 end) return free end)() INTO worker_free

READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local n = 0 pcall(function() n = math.floor(tonumber((wl:GetCostItems() or {})[1].itemNum) or 0) end) return n end)() INTO worker_c1

READ_LUA (function() local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl == nil then return 0 end local n = 0 pcall(function() n = math.floor(tonumber((wl:GetCostItems() or {})[2].itemNum) or 0) end) return n end)() INTO worker_c10

LOG "survivor tickets: {worker_tickets} (free pull: {worker_free}, x1 costs {worker_c1}, x10 costs {worker_c10})"
