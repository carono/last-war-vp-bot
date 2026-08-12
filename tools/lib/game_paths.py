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
    LW_CACHE_DIR     where WE keep what is the same for every profile — the players'
                     faces, the generated pages. Defaults to `<project>/cache/`

The last one is the odd one out and says so where it is defined: everything else here
answers «where is the game on this machine», and that one answers «where do we put what
we downloaded». It is here because this is the module both the panel and the tools
already ask, and a path spelled in two places is a path that drifts.

**AND A DEFAULT IS A GUESS, WHICH AN UPDATE CAN OUTLIVE (#1320).** Every value below
used to be one literal with one fallback, and a client update is exactly the event that
makes such a literal wrong on a machine where it had been right for a year: the update
of 2026-08-12 left the window and the process alone and moved the downloaded-bundle
cache clean off the install — off the drive, even — so `asset_cache()` named a folder
that no longer existed, and the newest language tables started arriving in the client's
DOWNLOAD tree while the install kept a stale build of them.

So nothing here guesses ONCE any more. Three things changed, and they are the shape
every value in this module should have:

* **The launcher's own manifest is asked first** (:func:`launcher_manifest`).
  `LastWarLauncher.json` sits beside the launcher, is written by the installer, and
  names the install, the download tree, the temp folder, the bundle root and the
  client's own display name. It is the machine's answer *written by the thing that
  chose it*, which no default can be.
* **Where several answers are possible, the one that EXISTS wins**
  (:func:`_resolve`). A candidate list — the variable, the manifest, the old default —
  is walked in that order and the first that is actually on disk is the answer; if none
  are, the highest-priority one is returned anyway, so the error names the path a person
  would have to create or configure.
* **Every value can say where it came from** (:func:`describe`, :func:`report`, and
  `python tools/lib/game_paths.py`). A path that is missing must be visible as a path
  that is missing, with the variable that overrides it printed beside it — the failure
  this all exists for looked, from the panel, like «the game is not running».

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

import json
import os
import re

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
#: A *fallback* since #1320: the launcher's manifest names the build's own title, and a
#: re-skinned or renamed client is then found without anybody setting anything.
DEFAULT_WINDOW_TITLE = "Last War-Survival Game"

#: The launcher's own description of the install, beside the launcher. Written by the
#: installer, rewritten by every update, and therefore the only thing on the machine
#: that knows where THIS install decided to put its parts.
DEFAULT_LAUNCHER_JSON = "LastWarLauncher.json"

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
#: The bundle cache, relative to the bundle ROOT the installer picked. On an ordinary
#: install that root is `<install>\Cache`; on this one it is a folder on another drive,
#: which is why the root is asked of the launcher rather than assumed (#1320).
BUNDLE_CACHE_SUBDIR = "AssetBundles"
#: The bundle root, relative to the installation folder — the arrangement an install
#: that never chose otherwise has.
DEFAULT_BUNDLE_SUBDIR = "Cache"
#: The client itself, relative to the installation folder (the launcher's sibling).
GAME_EXE_SUBDIR = "Game"
#: The game's own translations — one directory per build, one `<lang>.bin` per language
#: inside it (`docs/research/game-locale-tables.md`). Relative to the install.
LOCALE_SUBPATH = os.path.join("Game", "LastWar_Data", "StreamingAssets", "locale")
#: …and the same tree in the client's DOWNLOAD directory, which is where a build newer
#: than the installed one arrives. The install keeps whatever it shipped with, so after
#: an update the two disagree and only one of them is what the player is reading
#: (#1320: install `.../locale/<older build>`, download `.../locale/<newer build>`).
LOCALE_DOWNLOAD_SUBDIR = "locale"

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


# --- what the launcher itself says (#1320) -----------------------------------------
#
# `LastWarLauncher.json` is the installer's own note of the choices it made, and an
# update rewrites it. Reading it is what turns «the bundle cache moved to another drive»
# from a source change into no change at all.

_manifest_cache: "tuple[tuple, dict] | None" = None


def launcher_json() -> str:
    """The launcher's manifest file, absolute.

    `LW_LAUNCHER_JSON` names it outright — for an install laid out so unusually that the
    manifest is not the launcher's sibling. Otherwise it is exactly that.
    """
    forced = (os.environ.get("LW_LAUNCHER_JSON") or "").strip()
    return forced or os.path.join(os.path.dirname(launcher()), DEFAULT_LAUNCHER_JSON)


def launcher_manifest() -> dict:
    """The launcher's manifest, or ``{}`` where there is none to read.

    **Never raises.** A machine with no game, a half-finished update writing the file,
    a manifest in a shape a later build changed — every one of them is «no answer from
    here», which simply lets the next candidate through. A resolver that could throw
    would take the panel down for a file that is nobody's contract.

    Cached against the file's own timestamp and size, so an update is picked up without
    a restart and a hot path does not re-read a 1 KB file on every call.
    """
    global _manifest_cache                     # noqa: PLW0603 — one file, re-read on change
    path = launcher_json()
    try:
        stat = os.stat(path)
        stamp = (path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        _manifest_cache = None
        return {}
    if _manifest_cache is not None and _manifest_cache[0] == stamp:
        return _manifest_cache[1]
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        _manifest_cache = (stamp, {})
        return {}
    if not isinstance(data, dict):
        data = {}
    _manifest_cache = (stamp, data)
    return data


def forget_manifest() -> None:
    """Drop the cached manifest — for a test, and after an install has been moved."""
    global _manifest_cache                     # noqa: PLW0603
    _manifest_cache = None


def _flag(cmdline: str, flag: str) -> str:
    """One ``--flag <path>`` out of a Windows command line, quoted or bare.

    The manifest keeps the interesting directories in the uninstall command rather than
    as fields of their own, so this is how they are got at. Written by hand rather than
    with `shlex`, which is POSIX-minded and eats the backslashes out of every path here.
    """
    match = re.search(rf"{re.escape(flag)}\s+(?:\"([^\"]*)\"|(\S+))", cmdline)
    if not match:
        return ""
    return (match.group(1) or match.group(2) or "").strip()


def manifest_paths() -> dict:
    """What the launcher's manifest says about this install, under our own names.

    Every value may be empty — see :func:`launcher_manifest` — and an empty one is «this
    file does not know», never «there is nothing there».

    ``install`` the installation folder · ``data`` the client's download tree ·
    ``temp`` the updater's staging folder · ``bundle`` the ROOT of the downloaded-bundle
    cache · ``titles`` what this build calls itself, most specific first.
    """
    data = launcher_manifest()
    uninstall = str(data.get("uninstall_string") or "")
    titles = []
    for key in ("display_name", "app_name"):
        name = str(data.get(key) or "").strip()
        if name and name not in titles:
            titles.append(name)
    return {
        "install": str(data.get("app_dir") or "").strip() or _flag(uninstall, "--root"),
        "data": _flag(uninstall, "--app"),
        "temp": _flag(uninstall, "--temp"),
        "bundle": _flag(uninstall, "--bundle"),
        "titles": tuple(titles),
    }


# --- one answer out of several candidates -------------------------------------------


def _resolve(candidates) -> "tuple[str, str]":
    """``(path, where it came from)`` — the answer, and what supplied it.

    `candidates` is ``(source, path)`` in order of authority, and **the first entry is
    always the environment variable**. Three rules, in this order:

    1. **A variable that is set wins outright, existing or not.** It is a person's
       statement about their machine, and quietly overruling a typo with the ordinary
       install is how somebody spends an afternoon watching the bot use a folder they
       explicitly told it not to. A path that is set and missing must fail as itself.
    2. Otherwise the first candidate that is actually **on disk** — because that is
       precisely the reading a client update invalidates: yesterday's default still
       parses, still looks like a path, and simply is not there any more.
    3. Otherwise the highest-priority candidate anyway, with its source, so the caller
       reports a path a person can create or override rather than an empty string that
       reads as a bug in the bot.
    """
    named = [(src, path) for src, path in candidates if path]
    if not named:
        return "", "none"
    first_src, first_path = named[0]
    if first_src.startswith("LW_"):
        return first_path, first_src
    for src, path in named:
        if os.path.exists(path):
            return path, src
    return named[0][1], named[0][0]


def game_folder() -> str:
    """``FunFly\\Last War-Survival Game`` — relative to a user's Local AppData."""
    return _env("LW_GAME_FOLDER", DEFAULT_GAME_FOLDER)


def launcher_exe() -> str:
    """The launcher's filename, without a directory."""
    return _env("LW_LAUNCHER_EXE", DEFAULT_LAUNCHER_EXE)


def game_exe() -> str:
    """The client's process name — what a process list is searched for."""
    return _env("LW_GAME_EXE", DEFAULT_GAME_EXE)


def window_titles() -> "tuple[str, ...]":
    """Every title the client might be running under, most specific first.

    Together with :func:`game_exe` this is the whole of «which window is the game», and
    for a long time it was ONE string: right until the day a build named its window
    something else, after which nothing on the machine could find a client that was
    plainly on screen.

    `LW_WINDOW_TITLE` is the override and is the whole answer when it is set — several
    titles may be given, separated by ``;``, for a machine that runs more than one build.
    Unset, the launcher's manifest is asked what THIS build calls itself, and the title
    the client has always used is kept behind it, so nothing changes on a machine whose
    manifest cannot be read.

    Matched as case-insensitive substrings, in this order — and see
    `lastwar_bot.perception.capture.find_window`, which falls back to the game's own
    process when not one of them matches, rather than reporting no client at all.
    """
    forced = (os.environ.get("LW_WINDOW_TITLE") or "").strip()
    if forced:
        wanted = [part.strip() for part in forced.split(";") if part.strip()]
    else:
        wanted = [*manifest_paths()["titles"], DEFAULT_WINDOW_TITLE]
    out: list[str] = []
    seen: set[str] = set()
    for title in wanted:
        if title.lower() not in seen:
            seen.add(title.lower())
            out.append(title)
    return tuple(out) or (DEFAULT_WINDOW_TITLE,)


def window_title() -> str:
    """The likeliest of :func:`window_titles` — what a lone default is built from."""
    return window_titles()[0]


def win_python() -> str:
    """The Windows interpreter child processes are started with."""
    return _env("LW_WIN_PYTHON", DEFAULT_WIN_PYTHON)


def local_appdata() -> str:
    """This account's Local AppData, with the fallback Windows itself would use."""
    return _env("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))


def game_dir() -> str:
    """The installation folder on THIS desktop.

    `LW_GAME_DIR` wins; failing that, a configured absolute `LW_LAUNCHER` already names
    the folder it sits in, and taking it from there is what stops the two settings from
    disagreeing — before #1320 a machine that had moved its install with `LW_LAUNCHER`
    alone still had `gameres()` and the language tables looked for under the folder the
    game was NOT in. Last of all it is built from this account's Local AppData, which
    makes it per-user and therefore useless for another session — see the module note.

    Deliberately does NOT ask the launcher's manifest: that file is found by way of this
    answer, so consulting it here would be a circle. It has nothing to add anyway — it
    lives in the very folder in question.
    """
    forced_launcher = (os.environ.get("LW_LAUNCHER") or "").strip()
    beside = os.path.dirname(forced_launcher) if os.path.isabs(forced_launcher) else ""
    path, _src = _resolve((
        ("LW_GAME_DIR", (os.environ.get("LW_GAME_DIR") or "").strip()),
        ("LW_LAUNCHER", beside),
        ("default", os.path.join(local_appdata(), game_folder())),
    ))
    return path


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
    """The client's `persistentDataPath` on THIS desktop — its download tree.

    `LW_GAME_DATA_DIR` first, then whatever the installer wrote down (`--app` in the
    manifest's uninstall command), then the ordinary spot under LocalLow.
    """
    path, _src = _resolve(_data_candidates())
    return path


def _data_candidates() -> tuple:
    return (
        ("LW_GAME_DATA_DIR", (os.environ.get("LW_GAME_DATA_DIR") or "").strip()),
        ("launcher manifest", manifest_paths()["data"]),
        ("default", os.path.join(local_low(), game_folder())),
    )


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


def bundle_root() -> str:
    """The root the client keeps its downloaded bundles under.

    Chosen at install time and **not necessarily on the drive the game is installed on**
    — the installer offers to put the tens of thousands of bundles elsewhere, and the
    machine this was found on has them on a second disk. So it is asked of the launcher's
    manifest (`--bundle`), and only failing that assumed to be the folder inside the
    install that an unchanged install uses.
    """
    path, _src = _resolve(_bundle_candidates())
    return path


def _bundle_candidates() -> tuple:
    return (
        ("LW_BUNDLE_ROOT", (os.environ.get("LW_BUNDLE_ROOT") or "").strip()),
        ("launcher manifest", manifest_paths()["bundle"]),
        ("default", os.path.join(game_dir(), DEFAULT_BUNDLE_SUBDIR)),
    )


def asset_cache() -> str:
    """The downloaded-bundle cache. Machine-specific: it can sit on any drive.

    `LW_ASSET_CACHE` still names it outright and still means exactly what it did.
    Unset, it is :func:`bundle_root` and the one subfolder in it — which is how a client
    update that moved the whole cache off the install stopped being a source change
    (#1320: the old default named `<install>\\Cache\\AssetBundles`, and after the update
    there was no `Cache` in the install at all).
    """
    path, _src = _resolve(_asset_cache_candidates())
    return path


def _asset_cache_candidates() -> tuple:
    return (
        ("LW_ASSET_CACHE", (os.environ.get("LW_ASSET_CACHE") or "").strip()),
        # Named for what it IS, not for what fed it: `_resolve` reads an `LW_` prefix as
        # «a person said so, do not second-guess it», and the bundle root may just as
        # well have come from the manifest.
        ("bundle root",
         os.path.join(bundle_root(), BUNDLE_CACHE_SUBDIR) if bundle_root() else ""),
        ("default", os.path.join(game_dir(), ASSET_CACHE_SUBPATH)),
    )


def locale_root() -> str:
    """Where the INSTALL keeps its own translations — the folder holding the builds."""
    return os.path.join(game_dir(), LOCALE_SUBPATH)


def locale_roots() -> "tuple[str, ...]":
    """Every folder that can hold builds of language tables.

    TWO of them, and that is the whole of the fix (#1320). The install ships a build and
    keeps it for ever; an update fetches a newer one into the client's DOWNLOAD tree. Ask
    the install alone — which is what this module did — and every reading taken from the
    game's own wording is one build behind from the first update onwards, silently,
    because a stale table is a perfectly readable table.
    """
    return (locale_root(), os.path.join(data_dir(), LOCALE_DOWNLOAD_SUBDIR))


def locale_dirs() -> "tuple[str, ...]":
    """Every build directory that actually holds tables, newest first.

    `LW_LOCALE_DIR` names one outright and is then the whole answer. Otherwise every
    build under every root in :func:`locale_roots` is collected and sorted by age: the
    client leaves the previous build's folder behind after an update, and an empty one
    is not an answer.

    **Never raises.** A machine with no game gets an empty tuple, which callers must be
    able to tell apart from «the tables say no» (`tools/lib/game_kick.py`).
    """
    forced = (os.environ.get("LW_LOCALE_DIR") or "").strip()
    if forced:
        return (forced,) if os.path.isdir(forced) else ()
    builds = []
    for root in locale_roots():
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            path = os.path.join(root, name)
            try:
                if not os.path.isdir(path):
                    continue
                if not any(f.endswith(".bin") for f in os.listdir(path)):
                    continue
                builds.append((os.stat(path).st_mtime, path))
            except OSError:
                continue
    builds.sort(key=lambda pair: pair[0], reverse=True)
    return tuple(path for _mtime, path in builds)


def locale_dir() -> "str | None":
    """The newest build directory of language tables, or ``None`` if there is none.

    **Never raises and never guesses.** A caller reads the game's own wording out of
    this — the kick sentence, a glossary term — and «the tables are not here» has to be
    distinguishable from «the tables say no», or a reading built on them fails closed on
    a machine whose install this cannot find (`tools/lib/game_kick.py`).

    For anything that wants a PARTICULAR language, prefer :func:`locale_tables`: the
    build the client downloads holds only the languages it is actually being played in,
    so the newest directory is not the one with the most tables in it.
    """
    found = locale_dirs()
    return found[0] if found else None


def locale_tables() -> dict:
    """``{language: the newest <lang>.bin on this machine}``.

    A build is not all-or-nothing, and assuming it was is the second half of the same
    fault: the install ships every language the client has, while the build an update
    downloads holds only the ones this player is using. Take «the newest build» whole
    and a glossary lookup loses eighteen languages the moment the client updates; take
    the newest *table per language* and both trees are used for exactly what each has.
    """
    out: dict = {}
    for path in locale_dirs():
        try:
            names = os.listdir(path)
        except OSError:
            continue
        for name in names:
            if name.endswith(".bin"):
                out.setdefault(name[:-len(".bin")], os.path.join(path, name))
    return out


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


# -- what WE keep, as opposed to where the game is ----------------------------------
#
# One directory, `<project>/cache/`, shared by every profile on the machine (#1306).
#
# WHY IT IS NOT A PROFILE'S. A profile owns what belongs to the ACCOUNT — its log, its
# schedule, its daemon, its state, its budgets — and isolating those is the whole of
# #1306. A picture downloaded off the client's own cache is not one of those: the same
# player's face is the same file whatever account happened to see them first, so four
# profiles keeping four copies is four times the disk and four times the work for one
# answer. The operator's words: «Кеш файлы, аватары, можно делать общими для всех, не
# обязательно это тянуть в профиль.»
#
# AND IT IS NOT IN `profiles/` EITHER. That directory is accounts, and a folder sitting
# in it is how the squads report's faces became an account with a share in another
# profile's daemon. A profile is a directory with a `config.json` now
# (`panel/profile.py`), which closes that on its own — but a cache still has no business
# being filed among the accounts, so it lives beside them rather than in them.


def repo_dir() -> str:
    """The project root — the directory holding `tools/`, `panel/`, `docs/`.

    Derived, never configured: it is where this file is, so it is already right on every
    machine. The same reasoning as `panel/paths.py`, which says it at length.
    """
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def cache_dir() -> str:
    """Everything downloaded or derived that is the same for every profile.

    `LW_CACHE_DIR` moves it, for a machine that would rather it were on another disk —
    it fills with pictures and it grows. Git-ignored, and nothing in it is ever needed
    to run: deleting the whole directory costs the time to fetch it again.
    """
    return _env("LW_CACHE_DIR", os.path.join(repo_dir(), "cache"))


def avatar_cache() -> str:
    """The players' faces, copied out of the client's own photo cache, one per uid.

    Shared on purpose (see the note above): the same player has the same face whichever
    account met them. `tools/lib/player_photos.py` finds the originals; this is where
    the shrunk copies the reports link to are kept.
    """
    return os.path.join(cache_dir(), "avatars")


def report_dir() -> str:
    """Where the generated pages go — beside the cache they link into, not in `profiles/`.

    A report is not an account's either: `tools/rally_report.py` folds EVERY profile's
    archive into one page, so filing it under one of them was always a misnomer.
    """
    return os.path.join(cache_dir(), "reports")


# --- saying it out loud (#1320) -----------------------------------------------------
#
# The failure this module was hardened against did not look like a path problem from
# anywhere a person could see. The panel said the game was not there; the game was on
# screen. So every drifting value can now say what it resolved to, WHERE that answer
# came from, and whether it is on disk — in the panel's debug log at every start, and
# from a shell when somebody is trying to work out why an install is not being found:
#
#     C:\Python312\python.exe tools\lib\game_paths.py
#     python3 tools/lib/game_paths.py


def describe() -> list:
    """Every value an update can invalidate: what it is, where it came from, is it there.

    One row per path, in the order a person would check them, each a dict of
    ``name`` · ``value`` · ``source`` (the variable or the file that supplied it) ·
    ``exists`` · ``override`` (the variable that moves it). Nothing here reads anything
    the getters do not, on purpose: a diagnosis that walks its own candidates is a second
    opinion, and the whole point is that there is one.
    """
    rows = []

    def row(name: str, value: str, source: str, override: str) -> None:
        rows.append({"name": name, "value": value, "source": source,
                     "override": override,
                     "exists": bool(value) and os.path.exists(value)})

    forced_launcher = (os.environ.get("LW_LAUNCHER") or "").strip()
    beside = os.path.dirname(forced_launcher) if os.path.isabs(forced_launcher) else ""
    _, src = _resolve((("LW_GAME_DIR", (os.environ.get("LW_GAME_DIR") or "").strip()),
                       ("LW_LAUNCHER", beside),
                       ("default", os.path.join(local_appdata(), game_folder()))))
    row("install", game_dir(), src, "LW_GAME_DIR")
    row("launcher", launcher(),
        "LW_LAUNCHER" if forced_launcher else "install + LW_LAUNCHER_EXE", "LW_LAUNCHER")
    row("client", game_exe_path(), "install + LW_GAME_EXE", "LW_GAME_EXE")
    row("launcher manifest", launcher_json(),
        "LW_LAUNCHER_JSON" if os.environ.get("LW_LAUNCHER_JSON") else "beside the launcher",
        "LW_LAUNCHER_JSON")
    row("asset index", gameres(),
        "LW_GAMERES" if os.environ.get("LW_GAMERES") else "install", "LW_GAMERES")
    row("download tree", *_resolve(_data_candidates()), "LW_GAME_DATA_DIR")
    row("bundle root", *_resolve(_bundle_candidates()), "LW_BUNDLE_ROOT")
    row("bundle cache", *_resolve(_asset_cache_candidates()), "LW_ASSET_CACHE")
    builds = locale_dirs()
    row("language tables", builds[0] if builds else "",
        "LW_LOCALE_DIR" if os.environ.get("LW_LOCALE_DIR")
        else f"newest of {len(builds)} build(s)", "LW_LOCALE_DIR")
    return rows


def report() -> str:
    """:func:`describe` as lines a person reads — the panel logs this, so does the CLI.

    A missing path is marked rather than merely absent from the list: «the folder the bot
    is looking in is not there» is the sentence that was missing when a client update
    moved one, and it has to survive being read in a hurry.
    """
    lines = []
    for item in describe():
        mark = "ok     " if item["exists"] else "MISSING"
        lines.append(f"{mark} {item['name']:<18} {item['value'] or '(nothing)'}"
                     f"   [{item['source']}; override {item['override']}]")
    titles = " | ".join(window_titles())
    lines.append(f"window   titles: {titles}   process: {game_exe()}"
                 f"   [override LW_WINDOW_TITLE, LW_GAME_EXE]")
    # Not a path, and here for the same reason as the rest: it has already moved once,
    # and a capture pinned to a port the game left does not fail — it records nothing,
    # which reads exactly like an idle account.
    lines.append(f"port     capture fallback: {game_port()} (the live socket is asked"
                 f" first)   [override LW_GAME_PORT]")
    return "\n".join(lines)


def missing() -> list:
    """The names of the paths that are not on disk — empty when all is well."""
    return [item["name"] for item in describe() if not item["exists"]]


def wireshark_dirs() -> tuple[str, ...]:
    """Where to look for `tshark`, most specific first.

    `LW_WIRESHARK_DIR` is tried first and is the whole answer for a machine that keeps
    Wireshark somewhere else or mounts its Windows drives somewhere else — both of
    which are ordinary, and neither of which the two guesses below can cover.
    """
    forced = (os.environ.get("LW_WIRESHARK_DIR") or "").strip()
    return (forced,) + DEFAULT_WIRESHARK_DIRS if forced else DEFAULT_WIRESHARK_DIRS


if __name__ == "__main__":                   # a support command, not an import
    print(report())
    raise SystemExit(1 if missing() else 0)
