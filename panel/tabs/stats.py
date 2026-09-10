"""The «Статистика» tab: how much of each resource came in, per day.

One row per day, newest first, a column per resource. Nothing here drives the game — it
reads the ACTIVE PROFILE's tally, which the runtime's own book fills as balance pushes
arrive (`panel/runtime/resource_book.py`, #2743 — it used to be this tab's own method,
which is why a live panel with the trigger switched on had never written a row).

That makes it the one tab in the first wave with no live read at all: it opens, on any
profile, with or without a daemon, and shows what that account has collected.
"""
from __future__ import annotations

from tkinter import ttk

from .. import resource_stats as resourcestatsmod
from ..runtime import resource_book
from .base import PanelTab


#: THE RECEIVER IS THE BOOK'S, NOT THIS TAB'S, since #2743 — kept here as a name so
#: nothing that reads the ledger has to learn a new one.
INTAKE_GAINS = resource_book.INTAKE_GAINS


#: HOW LONG A BURST OF EVENTS WAITS BEFORE THE TABLE IS REPAINTED (#2660). The repaint
#: destroys and rebuilds every label in the grid, and the events arrive in bursts — one
#: harvest prices about 25 balance pushes. A second is invisible on a table of days and
#: turns a burst into one repaint of the Tk thread every open profile shares.
REDRAW_MS = 900


class StatsTab(PanelTab):
    ID = "stats"
    TITLE_KEY = "tab.stats"
    ORDER = 250
    #: Still being written: hidden unless «Разработка» is on (#1273). The mark
    #: comes off when this tab's abilities are proven live and said so in
    #: `docs/farming.md` (`PanelTab.IN_DEVELOPMENT`).
    IN_DEVELOPMENT = True
    LOCALE_NS = ("stats",)
    #: NO TRIGGER OF ITS OWN ANY MORE (#2743). The tracker used to be this tab's method,
    #: and this tab is `IN_DEVELOPMENT` — so on a live panel the `resource_tracker`
    #: trigger was switched on, offered, fired, and bound to nothing: measured on
    #: 2026-09-10, three live profiles with the trigger on and not one row written since
    #: the store was created. It lives in `panel/runtime/resource_book.py` now, bound by
    #: the schedule for every profile, and this tab DRAWS what the book holds.

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._grid = None
        self._stats = None
        self._unsubscribe = None

    # -- construction -------------------------------------------------------
    def build(self) -> None:
        frame = self.rt.tr(ttk.LabelFrame(self.parent, padding=8), "stats.frame")
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        self._grid = ttk.Frame(frame)
        self._grid.pack(fill="x")
        self.rt.tr(ttk.Label(frame, foreground="#888", wraplength=620, justify="left"),
                   "stats.hint").pack(anchor="w", pady=(8, 0))
        self._load()
        self.redraw()
        # A gain recorded while this tab is open should show up without a click — AND A
        # BURST OF THEM MUST COST ONE REPAINT (#2660): one harvest prices about 25
        # balance pushes, and the repaint destroys and rebuilds every label in the grid
        # on the Tk thread every open profile shares. `arm` cancels the pending one.
        self._unsubscribe = self.rt.bus.subscribe(
            resource_book.GAINED,
            lambda _p: self.post(
                lambda: self.rt.tick.arm("stats_redraw", REDRAW_MS, self.refresh)))

    # -- data ---------------------------------------------------------------
    def _load(self) -> None:
        """What the book holds — this tab reads and never writes (#2743)."""
        book = getattr(self.rt, "resource_book", None)
        if book is not None:
            book.refresh()
            self._stats = book.stats
            return
        # A tab opened by a bare harness (`python -m panel.tabs.stats`, a test) has no
        # runtime behind it and still draws: the tally is a row of this profile's own
        # database, and reading it needs nothing else.
        self._stats = resourcestatsmod.load_stats_from_store(
            self.rt.store, self.rt.profiles.resource_stats_json())

    @property
    def stats(self):
        """The tally this tab is showing (the shell shares its own — see `adopt`)."""
        return self._stats

    def adopt(self, stats) -> None:
        """Show a tally somebody else owns, without re-reading the file.

        The shell keeps the live one because the resource tracker updates it on every
        push; a standalone tab has no tracker and simply reads the profile's file.
        """
        self._stats = stats
        self.redraw()

    def refresh(self) -> None:
        self._load()
        self.redraw()

    def on_profile_switch(self) -> None:
        # The tally is per profile; the baseline the diff needs belongs to the book.
        self.refresh()

    def shutdown(self) -> None:
        self.rt.tick.disarm("stats_redraw")
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    # -- drawing ------------------------------------------------------------
    # -- the phone -----------------------------------------------------------
    WEB_SCREEN = True

    def web_view(self) -> "dict | None":
        """A day per card — because a five-column table on a 360-wide screen is a
        table nobody can read, and the columns here are exactly what a card's rows are.

        No reading of the game: the tally is a file this profile owns, and it is
        already in memory.
        """
        stats = self._stats
        dates = stats.dates() if stats is not None else []
        cards = []
        for date in dates:
            row = stats.on(date)
            cards.append({
                "title": None,
                "head": date,
                "rows": [{"label": f"stats.res.{key}", "value": f"{row[key]:,}"}
                         for key in resourcestatsmod.RESOURCES],
            })
        if not cards:
            cards = [{"title": "stats.frame", "empty": "stats.empty"}]
        # NO «ОБНОВИТЬ» (#2633): the tally only ever moves when a balance push is
        # priced, and the book says so on the bus when it does.
        return {"cards": cards}

    def redraw(self) -> None:
        """Repaint the per-day table from the tally."""
        grid = self._grid
        if grid is None or self._stats is None:
            return
        for child in grid.winfo_children():
            child.destroy()
        self.rt.tr(ttk.Label(grid, foreground="#888"), "stats.col.date").grid(
            row=0, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
        for col, key in enumerate(resourcestatsmod.RESOURCES, start=1):
            self.rt.tr(ttk.Label(grid, foreground="#888"), f"stats.res.{key}").grid(
                row=0, column=col, sticky="e", padx=(0, 10), pady=(0, 4))
        dates = self._stats.dates()
        if not dates:
            self.rt.tr(ttk.Label(grid, foreground="#888"), "stats.empty").grid(
                row=1, column=0, columnspan=len(resourcestatsmod.RESOURCES) + 1,
                sticky="w", pady=4)
            return
        for r, date in enumerate(dates, start=1):
            ttk.Label(grid, text=date).grid(row=r, column=0, sticky="w",
                                            padx=(0, 14), pady=1)
            row = self._stats.on(date)
            for col, key in enumerate(resourcestatsmod.RESOURCES, start=1):
                ttk.Label(grid, text=f"{row[key]:,}").grid(
                    row=r, column=col, sticky="e", padx=(0, 10))


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(StatsTab))
