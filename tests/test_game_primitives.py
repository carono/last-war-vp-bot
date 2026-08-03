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


class FakeGame(FakeEval):
    """A fake that donates for real: a batched press spends attempts, a read reports them.

    Batched buttons send ONE chunk carrying `local n=<k>` and get back the tally the
    real chunk logs (`ACT fired=<k>`), so a test sees the same feedback loop the game
    gives — including a batch that asks for more than is banked.
    """

    def __init__(self, banked: int) -> None:
        super().__init__()
        self.rest = banked

    def run(self, chunk, marker=None, settle=1.4):
        self.chunks.append(chunk)
        if marker == "RLUA":
            return [f"RLUA {self.rest}"]
        if chunk.startswith("local n="):
            want = int(chunk.split("local n=", 1)[1].split()[0])
            fired = min(want, self.rest)
            self.rest -= fired
            return [f"ACT fired={fired}"]
        return []

    @property
    def batches(self) -> int:
        return sum(1 for c in self.chunks if c.startswith("local n="))

    @property
    def reads(self) -> int:
        return sum(1 for c in self.chunks if "GetResDonateRestCount" in c)


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
    # A batched button spends its repeat inside one call: `x3` = one chunk asking for 3.
    ev = FakeGame(banked=10)
    _run("TAP donate_1000 x3", ev)
    assert ev.batches == 1, f"expected 1 batched call, got {ev.batches}"
    assert ev.rest == 7, f"expected 3 of 10 attempts spent, {ev.rest} left"


def test_tap_without_a_batch_form_presses_once_per_call():
    # help_ally_all has no batch_lua — its repeat stays one press per game-VM call.
    ev = FakeEval()
    _run("TAP help_ally_all x3", ev)
    presses = sum(1 for c in ev.chunks if "AlHelpAll" in c)
    assert presses == 3, f"expected 3 separate presses, got {presses}"


def test_parse_tap_all():
    (t,) = se.parse_text("TAP donate_1000 xall")
    assert isinstance(t, se.TapStmt) and t.name == "donate_1000" and t.count is None


def test_tap_all_presses_until_count_zero():
    # A button with no batch form presses once per non-zero read: 3, 2, 1, 0 -> 3 presses.
    ev = FakeEval(rluas=["3", "2", "1", "0"])
    _run("TAP help_ally_all xall", ev)
    presses = sum(1 for c in ev.chunks if "AlHelpAll" in c)
    assert presses == 3, f"expected 3 presses for xall over 3->0, got {presses}"


def test_tap_all_spends_the_whole_quota_in_one_call():
    """The speed-up: `xall` on a batched button is one call, not one call per press.

    Donating is what it exists for — a round trip into the game VM costs ~0.15 s while
    the loop inside it is free. 7 banked attempts must cost one donate call, sized by
    the read before it and confirmed by the read after it, and must leave the quota at
    zero: the count, not a guess, is still what stops the loop.
    """
    import game_buttons as gb
    assert gb.get("donate_1000").batch_lua, "donate is the button that batches its presses"
    ev = FakeGame(banked=7)
    log, _ctx = _run("TAP donate_1000 xall", ev)
    assert ev.batches == 1, f"expected 1 batched call for 7 attempts, got {ev.batches}"
    assert ev.reads == 2, f"expected 2 count reads (size it, confirm it), got {ev.reads}"
    assert ev.rest == 0, f"expected the quota spent, {ev.rest} left"
    assert any("-> 7 press(es)" in ln for ln in log), f"press tally missing from {log}"


def test_tap_all_gives_up_when_a_batch_fires_nothing():
    """A count that will not fall must end the loop instead of spinning on it."""
    class Stuck(FakeGame):
        def run(self, chunk, marker=None, settle=1.4):
            self.chunks.append(chunk)
            if marker == "RLUA":
                return [f"RLUA {self.rest}"]
            return ["ACT fired=0"] if chunk.startswith("local n=") else []

    ev = Stuck(banked=5)
    log, _ctx = _run("TAP donate_1000 xall", ev)
    assert ev.batches == 1, f"expected exactly one attempted batch, got {ev.batches}"
    assert any("-> 0 press(es)" in ln for ln in log), f"expected a zero tally, got {log}"


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


def test_fail_parses_with_and_without_reason():
    (f1,) = se.parse_text("FAIL")
    assert isinstance(f1, se.FailStmt) and f1.reason is None
    (f2,) = se.parse_text('FAIL "not on base"')
    assert isinstance(f2, se.FailStmt) and f2.reason == "not on base"
    (f3,) = se.parse_text("RETURN FAIL")
    assert isinstance(f3, se.FailStmt), "RETURN FAIL is a synonym"


def test_stop_returns_true_but_fail_returns_false():
    """The whole point of FAIL: STOP ends a run as success, FAIL as failure."""
    assert se.run_text('STOP "done"',
                       ctx=se.Context(hwnd=0, evaluator=FakeEval())) is True
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=FakeEval())
    assert se.run_text('FAIL "nope"', ctx=ctx) is False
    assert ctx.failed and ctx.fail_reason == "nope"


