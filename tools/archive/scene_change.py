r"""City<->World via the game's xLua VM (tasks #1017/#1024 — SUPERSEDES the C# route).

The C# `SceneManager` primitives do NOT drive a real City->World transition:
`ChangeScene(SceneID.World)` and `CreateWorld()` flip the engine scene *enum* but tear
the view to black without rendering the target scene (docs/research/xlua-state.md §11).
The working path is a Lua call through the static facade:

    GameEntry.get_Lua()  (static)                -> XLuaManager
    XLuaManager.SafeDoString("SceneUtils.ChangeToWorld()")   -> renders World
    # reverse: SafeDoString("SceneUtils.ChangeToCity()")

Everything (GameEntry/XLuaManager classes + MethodInfos) is resolved at RUNTIME
(addresses are per-pid), validated by reading the class name back — NEVER the dump JSON
`addr`, which crashed the game in §8.3. State is read FROM LUA (SceneUtils.GetIsInWorld/
GetIsInCity), emitted to the Unity Player.log: SafeDoString swallows Lua errors and
returns nothing, so state is confirmed via the log, not a return value.

    C:\Python312\python.exe tools\scene_change.py            # read-only: report state
    C:\Python312\python.exe tools\scene_change.py --fire     # City -> World
    C:\Python312\python.exe tools\scene_change.py --to-city  # World -> City
    C:\Python312\python.exe tools\scene_change.py --fire --shot   # + screenshot before/after

Launch (game must be running first; run the exe from its own dir via WSL interop):
    "$LOCALAPPDATA/FunFly/Last War-Survival Game/Game/LastWar.exe"
"""
from __future__ import annotations
import os
import sys
import time

sys.path.insert(0, "tools/lib")
import xlua_route as XR
import il2cpp_probe as P
from lua_goto_world import shot


def player_log_path():
    """%LOCALAPPDATA% is ...\\AppData\\Local; Player.log lives under ...\\AppData\\LocalLow."""
    local = os.environ.get("LOCALAPPDATA", "")
    low = os.path.join(os.path.dirname(local), "LocalLow")
    return os.path.join(low, "FunFly", "Last War-Survival Game", "Player.log")


def log_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def read_state_from_log(path, since):
    """Parse (inWorld, inCity) from the newest SCENE_STATE marker written after byte
    offset `since`. Returns (None, None) if no marker / log unreadable."""
    try:
        with open(path, "rb") as f:
            f.seek(since)
            data = f.read()
    except OSError:
        return None, None
    inw = inc = None
    for line in data.decode("utf-8", "replace").splitlines():
        if "SCENE_STATE" not in line:
            continue
        for tok in line.split():
            if tok.startswith("inWorld="):
                inw = tok.split("=", 1)[1] == "true"
            elif tok.startswith("inCity="):
                inc = tok.split("=", 1)[1].rstrip("'\"") == "true"
    return inw, inc


def main():
    fire = "--fire" in sys.argv
    to_city = "--to-city" in sys.argv
    do_shot = "--shot" in sys.argv
    log = player_log_path()

    x = XR.X()
    # find_luaenv_class() resolves the Assembly-CSharp image and sets x.gameentry_cls /
    # x.xluamgr_cls (validated at runtime); we only need those two for SafeDoString.
    x.find_luaenv_class()

    m, _, _ = x.gmfn(x.gameentry_cls, "get_Lua", 0)
    if not m:
        raise SystemExit("GameEntry.get_Lua not resolved")
    mgr, exc = x.invoke(m, 0, [], "GameEntry.get_Lua")
    if not mgr or exc:
        raise SystemExit(f"GameEntry.get_Lua failed mgr=0x{mgr:x} exc=0x{exc:x}")
    sd, _, _ = x.gmfn(x.xluamgr_cls, "SafeDoString", 1)
    if not sd:
        raise SystemExit("XLuaManager.SafeDoString not resolved")
    print(f"XLuaManager=0x{mgr:x} SafeDoString MI=0x{sd:x}")

    def run(lua):
        s = x.il2_string_new(lua)
        x.invoke(sd, mgr, [("ref", s)], "SafeDoString")

    def state(tag):
        since = log_size(log)
        run("CS.UnityEngine.Debug.LogError('SCENE_STATE " + tag + " inWorld='.."
            "tostring(SceneUtils.GetIsInWorld())..' inCity='.."
            "tostring(SceneUtils.GetIsInCity()))")
        time.sleep(0.6)
        inw, inc = read_state_from_log(log, since)
        print(f"  [{tag}] inWorld={inw} inCity={inc}")
        return inw, inc

    inw, _ = state("before")
    if do_shot:
        shot(x.pid, "scene_before.png")

    if not fire and not to_city:
        print("(read-only; pass --fire for City->World or --to-city for World->City)")
        P.CloseHandle(x.h)
        return 0

    target_world = not to_city
    call = "SceneUtils.ChangeToCity()" if to_city else "SceneUtils.ChangeToWorld()"
    if inw is target_world:
        print(f"already {'in World' if target_world else 'in City'} — not firing")
        P.CloseHandle(x.h)
        return 0

    print(f"=== SafeDoString({call!r}) ===")
    run(call)
    time.sleep(6.0)  # scene build + camera settle
    inw2, _ = state("after")
    if do_shot:
        shot(x.pid, "scene_after.png")

    P.CloseHandle(x.h)
    ok = inw2 is target_world
    print("RESULT:", "OK — transition confirmed" if ok else "state not confirmed (check Player.log)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
