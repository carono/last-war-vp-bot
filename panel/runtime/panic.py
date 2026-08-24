"""The two acts a profile's switch causes: close the client, stop this profile's daemon.

WHO PRESSES THIS. Nobody, directly, any more (#1882). «Стоп всё» and «Включить обратно»
were buttons; what there is now is one checkbox per profile — «Профиль работает» — and
`panel/runtime/power.py` is the flag behind it. This file is what the flag DOES when it
moves, and it is a file of its own for the same reason it always was: two acts written
down twice is how the window and the phone end up stopping different amounts of the same
profile.

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


THE MARK IS NOT HERE ANY MORE (#1882). It used to be — a `Panic` object holding «is this
profile stopped, and since when», in memory, for the length of one run of the panel. It
is a SETTING now (`panel/runtime/power.py`): the switch is written into the profile's own
`config.json`, so it survives a restart, and the mark both front-ends draw is read off
the same flag rather than off a second state that could disagree with it.

Why that mattered: the button used to say what it had done in ONE line in the log, which
scrolls away, and on 2026-08-06 that cost seven hours — «Стоп всё» was pressed at 12:44,
the client lost its server at 18:58, died at 20:02 and was still dead two hours later,
with the panel open in front of somebody the whole time. A restart in the middle of that
would have quietly started everything again, which is the other half of the same fault.

WHAT NEITHER ACT HOLDS IS A SNAPSHOT OF ANYTHING. Nothing is remembered because nothing
is touched: no watcher's box is switched off, so a watcher the person had deliberately
left off comes back off and one they had left on comes back on — the version of that
promise that cannot be got wrong.
"""
from __future__ import annotations

import threading


# -- the two acts -------------------------------------------------------------
#
# Here rather than in the shell because both front-ends press them and a standalone tab
# has no shell at all — and because two acts written down twice is how the window and
# the phone end up stopping different amounts of the same profile.


def stop(rt) -> None:
    """The switch going OFF for ONE profile: close its client, then stop its daemon.

    In that order, and the order is not cosmetic: closing the client is done through the
    `quit_game` scenario (`CLAUDE.md` — the panel plays abilities, it does not write
    them), which asks the daemon for the pid it is holding. Stopping the daemon first
    would take away the one thing that knows WHICH client belongs to this profile, and
    on a machine with two accounts «the LastWar.exe» is the other person's session.

    Both acts happen on a worker: the scenario takes the game claim and the daemon's
    shutdown waits for a port to come free, and neither may be done on the Tk thread.
    The mark is set here, on the way in, so the window says «ВСЁ ОСТАНОВЛЕНО» from the
    moment of the press rather than a minute later when the client has finished closing.

    THE FLAG IS ALREADY WRITTEN when this runs: the switch is persisted by
    `panel/runtime/power.py::set_on`, which then calls this. Nothing here reads or writes
    it — an act that decided for itself whether it was allowed is an act that can
    disagree with the switch drawn on screen.

    A client that is already gone is not a failure — `quit_game` is a no-op then — and a
    claim refused is not a reason to leave the daemon running: the press is what somebody
    reaches for when things have gone wrong, so the second act happens whatever the first
    one managed. Ending the daemon under a scenario in flight is not collateral damage
    either; it is the point. The run fails, says so, and nothing starts another.
    """
    rt.say("panel", "panic.log")

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

    # A PRESS, and it has to be (#1910): this IS the switch being flipped off, and a
    # gate that held it would leave the client running for ever in a profile somebody
    # had just switched off — the gate holding its own cure.
    if not rt.play_async("quit_game", tag="game", on_done=then, human=True):
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
    """The switch going back ON for ONE profile: bring its daemon back.

    The inverse of :func:`stop`, and deliberately not «start the client» as well: with a
    daemon up the gate opens, and whatever puts a client back — the six-hourly
    `restart_game`, the watchdog, the recovery — does it by itself, once. Starting one
    here as well would be the second relaunch racing the first, which is what the
    relaunch lock in `panel/runtime/host.py` exists to stop.

    On a worker for the same reason as its opposite: `ensure` waits for a daemon to come
    up, which is seconds.
    """
    def work() -> None:
        try:
            rt.game.ensure()
        except Exception:                 # noqa: BLE001 — a press, never the panel
            rt.dbg("daemon").error("resume failed", exc_info=True)
        finally:
            rt.gate.changed()
            rt.say("panel", "panic.resumed")

    threading.Thread(target=work, name="panel-resume", daemon=True).start()
