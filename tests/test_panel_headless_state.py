r"""A tab's state and the panel's clock, with NO window under them (#1976, P3).

The window is being deleted (`docs/research/panel-service-and-spa-plan.md` P3), and two
things it owns have to go on working without it — not «be replaced eventually», but work
on the day the window is gone and every day before it:

  * **the 126 variables a tab keeps its state in.** A `StringVar` was the label as well as
    the value, which was the right shape while a value existed to be drawn; a panel
    serving a phone holds the same schedule, the same standing orders and the same
    settings with nothing to draw them into. `panel/runtime/statevar.py` hands back the
    WINDOW's variable while there is a window and a plain one when there is not, so the
    same line of a tab works either way and `textvariable=` is untouched until Tk goes;
  * **the clock.** Every repeating callback rides Tk's `after` queue, and `Ticker` with no
    widget silently arms NOTHING — which is a schedule that never fires. `ThreadTicker`
    keeps the two guarantees the panel actually leans on: one thread runs everything, and
    posting is FIFO and never raises.

Runs anywhere: no display, no game, and — the point of the exercise — no `tkinter` at all.

    C:\Python312\python.exe tests\test_panel_headless_state.py
    python3 tests/test_panel_headless_state.py
"""
from __future__ import annotations

TIER = "offline"   # no window, no display, no Tk

import importlib.util as _util
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _module(name: str, path: str):
    """Load one file WITHOUT importing the package around it.

    `panel.runtime` imports the log pane, which imports tkinter — and the whole point
    here is that these two files do not. Loading them alone is what proves it.
    """
    spec = _util.spec_from_file_location(name, _REPO / path)
    module = _util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


statevar = _module("statevar", "panel/runtime/statevar.py")
tickmod = _module("tickmod", "panel/runtime/tick.py")


# ---------------------------------------------------------------------------
# the variable
# ---------------------------------------------------------------------------
def test_a_variable_with_no_window_keeps_its_value_and_its_type() -> None:
    text = statevar.string(None, "hello")
    assert text.get() == "hello"
    text.set(42)
    assert text.get() == "42", "a string variable stopped being a string"

    flag = statevar.boolean(None)
    assert flag.get() is False
    flag.set(1)
    assert flag.get() is True, "a boolean variable stopped being a boolean"

    count = statevar.integer(None, "7")
    assert count.get() == 7 and isinstance(count.get(), int)
    count.set("not a number")
    assert count.get() == 0, "junk in a number box must read as the empty one, not raise"


def test_a_write_reaches_every_watcher_and_one_that_raises_stops_nothing() -> None:
    """Tk's own contract: the trace is what saves the profile and redraws the line."""
    var = statevar.string(None, "")
    seen: list = []
    var.trace_add("write", lambda *_a: (_ for _ in ()).throw(RuntimeError("boom")))
    handle = var.trace_add("write", lambda *_a: seen.append(var.get()))
    var.set("one")
    assert seen == ["one"], seen
    var.trace_remove("write", handle)
    var.set("two")
    assert seen == ["one"], "a removed watcher is still being told"


def test_the_window_still_owns_its_variables_while_there_is_one() -> None:
    """Not a replacement for Tk while Tk is here: `textvariable=` must keep working."""
    try:
        import tkinter as tk
    except Exception as exc:                     # noqa: BLE001 — no Tk in this box
        print(f"    (skipped: {type(exc).__name__}: {exc})")
        return
    try:
        root = tk.Tk()
        root.withdraw()
    except Exception as exc:                     # noqa: BLE001 — headless box
        print(f"    (skipped: {type(exc).__name__}: {exc})")
        return
    try:
        var = statevar.string(root, "x")
        assert isinstance(var, tk.StringVar), type(var)
        flag = statevar.boolean(root, True)
        assert isinstance(flag, tk.BooleanVar) and flag.get() is True
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# the clock
# ---------------------------------------------------------------------------
def test_the_windowless_clock_actually_fires() -> None:
    """`Ticker` with no widget arms nothing at all — which is a schedule that never runs."""
    quiet = tickmod.Ticker(None)
    quiet.arm("never", 1, lambda: None)
    assert quiet.armed() == 0, "the Tk ticker pretended to arm something with no widget"

    clock = tickmod.ThreadTicker()
    fired = threading.Event()
    try:
        clock.arm("once", 10, fired.set)
        assert fired.wait(3.0), "the clock never fired"
        assert clock.armed() == 0, "a fired chain is still armed — it would fire twice"
    finally:
        clock.stop()


