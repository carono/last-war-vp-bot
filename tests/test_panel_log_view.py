r"""The log after it left the shell (#1391).

The pane that had lived on «Главная» since the panel had one page is «Разработка»'s now,
and the half of it that is NOT a widget — the stamped history, the drain, the mirror
into `panel.log` — is `panel/runtime/log_view.py`'s. Which is the whole risk of the
move, and what this file is about:

  * **the spool runs whether or not anybody is drawing.** Most profiles do not have
    «Разработка» switched on, and the ones that do only build it when somebody first
    looks (`PanelTab.LAZY`). A queue nobody drains grows for ever and a `panel.log`
    nobody writes is a session with no record of itself — so the pump is the shell's
    clock and the pane is optional underneath it;
  * **a pane opened an hour in shows the hour**, because the history is the spool's and
    not the widget's;
  * **the shell keeps none of it.** The widget, the filter, the trim, the redraw and the
    clickable coordinate are gone from `panel/__main__.py`, and what is left there is
    one method that pumps;
  * **the record did not move.** `panel.log` is written by the drain, and the phone's
    «Лог» screen is the web front-end's own — neither depends on a tab being on.

Tk is imported (the pane's module is), but no display is needed: everything here is the
spool, plus source checks. Hence `ui`:

    C:\Python312\python.exe tests\test_panel_log_view.py
"""
from __future__ import annotations

TIER = "ui"        # imports tkinter (not a display) — see tools/run_tests.py

import queue
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime.log import LogBus                       # noqa: E402
from panel.runtime.log_view import LogSpool                # noqa: E402


class _Pane:
    """A pane that counts, so the spool can be tested with no display at all."""

    def __init__(self, keep: str = "") -> None:
        self.drawn: list = []
        self.settled = 0
        self.keep = keep                     # "" = draw everything

    def append(self, stamp: str, line: str, scroll: bool = True) -> bool:
        if self.keep and self.keep not in line:
            return False
        self.drawn.append((stamp, line))
        return True

    def settle(self) -> None:
        self.settled += 1


def _bus(tmp: "Path | None" = None) -> LogBus:
    bus = LogBus()
    if tmp is not None:
        bus.open_file(str(tmp))
    return bus


# -- the spool without a widget -----------------------------------------------

def test_a_profile_with_no_pane_still_drains_and_still_writes_the_record(tmp=None):
    """The reason the drain is not part of the pane.

    «Разработка» ships off, so for most profiles there is never a widget — and every
    line still has to reach `panel.log` and leave the queue.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "panel.log"
        bus = _bus(path)
        spool = LogSpool(bus)
        for n in range(5):
            bus.say("panel", f"line {n}")
        assert bus.pending() == 5
        assert spool.pump() == 0, "nothing was drawn, and nothing claimed to be"
        assert bus.pending() == 0, "the queue was left to grow"
        assert len(spool) == 5, "the history is empty with nobody drawing"
        bus.close_file()
        written = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(written) == 5, written
        assert written[0].endswith("[panel] line 0"), written[0]


def test_a_pane_opened_late_is_handed_the_whole_session():
    """A tab nobody has looked at is built on the first look — an hour in, say."""
    bus = _bus()
    spool = LogSpool(bus)
    for n in range(3):
        bus.put(f"[panel] before {n}")
    spool.pump()

    pane = _Pane()
    spool.attach(pane)
    # What `LogPane.__init__` does last: draw what is already there.
    for stamp, line in spool.lines():
        pane.append(stamp, line, scroll=False)
    assert [line for _s, line in pane.drawn] == [f"[panel] before {n}" for n in range(3)]

    bus.put("[panel] after")
    spool.pump()
    assert pane.drawn[-1][1] == "[panel] after"
    assert pane.settled == 1, "one scroll for the drain, not one per line"


def test_the_history_is_bounded_and_the_filter_can_still_redraw_from_it():
    """Twice the widget's cap: a re-filter has more than the widget ever showed."""
    bus = _bus()
    spool = LogSpool(bus, cap=10)
    for n in range(100):
        bus.put(f"[panel] {n}")
    spool.pump()
    assert 10 <= len(spool) <= 20, len(spool)
    assert spool.lines()[-1][1] == "[panel] 99", "the newest line was trimmed away"


def test_a_pane_that_raises_costs_its_own_line_and_not_the_record():
    """A log line must never be the reason a profile stops writing its log."""
    import tempfile

    class _Broken(_Pane):
        def append(self, stamp, line, scroll=True):
            raise RuntimeError("the Text is gone")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "panel.log"
        bus = _bus(path)
        spool = LogSpool(bus)
        spool.attach(_Broken())
        bus.put("[panel] one")
        bus.put("[panel] two")
        spool.pump()
        bus.close_file()
        assert bus.pending() == 0
        assert len(spool) == 2
        assert len(path.read_text(encoding="utf-8").strip().split("\n")) == 2


