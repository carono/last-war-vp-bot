# Send the squad at the armed target — the only brick that gives an order.
# ru: Отправить отряд на выбранную цель — единственный кирпич, который отдаёт приказ.
#
# The ride (when it is on and has not been fused off), the march itself, and the proof
# that an order became a march. Everything that can refuse in silence is handled here and
# nowhere else, so there is one place to look when a hunt stops moving.
#
# Runnable on its own (#1702) — it will send the squad at whatever `golden_choose_a_target`
# last armed, which is exactly what a person debugging the send wants.

ARGS approach = 0
ARGS march_wait = 200
ARGS miss_limit = 6
ARGS breather = 90

# NOTHING TO SEND AT IS THE SAME KIND OF PAUSE AS A REFUSED SEND (#1702). The chooser
# comes back empty when every zombie it can reach has been killed — by us or by the
# neighbours — and the invasion puts more there within a couple of minutes. Ending the
# run on it is what left thousands of energy unspent all morning, so it is marked as a
# stall and answered by the same wait as a streak of refusals below.
IF picked == 0
    TAP golden_stall_mark

IF picked == 1
    # THE INVARIANT, AND EVERYTHING ELSE HERE RESTS ON IT (#1702): never give an order to
    # a squad the game says cannot take one. Both of the operator's worst complaints are
    # this rule being broken.
    #
    #  * «залипание на шахте» — the ride is a GATHER order and a squad that lands on a
    #    mine works it: measured live, `canMarch = false` with the march's own clock 109
    #    minutes out. Every attack sent into that window was refused in silence and cost
    #    ten seconds to prove, over and over, for as long as the run lasted.
    #  * «меняет маршрут, когда уже идёт на зомби» — an order that WAS accepted but whose
    #    march the client had not listed yet read as a refusal, so the chain wrote the
    #    target off and ordered the squad somewhere else, re-routing a squad mid-walk.
    #
    # One read, and it is the client's own answer about our own formation. A squad that
    # cannot march is RECALLED rather than shouted at — the recall is the same press that
    # takes a squad off dirty ground, because from here the two are the same thing.
    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
    IF squad_free == 0
        LOG "the squad cannot take an order where it stands — recalling it instead of sending orders nobody can carry out"
        TAP golden_unstick
        READ_LUA (0) INTO picked
    # …and «no army loaded» is NOT «busy» (#1702): a squad the client is holding no
    # soldiers for reads `canMarch = false` while standing at home doing nothing. One
    # question puts them back; only if that fails is the order withheld.
    IF squad_free == -2
        LOG "the client is holding no army for the squad — asking for it before giving any order"
        CALL fill_empty_squads
        READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
    IF squad_free == -2
        LOG "the squad still holds no army — no order is given"
        READ_LUA (0) INTO picked

