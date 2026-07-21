"""Task #973 Step 2 — Capture base building collect command.

Steps:
1. Start trap_resource_collect in background
2. Inject user.leave.world to navigate to base
3. Screenshot, detect resource bubbles via HSV color
4. Click each bubble via win32api.mouse_event (NOT pydirectinput)
5. Print captured upstream command(s) for inject implementation
"""
import io, os, sys, time, subprocess, json, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

REPO = r'P:\projects abandoned\carono\last-war-vp-bot'
TOOLS = os.path.join(REPO, 'tools')
RESULTS = os.path.join(REPO, 'results')
WIN_PYTHON = r'C:\Python312\python.exe'
GAME_TITLE = 'Last War-Survival Game'

import win32api, win32con, win32gui, win32ui
import numpy as np
import cv2


# ── window helpers ──────────────────────────────────────────────────────────

def find_hwnd():
    hwnd = win32gui.FindWindow(None, GAME_TITLE)
    if not hwnd:
        found = []
        def _cb(h, _):
            if 'last war' in win32gui.GetWindowText(h).lower():
                found.append(h)
        win32gui.EnumWindows(_cb, None)
        hwnd = found[0] if found else 0
    return hwnd


def grab(hwnd):
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    dc = win32gui.GetWindowDC(hwnd)
    mdc = win32ui.CreateDCFromHandle(dc)
    sdc = mdc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mdc, w, h)
    sdc.SelectObject(bmp)
    sdc.BitBlt((0, 0), (w, h), mdc, (0, 0), win32con.SRCCOPY)
    info = bmp.GetInfo()
    data = bmp.GetBitmapBits(True)
    arr = np.frombuffer(data, dtype=np.uint8).reshape(
        (info['bmHeight'], info['bmWidth'], 4))
    win32gui.DeleteObject(bmp.GetHandle())
    sdc.DeleteDC(); mdc.DeleteDC()
    win32gui.ReleaseDC(hwnd, dc)
    return arr[:, :, :3]  # BGR


def focus_win(hwnd):
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.2)


def click_at(hwnd, sx, sy, label=''):
    """Click at window-relative (sx, sy) using win32api.mouse_event."""
    rect = win32gui.GetWindowRect(hwnd)
    ax, ay = rect[0] + sx, rect[1] + sy
    focus_win(hwnd)
    win32api.SetCursorPos((ax, ay))
    time.sleep(0.10)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.09)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.35)
    if label:
        print(f'  click {label} abs=({ax},{ay}) win=({sx},{sy})')


# ── bubble detection ────────────────────────────────────────────────────────

