r"""The panel's schedule — what it reads, what comes due, what is written down.

The Timers tab (task #1118) is a standing order like «Автолут ★»: while a row is
ticked the panel runs that errand once its period has passed, remembering across
restarts when it last ran. Two things can quietly go wrong — the bookkeeping (a
failed run counted as a run means an hour of production left in the buildings)
and the config (a typo in one entry must cost that entry, not the schedule) — so
that is what is tested here:

  * the catalogue comes from the PROFILE's timers.json: a profile with none yet
    is seeded from the template, two profiles keep two schedules, entries fall
    back field by field, junk entries are dropped with a complaint rather than an
    exception, and an unreadable file falls back instead of being overwritten;
  * ticking a box writes back into that profile's file, leaving the scenario,
    the args and the title exactly as they were typed;
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
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_runtime  # noqa: E402

from panel import timers as timersmod  # noqa: E402

BASE = "collect_base_resources"
ALLY = "alliance_upkeep"          # donate, then claim the gifts
MINISTRY = "apply_ministry_interior"   # ask for the Minister of the Interior post


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

    # The seed is whatever ships in the built-in catalogue — derived from it rather
    # than hard-coded, so adding a default timer does not break this test.
    defaults = [t.name for t in timersmod.DEFAULT_TIMERS]
    assert defaults[:2] == [BASE, ALLY], defaults          # the first two are stable

    cat = timersmod.load_catalogue(str(path))
    assert cat.names() == defaults, cat.names()
    assert path.exists(), "the config file was not seeded"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert [e["name"] for e in written] == defaults, written
    assert written[1]["scenario"] == ["donate_alliance_tech",
                                      "collect_alliance_gifts"], written[1]

    # A file that cannot be read is NOT overwritten — whatever the operator typed
    # is still there to be fixed, and the panel runs on the fallback meanwhile.
    path.write_text("{ this is not json", encoding="utf-8")
    broken = timersmod.load_catalogue(str(path))
    assert broken.names() == defaults, broken.names()
    assert broken.errors, "a broken file must say so"
    assert path.read_text(encoding="utf-8") == "{ this is not json"


def test_each_profile_keeps_its_own_timers():
    """Two profiles, two schedules — seeded from the same template, then apart."""
    template = Path(tempfile.mkdtemp()) / "timers.json"
    template.write_text(json.dumps([
        {"name": BASE, "interval_sec": 1800},
        {"name": "shared_extra", "scenario": 'LOG "hi"', "interval_sec": 600},
    ]), encoding="utf-8")
    seed = timersmod.load_catalogue(str(template))

    one = Path(tempfile.mkdtemp()) / "timers.json"
    two = Path(tempfile.mkdtemp()) / "timers.json"
    first = timersmod.load_catalogue(str(one), seed_from=seed)
    second = timersmod.load_catalogue(str(two), seed_from=seed)

    # Both start as the template says…
    assert first.names() == second.names() == [BASE, "shared_extra"]
    assert first.by_name(BASE).interval_sec == 1800

    # …and then go their own way: the first account switches the base on and
    # halves its period, the second drops that timer from its list entirely.
    timersmod.save_catalogue(
        first.with_settings({BASE: {"enabled": True, "interval_sec": 900}}), str(one))
    two.write_text(json.dumps([{"name": "shared_extra", "interval_sec": 60}]),
                   encoding="utf-8")

    first = timersmod.load_catalogue(str(one), seed_from=seed)
    second = timersmod.load_catalogue(str(two), seed_from=seed)
    assert first.by_name(BASE).enabled is True
    assert first.by_name(BASE).interval_sec == 900
    assert second.by_name(BASE) is None, "the other profile's timer leaked in"
    assert second.names() == ["shared_extra"], second.names()
    # The template is untouched by either of them.
    assert timersmod.load_catalogue(str(template)).by_name(BASE).interval_sec == 1800


def test_saving_settings_leaves_the_scenario_alone():
    """The UI writes the switch and the period — never the operator's own text."""
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "timers.json"
    path.write_text(json.dumps([
        {"name": "mine", "scenario": ['LOG "one"', 'LOG "two"'], "interval_sec": 600,
         "args": {"who": "world"}, "title": "Mine"},
    ]), encoding="utf-8")
    cat = timersmod.load_catalogue(str(path))

    timersmod.save_catalogue(
        cat.with_settings({"mine": {"enabled": True, "interval_sec": 120}}), str(path))

    back = timersmod.load_catalogue(str(path)).by_name("mine")
    assert back.enabled is True and back.interval_sec == 120
    assert back.scenario == ('LOG "one"', 'LOG "two"'), back.scenario
    assert back.args == {"who": "world"} and back.title == "Mine"


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


