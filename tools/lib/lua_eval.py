r"""Evaluate a Lua chunk in the live game and read the result back from Player.log.

Runs arbitrary Lua via the static facade GameEntry.get_Lua() -> XLuaManager
.SafeDoString(string) (docs/research/xlua-state.md §12). SafeDoString has full CS.*
bindings but returns nothing and swallows Lua errors, so a chunk reports results by
logging: `CS.UnityEngine.Debug.LogError('<MARKER> ...')`. This tool captures the
Player.log lines written during the call and prints the ones matching the marker.

    C:\Python312\python.exe tools\lua_eval.py "CS.UnityEngine.Debug.LogError('HI '..(1+1))"
    C:\Python312\python.exe tools\lua_eval.py --marker CAM --file chunk.lua

Importable: `from lua_eval import run_lua` -> run_lua(chunk, marker=None) -> [log lines].
"""
from __future__ import annotations
import os
import sys
import time

sys.path.insert(0, "tools/lib")
import xlua_route as XR
import il2cpp_probe as P


def player_log_path():
    """%LOCALAPPDATA% is ...\\AppData\\Local; Player.log lives under ...\\AppData\\LocalLow."""
    local = os.environ.get("LOCALAPPDATA", "")
    low = os.path.join(os.path.dirname(local), "LocalLow")
    return os.path.join(low, "FunFly", "Last War-Survival Game", "Player.log")


class LuaEval:
    """Reusable SafeDoString driver — resolve once, run many chunks."""

    def __init__(self):
        self.x = XR.X()
        self.x.find_luaenv_class()  # sets gameentry_cls / xluamgr_cls
        m, _, _ = self.x.gmfn(self.x.gameentry_cls, "get_Lua", 0)
        self.mgr, exc = self.x.invoke(m, 0, [], "GameEntry.get_Lua")
        if not self.mgr or exc:
            raise SystemExit(f"GameEntry.get_Lua failed mgr=0x{self.mgr:x} exc=0x{exc:x}")
        self.sd, _, _ = self.x.gmfn(self.x.xluamgr_cls, "SafeDoString", 1)
        if not self.sd:
            raise SystemExit("XLuaManager.SafeDoString not resolved")
        self.log = player_log_path()

    def run(self, chunk, marker=None, settle=1.2):
        since = os.path.getsize(self.log) if os.path.exists(self.log) else 0
        s = self.x.il2_string_new(chunk)
        self.x.invoke(self.sd, self.mgr, [("ref", s)], "SafeDoString")
        time.sleep(settle)
        out = []
        try:
            with open(self.log, "rb") as f:
                f.seek(since)
                data = f.read().decode("utf-8", "replace")
            for ln in data.splitlines():
                if marker is None or marker in ln:
                    out.append(ln.rstrip("\r"))
        except OSError:
            pass
        return out

    def close(self):
        P.CloseHandle(self.x.h)


def run_lua(chunk, marker=None, settle=1.2):
    """One-shot convenience: build a LuaEval, run one chunk, tear down."""
    ev = LuaEval()
    try:
        return ev.run(chunk, marker=marker, settle=settle)
    finally:
        ev.close()


def main():
    argv = sys.argv[1:]
    marker = None
    if "--marker" in argv:
        i = argv.index("--marker")
        marker = argv[i + 1]
        del argv[i:i + 2]
    if "--file" in argv:
        i = argv.index("--file")
        chunk = open(argv[i + 1], encoding="utf-8").read()
    elif argv:
        chunk = argv[0]
    else:
        chunk = "CS.UnityEngine.Debug.LogError('LUA_EVAL alive '..tostring(1+1))"
        marker = marker or "LUA_EVAL"
    for ln in run_lua(chunk, marker=marker):
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
