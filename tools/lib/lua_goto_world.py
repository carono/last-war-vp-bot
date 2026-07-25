r"""City<->World via the loaded xLua VM, through LuaEnv.DoString (task #1024).

Replaces the ClickWorld / toggle-button approach with a direct Lua scene switch.
Reaches the live XLua.LuaEnv instance via tools/xlua_route.py and drives the scene
with LuaEnv.DoString("SceneUtils.ChangeToWorld()") -- the proven world-open Lua from
task #1017, but delivered through LuaEnv.DoString instead of XLuaManager.SafeDoString.

Difference from the SafeDoString route (see docs/research/xlua-state.md sec 12):
LuaEnv.DoString does NOT swallow Lua errors, so a bad chunk surfaces in the il2cpp
exc slot. Scene state is confirmed from Lua via SceneUtils.GetIsInWorld/GetIsInCity
(logged to the Unity Player.log as LUAENV_1024 markers) and, optionally, a screenshot.

    C:\Python312\python.exe tools\lua_goto_world.py            # City -> World
    C:\Python312\python.exe tools\lua_goto_world.py --to-city  # World -> City
    C:\Python312\python.exe tools\lua_goto_world.py --shot     # also screenshot after

Player.log: %LOCALAPPDATA%Low\FunFly\Last War-Survival Game\Player.log
"""
from __future__ import annotations
import sys
import time

sys.path.insert(0, "tools/lib")
import xlua_route as XR
import il2cpp_probe as P

RES = r"P:\projects abandoned\carono\last-war-vp-bot\results"


def shot(pid, name):
    """Focus the game window (Alt-key trick) and grab it with mss. The 3D scene
    photographs black on this Unity client, but the 2D HUD / toggle button is
    visible -- enough to read the «Мир»/«База» toggle (see docs)."""
    import mss, mss.tools, win32gui, win32process, win32con, win32api
    hs = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            _, p = win32process.GetWindowThreadProcessId(h)
            if p == pid:
                r = win32gui.GetWindowRect(h)
                if r[2] - r[0] > 200 and r[3] - r[1] > 200:
                    hs.append((h, r))
        return True

    win32gui.EnumWindows(cb, None)
    if not hs:
        print("  no window to screenshot")
        return
    h, _ = hs[0]
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(h)
    except Exception:
        pass
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(1.5)
    r = win32gui.GetWindowRect(h)
    with mss.MSS() as sct:
        img = sct.grab({"left": r[0], "top": r[1], "width": r[2] - r[0], "height": r[3] - r[1]})
        mss.tools.to_png(img.rgb, img.size, output=RES + "\\" + name)
    print("  saved", name)


def main():
    to_city = "--to-city" in sys.argv
    do_shot = "--shot" in sys.argv
    call = "SceneUtils.ChangeToCity()" if to_city else "SceneUtils.ChangeToWorld()"
    tag = "TOCITY" if to_city else "TOWORLD"

    x = XR.X()
    x.setup_luaenv()

    def log_state(when):
        chunk = (f"CS.UnityEngine.Debug.LogError('LUAENV_1024 {tag} {when} inWorld='.."
                 "tostring(SceneUtils.GetIsInWorld())..' inCity='.."
                 "tostring(SceneUtils.GetIsInCity()))")
        _, exc = x.dostring(chunk, "state")
        print(f"  state[{when}] logged to Player.log; exc[{x.excdesc(exc)}]")

    log_state("before")
    print(f"=== LuaEnv.DoString({call!r}) ===")
    ret, exc = x.dostring(call, "goto")
    print(f"  ret=0x{(ret or 0):x} exc[{x.excdesc(exc)}]")
    time.sleep(6.0)  # scene build + camera settle
    log_state("after")
    if do_shot:
        shot(x.pid, "gw_after.png" if not to_city else "gw_city_after.png")

    P.CloseHandle(x.h)
    # DoString swallows nothing: exc!=0 on the transition call means it failed.
    return 0 if not exc else 1


if __name__ == "__main__":
    sys.exit(main())