def find_collect_bubbles(img, debug_out=None):
    """HSV color filter for yellow/green/gold resource collect icons.

    Returns list of (cx, cy) sorted by area desc (largest first).
    Also saves annotated debug image if debug_out given.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # gold/yellow — food, oil icons
    m1 = cv2.inRange(hsv, (15, 100, 150), (38, 255, 255))
    # lime-green — lumber/wood icons
    m2 = cv2.inRange(hsv, (40, 80, 100), (85, 255, 255))
    # orange — some collect chest icons
    m3 = cv2.inRange(hsv, (5, 120, 150), (16, 255, 255))

    mask = cv2.bitwise_or(m1, cv2.bitwise_or(m2, m3))

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    hits = []
    dbg = img.copy() if debug_out else None

    for cnt in cnts:
        area = cv2.contourArea(cnt)
        if area < 120 or area > 12000:
            continue
        peri = cv2.arcLength(cnt, True)
        if peri < 1:
            continue
        circ = 4 * np.pi * area / (peri * peri)
        if circ < 0.30:
            continue
        M = cv2.moments(cnt)
        if M['m00'] == 0:
            continue
        cx = int(M['m10'] / M['m00'])
        cy = int(M['m01'] / M['m00'])
        hits.append((cx, cy, area, circ))
        if dbg is not None:
            cv2.circle(dbg, (cx, cy), 20, (0, 0, 255), 2)
            cv2.putText(dbg, f'a={int(area)} c={circ:.2f}',
                        (cx - 30, cy - 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)

    if debug_out and dbg is not None:
        cv2.imwrite(debug_out, dbg)

    hits.sort(key=lambda x: -x[2])
    return [(c[0], c[1]) for c in hits]


# ── inject helper ───────────────────────────────────────────────────────────

def run_inject(command, req_id, label, extra_args=()):
    """Run steal_via_socket.py and stream output until ws2.send or error."""
    cmd = [WIN_PYTHON, os.path.join(TOOLS, 'steal_via_socket.py'),
           '--sniff-and-inject', '--force',
           '--command', command,
           '--server-id', '935',
           '--req-id', str(req_id)] + list(extra_args)
    print(f'\n[{label}] launching inject: {" ".join(cmd[-6:])}')
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', bufsize=1,
        cwd=REPO, creationflags=0x08000000,
    )
    t0 = time.time()
    sent = False
    for line in proc.stdout:
        line = line.rstrip()
        print(f'  [{label}] {line}')
        if 'ws2.send: sent' in line:
            sent = True
            break
        if 'ERROR' in line or 'FAIL' in line or 'no upstream' in line:
            break
        if time.time() - t0 > 45:
            break
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    return sent


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════

hwnd = find_hwnd()
print(f'hwnd={hwnd}')
if not hwnd:
    print('ERROR: game window not found')
    sys.exit(1)

rect = win32gui.GetWindowRect(hwnd)
W, H = rect[2] - rect[0], rect[3] - rect[1]
print(f'window {W}x{H}')

# ── Step 1: Start trap in background ─────────────────────────────────────
trap_jsonl = os.path.join(RESULTS, 'trap_base_collect.jsonl')
trap_log   = os.path.join(RESULTS, 'trap_base_collect.log')
if os.path.exists(trap_jsonl):
    os.remove(trap_jsonl)

trap_proc = subprocess.Popen(
    [WIN_PYTHON, os.path.join(TOOLS, 'trap_resource_collect.py'),
     '--match', 'collect', '--seconds', '180', '--out', trap_jsonl],
    stdout=open(trap_log, 'w', encoding='utf-8'),
    stderr=subprocess.STDOUT,
    cwd=REPO, creationflags=0x08000000,
)
print(f'trap pid={trap_proc.pid}  log={trap_log}')
time.sleep(3)

# ── Step 2: Screenshot to see current state ───────────────────────────────
screen0 = grab(hwnd)
cv2.imwrite(os.path.join(RESULTS, 'base_01_current.png'), screen0)
print('saved base_01_current.png')

# ── Step 3: Navigate to base via inject ───────────────────────────────────
sent = run_inject('user.leave.world', req_id=5, label='leave_world')
if sent:
    print('leave.world sent — waiting 6 s for game to transition...')
    time.sleep(6)
else:
    print('leave.world send skipped/failed — proceeding anyway')
    time.sleep(2)

# ── Step 4: Screenshot after navigate ────────────────────────────────────
focus_win(hwnd)
time.sleep(0.4)
# Dismiss any popup that may have appeared
click_at(hwnd, int(0.05 * W), int(0.30 * H), 'dismiss-popup')
time.sleep(0.5)
screen1 = grab(hwnd)
cv2.imwrite(os.path.join(RESULTS, 'base_02_after_nav.png'), screen1)
print('saved base_02_after_nav.png')

# ── Step 5: Detect resource bubbles ──────────────────────────────────────
debug_path = os.path.join(RESULTS, 'base_03_bubbles_debug.png')
bubbles = find_collect_bubbles(screen1, debug_path)
print(f'detected {len(bubbles)} bubble(s): {bubbles}')

# ── Step 6: Click bubbles (or fallback building spots) ───────────────────
# Popup collect button relative positions
COLLECT_BTN = [
    (0.50, 0.71), (0.50, 0.66), (0.45, 0.69), (0.55, 0.69),
    (0.50, 0.75), (0.50, 0.62),
]

def click_building_and_collect(sx, sy, lbl, shot_tag):
    click_at(hwnd, sx, sy, lbl)
    time.sleep(1.3)
    s = grab(hwnd)
    cv2.imwrite(os.path.join(RESULTS, f'base_04_{shot_tag}.png'), s)
    # Try all collect button positions
    for cx_f, cy_f in COLLECT_BTN:
        click_at(hwnd, int(cx_f * W), int(cy_f * H), f'collect-btn@{cx_f:.0%},{cy_f:.0%}')
    # Dismiss popup
    click_at(hwnd, int(0.05 * W), int(0.25 * H), 'dismiss')
    time.sleep(0.5)


if bubbles:
    for i, (bx, by) in enumerate(bubbles[:8]):
        click_building_and_collect(bx, by, f'bubble#{i}', f'bubble{i}_{bx}_{by}')
else:
    print('no color bubbles found — clicking known building positions as fallback')
    BUILDING_FALLBACK = [
        # (rel_x, rel_y, label)
        (0.38, 0.50, 'farm'),
        (0.55, 0.46, 'sawmill'),
        (0.44, 0.60, 'mine'),
        (0.62, 0.53, 'oil'),
        # bubble floats above building top
        (0.38, 0.38, 'farm-top'),
        (0.55, 0.34, 'sawmill-top'),
        (0.44, 0.48, 'mine-top'),
    ]
    for fx, fy, lbl in BUILDING_FALLBACK:
        click_building_and_collect(int(fx * W), int(fy * H), lbl, lbl)

# Try "collect all" shortcut button (chest icon, usually top-right HUD)
print('\ntrying collect-all shortcut (top-right HUD)...')
for fx, fy in [(0.88, 0.07), (0.83, 0.07), (0.92, 0.12), (0.78, 0.07), (0.90, 0.10)]:
    click_at(hwnd, int(fx * W), int(fy * H), f'collect-all@{fx:.0%},{fy:.0%}')

screen_ca = grab(hwnd)
cv2.imwrite(os.path.join(RESULTS, 'base_04_collect_all.png'), screen_ca)

# ── Step 7: Read trap output ──────────────────────────────────────────────
print('\nwaiting 4 s for protocol trap to flush...')
time.sleep(4)
trap_proc.kill()
time.sleep(1)

captured = []
if os.path.exists(trap_jsonl):
    with open(trap_jsonl, encoding='utf-8') as f:
        for line in f:
            try:
                captured.append(json.loads(line))
            except Exception:
                pass

print(f'\n{"="*60}')
print(f'TRAP RESULTS: {len(captured)} record(s)')
for r in captured:
    d = r.get('dir', '?')
    cmd = r.get('command', '?')
    payload = r.get('payload')
    print(f"  [{d}] {cmd}")
    if payload:
        print(f"        payload: {json.dumps(payload, ensure_ascii=False)}")

upstream_collect = [r for r in captured if r.get('dir') == 'up']
if upstream_collect:
    print(f'\n*** FOUND {len(upstream_collect)} upstream collect command(s)! ***')
    for r in upstream_collect:
        print(f"  CMD:     {r['command']}")
        print(f"  PAYLOAD: {json.dumps(r.get('payload'), ensure_ascii=False, indent=4)}")
else:
    print('\nNo upstream collect command captured this run.')
    print('Check base_*.png screenshots to see game state.')
print('='*60)

# Final screenshot
screen_fin = grab(hwnd)
cv2.imwrite(os.path.join(RESULTS, 'base_05_final.png'), screen_fin)
print('saved base_05_final.png')
print('Done.')
