"""Named repeating callbacks, and a way to get onto the Tk thread from another one.

Was `Panel._arm` / `_disarm` / `_disarm_all` / `_on_tk`. It moves here because every tab
that polls something needs it, in both launch modes, and none of it is about the shell's
window (docs/research/panel-tabs-refactor.md §4.1).

ONE CHAIN PER NAME is the whole point of the name (#1177). A self-rearming `after` chain
started twice doubles every tick from then on, and it is invisible from the outside — the
panel just gets slower and slower. Arming by name cancels whatever was pending under it,
so starting a loop twice is starting it once.

WHY A WORKER MUST NOT CALL `after` ITSELF (#1226)
-------------------------------------------------

`widget.after(0, func)` looks like a free hand-over and is not. Tkinter registers a Tcl
command for the callback (`Misc._register`) and then makes the `after` call itself — two
trips into the Tcl interpreter — and from a thread that is not the Tk one, `_tkinter`
does not run them: it queues each as an event for the Tk thread and **blocks the caller**
until the event loop gets round to it. So a worker handing a repaint over pays whatever
the Tk thread is busy with, and the Tk thread pays an event per hand-over.

With one profile that is a rounding error. With four it is the panel's whole problem:
every profile's status poll, dashboard tick, tab read and child death goes through the
one event loop, so a profile that is merely *reporting* its work occupies the thread that
draws all the others, and each of them waits behind the rest. Measured on the live panel
(`LW_PANEL_STALL_MS`, docs/research/panel-freezes.md): worker threads sitting in
`Variable.get` and `Misc._register` are the largest real contributor to the samples, and
the two boot threads made the failure below reliable rather than rare.

And it is worse than slow. While the main thread is not inside the event loop — which is
most of a panel's boot, because the window pumps `update()` by hand until every profile
is up — the same call raises «main thread is not in main loop», which killed the worker
that made it. `panel/childmon.py::_announce_exit` and `panel/__main__.py::_startup` both
carry a paragraph about losing a whole boot step to exactly that.

:meth:`post` is the answer, and it touches no Tk at all: the callable goes into a plain
queue and ONE chain per window drains it on the Tk thread. A worker never blocks, the
event loop pays one wake-up per pump instead of one per hand-over, and there is no
call that can raise «not in main loop» because there is no call.

Use :meth:`post` for "repaint this when you can" (which is nearly every hand-over),
:meth:`on_tk` for "do this on the Tk thread and tell me when it is done", and `after`
directly only for a real DELAY on the Tk thread.
"""
from __future__ import annotations

import queue
import threading
import time

#: How often the shared pump looks for work handed over from a worker thread. Small
#: enough that a repaint is not visibly late, large enough that an idle window with four
#: profiles open is still one wake-up per tick and not four.
POST_MS = 30

#: The attribute a window's pump is stashed under. On the widget rather than in a module
#: dict so it goes away with the window and cannot keep a destroyed root alive.
_POSTER_ATTR = "_lw_tk_poster"


class TkPost:
    """The queue of callables waiting for the Tk thread, and the chain that drains it.

    ONE PER WINDOW, whatever the number of open profiles: the queue is a hand-over, not
    a per-profile fact, and four chains waking thirty times a second would be four times
    the idle cost for no benefit. Every session's :class:`Ticker` shares the one belonging
    to the root it was built on.
    """

    def __init__(self, widget, interval_ms: int = POST_MS) -> None:
        self._w = widget
        self._q: "queue.Queue" = queue.Queue()
        self._interval = int(interval_ms)
        self._job = None
        self._running = False

    # -- the worker's half (never touches Tk) --------------------------------
    def post(self, func) -> None:
        """Hand ``func`` to the Tk thread. Any thread, no Tk call, never raises."""
        if func is None:
            return
        self._q.put(func)

    def pending(self) -> int:
        return self._q.qsize()

    # -- the Tk thread's half ------------------------------------------------
    def start(self) -> None:
        """Begin draining. Idempotent, and only ever called from the Tk thread."""
        if self._running or self._w is None:
            return
        self._running = True
        self._arm()

    def stop(self) -> None:
        """Stop draining — the window is going away. Queued work is dropped."""
        self._running = False
        job, self._job = self._job, None
        if job is None:
            return
        try:
            self._w.after_cancel(job)
        except Exception:                        # noqa: BLE001 — already gone is fine
            pass

    def drain(self) -> int:
        """Run everything waiting, on THIS thread. Returns how many ran.

        Each callable is run inside its own guard, so one that raises does not swallow
        the rest of the batch — which a bare loop would, and the rest of the batch is
        another profile's repaint. The exception is reported the way Tk reports any
        callback exception, so the panel's existing hook still logs it.
        """
        ran = 0
        while True:
            try:
                func = self._q.get_nowait()
            except queue.Empty:
                return ran
            ran += 1
            try:
                func()
            except Exception:                    # noqa: BLE001 — one hand-over, not all
                self._complain()

    def _complain(self) -> None:
        import sys

        report = getattr(self._w, "report_callback_exception", None)
        try:
            if report is not None:
                report(*sys.exc_info())
                return
        except Exception:                        # noqa: BLE001 — a report, not the panel
            pass
        import traceback
        traceback.print_exc()

    def _pump(self) -> None:
        if not self._running:
            return
        self.drain()
        self._arm()

    def _arm(self) -> None:
        import tkinter as tk

        try:
            self._job = self._w.after(self._interval, self._pump)
        except (tk.TclError, RuntimeError, AttributeError):
            self._running, self._job = False, None


