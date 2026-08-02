@echo off
REM Open the control panel: `python -m panel`. This is what the Desktop
REM shortcut made by install.bat points at, so the console window it needs
REM stays minimised and is there to read if the panel refuses to start.
REM
REM Any argument is passed straight through - `panel.bat --profile second`
REM opens the panel on another profile.
setlocal EnableExtensions
cd /d "%~dp0"

REM LW_PYTHON overrides everything; otherwise the interpreter install.bat
REM set up, then a repo-local venv, then whatever is on PATH.
set "PY=%LW_PYTHON%"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY set "PY=python"

"%PY%" -m panel %*

if errorlevel 1 (
    echo.
    echo The panel exited with an error. If it never opened, re-run
    echo install.bat - it repairs a half-installed set of dependencies.
    pause >nul
)
