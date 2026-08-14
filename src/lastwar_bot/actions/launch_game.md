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
# Readiness is checked by STATE, not pixels, and `client == ready` is that state: the
# game's own Lua VM is asked which scene it is in, and when there is no warm daemon to
# ask, the client's own conversation with the game server answers instead. The wait ends
# the moment either says yes — `WITHIN` is a CAP on a client that never comes up, never a
# duration to sit out.
#
# IT USED TO WAIT FOR THE CITY, AND THAT WAS THE FIRST BUG (#1281). A client sitting on
# the WORLD MAP — where the player usually is — answers 'world' for ever, so a launch
# that had already succeeded went on waiting the full five minutes, holding the panel's
# single-file queue the whole time and killing the client again on the next turn. The
# base is not what this recipe is for; the client being up is. Whatever needs the city
# in particular changes scene itself (`GAME CITY`), which costs one call.
#
# AND `scene != unknown` WAS THE SECOND (#1399). The scene can only be read through the
# Lua daemon, and after a relaunch the daemon is the one thing on the machine that is
# down: it was pinned to the process that just died and the panel is rebuilding it.
# Measured live on 2026-08-14 — the client's process was back 8 s after START_GAME and
# its link to the game server 32 s after it, while the daemon stayed down for 170 s. So
# the wait sat out its whole cap and reported a FAILED launch twelve times in one
# evening, over a client the very next scenario read as `scene == city`. A launch may
# not stand on the one reading a launch reliably breaks.
#
# Cold launches normally finish in 1-2 minutes. WITHIN 180s leaves a margin over that
# and is a CAP: past it the run fails and lets the queue go, rather than sitting on it.
# It says WHY it gave up — no client, a client whose sockets say the server hung up, or
# a client that answered and is still loading are three different mornings.

START_GAME
WAIT client == ready WITHIN 180s
LOG "Game ready — the client is up and in play."
