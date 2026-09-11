r"""A strip of the panel's buttons, drawn OVER the game's own window (#2768).

    C:\Python312\python.exe tools\game_overlay.py --profile main --url http://127.0.0.1:9761 --token …

WHAT IT IS. A window of our own — a small always-on-top bar — that follows the client's
window around the desktop, carries one button per ability and, when the button is
pressed, asks the PANEL to play that scenario over its ordinary web door. Nothing more.
It is a front-end the way the phone is a front-end: it presses what the runtime already
presses and holds no gate, no Lua and no game step of its own (`CLAUDE.md`, «Everything
is a scenario — the panel only plays them»).

WHY A SEPARATE PROCESS, AND WHY NOT IN THE GAME. Two constraints decide the whole shape:

* **The anti-cheat.** ACE kills a client whose process has been written into — a hook, an
  injected renderer, a foreign thread started in private memory
  (`docs/research/dll-injection-vs-ace.md`). So nothing here goes near the game process:
  this is an ordinary top-level window of an ordinary process, positioned over another
  program's window the way any screen ruler or chat overlay is. The client is never told
  it exists.
* **The desktop.** A window can only be drawn by a process that has one — a session with
  a window station and a desktop. That is the same wall #2767 hit from the other side
  (the keyboard hook), and the answer is the same: the helper runs in the interactive
  session the client lives in, started by the panel that is already there.

WHOSE CLIENT. The window is found by title among the VISIBLE windows of this session
(`game_paths.window_titles()`), and windows of another Windows session are not
enumerable from here at all — so an overlay started by one profile's panel can only ever
attach to that profile's own client, which is the isolation rule holding by construction
rather than by a check (`CLAUDE.md`, «A profile is a whole panel of its own»).

IT MUST NOT COST THE GAME ITS INPUT. The client takes only foreground input
(`pydirectinput`, and the panel's own macros ride on that), so an overlay that stole the
foreground every time a thumb landed on it would break the very thing it sits on top of.
Two things prevent it: the window carries `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`, so a
click on a button is delivered without the window ever being activated, and the bar is
small and hugs one edge instead of covering the scene. It hides itself the moment the
game is minimised or something else comes to the front, so it is never a lid over
another program.

NOTHING IS ASKED IN THE BACKGROUND. The panel is polled only while a press this overlay
made is still running, and not at all otherwise (`CLAUDE.md`, «Read once, then LISTEN»).
The one clock is the position follower, which reads the game window's rectangle from the
window manager and asks the game and the panel nothing.

NOT ONE WORD OF IT IS WRITTEN HERE. The labels come from `/api/i18n` — the panel's own
locale table, in the panel's own language — and the name on a button is the SCENARIO's
own title off `/api/actions`, so a recipe renamed in its `# ru:` line is renamed on the
bar with no edit here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import game_paths                                                # noqa: E402

#: The installation this helper belongs to — `tools/` is one level down from it.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The scenarios the bar offers, in order. ONE for the trial (#2768) — the point of this
#: first pass is that the window holds and that the press really plays. Each row is the
#: scenario's own name; its title comes from `/api/actions`, so nothing is spelled twice.
BUTTONS = ("collect_base_resources",)

#: How often the bar catches up with the game window — its position, its size, whether it
#: is minimised and whether it is still the window in front. Cheap: two calls into the
#: window manager, no game and no panel.
FOLLOW_MS = 200

#: How often the panel is asked how a press of OURS is getting on, and for how long. Only
#: while one is in flight; a bar nobody has pressed asks nothing at all.
WATCH_SEC = 1.5
WATCH_MAX_SEC = 900.0

#: How long a finished press keeps its answer on the bar before it goes back to idle.
KEEP_SEC = 30.0

#: The gap between the bar and the client's own edge, in pixels.
MARGIN = 12

#: How solid the bar is. Not fully opaque: it sits over somebody's game.
ALPHA = 0.88

#: Windows constants, spelled here rather than importing win32con — this helper starts
#: on a desktop and must not fail to draw because a package is missing.
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


# -- the panel's door ---------------------------------------------------------
class Door:
    """The panel's web API, from a helper standing on the same machine.

    The same routes the phone uses and the same token: this is a front-end, and a
    front-end that had a private way in would be a second panel.
    """

    def __init__(self, url: str, token: str, profile: str, timeout: float = 10.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.profile = profile
        self.timeout = float(timeout)

    def get(self, path: str, **query) -> dict:
        tail = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in query.items() if v != "")
        address = f"{self.url}{path}" + (f"?{tail}" if tail else "")
        return self._ask(urllib.request.Request(address, method="GET"))

    def post(self, path: str, body: dict) -> dict:
        payload = dict(body)
        payload.setdefault("profile", self.profile)
        blob = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(f"{self.url}{path}", data=blob, method="POST")
        request.add_header("Content-Type", "application/json")
        return self._ask(request)

    def _ask(self, request) -> dict:
        if self.token:
            request.add_header("X-Panel-Token", self.token)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as answer:
                data = json.loads(answer.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return {"error": "unreachable", "detail": str(exc)}
        return data if isinstance(data, dict) else {}


class Words:
    """The panel's locale table, fetched once. A key with no word is the key itself."""

    def __init__(self, table: dict | None = None) -> None:
        self.table = dict(table or {})

    def t(self, key: str, **fmt) -> str:
        text = self.table.get(key)
        if text is None:
            return key
        for name, value in fmt.items():
            text = text.replace("{%s}" % name, str(value))
        return text


