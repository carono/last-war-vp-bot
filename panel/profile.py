"""Named profiles + persistent settings for the control panel.

A *profile* is a named set of panel settings plus its own logs, stored under
``panel/profiles/<name>/``::

    config.json             this profile's settings — see "the default is the base" below
    rally_log.jsonl         rally-monitor output for this profile
    secret_tasks_log.jsonl  secret-task findings for this profile
    timers.json             this profile's timers (what runs, how often, args)
    timers_last_run.json    when each scheduled errand last ran
    panel.log               plain-text mirror of the panel log widget

The active profile name lives in ``panel/settings.json`` (global, profile-
independent), so the last-used profile is restored on the next launch. Switching
a profile just means reading a different ``config.json``; the panel re-applies
every setting from it.

THE DEFAULT PROFILE IS THE BASE, EVERY OTHER ONE IS ITS OVERRIDES (#1246). A
profile named anything but :data:`DEFAULT_PROFILE` stores on disk only the
settings that differ from the default profile's own ``config.json`` — :meth:`load`
layers those overrides onto the default's config, and :meth:`save` throws away
whatever a profile would have written unchanged from it. The default profile's
file has no parent and is read and written whole, exactly as before.

This is what makes a knob "central": switching a tab on or off, or changing any
other setting, in the DEFAULT profile's own Settings page reaches every profile
that never touched that setting itself the next time it starts — instead of every
profile carrying its own full copy of the same fifteen tab ids and silently
drifting apart, which is how profile "casper" ended up rebuilding NO tabs at all
(its own ``tabs.enabled`` had gone empty, and there was no shared base underneath
it to fall back to). A profile that DOES set its own value for a setting keeps
overriding the default with it, same as it always could.

A brand-new profile's ``config.json`` is written the moment its directory is —
empty (``{}``, "nothing overridden yet") rather than left to appear only after
the first Settings save. A profile directory that existed before this rule with
no file of its own is backfilled the same empty way the next time anything asks
for its directory, so ``panel/profiles/`` never again shows a profile with no
config file to point at (part of #1246 too — several already had none).

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
# The «Секретки» tab's OWN session list — the starred tiles it is showing, each with the
# countdown fields a restart needs to pick up where it left off (#1242). Not the same
# thing as TASKS_JSON above: that is the capture's raw scan of everything on the map,
# this is the tab's own filtered, deduplicated list. Rewritten whole on every change the
# tab makes to its rows, so the list is never more than one merge behind what is on
# screen; read back once, on the tab's next `on_show`, and verified against a live game
# read before any of it is trusted (panel/tabs/secret_tasks/tab.py).
SECRET_TASKS_STATE = "secret_tasks_state.json"
# Which secret tasks have already been forwarded to the alliance (#1245). Append-only,
# because three separate processes write it — the panel, when its own «Поделиться»
# lands, and the two capture children, when the game announces a share somebody made in
# the client. One line per share; `tools/lib/share_marks.py` owns the shape, ages the
# marks out and compacts the file.
SECRET_SHARED = "secret_shared.jsonl"
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
# The instance lock: an open file the panel holds an exclusive OS lock on for its whole
# life, so "a panel is on this profile" is answered by the kernel and cannot go stale —
# the lock dies with the process whatever killed it. Its contents are the pid, for
# somebody reading the folder; the LOCK is the part that means anything.
LOCK_FILE = "panel.lock"
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


#: Marks a diff entry as a WHOLE value rather than a partial patch — see
#: :func:`_deep_diff`'s docstring for why a partial patch is not always possible.
#: Distinctive on purpose: a real setting named this would be a stranger coincidence
#: than the bug this guards against.
_WHOLE_KEY = "__lw_profile_whole_value__"


def _deep_merge(base: dict, override: dict) -> dict:
    """Layer ``override`` onto ``base``: a nested dict merges key by key, anything
    else — a list, a string, a number, ``None`` — in ``override`` replaces the base
    value outright rather than combining with it (a tab list is a whole choice, not
    something to concatenate). ``base`` and ``override`` are left untouched.

    A dict wrapped in :data:`_WHOLE_KEY` by :func:`_deep_diff` is unwrapped and used
    whole, not merged — it is there precisely because merging it WOULD be wrong.
    """
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and _WHOLE_KEY in value:
            out[key] = value[_WHOLE_KEY]
            continue
        base_value = out.get(key)
        if isinstance(value, dict) and isinstance(base_value, dict):
            out[key] = _deep_merge(base_value, value)
        else:
            out[key] = value
    return out


def _deep_diff(full: dict, base: dict) -> dict:
    """The inverse of :func:`_deep_merge`: what of ``full`` is not already implied by
    ``base``. A key equal to the base's own value — recursively, for a nested dict —
    is dropped, so saving a profile that never touched a setting does not start
    carrying the default's value for it forever.

    Recursing into a nested dict as a PARTIAL patch is only correct when ``full``'s
    side carries every key ``base``'s side does — then whatever gets dropped is
    provably a key equal to the base's own, and merging the two back together
    reconstructs ``full`` exactly. A ``full`` whose dict is missing a key the base's
    has (an old profile saved before the base gained a field, or a block a newer
    default widened) cannot be diffed partially: :func:`_deep_merge` cannot tell "the
    profile never had this key" from "the profile did not change it", so a plain
    partial dict here would have the base's extra key silently reappear on load. That
    subtree is wrapped as a WHOLE value instead (:data:`_WHOLE_KEY`) — bigger on disk
    for that one profile than a clean partial diff would be, but exact.
    """
    out = {}
    for key, value in full.items():
        base_value = base.get(key)
        if isinstance(value, dict) and isinstance(base_value, dict):
            if set(base_value) <= set(value):
                sub = _deep_diff(value, base_value)
                if sub:
                    out[key] = sub
            elif value != base_value:
                out[key] = {_WHOLE_KEY: value}
        elif key not in base or value != base_value:
            out[key] = value
    return out


class ProfileManager:
    """On-disk store of named profiles and the active-profile pointer.

    ``pin`` makes this manager *be* one named profile instead of following the panel's
    saved pointer: `active` is that profile, and :meth:`set_active` moves this manager
    alone and writes nothing to the shared `panel/settings.json`.

    That is what lets one window hold several profiles open at once (#1206). Without it
    every runtime built in the process shares one answer to "which profile is this",
    and the second one to be built silently redefines the first. Unpinned — the default
    — is the panel's own manager and behaves exactly as it always has.
    """

    def __init__(self, pin: str | None = None) -> None:
        os.makedirs(PROFILES_DIR, exist_ok=True)
        # A fresh install has no profiles — seed the default so the UI always
        # has something to select.
        if not self.list():
            self._ensure_dir(DEFAULT_PROFILE)
        else:
            # Backfill config.json for any profile that predates this rule — so
            # `panel/profiles/` never shows a profile with no config file of its own,
            # right from the next time anything so much as opens the panel (#1246),
            # rather than only once that particular profile is next touched.
            for existing in self.list():
                self._ensure_dir(existing)
        self.pinned = bool(sanitize(pin or ""))
        self._active = self._ensure_dir(pin) if self.pinned else self._read_active()

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

    # -- the panel-wide file (panel/settings.json) --------------------------
    #
    # Two facts live here, both about the PANEL rather than about any one profile:
    # which profile's page is on screen (`active_profile`) and which profiles are open
    # beside it (`open_profiles`). A pinned manager speaks for one open profile and
    # writes neither — see the class docstring.
    @staticmethod
    def _read_settings() -> dict:
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_setting(self, key: str, value) -> None:
        self._write_settings({key: value})

    def _write_settings(self, values: dict) -> None:
        """Merge ``values`` into the panel-wide file — ONE read and ONE write.

        A profile switch used to write this file twice, once per key, on the Tk thread
        with the operator waiting on the click (#1211).
        """
        data = self._read_settings()
        if all(data.get(k) == v for k, v in values.items()):
            return                      # nothing to say: do not touch the disk
        data.update(values)
        _write_json(SETTINGS_FILE, data)

    def _read_active(self) -> str:
        name = self._read_settings().get("active_profile", DEFAULT_PROFILE)
        if not self.exists(name):
            names = self.list()
            name = names[0] if names else self._ensure_dir(DEFAULT_PROFILE)
        return name

    def set_active(self, name: str, *, write: bool = True) -> str:
        """Point the panel at ``name`` (creating it if missing) and persist it.

        A PINNED manager moves itself and stops there: it speaks for one open profile,
        not for the panel, and the shared pointer is the workspace's to write.

        ``write=False`` moves the pointer without touching the file — for a caller that
        is about to write it anyway, in the same breath as the open-profile list
        (:meth:`set_open_profiles`). One file write per switch, not two (#1211).
        """
        name = self._ensure_dir(name) if not self.exists(name) else sanitize(name)
        self._active = name
        if self.pinned or not write:
            return name
        self._write_setting("active_profile", name)
        return name

    def open_profiles(self) -> list[str]:
        """Which profiles the panel had open last time, the on-screen one first.

        Names that no longer exist are dropped — a profile deleted between two runs
        must not be re-opened, and an empty answer means "just the active one", which
        is every panel there has ever been before this (#1206).
        """
        raw = self._read_settings().get("open_profiles")
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            name = sanitize(str(item))
            if name and self.exists(name) and name not in out:
                out.append(name)
        return out

    def set_open_profiles(self, names, active: str | None = None) -> None:
        """Remember which profiles are open — and, in the same write, which is showing.

        ``active`` is the pointer :meth:`set_active` writes; passing it here is what
        makes a profile switch one file write instead of two.
        """
        if self.pinned:
            return
        seen: list[str] = []
        for item in names or ():
            name = sanitize(str(item))
            if name and name not in seen:
                seen.append(name)
        values = {"open_profiles": seen}
        if active:
            values["active_profile"] = sanitize(active)
        self._write_settings(values)

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

        **IT SAYS SO WHEN THE DIRECTORY DOES NOT GO** (#1253). This used to be one
        `rmtree(..., ignore_errors=True)` and nothing else, and on Windows that is a
        delete that reports success without having happened: a file something still
        holds open cannot be unlinked — a `panel.log`, a `debug.log`, a capture's
        checkpoint, the SQLite chat store — and every one of those is held by the very
        session the person is deleting. The profile then came back in the list, kept its
        settings, and the only clue was that nothing had changed.

        So: try, look, and try again saying why. The second attempt is not superstition
        — the first one deletes everything it can, and a handle released in between (a
        child process ending, a log handler closing) makes the retry succeed. Only when
        the directory is still there afterwards is this a refusal, and then the active
        pointer has not been moved: a profile that is still on the disk must not have
        been quietly stood down.
        """
        name = sanitize(name)
        if not self.exists(name):
            raise ValueError(Message("profile.error.missing",
                                     f"no such profile: {name}", name=name))
        if len(self.list()) <= 1:
            raise ValueError(Message("profile.error.last_one",
                                     "cannot delete the last profile"))
        import shutil
        path = os.path.join(PROFILES_DIR, name)
        shutil.rmtree(path, ignore_errors=True)
        refused = None
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
            except OSError as exc:
                refused = exc
        if os.path.isdir(path):
            # `error` is technical on purpose — the reason Windows gave, or, when it
            # gave none, WHAT SURVIVED. Either one names the thing still holding the
            # directory; a translated «could not delete» would not.
            said = refused if refused is not None else _leftovers(path)
            raise ValueError(Message(
                "profile.error.not_removed",
                f"the profile directory could not be removed: {said}",
                name=name, path=path, error=said))
        if self._active == name:
            return self.set_active(self.list()[0])
        return self._active

    # -- config read / write ------------------------------------------------
    def _load_own(self, name: str) -> dict:
        """This profile's OWN file, unmerged — ``{}`` if it has none yet."""
        try:
            with open(os.path.join(PROFILES_DIR, name, CONFIG_FILE), encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _default_base(self, name: str) -> dict:
        """The default profile's own config, unless ``name`` already IS the default —
        which has no base underneath it (module docstring)."""
        if name == DEFAULT_PROFILE or not self.exists(DEFAULT_PROFILE):
            return {}
        return self._load_own(DEFAULT_PROFILE)

    def load(self, name: str | None = None) -> dict:
        """A profile's EFFECTIVE settings: its own overrides layered on the default
        profile's config (``{}`` for the default itself, or if there is no default
        profile at all — a profile has no base to fall back to then, not a crash)."""
        name = sanitize(name) if name else self._active
        own = self._load_own(name)
        base = self._default_base(name)
        return _deep_merge(base, own) if base else own

    def save(self, config: dict, name: str | None = None) -> None:
        """Persist a profile's settings.

        The default profile stores ``config`` whole — it IS the base. Any other
        profile stores only what of ``config`` differs from the default profile's own
        file, so a knob left untouched here starts following the default from now on
        instead of freezing at whatever it happened to equal at the last save.
        """
        name = sanitize(name) if name else self._active
        self._ensure_dir(name)
        own = config if name == DEFAULT_PROFILE else _deep_diff(config, self._default_base(name))
        _write_json(os.path.join(PROFILES_DIR, name, CONFIG_FILE), own)

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

    def secret_tasks_state_json(self, name: str | None = None) -> str:
        """Where the «Секретки» tab checkpoints its own session list (#1242)."""
        return os.path.join(self.dir(name), SECRET_TASKS_STATE)

    def secret_shared_json(self, name: str | None = None) -> str:
        """Which secret tasks have already been shared with the alliance (#1245).

        Written by the panel and by the capture children alike, so the mark on a row is
        the same whether the share was made from here or pressed in the game itself.
        """
        return os.path.join(self.dir(name), SECRET_SHARED)

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

    def lock_file(self, name: str | None = None) -> str:
        """The file whose OS lock means «a panel process holds this profile»."""
        return os.path.join(self.dir(name), LOCK_FILE)

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

        Also backfills ``config.json`` with an empty ``{}`` when the profile has none
        yet — a brand-new profile as much as one from before this rule existed — so a
        profile in ``panel/profiles/`` always has a config file to point at rather
        than one that only appears after its first Settings save (#1246). Empty means
        "nothing overridden": read through :meth:`load` it is exactly the default
        profile's own config, or the code's constants for the default profile itself.
        """
        name = sanitize(name) or DEFAULT_PROFILE
        path = os.path.join(PROFILES_DIR, name)
        os.makedirs(path, exist_ok=True)
        config_path = os.path.join(path, CONFIG_FILE)
        if not os.path.exists(config_path):
            _write_json(config_path, {})
        return name


def _leftovers(path: str, most: int = 5) -> str:
    """What is still in a directory that would not delete — the useful half of «why».

    Names, not a count: `chat_history_<uid>.db` says a chat window is still open and
    `panel.log` says the session was not closed first, and those are different faults
    with different fixes (#1253).
    """
    try:
        names = sorted(os.listdir(path))
    except OSError as exc:
        return str(exc)
    shown = ", ".join(names[:most])
    return f"{shown}, …" if len(names) > most else shown or path


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