def test_a_detached_pane_stops_being_drawn_into():
    """The tab was closed, or the profile was. Nothing keeps a dead Text."""
    bus = _bus()
    spool = LogSpool(bus)
    pane = _Pane()
    spool.attach(pane)
    bus.put("[panel] one")
    spool.pump()
    spool.detach(pane)
    bus.put("[panel] two")
    spool.pump()
    assert [line for _s, line in pane.drawn] == ["[panel] one"]


def test_take_hands_over_one_line_at_a_time():
    """`drain()` is still there for whoever wants the list; the pump wants one."""
    bus = _bus()
    bus.put("a")
    assert bus.take() == "a"
    assert bus.take() is None


# -- the widget itself, on a real Tk root -------------------------------------

class _Rt:
    """The four things `LogPane` asks of a runtime, and nothing else."""

    def __init__(self, root, spool) -> None:
        self.root = root
        self.log_spool = spool
        self.i18n = self
        self.said: list = []

    def t(self, key: str, **fmt) -> str:
        return key

    def tr(self, widget, key: str, option: str = "text", **fmt):
        widget.configure(**{option: key})
        return widget

    def hook(self, func, key=None) -> None:
        pass

    def say(self, tag: str, key: str, **fmt) -> None:
        self.said.append((tag, key, fmt))


def test_the_pane_draws_what_is_pumped_and_the_filter_narrows_it():
    """The widget half, end to end: spool → pane → the Text a person reads."""
    import tkinter as tk

    try:
        root = tk.Tk()
    except Exception:                        # noqa: BLE001 — no display: nothing to draw
        return
    root.withdraw()
    try:
        from panel.runtime.log_view import LogPane

        bus = _bus()
        spool = LogSpool(bus)
        pane = LogPane(root, _Rt(root, spool), height=4)
        pane.frame.pack()

        bus.put("[secret] a tile")
        bus.put("[rally] a banner")
        spool.pump()
        root.update()
        shown = pane.text.get("1.0", "end")
        assert "a tile" in shown and "a banner" in shown, shown

        # …and narrowing to one producer redraws from the spool, not from the widget.
        pane.filter_var.set("secret")
        pane.redraw()
        shown = pane.text.get("1.0", "end")
        assert "a tile" in shown and "a banner" not in shown, shown

        # Clear empties both, and `panel.log` is untouched by it (it is the record).
        pane.clear()
        assert len(spool) == 0
        assert pane.text.get("1.0", "end").strip() == ""

        pane.destroy()
        assert spool.pane is None, "a destroyed pane is still on the spool"
    finally:
        root.destroy()


# -- where the log now lives --------------------------------------------------

def _source(*parts: str) -> str:
    return (_REPO.joinpath(*parts)).read_text(encoding="utf-8")


def test_the_shell_keeps_no_log_widget():
    """`panel/__main__.py` is the shell; the log was the biggest thing in it that a tab
    could own instead (`CLAUDE.md` — nothing new goes into the shell)."""
    src = _source("panel", "__main__.py")
    for gone in ("self._log =", "self._log_kept", "self._log_filter_var",
                 "def _insert_line", "def _redraw_log", "def _clear_log",
                 "def _trim_log", "def _install_log_copy", "ScrolledText(logframe"):
        assert gone not in src, f"the log widget is back in the shell: {gone!r}"
    assert "log_spool.pump" in src, "nothing drains the queue any more"


def test_the_develop_tab_draws_it():
    src = _source("panel", "tabs", "develop.py")
    assert "from ..runtime.log_view import LogPane" in src
    # …on a page of its own since #1415, built when that page is first opened. The
    # column it used to be packed into gave it a height of one pixel, so it was drawn
    # and invisible; `tests/test_panel_develop_pages.py` pins the new shape.
    assert "def _build_log" in src and "self._build_log," in src
    # The filter travels in the tab's block now, with the flat key an older profile
    # was written with named as legacy so nobody's choice is lost.
    assert '"log_filter"' in src and "LEGACY_KEYS" in src


def test_a_tab_launched_on_its_own_pumps_its_own_log():
    """`python -m panel.tabs.<id>` has no shell to keep the clock for it."""
    src = _source("panel", "tabs", "base.py")
    assert "rt.log_spool.pump" in src, "a standalone tab leaves its queue growing"


def test_the_phones_log_screen_did_not_move_with_it():
    """The web front-end's «Лог» is its own screen, off the tapped bus — not this tab's.

    Which is why moving the window's pane onto a `WEB_SCREEN = False` tab did not take
    the log away from anybody holding a phone.
    """
    src = _source("panel", "web", "api.py")
    assert "/api/log" in src
    assert "rt.log.tap" in src, "the phone's feed stopped riding the bus's tap"


def test_the_develop_tab_still_has_no_screen_on_the_phone():
    """The standing divergence is untouched by the move (`CLAUDE.md`)."""
    from panel.tabs import BY_ID

    cls = BY_ID["develop"].load()
    assert cls.WEB_SCREEN is False, "«Разработка» grew a phone screen"


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
