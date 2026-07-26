r"""Persistent warm-LuaEval daemon — keeps the hijack/il2cpp resolution hot.

`LuaEval.__init__` resolves the xLua facade through a thread hijack (~seconds); running
every panel click as a new process pays that each time. This daemon builds ONE `LuaEval`
and serves `run` requests over a local TCP socket, so a client executes a Lua chunk in the
time of a single SafeDoString invoke.

Protocol — newline-delimited JSON on 127.0.0.1:47654 (see tools/lua_client.py):
    {"op":"run","chunk":"<lua>","marker":"X","settle":1.2}  -> {"ok":true,"lines":[...]}
    {"op":"ping"}     -> {"ok":true,"warm":<bool>}
    {"op":"reload"}   -> rebuild the LuaEval (after a game restart) -> {"ok":true}
    {"op":"shutdown"} -> {"ok":true} then exit

Calls are serialized by a lock (the game hijack is not reentrant). A failing invoke — e.g.
the game restarted and the cached per-pid addresses are stale — triggers one automatic
rebuild-and-retry. Run under the Windows Python:

    C:\Python312\python.exe tools\lua_daemon.py
"""
from __future__ import annotations
import json
import os
import socket
import sys
import threading

# Absolute, not "tools/lib": resolve regardless of the launcher's cwd.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import lua_client  # HOST/PORT only — lightweight
from lua_eval import LuaEval


class Daemon:
    def __init__(self):
        self._lock = threading.Lock()
        self._ev = None

    def _ensure(self) -> LuaEval:
        if self._ev is None:
            self._ev = LuaEval()
        return self._ev

    def _drop(self):
        if self._ev is not None:
            try:
                self._ev.close()
            except BaseException:
                pass
            self._ev = None

    def reload(self):
        with self._lock:
            self._drop()
            self._ensure()

    def is_warm(self) -> bool:
        return self._ev is not None

    def run(self, chunk: str, marker, settle: float):
        with self._lock:
            for attempt in (1, 2):
                try:
                    return self._ensure().run(chunk, marker=marker, settle=settle)
                except BaseException:
                    # Stale handle (game restarted?) or transient hijack failure —
                    # drop the warm state and rebuild once before giving up.
                    self._drop()
                    if attempt == 2:
                        raise

    def close(self):
        with self._lock:
            self._drop()


def _handle(conn: socket.socket, daemon: Daemon) -> None:
    f = conn.makefile("rwb")
    try:
        for raw in f:
            try:
                req = json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                f.write(b'{"ok":false,"error":"bad json"}\n'); f.flush(); continue
            op = req.get("op", "run")
            try:
                if op == "ping":
                    resp = {"ok": True, "warm": daemon.is_warm()}
                elif op == "run":
                    lines = daemon.run(req.get("chunk", ""), req.get("marker"),
                                       float(req.get("settle", 1.2)))
                    resp = {"ok": True, "lines": lines}
                elif op == "reload":
                    daemon.reload(); resp = {"ok": True, "warm": daemon.is_warm()}
                elif op == "shutdown":
                    f.write(b'{"ok":true}\n'); f.flush(); daemon.close(); os._exit(0)
                else:
                    resp = {"ok": False, "error": f"unknown op {op!r}"}
            except BaseException as exc:
                resp = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            f.write((json.dumps(resp) + "\n").encode("utf-8")); f.flush()
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main() -> int:
    daemon = Daemon()
    try:
        daemon._ensure()
        print("[daemon] warm — LuaEval resolved", flush=True)
    except BaseException as exc:
        print(f"[daemon] not warm yet (game offline?): {exc}", flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((lua_client.HOST, lua_client.PORT))
    except OSError as exc:
        print(f"[daemon] cannot bind {lua_client.HOST}:{lua_client.PORT}: {exc} "
              f"(already running?)", file=sys.stderr)
        return 1
    srv.listen(8)
    print(f"[daemon] listening {lua_client.HOST}:{lua_client.PORT}", flush=True)
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=_handle, args=(conn, daemon), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
