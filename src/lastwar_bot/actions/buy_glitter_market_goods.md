# Spend Glitter Coins on one row of the Glittering Market — the price is said first.
# ru: Потратить блестящие монеты на один товар «Сверкающего рынка» — цена называется заранее.
#
# THIS ONE SPENDS, AND IT IS SWITCHED OFF. A Glitter Coin is bought with diamonds in the
# game's own pack window and never comes back, so this recipe ships off, is run by a
# PERSON pressing it, and says what it is about to spend before it sends anything
# (`CLAUDE.md`, «A new ability ships SWITCHED ON» and its one exception — an irreversible
# spend).
#
# WHAT IT CANNOT DO, and it is not a gap: it cannot BUY the coins. The packs are not on
# the wire — no manager holds them, no config table has a row for them and there is no
# message that buys one; the only ways in are two window-opening calls. Buying coins is a
# purchase the person makes in the game. See `docs/research/glittering-market.md`.
#
# WHAT IT NEEDS TOLD:
#
#   product  — the row's id, as the shop numbers it. 0 means «nothing chosen» and the
#              recipe stops rather than guessing which of two dozen rows was meant.
#   count    — how many of it to buy. Never more than the row's own quota allows.
#   budget   — the most coins one run may spend. 0 means «only what the row costs», which
#              is the same thing said the other way and is the safe default.
#
# WHAT IT DOES:
#
#   1. reads the event and refuses if the run is over;
#   2. finds the row, and refuses if it does not exist, costs nothing (that one is free
#      and belongs to `collect_glittering_market`), has no quota left, or costs more than
#      the account is holding;
#   3. SAYS THE PRICE — the row, what it gives, what it costs and what the bag has;
#   4. sends `blue.shop.buy` once per copy, with three bare arguments and the ids as
#      STRINGS (the shape was found live and is written down in the research);
#   5. reads back and reports how many of them the server actually accepted.

ARGS product = 0
ARGS count = 1
ARGS budget = 0

CALL read_glittering_market

IF open == 0
    LOG "Сверкающий рынок: акция не идёт — покупать нечего"
    STOP

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local D = DataCenter.LWTitaniumBlueStoreManager local want = num('{product}') local M = DataCenter.__lw_market or {} local P = nil for _, p in pairs(D.productList or {}) do if tostring(p.id) == tostring(want) then P = p end end DataCenter.__lw_market_pick = P if want == 0 then return 'нечего покупать: товар не выбран' end if P == nil then return 'товара ' .. want .. ' нет в этом рынке' end local price = num(P.costNum) if price == 0 then return 'товар ' .. want .. ' бесплатный — его берёт «Сверкающий рынок: бесплатное»' end local left = num(P.buyTimeLimit) - num(P.buyTimes) local give = '' for _, r in pairs(P.rewardList or {}) do local nm = nil pcall(function() nm = DataCenter.ItemTemplateManager:GetName(num(r.itemId)) end) give = tostring(nm or r.itemId) .. ' x' .. num(r.count) end return 'товар ' .. want .. ' — ' .. give .. ', цена ' .. price .. ' монет за штуку, куплено ' .. num(P.buyTimes) .. ' из ' .. num(P.buyTimeLimit) .. ', в сумке ' .. num(M.coins) .. ' монет' end)() INTO offer
LOG "Сверкающий рынок: {offer}"

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local P = DataCenter.__lw_market_pick local M = DataCenter.__lw_market or {} if P == nil then return 0 end local price = num(P.costNum) if price == 0 then return 0 end local left = num(P.buyTimeLimit) - num(P.buyTimes) local want = num('{count}') if want < 1 then want = 1 end if want > left then want = left end local purse = num(M.coins) local budget = num('{budget}') if budget > 0 and budget < purse then purse = budget end local afford = math.floor(purse / price) if want > afford then want = afford end if want < 0 then want = 0 end DataCenter.__lw_market_n = want return want end)() INTO buying

IF buying < 1
    LOG "Сверкающий рынок: не покупаю — либо кончилась квота, либо не хватает монет"
    STOP

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local D = DataCenter.LWTitaniumBlueStoreManager local P = DataCenter.__lw_market_pick local n = num(DataCenter.__lw_market_n) local price = num(P.costNum) DataCenter.__lw_market_was = num(P.buyTimes) local sent = 0 while sent < n do pcall(function() SFSNetwork.SendMessage(MsgDefines.BlueShopBuy, D.activityId, P.id, 1) end) sent = sent + 1 end return 'отправлено ' .. sent .. ' покупок, до ' .. (sent * price) .. ' монет' end)() INTO spent
LOG "Сверкающий рынок: {spent}"
WAIT 3.5

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local D = DataCenter.LWTitaniumBlueStoreManager local want = num('{product}') local was = num(DataCenter.__lw_market_was) local now = was for _, p in pairs(D.productList or {}) do if tostring(p.id) == tostring(want) then now = num(p.buyTimes) end end return (now - was) end)() INTO bought
LOG "Сверкающий рынок: сервер принял покупок — {bought}"

CALL read_glittering_market
