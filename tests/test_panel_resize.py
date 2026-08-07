r"""The resize damper — what keeps dragging the panel's frame smooth (#1146).

Painting the window is what a size change costs: on the busiest tab a step was
around 400 ms, so a drag ran at two or three frames a second. The damper switches
Windows' painting off for the length of the drag and back on once the size has
been still, which takes the same drag down to single-digit milliseconds a step.

The rules that are easy to break and quiet when broken:

  * a <Configure> binding on a toplevel also hears every CHILD's resize, and it
    hears window MOVES — neither may switch painting off, or the panel would sit
    unpainted after any old repack;
  * a size change that arrives ON ITS OWN is not a drag and must not switch painting
    off at all (#1210): maximise, restore, a geometry set from code and a page asking
    the window for a different size all produce one, and a settle-time with painting
    off is long enough for Tk to draw a whole page into a window that shows none of
    it — which is what left a freshly-switched-to profile with empty blocks;
  * the timer that puts painting back has to be armed even when cancelling the
    previous one fails: a window with painting off and no timer is a frozen panel;
  * settling must always end with painting on, and one repaint asked for.

The Windows calls themselves are stubbed, so this runs anywhere Tk does — the
test is about when the panel asks for them, not about user32.

    C:\Python312\python.exe tests\test_panel_resize.py
    python3 tests/test_panel_resize.py          # SKIP without tkinter
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else
          "  SKIP tkinter not importable — run under the Windows Python")


class _Damper:
    """A Panel stand-in: a real Tk window with only the damper's methods on it.

    `Panel.__init__` starts a whole panel (profiles, daemon, children); the damper
    is four methods and a binding, so they are called unbound against this.
    """

    def __init__(self, root, pm):
        self._pm = pm
        self.tk_root = root
        self.calls = []                      # ("off"|"on"|"redraw") in order
        self.bind = root.bind
        self.after = root.after
        self.after_cancel = root.after_cancel
        self.winfo_width = root.winfo_width
        self.winfo_height = root.winfo_height
        self.wm_frame = lambda: "0x1234"
        # Both are reached by name — one by the binding `_install_resize_damper`
        # makes, one by the timer the handler arms.
        self._on_window_configure = self.configure_event_raw
        self._settle_resize = self.settle

    # -- the methods under test, borrowed from Panel -------------------------
    def install(self):
        self._pm.Panel._install_resize_damper(self)

    def configure_event_raw(self, event):
        self._pm.Panel._on_window_configure(self, event)

    def configure_event(self, widget, width, height):
        self.configure_event_raw(
            types.SimpleNamespace(widget=widget, width=width, height=height))

    def settle(self):
        self._pm.Panel._settle_resize(self)

    # -- user32, stubbed -----------------------------------------------------
    def _suspend_painting(self):
        if self._paint_off:
            return
        self._paint_off = True
        self.calls.append("off")

    def _resume_painting(self):
        if not self._paint_off:
            return
        self._paint_off = False
        self.calls += ["on", "redraw"]


def _damper():
    """A window and a damper on it, or `(None, None, None)` where Tk cannot run.

    Only building the window may legitimately fail (no tkinter, no display) — a
    failure past that point is a real one and is left to blow up the test.
    """
    try:
        import tkinter as tk
        import panel.__main__ as pm
        root = tk.Tk()
        root.withdraw()
    except Exception as exc:                             # noqa: BLE001
        _skip(exc)
        return None, None, None
    damper = _Damper(root, pm)
    damper.install()
    root.unbind("<Configure>")       # drive the handler by hand, not through Tk
    return root, damper, pm


def test_a_a_drag_suspends_painting_and_settling_restores_it():
    root, damper, _pm = _damper()
    if root is None:
        return
    try:
        assert damper._paint_off is False, "painting was off before any resize"
        # The first step of the drag paints as usual — one size change is not a drag.
        damper.configure_event(damper, 900, 700)
        assert damper.calls == [], damper.calls
        assert damper._resize_job is not None, "no timer to put painting back"

        # The second one is what makes it a drag, and painting goes off once.
        job = damper._resize_job
        damper.configure_event(damper, 920, 700)
        assert damper._paint_off is True, "a drag did not suspend painting"
        assert damper.calls == ["off"], damper.calls
        assert damper._resize_job is not None and damper._resize_job != job

        damper.configure_event(damper, 940, 700)
        assert damper.calls == ["off"], damper.calls

        damper.settle()
        assert damper._paint_off is False
        assert damper.calls == ["off", "on", "redraw"], damper.calls
        assert damper._resize_job is None
    finally:
        root.destroy()


def test_a2_a_one_off_resize_never_switches_painting_off():
    """#1210 — maximise, restore, `wm geometry`, a page asking for another size.

    Each is a single <Configure>, and each used to buy a settle-time of a window that
    paints nothing. A page laid out inside one of those is drawn once by Tk, into
    nowhere, and stays blank until the frame is dragged.
    """
    root, damper, _pm = _damper()
    if root is None:
        return
    try:
        damper.configure_event(damper, 900, 700)
        damper.settle()
        assert damper.calls == [], f"a lone resize damped the window: {damper.calls}"
        assert damper._paint_off is False

        # …and the next lone one does not either: settling forgets the run, so two
        # unrelated resizes minutes apart are not read as a drag.
        damper.configure_event(damper, 800, 600)
        assert damper.calls == [], f"the second lone resize damped it: {damper.calls}"
        damper.settle()
        assert damper.calls == [], damper.calls
    finally:
        root.destroy()


def test_b_child_resizes_and_window_moves_are_not_resizes():
    root, damper, _pm = _damper()
    if root is None:
        return
    try:
        # A child's own <Configure> reaches this binding too (Tk bind tags).
        damper.configure_event(object(), 300, 40)
        assert damper.calls == [], "a child's resize suspended painting"

        damper.configure_event(damper, 900, 700)
        damper.configure_event(damper, 920, 700)
        damper.settle()
        damper.calls.clear()
        # Same size again = the window was moved, not resized.
        damper.configure_event(damper, 920, 700)
        assert damper.calls == [], "a window move suspended painting"
        assert damper._resize_job is None, "a window move armed the settle timer"
    finally:
        root.destroy()


def test_c_the_settle_timer_is_armed_even_if_the_old_one_will_not_cancel():
    root, damper, _pm = _damper()
    if root is None:
        return
    try:
        import tkinter as tk

        def refuse(_job):
            raise tk.TclError("bad event id")

        damper.after_cancel = refuse
        damper.configure_event(damper, 900, 700)
        damper.configure_event(damper, 920, 700)     # cancelling this one throws
        damper.configure_event(damper, 940, 700)     # …and this one too
        assert damper._resize_job is not None, "painting could never come back"
        assert damper._paint_off is True
    finally:
        root.destroy()


def test_d_resuming_twice_asks_windows_once():
    root, damper, _pm = _damper()
    if root is None:
        return
    try:
        damper.configure_event(damper, 900, 700)
        damper.configure_event(damper, 920, 700)
        damper.settle()
        damper.settle()
        assert damper.calls == ["off", "on", "redraw"], damper.calls
    finally:
        root.destroy()


class _Front:
    """A Panel stand-in for `_show`: enough of it to see what the switch repaints.

    `_show` is the profile switch — the sash, the title, the menu, the activity strip
    — and every one of those is somebody else's test. What is pinned here is the last
    line of it: the page that has just come to the front is INVALIDATED, so a page Tk
    drew while another profile was in front cannot stay blank (#1210).
    """

    def __init__(self, pm, page):
        self._pm = pm
        self._page = page
        self.repainted = []
        self.resumed = 0
        self._current_session = None
        self._menu_lang = "ru"
        self._i18n = types.SimpleNamespace(lang="ru")
        self._profile_var = types.SimpleNamespace(set=lambda _name: None)

    def show(self, session):
        self._pm.Panel._show(self, session)

    # -- what `_show` reaches for --------------------------------------------
    def _resume_painting(self):
        self.resumed += 1

    def _repaint_page(self, page):
        self.repainted.append(page)

    def _saved_sash(self):
        return 0

    def _apply_sash(self, _sash):
        pass

    def _t(self, key, **_fmt):
        return key

    def title(self, _text):
        pass

    def _paint_activity(self):
        pass


def test_e_the_page_brought_to_the_front_is_repainted():
    root, damper, pm = _damper()
    if root is None:
        return
    try:
        page = types.SimpleNamespace(update_idletasks=lambda: None)
        front = _Front(pm, page)
        front.show(types.SimpleNamespace(name="beta", page=page))
        assert front.resumed == 1, "the switch did not put painting back"
        assert front.repainted == [page], \
            f"the page that came to the front was never invalidated: {front.repainted}"

        # A session with no page yet (it is still being built) is not a repaint.
        front.repainted.clear()
        front.show(types.SimpleNamespace(name="gamma", page=None))
        assert front.repainted == [], front.repainted
    finally:
        root.destroy()


def test_f_repainting_a_page_that_is_going_away_is_not_fatal():
    """The real `_repaint_page`, against nothing and against a dead widget."""
    root, damper, pm = _damper()
    if root is None:
        return
    try:
        import tkinter as tk

        pm.Panel._repaint_page(damper, None)          # no page at all
        frame = tk.Frame(root)
        frame.destroy()
        pm.Panel._repaint_page(damper, frame)         # a widget that is gone
    finally:
        root.destroy()


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
