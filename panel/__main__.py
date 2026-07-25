"""Last War control panel — navigation GUI (daemon-backed).

Actions run through the warm Lua daemon (tools/lua_daemon.py) so every button dispatches
in ~0.1 s instead of spawning a fresh process that re-resolves the il2cpp hijack (~5 s).
The panel auto-starts the daemon if it is not already running. The in-game recipes live in
tools/lua_actions.py (shared with the standalone scripts, so nothing drifts).

Navigation group:
  * Сцена — Домой / Мир  (SceneUtils.ChangeToCity / ChangeToWorld)
  * Переход по координатам — X / Y / Сервер. Same server -> in-server camera jump; a
    different server -> the cross-server load recipe (authorize + JumpToServerByServerId +
    close UIMoveCity), because GotoPos alone does not load a foreign world. The server field
    defaults to the current server (DataCenter.WorldFavoDataManager.curServerId).

Run under Windows Python (needs psutil/tkinter; the daemon needs the il2cpp deps of
tools/lua_eval.py):

    C:\\Python312\\python.exe -m panel
    C:\\Python312\\python.exe panel\\__main__.py
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
sys.path.insert(0, TOOLS)
import lua_client       # noqa: E402  (lightweight — no il2cpp deps)
import lua_actions      # noqa: E402

WIN_PYTHON = r"C:\Python312\python.exe"
GAME_PORT = 17935
DEFAULT_SERVER = str(lua_actions.HOME_SERVER)
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW
DETACHED = 0x00000008         # DETACHED_PROCESS


def connection_status() -> str:
    """Short human string describing the :17935 TCP state."""
    try:
        import psutil
    except Exception:
        return "psutil missing"
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.raddr and c.raddr.port == GAME_PORT and c.status == "ESTABLISHED":
                return f"ESTABLISHED -> {c.raddr.ip}:{c.raddr.port}"
    except Exception as exc:
        return f"probe error: {exc}"
    return "no :17935 ESTABLISHED (game offline?)"


class Panel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Last War — навигация")
        self.geometry("720x520")
        self.minsize(600, 440)
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._busy = False
        self._client = lua_client.DaemonClient()
        self._build_ui()
        self._pump_log()
        self._refresh_status()
        threading.Thread(target=self._startup, daemon=True).start()

    # -- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Игра:").pack(side="left")
        self._status_var = tk.StringVar(value="проверяю…")
        self._status_lbl = ttk.Label(top, textvariable=self._status_var, foreground="#888")
        self._status_lbl.pack(side="left", padx=6)
        ttk.Label(top, text="daemon:").pack(side="left", padx=(12, 0))
        self._daemon_var = tk.StringVar(value="…")
        self._daemon_lbl = ttk.Label(top, textvariable=self._daemon_var, foreground="#888")
        self._daemon_lbl.pack(side="left", padx=6)
        ttk.Button(top, text="↻", width=3, command=self._refresh_status).pack(side="right")

        nav = ttk.LabelFrame(self, text="Навигация", padding=8)
        nav.pack(fill="x", padx=8, pady=(0, 6))

        scene = ttk.LabelFrame(nav, text="Сцена", padding=6)
        scene.pack(fill="x", pady=(0, 6))
        ttk.Button(scene, text="\U0001F3E0  Домой",
                   command=lambda: self._act(lua_actions.scene_city(), "scene", "Домой")
                   ).pack(side="left", padx=4, ipadx=8, ipady=6)
        ttk.Button(scene, text="\U0001F30D  Мир",
                   command=lambda: self._act(lua_actions.scene_world(), "scene", "Мир")
                   ).pack(side="left", padx=4, ipadx=8, ipady=6)
        ttk.Label(scene, text="SceneUtils.ChangeToCity / ChangeToWorld",
                  foreground="#888").pack(side="left", padx=10)

        coord = ttk.LabelFrame(nav, text="Переход по координатам", padding=6)
        coord.pack(fill="x")
        self._x_var = tk.StringVar()
        self._y_var = tk.StringVar()
        self._srv_var = tk.StringVar(value=DEFAULT_SERVER)
        ttk.Label(coord, text="X").pack(side="left")
        ttk.Entry(coord, textvariable=self._x_var, width=7).pack(side="left", padx=(2, 8))
        ttk.Label(coord, text="Y").pack(side="left")
        ttk.Entry(coord, textvariable=self._y_var, width=7).pack(side="left", padx=(2, 8))
        ttk.Label(coord, text="Сервер").pack(side="left")
        ttk.Entry(coord, textvariable=self._srv_var, width=7).pack(side="left", padx=(2, 8))
        ttk.Button(coord, text="Перейти", command=self._goto_coord).pack(side="left", padx=4, ipady=2)
        ttk.Button(coord, text="↻ сервер", command=self._load_current_server).pack(side="left", padx=4)

        logframe = ttk.LabelFrame(self, text="Лог", padding=4)
        logframe.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self._log = scrolledtext.ScrolledText(logframe, wrap="word", height=14,
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

    # -- daemon lifecycle ---------------------------------------------------
    def _startup(self) -> None:
        self._ensure_daemon()
        self._load_current_server()

    def _ensure_daemon(self) -> bool:
        """Start the daemon if it is not already listening; wait until it is warm."""
        if lua_client.is_running():
            self.after(0, lambda: self._set_daemon("warm", True))
            return True
        self._log_put("[daemon] не запущен — стартую tools/lua_daemon.py…")
        self.after(0, lambda: self._set_daemon("старт…", None))
        try:
            subprocess.Popen(
                [WIN_PYTHON, os.path.join(TOOLS, "lua_daemon.py")],
                cwd=REPO, creationflags=NO_WINDOW | DETACHED,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL)
        except Exception as exc:
            self._log_put(f"[daemon] не удалось запустить: {exc}")
            self.after(0, lambda: self._set_daemon("ошибка", False))
            return False
        for _ in range(60):                     # up to ~30 s for il2cpp warm-up
            if lua_client.is_running():
                self._log_put("[daemon] готов (warm)")
                self.after(0, lambda: self._set_daemon("warm", True))
                return True
            time.sleep(0.5)
        self._log_put("[daemon] не поднялся за отведённое время")
        self.after(0, lambda: self._set_daemon("нет", False))
        return False

    def _set_daemon(self, text: str, ok) -> None:
        color = "#3c3" if ok else ("#888" if ok is None else "#c33")
        self._daemon_var.set(text)
        self._daemon_lbl.configure(foreground=color)

    # -- status -------------------------------------------------------------
    def _refresh_status(self) -> None:
        def work() -> None:
            s = connection_status()
            ok = s.startswith("ESTABLISHED")
            warm = lua_client.is_running()
            self.after(0, lambda: (
                self._status_var.set(s),
                self._status_lbl.configure(foreground="#3c3" if ok else "#c33"),
                self._set_daemon("warm" if warm else "нет", warm)))
        threading.Thread(target=work, daemon=True).start()

    def _load_current_server(self) -> None:
        def work() -> None:
            srv = self._current_server()
            self.after(0, lambda: (self._srv_var.set(srv),
                                   self._log_put(f"[server] текущий сервер: {srv}")))
        threading.Thread(target=work, daemon=True).start()

    def _current_server(self) -> str:
        """Read the viewed server id via the daemon; fall back to DEFAULT_SERVER."""
        try:
            for ln in self._client.run(lua_actions.current_server(), marker="ACT", settle=0.5):
                if "curserver=" in ln:
                    return ln.split("curserver=")[1].split()[0]
        except Exception as exc:
            self._log_put(f"[server] ошибка чтения: {exc}")
        return DEFAULT_SERVER

    # -- run guard ----------------------------------------------------------
    def _act(self, chunk: str, tag: str, label: str, settle: float = 1.2) -> None:
        """Dispatch a Lua chunk through the warm daemon on a worker thread."""
        if self._busy:
            self._log_put("[panel] занят — дождись завершения текущего действия")
            return
        self._busy = True
        self._log_put(f"[{tag}] {label}")

        def work() -> None:
            try:
                if not lua_client.is_running() and not self._ensure_daemon():
                    self._log_put(f"[{tag}] daemon недоступен")
                    return
                out = self._client.run(chunk, marker="ACT", settle=settle)
                for ln in out:
                    self._log_put(f"[{tag}] {ln}")
                self._log_put(f"[{tag}] готово")
            except Exception as exc:
                self._log_put(f"[{tag}] ошибка: {exc}")
            finally:
                self._busy = False
                self.after(400, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    # -- coordinate jump (routes by server) ---------------------------------
    def _goto_coord(self) -> None:
        x, y, srv = self._x_var.get().strip(), self._y_var.get().strip(), self._srv_var.get().strip()
        if not (x.lstrip("-").isdigit() and y.lstrip("-").isdigit()):
            self._log_put("[coord] X и Y должны быть целыми числами")
            return
        srv = srv if srv.isdigit() else DEFAULT_SERVER
        xi, yi, si = int(x), int(y), int(srv)
        if self._busy:
            self._log_put("[panel] занят — дождись завершения текущего действия")
            return
        self._busy = True

        def work() -> None:
            try:
                if not lua_client.is_running() and not self._ensure_daemon():
                    self._log_put("[coord] daemon недоступен")
                    return
                cur = self._current_server()
                if str(si) != cur:
                    self._log_put(f"[coord] другой сервер ({si} != {cur}) — кросс-загрузка + переход в ({xi},{yi})")
                    chunk, settle = lua_actions.cross_jump(si, x=xi, y=yi), 1.6
                else:
                    self._log_put(f"[coord] тот же сервер ({si}) — переход камерой в ({xi},{yi})")
                    chunk, settle = lua_actions.goto_pos(xi, yi, si), 1.0
                for ln in self._client.run(chunk, marker="ACT", settle=settle):
                    self._log_put(f"[coord] {ln}")
                self._log_put("[coord] готово")
            except Exception as exc:
                self._log_put(f"[coord] ошибка: {exc}")
            finally:
                self._busy = False
                self.after(400, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()


def main() -> int:
    for tool in ("lua_daemon.py", "lua_client.py", "lua_actions.py"):
        if not os.path.isfile(os.path.join(TOOLS, tool)):
            print(f"tool not found: tools/{tool}", file=sys.stderr)
    Panel().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
