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
  * Таймеры — a schedule: each listed errand (collect the base; donate to alliance tech;
    claim its gifts) has ITS OWN switch and period, and runs itself once that long has
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
import functools
import logging
import os
import queue
import re
import subprocess
import sys
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
from . import widgets
from .widgets import ScrollableFrame, font as ui_font
from .splash import SplashScreen
from .runtime import autostart as autostartmod
from .runtime import game_control as gamectl
from .runtime import panel_control as panelctl
from .runtime import panic as panicmod

import game_link
from . import dashboard as dashmod
from . import debug_log as dbgmod
from . import i18n as i18nmod
from . import runtime
from .runtime import stall as stallmod
from .runtime import tick as tickmod
from . import debug_sender as dbgsender
from . import profile as profilemod
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
import lua_actions      # noqa: E402
import coords           # noqa: E402
import game_paths       # noqa: E402  (where the game is — LW_LAUNCHER & co)
import game_buttons     # noqa: E402  (the named presses the reference pane lists)

WIN_PYTHON = game_paths.win_python()
DEFAULT_SERVER = str(lua_actions.HOME_SERVER)
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW
DETACHED = 0x00000008         # DETACHED_PROCESS
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

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

# -- is this checkout still the current one? --------------------------------
# The bot ships as a git checkout, so «обновиться» is a fast-forward of the repo the
# panel is imported from (panel/runtime/updates.py decides what that means). The panel
# looks once on the way up and then on this period, because it is meant to stay open
# for days and an update that landed this morning is worth knowing about tonight.
# Six hours: a fetch of one branch is cheap, but it IS network, and nothing about this
# repo moves fast enough to justify asking more often.
UPDATE_POLL_MS = 6 * 60 * 60 * 1000
# How long the first check waits after the window opens. The boot already spends its
# seconds on the daemon and the monitors; an SSH handshake on top of that would be one
# more thing between the operator and a usable panel.
UPDATE_FIRST_DELAY_MS = 20_000
# What each conclusion looks like. Amber is "there is something for you to do", red is
# "the check itself did not work"; everything else stays the neutral grey of a status
# line nobody needs to read. A state not named here is grey by default.
UPDATE_COLOURS = {
    runtime.updates.CURRENT: "#3c3",
    runtime.updates.BEHIND: "#e8c069",
    runtime.updates.AHEAD: "#888",
    runtime.updates.DIVERGED: "#e8c069",
    # Grey, not red: an origin that could not be reached is «не знаю», the same weight
    # as «нечего предлагать» — the panel works exactly as well either way. Red is kept
    # for ERROR, which is git itself refusing and worth a person's attention.
    runtime.updates.OFFLINE: "#888",
    runtime.updates.ERROR: "#c33",
}

# -- liveness ---------------------------------------------------------------
# How often the status row re-reads the game and the daemon. A process-list scan
# costs a few milliseconds off the Tk thread, so looking often is free — and
# without it the panel sat for an hour showing "running (pid …)" over a client
# that had crashed, every timer tick failing into the retry hold.
STATUS_POLL_MS = 8000
# What each link state looks like on the strip (panel/runtime/game_process.py decides
# which one it is). Green is the ONLY state that means the account is actually playing:
# a client that lost the server keeps its window, its pid and every Lua getter, so
# painting «работает» green over it is the whole bug this table exists to end. Amber is
# «не знаю» — a client that has not opened a game socket yet (a launch takes about 45
# seconds), or a machine that will not show us this client's sockets at all. Neither is
# a fault, and painting either red is how a warning stops being read by the second day.
LINK_COLOURS = {
    runtime.game_process.ONLINE: "#3c3",
    runtime.game_process.LOST: "#c33",
    runtime.game_process.UNKNOWN: "#e8c069",
    runtime.game_process.OFFLINE: "#c33",
}
# How long the game must read as gone before the watchdog relaunches it. Two
# polls, so a single scan that raced the process table (or a client restarting
# itself after the first login — it does that once) is not a crash.
WATCHDOG_STRIKES = 2
# Least time between two watchdog relaunches. A client that dies on startup would
# otherwise be relaunched every eight seconds forever.
WATCHDOG_COOLDOWN_SEC = 300.0
# How often «has the account been taken from us» is asked of a client that otherwise
# looks fine. Unlike the socket walk this is a round trip into the game VM (~0.7 s), so
# it is not free enough to make every eight seconds — but the kick modal does not
# self-dismiss and was still up seven minutes later when it was watched
# (docs/research/session-kick.md §4), so three polls is comfortably inside it.
#
# A lost link, and a kick already seen, are both asked EVERY poll: there the answer is
# the thing being decided, and the recovery counts consecutive readings.
KICK_POLL_SEC = 24.0

# How quiet the window size has to go before the window is painted again after a
# drag (see Panel._install_resize_damper). Long enough that the pauses inside a
# drag do not each cost a full repaint, short enough that letting go of the frame
# reads as instant. WM_SETREDRAW is the Windows message that turns painting off
# and on again; RedrawWindow's flags are INVALIDATE | ERASE | ALLCHILDREN | FRAME,
# i.e. "repaint the lot, title bar included".
RESIZE_SETTLE_MS = 160
# …and the longest painting may stay off whatever else goes wrong (#1211). A drag
# pauses for longer than this and repaints mid-drag, which is the price of never
# leaving a window that answers every click and shows none of them.
PAINT_OFF_MAX_MS = 500
WM_SETREDRAW = 0x000B
RDW_REPAINT_ALL = 0x0001 | 0x0004 | 0x0080 | 0x0400
# …and PAINT IT NOW rather than marking it dirty and hoping (#1210). Without
# RDW_UPDATENOW the flags above only queue a WM_PAINT, which Windows delivers when
# the message queue next runs dry — and the Tk thread of this panel does not run dry
# on any schedule worth trusting. The pixels Tk drew into a window that was not
# painting are gone until that WM_PAINT lands, so it is made to land here.
RDW_UPDATENOW = 0x0100

# -- the account dashboard --------------------------------------------------
# How often the strip is re-read. One game-VM call for all of it (panel/dashboard.py
# builds the single chunk), so the cost is a round trip; half a minute is well
# inside the pace at which any of these numbers actually changes.
DASH_POLL_SEC = 30.0

# The Python that runs every child (captures, robberies, the daemon). A constant
# no longer: it is a profile setting whose default this is, so a machine with
# Python somewhere else is a field to edit rather than a source change.
DEFAULT_WIN_PYTHON = WIN_PYTHON

# Game lifecycle. No hardcoded username and, since #1218, no hardcoded install either:
# `tools/lib/game_paths.py` is the one resolver, and `LW_LAUNCHER` / `LW_GAME_DIR` /
# `LW_GAME_EXE` move it without a source change. These stay as names because the file
# uses them; they are no longer a SECOND opinion about where the game is.
GAME_DIR = game_paths.game_dir()
LAUNCHER = game_paths.launcher()
GAME_EXE = game_paths.game_exe()

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
# Where the DSL action scripts live — the runtime's constant now, re-exported because
# this file's callers (and the tests) reach for it by the old name.
ACTIONS_DIR = runtime.ACTIONS_DIR
# The Settings page's own sub-pages moved with it (panel/tabs/settings.py SHELL_PAGES).

# One Tk variable per Settings knob is the RUNTIME's job now, done for every window it
# builds (panel/runtime/settings.py) — the factory used to live here, where a standalone
# tab cannot reach it, so `python -m panel.tabs.settings` drew its rows into a KeyError.

# Every knob the Settings page owns — the runtime's now (panel/runtime/settings.py),
# because a page that draws them can be a tab of its own and a standalone tab has no
# panel to ask. Re-exported: this file's callers and the tests reach for the old name.
SETTINGS_DEFAULTS = runtime.DEFAULTS

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


