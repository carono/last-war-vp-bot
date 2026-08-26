@echo off
REM Run the panel WITHOUT a window (`python -m panel.headless`) - the same panel,
REM minus the drawing: the profiles that were last open, their schedules, their
REM standing orders, the remote control and the link to the machine's service.
REM
REM   headless.bat                     the profiles the panel last had open
REM   headless.bat --profile main      one, by name (repeatable)
REM   headless.bat --no-web            do not bind this machine's web port
REM                                    (the service already answers for every panel)
REM
REM The window (panel.bat) still works and is what the panel opens by default; this
REM is the way it will run once Tk is deleted (#1976, P3). Nothing else changes: the
REM same profiles, the same settings, the same recipes, the same API.
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%LW_PYTHON%"
if not defined PY if defined LW_WIN_PYTHON set "PY=%LW_WIN_PYTHON%"
if not defined PY if defined LW_PY_DIR if exist "%LW_PY_DIR%\python.exe" set "PY=%LW_PY_DIR%\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY set "PY=python"

"%PY%" -m panel.headless %*
