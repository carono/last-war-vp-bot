r"""A profile's page is built the same both ways — in one go, and a step at a time.

`panel/__main__.py::_build_ui` used to be one straight line: fifteen plugin tabs
constructed before it returned, a second and a half of Tk in which the window did not
redraw and answered nothing. #1208 split it in two — the shell's own half (the status
strip, the control blocks, the log pane, the command line) first, the tabs one per turn
of the event loop after it — and that is a reordering of the panel's main build path,
which nothing tested at all.

So this builds a real page, both ways, and asserts the end state is the same one:

  * every tab the registry offers is built, registered with the runtime, and reachable
    through `_lazy_tabs` (which is what «somebody is looking at this tab» reads);
  * «Главная» is whole — the game strip, the daemon indicator, the log widget, the
    command line;
  * the account summary strip is built INSIDE the «Аккаунты» tab and after it, which is
    the ordering that puts it under the character list rather than above it;
  * the staged build reaches exactly the same place, and calls back when it gets there;
  * and the window's own bottom strip exists and starts out idle.

Needs Tk and a display; it opens a hidden window and takes it down again. The profile
directory is a temporary one, so nothing here touches a real profile's config, log or
heartbeat.

    C:\Python312\python.exe tests\test_panel_page_build.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_SKIPPED: list = []


def _skip(why) -> None:
    _SKIPPED.append(str(why))
    print(f"  skip (no display: {why})")


class _Harness:
    """One `Panel`, minus its `__init__` — the window, the workspace, one page.

    `Panel.__init__` is the boot: a splash, the menu, the geometry, a start-up thread
    per profile that brings a daemon up. None of that is what this file is about, and
    all of it would touch the machine. So the object is made without it and given
    exactly what `_build_outer` and `_open_session_page` read.
    """

    def __init__(self, staged: bool = False) -> None:
        import tkinter as tk

        from panel import __main__ as pm
        from panel import profile as profilemod
        from panel import runtime as rtmod

        # `ignore_cleanup_errors` because Windows will not delete a file something
        # still holds open, and a log handler that outlives its session is a bug in the
        # session, not in this file — `test_panel_debug_log.py` is where that is pinned.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.saved_dir = profilemod.PROFILES_DIR
        profilemod.PROFILES_DIR = self.tmp.name

        app = pm.Panel.__new__(pm.Panel)
        tk.Tk.__init__(app)
        app.withdraw()
        # In the order `Panel.__init__` does it: nothing is routed until a session has
        # been adopted, and the window's own chrome is said in that session's language.
        app._current_session = None
        app._activity = rtmod.Activity()
        app._activity_var = None
        app._activity_lbl = None
        app._activity_pending = False
        app._workspace = rtmod.Workspace(app, defaults=pm.SETTINGS_DEFAULTS)
        self.session = app._workspace.open("smoke")
        # The one thing a page build would otherwise do to the machine: hold this
        # profile's instance lock and beat for it. Not what is under test.
        self.session.rt.start_heartbeat = lambda: None
        app._adopt(self.session)
        app._profile_var = tk.StringVar(value=self.session.name)
        app._build_outer()

        self.app = app
        self.done: list = []
        app._open_session_page(self.session, staged=staged,
                               done=lambda: self.done.append(True))

    def pump(self, turns: int = 600) -> None:
        """Turn the event loop until the staged build says it is finished.

        With a breath between the turns: the steps are handed on with `after(1, …)`,
        and a loop tight enough to spin faster than the clock ticks never lets one
        come due.
        """
        for _ in range(turns):
            if self.done:
                return
            self.app.update()
            time.sleep(0.002)

    def close(self) -> None:
        from panel import profile as profilemod

        try:
            self.app._disarm_all()
        except Exception:                              # noqa: BLE001
            pass
        try:
            self.session.shutdown()                    # tabs, errands, files
        except Exception:                              # noqa: BLE001
            pass
        try:
            self.app.destroy()
        except Exception:                              # noqa: BLE001
            pass
        profilemod.PROFILES_DIR = self.saved_dir
        self.tmp.cleanup()


def _open(staged: bool):
    """A harness, or ``None`` when there is no display to build one in.

    ONLY a Tk failure is a skip. Anything the page build itself raises is the answer
    this file exists to get, and swallowing it would make a broken build read as «no
    display» on every machine that has none to spare.
    """
    try:
        import tkinter as tk

        tk.Tk().destroy()
    except Exception as exc:                           # noqa: BLE001
        _skip(exc)
        return None
    return _Harness(staged=staged)


def _built(harness: "_Harness") -> None:
    """Everything that must be true of a finished page, however it was built."""
    app, session = harness.app, harness.session
    with app._on(session):
        tabs = app._plugin_tabs
        assert tabs, "no plugin tab was built at all"
        # Every tab built is known to the runtime, and reachable by the frame the
        # notebook reports as selected.
        for tab_id, tab in tabs.items():
            assert session.rt.tabs.get(tab_id) is tab, tab_id
        lazy = app._lazy_tabs
        assert len(lazy) == len(tabs), (len(lazy), len(tabs))
        assert set(lazy.values()) == set(tabs.values())
        # «Главная» is whole.
        assert app._log is not None, "the log pane was not built"
        assert app._status_var.get(), "the game status strip was not built"
        assert app._daemon_var.get(), "the daemon indicator was not built"
        assert app._cmd_var.get() == "", "the command line was not built"
        assert app._main_nb is not None and app._main_split is not None
        # …and the settings were applied to it, with auto-save armed afterwards.
        assert app._loading is False, "the page was left in its loading state"
        # The account strip belongs to the «Аккаунты» tab and comes AFTER it, so it
        # sits under the character list. Only if this profile has that tab at all.
        if "accounts" in tabs:
            assert app._dash_view is not None, "the account summary strip is missing"
            frame = tabs["accounts"].parent
            children = [str(w) for w in frame.winfo_children()]
            # Tk widget paths are the tree: the strip's own block is whichever child of
            # the tab the view's path starts with.
            block = [c for c in children if str(app._dash_view).startswith(c + ".")]
            assert block, "the summary strip was not built into the «Аккаунты» tab"
            assert children[-1] == block[0], \
                "the summary strip was built before the tab it belongs under"


def test_a_page_built_in_one_go_is_whole() -> None:
    harness = _open(staged=False)
    if harness is None:
        return
    try:
        assert harness.done, "the boot path must finish before it returns"
        _built(harness)
        assert harness.app._activity_var.get(), "the bottom strip was never said"
    finally:
        harness.close()


def test_a_staged_page_reaches_exactly_the_same_place() -> None:
    harness = _open(staged=True)
    if harness is None:
        return
    try:
        assert not harness.done, "a staged build must return before it is finished"
        with harness.app._on(harness.session):
            # The shell's own half is whole before the first tab is touched — that is
            # the half a person can already read and use while the rest fills in.
            assert harness.app._log is not None, \
                "the shell's own half must be there before the first turn"
            assert not hasattr(harness.app, "_lazy_tabs"), \
                "the tabs were all built straight away after all"
        harness.pump()
        assert harness.done, "the staged build never finished"
        _built(harness)
    finally:
        harness.close()


def test_the_bottom_strip_says_what_is_running_and_names_the_profile() -> None:
    """The window's strip: idle by default, the newest step otherwise."""
    harness = _open(staged=False)
    if harness is None:
        return
    try:
        app, session = harness.app, harness.session
        assert app._activity_text() == app._t("activity.idle")
        with session.rt.activity.step("activity.daemon.start", port=47654):
            said = app._activity_text()
            assert "47654" in said, said
            # One profile open — the strip does not repeat its name at every step.
            assert session.name not in said, said
        assert app._activity_text() == app._t("activity.idle")
        # The window's own steps are shown too, and outrank an older profile step.
        with session.rt.activity.step("activity.dashboard"):
            with app._activity.step("activity.update.check"):
                assert app._activity_text() == app._t("activity.update.check")
    finally:
        harness.close()


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
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f"  ERR  {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    if _SKIPPED:
        print(f"({len(_SKIPPED)} skipped — no display)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
