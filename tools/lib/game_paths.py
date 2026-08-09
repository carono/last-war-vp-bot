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
    LW_WEB_PORT      the port the panel's web front-end listens on (a profile may
                     override it; this is the machine's answer)

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

#: The client's window title — what a window search matches on, as a substring. Not a
#: locale question: the client names its window the same in every language it ships.
DEFAULT_WINDOW_TITLE = "Last War-Survival Game"

#: Where Local AppData sits inside a user profile — the fixed half of the path to
#: another account's install (`<profile>\AppData\Local\<game folder>`).
LOCAL_APPDATA_SUBDIR = os.path.join("AppData", "Local")
#: Unity's `persistentDataPath` root. What the client DOWNLOADS (chat photos, avatars)
#: lands under `<LocalLow>\<game folder>`, which is a different tree from the install.
LOCAL_LOW_SUBDIR = os.path.join("AppData", "LocalLow")

#: The asset index and the bundle cache, relative to the installation folder.
GAMERES_SUBPATH = os.path.join("Game", "LastWar_Data", "StreamingAssets",
                               "AssetBundles", "gameres")
ASSET_CACHE_SUBPATH = os.path.join("Cache", "AssetBundles")
#: The client itself, relative to the installation folder (the launcher's sibling).
GAME_EXE_SUBDIR = "Game"
#: The game's own translations — one directory per build, one `<lang>.bin` per language
#: inside it (`docs/research/game-locale-tables.md`). Relative to the install.
LOCALE_SUBPATH = os.path.join("Game", "LastWar_Data", "StreamingAssets", "locale")

#: The TCP port the client talks to the game server on. A *fallback*: the capture tools
#: ask the live connection first (`map_capture.detect_game_ports`), because this has
#: already moved once — a capture pinned to 17935 went quietly empty against a client
#: that had connected out on 10012, which reads exactly like «nothing is happening».
DEFAULT_GAME_PORT = 17935

#: The port the panel's web front-end listens on (`panel/web/`, #1221). High, in no
#: registry, and easy to type on a phone — but not everybody's to have: a machine
#: already running something there needs another one, and a person who has forwarded a
#: port on their router has a number they must use. A profile's own knob overrides this;
#: this is the answer for a profile that has never been asked.
DEFAULT_WEB_PORT = 9761

#: Where Wireshark's `tshark` lives, seen from WSL. Two guesses at the ordinary Windows
#: install under the ordinary mount point — neither of which is a given: a machine may
#: mount its drives elsewhere (`/c`, `/windows/c`) and may keep Wireshark off C:.
DEFAULT_WIRESHARK_DIRS = (
    "/mnt/c/Program Files/Wireshark",
    "/mnt/c/Program Files (x86)/Wireshark",
)


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


def window_title() -> str:
    """The client's window title — matched as a case-insensitive substring.

    Together with :func:`game_exe` this is the whole of «which window is the game»,
    and it used to be a literal pair repeated at seven call sites across the bot,
    the vision tools and the panel. A client that names its window otherwise — a
    re-skinned or regional build — is now one variable, not seven edits.
    """
    return _env("LW_WINDOW_TITLE", DEFAULT_WINDOW_TITLE)


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

    `profile_dir` is that account's profile directory (`C:\\Users\\<login>`), which only
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


def game_exe_path() -> str:
    """The client executable on THIS desktop, absolute — the launcher's child."""
    return os.path.join(game_dir(), GAME_EXE_SUBDIR, game_exe())


def paths_in_profile(profile_dir: str) -> tuple[str, str]:
    """``(launcher, client)`` inside somebody ELSE's user profile.

    The pair `tools/launch_as_user.py` needs, built the same way and from the same
    values as :func:`launcher_in_profile` — see its note on why nothing here reads
    `LW_LAUNCHER`.
    """
    root = os.path.join(profile_dir, LOCAL_APPDATA_SUBDIR, game_folder())
    return (os.path.join(root, launcher_exe()),
            os.path.join(root, GAME_EXE_SUBDIR, game_exe()))


# --- what the client keeps on disk -------------------------------------------------
#
# Two separate trees, and confusing them costs an afternoon: the INSTALL sits under
# Local AppData (the bundles it shipped with), while everything the client DOWNLOADS
# lands under LocalLow, Unity's `persistentDataPath`. Chat photos are the second kind.


def local_low() -> str:
    """This account's LocalLow, with the fallback Windows itself would use."""
    return _env("LW_LOCALLOW", os.path.expanduser(os.path.join("~", LOCAL_LOW_SUBDIR)))


