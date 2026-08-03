@echo off
REM Open the control panel: `python -m panel`. This is what the Desktop
REM shortcut made by install.bat points at, so the console window it needs
REM stays minimised and is there to read if the panel refuses to start.
REM
REM Any argument is passed straight through - `panel.bat --profile second`
REM opens the panel on another profile.
REM
REM UTF-8 first, and this file is saved UTF-8 without a BOM: what it prints
REM is read by a player, so it is Russian (the comments stay English).
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

REM LW_PYTHON overrides everything, then LW_WIN_PYTHON (the name the rest of the
REM repo uses) and LW_PY_DIR (where install.bat was told to put it); then the
REM place install.bat puts it by default, then a repo-local venv, then PATH.
set "PY=%LW_PYTHON%"
if not defined PY if defined LW_WIN_PYTHON set "PY=%LW_WIN_PYTHON%"
if not defined PY if defined LW_PY_DIR if exist "%LW_PY_DIR%\python.exe" set "PY=%LW_PY_DIR%\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY set "PY=python"

"%PY%" -m panel %*

if errorlevel 1 (
    echo.
    echo Панель завершилась с ошибкой. Если окно так и не открылось —
    echo запустите install.bat: он чинит недоустановленное окружение.
    pause >nul
)
