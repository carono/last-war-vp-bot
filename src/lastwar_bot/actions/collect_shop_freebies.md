# Take everything the shop gives for nothing: the gifts, the cards, the battle pass, the free spins.
# ru: Забрать всё бесплатное в магазине: подарки, карты, ступени пропуска и бесплатные попытки.
#
# HEADLESS, and completely so: no window is opened, no tab is switched, no marker is
# tapped and no scene is required. Both presses are the client's own send, made from the
# base or from the world map alike, and a run with nothing waiting is one VM round trip.
#
# NOTHING IS EVER BOUGHT. Not a diamond, not a gold brick, not an honour point, not a
# coupon — see `read_shop_freebies` for what «free» means here and
# `docs/research/shop-free-claims.md` for the census of every shop tab that led to it.
#
# WHAT ONE RUN DOES, in the order it does it:
#
#   1. reads both gates (`CALL read_shop_freebies`, which is where every line in the log
#      about the shop comes from);
#   2. takes the DAILY FREE GIFT of the week-card page when the game says one is on
#      offer — `receive.week.card.daily.free.reward`, no payload;
#   3. takes the daily reward of every week card the account already holds —
#      `receive.all.week.card.reward`, one message for all of them, no payload;
#   4. takes the MONTH card's daily reward when a card is running —
#      `month.card.reward`, **with the card's own `monthCardId` as its one argument**.
#      That argument is the whole of it: the same message sent bare was answered by
#      silence and moved nothing, and sent with the id it came back with the reward, the
#      gold and `push.resource.item.update`, and `CheckIfHasGolloesGift()` flipped to
#      `false`. Buying a subscription is a purchase; claiming what a running one owes is
#      free, and a day it is not claimed is a day of it thrown away;
#   5. takes the BATTLE PASS ladder of every event pass that is running —
#      `receive.bpv2.all.reward`, ONE message per pass and no level list: the server
#      hands over everything the account has earned and left unclaimed, on the free track
#      always and on the premium one when it has been unlocked. Nothing is bought: the
#      paid way up the ladder is `buy.battle.pass.level` and this recipe never sends it.
#      When a pass is at its last level and has the experience for it, the overflow box
#      goes with it (`receive.bpv2.extra.reward`);
#   6. takes the DECORATION SHOP's free spin when its own counter says there is an
#      attempt left — `decoration.shop.receive.free.reward`, with the shop row's `id` as
#      its one field. The attempt is free; nothing is bought, and the skins the shop
#      SELLS are never touched;
#   7. takes the free reward of the recharge page when the game says one is on offer
#      today — `receive.week.free.reward`, no payload. Its gate is daily, not a purchase
#      score;
#   8. takes the GOLLOES CAMP's daily free one when the camp offers it —
#      `receive.golloes.daily.free.reward`, no payload;
#   9. reads the gates back and reports what MOVED rather than what was sent.
#
# THE LAST THREE ARE GATED AND WERE ALL CLOSED THE DAY THEY WERE ADDED (2026-09-04): the
# decoration shop was not even selling, the recharge one had been taken earlier that game
# day, and the camp was empty. That is the whole reason they are gated rather than sent
# blind — an earlier pass sent all three with no gate, and a `success=true` that moves
# nothing is indistinguishable from a claim.
#
# A REFUSAL IS NOT A SUCCESS. The server answers a claim it accepts by pushing the record
# back — the free gate flips to `false`, a card's status goes from `2` to `3` — and one it
# refuses by leaving them where they were. So the recipe never reports the SEND: it
# presses, waits for the record, and names a gate still open afterwards as refused.
#
# Confirmed live on 2026-09-03 (#2395): the free gift moved `free=true → false` with
# `push.resource.item.update` beside it, and the card claim moved one card `status 2 → 3`
# with `reward` in the reply.
#
# NOT DETACHED. The whole run is a few seconds, nothing about it is a race, and it takes
# its ordinary turn in the queue.

ARGS free_gift = 1
ARGS card_daily = 1
ARGS month_card = 1
ARGS battle_pass = 1
ARGS decoration_free = 1
ARGS recharge_free = 1
ARGS golloes_free = 1

# ---- what the game says is waiting -------------------------------------------------
CALL read_shop_freebies

IF known == 0
    LOG "Магазин: игра не отвечает — ничего не нажато"
    STOP

# ---- 1. the daily free gift of the week-card page ----------------------------------
IF free_gift == 1
    IF free_due > 0
        LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.ClaimWeekCardFreeReward) end)
        WAIT 2.5

# ---- 2. the daily reward of the cards already held ---------------------------------
IF card_daily == 1
    IF cards_due > 0
        LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.ClaimAllWeekCardRewardMessage) end)
        WAIT 2.5

# ---- 3. the month card's daily reward, when one is running --------------------------
IF month_card == 1
    IF month_due > 0
        LUA pcall(function() local c = DataCenter.MonthCardNewManager:GetGolloesMonthCard() SFSNetwork.SendMessage(MsgDefines.ClaimGolloesDailyReward, c.monthCardId) end)
        WAIT 2.5

