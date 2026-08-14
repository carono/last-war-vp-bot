"""What the panel is DOING RIGHT NOW — the line along the bottom of the window.

A panel that is thinking looks exactly like a panel that has hung. Opening a profile
builds fifteen tabs, brings a daemon up and reads the game; every one of those is
several hundred milliseconds of a frozen window, and until this there was nothing on
screen that said which of them was in flight — only a log line afterwards, if the step
happened to write one.

So each of those steps announces itself while it runs. Not into the log (the log is the
record of what HAPPENED, and a line per «I am about to…» would drown it) but into this:
one object per open profile, holding the steps that are live at this instant, and a
listener per window that paints the newest of them.

WHAT A STEP IS. A locale key and its format arguments — never a sentence. The words are
said by whoever draws them, in whatever language that window is showing
(`CLAUDE.md`, «Not one word of the panel is written in the panel»), which is also why
a step can be reported from a worker thread that has no idea what language is on.

WHY A SET AND NOT ONE VALUE. Several things really are in flight at once: the boot runs
a thread per profile, an errand fires while a tab is being built, a daemon comes up
while the account strip is being read. A single «current» string means the last writer
wins and the loser's step is lost — including the case where the loser is the long one
and the winner finished instantly. Every step is held until it ENDS, and «what is the
panel doing» is answered by the newest one still live; when it ends, whatever is still
running underneath comes back into view by itself.

USE IT AS A CONTEXT MANAGER wherever the work is one block:

    with rt.activity.step("activity.daemon.start", port=47654):
        link.ensure()

and as :meth:`begin` / :meth:`end` only where it cannot be — a build spread across
event-loop turns, which is the one caller that needs it.

THREAD-SAFE AND NEVER LOAD-BEARING. Any thread may report; listeners are called outside
the lock and a listener that raises is swallowed. Nothing here may be the reason an
errand fails: this object exists to describe work, not to do it.
"""
from __future__ import annotations

import contextlib
import itertools
import threading
import time

#: Global ordering across every activity in the process. The window shows the newest
#: live step of ALL its open profiles, so «newest» has to mean something between two
#: objects that never see each other.
_SEQ = itertools.count(1)


class Step:
    """One thing being done: a locale key, its arguments, and who is doing it."""

    __slots__ = ("seq", "key", "fmt", "owner", "started")

    def __init__(self, key: str, fmt: dict, owner) -> None:
        self.seq = next(_SEQ)
        self.key = key
        self.fmt = fmt
        #: When it began, on the monotonic clock. The strip shows what is running; the
        #: busy debugger has to show how LONG it has been running, and a step with no
        #: start time cannot say (#1392).
        self.started = time.monotonic()
        #: The :class:`Activity` this step belongs to — so a painter that watches
        #: several of them can say WHOSE step it is showing.
        self.owner = owner

    def __repr__(self) -> str:
        return f"<Step {self.key!r} seq={self.seq}>"


class Activity:
    """The steps one profile (or the window itself) has in flight."""

    def __init__(self, name: str | None = None) -> None:
        #: The profile these steps are about, or ``None`` for the window's own.
        self.name = name
        self._live: dict = {}
        self._lock = threading.RLock()
        self._listeners: list = []

    # -- reporting ----------------------------------------------------------
    def begin(self, key: str, **fmt) -> Step:
        """Start a step. Keep the handle — :meth:`end` is what takes it off screen."""
        step = Step(key, fmt, self)
        with self._lock:
            self._live[step.seq] = step
        self._changed()
        return step

    def end(self, step: "Step | None") -> None:
        """Finish a step. Harmless for one already ended, or for ``None``."""
        if step is None:
            return
        with self._lock:
            if self._live.pop(step.seq, None) is None:
                return
        self._changed()

    @contextlib.contextmanager
    def step(self, key: str, **fmt):
        """``with activity.step("activity.x", n=1):`` — begun here, ended whatever happens."""
        handle = self.begin(key, **fmt)
        try:
            yield handle
        finally:
            self.end(handle)

    def clear(self) -> None:
        """Forget every live step. «Стоп всё», and a session being torn down."""
        with self._lock:
            if not self._live:
                return
            self._live.clear()
        self._changed()

    # -- reading ------------------------------------------------------------
    def current(self) -> "Step | None":
        """The newest step still running, or ``None`` when nothing is."""
        with self._lock:
            if not self._live:
                return None
            return self._live[max(self._live)]

    def live(self) -> list:
        """Every step still running, oldest first — what the busy debugger draws.

        The strip wants ONE step (`current`); a debugger wants all of them, because two
        things in flight at once is the state it exists to explain. Oldest first so the
        one that has been going longest — the one a jam is usually about — is at the top.
        """
        with self._lock:
            return sorted(self._live.values(), key=lambda step: step.seq)

    def busy(self) -> bool:
        with self._lock:
            return bool(self._live)

    def __len__(self) -> int:
        with self._lock:
            return len(self._live)

    # -- watching -----------------------------------------------------------
    def listen(self, func):
        """Be told, on the reporting thread, that something started or finished.

        The listener is called with no arguments and asks :meth:`current` for itself:
        it may be woken twice for one change (two threads, two steps) and must be able
        to answer «what is showing now» rather than «what just happened».

        Returns the callable that stops listening.
        """
        with self._lock:
            self._listeners.append(func)

        def _off() -> None:
            with self._lock:
                try:
                    self._listeners.remove(func)
                except ValueError:
                    pass
        return _off

    def _changed(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for func in listeners:
            try:
                func()
            except Exception:                # noqa: BLE001 — a strip, never the errand
                pass
