# «Гонка вооружений», фаза «Улучшение Дрона» — набирать очки стягами до конца фазы.
# ru: «Гонка вооружений», фаза дрона — стяги поднимаются до конца фазы, потолок 300 стамины.
#
# THIS SPENDS THE PLAYER'S STAMINA, and it has THREE ceilings. It stops at whichever it
# reaches first, and it says which one stopped it:
#
#   1. `stamina` — the most stamina THIS PHASE may spend. 300 by default, which is the
#      number the person named for it. **A ceiling of the PHASE, not of one run**
#      (#2574): a run ends the moment the squad leaves, so a per-run ceiling multiplied
#      by however many runs the phase had, which is not a ceiling at all. The purse is
#      parked in the client's VM against the phase's own `stage_end_time`, so a new
#      phase resets it and a restart in the middle of one does not.
#   2. the phase's TOP CHEST — points already scored are the server's own count, so a
#      chest reached by hand from the phone is a chest this run does not pay for again.
#   3. the squad. A squad that is out cannot raise a banner.
#
# It never spends anything else. No diamonds, no stamina refills, no second squad.
#
# ## RAISING A BANNER IS NOT JOINING ONE, AND THE DAY'S JOIN CAP IS NONE OF ITS BUSINESS
#
# The person's words, and they end a wrong ceiling this recipe used to carry: «Автостяги
# с дроном никак не связаны, на стяги, что мы создаем лимитов нет». The daily per-kind
# numbers in `panel/rally_limits.py` are a cap on JOINING somebody else's banner — the
# «rally_auto_join» trigger's own budget, counted per join. A banner this recipe RAISES
# is a march the account creates, the game charges it in stamina and caps it nowhere, so
# there is nothing for a join budget to say about it. It was wired to that book until
# #2574: on 2026-09-05 a drone phase halted with «no rally allowance» while the account
# had stamina, a free squad and an unscored chest — refused by a ceiling that was never
# about it. The ceilings above are the real ones.
#
# ## THE PHASE IS WORKED BY EVENTS, AND THE CLOCK IS ONLY THE SAFETY NET (#2661)
#
# The person's decision, in their words: «Какой нахуй повтор через 10 минут, у тебя есть
# пуши, отправили стяг, ждем пока закончим и вернемся на базу, и сразу снова отправляем
# тех, кто пришел на базу».
#
# So there is no retry clock here at all. A march of ours ending is announced on the wire
# — `push.world.march.del` — and the «arms_drone_relay» trigger answers that push by
# playing this recipe again. The squad that has just come home raises the next banner,
# within seconds of arriving, for as long as the hour lasts. `perform_arms_race` keeps
# its turn on the PHASE BORDER, and that is now a safety net rather than the mechanism: a
# profile whose ear is down still works the hour, only slowly.
#
# What that push costs when it is somebody else's march — and most of them are, because
# the world stream carries every march in view — is ONE Lua read of which phase is
# running, taken before anything else in this file. #2574 declined to pay even that and
# took the same event off the client's own march clock instead; seven measured phases
# later it had raised one or two banners each, because a clock that fires once is a clock
# that misses every return but the first.
#
# ## …AND IT IS WORKED PER SQUAD, so a squad in the air never stops the hour (#2661)
#
# The gate used to be asked about ONE squad, named in the order. A banner takes that squad
# away for minutes, so the very next fire found it busy and FAILED the whole run —
# measured live on 2026-09-09: «the squad screen would not take squad 4» while three other
# squads stood at the base. `ARGS squads` is the set the order may spend; the gate hands
# back the lowest FREE one and the loop raises a banner with it, and a busy squad is
# skipped rather than refused. «Остальные пусть идут своим ходом» — an order that cannot
# find a free squad says so and does nothing, which is a clean no-op and not a failure.
#
# ## The phase must be PAYING — and that is judged ACROSS the phase, not after two seconds
#
# The server hands over the score rules of the CURRENT phase only — what pays next is
# not knowable in advance and what paid yesterday is worthless. So this recipe carries no
# rule id at all: it judges by the score MOVING, which is a check the game itself answers
# and which survives the rules changing.
#
# WHEN it looks was the mistake (#2661). The check used to read the score two seconds
# after a banner left and stop on the spot if it had not moved — but the server credits a
# rally when the march RESOLVES, not when it is sent. Measured live on 2026-09-09: 6500
# two seconds after the banner went up, 8500 three minutes later. Every run of a phase
# that was paying perfectly well ended with «this phase did not pay for that». What is
# refused now is a phase that has had TWO banners out of it and still shows the score it
# had when the first one left — the same protection, at the timescale the answer arrives
# on.
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
#   squads   which squads this order may spend, as `1,2,3,4` — the numbers the player
#            sees. The banner goes out with the lowest one that is FREE; the rest are
#            skipped, not waited for.
#   drone    0 turns the whole order off, and it is checked before anything is read —
#            the relay fires on a push that is mostly other people's marches.
#   level    the level to search for, and `target` which «лупа» tab to look in.
#            `auto` — the default since #2646 — asks the game which tab holds a rally
#            target at that level this season, because a season renames the Fatal
#            Elite and moves the ceiling the search will take (35 once, 60 now). Both
#            travel straight through to actions/create_rally.md, the ability this one
#            spends.
#   phase_left  seconds to the phase border, as the caller read it. The next turn is
#            never booked past it. 0 = unknown, and then the return clock stands alone.
#
# The reading is actions/read_arms_race.md; the research is docs/research/arms-race.md.

