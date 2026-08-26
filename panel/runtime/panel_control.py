"""The PANEL's own life — putting it back on the code that is now on disk (#1258).

An edited `.py` is picked up by a fresh interpreter and by nothing else: the panel is
imported once and never reloaded, which is the same reason a successful `git pull` means
"restart me" rather than "done" (panel/runtime/updates.py). So «перезапустить панель» is
an ordinary thing to want several times a day — and until now it was reachable from
exactly one place: a button that appeared only after an update, in a window the person is
not standing at precisely when they most want it.

This is `panel/runtime/game_control.py` for the panel instead of for the client, one row
long. It holds the four things the WINDOW and the PHONE must agree about — the word on
the button, the question asked first, the line said in the log, and whether the press
applies at all — so neither front-end can come to mean something of its own by it.

WHY A REGISTERED HANDLER, NOT A FUNCTION. Closing the window is the SHELL's and nobody
else's: `_on_close` is what writes every profile out, stops the tabs' children and lets
the instance lock go, and a replacement started before that would read a settings file
the old window has not finished with. A runtime knows nothing about a window, so the
shell registers what to run (:func:`set_handler`) and everyone else only asks whether
there is one. A tab launched on its own — `python -m panel.tabs.<id>` — registers
nothing, and then there is no press to offer: that process is not the panel, and ending
it would not be a restart.

WHAT SURVIVES IT, which is what makes this safe to hand to a phone:

* **the profiles that are open.** `Workspace.restore` opens what the last window had,
  off `panel/settings.json`, which every open, close and switch writes
  (panel/runtime/workspace.py). The command line is repeated as it was, too
  (`updates.relaunch`), so a `--profile` still names the page that comes up first.
* **the address the person is holding.** The web server's port and token are the
  PANEL's own knobs, in `profiles/settings.json`, and the shell binds the socket while
  it is building the window (panel/runtime/web_control.py, #1313) — so the new panel
  comes up on the same socket with the same token, and the browser's cookie is still the
  right one. The page says «нет связи» for as long as the boot takes and comes back by
  itself on the next poll.
* **the game and the daemon.** Separate processes holding a warm Lua VM and a client;
  nothing here touches either, and the new panel attaches to the same daemon.

WHY IT WAITS. The press arrives on an HTTP worker thread, and the answer to it is
written on that same thread — pulling the interpreter out from under it would leave the
phone with a dead socket and no way to tell «перезапускается» from «упало». So the
handler is armed on the Tk thread a moment later (:data:`DELAY_MS`) and the request
finishes normally in between. The window's own press goes the same way for the same
reason: the button that was clicked is still redrawing itself.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

#: The id the press travels under — on the wire from the phone, and in the window's
#: handler. Not the name of what it does, for the same reason the client's three are
#: not their scenarios: what a button IS outlives how it is carried out.
RESTART = "restart"
QUIT = "quit"


@dataclass(frozen=True)
class Control:
    """One press on the panel itself, in both front-ends."""

    id: str
    #: The word on the button — the SAME key in the window and in the browser.
    label: str
    #: The question asked before it happens. A phone asks it as a dialog, the window as
    #: a message box, and both out of this one key. Never empty here: this press ends
    #: the very thing the person is using, and a thumb slips more easily than a cursor.
    confirm: str
    #: Said in the log before anything is closed, so the record shows the intent even if
    #: the shutdown then goes wrong halfway.
    saying: str


#: Two rows: put the panel back on the code that is on disk, and put it down.
#:
#: THE SECOND ONE IS NOT A RESTART WITHOUT THE SECOND HALF, whatever the code says. A
#: restart is routine — it costs seconds and the panel comes back with everything open.
#: Stopping is the end of the evening: the schedule stops, the monitors stop, nothing
#: is watching the accounts any more, and the only way back is somebody at the machine.
#: That is why it asks a question of its own rather than sharing the restart's.
CONTROLS = (
    Control(RESTART, "panel.restart", "panel.restart.confirm", "log.panel.restarting"),
    Control(QUIT, "panel.quit", "panel.quit.confirm", "log.panel.quitting"),
)

BY_ID = {control.id: control for control in CONTROLS}

#: The tag it is logged under. The panel's own doings, like the boot and the profile
#: switch — not «action», which is a scenario somebody ran.
TAG = "panel"

#: How long the press is left pending before the floor comes out. Long enough for an
#: HTTP answer to be written and flushed on the thread that asked, short enough that
#: nobody presses twice wondering whether it took.
DELAY_MS = 1200

#: The Ticker chain a pending press is armed under. Named, so a second press re-arms
#: the one shutdown instead of queueing another — and one name for both, because
#: «restart» and «quit» are two answers to the same question and the last one asked is
#: the one meant.
TICK = "panel-restart"

#: WHAT ACTUALLY DOES IT, in THIS process — set by the shell, one per press.
#:
#: Process-wide rather than per runtime because it is a fact about the PROCESS: one
#: window, however many profiles are open in it, and either press is all of them at once.
_HANDLERS: dict = {}
_LOCK = threading.Lock()


def set_handler(func, action: str = RESTART) -> None:
    """The shell says how one press is carried out. ``None`` takes it away."""
    with _LOCK:
        if func is None:
            _HANDLERS.pop(str(action), None)
        else:
            _HANDLERS[str(action)] = func


def handler(action: str = RESTART):
    """What that press would run, or ``None`` in a process that is not a panel."""
    with _LOCK:
        return _HANDLERS.get(str(action))


def available(action: str = RESTART) -> bool:
    """Is there a panel here that can do that at all?"""
    return handler(action) is not None


def get(action: str):
    """The control ``action`` names, or ``None`` — an unknown id is never a press."""
    return BY_ID.get(str(action or ""))


def state() -> list:
    """The press as the phone receives it — id, word, question, may-I.

    EMPTY when this process cannot restart itself. A greyed-out button would be the
    honest drawing of a press that is merely unavailable *right now* (which is what the
    client's three are); this one is not available in that sense — it does not exist
    here — and a permanently dead button is noise the window has always refused to draw.
    """
    return [{"id": control.id, "label": control.label, "confirm": control.confirm,
             "enabled": True}
            for control in CONTROLS if available(control.id)]


def request(rt, action: str = RESTART) -> dict:
    """Say the line and set the restart going — the whole of what a press does.

    Comes back in the front-ends' shared vocabulary: ``ok`` it is happening,
    ``unavailable`` there is no panel in this process to restart. There is no ``busy``
    — a scenario in flight is not a reason to refuse, it is a reason the question was
    asked, and everything it holds is let go by `_on_close` the same way it would be if
    the person closed the window.
    """
    control = get(action)
    if control is None:
        return {"error": "unknown"}
    func = handler(control.id)
    if func is None:
        return {"ok": False, "unavailable": True, "id": control.id}
    rt.say(TAG, control.saying)
    _arm(rt, func)
    return {"ok": True, "id": control.id, "delay_ms": DELAY_MS}


def _arm(rt, func) -> None:
    """Run ``func`` on the Tk thread, :data:`DELAY_MS` from now — see the docstring.

    Two hops, both of them deliberate: `post` is the only hand-over a worker thread may
    make (panel/runtime/tick.py), and `arm` is a real `after` delay, which may only be
    asked for from the Tk thread. A runtime with no window — a test, a bare harness —
    has neither, and nothing is drawing an answer there either, so it simply happens.
    """
    if getattr(rt, "root", None) is None:
        # NO WINDOW. Which used to mean «a test, a bare harness — nothing is drawing an
        # answer there either», and stopped being true the day the panel could run with
        # no window at all (#1976): the phone IS the front-end then, and it is waiting on
        # the very socket this press arrived on. So the delay is kept, on the clock this
        # process actually has — `ThreadTicker`, which is its own thread. A `Ticker`
        # without a widget arms NOTHING, so it is told apart by name rather than trusted.
        tick = getattr(rt, "tick", None)
        if tick is not None and getattr(tick, "THREADED", False):
            tick.arm(TICK, DELAY_MS, func)
        else:
            func()
        return
    rt.post(lambda: rt.tick.arm(TICK, DELAY_MS, func))
