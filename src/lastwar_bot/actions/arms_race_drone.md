# «Гонка вооружений», фаза «Улучшение Дрона» — набирать очки стягами до конца фазы.
# ru: «Гонка вооружений», фаза дрона — стяги поднимаются до конца фазы, потолок 300 стамины.
#
# THIS SPENDS THE PLAYER'S STAMINA AND THE DAY'S RALLIES, and it has FOUR ceilings. It
# stops at whichever it reaches first, and it says which one stopped it:
#
#   1. `stamina` — the most stamina THIS PHASE may spend. 300 by default, which is the
#      number the person named for it. **A ceiling of the PHASE, not of one run**
#      (#2574): a run ends the moment the squad leaves, so a per-run ceiling multiplied
#      by however many runs the phase had, which is not a ceiling at all. The purse is
#      parked in the client's VM against the phase's own `stage_end_time`, so a new
#      phase resets it and a restart in the middle of one does not.
#   2. `rallies` — how many rallies the panel's own daily budget still allows. **A run
#      handed none raises nothing**: silence is a refusal here and never a licence, so
#      an arms-race phase can never quietly overspend the rally budget the person set
#      for the day (#2051/#2055). The panel passes the live remainder.
#   3. the phase's TOP CHEST — points already scored are the server's own count, so a
#      chest reached by hand from the phone is a chest this run does not pay for again.
#   4. the squad. A squad that is out cannot raise a banner.
#
# It never spends anything else. No diamonds, no stamina refills, no second squad.
#
# ## The phase is worked to its END, and the wake-up is the squad's own clock (#2574)
#
# What this recipe used to do was raise ONE banner and go to sleep until the phase was
# over — because the squad is busy the instant the first banner goes out, and the errand
# above it books its next turn on the PHASE BORDER. Measured on the live account: seven
# drone phases, seven single runs, and four of the seven raised nothing at all. «1 или 2
# стяга за 4 часа события» is exactly that, and the person is right that it is wrong.
#
# So the run no longer STOPS when the squad is out. It says why it cannot raise another
# one, and it leaves in `next_run_in` the seconds until the NEAREST MARCH THIS ACCOUNT
# HAS OUT comes home — the game's own `endTime`, plus half a minute of slack. That is
# the «отряд вернулся» event the person asked for, read off the clock the server already
# handed over rather than watched for with a poll (`CLAUDE.md`, «Read once, then
# LISTEN»). The turn is capped at the phase border: a return that lands after the phase
# is over books nothing, and the border the caller read stands.
#
# When there is nothing left to gain — every chest scored, the allowance spent, the
# stamina ceiling reached, the phase gone — `next_run_in` is 0 and the caller's border
# stands, which is the old behaviour and the right one.
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
# ## Every refusal says WHICH gate said no (#2574)
#
# The gate used to answer one boolean, so the log line was «the allowance, the stamina,
# the top chest or the squad says no» — four possibilities and no way to tell them apart
# without a hand reading of the client. It answers a word now, and the word is what the
# run reports.
#
# ## Arguments
#
#   stamina  the most stamina this PHASE may spend. 300.
#   rallies  how many rallies the day's own budget still allows. 0 = none were given,
#            and then nothing is raised.
#   squad    which squad raises the banners — the 1..4 the player sees.
#   level    the level to search for, and `target` what kind: `boss` is a «Роковая
#            Элита», `monster` an ordinary field monster. Both travel straight through
#            to actions/create_rally.md, which is the ability this one spends.
#   phase_left  seconds to the phase border, as the caller read it. The next turn is
#            never booked past it. 0 = unknown, and then the return clock stands alone.
#
# The reading is actions/read_arms_race.md; the research is docs/research/arms-race.md.

ARGS stamina = 300
ARGS rallies = 0
ARGS squad = 1
ARGS level = 35
ARGS target = boss
ARGS phase_left = 0

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

# THE PHASE'S OWN PURSE, and it outlives this run on purpose (#2574). Keyed on the
# phase's `stage_end_time`: a new phase makes a new one, a second run inside the same
# phase finds the stamina the first one spent, and a client restart makes a fresh one
# because the VM went with it.
LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local ends = 0 if d ~= nil then ends = math.floor((d.stage_end_time or 0) + 0) end local ph = DataCenter.__lw_arms_ph if type(ph) ~= 'table' or math.floor(tonumber(ph.ends) or 0) ~= ends then DataCenter.__lw_arms_ph = {ends = ends, spent = 0, made = 0} end end)()

# The run's own counters, parked beside the ceilings they are judged against, so the two
# are read in one place and cannot drift apart. `sc0` is the score standing before the
# rally about to go out; `paid` is whether the last one moved it. What has been SPENT
# lives in the phase purse above, not here.
LUA DataCenter.__lw_arms_dr = {cap = tonumber("{stamina}") or 0, cost = 0, left = tonumber("{rallies}") or 0, made = 0, sc0 = -1, paid = 1}

LUA DataCenter.__lw_arms_dr.cost = math.floor(tonumber("{rally_cost}") or 0)

