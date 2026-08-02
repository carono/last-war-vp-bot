"""The «Сценарии» tab: the list of `actions/*.md`, an editor for one, and the run.

Each `src/lastwar_bot/actions/*.md` is one runnable ability — which is the whole point
of `CLAUDE.md`'s rule — and this tab is where a person picks one, reads it, fixes it and
presses it. Nothing here knows anything about the game: the run goes through
`rt.play_async`, the same door the shell relaunches the client with.

Three things it does that are worth keeping straight:

* **the editor writes itself back**, a second after the last keystroke, having PARSED
  the text first. It used to write whatever was in it, so a typo was discovered when the
  run failed — by which time the file had already replaced a working recipe. A `.bak` of
  the previous text sits beside the file, because Tk's undo is in-session only;
* **one script runs at a time, and it is visible which.** The list is locked and the
  running row carries a marker;
* **Stop is not a kill.** The interpreter checks a flag between statements, so the step
  in flight finishes and nothing is left half-sent to the game.

The `TAP` reference is opened here but drawn by the shell — the dialog drops its choice
into the DSL command line on «Главная», which is not this tab's to write to
(docs/research/panel-tabs-refactor.md §7). So the button publishes and the shell listens.
"""
from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ..runtime import ActionRunner, list_actions
from ..widgets import numeric_spinbox
from .base import PanelTab

# How long the editor waits after the last keystroke before writing the file. Long
# enough that a burst of typing is one write, short enough that a run started right
# after an edit reads what is on screen (and a run flushes first anyway, so this is
# about disk chatter, not correctness).
SAVE_DELAY_MS = 1000
#: Marks the row of the script that is running right now.
RUNNING_MARK = "▶"
#: Marks a row that came out of actions/dev/ — experimental, shown only on request.
DEV_MARK = "⚙ "


