"""The tab contract, and the harness that runs one on its own.

A tab is built into a frame and knows nothing about the notebook around it. Everything
it needs comes from the runtime it is handed; everything the container needs to know
about it, it declares (docs/research/panel-tabs-refactor.md §3).

Every method has a no-op default, so a read-only tab implements `build`, `fetch` and
`render` and nothing else.

ONE HARD RULE: **`build()` must not touch the game.** A standalone tab has to open with
no daemon, no client and no network, so everything live goes in `ensure_loaded()`. The
contract test enforces it by building every tab against a cold runtime.

AND ONE ABOUT WHEN IT RUNS: **`build()` happens the first time somebody looks at the
tab, not when the page is made** (`LAZY`, #1215). A profile's page is fifteen tabs and
the person is looking at one of them; the other fourteen used to be drawn — every
widget, every layout pass — before the window would answer a click. What that costs a
tab author is written under :attr:`PanelTab.LAZY`: whatever answers before anybody
looks (a saved block, a trigger, the phone's screen) is made in ``__init__``, and
``build()`` only draws.
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
    #: whose it is a read to draw. An EAGER tab is also BUILT at boot, because what it
    #: starts usually asks its own checkbox whether it is switched on.
    EAGER: bool = False
    #: Is this tab's `build()` allowed to wait until somebody looks at it? (#1215)
    #:
    #: **Yes, for every tab that has no reason otherwise** — which is why it is the
    #: default rather than something to opt into. A page is built when the panel opens
    #: and again the first time a profile is switched to, and building fifteen tabs
    #: there cost between one and a half and eight seconds of a window that answered
    #: nothing, for fourteen tabs nobody had asked to see.
    #:
    #: WHAT IT ASKS OF A TAB is that the tab is ANSWERABLE before it is drawn, because
    #: four things reach a tab that nobody has opened:
    #:
    #: * **its saved block.** The container hands it over with :meth:`restore` and asks
    #:   for it back with :meth:`stored_config`; an undrawn tab hands back exactly what
    #:   it was given, so a profile saved while a tab was never opened keeps its
    #:   settings. Anything `config()` reads that is NOT a widget — a plan, a set, a
    #:   catalogue — belongs in ``__init__``, and then it is right either way;
    #: * **a trigger it declared.** It fires on the wire whether or not anybody is
    #:   looking, so its handler must work with no widgets: keep the state in
    #:   ``__init__`` and guard the repaint (`stats.track` / `DataTab.refresh_live` are
    #:   the two that do it);
    #: * **the phone.** `web_view` / `web_press` come through the runtime, which BUILDS
    #:   the tab before asking it — the phone must not see less than the window;
    #: * **the lifecycle.** `panic`, `resume`, `on_profile_switch`, `on_language_change`
    #:   and `shutdown` are NOT called on an undrawn tab: it started nothing, holds
    #:   nothing, and reads what it needs when it is first shown.
    #:
    #: Set it to ``False`` only for a tab that must exist before it is looked at, and
    #: say beside it why. Nothing does today.
    LAZY: bool = True
    #: Is this tab STILL BEING WRITTEN? (#1273)
    #:
    #: A tab that says yes is not shown at all unless the profile is in DEVELOPMENT
    #: MODE — which is «Разработка» being switched on, and nothing else
    #: (`panel.tabs.DEV_TAB`). It is not built, so it draws nothing, offers no trigger,
    #: starts no capture and hands the phone no screen; its saved block is left exactly
    #: as it is, so a profile that had it ticked before loses nothing by it going quiet.
    #:
    #: **The mark belongs where the tab is declared**, beside `DEFAULT_ENABLED` and
    #: `WEB_SCREEN`, so that a half-finished tab is marked in the one file its author is
    #: already editing rather than in a list of names somewhere else.
    #:
    #: It comes OFF when the tab's abilities have been proven in the live game and said
    #: so in `docs/farming.md` / `docs/farming.ru.md` — that confirmation is the whole
    #: definition. `DEFAULT_ENABLED` decides what happens next: the tab appears for
    #: everybody on the following start unless it says otherwise.
    IN_DEVELOPMENT: bool = False

    # -- what it owns -------------------------------------------------------
    LOCALE_NS: tuple = ()
    SETTINGS: dict = {}
    LEGACY_KEYS: dict = {}
    TIMERS: tuple = ()
    TRIGGERS: tuple = ()
    NEEDS: frozenset = frozenset()

    # -- the settings page it contributes, if any ---------------------------
    SETTINGS_PAGE_KEY: str = ""

    #: Does this tab draw parts CONTRIBUTED BY OTHER TABS? Only «Настройки» does — it
    #: collects a page from every tab that declares a `SETTINGS_PAGE_KEY` above. Such a
    #: tab is built LAST (`panel.tabs.build_order`), whatever its `ORDER` puts it at in
    #: the tab bar, because it can only draw the tabs that already exist (#1237).
    AGGREGATES_TABS: bool = False

    # -- and what it looks like on a phone ----------------------------------
    #: Does this tab offer a screen to the web front-end (`panel/web/`)? A tab that
    #: says yes implements :meth:`web_view`, and the phone lists it under «Ещё».
    #:
    #: NOT every tab should. «Настройки» is paths, interpreters and ports — breaking a
    #: profile with one thumb is easier than fixing it from a bus; «Веб» is the door the
    #: person came in through and managing it from the far side is how you lock yourself
    #: out; «Develop» is two sniffers for working on the bot itself. Those three say no
    #: on purpose (docs/research/panel-web.md §4).
    WEB_SCREEN: bool = False

    def __init__(self, rt, parent) -> None:
        self.rt = rt
        self.parent = parent
        #: Has :meth:`build` run? The container asks before it hands this tab anything
        #: that would reach a widget (see :attr:`LAZY`).
        self._built = False
        #: The saved block this tab was handed while it was still undrawn, and what it
        #: hands back when the profile is written. ``None`` means «never handed one».
        self._saved_config = None

    # -- construction -------------------------------------------------------
    def build(self) -> None:
        """Widgets only. MUST NOT touch the game — see the module docstring."""

    @property
    def built(self) -> bool:
        """Have this tab's widgets been drawn yet? (:attr:`LAZY`)"""
        return self._built

    def realize(self) -> bool:
        """Draw the tab now if it is not drawn. ``True`` if this call is what drew it.

        ON THE TK THREAD, always — it makes widgets. The container calls it the first
        time the tab is shown, at boot for an `EAGER` one, and before it hands the tab
        to anything that needs a drawn one (the phone's screen, another tab asking
        `rt.tabs.get`). Idempotent, so nobody has to know who got there first.

        THE WHOLE OF IT RUNS WITH THE BINDER TOLD IT IS LOADING. Drawing a tab is not a
        person changing a setting, and neither is restoring one: a variable made and
        filled in here must not write the profile back. It mattered less when every tab
        was drawn during the page build, which was already inside the shell's own
        loading window — a tab drawn an hour later is not.
        """
        if self._built:
            return False
        self._built = True
        settings = getattr(self.rt, "settings", None)
        was = getattr(settings, "loading", False)
        if settings is not None:
            settings.loading = True
        try:
            self.build()
            if self._saved_config is not None:
                self.apply_config(self._saved_config)
        finally:
            if settings is not None:
                settings.loading = was
        return True

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
        """What a «hold still» has to stop here — **and nothing calls it today (#1393)**.

        «Стоп всё» used to run this on every built tab. It is two acts now — close the
        client, stop this profile's daemon — and everything else holds still as a
        CONSEQUENCE: with no daemon there is nothing for a timer, a trigger, the watchdog
        or the recovery to press through, and `panel/runtime/gate.py` turns that fact into
        «and so they do not try». Five switches to put back by hand became none to put
        back at all, which is the version of that promise that cannot be got wrong.

        The pair is kept because it is the right SHAPE for the day something asks a tab
        to hold still again, and `tests/test_panel_panic_resume.py` still pins it. Until
        then, overriding it is writing code nobody runs — do not reach for it, and do not
        wire the emergency button back into it.

        Whatever is switched off here should be REMEMBERED here too, so :meth:`resume`
        can put back what was actually on rather than everything the tab has. The tab
        owns its own switches, so the tab is the only place that snapshot can live
        without drifting from them.
        """

    def resume(self) -> None:
        """Undo this tab's :meth:`panic`, and nothing else — **also uncalled** (#1393).

        The half that was missing until #1262. «Стоп всё» is pressed when something has
        gone wrong, and the state it leaves — every monitor down, the schedule off —
        used to be undone by hand, tab by tab, from one line in the log that scrolled
        away. Seven hours of a dead client went past that way, with the panel running
        and nothing switched on.

        **Put back what was ON, not everything there is.** A tab whose watcher the
        person had deliberately left off must not find it running afterwards: «Включить
        обратно» is an undo, not a start-everything. A tab with nothing to restore
        leaves this alone.
        """

    def shutdown(self) -> None:
        """The window is closing: children, listeners, subscriptions."""

    # -- the phone's copy of this tab ---------------------------------------
    def web_view(self) -> "dict | None":
        """This tab as DATA, for the web front-end to draw. ``None`` = no screen.

        THE SHAPE, and it is deliberately small — the phone has one renderer and every
        screen is made of the same four things (`panel/web/static/app.js`)::

            {"cards": [
                {"title": "profile.balance",            # a LOCALE KEY
                 "rows":  [{"label": "res.food",        # a KEY …
                            "value": "1 234"}],         # … and DATA, never translated
                 "items": [{"text": "Иванов",           # data: a name, a number, a time
                            # …or `"label": "vsduel.drone_parts"` when the line IS a
                            # word of the panel's rather than something read off a game
                            "detail": "30 · 12 480 000",
                            "facts": [{"label": "secrettasks.col.level",
                                       "value": "12"}],   # KEY + DATA, side by side
                            "until": 1785776747.0,        # epoch: the phone counts down
                            "pill": "web.ui.queued",      # a KEY, or absent
                            "actions": [{"id": "join", "label": "rally.join"}]}],
                 "empty": "alliance.empty"}],           # a KEY, shown for no items
             "actions": [{"id": "refresh", "label": "tabx.refresh"}]}

        WHICH FIELDS ARE WORDS AND WHICH ARE DATA is fixed and not negotiable, because
        it is what keeps the eleven languages honest: `title`, `label`, `empty` and
        `pill` are **locale keys** and are said by the browser out of the panel's own
        table; `text`, `value` and `detail` are **data** — a player's name, a count, a
        clock — and are shown as they are. A sentence built here in Russian would reach
        a person who has the panel in Turkish and could never be reviewed beside its
        siblings (`CLAUDE.md`). `tests/test_panel_web_screens.py` fails on a `label`
        that is not a key.

        CHEAP, ALWAYS. This is called on the Tk thread whenever a phone opens the
        screen, so it returns what the tab ALREADY HAS. Reading the game belongs in
        the tab's own refresh, which the phone asks for by pressing «Обновить» — a
        phone in a pocket must not poll the game all day (docs/research/panel-web.md).
        """
        return None

    def web_press(self, action: str, args: dict) -> dict:
        """One press from the phone. ``{"ok": True}``, or ``{"error": "unknown"}``.

        The same rule as everywhere else in the panel: what it presses is a scenario
        (`rt.actions` / `rt.play_async`) or something the tab already does for its own
        button. A tab that drives the game by hand today (the secret tasks and the
        command post do, and it is written down as debt in `CLAUDE.md`) offers the
        phone the READING and not the press until that ability is a scenario — a second
        copy of the debt is not an improvement.

        THREE ANSWERS, AND ``unknown`` IS ONLY ONE OF THEM (#1331). ``{"ok": True}`` is
        «done or started», ``{"ok": False}`` is «refused» — add ``reason`` when the tab
        knows why, a locale key or the game's own words, and the phone shows it — and
        ``{"error": "unknown"}`` means THIS TAB HAS NO SUCH PRESS and answers a 404.
        Never use the last one for a press that was merely not carried out: the page
        draws it as «панель не знает такого нажатия», and telling somebody that about a
        press that worked is how a press gets made twice.

        It runs on the Tk thread, so it may read widgets; it need not be quick. A press
        that outlasts `panel/web/api.py::PRESS_TIMEOUT_SEC` is answered «принято, идёт»
        and goes on running — but everything slow inside it still sits on the thread that
        draws every open profile, so the work itself belongs on `rt.play_async`'s worker
        exactly as it does for the window's own button.
        """
        return {"error": "unknown"}

    # -- persistence --------------------------------------------------------
    def config(self) -> dict:
        return {}

    def apply_config(self, raw: dict) -> None: ...

    # -- persistence, the container's side ----------------------------------
    #
    # A tab implements the two above and nothing here. These are what the container
    # calls, and they are the whole of what makes `LAZY` safe: a tab nobody has opened
    # is handed its block and hands the same one back, so a save that happens while it
    # is undrawn writes what was on disk rather than a screenful of defaults.
    def restore(self, raw: dict) -> None:
        """Give the tab its saved block: applied now if drawn, kept for `realize` if not."""
        self._saved_config = dict(raw or {})
        if self._built:
            self.apply_config(self._saved_config)

    def stored_config(self) -> dict:
        """What the profile writes for this tab — its widgets, or the block it was given.

        THE UNDRAWN CASE IS THE ONE THAT MATTERS. `config()` reads widgets, and a tab
        with none answers with whatever its variables were born with; writing that would
        turn «this profile was saved while the tab was closed» into «this profile has no
        such settings». So an undrawn tab is a pass-through, and every setting it holds
        survives a run in which nobody opened it.
        """
        if self._built:
            return self.config()
        return dict(self._saved_config or {})

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

    def post(self, call) -> None:
        """Repaint from a background thread: hand ``call`` to the Tk thread.

        **The only way a tab may come back from a worker.** `self.rt.root.after(0, …)`
        looks like the same thing and is not: from a thread that is not the Tk one it
        makes two blocking trips into the Tcl interpreter and waits for the event loop,
        so a tab of ONE profile reporting a reading sits on the thread that draws all
        the others — which is what stopped the panel scaling past two profiles (#1226,
        panel/runtime/tick.py). It also cannot raise «main thread is not in main loop»,
        which is what killed a worker that finished during the boot.
        """
        self.rt.post(call)


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

    A LOG PANE ONLY IF THE TAB DRAWS ONE — «Разработка» does, since #1391. Every other
    tab says its lines into the profile's panel.log and debug.log and into this console,
    exactly as it did; what this harness owes them either way is the PUMP, because the
    drain is what writes panel.log and what keeps the queue from growing for ever.
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
    # A window holding one tab IS a window where that tab is being looked at, so it is
    # drawn straight away rather than lazily (`PanelTab.LAZY`). `realize` applies the
    # saved block as part of drawing, with the binder told an apply is not a change.
    tab.restore(rt.settings.tab_config(cls.ID, cls.LEGACY_KEYS))
    tab.realize()
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
        rt.settings.set_tab_config(cls.ID, tab.stored_config(), cls.LEGACY_KEYS)
        rt.settings.save()

    rt.settings.on_change = _persist
    for var in tab.persist_vars():
        var.trace_add("write", lambda *_a: rt.settings.changed())

    # The log spool, on the clock the shell keeps it on (panel/runtime/log_view.py).
    # It remembers the line, writes it to `panel.log` and hands it to a pane if the tab
    # drew one — so a window holding one tab leaves the same record a whole panel does.
    def _pump_log() -> None:
        try:
            rt.log_spool.pump(cap=rt.settings.opt_int("log_max_lines",
                                                      low=200, high=200000))
        except Exception:                # noqa: BLE001 — the log, never the window
            rt.dbg("log").error("log pump failed", exc_info=True)
        rt.tick.arm("log", 120, _pump_log)

    _pump_log()

    def _close() -> None:
        from ..runtime import tick as tickmod

        try:
            tab.shutdown()
        finally:
            rt.shutdown()
            # This window holds exactly one runtime, so it is also the only one
            # standing on the shared pump `rt.tick` armed — safe to stop it here
            # (see panel/runtime/tick.py::stop).
            tickmod.stop(root)
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", _close)
    # A window holding one tab is a window where that tab is always the one on screen.
    rt.say("panel", "standalone.started", tab=rt.t(cls.TITLE_KEY),
           profile=rt.profiles.active)
    root.after(0, lambda: (tab.ensure_loaded(), tab.on_show()))
    root.mainloop()
    return 0
