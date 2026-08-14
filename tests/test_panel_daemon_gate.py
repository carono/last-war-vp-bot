r"""«Стоп всё» is two acts, and a dead daemon holds everything else (task #1393).

Two promises, and they are the same promise seen from both ends.

**The press does exactly two things:** it closes the client and it stops this profile's
daemon. It used to switch off the schedule, every plugin tab's monitors, every child, the
scenario in flight and the activity strip as well — five things to put back by hand
afterwards — and then went on putting the client back within eight seconds, because the
watchdog and the recovery had never heard of it.

**And a daemon that is not there is the ONE gate on everything automatic:** no timer, no
trigger, no poll, no watchdog relaunch, no retry, and no line every few seconds saying
that none of it worked. What is pinned here is what «does not try» has to mean:

  * a held timer never calls its runner, never queues and leaves the clock alone, so the
    errand is still due when the daemon comes back;
  * when it does come back the errand runs ONCE — the missed turns are not a queue
    (the rule daily errands already keep, #1333);
  * a trigger's fire is dropped at the gate rather than at the queue, and says nothing
    in the person's log;
  * the gate says the EDGE once — «нечего запускать» and «снова работает» — and nothing
    in between, which is the difference between a state and a complaint per tick;
  * it costs nothing to ask: with a fresh reading from the status poll it never touches
    a socket;
  * …except right after somebody has started or stopped a daemon, when the poll's last
    verdict is about the world before that and is deliberately not believed;
  * and it is PER PROFILE — two runtimes, two daemons, two answers, no module-level
    state (`CLAUDE.md`, «A profile is a whole panel of its own»).

No Tk, no game, no daemon: the readings are handed in.

    C:\Python312\python.exe tests\test_panel_daemon_gate.py
    python3 tests/test_panel_daemon_gate.py
"""
from __future__ import annotations

TIER = "ui"        # no display of its own, but `panel.runtime` imports Tk on the way in

import sys
import tempfile
import time
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools" / "lib"))

import profile_health  # noqa: E402

from panel import timers as timersmod  # noqa: E402
from panel import triggers as triggersmod  # noqa: E402
from panel.runtime import gate as gatemod  # noqa: E402
from panel.runtime import panic as panicmod  # noqa: E402

BASE = "collect_base_resources"
RESTART = "restart_game"


# --- the stand-ins ----------------------------------------------------------
#
# Small on purpose: the gate reads three things (the light, the port, the log) and
# nothing else, and a fake that offers more would let a change slip past this test.

class _Link:
    """A daemon link that answers `up()` off a value the test sets."""

    def __init__(self, up: bool = True) -> None:
        self.answer = up
        self.probes = 0                 # how many times the PORT was asked
        self.stopped = 0
        self.ensured = 0
        self.forgot = 0

    def up(self) -> bool:
        self.probes += 1
        return self.answer

    def forget_up(self) -> None:
        self.forgot += 1

    def stop(self) -> bool:
        self.stopped += 1
        self.answer = False
        return True

    def ensure(self) -> bool:
        self.ensured += 1
        self.answer = True
        return True


class _Light:
    """`ProfileHealth` as the gate sees it: one verdict and when it was made."""

    def __init__(self, daemon: str = profile_health.DAEMON_LIVE, at=None) -> None:
        self.current = types.SimpleNamespace(daemon=daemon)
        self.read_at = time.time() if at is None else at

    def set(self, daemon: str, at=None) -> None:
        self.current = types.SimpleNamespace(daemon=daemon)
        self.read_at = time.time() if at is None else at


class _RT:
    """Everything the gate and the press lean on, and nothing else."""

    def __init__(self, up: bool = True, daemon: str = profile_health.DAEMON_LIVE) -> None:
        self.game = _Link(up)
        self.health = _Light(daemon)
        self.said: list = []
        self.played: list = []
        self.panic = panicmod.Panic()
        self.gate = gatemod.DaemonGate(self)

    def say(self, tag: str, key: str, **fmt) -> None:
        self.said.append(key)

    def dbg(self, component: str = "panel"):
        return types.SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None,
            error=lambda *a, **k: None, debug=lambda *a, **k: None)

    def play_async(self, name: str, args=None, *, tag: str = "action", on_done=None,
                   **kw) -> bool:
        self.played.append(name)
        if on_done is not None:
            on_done()
        return True