def test_retry_hold_is_per_timer():
    """A failed timer is held for its OWN retry_sec, not a single global constant."""
    quick = timersmod.Timer(name="quick", scenario=("noop",),
                            interval_sec=3600, retry_sec=60)
    slow = timersmod.Timer(name="slow", scenario=("noop",),
                           interval_sec=3600, retry_sec=600)
    cat = timersmod.Catalogue([quick, slow])
    cfg = {"quick": {"enabled": True, "interval_sec": 3600},
           "slow": {"enabled": True, "interval_sec": 3600}}
    now = 10_000.0
    records = {"quick": {"failed_at": now - 120}, "slow": {"failed_at": now - 120}}
    # 120 s since each failed: quick's 60 s hold is out (due again), slow's 600 s is not.
    assert cat.due_names(cfg, records, now) == ["quick"], \
        cat.due_names(cfg, records, now)


def test_retry_sec_reads_from_the_file_and_round_trips():
    """retry_sec is read per entry, falls back to the default, and is written back."""
    cat = timersmod.parse_catalogue(
        [{"name": "t", "scenario": "noop", "interval_sec": 3600, "retry_sec": 45}])
    t = cat.by_name("t")
    assert t.retry_sec == 45, t.retry_sec
    assert t.as_dict()["retry_sec"] == 45, t.as_dict()
    # An entry that leaves it out falls back to the module default.
    plain = timersmod.parse_catalogue([{"name": "t", "scenario": "noop"}]).by_name("t")
    assert plain.retry_sec == int(timersmod.RETRY_HOLD_SEC), plain.retry_sec


def test_new_default_timers_carry_a_retry():
    """The three #1127 timers ship with retry_sec so an off-base FAIL is retried soon."""
    cat = _catalogue()
    for name in ("collect_truck_resources", "collect_visitor_gifts", "recruit_survivors"):
        assert cat.by_name(name).retry_sec == 300, name


def test_the_ministry_errand_is_half_hourly_either_way():
    """#1176: apply for the Minister of the Interior post every 30 minutes.

    The two periods are deliberately the same 1800 s: the wait after a successful
    application, and the hold after a refused one. `retry_sec` is what stops a scenario
    that fails on a standing condition (another post already held) from re-firing every
    tick, and here the answer to "how soon should we try again" is the same half hour
    whichever way the last attempt went.
    """
    t = _catalogue().by_name(MINISTRY)
    assert t is not None, "the built-in catalogue has no ministry errand"
    assert t.scenario == (MINISTRY,), t.scenario
    assert (t.interval_sec, t.retry_sec) == (1800, 1800), t
    assert t.enabled is False, "asking for a post is opt-in, like every other errand"
    # A profile that has never seen the errand is seeded with it, whole — the entry is
    # only a name and a scenario in the file, and everything else falls back to here.
    seeded = timersmod.parse_catalogue([{"name": MINISTRY, "scenario": MINISTRY}])
    assert (seeded.by_name(MINISTRY).interval_sec,
            seeded.by_name(MINISTRY).retry_sec) == (1800, 1800), seeded.by_name(MINISTRY)