# ---- 4. the battle pass: one message per running pass, both tracks it has earned ------
IF battle_pass == 1
    IF pass_due > 0
        READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.ActBattlePassData local sent = 0 for id, _ in pairs((M or {}).list or {}) do local red = 0 pcall(function() red = num(M:GetActRed(id)) end) if red > 0 then pcall(function() SFSNetwork.SendMessage(MsgDefines.NewReceiveBPAllReward, id) end) sent = sent + 1 end end return sent end)() INTO pass_sent
        LOG "Боевой пропуск: запрошено пропусков {pass_sent}"
        WAIT 3.5
    IF pass_extra > 0
        READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.ActBattlePassData local sent = 0 for id, v in pairs((M or {}).list or {}) do local bp = v.battlePass or {} local stages = 0 pcall(function() for i, _ in pairs(v.stateInfo or {}) do local k = num(i) if k > stages then stages = k end end end) local need = num(v.extraExp) if stages > 0 and num(bp.level) >= stages and need > 0 and num(bp.exp) >= need then pcall(function() SFSNetwork.SendMessage(MsgDefines.NewReceiveBPExtraReward, id) end) sent = sent + 1 end end return sent end)() INTO extra_sent
        LOG "Боевой пропуск: сверхнаград запрошено {extra_sent}"
        WAIT 3

# ---- 5. the decoration shop's free spin, when an attempt is left ---------------------
IF decoration_free == 1
    IF dec_due > 0
        LUA pcall(function() local d = DataCenter.CommonShopManager.decorationShopDic[150] SFSNetwork.SendMessage(MsgDefines.DecorationShopReceiveFreeReward, {id = d.id}) end)
        WAIT 2.5

# ---- 6. the free reward of the recharge page, when today's is still waiting ----------
IF recharge_free == 1
    IF week_free_due > 0
        LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.BuyFreeWeeklyPackage) end)
        WAIT 2.5

# ---- 7. the golloes camp's daily free one -------------------------------------------
IF golloes_free == 1
    IF golloes_due > 0
        LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.ClaimGolloesFreeReward) end)
        WAIT 2.5

# ---- what actually moved ------------------------------------------------------------
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local was = DataCenter.__lw_shop or {} local M = DataCenter.WeekCardManager local free = false pcall(function() free = (M:CheckIfHasFreeReward() == true) end) local due = 0 pcall(function() for _, c in pairs(M:GetWeekCardList() or {}) do if num(c:GetStatus()) == 2 then due = due + 1 end end end) local said = {} if num(was.free) == 1 then said[#said + 1] = 'подарок=' .. (free and 'ОТКАЗАНО — всё ещё предлагается' or 'забран') else said[#said + 1] = 'подарок=сегодня не предлагался' end local wasdue = num(was.cards) if wasdue > 0 then said[#said + 1] = 'карты=' .. (wasdue - due) .. ' из ' .. wasdue .. (due > 0 and (' (ОТКАЗАНО ' .. due .. ')') or '') else said[#said + 1] = 'карты=нечего забирать' end local mleft = false pcall(function() local MC = DataCenter.MonthCardNewManager mleft = (MC:CheckIfMonthCardActive() == true) and (MC:CheckIfHasGolloesGift() == true) end) if num(was.month) == 1 then said[#said + 1] = 'месячная карта=' .. (mleft and 'ОТКАЗАНО — всё ещё ждёт' or 'забрана') else said[#said + 1] = 'месячная карта=нечего забирать' end local X = DataCenter.__lw_shop_x or {} if num(X.dec) == 1 then local left = 0 pcall(function() local d = DataCenter.CommonShopManager.decorationShopDic[150] left = num(d.freeCount) end) said[#said + 1] = 'облики=' .. (left > 0 and 'ОТКАЗАНО — попытка на месте' or 'покручено') else said[#said + 1] = 'облики=нечего крутить' end if num(X.week) == 1 then local open = 0 pcall(function() local R = DataCenter.RechargeManager for k = 0, 8 do if R:GetIsCanReceiveFreeReward(k) == true then open = open + 1 end end end) said[#said + 1] = 'страница пополнения=' .. (open > 0 and 'ОТКАЗАНО — всё ещё предлагается' or 'забрано') else said[#said + 1] = 'страница пополнения=нечего забирать' end if num(X.gol) == 1 then local still = false pcall(function() still = (DataCenter.GolloesCampManager:CheckIfCanClaimFreeGolloes() == true) end) said[#said + 1] = 'лагерь Golloes=' .. (still and 'ОТКАЗАНО — всё ещё ждёт' or 'забран') else said[#said + 1] = 'лагерь Golloes=нечего забирать' end local B = DataCenter.__lw_shop_bp or {} local wasbp = num(B.due) if wasbp > 0 then local left = 0 local P = DataCenter.ActBattlePassData pcall(function() for id, _ in pairs((P or {}).list or {}) do left = left + num(P:GetActRed(id)) end end) said[#said + 1] = 'боевой пропуск=' .. (wasbp - left) .. ' из ' .. wasbp .. (left > 0 and (' (ОТКАЗАНО ' .. left .. ')') or '') else said[#said + 1] = 'боевой пропуск=' .. (num(B.acts) == 0 and 'не идёт' or 'нечего забирать') end return table.concat(said, ' ') end)() INTO taken
LOG "Магазин, итог: {taken}"

# ---- and the readings the page draws, off the state as it is NOW --------------------
CALL read_shop_freebies
