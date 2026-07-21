"""Locate the running game: its PID and its top-level window handle.

Two independent facts the rest of the bot needs:

* ``find_game_pid()`` — the process id, used by the memory/IL2CPP tooling. Pure
  psutil, works even when the window can't be found.
* ``get_hwnd()`` — the window handle, used for screenshots and input. Delegates
  to :func:`lastwar_bot.perception.capture.find_window`, which already does a
  single ``EnumWindows`` pass and returns hwnd + pid together, so there is no
  second window-enumeration implementation to keep in sync.

Both are Windows-only at call time; imports stay lazy so this module loads on
any platform (handy for offline protocol tests on Linux/WSL).
"""
from __future__ import annotations

# Substrings/names the game is known by. The window title and the executable
# differ, so each discovery path uses the one it can see.
GAME_PROCESS_NEEDLE = "lastwar"
GAME_EXE = "LastWar.exe"
GAME_WINDOW_TITLE = "Last War"

# The launcher (not the game exe) is what a cold start spawns; it patches, then
# starts LastWar.exe itself. ``%LOCALAPPDATA%`` keeps the path user-agnostic —
# the same string the ``launch_game`` action script uses.
GAME_LAUNCHER = r"%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe"


class GameNotRunning(RuntimeError):
    """The game process or window could not be found."""


def find_game_pid() -> int:
    """Return the PID of the running game, or raise :class:`GameNotRunning`."""
    import psutil

    for proc in psutil.process_iter(["name"]):
        name = (proc.info["name"] or "").lower()
        if GAME_PROCESS_NEEDLE in name:
            return proc.pid
    raise GameNotRunning(f"{GAME_EXE} is not running")


def find_window():
    """Return the game's :class:`~lastwar_bot.perception.capture.WindowInfo`.

    Reuses the perception layer's window finder (hwnd + title + pid + process
    name in one shot). Raises :class:`GameNotRunning` if the window is absent.
    """
    from lastwar_bot.perception.capture import WindowNotFoundError, find_window as _find

    try:
        # process_name="" disables the exe filter, since some builds report a
        # different image name than the window title suggests.
        return _find(GAME_WINDOW_TITLE, None)
    except WindowNotFoundError as exc:  # normalise to our own error type
        raise GameNotRunning(str(exc)) from exc


def get_hwnd() -> int:
    """Return the game's top-level window handle (HWND)."""
    return find_window().hwnd


def is_game_running() -> bool:
    """Whether the game process is up. Never raises."""
    try:
        find_game_pid()
        return True
    except GameNotRunning:
        return False


def launch_game(launcher: str = GAME_LAUNCHER) -> None:
    """Spawn the game launcher (detached). Returns immediately.

    A cold start takes a minute or two and ends on the base screen; the caller
    should watch the passive stream for the first scene rather than poll here.
    Raises :class:`GameNotRunning` if the launcher executable is missing.
    """
    import os
    import subprocess
    from pathlib import Path

    exe = Path(os.path.expanduser(os.path.expandvars(launcher)))
    if not exe.exists():
        raise GameNotRunning(f"launcher not found at {exe}")
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)


__all__ = [
    "GAME_PROCESS_NEEDLE", "GAME_EXE", "GAME_WINDOW_TITLE", "GAME_LAUNCHER",
    "GameNotRunning", "find_game_pid", "find_window", "get_hwnd",
    "is_game_running", "launch_game",
]
