"""Last War control panel — navigation + secret-task monitoring (daemon-backed).

Actions run through the warm Lua daemon (tools/lua_daemon.py) so every button dispatches
in ~0.1 s instead of spawning a fresh process that re-resolves the il2cpp hijack (~5 s). The
panel auto-starts the daemon if it is not already running. In-game recipes live in
tools/lua_actions.py (shared with the standalone scripts, so nothing drifts).

Blocks:
  * Навигация — Домой / Мир (SceneUtils.ChangeToCity / ChangeToWorld) and a coordinate jump
    (X / Y / Сервер). Same server -> in-server camera jump; a different server -> the
    cross-server load recipe. The server field defaults to the current server
    (DataCenter.WorldFavoDataManager.curServerId).
  * Секретные задания — a checkbox that runs the passive capture (tools/secret_task_capture.py
    or secret_mission_capture.py) in the background and streams findings into the log.

Any coordinate printed in the log — canonical `@[X,Y]` / `@[X,Y|server]` (tools/coords.py) or a
free-form `X:1 Y:2` / `(1,2)` / `1/2` / `координаты 1 2` — becomes a clickable link that jumps
there.

Run under Windows Python (needs psutil/tkinter; the daemon needs the il2cpp deps of
tools/lua_eval.py; the capture needs scapy/npcap):

    C:\\Python312\\python.exe -m panel
"""
from __future__ import annotations

import os
import queue
import re
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
import coords           # noqa: E402

WIN_PYTHON = r"C:\Python312\python.exe"
GAME_PORT = 17935
DEFAULT_SERVER = str(lua_actions.HOME_SERVER)
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW
DETACHED = 0x00000008         # DETACHED_PROCESS
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Game lifecycle (paths derived from %LOCALAPPDATA%, no hardcoded username)
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
GAME_DIR = os.path.join(_LOCALAPPDATA, "FunFly", "Last War-Survival Game")
LAUNCHER = os.path.join(GAME_DIR, "LastWarLauncher.exe")
GAME_EXE = "LastWar.exe"

CAPTURE_SCRIPTS = {
    "Секретные задания": "secret_task_capture.py",
    "Операция Призрак": "secret_mission_capture.py",
}
RALLY_OUT_REL = os.path.join("results", "rally_log.jsonl")
RALLY_OUT = os.path.join(REPO, RALLY_OUT_REL)


