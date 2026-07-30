# Upgrade every base decoration that is ready.
# ru: Повысить украшения на базе, которые уже можно повысить.
#
# In the game this is: tap the building that carries decorations, switch to its
# handbook, pick a decoration whose upgrade is available and press the upgrade
# button. This does the same without opening any of it — it finds the decoration
# itself, so nothing has to be picked or prepared beforehand.
#
# It only presses on a decoration that can really be upgraded: the upgrade step
# has to exist at the decoration's current level, and the material it costs has
# to be banked. Neither is usually true — the material accumulates over days — so
# the ordinary outcome is that this does nothing and says so. That is not a
# failure: pressing anyway is refused by the game.
#
# To see where each decoration stands (what it costs, what is held, which one is
# ready), run `TAP dump_decorations` — it writes a line per decoration and sends
# nothing. `TAP decorations` opens the decoration window if you want to look.
#
# Still dev: every step is verified against the live game — the search, the
# target it picks, the gate, and the refusal when nothing is ready — but no
# decoration on this account has been upgradable since, so a successful upgrade
# has not been driven end to end yet.

TAP upgrade_decoration xall

LOG "Decorations: everything that was ready has been upgraded."
