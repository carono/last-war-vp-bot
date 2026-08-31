"""The panel's end of the service: dial out, answer what is asked, never listen.

`panel/service/` is the door — the port, the token, TLS and the SPA — and it lives in
session 0 where nothing may touch the game. This is the other half: a thread in the PANEL
that opens a socket TO the service and answers requests on it with the panel's own
`panel/web/api.py::WebApi`, which is the same object the panel's own remote control uses.

WHY OUT AND NOT IN. A service in session 0 cannot reach into an interactive session — no
window station, no desktop, and no port it may open there — but a program in a session may
always dial a loopback port. So the direction is fixed by Windows rather than chosen, and
it is the reason this needs no ACL, no per-session token and no firewall hole.

IT RETRIES FOR EVER, QUIETLY. The service may not be installed, may be stopped, may be
being restarted; the panel is perfectly usable meanwhile through its own window and its own
port. So a failed dial is one line the first time and silence afterwards, and the thread
goes on trying at :data:`RETRY_SEC` until it is told to stop or the panel closes.

NOTHING HERE DECIDES ANYTHING. Every request is handed to `WebApi.dispatch` exactly as the
HTTP handler hands it, and every answer goes back verbatim. A route added to the panel is
served through the service the same day, with no table anywhere to keep in step.
"""
from __future__ import annotations

import os
import socket
import threading
import time

from ..service import wire
from ..service.door import DEFAULT_DOOR_PORT, DOOR_HOST

#: How long between dials while the service is not there. Long enough that a machine with
#: no service installed pays nothing worth measuring, short enough that starting one is
#: not followed by a wait somebody notices.
RETRY_SEC = 15.0

#: The environment variables a machine that is not ordinary sets, exactly as every other
#: address in this repository is asked for rather than assumed (`CLAUDE.md`).
HOST_ENV, PORT_ENV = "LW_SERVICE_HOST", "LW_SERVICE_PORT"


def door_address() -> tuple:
    """Where the service's panel door is — asked, never spelled here twice."""
    host = (os.environ.get(HOST_ENV) or "").strip() or DOOR_HOST
    try:
        port = int((os.environ.get(PORT_ENV) or "").strip() or DEFAULT_DOOR_PORT)
    except ValueError:
        port = DEFAULT_DOOR_PORT
    return host, port


#: The one link THIS process has, for :func:`announce` to find. Process-wide for the same
#: reason `panel/runtime/panel_control.py`'s handler is: there is one panel here, and
#: which service it is talking to is a fact about the process rather than about a runtime.
_LINK = None


def announce() -> bool:
    """Say the profile list again, because it has just changed (#2068).

    THE LIST WAS A SNAPSHOT WITH NO WAY TO MOVE. `hello` is sent once per connection and
    carries the profiles the panel had at that moment; the service files it under the
    panel and routes by it for the life of the socket. So a profile opened afterwards was
    a profile the service did not know anybody had — `for_profile` answered `None`, the
    door said `no_such_profile` about an account that was farming, and the keeper counted
    it as missing and went looking for somewhere to start it. The only thing that stopped
    a second panel being started on top of it was the instance lock, which is a backstop
    and not an answer.

    Called from `panel/runtime/profile_control.py` on every open and close that WORKED,
    which is every route either front-end has. Not a clock and not a poll: the list moves
    when a person moves it, and that is the moment it is said.

    Returns whether it went. `False` — no link, or not connected — is ordinary and costs
    nothing: the next dial sends a fresh `hello` with the list as it is by then.
    """
    link = _LINK
    if link is None:
        return False
    return link.announce()


