@echo off
REM ======================================================================
REM  Last War Bot - Windows installer.
REM
REM  The archive is unpacked wherever the person likes and this file is run
REM  from inside the folder that came out of it. That folder IS the install:
REM  nothing is cloned, copied or downloaded into a directory of its own,
REM  and every path below is relative to this file. What the installer does
REM  is put the surroundings in place - Python 3.12, Git, the Python
REM  dependencies - and drop shortcuts to the panel in THIS folder onto the
REM  Desktop.
REM
REM  An archive has no git history, so the panel's «Обновить» button and
REM  update.bat would have nothing to pull. Rather than leave updating broken,
REM  the installer offers to ATTACH the folder to the repository - init,
REM  remote, fetch, track - which turns it into a checkout without moving a
REM  single file out of it. Say no and everything works except updating, which
REM  then means unpacking a newer archive over the folder.
REM
REM  Re-running it is safe: whatever is already installed is detected and
REM  kept, and the dependencies are refreshed. That makes it the repair tool
REM  as well - and the thing to run after moving the folder, because the
REM  shortcuts and the editable package install both point at the old place
REM  until it runs again.
REM
REM  Every default it works by can be overridden - "install.bat --help"
REM  prints the options (:usage below is the one copy of that list).
REM
REM  Python lands in C:\Python312 on purpose: that is what the panel's
REM  Settings -> General -> Python defaults to, so the sniffers and the
REM  other child processes it spawns find their interpreter unconfigured.
REM
REM  The person reading this window is a player, so everything it says is
REM  Russian - which is why the console is switched to UTF-8 first and this
REM  file is saved UTF-8 without a BOM. Comments stay English, as the rest
REM  of the repository does. Verified live: the codepage switch leaves the
REM  `for /f` probes below (reg, where, certutil, py) parsing correctly.
REM ======================================================================
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
title Last War Bot — установка

set "LW_SELF=%~f0"
set "LW_DIR=%~dp0"
if "%LW_DIR:~-1%"=="\" set "LW_DIR=%LW_DIR:~0,-1%"

REM --------------------------------------------- is this the bot's folder
REM Checked here, with delayed expansion still off, so that a "!" in the
REM path is still visible rather than eaten by the expansion.
if not exist "%LW_DIR%\panel\__main__.py" goto not_a_tree
if not exist "%LW_DIR%\requirements.txt"  goto not_a_tree
if not exist "%LW_DIR%\pyproject.toml"    goto not_a_tree

REM Double-clicking install.bat inside Explorer's zip preview runs it out of
REM a throwaway copy under %TEMP%: everything would appear to work and then
REM be deleted. Both spellings are looked for - a redirected TEMP still gets
REM the "Temp1_" folder name.
set "LW_PROBE=%LW_DIR:\AppData\Local\Temp\=%"
if not "%LW_PROBE%"=="%LW_DIR%" goto in_temp
set "LW_PROBE=%LW_DIR:Temp1_=%"
if not "%LW_PROBE%"=="%LW_DIR%" goto in_temp

REM A "!" or a "%" in the path survives neither this script's delayed
REM expansion nor the batch files the shortcuts point at. The path is echoed
REM quoted, here and in the refusals below: an "&" in a folder name would
REM otherwise end the echo and run the rest of the name as a command.
echo "%LW_DIR%"| findstr /c:"!" /c:"%%" >nul
if not errorlevel 1 goto bad_path

setlocal EnableDelayedExpansion

set "LW_TMP=%TEMP%\lw-install"

