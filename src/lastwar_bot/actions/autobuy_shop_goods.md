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
#                  THE COUNT IS HOW MANY TO OWN IN ALL, not how many per run (#2670,
#                  the person's words: «логика количества не за прогон должна быть а
#                  вообще»). The errand tops the row up TO that number and stops: what
#                  is still wanted is `count - boughtTimes`, read out of the client's
#                  own counter rather than out of any bookkeeping of ours, so a row
#                  bought by hand in the game counts too. A row already at its number
#                  is stepped over in silence.
#                  A COUNT OF 0 MEANS «ALL OF IT» (#2670) — the tick «покупать всё» on
#                  the row: take as many as the row's own quota, the purse and the two
#                  ceilings below allow, rather than a number somebody typed. It is
#                  never «none»: a row is taken out of the order by dropping it from
#                  the list, which is what the tick «покупать автоматически» does.
#   caps         — the ceilings, ONE PER CURRENCY: «currency:limit», comma separated.
#                  The person's correction (#2670): «у каждого магазина своя валюта» —
#                  a single number over all the shelves added alliance points to
#                  diamonds to honour, which is not a sum anybody can mean. So the
#                  ceiling belongs to the CURRENCY a shelf spends, and it is drawn where
#                  it is spent (the gear beside the shop's own heading).
#                  A currency that is not named here has NO ceiling: it is earned by
#                  playing and cannot be bought, so the row's own quota is already the
#                  limit. `5:300` is the default and it is the diamonds, the one
#                  irreversible spend — the same 300 settled for the energy refill
#                  (#2390). `5:0` means «not one diamond», the same knob turned all the
#                  way down; `-1` says «no ceiling at all» for that currency.
#                  A ceiling TRIMS rather than drops: 300 over a row priced at 100 buys
#                  three, not none.
#   diamond_cap  — what `caps` used to be, and read only when `caps` says nothing, so a
#                  profile written before #2670 keeps the ceiling it had.
#   cap          — the most purchases one run may make at all, whatever the order says.
#
# WHAT IT SHIPS AS: switched OFF, with an empty order and a diamond ceiling of 300 — the
# number the person already settled for the energy refill (#2390), so the panel is not
# inventing a scale of its own. Nothing is spent until somebody turns the errand on, and
# the order and both ceilings are visible on «Магазин» and behind the gear on «Таймеры»
# before that happens.
#
# WHAT IT DOES, and the order is the whole of it: it walks the plan from the top, and for
# each row it takes as many as the row's own quota allows, as many as the ceilings allow,
# and only while the GAME says the account can pay (`CheckCostEnough` — a price paid out
# of two purses is the client's arithmetic, never this file's). A row it cannot afford is
# stepped over rather than ending the run: the next thing in the order may be cheaper,
# and that is exactly what an order of preference is for.
#
# HOW MANY OF A ROW ARE LEFT, and this is what the toast storm was (#2670). The
# person's report: «не покупается в магазине по приоритету, идут тосты что произошла
# ошибка и не хватает предметов». `CommonShopManager:GetShopGoodsNum(row)` answers 0
# for every row whatever has been bought — measured live — so the errand thought every
# quota was untouched, re-sent purchases the server had already given out, and the
# client showed a toast per refusal. The count IS in the client, one table further in:
#
#     CommonShopManager.goodsInfoDic[<shop type>][<row id>].boughtTimes
#
# Read live against an account that had spent them: `7/70035 5/5`, `7/70020 5/5`,
# `7/70030 1/1`, `7/70026 2500/2500`, `100/100001 10/10` — every one of which the old
# reading called 0. So the room is `maxTimes - boughtTimes`, and an exhausted row is
# stepped over in silence instead of being sent and refused.
#
# AND THE PURSE IS ASKED BEFORE ANYTHING IS SENT — a ceiling is not a balance, and the
# purse is not always where the first guess put it (#2670, the person's report: «первая
# покупка проходит, говорит что обмен успешен, дальше спамит что не хватает предметов»).
# A shelf can be paid FOUR different ways, and they were measured on the live account:
#
#   currency 5   → `LuaEntry.Player.gold`                    (diamonds, 32093)
#   1004         → `LuaEntry.Resource:GetCntByResType`       (alliance points, 90630)
#   7            → the row's `currencyId` as a BAG ITEM      (900002 → 49881 in the bag)
#   40           → the row's `resourceitem_id`               (7016 → 11 resource items)
#
# The last two are the EXCHANGE shelves — the ones whose success line says «обмен
# успешен» — and neither is in the resource table, so the old gate saw «0», called it
# «cannot see» and let every row through. That is the spam: one exchange goes out, the
# items are gone, and the rest of the order is sent anyway.
#
# AND THE BALANCE IS COUNTED DOWN AS THE ORDER IS WALKED. Every row is picked BEFORE the
# first message leaves, so the game cannot tell us what our own earlier picks have
# already promised — that is why the first purchase landed and the rest could not. Each
# pick now subtracts what it costs from the running purse (`paid`), so the second row of
# the same currency is judged against what would actually be left.
#
# WHAT A PURSE WE CANNOT READ BUYS: exactly ONE attempt per currency per run (`tried`).
# A number smaller than one price is treated the same way — the unit may not be what it
# looks like (honour reads 11 against a price of 30000) — so the run tries once and never
# spams. `CheckCostEnough` stays as the game's own second opinion.
#
# HOW IT KNOWS IT WORKED: by what the BAG holds, before and after. The shop's own
# bought-counter does not move for a purchase made this way — measured live, #2666 — so a
# proof that read it reported every working purchase as a failed one.
#
# EVERY LINE NAMES ITS SHELF (#2670). «Первый обмен проходит, но не в том магазине где
# нажимал» took a live hunt to find, and it would have been one line of the log if the
# offer had said which shop each row came off. It does now.
#
# IT SAYS THE PRICE FIRST. The line before anything is sent names every row it is about
# to buy, how many, and what that comes to — so a run that turns out wrong is visible in
# the log rather than only in the purse.
#
# The wire and the shape of a shelf are docs/research/shops.md.

