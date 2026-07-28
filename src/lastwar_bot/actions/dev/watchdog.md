# Watchdog: runs on every bot tick. Reacts to interrupt conditions that
# must halt the bot regardless of what the main routine is doing.
#
# Currently watching for the "logged in from another device" modal: when
# the user signs in on another device, Last War shows a modal that locks
# the client until acknowledged. Continuing to click around in that state
# is useless and risky, so the bot halts and closes the game.
#
# To activate, capture the modal as `kicked_modal.png` into
# `src/lastwar_bot/game/templates/`, then uncomment the FIND block.

FIND kicked_modal.png
     LOG "Another login detected; closing game and halting bot"
     CLOSE_WINDOW
     STOP "kicked by another login"