def test_only_a_successful_application_restarts_the_ministry_clock():
    """A refused application keeps its place in the queue — it never counts as a run.

    The recipe FAILs on every ending that did not seat us at the post, so the timer sees
    a raise: `last_run` stays where it was and the errand is tried again half an hour
    later, not an hour, and not a day. The failing case is the ordinary one here — while
    another ministry post is held the server refuses every application — so a clock that
    reset on it would look like a working timer that never once applied.
    """
    tmp = Path(tempfile.mkdtemp())
    s = _Scheduler(tmp, _cfg(**{MINISTRY: 1800}),
                   outcome=RuntimeError("another ministry post is held"))
    now = time.time()
    assert s.sched.tick_once(now=now) == []
    assert s.ran == [MINISTRY], s.ran
    assert s.store.last_run(MINISTRY) == 0.0, "a refused application counted as a run"

    # Just under half an hour later: still nothing, the hold has not run out.
    assert s.sched.tick_once(now=now + 1799) == []
    assert s.ran == [MINISTRY], "re-applied inside the half-hour hold: %r" % (s.ran,)

    # Half an hour later it asks again — and a granted application starts the clock.
    s.outcome = True
    assert s.sched.tick_once(now=now + 1801) == [MINISTRY], s.ran
    assert s.store.last_run(MINISTRY) > 0, s.store.records()
    assert s.store.records()[MINISTRY]["failed_at"] == 0.0, s.store.records()

    # …and having applied, it sits out its own period rather than asking again at once.
    assert s.sched.tick_once() == [], s.ran


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


def test_the_countdown_shows_the_retry_hold_not_a_due_it_will_not_honour():
    """After a failure the row must count down the HOLD, not say «сейчас» for it.

    `last_run` does not move on a failure, so the period is already over as far as the
    old reading went — and the column said "due now" for the whole retry hold while the
    scheduler deliberately did nothing. The two must agree: whichever wait ends later is
    the one the row shows.
    """
    now = 10_000.0
    cat = _catalogue()
    timer = cat.by_name(BASE)                             # retry_sec = 300
    cfg = _cfg(**{BASE: 3600})

    # Never run, just failed: the hold is the whole answer.
    records = {BASE: {"failed_at": now}}
    assert cat.next_due(timer, cfg, records) == now + timer.retry_sec
    assert cat.due_names(cfg, records, now + 299) == []
    assert cat.due_names(cfg, records, now + 301) == [BASE]

    # Ran an hour ago and failed a minute ago: the hold outlasts the period.
    records = {BASE: {"last_run": now - 3600, "failed_at": now - 60}}
    assert cat.next_due(timer, cfg, records) == now - 60 + timer.retry_sec

    # Failed long ago, succeeded since: the failure is spent and the period rules.
    records = {BASE: {"last_run": now, "failed_at": 0.0}}
    assert cat.next_due(timer, cfg, records) == now + 3600


def test_the_row_can_tell_a_failing_errand_from_one_that_never_ran():
    """The status reading behind the «последняя попытка» column.

    Both a never-run errand and a failing one leave `last_run` at zero, so the row had
    no way to show the difference — and an errand that has been refused every half hour
    since morning looked exactly like one nobody had switched on.
    """
    assert timersmod.last_attempt({}, BASE) == (timersmod.ATTEMPT_NONE, 0.0)
    assert timersmod.last_attempt({BASE: {"failed_at": 500.0}}, BASE) == \
        (timersmod.ATTEMPT_FAILED, 500.0)

    # The later of the two wins: a success after a failure, and a failure after a
    # success, are both read off the timestamps rather than off which key exists.
    ok_then_failed = {BASE: {"last_run": 400.0, "failed_at": 500.0}}
    assert timersmod.last_attempt(ok_then_failed, BASE)[0] == timersmod.ATTEMPT_FAILED
    failed_then_ok = {BASE: {"last_run": 600.0, "failed_at": 500.0}}
    assert timersmod.last_attempt(failed_then_ok, BASE) == (timersmod.ATTEMPT_OK, 600.0)


