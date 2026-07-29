r"""The panel's schedule — what it reads, what comes due, what is written down.

The Timers tab (task #1118) is a standing order like «Автолут ★»: while a row is
ticked the panel runs that errand once its period has passed, remembering across
restarts when it last ran. Two things can quietly go wrong — the bookkeeping (a
failed run counted as a run means an hour of production left in the buildings)
and the config (a typo in one entry must cost that entry, not the schedule) — so
that is what is tested here:

  * the catalogue comes from panel/timers.json: entries fall back field by field
    to the built-ins, junk entries are dropped with a complaint rather than an
    exception, and a missing/unreadable file falls back to the built-in list;
  * a timer that has never run is due at once, and one just run is not;
  * a switched-off row is never due, whatever its clock says;
  * the alliance errand is ONE timer of two steps, in order (donate, then gifts);
  * every scenario runs single-file on ONE worker thread — two errands due at the
    same second do not overlap, and "run now" queues instead of starting a thread;
  * a run is written down; a FAILED run is not, and is held back from re-firing
    every tick;
  * "the panel is busy" leaves the errand IN the queue (delayed, never lost);
  * the gate (game not running) holds everything and complains once, not per tick;
  * a garbled setting (empty period, a string from the spinbox, a missing block)
    falls back to the configured value instead of dropping the row.

``panel.timers`` imports no Tk and never touches the game, so this runs anywhere::

    python3 tests/test_panel_timers.py
    C:\Python312\python.exe tests\test_panel_timers.py

The last case also builds the tab for real; it says SKIP where tkinter or a
display is missing.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from panel import timers as timersmod  # noqa: E402

BASE = "collect_base_resources"
ALLY = "alliance_upkeep"          # donate, then claim the gifts


def _catalogue():
    """The built-in catalogue — what the panel runs with no config file."""
    return timersmod.default_catalogue()


def _cfg(**seconds) -> dict:
    """Settings with the named timers on at the given period, the rest off."""
    cfg = _catalogue().default_config()
    for name, period in seconds.items():
        cfg[name] = {"enabled": True, "interval_sec": period}
    return cfg


def _store(tmp: Path) -> timersmod.LastRunStore:
    return timersmod.LastRunStore(str(tmp / "timers_last_run.json"))


class _Scheduler:
    """A TimerScheduler with the runner and the log captured."""

    def __init__(self, tmp: Path, config: dict, outcome=True, gate=None,
                 catalogue=None, busy_retry: float = 0.0):
        self.ran: list = []
        self.logs: list = []
        self.outcome = outcome          # True / False / an Exception to raise
        self.store = _store(tmp)
        self.catalogue = catalogue or _catalogue()
        self.sched = timersmod.TimerScheduler(
            store=self.store, catalogue=lambda: self.catalogue,
            config=lambda: config, runner=self._run,
            log=lambda key, **fmt: self.logs.append(key), gate=gate,
            busy_retry=busy_retry)

    def _run(self, timer):
        self.ran.append(timer.name)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


# --- the config file --------------------------------------------------------

def test_the_timer_list_comes_from_the_config_file():
    """A new timer is a new JSON entry — no code change, no built-in needed."""
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "timers.json"
    path.write_text(json.dumps([
        # A built-in, overridden field by field — everything it leaves out (the
        # scenario, the label) comes from the hardcoded fallback.
        {"name": BASE, "interval_sec": 1800, "enabled": True},
        # An entry that exists nowhere in the code: inline commands, own args.
        {"name": "quick_donate", "scenario": "TAP donate_1000 xall",
         "interval_sec": 1200, "enabled": True, "args": {"limit": 5},
         "title": "Donate what is banked"},
    ]), encoding="utf-8")

    cat = timersmod.load_catalogue(str(path))
    assert cat.errors == (), cat.errors
    assert cat.names() == [BASE, "quick_donate"], cat.names()

    base = cat.by_name(BASE)
    assert base.interval_sec == 1800 and base.enabled is True
    assert base.scenario == ("collect_base_resources",), base.scenario
    assert base.label_key == "timers.item.collect_base_resources", base.label_key

    fresh = cat.by_name("quick_donate")
    assert fresh.scenario == ("TAP donate_1000 xall",), fresh.scenario
    assert fresh.args == {"limit": 5} and fresh.title == "Donate what is banked"

    # The file owns the LIST: a built-in it does not mention is not scheduled.
    assert cat.by_name(ALLY) is None, "a deleted entry came back"

    # And the switch/period from the file are defaults the profile can override.
    cfg = cat.normalize_config({BASE: {"enabled": False, "interval_sec": 600}})
    assert cfg[BASE] == {"enabled": False, "interval_sec": 600}, cfg
    assert cfg["quick_donate"]["enabled"] is True, cfg


def test_a_broken_entry_costs_that_entry_not_the_schedule():
    """Junk is dropped with a complaint; what is left still runs."""
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "timers.json"
    path.write_text(json.dumps([
        {"name": BASE},                              # fine: all defaults
        {"scenario": "whatever"},                    # no name
        "not an object",
        {"name": "no_scenario_anywhere"},            # nothing to run
        {"name": BASE, "interval_sec": 99},          # duplicate
        {"name": "odd", "scenario": "LOG \"hi\"", "interval_sec": "not a number"},
    ]), encoding="utf-8")

    cat = timersmod.load_catalogue(str(path))
    assert cat.names() == [BASE, "odd"], cat.names()
    assert len(cat.errors) == 4, cat.errors
    # The unreadable period falls back rather than dropping the row.
    assert cat.by_name("odd").interval_sec == timersmod.DEFAULT_INTERVAL_SEC
    # The first spelling of a duplicate wins; the later one is ignored.
    assert cat.by_name(BASE).interval_sec == 3600, cat.by_name(BASE)


def test_a_missing_file_is_seeded_and_a_broken_one_falls_back():
    """There is always something on disk to edit, and always a schedule to run."""
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "timers.json"

    cat = timersmod.load_catalogue(str(path))
    assert cat.names() == [BASE, ALLY], cat.names()
    assert path.exists(), "the config file was not seeded"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert [e["name"] for e in written] == [BASE, ALLY], written
    assert written[1]["scenario"] == ["donate_alliance_tech",
                                      "collect_alliance_gifts"], written[1]

    path.write_text("{ this is not json", encoding="utf-8")
    broken = timersmod.load_catalogue(str(path))
    assert broken.names() == [BASE, ALLY], broken.names()
    assert broken.errors, "a broken file must say so"


# --- what is due ------------------------------------------------------------

def test_due_never_run_then_waits_out_its_period():
    """No record = never collected = due now; a fresh run resets the clock."""
    now = time.time()
    cat, cfg = _catalogue(), _cfg(**{BASE: 3600})
    assert cat.due_names(cfg, {}, now) == [BASE]

    just_ran = {BASE: {"last_run": now - 59 * 60}}
    assert cat.due_names(cfg, just_ran, now) == []

    an_hour_ago = {BASE: {"last_run": now - 61 * 60}}
    assert cat.due_names(cfg, an_hour_ago, now) == [BASE]


def test_switched_off_is_never_due():
    """An unticked row does not fire, however long since it last ran."""
    cat = _catalogue()
    cfg = cat.default_config()                # everything off
    stale = {name: {"last_run": 0.0} for name in cat.names()}
    assert cat.due_names(cfg, stale, time.time()) == []


def test_most_overdue_goes_first():
    """Several due at once are offered worst-first, so nothing starves."""
    now = time.time()
    cat, cfg = _catalogue(), _cfg(**{BASE: 3600, ALLY: 3600})
    records = {BASE: {"last_run": now - 2 * 3600},     # 1 h overdue
               ALLY: {"last_run": now - 5 * 3600}}     # 4 h overdue
    assert cat.due_names(cfg, records, now) == [ALLY, BASE]


def test_the_alliance_errand_is_one_timer_of_two_steps():
    """Donate and gifts share a switch, a period and a clock — and their order."""
    timer = _catalogue().by_name(ALLY)
    assert timer.scenario == ("donate_alliance_tech", "collect_alliance_gifts")

    # One tick = one errand = both steps, once. The runner is the panel's, so
    # what is checked here is that the scheduler hands the pair over as a unit.
    tmp = Path(tempfile.mkdtemp())
    s = _Scheduler(tmp, _cfg(**{ALLY: 3600}))
    assert s.sched.tick_once() == [ALLY], s.ran
    assert s.ran == [ALLY], s.ran
    assert s.sched.tick_once() == [], "the pair re-fired inside its period"


# --- running ----------------------------------------------------------------

def test_a_run_is_recorded_and_stops_the_next_tick():
    """One tick fires the due timer; the following tick has nothing to do."""
    tmp = Path(tempfile.mkdtemp())
    s = _Scheduler(tmp, _cfg(**{BASE: 3600}))
    assert s.sched.tick_once() == [BASE], s.ran
    assert s.sched.tick_once() == [], s.ran

    # …and it is on disk, so a restart does not collect the base again.
    saved = json.loads((tmp / "timers_last_run.json").read_text(encoding="utf-8"))
    assert saved[BASE]["last_run"] > 0, saved
    assert _store(tmp).last_run(BASE) > 0


def test_a_failed_run_is_not_a_run_and_is_held_back():
    """A raising scenario leaves the clock alone but does not re-fire every tick."""
    tmp = Path(tempfile.mkdtemp())
    s = _Scheduler(tmp, _cfg(**{BASE: 3600}), outcome=RuntimeError("game closed"))
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


def test_a_busy_panel_delays_the_errand_but_never_loses_it():
    """"Try later" stops the pass and leaves the work in the queue, not on the floor."""
    tmp = Path(tempfile.mkdtemp())
    s = _Scheduler(tmp, _cfg(**{BASE: 3600, ALLY: 3600}), outcome=False)
    assert s.sched.tick_once() == []
    assert len(s.ran) == 1, "kept asking while the panel was busy: %r" % (s.ran,)
    assert s.store.last_run(s.ran[0]) == 0.0
    assert "timers.log.skip_busy" in s.logs, s.logs

    # Both are still queued — the one turned down and the one never reached.
    assert s.sched.pending() == {BASE, ALLY}, s.sched.pending()

    # The panel frees up: the queue is worked off in order, nothing re-decided.
    # The turned-down errand rejoins at the BACK — it was never started, and
    # whatever was behind it was due just as much.
    s.outcome = True
    assert s.sched.drain() == [ALLY, BASE], s.ran
    assert s.sched.pending() == set(), s.sched.pending()


def test_run_now_is_queued_not_a_thread_of_its_own():
    """The button hands work to the worker: it does not run in the caller."""
    tmp = Path(tempfile.mkdtemp())
    cat = _catalogue()
    s = _Scheduler(tmp, cat.default_config())          # every row switched OFF
    timer = cat.by_name(BASE)

    assert s.sched.request(timer) is True
    assert s.sched.pending() == {BASE}, s.sched.pending()
    assert s.ran == [], "ran inside the UI thread instead of queueing"

    # A second press while it is still waiting does not line the errand up twice.
    assert s.sched.request(timer) is False
    assert s.sched.pending() == {BASE}, s.sched.pending()

    # It runs on the worker — and it runs even though the row is switched off,
    # because a press by hand is a press.
    assert s.sched.drain() == [BASE], s.ran
    assert s.ran == [BASE], s.ran
    assert s.store.last_run(BASE) > 0, "a manual run must restart the period too"


def test_nothing_runs_in_parallel_on_the_real_worker():
    """The live thread: two errands due at once, executed one after the other.

    The only test here that starts the scheduler for real. The runner records
    what is in flight while it sleeps, so an overlap would be caught rather than
    inferred — and every run is asserted to have happened on the one worker.
    """
    tmp = Path(tempfile.mkdtemp())
    inflight: list = []
    overlaps: list = []
    finished: list = []

    def runner(timer):
        inflight.append(timer.name)
        if len(inflight) > 1:                       # two scenarios at once
            overlaps.append(tuple(inflight))
        time.sleep(0.05)
        finished.append((timer.name, threading.current_thread().name))
        inflight.pop()
        return True

    cat = _catalogue()
    sched = timersmod.TimerScheduler(
        store=_store(tmp), catalogue=lambda: cat,
        config=lambda: _cfg(**{BASE: 3600, ALLY: 3600}),
        runner=runner, log=lambda key, **fmt: None, tick=0.05)
    sched.start()
    try:
        deadline = time.time() + 5
        while len(finished) < 2 and time.time() < deadline:
            time.sleep(0.02)
    finally:
        sched.stop()

    assert len(finished) == 2, finished
    assert overlaps == [], "two timer scenarios ran at the same time: %r" % (overlaps,)
    assert {name for _key, name in finished} == {"panel-timers"}, finished
    assert {key for key, _name in finished} == {BASE, ALLY}, finished


def test_gate_holds_everything_and_says_so_once():
    """With the game closed nothing runs, and the log gets one line, not one a tick."""
    tmp = Path(tempfile.mkdtemp())
    closed = ["timers.log.skip_game"]
    s = _Scheduler(tmp, _cfg(**{BASE: 3600}), gate=lambda: closed[0])
    for _ in range(5):
        assert s.sched.tick_once() == []
    assert s.ran == [], s.ran
    assert s.logs.count("timers.log.skip_game") == 1, s.logs

    # The game comes up: the timer that waited fires on the next tick.
    closed[0] = None
    assert s.sched.tick_once() == [BASE], s.ran


def test_settings_are_re_derived_not_trusted():
    """Spinbox strings, junk and a missing block all resolve to something sane."""
    cat = _catalogue()
    cfg = cat.normalize_config({BASE: {"enabled": 1, "interval_sec": "900"}})
    assert cfg[BASE] == {"enabled": True, "interval_sec": 900}, cfg

    # A half-typed period keeps the row alive at its configured value rather than
    # silently disabling a timer the operator believes is on.
    junk = cat.normalize_config({BASE: {"enabled": True, "interval_sec": ""}})
    assert junk[BASE]["interval_sec"] == 3600, junk

    # Out of bounds is clamped, not honoured.
    huge = cat.normalize_config({BASE: {"enabled": True, "interval_sec": 10 ** 9}})
    assert huge[BASE]["interval_sec"] == timersmod.MAX_INTERVAL_SEC, huge

    # An old profile with no "timers" block: every timer present and off.
    empty = cat.normalize_config(None)
    assert set(empty) == set(cat.names()), empty
    assert not any(item["enabled"] for item in empty.values()), empty

    # A profile that still carries a timer since deleted from the config: gone.
    stale = cat.normalize_config({"was_deleted": {"enabled": True}})
    assert "was_deleted" not in stale, stale


def test_store_follows_a_profile_switch():
    """The clock belongs to the account: switching profiles re-reads the records."""
    one, two = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    store = _store(one)
    store.mark_run(BASE)
    assert store.last_run(BASE) > 0

    store.set_path(str(two / "timers_last_run.json"))
    assert store.last_run(BASE) == 0.0, "the other account looked freshly collected"
    store.set_path(str(one / "timers_last_run.json"))
    assert store.last_run(BASE) > 0, "the first account's clock was lost"


def test_next_due_reads_back_what_the_rows_show():
    """The "next run" column: off / now / a wall clock, matching due_names."""
    now = time.time()
    cat = _catalogue()
    timer = cat.by_name(BASE)
    assert cat.next_due(timer, cat.default_config(), {}) is None

    cfg = _cfg(**{BASE: 3600})
    assert cat.next_due(timer, cfg, {}) == 0.0            # never run -> now
    due_at = cat.next_due(timer, cfg, {BASE: {"last_run": now}})
    assert abs(due_at - (now + 3600)) < 1, due_at


# --- the tab itself ---------------------------------------------------------

def test_timers_tab_builds_from_the_config_and_binds():
    """The rows are drawn from the catalogue, and the widgets feed the scheduler.

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
        from panel.__main__ import Panel, _expand_args
        from panel import i18n as i18nmod
        root = tk.Tk()
    except Exception as exc:                           # noqa: BLE001
        print(f"  SKIP no display / panel deps: {exc}")
        return
    root.withdraw()
    tmp = Path(tempfile.mkdtemp())

    # A catalogue with one built-in and one timer that exists only in "the file",
    # so the row builder is exercised on both label routes.
    cat = timersmod.parse_catalogue([
        {"name": BASE, "interval_sec": 1800},
        {"name": "inline_one", "scenario": "LOG \"hello\"", "interval_sec": 600,
         "title": "Inline step"},
    ])

    class _Tab:
        """A Panel stand-in carrying only what the tab builder touches."""

        def __init__(self):
            self._i18n = i18nmod.I18n("ru")
            self._tr_widgets: list = []
            self._settings: dict = {}
            self._loading = False
            self._timer_vars: dict = {}
            self._timer_rows: dict = {}
            self._timer_catalogue = cat
            self._timer_store = _store(tmp)
            self.saves = 0
            self.afters: list = []

        _t = Panel._t
        _tr = Panel._tr
        _fill_timer_grid = Panel._fill_timer_grid
        _bind_timer_autosave = Panel._bind_timer_autosave
        _timer_config = Panel._timer_config
        _fmt_span = Panel._fmt_span
        _refresh_timer_rows = Panel._refresh_timer_rows

        def _save_settings(self):
            self.saves += 1

        def after(self, _ms, _fn=None):                # the 1 s re-arm, not run here
            self.afters.append(_ms)

    tab = _Tab()
    try:
        tab._timer_grid = ttk.Frame(root)
        tab._fill_timer_grid()

        assert set(tab._timer_rows) == {BASE, "inline_one"}, tab._timer_rows
        assert tab._timer_config()[BASE] == {"enabled": False, "interval_sec": 1800}

        # A ticked box and a retyped period reach the scheduler and are saved.
        tab._timer_vars[BASE]["enabled"].set(True)
        tab._timer_vars[BASE]["interval"].set("900")
        assert tab._timer_config()[BASE] == {"enabled": True, "interval_sec": 900}
        assert tab.saves >= 2, "the row did not autosave"

        # The rows repaint from the store: never run -> due now; just run -> a
        # period away.
        tab._refresh_timer_rows()
        row = tab._timer_rows[BASE]
        assert row["last"].cget("text") == tab._t("timers.never"), row["last"].cget("text")
        assert row["next"].cget("text") == tab._t("timers.due_now")
        assert tab._timer_rows["inline_one"]["next"].cget("text") == tab._t("timers.off")

        tab._timer_store.mark_run(BASE)
        tab._refresh_timer_rows()
        assert row["next"].cget("text") == tab._t(
            "timers.in_span", span=tab._t("timers.span.min", n=14)), row["next"].cget("text")

        # args reach an inline step as {placeholders}, and braces of the step's
        # own (Lua tables) survive untouched.
        assert _expand_args("TAP donate x{n}", {"n": 7}) == "TAP donate x7"
        assert _expand_args("LUA f({a=1})", {}) == "LUA f({a=1})"
        assert _expand_args("LUA g({b=2}) {miss}", {"n": 1}) == "LUA g({b=2}) {miss}"
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
