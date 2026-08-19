# Ask the world for every monster it holds — uuid, tile, level and kind, with no slow walk.
# ru: Спросить мир обо всех монстрах, которых он держит, — uuid, тайл, уровень и вид, без медленного обхода.
#
# THE OTHER SOURCE, and it answers a different question from the two reads beside it.
#
#   * `read_world_monsters.md` looks at what the client has DRAWN around the camera — as
#     wide as one view, no uuid, and the level only when a tag happens to be readable.
#   * `scan_map_monsters.md` walks the map slowly and samples the drawing at every stop —
#     897 monsters of every kind in 147 seconds, still with no uuid.
#   * **this** asks `WorldScene`'s own register (`SCAN_MONSTERS`), which answers out of
#     what the client has LOADED rather than out of what it is showing. So the walk in
#     front of it can be the CHEAP one, and the answer carries the uuid.
#
# Measured live, and each number decided a line of this file:
#
#   * the register held **36** rows before any walk, **178** after a FAST lap of 8 seconds,
#     and still 178 ten seconds later. The slow monster lap — 147 s — added **nothing** to
#     it, so paying for one in front of this question is paying for nothing.
#   * asked at the camera, at the middle of the map and with a radius of 5 000 it answered
#     the same 28: the radius is not a window, one call is «tell me everything».
#   * a lap at height **1199 emptied it to 0**. That height loads the coarse big-map layer
#     and the client lets the fine one go, so the walk here is at 600 and the question is
#     asked at the bottom of it.
#   * the asking itself is **36 ms** for 178 monsters, every one of them with an exact
#     level: iron 35, bread 31, coin 40, and 72 golden zombies at level 10.
#
# **WHAT IT DOES NOT ANSWER, said plainly:** the plain roaming squads the client draws as
# `WorldMonster*` clones are not in the register at all. This is not «the whole map», it
# is the kinds the register keeps — and for those it is exact, cheap, and carries the one
# field a march cannot go out without.
#
# `lap = 0` skips the walk, for a caller that has just done one for another reason.

ARGS server = 0
ARGS lap = 1
ARGS zoom = 600
ARGS step = 90
ARGS every = 0.05

IF scene != world
    LOG "Putting the map up first — the register is the world's, and it is empty in the base."
    GAME WORLD
    WAIT scene == world WITHIN 30s

# `WHILE … LIMIT 1` is how a DSL with no «if this number» runs a step none, once: the
# recipe has no other way to make the walk optional, and a caller that has just lapped for
# another reason must not be made to lap again for this one.
WHILE lap > 0 LIMIT 1
    SWEEP_MAP ZOOM {zoom} STEP {step} EVERY {every} SERVER {server}

SCAN_MONSTERS INTO monsters
