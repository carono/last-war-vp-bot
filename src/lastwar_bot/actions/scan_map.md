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

# WHICH SERVER the lap walks. 0 — the default — means «ask the client», which is what
# every lap did before and what is right when nobody knows better. A caller that DOES
# know says so: the client's own answer is a cached manager field, and live it kept
# sending the camera back to the server before last (#1280).
ARGS server = 0
ARGS zoom = 600
ARGS step = 90
ARGS every = 0.05

IF scene != world
    LOG "Putting the map up first — a lap from the base fetches no tiles."
    GAME WORLD
    WAIT scene == world WITHIN 30s

SWEEP_MAP ZOOM {zoom} STEP {step} EVERY {every} SERVER {server}

LOG "One lap of the map is done."
