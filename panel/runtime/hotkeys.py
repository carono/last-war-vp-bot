"""The keyboard macros: 1..4 send a squad, CapsLock repeats the last march (#1283).

The panel listens for five keys while the GAME's window is in front, and each one plays
a scenario. That is the whole of it — the abilities live in
`src/lastwar_bot/actions/march_selected_squad.md` and `march_repeat_last.md`, and this
module knows nothing about marches, targets or squads beyond the number it passes.

WHY A LOW-LEVEL HOOK AND NOT `RegisterHotKey`. A registered hotkey is taken away from
whatever is in front, system-wide, for as long as the panel runs: the person could no
longer type `1` anywhere on the machine. `WH_KEYBOARD_LL` sees the press first and
decides, per press, whether to pass it on — so:

* **1 2 3 4 pass through untouched.** They are not swallowed, ever. The game does
  nothing with a digit outside a text box, and inside one (the in-game chat) the digit
  must still be typed. The macro fires anyway and the scenario refuses in a line of the
  log — «no target is chosen» — because it is only meaningful with the squad screen
  open, and asking the game about that would mean a round trip inside the hook, which
  Windows gives about a quarter of a second before it drops the hook entirely.
* **CapsLock IS swallowed**, and only while the game is in front. Otherwise every
  repeat would flip the keyboard into capitals — the one side effect that cannot be
  lived with. The cost is that CapsLock does not toggle while the game has focus; the
  in-game chat is the only place that is noticeable, and the key is not one people type
  with.

The hook runs on a thread of its own with its own message pump, because that is what
`SetWindowsHookEx` requires; the callback does nothing but drop a number in a queue,
and a worker thread plays the scenario. Nothing here touches Tk.

NOT WINDOWS, or the hook refused: `start()` answers False, says so once in the log, and
the panel goes on without macros.
"""
from __future__ import annotations

import ctypes
import queue
import sys
import threading

from . import paths as _paths       # noqa: F401 — puts tools/lib on sys.path

_paths.ensure()

#: The scenario each key plays. Hard-coded on purpose (#1283 asked for exactly this and
#: no settings): the ability is a recipe, and the key is a way of starting it.
SEND_ACTION = "march_selected_squad"
REPEAT_ACTION = "march_repeat_last"

#: The tag every line of this lands under in the panel's log.
TAG = "macro"

#: Virtual-key codes. The digit row and the numeric keypad both count — a person with
#: a full keyboard reaches for whichever is under their hand.
_VK_SQUAD = {0x31: 1, 0x32: 2, 0x33: 3, 0x34: 4,      # '1'..'4'
             0x61: 1, 0x62: 2, 0x63: 3, 0x64: 4}      # numpad 1..4
_VK_CAPITAL = 0x14

_WH_KEYBOARD_LL = 13
_WM_KEYDOWN = 0x0100
_WM_SYSKEYDOWN = 0x0104
_WM_QUIT = 0x0012


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", ctypes.c_uint32),
                ("scanCode", ctypes.c_uint32),
                ("flags", ctypes.c_uint32),
                ("time", ctypes.c_uint32),
                ("dwExtraInfo", ctypes.c_void_p)]


