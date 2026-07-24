r"""Click a base building by its grid position (task: decode building coords + click).

Pipeline (docs/research/city-navigation.md):
  building pId  ->  grid (gx=pId%100, gy=pId//100)
  grid          ->  world (2*gx, 0, 2*gy)          # TileSize == 2, base grid on XZ, y=0
  world         ->  render px via the LIVE game camera (Camera.main:WorldToScreenPoint)
  render px     ->  desktop px via the window's client rect (Unity y is bottom-up)
  desktop px    ->  pydirectinput click (foreground input; PostMessage is ignored)

The camera projection is taken from the running game, so this tracks camera pans/zooms
automatically — no baked matrix. A target off-screen (z<=0 or outside the client) means
"pan the base to it first"; this tool does not scroll.

    C:\Python312\python.exe tools\city_click.py --grid 49 49            # dry: pixel only
    C:\Python312\python.exe tools\city_click.py --pid 6531 --click      # move + click it
"""
from __future__ import annotations
import sys
import time

sys.path.insert(0, "tools")
from lua_eval import LuaEval
import win32gui
import win32process
import win32con
import win32api

TILE = 2  # world units per grid cell (Lua global TileSize)


def find_window(pid=None):
    hs = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and "Last War" in win32gui.GetWindowText(h):
            _, p = win32process.GetWindowThreadProcessId(h)
            if pid is None or p == pid:
                r = win32gui.GetWindowRect(h)
                if r[2] - r[0] > 200 and r[3] - r[1] > 200:
                    hs.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    if not hs:
        raise SystemExit("game window not found")
    return hs[0]


def project(ev, gx, gy):
    """Live Camera.main:WorldToScreenPoint of the grid cell's ground point.
    Returns (render_x, render_y, depth) in the 1576x1032 render space (y bottom-up)."""
    chunk = (
        "local c=CS.UnityEngine.Camera.main "
        f"local s=c:WorldToScreenPoint(CS.UnityEngine.Vector3({TILE}*{gx},0,{TILE}*{gy})) "
        "CS.UnityEngine.Debug.LogError('CLICKPT '..s.x..' '..s.y..' '..s.z..' '..c.pixelWidth..' '..c.pixelHeight)"
    )
    for ln in ev.run(chunk, marker="CLICKPT"):
        p = ln.split("CLICKPT ", 1)[1].split()
        return float(p[0]), float(p[1]), float(p[2]), int(float(p[3])), int(float(p[4]))
    raise SystemExit("no projection returned (game not in a scene?)")


def main():
    argv = sys.argv[1:]
    do_click = "--click" in argv
    if "--grid" in argv:
        i = argv.index("--grid")
        gx, gy = int(argv[i + 1]), int(argv[i + 2])
    elif "--pid" in argv:
        pid_val = int(argv[argv.index("--pid") + 1])
        gx, gy = pid_val % 100, pid_val // 100
    else:
        raise SystemExit("pass --grid GX GY or --pid PID")

    ev = LuaEval()
    rx, ry, z, rw, rh = project(ev, gx, gy)
    ev.close()

    h = find_window()
    cw, ch = win32gui.GetClientRect(h)[2], win32gui.GetClientRect(h)[3]
    ox, oy = win32gui.ClientToScreen(h, (0, 0))
    # Unity render (origin bottom-left) -> desktop pixel. Client px scales if the
    # render target differs from the client size (usually equal, 1576x1032 here).
    cx = rx * cw / rw
    cy = (rh - ry) * ch / rh
    px, py = int(ox + cx), int(oy + cy)
    on = z > 0 and 0 <= rx <= rw and 0 <= ry <= rh
    print(f"grid=({gx},{gy}) world=({TILE*gx},0,{TILE*gy}) render=({rx:.1f},{ry:.1f}) depth={z:.1f} "
          f"desktop=({px},{py}) visible={on}")
    if not on:
        print("target off-screen — pan the base to it first; not clicking")
        return 1
    if do_click:
        import pydirectinput
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        try:
            win32gui.ShowWindow(h, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(h)
        except Exception:
            pass
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.6)
        pydirectinput.moveTo(px, py)
        time.sleep(0.15)
        pydirectinput.click(px, py)
        print(f"clicked ({px},{py})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
