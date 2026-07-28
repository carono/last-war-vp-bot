r"""Unit tests for the DSL game-VM primitives (LUA / READ_LUA / GAME / JUMP).

These exercise the Lua-daemon bridge in src/lastwar_bot/script_engine.py with a *fake*
evaluator injected onto the run context — so they need no game, no daemon and no
Wireshark, and run anywhere.

    python3 tests/test_game_primitives.py    # standalone, prints PASS/FAIL
    pytest tests/test_game_primitives.py     # or under pytest

Exit codes (standalone): 0 = passed, 1 = failed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "src", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lastwar_bot import script_engine as se  # noqa: E402


class FakeEval:
    """Records every Lua chunk; for READ_LUA queries, replays a scripted RLUA value.

    `rluas` is a list of values returned, in order, to successive READ_LUA (marker
    "RLUA") chunks — so a test can drive a countdown loop deterministically.
    """

    def __init__(self, rluas=None) -> None:
        self.chunks: list[str] = []
        self._rluas = list(rluas or [])

    def run(self, chunk, marker=None, settle=1.4):
        self.chunks.append(chunk)
        if marker == "RLUA":
            val = self._rluas.pop(0) if self._rluas else "nil"
            return [f"RLUA {val}"]
        return []


def _run(script: str, evaluator) -> tuple[list[str], se.Context]:
    """Parse+run a script with a fake evaluator; return (log lines, context)."""
    log: list[str] = []
    ctx = se.Context(hwnd=0, on_event=log.append, evaluator=evaluator)
    se.Interpreter(ctx)._run_block(se.parse_text(script))
    return log, ctx


def test_parse_lua_and_readlua():
    (lua,) = se.parse_text("LUA UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceScience)")
    assert isinstance(lua, se.LuaStmt)
    assert lua.chunk == "UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceScience)"
    (rl,) = se.parse_text("READ_LUA Foo:Bar() INTO attempts")
    assert isinstance(rl, se.ReadLuaStmt)
    assert rl.expr == "Foo:Bar()" and rl.var == "attempts"
    (jump,) = se.parse_text("JUMP 512, 640, 972")
    assert (jump.x, jump.y, jump.server) == (512, 640, 972)


def test_parse_tap():
    (t,) = se.parse_text("TAP donate_1000 x30")
    assert isinstance(t, se.TapStmt) and t.name == "donate_1000" and t.count == 30
    (t2,) = se.parse_text("TAP alliance")
    assert t2.name == "alliance" and t2.count == 1


def test_tap_presses_button_n_times():
    ev = FakeEval()
    _run("TAP donate_1000 x3", ev)
    presses = sum(1 for c in ev.chunks if "OnResDonateClick" in c)
    assert presses == 3, f"expected 3 button presses, got {presses}"


def test_parse_tap_all():
    (t,) = se.parse_text("TAP donate_1000 xall")
    assert isinstance(t, se.TapStmt) and t.name == "donate_1000" and t.count is None


def test_tap_all_presses_until_count_zero():
    # count_lua reads 3, 2, 1, 0 -> exactly 3 presses (one press per non-zero read).
    ev = FakeEval(rluas=["3", "2", "1", "0"])
    _run("TAP donate_1000 xall", ev)
    presses = sum(1 for c in ev.chunks if "OnResDonateClick" in c)
    assert presses == 3, f"expected 3 presses for xall over 3->0, got {presses}"


def test_tap_all_without_count_is_error():
    # `close` has no count_lua, so xall on it must fail loudly.
    ev = FakeEval()
    try:
        _run("TAP close xall", ev)
    except se.ScriptRuntimeError:
        pass
    else:
        raise AssertionError("xall on a button with no count should raise")


def test_tap_unknown_button_is_runtime_error():
    ev = FakeEval()
    try:
        _run("TAP no_such_button", ev)
    except se.ScriptRuntimeError:
        pass
    else:
        raise AssertionError("unknown button should raise")


def test_lua_runs_chunk_verbatim():
    ev = FakeEval()
    _run("LUA SomeGame.Call(1, 2)", ev)
    assert any("SomeGame.Call(1, 2)" in c for c in ev.chunks), "LUA must send the chunk verbatim"
    assert any("pcall" in c for c in ev.chunks), "LUA should guard with pcall"


def test_read_lua_coerces_and_stores():
    ev = FakeEval(rluas=["7"])
    _log, ctx = _run("READ_LUA Foo:Count() INTO n", ev)
    assert ctx.vars["n"] == 7 and isinstance(ctx.vars["n"], int)


def test_while_var_countdown_presses_once_per_iteration():
    # attempts read: 3, 2, 1, 0 -> exactly 3 presses (one LUA per loop body).
    ev = FakeEval(rluas=["3", "2", "1", "0"])
    script = (
        "READ_LUA Foo:Rest() INTO attempts\n"
        "WHILE attempts > 0 LIMIT 40\n"
        "    LUA Foo:Press()\n"
        "    READ_LUA Foo:Rest() INTO attempts\n"
    )
    _run(script, ev)
    presses = sum(1 for c in ev.chunks if "Foo:Press()" in c)
    assert presses == 3, f"expected 3 presses, got {presses}"


def test_unknown_variable_is_runtime_error():
    ev = FakeEval()
    try:
        _run("WHILE nope > 0 LIMIT 3\n    LOG \"x\"", ev)
    except se.ScriptRuntimeError:
        pass
    else:
        raise AssertionError("using an unset variable should raise")


def test_game_scene_and_jump_sugar():
    ev = FakeEval()
    _run("GAME WORLD", ev)
    assert any("ChangeToWorld" in c for c in ev.chunks)
    ev2 = FakeEval()
    _run("JUMP 100, 200, 972", ev2)
    joined = "\n".join(ev2.chunks)
    assert "GotoWorldPos" in joined and "972" in joined


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
