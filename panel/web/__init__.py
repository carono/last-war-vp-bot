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
    panel/runtime/web_control.py  the switch, the port and the token — the WINDOW's
    panel/runtime/web_dialog.py   …and the modal that draws them, off the menu bar

WHO STARTS IT. The shell does, at boot, from the panel-wide block in
`profiles/settings.json` — because there is ONE server per window and it answers for
every profile that window has open. It used to be a per-profile tab, which meant a
window with three accounts open held three copies of one answer and obeyed whichever of
them switched on first (#1313). Switch it off in menu → «Веб» and there is no server:
no thread, no socket, nothing listening.
"""
from __future__ import annotations

from .api import TAIL_LINES, WebApi, static_dir
from .server import COOKIE, DEFAULT_HOST, WebServer, addresses, default_port

__all__ = ["WebApi", "WebServer", "addresses", "static_dir", "default_port",
           "COOKIE", "DEFAULT_HOST", "TAIL_LINES"]
