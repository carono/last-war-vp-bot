"""Named profiles + persistent settings for the control panel.

A *profile* is a named set of panel settings plus its own logs, stored under
``panel/profiles/<name>/``::

    config.json             all panel settings (language, checkboxes, filters, coords…)
    rally_log.jsonl         rally-monitor output for this profile
    secret_tasks_log.jsonl  secret-task findings for this profile
    timers.json             this profile's timers (what runs, how often, args)
    timers_last_run.json    when each scheduled errand last ran
    panel.log               plain-text mirror of the panel log widget

The active profile name lives in ``panel/settings.json`` (global, profile-
independent), so the last-used profile is restored on the next launch. Switching
a profile just means reading a different ``config.json``; the panel re-applies
every setting from it.

This module is intentionally UI-agnostic: it only reads/writes JSON and manages
the on-disk layout. The panel binds its Tk variables to config keys and calls
:meth:`ProfileManager.save` whenever one changes.
"""
from __future__ import annotations

import json
import os
import re

# The ONLY thing this module takes from i18n: a way to name the reason it refused, so
# the dialog showing it can be in the person's language. No translator is built here —
# that stays the UI's business (see the module docstring).
from .i18n import Message

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(PANEL_DIR, "profiles")
SETTINGS_FILE = os.path.join(PANEL_DIR, "settings.json")

DEFAULT_PROFILE = "default"
RALLY_LOG = "rally_log.jsonl"
SECRET_LOG = "secret_tasks_log.jsonl"
CHAT_LOG = "chat_log.jsonl"
# The queryable chat store (panel/chat_history.py): every message the monitor sees
# is written here, and the panel reads the newest page from it at startup and pages
# older chunks in on scroll. Kept apart from CHAT_LOG, which stays the raw capture
# append-log written by the reader process itself.
CHAT_DB = "chat_history.db"
# Live checkpoint of the secret-task capture (tools/secret_task_capture.py --json).
# Unlike the *_log.jsonl files this one is rewritten whole each tick: it is the
# current state of the map, which is what an auto-loot decision has to read.
TASKS_JSON = "secret_tasks.json"
# The same shape for the other two map scans the «Командный пункт» tab drives: the
# ghost-recon squad tiles (f2 = 29, tools/dev/secret_mission_capture.py) and the
# detect-event treasures (f2 = 21, tools/dev/treasure_capture.py). Separate files
# because the record shapes differ — handing one scan's checkpoint to the other's
# reader is exactly the mix-up the secret-task capture already guards against.
GHOST_JSON = "ghost_recon_tiles.json"
TREASURES_JSON = "world_treasures.json"
# The profile's own timer catalogue and the record of when each of them last ran
# (panel/timers.py). Both per profile: one account's schedule is not the other's,
# and neither is its clock. A profile with no catalogue yet is seeded from the
# template panel/timers.json.
TIMERS_CONFIG = "timers.json"
TIMERS_STATE = "timers_last_run.json"
# The wire-driven errands (panel/triggers.py), seeded from the template
# panel/triggers.json exactly as the timers are from panel/timers.json.
TRIGGERS_CONFIG = "triggers.json"
# Per-monster-type daily caps on rally auto-join and today's running count
# (panel/rally_limits.py). Limits are seeded from the built-ins; counts reset daily.
RALLY_LIMITS_CONFIG = "rally_limits.json"
RALLY_COUNTS_STATE = "rally_counts.json"
# Daily tally of resources gained (panel/resource_stats.py): {date: {resource: n}},
# accumulated across days.
RESOURCE_STATS_STATE = "resource_stats.json"
# The accumulating SQLite history of ranking-board snapshots (tools/lib/leaderboard_store.py),
# filled by the «leaderboard_collect» trigger.
LEADERBOARD_DB = "leaderboard_history.db"
# The three files the autostart uses (panel/runtime/autostart.py). ALIVE_FILE is the heartbeat
# the open panel rewrites once a minute from its Tk event loop — the hourly scheduled
# check reads it to tell a live panel from a wedged one. AUTOSTART_STATE is what that
# check made of it last time (which is what the Settings page shows, since the
# scheduler's own «last run» column only says a task ran). AUTOSTART_LOG keeps the
# launches and anything a panel printed before its own logging was up.
ALIVE_FILE = "panel_alive.json"
AUTOSTART_STATE = "autostart.json"
AUTOSTART_LOG = "autostart.log"
PANEL_LOG = "panel.log"
# The technical debug log (panel/debug_log.py): every action, every traceback and a
# running snapshot of the systems' state, rotated by size. Kept apart from PANEL_LOG,
# which is only the human-facing widget's mirror.
DEBUG_LOG = "debug.log"
CONFIG_FILE = "config.json"

