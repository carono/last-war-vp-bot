"""The panel, reachable from a phone (#1221).

The bot runs where the game runs — a Windows machine with a client on it — and that is
not where its owner is standing. This package is the other half of the panel: the same
runtime, the same profile, the same scenarios, drawn in a browser instead of in a Tk
window, so «did the collection fire», «switch the base timer on» and «run the alliance
upkeep now» do not need the person to be at the machine.

It is a PLAYER, exactly as the window is. Nothing here presses the game: a request lands
on :class:`~panel.web.api.WebApi`, which asks the runtime — `rt.schedule` for the
errands, `rt.play_async` for a scenario, `rt.game` for whether the client is up — and
hands back what it said. There is no game logic in this package and none may be added;
an ability is one `src/lastwar_bot/actions/*.md` scenario and both front-ends play it.

    panel/web/api.py       the JSON surface: state, timers, scenarios, log, words
    panel/web/server.py    the socket, the token and the static files
    panel/web/static/      the page itself — no words in it, they come from /api/i18n
    panel/tabs/web.py      the switch, the address and the token, in the window

WHO STARTS IT. The «Веб» tab, from the profile's own knobs, which is what makes the
remote control a per-profile thing like the daemon port: two accounts farming at once
are two panels' worth of state and two ports. Switch the tab off and there is no server
— the plugin rule, doing exactly what it says.
"""
from __future__ import annotations

from .api import TAIL_LINES, WebApi, static_dir
from .server import COOKIE, DEFAULT_HOST, DEFAULT_PORT, WebServer, addresses

__all__ = ["WebApi", "WebServer", "addresses", "static_dir",
           "COOKIE", "DEFAULT_HOST", "DEFAULT_PORT", "TAIL_LINES"]
