r"""An event is acted on. Being busy may DELAY it; it may never cancel it (#1416).

The operator's rule for the whole task, in their own words: «если есть слушатель на
событие в трафике, мы должны мгновенно его обрабатывать, в крайнем случае ставить в
очередь, но оно гарантировано должно быть обработано».

Everything in the scheduler already honoured that except one door. A busy panel
RE-QUEUES the errand (`_run_queued` → `_requeue`), a fire that lands mid-run RE-FIRES it
(`submit` → `_refire`), an express errand that ran out of patience goes onto the ordinary
queue — but the GATE simply dropped what came through it. «The next tick queues it
again» is true of a catalogue timer, which has a clock, and was never true of a trigger's
errand: its moment was a push, and the push has already gone. Measured on one live day,
524 fires were turned away and about 230 of them went through a gate.

So a refused fire is PARKED and offered again on `GATE_RETRY_SEC` until the gate opens,
and is given up only when it is older than `GATE_KEEP_SEC` — said out loud, because an
event nobody could act on is news whichever way it ends.

No Tk, no game, no threads: the scheduler is driven by hand::

    python3 tests/test_panel_event_guarantee.py
    C:\Python312\python.exe tests\test_panel_event_guarantee.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import timers as timersmod                       # noqa: E402


class _Errand:
    """What a trigger hands the scheduler: a name and a scenario, nothing else."""

    def __init__(self, name="rally_auto_join", immediate=False) -> None:
        self.name, self.scenario, self.immediate = name, ("join_rally",), immediate


class _Store:
    def __init__(self) -> None:
        self.started, self.ran = [], []

    def records(self):
        return {}

    def mark_started(self, name, when=None):
        self.started.append(name)

    def mark_run(self, name):
        self.ran.append(name)

    def mark_failed(self, name):
        pass


class _Catalogue:
    """A catalogue with NOTHING in it — an ad-hoc errand is not one of its own."""

    def by_name(self, name):
        return None

    def normalize_config(self, raw):
        return {}

    def due_names(self, *a, **kw):
        return []


def _scheduler(gate, runner=None, spawn_inline=True):
    ran: list = []
    sched = timersmod.TimerScheduler(
        store=_Store(), catalogue=lambda: _Catalogue(), config=lambda: {},
        runner=runner or (lambda errand: ran.append(errand.name) or True),
        log=lambda key, **fmt: ran.append(("log", key)), gate=gate)
    if spawn_inline:
        # The express path spawns a thread; run it here so the test stays deterministic.
        sched._spawn = lambda work, label: work()
    return sched, ran


def test_a_gated_fire_is_kept_and_runs_when_the_gate_opens():
    """The whole rule, in one test: refused now, RUN later — never dropped."""
    shut = {"why": "timers.log.skip_game"}
    sched, ran = _scheduler(lambda name: shut["why"])

    assert sched.submit(_Errand()) in ("queued", "waiting")
    sched.drain()
    assert "rally_auto_join" not in ran, "it must not have run while the gate was shut"
    assert [row["name"] for row in sched.gated()] == ["rally_auto_join"], \
        "a refused fire has to be waiting somewhere, or it is simply lost"

    shut["why"] = None                                  # the client came back
    assert sched.enqueue_due() == ["rally_auto_join"]
    sched.drain()
    assert "rally_auto_join" in ran, "the event was never acted on"
    assert sched.gated() == [], "and it stops waiting once it has run"


def test_an_express_fire_is_kept_too():
    """«Сразу, без очереди» is about the QUEUE, not about being allowed to vanish."""
    shut = {"why": "timers.log.skip_daemon"}
    sched, ran = _scheduler(lambda name: shut["why"])

    sched.submit(_Errand(immediate=True))
    assert [row["name"] for row in sched.gated()] == ["rally_auto_join"]

    shut["why"] = None
    sched.enqueue_due()
    sched.drain()
    assert "rally_auto_join" in ran


def test_a_second_fire_of_the_same_name_does_not_stack():
    """Two parked copies would be one press made twice — the errand re-reads the game."""
    sched, _ran = _scheduler(lambda name: "timers.log.skip_game")
    for _ in range(5):
        sched.submit(_Errand())
        sched.drain()                       # …and each one is refused by the gate
    assert len(sched.gated()) == 1


def test_the_wait_is_bounded_and_the_giving_up_is_said():
    """A push is about a MOMENT; acting on it a quarter of an hour later presses at
    something that is no longer there. So the wait ends — out loud."""
    sched, ran = _scheduler(lambda name: "timers.log.skip_game")
    sched.submit(_Errand())
    sched.drain()
    # …and the fire is older than the panel's patience.
    with sched._queue_lock:
        errand, scheduled, by, _since, _last, reason = sched._gated["rally_auto_join"]
        sched._gated["rally_auto_join"] = (
            errand, scheduled, by,
            time.monotonic() - timersmod.GATE_KEEP_SEC - 1, 0.0, reason)
    assert sched.enqueue_due() == []
    assert sched.gated() == []
    assert ("log", "timers.log.gate_expired") in ran, \
        "an event given up on is never silent"


def test_a_catalogue_timer_is_left_to_its_own_clock():
    """It has one; parking it as well would run it twice for the same moment."""

    class _WithEntry(_Catalogue):
        def by_name(self, name):
            return _Errand(name)

    sched, _ran = _scheduler(lambda name: "timers.log.skip_game")
    sched._catalogue = lambda: _WithEntry()
    sched._enqueue("collect_base_resources", scheduled=True)
    sched.drain()
    assert sched.gated() == [], "a timer comes back on its clock, not through the park"


def test_a_retry_waits_its_beat_rather_than_spinning():
    """The gate is asked again on `GATE_RETRY_SEC`, not on every pass of the tick."""
    asked: list = []

    def gate(name):
        asked.append(name)
        return "timers.log.skip_game"

    sched, _ran = _scheduler(gate)
    sched.submit(_Errand())
    before = len(asked)
    sched.enqueue_due()
    sched.enqueue_due()
    assert len(asked) == before, "a parked fire must not re-ask the gate every tick"


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
