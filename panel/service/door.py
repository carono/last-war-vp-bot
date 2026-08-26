"""The listener panels dial in on, and the loop that reads each one.

Loopback only, and that is not a default anybody may change: a panel dials this port from
an interactive session on the SAME machine, and a port on `0.0.0.0` would be a way into
every panel on it for anybody who can reach the box. What is exposed to the world is the
HTTP half, behind its token; this is the inside of the house.

WHY NOT AUTHENTICATE THE PANEL. Because on this side of the loopback the question does not
have an answer worth having: anything that can open 127.0.0.1 can also read the token file
the panel would prove itself with. What a panel says about itself — its session, its
profiles — is used for ROUTING and for saying who is there, never as permission.
"""
from __future__ import annotations

import socket
import threading

from . import wire
from .registry import Panel, Registry

#: Where the panels dial in. Not the HTTP port: that one is the world's and this one is
#: the machine's, and giving them one number would mean a browser could open a panel's
#: connector by accident.
DEFAULT_DOOR_PORT = 9762
DOOR_HOST = "127.0.0.1"


def _is_loopback(host: str) -> bool:
    """Is ``host`` this machine talking to itself? Anything else is refused above."""
    import ipaddress

    said = str(host or "").strip()
    if said in ("localhost", ""):
        return said == "localhost"
    try:
        return ipaddress.ip_address(said).is_loopback
    except ValueError:
        return False


class Door:
    """The panels' way in. One thread accepting, one per connected panel."""

    def __init__(self, registry: Registry, *, host: str = DOOR_HOST,
                 port: int = DEFAULT_DOOR_PORT, log=None) -> None:
        self.registry = registry
        self.host = host or DOOR_HOST
        self.port = int(port)
        self._log = log or (lambda line: None)
        self._sock = None
        self._thread = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._sock is not None

    def start(self) -> None:
        """Bind and accept. Raises `OSError` when the port is taken — the caller says so."""
        if self.running:
            return
        # LOOPBACK OR NOTHING, and it is refused rather than corrected: a door that
        # listened on an interface would be a way into every panel on this machine for
        # anybody who can reach the box, and a misconfiguration that quietly did the safe
        # thing instead would leave whoever wrote it believing something else.
        if not _is_loopback(self.host):
            raise ValueError(f"the panels' door may only listen on the loopback, "
                             f"not on {self.host!r}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(16)
        self._sock = sock
        self.port = sock.getsockname()[1]        # `0` in a test becomes the real one
        self._thread = threading.Thread(target=self._accept, name="service-door",
                                        daemon=True)
        self._thread.start()
        self._log(f"door: panels may dial {self.host}:{self.port}")

    def stop(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        for panel in self.registry.all():
            self.registry.remove(panel)

    # -- the loops ----------------------------------------------------------
    def _accept(self) -> None:
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                return
            try:
                conn, peer = sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn, peer),
                             name="service-panel", daemon=True).start()

    def _serve(self, conn, peer) -> None:
        """One panel, for as long as its socket is open."""
        panel = Panel(conn, peer)
        self.registry.add(panel)
        try:
            for frame in wire.reader(conn):
                if "hello" in frame:
                    panel.hello(frame.get("hello") or {})
                    self._log("panel connected: session "
                              f"{panel.session or '?'} pid {panel.pid} "
                              f"profiles {', '.join(panel.profiles) or '—'}")
                    try:
                        conn.sendall(wire.dumps({"welcome": 1}))
                    except OSError:
                        break
                elif "id" in frame:
                    panel.answered(frame)
                elif "ping" in frame:
                    try:
                        conn.sendall(wire.dumps({"pong": 1}))
                    except OSError:
                        break
        finally:
            self.registry.remove(panel)
            self._log(f"panel gone: session {panel.session or '?'} pid {panel.pid}")
