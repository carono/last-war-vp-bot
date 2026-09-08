# Read the Glittering Market: is it running, what is free today, what the coins buy.
# ru: Чтение «Сверкающего рынка»: идёт ли акция, что бесплатно сегодня, что купят монеты.
#
# HEADLESS and free: nothing is opened, nothing is pressed and NOT ONE QUESTION goes on
# the wire. The whole record arrives with the activity and the server keeps it up to date
# (`docs/research/glittering-market.md`), so a reading is one round trip against the
# client's own memory.
#
# WHAT IT LEAVES BEHIND, for the recipes that act on it and for the card that draws it:
#
#   market      — the whole reading as one line, which is what the panel keeps
#   open        — 1 while the run is on, 0 when it is over or has not started
#   free_due    — 1 when today's free reward is still waiting
#   goods_free  — how many rows priced at NOTHING still have a quota left
#   boxes_due   — how many progress chests have been earned and not claimed
#   coins       — the Glitter Coins the account is holding
#
# THE PARKED TABLE. Everything is worked out once, inside the first chunk, and left on
# `DataCenter.__lw_market` — the readings below take it off that table instead of walking
# the shop five more times.

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = {open = 0, free = 0, goods = 0, boxes = 0, coins = 0, ends = 0, starts = 0, restock = 0, score = 0, top = 0, free_item = '', free_count = 0, priced = 0} DataCenter.__lw_market = M local D = DataCenter.LWTitaniumBlueStoreManager if type(D) ~= 'table' or D.activityId == nil then return 'not running — the client has no Glittering Market' end local now = 0 pcall(function() now = num(UITimeManager.Instance:GetServerTime()) end) if now == 0 then now = os.time() * 1000 end M.starts = math.floor(num(D.startTime) / 1000) M.ends = math.floor(num(D.endTime) / 1000) M.restock = num(D.dayRewardNextRefreshTime) M.score = num(D.totalScore) pcall(function() M.top = num(D:GetBoxRewardMaxValue()) end) if num(D.startTime) <= now and now <= num(D.endTime) then M.open = 1 end local can = false pcall(function() can = (D.activityFreeRewardData:CanGetFreePack() == true) end) if can and num(D.dayRewardReceiveState) == 0 then M.free = 1 end for _, r in pairs(D.dayRewardList or {}) do M.free_count = num(r.count) local nm = nil pcall(function() nm = DataCenter.ItemTemplateManager:GetName(num(r.itemId)) end) M.free_item = tostring(nm or r.itemId) end pcall(function() local have = nil pcall(function() have = num(DataCenter.ItemData:GetItemNumById(654001)) end) if have == nil or have == 0 then local n = 0 for _, s in pairs(DataCenter.ItemData.ItemInfos or {}) do if tostring(s.itemId) == '654001' then n = n + num(s.num) + num(s.count) end end have = n end M.coins = have end) for _, p in pairs(D.productList or {}) do local left = num(p.buyTimeLimit) - num(p.buyTimes) if left > 0 then if num(p.costNum) == 0 then M.goods = M.goods + left else M.priced = M.priced + 1 end end end local taken = {} for _, v in pairs(D.boxReceiveList or {}) do taken[tostring(v)] = true end for _, b in pairs(D.boxRewardsList or {}) do local idx = num(b.index) local st = -1 pcall(function() st = num(D:GetBoxRewardState(idx)) end) if M.score >= num(b.targetCount) and not taken[tostring(idx)] and st ~= 2 then M.boxes = M.boxes + 1 end end return 'open=' .. M.open .. ' starts=' .. M.starts .. ' ends=' .. M.ends .. ' restock=' .. M.restock .. ' free=' .. M.free .. ' goods_free=' .. M.goods .. ' priced_rows=' .. M.priced .. ' coins=' .. M.coins .. ' score=' .. M.score .. ' top=' .. M.top .. ' boxes_due=' .. M.boxes .. ' free_count=' .. M.free_count .. ' free_item=' .. M.free_item end)() INTO market

READ_LUA (function() local M = DataCenter.__lw_market or {} return math.floor(M.open or 0) end)() INTO open
READ_LUA (function() local M = DataCenter.__lw_market or {} return math.floor(M.free or 0) end)() INTO free_due
READ_LUA (function() local M = DataCenter.__lw_market or {} return math.floor(M.goods or 0) end)() INTO goods_free
READ_LUA (function() local M = DataCenter.__lw_market or {} return math.floor(M.boxes or 0) end)() INTO boxes_due
READ_LUA (function() local M = DataCenter.__lw_market or {} return math.floor(M.coins or 0) end)() INTO coins

LOG "Сверкающий рынок: {market}"
