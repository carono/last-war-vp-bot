r"""«Операция Призрак» robs in ONE step, and the queue travels as an argument (#1976).

The robbery used to be two steps: spawn `tools/ghost_recon_steal.py --queue-only` to park
the chosen squads in the game VM, then play `actions/steal_ghost_recon.md` to press them.
The spawn was there because `TAP` takes no arguments — true of `TAP`, and not true of the
recipe, which takes `ARGS`. What settled it is the measurement `CLAUDE.md` records: **the
parking child costs five seconds**, and the whole of what it did here was park a list the
panel had already chosen.

So this file pins the three things that make the one-step version correct, and that a
one-line «just call run_action» version would have got wrong:

  * the recipe DECLARES `queue` and PARKS what it is given, in the call it was going to
    make anyway — a recipe played over a queue nobody filled robs nothing and says so;
  * an EMPTY `queue` does not wipe a queue somebody else parked (the tool still exists at
    the command line, and «spend what is parked» is what it leaves behind);
  * the panel hands the queue over and spawns NOTHING, and a second press while one
    robbery is in flight is refused rather than parking a second set of squads on top of
    the one being pressed.

    C:\Python312\python.exe tests\test_ghost_steal_queue.py
    python3 tests/test_ghost_steal_queue.py          # lupa is enough; no game, no panel
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "tools", ROOT / "tools" / "lib", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lastwar_bot.script_engine import parse_text, prepare_source   # noqa: E402

try:
    import lupa                                     # noqa: E402
except ImportError:                                 # pragma: no cover - optional
    lupa = None

RECIPE = ROOT / "src" / "lastwar_bot" / "actions" / "steal_ghost_recon.md"
ORDER = ROOT / "panel" / "tabs" / "secret_tasks" / "ghost_order.py"
TAB = ROOT / "panel" / "tabs" / "secret_tasks" / "tab.py"

#: As much of the client's ghost-recon manager as the recipe touches: the queue it parks,
#: the spent counter the server moves, and the settings row the cap comes off.
_MANAGER = """
DataCenter = { ActGhostreconManager = {
  __lw_ghost_queue = {},
  stealTimes = 0,
  _cap = 5,
  GetNowSettingCfg = function(self) return {stealCount = self._cap} end,
  IsOpenDay = function(self) return true end,
} }
"""


def _source(queue=None) -> str:
    text = RECIPE.read_text(encoding="utf-8")
    body, _merged = prepare_source(text, {"queue": queue} if queue is not None else None)
    return body


def _statements(queue=None):
    return parse_text(_source(queue))


def _vm(parked: int = 0, spent: int = 0):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_MANAGER)
    manager = lua.eval("DataCenter.ActGhostreconManager")
    manager.stealTimes = spent
    lua.execute("local q = DataCenter.ActGhostreconManager.__lw_ghost_queue "
                "for i = 1, %d do q[i] = {uuid = i, server = 1} end" % parked)
    return lua, manager


def _park_chunk(queue=None) -> str:
    """The recipe's own first statement — never a copy of it written here."""
    first = _statements(queue)[0]
    assert type(first).__name__ == "LuaStmt", type(first).__name__
    return first.chunk if hasattr(first, "chunk") else first.code


