@echo off
REM Pull the latest sources and refresh the Python dependencies. This is the
REM second Desktop shortcut install.bat makes; run it whenever the panel has
REM fallen behind, or after a task lands upstream.
REM
REM Local edits are never thrown away: the pull is fast-forward only, and it
REM says so and stops if a commit or an uncommitted change is in the way.
REM
REM Unpacked from an archive rather than cloned? Then there is no history to
REM pull and the sources step says so instead of failing at git; the packages
REM are refreshed all the same.
REM
REM Refreshing the packages writes into the all-users Python install.bat set
REM up, which needs administrator rights - the Desktop shortcut carries them.
REM Started by hand, right-click it and pick "Run as administrator".
REM
REM UTF-8 first; what it prints is Russian, the comments stay English.
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%LW_PYTHON%"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY set "PY=python"

set "GIT=git"
where git.exe >nul 2>&1 || if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"

echo [1/2] Исходники
if not exist "%~dp0.git" (
    echo     Эта папка распакована из архива — истории git в ней нет, и
    echo     обновить исходники отсюда нельзя. Два выхода:
    echo       * запустить install.bat — он предложит подключить папку к
    echo         репозиторию, и дальше обновление заработает и здесь, и
    echo         кнопкой «Обновить» в панели;
    echo       * скачать свежий архив и распаковать его поверх этой папки,
    echo         заменив файлы: профили, логи и записи лежат в отдельных
    echo         папках и не пострадают.
    echo     Пакеты Python обновлю в любом случае.
    goto packages
)
"%GIT%" pull --ff-only
if errorlevel 1 (
    echo.
    echo     Перемотать вперёд не вышло: мешают локальные коммиты или правки.
    echo     Закоммитьте, спрячьте в stash или отмените их — и запустите снова.
    pause
    exit /b 1
)

:packages
echo.
echo [2/2] Пакеты Python
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto failed
if exist "requirements-tools.txt" "%PY%" -m pip install -r requirements-tools.txt
"%PY%" -m pip install -e .
if errorlevel 1 goto failed

echo.
echo Всё свежее.
pause
exit /b 0

:failed
echo.
echo Установить зависимости не удалось. Запустите install.bat — он доставит
echo всё, чего не хватает, включая сам интерпретатор. Если пакеты ставятся
echo в общий Python, запускать нужно от имени администратора.
pause
exit /b 1
