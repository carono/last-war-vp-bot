"""The «Таймеры» tab: the errands on a clock, and the ones the wire sets off.

An EDITOR for two lists, and nothing more. The schedule itself is
:mod:`panel.runtime.schedule` — it runs whether or not this tab was ever built, which
is the point: a profile that never opens it still collects its base every hour. What is
here is the grid of rows, the dialog that edits one, and the master switch.

The Scenarios tab's «Повтор» repeats ONE selected action for as long as the panel is
open; a timer is the other half — several errands, each on its own clock, remembered
across restarts. Nothing here drives the game: a row only edits the settings the
scheduler thread reads on its next tick.

Both lists belong to the active profile — every account keeps its own — and both are
edited here: add a row, copy one, delete one, or open one and change its steps, its
args and its title. That is what makes "play the session" a thing the panel can do at
all: the daily list is one errand with ten steps and a period of an hour, and building
it used to mean hand-editing JSON per account.

The triggers below the timers are the wire half: no period, a listener per switched-on
row, and a fire the moment its push crosses. A trigger whose work is another tab's
method is only offered while that tab is in this profile (§3.2) — the schedule decides
that, and the row simply reflects it.
"""
from __future__ import annotations

import json
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .. import timers as timersmod
from .. import triggers as triggersmod
from ..runtime import list_actions
from ..widgets import NumericEntry, numeric_spinbox
from .base import PanelTab


