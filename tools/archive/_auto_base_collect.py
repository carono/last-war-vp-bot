"""Auto: navigate to base + click resource buildings to trigger collect commands."""
import io, os, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

# Repo root derived from this file's location (tools/archive/…) — no hardcoded machine path.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES = os.path.join(REPO, 'src', 'lastwar_bot', 'game', 'templates')
RESULTS   = os.path.join(REPO, 'results')
GAME_TITLE = "Last War-Survival Game"

import cv2, numpy as np
import win32gui, win32ui, win32con, win32api
import pydirectinput

def grab(hwnd):
    l,t,r,b = win32gui.GetWindowRect(hwnd)
    w,h = r-l, b-t
    dc = win32gui.GetWindowDC(hwnd)
    mdc = win32ui.CreateDCFromHandle(dc)
    sdc = mdc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mdc, w, h)
    sdc.SelectObject(bmp)
    sdc.BitBlt((0,0),(w,h),mdc,(0,0),win32con.SRCCOPY)
    info = bmp.GetInfo(); data = bmp.GetBitmapBits(True)
    arr = np.frombuffer(data, dtype=np.uint8).reshape((info['bmHeight'],info['bmWidth'],4))
    win32gui.DeleteObject(bmp.GetHandle()); sdc.DeleteDC(); mdc.DeleteDC()
    win32gui.ReleaseDC(hwnd, dc)
    return arr[:,:,:3]

def find_hwnd():
    hwnd = win32gui.FindWindow(None, GAME_TITLE)
    if hwnd: return hwnd
    found = []
    def cb(h,_):
        if 'last war' in win32gui.GetWindowText(h).lower(): found.append(h)
    win32gui.EnumWindows(cb, None)
    return found[0] if found else 0

def focus(hwnd):
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try: win32gui.SetForegroundWindow(hwnd)
    except: pass
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.4)

def match_tpl(screen, path, thr=0.70):
    tpl = cv2.imread(path, cv2.IMREAD_COLOR)
    if tpl is None: return None, 0.0
    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    _, val, _, loc = cv2.minMaxLoc(res)
    h,w = tpl.shape[:2]
    return ((loc[0]+w//2, loc[1]+h//2), val) if val >= thr else (None, val)

def clk(hwnd, sx, sy):
    r = win32gui.GetWindowRect(hwnd)
    pydirectinput.click(r[0]+sx, r[1]+sy)
    time.sleep(0.35)

# ── init ───────────────────────────────────────────────────────────────────
hwnd = find_hwnd()
print(f'hwnd={hwnd}')
if not hwnd: print('ERROR: game not found'); sys.exit(1)

focus(hwnd)
time.sleep(0.4)
screen = grab(hwnd)
rect = win32gui.GetWindowRect(hwnd)
W = rect[2]-rect[0]; H = rect[3]-rect[1]
print(f'window {W}x{H}')
cv2.imwrite(os.path.join(RESULTS,'auto_01_before.png'), screen)

# ── Step 1: go to base ────────────────────────────────────────────────────
went_to_base = False
for tpl_name in ('toggle_to_base.png', 'toggle_to_base_fs.png'):
    pos, val = match_tpl(screen, os.path.join(TEMPLATES, tpl_name))
    print(f'  {tpl_name}: val={val:.3f} pos={pos}')
    if pos:
        clk(hwnd, pos[0], pos[1])
        print(f'  -> clicked toggle_to_base')
        time.sleep(3.5)
        went_to_base = True
        break

if not went_to_base:
    # Fallback: bottom-left corner (typical "return to base" location)
    fb = (int(0.07*W), int(0.87*H))
    print(f'  toggle_to_base not found -> fallback ({fb[0]},{fb[1]})')
    clk(hwnd, fb[0], fb[1])
    time.sleep(3.5)

screen2 = grab(hwnd)
cv2.imwrite(os.path.join(RESULTS,'auto_02_base.png'), screen2)
print('base screenshot saved')

# ── Step 2: close any open popup ─────────────────────────────────────────
clk(hwnd, int(0.05*W), int(0.50*H))
time.sleep(0.5)

# ── Step 3: click resource buildings ─────────────────────────────────────
# In Last War base the farm/sawmill/mine are center of screen, collect button
# appears in a popup at roughly center-bottom.
# Also try HUD resource icons (top of screen) which may have collect shortcut.
print('\n--- resource building clicks ---')

def try_collect_at(bx, by, label):
    print(f'building click: {label} ({bx},{by})')
    clk(hwnd, bx, by)
    time.sleep(0.9)
    s = grab(hwnd)
    cv2.imwrite(os.path.join(RESULTS, f'auto_03_{label}.png'), s)
    # popup collect button guesses
    for cx, cy in [
        (int(0.50*W), int(0.72*H)),
        (int(0.50*W), int(0.65*H)),
        (int(0.43*W), int(0.70*H)),
        (int(0.57*W), int(0.70*H)),
    ]:
        clk(hwnd, cx, cy)
        time.sleep(0.35)
    # dismiss popup
    clk(hwnd, int(0.05*W), int(0.25*H))
    time.sleep(0.4)

building_spots = [
    (int(0.38*W), int(0.52*H), 'farm'),
    (int(0.55*W), int(0.48*H), 'sawmill'),
    (int(0.45*W), int(0.62*H), 'mine'),
    (int(0.62*W), int(0.56*H), 'oil'),
]
for bx, by, lbl in building_spots:
    try_collect_at(bx, by, lbl)

# Also try top-right HUD area (some Last War versions have collect-all shortcut)
print('trying HUD collect-all area...')
for fx, fy in [(0.88,0.06),(0.82,0.06),(0.92,0.10)]:
    clk(hwnd, int(fx*W), int(fy*H))
    time.sleep(0.5)

screen3 = grab(hwnd)
cv2.imwrite(os.path.join(RESULTS,'auto_04_final.png'), screen3)
print('\nAll clicks done. Trap should have the command.')
