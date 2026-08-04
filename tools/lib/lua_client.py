r"""Lightweight client for the warm Lua daemon (tools/lua_daemon.py).

The expensive part of driving the game is `LuaEval.__init__` — the il2cpp class
enumeration + method resolution done through a thread hijack (~seconds). Running every
action as a fresh process pays that cost each time. `lua_daemon.py` keeps ONE warm
`LuaEval` alive and executes chunks over a local socket; this module is the client.

`get_evaluator()` returns an object with the same `.run(chunk, marker, settle)` /
`.close()` interface as `LuaEval`, backed by the daemon when it is up and by a fresh
local `LuaEval` otherwise — so standalone scripts keep working with or without the daemon
(and transparently speed up when it is running).

This module imports NOTHING heavy (no il2cpp deps) — safe to import anywhere. The local
`LuaEval` fallback is imported lazily, only when actually needed.

One daemon per client. A second Last War client lives in its own Windows session with
its own daemon on its own port (task #1106, `tools/rdp_instance.py`), so the port is not
a constant: it comes from ``LW_DAEMON_PORT`` when set, which is all an existing script
needs to be pointed at the other instance —

    LW_DAEMON_PORT=47655 C:\Python312\python.exe tools\dispatch_tasks.py

The local `LuaEval` fallback only ever drives the client in *this* session, so it is
skipped when the port is not the default one: an unreachable foreign daemon must be an
error, not a silent hijack of the wrong client.
"""
from __future__ import annotations
import json
import os
import socket
import sys

sys.path.insert(0, "tools/lib")

HOST = os.environ.get("LW_DAEMON_HOST") or "127.0.0.1"
DEFAULT_PORT = 47654
PORT = int(os.environ.get("LW_DAEMON_PORT") or DEFAULT_PORT)

# The game lease this process runs under lives in the environment, so that ONE fact —
# "this process is allowed to drive the game" — reaches everything without being threaded
# through every call: the evaluators built later in this process (a recipe asks
# `get_evaluator()` for its own), and every child spawned from it (the panel copies the
# environment). Read per client rather than snapshotted at import, because a panel claims
# the lease long after this module was imported.
LEASE_ENV_VAR = "LW_GAME_LEASE"

#: How long a CONNECT to the daemon may take, as opposed to how long an answer may take.
#: The daemon is on this machine: a connect that has not succeeded in half a second is
#: not going to. See `DaemonClient.__init__` for what the shared number used to cost.
CONNECT_TIMEOUT = 0.5


def current_lease() -> str:
    """The token this process holds or inherited, or ``""``."""
    return os.environ.get(LEASE_ENV_VAR) or ""


class LeaseLost(RuntimeError):
    """A `run` was refused because the caller's lease is no longer the live one.

    Distinct from a plain daemon error: nothing is wrong with the chunk or the game —
    this process simply stopped being the one allowed to drive it, and the right
    response is to stop, not to retry.
    """


