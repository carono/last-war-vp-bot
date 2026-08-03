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

    LW_LAUNCHER      the launcher — an override for an install that is not ordinary
    LW_GAME_DIR      the installation folder (the launcher's parent)
    LW_GAME_FOLDER   where the game sits under a user's Local AppData — relative, and
                     the only form that works for ANOTHER account's copy
    LW_LAUNCHER_EXE  the launcher's filename
    LW_GAME_EXE      the client's process name
    LW_WIN_PYTHON    the Windows interpreter child processes are started with

**Nothing here has to be set.** A second account is a tick and a login: the launcher in
*that* account's profile is found by looking its profile directory up in the registry
(:func:`launcher_in_profile`) and joining the ordinary install onto it. The variables
are for installs that are not ordinary.

**A per-user path is expanded where it means something.** ``%LOCALAPPDATA%`` names a
different folder for every account, so expanding it in the panel would name the PANEL
user's install and then hand that to the other account's token. A configured launcher
therefore travels to a second session **verbatim**, and
`tools/session_launch.py::expand_for` resolves it against that session's own environment
block — the one place on the machine where those variables are the target account's.
An absolute path is simply unaffected by that step.

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
    else needs. THIS desktop's answer only: a second account's launcher is resolved
    inside that account's session, from the string passed down unexpanded.
    """
    return _env("LW_LAUNCHER", os.path.join(game_dir(), launcher_exe()))


def launcher_in_profile(profile_dir: str) -> str:
    """The launcher inside somebody ELSE's user profile.

    `profile_dir` is that account's profile directory (`C:\\Users\\casper`), which only
    SYSTEM can look up out of the registry — so this is the shape
    `tools/session_launch.py` needs, and the one `%LOCALAPPDATA%` cannot express from
    outside. **This is what makes adding an account free:** tick the box, type the
    login, and the path is a lookup rather than something typed by hand.

    Deliberately no `LW_LAUNCHER` branch. A configured launcher is applied by the
    caller that still has a usable environment, and is passed down verbatim so the far
    side can expand it against the target session's own variables; reading the variable
    *here* would read SYSTEM's copy of it, which is nobody's game.
    """
    return os.path.join(profile_dir, LOCAL_APPDATA_SUBDIR, game_folder(),
                        launcher_exe())
