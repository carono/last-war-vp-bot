"""The «Статистика» tab: how much of each resource came in, per day.

One row per day, newest first, a column per resource. Nothing here drives the game — it
reads the ACTIVE PROFILE's tally, which the «resource_tracker» trigger fills as balance
pushes arrive (panel/resource_stats.py).

That makes it the one tab in the first wave with no live read at all: it opens, on any
profile, with or without a daemon, and shows what that account has collected.
"""
from __future__ import annotations

from tkinter import ttk

from .. import resource_stats as resourcestatsmod
from ..runtime import reads
from .base import PanelTab, TriggerSpec


class StatsTab(PanelTab):
    ID = "stats"
    TITLE_KEY = "tab.stats"
    ORDER = 250
    LOCALE_NS = ("stats",)
    #: The tally is only ever filled by this: a balance-changed push, read and
    #: differenced. The trigger is the tab's own — with the tab switched off nothing
    #: listens, because there would be nothing to write the gains into.
    TRIGGERS = (TriggerSpec(name="resource_tracker",
                            event="push.resource.item.update",
                            handler="track", needs_game=True),)

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._grid = None
        self._stats = None
        self._unsubscribe = None
        # The last balance seen, so a push's gain is `current - last`. Empty until the
        # first read establishes a baseline — no gain is counted then, because there is
        # nothing to diff against.
        self._last: dict = {}

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
        # A gain recorded while this tab is open should show up without a click.
        self._unsubscribe = self.rt.bus.subscribe("resources.gained",
                                                  lambda _p: self.refresh())

    # -- data ---------------------------------------------------------------
    def _load(self) -> None:
        self._stats = resourcestatsmod.load_stats(self.rt.profiles.resource_stats_json())

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
        # The tally is per profile and so is the baseline: the other account's numbers
        # are not this one's, and diffing across a switch would invent a gain.
        self._last = {}
        self.refresh()

    # -- the tracker (the «resource_tracker» trigger) ------------------------
    def track(self) -> None:
        """One balance-changed push: read the balance and tally what went up.

        The gain is `current - last` per resource (positive only): the push says a
        balance moved, not by how much, so the tracker diffs. The first read of a
        session is a baseline.
        """
        current = reads.resource_balance(self.rt.game)
        if not current:
            return
        gains = resourcestatsmod.positive_deltas(current, self._last)
        self._last = current
        if not gains:
            return
        self._stats = (self._stats or resourcestatsmod.load_stats(
            self.rt.profiles.resource_stats_json())).add(gains)
        resourcestatsmod.save_stats(self._stats,
                                    self.rt.profiles.resource_stats_json())
        self.say("trigger", "triggers.log.resource_gain",
                 what=", ".join(f"{k} +{v}" for k, v in gains.items()))
        self.rt.root.after(0, self.redraw)

    def shutdown(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    # -- drawing ------------------------------------------------------------
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