class ServiceLink:
    """One panel's connection to the service. Started by the shell, stopped with it."""

    def __init__(self, api, *, session: str = "", profiles=None, version: str = "",
                 boot=None, log=None, address=None) -> None:
        self.api = api
        self.session = str(session or "")
        #: A CALLABLE, not a list: which profiles a window has open changes while it runs,
        #: and a snapshot taken at boot would route a request for a profile opened later
        #: to nobody at all.
        self._profiles = profiles if callable(profiles) else (lambda: list(profiles or ()))
        self.version = str(version or "")
        #: THE STAMP OF THE CODE THIS PROCESS IMPORTED (`panel/runtime/updates.py::boot`)
        #: — pid, when it was imported, and the commit it came from. Announced beside the
        #: version because the version is not proof of anything: it is computed off git
        #: whenever it is asked, so it moves on a commit with no restart at all, and a
        #: register of panels showing it says nothing about which of them is running what
        #: (#1994).
        self.boot = dict(boot or {})
        self._log = log or (lambda line: None)
        self._address = address or door_address
        self._stop = threading.Event()
        self._thread = None
        self._sock = None
        self._said_down = False
        #: How many requests this link has answered — what «Состояние» can show and what
        #: a test asserts on without reaching into the socket.
        self.answered = 0
        self.connected = False

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        global _LINK                          # noqa: PLW0603 — one panel per process
        _LINK = self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="service-link",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        global _LINK                          # noqa: PLW0603
        if _LINK is self:
            _LINK = None
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            # SHUT DOWN BEFORE CLOSING. A `close()` from another thread does not
            # necessarily wake a `recv` that is already blocked on the socket — the
            # service went on holding a panel that had gone, and everything that asked it
            # anything waited out the whole answer timeout for nothing.
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self._thread = None

    # -- the loop -----------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._session_once()
            except Exception as exc:            # noqa: BLE001 — one dial, never the panel
                self._log(f"[service] {type(exc).__name__}: {exc}")
            if self._stop.wait(RETRY_SEC):
                return

    def _session_once(self) -> None:
        host, port = self._address()
        try:
            sock = socket.create_connection((host, port), timeout=5.0)
        except OSError as exc:
            if not self._said_down:
                self._said_down = True
                self._log(f"[service] not answering on {host}:{port} ({exc}) — "
                          f"the panel works on its own port meanwhile")
            return
        sock.settimeout(None)
        self._sock = sock
        self._said_down = False
        self.connected = True
        self._log(f"[service] connected to {host}:{port}")
        try:
            sock.sendall(wire.dumps({"hello": self._hello()}))
            for frame in wire.reader(sock):
                if "id" in frame:
                    self._answer(sock, frame)
                elif "ping" in frame:
                    sock.sendall(wire.dumps({"pong": 1}))
        finally:
            self.connected = False
            self._sock = None
            try:
                sock.close()
            except OSError:
                pass
            self._log("[service] connection closed")

    def _hello(self) -> dict:
        """What this panel IS, as the service files it. Read fresh every time it is said.

        `profiles` is asked of the callable rather than remembered, which is the whole
        point of it being one: the list is right at the moment of speaking, whether that
        is the first dial or an :func:`announce` after a profile was opened.
        """
        return {"session": self.session, "pid": os.getpid(),
                "version": self.version, "boot": dict(self.boot),
                "profiles": list(self._profiles() or ())}

    def announce(self) -> bool:
        """Re-say `hello` on the live socket. ``False`` when there is nothing to say it on.

        The service's `Panel.hello` simply overwrites what it holds, so this needs no new
        frame kind and no version negotiation: an older service files the same dictionary
        it filed at the dial, and a newer panel talking to it loses nothing.
        """
        sock = self._sock
        if sock is None or not self.connected:
            return False
        try:
            sock.sendall(wire.dumps({"hello": self._hello()}))
        except OSError:
            # The link is going down and the retry loop will dial again with a fresh
            # list. Never the caller's problem: this is said from inside a press.
            return False
        return True

    def _answer(self, sock, frame: dict) -> None:
        """One request, answered on a worker of its own.

        ON ITS OWN THREAD because a request may take seconds — a press hands work to the
        Tk thread and waits a moment for it — and a link that answered them one after the
        other would make a slow screen hold up every other request the service sends,
        including the ones a person is watching.
        """
        def work() -> None:
            try:
                status, payload = self.api.dispatch(
                    str(frame.get("method") or "GET"), str(frame.get("path") or ""),
                    dict(frame.get("query") or {}), dict(frame.get("body") or {}))
            except Exception as exc:            # noqa: BLE001 — one request, not the panel
                status, payload = 500, {"error": f"{type(exc).__name__}: {exc}"}
            self.answered += 1
            try:
                sock.sendall(wire.dumps({"id": frame.get("id"), "status": int(status),
                                         "payload": payload}))
            except OSError:
                pass

        threading.Thread(target=work, name="service-answer", daemon=True).start()
