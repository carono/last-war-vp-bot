# Radar: the whole cycle, forced into the hoarding mode (#1473).
# ru: Радар: полный цикл, принудительно в режиме накопления.
#
# `radar_full_cycle` picks its mode from the GAME's weekday, which is the right rule and
# the reason the hoarding half cannot be watched on a duel day. `force = 2` is the
# recipe's own override for exactly that, and the web front-end has no way to pass an
# argument — so this wrapper sets the variable and calls the cycle. A run of this on a
# duel day proves the held-rewards branch and nothing else changes.

READ_LUA 2 INTO force
CALL radar_full_cycle
