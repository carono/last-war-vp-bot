# Read every shop the account has: what is on the shelves, at what price, and how much is left.
# ru: Чтение всех магазинов аккаунта: что на полках, по какой цене и сколько осталось.
#
# HEADLESS and free: nothing is opened, nothing is pressed and NOT ONE QUESTION goes on
# the wire. Every row of every shop is already in the client's own memory — the game
# fills `CommonShopManager` when the player enters and keeps it up to date — so a reading
# is one round trip against that memory (docs/research/shops.md).
#
# WHAT IT LEAVES BEHIND:
#
#   shops   — the shelves that are spent with a currency the account EARNS, packed
#   money   — the storefronts that want money, packed the same way, drawn and never
#             pressed: no message buys one of those, so the panel offers no button
#   rows    — how many goods were read in all
#
# HOW A ROW IS PACKED. Records are separated by « #|# », and one record is fifteen fields
# separated by « ;; » with the NAME last, so a name holding a separator costs nothing:
#
#   kind;;shop;;id;;item;;icon;;colour;;count;;cost_id;;cost;;limit;;bought;;reset;;afford;;cost_name;;name
#
#   kind      — `common` for a shelf of the game's own «Магазин», `market` for
#               «Сверкающий рынок», `money` for a storefront that wants money.
#   shop      — the shelf's own number, the one the CLIENT numbers it with. Never a name:
#               which shelves exist is the game's answer, not this file's.
#   id        — the row's own id, which is what a purchase names.
#   item      — what the row hands over, and `icon`/`colour` are that item's own sprite
#               and rarity, read exactly as the bag reads them (`read_inventory.md`), so
#               the panel composes the game's own cell and never invents a picture.
#               A row whose `itemId` is EMPTY is not a broken row: a good part of the
#               alliance and season shelves sell RESOURCE ITEMS, which are a different
#               table with a different name, picture and quality
#               (`ResourceItemDataManager`), and the row's own `GetRewardData()` says
#               which of the two it is. Asked the wrong table, such a row draws its own
#               id where its name should be — which is exactly what it did (#2666).
#   count     — how many of the item one purchase gives.
#   cost_id   — the currency the row is priced in, as the client numbers it; `cost` is
#               the price; `cost_name` is the game's own word for that currency, and it
#               is empty when the client itself has no word for it — a panel that draws
#               the number is honest, a panel that invents a name is not.
#   limit     — how many of the row the account may ever buy (0 = no limit at all);
#               `bought` is how many it has, and `reset` is when that quota comes back.
#   afford    — 1 when the GAME says the account can pay for one right now
#               (`CheckCostEnough`), 0 when it says it cannot. Never worked out here:
#               a price paid out of two purses is the client's own arithmetic.
#
# A field the game will not answer is left at its «unknown» value rather than guessed:
# every read is wrapped, so one row the client cannot describe costs one blank and not
# the whole shelf.

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function flat(s) local out = tostring(s or '') out = out:gsub('%s+', ' ') out = out:gsub(';;', ' ') out = out:gsub('#|#', ' ') return out end local C = DataCenter.CommonShopManager local T = DataCenter.ItemTemplateManager local R = DataCenter.ResourceManager if type(C) ~= 'table' then return '' end local out = {} local function money_name(t) local said = '' pcall(function() said = tostring(R:GetResourceNameByType(t) or '') end) if said:sub(1, 1) == '<' then said = '' end return said end local I = DataCenter.ResourceItemDataManager local function base(path) local out = tostring(path or '') out = out:gsub('.*/', '') out = out:gsub('%.png$', '') return out end local function item_bits(id) local nm, ic, co = '', '', 0 pcall(function() nm = tostring(T:GetName(id) or '') end) pcall(function() local tpl = T:GetItemTemplate(id) ic = tostring(tpl.icon or '') co = num(tpl.color) end) return nm, ic, co end local function res_bits(id) local nm, ic, co = '', '', 0 pcall(function() nm = tostring(I:GetName(id) or '') end) pcall(function() ic = base(I:GetIconPath(id)) end) pcall(function() co = num(I:GetResourceItemQuality(id)) end) return nm, ic, co end local function row_bits(p) local id = num(p.itemId) if id > 0 then local nm, ic, co = item_bits(id) if nm ~= '' or ic ~= '' then return id, num(p.itemNum), nm, ic, co end end local r = nil pcall(function() r = p:GetRewardData() end) if r ~= nil then local rid = num(r.itemId) local kind = num(r.rewardType) local cnt = num(r.count) if cnt < 1 then cnt = num(p.itemNum) end if kind == 27 then local nm, ic, co = res_bits(rid) return rid, cnt, nm, ic, co end local nm, ic, co = item_bits(rid) return rid, cnt, nm, ic, co end return id, num(p.itemNum), '', '', 0 end for shopType, rows in pairs(C.goodsShopDic or {}) do local reset = 0 pcall(function() reset = math.floor(num(C:GetLimitShopNextRefreshTs(shopType)) / 1000) end) for _, p in pairs(rows or {}) do local item, give, nm, ic, co = row_bits(p) local bought, afford = 0, 0 pcall(function() bought = num(C:GetShopGoodsNum(p)) end) pcall(function() afford = (C:CheckCostEnough(p, 1) == true) and 1 or 0 end) out[#out + 1] = table.concat({'common', tostring(shopType), tostring(p.id), tostring(item), ic, tostring(co), tostring(give), tostring(num(p.currencyType)), tostring(num(p.costNum)), tostring(num(p.maxTimes)), tostring(bought), tostring(reset), tostring(afford), flat(money_name(num(p.currencyType))), flat(nm)}, ';;') end end local D = DataCenter.LWTitaniumBlueStoreManager if type(D) == 'table' and D.activityId ~= nil then local coin_name = '' pcall(function() coin_name = tostring(T:GetName(654001) or '') end) local coins = 0 pcall(function() for _, s in pairs(DataCenter.ItemData.ItemInfos or {}) do if tostring(s.itemId) == '654001' then coins = coins + num(s.num) + num(s.count) end end end) for _, p in pairs(D.productList or {}) do local item, give, kind = 0, 1, 0 for _, r in pairs(p.rewardList or {}) do item = num(r.itemId) give = num(r.count) kind = num(r.rewardType) end local nm, ic, co = item_bits(item) if kind == 27 or (nm == '' and ic == '') then local n2, i2, c2 = res_bits(item) if n2 ~= '' or i2 ~= '' then nm, ic, co = n2, i2, c2 end end local afford = (num(p.costNum) <= coins) and 1 or 0 out[#out + 1] = table.concat({'market', '0', tostring(p.id), tostring(item), ic, tostring(co), tostring(give), '654001', tostring(num(p.costNum)), tostring(num(p.buyTimeLimit)), tostring(num(p.buyTimes)), tostring(math.floor(num(p.nextResetTime))), tostring(afford), flat(coin_name), flat(nm)}, ';;') end end return table.concat(out, ' #|# ') end)() INTO shops

# THE STOREFRONTS THAT WANT MONEY are drawn and never pressed. A pack is bought through
# the platform's own purchase and there is no message on the wire that buys one, so the
# panel shows what the account is being offered — the picture, what it hands over, how
# long it runs — and offers no button at all. The PRICE is deliberately absent for the
# same reason: what a pack costs is the store's own number in the player's own money,
# and this side of the client never sees it.
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function flat(s) local out = tostring(s or '') out = out:gsub('%s+', ' ') out = out:gsub(';;', ' ') out = out:gsub('#|#', ' ') return out end local T = DataCenter.ItemTemplateManager local out = {} local M = DataCenter.WeekCardManager local list = nil pcall(function() list = M:GetWeekCardList() end) for _, c in pairs(list or {}) do local item, give = 0, 1 pcall(function() for _, r in pairs(c.showReward or c.reward or {}) do item = num(r.itemId) give = num(r.count) end end) local nm, ic, co = '', '', 0 pcall(function() nm = tostring(T:GetName(item) or '') end) pcall(function() local tpl = T:GetItemTemplate(item) ic = tostring(tpl.icon or '') co = num(tpl.color) end) out[#out + 1] = table.concat({'money', '1', tostring(c.id), tostring(item), ic, tostring(co), tostring(give), '0', '0', '0', '0', tostring(math.floor(num(c.endTime) / 1000)), '0', '', flat(nm)}, ';;') end return table.concat(out, ' #|# ') end)() INTO money

READ_LUA (function() local n = 0 local C = DataCenter.CommonShopManager for _, rows in pairs((C or {}).goodsShopDic or {}) do for _ in pairs(rows or {}) do n = n + 1 end end local D = DataCenter.LWTitaniumBlueStoreManager if type(D) == 'table' and D.activityId ~= nil then for _ in pairs(D.productList or {}) do n = n + 1 end end return n end)() INTO rows
LOG "магазины: прочитано товаров — {rows}"
