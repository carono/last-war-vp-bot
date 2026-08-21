# Stop the firework watcher — «снять караул салютов».
# ru: Снять караул салютов.
#
# The wrapper stays in place (unwrapping one of the client's own functions safely means
# knowing nobody wrapped it after us, and nobody can know that) — what this does is turn
# it into a pass-through: the flag goes off, the press is not attempted, and the counters
# are kept so a reading taken afterwards still says what the session did.
#
# A client restart does the thorough version by itself: the VM goes, and with it the hook.

READ_LUA (function() local B = DataCenter.__lw_fww if not B then return 'was not on' end B.on = false return 'off: pushes=' .. B.pushes .. ' taken=' .. B.taken end)() INTO state
LOG "Fireworks watch: {state}"
