r"""Priorities over one queue: «сразу» errands, and a press that goes first (#1288).

Everything the panel does to the game used to run single-file: one worker thread for the
schedule, one claim on the client, and a button that found either taken said «занят» and
did nothing. Measured on 2026-08-07, one profile's `panel.log`: **343 presses turned away
in a day**, and an `alliance_help` fire — a two-second press that pays nothing once the
request has closed — waiting a p90 of 8–10 s and a maximum of 1276 s for its turn.

Three things replace that, and this file is what holds them apart:

  * **a demand is a note on the door, not a lock** (`panel/runtime/claims.py`): the
    holder reads it and decides to park; nothing here can make it, which is why a run
    driving the game can never be interrupted anywhere but at its own checkpoints;
  * **the checkpoint is the interpreter's** (`Context.yield_to`, checked between
    statements, between the presses of a repeat and between the polls of a WAIT) — the
    three moments a scenario is between two thoughts rather than inside one;
  * **«сразу» is a field on the errand**, not a list of names in the code: it skips the
    shared queue and asks for the client at a level an ordinary errand steps aside for.

What must NOT change is the reason the queue was built: two chunks never go into the
game VM at once. The claim is still what serialises the panel's access — parking hands
it over, it is never shared — and the daemon's own run lock is still under that.

    python3 tests/test_panel_priority.py
    C:\Python312\python.exe tests\test_panel_priority.py
"""
from __future__ import annotations

# `ui`, and none of it draws anything: importing `panel.runtime` for the claim registry
# pulls the package in, and the package pulls the settings binder, which imports tkinter
# — absent from the WSL interpreter. See tools/run_tests.py.
TIER = "ui"

import json
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "tools" / "lib"),
           str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from panel import timers as timersmod          # noqa: E402
from panel import triggers as triggersmod      # noqa: E402
from panel.runtime import claims               # noqa: E402
from lastwar_bot import script_engine          # noqa: E402

KEY = ("127.0.0.1", 47654)


# ---------------------------------------------------------------------------
# the registry: a demand is a note, and it names the most urgent waiter
# ---------------------------------------------------------------------------
def test_a_demand_is_seen_only_by_a_holder_it_outranks():
    claims.clear()
    try:
        assert claims.acquire(KEY, "alice/timer", claims.BACKGROUND) is None
        assert claims.level(KEY) == claims.BACKGROUND

        # Nobody waiting: the run has no reason to stop.
        assert claims.wanted(KEY, claims.BACKGROUND) is None

        press = claims.demand(KEY, claims.HUMAN, "alice/rally")
        # The background run sees it…
        assert claims.wanted(KEY, claims.BACKGROUND) == "alice/rally"
        # …and a press holding the client would not: it does not step aside for itself,
        # nor for anything at its own level.
        assert claims.wanted(KEY, claims.HUMAN) is None
        # An express errand ranks between the two.
        assert claims.wanted(KEY, claims.EXPRESS) == "alice/rally"

        claims.withdraw(KEY, press)
        assert claims.wanted(KEY, claims.BACKGROUND) is None, \
            "a withdrawn demand would park every background run for a press that is " \
            "not coming"
    finally:
        claims.clear()


def test_the_most_urgent_waiter_is_the_one_named():
    claims.clear()
    try:
        claims.acquire(KEY, "alice/timer", claims.BACKGROUND)
        claims.demand(KEY, claims.EXPRESS, "alice/help")
        claims.demand(KEY, claims.HUMAN, "alice/checklist")
        assert claims.wanted(KEY, claims.BACKGROUND) == "alice/checklist"
    finally:
        claims.clear()


def test_a_free_key_is_outranked_by_everybody():
    """`level` answers BACKGROUND for a key nobody holds, and that is the right lie.

    Every caller of it is about to compare; «nobody is holding it» has to lose the
    comparison exactly as «a background errand is» does, because in both cases the
    newcomer may simply take it.
    """
    claims.clear()
    try:
        assert claims.level(KEY) == claims.BACKGROUND
    finally:
        claims.clear()


