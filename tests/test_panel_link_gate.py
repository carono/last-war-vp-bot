r"""Switching a profile off is two acts, and nothing automatic runs after them (#1393).

Three promises now, and the first two are the same promise seen from both ends.

**The switch is one box per profile** — «Профиль работает» (#1882,
`tests/test_panel_power_switch.py`). What it does when it moves is what this file has
always pinned; what it added is that a daemon started by HAND while the box is unticked
opens nothing, because the gate is shut on the flag rather than on the port.

**The flip does exactly two things:** it closes the client and it stops this profile's
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
from panel.runtime import power as powermod  # noqa: E402

BASE = "collect_base_resources"
RESTART = "restart_game"


# --- the stand-ins ----------------------------------------------------------
#
# Small on purpose: the gate reads three things (the light, the port, the log) and
# nothing else, and a fake that offers more would let a change slip past this test.

class _Link:
    """A link that answers `ready()` — «does a chunk land» — off a value the test sets."""

    def __init__(self, up: bool = True) -> None:
        self.answer = up
        self.probes = 0                 # how many times the LINK was asked directly
        self.stopped = 0
        self.ensured = 0
        self.forgot = 0

    def ready(self, fresh: bool = False) -> bool:
        self.probes += 1
        return self.answer

    def up(self, fresh: bool = False) -> bool:
        return self.answer

    def forget_up(self) -> None:
        self.forgot += 1

    def let_go(self) -> bool:
        self.stopped += 1
        self.answer = False
        return True

    def ensure(self) -> bool:
        self.ensured += 1
        self.answer = True
        return True


class _Light:
    """`ProfileHealth` as the gate sees it: one verdict and when it was made.

    The gate asks ONE thing of it since #1911 — does a chunk reach the client — because
    that is «может ли панель что-то нажать». A server that is silent is amber and does
    NOT hold this gate: its cure is a restart, and refusing to press anything meanwhile
    is how #1910 lost hours of banners to a socket reading that was simply wrong.
    """

    def __init__(self, plumbing: str = profile_health.LANDING, at=None,
                 reason: str = profile_health.TRAFFIC) -> None:
        self.current = types.SimpleNamespace(plumbing=plumbing, reason=reason)
        self.read_at = time.time() if at is None else at

    def set(self, plumbing: str, at=None, reason: str = profile_health.TRAFFIC) -> None:
        self.current = types.SimpleNamespace(plumbing=plumbing, reason=reason)
        self.read_at = time.time() if at is None else at


class _RT:
    """Everything the gate and the press lean on, and nothing else."""

    def __init__(self, up: bool = True,
                 plumbing: str = profile_health.LANDING) -> None:
        self.game = _Link(up)
        self.health = _Light(plumbing)
        self.said: list = []
        self.played: list = []
        self.power = powermod.Power()
        self.gate = gatemod.LinkGate(self)

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
    """The named errands on, and every other row switched OFF explicitly.

    Since #2390 an errand ships switched on, so the catalogue's own defaults are no
    longer «nothing is running»: a gate test that inherited them would be measuring the
    shipped list rather than the gate.
    """
    cfg = timersmod.default_catalogue().default_config()
    for block in cfg.values():
        block["enabled"] = False
    for name, period in seconds.items():
        cfg[name] = {"enabled": True, "interval_sec": period}
    return cfg


# --- switching a profile off is two acts ------------------------------------

def test_switching_off_closes_the_client_and_lets_the_link_go_and_nothing_else():
    """The whole flip, in two lines — and the four things it must NOT touch.

    The old one stopped the schedule, every tab, every child and the run in flight. Each
    of those was a switch somebody then had to find again, and none of them stopped the
    watchdog putting the client straight back. Anything this press grows a third act for
    is a state that has to be undone by hand, which is what «Включить обратно» kept
    failing to do.
    """
    rt = _RT()
    for forbidden in ("schedule", "children", "interrupts", "activity", "tabs"):
        setattr(rt, forbidden, _Tripwire(forbidden))

    assert powermod.set_on(rt, False) is True

    assert rt.played == ["quit_game"], rt.played
    assert rt.game.stopped == 1, "the link was not let go"
    assert rt.power.off, "the switch was not written"
    # …and the gate was told, or the schedule would spend up to a poll's period acting
    # on a reading taken while the daemon was still there — and an errand that believes
    # that calls `ensure()`, which starts the daemon the press has just stopped.
    assert rt.game.forgot >= 1, "the gate was not told the daemon had gone"


def test_the_link_still_goes_when_the_client_will_not_close():
    """A claim refused is not a reason to leave the daemon running.

    The press is what somebody reaches for when things have gone wrong, and «the client
    is busy» is one of the ways they have gone wrong. The second act happens whatever
    the first one managed.
    """
    rt = _RT()
    rt.play_async = lambda *a, **kw: False          # something more urgent holds it
    panicmod.stop(rt)                               # the act itself, flag already written
    assert rt.game.stopped == 1, "the link survived a refused quit"


def test_switching_back_on_brings_the_daemon_back_and_starts_no_client():
    """«Включить обратно» is the inverse, and just as short.

    Not «and start the client» as well: with a daemon up the gate opens, and whatever
    puts a client back — the six-hourly errand, the watchdog, the recovery — does it by
    itself, once. A launch from here as well would be the second relaunch racing the
    first.
    """
    rt = _RT(up=False, plumbing=profile_health.NOT_LANDING)
    rt.power.set(False, time.time())
    assert powermod.set_on(rt, True) is True
    _settle(lambda: rt.game.ensured == 1)
    assert rt.game.ensured == 1, "the daemon was not brought back"
    assert rt.played == [], f"a client was started as well: {rt.played}"
    assert rt.power.on, "the switch stayed off"


# --- nothing runs while the daemon is down ----------------------------------

def test_a_held_timer_makes_no_attempt_at_all():
    """Not one call into the runner, and nothing left on the queue.

    «Не пытаются ничего делать» is the whole requirement: no scenario, no read, no
    relaunch and no failure to write down. The clock is left alone too, so the errand is
    still due the moment the daemon is back.
    """
    tmp = Path(tempfile.mkdtemp())
    rt = _RT(up=False, plumbing=profile_health.NOT_LANDING)
    s = _Scheduler(tmp, _cfg(**{BASE: 3600, RESTART: 3600}),
                   gate=lambda name: rt.gate.reason())
    for _ in range(5):
        s.sched.tick_once()
    assert s.ran == [], f"something ran with the daemon down: {s.ran}"
    assert s.sched.pending() == set(), f"errands were queued anyway: {s.sched.pending()}"
    assert s.store.last_run(BASE) == 0.0, "a held errand had its clock moved"


def test_the_errand_that_puts_the_client_back_is_held_by_the_SWITCH():
    """…and by the switch alone (#1910). It used to be held by the daemon as well.

    The exemption exists because the recovery errands are the cure for a client that is
    down (#1259). They are not the cure for a panel somebody stopped, and they are
    exactly what used to undo «Стоп всё» within a tick of it being pressed — so the
    SWITCH holds them, and that is the half of #1393 that was doing the work.

    What must NOT hold them is the daemon, and that is what this task changed. A daemon
    with no client to attach to is not alive; the thing that gives it one is this very
    errand. Live on 2026-08-24 `default` sat in that loop all afternoon — no client,
    seventeen daemon restarts, zero client restarts, the watchdog held at every poll by
    the missing client itself.
    """
    tmp = Path(tempfile.mkdtemp())
    rt = _RT(up=False, plumbing=profile_health.NOT_LANDING)

    # The switch is on and the daemon is gone: the cure runs.
    assert rt.gate.relaunch_held() is False
    assert rt.gate.blocks(RESTART) == "", "the cure was held by the illness"
    s = _Scheduler(tmp, _cfg(**{RESTART: 3600}),
                   gate=lambda name: _schedule_gate(rt, name))
    s.sched.tick_once()
    assert s.ran == [RESTART], f"the client was not put back: {s.ran}"

    # …and «Профиль работает» unticked stops it dead, which is what «Стоп всё» means.
    rt.power.set(False)
    assert rt.gate.relaunch_held() is True
    assert rt.gate.blocks(RESTART) == "action.held.off"
    s2 = _Scheduler(Path(tempfile.mkdtemp()), _cfg(**{RESTART: 3600}),
                    gate=lambda name: _schedule_gate(rt, name))
    s2.sched.tick_once()
    assert s2.ran == [], f"a switched-off profile put its client back: {s2.ran}"


def _schedule_gate(rt, name):
    """`Schedule.gate`'s two lines, as the scheduler sees them (`schedule.py`)."""
    recovery = name == RESTART
    if not rt.gate.alive() and not (recovery and not rt.gate.relaunch_held()):
        return "timers.log.skip_daemon"
    return None


def test_the_daemon_coming_back_gives_one_run_and_not_a_queue():
    """Five held turns and one run, not five (#1333's rule, in the other half).

    A missed turn is not a debt. The gate refuses BEFORE anything is queued, so nothing
    piles up while it is closed — and the first tick after it opens finds one errand due,
    exactly as it would have if the daemon had never gone.
    """
    tmp = Path(tempfile.mkdtemp())
    rt = _RT(up=False, plumbing=profile_health.NOT_LANDING)
    s = _Scheduler(tmp, _cfg(**{BASE: 3600}), gate=lambda name: rt.gate.reason())
    for _ in range(5):
        s.sched.tick_once()
    assert s.ran == []

    rt.health.set(profile_health.LANDING)
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
    stale.health.set(profile_health.LANDING, at=time.time() - gatemod.FRESH_SEC - 1)
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

    rt.game.let_go()                        # …the link is gone, the light is not yet
    assert rt.health.current.plumbing == profile_health.LANDING
    rt.gate.changed()
    assert rt.gate.alive() is False, "the gate quoted a verdict from before the stop"


def test_the_switch_shuts_the_gate_over_a_perfectly_live_daemon():
    """«Выключен» is a person's decision; a warm port is only what a machine is doing.

    Without this the «⭮» button — or any `ensure()` that slipped through — would put the
    daemon back and open the gate under a profile somebody had deliberately switched off,
    which is the eight-second undo of #1393 with a longer fuse (#1882).
    """
    rt = _RT()                                  # daemon warm, poll fresh
    assert rt.gate.alive() is True
    rt.power.set(False, time.time())
    assert rt.gate.alive() is False, "a live daemon reopened a switched-off profile"
    assert rt.gate.reason() == "timers.log.skip_off"
    assert rt.said.count("gate.log.off") == 1, rt.said
    assert "gate.log.held" not in rt.said, "it blamed the daemon for a person's choice"

    rt.power.set(True, time.time())
    assert rt.gate.alive() is True, "ticking it back on left the gate shut"


def test_a_link_that_lands_nothing_is_not_an_alive_one():
    """Reaching the client is what «alive» means (#1286, #1911).

    An errand run through a link that carries nothing fails, is written down as a
    failure and sits out its retry hold for nothing. Taking hold of the client again is
    the poll's business and is deliberately not behind this gate.
    """
    rt = _RT(plumbing=profile_health.NOT_LANDING)
    assert rt.gate.alive() is False
    assert rt.gate.reason() == "timers.log.skip_link"


def test_the_edge_is_said_once_and_the_state_is_left_on_screen():
    """One line when it closes, one when it opens, and nothing in between.

    The gate is asked by the timer thread, the trigger polls, the watchdog and the status
    poll — several times a minute between them. Saying the state per ask is the log this
    task is here to quieten; saying nothing at all is how a stopped panel and an idle one
    look the same (#1262). So: the change is said, and the mark carries it in between.
    """
    rt = _RT(up=False, plumbing=profile_health.NOT_LANDING)
    for _ in range(10):
        rt.gate.alive()
    assert rt.said.count("gate.log.held") == 1, rt.said
    assert rt.gate.state()["held"] is True

    rt.health.set(profile_health.LANDING)
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
    first = _RT(up=False, plumbing=profile_health.NOT_LANDING)
    second = _RT()
    assert first.gate.alive() is False
    assert second.gate.alive() is True
    assert second.said == [], f"one profile's edge was said in the other: {second.said}"


# --- and every RUN asks it, not only the schedule (#1910) --------------------

def test_a_run_nobody_marked_as_a_press_is_held_and_says_so():
    """The hole this task closed: a scenario played past the schedule entirely.

    A tab polling its board, a wire handler joining a rally off the capture's own reader,
    an auto-order re-armed on the panel's clock — none of them is a timer and none is a
    trigger, so none of them was asking the gate. Live on 2026-08-24 a switched-off
    profile printed «профиль выключен» and went on playing `read_daily_checklist` every
    thirty seconds and joining rallies all afternoon.

    So the question is asked at the one door every scenario goes through, and the default
    is HELD: a caller nobody marked is a caller nobody thought about.
    """
    from panel.runtime import actions as actionsmod

    rt = _RT(up=False, plumbing=profile_health.NOT_LANDING)
    assert rt.gate.blocks(BASE) == "action.held.link"

    said: list = []
    runner = actionsmod.ActionRunner(
        log=types.SimpleNamespace(say=lambda tag, key, **fmt: said.append(key),
                                  put=lambda msg: None),
        gate=lambda name, human: rt.gate.blocks(name, human=human))
    assert runner.run(BASE) is False, "a held run played the scenario anyway"
    assert said == ["action.held.link"], f"a held run said {said!r}, not the hold"


def test_the_hold_names_which_of_the_two_it_is():
    """«профиль выключен» sends a person to a checkbox; «демон не работает» to a fault.

    One sentence for both would be the exact confusion #1882 removed from the schedule's
    skip line, put straight back at the door every run comes through.
    """
    rt = _RT()                                    # a perfectly live daemon…
    rt.power.set(False)                           # …and the switch off
    assert rt.gate.blocks(BASE) == "action.held.off"


def test_a_persons_press_is_never_held():
    """The one exemption, and it is the module docstring's: somebody at a button.

    Closing the client is the plainest case — it is what switching the profile OFF has
    to do, and a gate that held it would be holding its own cure.
    """
    rt = _RT(up=False, plumbing=profile_health.NOT_LANDING)
    assert rt.gate.blocks("quit_game", human=True) == ""
    rt.power.set(False)
    assert rt.gate.blocks("quit_game", human=True) == ""


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


# --- the closed door (#1982) ------------------------------------------------
def test_the_server_being_shut_holds_the_gate_although_the_link_is_perfect():
    """The operator's decision, in their words: «держать очередь и сказать один раз».

    Maintenance is the one amber that holds this gate, and it is nothing like the deaf
    client the module refuses to hold for: chunks land, the panel drives the client
    perfectly, and every errand it starts is refused by a server that is not there —
    twenty identical failures and a daily quota's attempts written off against a door.
    """
    rt = _RT()
    rt.health.set(profile_health.LANDING, reason=profile_health.MAINTENANCE)
    assert rt.gate.alive() is False
    assert rt.gate.reason() == "timers.log.skip_maintenance"
    assert "gate.log.maintenance" in rt.said, rt.said
    assert rt.gate.state()["reason"] == "maintenance"


def test_the_door_opening_lets_everything_go_again_by_itself():
    """Nothing has to be pressed: the hold lifts with the message it was made of."""
    rt = _RT()
    rt.health.set(profile_health.LANDING, reason=profile_health.MAINTENANCE)
    assert rt.gate.alive() is False
    rt.health.set(profile_health.LANDING, reason=profile_health.TRAFFIC)
    assert rt.gate.alive() is True
    assert rt.gate.reason() is None
    assert rt.gate.state()["reason"] == ""


def test_the_closed_door_is_said_ONCE_however_many_errands_ask():
    """A line per tick is the other failure, and the one the gate exists to remove."""
    rt = _RT()
    rt.health.set(profile_health.LANDING, reason=profile_health.MAINTENANCE)
    for _ in range(20):
        rt.gate.alive()
    assert rt.said.count("gate.log.maintenance") == 1, rt.said


def test_a_deaf_client_still_does_not_hold_the_gate():
    """The narrowing has to stay narrow: `no_traffic` is a restart, not a wait (#1910)."""
    rt = _RT()
    rt.health.set(profile_health.LANDING, reason=profile_health.NO_TRAFFIC)
    assert rt.gate.alive() is True


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
