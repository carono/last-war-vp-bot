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

import threading
import tkinter as tk
from tkinter import ttk

from .. import debug_log as dbgmod
from .. import debug_sender as dbgsender
from .. import mapsweep as mapsweepmod
from .. import runtime
from ..runtime.paths import repo_rel
from ..widgets import numeric_spinbox
from .base import PanelTab

#: The shell's own sub-pages, in the order they appear. `builder` is the method that
#: fills one; `None` shows the placeholder, so the page is complete from the first day
#: and filling one in is writing its builder.
SHELL_PAGES: tuple = (
    ("general", "_build_general_settings"),
    ("game", "_build_game_settings"),
)


class SettingsTab(PanelTab):
    """The notebook of settings pages, the shell's own and the tabs'."""

    ID = "settings"
    TITLE_KEY = "tab.settings"
    ORDER = 40
    PREFERRED_SIZE = "820x640"
    LOCALE_NS = ("settings", "opt", "debug")
    NEEDS = frozenset()

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
                self.rt.put(f"[panel] settings page {title_key}: {exc}")
                self.say("panel", "log.tab.failed", tab=title_key, error=exc)

    # -- settings: the knobs that used to be constants in this file -----------
    #
    # Both tabs said "Скоро" while WIN_PYTHON, the auto-loot budget, the trace
    # filter, the game paths and the sweep box were all edit-the-source. Every row
    # below is one entry in runtime.DEFAULTS bound to its `_opt_vars` variable, so
    # a new knob is a line there plus a row here plus two locale strings.
    def _opt_row(self, parent: ttk.Frame, row: int, key: str, *,
                 width: int = 12, spin: "tuple | None" = None) -> None:
        """One labelled field on a Settings tab, bound to ``_opt_vars[key]``."""
        self.tr(ttk.Label(parent), f"opt.{key}").grid(row=row, column=0, sticky="w",
                                                       padx=(0, 8), pady=3)
        var = self.rt.settings.vars[key]
        if isinstance(var, tk.BooleanVar):
            ttk.Checkbutton(parent, variable=var).grid(row=row, column=1, sticky="w")
        elif spin is not None:
            # A float knob (poll seconds, dwell, timeout) needs the decimal point;
            # an integer one stays digit-only.
            decimal = isinstance(runtime.DEFAULTS.get(key), float)
            numeric_spinbox(parent, from_=spin[0], to=spin[1], width=width,
                        decimal=decimal, textvariable=var).grid(
                            row=row, column=1, sticky="w")
        else:
            ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1,
                                                                  sticky="we")
        self.tr(ttk.Label(parent, foreground="#888", wraplength=340, justify="left"),
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
        """«Отправить диагностику»: zip the debug logs and hand them to `debug_send_url`.

        The destination is a stub for now (no transport wired), so this always
        produces the zip and reports where it went — an empty URL means "do not send",
        which is not an error: the archive is still written for a by-hand hand-off.
        """
        url = self.rt.settings.opt_str("debug_send_url")
        path = self.rt.profiles.debug_log()
        self.say("debug", "log.debug.packing")

        def work():
            try:
                status, archive, _detail = dbgsender.send(
                    url, path=path, logger=dbgmod.get_logger("sender"))
            except Exception as exc:  # noqa: BLE001
                # BOUND, not captured: Python deletes the `except` name when the block
                # ends, so a lambda closing over it raised NameError at the one moment
                # this line exists for — reporting that the send failed.
                self.rt.root.after(0, lambda e=exc: self.say("debug",
                                                             "log.debug.failed", error=e))
                return
            rel = repo_rel(archive)

            def done():
                if status == "disabled":
                    self.say("debug", "log.debug.no_dest", path=rel)
                elif status == "sent":
                    self.say("debug", "log.debug.sent", dest=url, path=rel)
                else:                 # "stub" — archive is ready, transport is not
                    self.say("debug", "log.debug.stub", path=rel, dest=url)
            self.rt.root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(SettingsTab))