REM ---- pinned prerequisites (checksums taken from the vendors' own files)
set "PY_VERSION=3.12.10"
set "PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
set "PY_SHA256=67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
set "GIT_VERSION=2.55.0.3"
set "GIT_URL=https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/Git-2.55.0.3-64-bit.exe"
set "GIT_SHA256=af12577d0fdff74243a5988197aa49b957d5044edc17004f6ddf0768996f1dca"
REM npcap's free edition has no unattended installer, so it is offered
REM rather than installed - its own window opens and the person clicks it.
set "NPCAP_URL=https://npcap.com/dist/npcap-1.88.exe"

set "STEP=0"
set "WARNINGS=0"

REM ---------------------------------------------------------------- args
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--pydir"        ( set "LW_PY_DIR=%~2"   & shift & shift & goto parse_args )
if /i "%~1"=="--desktop"      ( set "LW_DESKTOP=%~2"  & shift & shift & goto parse_args )
if /i "%~1"=="--user"         ( set "LW_USER=%~2"     & shift & shift & goto parse_args )
if /i "%~1"=="--repo"         ( set "LW_REPO_URL=%~2" & shift & shift & goto parse_args )
if /i "%~1"=="--branch"       ( set "LW_BRANCH=%~2"   & shift & shift & goto parse_args )
if /i "%~1"=="--profile"      ( set "LW_PROFILES=!LW_PROFILES! %~2" & shift & shift & goto parse_args )
if /i "%~1"=="--no-attach"    ( set "LW_NO_ATTACH=1"    & shift & goto parse_args )
if /i "%~1"=="--no-npcap"     ( set "LW_SKIP_NPCAP=1"   & shift & goto parse_args )
if /i "%~1"=="--no-shortcuts" ( set "LW_NO_SHORTCUTS=1" & shift & goto parse_args )
if /i "%~1"=="--yes"          ( set "LW_ASSUME_YES=1"   & shift & goto parse_args )
if /i "%~1"=="--elevated"     ( set "LW_ELEVATED=1"     & shift & goto parse_args )
if /i "%~1"=="--help"         goto usage
if /i "%~1"=="/?"             goto usage
echo Неизвестный ключ: %~1
echo Список ключей: install.bat --help
exit /b 2

:usage
echo.
echo   Установщик Last War Bot — ставит Python 3.12, Git, зависимости и
echo   ярлыки на рабочем столе для той папки, из которой запущен. Запускать
echo   повторно можно.
echo.
echo   install.bat [ключи]
echo.
echo     --pydir ПУТЬ        куда ставить Python 3.12 [по умолчанию C:\Python312]
echo     --profile ИМЯ       ещё один ярлык: панель на этом профиле.
echo                         Ключ можно повторять — по ярлыку на аккаунт
echo     --no-attach         не подключать папку к репозиторию: обновляться
echo                         тогда можно только новым архивом
echo     --repo URL          к какому репозиторию подключать
echo     --branch ИМЯ        какую ветку отслеживать [по умолчанию master]
echo     --no-npcap          не предлагать установку npcap
echo     --no-shortcuts      не трогать рабочий стол
echo     --yes               ничего не спрашивать
echo     --help              показать это и выйти
echo.
echo   Ключа «куда поставить бот» нет: он уже стоит — это папка, в которой
echo   лежит install.bat. Чтобы перенести, перенесите папку и запустите
echo   install.bat ещё раз.
echo.
exit /b 0

:args_done
if not defined LW_PY_DIR   set "LW_PY_DIR=C:\Python312"
if not defined LW_REPO_URL set "LW_REPO_URL=https://github.com/carono/last-war-vp-bot.git"
if not defined LW_BRANCH   set "LW_BRANCH=master"
if not defined LW_DESKTOP call :resolve_desktop
REM Who is being installed for. Kept across the elevation: from here on an
REM administrator writes inside a folder that belongs to somebody else, and
REM what it creates there has to stay writable by them.
if not defined LW_USER set "LW_USER=%USERDOMAIN%\%USERNAME%"

echo.
echo   Last War Bot — установка
echo   ------------------------
echo   папка бота   : "%LW_DIR%"
echo   Python       : %LW_PY_DIR%  [%PY_VERSION%]
echo   обновления   : %LW_REPO_URL%  [ветка %LW_BRANCH%]
echo   рабочий стол : %LW_DESKTOP%
echo.

REM A share is not a home: panel.bat, update.bat and daemon.bat all "cd"
REM into their own folder, which a UNC path refuses.
if "%LW_DIR:~0,2%"=="\\" call :warn "папка лежит в сетевом пути — панель оттуда не запустится, распакуйте архив на локальный диск"

REM ----------------------------------------------------------- elevation
REM Installing Python and Git for all users needs administrator rights, and
REM so does pip writing into the interpreter's site-packages. The Desktop is
REM resolved BEFORE elevating and handed over, so the shortcuts land on the
REM desktop of whoever started this even if another account answers the UAC
REM prompt.
call :is_admin
if errorlevel 1 (
    if defined LW_ELEVATED (
        echo   [ошибка] Права администратора так и не получены. Нажмите на
        echo            install.bat правой кнопкой и выберите «Запуск от имени
        echo            администратора».
        goto abort
    )
    call :step "Запрашиваю права администратора"
    echo     Они нужны: Python и Git ставятся для всех пользователей, и туда же
    echo     пишет pip. Сейчас Windows покажет своё окно с вопросом.
    call :relaunch_elevated
    exit /b !ERRORLEVEL!
)

if not exist "%LW_TMP%" mkdir "%LW_TMP%" >nul 2>&1

REM The folder is the person's, but everything below this line runs as an
REM administrator inside it - pip's egg-info, the .git the attach step makes.
REM Granted on the folder and inheritable, so those arrive already writable by
REM the person who will run the panel; the files already there are theirs and
REM are left alone, which is also why this does not walk the tree (/T) and cost
REM a minute on a folder full of captures.
icacls "%LW_DIR%" /grant "%LW_USER%:(OI)(CI)M" /Q >nul 2>&1
if errorlevel 1 call :warn "не удалось выдать %LW_USER% права на запись в папку — панель может не сохранить профиль"

call :step "Python %PY_VERSION%"
call :ensure_python
if errorlevel 1 goto abort

call :step "Git"
call :ensure_git

call :step "Обновления"
call :attach_repo

call :step "Пакеты Python"
call :install_requirements
if errorlevel 1 goto abort

call :step "npcap — драйвер захвата трафика"
call :offer_npcap

call :step "Ярлыки на рабочем столе"
call :make_shortcuts

echo.
echo   Готово.
echo     панель      : "%LW_DIR%\panel.bat"    [ярлык «Last War — панель»]
echo     обновление  : "%LW_DIR%\update.bat"   [ярлык «Last War — обновление»]
echo     Python      : !PY!
if exist "%LW_DIR%\.git" (
    echo     обновляется : кнопкой «Обновить» в панели, на «Главной»
) else (
    echo     обновляется : только новым архивом, распакованным поверх папки
)
if not "!WARNINGS!"=="0" echo     Выше есть предупреждения, штук !WARNINGS! — прочитайте их до первого запуска.
echo.
echo   Бот живёт в этой папке и больше нигде: сюда же пишутся профили, логи
echo   и все записи трафика. Переносить можно — перенесите папку целиком и
echo   запустите install.bat ещё раз, тогда ярлыки и пакеты найдут её на
echo   новом месте.
echo.
echo   Панель открывается на сводке. Где стоит клиент игры — на её странице
echo   настроек, раздел «Игра»; интерпретатор выше уже такой, какой ждёт
echo   раздел «Общие».
echo.
if not defined LW_ASSUME_YES pause
exit /b 0

:abort
echo.
echo   Установка прервана.
if not defined LW_ASSUME_YES pause
exit /b 1

:not_a_tree
echo.
echo   [ошибка] Это не папка бота.
echo.
echo            install.bat запускают из распакованного архива — из той
echo            папки, где рядом с ним лежат panel\, src\ и
echo            requirements.txt.
echo.
echo            Нажмите на скачанный .zip правой кнопкой, выберите
echo            «Извлечь всё», откройте получившуюся папку и запустите
echo            install.bat уже оттуда.
echo.
pause
exit /b 1

:in_temp
echo.
echo   [ошибка] Запуск идёт из временной папки:
echo            "%LW_DIR%"
echo.
echo            Так бывает, когда install.bat запускают прямо из окна .zip,
echo            не распаковав архив: Windows копирует его куда-то во
echo            временную папку и потом стирает — вместе со всей установкой.
echo.
echo            Нажмите на .zip правой кнопкой, выберите «Извлечь всё»,
echo            укажите свою папку (например, «Документы») и запустите
echo            install.bat оттуда.
echo.
pause
exit /b 1

:bad_path
echo.
echo   [ошибка] В пути к папке есть «!» или «%%»:
echo            "%LW_DIR%"
echo.
echo            Из такого пути bat-файлы Windows работают неправильно.
echo            Переименуйте папку или распакуйте архив в другое место и
echo            запустите install.bat ещё раз.
echo.
pause
exit /b 1


REM ======================================================= subroutines ==

:step
set /a STEP+=1
echo [!STEP!] %~1
exit /b 0

:warn
set /a WARNINGS+=1
echo     [внимание] %~1
exit /b 0

:is_admin
REM Readable only by an elevated process.
reg query "HKU\S-1-5-19" >nul 2>&1
exit /b %ERRORLEVEL%

:resolve_desktop
REM The real Desktop, which may be redirected (OneDrive, a network share).
set "LW_DESKTOP="
for /f "usebackq tokens=2,*" %%a in (`reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders" /v Desktop 2^>nul`) do set "LW_DESKTOP=%%b"
if defined LW_DESKTOP call set "LW_DESKTOP=%LW_DESKTOP%"
if not defined LW_DESKTOP set "LW_DESKTOP=%USERPROFILE%\Desktop"
exit /b 0

:relaunch_elevated
REM Everything PowerShell needs travels in the environment, not in the
REM command text: a path with a quote or an apostrophe in it would otherwise
REM end the string it sits in. Where the bot is does not travel at all - the
REM elevated copy is this same file and works it out from its own path.
set "PS_FILE=%LW_SELF%"
set "PS_ARGS=--elevated --desktop "%LW_DESKTOP%" --user "%LW_USER%" --pydir "%LW_PY_DIR%" --repo "%LW_REPO_URL%" --branch "%LW_BRANCH%""
for %%p in (!LW_PROFILES!) do set "PS_ARGS=!PS_ARGS! --profile %%p"
if defined LW_NO_ATTACH    set "PS_ARGS=!PS_ARGS! --no-attach"
if defined LW_SKIP_NPCAP   set "PS_ARGS=!PS_ARGS! --no-npcap"
if defined LW_NO_SHORTCUTS set "PS_ARGS=!PS_ARGS! --no-shortcuts"
if defined LW_ASSUME_YES   set "PS_ARGS=!PS_ARGS! --yes"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:PS_FILE -ArgumentList $env:PS_ARGS -Verb RunAs"
if errorlevel 1 (
    echo   [ошибка] Не удалось поднять права. Нажмите на install.bat правой
    echo            кнопкой и выберите «Запуск от имени администратора».
    if not defined LW_ASSUME_YES pause
    exit /b 1
)
exit /b 0

:download
REM %1 url, %2 destination. Two fetchers, in order, because they fail at
REM different things: curl ships with Windows 10 1803 and later but its TLS
REM stack refuses a certificate whose revocation list it cannot reach (a
REM machine behind an inspecting proxy, or one that is offline for that
REM lookup), and PowerShell's .NET one does not - while an older box has no
REM curl at all. Whatever arrives is checksummed by the caller either way.
if exist "%~2" del /f /q "%~2" >nul 2>&1
set "PS_URL=%~1"
set "PS_OUT=%~2"
where curl.exe >nul 2>&1
if not errorlevel 1 (
    curl.exe -L --fail --retry 3 --retry-delay 2 -# -o "%~2" "%~1"
    if errorlevel 1 if exist "%~2" del /f /q "%~2" >nul 2>&1
)
if not exist "%~2" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri $env:PS_URL -OutFile $env:PS_OUT -UseBasicParsing"
)
if not exist "%~2" (
    echo     [ошибка] Не удалось скачать: %~1
    exit /b 1
)
exit /b 0

