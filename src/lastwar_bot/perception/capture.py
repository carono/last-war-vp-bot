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

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Which window is the game — one answer for the whole repo, and an environment
# variable rather than a literal (`tools/lib/game_paths.py`). tools/lib is not an
# installed package, so the path is wired up the way script_engine does it.
_LIB = Path(__file__).resolve().parents[3] / "tools" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import game_paths  # noqa: E402

#: Where a window search says what it had to do to find the client. Plain `logging`, so
#: it lands in the debug log of whoever is running (the panel configures the tree) and
#: costs nothing at all when nobody is listening — this file is imported by tools that
#: have no panel around them.
_log = logging.getLogger(__name__)

# Minimum client-area size at which SIFT-based UI detection reliably works.
# Below this, icons rasterise too small for SIFT to extract enough keypoints.
MIN_CLIENT_WIDTH = 1638
MIN_CLIENT_HEIGHT = 1026
# Comfortable resize target used when the window is below the minimum.
DEFAULT_CLIENT_WIDTH = 1700
DEFAULT_CLIENT_HEIGHT = 1080


@dataclass(slots=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process_name: str


class WindowNotFoundError(LookupError):
    """No matching window found."""


def find_window(title_substring: str | None = None,
                process_name: str | None = None) -> WindowInfo:
    """Find a visible top-level window matching title and (optionally) process.

    The title check is a case-insensitive substring match. If `process_name`
    is given, the owning process's executable name must also match
    (case-insensitive, exact filename).

    **Left unsaid, both mean the game** — `game_paths.window_titles()` and
    `game_paths.game_exe()`, so `find_window()` with no arguments is the call every
    caller in this repo actually wants, and no caller has to repeat the pair. Pass
    `process_name=""` to search by title alone.

    **THE TITLE IS NOT A CONTRACT (#1320).** It is a string a build chooses, and a
    client update is free to change it — at which point a search pinned to one literal
    reports «no client» about a client that is plainly on screen, and every reading in
    the panel goes with it. So, unsaid, several titles are tried (the build's own name
    out of the launcher's manifest, then the one the client has always used), and if not
    one of them matches, **the game's own process is asked instead**: its largest visible
    window IS the client, whatever it has decided to call itself. That last step warns on
    the way past — it is a working answer AND a thing somebody should know about, because
    the title it found is what belongs in `LW_WINDOW_TITLE`.
    """
    if title_substring is None:
        wanted = list(game_paths.window_titles())
    else:
        wanted = [title_substring]
    if process_name is None:
        process_name = game_paths.game_exe()

    if sys.platform != "win32":
        raise RuntimeError("Window capture is Windows-only")

    for needle in wanted:
        found = _windows_matching(needle, process_name)
        if found:
            return _largest(found)

    # Nothing answered to any name we know. A window of the game's own process is a
    # better answer than none — and a silent one would hide the very drift that made
    # this branch necessary.
    if process_name:
        found = _windows_matching("", process_name)
        if found:
            best = _largest(found)
            _log.warning(
                "the game's window is titled %r, which matches none of %s; "
                "found it by its process (%s) instead - put that title in "
                "LW_WINDOW_TITLE to silence this",
                best.title, wanted, process_name)
            return best

    suffix = f" from process {process_name!r}" if process_name else ""
    raise WindowNotFoundError(
        f"No window with a title among {wanted}{suffix}"
    )


def _windows_matching(needle: str, process_name: str) -> list[WindowInfo]:
    """Every visible top-level window whose title contains `needle` — `""` means any.

    A window with no title at all is never a match: the client keeps a hidden 1×1
    helper window of its own, and «any window of that process» has to mean a window a
    person could be looking at.
    """
    import psutil
    import win32gui
    import win32process

    lowered = needle.lower()
    proc_needle = process_name.lower() if process_name else None
    matches: list[WindowInfo] = []

    def _enum_cb(hwnd: int, _ctx) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title or lowered not in title.lower():
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
    return matches


def _largest(matches: list[WindowInfo]) -> WindowInfo:
    """The biggest of several matches — the client, rather than a helper beside it."""
    if len(matches) > 1:
        matches = sorted(matches, key=lambda m: _window_area(m.hwnd), reverse=True)
    return matches[0]


def _window_area(hwnd: int) -> int:
    import win32gui

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return max(0, right - left) * max(0, bottom - top)


@dataclass(slots=True)
class ResizeResult:
    resized: bool
    before: tuple[int, int]
    after: tuple[int, int]
    target: tuple[int, int] | None  # None when no resize was needed


def get_client_size(hwnd: int) -> tuple[int, int]:
    """Return the (width, height) of the window's client area."""
    if sys.platform != "win32":
        raise RuntimeError("Window operations are Windows-only")
    import win32gui

    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return right - left, bottom - top


def ensure_client_size(
    hwnd: int,
    *,
    min_width: int = MIN_CLIENT_WIDTH,
    min_height: int = MIN_CLIENT_HEIGHT,
    target_width: int = DEFAULT_CLIENT_WIDTH,
    target_height: int = DEFAULT_CLIENT_HEIGHT,
) -> ResizeResult:
    """Resize the window so its client area is at least (min_width, min_height).

    No-op when already large enough. Otherwise the window keeps its
    top-left position and is grown to (target_width, target_height)
    client size. Useful for guaranteeing the SIFT detector has enough
    pixels to work with before starting a session.
    """
    if sys.platform != "win32":
        raise RuntimeError("Window operations are Windows-only")
    import win32gui

    before = get_client_size(hwnd)
    if before[0] >= min_width and before[1] >= min_height:
        return ResizeResult(resized=False, before=before, after=before, target=None)

    # Compute the non-client (border + title bar) overhead so the new
    # client area matches our target.
    win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(hwnd)
    border_w = (win_right - win_left) - before[0]
    border_h = (win_bottom - win_top) - before[1]

    new_window_w = target_width + border_w
    new_window_h = target_height + border_h
    win32gui.MoveWindow(hwnd, win_left, win_top, new_window_w, new_window_h, True)

    after = get_client_size(hwnd)
    return ResizeResult(resized=True, before=before, after=after, target=(target_width, target_height))


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

    # PW_CLIENTONLY (0x1) | PW_RENDERFULLCONTENT (0x2) — render only the
    # client area (skip the OS title bar / borders) and ask DWM for the
    # composed contents so DirectX/UWP windows aren't black.
    # Without PW_CLIENTONLY, the bitmap is window-sized starting at the
    # window top-left, so the top ~30 rows are the Windows title bar and
    # everything below is shifted down — every click derived from a
    # SIFT match ends up offset by the title-bar height.
    # Some pywin32 builds don't export PrintWindow; call user32 directly.
    print_window = ctypes.windll.user32.PrintWindow
    print_window.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    print_window.restype = ctypes.c_bool
    print_window(hwnd, mem_dc.GetSafeHdc(), 3)

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
        default=game_paths.window_title(),
        help="Window title substring (default: %(default)r)",
    )
    parser.add_argument(
        "--process",
        default=game_paths.game_exe(),
        help="Process name filter; pass an empty string to disable (default: %(default)r)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("screenshots/last.png"),
        help="Output PNG path (default: %(default)s)",
    )
    args = parser.parse_args()

    # Straight through: an empty --process is «title alone», which find_window reads
    # as such. Mapping it to None would ask for the default and filter after all.
    try:
        info = find_window(args.title, args.process)
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
