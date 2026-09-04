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
# THE SEVEN THINGS THAT ARE FREE (the first four confirmed live on 2026-09-03; the
# last three are gates read live on 2026-09-04 and all three were closed that day, #2395):
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
#   * `pass`  — the BATTLE PASS of whatever event is running («Акция» in the gift mall).
#               Its ladder hands out a reward at every level the account has reached, and
#               claiming one costs nothing: the levels are earned by playing, and the
#               premium track is claimed for free once it has been unlocked. Gate:
#               `DataCenter.ActBattlePassData:GetActRed(activityId)` — the game's own
#               count of rewards still owed on that pass, `0` when there is nothing.
#               Two passes were running when this was written and the census of them is
#               in the research file; the recipe never names one — it walks
#               `ActBattlePassData.list`, so a pass that starts tomorrow is read too.
#               NOT counted, and never pressed: `buy.battle.pass.level`, which is the
#               paid way up the ladder, and the premium track of a pass that has NOT been
#               unlocked — the game leaves those rewards out of `GetActRed` by itself.
#
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
#   * `dec`   — the DECORATION SHOP's free spin. The shop-of-skins row carries its own
#               free-attempt counter, and using it costs nothing but the attempt.
#               Gate: `CommonShopManager.decorationShopDic[150]` — `freeCount > 0` AND
#               `freeRewardId > 0`. Both read `0` on 2026-09-04 with the shop not even
#               selling (`IsSaleInDecorationShop()` = `false`, no goods loaded), and
#               asking the server for the page (`RequestDecorationShopInfo`) did not
#               change them: there was no attempt to spend, which is why the claim was
#               refused when it was pressed by hand. `GetActHasFreeDailyReward(1051010)`
#               reads `true` the whole time and is NOT the gate — it is the activity's
#               advertisement, not the account's counter.
#   * `week`  — the free reward of the recharge page, `receive.week.free.reward`.
#               It looked like a purchase reward and it is not: its gate is a DAILY one.
#               `RechargeManager:GetIsCanReceiveFreeReward(type)` over types `0…8`, and
#               `RechargeManager.freeRewardInfoDic` holds the stamp of when each type was
#               last taken — on 2026-09-04 type `1` read `1788517530`, which is after
#               that game day's zero, so it had been claimed already that day and the
#               gate was closed for it. Only type `1` has a reward id at all
#               (`GetFreeRewardIdByType`), and the message itself carries NO payload:
#               built in memory it puts not one field on the wire.
#   * `gol`   — the GOLLOES CAMP's daily free one, `receive.golloes.daily.free.reward`.
#               It is NOT the month card's reward (§4.3 sends `month.card.reward`, whose
#               `MsgDefines` name merely also says «Golloes»); it belongs to the camp —
#               `DataCenter.GolloesCampManager` — and its gate is that manager's own
#               `CheckIfCanClaimFreeGolloes()`. It read `false` on 2026-09-04 with the
#               whole camp empty (`GetGolloesCount()` = 0, trader and explorer states 0),
#               which is why the send used to answer `success=true` and move nothing:
#               there was nothing to give. The message carries no payload either.
#
# ALL THREE ARE GATED AND NONE OF THEM SPENDS. A gate that reads «nothing on offer» is
# reported as such and no message leaves — the earlier passes sent them blind, which is
# exactly what made a refusal look like a success.

