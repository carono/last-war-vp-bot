"""The client's life — start it, close it, put it back — as one table both front-ends read.

Three presses, and every one of them is a scenario: `launch_game`, `quit_game`,
`restart_game`. Nothing here drives the game. What this module holds is the four things
the WINDOW and the PHONE must agree about, and which were about to be written down
twice:

* **which scenario a press plays** — so «Перезапустить» cannot come to mean one recipe
  in the window and another on the phone;
* **what the log says before it starts** — so a person reading the log afterwards cannot
  tell which front-end the press came from, because it does not matter and should not;
* **the word on the button** — one locale key, said by `self.t` in the window and by
  `T()` in the browser out of the same table;
* **when the press is meaningless** — «Закрыть» with no client, «Запустить» with one
  already up. A disabled button is the honest version of a press that would have gone
  to a scenario to be refused there.

That last one is the reason this is a table and not two `if`s. The two front-ends read
the client's state through the same probe (`panel/runtime/game_process.py`) and would
have each decided for themselves what to do with it — and the moment those decisions
drift, the phone offers a press the window greys out, with no way for either to know
which is right (`CLAUDE.md`, «An edit travels between the window and the web»).

WHY THE LINK AND NOT `running`. Availability is decided on the four-state link, because
the interesting case is the stranded client: the process is there, the server has hung
up, and the person is looking at the phone precisely because something is wrong. «Стоп»
and «Перезапустить» must be pressable then — that client is exactly the one worth
restarting — and «Запустить» must not, because there is already a client and a second
one is not what was asked for.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import game_process

#: The ids a press travels under — on the wire from the phone, and in the window's
#: handlers. Deliberately not the scenario names: what a button IS outlives which
#: recipe it happens to play.
LAUNCH = "launch"
QUIT = "quit"
RESTART = "restart"


@dataclass(frozen=True)
class Control:
    """One press of the client's lifecycle, in both front-ends."""

    id: str
    #: The ability itself: `src/lastwar_bot/actions/<scenario>.md`, played by
    #: `rt.play_async`. The panel presses scenarios and writes none (CLAUDE.md).
    scenario: str
    #: Said in the log before the scenario starts, so the log shows the intent even
    #: when the run then fails inside the recipe.
    saying: str
    #: The word on the button — the SAME key in the window and in the browser.
    label: str
    #: Does this press want a client to exist? True: only with one. False: only
    #: without. The stranded client counts as one (see the module docstring).
    wants_client: bool
    #: The question asked before it happens, or "" to press straight away. A phone
    #: asks it as a dialog; the window asks it as a message box. Only the two
    #: destructive ones have it — a thumb slips more easily than a cursor, and
    #: «Запустить» costs nothing worse than a client.
    confirm: str = ""


#: In the order both front-ends draw them: the one that creates, then the one that
#: destroys, then the one that does both.
CONTROLS = (
    Control(LAUNCH, "launch_game", "log.game.launching", "game.launch",
            wants_client=False),
    Control(QUIT, "quit_game", "log.game.quitting", "game.quit",
            wants_client=True, confirm="game.confirm.quit"),
    Control(RESTART, "restart_game", "log.game.restarting", "game.restart",
            wants_client=True, confirm="game.confirm.restart"),
)

BY_ID = {control.id: control for control in CONTROLS}

#: The tag every one of them logs and claims under. `restart_game` already used it and
#: `launch_game` did not, which meant one of the two lifecycle presses was filed in the
#: log under «action» — the same word as any scenario a person happened to run by hand.
TAG = "game"


def get(action: str):
    """The control ``action`` names, or ``None`` — an unknown id is never a press."""
    return BY_ID.get(str(action or ""))


def is_up(link: str) -> bool:
    """Is there a client to act on, given the four-state link?

    Everything except `offline` is a client: `lost` is one that cannot reach the
    server, `unknown` is one whose sockets could not be read (an ordinary answer for a
    second account, and not a fault). Both are clients, and both are worth restarting.
    """
    return str(link or game_process.OFFLINE) != game_process.OFFLINE


def available(control, link: str) -> bool:
    """May ``control`` be pressed with the client in state ``link``?"""
    return bool(control) and control.wants_client == is_up(link)


def state(link: str, running: str = "") -> list:
    """The three presses as the phone receives them — id, word, question, may-I.

    Everything the browser needs to draw the row and nothing it could get wrong: it
    does not know which scenario a press plays, and cannot be taught to, because the
    press travels as an id and this module resolves it.

    ``enabled`` is the WINDOW's rule exactly — the link, and nothing else — so a button
    one front-end greys is greyed on the other. ``running`` is not a rule but a
    reading: which of the three is being played this second. The window says that on
    its activity strip and in its log, both of which are on screen the whole time; a
    phone showing one card at a time has neither in view, so it marks the button. How a
    thing is DRAWN is each front-end's own (CLAUDE.md); which things there are, and when
    they may be pressed, is this table's.
    """
    return [{"id": control.id, "label": control.label,
             "confirm": control.confirm,
             "enabled": available(control, link),
             "running": bool(running) and control.scenario == running}
            for control in CONTROLS]


def play(rt, action: str, link: str | None = None) -> dict:
    """Say the line and play the scenario — the whole of what a press does.

    ``link`` is what the presser believed the client was doing. Given, it is checked:
    a phone that has been in a pocket for a minute may well be showing a «Стоп» for a
    client that is already gone, and pressing it would run a recipe to no purpose. Left
    out (the window, which greys its buttons off the same reading a moment earlier),
    only the claim decides.

    Comes back as the front-ends' shared vocabulary: ``ok`` it started, ``busy``
    something else is driving this client, ``unavailable`` the press does not apply to
    the client as it is now.
    """
    control = get(action)
    if control is None:
        return {"error": "unknown"}
    if link is not None and not available(control, link):
        return {"ok": False, "unavailable": True, "id": control.id}
    rt.say(TAG, control.saying)
    started = rt.play_async(control.scenario, tag=TAG)
    return {"ok": bool(started), "busy": not started, "id": control.id,
            "name": control.scenario}