class _Scheduler:
    """A real TimerScheduler with the runner captured and a gate wired in."""

    def __init__(self, tmp: Path, config: dict, gate=None):
        self.ran: list = []
        self.logs: list = []
        self.store = timersmod.LastRunStore(str(tmp / "timers_last_run.json"))
        self.catalogue = timersmod.default_catalogue()
        self.sched = timersmod.TimerScheduler(
            store=self.store, catalogue=lambda: self.catalogue,
            config=lambda: config, runner=self._run,
            log=lambda key, **fmt: self.logs.append(key), gate=gate,
            busy_retry=0.0)

    def _run(self, timer):
        self.ran.append(timer.name)
        return True


def _cfg(**seconds) -> dict:
    cfg = timersmod.default_catalogue().default_config()
    for name, period in seconds.items():
        cfg[name] = {"enabled": True, "interval_sec": period}
    return cfg


# --- «Стоп всё» is two acts -------------------------------------------------

def test_stop_all_closes_the_client_and_stops_the_daemon_and_does_nothing_else():
    """The whole press, in two lines — and the four things it must NOT touch.

    The old one stopped the schedule, every tab, every child and the run in flight. Each
    of those was a switch somebody then had to find again, and none of them stopped the
    watchdog putting the client straight back. Anything this press grows a third act for
    is a state that has to be undone by hand, which is what «Включить обратно» kept
    failing to do.
    """
    rt = _RT()
    for forbidden in ("schedule", "children", "interrupts", "activity", "tabs"):
        setattr(rt, forbidden, _Tripwire(forbidden))

    panicmod.stop(rt)

    assert rt.played == ["quit_game"], rt.played
    assert rt.game.stopped == 1, "the daemon was not stopped"
    assert rt.panic.stopped, "the mark was not set"
    # …and the gate was told, or the schedule would spend up to a poll's period acting
    # on a reading taken while the daemon was still there — and an errand that believes
    # that calls `ensure()`, which starts the daemon the press has just stopped.
    assert rt.game.forgot >= 1, "the gate was not told the daemon had gone"


def test_the_daemon_still_goes_when_the_client_will_not_close():
    """A claim refused is not a reason to leave the daemon running.

    The press is what somebody reaches for when things have gone wrong, and «the client
    is busy» is one of the ways they have gone wrong. The second act happens whatever
    the first one managed.
    """
    rt = _RT()
    rt.play_async = lambda *a, **kw: False          # something more urgent holds it
    panicmod.stop(rt)
    assert rt.game.stopped == 1, "the daemon survived a refused quit"


def test_switching_back_on_brings_the_daemon_back_and_starts_no_client():
    """«Включить обратно» is the inverse, and just as short.

    Not «and start the client» as well: with a daemon up the gate opens, and whatever
    puts a client back — the six-hourly errand, the watchdog, the recovery — does it by
    itself, once. A launch from here as well would be the second relaunch racing the
    first.
    """
    rt = _RT(up=False, daemon=profile_health.DAEMON_IS_NONE)
    rt.panic.mark(time.time())
    panicmod.resume(rt)
    _settle(lambda: rt.game.ensured == 1)
    assert rt.game.ensured == 1, "the daemon was not brought back"
    assert rt.played == [], f"a client was started as well: {rt.played}"
    assert not rt.panic.stopped, "the mark stayed after the undo"


# --- nothing runs while the daemon is down ----------------------------------