:verify
REM %1 file, %2 expected sha256. A mismatch means the file is not what the
REM vendor published - it never gets run.
if not exist "%~1" (
    echo     [ошибка] Файла %~nx1 нет — проверять нечего.
    exit /b 1
)
set "GOT="
for /f %%h in ('certutil -hashfile "%~1" SHA256 ^| findstr /r /c:"^[0-9a-fA-F][0-9a-fA-F ]*$"') do if not defined GOT set "GOT=%%h"
if not defined GOT (
    call :warn "не удалось посчитать хеш %~nx1 — продолжаю без проверки"
    exit /b 0
)
set "GOT=!GOT: =!"
if /i not "!GOT!"=="%~2" (
    echo     [ошибка] Контрольная сумма %~nx1 не сходится.
    echo              ожидалась %~2
    echo              получена  !GOT!
    exit /b 1
)
exit /b 0

:ensure_python
call :find_python
if defined PY (
    echo     уже стоит: !PY!
    exit /b 0
)
echo     не найден — качаю %PY_URL%
call :download "%PY_URL%" "%LW_TMP%\python-installer.exe"
if errorlevel 1 exit /b 1
call :verify "%LW_TMP%\python-installer.exe" "%PY_SHA256%"
if errorlevel 1 exit /b 1
echo     ставлю в %LW_PY_DIR% — это займёт около минуты...
start /wait "" "%LW_TMP%\python-installer.exe" /quiet InstallAllUsers=1 TargetDir="%LW_PY_DIR%" PrependPath=1 Include_pip=1 Include_tcltk=1 Include_launcher=1 Include_test=0 AssociateFiles=0 CompileAll=0
call :find_python
if not defined PY (
    echo     [ошибка] Python не установился. Запустите установщик вручную:
    echo              %LW_TMP%\python-installer.exe
    exit /b 1
)
echo     поставлен: !PY!
exit /b 0

