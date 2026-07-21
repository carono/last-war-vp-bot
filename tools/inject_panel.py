"""Unified control panel for Last War map navigation and protocol injects.

One place that gathers every working technique from the tools/ directory:

  * Navigation (real scene switch, via the game's own il2cpp code) — invokes
    SceneManager.ChangeScene(SceneID.World / SceneID.City) through
    il2cpp_runtime_invoke on a hijacked thread (tools/call_go_to_world.py).
    This is the game's own scene switcher, so it flips BOTH the client view and
    the server state — no template matching, no mouse clicks. (The old path
    clicked an on-screen toggle button located by cv2 template matching; that is
    replaced by this in-process method.)

  * Injects (server-side commands) — spawns steal_via_socket.py to passively
    sniff the live _id counter and send a single protocol frame. Useful for
    actions whose effect lives on the server (resource collection, etc.).

Run under Windows Python (needs psutil/tkinter; navigation also needs the
il2cpp toolchain deps of call_go_to_world.py):

    C:\\Python312\\python.exe tools\\inject_panel.py
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
WIN_PYTHON = r"C:\Python312\python.exe"
GAME_PORT = 17935


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------
def connection_status() -> str:
    """Return a short human string describing the :17935 TCP state."""
    try:
        import psutil
    except Exception:
        return "psutil missing"
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.raddr and c.raddr.port == GAME_PORT and c.status == "ESTABLISHED":
                return f"ESTABLISHED {c.laddr.ip}:{c.laddr.port} -> {c.raddr.ip}:{c.raddr.port}"
    except Exception as exc:
        return f"probe error: {exc}"
    return "no :17935 ESTABLISHED (game offline?)"


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------
# Navigation actions invoke SceneManager.ChangeScene(SceneID) through the game's
# own il2cpp (tools/call_go_to_world.py --scene <s> --fire) — the real scene
# switch, view + server, no clicks.
NAV_ACTIONS = [
    {"label": "\U0001F30D  Мир", "scene": "world",
     "hint": "SceneManager.ChangeScene(SceneID.World) через il2cpp"},
    {"label": "\U0001F3E0  База", "scene": "city",
     "hint": "SceneManager.ChangeScene(SceneID.City) через il2cpp"},
]

# Inject actions call steal_via_socket.py DIRECTLY — a pure send-only test of
# the protocol function. No mouse clicks, no map pans, no swipes: the tool just
# passive-sniffs the live _id counter from natural traffic and injects the frame.
# (The old run_*_inject.py wrappers spammed clicks to force traffic — removed
# from the test path.) You may need to nudge the game yourself so an upstream
# _id appears within the 60 s window.
SERVER_ID = "935"
INJECT_ACTIONS = [
    {"label": "go.to.world", "cmd": "go.to.world", "prompts": []},
    {"label": "user.leave.world", "cmd": "user.leave.world", "prompts": []},
    {"label": "gather.collect.reward", "cmd": "gather.collect.reward",
     "prompts": [("--uuid-arr", "UUID марша(ей) через запятую")]},
    {"label": "building.production.collect", "cmd": "building.production.collect",
     "prompts": [("--uuid", "UUID здания")]},
]


class InjectPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Last War — панель инжектов и навигации")
        self.geometry("760x560")
        self.minsize(620, 460)
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._busy = False
        self._build_ui()
        self._pump_log()
        self._refresh_status()

    # -- UI construction ----------------------------------------------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Соединение :17935:").pack(side="left")
        self._status_var = tk.StringVar(value="проверяю…")
        self._status_lbl = ttk.Label(top, textvariable=self._status_var,
                                      foreground="#888")
        self._status_lbl.pack(side="left", padx=6)
        ttk.Button(top, text="↻", width=3,
                   command=self._refresh_status).pack(side="right")

        nav = ttk.LabelFrame(self, text="Навигация — смена сцены через il2cpp",
                             padding=8)
        nav.pack(fill="x", padx=8, pady=(0, 4))
        for act in NAV_ACTIONS:
            b = ttk.Button(nav, text=act["label"],
                           command=lambda a=act: self._run_nav(a))
            b.pack(side="left", padx=4, ipadx=8, ipady=6)
        ttk.Label(nav, text="SceneManager.ChangeScene(SceneID) — вид и сервер, без кликов",
                  foreground="#888").pack(side="left", padx=10)

        inj = ttk.LabelFrame(self, text="Инжекты — серверные команды (steal_via_socket.py)",
                             padding=8)
        inj.pack(fill="x", padx=8, pady=4)
        for act in INJECT_ACTIONS:
            b = ttk.Button(inj, text=act["label"],
                           command=lambda a=act: self._run_inject(a))
            b.pack(side="left", padx=4, ipady=4)

        logframe = ttk.LabelFrame(self, text="Лог", padding=4)
        logframe.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self._log = scrolledtext.ScrolledText(logframe, wrap="word", height=16,
                                              font=("Consolas", 9), state="disabled",
                                              background="#111", foreground="#ddd")
        self._log.pack(fill="both", expand=True)

    # -- logging ------------------------------------------------------------
    def _log_put(self, line: str) -> None:
        self._log_q.put(line)

    def _pump_log(self) -> None:
        try:
            while True:
                line = self._log_q.get_nowait()
                self._log.configure(state="normal")
                self._log.insert("end", line + "\n")
                self._log.see("end")
                self._log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(120, self._pump_log)

    # -- status -------------------------------------------------------------
    def _refresh_status(self) -> None:
        def work() -> None:
            s = connection_status()
            ok = s.startswith("ESTABLISHED")
            self.after(0, lambda: (self._status_var.set(s),
                                   self._status_lbl.configure(
                                       foreground="#3c3" if ok else "#c33")))
        threading.Thread(target=work, daemon=True).start()

    # -- run guards ---------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy

    # -- navigation (il2cpp scene switch) -----------------------------------
    def _run_nav(self, act: dict) -> None:
        if self._busy:
            self._log_put("[panel] занят — дождись завершения текущего действия")
            return
        self._set_busy(True)
        caller = os.path.join(TOOLS, "call_go_to_world.py")
        cmd = [WIN_PYTHON, caller, "--scene", act["scene"], "--fire"]
        self._log_put(f"[nav] {act['label'].strip()} — {act['hint']}")
        self._log_put(f"[nav] запуск: {' '.join(cmd)}")

        def work() -> None:
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    cwd=REPO, creationflags=0x08000000)  # CREATE_NO_WINDOW
                assert proc.stdout is not None
                for raw in proc.stdout:
                    self._log_put(raw.rstrip())
                proc.wait()
                self._log_put(f"[nav] {act['scene']} завершён rc={proc.returncode}")
            except Exception as exc:
                self._log_put(f"[nav] ошибка: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))
                self.after(600, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    # -- injects ------------------------------------------------------------
    def _run_inject(self, act: dict) -> None:
        if self._busy:
            self._log_put("[panel] занят — дождись завершения текущего действия")
            return
        extra: list[str] = []
        for flag, prompt in act["prompts"]:
            val = self._ask(prompt)
            if val is None:
                self._log_put(f"[inject] {act['label']} отменён")
                return
            extra += [flag, val.strip()]

        self._set_busy(True)
        steal = os.path.join(TOOLS, "steal_via_socket.py")
        cmd = [WIN_PYTHON, steal, "--sniff-and-inject", "--force",
               "--command", act["cmd"], "--server-id", SERVER_ID, *extra]
        self._log_put(f"[inject] запуск (без UI-кликов): {' '.join(cmd)}")

        def work() -> None:
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    cwd=REPO, creationflags=0x08000000)  # CREATE_NO_WINDOW
                assert proc.stdout is not None
                for raw in proc.stdout:
                    self._log_put(raw.rstrip())
                proc.wait()
                self._log_put(f"[inject] {act['cmd']} завершён rc={proc.returncode}")
            except Exception as exc:
                self._log_put(f"[inject] ошибка: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))
                self.after(600, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    def _ask(self, prompt: str):
        from tkinter import simpledialog
        return simpledialog.askstring("Параметр инжекта", prompt, parent=self)


def main() -> int:
    caller = os.path.join(TOOLS, "call_go_to_world.py")
    if not os.path.isfile(caller):
        print(f"navigation helper not found: {caller}", file=sys.stderr)
    InjectPanel().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
