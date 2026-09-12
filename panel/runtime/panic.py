"""The one act a profile's switch causes: let this profile's game link go.

WHO PRESSES THIS. Nobody, directly, any more (#1882). «Стоп всё» and «Включить обратно»
were buttons; what there is now is one checkbox per profile — «Профиль работает» — and
`panel/runtime/power.py` is the flag behind it. This file is what the flag DOES when it
moves, and it is a file of its own for the same reason it always was: two acts written
down twice is how the window and the phone end up stopping different amounts of the same
profile.

ONE ACT AND ONLY ONE (#2824): **let this profile's game link go.** It used to stop the
schedule, every plugin tab's monitors, every child, the scenario in flight and the
activity strip as well — five different things to keep in step with, each of which had to
be put back by hand afterwards, and none of which stopped the panel doing the one thing
that mattered: it went on putting the client back. #1393 cut those five down to two —
close the client, then let the link go — and #2824 cut the first of those two as well.

THE CLIENT IS NOT CLOSED ANY MORE, and it is the person's decision, in their words:
«Кнопка Профиль работает не должна вырубать клиент, а только работу панели выключать для
этого профиля». The switch answers «does the PANEL work on this account», and a person
who stops the panel is usually a person who wants to play that account by hand — the old
press took the game away from them to prove it had stopped. Stopping the panel is now
exactly that and no more: no errand, no trigger, no reading, no watchdog, no relaunch,
and a client left running for whoever wants to play it.

CLOSING THE CLIENT IS STILL A PRESS — «Состояние» has had it all along
(`panel/runtime/game_control.py`, the `quit_game` scenario). What changed is that it is a
press somebody makes on purpose rather than a side effect of a switch about the panel.

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


# -- the acts ------------------------------------------------------------------
#
# Here rather than in the shell because both front-ends press them and a standalone tab
# has no shell at all — and because an act written down twice is how the window and the
# phone end up stopping different amounts of the same profile.


def stop(rt) -> None:
    """The switch going OFF for ONE profile: let its game link go, and nothing else.

    THE CLIENT IS LEFT ALONE (#2824). This used to play `quit_game` first and let the
    link go after it, on the reasoning that «выключен» had to mean the account was not
    playing. It means the PANEL is not playing it: the person who switches a profile off
    is usually the person who wants to sit down at that account by hand, and closing
    their client to prove the panel had stopped is the opposite of what the switch is
    for. What stops is everything automatic — with the link let go there is nothing for a
    timer, a trigger, the watchdog or the recovery to press THROUGH, and
    `panel/runtime/gate.py` shuts on the flag rather than on the port, so a link somebody
    takes by hand opens nothing either.

    On a worker: letting a link go waits for a port to come free, and that may not be
    done on the Tk thread. The line is said on the way in so the window says «ВЫКЛЮЧЕНО»
    from the moment of the press, and again when the act is done.

    THE FLAG IS ALREADY WRITTEN when this runs: the switch is persisted by
    `panel/runtime/power.py::set_on`, which then calls this. Nothing here reads or writes
    it — an act that decided for itself whether it was allowed is an act that can
    disagree with the switch drawn on screen.
    """
    rt.say("panel", "panic.log")

    def work() -> None:
        let_link_go(rt)
        # Said when the act is DONE rather than when it was asked for: the whole value of
        # the line is that it names the state the panel is now in.
        rt.say("panel", "panic.done")

    threading.Thread(target=work, name="panel-panic", daemon=True).start()


def let_link_go(rt) -> bool:
    """Letting the link go on its own — and the gate is told, in the same breath.

    Whoever lets a link go has to say so (`panel/runtime/gate.py::changed`), or the
    schedule spends up to eight seconds — the status poll's period — believing the last
    verdict it was given. An errand that believes a daemon is warm calls `ensure()`, and
    `ensure()` would start the very daemon this has just stopped.
    """
    try:
        return rt.game.let_go()
    finally:
        rt.gate.changed()


def resume(rt) -> None:
    """The switch going back ON for ONE profile: take hold of its client again.

    The inverse of :func:`stop`, and deliberately not «start the client» as well: with
    the link back the gate opens, and whatever puts a client back — the six-hourly
    `restart_game`, the watchdog, the recovery — does it by itself, once. Starting one
    here as well would be the second relaunch racing the first, which is what the
    relaunch lock in `panel/runtime/host.py` exists to stop.

    On a worker for the same reason as its opposite: an attach is seconds.
    """
    def work() -> None:
        try:
            rt.game.ensure()
        except Exception:                 # noqa: BLE001 — a press, never the panel
            rt.dbg("link").error("resume failed", exc_info=True)
        finally:
            rt.gate.changed()
            rt.say("panel", "panic.resumed")

    threading.Thread(target=work, name="panel-resume", daemon=True).start()
