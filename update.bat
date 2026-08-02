@echo off
REM Pull the latest sources and refresh the Python dependencies. This is the
REM second Desktop shortcut install.bat makes; run it whenever the panel has
REM fallen behind, or after a task lands upstream.
REM
REM Local edits are never thrown away: the pull is fast-forward only, and it
REM says so and stops if a commit or an uncommitted change is in the way.
REM
REM Refreshing the packages writes into the all-users Python install.bat set
REM up, which needs administrator rights - the Desktop shortcut carries them.
REM Started by hand, right-click it and pick "Run as administrator".
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%LW_PYTHON%"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY set "PY=python"

set "GIT=git"
where git.exe >nul 2>&1 || if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"

echo [1/2] Sources
"%GIT%" pull --ff-only
if errorlevel 1 (
    echo.
    echo     Could not fast-forward. Local commits or edits are in the way -
    echo     commit, stash or discard them, then run this again.
    pause
    exit /b 1
)

echo.
echo [2/2] Python packages
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto failed
if exist "requirements-tools.txt" "%PY%" -m pip install -r requirements-tools.txt
"%PY%" -m pip install -e .
if errorlevel 1 goto failed

echo.
echo Up to date.
pause
exit /b 0

:failed
echo.
echo Installing the dependencies failed. Re-run install.bat - it sets up
echo whatever is missing, including the interpreter itself.
pause
exit /b 1
