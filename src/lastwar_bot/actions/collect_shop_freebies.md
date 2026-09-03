# Take everything the shop gives for nothing: the daily free gift and the week cards' daily reward.
# ru: Забрать всё, что магазин отдаёт бесплатно: ежедневный подарок и награду недельных карт.
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
#   4. reads the gates back and reports what MOVED rather than what was sent.
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

# ---- what actually moved ------------------------------------------------------------
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local was = DataCenter.__lw_shop or {} local M = DataCenter.WeekCardManager local free = false pcall(function() free = (M:CheckIfHasFreeReward() == true) end) local due = 0 pcall(function() for _, c in pairs(M:GetWeekCardList() or {}) do if num(c:GetStatus()) == 2 then due = due + 1 end end end) local said = {} if num(was.free) == 1 then said[#said + 1] = 'подарок=' .. (free and 'ОТКАЗАНО — всё ещё предлагается' or 'забран') else said[#said + 1] = 'подарок=сегодня не предлагался' end local wasdue = num(was.cards) if wasdue > 0 then said[#said + 1] = 'карты=' .. (wasdue - due) .. ' из ' .. wasdue .. (due > 0 and (' (ОТКАЗАНО ' .. due .. ')') or '') else said[#said + 1] = 'карты=нечего забирать' end return table.concat(said, ' ') end)() INTO taken
LOG "Магазин, итог: {taken}"

# ---- and the readings the page draws, off the state as it is NOW --------------------
CALL read_shop_freebies
