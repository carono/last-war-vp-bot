# Press ESC repeatedly until the bot can identify the current screen
# ru: Закрыть открытые модальные окна.
# again (base or world). Useful as a recovery step before any flow that
# expects to start from a known screen — popups, tutorials, event
# splashes, etc. all dismiss on ESC.
#
# Bounded by LIMIT to avoid infinite loops when ESC has no effect
# (e.g. modal that requires a specific button click instead). Eight
# iterations cover most stacks of nested popups.

WHILE screen == unknown LIMIT 8
    PRESS ESC
    WAIT 0.4
