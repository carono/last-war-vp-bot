r"""Every settings write is said out loud, and a knob with no widget is not lost (#1957).

Written after the live watchdog went off on all four accounts at once and nobody could
name what turned it off. Two things were true at the same time, and this file pins both
of their fixes:

  * a profile's settings are stored as a WHOLE SNAPSHOT, so a value that vanished left
    no trace anywhere — not a line in `panel.log`, not one in `debug.log`, and not even
    a usable mtime, because the row is rewritten in full on every save;
  * `_collect_settings` wrote a key only when its Tk variable existed, so a save taken
    before the widgets were drawn — the boot, a `LAZY` Settings page, a headless panel —
    deleted every knob it could not see, and the next load answered with the code's own
    default, which for a switch is off.

No Tk, no game, no daemon: a scratch profile store and a log handler.

    C:\Python312\python.exe tests\test_panel_settings_audit.py
    python3 tests/test_panel_settings_audit.py
"""
from __future__ import annotations

TIER = "offline"

import ast
import logging
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import debug_log                       # noqa: E402
from panel import profile as profilemod           # noqa: E402


class _Profiles:
    """`profilemod` pointed at a scratch directory for the duration of a test."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self._saved = (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE)
        profilemod.PROFILES_DIR = os.path.join(root, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(root, "settings.json")
        return self

    def __exit__(self, *exc):
        profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE = self._saved
        self._tmp.cleanup()
        return False


class _Heard:
    """Everything the profile's own settings logger says, as (level, text) pairs."""

    def __init__(self, name: str) -> None:
        self._log = debug_log.get_logger("settings", scope=name)
        self.lines: list[tuple[int, str]] = []

    def __enter__(self):
        outer = self

        class _Sink(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                outer.lines.append((record.levelno, record.getMessage()))

        self._sink = _Sink()
        self._log.addHandler(self._sink)
        self._level, self._prop = self._log.level, self._log.propagate
        self._log.setLevel(logging.DEBUG)
        self._log.propagate = False
        return self

    def __exit__(self, *exc):
        self._log.removeHandler(self._sink)
        self._log.setLevel(self._level)
        self._log.propagate = self._prop
        return False

    def about(self, key: str) -> list[tuple[int, str]]:
        return [line for line in self.lines if line[1].startswith(key + ":")]


# ---------------------------------------------------------------------------
# the audit line
# ---------------------------------------------------------------------------

def test_a_moved_knob_says_what_it_was_and_what_it_became() -> None:
    with _Profiles():
        mgr = profilemod.ProfileManager()
        mgr.save({"watchdog": True}, profilemod.DEFAULT_PROFILE)
        with _Heard(profilemod.DEFAULT_PROFILE) as heard:
            mgr.save({"watchdog": False}, profilemod.DEFAULT_PROFILE)
        said = heard.about("watchdog")
        assert said, f"nothing said about the knob that moved: {heard.lines}"
        text = said[0][1]
        assert "true" in text and "false" in text, text
        assert "from panel" in text, text


def test_a_key_that_vanishes_from_the_snapshot_is_a_warning() -> None:
    """The one that cost seven hours of a dead client: not a change, a DELETION."""
    with _Profiles():
        mgr = profilemod.ProfileManager()
        mgr.save({"watchdog": True}, profilemod.DEFAULT_PROFILE)
        with _Heard(profilemod.DEFAULT_PROFILE) as heard:
            mgr.save({}, profilemod.DEFAULT_PROFILE)
        said = heard.about("watchdog")
        assert said, f"a key was dropped and nothing was said: {heard.lines}"
        level, text = said[0]
        assert level >= logging.WARNING, text
        assert "gone" in text, text


def test_the_line_says_where_the_write_came_from() -> None:
    with _Profiles():
        mgr = profilemod.ProfileManager()
        with _Heard(profilemod.DEFAULT_PROFILE) as heard:
            with profilemod.writing("web"):
                mgr.save({"watchdog": True}, profilemod.DEFAULT_PROFILE)
        assert any("from web" in text for _, text in heard.about("watchdog")), heard.lines
        with _Heard(profilemod.DEFAULT_PROFILE) as heard:
            mgr.save({"watchdog": False}, profilemod.DEFAULT_PROFILE, source="timers")
        assert any("from timers" in text for _, text in heard.about("watchdog")), heard.lines


def test_an_inherited_value_says_so() -> None:
    """A knob a profile never set is the DEFAULT's — one tick moves all of them."""
    with _Profiles():
        mgr = profilemod.ProfileManager()
        mgr.create("alt")
        mgr.save({"watchdog": True}, profilemod.DEFAULT_PROFILE)
        with _Heard("alt") as heard:
            mgr.save({"watchdog": False}, "alt")      # an override of its own
        assert "own" in heard.about("watchdog")[0][1], heard.lines
        assert mgr.owns("watchdog", "alt") is True
        with _Heard("alt") as heard:
            mgr.save({"watchdog": True}, "alt")       # …given up again
        said = heard.about("watchdog")
        assert said, heard.lines
        assert "inherited" in said[0][1], said[0][1]
        # And that is the whole point of the label: nothing of «alt»'s own says
        # «watchdog» any more, so the default profile decides it from here on.
        assert mgr.owns("watchdog", "alt") is False
        assert mgr.owns("watchdog", profilemod.DEFAULT_PROFILE) is True


def test_a_save_that_changes_nothing_says_nothing() -> None:
    with _Profiles():
        mgr = profilemod.ProfileManager()
        mgr.save({"watchdog": True}, profilemod.DEFAULT_PROFILE)
        with _Heard(profilemod.DEFAULT_PROFILE) as heard:
            mgr.save({"watchdog": True}, profilemod.DEFAULT_PROFILE)
        assert heard.lines == [], heard.lines


def test_a_nested_block_is_named_by_its_path() -> None:
    with _Profiles():
        mgr = profilemod.ProfileManager()
        mgr.save({"tabs": {"config": {"rally": {"squads": [1]}}}},
                 profilemod.DEFAULT_PROFILE)
        with _Heard(profilemod.DEFAULT_PROFILE) as heard:
            mgr.save({"tabs": {"config": {"rally": {"squads": [1, 3]}}}},
                     profilemod.DEFAULT_PROFILE)
        assert heard.about("tabs.config.rally.squads"), heard.lines


# ---------------------------------------------------------------------------
# the snapshot keeps what it cannot see
# ---------------------------------------------------------------------------

def test_a_knob_with_no_widget_keeps_its_last_known_value() -> None:
    """Read over the source: building the shell needs Tk and a whole profile, and what
    is being pinned is one branch of one loop."""
    source = (_REPO / "panel" / "__main__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    collect = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_collect_settings")
    loop = next(n for n in ast.walk(collect)
                if isinstance(n, ast.For) and getattr(n.target, "id", "") == "key")
    branch = next(n for n in ast.walk(loop)
                  if isinstance(n, ast.If) and n.orelse)
    fallback = ast.unparse(branch.orelse)
    assert "_settings" in fallback, \
        "a knob with no widget is dropped from the snapshot — the next load answers " \
        "with the code's default, and for a switch that means off (#1957)"


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception as exc:            # noqa: BLE001 — a test runner
            bad += 1
            print(f"  FAIL {fn.__name__}: {exc.__class__.__name__}: {exc}")
    print(f"{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_run())
