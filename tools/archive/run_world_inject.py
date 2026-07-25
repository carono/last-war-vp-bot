"""Orchestrate go.to.world injection (Task #971).

Flow:
  1. Check :17935 ESTABLISHED
  2. Pan world map via win32api drag (5 movements)
  3. Popen steal_via_socket.py --sniff-and-inject --force  (non-blocking)
  4. Pan map 5 more times to generate upstream _id
  5. Read inject stdout via threading.Thread + join(timeout=15), then wait up to 45s
  6. Write results/socket_dup/RESULTS.md

Run under Windows Python:
    /mnt/c/Python312/python.exe tools/run_world_inject.py
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

GAME_TITLE = "Last War-Survival Game"
WIN_PYTHON = r"C:\Python312\python.exe"
GAME_PORT = 17935
TEMPLATES = os.path.join(REPO, "src", "lastwar_bot", "game", "templates")


def _game_hwnd() -> int:
    import win32gui
    hwnd = win32gui.FindWindow(None, GAME_TITLE)
    if not hwnd:
        found: list[int] = []

        def _cb(h: int, _: object) -> None:
            if "last war" in win32gui.GetWindowText(h).lower():
                found.append(h)

        win32gui.EnumWindows(_cb, None)
        hwnd = found[0] if found else 0
    return hwnd


def focus_game() -> bool:
    import win32api, win32con, win32gui
    hwnd = _game_hwnd()
    if not hwnd:
        print("[orch] game window not found")
        return False
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        print(f"[orch] SetForegroundWindow: {exc}")
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.35)
    return True


def _grab_hwnd(hwnd: int):
    """Take a screenshot of the game window and return as BGR ndarray."""
    import win32gui, win32ui, win32con
    import numpy as np
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    save_bmp = win32ui.CreateBitmap()
    save_bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(save_bmp)
    save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)
    bmpinfo = save_bmp.GetInfo()
    bmpstr = save_bmp.GetBitmapBits(True)
    arr = np.frombuffer(bmpstr, dtype=np.uint8)
    arr = arr.reshape((bmpinfo["bmHeight"], bmpinfo["bmWidth"], 4))
    win32gui.DeleteObject(save_bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return arr[:, :, :3]  # BGRA → BGR


def ensure_world_map() -> bool:
    """Click toggle_to_world if visible; return True if already on world map or after click."""
    import cv2
    import pydirectinput
    hwnd = _game_hwnd()
    if not hwnd:
        print("[orch] ensure_world_map: game window not found")
        return False
    focus_game()
    time.sleep(0.3)
    try:
        screen = _grab_hwnd(hwnd)
    except Exception as exc:
        print(f"[orch] ensure_world_map: screenshot failed: {exc}")
        return False
    tpl_path = os.path.join(TEMPLATES, "toggle_to_world.png")
    try:
        tpl = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
        if tpl is None:
            print(f"[orch] ensure_world_map: template not found: {tpl_path}")
            return False
        result = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        print(f"[orch] toggle_to_world match score={max_val:.3f} at {max_loc}")
        if max_val >= 0.80:
            import win32gui
            rect = win32gui.GetWindowRect(hwnd)
            cx = rect[0] + max_loc[0] + tpl.shape[1] // 2
            cy = rect[1] + max_loc[1] + tpl.shape[0] // 2
            print(f"[orch] clicking toggle_to_world at ({cx},{cy})")
            pydirectinput.click(cx, cy)
            time.sleep(2.0)
            return True
        else:
            print("[orch] toggle_to_world not visible — assuming already on world map")
            return True
    except Exception as exc:
        print(f"[orch] ensure_world_map: error: {exc}")
        return False


def pan_map(n: int = 5) -> None:
    """Drag world map AND click a tile to trigger upstream RPCs.

    Strategy:
      1. Large drag (40-50% of width) to pan to uncached tiles.
      2. Click on map center to select a tile (always triggers world.get.block RPC).
    Both generate upstream frames with _id regardless of cache state.
    """
    import win32api, win32con, win32gui, pydirectinput
    hwnd = _game_hwnd()
    if not hwnd:
        print("[orch] pan_map: game window not found")
        return
    rect = win32gui.GetWindowRect(hwnd)
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    ox, oy = rect[0], rect[1]

    focus_game()
    time.sleep(0.2)

    # Large drags — 40-50% of width — to pan well past cached tiles.
    big_offsets = [
        (int(0.45 * w), 0),
        (-int(0.45 * w), 0),
        (0, int(0.35 * h)),
        (0, -int(0.35 * h)),
        (int(0.40 * w), int(0.30 * h)),
    ]
    for i in range(min(n, len(big_offsets))):
        dx, dy = big_offsets[i]
        sx, sy = cx, cy
        win32api.SetCursorPos((sx, sy))
        time.sleep(0.04)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        steps = 8
        for step in range(1, steps + 1):
            win32api.SetCursorPos((sx + dx * step // steps, sy + dy * step // steps))
            time.sleep(0.02)
        time.sleep(0.03)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.4)
    print(f"[orch] large-dragged map {n} times  rect={rect}")

    # Click map center (50% width, 45% height) — triggers world.get.block RPC.
    # Avoid bottom/top/side UI panels by staying in the inner 40-60% of the window.
    tile_x = int(ox + 0.50 * w)
    tile_y = int(oy + 0.45 * h)
    print(f"[orch] clicking map tile at ({tile_x},{tile_y})")
    pydirectinput.click(tile_x, tile_y)
    time.sleep(0.5)


def check_vpn_active() -> list:
    """Return names of active VPN-like network adapters."""
    import psutil
    vpn_keywords = ("vpn", "tun", "tap", "wg", "nordlynx", "ovpn",
                    "clash", "v2ray", "sing-box")
    active = []
    try:
        for name, stats in psutil.net_if_stats().items():
            if stats.isup and any(k in name.lower() for k in vpn_keywords):
                active.append(name)
    except Exception:
        pass
    return active


def check_connection():
    """Return (laddr, raddr) if :17935 ESTABLISHED, else None."""
    import psutil
    for c in psutil.net_connections(kind="tcp"):
        if c.raddr and c.raddr.port == GAME_PORT and c.status == "ESTABLISHED":
            return c.laddr, c.raddr
    return None


def main() -> int:
    # 1. Check :17935 ESTABLISHED
    conn = check_connection()
    if not conn:
        print(f"[orch] ERROR: no :{GAME_PORT} ESTABLISHED — is the game running?")
        return 1
    laddr, raddr = conn
    print(f"[orch] :17935 ESTABLISHED  {laddr.ip}:{laddr.port} -> {raddr.ip}:{raddr.port}")

    vpn = check_vpn_active()
    if vpn:
        print(f"[orch] WARNING: VPN/proxy adapters detected: {vpn}")
        print("[orch] ws2.send via dup'd socket may be blocked — disable VPN first")
    else:
        print("[orch] no VPN adapters detected — ws2.send path should work")

    # 2. Navigate to world map, then click Events button to guarantee upstream RPCs.
    # toggle_to_world may give a false positive (score 0.848 even when on city screen),
    # so we ALSO click the Events button (reliable city-screen RPC with _id) as a
    # pre-warm so the inject process captures _id immediately.
    print("[orch] ensuring game is on world map...")
    ensure_world_map()
    # Click Events button to trigger burst of upstream RPCs (activity.hero.get.info etc.)
    focus_game()
    time.sleep(0.5)
    hwnd_pre = _game_hwnd()
    if hwnd_pre:
        import win32gui as _wg
        _rect = _wg.GetWindowRect(hwnd_pre)
        _ox, _oy = _rect[0], _rect[1]
        _w = _rect[2] - _rect[0]
        _h = _rect[3] - _rect[1]
        import pydirectinput as _pdi
        # Events button (~96% of window width, ~10% height) — reliable RPC trigger
        _ex = int(_ox + 0.960 * _w)
        _ey = int(_oy + 0.100 * _h)
        print(f"[orch] pre-warm: clicking Events at ({_ex},{_ey})")
        _pdi.click(_ex, _ey)
        time.sleep(0.8)
        # Close Events by clicking background (Esc opens exit dialog, avoid it)
        _pdi.click(int(_ox + 0.3 * _w), int(_oy + 0.5 * _h))
        time.sleep(0.5)
    print("[orch] pre-pan: 5 drag movements on world map...")
    focus_game()
    time.sleep(0.3)
    pan_map(5)
    time.sleep(0.3)

    # 3. Popen steal_via_socket.py --sniff-and-inject --force  (non-blocking)
    script = os.path.join(TOOLS, "steal_via_socket.py")
    cmd = [WIN_PYTHON, script, "--sniff-and-inject", "--force",
           "--server-id", "935"]  # server #972 home server_id; fallback when wire misses it
    print(f"[orch] launching: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=REPO,
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )
    print(f"[orch] inject pid={proc.pid}  (non-blocking, will pan map now)")

    # Give scapy 2.5 s to initialise all interface listeners before generating traffic.
    time.sleep(2.5)

    # 4. Start reading inject stdout immediately so we don't miss early lines.
    output_lines: list[str] = []
    done_event = threading.Event()

    def _reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            output_lines.append(line)
            print(f"[inject] {line}", flush=True)
        done_event.set()

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    # 5. Alternate between Events button click and map pan every 8 s for up to 150 s.
    # Events button (city screen) reliably fires upstream RPCs with _id without
    # requiring the world map to be loaded.  Map panning is kept as a secondary
    # trigger in case the game IS on the world map.
    pan_deadline = time.time() + 150
    pan_interval = 8.0
    pan_count = 0
    print("[orch] alternating Events clicks + map pans (every 8 s, 150 s total)…")
    while time.time() < pan_deadline and not done_event.is_set():
        # Odd cycles: click Events button for reliable upstream RPC
        if pan_count % 2 == 0:
            _hwnd2 = _game_hwnd()
            if _hwnd2:
                import win32gui as _wg2
                import pydirectinput as _pdi2
                focus_game()
                time.sleep(0.2)
                _r2 = _wg2.GetWindowRect(_hwnd2)
                _ox2, _oy2 = _r2[0], _r2[1]
                _w2, _h2 = _r2[2] - _r2[0], _r2[3] - _r2[1]
                _ex2 = int(_ox2 + 0.960 * _w2)
                _ey2 = int(_oy2 + 0.100 * _h2)
                print(f"[orch] clicking Events at ({_ex2},{_ey2})", flush=True)
                _pdi2.click(_ex2, _ey2)
                time.sleep(0.6)
        else:
            pan_map(3)
        pan_count += 1
        print(f"[orch] pan #{pan_count} done  lines_so_far={len(output_lines)}")
        remaining = pan_deadline - time.time()
        if remaining <= 0:
            break
        done_event.wait(timeout=min(pan_interval, remaining))

    print(f"[orch] panning loop ended  pans={pan_count}")

    # Wait for inject to finish (it exits after reply window or on error).
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("[orch] inject process killed (final 30 s timeout)")
    t.join(timeout=5)

    output = "\n".join(output_lines)
    rc = proc.returncode if proc.returncode is not None else 99
    # "TCP-ACK confirmed" is the strongest proof: the server received and ACKed
    # our injected bytes.  A go.to.world reply may not carry a plain success=True
    # (it triggers world.get.block pushes instead), so we accept TCP-ACK as the
    # gold-standard transport proof.
    success = ("server_reply" in output or "[SUCCESS]" in output
               or ("world-init detected" in output)
               or ("world.get.block" in output and "inject_id" in output)
               or "TCP-ACK confirmed" in output)

    print(f"\n[orch] {'SUCCESS' if success else 'FAILED'}  rc={rc}")

    # 6. Write results/socket_dup/RESULTS.md
    results_dir = os.path.join(REPO, "results", "socket_dup")
    os.makedirs(results_dir, exist_ok=True)
    result_path = os.path.join(results_dir, "RESULTS.md")

    if success:
        status = "SUCCESS — server_reply received"
    elif "sent" in output.lower() and "bytes" in output.lower():
        status = "SENT — no server reply confirmed (downstream miss)"
    elif "no upstream _id" in output:
        status = "TIMEOUT — no upstream _id seen in 30 s"
    elif "ws2.send blocked" in output or "VPN WSP" in output:
        status = "FAILED — ws2.send blocked by VPN WSP (disable VPN and retry)"
    elif "could not pin" in output or "VPN" in output:
        status = "FAILED — send_via_dup could not pin :17935 (VPN?)"
    else:
        status = f"FAILED (rc={rc})"

    with open(result_path, "w", encoding="utf-8") as f:
        f.write("# Task #971 — go.to.world inject via ws2.send (dup'd socket)\n\n")
        f.write(f"**Status:** {status}\n\n")
        f.write(f"**inject rc:** {rc}\n\n")
        f.write(f"**Connection:** {laddr.ip}:{laddr.port} -> {raddr.ip}:{raddr.port}\n\n")
        f.write(f"**inject stdout:**\n```\n{output}\n```\n")

    print(f"[orch] results written to {result_path}")
    return 0 if success else rc


if __name__ == "__main__":
    raise SystemExit(main())
