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
import time

from . import game_process
from . import rally_wire
from .paths import TOOLS

#: The marker line the child prints for every match. Kept in `panel/triggers.py` because
#: that is where the trigger vocabulary lives; imported rather than re-spelled.
from ..triggers import FIRE_MARKER

#: The child's SECOND machine line and the one command family it is asked for (#1323).
#: A rally's kind is `targetContentId`, which rides on this push and on nothing the
#: client keeps, so a profile that hears the push without its payload cannot name a
#: single banner — and every per-kind daily budget silently collapses into one bucket.
#: The line carries four numbers of THINGS and no player (tools/wire_event_monitor.py),
#: it is swallowed here exactly as the marker is, and it costs no extra capture: it is
#: read off a frame the ear had in its hands anyway.
FIELDS_MARKER = "##FIELDS##"
FIELDS_PATTERN = "push.alliance.march"

#: How often the ear may say what it has been hearing. Every match used to print a line
#: of its own — the command plus a summary of its payload — and a live day carried 6 307
#: of them for one push alone, each one naming a `uid` and an `allianceId` (#1293). The
#: child prints no such line any more (`--quiet`); what the log gets instead is this:
#: the first thing heard said at once, and after that a roll-up no oftener than this,
#: carrying the COUNTS per command and no field of any payload.
HEARD_NOTE_SEC = 600.0

#: How many distinct commands a roll-up names before it says «and N more». A profile
#: with every trigger on subscribes to a handful of patterns, so this is generous.
HEARD_TOP = 3


