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

import lua_client

from .. import mapsweep as mapsweepmod

# Where the Windows client and its launcher live by default. A profile may name
# another install (a second client in its own Windows session), which is the whole
# reason these are knobs and not constants any more.
WIN_PYTHON = r"C:\Python312\python.exe"
GAME_DIR = r"C:\Program Files\LastWar"

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
    "launcher": os.path.join(GAME_DIR, "LastWarLauncher.exe"),
    "game_exe": "LastWar.exe",
    "watchdog": False,
    "sweep_radius": mapsweepmod.DEFAULT_RADIUS,
    "sweep_step": mapsweepmod.DEFAULT_STEP,
    "sweep_dwell": mapsweepmod.DEFAULT_DWELL,
    "sweep_rest_min": 5,           # pause between two full passes, minutes
    # Where «Отправить диагностику» ships the zipped debug logs (panel/debug_sender.py).
    # Empty = do not send: the archive is still written, but nothing leaves the box.
    "debug_send_url": "",
}


class SettingsBinder:
    """The active profile's values: read, write, and the widgets bound to them."""

    def __init__(self, profiles, defaults: dict | None = None) -> None:
        self._profiles = profiles
        self.defaults: dict = dict(defaults or {})
        self._values: dict = {}
        self.vars: dict = {}         # knob key -> Tk variable, once widgets exist
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
        """Add another block of defaults (a tab's own `SETTINGS`)."""
        self.defaults.update(defaults)

    def create_vars(self, master, factory) -> dict:
        """Build one variable per default. ``factory(default) -> Tk variable``.

        Called before any tab is built, so a widget can bind to a knob's variable and
        two widgets showing the same knob can never disagree — the Main tab's watchdog
        checkbox and the Settings page's are literally the same variable.
        """
        for key, default in self.defaults.items():
            if key not in self.vars:
                self.vars[key] = factory(master, default)
        return self.vars

    def var(self, key):
        return self.vars.get(key)

    # -- typed readers ------------------------------------------------------
    def opt(self, key: str):
        """The raw current value of a knob: the widget, else the file, else the default.

        A `BooleanVar` whose entry holds something that is not a boolean raises out of
        `.get()`, which is a half-typed field rather than a broken panel — fall through.
        """
        var = self.vars.get(key)
        if var is not None:
            try:
                return var.get()
            except Exception:            # noqa: BLE001 — tk.TclError, without importing tk
                pass
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
        """One tab's saved block, or the legacy flat keys it was spelled with before."""
        block = (self._values.get("tabs") or {}).get("config", {}).get(tab_id)
        if isinstance(block, dict):
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

    def tab_list(self, key: str) -> "list | None":
        """``tabs.enabled`` / ``tabs.order``, or ``None`` when the profile has neither."""
        value = (self._values.get("tabs") or {}).get(key)
        return list(value) if isinstance(value, list) else None
