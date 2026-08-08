# Sweep the whole world map and queue every treasure chest lying on it.
# ru: Обойти всю карту мира и поставить в очередь каждое сокровище, лежащее на ней.
#
#   run scan_treasures                              -- the server the client is looking at
#   run scan_treasures {"server": 300}              -- that server, whatever the client thinks
#   run scan_treasures {"zoom": 600, "step": 90}    -- the lap's shape
#
# THE THIRD DOOR, AND WHY THE OTHER TWO ARE NOT ENOUGH. `auto_treasure.md` hears a chest
# in two ways, and neither of them looks at the map:
#
#   * the alliance chat share — a thing a PERSON does, and often nobody does it. Measured
#     live: twenty minutes of the alliance digging a chest and not one share crossed the
#     wire;
#   * the dig broadcast (`push.detect.treasure.claim`) — arrives once per member who
#     finishes, and carries a uuid with NO tile. Enough to claim, never enough to march.
#
# So a chest that is simply LYING on the map, announced by nobody, reaches neither. This
# is the door for it: the camera walks the whole server and the client's own point
# manager is read at every stop, which gives both halves at once — the uuid AND the tile.
#
# WHAT «ОБНОВИТЬ» ON «КОМАНДНОМ ПУНКТЕ» ASKS IS NOT THIS. That refresh sends
# `activity.detect.list` and reads the account's own detect-event list: the chests THIS
# alliance's event placed. A chest another alliance put out is not in that reply however
# often it is asked for, which is why refreshing it all day finds nothing.
#
# THE MAP IS NOT ON THE LUA WIRE, measured rather than assumed: with the client's own
# message hook in `wide` mode, three jumps at height 600 produced no `world.get.block`
# at all — the map stream is decoded on the C# side. What IS readable is
# `WorldScene.PointManager`, and its one limit shapes everything here: **it only holds
# what is in view**. Jump away and the old tiles go back to unknown. So the reading has
# to ride the lap, one box per waypoint, which is what `treasure_scan_start` schedules.
#
# A CHEST BELONGS TO AN ALLIANCE, and that is what the lap is really for. The first live
# lap found NINETEEN chests on the map that nobody had said a word about — and eighteen of
# them were other alliances': their claims come back «player not in same alliance», and a
# march at one spends a squad on a tile the server will not pay for. So a foreign chest is
# counted and left alone, and the run says how many there were. What is left is the chests
# this alliance's own event placed, which are the ones a squad can dig.
#
# COST, MEASURED ON THE LIVE CLIENT and not estimated. A 107 × 107 box is 0.03–0.04 s
# inside the VM, and a 1000 × 1000 server at height 600 / step 90 is 121 of them — so the
# reading itself is about four seconds, spread across the lap. What the lap actually costs
# is the CAMERA standing still long enough to be answered: 121 stops at 0.4 s is roughly
# 50 s, and that is the price of reading the map out of the client instead of off a wire.
# Nothing is sent to the server beyond the map requests the camera already makes, no
# window opens, and the errand walks it every few minutes rather than every tick.
#
# The protocol and the measurements: `docs/research/world-treasures.md`. The primitives
# are `treasure_scan_*` in `tools/lib/lua_actions.py`.

# WHICH SERVER the lap walks. 0 — the default — means «ask the client», which is right
# when nobody knows better; a caller that DOES know says so, because the client's answer
# is a cached manager field and live it kept sending the camera back to the server before
# last (#1280).
ARGS server = 0

# The lap's shape. 600 is the last height at which the tiles still arrive in full, and 90
# goes with it (`docs/research/map-sweep-zoom.md`).
#
# `lag` is how long after a jump the box is read and `every` how long the camera then
# stands still, and BOTH are measured rather than picked. A jump's tiles land in one step:
# read live at two spots, the box was empty at 0.05 / 0.10 / 0.15 s and complete at
# 0.20–0.30 s, and no later reading added one. A camera that has already left is a box
# that reads empty — at 0.05 s between waypoints a whole lap knew 2599 tiles, twenty a
# stop, against the 500–1250 a stop holds when it is given its quarter of a second.
ARGS zoom = 600
ARGS step = 90
ARGS every = 0.4
ARGS lag = 0.3

# How long to wait for the lap to finish before reading it. The lap itself is walked by
# the GAME's timer, so nothing here can block on it — this is the wait, and the harvest
# says `waypoints=<done>/<all>` so a wait that was too short is visible rather than
# silent. One lap of a 1000 × 1000 server is 121 waypoints, so about 48 s at the pause
# above; the default leaves room for a client that is answering slowly.
ARGS wait = 60

LUA DataCenter.__lw_treasure_scan_cfg = {zoom={zoom}, step={step}, every={every}, lag={lag}, server={server}}

TAP treasure_scan_start
WAIT {wait}
TAP treasure_scan_harvest

READ_LUA (DataCenter.__lw_treasure_scan and (function() local S = DataCenter.__lw_treasure_scan local c = 0 for _ in pairs(S.found or {}) do c = c + 1 end return 'done=' .. tostring(S.done or 0) .. '/' .. tostring(S.n or 0) .. ' chests=' .. tostring(c) .. ' tiles=' .. tostring(S.tiles or 0) .. ' known=' .. tostring(S.known or 0) .. ' errs=' .. tostring(S.errs or 0) end)() or 'no lap has been run') INTO lap

LOG "the line above is the lap itself: done= waypoints read of the whole list, tiles= point ids looked at, known= how many of them the client actually knew, chests= treasures the map had on it. known=0 with done>0 is the one to worry about — the lap walked over a client nothing was being answered to, and «no chest» there means nothing at all."

READ_LUA (DataCenter.__lw_treasure_auto and DataCenter.__lw_treasure_auto.scan_report or 'no lap has been harvested') INTO queued

LOG "and this one is what was queued: new= chests nobody had heard of, upgraded= chests already queued from the dig feed that have just got their tile, already-queued= ones nothing changed for, foreign= chests of other alliances, which this account cannot take at all."
