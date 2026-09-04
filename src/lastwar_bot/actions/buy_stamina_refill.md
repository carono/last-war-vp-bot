# Buy the day's refill of march energy for diamonds, once per server day.
# ru: Докупить суточное пополнение энергии марша за алмазы, один раз за игровые сутки.
#
# SECOND OF THE THREE, and the order is the operator's (#2390): the free claim first
# (`claim_free_stamina`), this refill second, the bag LAST (`use_stamina_items`). The
# free claim and this refill renew every server day; the bag does not renew at all.
#
# **The price is not in the client, anywhere.** All 743 config tables were swept, every
# Lua function whose name mentions stamina was listed, and the board's own reply
# (`user.get.daily.stamina.info`) was caught from Lua as it arrived: the purse, the
# stamps and the free-claim count, and nothing about a cost. The window shows a price
# because whoever opens it is handed the number. See `docs/research/march-energy.md`.
#
# So this recipe cannot do what the operator originally asked — «buy only when the price
# is exactly 300» — and it does the nearest honest thing instead, which they chose:
#
#   1. it buys only while the game says NO refill has been bought today, which by the
#      ladder the operator described (300, then 500, then 1000) is the cheap one;
#   2. it prices the purchase AFTERWARDS, off the diamond purse before and after;
#   3. if that price came out above `cap`, the game has re-priced, and the recipe
#      REMEMBERS the refusal and never buys again until a person clears it.
#
# Clearing it is one line at the machine:
#
#     python -m panel.forget stamina_refill_block
#
# **IT ENDS, IT DOES NOT STOP.** Meant to be CALLed — the hunt and the radar both take
# the day's energy before they spend any — and `STOP` unwinds the CALLER too
# (docs/dsl.md). Every «nothing to do» here is an `IF` that simply runs out of lines.
ARGS cap = 300

RECALL stamina_refill_block INTO refill_block
IF refill_block > 0
    LOG "the energy refill is switched off — one cost {cap} diamonds or more once, so nothing is bought until a person clears it"

IF refill_block == 0
    READ_LUA (function() local p = nil pcall(function() p = LuaEntry.Player end) if p == nil then return -1 end local n = tonumber(rawget(p, 'playerStaminaGoldNum')) if n == nil then return -1 end local at = tonumber(rawget(p, 'playerStaminaGoldTime')) or 0 local zero = 0 pcall(function() zero = math.floor(tonumber(UITimeManager:GetInstance():GetTomorrowZero()) or 0) end) if zero <= 0 then return -1 end if at < (zero - 86400000) then return 0 end return math.floor(n) end)() INTO refills_today
    IF refills_today == -1
        LOG "the client cannot say how many energy refills were bought today — leaving it alone"
    IF refills_today > 0
        LOG "today's energy refill has already been bought — nothing to do"
    IF refills_today == 0
        READ_LUA (((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.gold) end) if v == nil then return -1 end return math.floor(v) end)() >= {cap}) and 1 or 0) INTO can_pay
        IF can_pay == 0
            LOG "fewer than {cap} diamonds in the purse — the refill is left alone"
        IF can_pay == 1
            TAP buy_stamina_refill
            WAIT 1.5
            READ_LUA (function() local b = DataCenter.__lw_stambuy or {} local gems0 = math.floor(tonumber(b.gems) or -1) local gems1 = math.floor(tonumber((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.gold) end) if v == nil then return -1 end return math.floor(v) end)()) or -1) local e0 = math.floor(tonumber(b.energy) or 0) local e1 = math.floor(tonumber((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)()) or 0) local paid = -1 if gems0 >= 0 and gems1 >= 0 then paid = gems0 - gems1 end return 'sent=' .. tostring(b.sent == true) .. ' gems_before=' .. tostring(gems0) .. ' gems_now=' .. tostring(gems1) .. ' paid=' .. tostring(paid) .. ' energy_before=' .. tostring(e0) .. ' energy_now=' .. tostring(e1) .. ' gained=' .. tostring(e1 - e0) end)() INTO refill_report
            LOG "bought the day's energy refill — {refill_report}"
            READ_LUA (function() local b = DataCenter.__lw_stambuy or {} local gems0 = math.floor(tonumber(b.gems) or -1) local gems1 = math.floor(tonumber((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.gold) end) if v == nil then return -1 end return math.floor(v) end)()) or -1) if gems0 < 0 or gems1 < 0 then return -1 end local paid = gems0 - gems1 if paid < 0 then return -1 end return paid end)() INTO refill_paid
            READ_LUA ((((function() local b = DataCenter.__lw_stambuy or {} local gems0 = math.floor(tonumber(b.gems) or -1) local gems1 = math.floor(tonumber((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.gold) end) if v == nil then return -1 end return math.floor(v) end)()) or -1) if gems0 < 0 or gems1 < 0 then return -1 end local paid = gems0 - gems1 if paid < 0 then return -1 end return paid end)()) > {cap}) and 1 or 0) INTO overpaid
            IF overpaid == 1
                LOG "that refill cost more than {cap} diamonds — the game has re-priced, so nothing more is bought until a person says so"
                REMEMBER stamina_refill_block FROM refill_paid
