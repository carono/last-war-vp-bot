"""Orchestrate building.production.collect injection (Task #974).

Collects a base building's output (farm / sawmill / mine / oil / steel) via an
injected protocol command, without tapping the green bubble in the UI.

Prerequisite:
  - Game must be running and connected to :17935, on the CITY/base screen.
  - You need the building's UUID. Get it by trapping one manual collect:
        /mnt/c/Python312/python.exe -X utf8 tools/trap_all_up.py --seconds 60 \\
            --tshark "C:\\Program Files\\Wireshark\\tshark.exe" \\
            --dumpcap "C:\\Program Files\\Wireshark\\dumpcap.exe"
    then read the `uuid` field of the building.production.collect frame.

Protocol (trapped live 2026-07-21, task #974, protocol.md §8):
  upstream:  building.production.collect {uuid:<building_uuid>, _id:N}
  response:  building.production.collect / push.resource.item.update

Usage (run under Windows Python):
    /mnt/c/Python312/python.exe tools/run_collect_inject.py --uuid 1156814436946922740
    /mnt/c/Python312/python.exe tools/run_collect_inject.py --uuid <u1> --uuid <u2> ...
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


def nudge_base() -> None:
    """Pan the base a touch so the client emits a fresh upstream _id to sniff."""
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
    cx, cy = int(ox + 0.5 * w), int(oy + 0.55 * h)
    pydirectinput.moveTo(cx, cy)
    pydirectinput.mouseDown()
    pydirectinput.moveTo(cx - 60, cy)
    pydirectinput.moveTo(cx + 60, cy)
    pydirectinput.mouseUp()
    time.sleep(0.3)


def check_connection():
    import psutil
    for c in psutil.net_connections(kind="tcp"):
        if c.raddr and c.raddr.port == GAME_PORT and c.status == "ESTABLISHED":
            return c.laddr, c.raddr
    return None


def _inject_one(uuid: str, server_id: int) -> tuple[bool, int, str]:
    script = os.path.join(TOOLS, "steal_via_socket.py")
    cmd = [WIN_PYTHON, script, "--sniff-and-inject", "--force",
           "--command", "building.production.collect",
           "--uuid", uuid,
           "--server-id", str(server_id)]
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
    time.sleep(2.0)

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

    deadline = time.time() + 90
    while time.time() < deadline and not done_event.is_set():
        nudge_base()
        remaining = deadline - time.time()
        done_event.wait(timeout=min(8.0, remaining))

    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    t.join(timeout=5)

    output = "\n".join(output_lines)
    rc = proc.returncode if proc.returncode is not None else 99
    success = ("server_reply" in output or "[SUCCESS]" in output
               or "TCP-ACK confirmed" in output)
    return success, rc, output


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--uuid", action="append", required=True,
                    help="building UUID to collect (repeatable for several buildings)")
    ap.add_argument("--server-id", type=int, default=935,
                    help="home server ID (default: 935)")
    args = ap.parse_args()

    conn = check_connection()
    if not conn:
        print(f"[orch] ERROR: no :{GAME_PORT} ESTABLISHED — is the game running?")
        return 1
    laddr, raddr = conn
    print(f"[orch] :17935 ESTABLISHED  {laddr.ip}:{laddr.port} -> {raddr.ip}:{raddr.port}")
    print(f"[orch] buildings: {args.uuid}")

    results = []
    for uuid in args.uuid:
        print(f"\n[orch] === collecting building {uuid} ===")
        ok, rc, output = _inject_one(uuid, args.server_id)
        print(f"[orch] {'SUCCESS' if ok else 'FAILED'}  rc={rc}")
        results.append((uuid, ok, rc, output))

    any_ok = any(ok for _, ok, _, _ in results)

    results_dir = os.path.join(REPO, "results", "building_collect")
    os.makedirs(results_dir, exist_ok=True)
    result_path = os.path.join(results_dir, "RESULTS.md")
    with open(result_path, "w", encoding="utf-8") as f:
        f.write("# Task #974 — building.production.collect inject\n\n")
        f.write("**Protocol:** `building.production.collect {uuid:<building_uuid>, _id:N}`\n\n")
        for uuid, ok, rc, output in results:
            f.write(f"## building {uuid}\n\n")
            f.write(f"**Status:** {'SUCCESS' if ok else f'FAILED (rc={rc})'}\n\n")
            f.write(f"**inject stdout:**\n```\n{output}\n```\n\n")
    print(f"\n[orch] results → {result_path}")
    return 0 if any_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
