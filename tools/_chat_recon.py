r"""Ad-hoc recon helper for the chat investigation (run with Windows Python).

    C:\Python312\python.exe tools\_chat_recon.py focus     # bring game to front
    C:\Python312\python.exe tools\_chat_recon.py shot NAME # focus + screenshot -> screenshots/NAME.png
    C:\Python312\python.exe tools\_chat_recon.py rect      # print window rect only
"""
from __future__ import annotations
import ctypes as C
import os
import sys
import time
from ctypes import wintypes

user32 = C.WinDLL("user32", use_last_error=True)
TITLE = "Last War"


def find_hwnd() -> int:
    found = []

    @C.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = C.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if TITLE.lower() in buf.value.lower() and user32.IsWindowVisible(hwnd):
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        raise SystemExit("Last War window not found")
    return found[0][0]


def rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, C.byref(r))
    return r.left, r.top, r.right, r.bottom


def focus(hwnd):
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    # AttachThreadInput trick to reliably steal foreground
    fg = user32.GetForegroundWindow()
    cur_t = user32.GetWindowThreadProcessId(fg, 0)
    tgt_t = user32.GetWindowThreadProcessId(hwnd, 0)
    user32.AttachThreadInput(cur_t, tgt_t, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur_t, tgt_t, False)
    time.sleep(0.4)


def shot(name):
    import mss
    hwnd = find_hwnd()
    focus(hwnd)
    l, t, r, b = rect(hwnd)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(here, "screenshots", name + ".png")
    with mss.mss() as sct:
        img = sct.grab({"left": l, "top": t, "width": r - l, "height": b - t})
        import mss.tools
        mss.tools.to_png(img.rgb, img.size, output=out)
    print(f"rect=({l},{t},{r},{b}) size=({r-l}x{b-t}) -> {out}")


def click(x, y):
    """Physical-cursor click at absolute screen coords (handles negative/left monitor)."""
    hwnd = find_hwnd()
    focus(hwnd)
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    print(f"clicked ({x},{y})")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "rect"
    if cmd == "click":
        click(sys.argv[2], sys.argv[3]); return
    hwnd = find_hwnd()
    if cmd == "rect":
        print("hwnd=%#x rect=%s" % (hwnd, rect(hwnd)))
    elif cmd == "focus":
        focus(hwnd)
        print("focused hwnd=%#x rect=%s" % (hwnd, rect(hwnd)))
    elif cmd == "shot":
        shot(sys.argv[2] if len(sys.argv) > 2 else "chat_recon")


if __name__ == "__main__":
    main()
