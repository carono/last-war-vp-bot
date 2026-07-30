# Start the Last War launcher and wait for the home base to be ready.
# ru: Запустить лаунчер Last War и дождаться готовности базы.
#
# The path uses %LOCALAPPDATA% so it resolves correctly under any
# Windows user. If the launcher is installed elsewhere on this machine
# (custom drive, portable copy), edit the LAUNCH line.
#
# Readiness is checked by STATE, not pixels: `scene == city` asks the game's
# own Lua VM whether it is in the city scene with the main HUD up. It reads
# 'unknown' while the client is still loading (or restarting into a new
# process) and flips to 'city' the moment the base is interactive. Cold
# launches normally finish in 1-2 minutes; WITHIN 300s leaves a safety margin.

LAUNCH "%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe"
WAIT scene == city WITHIN 300s
LOG "Game ready at the home base (city scene)."
