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
    or secret_mission_capture.py) in the background and streams findings into the log, plus
    «Автолут ★» — a standing order that watches the capture's checkpoint and robs a starred
    task of the best level the moment one becomes raidable (tools/steal_secret_task.py).
  * Настройки — a page of sub-tabs (SETTINGS_TABS is the whole list; a tab with no builder
    yet shows a placeholder). «Авторалли» is the filled one: which squads may be sent to a
    rally, and the alliance-drill variant where each squad is out / in / leading and exactly
    one can carry the banner. Saved into the active profile as it changes; nothing reads it
    yet — actions/join_rally.md takes its squads as an argument.
  * Таймеры — a schedule: each listed errand (collect the base; donate to alliance tech and
    then claim the gifts) has a switch and a period, and runs itself once that long has
    passed since it last ran. Everything scheduled runs single-file on one worker thread
    fed by a queue — two errands due at the same moment take their turn instead of driving
    the game at once, and «Запустить» enqueues rather than starting a thread of its own.
    The list of errands, their switches and periods, and the clock that says when each last
    ran all belong to the ACTIVE PROFILE (its timers.json / timers_last_run.json), seeded
    from the template panel/timers.json — so two accounts keep two schedules, and both
    survive a restart (panel/timers.py).

All panel settings (language, checkboxes, filters, coordinates, monitor state) live in a named
*profile*; the switcher bar above the tabs creates / renames / deletes / selects one. Each profile
is a directory under panel/profiles/<name>/ holding config.json plus its own rally_log.jsonl,
secret_tasks_log.jsonl and timers.json; the active profile is remembered in panel/settings.json
(see panel/profile.py).
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
from . import timers as timersmod

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
import lua_trace        # noqa: E402  (RESTORE_CHUNK — unwrap tracer hooks after a hard Stop)
import run_notes        # noqa: E402  (keep/discard a sniffer run + its description)
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

# Auto-loot watcher (the «Автолут ★» checkbox in the secret-task block).
# Poll period of the capture checkpoint. Well under the capture's own tick
# (15 s by default), so a target is acted on the tick it appears; a poll is a
# small JSON parse off the Tk thread, so the cost of looking often is nil.
AUTOLOOT_POLL = 5.0
# Most targets handed to one robbery run — the day's whole budget, so a scan that
# happens to show several stars of the best level can spend it in one go.
AUTOLOOT_LIMIT = 5
# The day's robberies are spent: sleep instead of re-firing at every new star.
# Half an hour is short enough to pick the budget up soon after the daily reset
# without a human, and long enough to keep the log quiet overnight.
AUTOLOOT_SPENT_PAUSE = 1800.0

# Develop-tab sniffers. Absolute paths, resolved at launch, so the working
# directory the panel was started from is irrelevant.
#   * Traffic  — tools/lib/live_sniffer.py: raw live decode of the game protocol,
#     one line per command as it crosses the wire (see docs/research/protocol.md).
#   * Functions — tools/lua_trace.py: wraps every reachable Lua function and logs
#     EVERY call with its full argument list (per task #1060: the monkey-patch
#     tool is tools/lua_trace.py). It is kept safe by TRACE_FILTER, not by the
#     --dedup discovery mode: dedup keeps only the first call of each name, which
#     silently drops the second, third and fourth thing the player pressed.
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
# What the function tracer logs. A name matching ANY of these keywords is kept.
#
# `SFS` alone, deliberately. It covers the whole wire — `SFSNetwork.SendMessage`,
# `SFSObject.Put*`, `SFSArray.*`, `SFSBaseMessage.*` — and those fire only when a
# message is actually built, so a session costs a few hundred lines.
#
# Do NOT add `Manager` or `Util` here. The match is a plain substring against the
# full `table.fn` name, so `Manager` also catches `UIManager`, `UpdateManager` and
# `EventManager`, and `Util` catches `ProfilerUtil` — all of them per-frame. Tried
# once: one hospital session wrote 79887 lines, and since every child line is piped
# into the panel's own log widget, the panel froze. The game survived; the panel did
# not. Widening this costs the panel, not just the file.
TRACE_FILTER = "SFS"
# How long to wait for both sniffer halves to report "ready" before saying so in
# the log. Measured on this machine: capture is live ~1 s in, the Lua hooks
# ~2 s in with a warm daemon and noticeably later when it has to attach first —
# so the cap is generous, it only exists to break a silent wait.
SNIFF_READY_TIMEOUT = 25.0
# Pause between "the session is over" and the save/delete prompt, so the last
# lines of the killed children have travelled through their reader threads (the
# run file paths arrive that way) and the files are closed before the dialog
# offers to delete them.
SNIFF_FLUSH_MS = 600

# Directory holding the DSL action scripts the Scenarios tab lists and runs. Only the
# blessed (tested) actions live here; experimental ones sit in actions/dev/, which the
# non-recursive glob below deliberately skips, so the picker offers only what works.
ACTIONS_DIR = os.path.join(SRC, "lastwar_bot", "actions")
# The Settings page: one entry per sub-tab, in the order they appear. `builder` is
# the Panel method that fills the tab; None means "not written yet" and gets the
# placeholder. ADDING A TAB IS ADDING A LINE HERE plus its two locale strings —
# nothing else knows the list.
SETTINGS_TABS: tuple[tuple[str, str | None], ...] = (
    ("autorally", "_build_autorally_settings"),
    ("general", None),
    ("game", None),
)

# The squads the panel offers for a rally. The game's own squad slots are read
# live where they matter (the formation whose `index` is the slot, see
# tools/lib/lua_actions.py); this is only how many the page draws.
RALLY_SQUADS = (1, 2, 3, 4)

# The three states of a drill squad, in the order a click walks them.
DRILL_OFF, DRILL_ON, DRILL_FLAG = "", "on", "flag"
DRILL_MARKS = {DRILL_OFF: " ", DRILL_ON: "✓", DRILL_FLAG: "🚩"}

# How long the scenario editor waits after the last keystroke before writing the
# file. Long enough that a burst of typing is one write, short enough that a run
# started right after an edit reads what is on screen (and a run flushes first
# anyway, so this is about disk chatter, not correctness).
SCENARIO_SAVE_DELAY_MS = 1000
# Marks the row of the script that is running right now.
RUNNING_MARK = "▶"

# Actions that are runtime plumbing rather than user-facing scenarios — hidden from
# the picker even if present here. `watchdog` is ticked by the runner, not run by hand.
_HIDDEN_ACTIONS = frozenset({"watchdog"})


