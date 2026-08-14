"""Is this profile's daemon alive? — THE one gate on every timer and every trigger.

**Nothing automatic happens while this profile's daemon is down.** Not a scenario, not a
read into the game, not a relaunch of the client, not a retry, and not a line in the log
every few seconds saying that none of it worked. The schedule waits, quietly, until the
daemon is back — and then goes on exactly as it was.

WHY IT IS ONE OBJECT AND NOT A CHECK PER CALLER. Because the check drifts. «Стоп всё»
now ends two things and only two — the client and this profile's daemon (#1393) — and
everything that would otherwise notice a client missing was, until now, free to put it
back: the schedule's `restart_game`, the process watchdog, the recovery's verdict. Three
detectors, three ideas of «may I», and the emergency button undone within eight seconds
of being pressed. So they all ask ONE object, per profile, and a fourth detector added
tomorrow asks the same one.

WHAT IT COSTS, AND WHY IT IS HONEST. Nothing, on almost every call. The window's status
poll already probes this profile's daemon every eight seconds and leaves the verdict on
`rt.health` (`panel/runtime/health.py`) — a socket probe plus, when it matters, the pid
comparison. This reads THAT, so a timer tick and a trigger poll pay a dict lookup rather
than a round trip. Two things keep it from being a stale belief instead of a fact:

* a reading older than :data:`FRESH_SEC` is not used at all — a runtime with no window
  behind it (a tab launched on its own) has nobody polling, and «nobody has looked» may
  never read as «alive»;
* :meth:`DaemonGate.changed` throws away everything known so far. Whoever starts or
  stops a daemon says so, and the next question is answered by asking the port rather
  than by quoting a reading taken before the thing happened. Without it «Стоп всё» would
  leave up to eight seconds in which an errand still believed the daemon was warm — and
  an errand that believes that calls `ensure()`, which would start the daemon the press
  had just stopped.

WHAT IT DOES NOT GATE. A person's own press. A button in the window or on the phone that
starts the client, brings the daemon up or plays a scenario is somebody standing there
asking for it, and this is not the object that says no to a human being. It gates what
runs BY ITSELF.

PER PROFILE, LIKE EVERYTHING ELSE THAT IS AN ACCOUNT'S (`CLAUDE.md`). One of these lives
on each :class:`~panel.runtime.host.PanelRuntime`; there is no module-level state here at
all, because two open profiles have two daemons on two ports and one of them being down
says nothing whatever about the other.
"""
from __future__ import annotations

import threading
import time

import profile_health


#: How old the status poll's verdict may be before this stops believing it. The poll runs
#: every eight seconds (`panel/__main__.py::STATUS_POLL_MS`), so this is three of its
#: turns: long enough that an unlucky poll does not send every gate question to the
#: socket, short enough that a poll which has died is noticed rather than quoted for ever.
FRESH_SEC = 30.0


