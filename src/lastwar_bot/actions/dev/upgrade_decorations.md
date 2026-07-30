# Upgrade the queued base decorations.
# ru: Повысить украшения на базе (из подготовленного списка).
#
# In the game this is: tap the building that carries decorations, switch to its
# handbook, pick a decoration that can still be upgraded and press the upgrade
# button. The recorded session («Повышение украшений», 20260730_142543) showed
# that walk sending nothing at all — the whole action is one message carrying the
# building and the decoration slot, so this runs with no window opened.
#
# Which decorations to upgrade is parked on the game side first, because a `TAP`
# takes no arguments:
#
#     lua_actions.decoration_queue_set([(build_uuid, slot), ...])
#
# With nothing parked the press logs "empty queue" and does nothing. Reading the
# upgradable decorations out of the client automatically is not written yet — the
# manager holding them is known, its reader API is not (`TAP dump_decorations`
# logs its shape).
#
# Still dev: written from the wire, not yet proven in a live session — the reply
# to the recorded press was accepted (state=1), but this recipe has not fired one
# itself. Verify that the upgraded decoration really levels up in game.

TAP upgrade_decoration xall

LOG "Queued decorations processed."
