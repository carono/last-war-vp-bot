r"""What the SERVER answered reaches the run — the lines a button declares (#1416).

Everything a chunk logs comes back to `Interpreter._run_lua`, and the press paths read
out the two or three fields they need (`tap=`, `fired=`, `gate left=`) and drop the rest.
That is where a button's own verdict about what the game said used to end.

The robbery is the case that paid for this. `secret_task_queue_pop` has printed

    ACT steal_done uuid=<u> how=<taken|gone|unanswered>

since #1272, and BOTH readers of it — the «Автолут ★» watcher and the tab's own press —
match that line in the run's event stream. The stream never carried it, so a tile the
server called «задание уже взято» was never taken off the list and was chosen again on
the next tick, for as long as it stayed on the map. That is «автоограбление не читает
ответ игры».

`Button.relay` names the lines a run is entitled to hear. A list rather than «relay
everything»: the same robbery prints `steal_sent` on every one of up to sixty presses in
a spam, and a run that repeated all of them would bury its own verdict.

No game, no daemon: the evaluator is a stub that hands back the lines a chunk «logged»::

    python3 tests/test_engine_relay.py
    C:\Python312\python.exe tests\test_engine_relay.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import game_buttons                                       # noqa: E402
from lastwar_bot import script_engine                     # noqa: E402


class _Evaluator:
    """A game VM that logs whatever it was told to, and nothing else."""

    def __init__(self, lines) -> None:
        self.lines = list(lines)
        self.chunks: list = []

    def run(self, chunk, marker="ACT", settle=1.2, early=True):
        self.chunks.append(chunk)
        return list(self.lines)


def _interp(lines, said):
    interp = script_engine.Interpreter(
        script_engine.new_context(0, lambda msg: said.append(str(msg))))
    interp._evaluator = lambda: _Evaluator(lines)
    return interp


def _button(**kw):
    base = {"lua": "return 1", "wait": 0.0, "label": "test button"}
    base.update(kw)
    return game_buttons.Button(**base)


def test_a_declared_line_reaches_the_run():
    said: list = []
    btn = _button(relay=("steal_done",))
    interp = _interp([], said)
    interp._relay(btn, ["ACT tap=ok",
                        "ACT steal_done uuid=42 how=gone tip=dispatch_des042"])
    assert any("steal_done uuid=42 how=gone" in line for line in said), said
    assert not any("tap=ok" in line for line in said), \
        "the interpreter's own telemetry is not the run's news"


def test_a_button_that_declares_nothing_says_nothing_extra():
    said: list = []
    interp = _interp([], said)
    interp._relay(_button(), ["ACT steal_done uuid=42 how=gone"])
    assert said == [], said


def test_the_marker_prefix_is_stripped():
    """`ACT ` is what the evaluator keys on, not a word anybody reads."""
    said: list = []
    interp = _interp([], said)
    interp._relay(_button(relay=("steal_done",)), ["ACT steal_done uuid=7 how=taken"])
    assert said and said[-1].strip().startswith("steal_done"), said


def test_a_plain_press_relays_what_the_chunk_logged():
    """The whole path, not just the helper: `TAP` with no verifier (`drop_steal_target`)."""
    said: list = []
    btn = _button(relay=("steal_done",))
    interp = _interp(["ACT tap=ok", "ACT steal_done uuid=9 how=unanswered tip="], said)
    interp._press_button(btn)
    assert any("steal_done uuid=9 how=unanswered" in line for line in said), said


def test_the_robbery_button_declares_its_verdict():
    """…and the button that needs it actually carries the declaration.

    Both readers match `steal_done` off the event stream
    (`panel/tabs/secret_tasks/autoloot.py::DONE_LINE`), so a `drop_steal_target` that
    stopped declaring the line would silently disable the whole gate again.
    """
    btn = game_buttons.BUTTONS["drop_steal_target"]
    assert "steal_done" in btn.relay, btn.relay
    assert "steal_done" in btn.lua, "the button no longer prints the verdict it declares"


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
