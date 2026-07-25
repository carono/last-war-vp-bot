"""Last War control panel — navigation GUI.

One place for the project's confirmed, no-click navigation tools (all driven by the
game's own xLua VM through a hijacked thread — see docs/skills/sniff.md §7 and
docs/research/xlua-state.md):

  * Scene switch (Домой / Мир) — tools/scene_change.py
      Мир   -> SceneUtils.ChangeToWorld()  (--fire)
      Домой -> SceneUtils.ChangeToCity()   (--to-city)
    (The C# SceneManager.ChangeScene route tears the view to black; this Lua path
    is the confirmed one.)

  * Coordinate jump (X, Y, server) — tools/goto_coord.py X Y [serverId]
      GoToUtil.GotoPos(Vector3(X*2+1,0,Y*2+1),105,nil,nil,serverId,nil)
    The server field defaults to the current server
    (DataCenter.WorldFavoDataManager.curServerId).

Run under Windows Python (needs psutil/tkinter and the il2cpp toolchain deps of
tools/lua_eval.py):

    C:\\Python312\\python.exe -m panel
    C:\\Python312\\python.exe panel\\__main__.py
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
WIN_PYTHON = r"C:\Python312\python.exe"
GAME_PORT = 17935
DEFAULT_SERVER = "935"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


# ---------------------------------------------------------------------------
# Game-state helpers
# ---------------------------------------------------------------------------
def connection_status() -> str:
    """Short human string describing the :17935 TCP state."""
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


def current_server() -> str:
    """Read the current world server id from the live game (blocking, best-effort).

    DataCenter.WorldFavoDataManager.curServerId is the viewed server (home = 935);
    falls back to DEFAULT_SERVER if the game is offline or the field is unavailable.
    """
    chunk = ('CS.UnityEngine.Debug.LogError("CURSRV="..tostring('
             '(DataCenter.WorldFavoDataManager and DataCenter.WorldFavoDataManager.curServerId) or '
             '(DataCenter.WarFlagDataManager and DataCenter.WarFlagDataManager.curServerId) or %s))'
             % DEFAULT_SERVER)
    try:
        out = subprocess.run(
            [WIN_PYTHON, os.path.join(TOOLS, "lua_eval.py"), "--marker", "CURSRV", chunk],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=55, creationflags=NO_WINDOW).stdout
        m = re.search(r"CURSRV=(\d+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return DEFAULT_SERVER


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
class Panel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Last War — навигация")
        self.geometry("720x520")
        self.minsize(600, 440)
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._busy = False
        self._build_ui()
        self._pump_log()
        self._refresh_status()
        self._load_current_server()

    # -- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Соединение :17935:").pack(side="left")
        self._status_var = tk.StringVar(value="проверяю…")
        self._status_lbl = ttk.Label(top, textvariable=self._status_var, foreground="#888")
        self._status_lbl.pack(side="left", padx=6)
        ttk.Button(top, text="↻", width=3, command=self._refresh_status).pack(side="right")

        nav = ttk.LabelFrame(self, text="Навигация", padding=8)
        nav.pack(fill="x", padx=8, pady=(0, 6))

        # -- sub-block: scene switch ----------------------------------------
        scene = ttk.LabelFrame(nav, text="Сцена", padding=6)
        scene.pack(fill="x", pady=(0, 6))
        ttk.Button(scene, text="\U0001F3E0  Домой",
                   command=lambda: self._nav_scene("--to-city", "Домой (ChangeToCity)")
                   ).pack(side="left", padx=4, ipadx=8, ipady=6)
        ttk.Button(scene, text="\U0001F30D  Мир",
                   command=lambda: self._nav_scene("--fire", "Мир (ChangeToWorld)")
                   ).pack(side="left", padx=4, ipadx=8, ipady=6)
        ttk.Label(scene, text="tools/scene_change.py — Lua SceneUtils, без кликов",
                  foreground="#888").pack(side="left", padx=10)

        # -- sub-block: coordinate jump -------------------------------------
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

    # -- status -------------------------------------------------------------
    def _refresh_status(self) -> None:
        def work() -> None:
            s = connection_status()
            ok = s.startswith("ESTABLISHED")
            self.after(0, lambda: (self._status_var.set(s),
                                   self._status_lbl.configure(foreground="#3c3" if ok else "#c33")))
        threading.Thread(target=work, daemon=True).start()

    def _load_current_server(self) -> None:
        self._log_put("[server] читаю текущий сервер…")

        def work() -> None:
            srv = current_server()
            self.after(0, lambda: (self._srv_var.set(srv),
                                   self._log_put(f"[server] текущий сервер: {srv}")))
        threading.Thread(target=work, daemon=True).start()

    # -- run guard ----------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy

    def _stream(self, argv: list[str], tag: str) -> None:
        """Run a tool under the Windows Python, streaming its output to the log (blocking)."""
        cmd = [WIN_PYTHON, *argv]
        self._log_put(f"[{tag}] запуск: {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                cwd=REPO, creationflags=NO_WINDOW)
            assert proc.stdout is not None
            for raw in proc.stdout:
                self._log_put(raw.rstrip())
            proc.wait()
            self._log_put(f"[{tag}] завершён rc={proc.returncode}")
        except Exception as exc:
            self._log_put(f"[{tag}] ошибка: {exc}")

    def _run_async(self, body) -> None:
        """Run `body()` (which may call self._stream) on a worker thread, guarding _busy."""
        if self._busy:
            self._log_put("[panel] занят — дождись завершения текущего действия")
            return
        self._set_busy(True)

        def work() -> None:
            try:
                body()
            finally:
                self.after(0, lambda: self._set_busy(False))
                self.after(600, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    # -- actions ------------------------------------------------------------
    def _nav_scene(self, flag: str, label: str) -> None:
        self._log_put(f"[scene] {label}")
        self._run_async(lambda: self._stream([os.path.join(TOOLS, "scene_change.py"), flag], "scene"))

    def _goto_coord(self) -> None:
        x, y, srv = self._x_var.get().strip(), self._y_var.get().strip(), self._srv_var.get().strip()
        if not (x.lstrip("-").isdigit() and y.lstrip("-").isdigit()):
            self._log_put("[coord] X и Y должны быть целыми числами")
            return
        srv = srv if srv.isdigit() else DEFAULT_SERVER

        def body() -> None:
            cur = current_server()
            if srv != cur:
                # Different server: GotoPos alone does NOT load a foreign world (it only tags the
                # request). Use the cross-server recipe — authorize + JumpToServerByServerId + close
                # UIMoveCity — then pan to (X,Y). tools/cross_server.py does all of that.
                self._log_put(f"[coord] другой сервер ({srv} != {cur}) — кросс-серверная загрузка + переход в ({x},{y})")
                self._stream([os.path.join(TOOLS, "cross_server.py"), srv, x, y], "coord")
            else:
                # Same server: a plain in-server camera jump is enough.
                self._log_put(f"[coord] тот же сервер ({srv}) — переход камерой в ({x},{y})")
                self._stream([os.path.join(TOOLS, "goto_coord.py"), x, y, srv], "coord")

        self._run_async(body)


def main() -> int:
    for tool in ("scene_change.py", "goto_coord.py", "lua_eval.py"):
        if not os.path.isfile(os.path.join(TOOLS, tool)):
            print(f"tool not found: tools/{tool}", file=sys.stderr)
    Panel().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