# May another banner go out? Everything the answer needs is read in ONE call: the four
# ceilings, whether the last rally actually paid, and — since #2574 — the WORD for
# whichever of them said no.
READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} local ph = DataCenter.__lw_arms_ph or {} if math.floor(tonumber(p.paid) or 1) == 0 then return 0, 'this phase did not pay for the last banner' end local left = math.floor(tonumber(p.left) or 0) if left <= 0 then return 0, 'the day rally allowance is spent' end local cost = math.floor(tonumber(p.cost) or 0) if cost <= 0 then return 0, 'the game prices a rally at no stamina' end local spent = math.floor(tonumber(ph.spent) or 0) if spent + cost > math.floor(tonumber(p.cap) or 0) then return 0, 'the stamina ceiling of this phase is reached' end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) if have < cost then return 0, 'not enough stamina in the purse' end local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0, 'the game would not say which phase is running' end if math.floor((d.event_id or 0) + 0) ~= 120004 then return 0, 'the drone phase is over' end local sc = math.floor((d.sc or 0) + 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) if top > 0 and sc >= top then return 0, 'every chest of this phase is scored' end p.sc0 = sc local afd = DataCenter.ArmyFormationDataManager local f = nil pcall(function() for _, v in pairs(afd.ArmyFormationList) do if math.floor((v.index or -1) + 0) == {squad} then f = v end end end) if f == nil then return 0, 'that squad is not there' end local st = math.floor((f.state or -1) + 0) local ok, idle = pcall(function() return f:IsFree() end) local free = true if ok and idle ~= nil then free = (idle and true or false) end if st ~= 0 or not free then return 0, 'the squad is out' end return 1, 'ok' end)() INTO arms_go, arms_why

IF arms_go == 0
    LOG "arms drone: no banner this round — {arms_why}"

WHILE arms_go == 1 LIMIT 40
    CALL create_rally
    WAIT 2
    # What that banner cost and whether it paid. The score is the SERVER's, so a rally
    # that moved nothing is a rally this phase does not reward — and the next read
    # refuses on `paid`.
    READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} local ph = DataCenter.__lw_arms_ph or {} ph.spent = math.floor(tonumber(ph.spent) or 0) + math.floor(tonumber(p.cost) or 0) ph.made = math.floor(tonumber(ph.made) or 0) + 1 p.made = math.floor(tonumber(p.made) or 0) + 1 p.left = math.floor(tonumber(p.left) or 0) - 1 local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = -1 if d ~= nil then sc = math.floor((d.sc or 0) + 0) end local before = math.floor(tonumber(p.sc0) or -1) if before >= 0 and sc >= 0 and sc <= before then p.paid = 0 else p.paid = 1 end return p.paid end)() INTO arms_paid

    IF arms_paid == 0
        LOG "the score did not move for that banner — this phase does not pay for a rally, so nothing more is spent on it"

    READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} local ph = DataCenter.__lw_arms_ph or {} if math.floor(tonumber(p.paid) or 1) == 0 then return 0, 'this phase did not pay for the last banner' end local left = math.floor(tonumber(p.left) or 0) if left <= 0 then return 0, 'the day rally allowance is spent' end local cost = math.floor(tonumber(p.cost) or 0) if cost <= 0 then return 0, 'the game prices a rally at no stamina' end local spent = math.floor(tonumber(ph.spent) or 0) if spent + cost > math.floor(tonumber(p.cap) or 0) then return 0, 'the stamina ceiling of this phase is reached' end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) if have < cost then return 0, 'not enough stamina in the purse' end local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0, 'the game would not say which phase is running' end if math.floor((d.event_id or 0) + 0) ~= 120004 then return 0, 'the drone phase is over' end local sc = math.floor((d.sc or 0) + 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) if top > 0 and sc >= top then return 0, 'every chest of this phase is scored' end p.sc0 = sc local afd = DataCenter.ArmyFormationDataManager local f = nil pcall(function() for _, v in pairs(afd.ArmyFormationList) do if math.floor((v.index or -1) + 0) == {squad} then f = v end end end) if f == nil then return 0, 'that squad is not there' end local st = math.floor((f.state or -1) + 0) local ok, idle = pcall(function() return f:IsFree() end) local free = true if ok and idle ~= nil then free = (idle and true or false) end if st ~= 0 or not free then return 0, 'the squad is out' end return 1, 'ok' end)() INTO arms_go, arms_why

# WHEN TO COME BACK, and what the phase has done so far. Both in one call, because both
# are answers to the same reading (`next_run_in`, docs/dsl.md).
READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} local ph = DataCenter.__lw_arms_ph or {} local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = -1 local top = 0 local ev = 0 if d ~= nil then sc = math.floor((d.sc or 0) + 0) ev = math.floor((d.event_id or 0) + 0) pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) end local made = math.floor(tonumber(ph.made) or 0) local spent = math.floor(tonumber(ph.spent) or 0) local left = math.floor(tonumber(p.left) or 0) local cost = math.floor(tonumber(p.cost) or 0) local cap = math.floor(tonumber(p.cap) or 0) local border = math.floor(tonumber("{phase_left}") or 0) local done = (ev ~= 120004) or (top > 0 and sc >= top) or (left <= 0) or (cost <= 0) or (spent + cost > cap) local nxt = 0 if not done then local now = 0 pcall(function() now = math.floor(tonumber(UITimeManager:GetInstance():GetServerTime()) or 0) end) local best = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local x = nil pcall(function() x = ms[i] end) if x ~= nil then local e = 0 pcall(function() e = math.floor(tonumber(x.endTime) or 0) end) if e > 0 then if e < 100000000000 then e = e * 1000 end local dt = math.floor((e - now) / 1000) if dt > 0 and (best == 0 or dt < best) then best = dt end end end end end) if best > 0 then nxt = best + 30 else nxt = 300 end if nxt < 60 then nxt = 60 end if border > 0 and nxt >= border then nxt = 0 end end return nxt, 'phase rallies=' .. made .. ' stamina=' .. spent .. '/' .. cap .. ' allowance_left=' .. left .. ' score=' .. sc .. '/' .. top, made end)() INTO next_run_in, arms_drone_report, arms_drone_made

LOG "arms drone: {arms_drone_report} — {arms_why}"
