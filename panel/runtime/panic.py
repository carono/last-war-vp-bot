"""«Стоп всё» and «Включить обратно» — the two acts, and the mark that says they happened.

TWO ACTS AND ONLY TWO (#1393): **close the client, stop this profile's daemon.** That is
the whole of the press. It used to stop the schedule, every plugin tab's monitors, every
child, the scenario in flight and the activity strip as well — five different things to
keep in step with, each of which had to be put back by hand afterwards, and none of which
stopped the panel doing the one thing that mattered: it went on putting the client back.

What replaced the other four is a consequence rather than an act. With no daemon there is
nothing for a timer, a trigger, the watchdog or the recovery to press THROUGH, and
`panel/runtime/gate.py` is what turns that fact into «and so they do not try»: no
scenario, no read into the game, no relaunch, no retry, and no line every few seconds
saying that none of it worked. The panel holds still because there is nothing to hold it
still WITH, which is a state that cannot drift out of step with itself.

«Включить обратно» is therefore the inverse and just as short: bring the daemon back. The
gate opens by itself the moment it is up, and whatever the schedule was going to do it
does — once, not as a queue of everything it missed (`panel/timers.py`, #1333).


THE MARK is the other half, and it predates the two acts. The button used to say what it
had done in ONE line in the log, which scrolls away. Nothing on screen afterwards said
the panel was holding still; the profile simply did nothing, exactly as it would if
everything were merely idle.

That is not a hypothetical. On 2026-08-06 «Стоп всё» was pressed at 12:44, the line was
said, and the schedule stayed off for the rest of the day: the client lost its server at
18:58, died at 20:02 and was still dead two hours later, with the panel open in front of
somebody the whole time. Seven hours went past a log line.

So this holds two things and nothing else:

* **that the profile is stopped**, for as long as it is, so both front-ends can put a
  mark where a mark cannot scroll away;
* **when it happened**, so the mark can say «уже 7 часов» rather than «остановлено» —
  the number is what makes it uncomfortable enough to act on.

WHAT IT DOES NOT HOLD IS A SNAPSHOT OF ANYTHING. There is nothing to remember any more:
the press does not switch anybody's boxes off, so it has nothing to put back. A watcher
the person had deliberately left off comes back off, and one they had left on comes back
on, because neither was ever touched — which is the version of that promise that cannot
be got wrong.
"""
from __future__ import annotations

import threading
import time


class Panic:
    """One profile's «is everything stopped, and since when».

    Not thread-safe and not required to be: it is written from the button press and
    read from the paint, both on the Tk thread, and the web reads a snapshot dict.
    """

    __slots__ = ("_at", "_count")

    def __init__(self) -> None:
        #: When «Стоп всё» was last pressed, or 0.0 while the profile is running.
        self._at = 0.0
        #: How many times this session — so «нажали и забыли» and «нажимают всё время»
        #: do not look the same.
        self._count = 0

    @property
    def stopped(self) -> bool:
        return self._at > 0.0

    def mark(self, now: float) -> None:
        """«Стоп всё» was pressed."""
        self._at = now
        self._count += 1

    def clear(self) -> None:
        """«Включить обратно» was pressed — or a profile switch made the mark meaningless."""
        self._at = 0.0

    def state(self, now: float) -> dict:
        """What both front-ends draw. Numbers, never words (`CLAUDE.md`)."""
        return {"stopped": self.stopped,
                "for_sec": int(now - self._at) if self.stopped else 0,
                "count": self._count}


# -- the two acts -------------------------------------------------------------
#
# Here rather than in the shell because both front-ends press them and a standalone tab
# has no shell at all — and because two acts written down twice is how the window and
# the phone end up stopping different amounts of the same profile.


