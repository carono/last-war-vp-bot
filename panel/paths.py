"""Where the panel keeps everything it owns — ONE directory, and this file says which.

**Everything local the panel has is under ``<project>/profiles/``.** The per-profile
directories, the panel-wide ``settings.json``, the timer and trigger templates, the
fallback debug log. Nothing of the panel's lives in the user's home directory, in
``%APPDATA%``, in a temporary directory or at any absolute path written into the code:
copy the project folder somewhere else and you get a panel with its own profiles in it,
and an empty ``profiles/`` is a clean panel with nobody else's settings (#1276).

THERE USED TO BE TWO DIRECTORIES CALLED ``profiles`` AND THAT IS THE WHOLE STORY OF
#1263 / #1276. The panel wrote to ``panel/profiles/``; the repository root also had a
``profiles/``, which belonged to the DSL bot's own ``--profile`` flag
(``src/lastwar_bot/profile.py``) and held one flat ``<id>.json`` per operator. A person
looking for their settings opened the one in the root — the obvious place, and the right
instinct — and found a stale file from months ago. Asked three times, told twice that the
settings were "in the panel folder", and still nothing they could see.

So there is one now, in the root, and it is the panel's. The bot's own profiles moved
into :data:`BOT_PROFILES_DIR` — ``profiles/_bot/`` — which is inside the same directory,
named so that it cannot be mistaken for an account, and skipped by the profile list
(:data:`RESERVED_NAMES`). Two different things may not share one name blindly; when they
do, the person pays for it and no amount of documentation gets them their afternoon back.

**A path is written here once.** :mod:`panel.profile`, :mod:`panel.i18n`,
:mod:`panel.debug_log`, :mod:`panel.timers` and :mod:`panel.triggers` all import it from
here rather than each spelling out its own ``os.path.join(PANEL_DIR, …)``, which is how
five of them drifted into five different answers to "where does the panel keep things".

**And there is deliberately no environment variable in front of it.** Everywhere else
in this repository a machine-dependent value gets one (``tools/lib/game_paths.py``),
because the game may be installed anywhere. This is the opposite case: the answer is
*derived from where the project itself is*, so it is already right on every machine, and
a variable pointing somewhere else would reintroduce the exact thing being fixed — state
living outside the folder you copied.

This module imports nothing but :mod:`os`. Everything else in the panel is free to
import it, including :mod:`panel.i18n`, which :mod:`panel.profile` in turn imports.
"""
from __future__ import annotations

import os

#: ``panel/`` itself — the code. Nothing local is written here any more.
PANEL_DIR = os.path.dirname(os.path.abspath(__file__))

#: The project root: the directory holding ``panel/``, ``src/``, ``tools/``, ``docs/``.
PROJECT_DIR = os.path.dirname(PANEL_DIR)

#: **The one directory.** Everything the panel keeps locally is in here.
PROFILES_DIR = os.path.join(PROJECT_DIR, "profiles")

#: Panel-wide, not any one account's: which profile is showing, which are open, the
#: update channel, the language. Beside the profile directories, inside the same tree.
SETTINGS_FILE = os.path.join(PROFILES_DIR, "settings.json")

#: The timer and trigger TEMPLATES: what a profile with no catalogue of its own is
#: seeded from (``panel/timers.py``, ``panel/triggers.py``). Panel-wide and editable,
#: so they sit beside ``settings.json`` rather than beside the code that seeds them.
TIMERS_TEMPLATE = os.path.join(PROFILES_DIR, "timers.json")
TRIGGERS_TEMPLATE = os.path.join(PROFILES_DIR, "triggers.json")

#: The fallback debug log — used only before the panel has pointed the handler at a
#: profile's own ``debug.log`` (``panel/debug_log.py``).
FALLBACK_DEBUG_LOG = os.path.join(PROFILES_DIR, "panel_debug.log")

#: The DSL bot's own profiles (``src/lastwar_bot/profile.py``, ``--profile <id>``): one
#: flat ``<id>.json`` each. Inside the panel's directory, under a name that reads as
#: machinery rather than as somebody's account — see the module docstring.
BOT_PROFILES_DIR = os.path.join(PROFILES_DIR, "_bot")

#: Directory names inside :data:`PROFILES_DIR` that are NOT a panel profile. The profile
#: list skips them and a profile may not be created or renamed to one.
RESERVED_NAMES = frozenset({"_bot"})

# -- where things used to be, so the first start can bring them across ---------------
#
# Read by `panel/profile.py`'s migration and by nothing else. Kept here so that the old
# layout is written down in the same file as the new one: the next person to wonder
# "why is there a `panel/profiles` in this old checkout" has one place to look.

LEGACY_PROFILES_DIR = os.path.join(PANEL_DIR, "profiles")
LEGACY_SETTINGS_FILE = os.path.join(PANEL_DIR, "settings.json")
LEGACY_TIMERS_TEMPLATE = os.path.join(PANEL_DIR, "timers.json")
LEGACY_TRIGGERS_TEMPLATE = os.path.join(PANEL_DIR, "triggers.json")

#: The language preference, which used to live in the operator's HOME directory — the
#: one thing the panel wrote outside the project altogether, so a fresh copy of the
#: project silently inherited the original's language and nothing else (#1276). Now a
#: key in :data:`SETTINGS_FILE`; this path is read once, to bring the old answer across.
LEGACY_LANG_FILE = os.path.join(os.path.expanduser("~"), ".last_war_panel.json")

#: Dropped in the old ``panel/profiles/`` once its contents have been brought across, so
#: a second start does not copy stale files back over fresher ones. Only written when the
#: directory could not simply be MOVED (Windows refuses to move a tree something still
#: holds a file open in) — a successful move leaves nothing behind to mark.
MIGRATION_MARKER = "MOVED-TO-PROJECT-PROFILES.txt"


def is_profile_name(name: str) -> bool:
    """Is ``name`` a directory inside :data:`PROFILES_DIR` that names a panel profile?

    False for the machinery (:data:`RESERVED_NAMES`) and for anything starting with a
    dot, so a ``.git``-like directory somebody drops in never becomes an account.
    """
    name = (name or "").strip()
    return bool(name) and not name.startswith(".") and name not in RESERVED_NAMES
