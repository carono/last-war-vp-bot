r"""Neighbouring `READ_LUA` lines become ONE call into the game (#2660).

A round trip to the client's Lua VM costs about 0.15 s whatever it carries
(`docs/research/game-call-latency.md`), and the recipes are full of runs of single
reads: `refresh_secret_tasks` had 41 of them in a row, `send_trucks` 31. Across every
recipe in the tree the joining takes 923 reads down to 707 calls.

It is done in the PARSER rather than by hand in 124 files because it is safe without
looking at what the expressions say: `{name}` is substituted when a file is parsed
(`script_engine.substitute`), so a read can never depend on a read that ran a moment
earlier. Anything that is not a single-name read ends the run.

What the joining may NOT change is what lands in a variable. Each expression keeps its
own `pcall` and its own `tostring` inside the chunk, so a `nil` still arrives as the
string «nil», a value still arrives coerced, and an expression that raises still leaves
`None` — in ONE name, never in its neighbours'.

No game, no daemon: the evaluator is a stub, and the Lua chunk itself is run through
`lupa` where that is installed::

    python3 tests/test_read_coalescing.py
    C:\Python312\python.exe tests\test_read_coalescing.py
"""
from __future__ import annotations

TIER = "pure"

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lastwar_bot import script_engine as se                # noqa: E402


def _parse(text: str):
    body, _ = se.prepare_source(text, {})
    return se.parse_text(body)


def test_a_run_of_single_reads_becomes_one_statement() -> None:
    stmts = _parse(
        "READ_LUA 1 INTO a\n"
        "READ_LUA 2 INTO b\n"
        "READ_LUA 3 INTO c\n"
    )
    assert len(stmts) == 1, [type(s).__name__ for s in stmts]
    assert stmts[0].names == ("a", "b", "c"), stmts[0].names
    assert stmts[0].exprs == ("1", "2", "3"), stmts[0].exprs


def test_anything_between_two_reads_keeps_them_apart() -> None:
    stmts = _parse(
        "READ_LUA 1 INTO a\n"
        'LOG "hello"\n'
        "READ_LUA 2 INTO b\n"
    )
    reads = [s for s in stmts if isinstance(s, se.ReadLuaStmt)]
    assert len(reads) == 2, [type(s).__name__ for s in stmts]
    assert all(not r.exprs for r in reads), "they were joined across a LOG"


def test_a_multi_name_read_is_left_alone() -> None:
    stmts = _parse("READ_LUA 1, 2 INTO a, b\nREAD_LUA 3 INTO c\n")
    assert len(stmts) == 2, [type(s).__name__ for s in stmts]
    assert not stmts[0].exprs and stmts[0].names == ("a", "b")
    assert not stmts[1].exprs


def test_a_group_never_grows_past_the_cap() -> None:
    text = "".join("READ_LUA %d INTO v%d\n" % (i, i) for i in range(30))
    stmts = _parse(text)
    assert all(len(s.exprs or ("x",)) <= se.READ_COALESCE_MAX for s in stmts), \
        [len(s.exprs) for s in stmts]
    assert sum(len(s.exprs) or 1 for s in stmts) == 30


def test_every_recipe_in_the_tree_still_parses() -> None:
    root = _REPO / "src" / "lastwar_bot" / "actions"
    broken = []
    for path in sorted(root.rglob("*.md")):
        try:
            _parse(path.read_text(encoding="utf-8"))
        except Exception as exc:            # noqa: BLE001 — the test IS the report
            broken.append((path.name, exc))
    assert not broken, broken[:5]


class _Stub:
    """A VM that runs the chunk in `lupa`, or hands back a prepared line."""

    def __init__(self, line=None) -> None:
        self.line = line
        self.chunks: list = []

    def run(self, chunk, marker="ACT", settle=1.2, early=True):
        self.chunks.append(chunk)
        if self.line is not None:
            return [self.line]
        import lupa

        lua = lupa.LuaRuntime()
        lua.execute("CS = {UnityEngine = {Debug = {LogError = "
                    "function(s) OUT = s end}}}")
        lua.execute(chunk)
        return [lua.globals().OUT]


def _run(stmt, stub) -> dict:
    said: list = []
    interp = se.Interpreter(se.new_context(0, lambda m: said.append(str(m))))
    interp._evaluator = lambda: stub
    interp._do_read_lua(stmt)
    return dict(interp.ctx.vars), said


def _batch(*exprs):
    names = tuple("v%d" % i for i in range(len(exprs)))
    return se.ReadLuaStmt(text="", line_no=1, expr=exprs[0], var=names[0],
                          names=names, exprs=tuple(exprs))


def test_a_nil_arrives_as_nil_and_a_raise_lands_in_one_name_only() -> None:
    try:
        import lupa                                        # noqa: F401
    except ImportError:
        print("  (skipped: no lupa)")
        return
    values, _said = _run(_batch("1+1", "nil", "error('boom')", "'x'"), _Stub())
    # Byte for byte what four separate reads would have written: a number coerced, a
    # nil as the string tostring gives it, an error as None — and the value AFTER the
    # error still in its own name rather than shifted up by one.
    assert values == {"v0": 2, "v1": "nil", "v2": None, "v3": "x"}, values


def test_one_call_and_not_four() -> None:
    try:
        import lupa                                        # noqa: F401
    except ImportError:
        print("  (skipped: no lupa)")
        return
    stub = _Stub()
    _run(_batch("1", "2", "3", "4"), stub)
    assert len(stub.chunks) == 1, len(stub.chunks)


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
