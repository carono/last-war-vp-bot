@echo off
REM Run the machine's SERVICE — the door that owns the web port and routes to the
REM panels (`python -m panel.service`). Started by hand it runs in this window; the
REM whole point of it, though, is to be a Windows service that is up before anybody
REM signs in:
REM
REM   sc create LastWarBot binPath= "\"C:\Python312\pythonw.exe\" -m panel.service" ^
REM      start= auto DisplayName= "Last War panel service"
REM   sc description LastWarBot "The door: the web port and the routing to the panels"
REM   sc start LastWarBot
REM
REM Both `sc` lines need an elevated prompt. The service starts NO panel and watches
REM none - a panel comes up with its own Windows session and dials the service itself.
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