def test_scene_guard_fails_off_base_and_passes_on_base():
    """The visitor recipes' new guard: FAIL off the base, run through on it."""
    guard = 'IF scene != city\n    FAIL "not on the base"\nLOG "ran"'
    off = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=FakeEval(rluas=["world"]))
    assert se.run_text(guard, ctx=off) is False
    assert off.failed
    on = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=FakeEval(rluas=["city"]))
    assert se.run_text(guard, ctx=on) is True
    assert not on.failed


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


def test_ghost_recon_recipe_is_a_noop_while_the_event_is_closed():
    """The ghost-recon recipe presses once per queued squad — and never off-day.

    «Операция Призрак» runs one day a week. Six days out of seven `IsOpenDay()` is
    false, and the count expression has to read 0 then, otherwise `xall` would fire
    robberies the server refuses (each one a toast in the operator's face). The queue
    can legitimately still hold yesterday's targets, so the open-day check cannot be
    left to "the queue is empty".
    """
    import game_buttons as gb

    path = se.resolve_action("steal_ghost_recon")
    assert path is not None, "actions/steal_ghost_recon.md is missing"
    stmts = se.parse_text(path.read_text(encoding="utf-8"))
    taps = [s for s in stmts if isinstance(s, se.TapStmt)]
    assert [s.name for s in taps] == ["steal_ghost_recon", "dismiss_ghost_recon_reward"]
    assert taps[0].count is None, "the press must be TAP … xall, not a fixed count"

    button = gb.get("steal_ghost_recon")
    assert button is not None and button.count_lua, "xall needs a count expression"
    assert "IsOpenDay" in button.count_lua, "off-day the count must read 0"

    # Two squads available, then none -> exactly two presses.
    ev = FakeEval(rluas=[2, 1, 0])
    _run("TAP steal_ghost_recon xall", ev)
    presses = [c for c in ev.chunks if "MsgDefines.GhostReconSteal" in c]
    assert len(presses) == 2, presses
    # Nothing available -> no press at all.
    idle = FakeEval(rluas=[0])
    _run("TAP steal_ghost_recon xall", idle)
    assert not [c for c in idle.chunks if "MsgDefines.GhostReconSteal" in c]


def test_ghost_recon_and_secret_task_robberies_never_share_state():
    """The two robberies must not touch each other's command, queue or budget.

    They look alike («украсть» on a map tile) and differ in every detail that
    matters: `ghost.recon.steal {uuid, ownerServer}` vs `hero.dispatch.steal
    {uuid, targetServer}`, a weekly event vs an everyday feature, and two budgets
    of five that are counted apart. Crossing them would send the wrong command at
    a real uuid and burn the wrong day's allowance.
    """
    import lua_actions as la

    ghost = la.steal_next_ghost_recon()
    dispatch = la.steal_next_secret_task()
    assert "GhostReconSteal" in ghost and "DispatchSteal" not in ghost
    assert "DispatchSteal" in dispatch and "GhostReconSteal" not in dispatch
    assert "__lw_ghost_queue" in ghost and "__lw_steal_queue" not in ghost
    assert "__lw_steal_queue" in dispatch and "__lw_ghost_queue" not in dispatch
    # Separate budgets: each reads its own manager's counter.
    assert "ActGhostreconManager" in la.ghost_recon_steals_left()
    assert "ActDispatchTaskDataManager" in la.secret_task_steals_left()
    # The ghost gate asks the game for the timing half with an EMPTY looter list —
    # a non-empty one throws inside the client (LuaEntry.player is nil).
    gate = la.ghost_recon_can_steal(1)
    assert "GetPointStealType" in gate and "t.completionTime, {}" in gate
    assert "stealMaxtimes" in gate, "the looter half has to be counted here"


# --- script arguments (ARGS / {name} substitution) --------------------------

def test_args_defaults_and_substitution():
    """`ARGS` declares a parameter and its default; `{name}` is replaced in the text."""
    src = ('ARGS squads = [1, 2, 3]\n'
           'ARGS note = hello\n'
           'LUA q = { {squads} } -- {note}\n')

    # No arguments: the script runs on its own defaults.
    body, merged = se.prepare_source(src, {})
    assert merged == {"squads": [1, 2, 3], "note": "hello"}, merged
    (lua,) = se.parse_text(body)
    assert lua.chunk == "q = { 1, 2, 3 } -- hello", lua.chunk

    # The caller's value wins, per field.
    body, merged = se.prepare_source(src, {"squads": [2, 3]})
    (lua,) = se.parse_text(body)
    assert lua.chunk == "q = { 2, 3 } -- hello", lua.chunk
    assert merged["squads"] == [2, 3]

    # The declarations never reach the parser, and the lines they stood on are kept
    # blank so a later error still points at the right line.
    assert "ARGS" not in body
    assert len(body.splitlines()) == len(src.splitlines())


def test_args_do_not_maul_lua_braces():
    """Substitution is textual and name-keyed — a Lua table is not a placeholder."""
    assert se.substitute("LUA f({a=1}, {})", {"n": 7}) == "LUA f({a=1}, {})"
    # An unknown placeholder stays visible instead of silently becoming empty.
    assert se.substitute("TAP x{miss}", {"n": 7}) == "TAP x{miss}"
    # Lists join with commas (so `{ {squads} }` is a Lua table), bools are Lua's.
    assert se.render_value([1, 2, 3]) == "1, 2, 3"
    assert se.render_value(True) == "true" and se.render_value(False) == "false"