ARGS stamina = 300
ARGS squads = 1,2,3,4
ARGS drone = 1
ARGS level = 35
ARGS target = auto
ARGS phase_left = 0

# THE CHEAPEST GATE FIRST, BECAUSE THIS RECIPE IS NOW ANSWERED BY A PUSH (#2661). The
# relay fires on `push.world.march.del` — «a march ended» — and that push is not only
# ours: the world stream carries every march in view. So the very first thing a fire
# costs is ONE Lua read, and a fire that is not the drone phase (or whose switch is off)
# stops on it, before the calendar get inside `read_arms_race` is ever sent.
IF drone == 0
    STOP "the drone order is switched off"

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end return math.floor((d.event_id or 0) + 0) end)() INTO arms_phase_now

IF arms_phase_now != 120004
    STOP "not the drone phase — nothing raised"

CALL read_arms_race

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end return math.floor((d.event_id or 0) + 0) end)() INTO arms_event

IF arms_event != 120004
    STOP "not the drone phase — nothing raised"

# What the game charges for raising one banner, asked every run. A build that answers 0
# means this phase is not paid for in stamina at all and the ceiling would be a ceiling
# over nothing — so the run says so and spends nothing.
READ_LUA (function() local v = nil pcall(function() v = MarchUtil.GetCostStaminaByTargetType(MarchTargetType.RALLY_FOR_BOSS) + 0 end) if v == nil then return 0 end return math.floor(v) end)() INTO rally_cost

IF rally_cost == 0
    STOP "the game prices a rally at no stamina at all — «300 стамины» would be a ceiling over an empty spend, so nothing is raised until somebody says what this phase really costs"

# THE PHASE'S OWN PURSE, and it outlives this run on purpose (#2574). Keyed on the
# phase's `stage_end_time`: a new phase makes a new one, a second run inside the same
# phase finds the stamina the first one spent, and a client restart makes a fresh one
# because the VM went with it. `sc_first` is the score standing when the phase's FIRST
# banner went out, and it is what «did this phase pay» is judged against (below).
LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local ends = 0 if d ~= nil then ends = math.floor((d.stage_end_time or 0) + 0) end local ph = DataCenter.__lw_arms_ph if type(ph) ~= 'table' or math.floor(tonumber(ph.ends) or 0) ~= ends then DataCenter.__lw_arms_ph = {ends = ends, spent = 0, made = 0, sc_first = -1} end end)()

# The run's own counters, parked beside the ceilings they are judged against, so the two
# are read in one place and cannot drift apart. What has been SPENT lives in the phase
# purse above, not here.
LUA DataCenter.__lw_arms_dr = {cap = tonumber("{stamina}") or 0, cost = 0, made = 0, sc0 = -1, squads = "{squads}"}

# THE PRICE TRAVELS BY `PARK`, AND NOT BY A PLACEHOLDER (#2649). `{name}` is substituted
# when the FILE IS PARSED, so a value the run has only just READ cannot go into a `LUA`
# chunk that way: what reached the game was the literal text of the name, and
# `tonumber("{rally_cost}")` is nil. The cost stayed 0, every gate answered «the game
# prices a rally at no stamina», and the drone phase raised NOTHING — measured live on
# 2026-09-08 with the game pricing a rally at 20. `PARK` is the primitive for exactly
# this (docs/dsl.md); the value arrives as a string and the gate reads it back with the
# `tonumber` it already used.
PARK rally_cost INTO DataCenter.__lw_arms_dr.cost

