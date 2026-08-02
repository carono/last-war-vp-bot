@echo off
REM ======================================================================
REM  Last War Bot - Windows installer.
REM
REM  Brings a bare Windows 10/11 box to a working control panel: installs
REM  Git and Python 3.12, clones this repository, installs the Python
REM  dependencies and puts shortcuts on the Desktop. Nothing has to be
REM  installed beforehand - download this one file and run it.
REM
REM  Re-running it is safe: what is already there is detected and kept, an
REM  existing checkout is fast-forwarded instead of re-cloned, and the
REM  dependencies are refreshed.
REM
REM  Every default it works by can be overridden - "install.bat --help"
REM  prints the options (:usage below is the one copy of that list).
REM
REM  Python lands in C:\Python312 on purpose: that is what the panel's
REM  Settings -> General -> Python defaults to, so the sniffers and the
REM  other child processes it spawns find their interpreter unconfigured.
REM ======================================================================
setlocal EnableExtensions EnableDelayedExpansion
title Last War Bot installer

set "LW_SELF=%~f0"
set "LW_SELFDIR=%~dp0"
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
if /i "%~1"=="--dir"          ( set "LW_DIR=%~2"      & shift & shift & goto parse_args )
if /i "%~1"=="--branch"       ( set "LW_BRANCH=%~2"   & shift & shift & goto parse_args )
if /i "%~1"=="--repo"         ( set "LW_REPO_URL=%~2" & shift & shift & goto parse_args )
if /i "%~1"=="--pydir"        ( set "LW_PY_DIR=%~2"   & shift & shift & goto parse_args )
if /i "%~1"=="--desktop"      ( set "LW_DESKTOP=%~2"  & shift & shift & goto parse_args )
if /i "%~1"=="--user"         ( set "LW_USER=%~2"     & shift & shift & goto parse_args )
if /i "%~1"=="--profile"      ( set "LW_PROFILES=!LW_PROFILES! %~2" & shift & shift & goto parse_args )
if /i "%~1"=="--no-npcap"     ( set "LW_SKIP_NPCAP=1"   & shift & goto parse_args )
if /i "%~1"=="--no-shortcuts" ( set "LW_NO_SHORTCUTS=1" & shift & goto parse_args )
if /i "%~1"=="--yes"          ( set "LW_ASSUME_YES=1"   & shift & goto parse_args )
if /i "%~1"=="--elevated"     ( set "LW_ELEVATED=1"     & shift & goto parse_args )
if /i "%~1"=="--help"         goto usage
if /i "%~1"=="/?"             goto usage
echo Unknown option: %~1
echo Run "install.bat --help" for the list.
exit /b 2

:usage
echo.
echo   Last War Bot installer - sets up Git, Python 3.12, this repository,
echo   its dependencies and the Desktop shortcuts. Safe to run again.
echo.
echo   install.bat [options]
echo.
echo     --dir  PATH      where the repository goes  (default C:\LastWarBot;
echo                      when run from inside a checkout, that checkout)
echo     --branch NAME    branch to check out        (default v2)
echo     --repo URL       repository to clone from
echo     --pydir PATH     where Python 3.12 goes     (default C:\Python312)
echo     --profile NAME   an extra Desktop shortcut opening the panel on that
echo                      panel profile; may be repeated
echo     --no-npcap       do not offer to install npcap
echo     --no-shortcuts   do not touch the Desktop
echo     --yes            never ask anything
echo     --help           print this and exit
echo.
exit /b 0

:args_done
if not defined LW_REPO_URL set "LW_REPO_URL=https://github.com/carono/last-war-vp-bot.git"
if not defined LW_BRANCH   set "LW_BRANCH=v2"
if not defined LW_PY_DIR   set "LW_PY_DIR=C:\Python312"

REM Started from inside a checkout? Then that checkout is what gets set up.
if not defined LW_DIR (
    if exist "%LW_SELFDIR%pyproject.toml" if exist "%LW_SELFDIR%panel\__main__.py" set "LW_DIR=%LW_SELFDIR:~0,-1%"
)
if not defined LW_DIR set "LW_DIR=C:\LastWarBot"
if not defined LW_DESKTOP call :resolve_desktop
REM Who is being installed for. Kept across the elevation because the tree
REM is created by an administrator and would otherwise be read-only to the
REM person who runs the panel.
if not defined LW_USER set "LW_USER=%USERDOMAIN%\%USERNAME%"

echo.
echo   Last War Bot - installer
echo   ------------------------
echo   repository : %LW_REPO_URL%  (%LW_BRANCH%)
echo   install to : %LW_DIR%
echo   python     : %LW_PY_DIR%  (%PY_VERSION%)
echo   desktop    : %LW_DESKTOP%
echo.

