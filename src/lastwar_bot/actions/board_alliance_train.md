# Board a carriage of the alliance train and pay the fare.
# ru: Сесть в вагон поезда альянса и оплатить проезд.
#
# The whole ability, in one file: the gates, the boarding and the fare. The panel plays
# it and draws what came back; it holds none of this itself (`CLAUDE.md`).
#
# WHAT THE GAME CALLS THIS. A train arrives at the alliance station and stands there
# with no driver until an R4 or R5 appoints a CONDUCTOR («машинист»). From that moment
# the rest of the alliance may queue up in one of its carriages, and the train leaves on
# a clock. Boarding is free; what the passenger then offers the conductor is the fare —
# a like, which costs nothing, or up to three Trade Contracts («билеты на грузовики»,
# the same item that refreshes a trade truck). The protocol, and how every one of these
# numbers was found, is docs/research/alliance-train.md.
#
# THE FARE IS NEVER PAID IN DIAMONDS. The game offers to buy the missing contracts for
# diamonds when the bag is short, and this recipe does not take that offer: `tickets` is
# clamped to what the bag actually holds, and a run that could not afford the whole fare
# sends the like instead and says so. Spending a player's diamonds is not something a
# standing order may do quietly (`CLAUDE.md`), so it is not done at all.
#
#     run_action("board_alliance_train", variables={"carriage": 2, "tickets": 1})
#
# Every step is a no-op when it has nothing to do: no train, no conductor yet, already in
# a carriage, fare already paid. So the trigger that plays this on every platform push
# costs one round trip and says nothing when there is nothing to say.

# Which carriage to queue in, as the player sees them — 1 is the first one behind the
# locomotive. Clamped to the carriages this train actually has.
ARGS carriage = 1

# What to offer the conductor: 0 is a like and costs nothing, 1..3 are Trade Contracts
# out of the bag.
ARGS tickets = 0

# Whether a SHORT fare may be made up out of the player's diamonds. `0` — the default and
# what the panel ships — pays only out of the bag. `1` is the person having ticked
# «докупать, если не хватает» on the card, and even then the purchase is capped by
# `tickets` and never goes one contract past it.
#
# **The purchase itself is not made yet, and this recipe will not guess it.** The command
# behind the game's own «buy» is `alliance.train.buy`, and what it buys has NOT been
# confirmed against a live train — `UITrainBuy` also serves the conductor's Mega Express,
# which is a far larger spend. So with `buy = 1` and a short bag this says so and pays
# what the bag holds; it does not send a message it cannot yet prove the price of. One
# live confirmation turns this into the purchase (`docs/research/alliance-train.md`).
ARGS buy = 0

# 1. Park what the caller asked for. `{carriage}` and `{tickets}` are substituted before
#    the script is parsed, so everything below reads them off the game's own table.
LUA local M = DataCenter.LWAllyStationDataManager local c = ({carriage}) + 0 local t = ({tickets}) + 0 local b = ({buy}) + 0 if c < 1 then c = 1 end if t < 0 then t = 0 end if t > 3 then t = 3 end M.__lw_train_car = c M.__lw_train_want = t M.__lw_train_buy = b M.__lw_train_pay = 0 M.__lw_train_short = 0

# 2. Is there an alliance train to board at all?
READ_LUA (function() local M = DataCenter.LWAllyStationDataManager if M == nil then return 0 end local function yes(f) local ok, v = pcall(f) return (ok and v) and 1 or 0 end if yes(function() return (M:IsTrainActivityOpen()) end) == 0 then return 0 end if yes(function() return (M:IsTrainClosed()) end) == 1 then return 0 end if yes(function() return (M:IsTrainFunctionLock()) end) == 1 then return 0 end return 1 end)() INTO open
IF open == 0
    STOP "the alliance train is not running — nothing to board"