# MAY ANOTHER BANNER GO OUT, AND WITH WHICH SQUAD? One call answers both (#2661). It used
# to be asked about ONE squad named in the order, so a squad that had just left with a
# banner failed the whole run — measured live on 2026-09-09: «the squad screen would not
# take squad 4» while three other squads stood at the base doing nothing. The gate now
# reads the whole allowed set and hands back the lowest FREE one; a busy squad is skipped,
# never a refusal. `arms_squad` is the answer, and it is what `create_rally` is called
# with: the gate writes the plain variable `squad`, and `{squad}` in a sub-recipe is filled
# from the caller's variables at CALL time, so
# a squad chosen a line earlier is the squad that raises the banner.
#
# «Не заплатила ли фаза» is judged ACROSS the phase rather than two seconds after a send
# (#2661). The server credits a rally's points when the march RESOLVES, not when it
# leaves: on 2026-09-09 the score read 6500 two seconds after the banner went up and 8500
# three minutes later, so the old check called a paying phase unpaid every single time.
# What is refused now is a phase that has had TWO banners out of it and still shows the
# score it had when the first one left.
READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} local ph = DataCenter.__lw_arms_ph or {} local cost = math.floor(tonumber(p.cost) or 0) if cost <= 0 then return 0, 'the game prices a rally at no stamina', 0 end local spent = math.floor(tonumber(ph.spent) or 0) if spent + cost > math.floor(tonumber(p.cap) or 0) then return 0, 'the stamina ceiling of this phase is reached', 0 end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) if have < cost then return 0, 'not enough stamina in the purse', 0 end local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0, 'the game would not say which phase is running', 0 end if math.floor((d.event_id or 0) + 0) ~= 120004 then return 0, 'the drone phase is over', 0 end local sc = math.floor((d.sc or 0) + 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) if top > 0 and sc >= top then return 0, 'every chest of this phase is scored', 0 end local first = math.floor(tonumber(ph.sc_first) or -1) local made = math.floor(tonumber(ph.made) or 0) if made >= 2 and first >= 0 and sc <= first then return 0, 'this phase has paid nothing for the banners already raised', 0 end local afd = DataCenter.ArmyFormationDataManager local pick = 0 local allow = {} for w in string.gmatch(tostring(p.squads or ''), '%d+') do allow[w] = 1 end local seen = 0 pcall(function() for _, v in pairs(afd.ArmyFormationList) do local idx = math.floor((v.index or -1) + 0) if allow[tostring(idx)] == 1 then seen = seen + 1 local st = math.floor((v.state or -1) + 0) local ok, idle = pcall(function() return v:IsFree() end) local free = true if ok and idle ~= nil then free = (idle and true or false) end if st == 0 and free and (pick == 0 or idx < pick) then pick = idx end end end end) if seen == 0 then return 0, 'none of the squads this order may use is on the board', 0 end if pick == 0 then return 0, 'every squad this order may use is out', 0 end p.sc0 = sc DataCenter.__lw_arms_dr = p return 1, 'ok', pick end)() INTO arms_go, arms_why, squad

IF arms_go == 0
    LOG "arms drone: no banner this round — {arms_why}"

