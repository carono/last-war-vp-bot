"""The «Настройки» tab — an aggregator, not a page.

Two halves. The SHELL's own knobs are here: which Python runs the children, which
daemon this profile drives, how big the log grows, the auto-loot budget, the game's
paths, the map-sweep box, the debug log. Their values and their defaults live in
`panel/runtime/settings.py`, so a knob is a line there, a row on a page below, and two
locale strings.

The other half is not here at all. Every tab that declares a `SETTINGS_PAGE_KEY`
contributes a page of its own, drawn by that tab — «Авторалли» belongs to «Ралли» and
travels with it, so switching rally off in the profile takes its settings away too
(docs/research/panel-tabs-refactor.md §6). That is what makes this an aggregator: it
knows how to hold pages, not what is on them.

A page that raises costs its page and not the panel: the notebook keeps going and the
log says which one broke.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from ..runtime import autostart as autostartmod
from .. import i18n as i18nmod
from .. import mapsweep as mapsweepmod
from .. import runtime
from ..runtime import diag
from ..widgets import numeric_spinbox
from .base import PanelTab

#: The shell's own sub-pages, in the order they appear. `builder` is the method that
#: fills one; `None` shows the placeholder, so the page is complete from the first day
#: and filling one in is writing its builder.
SHELL_PAGES: tuple = (
    ("general", "_build_general_settings"),
    ("game", "_build_game_settings"),
    ("tabs", "_build_tabs_settings"),
)


def _loadable(spec) -> bool:
    """Whether the registry can import this tab — a broken one still gets a row."""
    try:
        spec.load()
        return True
    except Exception:                        # noqa: BLE001 — a row, not the page
        return False


class SettingsTab(PanelTab):
    """The notebook of settings pages, the shell's own and the tabs'."""

    ID = "settings"
    TITLE_KEY = "tab.settings"
    ORDER = 40
    PREFERRED_SIZE = "820x640"
    LOCALE_NS = ("settings", "opt", "debug", "session", "autostart", "graphics")
    NEEDS = frozenset()

    # -- «Вкладки»: which of them this profile shows --------------------------
    def _build_tabs_settings(self, parent: ttk.Frame) -> None:
        """One row per tab in the registry: show it or not, and in what order.

        This is the page the whole refactor was for. A tab that is unticked here is not
        built at all on the next start — no widgets, no settings page of its own, no
        triggers offered, and none of its captures or watchers started. That last one is
        the part that costs: «Secret Tasks» switched off is a pcap child and two watcher
        threads that never run.

        WHY A RESTART. A tab brings up its own standing orders and hands the schedule
        its triggers when it is built; taking one down live would mean unwinding all of
        that in the right order with a capture mid-flight. The list is a profile
        setting, so it is written now and obeyed at the next start — said in as many
        words on the page, rather than left to be discovered.
        """
        from .. import tabs as tabsreg

        self.tr(ttk.Label(parent, foreground="#888", wraplength=620, justify="left"),
                "settings.tabs.hint").pack(anchor="w", pady=(0, 8))
        grid = ttk.Frame(parent)
        grid.pack(fill="x")

        saved = self.rt.settings.tab_list("enabled")
        shown = {spec.id for spec in tabsreg.resolve(
            enabled=saved, known=self.rt.settings.tab_list("known"))}
        self._tab_vars = {}
        for row, spec in enumerate(sorted(tabsreg.TABS, key=lambda s: s.order)):
            var = tk.BooleanVar(master=self.rt.root, value=spec.id in shown)
            self._tab_vars[spec.id] = var
            box = ttk.Checkbutton(grid, variable=var, command=self._save_tab_choice)
            self.tr(box, spec.title_key).grid(row=row, column=0, sticky="w", pady=1)
            # What the tab brings up when it is on, so the cost of each is readable.
            needs = ", ".join(sorted(spec.load().NEEDS)) if _loadable(spec) else "?"
            ttk.Label(grid, foreground="#888", text=needs).grid(
                row=row, column=1, sticky="w", padx=(14, 0))
        self._tabs_note = ttk.Label(parent, foreground="#e0a84f", wraplength=620,
                                    justify="left")
        self._tabs_note.pack(anchor="w", pady=(8, 0))

    def _save_tab_choice(self) -> None:
        """Write the ticked list into the profile, and say a restart is what applies it."""
        from .. import tabs as tabsreg

        enabled = [spec.id for spec in sorted(tabsreg.TABS, key=lambda s: s.order)
                   if self._tab_vars[spec.id].get()]
        values = self.rt.settings.values
        block = dict(values.get("tabs") or {})
        block["enabled"] = enabled
        block["known"] = [spec.id for spec in tabsreg.TABS]
        values["tabs"] = block
        self.rt.settings.save()
        try:
            self._tabs_note.configure(text=self.t("settings.tabs.restart"))
        except tk.TclError:
            pass

    def _sweep_box(self) -> tuple:
        """``(radius, step, dwell, rest)`` of the map sweep, all bounded.

        Read here only to describe the box in words under its knobs — the sweep itself
        reads its own (panel/tabs/secret_tasks/sweep.py), because a tab must not depend
        on another tab being present to know what it is doing.
        """
        opt = self.rt.settings
        return (
            opt.opt_int("sweep_radius", low=mapsweepmod.MIN_RADIUS,
                        high=mapsweepmod.MAX_RADIUS),
            opt.opt_int("sweep_step", low=mapsweepmod.MIN_STEP,
                        high=mapsweepmod.MAX_STEP),
            opt.opt_float("sweep_dwell", low=mapsweepmod.MIN_DWELL,
                          high=mapsweepmod.MAX_DWELL),
            opt.opt_int("sweep_rest_min", low=0, high=1440) * 60.0,
        )

    def build(self) -> None:
        """The Settings page: an aggregator, not a page.

        The shell's own sub-tabs come from SHELL_PAGES (a builder of None shows the
        placeholder), and then every plugin tab that declares a `SETTINGS_PAGE_KEY`
        contributes one of its own — so «Авторалли» is drawn by the rally tab, travels
        with it, and is simply not there when rally is switched off
        (docs/research/panel-tabs-refactor.md §6).
        """
        sub_nb = ttk.Notebook(self.parent)
        sub_nb.pack(fill="both", expand=True, padx=4, pady=4)

        pages = [(f"settings.tab.{key}", getattr(self, builder) if builder else None)
                 for key, builder in SHELL_PAGES]
        for tab in self.rt.tabs.live:
            if tab.SETTINGS_PAGE_KEY:
                pages.append((tab.SETTINGS_PAGE_KEY, tab.settings_page))

        for title_key, fill in pages:
            frame = ttk.Frame(sub_nb, padding=8)
            sub_nb.add(frame, text=self.t(title_key))
            self.rt.i18n.hook(
                lambda nb=sub_nb, f=frame, k=title_key: nb.tab(f, text=self.t(k)),
                key=f"settings-tab-{title_key}",
            )
            if fill is None:
                self.tr(ttk.Label(frame, foreground="#888"),
                         "settings.placeholder").pack(anchor="w")
                continue
            try:
                fill(frame)
            except Exception as exc:            # noqa: BLE001 — a page, not the panel
                # One line, translated. The raw English one that used to precede it said
                # the same thing in a language the panel may not be showing.
                self.say("panel", "log.tab.failed", tab=title_key, error=exc)

    # -- settings: the knobs that used to be constants in this file -----------
    #
    # Both tabs said "Скоро" while WIN_PYTHON, the auto-loot budget, the trace
    # filter, the game paths and the sweep box were all edit-the-source. Every row
    # below is one entry in runtime.DEFAULTS bound to its `_opt_vars` variable, so
    # a new knob is a line there plus a row here plus two locale strings.
    def _opt_row(self, parent: ttk.Frame, row: int, key: str, *,
                 width: int = 12, spin: "tuple | None" = None):
        """One labelled field on a Settings tab, bound to ``_opt_vars[key]``.

        Returns the control itself, for the rare knob that another one governs (the
        RDP login is meaningless while its checkbox is off).
        """
        self.tr(ttk.Label(parent), f"opt.{key}").grid(row=row, column=0, sticky="w",
                                                       padx=(0, 8), pady=3)
        var = self.rt.settings.vars[key]
        if isinstance(var, tk.BooleanVar):
            widget = ttk.Checkbutton(parent, variable=var)
            widget.grid(row=row, column=1, sticky="w")
        elif spin is not None:
            # A float knob (poll seconds, dwell, timeout) needs the decimal point;
            # an integer one stays digit-only.
            decimal = isinstance(runtime.DEFAULTS.get(key), float)
            widget = numeric_spinbox(parent, from_=spin[0], to=spin[1], width=width,
                                     decimal=decimal, textvariable=var)
            widget.grid(row=row, column=1, sticky="w")
        else:
            widget = ttk.Entry(parent, textvariable=var, width=width)
            widget.grid(row=row, column=1, sticky="we")
        self.tr(ttk.Label(parent, foreground="#888", wraplength=340, justify="left"),
                 f"opt.{key}.hint").grid(row=row, column=2, sticky="w", padx=(10, 0))
        return widget

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
        self._build_autostart_settings(parent)
        self._build_debug_log_settings(parent)

    # -- «Автозапуск»: the hourly task that opens the panel when it is not there --
    #
    # The tick is NOT a profile knob, and that is deliberate. What it shows is what the
    # Windows scheduler holds (panel/runtime/autostart.py `registered`), so a task somebody
    # removed by hand in taskschd.msc, or one this profile never had on this machine,
    # reads as off — where a saved boolean would confidently say «on» about a task that
    # is not there. Ticking it registers; unticking removes; both then re-read.
    def _build_autostart_settings(self, parent: ttk.Frame) -> None:
        """The box, what it registered, and what the last hourly look made of it."""
        frame = self.tr(ttk.LabelFrame(parent, padding=8), "autostart.frame")
        frame.pack(fill="x", pady=(12, 0))
        self._autostart_var = tk.BooleanVar(master=self.rt.root, value=False)
        box = ttk.Checkbutton(frame, variable=self._autostart_var,
                              command=self._toggle_autostart)
        self.tr(box, "autostart.enable").pack(anchor="w")
        self.tr(ttk.Label(frame, foreground="#888", wraplength=620, justify="left"),
                "autostart.hint").pack(anchor="w", pady=(4, 0))
        self._autostart_note = ttk.Label(frame, foreground="#888", wraplength=620,
                                         justify="left")
        self._autostart_note.pack(anchor="w", pady=(6, 0))
        self._refresh_autostart()

    def _toggle_autostart(self) -> None:
        """Register or remove this profile's task — and say why if Windows refused.

        The box snaps back to whatever the scheduler actually holds afterwards, so a
        refusal (no administrator rights, group policy, no `schtasks` at all) leaves a
        tick that tells the truth rather than one that merely remembers the click.
        """
        want = bool(self._autostart_var.get())
        try:
            autostartmod.set_enabled(self.rt.profiles, want)
        except RuntimeError as exc:
            said = i18nmod.translated(self.t, exc)
            messagebox.showerror(self.t("autostart.frame"), said)
            self.say("autostart", "log.autostart.failed", error=said)
        else:
            if want:
                # The task opens ONE panel with the whole set (#1207), so the set is what
                # the line names — «для профиля X» would be a promise it does not make.
                self.say("autostart", "log.autostart.on",
                         profiles=", ".join(autostartmod.open_set(self.rt.profiles)))
            else:
                self.say("autostart", "log.autostart.off")
        self._refresh_autostart()

    def _refresh_autostart(self) -> None:
        """Re-read the scheduler and the last verdict, and say both in one block.

        Whole sentences joined by a newline, never fragments glued together: the order
        of the pieces is not the same in every language, and each line here stands by
        itself in any of them.
        """
        note = getattr(self, "_autostart_note", None)
        if note is None:
            return
        info = autostartmod.status(self.rt.profiles)
        self._autostart_var.set(info.registered)
        lines = []
        if not info.supported:
            lines.append(self.t("autostart.state.unsupported"))
        elif info.registered:
            lines.append(self.t("autostart.state.on", task=info.task))
            # Which pages come up with it — the one thing a person cannot tell from the
            # task's name, now that the name has no profile in it (#1207).
            lines.append(self.t("autostart.state.profiles",
                                profiles=", ".join(info.profiles)))
            if not info.elevated:
                lines.append(self.t("autostart.state.limited"))
        else:
            lines.append(self.t("autostart.state.off"))
        lines.append(self._autostart_last(info.last))
        try:
            note.configure(text="\n".join(line for line in lines if line))
        except tk.TclError:
            pass

    def _autostart_last(self, last: dict) -> str:
        """One sentence about the last hourly look — a key per verdict, spelled out.

        Built as a `t(...)` per branch rather than `t(f"autostart.check.{state}")`: a key
        assembled at run time is one `tests/test_panel_i18n.py` cannot see, and a locale
        missing it shows the person the key itself.
        """
        state = str((last or {}).get("state") or "")
        if not state:
            return ""
        when = time.strftime("%d.%m %H:%M", time.localtime((last.get("ts") or 0)))
        if state == "running":
            return self.t("autostart.check.running", when=when)
        if state == "started":
            return self.t("autostart.check.started", when=when)
        if state == "restarted":
            return self.t("autostart.check.restarted", when=when)
        return self.t("autostart.check.failed", when=when,
                      error=last.get("error") or "")

    def on_language_change(self) -> None:
        """The two blocks the page words itself: the sweep hint and the autostart note.

        `tr` re-labels what it registered; a string built with `t` is not registered and
        would keep whatever language it was drawn in until the tab was rebuilt.
        """
        self._refresh_sweep_settings_hint()
        self._refresh_autostart()

    def _build_debug_log_settings(self, parent: ttk.Frame) -> None:
        """The technical debug log: the send target and «Отправить диагностику».

        The debug file is separate from panel.log and the UI widget — a developer
        diagnostic (panel/debug_log.py) that keeps every component's key events, every
        traceback and a systems snapshot, rotated at a fixed 5 MiB × 3. The only knob
        is where the zipped logs go; «Отправить диагностику» packs and hands them to
        `debug_send_url` (empty = do not send; a stub until a transport is wired).
        """
        frame = self.tr(ttk.LabelFrame(parent, padding=8), "debug.frame")
        frame.pack(fill="x", pady=(12, 0))
        frame.columnconfigure(2, weight=1)
        self._opt_row(frame, 0, "debug_send_url", width=34)
        self.tr(ttk.Button(frame, command=self._send_debug_archive),
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

        self._build_session_settings(parent)
        self._build_graphics_settings(parent)
        sweep = self.tr(ttk.LabelFrame(parent, padding=8), "sweep.frame")
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
            self.rt.settings.vars[key].trace_add(
                "write", lambda *a: self._refresh_sweep_settings_hint())
        self._refresh_sweep_settings_hint()

    def _build_session_settings(self, parent: ttk.Frame) -> None:
        """«Windows-сессия»: is this profile's client the one on this desktop?

        The second account does not live here. It runs in its own Windows session, owned
        by that session's own user (tools/rdp_instance.py), and the panel drives it over
        the daemon port on the «Общие» page. The port is only half the answer: everything
        that goes looking for the *process* — the status strip, the watchdog, the tabs
        that will not spend an errand on a client that is gone — finds a client by
        executable name, and both clients have the same name. Naming the session's login
        here is what tells them apart.
        """
        frame = self.tr(ttk.LabelFrame(parent, padding=8), "session.frame")
        frame.pack(fill="x", pady=(12, 0))
        frame.columnconfigure(2, weight=1)
        self._opt_row(frame, 0, "rdp_session")
        self._session_user_entry = self._opt_row(frame, 1, "rdp_user", width=20)

        # «Проверить»: the settings answer for themselves, here, rather than being
        # discovered at three in the morning as a profile that farmed nothing. The
        # reading itself is the runtime's (`game_process.check`); this half only puts
        # words to the verdict it comes back with.
        self._session_check_btn = self.tr(
            ttk.Button(frame, command=self._check_session), "session.check")
        self._session_check_btn.grid(row=2, column=1, sticky="w", pady=(8, 0))
        self._session_verdict = ttk.Label(frame, foreground="#888", wraplength=520,
                                          justify="left")
        self._session_verdict.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        # The port and the session are two halves of one answer, so the contradiction
        # between them is shown without waiting to be asked for.
        self._session_clash = ttk.Label(frame, foreground="#e0a84f", wraplength=520,
                                        justify="left")
        self._session_clash.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # The login is meaningless while the tick is off, and a box that still takes
        # typing says otherwise. Follow the checkbox — and the port — on every change.
        for key in ("rdp_session", "daemon_port"):
            self.rt.settings.vars[key].trace_add(
                "write", lambda *a: self._refresh_session_user_state())
        self._refresh_session_user_state()

    def _refresh_session_user_state(self) -> None:
        """Keep the login box and the port warning in step with the tick."""
        on = self.rt.settings.opt_bool("rdp_session")
        entry = getattr(self, "_session_user_entry", None)
        try:
            if entry is not None:
                entry.configure(state="normal" if on else "disabled")
            clash = getattr(self, "_session_clash", None)
            if clash is not None:
                gp = runtime.game_process
                # The cheap half of the check: three knobs, no Windows call, because
                # this runs on every keystroke in the port box.
                clash.configure(
                    text=self.t("session.clash",
                                port=self.rt.settings.opt_int("daemon_port", low=1,
                                                              high=65535),
                                user=gp.profile_user(self.rt.settings) or "")
                    if gp.port_clash(self.rt.settings) else "")
        except tk.TclError:
            pass

    #: What `game_process.check` can come back with, and how sure each verdict is.
    #: Green is "this profile will find its client"; anything else is a step the
    #: person still has to take, said in the words of the step rather than a code.
    _VERDICT_COLOURS = {"ok": "#3c3", "off": "#888", "no_client": "#e0a84f"}

    def _check_session(self) -> None:
        """Say what the session settings currently amount to, in one line."""
        try:
            verdict = runtime.game_process.check(self.rt.settings)
        except Exception as exc:                # noqa: BLE001 — a line, not the page
            verdict = {"kind": "probe_error", "error": exc}
        kind = verdict.get("kind", "probe_error")
        fmt = dict(verdict)
        fmt.pop("kind", None)
        if "state" in fmt:
            fmt["state"] = self._session_state_word(fmt["state"])
        # The verdict that names a button spells the button out of the SAME key the
        # button itself is drawn from, so the two can never drift into telling the
        # person to press something that is no longer written there.
        fmt["button"] = self.t("game.launch").strip("▶ ")
        try:
            self._session_verdict.configure(
                text=self.t(f"session.check.{kind}", **fmt),
                foreground=self._VERDICT_COLOURS.get(kind, "#c33"))
        except tk.TclError:
            pass
        self._refresh_session_user_state()

    def _session_state_word(self, state) -> str:
        """«активна» / «отключена» / the raw code for the states nobody has to know."""
        gp = runtime.game_process
        if state == gp.WTS_ACTIVE:
            return self.t("session.state.active")
        if state == gp.WTS_DISCONNECTED:
            return self.t("session.state.disconnected")
        return self.t("session.state.other", code=state)

    # -- «Качество графики» --------------------------------------------------
    #
    # It lives on «Игра», under «Windows-сессия», because that block is the one that
    # answers *which client this profile drives* — and how hard that client draws is a
    # property of it, not of the panel. The pairing is not decorative: the client that
    # most wants economising is the second account's, headless in a session nobody is
    # connected to, and that is the client the block above is there to name. «Главная»
    # was the other candidate and is the wrong one — it is a status strip, and a
    # remembered per-profile choice put there would need a second persistence path and
    # would end up written in two places.
    #
    # Nothing here knows what "economy" means to the game. The two settings below are
    # arguments to `actions/set_graphics_load.md`, which is where the ability lives, and
    # the reading comes back from `actions/read_graphics_load.md` (`CLAUDE.md`: the panel
    # plays scenarios, it does not write them).

    #: The economy profile, in the scenario's own arguments. Measured at −82 % of the
    #: video card with no cost to anything the bot does (docs/research/headless-gpu.md).
    LOW_GRAPHICS = {"fps": 10, "quality": 0, "width": 320, "height": 200}

    #: What to put back when nothing was ever remembered — the client's own shipped
    #: settings. Only reached for a profile that arrives already switched to economy,
    #: which cannot happen through this page but can through a hand-edited profile.
    STOCK_GRAPHICS = {"fps": 60, "quality": 2, "width": 1700, "height": 1065}

    def _build_graphics_settings(self, parent: ttk.Frame) -> None:
        """Two states — economy and the picture as the person had it — and what is on."""
        frame = self.tr(ttk.LabelFrame(parent, padding=8), "graphics.frame")
        frame.pack(fill="x", pady=(12, 0))
        frame.columnconfigure(2, weight=1)

        var = self.rt.settings.vars["graphics_mode"]
        row = ttk.Frame(frame)
        row.grid(row=0, column=0, columnspan=3, sticky="w")
        # `command` and not a trace on the variable: a trace also fires when a profile
        # is loaded into the widget, and the panel would drive the game every time
        # somebody switched profile. This way only a person's click applies anything.
        for column, mode in enumerate(("standard", "low")):
            self.tr(ttk.Radiobutton(row, variable=var, value=mode,
                                    command=lambda m=mode: self._apply_graphics(m)),
                    f"graphics.mode.{mode}").grid(row=0, column=column, sticky="w",
                                                  padx=(0, 16))

        self.tr(ttk.Label(frame, foreground="#888", wraplength=560, justify="left"),
                "graphics.hint").grid(row=1, column=0, columnspan=3, sticky="w",
                                      pady=(8, 0))

        # What the CLIENT says, not what the panel last asked for. The two part company
        # the moment the game restarts — it comes back at full quality without telling
        # anybody — and on this page the truth is the useful one.
        self._graphics_state = ttk.Label(frame, foreground="#888", wraplength=560,
                                         justify="left")
        self._graphics_state.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._graphics_refresh_btn = self.tr(
            ttk.Button(frame, command=self._read_graphics), "graphics.refresh")
        self._graphics_refresh_btn.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self._graphics_read_at = 0.0
        self._say_graphics("graphics.state.idle")

    #: How stale a reading may be before opening the page asks the client again. The
    #: read is five Lua round trips — cheap, but not free enough to spend every time
    #: somebody clicks through the Settings pages looking for something else.
    GRAPHICS_READ_TTL = 60.0

    def on_show(self) -> None:
        """Somebody is looking: refresh what the client says it is drawing.

        `on_show` and not `ensure_loaded` on purpose — this is a read that only feeds the
        screen, and putting it in `ensure_loaded` would spend it at every start-up for
        every profile whether or not anybody opens Settings (`docs/panel-tabs.md`).
        """
        if getattr(self, "_graphics_state", None) is None:
            return
        if time.time() - getattr(self, "_graphics_read_at", 0.0) < self.GRAPHICS_READ_TTL:
            return
        if not self.rt.game.up():
            self._say_graphics("graphics.state.offline",
                               mode=self._graphics_mode_word())
            return
        self._read_graphics()

    def _graphics_mode_word(self) -> str:
        """The mode this profile is set to, in the language on the screen."""
        return self.t(f"graphics.mode.{self.rt.settings.opt_str('graphics_mode')}")

    def _say_graphics(self, key: str, **fmt) -> None:
        label = getattr(self, "_graphics_state", None)
        if label is None:
            return
        try:
            label.configure(text=self.t(key, **fmt))
        except tk.TclError:
            pass

    def _graphics_args(self, mode: str) -> dict:
        """The arguments to hand the scenario for the mode being switched to."""
        if mode == "low":
            return dict(self.LOW_GRAPHICS)
        saved = self.rt.settings.opt_str("graphics_stock")
        parts = [p for p in saved.split("/") if p.strip()]
        if len(parts) == 5:
            try:
                fps, _vsync, quality, width, height = (int(float(p)) for p in parts)
                return {"fps": fps, "quality": quality, "width": width, "height": height}
            except ValueError:
                pass
        return dict(self.STOCK_GRAPHICS)

    def _apply_graphics(self, mode: str) -> None:
        """Switch the client, remembering the picture on the way out of standard."""
        if not self.rt.game.up():
            # The choice is still the profile's — it just cannot reach a client yet, and
            # saying "saved, not applied" beats a switch that silently did nothing.
            self._say_graphics("graphics.state.offline",
                               mode=self.t(f"graphics.mode.{mode}"))
            return
        if mode == "low" and not self.rt.settings.opt_str("graphics_stock"):
            # Remember what to come back to BEFORE changing it. Without this
            # «стандартное» would restore a guess rather than this person's picture.
            self._read_graphics(then=lambda: self._start_graphics(mode), remember=True)
            return
        self._start_graphics(mode)

    def _start_graphics(self, mode: str) -> None:
        self._say_graphics("graphics.state.applying",
                           mode=self.t(f"graphics.mode.{mode}"))
        # A refused claim means nothing was started and no callback will ever come, so
        # the «…» line has to be taken back here or it stays on screen for ever.
        if not self.rt.play_async("set_graphics_load", self._graphics_args(mode),
                                  tag="graphics",
                                  on_result=lambda out: self._graphics_done(out)):
            self._say_graphics("graphics.state.busy")

    def _graphics_done(self, outcome) -> None:
        if not outcome:
            self._say_graphics("graphics.state.failed",
                               reason=outcome.reason or self.t("graphics.state.noreason"))
            return
        self._read_graphics()

    def _read_graphics(self, then=None, remember: bool = False) -> None:
        """Ask the client what it is actually drawing, and say so."""
        if not self.rt.game.up():
            self._say_graphics("graphics.state.offline",
                               mode=self._graphics_mode_word())
            return
        self._say_graphics("graphics.state.reading")
        if not self.rt.play_async(
                "read_graphics_load", tag="graphics",
                on_result=lambda out: self._graphics_read(out, then, remember)):
            self._say_graphics("graphics.state.busy")

    def _graphics_read(self, outcome, then=None, remember: bool = False) -> None:
        values = dict(getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        try:
            fps, vsync, quality, width, height = (
                int(float(values[key]))
                for key in ("fps", "vsync", "quality", "width", "height"))
        except (KeyError, TypeError, ValueError):
            # A switch that was waiting on this still goes ahead: what could not be
            # remembered simply is not, and «стандартное» falls back to the client's own
            # shipped picture. Refusing to switch would leave the radio saying one thing
            # and the client doing another, which is worse than an approximate restore.
            self._say_graphics("graphics.state.unreadable")
            if then is not None:
                then()
            return
        # `remember` and not "are we in standard?": by the time a click reaches here the
        # radio has ALREADY moved to the mode being switched to, so asking the setting
        # would record the economy picture as the one to come back to. Only the one call
        # that runs before the switch is allowed to write it, and only once.
        if remember and not self.rt.settings.opt_str("graphics_stock"):
            self.rt.settings.vars["graphics_stock"].set(
                "/".join(str(v) for v in (fps, vsync, quality, width, height)))
        self._graphics_read_at = time.time()
        # vSync makes the frame cap a number the engine is ignoring, so the cap is only
        # quoted when it is actually in force; otherwise the display is what paces it.
        self._say_graphics(
            "graphics.state.now" if not vsync else "graphics.state.now_vsync",
            fps=fps, quality=self.t(f"graphics.quality.{min(max(quality, 0), 2)}"),
            width=width, height=height)
        if then is not None:
            then()

    def _refresh_sweep_settings_hint(self) -> None:
        hint = getattr(self, "_sweep_settings_hint", None)
        if hint is None:
            return
        radius, step, dwell, _rest = self._sweep_box()
        # A centre of (0, 0) would be clamped against the map edge and undercount, so
        # describe the box from a point well inside the map instead.
        jumps, seconds = mapsweepmod.describe(500, 500, radius, step, dwell)
        try:
            hint.configure(text=self.t("sweep.settings_hint", side=radius * 2 + 1,
                                        jumps=jumps, mins=max(1, int(seconds // 60))))
        except tk.TclError:
            pass


    def _send_debug_archive(self) -> None:
        """«Отправить диагностику»: the packing lives in the runtime.

        The shell's "send the log to the developer" dialog presses the same thing, and
        a routine two pages share belongs to neither of them (panel/runtime/diag.py).
        """
        diag.send_archive(self.rt)

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(SettingsTab))
