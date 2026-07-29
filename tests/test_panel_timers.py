r"""The panel's schedule — what comes due, what is written down, what is skipped.

The Timers tab (task #1118) is a standing order like «Автолут ★»: while a row is
ticked the panel runs that action once its period has passed, remembering across
restarts when it last ran. The part that can quietly go wrong is the bookkeeping —
a failed run counted as a run means an hour of production left in the buildings,
and a period re-read from a mistyped box means a press every tick — so that is
what is tested here:

  * a timer that has never run is due at once, and one just run is not;
  * a switched-off row is never due, whatever its clock says;
  * a run is written down; a FAILED run is not, and is held back from re-firing
    every tick;
  * "the panel is busy" abandons the tick instead of queueing presses;
  * the gate (game not running) holds everything and complains once, not per tick;
  * a garbled config (empty period, a string from the spinbox, a missing block)
    falls back to the timer's default instead of dropping the row.

``panel.timers`` imports no Tk and never touches the game, so this runs anywhere::

    python3 tests/test_panel_timers.py
    C:\Python312\python.exe tests\test_panel_timers.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from panel import timers as timersmod  # noqa: E402

BASE = "collect_base_resources"
GIFTS = "collect_alliance_gifts"
TECH = "donate_alliance_tech"


def _cfg(**minutes) -> dict:
    """Config with the named timers on at the given period, the rest off."""
    cfg = timersmod.default_config()
    for key, mins in minutes.items():
        cfg[key] = {"enabled": True, "minutes": mins}
    return cfg


def _store(tmp: Path) -> timersmod.LastRunStore:
    return timersmod.LastRunStore(str(tmp / "timers.json"))


class _Scheduler:
    """A TimerScheduler with the runner and the log captured."""

    def __init__(self, tmp: Path, config: dict, outcome=True, gate=None):
        self.ran: list = []
        self.logs: list = []
        self.outcome = outcome          # True / False / an Exception to raise
        self.store = _store(tmp)
        self.sched = timersmod.TimerScheduler(
            store=self.store, config=lambda: config, runner=self._run,
            log=lambda key, **fmt: self.logs.append(key), gate=gate)

    def _run(self, spec):
        self.ran.append(spec.key)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_due_never_run_then_waits_out_its_period():
    """No record = never collected = due now; a fresh run resets the clock."""
    now = time.time()
    cfg = _cfg(**{BASE: 60})
    assert timersmod.due_keys(cfg, {}, now) == [BASE]

    just_ran = {BASE: {"last_run": now - 59 * 60}}
    assert timersmod.due_keys(cfg, just_ran, now) == []

    an_hour_ago = {BASE: {"last_run": now - 61 * 60}}
    assert timersmod.due_keys(cfg, an_hour_ago, now) == [BASE]


def test_switched_off_is_never_due():
    """An unticked row does not fire, however long since it last ran."""
    cfg = timersmod.default_config()          # everything off
    stale = {key: {"last_run": 0.0} for key in timersmod.BY_KEY}
    assert timersmod.due_keys(cfg, stale, time.time()) == []


def test_most_overdue_goes_first():
    """Several due at once are offered worst-first, so nothing starves."""
    now = time.time()
    cfg = _cfg(**{BASE: 60, GIFTS: 60, TECH: 60})
    records = {BASE: {"last_run": now - 2 * 3600},     # 1 h overdue
               GIFTS: {"last_run": now - 5 * 3600},    # 4 h overdue
               TECH: {"last_run": now - 90 * 60}}      # 30 min overdue
    assert timersmod.due_keys(cfg, records, now) == [GIFTS, BASE, TECH]


def test_a_run_is_recorded_and_stops_the_next_tick():
    """One tick fires the due timer; the following tick has nothing to do."""
    tmp = Path(tempfile.mkdtemp())
    s = _Scheduler(tmp, _cfg(**{BASE: 60}))
    assert s.sched.tick_once() == [BASE], s.ran
    assert s.sched.tick_once() == [], s.ran

    # …and it is on disk, so a restart does not collect the base again.
    saved = json.loads((tmp / "timers.json").read_text(encoding="utf-8"))
    assert saved[BASE]["last_run"] > 0, saved
    assert timersmod.LastRunStore(str(tmp / "timers.json")).last_run(BASE) > 0


def test_a_failed_run_is_not_a_run_and_is_held_back():
    """A raising action leaves the clock alone but does not re-fire every tick."""
    tmp = Path(tempfile.mkdtemp())
    s = _Scheduler(tmp, _cfg(**{BASE: 60}), outcome=RuntimeError("game closed"))
    assert s.sched.tick_once() == []
    assert s.ran == [BASE], s.ran
    assert s.store.last_run(BASE) == 0.0, "a failure must not count as a run"
    assert "timers.log.failed" in s.logs, s.logs

    # Next tick: still due, but parked by the retry hold — no second attempt.
    assert s.sched.tick_once() == []
    assert s.ran == [BASE], "re-fired inside the retry hold: %r" % (s.ran,)

    # Once the hold is out it is tried again, and a success clears the failure.
    s.outcome = True
    later = time.time() + timersmod.RETRY_HOLD_SEC + 1
    assert s.sched.tick_once(now=later) == [BASE], s.ran
    assert s.store.records()[BASE]["failed_at"] == 0.0, s.store.records()


def test_busy_panel_abandons_the_tick():
    """"Try later" stops the whole pass — presses are not queued behind each other."""
    tmp = Path(tempfile.mkdtemp())
    s = _Scheduler(tmp, _cfg(**{BASE: 60, GIFTS: 60, TECH: 60}), outcome=False)
    assert s.sched.tick_once() == []
    assert len(s.ran) == 1, "kept trying while the panel was busy: %r" % (s.ran,)
    assert s.store.last_run(s.ran[0]) == 0.0
    assert "timers.log.skip_busy" in s.logs, s.logs


def test_gate_holds_everything_and_says_so_once():
    """With the game closed nothing runs, and the log gets one line, not one a tick."""
    tmp = Path(tempfile.mkdtemp())
    closed = ["timers.log.skip_game"]
    s = _Scheduler(tmp, _cfg(**{BASE: 60}), gate=lambda: closed[0])
    for _ in range(5):
        assert s.sched.tick_once() == []
    assert s.ran == [], s.ran
    assert s.logs.count("timers.log.skip_game") == 1, s.logs

    # The game comes up: the timer that waited fires on the next tick.
    closed[0] = None
    assert s.sched.tick_once() == [BASE], s.ran


def test_config_is_re_derived_not_trusted():
    """Spinbox strings, junk and a missing block all resolve to something sane."""
    spec = timersmod.BY_KEY[BASE]
    cfg = timersmod.normalize_config({BASE: {"enabled": 1, "minutes": "90"}})
    assert cfg[BASE] == {"enabled": True, "minutes": 90}, cfg

    # A half-typed period keeps the row alive at its default rather than
    # silently disabling a timer the operator believes is on.
    junk = timersmod.normalize_config({BASE: {"enabled": True, "minutes": ""}})
    assert junk[BASE]["minutes"] == spec.default_minutes, junk

    # Out of bounds is clamped, not honoured.
    huge = timersmod.normalize_config({BASE: {"enabled": True, "minutes": 10 ** 6}})
    assert huge[BASE]["minutes"] == timersmod.MAX_MINUTES, huge

    # An old profile with no "timers" block: every timer present and off.
    empty = timersmod.normalize_config(None)
    assert set(empty) == set(timersmod.BY_KEY), empty
    assert not any(item["enabled"] for item in empty.values()), empty


def test_store_follows_a_profile_switch():
    """The clock belongs to the account: switching profiles re-reads the records."""
    one, two = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    store = _store(one)
    store.mark_run(BASE)
    assert store.last_run(BASE) > 0

    store.set_path(str(two / "timers.json"))
    assert store.last_run(BASE) == 0.0, "the other account looked freshly collected"
    store.set_path(str(one / "timers.json"))
    assert store.last_run(BASE) > 0, "the first account's clock was lost"


def test_next_due_reads_back_what_the_rows_show():
    """The "next run" column: off / now / a wall clock, matching due_keys."""
    now = time.time()
    spec = timersmod.BY_KEY[BASE]
    off = timersmod.default_config()
    assert timersmod.next_due(spec, off, {}) is None

    cfg = _cfg(**{BASE: 60})
    assert timersmod.next_due(spec, cfg, {}) == 0.0            # never run -> now
    due_at = timersmod.next_due(spec, cfg, {BASE: {"last_run": now}})
    assert abs(due_at - (now + 3600)) < 1, due_at


def test_timers_tab_builds_and_binds():
    """The tab itself: a row per timer, and the widgets feed the scheduler.

    Unlike everything above this needs Tk and a display — under the WSL python3
    (no tkinter) or on a headless box it says SKIP and passes. ``Panel``'s
    methods are called unbound against a stand-in, so no panel is opened, no
    profile is touched and no game is needed.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:                                  # noqa: BLE001
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    try:
        from panel.__main__ import Panel
        from panel import i18n as i18nmod
        root = tk.Tk()
    except Exception as exc:                           # noqa: BLE001
        print(f"  SKIP no display / panel deps: {exc}")
        return
    root.withdraw()
    tmp = Path(tempfile.mkdtemp())

    class _Tab:
        """A Panel stand-in carrying only what the tab builder touches."""

        def __init__(self):
            self._i18n = i18nmod.I18n("ru")
            self._tr_widgets: list = []
            self._settings: dict = {}
            self._timer_vars: dict = {}
            self._timer_rows: dict = {}
            self._timer_store = _store(tmp)
            self.afters: list = []

        _t = Panel._t
        _tr = Panel._tr
        _timer_config = Panel._timer_config
        _fmt_span = Panel._fmt_span
        _refresh_timer_rows = Panel._refresh_timer_rows

        def after(self, _ms, _fn=None):                # the 1 s re-arm, not run here
            self.afters.append(_ms)

    tab = _Tab()
    try:
        Panel._build_timers_tab(tab, ttk.Frame(root))

        assert set(tab._timer_rows) == set(timersmod.BY_KEY), tab._timer_rows
        assert tab._timer_config() == timersmod.default_config(), tab._timer_config()

        # A ticked box and a retyped period reach the scheduler unchanged…
        tab._timer_vars[BASE]["enabled"].set(True)
        tab._timer_vars[BASE]["minutes"].set("45")
        assert tab._timer_config()[BASE] == {"enabled": True, "minutes": 45}

        # …and the row repaints from the store: never run -> due now; just run ->
        # a period away.
        tab._refresh_timer_rows()
        row = tab._timer_rows[BASE]
        assert row["last"].cget("text") == tab._t("timers.never"), row["last"].cget("text")
        assert row["next"].cget("text") == tab._t("timers.due_now"), row["next"].cget("text")
        assert tab._timer_rows[GIFTS]["next"].cget("text") == tab._t("timers.off")

        tab._timer_store.mark_run(BASE)
        tab._refresh_timer_rows()
        assert row["next"].cget("text") == tab._t(
            "timers.in_span", span=tab._t("timers.span.min", n=44)), row["next"].cget("text")
    finally:
        root.destroy()


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
