# Walk one warzone at the height secret-task tiles still arrive at.
# ru: Обойти одну зону на высоте, на которой ещё приходят тайлы секреток.
#
# The step of the star round (`sweep_star_servers.md`), and it is a file of its own for a
# reason of the language rather than of taste: a `{name}` is filled in when a recipe is
# PARSED, and a sub-recipe is parsed at every `CALL`. So the warzone the caller has just
# taken off its queue reaches `SWEEP_MAP` here, and would reach nothing at all if this
# loop body were written inside the caller — every lap would sweep whatever `STAR_SERVER`
# held when the caller's own file was read, which is zero.
#
# ZOOM 600 IS NOT A PREFERENCE. It is the last height at which the client asks for
# secret-task tiles at all; one notch higher and bases and mines keep arriving while the
# tasks stop, silently (docs/research/map-sweep-zoom.md). And the height is part of every
# jump the lap makes rather than something set before it, which is what «zoom before the
# jump» means in practice — `SWEEP_MAP` hands the game a waypoint list carrying both.
#
# NOTHING IS ROBBED, NOTHING IS PRESSED, no window opens: the camera walks the warzone in
# a couple of seconds and whatever capture is listening decodes what the server sends back.

# Which warzone. Zero is «the caller named none», which is a bug in the caller rather
# than a lap of the warzone the client happens to be looking at — say so and stop.
ARGS STAR_SERVER = 0

IF STAR_SERVER == 0
    FAIL "sweep_one_star_server was called with no warzone — NEXT_STAR_SERVER first"

LOG "star_lap — walking warzone {STAR_SERVER}"
SWEEP_MAP ZOOM 600 STEP 90 SERVER {STAR_SERVER}