def test_args_reach_conditions_as_variables():
    """A passed argument is also a script variable, so IF/WHILE can test it."""
    ev = FakeEval()
    log: list[str] = []
    ctx = se.new_context(on_event=log.append, variables={"limit": 2})
    ctx.evaluator = ev
    se.run_text("IF limit > 1\n    LUA fired()\n", ctx=ctx)
    assert any("fired()" in c for c in ev.chunks), ev.chunks


def test_join_rally_recipe_spends_one_squad_per_rally():
    """actions/join_rally.md: `squads` picks which squads go, one rally each.

    The two things worth pinning: the argument really reaches the parked queue (so
    `squads=[2,3]` cannot silently send squad 1), and the press is `xall` off a live
    count — a fixed count would either leave a rally unjoined or send a squad twice.
    """
    import game_buttons as gb

    path = se.resolve_action("join_rally")
    assert path is not None, "actions/join_rally.md is missing"
    src = path.read_text(encoding="utf-8")

    body, merged = se.prepare_source(src, {})
    assert merged["squads"] == [1, 2, 3], "the recipe must default to all three squads"
    stmts = se.parse_text(body)
    # The recipe now leads with `CALL rally_monitor` — it logs who is in the rallies
    # (the members and squads) before spending anything (#1130) — then parks the
    # squads and presses.
    assert [type(s).__name__ for s in stmts] == ["CallStmt", "LuaStmt", "TapStmt"], stmts
    assert stmts[0].action_name == "rally_monitor"
    assert "{ 1, 2, 3 }" in stmts[1].chunk, stmts[1].chunk
    assert stmts[2].name == "join_rally"
    assert stmts[2].count is None, "the press must be TAP … xall, not a fixed count"

    # The parked squads live on the LuaStmt (now the second statement, after CALL).
    def _lua_chunk(squads):
        for s in se.parse_text(se.prepare_source(src, {"squads": squads})[0]):
            if type(s).__name__ == "LuaStmt":
                return s.chunk
        raise AssertionError("no LuaStmt in join_rally")

    # One squad, and only that one is parked.
    only_first = _lua_chunk([1])
    assert "{ 1 }" in only_first, only_first
    # Two squads -> both parked, in the order asked for.
    two = _lua_chunk([2, 3])
    assert "{ 2, 3 }" in two, two
    # Every run starts by forgetting the previous one's joins, or a second run
    # would refuse every rally it joined the first time.
    assert "__lw_rally_joined" in two

    button = gb.get("join_rally")
    assert button is not None and button.count_lua, "xall needs a count expression"
    # The count is min(squads left, rallies not already joined) -> a quiet map is a
    # clean no-op rather than a press that goes nowhere.
    ev = FakeEval(rluas=[2, 1, 0])
    _run("TAP join_rally xall", ev)
    presses = [c for c in ev.chunks if "SendCreateMarchMessage" in c]
    assert len(presses) == 2, presses
    assert all("__lw_rally_joined" in c for c in presses), "each press must claim its rally"


def test_visitor_presses_key_on_the_kind_not_the_arrival_number():
    """Gift / recruit visitors are told apart by `eventType`, never by `visitorId`.

    `visitorId` reads like a kind and is not one — it counts arrivals, so a queue can
    hold 3, 4, 5, 6 with every one of them the same kind (that is task #1122: the gift
    press matched nothing, and the recruit press fired at whoever was the third visitor
    of the session). Both primitives must therefore name `eventType` and the enum they
    mean, and must not mention `visitorId` at all. The readiness half matters as much:
    a queue entry exists before the visitor walks up, and pressing one of those spends
    a round trip on somebody who is not there yet.
    """
    import lua_actions as la

    for name, expr in (
        ("gift count", la.visitor_gift_pending()),
        ("gift press", la.visitor_gift_collect()),
        ("recruit count", la.visitor_recruit_pending()),
        ("recruit press", la.visitor_recruit_survivor()),
    ):
        assert "visitorId" not in expr, f"{name} still reads the arrival counter: {expr}"
        assert "d.eventType ==" in expr, f"{name} does not test the kind: {expr}"
        assert "m.isArrival" in expr and "m.isFinish" in expr, \
            f"{name} presses visitors that have not walked up: {expr}"

    assert "VisitorType.GIFT" in la.visitor_gift_collect()
    assert "VisitorType.RECRUITMENT" in la.visitor_recruit_survivor()
    # The two kinds must not be confusable: a gift press may not mention RECRUITMENT
    # and vice versa, which is what a copy-paste of one into the other would look like.
    assert "RECRUITMENT" not in la.visitor_gift_collect()
    assert "GIFT" not in la.visitor_recruit_survivor()

    # Both presses send visitor.operate for the front matching visitor and nothing else.
    for press in (la.visitor_gift_collect(), la.visitor_recruit_survivor()):
        assert press.count("SFSNetwork.SendMessage") == 1, press
        assert "MsgDefines.VisitorOperateMessage, d.uid, 1" in press, press

    # The buttons' xall count is the same gate as the press, or the loop would either
    # stop early or keep pressing at a visitor the press refuses.
    import game_buttons as gb

    assert gb.get("collect_visitor_gifts").count_lua == la.visitor_gift_pending()
    assert gb.get("recruit_survivor").count_lua == la.visitor_recruit_pending()


