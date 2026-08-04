# Close the Last War client this profile drives.
# ru: Закрыть клиент Last War этого профиля.
#
# The half of `restart_game` that ends things, on its own — because "put the client
# down and leave it down" is a thing a person actually wants: before the machine is
# used for something else, before an update, or when an account is to sit out the rest
# of the evening. Until this file existed the panel could start a client and replace a
# client, and the only way to stop one was the Task Manager.
#
# WHICH client is the whole of the care here, and it is `QUIT_GAME` that takes it: the
# target is the process THIS PROFILE'S daemon is attached to, never "the LastWar.exe"
# by name. With two accounts on one machine there are two clients, one per Windows
# session, and closing by image name would end the other account's session as well —
# an account nobody pressed anything for, mid-farm. That was a real bug in the
# restart button once (#1205), and naming an image is how it happened.
#
# It is a FORCE close, like the one inside `restart_game`, and for the same reason:
# half the reason to end a client is that it has stopped answering, and a window that
# ignores WM_CLOSE would turn this into a long wait for nothing. A client that is
# already gone is not an error — the job is to leave nothing running, and that is
# already true.
#
# Nothing is spent in the game by closing it and nothing is lost: the session comes
# back on the same base whenever `launch_game` is played next.

QUIT_GAME

LOG "Client closed — nothing of this profile's game is running."
