r"""«Стоп всё» has an undo, and being stopped is VISIBLE (task #1262).

The emergency button was half a control. It stops every monitor, every watcher, the
sweep, a running scenario and the schedule — and then says so in one line in the log,
which scrolls away. Afterwards nothing on screen says the panel is holding still: a
stopped profile looks exactly like an idle one.

On 2026-08-06 that cost seven hours. «Стоп всё» was pressed at 12:44; the client lost
its server at 18:58, died at 20:02, and was still dead two hours later with the panel
open in front of somebody the whole time.

Three things are pinned here, and the second is the one with teeth:

  * the mark exists and carries a NUMBER — «остановлено» is ignorable, «остановлено 47
    минут» is not;
  * «Включить обратно» restores what was ON, not everything there is. A watcher the
    person had deliberately left off must not come back running, or the undo becomes a
    start-everything nobody asked for;
  * both front-ends read one object and offer the press on the same terms.

No Tk, no game.

    C:\Python312\python.exe tests\test_panel_panic_resume.py
    python3 tests/test_panel_panic_resume.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

try:
    from panel.runtime import panic as panicmod  # noqa: E402
except Exception as _exc:                        # noqa: BLE001
    panicmod, _WHY = None, _exc


class _Var:
    """A Tk BooleanVar's whole surface, as a tab uses it."""

    def __init__(self, value=False):
        self._v = bool(value)

    def get(self):
        return self._v

    def set(self, v):
        self._v = bool(v)


# --- the mark ---------------------------------------------------------------
def test_a_running_profile_is_not_marked():
    p = panicmod.Panic()
    assert p.stopped is False
    assert p.state(1000.0) == {"stopped": False, "for_sec": 0, "count": 0}


def test_the_mark_carries_how_long_because_a_number_is_what_makes_it_uncomfortable():
    p = panicmod.Panic()
    p.mark(1000.0)
    st = p.state(1000.0 + 47 * 60)
    assert st["stopped"] is True
    assert st["for_sec"] == 47 * 60, st
    assert st["count"] == 1


def test_switching_back_on_clears_the_mark_but_not_the_tally():
    p = panicmod.Panic()
    p.mark(1000.0)
    p.clear()
    assert p.stopped is False
    assert p.state(2000.0)["count"] == 1, "pressed-and-forgot must not look like never"
    p.mark(3000.0)
    assert p.state(3000.0)["count"] == 2


# --- who may carry the press out --------------------------------------------
def test_a_process_that_is_not_the_panel_offers_no_press():
    """`python -m panel.tabs.<id>` registers nothing — there is no shell to undo with."""
    panicmod.set_handler(None)
    try:
        assert panicmod.available() is False
        assert panicmod.run() is False
    finally:
        panicmod.set_handler(None)


def test_the_shell_registers_how_and_the_press_runs_it():
    calls = []
    panicmod.set_handler(lambda: calls.append(1))
    try:
        assert panicmod.available() is True
        assert panicmod.run() is True
        assert calls == [1]
    finally:
        panicmod.set_handler(None)


# --- the undo restores what WAS on ------------------------------------------
def _timers_tab_pair():
    """The Timers tab's panic/resume pair, exercised off a stand-in switch.

    Driven through the real methods rather than a copy of them: the point of the test
    is that the tab remembers, and a re-implementation here would remember perfectly
    while the tab did not.
    """
    from panel.tabs import timers as timerstab

    tab = timerstab.TimersTab.__new__(timerstab.TimersTab)
    return tab


def test_the_schedule_comes_back_only_if_it_was_on():
    tab = _timers_tab_pair()
    for was_on in (True, False):
        tab._sched_var = _Var(was_on)
        tab.panic()
        assert tab._sched_var.get() is False, "panic left the schedule running"
        tab.resume()
        assert tab._sched_var.get() is was_on, (
            f"resume put the schedule at {tab._sched_var.get()} when it had been {was_on}")


def test_resume_twice_does_not_start_what_the_person_has_since_switched_off():
    """The undo is spent once. A second press must not resurrect it."""
    tab = _timers_tab_pair()
    tab._sched_var = _Var(True)
    tab.panic()
    tab.resume()
    tab._sched_var.set(False)          # the person turns it off by hand afterwards
    tab.resume()
    assert tab._sched_var.get() is False, "a second resume overrode a deliberate choice"


def test_every_tab_that_switches_something_off_can_put_it_back():
    """A tab with a `panic` that moves a switch needs the matching `resume`.

    Read off the source rather than a list, so a tab that grows a switch tomorrow is
    covered without anybody remembering this file. Tabs whose panic only disarms a tick
    are exempt — they re-arm themselves when the tab is next shown.
    """
    import re

    base = (ROOT / "panel" / "tabs")
    missing = []
    for path in sorted(list(base.glob("*.py")) + list(base.glob("*/tab.py"))):
        src = path.read_text(encoding="utf-8")
        m = re.search(r"\n    def panic\(self\)[^\n]*:\n(.*?)(?=\n    def )", src, re.S)
        if not m:
            continue
        body = m.group(1)
        if ".set(False)" not in body:
            continue                    # disarms only — nothing to remember
        if "\n    def resume(self)" not in src:
            missing.append(path.relative_to(ROOT).as_posix())
    assert not missing, f"panic switches something off with no resume: {missing}"


# --- both front-ends ---------------------------------------------------------
def test_both_front_ends_read_one_object_and_offer_the_same_press():
    host = (ROOT / "panel" / "runtime" / "host.py").read_text(encoding="utf-8")
    assert "self.panic" in host, "the runtime does not hold it"

    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "panicmod.set_handler(self._resume)" in shell, "the shell never says how"
    assert '"panic.resume"' in shell, "the window has no button"
    assert "_paint_panic" in shell, "the window never draws the mark"
    assert "self._rt.panic.mark(" in shell, "«Стоп всё» never marks the profile"

    api = (ROOT / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert "rt.panic.state(" in api, "the phone is not sent the mark"
    assert "/api/panic" in api, "the phone has no route to press it"

    page = (ROOT / "panel" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "state.panic" in page and "panic.resume" in page, "the page ignores both"


def test_the_phone_may_not_press_it_into_a_running_profile():
    """That would put back switches somebody has since turned off by hand."""
    api = (ROOT / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    at = api.index("def resume(self")
    body = api[at:api.index("\n    # --", at)]
    assert "rt.panic.stopped" in body and "unavailable" in body, body[:400]


def test_all_three_words_are_in_every_shipped_locale():
    import json

    keys = ("panic.mark", "panic.resume", "panic.resumed")
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in locale]
        assert not missing, f"{path.name}: {missing}"


def _main() -> int:
    if panicmod is None:
        print(f"  SKIP the runtime package will not import here: {_WHY}")
        return 0
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