def test_visitor_presses_search_every_queue():
    """The manager keeps two visitor queues and a kind is not tied to either of them.

    Reading one queue is reading half the visitors: live, gift visitors were queued in
    queue 1 while the waiting survivor was in queue 2, which is why `recruit_survivors`
    saw nobody and did nothing even with the kind test already right (#1122). So the
    queue index must never be a constant in one of these expressions — both are walked,
    and each fetch is its own pcall so a queue the client does not keep costs a queue
    rather than the whole reading.
    """
    import lua_actions as la

    for name, expr in (
        ("gift count", la.visitor_gift_pending()),
        ("gift press", la.visitor_gift_collect()),
        ("recruit count", la.visitor_recruit_pending()),
        ("recruit press", la.visitor_recruit_survivor()),
    ):
        assert "GetQueueAllVisitorData(1)" not in expr, \
            f"{name} still pins the queue index: {expr}"
        assert "for __q = 1, 2 do" in expr, f"{name} does not walk every queue: {expr}"
        assert "pcall(__M.GetQueueAllVisitorData" in expr, \
            f"{name} lets one missing queue take the whole reading down: {expr}"

    # One press, whichever queue the visitor turns up in — the send returns out of both
    # loops, so a second candidate in the other queue is not pressed in the same call.
    for press in (la.visitor_gift_collect(), la.visitor_recruit_survivor()):
        assert press.count("SFSNetwork.SendMessage") == 1, press
        assert "d.uid, 1) return end" in press, f"the send must stop the scan: {press}"


# --- the ministry errand (#1176) --------------------------------------------

def _run_ministry(rluas) -> tuple[bool, FakeEval, list[str]]:
    """Run actions/apply_ministry_interior.md against scripted READ_LUA answers."""
    ev = FakeEval(rluas=list(rluas))
    log: list[str] = []
    ctx = se.Context(hwnd=0, on_event=log.append, evaluator=ev)
    return se.run_action("apply_ministry_interior", hwnd=0, ctx=ctx), ev, log


def _applied(ev: FakeEval) -> list[str]:
    """The chunks that actually put an application on the wire."""
    return [c for c in ev.chunks if "SendKingdomPositionApply" in c]


def test_ministry_errand_only_succeeds_when_the_post_was_granted():
    """#1176: the timer's clock may only restart on an application that took.

    The scheduler moves `last_run` when the scenario returns True and leaves it alone
    when it returns False, so "reset on success only" is the recipe's job: every ending
    that did not seat us at the post has to be a FAILURE. The reading that decides it is
    the post held after the press — the server grants an accepted application straight
    away, so a round trip later it either is 10007 or the request did not take.
    """
    # The reads, in order: the post held, the apply cooldown, the post's own gate.
    # Granted: nothing held, cooldown out, gate open, 10007 on the first poll.
    ok, ev, _log = _run_ministry([0, 0, 1, 10007])
    assert ok is True, "an application that seated us must count as a run"
    assert len(_applied(ev)) == 1, ev.chunks

    # Granted a beat late: the poll waits for the answer instead of calling it a failure.
    ok, ev, _log = _run_ministry([0, 0, 1, 0, 0, 10007])
    assert ok is True, "a slow reply was written off as a refusal"

    # Sent and refused: the press went out, the post never changed hands.
    ok, ev, _log = _run_ministry([0, 0, 1, 0, 0, 0, 0])
    assert ok is False, "a refused application must not restart the clock"
    assert len(_applied(ev)) == 1, ev.chunks

    # Already ours: nothing to ask for — a clean success, and no request sent.
    ok, ev, _log = _run_ministry([10007])
    assert ok is True and not _applied(ev), ev.chunks


def test_ministry_errand_sends_nothing_while_another_post_is_held():
    """«has position»: the server refuses a second application, and the client won't say so.

    `CheckCanApply` answers **true** with a post already in hand — live, holding 10005 it
    said yes and the server came back `errorCode E000000, errorMsg "has position"`. Every
    such request is a wasted round trip and a toast in the player's face (the same trap as
    the resource-collect readiness gate), so the recipe reads the held post FIRST and
    fails without pressing.
    """
    ok, ev, _log = _run_ministry([10005])
    assert ok is False, "holding another post is a failed errand, not a quiet success"
    assert not _applied(ev), "an application was sent while another post was held"

    # The gate is state, and it is read FIRST: nothing else is even consulted, so a
    # `true` from the client's pre-flight can never let the request through.
    assert [c for c in ev.chunks if "GetOwnPositionId" in c], ev.chunks
    assert not [c for c in ev.chunks if "CheckCanApply" in c], \
        "the pre-flight was consulted before the held-post gate: %r" % (ev.chunks,)


def test_ministry_errand_waits_out_the_apply_cooldown_without_sending():
    """«in cd»: the server refuses an application inside the half-hour apply cooldown.

    The client's CheckCanApply says `true` right through it — read back, it only asks
    whether the id is in the list of applicable posts — so the cooldown has to be read
    on its own, and read BEFORE the press. It was live: 27 minutes left on 10007 and the
    request going out anyway earned `errorCode E000000, errorMsg "in cd"` and a toast.
    """
    ok, ev, _log = _run_ministry([0, 1_620_108])
    assert ok is False, "a run that could not even ask must not restart the clock"
    assert not _applied(ev), "an application was sent inside the apply cooldown"
    assert [c for c in ev.chunks if "GetOwnApplyCD" in c], ev.chunks


