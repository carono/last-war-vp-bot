r"""One child process, streamed into the panel's log — the shape all the monitors share.

Four of the panel's features are the same forty lines: spawn a Windows-Python child,
read its stdout line by line on a thread, put each line in the log with a tag, and
untick the checkbox when it dies. The secret-task capture, the rally monitor, the
alliance auto-help watcher and the chat reader each had their own copy
(``_start_x`` / ``_x_reader`` / ``_stop_x``), and every fix — utf-8 on the pipe, «no
console window», "did it start at all" — had to be made four times or was made
three.

:class:`ChildMonitor` is that shape once. What differs between the four becomes
arguments:

  * ``cmd``      — the command, already built (each feature knows its own flags).
  * ``tag``      — the ``[secret]`` / ``[rally]`` prefix its lines are logged under.
  * ``on_line``  — what to do with a line, when a plain "log it" will not do: the
                   secret capture filters and records, the chat reader parses JSON
                   into a queue. Returning ``False`` swallows the line (it has been
                   dealt with); returning ``None``/``True`` logs it as usual.
  * ``on_exit``  — run when the child has gone *on its own* (not via :meth:`stop`),
                   which is what unticks the checkbox.
  * ``on_spawn`` — run the moment the child exists, with this monitor. The factory
                   (`panel/runtime/children.py`) uses it to take ownership: the process
                   only has a pid once it has started, and something has to know the
                   pid for the panel to be able to end it at shutdown (#1212).

The child is always launched the same way, and that is the point: unbuffered, utf-8
forced on the pipe (a Windows child's piped stdout otherwise falls back to the ANSI
code page and its em-dashes arrive as ``�``), stderr folded into stdout so a
traceback lands in the log instead of nowhere, and no console window.

Nothing here imports Tk. The panel passes in ``log`` and a ``schedule`` callable
(its own ``after``), so every widget touch still happens on the Tk thread while this
module stays a plain object a test can drive with two lambdas.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

# CREATE_NO_WINDOW: a child spawned from a windowed process would otherwise flash
# its own console. Same constant the panel uses for everything else it launches.
NO_WINDOW = 0x08000000


class ChildMonitor:
    """A background child whose output is the panel's log.

    Not restartable: one monitor object is one run of the child. The panel keeps a
    slot per feature and puts a fresh monitor in it, which is what makes "is it
    running" a plain ``is not None`` test on the slot instead of a flag that can
    disagree with the process.
    """

    def __init__(self, cmd: list, tag: str, *, log, cwd: str,
                 on_line=None, on_exit=None, schedule=None, env=None,
                 capture_stderr: bool = True, on_spawn=None) -> None:
        self.cmd = list(cmd)
        self.tag = tag
        self.proc: "subprocess.Popen | None" = None
        self._log = log
        self._cwd = cwd
        self._on_line = on_line
        self._on_exit = on_exit
        self._on_spawn = on_spawn
        self._schedule = schedule
        # The panel supplies this (it carries LW_DAEMON_PORT, so a child drives the
        # same client the panel does). The fallback keeps a bare ChildMonitor usable.
        self._env = env
        self._capture_stderr = capture_stderr
        # Set by stop(): tells the reader thread that the child's death was asked
        # for, so it does not report it as one and does not run on_exit.
        self._stopping = False
        self._thread: "threading.Thread | None" = None
        #: PROOF OF LIFE (#1416). A capture child that has gone deaf is still a running
        #: process with a tidy log: nothing about `alive` can tell «слушает и молчит»
        #: from «слушает и слышит». Its output can — every sniffer in this repo prints a
        #: progress line as it works — so the reader counts what comes past and stamps
        #: when. `time.monotonic`, and `0.0` for «not a line yet».
        self.lines = 0
        self.last_line_at = 0.0

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> bool:
        """Launch the child and start reading it. ``False`` if it would not start."""
        env = self._env or dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            self.proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT if self._capture_stderr else subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                cwd=self._cwd, env=env, creationflags=NO_WINDOW)
        except Exception as exc:      # noqa: BLE001 — a failed launch is a log line
            self._log(f"[{self.tag}] ошибка запуска: {exc}")
            self.proc = None
            return False
        # Owned before it is read: a child the panel does not know about is a child the
        # panel cannot stop, and it would go on sniffing after the window is gone.
        if self._on_spawn is not None:
            try:
                self._on_spawn(self)
            except Exception:         # noqa: BLE001 — bookkeeping, not the child
                pass
        self._thread = threading.Thread(target=self._read, daemon=True,
                                        name=f"panel-{self.tag}")
        self._thread.start()
        return True

    @property
    def pid(self) -> "int | None":
        return self.proc.pid if self.proc is not None else None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        """Ask the child to go. Idempotent, and never raises.

        The flag goes up *before* the kill so the reader thread — which may be
        mid-line — knows the death was deliberate by the time it notices it.
        """
        self._stopping = True
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:             # noqa: BLE001 — already gone is a fine outcome
            pass

    # -- the reader ---------------------------------------------------------
    def _read(self) -> None:
        proc = self.proc
        try:
            if proc is not None and proc.stdout is not None:
                for raw in proc.stdout:
                    line = raw.rstrip()
                    self.lines += 1
                    self.last_line_at = time.monotonic()
                    if self._on_line is not None:
                        # False = "handled, do not log it"; anything else logs.
                        if self._on_line(line) is False:
                            continue
                    if line:
                        self._log(f"[{self.tag}] {line}")
        except Exception:             # noqa: BLE001 — a broken pipe ends the stream
            pass
        if self._stopping or self.proc is not proc:
            return                    # asked for, or already replaced: not news
        self.proc = None
        if self._on_exit is not None:
            self._announce_exit()

    def _announce_exit(self) -> None:
        """Run ``on_exit``, on the Tk thread if there is one to get onto.

        `after()` is itself a Tk call, and calling it from this thread while the main
        thread is NOT inside the event loop raises «main thread is not in main loop» —
        which is most of a panel's boot, because the window pumps `update()` by hand
        until every profile is up. A child that ends during those seconds therefore
        killed this thread with a traceback on stderr and its `on_exit` never ran: the
        checkbox stayed ticked for a monitor that had gone, and the line it owed the log
        was never said (#1212, seen at every start once the sweep — a child that always
        ends a few seconds after the boot begins — existed).

        The panel's ``schedule`` is the window's hand-over QUEUE now
        (`panel/runtime/tick.py`, #1226), which cannot raise that at all and does not
        make this thread wait on the event loop — so the fallback below is for a monitor
        built without one (a test, a harness) rather than for the boot. Running it on
        this thread is the lesser evil there: the callbacks are a log line and a Tk
        variable, and the alternative is not running them at all.
        """
        try:
            if self._schedule is not None:
                self._schedule(0, self._on_exit)
                return
        except Exception:             # noqa: BLE001 — no event loop to hand it to (yet)
            pass
        try:
            self._on_exit()
        except Exception:             # noqa: BLE001 — a child's death is not the panel's
            pass
