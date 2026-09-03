# Take the day's FREE march energy, once per server day.
# ru: Забрать бесплатную суточную энергию марша, один раз за игровые сутки.
#
# FIRST OF THE THREE, and the order is the operator's (#2390): free energy, then the
# cheap refill, and the bag LAST. The free claim and the refill renew every server day;
# what is in the bag does not renew at all, so spending the reserve while a free claim
# is standing there is the one order of the three that cannot be undone.
#
# The gate is the game's own stamp of the last claim measured against the SERVER's
# midnight, never the machine's clock and never a count somebody else resets.
READ_LUA (function() local p = nil pcall(function() p = LuaEntry.Player end) if p == nil then return -1 end local at = tonumber(rawget(p, 'lastClaimFreeStaminaTime')) or 0 local zero = 0 pcall(function() zero = math.floor(tonumber(UITimeManager:GetInstance():GetTomorrowZero()) or 0) end) if zero <= 0 then return -1 end local day = zero - 86400000 if at >= day then return 0 end return 1 end)() INTO free_ready
IF free_ready == -1
    LOG "the client cannot say whether today's free energy has been taken — leaving it alone"
    STOP
IF free_ready == 0
    LOG "today's free energy has already been taken — nothing to do"
    STOP
TAP claim_free_stamina
WAIT 1.5
READ_LUA (function() local f = DataCenter.__lw_freestam or {} local before = math.floor(tonumber(f.before) or 0) local now = math.floor(tonumber((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)()) or 0) return 'sent=' .. tostring(f.sent == true) .. ' before=' .. tostring(before) .. ' now=' .. tostring(now) .. ' gained=' .. tostring(now - before) end)() INTO free_report
LOG "took the day's free energy — {free_report}"
