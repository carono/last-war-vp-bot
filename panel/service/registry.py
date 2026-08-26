"""Which PANELS have dialled in, and how a request reaches one of them.

One entry per panel process — which in practice is one per interactive Windows session,
because that is where a panel comes up. Each holds the socket the panel dialled in on, the
few facts it announced about itself, and the answers it still owes.

WHY A REGISTER AND NOT A LOOKUP. A panel is not addressable from session 0: the service
cannot open a port inside somebody's session, and it must not try. So the panel dials out
and the register keeps the socket it arrived on — that socket IS the address, for as long
as it is open, and when it closes the panel is gone with no timeout to tune.

WHOSE PROFILE IS WHOSE. A machine may run several panels (a second client in its own
Windows session, `docs/research/multi-instance-rdp.md`) and each holds several profiles.
So a request that names a profile is routed to the panel that says it has one by that
name, and a request that names none goes to the panel that connected first — the same rule
the panel's own server uses for a request with no `?profile=`.
"""
from __future__ import annotations

import itertools
import threading
import time

from . import wire


class Panel:
    """One connected panel: its socket, what it said it is, and what it owes."""

    def __init__(self, sock, peer) -> None:
        self.sock = sock
        self.peer = peer
        self.at = time.time()
        #: What the panel announced in its `hello` — never trusted for anything but
        #: routing and for saying who is there.
        self.session = ""
        self.pid = 0
        self.profiles: list = []
        self.version = ""
        #: What the panel said about the CODE it imported: `pid`, `at`, `head`. A version
        #: is read off git when it is asked and therefore moves without a restart, so a
        #: row that carries only a version cannot answer «which of these is running the
        #: fix» — the question that took eight panels to notice (#1994).
        self.boot: dict = {}
        self._lock = threading.Lock()
        self._waiting: dict = {}          # request id -> [Event, answer]
        self._ids = itertools.count(1)
        self.closed = False

    # -- what it is ---------------------------------------------------------
    def hello(self, said: dict) -> None:
        self.session = str(said.get("session") or "")
        self.pid = int(said.get("pid") or 0)
        self.version = str(said.get("version") or "")
        boot = said.get("boot")
        self.boot = dict(boot) if isinstance(boot, dict) else {}
        self.profiles = [str(p) for p in (said.get("profiles") or [])]

    def state(self) -> dict:
        """What `/api/panels` says about it — no secrets, nothing it did not announce."""
        return {"session": self.session, "pid": self.pid, "version": self.version,
                "head": str(self.boot.get("head") or ""),
                "boot_at": self.boot.get("at") or 0,
                "profiles": list(self.profiles), "peer": str(self.peer),
                "since": self.at, "waiting": len(self._waiting)}

    # -- the conversation ---------------------------------------------------
    def ask(self, method: str, path: str, query: dict, body: dict,
            timeout: float = wire.ANSWER_TIMEOUT_SEC) -> tuple:
        """Hand one request over and wait for its answer. ``(status, payload)``.

        A panel that does not answer inside ``timeout`` is not killed and not marked
        dead: it may be walking a map with the game claim held. What is returned is a
        504 saying so, and the browser is free to ask again — the alternative is a page
        that hangs with nothing on it.
        """
        if self.closed:
            return 503, {"error": "panel_gone"}
        ident = next(self._ids)
        done = threading.Event()
        with self._lock:
            self._waiting[ident] = [done, None]
        frame = wire.dumps({"id": ident, "method": method, "path": path,
                            "query": dict(query or {}), "body": dict(body or {})})
        try:
            self.sock.sendall(frame)
        except OSError:
            self.drop()
            with self._lock:
                self._waiting.pop(ident, None)
            return 503, {"error": "panel_gone"}
        if not done.wait(timeout):
            with self._lock:
                self._waiting.pop(ident, None)
            return 504, {"error": "panel_slow", "path": path}
        with self._lock:
            answer = (self._waiting.pop(ident, [None, None]) or [None, None])[1]
        if not answer:
            return 503, {"error": "panel_gone"}
        return int(answer.get("status") or 500), answer.get("payload")

    def answered(self, frame: dict) -> None:
        """A panel's answer arrived — wake whoever is waiting for it."""
        try:
            ident = int(frame.get("id") or 0)
        except (TypeError, ValueError):
            return
        with self._lock:
            slot = self._waiting.get(ident)
            if slot is None:
                return                     # timed out already, or never asked
            slot[1] = frame
        slot[0].set()

    def ping(self) -> bool:
        try:
            self.sock.sendall(wire.dumps({"ping": 1}))
            return True
        except OSError:
            self.drop()
            return False

    def drop(self) -> None:
        """This panel is gone: wake everything waiting on it rather than hanging."""
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass
        with self._lock:
            waiting = list(self._waiting.values())
        for slot in waiting:
            slot[0].set()


class Registry:
    """Every panel that has dialled in, oldest first."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._panels: list = []

    def add(self, panel: Panel) -> None:
        with self._lock:
            self._panels.append(panel)

    def remove(self, panel: Panel) -> None:
        panel.drop()
        with self._lock:
            if panel in self._panels:
                self._panels.remove(panel)

    def all(self) -> list:
        with self._lock:
            return list(self._panels)

    def __len__(self) -> int:
        with self._lock:
            return len(self._panels)

    def for_profile(self, name: str = "") -> "Panel | None":
        """The panel to ask about ``name``, or the first one when it names nobody."""
        panels = [p for p in self.all() if not p.closed]
        if not panels:
            return None
        wanted = str(name or "").strip()
        if wanted:
            for panel in panels:
                if wanted in panel.profiles:
                    return panel
        return panels[0]

    def by_pid(self, pid: int) -> "Panel | None":
        """The panel running as ``pid``, or ``None`` — the only way to address ONE of them.

        Routing is by PROFILE everywhere else, which is right for every request that is
        about an account and useless for the two that are about a PROCESS: put this one
        down, restart this one. With one panel per profile those are the same thing; with
        two panels answering for one name — a state that should not happen and did (#1994)
        — the profile route reaches whichever dialled in first, for ever.
        """
        for panel in self.all():
            if not panel.closed and int(getattr(panel, "pid", 0) or 0) == int(pid):
                return panel
        return None

    def profiles(self) -> list:
        """Every profile every connected panel has open, in the order they dialled in."""
        seen, out = set(), []
        for panel in self.all():
            for name in panel.profiles:
                if name not in seen:
                    seen.add(name)
                    out.append(name)
        return out
