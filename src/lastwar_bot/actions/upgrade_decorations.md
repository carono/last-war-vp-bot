# Upgrade every base decoration that is ready.
# ru: Повысить украшения на базе, которые уже можно повысить.
#
# In the game this is: tap the building that carries decorations, switch to its
# handbook, pick a decoration whose upgrade is available and press the upgrade
# button. This does the same without opening any of it — it finds the decoration
# itself, so nothing has to be picked or prepared beforehand.
#
# It only presses on a decoration that can really be upgraded: the upgrade step
# has to exist at the decoration's current level, and a spare duplicate of that
# decoration has to be banked to feed into it. One spare copy buys one step of
# progress towards the next star. Spares are rare, so the ordinary outcome is
# that this does nothing and says so — that is not a failure, and pressing
# anyway would be refused by the game.
#
# To see where each decoration stands (the star score it is at, the threshold it
# is climbing to, how many steps its spares would buy), run
# `TAP dump_decorations` — it writes a line per decoration and sends nothing.
# `TAP decorations` opens the decoration window if you want to look.

TAP upgrade_decoration xall

LOG "Decorations: everything that was ready has been upgraded."
