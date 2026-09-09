# Buy one row of one shop — the price is said before anything is sent.
# ru: Купить один товар одного магазина — цена называется до отправки.
#
# THIS ONE SPENDS. Everything a shop sells is bought with something the account earned
# over weeks and none of it comes back, so this recipe is played by a PERSON pressing it,
# it says what it is about to spend before it sends anything, and it refuses rather than
# guesses: a row it cannot find, a quota that is used up, a price the game says the
# account cannot pay are all «нет», not «probably».
#
# WHAT IT NEEDS TOLD:
#
#   kind     — `common` for a shelf of the game's own «Магазин», `market` for
#              «Сверкающий рынок». Anything else is refused.
#   shop     — the shelf's own number, as the CLIENT numbers it (`read_shops.md`).
#   product  — the row's own id. 0 means «nothing chosen» and the recipe stops rather
#              than guessing which of a hundred and fifty rows was meant.
#   count    — how many of it. Never more than the row's own quota allows.
#
# «СВЕРКАЮЩИЙ РЫНОК» IS NOT A SECOND IMPLEMENTATION. Its purchase already exists and is
# proven live (`buy_glitter_market_goods.md`, #2636), so this recipe CALLs it and hands
# over the same two variables it takes. One ability, one file.
#
# THE WIRE. `user.shop.buy.new` (`MsgDefines.BuyCommonShopGoods`) puts `PutInt id`,
# `PutInt num` and a `PutSFSArray goodsArr` — read without sending a byte, with the
# `NewEmpty` + recording `sfsObj` trick. The array is what the game fills when a purchase
# is paid out of resource items; a purchase paid with the shelf's own currency sends it
# empty. The whole of it is docs/research/shops.md.

ARGS kind = common
ARGS shop = 0
ARGS product = 0
ARGS count = 1

READ_LUA (function() local k = '{kind}' if k == 'market' then return 1 end return 0 end)() INTO is_market

IF is_market == 1
    CALL buy_glitter_market_goods
    STOP

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local C = DataCenter.CommonShopManager local st = num('{shop}') local want = '{product}' local P = nil for _, p in pairs((C.goodsShopDic or {})[st] or {}) do if tostring(p.id) == want then P = p end end DataCenter.__lw_shop_pick = P if want == '0' then return 'товар не выбран' end if P == nil then return 'товара ' .. want .. ' нет в магазине ' .. st end local nm = '' pcall(function() nm = tostring(DataCenter.ItemTemplateManager:GetName(num(P.itemId)) or '') end) local cn = '' pcall(function() cn = tostring(DataCenter.ResourceManager:GetResourceNameByType(num(P.currencyType)) or '') end) if cn:sub(1, 1) == '<' then cn = 'валюта ' .. num(P.currencyType) end local bought = 0 pcall(function() bought = num(C:GetShopGoodsNum(P)) end) local left = 'без лимита' if num(P.maxTimes) > 0 then left = tostring(num(P.maxTimes) - bought) .. ' из ' .. num(P.maxTimes) end return nm .. ' x' .. num(P.itemNum) .. ', цена ' .. num(P.costNum) .. ' (' .. cn .. ') за штуку, осталось ' .. left end)() INTO offer
LOG "магазин: {offer}"

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local C = DataCenter.CommonShopManager local P = DataCenter.__lw_shop_pick if P == nil then return 0 end local want = num('{count}') if want < 1 then want = 1 end if num(P.maxTimes) > 0 then local bought = 0 pcall(function() bought = num(C:GetShopGoodsNum(P)) end) local left = num(P.maxTimes) - bought if want > left then want = left end end if want < 1 then return 0 end local afford = false pcall(function() afford = (C:CheckCostEnough(P, want) == true) end) if not afford then local one = false pcall(function() one = (C:CheckCostEnough(P, 1) == true) end) if not one then return 0 end want = 1 end DataCenter.__lw_shop_n = want return want end)() INTO buying

IF buying < 1
    LOG "магазин: не покупаю — либо кончился лимит, либо игра говорит, что не хватает валюты"
    STOP

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local C = DataCenter.CommonShopManager local P = DataCenter.__lw_shop_pick local n = num(DataCenter.__lw_shop_n) local was = 0 pcall(function() was = num(C:GetShopGoodsNum(P)) end) DataCenter.__lw_shop_was = was local sent = 0 pcall(function() SFSNetwork.SendMessage(MsgDefines.BuyCommonShopGoods, P.id, {}, n) sent = n end) return 'отправлена покупка на ' .. sent .. ' шт., до ' .. (sent * num(P.costNum)) .. ' единиц валюты' end)() INTO spent
LOG "магазин: {spent}"
WAIT 3.5

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local C = DataCenter.CommonShopManager local P = DataCenter.__lw_shop_pick local was = num(DataCenter.__lw_shop_was) local now = was pcall(function() now = num(C:GetShopGoodsNum(P)) end) return (now - was) end)() INTO bought
LOG "магазин: сервер принял покупок — {bought}"
