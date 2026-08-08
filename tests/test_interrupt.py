r"""«Прервать» — a running scenario ends WHERE IT IS, and says so (#1300).

The footer's button, and the phone's, are one press over one register
(`panel/runtime/interrupt.py`). What this pins is everything about that press a person
would notice if it broke:

* a run is on the register while it runs, and off it the moment it ends — a stale entry
  would have the button offering to stop something that finished an hour ago;
* a LONG step does not have to finish first. `WAIT 30` used to be one `time.sleep(30)`,
  so a Stop pressed a second in was noticed half a minute later; the sleep is sliced now
  and the run halts inside it;
* an interrupted run is NOT a successful one. A scenario's own `STOP` still reports
  success — it decided it was done — and an interrupted one reports failure, because it
  did not finish. The two say different words in the log for the same reason (#1296).
* the steps BEHIND the one that was stopped are refused, so a timer's multi-step errand
  does not carry on into whatever made somebody press the button;
* and it can all be done again straight afterwards: nothing is left held, and a fresh
  run on a fresh context plays normally.

Runs anywhere: the scenarios are written to a temp dir and use only LOG / WAIT / STOP /
FAIL, so nothing touches the game.

    python3 tests/test_interrupt.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
import tempfile
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_runtime  # noqa: E402
from panel.runtime.actions import ActionRunner  # noqa: E402
from panel.runtime.interrupt import Interrupts, Stop  # noqa: E402


def _runner(tmp: Path, interrupts=None):
    from lastwar_bot import script_engine as se
    se.ACTIONS_DIR = tmp
    se.DEV_ACTIONS_DIR = tmp / "dev"
    bus = fake_runtime.RecordingBus()
    return ActionRunner(log=bus, interrupts=interrupts), bus


def _write(tmp: Path, name: str, body: str) -> None:
    (tmp / f"{name}.md").write_text(f"# {name}.\n\n{body}", encoding="utf-8")


def _await(check, timeout: float = 5.0) -> bool:
    """Wait for a condition another thread brings about. Never a bare sleep."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return False


# -- the register ------------------------------------------------------------
def test_a_run_is_on_the_register_while_it_runs_and_off_it_afterwards():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "slow", 'LOG "starting"\nWAIT 30\nLOG "done"\n')
        register = Interrupts()
        runner, _bus = _runner(tmp, register)
        assert not register.busy(), "nothing has been played yet"
        done = []
        worker = threading.Thread(
            target=lambda: done.append(runner.run("slow", tag="timer")), daemon=True)
        worker.start()
        assert _await(register.busy), "the run never appeared on the register"
        runs = register.running()
        assert len(runs) == 1 and runs[0].name == "slow", runs
        assert runs[0].tag == "timer", "who started it travels with the run"
        # …and the step it has reached, which is what the log line is worth having for.
        assert _await(lambda: "WAIT 30" in register.running()[0].step), \
            register.running()[0].step
        register.stop()
        worker.join(timeout=5)
        assert not worker.is_alive(), "the run did not end when asked"
        assert not register.busy(), "the run stayed on the register after ending"


def test_the_register_is_empty_again_even_when_the_scenario_failed():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "nope", 'FAIL "not today"\n')
        register = Interrupts()
        runner, _bus = _runner(tmp, register)
        assert runner.run("nope") is False
        assert not register.busy(), "a failed run left itself on the register"


