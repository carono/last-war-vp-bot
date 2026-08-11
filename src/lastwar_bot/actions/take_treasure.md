# Work ONE named chest: send a squad if it still needs digging, take the gift when it is dug.
# ru: Отработать одно указанное сокровище: отправить отряд, если ещё копают, и забрать подарок.
#
#   run take_treasure {"uuid": 1000000000000000001, "server": 100, "pid": 500553, "x": 552, "y": 500}
#   run take_treasure {"uuid": 1000000000000000001, "server": 100}      -- claim only: no tile known
#
# THE ROW'S OWN PRESS, AND WHY IT IS A RECIPE NOW (#1318). «Кнопка принудительного сбора
# может не срабатывать.» It could not do otherwise: each row of «Командный пункт» drove the
# game by hand — one march assembled in the panel, or one claim sent and reported as done
# because the send did not throw. A send that returns cleanly proves NOTHING here: a refused
# claim is silent, and the reply comes back under the same command name with no readable
# fields (`docs/research/world-treasures.md`). So the button said «взято» and nothing
# arrived, which is exactly what the player saw.
#
# What a press means instead: THIS chest joins the errand's own queue, and everything that
# already works for a chest the errand heard about works for it too — the nearest free
# squad is paired with it, the dig's own deadline is read off our march, the claim leaves in
# the frame that deadline passes, and it goes again until the chest is paid or gone. The
# panel keeps nothing: the row still moves when the READING moves (`CLAUDE.md`).
#
# BOTH ROW BUTTONS PLAY THIS ONE FILE, and that is deliberate rather than lazy. «Копать» and
# «Забрать» are not two abilities — they are one ability, drawn with the word the reading
# earned: a chest whose finisher field is filled says «раскопано» and one whose is not says
# «копают». Which of the two the game will actually accept is the game's answer and not the
# panel's guess, and the errand asks it properly: a chest with no squad out gets one, a
# chest whose dig is over gets a claim. A button that had to choose would be the panel
# holding a gate, which is the thing that may never happen here.
#
# WITH NO TILE it is a claim and says so. A chest heard through the alliance's dig feed
# carries a uuid and no position, so there is nothing to march at; it is queued `claim_only`
# and taken by the claim alone. Give `pid`/`x`/`y` and the same chest is upgraded rather
# than duplicated — one target, keeping the best half of every door it came through.
#
# The protocol: `docs/research/world-treasures.md`. The primitives are `treasure_*` in
# `tools/lib/lua_actions.py`; the standing errand that hears chests by itself is
# `auto_treasure.md`.

# WHICH CHEST. `uuid` is the only one that is required — it is what a claim carries. The
# tile is what a march needs, and a caller that has it says so.
ARGS uuid = 0
ARGS server = 0
ARGS pid = 0
ARGS x = 0
ARGS y = 0

# Which squads may be spent on it, in the order they may be spent — the same 1/2/3/4 the
# player sees in the dispatch panel.
ARGS squads = [1, 2, 3, 4]

ARGS grace = 240
ARGS ttl = 1800

# What this run may spend and which chest it is about, parked where the presses can read
# them: a `TAP` takes no arguments of its own (`docs/dsl.md`).
LUA DataCenter.__lw_treasure_squads = { {squads} } DataCenter.__lw_treasure_grace = {grace} DataCenter.__lw_treasure_ttl = {ttl} DataCenter.__lw_treasure_one = {uuid={uuid}, server={server}, pid={pid}, x={x}, y={y}}

# The ear, the watch and the rules, exactly as the standing errand arms them — a row press
# on a client that has never run the errand must not be a lesser press than one that has.
TAP treasure_auto_arm

# THIS chest into the queue. Already there and it is upgraded with whatever half this press
# brought; already spent and it is started over, because a person pressing a button is
# saying «try it again» and that is the one case a person can see something the errand
# cannot.
TAP treasure_queue_one

# One step of the whole queue: the nearest free squad marches at the nearest chest that
# needs one, and the claim half runs at the end of the same chunk.
TAP treasure_auto_step

READ_LUA (DataCenter.__lw_treasure_auto and DataCenter.__lw_treasure_auto.report or "the step left no report — the press did not run") INTO report

LOG "the line above is what the press did: sent= marches that went out, claimed= claims sent, paid= gifts actually received, waiting= chests whose squad is still out or whose claim has not answered, resent= sends the client had dropped in silence, lag=/worst= milliseconds from takeable to claim, and one note per chest. A press that reports nothing but `waiting` has NOT failed — the watch it just started is what finishes the chest, in the frame its dig ends."

# Where this chest stands now, in its own words rather than the queue's — the row that
# pressed reads this back, and «ещё копают» has to be distinguishable from «уже пробовали и
# сервер отказал».
READ_LUA (function() local A = DataCenter.__lw_treasure_auto if A == nil then return 'the errand has never been armed' end for _, t in ipairs(A.targets or {}) do if tostring(t.uuid) == '{uuid}' then return tostring(t.state or (t.done and tostring(t.why) or 'queued')) .. (t.squad and (' squad' .. tostring(t.squad)) or '') .. ((tonumber(t.lag) ~= nil) and (' lag' .. tostring(t.lag) .. 'ms') or '') end end return 'this chest is not in the queue' end)() INTO chest

LOG "the line above is where THIS chest stands: to-send= waiting for a free squad, squadN= a squad has just gone, digging-Ns= our squad is digging and the claim is already scheduled for the second it finishes, claimN= the Nth claim has gone out, paid / already-had-it= the gift is in, foreign= another alliance's chest, which the game refuses outright, expired= it is off the map"
