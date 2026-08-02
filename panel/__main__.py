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
import glob
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
from . import timers as timersmod
from . import triggers as triggersmod
from . import rally_limits as rallylimitsmod
from . import resource_stats as resourcestatsmod
from . import chat_history as chathistmod
from . import tabs_extra as tabsextra
from . import secret_tasks as secrettasksmod
from . import command_post as commandpostmod

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

# The squads the panel offers for a rally. The game's own squad slots are read
# live where they matter (the formation whose `index` is the slot, see
# tools/lib/lua_actions.py); this is only how many the page draws.
RALLY_SQUADS = (1, 2, 3, 4)
# The elite-monster level a created rally may target.
RALLY_ELITE_MIN, RALLY_ELITE_MAX = 1, 35

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
# Marks a row that came out of actions/dev/ — experimental, shown only on request.
DEV_MARK = "⚙ "

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


def _action_titles(path: str, name: str) -> dict:
    """The title lines of one action script, by language.

    A script's first `#` line is its English title, which is why the picker read
    English while the rest of the UI was Russian. A script may now add a language
    tag to any of its leading comment lines —

        # Claim the alliance gifts — ordinary and premium
        # ru: Подарки альянса — обычные и премиальные

    — and the picker prefers the one matching the UI. Untagged is the fallback, so
    every existing script keeps working untouched and translating one is adding a
    line to it.
    """
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                s = raw.strip()
                if not s:
                    if out:
                        break             # the leading comment block is over
                    continue
                if not s.startswith("#"):
                    break
                body = s.lstrip("#").strip()
                if not body:
                    continue
                tag, sep, rest = body.partition(":")
                if sep and tag.strip().isalpha() and len(tag.strip()) == 2:
                    out.setdefault(tag.strip().lower(), rest.strip())
                else:
                    out.setdefault("", body)
    except OSError:
        pass
    if not out:
        out[""] = name
    return out


def list_actions(include_dev: bool = False, lang: str | None = None) -> list[dict]:
    """Enumerate the action scripts as ``{name, title, dev}``.

    The blessed ones (``actions/*.md``) always; ``actions/dev/*.md`` too when asked
    for. The dev folder is hidden by default so the picker offers only what works —
    but hiding it also hid `work_treasure` and `collect_trucks`, and reaching those
    used to be a code change rather than a checkbox.

    `title` is the script's own title line, in the UI's language when the script
    offers one (see :func:`_action_titles`), falling back to the untagged line and
    then to the bare file stem.
    """
    paths = sorted(glob.glob(os.path.join(ACTIONS_DIR, "*.md")))
    if include_dev:
        paths += sorted(glob.glob(os.path.join(ACTIONS_DIR, "dev", "*.md")))
    out = []
    for path in paths:
        name = os.path.splitext(os.path.basename(path))[0]
        if name in _HIDDEN_ACTIONS:
            continue
        titles = _action_titles(path, name)
        title = titles.get(lang or "") or titles.get("") or name
        out.append({"name": name, "title": title,
                    "dev": os.path.basename(os.path.dirname(path)) == "dev"})
    return out


_NON_GAME_PORTS = frozenset({80, 443})


def _server_connection(game_exe: str = GAME_EXE) -> str | None:
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
                if (p.info["name"] or "").lower() == game_exe.lower()}
        if not pids:
            return None
        for c in psutil.net_connections(kind="tcp"):
            if (c.pid in pids and c.raddr and c.status == "ESTABLISHED"
                    and c.raddr.port not in _NON_GAME_PORTS):
                return f"{c.raddr.ip}:{c.raddr.port}"
    except Exception:
        return None
    return None


def game_status(game_exe: str = GAME_EXE) -> tuple[bool, str]:
    """Whether the game is running, detected by process name only.

    Detection is deliberately independent of network state: the game is "found"
    whenever its process exists, regardless of VPN presence or whether a TCP
    connection to the game server is currently established. The connection state,
    when available, is appended as supplementary detail.

    ``game_exe`` is a parameter because the executable is a profile setting (a
    second client in its own Windows session, an install somewhere else); the
    default keeps every existing caller — and the tests — unchanged.

    Returns ``(running, label)``.
    """
    try:
        import psutil
    except Exception:
        return False, "psutil missing"

    pid = None
    try:
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() == game_exe.lower():
                pid = proc.pid
                break
    except Exception as exc:
        return False, f"probe error: {exc}"

    if pid is None:
        return False, "game not found"

    conn = _server_connection(game_exe)
    if conn:
        return True, f"running (pid {pid}) -> {conn}"
    return True, f"running (pid {pid})"