def _code(path: Path) -> str:
    """A module's source with every docstring removed.

    The prose in this file's neighbours still tells the story of the child that used to
    run here, and it should — what must not come back is a CALL.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    cut = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        doc = node.body[0] if node.body else None
        if (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str)):
            cut.append((doc.lineno, doc.end_lineno))
    lines = text.split("\n")
    for start, end in cut:
        for i in range(start - 1, end):
            lines[i] = ""
    # …and the line comments with them, for the same reason.
    return "\n".join(ln.split("#", 1)[0] if "#" in ln else ln for ln in lines)


def _needs_lua(name: str) -> bool:
    if lupa is None:
        print(f"       (skipped {name}: no lupa here — pip install lupa)")
        return False
    return True


# -- the recipe --------------------------------------------------------------
def test_the_recipe_takes_a_queue_and_parks_it():
    """`ARGS queue` exists, and the first thing the recipe does is park it."""
    defaults, _body = __import__("lastwar_bot.script_engine", fromlist=["x"]) \
        .extract_defaults(RECIPE.read_text(encoding="utf-8"))
    assert "queue" in defaults, "the recipe cannot be named a target"
    assert defaults["queue"] in ("", None), defaults["queue"]
    assert "__lw_ghost_queue" in _park_chunk(), "nothing is parked"


def test_a_named_queue_replaces_what_was_parked():
    """The panel names its squads and the recipe spends exactly those."""
    if not _needs_lua("a named queue is parked"):
        return
    lua, manager = _vm(parked=3)
    lua.execute(_park_chunk("{uuid=7,server=534},{uuid=8,server=534}"))
    queue = manager.__lw_ghost_queue
    assert len(queue) == 2, len(queue)
    assert int(queue[1].uuid) == 7 and int(queue[1].server) == 534
    assert int(queue[2].uuid) == 8


def test_an_empty_queue_does_not_wipe_what_the_tool_parked():
    """«Spend what is parked» has to keep working — the command-line tool still parks."""
    if not _needs_lua("an empty queue keeps the parked one"):
        return
    lua, manager = _vm(parked=3)
    lua.execute(_park_chunk())               # no argument at all
    assert len(manager.__lw_ghost_queue) == 3, "an empty argument emptied the queue"


def test_nothing_queued_is_said_rather_than_pressed():
    """A recipe played over an empty queue must SAY so; a silent success is the failure
    mode the two-step version had when its child parked nothing."""
    program = _statements()
    guard = program[2]
    assert type(guard).__name__ == "IfStmt", type(guard).__name__
    said = " ".join(str(getattr(s, "message", "")) for s in guard.then_block)
    assert "queue" in said.lower(), said


def test_the_run_is_judged_by_the_server_and_not_by_a_sent_frame():
    """`stealTimes` only moves on the reply, so the baseline/after pair is the honest
    «it worked» — and it is what the standing order reads."""
    if not _needs_lua("the counter judges the run"):
        return
    lua, manager = _vm(parked=1, spent=2)
    lua.execute(_park_chunk("{uuid=1,server=1}"))
    assert int(manager.__lw_ghost_run) == 2, "no baseline was stamped"
    manager.stealTimes = 3                   # the reply landed
    taken = _statements()[5]
    assert type(taken).__name__ == "ReadLuaStmt", type(taken).__name__
    assert int(lua.eval(taken.expr if hasattr(taken, "expr") else taken.code)) == 1


def test_the_marks_the_panel_reads_are_the_ones_the_recipe_says():
    """Reword one and the standing order stops noticing its own successes — the two are
    pinned against each other rather than trusted to stay in step."""
    order = ORDER.read_text(encoding="utf-8")
    recipe = RECIPE.read_text(encoding="utf-8")
    for mark in ("ghost_taken", "ghost_steals_spent"):
        assert mark in recipe, f"the recipe stopped saying {mark}"
        assert mark in order, f"the panel stopped reading {mark}"


# -- the panel ---------------------------------------------------------------
def test_the_panel_spawns_nothing_to_rob():
    """The five seconds this task removed: no child, no `--queue-only`, no stdout to
    read a contract off."""
    order = _code(ORDER)          # docstrings stripped: the prose may still tell the story
    for gone in ("spawn_raw", "children", "queue-only", "QUEUED_MARK", "subprocess"):
        assert gone not in order, f"the parking child is back ({gone})"
    assert 'actions.play("steal_ghost_recon"' in order, "nothing plays the recipe"
    assert '"queue"' in order or "queue=" in order or "queue)" in order, \
        "the queue is not handed over"


def test_the_queue_string_is_lua_the_recipe_can_park():
    """What the panel builds is substituted into the recipe as-is, so it has to be a Lua
    table body — a shape mismatch would park nothing and rob nothing, silently."""
    if not _needs_lua("the panel's queue string parks"):
        return
    pairs = [(11, 534), (12, 971)]
    queue = ",".join("{uuid=%d,server=%d}" % pair for pair in pairs)
    lua, manager = _vm()
    lua.execute(_park_chunk(queue))
    parked = manager.__lw_ghost_queue
    assert [(int(parked[i + 1].uuid), int(parked[i + 1].server))
            for i in range(len(pairs))] == pairs


def test_the_phone_may_press_it_now():
    """The press travels because the ability is ONE recipe (`CLAUDE.md`). Before #1976 it
    was reading-only, and the reason was the spawn that has since gone.

    On «Секретки» → «Призрак: карта» since #2010: the screen it was on belongs to a DEV
    tab, so on a profile with that tab switched off the phone could not reach the press
    at all — nor the switch and the level rule beside it.
    """
    tab = TAB.read_text(encoding="utf-8")
    assert '"id": "ghost_rob"' in tab, "«Ограбить всех» is missing from the screen"
    assert 'action == "ghost_rob"' in tab, "the screen offers a press nobody answers"
    assert "order.run_once()" in tab, "the press does not go through the standing order"


def test_a_second_press_is_refused_while_one_is_in_flight():
    """Two presses must not park two sets of squads on top of each other. Checked against
    the real class, with the runtime stubbed out — no game, no Tk."""
    try:
        import panel.tabs.secret_tasks.ghost_order as ghost_mod
    except Exception as exc:              # noqa: BLE001 — no tkinter here, say which
        print(f"       (skipped the in-flight refusal: {type(exc).__name__}: {exc})")
        return

    class _Rt:
        def say(self, *a, **k):
            pass

        def put(self, *a, **k):
            pass

    order = ghost_mod.GhostOrder.__new__(ghost_mod.GhostOrder)
    order.rt, order.page, order._stop, order._proc, order._seen = \
        _Rt(), None, None, None, set()
    started = []
    order._look_and_rob = lambda: started.append(1)          # never really reads
    assert order.run_once() is True
    assert order.run_once() is False, "a second press was let through"


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
