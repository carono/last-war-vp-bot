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
        # BOTH of them, and the second one is the one that bites: `PROFILES_DIR` holds
        # the profiles, but which of them a panel has OPEN is panel-wide state in
        # `SETTINGS_FILE` beside them — and a workspace writes it on every open. Patch
        # only the first and this test quietly tells the operator's own panel to come
        # up on a profile that exists nowhere but in a temporary directory.
        self.saved_dir = profilemod.PROFILES_DIR
        self.saved_settings = profilemod.SETTINGS_FILE
        profilemod.PROFILES_DIR = self.tmp.name
        profilemod.SETTINGS_FILE = str(Path(self.tmp.name) / "settings.json")

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
        from panel.runtime import tick as tickmod

        try:
            self.app._disarm_all()
        except Exception:                              # noqa: BLE001
            pass
        try:
            self.session.shutdown()                    # tabs, errands, files
        except Exception:                              # noqa: BLE001
            pass
        # `Workspace.shutdown` is skipped on purpose above (this harness closes ONE
        # session by hand, not the workspace) — but that also means it never stops the
        # shared pump `Workspace.shutdown` would have. Do it here instead, or the next
        # harness's `tk.Tk()` in the same process inherits a still-armed `after` chain
        # aimed at a destroyed widget (#1236 — "invalid command name … _pump").
        tickmod.stop(self.app)
        try:
            self.app.destroy()
        except Exception:                              # noqa: BLE001
            pass
        profilemod.PROFILES_DIR = self.saved_dir
        profilemod.SETTINGS_FILE = self.saved_settings
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


def test_building_a_page_leaves_the_machines_own_panel_alone() -> None:
    """Opening a profile HERE must not tell the operator's panel to open it too.

    Written after this file did exactly that: a workspace writes «which profiles are
    open» to the panel-wide `settings.json` on every open, and patching only the
    profiles DIRECTORY left that file pointing the real panel at a profile that existed
    nowhere but in a temporary folder — which it would have come up on at the next
    launch, alone, instead of the two the operator had.
    """
    from panel import profile as profilemod

    path = Path(profilemod.SETTINGS_FILE)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    harness = _open(staged=False)
    if harness is None:
        return
    harness.close()
    after = path.read_text(encoding="utf-8") if path.exists() else None
    assert after == before, "the machine's own panel state was rewritten"


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


def test_the_game_row_is_the_three_presses_and_they_grey_themselves() -> None:
    """The window's half of the client's lifecycle (#1221), against real widgets.

    The phone's half is `/api/state` → `game.controls` and is pinned in
    tests/test_panel_web.py. Both are built by walking the same table, and this is
    where that stops being a promise: three buttons in the order the table gives, and
    each of them greyed by the SAME rule the phone greys by — «Закрыть» with no client
    is not a press, and neither is «Запустить» with one already up.
    """
    from panel.runtime import game_control as gamectl
    from panel.runtime import game_process as gp

    harness = _open(staged=False)
    if harness is None:
        return
    try:
        app, session = harness.app, harness.session
        with app._on(session):
            row = app._game_buttons
            assert list(row) == [c.id for c in gamectl.CONTROLS], list(row)
            # A fresh page has not probed yet and assumes no client: the one press that
            # is harmless when that belief is wrong is the only one offered.
            assert str(row["launch"]["state"]) == "normal"
            assert str(row["quit"]["state"]) == "disabled"
            for link, expected in ((gp.ONLINE, {"launch": "disabled", "quit": "normal",
                                                "restart": "normal"}),
                                   (gp.LOST, {"launch": "disabled", "quit": "normal",
                                              "restart": "normal"}),
                                   (gp.OFFLINE, {"launch": "normal", "quit": "disabled",
                                                 "restart": "disabled"})):
                app._paint_game_buttons(link)
                got = {i: str(b["state"]) for i, b in row.items()}
                assert got == expected, (link, got)
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


def test_a_page_cannot_be_stolen_by_a_profile_switch_halfway_through() -> None:
    """A build writes to ITS OWN profile even if the shown one moves under it.

    The live failure this is written from: the strip's own commentary was rendered on
    the splash with `update()`, which drains the event queue — and a `<<NotebookTabChanged>>`
    queued by adding a page arrived in the middle of building the next one. `_show`
    ran, `_current_session` moved, and every widget the rest of the build made was
    recorded against the wrong profile: one page came up blank and the other's tabs
    did nothing. Both halves are pinned here — the pumping is gone (`splash.say`), and
    a build binds its session so that even a re-entrant switch cannot take it.
    """
    harness = _open(staged=False)
    if harness is None:
        return
    try:
        app, first = harness.app, harness.session
        second = app._workspace.open("other")
        second.rt.start_heartbeat = lambda: None
        # Somebody switches to the FIRST profile in the middle of the second's build:
        # `_show` is what a notebook's tab-changed handler calls, so call that.
        # IN THE MIDDLE OF «Главная», before the line that decides which session the
        # tab steps will be built under. Later than that and the staged build's own
        # per-step binding already covers it, and the test would pass either way.
        stolen: list = []

        original = app._install_log_copy

        def steal(widget) -> None:
            stolen.append(True)
            app._show(first)                      # …the page on screen is now the other
            original(widget)

        app._install_log_copy = steal
        try:
            app._open_session_page(second)
        finally:
            del app._install_log_copy
        assert stolen, "the build never reached the log pane — the test proves nothing"
        # Every routed name of the SECOND page must have landed on the second session.
        for name in ("_log", "_main_nb", "_status_var", "_lazy_tabs", "_plugin_tabs"):
            assert name in second.state, f"{name} was recorded against the wrong profile"
        assert second.state["_log"] is not first.state["_log"], \
            "the two pages share one log widget"
        assert second.state["_plugin_tabs"], "the second page built no tabs at all"
        # …and the first profile's page is untouched by any of it.
        assert first.state["_main_nb"] is not second.state["_main_nb"]
    finally:
        harness.close()


