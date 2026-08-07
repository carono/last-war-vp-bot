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
# Readiness is checked by STATE, not pixels: the game's own Lua VM is asked which
# scene it is in. It answers 'unknown' while the client is still loading (or
# restarting into a new process) and names a scene the moment the client is
# interactive, so `scene != unknown` is exactly "the person could play now".
#
# IT USED TO WAIT FOR THE CITY, AND THAT WAS THE BUG (#1281). A client sitting on the
# WORLD MAP — where the player usually is — answers 'world' for ever, so a launch that
# had already succeeded went on waiting the full five minutes, holding the panel's
# single-file queue the whole time and killing the client again on the next turn. The
# base is not what this recipe is for; the client being up is. Whatever needs the city
# in particular changes scene itself (`GAME CITY`), which costs one call.
#
# Cold launches normally finish in 1-2 minutes. WITHIN 180s leaves a margin over that
# and is a CAP: past it the run fails and lets the queue go, rather than sitting on it.

START_GAME
WAIT scene != unknown WITHIN 180s
LOG "Game ready — the client is up and in a scene."
