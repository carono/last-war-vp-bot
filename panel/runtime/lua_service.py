r"""The panel's own hold on the game — there is no daemon process any more (#1911).

**The panel IS the link.** A `LuaEval` — the thread hijack and the il2cpp resolution that
let a chunk run inside the client — is built HERE, in the panel's own process, on a
worker thread, and it stays warm for as long as the panel is open. Nothing starts it,
nothing supervises it, nothing elects a watcher for it, and there is no port to be «up»
without a client behind it. What used to be a whole lifecycle — `ensure` / `restart` /
`stop` / `_kill` / «warm, stale, none» — is now the ordinary question of whether a chunk
lands, asked of an object this process owns.

THE DOOR IS STILL A SOCKET, and that is not a leftover. Two dozen tools under `tools/`
are spawned as CHILD processes by the panel and drive the game through
`tools/lib/lua_client.py`; a child cannot share this process's evaluator, and two
hijacks of one client racing each other is exactly what the lease exists to prevent. So
the service listens on the profile's port and speaks the protocol `lua_daemon` always
spoke — the same ops, the same lease, the same pulse. From a child's side nothing has
changed. From the panel's side the socket is not used at all: panel code holds a
:class:`LocalClient`, which is the same surface with the round trip taken out.

ONE ATTACH PER PROCESS. A Windows session has one Last War client, so the panel has one
VM to hold however many profiles are open on it; the listeners are per PORT and the
evaluator behind them is shared, which is also what keeps the run lock and the lease
meaning what they say. A profile whose client lives in ANOTHER Windows session cannot be
attached to from here at all — a hijack finds its client in the session it runs in — and
that one still speaks to a small process over there (`panel/runtime/link.py`), owned by
the link that started it and supervised by nobody.

WHAT DOES NOT HAPPEN HERE, ON PURPOSE:

* **nothing exits.** `lua_daemon`'s answer to three failed probes is to let go of the
  port and die, because a fresh daemon on a free port was a state the panel knew how to
  cure. This process is the panel: it drops the evaluator and builds a new one, and if
  that fails the light goes amber and says so.
* **`shutdown` is refused.** It is an op an old tool may still send; carrying it out
  would close the panel.
* **no failure is announced more than once.** The same standing failure, said on the
  edge and then left alone — the class of defect this codebase keeps relearning (#1910).
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time

import lua_client

#: How often the watch thread looks in: follow the client across a restart, and probe
#: the link if nothing has landed lately. Five seconds — the same interval the daemon
#: used, for the same reason: a client restart takes the better part of a minute, so
#: this is never the slow part.
WATCH_SEC = 5.0

#: How long a bind is retried before the service gives up on the port. A panel that has
#: just been restarted may find its own previous listener still letting go.
BIND_TRIES, BIND_WAIT = 20, 0.25


def _daemon_module():
    """`tools/lua_daemon.py`, imported lazily — it is the VM half, not the protocol.

    Lazy because it drags in the lease and the pulse, and because a test of the panel
    that never touches the game should not need either. `tools/` is on `sys.path`
    already (`panel/runtime/paths.py`); the fallback is for a bare harness.
    """
    try:
        import lua_daemon                              # noqa: PLC0415
    except ImportError:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.path.insert(0, os.path.join(here, "tools"))
        import lua_daemon                              # noqa: PLC0415
    return lua_daemon


class LocalClient:
    """`lua_client.DaemonClient`'s surface, served in-process by a :class:`LuaService`.

    Everything in the panel that drives the game already speaks this shape, so the whole
    change of «the panel is the daemon» reaches those callers as a different object with
    the same methods — and one that costs a function call instead of a socket.

    The token lives on the client, exactly as it does for the socket version: a panel
    holding four profiles holds four rights to drive four clients, and an environment
    variable could never get that right (#1206).
    """

    def __init__(self, service: "LuaService", token: str = "") -> None:
        self._service = service
        self.token = token or ""

    @property
    def port(self) -> int:
        return self._service.port

    # -- driving the game ----------------------------------------------------
    def run(self, chunk: str, marker=None, settle: float = 1.2, early: bool = False,
            sentinel: "str | None" = None):
        return self._service.run(chunk, marker=marker, settle=settle, early=early,
                                 sentinel=sentinel, token=self.token)

    # -- readings ------------------------------------------------------------
    def ping(self) -> bool:
        return True                     # this object cannot exist without the service

    def status(self) -> dict:
        return self._service.status()

    def target_pid(self) -> "int | None":
        return self._service.target_pid()

    # -- the lease -----------------------------------------------------------
    def acquire(self, owner: str, ttl: float = 120.0) -> "str | None":
        reply = self._service.lease.acquire(owner, ttl, self.token or None)
        self.token = (reply.get("token") or "") if reply.get("ok") else self.token
        return self.token if reply.get("ok") else None

    def renew(self) -> bool:
        return bool(self.token) and bool(self._service.lease.renew(self.token).get("ok"))

    def release(self) -> bool:
        if not self.token:
            return True
        try:
            return bool(self._service.lease.release(self.token).get("ok"))
        finally:
            self.token = ""

    def lease_state(self) -> dict:
        return self._service.lease.state() or {}

    # -- the two ops that no longer mean anything ----------------------------
    def reload(self) -> dict:
        self._service.reattach()
        return {"ok": True}

    def shutdown(self) -> dict:
        """Refused: this «daemon» is the panel, and closing it is a person's press."""
        return {"ok": False, "error": "the panel holds the link; it does not shut down"}

    def close(self) -> None:
        """No-op — the service outlives every client object made against it."""


class LuaService:
    """One warm `LuaEval` for this Windows session's client, and the door children use.

    Built lazily: nothing is attached until something asks the game a question or the
    watch thread's first probe comes due, so opening a panel on a machine with no client
    running costs nothing.
    """

    def __init__(self, host: str = "", log=None, debug=None) -> None:
        self._host = host or lua_client.HOST
        self._log, self._dbg = log, debug
        self._mod = _daemon_module()
        self._daemon = self._mod.Daemon()
        self._ports: dict = {}                    # port -> the listening socket
        self._lock = threading.Lock()
        self._watching = False
        #: The last thing an attach said, for the amber that has to name a cause.
        self._error = ""
        #: …and what has already been said about it, so a standing failure is one line.
        self._said = ""

    # -- the connection ------------------------------------------------------
    @property
    def port(self) -> int:
        """Any port this service answers on — the first one bound. For an endpoint key."""
        return next(iter(self._ports), 0)

    @property
    def lease(self):
        return self._daemon.lease

    @property
    def pulse(self):
        return self._daemon.pulse

    def listen(self, port: int) -> bool:
        """Bind ``port`` for the child tools, and start the watch. Idempotent.

        A port that cannot be bound is not fatal and never was: the panel drives the game
        in-process either way, and what is lost is the children's door. It is said once.
        """
        port = int(port)
        with self._lock:
            if port in self._ports:
                return True
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # SO_REUSEADDR on Windows lets a second bind STEAL a live port, which would
            # route one profile's calls into another account's game.
            srv.setsockopt(socket.SOL_SOCKET,
                           getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
            bound = False
            for _ in range(BIND_TRIES):
                try:
                    srv.bind((self._host, port))
                    bound = True
                    break
                except OSError:
                    time.sleep(BIND_WAIT)
            if not bound:
                srv.close()
                self._say_once(f"port {port} is held by something else",
                               "log.link.port_taken", port=port)
                return False
            srv.listen(8)
            self._ports[port] = srv
        threading.Thread(target=self._accept, args=(srv,), daemon=True).start()
        self._watch()
        self._note("listening on %s:%s for the child tools", self._host, port)
        return True

    def forget(self, port: int) -> None:
        """Let a port go — a profile was closed, or its port setting moved."""
        with self._lock:
            srv = self._ports.pop(int(port), None)
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass

    def stop(self) -> None:
        """Close every door and let the client go. The panel is shutting down."""
        for port in list(self._ports):
            self.forget(port)
        try:
            self._daemon.close()
        except BaseException:                         # noqa: BLE001 — leaving anyway
            pass

    # -- driving the game ----------------------------------------------------
    def run(self, chunk: str, marker=None, settle: float = 1.2, early: bool = False,
            sentinel: "str | None" = None, token: "str | None" = None):
        """One chunk, through the same lock and the same lease a child's `run` uses."""
        refused = self.lease.check_run(token)
        if refused:
            raise lua_client.LeaseLost(refused)
        try:
            lines = self._daemon.run(chunk, marker, float(settle), early=early,
                                     sentinel=sentinel)
        except self._mod.ClientUnreachable as exc:
            self._error = str(exc)
            raise lua_client.ClientGone(str(exc)) from exc
        except BaseException as exc:                  # noqa: BLE001 — the caller's chunk
            self._error = f"{type(exc).__name__}: {exc}"
            raise
        self._error = ""
        return lines

    def reattach(self) -> bool:
        """Let the client go and take hold of it again. ``True`` if it worked."""
        try:
            self._daemon.reload()
        except BaseException as exc:                  # noqa: BLE001 — a state, not a crash
            self._error = f"{type(exc).__name__}: {exc}"
            self._note_warn("could not attach: %s", exc)
            return False
        self._error = ""
        return True

    # -- readings ------------------------------------------------------------
    def status(self) -> dict:
        """What a `{"op":"ping"}` used to answer, from the object rather than the wire."""
        return {"ok": True, "warm": self._daemon.is_warm(),
                "pid": self._daemon.target_pid(), "self": os.getpid(),
                "panel": True, "lease": self.lease.state(), **self.pulse.state()}

    def target_pid(self) -> "int | None":
        return self._daemon.target_pid()

    def traffic_age(self) -> "float | None":
        """Seconds since a chunk last came back out of the game, or ``None``."""
        return self.pulse.age()

    def error(self) -> str:
        """Why nothing lands, in the words of whatever refused it. ``""`` while it does."""
        return self._error or str(self.pulse.state().get("probe_error") or "")

    # -- the watch -----------------------------------------------------------
    def _watch(self) -> None:
        if self._watching:
            return
        self._watching = True
        threading.Thread(target=self._watch_loop, daemon=True).start()

    def _watch_loop(self) -> None:
        """Follow the client, prove the link, and rebuild when it cannot be proved.

        The daemon's own watch, minus the one thing it did that a panel may not: leaving.
        Three failed probes there meant «let go of the port and die, the panel will start
        a fresh one»; here it means «drop the evaluator and attach again», which is the
        same cure with the process kept.
        """
        while True:
            time.sleep(WATCH_SEC)
            try:
                self._daemon.follow_client()
                self._daemon.heartbeat()
                if self.pulse.should_leave():
                    self._note_warn("%s probes in a row did not reach the client — "
                                    "attaching again", self.pulse.misses())
                    self.reattach()
            except BaseException as exc:              # noqa: BLE001 — never the last word
                self._note_warn("watch: %s", exc)

    # -- the door the child tools come through -------------------------------
    def _accept(self, srv: socket.socket) -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return                                # the port was let go
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        """`lua_daemon._handle`, with `shutdown` refused and nothing that can exit."""
        f = conn.makefile("rwb")
        try:
            for raw in f:
                try:
                    req = json.loads(raw.decode("utf-8", "replace"))
                except Exception:                     # noqa: BLE001
                    f.write(b'{"ok":false,"error":"bad json"}\n')
                    f.flush()
                    continue
                f.write((json.dumps(self._answer(req)) + "\n").encode("utf-8"))
                f.flush()
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _answer(self, req: dict) -> dict:
        op = req.get("op", "run")
        try:
            if op == "ping":
                return self.status()
            if op == "run":
                lines = self.run(req.get("chunk", ""), req.get("marker"),
                                 float(req.get("settle", 1.2)),
                                 early=bool(req.get("early")),
                                 sentinel=req.get("sentinel"), token=req.get("token"))
                return {"ok": True, "lines": lines}
            if op == "acquire":
                return self.lease.acquire(req.get("owner", "?"),
                                          req.get("ttl", self._mod.DEFAULT_LEASE_TTL),
                                          req.get("token"))
            if op == "renew":
                return self.lease.renew(req.get("token"))
            if op == "release":
                return self.lease.release(req.get("token"))
            if op == "reload":
                return {"ok": self.reattach(), "warm": self._daemon.is_warm()}
            if op == "shutdown":
                return {"ok": False,
                        "error": "the panel holds the link; it does not shut down"}
            return {"ok": False, "error": f"unknown op {op!r}"}
        except lua_client.LeaseLost as exc:
            return {"ok": False, "error": str(exc), "lease_lost": True}
        except lua_client.ClientGone as exc:
            return {"ok": False, "error": str(exc), "client_gone": True}
        except BaseException as exc:                  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # -- diagnostics ---------------------------------------------------------
    def _say_once(self, fingerprint: str, key: str, **fmt) -> None:
        if self._said == fingerprint or self._log is None:
            return
        self._said = fingerprint
        self._log.say("link", key, **fmt)

    def _note(self, msg, *args) -> None:
        if self._dbg is not None:
            self._dbg.info(msg, *args)

    def _note_warn(self, msg, *args) -> None:
        if self._dbg is not None:
            self._dbg.warning(msg, *args)


#: The one attach this process has. A Windows session holds one client, so every profile
#: open on it shares this — and with it the run lock and the lease, which is precisely
#: what keeps two profiles pointed at one game taking turns.
_LOCAL: "LuaService | None" = None
_LOCAL_LOCK = threading.Lock()


def local(log=None, debug=None) -> LuaService:
    """This process's service, made on first use."""
    global _LOCAL
    with _LOCAL_LOCK:
        if _LOCAL is None:
            _LOCAL = LuaService(log=log, debug=debug)
        return _LOCAL


def current() -> "LuaService | None":
    """The process's service IF one has been made — never makes one.

    The reading half. A light, a gate or a claim asking «how long ago did a chunk land»
    must not be the thing that attaches to a client or binds a port: a reading with a
    side effect is how a test binds 47654 and how a drawer pays for an attach (#1911).
    """
    return _LOCAL


def forget_local() -> None:
    """Drop the process's service — for a test, and for a panel on its way out."""
    global _LOCAL
    with _LOCAL_LOCK:
        service, _LOCAL = _LOCAL, None
    if service is not None:
        service.stop()
