"""The `api` the service's HTTP half talks to: every route, answered by a PANEL.

`panel/web/server.py::WebServer` takes an `api=` object and asks it exactly two things —
`attach()` / `detach()` around its own lifetime, and `dispatch(method, path, query, body)`
per request. So the whole of the service's routing is this class: pick the panel the
request is about, hand it the request verbatim, hand back what it says.

NOT ONE ROUTE IS WRITTEN TWICE, and that is the point rather than a saving. A route added
to `panel/web/api.py` tomorrow is served through here the same day, with no table to keep
in step and no chance of the two disagreeing about what `/api/screen/press` means. The
service does not know what a screen IS.

THE ROUTES IT ANSWERS ITSELF are the ones no single panel can: which panels have dialled in
(`/api/panels`, and a POST to it puts ONE of them down or back by pid — the standard way
to clear a panel that should not be there, #1994), and the three the browser asks before
it has chosen an account —
`/api/profiles`, `/api/i18n` and `/api/words` — which have to work when no panel has
connected at all, or the phone shows an empty page with no way to tell «nothing is
running» from «the door is broken».
"""
from __future__ import annotations

from . import self_control
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

    # -- one named panel, put down or put back ------------------------------
    def press(self, body: dict) -> tuple:
        """`POST /api/panels {"action": "quit"|"restart", "pid": N}` — ONE process.

        THE STANDARD WAY TO REMOVE A PANEL THAT SHOULD NOT BE THERE, and it exists
        because there was none (#1994). Every other route is routed by PROFILE, which is
        right for anything about an account and cannot address a process: with two panels
        answering for one profile the request reaches whichever dialled in first, and the
        other one is unreachable for as long as it lives. The only way left was to kill
        it, which the person has forbidden — a killed panel leaves locks, children and a
        client nobody let go of.

        So it ASKS, through the panel's own `/api/panel`
        (`panel/runtime/panel_control.py`): the same orderly shutdown the window's ✕ runs,
        the same two presses both front-ends offer, and nothing here knows what either of
        them does.
        """
        action = str(body.get("action") or "").strip()
        if action not in ("quit", "restart"):
            return 400, {"error": "unknown_action", "action": action}
        try:
            pid = int(body.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid <= 0:
            # NAMING THE PANEL IS THE WHOLE POINT. Without a pid this would be the
            # profile route again, and «put down the panel» would mean «put down whichever
            # one answers» — the very thing that made eight of them impossible to clear.
            return 400, {"error": "no_pid"}
        panel = self.registry.by_pid(pid)
        if panel is None:
            return 404, {"error": "no_such_panel", "pid": pid}
        self._log(f"asking panel {pid} to {action}")
        return panel.ask("POST", "/api/panel", {}, {"action": action},
                         timeout=wire.ANSWER_TIMEOUT_SEC)

    # -- the routing --------------------------------------------------------
    def dispatch(self, method: str, path: str, query: dict, body: dict) -> tuple:
        query = dict(query or {})
        body = dict(body or {})
        if path == "/api/service":
            # THE SERVICE'S OWN LIFE, and the only route here that is about this process
            # rather than about a panel (`panel/service/self_control.py`). It is the
            # answer to the thing #1994 ran into last: the panel-side fix was delivered in
            # one press and the service-side one could not be delivered at all, because a
            # service started by Windows is restarted by Windows and nothing could ask.
            if str(method or "").upper() == "POST":
                if str(body.get("action") or "") != self_control.RESTART:
                    return 400, {"error": "unknown_action",
                                 "action": str(body.get("action") or "")}
                said = self_control.restart(log=self._log)
                return (200 if said.get("ok") else 503), said
            return 200, self_control.state()
        if path == "/api/panels":
            if str(method or "").upper() == "POST":
                return self.press(body)
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
