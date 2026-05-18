"""Synthetic input to the game window (Windows-only).

Two backends are exposed; each has trade-offs that depend on the game:

- ``foreground`` — uses ``pydirectinput`` + ``SetForegroundWindow``. The
  Last War window is raised to the front, the cursor is moved, and a real
  click is sent. Reliable, but the game must be focused, and the cursor
  visibly jumps.
- ``background`` — posts ``WM_LBUTTONDOWN`` / ``WM_LBUTTONUP`` directly to
  the window handle via ``PostMessage``. No focus, the cursor isn't
  moved. Many DirectX games ignore these messages — must be verified per
  game.

CLI:

    python -m lastwar_bot.inputs X Y [--mode foreground|background] [--no-verify]

The verify mode (default on) captures a screenshot before and after the
click and reports how many pixels changed, so we can tell whether the
click actually landed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Literal

from .perception.capture import find_window, grab

InputMode = Literal["foreground", "background"]


def click(hwnd: int, x: int, y: int, mode: InputMode = "background") -> None:
    """Click at client coordinates (x, y) in window `hwnd`."""
    if mode == "background":
        _click_background(hwnd, x, y)
    elif mode == "foreground":
        _click_foreground(hwnd, x, y)
    else:
        raise ValueError(f"Unknown mode: {mode!r}")


def _client_lparam(x: int, y: int) -> int:
    """Pack client coordinates into an LPARAM for mouse messages."""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def _click_background(hwnd: int, x: int, y: int) -> None:
    import win32api
    import win32con

    lparam = _client_lparam(x, y)
    # Many games hit-test against the last seen cursor position — move first.
    win32api.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)


def _click_foreground(hwnd: int, x: int, y: int) -> None:
    import win32api
    import win32con
    import win32gui

    # Best-effort focus. SetForegroundWindow can be denied by Windows focus-
    # stealing protection; the caller should normally have user-triggered
    # focus recently.
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.05)

    sx, sy = win32gui.ClientToScreen(hwnd, (x, y))

    # Use SetCursorPos + mouse_event instead of pydirectinput.moveTo. The
    # latter routes through SendInput with normalised 0-65535 coordinates
    # relative to the primary monitor, which mis-positions clicks on
    # secondary monitors (especially ones with negative screen-x). The
    # win32api path uses raw screen pixels and addresses the full virtual
    # desktop directly.
    win32api.SetCursorPos((sx, sy))
    time.sleep(0.02)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _main() -> int:
    import argparse

    import cv2
    import numpy as np

    p = argparse.ArgumentParser(description="Click into the Last War window.")
    p.add_argument("x", type=int, help="Client X coordinate")
    p.add_argument("y", type=int, help="Client Y coordinate")
    p.add_argument("--mode", choices=["foreground", "background"], default="background")
    p.add_argument("--title", default="Last War-Survival Game")
    p.add_argument("--process", default="LastWar.exe")
    p.add_argument("--no-verify", action="store_true", help="Skip the before/after diff")
    p.add_argument(
        "--wait", type=float, default=1.0,
        help="Seconds to wait after click before re-capture (default %(default)s)",
    )
    args = p.parse_args()

    info = find_window(args.title, args.process or None)
    print(f"Window: hwnd=0x{info.hwnd:x} {info.title!r}")

    if args.no_verify:
        click(info.hwnd, args.x, args.y, mode=args.mode)
        print(f"Sent {args.mode} click at ({args.x}, {args.y}).")
        return 0

    out_dir = Path("screenshots")
    out_dir.mkdir(exist_ok=True)

    before = grab(info.hwnd)
    cv2.imwrite(str(out_dir / "before_click.png"), before)

    click(info.hwnd, args.x, args.y, mode=args.mode)
    print(f"Sent {args.mode} click at ({args.x}, {args.y}). Waiting {args.wait}s...")
    time.sleep(args.wait)

    after = grab(info.hwnd)
    cv2.imwrite(str(out_dir / "after_click.png"), after)

    if before.shape != after.shape:
        print(f"Frame size changed: {before.shape} -> {after.shape}")
        return 0

    diff = np.abs(before.astype(np.int16) - after.astype(np.int16)).astype(np.uint8)
    mean_diff = float(diff.mean())
    max_diff = int(diff.max())
    changed_px = int((diff.sum(axis=2) > 30).sum())
    total_px = before.shape[0] * before.shape[1]
    print(
        f"Diff: mean_abs={mean_diff:.2f}  max={max_diff}  "
        f"changed_px={changed_px}/{total_px} ({100 * changed_px / total_px:.2f}%)"
    )
    if mean_diff < 1.0:
        print(
            "WARNING: almost no change — click likely not registered "
            "(or nothing visible changes for this target).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(_main())