def test_a_chain_re_arms_itself_exactly_as_it_does_under_tk() -> None:
    clock = tickmod.ThreadTicker()
    beats: list = []

    def beat() -> None:
        beats.append(time.monotonic())
        if len(beats) < 3:
            clock.arm("beat", 10, beat)

    try:
        clock.arm("beat", 10, beat)
        for _ in range(200):
            if len(beats) >= 3:
                break
            time.sleep(0.02)
        assert len(beats) == 3, beats
    finally:
        clock.stop()


def test_disarming_stops_it_and_re_arming_moves_it() -> None:
    clock = tickmod.ThreadTicker()
    fired: list = []
    try:
        clock.arm("later", 5000, lambda: fired.append("late"))
        assert clock.armed() == 1
        assert [row["name"] for row in clock.pending()] == ["later"]
        clock.arm("later", 10, lambda: fired.append("soon"))   # re-armed, not doubled
        time.sleep(0.4)
        assert fired == ["soon"], fired
        clock.arm("gone", 5000, lambda: fired.append("never"))
        clock.disarm("gone")
        assert clock.armed() == 0
        clock.arm("swept", 5000, lambda: fired.append("never"))
        clock.disarm_all()
        assert clock.armed() == 0 and clock.pending() == []
        time.sleep(0.2)
        assert fired == ["soon"], fired
    finally:
        clock.stop()


def test_a_callback_that_raises_does_not_stop_the_clock() -> None:
    clock = tickmod.ThreadTicker()
    after = threading.Event()
    try:
        clock.arm("bad", 5, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        clock.arm("good", 30, after.set)
        assert after.wait(3.0), "one raising callback stopped everything else"
    finally:
        clock.stop()


def test_a_hand_over_is_fifo_and_runs_on_the_clocks_own_thread() -> None:
    """Tk's other guarantee, and the reason nothing in the panel locks around its state."""
    clock = tickmod.ThreadTicker()
    order: list = []
    threads: list = []
    done = threading.Event()
    try:
        for n in range(5):
            clock.post(lambda n=n: (order.append(n),
                                    threads.append(threading.current_thread().name)))
        clock.post(done.set)
        assert done.wait(3.0), "nothing posted ever ran"
        assert order == [0, 1, 2, 3, 4], order
        assert len(set(threads)) == 1, f"the hand-overs ran on {len(set(threads))} threads"
    finally:
        clock.stop()


def test_on_tk_waits_for_the_work_and_never_deadlocks_on_its_own_thread() -> None:
    clock = tickmod.ThreadTicker()
    box: list = []
    try:
        clock.on_tk(lambda: box.append("from a worker"))
        assert box == ["from a worker"], box
        # …and from INSIDE the clock's own thread it runs straight away rather than
        # queueing behind itself, exactly as `Ticker.on_tk` does on the Tk thread.
        inner = threading.Event()
        clock.post(lambda: (clock.on_tk(lambda: box.append("from the clock")),
                            inner.set()))
        assert inner.wait(3.0), "on_tk from the clock's own thread deadlocked"
        assert box == ["from a worker", "from the clock"], box
    finally:
        clock.stop()


def test_neither_file_imports_tkinter() -> None:
    """The acceptance test of P3, applied to the two files that go first."""
    for path in ("panel/runtime/statevar.py", "panel/runtime/tick.py"):
        text = (_REPO / path).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import tkinter", "from tkinter")):
                # `statevar` imports it INSIDE the one function that asks for a window's
                # own variable, and `tick` inside the two that touch a widget's queue —
                # both under a `try`, so a panel with no Tk installed still imports them.
                assert not stripped.startswith("import tkinter") or "    " in line[:4], \
                    f"{path}: tkinter at import time"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
