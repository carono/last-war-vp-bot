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

set "PORT=%~1"
if "%PORT%"=="" set "PORT=47655"

set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "PY=C:\Python312\python.exe"
if not exist "%PY%" (
    echo [start_instance] %PY% not found - install the Windows Python or edit PY
    exit /b 1
)

set "GAME=%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe"
if not exist "%GAME%" (
    echo [start_instance] no game install for %USERNAME%: "%GAME%"
    echo [start_instance] log in as this account once and install it, then retry
    exit /b 1
)

rem -- the client ------------------------------------------------------------
rem One Windows account holds exactly one client, so "does this user own a
rem LastWar.exe" is the right question - no session arithmetic needed.
tasklist /FI "IMAGENAME eq LastWar.exe" /FI "USERNAME eq %USERNAME%" 2>nul | find /I "LastWar.exe" >nul
if errorlevel 1 (
    echo [start_instance] starting the client for %USERNAME%
    start "" "%GAME%"
) else (
    echo [start_instance] client already running for %USERNAME%
)

echo [start_instance] waiting for LastWar.exe ...
set "FOUND="
for /L %%i in (1,1,120) do (
    if not defined FOUND (
        tasklist /FI "IMAGENAME eq LastWar.exe" /FI "USERNAME eq %USERNAME%" 2>nul | find /I "LastWar.exe" >nul
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
