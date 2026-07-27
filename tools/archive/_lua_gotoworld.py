r"""Trigger the real City->World flow from Lua (task #1017 scratch).

xLua DoString works via the STATIC facade GameEntry.get_Lua() -> XLuaManager, then
XLuaManager.SafeDoString(string). _G exposes the game's Lua API; candidates:
  GoToUtil.TryJumpToWorld()  (full flow the UI likely calls)
  SceneUtils.ChangeToWorld() (lower-level scene change)
This logs state, screenshots BEFORE, runs the chosen chunk, screenshots AFTER,
and logs state again. Read output markers from the Unity Player.log.
"""
from __future__ import annotations
import os, sys, time, ctypes as C
sys.path.insert(0, "tools/lib")
import xlua_route as XR
import il2cpp_dump as D
import il2cpp_probe as P
import mss, win32gui, win32process, win32con, win32api

# Results dir under the repo root (tools/archive/… → repo) — no hardcoded machine path.
RES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "results")
GET_LUA = 0x129eaa8e8      # GameEntry.get_Lua (static) -> XLuaManager
SAFEDO = 0x13d0e4830       # XLuaManager.SafeDoString(string)


def shot(pid, name):
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
        print("  no window"); return
    h, r = hs[0]
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.ShowWindow(h, win32con.SW_RESTORE); win32gui.SetForegroundWindow(h)
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
    chunk = sys.argv[1] if len(sys.argv) > 1 else "GoToUtil.TryJumpToWorld()"
    x = XR.X()
    mgr, _ = x.invoke(GET_LUA, 0, [], "get_Lua")
    print(f"XLuaManager=0x{mgr:x}")

    def run(lua):
        s = x.il2_string_new(lua)
        x.invoke(SAFEDO, mgr, [("ref", s)], "SafeDoString")

    def logstate(tag):
        run(f"CS.UnityEngine.Debug.LogError('XLUA_STATE {tag} inWorld='..tostring(SceneUtils.GetIsInWorld())"
            f"..' inCity='..tostring(SceneUtils.GetIsInCity()))")

    logstate("before")
    print("BEFORE screenshot:"); shot(x.pid, "gw_before.png")

    print(f"=== run: {chunk} ===")
    # wrap in pcall so we capture any error into the log
    run(f"CS.UnityEngine.Debug.LogError('XLUA_CALL start'); local ok,err=pcall(function() {chunk} end); "
        f"CS.UnityEngine.Debug.LogError('XLUA_CALL done ok='..tostring(ok)..' err='..tostring(err))")
    time.sleep(6.0)

    logstate("after")
    print("AFTER screenshot:"); shot(x.pid, "gw_after.png")
    P.CloseHandle(x.h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
