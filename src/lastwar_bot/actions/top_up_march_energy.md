# Top up march energy in the order the person settled: free, the cheap refill, then the bag.
# ru: Пополнить энергию марша по согласованному порядку: бесплатное, покупка за 300 алмазов, затем сумка.
#
# THE ORDER IS THE PERSON'S, and it was settled once (#2390) and restated for the drone
# hour (#2664): «Правила на энергию мы писали, берем бесплатное если есть, покупаем за 300
# алмазов, остальное берем из сумки». This file is that order in one place, so an ability
# that runs out of energy mid-phase calls ONE recipe instead of growing its own ladder:
#
#   1. `claim_free_stamina` — free, once per server day, renews;
#   2. `buy_stamina_refill` — 300 diamonds, once per server day, renews, and it prices the
#      purchase off the diamond purse afterwards and blocks itself for good if the game has
#      re-priced above `cap` (clear it with `python -m panel.forget stamina_refill_block`);
#   3. the bag, LAST, because what is in it does not renew at all.
#
# Each rung is walked only while the purse is still short of `need`: on a day whose free
# claim is taken and whose refill is bought the first two rungs are one reading each and
# send nothing.
#
# **IT ENDS, IT DOES NOT STOP, AND IT NEVER FAILS.** Meant to be CALLed from the middle of
# a phase — `STOP` and `FAIL` both unwind the CALLER (docs/dsl.md), and an empty bag is not
# a reason to end somebody's drone hour. Every «nothing to do» here is an `IF` that runs
# out of lines, and the bag is asked with `strict = 0` so that a stack the server refuses
# is a log line rather than a failed run.
#
# ## Arguments
#
#   need    how much energy the caller needs standing in the purse. 0 reads as «one of
#           anything», which is what a caller with no price to name wants.
#   cap     the most diamonds one refill may cost. 300 — the person's number, and it
#           travels into `buy_stamina_refill` under the name that recipe already uses.
#   bag     0 leaves the bag alone and stops the ladder after the refill. The bag is the
#           only rung that spends something the day will not give back.
#   strict  handed straight to `use_stamina`: 0 (the default here) makes «nothing was
#           spent» a log line instead of a failure.
#
# The research is docs/research/march-energy.md.

ARGS need = 0
ARGS cap = 300
ARGS bag = 1
ARGS strict = 0

READ_LUA (function() local need = math.floor(tonumber("{need}") or 0) if need <= 0 then need = 1 end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) return 'need=' .. tostring(need) .. ' have=' .. tostring(have) end)() INTO energy_state
LOG "topping up march energy — {energy_state}"

# FIRST RUNG: the day's free claim. It costs nothing and says «already taken» on every
# later run of the day, so it is asked before anything is bought.
CALL claim_free_stamina

READ_LUA (function() local need = math.floor(tonumber("{need}") or 0) if need <= 0 then need = 1 end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) if have >= need then return 1 end return 0 end)() INTO energy_enough

# SECOND RUNG: the refill for diamonds. Irreversible, so it is only reached while the
# purse is still short, and `cap` is the ceiling it refuses to pass.
IF energy_enough == 0
    CALL buy_stamina_refill
    READ_LUA (function() local need = math.floor(tonumber("{need}") or 0) if need <= 0 then need = 1 end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) if have >= need then return 1 end return 0 end)() INTO energy_enough

# THIRD RUNG: the bag, and only what is missing. The amount asked for is worked out from
# what the bag actually holds, because `use_stamina` spends the big denominations first and
# STOPS SHORT rather than overshoot — asking for 20 with nothing but fifties in the bag
# spends nothing at all. So the amount is rounded up to something the bag can pay exactly,
# capped at everything it holds, and 0 means «the bag cannot help», which is a log line.
IF energy_enough == 0
    IF bag == 0
        LOG "still short of march energy, and the bag is switched off for this order — nothing more is spent"
    IF bag == 1
        READ_LUA (function() local need = math.floor(tonumber("{need}") or 0) if need <= 0 then need = 1 end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) local want = need - have if want <= 0 then return 0 end local D = DataCenter.ItemData local n50, n10 = 0, 0 pcall(function() for _, v in pairs(D.ItemInfos or {}) do local id = math.floor(tonumber(v.itemId) or 0) local c = math.floor(tonumber(v.count) or 0) if id == 400401 then n50 = n50 + c elseif id == 400402 then n10 = n10 + c end end end) local worth = n50 * 50 + n10 * 10 if worth <= 0 then return 0 end local function sim(w) local s = 0 local room = math.floor((w - s) / 50) local n = math.min(room, n50) s = s + n * 50 room = math.floor((w - s) / 10) n = math.min(room, n10) s = s + n * 10 return s end local cands = {math.ceil(want / 10) * 10, math.ceil(want / 50) * 50, worth} for _, c in ipairs(cands) do if c > 0 and c <= worth and sim(c) >= want then return c end end if sim(worth) > 0 then return worth end return 0 end)() INTO amount
        IF amount == 0
            LOG "still short of march energy and the bag has no items it can pay with — nothing more is spent"
        IF amount > 0
            # No number in this line on purpose: `{name}` is substituted when the file is
            # PARSED, so a second call inside one run would print the first call's amount.
            # `use_stamina` logs what it actually spent, at the moment it spends it.
            LOG "the bag is the last of the three — spending what it can of the missing energy"
            CALL use_stamina