IF picked == 1
    # THE RIDE. A gather order travels 2.5x faster than an attack one, so a long
    # haul is ridden to a mine beside the zombie and only the last few tiles are
    # paid at attack speed. Taken only when the arithmetic wins — a short hop
    # loses more to the extra stop than it saves.
    IF approach == 1
        # THE RIDE, AND ONLY THE RIDE, STILL FLIES THE CAMERA (#1702). The mine
        # hunt below asks `HasPointInfo` about the tiles around the target, and
        # the client can only answer for a district it holds — so this branch
        # fetches it. The chain itself does not: the pick works off the reaped
        # registry, and the flight used to be paid on every kill for a re-pick
        # that the reaping has made unnecessary.
        # THE SUMS FIRST, THE CAMERA ONLY IF THE SUMS ASK FOR IT (#1702). The planner
        # bails on «short» and «no-gain» without touching the map, so asking it first
        # costs a fifth of a second and answers most laps. It is only when it gets as far
        # as hunting for a mine and finds none — «no-mine», which on an unloaded corner of
        # the map means «nobody has shown me» — that the flight is worth its three
        # seconds. Measured: the flight ran on all twelve laps of one run, on hops of four
        # and six tiles the planner then called short.
        TAP golden_approach_arm
        READ_LUA (function() local p = DataCenter.__lw_gold or {} return (tostring(p.why or '') == 'no-mine') and 1 or 0 end)() INTO needs_district
        IF needs_district == 1
            TAP golden_look
            WAIT 1
            TAP golden_scan
            TAP golden_approach_arm
        READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.approach ~= nil) and 1 or 0 end)() INTO riding
        IF riding == 1
            READ_LUA (function() local p = DataCenter.__lw_gold or {} return 'why=' .. tostring(p.why or '-') .. ' direct=' .. tostring(math.floor(tonumber(p.direct_sec) or 0)) .. ' via=' .. tostring(math.floor(tonumber(p.approach_sec) or 0)) .. ' rode=' .. tostring(math.floor(tonumber(p.rode) or 0)) .. ' atk=' .. string.format('%.3f', tonumber(p.speed_atk) or 0) .. ' col=' .. string.format('%.3f', tonumber(p.speed_col) or 0) end)() INTO ride_report
            LOG "riding to a mine beside the target — {ride_report}"
            TAP golden_ride
            TAP golden_eta
            # The march's OWN clock, never the squad's state: a squad
            # that has landed at a mine is gathering, and it goes on
            # reading «out» for as long as it works there.
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived
            WHILE arrived == 0 LIMIT {march_wait}
                WAIT 3
                READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived
            # …AND THEN THE FUSE (#1702). A ride that lands on a mine and starts
            # GATHERING has parked the squad — measured live, 109 minutes of
            # `canMarch = false`, during which every attack is refused in silence.
            # One such ride per run is a mistake; two would be a policy. So the
            # first one switches the ride off for the rest of the run, recalls the
            # squad, and the hunt carries on at attack speed. The person's own
            # setting is untouched — this is a fuse inside one run.
            READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
            IF squad_free == 0
                LOG "the ride ended in a gather — the squad is working the mine and takes no orders; recalling it and hunting on foot for the rest of this run"
                TAP golden_no_ride
                TAP golden_unstick
                READ_LUA (0) INTO picked
    # The last march of the run is the one that brings the squad home; every one
    # before it deliberately leaves it standing where it killed.

