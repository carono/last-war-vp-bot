# Attack the golden zombies one after another, from wherever the squad is, until the energy runs out.
# ru: Бить золотых зомби одного за другим — от места, где стоит отряд, — пока не кончится энергия.
#
# The «golden zombie» is the invasion event's own small monster, and it is told apart by
# ONE number and never by its picture: config id **1030000** in the client's
# `lw_world_monster` table — level 10, `type = 7` (the zombie line), `special = 9`
# (MonsterInvasion), recommended power 670 000, and `worldmap_icon` ending in `huang`,
# the yellow one. So a re-skin of the model changes nothing here and a monster that
# merely LOOKS golden is not attacked.
#
# ## What makes this a chain and not a fan
#
# The next target is the nearest one to **where the squad is**, not to the base. Every
# march but the last goes out with «come home afterwards» switched OFF, so the squad
# stands on the tile it has just cleared and the following pick is measured from there.
# The naive version — nearest to home, every time — walks the same ground over and over
# for the same twelve kills. Only the LAST march brings the squad back, because a squad
# left standing on the world map when a run ends is a squad somebody else can hit.
#
# **The FIRST zombie is the one nearest the BASE, and getting that right took two
# corrections.** The base is where the squad stands before the first march, so it is the
# origin the first pick is measured from — never the tile under the camera, which is the
# base only if the world scene was just entered.
#
#   * the base's own tile is worked out from the game's distance oracle: three readings of
#     `SceneUtils.TileDistanceToMyHome` around the camera and one small sweep to place it
#     exactly. Every pick then compares tile against tile — the first one against the
#     base, the rest against the last kill — instead of comparing two different kinds of
#     number;
#   * and the camera is put back on that origin before every scan. The client's monster
#     list only holds what it has LOADED, and a lap of `scan_map` ends at the far side of
#     the warzone with the tiles around the base long since evicted. «The nearest zombie»
#     was then the nearest of the far ones — five minutes of marching with a dozen sitting
#     beside the house.
#
# ## It does not hold the panel up
#
# `DETACH`, on the line below the arguments: a chain of marches lasts as long as the
# marches do, and nothing else in the panel may queue behind it. The run gets a worker of
# its own, at a priority below an ordinary errand, and steps aside at the first statement
# boundary anybody else wants the client — so the timers, the rally joins and a person's
# button all go on exactly as they would with this run absent (docs/dsl.md, `DETACH`).
#
# ## The energy is the clock, and it is the GAME'S energy
#
# One solo attack costs what the game says it costs
# (`MarchUtil.GetCostStaminaByTargetType(ATTACK_MONSTER)` — 10 on 2026-08-19) and the
# purse is `LuaEntry.Player.stamina` — 120 on a full account, so twelve attacks. Both are
# re-asked every lap and NEITHER is ever decremented by us: the same purse is spent by a
# person playing on the screen at that moment, and a number we kept would be confidently
# wrong within a minute of them touching anything.
#
# It is also the PROOF. A send returns cleanly whether or not the server honoured it
# (docs/research/world-monsters.md, Findings 13 and 16), so an attack is counted only
# when the purse has moved by the price of one — live, 55 to 45 on the first run of this
# recipe, and unmoved on the second, where the chosen squad turned out to be already out
# on the map and every send was refused in silence.
#
# ## The ride, and why it is off until the game lets go of the squad
#
# A march is priced by the ORDER, not by the distance: live,
# `CalcMarchSpeedByConfig(ATTACK_MONSTER)` is 0.765 tiles a second and `COLLECT` is
# 1.930 — **2.52 times faster**, out of two bonuses the player levels separately. Since
# golden zombies live several hundred tiles from anybody's base, the haul is most of the
# cost of a kill: across the live queue of 80, the farthest was 680 tiles — **888 s
# marched straight there against 361 s ridden**. The ride is free, too:
# `GetCostStaminaByTargetType(COLLECT)` is 0.
#
# All of that is real and measured, including the clock: a plan priced a ride at 285 s
# and the march the server actually made answered 271 s to arrival.
#
# **And the manoeuvre still does not finish.** The squad rode out, landed at the mine,
# and the attack sent from there was refused in silence — fourteen seconds of polling and
# the server never took the energy. A squad that has arrived at a mine is GATHERING, and
# the game does not let a bare `SendCreateMarchMessage` move it on. That is the same
# missing step the chain's second kill needs, and until it is solved a ride would strand
# the squad at a mine having bought nothing.
#
# So the switch ships OFF. Everything it needs is here and measured; what is missing is
# one call — how the game takes an army off a resource node without walking it home —
# and docs/research/golden-zombies.md says exactly what was tried.
#
# ## The scan
#
# `scan = 1` walks the camera over the whole server first (`scan_map.md`), which is what
# fills the client's own invasion list; the queue is then read from it in one call, and
# from two sources in order:
#
#   * the invasion enumerator — `WorldScene:GetMonsterListInArea` with the config id as
#     its whitelist and a radius wide enough to mean «everything the client knows». It
#     answers uuid AND tile, which is everything the send needs, with nothing opened and
#     nothing tapped. Live, that was 11 monsters before a lap of the map and 135 after
#     one;
#   * the drawn clones around the camera, for anything the enumerator misses. A clone
#     knows its tile and not its uuid — the uuid is the server's answer — so that one is
#     completed by a single point-popup open, read and close before it is marched at.
#
# The queue is re-scanned after every kill, because the event keeps spawning.
#
# ## Arguments
#
#   squad       which squad goes, by the SLOT the player sees (1/2/3/4). The panel's
#               «События» tab is where it is chosen.
#   radius      how many tiles around the base the enumerator is asked about. The
#               default is wider than the map on purpose: the list it filters is the
#               client's own, so a wide ask is «everything you know» and costs nothing.
#   scan        1 to walk the whole map first, 0 to work with what is already loaded.
#   limit       stop after this many attacks; 0 means «as many as the energy allows».
#   approach    ride to a far target on a gather order before attacking it. **OFF by
#               default, and the reason is a measurement rather than caution** — see
#               «the ride» below. Turn it on from «События» when the missing step is
#               solved.
#   miss_limit  how many sends in a row may produce no march before the run stops. The
#               ordinary reason for one is a zombie that was already dead — the client's
#               list is a snapshot and the ground near a base is farmed by everybody — so
#               a couple in a row says nothing about the client. Past this many it is the
#               link, not the map, and the run stops.
#   march_wait  how many three-second beats to wait for one march before giving up on it.
#               The default is ten minutes because the FIRST march of a chain can be long:
#               live, the nearest of 134 golden zombies to the base was once 492 tiles
#               away — they cluster in their own region of the map — and that leg took
#               over four minutes. Every march after it is a few tiles, which is the whole
#               point — and the last four seconds of every march are watched in
#               one-second beats instead, because a three-second beat spent an average of
#               a second and a half of every kill waiting for a squad that had already
#               landed (#1702).
#
# ## What is proven, and what is not
#
# Proven against the live client on 2026-08-19: the config read, the energy read, the
# price of an attack, the squad lookup, the enumerator (134 golden zombies queued after
# one lap of the map), the pick, the send — the server charged the ten energy for it —
# and the whole thing played from the phone, which filed its report and re-read the board.
# **The chain past the first kill is not proven yet**: the first march was 492 tiles and
# the wait then ran out at four minutes, which is what the ten-minute default above is
# for. docs/research/golden-zombies.md says exactly what is still waiting on a run long
# enough to show it.

