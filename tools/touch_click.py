r"""Cursor-free synthetic tap via the Windows Touch Injection API.

Unlike SetCursorPos+mouse_event (which physically moves the mouse and steals it
from the user), InjectTouchInput emulates a touchscreen contact at absolute
screen coordinates without touching the real cursor. Last War is a mobile port,
so it should accept touch input. This lets the bot drive the game while the user
keeps using the PC.

    C:\Python312\python.exe tools\touch_click.py            # tap "Мир" (1713,1095)
    C:\Python312\python.exe tools\touch_click.py X Y

Fallback if touch is rejected: postmessage_click() (WM_LBUTTONDOWN/UP), also
cursor-free but delivered straight to the window.
"""
from __future__ import annotations

import ctypes as C
import sys
import time
from ctypes import wintypes

user32 = C.WinDLL("user32", use_last_error=True)

# --- Touch Injection constants ------------------------------------------------
TOUCH_FEEDBACK_DEFAULT = 0x1
TOUCH_FEEDBACK_INDIRECT = 0x2
TOUCH_FEEDBACK_NONE = 0x3

PT_TOUCH = 0x00000002

POINTER_FLAG_NONE = 0x00000000
POINTER_FLAG_NEW = 0x00000001
POINTER_FLAG_INRANGE = 0x00000002
POINTER_FLAG_INCONTACT = 0x00000004
POINTER_FLAG_DOWN = 0x00010000
POINTER_FLAG_UPDATE = 0x00020000
POINTER_FLAG_UP = 0x00040000

TOUCH_FLAG_NONE = 0x00000000
TOUCH_MASK_NONE = 0x00000000
TOUCH_MASK_CONTACTAREA = 0x00000001
TOUCH_MASK_ORIENTATION = 0x00000002
TOUCH_MASK_PRESSURE = 0x00000004


