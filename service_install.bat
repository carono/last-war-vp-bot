@echo off
REM Register the panel's SERVICE with Windows and start it (#1976, P0).
REM
REM   service_install.bat              register, set to start at boot, and start now
REM   service_install.bat --dry-run    print the `sc create` line and change nothing
REM
REM What it registers is `tools\run_service.py` under THIS repository, run by a
REM windowless interpreter - the service has no console. Nothing about this machine is
REM written down anywhere: the repository comes from where this file sits (%~dp0) and
REM the interpreter from the same chain every other .bat here uses (LW_SERVICE_PYTHONW,
REM then LW_PYTHON / LW_WIN_PYTHON / LW_PY_DIR, then the ordinary install, then PATH).
REM
REM Needs an ELEVATED prompt: `sc create` without one fails with «Отказано в доступе»
REM and nothing else. Started without, this asks Windows for elevation and comes back.
REM Set LW_SERVICE_NO_ELEVATE=1 to be told instead of asked.
REM
REM Removing it again: service_uninstall.bat
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "RC=0"
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
if not defined LW_SERVICE_NAME set "LW_SERVICE_NAME=LastWarBot"
set "NAME=%LW_SERVICE_NAME%"

set "DRYRUN="
if /i "%~1"=="--dry-run" set "DRYRUN=1"

REM -- the interpreter, asked for rather than assumed --------------------------
REM The same chain as service.bat and panel.bat, with one difference: a service has no
REM console, so what is registered is the WINDOWLESS twin. Whatever the chain answers
REM with, `python.exe` becomes `pythonw.exe` by name — no subprocess, and nothing here
REM has to know where anybody's Python lives.
set "PYW=%LW_SERVICE_PYTHONW%"
if not defined PYW (
  set "PY=%LW_PYTHON%"
  if not defined PY if defined LW_WIN_PYTHON set "PY=%LW_WIN_PYTHON%"
  if not defined PY if defined LW_PY_DIR if exist "%LW_PY_DIR%\python.exe" set "PY=%LW_PY_DIR%\python.exe"
  if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
  if not defined PY set "PY=python.exe"
  set "PYW=!PY:python.exe=pythonw.exe!"
)
if not defined PYW (
  echo [service] не нашёл интерпретатор. Укажи его: set LW_SERVICE_PYTHONW=C:\Path\pythonw.exe
  set "RC=1" & goto :done
)
if /i not "!PYW!"=="pythonw.exe" if not exist "!PYW!" (
  echo [service] нет такого интерпретатора: !PYW!
  echo [service] укажи его: set LW_SERVICE_PYTHONW=C:\Path\pythonw.exe
  set "RC=1" & goto :done
)
if not exist "%REPO%\tools\run_service.py" (
  echo [service] это не корень репозитория: %REPO%
  set "RC=1" & goto :done
)

set "BINPATH=\"!PYW!\" \"%REPO%\tools\run_service.py\""

if defined DRYRUN (
  echo sc create %NAME% binPath= "!BINPATH!" start= auto DisplayName= "Last War panel service"
  echo sc start %NAME%
  set "RC=0" & goto :done
)

REM -- elevation ---------------------------------------------------------------
net session >nul 2>&1
if errorlevel 1 (
  if "%LW_SERVICE_NO_ELEVATE%"=="1" (
    echo [service] нужен запуск ОТ АДМИНИСТРАТОРА: sc create без прав отказывает.
    echo [service] правый клик по service_install.bat -^> «Запуск от имени администратора».
    set "RC=2" & goto :done
  )
  echo [service] прошу повышение прав…
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul 2>&1
  if errorlevel 1 (
    echo [service] повышение не получено. Запусти этот файл от имени администратора.
    set "RC=2" & goto :done
  )
  set "RC=0" & goto :done
)

REM -- already there? ----------------------------------------------------------
sc query %NAME% >nul 2>&1
if not errorlevel 1 (
  echo [service] служба %NAME% уже зарегистрирована.
  echo [service] запустить:  sc start %NAME%
  echo [service] удалить:    service_uninstall.bat
  sc query %NAME% | findstr /i "STATE"
  set "RC=3" & goto :done
)

REM -- register ----------------------------------------------------------------
sc create %NAME% binPath= "!BINPATH!" start= auto DisplayName= "Last War panel service" >nul
if errorlevel 1 (
  echo [service] sc create не отработал. Служба НЕ зарегистрирована.
  set "RC=1" & goto :done
)
sc description %NAME% "Дверь панели: веб-порт и маршрутизация к панелям. Игру не трогает и ничего не перезапускает." >nul
sc start %NAME% >nul
if errorlevel 1 (
  echo [service] служба зарегистрирована, но не стартовала.
  echo [service] частая причина: репозиторий лежит на подключённом или подставленном
  echo [service] диске — служба идёт под LocalSystem и такого диска не видит.
  echo [service] путь сейчас: %REPO%
  sc query %NAME% | findstr /i "STATE"
  set "RC=1" & goto :done
)
echo [service] %NAME% зарегистрирована и запущена. Автозапуск при загрузке — включён.
echo [service] порт и токен: service.json в корне репозитория.
sc query %NAME% | findstr /i "STATE"
set "RC=0" & goto :done

:done
REM ONE WAY OUT. `exit /b` from inside a parenthesised block does not reliably
REM survive `setlocal`, and a batch that says «нужен администратор» and answers 0 is a
REM batch whose caller cannot tell it refused. `%RC%` is expanded before `endlocal`
REM runs, which is the documented way to carry a value out of a local scope.
endlocal & exit /b %RC%
