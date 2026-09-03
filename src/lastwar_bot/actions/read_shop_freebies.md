# Read the shop: what it hands over for nothing, and how much of it is waiting today.
# ru: Чтение магазина: что он отдаёт бесплатно и сколько этого ждёт сегодня.
#
# HEADLESS. No window is opened, no tab is switched, no camera moves and no scene is
# required. Every gate below is the client's OWN record, filled at login and kept up to
# date by the server's pushes, so the whole reading is one VM round trip and not one
# question goes on the wire for it.
#
# WHAT «БЕСПЛАТНО» MEANS HERE, and it is the boundary of the whole ability: only what
# costs NOTHING is counted. Not diamonds, not gold bricks, not honour, not alliance
# coins, not coupons — a shop row with a price is a purchase and this recipe never makes
# one. The census of every shop tab and what each of them sells is
# `docs/research/shop-free-claims.md`; the short of it is that the eight tabs of the
# ordinary «Магазин» (UICommonShop) hold 175 goods and not one of them is free, and what
# IS free lives on the gift mall's week-card page.
#
# THE TWO THINGS THAT ARE FREE (both confirmed live on 2026-09-03, #2395):
#
#   * `free`  — the DAILY FREE GIFT of the week-card page. It is handed out whether or
#               not a card was ever bought, once a game day.
#               Gate: `DataCenter.WeekCardManager:CheckIfHasFreeReward()` — the game's
#               own answer about today, so this recipe keeps no «last taken» of its own,
#               consults no clock and has nothing to drift.
#   * `cards` — the daily reward of the week cards the account ALREADY HOLDS. Claiming it
#               spends nothing: the card was paid for once and pays out every day of its
#               week. Gate: each card's own `GetStatus()` — `1` not held or expired,
#               `2` held and today's reward still waiting, `3` held and today's taken.
#               Measured: a card read `2` before the claim and `3` immediately after.
#   * `month` — the same thing for the MONTH card, when one is running. Gate:
#               `MonthCardNewManager:CheckIfMonthCardActive()` and
#               `CheckIfHasGolloesGift()` — the second is the game's own answer about
#               today and it flipped to `false` the moment the claim landed.
#
# WHAT IS DELIBERATELY NOT COUNTED, because it is not free:
#
#   * the whole of `UICommonShop` — diamonds, VIP, alliance, honour, expedition, season,
#     skins, coupons: every row has a price;
#   * «Ежедневные спецпредложения» (`DailyMustBuyManager`): its ladder is climbed with
#     purchase points, so its rewards are behind money;
#   * the gold-brick store: gold bricks are a currency;
#   * anything that would SPEND — the whole of `UICommonShop`, the packs, the mall's
#     money tabs. A subscription is not in that list: buying one is a purchase, but
#     claiming what a running one owes costs nothing and is taken.
#
# Three more free-shaped claims answered the server with a shrug and are named in the
# research file rather than pressed: `receive.week.free.reward` and
# `receive.golloes.daily.free.reward` both said `success=true` and moved nothing, and
# `decoration.shop.receive.free.reward` came back `E000000` — which is a REFUSAL and not
# an «all clear»: the same code arrived with `errorMsg=already received` on a claim that
# had genuinely already been taken. A press nobody can tell from a refusal is not
# shipped.

# ---- one round trip: both gates, and the sentence for the log ----------------------
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter and DataCenter.WeekCardManager local t = {known = 0, free = 0, cards = 0, held = 0, month = 0, text = ''} DataCenter.__lw_shop = t local now = 0 pcall(function() now = num(UITimeManager.Instance:GetServerTime()) end) if now < 1600000000000 then t.text = 'клиент ещё на экране входа — ничего не прочитано' return t.text end if M == nil then t.text = 'у этого клиента нет записи о недельных картах' return t.text end local free = false pcall(function() free = (M:CheckIfHasFreeReward() == true) end) local held, due, rows = 0, 0, {} pcall(function() for _, c in pairs(M:GetWeekCardList() or {}) do local st = num(c:GetStatus()) if st == 2 or st == 3 then held = held + 1 end if st == 2 then due = due + 1 end rows[#rows + 1] = num(c.id) .. ':' .. st end end) local red = false pcall(function() red = (M:CheckIfHasRed() == true) end) local month, mcard = 0, false pcall(function() local MC = DataCenter.MonthCardNewManager if MC ~= nil and MC:CheckIfMonthCardActive() == true then mcard = true if MC:CheckIfHasGolloesGift() == true then month = 1 end end end) t.known = 1 t.free = free and 1 or 0 t.cards = due t.held = held t.month = month t.text = 'бесплатный подарок=' .. tostring(free) .. ' карт куплено=' .. held .. ' наград по картам=' .. due .. ' месячная карта=' .. (mcard and (month == 1 and 'ждёт' or 'сегодня забрана') or 'нет') .. ' значок=' .. tostring(red) .. ' [' .. table.concat(rows, ' ') .. ']' return t.text end)() INTO shop
LOG "Магазин: {shop}"

# ---- the readings the panel draws, one cheap field each -----------------------------
READ_LUA (math.floor((DataCenter.__lw_shop or {}).known or 0)) INTO known
READ_LUA (math.floor((DataCenter.__lw_shop or {}).free or 0)) INTO free_due
READ_LUA (math.floor((DataCenter.__lw_shop or {}).cards or 0)) INTO cards_due
READ_LUA (math.floor((DataCenter.__lw_shop or {}).held or 0)) INTO cards_held
READ_LUA (math.floor((DataCenter.__lw_shop or {}).month or 0)) INTO month_due
READ_LUA (function() local t = DataCenter.__lw_shop or {} return math.floor((t.free or 0) + (t.cards or 0) + (t.month or 0)) end)() INTO due