def test_a_failure_survives_a_restart_and_a_success_clears_it():
    """The status is read off the file, so a panel reopened still shows it."""
    tmp = Path(tempfile.mkdtemp())
    store = _store(tmp)
    store.mark_failed(BASE, when=500.0)
    assert timersmod.last_attempt(_store(tmp).records(), BASE) == \
        (timersmod.ATTEMPT_FAILED, 500.0)
    store.mark_run(BASE, when=600.0)
    assert timersmod.last_attempt(_store(tmp).records(), BASE) == \
        (timersmod.ATTEMPT_OK, 600.0), "the failure outlived the run that cleared it"


def test_a_scheduled_failure_shows_up_as_one_on_the_row():
    """What the scheduler writes down is what the status column reads."""
    tmp = Path(tempfile.mkdtemp())
    s = _Scheduler(tmp, _cfg(**{BASE: 3600}),
                   outcome=RuntimeError("another ministry post is held"))
    s.sched.tick_once()
    assert timersmod.last_attempt(s.store.records(), BASE)[0] == timersmod.ATTEMPT_FAILED
    # The reason is not on the row — it is a sentence and the column is 20 characters —
    # but it must reach the log, and as the scenario's own words.
    assert "timers.log.failed" in s.logs, s.logs


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
        from panel.tabs.timers import TimersTab
        root = tk.Tk()
    except Exception as exc:                           # noqa: BLE001
        print(f"  SKIP no display / panel deps: {exc}")
        return
    root.withdraw()
    tmp = Path(tempfile.mkdtemp())

    # A profile catalogue on disk with one built-in and one timer that exists only
    # in the file, so the row builder is exercised on both label routes — and the
    # write-back has a real file to land in.
    cfg_path = tmp / "timers.json"
    cfg_path.write_text(json.dumps([
        {"name": BASE, "interval_sec": 1800},
        {"name": "inline_one", "scenario": 'LOG "hello"', "interval_sec": 600,
         "args": {"who": "world"}, "title": "Inline step"},
    ]), encoding="utf-8")
    cat = timersmod.load_catalogue(str(cfg_path))

    class _Tab(TimersTab):
        """The real tab, on a cold runtime whose schedule is just the catalogue.

        Nothing here needs a scheduler thread — the rows read a catalogue, a store and
        a queue — so the stand-in supplies exactly those three and no more.
        """

        def __init__(self):
            rt = fake_runtime.cold_runtime(root)
            rt.schedule = types.SimpleNamespace(
                timer_catalogue=cat,
                store=_store(tmp),
                # The rows read the queue to mark an errand that is waiting its turn.
                timers=types.SimpleNamespace(pending=lambda: set()),
                timer_config=lambda: rt.schedule.timer_catalogue.normalize_config(
                    self._timer_widget_config()
                    or rt.schedule.timer_catalogue.default_config()))
            rt.profiles = types.SimpleNamespace(timers_json=lambda: str(cfg_path))
            super().__init__(rt, ttk.Frame(root))
            self.logs = rt.log.lines
            self.afters: list = []
            self.cancelled: list = []
            # The repaint re-arms itself once a second; record the delay instead of
            # actually waiting it out.
            rt.tick.arm = lambda _n, ms, _f: self.afters.append(ms)
            # The trigger list is repainted at the end of the timer refresh; an empty
            # one makes that an early return, so this scheduled-only case needs no
            # trigger catalogue and no watcher.
            self._trigger_rows = {}

        def _timer_config(self):
            return self.rt.schedule.timer_config()

    tab = _Tab()
    try:
        tab._timer_grid = ttk.Frame(root)
        tab._fill_timer_grid()

        assert set(tab._timer_rows) == {BASE, "inline_one"}, tab._timer_rows
        assert tab._timer_config()[BASE] == {"enabled": False, "interval_sec": 1800}

        # A ticked box and a retyped period reach the scheduler — and land in the
        # profile's own file, leaving the other timer's scenario and args intact.
        tab._timer_vars[BASE]["enabled"].set(True)
        tab._timer_vars[BASE]["interval"].set("900")
        assert tab._timer_config()[BASE] == {"enabled": True, "interval_sec": 900}
        saved = timersmod.load_catalogue(str(cfg_path))
        assert saved.by_name(BASE).enabled is True, "the row did not autosave"
        assert saved.by_name(BASE).interval_sec == 900
        assert saved.by_name("inline_one").scenario == ('LOG "hello"',)
        assert saved.by_name("inline_one").args == {"who": "world"}

        # The rows repaint from the store: never run -> due now; just run -> a
        # period away.
        tab._refresh_timer_rows()
        row = tab._timer_rows[BASE]
        assert row["next"].cget("text") == tab.t("timers.due_now")
        assert tab._timer_rows["inline_one"]["next"].cget("text") == tab.t("timers.off")
        # Nothing has been tried yet, and the status column says so rather than
        # looking like a success.
        assert row["outcome"].cget("text") == tab.t("timers.outcome.never")

        # A failed attempt shows up as a failure, and the countdown switches to the
        # retry hold instead of claiming the errand is due now.
        tab.rt.schedule.store.mark_failed(BASE)
        tab._refresh_timer_rows()
        assert row["outcome"].cget("text") == tab.t(
            "timers.outcome.failed", ago=tab.t("timers.span.now")), \
            row["outcome"].cget("text")
        # str(): a ttk widget hands `cget` back a Tcl object, which is never == a str.
        assert str(row["outcome"].cget("foreground")) == "#c0392b", \
            row["outcome"].cget("foreground")
        assert row["next"].cget("text") != tab.t("timers.due_now"), \
            "the row claimed the errand was due while the retry hold was running"

        tab.rt.schedule.store.mark_run(BASE)
        tab._refresh_timer_rows()
        # 900 s away, give or take the second this test takes to get here — the
        # column rounds down to whole minutes, so both readings are correct.
        expected = {tab.t("timers.in_span", span=tab.t("timers.span.min", n=n))
                    for n in (14, 15)}
        assert row["next"].cget("text") in expected, row["next"].cget("text")
        # …and the success replaced the failure on the row, reason and colour with it.
        assert row["outcome"].cget("text") == tab.t(
            "timers.outcome.ok", ago=tab.t("timers.span.now")), row["outcome"].cget("text")
        assert str(row["outcome"].cget("foreground")) == "#2e7d32"

        # A queued errand is shown as queued rather than as "due now" — the
        # scheduler's own queue used to be invisible.
        tab.rt.schedule.timers = types.SimpleNamespace(pending=lambda: {BASE})
        tab._refresh_timer_rows()
        assert row["next"].cget("text") == tab.t("timers.queued"), row["next"].cget("text")
        tab.rt.schedule.timers = types.SimpleNamespace(pending=lambda: set())

        # The tab EDITS the list now, not just the switches. A copy gets a free name,
        # starts switched off, carries the original's steps and args, and lands in the
        # file — while the original is left exactly as it was.
        tab._select_timer("inline_one")
        tab._timer_duplicate()
        copy = timersmod.load_catalogue(str(cfg_path))
        assert copy.by_name("inline_one_2") is not None, copy.names()
        assert copy.by_name("inline_one_2").scenario == ('LOG "hello"',)
        assert copy.by_name("inline_one_2").args == {"who": "world"}
        assert copy.by_name("inline_one_2").enabled is False
        assert copy.by_name("inline_one").scenario == ('LOG "hello"',)
        # …and the rows were redrawn from it, so the copy is on screen.
        assert "inline_one_2" in tab._timer_rows, sorted(tab._timer_rows)

        # A timer's args reach its steps as {placeholders} — the engine does the
        # substituting now (see test_args in tests/test_game_primitives.py).
    finally:
        root.destroy()


