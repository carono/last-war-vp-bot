r"""«Профиль работает» — one switch per profile, and it survives a restart (task #1882).

It was a pair of buttons: «Стоп всё» closed the client and stopped the daemon, «Включить
обратно» brought it back, and the state between them lived in memory. So a panel
restarted five minutes after the press came up starting the daemon and putting the client
back — an account somebody had deliberately stopped, farming again, with nothing anywhere
saying why. The mark was the fix for the same fault at a smaller scale (#1262): «Стоп
всё» was pressed at 12:44 on 2026-08-06, the client lost its server at 18:58, died at
20:02, and was still dead two hours later with the panel open in front of somebody.

What is pinned here:

  * the switch is a SETTING — it is read from the profile's own knob, so a new panel over
    the same profile finds it exactly as it was left;
  * the mark carries a NUMBER — «выключен» is ignorable, «выключен 47 минут» is not;
  * one object, both front-ends: the window's box and the phone's are the same flag and
    the same two acts, and neither may grow a meaning of its own;
  * the tab-level `panic`/`resume` pair still restores what was ON, not everything there
    is — uncalled since #1393, and pinned because the day something asks a tab to hold
    still again it will already be right.

No Tk, no game.

    C:\Python312\python.exe tests\test_panel_power_switch.py
    python3 tests/test_panel_power_switch.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

try:
    from panel.runtime import power as powermod  # noqa: E402
except Exception as _exc:                        # noqa: BLE001
    powermod, _WHY = None, _exc


class _Var:
    """A Tk BooleanVar's whole surface, as a tab uses it."""

    def __init__(self, value=False):
        self._v = bool(value)

    def get(self):
        return self._v

    def set(self, v):
        self._v = bool(v)


# --- the switch --------------------------------------------------------------
def _switch(saved=None):
    """A Power over a store with no widgets — a profile's file, and nothing else."""
    power = powermod.Power()
    if saved:
        power._settings.values = dict(saved)
    return power


def test_a_profile_nobody_has_touched_works():
    power = _switch()
    assert power.on is True
    assert power.off is False
    assert power.state(1000.0) == {"on": True, "off_for_sec": 0, "count": 0}


def test_switching_it_off_is_written_into_the_profile_and_not_into_memory():
    """The whole of #1882: a restart of the panel must find it exactly as it was left."""
    power = _switch()
    assert power.set(False, 1000.0) is True
    assert power.off is True
    saved = power._settings.values
    assert saved[powermod.KEY] is False, saved
    assert saved[powermod.AT_KEY] == 1000.0, saved
    # …and a panel opening over that profile reads the switch back off it
    again = _switch(saved)
    assert again.off is True, "a fresh panel would have started the account again"
    assert again.since() == 1000.0, "the mark forgot when it happened"


def test_the_mark_carries_how_long_because_a_number_is_what_makes_it_uncomfortable():
    power = _switch()
    power.set(False, 1000.0)
    st = power.state(1000.0 + 47 * 60)
    assert st["on"] is False
    assert st["off_for_sec"] == 47 * 60, st
    assert st["count"] == 1


def test_switching_back_on_clears_the_mark_but_not_the_tally():
    power = _switch()
    power.set(False, 1000.0)
    assert power.set(True, 1500.0) is True
    assert power.on is True
    assert power.state(2000.0) == {"on": True, "off_for_sec": 0, "count": 1}, \
        "switched-off-and-forgot must not look like never switched off"
    power.set(False, 3000.0)
    assert power.state(3000.0)["count"] == 2


def test_a_flip_to_where_it_already_is_moves_nothing():
    """`set_on` acts on the answer, so a repeated press must not close a live client."""
    power = _switch()
    assert power.set(True) is False
    power.set(False, 1000.0)
    assert power.set(False, 2000.0) is False
    assert power.since() == 1000.0, "a second press restarted the clock"


def test_a_saved_string_reads_as_a_boolean():
    """A profile written by an older panel, or by hand, still says what it means."""
    for raw, expect in (("0", False), ("false", False), ("1", True), (True, True)):
        assert _switch({powermod.KEY: raw}).on is expect, raw


# --- what the flip causes ----------------------------------------------------
def test_the_act_is_the_runtimes_and_not_written_here_again():
    src = (ROOT / "panel" / "runtime" / "power.py").read_text(encoding="utf-8")
    assert "panicmod.stop(rt)" in src, "switching off does not let the link go"
    assert "panicmod.resume(rt)" in src, "switching on does not take the link back"
    acts = (ROOT / "panel" / "runtime" / "panic.py").read_text(encoding="utf-8")
    assert "let_link_go" in acts, acts[:400]
    # AND THE CLIENT IS NEVER CLOSED BY IT (#2824). The switch is about the PANEL —
    # «только работу панели выключать для этого профиля» — so somebody who stops it in
    # order to play that account by hand keeps their game. Closing a client is a press
    # of its own on «Состояние» (`panel/runtime/game_control.py`).
    body = acts[acts.index("def stop(rt)"):acts.index("def let_link_go(rt)")]
    assert "play_async" not in body, f"switching a profile off plays a scenario: {body}"


def test_the_boot_asks_the_switch_before_it_takes_the_link():
    """The one place that takes the client without asking the gate has to ask this."""
    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    at = shell.index('self._boot_at("splash.link"')
    window = shell[at:at + 800]
    assert "power.on" in window and "_ensure_link()" in window, window[:400]


