# Stop the map lap that is walking right now.
# ru: Остановить идущий обход карты.
#
# A lap (`scan_map.md`, `scan_map_monsters.md`, the star round) hands its WHOLE waypoint
# list to the game's own timer in one call, so there is nothing to cancel and no handle
# to cancel it with. The interruption is the run token: this bumps it, and every waypoint
# still pending compares the token before moving the camera and returns when it does not
# match. The camera stops wherever it had got to; nothing is pressed, nothing is sent and
# no window opens.
#
# WHAT IT IS NOT, AND THIS IS THE WHOLE OF #2739: it is not how a lap ALREADY WALKING is
# stopped. A lap sits out its own span holding the game claim, so this recipe — played as
# a press, at the same rank — outranks nobody and is answered «занято»: the token stays
# where it was, the game's timer walks the rest of the list, and the person watching the
# camera move is told the lap was stopped. The press that ends a lap of OURS ends the RUN
# (`panel/runtime/interrupt.py`), and the interpreter bumps the token on its way out with
# the claim it is already holding (`script_engine.Interpreter._sweep_wait`).
#
# THIS IS FOR THE LAP NOBODY OWNS: waypoints left walking by a panel that has since
# restarted, or a measurement (`benchmark_map_sweep.md`) whose jumps ride the same token.
# Nothing holds the claim then, so the press goes straight through.
#
# It is a recipe rather than a line of Lua in a tab because a tab may not drive the game
# by hand (`CLAUDE.md`) — and a person pressing «Остановить» while a lap holds the claim
# is exactly the press the human gate exists for.
TAP stop_map_sweep
