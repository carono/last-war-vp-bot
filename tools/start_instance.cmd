@echo off
setlocal enabledelayedexpansion
rem ---------------------------------------------------------------------------
rem  Bring one game instance up FROM INSIDE its own Windows session.
rem
rem  The automated route is tools\rdp_instance.py --bring-up, which does all of
rem  this from the main session without anyone logging in. This script is the
rem  manual equivalent: log in as the second account (RDP or fast user
rem  switching), run it once, then disconnect the session — the client and its
rem  Lua daemon keep running, and the main session drives them over TCP:
rem
rem      LW_DAEMON_PORT=47655 C:\Python312\python.exe tools\dispatch_tasks.py
rem
rem  Usage (from anywhere; the repo is found relative to this file):
rem      tools\start_instance.cmd            rem  port 47655
rem      tools\start_instance.cmd 47656      rem  another port
rem
rem  Both steps are guarded, so running it twice is harmless: the client is
rem  started only if this account has none, the daemon only if the port is free.
rem  See docs\research\multi-instance-rdp.md.
rem ---------------------------------------------------------------------------

rem Nothing below is written down twice: the port, the interpreter and the game
rem all take an environment variable first, matching tools\lib\game_paths.py and
rem tools\rdp_instance.py. An ordinary machine sets none of them.
set "PORT=%~1"
if "%PORT%"=="" set "PORT=%LW_SECOND_DAEMON_PORT%"
if "%PORT%"=="" set "PORT=47655"

set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "PY=%LW_WIN_PYTHON%"
if not defined PY if defined LW_PY_DIR set "PY=%LW_PY_DIR%\python.exe"
if not defined PY set "PY=C:\Python312\python.exe"
if not exist "%PY%" (
    echo [start_instance] %PY% not found - install the Windows Python,
    echo [start_instance] or point LW_WIN_PYTHON at it
    exit /b 1
)

set "GAME=%LW_LAUNCHER%"
if not defined LW_LAUNCHER_EXE set "LW_LAUNCHER_EXE=LastWarLauncher.exe"
if not defined LW_GAME_EXE set "LW_GAME_EXE=LastWar.exe"
if not defined GAME if defined LW_GAME_DIR set "GAME=%LW_GAME_DIR%\%LW_LAUNCHER_EXE%"
if not defined GAME set "GAME=%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe"
if not exist "%GAME%" (
    echo [start_instance] no game install for %USERNAME%: "%GAME%"
    echo [start_instance] log in as this account once and install it, then retry
    exit /b 1
)

rem -- the client ------------------------------------------------------------
rem One Windows account holds exactly one client, so "does this user own a
rem client" is the right question - no session arithmetic needed.
tasklist /FI "IMAGENAME eq %LW_GAME_EXE%" /FI "USERNAME eq %USERNAME%" 2>nul | find /I "%LW_GAME_EXE%" >nul
if errorlevel 1 (
    echo [start_instance] starting the client for %USERNAME%
    start "" "%GAME%"
) else (
    echo [start_instance] client already running for %USERNAME%
)

echo [start_instance] waiting for %LW_GAME_EXE% ...
set "FOUND="
for /L %%i in (1,1,120) do (
    if not defined FOUND (
        tasklist /FI "IMAGENAME eq %LW_GAME_EXE%" /FI "USERNAME eq %USERNAME%" 2>nul | find /I "%LW_GAME_EXE%" >nul
        if not errorlevel 1 set "FOUND=1"
        if not defined FOUND ping -n 3 127.0.0.1 >nul
    )
)
if not defined FOUND (
    echo [start_instance] the client did not appear - the launcher may still be updating
    exit /b 1
)

rem -- the daemon ------------------------------------------------------------
rem Give the client a moment to finish loading. A daemon that starts too early
rem is not fatal: it stays up cold and warms on the first `reload`.
ping -n 31 127.0.0.1 >nul

"%PY%" -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',%PORT%))==0 else 1)"
if not errorlevel 1 (
    echo [start_instance] a daemon already answers on :%PORT% - nothing to do
    exit /b 0
)

if not exist "%REPO%\results\logs" mkdir "%REPO%\results\logs"
echo [start_instance] starting the Lua daemon on :%PORT%
cd /d "%REPO%"
start "lua_daemon :%PORT%" /min cmd /c ""%PY%" tools\lua_daemon.py --port %PORT% >> "%REPO%\results\logs\lua_daemon_%PORT%.log" 2>&1"

ping -n 16 127.0.0.1 >nul
"%PY%" -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',%PORT%))==0 else 1)"
if errorlevel 1 (
    echo [start_instance] the daemon is not answering on :%PORT% - see results\logs\lua_daemon_%PORT%.log
    exit /b 1
)
echo [start_instance] instance up: client for %USERNAME%, daemon on :%PORT%
echo [start_instance] you can disconnect this session now - do NOT log off
exit /b 0
