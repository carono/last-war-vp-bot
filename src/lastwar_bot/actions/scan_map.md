# Walk the camera over the whole world map once, so the scan sees every tile.
# ru: Один проход камеры по всей карте мира, чтобы скан увидел все тайлы.
#
# The client only sends map data while the map is MOVING, so a passive scan is only ever
# as good as whatever moves the camera. This is that: one lap of the entire server,
# scheduled inside the game and walked in a few seconds.
#
# `zoom` decides what the lap is FOR, and there are only two heights worth passing:
#
#   600   the last height at which secret-task and ghost-recon tiles still arrive
#   1199  four times the ground per jump, and the last height at which anything arrives
#         at all — bases, mines, alliance cities and strongholds, but no tasks
#
# Above 1199 the client switches to its coarse big-map layer and answers a map request
# with no tiles whatever, so a lap up there collects nothing (docs/research/map-sweep-zoom.md).
#
# Nothing is pressed and no window opens: the camera walks and the answers land in
# whatever capture is already listening. Run it with the panel's monitor on, or it is a
# lap nobody is reading.
#
# **A LAP FROM THE BASE COLLECTS NOTHING, and it says so nowhere** (#1335). The camera
# this walks is the WORLD's; in the city scene the jumps are scheduled, the run reports
# «One lap of the map is done», and the client sends not one `world.get.block` — measured
# live over four laps in a row: `0 map response(s), 0 tile(s)` on every one, while the
# same lap an hour earlier, from the world, brought 246 responses and 51 452 tiles. A
# recipe that succeeds loudly and does nothing is worse than one that fails, so the scene
# is now part of the lap rather than a precondition nobody was told about.
#
# It is switched rather than refused because a lap ENDS on the world anyway — the camera
# is thrown across the whole server by the time it is done — so «put the map up first» is
# what the run was always going to do, only earlier and on purpose.

# THE LAP TAKES NO WARZONE FROM ANYBODY, AND THAT IS THE ABILITY (#2705). It walks the
# one the client is already looking at — the person stands where they want to stand and
# presses the button, in their own words: «мы сами в игре встаем на нужный сервер и
# делаем обход». There is no `server` argument to get wrong and no home warzone out of a
# settings file. A lap of a NAMED warzone is a different ability with a different price
# (`sweep_star_servers.md`, which jumps five to ten times on purpose).
#
# WHICH IS NOT THE SAME AS NAMING NOTHING (#2727). Handed an empty warzone slot the
# game's own jump loads the HOME world, so a lap that named nothing pulled the camera off
# the warzone the person was standing on — and said «the warzone the client is on» in the
# log while doing it.
#
# So the lap NAMES one, and it reads it itself, at the moment it starts: the warzone whose
# tiles the client is holding around the camera
# (`tools/lib/lua_actions.py::viewed_server_expr`). Not an argument, not a setting, not
# the panel's memory of anything. The two cached answers that were tried first both moved
# the client: the «Сервер» box is a setting nobody updates when they walk, and the wire's
# last word is true only until the camera comes back — measured on 2026-09-10, the header
# said 1011 while every loaded tile said 8128, and the press went to 1011. The client's
# own `curServerId` cannot answer either: on a foreign warzone it still names home.
#
# The log line names the number it walked, so a wrong one is visible.
ARGS zoom = 600
ARGS step = 90
ARGS every = 0.05

IF scene != world
    LOG "Putting the map up first — a lap from the base fetches no tiles."
    GAME WORLD
    WAIT scene == world WITHIN 30s

SWEEP_MAP ZOOM {zoom} STEP {step} EVERY {every}

LOG "One lap of the map is done."