# Filesystem-hostile characters; profile names are used verbatim as directory
# names, so keep them safe and portable (Windows is the target host).
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str) -> str:
    """Normalise a profile name to a safe, non-empty directory name.

    Trims surrounding whitespace and trailing dots (invalid on Windows) and drops
    filesystem-hostile characters. Returns ``""`` for a name that reduces to
    nothing so the caller can reject it.
    """
    cleaned = _BAD_CHARS.sub("", (name or "").strip()).rstrip(". ").strip()
    return cleaned


# A character uid is a long decimal string from the game, but it reaches us as
# free-form text — keep only the characters that are safe in a filename so it can
# never escape the profile directory or collide with a control character.
_UID_SAFE = re.compile(r"[^0-9A-Za-z_-]")


def _sanitize_uid(uid: str) -> str:
    return _UID_SAFE.sub("", str(uid or "")) or "unknown"


class ProfileManager:
    """On-disk store of named profiles and the active-profile pointer."""

    def __init__(self) -> None:
        os.makedirs(PROFILES_DIR, exist_ok=True)
        # A fresh install has no profiles — seed the default so the UI always
        # has something to select.
        if not self.list():
            self._ensure_dir(DEFAULT_PROFILE)
        self._active = self._read_active()

    # -- profile enumeration ------------------------------------------------
    def list(self) -> list[str]:
        """Existing profile names, sorted (the default first if present)."""
        try:
            names = [n for n in os.listdir(PROFILES_DIR)
                     if os.path.isdir(os.path.join(PROFILES_DIR, n))]
        except OSError:
            names = []
        return sorted(names, key=lambda n: (n != DEFAULT_PROFILE, n.lower()))

    def exists(self, name: str) -> bool:
        name = sanitize(name)
        return bool(name) and os.path.isdir(os.path.join(PROFILES_DIR, name))

    @property
    def active(self) -> str:
        return self._active

    # -- active-profile pointer (panel/settings.json) -----------------------
    def _read_active(self) -> str:
        name = DEFAULT_PROFILE
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                name = json.load(fh).get("active_profile", DEFAULT_PROFILE)
        except (OSError, ValueError):
            pass
        if not self.exists(name):
            names = self.list()
            name = names[0] if names else self._ensure_dir(DEFAULT_PROFILE)
        return name

    def set_active(self, name: str) -> str:
        """Point the panel at ``name`` (creating it if missing) and persist it."""
        name = self._ensure_dir(name) if not self.exists(name) else sanitize(name)
        self._active = name
        data = {}
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        data["active_profile"] = name
        _write_json(SETTINGS_FILE, data)
        return name

    # -- lifecycle: create / rename / delete --------------------------------
    def create(self, name: str) -> str:
        """Create an empty profile. Raises ``ValueError`` on a bad/duplicate name."""
        name = sanitize(name)
        if not name:
            raise ValueError(Message("profile.error.empty_name", "empty profile name"))
        if self.exists(name):
            raise ValueError(Message("profile.error.exists",
                                     f"profile already exists: {name}", name=name))
        return self._ensure_dir(name)

    def rename(self, old: str, new: str) -> str:
        """Rename a profile, following the active pointer if it moved."""
        old, new = sanitize(old), sanitize(new)
        if not self.exists(old):
            raise ValueError(Message("profile.error.missing",
                                     f"no such profile: {old}", name=old))
        if not new:
            raise ValueError(Message("profile.error.empty_name", "empty profile name"))
        if new == old:
            return old
        if self.exists(new):
            raise ValueError(Message("profile.error.exists",
                                     f"profile already exists: {new}", name=new))
        os.rename(os.path.join(PROFILES_DIR, old), os.path.join(PROFILES_DIR, new))
        if self._active == old:
            self.set_active(new)
        return new

    def delete(self, name: str) -> str:
        """Delete a profile. The last remaining profile cannot be deleted.

        Returns the name that is active afterwards.
        """
        name = sanitize(name)
        if not self.exists(name):
            raise ValueError(Message("profile.error.missing",
                                     f"no such profile: {name}", name=name))
        if len(self.list()) <= 1:
            raise ValueError(Message("profile.error.last_one",
                                     "cannot delete the last profile"))
        import shutil
        shutil.rmtree(os.path.join(PROFILES_DIR, name), ignore_errors=True)
        if self._active == name:
            return self.set_active(self.list()[0])
        return self._active

    # -- config read / write ------------------------------------------------
    def load(self, name: str | None = None) -> dict:
        """Return a profile's settings dict (``{}`` if it has none yet)."""
        name = sanitize(name) if name else self._active
        try:
            with open(os.path.join(PROFILES_DIR, name, CONFIG_FILE), encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, config: dict, name: str | None = None) -> None:
        """Persist a profile's full settings dict."""
        name = sanitize(name) if name else self._active
        self._ensure_dir(name)
        _write_json(os.path.join(PROFILES_DIR, name, CONFIG_FILE), config)

    # -- per-profile log paths ---------------------------------------------
    def dir(self, name: str | None = None) -> str:
        """Absolute path to a profile directory (created if missing).

        ``_ensure_dir`` returns the *normalised name* (it is also used to resolve
        the active-profile name), so join it with ``PROFILES_DIR`` here to get an
        absolute path — otherwise the log files resolve relative to the launch cwd.
        """
        name = sanitize(name) if name else self._active
        name = self._ensure_dir(name)
        return os.path.join(PROFILES_DIR, name)

    def rally_log(self, name: str | None = None) -> str:
        return os.path.join(self.dir(name), RALLY_LOG)

    def rally_limits_json(self, name: str | None = None) -> str:
        """This profile's per-monster-type rally-join caps (panel/rally_limits.py)."""
        return os.path.join(self.dir(name), RALLY_LIMITS_CONFIG)

    def rally_counts_json(self, name: str | None = None) -> str:
        """Today's per-type rally-join count for this profile (resets daily)."""
        return os.path.join(self.dir(name), RALLY_COUNTS_STATE)

    def resource_stats_json(self, name: str | None = None) -> str:
        """This profile's day-keyed tally of resources gained (panel/resource_stats.py)."""
        return os.path.join(self.dir(name), RESOURCE_STATS_STATE)

    def leaderboard_db(self, name: str | None = None) -> str:
        """This profile's ranking-board history SQLite (tools/lib/leaderboard_store.py)."""
        return os.path.join(self.dir(name), LEADERBOARD_DB)

    def secret_log(self, name: str | None = None) -> str:
        return os.path.join(self.dir(name), SECRET_LOG)

    def tasks_json(self, name: str | None = None) -> str:
        """Where the secret-task capture checkpoints what it currently sees."""
        return os.path.join(self.dir(name), TASKS_JSON)

    def ghost_json(self, name: str | None = None) -> str:
        """Where the ghost-recon tile scan checkpoints the squads it can see."""
        return os.path.join(self.dir(name), GHOST_JSON)

    def treasures_json(self, name: str | None = None) -> str:
        """Where the treasure scan checkpoints the chests it can see."""
        return os.path.join(self.dir(name), TREASURES_JSON)

    def timers_json(self, name: str | None = None) -> str:
        """This profile's timer catalogue (panel/timers.py)."""
        return os.path.join(self.dir(name), TIMERS_CONFIG)

    def timers_state(self, name: str | None = None) -> str:
        """Last-run records of the scheduled errands (panel/timers.py)."""
        return os.path.join(self.dir(name), TIMERS_STATE)

    def triggers_json(self, name: str | None = None) -> str:
        """This profile's trigger catalogue (panel/triggers.py)."""
        return os.path.join(self.dir(name), TRIGGERS_CONFIG)

    def chat_log(self, name: str | None = None) -> str:
        """JSONL log of chat messages captured on the plain-TCP leg."""
        return os.path.join(self.dir(name), CHAT_LOG)

    def chat_db(self, char_uid: str | None = None, name: str | None = None) -> str:
        """SQLite store of chat history the panel pages through (chat_history.py).

        Chat history belongs to the CHARACTER, not the account: one account can hold
        several characters with different uids, and their chats must not mix. Each
        gets its own file `chat_history_<uid>.db`. ``char_uid`` is the current
        player's uid, read live from the game; without one (uid unknown) the legacy
        account-wide `chat_history.db` name is used as a fallback.
        """
        stem = f"chat_history_{_sanitize_uid(char_uid)}.db" if char_uid else CHAT_DB
        return os.path.join(self.dir(name), stem)

    def panel_log(self, name: str | None = None) -> str:
        """Plain-text mirror of everything shown in the panel log widget."""
        return os.path.join(self.dir(name), PANEL_LOG)

    def debug_log(self, name: str | None = None) -> str:
        """Rotating technical debug log for this profile (panel/debug_log.py)."""
        return os.path.join(self.dir(name), DEBUG_LOG)

    def heartbeat(self, name: str | None = None) -> str:
        """Where the open panel says it is still answering (panel/runtime/autostart.py)."""
        return os.path.join(self.dir(name), ALIVE_FILE)

    def autostart_state(self, name: str | None = None) -> str:
        """What the hourly check last made of that heartbeat."""
        return os.path.join(self.dir(name), AUTOSTART_STATE)

    def autostart_log(self, name: str | None = None) -> str:
        """Every launch the hourly check made, and what the panel printed on the way up."""
        return os.path.join(self.dir(name), AUTOSTART_LOG)

    # -- helpers ------------------------------------------------------------
    def _ensure_dir(self, name: str) -> str:
        """Create the profile directory; return the normalised profile *name*.

        Callers (``set_active``/``create``/``_read_active``) rely on getting the
        name back, so keep returning the name — :meth:`dir` builds the full path.
        """
        name = sanitize(name) or DEFAULT_PROFILE
        os.makedirs(os.path.join(PROFILES_DIR, name), exist_ok=True)
        return name


def _write_json(path: str, data) -> None:
    """Atomically write ``data`` as pretty JSON (best-effort)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass
