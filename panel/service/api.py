"""The `api` the service's HTTP half talks to: every route, answered by a PANEL.

`panel/web/server.py::WebServer` takes an `api=` object and asks it exactly two things —
`attach()` / `detach()` around its own lifetime, and `dispatch(method, path, query, body)`
per request. So the whole of the service's routing is this class: pick the panel the
request is about, hand it the request verbatim, hand back what it says.

NOT ONE ROUTE IS WRITTEN TWICE, and that is the point rather than a saving. A route added
to `panel/web/api.py` tomorrow is served through here the same day, with no table to keep
in step and no chance of the two disagreeing about what `/api/screen/press` means. The
service does not know what a screen IS.

THE FOUR IT ANSWERS ITSELF are the ones no single panel can: which panels have dialled in
(`/api/panels`), and the three the browser asks before it has chosen an account —
`/api/profiles`, `/api/i18n` and `/api/words` — which have to work when no panel has
connected at all, or the phone shows an empty page with no way to tell «nothing is
running» from «the door is broken».
"""
from __future__ import annotations

from . import wire


class ServiceApi:
    """Routes to the panels; answers for itself only where it must."""

    def __init__(self, registry, log=None) -> None:
        self.registry = registry
        self._log = log or (lambda line: None)

    # -- the server's own lifetime ------------------------------------------
    def attach(self) -> None:
        """The panel's API taps its profiles' logs here. The service has none of its own."""

    def detach(self) -> None:
        pass

    # -- the routing --------------------------------------------------------
    def dispatch(self, method: str, path: str, query: dict, body: dict) -> tuple:
        query = dict(query or {})
        body = dict(body or {})
        if path == "/api/panels":
            return 200, {"panels": [p.state() for p in self.registry.all()],
                         "profiles": self.registry.profiles()}
        who = str(body.get("profile") or query.get("profile") or "")
        panel = self.registry.for_profile(who)
        if panel is None:
            # NO PANEL IS A STATE, NOT AN ERROR. The machine is up, the door answers, and
            # nobody has signed in — which is precisely the state this service exists to
            # be visible in. The page has to be able to say so, so the two routes it draws
            # itself with answer emptily rather than failing.
            if path in ("/api/profiles", "/api/panels"):
                return 200, {"profiles": [], "home": "", "lights": [], "showing": "",
                             "panels": []}
            return 503, {"error": "no_panel"}
        return panel.ask(method, path, query, body, timeout=wire.ANSWER_TIMEOUT_SEC)
