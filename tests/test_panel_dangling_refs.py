r"""Nothing in the panel calls a method that moved out from under it (task #1191).

#1184 emptied the shell into plugin tabs over seven waves, and each wave carried a
method away without taking its callers. Three were left behind, and none of them was
loud:

  * `self._refresh_rule_hints()` in `_apply_settings_to_ui` — the hints belong to the
    «Секретные задания» tab now. This one ran on EVERY start, so the panel did not
    open at all: `AttributeError: '_tkinter.tkapp' object has no attribute
    '_refresh_rule_hints'`, three lines into the window;
  * `self._send_debug_archive()` behind the diagnostics dialog's «Отправить» — moved
    to the «Настройки» tab, so the one button that exists to report a problem raised
    one instead;
  * `self._timer_vars` / `self._trigger_vars` in the systems snapshot — moved to
    «Таймеры», and the read was inside `except AttributeError`, so debug.log has been
    quietly recording `timers_on=-1` ever since.

A dangling attribute is invisible until the line runs, which is why a refactor can ship
one, and why this is a test and not a review note. It reads the source rather than the
running window: every class the panel defines, every `self.x` it mentions, checked
against what that class actually has — its own body, whatever it assigns to `self`, the
names it reaches for through `getattr`, and everything it inherits (the real MRO, so
`self.after` and `self.winfo_rootx` on `Panel(tk.Tk)` are known to be fine).

Needs tkinter to import the panel's modules (no display — nothing is instantiated), so
it says SKIP under the WSL python3::

    C:\Python312\python.exe tests\test_panel_dangling_refs.py
    python3 tests/test_panel_dangling_refs.py       # SKIP without tkinter
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import ast
import importlib
import inspect
import pkgutil
import sys
import textwrap
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_SKIPPED = []


def _skip(name: str, exc=None) -> None:
    _SKIPPED.append(name)
    print(f"  SKIP {name}: {exc}" if exc else f"  SKIP {name}: no tkinter")


def _panel_modules():
    """Every importable module of the panel, the shell included.

    `panel.__main__` is imported by NAME here, which is safe and is not the trap the
    tabs have to avoid: importing it from a panel submodule is what runs the whole
    application a second time (docs/panel-tabs.md §5). A test is not a submodule.
    """
    import panel
    names = ["panel.__main__"]
    for info in pkgutil.walk_packages(panel.__path__, prefix="panel."):
        if info.name.endswith(".__main__"):
            continue                  # a tab's standalone launcher, not a class holder
        names.append(info.name)
    out = []
    for name in names:
        try:
            out.append(importlib.import_module(name))
        except Exception as exc:      # noqa: BLE001 — an optional dependency, not a ref
            print(f"       (skipped {name}: {exc})")
    return out


def _body(node: ast.ClassDef):
    """Every node of this class body, NOT descending into a class nested in it.

    Nested functions are followed — a callback closing over `self` is the class's code.
    A nested class is not: its `self` is its own, and counting `_Pane`'s widgets as the
    tab's would report every one of them as missing.
    """
    stack = list(node.body)
    while stack:
        item = stack.pop()
        if isinstance(item, ast.ClassDef):
            continue
        yield item
        stack.extend(ast.iter_child_nodes(item))


def _self_attrs(node: ast.ClassDef):
    """What this class body does with `self`: names it reads, and names it sets."""
    read, written = {}, set()
    for sub in _body(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                and sub.value.id == "self":
            if isinstance(sub.ctx, ast.Store):
                written.add(sub.attr)
            else:
                read.setdefault(sub.attr, sub.lineno)
        # `getattr(self, "x", None)` / `setattr` / `hasattr` — a name spelled as a
        # string is still a name, and the guarded ones are deliberate.
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                and sub.func.id in ("getattr", "setattr", "hasattr") \
                and len(sub.args) > 1 and isinstance(sub.args[1], ast.Constant):
            written.add(sub.args[1].value)
        # A bare annotation (`name: str` in a dataclass) declares a field with nothing
        # for `dir()` to see.
        if isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
            written.add(sub.target.id)
    return read, written


def _sets(cls) -> set:
    """The attribute names one class's own body puts on `self`."""
    try:
        src = textwrap.dedent(inspect.getsource(cls))
        node = ast.parse(src).body[0]
    except (OSError, TypeError, SyntaxError, IndexError):
        return set()
    if not isinstance(node, ast.ClassDef):
        return set()
    return _self_attrs(node)[1]


def _dangling(module, subclass_sets=None) -> list:
    """`(class, attr, line)` for every `self.x` the class cannot possibly have.

    "Cannot possibly have" is measured against the whole family — what `dir()` reports,
    what each base's own `__init__` assigns, which `dir()` does not (`self.rt` on a tab
    and `self.tk` on the window are both set that way), and what a SUBCLASS assigns: a
    base that paints into a `self._scroll` its pages each build is a template, not a
    dangling reference.
    """
    try:
        tree = ast.parse(inspect.getsource(module))
    except (OSError, TypeError, SyntaxError):
        return []
    out = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        cls = getattr(module, node.name, None)
        if not isinstance(cls, type):
            continue                  # conditionally defined — no real MRO to check
        read, written = _self_attrs(node)
        known = set(dir(cls)) | written | (subclass_sets or {}).get(cls, set())
        for base in cls.__mro__[1:]:
            known |= _sets(base)
        for attr, line in sorted(read.items(), key=lambda kv: kv[1]):
            if attr not in known:
                out.append((f"{module.__name__}.{node.name}", attr, line))
    return out


def _subclass_sets(modules) -> dict:
    """`{class: what its subclasses assign to self}`, across the whole panel."""
    out: dict = {}
    seen = set()
    for module in modules:
        for cls in vars(module).values():
            if not isinstance(cls, type) or cls in seen:
                continue
            seen.add(cls)
            sets = _sets(cls)
            for base in cls.__mro__[1:]:
                out.setdefault(base, set()).update(sets)
    return out


def test_no_panel_class_reaches_for_something_it_does_not_have():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:          # noqa: BLE001
        _skip("dangling refs", exc)
        return
    modules = _panel_modules()
    subclasses = _subclass_sets(modules)
    bad = []
    for module in modules:
        bad.extend(_dangling(module, subclasses))
    assert not bad, "self.<attr> that no longer exists:\n" + "\n".join(
        f"    {cls}:{line} -> self.{attr}" for cls, attr, line in bad)


def test_the_scan_catches_a_method_that_moved_out():
    """The check itself, against a class shaped like the bug it is here for."""
    src = (
        "class Widget:\n"
        "    def build(self):\n"
        "        self._rows = []\n"
        "        self._refresh_hints()\n"
        "        self.gone_too\n"
    )

    class _Mod:                       # a module stand-in: source + the real class
        __name__ = "fake"

    ns: dict = {}
    exec(compile(src.replace("self._refresh_hints()", "pass"), "<fake>", "exec"), ns)
    _Mod.Widget = ns["Widget"]
    module = _Mod()
    module.Widget = ns["Widget"]
    tree = ast.parse(src)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    read, written = _self_attrs(node)
    known = set(dir(module.Widget)) | written
    missing = sorted(a for a in read if a not in known)
    assert missing == ["_refresh_hints", "gone_too"], missing
    # …and what the class DOES assign is not reported.
    assert "_rows" not in missing


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed"
          + (f" ({len(_SKIPPED)} skipped)" if _SKIPPED else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