:find_python
REM LW_PYTHON wins, then the managed install, then the py launcher. Only
REM 3.12 counts: part of the CV stack still has no 3.13 wheels.
set "PY="
if defined LW_PYTHON if exist "%LW_PYTHON%" call :py_is_312 "%LW_PYTHON%" && set "PY=%LW_PYTHON%"
if not defined PY if exist "%LW_PY_DIR%\python.exe" call :py_is_312 "%LW_PY_DIR%\python.exe" && set "PY=%LW_PY_DIR%\python.exe"
if not defined PY for /f "delims=" %%e in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%e"
exit /b 0

:py_is_312
"%~1" -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>&1
exit /b %ERRORLEVEL%

:ensure_git
REM Nothing in this install needs Git - the sources came in the archive - so
REM it is set up but never fatal. update.bat and the panel's own «Обновление»
REM block use it when the folder is a git checkout rather than an unpacked
REM archive.
call :find_git
if defined GIT (
    echo     уже стоит: !GIT!
    exit /b 0
)
echo     не найден — качаю %GIT_URL%
call :download "%GIT_URL%" "%LW_TMP%\git-installer.exe"
if errorlevel 1 (
    call :warn "Git не скачался — без него панель не сможет обновляться сама; поставьте позже с https://git-scm.com"
    exit /b 0
)
call :verify "%LW_TMP%\git-installer.exe" "%GIT_SHA256%"
if errorlevel 1 (
    call :warn "скачанный Git не сошёлся с контрольной суммой и запущен не был — поставьте позже с https://git-scm.com"
    exit /b 0
)
echo     ставлю — это займёт около минуты...
start /wait "" "%LW_TMP%\git-installer.exe" /VERYSILENT /NORESTART /NOCANCEL /SP- /SUPPRESSMSGBOXES /COMPONENTS="icons,ext\shellhere,assoc,assoc_sh" /o:PathOption=Cmd
call :find_git
if not defined GIT (
    call :warn "Git не установился — без него панель не сможет обновляться сама. Запустите установщик вручную: %LW_TMP%\git-installer.exe"
    exit /b 0
)
echo     поставлен: !GIT!
exit /b 0