ARGS squad = 1
ARGS radius = 2000
ARGS scan = 1
ARGS limit = 0
ARGS march_wait = 200
ARGS approach = 0
ARGS approach_sec = 60
ARGS approach_reach = 12
ARGS miss_limit = 3

# This run may take a march's worth of minutes; nothing else waits for it (docs/dsl.md).
DETACH

# The map, first. Everything below reads the world's own controller, which does not
# exist while the base is on screen — and the camera lands on the base, which is what
# the arm below takes for home.
IF scene != world
    LOG "Putting the map up first — the monsters live in the world scene."
    GAME WORLD
    WAIT scene == world WITHIN 30s

# A squad that reads zero soldiers is usually a squad the client has never asked about,
# and every gate downstream believes the zero (#1285). One request per empty slot, about
# a third of a second, no window.
CALL fill_empty_squads

# What the run is allowed to do, parked where the presses can read it — `TAP` carries no
# arguments of its own.
LUA DataCenter.__lw_gold_squad = {squad}
LUA DataCenter.__lw_gold_radius = {radius}
LUA DataCenter.__lw_gold_limit = {limit}
LUA DataCenter.__lw_gold_back = 0
LUA DataCenter.__lw_gold_approach_sec = {approach_sec}
LUA DataCenter.__lw_gold_approach_reach = {approach_reach}