class ScenariosTab(PanelTab):
    """List, edit, run, repeat."""

    ID = "scenarios"
    TITLE_KEY = "tab.scenarios"
    ORDER = 20
    PREFERRED_SIZE = "820x720"
    LOCALE_NS = ("scenarios", "cmd")
    NEEDS = frozenset({"daemon", "actions"})
    LEGACY_KEYS = {k: k for k in ("scenario_selected", "scenario_args",
                                  "scenario_interval")}

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._cancel = None            # threading.Event of the run in flight, else None

    # -- lifecycle ------------------------------------------------------------
    def panic(self) -> None:
        """«Стоп всё»: the repeat loop off, and the run in flight asked to halt."""
        self._stop_scenario_loop()
        self._stop_scenario()

    def shutdown(self) -> None:
        # A debounced edit is still pending for up to a second — write it before the
        # window goes, or the last thing typed is the thing that is lost.
        self.flush_save()
        self._stop_scenario_loop()

    def on_language_change(self) -> None:
        self._refresh_actions()

    # -- persistence ----------------------------------------------------------
    def config(self) -> dict:
        return {
            # The tab used to forget all three on every restart, so a launch always
            # started on the first row with an empty args box.
            "scenario_selected": self._scn_editor_name or "",
            "scenario_args": self._scn_args_var.get(),
            "scenario_interval": self._scn_interval_var.get(),
        }

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._scn_args_var.set(raw.get("scenario_args", ""))
        self._scn_interval_var.set(str(raw.get("scenario_interval", "60")))
        self._select_saved_scenario(raw.get("scenario_selected"))

    def persist_vars(self) -> list:
        return [self._scn_args_var, self._scn_interval_var]

    def _open_reference(self) -> None:
        """Ask whoever holds the DSL command line to show the `TAP` vocabulary."""
        self.rt.bus.publish("cmd.reference")

    def build(self) -> None:
        """List the DSL action scripts, edit one, and run or loop it.

        Each `src/lastwar_bot/actions/*.md` is one runnable action. Run executes it
        once through the interpreter on a worker thread (output streams into the
        shared log); Repeat re-runs it on an interval until switched off. Game-VM
        actions (LUA/READ_LUA/GAME/JUMP) go through the Lua daemon and need no
        window; vision actions (FIND/CLICK) resolve the game window on demand.

        Selecting a row opens that script in the editor below, which writes itself
        back a second after the last keystroke — so a recipe is fixed and re-run
        without leaving the panel.

        While a run is in flight the list is locked and its row carries a marker:
        one script at a time, and it is visible WHICH one. Stop asks the
        interpreter to halt at its next step (a flag it checks between statements),
        rather than killing the thread in the middle of a call into the game.
        """
        self._scn_loop_stop = threading.Event()
        self._scn_loop_thread: threading.Thread | None = None
        # Which script is running right now, and the flag that asks it to stop.
        # Both live here rather than in the worker so the Stop button, the row
        # marker and the lock all read the same truth.
        self._scn_running: str | None = None
        self._cancel: threading.Event | None = None
        # Editor state: which file is loaded (name and the path it came from —
        # the two are not interchangeable, a script may live in actions/dev/), and
        # the pending debounced save.
        self._scn_editor_name: str | None = None
        self._scn_editor_path: str | None = None
        self._scn_save_job = None
        self._scn_loading = False

        frame = self.tr(ttk.LabelFrame(self.parent, padding=8), "scenarios.actions")
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        listwrap = ttk.Frame(frame)
        listwrap.pack(fill="x")
        self._scn_list = tk.Listbox(listwrap, height=8, activestyle="dotbox",
                                    exportselection=False)
        scroll = ttk.Scrollbar(listwrap, orient="vertical", command=self._scn_list.yview)
        self._scn_list.configure(yscrollcommand=scroll.set)
        self._scn_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._scn_list.bind("<Double-Button-1>", lambda _e: self._run_selected_action())
        # Selecting a script opens it in the editor below.
        self._scn_list.bind("<<ListboxSelect>>", self._on_scenario_selected)

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(8, 0))
        self._scn_run_btn = self.tr(ttk.Button(controls, command=self._run_selected_action),
                                     "scenarios.run")
        self._scn_run_btn.pack(side="left", padx=(0, 4), ipady=2)
        # Stop is enabled only while a run is in flight; it asks the interpreter to
        # halt between steps rather than killing the thread mid-call.
        self._scn_stop_btn = self.tr(ttk.Button(controls, command=self._stop_scenario,
                                                 state="disabled"), "scenarios.stop")
        self._scn_stop_btn.pack(side="left", padx=(0, 4), ipady=2)
        self._scn_loop_var = tk.BooleanVar(value=False)
        self.tr(ttk.Checkbutton(controls, variable=self._scn_loop_var,
                                 command=self._toggle_scenario_loop),
                 "scenarios.loop").pack(side="left", padx=(8, 2))
        self.tr(ttk.Label(controls), "scenarios.interval").pack(side="left", padx=(6, 2))
        self._scn_interval_var = tk.StringVar(value="60")
        numeric_spinbox(controls, from_=5, to=86400, width=6,
                    textvariable=self._scn_interval_var).pack(side="left")
        self.tr(ttk.Button(controls, command=self._refresh_actions),
                 "scenarios.refresh").pack(side="right")
        # actions/dev/ is deliberately hidden from the picker — but it also hid
        # work_treasure and collect_trucks, and reaching those meant a code change.
        # A checkbox is the right size for "show the experimental ones too".
        self._scn_dev_var = tk.BooleanVar(value=False)
        self.tr(ttk.Checkbutton(controls, variable=self._scn_dev_var,
                                 command=self._refresh_actions),
                 "scenarios.show_dev").pack(side="right", padx=(0, 8))
        self.tr(ttk.Button(controls, command=self._open_reference),
                 "cmd.reference").pack(side="right", padx=(0, 8))

        # Arguments for the run — the script's own `ARGS` defaults fill in the rest.
        # JSON, because that is what a timer's `args` block is too, so a line that
        # works here can be pasted into timers.json unchanged.
        argrow = ttk.Frame(frame)
        argrow.pack(fill="x", pady=(6, 0))
        self.tr(ttk.Label(argrow), "scenarios.args").pack(side="left", padx=(0, 4))
        self._scn_args_var = tk.StringVar()
        ttk.Entry(argrow, textvariable=self._scn_args_var).pack(side="left", fill="x",
                                                                expand=True)

        # The editor. The selected script is loaded here and written back a second
        # after the last keystroke — no Save button to forget, and no write per
        # character either. Undo is Tk's own (`undo=True`), reset on every load so
        # Ctrl+Z can never reach back into the previously opened file.
        edit = self.tr(ttk.LabelFrame(frame, padding=4), "scenarios.editor")
        edit.pack(fill="both", expand=True, pady=(8, 0))
        self._scn_editor = ScrolledText(
            edit, wrap="none", height=12, undo=True, autoseparators=True, maxundo=-1,
            font=("Consolas", 9))
        self._scn_editor.pack(fill="both", expand=True)
        self._scn_editor.bind("<<Modified>>", self._on_editor_modified)
        # Ctrl+Z / Ctrl+Y by physical key, so they work under a Cyrillic layout —
        # Tk's own <<Undo>> binding matches the Latin keysym only (same fix as the
        # log's copy, see _install_log_copy).
        self._scn_editor.bind("<Control-KeyPress>", self._on_editor_ctrl_key)

        # The first parse error of what is in the editor, shown where it is typed —
        # a debounced save now refuses a recipe that does not parse instead of
        # replacing a working one with it.
        self._scn_problem_lbl = ttk.Label(frame, foreground="#c33", wraplength=680,
                                          justify="left")
        self._scn_problem_lbl.pack(anchor="w", pady=(4, 0))

        self.tr(ttk.Label(frame, foreground="#888", wraplength=680, justify="left"),
                 "scenarios.hint").pack(anchor="w", pady=(8, 0))

        self._scn_actions: list[dict] = []
        self._refresh_actions()
        self._load_scenario_into_editor(self._selected_action_name())

    def _refresh_actions(self) -> None:
        """(Re)load the action list into the listbox, keeping the selection if possible."""
        prev = self._selected_action_name()
        self._scn_actions = list_actions(
            include_dev=bool(getattr(self, "_scn_dev_var", None)
                             and self._scn_dev_var.get()),
            lang=self.rt.i18n.lang)
        self._paint_action_rows()
        if not self._scn_actions:
            self.say("action", "scenarios.empty")
            return
        idx = next((i for i, a in enumerate(self._scn_actions) if a["name"] == prev), 0)
        self._scn_list.selection_clear(0, "end")
        self._scn_list.selection_set(idx)
        self._scn_list.see(idx)

    def _select_saved_scenario(self, name) -> None:
        """Put the selection back on the script the profile was last using.

        The tab used to forget all of it on restart, so every launch started on the
        first row with an empty args box.
        """
        name = str(name or "").strip()
        if not name or not getattr(self, "_scn_actions", None):
            return
        idx = next((i for i, a in enumerate(self._scn_actions) if a["name"] == name), None)
        if idx is None:
            return
        try:
            self._scn_list.selection_clear(0, "end")
            self._scn_list.selection_set(idx)
            self._scn_list.see(idx)
        except tk.TclError:
            return
        self._load_scenario_into_editor(name)

    def _paint_action_rows(self) -> None:
        """Rewrite every row, marking the one that is running.

        Done wholesale rather than in place because the marker changes a row's
        width; the list is briefly re-enabled because a disabled Listbox is the
        state it sits in for the whole run.
        """
        keep = self._scn_list.cget("state")
        sel = self._scn_list.curselection()
        self._scn_list.configure(state="normal")
        self._scn_list.delete(0, "end")
        for item in self._scn_actions:
            mark = RUNNING_MARK if item["name"] == self._scn_running else "   "
            dev = DEV_MARK if item.get("dev") else ""
            self._scn_list.insert("end",
                                  f"{mark} {dev}{item['title']}   ·   {item['name']}")
        for idx in sel:
            self._scn_list.selection_set(idx)
        self._scn_list.configure(state=keep)

    def _selected_action_name(self) -> str | None:
        sel = self._scn_list.curselection() if hasattr(self, "_scn_list") else ()
        if not sel:
            return None
        return self._scn_actions[sel[0]]["name"]

    def _run_selected_action(self) -> None:
        name = self._selected_action_name()
        if name is None:
            self.say("action", "scenarios.none_selected")
            return
        args = self._scenario_args()
        if args is None:                      # unreadable JSON — already complained
            return
        self.play(name, args)

    def _scenario_args(self) -> dict | None:
        """What is typed in the «аргументы» box, as a dict. ``None`` = unusable.

        Empty means "no arguments", which is not the same as a typo: a script run
        with its defaults because the JSON did not parse would look like it worked,
        so a bad box refuses the run and says why.
        """
        raw = (self._scn_args_var.get() or "").strip()
        if not raw:
            return {}
        try:
            args = json.loads(raw)
        except ValueError as exc:
            self.say("action", "scenarios.bad_args", error=exc)
            return None
        if not isinstance(args, dict):
            self.say("action", "scenarios.bad_args",
                      error="expected {\"name\": value}")
            return None
        return args

    def play(self, name: str, args: dict | None = None) -> None:
        """Run one scenario through the interpreter on a worker thread.

        `args` are the script's parameters: they fill in its `ARGS` declarations and are
        substituted for `{name}` in its text (see docs/dsl.md). Passing none runs it on
        its own defaults.

        The claim, the thread and the log line are the runtime's `play_async` — the same
        press the shell relaunches the client with. What is this tab's is the marker on
        the running row and the lock on the list while it runs.
        """
        # Whatever is being typed lands on disk before the run reads the file —
        # otherwise a change made a second ago would silently not be in the run.
        self.flush_save()
        cancel = threading.Event()
        shown = f"{name} {json.dumps(args, ensure_ascii=False)}" if args else name
        # A refused press must NOT clear `_cancel`: the run it was refused BY is still
        # in flight, and Stop is the only thing that can end it.
        self.rt.play_async(
            name, args, tag="action", cancel=cancel,
            on_start=lambda: self._on_run_started(name, cancel, shown),
            on_done=lambda: self._set_scenario_running(None))

    def _on_run_started(self, name, cancel, shown) -> None:
        self._cancel = cancel
        self.rt.put(f"[action] {shown}: {self.t('scenarios.running')}")
        self._set_scenario_running(name)

    def _set_scenario_running(self, name: str | None) -> None:
        """Lock the list and mark the running row — or undo both when it ends."""
        self._scn_running = name
        running = name is not None
        if not running:
            # The run is over: Stop has nothing left to ask, and a stale flag would
            # make the button say «останавливаю» at a script that already finished.
            self._cancel = None
        try:
            self._paint_action_rows()
            self._scn_list.configure(state="disabled" if running else "normal")
            self._scn_run_btn.configure(state="disabled" if running else "normal")
            self._scn_stop_btn.configure(state="normal" if running else "disabled")
        except tk.TclError:
            pass                            # the tab is gone (panel closing)

    def _stop_scenario(self) -> None:
        """«Стоп» — ask the running script to halt at its next step.

        Not a kill: the interpreter checks the flag between statements, between the
        presses of a repeat and between the polls of a WAIT, so the step in flight
        finishes and nothing is left half-sent to the game. A looping run is stopped
        too, or the loop would start the next pass a second later.
        """
        cancel = self._cancel
        if cancel is None:
            return
        cancel.set()
        if getattr(self, "_scn_loop_var", None) is not None and self._scn_loop_var.get():
            self._stop_scenario_loop()
        self.say("action", "scenarios.stopping", name=self._scn_running or "")

    # -- scenario editor ----------------------------------------------------

    def _on_scenario_selected(self, _event=None) -> None:
        """A row was clicked: put that script in the editor (saving the old one)."""
        name = self._selected_action_name()
        if name is None or name == self._scn_editor_name:
            return
        self.flush_save()         # never carry edits into another file
        self._load_scenario_into_editor(name)

    def _load_scenario_into_editor(self, name: str | None) -> None:
        """Read a script into the editor and start its undo history fresh."""
        if name is None:
            return
        resolved = self.rt.actions.resolve(name)
        if resolved is None:
            self.say("action", "scenarios.not_found", name=name)
            return
        path = str(resolved)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            self.rt.put(f"[action] {name}: {exc}")
            return
        self._scn_loading = True            # the fill is not an edit to save back
        try:
            self._scn_editor.delete("1.0", "end")
            self._scn_editor.insert("1.0", text)
            # Reset AFTER the fill, or Ctrl+Z would undo its way back into whatever
            # file was open before this one.
            self._scn_editor.edit_reset()
            self._scn_editor.edit_modified(False)
        finally:
            self._scn_loading = False
        self._scn_editor_name = name
        self._scn_editor_path = path
        # A freshly opened file's own problems, if any — not the last file's.
        self._show_scenario_problem(self._scenario_problem(text))

    def _on_editor_modified(self, _event=None) -> None:
        """Tk's <<Modified>> fires once until reset — use it to debounce the save."""
        if not self._scn_editor.edit_modified():
            return
        self._scn_editor.edit_modified(False)
        if self._scn_loading or self._scn_editor_name is None:
            return
        self._schedule_scenario_save()

    def _schedule_scenario_save(self) -> None:
        """Write a second after the last keystroke, not on every character."""
        if self._scn_save_job is not None:
            try:
                self.rt.root.after_cancel(self._scn_save_job)
            except tk.TclError:
                pass
        self._scn_save_job = self.rt.root.after(SAVE_DELAY_MS, self._save_scenario)

    def flush_save(self) -> None:
        """Write a pending edit right now (before a run, or before another file)."""
        if self._scn_save_job is None:
            return
        try:
            self.rt.root.after_cancel(self._scn_save_job)
        except tk.TclError:
            pass
        self._scn_save_job = None
        self._save_scenario()

    def _save_scenario(self) -> None:
        """Write the editor back to the file it was loaded from — checked, and backed up.

        Two things the editor used to be missing, both of which cost work:

          * **The text is parsed first.** The editor wrote whatever was in it a second
            after the last keystroke, so a typo was discovered when the run failed —
            and by then the file had already replaced a working recipe. The DSL
            parser was right there; now the first error lands under the editor and
            the previous file is left alone.
          * **A `.bak` of the previous text.** Tk's own undo is in-session only, so a
            panel restart between the mistake and noticing it meant the recipe was
            gone. One copy of the last good version, beside the file.
        """
        self._scn_save_job = None
        name, path = self._scn_editor_name, self._scn_editor_path
        if name is None or path is None:
            return
        text = self._scn_editor.get("1.0", "end-1c")
        problem = self._scenario_problem(text)
        self._show_scenario_problem(problem)
        if problem is not None:
            # Not a save. The file on disk is still the last thing that parsed.
            return
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    previous = fh.read()
                if previous != text:
                    with open(path + ".bak", "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(previous)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except OSError as exc:
            self.say("action", "scenarios.save_failed", name=name, error=exc)
            return
        self.say("action", "scenarios.saved", name=name)

    @staticmethod
    def _scenario_problem(text: str) -> "str | None":
        """The first thing wrong with this recipe text, or ``None`` if it parses.

        The parser is run over the source with its `ARGS` defaults already
        substituted, exactly as a run would — otherwise a `{squads}` placeholder
        would read as a syntax error in a file that runs perfectly.
        """
        return ActionRunner.problem(text)

    def _show_scenario_problem(self, problem: "str | None") -> None:
        lbl = getattr(self, "_scn_problem_lbl", None)
        if lbl is None:
            return
        try:
            lbl.configure(text="" if problem is None
                          else self.t("scenarios.parse_error", error=problem))
        except tk.TclError:
            pass

    def _on_editor_ctrl_key(self, event):
        """Undo / redo by physical key, so a Cyrillic layout works too."""
        keysym = (event.keysym or "").lower()
        if event.keycode == 90 or keysym in ("z", "cyrillic_ya"):
            try:
                self._scn_editor.edit_undo()
            except tk.TclError:
                pass                        # nothing left to undo
            return "break"
        if event.keycode == 89 or keysym in ("y", "cyrillic_en"):
            try:
                self._scn_editor.edit_redo()
            except tk.TclError:
                pass
            return "break"
        return None                         # other Ctrl+combos pass through

    def _toggle_scenario_loop(self) -> None:
        if self._scn_loop_var.get():
            self._start_scenario_loop()
        else:
            self._stop_scenario_loop()

    def _start_scenario_loop(self) -> None:
        name = self._selected_action_name()
        if name is None:
            self._scn_loop_var.set(False)
            self.say("action", "scenarios.none_selected")
            return
        args = self._scenario_args()
        if args is None:                      # unreadable JSON — already complained
            self._scn_loop_var.set(False)
            return
        try:
            interval = max(5, int(self._scn_interval_var.get()))
        except ValueError:
            interval = 60
        self._scn_loop_stop.clear()
        self.say("action", "scenarios.loop_on", sec=interval)

        def loop() -> None:
            while not self._scn_loop_stop.is_set():
                self.play(name, args)
                # Wait out the interval, but also block while a run is still busy so
                # a slow action never overlaps its own next tick.
                self._scn_loop_stop.wait(interval)
                while self.rt.game.busy and not self._scn_loop_stop.is_set():
                    self._scn_loop_stop.wait(0.5)

        self._scn_loop_thread = threading.Thread(target=loop, daemon=True)
        self._scn_loop_thread.start()

    def _stop_scenario_loop(self) -> None:
        stop = getattr(self, "_scn_loop_stop", None)
        if stop is None:
            return
        stop.set()
        if getattr(self, "_scn_loop_var", None) is not None:
            self._scn_loop_var.set(False)
        self.say("action", "scenarios.loop_off")


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(ScenariosTab))
