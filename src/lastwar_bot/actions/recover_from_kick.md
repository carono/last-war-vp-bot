# Recover from a session kick — relaunch the client and wait for the base.
# ru: Восстановление после кика — перезапустить клиент и дождаться базы.
#
# A login on another device kicks this session: Last War stays alive but locks
# itself behind a "logged in from another device" modal, so nothing on screen
# moves on its own and no packet announces it. The session-kick trigger detects
# that state headlessly (panel/triggers.py — it reads the disconnect flag through
# the daemon, not pixels) and runs THIS recipe.
#
# Recovery is a relaunch, not a click: the kicked client is logged out and stuck,
# so acknowledging the modal would leave the session dead. Restarting the client
# through the launcher replaces the stuck instance with a fresh login, which is
# what dismisses the modal. This is the headless replacement for the pixel-based
# actions/dev/watchdog.md, which only closed the game and halted the bot.
#
# WHICH launcher, and what "ready" means, are NOT spelled out here any more (#1399).
# They were, and both were wrong in the same way. The path was a literal — right on the
# machine it was written on, and a folder that cannot exist for a profile whose client
# lives in another Windows session. Readiness was `scene == city`, which fails a recovery
# that landed on the world map (#1281) and, worse, cannot be read at all while the Lua
# daemon is being rebuilt around the new process — so a recovery that had WORKED sat out
# its whole 300 s and reported failure.
#
# One source of truth for «start the client and wait until it is up»: launch_game. It
# starts the client where THIS profile's client lives, and its `client == ready` ladder
# asks the game's own scene when there is a daemon to ask and the client's link to the
# game server when there is not.

LOG "Session kicked (logged in on another device) — relaunching the client."
CALL launch_game
LOG "Recovered: the client is back in play."