TAP golden_arm

READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end if (tonumber(p.soldiers) or 0) <= 0 then return -1 end return 1 end)() INTO armed

IF armed == 0
    FAIL "there is no such squad on this account — check the slot chosen on «События»"
IF armed < 0
    FAIL "the chosen squad has no soldiers in it — fill it and try again"

READ_LUA (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() INTO energy
READ_LUA (function() local v = nil pcall(function() v = tonumber(MarchUtil.GetCostStaminaByTargetType(MarchTargetType.ATTACK_MONSTER)) end) if v == nil or v <= 0 then return 10 end return math.floor(v) end)() INTO cost

# One reading rather than two compared: the DSL's conditions weigh a variable against a
# NUMBER, so a gate between two readings is arithmetic the game does, not the recipe.
READ_LUA (((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() >= (function() local v = nil pcall(function() v = tonumber(MarchUtil.GetCostStaminaByTargetType(MarchTargetType.ATTACK_MONSTER)) end) if v == nil or v <= 0 then return 10 end return math.floor(v) end)()) and 1 or 0) INTO has_energy

IF has_energy == 0
    FAIL "no energy left — one attack costs {cost} and there is {energy}"

# IS THE SQUAD ALREADY OUT? (#1702) A run starts with no march of its own parked, so the
# arrival gate below has nothing to wait for and the first send goes out at once — into a
# squad that is still walking, which the server refuses in silence. Live, two runs in a
# row spent their first two picks that way and stopped. If the squad reads «out», the
# clock of whatever it is doing is parked here, and the ordinary wait at the top of the
# chain sits it out before the first send.
READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end local st = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then st = math.floor(tonumber(v.state) or 0) end end end) return ((st or 0) == 1) and 1 or 0 end)() INTO squad_out
IF squad_out == 1
    LOG "the chosen squad is still out — waiting for it to land before the first send"
    TAP golden_eta

# One lap of the whole server, so the client's own invasion list is filled. Skippable: a
# second run a minute later is working with the same map.
IF scan == 1
    CALL scan_map
    # TAKE WHAT THE LAP LOADED, WHERE IT ENDED — before the camera goes anywhere (#1702).
    # The queue only ever grows, and the client answers about the districts it HOLDS:
    # flying home first and asking there threw the whole lap's catch away, and a press
    # over a warzone with hundreds of them answered «not one golden zombie on the map».
    TAP golden_scan

# THE NEAR GROUND, RING BY RING (#1702). The client answers about what it has DRAWN, and
# it draws a window of some sixty tiles around the camera — so a lap of the whole map
# leaves the queue holding wherever the lap ended, and one look at the base is blind to a
# zombie sixty tiles out that the player is looking at on their own screen. Live: 140
# queued with the nearest 500 tiles away, and twelve within sixty tiles of a tile the
# operator pointed at. The sweep walks rings around the base on the game's own timer and
# reads the enumerator at every stop.
TAP golden_ring
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.sweep_done) or 0) == 1) and 1 or 0 end)() INTO swept
WHILE swept == 0 LIMIT 27
    WAIT 1
    READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.sweep_done) or 0) == 1) and 1 or 0 end)() INTO swept

# …and then the camera onto the origin, and ask again — so the far catch of the lap, the
# near ring and the base's own district all end up in the same queue. The origin of the
# first pick is the base, which is where the squad is standing.
TAP golden_look_from
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.looked_moved) or 0) == 1) and 1 or 0 end)() INTO looked_moved
IF looked_moved == 1
    WAIT 1.5
TAP golden_scan