def _foreground_title() -> str:
    """The title of the window the person is typing into, '' when it cannot be read."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value or ""
    except Exception:                     # noqa: BLE001 — a hook must never raise
        return ""


class HotkeyListener:
    """Five keys, one thread, and a scenario per press.

    ``resolve`` is asked, at press time, which :class:`~panel.runtime.host.PanelRuntime`
    the key belongs to — the panel may have several profiles open, and the answer is
    whichever one is on screen. It may answer ``None``, which is «not now».
    """

    def __init__(self, resolve, *, title: str | None = None) -> None:
        self._resolve = resolve
        if title is None:
            import game_paths                # noqa: PLC0415 — bare name, see paths.py
            title = game_paths.window_title()
        self._title = (title or "").strip().casefold()
        self._hook = None
        self._thread_id = 0
        self._proc = None                 # the callback, kept alive by hand
        self._queue: "queue.Queue[int | None]" = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._running = False

    # -- what the keys mean -------------------------------------------------
    def game_in_front(self) -> bool:
        """Is the game the window the person is typing into?

        Title rather than process id: one `GetWindowTextW` against a `QueryFullProcess
        ImageNameW` behind an `OpenProcess`, and this runs inside a hook where Windows
        counts the milliseconds. A second client belonging to another profile lives in
        its own Windows session and cannot be the foreground window of this desktop, so
        the title is enough to tell «the game» from «everything else».
        """
        if not self._title:
            return False
        return self._title in _foreground_title().casefold()

    def _swallow(self, vk: int) -> bool:
        """Whether this key is taken away from the game — CapsLock only, see the module."""
        return vk == _VK_CAPITAL

    # -- the hook -----------------------------------------------------------
    def start(self) -> bool:
        """Install the hook. False when this machine has none to install."""
        if self._running:
            return True
        if not sys.platform.startswith("win"):
            return False
        self._running = True
        ready = threading.Event()
        ok: list[bool] = []
        pump = threading.Thread(target=self._pump, args=(ready, ok),
                                name="panel-hotkeys", daemon=True)
        worker = threading.Thread(target=self._work, name="panel-hotkeys-play",
                                  daemon=True)
        pump.start()
        worker.start()
        self._threads = [pump, worker]
        ready.wait(3.0)
        if not ok:
            self._running = False
            return False
        return True

    def stop(self) -> None:
        """Take the hook down and let both threads end."""
        if not self._running:
            return
        self._running = False
        try:
            if self._thread_id:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
        except Exception:                 # noqa: BLE001 — shutting down
            pass
        self._queue.put(None)

    def _pump(self, ready: threading.Event, ok: list) -> None:
        """The hook's own thread: install, then run a message loop until asked to stop.

        `SetWindowsHookEx` delivers to the thread that installed it, and only while that
        thread is pumping messages — a hook installed from a thread that then goes quiet
        simply never fires.
        """
        try:
            user32 = ctypes.windll.user32
            proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int,
                                       ctypes.c_uint, ctypes.POINTER(_KBDLLHOOKSTRUCT))
            self._proc = proto(self._callback)
            self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            self._hook = user32.SetWindowsHookExW(_WH_KEYBOARD_LL, self._proc, None, 0)
            if not self._hook:
                return
            ok.append(True)
        except Exception:                 # noqa: BLE001 — no macros, never a dead panel
            return
        finally:
            ready.set()
        try:
            import ctypes.wintypes as wt             # noqa: PLC0415 — Windows only
            msg = wt.MSG()
            while self._running and ctypes.windll.user32.GetMessageW(
                    ctypes.byref(msg), None, 0, 0) > 0:
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:                 # noqa: BLE001
            pass
        finally:
            try:
                if self._hook:
                    ctypes.windll.user32.UnhookWindowsHookEx(self._hook)
            except Exception:             # noqa: BLE001
                pass
            self._hook = None

    def _callback(self, code, wparam, lparam):
        """Windows calls this for EVERY key on the machine — so it does almost nothing.

        A press that belongs to the macros is queued and the queue is left to a worker;
        anything else is passed straight on. There is a hard budget here
        (`LowLevelHooksTimeout`, a quarter of a second by default) after which Windows
        removes the hook without saying so, which is why nothing in this function talks
        to the game, to Tk or to a log file.
        """
        swallow = False
        try:
            if code == 0 and wparam in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                vk = int(lparam[0].vkCode)
                if (vk in _VK_SQUAD or vk == _VK_CAPITAL) and self.game_in_front():
                    self._queue.put(vk)
                    swallow = self._swallow(vk)
        except Exception:                 # noqa: BLE001 — never break the keyboard
            swallow = False
        if swallow:
            return 1
        return ctypes.windll.user32.CallNextHookEx(None, code, wparam, lparam)

    # -- the worker ---------------------------------------------------------
    def _work(self) -> None:
        """Play the scenario a queued key names. Off the hook's thread, on purpose."""
        while True:
            vk = self._queue.get()
            if vk is None or not self._running:
                return
            try:
                self._press(vk)
            except Exception:             # noqa: BLE001 — one bad press, not the panel
                rt = self._resolve()
                if rt is not None:
                    rt.dbg("hotkeys").error("macro press failed", exc_info=True)

    def _press(self, vk: int) -> None:
        """One key, one scenario, and a line in the log whatever happens."""
        rt = self._resolve()
        if rt is None:
            return
        if vk == _VK_CAPITAL:
            rt.say(TAG, "log.macro.repeat")
            rt.play_async(REPEAT_ACTION, tag=TAG)
            return
        squad = _VK_SQUAD[vk]
        rt.say(TAG, "log.macro.send", squad=squad)
        rt.play_async(SEND_ACTION, {"squad": squad}, tag=TAG)