def test_a_queued_errand_can_be_taken_back_off_the_queue():
    """«✕» on a row: cancel takes a WAITING errand off, and never kills a running one.

    The tab had no cancel at all — a «Запустить» pressed by mistake, or three errands
    queued behind a slow one, could only be waited out.
    """
    ran: list = []
    sched = timersmod.TimerScheduler(
        store=_store(Path(tempfile.mkdtemp())),
        catalogue=lambda: timersmod.default_catalogue(),
        config=lambda: {BASE: {"enabled": True, "interval_sec": 60},
                        ALLY: {"enabled": True, "interval_sec": 60}},
        runner=lambda timer: (ran.append(timer.name), True)[1],
        log=lambda key, **fmt: None)

    # Nothing queued: there is nothing to cancel, and saying so is not a lie.
    assert sched.cancel(BASE) is False

    # Two errands asked for by hand; the first is cancelled before the queue is
    # worked, so only the second runs.
    assert sched.request(timersmod.default_catalogue().by_name(BASE)) is True
    assert sched.request(timersmod.default_catalogue().by_name(ALLY)) is True
    assert sched.cancel(BASE) is True
    assert sched.drain() == [ALLY], ran
    assert ran == [ALLY], ran
    # The claim is released either way, so the errand can be asked for again — and
    # the cancel mark did NOT survive it. A mark left behind would swallow this next
    # run and look like a timer that skips a turn for no reason.
    assert sched.pending() == set(), sched.pending()
    assert sched.request(timersmod.default_catalogue().by_name(BASE)) is True
    assert sched.drain() == [BASE], ran

    # An errand already IN FLIGHT is not cancellable, and says so rather than
    # claiming a run it cannot stop. (The runner asks mid-call, which is exactly
    # when a person would press «✕».)
    verdicts: list = []
    mid = timersmod.TimerScheduler(
        store=_store(Path(tempfile.mkdtemp())),
        catalogue=lambda: timersmod.default_catalogue(),
        config=lambda: {BASE: {"enabled": True, "interval_sec": 60}},
        runner=lambda timer: (verdicts.append(mid.cancel(timer.name)), True)[1],
        log=lambda key, **fmt: None)
    mid.request(timersmod.default_catalogue().by_name(BASE))
    assert mid.drain() == [BASE], verdicts
    assert verdicts == [False], "a running errand reported itself as cancelled"


