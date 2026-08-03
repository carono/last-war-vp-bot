# Start the Last War launcher and wait for the home base to be ready.
# ru: Запустить лаунчер Last War и дождаться готовности базы.
#
# START_GAME starts the client WHERE THIS PROFILE'S CLIENT LIVES. On an ordinary box
# that is this desktop, and the path below is used as it reads. A profile farming a
# second account names a Windows session of its own (tools/rdp_instance.py), and then
# the launcher is started inside THAT session instead — under the token that is already
# its interactive logon, which is the only arrangement the game accepts. Spawning a
# process from here would have put a third client on this desktop while the account
# that was asked for stayed down.
#
# The path uses %LOCALAPPDATA% so it resolves correctly under any Windows user — and
# for a session that is not ours it is deliberately not expanded here at all: that
# variable names a different folder for every account, so the other session resolves
# its own install. If the launcher lives somewhere else on this machine (custom drive,
# portable copy), edit the START_GAME line; an absolute path with nothing left to
# expand is the same file for both accounts and is used for either session.
#
# Readiness is checked by STATE, not pixels: `scene == city` asks the game's
# own Lua VM whether it is in the city scene with the main HUD up. It reads
# 'unknown' while the client is still loading (or restarting into a new
# process) and flips to 'city' the moment the base is interactive. Cold
# launches normally finish in 1-2 minutes; WITHIN 300s leaves a safety margin.

START_GAME "%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe"
WAIT scene == city WITHIN 300s
LOG "Game ready at the home base (city scene)."
