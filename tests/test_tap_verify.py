r"""A press that reports from a RE-READ, not from «the Lua did not raise» (#1282).

`script_engine._press_button` wraps a button's Lua in a `pcall` and logs `ACT tap=ok`
when it did not throw. That says the call ran. It does not say the game did anything —
and 32 of the 44 `TAP` lines in the shipped recipes have nothing to verify against, which
is the mechanism behind a whole class of «the panel confidently reported the wrong
thing»: the client told it was being restarted and was not (#1259), «развести клиенты»
that changed nothing (#1263), a live socket vouching for a dead game link (#1266).

A button may now declare `verify_lua` — an expression whose CHANGE after the press is the
proof. This file pins what that means:

  * a button WITHOUT one behaves exactly as it always did, so every shipped recipe is
    untouched by the mechanism landing;
  * a button WITH one reads the before-value in the same chunk as the press (nothing can
    move in between), then polls;
  * the value moving is a pass; the value not moving by the deadline FAILS the recipe
    rather than logging `tap=ok`;
  * and `wait` is that deadline rather than a sleep, so a verified press returns as soon
    as the game has answered — §1.3 of the audit, the same edit.

Needs neither Tk, a display nor a game: the evaluator is a fake.

    C:\Python312\python.exe tests\test_tap_verify.py
    python3 tests/test_tap_verify.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import game_buttons                                             # noqa: E402
from lastwar_bot import script_engine as se                     # noqa: E402


class FakeEval:
    """A game whose one number moves after `moves_after` presses — or never.

    It answers the two chunk shapes a verified press makes: the combined
    «read-before-and-press» one, and the plain `RLUA` re-read that follows it.
    """

    def __init__(self, moves_after: int = 1, start: int = 5) -> None:
        self.value = start
        self.presses = 0
        self.reads = 0
        self.moves_after = moves_after
        self.chunks: list[str] = []

    def run(self, chunk, marker=None, settle=1.4, early=False, **kw):
        self.chunks.append(chunk)
        if marker == "RLUA" or "RLUA " in chunk:
            self.reads += 1
            return [f"RLUA {self.value}"]
        was = self.value
        self.presses += 1
        if self.presses >= self.moves_after:
            self.value -= 1
        if " was=" in chunk or "was=" in chunk:
            return [f"ACT tap=ok was={was}"]
        return ["ACT tap=ok"]


def _run(script: str, evaluator) -> tuple:
    log: list[str] = []
    ctx = se.Context(hwnd=0, on_event=log.append, evaluator=evaluator)
    # The link gate walks the machine's socket table once per run and fails the whole
    # thing when no client is talking to a server. That is right for a recipe and wrong
    # for a test: on Windows it finds no client and nothing below ever presses, while on
    # a box where the probe cannot run at all it quietly passes — the same file green on
    # one interpreter and red on the other, which is how #1282 found it.
    ctx.link_checked = True
    se.Interpreter(ctx)._run_block(se.parse_text(script))
    return log, ctx


class _button:
    """Put one button in the catalogue for the length of a test."""

    def __init__(self, name: str, **kw) -> None:
        self.name = name
        self.button = game_buttons.Button(**kw)

    def __enter__(self) -> str:
        game_buttons.BUTTONS[self.name] = self.button
        return self.name

    def __exit__(self, *exc) -> None:
        game_buttons.BUTTONS.pop(self.name, None)


def test_a_button_with_no_verifier_presses_exactly_as_it_always_did() -> None:
    """The 55 buttons in the catalogue today: not one line of behaviour changes."""
    with _button("probe_plain", lua="Foo:Bar()", wait=0.0, label="plain") as name:
        ev = FakeEval()
        log, _ctx = _run(f"TAP {name}", ev)
        assert ev.presses == 1, ev.presses
        assert ev.reads == 0, "an unverified press must not re-read anything"
        assert any("TAP plain" in ln for ln in log), log


def test_a_verified_press_reads_before_in_the_same_chunk_as_the_press() -> None:
    """Two calls would leave a gap in which the number could move on its own."""
    with _button("probe_ok", lua="Foo:Bar()", wait=1.0, label="verified",
                 verify_lua="Foo:Count()") as name:
        ev = FakeEval(moves_after=1)
        _log, _ctx = _run(f"TAP {name}", ev)
        first = ev.chunks[0]
        assert "Foo:Count()" in first and "Foo:Bar()" in first, first
        assert first.index("return Foo:Count()") < first.index("Foo:Bar()"), \
            "the before-value must be read BEFORE the press, in the same chunk"


def test_a_value_that_moves_is_the_proof_and_the_press_passes() -> None:
    with _button("probe_ok", lua="Foo:Bar()", wait=1.0, label="verified",
                 verify_lua="Foo:Count()") as name:
        ev = FakeEval(moves_after=1)
        log, _ctx = _run(f"TAP {name}", ev)
        assert ev.presses == 1
        assert ev.reads >= 1, "a verified press must re-read"
        assert any("TAP verified" in ln for ln in log), log


def test_a_press_that_changes_nothing_fails_the_recipe() -> None:
    """The whole point: “issued” stops being reported as “done”."""
    with _button("probe_dead", lua="Foo:Bar()", wait=0.2, label="dead",
                 verify_lua="Foo:Count()") as name:
        ev = FakeEval(moves_after=99)          # the number never moves
        try:
            _run(f"TAP {name}", ev)
        except se.ScriptRuntimeError as exc:
            assert "nothing moved" in str(exc), exc
            assert "Foo:Count()" in str(exc), "the failure must name what it watched"
        else:
            raise AssertionError("a press that changed nothing was reported as done")
        assert ev.presses == 1


def test_the_wait_is_a_deadline_and_not_a_sleep() -> None:
    """A button with a 3-second pause whose value moves at once returns at once.

    §1.3 of the audit, in one assertion: 56 `wait` values across the catalogue sum to
    62.5 s of unconditional `time.sleep`, and #1230 measured a single `TAP` at 1228 ms
    of which 1000 was the button's own pause.
    """
    with _button("probe_fast", lua="Foo:Bar()", wait=3.0, label="fast",
                 verify_lua="Foo:Count()") as name:
        ev = FakeEval(moves_after=1)
        started = time.monotonic()
        _run(f"TAP {name}", ev)
        spent = time.monotonic() - started
        assert spent < 1.0, f"the verified press still sat out its pause ({spent:.2f}s)"


def test_the_deadline_is_honoured_when_nothing_moves() -> None:
    """…and the other half: it does not give up before the button's own wait."""
    with _button("probe_slow", lua="Foo:Bar()", wait=0.4, label="slow",
                 verify_lua="Foo:Count()") as name:
        ev = FakeEval(moves_after=99)
        started = time.monotonic()
        try:
            _run(f"TAP {name}", ev)
        except se.ScriptRuntimeError:
            pass
        spent = time.monotonic() - started
        assert spent >= 0.35, f"it gave up after {spent:.2f}s of a 0.4s deadline"


def test_a_lua_error_in_the_press_is_a_failure_not_a_pass() -> None:
    class Raiser(FakeEval):
        def run(self, chunk, marker=None, settle=1.4, early=False, **kw):
            if marker == "RLUA" or "RLUA " in chunk:
                return ["RLUA 5"]
            return ["ACT tap=ERR:attempt to index a nil value was=5"]

    with _button("probe_err", lua="Foo:Bar()", wait=0.1, label="broken",
                 verify_lua="Foo:Count()") as name:
        try:
            _run(f"TAP {name}", Raiser())
        except se.ScriptRuntimeError as exc:
            assert "nothing moved" in str(exc), exc
        else:
            raise AssertionError("a press whose Lua raised was reported as done")


def test_every_shipped_button_that_declares_a_verifier_declares_an_expression() -> None:
    """A statement, not an expression, would be a syntax error inside the press chunk —
    and it would only show up live, on the one press that was meant to be honest."""
    for name, btn in game_buttons.BUTTONS.items():
        expr = getattr(btn, "verify_lua", None)
        if expr is None:
            continue
        assert not expr.strip().startswith(("local ", "if ", "for ", "while ")), \
            f"{name}: verify_lua must be an expression, got {expr!r}"


def _run_all() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:                              # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