IF picked == 1
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local left = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = math.floor(tonumber(p.cost) or 10) if cost <= 0 then cost = 10 end if left < cost * 2 then return 1 end local lim = math.floor(tonumber(p.limit) or 0) if lim > 0 and (tonumber(p.attacks) or 0) + 1 >= lim then return 1 end return ((function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() <= 1) and 1 or 0 end)() INTO last_one
    IF last_one == 1
        LUA DataCenter.__lw_gold_back = 1
        TAP golden_home
    ELSE
        TAP golden_send

    # THE PROOF THAT THE ATTACK IS UNDER WAY IS A MARCH OF OURS THAT WAS NOT
    # THERE A MOMENT AGO (#1702) — the operator's own model, and a fact about the
    # order rather than about what was paid for it. The purse decided this until
    # now, and it was wrong twice: the server does not always charge the price it
    # quotes (10 quoted, 8 taken, live), and the purse does not only go down — an
    # energy refill mid-chain made three marches that had all gone out look like
    # sends nobody received.
    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local seen = p.march_before or {} local fresh = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and not seen[u] then fresh = fresh + 1 end end end end) if fresh > 0 then return 1 end local busy = false pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then busy = (v.canMarch ~= true) end end end) return busy and 1 or 0 end)() INTO launched
    # 0.4 SECONDS, TWENTY-FIVE TIMES — the same ten seconds of patience, watched two and
    # a half times as closely (#1702). This poll is on the hot path: it is the last thing
    # between an order and the chain moving on, and every beat of it is dead time on a
    # send that was accepted at once. Nothing here is a timeout being shortened.
    # SIX SECONDS, NOT TEN (#1702). The proof is instant when the order was taken — the
    # squad goes busy the moment the game accepts it — so the whole of this poll is time
    # spent on orders that were REFUSED. Live, half the sends of a run were refusals at
    # zombies somebody else had already killed, and each cost the full ten seconds. Six is
    # still far longer than the server takes to answer; what it is not is a patience that
    # only ever pays out on failure.
    WHILE launched == 0 LIMIT 15
        WAIT 0.4
        READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local seen = p.march_before or {} local fresh = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and not seen[u] then fresh = fresh + 1 end end end end) if fresh > 0 then return 1 end local busy = false pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then busy = (v.canMarch ~= true) end end end) return busy and 1 or 0 end)() INTO launched

    IF launched == 0
        # A ZOMBIE SOMEBODY ELSE KILLED FIRST, nearly always: the client's list is a
        # snapshot, and the server refuses an order at a monster that is not there. That
        # is worth another target, not the end of the run — but a client that has gone
        # deaf refuses everything, so a handful in a row stop it.
        #
        # THERE IS NO «IS THE SQUAD STUCK» BRANCH HERE ANY MORE (#1702), and its absence
        # is the fix rather than a simplification. It used to run AFTER a send had spent
        # ten seconds failing, and it read `canMarch == false` as «dirty ground». Two
        # things are wrong with that. A squad that cannot march is now caught BEFORE the
        # send by the gate at the top of this brick, so ten seconds are never spent on a
        # doomed order; and `canMarch == false` after a send is what an ACCEPTED order
        # looks like, which is why the launch proof reads it as success. Asking the same
        # question in two places with two opposite meanings is how a chain ends up
        # re-routing a squad that was already walking.
        LOG "the send never became a march — that zombie is gone, or this squad has forgotten its army; trying the next one"
        TAP golden_miss
        # A SQUAD THE CLIENT HAS FORGOTTEN THE ARMY OF reads zero soldiers, and the
        # server refuses a march for an empty formation — silently, exactly like a dead
        # target (#1285, #1702). One question puts them back, and it costs a third of a
        # second.
        CALL fill_empty_squads
        READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.misses) or 0) end)() INTO misses
        IF misses > {miss_limit}
            # …and the chain decides what that means (#1702). It used to end the run
            # here, which over one morning is what ended nearly every one of them with
            # thousands of energy unspent. A streak of refusals is the ground being
            # farmed out; the caller waits and looks again, and only gives up when it
            # has run out of patience it was given.
            # A STREAK OF REFUSALS IS A PAUSE, NOT AN ENDING (#1702). Measured over one
            # morning, this line ended nearly every run of the day — the best of them
            # after 19 kills — with seven and a half THOUSAND energy still in the purse.
            # What it means is that the corner the squad is standing in has been farmed
            # out, which is a fact about the map two minutes from now rather than about
            # the client. So the hunt waits, asks the client about the district it is
            # standing in, and goes round again; the tiles it has already cleared stay
            # used, so a pause never walks it back round its own kills.
            #
            # It is BOUNDED, and that bound is what keeps the old ending honest: a
            # client that has genuinely gone deaf refuses everything for ever, and a
            # hunt that waits for ever in front of one is the bug this task began with.
            LOG "several sends in a row went nowhere — the ground here is farmed out"
            TAP golden_stall_mark
    ELSE
        # The tally moves HERE and nowhere else. What the attack COST is read off
        # the purse for the books, and cannot decide anything.
        TAP golden_confirm
        # …and when this march is due to land, so the next lap knows what to
        # wait for.
        TAP golden_eta
        # No scan here: the lap below re-asks the client after it has looked at the
        # origin of the next pick, and asking twice cost most of a second per kill
        # for a list that is thrown away and rebuilt anyway (#1702).

# THE PAUSE, IN ONE PLACE, FOR BOTH WAYS A LAP CAN COME UP EMPTY (#1702) — no zombie the
# chooser could reach, or a streak of orders the server refused. Measured over one
# morning, those two lines ended nearly every run of the day, the best of them after 19
# kills, with seven and a half THOUSAND energy still in the purse. Both mean the corner
# the squad is standing in has been farmed out, which is a fact about the map two minutes
# from now rather than about the client — so the hunt waits, asks the client about the
# district it is standing in, and goes round again.
#
# The tiles already cleared stay used, so a pause never walks the hunt back round its own
# kills. And it is BOUNDED: a client that has genuinely gone deaf refuses everything for
# ever, and a hunt that waits for ever in front of one is the bug this task began with.
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.stalled == 1) and 1 or 0 end)() INTO stalled
IF stalled == 1
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local lim = math.floor(tonumber(p.breather_limit) or 0) if lim <= 0 then return 0 end local used = math.floor(tonumber(p.breathers) or 0) local left = lim - used if left < 0 then left = 0 end return left end)() INTO breathers_left
    IF breathers_left == 0
        LOG "nothing to attack here and no pauses left — stopping"
        READ_LUA (0) INTO go
    IF breathers_left > 0
        LOG "nothing to attack here just now — waiting {breather}s and looking again ({breathers_left} pause(s) left)"
        TAP golden_breathe
        WAIT {breather}
        TAP golden_scan