def test_a_held_timer_makes_no_attempt_at_all():
    """Not one call into the runner, and nothing left on the queue.

    «Не пытаются ничего делать» is the whole requirement: no scenario, no read, no
    relaunch and no failure to write down. The clock is left alone too, so the errand is
    still due the moment the daemon is back.
    """
    tmp = Path(tempfile.mkdtemp())
    rt = _RT(up=False, daemon=profile_health.DAEMON_IS_NONE)
    s = _Scheduler(tmp, _cfg(**{BASE: 3600, RESTART: 3600}),
                   gate=lambda name: rt.gate.reason())
    for _ in range(5):
        s.sched.tick_once()
    assert s.ran == [], f"something ran with the daemon down: {s.ran}"
    assert s.sched.pending() == set(), f"errands were queued anyway: {s.sched.pending()}"
    assert s.store.last_run(BASE) == 0.0, "a held errand had its clock moved"


def test_even_the_errand_that_puts_the_client_back_is_held():
    """`restart_game` is exempt from «the game is not running» and not from this.

    That exemption exists because the recovery errands are the cure for a client that is
    down (#1259). They are not the cure for a panel somebody stopped — and they are
    exactly what used to undo «Стоп всё» within a tick of it being pressed.
    """
    tmp = Path(tempfile.mkdtemp())
    rt = _RT(up=False, daemon=profile_health.DAEMON_IS_NONE)
    s = _Scheduler(tmp, _cfg(**{RESTART: 3600}), gate=lambda name: rt.gate.reason())
    s.sched.tick_once()
    assert s.ran == [], f"the client was put back with no daemon: {s.ran}"


def test_the_daemon_coming_back_gives_one_run_and_not_a_queue():
    """Five held turns and one run, not five (#1333's rule, in the other half).

    A missed turn is not a debt. The gate refuses BEFORE anything is queued, so nothing
    piles up while it is closed — and the first tick after it opens finds one errand due,
    exactly as it would have if the daemon had never gone.
    """
    tmp = Path(tempfile.mkdtemp())
    rt = _RT(up=False, daemon=profile_health.DAEMON_IS_NONE)
    s = _Scheduler(tmp, _cfg(**{BASE: 3600}), gate=lambda name: rt.gate.reason())
    for _ in range(5):
        s.sched.tick_once()
    assert s.ran == []

    rt.health.set(profile_health.DAEMON_LIVE)
    rt.game.answer = True
    s.sched.tick_once()
    s.sched.tick_once()                       # …and the turn after it is not a repeat
    assert s.ran == [BASE], f"the daemon coming back fired a burst: {s.ran}"


def test_a_trigger_fire_is_dropped_at_the_gate_and_says_nothing():
    """A push that could not be acted on costs a debug line and no more.

    A busy alliance sends a push a second. Dropped at the queue instead, each of them
    would come back as a rolled-up «пропуск» with a count on it — which is the «не
    удалось» every few seconds this task exists to remove.
    """
    said: list = []
    fired: list = []

    watcher = triggersmod.TriggerWatcher(
        catalogue=lambda: triggersmod.default_catalogue(),
        config=lambda: {},
        spawn=lambda *a, **k: None,
        submit=lambda trigger: (fired.append(trigger.name), "held")[1],
        log=lambda key, **fmt: said.append(key),
        poll=None)
    trigger = next(iter(triggersmod.default_catalogue()))
    watcher._fire(trigger)

    assert fired == [trigger.name], "the fire never reached the gate"
    assert said == [], f"a held fire was said out loud: {said}"


# --- what it costs, and what it believes ------------------------------------

def test_asking_the_gate_costs_nothing_while_the_poll_is_fresh():
    """A tick, a fire and a paint may ask as often as they like.

    The status poll probes this profile's daemon every eight seconds anyway and leaves
    the verdict on the light. Reading THAT is a dict lookup; probing per question would
    be a socket connect on the timer thread, the poll thread and the thread that draws.
    """
    rt = _RT()
    for _ in range(50):
        assert rt.gate.alive()
    assert rt.game.probes == 0, f"the port was asked {rt.game.probes} times"


