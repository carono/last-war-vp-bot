"""One ear for the whole profile, and everything that wants a push subscribes to it.

WHY THIS EXISTS. A wire trigger is «run this errand when the game sends that push», and
until now each enabled one was its own OS process: `wire_event_monitor.py --match <one
pattern>`. Every one of them opened its own npcap capture on the same interface, was
handed every packet the game sent, ran the whole envelope decode on it — and then threw
away all but the one command name it cared about. Three triggers meant the same traffic
decoded three times; and the panel holds a runtime per open profile, so the bill was
*listeners × profiles* and every term of it was the same work done again.

That is what this replaces. ONE capture per profile, carrying the union of every pattern
anybody asked for, and the dispatch done here in Python where it costs a substring test:

    off = rt.wire.subscribe("push.alliance.march", self._on_rally)
    ...
    off()                       # and the ear closes when the last subscriber goes

The child is spawned on the first subscription and stopped with the last, exactly like
`rt.squads`' poll — a profile that has switched every trigger off pays nothing at all.

WHAT DID NOT CHANGE, and it matters for reading the code that calls this: the marker
line, the human line, the log. The child is the same tool with the same output; the only
change on its side is that its cooldown is now per COMMAND rather than one clock for the
ear, because a shared clock across many patterns lets a chatty command swallow a quiet
one's only marker.

THE DISPATCH RUNS ON THE CHILD'S READER THREAD, never on Tk. A subscriber's callback
must therefore be safe off the Tk thread — the schedule's `submit` is (it hands to a
queue), and anything that draws should go through `rt.post`.

ONE PROFILE, ONE ACCOUNT'S TRAFFIC. The capture filter can only narrow by TCP port, and
two clients of the same game dial the SAME server port — so until this ear existed every
capture on the machine decoded both accounts and every profile's triggers fired off
whichever arrived first. What differs is the LOCAL port, which is not in the packet but
in the socket table, so the profile's client pids are resolved by `game_process.profile_pids` and
the capture keeps only the traffic on those sockets, following them by Windows user when
the client is restarted (`map_capture.OwnPorts`).

Where the owner cannot be worked out — no psutil, a session that will not answer, a
foreign token that refuses — the capture keeps ITS OLD machine-wide behaviour instead of
going quiet. Losing the separation is a fair price for an unanswerable question; losing
the traffic would make a profile that farms nothing look exactly like one with nothing
to do.
"""
from __future__ import annotations

import os
import threading

from . import game_process
from .paths import TOOLS

#: The marker line the child prints for every match. Kept in `panel/triggers.py` because
#: that is where the trigger vocabulary lives; imported rather than re-spelled.
from ..triggers import FIRE_MARKER


class WireHub:
    """The profile's single wire ear, and the subscriptions over it."""

    def __init__(self, rt) -> None:
        self._rt = rt
        self._lock = threading.Lock()
        self._subs: dict = {}          # token -> (pattern, callback)
        self._next = 0
        self._proc = None              # the capture child, while anybody wants it
        self._running: tuple = ()      # the pattern set it was actually launched with

    # -- subscribing ---------------------------------------------------------
    def subscribe(self, pattern: str, on_fire):
        """Hear every down command containing ``pattern``. Returns the unsubscribe.

        The callback is handed the command name that matched. It runs on the child's
        reader thread and must not block it for long — put the work on a queue.

        Subscribing with a pattern the ear is not carrying yet RESTARTS the child with
        the wider set. That is a process restart per switch toggled, which is rare and
        cheap; the alternative — one capture that prints every command and lets the
        panel filter — moves the whole game's chatter through a pipe all day.
        """
        pattern = (pattern or "").strip()
        if not pattern:
            raise ValueError("a wire subscription needs a pattern")
        with self._lock:
            self._next += 1
            token = self._next
            self._subs[token] = (pattern, on_fire)
        self._sync()

        def _off() -> None:
            with self._lock:
                self._subs.pop(token, None)
            self._sync()
        return _off

    def patterns(self) -> tuple:
        """Every distinct pattern currently subscribed, in a stable order."""
        with self._lock:
            return tuple(sorted({p for p, _cb in self._subs.values()}))

    def listeners(self) -> int:
        """How many subscriptions the one ear is serving — what the saving is made of."""
        with self._lock:
            return len(self._subs)

    # -- the child ------------------------------------------------------------
    def _sync(self) -> None:
        """Match the running capture to the patterns wanted right now. Idempotent."""
        wanted = self.patterns()
        if not wanted:
            self.stop()
            return
        if self._proc is not None and self._running == wanted:
            return
        self.stop()
        self._start(wanted)

    def _start(self, patterns: tuple) -> None:
        cmd = [self._rt.children.python(), "-u",
               os.path.join(TOOLS, "wire_event_monitor.py")]
        for pattern in patterns:
            cmd += ["--match", pattern]
        # WHOSE traffic this ear is for. Two accounts of the same game dial the same
        # server port, so the capture filter cannot separate them and every profile's
        # ear has been hearing both — a trigger firing in one account off the other's
        # push. The pids are resolved here, where the profile is known, and followed
        # inside the capture by user so a client restart does not need a new ear.
        for pid in game_process.profile_pids(self._rt.settings):
            cmd += ["--client-pid", str(pid)]
        mon = self._rt.children.spawn("trigger", cmd, on_line=self._on_line,
                                      on_exit=self._on_exit)
        if not mon.start():
            # `spawn` has already said why. The subscriptions stay: the next `sync()`
            # of whatever owns them tries again, and a subscriber that never hears
            # anything is better than one that has quietly forgotten it wanted to.
            return
        self._proc, self._running = mon, patterns
        self._rt.say("trigger", "triggers.log.ear",
                     count=len(self._subs), patterns=", ".join(patterns))

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        self._running = ()
        if proc is not None:
            proc.stop()

    def _on_exit(self) -> None:
        """The ear died. Tell everyone who was listening through it — once each.

        Each subscriber decides for itself what that means; the trigger watcher forgets
        its listener and brings it back on the next sync, which is the same thing it
        did when every trigger had a child of its own.
        """
        self._proc, self._running = None, ()
        with self._lock:
            callbacks = [cb for _p, cb in self._subs.values()]
        for callback in callbacks:
            try:
                callback(None)          # `None` — «the ear closed», not a command
            except Exception:           # noqa: BLE001 — one deaf listener is not the rest
                pass

    def _on_line(self, line: str):
        """One line off the child: dispatch a marker, let a human line reach the log.

        Returns ``False`` for the marker so the reader swallows it (it is machinery),
        and ``None`` for anything else so it logs as it always did.
        """
        if not line.startswith(FIRE_MARKER):
            return None
        command = line[len(FIRE_MARKER):].strip()
        with self._lock:
            wanted = [(pattern, cb) for pattern, cb in self._subs.values()]
        for pattern, callback in wanted:
            if pattern in command:
                try:
                    callback(command)
                except Exception:       # noqa: BLE001 — never let one kill the ear
                    self._rt.dbg("triggers").error(
                        "wire subscriber for %r raised", pattern, exc_info=True)
        return False
