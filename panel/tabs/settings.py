"""The «Настройки» tab — an aggregator, not a page.

Two halves. The SHELL's own knobs are here: which Python runs the children, which
daemon this profile drives, how big the log grows, the auto-loot budget, the game's
paths, the debug log. Their values and their defaults live in
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

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from ..runtime import autostart as autostartmod
from .. import i18n as i18nmod
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
    # …and this is the tab that collects the others' pages, so it is filled after every
    # one of them however early it sits in the tab bar (`panel.tabs.build_order`, #1237).
    AGGREGATES_TABS = True

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

        AND WHAT IS NOT LISTED: a tab still being written has no row here unless
        «Разработка» is on (#1273). A box for a tab that cannot appear whatever it says
        would be a control that does nothing and explains nothing; the line under the
        list says where they went instead. Their saved state is carried through
        untouched — see :meth:`_save_tab_choice`.
        """
        from .. import tabs as tabsreg

        self.tr(ttk.Label(parent, foreground="#888", wraplength=620, justify="left"),
                "settings.tabs.hint").pack(anchor="w", pady=(0, 8))
        grid = ttk.Frame(parent)
        grid.pack(fill="x")

        saved = self.rt.settings.tab_list("enabled")
        known = self.rt.settings.tab_list("known")
        # What the PROFILE asks for, before the development gate — a tab hidden by the
        # gate keeps whatever answer it was given rather than reading as unticked.
        asked = set(tabsreg.chosen_ids(enabled=saved, known=known))
        listed = tabsreg.listed(enabled=saved, known=known)
        self._tab_vars = {}
        for row, spec in enumerate(listed):
            var = tk.BooleanVar(master=self.rt.root, value=spec.id in asked)
            self._tab_vars[spec.id] = var
            box = ttk.Checkbutton(grid, variable=var, command=self._save_tab_choice)
            self.tr(box, spec.title_key).grid(row=row, column=0, sticky="w", pady=1)
            # What the tab brings up when it is on, so the cost of each is readable.
            needs = ", ".join(sorted(spec.load().NEEDS)) if _loadable(spec) else "?"
            ttk.Label(grid, foreground="#888", text=needs).grid(
                row=row, column=1, sticky="w", padx=(14, 0))
        #: The tabs this page did NOT offer a row for, and whether the profile had asked
        #: for each. Written back exactly as it stands, so switching «Разработка» off
        #: does not silently untick everything it was hiding.
        self._tab_hidden = {spec.id: spec.id in asked for spec in tabsreg.TABS
                            if spec.id not in self._tab_vars}
        if self._tab_hidden:
            self.tr(ttk.Label(parent, foreground="#888", wraplength=620,
                              justify="left"),
                    "settings.tabs.in_development").pack(anchor="w", pady=(8, 0))
        self._tabs_note = ttk.Label(parent, foreground="#e0a84f", wraplength=620,
                                    justify="left")
        self._tabs_note.pack(anchor="w", pady=(8, 0))

    def _save_tab_choice(self) -> None:
        """Write the ticked list into the profile, and say a restart is what applies it.

        A tab this page did not list keeps the answer it already had (`_tab_hidden`),
        and does not join `known` on the strength of a page it was never on: «offered
        and switched off» and «never offered» are what tell a tab that has to come back
        by itself from one somebody unticked, and a hidden row can honestly claim
        neither.
        """
        from .. import tabs as tabsreg

        enabled = [spec.id for spec in sorted(tabsreg.TABS, key=lambda s: s.order)
                   if (self._tab_vars[spec.id].get() if spec.id in self._tab_vars
                       else self._tab_hidden.get(spec.id, False))]
        values = self.rt.settings.values
        block = dict(values.get("tabs") or {})
        block["enabled"] = enabled
        was_known = set(block.get("known") or ())
        block["known"] = [spec.id for spec in tabsreg.TABS
                          if spec.id in self._tab_vars or spec.id in was_known]
        values["tabs"] = block
        self.rt.settings.save()
        try:
            self._tabs_note.configure(text=self.t("settings.tabs.restart"))
        except tk.TclError:
            pass

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
            if not tab.SETTINGS_PAGE_KEY:
                continue
            # A contributor is DRAWN before it is asked to draw a page here: since #1215
            # a tab nobody has opened has no widgets, and its page is usually a view of
            # them. Only the contributors — the rest of the window stays undrawn.
            self.rt.tabs.realize(tab)
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
    # filter and the game paths were all edit-the-source. Every row
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

    #: A reading rather than a field, and the reason it is one. Both kinds are here:
    #: what the MACHINE answers (`runtime.settings.MACHINE_KEYS` — where the game is
    #: installed, which Python drives the children) and what the PANEL decides (the
    #: daemon port, `panel/runtime/provision.py`). Neither has ever had an answer a
    #: person could give better than the code, and both were boxes it was possible to be
    #: quietly wrong in — a port typed the same as another profile's is two profiles
    #: farming one account with nothing on screen to say so (#1250, #1252).
    def _read_row(self, parent: ttk.Frame, row: int, key: str, value: str,
                  *, found: bool = True) -> int:
        """One label, its value as text, and the hint under it. Returns the next row.

        ``found=False`` draws the value in the colour of a fault and adds «не найдено»:
        a path the machine answered with that is not on the disk is something to report,
        never a box to correct by hand.
        """
        self.tr(ttk.Label(parent), f"opt.{key}").grid(row=row, column=0, sticky="nw",
                                                      padx=(0, 8), pady=3)
        text = value or self.t("opt.value.unknown")
        if not found:
            text = self.t("opt.value.missing", value=text)
        label = ttk.Label(parent, text=text, wraplength=420, justify="left",
                          foreground="#c33" if not found else "")
        label.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
        self.tr(ttk.Label(parent, foreground="#888", wraplength=420, justify="left"),
                f"opt.{key}.hint").grid(row=row + 1, column=1, columnspan=2, sticky="w",
                                        pady=(0, 6))
        return row + 2

    def _machine_row(self, parent: ttk.Frame, row: int, key: str) -> int:
        """:meth:`_read_row` for a key `tools/lib/game_paths.py` answers."""
        value, found = runtime.settings.machine_value(key)
        return self._read_row(parent, row, key, value, found=found)

    def _port_text(self) -> str:
        """The daemon port, and — the part that matters — WHICH client it reaches."""
        port = self.rt.settings.opt_int("daemon_port", low=1, high=65535)
        user = runtime.game_process.profile_user(self.rt.settings)
        return (self.t("session.client.session", user=user, port=port) if user
                else self.t("session.client.console", port=port))

    def _build_general_settings(self, parent: ttk.Frame) -> None:
        """«Общие»: the Python that runs the children, the daemon, the log, auto-loot."""
        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=0)
        grid.columnconfigure(2, weight=1)
        # The two nobody types, first — they are the two that decide which client this
        # whole page is about. The port follows the Windows session on «Игра»; there is
        # no order of pressing that can leave two profiles on one number (#1252).
        row = self._machine_row(grid, 0, "win_python")
        self._port_lbl = ttk.Label(grid, wraplength=420, justify="left")
        self.tr(ttk.Label(grid), "opt.daemon_port").grid(row=row, column=0, sticky="nw",
                                                         padx=(0, 8), pady=3)
        self._port_lbl.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
        self._port_lbl.configure(text=self._port_text())
        self.tr(ttk.Label(grid, foreground="#888", wraplength=420, justify="left"),
                "opt.daemon_port.hint").grid(row=row + 1, column=1, columnspan=2,
                                             sticky="w", pady=(0, 6))
        for offset, (key, kwargs) in enumerate((
                ("log_max_lines", {"spin": (200, 200000), "width": 10}),
                ("autoloot_limit", {"spin": (1, 50), "width": 10}),
                ("autoloot_poll", {"spin": (1, 600), "width": 10}),
                ("autoloot_pause_min", {"spin": (1, 1440), "width": 10}),
                # …and the OTHER standing order's pace (#1272). Its own pair rather than
                # a share of the auto-loot's: helping is a different budget over a
                # different list, and a look every two seconds — which is what the robbery
                # wants — would be four hundred game reads a day for five presses.
                ("autoassist_poll", {"spin": (30, 3600), "width": 10}),
                ("autoassist_pause_min", {"spin": (1, 1440), "width": 10}),
                ("trace_filter", {"width": 20}),
                ("sniff_ready_timeout", {"spin": (1, 600), "width": 10}),
        )):
            self._opt_row(grid, row + 2 + offset, key, **kwargs)
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

        THE READ IS OFF THE TK THREAD, because it is a `schtasks` SUBPROCESS: measured
        at ~58 ms, and this runs whenever the page is drawn — so with four profiles open
        it is a quarter of a second of window that has not redrawn, for a label nobody
        is waiting on (#1226). The painting comes back through `self.post`, which is the
        one way a tab may return from a worker (docs/panel-tabs.md).
        """
        if getattr(self, "_autostart_note", None) is None:
            return

        def read() -> None:
            try:
                info = autostartmod.status(self.rt.profiles)
            except Exception:            # noqa: BLE001 — a label, never the page
                return
            self.post(lambda: self._paint_autostart(info))

        threading.Thread(target=read, name="panel-autostart", daemon=True).start()

    def _paint_autostart(self, info) -> None:
        """Draw what :meth:`_refresh_autostart` read. Tk thread.

        Whole sentences joined by a newline, never fragments glued together: the order
        of the pieces is not the same in every language, and each line here stands by
        itself in any of them.
        """
        note = getattr(self, "_autostart_note", None)
        if note is None:
            return
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
        """The one block the page words itself: the autostart note.

        `tr` re-labels what it registered; a string built with `t` is not registered and
        would keep whatever language it was drawn in until the tab was rebuilt.
        """
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
        """«Игра»: where the client is, and whether to put it back.

        WHERE THE CLIENT IS IS NOT ASKED (#1252). The launcher and the process name are
        readings off `tools/lib/game_paths.py` — one answer per machine, an environment
        variable in front of an ordinary default — and a machine that keeps the game
        somewhere unusual says so with a variable rather than by typing a path into every
        profile. Typed, they were a way to be quietly wrong: a profile here still carried
        `C:\\Program Files\\LastWar\\…`, a folder the game has never installed itself
        into, and «Запустить игру» reported the ordinary «клиент не запущен».
        """
        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        grid.columnconfigure(2, weight=1)
        row = self._machine_row(grid, 0, "launcher")
        row = self._machine_row(grid, row, "game_exe")
        self._opt_row(grid, row, "watchdog")

        self._build_session_settings(parent)
        self._build_graphics_settings(parent)
        # NO «Автообъезд карты» BOX ANY MORE (#1272). The three knobs here — radius,
        # dwell, rest — paced a camera walk that has been replaced by «Обойти карту» on
        # the «Секретки» coordinate bar: the jumps are scheduled inside the game and the
        # whole server is covered in about three seconds (#1265), so there is nothing
        # left to size or to slow down.

    def _build_session_settings(self, parent: ttk.Frame) -> None:
        """«Windows-сессия»: is this profile's client the one on this desktop?

        The second account does not live here. It runs in its own Windows session, owned
        by that session's own user (tools/rdp_instance.py), and the panel drives it over
        a daemon port of its own. The port is only half the answer: everything that goes
        looking for the *process* — the status strip, the watchdog, the tabs that will not
        spend an errand on a client that is gone — finds a client by executable name, and
        both clients have the same name. Naming the session's login here is what tells
        them apart.

        THE LOGIN IS THE ONLY THING TYPED (#1252). The port travels with the tick: turned
        on, this profile is given one nobody else uses; turned off, it goes back to the
        console's. And it cannot be turned off while ANOTHER profile has the console —
        there is one desktop, so there is one console profile, and the refusal names who
        it is instead of letting two profiles farm one account in silence (#1250).

        AND THIS IS THE ONLY PLACE IT IS TYPED (#1263). There was a second one — «Профиль»
        → «Развести клиенты…» — which asked a login for every shared profile at once and
        wrote the answers with `provision.provision`, straight to the files. Under a
        profile that is OPEN, that write is undone by the next save of that profile's own
        widgets, so the person did it, was told it had worked, and nothing changed. Here
        the edit goes through the bound variable, which is what persists it AND re-points
        the link, so it applies to the profile it belongs to and to nothing else.

        Three sentences under the two knobs, and each answers a question the person had
        to guess at before: :meth:`_session_shared_text` — is this profile farming
        somebody else's account; :meth:`_session_means_text` — what the two knobs
        currently amount to and what is left to do about it; and «Проверить», which is
        the same question asked of live Windows.
        """
        frame = self.tr(ttk.LabelFrame(parent, padding=8), "session.frame")
        frame.pack(fill="x", pady=(12, 0))
        frame.columnconfigure(2, weight=1)
        # `command`, not a trace: a trace also fires when a profile is APPLIED to the
        # widgets, and this hands out a port — so switching profile would quietly move
        # one. Only a person's click may (the «Качество графики» block below took the
        # same lesson).
        self._session_box = self._opt_row(frame, 0, "rdp_session")
        self._session_box.configure(command=self._on_session_toggle)
        self._session_user_entry = self._build_user_picker(frame, 1)
        # …and, ONLY when the list could not be had, why there is a box to type in
        # instead of a list to pick from. Silent while the picker works, because a line
        # explaining a control that is behaving normally is noise.
        self._session_users = ttk.Label(frame, foreground="#e0a84f", wraplength=520,
                                        justify="left")
        self._session_users.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        if getattr(self, "_users_error", ""):
            self._session_users.configure(
                text=self.t("session.users.failed", error=self._users_error))

        # IS THIS PROFILE ALONE ON ITS CLIENT? (#1263) The one fault the two knobs above
        # can be in that nothing else on the page would ever mention: a profile that
        # shares its client with another farms that other account and looks perfectly
        # healthy doing it (#1250). Named here, where it is also put right, and the
        # sentence says which knob to move rather than leaving «непонятно, что делать».
        self._session_shared = ttk.Label(frame, foreground="#e0a84f", wraplength=520,
                                         justify="left")
        self._session_shared.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        # …and what the two knobs currently amount to, WITH what is still left to do —
        # the panel re-points its own link the moment the tick moves, but a client in a
        # session that has never been raised is not going to appear because a checkbox
        # was ticked. Said here rather than left to be discovered as a profile that
        # farmed nothing all night.
        self._session_means = ttk.Label(frame, foreground="#888", wraplength=520,
                                        justify="left")
        self._session_means.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # «Проверить»: the settings answer for themselves, here, rather than being
        # discovered at three in the morning as a profile that farmed nothing. The
        # reading itself is the runtime's (`game_process.check`); this half only puts
        # words to the verdict it comes back with.
        self._session_check_btn = self.tr(
            ttk.Button(frame, command=self._check_session), "session.check")
        self._session_check_btn.grid(row=5, column=1, sticky="w", pady=(8, 0))
        # …and beside it the thing «Проверить» used to send the person to a terminal for
        # (#1231). The verdict says «поднимите сессию»; the button that does it belongs
        # in arm's reach of the sentence, not in a command line in a document.
        self._session_up_btn = self.tr(
            ttk.Button(frame, command=self._bring_up_session), "session.bring_up")
        self._session_up_btn.grid(row=5, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        self._session_verdict = ttk.Label(frame, foreground="#888", wraplength=520,
                                          justify="left")
        self._session_verdict.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        # The port and the session are two halves of one answer, so the contradiction
        # between them is shown without waiting to be asked for.
        self._session_clash = ttk.Label(frame, foreground="#e0a84f", wraplength=520,
                                        justify="left")
        self._session_clash.grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        # WHOSE PASSWORD IS ON THIS PROFILE'S ADDRESS (#1263). Windows keys a saved RDP
        # password by the address and by nothing else, so a slot holding another
        # account's password is the whole reason every «Поднять сессию» used to come up
        # as that account. Filled by «Проверить», which is already the button that asks
        # live Windows — reading credentials on every keystroke would not be free.
        self._session_cred = ttk.Label(frame, foreground="#888", wraplength=520,
                                       justify="left")
        self._session_cred.grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # The login is meaningless while the tick is off, and a box that still takes
        # typing says otherwise. Follow the checkbox — and the port — on every change.
        for key in ("rdp_session", "rdp_user", "daemon_port"):
            self.rt.settings.vars[key].trace_add(
                "write", lambda *a: self._refresh_session_user_state())
        self._refresh_session_user_state()

    def _build_user_picker(self, frame: ttk.Frame, row: int):
        """The login row: PICKED from this machine's accounts, not typed.

        A typed login looks configured and is not: one letter wrong and the bring-up
        goes looking for a session of an account that does not exist, reports the
        ordinary «клиент не запущен», and there is nothing on screen to say which of the
        two states it is in. A list Windows itself answers with cannot be misspelt.

        THE LIST IS NEVER IN THIS REPOSITORY. It is read live
        (`game_process.local_users`), so it holds this machine's accounts on this
        machine and somebody else's on theirs, and no login is committed anywhere.

        Two things it must not do. It must not turn a machine that cannot be asked into
        «there are no accounts» — a panel with no pywin32 falls back to a box to type in
        and says why, rather than a picker with nothing in it and no explanation. And it
        must not drop a login that is already saved: a profile configured against an
        account since renamed, or against a domain one the enumeration does not return,
        keeps what it has and can still be read.

        The variable is the profile's own (`rt.settings.vars["rdp_user"]`), which is what
        persists the choice — the same route the tick takes, and the reason a change here
        is not undone by the next save (#1263).
        """
        self.tr(ttk.Label(frame), "opt.rdp_user").grid(row=row, column=0, sticky="w",
                                                       padx=(0, 8), pady=3)
        var = self.rt.settings.vars["rdp_user"]
        users, error = runtime.game_process.local_users()
        self._users_error = error
        if users:
            saved = str(var.get() or "").strip()
            if saved and saved not in users:
                users = sorted([*users, saved], key=str.casefold)
            widget = ttk.Combobox(frame, textvariable=var, values=users, width=22,
                                  state="readonly")
        else:
            # No list, so the login has to be typed — and the row below says whether
            # that is because the machine would not answer or because it has nobody.
            widget = ttk.Entry(frame, textvariable=var, width=22)
        widget.grid(row=row, column=1, sticky="w")
        self.tr(ttk.Label(frame, foreground="#888", wraplength=340, justify="left"),
                "opt.rdp_user.hint").grid(row=row, column=2, sticky="w", padx=(10, 0))
        return widget

    def _on_session_toggle(self) -> None:
        """A person moved the tick: give this profile the client it now asks for.

        The port is not a question, so it is not asked — it is handed out here and shown
        on «Общие» as a reading (:meth:`_port_text`). Setting the bound variable is what
        persists it and re-points the link: the shell traces `daemon_port` and rebinds
        the daemon on a change, which is exactly what has to happen.
        """
        prov = runtime.provision
        profiles = self.rt.profiles
        name = profiles.active
        want_session = bool(self.rt.settings.opt_bool("rdp_session"))
        port_var = self.rt.settings.vars.get("daemon_port")
        if port_var is None:
            return
        if not want_session:
            owner = prov.console_owner(profiles, exclude=name)
            if owner:
                # One desktop, one console profile. Put the tick back rather than let a
                # second profile drive the first one's client (#1250).
                self.rt.settings.vars["rdp_session"].set(True)
                messagebox.showinfo(self.t("session.frame"),
                                    self.t("session.console_taken", owner=owner))
                self._refresh_session_user_state()
                return
            port_var.set(prov.CONSOLE_PORT)
            self.say("session", "log.session.client.console", port=prov.CONSOLE_PORT)
        else:
            current = self.rt.settings.opt_int("daemon_port", low=1, high=65535)
            if current == prov.CONSOLE_PORT:
                try:
                    port = prov.free_port(profiles, exclude=name)
                except ValueError as exc:
                    messagebox.showerror(self.t("session.frame"),
                                         i18nmod.translated(self.t, exc))
                    self.rt.settings.vars["rdp_session"].set(False)
                    self._refresh_session_user_state()
                    return
                port_var.set(port)
                self.say("session", "log.session.client.own_port", port=port)
        self._refresh_session_user_state()

    def _live_client(self):
        """The client the WIDGETS name — the truth one save ahead of the files.

        `provision.client_of` reads a config dict, and the three keys it wants are
        exactly the three on this page. Handing it what the widgets hold is what makes
        the two sentences below move with the tick instead of one edit behind it.
        """
        s = self.rt.settings
        return runtime.provision.client_of(
            {"rdp_session": s.opt_bool("rdp_session"),
             "rdp_user": s.opt_str("rdp_user"),
             "daemon_port": s.opt_int("daemon_port", low=1, high=65535)})

    def _session_shared_text(self) -> str:
        """«Этот профиль ведёт тот же клиент, что и …», or nothing when it is alone.

        Two ways of being wrong, and they need different instructions: the tick is off
        (or the login is empty), so this profile is on the console beside somebody else
        — tick it and name a session; or two profiles genuinely name the SAME login,
        which no port can separate because there is one client in that session.

        The other profiles are read off disk and this runs on every keystroke in the
        login box, so the answer is held for a second — keyed by the client the widgets
        name, so the tick moving invalidates it at once rather than a second later.
        """
        try:
            client = self._live_client()
            now = time.monotonic()
            seen = getattr(self, "_shared_seen", None)
            if seen is None or seen[0] != client.user or now - seen[1] > 1.0:
                seen = (client.user, now, runtime.provision.sharing_with(
                    self.rt.profiles, self.rt.profiles.active, client=client))
                self._shared_seen = seen
            others = seen[2]
        except Exception:                    # noqa: BLE001 — a sentence, never the page
            return ""
        if not others:
            return ""
        names = ", ".join(others)
        if client.console:
            return self.t("session.shared.console", others=names)
        return self.t("session.shared.same_login", others=names, user=client.user)

    def _session_means_text(self) -> str:
        """What the two knobs amount to, and what is left for the person to do.

        The panel re-points its own link the moment the port changes, so «применилось»
        is true of the panel — and says so. What it is NOT true of is the client: a
        session nobody has raised holds no game, and that is the step this sentence
        exists to name rather than let it be found at three in the morning (#1263).
        """
        s = self.rt.settings
        port = s.opt_int("daemon_port", low=1, high=65535)
        if not s.opt_bool("rdp_session"):
            return self.t("session.means.console", port=port)
        user = s.opt_str("rdp_user").strip()
        if not user:
            return self.t("session.means.no_login")
        return self.t("session.means.session", user=user, port=port,
                      up=self.t("session.bring_up"))

    def _refresh_session_user_state(self) -> None:
        """Keep the login box, the port reading and the warning in step with the tick."""
        on = self.rt.settings.opt_bool("rdp_session")
        entry = getattr(self, "_session_user_entry", None)
        try:
            if entry is not None:
                # A picker's «on» is `readonly`: it opens and it chooses, and it cannot
                # be typed into — which is the whole point of it being a list (#1263).
                # The typed fallback is an ordinary Entry and wants `normal`.
                live = "readonly" if isinstance(entry, ttk.Combobox) else "normal"
                entry.configure(state=live if on else "disabled")
            port_lbl = getattr(self, "_port_lbl", None)
            if port_lbl is not None:
                port_lbl.configure(text=self._port_text())
            shared = getattr(self, "_session_shared", None)
            if shared is not None:
                shared.configure(text=self._session_shared_text())
            means = getattr(self, "_session_means", None)
            if means is not None:
                means.configure(text=self._session_means_text())
            clash = getattr(self, "_session_clash", None)
            if clash is not None:
                gp = runtime.game_process
                # The cheap half of the check: three knobs, no Windows call, because
                # this runs on every keystroke in the login box. It should now be
                # unreachable — the port follows the tick — so it stays as the proof of
                # that rather than as something a person is expected to act on.
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
        fmt["up"] = self.t("session.bring_up")
        try:
            self._session_verdict.configure(
                text=self.t(f"session.check.{kind}", **fmt),
                foreground=self._VERDICT_COLOURS.get(kind, "#c33"))
        except tk.TclError:
            pass
        self._paint_credential()
        self._refresh_session_user_state()

    def _paint_credential(self) -> None:
        """Whose password sits on this profile's RDP address — the #1263 reading.

        Three states worth different words: the slot is this account's (the bring-up
        runs unattended), the slot is empty (Windows will ask, once per reboot), or the
        slot belongs to somebody else — which is the one that used to be invisible and
        used to bring the session up as its owner.
        """
        label = getattr(self, "_session_cred", None)
        if label is None:
            return
        state = runtime.game_process.credential_state(self.rt.settings)
        if state is None:
            text, colour = "", "#888"
        elif state.get("foreign"):
            text = self.t("session.cred.foreign", server=state.get("server"),
                          owner=state.get("owner"), user=state.get("user"))
            colour = "#e0a84f"
        elif state.get("stored"):
            text = self.t("session.cred.stored", server=state.get("server"),
                          user=state.get("user"))
            colour = "#888"
        else:
            text = self.t("session.cred.none", server=state.get("server"),
                          user=state.get("user"))
            colour = "#888"
        try:
            label.configure(text=text, foreground=colour)
        except tk.TclError:
            pass

    def _bring_up_session(self) -> None:
        """Create this profile's Windows session, and start its client and daemon in it.

        Minutes of work, none of it on the Tk thread: an RDP logon, a launcher that may
        decide to update, and a daemon that waits for the client to finish loading. What
        the tool says on the way goes into the panel's log as it happens, so the wait is
        something a person can watch rather than a window that has stopped answering.
        """
        if not runtime.game_process.profile_user(self.rt.settings):
            # Nothing to bring up: no session is named. «Проверить» already has the
            # words for both ways of being in that state, so let it say them.
            self._check_session()
            return
        btn = getattr(self, "_session_up_btn", None)
        if btn is not None:
            btn.configure(state="disabled")
        # Windows asks for the password when none is stored, and the dialog appears on
        # the desktop with no explanation of what wanted it (#1231). Say so first.
        # Nothing stored means Windows is about to put a password box on the desktop
        # with no hint of what wanted it — and, unless the person is told otherwise, it
        # will do that again after every reboot. Both halves are said before the dialog
        # appears rather than after it has confused somebody (#1231).
        state = runtime.game_process.credential_state(self.rt.settings)
        if state is not None and state.get("foreign"):
            # The one that used to bring the session up as somebody else (#1263).
            # Said BEFORE the wait, because otherwise the person watches three minutes
            # of nothing and is told «nobody is logged on as …» at the end of it.
            self.say("session", "log.session.cred_foreign", server=state.get("server"),
                     owner=state.get("owner"), user=state.get("user"))
        if state is not None and not state.get("stored"):
            self.say("session", "log.session.will_ask")
            # …with the PORT in the command, because the port is what decides which
            # address the password is saved against (#1263). Without it the person
            # saves a password on one address and the bring-up looks on another.
            self.say("session", "log.session.save_hint",
                     user=runtime.game_process.profile_user(self.rt.settings),
                     port=self.rt.settings.opt_int("daemon_port", low=1, high=65535))
        self.say("session", "log.session.bringing_up",
                 user=runtime.game_process.profile_user(self.rt.settings))

        def work() -> None:
            try:
                code = runtime.game_process.bring_up(
                    self.rt.settings, say=lambda msg: self.rt.put(f"[session] {msg}"))
            except Exception as exc:     # noqa: BLE001 — a line in the log, not a crash
                self.post(lambda: self._brought_up(None, exc))
                return
            self.post(lambda: self._brought_up(code, None))

        threading.Thread(target=work, name="panel-session-up", daemon=True).start()

    def _brought_up(self, code: "int | None", error: "Exception | None") -> None:
        """Say how the bring-up ended and re-read the verdict. Tk thread."""
        btn = getattr(self, "_session_up_btn", None)
        if btn is not None:
            try:
                btn.configure(state="normal")
            except tk.TclError:
                pass
        if error is not None:
            self.say("session", "log.session.up_failed", error=error)
        elif code == 0:
            self.say("session", "log.session.up_ok")
        else:
            self.say("session", "log.session.up_partial", code=code)
        # Whatever it says, the verdict line is now stale — and it is the one place the
        # person looks to find out whether the thing they just pressed worked.
        self._check_session()

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

    #: The economy profile, in the scenario's own arguments. This combination measured
    #: 0.06 % of the video card and 0.67 % of one core, against a quarter of the card for
    #: a client left alone (docs/research/headless-gpu.md). 640 × 480 rather than
    #: something smaller because the saving below it is a rounding error and the picture
    #: stays large enough to glance at when a person wants to see what the bot is doing.
    LOW_GRAPHICS = {"fps": 10, "quality": 0, "width": 640, "height": 480}

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
        if not self.rt.game.ready():
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
        if not self.rt.game.ready():
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
        if not self.rt.game.ready():
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
        key = "graphics.state.now" if not vsync else "graphics.state.now_vsync"
        # …and the case worth catching: the profile says economy and the client is not in
        # it. That is what a restart looks like — measured on a real one, the render size
        # came back at 640 × 480 (Unity keeps it) while the cap and the quality were back
        # at 60 and High. Half a mode in force is exactly the state nobody notices, so it
        # is named rather than left for the person to spot in the numbers.
        if self.rt.settings.opt_str("graphics_mode") == "low" and not self._is_low(
                fps, vsync, quality):
            key = "graphics.state.lapsed"
        self._say_graphics(
            key, fps=fps, quality=self.t(f"graphics.quality.{min(max(quality, 0), 2)}"),
            width=width, height=height, mode=self.t("graphics.mode.low"))
        if then is not None:
            then()

    def _is_low(self, fps: int, vsync: int, quality: int) -> bool:
        """Is the frame cap this switch asks for actually in force?

        The render size is deliberately not part of the answer. It survives a restart on
        its own — Unity writes it where it reads it back from — so a client that lost the
        mode still looks small, and judging by the size would call a lapsed mode fine.
        """
        return (not vsync and fps <= self.LOW_GRAPHICS["fps"]
                and quality <= self.LOW_GRAPHICS["quality"])

    def _send_debug_archive(self) -> None:
        """«Отправить диагностику»: the packing lives in the runtime.

        The shell's "send the log to the developer" dialog presses the same thing, and
        a routine two pages share belongs to neither of them (panel/runtime/diag.py).
        """
        diag.send_archive(self.rt)

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(SettingsTab))