class TimersTab(PanelTab):
    """The two grids, the editor dialog and the master switch."""

    ID = "timers"
    TITLE_KEY = "tab.timers"
    ORDER = 30
    PREFERRED_SIZE = "900x760"
    LOCALE_NS = ("timers", "triggers")
    NEEDS = frozenset({"schedule"})

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._timer_vars: dict = {}     # name -> {"enabled": Var, "interval": Var}
        self._timer_rows: dict = {}     # name -> {"last"/"next" Labels, "box"}
        self._trigger_vars: dict = {}   # name -> enabled Var
        self._trigger_rows: dict = {}   # name -> {"status" Label}
        # A grid of checkbuttons has no selection of its own, so the row label
        # doubles as one — this is which row the editor's buttons act on.
        self._timer_selected = None
        self._timer_grid = None
        self._trigger_grid = None
        self._sched_var = None

    # -- the switches the schedule reads -------------------------------------
    #
    # THE SCHEDULE ASKS THE ROWS, not the other way round: ticking a box or changing a
    # period applies on the next tick with nothing to restart. With this tab switched
    # off in the profile there are no rows, the source answers `None`, and the saved
    # catalogue is what the schedule obeys — which is what keeps it firing without the
    # editor for its list.
    def _timer_widget_config(self):
        if not self._timer_vars:
            return None
        return {name: {"enabled": bool(var["enabled"].get()),
                       "interval_sec": var["interval"].get()}
                for name, var in self._timer_vars.items()}

    def _trigger_widget_config(self):
        if not self._trigger_vars:
            return None
        return {name: bool(var.get()) for name, var in self._trigger_vars.items()}

    # -- the catalogues, under the names the rows have always used -----------
    @property
    def _timer_catalogue(self):
        return self.rt.schedule.timer_catalogue

    @_timer_catalogue.setter
    def _timer_catalogue(self, value) -> None:
        self.rt.schedule.timer_catalogue = value

    @property
    def _trigger_catalogue(self):
        return self.rt.schedule.trigger_catalogue

    @_trigger_catalogue.setter
    def _trigger_catalogue(self, value) -> None:
        self.rt.schedule.trigger_catalogue = value

    # -- lifecycle ------------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Reading a file, not the game — so the rows are right the first time they
        are looked at, whatever happened while nobody was."""
        self._reload_triggers(quiet=True)

    def on_profile_switch(self) -> None:
        """The account's own errands: re-read both lists and redraw. The schedule has
        already re-pointed itself; this is the editor catching up."""
        self._reload_timers(quiet=True)
        self._reload_triggers(quiet=True)

    def on_language_change(self) -> None:
        self._fill_timer_grid()

    def panic(self) -> None:
        """«Стоп всё» stops the schedule — and the switch has to say so, or it would be
        silently dead for the rest of the session with nothing to bring it back."""
        if self._sched_var is not None:
            self._sched_var.set(False)

    def shutdown(self) -> None:
        self.rt.tick.disarm("timer_rows")

    def build(self) -> None:
        """One row per configured errand: switch, period, when it last/next runs.

        The Scenarios tab's «Повтор» repeats *one selected* action for as long as
        the panel is open; a timer is the other half — several errands, each on
        its own clock, remembered across restarts (panel/timers.py). Nothing here
        drives the game directly: a row only edits the settings the scheduler
        thread reads on its next tick.

        The list belongs to the active profile's timers.json — every account keeps
        its own set — but it is EDITED HERE: add a row, copy one, delete one, or
        open one and change its steps, its args and its title. That is what makes
        "play the session" a thing the panel can do at all: the daily list is one
        timer with ten steps and a period of an hour, and building it used to mean
        hand-editing JSON per account. «⟳» still re-reads the file for anything
        edited outside.
        """
        frame = self.tr(ttk.LabelFrame(self.parent, padding=8), "timers.frame")
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        # Rebuilt wholesale by _reload_timers, so the rows live in their own
        # frame with nothing else in it.
        self._timer_grid = ttk.Frame(frame)
        self._timer_grid.pack(fill="x")
        self._fill_timer_grid()

        # -- the editor's buttons ------------------------------------------------
        tools = ttk.Frame(frame)
        tools.pack(fill="x", pady=(10, 0))
        self.tr(ttk.Button(tools, command=self._timer_add),
                 "timers.add").pack(side="left", padx=(0, 4))
        self.tr(ttk.Button(tools, command=self._timer_edit),
                 "timers.edit").pack(side="left", padx=(0, 4))
        self.tr(ttk.Button(tools, command=self._timer_duplicate),
                 "timers.duplicate").pack(side="left", padx=(0, 4))
        self.tr(ttk.Button(tools, command=self._timer_delete),
                 "timers.delete").pack(side="left", padx=(0, 4))
        # The schedule's own master switch. «Стоп всё» stops the scheduler thread,
        # and without something that says so — and puts it back — the schedule would
        # be silently dead for the rest of the session.
        self._sched_var = tk.BooleanVar(value=True)
        self.tr(ttk.Checkbutton(tools, variable=self._sched_var,
                                 command=self._toggle_schedule),
                 "timers.scheduler").pack(side="right")

        # -- the Triggers section (panel/triggers.py) ----------------------------
        # A separate list below the timers: errands driven by a wire event, not a
        # clock. The alliance-help one answers «Помочь всем» the instant a request's
        # push lands. It is a standing order you switch on — no period, no editor — so
        # the section is just checkboxes, the event each listens for, and its status.
        trig_frame = self.tr(ttk.LabelFrame(frame, padding=8), "triggers.frame")
        trig_frame.pack(fill="x", pady=(10, 0))
        self._trigger_grid = ttk.Frame(trig_frame)
        self._trigger_grid.pack(fill="x")
        self._fill_trigger_grid()
        trig_bottom = ttk.Frame(trig_frame)
        trig_bottom.pack(fill="x", pady=(6, 0))
        self.tr(ttk.Label(trig_bottom, foreground="#888", wraplength=600,
                          justify="left"), "triggers.hint").pack(side="left", anchor="w")
        self.tr(ttk.Button(trig_bottom, width=3, command=self._reload_triggers),
                 "timers.reload").pack(side="right", anchor="ne")

        bottom = ttk.Frame(frame)
        bottom.pack(fill="x", pady=(8, 0))
        self.tr(ttk.Label(bottom, foreground="#888", wraplength=600, justify="left"),
                 "timers.hint").pack(side="left", anchor="w")
        self.tr(ttk.Button(bottom, width=3, command=self._reload_timers),
                 "timers.reload").pack(side="right", anchor="ne")

        self._refresh_timer_rows()

    # -- which row is selected ----------------------------------------------
    #
    # A grid of checkbuttons has no selection of its own, so the row label doubles
    # as one: clicking a row's name selects it and the four buttons act on that.
    def _select_timer(self, name: str) -> None:
        self._timer_selected = name
        self._paint_timer_selection()

    def _paint_timer_selection(self) -> None:
        for row_name, row in self._timer_rows.items():
            box = row.get("box")
            if box is None:
                continue
            try:
                box.configure(style="Selected.TCheckbutton"
                              if row_name == self._timer_selected else "TCheckbutton")
            except tk.TclError:
                pass

    def _selected_timer(self):
        """The selected timer, or ``None`` (with a log line saying to pick one)."""
        name = getattr(self, "_timer_selected", None)
        timer = self._timer_catalogue.by_name(name) if name else None
        if timer is None:
            self.say("timer", "timers.none_selected")
        return timer

    def _fill_timer_grid(self) -> None:
        """(Re)draw a row per timer in the current catalogue.

        Scheduled timers only — the wire-driven triggers are their own list, built
        below the timer grid by :meth:`_fill_trigger_grid` (panel/triggers.py).
        """
        grid = self._timer_grid
        for child in grid.winfo_children():
            child.destroy()
        self._timer_vars.clear()
        self._timer_rows.clear()
        grid.columnconfigure(0, weight=1)
        # «последняя попытка» stands where «последний запуск» used to: that column only
        # ever moved on a SUCCESS, so an errand failing every half hour read from here
        # as one nobody had switched on. It is the same reading, plus how it went — and
        # putting it in the old column's place keeps the row inside the window.
        for col, key in enumerate(("timers.col.action", "timers.col.interval",
                                   "timers.col.outcome", "timers.col.next")):
            self.tr(ttk.Label(grid, foreground="#888"), key).grid(
                row=0, column=col, sticky="w", padx=(0, 10), pady=(0, 4))

        # The catalogue IS the settings now: its own enabled/interval_sec are
        # what the row shows, and what the row writes back to.
        config = self._timer_catalogue.default_config()
        for row, timer in enumerate(self._timer_catalogue, start=1):
            item = config[timer.name]
            enabled = tk.BooleanVar(value=bool(item["enabled"]))
            seconds = tk.StringVar(value=str(item["interval_sec"]))
            self._timer_vars[timer.name] = {"enabled": enabled, "interval": seconds}
            box = ttk.Checkbutton(grid, variable=enabled)
            # A configured `title` wins; a built-in falls back to its locale
            # string; a timer added to the JSON without either shows the name it
            # was given there.
            if timer.title:
                box.configure(text=timer.title)
            elif timer.label_key:
                self.tr(box, timer.label_key)
            else:
                box.configure(text=timer.name)
            box.grid(row=row, column=0, sticky="w", pady=2)
            # The label is also the row's selection: a grid of checkbuttons has none
            # of its own, and the editor buttons need to know which row they act on.
            box.bind("<Button-1>", lambda _e, n=timer.name: self._select_timer(n),
                     add="+")
            box.bind("<Double-Button-1>", lambda _e, n=timer.name: (
                self._select_timer(n), self._timer_edit()), add="+")
            numeric_spinbox(grid, from_=timersmod.MIN_INTERVAL_SEC,
                        to=timersmod.MAX_INTERVAL_SEC, width=7,
                        textvariable=seconds).grid(row=row, column=1, sticky="w",
                                                   padx=(0, 10))
            outcome = ttk.Label(grid, foreground="#888", width=20)
            outcome.grid(row=row, column=2, sticky="w", padx=(0, 10))
            nxt = ttk.Label(grid, foreground="#888", width=18)
            nxt.grid(row=row, column=3, sticky="w", padx=(0, 10))
            self.tr(ttk.Button(grid, command=lambda t=timer: self._timer_run_now(t)),
                     "timers.run_now").grid(row=row, column=4, sticky="e")
            # A queued or running errand had no way back: «✕» takes it off the queue.
            self.tr(ttk.Button(grid, width=3,
                                command=lambda t=timer: self._timer_cancel(t)),
                     "timers.cancel").grid(row=row, column=5, sticky="e", padx=(4, 0))
            self._timer_rows[timer.name] = {"next": nxt, "outcome": outcome, "box": box}
        self._bind_timer_autosave()
        self._paint_timer_selection()

    # -- triggers: wire-driven errands, their own list (panel/triggers.py) ---
    def _fill_trigger_grid(self) -> None:
        """(Re)draw a checkbox row per trigger, below the timers.

        A trigger has no period and no editor: it is a standing order you switch on,
        and it answers on its own. So each row is just a switch, the event it listens
        for, and whether a listener is up right now.
        """
        grid = self._trigger_grid
        for child in grid.winfo_children():
            child.destroy()
        self._trigger_vars.clear()
        self._trigger_rows.clear()
        grid.columnconfigure(0, weight=1)
        for col, key in enumerate(("triggers.col.action", "triggers.col.event",
                                   "triggers.col.status")):
            self.tr(ttk.Label(grid, foreground="#888"), key).grid(
                row=0, column=col, sticky="w", padx=(0, 10), pady=(0, 4))
        for row, trig in enumerate(self._trigger_catalogue, start=1):
            enabled = tk.BooleanVar(value=bool(trig.enabled))
            self._trigger_vars[trig.name] = enabled
            box = ttk.Checkbutton(grid, variable=enabled)
            if trig.title:
                box.configure(text=trig.title)
            elif trig.label_key:
                self.tr(box, trig.label_key)
            else:
                box.configure(text=trig.name)
            box.grid(row=row, column=0, sticky="w", pady=2)
            # The wire event a listener waits for, or a short label for a poll check
            # (the raw Lua is unreadable in a narrow column).
            signal = trig.event_pattern if not trig.is_poll else self.t("triggers.poll")
            ttk.Label(grid, foreground="#888", text=signal).grid(
                row=row, column=1, sticky="w", padx=(0, 10))
            status = ttk.Label(grid, foreground="#888", width=14)
            status.grid(row=row, column=2, sticky="w", padx=(0, 10))
            self._trigger_rows[trig.name] = {"status": status}
        for var in self._trigger_vars.values():
            var.trace_add("write", lambda *a: self._save_triggers())

    def _bind_timer_autosave(self) -> None:
        """Persist a ticked box / retyped period, for rows built at any time.

        Called from the row builder rather than from `_install_autosave`, because
        the rows can be rebuilt at any moment by «⟳» or by a profile switch.
        """
        for var in self._timer_vars.values():
            var["enabled"].trace_add("write", lambda *a: self._save_timers())
            var["interval"].trace_add("write", lambda *a: self._save_timers())

    def _save_timers(self) -> None:
        """Write the ticked boxes and typed periods into the profile's timers.json.

        Only those two: the scenario, the args and the title are the operator's text
        and travel through `_write_timer` instead, which writes a whole entry on
        purpose. A ticked box must never be able to rewrite a recipe.
        """
        if getattr(self, "_loading", False) or not self._timer_vars:
            return
        self._timer_catalogue = self._timer_catalogue.with_settings(self.rt.schedule.timer_config())
        timersmod.save_catalogue(self._timer_catalogue, self.rt.profiles.timers_json())

    def _save_triggers(self) -> None:
        """Write the ticked trigger boxes into the profile's triggers.json.

        A trigger's box just changed → save it and reconcile the listeners: the
        watcher brings the newly-on one's ear up and takes a newly-off one's down.
        """
        if getattr(self, "_loading", False) or not self._trigger_vars:
            return
        config = {name: {"enabled": bool(var.get())}
                  for name, var in self._trigger_vars.items()}
        self._trigger_catalogue = self._trigger_catalogue.with_enabled(config)
        triggersmod.save_catalogue(self._trigger_catalogue,
                                   self.rt.profiles.triggers_json())
        self.rt.schedule.triggers.sync()

    # -- add / copy / edit / delete a row ------------------------------------
    #
    # The one feature that makes the bot unattended used to be gated behind
    # hand-editing timers.json per account — the tab's own hint said so. The file
    # format always supported everything below; only the UI was missing.
    def _write_timer(self, catalogue) -> None:
        """Persist a whole catalogue and redraw the rows from it.

        The switches and periods on screen are folded in first: a row edited while
        another row's box was just ticked must not lose the tick.
        """
        self._timer_catalogue = catalogue.with_settings(self.rt.schedule.timer_config())
        timersmod.save_catalogue(self._timer_catalogue, self.rt.profiles.timers_json())
        self._fill_timer_grid()

    def _timer_add(self) -> None:
        """A new errand, empty, named for the operator to fill in."""
        name = self._timer_catalogue.unique_name("errand")
        draft = timersmod.Timer(name=name, scenario=("",),
                               interval_sec=timersmod.DEFAULT_INTERVAL_SEC,
                               enabled=False)
        self._edit_timer_dialog(draft, is_new=True)

    def _timer_duplicate(self) -> None:
        """A copy of the selected row under a free name.

        The name is the id the schedule keys its clock on, so the copy must not
        answer to the original's last-run record — `unique_name` is what guarantees
        that.
        """
        timer = self._selected_timer()
        if timer is None:
            return
        copy = timersmod.Timer(
            name=self._timer_catalogue.unique_name(timer.name),
            scenario=timer.scenario, interval_sec=timer.interval_sec,
            enabled=False,          # a copy starts off: two clocks on one errand is
                                    # rarely what a duplicate was for
            args=dict(timer.args),
            title=timer.title, label_key=None)
        self._write_timer(self._timer_catalogue.replace(copy))
        self._select_timer(copy.name)
        self.say("timer", "timers.log.duplicated",
                  name=timer.name, copy=copy.name)

    def _timer_delete(self) -> None:
        timer = self._selected_timer()
        if timer is None:
            return
        if not messagebox.askyesno(self.t("timers.delete"),
                                   self.t("timers.confirm_delete", name=timer.name),
                                   parent=self):
            return
        self._timer_selected = None
        self._write_timer(self._timer_catalogue.remove(timer.name))
        self.say("timer", "timers.log.deleted", name=timer.name)

    def _timer_edit(self) -> None:
        timer = self._selected_timer()
        if timer is not None:
            self._edit_timer_dialog(timer, is_new=False)

    def _edit_timer_dialog(self, timer, is_new: bool) -> None:
        """The row's whole entry, in a window: name, title, period, steps, args.

        Steps are one per line, because that is what a scenario is — «donate, then
        claim the gifts» is two lines — and a line is either the name of an action
        script or DSL source run as it stands (panel/timers.py says so too). The
        picker beside the box appends a script's name so the thirty-odd recipes do
        not have to be remembered.

        Nothing is written until Save, and Save refuses an entry the scheduler could
        not run: no name, a name already taken by another row, or no steps at all.
        """
        win = tk.Toplevel(self)
        win.title(self.t("timers.editor.window"))
        win.transient(self)
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        name_var = tk.StringVar(value=timer.name)
        title_var = tk.StringVar(value=timer.title or "")
        interval_var = tk.StringVar(value=str(timer.interval_sec))
        args_var = tk.StringVar(value=json.dumps(timer.args, ensure_ascii=False)
                                if timer.args else "")
        for row, (key, var, width) in enumerate((
                ("timers.editor.name", name_var, 28),
                ("timers.editor.title", title_var, 40),
                ("timers.editor.interval", interval_var, 10),
                ("timers.editor.args", args_var, 40))):
            self.tr(ttk.Label(frm), key).grid(row=row, column=0, sticky="w",
                                               padx=(0, 8), pady=3)
            # Only the interval is a number; name/title/args stay free text.
            entry_cls = (NumericEntry if key == "timers.editor.interval"
                         else ttk.Entry)
            entry_cls(frm, textvariable=var, width=width).grid(row=row, column=1,
                                                               sticky="we", pady=3)
        self.tr(ttk.Label(frm, foreground="#888", wraplength=460, justify="left"),
                 "timers.editor.steps_hint").grid(row=4, column=0, columnspan=2,
                                                  sticky="w", pady=(8, 2))
        steps = ScrolledText(frm, height=8, width=56, wrap="none", font=("Consolas", 9))
        steps.grid(row=5, column=0, columnspan=2, sticky="nsew")
        steps.insert("1.0", "\n".join(timer.scenario))
        frm.rowconfigure(5, weight=1)

        # The picker: every blessed action script, appended as a step.
        pick = ttk.Frame(frm)
        pick.grid(row=6, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.tr(ttk.Label(pick), "timers.editor.pick").pack(side="left", padx=(0, 4))
        actions = list_actions()
        pick_var = tk.StringVar()
        pick_combo = ttk.Combobox(pick, textvariable=pick_var, state="readonly",
                                  width=34,
                                  values=[f"{a['name']} — {a['title']}" for a in actions])
        pick_combo.pack(side="left")

        def add_step() -> None:
            idx = pick_combo.current()
            if idx < 0:
                return
            text = steps.get("1.0", "end-1c")
            steps.insert("end", ("\n" if text.strip() else "") + actions[idx]["name"])

        self.tr(ttk.Button(pick, command=add_step),
                 "timers.editor.add_step").pack(side="left", padx=(4, 0))

        problem = ttk.Label(frm, foreground="#c33", wraplength=460, justify="left")
        problem.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def save() -> None:
            name = name_var.get().strip()
            if not name:
                problem.configure(text=self.t("timers.editor.err_name"))
                return
            clash = self._timer_catalogue.by_name(name)
            if clash is not None and name != timer.name:
                problem.configure(text=self.t("timers.editor.err_taken", name=name))
                return
            scenario = tuple(s.strip() for s in steps.get("1.0", "end-1c").splitlines()
                             if s.strip())
            if not scenario:
                problem.configure(text=self.t("timers.editor.err_steps"))
                return
            raw_args = args_var.get().strip()
            args: dict = {}
            if raw_args:
                try:
                    args = json.loads(raw_args)
                except ValueError as exc:
                    problem.configure(text=self.t("timers.editor.err_args", error=exc))
                    return
                if not isinstance(args, dict):
                    problem.configure(text=self.t("timers.editor.err_args",
                                                   error='expected {"name": value}'))
                    return
            # Keep the switch as it stands ON SCREEN, not as the catalogue last saw
            # it: a box ticked a second ago must survive an edit of the same row. A
            # brand-new errand starts off — one nobody has read yet should not fire a
            # minute later.
            row_var = self._timer_vars.get(timer.name)
            enabled = bool(row_var["enabled"].get()) if row_var else bool(timer.enabled)
            edited = timersmod.Timer(
                name=name, scenario=scenario,
                interval_sec=timersmod._as_interval(interval_var.get(),
                                                    timer.interval_sec),
                enabled=enabled,
                args=args, title=title_var.get().strip() or None,
                # The locale key belongs to the BUILT-IN entry of that name; a
                # renamed row is no longer that entry, and keeping it would show a
                # translated label over the wrong errand.
                label_key=timer.label_key if name == timer.name else None)
            catalogue = self._timer_catalogue
            if not is_new and name != timer.name:
                # A rename is a delete plus an add: the name is the record key, so
                # the row starts a fresh clock rather than inheriting the old one's.
                catalogue = catalogue.remove(timer.name)
            win.destroy()
            self._write_timer(catalogue.replace(edited))
            self._select_timer(name)
            self.say("timer", "timers.log.saved", name=name)

        btns = ttk.Frame(frm)
        btns.grid(row=8, column=0, columnspan=2, sticky="we", pady=(10, 0))
        ttk.Button(btns, text=self.t("timers.editor.cancel"),
                   command=win.destroy).pack(side="left")
        ttk.Button(btns, text=self.t("timers.editor.save"),
                   command=save).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())
        win.grab_set()

    # -- the schedule's master switch ---------------------------------------
    def _toggle_schedule(self) -> None:
        """Start or stop the scheduler thread from the tab.

        «Стоп всё» stops it, and without this the schedule would be silently dead
        for the rest of the session — the one failure mode of a panic button.
        """
        if self._sched_var.get():
            self.rt.schedule.start()           # the master switch governs both halves
            self.say("timer", "timers.log.scheduler_on")
        else:
            self.rt.schedule.stop()
            self.say("timer", "timers.log.scheduler_off")

    def _timer_cancel(self, timer) -> None:
        """The row's «✕»: take a WAITING errand back off the queue.

        Three outcomes, and they must read differently: taken off, already running
        (the press is in flight and stopping it mid-call into the game is not on
        offer), and never queued in the first place.
        """
        if self.rt.schedule.timers.cancel(timer.name):
            self.say("timer", "timers.log.cancelled", name=timer.name)
        elif timer.name in self.rt.schedule.timers.pending():
            self.say("timer", "timers.log.already_running", name=timer.name)
        else:
            self.say("timer", "timers.log.not_queued", name=timer.name)

    def _reload_timers(self, quiet: bool = False) -> None:
        """Re-read the profile's timers.json and redraw the rows from it."""
        self.rt.schedule.load_timers()
        if hasattr(self, "_timer_grid"):
            self._fill_timer_grid()
        if not quiet:
            self.say("timer", "timers.log.reloaded", n=len(self._timer_catalogue))

    # Reading a catalogue is panel/runtime/schedule.py's — a profile that shows no
    # Timers tab still has errands, and they still have to be read.

    def _reload_triggers(self, quiet: bool = False) -> None:
        """Re-read the profile's triggers.json, redraw the rows, reconcile listeners."""
        self.rt.schedule.load_triggers()
        self._migrate_autohelp()
        if hasattr(self, "_trigger_grid"):
            self._fill_trigger_grid()
        if getattr(self, "_triggers", None) is not None:
            self.rt.schedule.triggers.sync()
        if not quiet:
            self.say("trigger", "triggers.log.reloaded", n=len(self._trigger_catalogue))

    # The gate, the runner and the errand's live arguments went to the runtime with
    # the rest of the schedule. The four sentinel errands went with them and came out
    # the other side as `TriggerSpec(handler=…)` on the tabs that do the work (§3.2):
    # a trigger whose tab is not in this profile is not offered at all, which the
    # `if timer.name == …` chain could not express.

    # The resource tracker, the inventory repaint and the secret-task re-merge are
    # their own tabs' `TriggerSpec(handler=…)` now (§3.2): each is registered with the
    # schedule by the tab that does the work, and a tab that is not in this profile
    # registers nothing — so its trigger is not offered and nothing listens for it.

    def _timer_run_now(self, timer) -> None:
        """The row's «Запустить» — put the errand on the schedule's own queue.

        Not a thread of its own: every timer script runs single-file on the one
        worker, so a press while another errand is running waits its turn behind
        it instead of driving the game at the same time. The call returns at once,
        so the button never blocks the UI.

        It also goes through the scheduler so a manual run restarts the period:
        pressing the button by hand *is* collecting the base, and the timer must
        not then collect it again a minute later.
        """
        if not self.rt.schedule.timers.request(timer):
            self.say("timer", "timers.log.already_queued", name=timer.name)

    def _refresh_timer_rows(self) -> None:
        """Repaint the "last attempt / next run" columns (and the trigger status); re-armed once a second."""
        if self._timer_rows:
            config = self.rt.schedule.timer_config()
            records = self.rt.schedule.store.records()
            # What is waiting on the schedule's own queue. It was never shown, so an
            # errand queued behind a slow one looked like nothing had happened.
            pending = self.rt.schedule.timers.pending()
            now = time.time()
            for timer in self._timer_catalogue:
                row = self._timer_rows.get(timer.name)
                if row is None:
                    continue
                self._paint_timer_outcome(row, timer.name, records, now)
                due = self._timer_catalogue.next_due(timer, config, records)
                if timer.name in pending:
                    row["next"].configure(text=self.t("timers.queued"))
                elif due is None:
                    row["next"].configure(text=self.t("timers.off"))
                elif due <= now:
                    row["next"].configure(text=self.t("timers.due_now"))
                else:
                    row["next"].configure(
                        text=self.t("timers.in_span", span=self._fmt_span(due - now)))
        self._refresh_trigger_rows()
        self.rt.tick.arm("timer_rows", 1000, self._refresh_timer_rows)

    def _paint_timer_outcome(self, row: dict, name: str, records: dict,
                             now: float) -> None:
        """Say how the last attempt ended — succeeded, failed, or never ran.

        Green / red / grey rather than a word alone: the one thing an operator wants off
        this tab at a glance is whether the schedule is getting anywhere, and an errand
        that fails on a standing condition (the ministry one, while another post is
        held) would otherwise be indistinguishable from one that keeps succeeding — both
        leave the row looking idle between fires.

        *Why* it failed is not here: the reason is a sentence, the column is twenty
        characters, and a label that grows to fit one would push the row's buttons off a
        760-wide window. It goes to the log instead, where the failure is already
        announced (``timers.log.failed``) — carrying the scenario's own FAIL reason
        since :meth:`_run_timer_action` started passing it up.
        """
        label = row.get("outcome")
        if label is None:
            return
        state, when = timersmod.last_attempt(records, name)
        if state == timersmod.ATTEMPT_FAILED:
            text = self.t("timers.outcome.failed", ago=self._fmt_span(now - when))
            colour = "#c0392b"
        elif state == timersmod.ATTEMPT_OK:
            text = self.t("timers.outcome.ok", ago=self._fmt_span(now - when))
            colour = "#2e7d32"
        else:
            text = self.t("timers.outcome.never")
            colour = "#888"
        label.configure(text=text, foreground=colour)

    def _refresh_trigger_rows(self) -> None:
        """Repaint each trigger's status: queued / listening / off."""
        if not self._trigger_rows:
            return
        pending = self.rt.schedule.timers.pending()
        watching = self.rt.schedule.triggers.watching()
        for trig in self._trigger_catalogue:
            row = self._trigger_rows.get(trig.name)
            if row is None:
                continue
            if trig.name in pending:
                row["status"].configure(text=self.t("timers.queued"))
            elif trig.name in watching:
                row["status"].configure(text=self.t("triggers.listening"))
            else:
                row["status"].configure(text=self.t("triggers.off"))

    def _fmt_span(self, seconds: float) -> str:
        """A duration as the rows show it: «45 мин» / «2 ч 5 мин» / «3 дн»."""
        seconds = max(0, int(seconds))
        if seconds < 60:
            # "0 мин" reads like a stopped clock right after a run — say the
            # span is under a minute instead.
            return self.t("timers.span.now")
        if seconds < 3600:
            return self.t("timers.span.min", n=seconds // 60)
        if seconds < 86400:
            return self.t("timers.span.hour", h=seconds // 3600,
                           m=(seconds % 3600) // 60)
        return self.t("timers.span.day", d=seconds // 86400)

    # -- settings page (sub-tabs; SETTINGS_TABS is the whole list) -----------


    def _migrate_autohelp(self) -> None:
        """Carry the retired «Авто-помощь» checkbox onto the `alliance_help` trigger.

        The old per-profile setting was `alliance_autohelp`; a profile that had it on
        should keep answering, so flip the trigger on once (and persist it) and let
        the box's own state in triggers.json own it from then on. Idempotent: enabling
        an already-on trigger changes nothing.
        """
        if not self.rt.settings.values.get("alliance_autohelp"):
            return
        # Consume the flag so this runs ONCE: without clearing it, a user who then
        # unticks the trigger would have it switched back on at the next switch.
        self.rt.settings.values.pop("alliance_autohelp", None)
        self.rt.profiles.save(self.rt.settings.values)
        trig = self._trigger_catalogue.by_name("alliance_help")
        if trig is None or trig.enabled:
            return
        self._trigger_catalogue = self._trigger_catalogue.with_enabled(
            {**self._trigger_catalogue.enabled_config(), "alliance_help": True})
        triggersmod.save_catalogue(self._trigger_catalogue,
                                   self.rt.profiles.triggers_json())
        if hasattr(self, "_trigger_grid"):
            self._fill_trigger_grid()


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(TimersTab))
