r"""Where the panel keeps its things: ONE directory, inside the project, and nowhere else.

This is the test for #1276, and #1276 is a question that had to be asked three times.
The person copied the project folder, opened the panel, and saw the original's settings
staring back at them while the ``profiles/`` they were looking at held one stale file
from months earlier. Both halves of that were true at once:

* the panel's real state was in ``panel/profiles/`` — a SECOND directory with the same
  name, one level down, that nobody thinks to open;
* the root ``profiles/`` belonged to the DSL bot's ``--profile`` flag, addressed
  relative to the working directory, and had nothing of the panel's in it;
* and the language was in ``~/.last_war_panel.json``, outside the project altogether —
  the one thing a folder copy genuinely could not bring with it or leave behind.

So what is pinned here:

* **One directory, and it is the project's.** ``profiles/`` sits beside ``panel/``, and
  every path the panel writes is under it — no home directory, no ``%APPDATA%``, no
  temporary directory, no absolute path spelled into the code.
* **Nothing writes its own answer.** Five modules used to build their own
  ``os.path.join(PANEL_DIR, …)``; they all read `panel/paths.py` now, so the store can
  never again mean two different places in one process.
* **The machinery is not an account.** ``profiles/_bot/`` holds the DSL bot's profiles
  and must not appear in the panel's profile list, nor be creatable as a profile.
* **An old checkout comes across by itself, and loses nothing.** Profiles, the panel-wide
  settings, both templates and the language, moved once, never overwriting anything
  newer, never deleting anything.

Runs anywhere — it imports `panel.profile`, `panel.paths` and `panel.i18n`, none of
which need tkinter.

    python3 tests/test_panel_storage.py
    C:\Python312\python.exe tests\test_panel_storage.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from panel import paths, profile as profilemod          # noqa: E402
from panel import i18n as i18nmod                       # noqa: E402

REPO = Path(__file__).resolve().parents[1]


# -- the layout itself ---------------------------------------------------------------

def test_everything_is_inside_the_project():
    """Every path the panel keeps state at is under ``<project>/profiles/``."""
    assert Path(paths.PROJECT_DIR) == REPO, paths.PROJECT_DIR
    assert Path(paths.PROFILES_DIR) == REPO / "profiles", paths.PROFILES_DIR
    for name in ("SETTINGS_FILE", "TIMERS_TEMPLATE", "TRIGGERS_TEMPLATE",
                 "FALLBACK_DEBUG_LOG", "BOT_PROFILES_DIR"):
        path = Path(getattr(paths, name))
        assert paths.PROFILES_DIR in str(path.parents[0]) or path.parent == Path(
            paths.PROFILES_DIR), f"{name} is outside profiles/: {path}"


def test_no_module_spells_out_its_own_store():
    """The five modules that used to build their own path read `panel/paths.py`.

    Checked as text on purpose: the values agreeing today says nothing about the next
    edit, and every one of these drifted apart exactly by somebody adding one more
    `os.path.join(PANEL_DIR, "something.json")` next to the others.
    """
    culprits = []
    pattern = re.compile(r"""os\.path\.join\(\s*PANEL_DIR\s*,\s*["']""")
    home = re.compile(r"""expanduser\(\s*["']~""")
    for path in sorted((REPO / "panel").rglob("*.py")):
        if path.name == "paths.py" or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        # Comments and docstrings may say anything; only code that BUILDS a path counts.
        for line in text.splitlines():
            code = line.split("#", 1)[0]
            if code.lstrip().startswith(("*", '"""', "'''", ":")):
                continue
            if pattern.search(code) or home.search(code):
                culprits.append(f"{path.relative_to(REPO)}: {line.strip()}")
    assert not culprits, "state path built outside panel/paths.py:\n  " + \
                         "\n  ".join(culprits)


def test_language_is_a_key_in_the_settings_file():
    """The language lives with the other panel-wide facts, not in the operator's home."""
    assert Path(i18nmod._PREF_FILE) == Path(paths.SETTINGS_FILE)


def test_bot_profiles_are_under_the_panel_directory_and_absolute():
    """The DSL bot's own profiles: inside ``profiles/``, and NOT relative to the cwd."""
    from lastwar_bot.profile import DEFAULT_PROFILES_DIR
    assert DEFAULT_PROFILES_DIR.is_absolute(), DEFAULT_PROFILES_DIR
    assert DEFAULT_PROFILES_DIR == REPO / "profiles" / "_bot", DEFAULT_PROFILES_DIR


def test_machinery_is_not_a_profile():
    """``_bot`` and dot-directories are not accounts, and cannot be made into one."""
    assert not paths.is_profile_name("_bot")
    assert not paths.is_profile_name(".git")
    assert not paths.is_profile_name("")
    assert paths.is_profile_name("default")
    with _store() as store:
        listed = store.list()
        os.makedirs(os.path.join(profilemod.PROFILES_DIR, "_bot"), exist_ok=True)
        assert store.list() == listed, "the bot's directory showed up as a profile"
        try:
            store.create("_bot")
        except ValueError as exc:
            assert getattr(exc.args[0], "key", "") == "profile.error.reserved"
        else:
            raise AssertionError("creating a profile named _bot was allowed")


# -- the migration -------------------------------------------------------------------

def test_old_layout_moves_across_whole():
    """A pre-#1276 checkout: profiles, settings, both templates and the language."""
    with _store(legacy=True) as store:
        del store
        names = sorted(n for n in os.listdir(profilemod.PROFILES_DIR)
                       if os.path.isdir(os.path.join(profilemod.PROFILES_DIR, n)))
        assert names == ["default", "second"], names
        moved = Path(profilemod.PROFILES_DIR) / "second" / "config.json"
        assert json.loads(moved.read_text(encoding="utf-8")) == {"port": 47655}
        assert (Path(profilemod.PROFILES_DIR) / "second" / "panel.log"
                ).read_text(encoding="utf-8") == "a line"
        settings = json.loads(Path(profilemod.SETTINGS_FILE).read_text(encoding="utf-8"))
        assert settings["active_profile"] == "second", settings
        assert settings["language"] == "ru", settings
        for template in (paths.TIMERS_TEMPLATE, paths.TRIGGERS_TEMPLATE):
            assert os.path.isfile(template), template
        assert not os.path.isdir(paths.LEGACY_PROFILES_DIR), "old directory left behind"


def test_a_loose_bot_profile_is_swept_into_its_own_folder():
    """The thing that started all this: a flat ``profiles/<id>.json`` beside the folders.

    The bot moves its own the next time it loads one, but it may not be run for months,
    and a stray json next to the profile directories is the whole confusion in miniature.
    The panel-wide files keep their place.
    """
    with _store(legacy=True) as store:
        del store
        loose = Path(profilemod.PROFILES_DIR) / "someone.json"
        loose.write_text(json.dumps({"name": "Player1"}), encoding="utf-8")
        profilemod.migrate_legacy_layout()
        assert not loose.exists(), "left lying beside the profiles"
        swept = Path(paths.BOT_PROFILES_DIR) / "someone.json"
        assert json.loads(swept.read_text(encoding="utf-8")) == {"name": "Player1"}
        assert os.path.isfile(profilemod.SETTINGS_FILE), "settings.json was swept away"
        assert os.path.isfile(paths.TIMERS_TEMPLATE), "the template was swept away"


def test_migration_never_overwrites_what_is_already_there():
    """Run twice, with a newer file in the new place: the old one does not land on it."""
    with _store(legacy=True) as store:
        del store
        kept = Path(profilemod.PROFILES_DIR) / "second" / "config.json"
        kept.write_text(json.dumps({"port": 1}), encoding="utf-8")
        # …and put the old tree back, as a second start on a half-migrated machine would
        # find it if somebody restored a backup over it.
        _make_legacy_tree()
        profilemod.migrate_legacy_layout()
        assert json.loads(kept.read_text(encoding="utf-8")) == {"port": 1}


def test_migration_leaves_a_note_when_it_had_to_copy():
    """A directory that cannot be MOVED is copied and marked, never silently redone."""
    with _store(legacy=True, skip_migration=True):
        held = Path(paths.LEGACY_PROFILES_DIR) / "second" / "panel.log"
        with open(held, "a", encoding="utf-8"):        # a handle, as a live panel has
            _force_copy_fallback()
            profilemod.migrate_legacy_layout()
        marker = Path(paths.LEGACY_PROFILES_DIR) / paths.MIGRATION_MARKER
        assert marker.is_file(), "copied across without saying so"
        assert held.is_file(), "the original was removed after a copy"
        # …and a second start does not put the old files back over newer ones.
        moved = Path(profilemod.PROFILES_DIR) / "second" / "config.json"
        moved.write_text(json.dumps({"port": 2}), encoding="utf-8")
        profilemod.migrate_legacy_layout()
        assert json.loads(moved.read_text(encoding="utf-8")) == {"port": 2}


def test_migration_stays_away_from_a_redirected_store():
    """A test or a bench pointing the store at a scratch directory migrates nothing."""
    with _store() as store:
        del store
        # The real panel/profiles/ of this checkout, if it still exists, is not to be
        # dragged into a temporary directory by anything.
        assert profilemod.migrate_legacy_layout() == []


# -- helpers -------------------------------------------------------------------------

class _store:
    """Point the whole store at a fresh temporary directory for the duration.

    Rebinds `panel.paths` as well as `panel.profile`: the migration refuses to run when
    the two disagree, which is exactly what keeps it away from this machine's real
    profiles when a test redirects the store.
    """

    def __init__(self, legacy: bool = False, skip_migration: bool = False) -> None:
        self._legacy, self._skip = legacy, skip_migration

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self._saved = {
            "paths": {k: getattr(paths, k) for k in _REBOUND},
            "profile": (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE),
            "move": profilemod.__dict__.get("_forced_copy"),
        }
        new = os.path.join(root, "profiles")
        paths.PROFILES_DIR = new
        paths.SETTINGS_FILE = os.path.join(new, "settings.json")
        paths.TIMERS_TEMPLATE = os.path.join(new, "timers.json")
        paths.TRIGGERS_TEMPLATE = os.path.join(new, "triggers.json")
        paths.FALLBACK_DEBUG_LOG = os.path.join(new, "panel_debug.log")
        paths.BOT_PROFILES_DIR = os.path.join(new, "_bot")
        paths.LEGACY_PROFILES_DIR = os.path.join(root, "panel", "profiles")
        paths.LEGACY_SETTINGS_FILE = os.path.join(root, "panel", "settings.json")
        paths.LEGACY_TIMERS_TEMPLATE = os.path.join(root, "panel", "timers.json")
        paths.LEGACY_TRIGGERS_TEMPLATE = os.path.join(root, "panel", "triggers.json")
        paths.LEGACY_LANG_FILE = os.path.join(root, "home", ".last_war_panel.json")
        profilemod.PROFILES_DIR = paths.PROFILES_DIR
        profilemod.SETTINGS_FILE = paths.SETTINGS_FILE
        if self._legacy:
            _make_legacy_tree()
        return None if self._skip else profilemod.ProfileManager()

    def __exit__(self, *exc):
        for key, value in self._saved["paths"].items():
            setattr(paths, key, value)
        profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE = self._saved["profile"]
        _restore_move()
        self._tmp.cleanup()
        return False


_REBOUND = ("PROFILES_DIR", "SETTINGS_FILE", "TIMERS_TEMPLATE", "TRIGGERS_TEMPLATE",
            "FALLBACK_DEBUG_LOG", "BOT_PROFILES_DIR", "LEGACY_PROFILES_DIR",
            "LEGACY_SETTINGS_FILE", "LEGACY_TIMERS_TEMPLATE",
            "LEGACY_TRIGGERS_TEMPLATE", "LEGACY_LANG_FILE")


def _make_legacy_tree() -> None:
    """Write the pre-#1276 layout: two profiles, the settings, templates, language."""
    legacy = Path(paths.LEGACY_PROFILES_DIR)
    for name, config in (("default", {}), ("second", {"port": 47655})):
        (legacy / name).mkdir(parents=True, exist_ok=True)
        (legacy / name / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (legacy / name / "panel.log").write_text("a line", encoding="utf-8")
    Path(paths.LEGACY_SETTINGS_FILE).write_text(
        json.dumps({"active_profile": "second", "open_profiles": ["second"]}),
        encoding="utf-8")
    Path(paths.LEGACY_TIMERS_TEMPLATE).write_text("[]", encoding="utf-8")
    Path(paths.LEGACY_TRIGGERS_TEMPLATE).write_text("[]", encoding="utf-8")
    lang = Path(paths.LEGACY_LANG_FILE)
    lang.parent.mkdir(parents=True, exist_ok=True)
    lang.write_text(json.dumps({"lang": "ru"}), encoding="utf-8")


# `shutil.move` succeeds on POSIX where Windows would refuse (an open file does not
# stop a rename here), so the copy-and-mark path has to be provoked rather than waited
# for. Swapped back out by `_restore_move`.
_REAL_MOVE = None


def _force_copy_fallback() -> None:
    global _REAL_MOVE
    import shutil
    if _REAL_MOVE is None:
        _REAL_MOVE = shutil.move

    def refuse(src, dst, *a, **kw):
        if os.path.isdir(src):
            raise OSError("in use")
        return _REAL_MOVE(src, dst, *a, **kw)

    shutil.move = refuse


def _restore_move() -> None:
    global _REAL_MOVE
    if _REAL_MOVE is not None:
        import shutil
        shutil.move = _REAL_MOVE
        _REAL_MOVE = None


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
