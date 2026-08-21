# Attack the golden zombies one after another, from wherever the squad is, until the energy runs out. (the second squad)
# ru: Бить золотых зомби одного за другим — от места, где стоит отряд, — пока не кончится энергия. (второй отряд)
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
#               a few in a row say nothing about the client. Six, because three ended runs
#               that had a live squad, a live link and a hundred targets left (#1702).
#               Past this many it is the link, not the map, and the run stops.
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
ARGS reach = 600
ARGS reach_far = 700
ARGS breather = 90
ARGS breathers = 30
ARGS scan = 1
ARGS limit = 0
ARGS march_wait = 200
ARGS approach = 0
ARGS approach_sec = 60
ARGS approach_reach = 12
ARGS miss_limit = 6
# How many targets have to be PROVEN gone before the ground is worth redrawing.
# The operator's band is 2–5; 0 switches the redraw off and leaves the run on the
# opening lap and the reaping alone.
ARGS refresh_after = 3

# This run may take a march's worth of minutes; nothing else waits for it (docs/dsl.md).
DETACH

# THE SESSION, BEFORE THE SCENE (#1702). A client that has just been restarted answers
# everything plausibly while it is still on the login screen — the panel's own rule,
# and the reason every other brick of this chain opens with the same line. This one did
# not, and it opened by switching scenes instead: measured tonight, two runs started
# within thirty seconds of a fresh client and both times the log's next entry was
# «клиент пропал — процесса игры больше нет». That is a correlation and not yet a
# proof, but the ordering is right whichever way it turns out: a run that cannot be
# played yet should say so, not drive a half-loaded client into the world map.
WAIT client == ready WITHIN 180s

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
LUA DataCenter.__lw_gold2_squad = {squad}
LUA DataCenter.__lw_gold2_radius = {radius}
LUA DataCenter.__lw_gold2_reach = {reach}
LUA DataCenter.__lw_gold2_reach_far = {reach_far}
LUA DataCenter.__lw_gold2_breathers = {breathers}
LUA DataCenter.__lw_gold2_limit = {limit}
LUA DataCenter.__lw_gold2_back = 0
LUA DataCenter.__lw_gold2_approach_sec = {approach_sec}
LUA DataCenter.__lw_gold2_approach_reach = {approach_reach}
LUA DataCenter.__lw_gold2_refresh_after = {refresh_after}

TAP golden2_arm

# A RUN THAT STARTS BEHIND A GATHERING SQUAD FREES IT FIRST (#1702). The operator
# watched this happen: the ride took the squad to a mine, the zombie was killed by
# somebody else while it travelled, the squad landed and started gathering — 24 762
# seconds of it — and pressing «охота» again moved nothing, because every order after
# that is refused in silence. The recall the chain had was the one that does not work
# on a gather: `OnBackHome(formation)` frees a squad that is walking and leaves one
# that is working. The MARCH's own uuid is what a person taps in the game, and it
# brought the squad home in under a minute (`golden_unstick` sends that now).
READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local out = 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then if math.floor(tonumber(v.state) or 0) ~= 0 then out = 1 end end end end) return out end)() INTO standing_out
IF standing_out == 1
    LOG "the squad is out before this hunt has ordered anything — bringing it home first"
    TAP golden2_unstick
    WAIT 8
    CALL fill_empty_squads

READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end if p.formation == nil then return 0 end if (tonumber(p.soldiers) or 0) <= 0 then return -1 end return 1 end)() INTO armed

IF armed == 0
    FAIL "there is no such squad on this account — check the slot chosen on «События»"
IF armed < 0
    FAIL "the chosen squad has no soldiers in it — fill it and try again"

# IS THIS SQUAD ALSO THE RALLY'S? (#1702) Measured live, and it explains an evening of
# «залипаний» that were nothing of the kind: the auto-join was set to squads 1, 2 and 3 —
# every squad the account HAS — so an alliance banner took the hunt's squad within seconds
# of it coming home, over and over, and the hunt spent its laps waiting for a squad that
# was standing in somebody's rally. That is a настройка and not a bug, so the run says it
# plainly once and carries on rather than deciding for the person.
READ_LUA (function() local want = math.floor(tonumber((DataCenter.__lw_gold2 or {}).squad) or 0) local t = DataCenter.__lw_rally_squads if type(t) ~= 'table' then return 0 end for _, v in ipairs(t) do if math.floor(tonumber(v) or -1) == want then return 1 end end return 0 end)() INTO squad_is_rallying
IF squad_is_rallying == 1
    LOG "heads up: the squad this hunt uses is also one the rally auto-join takes, so a banner can walk off with it mid-hunt"

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
READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end if p.formation == nil then return 0 end local st = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then st = math.floor(tonumber(v.state) or 0) end end end) return ((st or 0) == 1) and 1 or 0 end)() INTO squad_out
IF squad_out == 1
    LOG "the chosen squad is still out — waiting for it to land before the first send"
    TAP golden2_eta

