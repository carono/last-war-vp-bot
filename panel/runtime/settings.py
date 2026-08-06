"""What a profile is set to, and the one place that answers it.

The panel keeps its settings in three hand-maintained lists — one that writes them, one
that applies them to widgets, one that traces them for auto-save — and a key dropped
from any of the three is a setting that silently stops persisting
(docs/research/panel-tabs-refactor.md §9.2). This is the value half of that, pulled out:
the saved dict, the widget variables, the typed readers with their bounds, and the
`loading` flag that stops an apply from saving itself back.

Three properties worth stating, because they are what the readers guarantee:

* **A widget beats the file, the file beats the default.** A knob being edited right now
  is the truth; a profile that has never opened the Settings page behaves exactly as the
  code's own constants say.
* **A half-typed box is never obeyed.** An empty «лимит краж» read as 0 would silently
  stop the auto-loot and a stray letter in the daemon port would aim the panel at
  nothing, so every typed reader falls back to the default and clamps.
* **Defaults arrive in pieces.** `register()` takes another block of them, which is how a
  tab will bring its own `SETTINGS` along as it moves out — the shell no longer has to
  know every knob in advance.

`tests/test_panel_profile_compat.py` pins what a pre-migration profile means, and was
written before any of this existed.
"""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk

import game_paths
import lua_client

from .. import mapsweep as mapsweepmod

# Where the Windows client and its launcher live by default. A profile may name
# another install (a second client in its own Windows session), which is the whole
# reason these are knobs and not constants any more — and the DEFAULT behind the knob
# is `tools/lib/game_paths.py`, so a machine with the game somewhere else is an
# environment variable rather than a source change.
#
# It had to become one answer rather than two: what stood here was
# `C:\Program Files\LastWar`, which is not where the game installs itself and not what
# `panel/__main__.py` said three hundred lines away. Nothing noticed for as long as the
# «launcher» setting was unread; `tools/game_locale.py` reads it to find the game's own
# locale tables, and #1218 made it reachable from a button.
MANAGED_PYTHON = game_paths.win_python()
GAME_DIR = game_paths.game_dir()


def _default_python() -> str:
    """The interpreter a child process is launched with when nothing says otherwise.

    `install.bat` puts Python 3.12 in `C:\\Python312` precisely so this answers
    itself. On a machine where 3.12 already lived somewhere else the installer
    reuses it, and then that path does not exist — so fall back to the panel's own
    interpreter, which by definition has the packages the children need. A windowed
    build has no console for a child's stdout to travel through, so its console twin
    is preferred when it is there.
    """
    if os.path.exists(MANAGED_PYTHON):
        return MANAGED_PYTHON
    exe = sys.executable or ""
    if os.path.basename(exe).lower() == "pythonw.exe":
        console = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(console):
            return console
    return exe or MANAGED_PYTHON


WIN_PYTHON = _default_python()

#: Every knob the Settings page owns, with the value a profile that has never been
#: there behaves by. A default here IS the old constant, so nothing changes for an
#: existing profile — and adding a knob is a line here, a row on a page, and two
#: locale strings.
#:
#: `daemon_port` is the one with teeth: a second client lives in its own Windows
#: session with its own daemon on its own port (tools/rdp_instance.py), so a profile
#: naming 47655 drives THAT client — the panel's own client and every child it
#: launches (they read LW_DAEMON_PORT from the environment). That is what turns "two
#: profiles" into "two accounts farmed at once".
DEFAULTS: dict = {
    "win_python": WIN_PYTHON,
    "daemon_port": lua_client.DEFAULT_PORT,
    "log_max_lines": 4000,
    "autoloot_limit": 5,
    "autoloot_poll": 2.0,
    "autoloot_pause_min": 30,
    "trace_filter": "SFS",
    "sniff_ready_timeout": 25.0,
    "launcher": game_paths.launcher(),
    "game_exe": game_paths.game_exe(),
    "watchdog": False,
    # …and `daemon_port`'s other half. The port says WHAT to talk to; these two say
    # WHERE the client is, which is a different question and the one the process probe
    # asks: a second account lives in its own Windows session (tools/rdp_instance.py),
    # and by executable name alone the panel would find the console session's client
    # and call it this profile's — reporting "running" over a client of its own that
    # died hours ago, and letting the watchdog start a third one here.
    # `rdp_user` is the login of the user logged on to that session; it means nothing
    # while `rdp_session` is off (panel/runtime/game_process.py reads the pair).
    "rdp_session": False,
    "rdp_user": "",
    # How hard this profile's client is asked to DRAW. The bot reads the game out of the
    # Lua VM and never looks at the picture, so a client left at the settings it ships
    # with spends a quarter of the video card on frames nobody sees — and a client in a
    # session nobody is connected to spends more than that, because vSync has no display
    # to pace it (docs/research/headless-gpu.md). "low" is the economy profile,
    # "standard" is the picture as the person had it.
    #
    # Per profile on purpose: the second account, headless in its own Windows session, is
    # exactly the one that should be economising while the client somebody is watching is
    # not. `graphics_stock` is bookkeeping rather than a knob — it remembers what the
    # picture WAS, the first time economy is switched on, so «стандартное» puts back that
    # person's settings and not a guess. `fps/vsync/quality/width/height`, slash-separated;
    # empty until economy has been switched on once.
    "graphics_mode": "standard",
    "graphics_stock": "",
    "sweep_radius": mapsweepmod.DEFAULT_RADIUS,
    "sweep_step": mapsweepmod.DEFAULT_STEP,
    "sweep_dwell": mapsweepmod.DEFAULT_DWELL,
    "sweep_rest_min": 5,           # pause between two full passes, minutes
    # Where «Отправить диагностику» ships the zipped debug logs (panel/debug_sender.py).
    # Empty = do not send: the archive is still written, but nothing leaves the box.
    "debug_send_url": "",
}