# ---------------------------------------------------------------------------
# the link: claim_soon waits for a park, park hands the client over
# ---------------------------------------------------------------------------
def _link(port: int = 47654):
    """A real GameLink with everything below the claim stubbed out.

    The claim, the demand and the park are all this module's own bookkeeping — no
    daemon is involved — so the only things replaced are the two that would reach for
    one (`client`, `up`).
    """
    from panel.runtime import daemon as daemonmod

    link = daemonmod.GameLink(
        port=lambda: port, python=lambda: "python", log=_Log(),
        env=lambda: {}, cwd=".", daemon_script="x", name=lambda: "alice")
    link._client = None                     # no lease to take: `_claim_lease` says yes
    link.up = lambda: False
    return link


class _Log:
    def __init__(self) -> None:
        self.said: list = []

    def say(self, tag, key, **fmt) -> None:
        self.said.append((tag, key, fmt))

    def put(self, line) -> None:
        self.said.append(("put", line, {}))


def test_a_press_waits_for_a_background_run_to_park_and_then_gets_in():
    claims.clear()
    try:
        errand, press = _link(), _link()
        assert errand.claim("timer", claims.BACKGROUND) is True
        # The ordinary try still fails — the client IS held, and nothing about a
        # priority takes it away from the run that has it.
        assert press.claim("rally", claims.HUMAN) is False

        parked = threading.Event()

        def background() -> None:
            # What the interpreter's checkpoint does, by hand: notice, park, resume.
            while errand.yielded_to() is None:
                time.sleep(0.01)
            parked.set()
            errand.park("timer", timeout=5.0)
            errand.release()

        thread = threading.Thread(target=background, daemon=True)
        thread.start()
        got = press.claim_soon("rally", claims.HUMAN, timeout=5.0)
        assert parked.is_set(), "the background run never saw the demand"
        assert got is True, "the press never got in"
        assert claims.holder(KEY) == "alice/rally", claims.holder(KEY)
        press.release()
        thread.join(timeout=5.0)
    finally:
        claims.clear()


def test_two_runs_never_hold_the_client_at_once():
    """The point of the queue, kept: a park HANDS the client over, it does not share it.

    Twenty presses race twenty background runs over one client; a counter records the
    largest number of holders seen at any instant. Anything but 1 is the race the whole
    arrangement exists to prevent.
    """
    claims.clear()
    try:
        inside, worst, guard = [0], [0], threading.Lock()

        def hold(link, owner, priority, park_first) -> None:
            if priority == claims.HUMAN:
                if not link.claim_soon(owner, priority, timeout=5.0):
                    return
            elif not _claim_eventually(link, owner, priority):
                return
            with guard:
                inside[0] += 1
                worst[0] = max(worst[0], inside[0])
            time.sleep(0.005)
            if park_first and link.yielded_to() is not None:
                with guard:
                    inside[0] -= 1
                if not link.park(owner, timeout=5.0):
                    return
                with guard:
                    inside[0] += 1
                    worst[0] = max(worst[0], inside[0])
                time.sleep(0.005)
            with guard:
                inside[0] -= 1
            link.release()

        threads = []
        for i in range(20):
            threads.append(threading.Thread(
                target=hold, args=(_link(), f"timer{i}", claims.BACKGROUND, True),
                daemon=True))
            threads.append(threading.Thread(
                target=hold, args=(_link(), f"press{i}", claims.HUMAN, False),
                daemon=True))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20.0)
        assert worst[0] == 1, f"{worst[0]} runs held the same client at once"
        assert claims.held() == {}, claims.held()
    finally:
        claims.clear()