# -- the client's window ------------------------------------------------------
def _user32():
    import ctypes

    return ctypes.windll.user32


def find_client(titles=None) -> int:
    """The hwnd of the game's window on THIS desktop, or 0.

    By title, among the visible top-level windows: another Windows session's windows are
    not enumerable from here, so the answer can only ever be this session's client.
    """
    import ctypes

    wanted = tuple(t.lower() for t in (titles or game_paths.window_titles()))
    user32 = _user32()
    found = []

    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _param):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        text = buf.value.strip().lower()
        if text and any(text == want or want in text for want in wanted):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(proto(visit), None)
    return int(found[0]) if found else 0


def window_rect(hwnd: int) -> "tuple | None":
    """``(left, top, right, bottom)`` of a window, or ``None`` when it is gone."""
    import ctypes

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    if not _user32().GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


# -- the bar ------------------------------------------------------------------
class Overlay:
    """The bar itself: a Tk window that follows the client's and presses scenarios."""

    def __init__(self, door: Door, words: Words, labels=None, anchor: str = "right") -> None:
        import tkinter as tk

        self.door = door
        self.words = words
        # WHAT EACH BUTTON IS CALLED — the SCENARIOS' own titles, keyed by name. Never
        # confused with the window titles `find_client` matches on: they were one
        # attribute for an hour, and the bar then looked for a window called
        # «collect_base_resources» and hid itself for ever without a word (#2768).
        self.labels = labels or {}
        self.anchor = anchor
        self.hwnd_game = 0
        self._had_window = False            # so the first answer either way is said once
        self.watching = None                # the scenario a press of ours is running
        self.said_at = 0.0
        self._buttons = {}

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", ALPHA)
        self.root.configure(bg="#10141c")
        self.frame = tk.Frame(self.root, bg="#10141c", padx=8, pady=8)
        self.frame.pack()

        for name in BUTTONS:
            button = tk.Button(
                self.frame, text=self._title(name), bg="#1f6feb", fg="#ffffff",
                activebackground="#388bfd", activeforeground="#ffffff",
                relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
                command=(lambda n=name: self.press(n)))
            button.pack(fill="x", pady=(0, 6))
            self._buttons[name] = button

        self.status = tk.Label(self.frame, text=self.words.t("overlay.idle"),
                               bg="#10141c", fg="#9aa7b6", anchor="w",
                               font=("Segoe UI", 8))
        self.status.pack(fill="x")
        self.hide_button = tk.Button(
            self.frame, text=self.words.t("overlay.hide"), bg="#232a36", fg="#9aa7b6",
            relief="flat", bd=0, padx=6, pady=2, cursor="hand2", command=self.quit)
        self.hide_button.pack(fill="x", pady=(6, 0))

    # -- what a button is called -------------------------------------------
    def _title(self, name: str) -> str:
        """The SCENARIO's own title, off the panel — never a word written here."""
        return self.labels.get(name) or name

    # -- the press ----------------------------------------------------------
    def press(self, name: str) -> None:
        if self.watching:
            return
        self.watching = name
        self._say("overlay.running", tone="#d29922")
        self._enable(False)
        threading.Thread(target=self._run, args=(name,), daemon=True).start()

    def _run(self, name: str) -> None:
        """Ask the panel to play it, then watch until it is over. Off the Tk thread."""
        mark = self.door.get("/api/log", profile=self.door.profile).get("next", 0)
        answer = self.door.post("/api/actions/run", {"name": name})
        if answer.get("error"):
            self._finish("overlay.unreachable", "#f85149")
            return
        if not answer.get("ok"):
            # `busy` is the panel's honest «something else is driving this client» — the
            # one answer a press from outside must never override.
            self._finish("overlay.busy" if answer.get("busy") else "overlay.refused",
                         "#f85149")
            return
        deadline = time.monotonic() + WATCH_MAX_SEC
        started = False
        while time.monotonic() < deadline:
            time.sleep(WATCH_SEC)
            state = self.door.get("/api/state", profile=self.door.profile)
            if state.get("error"):
                continue
            activity = state.get("activity") or {}
            running = str(activity.get("name") or "")
            if running == name:
                started = True
                continue
            if started or not running:
                break
        self._finish_with_log(mark)

    def _finish_with_log(self, mark: int) -> None:
        """Say how it ended in the PANEL's own words — the last line the run wrote.

        The log line is already a sentence in the panel's language by the time it gets
        here, which is why it is shown as it is rather than mapped to a key: the reason a
        harvest was refused is the scenario's own and this overlay must not invent a
        second wording for it.
        """
        rows = self.door.get("/api/log", since=mark, profile=self.door.profile)
        lines = [r for r in (rows.get("lines") or [])
                 if str(r.get("tag") or "") in ("action", "error")]
        bad = [r for r in lines if str(r.get("sev") or "") in ("error", "warn")]
        if bad:
            self._finish(text=str(bad[-1].get("text") or ""), tone="#f85149")
            return
        if lines:
            self._finish(text=str(lines[-1].get("text") or ""), tone="#3fb950")
            return
        self._finish("overlay.done", "#3fb950")

    def _finish(self, key: str = "", tone: str = "#9aa7b6", text: str = "") -> None:
        def done() -> None:
            self.watching = None
            self._enable(True)
            self._say(key, tone=tone, text=text)
        self.root.after(0, done)

    def _enable(self, on: bool) -> None:
        for button in self._buttons.values():
            button.configure(state=("normal" if on else "disabled"))

    def _say(self, key: str = "", tone: str = "#9aa7b6", text: str = "") -> None:
        said = text or (self.words.t(key) if key else "")
        self.status.configure(text=said[:60], fg=tone)
        self.said_at = time.monotonic()

    # -- following the client ------------------------------------------------
    def _exstyle(self) -> None:
        """`WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`: a click here never takes the foreground.

        That is the whole reason the game keeps working underneath — it takes foreground
        input only, so an overlay that activated itself on every press would be pressing
        buttons into a client that had just lost focus.
        """
        import ctypes

        hwnd = self.root.winfo_id()
        parent = _user32().GetParent(ctypes.c_void_p(hwnd))
        hwnd = int(parent) if parent else int(hwnd)
        self.hwnd_self = hwnd
        user32 = _user32()
        style = user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
        user32.SetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE,
                              style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

    def follow(self) -> None:
        """One tick of the position clock: where the client is, and whether to be seen."""
        import ctypes

        user32 = _user32()
        if not self.hwnd_game or not user32.IsWindow(ctypes.c_void_p(self.hwnd_game)):
            self.hwnd_game = find_client()
        # A BAR THAT CANNOT FIND THE CLIENT SAYS SO ONCE, on stdout, which the panel
        # streams into its log. Hiding silently for ever is exactly what an hour of #2768
        # was spent on: the window it was looking for had the wrong name and nothing
        # anywhere said a word about it.
        if bool(self.hwnd_game) is not self._had_window:
            self._had_window = bool(self.hwnd_game)
            print("game window found" if self.hwnd_game else "no game window on this desktop",
                  flush=True)
        rect = window_rect(self.hwnd_game) if self.hwnd_game else None
        front = int(user32.GetForegroundWindow() or 0)
        minimised = bool(self.hwnd_game and user32.IsIconic(ctypes.c_void_p(self.hwnd_game)))
        mine = front in (self.hwnd_game, getattr(self, "hwnd_self", 0))
        if rect is None or minimised or not mine:
            # Never a lid over another program: the bar belongs to the game's window and
            # goes away with it.
            self.root.withdraw()
        else:
            self._place(rect)
        if self.said_at and time.monotonic() - self.said_at > KEEP_SEC and not self.watching:
            self._say("overlay.idle")
            self.said_at = 0.0
        self.root.after(FOLLOW_MS, self.follow)

    def _place(self, rect) -> None:
        import ctypes

        left, top, right, _bottom = rect
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        x = (right - width - MARGIN) if self.anchor == "right" else (left + MARGIN)
        y = top + MARGIN
        self.root.geometry(f"+{int(x)}+{int(y)}")
        if not self.root.winfo_viewable():
            self.root.deiconify()
        # Re-asserted every tick without activating: a client that was just brought to
        # the front would otherwise be drawn over the bar.
        _user32().SetWindowPos(ctypes.c_void_p(getattr(self, "hwnd_self", 0)),
                               ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                               SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def quit(self) -> None:
        try:
            self.root.destroy()
        except Exception:                  # noqa: BLE001 — it is on its way out
            pass

    def run(self) -> None:
        self.root.deiconify()
        self.root.update_idletasks()
        self._exstyle()
        self.root.withdraw()
        self.follow()
        self.root.mainloop()


def titles_of(door: Door, names) -> dict:
    """Each scenario's own title, in the panel's language, off `/api/actions`."""
    answer = door.get("/api/actions", profile=door.profile)
    table = {}
    for row in answer.get("actions") or []:
        name = str(row.get("name") or "")
        if name in names:
            table[name] = str(row.get("title") or row.get("text") or name)
    return table


def door_from_disk() -> tuple:
    """``(url, token)`` off the machine's own `service.json`, for a helper told neither.

    THE TOKEN IS NOT PUT ON A COMMAND LINE. A process list is readable by anything in the
    session, and the panel writes every child's command down in `children-<pid>.json` —
    so the door's secret would end up in both. The helper stands in the same installation
    as the panel, so it reads the machine's own service settings instead, which is where
    the service itself reads them from.
    """
    config = os.path.join(REPO, "service.json")
    try:
        with open(config, encoding="utf-8") as fh:
            values = json.load(fh) or {}
    except (OSError, ValueError):
        return "", ""
    port = str(values.get("port") or "").strip()
    if not port:
        return "", ""
    scheme = "https" if str(values.get("certfile") or "").strip() else "http"
    return f"{scheme}://127.0.0.1:{port}", str(values.get("token") or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default="", help="which account's panel to press")
    ap.add_argument("--url", default="", help="the panel's web address, e.g. http://127.0.0.1:9761")
    ap.add_argument("--token", default="", help="that door's token")
    ap.add_argument("--anchor", default="right", choices=("left", "right"),
                    help="which edge of the client's window the bar hugs")
    args = ap.parse_args(argv)

    url = args.url or os.environ.get("LW_PANEL_URL") or ""
    token = args.token or os.environ.get("LW_PANEL_TOKEN") or ""
    if not url or not token:
        found_url, found_token = door_from_disk()
        url = url or found_url
        token = token or found_token
    if not url:
        print("no panel address: pass --url", file=sys.stderr)
        return 2
    door = Door(url, token, args.profile)
    words = Words(door.get("/api/i18n", profile=args.profile).get("words") or {})
    overlay = Overlay(door, words, labels=titles_of(door, set(BUTTONS)),
                      anchor=args.anchor)
    overlay.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