def test_a_row_can_be_added_renamed_and_deleted():
    """The catalogue edits the Timers tab performs, without a display.

    A rename is a delete plus an add on purpose: the name is the key the last-run
    record is filed under, so a renamed errand must start a fresh clock rather than
    inherit the old one's.
    """
    cat = timersmod.default_catalogue()
    assert cat.unique_name("brand_new") == "brand_new"
    assert cat.unique_name(BASE) == f"{BASE}_2"

    added = cat.replace(timersmod.Timer(name="morning",
                                       scenario=("collect_base_resources",
                                                 "donate_alliance_tech"),
                                       interval_sec=3600, enabled=True))
    assert "morning" in added.names(), added.names()
    assert len(added) == len(cat) + 1
    assert added.by_name("morning").scenario == ("collect_base_resources",
                                                "donate_alliance_tech")

    # Replacing an existing name edits it in place and keeps the order.
    edited = added.replace(timersmod.Timer(name=BASE, scenario=("something_else",),
                                          interval_sec=120))
    assert edited.names() == added.names(), edited.names()
    assert edited.by_name(BASE).scenario == ("something_else",)

    # A delete really removes it, and removing what is not there is a no-op.
    assert BASE not in edited.remove(BASE).names()
    assert edited.remove("nothing_by_that_name").names() == edited.names()

    # A switch/period edit must never rewrite the steps beside it.
    settled = edited.with_settings({"morning": {"enabled": False, "interval_sec": 7200}})
    assert settled.by_name("morning").scenario == ("collect_base_resources",
                                                   "donate_alliance_tech")
    assert settled.by_name("morning").interval_sec == 7200
    assert settled.by_name("morning").enabled is False


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
