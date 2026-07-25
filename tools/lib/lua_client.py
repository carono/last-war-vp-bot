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
"""
from __future__ import annotations
import json
import socket
import sys

sys.path.insert(0, "tools/lib")

HOST = "127.0.0.1"
PORT = 47654


class DaemonClient:
    """Talks to lua_daemon over a per-call TCP connection. Same interface as LuaEval."""

    def __init__(self, host: str = HOST, port: int = PORT, timeout: float = 90.0):
        self.host, self.port, self.timeout = host, port, timeout

    def _rpc(self, req: dict) -> dict:
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
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

    def run(self, chunk: str, marker=None, settle: float = 1.2):
        r = self._rpc({"op": "run", "chunk": chunk, "marker": marker, "settle": settle})
        if not r.get("ok"):
            raise RuntimeError(r.get("error", "daemon error"))
        return r.get("lines", [])

    def ping(self) -> bool:
        try:
            return bool(self._rpc({"op": "ping"}).get("ok"))
        except OSError:
            return False

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


def get_evaluator(prefer_daemon: bool = True):
    """Return a `.run(chunk, marker, settle)` evaluator.

    Daemon-backed when reachable, otherwise a fresh local `LuaEval` (imported lazily so
    this module stays dependency-light). Both expose `.run()` and `.close()`.
    """
    if prefer_daemon and is_running():
        return DaemonClient()
    import lua_eval
    return lua_eval.LuaEval()
