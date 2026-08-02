@echo off
REM Start the warm Lua daemon (tools/lua_daemon.py) on its own, in a window
REM you can watch.
REM
REM The panel does NOT need this: it starts the daemon itself, detached and
REM windowless, the first time a button needs the game. This is for driving
REM the game WITHOUT the panel — the standalone tools under tools/, or a
REM second client living in its own Windows session, which wants its own
REM daemon on its own port:
REM
REM     daemon.bat --port 47655
REM
REM One daemon per client. A second one on a port that is already taken does
REM not fight for it: it fails to bind and says so.
REM
REM UTF-8 first; what it prints is Russian, the comments stay English.
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%LW_PYTHON%"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY set "PY=python"

echo Демон Lua. Окно закрыть — демон остановится. Панель поднимает свой сама.
echo.
"%PY%" tools\lua_daemon.py %*

if errorlevel 1 (
    echo.
    echo Демон завершился с ошибкой. Обычные причины: порт уже занят другим
    echo демоном, или игра не запущена. Проверьте и запустите снова.
    pause >nul
)
