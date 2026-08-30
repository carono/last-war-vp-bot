# «Гонка вооружений», фаза «Улучшение Дрона» — набрать очки стягами, на 300 стамины.
# ru: «Гонка вооружений», фаза дрона — очки набираются стягами, потолок 300 стамины.
#
# THIS SPENDS THE PLAYER'S STAMINA AND THE DAY'S RALLIES, and it has FOUR ceilings. It
# stops at whichever it reaches first, and it says which one stopped it:
#
#   1. `stamina` — the most stamina this run may spend. 300 by default, which is the
#      number the person named for this phase.
#   2. `rallies` — how many rallies the panel's own daily budget still allows. **A run
#      handed none raises nothing**: silence is a refusal here and never a licence, so
#      an arms-race phase can never quietly overspend the rally budget the person set
#      for the day (#2051/#2055). The panel passes the live remainder.
#   3. the phase's TOP CHEST — points already scored are the server's own count, so a
#      chest reached by hand from the phone is a chest this run does not pay for again.
#   4. the squad. A squad that is out cannot raise a banner; the run ends politely
#      instead of failing on the last press four steps later.
#
# It never spends anything else. No diamonds, no stamina refills, no second squad.
#
# ## The phase must be PAYING, and it is checked against the game, not against a memory
#
# The server hands over the score rules of the CURRENT phase only — what pays next is
# not knowable in advance and what paid yesterday is worthless. So this recipe does not
# carry a rule id at all. It reads the score before a rally and again after it, and if
# the number did not move it stops on the spot with «this phase did not pay for that».
# That is a check the game itself answers, and it survives the rules changing.
#
# The same goes for the price: `MarchUtil.GetCostStaminaByTargetType` is asked what a
# rally costs, every run. A build that prices one at nothing makes «300 стамины» a
# ceiling over an empty spend, so the run refuses rather than looping — a ceiling that
# cannot bite is not a ceiling.
#
# ## Arguments
#
#   stamina  the most stamina one run may spend. 300.
#   rallies  how many rallies the day's own budget still allows. 0 = none were given,
#            and then nothing is raised.
#   squad    which squad raises the banners — the 1..4 the player sees.
#   level    the level to search for, and `target` what kind: `boss` is a «Роковая
#            Элита», `monster` an ordinary field monster. Both travel straight through
#            to actions/create_rally.md, which is the ability this one spends.
#
# The reading is actions/read_arms_race.md; the research is docs/research/arms-race.md.

ARGS stamina = 300
ARGS rallies = 0
ARGS squad = 1
ARGS level = 35
ARGS target = boss

CALL read_arms_race

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end return math.floor((d.event_id or 0) + 0) end)() INTO arms_event

IF arms_event != 120004
    STOP "not the drone phase — nothing raised"

IF rallies == 0
    STOP "no rally allowance was handed over — the day's rally budget is spent, or nobody said what is left, and neither is a reason to raise one"

# What the game charges for raising one banner, asked every run. A build that answers 0
# means this phase is not paid for in stamina at all and the ceiling would be a ceiling
# over nothing — so the run says so and spends nothing.
READ_LUA (function() local v = nil pcall(function() v = MarchUtil.GetCostStaminaByTargetType(MarchTargetType.RALLY_FOR_BOSS) + 0 end) if v == nil then return 0 end return math.floor(v) end)() INTO rally_cost

IF rally_cost == 0
    STOP "the game prices a rally at no stamina at all — «300 стамины» would be a ceiling over an empty spend, so nothing is raised until somebody says what this phase really costs"

# The run's own counters, parked beside the ceilings they are judged against, so the two
# are read in one place and cannot drift apart. `sc0` is the score standing before the
# rally about to go out; `paid` is whether the last one moved it.
LUA DataCenter.__lw_arms_dr = {cap = tonumber("{stamina}") or 0, cost = 0, spent = 0, left = tonumber("{rallies}") or 0, made = 0, sc0 = -1, paid = 1}

