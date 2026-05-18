@echo off
REM Launch the Last War Bot UI. Double-click this file from Explorer
REM or run it from any terminal — paths are resolved relative to this script.

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo .venv not found. See docs\install\03-bot.md to set it up.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python -m lastwar_bot.ui

if errorlevel 1 (
    echo.
    echo Bot exited with an error. Press any key to close.
    pause >nul
)