ARGS plan =
ARGS caps = 5:300

ARGS diamond_cap = 300
ARGS cap = 20

# A PURCHASE ENDS IN A MODAL, AND THE MODAL IS SHUT BEHIND IT (#2670, the person's
# words: «после покупки закрывай модальные окна»). The panel presses headless, so
# nobody in front of the client asked for that window — it lands on top of the game
# anyway and stays there. The ear is the one from #2027/#2642: `watch_reward_popups`
# wraps the client's OWN reward-show and window-open calls, so a modal that arrives
# late is shut the instant it opens, by the client, with nothing asked of the game
# — and only a window the game itself has just called a reward for (`Reward` /
# `GetGift` in its name) can ever be closed by it. `DestroyAllWindow` is never used
# and never will be (`CLAUDE.md`): it takes the HUD with it and does not come back.
TAP watch_reward_popups

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local C = DataCenter.CommonShopManager local function bought_of(C, st, id) local n = 0 pcall(function() local g = (C.goodsInfoDic or {})[st] if g ~= nil then local r = g[id] or g[tostring(id)] or g[tonumber(id) or -1] if r ~= nil and r.boughtTimes ~= nil then n = math.floor(r.boughtTimes + 0) end end end) return n end local function purse(P) local cur = num(P.currencyType) local have = 0 if cur == 5 then pcall(function() have = num(LuaEntry.Player.gold) end) return have end pcall(function() have = num(LuaEntry.Resource:GetCntByResType(cur)) end) if have > 0 then return have end local function bag(id) local n = 0 pcall(function() for _, v in pairs(DataCenter.ItemData.ItemInfos or {}) do if tostring(v.itemId) == tostring(id) then n = n + num(v.count) + num(v.num) end end end) if n == 0 then pcall(function() n = num(DataCenter.ResourceItemDataManager:GetCountByItemId(num(id))) end) end return n end local cid = tostring(P.currencyId or '') if cid ~= '' then local n = bag(cid) if n > 0 then return n end end local rid = tostring(P.resourceitem_id or '') if rid ~= '' then return bag(rid) end return -1 end local plan = '{plan}' local order = {} for piece in plan:gmatch('[^,]+') do local bits = {} for b in piece:gmatch('[^:]+') do bits[#bits + 1] = b end if #bits >= 3 then order[#order + 1] = {kind = bits[1], shop = num(bits[2]), id = bits[3], count = math.max(0, num(bits[4] or '1'))} end end DataCenter.__lw_shop_plan = order local rows = {} local caps = {} local capstr = '{caps}' if capstr:match('%S') == nil then capstr = '5:' .. num('{diamond_cap}') end for piece in capstr:gmatch('[^,]+') do local a, b = piece:match('(%-?%d+)%s*:%s*(%-?%d+)') if a ~= nil then caps[num(a)] = num(b) end end local left = num('{cap}') if left < 1 then left = 1 end local spent = {} local paid = {} local tried = {} local picked = {} for _, e in ipairs(order) do if left <= 0 then break end local P = nil if e.kind == 'common' then for _, p in pairs((C.goodsShopDic or {})[e.shop] or {}) do if tostring(p.id) == e.id then P = p end end end if P ~= nil then local mine = bought_of(C, e.shop, P.id) local want = e.count if want < 1 then want = left else want = want - mine end if want > left then want = left end if num(P.maxTimes) > 0 then local room = num(P.maxTimes) - mine if want > room then want = room end end local cur0 = num(P.currencyType) local have = purse(P) local price0 = num(P.costNum) local used = paid[cur0] or 0 if want > 0 then if have < 0 then if tried[cur0] then want = 0 end elseif have == 0 then want = 0 elseif price0 > 0 and have >= price0 then local room = have - used if room < price0 then want = 0 else local fit = math.floor(room / price0) if want > fit then want = fit end end else if tried[cur0] then want = 0 elseif want > 1 then want = 1 end end end if want > 0 then tried[cur0] = true paid[cur0] = used + want * price0 end while want > 0 do local ok = false pcall(function() ok = (C:CheckCostEnough(P, want) == true) end) if ok then break end want = want - 1 end local cur = num(P.currencyType) local lim = caps[cur] if want > 0 and lim ~= nil and lim >= 0 then local price = num(P.costNum) local room = lim - (spent[cur] or 0) local fit = want if price > 0 then fit = math.floor(room / price) end if want > fit then want = fit end end if want > 0 then spent[cur] = (spent[cur] or 0) + want * num(P.costNum) end if want > 0 then left = left - want local gid, res = num(P.itemId), 0 if gid == 0 then local r = nil pcall(function() r = P:GetRewardData() end) if r ~= nil then gid = num(r.itemId) if num(r.rewardType) == 27 then res = 1 end end end picked[#picked + 1] = {row = P, n = want, gives = gid, res = res} local nm = '' pcall(function() nm = tostring(DataCenter.ItemTemplateManager:GetName(num(P.itemId)) or '') end) local cn = '' pcall(function() cn = tostring(DataCenter.ResourceManager:GetResourceNameByType(num(P.currencyType)) or '') end) if cn:sub(1, 1) == '<' then cn = 'валюта ' .. num(P.currencyType) end rows[#rows + 1] = 'магазин ' .. e.shop .. ': ' .. nm .. ' x' .. want .. ' за ' .. (want * num(P.costNum)) .. ' (' .. cn .. ')' end end end DataCenter.__lw_shop_picked = picked if #rows == 0 then return 'по очереди покупать нечего' end local sums = {} for cur, amount in pairs(spent) do local nm = '' pcall(function() nm = tostring(DataCenter.ResourceManager:GetResourceNameByType(cur) or '') end) if nm == '' or nm:sub(1, 1) == '<' then nm = 'валюта ' .. cur end local lim = caps[cur] sums[#sums + 1] = nm .. ' ' .. amount .. ((lim ~= nil and lim >= 0) and (' из ' .. lim) or '') end return 'собираюсь купить: ' .. table.concat(rows, '; ') .. ((#sums > 0) and (' (тратится: ' .. table.concat(sums, ', ') .. ')') or '') end)() INTO offer
LOG "автопокупка: {offer}"

READ_LUA (function() local picked = DataCenter.__lw_shop_picked or {} local n = 0 for _ in ipairs(picked) do n = n + 1 end return n end)() INTO lots

IF lots < 1
    LOG "автопокупка: ничего не отправлено"
    STOP

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local I = DataCenter.ResourceItemDataManager local picked = DataCenter.__lw_shop_picked or {} local held = {} local sent = 0 local function bag(e) local now = 0 if e.res == 1 then pcall(function() now = num(I:GetCountByItemId(e.gives)) end) else pcall(function() for _, v in pairs(DataCenter.ItemData.ItemInfos or {}) do if num(v.itemId) == e.gives then now = now + num(v.count) end end end) end return now end DataCenter.__lw_shop_bag = bag for i, e in ipairs(picked) do held[i] = bag(e) pcall(function() SFSNetwork.SendMessage(MsgDefines.BuyCommonShopGoods, e.row.id, {}, e.n) sent = sent + e.n end) end DataCenter.__lw_shop_held_all = held return sent end)() INTO sent
LOG "автопокупка: отправлено покупок — {sent}"
WAIT 4

READ_LUA (function() local picked = DataCenter.__lw_shop_picked or {} local held = DataCenter.__lw_shop_held_all or {} local bag = DataCenter.__lw_shop_bag local moved = 0 for i, e in ipairs(picked) do local now = held[i] or 0 if bag ~= nil then now = bag(e) end moved = moved + (now - (held[i] or 0)) end return moved end)() INTO bought
LOG "автопокупка: в сумке прибавилось — {bought}"

# …AND THE DRAIN, which says what was in the window and puts the ear back into a
# client that has restarted since the last one.
CALL collect_reward_popups