# ---- one round trip: both gates, and the sentence for the log ----------------------
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter and DataCenter.WeekCardManager local t = {known = 0, free = 0, cards = 0, held = 0, month = 0, text = ''} DataCenter.__lw_shop = t local now = 0 pcall(function() now = num(UITimeManager.Instance:GetServerTime()) end) if now < 1600000000000 then t.text = 'клиент ещё на экране входа — ничего не прочитано' return t.text end if M == nil then t.text = 'у этого клиента нет записи о недельных картах' return t.text end local free = false pcall(function() free = (M:CheckIfHasFreeReward() == true) end) local held, due, rows = 0, 0, {} pcall(function() for _, c in pairs(M:GetWeekCardList() or {}) do local st = num(c:GetStatus()) if st == 2 or st == 3 then held = held + 1 end if st == 2 then due = due + 1 end rows[#rows + 1] = num(c.id) .. ':' .. st end end) local red = false pcall(function() red = (M:CheckIfHasRed() == true) end) local month, mcard = 0, false pcall(function() local MC = DataCenter.MonthCardNewManager if MC ~= nil and MC:CheckIfMonthCardActive() == true then mcard = true if MC:CheckIfHasGolloesGift() == true then month = 1 end end end) t.known = 1 t.free = free and 1 or 0 t.cards = due t.held = held t.month = month t.text = 'бесплатный подарок=' .. tostring(free) .. ' карт куплено=' .. held .. ' наград по картам=' .. due .. ' месячная карта=' .. (mcard and (month == 1 and 'ждёт' or 'сегодня забрана') or 'нет') .. ' значок=' .. tostring(red) .. ' [' .. table.concat(rows, ' ') .. ']' return t.text end)() INTO shop
LOG "Магазин: {shop}"

# ---- the battle pass of whatever event is running, in one more round trip ------------
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter and DataCenter.ActBattlePassData local t = {due = 0, acts = 0, extra = 0, text = ''} DataCenter.__lw_shop_bp = t if M == nil or M.list == nil then t.text = 'боевого пропуска у этого клиента нет' return t.text end local rows = {} for id, v in pairs(M.list) do local bp = v.battlePass or {} local red = 0 pcall(function() red = num(M:GetActRed(id)) end) local stages = 0 pcall(function() for i, _ in pairs(v.stateInfo or {}) do local k = num(i) if k > stages then stages = k end end end) local lv = num(bp.level) local exp = num(bp.exp) local need = num(v.extraExp) local unl = num(bp.unlock) local extra = 0 if stages > 0 and lv >= stages and need > 0 and exp >= need then extra = 1 end t.due = t.due + red t.extra = t.extra + extra t.acts = t.acts + 1 rows[#rows + 1] = tostring(id) .. ': ступень ' .. lv .. '/' .. stages .. ' ждёт ' .. red .. (unl == 1 and ', платная дорожка открыта' or ', только бесплатная дорожка') .. (extra == 1 and ', есть сверхнаграда' or '') end if t.acts == 0 then t.text = 'сейчас не идёт ни один боевой пропуск' else t.text = 'пропусков ' .. t.acts .. ', ждёт наград ' .. t.due .. ' [' .. table.concat(rows, '; ') .. ']' end return t.text end)() INTO pass
LOG "Боевой пропуск: {pass}"

# ---- the three claims that are open only some days, in one more round trip -----------
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local t = {dec = 0, week = 0, gol = 0, text = ''} DataCenter.__lw_shop_x = t local rows = {} local dec_id = 0 pcall(function() local d = DataCenter.CommonShopManager.decorationShopDic[150] if d ~= nil and num(d.freeCount) > 0 and num(d.freeRewardId) > 0 then t.dec = 1 dec_id = num(d.id) end rows[#rows + 1] = 'облики: попыток ' .. num((d or {}).freeCount) .. (t.dec == 1 and ', есть что крутить' or ', крутить нечего') end) t.dec_id = dec_id local wtypes = {} pcall(function() local R = DataCenter.RechargeManager for k = 0, 8 do local can = false pcall(function() can = (R:GetIsCanReceiveFreeReward(k) == true) end) if can then wtypes[#wtypes + 1] = k end end end) t.week = #wtypes > 0 and 1 or 0 rows[#rows + 1] = 'страница пополнения: ' .. (t.week == 1 and ('ждёт (тип ' .. table.concat(wtypes, ',') .. ')') or 'сегодня уже забрано или нечего') pcall(function() local G = DataCenter.GolloesCampManager if G ~= nil and G:CheckIfCanClaimFreeGolloes() == true then t.gol = 1 end rows[#rows + 1] = 'лагерь Golloes: ' .. (t.gol == 1 and 'ждёт' or 'нечего') end) t.text = table.concat(rows, ' | ') return t.text end)() INTO extra
LOG "Магазин, редкое: {extra}"

# ---- the readings the panel draws, one cheap field each -----------------------------
READ_LUA (math.floor((DataCenter.__lw_shop or {}).known or 0)) INTO known
READ_LUA (math.floor((DataCenter.__lw_shop or {}).free or 0)) INTO free_due
READ_LUA (math.floor((DataCenter.__lw_shop or {}).cards or 0)) INTO cards_due
READ_LUA (math.floor((DataCenter.__lw_shop or {}).held or 0)) INTO cards_held
READ_LUA (math.floor((DataCenter.__lw_shop or {}).month or 0)) INTO month_due
READ_LUA (math.floor((DataCenter.__lw_shop_bp or {}).due or 0)) INTO pass_due
READ_LUA (math.floor((DataCenter.__lw_shop_bp or {}).acts or 0)) INTO pass_acts
READ_LUA (math.floor((DataCenter.__lw_shop_bp or {}).extra or 0)) INTO pass_extra
READ_LUA (math.floor((DataCenter.__lw_shop_x or {}).dec or 0)) INTO dec_due
READ_LUA (math.floor((DataCenter.__lw_shop_x or {}).week or 0)) INTO week_free_due
READ_LUA (math.floor((DataCenter.__lw_shop_x or {}).gol or 0)) INTO golloes_due
READ_LUA (function() local t = DataCenter.__lw_shop or {} local b = DataCenter.__lw_shop_bp or {} local x = DataCenter.__lw_shop_x or {} return math.floor((t.free or 0) + (t.cards or 0) + (t.month or 0) + (b.due or 0) + (b.extra or 0) + (x.dec or 0) + (x.week or 0) + (x.gol or 0)) end)() INTO due