class Panel(tk.Tk):
    def __init__(self, active_profile: str | None = None) -> None:
        super().__init__()
        # Locale lookup AND the registry of what to re-render on a language switch
        # (panel/runtime/i18n.py). `_t` / `_tr` / `_hook` below are its three faces.
        self._i18n = runtime.Translator()
        # Repeating callbacks, one chain per name (panel/runtime/tick.py). Created
        # before anything can arm a loop, which is before the first widget is built.
        self._tick = runtime.Ticker(self)
        # Profiles: the active profile's config.json drives every panel setting.
        self._profiles = profilemod.ProfileManager()
        # An explicit --profile overrides the saved last-active profile, creating
        # it on the fly if it does not exist yet.
        if active_profile:
            self._profiles.set_active(active_profile)
        # The profile's values, its widget variables and the typed readers with their
        # bounds (panel/runtime/settings.py). `_settings` / `_loading` / `_opt_vars`
        # below stay as this file's names for the same three things.
        self._binder = runtime.SettingsBinder(self._profiles, SETTINGS_DEFAULTS)
        self._binder.load()
        self._binder.loading = True   # suppresses auto-save while we apply settings
        saved_lang = self._settings.get("language")
        if saved_lang:                # profile is the source of truth for language
            self._i18n.set_lang(saved_lang)
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
        self._logbus = runtime.LogBus(translate=self._t)
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
        self._mon_proc = None
        self._rally_proc = None
        # teamUuids already alerted on this session. A rally emits create AND
        # refresh events, so without this one стяг would ring four times.
        self._rally_seen: set = set()
        self._autoloot_proc = None    # one auto-loot run at a time
        self._autoloot_push_proc = None   # the event-driven share-push listener, when running
        self._autoloot_push_restart = None  # debounce handle for a range change mid-run
        self._autoloot_stop = None    # threading.Event of the watcher loop, when running
        self._autoloot_seen: set = set()   # uuids already sent this session (no re-tries)
        self._autoloot_pause_until = 0.0   # wall clock the watcher may fire again at
        self._autoloot_warned = False      # "no checkpoint yet" is said once per run
        self._ghost_proc = None       # one ghost-recon robbery at a time
        self._ghost_stop = None       # threading.Event of its watcher, when running
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
        # Scheduled actions (panel/timers.py). The store is per profile, so it is
        # re-pointed on a switch; the scheduler itself is created here and only
        # started once the UI exists (_startup), because a fired timer logs.
        self._timer_store = timersmod.LastRunStore(self._profiles.timers_state())
        # WHICH timers exist comes from the PROFILE's own timers.json — not from
        # code: one account's schedule is not the other's. A profile that has none
        # yet is seeded from the template panel/timers.json.
        self._timer_catalogue = timersmod.default_catalogue()
        self._timer_vars: dict[str, dict] = {}   # name -> {"enabled": Var, "interval": Var}
        self._timer_rows: dict[str, dict] = {}   # name -> {"last"/"next" Labels, "box"}
        # Which row the editor's Add/Copy/Edit/Delete act on. A grid of checkbuttons
        # has no selection of its own, so the row label doubles as one.
        self._timer_selected: str | None = None
        self._load_timer_catalogue()
        self._timers = timersmod.TimerScheduler(
            store=self._timer_store,
            catalogue=lambda: self._timer_catalogue,
            config=self._timer_config,
            runner=self._run_timer_action,
            log=lambda key, **fmt: self._log_put("[timer] " + self._t(key, **fmt)),
            gate=self._timer_gate,
        )
        # Wire-driven errands (panel/triggers.py) — their OWN catalogue and OWN file,
        # per profile, seeded from the template panel/triggers.json. A trigger has no
        # period; the watcher keeps a listener alive per switched-on trigger and, on a
        # matching push, hands the scenario to the scheduler's own queue (submit) so a
        # triggered press runs single-file with the scheduled timers.
        self._splash_step("splash.triggers", 0.35)
        self._trigger_catalogue = triggersmod.default_catalogue()
        self._trigger_vars: dict[str, tk.BooleanVar] = {}   # name -> enabled Var
        self._trigger_rows: dict[str, dict] = {}            # name -> {"status" Label}
        self._load_trigger_catalogue()
        self._triggers = triggersmod.TriggerWatcher(
            catalogue=lambda: self._trigger_catalogue,
            config=self._trigger_config,
            spawn=self._spawn_trigger_listener,
            submit=self._timers.submit,
            poll=self._poll_trigger,
            log=lambda key, **fmt: self._log_put("[trigger] " + self._t(key, **fmt)),
        )
        # The «resource_tracker» trigger's state: the day-keyed tally (per profile) and
        # the last balance seen, in memory, so a push's gain is `current - last`. The
        # last is empty until the first push establishes a baseline (no gain counted
        # then). Both re-pointed / cleared on a profile switch.
        self._resource_stats = resourcestatsmod.load_stats(
            self._profiles.resource_stats_json())
        self._resource_last: dict = {}
        # The Settings page's knobs, one Tk variable each, created BEFORE any tab is
        # built — the Settings tabs bind widgets to them and the main tab's watchdog
        # checkbox shares the very same variable, so the two can never disagree.
        self._binder.create_vars(self, _settings_var)
        # The daemon this profile drives. A profile naming a non-default port drives
        # the client of ANOTHER Windows session (tools/rdp_instance.py) — see
        # SETTINGS_DEFAULTS. Re-pointed by `_rebind_daemon` on a switch or an edit.
        # How every child process is launched (panel/runtime/children.py): the
        # interpreter, the environment — the daemon port and the game lease — and
        # where its output goes.
        self._children = runtime.ChildFactory(
            log=self._logbus, cwd=REPO, python=self._python,
            port=self._daemon_port, schedule=self.after)
        # The link to the game (panel/runtime/daemon.py): which daemon this profile
        # drives, whether it is up, and the one-action-at-a-time claim — the local
        # flag AND the daemon's lease, so a separately-launched tab cannot drive the
        # same client at the same time.
        self._game = runtime.GameLink(
            port=self._daemon_port, python=self._python, log=self._logbus,
            env=self._children.env, cwd=REPO,
            daemon_script=os.path.join(TOOLS, "lua_daemon.py"),
            on_state=self._daemon_state, debug=dbgmod.get_logger("daemon"))
        # Playing an actions/*.md scenario — the one door the panel presses through
        # (panel/runtime/actions.py).
        self._actions = runtime.ActionRunner(log=self._logbus)
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
        self._timer_store.set_path(self._profiles.timers_state())
        self._reload_timers(quiet=True)
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
            "monitor_kind": self._mon_combo.current(),
            "monitor_interval": self._interval_var.get(),
            "filter_star": self._star_var.get(),
            "filter_pending": self._pending_var.get(),
            "filter_can_loot": self._can_loot_var.get(),
            # The display filter…
            "filter_level_from": self._flt_from_var.get(),
            "filter_level_to": self._flt_to_var.get(),
            # …and, separately, the level auto-loot actually robs at. One pair used
            # to be both, which is how a robbery got spent on a level-6 star.
            "autoloot_level_from": self._lvl_from_var.get(),
            "autoloot_level_to": self._lvl_to_var.get(),
            "rally_monitor": self._rally_var.get(),
            # `alliance_autohelp` (the old checkbox) is deliberately not written back:
            # it became the «alliance_help» trigger in the profile's timers.json, and
            # `_migrate_autohelp` flips that on once for a profile that had it set.
            "rally_autojoin": self._rally_autojoin_var.get(),
            "rally_alert": self._rally_alert_var.get(),
            "secret_monitor": self._mon_var.get(),
            "autoloot": self._autoloot_var.get(),
            "ghost_autoloot": self._ghost_autoloot_var.get(),
            "chat_monitor": self._chat_var.get(),
            "map_sweep": self._sweep_var.get(),
            "sweep_centre_x": self._sweep_cx_var.get(),
            "sweep_centre_y": self._sweep_cy_var.get(),
            # The Scenarios tab used to forget all three on every restart, so a
            # launch always started on the first row with an empty args box.
            "scenario_selected": self._scn_editor_name or "",
            "scenario_args": self._scn_args_var.get(),
            "scenario_interval": self._scn_interval_var.get(),
            "log_filter": self._log_filter_var.get(),
            "window_geometry": self._current_geometry(),
            "log_sash": self._current_sash(),
            # Settings page -> «Авторалли»: which squads may be sent, and the
            # alliance-drill variant with its single banner-carrier.
            "autorally": self._autorally_config(),
            # The «Ралли» tab's own four choices (target kind, level, squads, repeats).
            "rally_tab": self._rally_tab_config(),
            # The «Командный пункт» tab: the shared-mission robbery rule and the
            # treasure page's digging squad, a block per page.
            "command_post": self._command_post_config(),
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
        return out

    def _apply_settings_to_ui(self) -> None:
        """Push self._settings into the widgets without triggering auto-save."""
        s = self._settings
        self._loading = True
        try:
            idx = s.get("monitor_kind", 0)
            if isinstance(idx, int) and 0 <= idx < len(CAPTURE_OPTIONS):
                self._mon_combo.current(idx)
            self._interval_var.set(str(s.get("monitor_interval", "15")))
            self._star_var.set(bool(s.get("filter_star", False)))
            self._pending_var.set(bool(s.get("filter_pending", False)))
            self._can_loot_var.set(bool(s.get("filter_can_loot", False)))
            self._flt_from_var.set(s.get("filter_level_from", ""))
            self._flt_to_var.set(s.get("filter_level_to", ""))
            # A profile saved before the two were split has only the one pair, and
            # it was aiming the robberies as well as filtering the log — so seed the
            # auto-loot range from it rather than silently widening the rule.
            self._lvl_from_var.set(s.get("autoloot_level_from",
                                         s.get("filter_level_from", "")))
            self._lvl_to_var.set(s.get("autoloot_level_to",
                                       s.get("filter_level_to", "")))
            self._rally_var.set(bool(s.get("rally_monitor", True)))
            self._rally_autojoin_var.set(bool(s.get("rally_autojoin", False)))
            self._rally_alert_var.set(bool(s.get("rally_alert", True)))
            self._mon_var.set(bool(s.get("secret_monitor", False)))
            self._autoloot_var.set(bool(s.get("autoloot", False)))
            self._ghost_autoloot_var.set(bool(s.get("ghost_autoloot", False)))
            self._chat_var.set(bool(s.get("chat_monitor", False)))
            self._sweep_var.set(bool(s.get("map_sweep", False)))
            self._sweep_cx_var.set(s.get("sweep_centre_x", ""))
            self._sweep_cy_var.set(s.get("sweep_centre_y", ""))
            self._scn_args_var.set(s.get("scenario_args", ""))
            self._scn_interval_var.set(str(s.get("scenario_interval", "60")))
            self._log_filter_var.set(s.get("log_filter") or LOG_FILTER_ALL)
            for key, default in SETTINGS_DEFAULTS.items():
                var = self._opt_vars.get(key)
                if var is not None:
                    var.set(s.get(key, default))
            self._apply_autorally_config(s.get("autorally"))
            tab = getattr(self, "_rally_tab", None)
            if tab is not None:
                tab.apply_config(s.get("rally_tab"))
            post = getattr(self, "_command_post_tab", None)
            if post is not None:
                post.apply_config(s.get("command_post"))
            self._reload_rally_limits_ui()
        finally:
            self._loading = False
        self._update_path_hints()
        self._select_saved_scenario(s.get("scenario_selected"))
        self._refresh_rule_hints()

    def _install_autosave(self) -> None:
        """Persist to the active profile whenever any bound setting changes."""
        for var in (self._star_var,
                    self._pending_var, self._can_loot_var,
                    self._flt_from_var, self._flt_to_var,
                    self._lvl_from_var, self._lvl_to_var,
                    self._rally_var, self._mon_var,
                    self._autoloot_var, self._ghost_autoloot_var, self._chat_var,
                    self._rally_autojoin_var, self._rally_alert_var,
                    self._sweep_var, self._sweep_cx_var, self._sweep_cy_var,
                    self._scn_args_var, self._scn_interval_var,
                    self._log_filter_var,
                    self._drill_on_var, self._drill_banner_var,
                    self._create_elite_var,
                    *self._rally_squad_vars.values()):
            var.trace_add("write", lambda *a: self._save_settings())
        # The two tabs that keep their own settings (panel/tabs_extra.py RallyTab,
        # panel/command_post.py CommandPostTab). Traced from here like every other bound
        # setting, so the tabs stay free of the profile machinery.
        for owner in (getattr(self, "_rally_tab", None),
                      getattr(self, "_command_post_tab", None)):
            if owner is None:
                continue
            for var in owner.persist_vars():
                var.trace_add("write", lambda *a: self._save_settings())
        # The two rule lines under «Автолут ★» and «Автообъезд» describe what the
        # boxes are about to do; keep them true as the numbers are typed.
        for var in (self._lvl_from_var, self._lvl_to_var,
                    self._sweep_cx_var, self._sweep_cy_var):
            var.trace_add("write", lambda *a: self._refresh_rule_hints())
        # The Settings page's own knobs. The daemon port is the one that needs more
        # than a save: the panel's client has to be re-pointed at it.
        for key, var in self._opt_vars.items():
            if key == "daemon_port":
                var.trace_add("write", lambda *a: self._on_daemon_port_change())
            else:
                var.trace_add("write", lambda *a: self._save_settings())
        self._mon_combo.bind("<<ComboboxSelected>>", lambda e: self._save_settings(), add="+")
        # The interval is a child-process argument, not a live panel-side filter,
        # so a change only takes effect on the next capture launch. Bounce a
        # running monitor so a new value applies at once instead of on the next
        # manual toggle. Saved too (via _save_settings inside _restart_monitor).
        self._interval_var.trace_add("write", lambda *a: self._on_interval_change())

    def _on_daemon_port_change(self) -> None:
        self._save_settings()
        if not self._loading:
            self._rebind_daemon()

    def _refresh_rule_hints(self) -> None:
        """Re-render the two "this is what the checkbox will do" lines.

        Both standing orders are invisible otherwise, and an invisible rule is how a
        robbery got spent on a level-6 star: the operator has to be able to read
        what a checkbox is about to do without opening the source.
        """
        lbl = getattr(self, "_autoloot_rule_lbl", None)
        if lbl is not None:
            try:
                lbl.configure(text=self._autoloot_rule_text())
            except tk.TclError:
                pass
        # The poll re-reads the range live every tick, but the event-driven listener is a
        # subprocess started with a fixed range — so a range typed while auto-loot is on
        # has to restart it, or it would rob to the OLD «уровень до» (the very "robbed the
        # wrong level" trap #1099 fixed for the poll). Debounced so typing "1" then "7"
        # restarts once, not per keystroke — spawning a capture is not free.
        if getattr(self, "_autoloot_stop", None) is not None:
            after = getattr(self, "_autoloot_push_restart", None)
            if after is not None:
                try:
                    self.after_cancel(after)
                except Exception:                # noqa: BLE001
                    pass
            self._autoloot_push_restart = self.after(1500, self._restart_autoloot_push)
        hint = getattr(self, "_sweep_hint", None)
        if hint is not None:
            try:
                hint.configure(text=self._sweep_rule_text())
            except tk.TclError:
                pass

    def _on_interval_change(self) -> None:
        self._save_settings()
        if not self._loading and self._mon_proc is not None:
            self._restart_monitor()

    def _restart_monitor(self) -> None:
        """Bounce the secret capture so a changed --interval/server seed applies."""
        self._stop_monitor()
        self._start_monitor()

    def _save_settings(self) -> None:
        if self._binder.loading:
            return
        self._binder.save(self._collect_settings())

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
        # Auto-loot reads the *profile's* checkpoint, so a profile switch has to
        # bounce the watcher too — and clear the uuids it robbed under the old one.
        self._stop_autoloot()
        if self._autoloot_var.get():
            self._start_autoloot()
        # The ghost-recon order and the map sweep both drive THIS profile's client,
        # so a switch has to bounce them as well.
        self._stop_ghost_autoloot()
        if self._ghost_autoloot_var.get():
            self._start_ghost_autoloot()
        # Same for the command post's shared-mission listener: it captures for THIS
        # profile's client and robs through its daemon, so it is bounced and brought
        # back under the new one if its box is still ticked.
        post = getattr(self, "_command_post_tab", None)
        if post is not None:
            post.restart_children()
        self._stop_sweep()
        if self._sweep_var.get():
            self._start_sweep()
        self._stop_chat()
        if self._chat_var.get():
            self._start_chat()
        # The schedule belongs to the account: its timers, their switches and
        # periods, and the clock that says when each last ran. Re-read all of it,
        # or the profile just switched to would run the other one's errands and
        # look as freshly collected as it did.
        self._timer_store.set_path(self._profiles.timers_state())
        self._reload_timers(quiet=True)
        # The triggers belong to the account as much as the schedule: re-read this
        # profile's triggers.json, redraw the rows and reconcile the listeners — a
        # switch must not leave the previous profile's watcher listening on this one's
        # behalf. `_reload_triggers` does all three (and the one-time autohelp migrate).
        self._reload_triggers(quiet=True)
        # The resource tally is per profile too: re-read this one's, drop the balance
        # baseline (the other account's numbers are not this one's), and redraw.
        self._resource_stats = resourcestatsmod.load_stats(
            self._profiles.resource_stats_json())
        self._resource_last = {}
        if hasattr(self, "_stats_grid"):
            self._refresh_stats_table()

    def _update_path_hints(self) -> None:
        """Refresh labels that show the active profile's log path (rally hint)."""
        if hasattr(self, "_rally_hint"):
            try:
                # _repo_rel, not os.path.relpath: a profile directory on
                # another drive makes the bare call RAISE, and a display helper
                # must never be the thing that breaks the UI.
                rel = _repo_rel(self._profiles.rally_log())
                self._rally_hint.configure(text=self._t("rally.hint", path=rel))
            except tk.TclError:
                pass

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
        scenarios = ttk.Frame(nb)
        timers_tab = ttk.Frame(nb)
        settings_tab = ttk.Frame(nb)
        chat_tab = ttk.Frame(nb)
        stats_tab = ttk.Frame(nb)
        alliance_tab = ttk.Frame(nb)
        profile_tab = ttk.Frame(nb)
        inventory_tab = ttk.Frame(nb)
        heroes_tab = ttk.Frame(nb)
        accounts_tab = ttk.Frame(nb)
        secret_tasks_tab = ttk.Frame(nb)
        command_post_tab = ttk.Frame(nb)
        rally_tab = ttk.Frame(nb)
        nb.add(main, text=self._t("tab.main"))
        nb.add(scenarios, text=self._t("tab.scenarios"))
        nb.add(timers_tab, text=self._t("tab.timers"))
        nb.add(settings_tab, text=self._t("tab.settings"))
        nb.add(chat_tab, text=self._t("tab.chat"))
        nb.add(stats_tab, text=self._t("tab.stats"))
        nb.add(alliance_tab, text=self._t("tab.alliance"))
        nb.add(profile_tab, text=self._t("tab.profile"))
        nb.add(inventory_tab, text=self._t("tab.inventory"))
        nb.add(heroes_tab, text=self._t("tab.heroes"))
        nb.add(accounts_tab, text=self._t("tab.accounts"))
        nb.add(secret_tasks_tab, text=self._t("tab.secret_tasks"))
        nb.add(command_post_tab, text=self._t("tab.command_post"))
        nb.add(rally_tab, text=self._t("tab.rally"))
        self._hook(key="tab-titles", func=lambda: (
            nb.tab(main, text=self._t("tab.main")),
            nb.tab(scenarios, text=self._t("tab.scenarios")),
            nb.tab(timers_tab, text=self._t("tab.timers")),
            nb.tab(settings_tab, text=self._t("tab.settings")),
            nb.tab(chat_tab, text=self._t("tab.chat")),
            nb.tab(stats_tab, text=self._t("tab.stats")),
            nb.tab(alliance_tab, text=self._t("tab.alliance")),
            nb.tab(profile_tab, text=self._t("tab.profile")),
            nb.tab(inventory_tab, text=self._t("tab.inventory")),
            nb.tab(heroes_tab, text=self._t("tab.heroes")),
            nb.tab(accounts_tab, text=self._t("tab.accounts")),
            nb.tab(secret_tasks_tab,
                   text=self._t("tab.secret_tasks")),
            nb.tab(command_post_tab,
                   text=self._t("tab.command_post")),
            nb.tab(rally_tab, text=self._t("tab.rally"))))
        self._build_scenarios_tab(scenarios)
        self._build_timers_tab(timers_tab)
        self._build_settings_tab(settings_tab)
        self._build_chat_tab(chat_tab)
        self._build_stats_tab(stats_tab)
        # The three read-only tabs (panel/tabs_extra.py). Their UI is built now but the
        # data is read lazily — the first time each tab is opened (_on_main_tab_changed).
        self._main_nb = nb
        self._inventory_tab = tabsextra.InventoryTab(self, inventory_tab)
        self._secret_tasks_tab = secrettasksmod.SecretTasksTab(self, secret_tasks_tab)
        # «Секретный командный пункт» — ghost recon, shared missions and treasures. Built
        # eagerly like the one above (its ghost page owns `_ghost_autoloot_var`, which the
        # settings load expects to exist); each of its three pages still reads lazily.
        self._command_post_tab = commandpostmod.CommandPostTab(self, command_post_tab)
        # The account summary strip: built into the «Аккаунты» tab, above the list of
        # characters it summarises. It used to sit on the Main tab, which left that tab
        # holding three unrelated subjects at once (#1183). Built BEFORE the tab class
        # below so the strip packs above that tab's own header.
        self._build_dashboard(accounts_tab)
        self._lazy_tabs = {
            str(alliance_tab): tabsextra.AllianceTab(self, alliance_tab),
            str(profile_tab): tabsextra.ProfileTab(self, profile_tab),
            str(inventory_tab): self._inventory_tab,
            str(heroes_tab): tabsextra.HeroesTab(self, heroes_tab),
            str(accounts_tab): tabsextra.AccountsTab(self, accounts_tab),
            str(secret_tasks_tab): self._secret_tasks_tab,
            str(command_post_tab): self._command_post_tab,
        }
        # The «Ралли» tab drives the game (raise a rally on an elite, loop N times); it
        # has no data to lazy-load, so it is built eagerly and not in _lazy_tabs.
        self._rally_tab = tabsextra.RallyTab(self, rally_tab)
        # …and the rally monitor goes into the slot that tab leaves for it, under the
        # «создать ралли» form (#1183).
        self._build_rally_monitor(self._rally_tab.monitor_host)
        nb.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

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

        # -- Secret tasks + «Операция Призрак» moved to the «Secret Tasks» tab ----
        #
        # The whole secret-task block — the passive-capture monitor (kind combo,
        # interval, the panel-side log filters), the «Автообъезд карты» map sweep, the
        # «Автолут ★» range, AND the «Операция Призрак» watcher — used to sit on this
        # Main tab. They now live on the «Secret Tasks» tab (panel/secret_tasks.py),
        # beside the list of starred tiles they feed and gate, so the whole story is on
        # one screen. Only the *widgets* moved: every var (`_mon_var` / `_mon_combo` /
        # `_interval_var`, the `_star_var` / `_pending_var` / `_can_loot_var` /
        # `_flt_*` log filters, the `_sweep_*` map-sweep vars, `_ghost_autoloot_var`)
        # and every method (`_toggle_monitor`, `_start_monitor`, `_toggle_sweep`,
        # `_toggle_ghost_autoloot`, …) still live on this app, created by the tab's
        # `_build_monitor_bar` / `_build_ghost_bar` at construction — so the settings
        # save/load, the profile-switch restart and the capture plumbing here are
        # unchanged. The tab is built (line ~1594) before this method's body and before
        # settings are applied, so the vars exist by the time anything reads them.
        #
        # The capture the monitor runs writes a checkpoint each tick; the tab's list is
        # fed from that checkpoint (the wire), with a first-open VM snapshot to seed it.

        # -- «Ралли» moved to the «Ралли» tab ------------------------------------
        #
        # The monitor's own block (the switch, «Оповещать», «Присоединяться сам», the
        # «Присоединиться» button and the log-path hint) is built by
        # `_build_rally_monitor` into the slot the «Ралли» tab leaves for it, beside the
        # form that raises one. Only the widgets moved: `_rally_var` /
        # `_rally_alert_var` / `_rally_autojoin_var` / `_rally_hint` are still this
        # app's, so the settings save/load, the autosave traces and the monitor
        # plumbing are unchanged.

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

    # -- the rally monitor (shown on the «Ралли» tab) ------------------------
    def _build_rally_monitor(self, parent: ttk.Frame) -> None:
        """The push-driven rally watcher: listen, alert, join.

        Built here rather than in panel/tabs_extra.py because every variable and
        every handler these four widgets touch (`_toggle_rally`, `_join_rally_now`,
        the persisted `rally_*` settings) belongs to the app; the tab only says
        where they go.
        """
        rally = self._tr(ttk.LabelFrame(parent, padding=8), "rally.frame")
        rally.pack(fill="x", padx=8, pady=(0, 6))
        rally_top = ttk.Frame(rally)
        rally_top.pack(fill="x")
        self._rally_var = tk.BooleanVar(value=True)
        self._tr(ttk.Checkbutton(rally_top, variable=self._rally_var,
                                 command=self._toggle_rally),
                 "rally.monitor").pack(side="left")
        # A rally is worth minutes and the alert used to be one log line that
        # scrolled past. Now it is a line the log paints as news, a bell, and — if
        # the operator asks for it — the join itself.
        self._rally_alert_var = tk.BooleanVar(value=True)
        self._tr(ttk.Checkbutton(rally_top, variable=self._rally_alert_var),
                 "rally.alert").pack(side="left", padx=(12, 0))
        self._rally_autojoin_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(rally_top, variable=self._rally_autojoin_var),
                 "rally.autojoin").pack(side="left", padx=(12, 0))
        self._tr(ttk.Button(rally_top, command=self._join_rally_now),
                 "rally.join_now").pack(side="right")
        # Hint shows the active profile's rally log; refreshed on language/profile change.
        self._rally_hint = ttk.Label(rally, foreground="#888", wraplength=620,
                                     justify="left")
        self._rally_hint.pack(anchor="w", pady=(4, 0))
        self._hook(self._update_path_hints)

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
        if self._rally_var.get():           # rally monitor is on by default
            self._start_rally()
        if self._mon_var.get():             # secret-task monitor, if the profile had it on
            self._start_monitor()
        if self._autoloot_var.get():        # standing auto-loot order, if the profile had it on
            self._start_autoloot()
        if self._ghost_autoloot_var.get():  # the ghost-recon standing order likewise
            self._start_ghost_autoloot()
        if self._sweep_var.get():           # the map sweep, if the profile had it on
            self._start_sweep()
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
        self._timers.start()
        # A profile that had the old «Авто-помощь» checkbox on becomes the
        # «alliance_help» trigger switched on, once; then the watcher brings up a
        # listener for every enabled trigger, exactly as `sync` does on a toggle.
        self._migrate_autohelp()
        self._triggers.start()
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
        self._run_md_action("launch_game")

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
        for var, stop in ((self._mon_var, self._stop_monitor),
                          (self._autoloot_var, self._stop_autoloot),
                          (self._ghost_autoloot_var, self._stop_ghost_autoloot),
                          (self._sweep_var, self._stop_sweep),
                          (self._rally_var, self._stop_rally),
                          (self._chat_var, self._stop_chat)):
            var.set(False)
            stop()
        self._stop_scenario_loop()
        self._stop_scenario()
        self._triggers.stop()
        self._timers.stop()
        # …and say so on the Timers tab, or the schedule would be silently dead for
        # the rest of the session. That switch is how it comes back.
        if getattr(self, "_sched_var", None) is not None:
            self._sched_var.set(False)
        self._say("panel", "panic.done")

    def _current_server(self) -> str:
        try:
            for ln in self._client.run(lua_actions.current_server(), marker="ACT", settle=0.5):
                if "curserver=" in ln:
                    return ln.split("curserver=")[1].split()[0]
        except Exception as exc:
            self._say("server", "log.server.read_failed", error=exc)
        return DEFAULT_SERVER

    def _retranslate_capture_combo(self) -> None:
        idx = self._mon_combo.current()
        self._mon_combo.configure(values=[self._t(o["key"]) for o in CAPTURE_OPTIONS])
        self._mon_combo.current(idx if idx >= 0 else 0)

    # -- one way to run a child ---------------------------------------------
    def _child(self, tag: str, cmd: list, *, on_line=None, on_exit=None,
               capture_stderr: bool = True) -> "childmonmod.ChildMonitor":
        """A :class:`panel.childmon.ChildMonitor` wired to this panel."""
        return self._children.spawn(tag, cmd, on_line=on_line, on_exit=on_exit,
                                    capture_stderr=capture_stderr)

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
        cmd = [self._python(), "-u", os.path.join(TOOLS, script)]
        # Checkpoint what the capture currently sees into the profile, so the
        # auto-loot button has a machine-readable view of the map instead of the
        # log lines this panel prints for the human. Rewritten every tick; the
        # reader drops anything not re-seen in the scan window, so a stale file
        # cannot send a robbery at a tile that has already been taken.
        # Only for the secret-task capture: the ghost-recon one writes its own
        # record shape, and auto-loot must never be handed that by mistake.
        if script == runtime.SECRET_TASK_CAPTURE:
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
        if self._daemon_up():
            srv = self._current_server()
            if srv and str(srv).isdigit():
                cmd += ["--seed-server", str(srv)]
                self._say("secret", "log.secret.seed_server", srv=srv)
        self._say("secret", "log.secret.starting", script=script)
        mon = self._child("secret", cmd, on_line=self._on_secret_line,
                          on_exit=self._on_secret_exit)
        if not mon.start():
            self._mon_var.set(False)
            return
        self._mon_proc = mon
        # Confirm the child really started (so a silent monitor is never mistaken
        # for a crash). A passive pcap only yields tiles while the map is scrolling —
        # so say so, unless «Автообъезд карты» is already doing the scrolling.
        self._say("secret", "log.secret.started" if self._sweep_stop is not None
                  else "log.secret.started_move_map", pid=mon.pid)

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
        # The DISPLAY filter's own entries — not the auto-loot rule's. The two used
        # to share one pair and a person narrowing the log silently re-aimed the
        # robberies with it.
        lo, hi = self._flt_from_var.get().strip(), self._flt_to_var.get().strip()
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

    def _on_secret_line(self, line: str) -> bool:
        """One capture line: log it if the display filter lets it through, record a real
        finding into the profile's own log, and nudge the «Secret Tasks» tab to merge the
        freshly-written checkpoint — the wire feed for its list.

        The nudge is independent of the log's display filter: a tile the operator hid from
        the log is still on the map and still belongs on the tab. So it runs on every
        finding line, and on the periodic "star(s) still on timer" progress line (no
        coordinate of its own, but it marks a checkpoint flush). Called on the child's
        reader thread, so it marshals onto the Tk thread, where the merge is debounced.
        """
        is_finding = bool(coords.parse(line))
        if is_finding or "on timer" in line:
            self.after(0, self._nudge_secret_tasks_tab)
        if not self._task_passes(line):
            return False                # filtered out — handled, do not log
        if is_finding:                  # a coordinate present -> an actual finding
            self._append_secret(line)
        return True

    def _nudge_secret_tasks_tab(self) -> None:
        """A capture finding crossed the wire: re-merge the checkpoint into the tab.

        Runs on the Tk thread (marshalled from the reader). Debounced — one capture tick
        prints a burst of findings and a single merge covers them all — and a no-op unless
        the tab has been opened (an unopened one reads fresh when first shown anyway).
        """
        tab = getattr(self, "_secret_tasks_tab", None)
        if tab is None or not getattr(tab, "_loaded", False):
            return
        after = getattr(self, "_secret_tab_nudge_id", None)
        if after is not None:
            try:
                self.after_cancel(after)
            except Exception:            # noqa: BLE001 — already fired / invalid id
                pass
        self._secret_tab_nudge_id = self.after(800, tab.refresh)

    def _on_secret_exit(self) -> None:
        self._say("secret", "log.secret.ended")
        self._mon_proc = None
        self._mon_var.set(False)

    def _append_secret(self, line: str) -> None:
        """Append a secret-task finding to the active profile's log (best-effort)."""
        try:
            with open(self._profiles.secret_log(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "line": line}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _stop_monitor(self) -> None:
        mon, self._mon_proc = self._mon_proc, None
        if mon is not None:
            self._say("secret", "log.secret.stopped")
            mon.stop()

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
        rel = _repo_rel(out)
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
        except Exception:
            pass
        self._say("rally", "log.rally.started", path=rel)
        # no --all-tcp: auto-detect the narrow game port (see _start_monitor)
        mon = self._child("rally",
                          [self._python(), "-u", os.path.join(TOOLS, "rally_monitor.py"),
                           "--out", out],
                          on_line=self._on_rally_line, on_exit=self._on_rally_exit)
        if not mon.start():
            self._rally_var.set(False)
            return
        self._rally_proc = mon

    def _on_rally_exit(self) -> None:
        self._say("rally", "log.rally.ended")
        self._rally_proc = None
        self._rally_var.set(False)

    def _stop_rally(self) -> None:
        mon, self._rally_proc = self._rally_proc, None
        if mon is not None:
            self._say("rally", "log.rally.stopped")
            mon.stop()

    # -- the rally alert: a rally is worth minutes ---------------------------
    #
    # The monitor's line used to scroll past in a log six producers write to, and
    # that was the whole of it: the Settings → «Авторалли» page said which squads
    # may go and NOTHING read it. Now a rally can (a) be announced loudly, (b) be
    # joined with one press, and (c) be joined by itself.
    #
    # `team=<uuid>` in the monitor's own output is what makes a march a rally — a
    # solo march is tagged `solo` (tools/rally_monitor.py). The uuid is also the
    # de-duplicator: a rally emits create AND refresh events, and an alert per event
    # would ring four times for one стяг.
    def _on_rally_line(self, line: str) -> bool:
        # The monitor's own line first, then the alert about it — the other way round
        # reads as an alert with no event under it.
        if line:
            self._log_put(f"[rally] {line}")
        clean = _ANSI.sub("", line)
        if "team=" not in clean:
            return False                  # a solo march, or a progress line
        team = clean.split("team=")[1].split()[0].strip()
        if not team or team in self._rally_seen:
            return False
        self._rally_seen.add(team)
        if self._rally_alert_var.get():
            self._say("rally", "rally.alert.fired", team=team)
            try:
                self.bell()               # not just a line in a scrolling log
            except tk.TclError:
                pass
        if self._rally_autojoin_var.get():
            self.after(0, self._join_rally_now)
        return False                      # already logged above

    def _autorally_squads(self) -> list:
        """The squads the «Авторалли» page allows, as `join_rally` wants them."""
        raw = self._autorally_config().get("squads")
        return [int(s) for s in raw] if isinstance(raw, list) else []

    def _join_rally_now(self) -> None:
        """Join the rallies that are out, with the squads the settings page allows.

        This is what makes the «Авторалли» page real: its squad list IS the recipe's
        `squads` argument. With no squad ticked the join would be a silent no-op that
        looked like it had worked, so it refuses and says which page to visit.
        """
        squads = self._autorally_squads()
        if not squads:
            self._say("rally", "rally.no_squads")
            return
        self._say("rally", "rally.joining",
                  squads=", ".join(str(s) for s in squads))
        self._run_md_action("join_rally", {"squads": squads})

    # -- triggers: run an errand when a wire event lands ---------------------
    #
    # A trigger (panel/triggers.py) answers «Помочь всем» the instant a request's push
    # crosses the wire. The bookkeeping — which listeners should be running — lives in
    # the watcher; the panel only supplies the two things that need Tk / a child
    # process: how to spawn a listener, and what to do when one fires. The watcher's
    # `submit` is `self._timers.submit`, so a fired scenario goes on the SAME queue the
    # schedule feeds and runs single-file with the scheduled timers.
    #
    # The listener is a general wire-event child (tools/wire_event_monitor.py):
    # capture must run in the Windows Python, off the Tk thread. It presses nothing —
    # it prints a marker line, and the panel turns that into one submit.
    def _spawn_trigger_listener(self, trigger, on_fire):
        """Start a wire listener for one trigger; call `on_fire` on every match.

        Returns the child handle (a ChildMonitor, which has the `.stop()` the
        watcher wants) or ``None`` if it would not start. The reader swallows the
        marker line and lets the human line through into the log.

        Most wire triggers listen with the generic wire_event_monitor (a marker on
        every match). «leaderboard_collect» is different: the board data is in the
        push payload, not readable off a mark, so its listener is the specialised
        collector (scan_leaderboard.py) which decodes each board and appends it to
        this profile's leaderboard_history.db itself — nothing is submitted, the
        child does the work.
        """
        if trigger.name == "leaderboard_collect":
            return self._spawn_leaderboard_collector(trigger)
        marker = triggersmod.FIRE_MARKER

        def on_line(line: str):
            if line.startswith(marker):
                on_fire()               # thread-safe: submit hands to the queue
                return False            # the marker is machinery, not for the log
            return None                 # the human line logs as usual

        # no --all-tcp: auto-detect the narrow game port (see _start_monitor)
        mon = self._child("trigger",
                          [self._python(), "-u",
                           os.path.join(TOOLS, "wire_event_monitor.py"),
                           "--match", trigger.event_pattern],
                          on_line=on_line,
                          on_exit=lambda n=trigger.name: self._on_trigger_exit(n))
        if not mon.start():
            return None
        return mon

    def _spawn_leaderboard_collector(self, trigger):
        """The «leaderboard_collect» listener: a standing capture that saves boards.

        scan_leaderboard.py decodes every ranking board that crosses the wire and, with
        --sqlite, appends it to this profile's leaderboard_history.db as a timestamped
        snapshot. It writes the DB itself, so there is no marker and nothing is
        submitted — the watcher just needs the handle to stop it when the box is
        unticked. Runs under the Windows Python off the Tk thread, like every capture.
        """
        mon = self._child("trigger",
                          [self._python(), "-u",
                           os.path.join(TOOLS, "scan_leaderboard.py"),
                           "--sqlite", self._profiles.leaderboard_db()],
                          on_exit=lambda n=trigger.name: self._on_trigger_exit(n))
        if not mon.start():
            return None
        return mon

    def _on_trigger_exit(self, name: str) -> None:
        """A trigger's listener died on its own — forget it and say so.

        The next `_triggers.sync()` (a box toggled, the game relaunched) brings it
        back if the trigger is still switched on.
        """
        self._triggers.on_listener_exit(name)
        self._say("trigger", "triggers.log.died", name=name)

    def _poll_trigger(self, trigger) -> bool:
        """Evaluate a poll trigger's check through the daemon; ``True`` to fire.

        Runs on the watcher's own poll thread (not Tk), every ``interval_sec``. Reads
        the boolean off a marked log line the way the dashboard reads its numbers, and
        uses its own evaluator so it does not share the dashboard client's socket. A
        closed game / no daemon reads as ``False`` — there is no kick to recover from
        if the client is not even up, and firing then would relaunch a game nobody
        started.
        """
        if not self._daemon_up():
            return False
        chunk = ('local ok, v = pcall(function() return %s end) '
                 'CS.UnityEngine.Debug.LogError("TRIGCHK=" .. tostring(ok and v and true or false))'
                 % trigger.check)
        try:
            ev = lua_client.get_evaluator(port=self._daemon_port())
            lines = ev.run(chunk, marker="TRIGCHK", settle=0.6)
        except Exception:                       # noqa: BLE001 — a bad read is not a kick
            return False
        return any("TRIGCHK=true" in ln.lower() for ln in (lines or []))

    def _migrate_autohelp(self) -> None:
        """Carry the retired «Авто-помощь» checkbox onto the `alliance_help` trigger.

        The old per-profile setting was `alliance_autohelp`; a profile that had it on
        should keep answering, so flip the trigger on once (and persist it) and let
        the box's own state in triggers.json own it from then on. Idempotent: enabling
        an already-on trigger changes nothing.
        """
        if not self._settings.get("alliance_autohelp"):
            return
        # Consume the flag so this runs ONCE: without clearing it, a user who then
        # unticks the trigger would have it switched back on at the next switch.
        self._settings.pop("alliance_autohelp", None)
        self._profiles.save(self._settings)
        trig = self._trigger_catalogue.by_name("alliance_help")
        if trig is None or trig.enabled:
            return
        self._trigger_catalogue = self._trigger_catalogue.with_enabled(
            {**self._trigger_catalogue.enabled_config(), "alliance_help": True})
        triggersmod.save_catalogue(self._trigger_catalogue,
                                   self._profiles.triggers_json())
        if hasattr(self, "_trigger_grid"):
            self._fill_trigger_grid()

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
        self._say("autoloot", "log.autoloot.on", rule=self._autoloot_rule_text())
        if self._mon_proc is None:
            self._say("autoloot", "log.autoloot.no_monitor")
        # Two paths, on purpose. The event-driven listener robs a *shared* secret task
        # the instant its push crosses the wire (< 1 s), which is the case a human used
        # to win; the poll below is the slower safety net that still catches enemy tiles
        # the sweep panned over and tasks already present before the listener started.
        self._start_autoloot_push()
        threading.Thread(target=self._autoloot_loop, args=(self._autoloot_stop,),
                         daemon=True).start()

    def _stop_autoloot(self) -> None:
        stop, self._autoloot_stop = self._autoloot_stop, None
        if stop is not None:
            stop.set()
            self._say("autoloot", "log.autoloot.off")
        self._stop_autoloot_push()

    def _start_autoloot_push(self) -> None:
        """Spawn the event-driven listener: rob a shared secret task on its push (#1124).

        It sniffs the game stream itself (no dependence on the «Мониторинг» capture) and
        acts through this profile's daemon, so it gets the same level range the poll's
        child does — otherwise it would rob outside «уровень от / до».
        """
        if self._autoloot_push_proc is not None:
            return
        cmd = [self._python(), "-u", os.path.join(TOOLS, "secret_share_autoloot.py"),
               "--star-max", "--limit", str(self._autoloot_limit())]
        lo, hi = self._autoloot_levels()
        if lo is not None:
            cmd += ["--level-min", str(lo)]
        if hi is not None:
            cmd += ["--level-max", str(hi)]
        proc = self._spawn_sniffer(cmd, "autoloot")
        if proc is None:
            return
        self._autoloot_push_proc = proc
        threading.Thread(target=self._autoloot_push_reader, args=(proc,),
                         daemon=True).start()

    def _stop_autoloot_push(self) -> None:
        proc, self._autoloot_push_proc = self._autoloot_push_proc, None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:                    # noqa: BLE001 — already gone is fine
                pass

    def _restart_autoloot_push(self) -> None:
        """Re-spawn the listener so a changed «уровень от / до» takes effect (debounced)."""
        self._autoloot_push_restart = None
        if self._autoloot_stop is None:          # auto-loot was unticked meanwhile
            return
        self._stop_autoloot_push()
        self._start_autoloot_push()

    def _autoloot_push_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                ln = raw.rstrip()
                if ln:
                    self._log_put(f"[autoloot] {ln}")
        except Exception:
            pass
        if self._autoloot_push_proc is proc:
            self._autoloot_push_proc = None

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
                    self._say("autoloot", "log.autoloot.poll_error", error=err)
            if stop.wait(self._opt_float("autoloot_poll", low=1.0, high=600.0)):
                return

    def _autoloot_tick(self) -> None:
        """One look at the sources: fire when the rule has a target we have not sent yet.

        The primary source is the live game VM (`ActDispatchTaskDataManager.allianceTask`,
        read through the warm daemon): a member's shared secret task is in it the moment
        the push lands, so a raidable star is knowable in the second it appears rather
        than whenever the map sweep next pans over it — which is what let a human beat the
        bot to the tile (task #1124). The capture checkpoint is kept as a *second* source,
        so enemy tiles the sweep panned over are still robbed when the monitor is on; when
        it is off, the VM alone carries the feature.
        """
        if self._autoloot_proc is not None:          # a robbery is still running
            return
        if time.time() < self._autoloot_pause_until:  # the day's budget is spent
            return
        checkpoint = self._profiles.tasks_json()
        have_scan = os.path.exists(checkpoint)
        vm_ready = self._daemon_up() and not self._busy
        if not vm_ready and not have_scan:
            # No live VM to read and no checkpoint to fall back on — there is simply no
            # source yet. Say so once, not on every poll.
            if not self._autoloot_warned:
                self._autoloot_warned = True
                self._say("autoloot", "log.autoloot.no_scan")
            return
        self._autoloot_warned = False
        targets = self._autoloot_all_targets(checkpoint if have_scan else None, vm_ready)
        # Already-sent uuids are skipped: a source keeps showing a tile the server
        # refused (or that we robbed but whose loot count has not come back yet), and
        # re-firing at it would burn the day's budget on a target that cannot pay. A
        # fresh session forgets them again.
        fresh = [t for t in targets if t[0] not in self._autoloot_seen]
        if not fresh:
            return
        for _uuid, _srv, label in fresh:
            self._say("autoloot", "log.autoloot.target", label=label)
        # Mark *every* target of the rule, not just the fresh ones: the child re-reads
        # the same sources and will attempt the whole list, so the panel must not treat
        # the rest as new the next time round.
        self._autoloot_seen.update(uuid for uuid, _srv, _label in targets)
        self._autoloot_run(checkpoint if have_scan else None, vm_ready)

    def _autoloot_all_targets(self, checkpoint, vm_ready: bool) -> list:
        """Union of the VM's raidable alliance tasks and the checkpoint's, VM first.

        A target that appears in both sources under the same `(uuid, server)` is kept
        once — the VM copy, the fresher of the two. A source raising propagates up to
        `_autoloot_loop`, which logs it once and tries again next poll; that is fine
        because a robbery needs the daemon anyway, so a dead VM is a tick with nothing to
        rob rather than a target quietly dropped.
        """
        seen: set = set()
        out: list = []

        def _merge(rows):
            for uuid, srv, label in rows:
                if (uuid, srv) in seen:
                    continue
                seen.add((uuid, srv))
                out.append((uuid, srv, label))

        if vm_ready:
            _merge(self._autoloot_vm_targets())
        if checkpoint is not None:
            _merge(self._autoloot_targets(checkpoint))
        return out

    def _autoloot_vm_targets(self) -> list:
        """Star-max raidable alliance tasks read live from the VM, as (uuid, server, label).

        The same rule `_autoloot_targets` applies to a checkpoint, applied to the tasks
        the game already holds — no capture, no map panning. `self._client` is the warm
        daemon, which `steal_secret_task.targets_from_vm` drives exactly like the
        `get_evaluator()` handle a standalone run uses.
        """
        import steal_secret_task     # lazy: keeps panel start-up free of it
        lo, hi = self._autoloot_levels()
        return steal_secret_task.targets_from_vm(self._client, limit=self._autoloot_limit(),
                                                 star_max=True, level_min=lo,
                                                 level_max=hi, say=lambda _m: None)

    def _autoloot_targets(self, checkpoint: str) -> list:
        """Star-max targets in the checkpoint right now, as (uuid, server, label).

        Pure file work — `targets_from_scan` parses the checkpoint and applies the
        freshness/raidability rules; it does not touch the game or the daemon, so it
        is safe to call from the watcher thread on every poll.
        """
        import steal_secret_task     # lazy: keeps panel start-up free of it
        lo, hi = self._autoloot_levels()
        return steal_secret_task.targets_from_scan(checkpoint, limit=self._autoloot_limit(),
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

    def _autoloot_run(self, checkpoint, vm_ready: bool) -> None:
        cmd = [self._python(), "-u", os.path.join(TOOLS, "steal_secret_task.py"),
               "--star-max", "--limit", str(self._autoloot_limit())]
        # The child re-reads the same sources and re-applies the rule, so it has to be
        # told which ones the tick used: the live VM (fast path) and/or the capture
        # checkpoint (enemy tiles the sweep saw). Passing neither would leave it with
        # nothing to rob.
        if vm_ready:
            cmd.append("--from-vm")
        if checkpoint is not None:
            cmd += ["--from-scan", checkpoint]
        # The child re-applies the rule, so the range has to travel with it: without
        # these the watcher would agree to a target inside the range and the child
        # would then rob outside it.
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
            pause = self._opt_int("autoloot_pause_min", low=1, high=1440) * 60
            self._autoloot_pause_until = time.time() + pause
            self._say("autoloot", "log.autoloot.spent", mins=int(pause // 60))
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
        try:
            return subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=REPO,
                env=self._child_env(), creationflags=NO_WINDOW)
        except Exception as exc:
            self._say(tag, "log.launch_failed", error=exc)
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
        """Jump the camera to a tile. Serialised against every other game action.

        The claim goes through `_claim_busy` like `_act` and `_run_timer_action` do.
        It used to read and set `self._busy` bare, outside the lock — so a
        coordinate clicked in the log and a timer coming due in the same instant
        could both read "free" and both proceed into the game VM at once.

        `quiet` is for the map sweep, which jumps dozens of times a pass: its own
        progress line is enough, one «переход / готово» pair per waypoint would bury
        the findings the sweep exists to produce, and a «занят» every few seconds
        while an errand runs would be worse still.

        Returns whether the jump was STARTED — ``False`` means the flag was taken by
        something else. The sweep uses that to keep its place instead of losing the
        waypoint it was refused on.
        """
        if not self._claim_busy():
            if not quiet:
                self._say("panel", "busy")
            return False

        def work() -> None:
            try:
                if not self._daemon_up() and not self._ensure_daemon():
                    self._say("coord", "log.no_daemon")
                    return
                cur = self._current_server()
                target = int(server) if server is not None else int(cur)
                if not quiet:
                    self._say("coord", "log.coord.jumping",
                              where=coords.fmt(x, y, target))
                chunk = lua_actions.jump_to_coord(x, y, target)
                for ln in self._client.run(chunk, marker="ACT", settle=1.6):
                    self._log_put(f"[coord] {ln}")
                if not quiet:
                    self._say("coord", "log.done")
            except Exception as exc:
                self._say("coord", "log.error", error=exc)
            finally:
                self._release_busy()
                self.after(400, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()
        return True

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
        self._run_md_action("launch_game")

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
            self._run_md_action("launch_game")
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
    def _toggle_sweep(self) -> None:
        if self._sweep_var.get():
            self._start_sweep()
        else:
            self._stop_sweep()

    def _sweep_centre(self) -> "tuple[int, int] | None":
        """The box's centre, or ``None`` when it has not been given one."""
        cx, cy = self._sweep_cx_var.get().strip(), self._sweep_cy_var.get().strip()
        if not (cx.lstrip("-").isdigit() and cy.lstrip("-").isdigit()):
            return None
        return int(cx), int(cy)

    # «Отсюда» — which copied the jump block's X/Y into the two boxes above — went
    # with that block (#1183). The centre is typed into `_sweep_cx_var` /
    # `_sweep_cy_var` directly, and those two are still saved to the profile.

    def _sweep_rule_text(self) -> str:
        """What the checkbox is about to do, in one phrase — box, jumps, minutes."""
        centre = self._sweep_centre()
        if centre is None:
            return self._t("sweep.no_centre")
        radius, step, dwell, _rest = self._sweep_box()
        jumps, seconds = mapsweepmod.describe(centre[0], centre[1], radius, step, dwell)
        return self._t("sweep.rule", side=radius * 2 + 1, jumps=jumps,
                       mins=max(1, int(seconds // 60)))

    def _start_sweep(self) -> None:
        if self._sweep_stop is not None:         # already sweeping
            return
        if self._sweep_centre() is None:
            self._sweep_var.set(False)
            self._say("sweep", "sweep.no_centre")
            return
        self._sweep_stop = threading.Event()
        self._sweep_at = 0
        self._sweep_pass = 0
        self._log_put("[sweep] " + self._sweep_rule_text())
        if self._mon_proc is None:
            # The sweep produces traffic; without the capture nobody reads it.
            self._say("sweep", "sweep.no_monitor")
        threading.Thread(target=self._sweep_loop, args=(self._sweep_stop,),
                         daemon=True).start()

    def _stop_sweep(self) -> None:
        stop, self._sweep_stop = self._sweep_stop, None
        if stop is not None:
            stop.set()
            self._say("sweep", "sweep.off")

    def _sweep_loop(self, stop: threading.Event) -> None:
        """Walk the box, pass after pass, until the checkbox is cleared.

        The waypoint list is rebuilt at the start of each pass rather than held: the
        centre and the box are live fields, so retyping them takes effect on the next
        pass instead of needing the checkbox toggled.

        One tick is wrapped like the auto-loot watcher's: this is a background loop
        nobody is watching, so a single failed jump must cost a log line and not the
        sweep for the session.
        """
        last_err = ""
        dwell = mapsweepmod.DEFAULT_DWELL
        while not stop.is_set():
            try:
                centre = self._sweep_centre()
                if centre is None:
                    self._say("sweep", "sweep.no_centre")
                    return
                radius, step, dwell, rest = self._sweep_box()
                points = mapsweepmod.waypoints(centre[0], centre[1], radius, step)
                if self._sweep_at >= len(points):
                    # A pass is done. Rest before the next one: the map does not
                    # change fast enough to be worth walking it back to back, and a
                    # gap is what lets an errand or a person use the client.
                    self._sweep_pass += 1
                    self._sweep_at = 0
                    self._say("sweep", "sweep.pass_done", n=self._sweep_pass,
                              mins=int(rest // 60))
                    if stop.wait(rest):
                        return
                    continue
                x, y = points[self._sweep_at]
                # Quiet: dozens of waypoints a pass, and one «переход / готово» pair
                # each would bury the findings the sweep exists to produce.
                #
                # Advance ONLY on a jump that really started. A refusal means an
                # errand or a button press holds the flag, and losing the waypoint
                # would leave a hole in the pass — exactly the band of tiles the
                # sweep exists to cover. It waits out the dwell and tries the same
                # one again.
                if self._jump(x, y, None, quiet=True):
                    self._sweep_at += 1
                last_err = ""
            except Exception as exc:      # noqa: BLE001 — one tick, not the loop
                err = f"{type(exc).__name__}: {exc}"
                if err != last_err:
                    last_err = err
                    self._say("sweep", "log.sweep.error", error=err)
            if stop.wait(dwell):
                return

    # -- «Операция Призрак»: the same standing order, no capture needed -------
    #
    # Secret tasks needed a pcap because their tiles only arrive while the map moves.
    # Ghost recon does not: the client keeps the whole squad list
    # (`ghost.recon.get.task.list`) and its own verdict on each, so the watcher polls
    # the game rather than a checkpoint. tools/ghost_recon_steal.py --all does the
    # deciding and the robbing, exactly as steal_secret_task.py does for the other.
    def _toggle_ghost_autoloot(self) -> None:
        if self._ghost_autoloot_var.get():
            self._start_ghost_autoloot()
        else:
            self._stop_ghost_autoloot()

    def _start_ghost_autoloot(self) -> None:
        if self._ghost_stop is not None:
            return
        self._ghost_stop = threading.Event()
        self._say("ghost", "ghost.on")
        threading.Thread(target=self._ghost_loop, args=(self._ghost_stop,),
                         daemon=True).start()

    def _stop_ghost_autoloot(self) -> None:
        stop, self._ghost_stop = self._ghost_stop, None
        if stop is not None:
            stop.set()
            self._say("ghost", "ghost.off")

    def _ghost_loop(self, stop: threading.Event) -> None:
        """Poll the event's budget; rob when it is open and something is robbable."""
        last_err = ""
        while not stop.is_set():
            wait = GHOST_POLL
            try:
                wait = self._ghost_tick()
                last_err = ""
            except Exception as exc:      # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                if err != last_err:
                    last_err = err
                    self._say("ghost", "log.ghost.error", error=err)
            if stop.wait(wait):
                return

    def _ghost_tick(self) -> float:
        """One look. Returns how long to wait before the next one.

        Six days a week the event is shut, `IsOpenDay()` says so in one cheap read,
        and the answer is "look again in an hour" — a minute-by-minute poll of a
        closed event is a log nobody wants and a round trip nobody needs.
        """
        if self._ghost_proc is not None:      # a robbery is still running
            return GHOST_POLL
        if self._busy or not self._daemon_up():
            return GHOST_POLL
        running, _text = game_status(self._game_exe())
        if not running:
            return GHOST_POLL
        chunk = ('CS.UnityEngine.Debug.LogError("GHOST open=" .. tostring(%s) '
                 '.. " left=" .. tostring(%s))'
                 % (lua_actions.ghost_recon_is_open(),
                    lua_actions.ghost_recon_steals_left()))
        text = " ".join(self._client.run(chunk, marker="GHOST", settle=0.6))
        if "open=1" not in text:
            return GHOST_CLOSED_PAUSE
        left = 0
        if "left=" in text:
            try:
                left = int(float(text.split("left=")[1].split()[0]))
            except (ValueError, IndexError):
                left = 0
        if left <= 0:
            # Open, but today's five are spent. The reset is at the server's day
            # boundary, so the same pause the secret-task watcher uses fits.
            return self._opt_int("autoloot_pause_min", low=1, high=1440) * 60.0
        self._ghost_run(left)
        return GHOST_POLL

    def _ghost_run(self, left: int) -> None:
        cmd = [self._python(), "-u", os.path.join(TOOLS, "ghost_recon_steal.py"),
               "--all", "--limit", str(min(left, self._autoloot_limit()))]
        self._say("ghost", "ghost.robbing", n=left)
        proc = self._spawn_sniffer(cmd, "ghost")
        if proc is None:
            return
        self._ghost_proc = proc
        threading.Thread(target=self._ghost_reader, args=(proc,), daemon=True).start()

    def _ghost_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                ln = raw.rstrip()
                if ln:
                    self._log_put(f"[ghost] {ln}")
        except Exception:
            pass
        if self._ghost_proc is proc:
            self._ghost_proc = None

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
        self._flush_scenario_save()
        self._save_settings()   # geometry and the sash, as the operator left them
        self._stop_monitor()
        self._stop_autoloot()
        self._stop_ghost_autoloot()
        # The «Секретный командный пункт» tab holds one child of its own — the
        # shared-mission listener — which must go with the window, not outlive it.
        post = getattr(self, "_command_post_tab", None)
        if post is not None:
            post.shutdown()
        self._stop_sweep()
        self._stop_dashboard()
        self._stop_rally()
        self._stop_sniff()      # stops both the traffic sniffer and the tracer
        self._stop_chat()
        if self._chat_store is not None:
            self._chat_store.close()
            self._chat_store = None
        self._stop_scenario_loop()
        self._triggers.stop()
        self._timers.stop()
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
        numeric_spinbox(controls, from_=5, to=86400, width=6,
                    textvariable=self._scn_interval_var).pack(side="left")
        self._tr(ttk.Button(controls, command=self._refresh_actions),
                 "scenarios.refresh").pack(side="right")
        # actions/dev/ is deliberately hidden from the picker — but it also hid
        # work_treasure and collect_trucks, and reaching those meant a code change.
        # A checkbox is the right size for "show the experimental ones too".
        self._scn_dev_var = tk.BooleanVar(value=False)
        self._tr(ttk.Checkbutton(controls, variable=self._scn_dev_var,
                                 command=self._refresh_actions),
                 "scenarios.show_dev").pack(side="right", padx=(0, 8))
        self._tr(ttk.Button(controls, command=self._show_button_reference),
                 "cmd.reference").pack(side="right", padx=(0, 8))

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
        self._scn_editor = ScrolledText(
            edit, wrap="none", height=12, undo=True, autoseparators=True, maxundo=-1,
            font=("Consolas", 9))
        self._scn_editor.pack(fill="both", expand=True)
        self._scn_editor.bind("<<Modified>>", self._on_editor_modified)
        # Ctrl+Z / Ctrl+Y by physical key, so they work under a Cyrillic layout —
        # Tk's own <<Undo>> binding matches the Latin keysym only (same fix as the
        # log's copy, see _install_log_copy).
        self._scn_editor.bind("<Control-KeyPress>", self._on_editor_ctrl_key)

        # The first parse error of what is in the editor, shown where it is typed —
        # a debounced save now refuses a recipe that does not parse instead of
        # replacing a working one with it.
        self._scn_problem_lbl = ttk.Label(frame, foreground="#c33", wraplength=680,
                                          justify="left")
        self._scn_problem_lbl.pack(anchor="w", pady=(4, 0))

        self._tr(ttk.Label(frame, foreground="#888", wraplength=680, justify="left"),
                 "scenarios.hint").pack(anchor="w", pady=(8, 0))

        self._scn_actions: list[dict] = []
        self._refresh_actions()
        self._load_scenario_into_editor(self._selected_action_name())

    def _refresh_actions(self) -> None:
        """(Re)load the action list into the listbox, keeping the selection if possible."""
        prev = self._selected_action_name()
        self._scn_actions = list_actions(
            include_dev=bool(getattr(self, "_scn_dev_var", None)
                             and self._scn_dev_var.get()),
            lang=self._i18n.lang)
        self._paint_action_rows()
        if not self._scn_actions:
            self._say("action", "scenarios.empty")
            return
        idx = next((i for i, a in enumerate(self._scn_actions) if a["name"] == prev), 0)
        self._scn_list.selection_clear(0, "end")
        self._scn_list.selection_set(idx)
        self._scn_list.see(idx)

    def _select_saved_scenario(self, name) -> None:
        """Put the selection back on the script the profile was last using.

        The tab used to forget all of it on restart, so every launch started on the
        first row with an empty args box.
        """
        name = str(name or "").strip()
        if not name or not getattr(self, "_scn_actions", None):
            return
        idx = next((i for i, a in enumerate(self._scn_actions) if a["name"] == name), None)
        if idx is None:
            return
        try:
            self._scn_list.selection_clear(0, "end")
            self._scn_list.selection_set(idx)
            self._scn_list.see(idx)
        except tk.TclError:
            return
        self._load_scenario_into_editor(name)

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
            dev = DEV_MARK if item.get("dev") else ""
            self._scn_list.insert("end",
                                  f"{mark} {dev}{item['title']}   ·   {item['name']}")
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
            self._say("action", "scenarios.none_selected")
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
            self._say("action", "scenarios.bad_args", error=exc)
            return None
        if not isinstance(args, dict):
            self._say("action", "scenarios.bad_args",
                      error="expected {\"name\": value}")
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
            self._say("action", "busy")
            return
        shown = f"{name} {json.dumps(args, ensure_ascii=False)}" if args else name
        self._log_put(f"[action] {shown}: {self._t('scenarios.running')}")
        cancel = threading.Event()
        self._scn_cancel = cancel
        self._set_scenario_running(name)

        def work() -> None:
            try:
                # hwnd=0 → resolved lazily only if the action uses vision primitives.
                # profile=None → READ_TEXT actions raise clearly if run without one.
                self._actions.run(
                    name, args, hwnd=0,
                    on_event=lambda msg: self._log_put(f"[action] {msg}"),
                    profile=None, cancel=cancel,
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
        self._say("action", "scenarios.stopping", name=self._scn_running or "")

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
        resolved = self._actions.resolve(name)
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
        # A freshly opened file's own problems, if any — not the last file's.
        self._show_scenario_problem(self._scenario_problem(text))

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
        """Write the editor back to the file it was loaded from — checked, and backed up.

        Two things the editor used to be missing, both of which cost work:

          * **The text is parsed first.** The editor wrote whatever was in it a second
            after the last keystroke, so a typo was discovered when the run failed —
            and by then the file had already replaced a working recipe. The DSL
            parser was right there; now the first error lands under the editor and
            the previous file is left alone.
          * **A `.bak` of the previous text.** Tk's own undo is in-session only, so a
            panel restart between the mistake and noticing it meant the recipe was
            gone. One copy of the last good version, beside the file.
        """
        self._scn_save_job = None
        name, path = self._scn_editor_name, self._scn_editor_path
        if name is None or path is None:
            return
        text = self._scn_editor.get("1.0", "end-1c")
        problem = self._scenario_problem(text)
        self._show_scenario_problem(problem)
        if problem is not None:
            # Not a save. The file on disk is still the last thing that parsed.
            return
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    previous = fh.read()
                if previous != text:
                    with open(path + ".bak", "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(previous)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except OSError as exc:
            self._say("action", "scenarios.save_failed", name=name, error=exc)
            return
        self._say("action", "scenarios.saved", name=name)

    @staticmethod
    def _scenario_problem(text: str) -> "str | None":
        """The first thing wrong with this recipe text, or ``None`` if it parses.

        The parser is run over the source with its `ARGS` defaults already
        substituted, exactly as a run would — otherwise a `{squads}` placeholder
        would read as a syntax error in a file that runs perfectly.
        """
        return runtime.ActionRunner.problem(text)

    def _show_scenario_problem(self, problem: "str | None") -> None:
        lbl = getattr(self, "_scn_problem_lbl", None)
        if lbl is None:
            return
        try:
            lbl.configure(text="" if problem is None
                          else self._t("scenarios.parse_error", error=problem))
        except tk.TclError:
            pass

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
            self._say("action", "scenarios.none_selected")
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
        self._say("action", "scenarios.loop_on", sec=interval)

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
        self._say("action", "scenarios.loop_off")

    # -- timers tab (scheduled repeats of an action) ------------------------

    def _build_timers_tab(self, parent: ttk.Frame) -> None:
        """One row per configured errand: switch, period, when it last/next runs.

        The Scenarios tab's «Повтор» repeats *one selected* action for as long as
        the panel is open; a timer is the other half — several errands, each on
        its own clock, remembered across restarts (panel/timers.py). Nothing here
        drives the game directly: a row only edits the settings the scheduler
        thread reads on its next tick.

        The list belongs to the active profile's timers.json — every account keeps
        its own set — but it is EDITED HERE: add a row, copy one, delete one, or
        open one and change its steps, its args and its title. That is what makes
        "play the session" a thing the panel can do at all: the daily list is one
        timer with ten steps and a period of an hour, and building it used to mean
        hand-editing JSON per account. «⟳» still re-reads the file for anything
        edited outside.
        """
        frame = self._tr(ttk.LabelFrame(parent, padding=8), "timers.frame")
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        # Rebuilt wholesale by _reload_timers, so the rows live in their own
        # frame with nothing else in it.
        self._timer_grid = ttk.Frame(frame)
        self._timer_grid.pack(fill="x")
        self._fill_timer_grid()

        # -- the editor's buttons ------------------------------------------------
        tools = ttk.Frame(frame)
        tools.pack(fill="x", pady=(10, 0))
        self._tr(ttk.Button(tools, command=self._timer_add),
                 "timers.add").pack(side="left", padx=(0, 4))
        self._tr(ttk.Button(tools, command=self._timer_edit),
                 "timers.edit").pack(side="left", padx=(0, 4))
        self._tr(ttk.Button(tools, command=self._timer_duplicate),
                 "timers.duplicate").pack(side="left", padx=(0, 4))
        self._tr(ttk.Button(tools, command=self._timer_delete),
                 "timers.delete").pack(side="left", padx=(0, 4))
        # The schedule's own master switch. «Стоп всё» stops the scheduler thread,
        # and without something that says so — and puts it back — the schedule would
        # be silently dead for the rest of the session.
        self._sched_var = tk.BooleanVar(value=True)
        self._tr(ttk.Checkbutton(tools, variable=self._sched_var,
                                 command=self._toggle_schedule),
                 "timers.scheduler").pack(side="right")

        # -- the Triggers section (panel/triggers.py) ----------------------------
        # A separate list below the timers: errands driven by a wire event, not a
        # clock. The alliance-help one answers «Помочь всем» the instant a request's
        # push lands. It is a standing order you switch on — no period, no editor — so
        # the section is just checkboxes, the event each listens for, and its status.
        trig_frame = self._tr(ttk.LabelFrame(frame, padding=8), "triggers.frame")
        trig_frame.pack(fill="x", pady=(10, 0))
        self._trigger_grid = ttk.Frame(trig_frame)
        self._trigger_grid.pack(fill="x")
        self._fill_trigger_grid()
        trig_bottom = ttk.Frame(trig_frame)
        trig_bottom.pack(fill="x", pady=(6, 0))
        self._tr(ttk.Label(trig_bottom, foreground="#888", wraplength=600,
                          justify="left"), "triggers.hint").pack(side="left", anchor="w")
        self._tr(ttk.Button(trig_bottom, width=3, command=self._reload_triggers),
                 "timers.reload").pack(side="right", anchor="ne")

        bottom = ttk.Frame(frame)
        bottom.pack(fill="x", pady=(8, 0))
        self._tr(ttk.Label(bottom, foreground="#888", wraplength=600, justify="left"),
                 "timers.hint").pack(side="left", anchor="w")
        self._tr(ttk.Button(bottom, width=3, command=self._reload_timers),
                 "timers.reload").pack(side="right", anchor="ne")

        self._refresh_timer_rows()

    # -- which row is selected ----------------------------------------------
    #
    # A grid of checkbuttons has no selection of its own, so the row label doubles
    # as one: clicking a row's name selects it and the four buttons act on that.
    def _select_timer(self, name: str) -> None:
        self._timer_selected = name
        self._paint_timer_selection()

    def _paint_timer_selection(self) -> None:
        for row_name, row in self._timer_rows.items():
            box = row.get("box")
            if box is None:
                continue
            try:
                box.configure(style="Selected.TCheckbutton"
                              if row_name == self._timer_selected else "TCheckbutton")
            except tk.TclError:
                pass

    def _selected_timer(self):
        """The selected timer, or ``None`` (with a log line saying to pick one)."""
        name = getattr(self, "_timer_selected", None)
        timer = self._timer_catalogue.by_name(name) if name else None
        if timer is None:
            self._say("timer", "timers.none_selected")
        return timer

    def _fill_timer_grid(self) -> None:
        """(Re)draw a row per timer in the current catalogue.

        Scheduled timers only — the wire-driven triggers are their own list, built
        below the timer grid by :meth:`_fill_trigger_grid` (panel/triggers.py).
        """
        grid = self._timer_grid
        for child in grid.winfo_children():
            child.destroy()
        self._timer_vars.clear()
        self._timer_rows.clear()
        grid.columnconfigure(0, weight=1)
        # «последняя попытка» stands where «последний запуск» used to: that column only
        # ever moved on a SUCCESS, so an errand failing every half hour read from here
        # as one nobody had switched on. It is the same reading, plus how it went — and
        # putting it in the old column's place keeps the row inside the window.
        for col, key in enumerate(("timers.col.action", "timers.col.interval",
                                   "timers.col.outcome", "timers.col.next")):
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
            # string; a timer added to the JSON without either shows the name it
            # was given there.
            if timer.title:
                box.configure(text=timer.title)
            elif timer.label_key:
                self._tr(box, timer.label_key)
            else:
                box.configure(text=timer.name)
            box.grid(row=row, column=0, sticky="w", pady=2)
            # The label is also the row's selection: a grid of checkbuttons has none
            # of its own, and the editor buttons need to know which row they act on.
            box.bind("<Button-1>", lambda _e, n=timer.name: self._select_timer(n),
                     add="+")
            box.bind("<Double-Button-1>", lambda _e, n=timer.name: (
                self._select_timer(n), self._timer_edit()), add="+")
            numeric_spinbox(grid, from_=timersmod.MIN_INTERVAL_SEC,
                        to=timersmod.MAX_INTERVAL_SEC, width=7,
                        textvariable=seconds).grid(row=row, column=1, sticky="w",
                                                   padx=(0, 10))
            outcome = ttk.Label(grid, foreground="#888", width=20)
            outcome.grid(row=row, column=2, sticky="w", padx=(0, 10))
            nxt = ttk.Label(grid, foreground="#888", width=18)
            nxt.grid(row=row, column=3, sticky="w", padx=(0, 10))
            self._tr(ttk.Button(grid, command=lambda t=timer: self._timer_run_now(t)),
                     "timers.run_now").grid(row=row, column=4, sticky="e")
            # A queued or running errand had no way back: «✕» takes it off the queue.
            self._tr(ttk.Button(grid, width=3,
                                command=lambda t=timer: self._timer_cancel(t)),
                     "timers.cancel").grid(row=row, column=5, sticky="e", padx=(4, 0))
            self._timer_rows[timer.name] = {"next": nxt, "outcome": outcome, "box": box}
        self._bind_timer_autosave()
        self._paint_timer_selection()

    # -- triggers: wire-driven errands, their own list (panel/triggers.py) ---
    def _fill_trigger_grid(self) -> None:
        """(Re)draw a checkbox row per trigger, below the timers.

        A trigger has no period and no editor: it is a standing order you switch on,
        and it answers on its own. So each row is just a switch, the event it listens
        for, and whether a listener is up right now.
        """
        grid = self._trigger_grid
        for child in grid.winfo_children():
            child.destroy()
        self._trigger_vars.clear()
        self._trigger_rows.clear()
        grid.columnconfigure(0, weight=1)
        for col, key in enumerate(("triggers.col.action", "triggers.col.event",
                                   "triggers.col.status")):
            self._tr(ttk.Label(grid, foreground="#888"), key).grid(
                row=0, column=col, sticky="w", padx=(0, 10), pady=(0, 4))
        for row, trig in enumerate(self._trigger_catalogue, start=1):
            enabled = tk.BooleanVar(value=bool(trig.enabled))
            self._trigger_vars[trig.name] = enabled
            box = ttk.Checkbutton(grid, variable=enabled)
            if trig.title:
                box.configure(text=trig.title)
            elif trig.label_key:
                self._tr(box, trig.label_key)
            else:
                box.configure(text=trig.name)
            box.grid(row=row, column=0, sticky="w", pady=2)
            # The wire event a listener waits for, or a short label for a poll check
            # (the raw Lua is unreadable in a narrow column).
            signal = trig.event_pattern if not trig.is_poll else self._t("triggers.poll")
            ttk.Label(grid, foreground="#888", text=signal).grid(
                row=row, column=1, sticky="w", padx=(0, 10))
            status = ttk.Label(grid, foreground="#888", width=14)
            status.grid(row=row, column=2, sticky="w", padx=(0, 10))
            self._trigger_rows[trig.name] = {"status": status}
        for var in self._trigger_vars.values():
            var.trace_add("write", lambda *a: self._save_triggers())

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

        Only those two: the scenario, the args and the title are the operator's text
        and travel through `_write_timer` instead, which writes a whole entry on
        purpose. A ticked box must never be able to rewrite a recipe.
        """
        if getattr(self, "_loading", False) or not self._timer_vars:
            return
        self._timer_catalogue = self._timer_catalogue.with_settings(self._timer_config())
        timersmod.save_catalogue(self._timer_catalogue, self._profiles.timers_json())

    def _save_triggers(self) -> None:
        """Write the ticked trigger boxes into the profile's triggers.json.

        A trigger's box just changed → save it and reconcile the listeners: the
        watcher brings the newly-on one's ear up and takes a newly-off one's down.
        """
        if getattr(self, "_loading", False) or not self._trigger_vars:
            return
        config = {name: {"enabled": bool(var.get())}
                  for name, var in self._trigger_vars.items()}
        self._trigger_catalogue = self._trigger_catalogue.with_enabled(config)
        triggersmod.save_catalogue(self._trigger_catalogue,
                                   self._profiles.triggers_json())
        self._triggers.sync()

    # -- add / copy / edit / delete a row ------------------------------------
    #
    # The one feature that makes the bot unattended used to be gated behind
    # hand-editing timers.json per account — the tab's own hint said so. The file
    # format always supported everything below; only the UI was missing.
    def _write_timer(self, catalogue) -> None:
        """Persist a whole catalogue and redraw the rows from it.

        The switches and periods on screen are folded in first: a row edited while
        another row's box was just ticked must not lose the tick.
        """
        self._timer_catalogue = catalogue.with_settings(self._timer_config())
        timersmod.save_catalogue(self._timer_catalogue, self._profiles.timers_json())
        self._fill_timer_grid()

    def _timer_add(self) -> None:
        """A new errand, empty, named for the operator to fill in."""
        name = self._timer_catalogue.unique_name("errand")
        draft = timersmod.Timer(name=name, scenario=("",),
                               interval_sec=timersmod.DEFAULT_INTERVAL_SEC,
                               enabled=False)
        self._edit_timer_dialog(draft, is_new=True)

    def _timer_duplicate(self) -> None:
        """A copy of the selected row under a free name.

        The name is the id the schedule keys its clock on, so the copy must not
        answer to the original's last-run record — `unique_name` is what guarantees
        that.
        """
        timer = self._selected_timer()
        if timer is None:
            return
        copy = timersmod.Timer(
            name=self._timer_catalogue.unique_name(timer.name),
            scenario=timer.scenario, interval_sec=timer.interval_sec,
            enabled=False,          # a copy starts off: two clocks on one errand is
                                    # rarely what a duplicate was for
            args=dict(timer.args),
            title=timer.title, label_key=None)
        self._write_timer(self._timer_catalogue.replace(copy))
        self._select_timer(copy.name)
        self._say("timer", "timers.log.duplicated",
                  name=timer.name, copy=copy.name)

    def _timer_delete(self) -> None:
        timer = self._selected_timer()
        if timer is None:
            return
        if not messagebox.askyesno(self._t("timers.delete"),
                                   self._t("timers.confirm_delete", name=timer.name),
                                   parent=self):
            return
        self._timer_selected = None
        self._write_timer(self._timer_catalogue.remove(timer.name))
        self._say("timer", "timers.log.deleted", name=timer.name)

    def _timer_edit(self) -> None:
        timer = self._selected_timer()
        if timer is not None:
            self._edit_timer_dialog(timer, is_new=False)

    def _edit_timer_dialog(self, timer, is_new: bool) -> None:
        """The row's whole entry, in a window: name, title, period, steps, args.

        Steps are one per line, because that is what a scenario is — «donate, then
        claim the gifts» is two lines — and a line is either the name of an action
        script or DSL source run as it stands (panel/timers.py says so too). The
        picker beside the box appends a script's name so the thirty-odd recipes do
        not have to be remembered.

        Nothing is written until Save, and Save refuses an entry the scheduler could
        not run: no name, a name already taken by another row, or no steps at all.
        """
        win = tk.Toplevel(self)
        win.title(self._t("timers.editor.window"))
        win.transient(self)
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        name_var = tk.StringVar(value=timer.name)
        title_var = tk.StringVar(value=timer.title or "")
        interval_var = tk.StringVar(value=str(timer.interval_sec))
        args_var = tk.StringVar(value=json.dumps(timer.args, ensure_ascii=False)
                                if timer.args else "")
        for row, (key, var, width) in enumerate((
                ("timers.editor.name", name_var, 28),
                ("timers.editor.title", title_var, 40),
                ("timers.editor.interval", interval_var, 10),
                ("timers.editor.args", args_var, 40))):
            self._tr(ttk.Label(frm), key).grid(row=row, column=0, sticky="w",
                                               padx=(0, 8), pady=3)
            # Only the interval is a number; name/title/args stay free text.
            entry_cls = (NumericEntry if key == "timers.editor.interval"
                         else ttk.Entry)
            entry_cls(frm, textvariable=var, width=width).grid(row=row, column=1,
                                                               sticky="we", pady=3)
        self._tr(ttk.Label(frm, foreground="#888", wraplength=460, justify="left"),
                 "timers.editor.steps_hint").grid(row=4, column=0, columnspan=2,
                                                  sticky="w", pady=(8, 2))
        steps = ScrolledText(frm, height=8, width=56, wrap="none", font=("Consolas", 9))
        steps.grid(row=5, column=0, columnspan=2, sticky="nsew")
        steps.insert("1.0", "\n".join(timer.scenario))
        frm.rowconfigure(5, weight=1)

        # The picker: every blessed action script, appended as a step.
        pick = ttk.Frame(frm)
        pick.grid(row=6, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self._tr(ttk.Label(pick), "timers.editor.pick").pack(side="left", padx=(0, 4))
        actions = list_actions()
        pick_var = tk.StringVar()
        pick_combo = ttk.Combobox(pick, textvariable=pick_var, state="readonly",
                                  width=34,
                                  values=[f"{a['name']} — {a['title']}" for a in actions])
        pick_combo.pack(side="left")

        def add_step() -> None:
            idx = pick_combo.current()
            if idx < 0:
                return
            text = steps.get("1.0", "end-1c")
            steps.insert("end", ("\n" if text.strip() else "") + actions[idx]["name"])

        self._tr(ttk.Button(pick, command=add_step),
                 "timers.editor.add_step").pack(side="left", padx=(4, 0))

        problem = ttk.Label(frm, foreground="#c33", wraplength=460, justify="left")
        problem.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def save() -> None:
            name = name_var.get().strip()
            if not name:
                problem.configure(text=self._t("timers.editor.err_name"))
                return
            clash = self._timer_catalogue.by_name(name)
            if clash is not None and name != timer.name:
                problem.configure(text=self._t("timers.editor.err_taken", name=name))
                return
            scenario = tuple(s.strip() for s in steps.get("1.0", "end-1c").splitlines()
                             if s.strip())
            if not scenario:
                problem.configure(text=self._t("timers.editor.err_steps"))
                return
            raw_args = args_var.get().strip()
            args: dict = {}
            if raw_args:
                try:
                    args = json.loads(raw_args)
                except ValueError as exc:
                    problem.configure(text=self._t("timers.editor.err_args", error=exc))
                    return
                if not isinstance(args, dict):
                    problem.configure(text=self._t("timers.editor.err_args",
                                                   error='expected {"name": value}'))
                    return
            # Keep the switch as it stands ON SCREEN, not as the catalogue last saw
            # it: a box ticked a second ago must survive an edit of the same row. A
            # brand-new errand starts off — one nobody has read yet should not fire a
            # minute later.
            row_var = self._timer_vars.get(timer.name)
            enabled = bool(row_var["enabled"].get()) if row_var else bool(timer.enabled)
            edited = timersmod.Timer(
                name=name, scenario=scenario,
                interval_sec=timersmod._as_interval(interval_var.get(),
                                                    timer.interval_sec),
                enabled=enabled,
                args=args, title=title_var.get().strip() or None,
                # The locale key belongs to the BUILT-IN entry of that name; a
                # renamed row is no longer that entry, and keeping it would show a
                # translated label over the wrong errand.
                label_key=timer.label_key if name == timer.name else None)
            catalogue = self._timer_catalogue
            if not is_new and name != timer.name:
                # A rename is a delete plus an add: the name is the record key, so
                # the row starts a fresh clock rather than inheriting the old one's.
                catalogue = catalogue.remove(timer.name)
            win.destroy()
            self._write_timer(catalogue.replace(edited))
            self._select_timer(name)
            self._say("timer", "timers.log.saved", name=name)

        btns = ttk.Frame(frm)
        btns.grid(row=8, column=0, columnspan=2, sticky="we", pady=(10, 0))
        ttk.Button(btns, text=self._t("timers.editor.cancel"),
                   command=win.destroy).pack(side="left")
        ttk.Button(btns, text=self._t("timers.editor.save"),
                   command=save).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())
        win.grab_set()

    # -- the schedule's master switch ---------------------------------------
    def _toggle_schedule(self) -> None:
        """Start or stop the scheduler thread from the tab.

        «Стоп всё» stops it, and without this the schedule would be silently dead
        for the rest of the session — the one failure mode of a panic button.
        """
        if self._sched_var.get():
            self._timers.start()
            self._triggers.start()      # the master switch governs both halves
            self._say("timer", "timers.log.scheduler_on")
        else:
            self._triggers.stop()
            self._timers.stop()
            self._say("timer", "timers.log.scheduler_off")

    def _timer_cancel(self, timer) -> None:
        """The row's «✕»: take a WAITING errand back off the queue.

        Three outcomes, and they must read differently: taken off, already running
        (the press is in flight and stopping it mid-call into the game is not on
        offer), and never queued in the first place.
        """
        if self._timers.cancel(timer.name):
            self._say("timer", "timers.log.cancelled", name=timer.name)
        elif timer.name in self._timers.pending():
            self._say("timer", "timers.log.already_running", name=timer.name)
        else:
            self._say("timer", "timers.log.not_queued", name=timer.name)

    def _reload_timers(self, quiet: bool = False) -> None:
        """Re-read the profile's timers.json and redraw the rows from it."""
        self._load_timer_catalogue()
        if hasattr(self, "_timer_grid"):
            self._fill_timer_grid()
        if not quiet:
            self._say("timer", "timers.log.reloaded", n=len(self._timer_catalogue))

    def _load_timer_catalogue(self) -> None:
        """Read the active profile's catalogue, reporting what it made no sense of.

        Seeded from the template on a profile that has none yet, so a new account
        starts with the same schedule and can then diverge freely.
        """
        path = self._profiles.timers_json()
        self._timer_catalogue = timersmod.load_profile_catalogue(path)
        for problem in self._timer_catalogue.errors:
            self._log_put(f"[timer] {_repo_rel(path)}: {problem}")

    # -- triggers: load, config, reload (panel/triggers.py) ------------------
    def _load_trigger_catalogue(self) -> None:
        """Read the active profile's trigger catalogue, reporting any junk in it.

        Seeded from the template panel/triggers.json on a profile that has none yet,
        exactly the way the timers are.
        """
        path = self._profiles.triggers_json()
        self._trigger_catalogue = triggersmod.load_profile_catalogue(path)
        for problem in self._trigger_catalogue.errors:
            self._log_put(f"[trigger] {_repo_rel(path)}: {problem}")

    def _trigger_config(self) -> dict:
        """Which triggers are switched on, read off the widgets (fresh every sync).

        Falls back to the catalogue's own switches while the UI is still being built
        (the watcher may sync before the rows exist).
        """
        if not self._trigger_vars:
            return self._trigger_catalogue.enabled_config()
        return {name: bool(var.get()) for name, var in self._trigger_vars.items()}

    def _reload_triggers(self, quiet: bool = False) -> None:
        """Re-read the profile's triggers.json, redraw the rows, reconcile listeners."""
        self._load_trigger_catalogue()
        self._migrate_autohelp()
        if hasattr(self, "_trigger_grid"):
            self._fill_trigger_grid()
        if getattr(self, "_triggers", None) is not None:
            self._triggers.sync()
        if not quiet:
            self._say("trigger", "triggers.log.reloaded", n=len(self._trigger_catalogue))

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
        running, _text = game_status(self._game_exe())
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
            # A UI refresh, not a game press: re-read the bag and repaint the
            # «Инвентарь» tab. Handled before the daemon gate — the tab's own read
            # degrades gracefully, so a missing daemon must not fault the trigger.
            if getattr(timer, "name", "") == "inventory_refresh":
                self.after(0, self._refresh_inventory_tab)
                return True
            # An alliancemate shared a secret task: re-merge the capture checkpoint so a
            # freshly-seen tile appears on the «Secret Tasks» tab without a manual
            # «Обновить». A UI refresh, not a game press — handled before the daemon gate,
            # the tab's own read degrades gracefully.
            if getattr(timer, "name", "") == "secret_task_share":
                self.after(0, self._refresh_secret_tasks_tab)
                return True
            if not self._daemon_up() and not self._ensure_daemon():
                raise RuntimeError(self._t("timers.log.no_daemon"))
            # The resource tracker is a Python handler, not a DSL scenario: on each
            # balance-changed push it reads the balance and tallies what went up.
            if getattr(timer, "name", "") == "resource_tracker":
                self._track_resources()
                return True
            # The leaderboard collector does all its work in its listener child
            # (a standing scan_leaderboard --sqlite), so a fire is a no-op here — the
            # arm-sweep submit must not try to run the placeholder scenario.
            if getattr(timer, "name", "") == "leaderboard_collect":
                return True
            # Rally auto-join is capped per monster type per day (panel/rally_limits.py).
            # Read the types out; if every one is at its cap, skip the whole join. `None`
            # = the types could not be read — let the join proceed, uncounted.
            join_types = None
            if getattr(timer, "name", "") == "rally_auto_join":
                join_types = self._rally_join_gate()
                if join_types is not None and not join_types:
                    return True                  # all types at their daily cap — no-op
            ctx = self._actions.context(
                hwnd=0,
                on_event=lambda msg: self._log_put(f"[timer] {timer.name}: {msg}"),
                variables=self._errand_args(timer),
            )
            for step in timer.scenario:
                if self._actions.resolve(step) is not None:
                    ok = self._actions.run(step, hwnd=0, ctx=ctx)
                else:
                    ok = self._actions.run_text(step, ctx=ctx,
                                                label=step.splitlines()[0])
                if not ok:
                    # The scenario's own FAIL reason when it left one. It is what the
                    # row's status column will show, and «the step did not work: X»
                    # tells the operator nothing they cannot already see in the name.
                    reason = str(getattr(ctx, "fail_reason", "") or "").strip()
                    raise RuntimeError(
                        reason or self._t("timers.log.step_failed", step=step))
            # The join ran clean — count what we let through, one per rally that was
            # out and under its cap (best-effort: join_rally joins all it can).
            if join_types:
                self._record_rally_joins(join_types)
            return True
        finally:
            self._release_busy()
            self.after(400, self._refresh_status)

    def _errand_args(self, errand) -> dict:
        """The variables a scenario runs with: the errand's own args, plus the few
        that must be read LIVE from the panel rather than stored on the errand.

        The «rally_auto_join» trigger is the one such case: which squads it joins with
        is the «Авторалли» page's own list (the JOIN squads, the same one the manual
        «Присоединиться» button and the rally-monitor auto-join use), and it must be
        able to change on the Settings page without editing the trigger. With no squad
        ticked the join is a clean no-op, so we say so and let it pass rather than fail.
        """
        args = dict(getattr(errand, "args", {}) or {})
        if getattr(errand, "name", "") == "rally_auto_join":
            squads = self._autorally_squads()
            if not squads:
                self._say("trigger", "triggers.log.no_squads")
            args["squads"] = squads
        return args

    # -- rally auto-join daily caps (panel/rally_limits.py) ------------------
    def _rally_types_out(self) -> list:
        """Best-effort monster-type key per rally currently out, read off the game.

        The push carries no type, so the rallies are read from the VM
        (WorldMarchDataManager) and each is classified by its target. Classification is
        BEST-EFFORT: the reliable headless signals for zombie-invasion vs alliance-drill
        vs a plain monster are not yet confirmed live, so every rally currently counts
        under the fallback type ('monster'). The Lua has the one spot to refine when a
        signal is known. Returns ``[]`` when the game / daemon cannot answer — the
        caller then lets the join proceed uncounted rather than blocking it.
        """
        if not self._daemon_up():
            return []
        chunk = (
            'local wm=DataCenter.WorldMarchDataManager local col=wm and wm:GetAllMarches() '
            'if not col then CS.UnityEngine.Debug.LogError("RTYPE end") return end '
            'local e=col:GetEnumerator() '
            'local function g(mo,k) local ok,v=pcall(function() return mo[k] end) '
            'if ok then return v end return nil end '
            'while e:MoveNext() do local mo=e.Current.Value if mo==nil then mo=e.Current end '
            'local team=g(mo,"teamUuid") local ts=tostring(team) '
            'if team~=nil and ts~="0" and ts~="nil" then local isL=false '
            'pcall(function() isL=(tostring(g(mo,"uuid"))==tostring(team-1)) end) '
            # One line per rally LEADER. `kind` is where a confirmed zombie/drill signal
            # would classify; until then every rally is the fallback monster type.
            'if isL then local kind="%s" '
            'CS.UnityEngine.Debug.LogError("RTYPE="..kind) end end end '
            'CS.UnityEngine.Debug.LogError("RTYPE end")' % rallylimitsmod.UNKNOWN_TYPE
        )
        try:
            ev = lua_client.get_evaluator(port=self._daemon_port())
            lines = ev.run(chunk, marker="RTYPE", settle=0.8)
        except Exception:                        # noqa: BLE001 — a bad read is not a cap
            return []
        out = []
        for ln in lines or []:
            if "RTYPE=" in ln:
                key = ln.split("RTYPE=", 1)[1].split()[0].strip()
                if key and key != "end":
                    out.append(key)
        return out

    def _rally_join_gate(self):
        """The rally types out that are still under their daily cap.

        ``None`` when the types could not be read (the join then proceeds uncounted);
        ``[]`` when every type out is at its cap (the caller skips the join); otherwise
        the eligible types, which are counted after a clean join.
        """
        types = self._rally_types_out()
        if not types:
            return None
        limits = rallylimitsmod.load_limits(self._profiles.rally_limits_json())
        counts = rallylimitsmod.load_counts(self._profiles.rally_counts_json())
        eligible = [t for t in types if counts.allowed(t, limits)]
        if not eligible:
            self._say("trigger", "triggers.log.rally_capped")
        return eligible

    def _record_rally_joins(self, types) -> None:
        """Count one join per eligible rally type, persisted for today."""
        path = self._profiles.rally_counts_json()
        counts = rallylimitsmod.load_counts(path)
        for t in types:
            counts = counts.record(t)
        rallylimitsmod.save_counts(counts, path)

    # -- resource tracker (panel/resource_stats.py) -------------------------
    def _read_resource_balance(self) -> dict:
        """The current resource balance off the game, in the tracker's keys.

        The balance is a flat dict on the wire (`init.resource`: money / metal / wood /
        petroleum / food …, docs/research/city-protocol.md); at runtime it is read
        through the daemon from `DataCenter.ResourceManager`. BEST-EFFORT: the exact
        getter is not confirmed live, so several plausible field/accessor shapes are
        tried and a resource that cannot be read is left out (never guessed). Returns
        ``{}`` when nothing readable — the caller then records no gain.
        """
        if not self._daemon_up():
            return {}
        # For each key, read the game field (gold=money, oil=petroleum) off a resource
        # object, trying `:GetXxx()` / `.xxx` / an index. `RB k=v …` on one line.
        chunk = (
            'local R = DataCenter.ResourceManager or DataCenter.ResourceItemDataManager '
            'local function bal(field) '
            'if not R then return nil end '
            'local ok, v = pcall(function() return R["Get"..field:sub(1,1):upper()..field:sub(2)](R) end) '
            'if ok and type(v)=="number" then return v end '
            'ok, v = pcall(function() return R[field] end) if ok and type(v)=="number" then return v end '
            'ok, v = pcall(function() return R.resource[field] end) '
            'if ok and type(v)=="number" then return v end return nil end '
            'local out = {} '
            'for _, p in ipairs({{"food","food"},{"wood","wood"},{"metal","metal"},'
            '{"oil","petroleum"},{"gold","money"}}) do '
            'local n = bal(p[2]) if n ~= nil then out[#out+1] = p[1].."="..tostring(math.floor(n)) end end '
            'CS.UnityEngine.Debug.LogError("RB "..table.concat(out, " "))'
        )
        try:
            ev = lua_client.get_evaluator(port=self._daemon_port())
            lines = ev.run(chunk, marker="RB", settle=0.6)
        except Exception:                        # noqa: BLE001 — a bad read is not a gain
            return {}
        out: dict = {}
        for ln in lines or []:
            if "RB " not in ln:
                continue
            for tok in ln.split("RB ", 1)[1].split():
                if "=" in tok:
                    key, _, val = tok.partition("=")
                    try:
                        out[key] = int(val)
                    except ValueError:
                        pass
        return out

    def _track_resources(self) -> None:
        """One balance-changed push: read the balance and tally what went up.

        The gain is `current - last` per resource (positive only): the push says a
        balance moved, not by how much, so the tracker diffs. The first read of a
        session is a baseline — no gain — because there is nothing to diff against.
        """
        current = self._read_resource_balance()
        if not current:
            return
        gains = resourcestatsmod.positive_deltas(current, self._resource_last)
        self._resource_last = current
        if not gains:
            return
        self._resource_stats = self._resource_stats.add(gains)
        resourcestatsmod.save_stats(self._resource_stats,
                                    self._profiles.resource_stats_json())
        self._say("trigger", "triggers.log.resource_gain",
                  what=", ".join(f"{k} +{v}" for k, v in gains.items()))
        if hasattr(self, "_stats_grid"):
            self.after(0, self._refresh_stats_table)

    def _refresh_inventory_tab(self) -> None:
        """A `push.resource.item.update` landed (the «inventory_refresh» trigger):
        re-read the bag so the «Инвентарь» tab's counts stay live. Only if it has
        been opened once — an unopened tab reads fresh when first shown anyway — and
        InventoryTab.refresh() coalesces a burst of pushes (it skips while busy) and
        keeps the current search filter, so this is a full-but-cheap repaint.
        """
        tab = getattr(self, "_inventory_tab", None)
        if tab is not None and getattr(tab, "_loaded", False):
            tab.refresh()

    def _refresh_secret_tasks_tab(self) -> None:
        """A share landed (the «secret_task_share» trigger): re-merge the capture
        checkpoint so a freshly-seen starred tile shows up on the «Secret Tasks» tab.
        Only once the tab has been opened — an unopened one reads fresh when first shown
        anyway — and the tab's own refresh coalesces a burst (it skips while busy) and
        only ADDS rows, so nothing on screen is lost.
        """
        tab = getattr(self, "_secret_tasks_tab", None)
        if tab is not None and getattr(tab, "_loaded", False):
            tab.refresh()

    def _on_main_tab_changed(self, _event=None) -> None:
        """Lazy-load the Alliance / Profile / Inventory tabs the first time each is
        opened — their data reads the live game, so nothing runs until it is shown."""
        nb = getattr(self, "_main_nb", None)
        if nb is None:
            return
        try:
            current = str(nb.select())
        except tk.TclError:
            return
        tab = getattr(self, "_lazy_tabs", {}).get(current)
        if tab is not None:
            tab.ensure_loaded()

    # -- statistics tab: resources gained per day ---------------------------
    def _build_stats_tab(self, parent) -> None:
        """A table of resources gained per day (panel/resource_stats.py).

        Filled by the «resource_tracker» trigger — one row per day, newest first, a
        column per resource. Nothing here drives the game; it reads the profile's tally.
        """
        frame = self._tr(ttk.LabelFrame(parent, padding=8), "stats.frame")
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        self._stats_grid = ttk.Frame(frame)
        self._stats_grid.pack(fill="x")
        self._tr(ttk.Label(frame, foreground="#888", wraplength=620, justify="left"),
                 "stats.hint").pack(anchor="w", pady=(8, 0))
        self._refresh_stats_table()

    def _refresh_stats_table(self) -> None:
        """Redraw the per-day resource table from the profile's tally."""
        grid = getattr(self, "_stats_grid", None)
        if grid is None:
            return
        for child in grid.winfo_children():
            child.destroy()
        self._tr(ttk.Label(grid, foreground="#888"), "stats.col.date").grid(
            row=0, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
        for col, key in enumerate(resourcestatsmod.RESOURCES, start=1):
            self._tr(ttk.Label(grid, foreground="#888"), f"stats.res.{key}").grid(
                row=0, column=col, sticky="e", padx=(0, 10), pady=(0, 4))
        dates = self._resource_stats.dates()
        if not dates:
            self._tr(ttk.Label(grid, foreground="#888"), "stats.empty").grid(
                row=1, column=0, columnspan=len(resourcestatsmod.RESOURCES) + 1,
                sticky="w", pady=4)
            return
        for r, date in enumerate(dates, start=1):
            ttk.Label(grid, text=date).grid(row=r, column=0, sticky="w",
                                           padx=(0, 14), pady=1)
            row = self._resource_stats.on(date)
            for col, key in enumerate(resourcestatsmod.RESOURCES, start=1):
                ttk.Label(grid, text=f"{row[key]:,}").grid(
                    row=r, column=col, sticky="e", padx=(0, 10))

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
            self._say("timer", "timers.log.already_queued", name=timer.name)

    def _refresh_timer_rows(self) -> None:
        """Repaint the "last attempt / next run" columns (and the trigger status); re-armed once a second."""
        if self._timer_rows:
            config = self._timer_config()
            records = self._timer_store.records()
            # What is waiting on the schedule's own queue. It was never shown, so an
            # errand queued behind a slow one looked like nothing had happened.
            pending = self._timers.pending()
            now = time.time()
            for timer in self._timer_catalogue:
                row = self._timer_rows.get(timer.name)
                if row is None:
                    continue
                self._paint_timer_outcome(row, timer.name, records, now)
                due = self._timer_catalogue.next_due(timer, config, records)
                if timer.name in pending:
                    row["next"].configure(text=self._t("timers.queued"))
                elif due is None:
                    row["next"].configure(text=self._t("timers.off"))
                elif due <= now:
                    row["next"].configure(text=self._t("timers.due_now"))
                else:
                    row["next"].configure(
                        text=self._t("timers.in_span", span=self._fmt_span(due - now)))
        self._refresh_trigger_rows()
        self._arm("timer_rows", 1000, self._refresh_timer_rows)

    def _paint_timer_outcome(self, row: dict, name: str, records: dict,
                             now: float) -> None:
        """Say how the last attempt ended — succeeded, failed, or never ran.

        Green / red / grey rather than a word alone: the one thing an operator wants off
        this tab at a glance is whether the schedule is getting anywhere, and an errand
        that fails on a standing condition (the ministry one, while another post is
        held) would otherwise be indistinguishable from one that keeps succeeding — both
        leave the row looking idle between fires.

        *Why* it failed is not here: the reason is a sentence, the column is twenty
        characters, and a label that grows to fit one would push the row's buttons off a
        760-wide window. It goes to the log instead, where the failure is already
        announced (``timers.log.failed``) — carrying the scenario's own FAIL reason
        since :meth:`_run_timer_action` started passing it up.
        """
        label = row.get("outcome")
        if label is None:
            return
        state, when = timersmod.last_attempt(records, name)
        if state == timersmod.ATTEMPT_FAILED:
            text = self._t("timers.outcome.failed", ago=self._fmt_span(now - when))
            colour = "#c0392b"
        elif state == timersmod.ATTEMPT_OK:
            text = self._t("timers.outcome.ok", ago=self._fmt_span(now - when))
            colour = "#2e7d32"
        else:
            text = self._t("timers.outcome.never")
            colour = "#888"
        label.configure(text=text, foreground=colour)

    def _refresh_trigger_rows(self) -> None:
        """Repaint each trigger's status: queued / listening / off."""
        if not self._trigger_rows:
            return
        pending = self._timers.pending()
        watching = self._triggers.watching()
        for trig in self._trigger_catalogue:
            row = self._trigger_rows.get(trig.name)
            if row is None:
                continue
            if trig.name in pending:
                row["status"].configure(text=self._t("timers.queued"))
            elif trig.name in watching:
                row["status"].configure(text=self._t("triggers.listening"))
            else:
                row["status"].configure(text=self._t("triggers.off"))

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
            self._hook(
                lambda nb=sub_nb, f=frame, k=key: nb.tab(f, text=self._t(f"settings.tab.{k}")),
                key=f"settings-tab-{key}",
            )
            fill = getattr(self, builder) if builder else None
            if fill is None:
                self._tr(ttk.Label(frame, foreground="#888"),
                         "settings.placeholder").pack(anchor="w")
            else:
                fill(frame)

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

    # -- settings: auto-rally -----------------------------------------------

    def _build_autorally_settings(self, parent: ttk.Frame) -> None:
        """Which squads may be sent to a rally, and the alliance-drill variant.

        Two independent things share the page because they are the same decision
        asked twice. An ordinary rally only needs "which squads may go" — four
        plain checkboxes, saved as the list `[1, 3]`. The drill also needs to know
        WHO raises the banner, so each squad there has three states instead of two
        (out / in / in and leading) and only one of them can be the leader.

        Everything is written to the active profile the moment it changes, and the
        `squads` list IS what the rally recipe is handed: «Присоединиться» on the main
        tab, and the auto-join that fires on the alert, both pass it as
        `actions/join_rally.md`'s `squads` argument (`_join_rally_now`). With no squad
        ticked the join refuses rather than being a no-op that looks like a success.
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

        # -- creating a rally ----------------------------------------------------
        #
        # Two decisions: which single squad raises the banner (creates the rally),
        # and what elite level the rally is against. The creator is a banner, so at
        # most one squad carries it — the squad buttons toggle blank <-> 🚩 and
        # picking one clears any other, the same one-banner rule the drill enforces.
        create = self._tr(ttk.LabelFrame(parent, padding=8), "autorally.create.frame")
        create.pack(fill="x", pady=(10, 0))
        crow = ttk.Frame(create)
        crow.pack(fill="x")
        self._tr(ttk.Label(crow), "autorally.create.squads").pack(side="left", padx=(0, 6))
        self._create_flagship: int | None = None
        self._create_buttons: dict[int, ttk.Button] = {}
        for squad in RALLY_SQUADS:
            btn = ttk.Button(crow, width=5,
                            command=lambda s=squad: self._cycle_create_squad(s))
            btn.pack(side="left", padx=3)
            self._create_buttons[squad] = btn

        erow = ttk.Frame(create)
        erow.pack(fill="x", pady=(6, 0))
        self._tr(ttk.Label(erow), "autorally.create.elite").pack(side="left", padx=(0, 6))
        self._create_elite_var = tk.StringVar(value=str(RALLY_ELITE_MIN))
        numeric_spinbox(erow, from_=RALLY_ELITE_MIN, to=RALLY_ELITE_MAX, width=5,
                    textvariable=self._create_elite_var).pack(side="left")
        self._tr(ttk.Label(create, foreground="#888", wraplength=620, justify="left"),
                 "autorally.create.hint").pack(anchor="w", pady=(6, 0))
        self._paint_create_squads()

        # -- daily caps per monster type (panel/rally_limits.py) -----------------
        #
        # A cap on how many rallies of each type the auto-join spends in a day: a
        # squad sent is a squad that cannot go elsewhere for the march. One editable
        # number per monster type, 0 = no cap. The list of types is the caps file's
        # own keys (seeded from the built-ins), so adding a type is a data change, not
        # a code one. The count itself resets daily (panel/rally_limits.py).
        limits_frame = self._tr(ttk.LabelFrame(parent, padding=8), "rally_limit.frame")
        limits_frame.pack(fill="x", pady=(10, 0))
        self._rally_limits = rallylimitsmod.load_limits(self._profiles.rally_limits_json())
        self._rally_limit_vars: dict = {}
        lgrid = ttk.Frame(limits_frame)
        lgrid.pack(fill="x")
        for r, key in enumerate(self._rally_limits.types()):
            self._tr(ttk.Label(lgrid), f"rally_limit.type.{key}").grid(
                row=r, column=0, sticky="w", padx=(0, 10), pady=2)
            var = tk.StringVar(value=str(self._rally_limits.limit_for(key)))
            self._rally_limit_vars[key] = var
            numeric_spinbox(lgrid, from_=0, to=999, width=6,
                            textvariable=var).grid(row=r, column=1, sticky="w")
            var.trace_add("write", lambda *a: self._save_rally_limits())
        self._tr(ttk.Label(limits_frame, foreground="#888", wraplength=620,
                          justify="left"), "rally_limit.hint").pack(anchor="w", pady=(6, 0))

    def _save_rally_limits(self) -> None:
        """Persist the edited per-type caps to the profile's rally_limits.json."""
        if getattr(self, "_loading", False) or not getattr(self, "_rally_limit_vars", None):
            return
        limits = self._rally_limits
        for key, var in self._rally_limit_vars.items():
            limits = limits.with_limit(key, var.get())
        self._rally_limits = limits
        rallylimitsmod.save_limits(limits, self._profiles.rally_limits_json())

    def _reload_rally_limits_ui(self) -> None:
        """Re-read the active profile's caps into the fields (on a profile switch).

        The caps live in their own per-profile file, not in the settings blob, so a
        switch has to re-read them; done inside the `_loading` guard so setting the
        fields does not write them straight back.
        """
        if not getattr(self, "_rally_limit_vars", None):
            return
        self._rally_limits = rallylimitsmod.load_limits(self._profiles.rally_limits_json())
        for key, var in self._rally_limit_vars.items():
            var.set(str(self._rally_limits.limit_for(key)))

    def _cycle_create_squad(self, squad: int) -> None:
        """Toggle the banner between blank and this squad — only one may carry it."""
        self._create_flagship = None if self._create_flagship == squad else squad
        self._paint_create_squads()
        self._save_settings()

    def _paint_create_squads(self) -> None:
        """Redraw the creator buttons: the flagship shows 🚩, the rest blank."""
        for squad, btn in getattr(self, "_create_buttons", {}).items():
            mark = "🚩" if self._create_flagship == squad else " "
            try:
                btn.configure(text=f"{squad} {mark}")
            except tk.TclError:
                pass

    def _create_elite_level(self) -> int:
        """The chosen elite level, clamped to the allowed range (bad input -> min)."""
        try:
            level = int(self._create_elite_var.get())
        except (TypeError, ValueError):
            return RALLY_ELITE_MIN
        return max(RALLY_ELITE_MIN, min(RALLY_ELITE_MAX, level))

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
            "create": {
                "flagship": self._create_flagship,
                "elite_level": self._create_elite_level(),
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

        create = raw.get("create")
        create = create if isinstance(create, dict) else {}
        creator = create.get("flagship")
        self._create_flagship = creator if creator in RALLY_SQUADS else None
        level = create.get("elite_level")
        if not isinstance(level, int) or not RALLY_ELITE_MIN <= level <= RALLY_ELITE_MAX:
            level = RALLY_ELITE_MIN
        self._create_elite_var.set(str(level))
        self._paint_create_squads()

    def _rally_tab_config(self) -> dict:
        """The «Ралли» tab's block for the profile (panel/tabs_extra.py RallyTab).

        A snapshot taken before the tab exists must not erase the saved block — the
        settings are collected on every save, and one taken during startup would
        otherwise write a default over the choices about to be restored.
        """
        return self._tab_config("_rally_tab", "rally_tab")

    def _command_post_config(self) -> dict:
        """The «Командный пункт» tab's block (panel/command_post.py CommandPostTab)."""
        return self._tab_config("_command_post_tab", "command_post")

    def _tab_config(self, attr: str, key: str) -> dict:
        """A tab's own settings block, or the saved one while the tab does not exist."""
        tab = getattr(self, attr, None)
        if tab is None:
            saved = getattr(self, "_settings", None) or {}
            block = saved.get(key)
            return block if isinstance(block, dict) else {}
        return tab.config()

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
