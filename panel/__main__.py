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

from . import __version__ as APP_VERSION
from . import i18n as i18nmod

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

# Capture options: a stable i18n key (combobox label) paired with its capture script.
# The selected script is resolved by combobox index, so the visible label can be
# translated freely without breaking the lookup.
CAPTURE_OPTIONS = [
    {"key": "capture.secret_tasks", "script": "secret_task_capture.py"},
    {"key": "capture.ghost_op", "script": "secret_mission_capture.py"},
]
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
        self._i18n = i18nmod.I18n()
        self._tr_widgets: list = []   # (widget, option, key, fmt) — retranslated in place
        self._tr_hooks: list = []     # callables run on every language change
        self.title(self._t("app.title"))
        self.geometry("760x600")
        self.minsize(640, 500)
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._busy = False
        self._coord_seq = 0
        self._mon_proc = None
        self._rally_proc = None
        self._client = lua_client.DaemonClient()
        self._build_menu()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_log()
        self._refresh_status()
        threading.Thread(target=self._startup, daemon=True).start()

    # -- i18n ---------------------------------------------------------------
    def _t(self, key: str, **fmt) -> str:
        return self._i18n.t(key, **fmt)

    def _tr(self, widget, key: str, option: str = "text", **fmt):
        """Set ``widget[option]`` from a locale key and remember it for retranslation."""
        widget.configure(**{option: self._t(key, **fmt)})
        self._tr_widgets.append((widget, option, key, fmt))
        return widget

    def _set_language(self, lang: str) -> None:
        if self._i18n.set_lang(lang):
            self._apply_language()

    def _apply_language(self) -> None:
        self.title(self._t("app.title"))
        for widget, option, key, fmt in self._tr_widgets:
            try:
                widget.configure(**{option: self._t(key, **fmt)})
            except tk.TclError:
                pass
        for hook in self._tr_hooks:
            hook()
        self._refresh_status()   # re-render translated daemon/status words

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        lang_menu = tk.Menu(menubar, tearoff=0)
        self._lang_var = getattr(self, "_lang_var", tk.StringVar())
        self._lang_var.set(self._i18n.lang)
        for lang in i18nmod.available_langs():
            lang_menu.add_radiobutton(
                label=i18nmod.LANG_NAMES.get(lang, lang), value=lang,
                variable=self._lang_var, command=lambda l=lang: self._set_language(l))

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=self._t("menu.help.about"), command=self._show_about)

        menubar.add_cascade(label=self._t("menu.language"), menu=lang_menu)
        menubar.add_cascade(label=self._t("menu.help"), menu=help_menu)
        self.config(menu=menubar)
        if self._build_menu not in self._tr_hooks:
            self._tr_hooks.append(self._build_menu)

    def _show_about(self) -> None:
        win = tk.Toplevel(self)
        win.title(self._t("about.title"))
        win.resizable(False, False)
        win.transient(self)
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=self._t("about.name"),
                  font=("", 12, "bold")).pack(anchor="w")
        ttk.Label(frm, text=self._t("about.version", version=APP_VERSION),
                  foreground="#888").pack(anchor="w", pady=(2, 8))
        ttk.Label(frm, text=self._t("about.description"), wraplength=360,
                  justify="left").pack(anchor="w")
        ttk.Button(frm, text=self._t("about.ok"),
                   command=win.destroy).pack(anchor="e", pady=(12, 0))
        win.grab_set()

    # -- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        main = ttk.Frame(nb)
        scenarios = ttk.Frame(nb)
        nb.add(main, text=self._t("tab.main"))
        nb.add(scenarios, text=self._t("tab.scenarios"))
        self._tr_hooks.append(lambda: (nb.tab(main, text=self._t("tab.main")),
                                       nb.tab(scenarios, text=self._t("tab.scenarios"))))
        self._tr(ttk.Label(scenarios, foreground="#888", padding=20),
                 "scenarios.placeholder").pack(expand=True)

        top = ttk.Frame(main, padding=8)
        top.pack(fill="x")
        self._tr(ttk.Label(top), "top.game").pack(side="left")
        self._status_var = tk.StringVar(value=self._t("status.checking"))
        self._status_lbl = ttk.Label(top, textvariable=self._status_var, foreground="#888")
        self._status_lbl.pack(side="left", padx=6)
        self._tr(ttk.Label(top), "top.daemon").pack(side="left", padx=(12, 0))
        self._daemon_var = tk.StringVar(value=self._t("daemon.pending"))
        self._daemon_lbl = ttk.Label(top, textvariable=self._daemon_var, foreground="#888")
        self._daemon_lbl.pack(side="left", padx=6)
        ttk.Button(top, text="↻", width=3, command=self._refresh_status).pack(side="right")

        game = self._tr(ttk.LabelFrame(main, padding=8), "game.frame")
        game.pack(fill="x", padx=8, pady=(0, 6))
        self._tr(ttk.Button(game, command=self._launch_game),
                 "game.launch").pack(side="left", padx=4, ipady=3)
        self._tr(ttk.Button(game, command=self._restart_game),
                 "game.restart").pack(side="left", padx=4, ipady=3)
        self._tr(ttk.Label(game, foreground="#888"),
                 "game.launcher_hint").pack(side="left", padx=10)

        nav = self._tr(ttk.LabelFrame(main, padding=8), "nav.frame")
        nav.pack(fill="x", padx=8, pady=(0, 6))

        scene = self._tr(ttk.LabelFrame(nav, padding=6), "nav.scene")
        scene.pack(fill="x", pady=(0, 6))
        self._tr(ttk.Button(scene,
                 command=lambda: self._act(lua_actions.scene_city(), "scene", "Домой")),
                 "nav.home").pack(side="left", padx=4, ipadx=8, ipady=6)
        self._tr(ttk.Button(scene,
                 command=lambda: self._act(lua_actions.scene_world(), "scene", "Мир")),
                 "nav.world").pack(side="left", padx=4, ipadx=8, ipady=6)
        self._tr(ttk.Label(scene, foreground="#888"),
                 "nav.scene_hint").pack(side="left", padx=10)

        coord = self._tr(ttk.LabelFrame(nav, padding=6), "coord.frame")
        coord.pack(fill="x")
        self._x_var = tk.StringVar()
        self._y_var = tk.StringVar()
        self._srv_var = tk.StringVar(value=DEFAULT_SERVER)
        self._tr(ttk.Label(coord), "coord.x").pack(side="left")
        ttk.Entry(coord, textvariable=self._x_var, width=7).pack(side="left", padx=(2, 8))
        self._tr(ttk.Label(coord), "coord.y").pack(side="left")
        ttk.Entry(coord, textvariable=self._y_var, width=7).pack(side="left", padx=(2, 8))
        self._tr(ttk.Label(coord), "coord.server").pack(side="left")
        ttk.Entry(coord, textvariable=self._srv_var, width=7).pack(side="left", padx=(2, 8))
        self._tr(ttk.Button(coord, command=self._goto_coord),
                 "coord.jump").pack(side="left", padx=4, ipady=2)
        self._tr(ttk.Button(coord, command=self._load_current_server),
                 "coord.reload_server").pack(side="left", padx=4)

        sec = self._tr(ttk.LabelFrame(main, padding=8), "secret.frame")
        sec.pack(fill="x", padx=8, pady=(0, 6))
        row1 = ttk.Frame(sec)
        row1.pack(fill="x")
        self._mon_combo = ttk.Combobox(row1, state="readonly", width=20,
                                       values=[self._t(o["key"]) for o in CAPTURE_OPTIONS])
        self._mon_combo.current(0)
        self._mon_combo.pack(side="left", padx=(0, 8))
        self._tr_hooks.append(self._retranslate_capture_combo)
        self._mon_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(row1, variable=self._mon_var, command=self._toggle_monitor),
                 "secret.monitoring").pack(side="left")
        self._tr(ttk.Label(row1, foreground="#888"), "secret.hint").pack(side="left", padx=10)
        # filters (applied live, panel-side, to task findings only)
        row2 = ttk.Frame(sec)
        row2.pack(fill="x", pady=(6, 0))
        self._tr(ttk.Label(row2), "secret.filters").pack(side="left")
        self._star_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(row2, variable=self._star_var),
                 "secret.stars_only").pack(side="left", padx=(6, 0))
        self._pending_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(row2, variable=self._pending_var),
                 "secret.pending_only").pack(side="left", padx=(6, 0))
        self._tr(ttk.Label(row2), "secret.level_from").pack(side="left", padx=(12, 2))
        self._lvl_from_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self._lvl_from_var, width=4).pack(side="left")
        self._tr(ttk.Label(row2), "secret.level_to").pack(side="left", padx=(6, 2))
        self._lvl_to_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self._lvl_to_var, width=4).pack(side="left")

        rally = self._tr(ttk.LabelFrame(main, padding=8), "rally.frame")
        rally.pack(fill="x", padx=8, pady=(0, 6))
        self._rally_var = tk.BooleanVar(value=True)
        self._tr(ttk.Checkbutton(rally, variable=self._rally_var, command=self._toggle_rally),
                 "rally.monitor").pack(side="left")
        self._tr(ttk.Label(rally, foreground="#888"),
                 "rally.hint", path=RALLY_OUT_REL).pack(side="left", padx=10)

        logframe = self._tr(ttk.LabelFrame(main, padding=4), "log.frame")
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
            self.after(0, lambda: self._set_daemon(self._t("daemon.warm"), True))
            return True
        self._log_put("[daemon] не запущен — стартую tools/lua_daemon.py…")
        self.after(0, lambda: self._set_daemon(self._t("daemon.starting"), None))
        try:
            subprocess.Popen(
                [WIN_PYTHON, os.path.join(TOOLS, "lua_daemon.py")],
                cwd=REPO, creationflags=NO_WINDOW | DETACHED,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except Exception as exc:
            self._log_put(f"[daemon] не удалось запустить: {exc}")
            self.after(0, lambda: self._set_daemon(self._t("daemon.error"), False))
            return False
        for _ in range(60):
            if lua_client.is_running():
                self._log_put("[daemon] готов (warm)")
                self.after(0, lambda: self._set_daemon(self._t("daemon.warm"), True))
                return True
            time.sleep(0.5)
        self._log_put("[daemon] не поднялся за отведённое время")
        self.after(0, lambda: self._set_daemon(self._t("daemon.none"), False))
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
                self._set_daemon(self._t("daemon.warm") if warm else self._t("daemon.none"), warm)))
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

    def _retranslate_capture_combo(self) -> None:
        idx = self._mon_combo.current()
        self._mon_combo.configure(values=[self._t(o["key"]) for o in CAPTURE_OPTIONS])
        self._mon_combo.current(idx if idx >= 0 else 0)

    # -- secret-task monitoring ---------------------------------------------
    def _toggle_monitor(self) -> None:
        if self._mon_var.get():
            self._start_monitor()
        else:
            self._stop_monitor()

    def _start_monitor(self) -> None:
        if self._mon_proc is not None:
            return
        idx = self._mon_combo.current()
        script = CAPTURE_OPTIONS[idx if idx >= 0 else 0]["script"]
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

    def _task_passes(self, ln: str) -> bool:
        """Panel-side filters for a secret-task finding line. Non-task lines always pass.

        A finding looks like `[*] lvl N  @[x,y|server] ... [PENDING]`. Filters are read live
        from the checkboxes/entries, so toggling one affects subsequent lines immediately.
        """
        m = re.search(r"\blvl\s+(\d+)\b", ln)
        if not m or "@[" not in ln:
            return True  # header / progress / summary line — never filtered
        lvl = int(m.group(1))
        lo, hi = self._lvl_from_var.get().strip(), self._lvl_to_var.get().strip()
        if lo.isdigit() and lvl < int(lo):
            return False
        if hi.isdigit() and lvl > int(hi):
            return False
        if self._star_var.get() and not re.match(r"\s*\*", ln):
            return False
        if self._pending_var.get() and "PENDING" not in ln:
            return False
        return True

    def _mon_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                ln = raw.rstrip()
                if self._task_passes(ln):
                    self._log_put(f"[secret] {ln}")
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
