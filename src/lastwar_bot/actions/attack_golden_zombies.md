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
# for the same twelve kills.
#
# The first pick has no previous kill to measure from, so it asks the game the one
# question that answers itself — `SceneUtils.TileDistanceToMyHome`, the distance from the
# base, which is where the squad is standing before the first march. **Not the tile under
# the camera**: that is the base only if the world scene was just entered, and a client
# the panel keeps on the map has its camera wherever the last lap of `scan_map` left it.
# Only the LAST march brings the squad back, because a squad left standing on the world
# map when a run ends is a squad somebody else can hit.
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
#   march_wait  how many three-second beats to wait for one march before giving up on it.
#               The default is ten minutes because the FIRST march of a chain is long:
#               live, the nearest of 134 golden zombies to the base was 492 tiles away —
#               they cluster in their own region of the map — and that leg took over four
#               minutes. Every march after it is a few tiles, which is the whole point.
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
ARGS approach = 1
ARGS approach_sec = 60
ARGS approach_reach = 12

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

# One lap of the whole server, so the client's own invasion list is filled. Skippable: a
# second run a minute later is working with the same map.
IF scan == 1
    CALL scan_map

TAP golden_scan

READ_LUA (function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() INTO queued

LOG "golden zombies queued: {queued}; energy {energy}, one attack costs {cost}"

IF queued == 0
    FAIL "not one golden zombie on the map — the invasion is between waves"

READ_LUA (function() local p = DataCenter.__lw_gold or {} local left = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = math.floor(tonumber(p.cost) or 10) if cost <= 0 then cost = 10 end if left < cost then return 0 end local lim = math.floor(tonumber(p.limit) or 0) if lim > 0 and (tonumber(p.attacks) or 0) >= lim then return 0 end return ((function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() > 0) and 1 or 0 end)() INTO go

WHILE go == 1 LIMIT 24
    # A squad that is already out cannot be sent, and the send is refused in silence —
    # which is exactly how a whole run came to spend nothing and say nothing (#1519). So
    # the wait is here, BEFORE the pick, and it is the same wait for the squad coming
    # back from the previous kill.
    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end local st = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then st = math.floor(tonumber(v.state) or 0) end end end) return ((st or 0) == 1) and 1 or 0 end)() INTO marching
    WHILE marching == 1 LIMIT {march_wait}
        WAIT 3
        READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end local st = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then st = math.floor(tonumber(v.state) or 0) end end end) return ((st or 0) == 1) and 1 or 0 end)() INTO marching

    IF marching == 1
        LOG "the squad is still out after the wait — stopping rather than sending orders nobody can carry out"
        READ_LUA (0) INTO go

    IF go == 1
        TAP golden_pick
        READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.cur == nil then return 0 end return ((tonumber(p.cur.uuid) or 0) == 0) and 1 or 0 end)() INTO needs_uuid

        # A target found as a drawn clone knows its tile and not its uuid, and a send
        # with `uuid = 0` is refused in silence. One popup open, one read, one close —
        # of the POPUP, never of the HUD with it.
        IF needs_uuid == 1
            TAP golden_touch
            TAP golden_grab

        READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO picked

        IF picked == 1
            # THE RIDE. A gather order travels 2.5x faster than an attack one, so a long
            # haul is ridden to a mine beside the zombie and only the last few tiles are
            # paid at attack speed. Taken only when the arithmetic wins — a short hop
            # loses more to the extra stop than it saves.
            IF approach == 1
                # The camera first: `HasPointInfo` can only answer for a district
                # the client has actually loaded, and the target is usually one
                # it has never been to.
                TAP golden_look
                TAP golden_approach_arm
                READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.approach ~= nil) and 1 or 0 end)() INTO riding
                IF riding == 1
                    READ_LUA (function() local p = DataCenter.__lw_gold or {} return 'why=' .. tostring(p.why or '-') .. ' direct=' .. tostring(math.floor(tonumber(p.direct_sec) or 0)) .. ' via=' .. tostring(math.floor(tonumber(p.approach_sec) or 0)) .. ' rode=' .. tostring(math.floor(tonumber(p.rode) or 0)) .. ' atk=' .. string.format('%.3f', tonumber(p.speed_atk) or 0) .. ' col=' .. string.format('%.3f', tonumber(p.speed_col) or 0) end)() INTO ride_report
                    LOG "riding to a mine beside the target — {ride_report}"
                    TAP golden_ride
                    READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end local st = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then st = math.floor(tonumber(v.state) or 0) end end end) return ((st or 0) == 1) and 1 or 0 end)() INTO marching
                    WHILE marching == 1 LIMIT {march_wait}
                        WAIT 3
                        READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end local st = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then st = math.floor(tonumber(v.state) or 0) end end end) return ((st or 0) == 1) and 1 or 0 end)() INTO marching
            # The last march of the run is the one that brings the squad home; every one
            # before it deliberately leaves it standing where it killed.
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local left = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = math.floor(tonumber(p.cost) or 10) if cost <= 0 then cost = 10 end if left < cost * 2 then return 1 end local lim = math.floor(tonumber(p.limit) or 0) if lim > 0 and (tonumber(p.attacks) or 0) + 1 >= lim then return 1 end return ((function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() <= 1) and 1 or 0 end)() INTO last_one
            IF last_one == 1
                LUA DataCenter.__lw_gold_back = 1
                TAP golden_home
            ELSE
                TAP golden_send

            # The proof is the SERVER charging the energy, never the send returning
            # cleanly.
            READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local before = tonumber(p.before) if before == nil then return 1 end local cost = math.floor(tonumber(p.cost) or 10) return ((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() <= (before - cost)) and 1 or 0 end)() INTO settled
            WHILE settled == 0 LIMIT 10
                WAIT 0.7
                READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.pending == nil then return 1 end local before = tonumber(p.before) if before == nil then return 1 end local cost = math.floor(tonumber(p.cost) or 10) return ((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() <= (before - cost)) and 1 or 0 end)() INTO settled

            IF settled == 0
                LOG "the squad was sent and the energy was not charged — stopping rather than spending the rest of it on sends nobody is receiving"
                READ_LUA (0) INTO go
            ELSE
                # The tally moves HERE and nowhere else.
                TAP golden_confirm
                # The event keeps spawning while the squad is out.
                TAP golden_scan

        IF go == 1
            READ_LUA (function() local p = DataCenter.__lw_gold or {} local left = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = math.floor(tonumber(p.cost) or 10) if cost <= 0 then cost = 10 end if left < cost then return 0 end local lim = math.floor(tonumber(p.limit) or 0) if lim > 0 and (tonumber(p.attacks) or 0) >= lim then return 0 end return ((function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() > 0) and 1 or 0 end)() INTO go

READ_LUA (function() local p = DataCenter.__lw_gold or {} return 'found=' .. tostring(math.floor(tonumber(p.found) or 0)) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) .. ' spent=' .. tostring(math.floor(tonumber(p.spent) or 0)) .. ' cost=' .. tostring(math.floor(tonumber(p.cost) or 0)) .. ' energy=' .. tostring((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)()) .. ' queued=' .. tostring((function() local p = DataCenter.__lw_gold or {} local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)()) .. ' squad=' .. tostring(math.floor(tonumber(p.squad) or 0)) end)() INTO golden_report
READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.attacks) or 0) end)() INTO attacks
READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.spent) or 0) end)() INTO spent
READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.rode) or 0) end)() INTO rode
READ_LUA (function() local p = DataCenter.__lw_gold or {} return 'why=' .. tostring(p.why or '-') .. ' direct=' .. tostring(math.floor(tonumber(p.direct_sec) or 0)) .. ' via=' .. tostring(math.floor(tonumber(p.approach_sec) or 0)) .. ' rode=' .. tostring(math.floor(tonumber(p.rode) or 0)) .. ' atk=' .. string.format('%.3f', tonumber(p.speed_atk) or 0) .. ' col=' .. string.format('%.3f', tonumber(p.speed_col) or 0) end)() INTO ride_report

IF attacks == 0
    FAIL "nothing was sent — {golden_report}"

LOG "golden zombies: {attacks} attack(s) sent, {spent} energy spent, {rode} ride(s) — {golden_report} · {ride_report}"
