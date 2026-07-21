import sys, time
sys.path.insert(0, 'src')
import win32api, win32con, win32gui
from lastwar_bot.perception.capture import find_window, get_client_size

info = find_window('Last War-Survival Game', 'LastWar.exe')
hwnd = info.hwnd
w, h = get_client_size(hwnd)
cx, cy = w // 2, h // 2

def focus():
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        print('focus warn:', e)
    time.sleep(0.15)

def drag(dx, dy, steps=25, hold=0.006):
    # start near center, drag by (dx,dy) in client px
    sx, sy = win32gui.ClientToScreen(hwnd, (cx - dx // 2, cy - dy // 2))
    ex, ey = win32gui.ClientToScreen(hwnd, (cx + dx // 2, cy + dy // 2))
    win32api.SetCursorPos((sx, sy))
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    for i in range(1, steps + 1):
        ix = int(sx + (ex - sx) * i / steps)
        iy = int(sy + (ey - sy) * i / steps)
        win32api.SetCursorPos((ix, iy))
        time.sleep(hold)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.25)

focus()
dirs = [(700,0),(0,500),(-700,0),(-700,0),(0,-500),(0,-500),(700,0),(700,0),
        (0,500),(-500,300),(500,-300),(-700,0),(0,500),(700,0),(0,-500),(-500,0)]
n = int(sys.argv[1]) if len(sys.argv) > 1 else len(dirs)
for i in range(n):
    dx, dy = dirs[i % len(dirs)]
    drag(dx, dy)
    print('drag', i+1, (dx,dy), flush=True)
print('done panning')
