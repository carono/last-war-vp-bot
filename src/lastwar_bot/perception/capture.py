"""Capture the client area of a window by title / process (Windows-only).

Default backend: GDI `PrintWindow` with the `PW_RENDERFULLCONTENT` flag (2).
On Windows 10+ this works for most DirectX applications without bringing
the window to the foreground. If a specific game still gives a black
frame, a Windows Graphics Capture (`windows-capture`) backend will be
added as a fallback.

CLI:
    python -m lastwar_bot.perception.capture --out screenshot.png
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(slots=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process_name: str


class WindowNotFoundError(LookupError):
    """No matching window found."""


def find_window(title_substring: str, process_name: str | None = None) -> WindowInfo:
    """Find a visible top-level window matching title and (optionally) process.

    The title check is a case-insensitive substring match. If `process_name`
    is given, the owning process's executable name must also match
    (case-insensitive, exact filename).
    """
    if sys.platform != "win32":
        raise RuntimeError("Window capture is Windows-only")

    import psutil
    import win32gui
    import win32process

    needle = title_substring.lower()
    proc_needle = process_name.lower() if process_name else None
    matches: list[WindowInfo] = []

    def _enum_cb(hwnd: int, _ctx) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title or needle not in title.lower():
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            pname = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        if proc_needle and pname.lower() != proc_needle:
            return
        matches.append(WindowInfo(hwnd=hwnd, title=title, pid=pid, process_name=pname))

    win32gui.EnumWindows(_enum_cb, None)

    if not matches:
        suffix = f" from process {process_name!r}" if process_name else ""
        raise WindowNotFoundError(
            f"No window with title containing {title_substring!r}{suffix}"
        )

    if len(matches) > 1:
        matches.sort(key=lambda m: _window_area(m.hwnd), reverse=True)
    return matches[0]


def _window_area(hwnd: int) -> int:
    import win32gui

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return max(0, right - left) * max(0, bottom - top)


def grab(hwnd: int) -> np.ndarray:
    """Capture the client area of `hwnd`. Returns a BGR ndarray of shape (H, W, 3)."""
    import ctypes

    import win32gui
    import win32ui

    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Empty client area: {width}x{height}")

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    mem_dc = src_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src_dc, width, height)
    mem_dc.SelectObject(bmp)

    # PW_RENDERFULLCONTENT = 2 — required for DirectX/UWP content on Win10+.
    # Some pywin32 builds don't export PrintWindow, so we call user32 directly.
    print_window = ctypes.windll.user32.PrintWindow
    print_window.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    print_window.restype = ctypes.c_bool
    print_window(hwnd, mem_dc.GetSafeHdc(), 2)

    raw = bmp.GetBitmapBits(True)
    img_bgra = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 4))
    img_bgr = np.ascontiguousarray(img_bgra[:, :, :3])

    win32gui.DeleteObject(bmp.GetHandle())
    mem_dc.DeleteDC()
    src_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    return img_bgr


def _main() -> int:
    import argparse

    import cv2

    parser = argparse.ArgumentParser(description="Capture a window screenshot to PNG.")
    parser.add_argument(
        "--title",
        default="Last War-Survival Game",
        help="Window title substring (default: %(default)r)",
    )
    parser.add_argument(
        "--process",
        default="LastWar.exe",
        help="Process name filter; pass an empty string to disable (default: %(default)r)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("screenshots/last.png"),
        help="Output PNG path (default: %(default)s)",
    )
    args = parser.parse_args()

    proc_filter = args.process if args.process else None
    try:
        info = find_window(args.title, proc_filter)
    except WindowNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"Window found: hwnd=0x{info.hwnd:x} pid={info.pid} "
        f"process={info.process_name} title={info.title!r}"
    )

    img = grab(info.hwnd)
    height, width = img.shape[:2]
    mean = float(img.mean())
    print(f"Captured: {width}x{height} px, mean pixel value = {mean:.1f}")

    if mean < 1.0:
        print(
            "WARNING: the image looks black. For DirectX games this means GDI "
            "PrintWindow failed — a Windows Graphics Capture (windows-capture) "
            "backend is required.",
            file=sys.stderr,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), img)
    print(f"Saved: {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