:find_git
set "GIT="
for /f "delims=" %%g in ('where git.exe 2^>nul') do if not defined GIT set "GIT=%%g"
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramW6432%\Git\cmd\git.exe" set "GIT=%ProgramW6432%\Git\cmd\git.exe"
if not defined GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
exit /b 0

:attach_repo
REM An unpacked archive carries no history, so the panel's «Обновить» button and
REM update.bat have nothing to pull. This makes the folder a checkout where it
REM stands: init, remote, a shallow fetch of the one branch, and the branch set
REM to track it. Nothing is cloned and nothing moves - the files already on disk
REM stay where the person unpacked them, brought up to the branch's tip.
REM
REM It is offered rather than done: it reaches the network, it can pick up
REM changes the person did not ask for, and refusing costs only the update
REM route. A failure rolls the half-made repository back, so a folder that was
REM an archive before is an archive after.
if exist "%LW_DIR%\.git" (
    echo     папка уже git-репозиторий — кнопка «Обновить» в панели работает
    exit /b 0
)
if defined LW_NO_ATTACH (
    echo     пропущено — обновляться можно, распаковав новый архив поверх папки
    exit /b 0
)
if not defined GIT (
    call :warn "Git не найден — подключить папку не к чему; обновляться придётся, распаковывая новый архив поверх неё"
    exit /b 0
)
echo     Папка распакована из архива, истории git в ней нет — значит кнопка
echo     «Обновить» в панели и update.bat обновлять её не смогут. Могу
echo     подключить папку к репозиторию: файлы бота обновятся до последней
echo     версии ветки %LW_BRANCH%, профили, логи и записи не тронутся, никуда
echo     ничего не копируется.
call :ask "     Подключить папку к репозиторию?"
if errorlevel 1 (
    echo     пропущено — обновляться можно, распаковав новый архив поверх папки
    exit /b 0
)
"!GIT!" -C "%LW_DIR%" init >nul 2>&1
if errorlevel 1 (
    call :warn "git init не отработал — папка осталась как была, обновлять её придётся новым архивом"
    exit /b 0
)
REM `init -b` is git 2.28 and newer; this says the same to every version, and
REM the branch it names does not have to exist yet.
"!GIT!" -C "%LW_DIR%" symbolic-ref HEAD "refs/heads/%LW_BRANCH%" >nul 2>&1
"!GIT!" -C "%LW_DIR%" remote add origin "%LW_REPO_URL%" >nul 2>&1
echo     качаю историю ветки %LW_BRANCH%...
REM One branch, one commit deep: the panel only ever asks "есть ли что-то
REM новее", and a shallow fetch answers that without pulling years of history
REM down a home connection. `git pull --ff-only` later deepens it as needed.
"!GIT!" -C "%LW_DIR%" fetch --quiet --depth=1 origin "%LW_BRANCH%"
if errorlevel 1 goto attach_failed
"!GIT!" -C "%LW_DIR%" reset --mixed FETCH_HEAD >nul 2>&1
if errorlevel 1 goto attach_failed
"!GIT!" -C "%LW_DIR%" branch --set-upstream-to="origin/%LW_BRANCH%" "%LW_BRANCH%" >nul 2>&1
REM The archive may have been downloaded weeks ago; this brings the tracked
REM files up to the commit just fetched. Untracked ones - profiles, logs,
REM captures, .env - are not touched by it.
"!GIT!" -C "%LW_DIR%" checkout -- . >nul 2>&1
echo     подключено: origin/%LW_BRANCH% — кнопка «Обновить» в панели теперь работает
exit /b 0