class Panel(runtime.SessionScoped, tk.Tk):
    """The window, and the profiles it has open.

    ONE WINDOW, SEVERAL PROFILES (#1206). Everything below that reads `self._rt`,
    `self._log`, `self._game` means «the profile whose page is showing» — which is what
    those names always meant; there is simply more than one profile for them to mean it
    about now. `SESSION_ATTRS` is the list of names that work that way and
    `panel/runtime/session.py::SessionScoped` is how, in fifty lines with a test.

    The window itself keeps only what is about the window: the menu, the geometry, the
    splash, the update check. Everything else belongs to a `ProfileSession` and keeps
    running whether or not its page is the one on screen.
    """

    #: The attributes that belong to the OPEN PROFILE rather than to the window
    #: (docs/research/multi-profile-panel.md §9.1). Reads and writes of exactly these
    #: go to the session showing; everything else is stored the ordinary way.
    #:
    #: A name that is a PROPERTY on this class is never routed, so the read-only
    #: shorthands (`_settings`, `_loading`, `_daemon_up`, `_client`, `_busy`, …) are
    #: deliberately absent — they already answer off `_binder` and `_game`, which are
    #: here.
    SESSION_ATTRS = frozenset({
        # the runtime, and the pieces this file calls by their own names
        "_rt", "_profiles", "_binder", "_i18n", "_logbus", "_tick", "_children",
        "_game", "_actions", "_schedule", "_timers", "_triggers", "_timer_store",
        # the technical loggers
        "_dbg", "_dbg_ui", "_dbg_status_prev",
        # the log pane
        "_log", "_log_lines", "_log_kept", "_log_menu", "_log_filter_var",
        # the tab area
        "_main_nb", "_main_split", "_main_controls", "_lazy_tabs", "_plugin_tabs",
        "_shown_tab",
        # the two strips
        "_status_var", "_status_lbl", "_status_msg", "_status_busy", "_recovery_var",
        "_panic_var", "_panic_lbl", "_resume_btn",
        "_daemon_var", "_daemon_lbl",
        # the account summary
        "_dash_values", "_dash_stop", "_dash_err", "_dash_view",
        # the map sweep
        "_sweep_stop", "_sweep_at", "_sweep_pass",
        # liveness and the watchdog
        "_game_gone", "_game_was_up", "_watchdog_last", "_link_gone",
        "_kick_at", "_kick_was",
        # the three lifecycle buttons, greyed off this profile's own client
        "_game_buttons",
        # the DSL command line
        "_cmd_var", "_cmd_at",
    })

    #: The outer notebook's style while ONE profile is open: the same layout with the
    #: tab strip taken out of it, so a panel that never opens a second profile looks
    #: exactly as it did before this existed.
    _ONE_PAGE_STYLE = "OneProfile.TNotebook"

    def __init__(self, active_profile: str | None = None) -> None:
        super().__init__()
        # NOTHING IS ROUTED YET. `SessionScoped` sends a declared name to the showing
        # session, and there is no session until the workspace has built one — so every
        # attribute set between here and the first `_adopt` is plainly the window's.
        self._current_session = None
        self._menubar = None
        self._menu_lang = None            # the language the menu bar is written in

        # WHAT IS HOLDING THE TK THREAD, when it is held (panel/runtime/stall.py).
        # Off unless `LW_PANEL_STALL_MS` asks for it, because a sampler that runs
        # always is a sampler nobody reads; on, it is the only thing in the panel that
        # can say what a freeze consisted of — everything else lives on the thread the
        # freeze has stopped. Reports go to stderr and to the debug log, never to the
        # log widget: a diagnostic that draws changes what it is measuring.
        self._stall = stallmod.from_env(self, report=self._stall_report)

        # WHAT THE PANEL IS DOING RIGHT NOW (#1208). The window's own steps — opening a
        # profile, building a tab, pulling an update — live here; each open profile
        # reports its own into `rt.activity`, and the strip along the bottom shows the
        # newest of all of them (`_paint_activity`). Built first because everything
        # below may already report into it.
        self._activity = runtime.Activity()
        self._activity_var = None
        self._activity_lbl = None
        self._activity_pending = False

        # THE WORKSPACE (panel/runtime/workspace.py): which profiles this window holds
        # open. `restore` opens whatever was open when it was last closed — for every
        # panel before #1206 that is exactly one, the profile the saved pointer names,
        # and `--profile` overrides which page is on top (creating it if it is new).
        profiles = profilemod.ProfileManager()
        # BEFORE ANY SESSION IS BUILT, because a session reads its port on the way up and
        # a link built on the wrong one drives the wrong client for the rest of the run
        # (#1224). Only the half that needs nothing asked — see `_sort_out_clients`.
        self._client_notes = self._sort_out_clients(profiles)
        # …and the same for the profiles this window is asked to reopen and cannot,
        # because another panel holds them (`_profile_held_elsewhere`): kept here while
        # the workspace is restoring and said once there is a page to say them on.
        self._held_notes: list = []
        self._workspace = runtime.Workspace(
            self, defaults=SETTINGS_DEFAULTS, profiles=profiles,
            log=self._session_complaint,
            can_open=self._profile_is_free, refused=self._profile_held_elsewhere)
        sessions = self._workspace.restore(first=active_profile)
        # Adopted before anything is said or drawn: `self._t` is a session's translator.
        self._adopt(self._workspace.current)
        for key, fmt in self._client_notes:
            self._say("profile", key, **fmt)
        # …and why a remembered profile is not here. Said now rather than during the
        # restore, when there was no session to say it into and it went to a stderr
        # nobody reads (#1215).
        for key, fmt in self._held_notes:
            self._say("profile", key, **fmt)
        self._held_notes = []
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
        self._install_exception_logging()
        # Profile picker lives in a modal (menu → «Профиль»), not on the main page.
        # The var is always live; the combo exists only while that modal is open.
        self._profile_var = tk.StringVar(value=self._workspace.current.name)
        self._profile_combo = None
        self._profile_client_lbl = None
        self._profile_win = None
        self._splash_step("splash.ui", 0.45)
        self._build_outer()
        # ONE PAGE PER OPEN PROFILE, each built under its own session so that every
        # widget, every variable and every armed callback belongs to that profile.
        for session in sessions:
            self._open_session_page(session)
        self._show(self._workspace.current)
        self._build_menu()
        self._restore_geometry()      # window size/position and the log sash
        self._install_resize_damper()  # …and keep dragging the frame cheap
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # …and the same close followed by a fresh start, asked for from the phone. The
        # press itself lives in `panel/runtime/panel_control.py`, which both front-ends
        # read; this is the one thing in the process that can carry it out, so this is
        # where it is registered (#1258).
        panelctl.set_handler(self._restart_now)
        # …and the same for «Включить обратно»: only the shell knows which profiles
        # are open and which tabs each has, so it says how, and the phone only asks
        # whether anybody can (panel/runtime/panic.py).
        panicmod.set_handler(self._resume)
        self._splash_step("splash.daemon", 0.6)
        # Bringing the systems up is the slow half of the boot — the monitors, the
        # schedule, the trigger listeners, the chat history, the daemon, the account
        # strip. It runs on its own thread (it waits on processes and on the game),
        # but the splash STAYS UP until it is done: everything it registers —
        # `after` chains, Tk callbacks, the first painting of the chat views — used
        # to land in the window's lap after the splash had already gone, which is
        # why a freshly opened panel sat there unresponsive and half-drawn.
        self._boot_step: "queue.Queue[tuple]" = queue.Queue()
        self._boot_done = threading.Event()
        self._boot_lock = threading.Lock()
        # ONE THREAD PER SESSION, not one after another: `_ensure_daemon` blocks for up
        # to half a minute, and two profiles must not mean two minutes of splash.
        self._boot_left = len(sessions)
        for session in sessions:
            threading.Thread(target=self._startup_boot, args=(session,),
                             daemon=True).start()
        self._await_boot()
        self._start_health_watch()
        # …and ask origin whether this checkout is still the current one — after a
        # pause, because the first thing a freshly opened panel owes the operator is a
        # window, not an SSH handshake with github.
        # …unless the page it would report into was never built (`LW_PANEL_BARE`).
        if not os.environ.get("LW_PANEL_BARE"):
            self._arm("updates", UPDATE_FIRST_DELAY_MS, self._poll_updates)
        # Fade the splash and reveal the fully-built window.
        if self._splash is not None:
            try:
                self._splash.finish(self._t("splash.ready"))
            except Exception:        # noqa: BLE001
                pass
            self._splash = None
        self._reveal_window()

    # -- the profiles this window has open ----------------------------------
    #
    # Three helpers and the rule they exist for. Routing (`SessionScoped`) answers
    # «the session whose page is showing», which is right for a button and WRONG for a
    # timer firing while the operator is looking at another profile. So the binding
    # happens where work is SCHEDULED, never where an attribute is used: `_arm` binds
    # what it arms, a thread is given a bound target, and an `after` that touches a
    # declared name goes through `_later`. Get that right once at each of those places
    # and every method in this file keeps working unchanged.

    def _on(self, session):
        """Act for ``session`` on THIS thread until the block ends.

        Thread-local (`SessionScoped.session_scope`), not a swap of one shared
        attribute: the boot runs a thread per open profile and they would otherwise
        overwrite each other's idea of «the current profile» — which they did, and both
        booted the same one.
        """
        return self.session_scope(session)

    def _bound(self, func, session=None):
        """``func``, re-entering the session it was made in whenever it is called.

        «Made in» is `_session()` — the session THIS THREAD is acting for — and not
        `_current_session`, which is only the one whose page is showing. The difference
        is invisible on the Tk thread and load-bearing everywhere else: `_startup` runs
        on a thread per profile, so everything IT arms or spawns (the status poll, the
        account-strip poller) was being bound to whichever page happened to be on
        screen. The second profile's dashboard then polled the FIRST profile's client
        and wrote its readings into the first profile's log — the numbers were real,
        they were just the wrong account's.
        """
        return self.bind_session(func, session)

    def _later(self, delay_ms: int, func):
        """A one-shot callback that touches this profile, on the Tk thread. Bound.

        Never raises. Most callers are worker threads coming back to repaint something,
        and `after` itself is a Tk call: from a worker, while the main thread is not
        inside the event loop (which during the boot is most of the time), it raises
        «main thread is not in main loop» and killed the whole worker. What is being
        scheduled is always a repaint, and the poll behind it comes round again — so a
        hand-over that cannot be made is dropped, not thrown.

        WITH NO DELAY it is not `after` at all any more (#1226). «Run this on the Tk
        thread as soon as you can» is a hand-over, and a hand-over goes through the
        window's queue: a worker calling `after` does not schedule anything, it waits
        for the event loop — the same event loop every other open profile is drawing on.
        A real DELAY still needs `after`, because only Tk has a clock; those callers are
        on the Tk thread already (a settle, a re-poll after an action).
        """
        if not delay_ms:
            ticker = getattr(self, "_tick", None)     # before the first `_adopt`
            if ticker is not None:
                ticker.post(self._bound(func))
                return None
        try:
            return self.after(delay_ms, self._bound(func))
        except (tk.TclError, RuntimeError):
            return None

    def _session_complaint(self, session, message: str) -> None:
        """One session raised while the window was fanning something out at all of them."""
        try:
            with self._on(session):
                self._log_put(f"[panel] {session.name}: {message}")
                self._dbg.error("session %r: %s", session.name, message)
        except Exception:                  # noqa: BLE001 — a complaint, not the panel
            pass

    def _profile_is_free(self, name: str) -> bool:
        """Is ``name`` open in no OTHER panel? (ONE PANEL PER PROFILE.)

        Two windows on two profiles is a way people work; two windows on the same
        profile is the one that breaks quietly — both write its `config.json` over each
        other and both drive its daemon. A profile this window already holds reads as
        free, because the lock it is refused by is its own.
        """
        if self._workspace.get(name) is not None:
            return True
        return not autostartmod.locked(self._workspace.profiles, name)

    def _profile_held_elsewhere(self, name: str) -> None:
        """A remembered profile was NOT opened: somebody holds its instance lock.

        SAID WHERE A PERSON WILL READ IT (#1215). This went straight into `_say`, and
        `Workspace.restore` runs before any session has been adopted — so the line had
        no log to land in and fell through to a stderr a windowed panel does not have.
        The profile was simply missing, with nothing anywhere saying why; and because a
        profile that was not restored has no page, every switch to it afterwards paid
        for a whole page build.

        And it says WHOSE lock it is, which is the difference between the two cases
        that look identical from here: a second panel that is genuinely running (use
        that window) and a lock held by a process that stopped answering its own event
        loop (close it — until it is gone this profile cannot be opened at all). The
        lock itself is never broken: it is the kernel's answer to «is a process holding
        this profile», and overruling it on the strength of a file's timestamp is how
        two panels end up writing one `config.json`.
        """
        note = self._holder_note(name)
        if self._current_session is None:
            # Still in `restore`: keep it until there is a page to say it on.
            self._held_notes.append(note)
            return
        try:
            self._say("profile", note[0], **note[1])
        except Exception:                      # noqa: BLE001 — before there is a log
            print(f"[profile] {name} is open in another panel", file=sys.stderr)

    def _holder_note(self, name: str) -> tuple:
        """Which line to say about a profile this window could not open, and its values."""
        profiles = self._workspace.profiles
        try:
            life = autostartmod.probe(profiles, name)
            pid = life.pid or autostartmod.holder(profiles, name) or 0
        except Exception:                      # noqa: BLE001 — a note, never the boot
            return ("log.profile.held_elsewhere", {"name": name})
        if life.running:
            return ("log.profile.held_elsewhere", {"name": name})
        # The lock is held and the panel behind it is not beating: it is hung, or it
        # left something of its own holding the file. Either way the person has to go
        # and close it, and nothing here can do it for them.
        return ("log.profile.held_stale",
                {"name": name, "pid": pid, "mins": int((life.age or 0) // 60)})

    def _adopt(self, session) -> None:
        """Point the window at ``session`` and fill in the names this file calls by hand.

        The assignments land in the SESSION's state, not the window's, because every
        one of them is declared in `SESSION_ATTRS`. Which is the whole trick: the two
        hundred methods below go on saying `self._game` and mean this profile's.
        """
        self._current_session = session
        rt = session.rt
        self._rt = rt
        self._profiles = rt.profiles
        self._binder = rt.settings
        self._i18n = rt.i18n
        self._logbus = rt.log
        self._tick = rt.tick
        self._children = rt.children
        self._game = rt.game
        self._actions = rt.actions

    def _show(self, session) -> None:
        """Bring one open profile's page to the front. Nothing else changes.

        Explicitly NOT a profile switch: the session that goes out of sight keeps its
        daemon, its schedule, its captures and its claim. Only the window's own chrome
        follows, because the menu and the title are the window's and are said in the
        language of whatever profile is being looked at.
        """
        if session is None:
            return
        # BEFORE ANYTHING ELSE: put the picture back up. The resize damper switches
        # Windows' painting of this window off while a size settles
        # (`_install_resize_damper`), and a switch that lands inside that window drew a
        # whole page into a window that was not painting — the operator's click looked
        # ignored, the Tk thread being perfectly answerable the whole time (#1211).
        self._resume_painting()
        self._current_session = session
        self._profile_var.set(session.name)
        # EVERY PAGE GETS ITS OWN SASH, not just the first. `_restore_geometry` places
        # it once, for the window, out of whichever profile was in front at boot — so
        # the log pane of every other open profile sat wherever the pane happened to
        # leave it, and the position the operator dragged there was remembered and
        # never applied. It is a per-profile setting; this is where a page finds out
        # its own.
        try:
            if getattr(session, "page", None) is not None:
                # The pane has to have been laid out before a sash position means
                # anything, so this one `update_idletasks` stays.
                session.page.update_idletasks()
                self._apply_sash(self._saved_sash())
                # …and DRAW IT, rather than trusting that it drew itself. A page built
                # while another profile was in front is laid out here for the first
                # time, and whatever Tk painted while it was doing so may never have
                # reached the glass — see `_repaint_page` (#1210).
                self._repaint_page(session.page)
        except (tk.TclError, RuntimeError):
            pass
        try:
            self.title(self._t("app.title"))
            # ONLY WHEN THE WORDS WOULD CHANGE. Rebuilding the menu bar is a native
            # Windows call per switch, and it dropped three `tk.Menu` objects on the
            # floor each time — for a menu that says the same three words unless the
            # profile being looked at is in another language.
            if getattr(self, "_menu_lang", None) != self._i18n.lang:
                self._build_menu()
            # The strip is said in the language of the page being looked at, and names
            # a profile only while more than one is open — both change here.
            self._paint_activity()
        except tk.TclError:                # the window is going away
            pass

    # -- the outer notebook: one page per open profile -----------------------
    def _build_outer(self) -> None:
        """The profile notebook, with a style that can hide its own tab strip."""
        style = ttk.Style(self)
        style.layout(self._ONE_PAGE_STYLE, style.layout("TNotebook"))
        style.layout(f"{self._ONE_PAGE_STYLE}.Tab", [])       # no strip at all
        # BEFORE the notebook, and along the bottom: packed first so the strip keeps
        # its own two rows of pixels whatever the pages inside ask for.
        self._build_status_line()
        self._outer = ttk.Notebook(self)
        self._outer.pack(fill="both", expand=True)
        self._outer.bind("<<NotebookTabChanged>>", self._on_session_tab_changed)

    # -- the strip along the bottom: what the panel is doing right now --------
    #
    # THE WINDOW'S, not a page's (#1208). Everything that makes a panel sit there
    # silently for seconds — building a profile's fifteen tabs, waiting on a daemon that
    # takes half a minute, playing a scenario, pulling an update — happens somewhere
    # this strip can see, and none of it happens where the operator can. A log line is
    # written afterwards and says what HAPPENED; this says what is happening.
    #
    # It shows the newest live step of the window's own activity and of every open
    # profile's (panel/runtime/activity.py), so a background profile bringing its daemon
    # up is visible while another profile's page is the one on screen — named, in that
    # case, because «поднимаю демон» is a different sentence when it is not this page's.
    def _build_status_line(self) -> None:
        ttk.Separator(self, orient="horizontal").pack(side="bottom", fill="x")
        bar = ttk.Frame(self, padding=(8, 2))
        bar.pack(side="bottom", fill="x")
        self._activity_var = tk.StringVar(value=self._t("activity.idle"))
        self._activity_lbl = ttk.Label(bar, textvariable=self._activity_var,
                                       anchor="w", foreground="#888")
        self._activity_lbl.pack(side="left", fill="x", expand=True)
        # The words follow the language of whatever profile is being looked at, and the
        # strip is a variable rather than a `tr`-registered widget — so it is re-said
        # here instead of by the registry.
        self._hook(self._paint_activity, "activity-line")
        # The window's own steps. Each open profile's are added by `_watch_activity`
        # as its page is built.
        self._activity.listen(self._activity_changed)

    def _watch_activity(self, session) -> None:
        """Have one open profile's steps painted on the strip too.

        No unsubscribe is kept: the listener is stopped by the runtime going away with
        the session, and `_paint_activity` reads the workspace afresh every time — so a
        step reported by a profile that has just been closed paints nothing at all.
        """
        try:
            session.rt.activity.listen(self._activity_changed)
        except Exception:                      # noqa: BLE001 — a strip, never the boot
            self._dbg.error("activity listener failed", exc_info=True)

    def _activity_changed(self) -> None:
        """Something started or finished, on whatever thread started or finished it."""
        if threading.current_thread() is threading.main_thread():
            # ON THE TK THREAD the news is almost always «I am about to do the slow
            # thing», and an `after` would deliver it once the slow thing is over —
            # which is precisely too late to be worth saying. Paint it now, and force
            # the one redraw that puts it on the glass before the loop is blocked.
            self._paint_activity()
            try:
                self.update_idletasks()
            except (tk.TclError, RuntimeError):
                pass
            return
        if self._activity_pending:             # one repaint per turn, not per reporter
            return
        self._activity_pending = True
        # OFF THE TK THREAD it is a hand-over, and a hand-over goes through the window's
        # queue rather than `after` — a step is reported by the very worker whose work
        # the strip is about, and it must not pay the event loop to say so (#1226).
        post = tickmod.poster(self)
        if post is None:                       # no loop to paint from (closing, a test)
            self._activity_pending = False
            return
        post.post(self._paint_activity)

    def _paint_activity(self) -> None:
        """Write the newest live step — of any open profile — onto the strip."""
        self._activity_pending = False
        var = getattr(self, "_activity_var", None)
        if var is None:
            return
        try:
            said = self._activity_text()
            var.set(said)
        except tk.TclError:                    # the window is going away
            return
        # While the window is still hidden the strip is behind a splash, and the same
        # sentence is what the splash has room for — so the boot's «интерфейс» phase
        # names the tab it is on. `say`, NEVER `step`: this is reported from INSIDE a
        # page build, and `step` pumps the whole event queue (see panel/splash.py).
        splash = getattr(self, "_splash", None)
        if splash is not None:
            try:
                splash.say(said)
            except Exception:                  # noqa: BLE001 — never load-bearing
                self._splash = None

    def _activity_text(self) -> str:
        newest, owner = None, None
        for who, activity in self._activities():
            step = activity.current()
            if step is not None and (newest is None or step.seq > newest.seq):
                newest, owner = step, who
        if newest is None:
            return self._t("activity.idle")
        said = self._t(newest.key, **newest.fmt)
        # Named only when the name adds something: one profile open, or the step is
        # this window's own, and «who» is not in question.
        if owner and len(self._workspace) > 1:
            return self._t("activity.scoped", profile=owner, what=said)
        return said

    def _activities(self) -> list:
        """``(profile name or None, Activity)`` for the window and every open profile."""
        out = [(None, self._activity)]
        for session in self._workspace.sessions:
            activity = getattr(session.rt, "activity", None)
            if activity is not None:
                out.append((session.name, activity))
        return out

    def _paint_outer(self) -> None:
        """Show the profile strip only once there is more than one page to pick from."""
        try:
            self._outer.configure(style="TNotebook" if len(self._workspace) > 1
                                  else self._ONE_PAGE_STYLE)
        except tk.TclError:
            pass

    def _on_session_tab_changed(self, _event=None) -> None:
        try:
            page = self._outer.nametowidget(self._outer.select())
        except (tk.TclError, KeyError):
            return
        session = next((s for s in self._workspace.sessions if s.page is page), None)
        if session is None or session is self._current_session:
            return
        # Timed, because «переключение подвесило панель» has to be answerable with a
        # number and a name rather than a guess (#1211). DEBUG, so it costs a line in
        # the rotating log and nothing on screen.
        started = time.perf_counter()
        self._workspace.switch_to(session.name)
        moved = time.perf_counter()
        self._show(session)
        dbg = getattr(self, "_dbg", None)
        if dbg is not None:
            dbg.debug("switched to %r: workspace %d ms, page %d ms",
                      session.name, (moved - started) * 1000,
                      (time.perf_counter() - moved) * 1000)

    def _open_session_page(self, session, staged: bool = False, done=None) -> None:
        """Build one open profile: its page, its tabs, its log, its strips.

        This is what the whole of `__init__` used to be, minus the window. It runs once
        per session, under that session, so every widget it makes and every callback it
        arms belongs to the profile it was made for.

        ``staged`` spreads the plugin tabs over the event loop instead of building them
        in one go — see `_stage`. It is what the window does once it is open and the
        operator is looking at it; at boot the splash is up and there is no loop to
        stay answerable to, so the boot builds straight through.

        ``done`` is called once the page is complete, whichever way it was built: with
        `staged` the method returns long before that, and what follows an open profile —
        its start-up thread — must not begin against half a page.
        """
        # PINNED TO THE SESSION BEING BUILT, not to the one on screen. Every routed
        # name this writes — `_log`, `_main_nb`, `_status_var`, the lot — goes to
        # whichever session `_session()` answers, and until this that was
        # `_current_session`: a global that ANY re-entrant callback can move. One does
        # get in, too. Building a page adds pages to a notebook, and a notebook queues
        # `<<NotebookTabChanged>>`; anything that pumps the event loop mid-build (a
        # splash rendering itself, an `update()`) delivers it, `_on_session_tab_changed`
        # calls `_show`, and from that line on the rest of THIS page is recorded against
        # the OTHER profile. Which is exactly what a person sees as «открываю первый
        # профиль — чистая страница». The binding is thread-local and takes precedence,
        # so the build cannot be stolen from itself.
        with self._on(session):
            self._draw_session_page(session, staged, done)

    def _draw_session_page(self, session, staged: bool, done) -> None:
        """The page itself. Always under `_open_session_page`'s session binding."""
        page = ttk.Frame(self._outer)
        session.page = page
        self._outer.add(page, text=session.label())
        self._paint_outer()
        self._adopt(session)
        self._watch_activity(session)
        self._binder.loading = True   # suppresses auto-save while we apply settings
        # Technical debug log (panel/debug_log.py): a rotating file, one per profile,
        # kept apart from panel.log and the UI widget. Pointed at this profile before
        # any _log_put, so the first line and any start-up traceback land in it. Two
        # component loggers: `panel` for lifecycle and errors, `ui` for the mirror of
        # every widget line. _dbg_status_prev remembers the last systems snapshot so
        # only transitions are logged at INFO.
        self._configure_debug_log()
        self._dbg = self._rt.dbg("panel")
        self._dbg_ui = self._rt.dbg("ui")
        self._logbus.set_debug_logger(self._dbg_ui)
        self._dbg_status_prev = None
        self._dbg.info("panel starting — profile %r, version %s",
                       self._profiles.active, APP_VERSION)
        # Everything the panel says goes through one sink (panel/runtime/log.py): the
        # queue this page drains, the profile's panel.log, and the debug log. The
        # WIDGET is this page's — a tab launched on its own has none, and says the
        # same lines into the same two files.
        self._log = None              # the widget, built by _build_ui
        self._log_lines = 0           # lines in the widget, for the retention cap
        self._log_kept: list = []     # every line this session, for a filter redraw
        # An action letting go of the game is when the status strip is stale — the link
        # says so, and only a window that HAS a strip does anything about it. Both of
        # these are called from the link's own thread, so both are BOUND: the indicator
        # that gets painted must be the one on this profile's page.
        self._game.on_settled = self._bound(
            lambda: self._later(400, self._refresh_status))
        self._game.on_state = self._bound(self._daemon_state)
        # «I am still here», once a minute, from this window's event queue and once per
        # OPEN PROFILE — the hourly scheduled check reads one per profile
        # (panel/runtime/autostart.py), and a profile this panel is quietly farming
        # must not read as stopped and have a second panel opened on it.
        self._rt.start_heartbeat()
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
        # How many consecutive polls have found the server connection gone, so only
        # the edges reach the log rather than every eight seconds of it
        # (see `_announce_link`).
        self._link_gone = 0
        # When the kick modal was last asked about, and what it said. The answer is
        # CARRIED between reads rather than re-read every poll (`_read_kicked`): the
        # recovery counts consecutive readings, so a throttle that answered «no kick»
        # in the gaps would reset the count it is meant to be feeding.
        self._kick_at = 0.0
        self._kick_was = False
        # Account dashboard: the last readings and the poller's stop flag. The WIDGET is
        # made when «Аккаунты» is first drawn and not before (`_on_tab_realized`,
        # #1215), so the poller has to be able to run with nowhere to paint.
        self._dash_values: dict = {}
        self._dash_view = None
        self._dash_stop = None
        self._dash_err = ""          # last complaint, so it is said once not per poll
        # THE SCHEDULE (panel/runtime/schedule.py): errands on a clock and errands
        # the wire sets off, sharing one single-file queue. One per open profile, so
        # two accounts keep two schedules and neither waits for the other.
        self._splash_step("splash.triggers", 0.35)
        self._schedule = self._rt.schedule
        self._timers = self._schedule.timers
        self._triggers = self._schedule.triggers
        self._timer_store = self._schedule.store
        # Two rules the schedule does not own: the rally auto-join's daily cap, and the
        # squads it joins with. Both belong to the rally code (Tk-free on purpose, so
        # they answer in a profile that does not show the tab); only the wiring is here.
        # Bound and captured, because the scheduler calls them from its own thread and
        # they must read THIS profile's caps rather than the showing one's.
        self._schedule.register_gate(
            "rally_auto_join",
            self._bound(lambda rt=self._rt: rallygate.join_gate(rt)),
            self._bound(lambda spent, rt=self._rt: rallygate.record_joins(rt, spent)))
        self._schedule.register_args("rally_auto_join",
                                     self._bound(self._rally_join_args))
        self._build_ui(page, staged=staged,
                       done=lambda: self._finish_session_page(session, done))

    def _finish_session_page(self, session, done=None) -> None:
        """The last of a page, once every tab on it has been built.

        Split off `_open_session_page` because a staged build returns before the tabs
        exist and every line here needs them: the saved values are pushed into the
        tabs' own widgets, the auto-save traces the variables they made, and the status
        poll paints a strip that is not there yet.
        """
        with self._on(session):
            self._apply_settings_to_ui()  # restore this profile's saved values
            self._loading = False
            self._install_autosave()      # persist every subsequent change immediately
            self._pump_log()
            self._open_panel_log()
            self._refresh_status()
            self._poll_status()       # …and keep re-reading it: a crash is silent otherwise
            # The notebook's own «this tab is showing» went out before there was a
            # handler to hear it (the binding is made with `_lazy_tabs`, at the end of
            # the build), so the tab in front is told once, here.
            self._on_main_tab_changed()
        if done is not None:
            done()

    # -- building a page a piece at a time -----------------------------------
    def _stage(self, session, steps, staged: bool) -> None:
        """Run ``steps`` — one per turn of the event loop when ``staged`` (#1208).

        A profile's page is fifteen tabs, and building them is a second and a half of
        Tk with nothing between the widgets for the loop to run in: the window went
        white, the strip along the bottom could not be repainted, and every click
        queued up until it was over. None of that work can leave the Tk thread — it IS
        widgets — but it does not have to happen all at once. One step per turn keeps
        the window answering and lets the strip say which tab it is on.

        Every step re-enters its session, because the operator may well click back to
        another profile while this one is filling in; and every step checks the session
        is still open, because they may also close it, or the window.
        """
        if not staged:
            for step in steps:
                self._stage_one(session, step)
            return

        def turn(index: int = 0) -> None:
            if index >= len(steps) or not self._session_alive(session):
                return
            self._stage_one(session, steps[index])
            try:
                self.after(1, lambda: turn(index + 1))
            except (tk.TclError, RuntimeError):    # the window went away under us
                pass
        turn()

    def _stage_one(self, session, step) -> None:
        """One build step, under its session, and never fatal to the rest of the page."""
        with self._on(session):
            try:
                step()
            except Exception:                      # noqa: BLE001 — one step, not the page
                self._dbg.error("build step %r failed", getattr(step, "__name__", step),
                                exc_info=True)

    def _session_alive(self, session) -> bool:
        """Is this session still open, and still the one under that name?"""
        try:
            return self._workspace.get(session.name) is session
        except Exception:                          # noqa: BLE001 — the window is going
            return False

    def _startup_boot(self, session=None) -> None:
        """`_startup` for one session, with the splash told where it has got to.

        The end signal is raised only when the LAST session has finished, so the splash
        stays up until every open profile has its systems, not just the first.
        """
        session = session if session is not None else self._session()
        try:
            with self._on(session):
                self._startup()
        except Exception:            # noqa: BLE001 — a failed system is a log line,
            with self._on(session):                            # not a dead panel
                self._dbg.error("startup failed", exc_info=True)
        finally:
            with self._boot_lock:
                self._boot_left -= 1
                done = self._boot_left <= 0
            if done:
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
    def _game_exe(self) -> str:
        return self._opt_str("game_exe")

    # There WAS a `_game_user()` here, and it existed to refuse things: which Windows
    # session this profile's client lives in, read so the two lifecycle buttons could
    # decline. Nothing declines any more (#1218) — the recipes carry the session, and
    # the runtime hands it to them (`PanelRuntime.game_target`) and to the daemon it
    # starts (`GameLink.user`). `runtime.game_process.profile_user` is the one reader.

    def _game_status(self) -> tuple:
        """`(running, label)` for THIS profile's client — its executable, its session."""
        return runtime.game_process.profile_status(self._binder)

    def _game_probe(self):
        """The same reading with the LINK in it — online, lost, unknown, offline.

        What the strip and the phone show. `_game_status` is the half everything that
        merely presses buttons still asks for: a client that lost the server is running,
        and must not be relaunched from under the person.
        """
        return runtime.game_process.profile_probe(self._binder)

    def _launcher(self) -> str:
        return self._opt_str("launcher")

    def _autoloot_limit(self) -> int:
        return self._opt_int("autoloot_limit", low=1, high=50)

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

    def _set_language(self, lang: str) -> None:
        if self._i18n.set_lang(lang):
            self._apply_language()
            self._save_settings()   # language is a per-profile setting

    def _apply_language(self) -> None:
        self.title(self._t("app.title"))
        self._i18n.retranslate()
        self._refresh_status()   # re-render translated daemon/status words
        # The bottom strip belongs to the WINDOW, so it is not in the retranslate
        # registry of whichever profile's translator was just switched.
        self._paint_activity()

    def _build_menu(self) -> None:
        #: Which language the bar standing there is written in — `_show` rebuilds it
        #: only when that stops being the one being looked at (#1211).
        self._menu_lang = self._i18n.lang
        # The bar this replaces is dropped rather than left to the garbage collector:
        # a `tk.Menu` is a Tcl command and a native menu handle, and one per profile
        # switch is a leak that Windows notices long before Python does.
        old = getattr(self, "_menubar", None)
        menubar = tk.Menu(self)

        lang_menu = tk.Menu(menubar, tearoff=0)
        self._lang_var = getattr(self, "_lang_var", tk.StringVar())
        self._lang_var.set(self._i18n.lang)
        # The menu IS the locales directory: a file each, labelled with what the file
        # calls itself. Adding a language is copying en.json and translating it — there
        # is no list here to add it to (panel/i18n.py).
        for lang in self._i18n.available():
            lang_menu.add_radiobutton(
                label=self._i18n.name(lang), value=lang,
                variable=self._lang_var, command=lambda l=lang: self._set_language(l))

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=self._t("menu.help.send_log"),
                              command=self._open_send_log_dialog)
        help_menu.add_command(label=self._t("menu.help.about"), command=self._show_about)

        menubar.add_command(label=self._t("menu.profile"),
                            command=self._open_profile_dialog)
        menubar.add_cascade(label=self._t("menu.language"), menu=lang_menu)
        menubar.add_cascade(label=self._t("menu.help"), menu=help_menu)
        self.config(menu=menubar)
        self._menubar = menubar
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:            # already gone with the window
                pass
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
        """«Отправить»: hand the archive to the sender (result lands in the log).

        The packing is the runtime's — the «Настройки» tab's button presses the same
        function, and this dialog must work in a profile that switched that tab off.
        """
        win.destroy()
        runtime.diag.send_archive(self._rt)

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
        self._profile_combo.bind("<<ComboboxSelected>>",
                                 lambda e: (self._paint_profile_client(),
                                            self._switch_profile()))
        # Said out loud, because the combo now does two things: a profile that is
        # already open is gone to, one that is not is OPENED beside it (#1206).
        self._tr(ttk.Label(frm, foreground="#888"), "profile.open_hint").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        # WHICH CLIENT THE SELECTED PROFILE DRIVES (#1252). The one fact about a profile
        # that decides whether it farms its own account or somebody else's, and it used
        # to be spread over two boxes on a Settings page nobody visits.
        self._profile_client_lbl = ttk.Label(frm, foreground="#888", wraplength=320,
                                             justify="left")
        self._profile_client_lbl.grid(row=2, column=0, columnspan=2, sticky="w",
                                      pady=(6, 0))
        self._paint_profile_client()

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, sticky="we", pady=(14, 0))
        self._tr(ttk.Button(btns, command=lambda: self._switch_profile()),
                 "profile.open").pack(side="left")
        self._tr(ttk.Button(btns, command=lambda: self._close_profile()),
                 "profile.close_one").pack(side="left", padx=6)
        self._tr(ttk.Button(btns, command=self._create_profile),
                 "profile.new").pack(side="left")
        self._tr(ttk.Button(btns, command=self._rename_profile),
                 "profile.rename").pack(side="left", padx=6)
        self._tr(ttk.Button(btns, command=self._delete_profile),
                 "profile.delete").pack(side="left")
        self._tr(ttk.Button(btns, command=self._reveal_profile_dir),
                 "profile.folder").pack(side="left", padx=6)
        self._tr(ttk.Button(btns, command=win.destroy),
                 "profile.close").pack(side="right")
        # NOTHING ELSE GOES HERE (#1263). There used to be a «Развести клиенты…» below
        # this row that asked a login per shared profile and wrote the answers to disk —
        # under profiles that were open, whose widgets then put the old values back on
        # the next save. It reported success and changed nothing. Which client a profile
        # drives is now edited where the profile is configured: «Настройки» → «Игра» →
        # «Сессия Windows», through that profile's own bound variables.

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
            self._profile_client_lbl = None
            self._profile_win = None

    def _reveal_profile_dir(self) -> None:
        """Open the selected profile's own directory — where its `config.json` lives.

        «Я продолжаю видеть пустую папку profiles» (#1263), and the person was right to
        be confused: there are TWO directories of that name in this repository. The
        panel's profiles are `panel/profiles/<name>/`, one directory per account with a
        `config.json` in it; the `profiles/` in the repository root belongs to the DSL
        bot's own `--profile` (src/lastwar_bot/profile.py), holds one flat json per id,
        and has nothing to do with the panel. Looking into the wrong one shows an empty
        directory and no way to tell why. So the panel opens the right one.
        """
        name = self._profile_var.get() or self._profiles.active
        try:
            self._reveal_in_explorer(self._profiles.dir(name))
        except Exception as exc:          # noqa: BLE001 — a line, not the dialog
            self._say("profile", "log.profile.folder_failed", error=exc)

    def _paint_profile_client(self) -> None:
        """Say which client the profile in the combo drives — and if it is not alone.

        The second half is what «Развести клиенты…» used to be a button for (#1263):
        the state is named here, and the sentence says where it is put right, because
        the fix belongs to the profile being configured and not to this window.
        """
        label = getattr(self, "_profile_client_lbl", None)
        if label is None:
            return
        name = self._profile_var.get()
        client = runtime.provision.clients(self._profiles).get(name)
        if client is None:
            text = ""
        elif client.console:
            text = self._t("session.client.console", port=client.port)
        else:
            text = self._t("session.client.session", user=client.user,
                           port=client.port)
        others = runtime.provision.sharing_with(self._profiles, name) if client else []
        if others:
            text = text + "\n" + self._t(
                "profile.client.shared", others=", ".join(others),
                tab=self._t("tab.settings"), page=self._t("settings.tab.game"),
                frame=self._t("session.frame"))
        try:
            label.configure(text=text, foreground="#e0a84f" if others else "#888")
        except tk.TclError:
            pass

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
        self._paint_profile_client()

    def _switch_profile(self, name: str | None = None) -> None:
        """Go to a profile: its page if it is open, a NEW page if it is not.

        This used to re-point the one runtime the window had. It opens a second one
        instead (#1206) — which is what «open a profile and run a daemon in it» asks
        for, and it needs no new control: picking a profile that is not open is how you
        open it, and picking one that is brings its page to the front. The one being
        left keeps its daemon, its schedule and its captures; nothing is flushed,
        because nothing is going away.
        """
        name = name or self._profile_var.get()
        session = self._workspace.get(name)
        if session is not None:
            if session is not self._current_session:
                self._outer.select(session.page)
            return
        self._open_profile(name)

    def _open_profile(self, name: str) -> None:
        """Open one more profile beside the ones already open, and go to it.

        The page is built A STEP AT A TIME (#1208). This used to be one straight call
        that built fifteen tabs before it returned: some three seconds in which the
        window did not redraw, did not answer a click and said nothing about what it
        was doing — «переключение подвесило панель», which is exactly what it looked
        like. Now the page appears at once, fills in tab by tab with the strip along
        the bottom naming each, and what comes after it waits for `_opened`.
        """
        if not self._profile_is_free(name):
            self._profile_held_elsewhere(name)
            messagebox.showwarning(self._t("panel.busy.title"),
                                   self._t("panel.busy", profile=name),
                                   parent=self._profile_dialog_parent())
            return
        opening = self._activity.begin("activity.profile.open", name=name)
        session = self._workspace.open(name)
        self._open_session_page(
            session, staged=True,
            done=lambda: self._opened(session, opening))
        self._outer.select(session.page)
        self._show(session)

    def _opened(self, session, opening) -> None:
        """One more profile is fully drawn: say so, and bring its systems up."""
        self._activity.end(opening)
        with self._on(session):
            self._say("profile", "log.profile.opened", name=session.name)
        # Its systems come up on their own thread, exactly as they do at boot: the
        # daemon alone can block for half a minute and the window must stay answerable.
        threading.Thread(target=self._bound(self._startup, session),
                         daemon=True).start()

    def _close_profile(self, name: str | None = None) -> None:
        """Close one open profile: its errands, its captures, its claim, its page.

        The last one cannot be closed — a window with no profile in it is a window with
        nothing in it, so the workspace refuses and this says so rather than emptying
        the notebook.
        """
        name = name or self._profile_var.get()
        session = self._workspace.get(name)
        if session is None:
            return
        if len(self._workspace) <= 1:
            self._say("profile", "log.profile.last_one", name=name)
            return
        page = session.page
        with self._activity.step("activity.profile.close", name=name):
            self._close_session(session)
            if self._workspace.close(name) is None:
                return
            try:
                if page is not None:
                    self._outer.forget(page)
                    page.destroy()
            except tk.TclError:
                pass
        self._paint_outer()
        self._show(self._workspace.current)
        self._say("profile", "log.profile.closed", name=name)

    def _profile_language(self) -> str | None:
        """The language the active profile asks for — or English, said out loud.

        A profile carries a language code, and it may have been written on a machine
        that had `de.json` when this one does not. The panel must not follow it into a
        language it cannot render, and must not go quiet about why: English, and a line
        naming the missing file. Nothing is rewritten, so the profile's choice comes
        back by itself once the locale is put back (panel/runtime/host.py does the same
        for the language a window opens with).
        """
        lang = self._settings.get("language")
        if lang and not self._i18n.known(lang):
            self._say("panel", "log.lang.unknown", lang=lang,
                      used=i18nmod.DEFAULT_LANG)
            return i18nmod.DEFAULT_LANG
        return lang

    def _reload_active_profile(self) -> None:
        """Re-apply language, all UI values, and monitor state from self._settings."""
        lang = self._profile_language()
        if lang and lang != self._i18n.lang and self._i18n.set_lang(lang):
            self._apply_language()
        self._apply_settings_to_ui()
        self._open_panel_log()                # the mirror follows the active profile
        self._configure_debug_log()           # …and so does the debug log
        self._dbg.info("active profile is now %r", self._profiles.active)
        self._rebind_daemon()                 # …and so does the client it drives
        self._sync_monitors()                 # restart captures into the new profile's logs

    def _error_text(self, exc: Exception) -> str:
        """A refusal in the person's language when it named itself, its own words if not.

        The profile store is UI-agnostic and raises `ValueError`; what it raises carries
        a locale key (`panel/i18n.Message`), because «profile already exists: main» in a
        Russian panel is the message not being translated at all. Anything else — an
        `OSError` from the filesystem, say — is shown as it came.
        """
        return i18nmod.translated(self._t, exc)

    def _create_profile(self) -> None:
        """Ask for a name — and for the login of the session its client will live in.

        THE ONLY THING TYPED IS THE LOGIN (#1252). A profile is an account and an
        account is a client of its own, which is a Windows session plus a daemon port
        (`panel/runtime/provision.py`). Of those two the panel can work the port out for
        itself and cannot possibly guess the login, so it asks for exactly that and
        decides the rest.

        It used to ask for the name and nothing else, and seed the new profile with a
        copy of the CURRENT one's settings — including its port. Five profiles made that
        way all named 47654, all drove the console session's client, and all farmed one
        account while the panel reported four healthy profiles (#1250).
        """
        asked = self._ask_new_profile()
        if asked is None:
            return
        name, login = asked
        try:
            created = self._profiles.create(name)
        except ValueError as exc:
            messagebox.showerror(self._t("profile.new.title"), self._error_text(exc),
                                 parent=self._profile_dialog_parent())
            return
        # Seed the new profile with the current settings so it starts from a sane state —
        # then give it a client of its OWN, which is the one part of a seed that must
        # never be a copy.
        self._profiles.save(self._collect_settings(), created)
        try:
            plan = runtime.provision.provision(self._profiles, created, login=login)
        except ValueError as exc:
            # The port hunt is the only thing here that can still refuse, and a profile
            # left half-made is worse than none: undo the directory and say why.
            self._profiles.delete(created)
            messagebox.showerror(self._t("profile.new.title"), self._error_text(exc),
                                 parent=self._profile_dialog_parent())
            return
        self._say_client(created, plan)
        self._refresh_profile_combo(select=created)
        self._switch_profile(created)
        if not plan.console:
            self._offer_bring_up(created, plan)

    def _offer_bring_up(self, name: str, plan) -> None:
        """A profile whose client is in a session of its own: raise that session now?

        Asked rather than done, because it is an RDP logon, a launcher that may decide to
        update and a daemon waiting for the client to finish loading — minutes, and the
        person may be creating four profiles in a row. Saying no leaves «Поднять сессию»
        on the «Игра» page, which is the same call.
        """
        session = self._workspace.get(name)
        rt = getattr(session, "rt", None)
        if rt is None:
            return
        if not messagebox.askyesno(self._t("profile.new.title"),
                                   self._t("profile.new.bring_up", user=plan.user),
                                   parent=self._profile_dialog_parent()):
            return
        rt.say("session", "log.session.bringing_up", user=plan.user)

        def work() -> None:
            try:
                code = runtime.game_process.bring_up(
                    rt.settings, say=lambda msg: rt.put(f"[session] {msg}"))
            except Exception as exc:      # noqa: BLE001 — a line in the log, not a crash
                rt.say("session", "log.session.up_failed", error=exc)
                return
            rt.say("session", "log.session.up_ok" if code == 0
                   else "log.session.up_partial", code=code)

        threading.Thread(target=work, name="panel-session-up", daemon=True).start()

    # -- one profile, one client (#1252) ------------------------------------
    #
    # A profile is an account and an account is a client of its own: a Windows session
    # plus a daemon port (`panel/runtime/provision.py`). Creating one settles both, so a
    # panel that has only ever made profiles the new way cannot get into the state below.
    # What is here is for the profiles that predate that — five of them on this machine,
    # all silently on the console session's port, all farming one account (#1250).
    #
    # THE TWO HALVES ARE FIXED DIFFERENTLY, and the split is the whole design:
    #
    # * a port that two DIFFERENT clients both claim is put right unasked, at boot,
    #   before a single session is built. Nothing about the profile changes except a
    #   number nobody was supposed to see;
    # * two profiles on ONE client cannot be separated without knowing the login of the
    #   Windows session the second one's client should live in, and that is the one thing
    #   no amount of reading can answer. So the boot SAYS it and names where it is
    #   answered — never a modal on the way up, because the hourly autostart opens this
    #   panel with nobody at the machine and a question there is a panel that never
    #   finishes starting.
    #
    # WHERE IT IS ANSWERED IS THE PROFILE'S OWN SETTINGS PAGE (#1263). It used to be a
    # «Развести клиенты…» button in the «Профиль» window that asked a login for each
    # shared profile at once and wrote the answers to disk with `provision.provision`.
    # Under a profile that is OPEN that write does not survive: its widgets still hold
    # the old port and login, and `_collect_settings` puts them back on the next save —
    # including the save this window does while closing. The person did it, was told it
    # had worked, and nothing had changed. So the login is now typed on «Настройки» →
    # «Игра» → «Сессия Windows» of the profile it belongs to, where setting the bound
    # variable is what persists it and re-points the link.

    def _sort_out_clients(self, profiles) -> list:
        """Give every client its own port, and note what still needs a person.

        Returns the lines to say once there is a log to say them into — this runs before
        the workspace exists, which is the point: a session reads its port while it is
        being built.
        """
        notes = []
        self._boot_profiles = profiles
        try:
            moved = runtime.provision.repair_ports(profiles)
            stranded = runtime.provision.needs_own_client(profiles)
        except Exception:                    # noqa: BLE001 — a boot, not a repair job
            return notes
        for name, old, new in moved:
            notes.append(("log.profile.port_moved",
                          {"name": name, "old": old, "new": new}))
        if stranded:
            # …and where a person answers it. The path, not a button: the answer is one
            # login per profile, typed on the profile it belongs to (#1263).
            notes.append(("log.profile.client_shared_boot",
                          {"names": ", ".join(stranded),
                           "tab": self._t_boot("tab.settings"),
                           "page": self._t_boot("settings.tab.game"),
                           "frame": self._t_boot("session.frame")}))
        return notes

    def _t_boot(self, key: str) -> str:
        """Translate before there is a session to translate with.

        `self._t` is the SHOWING session's translator and nothing is showing yet. This
        builds one off the profile the panel is about to open, with `persist=False` so a
        boot-time lookup cannot rename the machine's language.
        """
        cached = getattr(self, "_boot_i18n", None)
        if cached is None:
            lang = None
            try:
                lang = getattr(self, "_boot_profiles").load().get("language")
            except Exception:                # noqa: BLE001
                lang = None
            cached = self._boot_i18n = runtime.Translator(lang, persist=False)
        return cached.t(key)

    # `_separate_clients` and `_ask_client_logins` stood here until #1263. They asked a
    # login for every shared profile in one modal and wrote the answers with
    # `provision.provision` — straight into the files, under profiles that were open.
    # An open profile's client is not in its file, it is in the Tk variables its
    # Settings page is bound to, and `_collect_settings` writes those back on the next
    # save — including the one this window makes while closing. So the fix landed, said
    # so in the log, and was gone by the next morning. It is done per profile now, on
    # «Настройки» → «Игра» → «Сессия Windows», through that profile's own binder.

    def _say_client(self, name: str, plan) -> None:
        """One line naming the client a profile was given — which desktop, which port."""
        if plan.console:
            self._say("profile", "log.profile.client.console", name=name,
                      port=plan.port)
        else:
            self._say("profile", "log.profile.client.session", name=name,
                      user=plan.user, port=plan.port)

    def _ask_new_profile(self):
        """The create dialog: a name, and a login when the console is already taken.

        Returns ``(name, login)`` — ``login`` empty for the console — or ``None`` if the
        person closed it. The two fields are in ONE window on purpose: which of them is
        needed depends on what the other profiles already hold, and a person answering
        two chained boxes cannot see why the second appeared.
        """
        owner = runtime.provision.console_owner(self._profiles)
        win = tk.Toplevel(self)
        win.title(self._t("profile.new.title"))
        win.resizable(False, False)
        win.transient(self._profile_dialog_parent())

        frm = ttk.Frame(win)
        frm.pack(fill="both", expand=True, padx=16, pady=16)
        frm.columnconfigure(1, weight=1)

        name_var = tk.StringVar(master=win)
        self._tr(ttk.Label(frm), "profile.prompt_name").grid(row=0, column=0, sticky="w")
        name_entry = ttk.Entry(frm, textvariable=name_var, width=28)
        name_entry.grid(row=0, column=1, sticky="we", padx=(8, 0))

        login_var = tk.StringVar(master=win)
        if owner:
            self._tr(ttk.Label(frm), "profile.new.login").grid(row=1, column=0,
                                                              sticky="w", pady=(8, 0))
            ttk.Entry(frm, textvariable=login_var, width=28).grid(
                row=1, column=1, sticky="we", padx=(8, 0), pady=(8, 0))
            hint = self._t("profile.new.login_hint", owner=owner)
        else:
            hint = self._t("profile.new.console_hint")
        ttk.Label(frm, text=hint, foreground="#888", wraplength=360,
                  justify="left").grid(row=2, column=0, columnspan=2, sticky="w",
                                       pady=(10, 0))

        answer: list = []

        def ok() -> None:
            if not profilemod.sanitize(name_var.get()):
                return                       # an empty name is the one thing to re-ask
            if owner and not login_var.get().strip():
                return                       # …and so is a session with nobody in it
            answer.append((name_var.get(), login_var.get().strip()))
            win.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        self._tr(ttk.Button(btns, command=ok), "profile.new").pack(side="left")
        self._tr(ttk.Button(btns, command=win.destroy),
                 "profile.cancel").pack(side="left", padx=(8, 0))
        win.bind("<Return>", lambda e: ok())
        win.bind("<Escape>", lambda e: win.destroy())

        win.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - win.winfo_height()) // 3)
        win.geometry(f"+{x}+{y}")
        win.grab_set()
        name_entry.focus_set()
        self.wait_window(win)
        return answer[0] if answer else None

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
            messagebox.showerror(self._t("profile.rename"), self._error_text(exc),
                                 parent=self._profile_dialog_parent())
            return
        self._refresh_profile_combo(select=newn)
        # The directory moved under the schedule's feet: re-point both files, or
        # the next run would write into a re-created old directory.
        self._schedule.on_profile_switch()
        # The hourly autostart names no profile since #1207 — it opens ONE panel with
        # whatever set the panel itself saved, and that set already knows the new name.
        # This only sweeps away a per-profile task from #1203, if the machine still has
        # one (panel/runtime/autostart.py).
        autostartmod.rename(cur, newn)
        self._say("profile", "log.profile.renamed", old=cur, new=newn)

    def _delete_profile(self) -> None:
        """Delete a profile: its page, its session, and everything that session held.

        THE PAGE WAS THE PART THAT NEVER WENT (#1253). This method predates the window
        holding more than one profile (#1206): it deleted the directory and then
        *re-pointed the one runtime*, which is what a panel with a single profile used
        to need. With a workspace, nothing told the workspace — so the page stayed in
        the notebook, its schedule went on firing errands, its captures went on writing,
        it went on holding the game lease, and the profile came back in the list the
        moment anything asked for its directory (`ProfileManager._ensure_dir` makes one).

        The delete did not even reach the disk, and could not have. `self._profiles` is
        the SHOWING SESSION's pinned manager, so the shared `panel/settings.json` was
        never re-pointed and the next launch reopened the profile; and the `rmtree` ran
        while that same session had `panel.log` and `debug.log` open, which on Windows is
        a directory that cannot be removed — reported as success, because the store
        ignored the errors (now it does not).

        So the order below is the whole fix, and every step is load-bearing:

        1. refuse early — the last profile on disk, and a delete with no page to fall
           back to, are both refusals with words rather than half-done work;
        2. keep a page: if this is the only one open, open another profile FIRST, since
           a window with no page in it is a window with nothing in it;
        3. stop the daemon, while the link that can still reach it is alive — but only
           if no other profile drives that client;
        4. close the session — errands, listeners, captures, children, the game lease,
           the instance lock and both log files, then the page out of the notebook;
        5. and only then the directory, through the WORKSPACE's unpinned manager, which
           is the one allowed to write which profiles are open and which is showing.
        """
        profiles = self._workspace.profiles          # the unpinned one — see step 5
        name = profilemod.sanitize(self._profile_var.get() or "")
        if not name or not profiles.exists(name):
            name = self._workspace.current.name
        if len(profiles.list()) <= 1:
            messagebox.showerror(self._t("profile.delete"),
                                 self._t("profile.error.last_one"),
                                 parent=self._profile_dialog_parent())
            return
        # The confirmation names the whole directory, because the delete is an `rmtree`
        # of it — the chat history, the rally log, panel.log and the record of when
        # every timer last ran. Built by hand rather than through `profiles.dir()`,
        # which CREATES the directory it names: a question about deleting something
        # must not be the thing that brings it back.
        path = os.path.join(profilemod.PROFILES_DIR, name)
        if not messagebox.askyesno(
                self._t("profile.delete"),
                self._t("profile.confirm_delete", name=name, path=_repo_rel(path)),
                parent=self._profile_dialog_parent()):
            return
        if name in self._workspace and not self._make_room_to_delete(name):
            return

        note = None
        with self._activity.step("activity.profile.delete", name=name):
            if name in self._workspace:
                # Worked out while the link is alive, SAID once the page is gone: a line
                # about the daemon put into the log of the profile being deleted is a
                # line written into a file that is about to be removed.
                note = self._stop_daemon_of(name)
                self._close_profile(name)
            if note is not None:
                self._say("profile", note[0], **note[1])
            try:
                now_active = profiles.delete(name)
            except ValueError as exc:
                said = self._error_text(exc)
                messagebox.showerror(self._t("profile.delete"), said,
                                     parent=self._profile_dialog_parent())
                self._say("profile", "log.profile.delete_failed", name=name, error=said)
                self._refresh_profile_combo()
                return
        # A per-profile task from #1203 goes with it — the one hourly task of #1207 stays,
        # because the panel it opens is still wanted; it simply has one page fewer now.
        left = autostartmod.drop_legacy(name)
        if left:
            self._say("profile", "log.autostart.leftover", name=name,
                      error=", ".join(left))
        self._refresh_profile_combo(select=self._workspace.current.name)
        self._say("profile", "log.profile.deleted", name=name, active=now_active)

    def _make_room_to_delete(self, name: str) -> bool:
        """Make sure a page will be left once ``name``'s is gone. ``False`` = refuse.

        `Workspace.close` will not close the last open session and is right not to. So
        the profile that is about to go stops being the only one open: another is opened
        beside it first, and the delete carries on from there. When there is no other
        that this window may open — every one of them held by a second panel — the
        honest answer is to say so and delete nothing.
        """
        if len(self._workspace) > 1:
            return True
        other = next((n for n in self._workspace.profiles.list()
                      if n != name and self._profile_is_free(n)), None)
        if other is None:
            messagebox.showerror(self._t("profile.delete"),
                                 self._t("profile.error.no_replacement", name=name),
                                 parent=self._profile_dialog_parent())
            return False
        self._open_profile(other)
        return len(self._workspace) > 1

    def _stop_daemon_of(self, name: str):
        """Ask this profile's daemon to exit — nothing will ever ask it for anything again.

        A daemon deliberately outlives the panel (docs/research/multi-profile-panel.md
        §4.2), because a profile CLOSED is a profile that will be opened again. A profile
        DELETED is not: leaving its daemon up leaves a process holding a client, a game
        lease and a port that `panel/runtime/provision.py` will then step around for ever.

        Unless somebody else is on that port. Two profiles on one client is a state
        installs made before #1252 are still in, and shutting the daemon down from under
        the other one would take its game with it.

        Fire-and-forget on a thread: the shutdown is an RPC to a process that answers and
        then exits, and the person is waiting on a modal. Nothing in the profile
        directory depends on it — the daemon's own log lives elsewhere — so the delete
        below does not have to wait for it.

        Returns ``(key, fmt)`` for the caller to say once the page is gone, or ``None``.
        """
        session = self._workspace.get(name)
        rt = getattr(session, "rt", None)
        if rt is None:
            return None
        port = rt.daemon_port()
        others = runtime.provision.clients(self._workspace.profiles, exclude=name)
        sharing = sorted(n for n, client in others.items() if client.port == port)
        if sharing:
            return ("log.profile.daemon_kept",
                    {"port": port, "others": ", ".join(sharing)})
        if not rt.game.up():
            return None
        client = rt.game.client

        def work() -> None:
            try:
                client.shutdown()
            except Exception:                # noqa: BLE001 — a daemon, not the window
                pass

        threading.Thread(target=work, name="panel-daemon-stop", daemon=True).start()
        return ("log.profile.daemon_stopped", {"port": port})

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
            # The Scenarios tab used to forget all three on every restart, so a
            # launch always started on the first row with an empty args box.
            "log_filter": self._log_filter_var.get(),
            "window_geometry": self._current_geometry(),
            "window_zoomed": self._is_zoomed(),
            "log_sash": self._current_sash(),
            # The «Командный пункт» tab: the shared-mission robbery rule and the
            # treasure page's digging squad, a block per page.
            # The schedule is NOT here: a timer's switch and period live in the
            # profile's own timers.json beside its scenario, and when each last
            # ran in timers_last_run.json (see panel/timers.py).
        }
        # Settings page -> «Общие» / «Игра». One loop, so adding a knob is adding a
        # line to SETTINGS_DEFAULTS and a widget bound to `_opt_vars[key]`.
        #
        # …except the ones the MACHINE answers (#1252). Where the game is installed and
        # which Python drives the children are not this profile's opinions, and writing
        # them into a profile is how one carried `C:\Program Files\LastWar\…` — a folder
        # the game has never installed itself into — for long enough that «Запустить
        # игру» silently stopped working. Not written here means an old one drops out of
        # the file on the next save, and `runtime.settings.MACHINE_KEYS` means it is not
        # obeyed in the meantime.
        for key in SETTINGS_DEFAULTS:
            if key in runtime.settings.MACHINE_KEYS:
                continue
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
        # Every tab this build OFFERS THIS PROFILE. A tab that is in here and not in
        # `enabled` was switched off ON PURPOSE; without the record it would be
        # indistinguishable from one that did not exist yet, and would come back on the
        # next start.
        #
        # Which is why a tab still being written does not go in while it is hidden
        # (#1273): it was never offered, so recording it as offered-and-declined would
        # be the one lie that keeps it away for ever — the day its mark comes off, the
        # rule above would read it as a tab this profile had already said no to.
        was_known = set(block.get("known") or ())
        offered = {spec.id for spec in tabsreg.listed(
            enabled=block.get("enabled"), known=block.get("known"))}
        block["known"] = [spec.id for spec in tabsreg.TABS
                          if spec.id in offered or spec.id in was_known]
        config = dict(block.get("config") or {})
        for tab in getattr(self, "_plugin_tabs", {}).values():
            # `stored_config`, not `config`: a tab nobody has opened has no widgets to
            # read and hands back the block it was given instead of a screenful of
            # defaults (`PanelTab.LAZY`, #1215).
            config[tab.ID] = tab.stored_config()
        block["config"] = config
        return block

    def _apply_settings_to_ui(self) -> None:
        """Push self._settings into the widgets without triggering auto-save."""
        s = self._settings
        self._loading = True
        try:
            self._log_filter_var.set(s.get("log_filter") or LOG_FILTER_ALL)
            for key, default in SETTINGS_DEFAULTS.items():
                var = self._opt_vars.get(key)
                if var is not None:
                    # A machine-answered key shows what the machine answered, never what
                    # the profile happens to still carry (#1252) — the file's value is
                    # already ignored by every reader, and a Settings page showing a
                    # stale path beside a panel that is not using it is worse than no
                    # page at all.
                    var.set(default if key in runtime.settings.MACHINE_KEYS
                            else s.get(key, default))
            # Each plugin tab restores its own block — the new `tabs.config.<id>` if the
            # profile has one, else the flat keys it used to be spelled with. Whatever a
            # restored value has to re-draw (a rule hint, a status line) the tab does at
            # the end of its own `apply_config`: the shell does not know what its
            # widgets are, and a line here naming one of them is a crash waiting for the
            # release that moves it.
            for tab in getattr(self, "_plugin_tabs", {}).values():
                # `restore`, not `apply_config`: an undrawn tab keeps the block until it
                # is drawn and then applies it, so a profile restored into a page nobody
                # has opened is not lost (`PanelTab.LAZY`, #1215).
                tab.restore(
                    self._binder.tab_config(tab.ID, type(tab).LEGACY_KEYS))
        finally:
            self._loading = False
            # A whole profile has just landed in the widgets. The traces have kept the
            # background-readable shadow in step all the way through, but this is the
            # one moment worth being certain about — everything a worker reads (the
            # port, the session, the executable) has just changed at once (#1226).
            self._binder.refresh_live()

    def _install_autosave(self) -> None:
        """Persist to the active profile whenever any bound setting changes."""
        for var in (self._log_filter_var,):
            var.trace_add("write", lambda *a: self._save_settings())
        # Every plugin tab's own settings, traced from here like any other bound
        # setting, so a tab stays free of the profile machinery.
        #
        # THE DRAWN ONES NOW, THE REST AS THEY ARE DRAWN. A `LAZY` tab makes its
        # variables when somebody first looks at it (#1215), and a variable made after
        # this ran would be untraced — the box would tick and nothing would be written.
        # So the registry says when it draws one, and that tab is traced then.
        self._rt.tabs.on_realized = self._bound(self._on_tab_realized)
        for owner in self._rt.tabs.drawn:
            self._trace_tab(owner)
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
        #
        # THE DRAWN ONES. A tab nobody has opened has nothing pointed at the old profile
        # — no widgets, no child, no read — and it is handed the new profile's block
        # anyway (`_apply_settings_to_ui`), so it comes up as that account's the first
        # time somebody looks at it (#1215).
        for tab in getattr(self, "_plugin_tabs", {}).values():
            if tab.built:
                tab.on_profile_switch()
        # The schedule belongs to the account: its errands, their switches and periods,
        # the clock that says when each last ran, and the listeners a switch must not
        # leave watching on the previous profile's behalf. The Timers tab, if this
        # profile has one, redraws its rows from its own `on_profile_switch`.
        self._schedule.on_profile_switch()

    # `_update_path_hints` went with the rally monitor: the one label showing a
    # profile's log path is that tab's own now, and it refreshes itself on a language
    # switch and on `on_profile_switch`.

    # -- UI -----------------------------------------------------------------
    def _build_ui(self, parent=None, staged: bool = False, done=None) -> None:
        """Draw one profile's page: its notebook, «Главная», the log, and its tabs.

        THE ORDER IS DELIBERATE (#1208). The shell's own half — the status strip, the
        control blocks, the log pane, the command line — is built first and costs
        milliseconds; the fifteen plugin tabs, which cost a second and a half between
        them, follow one per turn of the event loop when ``staged``. So a profile being
        opened shows a page one can already read and use while the rest of it fills in,
        instead of a white rectangle and a window that answers nothing.
        """
        # The selected timer row has to be visible: a checkbox has no "selected"
        # look of its own, and the four editor buttons act on whichever row that
        # is. Give that row a bold "Selected.TCheckbutton" style; every other row
        # keeps the stock "TCheckbutton" (see _paint_timer_selection).
        ttk.Style(self).configure("Selected.TCheckbutton", font=ui_font(weight="bold"))
        # Into this profile's PAGE, not into the window: the window holds the outer
        # notebook and one page per open profile (#1206).
        nb = ttk.Notebook(parent if parent is not None else self)
        nb.pack(fill="both", expand=True)
        main = ttk.Frame(nb)
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
        # `LW_PANEL_BARE=1` takes «Главная» out of the notebook as well as out of the
        # page — the tab itself, not only what is drawn under it. With every plugin tab
        # switched off too the notebook is then empty, which is the floor of a
        # bisection: a window with a profile strip, a status row and nothing else.
        bare = bool(os.environ.get("LW_PANEL_BARE"))
        entries = [] if bare else [("main", main, "tab.main", 0)]
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

        # THE PLUGIN TABS (panel/tabs/) are built AFTER everything below — see the
        # docstring. The dictionary is made here because a step of the staged build
        # fills it in, and because `_apply_settings_to_ui` and `_install_autosave`
        # already read it through `getattr(..., {})` while it is still empty.
        self._plugin_tabs: dict = {}
        # The «Сценарии» tab's `TAP` reference drops its choice into the DSL command
        # line, which lives here on «Главная» — so it asks rather than reaching (§7).
        self._rt.bus.subscribe("cmd.reference", lambda _p: self._show_button_reference())


        top = ttk.Frame(main, padding=8)
        top.pack(fill="x")
        self._tr(ttk.Label(top), "top.game").pack(side="left")
        self._status_var = tk.StringVar(value=self._t("status.checking"))
        self._status_lbl = ttk.Label(top, textvariable=self._status_var, foreground="#888")
        self._status_lbl.pack(side="left", padx=6)
        # The self-restart, beside the state that causes it. The phone draws the same
        # three numbers on its «Состояние» card (`panel/web/static/app.js`), out of the
        # same object — a client that is being restarted round and round must not look
        # like one that is simply working.
        self._recovery_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self._recovery_var,
                  foreground="#888").pack(side="left", padx=6)
        # The probe words its own answer (`panel/runtime/game_process.py` returns a
        # `Message`: the sentence and its locale key in one value), so the strip can be
        # re-said on a language change instead of sitting in the old one until the next
        # poll — and the poll is eight seconds away.
        self._status_msg = None
        self._hook(self._retranslate_status, "top-status")
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
        # …and the half that was missing (#1262): the same place, the other direction.
        # «Стоп всё» left a state nobody could see and nothing could undo but hand, from
        # one log line that scrolls away — which is how a stopped panel sat in front of
        # somebody for seven hours with a dead client behind it.
        self._resume_btn = self._tr(ttk.Button(top, command=self._resume),
                                    "panic.resume")
        self._resume_btn.pack(side="right", padx=(0, 6))
        # A MARK, not a log line: it stays until the profile is running again.
        self._panic_var = tk.StringVar(value="")
        self._panic_lbl = ttk.Label(top, textvariable=self._panic_var,
                                    foreground="#c33", font=ui_font(weight="bold"))
        self._panic_lbl.pack(side="right", padx=(0, 6))

        # A PAGE WITH NOTHING BELOW THIS LINE (`LW_PANEL_BARE=1`) — the floor of a
        # bisection. Switching a tab off takes that tab out of the page; this takes the
        # whole of «Главная» with it — the control blocks, the update block, the log
        # widget and the command line — leaving the profile strip, the row above (the
        # game and daemon indicators, which the status poll writes into every eight
        # seconds and which would raise without them) and the runtime behind the page:
        # the schedule, the wire listeners, the daemon, the poll itself. Whatever a
        # freeze still costs with this set is the shell's own; whatever it stops costing
        # belongs to what was removed. Off by default, never written into a profile —
        # a switch for one run rather than a setting.
        if bare:
            self._log = None                 # no widget; the lines still reach panel.log
            self._dbg.info("bare page: «Главная» is not in the notebook at all")
            self._stage(self._session(),
                        [functools.partial(self._finish_tabs, nb, frames, done)], staged)
            return

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
        # The client's whole life, from one table (panel/runtime/game_control.py): the
        # same three presses the phone draws, playing the same three scenarios, said in
        # the log with the same words. The phone's copy is `/api/state` → `game.controls`
        # and `/api/game`; keeping the pair in step is what that module is for.
        self._game_buttons = {}
        for control in gamectl.CONTROLS:
            button = self._tr(ttk.Button(game, command=self._presser(control)),
                              control.label)
            button.pack(side="left", padx=4, ipady=3)
            self._game_buttons[control.id] = button
        # Until the first probe answers (a second, at most eight), assume there is no
        # client: «Запустить» is the one press that is harmless when the belief is
        # wrong, and «Закрыть» the one that is not.
        self._paint_game_buttons(runtime.game_process.OFFLINE)
        self._tr(ttk.Label(game, foreground="#888"),
                 "game.launcher_hint").pack(side="left", padx=10)
        # The watchdog: the client is crash-prone (that is why launch_game exists),
        # and until now a crash was silent — the panel kept saying "running (pid …)"
        # while every timer tick failed into the retry hold. The same variable the
        # Settings → «Игра» tab shows, so the two switches are one switch.
        self._tr(ttk.Checkbutton(game, variable=self._opt_vars["watchdog"]),
                 "game.watchdog").pack(side="right")

        self._build_update_block(main)

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

        # …and now the tabs themselves, a step each (see `_stage`). The last step is
        # what depends on all of them having been built.
        session = self._session()
        # THE ORDER THEY ARE FILLED IN IS NOT THE ORDER THEY SIT IN. The pages went into
        # the notebook above in the profile's order and stay there; «Настройки» collects
        # a page from every tab that has one, so it is built last whatever its place on
        # the strip (`tabsreg.build_order`, #1237).
        steps = [functools.partial(self._build_one_tab, spec, frames[spec.id])
                 for spec in tabsreg.build_order(specs)]
        steps.append(functools.partial(self._finish_tabs, nb, frames, done))
        self._stage(session, steps, staged)

    def _build_one_tab(self, spec, frame) -> None:
        """One plugin tab: made, registered, and named on the strip while it is.

        MADE, not necessarily DRAWN (#1215). A `LAZY` tab — every tab that has no reason
        otherwise — is constructed here and handed its saved block, and its widgets wait
        for the first person to look at it. What is left in this step is a class import
        and an `__init__`: a page of fifteen tabs used to spend between one and a half
        and eight seconds here, all of it on tabs nobody had asked to see.

        BEFORE the Settings page is drawn, because a tab contributes its own page to it
        (§6) and the aggregator can only draw the tabs that exist by then. That is what
        `tabsreg.build_order` above is for — «settings» sits at order 40 and would
        otherwise be filled third, with «Ралли» and its «Авторалли» page still nine
        tabs away (#1237).
        """
        with self._rt.activity.step("activity.tab.build",
                                    tab=self._t(spec.title_key)):
            tab = self._build_plugin_tab(spec, frame)
        if tab is None:
            return
        self._plugin_tabs[spec.id] = tab
        self._rt.tabs.add(tab)
        # What the tab brought with it: its wire-driven errands (§3.2). A tab that is
        # not in this profile registers nothing, so its trigger is not offered and no
        # listener is spawned for it.
        self._schedule.register(tab)
        # The Timers tab IS the switches while it is here: the schedule asks the rows,
        # and falls back to the saved catalogue when it is not.
        if tab.ID == "timers":
            self._schedule.timer_config_source = tab._timer_widget_config
            self._schedule.trigger_config_source = tab._trigger_widget_config

    def _finish_tabs(self, nb, frames: dict, done=None) -> None:
        """Everything about the tabs that can only be done once they are all there."""
        # The account summary strip goes into the «Аккаунты» tab, beside the list of
        # characters it summarises. It is packed when that tab is DRAWN and not before
        # (`_on_tab_realized`), for the reason it was here: it has to sit under the
        # list, and a strip packed into a frame the tab has not filled yet sits above
        # it. Until then the poller keeps reading — `_render_dashboard` finds no widget
        # and simply holds the numbers.
        # Lazily loaded on first show, by the frame the notebook reports as selected.
        self._lazy_tabs = {str(frames[tab_id]): tab
                           for tab_id, tab in self._plugin_tabs.items()}
        # BOUND: with several profiles open this fires for a page that may not be the
        # one showing (a tab clicked, then a profile switched before the event is
        # drained), and it acts on `self._main_nb` — which would be the wrong page's.
        nb.bind("<<NotebookTabChanged>>", self._bound(self._on_main_tab_changed))
        # EVERY EAGER TAB, NOW THAT THEY EXIST. `_startup` also walks them, but it runs
        # on a thread of its own that is started while these are still being built one
        # event-loop turn at a time — so a tab built after that walk was silently never
        # loaded. It cost the «Веб» tab its whole point: the panel came up, the profile
        # said the remote control was on, and nothing was listening until somebody
        # clicked the tab (#1221). `ensure_loaded` is idempotent by contract, so the two
        # walks cost nothing where they overlap.
        #
        # AND DRAWN FIRST: what an EAGER tab starts asks its own checkbox whether it is
        # switched on, so «load at boot» has to mean «exists at boot» too (#1215).
        for tab in self._plugin_tabs.values():
            if not tab.EAGER:
                continue
            try:
                self._rt.tabs.realize(tab)
                tab.ensure_loaded()
            except Exception:                # noqa: BLE001 — one tab, not the window
                self._dbg.error("eager load of %r failed", tab.ID, exc_info=True)
        if done is not None:
            done()

    def _build_plugin_tab(self, spec, frame):
        """Build one registry tab into ``frame``. ``None`` if it could not be built.

        A tab that raises used to take the boot with it — `_build_ui` was one straight
        line of fourteen constructions. Now the panel opens without it and says so.
        """
        try:
            cls = spec.load()
            self._binder.register(cls.SETTINGS)
            tab = cls(self._rt, frame)
            # The block first, whether or not the widgets follow now: a tab that is
            # never opened hands this same block back when the profile is saved
            # (`PanelTab.stored_config`), and a tab that IS opened has it applied as
            # part of being drawn (`PanelTab.realize`).
            tab.restore(self._binder.tab_config(cls.ID, cls.LEGACY_KEYS))
            if not cls.LAZY:
                self._rt.tabs.realize(tab)
            return tab
        except Exception as exc:                 # noqa: BLE001
            self._dbg.error("tab %r failed to build", spec.id, exc_info=True)
            self._say("panel", "log.tab.failed", tab=spec.id, error=exc)
            return None

    def _on_tab_realized(self, tab) -> None:
        """A tab has just been drawn — do to it what only a drawn tab can be done to.

        The one hook the container has on `PanelTab.LAZY` (#1215). A tab is drawn the
        first time somebody looks at it, which may be an hour after its page was made,
        and two things have to happen at that moment rather than at the page's:

        * its variables are traced, so ticking a box it has just made is still written
          to the profile;
        * «Аккаунты» gets the account strip packed under its list — it is the shell's
          own widget in that tab's frame, and it can only go under a list that exists.
        """
        try:
            self._trace_tab(tab)
            if tab.ID == "accounts":
                self._build_dashboard(tab.parent)
        except Exception:                    # noqa: BLE001 — one tab, not the window
            self._dbg.error("wiring up %r after it was drawn failed", tab.ID,
                            exc_info=True)

    def _trace_tab(self, tab) -> None:
        """Save the profile whenever one of this tab's own variables changes."""
        for var in tab.persist_vars():
            var.trace_add("write", lambda *a: self._save_settings())

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
        self._rt.dbg("dashboard").info("poller started")
        threading.Thread(target=self._bound(self._dash_loop), args=(self._dash_stop,),
                         daemon=True).start()

    def _stop_dashboard(self) -> None:
        stop, self._dash_stop = self._dash_stop, None
        if stop is not None:
            stop.set()
            self._rt.dbg("dashboard").info("poller stopped")

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
                    self._rt.dbg("dashboard").warning(
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
        running, _text = self._game_status()
        if not running:
            return
        with self._rt.activity.step("activity.dashboard"):
            # `early`: the chunk logs its whole answer in one line and the daemon holds
            # its lock for the length of the call, so sitting out the rest of the settle
            # is the strip making a press wait on it (#1230, #1232).
            lines = self._client.run(dashmod.build_chunk(), marker=dashmod.MARKER,
                                     settle=dashmod.SETTLE, early=True)
        values = dashmod.parse(lines, debug=self._rt.dbg("dashboard"))
        self._dash_err = ""
        self._dash_values = values
        self._later(0, self._render_dashboard)

    def _refresh_dashboard(self) -> None:
        """The ↻ beside the strip — one read, now, off the Tk thread."""
        def work() -> None:
            try:
                self._dash_tick()
            except Exception as exc:      # noqa: BLE001
                self._say("dash", "log.dash.unreadable", error=exc)
        threading.Thread(target=self._bound(work), daemon=True).start()

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
        dbgmod.configure(self._profiles.debug_log(), scope=self._rt.scope)

    def _stall_report(self, text: str) -> None:
        """One recorded freeze, from the sampler's thread. stderr and the debug log.

        Deliberately NOT the log widget and not `say`: writing a stall report onto the
        Tk thread would queue work behind the very freeze it describes, and a person
        watching the panel is not who this is for.
        """
        print(text, file=sys.stderr, flush=True)
        dbg = getattr(self, "_dbg", None)
        if dbg is not None:
            try:
                dbg.warning("%s", text)
            except Exception:            # noqa: BLE001 — a diagnostic, never the panel
                pass

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


    def _dbg_status(self, game_ok: bool, daemon_warm: bool, link=None) -> None:
        """Record a systems snapshot: DEBUG every poll, INFO only when it changes.

        ``link`` is the server connection as `panel/runtime/game_process.py` found it,
        and it is here for the morning after: «game=up» all night with «link=lost» from
        03:41 is the difference between a panel that was lying and a client that was.

        Runs on the Tk thread (the status poll's after-callback), so it can read the
        timer/trigger checkbuttons safely. This is the "statuses of systems" stream —
        daemon, game, how many timers/triggers are armed, and whether the dashboard
        poll is up or complaining.

        The counts come from the schedule, not from the rows: the rows belong to the
        «Таймеры» tab and are not here when the profile switches it off, whereas the
        schedule answers either way — off the widgets while they exist, off the saved
        catalogue when they do not. That is the same reading the schedule fires on.
        """
        dbg = getattr(self, "_dbg", None)
        if dbg is None:
            return
        try:
            timers_on = sum(1 for row in self._schedule.timer_config().values()
                            if row.get("enabled"))
            triggers_on = sum(1 for on in self._schedule.trigger_config().values() if on)
        except (tk.TclError, AttributeError):
            timers_on = triggers_on = -1
        dash = "err" if self._dash_err else ("on" if self._dash_stop else "off")
        snap = (bool(game_ok), str(link or ""), bool(daemon_warm), timers_on,
                triggers_on, dash)
        msg = ("systems: game=%s link=%s daemon=%s timers_on=%s triggers_on=%s "
               "dashboard=%s"
               % ("up" if game_ok else "down", link or "?",
                  "warm" if daemon_warm else "down", timers_on, triggers_on, dash))
        if snap != self._dbg_status_prev:
            self._dbg_status_prev = snap
            dbg.info(msg)
        else:
            dbg.debug(msg)

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
        if self._log is None:            # a page built without one (`LW_PANEL_BARE`)
            return
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
        """Make this widget's coordinate links clickable (panel/widgets.py owns them).

        Shared by the log and the chat views, which is why the mechanics are in
        `widgets` and only "where a click goes" is here.
        """
        widgets.bind_coord_links(widget, self._on_coord_click)

    def _insert_coord_link(self, widget, text: str) -> None:
        widgets.insert_coord_link(widget, text)

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
        #
        # ON THE TK THREAD, and each one guarded. `ensure_loaded` reads the tab's own
        # widgets (the rally monitor asks its own checkbox whether it is switched on),
        # and this runs on the boot thread — while the main thread is pumping `update()`
        # in `_await_boot` with gaps between the pumps. A Tk read landing in one of
        # those gaps raises «main thread is not in main loop»: a race that was always
        # here (thirty-six of them in one profile's debug log) and that TWO boot threads
        # made reliable. It cost the whole rest of this method — the schedule included,
        # so the panel came up with no timers running at all and said nothing.
        for tab in getattr(self, "_plugin_tabs", {}).values():
            if not tab.EAGER:
                continue
            try:
                # Drawn on the Tk thread first, for the same reason the load is handed
                # there: widgets are made nowhere else, and what an EAGER tab starts
                # reads its own checkbox (#1215).
                self._on_tk(lambda t=tab: (self._rt.tabs.realize(t), t.ensure_loaded()))
            except Exception:            # noqa: BLE001 — one tab, not the whole boot
                self._dbg.error("eager load of %r failed", tab.ID, exc_info=True)
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
        """(Re)arm the repeating callback ``name`` — cancelling any pending one.

        BOUND: the ticker is this profile's, and so is what the callback will touch
        when it fires — which may well be while another profile's page is showing.
        Binding here covers every self-rearming loop in the file at once, which is
        exactly why they all go through this method (#1206).
        """
        self._tick.arm(name, delay_ms, self._bound(func))

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
            "log_lines": self._log_lines,
            "log_kept": len(self._log_kept),
            "links": widgets.coord_link_count(),
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
            self._later(0, lambda: self._set_daemon(self._t(key), ok))
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
            kicked = False
            stale = False
            try:
                found = self._game_probe()
                warm = self._daemon_up()
                # IS THE DAEMON ON THE CLIENT THAT IS RUNNING? One loopback round trip,
                # on THIS thread because it is a socket. Two pids, compared — the fault
                # that cost six pointless client restarts is a fact, not an inference
                # (#1268, panel/runtime/recovery.py).
                stale = self._daemon_stale(found, warm)
                # HAS THE ACCOUNT BEEN TAKEN? Asked whatever the sockets say, because a
                # kick can sit behind a link that reads `online` — one surviving
                # conversation out of six — and while this was asked only on a lost link
                # the one flag that knew was never consulted for two and a quarter hours
                # (#1270, docs/research/server-link-status.md §5.3). On THIS thread: it
                # is a round trip into the game VM.
                kicked = self._read_kicked(found, warm)
            finally:
                self._status_busy = False
            ok = found.running
            self._later(0, lambda: (
                self._set_status_msg(found.message),
                self._status_lbl.configure(
                    foreground=LINK_COLOURS.get(found.link, "#888")),
                self._set_daemon(self._t("daemon.warm") if warm else self._t("daemon.none"), warm),
                self._dbg_status(ok, warm, found.link),
                self._paint_game_buttons(found.link),
                self._announce_link(found),
                self._recovery_check(found, kicked, stale),
                self._paint_panic(),
                self._watchdog_check(ok)))
        threading.Thread(target=self._bound(work), daemon=True).start()

    def _announce_link(self, found) -> None:
        """Say it in the log the moment the server connection goes, and when it returns.

        The strip is only true while somebody is looking at it, and this is the state
        nobody looks for: the client is up, the daemon is warm, every errand reports
        success, and the account has been doing nothing since some hour of the night.
        A line in the log is what puts a time on it afterwards.

        Only the edges are said — a lost link would otherwise repeat every eight seconds
        until morning — and the loss only after WATCHDOG_STRIKES consecutive readings of
        it, the same patience the crash gets and for the same reason: a client that is
        reconnecting has, for a moment, exactly the sockets of one that has given up.
        The recovery is said only after a loss was announced, so an ordinary start-up
        does not announce a connection nobody watched go.
        """
        gp = runtime.game_process
        if found.link != gp.LOST:
            # …and only ONLINE is a recovery. A client that was killed and relaunched
            # goes LOST → OFFLINE → ONLINE, and «клиент снова на связи» is the
            # watchdog's line to say about that, not this one's.
            if self._link_gone >= WATCHDOG_STRIKES and found.link == gp.ONLINE:
                self._say("game", "log.game.link_back")
            self._link_gone = 0
            return
        self._link_gone += 1
        if self._link_gone == WATCHDOG_STRIKES:
            self._say("game", "log.game.link_lost")

    def _set_status_msg(self, msg) -> None:
        """Show the probe's answer, in the panel's language, and keep it for a re-say."""
        self._status_msg = msg
        self._status_var.set(i18nmod.translated(self._t, msg))

    def _retranslate_status(self) -> None:
        if getattr(self, "_status_msg", None) is not None:
            self._status_var.set(i18nmod.translated(self._t, self._status_msg))

    def _daemon_stale(self, found, warm: bool) -> bool:
        """Is this profile's daemon holding a client that is not the one running?

        The positive half of #1268, and it is two integers rather than a diagnosis: the
        pid `{"op":"ping"}` names against the pid the probe just found. Anything missing
        — no daemon, no client, a daemon that will not say — is ``False``, because the
        cure is a restart and «I could not tell» is never a reason for one (the rule
        `panel/runtime/recovery.py` already keeps for `unknown` link readings).

        Runs on the status thread: it is a socket, and `attached_pid` guards itself with
        `up()` so a profile whose daemon is down pays nothing for asking.
        """
        if not warm or not found.running or not found.pid:
            return False
        held = self._rt.game.attached_pid()
        if not held:
            # A warm daemon that names NO client while one is running is the same fault
            # wearing a different answer — it never attached, or it let go — and the
            # same restart fixes it. But it is also what a daemon says in the seconds
            # after a client is replaced, which is exactly what DAEMON_STRIKES is for.
            return True
        return int(held) != int(found.pid)

    def _recovery_check(self, found, kicked: bool = False,
                        stale: bool = False) -> None:
        """Restart a client the server has stopped hearing — the other half of a crash.

        The watchdog below notices the PROCESS going away. This notices the account
        going away underneath a process that is still drawing: a server that hung up on
        an idle client, or a session kicked because the account logged in on another
        device. From outside they are one state (`link == lost`) and they have one cure.

        Everything that makes it safe to leave on overnight — a run of readings rather
        than one, `unknown` never counting, a cooldown between restarts — is in
        `panel/runtime/recovery.py` and pinned by `tests/test_panel_recovery.py`. What
        is here is the wiring: the same `watchdog` switch as the crash half (from the
        person's side it is one promise, and a dead client and a deaf one are the same
        thing to whoever is not looking), the log line, and the press.

        Nothing pauses the schedule for this, because the schedule pauses itself: with
        the client down `Schedule.gate` holds every errand except the recovery one and
        says so, and lifts on its own when the client is back (#1259).
        """
        now = time.time()
        self._paint_recovery(self._rt.recovery.state(now))
        # THE DAEMON FIRST. It is asked on every poll, not only on a lost link, because
        # its fault is true while the link is perfectly ONLINE — which is the shape it
        # had live, and the reason a decision hung off `link == lost` would never have
        # been asked at all (#1268).
        self._act_on(self._rt.recovery.note_daemon(stale, now))
        # «Is somebody at the machine» — the gate that stops this closing a window
        # a person is playing in, which it did once (#1259).
        self._act_on(self._rt.recovery.note(found.link, now,
                                            idle_sec=game_link.idle_sec(),
                                            kicked=kicked))

    def _act_on(self, said) -> None:
        """Say what the recovery decided, and do it. One door for both decisions.

        ASK THE SETS, never a constant. `ACT_KICK` was added beside `ACT` and the panel
        went on testing `key == ACT`, so a kicked client was told it was being restarted
        and never was (#1259). There are four acts now and two cures, and the only way
        that stays true as a fifth arrives is for the wiring to ask which set the key is
        in rather than to enumerate keys.
        """
        if said is None:
            return
        key, fmt = said
        if key in runtime.recovery.SAYINGS:
            # A reading, not a cure. It is said whatever the watchdog switch is set to:
            # somebody who has turned the automatic restart OFF is exactly the person
            # who has to be told that their errands are pressing nothing, since nothing
            # is going to act on it for them.
            self._say("game", key, **fmt)
            return
        if not self._opt_bool("watchdog"):
            return
        self._say("game", key, **fmt)
        if key in runtime.recovery.RESTARTS:
            self._rt.play_async("restart_game")
        elif key in runtime.recovery.DAEMON_RESTARTS:
            # THE SAME METHOD THE «⭮» BUTTON PRESSES, deliberately — the cure already
            # existed beside the daemon indicator and only the decision to reach for it
            # was missing. A second one here would be a second thing to keep in step,
            # and the first draft of this actually wrote one: a duplicate `def` that
            # silently overrode the button's.
            self._restart_daemon()

    def _read_kicked(self, found, warm: bool) -> bool:
        """Is the client showing the game's own «вход с другого устройства» modal?

        ASKED WHATEVER THE SOCKETS SAY (#1270). It used to be asked only while the link
        already read `lost`, on the reasoning that a healthy client would always answer
        the same — and a kick that leaves one conversation standing reads `online`,
        `dead=0`, which is precisely the answer that reasoning assumed could not happen.
        The account was taken at ~04:38 on 2026-08-07 and the flag was never once
        consulted until a person looked at 07:27.

        A worker-thread read, and a forgiving one: any failure leaves the last answer
        standing, so this can only ever ADD a reason and never take one away. What is
        read, and why it is the modal's TEXT rather than «is a dialog open», is
        `tools/lib/game_kick.py` — the reading had to become conclusive on its own
        before it could be trusted against a healthy-looking link.

        Only ever through a WARM daemon, and only with a client to ask: `evaluator()`
        would otherwise build a local `LuaEval`, which costs seconds and an attach, on a
        status poll that runs every eight seconds for ever.
        """
        if not warm or not getattr(found, "running", False):
            self._kick_at, self._kick_was = 0.0, False
            return False
        now = time.time()
        # Every poll while it matters — a lost link, or a kick already on screen — and
        # otherwise on the throttle. The previous answer is what fills the gaps: the
        # recovery counts CONSECUTIVE readings, and a throttle that reported «no kick»
        # in between would keep resetting the run it exists to feed.
        due = (found.link == runtime.game_process.LOST or self._kick_was
               or (now - self._kick_at) >= KICK_POLL_SEC)
        if not due:
            return self._kick_was
        try:
            import game_kick

            said = game_kick.read(self._rt.game.evaluator(),
                                  link_lost=found.link == runtime.game_process.LOST)
        except Exception:                    # noqa: BLE001 — a reading, never the fault
            said = None
        self._kick_at = now
        if said is not None:                 # `None` is «could not tell» — keep the last
            self._kick_was = said
        return self._kick_was

    def _paint_recovery(self, st: dict) -> None:
        """Say the restart bookkeeping on the strip — and nothing at all while it is idle."""
        why = st.get("held_by") or ""
        if why == "player":
            # «Не перезапускается» must never be unexplained: this one is deliberate,
            # and it is the reason a person at the machine keeps their session (#1259).
            text = self._t("status.recovery.player")
        elif why == "daemon_cooldown":
            text = self._t("status.recovery.daemon_wait",
                           mins=int(st.get("daemon_cooldown_left", 0) // 60) + 1)
        elif st.get("blame") == "daemon":
            # WHAT is being restarted, not just that something is. A person watching the
            # strip during the six pointless restarts had no way to learn that the panel
            # was reaching for the wrong thing (#1268).
            text = self._t("status.recovery.daemon",
                           n=st.get("daemon_stale", 0),
                           of=st.get("daemon_strikes", 0),
                           done=st.get("daemon_restarts", 0))
        elif st.get("fruitless"):
            # The evidence, while it is still evidence: two restarts spent with the link
            # never back means the panel is about to change its mind about the diagnosis.
            text = self._t("status.recovery.fruitless", n=st["fruitless"])
        elif st.get("barren", 0) >= st.get("barren_of", 0) > 0:
            # «Успешно ничего»: errands running and pressing nothing. Not a fault on its
            # own — a spent account presses nothing all evening — which is why it is
            # drawn rather than acted on (#1270).
            text = self._t("status.recovery.barren", n=st["barren"])
        elif why == "cooldown" or st.get("cooldown_left"):
            text = self._t("status.recovery.wait",
                           mins=int(st.get("cooldown_left", 0) // 60) + 1)
        elif st.get("deaf_for"):
            text = self._t("status.recovery.deaf", n=st["deaf_for"], of=st.get("strikes", 0))
        elif st.get("restarts"):
            text = self._t("status.recovery.done", n=st["restarts"])
        else:
            text = ""
        self._recovery_var.set(text)

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
        # A client of another session is put back too, and by the same recipe: it
        # starts the launcher inside the session the profile names (#1218). It used to
        # be refused here, because what the recipe did then was spawn a process on THIS
        # desktop — a third client nobody asked for, while the account that had died
        # stayed dead all night, which is the one case an overnight watchdog exists for.
        since = time.time() - self._watchdog_last
        if since < WATCHDOG_COOLDOWN_SEC:
            self._say("game", "log.game.watchdog_hold", mins=int(since // 60))
            return
        self._watchdog_last = time.time()
        self._say("game", "log.game.watchdog_relaunch")
        self._rt.play_async("launch_game")

    # -- «Обновление»: is this checkout still the current one? ---------------
    #
    # There is no release channel: the bot IS the git checkout it runs from, and updating
    # it used to mean remembering to open a terminal and type `git pull` — which is why a
    # box could sit weeks behind `origin` with nobody noticing. The block below is the
    # whole feature's face: which commit this is, whether `origin` has moved, and one
    # button when (and only when) a fast-forward is safe.
    #
    # Everything it decides lives in panel/runtime/updates.py — this half draws the
    # answer and keeps the two buttons in step with it. The three states an operator
    # actually has to act on are spelled out rather than reduced to a red dot: a dirty
    # tree, a diverged branch and no route to `origin` all look like "не обновляется"
    # from the outside and want three different things done about them.
    def _build_update_block(self, parent) -> None:
        upd = self._tr(ttk.LabelFrame(parent, padding=8), "update.frame")
        upd.pack(fill="x", padx=8, pady=(0, 6))
        self._update_state = None          # the last UpdateState, for a retranslation
        self._update_busy = False          # a check or a pull is in flight
        self._update_ready = False         # a pull succeeded: the panel is stale code

        self._update_version_var = tk.StringVar(value=self._t("update.version",
                                                              version=APP_VERSION))
        ttk.Label(upd, textvariable=self._update_version_var,
                  font=ui_font(weight="bold")).pack(side="left")
        self._update_status_var = tk.StringVar(value=self._t("update.st.idle"))
        self._update_status_lbl = ttk.Label(upd, textvariable=self._update_status_var,
                                            foreground="#888")
        self._update_status_lbl.pack(side="left", padx=8)

        # Right to left, so the pair that appears and disappears sits at the edge and
        # «Проверить» does not move under the cursor when it does.
        self._update_check_btn = self._tr(
            ttk.Button(upd, command=lambda: self._check_updates(manual=True)),
            "update.check")
        self._update_check_btn.pack(side="right")
        # ALWAYS THERE, and this is the block it belongs in: what it restarts the panel
        # FOR is the code the block is about — a pull that has landed, and just as often
        # an edit made on this machine, which no check will ever report. It used to
        # appear only after a successful pull, so the one press that applies a change to
        # the running panel was hidden behind the one path that had not been taken
        # (#1258). The phone draws the same press on «Состояние» out of the same table.
        self._update_restart_btn = self._tr(
            ttk.Button(upd, command=self._restart_panel),
            panelctl.BY_ID[panelctl.RESTART].label)
        self._update_restart_btn.pack(side="right", padx=(0, 6))
        # «Обновить» still comes and goes: nothing has been checked yet, so it has
        # nothing to offer. `pack`/`pack_forget` rather than `state=disabled` — a button
        # that is never pressable is noise, and the label already says why.
        self._update_pull_btn = self._tr(
            ttk.Button(upd, command=self._do_update), "update.pull")
        # A language switch has to re-render both dynamic labels; `tr` only knows the
        # static ones, and the state they are formatted from is not a locale key.
        self._hook(self._paint_update, key="update-block")

    def _check_updates(self, manual: bool = False) -> None:
        """Ask `origin` whether this checkout has fallen behind. Off the Tk thread.

        `manual` is the ↻ press: it says so in the log even when the answer is "всё
        актуально", which the periodic check keeps to itself.
        """
        if self._update_busy:
            return          # a fetch is already out; the ↻ press has nothing to add
        self._update_busy = True
        self._update_status_var.set(self._t("update.st.checking"))
        self._update_status_lbl.configure(foreground="#888")

        def work() -> None:
            handle = self._activity.begin("activity.update.check")
            try:
                state = runtime.updates.check()
            except Exception as exc:       # noqa: BLE001 — a broken probe is a label,
                state = runtime.updates.UpdateState(   # not a dead panel
                    runtime.updates.ERROR, detail=str(exc))
            finally:
                self._activity.end(handle)
                self._update_busy = False
            self._later(0, lambda: self._show_update_state(state, manual))
        threading.Thread(target=self._bound(work), daemon=True).start()

    def _poll_updates(self) -> None:
        """The periodic check, re-arming itself (see UPDATE_POLL_MS)."""
        self._check_updates()
        self._arm("updates", UPDATE_POLL_MS, self._poll_updates)

    def _show_update_state(self, state, manual: bool = False) -> None:
        """A fresh reading landed: repaint the block and log what is worth logging."""
        prev = self._update_state
        self._update_state = state
        self._paint_update()
        upd = runtime.updates
        # A conclusion is logged when it CHANGES, plus always on a manual press. The
        # periodic check would otherwise write the same line four times a day.
        if not manual and prev is not None and prev.state == state.state:
            return
        if state.state == upd.BEHIND:
            self._say("panel", "log.update.behind", branch=state.branch,
                      behind=state.behind, remote=state.remote)
        elif state.state == upd.CURRENT and manual:
            self._say("panel", "log.update.current", local=state.local)
        elif state.state == upd.OFFLINE:
            # NOT in the log unless the operator asked. An origin that cannot be reached
            # is nothing they can act on — a home connection that was not up yet when the
            # panel started says it every start — and git's own words for it («Permission
            # denied (publickey)», «Could not resolve host») read as something broke. The
            # block on «Главная» already shows the state, and the debug log keeps the
            # detail for whoever is looking for it.
            self._dbg.info("update check offline: %s", state.detail)
            if manual:
                self._say("panel", "log.update.offline", detail=state.detail)
        elif state.state == upd.ERROR:
            self._say("panel", "log.update.error", detail=state.detail)
        elif state.state == upd.DIVERGED:
            self._say("panel", "log.update.diverged", branch=state.branch,
                      ahead=state.ahead, behind=state.behind)
        elif manual:
            self._say("panel", "log.update.state", state=state.state)

    def _paint_update(self) -> None:
        """Draw the block from `self._update_state` — also the language-switch hook."""
        state = self._update_state
        if getattr(self, "_update_version_var", None) is None:
            return
        upd = runtime.updates
        # Whatever the LAST READING said, never a fresh one: this runs on the Tk thread
        # — off a language switch as well as off a check — and `head()` is a subprocess.
        # Until the first check lands the label is just the version, which is true.
        local = state.local if state is not None else ""
        branch = state.branch if state is not None else ""
        if local and branch:
            self._update_version_var.set(self._t("update.version.branch",
                                                 version=APP_VERSION,
                                                 branch=branch, local=local))
        elif local:
            self._update_version_var.set(self._t("update.version.commit",
                                                 version=APP_VERSION, local=local))
        else:
            self._update_version_var.set(self._t("update.version",
                                                 version=APP_VERSION))

        if self._update_ready:
            # A pull has already landed. Nothing else the block could say matters until
            # the panel is running the code that is now on disk — and the button that
            # does that is beside this line whether or not anything was pulled.
            self._update_status_var.set(self._t("update.st.updated", local=local))
            self._update_status_lbl.configure(foreground="#3c3")
            self._update_pull_btn.pack_forget()
            return
        if state is None:
            self._update_status_var.set(self._t("update.st.idle"))
            self._update_status_lbl.configure(foreground="#888")
            self._update_pull_btn.pack_forget()
            return

        # Behind AND dirty is the one combination that needs two facts in one line: the
        # update exists, and it is the operator's own uncommitted work that is holding
        # it — not a failure of anything the panel does.
        key = ("update.st.behind_dirty" if state.state == upd.BEHIND and state.dirty
               else f"update.st.{state.state}")
        self._update_status_var.set(self._t(
            key, branch=state.branch, local=state.local, remote=state.remote,
            behind=state.behind, ahead=state.ahead, detail=state.detail))
        self._update_status_lbl.configure(
            foreground=UPDATE_COLOURS.get(state.state, "#888"))
        if state.can_pull:
            self._update_pull_btn.pack(side="right", padx=(0, 6))
        else:
            self._update_pull_btn.pack_forget()

    def _do_update(self) -> None:
        """«Обновить» — confirm, fast-forward, and report. The pull is off the Tk thread."""
        state = self._update_state
        if self._update_busy or state is None or not state.can_pull:
            return
        if not messagebox.askyesno(
                self._t("update.confirm.title"),
                self._t("update.confirm.body", branch=state.branch,
                        behind=state.behind, remote=state.remote), parent=self):
            return
        self._update_busy = True
        self._update_status_var.set(self._t("update.st.pulling"))
        self._update_status_lbl.configure(foreground="#888")
        self._update_pull_btn.pack_forget()
        self._say("panel", "log.update.pulling", branch=state.branch,
                  remote=state.remote)
        before = state.local

        def work() -> None:
            handle = self._activity.begin("activity.update.pull")
            try:
                res = runtime.updates.pull()
            except Exception as exc:       # noqa: BLE001
                res = runtime.updates.PullResult(runtime.updates.FAIL_ERROR,
                                                 detail=str(exc))
            finally:
                self._activity.end(handle)
                self._update_busy = False
            self._later(0, lambda: self._show_pull_result(res, before))
        threading.Thread(target=self._bound(work), daemon=True).start()

    def _show_pull_result(self, res, before: str) -> None:
        """What the pull did — in the log, in the block, and (on success) in a dialog."""
        upd = runtime.updates
        self._update_state = res.state
        if res.ok:
            # The files on disk are no longer the code in this interpreter. Say so
            # loudly: a panel left running on the old modules is exactly the state
            # where "я же обновил" and "не работает" meet.
            self._update_ready = True
            self._paint_update()
            local = res.state.local if res.state is not None else ""
            self._say("panel", "log.update.done", before=before, local=local)
            messagebox.showinfo(self._t("update.done.title"),
                                self._t("update.done.body", before=before, local=local),
                                parent=self)
            return

        self._paint_update()
        if res.reason == upd.FAIL_DIRTY:
            self._say("panel", "log.update.fail_dirty")
            messagebox.showwarning(self._t("update.fail.title"),
                                   self._t("update.fail.dirty"), parent=self)
        elif res.reason == upd.FAIL_DIVERGED:
            self._say("panel", "log.update.fail_diverged")
            messagebox.showwarning(self._t("update.fail.title"),
                                   self._t("update.fail.diverged"), parent=self)
        elif res.reason == upd.FAIL_OVERWRITE:
            files = ", ".join(res.files[:8]) or res.detail
            self._say("panel", "log.update.fail_overwrite", files=files)
            messagebox.showwarning(self._t("update.fail.title"),
                                   self._t("update.fail.overwrite", files=files),
                                   parent=self)
        elif res.reason == upd.FAIL_OFFLINE:
            self._say("panel", "log.update.fail_offline", detail=res.detail)
            messagebox.showwarning(self._t("update.fail.title"),
                                   self._t("update.fail.offline", detail=res.detail),
                                   parent=self)
        elif res.reason == upd.FAIL_NOTHING:
            self._say("panel", "log.update.current", local=res.state.local
                      if res.state is not None else "")
        else:
            self._say("panel", "log.update.fail_error", detail=res.detail)
            messagebox.showerror(self._t("update.fail.title"),
                                 self._t("update.fail.error", detail=res.detail),
                                 parent=self)

    def _restart_panel(self) -> None:
        """«Перезапустить панель» — the window's half of the press (#1258).

        The question, the word on the button and the line in the log are the table's
        (`panel/runtime/panel_control.py`), because the phone asks the very same question
        out of the very same key before landing in the very same `_restart_now`. What is
        this method's own is only HOW the question is asked: a message box here, a
        browser dialog there.
        """
        control = panelctl.BY_ID[panelctl.RESTART]
        if not messagebox.askyesno(self._t("panel.restart.title"),
                                   self._t(control.confirm), parent=self):
            return
        panelctl.request(self._rt, control.id)

    def _restart_now(self) -> None:
        """Close this panel properly and start a fresh one. The question was already put.

        Registered with `panel/runtime/panel_control.py` while the window is being
        built, which is how a press from a phone reaches it — and why there is no
        confirmation here: whichever front-end asked has asked already.

        In this order, and it matters: `_on_close` is what writes the profiles out and
        stops the tabs' children, and a replacement started before that would read a
        settings file the old window has not finished with. It is also what makes the
        new panel come up the way this one was left — every open profile, the same
        pages. The daemon is deliberately NOT touched: it is a separate process holding
        a warm Lua VM, and the new panel picks up the same one.
        """
        self._activity.begin("activity.panel.restart")   # ended by the process ending
        try:
            self._on_close()
        except Exception:                  # noqa: BLE001 — a tab that fails to shut
            self._dbg.error("restart shutdown failed", exc_info=True)   # down must not
        try:                                                    # strand the operator
            runtime.updates.relaunch()
        except Exception as exc:           # noqa: BLE001
            self._dbg.error("relaunch failed: %s", exc)
            print(f"relaunch failed: {exc}", file=sys.stderr)

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

        EVERY open profile, not the one being looked at. It is the emergency button:
        the moment you want it is the moment you do not want to find out that the other
        account carried on pressing.
        """
        self._workspace.each(self._panic_session)

    def _panic_session(self, session) -> None:
        with self._on(session):
            self._say("panel", "panic.log")
            # …and each plugin tab stops whatever it holds — one loop, so a tab added
            # later cannot be the one «Стоп всё» quietly does not reach. A tab nobody
            # has opened holds nothing: it was never drawn and never loaded, so there is
            # nothing in it to stop (#1215).
            for tab in getattr(self, "_plugin_tabs", {}).values():
                if tab.built:
                    tab.panic()
            self._schedule.stop()
            # …and then whatever is STILL running, whoever started it. Each tab has just
            # stopped what it holds, but «Стоп всё» is pressed when something has gone
            # wrong, and that is precisely when a child nobody is holding any more is
            # the one still sniffing (#1212).
            stopped = self._rt.children.stop_all()
            if stopped:
                self._say("panel", "log.children.stopped", count=stopped)
            # Nothing is being done any more, so nothing may be left saying it is: a
            # step whose thread was asked to stop mid-way would otherwise sit on the
            # bottom strip for the rest of the session.
            self._rt.activity.clear()
            self._rt.panic.mark(time.time())
            self._paint_panic()
            self._say("panel", "panic.done")

    def _resume(self) -> None:
        """«Включить обратно» — put back exactly what «Стоп всё» switched off.

        Every open profile, like its opposite: the emergency button stops them all, so
        the one that brings them back has to reach all of them or half the machine stays
        held with nothing on screen to say which half.
        """
        self._workspace.each(self._resume_session)

    def _resume_session(self, session) -> None:
        with self._on(session):
            # Each tab puts back what IT switched off, and only what was on — the tab
            # owns the switch, so the tab is the only place that snapshot can live
            # without drifting from it (panel/runtime/panic.py). An undrawn tab was not
            # asked to stop anything, so there is nothing of its to put back.
            for tab in getattr(self, "_plugin_tabs", {}).values():
                if tab.built:
                    tab.resume()
            self._rt.panic.clear()
            self._paint_panic()
            self._say("panel", "panic.resumed")

    def _paint_panic(self) -> None:
        """The mark, and the button that only exists while there is something to undo."""
        st = self._rt.panic.state(time.time())
        if st["stopped"]:
            self._panic_var.set(self._t("panic.mark", mins=st["for_sec"] // 60))
            self._resume_btn.pack(side="right", padx=(0, 6))
        else:
            self._panic_var.set("")
            self._resume_btn.pack_forget()

    # -- one way to run a child ---------------------------------------------
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
    # -- the Develop sniffers are a tab now (panel/tabs/develop.py) ----------
    #
    # Both halves, the readiness watch, the graceful stop that unwraps the tracer's
    # hooks and the keep-or-throw-away prompt went with it. It is `DEFAULT_ENABLED =
    # False`: a panel whose owner has never reverse-engineered anything does not carry
    # it at all, which a menu entry could not express. The «Сценарии» tab's list,
    # editor, runner and repeat loop joined it in the same file (task #1240) — writing
    # and fixing an `actions/*.md` recipe is «working on the bot» too.

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
                self._later(400, self._refresh_status)

        threading.Thread(target=self._bound(work), daemon=True).start()

    # -- game lifecycle -----------------------------------------------------
    #
    # Both buttons used to refuse a profile whose client lives in another Windows
    # session, and the refusal was right for as long as it lasted: what the recipes did
    # was spawn a launcher on THIS desktop and terminate a process this account owns —
    # a third client in front of whoever is at the keyboard, and a kill that silently
    # did nothing. #1218 moved both ends into the recipes (`START_GAME`, and `QUIT_GAME`
    # carrying the session), so neither button needs a guard any more: they play the
    # same scenario for every profile and the scenario knows where the client is.
    # Every one of the three plays a recipe and does nothing else, which is CLAUDE.md's
    # rule and, for the restart, was a bug fix rather than tidying: what stood here was
    # `taskkill /F /IM LastWar.exe`, and `/IM` names an IMAGE. On a machine farming two
    # accounts — one client per Windows session — that closed BOTH, and the second
    # belonged to a profile nobody pressed anything for (#1205).
    #
    # The recipes end the client THIS profile drives (the process its own daemon is
    # attached to), wait for the base to be in play again, and re-point the game link at
    # the new process. A kill and a sleep could not do any of it: the link is bound to a
    # process id, so everything that read the game afterwards was reading a pid that no
    # longer existed. A second account's client is ended the same way as this one's, and
    # the only difference is who is allowed to — `TerminateProcess` on another account's
    # process comes back ACCESS_DENIED for an unelevated panel, so `QUIT_GAME` falls back
    # to one elevated taskkill BY PID, never by image name (#1218).
    #
    # `play_async` rather than `actions.play`, for the same reason «Запустить» on the
    # Scenarios tab uses it: it is the one place the claim, the worker thread and the log
    # line are spelled out together, so a restart cannot overlap a timer errand and a
    # 35-second run cannot freeze the window.
    def _presser(self, control):
        """The command behind one lifecycle button — asks first when the table says to."""
        return lambda: self._press_game(control)

    def _press_game(self, control) -> None:
        # The question is the table's, not this button's: the phone asks the very same
        # one, out of the same key, before the very same scenario. Closing a client and
        # replacing one are both a minute of an account's evening if they were a slip.
        if control.confirm and not messagebox.askyesno(
                self._t("game.frame"), self._t(control.confirm)):
            return
        gamectl.play(self._rt, control.id)

    def _paint_game_buttons(self, link: str) -> None:
        """Grey the presses that would mean nothing — off the SAME reading the phone gets.

        Runs on the Tk thread from the status poll, so «Закрыть игру» goes flat within
        eight seconds of the client going away and «Запустить игру» comes back at the
        same moment. Both front-ends decide this in `panel/runtime/game_control.py`, so
        a button the window greys is a button the phone greys.
        """
        for control in gamectl.CONTROLS:
            button = (getattr(self, "_game_buttons", None) or {}).get(control.id)
            if button is None:
                continue
            try:
                button.configure(state=("normal" if gamectl.available(control, link)
                                        else "disabled"))
            except tk.TclError:              # the page is going away under us
                return

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
                self._later(400, self._refresh_status)

        threading.Thread(target=self._bound(work), daemon=True).start()

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
        """Close the window — and with it EVERY open profile.

        Two halves on purpose. `_close_session` is what only the WINDOW knows about (a
        pending edit, the strip poller, the log mirror); `Workspace.shutdown` is what a
        session holds whether or not it was ever drawn (its tabs, its errands, its
        claim, its files) and is the same call a standalone tab makes. Both go through
        `each`, so a profile that throws on the way out cannot leave the others running
        behind a window that is gone.
        """
        if self._stall is not None:
            self._stall.stop()
        self._workspace.each(self._close_session)
        self._workspace.shutdown()
        self.destroy()

    def _close_session(self, session) -> None:
        """The window's half of letting one open profile go.

        Deliberately does NOT shut the tabs down or release the runtime: that is
        `ProfileSession.shutdown`, and doing it in both places would shut every tab
        down twice.
        """
        with self._on(session):
            # A debounced edit is still pending for up to a second — write it before
            # the window goes, or the last thing typed is the thing that is lost.
            self._save_settings()   # geometry and the sash, as the operator left them
            self._stop_dashboard()
            # Closed on purpose: take the heartbeat with it, so the hourly check reads
            # «not running» straight away instead of waiting for the beat to go stale.
            self._rt.stop_heartbeat()
            self._close_panel_log()
            # Every repeating callback goes with the page. One that fires into a
            # half-torn-down panel is a traceback nobody sees and a log line nobody
            # gets, because the log has just been closed above.
            self._disarm_all()
            self._dbg.info("panel closing — profile %r", session.name)

    # -- window geometry, remembered per profile -----------------------------
    def _is_zoomed(self) -> bool:
        """Is the window maximised right now?"""
        try:
            return self.state() == "zoomed"
        except tk.TclError:
            return False

    def _current_geometry(self) -> str:
        """Where the window is — the size it has when it is NOT maximised.

        `winfo_geometry` on a maximised window answers with the maximised rectangle,
        and on Windows that is a little TALLER than the space a window may use: the
        resize frame is invisible but counted. Restoring it as an ordinary window
        therefore hangs the last twenty pixels of the panel under the taskbar, where
        they cannot be seen — and the last thing on the panel is now the strip that
        says what it is doing (#1208), so the whole feature disappeared for anybody
        whose panel had been closed while maximised.

        A maximised window keeps the geometry it had before it was maximised, and
        `window_zoomed` remembers the state separately. Un-maximising then gives back a
        window the right size instead of one exactly the size of the screen.
        """
        try:
            if self._is_zoomed():
                return str(self._settings.get("window_geometry") or "")
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
        # …and maximise it again if that is how it was left. The state, never the
        # rectangle: the window manager knows how much room there actually is, and a
        # remembered maximised rectangle does not (see `_current_geometry`).
        if self._settings.get("window_zoomed"):
            try:
                self.state("zoomed")
            except tk.TclError:
                pass
        sash = self._settings.get("log_sash")
        try:
            sash = max(int(sash), 0)
        except (TypeError, ValueError):
            sash = 0
        self._later(200, lambda: self._apply_sash(sash))

    def _saved_sash(self) -> int:
        """Where this profile last left the log's sash (0 = «wherever the blocks end»)."""
        try:
            return max(int(self._settings.get("log_sash")), 0)
        except (TypeError, ValueError):
            return 0

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

        ONLY A DRAG IS DAMPED, and that is the whole of #1210. A size change that
        arrives on its own — maximise, restore, a geometry set from code, the reveal
        at boot, a page whose contents ask the window for a different size — used to
        switch painting off for a settle-time too, and a settle-time is exactly long
        enough for Tk to lay out and DRAW a page inside it. Tk draws a ttk widget once,
        at idle, and clears its own «needs redrawing» flag whether or not the pixels
        reached the glass; a page that was drawn into a window with its painting off is
        therefore blank until something invalidates it again — which is why a profile
        switched to for the first time showed empty «Игра» and «Обновление» blocks and
        stayed that way until the frame was dragged. So the first size change paints
        normally (it costs one repaint, and a drag never actually performs it — the
        next step arrives long before the message queue runs dry), and painting goes
        off only once a SECOND change arrives while the first is still settling, which
        no one-off resize ever produces.

        Windows only; elsewhere the damper is simply not installed.
        """
        self._resize_size = (self.winfo_width(), self.winfo_height())
        self._resize_job = None         # settle timer, while a resize is in flight
        self._resize_run = False        # …and «this size change has one behind it»
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
        self._paint_sizes = getattr(self, "_paint_sizes", []) + [size] if self._paint_off \
            else [size]
        # Order matters: the timer that puts painting back is armed even if
        # cancelling the old one goes wrong, because a window left with its
        # painting switched off and no timer to switch it back is a frozen panel.
        try:
            if self._resize_job is not None:
                self.after_cancel(self._resize_job)
        except (tk.TclError, ValueError):
            pass
        self._resize_job = self.after(RESIZE_SETTLE_MS, self._settle_resize)
        # THE SECOND STEP ONWARDS — see `_install_resize_damper`. One size change on its
        # own is not a drag, and damping it is what left a background page unpainted
        # (#1210); a drag has hardly begun by the time its second step arrives.
        if self._resize_run:
            self._suspend_painting()
        self._resize_run = True

    def _settle_resize(self) -> None:
        """The size has been still long enough — put the picture back up."""
        self._resize_job = None
        self._resize_run = False
        self._resume_painting()

    def _window_handle(self) -> int:
        # `getattr`, because the first page is SHOWN before the resize damper has been
        # installed — and the damper is where these two were being initialised. Asking
        # for a window handle that early used to be an AttributeError out of `_show`,
        # which is inside `__init__`: the panel died on boot with nothing in the log
        # (pythonw has no console to print the traceback to).
        if getattr(self, "_paint_hwnd", None) is None:
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
        self._paint_off_at = time.time()
        # A DEAD MAN'S HANDLE (#1211). The settle timer is the normal way back, and it
        # is one `after` among many: cancelled with a page, lost to a re-arm, delayed
        # behind a busy loop. A window whose painting stayed off is a window that has
        # frozen as far as anybody looking at it is concerned — the Tk thread answers,
        # the clicks land, and nothing on the glass moves. So a second timer, armed here
        # and never cancelled, puts the picture back whatever else happens.
        try:
            self.after(PAINT_OFF_MAX_MS, self._resume_painting)
        except (tk.TclError, RuntimeError):
            self._resume_painting()

    def _resume_painting(self) -> None:
        """Paint again, and repaint everything once — the window is out of date.

        `getattr`, because `_show` calls this before the damper has been installed: the
        first page is brought to the front from inside `__init__` (#1211).
        """
        if not getattr(self, "_paint_off", False):
            return
        self._paint_off = False
        hwnd = self._window_handle()
        try:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETREDRAW, 1, 0)
            ctypes.windll.user32.RedrawWindow(hwnd, None, None,
                                              RDW_REPAINT_ALL | RDW_UPDATENOW)
        except Exception:            # noqa: BLE001
            pass
        # A window that is not painting IS a frozen panel as far as anybody looking at
        # it is concerned, and it leaves no other trace — the Tk thread is answering
        # the whole time, so a stall sampler sees nothing (#1211). This is the trace.
        held = time.time() - getattr(self, "_paint_off_at", 0.0)
        dbg = getattr(self, "_dbg", None)
        if dbg is not None and held > 0.3:
            dbg.debug("window painted nothing for %d ms (resize damper, sizes %s)",
                      held * 1000, getattr(self, "_paint_sizes", [])[:6])

    def _repaint_page(self, page) -> None:
        """Repaint one profile's page, from its own frame down (#1210).

        A page that comes to the front is drawn by Tk once, at idle, and Tk then
        believes it is on the glass. Anything that swallowed those pixels — the damper
        above, a WM_PAINT that was queued while the window was busy, a page mapped
        while Windows had this window's painting off — leaves a page that is laid out
        correctly, answers the mouse, and shows blank blocks. Nothing in Tk repairs
        that on its own, because as far as Tk is concerned nothing is out of date; only
        an invalidation from the window manager makes it draw again, which is what this
        is. `RDW_ALLCHILDREN` takes the whole subtree, `RDW_UPDATENOW` paints it before
        this call returns rather than leaving a WM_PAINT for a quiet moment that may
        not come.

        Windows only, and never fatal: a page that cannot be invalidated is a page that
        draws whenever the window next tells it to, exactly as before.
        """
        if page is None or os.name != "nt":
            return
        try:
            hwnd = page.winfo_id()
        except (tk.TclError, RuntimeError):        # the page is going away
            return
        try:
            ctypes.windll.user32.RedrawWindow(hwnd, None, None,
                                              RDW_REPAINT_ALL | RDW_UPDATENOW)
        except Exception:            # noqa: BLE001 — a repaint is never worth a crash
            pass

    # -- scenarios tab (run .md action scripts) -----------------------------

    # -- the Scenarios tab is part of «Разработка» now (panel/tabs/develop.py, #1240) -
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
            if previous.built:               # an undrawn tab was never on screen
                previous.on_hide()
        tab = tabs.get(current)
        self._shown_tab = tab
        if tab is None:
            return
        # ALL THREE under one step: a tab shown for the first time is DRAWN here as well
        # as read (#1215), and both happen on the Tk thread — together they are the
        # longest freeze the panel has left in it. The strip is painted before any of it
        # starts (`_activity_changed` forces the redraw when it is reported from this
        # thread), so the window says which tab it has gone quiet for instead of merely
        # going quiet.
        with self._rt.activity.step("activity.tab.load",
                                    tab=self._t(type(tab).TITLE_KEY)):
            begun = time.perf_counter()
            self._rt.tabs.realize(tab)
            started = time.perf_counter()
            tab.ensure_loaded()
            loaded = time.perf_counter()
            tab.on_show()
        # The two of them separately: they are allowed to cost very different things
        # and the difference is the one the contract is about (§3).
        dbg = getattr(self, "_dbg", None)
        if dbg is not None:
            dbg.debug("tab %r shown: build %d ms, ensure_loaded %d ms, on_show %d ms",
                      tab.ID, (started - begun) * 1000, (loaded - started) * 1000,
                      (time.perf_counter() - loaded) * 1000)

    # -- «Настройки» is a plugin tab now (panel/tabs/settings.py) ------------
    #
    # It was already an aggregator — the shell's own knobs plus a page per tab that
    # brings one — so it moved as one. The knobs' DEFAULTS went to
    # panel/runtime/settings.py, which is what a page (and a standalone tab) reads
    # them from.

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

    # -- «Чат» is a plugin tab now (panel/tabs/chat.py) -----------------------
    #
    # The views, the DM pane, the emoji picker, the image cache, the reader child and
    # the per-character store went with it. A profile that does not list the tab now
    # starts no reader and opens no SQLite file — which is the whole reason a tab is
    # switchable at all.

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
    if _already_open(args.profile):
        return 0
    Panel(active_profile=args.profile).mainloop()
    return 0


def _already_open(profile: str | None) -> bool:
    """Is this profile open in another panel? Then say so and open nothing.

    ONE PANEL PER PROFILE — not one per machine. Two windows on two profiles is a way
    people work: a second account, or an instance of one's own inside an RDP session,
    and neither is touched by this. Two windows on the SAME profile is the one that
    breaks, quietly and later: both write that profile's `config.json` over each other
    and both drive its daemon.

    Before this, the second one opened, said one line into its own log, and left the
    person with two identical windows and no idea which was which.

    Said BEFORE anything is built — no window, no runtime, no daemon, no captures — and
    the window they already have is brought to the front, because that is what clicking
    a shortcut twice is asking for. In the profile's own language: there is no panel yet
    to ask, so the translator is built from what that profile saved.
    """
    profiles = profilemod.ProfileManager()
    name = profilemod.sanitize(profile or "") or profiles.active
    if not autostartmod.locked(profiles, name):
        return False

    say = i18nmod.I18n(profiles.load(name).get("language")).t
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(say("panel.busy.title"), say("panel.busy", profile=name))
    except Exception:                          # noqa: BLE001 — no display: the print stands
        print(say("panel.busy", profile=name), file=sys.stderr)
    finally:
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass
    autostartmod.focus_panel(profiles, name)
    return True


if __name__ == "__main__":
    raise SystemExit(main())