REM ----------------------------------------------------------- elevation
REM Installing Python and Git for all users needs administrator rights, and
REM so does pip writing into the interpreter's site-packages. The Desktop is
REM resolved BEFORE elevating and handed over, so the shortcuts land on the
REM desktop of whoever started this even if another account answers the UAC
REM prompt.
call :is_admin
if errorlevel 1 (
    if defined LW_ELEVATED (
        echo   [error] Still not running as administrator. Right-click install.bat
        echo       and pick "Run as administrator".
        goto abort
    )
    call :step "Asking for administrator rights"
    call :relaunch_elevated
    exit /b !ERRORLEVEL!
)

if not exist "%LW_TMP%" mkdir "%LW_TMP%" >nul 2>&1

call :step "Python %PY_VERSION%"
call :ensure_python
if errorlevel 1 goto abort

call :step "Git"
call :ensure_git
if errorlevel 1 goto abort

call :step "Repository"
call :ensure_source
if errorlevel 1 goto abort

call :step "Python packages"
call :install_requirements
if errorlevel 1 goto abort

call :step "npcap (packet capture driver)"
call :offer_npcap

call :step "Desktop shortcuts"
call :make_shortcuts

echo.
echo   Done.
echo     panel        : %LW_DIR%\panel.bat    (Desktop: "Last War - panel")
echo     update later : %LW_DIR%\update.bat   (Desktop: "Last War - update")
echo     python       : !PY!
if not "!WARNINGS!"=="0" echo     !WARNINGS! warning(s) above - read them before the first run.
echo.
echo   The panel opens on its summary page. Where the game client lives is
echo   set on its Settings page, under Game; the interpreter above is already
echo   what the General page expects.
echo.
if not defined LW_ASSUME_YES pause
exit /b 0

:abort
echo.
echo   Installation stopped.
if not defined LW_ASSUME_YES pause
exit /b 1


REM ======================================================= subroutines ==

:step
set /a STEP+=1
echo [!STEP!] %~1
exit /b 0

:warn
set /a WARNINGS+=1
echo     [warn] %~1
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
REM end the string it sits in.
set "PS_FILE=%LW_SELF%"
set "PS_ARGS=--elevated --dir "%LW_DIR%" --desktop "%LW_DESKTOP%" --user "%LW_USER%" --pydir "%LW_PY_DIR%" --repo "%LW_REPO_URL%" --branch "%LW_BRANCH%""
for %%p in (!LW_PROFILES!) do set "PS_ARGS=!PS_ARGS! --profile %%p"
if defined LW_SKIP_NPCAP   set "PS_ARGS=!PS_ARGS! --no-npcap"
if defined LW_NO_SHORTCUTS set "PS_ARGS=!PS_ARGS! --no-shortcuts"
if defined LW_ASSUME_YES   set "PS_ARGS=!PS_ARGS! --yes"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:PS_FILE -ArgumentList $env:PS_ARGS -Verb RunAs"
if errorlevel 1 (
    echo   [error] Could not elevate. Right-click install.bat and pick
    echo       "Run as administrator".
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
    echo     [error] Download failed: %~1
    exit /b 1
)
exit /b 0

:verify
REM %1 file, %2 expected sha256. A mismatch means the file is not what the
REM vendor published - it never gets run.
if not exist "%~1" (
    echo     [error] %~nx1 is not there to be checked.
    exit /b 1
)
set "GOT="
for /f %%h in ('certutil -hashfile "%~1" SHA256 ^| findstr /r /c:"^[0-9a-fA-F][0-9a-fA-F ]*$"') do if not defined GOT set "GOT=%%h"
if not defined GOT (
    call :warn "could not hash %~nx1 - carrying on without the checksum"
    exit /b 0
)
set "GOT=!GOT: =!"
if /i not "!GOT!"=="%~2" (
    echo     [error] Checksum mismatch for %~nx1
    echo         expected %~2
    echo         got      !GOT!
    exit /b 1
)
exit /b 0

:ensure_python
call :find_python
if defined PY (
    echo     found: !PY!
    exit /b 0
)
echo     not installed - downloading %PY_URL%
call :download "%PY_URL%" "%LW_TMP%\python-installer.exe"
if errorlevel 1 exit /b 1
call :verify "%LW_TMP%\python-installer.exe" "%PY_SHA256%"
if errorlevel 1 exit /b 1
echo     installing into %LW_PY_DIR% - this takes a minute...
start /wait "" "%LW_TMP%\python-installer.exe" /quiet InstallAllUsers=1 TargetDir="%LW_PY_DIR%" PrependPath=1 Include_pip=1 Include_tcltk=1 Include_launcher=1 Include_test=0 AssociateFiles=0 CompileAll=0
call :find_python
if not defined PY (
    echo     [error] Python did not install. Run the downloaded installer by hand:
    echo         %LW_TMP%\python-installer.exe
    exit /b 1
)
echo     installed: !PY!
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
call :find_git
if defined GIT (
    echo     found: !GIT!
    exit /b 0
)
echo     not installed - downloading %GIT_URL%
call :download "%GIT_URL%" "%LW_TMP%\git-installer.exe"
if errorlevel 1 exit /b 1
call :verify "%LW_TMP%\git-installer.exe" "%GIT_SHA256%"
if errorlevel 1 exit /b 1
echo     installing - this takes a minute...
start /wait "" "%LW_TMP%\git-installer.exe" /VERYSILENT /NORESTART /NOCANCEL /SP- /SUPPRESSMSGBOXES /COMPONENTS="icons,ext\shellhere,assoc,assoc_sh" /o:PathOption=Cmd
call :find_git
if not defined GIT (
    echo     [error] Git did not install. Run the downloaded installer by hand:
    echo         %LW_TMP%\git-installer.exe
    exit /b 1
)
echo     installed: !GIT!
exit /b 0