# 3. A train with no conductor cannot be boarded: the queue opens when one is appointed.
READ_LUA (function() local p = nil pcall(function() p = DataCenter.LWAllyStationDataManager:GetPlatform(1) end) if type(p) ~= 'table' then return -1 end local ok, v = pcall(function() return p.state + 0 end) if ok then return v end return -1 end)() INTO state
IF state < 2
    STOP "no conductor appointed yet — nothing to board"

# 4. Get in the carriage, unless we are in one already.
READ_LUA (function() local p = nil pcall(function() p = DataCenter.LWAllyStationDataManager:GetPlatform(1) end) if type(p) ~= 'table' then return -1 end return (p.meInQueue == true) and 1 or 0 end)() INTO queued
IF queued == 0
    LUA local M = DataCenter.LWAllyStationDataManager local c = M.__lw_train_car or 1 local cars = 0 pcall(function() for _, x in pairs(M:GetTrainByPlatformId(1).carriages or {}) do local id = 0 pcall(function() id = x.carriageId + 0 end) if id > cars then cars = id end end end) if cars > 0 and c > cars then c = cars end M.__lw_train_car = c pcall(function() SFSNetwork.SendMessage(MsgDefines.AllianceTrainLineUp, c) end)
    WAIT 3
    READ_LUA (function() local p = nil pcall(function() p = DataCenter.LWAllyStationDataManager:GetPlatform(1) end) if type(p) ~= 'table' then return -1 end return (p.meInQueue == true) and 1 or 0 end)() INTO queued
    IF queued == 0
        FAIL "the game refused the carriage — retry later"

# 5. The fare. Once per train, and only if nobody has paid it yet — by this panel or by
#    the person playing. What the fare WOULD be is worked out first — it only reads the
#    bag and parks the number, so the line below can name it either way.
READ_LUA (function() local M = DataCenter.LWAllyStationDataManager local want = M.__lw_train_want or 0 local have = 0 pcall(function() for _, s in pairs(DataCenter.ItemData.ItemInfos or {}) do if type(s) == 'table' and tostring(s.itemId) == '1520001' then local c = 0 pcall(function() c = s.count + 0 end) have = have + c end end end) local pay = want if pay > have then pay = have end if pay < 0 then pay = 0 end local short = want - pay if short < 0 then short = 0 end M.__lw_train_pay = pay M.__lw_train_have = have M.__lw_train_short = short return pay end)() INTO pay
READ_LUA (function() return (DataCenter.LWAllyStationDataManager.__lw_train_short or 0) end)() INTO short
IF short > 0
    LOG "alliance train: the bag is {short} trade contract(s) short of the fare of {tickets} — paying what it holds. Buying them for diamonds is not done: «докупать» is on={buy}, and the purchase command is not confirmed live yet (docs/research/alliance-train.md)."
READ_LUA (function() local M = DataCenter.LWAllyStationDataManager local ok, v = pcall(function() return (M:AlreadyThumbsUp()) end) if not ok then return -1 end return v and 1 or 0 end)() INTO thanked
IF thanked == 0
    LUA local M = DataCenter.LWAllyStationDataManager local pay = M.__lw_train_pay or 0 local idx = 0 pcall(function() idx = (M:RandomThanksLangIndex()) + 0 end) pcall(function() SFSNetwork.SendMessage(MsgDefines.AllianceTrainThumbsUp, 1, pay, idx) end)
    WAIT 3
    READ_LUA (function() local M = DataCenter.LWAllyStationDataManager local ok, v = pcall(function() return (M:AlreadyThumbsUp()) end) if not ok then return -1 end return v and 1 or 0 end)() INTO thanked

# 6. Say what was done, in numbers a person can check against the game.
READ_LUA (function() return (DataCenter.LWAllyStationDataManager.__lw_train_car or 0) end)() INTO car
READ_LUA (function() return (DataCenter.LWAllyStationDataManager.__lw_train_have or 0) end)() INTO have
LOG "alliance train: carriage {car}, fare {pay} of {tickets} (bag holds {have}), thanked={thanked}"
