r"""A profile's settings live in its database, not in a JSON file (#2017).

The person's decision, in their words: «Никаких json, все должно быть в базе». Three
stores moved — the timer catalogue, the trigger catalogue and the rally caps — and what
this file pins is the part that is easy to get wrong:

* an old profile's file is carried across ONCE and kept beside the database as
  `.imported`, so a panel that has been running for months does not wake up blank;
* a write lands in the database and the reader sees it — including a reader in the same
  process a moment later, which is what «шестерёнка не сохраняет» would look like;
* a shipped TEMPLATE is not a profile's settings: it is code, it stays a file, and
  nothing here may write a database into the source tree;
* nothing holds the database open, or a profile could not be deleted on Windows and a
  temporary directory could not be cleaned up.

No Tk, no game, no network::

    python3 tests/test_panel_settings_files.py
"""
from __future__ import annotations

TIER = "offline"        # see tools/run_tests.py

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "tests", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import settings_files
from panel.runtime import store as storemod                   # noqa: E402
from panel import timers as timersmod                      # noqa: E402
from panel import triggers as triggersmod                  # noqa: E402
from panel import rally_limits as limitsmod                # noqa: E402


def test_a_store_answers_nothing_before_anything_was_saved():
    with tempfile.TemporaryDirectory() as home:
        path = os.path.join(home, "timers.json")
        assert settings_files.read(path) is None
        assert settings_files.exists(path) is False


def test_a_write_is_read_back_out_of_the_database():
    with tempfile.TemporaryDirectory() as home:
        path = os.path.join(home, "timers.json")
        assert settings_files.write(path, [{"name": "collect"}]) is True
        assert settings_files.read(path) == [{"name": "collect"}]
        assert settings_files.exists(path) is True
        # …in the profile's own database, beside where the file used to be, and NOT
        # as a file: that is the whole of the change.
        assert os.path.exists(os.path.join(home, "panel.db"))
        assert not os.path.exists(path)


def test_an_old_profiles_file_is_carried_across_once_and_kept():
    with tempfile.TemporaryDirectory() as home:
        path = os.path.join(home, "triggers.json")
        Path(path).write_text(json.dumps([{"name": "alliance_help"}]),
                              encoding="utf-8")

        assert settings_files.read(path) == [{"name": "alliance_help"}]
        # The file is kept beside the database rather than deleted: an import that
        # misread a field is answered by opening it, and a delete is answered by nothing.
        assert not os.path.exists(path)
        assert os.path.exists(path + ".imported")

        # …and the import does not run twice: what is written afterwards stands.
        settings_files.write(path, [{"name": "session_kick"}])
        assert settings_files.read(path) == [{"name": "session_kick"}]


def test_a_shipped_template_is_code_and_stays_a_file():
    """`panel/timers.json` is part of the repository, not part of an account."""
    template = os.path.join(str(_REPO), "panel", "timers.json")
    assert settings_files.owned(template) is False
    assert settings_files.write(template, [{"name": "nope"}]) is False
    assert settings_files.read(template) is None
    assert not os.path.exists(os.path.join(str(_REPO), "panel", "panel.db")), (
        "a database was opened inside the source tree")


def test_nothing_holds_the_database_open():
    """A kept handle is a profile Windows will not let anybody delete."""
    home = tempfile.mkdtemp()
    settings_files.write(os.path.join(home, "timers.json"), [{"name": "collect"}])
    shutil.rmtree(home)                       # would raise if a handle were open
    assert not os.path.exists(home)


# ---------------------------------------------------------------------------
# the three stores that moved
# ---------------------------------------------------------------------------
def test_the_timer_catalogue_is_stored_and_re_read():
    with tempfile.TemporaryDirectory() as home:
        path = os.path.join(home, "timers.json")
        seeded = timersmod.load_catalogue(path)
        assert seeded.names(), "a fresh profile is seeded from the built-ins"
        assert settings_files.read(path) is not None, "the list is a row now"
        assert not os.path.exists(path)

        timersmod.save_catalogue(
            seeded.with_settings({seeded.names()[0]: {"enabled": True,
                                                      "interval_sec": 900}}), path)
        again = timersmod.load_catalogue(path)
        assert again.by_name(seeded.names()[0]).interval_sec == 900


def test_the_trigger_catalogue_is_stored_and_re_read():
    with tempfile.TemporaryDirectory() as home:
        path = os.path.join(home, "triggers.json")
        seeded = triggersmod.load_catalogue(path)
        assert seeded.names()
        assert settings_files.read(path) is not None
        assert not os.path.exists(path)


def test_the_rally_caps_are_stored_and_re_read():
    with tempfile.TemporaryDirectory() as home:
        path = os.path.join(home, "rally_limits.json")
        limits = limitsmod.load_limits(path)
        limitsmod.save_limits(limits.with_limit("doom_elite", 4), path)
        assert not os.path.exists(path), "the caps are a row, not a file"
        assert limitsmod.load_limits(path).limit_for("doom_elite") == 4


def test_the_two_stores_that_had_not_moved_have_and_the_module_says_so():
    """`config.json` and the panel-wide `settings.json` were named here as open
    questions; #2025 answered both, and the module says which and why rather than
    leaving the reversal silent."""
    source = (_REPO / "panel" / "runtime"
              / "settings_files.py").read_text(encoding="utf-8")
    assert "config.json" in source and "profiles/settings.json" in source
    assert "#2025" in source


def test_a_shipped_template_lands_in_the_real_database_even_mid_test():
    """THE LIVE BUG THIS COST (#2025), pinned from the outside.

    A test points the panel at a scratch tree by rebinding `panel.profile.PROFILES_DIR`
    — but the code seeding a new profile still reads the SHIPPED TEMPLATE by its own
    real path. Resolving the database against the rebound root alone sent that read to
    «beside the file, under the directory's own name», which for the real template is
    the live `profiles/panel.db` under a scope called `profiles`. Nothing was lost and
    nothing was read back, which is exactly why it went unnoticed for a whole session.
    """
    from panel import paths, profile as profilemod

    was = profilemod.PROFILES_DIR
    try:
        profilemod.PROFILES_DIR = os.path.join(tempfile.gettempdir(), "nowhere",
                                               "profiles")
        for template in (paths.TIMERS_TEMPLATE, paths.TRIGGERS_TEMPLATE):
            database, whose = settings_files._home(template)
            assert whose == storemod.PANEL_SCOPE, (template, whose)
            assert database == os.path.join(paths.PROFILES_DIR,
                                            storemod.DB_FILE), database
    finally:
        profilemod.PROFILES_DIR = was


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:      # noqa: BLE001 — a raise is a failure too
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
