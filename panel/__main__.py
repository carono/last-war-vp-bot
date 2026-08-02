"""Last War control panel — navigation + secret-task monitoring (daemon-backed).

Actions run through the warm Lua daemon (tools/lua_daemon.py) so every button dispatches
in ~0.1 s instead of spawning a fresh process that re-resolves the il2cpp hijack (~5 s). The
panel auto-starts the daemon if it is not already running. In-game recipes live in
tools/lib/lua_actions.py (shared with the standalone scripts, so nothing drifts) and the
named presses `TAP` speaks in tools/lib/game_buttons.py.

Blocks:
  * Сводка — the account dashboard: the day's budgets and everything waiting for the
    person, polled off the warm daemon in ONE call every half-minute (panel/dashboard.py
    holds the list). It answers "does today need me at all" without opening a window.
  * Навигация — Домой / Мир (SceneUtils.ChangeToCity / ChangeToWorld) and a coordinate jump
    (X / Y / Сервер) with a history of where it has been. Same server -> in-server camera
    jump; a different server -> the cross-server load recipe. The server field defaults to
    the current server (DataCenter.WorldFavoDataManager.curServerId).
  * Секретные задания — a checkbox that runs the passive capture (tools/secret_task_capture.py
    or secret_mission_capture.py) in the background and streams findings into the log, plus
    «Автолут ★» — a standing order that watches the capture's checkpoint and robs a starred
    task of the best level the moment one becomes raidable (tools/steal_secret_task.py) —
    and «Автообъезд карты», which walks the camera over a box of tiles around the base so
    the passive capture has traffic to read without anybody dragging the map
    (panel/mapsweep.py decides where to look next).
  * Настройки — a page of sub-tabs (SETTINGS_TABS is the whole list). «Авторалли» says
    which squads may be sent to a rally, and the alliance-drill variant where each squad is
    out / in / leading and exactly one can carry the banner — and it IS what the rally
    recipe is handed now. «Общие» and «Игра» hold the knobs that used to be constants in
    this file: the Python that runs the children, the daemon port, the auto-loot budget,
    the log's retention cap, the game paths and the map-sweep box.
  * Таймеры — a schedule: each listed errand (collect the base; donate to alliance tech and
    then claim the gifts) has a switch and a period, and runs itself once that long has
    passed since it last ran. Rows are ADDED, COPIED, EDITED and DELETED from the tab
    itself — scenario steps, args and title included — so an unattended routine is built
    without leaving the panel. Everything scheduled runs single-file on one worker thread
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

Any coordinate printed in the log OR in a chat message — canonical `X:1 Y:2` / `#server X:1 Y:2`
(tools/lib/coords.py) or a free-form `(1,2)` / `1/2` / `координаты 1 2` / legacy `@[1,2]` — becomes
a clickable link that jumps there.

Every log line is stamped with the time it arrived, coloured by severity, and can be narrowed to
one producer; the widget keeps a bounded number of lines so an overnight session cannot grow it
until the panel crawls. The box under it takes one DSL line (`TAP collect_trucks xall`, `LUA …`,
`JUMP …`) through the same interpreter a recipe runs on, so all thirty-odd named presses are
reachable without authoring a file — «Справочник» beside it is the list of them.

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

import ctypes
import json
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__ as APP_VERSION
# Reusable tk/ttk helpers: a numeric-only entry/spinbox and a font-tuple builder.
# Stock widgets (Frame, Label, Button, Entry, Checkbutton, Combobox, Notebook,
# LabelFrame, Scrollbar, Text, Treeview, Spinbox, Listbox, Menu, PanedWindow)
# come straight from tk/ttk above.
from .widgets import NumericEntry, ScrollableFrame, numeric_spinbox, font as ui_font
from .splash import SplashScreen
from . import childmon as childmonmod
from . import dashboard as dashmod
from . import debug_log as dbgmod
from . import debug_sender as dbgsender
from . import i18n as i18nmod
from . import runtime
from . import mapsweep as mapsweepmod
from . import profile as profilemod
from . import chat_history as chathistmod
from . import tabs as tabsreg
from .tabs import rally as rallytab
from .tabs.rally import limits as rallygate

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
import chat_share       # noqa: E402  (self_profile -> the current player's uid, read live)
import game_buttons     # noqa: E402  (the named presses the reference pane lists)

try:
    from PIL import (Image as _PILImage, ImageTk as _PILImageTk,  # noqa: E402
                     ImageDraw as _PILImageDraw)
    _PIL_OK = True
except Exception:       # noqa: BLE001
    _PIL_OK = False

WIN_PYTHON = r"C:\Python312\python.exe"
DEFAULT_SERVER = str(lua_actions.HOME_SERVER)
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW
DETACHED = 0x00000008         # DETACHED_PROCESS
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PHOTO_TOK = re.compile(r"\[photo:(\d+)\]")

# -- the log widget ---------------------------------------------------------
# How many lines the widget keeps. An overnight session with a tracer running
# writes tens of thousands of them, and a Text widget that large makes every
# subsequent insert visibly slow — the panel froze once for exactly this reason.
# The on-disk mirror (panel.log) is NOT trimmed: the widget is a window onto the
# session, the file is the record.
LOG_MAX_LINES = 4000
# Trimming a line at a time would run on every insert; drop a block instead, so
# the cost is paid once every LOG_TRIM_BLOCK lines.
LOG_TRIM_BLOCK = 500
# Every producer that writes a `[tag]` into the log, in the order the filter
# offers them. Adding a producer without adding it here costs nothing — its lines
# are always shown, and only "show just this one" cannot single it out.
LOG_TAGS = ("panel", "action", "timer", "trigger", "secret", "autoloot", "ghost",
            "sweep", "rally", "help", "chat", "coord", "scene", "server", "game",
            "daemon", "profile", "traffic", "trace", "sniff", "dash", "cmd",
            "debug")
# The filter's "show everything" entry. A sentinel rather than the empty string so
# the combobox has something to display.
LOG_FILTER_ALL = "*"
# Severity colours, on the log's dark background.
LOG_COLOURS = {"sev_error": "#ff6b6b", "sev_warn": "#e8c069", "sev_ok": "#7bd88f",
               "stamp": "#6a6a6a"}
# How much of the main tab the log keeps when the panel places the sash itself:
# the control blocks above it are given the height they ask for, but never so much
# that the log below is left with nothing to show.
LOG_MIN_HEIGHT = 150
# Severity colouring and the producer tag both live in panel/runtime/log.py now — the
# classifier and the word lists belong with the sink that applies them, and a tab
# launched on its own colours its lines by the very same rules.
LOG_SEVERITY_WORDS = runtime.log.SEVERITY_WORDS

# -- the boot ---------------------------------------------------------------
# How long the splash may hold the window back while the systems come up. Longer
# than a healthy boot needs and longer than `_ensure_daemon`'s own wait, so the
# ceiling is only ever reached when something is genuinely stuck; past it the panel
# opens and says so, because a half-started system is still a usable panel and a
# window that never appears is not.
BOOT_MAX_WAIT_SEC = 75.0

# -- the health snapshot ----------------------------------------------------
# The panel is meant to stay open for days, so the things that could grow without
# bound are counted into the debug log on this period: pending `after` callbacks,
# live threads, the retranslation registry, the tag tables of the text widgets. A
# slow-down reported a week from now is then a question the log can answer instead
# of one that has to be reproduced.
HEALTH_SNAPSHOT_MS = 300_000

# -- liveness ---------------------------------------------------------------
# How often the status row re-reads the game and the daemon. A process-list scan
# costs a few milliseconds off the Tk thread, so looking often is free — and
# without it the panel sat for an hour showing "running (pid …)" over a client
# that had crashed, every timer tick failing into the retry hold.
STATUS_POLL_MS = 8000
# How long the game must read as gone before the watchdog relaunches it. Two
# polls, so a single scan that raced the process table (or a client restarting
# itself after the first login — it does that once) is not a crash.
WATCHDOG_STRIKES = 2
# Least time between two watchdog relaunches. A client that dies on startup would
# otherwise be relaunched every eight seconds forever.
WATCHDOG_COOLDOWN_SEC = 300.0

# How quiet the window size has to go before the window is painted again after a
# drag (see Panel._install_resize_damper). Long enough that the pauses inside a
# drag do not each cost a full repaint, short enough that letting go of the frame
# reads as instant. WM_SETREDRAW is the Windows message that turns painting off
# and on again; RedrawWindow's flags are INVALIDATE | ERASE | ALLCHILDREN | FRAME,
# i.e. "repaint the lot, title bar included".
RESIZE_SETTLE_MS = 160
WM_SETREDRAW = 0x000B
RDW_REPAINT_ALL = 0x0001 | 0x0004 | 0x0080 | 0x0400

# -- the account dashboard --------------------------------------------------
# How often the strip is re-read. One game-VM call for all of it (panel/dashboard.py
# builds the single chunk), so the cost is a round trip; half a minute is well
# inside the pace at which any of these numbers actually changes.
DASH_POLL_SEC = 30.0

# The Python that runs every child (captures, robberies, the daemon). A constant
# no longer: it is a profile setting whose default this is, so a machine with
# Python somewhere else is a field to edit rather than a source change.
DEFAULT_WIN_PYTHON = WIN_PYTHON

# Game lifecycle (paths derived from %LOCALAPPDATA%, no hardcoded username)
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
GAME_DIR = os.path.join(_LOCALAPPDATA, "FunFly", "Last War-Survival Game")
LAUNCHER = os.path.join(GAME_DIR, "LastWarLauncher.exe")
GAME_EXE = "LastWar.exe"

# Capture options: a stable i18n key (combobox label) paired with its capture script.
# The selected script is resolved by combobox index, so the visible label can be
# translated freely without breaking the lookup.
# The captures the monitor offers — data, in panel/runtime/captures.py, so the tab that
# draws the combo can simply import it (it used to be handed the list off the app
# instance, because this file cannot be imported from a tab).
CAPTURE_OPTIONS = runtime.CAPTURE_OPTIONS

# Auto-loot watcher (the «Автолут ★» checkbox in the secret-task block).
# All three are DEFAULTS now, not constants: the Settings → «Общие» page writes
# them per profile and the code reads them through `_opt_*`. They stay here
# because a profile that has never been to that page must still behave exactly
# as it did, and because this is where the reasoning belongs.
#
# Poll period of the auto-loot sources. Since #1124 the primary source is the live
# game VM (read through the warm daemon), which is always current — so this period is
# the whole reaction latency for a newly-raidable star, not a fraction of a slower
# capture tick. Kept tight (2 s) so the bot reaches a fresh target well before a human
# reading the same line in the log could jump to it and press. Each poll is one cheap
# daemon read (only the handful of currently-raidable tiles come back) plus a small
# JSON parse, both off the Tk thread; the read is skipped while the panel is busy
# navigating so it never contends with a jump.
AUTOLOOT_POLL = 2.0
# Most targets handed to one robbery run — the day's whole budget, so a scan that
# happens to show several stars of the best level can spend it in one go.
AUTOLOOT_LIMIT = 5
# The day's robberies are spent: sleep instead of re-firing at every new star.
# Half an hour is short enough to pick the budget up soon after the daily reset
# without a human, and long enough to keep the log quiet overnight.
AUTOLOOT_SPENT_PAUSE = 1800.0

# «Операция Призрак» standing order. Slower than the secret-task poll on purpose:
# its targets are read off the client's own task list (no capture, no map panning),
# a squad's loot window is minutes rather than seconds, and the event runs ONE day a
# week — so a minute between looks is plenty.
GHOST_POLL = 60.0
# The event is not running today: look again in an hour instead of every minute. Six
# days out of seven this is the branch that runs, and it should cost nothing.
GHOST_CLOSED_PAUSE = 3600.0

# Develop-tab sniffers. Absolute paths, resolved at launch, so the working
# directory the panel was started from is irrelevant.
#   * Traffic  — tools/lib/live_sniffer.py: raw live decode of the game protocol,
#     one line per command as it crosses the wire (see docs/research/protocol.md).
#   * Functions — tools/lua_trace.py: wraps every reachable Lua function and logs
#     EVERY call with its full argument list (per task #1060: the monkey-patch
#     tool is tools/lua_trace.py). It runs UNFILTERED so the recording on disk is
#     complete — a capture filter used to trim the file to the wire and hide every
#     UI/Manager call, the blind spot behind more than one wrong analysis. --dedup
#     is not used either: it keeps only the first call of each name, silently
#     dropping the second, third and fourth thing the player pressed. TRACE_FILTER
#     lives on only as the panel LOG's display filter (`_trace_show`), so an
#     unfiltered recording cannot flood the Tk widget.
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
# DISPLAY filter for the panel's own trace log — NOT a capture filter. The tracer
# child (tools/lua_trace.py) now runs UNFILTERED, so its recording on disk
# (results/traces/*_trace.log) holds every call: a filter that trimmed the file
# hid the very client-side calls a trace analysis needs (a run written with
# `filter=SFS` never showed a single UI/Manager call, which is exactly the blind
# spot that made past analyses wrong). The file must be complete.
#
# What this string still does: keep the PANEL's log widget readable. Every child
# line is piped into that Tk widget, and an unfiltered trace is tens of thousands of
# lines a second — enough to freeze the panel (not the game, which survives). So the
# reader (`_trace_show`) shows only the `XSCALL` lines whose name matches one of
# these keywords; status/marker lines always show, and the file is untouched either
# way. `SFS` covers the whole wire (`SFSNetwork.*`, `SFSObject.Put*`, …). Widening it
# here only shows MORE of what is already on disk — it costs the panel log's
# readability, never the recording.
#
# The game-side flood is handled by the tracer itself, not by this filter: in broad
# mode (which is how the panel runs it) tools/lua_trace.py drops the per-frame noise
# at wrap time — metamethods (`__index`/`__tostring`) and Unity value types
# (`Vector3`, …), the 100%-of-127145-lines flood that froze the game in #1128 — while
# keeping SFS / UI / Manager. So a complete recording no longer costs the client a
# freeze; widen `--exclude` there if a new value type shows up.
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

# How long the panel waits for the tracer to stop on its own after dropping the
# --stop-flag, before hard-killing it (task #1084). The tail loop sleeps 0.3s, so
# ~1.5s leaves room for a couple of passes plus its restore round-trip; longer only
# delays the Stop when the child is wedged.
TRACE_GRACEFUL_SEC = 1.5

# Where the DSL action scripts live — the runtime's constant now, re-exported because
# this file's callers (and the tests) reach for it by the old name.
ACTIONS_DIR = runtime.ACTIONS_DIR
# The Settings page: one entry per sub-tab THE SHELL owns, in the order they appear.
# `builder` is the Panel method that fills the tab; None means "not written yet" and
# gets the placeholder.
#
# It is no longer the whole page. A tab contributes its own page by declaring
# `SETTINGS_PAGE_KEY` and implementing `settings_page` (docs/research/
# panel-tabs-refactor.md §6), and those are appended after these — «Авторалли» is the
# rally tab's now, so switching rally off takes its settings with it.
SETTINGS_TABS: tuple[tuple[str, str | None], ...] = (
    ("general", "_build_general_settings"),
    ("game", "_build_game_settings"),
)

# Every knob the Settings page owns, with the value a profile that has never been
# there behaves by. The panel reads them through `_opt_*`, so a default here IS the
# old constant and nothing changes for an existing profile.
#
# `daemon_port` is the one with teeth: a second client lives in its own Windows
# session with its own daemon on its own port (tools/rdp_instance.py), so a profile
# that names 47655 drives THAT client — the panel's own DaemonClient and every child
# it launches (which read LW_DAEMON_PORT from the environment). That is what turns
# "two profiles" into "two accounts farmed at once".
def _settings_var(master, default):
    """One Tk variable per Settings knob — a checkbox for a bool, a box for the rest."""
    return (tk.BooleanVar(master=master, value=bool(default)) if isinstance(default, bool)
            else tk.StringVar(master=master, value=str(default)))


SETTINGS_DEFAULTS: dict = {
    "win_python": DEFAULT_WIN_PYTHON,
    "daemon_port": lua_client.DEFAULT_PORT,
    "log_max_lines": LOG_MAX_LINES,
    "autoloot_limit": AUTOLOOT_LIMIT,
    "autoloot_poll": AUTOLOOT_POLL,
    "autoloot_pause_min": int(AUTOLOOT_SPENT_PAUSE // 60),
    "trace_filter": TRACE_FILTER,
    "sniff_ready_timeout": SNIFF_READY_TIMEOUT,
    "launcher": LAUNCHER,
    "game_exe": GAME_EXE,
    "watchdog": False,
    "sweep_radius": mapsweepmod.DEFAULT_RADIUS,
    "sweep_step": mapsweepmod.DEFAULT_STEP,
    "sweep_dwell": mapsweepmod.DEFAULT_DWELL,
    "sweep_rest_min": 5,           # pause between two full passes, minutes
    # Where «Отправить диагностику» ships the zipped debug logs (panel/debug_sender.py).
    # Empty = do not send: the archive is still written, but nothing leaves the box.
    # A stub for now — no transport is wired. The rotating debug log itself is not
    # configured here: it is a fixed 5 MiB × 3 (panel/debug_log.py).
    "debug_send_url": "",
}

# The chat sub-tabs, in order. `system` is on the list: `_chat_msgs` always carried
# the bucket, so those messages were counted and never shown anywhere.
CHAT_TABS: tuple[str, ...] = ("world", "alliance", "national", "dm", "other", "system")

# Lazy-load: chat history lives in the per-profile SQLite store; only the newest
# CHAT_PAGE of a tab is read into memory and rendered at startup, and a scroll to the
# top pages the next CHAT_PAGE in from the store. CHAT_MSGS_MAX caps the in-memory
# (rendered) list so a marathon live session cannot grow it without bound — overflow
# is dropped from the front but stays in the store, reachable again by scrolling up.
CHAT_PAGE = 100
CHAT_MSGS_MAX = 2000
# Inline pictures — one Tk image per distinct (file, size): every sender's avatar
# and every photo posted. Kept as an LRU of this many, because they are live Tk
# objects and world chat walks past a new sender every few seconds; what falls out
# is history far above the viewport, which redraws its picture if it is scrolled
# back to.
CHAT_IMG_CACHE_MAX = 1500

# The retranslation registry's sweep threshold — the runtime owns it now
# (panel/runtime/i18n.py). Re-exported under the old name because that is what the
# panel's own tests reach for.
TR_REGISTRY_SWEEP = runtime.i18n.REGISTRY_SWEEP

# How long the daemon holds this panel's claim on the game without hearing from it
# (tools/lib/game_lease.py). Every chunk the action runs renews it, so this only ever
# fires for a panel that died mid-action — and then the next window may take the game
# instead of finding it wedged until somebody restarts the daemon.
LEASE_TTL_SEC = 120

# The rally squads, the elite level a created rally targets and the drill's three
# states went with the «Ралли» tab (panel/tabs/rally/) — the page that draws them is
# the one the tab contributes to Settings.

# How long the scenario editor waits after the last keystroke before writing the
# file. Long enough that a burst of typing is one write, short enough that a run
# started right after an edit reads what is on screen (and a run flushes first
# anyway, so this is about disk chatter, not correctness).
SCENARIO_SAVE_DELAY_MS = 1000
# A path as it reads in the log — relative to the repo, forward slashes. The runtime
# owns it now (panel/runtime/paths.py): a tab launched on its own shows a path too.
_repo_rel = runtime.paths.repo_rel


# The action catalogue — which scripts exist and what each is called — is the
# runtime's (panel/runtime/actions.py): the Scenarios tab lists them and a tab
# launched on its own has no panel to ask. Re-exported under the old names.
list_actions = runtime.list_actions


# Whether the client is running, and what it is connected to — the runtime owns the
# probe now (panel/runtime/game_process.py), because a tab launched on its own has to
# be able to ask too. Re-exported under the old names: this file's callers, and the
# tests that borrow them, do not care where the psutil call lives.
game_status = runtime.game_process.status


class Panel(tk.Tk):
    def __init__(self, active_profile: str | None = None) -> None:
        super().__init__()
        # THE RUNTIME (panel/runtime/): the profile and its settings, the translator,
        # the log sink, the tick, the child factory, the link to the game and the
        # action runner. A tab launched on its own builds the very same object around
        # a bare root — which is what makes it launchable at all.
        #
        # An explicit --profile overrides the saved last-active profile, creating it
        # on the fly if it does not exist yet.
        profiles = profilemod.ProfileManager()
        if active_profile:
            profiles.set_active(active_profile)
        self._rt = runtime.PanelRuntime(self, profiles=profiles,
                                        defaults=SETTINGS_DEFAULTS,
                                        daemon_state=self._daemon_state)
        # The names the rest of this file (and the tests that borrow its methods)
        # already use, pointing at the runtime's own pieces.
        self._profiles = self._rt.profiles
        self._binder = self._rt.settings
        self._i18n = self._rt.i18n
        self._logbus = self._rt.log
        self._tick = self._rt.tick
        self._children = self._rt.children
        self._game = self._rt.game
        # An action letting go of the game is when the status strip is stale — the link
        # says so, and only a window that HAS a strip does anything about it.
        self._game.on_settled = lambda: self.after(400, self._refresh_status)
        self._actions = self._rt.actions
        self._binder.loading = True   # suppresses auto-save while we apply settings
        self.title(self._t("app.title"))
        self.geometry("760x600")
        self.minsize(640, 500)
        # Hide the main window and put a splash up while the systems come online;
        # `_startup` finishes wiring the live game link in the background. A splash
        # must never be the reason the panel fails to open, so it is best-effort.
        self.withdraw()
        self._splash = None
        try:
            self._splash = SplashScreen(self, subtitle=self._t("about.name"))
        except Exception:             # noqa: BLE001
            self._splash = None
        self._splash_step("splash.profile", 0.12)
        # Everything the panel says goes through one sink (panel/runtime/log.py): the
        # queue this window drains, the profile's panel.log, and the debug log. The
        # WIDGET is this shell's — a tab launched on its own has none, and says the
        # same lines into the same two files.
        self._log = None              # the widget, built by _build_ui
        self._log_lines = 0           # lines in the widget, for the retention cap
        self._log_kept: list = []     # every line this session, for a filter redraw
        # Technical debug log (panel/debug_log.py): a rotating file, one per profile,
        # kept apart from panel.log and the UI widget. Pointed at the active profile
        # here — before any _log_put — so the very first line and any start-up
        # traceback already land in it. Two component loggers: `panel` for lifecycle
        # and errors, `ui` for the mirror of every widget line. _dbg_status_prev
        # remembers the last systems snapshot so only transitions are logged at INFO.
        self._configure_debug_log()
        self._dbg = dbgmod.get_logger("panel")
        self._dbg_ui = dbgmod.get_logger("ui")
        self._logbus.set_debug_logger(self._dbg_ui)
        self._dbg_status_prev = None
        self._install_exception_logging()
        self._dbg.info("panel starting — profile %r, version %s",
                       self._profiles.active, APP_VERSION)
        self._coord_seq = 0
        # Map sweep: the wrist that keeps the passive scan fed (panel/mapsweep.py).
        self._sweep_stop = None       # threading.Event of the sweep loop, when running
        self._sweep_at = 0            # index into the current pass's waypoints
        self._sweep_pass = 0          # completed passes this session (for the log)
        # Liveness: how many consecutive polls have found the game gone, and when
        # the watchdog last relaunched it (see _refresh_status / _watchdog_check).
        self._game_gone = 0
        self._game_was_up = False
        self._watchdog_last = 0.0
        self._status_busy = False     # one status reading in flight at a time
        # Account dashboard: the last readings and the poller's stop flag.
        self._dash_values: dict = {}
        self._dash_stop = None
        self._dash_err = ""          # last complaint, so it is said once not per poll
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
        # In-memory chat messages keyed by chat_type. `system` has a tab of its own
        # now — it used to be counted here and shown nowhere.
        self._chat_msgs: dict = {t: [] for t in CHAT_TABS}
        # Unread marks: how many messages have arrived in a tab nobody is looking
        # at. Cleared when that tab is selected.
        self._chat_unread: dict = {t: 0 for t in CHAT_TABS}
        # Text-view widgets per chat type (populated by _build_chat_tab). Named
        # _chat_trees for historical reasons; they are tk.Text now, not Treeviews.
        self._chat_trees: dict = {}
        # Count of lines already rendered into each view (for incremental appends)
        self._chat_tree_rows: dict = {}
        # Lazy-load: `_chat_msgs` holds only the records currently in memory (the
        # newest page at startup); `_chat_has_more` is True while the SQLite store
        # still holds OLDER messages for that tab than the oldest one in memory. A
        # scroll to the top (or the load-more header) pages the next chunk in from
        # the store. `_chat_store` is the ChatHistoryStore of the CURRENT CHARACTER
        # (`_chat_uid`), not the account: one account can hold several characters and
        # their chats live in separate files. It is re-pointed when the chat monitor
        # starts (the uid is read live from the game then).
        self._chat_has_more: dict = {t: False for t in CHAT_TABS}
        self._chat_store = None
        self._chat_uid = ""            # current character's uid; "" until resolved
        self._chat_resolving = False   # guards against overlapping uid resolves
        # DM contact list. The DM tab is split: a contact list (one peer per DM
        # conversation, read from the store) beside a conversation view that shows
        # ONE peer at a time. `_dm_active_room`/`_dm_active_peer` is the open
        # conversation; `_dm_unread` counts messages that arrived for a contact while
        # it was not the open one; `_dm_contacts_dirty` asks for a sidebar repaint.
        self._dm_active_room = ""
        self._dm_active_peer = ""
        self._dm_unread: dict = {}
        self._dm_contacts_dirty = False
        self._dm_list = None           # the contact-list textbox (built in _build_dm_tab)
        self._chat_entry = None        # the message-send Entry (for emoji insertion)
        self._emoji_win = None         # the open emoji/sticker picker, if any
        # Cache of inline sprite images keyed by (path, height) -- also keeps the
        # PhotoImage refs alive (tk.Text does not hold a Python reference). Bounded
        # at CHAT_IMG_CACHE_MAX: a night of chat walks past thousands of distinct
        # avatars and photos, and every one of them is a live Tk image until it is
        # dropped (see `_chat_image`).
        self._chat_img_cache: dict = {}
        self._photo_seq = 0            # how many photos have been drawn (diagnostics)
        # Tk image name -> (uid, pic_ver, path) for the click that opens a chat photo
        # full-size. Keyed by the image, so it is bounded by the cache above.
        self._photo_meta: dict = {}
        # THE SCHEDULE (panel/runtime/schedule.py): errands on a clock and errands
        # the wire sets off, sharing one single-file queue. It is the runtime's rather
        # than the Timers tab's because it is what the panel does while nobody is
        # looking — and the tab that edits the list may well be switched off.
        self._splash_step("splash.triggers", 0.35)
        self._schedule = self._rt.schedule
        self._timers = self._schedule.timers
        self._triggers = self._schedule.triggers
        self._timer_store = self._schedule.store
        # Two rules the schedule does not own: the rally auto-join's daily cap, and the
        # squads it joins with. Both belong to the rally code (Tk-free on purpose, so
        # they answer in a profile that does not show the tab); only the wiring is here.
        self._schedule.register_gate("rally_auto_join",
                                     lambda: rallygate.join_gate(self._rt),
                                     lambda spent: rallygate.record_joins(self._rt, spent))
        self._schedule.register_args("rally_auto_join", self._rally_join_args)



        # The Settings page's knobs, one Tk variable each, created BEFORE any tab is
        # built — the Settings tabs bind widgets to them and the main tab's watchdog
        # checkbox shares the very same variable, so the two can never disagree.
        self._binder.create_vars(self, _settings_var)
        # The daemon this profile drives. A profile naming a non-default port drives
        # the client of ANOTHER Windows session (tools/rdp_instance.py) — see
        # SETTINGS_DEFAULTS. Re-pointed by `_rebind_daemon` on a switch or an edit.
        # Profile picker lives in a modal (menu → «Профиль»), not on the main page.
        # The var is always live; the combo exists only while that modal is open.
        self._profile_var = tk.StringVar(value=self._profiles.active)
        self._profile_combo = None
        self._profile_win = None
        self._splash_step("splash.ui", 0.45)
        self._build_menu()
        self._build_ui()
        self._apply_settings_to_ui()  # restore this profile's saved values
        self._loading = False
        self._install_autosave()      # persist every subsequent change immediately
        self._restore_geometry()      # window size/position and the log sash
        self._install_resize_damper()  # …and keep dragging the frame cheap
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_log()
        self._open_panel_log()
        self._splash_step("splash.daemon", 0.6)
        self._refresh_status()
        self._poll_status()           # …and keep re-reading it: a crash is silent otherwise
        # Bringing the systems up is the slow half of the boot — the monitors, the
        # schedule, the trigger listeners, the chat history, the daemon, the account
        # strip. It runs on its own thread (it waits on processes and on the game),
        # but the splash STAYS UP until it is done: everything it registers —
        # `after` chains, Tk callbacks, the first painting of the chat views — used
        # to land in the window's lap after the splash had already gone, which is
        # why a freshly opened panel sat there unresponsive and half-drawn.
        self._boot_step: "queue.Queue[tuple]" = queue.Queue()
        self._boot_done = threading.Event()
        threading.Thread(target=self._startup_boot, daemon=True).start()
        self._await_boot()
        self._start_health_watch()
        # Fade the splash and reveal the fully-built window.
        if self._splash is not None:
            try:
                self._splash.finish(self._t("splash.ready"))
            except Exception:        # noqa: BLE001
                pass
            self._splash = None
        self._reveal_window()

    def _startup_boot(self) -> None:
        """`_startup` with the splash told where it has got to, and an end signal."""
        try:
            self._startup()
        except Exception:            # noqa: BLE001 — a failed system is a log line,
            self._dbg.error("startup failed", exc_info=True)   # not a dead panel
        finally:
            self._boot_done.set()

    def _boot_at(self, key: str, progress: float) -> None:
        """Report a boot phase from the startup thread (drained by `_await_boot`)."""
        try:
            self._boot_step.put_nowait((key, progress))
        except Exception:            # noqa: BLE001 — progress is never load-bearing
            pass

    def _await_boot(self) -> None:
        """Hold the splash — pumping Tk — until the systems are up.

        There is no mainloop yet, so this loop IS the event loop for the length of
        the boot: `update()` runs the `after(0, …)` calls the startup thread posts
        (which is where the chat history is drawn and the daemon indicator is set),
        while the bar follows the phases it reports.

        BOOT_MAX_WAIT_SEC is the ceiling. A daemon that never comes up already costs
        half a minute of waiting inside `_ensure_daemon`, and no start-up step is
        worth holding the whole window hostage — past the ceiling the panel opens
        anyway and whatever is still coming up says so in the log.
        """
        deadline = time.time() + BOOT_MAX_WAIT_SEC
        while not self._boot_done.is_set():
            drained = False
            try:
                while True:
                    key, progress = self._boot_step.get_nowait()
                    self._splash_step(key, progress)      # this pumps Tk itself
                    drained = True
            except queue.Empty:
                pass
            if time.time() > deadline:
                self._say("panel", "log.boot.slow")
                self._dbg.warning("boot still unfinished after %ss — opening anyway",
                                  BOOT_MAX_WAIT_SEC)
                return
            if not drained:
                try:
                    self.update()
                except tk.TclError:      # the window went away under us
                    return
                time.sleep(0.02)
        # Drain whatever the last phase reported before the splash is torn down.
        try:
            while True:
                key, progress = self._boot_step.get_nowait()
                self._splash_step(key, progress)
        except queue.Empty:
            pass

    def _reveal_window(self) -> None:
        """Show the main window once the boot splash is gone."""
        self.deiconify()
        try:
            self.lift()
            # Draw it NOW rather than on the mainloop's first pass: everything is
            # built and wired by this point, so there is nothing left to wait for.
            self.update_idletasks()
        except Exception:            # noqa: BLE001
            pass

    def _splash_step(self, key: str, progress: float) -> None:
        """Advance the boot splash (a no-op once it is gone or was never built)."""
        if getattr(self, "_splash", None) is None:
            return
        try:
            self._splash.step(self._t(key), progress)
        except Exception:            # noqa: BLE001 — the splash is never load-bearing
            self._splash = None

    # -- the Settings page's knobs ------------------------------------------
    #
    # Every one of these used to be a constant in this file. They are read through
    # `_opt` so the value is taken from, in order: the widget on the Settings page
    # (live, so an edit applies without a restart), the profile's saved config, and
    # SETTINGS_DEFAULTS — which is the old constant. That order is what lets the
    # panel read a setting during __init__, before the page that edits it exists.
    # panel/runtime/settings.py answers all four; these stay as this file's names.
    def _opt(self, key: str):
        return self._binder.opt(key)

    def _opt_int(self, key: str, low: int | None = None, high: int | None = None) -> int:
        return self._binder.opt_int(key, low, high)

    def _opt_float(self, key: str, low: float | None = None,
                   high: float | None = None) -> float:
        return self._binder.opt_float(key, low, high)

    def _opt_str(self, key: str) -> str:
        return self._binder.opt_str(key)

    def _opt_bool(self, key: str) -> bool:
        return self._binder.opt_bool(key)

    # `_settings`, `_opt_vars` and `_loading` are the binder's, under the names the
    # rest of this file (and the tests that borrow its methods) already use.
    @property
    def _settings(self) -> dict:
        return self._binder.values

    @_settings.setter
    def _settings(self, raw: dict) -> None:
        self._binder.values = raw

    @property
    def _opt_vars(self) -> dict:
        return self._binder.vars

    @property
    def _loading(self) -> bool:
        return self._binder.loading

    @_loading.setter
    def _loading(self, flag: bool) -> None:
        self._binder.loading = bool(flag)

    # Named readers for the knobs used in more than one place, so the bounds live
    # once and a caller reads a phrase instead of a key and two magic numbers.
    def _python(self) -> str:
        return self._opt_str("win_python")

    def _daemon_port(self) -> int:
        return self._opt_int("daemon_port", low=1, high=65535)

    def _game_exe(self) -> str:
        return self._opt_str("game_exe")

    def _launcher(self) -> str:
        return self._opt_str("launcher")

    def _autoloot_limit(self) -> int:
        return self._opt_int("autoloot_limit", low=1, high=50)

    def _trace_filter(self) -> str:
        return self._opt_str("trace_filter")

    def _sniff_timeout(self) -> float:
        return self._opt_float("sniff_ready_timeout", low=1.0, high=600.0)

    def _sweep_box(self) -> tuple[int, int, float, float]:
        """``(radius, step, dwell, rest)`` of the map sweep, all bounded."""
        return (
            self._opt_int("sweep_radius", low=mapsweepmod.MIN_RADIUS,
                          high=mapsweepmod.MAX_RADIUS),
            self._opt_int("sweep_step", low=mapsweepmod.MIN_STEP,
                          high=mapsweepmod.MAX_STEP),
            self._opt_float("sweep_dwell", low=mapsweepmod.MIN_DWELL,
                            high=mapsweepmod.MAX_DWELL),
            self._opt_int("sweep_rest_min", low=0, high=1440) * 60.0,
        )

    def _child_env(self) -> dict:
        """The environment every child is launched with (panel/runtime/children.py)."""
        return self._children.env()

    def _daemon_up(self) -> bool:
        """Is THIS profile's daemon reachable? (Not "a daemon somewhere".)"""
        return self._game.up()

    @property
    def _client(self):
        """This profile's daemon client (panel/runtime/daemon.py owns it)."""
        return self._game.client

    @property
    def _busy(self) -> bool:
        """Is a game action running right now? (The link holds the flag.)"""
        return self._game.busy

    def _rebind_daemon(self) -> None:
        """Point the panel's own client at the profile's daemon port."""
        if self._game.rebind():
            self._say("daemon", "log.daemon.port", port=self._game.port())
            self._refresh_status()

    # -- i18n (panel/runtime/i18n.py holds it; these stay as the panel's names) ----
    def _t(self, key: str, **fmt) -> str:
        return self._i18n.t(key, **fmt)

    def _tr(self, widget, key: str, option: str = "text", **fmt):
        """Set ``widget[option]`` from a locale key and remember it for retranslation."""
        return self._i18n.tr(widget, key, option, **fmt)

    def _hook(self, func, key=None) -> None:
        """Register a language-change hook — once, however often this is reached."""
        self._i18n.hook(func, key)

    def _sweep_tr_widgets(self) -> None:
        self._i18n.sweep()

    def _set_language(self, lang: str) -> None:
        if self._i18n.set_lang(lang):
            self._apply_language()
            self._save_settings()   # language is a per-profile setting

    def _apply_language(self) -> None:
        self.title(self._t("app.title"))
        self._i18n.retranslate()
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
        help_menu.add_command(label=self._t("menu.help.send_log"),
                              command=self._open_send_log_dialog)
        help_menu.add_command(label=self._t("menu.help.about"), command=self._show_about)

        menubar.add_command(label=self._t("menu.profile"),
                            command=self._open_profile_dialog)
        menubar.add_cascade(label=self._t("menu.language"), menu=lang_menu)
        menubar.add_cascade(label=self._t("menu.develop"), menu=develop_menu)
        menubar.add_cascade(label=self._t("menu.help"), menu=help_menu)
        self.config(menu=menubar)
        self._hook(self._build_menu)

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

    # -- send diagnostics ---------------------------------------------------
    def _open_send_log_dialog(self) -> None:
        """«Помощь → Отправить лог разработчику»: a modal that shows what would be
        sent (the zipped debug log + a preview of its tail), reassures that nothing
        personal leaves the box, and ships it via panel/debug_sender.py."""
        existing = getattr(self, "_senddiag_win", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return

        win = tk.Toplevel(self)
        self._senddiag_win = win
        win.title(self._t("senddiag.title"))
        win.transient(self)
        frm = ttk.Frame(win)
        frm.pack(fill="both", expand=True, padx=16, pady=16)

        # Nothing personal leaves the machine — say so, up top and in warning colour.
        self._tr(ttk.Label(frm, foreground="#e0a84f", wraplength=470, justify="left"),
                 "senddiag.warning").pack(anchor="w")

        # The archive that would be sent — built now so «Открыть» has a real file.
        logpath = self._profiles.debug_log()
        try:
            archive = dbgsender.make_archive(path=logpath)
        except Exception:             # noqa: BLE001 — display must not break the dialog
            archive = logpath + ".zip"
        pathrow = ttk.Frame(frm)
        pathrow.pack(fill="x", pady=(12, 8))
        self._tr(ttk.Label(pathrow), "senddiag.path").pack(side="left")
        path_var = tk.StringVar(value=_repo_rel(archive))
        entry = ttk.Entry(pathrow, textvariable=path_var)
        entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
        try:
            entry._entry.configure(state="readonly")   # shown for reading, not editing
        except Exception:             # noqa: BLE001
            pass
        self._tr(ttk.Button(pathrow, width=10,
                           command=lambda p=archive: self._reveal_in_explorer(p)),
                 "senddiag.open").pack(side="left")

        # A read-only preview of the tail of the actual debug.log.
        self._tr(ttk.Label(frm, foreground="#888"), "senddiag.preview").pack(anchor="w")
        # width/height are in characters / lines (the ScrolledText adapter scales them);
        # it fills the window anyway, these are just the initial ask.
        preview = ScrolledText(frm, width=64, height=14, wrap="none",
                             font=("Consolas", 9))
        preview.pack(fill="both", expand=True, pady=(2, 12))
        tail = self._tail_debug_log(logpath, 100)
        preview.insert("1.0", tail if tail else self._t("senddiag.empty"))
        preview.configure(state="disabled")

        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        self._tr(ttk.Button(btns, command=lambda: self._send_log_and_close(win)),
                 "senddiag.send").pack(side="right")
        self._tr(ttk.Button(btns, command=win.destroy),
                 "senddiag.cancel").pack(side="right", padx=(0, 6))

        win.bind("<Destroy>", self._on_senddiag_destroyed)
        win.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - win.winfo_height()) // 5)
        win.geometry(f"+{x}+{y}")
        win.grab_set()
        win.focus_set()

    def _on_senddiag_destroyed(self, event) -> None:
        if event.widget is getattr(self, "_senddiag_win", None):
            self._senddiag_win = None

    def _send_log_and_close(self, win) -> None:
        """«Отправить»: hand the archive to the sender (result lands in the log)."""
        win.destroy()
        self._send_debug_archive()

    @staticmethod
    def _tail_debug_log(path: str, lines: int = 100) -> str:
        """The last ``lines`` of ``path`` (reading only the tail), or "" if unreadable."""
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 65536))
                text = handle.read().decode("utf-8", "replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])

    def _reveal_in_explorer(self, path: str) -> None:
        """Show ``path`` selected in the OS file manager."""
        target = os.path.normpath(path)
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select," + target])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", target])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(target) or "."])
        except Exception as exc:      # noqa: BLE001
            self._say("debug", "log.debug.failed", error=exc)

    # -- profiles -----------------------------------------------------------
    def _open_profile_dialog(self) -> None:
        """The profile manager, in a modal window (menu → «Профиль»): pick the
        active profile, or create / rename / delete one. It used to be a bar above
        the tabs on the main page; a switch that is used rarely does not earn a
        permanent strip there."""
        existing = getattr(self, "_profile_win", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return

        win = tk.Toplevel(self)
        self._profile_win = win
        win.title(self._t("menu.profile"))
        win.resizable(False, False)
        win.transient(self)

        frm = ttk.Frame(win)
        frm.pack(fill="both", expand=True, padx=16, pady=16)
        self._tr(ttk.Label(frm), "profile.label").grid(row=0, column=0, sticky="w")
        self._profile_var.set(self._profiles.active)
        self._profile_combo = ttk.Combobox(frm, textvariable=self._profile_var,
                                          state="readonly", width=24,
                                          values=self._profiles.list())
        self._profile_combo.grid(row=0, column=1, sticky="we", padx=(8, 0))
        self._profile_combo.bind("<<ComboboxSelected>>", lambda e: self._switch_profile())

        btns = ttk.Frame(frm)
        btns.grid(row=1, column=0, columnspan=2, sticky="we", pady=(14, 0))
        self._tr(ttk.Button(btns, command=self._create_profile),
                 "profile.new").pack(side="left")
        self._tr(ttk.Button(btns, command=self._rename_profile),
                 "profile.rename").pack(side="left", padx=6)
        self._tr(ttk.Button(btns, command=self._delete_profile),
                 "profile.delete").pack(side="left")
        self._tr(ttk.Button(btns, command=win.destroy),
                 "profile.close").pack(side="right")

        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.bind("<Destroy>", self._on_profile_dialog_destroyed)
        win.update_idletasks()
        # Centre over the main window.
        x = self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - win.winfo_height()) // 3)
        win.geometry(f"+{x}+{y}")
        win.grab_set()
        win.focus_set()

    def _on_profile_dialog_destroyed(self, event) -> None:
        # The combo lives only while the modal is open; forget it once it is gone so
        # `_refresh_profile_combo` never touches a dead widget.
        if event.widget is self._profile_win:
            self._profile_combo = None
            self._profile_win = None

    def _profile_dialog_parent(self):
        """Parent the create/rename/delete sub-dialogs at the modal if it is open,
        so they stack above it and get the input grab; else at the main window."""
        win = getattr(self, "_profile_win", None)
        return win if win is not None and win.winfo_exists() else self

    def _refresh_profile_combo(self, select: str | None = None) -> None:
        self._profile_var.set(select or self._profiles.active)
        combo = getattr(self, "_profile_combo", None)
        if combo is not None:
            try:
                combo.configure(values=self._profiles.list())
            except tk.TclError:
                pass

    def _switch_profile(self, name: str | None = None) -> None:
        name = name or self._profile_var.get()
        if name == self._profiles.active:
            return
        self._save_settings()                 # flush the profile we are leaving
        self._profiles.set_active(name)
        self._settings = self._profiles.load()
        self._reload_active_profile()
        self._say("profile", "log.profile.active", name=name)

    def _reload_active_profile(self) -> None:
        """Re-apply language, all UI values, and monitor state from self._settings."""
        lang = self._settings.get("language")
        if lang and lang != self._i18n.lang and self._i18n.set_lang(lang):
            self._apply_language()
        self._apply_settings_to_ui()
        self._open_panel_log()                # the mirror follows the active profile
        self._configure_debug_log()           # …and so does the debug log
        self._dbg.info("active profile is now %r", self._profiles.active)
        self._rebind_daemon()                 # …and so does the client it drives
        self._sync_monitors()                 # restart captures into the new profile's logs
        self._load_chat_history()             # reload chat messages for the new profile

    def _create_profile(self) -> None:
        name = simpledialog.askstring(self._t("profile.new"),
                                      self._t("profile.prompt_name"), parent=self._profile_dialog_parent())
        if not name:
            return
        try:
            created = self._profiles.create(name)
        except ValueError as exc:
            messagebox.showerror(self._t("profile.new"), str(exc), parent=self._profile_dialog_parent())
            return
        # Seed the new profile with the current settings so it starts from a sane state.
        self._profiles.save(self._collect_settings(), created)
        self._refresh_profile_combo(select=created)
        self._switch_profile(created)

    def _rename_profile(self) -> None:
        cur = self._profiles.active
        name = simpledialog.askstring(self._t("profile.rename"),
                                      self._t("profile.prompt_name"),
                                      initialvalue=cur, parent=self._profile_dialog_parent())
        if not name:
            return
        try:
            newn = self._profiles.rename(cur, name)
        except ValueError as exc:
            messagebox.showerror(self._t("profile.rename"), str(exc), parent=self._profile_dialog_parent())
            return
        self._refresh_profile_combo(select=newn)
        # The directory moved under the schedule's feet: re-point both files, or
        # the next run would write into a re-created old directory.
        self._schedule.on_profile_switch()
        self._say("profile", "log.profile.renamed", old=cur, new=newn)

    def _delete_profile(self) -> None:
        cur = self._profiles.active
        # The confirmation used to name the profile and nothing else, while the delete
        # is an `rmtree` of its whole directory — its chat history, its rally log, its
        # panel.log and the record of when every timer last ran. Say what goes.
        if not messagebox.askyesno(
                self._t("profile.delete"),
                self._t("profile.confirm_delete", name=cur,
                        path=_repo_rel(self._profiles.dir(cur))), parent=self._profile_dialog_parent()):
            return
        try:
            now_active = self._profiles.delete(cur)
        except ValueError as exc:
            messagebox.showerror(self._t("profile.delete"), str(exc), parent=self._profile_dialog_parent())
            return
        self._refresh_profile_combo(select=now_active)
        self._settings = self._profiles.load()
        self._reload_active_profile()
        self._say("profile", "log.profile.deleted", name=cur, active=now_active)

    # -- persistent settings ------------------------------------------------
    def _collect_settings(self) -> dict:
        """Snapshot every persisted panel setting into a plain dict."""
        out = {
            "language": self._i18n.lang,
            # `coord_x` / `coord_y` / `coord_server` / `coord_history` are no longer
            # written: the block they belonged to is gone (#1183). A profile saved by
            # an older panel still carries them — they are simply ignored, and drop
            # out on the next save.
            # `alliance_autohelp` (the old checkbox) is deliberately not written back:
            # it became the «alliance_help» trigger in the profile's timers.json, and
            # `_migrate_autohelp` flips that on once for a profile that had it set.
            "chat_monitor": self._chat_var.get(),
            # The Scenarios tab used to forget all three on every restart, so a
            # launch always started on the first row with an empty args box.
            "log_filter": self._log_filter_var.get(),
            "window_geometry": self._current_geometry(),
            "log_sash": self._current_sash(),
            # The «Командный пункт» tab: the shared-mission robbery rule and the
            # treasure page's digging squad, a block per page.
            # The schedule is NOT here: a timer's switch and period live in the
            # profile's own timers.json beside its scenario, and when each last
            # ran in timers_last_run.json (see panel/timers.py).
        }
        # Settings page -> «Общие» / «Игра». One loop, so adding a knob is adding a
        # line to SETTINGS_DEFAULTS and a widget bound to `_opt_vars[key]`.
        for key in SETTINGS_DEFAULTS:
            var = self._opt_vars.get(key)
            if var is not None:
                out[key] = var.get()
        # …and the plugin tabs' own blocks, plus the flat keys they used to be spelled
        # with, so a profile this panel touches still opens in an older one (§5 rule 2).
        out["tabs"] = self._tabs_block()
        for tab in getattr(self, "_plugin_tabs", {}).values():
            block = out["tabs"]["config"].get(tab.ID) or {}
            for new_key, old_key in type(tab).LEGACY_KEYS.items():
                if new_key in block:
                    out[old_key] = block[new_key]
        return out

    def _tabs_block(self) -> dict:
        """The profile's `tabs` block: which tabs, in what order, and their settings.

        `enabled` / `order` are carried through untouched — nothing edits them yet, and
        a save must not be what wipes a hand-written list. A tab that is not in this
        window (switched off, or it failed to build) keeps the block that is on disk:
        settings are collected on every save, including saves that happen before the
        tabs exist, and one of those must not overwrite the choices about to be
        restored.
        """
        saved = self._settings.get("tabs")
        block = dict(saved) if isinstance(saved, dict) else {}
        # Every tab this build offers. A tab that is in here and not in `enabled` was
        # switched off ON PURPOSE; without the record it would be indistinguishable
        # from one that did not exist yet, and would come back on the next start.
        block["known"] = [spec.id for spec in tabsreg.TABS]
        config = dict(block.get("config") or {})
        for tab in getattr(self, "_plugin_tabs", {}).values():
            config[tab.ID] = tab.config()
        block["config"] = config
        return block

    def _apply_settings_to_ui(self) -> None:
        """Push self._settings into the widgets without triggering auto-save."""
        s = self._settings
        self._loading = True
        try:
            self._chat_var.set(bool(s.get("chat_monitor", False)))
            self._log_filter_var.set(s.get("log_filter") or LOG_FILTER_ALL)
            for key, default in SETTINGS_DEFAULTS.items():
                var = self._opt_vars.get(key)
                if var is not None:
                    var.set(s.get(key, default))
            # Each plugin tab restores its own block — the new `tabs.config.<id>` if the
            # profile has one, else the flat keys it used to be spelled with.
            for tab in getattr(self, "_plugin_tabs", {}).values():
                tab.apply_config(
                    self._binder.tab_config(tab.ID, type(tab).LEGACY_KEYS))
        finally:
            self._loading = False
        self._refresh_rule_hints()

    def _install_autosave(self) -> None:
        """Persist to the active profile whenever any bound setting changes."""
        for var in (self._chat_var, self._log_filter_var):
            var.trace_add("write", lambda *a: self._save_settings())
        # Every plugin tab's own settings, traced from here like any other bound
        # setting, so a tab stays free of the profile machinery.
        for owner in getattr(self, "_plugin_tabs", {}).values():
            for var in owner.persist_vars():
                var.trace_add("write", lambda *a: self._save_settings())
        # …and what a tab changes that is NOT a variable — the «Авторалли» page's
        # tri-state squad buttons, the capture combo. A widget with no variable of its
        # own says so instead of being traced.
        self._binder.on_change = self._save_settings
        # The Settings page's own knobs. The daemon port is the one that needs more
        # than a save: the panel's client has to be re-pointed at it.
        for key, var in self._opt_vars.items():
            if key == "daemon_port":
                var.trace_add("write", lambda *a: self._on_daemon_port_change())
            else:
                var.trace_add("write", lambda *a: self._save_settings())

    def _on_daemon_port_change(self) -> None:
        self._save_settings()
        if not self._loading:
            self._rebind_daemon()

    # The two "this is what the checkbox will do" lines, the capture's interval
    # bounce and the listener's debounced restart all went with the «Secret Tasks» tab
    # (panel/tabs/secret_tasks/): they describe and re-aim ITS standing orders.

    def _save_settings(self) -> None:
        if self._binder.loading:
            return
        self._binder.save(self._collect_settings())

    def _sync_monitors(self) -> None:
        """Start/stop (restart) the rally, secret and chat captures to match the checkboxes.

        Restarting is deliberate: a running capture keeps writing to the *old* profile's
        log, so on a profile switch we bounce it to redirect output to the new directory.
        """
        # Every plugin tab re-points itself: the rally monitor bounces onto the new
        # profile's log, the stats table re-reads that account's tally. One loop, so a
        # tab added later cannot be the one somebody forgot to list here.
        for tab in getattr(self, "_plugin_tabs", {}).values():
            tab.on_profile_switch()
        self._stop_chat()
        if self._chat_var.get():
            self._start_chat()
        # The schedule belongs to the account: its errands, their switches and periods,
        # the clock that says when each last ran, and the listeners a switch must not
        # leave watching on the previous profile's behalf. The Timers tab, if this
        # profile has one, redraws its rows from its own `on_profile_switch`.
        self._schedule.on_profile_switch()

    # `_update_path_hints` went with the rally monitor: the one label showing a
    # profile's log path is that tab's own now, and it refreshes itself on a language
    # switch and on `on_profile_switch`.

    # -- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        # The selected timer row has to be visible: a checkbox has no "selected"
        # look of its own, and the four editor buttons act on whichever row that
        # is. Give that row a bold "Selected.TCheckbutton" style; every other row
        # keeps the stock "TCheckbutton" (see _paint_timer_selection).
        ttk.Style(self).configure("Selected.TCheckbutton", font=ui_font(weight="bold"))
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        main = ttk.Frame(nb)
        settings_tab = ttk.Frame(nb)
        chat_tab = ttk.Frame(nb)
        self._main_nb = nb

        # WHICH TABS THIS WINDOW HAS IS THE PROFILE'S BUSINESS (§5). The registry says
        # what exists and in what order; `tabs.enabled` / `tabs.order` in the profile
        # override both. A tab that is switched off is not built, not added to the
        # notebook, contributes no settings page, and — because nothing calls its
        # `ensure_loaded` — starts none of its captures or watchers.
        #
        # The four below are still the shell's own rather than plugins (waves 5 and 6
        # move three of them; «Главная» never moves — §4.4). They are ordered into the
        # same sequence by the numbers the registry would have given them, so the tab
        # bar reads the same whichever half a tab comes from.
        entries = [("main", main, "tab.main", 0),
                   ("settings", settings_tab, "tab.settings", 40),
                   ("chat", chat_tab, "tab.chat", 50)]
        want_order = self._binder.tab_list("order")
        specs = tabsreg.resolve(
            enabled=self._binder.tab_list("enabled"), order=want_order,
            known=self._binder.tab_list("known"),
            on_unknown=lambda t: self._say("panel", "log.tab.unknown", tab=t))
        frames = {spec.id: ttk.Frame(nb) for spec in specs}
        entries += [(s.id, frames[s.id], s.title_key, s.order) for s in specs]
        slot = tabsreg.ranker(want_order)
        entries.sort(key=lambda e: slot(e[0], e[3]))
        for _id, frame, title_key, _order in entries:
            nb.add(frame, text=self._t(title_key))
        # One loop instead of the fourteen-entry lambda this used to be: a tab's title
        # is its own `TITLE_KEY`, and a tab that is not here has no title to retranslate.
        self._hook(key="tab-titles", func=lambda: [
            nb.tab(f, text=self._t(k)) for _i, f, k, _o in entries])

        self._build_chat_tab(chat_tab)
        # THE PLUGIN TABS (panel/tabs/). Each is a class the registry names, built from
        # the runtime and nothing else — the same six lines `run_tab` performs when one
        # of them is launched on its own. A tab that fails to import or build is skipped
        # with a line in the log; it used to take the whole boot down with it.
        #
        # BEFORE the Settings page, because a tab contributes its own page to it (§6)
        # and the aggregator can only draw the tabs that exist by then.
        self._plugin_tabs: dict = {}
        for spec in specs:
            tab = self._build_plugin_tab(spec, frames[spec.id])
            if tab is not None:
                self._plugin_tabs[spec.id] = tab
                self._rt.tabs.add(tab)
                # What the tab brought with it: its wire-driven errands (§3.2). A tab
                # that is not in this profile registers nothing, so its trigger is not
                # offered and no listener is spawned for it.
                self._schedule.register(tab)
                # The Timers tab IS the switches while it is here: the schedule asks
                # the rows, and falls back to the saved catalogue when it is not.
                if tab.ID == "timers":
                    self._schedule.timer_config_source = tab._timer_widget_config
                    self._schedule.trigger_config_source = tab._trigger_widget_config
        # The Settings page is an aggregator now: the shell's own sub-tabs, then one per
        # tab that brought a page along («Авторалли» comes with rally).
        self._build_settings_tab(settings_tab)
        # The account summary strip goes into the «Аккаунты» tab, beside the list of
        # characters it summarises — and only if this profile has that tab at all.
        if "accounts" in frames:
            self._build_dashboard(frames["accounts"])
        # Lazily loaded on first show, by the frame the notebook reports as selected.
        self._lazy_tabs = {str(frames[tab_id]): tab
                           for tab_id, tab in self._plugin_tabs.items()}
        nb.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)
        # The «Сценарии» tab's `TAP` reference drops its choice into the DSL command
        # line, which lives here on «Главная» — so it asks rather than reaching (§7).
        self._rt.bus.subscribe("cmd.reference", lambda _p: self._show_button_reference())

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
        # Restarting the daemon used to mean killing it from outside the panel: a
        # wedged lua_daemon left every button dead with no way back in the UI.
        self._tr(ttk.Button(top, width=3, command=self._restart_daemon),
                 "daemon.restart").pack(side="left", padx=(2, 0))
        ttk.Button(top, text="↻", width=3, command=self._refresh_status).pack(side="right")
        # One control that stops everything: monitors, watchers, the sweep, a running
        # scenario and the schedule. It used to be five clicks across three tabs,
        # which is exactly the wrong shape for the moment you actually need it.
        self._tr(ttk.Button(top, command=self._panic),
                 "panic.stop_all").pack(side="right", padx=(0, 6))

        # The account summary strip that used to hang here now opens the «Аккаунты»
        # tab (built above, beside the character list it belongs with).

        # Everything above the log is fixed-height and the log used to get whatever
        # was left — a few lines at the 640×500 minimum. A sash makes that the
        # operator's choice, and its position is remembered per profile.
        split = ttk.PanedWindow(main, orient="vertical")
        split.pack(fill="both", expand=True)
        self._main_split = split
        upper = ttk.Frame(split)
        lower = ttk.Frame(split)
        split.add(upper, weight=0)
        split.add(lower, weight=1)
        # The blocks in the top pane scroll. Stacked they ask for more height than
        # the pane ever gets — the window opens 760×600 and the strip alone wants
        # some 550 px — and `pack` answers that by collapsing whatever crosses the
        # bottom edge to a single pixel. «Автолут секреток» and «Автолут Призрака»
        # sat right at that edge and showed a caption with nothing under it, with
        # no hint that anything was missing (#1153). Inside a scroll area every
        # block keeps the height it asks for, wherever the sash ends up.
        controls = ScrollableFrame(upper)
        controls.pack(fill="both", expand=True)
        self._main_controls = controls
        main = controls               # the control blocks below fill the top pane

        game = self._tr(ttk.LabelFrame(main, padding=8), "game.frame")
        game.pack(fill="x", padx=8, pady=(0, 6))
        self._tr(ttk.Button(game, command=self._launch_game),
                 "game.launch").pack(side="left", padx=4, ipady=3)
        self._tr(ttk.Button(game, command=self._restart_game),
                 "game.restart").pack(side="left", padx=4, ipady=3)
        self._tr(ttk.Label(game, foreground="#888"),
                 "game.launcher_hint").pack(side="left", padx=10)
        # The watchdog: the client is crash-prone (that is why launch_game exists),
        # and until now a crash was silent — the panel kept saying "running (pid …)"
        # while every timer tick failed into the retry hold. The same variable the
        # Settings → «Игра» tab shows, so the two switches are one switch.
        self._tr(ttk.Checkbutton(game, variable=self._opt_vars["watchdog"]),
                 "game.watchdog").pack(side="right")

        # -- «Навигация» is gone (#1183) ----------------------------------------
        #
        # Both of its rows went with the block: the «Сцена» switch (🏠 Домой / 🌍 Мир),
        # because changing scene is what `SCENE` does in a scenario, and «Переход по
        # координатам» — the X/Y/server triple, «Перейти», «↻ сервер» and the «куда
        # ходил» history — with the four `coord_*` settings that remembered them.
        #
        # Jumping itself did NOT go: `_jump` is still here and still the only way a
        # coordinate is walked to. What used to aim it now aims it from where the
        # coordinate already is — a `#2305 X:568 Y:371` in the log is clickable
        # (`_bind_coord_links` → `_on_coord_click`), the «Командный пункт» tab jumps to
        # the tile a row is about, and a scenario's `JUMP` names its own.
        #
        # Two buttons read the deleted fields and were re-sourced rather than left
        # pointing at nothing: «Отсюда» in «Автообъезд карты» is gone (that block has
        # its own centre boxes, two widgets to the left), and the chat's «📍 координаты»
        # now shares whatever coordinate is written in the message box.

        # -- Secret tasks are a plugin tab now (panel/tabs/secret_tasks/) --------
        #
        # The whole block went: the passive capture with its kind, interval and log
        # filters, the «Автообъезд карты» map sweep, and the «Автолут ★» range. Not just
        # the widgets this time — the child processes, the watcher loops, the daily
        # budget and the rule that aims it are the tab's own, and it opens on its own
        # with `python -m panel.tabs.secret_tasks`.
        #
        # «Операция Призрак» passed through here on its way to the «Секретный командный
        # пункт» tab, where the rest of that event lives.

        # -- «Ралли» is a plugin tab now (panel/tabs/rally/) ----------------------
        #
        # Both halves went: the form that raises a rally AND the monitor block (the
        # switch, «Оповещать», «Присоединяться сам», the «Присоединиться» button and the
        # log-path hint). The switches, the capture child, the alert, the daily caps and
        # the «Авторалли» settings page are all that tab's own — this shell neither
        # holds a `rally_*` variable nor knows how a rally is raised, and the tab opens
        # on its own with `python -m panel.tabs.rally`.

        # Alliance auto-help used to live here as its own checkbox. It is a wire-
        # driven standing order — answer «Помочь всем» the instant a request lands —
        # which is exactly a *trigger*, so it moved to the Timers tab's «Триггеры»
        # group (panel/timers.py, panel/triggers.py) and this frame went away.

        logframe = self._tr(ttk.LabelFrame(lower, padding=4), "log.frame")
        logframe.pack(fill="both", expand=True, padx=8, pady=(4, 4))

        # The strip above the log: which producer to show, and Clear. Six producers
        # write into one widget, so "давно ли пришёл этот запрос помощи" used to mean
        # reading past everything else that happened meanwhile.
        strip = ttk.Frame(logframe)
        strip.pack(fill="x", pady=(0, 3))
        self._tr(ttk.Label(strip), "log.filter").pack(side="left")
        self._log_filter_var = tk.StringVar(value=LOG_FILTER_ALL)
        filt = ttk.Combobox(strip, textvariable=self._log_filter_var, state="readonly",
                            width=10, values=(LOG_FILTER_ALL,) + LOG_TAGS)
        filt.pack(side="left", padx=(4, 8))
        filt.bind("<<ComboboxSelected>>", lambda _e: self._redraw_log())
        self._tr(ttk.Button(strip, command=self._clear_log),
                 "log.clear").pack(side="left")
        self._tr(ttk.Label(strip, foreground="#888"),
                 "log.filter_hint").pack(side="left", padx=(10, 0))

        # Plain native Text widget: state="normal" (never toggled to "disabled",
        # which would block interactive selection). The log stays technically
        # editable, but stray typed edits to a log are harmless. Mouse selection
        # comes for free from Tk's Text defaults; copy needs help, though — Tk's
        # built-in <Control-c> binding matches only the Latin 'c' keysym, so with
        # a non-Latin keyboard layout (e.g. Cyrillic) Ctrl+C never fires. We add
        # layout-independent copy/select-all: explicit key bindings that cover the
        # Cyrillic keysyms plus a right-click context menu (Copy / Select All).
        self._log = ScrolledText(logframe, wrap="word", height=16,
                                              font=("Consolas", 9),
                                              background="#111", foreground="#ddd")
        self._log.pack(fill="both", expand=True)
        self._log.tag_config("coordlink", foreground="#5cf", underline=True)
        self._bind_coord_links(self._log)
        for tag, colour in LOG_COLOURS.items():
            self._log.tag_config(tag, foreground=colour)
        self._install_log_copy(self._log)

        # -- one DSL line, run through the same interpreter a recipe runs on ------
        #
        # Thirty-odd named presses exist in tools/lib/game_buttons.py and the only
        # way to fire one from the panel was if some actions/*.md happened to wrap
        # it — pressing "collect the trucks" once, by hand, meant writing a file
        # first. This is that file's one line, typed. It also makes debugging a
        # recipe interactive instead of edit-save-run.
        cmdrow = ttk.Frame(lower, padding=(8, 0, 8, 6))
        cmdrow.pack(fill="x")
        self._tr(ttk.Label(cmdrow), "cmd.label").pack(side="left")
        self._cmd_var = tk.StringVar()
        cmd_entry = ttk.Entry(cmdrow, textvariable=self._cmd_var, font=("Consolas", 9))
        cmd_entry.pack(side="left", fill="x", expand=True, padx=(4, 4))
        cmd_entry.bind("<Return>", lambda _e: self._run_command())
        # Up/Down walk what has been typed before — a debugging loop is the same
        # line with one number changed, over and over.
        cmd_entry.bind("<Up>", lambda _e: self._cmd_recall(-1))
        cmd_entry.bind("<Down>", lambda _e: self._cmd_recall(1))
        self._cmd_hist: list = []
        self._cmd_at = 0
        self._tr(ttk.Button(cmdrow, command=self._run_command),
                 "cmd.run").pack(side="left")
        self._tr(ttk.Button(cmdrow, command=self._show_button_reference),
                 "cmd.reference").pack(side="left", padx=(4, 0))

    def _build_plugin_tab(self, spec, frame):
        """Build one registry tab into ``frame``. ``None`` if it could not be built.

        A tab that raises used to take the boot with it — `_build_ui` was one straight
        line of fourteen constructions. Now the panel opens without it and says so.
        """
        try:
            cls = spec.load()
            self._binder.register(cls.SETTINGS)
            tab = cls(self._rt, frame)
            tab.build()
            tab.apply_config(self._binder.tab_config(cls.ID, cls.LEGACY_KEYS))
            return tab
        except Exception as exc:                 # noqa: BLE001
            self._dbg.error("tab %r failed to build", spec.id, exc_info=True)
            self._say("panel", "log.tab.failed", tab=spec.id, error=exc)
            return None

    # -- the account dashboard ----------------------------------------------
    #
    # A display over gates that were already written. Every number on this strip is
    # the `count_lua` of some press in tools/lib/game_buttons.py — evaluated, until
    # now, only *inside* a press, with the answer thrown away. panel/dashboard.py
    # holds the list and builds the ONE game-VM call that reads all of them, so the
    # strip costs a round trip every DASH_POLL_SEC and nothing else.
    #
    # It decides nothing. That matters: a person reading "кражи 0 · ждут помощи 4"
    # is deciding whether today needs them at all, and a strip that also acted would
    # be a second, invisible place where the bot chose to press something.
    def _build_dashboard(self, parent: ttk.Frame) -> None:
        frame = self._tr(ttk.LabelFrame(parent, padding=(8, 4)), "dash.frame")
        frame.pack(fill="x", padx=8, pady=(0, 6))
        # A Text rather than a Label: a reading of 0 is greyed and one with work in
        # it is bright, which is what makes the strip readable at a glance instead of
        # a wall of even-weight words.
        self._dash_view = ScrolledText(frame, height=2, wrap="word", state="disabled",
                                  cursor="arrow", relief="flat", borderwidth=0,
                                  highlightthickness=0, font=("Segoe UI", 9))
        self._dash_view.tag_configure("label", foreground="#888")
        self._dash_view.tag_configure("hot", foreground="#66bb6a")
        self._dash_view.tag_configure("cold", foreground="#999999")
        self._dash_view.tag_configure("unread", foreground="#ef5350")
        self._dash_view.pack(side="left", fill="x", expand=True)
        ttk.Button(frame, text="↻", width=3, command=self._refresh_dashboard).pack(side="right")
        self._render_dashboard()

    def _start_dashboard(self) -> None:
        """Begin polling the readings (idempotent — one poller per panel)."""
        if self._dash_stop is not None:
            return
        self._dash_stop = threading.Event()
        dbgmod.get_logger("dashboard").info("poller started")
        threading.Thread(target=self._dash_loop, args=(self._dash_stop,),
                         daemon=True).start()

    def _stop_dashboard(self) -> None:
        stop, self._dash_stop = self._dash_stop, None
        if stop is not None:
            stop.set()
            dbgmod.get_logger("dashboard").info("poller stopped")

    def _dash_loop(self, stop: threading.Event) -> None:
        """Re-read the strip until the panel closes.

        A whole tick is wrapped: the readings run against a live game VM, so a
        client that is restarting, a daemon mid-rehijack or an expression a game
        update broke must cost one poll and a single log line — never the strip for
        the session, and never the panel.
        """
        while not stop.is_set():
            try:
                self._dash_tick()
            except Exception as exc:      # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                if err != self._dash_err:
                    self._dash_err = err
                    self._say("dash", "log.dash.unreadable", error=err)
                    dbgmod.get_logger("dashboard").warning(
                        "readings unreadable", exc_info=True)
            if stop.wait(DASH_POLL_SEC):
                return

    def _dash_tick(self) -> None:
        """One read of every reading, in one call into the game VM.

        Skipped entirely while a game action is in flight: the strip is a
        convenience and the action is the errand, and interleaving a read with a
        recipe's own calls buys a fresher number at the cost of the thing that
        matters. Skipped with the game or the daemon down too — there is nothing to
        read, and saying so once is the status row's job, not this loop's.
        """
        if self._busy:
            return
        if not self._daemon_up():
            return
        running, _text = game_status(self._game_exe())
        if not running:
            return
        lines = self._client.run(dashmod.build_chunk(), marker=dashmod.MARKER,
                                 settle=dashmod.SETTLE)
        values = dashmod.parse(lines)
        self._dash_err = ""
        self._dash_values = values
        self.after(0, self._render_dashboard)

    def _refresh_dashboard(self) -> None:
        """The ↻ beside the strip — one read, now, off the Tk thread."""
        def work() -> None:
            try:
                self._dash_tick()
            except Exception as exc:      # noqa: BLE001
                self._say("dash", "log.dash.unreadable", error=exc)
        threading.Thread(target=work, daemon=True).start()

    def _render_dashboard(self) -> None:
        """Paint the strip from the last readings."""
        view = getattr(self, "_dash_view", None)
        if view is None:
            return
        try:
            view.configure(state="normal")
            view.delete("1.0", "end")
            shown = dashmod.visible(self._dash_values)
            if not self._dash_values:
                view.insert("end", self._t("dash.pending"), ("label",))
            elif not shown:
                view.insert("end", self._t("dash.all_quiet"), ("cold",))
            else:
                for i, (reading, value) in enumerate(shown):
                    if i:
                        view.insert("end", "  ·  ", ("label",))
                    view.insert("end", self._t(reading.label_key) + " ", ("label",))
                    if value is None:
                        view.insert("end", dashmod.UNREADABLE, ("unread",))
                    else:
                        view.insert("end", str(value),
                                    ("cold",) if value == 0 else ("hot",))
            view.configure(state="disabled")
        except tk.TclError:
            pass                        # the tab is gone (panel closing)

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
        self._hook(self._retranslate_log_menu)
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

    # -- logging (panel/runtime/log.py holds the sink; the widget is this file's) --
    def _log_put(self, line: str) -> None:
        self._logbus.put(line)

    # -- the technical debug log (panel/debug_log.py) -----------------------
    def _configure_debug_log(self) -> None:
        """Point the shared rotating debug handler at the active profile's debug.log.

        Idempotent — the same call re-points the file on a profile switch without
        stacking handlers. The rotation is fixed (5 MiB × 3); only the destination
        follows the profile.
        """
        dbgmod.configure(self._profiles.debug_log())

    def _install_exception_logging(self) -> None:
        """Route uncaught errors — Tk callbacks and worker threads — into the debug log.

        Half the panel's work runs off the Tk thread (captures, robberies, the
        dashboard poll); an exception there vanished with the thread and left no
        trace. These hooks give every one of them a traceback in the debug log while
        keeping the default behaviour (the interpreter still prints it).
        """
        self.report_callback_exception = self._dbg_tk_exception
        prev = threading.excepthook

        def hook(args):
            dbg = getattr(self, "_dbg", None)
            if dbg is not None:
                name = getattr(args.thread, "name", "?")
                dbg.error("uncaught in thread %s", name,
                          exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            prev(args)

        threading.excepthook = hook

    def _dbg_tk_exception(self, exc, val, tb) -> None:
        """Tk's ``report_callback_exception``: log the traceback, then print it."""
        dbg = getattr(self, "_dbg", None)
        if dbg is not None:
            dbg.error("uncaught in a Tk callback", exc_info=(exc, val, tb))
        traceback.print_exception(exc, val, tb)


    def _dbg_status(self, game_ok: bool, daemon_warm: bool) -> None:
        """Record a systems snapshot: DEBUG every poll, INFO only when it changes.

        Runs on the Tk thread (the status poll's after-callback), so it can read the
        timer/trigger checkbuttons safely. This is the "statuses of systems" stream —
        daemon, game, how many timers/triggers are armed, and whether the dashboard
        poll is up or complaining.
        """
        dbg = getattr(self, "_dbg", None)
        if dbg is None:
            return
        try:
            timers_on = sum(1 for v in self._timer_vars.values()
                            if v.get("enabled") and v["enabled"].get())
            triggers_on = sum(1 for v in self._trigger_vars.values() if v.get())
        except (tk.TclError, AttributeError):
            timers_on = triggers_on = -1
        dash = "err" if self._dash_err else ("on" if self._dash_stop else "off")
        snap = (bool(game_ok), bool(daemon_warm), timers_on, triggers_on, dash)
        msg = ("systems: game=%s daemon=%s timers_on=%s triggers_on=%s dashboard=%s"
               % ("up" if game_ok else "down",
                  "warm" if daemon_warm else "down", timers_on, triggers_on, dash))
        if snap != self._dbg_status_prev:
            self._dbg_status_prev = snap
            dbg.info(msg)
        else:
            dbg.debug(msg)

    def _send_debug_archive(self) -> None:
        """«Отправить диагностику»: zip the debug logs and hand them to `debug_send_url`.

        The destination is a stub for now (no transport wired), so this always
        produces the zip and reports where it went — an empty URL means "do not send",
        which is not an error: the archive is still written for a by-hand hand-off.
        """
        url = self._opt_str("debug_send_url")
        path = self._profiles.debug_log()
        self._say("debug", "log.debug.packing")

        def work():
            try:
                status, archive, _detail = dbgsender.send(
                    url, path=path, logger=dbgmod.get_logger("sender"))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._say("debug", "log.debug.failed", error=exc))
                return
            rel = _repo_rel(archive)

            def done():
                if status == "disabled":
                    self._say("debug", "log.debug.no_dest", path=rel)
                elif status == "sent":
                    self._say("debug", "log.debug.sent", dest=url, path=rel)
                else:                 # "stub" — archive is ready, transport is not
                    self._say("debug", "log.debug.stub", path=rel, dest=url)
            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _say(self, tag: str, key: str, **fmt) -> None:
        """Log one translated line under ``[tag]``."""
        self._logbus.say(tag, key, **fmt)

    def _pump_log(self) -> None:
        drawn = False
        try:
            while True:
                line = self._logbus.q.get_nowait()
                stamp = time.strftime("%H:%M:%S")
                self._log_kept.append((stamp, line))
                if len(self._log_kept) > self._log_cap() * 2:
                    # The filter redraws from this list, so it is kept — but not
                    # without bound. Twice the widget's cap means a re-filter still
                    # has more history than the widget ever showed.
                    del self._log_kept[:len(self._log_kept) - self._log_cap()]
                if self._log_shown(line):
                    # One scroll for the whole drain, below — a tracer streaming a
                    # thousand lines a second must not make Tk chase the tail a
                    # thousand times in the same tick.
                    self._insert_line(stamp, line, scroll=False)
                    drawn = True
                self._append_log(line)
        except queue.Empty:
            pass
        if drawn:
            try:
                self._log.see("end")
            except tk.TclError:
                pass
        self._arm("log", 120, self._pump_log)

    # -- the on-disk mirror (panel/runtime/log.py) --------------------------
    def _open_panel_log(self) -> None:
        self._logbus.open_file(self._profiles.panel_log())

    def _close_panel_log(self) -> None:
        self._logbus.close_file()

    def _append_log(self, line: str) -> None:
        self._logbus.append_file(line)

    # -- severity, filtering, retention -------------------------------------
    _log_tag = staticmethod(runtime.log.tag_of)
    _log_severity = staticmethod(runtime.log.severity_of)

    def _log_cap(self) -> int:
        return self._opt_int("log_max_lines", low=200, high=200000)

    def _log_shown(self, line: str) -> bool:
        """Does the filter let this line through?

        The filter is display-only: everything is still written to panel.log and
        still kept for a redraw, so narrowing to `[secret]` and back loses nothing.
        """
        want = getattr(self, "_log_filter_var", None)
        if want is None:
            return True
        chosen = want.get()
        if not chosen or chosen == LOG_FILTER_ALL:
            return True
        return self._log_tag(line) == chosen

    def _insert_line(self, stamp: str, text: str, scroll: bool = True) -> None:
        """Insert one stamped log line: clock, severity colour, clickable coordinates.

        The clock is the thing that was missed every single session — "когда
        собралась база?" used to mean opening panel.log, because the widget carried
        no time at all while the file did.

        ``scroll=False`` skips the follow-the-tail scroll — a caller writing a whole
        batch (a drained queue, a filter redraw) scrolls once at the end instead of
        once per line, which is the difference between a tracer's burst arriving in
        a blink and the panel visibly stuttering through it.
        """
        clean = _ANSI.sub("", text)
        level = self._log_severity(clean)
        body_tags = (f"sev_{level}",) if level else ()
        self._log.insert("end", stamp + " ", ("stamp",))
        pos = 0
        for (s, e, _x, _y, _srv) in coords.parse(clean):
            if s > pos:
                self._log.insert("end", clean[pos:s], body_tags)
            self._insert_coord_link(self._log, clean[s:e])
            pos = e
        if pos < len(clean):
            self._log.insert("end", clean[pos:], body_tags)
        self._log.insert("end", "\n", body_tags)
        self._log_lines += 1
        self._trim_log()
        if scroll:
            self._log.see("end")

    # -- clickable coordinates: ONE binding per widget, not one per link -------
    #
    # A coordinate used to be written with a tag of its own (`c0`, `c1`, …) carrying
    # three fresh callbacks that closed over its x/y/server. Nothing ever took them
    # off again: `_trim_log` drops the TEXT, and a chat rebuild clears the view, but
    # a Tk tag and its bindings outlive the characters they were laid over. A panel
    # left running for a night therefore accumulated a tag, three Tcl commands and
    # three Python closures per coordinate it had ever printed — the "нарастающие
    # Tk-колбэки" behind the slow-down.
    #
    # The link needs no state of its own: the tagged text IS the coordinate, and
    # `coords.parse` reads it back. So the shared `coordlink` tag is bound once per
    # widget and the click resolves what was clicked from the range under the mouse.
    def _bind_coord_links(self, widget) -> None:
        """Install the coordinate-link handlers on a Text widget, once."""
        # The cursor to put back on Leave is whatever the widget normally shows —
        # "" in the log, "arrow" in a chat view — not a hardcoded one.
        try:
            rest = widget.cget("cursor")
        except tk.TclError:
            rest = ""
        widget.tag_bind("coordlink", "<Button-1>",
                        lambda ev, w=widget: self._on_coord_link_click(w, ev))
        widget.tag_bind("coordlink", "<Enter>",
                        lambda ev, w=widget: w.configure(cursor="hand2"))
        widget.tag_bind("coordlink", "<Leave>",
                        lambda ev, w=widget, c=rest: w.configure(cursor=c))

    def _insert_coord_link(self, widget, text: str) -> None:
        """Write ``text`` into ``widget`` as a coordinate that jumps when clicked.

        Shared by the log and the chat renderer — chat is where coordinates actually
        arrive (a rally target, a treasure, a base to hit), and it used to insert
        them as dead text while the log made them links.
        """
        self._coord_seq += 1          # how many links this session (health snapshot)
        widget.insert("end", text, ("coordlink",))

    def _on_coord_link_click(self, widget, event) -> None:
        """Jump to the coordinate under the pointer, read back off the widget."""
        try:
            here = widget.index(f"@{event.x},{event.y}")
            span = widget.tag_prevrange("coordlink", f"{here} +1c")
            text = widget.get(*span) if span else ""
        except tk.TclError:
            return
        hits = coords.parse(text)
        if not hits:
            return
        _s, _e, x, y, srv = hits[0]
        self._on_coord_click(x, y, srv)

    def _bind_photo_links(self, widget) -> None:
        """Install the chat-photo handlers on a Text widget, once — see above."""
        widget.tag_bind("photolink", "<Button-1>",
                        lambda ev, w=widget: self._on_photo_link_click(w, ev))
        widget.tag_bind("photolink", "<Enter>",
                        lambda ev, w=widget: w.configure(cursor="hand2"))
        widget.tag_bind("photolink", "<Leave>",
                        lambda ev, w=widget: w.configure(cursor="arrow"))

    def _on_photo_link_click(self, widget, event) -> None:
        """Open the photo under the pointer full-size — which one is read off the
        embedded image, not off a tag that had to be kept alive to remember it."""
        try:
            here = widget.index(f"@{event.x},{event.y}")
            found = widget.dump(here, f"{here} +1c", image=True)
        except tk.TclError:
            return
        meta = self._photo_meta.get(found[0][1]) if found else None
        if meta is not None:
            self._open_photo(*meta)

    def _trim_log(self) -> None:
        """Keep the widget bounded — drop the oldest block when it overflows.

        A block at a time, not a line: trimming per insert would run the delete on
        every single line once the cap is reached, which is the cost this is here to
        avoid in the first place.
        """
        cap = self._log_cap()
        if self._log_lines <= cap + LOG_TRIM_BLOCK:
            return
        drop = self._log_lines - cap
        try:
            self._log.delete("1.0", f"{drop + 1}.0")
        except tk.TclError:
            return
        self._log_lines -= drop

    def _redraw_log(self) -> None:
        """Repaint the widget from the kept lines — after a filter change.

        Only the last `cap` matching lines: a session that has scrolled far past the
        cap must not become slow the moment somebody narrows the filter.
        """
        try:
            self._log.delete("1.0", "end")
        except tk.TclError:
            return
        self._log_lines = 0
        shown = [(s, ln) for s, ln in self._log_kept if self._log_shown(ln)]
        for stamp, line in shown[-self._log_cap():]:
            self._insert_line(stamp, line, scroll=False)
        try:
            self._log.see("end")
        except tk.TclError:
            pass

    def _clear_log(self) -> None:
        """Empty the widget (and the history behind it). panel.log is untouched."""
        self._log_kept.clear()
        try:
            self._log.delete("1.0", "end")
        except tk.TclError:
            pass
        self._log_lines = 0

    # -- daemon lifecycle ---------------------------------------------------
    def _startup(self) -> None:
        self._boot_at("splash.monitors", 0.68)
        # A tab that declares itself EAGER is loaded here rather than on first show:
        # the rally monitor is a capture whose whole point is being up before the rally
        # goes out, and nobody has opened a tab yet. Idempotent, so the first show
        # calling it again costs nothing.
        for tab in getattr(self, "_plugin_tabs", {}).values():
            if tab.EAGER:
                tab.ensure_loaded()
        if self._chat_var.get():            # chat monitor, if the profile had it on
            self._start_chat()
        # Drawing the history is the heaviest thing the boot does to the widgets, so
        # it is WAITED for, not fired and forgotten: it used to be posted here and
        # rendered whenever the mainloop got round to it, which was after the splash
        # had gone and the window was supposedly ready.
        self._boot_at("splash.chat", 0.76)
        self._on_tk(self._load_chat_history)
        # The schedule runs whenever the panel is open: the thread is started
        # unconditionally and a tick with every row unticked costs one dict
        # comparison, which keeps switching a timer on a matter of the checkbox
        # alone (no start/stop plumbing to get out of step with it).
        self._boot_at("splash.schedule", 0.82)
        self._schedule.start()
        self._boot_at("splash.daemon", 0.90)
        self._ensure_daemon()
        # The server used to be read here to fill the «Сервер» box of the jump block.
        # That block is gone (#1183) and `_jump` reads the current server for itself,
        # so the boot no longer spends a game round trip on it.
        # The strip needs a warm daemon and a live game, so it starts last.
        self._start_dashboard()
        self._boot_at("splash.systems", 1.0)

    # -- repeating callbacks: one chain per name, always -----------------------
    #
    # Every `after` that re-arms itself is a loop, and two of the same loop is a
    # panel that ticks twice as often for the rest of the session — invisible from
    # the outside, permanent, and cumulative if it happens again. Today each of them
    # is started from exactly one place, but that is a property of the call graph,
    # not of the code: one `self._refresh_timer_rows()` added to the grid rebuild
    # (which runs on every «перезагрузить») and the schedule would gain a chain per
    # press, for ever.
    #
    # So a loop is not armed with a bare `after` any more. `_arm` keeps the pending
    # id under a name and cancels the previous one first, which makes "started
    # twice" impossible rather than merely absent: the second start replaces the
    # first instead of racing it. `_disarm` is the same guarantee at the other end —
    # a pending callback must not fire into a window that is being torn down.
    def _arm(self, name: str, delay_ms: int, func) -> None:
        """(Re)arm the repeating callback ``name`` — cancelling any pending one."""
        self._tick.arm(name, delay_ms, func)

    def _disarm(self, name: str) -> None:
        """Cancel the pending callback under ``name``, if there is one."""
        self._tick.disarm(name)

    def _disarm_all(self) -> None:
        self._tick.disarm_all()

    # -- is the panel still healthy after three days? ------------------------
    def _start_health_watch(self) -> None:
        """Arm the periodic health snapshot (see HEALTH_SNAPSHOT_MS)."""
        self._health_prev: dict = {}
        self._arm("health", HEALTH_SNAPSHOT_MS, self._health_snapshot)

    def _health_snapshot(self) -> None:
        """Write what could be growing into the debug log, and re-arm.

        Everything here is a count of something the panel accumulates while it is
        open. `after` is the one that matters most: a self-rearming chain started
        twice doubles every tick from then on, and it is invisible from the outside
        — the panel just gets slower. The rest are the caches and registries whose
        bounds this file promises.
        """
        try:
            pending = len(self.tk.call("after", "info"))
        except tk.TclError:
            pending = -1
        now = {
            "after": pending,
            "threads": threading.active_count(),
            "tr": self._i18n.registry_size(),
            "log_tags": self._tag_count(getattr(self, "_log", None)),
            "chat_tags": sum(self._tag_count(v) for v in self._chat_trees.values()),
            "log_lines": self._log_lines,
            "log_kept": len(self._log_kept),
            "chat_msgs": sum(len(v) for v in self._chat_msgs.values()),
            "images": len(self._chat_img_cache),
            "links": self._coord_seq,
            "photos": self._photo_seq,
        }
        # INFO on the first snapshot and whenever something moved; the steady state
        # is not worth a line every five minutes.
        line = " ".join(f"{k}={v}" for k, v in now.items())
        if now != self._health_prev:
            self._dbg.info("health %s", line)
            self._health_prev = now
        else:
            self._dbg.debug("health %s", line)
        self._arm("health", HEALTH_SNAPSHOT_MS, self._health_snapshot)

    @staticmethod
    def _tag_count(widget) -> int:
        """How many tags a Text widget carries (0 for anything else)."""
        if widget is None:
            return 0
        try:
            return len(widget.tag_names())
        except (tk.TclError, AttributeError):
            return 0

    def _on_tk(self, func, timeout: float = 20.0) -> None:
        """Run ``func`` on the Tk thread from a worker and wait for it to finish."""
        self._tick.on_tk(func, timeout)

    def _ensure_daemon(self) -> bool:
        """Make sure this profile's daemon is up (panel/runtime/daemon.py). Blocks."""
        return self._game.ensure()

    def _restart_daemon(self) -> None:
        """The ⭮ beside the daemon indicator: shut the daemon down and bring it back."""
        threading.Thread(target=self._game.restart, daemon=True).start()

    def _daemon_state(self, state: str, ok) -> None:
        """Paint the daemon indicator from the link, whichever thread reports it.

        The link says what happened in one word; the words the operator reads are this
        window's business, and so is getting onto the Tk thread to write them.
        """
        key = {"warm": "daemon.warm", "starting": "daemon.starting",
               "error": "daemon.error"}.get(state, "daemon.none")
        try:
            self.after(0, lambda: self._set_daemon(self._t(key), ok))
        except (tk.TclError, RuntimeError):      # the window is going away
            pass

    def _set_daemon(self, text: str, ok) -> None:
        color = "#3c3" if ok else ("#888" if ok is None else "#c33")
        self._daemon_var.set(text)
        self._daemon_lbl.configure(foreground=color)

    # -- status: read on a clock, not only when something asks ---------------
    #
    # `_refresh_status` used to run at start-up, after an action and on ↻ — and
    # nowhere else. The game is crash-prone, so the panel could sit for an hour
    # showing "running (pid …)" over a dead client while every timer tick failed
    # into the retry hold. A poll is a process-list scan off the Tk thread: free.
    def _poll_status(self) -> None:
        self._refresh_status()
        self._arm("status", STATUS_POLL_MS, self._poll_status)

    def _refresh_status(self) -> None:
        # One reading at a time. The poll fires every eight seconds and the reading
        # is a process-list scan plus a socket probe of the daemon: both are quick
        # while things are well, and both can hang for far longer than eight seconds
        # when they are not (a wedged daemon holds the connect until it times out).
        # Without this, an unhealthy daemon quietly grew a thread per poll for as
        # long as it stayed unhealthy.
        if self._status_busy:
            return
        self._status_busy = True

        def work() -> None:
            try:
                ok, s = game_status(self._game_exe())
                warm = self._daemon_up()
            finally:
                self._status_busy = False
            self.after(0, lambda: (
                self._status_var.set(s),
                self._status_lbl.configure(foreground="#3c3" if ok else "#c33"),
                self._set_daemon(self._t("daemon.warm") if warm else self._t("daemon.none"), warm),
                self._dbg_status(ok, warm),
                self._watchdog_check(ok)))
        threading.Thread(target=work, daemon=True).start()

    def _watchdog_check(self, running: bool) -> None:
        """Notice the client dying, and put it back if asked to.

        Runs on the Tk thread off every status poll. Two things make it safe to
        leave on overnight:

          * WATCHDOG_STRIKES consecutive dead readings, not one. A single scan can
            race the process table, and the client legitimately restarts itself once
            after the first login — relaunching *that* would fight the game.
          * a cooldown between relaunches. A client that dies during start-up would
            otherwise be relaunched every eight seconds until morning.

        A crash is announced whether or not the watchdog is on: knowing the client
        went away is worth a log line even when putting it back is the person's job.
        """
        if running:
            if self._game_gone >= WATCHDOG_STRIKES:
                self._say("game", "log.game.back")
            self._game_gone = 0
            self._game_was_up = True
            return
        self._game_gone += 1
        if self._game_gone != WATCHDOG_STRIKES:
            return                        # counting, or already reported
        if self._game_was_up:
            self._say("game", "log.game.gone")
        if not self._opt_bool("watchdog"):
            return
        since = time.time() - self._watchdog_last
        if since < WATCHDOG_COOLDOWN_SEC:
            self._say("game", "log.game.watchdog_hold", mins=int(since // 60))
            return
        self._watchdog_last = time.time()
        self._say("game", "log.game.watchdog_relaunch")
        self._rt.play_async("launch_game")

    # -- one control that stops everything ----------------------------------
    def _panic(self) -> None:
        """«Стоп всё» — every monitor, watcher, sweep, scenario and the schedule.

        The moment you want this is the moment the game is misbehaving, and until now
        it was five separate clicks across three tabs. The schedule is stopped too:
        leaving it running would have a timer fire into whatever went wrong a few
        seconds later.

        A scenario in flight is ASKED to stop (it halts at its next step) rather than
        killed, so nothing is left half-sent to the game — same as the Scenarios
        tab's own Stop.
        """
        self._say("panel", "panic.log")
        for var, stop in ((self._chat_var, self._stop_chat),):
            var.set(False)
            stop()
        # …and each plugin tab stops whatever it holds — one loop, so a tab added
        # later cannot be the one «Стоп всё» quietly does not reach.
        for tab in getattr(self, "_plugin_tabs", {}).values():
            tab.panic()
        self._schedule.stop()
        self._say("panel", "panic.done")

    def _current_server(self) -> str:
        """Which server the client is on (panel/runtime/daemon.py owns the read)."""
        return self._game.current_server()

    # -- one way to run a child ---------------------------------------------
    def _child(self, tag: str, cmd: list, *, on_line=None, on_exit=None,
               capture_stderr: bool = True) -> "childmonmod.ChildMonitor":
        """A :class:`panel.childmon.ChildMonitor` wired to this panel."""
        return self._children.spawn(tag, cmd, on_line=on_line, on_exit=on_exit,
                                    capture_stderr=capture_stderr)

    # -- the secret-task capture went with its tab (panel/tabs/secret_tasks/) -
    #
    # The child, the panel-side line filter, the findings log and the nudge that
    # re-merges the checkpoint are all beside the list they feed now.

    # -- rally monitoring, the alert and the join all moved to the «Ралли» tab
    # (panel/tabs/rally/): the capture child, the de-duplicated alert, the
    # «Присоединиться» press and the squads «Авторалли» allows are its own now.

    # -- the wire watcher's listeners went to the runtime ---------------------
    #
    # Spawning a trigger's listener, noticing one died and polling a check are
    # panel/runtime/schedule.py's. They were here because they need a child process
    # and a log line; neither needs a window, and both have to work in a profile that
    # shows no Timers tab.

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
    # -- «Автолут ★» went with its tab (panel/tabs/secret_tasks/autoloot.py) -
    #
    # The watcher, the event-driven listener, the rule they both obey and the day's
    # budget are the tab's own. It is the one piece of this panel where a bug does not
    # fail loudly — it quietly spends a robbery on the wrong level (#1099) — so it
    # lives beside the range that aims it.

    # -- Develop menu: raw sniffers -----------------------------------------
    def _spawn_sniffer(self, cmd: list, tag: str) -> "subprocess.Popen | None":
        """A raw child whose stdout a reader thread streams (panel/runtime/children.py)."""
        return self._children.spawn_raw(cmd, tag)

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

        self._say("traffic", "log.traffic.starting")
        self._sniff_proc = self._spawn_sniffer(
            [self._python(), "-u", TRAFFIC_SNIFFER] + label_args, "traffic")
        if self._sniff_proc is not None:
            self._sniff_ready["traffic"] = None
            self._say("traffic", "log.traffic.started", pid=self._sniff_proc.pid)
            threading.Thread(target=self._sniff_reader, args=(self._sniff_proc,),
                             daemon=True).start()

        # No --filter and no --dedup: the recording on disk must be COMPLETE. A
        # capture filter (the old `--filter SFS`) trimmed the file to the wire and hid
        # every UI/Manager call — the exact blind spot that made past trace analyses
        # wrong. --dedup is no good either: it keeps only the FIRST call of each name,
        # so opening a window, picking an amount, confirming and collecting lands as
        # one click and one message, the repeats gone at write time. So the child runs
        # unfiltered — every call, with full args, into results/traces/. TRACE_FILTER
        # survives only as the panel LOG's display filter (see `_trace_show`), so the
        # Tk widget stays readable while the file keeps everything.
        self._say("trace", "log.trace.starting", filter=self._trace_filter())
        # A graceful-stop flag path (task #1084): _stop_sniff drops this file so the
        # tracer breaks its loop and runs its own restore + closes the trace file,
        # rather than being hard-killed. Unique per run so two runs never share one.
        self._trace_stop_flag = os.path.join(
            tempfile.gettempdir(), f"lw_trace_stop_{os.getpid()}_{int(time.time())}.flag")
        try:
            os.path.exists(self._trace_stop_flag) and os.remove(self._trace_stop_flag)
        except OSError:
            pass
        self._trace_proc = self._spawn_sniffer(
            [self._python(), "-u", FUNCTION_SNIFFER,
             "--stop-flag", self._trace_stop_flag] + label_args,
            "trace")
        if self._trace_proc is not None:
            self._sniff_ready["trace"] = None
            self._say("trace", "log.trace.started", pid=self._trace_proc.pid)
            threading.Thread(target=self._trace_reader, args=(self._trace_proc,),
                             daemon=True).start()

        if self._sniff_proc is None and self._trace_proc is None:
            self._sniff_var.set(False)
            return
        self._say("sniff", "log.sniff.waiting")
        self._arm("sniff_ready", int(self._sniff_timeout() * 1000), self._sniff_ready_watchdog)

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
            self._say("sniff", "log.sniff.ready", sec=f"{dt:.1f}")
        elif live:
            self._say("sniff", "log.sniff.partial", sec=f"{dt:.1f}",
                      live=", ".join(live))
        else:
            self._say("sniff", "log.sniff.not_ready", sec=f"{dt:.1f}")

    def _sniff_ready_watchdog(self) -> None:
        """Never leave the log on "жду готовности" if a marker never arrives."""
        if self._sniff_proc is None and self._trace_proc is None:
            return                                   # session already over
        pending = [p for p, v in self._sniff_ready.items() if v is None]
        if pending:
            self._say("sniff", "log.sniff.unconfirmed",
                      sec=f"{self._sniff_timeout():.0f}", pending=", ".join(pending))

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
            self._say("traffic", "log.traffic.ended")
            self._sniff_proc = None
            self._mark_sniff_ready("traffic", False)  # died before reporting: nothing captured
            self._sync_sniff_var()

    def _trace_show(self, line: str) -> bool:
        """Should this tracer line reach the panel's log widget?

        The trace FILE is complete — the child writes every call to it regardless of
        this. The Tk log, though, would drown in an unfiltered trace and freeze the
        panel, so only the `XSCALL` call lines whose name matches the display filter
        (TRACE_FILTER, UI-only) are shown. Everything else — the `[lua_trace]` status
        lines, the `XSTRACE` install/restore summaries, the readiness and run-file
        markers — is low-volume and always shown, and the session's bookkeeping rides
        on it. An empty filter shows everything (the operator asked to see it all).
        """
        if "XSCALL" not in line:
            return True
        keys = [k.strip() for k in (self._trace_filter() or "").split(",") if k.strip()]
        if not keys:
            return True
        return any(k in line for k in keys)

    def _trace_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                # The file keeps every line (the child writes it); the panel log shows
                # only what the display filter lets through, so an unfiltered recording
                # cannot freeze the Tk widget.
                if self._trace_show(line):
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
            self._say("trace", "log.trace.ended")
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
            self._arm("sniff_flush", SNIFF_FLUSH_MS, self._finish_sniff_session)

    def _stop_sniff(self) -> None:
        proc, self._sniff_proc = self._sniff_proc, None
        if proc is not None:
            self._say("traffic", "log.traffic.stopped")
            try:
                proc.terminate()
            except Exception:
                pass
        proc, self._trace_proc = self._trace_proc, None
        if proc is not None:
            self._say("trace", "log.trace.stopped")
            # Ask the tracer to stop GRACEFULLY first (task #1084): drop its
            # --stop-flag so it breaks its tail loop and runs its own atexit/finally —
            # restore()ing the ~8700 wrapped Lua functions and closing the trace file.
            # A hard proc.terminate() (TerminateProcess on Windows) runs NEITHER, which
            # is why the hooks used to stay live in the VM and keep lagging the game
            # after a sniff (#1086). All of it — the wait, the fallback hard kill, and
            # an idempotent daemon-side RESTORE_CHUNK as the safety net — runs off the
            # Tk thread so Stop never freezes the UI.
            flag = getattr(self, "_trace_stop_flag", None)
            threading.Thread(target=self._graceful_stop_trace, args=(proc, flag),
                             daemon=True).start()

        # Ask what this run was, once the killed children have let go of their
        # files. The delay is not about buffering (both write line-buffered) but
        # about the last lines still travelling through the reader threads — the
        # traffic child announces its transcript path early, the tracer's «trace
        # file:» line can still be in flight when a very short run is stopped.
        self._arm("sniff_flush", SNIFF_FLUSH_MS, self._finish_sniff_session)

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
        text = ScrolledText(frm, height=4, width=64, wrap="word")
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
            self._say("sniff", "log.sniff.discarded", n=len(gone))

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
            self._say("sniff", "log.sniff.kept_bare")
            return
        try:
            written = run_notes.write_note(paths, description, label=label)
        except Exception as exc:      # noqa: BLE001  (a note must never break the panel)
            self._say("sniff", "log.sniff.note_failed", error=exc)
            return
        names = ", ".join(_repo_rel(p) for p in written)
        self._say("sniff", "log.sniff.kept", path=names or "—")

    def _run_file_caption(self, kind: str, path: str) -> str:
        """One line of the dialog's info block: path, size and what is inside."""
        stats = run_notes.run_stats(path)
        size = stats["size"]
        human = f"{size / 1024:.0f} KB" if size >= 1024 else f"{size} B"
        return self._t(f"develop.run.file.{kind}", path=_repo_rel(path),
                       size=human, records=stats["records"])

    def _graceful_stop_trace(self, proc, flag) -> None:
        """Stop the tracer cleanly, then make sure the VM is unhooked (off the Tk thread).

        The order is belt-and-suspenders (task #1084):

          1. drop the ``--stop-flag`` file so the tracer breaks its own loop and runs
             ``restore()`` + closes its trace file — the clean exit a hard kill skips;
          2. give it a moment; if it has not gone, ``terminate()`` it (hard kill);
          3. either way run the idempotent ``RESTORE_CHUNK`` over the daemon — it
             reports "nothing installed" when the child already cleaned up, so a
             redundant restore is harmless, and a genuinely-missed one is caught.
        """
        if flag:
            try:
                with open(flag, "w", encoding="utf-8") as fh:
                    fh.write("stop")             # its existence is the whole signal
            except OSError:
                flag = None
            deadline = time.time() + TRACE_GRACEFUL_SEC
            while time.time() < deadline:
                if proc.poll() is not None:
                    break                        # it exited on its own — restore ran
                time.sleep(0.1)
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:                    # noqa: BLE001 — already gone is fine
                pass
        self._restore_trace_hooks()
        if flag:
            try:
                os.remove(flag)
            except OSError:
                pass

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
            ev = lua_client.get_evaluator(port=self._daemon_port())
        except Exception as exc:      # noqa: BLE001
            self._say("trace", "log.trace.no_evaluator", error=exc)
            return
        try:
            for attempt in range(3):
                out = ev.run(lua_trace.RESTORE_CHUNK, marker="XSTRACE", settle=1.5 + attempt)
                if any("XSTRACE restored" in ln for ln in out):
                    self._say("trace", "log.trace.unhooked", detail="; ".join(out))
                    return
            self._say("trace", "log.trace.unhook_unconfirmed")
        except Exception as exc:      # noqa: BLE001  (teardown must never crash)
            self._say("trace", "log.trace.unhook_failed", error=exc)
        finally:
            try:
                ev.close()
            except Exception:
                pass

    # -- jump routing (shared by the entry button and clickable coords) -----
    def _jump(self, x: int, y: int, server, quiet: bool = False) -> bool:
        """Walk the camera to a tile (panel/runtime/daemon.py owns it).

        A log link, a «Командный пункт» row and a scenario's `JUMP` all come through
        here, and so does a tab launched on its own — which is why the jump is the game
        link's rather than this window's.
        """
        return self._game.jump(x, y, server, quiet=quiet)

    def _on_coord_click(self, x: int, y: int, server) -> None:
        self._say("coord", "log.coord.clicked", where=coords.fmt(x, y, server))
        self._jump(x, y, server)

    # `_goto_coord` (the «Перейти» button), the «куда ходил» history and its
    # `_remember_jump` / `_set_jump_history` / `_on_jump_history` went with the
    # «Навигация» block (#1183). Every remaining caller of `_jump` already knows the
    # coordinate it wants: a log link, a «Командный пункт» row, a scenario's `JUMP`.

    # -- generic action -----------------------------------------------------
    # -- one game action at a time ------------------------------------------
    def _claim_busy(self, owner: str = "panel") -> bool:
        """Take the right to drive the game, or say it is already taken.

        Two locks — this process's flag and the daemon's lease, so a tab launched on
        its own cannot drive the same client at the same time. See
        panel/runtime/daemon.py for why the daemon's answer is the authoritative one.
        """
        return self._game.claim(owner)

    def _release_busy(self) -> None:
        self._game.release()

    def _act(self, chunk: str, tag: str, label: str, settle: float = 1.2) -> None:
        if not self._claim_busy():
            self._say("panel", "busy")
            return
        self._log_put(f"[{tag}] {label}")

        def work() -> None:
            try:
                if not self._daemon_up() and not self._ensure_daemon():
                    self._say(tag, "log.no_daemon")
                    return
                for ln in self._client.run(chunk, marker="ACT", settle=settle):
                    self._log_put(f"[{tag}] {ln}")
                self._say(tag, "log.done")
            except Exception as exc:
                self._say(tag, "log.error", error=exc)
            finally:
                self._release_busy()
                self.after(400, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    # -- game lifecycle -----------------------------------------------------
    def _launch_game(self) -> None:
        # Launch through the same DSL recipe the bot uses: actions/launch_game.md
        # (LAUNCH the launcher, then WAIT for the base screen). One source of truth
        # for "start the game", shared by the panel and any scripted run.
        self._say("game", "log.game.launching")
        self._rt.play_async("launch_game")

    def _restart_game(self) -> None:
        exe = self._game_exe()

        def work() -> None:
            self._say("game", "log.game.killing", exe=exe)
            try:
                r = subprocess.run(["taskkill", "/F", "/IM", exe],
                                   capture_output=True, text=True, creationflags=NO_WINDOW)
                self._log_put(f"[game] taskkill: {(r.stdout or r.stderr).strip() or 'ok'}")
            except Exception as exc:
                self._say("game", "log.game.kill_failed", error=exc)
            time.sleep(1.0)
            # Relaunch via the recipe (waits for the base screen, then daemon
            # re-initialises on the next action).
            self._rt.play_async("launch_game")
        threading.Thread(target=work, daemon=True).start()

    # -- the map sweep: walk the camera so the passive scan sees something ----
    #
    # The capture only learns tiles while the map is MOVING (it is a pcap of the
    # client's own `world.get.block` traffic), so «Автолут ★» stood still unless a
    # person dragged the map. panel/mapsweep.py decides the waypoints; this drives
    # them, one `_jump` at a time.
    #
    # Every jump goes through the SAME busy claim a button press does, so a sweep
    # never overlaps a timer errand or a recipe — it simply loses that waypoint's
    # turn and takes the next one when the errand is done. That is the right way
    # round: the errand is the work, the sweep is the wrist.
    # -- «Автообъезд карты» went with its tab (panel/tabs/secret_tasks/sweep.py)
    #
    # The camera walk that keeps the passive capture fed: the box, the waypoints and
    # the pass-and-rest loop. panel/mapsweep.py is still the geometry.

    # -- «Операция Призрак» went with the «Секретный командный пункт» tab -----
    #
    # The watcher, the open-day read that gates it and the child that robs are
    # panel/tabs/command_post/ghost.py — beside the page that lists the squads and the
    # box that switches the order on.

    # -- one DSL line, typed --------------------------------------------------
    def _run_command(self) -> None:
        """Run whatever is in the command box through the recipe interpreter.

        The very same `run_text` a timer's inline step goes through, so a line that
        works here works verbatim in a timer or a recipe — which is the point. It
        claims the busy flag like every other game action, so it queues behind
        nothing and races nothing.
        """
        text = self._cmd_var.get().strip()
        if not text:
            return
        if not self._cmd_hist or self._cmd_hist[-1] != text:
            self._cmd_hist.append(text)
        self._cmd_at = len(self._cmd_hist)
        self._cmd_var.set("")
        if not self._claim_busy():
            self._say("cmd", "busy")
            return
        self._log_put(f"[cmd] {text}")

        def work() -> None:
            try:
                if not self._daemon_up() and not self._ensure_daemon():
                    self._say("cmd", "log.no_daemon")
                    return
                ctx = self._actions.context(
                    hwnd=0, on_event=lambda msg: self._log_put(f"[cmd] {msg}"))
                ok = self._actions.run_text(text, ctx=ctx, label="cmd")
                self._say("cmd", "cmd.ok" if ok else "cmd.failed")
            except Exception as exc:                       # noqa: BLE001
                self._say("cmd", "log.error", error=exc)
            finally:
                self._release_busy()
                self.after(400, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    def _cmd_recall(self, delta: int) -> str:
        """Up / Down through what has been typed — a debugging loop is one line
        with one number changed, over and over."""
        if not self._cmd_hist:
            return "break"
        self._cmd_at = max(0, min(len(self._cmd_hist), self._cmd_at + delta))
        self._cmd_var.set(self._cmd_hist[self._cmd_at]
                          if self._cmd_at < len(self._cmd_hist) else "")
        return "break"

    def _show_button_reference(self) -> None:
        """The `TAP` vocabulary as a window: name · label · xall · cap.

        tools/lib/game_buttons.py is what `TAP` speaks and a person writing a recipe
        in the panel's own editor had no way to see the list without opening the
        source. Double-clicking a row drops `TAP <name>` into the command box, so the
        reference and the box are one tool.
        """
        win = tk.Toplevel(self)
        win.title(self._t("cmd.reference.title"))
        win.transient(self)
        win.geometry("620x460")
        frm = ttk.Frame(win, padding=8)
        frm.pack(fill="both", expand=True)
        self._tr(ttk.Label(frm, foreground="#888", wraplength=580, justify="left"),
                 "cmd.reference.hint").pack(anchor="w", pady=(0, 6))
        cols = ("name", "label", "xall")
        tree = ttk.Treeview(frm, columns=cols, show="headings", height=16)
        for col, width in zip(cols, (170, 330, 60)):
            tree.heading(col, text=self._t(f"cmd.reference.col.{col}"))
            tree.column(col, width=width, anchor="w")
        sb = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for name in game_buttons.names():
            btn = game_buttons.get(name)
            if btn is None:
                continue
            xall = f"≤{btn.max_taps}" if btn.count_lua else "—"
            tree.insert("", "end", values=(name, btn.label, xall))

        def take(_event=None) -> None:
            sel = tree.selection()
            if not sel:
                return
            name = tree.item(sel[0], "values")[0]
            self._cmd_var.set(f"TAP {name}")
            win.destroy()

        tree.bind("<Double-Button-1>", take)
        ttk.Button(frm, text=self._t("cmd.reference.take"), command=take).pack(
            side="bottom", anchor="e", pady=(6, 0))

    def _on_close(self) -> None:
        # A debounced edit is still pending for up to a second — write it before
        # the window goes, or the last thing typed is the thing that is lost.
        self._save_settings()   # geometry and the sash, as the operator left them
        # Every plugin tab goes with the window: the rally monitor's child, a bus
        # subscription, anything else a tab is holding.
        for tab in getattr(self, "_plugin_tabs", {}).values():
            tab.shutdown()
        self._stop_dashboard()
        self._stop_sniff()      # stops both the traffic sniffer and the tracer
        self._stop_chat()
        if self._chat_store is not None:
            self._chat_store.close()
            self._chat_store = None
        self._schedule.stop()
        self._close_panel_log()
        # Every repeating callback goes with the window. One that fires into a
        # half-torn-down panel is a traceback nobody sees and a log line nobody
        # gets, because the log has just been closed above.
        self._disarm_all()
        self._dbg.info("panel closing")
        dbgmod.shutdown()
        self.destroy()

    # -- window geometry, remembered per profile -----------------------------
    def _current_geometry(self) -> str:
        try:
            return self.winfo_geometry()
        except tk.TclError:
            return ""

    def _current_sash(self) -> int:
        """Where the operator left the log's sash, in pixels from the top."""
        split = getattr(self, "_main_split", None)
        if split is None:
            return 0
        try:
            return int(split.sashpos(0))
        except (tk.TclError, IndexError):
            return 0

    def _restore_geometry(self) -> None:
        """Put the window and the sash back where they were.

        The sash needs the window to have been laid out first (its position is in
        pixels and there are none before the first idle pass), which is why this is
        an `after` rather than a call.
        """
        geom = str(self._settings.get("window_geometry") or "").strip()
        if geom:
            try:
                self.geometry(geom)
            except tk.TclError:
                pass
        sash = self._settings.get("log_sash")
        try:
            sash = max(int(sash), 0)
        except (TypeError, ValueError):
            sash = 0
        self.after(200, lambda: self._apply_sash(sash))

    def _apply_sash(self, sash: int = 0) -> None:
        """Put the main tab's sash ``sash`` px from the top — or, with 0, where the
        control blocks naturally end.

        Bounded at both ends, because a remembered pixel count is a poor answer on
        any window it was not measured on. The top pane never gets more than the
        blocks ask for (the surplus would be dead space above the sash), and never
        so much that the log below is squeezed out of sight — which is what a
        window too short for both used to do to «Автолут секреток» and «Автолут
        Призрака» (#1153). The blocks scroll now, so bounding the pane costs
        nothing: what does not fit is reachable rather than cut off.
        """
        split = getattr(self, "_main_split", None)
        controls = getattr(self, "_main_controls", None)
        if split is None:
            return
        try:
            self.update_idletasks()
            want = int(controls.winfo_reqheight()) if controls is not None else 0
            total = int(split.winfo_height())
            if want > 0:
                sash = want if sash <= 0 else min(sash, want)
            if total > 0:
                # Half the pane is the floor's own floor: on a window too short for
                # both there is no split that pleases anybody, and an even one at
                # least leaves each side something to show.
                sash = min(sash, max(total - LOG_MIN_HEIGHT, total // 2))
            if sash > 0:
                split.sashpos(0, sash)
        except (tk.TclError, IndexError, ValueError):
            pass

    # -- resizing the window ------------------------------------------------

    def _install_resize_damper(self) -> None:
        """Make dragging the window frame cheap.

        Every single size change repaints the whole window, and with an open tab
        that is several hundred widgets — around 400 ms of painting per step on the
        busiest tabs, which is why pulling the frame crawled at a few frames a
        second. The layout itself is not the problem: with painting switched off the
        same drag costs 4 ms a step, Tk re-flowing everything included.

        So painting is switched off for the length of the drag and switched back on
        once the size has been still for `RESIZE_SETTLE_MS`, which repaints the
        window once, at its final size. Nothing is deferred but the pixels — every
        widget is already sitting where it belongs when that repaint happens.

        What that costs: while the frame is actually moving, a window being made
        bigger shows a bare strip along the edge it grew by — nothing paints there
        until the drag settles. Pausing mid-drag fills it in, letting go of the
        frame fills it in, and it beats the alternative of a few frames a second.

        A one-off resize (maximise, restore, a geometry set from code) is a drag of
        one step as far as this is concerned: it shows its result a settle-time
        later. Windows only; elsewhere the damper is simply not installed.
        """
        self._resize_size = (self.winfo_width(), self.winfo_height())
        self._resize_job = None         # settle timer, while a resize is in flight
        self._paint_off = False
        self._paint_hwnd = None
        if os.name != "nt":
            return
        self.bind("<Configure>", self._on_window_configure, add="+")

    def _on_window_configure(self, event) -> None:
        # A <Configure> binding on a toplevel also hears every child's own resize
        # (Tk puts the toplevel in each child's bind tags), and it hears window
        # *moves* too — neither is a window resize, so both are dropped here.
        if event.widget is not self:
            return
        size = (event.width, event.height)
        if size == self._resize_size:
            return
        self._resize_size = size
        # Order matters: the timer that puts painting back is armed even if
        # cancelling the old one goes wrong, because a window left with its
        # painting switched off and no timer to switch it back is a frozen panel.
        try:
            if self._resize_job is not None:
                self.after_cancel(self._resize_job)
        except (tk.TclError, ValueError):
            pass
        self._resize_job = self.after(RESIZE_SETTLE_MS, self._settle_resize)
        self._suspend_painting()

    def _settle_resize(self) -> None:
        """The size has been still long enough — put the picture back up."""
        self._resize_job = None
        self._resume_painting()

    def _window_handle(self) -> int:
        if self._paint_hwnd is None:
            try:
                self._paint_hwnd = int(self.wm_frame(), 16)
            except (tk.TclError, ValueError):
                self._paint_hwnd = 0
        return self._paint_hwnd

    def _suspend_painting(self) -> None:
        """Tell Windows to stop painting this window (a drag is in progress)."""
        if self._paint_off:
            return
        hwnd = self._window_handle()
        if not hwnd:
            return
        try:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETREDRAW, 0, 0)
        except Exception:            # noqa: BLE001 — never break a resize over this
            return
        self._paint_off = True

    def _resume_painting(self) -> None:
        """Paint again, and repaint everything once — the window is out of date."""
        if not self._paint_off:
            return
        self._paint_off = False
        hwnd = self._window_handle()
        try:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETREDRAW, 1, 0)
            ctypes.windll.user32.RedrawWindow(hwnd, None, None, RDW_REPAINT_ALL)
        except Exception:            # noqa: BLE001
            pass

    # -- scenarios tab (run .md action scripts) -----------------------------

    # -- the Scenarios tab is a plugin (panel/tabs/scenarios.py) --------------
    #
    # The list, the editor with its debounced parse-then-save, the runner, the repeat
    # loop and the `TAP` reference all went with it. Only the runtime it leans on is
    # left here: `rt.actions`, the game claim and the log.

    # -- timers tab (scheduled repeats of an action) ------------------------

    # -- «Таймеры» is a plugin tab now (panel/tabs/timers.py) -----------------
    #
    # The two grids, the editor dialog and the master switch went with it. The
    # SCHEDULE did not: it is panel/runtime/schedule.py and runs whether or not this
    # profile shows the tab that edits its lists.

    def _rally_join_args(self) -> dict:
        """Which squads the rally auto-join spends — the «Авторалли» list, read live.

        Registered with the schedule rather than known to it: the rule belongs to the
        rally code, which answers in a profile that does not show that tab either.
        """
        squads = rallytab.join_squads(self._rt)
        if not squads:
            self._say("trigger", "triggers.log.no_squads")
        return {"squads": squads}

    def _on_main_tab_changed(self, _event=None) -> None:
        """Tell the tabs which of them is on screen.

        Three things, in the order the contract sets them out (§3): the tab being left
        hears `on_hide`, the one arriving hears `ensure_loaded` (its first-time read)
        and then `on_show`.

        The two are NOT the same and the difference costs a game round trip.
        `ensure_loaded` is "bring up what this tab is FOR" — a capture that has to be
        listening whether or not anybody looks, which is why an EAGER tab gets it at
        boot. `on_show` is "somebody is actually looking", which is where a read that
        only feeds the screen belongs. Folding the second into the first meant every
        profile paid a VM read at start-up for a list nobody had opened.
        """
        nb = getattr(self, "_main_nb", None)
        if nb is None:
            return
        try:
            current = str(nb.select())
        except tk.TclError:
            return
        tabs = getattr(self, "_lazy_tabs", {})
        previous = getattr(self, "_shown_tab", None)
        if previous is not None and previous is not tabs.get(current):
            previous.on_hide()
        tab = tabs.get(current)
        self._shown_tab = tab
        if tab is not None:
            tab.ensure_loaded()
            tab.on_show()

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        """The Settings page: an aggregator, not a page.

        The shell's own sub-tabs come from SETTINGS_TABS (a builder of None shows the
        placeholder), and then every plugin tab that declares a `SETTINGS_PAGE_KEY`
        contributes one of its own — so «Авторалли» is drawn by the rally tab, travels
        with it, and is simply not there when rally is switched off
        (docs/research/panel-tabs-refactor.md §6).
        """
        sub_nb = ttk.Notebook(parent)
        sub_nb.pack(fill="both", expand=True, padx=4, pady=4)

        pages = [(f"settings.tab.{key}", getattr(self, builder) if builder else None)
                 for key, builder in SETTINGS_TABS]
        for tab in getattr(self, "_plugin_tabs", {}).values():
            if tab.SETTINGS_PAGE_KEY:
                pages.append((tab.SETTINGS_PAGE_KEY, tab.settings_page))

        for title_key, fill in pages:
            frame = ttk.Frame(sub_nb, padding=8)
            sub_nb.add(frame, text=self._t(title_key))
            self._hook(
                lambda nb=sub_nb, f=frame, k=title_key: nb.tab(f, text=self._t(k)),
                key=f"settings-tab-{title_key}",
            )
            if fill is None:
                self._tr(ttk.Label(frame, foreground="#888"),
                         "settings.placeholder").pack(anchor="w")
                continue
            try:
                fill(frame)
            except Exception as exc:            # noqa: BLE001 — a page, not the panel
                self._dbg.error("settings page %r failed", title_key, exc_info=True)
                self._say("panel", "log.tab.failed", tab=title_key, error=exc)

    # -- settings: the knobs that used to be constants in this file -----------
    #
    # Both tabs said "Скоро" while WIN_PYTHON, the auto-loot budget, the trace
    # filter, the game paths and the sweep box were all edit-the-source. Every row
    # below is one entry in SETTINGS_DEFAULTS bound to its `_opt_vars` variable, so
    # a new knob is a line there plus a row here plus two locale strings.
    def _opt_row(self, parent: ttk.Frame, row: int, key: str, *,
                 width: int = 12, spin: "tuple | None" = None) -> None:
        """One labelled field on a Settings tab, bound to ``_opt_vars[key]``."""
        self._tr(ttk.Label(parent), f"opt.{key}").grid(row=row, column=0, sticky="w",
                                                       padx=(0, 8), pady=3)
        var = self._opt_vars[key]
        if isinstance(var, tk.BooleanVar):
            ttk.Checkbutton(parent, variable=var).grid(row=row, column=1, sticky="w")
        elif spin is not None:
            # A float knob (poll seconds, dwell, timeout) needs the decimal point;
            # an integer one stays digit-only.
            decimal = isinstance(SETTINGS_DEFAULTS.get(key), float)
            numeric_spinbox(parent, from_=spin[0], to=spin[1], width=width,
                        decimal=decimal, textvariable=var).grid(
                            row=row, column=1, sticky="w")
        else:
            ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1,
                                                                  sticky="we")
        self._tr(ttk.Label(parent, foreground="#888", wraplength=340, justify="left"),
                 f"opt.{key}.hint").grid(row=row, column=2, sticky="w", padx=(10, 0))

    def _build_general_settings(self, parent: ttk.Frame) -> None:
        """«Общие»: the Python that runs the children, the daemon, the log, auto-loot."""
        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=0)
        grid.columnconfigure(2, weight=1)
        for row, (key, kwargs) in enumerate((
                ("win_python", {"width": 34}),
                ("daemon_port", {"spin": (1, 65535), "width": 10}),
                ("log_max_lines", {"spin": (200, 200000), "width": 10}),
                ("autoloot_limit", {"spin": (1, 50), "width": 10}),
                ("autoloot_poll", {"spin": (1, 600), "width": 10}),
                ("autoloot_pause_min", {"spin": (1, 1440), "width": 10}),
                ("trace_filter", {"width": 20}),
                ("sniff_ready_timeout", {"spin": (1, 600), "width": 10}),
        )):
            self._opt_row(grid, row, key, **kwargs)
        self._build_debug_log_settings(parent)

    def _build_debug_log_settings(self, parent: ttk.Frame) -> None:
        """The technical debug log: the send target and «Отправить диагностику».

        The debug file is separate from panel.log and the UI widget — a developer
        diagnostic (panel/debug_log.py) that keeps every component's key events, every
        traceback and a systems snapshot, rotated at a fixed 5 MiB × 3. The only knob
        is where the zipped logs go; «Отправить диагностику» packs and hands them to
        `debug_send_url` (empty = do not send; a stub until a transport is wired).
        """
        frame = self._tr(ttk.LabelFrame(parent, padding=8), "debug.frame")
        frame.pack(fill="x", pady=(12, 0))
        frame.columnconfigure(2, weight=1)
        self._opt_row(frame, 0, "debug_send_url", width=34)
        self._tr(ttk.Button(frame, command=self._send_debug_archive),
                 "debug.send").grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))

    def _build_game_settings(self, parent: ttk.Frame) -> None:
        """«Игра»: where the client is, whether to put it back, and the sweep box."""
        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        grid.columnconfigure(2, weight=1)
        for row, (key, kwargs) in enumerate((
                ("launcher", {"width": 34}),
                ("game_exe", {"width": 20}),
                ("watchdog", {}),
        )):
            self._opt_row(grid, row, key, **kwargs)

        sweep = self._tr(ttk.LabelFrame(parent, padding=8), "sweep.frame")
        sweep.pack(fill="x", pady=(12, 0))
        sweep.columnconfigure(2, weight=1)
        for row, (key, kwargs) in enumerate((
                ("sweep_radius", {"spin": (mapsweepmod.MIN_RADIUS,
                                           mapsweepmod.MAX_RADIUS), "width": 10}),
                ("sweep_step", {"spin": (mapsweepmod.MIN_STEP,
                                         mapsweepmod.MAX_STEP), "width": 10}),
                ("sweep_dwell", {"spin": (mapsweepmod.MIN_DWELL,
                                          mapsweepmod.MAX_DWELL), "width": 10}),
                ("sweep_rest_min", {"spin": (0, 1440), "width": 10}),
        )):
            self._opt_row(sweep, row, key, **kwargs)
        # The box in words, so the numbers above are not abstract.
        hint = ttk.Label(sweep, foreground="#888", wraplength=520, justify="left")
        hint.grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self._sweep_settings_hint = hint
        for key in ("sweep_radius", "sweep_step", "sweep_dwell"):
            self._opt_vars[key].trace_add(
                "write", lambda *a: self._refresh_sweep_settings_hint())
        self._refresh_sweep_settings_hint()

    def _refresh_sweep_settings_hint(self) -> None:
        hint = getattr(self, "_sweep_settings_hint", None)
        if hint is None:
            return
        radius, step, dwell, _rest = self._sweep_box()
        # A centre of (0, 0) would be clamped against the map edge and undercount, so
        # describe the box from a point well inside the map instead.
        jumps, seconds = mapsweepmod.describe(500, 500, radius, step, dwell)
        try:
            hint.configure(text=self._t("sweep.settings_hint", side=radius * 2 + 1,
                                        jumps=jumps, mins=max(1, int(seconds // 60))))
        except tk.TclError:
            pass

    # -- «Авторалли» is the rally tab's own settings page now ----------------
    #
    # The join list, the alliance drill with its single banner-carrier, the
    # create-a-rally squad and level, and the daily caps per monster type all went
    # to panel/tabs/rally/autorally.py — contributed to this page by the tab that
    # uses them (§6), so switching rally off takes its settings with it.

    # `_command_post_config` / `_tab_config` are gone: a tab that is not in this
    # window keeps the block on disk, and `_tabs_block` does that for every plugin tab
    # at once rather than one hand-written method per tab.

    # -- chat tab -----------------------------------------------------------

    def _build_chat_tab(self, parent: ttk.Frame) -> None:
        """Build the Chat tab: monitor toggle, sub-tabs per chat type, and a box to answer in."""
        ctrl = ttk.Frame(parent, padding=(8, 6, 8, 4))
        ctrl.pack(fill="x")
        self._tr(ttk.Checkbutton(ctrl, variable=self._chat_var, command=self._toggle_chat),
                 "chat.monitor").pack(side="left")
        self._tr(ttk.Label(ctrl, foreground="#888", wraplength=500, justify="left"),
                 "chat.hint").pack(side="left", padx=(10, 0))

        sub_nb = ttk.Notebook(parent)
        sub_nb.pack(fill="both", expand=True, padx=4, pady=(0, 2))
        self._chat_nb = sub_nb
        self._chat_frames: dict = {}

        for type_key in CHAT_TABS:
            frame = ttk.Frame(sub_nb)
            sub_nb.add(frame, text=self._t(f"chat.tab.{type_key}"))
            self._chat_frames[type_key] = frame
            # The DM tab is a contact list beside the conversation; every other tab
            # is just the message view.
            tree = (self._build_dm_tab(frame) if type_key == "dm"
                    else self._make_chat_tree(frame))
            self._chat_trees[type_key] = tree
            self._chat_tree_rows[type_key] = 0
        # One hook for all of them: the labels carry an unread count, so they are
        # rewritten together and by the same code that draws the marks.
        self._hook(self._paint_chat_tabs)
        # A DM that arrived while another tab was open used to be silent. Selecting a
        # tab is what marks it read.
        sub_nb.bind("<<NotebookTabChanged>>", self._on_chat_tab_changed)

        # -- the box to answer in ------------------------------------------------
        #
        # chat_send.py, tools/lib/chat_share.py and actions/send_chat_message.md all
        # existed and the tab had no input at all, so answering a mate or sharing a
        # coordinate meant leaving the panel. The target is the room of the last
        # message in the tab that is open — and it is SHOWN, so it is never a guess:
        # a message sent to the wrong room cannot be unsent.
        send = ttk.Frame(parent, padding=(6, 2, 6, 2))
        send.pack(fill="x")
        self._chat_room_var = tk.StringVar(value="—")
        self._tr(ttk.Label(send), "chat.to").pack(side="left")
        ttk.Label(send, textvariable=self._chat_room_var, foreground="#888",
                  width=26).pack(side="left", padx=(4, 6))
        # The emoji / sticker picker: a game emoji goes inline into the text as a
        # {e:<id>} token (chat_send resolves it), a sticker is sent as its own
        # message (the game does not let a sticker ride alongside text).
        ttk.Button(send, text="😊", width=32, command=self._open_emoji_picker).pack(
            side="left", padx=(0, 4))
        self._chat_msg_var = tk.StringVar()
        entry = ttk.Entry(send, textvariable=self._chat_msg_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self._chat_send_text())
        self._chat_entry = entry
        self._tr(ttk.Button(send, command=self._chat_send_text),
                 "chat.send").pack(side="left", padx=(4, 0))
        # The coordinate written in the box beside it, shared as a map pin — not as
        # text. A pin is tappable in the game; "567,471" is not.
        self._tr(ttk.Button(send, command=self._chat_send_coords),
                 "chat.send_coords").pack(side="left", padx=(4, 0))

        bot = ttk.Frame(parent, padding=(6, 2, 6, 4))
        bot.pack(fill="x")
        self._tr(ttk.Button(bot, command=self._clear_chat),
                 "chat.clear").pack(side="left")
        self._chat_count_var = tk.StringVar(value=self._t("chat.count", n=0))
        ttk.Label(bot, textvariable=self._chat_count_var, foreground="#888").pack(
            side="right", padx=8)
        self._hook(self._retranslate_chat_bottom)

        self._pump_chat()

    def _retranslate_chat_bottom(self) -> None:
        """Re-apply translatable text in the chat bottom bar after a language change."""
        total = sum(len(v) for v in self._chat_msgs.values())
        self._chat_count_var.set(self._t("chat.count", n=total))

    # -- which tab is open, and what has arrived in the others ---------------
    def _active_chat_type(self) -> str:
        nb = getattr(self, "_chat_nb", None)
        if nb is None:
            return CHAT_TABS[0]
        try:
            current = nb.select()
        except tk.TclError:
            return CHAT_TABS[0]
        for key, frame in self._chat_frames.items():
            if str(frame) == str(current):
                return key
        return CHAT_TABS[0]

    def _on_chat_tab_changed(self, _event=None) -> None:
        """A tab was selected: it is read now, and it is the send target."""
        active = self._active_chat_type()
        self._chat_unread[active] = 0
        if active == "dm":
            self._refresh_dm_contacts()     # show the freshest ordering on open
        self._paint_chat_tabs()
        self._update_chat_target()

    def _paint_chat_tabs(self) -> None:
        """Tab labels, each carrying its unread count."""
        nb = getattr(self, "_chat_nb", None)
        if nb is None:
            return
        for key, frame in self._chat_frames.items():
            unread = self._chat_unread.get(key, 0)
            label = self._t(f"chat.tab.{key}")
            if unread:
                label = f"{label} ({unread})"
            try:
                nb.tab(frame, text=label)
            except tk.TclError:
                pass

    def _chat_room(self, chat_type: str) -> str:
        """The room to answer in.

        For a DM that is the open conversation's room (a reply must go to the peer
        whose thread is on screen, not to whoever spoke last across all DMs). For any
        other tab it is the room of that tab's last message.
        """
        if chat_type == "dm":
            return self._dm_active_room
        for record in reversed(self._chat_msgs.get(chat_type, [])):
            room = str(record.get("room_id") or "").strip()
            if room:
                return room
        return ""

    def _update_chat_target(self) -> None:
        room = self._chat_room(self._active_chat_type())
        try:
            self._chat_room_var.set(room or "—")
        except tk.TclError:
            pass

    # -- sending -------------------------------------------------------------
    def _chat_send(self, args: list, what: str) -> None:
        """Run tools/chat_send.py with ``args``, streaming its output into the log.

        A child, like the monitors: the send walks the Lua VM several times and must
        not sit on the Tk thread. It does not claim the busy flag — a chat message is
        not a game action competing for the camera, and making a reply wait behind a
        collect run would be its own kind of wrong.
        """
        room = self._chat_room(self._active_chat_type())
        if not room:
            self._say("chat", "chat.no_room")
            return
        cmd = [self._python(), "-u", os.path.join(TOOLS, "chat_send.py"),
               "--room", room] + args
        self._say("chat", "chat.sending", room=room, what=what)
        proc = self._spawn_sniffer(cmd, "chat")
        if proc is None:
            return
        threading.Thread(target=self._chat_send_reader, args=(proc,),
                         daemon=True).start()

    def _chat_send_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if line:
                    self._log_put(f"[chat] {line}")
        except Exception:
            pass

    def _chat_send_text(self) -> None:
        text = self._chat_msg_var.get().strip()
        if not text:
            return
        self._chat_msg_var.set("")
        self._chat_send(["--text", text], text[:40])

    def _chat_send_coords(self) -> None:
        """Share the coordinate written in the message box as a map pin.

        It used to be read from the Main tab's X/Y/server fields; that block is gone
        (#1183), so the box the message is typed into is the source — through the same
        tolerant parser the log's clickable links use, so anything a coordinate is
        written as elsewhere in the panel (`#2305 X:568 Y:371`, `@[568,371]`,
        `(568,371)`) can simply be pasted in and shared.
        """
        found = coords.parse(self._chat_msg_var.get())
        if not found:
            self._say("chat", "chat.no_coords")
            return
        _s, _e, x, y, srv = found[0]
        args = ["--coords", f"{x},{y}"]
        if srv is not None:
            args += ["--coord-server", str(srv)]
        # The box held the coordinate, not a message — clear it like a send does, or
        # the next «Отправить» would post the pin's text alongside the pin.
        self._chat_msg_var.set("")
        self._chat_send(args, coords.fmt(x, y, srv))

    # -- emoji / sticker picker ---------------------------------------------
    def _open_emoji_picker(self) -> None:
        """A popup of the game's emoji (insert inline) and stickers (send one).

        Both grids are drawn from the sprites `tools/chat_assets.py` already extracts
        — no game call needed to open the picker. An emoji click drops a `{e:<id>}`
        token into the message box; a sticker click sends that sticker as its own
        message (the game does not allow a sticker beside text).
        """
        old = getattr(self, "_emoji_win", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        emojis = chat_assets.emoji_catalogue()
        stickers = chat_assets.sticker_catalogue()

        top = tk.Toplevel(self)
        self._emoji_win = top
        top.title(self._t("chat.picker.title"))
        top.transient(self)
        ttk.Label(top, text=self._t("chat.picker.emoji"), anchor="w",
                 foreground="#8a8a8a").pack(fill="x", padx=8, pady=(8, 0))
        em_box = ScrolledText(top, wrap="char", state="disabled", cursor="arrow",
                            borderwidth=0, highlightthickness=0, padx=4, pady=4)
        em_box.pack(fill="both", expand=True, padx=8, pady=(2, 4))
        self._fill_picker(em_box, emojis, "emoji", 24)
        ttk.Label(top, text=self._t("chat.picker.sticker"), anchor="w",
                 foreground="#8a8a8a").pack(fill="x", padx=8, pady=(4, 0))
        st_box = ScrolledText(top, wrap="char", state="disabled", cursor="arrow",
                            height=4, borderwidth=0, highlightthickness=0, padx=4, pady=4)
        st_box.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self._fill_picker(st_box, stickers, "sticker", 44)

        top.geometry("380x460")
        top.bind("<Escape>", lambda _e: top.destroy())
        try:
            top.update_idletasks()
            x = self.winfo_rootx() + 60
            y = self.winfo_rooty() + 80
            top.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def _fill_picker(self, box: "tk.Text", items: list, kind: str, px: int) -> None:
        """Draw one grid of clickable sprites into ``box`` (fresh widget, no stale tags)."""
        box.configure(state="normal")
        box.delete("1.0", "end")
        drawn = 0
        for idx, item in enumerate(items):
            img = self._chat_image(item["path"], px)
            if img is None:
                continue
            tag = f"{kind}{idx}"
            pos = box.index("end -1c")
            box.image_create("end", image=img)
            box.insert("end", " ")
            box.tag_add(tag, pos, f"{pos} +1c")
            if kind == "emoji":
                box.tag_bind(tag, "<Button-1>", lambda _e, it=item: self._pick_emoji(it))
            else:
                box.tag_bind(tag, "<Button-1>", lambda _e, it=item: self._pick_sticker(it))
            box.tag_bind(tag, "<Enter>", lambda _e, b=box: b.configure(cursor="hand2"))
            box.tag_bind(tag, "<Leave>", lambda _e, b=box: b.configure(cursor="arrow"))
            drawn += 1
        if drawn == 0:
            box.insert("end", self._t("chat.picker.empty"), ("token",))
        box.configure(state="disabled")

    def _pick_emoji(self, item: dict) -> None:
        """Insert an emoji token at the cursor; the picker stays open for more."""
        token = "{e:%s}" % item.get("id", "")
        entry = getattr(self, "_chat_entry", None)
        try:
            entry.insert("insert", token)          # at the caret
            entry.focus_set()
        except (tk.TclError, AttributeError):
            self._chat_msg_var.set(self._chat_msg_var.get() + token)

    def _pick_sticker(self, item: dict) -> None:
        """Send one sticker as its own message, then close the picker."""
        sid = str(item.get("id", ""))
        if sid:
            self._chat_send(["--sticker", sid], f"sticker {sid}")
        win = getattr(self, "_emoji_win", None)
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    def _build_dm_tab(self, parent: ttk.Frame) -> "tk.Text":
        """The DM tab: a contact list on the left, one conversation on the right.

        Returns the conversation Text view (which becomes ``_chat_trees['dm']`` so the
        generic lazy-load machinery drives it), while the contact list is its own
        read-only textbox drawn from the store. A contact = one DM peer; clicking it
        opens that peer's conversation and nothing else.
        """
        left = ttk.Frame(parent, width=210)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)          # keep the fixed sidebar width
        self._tr(ttk.Label(left, foreground="#8a8a8a"),
                 "chat.contacts").pack(anchor="w", padx=6, pady=(4, 2))
        lst = ScrolledText(left, wrap="none", state="disabled", cursor="arrow",
                         font=("Segoe UI", 9), borderwidth=0, highlightthickness=0,
                         padx=4, pady=2)
        lst.tag_configure("dmname", foreground="#d8d8d8")
        lst.tag_configure("dmlast", foreground="#8a8a8a")
        lst.tag_configure("time", foreground="#6f6f6f")
        lst.tag_configure("dmunread", foreground="#66bb6a")
        lst.tag_configure("dmactive", background="#2a3a52")
        lst.pack(fill="both", expand=True, padx=(2, 0), pady=(0, 4))
        self._dm_list = lst

        right = ttk.Frame(parent)
        right.pack(side="left", fill="both", expand=True)
        self._dm_header_var = tk.StringVar(value=self._t("chat.dm.pick"))
        ttk.Label(right, textvariable=self._dm_header_var, anchor="w",
                 foreground="#c8c8c8").pack(fill="x", padx=6, pady=(4, 0))
        return self._make_chat_tree(right)

    def _refresh_dm_contacts(self) -> None:
        """Repaint the contact sidebar from the store, newest conversation on top."""
        lst = self._dm_list
        if lst is None:
            return
        # Drop the previous rows' per-contact tags (and their click bindings): the
        # idx->contact mapping changes on every repaint, so a stale binding would
        # open the wrong peer. Style tags (dmname/…) are kept.
        for tag in lst.tag_names():
            if tag[:2] == "dm" and tag[2:].isdigit():
                lst.tag_delete(tag)
        lst.configure(state="normal")
        lst.delete("1.0", "end")
        contacts: list = []
        if self._chat_store is not None:
            try:
                contacts = self._chat_store.dm_contacts(self._chat_uid)
            except Exception:       # noqa: BLE001
                contacts = []
        if not contacts:
            lst.insert("end", self._t("chat.contacts.empty"), ("dmlast",))
            lst.configure(state="disabled")
            return
        for idx, contact in enumerate(contacts):
            self._render_contact_row(lst, idx, contact)
        lst.configure(state="disabled")

    def _render_contact_row(self, lst: "tk.Text", idx: int, contact: dict) -> None:
        """One contact: avatar + name + time on the first line, last message below."""
        tag = f"dm{idx}"
        start = lst.index("end -1c")
        img = self._chat_avatar({"sender_uid": contact.get("peer_uid", ""),
                                 "head_pic_ver": contact.get("head_pic_ver", "")})
        if img is not None:
            lst.image_create("end", image=img)
        lst.insert("end", " ")
        lst.insert("end", (contact.get("name") or "")[:16], ("dmname",))
        t_str = self._dm_contact_time(contact.get("last_ts", 0))
        if t_str:
            lst.insert("end", "  " + t_str, ("time",))
        unread = self._dm_unread.get(contact.get("room"), 0)
        if unread:
            lst.insert("end", f"  ●{unread}", ("dmunread",))
        lst.insert("end", "\n")
        prefix = (self._t("chat.you") + " ") if contact.get("last_mine") else ""
        preview = (prefix + (contact.get("last_text") or "")).replace("\n", " ")[:26]
        lst.insert("end", "    " + preview + "\n", ("dmlast",))
        end = lst.index("end -1c")
        lst.tag_add(tag, start, end)
        if contact.get("room") and contact.get("room") == self._dm_active_room:
            lst.tag_add("dmactive", start, end)
        lst.tag_bind(tag, "<Button-1>", lambda _e, c=contact: self._open_dm(c))
        lst.tag_bind(tag, "<Enter>", lambda _e: lst.configure(cursor="hand2"))
        lst.tag_bind(tag, "<Leave>", lambda _e: lst.configure(cursor="arrow"))

    @staticmethod
    def _dm_contact_time(ts) -> str:
        """A compact last-message stamp: HH:MM today, DD.MM on an earlier day."""
        from datetime import datetime as _dt
        if not ts:
            return ""
        try:
            when = _dt.fromtimestamp(ts)
        except (OSError, ValueError, OverflowError):
            return ""
        now = _dt.now()
        return when.strftime("%H:%M") if when.date() == now.date() else when.strftime("%d.%m")

    def _open_dm(self, contact: dict) -> None:
        """Show one DM peer's conversation in the DM tab, filtered to their room."""
        room = contact.get("room") or ""
        if not room:
            return
        self._dm_active_room = room
        self._dm_active_peer = contact.get("peer_uid") or ""
        self._dm_unread[room] = 0
        try:
            self._dm_header_var.set(contact.get("name") or room)
        except (tk.TclError, AttributeError):
            pass
        msgs: list = []
        self._chat_has_more["dm"] = False
        if self._chat_store is not None:
            msgs = self._chat_store.recent_room(room, CHAT_PAGE)
            if msgs:
                self._chat_has_more["dm"] = self._chat_store.has_older_room(
                    room, msgs[0].get("ts", 0))
        self._chat_msgs["dm"] = msgs
        self._chat_tree_rows["dm"] = 0
        self._rebuild_chat_view("dm")
        self._refresh_dm_contacts()      # re-highlight the open contact, clear its dot
        self._update_chat_target()

    def _make_chat_tree(self, parent: ttk.Frame) -> "tk.Text":
        """Build a read-only Text view for one chat type, with a scrollbar.

        A Text widget (not a Treeview) is used so emoji / sticker sprites can be
        drawn inline with the message text via ``image_create``.
        """
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        txt = ScrolledText(frame, wrap="word", state="disabled", cursor="arrow",
                      font=("Segoe UI", 10), spacing1=1, spacing3=3,
                      borderwidth=0, highlightthickness=0, padx=6, pady=4)
        txt.tag_configure("time", foreground="#8a8a8a")
        txt.tag_configure("alliance", foreground="#5c9dff")
        txt.tag_configure("nick", foreground="#c8c8c8")
        txt.tag_configure("mine", foreground="#66bb6a")
        txt.tag_configure("token", foreground="#a586e0")
        # Same look the log gives a coordinate, so a clickable one reads as clickable
        # here too (bright blue, on the dark textbox).
        txt.tag_configure("coordlink", foreground="#5cf", underline=True)
        # Both link kinds are bound ONCE per view, for the same reason the header
        # below is: a handler laid down per rendered item stacks up for as long as
        # the panel is open (see `_bind_coord_links`).
        self._bind_coord_links(txt)
        self._bind_photo_links(txt)
        # The "↑ older messages" affordance drawn atop a partially-loaded tab.
        txt.tag_configure("loadmore", foreground="#5c9dff", underline=True,
                          justify="center")
        # Clicking the header pages in older history. Bound once here (not per
        # rebuild) so the handler cannot stack up; the tab is resolved at click time.
        txt.tag_bind("loadmore", "<Button-1>",
                     lambda _e, v=txt: self._chat_click_load_more(v))
        txt.tag_bind("loadmore", "<Enter>", lambda _e, v=txt: v.configure(cursor="hand2"))
        txt.tag_bind("loadmore", "<Leave>", lambda _e, v=txt: v.configure(cursor="arrow"))
        # ScrolledText carries its own scrollbars, so no ttk.Scrollbar is wired here.
        txt.pack(fill="both", expand=True)
        # Paging in older history: a scroll to the very top loads the previous
        # CHAT_PAGE. Bind on the inner tk.Text (ScrolledText proxies to `_textbox`);
        # add="+" so the widget's own scrolling is untouched. Wheel/keys all route
        # through one deferred check of the top fraction.
        inner = getattr(txt, "_textbox", txt)
        for seq in ("<MouseWheel>", "<Button-4>", "<Prior>", "<Up>", "<Home>"):
            inner.bind(seq, lambda _e, v=txt: v.after(40, lambda: self._on_chat_scroll(v)),
                       add="+")
        return txt

    def _chat_image(self, path: str, height: int):
        """Load (and cache) an inline sprite scaled to ``height`` px, or None.

        The cache is an LRU bounded at CHAT_IMG_CACHE_MAX. It used to be unbounded,
        and it holds a live Tk image per distinct (file, size) — one per sender's
        avatar and one per photo — so a night in world chat quietly turned into
        thousands of them. What falls out is what has not been drawn for longest,
        i.e. history far above the viewport; the newest page always keeps its
        pictures.
        """
        key = (path, height)
        img = self._chat_img_cache.get(key)
        if img is not None:
            self._chat_img_cache[key] = self._chat_img_cache.pop(key)   # touch (LRU)
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
        self._trim_chat_images()
        return img

    def _trim_chat_images(self) -> None:
        """Drop the least recently drawn images once the cache is over its cap.

        The placeholder avatar is never evicted — it is the fallback every sender
        without a cached picture shares, so dropping it only means drawing it again.
        """
        cache = self._chat_img_cache
        while len(cache) > CHAT_IMG_CACHE_MAX:
            key = next(iter(cache))
            if key[0] == "__avatar_placeholder__":
                cache[key] = cache.pop(key)      # keep it: move to the young end
                continue
            self._photo_meta.pop(str(cache.pop(key)), None)

    _AVATAR_PX = 20

    def _chat_avatar(self, record: dict):
        """The avatar image for a message: the sender's cached JPG, else a placeholder.

        Returns a Tk image (never None when PIL is available); only if the image
        machinery is missing entirely does it return None, and the caller draws a
        text glyph instead.
        """
        uid = record.get("sender_uid") or ""
        ver = record.get("head_pic_ver") or ""
        path = chat_assets.avatar_path(uid, ver) if uid and ver else None
        if path:
            img = self._chat_image(path, self._AVATAR_PX)
            if img is not None:
                return img
        return self._chat_avatar_placeholder()

    def _chat_avatar_placeholder(self):
        """A cached neutral head-and-shoulders silhouette, sized like a real avatar."""
        key = ("__avatar_placeholder__", self._AVATAR_PX)
        img = self._chat_img_cache.get(key)
        if img is not None:
            return img
        px = self._AVATAR_PX
        try:
            if not _PIL_OK:
                return None
            im = _PILImage.new("RGBA", (px, px), (0, 0, 0, 0))
            d = _PILImageDraw.Draw(im)
            d.ellipse((0, 0, px - 1, px - 1), fill=(74, 78, 86, 255))        # disc
            head = (px * 0.32, px * 0.16, px * 0.68, px * 0.52)
            body = (px * 0.18, px * 0.56, px * 0.82, px * 1.04)
            d.ellipse(head, fill=(176, 180, 188, 255))
            d.ellipse(body, fill=(176, 180, 188, 255))
            img = _PILImageTk.PhotoImage(im)
        except Exception:       # noqa: BLE001
            return None
        self._chat_img_cache[key] = img
        return img

    @staticmethod
    def _chat_clear_view(view: "tk.Text") -> None:
        view.configure(state="normal")
        view.delete("1.0", "end")
        view.configure(state="disabled")

    def _insert_chat_text(self, view: "tk.Text", text: str) -> None:
        """Write chat text, turning coordinates into the same links the log makes.

        Chat is where coordinates actually ARRIVE — a rally target, a treasure, a base
        to hit — and it was the one place that inserted them as dead text while the
        log made them clickable.
        """
        pos = 0
        for (s, e, _x, _y, _srv) in coords.parse(text):
            if s > pos:
                view.insert("end", text[pos:s])
            self._insert_coord_link(view, text[s:e])
            pos = e
        if pos < len(text):
            view.insert("end", text[pos:])

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
        # Sender avatar, drawn inline before the nick. It resolves to the JPG the
        # client already cached under ChatPhotos (keyed by uid+headPicVer); a
        # built-in head with no cached file falls back to a neutral placeholder.
        av_img = self._chat_avatar(record)
        if av_img is not None:
            view.image_create("end", image=av_img)
            view.insert("end", " ")
        else:
            view.insert("end", "👤 ", ("token",))    # PIL/Tk image unavailable
        if alliance:
            view.insert("end", f"[{alliance}] ", ("alliance",))
        view.insert("end", nick + ": ", (nick_tag,))
        uid = record.get("sender_uid") or ""
        for kind, val in chat_assets.segments((record.get("msg") or "")[:300]):
            if kind == "text":
                self._insert_chat_text(view, val)
            elif kind == "token":
                # A photo token resolves to a JPG the client already cached on disk
                # (keyed by uid+picVer) -> render it; else a friendly placeholder.
                m = _PHOTO_TOK.match(val)
                path = chat_assets.photo_path(uid, m.group(1)) if m else None
                if path:
                    img = self._chat_image(path, 110)
                    if img is not None:
                        # Tag the image so a click opens it full-size (like the game).
                        # ONE shared tag, bound once per view (`_bind_photo_links`):
                        # a tag per photo left three callbacks behind on every chat
                        # rebuild, and the DM tab rebuilds its whole window whenever
                        # a message arrives. What was clicked is resolved from the
                        # image itself, which is cached and therefore bounded.
                        self._photo_seq += 1
                        pos = view.index("end -1c")
                        view.image_create(pos, image=img)
                        view.tag_add("photolink", pos, f"{pos} +1c")
                        self._photo_meta[str(img)] = (uid, m.group(1), path)
                        continue
                view.insert("end", self._t("chat.photo") if m else val, ("token",))
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
            self._say("chat", "log.chat.photo_failed", error=exc)
            return
        top = tk.Toplevel(self)
        top.title(self._t("tab.chat"))
        top.configure(bg="#000000")
        lbl = tk.Label(top, image=photo, bg="#000000", cursor="hand2")
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
        rebuild: set = set()          # types whose whole window must be redrawn
        try:
            while True:
                record = self._chat_q.get_nowait()
                chat_type = record.get("chat_type", "other")
                if chat_type not in self._chat_msgs:
                    chat_type = "other"
                # Persist first: the SQLite store is the history of record, so a
                # message is durable the moment it arrives (idempotent on identity).
                if self._chat_store is not None:
                    self._chat_store.append(record)
                # A DM does NOT go into one shared stream: it belongs to a contact.
                # The sidebar always updates; the conversation view only grows when
                # the message is for the peer currently open.
                if chat_type == "dm":
                    self._dm_contacts_dirty = True
                    room = str(record.get("room_id") or "")
                    if room and room == self._dm_active_room:
                        if self._dm_append(record):
                            rebuild.add("dm")
                        changed.add("dm")
                    elif not record.get("is_mine"):
                        self._dm_unread[room] = self._dm_unread.get(room, 0) + 1
                    if not record.get("is_mine") and "dm" != self._active_chat_type():
                        self._chat_unread["dm"] = self._chat_unread.get("dm", 0) + 1
                    continue
                msgs = self._chat_msgs[chat_type]
                # Order by the message's own serverTime (record["ts"]). The live
                # stream is already monotonic; only history re-parsed on scroll-up
                # arrives "from the past" -- resort and rebuild that tree then, so
                # old messages land in their proper place, not at the bottom. A plain
                # append just grows the bottom — no rebuild, only the new tail draws.
                out_of_order = bool(msgs) and record.get("ts", 0) < msgs[-1].get("ts", 0)
                msgs.append(record)
                if out_of_order:
                    msgs.sort(key=lambda r: r.get("ts", 0))
                    rebuild.add(chat_type)
                if len(msgs) > CHAT_MSGS_MAX:
                    # Bound the rendered list: drop the oldest overflow from memory.
                    # It is still in the store, so mark the tab as having more to page
                    # back in, and redraw so the load-more header appears.
                    del msgs[:len(msgs) - CHAT_MSGS_MAX]
                    self._chat_has_more[chat_type] = True
                    rebuild.add(chat_type)
                changed.add(chat_type)
                # Unread only counts somebody else's message in a tab nobody is
                # looking at: my own echo back is not news, and neither is a message
                # in the tab that is open.
                if not record.get("is_mine") and chat_type != self._active_chat_type():
                    self._chat_unread[chat_type] = self._chat_unread.get(chat_type, 0) + 1
        except queue.Empty:
            pass

        if self._dm_contacts_dirty:
            self._dm_contacts_dirty = False
            self._refresh_dm_contacts()

        for chat_type in changed:
            if chat_type in rebuild:
                self._rebuild_chat_view(chat_type)
            else:
                self._update_chat_tree(chat_type)
        if changed:
            # A DM that arrives while another tab is open used to be silent.
            self._paint_chat_tabs()
            if self._active_chat_type() in changed:
                self._update_chat_target()

        # The count reflects the whole stored history, not just the loaded window.
        # `total()` is the running tally, not a fresh COUNT(*): this line runs once
        # a second for as long as the panel is open.
        total = (self._chat_store.total() if self._chat_store is not None
                 else sum(len(v) for v in self._chat_msgs.values()))
        self._chat_count_var.set(self._t("chat.count", n=total))
        self._arm("chat", 1000, self._pump_chat)

    def _dm_append(self, record: dict) -> bool:
        """Append a live DM to the OPEN conversation. True if a full rebuild is needed.

        Same ordering/cap rules as the generic append, but scoped to the DM tab's
        single-conversation window.
        """
        msgs = self._chat_msgs["dm"]
        need_rebuild = False
        if msgs and record.get("ts", 0) < msgs[-1].get("ts", 0):
            msgs.append(record)
            msgs.sort(key=lambda r: r.get("ts", 0))
            need_rebuild = True
        else:
            msgs.append(record)
        if len(msgs) > CHAT_MSGS_MAX:
            del msgs[:len(msgs) - CHAT_MSGS_MAX]
            self._chat_has_more["dm"] = True
            need_rebuild = True
        return need_rebuild

    def _update_chat_tree(self, chat_type: str) -> None:
        """Append records not yet rendered into the view, and autoscroll if at the bottom.

        Only the tail beyond ``_chat_tree_rows`` is drawn (an incremental append for
        the live stream). The view is kept pinned to the newest message ONLY when the
        reader is already there — a live message must not yank someone reading older
        history back down to the bottom.
        """
        view = self._chat_trees.get(chat_type)
        if view is None:
            return
        msgs = self._chat_msgs.get(chat_type, [])
        start = self._chat_tree_rows.get(chat_type, 0)
        if start >= len(msgs):
            return
        at_bottom = self._chat_view_at_bottom(view)
        for record in msgs[start:]:
            self._render_msg_line(view, record)
        self._chat_tree_rows[chat_type] = len(msgs)
        if at_bottom:
            view.see("end")

    @staticmethod
    def _chat_view_at_bottom(view: "tk.Text") -> bool:
        """True if the view is scrolled to (or very near) its bottom edge."""
        try:
            return float(view.yview()[1]) >= 0.999
        except (tk.TclError, ValueError, IndexError):
            return True

    def _chat_type_of_view(self, view) -> str | None:
        for key, v in self._chat_trees.items():
            if v is view:
                return key
        return None

    def _rebuild_chat_view(self, chat_type: str, keep_index: int | None = None) -> None:
        """Redraw a tab's whole in-memory window from scratch: the load-more header
        (when the store holds older messages than are in memory) followed by every
        loaded record.

        ``keep_index`` is the absolute index in ``_chat_msgs`` of the record to hold
        under the viewport after the redraw — used when paging in older messages so
        the reader stays on the line they were looking at instead of jumping.
        """
        view = self._chat_trees.get(chat_type)
        if view is None:
            return
        msgs = self._chat_msgs.get(chat_type, [])
        self._chat_clear_view(view)
        view.configure(state="normal")
        if self._chat_has_more.get(chat_type):
            view.insert("end", self._t("chat.load_more") + "\n", ("loadmore",))
        keep_mark = None
        for i, record in enumerate(msgs):
            if keep_index is not None and i == keep_index:
                keep_mark = view.index("end -1c")
            self._render_msg_line(view, record)
        view.configure(state="disabled")
        self._chat_tree_rows[chat_type] = len(msgs)
        if keep_mark is not None:
            view.see(keep_mark)
        else:
            view.see("end")

    def _chat_load_older(self, chat_type: str) -> None:
        """Page the previous CHAT_PAGE of history in from the store (top-anchored).

        The DM tab pages ONE conversation (its open room); every other tab pages its
        whole chat_type bucket.
        """
        if not self._chat_has_more.get(chat_type) or self._chat_store is None:
            return
        msgs = self._chat_msgs.get(chat_type, [])
        oldest_ts = msgs[0].get("ts", 0) if msgs else float("inf")
        if chat_type == "dm":
            room = self._dm_active_room
            if not room:
                return
            older = self._chat_store.older_room(room, oldest_ts, CHAT_PAGE)
            has_more = (lambda ts: self._chat_store.has_older_room(room, ts))
        else:
            older = self._chat_store.older(chat_type, oldest_ts, CHAT_PAGE)
            has_more = (lambda ts: self._chat_store.has_older(chat_type, ts))
        if not older:
            self._chat_has_more[chat_type] = False
            self._rebuild_chat_view(chat_type)
            return
        # Prepend the chunk; the record that WAS first is now at index len(older),
        # so hold it under the viewport — the new page appears above where the
        # reader already was.
        msgs[:0] = older
        self._chat_has_more[chat_type] = has_more(older[0].get("ts", 0))
        self._rebuild_chat_view(chat_type, keep_index=len(older))

    def _on_chat_scroll(self, view) -> None:
        """A scroll settled: if it reached the top and the store holds more, page it in."""
        try:
            top = float(view.yview()[0])
        except (tk.TclError, ValueError, IndexError):
            return
        if top > 0.001:
            return
        chat_type = self._chat_type_of_view(view)
        if chat_type and self._chat_has_more.get(chat_type):
            self._chat_load_older(chat_type)

    def _chat_click_load_more(self, view) -> None:
        """The '↑ show earlier messages' header was clicked."""
        chat_type = self._chat_type_of_view(view)
        if chat_type:
            self._chat_load_older(chat_type)

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
        rel = _repo_rel(out)
        self._say("chat", "log.chat.starting", path=rel)
        self._say("chat", "log.chat.needs_daemon")
        # stderr is dropped, not folded in: chat_reader's stdout is a JSONL stream and
        # a traceback interleaved into it would be parsed as a message.
        mon = self._child("chat",
                          [self._python(), "-u", os.path.join(TOOLS, "chat_reader.py"),
                           "--seconds", "0", "--out", out],
                          on_line=self._on_chat_line, on_exit=self._on_chat_exit,
                          capture_stderr=False)
        if not mon.start():
            self._chat_var.set(False)
            return
        self._chat_proc = mon
        # The monitor means the game is alive: read the current character's uid now
        # and (re)open its history file, so captured messages land in the right
        # character's store — not whatever was open (or nothing) before.
        self._reopen_chat_store()
        self._say("chat", "log.chat.started", pid=mon.pid)

    def _on_chat_line(self, line: str) -> bool:
        """One JSONL record from the reader into the queue the Tk pump drains."""
        line = line.strip()
        if line:
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    self._chat_q.put(record)
            except json.JSONDecodeError:
                pass
        return False                    # never logged: it is data, not prose

    def _on_chat_exit(self) -> None:
        self._say("chat", "log.chat.ended")
        self._chat_proc = None
        self._chat_var.set(False)

    # chat_log.jsonl is written by chat_reader.py itself (`--out`), so the panel
    # does NOT append here: two processes appending to one file interleaved
    # their buffers, duplicating every record and corrupting utf-8 mid-line.

    def _stop_chat(self) -> None:
        mon, self._chat_proc = self._chat_proc, None
        if mon is not None:
            self._say("chat", "log.chat.stopped")
            mon.stop()

    def _clear_chat(self) -> None:
        """Remove all in-memory chat messages and clear all views.

        Only the on-screen state is cleared; the SQLite store is untouched, so the
        history is still there after a restart or profile switch. The tabs are left
        able to page it back in (has_more), rather than looking permanently empty.
        """
        for chat_type in list(self._chat_msgs):
            self._chat_msgs[chat_type].clear()
            view = self._chat_trees.get(chat_type)
            if view is not None:
                self._chat_clear_view(view)
            self._chat_tree_rows[chat_type] = 0
            if chat_type == "dm":
                # Close the open conversation; the contact list stays (it is the store).
                self._chat_has_more["dm"] = False
                continue
            self._chat_has_more[chat_type] = bool(
                self._chat_store and self._chat_store.count(chat_type))
            if self._chat_has_more[chat_type]:
                self._rebuild_chat_view(chat_type)      # draw the load-more header
        self._dm_active_room = ""
        self._dm_active_peer = ""
        if getattr(self, "_dm_header_var", None) is not None:
            self._dm_header_var.set(self._t("chat.dm.pick"))
        self._refresh_dm_contacts()
        self._chat_count_var.set(self._t("chat.count", n=0))

    def _load_chat_history(self) -> None:
        """Point the chat store at the CURRENT CHARACTER and render its newest page.

        Called on startup and on profile switch. The store is per character, not per
        profile, so the character's uid has to be read from the game first — a daemon
        round trip that must not sit on the Tk thread. Resolve it off-thread, then
        open the matching file back on the Tk thread.
        """
        self._reopen_chat_store()

    def _resolve_char_uid(self) -> str:
        """The logged-in character's uid, read live from the game (or "" if unknown).

        Empty when the game is not alive / not logged in or the daemon is not up —
        the caller then shows no history until the chat monitor starts and the uid
        can be read.
        """
        try:
            return str(chat_share.self_profile(self._client).get("uid") or "")
        except Exception:       # noqa: BLE001 -- daemon down / game not alive
            return ""

    def _reopen_chat_store(self) -> None:
        """Resolve the current character's uid off-thread, then (re)open its store."""
        if self._chat_resolving:
            return
        self._chat_resolving = True

        def work() -> None:
            uid = self._resolve_char_uid()
            self.after(0, lambda: self._open_chat_store(uid))

        threading.Thread(target=work, daemon=True).start()

    def _open_chat_store(self, char_uid: str) -> None:
        """Open the SQLite store for ``char_uid`` and render the newest page per tab.

        Clears the current in-memory state first. An empty uid means the character is
        not known yet (game not alive): the tabs are simply left empty and no store is
        opened — persistence begins once the monitor starts and the uid resolves.
        """
        self._chat_resolving = False
        # Clear current state and drop the previous character's store.
        for chat_type in list(self._chat_msgs):
            self._chat_msgs[chat_type].clear()
            view = self._chat_trees.get(chat_type)
            if view is not None:
                self._chat_clear_view(view)
            self._chat_tree_rows[chat_type] = 0
            self._chat_has_more[chat_type] = False
        # The DM tab starts with no conversation open — the contact list is the entry
        # point, and a conversation loads only when a contact is clicked.
        self._dm_active_room = ""
        self._dm_active_peer = ""
        self._dm_unread = {}
        if getattr(self, "_dm_header_var", None) is not None:
            self._dm_header_var.set(self._t("chat.dm.pick"))
        if self._chat_store is not None:
            self._chat_store.close()
            self._chat_store = None
        self._chat_uid = char_uid or ""
        self._chat_count_var.set(self._t("chat.count", n=0))
        if not char_uid:
            self._refresh_dm_contacts()      # empties the sidebar too
            return

        try:
            store = chathistmod.ChatHistoryStore(self._profiles.chat_db(char_uid))
        except Exception as exc:        # noqa: BLE001 -- a bad store must not kill startup
            self._say("chat", "log.error", error=exc)
            return
        self._chat_store = store

        total = 0
        for chat_type in CHAT_TABS:
            total += store.count(chat_type)
            # DMs are shown per contact, not as one stream — the sidebar handles them.
            if chat_type == "dm":
                continue
            recs = store.recent(chat_type, CHAT_PAGE)
            if not recs:
                continue
            self._chat_msgs[chat_type] = recs
            self._chat_has_more[chat_type] = store.has_older(
                chat_type, recs[0].get("ts", 0))
            self._chat_tree_rows[chat_type] = 0
            self._rebuild_chat_view(chat_type)

        self._refresh_dm_contacts()
        self._chat_count_var.set(self._t("chat.count", n=total))
        if total:
            self._say("chat", "log.chat.history", n=total)


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