def stop(widget) -> None:
    """Stop the window's shared pump — call ONLY when the WHOLE window is closing.

    `poster(widget)` hands out the same :class:`TkPost` to every session built on
    ``widget`` (see its docstring), so this must never be reached from one session's
    own teardown — that would kill the drain out from under every OTHER open profile,
    which is invisible until one of them tries to repaint. It belongs at the one place
    that already knows every session is gone: `Workspace.shutdown` for the shell,
    `run_tab`'s close handler for a standalone tab. Calling it on a widget that never
    got a pump — ``None``, or a bare harness — is a no-op.
    """
    if widget is None:
        return
    found = getattr(widget, _POSTER_ATTR, None)
    if found is not None:
        found.stop()


def poster(widget) -> "TkPost | None":
    """The window's shared hand-over queue, made on first ask. ``None`` without a widget.

    Made and started here rather than by whoever asks first, because "first ask" may be a
    worker thread — and `start` arms an `after`, which is the very Tk call this module
    exists to keep off worker threads. So it is armed only when the asker is the Tk
    thread; a worker that gets in first still queues its work safely and the first Tk
    caller starts the drain.
    """
    if widget is None:
        return None
    found = getattr(widget, _POSTER_ATTR, None)
    if found is None:
        found = TkPost(widget)
        try:
            setattr(widget, _POSTER_ATTR, found)
        except Exception:                        # noqa: BLE001 — a bare mock in a test
            return found
    if not found._running and threading.current_thread() is threading.main_thread():
        found.start()
    return found


class Ticker:
    """Repeating callbacks keyed by name, on one Tk widget's `after` queue."""

    def __init__(self, widget) -> None:
        self._w = widget
        #: ``name -> job id``. What Tk needs to cancel a chain, and nothing else.
        self._loops: dict = {}
        #: ``name -> (delay_ms, armed_at)`` beside it, for the busy debugger: a chain
        #: that is armed says nothing about WHEN it fires, and «какой следующий срок» is
        #: half of what a timer view is for (#1392). Kept apart from `_loops` so the
        #: cancel path stays exactly what it was.
        self._armed_at: dict = {}
        # The window's shared pump, armed here because a runtime is always built on the
        # Tk thread — so the drain is running before the first worker has anything to
        # hand over, and no worker is ever the one to arm it.
        poster(widget)

    def arm(self, name: str, delay_ms: int, func) -> None:
        """(Re)arm the repeating callback ``name`` — cancelling any pending one."""
        import tkinter as tk

        self.disarm(name)
        try:
            self._loops[name] = self._w.after(int(delay_ms), func)
            self._armed_at[name] = (int(delay_ms), time.monotonic())
        except (tk.TclError, RuntimeError, AttributeError):   # the window is going away
            self._loops.pop(name, None)
            self._armed_at.pop(name, None)

    def disarm(self, name: str) -> None:
        """Cancel the pending callback under ``name``, if there is one."""
        import tkinter as tk

        job = self._loops.pop(name, None)
        self._armed_at.pop(name, None)
        if job is None:
            return
        try:
            self._w.after_cancel(job)
        except (tk.TclError, ValueError, AttributeError):  # already fired, or gone
            pass

    def disarm_all(self) -> None:
        for name in list(self._loops):
            self.disarm(name)

    def armed(self) -> int:
        """How many chains are pending (what the health snapshot watches)."""
        return len(self._loops)

    def pending(self) -> list:
        """Every armed chain: ``{name, delay_ms, secs, due_in}``, soonest first.

        `secs` is how long it has been armed and `due_in` how long until it fires — a
        NEGATIVE `due_in` is the interesting one: the chain's moment has passed and the
        event loop has not got to it, which is what a Tk-thread jam looks like from the
        outside (#1392). Plain arithmetic over a dict, so the debugger's refresh costs
        nothing worth measuring.
        """
        now = time.monotonic()
        rows = []
        for name in list(self._loops):
            delay_ms, at = self._armed_at.get(name, (0, now))
            waited = max(0.0, now - at)
            rows.append({"name": name, "delay_ms": int(delay_ms), "secs": waited,
                         "due_in": delay_ms / 1000.0 - waited})
        rows.sort(key=lambda row: row["due_in"])
        return rows

    # -- getting onto the Tk thread -----------------------------------------
    def post(self, func) -> None:
        """Run ``func`` on the Tk thread soon. Any thread, no Tk call, never raises.

        The blessed hand-over: see the module docstring for why `root.after(0, …)` from
        a worker is not one. Ordering is kept — the queue is FIFO — so two repaints
        posted in order arrive in order.
        """
        if func is None:
            return
        post = poster(self._w)
        if post is None:                        # no window (a bare harness, a test)
            try:
                func()
            except Exception:                   # noqa: BLE001 — as Tk would have
                pass
            return
        post.post(func)

    def on_tk(self, func, timeout: float = 20.0) -> None:
        """Run ``func`` on the Tk thread from a worker and wait for it to finish.

        Handed over through :meth:`post`, so the CALL costs a queue insert rather than a
        blocking trip into the Tcl interpreter — the wait that follows is for the work
        itself, which is what the caller actually asked to wait for.

        Only safe while somebody is pumping Tk — during the boot that is the panel's
        `_await_boot`, afterwards the mainloop — so the wait is bounded and a timeout
        simply means the call is still queued, not that it was lost.
        """
        if threading.current_thread() is threading.main_thread():
            # Already there. Posting would deadlock a caller that is itself inside the
            # event loop: the pump cannot run until this returns.
            func()
            return
        done = threading.Event()

        def call() -> None:
            try:
                func()
            finally:
                done.set()

        self.post(call)
        done.wait(timeout)