def test_ministry_errand_respects_the_posts_own_gate():
    """A post that cannot be applied for at all ends the errand before the press."""
    ok, ev, _log = _run_ministry([0, 0, 0])
    assert ok is False and not _applied(ev), ev.chunks


def test_the_ministry_gate_covers_what_check_can_apply_does_not():
    """Every rejection seen live has to be closed off before the request leaves.

    `CheckCanApply` is not a permission test — it walks `GetCanApplyGovernmentList()`
    and answers whether the id is in it — so on its own it lets three different doomed
    requests onto the wire, each one a toast in the player's face: «has position»,
    «in cd», and «not conqueror» for the commander posts.
    """
    import lua_actions as la

    gate = la.ministry_can_apply(10007)
    assert "CheckCanApply('10007')" in gate, gate
    assert "GetOwnApplyCD('10007')" in gate, "the apply cooldown is not gated: %s" % gate
    assert "GetOwnPositionId" in gate, "a post already held is not gated: %s" % gate
    assert "IsConqueror" in gate, "the commander posts are not gated: %s" % gate
    # Ids are strings in the apply manager, and the cooldown is the loudest case: asked
    # with a number it answers a flat 0 — "go ahead" — for a post still on cooldown.
    assert "GetOwnApplyCD(10007)" not in gate, gate
    # The press and its `xall` count share the one gate, or the loop would report a
    # press the chunk then declines to make.
    import game_buttons as gb

    assert gb.get("apply_minister_interior").count_lua == gate
    assert "GetOwnApplyCD('10007')" in gb.get("apply_minister_interior").lua


def test_ministry_own_position_reading_is_numeric_and_shared():
    """The recipe and the library must read the held post the same way."""
    import lua_actions as la

    expr = la.ministry_own_position()
    assert "GetOwnPositionId" in expr and "self_positionId" in expr
    assert "tonumber" in expr, "IF post == 10007 needs a number, not '10007'"
    path = se.resolve_action("apply_ministry_interior")
    assert path is not None, "actions/apply_ministry_interior.md is missing"
    source = path.read_text(encoding="utf-8")
    assert source.count(expr) == 2, "the recipe reads the post before AND after the press"
    assert la.ministry_can_apply(10007) in source, \
        "the pre-flight expression drifted from lua_actions"
    assert la.ministry_apply_cooldown_ms(10007) in source, \
        "the cooldown expression drifted from lua_actions"


# --- restarting the client (QUIT_GAME / ATTACH_GAME) ------------------------

class FakeClient:
    """A stand-in for tools/lib/game_client.py: one client, closable, restartable.

    `pid` is what is running; `close()` ends it, and `restart()` puts a NEW pid in its
    place — which is the whole point of the pair of primitives, since the link into
    the game VM is bound to a process id and the new one is not the old one.
    """

    def __init__(self, pid=4242, attached=None) -> None:
        self.pid = pid
        self.attached = pid if attached is None else attached
        #: every close, as ``{"pid", "user"}`` — the session has to reach the closer
        #: too, or another account's client refuses the kill and is waited for anyway.
        self.closed: list[dict] = []
        self.close_ok = True
        self.asked_for: list = []
        self.reloads = 0
        # …and the other end of its life: what START_GAME was asked for, what the
        # launch is to raise (a missing launcher, a session nobody is logged on to),
        # and the pid a successful launch into another session reports.
        self.started: list[dict] = []
        self.start_error: "Exception | None" = None
        self.next_pid = 9999

    # the module surface the interpreter uses
    def target_pid(self, port=None, game_exe=None, user=None, log=None):
        self.asked_for.append(user)
        return self.attached or self.pid

    def start(self, launcher=None, user=None, timeout=None, game_exe=None, log=None):
        self.started.append({"launcher": launcher, "user": user, "timeout": timeout})
        if self.start_error is not None:
            raise self.start_error
        self.pid = self.next_pid
        # A launch on this desktop is fire-and-forget and has no client pid to give;
        # one into another session waits for the client and knows it.
        return self.pid if user else None

    def running_pid(self, game_exe=None):
        return self.pid

    def attached_pid(self, port=None):
        return self.attached

    def close(self, pid, timeout=None, user=None, log=None):
        self.closed.append({"pid": pid, "user": user})
        if pid == self.pid:
            self.pid = None
        self.attached = None
        return self.close_ok

    # what the game does around it
    def restart(self, pid=5151):
        self.pid = pid

    def reload(self):
        self.reloads += 1
        self.attached = self.pid
        return {"ok": True, "warm": bool(self.pid)}


class _FakeLuaClient:
    """Only the two things ATTACH_GAME asks of lua_client, wired to a FakeClient."""

    PORT = 47654

    def __init__(self, client, daemon_up=True) -> None:
        self._client, self._up = client, daemon_up

    def is_running(self, host=None, port=None, timeout=1.0):
        return self._up

    def DaemonClient(self, host=None, port=None, timeout=90.0, token=None):  # noqa: N802
        return self._client


