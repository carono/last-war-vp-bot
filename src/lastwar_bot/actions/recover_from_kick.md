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
# The path uses %LOCALAPPDATA% so it resolves under any Windows user; edit the
# LAUNCH line if the launcher lives elsewhere. Readiness is checked by STATE, not
# pixels: `scene == city` asks the game's own Lua VM whether the base is up. Cold
# relaunches normally finish in 1-2 minutes; WITHIN 300s leaves a safety margin.

LOG "Session kicked (logged in on another device) — relaunching the client."
LAUNCH "%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe"
WAIT scene == city WITHIN 300s
LOG "Recovered: back at the home base."
