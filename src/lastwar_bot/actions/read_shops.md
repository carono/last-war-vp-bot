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
#   purses  — one record per CURRENCY the shelves want: what it is called, its own
#             picture and how much of it the account has (#2830)
#   rows    — how many goods were read in all
#
# HOW A ROW IS PACKED. Records are separated by « #|# », and one record is fifteen fields
# separated by « ;; » with the NAME last, so a name holding a separator costs nothing:
#
#   kind;;shop;;id;;item;;icon;;colour;;count;;cost_id;;cost;;limit;;bought;;reset;;afford;;cost_name;;name;;cost_item
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
#   cost_item — WHICH ITEM the price is paid in, when the type does not say (#2830).
#               `currencyType` is not the currency: **7 means «an item»**, and six
#               different shelves are priced in six different items under that one
#               number — measured live, the coupon, decoration, season, expedition and
#               two unnamed shelves all answered `7`. So a currency is identified by the
#               PAIR (`cost_id`, `cost_item`), the item id being the row's own
#               `currencyId`, and empty for a currency the type already names (the
#               diamonds, a resource).
#
#               **`resourceitem_id` IS NOT THE CURRENCY** and #2670 read it as one: it
#               is the resource item the row HANDS OVER when `itemId` is empty. Measured
#               live on 2026-09-12 — the honour shelf's rows carry 7016, 7015, 7038 and
#               7005 there, which are four things it SELLS, and counting them as a purse
#               priced the shelf out of the player's own goods.
#   limit     — how many of the row the account may ever buy (0 = no limit at all);
#               `bought` is how many it has, and `reset` is when that quota comes back.
#   afford    — 1 when the account can pay for one right now, worked out HERE.
#
#               IT USED TO ASK THE GAME, AND THAT WAS THE TOAST STORM (#2670).
#               `CommonShopManager:CheckCostEnough` does not only answer — when the
#               answer is «no» it SHOWS «Недостаточно предметов» on screen (caught with
#               the stack: `UIUtil.ShowTipsId(120021)` ← `CommonShopManager.lua:436`
#               ← our own chunk). This reading asks about EVERY row of every shelf, so
#               one reading raised one toast per row the account cannot afford — and it
#               runs when the client gets into the game, on a balance push and after a
#               purchase. That is the «спам», and it had nothing to do with buying.
#               So the purse is read (`purse`) and compared to the price here; a purse
#               the client will not show us answers «can pay», because a reading may not
#               invent a refusal it cannot prove.
#
# A field the game will not answer is left at its «unknown» value rather than guessed:
# every read is wrapped, so one row the client cannot describe costs one blank and not
# the whole shelf.

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function flat(s) local out = tostring(s or '') out = out:gsub('%s+', ' ') out = out:gsub(';;', ' ') out = out:gsub('#|#', ' ') return out end local C = DataCenter.CommonShopManager local T = DataCenter.ItemTemplateManager local R = DataCenter.ResourceManager if type(C) ~= 'table' then return '' end local out = {} local function bag(id) local n = 0 pcall(function() for _, v in pairs(DataCenter.ItemData.ItemInfos or {}) do if tostring(v.itemId) == tostring(id) then n = n + num(v.count) + num(v.num) end end end) if n == 0 then pcall(function() n = num(DataCenter.ResourceItemDataManager:GetCountByItemId(num(id))) end) end return n end local function purse(P) local cur = num(P.currencyType) if cur == 5 then local g = 0 pcall(function() g = num(LuaEntry.Player.gold) end) return g end local cid = tonumber(tostring(P.currencyId or '')) if cid ~= nil and cid > 0 then return bag(math.floor(cid)) end local have = 0 pcall(function() have = num(LuaEntry.Resource:GetCntByResType(cur)) end) if have > 0 then return have end if cur == 40 then local h = -1 pcall(function() h = num(LuaEntry.Resource:GetHonorScore()) end) if h >= 0 then return h end end local nm = '' pcall(function() nm = tostring(DataCenter.ResourceManager:GetResourceNameByType(cur) or '') end) if nm ~= '' and nm:sub(1, 1) ~= '<' then return have end return -1 end local function bought_of(C, st, id) local n = 0 pcall(function() local g = (C.goodsInfoDic or {})[st] if g ~= nil then local r = g[id] or g[tostring(id)] or g[tonumber(id) or -1] if r ~= nil and r.boughtTimes ~= nil then n = math.floor(r.boughtTimes + 0) end end end) return n end local function money_name(t) local said = '' pcall(function() said = tostring(R:GetResourceNameByType((t == 5) and 15 or t) or '') end) if said:sub(1, 1) == '<' then said = '' end return said end local I = DataCenter.ResourceItemDataManager local function cost_item(p) local cid = tonumber(tostring(p.currencyId or '')) if cid ~= nil and cid > 0 then return tostring(math.floor(cid)) end return '' end local function base(path) local out = tostring(path or '') out = out:gsub('.*/', '') out = out:gsub('%.png$', '') return out end local function item_bits(id) local nm, ic, co = '', '', 0 pcall(function() nm = tostring(T:GetName(id) or '') end) pcall(function() local tpl = T:GetItemTemplate(id) ic = tostring(tpl.icon or '') co = num(tpl.color) end) return nm, ic, co end local function res_bits(id) local nm, ic, co = '', '', 0 pcall(function() nm = tostring(I:GetName(id) or '') end) pcall(function() ic = base(I:GetIconPath(id)) end) pcall(function() co = num(I:GetResourceItemQuality(id)) end) return nm, ic, co end local function row_bits(p) local id = num(p.itemId) if id > 0 then local nm, ic, co = item_bits(id) if nm ~= '' or ic ~= '' then return id, num(p.itemNum), nm, ic, co end end local r = nil pcall(function() r = p:GetRewardData() end) if r ~= nil then local rid = num(r.itemId) local kind = num(r.rewardType) local cnt = num(r.count) if cnt < 1 then cnt = num(p.itemNum) end if kind == 27 then local nm, ic, co = res_bits(rid) return rid, cnt, nm, ic, co end local nm, ic, co = item_bits(rid) return rid, cnt, nm, ic, co end return id, num(p.itemNum), '', '', 0 end for shopType, rows in pairs(C.goodsShopDic or {}) do local reset = 0 pcall(function() reset = math.floor(num(C:GetLimitShopNextRefreshTs(shopType)) / 1000) end) for _, p in pairs(rows or {}) do local item, give, nm, ic, co = row_bits(p) local bought, afford = 0, 0 bought = bought_of(C, shopType, p.id) local have = purse(p) local price = math.floor((p.costNum or 0) + 0) afford = ((have < 0) or (price <= 0) or (have >= price)) and 1 or 0 out[#out + 1] = table.concat({'common', tostring(shopType), tostring(p.id), tostring(item), ic, tostring(co), tostring(give), tostring(num(p.currencyType)), tostring(num(p.costNum)), tostring(num(p.maxTimes)), tostring(bought), tostring(reset), tostring(afford), flat(money_name(num(p.currencyType))), flat(nm), cost_item(p)}, ';;') end end local D = DataCenter.LWTitaniumBlueStoreManager if type(D) == 'table' and D.activityId ~= nil then local coin_name = '' pcall(function() coin_name = tostring(T:GetName(654001) or '') end) local coins = 0 pcall(function() for _, s in pairs(DataCenter.ItemData.ItemInfos or {}) do if tostring(s.itemId) == '654001' then coins = coins + num(s.num) + num(s.count) end end end) for _, p in pairs(D.productList or {}) do local item, give, kind = 0, 1, 0 for _, r in pairs(p.rewardList or {}) do item = num(r.itemId) give = num(r.count) kind = num(r.rewardType) end local nm, ic, co = item_bits(item) if kind == 27 or (nm == '' and ic == '') then local n2, i2, c2 = res_bits(item) if n2 ~= '' or i2 ~= '' then nm, ic, co = n2, i2, c2 end end local afford = (num(p.costNum) <= coins) and 1 or 0 out[#out + 1] = table.concat({'market', '0', tostring(p.id), tostring(item), ic, tostring(co), tostring(give), '654001', tostring(num(p.costNum)), tostring(num(p.buyTimeLimit)), tostring(num(p.buyTimes)), tostring(math.floor(num(p.nextResetTime))), tostring(afford), flat(coin_name), flat(nm), ''}, ';;') end end return table.concat(out, ' #|# ') end)() INTO shops

# THE STOREFRONTS THAT WANT MONEY are drawn and never pressed. A pack is bought through
# the platform's own purchase and there is no message on the wire that buys one, so the
# panel shows what the account is being offered — the picture, what it hands over, how
# long it runs — and offers no button at all. The PRICE is deliberately absent for the
# same reason: what a pack costs is the store's own number in the player's own money,
# and this side of the client never sees it.
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function flat(s) local out = tostring(s or '') out = out:gsub('%s+', ' ') out = out:gsub(';;', ' ') out = out:gsub('#|#', ' ') return out end local T = DataCenter.ItemTemplateManager local out = {} local M = DataCenter.WeekCardManager local list = nil pcall(function() list = M:GetWeekCardList() end) for _, c in pairs(list or {}) do local item, give = 0, 1 pcall(function() for _, r in pairs(c.showReward or c.reward or {}) do item = num(r.itemId) give = num(r.count) end end) local nm, ic, co = '', '', 0 pcall(function() nm = tostring(T:GetName(item) or '') end) pcall(function() local tpl = T:GetItemTemplate(item) ic = tostring(tpl.icon or '') co = num(tpl.color) end) out[#out + 1] = table.concat({'money', '1', tostring(c.id), tostring(item), ic, tostring(co), tostring(give), '0', '0', '0', '0', tostring(math.floor(num(c.endTime) / 1000)), '0', '', flat(nm), ''}, ';;') end return table.concat(out, ' #|# ') end)() INTO money

# THE PURSES — what every currency the shelves want is CALLED, what it LOOKS like and how
# much of it the account has (#2830). One record per currency, never per row:
#
#   cost_id;;have;;icon;;name
#
#   cost_id — the currency's own KEY, and it is a PAIR where the type does not name the
#             currency: `5` for the diamonds, `1004` for a resource, `7:900002` for an
#             item (#2830). `currencyType` of 7 means «paid with an item», and six
#             shelves are priced in six different items under that one number, so a
#             purse keyed by the type alone showed one balance for all of them.
#   have  — the balance, and **-1 means «the client will not show it»**, which is not
#           zero: a shelf paid in something this side of the client cannot count is
#           drawn without a number rather than with a wrong one (`docs/research/shops.md`).
#   icon  — the currency's own sprite, named the way every other picture here is named
#           (the file's stem, no path and no extension); empty when the client has no
#           picture for it, and the panel then draws the name alone. Never a stand-in.
#
# A CURRENCY IS READ FOUR WAYS, exactly as a row's price is: the diamonds off
# `LuaEntry.Player.gold`, a resource through `Resource:GetCntByResType`, and the two
# EXCHANGE shelves out of the bag by the row's own `currencyId` / `resourceitem_id`. A
# shelf may want SEVERAL currencies at once, so nothing here assumes one per shop.
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function flat(s) local out = tostring(s or '') out = out:gsub('%s+', ' ') out = out:gsub(';;', ' ') out = out:gsub('#|#', ' ') return out end local function base(path) local out = tostring(path or '') out = out:gsub('.*/', '') out = out:gsub('%.png$', '') return out end local C = DataCenter.CommonShopManager local R = DataCenter.ResourceManager local T = DataCenter.ItemTemplateManager local I = DataCenter.ResourceItemDataManager local function bag(id) local n = 0 pcall(function() for _, v in pairs(DataCenter.ItemData.ItemInfos or {}) do if tostring(v.itemId) == tostring(id) then n = n + math.floor((v.count or 0) + 0) + math.floor((v.num or 0) + 0) end end end) if n == 0 then pcall(function() n = math.floor((I:GetCountByItemId(math.floor(id + 0)) or 0) + 0) end) end return n end local function cost_item(p) local cid = tonumber(tostring(p.currencyId or '')) if cid ~= nil and cid > 0 then return math.floor(cid) end return nil end local function bag(id) local n = 0 pcall(function() for _, v in pairs(DataCenter.ItemData.ItemInfos or {}) do if tostring(v.itemId) == tostring(id) then n = n + num(v.count) + num(v.num) end end end) if n == 0 then pcall(function() n = num(DataCenter.ResourceItemDataManager:GetCountByItemId(num(id))) end) end return n end local function purse(P) local cur = num(P.currencyType) if cur == 5 then local g = 0 pcall(function() g = num(LuaEntry.Player.gold) end) return g end local cid = tonumber(tostring(P.currencyId or '')) if cid ~= nil and cid > 0 then return bag(math.floor(cid)) end local have = 0 pcall(function() have = num(LuaEntry.Resource:GetCntByResType(cur)) end) if have > 0 then return have end if cur == 40 then local h = -1 pcall(function() h = num(LuaEntry.Resource:GetHonorScore()) end) if h >= 0 then return h end end local nm = '' pcall(function() nm = tostring(DataCenter.ResourceManager:GetResourceNameByType(cur) or '') end) if nm ~= '' and nm:sub(1, 1) ~= '<' then return have end return -1 end local function item_name(id) local nm = '' pcall(function() nm = tostring(T:GetName(id) or '') end) if nm == '' then pcall(function() nm = tostring(I:GetName(id) or '') end) end if nm:sub(1, 1) == '<' then nm = '' end return nm end local function res_of(cur) if cur == 5 then return 15 end return cur end local function money_name(cur, P) local said = '' pcall(function() said = tostring(R:GetResourceNameByType(res_of(cur)) or '') end) if said:sub(1, 1) == '<' then said = '' end if said ~= '' then return said end local id = cost_item(P) if id ~= nil then return item_name(id) end return '' end local function money_icon(cur, P) local ic = '' pcall(function() ic = base(R:GetResourceIconByType(res_of(cur))) end) if ic ~= '' then return ic end local id = cost_item(P) if id ~= nil then pcall(function() ic = base((T:GetItemTemplate(id) or {}).icon) end) if ic == '' then pcall(function() ic = base(I:GetIconPath(id)) end) end end return ic end local order, held = {}, {} local function keep(key, have, icon, name) local was = held[key] if was == nil then order[#order + 1] = key held[key] = {have, icon, name} return end if was[1] < 0 and have >= 0 then was[1] = have end if was[2] == '' then was[2] = icon end if was[3] == '' then was[3] = name end end if type(C) == 'table' then for _, rows in pairs(C.goodsShopDic or {}) do for _, p in pairs(rows or {}) do local cur = num(p.currencyType) local id = cost_item(p) local key = tostring(cur) if id ~= nil then key = key .. ':' .. tostring(id) end keep(key, purse(p), money_icon(cur, p), money_name(cur, p)) end end end local D = DataCenter.LWTitaniumBlueStoreManager if type(D) == 'table' and D.activityId ~= nil then local ic = '' pcall(function() ic = base((T:GetItemTemplate(654001) or {}).icon) end) keep('654001', bag(654001), ic, item_name(654001)) end local out = {} for _, key in ipairs(order) do local v = held[key] out[#out + 1] = table.concat({key, tostring(v[1]), v[2], flat(v[3])}, ';;') end return table.concat(out, ' #|# ') end)() INTO purses

READ_LUA (function() local n = 0 local C = DataCenter.CommonShopManager for _, rows in pairs((C or {}).goodsShopDic or {}) do for _ in pairs(rows or {}) do n = n + 1 end end local D = DataCenter.LWTitaniumBlueStoreManager if type(D) == 'table' and D.activityId ~= nil then for _ in pairs(D.productList or {}) do n = n + 1 end end return n end)() INTO rows
LOG "магазины: прочитано товаров — {rows}"