def test_a_maximised_window_is_remembered_as_maximised_not_as_a_rectangle() -> None:
    """…because the last row of the panel is the strip, and it was falling off.

    A maximised window's own rectangle is taller than the room a window may use, so
    putting it back as an ordinary window hangs the bottom of the panel under the
    taskbar. That used to cost nothing visible; it now costs the whole strip.
    """
    harness = _open(staged=False)
    if harness is None:
        return
    try:
        app = harness.app
        app.deiconify()
        app.geometry("800x600+40+40")
        app.update()
        normal = app._current_geometry()
        assert normal.startswith("800x600"), normal
        with app._on(harness.session):
            app._binder.values["window_geometry"] = normal
            try:
                app.state("zoomed")
                app.update()
            except Exception:                          # noqa: BLE001 — no such state
                return                                 # …then there is nothing to pin
            if not app._is_zoomed():
                return                    # the window manager refused; not a failure
            # Maximised: the remembered geometry is the one from BEFORE, and the state
            # is remembered on its own.
            assert app._current_geometry() == normal, app._current_geometry()
            assert app._collect_settings()["window_zoomed"] is True
            app.state("normal")
            app.update()
            assert app._collect_settings()["window_zoomed"] is False
    finally:
        harness.close()


def test_every_page_gets_its_own_remembered_sash_when_it_is_shown() -> None:
    """The log pane's position is per profile, and every page must get ITS one.

    The window places the sash once, at boot, from whichever profile was in front —
    so with two profiles open the second one's log pane sat where the pane happened to
    leave it, and the position that profile had remembered was never applied to
    anything.
    """
    harness = _open(staged=False)
    if harness is None:
        return
    try:
        app, first = harness.app, harness.session
        second = app._workspace.open("other")
        second.rt.start_heartbeat = lambda: None
        app._open_session_page(second)
        app.deiconify()
        app.geometry("900x700")
        app.update()
        with app._on(second):
            app._binder.values["log_sash"] = 90
        # …the way a person does it: pick the profile's tab, and let the notebook's
        # own handler run (`_on_session_tab_changed` → `_show`).
        app._outer.select(second.page)
        app.update()
        with app._on(second):
            got = app._current_sash()
        # Bounded from above by what the blocks ask for (see `_apply_sash`), so a
        # modest number is the one that survives unchanged.
        assert abs(got - 90) <= 8, f"the page was shown with the sash at {got}"
    finally:
        harness.close()


def test_showing_a_page_works_before_the_window_is_finished() -> None:
    """`_show` runs during `__init__`, BEFORE the resize damper is installed.

    That order is what the boot does — pages, then `_show`, then the menu, then the
    geometry, then the damper — and everything `_show` reaches for has to survive it.
    It did not: forcing the repaint that a freshly shown page needs asked for the
    window handle, which the damper had not created yet, and the panel died on boot
    with an AttributeError nothing could print (pythonw has no console).
    """
    harness = _open(staged=False)
    if harness is None:
        return
    try:
        app = harness.app
        for name in ("_paint_hwnd", "_paint_off", "_resize_size", "_resize_job"):
            assert not hasattr(app, name), f"{name} exists before the damper — re-aim me"
        app._show(harness.session)          # must not raise
        assert app._current_session is harness.session
        # …and again once the damper IS installed, which is the ordinary case.
        app._install_resize_damper()
        app._show(harness.session)
    finally:
        harness.close()


def test_the_splash_commentary_does_not_pump_the_event_loop() -> None:
    """`say` repaints; `step` pumps. A build reports through the first one only.

    An `update()` from inside a page build delivers whatever is queued — clicks,
    virtual events, `after` callbacks — into a half-built window. `update_idletasks`
    redraws and does not.
    """
    from panel import splash as splashmod

    calls: list = []

    class _Fake(splashmod.SplashScreen):
        def __init__(self) -> None:               # no Tk, no window
            self._step_lbl = self
            self._progress = 0.0

        def configure(self, **kw) -> None:
            calls.append(("label", kw.get("text")))

        def update(self) -> None:
            calls.append(("update",))

        def update_idletasks(self) -> None:
            calls.append(("idle",))

    fake = _Fake()
    fake.say("building the «Чат» tab…")
    kinds = [c[0] for c in calls]
    assert "update" not in kinds, "say() pumped the event loop"
    assert kinds == ["label", "idle"], kinds

    # …and the FLUSH is rationed, which the label is not (#1226). `update_idletasks`
    # re-lays out the whole window, so one per reported step makes a page build
    # quadratic in its own size — it was the largest stall left in a four-profile boot.
    # Every step still updates the words; the glass catches up at most every
    # SAY_FLUSH_MS.
    calls.clear()
    for i in range(5):
        fake.say(f"building tab {i}…")
    kinds = [c[0] for c in calls]
    assert kinds.count("label") == 5, kinds
    assert kinds.count("idle") == 0, f"the flush is not rationed: {kinds}"

    # …and once the window has passed, the next one flushes again.
    fake._flushed -= splashmod.SAY_FLUSH_MS / 1000.0
    calls.clear()
    fake.say("a later phase…")
    assert [c[0] for c in calls] == ["label", "idle"], calls


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