def _claim_eventually(link, owner, priority, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if link.claim(owner, priority):
            return True
        time.sleep(0.005)
    return False


def test_a_press_that_nobody_outranks_is_still_refused():
    """Two presses do not push each other about — that would only reorder two things
    that both have to happen, and the second one would be pushed off by the third."""
    claims.clear()
    try:
        first, second = _link(), _link()
        assert first.claim("rally", claims.HUMAN) is True
        assert second.outranks(claims.HUMAN) is False
        assert second.claim_soon("checklist", claims.HUMAN, timeout=0.2) is False
    finally:
        claims.clear()


# ---------------------------------------------------------------------------
# the interpreter's checkpoint
# ---------------------------------------------------------------------------
def test_the_interpreter_steps_aside_between_statements_and_inside_a_wait():
    """`yield_to` is called at the three moments, and a run without one pays nothing."""
    calls = []
    ctx = script_engine.new_context(yield_to=lambda c: calls.append(c))
    script_engine.run_text('LOG "one"\nLOG "two"\nWAIT 0.01', ctx=ctx)
    assert len(calls) >= 3, f"only {len(calls)} checkpoints in a three-statement script"
    # …and it is handed the CONTEXT, because standing aside invalidates the lease the
    # run was granted and only the context can be told so.
    assert all(c is ctx for c in calls), calls

    # …and the plain form is untouched: no hook, no cost, no behaviour change.
    plain = script_engine.new_context()
    assert plain.yield_to is None
    assert script_engine.run_text('LOG "one"', ctx=plain) is True


def test_the_park_hands_the_run_a_fresh_lease_and_says_both_ends_of_it():
    """The bug this arrangement would otherwise have introduced silently.

    Standing aside lets the daemon's lease go. The run is carrying the token it was
    granted and an evaluator built with it, so unless the hook tells the context that
    both are stale, every call after the first park comes back «lease lost» — which
    reads in the log exactly like the game going deaf.
    """
    from panel.runtime.host import PanelRuntime

    said, tokens = [], iter(["first", "second"])
    game = types.SimpleNamespace(
        yielded_to=lambda: "alice/rally",
        park=lambda owner, timeout=None: True,
        token="second")
    stub = types.SimpleNamespace(
        game=game,
        log=types.SimpleNamespace(say=lambda tag, key, **fmt: said.append(key)),
        t=lambda key, **fmt: key)
    ctx = script_engine.new_context()
    ctx.game_token, ctx.evaluator = "first", object()

    PanelRuntime.yield_hook(stub, "timer")(ctx)

    assert ctx.game_token == "second", ctx.game_token
    assert ctx.evaluator is None, "the run kept an evaluator built with the old lease"
    # Both ends said, and named: «прервано ради кого» is the whole reporting rule.
    assert said == ["priority.parked", "priority.resumed"], said


def test_a_run_that_cannot_get_the_client_back_fails_rather_than_pressing_on():
    from panel.runtime.host import PanelRuntime

    game = types.SimpleNamespace(
        yielded_to=lambda: "alice/rally",
        park=lambda owner, timeout=None: False,
        token="")
    stub = types.SimpleNamespace(
        game=game,
        log=types.SimpleNamespace(say=lambda tag, key, **fmt: None),
        t=lambda key, **fmt: key)
    try:
        PanelRuntime.yield_hook(stub, "timer")(script_engine.new_context())
    except RuntimeError as exc:
        assert "priority.lost" in str(exc), exc
    else:
        raise AssertionError("the run went on driving a client it does not hold")


def test_nothing_is_said_when_nobody_is_waiting():
    """The checkpoint is in the path of every statement of every scenario — it must be
    silent and free when there is nothing to step aside for."""
    from panel.runtime.host import PanelRuntime

    said = []
    stub = types.SimpleNamespace(
        game=types.SimpleNamespace(yielded_to=lambda: None,
                                   park=lambda *a, **k: (_ for _ in ()).throw(
                                       AssertionError("parked for nobody"))),
        log=types.SimpleNamespace(say=lambda tag, key, **fmt: said.append(key)),
        t=lambda key, **fmt: key)
    PanelRuntime.yield_hook(stub, "timer")(script_engine.new_context())
    assert said == [], said


def test_a_stop_beats_a_step_aside():
    """A run the operator has ended has no business waiting for anybody."""
    stop = threading.Event()
    stop.set()
    stepped = []
    ctx = script_engine.new_context(cancel=stop, yield_to=lambda _c: stepped.append(1))
    script_engine.run_text('LOG "one"', ctx=ctx)
    assert ctx.halt is True
    assert stepped == [], "a cancelled run still went looking for somebody to wait for"


# ---------------------------------------------------------------------------
# the flag, on both catalogues
# ---------------------------------------------------------------------------
def test_the_flag_round_trips_through_a_timer_file():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "timers.json"
    path.write_text(json.dumps([
        {"name": "quick", "scenario": "help_ally", "interval_sec": 60,
         "immediate": True},
        {"name": "slow", "scenario": "restart_game", "interval_sec": 21600},
    ]), encoding="utf-8")
    cat = timersmod.load_catalogue(str(path))
    assert cat.by_name("quick").immediate is True
    assert cat.by_name("slow").immediate is False
    # …and it survives a save, which is what a ticked box does.
    timersmod.save_catalogue(cat, str(path))
    again = timersmod.load_catalogue(str(path))
    assert again.by_name("quick").immediate is True
    # An entry that is not urgent does not carry the key at all — the file stays as
    # short as it was.
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = {item["name"]: item
               for item in (raw["timers"] if isinstance(raw, dict) else raw)}
    assert "immediate" not in entries["slow"], entries["slow"]


def test_a_row_box_carries_the_flag_and_touches_nothing_else():
    cat = timersmod.default_catalogue()
    name = cat.names()[0]
    config = cat.default_config()
    config[name] = {"enabled": True, "interval_sec": 900, "immediate": True}
    moved = cat.with_settings(config)
    assert moved.by_name(name).immediate is True
    assert moved.by_name(name).scenario == cat.by_name(name).scenario
    assert moved.by_name(name).retry_sec == cat.by_name(name).retry_sec


def test_the_alliance_help_trigger_ships_urgent():
    """The one entry the person named, and the one shipped with the flag on."""
    trig = triggersmod.default_catalogue().by_name("alliance_help")
    assert trig.immediate is True, "the help press would queue behind the schedule again"
    assert trig.as_dict()["immediate"] is True
    # Everything else is ordinary until somebody says otherwise.
    others = [t.name for t in triggersmod.default_catalogue()
              if t.immediate and t.name != "alliance_help"]
    assert others == [], others


def test_a_trigger_box_moves_only_the_two_it_is_given():
    cat = triggersmod.default_catalogue()
    name = "rally_monitor"
    moved = cat.with_enabled({name: {"enabled": True}}, {name: True})
    assert moved.by_name(name).enabled is True
    assert moved.by_name(name).immediate is True
    assert moved.by_name(name).scenario == cat.by_name(name).scenario
    # With no second dict the flag stays exactly where the file left it.
    kept = cat.with_enabled({name: {"enabled": True}})
    assert kept.by_name(name).immediate is cat.by_name(name).immediate


# ---------------------------------------------------------------------------
# the scheduler: «сразу» does not stand behind a long errand
# ---------------------------------------------------------------------------
def _scheduler(tmp: Path, catalogue, runner, spawn=None):
    sched = timersmod.TimerScheduler(
        store=timersmod.LastRunStore(str(tmp / "state.json")),
        catalogue=lambda: catalogue,
        config=catalogue.default_config,
        runner=runner,
        log=lambda key, **fmt: None,
        tick=1000.0)
    if spawn is not None:
        sched._spawn = spawn
    return sched


def test_an_urgent_errand_does_not_queue_behind_a_long_one():
    """The acceptance criterion, on the queue: the worker is inside a long errand and
    the urgent one runs anyway, on a thread of its own."""
    tmp = Path(tempfile.mkdtemp())
    catalogue = timersmod.Catalogue((
        timersmod.Timer(name="slow", scenario=("x",), interval_sec=10, enabled=True),
        timersmod.Timer(name="quick", scenario=("y",), interval_sec=10, enabled=True,
                        immediate=True),
    ))
    started, release = [], threading.Event()

    def runner(errand) -> bool:
        started.append(errand.name)
        if errand.name == "slow":
            release.wait(timeout=10.0)
        return True

    sched = _scheduler(tmp, catalogue, runner)
    sched._enqueue("slow", scheduled=True)
    worker = threading.Thread(target=sched.drain, daemon=True)
    worker.start()
    _wait_for(lambda: started == ["slow"])

    # The worker is now stuck inside «slow». The ordinary road is shut…
    assert sched.pending() >= {"slow"}, sched.pending()
    # …and the urgent one goes anyway.
    assert sched._enqueue("quick", scheduled=True) is True
    _wait_for(lambda: "quick" in started)
    assert started == ["slow", "quick"], started

    release.set()
    worker.join(timeout=10.0)


def test_an_urgent_errand_is_still_deduped_and_released():
    """A burst of pushes is one run, not ten — the flag removes the WAIT, not the
    coalescing that keeps a hundred help pushes from being a hundred presses."""
    tmp = Path(tempfile.mkdtemp())
    catalogue = timersmod.Catalogue((
        timersmod.Timer(name="quick", scenario=("y",), interval_sec=10, enabled=True,
                        immediate=True),
    ))
    runs, hold = [], threading.Event()

    def runner(errand) -> bool:
        runs.append(errand.name)
        hold.wait(timeout=10.0)
        return True

    sched = _scheduler(tmp, catalogue, runner)
    assert sched._enqueue("quick", scheduled=True) is True
    _wait_for(lambda: runs == ["quick"])
    # A second fire while the first is in flight is not a second thread.
    assert sched._enqueue("quick", scheduled=True) is False
    hold.set()
    _wait_for(lambda: sched.pending() == set())
    assert runs == ["quick"], runs


def test_a_fire_landing_mid_run_re_fires_urgently_rather_than_queueing():
    """The mid-run fire is the one that matters: the run in flight has already read the
    game and cannot know about it (#1281). It must come back the way it went — at once,
    not at the back of the queue the flag exists to skip."""
    tmp = Path(tempfile.mkdtemp())
    catalogue = timersmod.Catalogue(())
    runs, hold = [], threading.Event()

    def runner(errand) -> bool:
        runs.append(errand.name)
        if len(runs) == 1:
            hold.wait(timeout=10.0)
        return True

    sched = _scheduler(tmp, catalogue, runner)
    errand = triggersmod.Trigger(name="alliance_help", scenario=("help_ally",),
                                 event_pattern="al.help.new", immediate=True)
    assert sched.submit(errand) == "queued"
    _wait_for(lambda: runs == ["alliance_help"])
    assert sched.submit(errand) == "refired"
    hold.set()
    _wait_for(lambda: len(runs) == 2)
    assert runs == ["alliance_help", "alliance_help"], runs
    _wait_for(lambda: sched.pending() == set())
    # Nothing was left on the ordinary queue: the re-fire went the express way.
    assert sched._queue.empty(), "the re-fire fell back into the queue"


def test_an_urgent_errand_that_cannot_get_in_falls_back_to_the_queue():
    """When the flag has nothing left to offer — the client is held by something it does
    not outrank — the errand takes its turn like any other rather than disappearing."""
    tmp = Path(tempfile.mkdtemp())
    catalogue = timersmod.Catalogue((
        timersmod.Timer(name="quick", scenario=("y",), interval_sec=10, enabled=True,
                        immediate=True),
    ))
    tries = []

    def runner(errand) -> bool:
        tries.append(errand.name)
        return len(tries) > 1              # busy the first time, then it runs

    sched = _scheduler(tmp, catalogue, runner)
    assert sched._enqueue("quick", scheduled=True) is True
    _wait_for(lambda: tries == ["quick"])
    _wait_for(lambda: not sched._queue.empty())
    assert sched.pending() == {"quick"}, "a refused express errand let go of its name"
    assert sched.drain() == ["quick"], tries


def test_the_scheduler_runs_an_ordinary_errand_exactly_as_it_did():
    """No flag, no thread, no change: everything unmarked still goes single-file."""
    tmp = Path(tempfile.mkdtemp())
    catalogue = timersmod.Catalogue((
        timersmod.Timer(name="a", scenario=("x",), interval_sec=10, enabled=True),
        timersmod.Timer(name="b", scenario=("y",), interval_sec=10, enabled=True),
    ))
    order, inside, worst = [], [0], [0]

    def runner(errand) -> bool:
        inside[0] += 1
        worst[0] = max(worst[0], inside[0])
        order.append(errand.name)
        time.sleep(0.01)
        inside[0] -= 1
        return True

    sched = _scheduler(tmp, catalogue, runner)
    sched._enqueue("a", scheduled=True)
    sched._enqueue("b", scheduled=True)
    assert sched.drain() == ["a", "b"], order
    assert worst[0] == 1, "two ordinary errands overlapped"


# ---------------------------------------------------------------------------
# the wiring: what the schedule actually asks for, and what it hands the run
# ---------------------------------------------------------------------------
def _schedule_stub(errand, asked: list, made: list):
    """A `Schedule` with everything under `run_errand` replaced by a recorder.

    `Schedule.__new__` rather than a constructor: building a real one reads two
    catalogues and starts nothing this case is about. What is stubbed is exactly what
    `run_errand` touches, so the thing under test is its own decisions — which level it
    claims at, and what it puts on the context.
    """
    from panel.runtime.daemon import DAEMON_LIVE
    from panel.runtime.schedule import Schedule

    def context(**kw):
        made.append(kw)
        return types.SimpleNamespace(vars={}, fail_reason="", taps_tried=0,
                                     taps_fired=0)

    sched = Schedule.__new__(Schedule)
    sched._handlers, sched._needs_game = {}, set()
    sched._gates, sched._args = {}, {}
    sched.timer_catalogue = timersmod.Catalogue((errand,)
                                                if hasattr(errand, "interval_sec")
                                                else ())
    sched.rt = types.SimpleNamespace(
        game=types.SimpleNamespace(
            claim=lambda owner, priority: asked.append(("claim", priority)) or True,
            claim_soon=lambda owner, priority, timeout=None: asked.append(
                ("claim_soon", priority)) or True,
            last_health=lambda: DAEMON_LIVE,
            up=lambda: True,
            release=lambda: None,
            on_settled=lambda: None),
        actions=types.SimpleNamespace(context=context,
                                      resolve=lambda step: "somewhere",
                                      run=lambda step, hwnd=0, ctx=None: True),
        recovery=types.SimpleNamespace(note_run=lambda tried, fired: None),
        put=lambda line: None,
        yield_hook=lambda tag: ("the hook for " + tag))
    return sched


def test_an_ordinary_errand_claims_low_and_carries_the_step_aside_hook():
    asked, made = [], []
    errand = timersmod.Timer(name="slow", scenario=("x",), interval_sec=10)
    assert _schedule_stub(errand, asked, made).run_errand(errand) is True
    assert asked == [("claim", claims.BACKGROUND)], asked
    assert made and made[0]["yield_to"] == "the hook for timer", made


def test_an_urgent_errand_demands_the_client_and_is_never_asked_to_park():
    """Both halves of the flag, at the one place they are decided.

    It does not merely ASK for the client — a plain `claim` would be refused by the
    ordinary errand holding it and the errand would go back on the queue it was marked
    to skip. And it carries no hook: a thing that may not queue behind the ordinary work
    should not be parked by it either.
    """
    asked, made = [], []
    errand = timersmod.Timer(name="quick", scenario=("x",), interval_sec=10,
                             immediate=True)
    assert _schedule_stub(errand, asked, made).run_errand(errand) is True
    assert asked == [("claim_soon", claims.EXPRESS)], asked
    assert made and made[0]["yield_to"] is None, made


def _wait_for(cond, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for the condition")


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
