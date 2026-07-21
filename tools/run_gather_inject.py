"""Orchestrate gather.collect.reward injection (Task #973).

Collects resources from completed world-map gathering marches via injected
protocol command, without needing to interact with the game UI.

Prerequisite:
  - Game must be running and connected to :17935
  - You must have at least one completed gathering march (troops returned)
  - Get the march UUID from scan_trucks results or live sniff

Protocol (observed in live_5min.log 2026-07-xx):
  upstream:  gather.collect.reward {uuidArr:[<march_uuid>,...], _id:N}
  response:  {reward:[...], collect_reward:[], _id:N}

Usage:
    # First, find completed march UUIDs from truck scan data or live log:
    #   grep gather results/live_*.log
    #   python3 tools/scan_trucks.py --wait 60

    # Then inject:
    /mnt/c/Python312/python.exe tools/run_gather_inject.py --uuid-arr 1394584906709054020

Run under Windows Python:
    /mnt/c/Python312/python.exe tools/run_gather_inject.py --uuid-arr <uuid1>[,<uuid2>...]
"""
from __future__ import annotations

import argparse
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

WIN_PYTHON = r"C:\Python312\python.exe"
GAME_TITLE = "Last War-Survival Game"
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
        return False
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.35)
    return True


def click_map_tile() -> None:
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
    for fx, fy in [(0.50, 0.45), (0.45, 0.50)]:
        pydirectinput.click(int(ox + fx * w), int(oy + fy * h))
        time.sleep(0.3)


def check_connection():
    import psutil
    for c in psutil.net_connections(kind="tcp"):
        if c.raddr and c.raddr.port == GAME_PORT and c.status == "ESTABLISHED":
            return c.laddr, c.raddr
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--uuid-arr", required=True,
                    help="comma-separated march UUIDs to collect (from scan_trucks or live log)")
    ap.add_argument("--server-id", type=int, default=935,
                    help="home server ID (default: 935)")
    args = ap.parse_args()

    conn = check_connection()
    if not conn:
        print(f"[orch] ERROR: no :{GAME_PORT} ESTABLISHED")
        return 1
    laddr, raddr = conn
    print(f"[orch] :17935 ESTABLISHED  {laddr.ip}:{laddr.port} -> {raddr.ip}:{raddr.port}")
    print(f"[orch] uuid-arr: {args.uuid_arr}")

    # Pre-warm
    print("[orch] pre-warm: clicking map tiles…")
    focus_game()
    time.sleep(0.5)
    click_map_tile()
    time.sleep(0.5)

    script = os.path.join(TOOLS, "steal_via_socket.py")
    cmd = [WIN_PYTHON, script, "--sniff-and-inject", "--force",
           "--command", "gather.collect.reward",
           "--uuid-arr", args.uuid_arr,
           "--server-id", str(args.server_id)]
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
        creationflags=0x08000000,
    )
    print(f"[orch] inject pid={proc.pid}")
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

    deadline = time.time() + 120
    click_count = 0
    while time.time() < deadline and not done_event.is_set():
        click_map_tile()
        click_count += 1
        remaining = deadline - time.time()
        done_event.wait(timeout=min(8.0, remaining))

    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    t.join(timeout=5)

    output = "\n".join(output_lines)
    rc = proc.returncode if proc.returncode is not None else 99
    success = ("server_reply" in output or "[SUCCESS]" in output
               or "TCP-ACK confirmed" in output)

    print(f"\n[orch] {'SUCCESS' if success else 'FAILED'}  rc={rc}")

    results_dir = os.path.join(REPO, "results", "gather_collect")
    os.makedirs(results_dir, exist_ok=True)
    result_path = os.path.join(results_dir, "RESULTS.md")

    status = ("SUCCESS" if success
              else "TIMEOUT — no upstream _id" if "no upstream _id" in output
              else f"FAILED (rc={rc})")

    with open(result_path, "w", encoding="utf-8") as f:
        f.write("# Task #973 — gather.collect.reward inject\n\n")
        f.write(f"**Status:** {status}\n\n")
        f.write(f"**uuid-arr:** {args.uuid_arr}\n\n")
        f.write(f"**Protocol:** `gather.collect.reward {{uuidArr:[...], _id:N}}`\n\n")
        f.write(f"**inject stdout:**\n```\n{output}\n```\n")

    print(f"[orch] results → {result_path}")
    return 0 if success else rc


if __name__ == "__main__":
    raise SystemExit(main())