READ_LUA (function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() INTO queued

LOG "golden zombies queued: {queued}; energy {energy}, one attack costs {cost}"

IF queued == 0
    FAIL "not one golden zombie on the map — the invasion is between waves"

READ_LUA (function() local p = DataCenter.__lw_gold or {} local left = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = math.floor(tonumber(p.cost) or 10) if cost <= 0 then cost = 10 end if left < cost then return 0 end local lim = math.floor(tonumber(p.limit) or 0) if lim > 0 and (tonumber(p.attacks) or 0) >= lim then return 0 end return ((function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() > 0) and 1 or 0 end)() INTO go

WHILE go == 1 LIMIT 24
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
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 0 end return ((due - ((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)())) > 4000) and 1 or 0 end)() INTO far

    # …and the last few seconds closely, so a two-tile hop is not rounded up to three.
    WHILE arrived == 0 LIMIT 15
        WAIT 1
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local due = tonumber(p.eta_ms) if due == nil then return 1 end return (((function() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then pcall(function() t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end if t == nil then t = os.time() * 1000 end return t end)()) >= due) and 1 or 0 end)() INTO arrived

    IF arrived == 0
        LOG "the squad is still on the road after the wait — stopping rather than sending orders nobody can carry out"
        READ_LUA (0) INTO go

    IF go == 1
        # What is loaded right now, before the camera moves off it (#1702) …
        TAP golden_scan
        # … and then where the next pick is measured from — the last kill, or the base
        # before the first one — so that district is loaded before it is asked about.
        TAP golden_look_from
        # …and the settle only when it really flew: a kill two tiles from the last one is
        # inside the district the client is already holding (#1702).
        READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.looked_moved) or 0) == 1) and 1 or 0 end)() INTO looked_moved
        IF looked_moved == 1
            WAIT 1.5
        TAP golden_scan
        # THE ATTACK IS OVER WHEN THE ZOMBIE IS GONE (#1702). The march is the order; the
        # monster vanishing off the map is the fight. A zombie somebody else killed first
        # answers the same way, which is right — the question is whether it is still there to
        # be fought — and one that outlives the wait costs the chain nothing but the wait.
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local t = p.hit if t == nil then return 1 end local ws = _G.__LW_GOLD_WS local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) _G.__LW_GOLD_WS = ws end if ws == nil then return 1 end local want = tostring(t.key or t.uuid or 0) local there = false pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) return there and 0 or 1 end)() INTO gone
        WHILE gone == 0 LIMIT 8
            WAIT 1
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local t = p.hit if t == nil then return 1 end local ws = _G.__LW_GOLD_WS local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) _G.__LW_GOLD_WS = ws end if ws == nil then return 1 end local want = tostring(t.key or t.uuid or 0) local there = false pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) return there and 0 or 1 end)() INTO gone
        IF gone == 1
            TAP golden_kill
        ELSE
            LOG "the zombie is still standing — another player's kill, or a fight still running; moving on"
            TAP golden_kill_drop

        TAP golden_pick
        READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick_report
        LOG "first choice: {pick_report}"
        READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO picked

        # THE CLIENT ONLY KNOWS THE DISTRICTS IT HAS LOADED, so the first choice is the
        # minimum over what was known — and looking AT it teaches the client its
        # neighbours (#1702). Live: the chain chose one 500 tiles from the base, the scan
        # taken once the camera was on it turned up one at 484, and the operator saw the
        # bot walk past the nearer zombie. So the choice is made again over the bigger,
        # fresher queue; a second pick can only be nearer, because it is the minimum over
        # a superset measured from the same origin.
        IF picked == 1
            TAP golden_look
            WAIT 1
            TAP golden_scan
            TAP golden_pick
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick_report
            LOG "target: {pick_report}"
            READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.cur == nil then return 0 end return ((tonumber(p.cur.uuid) or 0) == 0) and 1 or 0 end)() INTO needs_uuid
            IF needs_uuid == 1
                TAP golden_touch
                TAP golden_grab
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local t = p.cur if t == nil then return 1 end local ws = _G.__LW_GOLD_WS local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) _G.__LW_GOLD_WS = ws end if ws == nil then return 1 end local want = tostring(t.key or t.uuid or 0) local there = false pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) local e = res:GetEnumerator() while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) return there and 1 or 0 end)() INTO here
            IF here == 0
                LOG "that zombie is not on the map any more — dropping it and picking another"
                TAP golden_drop_target
                READ_LUA (0) INTO picked

        IF picked == 1
            # THE RIDE. A gather order travels 2.5x faster than an attack one, so a long
            # haul is ridden to a mine beside the zombie and only the last few tiles are
            # paid at attack speed. Taken only when the arithmetic wins — a short hop
            # loses more to the extra stop than it saves.
            IF approach == 1
                # No camera move here any more: the check above (#1702) has just flown to
                # this very target and re-scanned, which is the same district
                # `HasPointInfo` needs for the mine hunt below.
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
            # The last march of the run is the one that brings the squad home; every one
            # before it deliberately leaves it standing where it killed.
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
            READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local seen = p.march_before or {} local fresh = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and not seen[u] then fresh = fresh + 1 end end end end) return (fresh > 0) and 1 or 0 end)() INTO launched
            WHILE launched == 0 LIMIT 15
                WAIT 0.7
                READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local seen = p.march_before or {} local fresh = 0 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) if u ~= nil and not seen[u] then fresh = fresh + 1 end end end end) return (fresh > 0) and 1 or 0 end)() INTO launched

            IF launched == 0
                # A ZOMBIE SOMEBODY ELSE KILLED FIRST, nearly always: the client's list is
                # a snapshot, and the server refuses an order at a monster that is not
                # there. That is worth another target, not the end of the run — but a
                # client that has gone deaf refuses everything, so two in a row stop it.
                # IS THE SQUAD STUCK WHERE IT STANDS? (#1702) A squad on DIRTY GROUND —
                # the fouled tiles the invasion leaves — takes neither an attack nor a
                # move, and refuses in exactly the same silence as a dead target. It reads
                # as an army that is there and a `canMarch` the game says is false, so the
                # chain takes the squad off that ground and goes on from the base instead
                # of counting the refusal against a client that is answering perfectly.
                READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end local n, can = 0, true pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then n = math.floor(tonumber(v.totalSoldierNum) or 0) can = (v.canMarch == true) end end end) return ((n > 0) and (can == false)) and 1 or 0 end)() INTO stuck
                IF stuck == 1
                    LOG "the squad will not take orders where it stands — dirty ground; walking it home and carrying on"
                    TAP golden_unstick
                ELSE
                    LOG "the send never became a march — that zombie is gone, or this squad has forgotten its army; trying the next one"
                    TAP golden_miss
                    # A SQUAD THE CLIENT HAS FORGOTTEN THE ARMY OF reads zero soldiers,
                    # and the server refuses a march for an empty formation — silently,
                    # exactly like a dead target (#1285, #1702). One question puts them
                    # back, and it costs a third of a second.
                    CALL fill_empty_squads
                    READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.misses) or 0) end)() INTO misses
                    IF misses > {miss_limit}
                        LOG "several sends in a row went nowhere — stopping rather than giving orders nobody is receiving"
                        READ_LUA (0) INTO go
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
        IF go == 1
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local left = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = math.floor(tonumber(p.cost) or 10) if cost <= 0 then cost = 10 end if left < cost then return 0 end local lim = math.floor(tonumber(p.limit) or 0) if lim > 0 and (tonumber(p.attacks) or 0) >= lim then return 0 end return ((function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() > 0) and 1 or 0 end)() INTO go

