# Buy from the shops in the order the person put them in, within what they allowed.
# ru: Покупка в магазинах по заданному человеком порядку и в пределах разрешённого.
#
# THIS ONE SPENDS, AND IT SHIPS SWITCHED OFF. It is the one exception the «ships switched
# on» rule names (`CLAUDE.md`): a purchase cannot be undone, and the currencies it spends
# take weeks to earn. So the errand is off, its order is empty until a person puts
# something in it, and the diamonds it may spend are 0 until a person types a ceiling.
#
# WHAT IT NEEDS TOLD:
#
#   plan         — the order, as «Магазин» writes it: `kind:shop:id:count`, comma
#                  separated, most wanted first. Empty means «nothing chosen», and the
#                  recipe says so and stops.
#   diamond_cap  — the most DIAMONDS one run may spend. 0 — the default — means not one,
#                  and a row priced in diamonds is skipped rather than bought.
#   cap          — the most purchases one run may make at all, whatever the order says.
#
# WHAT IT DOES, and the order is the whole of it: it walks the plan from the top, and for
# each row it takes as many as the row's own quota allows, as many as the ceilings allow,
# and only while the GAME says the account can pay (`CheckCostEnough` — a price paid out
# of two purses is the client's arithmetic, never this file's). A row it cannot afford is
# stepped over rather than ending the run: the next thing in the order may be cheaper,
# and that is exactly what an order of preference is for.
#
# IT SAYS THE PRICE FIRST. The line before anything is sent names every row it is about
# to buy, how many, and what that comes to — so a run that turns out wrong is visible in
# the log rather than only in the purse.
#
# The wire and the shape of a shelf are docs/research/shops.md.

ARGS plan =
ARGS diamond_cap = 0
ARGS cap = 20

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local C = DataCenter.CommonShopManager local plan = '{plan}' local order = {} for piece in plan:gmatch('[^,]+') do local bits = {} for b in piece:gmatch('[^:]+') do bits[#bits + 1] = b end if #bits >= 3 then order[#order + 1] = {kind = bits[1], shop = num(bits[2]), id = bits[3], count = math.max(1, num(bits[4] or '1'))} end end DataCenter.__lw_shop_plan = order local rows = {} local diamonds = num('{diamond_cap}') local left = num('{cap}') if left < 1 then left = 1 end local spent_d = 0 local picked = {} for _, e in ipairs(order) do if left <= 0 then break end local P = nil if e.kind == 'common' then for _, p in pairs((C.goodsShopDic or {})[e.shop] or {}) do if tostring(p.id) == e.id then P = p end end end if P ~= nil then local want = e.count if want > left then want = left end if num(P.maxTimes) > 0 then local bought = 0 pcall(function() bought = num(C:GetShopGoodsNum(P)) end) local room = num(P.maxTimes) - bought if want > room then want = room end end while want > 0 do local ok = false pcall(function() ok = (C:CheckCostEnough(P, want) == true) end) if ok then break end want = want - 1 end if want > 0 and num(P.currencyType) == 5 then local price = want * num(P.costNum) if spent_d + price > diamonds then want = 0 end if want > 0 then spent_d = spent_d + price end end if want > 0 then left = left - want picked[#picked + 1] = {row = P, n = want} local nm = '' pcall(function() nm = tostring(DataCenter.ItemTemplateManager:GetName(num(P.itemId)) or '') end) rows[#rows + 1] = nm .. ' x' .. want .. ' за ' .. (want * num(P.costNum)) end end end DataCenter.__lw_shop_picked = picked if #rows == 0 then return 'по очереди покупать нечего' end return 'собираюсь купить: ' .. table.concat(rows, '; ') .. (spent_d > 0 and (' (алмазов ' .. spent_d .. ' из ' .. diamonds .. ')') or '') end)() INTO offer
LOG "автопокупка: {offer}"

READ_LUA (function() local picked = DataCenter.__lw_shop_picked or {} local n = 0 for _ in ipairs(picked) do n = n + 1 end return n end)() INTO lots

IF lots < 1
    LOG "автопокупка: ничего не отправлено"
    STOP

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local C = DataCenter.CommonShopManager local picked = DataCenter.__lw_shop_picked or {} local was = {} local sent = 0 for i, e in ipairs(picked) do local b = 0 pcall(function() b = num(C:GetShopGoodsNum(e.row)) end) was[i] = b pcall(function() SFSNetwork.SendMessage(MsgDefines.BuyCommonShopGoods, e.row.id, {}, e.n) sent = sent + e.n end) end DataCenter.__lw_shop_was_all = was return sent end)() INTO sent
LOG "автопокупка: отправлено покупок — {sent}"
WAIT 4

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local C = DataCenter.CommonShopManager local picked = DataCenter.__lw_shop_picked or {} local was = DataCenter.__lw_shop_was_all or {} local moved = 0 for i, e in ipairs(picked) do local now = was[i] or 0 pcall(function() now = num(C:GetShopGoodsNum(e.row)) end) moved = moved + (now - (was[i] or 0)) end return moved end)() INTO bought
LOG "автопокупка: сервер принял покупок — {bought}"
