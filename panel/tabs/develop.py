r"""The «Develop» tab: the two sniffers, recorded as one session.

Reverse-engineering the game is done by RECORDING: a passive pcap of the wire beside a
tracer that wraps the client's own Lua functions, both running while a thing is done in
the game once. The two halves are started and stopped together and their run files are
kept — or thrown away — as one session with one description, because a capture nobody
labelled is a file nobody can read a week later (`tools/lib/run_output.py`).

It was a checkbutton on the Develop menu, which meant it was in every panel whether or
not the person in front of it had ever reverse-engineered anything. As a tab it is
`DEFAULT_ENABLED = False`: it appears when a profile asks for it and costs nothing when
it does not (docs/research/panel-tabs-refactor.md §10, wave 6).

Nothing here presses anything in the game. The tracer's hooks ARE written into the
client's Lua, so stopping is not a kill: the child is asked to stop, given
`TRACE_GRACEFUL_SEC` to unwrap itself, and the panel restores the hooks by hand if it
did not — a client left with the tracer's wrappers on is a client that has to be
restarted.
"""
from __future__ import annotations

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
from ..runtime.paths import TOOLS, TOOLS_LIB, repo_rel
from ..widgets import font as ui_font
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


class DevelopTab(PanelTab):
    """Start the pair, watch them come up, stop them, keep or throw the session away."""

    ID = "develop"
    TITLE_KEY = "tab.develop"
    ORDER = 900
    #: Off unless a profile asks: most people never record anything.
    DEFAULT_ENABLED = False
    PREFERRED_SIZE = "760x520"
    LOCALE_NS = ("develop", "trace", "sniff")
    NEEDS = frozenset({"daemon", "children"})

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
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

    # -- UI -------------------------------------------------------------------
    def build(self) -> None:
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

    # -- lifecycle -------------------------------------------------------------
    def panic(self) -> None:
        """«Стоп всё»: the recording stops like any other standing thing.

        It is the one place stopping matters most — the tracer's hooks are in the
        client's Lua and the stop is what takes them back out.
        """
        self._sniff_var.set(False)
        self._stop_sniff()

    def shutdown(self) -> None:
        self._stop_sniff()
        for name in ("sniff_ready", "sniff_flush"):
            self.rt.tick.disarm(name)

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
        """
        if self._sniff_proc is None and self._trace_proc is None:
            self.post(lambda: self._sniff_var.set(False))
            # Both children died on their own (the game restarted, tshark lost
            # the interface) — the session is over just as surely as after a
            # Stop, so it gets the same save/delete prompt. Whichever path runs
            # first empties _sniff_files, so the other one finds nothing to ask
            # about; both land on the Tk thread, so they cannot interleave.
            self.rt.tick.arm("sniff_flush", SNIFF_FLUSH_MS, self._finish_sniff_session)

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
        win.transient(self)
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
        placeholder = self.t("develop.run.placeholder")
        showing = {"placeholder": True}
        text.insert("1.0", placeholder)
        text.configure(foreground="#888")

        def clear_placeholder(_event=None) -> None:
            if showing["placeholder"]:
                showing["placeholder"] = False
                text.delete("1.0", "end")
                text.configure(foreground="")

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

    # -- jump routing (shared by the entry button and clickable coords) -----


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(DevelopTab))
