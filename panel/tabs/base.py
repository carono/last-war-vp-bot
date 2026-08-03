"""The tab contract, and the harness that runs one on its own.

A tab is built into a frame and knows nothing about the notebook around it. Everything
it needs comes from the runtime it is handed; everything the container needs to know
about it, it declares (docs/research/panel-tabs-refactor.md §3).

Every method has a no-op default, so a read-only tab implements `build`, `fetch` and
`render` and nothing else.

ONE HARD RULE: **`build()` must not touch the game.** A standalone tab has to open with
no daemon, no client and no network, so everything live goes in `ensure_loaded()`. The
contract test enforces it by building every tab against a cold runtime.
"""
from __future__ import annotations

import argparse


class TimerSpec:
    """A scheduled errand a tab brings with it (seeded into a profile that lacks it)."""

    def __init__(self, name: str, scenario, interval_sec: int,
                 retry_sec: int | None = None, enabled: bool = False) -> None:
        self.name, self.scenario = name, scenario
        self.interval_sec, self.retry_sec, self.enabled = interval_sec, retry_sec, enabled

    def as_entry(self) -> dict:
        out = {"name": self.name, "scenario": self.scenario,
               "interval_sec": self.interval_sec, "enabled": self.enabled}
        if self.retry_sec is not None:
            out["retry_sec"] = self.retry_sec
        return out


class TriggerSpec:
    """A wire-driven errand a tab brings with it.

    ``scenario`` names an actions/*.md and stays data. ``handler`` instead names a METHOD
    ON THE OWNING TAB — which is what replaces the sentinel scenario names
    (`__inventory_refresh__` and friends) an `if` in the runner dispatches today, and
    what makes a trigger belonging to a switched-off tab simply not be offered.
    """

    def __init__(self, name: str, event: str, scenario: str | None = None,
                 handler: str | None = None, enabled: bool = False,
                 needs_game: bool = False) -> None:
        self.name, self.event = name, event
        self.scenario, self.handler, self.enabled = scenario, handler, enabled
        # Whether the handler needs the client up. Most are a repaint off a file and
        # must run whether or not a daemon is reachable; one reads the game.
        self.needs_game = needs_game

    def as_entry(self) -> dict:
        return {"name": self.name, "event_pattern": self.event,
                "scenario": self.scenario or f"__{self.name}__",
                "enabled": self.enabled}