:find_git
set "GIT="
for /f "delims=" %%g in ('where git.exe 2^>nul') do if not defined GIT set "GIT=%%g"
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramW6432%\Git\cmd\git.exe" set "GIT=%ProgramW6432%\Git\cmd\git.exe"
if not defined GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
exit /b 0

:ensure_source
if exist "%LW_DIR%\.git" (
    echo     updating %LW_DIR%
    "!GIT!" -C "%LW_DIR%" fetch --prune origin
    "!GIT!" -C "%LW_DIR%" checkout "%LW_BRANCH%"
    if errorlevel 1 call :warn "could not check out %LW_BRANCH% - the checkout stays on its current branch"
    "!GIT!" -C "%LW_DIR%" pull --ff-only
    if errorlevel 1 call :warn "could not fast-forward - local commits or edits are in the way, the checkout is left alone"
) else (
    echo     cloning into %LW_DIR%
    "!GIT!" clone --branch "%LW_BRANCH%" "%LW_REPO_URL%" "%LW_DIR%"
    if errorlevel 1 (
        echo     [error] Clone failed. If the repository is private, sign in when Git
        echo         asks - or clone it by hand and re-run with --dir pointing at it.
        exit /b 1
    )
)
if not exist "%LW_DIR%\panel\__main__.py" (
    echo     [error] %LW_DIR% does not look like the bot's source tree.
    exit /b 1
)
REM An administrator made this tree, so by default the person who runs the
REM panel could only read it - and the panel writes its profiles, its logs
REM and every capture back into it.
icacls "%LW_DIR%" /grant "%LW_USER%:(OI)(CI)M" /T /C /Q >nul 2>&1
if errorlevel 1 call :warn "could not grant %LW_USER% write access to %LW_DIR% - the panel may not be able to save its profile"
exit /b 0

:install_requirements
pushd "%LW_DIR%"
"!PY!" -m pip install --upgrade pip
if errorlevel 1 call :warn "pip could not update itself - carrying on with the version that is there"
"!PY!" -m pip install -r requirements.txt
if errorlevel 1 (
    popd
    echo     [error] Installing requirements.txt failed.
    exit /b 1
)
if exist "requirements-tools.txt" (
    "!PY!" -m pip install -r requirements-tools.txt
    if errorlevel 1 call :warn "the capture extras did not install - the traffic sniffers will not run"
)
"!PY!" -m pip install -e .
if errorlevel 1 (
    popd
    echo     [error] "pip install -e ." failed.
    exit /b 1
)
popd
exit /b 0

:offer_npcap
if defined LW_SKIP_NPCAP (
    echo     skipped
    exit /b 0
)
if exist "%SystemRoot%\System32\Npcap\wpcap.dll" (
    echo     already installed
    exit /b 0
)
echo     npcap is the driver the traffic sniffers read the game's wire through.
echo     Its free edition installs by hand, so its own window opens - keep
echo     "Install Npcap in WinPcap API-compatible Mode" ticked.
call :ask "     Download and start the npcap installer now?"
if errorlevel 1 (
    echo     skipped - install it later from https://npcap.com
    exit /b 0
)
call :download "%NPCAP_URL%" "%LW_TMP%\npcap-installer.exe"
if errorlevel 1 (
    call :warn "npcap could not be downloaded - install it later from https://npcap.com"
    exit /b 0
)
start /wait "" "%LW_TMP%\npcap-installer.exe"
exit /b 0

:ask
REM %1 prompt. errorlevel 0 = yes, 1 = no. --yes answers yes without asking,
REM and a box without choice.exe answers no rather than blocking.
if defined LW_ASSUME_YES exit /b 0
choice /c YN /n /m "%~1 [Y/N] "
if errorlevel 2 exit /b 1
if errorlevel 1 exit /b 0
exit /b 1

:make_shortcuts
if defined LW_NO_SHORTCUTS (
    echo     skipped
    exit /b 0
)
call :shortcut "Last War - panel" "%LW_DIR%\panel.bat" "" 1
for %%p in (!LW_PROFILES!) do call :shortcut "Last War - panel (%%p)" "%LW_DIR%\panel.bat" "--profile %%p" 1
REM Elevated as well: refreshing the packages writes into an all-users Python.
call :shortcut "Last War - update" "%LW_DIR%\update.bat" "" 1
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
    call :warn "could not create the shortcut !SC_NAME!"
)
exit /b 0
