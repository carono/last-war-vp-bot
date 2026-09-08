# Take everything the Glittering Market gives for nothing — the free diamonds and the rest.
# ru: Забрать всё бесплатное на «Сверкающем рынке» — алмазы и остальное.
#
# HEADLESS, and completely so: no window is opened, no tab is switched, nothing is
# tapped. Every press is the client's own send, made from the base or from the world map
# alike, and a run with nothing waiting is one VM round trip.
#
# NOTHING IS EVER BOUGHT. Not a diamond, not a Glitter Coin. The three things it takes
# are the daily free reward — 100 diamonds on the day the event was read
# (`docs/research/glittering-market.md`) — the shop rows the game itself prices at zero,
# and the progress chests the account has already earned. Spending coins is a different
# recipe and it is switched off (`actions/buy_glitter_market_goods.md`).
#
# WHAT ONE RUN DOES, in order:
#
#   1. reads the event (`CALL read_glittering_market`) and stops at once if the run is
#      over — the manager is empty between runs and there is nothing to press;
#   2. takes TODAY'S FREE REWARD when the game says it is still waiting —
#      `blue.shop.day.reward` with the run's `activityId` as its ONE bare argument. That
#      argument is the whole of it: sent bare, sent with `{}`, and sent with the id in a
#      table, the message moved nothing at all; sent with the id it moved
#      `dayRewardReceiveState` from 0 to 1 and paid out. Confirmed live 2026-09-08;
#   3. buys every row the shop prices at NOTHING that still has a quota, up to `cap` of
#      them in one run — `blue.shop.buy` with three bare arguments, the ids as STRINGS.
#      Confirmed live on a zero-cost row: `buyTimes` 0 → 1 → 2, and not one coin left the
#      bag because the row costs none;
#   4. claims any progress chest already earned — `blue.shop.box.reward`. This one is
#      NOT proven live: the account it was written on had no points and therefore no
#      claimable chest, so it is gated on the score AND on the game's own
#      `GetBoxRewardState` rather than sent blind;
#   5. reads the event back and reports what MOVED rather than what was sent.
#
# A REFUSAL IS NOT A SUCCESS. The server answers a claim it accepts by moving the record
# — the free gate flips, `buyTimes` goes up — and one it refuses by leaving it where it
# was. So the report names a gate still open afterwards as refused.
#
# NOT DETACHED. The whole run is a few seconds and nothing about it is a race.

ARGS free_reward = 1
ARGS free_goods = 1
ARGS boxes = 1
ARGS cap = 20

CALL read_glittering_market

IF open == 0
    LOG "Сверкающий рынок: акция не идёт — ничего не нажато"
    STOP

# ---- 1. today's free reward — the diamonds ------------------------------------------
IF free_reward == 1
    IF free_due > 0
        LUA pcall(function() local D = DataCenter.LWTitaniumBlueStoreManager SFSNetwork.SendMessage(MsgDefines.BlueShopDayReward, D.activityId) end)
        WAIT 2.5

# ---- 2. every row the shop prices at nothing ----------------------------------------
IF free_goods == 1
    IF goods_free > 0
        READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local D = DataCenter.LWTitaniumBlueStoreManager local sent = 0 local cap = {cap} for _, p in pairs(D.productList or {}) do local left = num(p.buyTimeLimit) - num(p.buyTimes) if num(p.costNum) == 0 and left > 0 then while left > 0 and sent < cap do pcall(function() SFSNetwork.SendMessage(MsgDefines.BlueShopBuy, D.activityId, p.id, 1) end) left = left - 1 sent = sent + 1 end end end return sent end)() INTO goods_sent
        LOG "Сверкающий рынок: бесплатных товаров запрошено {goods_sent}"
        WAIT 3.5

# ---- 3. the progress chests already earned ------------------------------------------
IF boxes == 1
    IF boxes_due > 0
        READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local D = DataCenter.LWTitaniumBlueStoreManager local taken = {} for _, v in pairs(D.boxReceiveList or {}) do taken[tostring(v)] = true end local score = num(D.totalScore) local sent = 0 for _, b in pairs(D.boxRewardsList or {}) do local idx = num(b.index) local st = -1 pcall(function() st = num(D:GetBoxRewardState(idx)) end) if score >= num(b.targetCount) and not taken[tostring(idx)] and st ~= 2 then pcall(function() SFSNetwork.SendMessage(MsgDefines.BlueShopBoxReward, D.activityId, idx) end) sent = sent + 1 end end return sent end)() INTO box_sent
        LOG "Сверкающий рынок: сундуков прогресса запрошено {box_sent}"
        WAIT 3

# ---- what actually moved -------------------------------------------------------------
READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local was = DataCenter.__lw_market or {} local D = DataCenter.LWTitaniumBlueStoreManager local said = {} local can = false pcall(function() can = (D.activityFreeRewardData:CanGetFreePack() == true) end) local still = (can and num(D.dayRewardReceiveState) == 0) and 1 or 0 if num(was.free) == 1 then said[#said + 1] = 'бесплатная награда=' .. (still == 1 and 'ОТКАЗАНО — всё ещё ждёт' or 'забрана') else said[#said + 1] = 'бесплатная награда=сегодня уже забрана' end local left = 0 for _, p in pairs(D.productList or {}) do if num(p.costNum) == 0 then left = left + math.max(0, num(p.buyTimeLimit) - num(p.buyTimes)) end end local wasg = num(was.goods) if wasg > 0 then said[#said + 1] = 'бесплатные товары=' .. (wasg - left) .. ' из ' .. wasg .. ' (осталось ' .. left .. ')' else said[#said + 1] = 'бесплатные товары=нечего брать' end local taken = {} for _, v in pairs(D.boxReceiveList or {}) do taken[tostring(v)] = true end local due = 0 local score = num(D.totalScore) for _, b in pairs(D.boxRewardsList or {}) do local idx = num(b.index) if score >= num(b.targetCount) and not taken[tostring(idx)] then due = due + 1 end end local wasb = num(was.boxes) if wasb > 0 then said[#said + 1] = 'сундуки=' .. (wasb - due) .. ' из ' .. wasb .. (due > 0 and (' (ОТКАЗАНО ' .. due .. ')') or '') else said[#said + 1] = 'сундуки=нечего забирать' end return table.concat(said, ' ') end)() INTO taken
LOG "Сверкающий рынок, итог: {taken}"

# ---- and the readings the card draws, off the state as it is NOW ---------------------
CALL read_glittering_market
