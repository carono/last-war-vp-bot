r"""One profile's stamped log history — the half with NO WIDGET in it (#1976, P3).

`panel/runtime/log.py` is the SINK: a line goes into it from any thread, is mirrored into
the debug log, is handed to whoever is tapping, and waits in a queue. This is what drains
that queue: the record on disk, the history a pane seeds itself from an hour later, and
the tap the phone's `/api/log` reads.

    LogBus.put ──> queue ──> LogSpool.pump ──┬──> panel.log       (the record)
      (any thread)         (the panel's clock)├──> the history     (a filter redraw, and
                                              │                    a pane opened later)
                                              └──> LogPane, if one is drawn

IT RUNS WHETHER OR NOT ANYBODY IS DRAWING, which is why it is not part of the pane —
«Разработка» is off in most profiles and LAZY in the rest, so for long stretches there is
no widget at all, and a queue nobody drains grows without bound while a `panel.log` nobody
writes is a session with no record of itself.

AND IT IS SPLIT OUT OF `log_view.py` BECAUSE OF THE OTHER HALF: that file imports Tk at
its first line, and the panel has to run where there is no Tk at all
(`panel/headless.py`). The pane is the window's; the spool is the panel's.

ONE PANE AT A TIME, like `LogBus.drain` has one drainer. A second would not see half the
lines — it would see all of them, and every line would be drawn twice in the first. So
:meth:`LogSpool.attach` replaces rather than appends.
"""
from __future__ import annotations

import threading
import time

from .log import severity_of, strip_ansi, tag_of

#: How many lines the history keeps. An overnight session with a tracer running writes
#: tens of thousands of them, and a `Text` widget that large makes every subsequent insert
#: visibly slow — the panel froze once for exactly this reason. The on-disk mirror
#: (`panel.log`) is NOT trimmed: the history is a window onto the session, the file is the
#: record.
MAX_LINES = 4000
#: Trimming a line at a time would run on every insert; drop a block instead, so the cost
#: is paid once every this many lines.
TRIM_BLOCK = 500


class LogSpool:
    """One profile's stamped history, and the pump that fills it. NO WIDGET.

    Made per runtime beside the :class:`~panel.runtime.log.LogBus` it drains, and
    pumped by whoever owns the clock — the shell, once per profile, every 120 ms.
    """

    def __init__(self, bus, cap: int = MAX_LINES) -> None:
        self.bus = bus
        #: How many lines to keep for a redraw. Twice this is held, so narrowing the
        #: filter and widening it again still has more history than the widget showed.
        self.cap = max(int(cap), 1)
        self._kept: list = []
        self._lock = threading.RLock()
        self._pane = None

    # -- the pump ------------------------------------------------------------
    def pump(self, cap: "int | None" = None) -> int:
        """Drain the bus: stamp, remember, mirror to panel.log, draw. Tk thread.

        Returns how many lines the pane drew, which is 0 whenever there is no pane —
        everything else it does happens either way, and that is the point of it.
        """
        if cap:
            self.cap = max(int(cap), 1)
        pane = self._pane
        drawn = 0
        while True:
            line = self.bus.take()
            if line is None:
                break
            stamp = time.strftime("%H:%M:%S")
            with self._lock:
                self._kept.append((stamp, line))
            if pane is not None:
                try:
                    # One scroll for the whole drain, below: a tracer streaming a
                    # thousand lines a second must not make Tk chase the tail a
                    # thousand times in the same tick.
                    drawn += 1 if pane.append(stamp, line, scroll=False) else 0
                except Exception:            # noqa: BLE001 — a widget, never the record
                    pane = None
            self.bus.append_file(line)
        self._trim()
        if drawn and pane is not None:
            try:
                pane.settle()
            except Exception:                # noqa: BLE001
                pass
        return drawn

    def _trim(self) -> None:
        with self._lock:
            if len(self._kept) > self.cap * 2:
                del self._kept[:len(self._kept) - self.cap]

    # -- reading -------------------------------------------------------------
    def lines(self) -> list:
        """The history, oldest first, as ``(stamp, line)``. A copy."""
        with self._lock:
            return list(self._kept)

    def clear(self) -> None:
        """Forget the history. `panel.log` is untouched — it is the record."""
        with self._lock:
            self._kept.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._kept)

    # -- the one pane --------------------------------------------------------
    def attach(self, pane) -> None:
        """This pane draws from now on, and seeds itself from the history."""
        self._pane = pane

    def detach(self, pane=None) -> None:
        """Stop drawing — the tab was closed, or the profile went away."""
        if pane is None or self._pane is pane:
            self._pane = None

    @property
    def pane(self):
        return self._pane
