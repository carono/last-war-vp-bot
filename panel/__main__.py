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

All panel settings (language, checkboxes, filters, coordinates, monitor state) live in a named
*profile*; the switcher bar above the tabs creates / renames / deletes / selects one. Each profile
is a directory under panel/profiles/<name>/ holding config.json plus its own rally_log.jsonl and
secret_tasks_log.jsonl; the active profile is remembered in panel/settings.json (see panel/profile.py).
Every change auto-saves, and switching a profile re-applies all of its settings.

Any coordinate printed in the log — canonical `X:1 Y:2` / `#server X:1 Y:2` (tools/coords.py) or a
free-form `(1,2)` / `1/2` / `координаты 1 2` / legacy `@[1,2]` — becomes a clickable link that jumps
there.

Run under Windows Python (needs psutil/tkinter; the daemon needs the il2cpp deps of
tools/lua_eval.py; the capture needs scapy/npcap):

    C:\\Python312\\python.exe -m panel
"""
from __future__ import annotations

# Make relative imports work in BOTH launch modes, before importing anything
# from the package. `from __future__` must stay first (a language rule), so this
# is as close to the very top as Python allows.
#   * `python -m panel`         -> __package__ == "panel"   (already fine)
#   * `python panel/__main__.py` -> __package__ is None/""   (no parent package)
# Putting the repo root on sys.path and pinning __package__ = "panel" lets the
# plain `from . import ...` below resolve identically in either case.
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if not __package__:
    __package__ = "panel"

import glob
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from . import __version__ as APP_VERSION
from . import i18n as i18nmod
from . import profile as profilemod

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
# The production entrypoints live in tools/ and the shared library modules
# (lua_client, lua_actions, coords, …) in tools/lib/ since the split. Both must
# be importable by bare name — the same fix bot/__init__.py already carries.
TOOLS_LIB = os.path.join(TOOLS, "lib")
# src/ carries the DSL runtime (lastwar_bot.script_engine) that interprets the
# actions/*.md scripts — the Scenarios tab runs them. Its heavy deps (cv2, win32)
# are imported lazily inside the interpreter, so importing the package is cheap and
# Lua-only actions run without them.
SRC = os.path.join(REPO, "src")
for _tp in (TOOLS, TOOLS_LIB, SRC):
    if _tp not in sys.path:
        sys.path.insert(0, _tp)
import lua_client       # noqa: E402  (lightweight — no il2cpp deps)
import lua_actions      # noqa: E402
import coords           # noqa: E402
import chat_assets      # noqa: E402  (token -> local sprite PNG for chat rendering)

try:
    from PIL import Image as _PILImage, ImageTk as _PILImageTk  # noqa: E402
    _PIL_OK = True
except Exception:       # noqa: BLE001
    _PIL_OK = False

WIN_PYTHON = r"C:\Python312\python.exe"
DEFAULT_SERVER = str(lua_actions.HOME_SERVER)
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW
DETACHED = 0x00000008         # DETACHED_PROCESS
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PHOTO_TOK = re.compile(r"\[photo:(\d+)\]")

# Game lifecycle (paths derived from %LOCALAPPDATA%, no hardcoded username)
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
GAME_DIR = os.path.join(_LOCALAPPDATA, "FunFly", "Last War-Survival Game")
LAUNCHER = os.path.join(GAME_DIR, "LastWarLauncher.exe")
GAME_EXE = "LastWar.exe"

# Capture options: a stable i18n key (combobox label) paired with its capture script.
# The selected script is resolved by combobox index, so the visible label can be
# translated freely without breaking the lookup.
# `script` is a path relative to tools/ — secret_mission_capture.py lives under
# tools/dev/, so the subdir must travel with the name or the launch FileNotFounds.
CAPTURE_OPTIONS = [
    {"key": "capture.secret_tasks", "script": "secret_task_capture.py"},
    {"key": "capture.ghost_op", "script": os.path.join("dev", "secret_mission_capture.py")},
]

# Develop-tab sniffers. Absolute paths, resolved at launch, so the working
# directory the panel was started from is irrelevant.
#   * Traffic  — tools/lib/live_sniffer.py: raw live decode of the game protocol,
#     one line per command as it crosses the wire (see docs/research/protocol.md).
#   * Functions — tools/lua_trace.py --dedup: wraps every reachable Lua function
#     and logs the FIRST call of each name only. The unfiltered tracer floods
#     Player.log and freezes the game, so --dedup is the safe discovery default
#     (per task #1060: the monkey-patch tool is tools/lua_trace.py).
# The two answer the same question from opposite ends — what crossed the wire vs
# what the client called — so the menu runs them as ONE toggle: a single label is
# asked once and handed to both children, which makes the two run files of a
# session share a name and line up when read side by side (task #1079).
# Each start spawns fresh children, and each child opens its own timestamped file
# under results/traffic/ resp. results/traces/ — so a stop/start cycle never
# overwrites the previous session. The child prints the path it chose, which
# lands in the panel log like the rest of its output, tagged [traffic] / [trace].
TRAFFIC_SNIFFER = os.path.join(TOOLS_LIB, "live_sniffer.py")
FUNCTION_SNIFFER = os.path.join(TOOLS, "lua_trace.py")
# How long to wait for both sniffer halves to report "ready" before saying so in
# the log. Measured on this machine: capture is live ~1 s in, the Lua hooks
# ~2 s in with a warm daemon and noticeably later when it has to attach first —
# so the cap is generous, it only exists to break a silent wait.
SNIFF_READY_TIMEOUT = 25.0

# Directory holding the DSL action scripts the Scenarios tab lists and runs. Only the
# blessed (tested) actions live here; experimental ones sit in actions/dev/, which the
# non-recursive glob below deliberately skips, so the picker offers only what works.
ACTIONS_DIR = os.path.join(SRC, "lastwar_bot", "actions")
# Actions that are runtime plumbing rather than user-facing scenarios — hidden from
# the picker even if present here. `watchdog` is ticked by the runner, not run by hand.
_HIDDEN_ACTIONS = frozenset({"watchdog"})


def list_actions() -> list[dict]:
    """Enumerate the blessed action scripts (actions/*.md, not actions/dev/) as {name, title}.

    `title` is the first `#` comment line of the .md (falling back to the name),
    so the picker shows a human sentence instead of a bare file stem.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(ACTIONS_DIR, "*.md"))):
        name = os.path.splitext(os.path.basename(path))[0]
        if name in _HIDDEN_ACTIONS:
            continue
        title = name
        try:
            with open(path, encoding="utf-8") as fh:
                for raw in fh:
                    s = raw.strip()
                    if s.startswith("#"):
                        title = s.lstrip("#").strip() or name
                        break
                    if s:
                        break
        except OSError:
            pass
        out.append({"name": name, "title": title})
    return out


_NON_GAME_PORTS = frozenset({80, 443})


def _server_connection() -> str | None:
    """The game-server TCP endpoint, if a connection is currently ESTABLISHED.

    Purely supplementary detail. Its absence (VPN off, mid-reconnect, or the OS
    withholding foreign-owned sockets) must NOT be read as "game not running" —
    that is decided by :func:`game_status` from the process list alone.

    The remote port is not stable across builds (:17935 historically, :10012 on
    the current client), so the check is port-agnostic: find lastwar.exe's PIDs,
    then return the first ESTABLISHED remote address that is not a web port.
    """
    try:
        import psutil
        pids = {p.info["pid"] for p in psutil.process_iter(["pid", "name"])
                if (p.info["name"] or "").lower() == GAME_EXE.lower()}
        if not pids:
            return None
        for c in psutil.net_connections(kind="tcp"):
            if (c.pid in pids and c.raddr and c.status == "ESTABLISHED"
                    and c.raddr.port not in _NON_GAME_PORTS):
                return f"{c.raddr.ip}:{c.raddr.port}"
    except Exception:
        return None
    return None


def game_status() -> tuple[bool, str]:
    """Whether the game is running, detected by process name only.

    Detection is deliberately independent of network state: the game is "found"
    whenever its process exists, regardless of VPN presence or whether a TCP
    connection to the game server is currently established. The connection state,
    when available, is appended as supplementary detail.

    Returns ``(running, label)``.
    """
    try:
        import psutil
    except Exception:
        return False, "psutil missing"

    pid = None
    try:
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() == GAME_EXE.lower():
                pid = proc.pid
                break
    except Exception as exc:
        return False, f"probe error: {exc}"

    if pid is None:
        return False, "game not found"

    conn = _server_connection()
    if conn:
        return True, f"running (pid {pid}) -> {conn}"
    return True, f"running (pid {pid})"


class Panel(tk.Tk):
    def __init__(self, active_profile: str | None = None) -> None:
        super().__init__()
        self._i18n = i18nmod.I18n()
        self._tr_widgets: list = []   # (widget, option, key, fmt) — retranslated in place
        self._tr_hooks: list = []     # callables run on every language change
        # Profiles: the active profile's config.json drives every panel setting.
        self._profiles = profilemod.ProfileManager()
        # An explicit --profile overrides the saved last-active profile, creating
        # it on the fly if it does not exist yet.
        if active_profile:
            self._profiles.set_active(active_profile)
        self._settings = self._profiles.load()
        self._loading = True          # suppresses auto-save while we apply settings
        saved_lang = self._settings.get("language")
        if saved_lang:                # profile is the source of truth for language
            self._i18n.set_lang(saved_lang)
        self.title(self._t("app.title"))
        self.geometry("760x600")
        self.minsize(640, 500)
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._busy = False
        self._coord_seq = 0
        self._mon_proc = None
        self._rally_proc = None
        self._sniff_proc = None       # Develop: traffic sniffer
        self._trace_proc = None       # Develop: Lua-function tracer
        self._sniff_ready = {}        # per-half readiness: None pending / True / False
        self._sniff_t0 = 0.0          # when the pair was launched (for "ready in Ns")
        # Toggle state for the single Develop-menu sniffer entry (it drives both
        # children above). Created here (not in a tab builder) because the menu
        # bar is built before the UI and is rebuilt on every language change —
        # the var must outlive those rebuilds.
        self._sniff_var = tk.BooleanVar(value=False)
        self._chat_var = tk.BooleanVar(value=False)
        self._chat_q: "queue.Queue[dict]" = queue.Queue()
        self._chat_proc = None
        # In-memory chat messages keyed by chat_type
        self._chat_msgs: dict = {t: [] for t in ("world", "alliance", "national", "dm", "other", "system")}
        # Text-view widgets per chat type (populated by _build_chat_tab). Named
        # _chat_trees for historical reasons; they are tk.Text now, not Treeviews.
        self._chat_trees: dict = {}
        # Count of lines already rendered into each view (for incremental appends)
        self._chat_tree_rows: dict = {}
        # Cache of inline sprite images keyed by (path, height) -- also keeps the
        # PhotoImage refs alive (tk.Text does not hold a Python reference).
        self._chat_img_cache: dict = {}
        self._photo_seq = 0            # unique-tag counter for clickable photos
        self._client = lua_client.DaemonClient()
        self._build_menu()
        self._build_profile_bar()
        self._build_ui()
        self._apply_settings_to_ui()  # restore this profile's saved values
        self._loading = False
        self._install_autosave()      # persist every subsequent change immediately
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
            self._save_settings()   # language is a per-profile setting

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

        develop_menu = tk.Menu(menubar, tearoff=0)
        develop_menu.add_checkbutton(label=self._t("develop.sniff.toggle"),
                                     variable=self._sniff_var, command=self._toggle_sniff)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=self._t("menu.help.about"), command=self._show_about)

        menubar.add_cascade(label=self._t("menu.language"), menu=lang_menu)
        menubar.add_cascade(label=self._t("menu.develop"), menu=develop_menu)
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

    # -- profiles -----------------------------------------------------------
    def _build_profile_bar(self) -> None:
        """A switcher bar (create / rename / delete / select) above the tabs."""
        bar = ttk.Frame(self, padding=(8, 6, 8, 0))
        bar.pack(fill="x", side="top")
        self._tr(ttk.Label(bar), "profile.label").pack(side="left")
        self._profile_var = tk.StringVar(value=self._profiles.active)
        self._profile_combo = ttk.Combobox(bar, textvariable=self._profile_var,
                                            state="readonly", width=20,
                                            values=self._profiles.list())
        self._profile_combo.pack(side="left", padx=(6, 8))
        self._profile_combo.bind("<<ComboboxSelected>>", lambda e: self._switch_profile())
        self._tr(ttk.Button(bar, command=self._create_profile),
                 "profile.new").pack(side="left", padx=2)
        self._tr(ttk.Button(bar, command=self._rename_profile),
                 "profile.rename").pack(side="left", padx=2)
        self._tr(ttk.Button(bar, command=self._delete_profile),
                 "profile.delete").pack(side="left", padx=2)

    def _refresh_profile_combo(self, select: str | None = None) -> None:
        self._profile_combo.configure(values=self._profiles.list())
        self._profile_var.set(select or self._profiles.active)

    def _switch_profile(self, name: str | None = None) -> None:
        name = name or self._profile_var.get()
        if name == self._profiles.active:
            return
        self._save_settings()                 # flush the profile we are leaving
        self._profiles.set_active(name)
        self._settings = self._profiles.load()
        self._reload_active_profile()
        self._log_put(f"[profile] активный профиль: {name}")

    def _reload_active_profile(self) -> None:
        """Re-apply language, all UI values, and monitor state from self._settings."""
        lang = self._settings.get("language")
        if lang and lang != self._i18n.lang and self._i18n.set_lang(lang):
            self._apply_language()
        self._apply_settings_to_ui()
        self._sync_monitors()                 # restart captures into the new profile's logs
        self._load_chat_history()             # reload chat messages for the new profile

    def _create_profile(self) -> None:
        name = simpledialog.askstring(self._t("profile.new"),
                                      self._t("profile.prompt_name"), parent=self)
        if not name:
            return
        try:
            created = self._profiles.create(name)
        except ValueError as exc:
            messagebox.showerror(self._t("profile.new"), str(exc), parent=self)
            return
        # Seed the new profile with the current settings so it starts from a sane state.
        self._profiles.save(self._collect_settings(), created)
        self._refresh_profile_combo(select=created)
        self._switch_profile(created)

    def _rename_profile(self) -> None:
        cur = self._profiles.active
        name = simpledialog.askstring(self._t("profile.rename"),
                                      self._t("profile.prompt_name"),
                                      initialvalue=cur, parent=self)
        if not name:
            return
        try:
            newn = self._profiles.rename(cur, name)
        except ValueError as exc:
            messagebox.showerror(self._t("profile.rename"), str(exc), parent=self)
            return
        self._refresh_profile_combo(select=newn)
        self._log_put(f"[profile] переименован: {cur} → {newn}")

    def _delete_profile(self) -> None:
        cur = self._profiles.active
        if not messagebox.askyesno(self._t("profile.delete"),
                                   self._t("profile.confirm_delete", name=cur), parent=self):
            return
        try:
            now_active = self._profiles.delete(cur)
        except ValueError as exc:
            messagebox.showerror(self._t("profile.delete"), str(exc), parent=self)
            return
        self._refresh_profile_combo(select=now_active)
        self._settings = self._profiles.load()
        self._reload_active_profile()
        self._log_put(f"[profile] удалён {cur}; активный → {now_active}")

    # -- persistent settings ------------------------------------------------
    def _collect_settings(self) -> dict:
        """Snapshot every persisted panel setting into a plain dict."""
        return {
            "language": self._i18n.lang,
            "coord_x": self._x_var.get(),
            "coord_y": self._y_var.get(),
            "coord_server": self._srv_var.get(),
            "monitor_kind": self._mon_combo.current(),
            "monitor_interval": self._interval_var.get(),
            "filter_star": self._star_var.get(),
            "filter_pending": self._pending_var.get(),
            "filter_can_loot": self._can_loot_var.get(),
            "filter_level_from": self._lvl_from_var.get(),
            "filter_level_to": self._lvl_to_var.get(),
            "rally_monitor": self._rally_var.get(),
            "secret_monitor": self._mon_var.get(),
            "chat_monitor": self._chat_var.get(),
        }

    def _apply_settings_to_ui(self) -> None:
        """Push self._settings into the widgets without triggering auto-save."""
        s = self._settings
        self._loading = True
        try:
            self._x_var.set(s.get("coord_x", ""))
            self._y_var.set(s.get("coord_y", ""))
            self._srv_var.set(s.get("coord_server", DEFAULT_SERVER))
            idx = s.get("monitor_kind", 0)
            if isinstance(idx, int) and 0 <= idx < len(CAPTURE_OPTIONS):
                self._mon_combo.current(idx)
            self._interval_var.set(str(s.get("monitor_interval", "15")))
            self._star_var.set(bool(s.get("filter_star", False)))
            self._pending_var.set(bool(s.get("filter_pending", False)))
            self._can_loot_var.set(bool(s.get("filter_can_loot", False)))
            self._lvl_from_var.set(s.get("filter_level_from", ""))
            self._lvl_to_var.set(s.get("filter_level_to", ""))
            self._rally_var.set(bool(s.get("rally_monitor", True)))
            self._mon_var.set(bool(s.get("secret_monitor", False)))
            self._chat_var.set(bool(s.get("chat_monitor", False)))
        finally:
            self._loading = False
        self._update_path_hints()

    def _install_autosave(self) -> None:
        """Persist to the active profile whenever any bound setting changes."""
        for var in (self._x_var, self._y_var, self._srv_var, self._star_var,
                    self._pending_var, self._can_loot_var, self._lvl_from_var,
                    self._lvl_to_var, self._rally_var, self._mon_var, self._chat_var):
            var.trace_add("write", lambda *a: self._save_settings())
        self._mon_combo.bind("<<ComboboxSelected>>", lambda e: self._save_settings(), add="+")
        # The interval is a child-process argument, not a live panel-side filter,
        # so a change only takes effect on the next capture launch. Bounce a
        # running monitor so a new value applies at once instead of on the next
        # manual toggle. Saved too (via _save_settings inside _restart_monitor).
        self._interval_var.trace_add("write", lambda *a: self._on_interval_change())

    def _on_interval_change(self) -> None:
        self._save_settings()
        if not self._loading and self._mon_proc is not None:
            self._restart_monitor()

    def _restart_monitor(self) -> None:
        """Bounce the secret capture so a changed --interval/server seed applies."""
        self._stop_monitor()
        self._start_monitor()

    def _save_settings(self) -> None:
        if getattr(self, "_loading", False):
            return
        self._settings = self._collect_settings()
        self._profiles.save(self._settings)

    def _sync_monitors(self) -> None:
        """Start/stop (restart) the rally, secret and chat captures to match the checkboxes.

        Restarting is deliberate: a running capture keeps writing to the *old* profile's
        log, so on a profile switch we bounce it to redirect output to the new directory.
        """
        self._stop_rally()
        if self._rally_var.get():
            self._start_rally()
        self._stop_monitor()
        if self._mon_var.get():
            self._start_monitor()
        self._stop_chat()
        if self._chat_var.get():
            self._start_chat()

    def _update_path_hints(self) -> None:
        """Refresh labels that show the active profile's log path (rally hint)."""
        if hasattr(self, "_rally_hint"):
            try:
                rel = os.path.relpath(self._profiles.rally_log(), REPO)
                self._rally_hint.configure(text=self._t("rally.hint", path=rel))
            except tk.TclError:
                pass

    # -- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        main = ttk.Frame(nb)
        scenarios = ttk.Frame(nb)
        chat_tab = ttk.Frame(nb)
        nb.add(main, text=self._t("tab.main"))
        nb.add(scenarios, text=self._t("tab.scenarios"))
        nb.add(chat_tab, text=self._t("tab.chat"))
        self._tr_hooks.append(lambda: (nb.tab(main, text=self._t("tab.main")),
                                       nb.tab(scenarios, text=self._t("tab.scenarios")),
                                       nb.tab(chat_tab, text=self._t("tab.chat"))))
        self._build_scenarios_tab(scenarios)
        self._build_chat_tab(chat_tab)

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
        # Capture tick interval (the child's --interval): how often the progress
        # line prints and the checkpoint flushes. A Spinbox so it is bounded and
        # obviously numeric; a change while the monitor runs restarts it (below).
        self._tr(ttk.Label(row1), "secret.interval").pack(side="left", padx=(12, 2))
        self._interval_var = tk.StringVar(value="15")
        ttk.Spinbox(row1, from_=1, to=3600, width=5, textvariable=self._interval_var
                    ).pack(side="left")
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
        self._can_loot_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(row2, variable=self._can_loot_var),
                 "secret.can_loot_only").pack(side="left", padx=(6, 0))
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
        # Hint shows the active profile's rally log; refreshed on language/profile change.
        self._rally_hint = ttk.Label(rally, foreground="#888")
        self._rally_hint.pack(side="left", padx=10)
        self._tr_hooks.append(self._update_path_hints)

        logframe = self._tr(ttk.LabelFrame(main, padding=4), "log.frame")
        logframe.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        # Plain native Text widget: state="normal" (never toggled to "disabled",
        # which would block interactive selection). The log stays technically
        # editable, but stray typed edits to a log are harmless. Mouse selection
        # comes for free from Tk's Text defaults; copy needs help, though — Tk's
        # built-in <Control-c> binding matches only the Latin 'c' keysym, so with
        # a non-Latin keyboard layout (e.g. Cyrillic) Ctrl+C never fires. We add
        # layout-independent copy/select-all: explicit key bindings that cover the
        # Cyrillic keysyms plus a right-click context menu (Copy / Select All).
        self._log = scrolledtext.ScrolledText(logframe, wrap="word", height=16,
                                              font=("Consolas", 9),
                                              background="#111", foreground="#ddd")
        self._log.pack(fill="both", expand=True)
        self._log.tag_config("coordlink", foreground="#5cf", underline=True)
        self._install_log_copy(self._log)

    # -- log copy support ---------------------------------------------------
    def _install_log_copy(self, widget: tk.Text) -> None:
        """Make the log copyable regardless of keyboard layout.

        Tk's default Text bindings copy on the Latin ``<Control-c>`` only, so a
        Cyrillic (or any non-Latin) layout leaves Ctrl+C dead. We add explicit
        bindings for the Cyrillic keysyms and a right-click context menu, which
        is fully layout-independent. Handlers return ``"break"`` so the default
        binding (when it does fire) doesn't run twice.
        """
        # One dispatcher for all Ctrl+<letter> presses. It matches on the
        # physical key (Windows VK code — layout-invariant: C=67, A=65) first,
        # then falls back to the keysym so Latin and named Cyrillic keysyms work
        # cross-platform. This is what makes copy work under a Cyrillic layout,
        # where Tk's default <Control-c> (Latin-only) never fires.
        widget.bind("<Control-KeyPress>", self._on_log_ctrl_key)

        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(command=self._copy_log_selection)        # idx 0: Copy
        menu.add_command(command=self._select_all_log)            # idx 1: Select All
        self._log_menu = menu
        self._retranslate_log_menu()
        self._tr_hooks.append(self._retranslate_log_menu)
        # Button-3 is right-click on Windows/X11; Button-2 covers macOS.
        widget.bind("<Button-3>", self._popup_log_menu)
        widget.bind("<Button-2>", self._popup_log_menu)

    def _retranslate_log_menu(self) -> None:
        self._log_menu.entryconfigure(0, label=self._t("log.copy"))
        self._log_menu.entryconfigure(1, label=self._t("log.select_all"))

    def _on_log_ctrl_key(self, event):
        """Route Ctrl+C / Ctrl+A independently of keyboard layout."""
        keysym = (event.keysym or "").lower()
        # keycode: Windows VK code (physical key). Cyrillic_es/ef cover X11.
        if event.keycode == 67 or keysym in ("c", "cyrillic_es"):
            return self._copy_log_selection()
        if event.keycode == 65 or keysym in ("a", "cyrillic_ef"):
            return self._select_all_log()
        return None                        # let other Ctrl+combos pass through

    def _copy_log_selection(self, _event=None) -> str:
        try:
            sel = self._log.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"                 # nothing selected
        if sel:
            self.clipboard_clear()
            self.clipboard_append(sel)
        return "break"

    def _select_all_log(self, _event=None) -> str:
        self._log.tag_remove("sel", "1.0", "end")
        self._log.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _popup_log_menu(self, event) -> str:
        try:
            self._log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._log_menu.grab_release()
        return "break"

    # -- logging ------------------------------------------------------------
    def _log_put(self, line: str) -> None:
        self._log_q.put(line)

    def _pump_log(self) -> None:
        try:
            while True:
                line = self._log_q.get_nowait()
                self._insert_line(line + "\n")
                self._append_log(line)
        except queue.Empty:
            pass
        self.after(120, self._pump_log)

    def _append_log(self, line: str) -> None:
        """Mirror a log line to the active profile's panel.log, flushed at once.

        Opened per line in line-buffered append mode and explicitly flushed so the
        on-disk log is never behind the widget, even if the panel is killed. Writes
        follow the active profile, so switching profiles redirects the file too.
        """
        try:
            clean = _ANSI.sub("", line)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self._profiles.panel_log(), "a", encoding="utf-8", buffering=1) as fh:
                fh.write(f"{stamp} {clean}\n")
                fh.flush()
        except Exception:
            pass                    # logging must never crash the panel

    def _insert_line(self, text: str) -> None:
        """Insert a log line, turning any coordinate token into a clickable link."""
        clean = _ANSI.sub("", text)
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

    # -- daemon lifecycle ---------------------------------------------------
    def _startup(self) -> None:
        if self._rally_var.get():           # rally monitor is on by default
            self._start_rally()
        if self._mon_var.get():             # secret-task monitor, if the profile had it on
            self._start_monitor()
        if self._chat_var.get():            # chat monitor, if the profile had it on
            self._start_chat()
        self.after(0, self._load_chat_history)
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
            ok, s = game_status()
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
        # NO --all-tcp. It sets the BPF to a bare "tcp", so on a busy adapter
        # (this box sees ~280 tcp frames/s) scapy's Python callback can't keep up
        # and npcap's ring overflows — ~98% of packets, the game's map frames
        # among them, are dropped before decode. That is exactly why the capture
        # works when run by hand (auto-detect → "tcp port 17935", filtered in the
        # kernel, no flood) but found nothing when the panel forced --all-tcp.
        # Let the capture auto-detect the game's live port; --all-tcp stays a
        # manual last resort for when detection genuinely fails.
        cmd = [WIN_PYTHON, "-u", os.path.join(TOOLS, script)]
        # Capture tick interval from the panel (falls back to the child's own
        # default if the field is blank or non-numeric).
        interval = self._interval_var.get().strip()
        if interval.isdigit() and int(interval) > 0:
            cmd += ["--interval", interval]
        # Seed the on-screen server from the running game via the warm Lua daemon,
        # so the capture prints "server N" from its first line instead of sitting
        # on "server unknown yet" until the map is scrolled (the passive capture
        # only learns the server from a map response, which arrives only while the
        # map moves). VPN-independent; the capture's own weight-of-traffic election
        # still overrides this seed the moment real map data disagrees.
        if lua_client.is_running():
            srv = self._current_server()
            if srv and str(srv).isdigit():
                cmd += ["--seed-server", str(srv)]
                self._log_put(f"[secret] сервер из игры (Lua): {srv}")
        # The child is Windows Python whose piped stdout defaults to the ANSI code
        # page (cp1251/cp1252), so its em-dash / ellipsis progress glyphs arrived
        # here as � under our utf-8 decode. Force the child to emit utf-8 to match.
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        self._log_put(f"[secret] запуск захвата: {script} …")
        try:
            self._mon_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=REPO,
                env=env, creationflags=NO_WINDOW)
        except Exception as exc:
            self._log_put(f"[secret] ошибка запуска: {exc}")
            self._mon_proc = None
            self._mon_var.set(False)
            return
        # Confirm the child really started (so a silent monitor is never mistaken
        # for a crash) and stream its stdout+stderr into the log. A passive pcap
        # only yields tiles while the map is scrolling, so remind the user.
        self._log_put(f"[secret] захват запущен (pid {self._mon_proc.pid}); "
                      f"вывод идёт в лог — двигай карту, иначе трафика не будет")
        threading.Thread(target=self._mon_reader, args=(self._mon_proc,), daemon=True).start()

    def _task_passes(self, ln: str) -> bool:
        """Panel-side filters for a secret-task finding line. Non-task lines always pass.

        A finding looks like `[*] lvl N  #server X:x Y:y ... [PENDING]`. Filters are read live
        from the checkboxes/entries, so toggling one affects subsequent lines immediately.
        A line counts as a finding when it has both a `lvl N` and a parseable coordinate.
        """
        m = re.search(r"\blvl\s+(\d+)\b", ln)
        if not m or not coords.parse(ln):
            return True  # header / progress / summary line — never filtered
        lvl = int(m.group(1))
        lo, hi = self._lvl_from_var.get().strip(), self._lvl_to_var.get().strip()
        if lo.isdigit() and lvl < int(lo):
            return False
        if hi.isdigit() and lvl > int(hi):
            return False
        if self._star_var.get() and not re.match(r"\s*\*", ln):
            return False
        # PENDING and LOOTABLE are two values of one dimension — raid readiness —
        # and the capture tags a line with exactly one of them (a tile walks
        # PENDING -> LOOTABLE, never both at once). So enabling both checkboxes
        # reads as "either", matching `filter_tasks` in lastwar_proto: ANDing the
        # two substrings could never match and the panel simply went blank.
        want_pending, want_loot = self._pending_var.get(), self._can_loot_var.get()
        if want_pending or want_loot:
            tags = ("PENDING",) if want_pending and not want_loot else \
                   ("LOOTABLE",) if want_loot and not want_pending else \
                   ("PENDING", "LOOTABLE")
            if not any(t in ln for t in tags):
                return False
        return True

    def _mon_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                ln = raw.rstrip()
                if self._task_passes(ln):
                    self._log_put(f"[secret] {ln}")
                    if coords.parse(ln):   # a coordinate present -> an actual finding; record it
                        self._append_secret(ln)
        except Exception:
            pass
        if self._mon_proc is proc:      # ended on its own, not via _stop_monitor
            self._log_put("[secret] поток мониторинга завершён")
            self._mon_proc = None
            self.after(0, lambda: self._mon_var.set(False))

    def _append_secret(self, line: str) -> None:
        """Append a secret-task finding to the active profile's log (best-effort)."""
        try:
            with open(self._profiles.secret_log(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "line": line}, ensure_ascii=False) + "\n")
        except OSError:
            pass

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
        out = self._profiles.rally_log()   # per-profile log
        rel = os.path.relpath(out, REPO)
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
        except Exception:
            pass
        self._log_put(f"[rally] старт мониторинга ралли → {rel}")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")   # utf-8 to match our decode
        try:
            self._rally_proc = subprocess.Popen(
                [WIN_PYTHON, "-u", os.path.join(TOOLS, "rally_monitor.py"),
                 "--out", out],   # no --all-tcp: auto-detect the narrow game port (see _start_monitor)
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=REPO,
                env=env, creationflags=NO_WINDOW)
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

    # -- Develop menu: raw sniffers -----------------------------------------
    def _spawn_sniffer(self, cmd: list, tag: str) -> "subprocess.Popen | None":
        """Launch a raw sniffer child, streaming its stdout+stderr into the log.

        Same recipe as the secret/rally monitors: Windows Python, unbuffered,
        utf-8 forced (the child's piped stdout would otherwise fall back to the
        ANSI code page and mangle its glyphs under our utf-8 decode), no console
        window. Returns the process, or None if it failed to start.
        """
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            return subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=REPO,
                env=env, creationflags=NO_WINDOW)
        except Exception as exc:
            self._log_put(f"[{tag}] ошибка запуска: {exc}")
            return None

    def _ask_run_label(self) -> "str | None":
        """Ask what this sniffer run is about; returns the label, or None if cancelled.

        A run file is named by its start time alone, which says nothing about
        what was being captured — the label is what makes a directory of them
        readable later (see tools/lib/run_output.py). Empty input is a valid
        answer (no label); only Cancel aborts the launch, which is why "" and
        None must stay distinguishable here.
        """
        return simpledialog.askstring(self._t("develop.label.title"),
                                      self._t("develop.label.prompt"), parent=self)

    def _toggle_sniff(self) -> None:
        """One menu entry, both sniffers: on → start the pair, off → stop the pair."""
        if self._sniff_var.get():
            self._start_sniff()
        else:
            self._stop_sniff()

    def _start_sniff(self) -> None:
        """Ask for one label, then start the traffic sniffer and the Lua tracer.

        The label is asked ONCE and passed to both children so a session's two
        run files carry the same name. If only one of the two comes up the
        toggle stays on — a half-running session is still worth watching — and
        the log says which half is missing; only a total failure flips it back.
        """
        if self._sniff_proc is not None or self._trace_proc is not None:
            return
        label = self._ask_run_label()
        if label is None:
            self._sniff_var.set(False)
            return
        label_args = ["--label", label] if label.strip() else []

        # Neither child is capturing when its pid appears: npcap needs ~1 s to
        # open the interfaces and the Lua hooks land ~2 s in (more with a cold
        # daemon). Both now print a readiness marker; collect them and say ONE
        # word when the pair is actually recording — acting before that quietly
        # loses the frames the run was started for.
        self._sniff_ready = {}
        self._sniff_t0 = time.time()

        self._log_put("[traffic] запуск сырого снифера трафика (live_sniffer.py) …")
        self._sniff_proc = self._spawn_sniffer(
            [WIN_PYTHON, "-u", TRAFFIC_SNIFFER] + label_args, "traffic")
        if self._sniff_proc is not None:
            self._sniff_ready["traffic"] = None
            self._log_put(f"[traffic] снифер запущен (pid {self._sniff_proc.pid}); "
                          f"вывод идёт в лог, запись — в results/traffic/")
            threading.Thread(target=self._sniff_reader, args=(self._sniff_proc,),
                             daemon=True).start()

        # --dedup: log only the first call of each function name. Without it the
        # tracer wraps every reachable Lua function and floods Player.log, which
        # freezes the game — see the tools/lua_trace.py docstring. The safe
        # discovery pass is the right default for a one-click panel button.
        self._log_put("[trace] запуск трассировщика Lua-функций (lua_trace.py --dedup) …")
        self._trace_proc = self._spawn_sniffer(
            [WIN_PYTHON, "-u", FUNCTION_SNIFFER, "--dedup"] + label_args, "trace")
        if self._trace_proc is not None:
            self._sniff_ready["trace"] = None
            self._log_put(f"[trace] трассировщик запущен (pid {self._trace_proc.pid}); "
                          f"вывод идёт в лог, запись — в results/traces/")
            threading.Thread(target=self._trace_reader, args=(self._trace_proc,),
                             daemon=True).start()

        if self._sniff_proc is None and self._trace_proc is None:
            self._sniff_var.set(False)
            return
        self._log_put("[sniff] жду готовности обоих потоков — пока не действуй в игре …")
        self.after(int(SNIFF_READY_TIMEOUT * 1000), self._sniff_ready_watchdog)

    def _mark_sniff_ready(self, part: str, ok: bool) -> None:
        """Record one half's verdict; announce as soon as both have reported.

        `self._sniff_ready` holds None until a half reports, so a failure is a
        distinct outcome from "still starting" — otherwise a dead tracer would
        either be announced as ready or block the announcement forever.
        """
        state = self._sniff_ready
        if state.get(part, "gone") is not None:      # unknown part, or already reported
            return
        state[part] = ok
        if any(v is None for v in state.values()):
            return
        dt = time.time() - self._sniff_t0
        live = [p for p, v in state.items() if v]
        if len(live) == len(state):
            self._log_put(f"[sniff] ГОТОВ ({dt:.1f} с) — оба потока пишут, "
                          f"можно выполнять действия в игре")
        elif live:
            self._log_put(f"[sniff] ЧАСТИЧНО ГОТОВ ({dt:.1f} с) — пишет только "
                          f"{', '.join(live)}; вторая половина сессии потеряна")
        else:
            self._log_put(f"[sniff] НЕ ГОТОВ ({dt:.1f} с) — ни один поток не пишет")

    def _sniff_ready_watchdog(self) -> None:
        """Never leave the log on "жду готовности" if a marker never arrives."""
        if self._sniff_proc is None and self._trace_proc is None:
            return                                   # session already over
        pending = [p for p, v in self._sniff_ready.items() if v is None]
        if pending:
            self._log_put(f"[sniff] готовность не подтверждена за "
                          f"{SNIFF_READY_TIMEOUT:.0f} с: {', '.join(pending)} — "
                          f"проверь лог выше")

    def _sniff_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                self._log_put(f"[traffic] {line}")
                if "CAPTURE READY" in line:
                    self._mark_sniff_ready("traffic", True)
                elif "CAPTURE FAILED" in line:
                    self._mark_sniff_ready("traffic", False)
        except Exception:
            pass
        if self._sniff_proc is proc:      # ended on its own, not via _stop_sniff
            self._log_put("[traffic] снифер завершён")
            self._sniff_proc = None
            self._mark_sniff_ready("traffic", False)  # died before reporting: nothing captured
            self._sync_sniff_var()

    def _trace_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                self._log_put(f"[trace] {line}")
                if "TRACE READY" in line:
                    self._mark_sniff_ready("trace", True)
                elif "TRACE FAILED" in line:
                    self._mark_sniff_ready("trace", False)
        except Exception:
            pass
        if self._trace_proc is proc:      # ended on its own, not via _stop_sniff
            self._log_put("[trace] трассировщик завершён")
            self._trace_proc = None
            self._mark_sniff_ready("trace", False)   # died before reporting: no hooks
            self._sync_sniff_var()

    def _sync_sniff_var(self) -> None:
        """Untick the shared toggle once BOTH children are gone.

        Either child may die on its own (the game restarts, tshark loses the
        interface). While the other one still runs the session is live, so the
        checkmark must stay — it is the pair's state, not one process's.
        """
        if self._sniff_proc is None and self._trace_proc is None:
            self.after(0, lambda: self._sniff_var.set(False))

    def _stop_sniff(self) -> None:
        proc, self._sniff_proc = self._sniff_proc, None
        if proc is not None:
            self._log_put("[traffic] стоп снифера трафика")
            try:
                proc.terminate()
            except Exception:
                pass
        proc, self._trace_proc = self._trace_proc, None
        if proc is not None:
            self._log_put("[trace] стоп трассировщика")
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
                target = int(server) if server is not None else int(cur)
                self._log_put(f"[coord] переход в ({x},{y}) [сервер {target}]")
                chunk = lua_actions.jump_to_coord(x, y, target)
                for ln in self._client.run(chunk, marker="ACT", settle=1.6):
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
    def _launch_game(self) -> None:
        # Launch through the same DSL recipe the bot uses: actions/launch_game.md
        # (LAUNCH the launcher, then WAIT for the base screen). One source of truth
        # for "start the game", shared by the panel and any scripted run.
        self._log_put("[game] запуск через рецепт launch_game…")
        self._run_md_action("launch_game")

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
            # Relaunch via the recipe (waits for the base screen, then daemon
            # re-initialises on the next action).
            self._run_md_action("launch_game")
        threading.Thread(target=work, daemon=True).start()

    def _on_close(self) -> None:
        self._stop_monitor()
        self._stop_rally()
        self._stop_sniff()      # stops both the traffic sniffer and the tracer
        self._stop_chat()
        self._stop_scenario_loop()
        self.destroy()


    # -- scenarios tab (run .md action scripts) -----------------------------

    def _build_scenarios_tab(self, parent: ttk.Frame) -> None:
        """List the DSL action scripts and let the operator run or loop one.

        Each `src/lastwar_bot/actions/*.md` is one runnable action. Run executes it
        once through the interpreter on a worker thread (output streams into the
        shared log); Repeat re-runs it on an interval until switched off. Game-VM
        actions (LUA/READ_LUA/GAME/JUMP) go through the Lua daemon and need no
        window; vision actions (FIND/CLICK) resolve the game window on demand.
        """
        self._scn_loop_stop = threading.Event()
        self._scn_loop_thread: threading.Thread | None = None

        frame = self._tr(ttk.LabelFrame(parent, padding=8), "scenarios.actions")
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        listwrap = ttk.Frame(frame)
        listwrap.pack(fill="both", expand=True)
        self._scn_list = tk.Listbox(listwrap, height=10, activestyle="dotbox",
                                    exportselection=False)
        scroll = ttk.Scrollbar(listwrap, orient="vertical", command=self._scn_list.yview)
        self._scn_list.configure(yscrollcommand=scroll.set)
        self._scn_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._scn_list.bind("<Double-Button-1>", lambda _e: self._run_selected_action())

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(8, 0))
        self._tr(ttk.Button(controls, command=self._run_selected_action),
                 "scenarios.run").pack(side="left", padx=(0, 4), ipady=2)
        self._scn_loop_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(controls, variable=self._scn_loop_var,
                                 command=self._toggle_scenario_loop),
                 "scenarios.loop").pack(side="left", padx=(8, 2))
        self._tr(ttk.Label(controls), "scenarios.interval").pack(side="left", padx=(6, 2))
        self._scn_interval_var = tk.StringVar(value="60")
        ttk.Spinbox(controls, from_=5, to=86400, width=6,
                    textvariable=self._scn_interval_var).pack(side="left")
        self._tr(ttk.Button(controls, command=self._refresh_actions),
                 "scenarios.refresh").pack(side="right")

        self._tr(ttk.Label(frame, foreground="#888", wraplength=680, justify="left"),
                 "scenarios.hint").pack(anchor="w", pady=(8, 0))

        self._scn_actions: list[dict] = []
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        """(Re)load the action list into the listbox, keeping the selection if possible."""
        prev = self._selected_action_name()
        self._scn_actions = list_actions()
        self._scn_list.delete(0, "end")
        for item in self._scn_actions:
            self._scn_list.insert("end", f"{item['title']}   ·   {item['name']}")
        if not self._scn_actions:
            self._log_put("[action] " + self._t("scenarios.empty"))
            return
        idx = next((i for i, a in enumerate(self._scn_actions) if a["name"] == prev), 0)
        self._scn_list.selection_clear(0, "end")
        self._scn_list.selection_set(idx)
        self._scn_list.see(idx)

    def _selected_action_name(self) -> str | None:
        sel = self._scn_list.curselection() if hasattr(self, "_scn_list") else ()
        if not sel:
            return None
        return self._scn_actions[sel[0]]["name"]

    def _run_selected_action(self) -> None:
        name = self._selected_action_name()
        if name is None:
            self._log_put("[action] " + self._t("scenarios.none_selected"))
            return
        self._run_md_action(name)

    def _run_md_action(self, name: str) -> None:
        """Run one action through the interpreter on a worker thread.

        Mirrors `_act`: a single `self._busy` guard serialises against nav/jump so two
        game-driving jobs never race on the daemon. The interpreter's on_event lines
        stream straight into the shared log via `_log_put`.
        """
        if self._busy:
            self._log_put("[action] " + self._t("busy"))
            return
        self._busy = True
        self._log_put(f"[action] {name}: {self._t('scenarios.running')}")

        def work() -> None:
            try:
                from lastwar_bot import script_engine
                # hwnd=0 → resolved lazily only if the action uses vision primitives.
                # profile=None → READ_TEXT actions raise clearly if run without one.
                script_engine.run_action(
                    name, hwnd=0,
                    on_event=lambda msg: self._log_put(f"[action] {msg}"),
                    profile=None,
                )
            except Exception as exc:                       # noqa: BLE001
                self._log_put(f"[action] {name}: error: {exc}")
            finally:
                self._busy = False
                self.after(400, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    def _toggle_scenario_loop(self) -> None:
        if self._scn_loop_var.get():
            self._start_scenario_loop()
        else:
            self._stop_scenario_loop()

    def _start_scenario_loop(self) -> None:
        name = self._selected_action_name()
        if name is None:
            self._scn_loop_var.set(False)
            self._log_put("[action] " + self._t("scenarios.none_selected"))
            return
        try:
            interval = max(5, int(self._scn_interval_var.get()))
        except ValueError:
            interval = 60
        self._scn_loop_stop.clear()
        self._log_put("[action] " + self._t("scenarios.loop_on", sec=interval))

        def loop() -> None:
            while not self._scn_loop_stop.is_set():
                self._run_md_action(name)
                # Wait out the interval, but also block while a run is still busy so
                # a slow action never overlaps its own next tick.
                self._scn_loop_stop.wait(interval)
                while self._busy and not self._scn_loop_stop.is_set():
                    self._scn_loop_stop.wait(0.5)

        self._scn_loop_thread = threading.Thread(target=loop, daemon=True)
        self._scn_loop_thread.start()

    def _stop_scenario_loop(self) -> None:
        stop = getattr(self, "_scn_loop_stop", None)
        if stop is None:
            return
        stop.set()
        if getattr(self, "_scn_loop_var", None) is not None:
            self._scn_loop_var.set(False)
        self._log_put("[action] " + self._t("scenarios.loop_off"))

    # -- chat tab -----------------------------------------------------------

    def _build_chat_tab(self, parent: ttk.Frame) -> None:
        """Build the Chat tab: monitor toggle + sub-tabs per chat type."""
        ctrl = ttk.Frame(parent, padding=(8, 6, 8, 4))
        ctrl.pack(fill="x")
        self._tr(ttk.Checkbutton(ctrl, variable=self._chat_var, command=self._toggle_chat),
                 "chat.monitor").pack(side="left")
        self._tr(ttk.Label(ctrl, foreground="#888", wraplength=500, justify="left"),
                 "chat.hint").pack(side="left", padx=(10, 0))

        sub_nb = ttk.Notebook(parent)
        sub_nb.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        for type_key in ("world", "alliance", "national", "dm", "other"):
            frame = ttk.Frame(sub_nb)
            sub_nb.add(frame, text=self._t(f"chat.tab.{type_key}"))
            _k = type_key  # capture for lambda
            self._tr_hooks.append(
                lambda nb=sub_nb, f=frame, k=_k: nb.tab(f, text=self._t(f"chat.tab.{k}"))
            )
            tree = self._make_chat_tree(frame)
            self._chat_trees[type_key] = tree
            self._chat_tree_rows[type_key] = 0

        bot = ttk.Frame(parent, padding=(6, 2, 6, 4))
        bot.pack(fill="x")
        self._tr(ttk.Button(bot, command=self._clear_chat),
                 "chat.clear").pack(side="left")
        self._chat_count_var = tk.StringVar(value=self._t("chat.count", n=0))
        ttk.Label(bot, textvariable=self._chat_count_var, foreground="#888").pack(
            side="right", padx=8)
        self._tr_hooks.append(self._retranslate_chat_bottom)

        self._pump_chat()

    def _retranslate_chat_bottom(self) -> None:
        """Re-apply translatable text in the chat bottom bar after a language change."""
        total = sum(len(v) for v in self._chat_msgs.values())
        self._chat_count_var.set(self._t("chat.count", n=total))

    def _make_chat_tree(self, parent: ttk.Frame) -> "tk.Text":
        """Build a read-only Text view for one chat type, with a scrollbar.

        A Text widget (not a Treeview) is used so emoji / sticker sprites can be
        drawn inline with the message text via ``image_create``.
        """
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        txt = tk.Text(frame, wrap="word", state="disabled", cursor="arrow",
                      font=("Segoe UI", 10), spacing1=1, spacing3=3,
                      borderwidth=0, highlightthickness=0, padx=6, pady=4)
        txt.tag_configure("time", foreground="#8a8a8a")
        txt.tag_configure("alliance", foreground="#2a6bd0")
        txt.tag_configure("nick", foreground="#333333")
        txt.tag_configure("mine", foreground="#2e7d32")
        txt.tag_configure("token", foreground="#6a4fb0")
        sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return txt

    def _chat_image(self, path: str, height: int):
        """Load (and cache) an inline sprite scaled to ``height`` px, or None."""
        key = (path, height)
        img = self._chat_img_cache.get(key)
        if img is not None:
            return img
        try:
            if _PIL_OK:
                im = _PILImage.open(path).convert("RGBA")
                w, h = im.size
                if h and h != height:
                    w = max(1, round(w * height / h))
                    im = im.resize((w, height), _PILImage.LANCZOS)
                img = _PILImageTk.PhotoImage(im)
            else:
                img = tk.PhotoImage(file=path)   # PNG, no scaling
        except Exception:       # noqa: BLE001
            return None
        self._chat_img_cache[key] = img
        return img

    @staticmethod
    def _chat_clear_view(view: "tk.Text") -> None:
        view.configure(state="normal")
        view.delete("1.0", "end")
        view.configure(state="disabled")

    def _render_msg_line(self, view: "tk.Text", record: dict) -> None:
        """Append one chat message as a line, with sprites drawn inline."""
        from datetime import datetime as _dt
        ts = record.get("ts", 0)
        t_str = _dt.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""
        alliance = (record.get("alliance") or "")[:12]
        nick = (record.get("sender_name") or "")[:30]
        nick_tag = "mine" if record.get("is_mine") else "nick"
        view.configure(state="normal")
        view.insert("end", (t_str + " ") if t_str else "", ("time",))
        if alliance:
            view.insert("end", f"[{alliance}] ", ("alliance",))
        view.insert("end", nick + ": ", (nick_tag,))
        uid = record.get("sender_uid") or ""
        for kind, val in chat_assets.segments((record.get("msg") or "")[:300]):
            if kind == "text":
                view.insert("end", val)
            elif kind == "token":
                # A photo token resolves to a JPG the client already cached on disk
                # (keyed by uid+picVer) -> render it; else a friendly placeholder.
                m = _PHOTO_TOK.match(val)
                path = chat_assets.photo_path(uid, m.group(1)) if m else None
                if path:
                    img = self._chat_image(path, 110)
                    if img is not None:
                        # Tag the image so a click opens it full-size (like the game).
                        tag = f"photo{self._photo_seq}"
                        self._photo_seq += 1
                        pos = view.index("end -1c")
                        view.image_create(pos, image=img)
                        view.tag_add(tag, pos, f"{pos} +1c")
                        pv = m.group(1)
                        view.tag_bind(tag, "<Button-1>",
                                      lambda e, u=uid, p=pv, f=path: self._open_photo(u, p, f))
                        view.tag_bind(tag, "<Enter>",
                                      lambda e, v=view: v.configure(cursor="hand2"))
                        view.tag_bind(tag, "<Leave>",
                                      lambda e, v=view: v.configure(cursor="arrow"))
                        continue
                view.insert("end", "🖼 фото" if m else val, ("token",))
            elif kind == "image":
                # stickers are bigger objects than inline emoji
                height = 56 if (os.sep + "sticker") in val else 18
                img = self._chat_image(val, height)
                if img is not None:
                    view.image_create("end", image=img)
                else:
                    view.insert("end", "[img]", ("token",))
        view.insert("end", "\n")
        view.configure(state="disabled")

    def _open_photo(self, uid: str, pic_ver: str, fallback: str) -> None:
        """Open a chat photo full-size in a popup, like tapping it in the game."""
        path = chat_assets.photo_path(uid, pic_ver, big=True) or fallback
        if not path or not os.path.isfile(path):
            return
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        max_w, max_h = int(sw * 0.85), int(sh * 0.85)
        try:
            if _PIL_OK:
                im = _PILImage.open(path).convert("RGBA")
                w, h = im.size
                # Fit within the screen; allow modest upscaling of small thumbnails.
                scale = min(max_w / w, max_h / h, 4.0)
                if abs(scale - 1.0) > 0.01:
                    im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                                   _PILImage.LANCZOS)
                photo = _PILImageTk.PhotoImage(im)
            else:
                photo = tk.PhotoImage(file=path)
        except Exception as exc:       # noqa: BLE001
            self._log_put(f"[chat] не удалось открыть фото: {exc}")
            return
        top = tk.Toplevel(self)
        top.title(self._t("tab.chat"))
        top.configure(background="#000000")
        lbl = tk.Label(top, image=photo, background="#000000", cursor="hand2")
        lbl.image = photo              # keep a reference alive
        lbl.pack()
        top.bind("<Button-1>", lambda e: top.destroy())
        top.bind("<Escape>", lambda e: top.destroy())
        top.update_idletasks()
        x = max(0, (sw - top.winfo_width()) // 2)
        y = max(0, (sh - top.winfo_height()) // 2)
        top.geometry(f"+{x}+{y}")
        top.transient(self)
        top.focus_set()

    def _pump_chat(self) -> None:
        """Drain the chat queue and refresh treeviews — scheduled every 1 s."""
        changed: set = set()
        try:
            while True:
                record = self._chat_q.get_nowait()
                chat_type = record.get("chat_type", "other")
                if chat_type not in self._chat_msgs:
                    chat_type = "other"
                msgs = self._chat_msgs[chat_type]
                # Order by the message's own serverTime (record["ts"]). The live
                # stream is already monotonic; only history re-parsed on scroll-up
                # arrives "from the past" -- resort and rebuild that tree then, so
                # old messages land in their proper place, not at the bottom.
                out_of_order = bool(msgs) and record.get("ts", 0) < msgs[-1].get("ts", 0)
                msgs.append(record)
                if out_of_order:
                    msgs.sort(key=lambda r: r.get("ts", 0))
                    self._chat_tree_rows[chat_type] = 0
                    view = self._chat_trees.get(chat_type)
                    if view is not None:
                        self._chat_clear_view(view)
                if len(msgs) > 500:
                    # Trim to the last 500 entries and force a full view rebuild.
                    msgs[:] = msgs[-500:]
                    self._chat_tree_rows[chat_type] = 0
                    view = self._chat_trees.get(chat_type)
                    if view is not None:
                        self._chat_clear_view(view)
                changed.add(chat_type)
        except queue.Empty:
            pass

        for chat_type in changed:
            self._update_chat_tree(chat_type)

        total = sum(len(v) for v in self._chat_msgs.values())
        self._chat_count_var.set(self._t("chat.count", n=total))
        self.after(1000, self._pump_chat)

    def _update_chat_tree(self, chat_type: str) -> None:
        """Append only the records not yet rendered into the view, and autoscroll."""
        view = self._chat_trees.get(chat_type)
        if view is None:
            return
        msgs = self._chat_msgs.get(chat_type, [])
        start = self._chat_tree_rows.get(chat_type, 0)
        for record in msgs[start:]:
            self._render_msg_line(view, record)
        self._chat_tree_rows[chat_type] = len(msgs)
        if len(msgs) > start:
            view.see("end")

    def _toggle_chat(self) -> None:
        if self._chat_var.get():
            self._start_chat()
        else:
            self._stop_chat()

    def _start_chat(self) -> None:
        if self._chat_proc is not None:
            return
        out = self._profiles.chat_log()
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
        except Exception:
            pass
        rel = os.path.relpath(out, REPO)
        self._log_put(f"[chat] старт чтения (Lua VM) → {rel}")
        self._log_put("[chat] нужен тёплый lua_daemon (окно чата открывать не нужно)")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            self._chat_proc = subprocess.Popen(
                [WIN_PYTHON, "-u", os.path.join(TOOLS, "chat_reader.py"),
                 "--seconds", "0", "--out", out],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=REPO,
                env=env, creationflags=NO_WINDOW)
        except Exception as exc:
            self._log_put(f"[chat] ошибка запуска: {exc}")
            self._chat_proc = None
            self._chat_var.set(False)
            return
        self._log_put(f"[chat] монитор запущен (pid {self._chat_proc.pid})")
        threading.Thread(target=self._chat_reader, args=(self._chat_proc,), daemon=True).start()

    def _chat_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                    if isinstance(record, dict):
                        self._chat_q.put(record)
                        self._append_chat(record)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        if self._chat_proc is proc:
            self._log_put("[chat] монитор завершён")
            self._chat_proc = None
            self.after(0, lambda: self._chat_var.set(False))

    def _append_chat(self, record: dict) -> None:
        """Persist one chat record to the active profile's chat_log.jsonl."""
        try:
            with open(self._profiles.chat_log(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _stop_chat(self) -> None:
        proc, self._chat_proc = self._chat_proc, None
        if proc is not None:
            self._log_put("[chat] стоп монитора")
            try:
                proc.terminate()
            except Exception:
                pass

    def _clear_chat(self) -> None:
        """Remove all in-memory chat messages and clear all views."""
        for chat_type in list(self._chat_msgs):
            self._chat_msgs[chat_type].clear()
            view = self._chat_trees.get(chat_type)
            if view is not None:
                self._chat_clear_view(view)
            self._chat_tree_rows[chat_type] = 0
        self._chat_count_var.set(self._t("chat.count", n=0))

    def _load_chat_history(self) -> None:
        """Load the last 500 records from the active profile's chat_log.jsonl.

        Called on startup and on profile switch. Clears the current in-memory
        state first, then repopulates from the file and rebuilds all treeviews.
        """
        # Clear current state
        for chat_type in list(self._chat_msgs):
            self._chat_msgs[chat_type].clear()
            view = self._chat_trees.get(chat_type)
            if view is not None:
                self._chat_clear_view(view)
            self._chat_tree_rows[chat_type] = 0

        path = self._profiles.chat_log()
        if not os.path.isfile(path):
            return

        raw_records: list = []
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if isinstance(rec, dict):
                            raw_records.append(rec)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            return

        for record in raw_records[-500:]:
            chat_type = record.get("chat_type", "other")
            if chat_type not in self._chat_msgs:
                chat_type = "other"
            self._chat_msgs[chat_type].append(record)

        for chat_type, msgs in self._chat_msgs.items():
            if msgs:
                self._update_chat_tree(chat_type)

        total = sum(len(v) for v in self._chat_msgs.values())
        self._chat_count_var.set(self._t("chat.count", n=total))
        if total:
            self._log_put(f"[chat] история загружена: {total} сообщений")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="panel", description="Last War control panel")
    parser.add_argument("--profile", metavar="NAME", default=None,
                        help="start with the named profile active (created if missing), "
                             "overriding the saved last-active profile")
    args = parser.parse_args(argv)
    # lua_daemon lives in tools/, the shared modules in tools/lib/ — look in both.
    for tool in ("lua_daemon.py", "lua_client.py", "lua_actions.py", "coords.py"):
        if not any(os.path.isfile(os.path.join(d, tool)) for d in (TOOLS, TOOLS_LIB)):
            print(f"tool not found: {tool}", file=sys.stderr)
    Panel(active_profile=args.profile).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