LUA DataCenter.__lw_arms_dr.cost = math.floor(tonumber("{rally_cost}") or 0)

# May another banner go out? Everything the answer needs is read in ONE call: the four
# ceilings, and whether the last rally actually paid.
READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} if math.floor(tonumber(p.paid) or 1) == 0 then return 0 end local left = math.floor(tonumber(p.left) or 0) if left <= 0 then return 0 end local cost = math.floor(tonumber(p.cost) or 0) if cost <= 0 then return 0 end local spent = math.floor(tonumber(p.spent) or 0) if spent + cost > math.floor(tonumber(p.cap) or 0) then return 0 end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) if have < cost then return 0 end local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end local sc = math.floor((d.sc or 0) + 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) if top > 0 and sc >= top then return 0 end p.sc0 = sc local afd = DataCenter.ArmyFormationDataManager local f = nil pcall(function() for _, v in pairs(afd.ArmyFormationList) do if math.floor((v.index or -1) + 0) == {squad} then f = v end end end) if f == nil then return 0 end local st = math.floor((f.state or -1) + 0) local ok, idle = pcall(function() return f:IsFree() end) local free = true if ok and idle ~= nil then free = (idle and true or false) end if st ~= 0 or not free then return 0 end return 1 end)() INTO arms_go

IF arms_go == 0
    STOP "nothing to raise — the allowance, the stamina, the top chest or the squad says no"

WHILE arms_go == 1 LIMIT 40
    CALL create_rally
    WAIT 2
    # What that banner cost and whether it paid. The score is the SERVER's, so a rally
    # that moved nothing is a rally this phase does not reward — and the next read
    # refuses on `paid`.
    READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} p.spent = math.floor(tonumber(p.spent) or 0) + math.floor(tonumber(p.cost) or 0) p.made = math.floor(tonumber(p.made) or 0) + 1 p.left = math.floor(tonumber(p.left) or 0) - 1 local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = -1 if d ~= nil then sc = math.floor((d.sc or 0) + 0) end local before = math.floor(tonumber(p.sc0) or -1) if before >= 0 and sc >= 0 and sc <= before then p.paid = 0 else p.paid = 1 end return p.paid end)() INTO arms_paid

    IF arms_paid == 0
        LOG "the score did not move for that banner — this phase does not pay for a rally, so nothing more is spent on it"

    READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} if math.floor(tonumber(p.paid) or 1) == 0 then return 0 end local left = math.floor(tonumber(p.left) or 0) if left <= 0 then return 0 end local cost = math.floor(tonumber(p.cost) or 0) if cost <= 0 then return 0 end local spent = math.floor(tonumber(p.spent) or 0) if spent + cost > math.floor(tonumber(p.cap) or 0) then return 0 end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) if have < cost then return 0 end local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end local sc = math.floor((d.sc or 0) + 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) if top > 0 and sc >= top then return 0 end p.sc0 = sc local afd = DataCenter.ArmyFormationDataManager local f = nil pcall(function() for _, v in pairs(afd.ArmyFormationList) do if math.floor((v.index or -1) + 0) == {squad} then f = v end end end) if f == nil then return 0 end local st = math.floor((f.state or -1) + 0) local ok, idle = pcall(function() return f:IsFree() end) local free = true if ok and idle ~= nil then free = (idle and true or false) end if st ~= 0 or not free then return 0 end return 1 end)() INTO arms_go

READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = -1 if d ~= nil then sc = math.floor((d.sc or 0) + 0) end return 'rallies=' .. math.floor(tonumber(p.made) or 0) .. ' stamina=' .. math.floor(tonumber(p.spent) or 0) .. ' left=' .. math.floor(tonumber(p.left) or 0) .. ' score=' .. sc end)() INTO arms_drone_report

LOG "arms drone: {arms_drone_report}"