def test_nothing_automatic_may_run_while_the_switch_is_off():
    """The gate reads the flag, so a daemon started by hand opens nothing."""
    gate = (ROOT / "panel" / "runtime" / "gate.py").read_text(encoding="utf-8")
    assert "_switched_off" in gate, "the gate never asks the switch"
    body = gate[gate.index("    def _read(self)"):gate.index("    def _switched_off")]
    assert "self._switched_off()" in body, body[:400]


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
def test_both_front_ends_read_one_object_and_offer_the_same_switch():
    host = (ROOT / "panel" / "runtime" / "host.py").read_text(encoding="utf-8")
    assert "self.power" in host, "the runtime does not hold it"

    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert '"power.on"' in shell, "the window has no box"
    assert 'self._opt_vars["profile_on"]' in shell, "the box is not bound to the knob"
    assert "powermod.set_on(self._rt" in shell, "the window's box carries nothing out"
    assert "_paint_power" in shell, "the window never draws the mark"
    # AND NOT THE BUTTONS IT REPLACED. Two ways to say the same thing is how the two
    # front-ends came to stop different amounts of the same profile (#1393).
    assert "panic.stop_all" not in shell, "«Стоп всё» is still on «Главная»"
    assert "panic.resume" not in shell, "«Включить обратно» is still on «Главная»"

    api = (ROOT / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert "rt.power.state(" in api, "the phone is not sent the mark"
    assert "/api/power" in api, "the phone has no route to move it"
    assert "powermod.set_on(rt" in api, "the phone's press carries nothing out"

    page = (ROOT / "panel" / "web" / "app" / "src" / "views" / "StateView.tsx").read_text(
        encoding="utf-8")
    assert "state.power" in page and "'/api/power'" in page, "the page ignores it"
    assert "power.on" in page, "the phone draws no box"
    assert "power.mark" in page, "the phone draws no mark for a stopped profile"


def test_the_phone_flips_the_same_switch_on_the_tk_thread():
    """The knob is a widget: a write that only touched the file is undone by the next save."""
    api = (ROOT / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    at = api.index("def power(self")
    body = api[at:api.index("\n    # --", at)]
    assert "_on_tk(" in body and "set_on(" in body, body[:400]


def test_all_the_words_are_in_every_shipped_locale():
    import json

    keys = ("power.on", "power.mark", "power.log.boot_off",
            "gate.log.off", "timers.log.skip_off")
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in locale]
        assert not missing, f"{path.name}: {missing}"


# --- a widget that wrote the flag first still gets its acts (#1910) ----------

class _RTPower:
    """Just enough runtime for `set_on`: a switch over a store with no widgets."""

    def __init__(self, saved=None):
        self.power = _switch(saved)


def _acts():
    """Capture the two acts `set_on` causes, and put `panic` back afterwards."""
    seen = {"stop": 0, "resume": 0}
    was = (powermod.panicmod.stop, powermod.panicmod.resume)
    powermod.panicmod.stop = lambda rt: seen.__setitem__("stop", seen["stop"] + 1)
    powermod.panicmod.resume = lambda rt: seen.__setitem__("resume", seen["resume"] + 1)
    return seen, was


def _restore(was):
    powermod.panicmod.stop, powermod.panicmod.resume = was


def test_a_widget_that_wrote_the_flag_first_still_gets_its_two_acts():
    """The window's checkbox is bound to the knob, and that used to swallow the flip.

    `ttk.Checkbutton` writes the variable and THEN calls its command, so by the time the
    shell asks `set_on` the flag already holds what the person asked for. `Power.set`
    answered «nothing moved» — correctly — and `set_on` returned on it, so ticking the
    box back on wrote a `True` and started no daemon at all: «демон не стартует», live on
    2026-08-24 (#1910). `written=True` is the window saying «the write was mine».
    """
    seen, was = _acts()
    try:
        rt = _RTPower({powermod.KEY: False})       # the checkbox already flipped it off
        assert rt.power.off is True
        assert powermod.set_on(rt, False, written=True) is True
        assert seen["stop"] == 1, "the flip closed no client and stopped no daemon"

        rt = _RTPower({powermod.KEY: True})        # …and back on, the same way
        assert powermod.set_on(rt, True, written=True) is True
        assert seen["resume"] == 1, "ticking it back on brought nothing back"
    finally:
        _restore(was)


def test_without_that_word_a_flip_to_where_it_already_is_still_does_nothing():
    """The phone writes through `set`, so «already there» has to stay a no-op for it."""
    seen, was = _acts()
    try:
        rt = _RTPower({powermod.KEY: False})
        assert powermod.set_on(rt, False) is False
        assert seen == {"stop": 0, "resume": 0}, seen
    finally:
        _restore(was)


def test_the_stamp_follows_a_flag_a_widget_wrote():
    """`profile_off_at` has to be written even when `set` did not do the writing.

    Live it was `profile_on=False` beside `profile_off_at=0.0`, so the mark on screen
    counted «выключен 0 минут» however long it had been off — the number that is the
    whole point of the mark (#1882).
    """
    seen, was = _acts()
    try:
        rt = _RTPower({powermod.KEY: False})
        powermod.set_on(rt, False, written=True)
        assert rt.power.since() > 0.0, "the flip left no timestamp to count from"
    finally:
        _restore(was)


def _main() -> int:
    if powermod is None:
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
