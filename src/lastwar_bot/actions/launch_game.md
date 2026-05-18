# Start the Last War launcher and wait for the base screen to appear.
#
# The path uses %LOCALAPPDATA% so it resolves correctly under any
# Windows user. If the launcher is installed elsewhere on this machine
# (custom drive, portable copy), edit the LAUNCH line.
#
# Cold launches normally finish in 1-2 minutes; WITHIN 300s leaves a
# safety margin. The bot polls every ~0.3s for the base screen and
# exits as soon as it appears.

LAUNCH "%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe"
WAIT screen == base WITHIN 300s
LOG "Game ready on the base screen."
