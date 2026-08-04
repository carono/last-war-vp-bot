r"""A tab is not a widget — and Tk only says so when the dialog is already on screen.

Every tab under `panel/tabs/` is a plain :class:`~panel.tabs.base.PanelTab`: it OWNS
widgets (`self.parent`, `self.rt.root`) and is not one. Tk, though, resolves a master,
a transient owner and a dialog's `parent=` by WINDOW PATH — it stringifies whatever it
is handed and looks the result up — so `tk.Toplevel(self)` and `win.transient(self)`
raise nothing at import time, nothing at build time, and blow up the moment a person
presses the button.

The failure is worse than a crash, because the crash is half-done. `_ask_run_outcome`
in the Develop tab created its `Toplevel`, set its title, and THEN called
`transient(self)`: the exception left a real window on screen with nothing in it —
no description box, no Save, no Delete, no grab — and the run it was supposed to label
sat unlabelled on disk (#1235). Two more of the same were in the Chat and Timers tabs,
all three left behind by the move of those tabs out of `panel/__main__.py`, where
`self` really was the `tk.Tk` window (#1184).

Nothing under `panel/tabs/` subclasses a Tk widget, so a bare `self` in any of those
slots is always this bug. Run it with the panel's own interpreter::

    C:\Python312\python.exe tests\test_panel_tab_dialogs.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

TABS_DIR = _REPO / "panel" / "tabs"

#: Modules whose callables take a window path where a first positional argument goes.
_TK_MODULES = {"tk", "ttk", "tkinter", "simpledialog", "messagebox", "filedialog"}

#: Keyword arguments Tk resolves as a window path.
_WINDOW_KWARGS = {"parent", "master", "in_"}

#: Methods whose only argument is another window.
_WINDOW_METHODS = {"transient", "wm_transient"}


def _is_self(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "self"


def _root_name(node: ast.AST) -> str:
    """`tk.Toplevel` -> "tk"; `self.rt.root.after` -> "self"; anything else -> ""."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _rel(path: Path) -> str:
    """Repo-relative when it can be, the path as given otherwise (a scratch probe)."""
    try:
        return path.resolve().relative_to(_REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _offences(path: Path) -> list:
    """Every place this file hands the tab itself to Tk as if it were a window."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = _rel(path)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # tk.Toplevel(self) / ttk.Frame(self) — `self` standing in for a master
        if (isinstance(func, ast.Attribute) and _root_name(func) in _TK_MODULES
                and node.args and _is_self(node.args[0])):
            found.append(f"{rel}:{node.lineno}: {_root_name(func)}.{func.attr}(self)")
        # win.transient(self)
        if (isinstance(func, ast.Attribute) and func.attr in _WINDOW_METHODS
                and node.args and _is_self(node.args[0])):
            found.append(f"{rel}:{node.lineno}: .{func.attr}(self)")
        # messagebox.askyesno(..., parent=self)
        for kw in node.keywords:
            if kw.arg in _WINDOW_KWARGS and _is_self(kw.value):
                found.append(f"{rel}:{node.lineno}: {kw.arg}=self")
    return found


def test_no_tab_passes_itself_to_tk() -> None:
    """A PanelTab handed to Tk as a window is a dialog that half-opens and dies."""
    offences = []
    for path in sorted(TABS_DIR.rglob("*.py")):
        offences += _offences(path)
    assert not offences, (
        "a PanelTab is not a widget; use self.rt.root (the window) or self.parent "
        "(the tab's frame):\n  " + "\n  ".join(offences))


def test_no_tab_subclasses_a_widget() -> None:
    """The rule above only holds while no tab IS a widget. Pin that too."""
    widgets = []
    for path in sorted(TABS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                if isinstance(base, ast.Attribute) and _root_name(base) in _TK_MODULES:
                    rel = _rel(path)
                    widgets.append(f"{rel}:{node.lineno}: {node.name}")
    assert not widgets, (
        "a tab that subclasses a Tk widget makes `self` a legal master again — "
        "teach test_no_tab_passes_itself_to_tk about it before landing:\n  "
        + "\n  ".join(widgets))


def test_the_check_would_have_caught_it() -> None:
    """The detector, against the three shapes that actually shipped broken."""
    sample = (
        "class T:\n"
        "    def go(self):\n"
        "        win = tk.Toplevel(self)\n"
        "        win.transient(self)\n"
        "        messagebox.askyesno('a', 'b', parent=self)\n"
        "        ok = tk.Toplevel(self.rt.root)\n"
        "        ok.transient(self.rt.root)\n"
    )
    tmp = _REPO / "tests" / "_dialog_probe.tmp.py"
    tmp.write_text(sample, encoding="utf-8")
    try:
        hits = _offences(tmp)
    finally:
        tmp.unlink()
    assert len(hits) == 3, f"expected the three bad lines, got: {hits}"


def test_the_develop_run_dialog_is_not_empty() -> None:
    """The bug as the person met it: open the real dialog and count what is in it.

    A static rule catches the shape; this catches the outcome, because «пустая
    модалка» is not «an exception was raised» — it is a window with no children.
    """
    import tkinter as tk
    from fake_runtime import cold_runtime

    root = tk.Tk()
    root.withdraw()
    try:
        from panel.tabs.develop import DevelopTab

        rt = cold_runtime(root)
        frame = tk.Frame(root)
        tab = DevelopTab(rt, frame)

        run = _REPO / "tests" / "_dialog_run.tmp.log"
        run.write_text("XSCALL probe\n", encoding="utf-8")
        before = set(root.winfo_children())
        try:
            tab._ask_run_outcome({"trace": str(run)}, "probe", seconds=3.0)
            new = [w for w in root.winfo_children() if w not in before]
            assert len(new) == 1, f"expected one dialog, got {new}"
            win = new[0]
            kinds = {type(w).__name__ for w in _descendants(win)}
            assert "Button" in kinds, f"no buttons in the dialog: {sorted(kinds)}"
            assert len(list(_descendants(win))) > 5, "the dialog came up empty"
        finally:
            for widget in root.winfo_children():
                widget.destroy()
            run.unlink(missing_ok=True)
    finally:
        root.destroy()


def _descendants(widget) -> list:
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out += _descendants(child)
    return out


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:                    # noqa: BLE001
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
