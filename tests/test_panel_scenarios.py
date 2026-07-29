r"""The Scenarios tab — editing a script, and driving a run from the panel.

Two things were added on top of "pick a script and run it" (task #1118), and both
can go wrong quietly:

  * **the editor** — clicking a row opens that script, and what is typed is written
    back a second later. The ways that hurt: writing the text of one file into
    another after a click, an undo that reaches back into the previously opened
    file, and a run that reads the file while an edit is still sitting in the
    debounce.
  * **the run controls** — while a script runs the list is locked, its row carries
    a marker, Stop is the only live button, and all of that must come BACK when
    the run ends, whether it ended by itself or was stopped.

Both need Tk and a display, so this says SKIP under the WSL python3 (no tkinter)
or on a headless box. `Panel`'s methods are called unbound against a stand-in, so
no panel window is opened and no game is needed — and both ACTIONS_DIRs (the
panel's and the engine's) are pointed at a temp copy, so the repo's own scripts
are never written to.

    C:\Python312\python.exe tests\test_panel_scenarios.py
    python3 tests/test_panel_scenarios.py        # SKIP without tkinter
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SLOW = 'LOG "one"\nWAIT 0.4\nLOG "two"\nWAIT 0.4\nLOG "three"\n'


def _tab(tmp: Path):
    """A Panel stand-in with the Scenarios tab really built, on a temp actions dir."""
    import tkinter as tk
    from tkinter import ttk
    from panel import i18n as i18nmod
    import panel.__main__ as pm
    from lastwar_bot import script_engine as se

    (tmp / "slow.md").write_text("# A slow script.\n\n" + SLOW, encoding="utf-8")
    (tmp / "other.md").write_text('# Another one.\n\nLOG "other"\n', encoding="utf-8")
    pm.ACTIONS_DIR = str(tmp)
    se.ACTIONS_DIR = tmp
    se.DEV_ACTIONS_DIR = tmp / "dev"

    root = tk.Tk()
    root.withdraw()

    class _Tab:
        def __init__(self):
            self._i18n = i18nmod.I18n("ru")
            self._tr_widgets: list = []
            self._busy = False
            import threading
            self._busy_lock = threading.Lock()
            self.logs: list = []

        # everything the tab builder and the paths under test touch
        _t = pm.Panel._t
        _tr = pm.Panel._tr
        _claim_busy = pm.Panel._claim_busy
        _release_busy = pm.Panel._release_busy
        _build_scenarios_tab = pm.Panel._build_scenarios_tab
        _refresh_actions = pm.Panel._refresh_actions
        _paint_action_rows = pm.Panel._paint_action_rows
        _selected_action_name = pm.Panel._selected_action_name
        _run_selected_action = pm.Panel._run_selected_action
        _scenario_args = pm.Panel._scenario_args
        _run_md_action = pm.Panel._run_md_action
        _set_scenario_running = pm.Panel._set_scenario_running
        _stop_scenario = pm.Panel._stop_scenario
        _on_scenario_selected = pm.Panel._on_scenario_selected
        _load_scenario_into_editor = pm.Panel._load_scenario_into_editor
        _on_editor_modified = pm.Panel._on_editor_modified
        _schedule_scenario_save = pm.Panel._schedule_scenario_save
        _flush_scenario_save = pm.Panel._flush_scenario_save
        _save_scenario = pm.Panel._save_scenario
        _on_editor_ctrl_key = pm.Panel._on_editor_ctrl_key
        _toggle_scenario_loop = pm.Panel._toggle_scenario_loop
        _stop_scenario_loop = pm.Panel._stop_scenario_loop

        def _log_put(self, line):
            self.logs.append(line)

        def after(self, ms, fn=None):
            return root.after(ms, fn) if fn is not None else None

        def after_cancel(self, job):
            root.after_cancel(job)

        def _refresh_status(self):
            pass

    tab = _Tab()
    tab._build_scenarios_tab(ttk.Frame(root))
    return root, tab, pm


def _select(tab, name: str) -> None:
    idx = next(i for i, a in enumerate(tab._scn_actions) if a["name"] == name)
    tab._scn_list.selection_clear(0, "end")
    tab._scn_list.selection_set(idx)
    tab._on_scenario_selected()


def _pump(root, until, timeout: float = 8.0) -> bool:
    """Run the REAL Tk event loop until `until()` or the timeout.

    `mainloop`, not a hand-rolled `update()` loop: the panel's workers hand their
    UI updates back with `self.after(...)`, and tkinter only accepts a call from
    another thread while the main thread is actually sitting in the event loop.
    Pumping with `update()` would fail here for a reason the real panel never has.
    """
    done = {"ok": False}
    deadline = time.time() + timeout

    def check():
        if until():
            done["ok"] = True
            root.quit()
            return
        if time.time() > deadline:
            root.quit()
            return
        root.after(30, check)

    root.after(0, check)
    root.mainloop()
    return done["ok"]


def _close(root) -> None:
    """Drop pending `after` jobs before tearing the interpreter down.

    A job still queued when the interpreter goes away makes Tcl print an
    "invalid command name" line — noise that reads like a failure in a test log.
    """
    try:
        for job in root.tk.eval("after info").split():
            try:
                root.after_cancel(job)
            except Exception:                           # noqa: BLE001
                pass
    except Exception:                                   # noqa: BLE001
        pass
    root.destroy()


def test_editor_loads_saves_and_undoes():
    try:
        import tkinter  # noqa: F401
    except Exception:                                   # noqa: BLE001
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        root, tab, _pm = _tab(tmp)
    except Exception as exc:                            # noqa: BLE001
        print(f"  SKIP no display / panel deps: {exc}")
        return
    try:
        # The first script is in the editor as soon as the tab exists.
        assert tab._scn_editor_name in {"other", "slow"}, tab._scn_editor_name
        _select(tab, "slow")
        assert tab._scn_editor_name == "slow"
        assert 'LOG "one"' in tab._scn_editor.get("1.0", "end")

        # Typing schedules a write rather than doing one per character…
        original = (tmp / "slow.md").read_text(encoding="utf-8")
        tab._scn_editor.insert("end", 'LOG "four"\n')
        tab._on_editor_modified()
        assert tab._scn_save_job is not None, "no save was scheduled"
        assert (tmp / "slow.md").read_text(encoding="utf-8") == original, \
            "wrote on the keystroke instead of debouncing"

        # …and the debounce really fires on its own.
        assert _pump(root, lambda: tab._scn_save_job is None, timeout=5), "the save never ran"
        assert 'LOG "four"' in (tmp / "slow.md").read_text(encoding="utf-8")

        # Ctrl+Z takes it back, and the next save writes the undone text.
        tab._scn_editor.edit_undo()
        assert 'LOG "four"' not in tab._scn_editor.get("1.0", "end")
        tab._on_editor_modified()
        tab._flush_scenario_save()
        assert 'LOG "four"' not in (tmp / "slow.md").read_text(encoding="utf-8")

        # Switching files flushes the old one and starts a fresh undo history —
        # an undo here must NOT drag the other script's text into this one.
        tab._scn_editor.insert("end", 'LOG "pending"\n')
        tab._on_editor_modified()
        _select(tab, "other")
        assert tab._scn_editor_name == "other"
        assert 'LOG "pending"' in (tmp / "slow.md").read_text(encoding="utf-8"), \
            "the pending edit was lost when the selection moved"
        before = tab._scn_editor.get("1.0", "end")
        try:
            tab._scn_editor.edit_undo()
        except Exception:                               # noqa: BLE001
            pass                                        # nothing to undo is the point
        assert tab._scn_editor.get("1.0", "end") == before, "undo reached into the other file"
        assert "pending" not in (tmp / "other.md").read_text(encoding="utf-8")
    finally:
        _close(root)


def test_a_run_locks_the_list_marks_the_row_and_stops():
    try:
        import tkinter  # noqa: F401
    except Exception:                                   # noqa: BLE001
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        root, tab, pm = _tab(tmp)
    except Exception as exc:                            # noqa: BLE001
        print(f"  SKIP no display / panel deps: {exc}")
        return
    try:
        _select(tab, "slow")
        tab._run_selected_action()

        # Locked, marked, and Stop is the only live button.
        assert tab._scn_running == "slow", tab._scn_running
        assert str(tab._scn_list.cget("state")) == "disabled", "the list stayed clickable"
        assert str(tab._scn_run_btn.cget("state")) == "disabled"
        assert str(tab._scn_stop_btn.cget("state")) == "normal"
        marked = [tab._scn_list.get(i) for i in range(tab._scn_list.size())
                  if tab._scn_list.get(i).startswith(pm.RUNNING_MARK)]
        assert len(marked) == 1 and "slow" in marked[0], marked

        # A second run is refused while the first is in flight.
        before = len(tab.logs)
        tab._run_selected_action()
        assert any(tab._t("busy") in ln for ln in tab.logs[before:]), tab.logs[before:]

        # Stop lands between steps: the script had three LOGs and 0.8 s of WAITs,
        # so it must end well before it would have finished on its own.
        t0 = time.time()
        tab._stop_scenario()
        assert _pump(root, lambda: tab._scn_running is None, timeout=6), "the run never ended"
        assert time.time() - t0 < 3.0, "stop did not take effect between steps"

        # …and everything came back.
        assert str(tab._scn_list.cget("state")) == "normal", "the list stayed locked"
        assert str(tab._scn_run_btn.cget("state")) == "normal"
        assert str(tab._scn_stop_btn.cget("state")) == "disabled"
        assert not any(tab._scn_list.get(i).startswith(pm.RUNNING_MARK)
                       for i in range(tab._scn_list.size())), "the marker was left behind"
        assert tab._busy is False, "the busy flag was left claimed"

        # The halt is reported as a halt, not as a failure.
        assert any("HALTED" in ln for ln in tab.logs), tab.logs[-6:]

        # A run left to finish on its own unlocks the same way.
        tab._run_selected_action()
        assert tab._scn_running == "slow"
        assert _pump(root, lambda: tab._scn_running is None, timeout=8), "the run never ended"
        assert str(tab._scn_list.cget("state")) == "normal"
        assert any("three" in ln for ln in tab.logs), "the script did not run to the end"
    finally:
        _close(root)


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