def stop(rt) -> None:
    """«Стоп всё» for ONE profile: close its client, then stop its daemon.

    In that order, and the order is not cosmetic: closing the client is done through the
    `quit_game` scenario (`CLAUDE.md` — the panel plays abilities, it does not write
    them), which asks the daemon for the pid it is holding. Stopping the daemon first
    would take away the one thing that knows WHICH client belongs to this profile, and
    on a machine with two accounts «the LastWar.exe» is the other person's session.

    Both acts happen on a worker: the scenario takes the game claim and the daemon's
    shutdown waits for a port to come free, and neither may be done on the Tk thread.
    The mark is set here, on the way in, so the window says «ВСЁ ОСТАНОВЛЕНО» from the
    moment of the press rather than a minute later when the client has finished closing.

    A client that is already gone is not a failure — `quit_game` is a no-op then — and a
    claim refused is not a reason to leave the daemon running: the press is what somebody
    reaches for when things have gone wrong, so the second act happens whatever the first
    one managed. Ending the daemon under a scenario in flight is not collateral damage
    either; it is the point. The run fails, says so, and nothing starts another.
    """
    rt.say("panel", "panic.log")
    rt.panic.mark(time.time())

    def second() -> None:
        stop_daemon(rt)
        # Said when both acts are DONE rather than when they were asked for: the whole
        # value of the line is that it names the state the panel is now in, and a client
        # takes seconds to close.
        rt.say("panel", "panic.done")

    def then() -> None:
        # On a thread of its own: `on_done` is delivered on the Tk thread, and stopping a
        # daemon blocks for as long as it takes a port to come free.
        threading.Thread(target=second, name="panel-panic", daemon=True).start()

    if not rt.play_async("quit_game", tag="game", on_done=then):
        # Nothing was played — something more urgent holds the client. The daemon still
        # goes, and with it everything that was going to press anything else.
        then()


def stop_daemon(rt) -> bool:
    """The second act on its own — and the gate is told, in the same breath.

    Whoever stops a daemon has to say so (`panel/runtime/gate.py::changed`), or the
    schedule spends up to eight seconds — the status poll's period — believing the last
    verdict it was given. An errand that believes a daemon is warm calls `ensure()`, and
    `ensure()` would start the very daemon this has just stopped.
    """
    try:
        return rt.game.stop()
    finally:
        rt.gate.changed()


def resume(rt) -> None:
    """«Включить обратно» for ONE profile: bring its daemon back, and clear the mark.

    The inverse of :func:`stop`, and deliberately not «start the client» as well: with a
    daemon up the gate opens, and whatever puts a client back — the six-hourly
    `restart_game`, the watchdog, the recovery — does it by itself, once. Starting one
    here as well would be the second relaunch racing the first, which is what the
    relaunch lock in `panel/runtime/host.py` exists to stop.

    On a worker for the same reason as its opposite: `ensure` waits for a daemon to come
    up, which is seconds.
    """
    rt.panic.clear()

    def work() -> None:
        try:
            rt.game.ensure()
        except Exception:                 # noqa: BLE001 — a press, never the panel
            rt.dbg("daemon").error("resume failed", exc_info=True)
        finally:
            rt.gate.changed()
            rt.say("panel", "panic.resumed")

    threading.Thread(target=work, name="panel-resume", daemon=True).start()


# -- the press, for the front-end that is not the window ----------------------
#
# «Включить обратно» has to be reachable from the phone for the same reason «Стоп всё»
# is worth having at all: the moment it matters is the moment nobody is standing at the
# machine. It is the SHELL's press — only the window knows which profiles are open and
# which tabs each of them has — so the shell registers what to run and everything else
# only asks whether there is anything registered, exactly as
# `panel/runtime/panel_control.py` does for the panel's own restart.
_handler = None


def set_handler(fn) -> None:
    """The shell says how «Включить обратно» is carried out. A standalone tab says nothing."""
    global _handler
    _handler = fn


def available() -> bool:
    """Is there anything that could carry the press out in this process?"""
    return _handler is not None


def run() -> bool:
    """Carry it out. ``False`` when there is nobody to — a tab launched on its own."""
    if _handler is None:
        return False
    _handler()
    return True
