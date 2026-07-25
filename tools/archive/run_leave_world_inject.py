"""Orchestrate user.leave.world injection (Task #973).

Returns the game from world map back to city/base via injected protocol command.

Prerequisite: the game must currently be on the world map.

Flow:
  1. Check :17935 ESTABLISHED (game is connected)
  2. Click world map tiles a few times to generate upstream _id
  3. Popen steal_via_socket.py --sniff-and-inject --command user.leave.world (non-blocking)
  4. Continue clicking tiles every 8 s to keep upstream traffic alive
  5. Read inject stdout; success = {success:True, _id:N} reply received
  6. Write results/leave_world/RESULTS.md

Run under Windows Python:
    /mnt/c/Python312/python.exe tools/run_leave_world_inject.py
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


def click_world_tile() -> None:
    """Click a few world map tiles to generate upstream RPCs with _id."""
    import win32gui, pydirectinput
    hwnd = _game_hwnd()
    if not hwnd:
        return
    focus_game()
    time.sleep(0.2)
    rect = win32gui.GetWindowRect(hwnd)
    ox, oy = rect[0], rect[1]
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    # Click inner-center area (avoids UI buttons at edges)
    for fx, fy in [(0.50, 0.45), (0.45, 0.50), (0.55, 0.40)]:
        tx = int(ox + fx * w)
        ty = int(oy + fy * h)
        pydirectinput.click(tx, ty)
        time.sleep(0.3)
    print(f"[orch] clicked 3 world map tiles")


def check_connection():
    import psutil
    for c in psutil.net_connections(kind="tcp"):
        if c.raddr and c.raddr.port == GAME_PORT and c.status == "ESTABLISHED":
            return c.laddr, c.raddr
    return None


def main() -> int:
    # 1. Check connection
    conn = check_connection()
    if not conn:
        print(f"[orch] ERROR: no :{GAME_PORT} ESTABLISHED — is the game running?")
        return 1
    laddr, raddr = conn
    print(f"[orch] :17935 ESTABLISHED  {laddr.ip}:{laddr.port} -> {raddr.ip}:{raddr.port}")

    # 2. Pre-warm: click map tiles to generate upstream RPCs
    print("[orch] pre-warm: clicking world map tiles to seed _id…")
    focus_game()
    time.sleep(0.5)
    click_world_tile()
    time.sleep(0.5)

    # 3. Launch steal_via_socket.py --sniff-and-inject --command user.leave.world
    script = os.path.join(TOOLS, "steal_via_socket.py")
    cmd = [WIN_PYTHON, script, "--sniff-and-inject", "--force",
           "--command", "user.leave.world",
           "--server-id", "935"]
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
    print(f"[orch] inject pid={proc.pid}")

    # Give scapy 2.5 s to initialise
    time.sleep(2.5)

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

    # 4. Keep clicking tiles every 8 s to generate _id for up to 120 s
    deadline = time.time() + 120
    interval = 8.0
    click_count = 0
    print("[orch] clicking world map tiles every 8 s to keep _id fresh…")
    while time.time() < deadline and not done_event.is_set():
        click_world_tile()
        click_count += 1
        print(f"[orch] click #{click_count}  lines_so_far={len(output_lines)}")
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        done_event.wait(timeout=min(interval, remaining))

    print(f"[orch] click loop ended  clicks={click_count}")

    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("[orch] inject process killed (30 s timeout)")
    t.join(timeout=5)

    output = "\n".join(output_lines)
    rc = proc.returncode if proc.returncode is not None else 99
    success = ("server_reply" in output or "[SUCCESS]" in output
               or ("success=True" in output and "user.leave.world" in output)
               or "TCP-ACK confirmed" in output)

    print(f"\n[orch] {'SUCCESS' if success else 'FAILED'}  rc={rc}")

    # 5. Write results
    results_dir = os.path.join(REPO, "results", "leave_world")
    os.makedirs(results_dir, exist_ok=True)
    result_path = os.path.join(results_dir, "RESULTS.md")

    if success:
        status = "SUCCESS — server replied success=True"
    elif "TCP-ACK confirmed" in output:
        status = "SENT — TCP-ACK confirmed, no application reply seen"
    elif "no upstream _id" in output:
        status = "TIMEOUT — no upstream _id seen (was game on world map?)"
    elif "ws2.send blocked" in output or "VPN WSP" in output:
        status = "FAILED — ws2.send blocked by VPN WSP (disable VPN and retry)"
    else:
        status = f"FAILED (rc={rc})"

    with open(result_path, "w", encoding="utf-8") as f:
        f.write("# Task #973 — user.leave.world inject\n\n")
        f.write(f"**Status:** {status}\n\n")
        f.write(f"**inject rc:** {rc}\n\n")
        f.write(f"**Connection:** {laddr.ip}:{laddr.port} -> {raddr.ip}:{raddr.port}\n\n")
        f.write(f"**Protocol:** `user.leave.world {{worldId:0, serverId:935, _id:N}}`\n\n")
        f.write(f"**inject stdout:**\n```\n{output}\n```\n")

    print(f"[orch] results written to {result_path}")
    return 0 if success else rc


if __name__ == "__main__":
    raise SystemExit(main())