class _fakes:
    """Install fake `game_client` / `lua_client` modules for the length of a test."""

    def __init__(self, client, daemon_up=True) -> None:
        self._client = client
        self._lua = _FakeLuaClient(client, daemon_up)

    def __enter__(self):
        self._saved = {name: sys.modules.get(name)
                       for name in ("game_client", "lua_client")}
        sys.modules["game_client"] = self._client
        sys.modules["lua_client"] = self._lua
        return self._client

    def __exit__(self, *exc):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        return False


def test_parse_quit_and_attach():
    (q,) = se.parse_text("QUIT_GAME")
    assert isinstance(q, se.QuitGameStmt)
    (a,) = se.parse_text("ATTACH_GAME")
    assert isinstance(a, se.AttachGameStmt) and a.timeout == se.ATTACH_TIMEOUT_SEC
    (a2,) = se.parse_text("ATTACH_GAME WITHIN 30s")
    assert a2.timeout == 30.0, a2.timeout


def test_quit_closes_the_pid_the_daemon_drives_and_drops_the_link():
    """Not "the LastWar.exe": the process THIS profile's daemon is attached to.

    Two accounts run two clients, one per Windows session — closing by image name
    would end the other one as well. And the run's cached evaluator has to go with
    it, or everything after the restart drives a dead process id.
    """
    client = FakeClient(pid=4242)
    ev = FakeEval()
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=ev)
    with _fakes(client):
        se.Interpreter(ctx)._run_block(se.parse_text("QUIT_GAME"))
    assert client.closed == [{"pid": 4242, "user": None}], client.closed
    assert ctx.evaluator is None, "the dead process's evaluator was kept"


def test_quit_on_a_client_that_is_already_gone_is_not_a_failure():
    client = FakeClient(pid=None, attached=None)
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=FakeEval())
    with _fakes(client):
        assert se.run_text("QUIT_GAME", ctx=ctx) is True
    assert client.closed == [], "nothing was running, so nothing may be closed"


def test_attach_re_points_the_daemon_at_the_new_process():
    """The pid changes across a restart; the warm daemon must follow it."""
    client = FakeClient(pid=4242)
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=FakeEval())
    with _fakes(client):
        se.Interpreter(ctx)._run_block(se.parse_text("QUIT_GAME"))
        client.restart(pid=5151)             # the launcher brought a NEW process up
        se.Interpreter(ctx)._run_block(se.parse_text("ATTACH_GAME WITHIN 5s"))
    assert client.reloads == 1, client.reloads
    assert client.attached == 5151, client.attached
    assert ctx.evaluator is None, "the next primitive must build its own link"


def test_attach_fails_in_words_when_the_client_never_came_back():
    """A restart that left nothing running is a failed errand — and it says why.

    A deliberate FAIL, not a blow-up: the reason has to reach the timer's row (the
    panel shows `ctx.fail_reason` verbatim), and a runtime error is deliberately not
    dressed as one (tests/test_panel_action_outcome.py). It is also the difference
    between "retry this later" and "this script is broken".
    """
    client = FakeClient(pid=None, attached=None)
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=None)
    with _fakes(client):
        assert se.run_text("ATTACH_GAME WITHIN 1s", ctx=ctx) is False
    assert ctx.failed, "a missing client must fail the recipe"
    assert "no client is running" in ctx.fail_reason, ctx.fail_reason


def test_attach_believes_the_daemon_over_a_local_pid_lookup():
    """A profile whose client lives in ANOTHER Windows session is still driven from
    this one, over a port. Nothing here can see that client in a process list, so a
    restart that checked the daemon's pid against a locally-found one would fail a
    handover that in fact worked. The daemon knows which client it drives; that is
    the answer."""
    client = FakeClient(pid=None, attached=None)   # nothing visible in THIS session
    client.reload = lambda: (setattr(client, "attached", 31337),
                             {"ok": True, "warm": True})[1]
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=FakeEval())
    with _fakes(client):
        se.Interpreter(ctx)._run_block(se.parse_text("ATTACH_GAME WITHIN 5s"))
    assert client.attached == 31337, client.attached


def test_a_restart_never_reaches_another_windows_session():
    """The bug this cost a live run to find: with the client of this session killed,
    the ordinary lookup answered with the SECOND account's client, in another
    session — and the next step of a restart is not a read but a kill."""
    import game_client

    class _Proc:
        def __init__(self, pid, name):
            self.pid, self.info = pid, {"name": name}

    class _FakePsutil:
        @staticmethod
        def process_iter(_fields=None):
            return [_Proc(111, "LastWar.exe"),      # ours, session 1
                    _Proc(222, "LastWar.exe"),      # the other account, session 3
                    _Proc(333, "chrome.exe")]

    class _FakeProbe:
        SESSIONS = {111: 1, 222: 3}

        @staticmethod
        def _session_of(pid):
            if pid in (222,):
                raise OSError("access denied")      # what a foreign session really gives
            return _FakeProbe.SESSIONS.get(pid, 1)  # this process, and ours

    saved = {n: sys.modules.get(n) for n in ("psutil", "il2cpp_probe")}
    sys.modules["psutil"], sys.modules["il2cpp_probe"] = _FakePsutil, _FakeProbe
    try:
        assert game_client.session_pids() == [111], game_client.session_pids()
        assert game_client.running_pid() == 111
        # …and with ours gone, the honest answer is "none", never the neighbour's.
        _FakePsutil.process_iter = staticmethod(lambda _f=None: [_Proc(222, "LastWar.exe")])
        assert game_client.running_pid() is None, "a foreign session's client was offered"
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def test_attach_without_a_daemon_waits_for_the_client_and_stops_there():
    """With nothing warm to re-point, the next primitive resolves its own link."""
    client = FakeClient(pid=7777)
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=FakeEval())
    with _fakes(client, daemon_up=False):
        se.Interpreter(ctx)._run_block(se.parse_text("ATTACH_GAME WITHIN 5s"))
    assert client.reloads == 0, "there was no daemon to reload"


