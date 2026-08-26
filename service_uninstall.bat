@echo off
REM Take the panel's SERVICE off this machine (#1976, P0) — the other half of
REM service_install.bat.
REM
REM   service_uninstall.bat            stop it if it runs, then delete the registration
REM   service_uninstall.bat --dry-run  print what would be done and change nothing
REM
REM Deletes the REGISTRATION and nothing else: `service.json` (the port, the token, the
REM certificate) is left where it is, so re-installing later comes back to the same door.
REM
REM Needs an ELEVATED prompt, exactly as the installer does; started without one it asks
REM Windows for elevation. Set LW_SERVICE_NO_ELEVATE=1 to be told instead of asked.
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "RC=0"
if not defined LW_SERVICE_NAME set "LW_SERVICE_NAME=LastWarBot"
set "NAME=%LW_SERVICE_NAME%"

if /i "%~1"=="--dry-run" (
  echo sc stop %NAME%
  echo sc delete %NAME%
  set "RC=0" & goto :done
)

net session >nul 2>&1
if errorlevel 1 (
  if "%LW_SERVICE_NO_ELEVATE%"=="1" (
    echo [service] нужен запуск ОТ АДМИНИСТРАТОРА: sc delete без прав отказывает.
    echo [service] правый клик по service_uninstall.bat -^> «Запуск от имени администратора».
    set "RC=2" & goto :done
  )
  echo [service] прошу повышение прав…
  REM `cmd /k` and not the file itself: the elevated window has to STAY OPEN, or
  REM everything this says — the state, the log path, a refusal — flashes past and
  REM the person is left with «ничего не произошло».
  set "SELF=%~f0"
  powershell -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', ([char]34 + $env:SELF + [char]34)) -Verb RunAs" >nul 2>&1
  if errorlevel 1 (
    echo [service] повышение не получено. Запусти этот файл от имени администратора.
    set "RC=2" & goto :done
  )
  set "RC=0" & goto :done
)

sc query %NAME% >nul 2>&1
if errorlevel 1 (
  echo [service] службы %NAME% на этой машине нет — удалять нечего.
  set "RC=3" & goto :done
)

REM Уже остановленная служба — это не ошибка: sc stop скажет своё и мы идём дальше.
sc stop %NAME% >nul 2>&1
REM Дать диспетчеру мгновение на остановку, иначе delete пометит службу «к удалению»
REM и она уйдёт только после перезагрузки.
ping -n 3 127.0.0.1 >nul
sc delete %NAME% >nul
if errorlevel 1 (
  echo [service] sc delete не отработал. Служба НЕ удалена.
  sc query %NAME% | findstr /i "STATE"
  set "RC=1" & goto :done
)
echo [service] %NAME% удалена. service.json оставлен на месте — порт и токен переживут переустановку.
set "RC=0" & goto :done

:done
REM ONE WAY OUT. `exit /b` from inside a parenthesised block does not reliably
REM survive `setlocal`, and a batch that says «нужен администратор» and answers 0 is a
REM batch whose caller cannot tell it refused. `%RC%` is expanded before `endlocal`
REM runs, which is the documented way to carry a value out of a local scope.
endlocal & exit /b %RC%
