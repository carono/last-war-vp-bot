r"""Where the game is on THIS machine — one answer, changeable without editing code.

Everything here was a literal, and most of it was a literal in several files at once
that had already drifted apart: `panel/__main__.py` said the game lives under
``%LOCALAPPDATA%\FunFly\Last War-Survival Game`` (right), while the default behind the
panel's own «launcher» setting said ``C:\Program Files\LastWar`` (wrong, and read by
`tools/game_locale.py` to find the game's locale tables). Someone whose game is on
another drive had no way to say so except a source change.

So: one module, read by the panel, the tools and the DSL alike, and every value an
environment variable with the old literal as its default. Nothing changes for a machine
that sets none of them.

    LW_LAUNCHER      the launcher, absolute. THE one most people would ever set.
    LW_GAME_DIR      the installation folder (the launcher's parent)
    LW_GAME_FOLDER   where the game sits under a user's Local AppData — relative, and
                     the only form that works for ANOTHER account's copy
    LW_LAUNCHER_EXE  the launcher's filename
    LW_GAME_EXE      the client's process name
    LW_WIN_PYTHON    the Windows interpreter child processes are started with

**Absolute beats per-user.** ``%LOCALAPPDATA%`` names a different folder for every
account, so a path built from it is this desktop's alone and cannot be handed to another
session's token (`game_client._shared_path` is where that is enforced). An absolute
``LW_LAUNCHER`` has nothing left to expand, so it is the same file for everybody and
reaches a second account's session unchanged — which is why it is the recommended knob
rather than the folder ones.

Functions, not constants, so a value can be changed in the environment and read back
without re-importing the world. Callers that want a constant snapshot one at import (as
the module defaults below them do), which is the same thing the literals used to be.
"""
from __future__ import annotations

import os

#: The publisher/product folder as it sits under a user's Local AppData. Relative on
#: purpose: it is the ONLY form that can name another account's copy, since that
#: account's `%LOCALAPPDATA%` is not ours to expand.
DEFAULT_GAME_FOLDER = os.path.join("FunFly", "Last War-Survival Game")
DEFAULT_LAUNCHER_EXE = "LastWarLauncher.exe"
DEFAULT_GAME_EXE = "LastWar.exe"
#: `install.bat` puts Python 3.12 here precisely so this answers itself.
DEFAULT_WIN_PYTHON = r"C:\Python312\python.exe"

#: Where Local AppData sits inside a user profile — the fixed half of the path to
#: another account's install (`<profile>\AppData\Local\<game folder>`).
LOCAL_APPDATA_SUBDIR = os.path.join("AppData", "Local")


def _env(name: str, fallback: str) -> str:
    """An environment override, ignoring one that is set but empty."""
    return (os.environ.get(name) or "").strip() or fallback


def game_folder() -> str:
    """``FunFly\\Last War-Survival Game`` — relative to a user's Local AppData."""
    return _env("LW_GAME_FOLDER", DEFAULT_GAME_FOLDER)


def launcher_exe() -> str:
    """The launcher's filename, without a directory."""
    return _env("LW_LAUNCHER_EXE", DEFAULT_LAUNCHER_EXE)


def game_exe() -> str:
    """The client's process name — what a process list is searched for."""
    return _env("LW_GAME_EXE", DEFAULT_GAME_EXE)


def win_python() -> str:
    """The Windows interpreter child processes are started with."""
    return _env("LW_WIN_PYTHON", DEFAULT_WIN_PYTHON)


def local_appdata() -> str:
    """This account's Local AppData, with the fallback Windows itself would use."""
    return _env("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))


def game_dir() -> str:
    """The installation folder on THIS desktop.

    `LW_GAME_DIR` wins; otherwise it is built from this account's Local AppData, which
    makes it per-user and therefore useless for another session — see the module note.
    """
    return _env("LW_GAME_DIR", os.path.join(local_appdata(), game_folder()))


def launcher() -> str:
    """The launcher on THIS desktop, absolute.

    `LW_LAUNCHER` wins outright, and setting it is the one thing an install somewhere
    else needs: being absolute, it also travels to another account's session.
    """
    return _env("LW_LAUNCHER", os.path.join(game_dir(), launcher_exe()))


def launcher_in_profile(profile_dir: str) -> str:
    """The launcher inside somebody ELSE's user profile.

    `profile_dir` is that account's profile directory (`C:\\Users\\casper`), which only
    SYSTEM can look up — so this is the shape `tools/session_launch.py` needs and the
    one `%LOCALAPPDATA%` cannot express. `LW_LAUNCHER` still wins when it is absolute,
    because then it names one file for every account on the machine.
    """
    forced = (os.environ.get("LW_LAUNCHER") or "").strip()
    if forced and os.path.isabs(forced) and forced == os.path.expandvars(forced):
        return forced
    return os.path.join(profile_dir, LOCAL_APPDATA_SUBDIR, game_folder(),
                        launcher_exe())
