"""Spawning the panel's child processes — the captures, the sniffers, the tools.

`panel/childmon.py` is the monitor (start it, stream its output, notice it died). This
is the factory that wires one to a runtime: the Python that runs it, the environment it
inherits, where its lines go.

The four monitors used to carry a copy each of "spawn a child, stream it into the log,
untick the box when it dies" — four places for every fix to be made, or forgotten in
three. What differs between them is the command, the tag, what a line means and what its
death means; that is exactly the signature here.

THE ENVIRONMENT IS THE INTERESTING PART. Two variables travel with every child:

* ``LW_DAEMON_PORT`` — a profile pointed at the second client's daemon
  (tools/rdp_instance.py) drives THAT client from its captures and robberies too, not
  just from the panel's own presses.
* ``LW_GAME_LEASE`` — for as long as the runtime is holding the game
  (tools/lib/game_lease.py). Auto-loot claims the lease and *then* spawns the tool that
  does the robbing; without the token that child would wait for a lease its own parent
  is holding. It rides in `os.environ` while held, so it is simply inherited.
"""
from __future__ import annotations

import os
import subprocess

from .. import childmon as childmonmod

# Windows: no console window for a child the panel is reading through a pipe.
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW


class ChildFactory:
    """Makes :class:`panel.childmon.ChildMonitor`s bound to one runtime."""

    def __init__(self, log, cwd: str, python, port, schedule) -> None:
        self._log = log                 # the LogBus
        self._cwd = cwd
        self._python = python           # callable: the interpreter to run children with
        self._port = port               # callable: this profile's daemon port
        self._schedule = schedule       # widget.after — how a child gets onto the Tk thread

    def python(self) -> str:
        return self._python()

    def env(self) -> dict:
        """The environment every child is launched with (see the module docstring)."""
        return dict(os.environ, PYTHONIOENCODING="utf-8",
                    LW_DAEMON_PORT=str(self._port()))

    def spawn(self, tag: str, cmd: list, *, on_line=None, on_exit=None,
              capture_stderr: bool = True) -> "childmonmod.ChildMonitor":
        return childmonmod.ChildMonitor(
            cmd, tag, log=self._log.put, cwd=self._cwd, on_line=on_line,
            on_exit=on_exit, schedule=self._schedule, env=self.env(),
            capture_stderr=capture_stderr)

    def spawn_raw(self, cmd: list, tag: str) -> "subprocess.Popen | None":
        """A bare `Popen` whose stdout+stderr the caller reads itself. ``None`` if it
        would not start.

        For the children whose output is streamed by a reader thread rather than by a
        ChildMonitor: the robberies, the raw sniffers, the chat reader. utf-8 is forced
        because a piped stdout would otherwise fall back to the ANSI code page and
        mangle its glyphs under our utf-8 decode.
        """
        try:
            return subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=self._cwd,
                env=self.env(), creationflags=NO_WINDOW)
        except Exception as exc:                  # noqa: BLE001 — it is a child, not us
            self._log.say(tag, "log.launch_failed", error=exc)
            return None