class POINT(C.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(C.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class POINTER_INFO(C.Structure):
    _fields_ = [
        ("pointerType", wintypes.DWORD),
        ("pointerId", wintypes.UINT),
        ("frameId", wintypes.UINT),
        ("pointerFlags", wintypes.DWORD),
        ("sourceDevice", wintypes.HANDLE),
        ("hwndTarget", wintypes.HWND),
        ("ptPixelLocation", POINT),
        ("ptHimetricLocation", POINT),
        ("ptPixelLocationRaw", POINT),
        ("ptHimetricLocationRaw", POINT),
        ("dwTime", wintypes.DWORD),
        ("historyCount", wintypes.UINT),
        ("InputData", C.c_int32),
        ("dwKeyStates", wintypes.DWORD),
        ("PerformanceCount", C.c_uint64),
        ("ButtonChangeType", C.c_int),
    ]


class POINTER_TOUCH_INFO(C.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("touchFlags", wintypes.DWORD),
        ("touchMask", wintypes.DWORD),
        ("rcContact", RECT),
        ("rcContactRaw", RECT),
        ("orientation", wintypes.UINT),
        ("pressure", wintypes.UINT),
    ]


user32.InitializeTouchInjection.argtypes = [wintypes.UINT, wintypes.DWORD]
user32.InitializeTouchInjection.restype = wintypes.BOOL
user32.InjectTouchInput.argtypes = [wintypes.UINT, C.POINTER(POINTER_TOUCH_INFO)]
user32.InjectTouchInput.restype = wintypes.BOOL

_INIT = False


def _ensure_init(max_count: int = 1) -> None:
    global _INIT
    if not _INIT:
        if not user32.InitializeTouchInjection(max_count, TOUCH_FEEDBACK_NONE):
            raise OSError(f"InitializeTouchInjection failed err={C.get_last_error()}")
        _INIT = True


def _make_contact(x: int, y: int, flags: int) -> POINTER_TOUCH_INFO:
    pti = POINTER_TOUCH_INFO()
    pti.pointerInfo.pointerType = PT_TOUCH
    pti.pointerInfo.pointerId = 0
    pti.pointerInfo.pointerFlags = flags
    pti.pointerInfo.ptPixelLocation.x = x
    pti.pointerInfo.ptPixelLocation.y = y
    pti.touchFlags = TOUCH_FLAG_NONE
    pti.touchMask = TOUCH_MASK_CONTACTAREA | TOUCH_MASK_PRESSURE
    pti.pressure = 1024
    pti.rcContact.left = x - 2
    pti.rcContact.top = y - 2
    pti.rcContact.right = x + 2
    pti.rcContact.bottom = y + 2
    return pti


def touch_tap(x: int, y: int, hwnd: int | None = None, hold: float = 0.06,
              restore_cursor: bool = True) -> bool:
    """Tap at absolute screen (x, y) via a touch contact.

    The touch itself does not move the cursor, but Windows promotes it to a mouse
    event for the (foreground, Unity/legacy) game window, which WARPS the OS
    cursor to the tap point. With restore_cursor=True the cursor is snapped back
    to where it was, so the net displacement is zero (only a brief flicker) and
    the user keeps their pointer position.
    """
    _ensure_init()
    origin = _cursor_pos() if restore_cursor else None
    down = _make_contact(x, y, POINTER_FLAG_DOWN | POINTER_FLAG_INRANGE
                         | POINTER_FLAG_INCONTACT)
    if not user32.InjectTouchInput(1, C.byref(down)):
        raise OSError(f"InjectTouchInput(down) failed err={C.get_last_error()}")
    time.sleep(hold)
    up = _make_contact(x, y, POINTER_FLAG_UP)
    if not user32.InjectTouchInput(1, C.byref(up)):
        raise OSError(f"InjectTouchInput(up) failed err={C.get_last_error()}")
    if origin is not None:
        # let the game consume the promoted-mouse warp, then restore twice
        for _ in range(3):
            time.sleep(0.03)
            user32.SetCursorPos(origin[0], origin[1])
    return True


def touch_drag(x0: int, y0: int, x1: int, y1: int, steps: int = 20,
               hold: float = 0.02, restore_cursor: bool = True) -> bool:
    """Drag a single touch contact from (x0, y0) to (x1, y1) in absolute screen
    coordinates. Used to pan the map: a swipe on the world map makes the client
    stream ``world.get.block`` tile queries, the decisive WORLD marker.

    ``steps`` intermediate moves keep the gesture smooth enough that the game reads
    it as a pan rather than a flick+release; ``restore_cursor`` snaps the OS cursor
    back afterwards (Windows warps it to the contact on the promoted mouse event).
    """
    _ensure_init()
    origin = _cursor_pos() if restore_cursor else None
    down = _make_contact(x0, y0, POINTER_FLAG_DOWN | POINTER_FLAG_INRANGE
                         | POINTER_FLAG_INCONTACT)
    if not user32.InjectTouchInput(1, C.byref(down)):
        raise OSError(f"InjectTouchInput(down) failed err={C.get_last_error()}")
    time.sleep(hold)
    for i in range(1, steps + 1):
        x = int(x0 + (x1 - x0) * i / steps)
        y = int(y0 + (y1 - y0) * i / steps)
        move = _make_contact(x, y, POINTER_FLAG_UPDATE | POINTER_FLAG_INRANGE
                             | POINTER_FLAG_INCONTACT)
        if not user32.InjectTouchInput(1, C.byref(move)):
            raise OSError(f"InjectTouchInput(move) failed err={C.get_last_error()}")
        time.sleep(hold)
    up = _make_contact(x1, y1, POINTER_FLAG_UP)
    if not user32.InjectTouchInput(1, C.byref(up)):
        raise OSError(f"InjectTouchInput(up) failed err={C.get_last_error()}")
    if origin is not None:
        for _ in range(3):
            time.sleep(0.03)
            user32.SetCursorPos(origin[0], origin[1])
    return True


# --- fallback: PostMessage (also cursor-free) ---------------------------------
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MK_LBUTTON = 0x0001


def postmessage_click(hwnd: int, x: int, y: int, screen: bool = True) -> bool:
    """Deliver a click straight to hwnd via PostMessage — no cursor movement.
    x,y are screen coords by default; converted to the window's client space."""
    import win32gui
    import win32api
    import win32con
    if screen:
        cx, cy = win32gui.ScreenToClient(hwnd, (x, y))
    else:
        cx, cy = x, y
    lparam = win32api.MAKELONG(cx, cy)
    win32api.PostMessage(hwnd, WM_MOUSEMOVE, 0, lparam)
    win32api.PostMessage(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.05)
    win32api.PostMessage(hwnd, WM_LBUTTONUP, 0, lparam)
    return True


def _cursor_pos():
    pt = POINT()
    user32.GetCursorPos(C.byref(pt))
    return pt.x, pt.y


def main() -> int:
    x = int(sys.argv[1]) if len(sys.argv) > 1 else 1713
    y = int(sys.argv[2]) if len(sys.argv) > 2 else 1095
    before = _cursor_pos()
    print(f"cursor before: {before}")
    touch_tap(x, y)
    time.sleep(0.2)
    after = _cursor_pos()
    print(f"cursor after:  {after}  (moved={before != after})")
    print(f"touch tap injected at ({x},{y})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