READ_LUA (function() local p = DataCenter.__lw_gold or {} return 'found=' .. tostring(math.floor(tonumber(p.found) or 0)) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) .. ' kills=' .. tostring(math.floor(tonumber(p.kills) or 0)) .. ' dropped=' .. tostring(math.floor(tonumber(p.dropped) or 0)) .. ' unstuck=' .. tostring(math.floor(tonumber(p.unstuck) or 0)) .. ' spent=' .. tostring(math.floor(tonumber(p.spent) or 0)) .. ' cost=' .. tostring(math.floor(tonumber(p.cost) or 0)) .. ' energy=' .. tostring((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)()) .. ' queued=' .. tostring((function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)()) .. ' squad=' .. tostring(math.floor(tonumber(p.squad) or 0)) end)() INTO golden_report
READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.attacks) or 0) end)() INTO attacks
READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.kills) or 0) end)() INTO kills
READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.spent) or 0) end)() INTO spent
READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.rode) or 0) end)() INTO rode
READ_LUA (function() local p = DataCenter.__lw_gold or {} return 'why=' .. tostring(p.why or '-') .. ' direct=' .. tostring(math.floor(tonumber(p.direct_sec) or 0)) .. ' via=' .. tostring(math.floor(tonumber(p.approach_sec) or 0)) .. ' rode=' .. tostring(math.floor(tonumber(p.rode) or 0)) .. ' atk=' .. string.format('%.3f', tonumber(p.speed_atk) or 0) .. ' col=' .. string.format('%.3f', tonumber(p.speed_col) or 0) end)() INTO ride_report

IF attacks == 0
    FAIL "nothing was sent — {golden_report}"

LOG "golden zombies: {attacks} attack(s) sent, {kills} confirmed gone, {spent} energy spent, {rode} ride(s) — {golden_report} · {ride_report}"