WHILE arms_go == 1 LIMIT 40
    CALL create_rally
    WAIT 2
    # What that banner cost, and the score it left behind. Nothing is judged here: the
    # points arrive when the march resolves, minutes later, and the gate above compares
    # across the phase instead.
    READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} local ph = DataCenter.__lw_arms_ph or {} ph.spent = math.floor(tonumber(ph.spent) or 0) + math.floor(tonumber(p.cost) or 0) ph.made = math.floor(tonumber(ph.made) or 0) + 1 p.made = math.floor(tonumber(p.made) or 0) + 1 if math.floor(tonumber(ph.sc_first) or -1) < 0 then ph.sc_first = math.floor(tonumber(p.sc0) or -1) end DataCenter.__lw_arms_ph = ph return math.floor(tonumber(ph.made) or 0) end)() INTO arms_phase_made

    READ_LUA (function() local p = DataCenter.__lw_arms_dr or {} local ph = DataCenter.__lw_arms_ph or {} local cost = math.floor(tonumber(p.cost) or 0) if cost <= 0 then return 0, 'the game prices a rally at no stamina', 0 end local spent = math.floor(tonumber(ph.spent) or 0) if spent + cost > math.floor(tonumber(p.cap) or 0) then return 0, 'the stamina ceiling of this phase is reached', 0 end local have = 0 pcall(function() have = math.floor((LuaEntry.Player.stamina or 0) + 0) end) if have < cost then return 0, 'not enough stamina in the purse', 0 end local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0, 'the game would not say which phase is running', 0 end if math.floor((d.event_id or 0) + 0) ~= 120004 then return 0, 'the drone phase is over', 0 end local sc = math.floor((d.sc or 0) + 0) local top = 0 pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) if top > 0 and sc >= top then return 0, 'every chest of this phase is scored', 0 end local first = math.floor(tonumber(ph.sc_first) or -1) local made = math.floor(tonumber(ph.made) or 0) if made >= 2 and first >= 0 and sc <= first then return 0, 'this phase has paid nothing for the banners already raised', 0 end local afd = DataCenter.ArmyFormationDataManager local pick = 0 local allow = {} for w in string.gmatch(tostring(p.squads or ''), '%d+') do allow[w] = 1 end local seen = 0 pcall(function() for _, v in pairs(afd.ArmyFormationList) do local idx = math.floor((v.index or -1) + 0) if allow[tostring(idx)] == 1 then seen = seen + 1 local st = math.floor((v.state or -1) + 0) local ok, idle = pcall(function() return v:IsFree() end) local free = true if ok and idle ~= nil then free = (idle and true or false) end if st == 0 and free and (pick == 0 or idx < pick) then pick = idx end end end end) if seen == 0 then return 0, 'none of the squads this order may use is on the board', 0 end if pick == 0 then return 0, 'every squad this order may use is out', 0 end p.sc0 = sc DataCenter.__lw_arms_dr = p return 1, 'ok', pick end)() INTO arms_go, arms_why, squad

# WHAT THE PHASE HAS DONE, AND NO CLOCK (#2661). The wake-up is the push — a march of
# ours ending is `push.world.march.del`, and the «arms_drone_relay» trigger answers it by
# playing this recipe again, which is «отряд вернулся — сразу отправляем его снова». The
# errand above keeps its turn on the phase border as the safety net, so a profile whose
# ear is down still works the hour, only slowly. Nothing here books anything.
READ_LUA (function() local ph = DataCenter.__lw_arms_ph or {} local p = DataCenter.__lw_arms_dr or {} local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) local sc = -1 local top = 0 if d ~= nil then sc = math.floor((d.sc or 0) + 0) pcall(function() for _, b in pairs(d.score_rewards or {}) do local t = math.floor((b.target or 0) + 0) if t > top then top = t end end end) end local made = math.floor(tonumber(ph.made) or 0) local spent = math.floor(tonumber(ph.spent) or 0) local cap = math.floor(tonumber(p.cap) or 0) return 'phase rallies=' .. made .. ' stamina=' .. spent .. '/' .. cap .. ' score=' .. sc .. '/' .. top, made end)() INTO arms_drone_report, arms_drone_made

LOG "arms drone: {arms_drone_report} — {arms_why}"

# THE CHESTS THE HOUR EARNS ARE TAKEN INSIDE THE HOUR (#2661). Measured live on
# 2026-09-09: the score passed the second chest's target (12000) at 09:31 and the row
# still read `receive == 0` at 09:50 — nineteen minutes of an earned chest sitting
# unclaimed — because the only thing that claims is `perform_arms_race`, and during the
# drone hour the banners are raised by the two wire triggers, which play THIS recipe and
# nothing else. A chest is not spent, it is owed, so leaving it for the phase border is
# a reward the account has and cannot see.
#
# The gate is one read rather than the claim recipe itself: a trigger fires on every
# march that ends in view, and `claim_arms_chests` opens with a `CALL read_arms_race`.
# Asking «is any row owed» costs one Lua read and is false on almost every fire.
READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end local sc = math.floor((d.sc or 0) + 0) local owed = 0 for _, b in pairs(d.score_rewards or {}) do if type(b) == 'table' then local got = math.floor((b.receive or 0) + 0) local target = math.floor((b.target or 0) + 0) if got == 0 and target > 0 and sc >= target then owed = owed + 1 end end end return owed end)() INTO arms_drone_owed

IF arms_drone_owed > 0
    LOG "the drone hour has earned {arms_drone_owed} chest(s) nobody has taken — claiming them now"
    CALL claim_arms_chests
