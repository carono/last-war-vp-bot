# Start the Last War launcher and wait for the base screen to appear.
#
# The launcher path below matches a typical install on Windows. If your
# launcher is elsewhere on this machine, edit the LAUNCH line — the
# rest of the script doesn't need to change.
#
# Cold launches normally finish in 1-2 minutes; WITHIN 300s leaves a
# safety margin. The bot polls every ~0.3s for the base screen and
# exits as soon as it appears.

LAUNCH "C:\Users\spame\AppData\Local\FunFly\Last War-Survival Game\LastWarLauncher.exe"
WAIT screen == base WITHIN 300s
LOG "Game ready on the base screen."