# One lap of the whole server, so the client's own invasion list is filled. Skippable: a
# second run a minute later is working with the same map.
IF scan == 1
    CALL scan_map
    # TAKE WHAT THE LAP LOADED, WHERE IT ENDED — before the camera goes anywhere (#1702).
    # The queue only ever grows, and the client answers about the districts it HOLDS:
    # flying home first and asking there threw the whole lap's catch away, and a press
    # over a warzone with hundreds of them answered «not one golden zombie on the map».
    TAP golden2_scan

# THE SECOND LAP IS GONE, AND SO IS THE RE-PICK AFTER EVERY KILL (#1702). The operator's
# model — «беглого просмотра карты достаточно… не нужно потом второй раз ходить» — with
# one correction the client forced and the note below records: a lap alone does not leave
# a registry, because it outruns the loader. What the lap DOES leave is the far picture,
# and from the first march onwards the registry is kept honest by the chain itself: every
# scan REAPS, so a target the map was read at and did not return is taken out, exactly
# the way a secret task leaves its list (#1272). The expensive redraw then happens on a
# THRESHOLD of proven disappearances rather than on every kill.

# …AND THEN THE GROUND THE CHAIN STARTS FROM, DWELT ON RATHER THAN GLANCED AT (#1702).
#
# THE MEASUREMENT THIS TURNS ON, because it contradicts the obvious guess: a lap moves the
# camera every 0.05 s, which is far faster than the client's region loader, so the lap
# gives the FAR picture and leaves the near ground blank. Standing 488 tiles out after a
# lap, the client answered «0 golden zombies within 300 tiles of the base». Thirteen
# camera stops later it answered «17, the nearest 14 tiles away». The ground was never
# empty — it was never loaded, and one wide look at the lap's own height does not load it
# either (tried: the first pick still came out 488 tiles away). Only dwell does.
#
# So the run opens with the same short ring it uses to redraw stale ground later — seven
# stops around the origin of the first pick, which is the base, where the squad is
# standing. Seven, where the old sweep walked eighteen.
TAP golden2_refresh
READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
WHILE refreshed == 0 LIMIT 12
    WAIT 1
    READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
TAP golden2_scan

# …AND A FIRST PICK FARTHER THAN THE RING COULD SEE IS NOT BELIEVED THE FIRST TIME
# (#1702). The ring above covers about 160 tiles — its own radius plus what the
# enumerator reads at each stop — and beyond that «the nearest golden zombie» means
# «the nearest of the ones the client happens to hold». Measured over 76 opening picks:
# median 47 tiles, tail 569. At the speed the game quotes an attack march, 569 tiles is
# over ten minutes; another ring is nine seconds. So the run doubles its own ring and
# looks again — twice at most, and only while the answer is still far.
READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local ox, oy = nil, nil local o = p.anchor or p.home if o ~= nil then ox, oy = o.x, o.y end local best = nil for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] and _goldfree(p, t.pid) then local d = nil if ox ~= nil then local dx, dy = (t.x - ox), (t.y - oy) d = math.sqrt(dx * dx + dy * dy) else pcall(function() d = tonumber(SceneUtils.TileDistanceToMyHome(t.pid, p.server)) end) end if d ~= nil and (best == nil or d < best) then best = d end end end if best == nil then return -1 end return math.floor(best + 0.5) end)() INTO best_far
WHILE best_far > 160 LIMIT 2
    LOG "the nearest one is beyond what the opening look covers — widening it rather than marching"
    TAP golden2_widen_ring
    TAP golden2_refresh
    READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
    WHILE refreshed == 0 LIMIT 20
        WAIT 1
        READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)() INTO refreshed
    TAP golden2_scan
    READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local ox, oy = nil, nil local o = p.anchor or p.home if o ~= nil then ox, oy = o.x, o.y end local best = nil for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] and _goldfree(p, t.pid) then local d = nil if ox ~= nil then local dx, dy = (t.x - ox), (t.y - oy) d = math.sqrt(dx * dx + dy * dy) else pcall(function() d = tonumber(SceneUtils.TileDistanceToMyHome(t.pid, p.server)) end) end if d ~= nil and (best == nil or d < best) then best = d end end end if best == nil then return -1 end return math.floor(best + 0.5) end)() INTO best_far

READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() INTO queued

LOG "golden zombies queued: {queued}; energy {energy}, one attack costs {cost}"

IF queued == 0
    FAIL "not one golden zombie on the map — the invasion is between waves"

READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local left = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = math.floor(tonumber(p.cost) or 10) if cost <= 0 then cost = 10 end if left < cost then return 0 end local lim = math.floor(tonumber(p.limit) or 0) if lim > 0 and (tonumber(p.attacks) or 0) >= lim then return 0 end return ((function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() > 0) and 1 or 0 end)() INTO go

WHILE go == 1 LIMIT 200
    # ONE LAP OF THE HUNT, FOUR BRICKS (#1702), and the order is the order of the facts:
    # nothing may be chosen while the squad is still walking, nothing may be judged before
    # the march that would have killed it has landed, and nothing may be sent at a target
    # that has not been checked. Each brick runs on its own from the picker, so a hunt
    # that stumbles is debugged one press at a time instead of inside this loop.
    CALL golden2_wait_for_the_march
    IF go == 1
        CALL golden2_judge_the_kill
        CALL golden2_choose_a_target
        # NOTHING WITHIN REACH IS AN ENDING, NOT A LAP (#1702). The invasion clusters, and
        # when its near zombies are dead the queue still holds the far ones the sweep saw —
        # measured live, 72 of them between 580 and 615 tiles out. A chain that keeps
        # choosing from those looks hung for ten minutes per kill, so it says so and stops.
        CALL golden2_send_the_squad
        IF go == 1
            READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local left = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = math.floor(tonumber(p.cost) or 10) if cost <= 0 then cost = 10 end if left < cost then return 0 end local lim = math.floor(tonumber(p.limit) or 0) if lim > 0 and (tonumber(p.attacks) or 0) >= lim then return 0 end return ((function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)() > 0) and 1 or 0 end)() INTO go

READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return 'found=' .. tostring(math.floor(tonumber(p.found) or 0)) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) .. ' kills=' .. tostring(math.floor(tonumber(p.kills) or 0)) .. ' dropped=' .. tostring(math.floor(tonumber(p.dropped) or 0)) .. ' vanished=' .. tostring(math.floor(tonumber(p.vanished) or 0)) .. ' refreshes=' .. tostring(math.floor(tonumber(p.refreshes) or 0)) .. ' unstuck=' .. tostring(math.floor(tonumber(p.unstuck) or 0)) .. ' spent=' .. tostring(math.floor(tonumber(p.spent) or 0)) .. ' cost=' .. tostring(math.floor(tonumber(p.cost) or 0)) .. ' energy=' .. tostring((function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)()) .. ' queued=' .. tostring((function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end local n = 0 for _, t in ipairs(p.targets or {}) do if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)()) .. ' squad=' .. tostring(math.floor(tonumber(p.squad) or 0)) end)() INTO golden_report
READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return math.floor(tonumber(p.attacks) or 0) end)() INTO attacks
READ_LUA (function() local p = DataCenter.__lw_gold2 or {} return math.floor(tonumber(p.kills) or 0) end)() INTO kills
READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return math.floor(tonumber(p.spent) or 0) end)() INTO spent
READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return math.floor(tonumber(p.rode) or 0) end)() INTO rode
READ_LUA (function() local p = DataCenter.__lw_gold2 or {} local _zc = DataCenter.__lw_zclaims if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end local function _goldnow() local t = nil pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) if t == nil then t = os.time() * 1000 end return t end local function _goldfree(p, pid) local c = _zc[tostring(pid)] if c == nil then return true end if tostring(c.sq) == tostring(p.squad) then return true end return (_goldnow() - (tonumber(c.at) or 0)) > (300 * 1000) end local function _goldclaim(p, pid) _zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end return 'why=' .. tostring(p.why or '-') .. ' direct=' .. tostring(math.floor(tonumber(p.direct_sec) or 0)) .. ' via=' .. tostring(math.floor(tonumber(p.approach_sec) or 0)) .. ' rode=' .. tostring(math.floor(tonumber(p.rode) or 0)) .. ' atk=' .. string.format('%.3f', tonumber(p.speed_atk) or 0) .. ' col=' .. string.format('%.3f', tonumber(p.speed_col) or 0) end)() INTO ride_report

IF attacks == 0
    FAIL "nothing was sent — {golden_report}"

LOG "golden zombies: {attacks} attack(s) sent, {kills} confirmed gone, {spent} energy spent, {rode} ride(s) — {golden_report} · {ride_report}"
