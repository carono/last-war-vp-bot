# Raise the drone's level while the bag pays for it — the duel's Monday.
# ru: Повышать уровень дрона, пока хватает запаса, — понедельник дуэли.
#
# WHAT THE DRONE IS, in the client's own words (#2617). Nothing in the game's data is
# named after a drone: it is the «tactical weapon», one per account, id 1000, and it is
# the wire that gives it away — `push.uav.effects` and `push.uav.skillchip.changes`. So
# `DataCenter.TacticalWeaponManager` is the drone, and `weapon.up.lv` raises it.
#
# WHAT IT SPENDS, read off the client's own level row rather than written down here:
# each level costs a fixed amount of two things (on a live account at level 130 that was
# 42 000 of item 7037 and 400 of item 7038), and the row changes as the drone climbs. So
# the recipe never assumes a price — `xall` re-reads how many levels the bag can pay for
# between presses and stops at zero.
#
# WHAT IT DOES NOT DO: it opens nothing, buys nothing for diamonds and touches no chest.
# Filling the bag is `open_drone_chips.md`, and the two are separate on purpose — the
# person asked for them in that order, chips first.
#
# WHERE THE PRICE IS COUNTED, and it is not the bag. Both cost items are RESOURCES
# (`ResourceItemDataManager`) rather than stacks, so a live account reads 0 of them in
# the bag while the client's own gate says it can pay. Reading the wrong store is how
# a run reports «not enough» over a purse of seventy million (#2617, measured).
#
# A drone that is at its ceiling — the account's own cap or the building's — is a STATE
# and not a failure: it stops and says which of the two it was.

# HOW MANY LEVELS AT MOST. 0 = as many as the bag pays for.
ARGS levels = 0

# 1. Park the ceiling, because `TAP` carries no arguments of its own.
LUA DataCenter.__lw_drone_max = math.floor(tonumber('{levels}') or 0)

