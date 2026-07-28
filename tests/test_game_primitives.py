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


def test_scene_condition_reads_state():
    # _current_scene evaluates a Lua expr via RLUA; FakeEval replays the tag.
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=FakeEval(rluas=["city"]))
    interp = se.Interpreter(ctx)
    assert interp.eval_condition("scene == city", 1) is True
    ctx.evaluator = FakeEval(rluas=["world"])
    assert interp.eval_condition("scene == city", 1) is False
    assert se.Interpreter(se.Context(hwnd=0, evaluator=FakeEval(rluas=["world"]))
                          ).eval_condition("scene == world", 1) is True


def test_scene_unknown_when_vm_unreachable():
    # A VM error (None) must read as 'unknown', not crash — this is what a launch
    # WAIT relies on while the daemon is re-hijacking a freshly-launched process.
    class Dead:
        def run(self, *a, **k):
            raise RuntimeError("daemon down")
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=Dead())
    interp = se.Interpreter(ctx)
    assert interp.eval_condition("scene == unknown", 1) is True
    assert interp.eval_condition("scene == city", 1) is False


def test_game_scene_and_jump_sugar():
    ev = FakeEval()
    _run("GAME WORLD", ev)
    assert any("ChangeToWorld" in c for c in ev.chunks)
    ev2 = FakeEval()
    _run("JUMP 100, 200, 972", ev2)
    joined = "\n".join(ev2.chunks)
    assert "GotoWorldPos" in joined and "972" in joined


def test_occupation_skills_recipe_walks_the_ready_set():
    """The profession-skill recipe presses once per ready skill, then clears the modal.

    Two things this pins down, both of which cost real charges to get wrong:
    the press must be driven by `xall` off a live count (never a fixed number, since
    how many skills are off cooldown is not knowable when the recipe is written), and
    each press must carry the re-fire stamp that stops one skill being fired twice
    while its cooldown is still in flight on the server.
    """
    import game_buttons as gb

    path = se.resolve_action("occupation_skills")
    assert path is not None, "actions/occupation_skills.md is missing"
    stmts = se.parse_text(path.read_text(encoding="utf-8"))
    assert [s.name for s in stmts] == ["use_profession_skill", "dismiss_skill_result"]
    assert stmts[0].count is None, "the press must be TAP … xall, not a fixed count"

    button = gb.get("use_profession_skill")
    assert button is not None and button.count_lua, "xall needs a count expression"
    # Two ready skills, then none -> exactly two presses.
    ev = FakeEval(rluas=[2, 1, 0])
    _run("TAP use_profession_skill xall", ev)
    presses = [c for c in ev.chunks if "UseSkill" in c]
    assert len(presses) == 2, presses
    assert all("__lw_fired" in c for c in presses), "presses must stamp the re-fire guard"


def test_occupation_skill_cooldown_is_server_clocked_and_state_aware():
    """The cooldown read must use the SERVER clock and rule out `Covered` / `Locked`.

    A `Covered` node (a tier superseded by a higher one) carries no charge data, so its
    availability time is 0 — read naively that says "ready now" about a skill that can
    never be pressed. The sentinel is -1, not 0, precisely so a scheduler can tell
    "castable, waiting" from "not a question about this skill".
    """
    import lua_actions as la

    cd = la.skill_cooldown_remaining(10113)
    assert "GetSkillAvailableTime" in cd
    assert "GetServerTime" in cd, "the local clock drifts from the server's"
    assert "MasterySkillState.Covered" in cd and "MasterySkillState.Locked" in cd
    assert "return -1" in cd


def test_mastery_gate_is_state_and_use_position():
    """Ready = `Normal` state AND a no-target (`SkillView`) skill — both, not either.

    Dropping either half is a live bug: without the state check a press lands on a
    skill still in cooldown and earns a server rejection toast; without the
    use-position check it fires a skill that wants a world target at nothing.
    """
    import lua_actions as la

    ready = la.occupation_skills_ready_count()
    assert "MasterySkillState.Normal" in ready
    assert "MasterySkillUsePosType.SkillView" in ready
    assert "active_skills" in ready
    # A specific-skill press carries the same gate plus its own id.
    one = la.apply_occupation_skill(10113)
    assert "10113" in one and "MasterySkillState.Normal" in one


def test_steal_recipe_spends_the_queue_and_stops_at_the_budget():
    """The robbery recipe presses once per queued target and closes the loot window.

    `xall` is load-bearing here for two reasons a fixed count cannot cover: how many
    targets are queued is not knowable when the recipe is written, and the daily cap
    (five robberies) is spent by anything else that robbed today. The button's count
    is the minimum of the two, so the loop stops at whichever runs out first.
    """
    import game_buttons as gb

    path = se.resolve_action("steal_secret_task")
    assert path is not None, "actions/steal_secret_task.md is missing"
    stmts = se.parse_text(path.read_text(encoding="utf-8"))
    taps = [s for s in stmts if isinstance(s, se.TapStmt)]
    assert [s.name for s in taps] == ["steal_secret_task", "dismiss_steal_reward"]
    assert taps[0].count is None, "the press must be TAP … xall, not a fixed count"

    button = gb.get("steal_secret_task")
    assert button is not None and button.count_lua, "xall needs a count expression"
    # Two robberies available, then none -> exactly two presses.
    ev = FakeEval(rluas=[2, 1, 0])
    _run("TAP steal_secret_task xall", ev)
    presses = [c for c in ev.chunks if "MsgDefines.DispatchSteal" in c]
    assert len(presses) == 2, presses
    assert all("table.remove" in c for c in presses), "a press must consume its target"


def test_steal_is_gated_on_the_daily_budget():
    """Every robbery carries the daily-cap gate, and the count never exceeds it.

    Sending past the cap is not a no-op: the server refuses it and the client raises a
    player-facing tip, the same trap as the resource-collect readiness gate. The queue
    length alone would happily send ten.
    """
    import lua_actions as la

    left = la.secret_task_steals_left()
    assert "steal_count" in left and "GetTodayStealNum" in left

    for chunk in (la.secret_task_steal(1, 534), la.steal_next_secret_task()):
        assert "GetTodayStealNum" in chunk, "an ungated robbery reaches the server"
        assert "MsgDefines.DispatchSteal" in chunk

    pending = la.secret_task_steals_pending()
    assert "__lw_steal_queue" in pending and "steal_count" in pending

    # The target is a uuid + server, never a coordinate (the command has no point field).
    queued = la.secret_task_queue_set([(1397117352503547575, 534)])
    assert "uuid=1397117352503547575" in queued and "server=534" in queued


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
