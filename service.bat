@echo off
REM Run the machine's SERVICE — the door that owns the web port and routes to the
REM panels (`python -m panel.service`). Started by hand it runs in THIS window, which is
REM what it is for: watching it, or trying a port before registering anything.
REM
REM The whole point of it, though, is to be a Windows service that is up before anybody
REM signs in — and that is two files of its own now, not a comment to copy out of here:
REM
REM   service_install.bat      register it, set it to start at boot, and start it now
REM   service_uninstall.bat    stop it and take the registration off
REM
REM Both ask Windows for elevation (`sc create` without it fails with «Отказано в
REM доступе» and nothing else), and both take `--dry-run`, which prints what they would
REM do and changes nothing.
REM
REM The service starts NO panel and watches none — a panel comes up with its own Windows
REM session and dials the service itself.
REM
REM `service.bat --status` says whether one is already answering.
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%LW_PYTHON%"
if not defined PY if defined LW_WIN_PYTHON set "PY=%LW_WIN_PYTHON%"
if not defined PY if defined LW_PY_DIR if exist "%LW_PY_DIR%\python.exe" set "PY=%LW_PY_DIR%\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY set "PY=python"

"%PY%" -m panel.service %*
