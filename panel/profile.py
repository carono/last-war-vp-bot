"""Named profiles + persistent settings for the control panel.

A *profile* is a named set of panel settings plus its own logs, stored under
``profiles/<name>/`` — in the PROJECT ROOT, beside ``panel/`` rather than inside it.
:mod:`panel.paths` owns that path and explains why there is exactly one directory
called ``profiles`` now (#1276); read it before moving anything::

    config.json             this profile's settings — see "the default is the base" below
    rally_log.jsonl         rally-monitor output for this profile
    secret_tasks_log.jsonl  secret-task findings for this profile
    timers.json             this profile's timers (what runs, how often, args)
    timers_last_run.json    when each scheduled errand last ran
    panel.log               plain-text mirror of the panel log widget

The active profile name lives in ``profiles/settings.json`` (global, profile-
independent), so the last-used profile is restored on the next launch. Switching
a profile just means reading a different ``config.json``; the panel re-applies
every setting from it.

WHAT WAS SOMEWHERE ELSE COMES ACROSS BY ITSELF, ONCE (#1276). A checkout that still
has the old ``panel/profiles/``, ``panel/settings.json``, the two templates beside them
or a language remembered in the operator's home directory has all of it brought into
``profiles/`` the next time anything builds a :class:`ProfileManager` — moved where the
filesystem allows a move, copied and marked where it does not, and never deleted behind
anybody's back. See :func:`migrate_legacy_layout`.

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
drifting apart, which is how one profile here ended up rebuilding NO tabs at all
(its own ``tabs.enabled`` had gone empty, and there was no shared base underneath
it to fall back to). A profile that DOES set its own value for a setting keeps
overriding the default with it, same as it always could.

A brand-new profile's ``config.json`` is written the moment its directory is —
empty (``{}``, "nothing overridden yet") rather than left to appear only after
the first Settings save. A profile directory that existed before this rule with
no file of its own is backfilled the same empty way the next time anything asks
for its directory, so ``profiles/`` never again shows a profile with no config
file to point at (part of #1246 too — several already had none).

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
from . import paths

# Re-exported rather than re-spelled: `panel/paths.py` is where these are decided, and
# the tests that redirect the store onto a scratch directory rebind them HERE, on this
# module, exactly as they always have.
PANEL_DIR = paths.PANEL_DIR
PROFILES_DIR = paths.PROFILES_DIR
SETTINGS_FILE = paths.SETTINGS_FILE

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
#: The «Призрак: карта» page's OWN list — what it has gathered from the tile capture and
#: kept, as opposed to what the capture currently sees (#1251). The capture fills; the
#: list is the panel's, survives a restart, and empties by its own rules.
GHOST_MAP_STATE = "ghost_map_state.json"
TREASURES_JSON = "world_treasures.json"
#: What the SECOND listener writes (#1289) — the mines off the same map responses, and
#: the player trucks and alliance trains off the march stream. One file with a list per
#: kind, rewritten every tick by the very same capture child that writes TASKS_JSON:
#: two npcap captures over one interface starve each other (044c19f), so the second
#: listener is an index inside the first one's process, never a second process.
WORLD_JSON = "world_map.json"
#: …and each world PAGE's own gathered list, the way GHOST_MAP_STATE is the ghost page's.
#: One file per page (`world_state_<page>.json`): the four hold different shapes, and
#: handing one page's checkpoint to another's reader is the mix-up the separate files
#: above already exist to prevent.
WORLD_STATE = "world_state_%s.json"
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


def migrate_legacy_layout() -> list[str]:
    """Bring an older checkout's state into ``profiles/``. Idempotent; never deletes.

    Four things used to live elsewhere, and every one of them is why somebody could copy
    the project folder and still be looking at the original's settings (#1276):

      * ``panel/profiles/<name>/`` — the profiles themselves;
      * ``panel/settings.json`` — which profile is showing, which are open, the channel;
      * ``panel/timers.json`` / ``panel/triggers.json`` — the two seed templates;
      * ``~/.last_war_panel.json`` — the language, the one file written outside the
        project altogether, which is what made a fresh copy come up in the original's
        language with no way to see why.

    A directory is MOVED when the destination is free and the filesystem allows it —
    then nothing is left behind to go stale. Windows will not move a tree it has a file
    open in (a running panel's ``debug.log``, a chat store), so the fallback is a copy
    that never overwrites a newer file, followed by :data:`paths.MIGRATION_MARKER` in
    the old directory so the next start does not put stale copies back over fresh ones.
    **Nothing is removed either way** — the old files stay on the disk for whoever wants
    to check them, they are simply no longer read.

    NOT RUN when the store has been redirected (a test's scratch directory, a bench):
    the legacy paths are absolute and real, and migrating this machine's actual profiles
    into a temporary folder is not a thing any caller ever wants.

    Returns what it moved, as short strings, for the log.
    """
    if PROFILES_DIR != paths.PROFILES_DIR or SETTINGS_FILE != paths.SETTINGS_FILE:
        return []
    moved: list[str] = []
    os.makedirs(PROFILES_DIR, exist_ok=True)
    moved += _migrate_profile_dirs()
    for src, dst, what in (
        (paths.LEGACY_SETTINGS_FILE, SETTINGS_FILE, "settings.json"),
        (paths.LEGACY_TIMERS_TEMPLATE, paths.TIMERS_TEMPLATE, "timers.json"),
        (paths.LEGACY_TRIGGERS_TEMPLATE, paths.TRIGGERS_TEMPLATE, "triggers.json"),
    ):
        if _move_file(src, dst):
            moved.append(what)
    if _migrate_language():
        moved.append("language")
    moved += _tidy_bot_profiles()
    return moved


def _tidy_bot_profiles() -> list[str]:
    """Flat ``profiles/<id>.json`` files → ``profiles/_bot/``.

    The DSL bot moves its own when it next loads one, but it may not be run for months
    and the whole point of this directory is that opening it answers the question. A
    loose json beside the profile folders is the confusion in miniature, so the panel
    sweeps it down on its way past. Only files it can identify: the three panel-wide
    ones by name, and nothing else that is not a plain ``.json``.
    """
    ours = {os.path.basename(SETTINGS_FILE), os.path.basename(paths.TIMERS_TEMPLATE),
            os.path.basename(paths.TRIGGERS_TEMPLATE)}
    moved: list[str] = []
    try:
        entries = sorted(os.listdir(PROFILES_DIR))
    except OSError:
        return moved
    for entry in entries:
        if not entry.endswith(".json") or entry in ours:
            continue
        src = os.path.join(PROFILES_DIR, entry)
        if not os.path.isfile(src):
            continue
        if _move_file(src, os.path.join(paths.BOT_PROFILES_DIR, entry)):
            moved.append(f"_bot/{entry}")
    return moved


def _migrate_profile_dirs() -> list[str]:
    """``panel/profiles/<name>/`` → ``profiles/<name>/``, one profile at a time."""
    legacy = paths.LEGACY_PROFILES_DIR
    if legacy == PROFILES_DIR or not os.path.isdir(legacy):
        return []
    if os.path.exists(os.path.join(legacy, paths.MIGRATION_MARKER)):
        return []                       # already brought across by an earlier start
    import shutil
    moved: list[str] = []
    #: Profiles the new place already had, and ones that could not be brought across at
    #: all. Both used to be `continue` and nothing else — see the comments below.
    skipped: list[str] = []
    failed: list[str] = []
    copied = False
    for name in sorted(os.listdir(legacy)):
        src = os.path.join(legacy, name)
        if not os.path.isdir(src) or not paths.is_profile_name(name):
            continue
        dst = os.path.join(PROFILES_DIR, name)
        if os.path.isdir(dst):
            # BOTH PLACES HOLD THIS PROFILE, and neither is safe to overwrite. It used
            # to be a bare `continue` — the quietest line in the file and the most
            # expensive. On this machine `profiles/default/` existed before the move
            # (the DSL bot's own directory of the same name), so the panel's `default`
            # was skipped whole and a run that looked ordinary started a brand-new
            # empty profile beside a full one. Weeks of a ranking history went that way
            # and there is no copy of it anywhere: the file was never deleted, it was
            # simply never read again (#1304).
            #
            # The files are still not touched — the right answer for two directories
            # that may both hold real data is to move neither — but the skip is now
            # SAID, out loud, in the return value the caller logs and in the marker
            # left in the old directory. A collision somebody is told about is a thing
            # they can sort out; a collision nobody is told about is a quiet loss.
            skipped.append(name)
            continue
        try:
            shutil.move(src, dst)
        except OSError as exc:
            # Something holds a file open in there. Copy what can be copied — a profile
            # half-brought-across is still better than a profile the panel cannot see —
            # and mark the old directory so the next start does not do it again.
            try:
                shutil.copytree(src, dst, dirs_exist_ok=True)
            except OSError as copy_exc:
                # Neither worked. Also never silent: this is a profile the panel is
                # about to carry on without, and the reason is the only clue there is.
                failed.append(f"{name} ({copy_exc or exc})")
                continue
            copied = True
        moved.append(name)
    if copied or skipped or failed:
        # A marker whenever anything was left behind, not only after a copy: the old
        # directory is the one place a person looking for the missing profile will
        # actually open, so it is where the reason has to be written.
        _write_marker(legacy, skipped, failed)
    elif moved and not [n for n in os.listdir(legacy) if paths.is_profile_name(n)]:
        # Everything moved cleanly and nothing of a profile is left: the empty shell can
        # go, and that is a directory removal, not a data one.
        try:
            os.rmdir(legacy)
        except OSError:
            pass
    # The skips and the failures travel with the moves, so the caller's log says «two
    # brought across, one left where it was and here is why» rather than «two».
    return (moved + [f"{name}: left in {legacy} — a profile of that name was already "
                     f"in {PROFILES_DIR}, and neither was overwritten"
                     for name in skipped]
            + [f"{name}: could not be brought across" for name in failed])


def _write_marker(legacy: str, skipped=(), failed=()) -> None:
    """Say, in the old directory, where its contents went and what stayed put."""
    try:
        with open(os.path.join(legacy, paths.MIGRATION_MARKER), "w",
                  encoding="utf-8") as fh:
            fh.write(
                "The panel keeps its profiles in <project>/profiles/ now (#1276).\n"
                "What was here has been copied there; nothing was deleted. This file\n"
                "stops a later start from copying these older files back over newer\n"
                "ones. Delete this whole directory once you are satisfied the panel\n"
                "shows what you expect.\n")
            if skipped:
                fh.write(
                    "\nNOT brought across, because the new place already had a profile\n"
                    "of the same name and overwriting either one would lose data. The\n"
                    "panel is reading the NEW one; what is here is untouched:\n"
                    + "".join(f"  - {name}\n" for name in skipped))
            if failed:
                fh.write(
                    "\nCould not be brought across at all — the reason is in brackets.\n"
                    "These are still only here:\n"
                    + "".join(f"  - {name}\n" for name in failed))
    except OSError:
        pass


def _move_file(src: str, dst: str) -> bool:
    """Move one file across, unless the destination already has one."""
    if src == dst or not os.path.isfile(src) or os.path.exists(dst):
        return False
    import shutil
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
    except OSError:
        return False
    return True


def _migrate_language() -> bool:
    """The language out of ``~/.last_war_panel.json`` and into ``settings.json``.

    Copied, not moved: the old file is in the operator's HOME, shared by every checkout
    on the machine, so an older copy of the panel elsewhere keeps working off it.
    """
    data = ProfileManager._read_settings()
    if "language" in data:
        return False
    try:
        with open(paths.LEGACY_LANG_FILE, encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return False
    # The old file's key was `lang`; the settings file calls it `language`, the same
    # name a profile's own config uses for the same choice.
    lang = (old or {}).get("lang") if isinstance(old, dict) else None
    if not isinstance(lang, str) or not lang.strip():
        return False
    data["language"] = lang.strip()
    _write_json(SETTINGS_FILE, data)
    return True


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
        # Before anything is listed or seeded: an older checkout's state is somewhere
        # else, and a panel that seeded a fresh default profile first would look for all
        # the world like the settings had been lost (#1276).
        migrate_legacy_layout()
        # A fresh install has no profiles — seed the default so the UI always
        # has something to select.
        if not self.list():
            self._ensure_dir(DEFAULT_PROFILE)
        # THE BACKFILL THAT USED TO BE HERE IS GONE (#1306). It wrote an empty
        # `config.json` into every listed profile that had none, so that `profiles/`
        # never showed a profile with no config file to point at (#1246). Under the
        # rule in `list()` that loop can no longer do anything — a directory without a
        # config is not listed — and worse, run over the DIRECTORIES instead it would
        # turn every stray folder into a real account, which is the exact bug this
        # change exists to fix. The invariant it was defending is now the definition:
        # everything `list()` returns has a config because having one is what put it
        # there. What has a directory and no config is said out loud (`strays`).
        self.pinned = bool(sanitize(pin or ""))
        self._active = self._ensure_dir(pin) if self.pinned else self._read_active()

    # -- profile enumeration ------------------------------------------------
    def list(self) -> list[str]:
        """Existing profile names, sorted (the default first if present).

        **A PROFILE IS A DIRECTORY WITH A `config.json` IN IT** (#1306), not any
        directory that happens to sit in ``profiles/``. That answers the question
        «what makes a profile a profile» once, and it stays right whatever else ends up
        beside them — which the old rule did not: the squads report writes its faces
        into ``profiles/<report>_avatars/``, and the panel duly believed there was an
        account of that name and reported it as a co-owner of the default profile's
        daemon. Reserving that one name would have fixed that one folder; this fixes
        the class.

        The machinery is excluded first and separately (:func:`paths.is_profile_name`):
        the DSL bot's ``_bot/``, anything dot-prefixed. A folder that passes THAT and
        still has no config is not silently dropped — :meth:`strays` is what the panel
        says out loud about it, because «skipped quietly» and «there was nothing there»
        are the same two states this repository keeps having to tell apart.
        """
        return sorted(self._dirs(with_config=True),
                      key=lambda n: (n != DEFAULT_PROFILE, n.lower()))

    def strays(self) -> list[str]:
        """Directories that look like a profile and have no ``config.json``. Sorted.

        Two quite different things end up here and the panel says the same sentence
        about both, because from the outside they ARE the same thing — a folder in
        ``profiles/`` that the panel is not treating as an account:

        * something that is not a profile at all (a report's pictures, a stray copy);
        * a real profile whose config was lost or never written, which under the rule
          above has just become invisible. That one MUST be said: a person who put it
          there is otherwise left looking for a profile the panel will never mention.
        """
        return sorted(self._dirs(with_config=False), key=str.lower)

    def _dirs(self, *, with_config: bool) -> list[str]:
        """Directory names in ``profiles/`` that pass the name rule, split by config."""
        try:
            entries = os.listdir(PROFILES_DIR)
        except OSError:
            return []
        out = []
        for name in entries:
            path = os.path.join(PROFILES_DIR, name)
            if not (paths.is_profile_name(name) and os.path.isdir(path)):
                continue
            if os.path.exists(os.path.join(path, CONFIG_FILE)) is with_config:
                out.append(name)
        return out

    def exists(self, name: str) -> bool:
        name = sanitize(name)
        return (bool(name) and paths.is_profile_name(name)
                and os.path.isfile(os.path.join(PROFILES_DIR, name, CONFIG_FILE)))

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
        _refuse_reserved(name)
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
        _refuse_reserved(new)
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

    def ghost_map_state_json(self, name: str | None = None) -> str:
        """Where the «Призрак: карта» page checkpoints its OWN list (#1251).

        Not the same file as `ghost_json`: that one is what the capture currently sees
        and is rewritten every tick, while this is what the page has gathered and is
        keeping — the distinction the whole «мониторинг только наполняет» rule is about.
        """
        return os.path.join(self.dir(name), GHOST_MAP_STATE)

    def world_json(self, name: str | None = None) -> str:
        """Where the world listener checkpoints the mines, trucks and trains (#1289).

        Written by the SAME capture child as `tasks_json`, because the wire may only be
        read once per client — see `tools/lib/world_index.py`.
        """
        return os.path.join(self.dir(name), WORLD_JSON)

    def world_state_json(self, page: str, name: str | None = None) -> str:
        """Where ONE world page checkpoints its OWN gathered list (#1289).

        `page` is the grid's `CONFIG_KEY` — «mines», «monsters», «trains», «trucks».
        """
        return os.path.join(self.dir(name), WORLD_STATE % page)

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


# -- the update channel: panel-wide, and deliberately not a profile's (#1274) ----
#
# WHY IT IS NOT A PROFILE SETTING. There is ONE checkout, and every profile in the
# window runs out of it. Two profiles that disagreed about whether to follow releases or
# the branch tip would be two answers to a question with one subject, and the first
# press would settle it for both of them without saying so. So it sits in the panel-wide
# file beside `active_profile` and `open_profiles` — the other two facts about the
# window rather than about an account.
#
# WHY THESE ARE MODULE FUNCTIONS AND NOT METHODS. A `ProfileManager` held by an open
# session is PINNED and refuses to write this file, because the two keys already in it
# are the workspace's to write and a session must not fight over them. This key has no
# such conflict — whichever session ticks the box means the same thing by it — so it is
# read and written without a manager at all, by the tab that draws the tick and by the
# shell that acts on it.

#: The key in `panel/settings.json`. Absent means «releases», which is the default a
#: panel that has never heard of the tick behaves by.
DEV_UPDATES_KEY = "dev_updates"


def dev_updates() -> bool:
    """Is this panel following the BRANCH TIP rather than the newest release?"""
    return bool(ProfileManager._read_settings().get(DEV_UPDATES_KEY, False))


def set_dev_updates(flag: bool) -> None:
    """Remember the answer for the whole panel. Written even when nothing else is."""
    data = ProfileManager._read_settings()
    flag = bool(flag)
    if bool(data.get(DEV_UPDATES_KEY, False)) == flag:
        return
    data[DEV_UPDATES_KEY] = flag
    _write_json(SETTINGS_FILE, data)


# -- the remote control: panel-wide too, for the same reason (#1313) -------------
#
# The web front-end is ONE SERVER PER WINDOW answering for every profile that window has
# open (`panel/web/api.py`), so the port it binds, the token it accepts and the
# certificate it serves are facts about the MACHINE and not about an account — the first
# of the two questions `CLAUDE.md` makes every value answer. They were a profile's knobs
# while they lived on a tab, which meant a window with three accounts open held three
# copies of one answer and obeyed whichever profile happened to switch on first.
#
# So the block moved here, beside `active_profile` and `open_profiles`, and the tab it
# used to live on became a menu entry: `panel/runtime/web_control.py` reads and writes
# it, `panel/runtime/web_dialog.py` draws it.

#: The key in `profiles/settings.json`. A dict of the six knobs; absent means the block
#: has never been written and :func:`migrate_web_settings` has not run yet.
WEB_KEY = "web"

#: What a profile's copy of it used to be called, inside that profile's `config.json`.
#: Read once, by the migration, and by nothing else.
LEGACY_WEB_TAB = "web"


def web_settings() -> dict:
    """The panel's remote-control knobs — ``{}`` when nobody has set any.

    Nothing is defaulted here: what an unset port or an unset host MEAN belongs to
    `panel/runtime/web_control.py`, which is also the only thing that starts a server.
    """
    block = ProfileManager._read_settings().get(WEB_KEY)
    return dict(block) if isinstance(block, dict) else {}


def set_web_settings(values: dict) -> None:
    """Remember them for the whole panel. Written even when nothing else is."""
    data = ProfileManager._read_settings()
    block = dict(values or {})
    if data.get(WEB_KEY) == block:
        return
    data[WEB_KEY] = block
    _write_json(SETTINGS_FILE, data)


def migrate_web_settings() -> "str | None":
    """Bring the «Веб» knobs out of the profiles and into the panel-wide file. Once.

    Returns the profile the answer was taken FROM (so the caller can say so in the log),
    or ``None`` when there was nothing to bring across — a fresh install, or a panel
    that has already migrated.

    WHICH PROFILE WINS, when several kept their own copy: the one that had the switch
    ON, because that is the port and the token a phone is holding right now; the first
    with a token if none is on, so a link that was set up and switched off still works
    when it is switched back on; the first block there is otherwise. Ties go to the
    default profile, which is read first — it is the base every other profile layers
    onto, so it is also the likeliest to be the one somebody configured.

    AND THE LEFTOVERS ARE SWEPT UP. The id `web` is taken out of each profile's
    `tabs.enabled` / `tabs.known` / `tabs.order` and its `tabs.config.web` block is
    dropped — otherwise every start would log «this profile names a tab that no longer
    exists» once per profile, for ever, about a tab nobody removed on purpose.
    """
    # ASKED FIRST, and cheaply: this is called on every read of the setting, and after
    # the first start the answer is one small JSON file rather than a walk of every
    # profile on disk. The KEY, not its value — an empty block is the recorded answer
    # «there was nothing to bring across», and re-running would only re-read the same
    # empty profiles.
    if WEB_KEY in ProfileManager._read_settings():
        return None
    manager = ProfileManager()
    best, best_rank, source = None, -1, None
    names = manager.list()
    ordered = ([DEFAULT_PROFILE] if DEFAULT_PROFILE in names else []) + \
              [n for n in names if n != DEFAULT_PROFILE]
    for name in ordered:
        own = manager._load_own(name)
        block = (own.get("tabs") or {}).get("config", {}).get(LEGACY_WEB_TAB)
        if not isinstance(block, dict) or not block:
            continue
        rank = 2 if block.get("enabled") else (1 if str(block.get("token") or "") else 0)
        if rank > best_rank:
            best, best_rank, source = dict(block), rank, name
    set_web_settings(best or {})
    for name in ordered:
        _sweep_web_leftovers(manager, name)
    return source


def _sweep_web_leftovers(manager: "ProfileManager", name: str) -> None:
    """Take the retired tab id out of one profile's OWN file. Writes only if it was there.

    The profile's own file, unmerged: a non-default profile that never had a copy of its
    own must not grow one here, and `save()` would have written the merged answer back
    as an override.
    """
    own = manager._load_own(name)
    tabs = own.get("tabs")
    if not isinstance(tabs, dict):
        return
    changed = False
    for key in ("enabled", "known", "order"):
        listed = tabs.get(key)
        if isinstance(listed, list) and LEGACY_WEB_TAB in listed:
            tabs[key] = [t for t in listed if t != LEGACY_WEB_TAB]
            changed = True
    config = tabs.get("config")
    if isinstance(config, dict) and LEGACY_WEB_TAB in config:
        del config[LEGACY_WEB_TAB]
        changed = True
    if changed:
        _write_json(os.path.join(PROFILES_DIR, name, CONFIG_FILE), own)


def update_channel() -> str:
    """The channel name `panel/runtime/updates.py` speaks — `"dev"` or `"release"`.

    Here rather than in the runtime so that the STORED answer and the two constants meet
    in one place: a caller asks this and passes the result on, and nothing else has to
    know that the preference is a boolean on disk.
    """
    from .runtime import updates as updatesmod
    return updatesmod.DEV if dev_updates() else updatesmod.RELEASE


def _refuse_reserved(name: str) -> None:
    """Refuse a name ``profiles/`` already uses for its own machinery.

    A profile called ``_bot`` would land on top of the DSL bot's own profiles, and the
    two would then take turns overwriting each other silently — the failure mode this
    whole directory was consolidated to end (#1276).
    """
    if not paths.is_profile_name(name):
        raise ValueError(Message("profile.error.reserved",
                                 f"this name is reserved: {name}", name=name))


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
