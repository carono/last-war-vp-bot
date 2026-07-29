# Heal the wounded soldiers in the base hospital ("Лечение юнитов").
#
# The operator's in-game routine is three steps — heal, ask the alliance to speed it up,
# collect the healed soldiers when the timer ends — but only two of them are presses:
# starting a heal registers it for alliance help by itself, so there is nothing to send
# for the middle step (docs/research/hospital-heal.md).
#
# Both lines below are headless Lua sends, not screen taps: no hospital window is opened,
# the wounded list and the heal timer are read straight off the game state.

# --- 1. Collect the healed soldiers first --------------------------------------
# Only fires once the heal timer has finished — while one is still running this is a clean
# no-op, so the recipe can be run on any schedule. It goes FIRST because finished soldiers
# left in the hospital block the next heal.
TAP collect_healed xall

# --- 2. Send every wounded soldier for treatment -------------------------------
# One hospital.cure covers every wounded type at once, so one press is the whole heal.
# `xall` means "only if somebody is actually hurt", so a healthy army costs no round trip.
TAP heal_all xall

# NB — the order matters. The hospital takes ONE job at a time, and soldiers that have
# finished healing still occupy it until they are collected, so a heal sent before the
# collect is refused. That is why the collect comes first here; both presses are proven
# live (681 wounded sent for treatment in one press).
