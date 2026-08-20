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
WHILE squad_free == 0 LIMIT 60
    WAIT 2
    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return -1 end local seen, can, n = false, nil, 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then seen = true can = (v.canMarch == true) n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) if not seen or can == nil then return -1 end if can then return 1 end if n <= 0 then return -2 end return 0 end)() INTO squad_free
IF squad_free == 0
    LOG "the squad has been busy for two minutes and still takes no orders — stopping rather than waiting on it"
    READ_LUA (0) INTO go
IF squad_free == -2
    LOG "the squad still holds no army after being asked for one — stopping rather than sending orders it cannot carry out"
    READ_LUA (0) INTO go