def test_restart_recipe_closes_relaunches_and_re_attaches():
    """actions/restart_game.md is the whole ability, in that order."""
    path = se.resolve_action("restart_game")
    assert path is not None, "actions/restart_game.md is missing"
    body, _merged = se.prepare_source(path.read_text(encoding="utf-8"), {})
    kinds = [type(s).__name__ for s in se.parse_text(body)]
    assert kinds == ["QuitGameStmt", "WaitStmt", "CallStmt", "AttachGameStmt",
                     "IfStmt", "LogStmt"], kinds
    called = [s.action_name for s in se.parse_text(body)
              if type(s).__name__ == "CallStmt"]
    assert called == ["launch_game"], "the restart must start the game the one way"
    assert se.resolve_action("launch_game") is not None
    # Done means BOTH halves: the link answers (ATTACH_GAME) and the base is in play,
    # read AFTER the re-attach — the client restarts itself once into a new process,
    # so a scene read taken any earlier is a reading of the wrong one.
    guard = se.parse_text(body)[4]
    assert guard.condition == "scene != city", guard.condition
    assert type(guard.then_block[0]).__name__ == "FailStmt", guard.then_block


# --- starting the client (START_GAME) ---------------------------------------

def test_parse_start_game():
    (s,) = se.parse_text("START_GAME")
    assert isinstance(s, se.StartGameStmt), s
    assert s.path is None and s.timeout == se.START_TIMEOUT_SEC, s
    (s2,) = se.parse_text('START_GAME "C:\\Games\\LastWarLauncher.exe"')
    assert s2.path == "C:\\Games\\LastWarLauncher.exe", s2
    (s3,) = se.parse_text('START_GAME "C:\\a.exe" WITHIN 45s')
    assert (s3.path, s3.timeout) == ("C:\\a.exe", 45.0), s3
    (s4,) = se.parse_text("START_GAME WITHIN 45s")
    assert s4.path is None and s4.timeout == 45.0, s4


def test_start_game_on_this_desktop_names_no_session():
    """The single-account case, which must keep behaving exactly like LAUNCH did."""
    client = FakeClient(pid=None, attached=None)
    ctx = se.Context(hwnd=0, on_event=lambda _m: None)
    with _fakes(client):
        assert se.run_text('START_GAME "C:\\a.exe"', ctx=ctx) is True
    assert client.started == [{"launcher": "C:\\a.exe", "user": None,
                               "timeout": se.START_TIMEOUT_SEC}], client.started


def test_start_game_goes_to_the_windows_session_the_profile_names():
    """The whole point (#1218): a profile farming a second account starts ITS client.

    The port cannot answer this — it reaches a client through the daemon attached to
    it, and there is nothing attached to at launch time — so the session travels on the
    context beside it, and a launcher spawned here would have landed on this desktop.
    """
    client = FakeClient(pid=None, attached=None)
    ctx = se.Context(hwnd=0, on_event=lambda _m: None,
                     game_port=47655, game_user="casper")
    with _fakes(client):
        assert se.run_text("START_GAME WITHIN 60s", ctx=ctx) is True
    assert client.started == [{"launcher": None, "user": "casper",
                               "timeout": 60.0}], client.started


def test_start_game_fails_in_words_when_nobody_is_logged_on():
    """A session that is not up is a thing to try again later, not a broken script.

    So it is a deliberate FAIL, with the reason the launcher gave: the panel shows
    `ctx.fail_reason` verbatim and a timer retries rather than counting the errand done.
    """
    client = FakeClient(pid=None, attached=None)
    client.start_error = LookupError("nobody is logged on as casper")
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, game_user="casper")
    with _fakes(client):
        assert se.run_text("START_GAME", ctx=ctx) is False
    assert ctx.failed and "casper" in ctx.fail_reason, ctx.fail_reason


def test_start_game_fails_in_words_when_the_client_never_appeared():
    client = FakeClient(pid=None, attached=None)
    client.start_error = TimeoutError("no client in casper's session after 300s")
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, game_user="casper")
    with _fakes(client):
        assert se.run_text("START_GAME", ctx=ctx) is False
    assert ctx.failed and "no client" in ctx.fail_reason, ctx.fail_reason


def test_a_launcher_that_is_not_there_blows_up_rather_than_failing():
    """A path that names nothing is a configuration mistake, and LAUNCH always said so.

    Kept apart from the two above on purpose: retrying it every hour would never help.
    """
    client = FakeClient(pid=None, attached=None)
    client.start_error = FileNotFoundError("C:\\nope\\LastWarLauncher.exe")
    ctx = se.Context(hwnd=0, on_event=lambda _m: None)
    with _fakes(client):
        assert se.run_text('START_GAME "C:\\nope\\LastWarLauncher.exe"', ctx=ctx) is False
    assert not ctx.failed, "a missing launcher is a blow-up, not a FAIL to be retried"


