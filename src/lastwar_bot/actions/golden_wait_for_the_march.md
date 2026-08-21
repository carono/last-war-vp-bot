# Wait for the chosen squad's own march to land — one brick of the golden-zombie chain.
# ru: Дождаться, пока марш выбранного отряда дойдёт — кирпич цепочки золотых зомби.
#
# Runnable on its own, deliberately (#1702): the chain is four bricks now, and each one is
# pressed and measured by itself instead of being debugged inside a loop where any one
# stumble hangs the whole hunt. It reads and waits; it sends nothing.
#
# The state it works on lives in the game VM (`DataCenter.__lw_gold`), parked there by
# `attack_golden_zombies.md`, so a brick needs no arguments to find its own run.

ARGS march_wait = 200

# NOTHING IS ORDERED INTO A LINK THE SERVER HAS ALREADY HUNG UP ON (#1702). The panel
# reads the link before a run is started (docs/research/server-link-status.md), and a
# hunt is minutes long: the client can go deaf in the middle of one, and from inside
# nothing changes — every getter answers, every send returns cleanly, and the client
# writes «Send msg when conn not ready» into its OWN log where nothing here was looking.
#
# What that costs is not a wasted order. Measured live on 2026-08-21, after a run that
# had gone on sending across a dropped link: the squad was left on a march the server
# never gave an arrival time to —
#
#     m0 uuid=1407629582470981526 endTime=0 startTime=1787285248626
#
# — which is what the operator saw as «отряд застрял в текстурах», a state ordinary play
# never produces. So the link is re-read at the top of every lap, and a hunt over a deaf
# client ends with the panel's own words instead of leaving marks in the game.
WAIT client == ready WITHIN 20s

# HOW LONG IS THIS MARCH, AND IS IT EVEN OURS? (#1702) The hunt's own hops are seconds
# and its longest ride is a minute; a clock three minutes out belongs to something else —
# a mine being gathered, a rally, a treasure run, an order the person gave by hand.
# Measured live: 109 minutes, and the chain sat in front of it doing nothing, which is
# the other half of «залипание на шахте».
#
# So the hunt does not wait it out. It recalls the squad — the same press that takes one
# off dirty ground — and the next lap starts from wherever the recall leaves it.
READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return -1 end local now = nil pcall(function() now = tonumber(UITimeManager.Instance:GetServerTime()) end) if now == nil then pcall(function() now = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if now == nil then now = os.time() * 1000 end return math.floor((due - now) / 1000) end)() INTO eta_left
IF eta_left > 180
    LOG "the squad is out on a march of its own for {eta_left} more seconds — that is not this hunt's; recalling it rather than waiting"
    TAP golden_unstick

# A squad that is still travelling cannot be sent again, and the send is refused in
# silence — which is how a whole run came to spend nothing and say nothing (#1519).
# So the wait is here, BEFORE the pick.
#
# It waits on the MARCH'S OWN CLOCK and not on the squad's state, because the state
# does not answer the question: a squad that has landed at a mine is gathering, and
# it goes on reading «out» for as long as it works there — measured, a 271-second
# ride still read «out» at 485 seconds. Nothing parked means nothing to wait for,
# which is the first lap.
READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived
# FAR, in three-second beats: a march across the map polled every second buys
# nothing and spends a checkpoint a second, and every checkpoint is a moment this
# run may be asked to step aside (#1702).
READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 0 end return ((due - ((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)())) > 4000) and 1 or 0 end)() INTO far
WHILE far == 1 LIMIT {march_wait}
    WAIT 3
    # …AND ASK THE CLIENT AGAIN WHILE WE WAIT (#1702). The march is minutes and
    # the beat is already being spent; a scan costs a fifth of a second and the
    # queue only grows. Live, a run threw away eighteen targets in a snapshot
    # taken once at the start — near a base everybody farms, a list goes stale
    # while the squad is still walking to the first of it.
    TAP golden_scan
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 0 end return ((due - ((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)())) > 4000) and 1 or 0 end)() INTO far

# …and the last few seconds closely, so a two-tile hop is not rounded up to three.
WHILE arrived == 0 LIMIT 15
    WAIT 1
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived

IF arrived == 0
    LOG "the squad is still on the road after the wait — stopping rather than sending orders nobody can carry out"
    READ_LUA (0) INTO go

