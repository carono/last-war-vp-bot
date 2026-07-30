# Heal the wounded soldiers in the base hospital ("Лечение юнитов").
# ru: Лечение раненых в госпитале базы («Лечение юнитов»).
#
# The operator's in-game routine is three presses — collect what has finished, send the
# wounded in, ask the alliance to speed it up — and all three are real messages
# (docs/research/hospital-heal.md).
#
# All three lines below are headless Lua sends, not screen taps: no hospital window is
# opened, the wounded list and the heal timer are read straight off the game state.

# --- 1. Collect the healed soldiers first --------------------------------------
# Only fires once the heal timer has finished — while one is still running this is a clean
# no-op, so the recipe can be run on any schedule. It goes FIRST because finished soldiers
# left in the hospital block the next heal.
TAP collect_healed xall

# --- 2. Send every wounded soldier for treatment -------------------------------
# One hospital.cure covers every wounded type at once, so one press is the whole heal.
# `xall` means "only if somebody is actually hurt", so a healthy army costs no round trip.
TAP heal_all xall

# --- 3. Ask the alliance to speed it up ----------------------------------------
# The third press of the in-game routine, and it comes last because the heal has to be
# running before there is a queue to ask about. It asks for every working queue, not just
# the hospital, and skips the ones already asked for, so it is safe on any schedule.
TAP call_help xall

# NB — the order matters. The hospital takes ONE job at a time, and soldiers that have
# finished healing still occupy it until they are collected, so a heal sent before the
# collect is refused (errorCode 130069). The help request comes last because it needs a
# queue already working. All three are proven live: 681 wounded sent in one press, a
# finished batch collected back, and allies answering the request within seconds.