def data_dir() -> str:
    """The client's `persistentDataPath` on THIS desktop — its download tree."""
    return _env("LW_GAME_DATA_DIR", os.path.join(local_low(), game_folder()))


def chat_photos_dir() -> str:
    """Where the client caches chat photos and avatars it has downloaded.

    `LASTWAR_CHATPHOTOS` is still honoured: it is what the panel's own machines were
    told to set before there was a resolver, and breaking a live install to tidy a
    name is not a trade worth making.
    """
    return _env("LW_CHAT_PHOTOS", _env("LASTWAR_CHATPHOTOS",
                                       os.path.join(data_dir(), "ChatPhotos")))


def local_images() -> str:
    """Where the client caches the player photos it downloads as it meets people.

    A flat-ish tree beside the chat-photo cache in the same download directory:
    `LocalImages/<last 6 digits of uid>/<md5(f"{uid}_{picVer}")>.jpg`. It fills up with
    exactly the players this client has seen, which is what makes it worth reading.
    """
    return _env("LW_LOCAL_IMAGES", os.path.join(data_dir(), "LocalImages"))


def gameres() -> str:
    """The text index of the shipped asset bundles."""
    return _env("LW_GAMERES", os.path.join(game_dir(), GAMERES_SUBPATH))


def asset_cache() -> str:
    """The downloaded-bundle cache. Machine-specific: it can sit on any drive."""
    return _env("LW_ASSET_CACHE", os.path.join(game_dir(), ASSET_CACHE_SUBPATH))


def locale_root() -> str:
    """Where the game keeps its own translations — the folder holding the build dirs."""
    return os.path.join(game_dir(), LOCALE_SUBPATH)


def locale_dir() -> "str | None":
    """The build directory of language tables, or ``None`` if there is none to read.

    `LW_LOCALE_DIR` names it outright — that is what a machine with the game somewhere
    unusual sets, and it is the variable `tools/game_locale.py` has always documented.
    Otherwise it is the newest build under :func:`locale_root` that actually holds
    tables: the client leaves the previous build's folder behind after an update, and an
    empty one is not an answer.

    **Never raises and never guesses.** A caller reads the game's own wording out of
    this — the kick sentence, a glossary term — and «the tables are not here» has to be
    distinguishable from «the tables say no», or a reading built on them fails closed on
    a machine whose install this cannot find (`tools/lib/game_kick.py`).
    """
    forced = (os.environ.get("LW_LOCALE_DIR") or "").strip()
    if forced:
        return forced if os.path.isdir(forced) else None
    root = locale_root()
    builds = []
    try:
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if os.path.isdir(path) and any(f.endswith(".bin") for f in os.listdir(path)):
                builds.append(path)
        return max(builds, key=lambda p: os.stat(p).st_mtime) if builds else None
    except OSError:
        return None


# --- what the capture tools need ---------------------------------------------------


def game_port() -> int:
    """The server port to filter a capture on, when the live connection cannot say.

    `LW_GAME_PORT` moves it. Prefer asking the running client
    (`map_capture.detect_game_ports`) — a port that has changed under a hardcoded
    filter does not raise, it simply captures nothing at all.
    """
    raw = (os.environ.get("LW_GAME_PORT") or "").strip()
    try:
        return int(raw) if raw else DEFAULT_GAME_PORT
    except ValueError:
        return DEFAULT_GAME_PORT


def web_port() -> int:
    """The port the panel's web front-end listens on when a profile has not said.

    `LW_WEB_PORT` moves it, for the machine where 9761 is taken or where a router
    forwards something else. THREE LAYERS, and this is the bottom one: the profile's own
    knob wins (a second account wants a second port), the variable is the machine's
    answer, and 9761 is everybody's. Out-of-range or unreadable falls back rather than
    binding something absurd — a port of 0 would listen on whatever the OS handed out,
    which is a remote control nobody can find.
    """
    raw = (os.environ.get("LW_WEB_PORT") or "").strip()
    try:
        port = int(raw) if raw else DEFAULT_WEB_PORT
    except ValueError:
        return DEFAULT_WEB_PORT
    return port if 1 <= port <= 65535 else DEFAULT_WEB_PORT


def wireshark_dirs() -> tuple[str, ...]:
    """Where to look for `tshark`, most specific first.

    `LW_WIRESHARK_DIR` is tried first and is the whole answer for a machine that keeps
    Wireshark somewhere else or mounts its Windows drives somewhere else — both of
    which are ordinary, and neither of which the two guesses below can cover.
    """
    forced = (os.environ.get("LW_WIRESHARK_DIR") or "").strip()
    return (forced,) + DEFAULT_WIRESHARK_DIRS if forced else DEFAULT_WIRESHARK_DIRS