# …AND THE MARCH ITSELF IS ASKED, NOT ONLY ITS CLOCK (#1702). The clock above is the
# server's `endTime` for the order this hunt sent, and it is right about when the march
# lands — but it is parked only when a send SUCCEEDS. After a send that was refused, the
# clock is the previous one's and already past, so the lap sailed straight through and
# sent another order at a squad that was still walking.
#
# `canMarch` does not save it. Measured live with `dev/golden_squad_state.md`, on a squad
# sent seconds earlier: `squad2 state=1 canMarch=true` with `marches=1 [left=71s]` — a
# march of ours in flight and the formation still saying yes. So the march's own uuid is
# what is watched: parked by the send, gone from our list when it lands.
#
# FIVE MINUTES, NOT THREE (#1702). The clock above is the server's estimate and it runs
# out early on a long haul — measured live, a march the client said had landed was still
# on the map 96 seconds later — so this wait, not that one, is what actually holds the
# lap. With the zombies near the base already killed the hunt walks 75-85 tiles at attack
# speed, which is minutes; a three-minute cap would end a run in the middle of a march it
# had correctly paid for.
READ_LUA (function() local p = DataCenter.__lw_gold or {} local want = p.march_uuid if want == nil then return 0 end local alive = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and u == tostring(want) then alive = 1 end end end end) return alive end)() INTO marching
WHILE marching == 1 LIMIT 150
    WAIT 2
    READ_LUA (function() local p = DataCenter.__lw_gold or {} local want = p.march_uuid if want == nil then return 0 end local alive = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and u == tostring(want) then alive = 1 end end end end) return alive end)() INTO marching
IF marching == 1
    LOG "the hunt's own march is still out after the wait — stopping rather than sending an order the squad cannot take"
    READ_LUA (0) INTO go

# …AND A LAP DOES NOT BEGIN UNTIL THE SQUAD IS FREE (#1702). One rule, in one place, for
# every reason a squad might not take an order — still walking, working a mine, standing
# on dirty ground, recalled a moment ago and on its way home. The march clock above
# answers «has our order landed»; this answers «will the game accept the next one», and
# only the second one is what the send actually needs.
#
# «CANNOT MARCH» IS TWO FACTS, and telling them apart is most of this block. Measured on
# a client that had just restarted: `squad3 state=0 canMarch=false soldiers=0` — a squad
# standing AT HOME, free, whose army the client had simply never fetched. Waiting for
# that to «finish» would wait for ever; one question puts the soldiers back.
#
# Bounded, and it says so when the bound is reached: a hunt that waits for ever is the
# thing being fixed, so two minutes of a squad that will not move ends the run with a
# reason instead of hanging in front of it.
READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
IF squad_free == -2
    LOG "the client is holding no army for the squad — asking for it rather than waiting"
    CALL fill_empty_squads
    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
WHILE squad_free == 0 LIMIT 300
    WAIT 2
    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
# A SECOND CHANCE AT THE ARMY, and it is not politeness (#1702). A squad that has just
# been recalled reads «no army» for a beat or two while the client catches up — measured,
# a hunt ended on exactly that, one lap after the fuse had correctly saved it from a mine.
# «No army» is the one refusal with a cure, so it is worth asking twice before a run is
# ended over it; «busy» is not, because waiting IS the cure and it has already been waited.
IF squad_free == -2
    LOG "still no army after the recall — asking once more before giving up"
    CALL fill_empty_squads
    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
    WHILE squad_free == 0 LIMIT 15
        WAIT 2
        READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
# TEN MINUTES, NOT TWO (#1702). Counted over one morning, «the squad has been busy for
# two minutes» ended four runs of the day — and a squad is busy because something else
# has it: a rally somebody joined it to, a gather it was sent on, an order the person
# gave by hand. Every one of those ends by itself in minutes, and the purse it was
# holding out on had thousands of energy in it. Waiting is the cheap answer; ten minutes
# is long enough for anything ordinary and short enough that a genuinely stuck squad
# still ends the run with a sentence.
IF squad_free == 0
    LOG "the squad has been busy for ten minutes and still takes no orders — stopping rather than waiting on it"
    READ_LUA (0) INTO go
IF squad_free == -2
    LOG "the squad still holds no army after being asked for it twice — stopping rather than sending orders it cannot carry out"
    READ_LUA (0) INTO go