class WireHub:
    """The profile's single wire ear, and the subscriptions over it."""

    def __init__(self, rt) -> None:
        self._rt = rt
        self._lock = threading.Lock()
        # A SECOND lock, and it is not paranoia. `_sync` reads the wanted patterns, stops
        # what is running and starts the replacement, and `self._proc` is only set once
        # the child has actually started — so two subscribers arriving together (which is
        # exactly what the trigger watcher does at boot, one `subscribe` per enabled
        # trigger) both saw `_proc` as None, both found nothing to stop, and both spawned.
        # The narrower ear was then orphaned and went on decoding the whole stream for
        # nobody — the very waste this module exists to remove. Seen live: two
        # `wire_event_monitor` processes, same second, one with a subset of the other's
        # patterns (#1237).
        self._sync_lock = threading.Lock()
        self._subs: dict = {}          # token -> (pattern, callback)
        self._next = 0
        self._proc = None              # the capture child, while anybody wants it
        self._running: tuple = ()      # the pattern set it was actually launched with
        # What has been heard since the last roll-up line: command -> how many. Under
        # `_lock`, because the markers arrive on the child's reader thread.
        self._heard: dict = {}
        self._heard_said = 0.0         # monotonic of the last roll-up line
        # A PROOF OF LIFE PER PATTERN (#1416). «Пропускаются события» cannot be told
        # from «событий не было» by looking at a subscription: both are a listener that
        # is quietly there. So every match is counted against the pattern it matched,
        # with the moment it arrived and the command it was — which is what «Занятость»
        # draws, and the only way a silent ear can say that it is silent.
        # `pattern -> [count, monotonic of the last, the last command]`.
        self._seen: dict = {}

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

    def report(self) -> list:
        """What this ear is listening for, and whether anything has come (#1416).

        One entry per PATTERN — the unit a person thinks in — carrying how many
        subscribers hang off it, how many matches have arrived, when the last one did
        (`time.monotonic`, or `0.0` for never) and what it was. No words: whoever draws
        it says them (`CLAUDE.md`).

        `alive` is the capture child's own state rather than «somebody subscribed»: an
        ear whose process has died still has its subscriptions, and that is exactly the
        case this exists to make visible.
        """
        proc = self._proc
        alive = bool(proc is not None and getattr(proc, "alive", False))
        with self._lock:
            counts: dict = {}
            for pattern, _cb in self._subs.values():
                counts[pattern] = counts.get(pattern, 0) + 1
            seen = dict(self._seen)
        out = []
        for pattern in sorted(counts):
            heard, when, command = seen.get(pattern, (0, 0.0, ""))
            out.append({"pattern": pattern, "subscribers": counts[pattern],
                        "heard": heard, "last": when, "command": command,
                        "alive": alive})
        return out

    # -- the child ------------------------------------------------------------
    def _sync(self) -> None:
        """Match the running capture to the patterns wanted right now. Idempotent.

        Serialised: see `_sync_lock`. Deciding and acting have to be one step, or two
        subscribers racing leave two captures behind.
        """
        with self._sync_lock:
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
        # THE EAR'S OWN THROTTLE, cut to a fraction. It exists to keep a burst of one
        # command from filling the log with markers, and its two-second default is fine
        # for an errand on a clock — but a rally is seconds long and the trigger waiting
        # on it must not sit out a throttle meant for tidiness (#1237). The panel's queue
        # coalesces the PRESSES anyway, so nothing is run twice by this.
        cmd += ["--cooldown", "0.3"]
        # MARKERS ONLY. The child's human line per match carries the push's payload, and
        # everything this child prints lands in the profile's panel.log — a file people
        # send each other when something goes wrong, so a mate's uid and an alliance id
        # have no business in it (#1293). What the ear heard is said here instead, by
        # counts, in `_note_heard`.
        cmd += ["--quiet"]
        # …AND THE ONE PAYLOAD THE PANEL CANNOT DO WITHOUT (#1323). Asked for
        # unconditionally rather than only when the auto-join is on: the ear is one
        # child for whatever this profile subscribes to, the fields line is only ever
        # built for a command already being matched, and a book that starts filling the
        # moment the ear opens is a book that has the banner in it when the trigger
        # fires. It costs a dict write per push and nothing else.
        cmd += ["--fields", FIELDS_PATTERN]
        # WHOSE traffic this ear is for. Two accounts of the same game dial the same
        # server port, so the capture filter cannot separate them and every profile's
        # ear has been hearing both — a trigger firing in one account off the other's
        # push. The profile's Windows session goes with the pids and the capture looks
        # them up again on its own clock, so an ear started before its client is not
        # deaf to the difference for the rest of the run (#1306).
        cmd += game_process.capture_narrowing(self._rt.settings)
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
        if line.startswith(FIELDS_MARKER):
            return self._on_fields(line)
        if not line.startswith(FIRE_MARKER):
            return None
        command = line[len(FIRE_MARKER):].strip()
        self._note_heard(command)
        with self._lock:
            wanted = [(pattern, cb) for pattern, cb in self._subs.values()]
        for pattern, callback in wanted:
            if pattern in command:
                with self._lock:
                    heard, _when, _cmd = self._seen.get(pattern, (0, 0.0, ""))
                    self._seen[pattern] = (heard + 1, time.monotonic(), command)
                try:
                    callback(command)
                except Exception:       # noqa: BLE001 — never let one kill the ear
                    self._rt.dbg("triggers").error(
                        "wire subscriber for %r raised", pattern, exc_info=True)
        return False

    def _on_fields(self, line: str):
        """A fields line: remember the banner it describes, and swallow the line.

        SWALLOWED WHATEVER HAPPENS (`False`), even when nothing could be made of it —
        it is machinery, like the marker, and the one thing it must never do is reach
        the profile's log, where the whole point of #1293 was to stop the wire's
        payloads from piling up.

        Never fires a subscriber. A trigger acts on the MARKER, which arrives beside
        this line and carries its own cooldown; this only fills the book that says what
        each banner is going for (`panel/runtime/rally_wire.py`).
        """
        parts = line.split("\t")
        try:
            self._rt.banners.note(rally_wire.parse_fields(parts[2] if len(parts) > 2
                                                          else ""))
        except Exception:               # noqa: BLE001 — a reading, never the ear
            self._rt.dbg("triggers").error("wire fields line unreadable", exc_info=True)
        return False

    def _note_heard(self, command: str) -> bool:
        """Tally one heard command; say what has piled up, at most every
        :data:`HEARD_NOTE_SEC`. Returns whether a line was written (the tests read it).

        The first command after a quiet stretch is said at once — «ухо живо» is worth
        one line — and everything after it is counted until the window is up. Only
        command NAMES and counts are ever said: the payload never reaches this side of
        the pipe any more, which is the whole point (#1293).
        """
        now = time.monotonic()
        with self._lock:
            self._heard[command] = self._heard.get(command, 0) + 1
            if now - self._heard_said < HEARD_NOTE_SEC:
                return False
            self._heard_said = now
            heard, self._heard = self._heard, {}
        total = sum(heard.values())
        top = sorted(heard.items(), key=lambda kv: (-kv[1], kv[0]))
        detail = ", ".join(f"{name}×{n}" for name, n in top[:HEARD_TOP])
        if len(top) > HEARD_TOP:
            detail += f", +{len(top) - HEARD_TOP}"
        self._rt.say("trigger", "triggers.log.heard", count=total, detail=detail)
        return True
