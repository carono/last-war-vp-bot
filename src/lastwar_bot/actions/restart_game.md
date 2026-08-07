# Restart the game client — close it and wait until the base is back.
# ru: Перезапуск клиента — закрыть игру и дождаться базы.
#
# The client is left running for days at a time, and it does not enjoy it: the longer
# a session lasts the more it leaks, the slower the scenes load, and the likelier a
# read is to come back empty from a client that is technically still alive. A restart
# on a clock is the cure, which is what the panel's six-hourly errand plays (the
# «restart_game» timer). Nothing in the game is spent by it and nothing is lost — the
# session comes back on the same base.
#
# It is deliberately a FORCE close and not a polite one. Half the reason to restart is
# a client that has stopped answering, and a window that ignores WM_CLOSE would turn
# the errand into a long wait for nothing. QUIT_GAME ends the client THIS profile
# drives — with two accounts on one machine that is not "the LastWar.exe", it is the
# process this profile's Lua daemon is attached to — and waits for it to be gone.
#
# The last line is the one worth understanding. The link into the game's Lua VM is
# bound to a process id, so a restart leaves every reader pointing at a pid that no
# longer exists. It does repair itself eventually (the first failing call rebuilds
# it), but that repair would land inside whatever errand ran next and could be read
# as that errand failing. ATTACH_GAME does the handover here instead, and gives this
# recipe something to fail on when the client never comes back.
#
# Nothing else can be pressing while this runs: the panel plays one errand at a time
# and holds the game for the whole of it, so an action already in flight finishes
# first and the restart waits its turn rather than cutting it off.

QUIT_GAME

# A breath for the process to release its window and its files before the launcher
# looks at them — starting one over a client that is still exiting can end with no
# client at all.
WAIT 3

# One source of truth for "start the game": the launcher, then the base itself
# reporting that it is interactive.
CALL launch_game

ATTACH_GAME WITHIN 120s

# Done means BOTH halves, and this is the second one. The base was last seen through
# the link the launch happened to be holding; the client restarts itself once after
# the first login, so the reading that counts is the one taken through the link that
# is attached NOW. A scenario that ends here having read anything else would report a
# working session while the panel talks to a process that is on its way out.
# «In play» means the client answers with a SCENE, not that the scene is the base: a
# session that came back on the world map is a session that came back (#1281). Asking
# for the city here failed a restart that had worked, purely because of where the
# player happened to be standing.
IF scene == unknown
    FAIL "the client is up and the game link answers, but nothing is in play"

LOG "Client restarted — the session is back in play."