def test_a_reading_nobody_has_refreshed_is_not_believed():
    """No window behind this runtime, or a poll that has died: ask the port.

    «Nobody has looked» may never read as «alive» — a tab launched on its own has no
    status poll at all, and a gate that trusted an empty light would let a standalone
    window run errands into a daemon that is not there.
    """
    rt = _RT(up=False)
    rt.health.read_at = 0.0
    assert rt.gate.alive() is False
    assert rt.game.probes == 1, "the port was not asked"

    stale = _RT(up=False)
    stale.health.set(profile_health.DAEMON_LIVE, at=time.time() - gatemod.FRESH_SEC - 1)
    assert stale.gate.alive() is False, "a reading older than FRESH_SEC was believed"


def test_a_verdict_from_before_the_stop_is_not_evidence_about_after_it():
    """The eight seconds that used to undo the press.

    The status poll runs every eight seconds, so for up to that long after «Стоп всё»
    the newest verdict says the daemon is warm — and an errand that believes it calls
    `ensure()`, which starts the daemon the press has just stopped. Whoever changes a
    daemon's existence says so, and everything read before that moment stops counting.
    """
    rt = _RT(up=True)
    assert rt.gate.alive() is True

    rt.game.stop()                          # …the daemon is gone, the light is not yet
    assert rt.health.current.daemon == profile_health.DAEMON_LIVE
    rt.gate.changed()
    assert rt.gate.alive() is False, "the gate quoted a verdict from before the stop"


def test_a_stale_daemon_is_not_an_alive_one():
    """A port that answers is not a link that carries a chunk (#1286).

    An errand run against a daemon holding a client that has gone fails, is written down
    as a failure and sits out its retry hold for nothing. Restarting THAT daemon is the
    recovery's business and is deliberately not behind this gate.
    """
    rt = _RT(daemon=profile_health.DAEMON_IS_STALE)
    assert rt.gate.alive() is False
    assert rt.gate.reason() == "timers.log.skip_daemon"


def test_the_edge_is_said_once_and_the_state_is_left_on_screen():
    """One line when it closes, one when it opens, and nothing in between.

    The gate is asked by the timer thread, the trigger polls, the watchdog and the status
    poll — several times a minute between them. Saying the state per ask is the log this
    task is here to quieten; saying nothing at all is how a stopped panel and an idle one
    look the same (#1262). So: the change is said, and the mark carries it in between.
    """
    rt = _RT(up=False, daemon=profile_health.DAEMON_IS_NONE)
    for _ in range(10):
        rt.gate.alive()
    assert rt.said.count("gate.log.held") == 1, rt.said
    assert rt.gate.state()["held"] is True

    rt.health.set(profile_health.DAEMON_LIVE)
    for _ in range(10):
        rt.gate.alive()
    assert rt.said.count("gate.log.free") == 1, rt.said
    assert rt.gate.state()["held"] is False


def test_an_ordinary_start_up_is_not_news():
    """A panel opening onto a working daemon says nothing about it."""
    rt = _RT()
    rt.gate.alive()
    assert rt.said == [], rt.said


def test_two_profiles_are_two_answers():
    """One account's daemon says nothing whatever about the other's.

    The one thing a gate must not be is a module-level flag: a window holds several
    profiles at once, each with its own daemon on its own port, and «all stopped» in one
    of them is not a sentence about any of the others (`CLAUDE.md`).
    """
    first = _RT(up=False, daemon=profile_health.DAEMON_IS_NONE)
    second = _RT()
    assert first.gate.alive() is False
    assert second.gate.alive() is True
    assert second.said == [], f"one profile's edge was said in the other: {second.said}"


# --- helpers ----------------------------------------------------------------

class _Tripwire:
    """Anything touched on it fails the test that touched it."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, item):
        raise AssertionError(f"«Стоп всё» reached {self._name}.{item} — it is two acts")


def _settle(done, timeout: float = 5.0) -> None:
    """Wait for a worker thread's effect, briefly. The acts are not on the Tk thread."""
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if done():
            return
        time.sleep(0.02)


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