def connection_status() -> str:
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
        self.geometry("760x600")
        self.minsize(640, 500)
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._busy = False
        self._coord_seq = 0
        self._mon_proc = None
        self._rally_proc = None
        self._client = lua_client.DaemonClient()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
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

        game = ttk.LabelFrame(self, text="Игра", padding=8)
        game.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Button(game, text="▶  Запустить игру",
                   command=self._launch_game).pack(side="left", padx=4, ipady=3)
        ttk.Button(game, text="⟳  Перезапустить игру",
                   command=self._restart_game).pack(side="left", padx=4, ipady=3)
        ttk.Label(game, text="LastWarLauncher.exe", foreground="#888").pack(side="left", padx=10)

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

        sec = ttk.LabelFrame(self, text="Секретные задания", padding=8)
        sec.pack(fill="x", padx=8, pady=(0, 6))
        self._mon_kind = tk.StringVar(value="Секретные задания")
        ttk.Combobox(sec, textvariable=self._mon_kind, state="readonly", width=20,
                     values=list(CAPTURE_SCRIPTS)).pack(side="left", padx=(0, 8))
        self._mon_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sec, text="Мониторинг", variable=self._mon_var,
                        command=self._toggle_monitor).pack(side="left")
        ttk.Label(sec, text="пассивный сниф — панорамируй карту, чтобы шли тайлы",
                  foreground="#888").pack(side="left", padx=10)

        rally = ttk.LabelFrame(self, text="Ралли", padding=8)
        rally.pack(fill="x", padx=8, pady=(0, 6))
        self._rally_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(rally, text="Монитор ралли", variable=self._rally_var,
                        command=self._toggle_rally).pack(side="left")
        ttk.Label(rally, text=f"push.alliance.march.* → лог + {RALLY_OUT_REL}",
                  foreground="#888").pack(side="left", padx=10)

        logframe = ttk.LabelFrame(self, text="Лог (координаты кликабельны)", padding=4)
        logframe.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self._log = scrolledtext.ScrolledText(logframe, wrap="word", height=16,
                                              font=("Consolas", 9), state="disabled",
                                              background="#111", foreground="#ddd")
        self._log.pack(fill="both", expand=True)
        self._log.tag_config("coordlink", foreground="#5cf", underline=True)

    # -- logging ------------------------------------------------------------
    def _log_put(self, line: str) -> None:
        self._log_q.put(line)

    def _pump_log(self) -> None:
        try:
            while True:
                self._insert_line(self._log_q.get_nowait() + "\n")
        except queue.Empty:
            pass
        self.after(120, self._pump_log)

    def _insert_line(self, text: str) -> None:
        """Insert a log line, turning any coordinate token into a clickable link."""
        clean = _ANSI.sub("", text)
        self._log.configure(state="normal")
        pos = 0
        for (s, e, x, y, srv) in coords.parse(clean):
            if s > pos:
                self._log.insert("end", clean[pos:s])
            tag = f"c{self._coord_seq}"
            self._coord_seq += 1
            self._log.insert("end", clean[s:e], ("coordlink", tag))
            self._log.tag_bind(tag, "<Button-1>",
                               lambda ev, x=x, y=y, srv=srv: self._on_coord_click(x, y, srv))
            self._log.tag_bind(tag, "<Enter>", lambda ev: self._log.configure(cursor="hand2"))
            self._log.tag_bind(tag, "<Leave>", lambda ev: self._log.configure(cursor=""))
            pos = e
        if pos < len(clean):
            self._log.insert("end", clean[pos:])
        self._log.see("end")
        self._log.configure(state="disabled")

    # -- daemon lifecycle ---------------------------------------------------
    def _startup(self) -> None:
        if self._rally_var.get():           # rally monitor is on by default
            self._start_rally()
        self._ensure_daemon()
        self._load_current_server()

    def _ensure_daemon(self) -> bool:
        if lua_client.is_running():
            self.after(0, lambda: self._set_daemon("warm", True))
            return True
        self._log_put("[daemon] не запущен — стартую tools/lua_daemon.py…")
        self.after(0, lambda: self._set_daemon("старт…", None))
        try:
            subprocess.Popen(
                [WIN_PYTHON, os.path.join(TOOLS, "lua_daemon.py")],
                cwd=REPO, creationflags=NO_WINDOW | DETACHED,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except Exception as exc:
            self._log_put(f"[daemon] не удалось запустить: {exc}")
            self.after(0, lambda: self._set_daemon("ошибка", False))
            return False
        for _ in range(60):
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
        try:
            for ln in self._client.run(lua_actions.current_server(), marker="ACT", settle=0.5):
                if "curserver=" in ln:
                    return ln.split("curserver=")[1].split()[0]
        except Exception as exc:
            self._log_put(f"[server] ошибка чтения: {exc}")
        return DEFAULT_SERVER

    # -- secret-task monitoring ---------------------------------------------
    def _toggle_monitor(self) -> None:
        if self._mon_var.get():
            self._start_monitor()
        else:
            self._stop_monitor()

    def _start_monitor(self) -> None:
        if self._mon_proc is not None:
            return
        script = CAPTURE_SCRIPTS.get(self._mon_kind.get(), "secret_task_capture.py")
        self._log_put(f"[secret] старт мониторинга: {script}")
        try:
            self._mon_proc = subprocess.Popen(
                [WIN_PYTHON, "-u", os.path.join(TOOLS, script), "--all-tcp"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=REPO,
                creationflags=NO_WINDOW)
        except Exception as exc:
            self._log_put(f"[secret] ошибка запуска: {exc}")
            self._mon_proc = None
            self._mon_var.set(False)
            return
        threading.Thread(target=self._mon_reader, args=(self._mon_proc,), daemon=True).start()

    def _mon_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                self._log_put(f"[secret] {raw.rstrip()}")
        except Exception:
            pass
        if self._mon_proc is proc:      # ended on its own, not via _stop_monitor
            self._log_put("[secret] поток мониторинга завершён")
            self._mon_proc = None
            self.after(0, lambda: self._mon_var.set(False))

    def _stop_monitor(self) -> None:
        proc, self._mon_proc = self._mon_proc, None
        if proc is not None:
            self._log_put("[secret] стоп мониторинга")
            try:
                proc.terminate()
            except Exception:
                pass

    # -- rally monitoring ---------------------------------------------------
    def _toggle_rally(self) -> None:
        if self._rally_var.get():
            self._start_rally()
        else:
            self._stop_rally()

    def _start_rally(self) -> None:
        if self._rally_proc is not None:
            return
        try:
            os.makedirs(os.path.dirname(RALLY_OUT), exist_ok=True)
        except Exception:
            pass
        self._log_put(f"[rally] старт мониторинга ралли → {RALLY_OUT_REL}")
        try:
            self._rally_proc = subprocess.Popen(
                [WIN_PYTHON, "-u", os.path.join(TOOLS, "rally_monitor.py"),
                 "--all-tcp", "--out", RALLY_OUT],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=REPO,
                creationflags=NO_WINDOW)
        except Exception as exc:
            self._log_put(f"[rally] ошибка запуска: {exc}")
            self._rally_proc = None
            self._rally_var.set(False)
            return
        threading.Thread(target=self._rally_reader, args=(self._rally_proc,), daemon=True).start()

    def _rally_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                self._log_put(f"[rally] {raw.rstrip()}")
        except Exception:
            pass
        if self._rally_proc is proc:      # ended on its own, not via _stop_rally
            self._log_put("[rally] поток мониторинга завершён")
            self._rally_proc = None
            self.after(0, lambda: self._rally_var.set(False))

    def _stop_rally(self) -> None:
        proc, self._rally_proc = self._rally_proc, None
        if proc is not None:
            self._log_put("[rally] стоп мониторинга")
            try:
                proc.terminate()
            except Exception:
                pass

    # -- jump routing (shared by the entry button and clickable coords) -----
    def _jump(self, x: int, y: int, server) -> None:
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
                target = str(server) if server is not None else cur
                if target != cur:
                    self._log_put(f"[coord] другой сервер ({target} != {cur}) — кросс-загрузка + переход в ({x},{y})")
                    chunk, settle = lua_actions.cross_jump(int(target), x=x, y=y), 1.6
                else:
                    self._log_put(f"[coord] переход камерой в ({x},{y}) [сервер {target}]")
                    chunk, settle = lua_actions.goto_pos(x, y, int(target)), 1.0
                for ln in self._client.run(chunk, marker="ACT", settle=settle):
                    self._log_put(f"[coord] {ln}")
                self._log_put("[coord] готово")
            except Exception as exc:
                self._log_put(f"[coord] ошибка: {exc}")
            finally:
                self._busy = False
                self.after(400, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    def _on_coord_click(self, x: int, y: int, server) -> None:
        self._log_put(f"[coord] клик → ({x},{y})" + (f" сервер {server}" if server is not None else ""))
        self._jump(x, y, server)

    def _goto_coord(self) -> None:
        x, y, srv = self._x_var.get().strip(), self._y_var.get().strip(), self._srv_var.get().strip()
        if not (x.lstrip("-").isdigit() and y.lstrip("-").isdigit()):
            self._log_put("[coord] X и Y должны быть целыми числами")
            return
        srv = srv if srv.isdigit() else DEFAULT_SERVER
        self._jump(int(x), int(y), int(srv))

    # -- generic action -----------------------------------------------------
    def _act(self, chunk: str, tag: str, label: str, settle: float = 1.2) -> None:
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
                for ln in self._client.run(chunk, marker="ACT", settle=settle):
                    self._log_put(f"[{tag}] {ln}")
                self._log_put(f"[{tag}] готово")
            except Exception as exc:
                self._log_put(f"[{tag}] ошибка: {exc}")
            finally:
                self._busy = False
                self.after(400, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    # -- game lifecycle -----------------------------------------------------
    def _start_launcher(self) -> bool:
        if not os.path.isfile(LAUNCHER):
            self._log_put(f"[game] лаунчер не найден: {LAUNCHER}")
            return False
        try:
            subprocess.Popen([LAUNCHER], cwd=GAME_DIR, creationflags=NO_WINDOW | DETACHED,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL)
            self._log_put("[game] лаунчер запущен")
            return True
        except Exception as exc:
            self._log_put(f"[game] ошибка запуска: {exc}")
            return False

    def _launch_game(self) -> None:
        self._log_put("[game] запуск LastWarLauncher.exe…")
        threading.Thread(target=self._start_launcher, daemon=True).start()

    def _restart_game(self) -> None:
        def work() -> None:
            self._log_put(f"[game] убиваю {GAME_EXE}…")
            try:
                r = subprocess.run(["taskkill", "/F", "/IM", GAME_EXE],
                                   capture_output=True, text=True, creationflags=NO_WINDOW)
                self._log_put(f"[game] taskkill: {(r.stdout or r.stderr).strip() or 'ok'}")
            except Exception as exc:
                self._log_put(f"[game] ошибка kill: {exc}")
            time.sleep(1.0)
            if self._start_launcher():
                self._log_put("[game] перезапуск: жди загрузки игры; daemon сам переинициализируется "
                              "при следующем действии")
        threading.Thread(target=work, daemon=True).start()

    def _on_close(self) -> None:
        self._stop_monitor()
        self._stop_rally()
        self.destroy()


def main() -> int:
    for tool in ("lua_daemon.py", "lua_client.py", "lua_actions.py", "coords.py"):
        if not os.path.isfile(os.path.join(TOOLS, tool)):
            print(f"tool not found: tools/{tool}", file=sys.stderr)
    Panel().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