# -- a long step stops where it is -------------------------------------------
def test_a_fixed_wait_is_cut_short_rather_than_waited_out():
    """The whole point: `WAIT 30` must not mean «stopped in half a minute»."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "napping", 'LOG "in"\nWAIT 30\nLOG "never"\n')
        register = Interrupts()
        runner, bus = _runner(tmp, register)
        out = []
        worker = threading.Thread(
            target=lambda: out.append(runner.run("napping")), daemon=True)
        worker.start()
        assert _await(lambda: "WAIT 30" in "".join(bus.lines)), bus.lines
        pressed = time.monotonic()
        register.stop()
        worker.join(timeout=5)
        took = time.monotonic() - pressed
        assert not worker.is_alive(), "the run sat out its whole WAIT"
        assert took < 2.0, f"it took {took:.1f}s to notice — the sleep is not sliced"
        assert out == [False], "an interrupted run did not finish, so it is not a success"
        assert not any("never" in line for line in bus.lines), \
            "the statement after the WAIT was played anyway"


def test_the_log_tells_an_interrupted_run_from_one_that_stopped_itself():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "quits", 'LOG "in"\nSTOP "nothing to do"\n')
        _write(tmp, "napping", 'WAIT 30\n')
        register = Interrupts()
        runner, bus = _runner(tmp, register)
        assert runner.run("quits") is True, "STOP is the scenario deciding it is done"
        said = "\n".join(bus.lines)
        assert "HALTED" in said and "INTERRUPTED" not in said, said
        bus.lines.clear()
        worker = threading.Thread(target=lambda: runner.run("napping"), daemon=True)
        worker.start()
        assert _await(lambda: "WAIT 30" in "".join(bus.lines)), bus.lines
        register.stop()
        worker.join(timeout=5)
        said = "\n".join(bus.lines)
        assert "INTERRUPTED" in said, said
        assert "HALTED" not in said, "the two must not read the same a month later"


# -- what the press says -----------------------------------------------------
def test_the_press_names_what_it_stopped_and_where():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "napping", 'WAIT 30\n')
        register = Interrupts()
        runner, bus = _runner(tmp, register)
        worker = threading.Thread(target=lambda: runner.run("napping"), daemon=True)
        worker.start()
        assert _await(lambda: bool(register.running())
                      and "WAIT" in register.running()[0].step)
        stopped = register.stop()
        worker.join(timeout=5)
        assert len(stopped) == 1, stopped
        assert stopped[0]["name"] == "napping"
        assert "WAIT 30" in stopped[0]["step"], stopped[0]
        # …and the run itself said, in the log, that it really ended.
        assert any("interrupt.halted" in line or "napping" in line for line in bus.lines)


def test_pressing_into_an_idle_panel_says_so_instead_of_nothing():
    register = Interrupts()
    assert register.stop() == [], "there was nothing to stop"
    assert register.presses == 1, "the press is still counted — it happened"


# -- the rest of an errand ---------------------------------------------------
def test_the_steps_behind_the_interrupted_one_are_refused():
    """A timer's errand shares ONE context across its steps (panel/runtime/schedule.py)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "napping", 'WAIT 30\n')
        _write(tmp, "after", 'LOG "should never run"\n')
        register = Interrupts()
        runner, bus = _runner(tmp, register)
        ctx = runner.context()
        worker = threading.Thread(
            target=lambda: runner.run("napping", ctx=ctx, tag="timer"), daemon=True)
        worker.start()
        assert _await(lambda: "WAIT 30" in "".join(bus.lines)), bus.lines
        register.stop()
        worker.join(timeout=5)
        assert runner.run("after", ctx=ctx, tag="timer") is False, \
            "the next step of a stopped errand was played"
        assert not any("should never run" in line for line in bus.lines), bus.lines


def test_a_fresh_run_works_straight_after_an_interruption():
    """«Повторный запуск сразу работает» — nothing is left held."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "napping", 'WAIT 30\n')
        _write(tmp, "quick", 'LOG "hello"\n')
        register = Interrupts()
        runner, bus = _runner(tmp, register)
        worker = threading.Thread(target=lambda: runner.run("napping"), daemon=True)
        worker.start()
        assert _await(lambda: "WAIT 30" in "".join(bus.lines)), bus.lines
        register.stop()
        worker.join(timeout=5)
        assert runner.run("quick") is True, "a run after an interruption was refused"
        assert not register.busy()


# -- the flag ----------------------------------------------------------------
def test_a_callers_own_stop_flag_still_works_beside_the_register():
    """The Scenarios tab has had its own `Event` since long before the register."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "napping", 'WAIT 30\n')
        register = Interrupts()
        runner, bus = _runner(tmp, register)
        mine = threading.Event()
        out = []
        worker = threading.Thread(
            target=lambda: out.append(runner.run("napping", cancel=mine)), daemon=True)
        worker.start()
        assert _await(lambda: "WAIT 30" in "".join(bus.lines)), bus.lines
        mine.set()                                  # the tab's own Stop, not the footer's
        worker.join(timeout=5)
        assert out == [False], "the caller's own flag no longer ends the run"
        assert not register.busy()


def test_a_stop_answers_for_every_flag_it_holds():
    own = Stop()
    assert not own.is_set()
    borrowed = threading.Event()
    both = Stop(borrowed)
    assert not both.is_set()
    borrowed.set()
    assert both.is_set(), "a flag handed in by the caller has to count"
    mine = Stop(threading.Event())
    mine.set()
    assert mine.is_set()


def test_a_scenario_run_with_no_register_of_its_own_is_still_stoppable():
    """A bare `ActionRunner` — a test, a tab launched on its own — makes its own."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "napping", 'WAIT 30\n')
        runner, bus = _runner(tmp)                  # no register passed in
        worker = threading.Thread(target=lambda: runner.run("napping"), daemon=True)
        worker.start()
        assert _await(lambda: runner.interrupts.busy()), "nothing was registered"
        runner.interrupts.stop()
        worker.join(timeout=5)
        assert not worker.is_alive()


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