class DaemonClient:
    """Talks to lua_daemon over a per-call TCP connection. Same interface as LuaEval."""

    def __init__(self, host: str = HOST, port: int = PORT, timeout: float = 90.0,
                 token: "str | None" = None, connect_timeout: float = CONNECT_TIMEOUT):
        self.host, self.port, self.timeout = host, port, timeout
        # CONNECTING and WAITING FOR AN ANSWER are two different waits and only one of
        # them is long. A Lua chunk may legitimately take a minute, which is what
        # `timeout` is for; the CONNECT is to a socket on this machine and either
        # succeeds in a fraction of a millisecond or is never going to. Sharing the one
        # number meant a call made while the daemon was down sat for the operating
        # system's own connect timeout — measured at 2.0 s — and `GameLink.claim` is
        # called from the Tk thread by every button, so that was two seconds of frozen
        # window per press with no daemon up (#1226).
        self.connect_timeout = float(connect_timeout)
        # None means "whatever this process is running under"; "" means explicitly
        # unleased (a read that must never queue behind, or be refused by, a lease).
        self.token = current_lease() if token is None else token

    def _rpc(self, req: dict) -> dict:
        s = socket.create_connection((self.host, self.port),
                                     timeout=self.connect_timeout)
        s.settimeout(self.timeout)       # …and the ANSWER may take as long as it takes
        try:
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            return json.loads(buf.decode("utf-8", "replace").splitlines()[0])
        finally:
            s.close()

    def run(self, chunk: str, marker=None, settle: float = 1.2, early: bool = False):
        """Run a chunk. ``early`` makes `settle` a deadline — see `lua_eval.collect`.

        Sent only when asked for, so a daemon started before this existed simply
        ignores an unknown key and waits the way it always did.
        """
        req = {"op": "run", "chunk": chunk, "marker": marker, "settle": settle}
        if early:
            req["early"] = True
        if self.token:
            req["token"] = self.token      # …which also renews the lease
        r = self._rpc(req)
        if not r.get("ok"):
            if r.get("lease_lost"):
                raise LeaseLost(r.get("error", "lease lost"))
            raise RuntimeError(r.get("error", "daemon error"))
        return r.get("lines", [])

    def ping(self) -> bool:
        try:
            return bool(self._rpc({"op": "ping"}).get("ok"))
        except OSError:
            return False

    def target_pid(self) -> "int | None":
        """Which client process this daemon is attached to, or ``None``.

        ``None`` covers both "no daemon there" and "there is one but it is not warm"
        — from the caller's side those are the same answer: nothing here names a live
        client. The one caller that needs it is a restart (tools/lib/game_client.py):
        with two clients on the machine, the process THIS profile's daemon drives is
        the only honest reading of "the game", and a process name is not.
        """
        try:
            pid = self._rpc({"op": "ping"}).get("pid")
        except OSError:
            return None
        try:
            return int(pid) or None
        except (TypeError, ValueError):
            return None

    # -- the game lease: one action at a time, across processes --------------
    def acquire(self, owner: str, ttl: float = 120.0) -> "str | None":
        """Claim the right to drive the game. The token, or ``None`` if someone else holds it.

        Re-claiming with a token this client already carries returns that same token, so
        a nested claim inside one owner is not a deadlock.
        """
        req = {"op": "acquire", "owner": owner, "ttl": ttl}
        if self.token:
            req["token"] = self.token
        r = self._rpc(req)
        if not r.get("ok"):
            return None
        self.token = r.get("token") or ""
        return self.token

    def renew(self) -> bool:
        if not self.token:
            return False
        return bool(self._rpc({"op": "renew", "token": self.token}).get("ok"))

    def release(self) -> bool:
        if not self.token:
            return True
        try:
            return bool(self._rpc({"op": "release", "token": self.token}).get("ok"))
        finally:
            self.token = ""

    def lease_state(self) -> dict:
        try:
            return self._rpc({"op": "ping"}).get("lease") or {}
        except OSError:
            return {}

    def reload(self):
        return self._rpc({"op": "reload"})

    def shutdown(self):
        try:
            return self._rpc({"op": "shutdown"})
        except OSError:
            return {"ok": True}

    def close(self):
        """No-op: the daemon persists across calls (that is the whole point)."""


def is_running(host: str = HOST, port: int = PORT, timeout: float = 1.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def get_evaluator(prefer_daemon: bool = True, host: str = HOST, port: int = PORT,
                  token: "str | None" = None):
    """Return a `.run(chunk, marker, settle)` evaluator.

    Daemon-backed when reachable, otherwise a fresh local `LuaEval` (imported lazily so
    this module stays dependency-light). Both expose `.run()` and `.close()`.

    The fallback applies to the default port only. A non-default port names another
    session's client, which a local `LuaEval` cannot reach — there, an unreachable
    daemon raises instead of quietly driving the client of this session.

    ``token`` names the lease this evaluator runs under, for a caller that holds one
    without the environment saying so. ``None`` keeps the old meaning — whatever
    `current_lease()` reads — and is right for every script started from a shell. It is
    the PANEL that needs to be explicit: one process there may hold two profiles' leases
    at once, and an environment variable can only ever hold one of them (#1206).
    """
    if prefer_daemon and is_running(host, port):
        return DaemonClient(host, port, token=token)
    if port != DEFAULT_PORT:
        raise ConnectionRefusedError(
            f"no Lua daemon on {host}:{port} — that is another session's client, and it "
            f"cannot be driven locally. Bring it up with tools/rdp_instance.py --status")
    import lua_eval
    return lua_eval.LuaEval()