:attach_failed
REM Leave nothing half-made behind: without this the folder would look like a
REM repository to the panel and report "нет origin" for ever.
rd /s /q "%LW_DIR%\.git" >nul 2>&1
call :warn "не удалось подключиться к %LW_REPO_URL% — папка осталась как была. Обновляться можно, распаковав новый архив поверх неё"
exit /b 0

:install_requirements
REM Everything is relative to the folder this file sits in - the requirement
REM files and the editable install of src\ alike.
pushd "%LW_DIR%"
"!PY!" -m pip install --upgrade pip
if errorlevel 1 call :warn "pip не смог обновить сам себя — продолжаю с той версией, что стоит"
"!PY!" -m pip install -r requirements.txt
if errorlevel 1 (
    popd
    echo     [ошибка] Установка requirements.txt не удалась.
    exit /b 1
)
if exist "requirements-tools.txt" (
    "!PY!" -m pip install -r requirements-tools.txt
    if errorlevel 1 call :warn "пакеты для захвата трафика не встали — снифферы не запустятся"
)
"!PY!" -m pip install -e .
if errorlevel 1 (
    popd
    echo     [ошибка] Команда "pip install -e ." не удалась.
    exit /b 1
)
popd
exit /b 0

:offer_npcap
if defined LW_SKIP_NPCAP (
    echo     пропущено
    exit /b 0
)
if exist "%SystemRoot%\System32\Npcap\wpcap.dll" (
    echo     уже стоит
    exit /b 0
)
echo     npcap — драйвер, через который снифферы читают трафик игры.
echo     Бесплатная версия ставится только руками, поэтому откроется её
echo     собственное окно: оставьте галочку
echo     "Install Npcap in WinPcap API-compatible Mode".
call :ask "     Скачать и запустить установщик npcap сейчас?"
if errorlevel 1 (
    echo     пропущено — поставьте позже с https://npcap.com
    exit /b 0
)
call :download "%NPCAP_URL%" "%LW_TMP%\npcap-installer.exe"
if errorlevel 1 (
    call :warn "npcap не скачался — поставьте позже с https://npcap.com"
    exit /b 0
)
start /wait "" "%LW_TMP%\npcap-installer.exe"
exit /b 0

