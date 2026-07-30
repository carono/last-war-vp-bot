# Switch to the World map via the game's own Lua VM (no pixels, no hwnd).
# ru: Перейти на карту мира через Lua (без пикселей).
#
# The vision-based go_to_world.md clicks the on-screen toggle; this one asks the
# engine to change scene directly through the daemon. Use whichever fits — the
# Lua path is immune to UI-layout drift, the vision path needs no daemon.

GAME WORLD