def _repo_rel(path: str) -> str:
    """A path as it reads in the log: relative to the repo, forward slashes.

    Falls back to the path itself for anything outside the repo (or on another
    drive, where relpath raises) — a display helper must never be the thing that
    breaks a dialog.
    """
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


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
        # Guards the flag above: buttons claim it on the Tk thread, the timer
        # scheduler from its own, so a plain read-then-set would let two recipes
        # into the game VM at once (see _claim_busy).
        self._busy_lock = threading.Lock()
        self._coord_seq = 0
        self._mon_proc = None
        self._rally_proc = None
        self._help_proc = None        # live auto-help watcher (push.al.help.new)
        self._autoloot_proc = None    # one auto-loot run at a time
        self._autoloot_stop = None    # threading.Event of the watcher loop, when running
        self._autoloot_seen: set = set()   # uuids already sent this session (no re-tries)
        self._autoloot_pause_until = 0.0   # wall clock the watcher may fire again at
        self._autoloot_warned = False      # "no checkpoint yet" is said once per run
        self._sniff_proc = None       # Develop: traffic sniffer
        self._trace_proc = None       # Develop: Lua-function tracer
        self._sniff_ready = {}        # per-half readiness: None pending / True / False
        self._sniff_t0 = 0.0          # when the pair was launched (for "ready in Ns")
        self._sniff_label = ""        # label typed at the start of the current session
        self._sniff_files = {}        # kind -> run file each child reported opening;
                                      # emptied by the save/delete prompt that closes
                                      # a session, which is what makes it fire once
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
        # Scheduled actions (panel/timers.py). The store is per profile, so it is
        # re-pointed on a switch; the scheduler itself is created here and only
        # started once the UI exists (_startup), because a fired timer logs.
        self._timer_store = timersmod.LastRunStore(self._profiles.timers_state())
        # WHICH timers exist comes from the PROFILE's own timers.json — not from
        # code: one account's schedule is not the other's. A profile that has none
        # yet is seeded from the template panel/timers.json.
        self._timer_catalogue = timersmod.default_catalogue()
        self._timer_vars: dict[str, dict] = {}   # name -> {"enabled": Var, "interval": Var}
        self._timer_rows: dict[str, dict] = {}   # name -> {"last": Label, "next": Label}
        self._load_timer_catalogue()
        self._timers = timersmod.TimerScheduler(
            store=self._timer_store,
            catalogue=lambda: self._timer_catalogue,
            config=self._timer_config,
            runner=self._run_timer_action,
            log=lambda key, **fmt: self._log_put("[timer] " + self._t(key, **fmt)),
            gate=self._timer_gate,
        )
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
        # The directory moved under the schedule's feet: re-point both files, or
        # the next run would write into a re-created old directory.
        self._timer_store.set_path(self._profiles.timers_state())
        self._reload_timers(quiet=True)
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
            "alliance_autohelp": self._help_var.get(),
            "secret_monitor": self._mon_var.get(),
            "autoloot": self._autoloot_var.get(),
            "chat_monitor": self._chat_var.get(),
            # Settings page -> «Авторалли»: which squads may be sent, and the
            # alliance-drill variant with its single banner-carrier.
            "autorally": self._autorally_config(),
            # The schedule is NOT here: a timer's switch and period live in the
            # profile's own timers.json beside its scenario, and when each last
            # ran in timers_last_run.json (see panel/timers.py).
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
            # Off by default: it answers on its own, so it is opted into, not out of.
            self._help_var.set(bool(s.get("alliance_autohelp", False)))
            self._mon_var.set(bool(s.get("secret_monitor", False)))
            self._autoloot_var.set(bool(s.get("autoloot", False)))
            self._chat_var.set(bool(s.get("chat_monitor", False)))
            self._apply_autorally_config(s.get("autorally"))
        finally:
            self._loading = False
        self._update_path_hints()

    def _install_autosave(self) -> None:
        """Persist to the active profile whenever any bound setting changes."""
        for var in (self._x_var, self._y_var, self._srv_var, self._star_var,
                    self._pending_var, self._can_loot_var, self._lvl_from_var,
                    self._lvl_to_var, self._rally_var, self._help_var, self._mon_var,
                    self._autoloot_var, self._chat_var,
                    self._drill_on_var, self._drill_banner_var,
                    *self._rally_squad_vars.values()):
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
        # Auto-help is per-profile too: a switch must not leave the previous
        # profile's watcher helping on this one's behalf.
        self._stop_help()
        if self._help_var.get():
            self._start_help()
        self._stop_monitor()
        if self._mon_var.get():
            self._start_monitor()
        # Auto-loot reads the *profile's* checkpoint, so a profile switch has to
        # bounce the watcher too — and clear the uuids it robbed under the old one.
        self._stop_autoloot()
        if self._autoloot_var.get():
            self._start_autoloot()
        self._stop_chat()
        if self._chat_var.get():
            self._start_chat()
        # The schedule belongs to the account: its timers, their switches and
        # periods, and the clock that says when each last ran. Re-read all of it,
        # or the profile just switched to would run the other one's errands and
        # look as freshly collected as it did.
        self._timer_store.set_path(self._profiles.timers_state())
        self._reload_timers(quiet=True)

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
        timers_tab = ttk.Frame(nb)
        settings_tab = ttk.Frame(nb)
        chat_tab = ttk.Frame(nb)
        nb.add(main, text=self._t("tab.main"))
        nb.add(scenarios, text=self._t("tab.scenarios"))
        nb.add(timers_tab, text=self._t("tab.timers"))
        nb.add(settings_tab, text=self._t("tab.settings"))
        nb.add(chat_tab, text=self._t("tab.chat"))
        self._tr_hooks.append(lambda: (nb.tab(main, text=self._t("tab.main")),
                                       nb.tab(scenarios, text=self._t("tab.scenarios")),
                                       nb.tab(timers_tab, text=self._t("tab.timers")),
                                       nb.tab(settings_tab, text=self._t("tab.settings")),
                                       nb.tab(chat_tab, text=self._t("tab.chat"))))
        self._build_scenarios_tab(scenarios)
        self._build_timers_tab(timers_tab)
        self._build_settings_tab(settings_tab)
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
        # Auto-loot: a standing order, not a press. While it is ticked the panel
        # watches the capture checkpoint and robs a starred task of the highest
        # level the moment one shows up — the scan only finds a raidable star for
        # as long as its loot window is open, so waiting for a human to notice
        # the log line and click was losing targets.
        # The «уровень до» entry to the left IS the level it robs — not a ceiling
        # over "whatever is lying around". «от 1 до 7» means 7s are taken and a
        # level-6 star waits, however alone it is on the map: the five daily
        # robberies are the scarce thing, and one spent on a 6 is one a 7 cannot
        # have until the reset (that is exactly what happened on 2026-07-29).
        # The star/PENDING/LOOTABLE checkboxes stay display-only — those decide
        # what is printed, and a display filter silently changing who gets raided
        # would be a nasty surprise.
        # Stars only: with no star at that level it robs nothing at all.
        self._autoloot_var = tk.BooleanVar(value=False)
        self._autoloot_chk = self._tr(ttk.Checkbutton(row2, variable=self._autoloot_var,
                                                      command=self._toggle_autoloot),
                                      "secret.autoloot")
        self._autoloot_chk.pack(side="right", padx=(8, 0))

        rally = self._tr(ttk.LabelFrame(main, padding=8), "rally.frame")
        rally.pack(fill="x", padx=8, pady=(0, 6))
        self._rally_var = tk.BooleanVar(value=True)
        self._tr(ttk.Checkbutton(rally, variable=self._rally_var, command=self._toggle_rally),
                 "rally.monitor").pack(side="left")
        # Hint shows the active profile's rally log; refreshed on language/profile change.
        self._rally_hint = ttk.Label(rally, foreground="#888")
        self._rally_hint.pack(side="left", padx=10)
        self._tr_hooks.append(self._update_path_hints)

        # Alliance auto-help: a standing order like «Автолут ★», but driven by the
        # wire instead of a poll — the request itself announces its arrival
        # (push.al.help.new), so there is nothing to poll for.
        ally = self._tr(ttk.LabelFrame(main, padding=8), "help.frame")
        ally.pack(fill="x", padx=8, pady=(0, 6))
        self._help_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(ally, variable=self._help_var, command=self._toggle_help),
                 "help.auto").pack(side="left")
        self._tr(ttk.Label(ally, foreground="#888"), "help.hint").pack(side="left", padx=10)

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
        if self._help_var.get():            # alliance auto-help, if the profile had it on
            self._start_help()
        if self._mon_var.get():             # secret-task monitor, if the profile had it on
            self._start_monitor()
        if self._autoloot_var.get():        # standing auto-loot order, if the profile had it on
            self._start_autoloot()
        if self._chat_var.get():            # chat monitor, if the profile had it on
            self._start_chat()
        self.after(0, self._load_chat_history)
        # The schedule runs whenever the panel is open: the thread is started
        # unconditionally and a tick with every row unticked costs one dict
        # comparison, which keeps switching a timer on a matter of the checkbox
        # alone (no start/stop plumbing to get out of step with it).
        self._timers.start()
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
        # Checkpoint what the capture currently sees into the profile, so the
        # auto-loot button has a machine-readable view of the map instead of the
        # log lines this panel prints for the human. Rewritten every tick; the
        # reader drops anything not re-seen in the scan window, so a stale file
        # cannot send a robbery at a tile that has already been taken.
        # Only for the secret-task capture: the ghost-recon one writes its own
        # record shape, and auto-loot must never be handed that by mistake.
        if script == CAPTURE_OPTIONS[0]["script"]:
            cmd += ["--json", self._profiles.tasks_json()]
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

    # -- alliance auto-help: answer push.al.help.new the moment it lands ------
    #
    # A standing order, not a press. An alliancemate's request pays help points only
    # while it is open, and the game announces it on the wire (`push.al.help.new`) —
    # so instead of a periodic sweep this keeps an ear on the traffic and fires the
    # one `al.help.all` that answers the whole list the second the push arrives.
    #
    # The listening and the pressing both live in the child
    # (tools/alliance_help_monitor.py): capture must run in the Windows Python, and
    # the press must not sit on the Tk thread. The panel only ticks the box, streams
    # the child's lines into the log, and remembers the choice per profile. The gate
    # («is anybody actually waiting») is the game's own — see
    # tools/lib/alliance_help.py and docs/research/alliance-help.md.
    def _toggle_help(self) -> None:
        if self._help_var.get():
            self._start_help()
        else:
            self._stop_help()

    def _start_help(self) -> None:
        if self._help_proc is not None:
            return
        self._log_put("[help] авто-помощь включена — слушаю push.al.help.new")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")   # utf-8 to match our decode
        try:
            self._help_proc = subprocess.Popen(
                [WIN_PYTHON, "-u", os.path.join(TOOLS, "alliance_help_monitor.py")],
                # no --all-tcp: auto-detect the narrow game port (see _start_monitor)
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=REPO,
                env=env, creationflags=NO_WINDOW)
        except Exception as exc:
            self._log_put(f"[help] ошибка запуска: {exc}")
            self._help_proc = None
            self._help_var.set(False)
            return
        threading.Thread(target=self._help_reader, args=(self._help_proc,),
                         daemon=True).start()

    def _help_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                self._log_put(f"[help] {raw.rstrip()}")
        except Exception:
            pass
        if self._help_proc is proc:      # ended on its own, not via _stop_help
            self._log_put("[help] авто-помощь остановлена (процесс завершился)")
            self._help_proc = None
            self.after(0, lambda: self._help_var.set(False))

    def _stop_help(self) -> None:
        proc, self._help_proc = self._help_proc, None
        if proc is not None:
            self._log_put("[help] авто-помощь выключена")
            try:
                proc.terminate()
            except Exception:
                pass

    # -- auto-loot: rob the best starred tasks the capture finds -------------
    #
    # One checkbox, one rule: **starred only, best level only**. The day's budget is
    # five robberies (`hero.dispatch.steal`), and a level-7 star pays several times
    # what a plain tile does — so spending an attempt on anything less is a loss that
    # cannot be taken back until the daily reset. With no star in the scan nothing
    # happens at all.
    #
    # It is a standing order rather than a press because a raidable star is a
    # perishable thing: the tile stops being raidable when its window closes or
    # someone else fills the third loot slot, so the gap between the capture
    # printing the finding and a human noticing it was where targets were lost.
    # While the box is ticked a watcher thread re-reads the capture checkpoint and
    # fires the moment the rule has a target.
    #
    # The decision and the robbery both go through `tools/steal_secret_task.py`
    # (`targets_from_scan` for "is there a target", `--from-scan … --star-max` for
    # the robbery itself), so the panel never grows a second copy of the rule. The
    # robbery runs as a child process (like the monitors) because it walks the Lua
    # daemon several times and must not sit on the Tk thread.
    # See docs/research/secret-task-steal.md.
    def _toggle_autoloot(self) -> None:
        if self._autoloot_var.get():
            self._start_autoloot()
        else:
            self._stop_autoloot()

    def _start_autoloot(self) -> None:
        if self._autoloot_stop is not None:      # already watching
            return
        self._autoloot_stop = threading.Event()
        self._autoloot_seen.clear()
        self._autoloot_pause_until = 0.0
        self._autoloot_warned = False
        self._log_put(f"[autoloot] включён — {self._autoloot_rule_text()}")
        if self._mon_proc is None:
            self._log_put("[autoloot] мониторинг секреток выключен: без него скан "
                          "не обновляется и целей не будет")
        threading.Thread(target=self._autoloot_loop, args=(self._autoloot_stop,),
                         daemon=True).start()

    def _stop_autoloot(self) -> None:
        stop, self._autoloot_stop = self._autoloot_stop, None
        if stop is not None:
            stop.set()
            self._log_put("[autoloot] выключен")

    def _autoloot_loop(self, stop: threading.Event) -> None:
        """Poll the capture checkpoint until the checkbox is cleared.

        A whole tick is wrapped in try/except: the watcher is a background loop the
        operator cannot see, so one unreadable checkpoint (caught half-written by the
        capture, say) must cost a log line and not the auto-loot for the session. The
        same complaint is printed once and not on every poll after it — a checkpoint
        that stays broken would otherwise fill the log a dozen times a minute.
        """
        last_err = ""
        while True:
            try:
                self._autoloot_tick()
                last_err = ""
            except Exception as exc:      # noqa: BLE001 — never let one tick kill the loop
                err = f"{type(exc).__name__}: {exc}"
                if err != last_err:
                    last_err = err
                    self._log_put(f"[autoloot] ошибка опроса скана: {err}")
            if stop.wait(AUTOLOOT_POLL):
                return

    def _autoloot_tick(self) -> None:
        """One look at the scan: fire when the rule has a target we have not sent yet."""
        if self._autoloot_proc is not None:          # a robbery is still running
            return
        if time.time() < self._autoloot_pause_until:  # the day's budget is spent
            return
        checkpoint = self._profiles.tasks_json()
        if not os.path.exists(checkpoint):
            if not self._autoloot_warned:            # say it once, not every poll
                self._autoloot_warned = True
                self._log_put("[autoloot] нет данных скана — включи «Мониторинг» "
                              "секреток и подвигай карту")
            return
        self._autoloot_warned = False
        targets = self._autoloot_targets(checkpoint)
        # Already-sent uuids are skipped: the checkpoint keeps showing a tile the
        # server refused (or that we robbed but whose loot count has not come back
        # in a scan yet), and re-firing at it would burn the day's budget on a
        # target that cannot pay. A fresh session forgets them again.
        fresh = [t for t in targets if t[0] not in self._autoloot_seen]
        if not fresh:
            return
        for _uuid, _srv, label in fresh:
            self._log_put(f"[autoloot] цель: {label}")
        # Mark *every* target of the rule, not just the fresh ones: the child gets
        # the same checkpoint and will attempt the whole list, so the panel must
        # not treat the rest as new the next time round.
        self._autoloot_seen.update(uuid for uuid, _srv, _label in targets)
        self._autoloot_run(checkpoint)

    def _autoloot_targets(self, checkpoint: str) -> list:
        """Star-max targets in the checkpoint right now, as (uuid, server, label).

        Pure file work — `targets_from_scan` parses the checkpoint and applies the
        freshness/raidability rules; it does not touch the game or the daemon, so it
        is safe to call from the watcher thread on every poll.
        """
        import steal_secret_task     # lazy: keeps panel start-up free of it
        lo, hi = self._autoloot_levels()
        return steal_secret_task.targets_from_scan(checkpoint, limit=AUTOLOOT_LIMIT,
                                                   star_max=True, level_min=lo,
                                                   level_max=hi, say=lambda _m: None)

    def _autoloot_levels(self) -> tuple:
        """The «уровень от / до» range as (min, max) ints, either end None if unset.

        Read live on every poll, like the display filters in `_task_passes`, so
        narrowing the range takes effect on the next tick instead of at the next
        tick of the checkbox. Anything that is not a number reads as "no bound" —
        a half-typed entry must not silently widen the gate to everything.
        """
        def bound(var) -> "int | None":
            raw = var.get().strip()
            return int(raw) if raw.isdigit() else None
        return bound(self._lvl_from_var), bound(self._lvl_to_var)

    def _autoloot_rule_text(self) -> str:
        """The standing order in one phrase — what it will rob, in the log's words.

        The rule is invisible otherwise, and an invisible rule is how a robbery
        got spent on a level-6 star: the operator must be able to read what the
        checkbox is about to do without opening the source.
        """
        lo, hi = self._autoloot_levels()
        if hi is not None:
            return self._t("secret.autoloot.rule_top", lvl=hi,
                           lo=lo if lo is not None else "—")
        return self._t("secret.autoloot.rule_found",
                       lo=lo if lo is not None else "—")

    def _autoloot_run(self, checkpoint: str) -> None:
        cmd = [WIN_PYTHON, "-u", os.path.join(TOOLS, "steal_secret_task.py"),
               "--from-scan", checkpoint, "--star-max", "--limit", str(AUTOLOOT_LIMIT)]
        # The child re-reads the checkpoint and re-applies the rule, so the range
        # has to travel with it: without these the watcher would agree to a
        # target inside the range and the child would then rob outside it.
        lo, hi = self._autoloot_levels()
        if lo is not None:
            cmd += ["--level-min", str(lo)]
        if hi is not None:
            cmd += ["--level-max", str(hi)]
        self._log_put(f"[autoloot] {self._autoloot_rule_text()} …")
        proc = self._spawn_sniffer(cmd, "autoloot")
        if proc is None:
            return
        self._autoloot_proc = proc
        threading.Thread(target=self._autoloot_reader, args=(proc,), daemon=True).start()

    def _autoloot_reader(self, proc) -> None:
        spent = False
        try:
            for raw in proc.stdout:
                ln = raw.rstrip()
                if not ln:
                    continue
                self._log_put(f"[autoloot] {ln}")
                # The child says so in words when there is nothing left to spend.
                if "robberies are spent" in ln or "robberies left today: 0" in ln:
                    spent = True
        except Exception:
            pass
        if spent:
            self._autoloot_pause_until = time.time() + AUTOLOOT_SPENT_PAUSE
            self._log_put("[autoloot] дневной лимит краж исчерпан — пауза %d мин "
                          "(после сброса продолжу сам)" % int(AUTOLOOT_SPENT_PAUSE // 60))
        if self._autoloot_proc is proc:
            self._autoloot_proc = None

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
        self._sniff_label = label
        self._sniff_files = {}

        self._log_put("[traffic] запуск сырого снифера трафика (live_sniffer.py) …")
        self._sniff_proc = self._spawn_sniffer(
            [WIN_PYTHON, "-u", TRAFFIC_SNIFFER] + label_args, "traffic")
        if self._sniff_proc is not None:
            self._sniff_ready["traffic"] = None
            self._log_put(f"[traffic] снифер запущен (pid {self._sniff_proc.pid}); "
                          f"вывод идёт в лог, запись — в results/traffic/")
            threading.Thread(target=self._sniff_reader, args=(self._sniff_proc,),
                             daemon=True).start()

        # NOT --dedup. That mode keeps only the FIRST call of each name, so a session
        # where somebody opens a window, picks an amount, confirms and later collects
        # lands in the file as one click and one message — the repeats are dropped at
        # write time and no amount of reading gets them back. Whoever presses the panel
        # button is recording what they did, not discovering which functions exist.
        # Every call is logged instead, kept safe by a narrow filter rather than by
        # throwing away repeats: TRACE_FILTER covers the wire (SFS*) and the code that
        # drives it (*Manager / *Util), while the UI redraw noise that actually floods
        # Player.log and freezes the game is left out.
        self._log_put(f"[trace] запуск трассировщика Lua-функций "
                      f"(lua_trace.py --filter {TRACE_FILTER}, без дедупа) …")
        self._trace_proc = self._spawn_sniffer(
            [WIN_PYTHON, "-u", FUNCTION_SNIFFER, "--filter", TRACE_FILTER] + label_args,
            "trace")
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

    def _note_run_file(self, kind: str, line: str, marker: str) -> None:
        """Remember the run file a child says it opened (`marker` precedes the path).

        The path is only ever announced in the child's own output, so this is
        where the session learns what it is recording — and the save/delete
        prompt at the end has nothing to offer without it.
        """
        _head, sep, path = _ANSI.sub("", line).partition(marker)
        path = path.strip()
        if sep and path:
            self._sniff_files[kind] = path

    def _sniff_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                self._log_put(f"[traffic] {line}")
                if line.startswith("transcript:"):
                    self._note_run_file("traffic", line, "transcript:")
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
                if "trace file:" in line:
                    self._note_run_file("trace", line, "trace file:")
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
            # Both children died on their own (the game restarted, tshark lost
            # the interface) — the session is over just as surely as after a
            # Stop, so it gets the same save/delete prompt. Whichever path runs
            # first empties _sniff_files, so the other one finds nothing to ask
            # about; both land on the Tk thread, so they cannot interleave.
            self.after(SNIFF_FLUSH_MS, self._finish_sniff_session)

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
            # proc.terminate() is TerminateProcess on Windows — a hard kill that
            # runs NEITHER the tracer's atexit handler NOR its finally block, so
            # the ~8700 Lua functions it wrapped stay live in the game VM. Every
            # wrapped call then keeps paying the logging-shim cost (pcall +
            # tostring + Debug.LogError), which is what lags the game after a
            # sniff (task #1086). The killed child cannot clean up after itself,
            # so unwrap the hooks from here, over the warm daemon. RESTORE_CHUNK
            # is idempotent — it reports "nothing installed" when the VM is
            # already clean — so a redundant call (e.g. the child DID exit
            # cleanly on its own) is harmless.
            threading.Thread(target=self._restore_trace_hooks, daemon=True).start()

        # Ask what this run was, once the killed children have let go of their
        # files. The delay is not about buffering (both write line-buffered) but
        # about the last lines still travelling through the reader threads — the
        # traffic child announces its transcript path early, the tracer's «trace
        # file:» line can still be in flight when a very short run is stopped.
        self.after(SNIFF_FLUSH_MS, self._finish_sniff_session)

    # -- end of a sniffer session: keep it with a description, or drop it ----
    def _finish_sniff_session(self) -> None:
        """Close the session out: prompt to keep (with a description) or delete.

        Runs once per session — it takes the recorded paths, so a second call
        (Stop and the children's own exit both lead here) finds nothing left.
        A session that opened no file at all is closed silently: there is
        nothing to describe and nothing to delete.
        """
        files, self._sniff_files = self._sniff_files, {}
        label, self._sniff_label = self._sniff_label, ""
        files = {k: p for k, p in files.items() if p and os.path.exists(p)}
        if not files:
            return
        seconds = max(0.0, time.time() - self._sniff_t0) if self._sniff_t0 else 0.0
        self._ask_run_outcome(files, label, seconds)

    def _ask_run_outcome(self, files: dict, label: str, seconds: float = 0.0) -> None:
        """The post-run dialog: a description field, Save and Delete.

        Both answers are worth having. A kept run needs the description — the
        two files say which Lua fired and what crossed the wire, never which
        buttons the operator pressed or what changed on screen, and that is the
        context the analysis starts from (docs/skills/sniff.md §8.4). A run that
        recorded the wrong thing is noise in a directory that is read by hand,
        so deleting it is one click rather than a shell detour.

        Closing the window with its X keeps the files: losing a recording must
        take a deliberate press, never a stray one.
        """
        paths = [files[k] for k in ("trace", "traffic") if k in files]
        win = tk.Toplevel(self)
        win.title(self._t("develop.run.title"))
        win.transient(self)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)

        shown = label.strip() or self._t("develop.run.nolabel")
        ttk.Label(frm, text=self._t("develop.run.header", label=shown),
                  font=("", 10, "bold")).pack(anchor="w")
        # What was actually recorded: how long, how much, and where it lies. The
        # counts are what tells a real run from an empty one — a transcript of
        # nothing but keepalives still weighs kilobytes.
        ttk.Label(frm, foreground="#888",
                  text=self._t("develop.run.duration",
                               sec=f"{seconds:.0f}")).pack(anchor="w")
        for kind in ("trace", "traffic"):
            path = files.get(kind)
            if path:
                ttk.Label(frm, foreground="#888",
                          text=self._run_file_caption(kind, path)).pack(anchor="w")
        ttk.Label(frm, text=self._t("develop.run.prompt"), wraplength=520,
                  justify="left").pack(anchor="w", pady=(10, 2))
        text = tk.Text(frm, height=4, width=64, wrap="word")
        text.pack(fill="both", expand=True)
        text.focus_set()

        # Placeholder: greyed prompt text that is NOT an answer. A widget-level
        # binding runs before the Text class binding that inserts the character,
        # so the first keypress empties the box and the typing lands in a clean
        # one. `showing` — not the widget's colour — is what `save()` trusts:
        # the placeholder must never be storable as a description.
        placeholder = self._t("develop.run.placeholder")
        showing = {"placeholder": True}
        text.insert("1.0", placeholder)
        text.configure(foreground="#888")

        def clear_placeholder(_event=None) -> None:
            if showing["placeholder"]:
                showing["placeholder"] = False
                text.delete("1.0", "end")
                text.configure(foreground="")

        text.bind("<Key>", clear_placeholder)
        text.bind("<Button-1>", clear_placeholder)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))

        def save() -> None:
            typed = text.get("1.0", "end").strip()
            description = "" if showing["placeholder"] or typed == placeholder else typed
            win.destroy()
            self._save_run_note(paths, label, description)

        def discard() -> None:
            if not messagebox.askyesno(self._t("develop.run.confirm_title"),
                                       self._t("develop.run.confirm", label=shown),
                                       parent=win):
                return
            win.destroy()
            gone = run_notes.discard_run(paths)
            self._log_put(f"[sniff] запись удалена ({len(gone)} файл(ов))")

        ttk.Button(btns, text=self._t("develop.run.discard"),
                   command=discard).pack(side="left")
        ttk.Button(btns, text=self._t("develop.run.save"),
                   command=save).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", save)
        win.bind("<Control-Return>", lambda e: save())
        win.grab_set()

    def _save_run_note(self, paths: list, label: str, description: str) -> None:
        """Keep the run; write the description beside every file of it."""
        if not description:
            self._log_put("[sniff] запись сохранена без описания — при анализе "
                          "придётся спрашивать, что делалось в игре")
            return
        try:
            written = run_notes.write_note(paths, description, label=label)
        except Exception as exc:      # noqa: BLE001  (a note must never break the panel)
            self._log_put(f"[sniff] описание не сохранено: {exc}")
            return
        names = ", ".join(_repo_rel(p) for p in written)
        self._log_put(f"[sniff] запись сохранена, описание → {names or '—'}")

    def _run_file_caption(self, kind: str, path: str) -> str:
        """One line of the dialog's info block: path, size and what is inside."""
        stats = run_notes.run_stats(path)
        size = stats["size"]
        human = f"{size / 1024:.0f} KB" if size >= 1024 else f"{size} B"
        return self._t(f"develop.run.file.{kind}", path=_repo_rel(path),
                       size=human, records=stats["records"])

    def _restore_trace_hooks(self) -> None:
        """Unwrap the lua_trace hooks left in the game VM after a hard Stop.

        Runs off the Tk thread: a restore round-trips the daemon and settles
        ~1.5 s. The tracer's own restore retries because the default (flood)
        mode can bury the confirmation line in Player.log; the panel only ever
        launches --dedup, which does not flood, so a couple of attempts suffice.
        get_evaluator() uses the warm daemon when it is up and falls back to a
        fresh local LuaEval otherwise, so this still works with no daemon as
        long as the game is alive (and if it is dead, there are no hooks to
        clear).
        """
        try:
            ev = lua_client.get_evaluator()
        except Exception as exc:      # noqa: BLE001
            self._log_put(f"[trace] снятие хуков: evaluator недоступен ({exc})")
            return
        try:
            for attempt in range(3):
                out = ev.run(lua_trace.RESTORE_CHUNK, marker="XSTRACE", settle=1.5 + attempt)
                if any("XSTRACE restored" in ln for ln in out):
                    self._log_put("[trace] хуки сняты: " + "; ".join(out))
                    return
            self._log_put("[trace] снятие хуков НЕ подтверждено за 3 попытки — "
                          "проверь игру (rerun tools/lua_trace.py или перезапуск)")
        except Exception as exc:      # noqa: BLE001  (teardown must never crash)
            self._log_put(f"[trace] ошибка снятия хуков: {exc}")
        finally:
            try:
                ev.close()
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
    # -- one game action at a time ------------------------------------------
    def _claim_busy(self) -> bool:
        """Take the "a game action is running" flag, or say it is already taken.

        Check-and-set under the lock: the panel's own buttons run on the Tk
        thread, but the timer scheduler runs on its own, and two threads that
        read the flag before either sets it would both proceed.
        """
        with self._busy_lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def _release_busy(self) -> None:
        with self._busy_lock:
            self._busy = False

    def _act(self, chunk: str, tag: str, label: str, settle: float = 1.2) -> None:
        if not self._claim_busy():
            self._log_put("[panel] занят — дождись завершения текущего действия")
            return
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
                self._release_busy()
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
        # A debounced edit is still pending for up to a second — write it before
        # the window goes, or the last thing typed is the thing that is lost.
        self._flush_scenario_save()
        self._stop_monitor()
        self._stop_autoloot()
        self._stop_rally()
        self._stop_help()
        self._stop_sniff()      # stops both the traffic sniffer and the tracer
        self._stop_chat()
        self._stop_scenario_loop()
        self._timers.stop()
        self.destroy()


    # -- scenarios tab (run .md action scripts) -----------------------------

    def _build_scenarios_tab(self, parent: ttk.Frame) -> None:
        """List the DSL action scripts, edit one, and run or loop it.

        Each `src/lastwar_bot/actions/*.md` is one runnable action. Run executes it
        once through the interpreter on a worker thread (output streams into the
        shared log); Repeat re-runs it on an interval until switched off. Game-VM
        actions (LUA/READ_LUA/GAME/JUMP) go through the Lua daemon and need no
        window; vision actions (FIND/CLICK) resolve the game window on demand.

        Selecting a row opens that script in the editor below, which writes itself
        back a second after the last keystroke — so a recipe is fixed and re-run
        without leaving the panel.

        While a run is in flight the list is locked and its row carries a marker:
        one script at a time, and it is visible WHICH one. Stop asks the
        interpreter to halt at its next step (a flag it checks between statements),
        rather than killing the thread in the middle of a call into the game.
        """
        self._scn_loop_stop = threading.Event()
        self._scn_loop_thread: threading.Thread | None = None
        # Which script is running right now, and the flag that asks it to stop.
        # Both live here rather than in the worker so the Stop button, the row
        # marker and the lock all read the same truth.
        self._scn_running: str | None = None
        self._scn_cancel: threading.Event | None = None
        # Editor state: which file is loaded (name and the path it came from —
        # the two are not interchangeable, a script may live in actions/dev/), and
        # the pending debounced save.
        self._scn_editor_name: str | None = None
        self._scn_editor_path: str | None = None
        self._scn_save_job = None
        self._scn_loading = False

        frame = self._tr(ttk.LabelFrame(parent, padding=8), "scenarios.actions")
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        listwrap = ttk.Frame(frame)
        listwrap.pack(fill="x")
        self._scn_list = tk.Listbox(listwrap, height=8, activestyle="dotbox",
                                    exportselection=False)
        scroll = ttk.Scrollbar(listwrap, orient="vertical", command=self._scn_list.yview)
        self._scn_list.configure(yscrollcommand=scroll.set)
        self._scn_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._scn_list.bind("<Double-Button-1>", lambda _e: self._run_selected_action())
        # Selecting a script opens it in the editor below.
        self._scn_list.bind("<<ListboxSelect>>", self._on_scenario_selected)

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(8, 0))
        self._scn_run_btn = self._tr(ttk.Button(controls, command=self._run_selected_action),
                                     "scenarios.run")
        self._scn_run_btn.pack(side="left", padx=(0, 4), ipady=2)
        # Stop is enabled only while a run is in flight; it asks the interpreter to
        # halt between steps rather than killing the thread mid-call.
        self._scn_stop_btn = self._tr(ttk.Button(controls, command=self._stop_scenario,
                                                 state="disabled"), "scenarios.stop")
        self._scn_stop_btn.pack(side="left", padx=(0, 4), ipady=2)
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

        # Arguments for the run — the script's own `ARGS` defaults fill in the rest.
        # JSON, because that is what a timer's `args` block is too, so a line that
        # works here can be pasted into timers.json unchanged.
        argrow = ttk.Frame(frame)
        argrow.pack(fill="x", pady=(6, 0))
        self._tr(ttk.Label(argrow), "scenarios.args").pack(side="left", padx=(0, 4))
        self._scn_args_var = tk.StringVar()
        ttk.Entry(argrow, textvariable=self._scn_args_var).pack(side="left", fill="x",
                                                                expand=True)

        # The editor. The selected script is loaded here and written back a second
        # after the last keystroke — no Save button to forget, and no write per
        # character either. Undo is Tk's own (`undo=True`), reset on every load so
        # Ctrl+Z can never reach back into the previously opened file.
        edit = self._tr(ttk.LabelFrame(frame, padding=4), "scenarios.editor")
        edit.pack(fill="both", expand=True, pady=(8, 0))
        self._scn_editor = scrolledtext.ScrolledText(
            edit, wrap="none", height=12, undo=True, autoseparators=True, maxundo=-1,
            font=("Consolas", 9))
        self._scn_editor.pack(fill="both", expand=True)
        self._scn_editor.bind("<<Modified>>", self._on_editor_modified)
        # Ctrl+Z / Ctrl+Y by physical key, so they work under a Cyrillic layout —
        # Tk's own <<Undo>> binding matches the Latin keysym only (same fix as the
        # log's copy, see _install_log_copy).
        self._scn_editor.bind("<Control-KeyPress>", self._on_editor_ctrl_key)

        self._tr(ttk.Label(frame, foreground="#888", wraplength=680, justify="left"),
                 "scenarios.hint").pack(anchor="w", pady=(8, 0))

        self._scn_actions: list[dict] = []
        self._refresh_actions()
        self._load_scenario_into_editor(self._selected_action_name())

    def _refresh_actions(self) -> None:
        """(Re)load the action list into the listbox, keeping the selection if possible."""
        prev = self._selected_action_name()
        self._scn_actions = list_actions()
        self._paint_action_rows()
        if not self._scn_actions:
            self._log_put("[action] " + self._t("scenarios.empty"))
            return
        idx = next((i for i, a in enumerate(self._scn_actions) if a["name"] == prev), 0)
        self._scn_list.selection_clear(0, "end")
        self._scn_list.selection_set(idx)
        self._scn_list.see(idx)

    def _paint_action_rows(self) -> None:
        """Rewrite every row, marking the one that is running.

        Done wholesale rather than in place because the marker changes a row's
        width; the list is briefly re-enabled because a disabled Listbox is the
        state it sits in for the whole run.
        """
        keep = self._scn_list.cget("state")
        sel = self._scn_list.curselection()
        self._scn_list.configure(state="normal")
        self._scn_list.delete(0, "end")
        for item in self._scn_actions:
            mark = RUNNING_MARK if item["name"] == self._scn_running else "   "
            self._scn_list.insert("end", f"{mark} {item['title']}   ·   {item['name']}")
        for idx in sel:
            self._scn_list.selection_set(idx)
        self._scn_list.configure(state=keep)

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
        args = self._scenario_args()
        if args is None:                      # unreadable JSON — already complained
            return
        self._run_md_action(name, args)

    def _scenario_args(self) -> dict | None:
        """What is typed in the «аргументы» box, as a dict. ``None`` = unusable.

        Empty means "no arguments", which is not the same as a typo: a script run
        with its defaults because the JSON did not parse would look like it worked,
        so a bad box refuses the run and says why.
        """
        raw = (self._scn_args_var.get() or "").strip()
        if not raw:
            return {}
        try:
            args = json.loads(raw)
        except ValueError as exc:
            self._log_put("[action] " + self._t("scenarios.bad_args", error=exc))
            return None
        if not isinstance(args, dict):
            self._log_put("[action] " + self._t("scenarios.bad_args",
                                                error="expected {\"name\": value}"))
            return None
        return args

    def _run_md_action(self, name: str, args: dict | None = None) -> None:
        """Run one action through the interpreter on a worker thread.

        Mirrors `_act`: a single `self._busy` guard serialises against nav/jump so two
        game-driving jobs never race on the daemon. The interpreter's on_event lines
        stream straight into the shared log via `_log_put`.

        `args` are the script's parameters: they fill in its `ARGS` declarations and
        are substituted for `{name}` in its text (see docs/dsl.md). Passing none runs
        the script on its own defaults.
        """
        # Whatever is being typed lands on disk before the run reads the file —
        # otherwise a change made a second ago would silently not be in the run.
        self._flush_scenario_save()
        if not self._claim_busy():
            self._log_put("[action] " + self._t("busy"))
            return
        shown = f"{name} {json.dumps(args, ensure_ascii=False)}" if args else name
        self._log_put(f"[action] {shown}: {self._t('scenarios.running')}")
        cancel = threading.Event()
        self._scn_cancel = cancel
        self._set_scenario_running(name)

        def work() -> None:
            try:
                from lastwar_bot import script_engine
                # hwnd=0 → resolved lazily only if the action uses vision primitives.
                # profile=None → READ_TEXT actions raise clearly if run without one.
                script_engine.run_action(
                    name, hwnd=0,
                    on_event=lambda msg: self._log_put(f"[action] {msg}"),
                    profile=None, variables=args, cancel=cancel,
                )
            except Exception as exc:                       # noqa: BLE001
                self._log_put(f"[action] {name}: error: {exc}")
            finally:
                self._release_busy()
                self._scn_cancel = None
                # Tk from a worker thread only through `after` — the marker, the
                # lock and the buttons are all widget state.
                self.after(0, lambda: self._set_scenario_running(None))
                self.after(400, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    def _set_scenario_running(self, name: str | None) -> None:
        """Lock the list and mark the running row — or undo both when it ends."""
        self._scn_running = name
        running = name is not None
        try:
            self._paint_action_rows()
            self._scn_list.configure(state="disabled" if running else "normal")
            self._scn_run_btn.configure(state="disabled" if running else "normal")
            self._scn_stop_btn.configure(state="normal" if running else "disabled")
        except tk.TclError:
            pass                            # the tab is gone (panel closing)

    def _stop_scenario(self) -> None:
        """«Стоп» — ask the running script to halt at its next step.

        Not a kill: the interpreter checks the flag between statements, between the
        presses of a repeat and between the polls of a WAIT, so the step in flight
        finishes and nothing is left half-sent to the game. A looping run is stopped
        too, or the loop would start the next pass a second later.
        """
        cancel = self._scn_cancel
        if cancel is None:
            return
        cancel.set()
        if getattr(self, "_scn_loop_var", None) is not None and self._scn_loop_var.get():
            self._stop_scenario_loop()
        self._log_put("[action] " + self._t("scenarios.stopping",
                                            name=self._scn_running or ""))

    # -- scenario editor ----------------------------------------------------

    def _on_scenario_selected(self, _event=None) -> None:
        """A row was clicked: put that script in the editor (saving the old one)."""
        name = self._selected_action_name()
        if name is None or name == self._scn_editor_name:
            return
        self._flush_scenario_save()         # never carry edits into another file
        self._load_scenario_into_editor(name)

    def _load_scenario_into_editor(self, name: str | None) -> None:
        """Read a script into the editor and start its undo history fresh."""
        if name is None:
            return
        from lastwar_bot import script_engine
        resolved = script_engine.resolve_action(name)
        if resolved is None:
            self._log_put(f"[action] {name}: not found")
            return
        path = str(resolved)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            self._log_put(f"[action] {name}: {exc}")
            return
        self._scn_loading = True            # the fill is not an edit to save back
        try:
            self._scn_editor.delete("1.0", "end")
            self._scn_editor.insert("1.0", text)
            # Reset AFTER the fill, or Ctrl+Z would undo its way back into whatever
            # file was open before this one.
            self._scn_editor.edit_reset()
            self._scn_editor.edit_modified(False)
        finally:
            self._scn_loading = False
        self._scn_editor_name = name
        self._scn_editor_path = path

    def _on_editor_modified(self, _event=None) -> None:
        """Tk's <<Modified>> fires once until reset — use it to debounce the save."""
        if not self._scn_editor.edit_modified():
            return
        self._scn_editor.edit_modified(False)
        if self._scn_loading or self._scn_editor_name is None:
            return
        self._schedule_scenario_save()

    def _schedule_scenario_save(self) -> None:
        """Write a second after the last keystroke, not on every character."""
        if self._scn_save_job is not None:
            try:
                self.after_cancel(self._scn_save_job)
            except tk.TclError:
                pass
        self._scn_save_job = self.after(SCENARIO_SAVE_DELAY_MS, self._save_scenario)

    def _flush_scenario_save(self) -> None:
        """Write a pending edit right now (before a run, or before another file)."""
        if self._scn_save_job is None:
            return
        try:
            self.after_cancel(self._scn_save_job)
        except tk.TclError:
            pass
        self._scn_save_job = None
        self._save_scenario()

    def _save_scenario(self) -> None:
        """Write the editor back to the file it was loaded from."""
        self._scn_save_job = None
        name, path = self._scn_editor_name, self._scn_editor_path
        if name is None or path is None:
            return
        text = self._scn_editor.get("1.0", "end-1c")
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except OSError as exc:
            self._log_put("[action] " + self._t("scenarios.save_failed",
                                                name=name, error=exc))
            return
        self._log_put("[action] " + self._t("scenarios.saved", name=name))

    def _on_editor_ctrl_key(self, event):
        """Undo / redo by physical key, so a Cyrillic layout works too."""
        keysym = (event.keysym or "").lower()
        if event.keycode == 90 or keysym in ("z", "cyrillic_ya"):
            try:
                self._scn_editor.edit_undo()
            except tk.TclError:
                pass                        # nothing left to undo
            return "break"
        if event.keycode == 89 or keysym in ("y", "cyrillic_en"):
            try:
                self._scn_editor.edit_redo()
            except tk.TclError:
                pass
            return "break"
        return None                         # other Ctrl+combos pass through

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
        args = self._scenario_args()
        if args is None:                      # unreadable JSON — already complained
            self._scn_loop_var.set(False)
            return
        try:
            interval = max(5, int(self._scn_interval_var.get()))
        except ValueError:
            interval = 60
        self._scn_loop_stop.clear()
        self._log_put("[action] " + self._t("scenarios.loop_on", sec=interval))

        def loop() -> None:
            while not self._scn_loop_stop.is_set():
                self._run_md_action(name, args)
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

    # -- timers tab (scheduled repeats of an action) ------------------------

    def _build_timers_tab(self, parent: ttk.Frame) -> None:
        """One row per configured errand: switch, period, when it last/next runs.

        The Scenarios tab's «Повтор» repeats *one selected* action for as long as
        the panel is open; a timer is the other half — several errands, each on
        its own clock, remembered across restarts (panel/timers.py). Nothing here
        drives the game directly: a row only edits the settings the scheduler
        thread reads on its next tick.

        WHICH rows exist is not decided here either — the list is read from the
        active profile's timers.json, so a new timer is a new entry in that file,
        every account keeps its own set, and «⟳» below re-reads it without
        restarting the panel.
        """
        frame = self._tr(ttk.LabelFrame(parent, padding=8), "timers.frame")
        frame.pack(fill="x", padx=8, pady=8)

        # Rebuilt wholesale by _reload_timers, so the rows live in their own
        # frame with nothing else in it.
        self._timer_grid = ttk.Frame(frame)
        self._timer_grid.pack(fill="x")
        self._fill_timer_grid()

        bottom = ttk.Frame(frame)
        bottom.pack(fill="x", pady=(8, 0))
        self._tr(ttk.Label(bottom, foreground="#888", wraplength=600, justify="left"),
                 "timers.hint").pack(side="left", anchor="w")
        self._tr(ttk.Button(bottom, width=3, command=self._reload_timers),
                 "timers.reload").pack(side="right", anchor="ne")

        self._refresh_timer_rows()

    def _fill_timer_grid(self) -> None:
        """(Re)draw a row per timer in the current catalogue."""
        grid = self._timer_grid
        for child in grid.winfo_children():
            child.destroy()
        self._timer_vars.clear()
        self._timer_rows.clear()
        grid.columnconfigure(0, weight=1)
        for col, key in enumerate(("timers.col.action", "timers.col.interval",
                                   "timers.col.last", "timers.col.next")):
            self._tr(ttk.Label(grid, foreground="#888"), key).grid(
                row=0, column=col, sticky="w", padx=(0, 10), pady=(0, 4))

        # The catalogue IS the settings now: its own enabled/interval_sec are
        # what the row shows, and what the row writes back to.
        config = self._timer_catalogue.default_config()
        for row, timer in enumerate(self._timer_catalogue, start=1):
            item = config[timer.name]
            enabled = tk.BooleanVar(value=bool(item["enabled"]))
            seconds = tk.StringVar(value=str(item["interval_sec"]))
            self._timer_vars[timer.name] = {"enabled": enabled, "interval": seconds}
            box = ttk.Checkbutton(grid, variable=enabled)
            # A configured `title` wins; a built-in falls back to its locale
            # string; a timer someone added to the JSON without either shows the
            # name it was given there.
            if timer.title:
                box.configure(text=timer.title)
            elif timer.label_key:
                self._tr(box, timer.label_key)
            else:
                box.configure(text=timer.name)
            box.grid(row=row, column=0, sticky="w", pady=2)
            ttk.Spinbox(grid, from_=timersmod.MIN_INTERVAL_SEC,
                        to=timersmod.MAX_INTERVAL_SEC, width=7,
                        textvariable=seconds).grid(row=row, column=1, sticky="w",
                                                   padx=(0, 10))
            last = ttk.Label(grid, foreground="#888", width=18)
            last.grid(row=row, column=2, sticky="w", padx=(0, 10))
            nxt = ttk.Label(grid, foreground="#888", width=18)
            nxt.grid(row=row, column=3, sticky="w", padx=(0, 10))
            self._tr(ttk.Button(grid, command=lambda t=timer: self._timer_run_now(t)),
                     "timers.run_now").grid(row=row, column=4, sticky="e")
            self._timer_rows[timer.name] = {"last": last, "next": nxt}
        self._bind_timer_autosave()

    def _bind_timer_autosave(self) -> None:
        """Persist a ticked box / retyped period, for rows built at any time.

        Called from the row builder rather than from `_install_autosave`, because
        the rows can be rebuilt at any moment by «⟳» or by a profile switch.
        """
        for var in self._timer_vars.values():
            var["enabled"].trace_add("write", lambda *a: self._save_timers())
            var["interval"].trace_add("write", lambda *a: self._save_timers())

    def _save_timers(self) -> None:
        """Write the ticked boxes and typed periods into the profile's timers.json.

        The scenario, the args and the title are left exactly as they were typed —
        the panel has no way to edit them and must not rewrite them.
        """
        if getattr(self, "_loading", False) or not self._timer_vars:
            return
        self._timer_catalogue = self._timer_catalogue.with_settings(self._timer_config())
        timersmod.save_catalogue(self._timer_catalogue, self._profiles.timers_json())

    def _reload_timers(self, quiet: bool = False) -> None:
        """Re-read the profile's timers.json and redraw the rows from it."""
        self._load_timer_catalogue()
        if hasattr(self, "_timer_grid"):
            self._fill_timer_grid()
        if not quiet:
            self._log_put("[timer] " + self._t("timers.log.reloaded",
                                               n=len(self._timer_catalogue)))

    def _load_timer_catalogue(self) -> None:
        """Read the active profile's catalogue, reporting what it made no sense of.

        Seeded from the template on a profile that has none yet, so a new account
        starts with the same schedule and can then diverge freely.
        """
        path = self._profiles.timers_json()
        self._timer_catalogue = timersmod.load_profile_catalogue(path)
        for problem in self._timer_catalogue.errors:
            self._log_put(f"[timer] {_repo_rel(path)}: {problem}")

    def _timer_config(self) -> dict:
        """The timers' settings as the scheduler wants them (read off the widgets).

        Read fresh on every tick, so ticking a box or changing a period applies at
        once — there is nothing to restart. Falls back to the saved config while
        the UI is still being built (the scheduler starts after it, but a manual
        run from a test double may not).
        """
        if not self._timer_vars:
            return self._timer_catalogue.default_config()
        raw = {}
        for name, var in self._timer_vars.items():
            raw[name] = {"enabled": bool(var["enabled"].get()),
                         "interval_sec": var["interval"].get()}
        return self._timer_catalogue.normalize_config(raw)

    def _timer_gate(self) -> str | None:
        """Why no timer may fire right now — or ``None`` to let the tick through.

        Only the game itself is a hard gate: a recipe fired at a closed client
        would fail, be recorded as a failure and sit out the retry hold for
        nothing. The daemon is not checked here — the runner starts it on demand,
        exactly like a button press does.
        """
        running, _text = game_status()
        return None if running else "timers.log.skip_game"

    def _run_timer_action(self, timer) -> bool:
        """Run one timer's scenario to completion. ``False`` = panel busy, later.

        Called on the scheduler thread, so it blocks there rather than spawning
        another: that is what keeps two due timers from pressing at once. Raises
        on a real failure — the scheduler turns that into a logged failure and a
        retry hold, and `last_run` is deliberately left where it was.

        A scenario of several steps (the alliance one is donate → gifts) runs
        under ONE claim on the busy flag and in ONE script context: nothing may
        slip between the halves, `args` and anything a step reads stay visible to
        the next one, and a failing step aborts the rest, so the retry replays the
        whole errand rather than half of it.

        A step is the name of an action script when one exists by that name, and
        otherwise DSL source run as it stands — which is what lets a timer in the
        JSON carry its commands inline.
        """
        if not self._claim_busy():
            return False
        try:
            if not lua_client.is_running() and not self._ensure_daemon():
                raise RuntimeError(self._t("timers.log.no_daemon"))
            from lastwar_bot import script_engine
            ctx = script_engine.new_context(
                hwnd=0,
                on_event=lambda msg: self._log_put(f"[timer] {timer.name}: {msg}"),
                variables=timer.args,
            )
            for step in timer.scenario:
                if script_engine.resolve_action(step) is not None:
                    ok = script_engine.run_action(step, hwnd=0, ctx=ctx)
                else:
                    ok = script_engine.run_text(step, ctx=ctx,
                                                label=step.splitlines()[0])
                if not ok:
                    raise RuntimeError(self._t("timers.log.step_failed", step=step))
            return True
        finally:
            self._release_busy()
            self.after(400, self._refresh_status)

    def _timer_run_now(self, timer) -> None:
        """The row's «Запустить» — put the errand on the schedule's own queue.

        Not a thread of its own: every timer script runs single-file on the one
        worker, so a press while another errand is running waits its turn behind
        it instead of driving the game at the same time. The call returns at once,
        so the button never blocks the UI.

        It also goes through the scheduler so a manual run restarts the period:
        pressing the button by hand *is* collecting the base, and the timer must
        not then collect it again a minute later.
        """
        if not self._timers.request(timer):
            self._log_put("[timer] " + self._t("timers.log.already_queued",
                                               name=timer.name))

    def _refresh_timer_rows(self) -> None:
        """Repaint the "last / next run" columns; re-armed once a second."""
        if self._timer_rows:
            config = self._timer_config()
            records = self._timer_store.records()
            now = time.time()
            for timer in self._timer_catalogue:
                row = self._timer_rows.get(timer.name)
                if row is None:
                    continue
                last = float((records.get(timer.name) or {}).get("last_run") or 0.0)
                row["last"].configure(
                    text=self._t("timers.never") if not last
                    else self._t("timers.ago", ago=self._fmt_span(now - last)))
                due = self._timer_catalogue.next_due(timer, config, records)
                if due is None:
                    row["next"].configure(text=self._t("timers.off"))
                elif due <= now:
                    row["next"].configure(text=self._t("timers.due_now"))
                else:
                    row["next"].configure(
                        text=self._t("timers.in_span", span=self._fmt_span(due - now)))
        self.after(1000, self._refresh_timer_rows)

    def _fmt_span(self, seconds: float) -> str:
        """A duration as the rows show it: «45 мин» / «2 ч 5 мин» / «3 дн»."""
        seconds = max(0, int(seconds))
        if seconds < 60:
            # "0 мин" reads like a stopped clock right after a run — say the
            # span is under a minute instead.
            return self._t("timers.span.now")
        if seconds < 3600:
            return self._t("timers.span.min", n=seconds // 60)
        if seconds < 86400:
            return self._t("timers.span.hour", h=seconds // 3600,
                           m=(seconds % 3600) // 60)
        return self._t("timers.span.day", d=seconds // 86400)

    # -- settings page (sub-tabs; SETTINGS_TABS is the whole list) -----------

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        """The Settings page: a Notebook whose tabs come from SETTINGS_TABS.

        A tab with no builder yet shows the placeholder, so the page is complete
        from the first day and filling one in is writing its builder — nothing
        here or in the tab bar has to change.
        """
        sub_nb = ttk.Notebook(parent)
        sub_nb.pack(fill="both", expand=True, padx=4, pady=4)

        for key, builder in SETTINGS_TABS:
            frame = ttk.Frame(sub_nb, padding=8)
            sub_nb.add(frame, text=self._t(f"settings.tab.{key}"))
            self._tr_hooks.append(
                lambda nb=sub_nb, f=frame, k=key: nb.tab(f, text=self._t(f"settings.tab.{k}"))
            )
            fill = getattr(self, builder) if builder else None
            if fill is None:
                self._tr(ttk.Label(frame, foreground="#888"),
                         "settings.placeholder").pack(anchor="w")
            else:
                fill(frame)

    # -- settings: auto-rally -----------------------------------------------

    def _build_autorally_settings(self, parent: ttk.Frame) -> None:
        """Which squads may be sent to a rally, and the alliance-drill variant.

        Two independent things share the page because they are the same decision
        asked twice. An ordinary rally only needs "which squads may go" — four
        plain checkboxes, saved as the list `[1, 3]`. The drill also needs to know
        WHO raises the banner, so each squad there has three states instead of two
        (out / in / in and leading) and only one of them can be the leader.

        Everything is written to the active profile the moment it changes; nothing
        reads it yet — the rally recipe takes its squads as an argument
        (`actions/join_rally.md`), and pointing it at this page is the next step.
        """
        rally = self._tr(ttk.LabelFrame(parent, padding=8), "autorally.frame")
        rally.pack(fill="x")
        self._tr(ttk.Label(rally), "autorally.squads").pack(side="left", padx=(0, 6))
        self._rally_squad_vars: dict[int, tk.BooleanVar] = {}
        for squad in RALLY_SQUADS:
            var = tk.BooleanVar(value=False)
            self._rally_squad_vars[squad] = var
            ttk.Checkbutton(rally, text=str(squad), variable=var).pack(side="left", padx=4)
        self._tr(ttk.Label(parent, foreground="#888", wraplength=620, justify="left"),
                 "autorally.hint").pack(anchor="w", pady=(4, 0))

        drill = self._tr(ttk.LabelFrame(parent, padding=8), "autorally.drill.frame")
        drill.pack(fill="x", pady=(10, 0))
        self._drill_on_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(drill, variable=self._drill_on_var),
                 "autorally.drill.enabled").pack(anchor="w")
        self._drill_banner_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(drill, variable=self._drill_banner_var),
                 "autorally.drill.banner").pack(anchor="w", pady=(2, 6))

        row = ttk.Frame(drill)
        row.pack(fill="x")
        self._tr(ttk.Label(row), "autorally.drill.squads").pack(side="left", padx=(0, 6))
        # Tri-state, so a checkbox will not do: each squad is a button whose text
        # is its state, and a click walks the states round.
        self._drill_state: dict[int, str] = {s: DRILL_OFF for s in RALLY_SQUADS}
        self._drill_buttons: dict[int, ttk.Button] = {}
        for squad in RALLY_SQUADS:
            btn = ttk.Button(row, width=5,
                             command=lambda s=squad: self._cycle_drill_squad(s))
            btn.pack(side="left", padx=3)
            self._drill_buttons[squad] = btn
        self._tr(ttk.Label(drill, foreground="#888", wraplength=620, justify="left"),
                 "autorally.drill.hint").pack(anchor="w", pady=(6, 0))
        self._paint_drill_squads()

    def _cycle_drill_squad(self, squad: int) -> None:
        """Walk one squad's state: out -> in -> leading -> out.

        `leading` is skipped when another squad already holds the banner, so a
        click can never quietly take it away from the squad the operator chose;
        clearing that one first is how it moves.
        """
        state = self._drill_state.get(squad, DRILL_OFF)
        if state == DRILL_OFF:
            self._drill_state[squad] = DRILL_ON
        elif state == DRILL_ON:
            taken = any(s != squad and st == DRILL_FLAG
                        for s, st in self._drill_state.items())
            self._drill_state[squad] = DRILL_OFF if taken else DRILL_FLAG
        else:
            self._drill_state[squad] = DRILL_OFF
        if self._drill_state[squad] == DRILL_FLAG:
            # One banner: whatever else claimed it stays in, just not leading.
            for other in self._drill_state:
                if other != squad and self._drill_state[other] == DRILL_FLAG:
                    self._drill_state[other] = DRILL_ON
        self._paint_drill_squads()
        self._save_settings()

    def _paint_drill_squads(self) -> None:
        """Redraw the four buttons from `_drill_state`."""
        for squad, btn in getattr(self, "_drill_buttons", {}).items():
            mark = DRILL_MARKS[self._drill_state.get(squad, DRILL_OFF)]
            try:
                btn.configure(text=f"{squad} {mark}")
            except tk.TclError:
                pass

    def _autorally_config(self) -> dict:
        """The page as it is stored: squad lists, not a widget per squad.

        `[1, 3]` says what it means to a reader of the config file, and survives
        the page offering a different number of squads later. The drill's leader
        is a separate field rather than a fourth list, because there is only ever
        one of it — and it is always also in `squads`.
        """
        drill_squads = [s for s in RALLY_SQUADS
                        if self._drill_state.get(s, DRILL_OFF) != DRILL_OFF]
        flagship = next((s for s in RALLY_SQUADS
                         if self._drill_state.get(s) == DRILL_FLAG), None)
        return {
            "squads": [s for s in RALLY_SQUADS if self._rally_squad_vars[s].get()],
            "drill": {
                "enabled": bool(self._drill_on_var.get()),
                "create_banner": bool(self._drill_banner_var.get()),
                "squads": drill_squads,
                "flagship": flagship,
            },
        }

    def _apply_autorally_config(self, raw) -> None:
        """Restore the page from a profile's saved block (anything odd -> off)."""
        raw = raw if isinstance(raw, dict) else {}
        squads = raw.get("squads")
        squads = squads if isinstance(squads, list) else []
        for squad, var in self._rally_squad_vars.items():
            var.set(squad in squads)

        drill = raw.get("drill")
        drill = drill if isinstance(drill, dict) else {}
        self._drill_on_var.set(bool(drill.get("enabled", False)))
        self._drill_banner_var.set(bool(drill.get("create_banner", False)))
        chosen = drill.get("squads")
        chosen = chosen if isinstance(chosen, list) else []
        flagship = drill.get("flagship")
        self._drill_state = {
            s: (DRILL_ON if s in chosen else DRILL_OFF) for s in RALLY_SQUADS
        }
        # The leader is only honoured if it is in the list at all, and only once —
        # a hand-edited config cannot end up with two banners.
        if flagship in self._drill_state and flagship in chosen:
            self._drill_state[flagship] = DRILL_FLAG
        self._paint_drill_squads()

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
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        if self._chat_proc is proc:
            self._log_put("[chat] монитор завершён")
            self._chat_proc = None
            self.after(0, lambda: self._chat_var.set(False))

    # chat_log.jsonl is written by chat_reader.py itself (`--out`), so the panel
    # does NOT append here: two processes appending to one file interleaved
    # their buffers, duplicating every record and corrupting utf-8 mid-line.

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

        # Older logs were appended by two processes at once (the panel and
        # `chat_reader --out`), so their buffers could interleave and split a
        # multi-byte character across a line boundary -- a strict utf-8 read
        # then died with UnicodeDecodeError on startup. Decode leniently: a
        # mangled line simply fails the json parse below and is skipped.
        raw_records: list = []
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
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

        # Same history: every message landed in the file twice (once per writer).
        # Drop repeats by the identity chat_reader itself dedupes on.
        seen: set = set()
        unique: list = []
        for rec in raw_records:
            key = (rec.get("room_id"), rec.get("seq_id"),
                   rec.get("sender_uid"), rec.get("msg"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(rec)
        raw_records = unique

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
