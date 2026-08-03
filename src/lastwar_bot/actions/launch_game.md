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
# WHERE the launcher is is not written here on purpose. A scenario is the same file on
# everybody's machine, and the install is not: it normally sits under the playing
# account's own %LOCALAPPDATA%, which is a different folder for every account and so
# cannot be spelled out for a session that is not ours. Left unsaid, each side resolves
# its own — and a person whose game is on another drive sets LW_LAUNCHER instead of
# editing this line. (An absolute LW_LAUNCHER has nothing left to expand, so it is one
# file for every account and reaches the other session too.)
#
# Readiness is checked by STATE, not pixels: `scene == city` asks the game's
# own Lua VM whether it is in the city scene with the main HUD up. It reads
# 'unknown' while the client is still loading (or restarting into a new
# process) and flips to 'city' the moment the base is interactive. Cold
# launches normally finish in 1-2 minutes; WITHIN 300s leaves a safety margin.

START_GAME
WAIT scene == city WITHIN 300s
LOG "Game ready at the home base (city scene)."