:ask
REM %1 prompt. errorlevel 0 = yes, 1 = no. --yes answers yes without asking,
REM and a box without choice.exe answers no rather than blocking.
if defined LW_ASSUME_YES exit /b 0
choice /c YN /n /m "%~1 [Y - да / N - нет] "
if errorlevel 2 exit /b 1
if errorlevel 1 exit /b 0
exit /b 1

:make_shortcuts
if defined LW_NO_SHORTCUTS (
    echo     пропущено
    exit /b 0
)
call :shortcut "Last War — панель" "%LW_DIR%\panel.bat" "" 1
for %%p in (!LW_PROFILES!) do call :shortcut "Last War — панель (%%p)" "%LW_DIR%\panel.bat" "--profile %%p" 1
REM Elevated as well: refreshing the packages writes into an all-users Python.
call :shortcut "Last War — обновление" "%LW_DIR%\update.bat" "" 1
REM No shortcut for daemon.bat, and there is not to be one: the panel starts the
REM daemon itself, and a second one on the same port only fails to bind. The file
REM stays in the folder for driving the game without the panel - scripts, or a
REM second client in its own Windows session.
exit /b 0

:shortcut
REM %1 name, %2 target, %3 arguments, %4 "1" = run as administrator.
REM The panel carries that flag: it reads the game out of another process'
REM memory and npcap wants the rights too. Untick "Run as administrator" in
REM the shortcut's properties to drop it.
REM Everything travels in the environment - see :relaunch_elevated.
REM The name is read back through a delayed variable, never as %~1 inside a
REM parenthesised block: a profile shortcut is called "... (main)", and the
REM closing bracket would be expanded into the block and end it early.
set "SC_NAME=%~1"
set "SC_LNK=%LW_DESKTOP%\%~1.lnk"
set "SC_TGT=%~2"
set "SC_ARG=%~3"
set "SC_WD=%LW_DIR%"
set "SC_ICON=%LW_PY_DIR%\pythonw.exe,0"
set "SC_ADM=%~4"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:SC_LNK); $s.TargetPath=$env:SC_TGT; $s.Arguments=$env:SC_ARG; $s.WorkingDirectory=$env:SC_WD; $s.IconLocation=$env:SC_ICON; $s.WindowStyle=7; $s.Description='Last War Bot'; $s.Save(); if ($env:SC_ADM -eq '1') { $b=[IO.File]::ReadAllBytes($env:SC_LNK); $b[0x15]=$b[0x15] -bor 0x20; [IO.File]::WriteAllBytes($env:SC_LNK,$b) }"
if exist "!SC_LNK!" (
    echo     !SC_NAME!
) else (
    call :warn "не удалось создать ярлык !SC_NAME!"
)
exit /b 0
