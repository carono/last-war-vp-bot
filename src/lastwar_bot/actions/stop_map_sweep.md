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
# It is a recipe rather than a line of Lua in a tab because a tab may not drive the game
# by hand (`CLAUDE.md`) — and a person pressing «Остановить» while a lap holds the claim
# is exactly the press the human gate exists for.
TAP stop_map_sweep
