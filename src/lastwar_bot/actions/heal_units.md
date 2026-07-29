# Heal the wounded soldiers in the base hospital ("Лечение юнитов").
#
# The operator's in-game routine is three steps — heal, ask the alliance to speed it up,
# collect the healed soldiers when the timer ends — but only two of them are presses:
# starting a heal registers it for alliance help by itself, so there is nothing to send
# for the middle step (docs/research/hospital-heal.md).
#
# Both lines below are headless Lua sends, not screen taps: no hospital window is opened,
# the wounded list and the heal timer are read straight off the game state.

# --- 1. Send every wounded soldier for treatment -------------------------------
# One hospital.cure covers every wounded type at once, so one press is the whole heal.
# `xall` means "only if somebody is actually hurt", so a healthy army costs no round trip.
TAP heal_all xall

# --- 2. Collect the healed soldiers --------------------------------------------
# Only fires once the heal timer has finished — while one is still running this is a clean
# no-op, so the recipe can be run on any schedule. A heal started by THIS run will not be
# ready yet; the collect belongs to the previous one.
TAP collect_healed xall

# NB — a heal also takes one of the base's building queues. With all of them busy the game
# refuses the heal and says so on screen only, so the run adds a line of its own when it
# sent into a base with no free queue. Nothing here can work around that; it only means the
# next run heals instead. Still not watched through end to end on a live game: every
# attempt so far met a base with all four queues working.