def _settings_var(master, default):
    """One Tk variable per Settings knob — a checkbox for a bool, a box for the rest."""
    return (tk.BooleanVar(master=master, value=bool(default)) if isinstance(default, bool)
            else tk.StringVar(master=master, value=str(default)))


class SettingsBinder:
    """The active profile's values: read, write, and the widgets bound to them."""

    def __init__(self, profiles, defaults: dict | None = None) -> None:
        self._profiles = profiles
        self.defaults: dict = dict(defaults or {})
        self._values: dict = {}
        self.vars: dict = {}         # knob key -> Tk variable, once widgets exist
        #: WHAT EVERY WIDGET CURRENTLY HOLDS, readable from any thread (#1226).
        #:
        #: `opt()` is the panel's most-read thing — the daemon port on every socket
        #: check, the interpreter on every child, the executable and the Windows session
        #: on every status poll — and it is read almost entirely from BACKGROUND
        #: threads: the scheduler, the status poll, the dashboard loop, an action, a
        #: tab's fetch. Reading a Tk variable from one of those is not a read: tkinter
        #: hands the call to the Tk thread and blocks until the event loop runs it, so
        #: each of them costs whatever the window is busy with, and the window pays an
        #: event for each. With four profiles open that is the panel's whole problem —
        #: every profile's background work queues up behind the one thread that draws
        #: all of them. And during the boot, when the main thread is not inside the
        #: event loop, the very same call raises «main thread is not in main loop» and
        #: killed the worker that made it.
        #:
        #: So the widgets' values are SHADOWED here by a trace that fires on the Tk
        #: thread whenever one is written, and a reader that is not the Tk thread reads
        #: this dict instead. Same answer, no Tk. The Tk thread itself still reads the
        #: variable directly — it is already there, and a value written and read inside
        #: one callback must not go through a trace that has not fired yet.
        self._live: dict = {}
        self._master = None          # what those variables hang off, for a late block
        self.loading = False         # suppresses auto-save while an apply is running
        # "Something bound changed — write the profile out." Set by whoever owns the
        # whole snapshot: the shell's `_save_settings`, or the standalone harness's
        # one-tab equivalent. A tab NEVER saves by itself; it says a choice moved and
        # the container decides what a profile looks like.
        self.on_change = None

    # -- the saved dict -----------------------------------------------------
    def load(self) -> dict:
        """Re-read the active profile. Returns the raw dict (the panel still holds one)."""
        self._values = self._profiles.load()
        return self._values

    @property
    def values(self) -> dict:
        return self._values

    @values.setter
    def values(self, raw: dict) -> None:
        self._values = raw

    def save(self, raw: dict | None = None) -> None:
        """Persist to the active profile — unless an apply is in flight."""
        if self.loading:
            return
        if raw is not None:
            self._values = raw
        self._profiles.save(self._values)

    def changed(self) -> None:
        """A bound control moved. Ask the container to persist — unless it is applying.

        This is what a tab's tri-state button calls: a Tk variable can be traced, a
        button whose state lives in a dict cannot, and both have to reach the profile
        the same way.
        """
        if self.loading or self.on_change is None:
            return
        self.on_change()

    # -- the knobs ----------------------------------------------------------
    def register(self, defaults: dict) -> None:
        """Add another block of defaults (a tab's own `SETTINGS`).

        A block that arrives after the variables were made gets its own — registering
        is what the standalone harness does with the tab's `SETTINGS`, and it happens
        after the runtime is built.
        """
        self.defaults.update(defaults)
        if self.vars and self._master is not None:
            self.create_vars(self._master)

    def create_vars(self, master, factory=None) -> dict:
        """Build one variable per default. ``factory(master, default) -> Tk variable``.

        Called before any tab is built, so a widget can bind to a knob's variable and
        two widgets showing the same knob can never disagree — the Main tab's watchdog
        checkbox and the Settings page's are literally the same variable.

        The runtime calls this for every window it builds, the shell's and a standalone
        tab's alike. It used to be the shell's own line, with the factory in
        `panel/__main__.py` where a tab cannot reach it: `python -m panel.tabs.settings`
        opened with «Общие» and «Игра» empty and a `'win_python'` in the log, because
        every row bound to a variable that was never made (#1191).
        """
        self._master = master
        make = factory or _settings_var
        for key, default in self.defaults.items():
            if key not in self.vars:
                self.vars[key] = make(master, self._initial(key, default))
                self._shadow(key)
        return self.vars

    def _initial(self, key: str, default):
        """What a knob's variable STARTS at: this profile's SAVED value, else the default.

        Not the bare default, and the difference is a class of bug rather than a
        cosmetic one. :meth:`opt` lets the widget beat the file — a knob being edited
        right now is the truth — so a variable made with the code's default IS the
        answer to every read of that knob until somebody applies the profile to the
        widgets, and the shell does that pages later, long after the runtime and its
        game link were built.

        What it cost: a profile whose client lives in another Windows session names a
        daemon port of its own (47655), and its link was built while the widget still
        said 47654. The port is re-read everywhere else, so the panel CLAIMED the game
        lease on one daemon and pressed the scenario into the other — every action of
        that profile came back «lease lost», `WAIT scene == city` never saw a scene, and
        the restart errand relaunched a perfectly healthy client every six minutes for
        two days (#1224).

        The TYPE stays the declared default's: a factory chooses the kind of variable
        from what it is handed, and a boolean knob saved as a string must not turn its
        checkbox into a text box.
        """
        if key not in self._values:
            return default
        raw = self._values[key]
        if raw is None:
            return default
        if isinstance(default, bool):
            if isinstance(raw, str):
                return raw.strip().lower() in ("1", "true", "yes", "on")
            return bool(raw)
        return raw

    def var(self, key):
        return self.vars.get(key)

    # -- the thread-safe shadow ---------------------------------------------
    def _shadow(self, key: str) -> None:
        """Mirror one knob's widget value into :attr:`_live`, now and on every write.

        The trace is what keeps the mirror honest, and it costs a dict store on the Tk
        thread per edit — against a blocking trip into Tcl for every background read,
        which is what it replaces. A variable that will not take a trace (a stand-in in
        a test, a Tk too old) simply has no mirror: :meth:`opt` then falls through to
        the saved value, which is what a runtime with no widgets at all already does.
        """
        var = self.vars.get(key)
        if var is None:
            return
        self._catch(key)
        try:
            var.trace_add("write", lambda *_a, k=key: self._catch(k))
        except Exception:            # noqa: BLE001 — no trace is a stale mirror, not a crash
            pass

    def _catch(self, key: str) -> None:
        """Read one variable and store it. Runs on whoever wrote it — the Tk thread."""
        var = self.vars.get(key)
        if var is None:
            return
        try:
            self._live[key] = var.get()
        except Exception:            # noqa: BLE001 — a half-typed box has no value yet
            self._live.pop(key, None)

    def refresh_live(self) -> None:
        """Re-read every variable into the shadow. Tk thread only.

        For the one case a trace cannot cover: a whole profile applied to the widgets at
        once, where something may have set a variable before its trace existed. Cheap
        (one Tcl read per knob) and called where the panel already touches all of them.
        """
        for key in list(self.vars):
            self._catch(key)

    # -- typed readers ------------------------------------------------------
    def opt(self, key: str):
        """The raw current value of a knob: the widget, else the file, else the default.

        A `BooleanVar` whose entry holds something that is not a boolean raises out of
        `.get()`, which is a half-typed field rather than a broken panel — fall through.

        SAFE FROM ANY THREAD, and free from all but one of them: only the Tk thread
        touches a Tk variable here, and everybody else reads the shadow that thread
        keeps (see :attr:`_live`). A background reader therefore never blocks on the
        window and never raises «main thread is not in main loop».
        """
        if self.vars:
            if threading.current_thread() is threading.main_thread():
                var = self.vars.get(key)
                if var is not None:
                    try:
                        return var.get()
                    except Exception:    # noqa: BLE001 — tk.TclError, without importing tk
                        pass
            elif key in self._live:
                return self._live[key]
        if key in self._values:
            return self._values[key]
        return self.defaults.get(key)

    def opt_int(self, key: str, low: int | None = None, high: int | None = None) -> int:
        default = int(self.defaults.get(key) or 0)
        try:
            value = int(float(str(self.opt(key)).strip()))
        except (TypeError, ValueError):
            value = default
        if low is not None:
            value = max(low, value)
        if high is not None:
            value = min(high, value)
        return value

    def opt_float(self, key: str, low: float | None = None,
                  high: float | None = None) -> float:
        default = float(self.defaults.get(key) or 0.0)
        try:
            value = float(str(self.opt(key)).strip().replace(",", "."))
        except (TypeError, ValueError):
            value = default
        if low is not None:
            value = max(low, value)
        if high is not None:
            value = min(high, value)
        return value

    def opt_str(self, key: str) -> str:
        raw = self.opt(key)
        text = str(raw).strip() if raw is not None else ""
        return text or str(self.defaults.get(key) or "")

    def opt_bool(self, key: str) -> bool:
        return bool(self.opt(key))

    # -- per-tab blocks -----------------------------------------------------
    #
    # The shape the profile grows as tabs become plugins (§5). Reading is available
    # now — writing follows the tabs themselves — and the legacy fallback is the whole
    # point: a profile that predates the block keeps every value it had, read from the
    # flat top level through the tab's own LEGACY_KEYS.
    def tab_config(self, tab_id: str, legacy: dict | None = None) -> dict:
        """One tab's saved block, or the legacy flat keys it was spelled with before.

        An EMPTY saved block does not count as "found" — a tab that has never been
        shown yet (`develop`, off by default) is autosaved as `{}` the first time any
        other tab's change writes the profile, and that `{}` must not shadow flat
        legacy keys a tab folded into it left behind (task #1240: `scenarios`'s
        `scenario_selected`/`scenario_args`/`scenario_interval` survive under
        `develop` this way, with no separate migration needed).
        """
        block = (self._values.get("tabs") or {}).get("config", {}).get(tab_id)
        if isinstance(block, dict) and block:
            return dict(block)
        out = {}
        for new_key, old_key in (legacy or {}).items():
            if old_key in self._values:
                out[new_key] = self._values[old_key]
        return out

    def set_tab_config(self, tab_id: str, block: dict, legacy: dict | None = None) -> None:
        """Write one tab's block — and, for one release, the flat keys it used to be.

        The dual write of §5 rule 2: a profile touched by the new panel still opens in
        the old one, which is what makes the migration reversible one tab at a time.
        It goes away in its own commit, not in a wave.
        """
        tabs = self._values.setdefault("tabs", {})
        tabs.setdefault("config", {})[tab_id] = block
        for new_key, old_key in (legacy or {}).items():
            if new_key in block:
                self._values[old_key] = block[new_key]

    #: An old tab id folded into another one — a profile written before the merge
    #: still names it in `tabs.enabled` / `tabs.known` / `tabs.order`, and without this
    #: the merge would look, to that profile, like the new tab was never asked for
    #: (task #1240: the standalone "Сценарии" tab became part of "Разработка").
    _TAB_ID_MERGES = {"scenarios": "develop"}

    def tab_list(self, key: str) -> "list | None":
        """``tabs.enabled`` / ``tabs.order`` / ``tabs.known``, or ``None`` if absent."""
        value = (self._values.get("tabs") or {}).get(key)
        if not isinstance(value, list):
            return None
        out = []
        for item in value:
            item = self._TAB_ID_MERGES.get(item, item)
            if item not in out:
                out.append(item)
        return out
