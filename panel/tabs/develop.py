r"""The «Develop» tab: two tools for working on the bot itself, one page.

**The sniffer pair**, recorded as one session. Reverse-engineering the game is done by
RECORDING: a passive pcap of the wire beside a tracer that wraps the client's own Lua
functions, both running while a thing is done in the game once. The two halves are
started and stopped together and their run files are kept — or thrown away — as one
session with one description, because a capture nobody labelled is a file nobody can
read a week later (`tools/lib/run_output.py`).

It was a checkbutton on the Develop menu, which meant it was in every panel whether or
not the person in front of it had ever reverse-engineered anything. As a tab it is
`DEFAULT_ENABLED = False`: it appears when a profile asks for it and costs nothing when
it does not (docs/research/panel-tabs-refactor.md §10, wave 6).

Nothing here presses anything in the game. The tracer's hooks ARE written into the
client's Lua, so stopping is not a kill: the child is asked to stop, given
`TRACE_GRACEFUL_SEC` to unwrap itself, and the panel restores the hooks by hand if it
did not — a client left with the tracer's wrappers on is a client that has to be
restarted.

**The list of `actions/*.md`**, an editor for one, and the run. Each
`src/lastwar_bot/actions/*.md` is one runnable ability — which is the whole point of
`CLAUDE.md`'s rule — and this is where a person picks one, reads it, fixes it and
presses it. Nothing here knows anything about the game either: the run goes through
`rt.play_async`, the same door the shell relaunches the client with.

It used to be its own tab, always on — every profile carried a way to run its own
scripts. It joined «Develop» instead of staying separate (task #1240): writing and
fixing a `TAP`/`LUA`/`GAME` recipe is exactly the same "working on the bot" as
recording a sniffer session, not something the person farming with an unmodified set
of actions needs open by default. A profile that already had the standalone tab
switched on keeps the merged one switched on too — `SettingsBinder.tab_list` /
`tab_config` in `panel/runtime/settings.py` carry both the visibility and the
remembered script/args/interval across the merge, so nobody loses what they had.

**This list is a door for the person WRITING a recipe, never the only door to one**
(task #1247). Because the tab is off unless a profile asks for it, an ability whose only
button is here is an ability an ordinary panel does not have — so every shipped
`actions/*.md` also has a press on the tab its theme belongs to: «Чеклист» for the day's
errands, «Ралли», «Секретки», «Командный пункт» for the ones that need a target chosen
first. `tests/test_scenario_homes.py` fails on a scenario that has no home outside this
file, and it does not accept a timer or a trigger as one — running by itself on a clock
is not a way for anybody to say «сделай это сейчас».

Three things about the scenario half worth keeping straight:

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
import re
import tempfile
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

# The runtime FIRST: importing it is what puts tools/ and tools/lib on sys.path, and
# the three bare-name modules below live there.
from ..runtime import ActionRunner, list_actions
from ..runtime.paths import TOOLS, TOOLS_LIB, repo_rel
from ..widgets import font as ui_font, numeric_spinbox
from .base import PanelTab

import lua_client       # noqa: E402  (the warm daemon, to unwrap the tracer's hooks)
import lua_trace        # noqa: E402  (RESTORE_CHUNK)
import run_notes        # noqa: E402  (keep/discard a sniffer run + its description)

#: The two halves of a recording: the wire, and the client's own Lua.
TRAFFIC_SNIFFER = os.path.join(TOOLS_LIB, "live_sniffer.py")
FUNCTION_SNIFFER = os.path.join(TOOLS, "lua_trace.py")

#: ANSI colour codes a child's output carries — stripped before a line is read.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# How long to wait for both halves to report "ready" before saying so in the log.
# Measured on this machine: capture is live ~1 s in, the Lua hooks ~2 s in with a warm
# daemon and noticeably later when it has to attach first — so the cap is generous, it
# only exists to break a silent wait. (The knob is `sniff_ready_timeout` in Settings.)
#
# Pause between "the session is over" and the save/delete prompt, so the last lines of
# the killed children have travelled through their reader threads (the run file paths
# arrive that way) and the files are closed before the dialog offers to delete them.
SNIFF_FLUSH_MS = 600

# How long to wait for the tracer to stop on its own after the --stop-flag is dropped,
# before hard-killing it (#1084). Its tail loop sleeps 0.3 s, so ~1.5 s leaves room for
# a couple of passes plus its restore round-trip; longer only delays the Stop when the
# child is wedged.
TRACE_GRACEFUL_SEC = 1.5

# How long the editor waits after the last keystroke before writing the file. Long
# enough that a burst of typing is one write, short enough that a run started right
# after an edit reads what is on screen (and a run flushes first anyway, so this is
# about disk chatter, not correctness).
SAVE_DELAY_MS = 1000
#: Marks the row of the script that is running right now.
RUNNING_MARK = "▶"
#: Marks a row that came out of actions/dev/ — experimental, shown only on request.
DEV_MARK = "⚙ "


class DevelopTab(PanelTab):
    """Record the sniffer pair, and list/edit/run/repeat the `actions/*.md` scripts."""

    ID = "develop"
    TITLE_KEY = "tab.develop"
    ORDER = 900
    #: Off unless a profile asks: most people never record anything, and running an
    #: unmodified set of actions does not need this page open either — the timers and
    #: the other tabs already do that without it.
    DEFAULT_ENABLED = False
    PREFERRED_SIZE = "860x900"
    LOCALE_NS = ("develop", "trace", "sniff", "scenarios", "cmd")
    NEEDS = frozenset({"daemon", "children", "actions"})
    LEGACY_KEYS = {k: k for k in ("scenario_selected", "scenario_args",
                                  "scenario_interval")}

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        # -- the sniffer pair --
        self._sniff_proc = None       # the traffic sniffer
        self._trace_proc = None       # the Lua-function tracer
        self._sniff_ready: dict = {}  # per-half readiness: None pending / True / False
        self._sniff_t0 = 0.0          # when the pair was launched (for "ready in Ns")
        self._sniff_label = ""        # label typed at the start of this session
        self._sniff_files: dict = {}  # kind -> run file each child reported opening;
                                      # emptied by the save/delete prompt that closes a
                                      # session, which is what makes it fire once
        self._sniff_var = tk.BooleanVar(master=rt.root, value=False)
        self._status_var = tk.StringVar(master=rt.root, value="")
        # -- the scenario runner --
        self._cancel = None            # threading.Event of the run in flight, else None

    # -- UI -------------------------------------------------------------------
    def build(self) -> None:
        """The sniffer pair's toggle, then the scenario list/editor/runner below it."""
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                "tab.develop").pack(side="left")

        box = self.tr(ttk.LabelFrame(self.parent, padding=8), "develop.sniff.frame")
        box.pack(fill="x", padx=10, pady=(0, 8))
        self.tr(ttk.Checkbutton(box, variable=self._sniff_var,
                                command=self._toggle_sniff),
                "develop.sniff.toggle").pack(anchor="w")
        ttk.Label(box, textvariable=self._status_var, foreground="#888").pack(
            anchor="w", pady=(6, 0))
        self.tr(ttk.Label(self.parent, foreground="#888", wraplength=660,
                          justify="left"), "develop.hint").pack(
            anchor="w", padx=10, pady=(0, 10))

        self._build_scenarios()

    def _build_scenarios(self) -> None:
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

    # -- lifecycle -------------------------------------------------------------
    def panic(self) -> None:
        """«Стоп всё»: the recording stops, and any run or loop in flight halts.

        The recording matters most here — the tracer's hooks are in the client's
        Lua and the stop is what takes them back out. A running or looping
        scenario is asked to halt at its next step, same as its own Stop button.
        """
        self._was_sniffing = bool(self._sniff_var.get())
        self._sniff_var.set(False)
        self._stop_sniff()
        self._stop_scenario_loop()
        self._stop_scenario()

    def resume(self) -> None:
        """«Включить обратно»: the recording resumes if it was recording.

        The scenario and its loop do NOT: a run that was asked to halt has halted, and
        starting it again is a press, not an undo.
        """
        if getattr(self, "_was_sniffing", False):
            self._was_sniffing = False
            self._sniff_var.set(True)

    def shutdown(self) -> None:
        # A debounced edit is still pending for up to a second — write it before the
        # window goes, or the last thing typed is the thing that is lost.
        self.flush_save()
        self._stop_scenario_loop()
        self._stop_sniff()
        for name in ("sniff_ready", "sniff_flush"):
            self.rt.tick.disarm(name)

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

    def _sniff_timeout(self) -> float:
        return self.rt.settings.opt_float("sniff_ready_timeout", low=1.0, high=600.0)

    def _trace_filter(self) -> str:
        return self.rt.settings.opt_str("trace_filter")

    def _ask_run_label(self) -> "str | None":
        """Ask what this sniffer run is about; returns the label, or None if cancelled.

        A run file is named by its start time alone, which says nothing about
        what was being captured — the label is what makes a directory of them
        readable later (see tools/lib/run_output.py). Empty input is a valid
        answer (no label); only Cancel aborts the launch, which is why "" and
        None must stay distinguishable here.
        """
        return simpledialog.askstring(self.t("develop.label.title"),
                                      self.t("develop.label.prompt"), parent=self.rt.root)

    def _toggle_sniff(self) -> None:
        """One menu entry, both sniffers: on → start the pair, off → stop the pair."""
        if self._sniff_var.get():
            self._start_sniff()
        else:
            self._stop_sniff()

    def _start_sniff(self) -> None:
        """Ask for one label, then start the traffic sniffer and the Lua tracer.

        The label is asked ONCE and passed to both children so a session's two
        run files carry the same name. If only one of the two comes up the
        toggle stays on — a half-running session is still worth watching — and
        the log says which half is missing; only a total failure flips it back.
        """
        if self._sniff_proc is not None or self._trace_proc is not None:
            return
        label = self._ask_run_label()
        if label is None:
            self._sniff_var.set(False)
            return
        label_args = ["--label", label] if label.strip() else []

        # Neither child is capturing when its pid appears: npcap needs ~1 s to
        # open the interfaces and the Lua hooks land ~2 s in (more with a cold
        # daemon). Both now print a readiness marker; collect them and say ONE
        # word when the pair is actually recording — acting before that quietly
        # loses the frames the run was started for.
        self._sniff_ready = {}
        self._sniff_t0 = time.time()
        self._sniff_label = label
        self._sniff_files = {}

        self.say("traffic", "log.traffic.starting")
        self._sniff_proc = self.rt.children.spawn_raw(
            [self.rt.children.python(), "-u", TRAFFIC_SNIFFER] + label_args, "traffic")
        if self._sniff_proc is not None:
            self._sniff_ready["traffic"] = None
            self.say("traffic", "log.traffic.started", pid=self._sniff_proc.pid)
            threading.Thread(target=self._sniff_reader, args=(self._sniff_proc,),
                             daemon=True).start()

        # No --filter and no --dedup: the recording on disk must be COMPLETE. A
        # capture filter (the old `--filter SFS`) trimmed the file to the wire and hid
        # every UI/Manager call — the exact blind spot that made past trace analyses
        # wrong. --dedup is no good either: it keeps only the FIRST call of each name,
        # so opening a window, picking an amount, confirming and collecting lands as
        # one click and one message, the repeats gone at write time. So the child runs
        # unfiltered — every call, with full args, into results/traces/. TRACE_FILTER
        # survives only as the panel LOG's display filter (see `_trace_show`), so the
        # Tk widget stays readable while the file keeps everything.
        self.say("trace", "log.trace.starting", filter=self._trace_filter())
        # A graceful-stop flag path (task #1084): _stop_sniff drops this file so the
        # tracer breaks its loop and runs its own restore + closes the trace file,
        # rather than being hard-killed. Unique per run so two runs never share one.
        self._trace_stop_flag = os.path.join(
            tempfile.gettempdir(), f"lw_trace_stop_{os.getpid()}_{int(time.time())}.flag")
        try:
            os.path.exists(self._trace_stop_flag) and os.remove(self._trace_stop_flag)
        except OSError:
            pass
        self._trace_proc = self.rt.children.spawn_raw(
            [self.rt.children.python(), "-u", FUNCTION_SNIFFER,
             "--stop-flag", self._trace_stop_flag] + label_args,
            "trace")
        if self._trace_proc is not None:
            self._sniff_ready["trace"] = None
            self.say("trace", "log.trace.started", pid=self._trace_proc.pid)
            threading.Thread(target=self._trace_reader, args=(self._trace_proc,),
                             daemon=True).start()

        if self._sniff_proc is None and self._trace_proc is None:
            self._sniff_var.set(False)
            return
        self.say("sniff", "log.sniff.waiting")
        self.rt.tick.arm("sniff_ready", int(self._sniff_timeout() * 1000),
                         self._sniff_ready_watchdog)

    def _mark_sniff_ready(self, part: str, ok: bool) -> None:
        """Record one half's verdict; announce as soon as both have reported.

        `self._sniff_ready` holds None until a half reports, so a failure is a
        distinct outcome from "still starting" — otherwise a dead tracer would
        either be announced as ready or block the announcement forever.
        """
        state = self._sniff_ready
        if state.get(part, "gone") is not None:      # unknown part, or already reported
            return
        state[part] = ok
        if any(v is None for v in state.values()):
            return
        dt = time.time() - self._sniff_t0
        live = [p for p, v in state.items() if v]
        if len(live) == len(state):
            self.say("sniff", "log.sniff.ready", sec=f"{dt:.1f}")
        elif live:
            self.say("sniff", "log.sniff.partial", sec=f"{dt:.1f}",
                      live=", ".join(live))
        else:
            self.say("sniff", "log.sniff.not_ready", sec=f"{dt:.1f}")

    def _sniff_ready_watchdog(self) -> None:
        """Never leave the log on "жду готовности" if a marker never arrives."""
        if self._sniff_proc is None and self._trace_proc is None:
            return                                   # session already over
        pending = [p for p, v in self._sniff_ready.items() if v is None]
        if pending:
            self.say("sniff", "log.sniff.unconfirmed",
                      sec=f"{self._sniff_timeout():.0f}", pending=", ".join(pending))

    def _note_run_file(self, kind: str, line: str, marker: str) -> None:
        """Remember the run file a child says it opened (`marker` precedes the path).

        The path is only ever announced in the child's own output, so this is
        where the session learns what it is recording — and the save/delete
        prompt at the end has nothing to offer without it.
        """
        _head, sep, path = _ANSI.sub("", line).partition(marker)
        path = path.strip()
        if sep and path:
            self._sniff_files[kind] = path

    def _sniff_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                self.rt.put(f"[traffic] {line}")
                if line.startswith("transcript:"):
                    self._note_run_file("traffic", line, "transcript:")
                if "CAPTURE READY" in line:
                    self._mark_sniff_ready("traffic", True)
                elif "CAPTURE FAILED" in line:
                    self._mark_sniff_ready("traffic", False)
        except Exception:
            pass
        if self._sniff_proc is proc:      # ended on its own, not via _stop_sniff
            self.say("traffic", "log.traffic.ended")
            self._sniff_proc = None
            self._mark_sniff_ready("traffic", False)  # died before reporting: nothing captured
            self._sync_sniff_var()

    def _trace_show(self, line: str) -> bool:
        """Should this tracer line reach the panel's log widget?

        The trace FILE is complete — the child writes every call to it regardless of
        this. The Tk log, though, would drown in an unfiltered trace and freeze the
        panel, so only the `XSCALL` call lines whose name matches the display filter
        (TRACE_FILTER, UI-only) are shown. Everything else — the `[lua_trace]` status
        lines, the `XSTRACE` install/restore summaries, the readiness and run-file
        markers — is low-volume and always shown, and the session's bookkeeping rides
        on it. An empty filter shows everything (the operator asked to see it all).
        """
        if "XSCALL" not in line:
            return True
        keys = [k.strip() for k in (self._trace_filter() or "").split(",") if k.strip()]
        if not keys:
            return True
        return any(k in line for k in keys)

    def _trace_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                # The file keeps every line (the child writes it); the panel log shows
                # only what the display filter lets through, so an unfiltered recording
                # cannot freeze the Tk widget.
                if self._trace_show(line):
                    self.rt.put(f"[trace] {line}")
                if "trace file:" in line:
                    self._note_run_file("trace", line, "trace file:")
                if "TRACE READY" in line:
                    self._mark_sniff_ready("trace", True)
                elif "TRACE FAILED" in line:
                    self._mark_sniff_ready("trace", False)
        except Exception:
            pass
        if self._trace_proc is proc:      # ended on its own, not via _stop_sniff
            self.say("trace", "log.trace.ended")
            self._trace_proc = None
            self._mark_sniff_ready("trace", False)   # died before reporting: no hooks
            self._sync_sniff_var()

    def _sync_sniff_var(self) -> None:
        """Untick the shared toggle once BOTH children are gone.

        Either child may die on its own (the game restarts, tshark loses the
        interface). While the other one still runs the session is live, so the
        checkmark must stay — it is the pair's state, not one process's.

        CALLED FROM A READER THREAD, so everything it does goes over `post`, in one
        callable. `tick.arm` is not bookkeeping — it is `widget.after`, the very Tk
        call a worker must not make: from here it blocks on the event loop, and while
        the window is pumping by hand it raises «main thread is not in main loop» and
        kills the reader that made it (#1226, panel/runtime/tick.py). Armed on the Tk
        thread it also cannot race the Stop path's own arm — one chain per name.
        """
        if self._sniff_proc is None and self._trace_proc is None:
            def close_out() -> None:
                self._sniff_var.set(False)
                # Both children died on their own (the game restarted, tshark lost
                # the interface) — the session is over just as surely as after a
                # Stop, so it gets the same save/delete prompt. Whichever path runs
                # first empties _sniff_files, so the other one finds nothing to ask
                # about; both land on the Tk thread, so they cannot interleave.
                self.rt.tick.arm("sniff_flush", SNIFF_FLUSH_MS,
                                 self._finish_sniff_session)

            self.post(close_out)

    def _stop_sniff(self) -> None:
        proc, self._sniff_proc = self._sniff_proc, None
        if proc is not None:
            self.say("traffic", "log.traffic.stopped")
            try:
                proc.terminate()
            except Exception:
                pass
        proc, self._trace_proc = self._trace_proc, None
        if proc is not None:
            self.say("trace", "log.trace.stopped")
            # Ask the tracer to stop GRACEFULLY first (task #1084): drop its
            # --stop-flag so it breaks its tail loop and runs its own atexit/finally —
            # restore()ing the ~8700 wrapped Lua functions and closing the trace file.
            # A hard proc.terminate() (TerminateProcess on Windows) runs NEITHER, which
            # is why the hooks used to stay live in the VM and keep lagging the game
            # after a sniff (#1086). All of it — the wait, the fallback hard kill, and
            # an idempotent daemon-side RESTORE_CHUNK as the safety net — runs off the
            # Tk thread so Stop never freezes the UI.
            flag = getattr(self, "_trace_stop_flag", None)
            threading.Thread(target=self._graceful_stop_trace, args=(proc, flag),
                             daemon=True).start()

        # Ask what this run was, once the killed children have let go of their
        # files. The delay is not about buffering (both write line-buffered) but
        # about the last lines still travelling through the reader threads — the
        # traffic child announces its transcript path early, the tracer's «trace
        # file:» line can still be in flight when a very short run is stopped.
        self.rt.tick.arm("sniff_flush", SNIFF_FLUSH_MS, self._finish_sniff_session)

    # -- end of a sniffer session: keep it with a description, or drop it ----
    def _finish_sniff_session(self) -> None:
        """Close the session out: prompt to keep (with a description) or delete.

        Runs once per session — it takes the recorded paths, so a second call
        (Stop and the children's own exit both lead here) finds nothing left.
        A session that opened no file at all is closed silently: there is
        nothing to describe and nothing to delete.
        """
        files, self._sniff_files = self._sniff_files, {}
        label, self._sniff_label = self._sniff_label, ""
        files = {k: p for k, p in files.items() if p and os.path.exists(p)}
        if not files:
            return
        seconds = max(0.0, time.time() - self._sniff_t0) if self._sniff_t0 else 0.0
        self._ask_run_outcome(files, label, seconds)

    def _ask_run_outcome(self, files: dict, label: str, seconds: float = 0.0) -> None:
        """The post-run dialog: a description field, Save and Delete.

        Both answers are worth having. A kept run needs the description — the
        two files say which Lua fired and what crossed the wire, never which
        buttons the operator pressed or what changed on screen, and that is the
        context the analysis starts from (docs/skills/sniff.md §8.4). A run that
        recorded the wrong thing is noise in a directory that is read by hand,
        so deleting it is one click rather than a shell detour.

        Closing the window with its X keeps the files: losing a recording must
        take a deliberate press, never a stray one.
        """
        paths = [files[k] for k in ("trace", "traffic") if k in files]
        win = tk.Toplevel(self.rt.root)
        win.title(self.t("develop.run.title"))
        # `self` is a PanelTab, NOT a widget: Tk resolves a master by window path, so
        # `transient(self)` raises «bad window path name» right here — after the
        # Toplevel exists and before anything is packed into it, which is exactly the
        # empty modal it produced (#1235). The window a dialog belongs to is rt.root.
        win.transient(self.rt.root)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)

        shown = label.strip() or self.t("develop.run.nolabel")
        ttk.Label(frm, text=self.t("develop.run.header", label=shown),
                  font=("", 10, "bold")).pack(anchor="w")
        # What was actually recorded: how long, how much, and where it lies. The
        # counts are what tells a real run from an empty one — a transcript of
        # nothing but keepalives still weighs kilobytes.
        ttk.Label(frm, foreground="#888",
                  text=self.t("develop.run.duration",
                               sec=f"{seconds:.0f}")).pack(anchor="w")
        for kind in ("trace", "traffic"):
            path = files.get(kind)
            if path:
                ttk.Label(frm, foreground="#888",
                          text=self._run_file_caption(kind, path)).pack(anchor="w")
        ttk.Label(frm, text=self.t("develop.run.prompt"), wraplength=520,
                  justify="left").pack(anchor="w", pady=(10, 2))
        text = ScrolledText(frm, height=4, width=64, wrap="word")
        text.pack(fill="both", expand=True)
        text.focus_set()

        # Placeholder: greyed prompt text that is NOT an answer. A widget-level
        # binding runs before the Text class binding that inserts the character,
        # so the first keypress empties the box and the typing lands in a clean
        # one. `showing` — not the widget's colour — is what `save()` trusts:
        # the placeholder must never be storable as a description.
        # The colour to put BACK is read off the widget before it is greyed, because
        # `foreground=""` is not "the default" to Tk — a Text has no empty colour and
        # raises «unknown color name ""» from inside the keypress that clears the
        # placeholder, leaving what the person is typing grey (#1235).
        placeholder = self.t("develop.run.placeholder")
        showing = {"placeholder": True}
        typed_fg = text.cget("foreground")
        text.insert("1.0", placeholder)
        text.configure(foreground="#888")

        def clear_placeholder(_event=None) -> None:
            if showing["placeholder"]:
                showing["placeholder"] = False
                text.delete("1.0", "end")
                text.configure(foreground=typed_fg)

        text.bind("<Key>", clear_placeholder)
        text.bind("<Button-1>", clear_placeholder)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))

        def save() -> None:
            typed = text.get("1.0", "end").strip()
            description = "" if showing["placeholder"] or typed == placeholder else typed
            win.destroy()
            self._save_run_note(paths, label, description)

        def discard() -> None:
            if not messagebox.askyesno(self.t("develop.run.confirm_title"),
                                       self.t("develop.run.confirm", label=shown),
                                       parent=win):
                return
            win.destroy()
            gone = run_notes.discard_run(paths)
            self.say("sniff", "log.sniff.discarded", n=len(gone))

        ttk.Button(btns, text=self.t("develop.run.discard"),
                   command=discard).pack(side="left")
        ttk.Button(btns, text=self.t("develop.run.save"),
                   command=save).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", save)
        win.bind("<Control-Return>", lambda e: save())
        win.grab_set()

    def _save_run_note(self, paths: list, label: str, description: str) -> None:
        """Keep the run; write the description beside every file of it."""
        if not description:
            self.say("sniff", "log.sniff.kept_bare")
            return
        try:
            written = run_notes.write_note(paths, description, label=label)
        except Exception as exc:      # noqa: BLE001  (a note must never break the panel)
            self.say("sniff", "log.sniff.note_failed", error=exc)
            return
        names = ", ".join(repo_rel(p) for p in written)
        self.say("sniff", "log.sniff.kept", path=names or "—")

    def _run_file_caption(self, kind: str, path: str) -> str:
        """One line of the dialog's info block: path, size and what is inside."""
        stats = run_notes.run_stats(path)
        size = stats["size"]
        human = f"{size / 1024:.0f} KB" if size >= 1024 else f"{size} B"
        return self.t(f"develop.run.file.{kind}", path=repo_rel(path),
                       size=human, records=stats["records"])

    def _graceful_stop_trace(self, proc, flag) -> None:
        """Stop the tracer cleanly, then make sure the VM is unhooked (off the Tk thread).

        The order is belt-and-suspenders (task #1084):

          1. drop the ``--stop-flag`` file so the tracer breaks its own loop and runs
             ``restore()`` + closes its trace file — the clean exit a hard kill skips;
          2. give it a moment; if it has not gone, ``terminate()`` it (hard kill);
          3. either way run the idempotent ``RESTORE_CHUNK`` over the daemon — it
             reports "nothing installed" when the child already cleaned up, so a
             redundant restore is harmless, and a genuinely-missed one is caught.
        """
        if flag:
            try:
                with open(flag, "w", encoding="utf-8") as fh:
                    fh.write("stop")             # its existence is the whole signal
            except OSError:
                flag = None
            deadline = time.time() + TRACE_GRACEFUL_SEC
            while time.time() < deadline:
                if proc.poll() is not None:
                    break                        # it exited on its own — restore ran
                time.sleep(0.1)
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:                    # noqa: BLE001 — already gone is fine
                pass
        self._restore_trace_hooks()
        if flag:
            try:
                os.remove(flag)
            except OSError:
                pass

    def _restore_trace_hooks(self) -> None:
        """Unwrap the lua_trace hooks left in the game VM after a hard Stop.

        Runs off the Tk thread: a restore round-trips the daemon and settles
        ~1.5 s. The tracer's own restore retries because the default (flood)
        mode can bury the confirmation line in Player.log; the panel only ever
        launches --dedup, which does not flood, so a couple of attempts suffice.
        get_evaluator() uses the warm daemon when it is up and falls back to a
        fresh local LuaEval otherwise, so this still works with no daemon as
        long as the game is alive (and if it is dead, there are no hooks to
        clear).
        """
        try:
            ev = lua_client.get_evaluator(port=self.rt.game.port())
        except Exception as exc:      # noqa: BLE001
            self.say("trace", "log.trace.no_evaluator", error=exc)
            return
        try:
            for attempt in range(3):
                out = ev.run(lua_trace.RESTORE_CHUNK, marker="XSTRACE", settle=1.5 + attempt)
                if any("XSTRACE restored" in ln for ln in out):
                    self.say("trace", "log.trace.unhooked", detail="; ".join(out))
                    return
            self.say("trace", "log.trace.unhook_unconfirmed")
        except Exception as exc:      # noqa: BLE001  (teardown must never crash)
            self.say("trace", "log.trace.unhook_failed", error=exc)
        finally:
            try:
                ev.close()
            except Exception:
                pass

    # -- scenario list / run / loop -------------------------------------------

    def _open_reference(self) -> None:
        """Ask whoever holds the DSL command line to show the `TAP` vocabulary."""
        self.rt.bus.publish("cmd.reference")

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
    raise SystemExit(run_tab(DevelopTab))
