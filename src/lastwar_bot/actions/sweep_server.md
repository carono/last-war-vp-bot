# Walk one NAMED warzone once — the lap a person starts from that warzone's own tile.
# ru: Один проход по УКАЗАННОЙ зоне — обход, который запускают с плитки этой зоны.
#
# THE OTHER HALF OF `scan_map.md`, and the difference is the whole reason this file
# exists. That lap names no warzone on purpose (#2705, #2727): the person stands where
# they want to stand and presses the button, and the recipe reads the warzone off the
# tiles the client is holding. Every cached answer tried before that moved the client to
# somewhere it had not been — the «Сервер» box is a setting nobody updates when they walk,
# and the wire's last word is true only until the camera comes back.
#
# This one is the case that rule never covered: the warzone is CHOSEN, out of the chart of
# four hundred on «Куда идти сегодня», by a person who is looking at a tile and pressing
# it (#2737). There is nothing to read off the client, because the point is to go
# somewhere else — so the number travels as an argument, and naming one IS the jump
# (`SWEEP_MAP SERVER`, docs/dsl.md).
#
# It is not a second lap either: the lap is the primitive, and both recipes hand it the
# same waypoint list. What differs is where the warzone comes from.
#
# NOTHING IS ROBBED AND NOTHING IS PRESSED: the camera walks the warzone in a couple of
# seconds and whatever capture is listening decodes what the server sends back. With the
# monitor off this is a camera walk that fills nothing.

# Which warzone. Zero is «the caller named none», and that is a bug in the caller rather
# than a lap of wherever the camera happens to be — the empty slot is what `scan_map.md`
# is for, and handed to the game's own jump it loads the HOME world (#2727).
ARGS server = 0
# The height and the pace, exactly as `scan_map.md` takes them — the two knobs behind the
# gear on «Обход карты», and nothing else about the lap is the caller's to decide.
ARGS zoom = 600
ARGS step = 90
ARGS every = 0.05

IF server == 0
    FAIL "sweep_server was called with no warzone — name one, or play scan_map for the one the client is on."

# A lap from inside the base fetches no tiles at all and says so nowhere (#1335), so the
# map goes up first — which is where the lap ends anyway.
IF scene != world
    LOG "Putting the map up first — a lap from the base fetches no tiles."
    GAME WORLD
    WAIT scene == world WITHIN 30s

LOG "Walking warzone {server}."
SWEEP_MAP ZOOM {zoom} STEP {step} EVERY {every} SERVER {server}

LOG "One lap of warzone {server} is done."
