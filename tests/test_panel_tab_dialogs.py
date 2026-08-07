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

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import ast
import sys
import time
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


class _Develop:
    """A real Tk root with a real Develop tab on it, and its end-of-run dialog.

    The tab is built against `cold_runtime`, so everything on screen is the panel's
    own — the locale files, the settings defaults — and nothing reaches the game.
    """

    def __enter__(self):
        import tkinter as tk
        from fake_runtime import cold_runtime
        from panel.tabs.develop import DevelopTab

        self.root = tk.Tk()
        self.root.withdraw()
        self.errors: list = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.rt = cold_runtime(self.root)
        self.tab = DevelopTab(self.rt, tk.Frame(self.root))
        self.run = _REPO / "tests" / "_dialog_run.tmp.log"
        self.run.write_text("XSCALL probe\n", encoding="utf-8")
        return self

    def open_dialog(self):
        """Run the end-of-session prompt; returns the Toplevel it put up."""
        before = set(self.root.winfo_children())
        self.tab._ask_run_outcome({"trace": str(self.run)}, "probe", seconds=3.0)
        new = [w for w in self.root.winfo_children() if w not in before]
        assert len(new) == 1, f"expected one dialog, got {new}"
        return new[0]

    def __exit__(self, *_exc) -> None:
        for widget in self.root.winfo_children():
            widget.destroy()
        self.run.unlink(missing_ok=True)
        self.rt.shutdown()
        # The window's shared hand-over pump re-arms itself every 30 ms and `shutdown`
        # only disarms the NAMED chains. The panel destroys its root and its process
        # together, so a pending pump never fires there; a test that raises and drops
        # several roots in one process gets «invalid command name …_pump» on stderr
        # unless it stops the chain itself.
        from panel.runtime import tick as tickmod

        pump = tickmod.poster(self.root)
        if pump is not None:
            pump.stop()
        self.root.destroy()


def test_the_develop_run_dialog_is_not_empty() -> None:
    """The bug as the person met it: open the real dialog and count what is in it.

    A static rule catches the shape; this catches the outcome, because «пустая
    модалка» is not «an exception was raised» — it is a window with no children.
    """
    with _Develop() as env:
        win = env.open_dialog()
        kinds = {type(w).__name__ for w in _descendants(win)}
        assert "Button" in kinds, f"no buttons in the dialog: {sorted(kinds)}"
        assert len(_descendants(win)) > 5, "the dialog came up empty"
        assert not env.errors, f"the dialog reported: {env.errors}"


def test_the_description_box_takes_the_first_keystroke() -> None:
    """Clicking the greyed placeholder must empty the box and hand back a colour.

    `foreground=""` is not "the widget's default" to Tk — a Text has no empty colour
    and raises «unknown color name ""» from inside the binding, which the event loop
    swallows into `report_callback_exception`: the person sees their own words stay
    grey and nothing says why (#1235, found by running the capture for real).
    """
    with _Develop() as env:
        win = env.open_dialog()
        boxes = [w for w in _descendants(win) if type(w).__name__ in ("Text", "ScrolledText")]
        assert boxes, "no description box in the dialog"
        box = boxes[0]
        assert box.get("1.0", "end").strip(), "the placeholder is not there to clear"
        box.focus_set()
        box.event_generate("<Button-1>")
        env.root.update()
        assert not env.errors, f"clearing the placeholder raised: {env.errors}"
        assert not box.get("1.0", "end").strip(), "the placeholder survived the click"
        colour = box.cget("foreground")
        assert colour and colour != "#888", f"typing would stay grey: {colour!r}"


def test_a_child_dying_arms_the_prompt_from_the_tk_thread() -> None:
    """`tick.arm` is `widget.after`, and a reader thread must not make that call.

    When both sniffers die on their own the session ends in the READER thread, and
    the same save/delete prompt has to come up. Arming it from there is the call
    that blocks on the event loop and raises «main thread is not in main loop»
    while the window is pumping by hand — killing the reader (#1226).
    """
    import threading

    with _Develop() as env:
        callers: list = []
        env.rt.tick.arm = lambda name, delay, func: callers.append(
            (name, threading.current_thread()))

        worker = threading.Thread(target=env.tab._sync_sniff_var)
        worker.start()
        worker.join(5.0)
        assert not worker.is_alive(), "the reader thread is stuck in a Tk call"
        assert not callers, f"armed straight from the worker: {callers}"

        for _ in range(20):                     # let the shared pump drain the queue
            env.root.update()
            time.sleep(0.02)
        assert callers, "the prompt was never armed"
        name, thread = callers[0]
        assert name == "sniff_flush", f"armed the wrong chain: {name}"
        assert thread is threading.main_thread(), f"armed on {thread.name}"


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
