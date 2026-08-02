"""Named repeating callbacks, and a way to get onto the Tk thread from another one.

Was `Panel._arm` / `_disarm` / `_disarm_all` / `_on_tk`. It moves here because every tab
that polls something needs it, in both launch modes, and none of it is about the shell's
window (docs/research/panel-tabs-refactor.md §4.1).

ONE CHAIN PER NAME is the whole point of the name (#1177). A self-rearming `after` chain
started twice doubles every tick from then on, and it is invisible from the outside — the
panel just gets slower and slower. Arming by name cancels whatever was pending under it,
so starting a loop twice is starting it once.
"""
from __future__ import annotations

import threading


class Ticker:
    """Repeating callbacks keyed by name, on one Tk widget's `after` queue."""

    def __init__(self, widget) -> None:
        self._w = widget
        self._loops: dict = {}

    def arm(self, name: str, delay_ms: int, func) -> None:
        """(Re)arm the repeating callback ``name`` — cancelling any pending one."""
        import tkinter as tk

        self.disarm(name)
        try:
            self._loops[name] = self._w.after(int(delay_ms), func)
        except (tk.TclError, RuntimeError):      # the window is going away
            self._loops.pop(name, None)

    def disarm(self, name: str) -> None:
        """Cancel the pending callback under ``name``, if there is one."""
        import tkinter as tk

        job = self._loops.pop(name, None)
        if job is None:
            return
        try:
            self._w.after_cancel(job)
        except (tk.TclError, ValueError):        # already fired, or already gone
            pass

    def disarm_all(self) -> None:
        for name in list(self._loops):
            self.disarm(name)

    def armed(self) -> int:
        """How many chains are pending (what the health snapshot watches)."""
        return len(self._loops)

    # -- getting onto the Tk thread -----------------------------------------
    def on_tk(self, func, timeout: float = 20.0) -> None:
        """Run ``func`` on the Tk thread from a worker and wait for it to finish.

        Only safe while somebody is pumping Tk — during the boot that is the panel's
        `_await_boot`, afterwards the mainloop — so the wait is bounded and a timeout
        simply means the call is still queued, not that it was lost.
        """
        import tkinter as tk

        done = threading.Event()

        def call() -> None:
            try:
                func()
            finally:
                done.set()

        try:
            self._w.after(0, call)
        except (tk.TclError, RuntimeError):
            return
        done.wait(timeout)
