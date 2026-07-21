"""Input primitives: cursor-free taps and screenshots.

Two building blocks the higher-level actions share, each delegating to the
proven implementation instead of re-writing it:

* :func:`touch_tap` — a synthetic touchscreen contact via the Windows Touch
  Injection API (``tools/touch_click.py``). Last War is a mobile port and accepts
  touch, so this drives the game without stealing the user's mouse.
* :func:`get_screenshot` — the client-area capture from the perception layer
  (``lastwar_bot.perception.capture.grab``), which uses ``PrintWindow`` with
  ``PW_RENDERFULLCONTENT`` so the Unity/DirectX surface isn't captured black.

Both are Windows-only at call time; imports are lazy so the module loads on any
platform.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from bot.core import process

if TYPE_CHECKING:  # numpy is a Windows-runtime dependency; keep imports lazy.
    import numpy as np


def focus_game(hwnd: int | None = None) -> bool:
    """Bring the game window to the foreground. Returns whether it is now focused.

    Windows promotes an injected touch to a mouse event only for the *foreground*
    window, so a tap silently misses unless the game is focused. When the bot runs
    unattended (e.g. driven from WSL) the game is usually in the background, and a
    bare ``SetForegroundWindow`` is refused by the foreground-lock unless the
    calling thread has recent input — so we first synthesise a stray ALT keypress
    to satisfy that eligibility check, then raise the window. No-op cost when the
    game is already frontmost.
    """
    import ctypes
    import win32con
    import win32gui

    if hwnd is None:
        hwnd = process.get_hwnd()
    if win32gui.GetForegroundWindow() == hwnd:
        return True
    user32 = ctypes.windll.user32
    # VK_MENU down/up: registers as user input so the foreground change is allowed.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 0x0002, 0)  # KEYEVENTF_KEYUP
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:  # foreground lock can still refuse; report via the check below
        pass
    return win32gui.GetForegroundWindow() == hwnd


def touch_tap(x: int, y: int, hold: float = 0.06, restore_cursor: bool = True,
              focus: bool = True) -> bool:
    """Tap at absolute screen ``(x, y)`` via a touch contact (no cursor move).

    ``restore_cursor`` snaps the OS cursor back after Windows promotes the touch
    to a mouse warp, so the user keeps their pointer position. ``focus`` first
    brings the game to the foreground (see :func:`focus_game`), without which the
    injected touch is delivered to whatever window is frontmost instead.
    """
    import touch_click  # tools/touch_click.py (on sys.path via bot/__init__)

    if focus:
        focus_game()

    return touch_click.touch_tap(x, y, hold=hold, restore_cursor=restore_cursor)


def swipe(x0: int, y0: int, x1: int, y1: int, steps: int = 20,
          restore_cursor: bool = True, focus: bool = True) -> bool:
    """Drag a touch contact across the screen (absolute coordinates).

    Panning the world map with this makes the client stream ``world.get.block``
    tile queries — the decisive, continuous WORLD marker the passive scene detector
    keys on. Focuses the game first (see :func:`focus_game`)."""
    import touch_click

    if focus:
        focus_game()

    return touch_click.touch_drag(x0, y0, x1, y1, steps=steps,
                                  restore_cursor=restore_cursor)


def get_screenshot(hwnd: int | None = None) -> np.ndarray:
    """Capture the game's client area as a BGR ``ndarray`` of shape (H, W, 3).

    Finds the window automatically when ``hwnd`` is omitted.
    """
    from lastwar_bot.perception.capture import grab

    if hwnd is None:
        hwnd = process.get_hwnd()
    return grab(hwnd)


def client_size(hwnd: int | None = None) -> tuple[int, int]:
    """Return the game's client-area ``(width, height)`` in pixels."""
    from lastwar_bot.perception.capture import get_client_size

    if hwnd is None:
        hwnd = process.get_hwnd()
    return get_client_size(hwnd)


def window_origin(hwnd: int | None = None) -> tuple[int, int]:
    """Return the screen ``(left, top)`` of the window's client area.

    Template matches are in client coordinates; touches are in absolute screen
    coordinates. This offset converts between the two.
    """
    import win32gui

    if hwnd is None:
        hwnd = process.get_hwnd()
    # ClientToScreen maps the client-area origin (0, 0) to absolute screen space,
    # correctly accounting for borders and the title bar.
    return win32gui.ClientToScreen(hwnd, (0, 0))


__all__ = ["touch_tap", "swipe", "focus_game", "get_screenshot", "client_size",
           "window_origin"]
