r"""A LAZY IMPORT THAT WAS FORGOTTEN BREAKS ONE BRANCH, SILENTLY (#2711).

WHAT THIS FILE IS FOR. `panel/` reaches the toolkit under `tools/lib` — `lua_actions`,
`coords`, `game_clock` and the rest — through an import written INSIDE the function that
needs it. That is not a style choice: the panel package is imported before `tools/lib` is
on `sys.path`, so a module-level `import lua_actions` would break the tab outright and be
noticed in the first second.

Forgetting the local one is the failure this file exists to stop, because it is the
opposite: nothing at all happens until the exact branch runs, and by then the traceback
is caught by whoever called it. Live, 2026-09-10 — `SecretTasksTab.apply_config` used
`lua_actions.sweep_division(…)` with no import in scope:

    [tabs] secret_tasks: saved block not applied while undrawn:
    NameError: name 'lua_actions' is not defined
      File "panel/tabs/secret_tasks/tab.py", line 1237, in apply_config
        self._sweep_pace = lua_actions.sweep_division(

It threw HALF WAY through restoring the tab's saved settings, so everything below that
line — the piece page's own block, the zoom combo, the rule hints — was skipped for every
profile of every restart for hours, and the only sign was one caught line in the log.

So: every name in `panel/` that matches a module under `tools/` or `tools/lib` must be
imported somewhere a reader of that name can see — at the top of its module, or in the
function it is used in, or in a function enclosing that one (a closure is how
`panel/widgets.py::click` legitimately reaches `coords`).

Needs nothing at all — it reads the source and never imports the panel.

    python3 tests/test_panel_lazy_imports.py
"""
from __future__ import annotations

TIER = "pure"      # source only: no Tk, no display, no game, no imports of the panel

import ast
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _toolkit_names() -> set:
    """Every module a `panel/` file could reach with a lazy `import <name>`."""
    names = set()
    for folder in ("tools", "tools/lib"):
        for path in (_REPO / folder).glob("*.py"):
            if path.stem != "__init__":
                names.add(path.stem)
    return names


def _bound_here(node) -> set:
    """Names this scope binds itself — imports, arguments and assignments.

    Nested functions are NOT walked into: their own bindings are theirs, and counting
    them here would let an inner import excuse an outer use.
    """
    bound = set()
    for child in ast.iter_child_nodes(node):
        bound |= _bound_in(child)
    for arg in getattr(getattr(node, "args", None), "args", []) or []:
        bound.add(arg.arg)
    return bound


def _bound_in(node) -> set:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    bound = set()
    if isinstance(node, ast.Import):
        bound |= {(a.asname or a.name).split(".")[0] for a in node.names}
    elif isinstance(node, ast.ImportFrom):
        bound |= {(a.asname or a.name) for a in node.names}
    elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        bound.add(node.id)
    for child in ast.iter_child_nodes(node):
        bound |= _bound_in(child)
    return bound


def _uses_here(node) -> list:
    """Names LOADED directly in this scope, not counting nested functions' own."""
    found = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            found.append(child)
        found += _uses_here(child)
    return found


def _walk(node, visible: set, toolkit: set, path: Path, out: list) -> None:
    """Check this scope against what it can see, then its children against more."""
    seen = visible | _bound_here(node)
    for name in _uses_here(node):
        if name.id in toolkit and name.id not in seen:
            out.append((path, getattr(node, "name", "<module>"), name.lineno, name.id))
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _walk(child, seen, toolkit, path, out)
        elif not isinstance(child, ast.Name):
            for deeper in ast.walk(child):
                if isinstance(deeper, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef)):
                    _walk(deeper, seen, toolkit, path, out)


def _offenders() -> list:
    toolkit = _toolkit_names()
    out: list = []
    for path in sorted((_REPO / "panel").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _walk(tree, set(), toolkit, path.relative_to(_REPO), out)
    return out


# ---------------------------------------------------------------------------
def test_the_toolkit_is_a_real_set_and_holds_the_name_that_broke():
    """A scan that found nothing because it looked for nothing is not a green test."""
    names = _toolkit_names()
    assert "lua_actions" in names, names
    assert len(names) > 20, len(names)


def test_no_panel_file_reaches_the_toolkit_without_importing_it():
    """THE BUG THIS FILE IS ABOUT. One line per offender, with the name it forgot."""
    bad = _offenders()
    assert not bad, "\n".join(f"{p}:{line}  {func}() uses «{name}» with no import"
                              for p, func, line, name in bad)


def test_the_scan_sees_a_closure_import_from_the_enclosing_function():
    """`panel/widgets.py::click` reads `coords` off its parent's import, and that is
    legal. A checker that flags it would be turned off within the week."""
    tree = ast.parse((_REPO / "panel" / "widgets.py").read_text(encoding="utf-8"))
    out: list = []
    _walk(tree, set(), {"coords"}, Path("panel/widgets.py"), out)
    assert not out, out


def test_the_scan_would_catch_the_line_that_actually_broke():
    """Fed the shape of the live defect, it must report it — otherwise the green above
    proves nothing."""
    src = ("def apply_config(self, raw):\n"
           "    self._pace = lua_actions.sweep_division(raw.get('p'))\n")
    out: list = []
    _walk(ast.parse(src), set(), {"lua_actions"}, Path("fake.py"), out)
    assert len(out) == 1 and out[0][3] == "lua_actions", out


def _run() -> int:
    bad = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
            print(f"  ok   {name}")
        except Exception as exc:                          # noqa: BLE001 — a report
            bad += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    total = sum(1 for n in globals() if n.startswith("test_"))
    print(f"\n{total - bad}/{total} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_run())
