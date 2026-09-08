r"""`READ_LUA <expr> INTO a, b, c` — the merged reads, checked without a game (#2404).

Run it anywhere::

    python3 tests/test_recipe_reads.py

Reading several answers in one call is what took a chunk's cost off the catalogue, and
thirteen recipes were converted to it — eight of them mechanically. A merge has two ways
of being wrong that no reviewer sees by eye:

* **it does not compile.** The expression is pasted into a `pcall(function() return … end)`
  and only the live game would ever say so — as a `READ_LUA error:` line in a log nobody
  is reading at the time.
* **it returns the wrong NUMBER of values.** Every name after `INTO` is filled in order,
  so an expression that returns two values into three names leaves the third `None` — and
  a recipe that gates on it does nothing, silently, for ever.

The second is only checkable where the expression is a plain list of values; where it is
one call handing back several, the count is the game's business and the test says so
rather than guessing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIONS = _REPO_ROOT / "src" / "lastwar_bot" / "actions"

READ = re.compile(
    r"^\s*READ_LUA\s+(.+?)\s+INTO\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)+)\s*$",
    re.IGNORECASE,
)
#: `{name}` is filled from the caller's variables before the chunk is built, so for a
#: syntax check it stands for any value.
PLACEHOLDER = re.compile(r"\{[^{}\s]+\}")


def _lines() -> list:
    """Every multi-value read in the catalogue: (path, line number, expr, names)."""
    out = []
    for f in sorted(ACTIONS.rglob("*.md")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = READ.match(line)
            if m:
                names = [n.strip() for n in m.group(2).split(",")]
                out.append((f, i, m.group(1), names))
    return out


def _top_level_commas(expr: str) -> "int | None":
    """How many values a plain value-list returns, or None if it is not one.

    None means «one expression that may hand back several answers» — a call, an `unpack`,
    anything the game decides. Counting those here would be guessing.
    """
    depth = 0
    parts = 1
    i = 0
    quote = ""
    while i < len(expr):
        c = expr[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts += 1
        i += 1
    return parts if parts > 1 else None


def test_every_merged_read_compiles():
    """The chunk the engine builds around the expression is valid Lua."""
    try:
        import lupa
    except ImportError:                                    # pragma: no cover
        print("  (no lupa here — the compile half is skipped)")
        return
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    bad = []
    for f, i, expr, _names in _lines():
        chunk = ("local t = {pcall(function() return "
                 + PLACEHOLDER.sub("0", expr) + " end)} "
                 "local out = {} for i = 2, #t do out[#out+1] = tostring(t[i]) end")
        try:
            rt.compile(chunk)
        except Exception as exc:                           # noqa: BLE001
            bad.append(f"{f.relative_to(_REPO_ROOT)}:{i}: {exc}")
    assert not bad, "these merged reads are not valid Lua:\n" + "\n".join(bad)


def test_a_value_list_has_a_value_for_every_name():
    """`a, b` into three names would leave the third None on every single run."""
    bad = []
    for f, i, expr, names in _lines():
        got = _top_level_commas(expr)
        if got is not None and got != len(names):
            bad.append(f"{f.relative_to(_REPO_ROOT)}:{i}: {got} value(s) "
                       f"into {len(names)} name(s)")
    assert not bad, "these merged reads fill the wrong number of names:\n" + "\n".join(bad)


def test_no_bare_nil_in_the_middle_of_a_list():
    """`{pcall(…)}` stops counting at a nil, so the names after it would shift up."""
    bad = []
    for f, i, expr, names in _lines():
        if _top_level_commas(expr) is None:
            continue
        for part in re.split(r",(?![^(\[{]*[)\]}])", expr):
            if part.strip() == "nil":
                bad.append(f"{f.relative_to(_REPO_ROOT)}:{i}: a bare nil in the list "
                           f"({len(names)} names)")
                break
    assert not bad, "a nil in the middle shifts every name after it:\n" + "\n".join(bad)


#: A recipe's own inputs — `ARGS x = …` — and the names it only learns while it RUNS.
_ARGS = re.compile(r"^\s*ARGS\s+([A-Za-z_]\w*)", re.MULTILINE)
_INTO = re.compile(r"\bINTO\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)", re.IGNORECASE)
_CHUNK = re.compile(r"^\s*(?:LUA|READ_LUA|GAME)\s", re.IGNORECASE)
_NAME_IN_BRACES = re.compile(r"\{([A-Za-z_]\w*)\}")


def _recipes() -> list:
    return sorted(ACTIONS.rglob("*.md"))


def test_no_runtime_variable_is_interpolated_into_lua():
    """`{name}` is filled when the FILE IS PARSED — never with what a run just read.

    So a value that arrives from `READ_LUA … INTO x` (or `RECALL`) cannot reach a Lua
    chunk as `{x}`: what the game receives is the six or so characters of the name, and
    what happens next depends only on where they landed. Measured live on 2026-09-08 in
    a running drone phase: `tonumber("{rally_cost}")` was nil, the phase's rally price
    stayed 0, every gate answered «the game prices a rally at no stamina» and the four
    hours raised nothing (#2649). Two more of the same shape were in the catalogue — a
    word count over the literal name, and `{liked}>0`, which is a table compared with a
    number.

    `PARK <var> INTO <a.lua.name>` is the primitive for this (docs/dsl.md), and an ARGS
    name is fine: those ARE known before the file is parsed.
    """
    bad = []
    for f in _recipes():
        body = "\n".join(l for l in f.read_text(encoding="utf-8").splitlines()
                          if not l.lstrip().startswith("#"))
        args = set(_ARGS.findall(body))
        runtime = set()
        for m in _INTO.finditer(body):
            runtime.update(n.strip() for n in m.group(1).split(","))
        runtime -= args
        if not runtime:
            continue
        for i, line in enumerate(body.splitlines(), 1):
            if not _CHUNK.match(line):
                continue
            for name in _NAME_IN_BRACES.findall(line):
                if name in runtime:
                    bad.append(f"{f.relative_to(_REPO_ROOT)}: {{{name}}} in a Lua chunk "
                               f"is the name itself, never the value the run read — "
                               f"PARK it instead")
    assert not bad, ("a placeholder cannot carry a value learnt mid-run:\n"
                     + "\n".join(bad))


def _run_standalone() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed "
          f"({len(_lines())} merged read(s) in the catalogue)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
