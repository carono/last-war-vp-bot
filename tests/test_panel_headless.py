r"""The panel with NO WINDOW, built and answering (#1976, P3).

`panel/headless.py` is what the plan's own rule for the migration needs: the old way of
driving the panel is deleted only after the NEW one has been used to drive it
(`docs/research/panel-service-and-spa-plan.md` §3). So there is a panel with no Tk in it
before a single `build()` is deleted, and every tab that still draws goes on drawing in
the window meanwhile.

What is pinned here is what «the panel, minus the drawing» has to mean:

  * the profiles open, their schedules start, and their tabs are BUILT — state, errands
    and screens — with `build()` never called, because there is no frame to draw into;
  * a tab's saved block is still applied: a tab's settings ARE its state, and a headless
    panel keeps every one of them;
  * a screen is data off that state, so the phone sees what it always saw;
  * and nothing here needs a display, which is the whole point.

    C:\Python312\python.exe tests\test_panel_headless.py
    python3 tests/test_panel_headless.py
"""
from __future__ import annotations

TIER = "offline"   # no window and no display — if this needs Tk, P3 is not done

import json
import os
import sys
import threading
import tempfile
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub_tk() -> None:
    """A tkinter that answers everything and draws nothing.

    Only so the test can RUN where the package is missing: what it proves is that the
    headless panel never asks it to draw. `test_panel_headless_state` is the one that
    pins the two files which import no Tk at all.
    """
    if "tkinter" in sys.modules:
        return

    class _W:
        def __init__(self, *a, **k) -> None:
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    def _module(name: str):
        mod = types.ModuleType(name)
        made: dict = {}

        def _make(attr: str):
            if attr not in made:
                made[attr] = type(attr, (_W,), {})
            return made[attr]

        mod.__getattr__ = _make
        return mod

    tk = _module("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    sys.modules["tkinter"] = tk
    for sub in ("ttk", "font", "messagebox", "simpledialog", "scrolledtext",
                "filedialog"):
        child = _module(f"tkinter.{sub}")
        sys.modules[f"tkinter.{sub}"] = child
        setattr(tk, sub, child)


_stub_tk()

from panel import profile as profilemod              # noqa: E402
from panel.headless import HeadlessPanel             # noqa: E402
from panel.web.api import WebApi                     # noqa: E402


class _Scratch:
    """A profiles tree of its own, so nothing here touches this machine's panel."""

    def __init__(self, tabs=("checklist",)) -> None:
        # `ignore_cleanup_errors`: an opened profile leaves a `panel.db`, and on Windows
        # a SQLite file cannot be unlinked while a connection to it is open.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE)
        profilemod.PROFILES_DIR = os.path.join(self._tmp.name, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(self._tmp.name, "settings.json")
        os.makedirs(os.path.join(profilemod.PROFILES_DIR, "solo"), exist_ok=True)
        with open(os.path.join(profilemod.PROFILES_DIR, "solo", "config.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"tabs": {"enabled": list(tabs), "known": list(tabs)},
                       "watchdog": False, "power": False}, fh)

    def close(self) -> None:
        profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE = self._saved
        self._tmp.cleanup()


def _panel(tabs=("checklist",)):
    scratch = _Scratch(tabs)
    panel = HeadlessPanel(["solo"], web=False)
    return scratch, panel


# ---------------------------------------------------------------------------
def test_a_panel_with_no_window_opens_its_profile_and_builds_its_tabs() -> None:
    scratch, panel = _panel()
    try:
        opened = panel.open()
        assert [s.name for s in opened] == ["solo"], opened
        rt = panel.workspace.current.rt
        assert rt.root is None, "a headless runtime grew a window"
        tab = rt.tabs.peek("checklist")
        assert tab is not None, "the tab was never built"
        assert tab.parent is None, "a headless tab was given something to draw into"
    finally:
        panel.shutdown()
        scratch.close()


def test_realizing_a_tab_applies_its_settings_and_draws_nothing() -> None:
    """A tab's saved block is its STATE, and state is what survives the window."""
    scratch, panel = _panel()
    try:
        panel.open()
        rt = panel.workspace.current.rt
        tab = rt.tabs.peek("checklist")
        drawn: list = []
        tab.build = lambda: drawn.append(1)      # …and it must never be called
        applied: list = []
        tab.apply_config = lambda raw: applied.append(raw)
        tab._saved_config = {"anything": 1}
        assert rt.tabs.realize(tab) is True
        assert drawn == [], "the headless panel tried to draw a tab"
        assert applied == [{"anything": 1}], applied
        assert tab.built is True
        assert rt.tabs.realize(tab) is False, "realize is not idempotent"
    finally:
        panel.shutdown()
        scratch.close()


def test_the_windowless_panel_answers_the_whole_api() -> None:
    """The phone sees what it always saw — the screens are data off the tabs' state."""
    scratch, panel = _panel()
    try:
        panel.open()
        rt = panel.workspace.current.rt
        api = WebApi(rt)
        status, payload = api.dispatch("GET", "/api/profiles", {}, {})
        assert status == 200 and "solo" in payload["profiles"], payload
        status, payload = api.dispatch("GET", "/api/state", {}, {})
        assert status == 200 and payload["profile"] == "solo", payload
        status, payload = api.dispatch("GET", "/api/screens", {}, {})
        assert status == 200, payload
        ids = [s["id"] for s in payload["screens"]]
        assert "checklist" in ids, ids
        status, screen = api.dispatch("GET", "/api/screen", {"id": "checklist"}, {})
        assert status == 200 and screen.get("cards") is not None, screen
    finally:
        panel.shutdown()
        scratch.close()


def test_its_clock_is_the_windowless_one_and_it_actually_ticks() -> None:
    """`Ticker` with no widget arms nothing — a schedule that never fires (#1976)."""
    import threading

    from panel.runtime.tick import ThreadTicker

    scratch, panel = _panel()
    try:
        panel.open()
        rt = panel.workspace.current.rt
        assert isinstance(rt.tick, ThreadTicker), type(rt.tick)
        fired = threading.Event()
        rt.tick.arm("test", 10, fired.set)
        assert fired.wait(3.0), "the headless clock never fired"
    finally:
        panel.shutdown()
        scratch.close()


def test_a_tab_that_will_not_build_is_skipped_and_said() -> None:
    """One broken tab is a line in the log, exactly as it is in a window."""
    scratch, panel = _panel(tabs=("checklist", "no_such_tab_at_all"))
    try:
        opened = panel.open()
        assert opened, "one unknown tab stopped the whole profile"
        assert panel.workspace.current.rt.tabs.peek("checklist") is not None
    finally:
        panel.shutdown()
        scratch.close()


def test_the_runtime_and_the_headless_panel_import_with_no_tkinter_at_all() -> None:
    """P3's acceptance test, as far as it reaches today (#1976).

    `panel.runtime` used to need Tk to be imported at all, because the package imported
    the log PANE — so a panel with no display, or a machine with no `tkinter` installed,
    could not so much as read its own settings. The spool is `panel/runtime/log_spool.py`
    now and the pane is imported by whoever draws one.

    WHAT IS STILL TRUE: a tab CLASS imports Tk when it is loaded, because it still draws.
    That is what the rest of P3 removes, one tab at a time; this test is what will notice
    when the last one goes.
    """
    import subprocess

    code = (
        "import sys\n"
        "sys.path[:0] = ['.', 'tools', 'tools/lib']\n"
        "sys.modules['tkinter'] = None\n"      # any import of it now raises
        "import panel.runtime, panel.headless\n"
        "print('ok')\n")
    done = subprocess.run([sys.executable, "-c", code], cwd=str(_REPO),
                          capture_output=True, text=True)
    assert done.returncode == 0 and "ok" in done.stdout, (done.stdout, done.stderr[-800:])


def test_the_two_presses_on_the_panel_ITSELF_exist_without_a_window() -> None:
    """«⟳ Перезапустить панель» and «Заглушить» were the SHELL's, and a panel with no
    window answered «unavailable» to both (#1976, measured live through the service).

    That is not a missing convenience: `CLAUDE.md` makes the restart MANDATORY after every
    fix, because a running panel plays the code it was imported with — and with no window
    there is nobody at the machine to end the process by hand either. So the windowless
    panel registers both, and a restart comes back as `panel.headless` rather than as a
    window this session may have no desktop for.
    """
    from panel.runtime import panel_control as panelctl

    source = (_REPO / "panel" / "headless.py").read_text(encoding="utf-8")
    for action in ("panelctl.RESTART", "panelctl.QUIT"):
        assert f"set_handler(self._restart_now, {action})" in source \
            or f"set_handler(self._quit_now, {action})" in source, \
            f"a windowless panel cannot be asked to {action}"
    assert 'relaunch(module="panel.headless")' in source, (
        "a windowless restart would come back with a window")
    assert panelctl.RESTART in panelctl.BY_ID and panelctl.QUIT in panelctl.BY_ID


def test_a_press_with_no_window_waits_for_its_own_answer_to_be_written() -> None:
    """The delay is not decoration: the press arrives on the socket the phone is holding,
    and pulling the interpreter out before the answer is flushed leaves it unable to tell
    «перезапускается» from «упало». With a window that wait is Tk's `after`; with none it
    is the panel's own clock — and a Tk `Ticker` without a widget arms NOTHING, which is
    why the two are told apart by name rather than trusted."""
    from panel.runtime import panel_control as panelctl
    from panel.runtime import tick as tickmod

    assert tickmod.ThreadTicker.THREADED is True
    assert tickmod.Ticker.THREADED is False

    clock = tickmod.ThreadTicker()
    clock.start()
    ran = threading.Event()

    class _Rt:
        root = None
        tick = clock

        def say(self, *a, **k):
            pass

    try:
        panelctl.set_handler(ran.set, panelctl.QUIT)
        said = panelctl.request(_Rt(), panelctl.QUIT)
        assert said.get("ok") is True, said
        assert not ran.is_set(), "the panel went down before its answer was written"
        assert ran.wait(5), "the press was armed on a clock that never fired"
    finally:
        panelctl.set_handler(None, panelctl.QUIT)
        clock.stop()


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