class PanelTab:
    """One tab of the control panel."""

    # -- identity -----------------------------------------------------------
    ID: str = ""
    TITLE_KEY: str = ""
    ORDER: int = 100
    DEFAULT_ENABLED: bool = True
    PREFERRED_SIZE: str = "760x600"
    #: Load at boot rather than the first time the tab is shown. For the tabs whose
    #: `ensure_loaded` starts something that has to be RUNNING (a capture listening for
    #: an event that will not wait for somebody to click the tab), not for the ones
    #: whose it is a read to draw.
    EAGER: bool = False

    # -- what it owns -------------------------------------------------------
    LOCALE_NS: tuple = ()
    SETTINGS: dict = {}
    LEGACY_KEYS: dict = {}
    TIMERS: tuple = ()
    TRIGGERS: tuple = ()
    NEEDS: frozenset = frozenset()

    # -- the settings page it contributes, if any ---------------------------
    SETTINGS_PAGE_KEY: str = ""

    def __init__(self, rt, parent) -> None:
        self.rt = rt
        self.parent = parent

    # -- construction -------------------------------------------------------
    def build(self) -> None:
        """Widgets only. MUST NOT touch the game — see the module docstring."""

    def settings_page(self, parent) -> None:
        """Draw this tab's page on the Settings tab (only if SETTINGS_PAGE_KEY is set)."""

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Bring up what this tab is FOR — once.

        Called at boot for an EAGER tab and on first show for every other, so it must
        be idempotent. What belongs here is what has to be RUNNING: a capture listening
        for an event that will not wait for a click. What does NOT belong here is a read
        that only feeds the screen — that is :meth:`on_show`, and putting it here makes
        every profile pay for it at start-up whether or not the tab is ever opened.
        """

    def on_show(self) -> None:
        """Somebody is looking at this tab now. The place for a read that draws.

        Called on every show, so a one-time seed gates itself on its own flag.
        """

    def on_hide(self) -> None:
        """The notebook moved to another tab."""
    def on_profile_switch(self) -> None: ...
    def on_language_change(self) -> None: ...
    def panic(self) -> None:
        """What «Стоп всё» has to stop here."""

    def shutdown(self) -> None:
        """The window is closing: children, listeners, subscriptions."""

    # -- persistence --------------------------------------------------------
    def config(self) -> dict:
        return {}

    def apply_config(self, raw: dict) -> None: ...

    def persist_vars(self) -> list:
        """Variables whose change means "save the profile now"."""
        return []

    # -- convenience, so a tab does not spell the runtime out every time ----
    def t(self, key: str, **fmt) -> str:
        return self.rt.t(key, **fmt)

    def tr(self, widget, key: str, option: str = "text", **fmt):
        return self.rt.tr(widget, key, option, **fmt)

    def say(self, tag: str, key: str, **fmt) -> None:
        self.rt.say(tag, key, **fmt)


# ---------------------------------------------------------------------------
# running one tab on its own
# ---------------------------------------------------------------------------

def _parse(argv, cls) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog=f"python -m panel.tabs.{cls.ID}",
        description=f"Run the panel's «{cls.ID}» tab on its own.")
    ap.add_argument("--profile", metavar="NAME", default=None,
                    help="which profile's settings and logs to use "
                         "(default: the saved active one; created if missing)")
    ap.add_argument("--lang", default=None, help="override the profile's language")
    ap.add_argument("--geometry", default=None,
                    help=f"window size (default: {cls.PREFERRED_SIZE})")
    ap.add_argument("--daemon-port", type=int, default=None,
                    help="drive this daemon for this run only (not written back)")
    ap.add_argument("--read-only", action="store_true",
                    help="build the tab but refuse every press that drives the game")
    return ap.parse_args(argv)


def run_tab(cls, argv=None) -> int:
    """Open a window with just ``cls`` in it. The same six steps the shell takes.

    There is no log pane: «Главная» keeps the log, in the container. The lines still go
    to the profile's panel.log and debug.log, and to this console.
    """
    import tkinter as tk
    from tkinter import ttk

    # NOTE: nothing here may import panel.__main__. `python -m panel` runs that file
    # AS `__main__`, so importing it from a tab re-executes the whole panel as a second
    # module — which is why the runtime exists and why this harness talks only to it.
    from ..runtime import host as hostmod

    args = _parse(argv, cls)
    root = tk.Tk()
    rt = hostmod.standalone(profile=args.profile, lang=args.lang,
                            port=args.daemon_port, root=root)
    rt.settings.register(cls.SETTINGS)
    root.title(f"{rt.t(cls.TITLE_KEY)} — {rt.profiles.active}")
    root.geometry(args.geometry or cls.PREFERRED_SIZE)

    frame = ttk.Frame(root)
    frame.pack(fill="both", expand=True)
    tab = cls(rt, frame)
    rt.tabs.add(tab)
    tab.build()
    rt.settings.loading = True          # an apply is not a change; do not save it back
    try:
        tab.apply_config(rt.settings.tab_config(cls.ID, cls.LEGACY_KEYS))
    finally:
        rt.settings.loading = False
    # A window holding one tab IS somebody looking at it, so it hears `on_show` exactly
    # as it would in the panel. A tab that draws part of itself on first show — the
    # duel's week does, because building it cost the page two and a half seconds
    # (#1211) — would otherwise come up empty here and nowhere else.
    tab.on_show()

    # A choice made in a standalone window belongs to the profile just as much as one
    # made in the shell — this is a tab of the panel, not a preview of it. Only THIS
    # tab's block is written (plus its legacy flat keys), so a window holding one tab
    # can never overwrite what the others are set to.
    def _persist() -> None:
        rt.settings.set_tab_config(cls.ID, tab.config(), cls.LEGACY_KEYS)
        rt.settings.save()

    rt.settings.on_change = _persist
    for var in tab.persist_vars():
        var.trace_add("write", lambda *_a: rt.settings.changed())

    def _close() -> None:
        try:
            tab.shutdown()
        finally:
            rt.shutdown()
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", _close)
    # A window holding one tab is a window where that tab is always the one on screen.
    rt.say("panel", "standalone.started", tab=rt.t(cls.TITLE_KEY),
           profile=rt.profiles.active)
    root.after(0, lambda: (tab.ensure_loaded(), tab.on_show()))
    root.mainloop()
    return 0
