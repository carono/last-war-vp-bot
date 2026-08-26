"""The DOOR: one process per machine that owns the port and routes to the panels.

`docs/research/panel-service-and-spa-plan.md` §1 in code. What lives here is everything
the panel's own remote control already was — the port, the token, TLS, the SPA bundle —
minus the one thing it could never be: something that is up before anybody signs in and
stays up when they sign out.

**IT NEVER TOUCHES THE GAME, AND IT SUPERVISES NOTHING.** A service runs in session 0: no
desktop, no window station, no foreground, no screen. Input, screenshots, finding the
game's window and the il2cpp attach all need those four, so every one of them stays in the
PANEL, which comes up with its Windows session exactly as the session's own programs do.
The service starts no panel and restarts none — there is no process anybody has to bring
up, so there is nothing that can fail to come up. What it gives, and the panel's own
server never could: the cure stops being locked behind the illness. A panel that is not
answering is still reachable from outside, and so is the machine before anybody logs in.

THE PANEL CONNECTS OUT; nothing connects in. That is what makes it work across Windows
sessions without a token, an ACL or a firewall hole per session: session 0 may not reach
into an interactive session, but an interactive session may always dial a loopback port.

THE ROUTING IS THE PANEL'S OWN API, VERBATIM. `panel/web/api.py::WebApi.dispatch` already
answers `(method, path, query, body) -> (status, payload)` for the whole surface, and the
HTTP half already takes an `api=` object (`panel/web/server.py::WebServer`). So the
service is: a listener for panels, a register of the ones that have dialled in, and an
`api` whose `dispatch` hands the request to one of them and waits for the answer. Not one
route is written twice, and a route added to the panel tomorrow is served by the service
the same day.
"""