# 2. One reading for the whole gate: the level, the cap, what the client says about
#    paying, and what each cost item costs against what the bag holds.
READ_LUA (function() local function _lw_res_counts() local out = {} local R = DataCenter and DataCenter.ResourceItemDataManager if R ~= nil then pcall(function() for k, v in pairs(R.itemList or {}) do local id = 0 local n = 0 if type(v) == 'table' then id = math.floor(tonumber(v.itemId or v.id or k) or 0) n = math.floor(tonumber(v.count or v.num or v.value or v.number) or 0) end if id > 0 then out[id] = (out[id] or 0) + n end end end) end local D = DataCenter and DataCenter.ItemData if D ~= nil then pcall(function() for _, v in pairs(D.ItemInfos or {}) do local id = math.floor(tonumber(v.itemId) or 0) if id > 0 then out[id] = (out[id] or 0) + math.floor(tonumber(v.count) or 0) end end end) end return out end local info = nil local M = DataCenter and DataCenter.TacticalWeaponManager if M ~= nil then pcall(function() info = M:GetTacticalWeaponInfo(1000) end) if type(info) ~= 'table' then pcall(function() for _, v in pairs(M.tacticalWeaponInfos or {}) do info = v end end) end end if type(info) ~= 'table' then return 'lv=0 max=0 can=0 why=no-drone' end local row = info.levelTemplate if type(row) ~= 'table' then pcall(function() row = info:GetLevelTemplate() end) end local cost = {} if type(row) == 'table' and type(row.cost_resItem) == 'table' then for _, c in pairs(row.cost_resItem) do if type(c) == 'table' then cost[#cost + 1] = {id = math.floor(tonumber(c.id) or 0), n = math.floor(tonumber(c.value) or 0)} end end end local have = _lw_res_counts() local bits = {} for _, c in ipairs(cost) do bits[#bits + 1] = c.id .. ':' .. (have[c.id] or 0) .. '/' .. c.n end local function ask(name) local v = nil local ok = pcall(function() v = info[name](info) end) if not ok then return -1 end if v == true then return 1 end if v == false then return 0 end return math.floor(tonumber(v) or -1) end return 'lv=' .. tostring(math.floor(tonumber(info.level) or 0)) .. ' max=' .. tostring(math.floor(tonumber(info.maxLevel) or 0)) .. ' capped=' .. tostring(ask('IsReachLevelLimit')) .. ' topped=' .. tostring(ask('IsReachMaxLevel')) .. ' pays=' .. tostring(ask('HasResItemToUpgrade')) .. ' cost=' .. table.concat(bits, ',') end)() INTO drone_state
LOG "drone: {drone_state}"

# 3. Nothing to do is a state, not a failure — and it says WHICH kind of nothing.
READ_LUA (function() local info = nil local M = DataCenter and DataCenter.TacticalWeaponManager if M ~= nil then pcall(function() info = M:GetTacticalWeaponInfo(1000) end) if type(info) ~= 'table' then pcall(function() for _, v in pairs(M.tacticalWeaponInfos or {}) do info = v end end) end end if type(info) ~= 'table' then return 0 end local function ask(name) local v = nil local ok = pcall(function() v = info[name](info) end) return ok and v == true end if ask('IsReachMaxLevel') then return 1 end if ask('IsReachLevelLimit') then return 2 end return 0 end)() INTO drone_capped
IF drone_capped == 1
    STOP "the drone is at its maximum level — nothing to raise"
IF drone_capped == 2
    STOP "the drone is held at the base's own level cap — raise the building first"

READ_LUA (function() local function _lw_res_counts() local out = {} local R = DataCenter and DataCenter.ResourceItemDataManager if R ~= nil then pcall(function() for k, v in pairs(R.itemList or {}) do local id = 0 local n = 0 if type(v) == 'table' then id = math.floor(tonumber(v.itemId or v.id or k) or 0) n = math.floor(tonumber(v.count or v.num or v.value or v.number) or 0) end if id > 0 then out[id] = (out[id] or 0) + n end end end) end local D = DataCenter and DataCenter.ItemData if D ~= nil then pcall(function() for _, v in pairs(D.ItemInfos or {}) do local id = math.floor(tonumber(v.itemId) or 0) if id > 0 then out[id] = (out[id] or 0) + math.floor(tonumber(v.count) or 0) end end end) end return out end local info = nil local M = DataCenter and DataCenter.TacticalWeaponManager if M ~= nil then pcall(function() info = M:GetTacticalWeaponInfo(1000) end) if type(info) ~= 'table' then pcall(function() for _, v in pairs(M.tacticalWeaponInfos or {}) do info = v end end) end end if type(info) ~= 'table' then return 0 end local function ask(name) local v = nil local ok = pcall(function() v = info[name](info) end) return ok and v == true end if ask('IsReachMaxLevel') or ask('IsReachLevelLimit') then return 0 end local row = info.levelTemplate if type(row) ~= 'table' then pcall(function() row = info:GetLevelTemplate() end) end if type(row) ~= 'table' or type(row.cost_resItem) ~= 'table' then return 0 end local have = _lw_res_counts() local can = -1 for _, c in pairs(row.cost_resItem) do if type(c) == 'table' then local id, n = math.floor(tonumber(c.id) or 0), math.floor(tonumber(c.value) or 0) if n > 0 then local buys = math.floor((have[id] or 0) / n) if can < 0 or buys < can then can = buys end end end end if can < 0 then can = 0 end local cap = math.floor(tonumber(DataCenter.__lw_drone_max) or 0) if cap > 0 and can > cap then can = cap end return can end)() INTO drone_can
IF drone_can == 0
    STOP "not enough drone parts for a level — open the boxes first"
LOG "levels the bag pays for: {drone_can}"

# 4. Raise it. `xall` re-reads the count between presses, so it spends exactly what the
#    bag holds and a press the client dropped is pressed again.
# The level BEFORE, parked in the game rather than only read out: `IF` compares a
# variable with a literal and never two variables (docs/dsl.md), so «did it move»
# has to come back already answered.
LUA DataCenter.__lw_drone_before = (function() local info = nil local M = DataCenter and DataCenter.TacticalWeaponManager if M ~= nil then pcall(function() info = M:GetTacticalWeaponInfo(1000) end) if type(info) ~= 'table' then pcall(function() for _, v in pairs(M.tacticalWeaponInfos or {}) do info = v end end) end end if type(info) ~= 'table' then return 0 end return math.floor(tonumber(info.level) or 0) end)()
READ_LUA (function() local info = nil local M = DataCenter and DataCenter.TacticalWeaponManager if M ~= nil then pcall(function() info = M:GetTacticalWeaponInfo(1000) end) if type(info) ~= 'table' then pcall(function() for _, v in pairs(M.tacticalWeaponInfos or {}) do info = v end end) end end if type(info) ~= 'table' then return 0 end return math.floor(tonumber(info.level) or 0) end)() INTO drone_before
TAP drone_level_up xall
WAIT 1.5

READ_LUA (function() local info = nil local M = DataCenter and DataCenter.TacticalWeaponManager if M ~= nil then pcall(function() info = M:GetTacticalWeaponInfo(1000) end) if type(info) ~= 'table' then pcall(function() for _, v in pairs(M.tacticalWeaponInfos or {}) do info = v end end) end end if type(info) ~= 'table' then return 0 end return math.floor(tonumber(info.level) or 0) end)() INTO drone_after
READ_LUA (function() local now = (function() local info = nil local M = DataCenter and DataCenter.TacticalWeaponManager if M ~= nil then pcall(function() info = M:GetTacticalWeaponInfo(1000) end) if type(info) ~= 'table' then pcall(function() for _, v in pairs(M.tacticalWeaponInfos or {}) do info = v end end) end end if type(info) ~= 'table' then return 0 end return math.floor(tonumber(info.level) or 0) end)() local was = math.floor(tonumber(DataCenter.__lw_drone_before) or 0) if now > was then return 1 end return 0 end)() INTO drone_moved
LOG "drone level: {drone_before} -> {drone_after}"
IF drone_moved == 0
    FAIL "the drone did not move — {drone_state}"