def test_launch_recipe_starts_the_game_where_the_profile_lives():
    """actions/launch_game.md is the one way to start the client, in that order."""
    path = se.resolve_action("launch_game")
    assert path is not None, "actions/launch_game.md is missing"
    body, _merged = se.prepare_source(path.read_text(encoding="utf-8"), {})
    kinds = [type(s).__name__ for s in se.parse_text(body)]
    assert kinds == ["StartGameStmt", "WaitStmt", "LogStmt"], kinds
    assert "LAUNCH " not in body, \
        "LAUNCH spawns on THIS desktop — a profile in another session gets a third client"


def test_quit_carries_the_session_to_the_closer():
    """Ending a client needs the session as much as starting one does.

    Another account's process refuses `TerminateProcess` outright for an unelevated
    panel, so a close that did not know whose session it was in would kill nothing and
    then sit out its whole timeout waiting for a process that never went away.
    """
    client = FakeClient(pid=4242)
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, evaluator=FakeEval(),
                     game_port=47655, game_user="casper")
    with _fakes(client):
        se.Interpreter(ctx)._run_block(se.parse_text("QUIT_GAME"))
    assert client.closed == [{"pid": 4242, "user": "casper"}], client.closed
    # …and the LOOKUP is narrowed by it too, which matters more: without the session
    # both routes fall back to the client of this desktop — the neighbour's game.
    assert client.asked_for == ["casper"], client.asked_for


def test_a_client_that_would_not_close_fails_the_recipe_in_words():
    client = FakeClient(pid=4242)
    client.close_ok = False
    ctx = se.Context(hwnd=0, on_event=lambda _m: None, game_user="casper")
    with _fakes(client):
        assert se.run_text("QUIT_GAME", ctx=ctx) is False
    assert ctx.failed and "4242" in ctx.fail_reason, ctx.fail_reason


def test_the_elevated_kill_is_only_for_a_client_in_another_session():
    """The fallback is gated on a session being NAMED, not on any refusal.

    A profile on this desktop that cannot kill its own client has something else wrong,
    and a surprise elevation prompt is not how a person should find that out.
    """
    import game_client

    calls: list = []
    saved = game_client._close_here, game_client._close_elevated, game_client.alive
    game_client.alive = lambda pid: True
    game_client._close_here = lambda pid, timeout, say: calls.append("here") or False
    game_client._close_elevated = lambda pid, timeout, say: calls.append("elevated") or True
    try:
        assert game_client.close(11, user=None) is False
        assert calls == ["here"], calls
        calls.clear()
        assert game_client.close(11, user="casper") is True
        assert calls == ["here", "elevated"], calls
        # …and a client that is already gone is never killed twice.
        calls.clear()
        game_client.alive = lambda pid: False
        assert game_client.close(11, user="casper") is True
        assert calls == [], calls
    finally:
        game_client._close_here, game_client._close_elevated, game_client.alive = saved


def test_a_daemon_pointing_at_the_wrong_session_is_not_believed():
    """Found live (#1218): the profile's daemon was running on THIS desktop.

    It bound the right port and hijacked the console session's client, so it answered
    "attached to 153576" — the game in front of the person. A restart that believed it
    would have force-closed that game instead of the second account's. So the daemon's
    answer is checked against the session the profile actually plays in.
    """
    import game_client

    saved = (game_client.attached_pid, game_client.session_of,
             game_client.session_pids_of)
    said: list = []
    game_client.session_of = lambda user: 4
    game_client.session_pids_of = lambda session, game_exe=None: [777]
    try:
        game_client.attached_pid = lambda port=None: 777          # the right client
        assert game_client.target_pid(port=47655, user="casper", log=said.append) == 777
        assert said == [], said
        game_client.attached_pid = lambda port=None: 153576       # this desktop's
        assert game_client.target_pid(port=47655, user="casper", log=said.append) == 777
        assert said and "NOT in casper's session" in said[0], said
        # …and with nothing of this profile's running, the honest answer is none —
        # never the client that happens to be in front of the person.
        game_client.session_pids_of = lambda session, game_exe=None: []
        assert game_client.target_pid(port=47655, user="casper") is None
    finally:
        (game_client.attached_pid, game_client.session_of,
         game_client.session_pids_of) = saved


def test_a_per_user_launcher_path_does_not_travel_to_another_session():
    """`%LOCALAPPDATA%` names a different folder for every account.

    Expanding it here and handing the result to the other session's token would start
    the PANEL user's installation from that account — so a path with anything left to
    expand stays home, and the session resolves its own install instead. An absolute
    path with nothing to expand is the same file for everybody and travels.
    """
    import os

    import game_client

    assert game_client._shared_path(
        r"%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe") is None
    assert game_client._shared_path(None) is None
    assert game_client._shared_path("LastWarLauncher.exe") is None, "not absolute"
    # Absolute means absolute HERE, so the test says it in the running platform's
    # words; the answer this asserts is the same one either way.
    shared = (r"D:\Games\LastWarLauncher.exe" if os.name == "nt"
              else "/opt/lastwar/LastWarLauncher.exe")
    assert game_client._shared_path(shared) == shared


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