class DaemonGate:
    """One profile's «may anything run right now», and the two lines that say it changed."""

    __slots__ = ("rt", "_lock", "_open", "_since", "_changed_at")

    def __init__(self, rt) -> None:
        self.rt = rt
        # Written from the timer thread, the trigger poll thread and the status poll;
        # read from both front-ends' paint. Cheap enough to hold for the whole of a read.
        self._lock = threading.Lock()
        #: The last answer given, or ``None`` while nothing has asked yet.
        self._open: "bool | None" = None
        #: …and since when it has been that answer — what the mark on screen counts.
        self._since = 0.0
        #: When somebody last told us the daemon's existence changed (:meth:`changed`).
        #: Readings taken before this moment are not evidence about the world after it.
        self._changed_at = 0.0

    # -- the question --------------------------------------------------------
    def alive(self) -> bool:
        """Is this profile's daemon up and holding the client it should be?

        The one question. ``True`` lets the automatic side of the panel do what it was
        going to do; ``False`` means it does nothing at all and says nothing about it —
        the edge is announced here, once, rather than by every caller in its own words.
        """
        answer = self._read()
        self._note(answer)
        return answer

    def held(self) -> bool:
        """The same reading, the other way round — for a drawer that asks «is it stuck»."""
        return not self.alive()

    def reason(self) -> "str | None":
        """The locale key naming why nothing may run, or ``None`` while it may.

        What a skip line puts inside its sentence (`panel/timers.py::note_skip`).
        """
        return None if self.alive() else "timers.log.skip_daemon"

    def _read(self) -> bool:
        """The reading itself: the status poll's verdict when it is fresh, else the port.

        Deliberately the poll's THREE-state verdict and not a bare `up()`: a daemon that
        answers its port while holding a client that has gone lands nothing in the game
        (#1286), so an errand run against it fails, is written down as a failure and sits
        out its retry hold for nothing. Stale is not alive. It is also not this object's
        business to fix — the recovery restarts a stale daemon and is deliberately NOT
        gated on this, or a stale daemon would hold the gate that holds its own cure.
        """
        health = getattr(self.rt, "health", None)
        read_at = float(getattr(health, "read_at", 0.0) or 0.0) if health is not None else 0.0
        # STRICTLY newer than the change, because the wall clock is not fine-grained:
        # Windows ticks it every ~16 ms, so a poll and a `changed()` in the same instant
        # carry the same stamp — and «the same instant» has to fall on the side of
        # distrusting the reading. The cost of being wrong that way is one socket probe.
        if read_at > self._changed_at and (time.time() - read_at) <= FRESH_SEC:
            return getattr(health.current, "daemon", "") == profile_health.DAEMON_LIVE
        # Nobody is polling this runtime (a tab launched on its own), the poll has died,
        # or something has just started or stopped a daemon and the last verdict predates
        # it. Ask the port — 0.35 s at worst, and cached for a second inside `up()`.
        try:
            return bool(self.rt.game.up())
        except Exception:                     # noqa: BLE001 — a reading, never the panel
            return False

    def changed(self) -> None:
        """A daemon of this profile was just started or stopped — distrust what is known.

        Called by whoever did it. Two effects, and both matter: the port's cached answer
        is dropped, and every verdict the status poll has already made is ruled out of
        date — so the next question is decided by asking rather than by quoting a reading
        from before the act. See the module docstring.
        """
        with self._lock:
            self._changed_at = time.time()
        try:
            self.rt.game.forget_up()
        except Exception:                     # noqa: BLE001 — housekeeping, never the act
            pass

    # -- saying it, once ------------------------------------------------------
    def _note(self, answer: bool) -> None:
        """Say the EDGE, in the person's log, and never the state.

        «Ничего не запускается, потому что демон остановлен» is a thing somebody has to
        be told — the whole of #1262 is that a panel holding still looks exactly like a
        panel with nothing to do. Saying it per tick is the other failure, and the one
        this task exists to remove, so it is said when it becomes true and again when it
        stops being true. The mark on screen (:meth:`state`) is what carries it in
        between, because a line scrolls away and a mark does not.
        """
        with self._lock:
            was, self._open = self._open, answer
            if was is answer:
                return
            self._since = time.time()
            first = was is None
        if answer:
            if not first:                     # an ordinary start-up is not news
                self._say("gate.log.free")
            return
        self._say("gate.log.held")

    def _say(self, key: str) -> None:
        try:
            self.rt.say("panel", key)
        except Exception:                     # noqa: BLE001 — a line, never the gate
            pass

    # -- what both front-ends draw -------------------------------------------
    def state(self, now: "float | None" = None) -> dict:
        """The mark: whether everything is held, and for how long. Numbers, never words.

        Read from the window's paint and from the phone's `/api/state`, out of ONE object
        — the same arrangement as the panic mark and the profile's light beside it. It
        reports what was last ANSWERED rather than taking a reading of its own: a drawer
        must never be the thing that probes a socket (`panel/runtime/health.py` says the
        same about the same kind of state).
        """
        now = time.time() if now is None else now
        with self._lock:
            held = self._open is False
            since = self._since
        return {"held": held, "for_sec": int(now - since) if held and since else 0}
