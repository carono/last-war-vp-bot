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
    assert [type(s).__name__ for s in stmts] == ["LuaStmt", "TapStmt"], stmts
    assert "{ 1, 2, 3 }" in stmts[0].chunk, stmts[0].chunk
    assert stmts[1].name == "join_rally"
    assert stmts[1].count is None, "the press must be TAP … xall, not a fixed count"

    # One squad, and only that one is parked.
    only_first = se.parse_text(se.prepare_source(src, {"squads": [1]})[0])[0].chunk
    assert "{ 1 }" in only_first, only_first
    # Two squads -> both parked, in the order asked for.
    two = se.parse_text(se.prepare_source(src, {"squads": [2, 3]})[0])[0].chunk
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
