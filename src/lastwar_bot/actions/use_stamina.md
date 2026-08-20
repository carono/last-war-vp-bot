# Spend the bag's stamina items on march energy — as much as asked for, and no more.
# ru: Потратить предметы выносливости из сумки на энергию для маршей — ровно сколько попросили.
#
# The energy a monster march is paid from is `stamina`, and the bag sells it back in two
# denominations the game names itself — a fifty and a ten. This spends them until the
# ASKED-FOR amount has been bought, biggest first, and stops short rather than overshoot:
# the caller named a number, and one item more than that is somebody's inventory spent
# without being asked.
#
# **The send is `item.use` with a table** — `{uuid = <the stack's own uuid>, num = n}`.
# That is the shape a live recording of the fireworks caught
# (docs/research/fireworks.md), and it is the only one of five tried that this client
# will serialise: the positional `(uuid, num)` every other message in this repository
# uses returns cleanly and does nothing at all, and `count` in place of `num` throws
# inside the game's own serialiser. Proven live on 2026-08-20: one ten-point item, purse
# 135 → 145.
#
# What it reports, in `stamina`:
#
#     want=1000 bought=1000 items=400401x20 before=145 now=1145
#
# `bought` is what the ITEMS were worth, and `now` is the purse the game answers with
# afterwards — they are two different readings on purpose, because the purse is what
# every gate downstream actually reads.
#
# ## Arguments
#
#   amount   how much stamina to buy. The default is a thousand, which is a hundred solo
#            attacks at the price the game charges today.

ARGS amount = 1000

READ_LUA (function() local D = DataCenter.ItemData local T = DataCenter.ItemTemplateManager local out = {} for _, pair in ipairs({{400401, 50}, {400402, 10}}) do local id, worth = pair[1], pair[2] local n = 0 pcall(function() for _, v in pairs(D.ItemInfos or {}) do if math.floor(tonumber(v.itemId) or 0) == id then n = n + math.floor(tonumber(v.count) or 0) end end end) local nm = '' pcall(function() nm = tostring(T:GetName(id) or '') end) out[#out + 1] = tostring(id) .. ':' .. tostring(n) .. 'x' .. tostring(worth) .. '=' .. tostring(n * worth) .. ' (' .. nm:gsub('%s+', ' ') .. ')' end return table.concat(out, ' | ') .. ' | stamina=' .. tostring((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)()) end)() INTO bag_before
LOG "stamina in the bag: {bag_before}"

LUA DataCenter.__lw_stam_want = {amount}

TAP use_stamina
WAIT 3

READ_LUA (function() local p = DataCenter.__lw_stam or {} return 'want=' .. tostring(math.floor(tonumber(p.want) or 0)) .. ' bought=' .. tostring(math.floor(tonumber(p.spent) or 0)) .. ' items=' .. tostring(p.used or '-') .. ' before=' .. tostring(math.floor(tonumber(p.before) or 0)) .. ' now=' .. tostring((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)()) end)() INTO stamina
LOG "stamina bought: {stamina}"

READ_LUA (function() local p = DataCenter.__lw_stam or {} return math.floor(tonumber(p.spent) or 0) end)() INTO bought

IF bought == 0
    FAIL "nothing was spent — the bag has no stamina items, or none small enough for what was asked"
