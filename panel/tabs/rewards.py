"""The «Награды» tab: what the game gave, what was closed, and what nobody vouched for.

NOTHING HERE DRIVES THE GAME, and nothing here asks it anything. The ability is an EAR
inside the client (`tools/lib/lua_actions.py::reward_watch_install`, #2027): it closes the
reward modals the client raises after a headless press and writes down what was in them.
The rows reach the panel when a recipe drains the ring
(`actions/collect_reward_popups.md`) and are booked by `panel/runtime/rewards.py`. This
page draws that book — a table this profile owns, with no live read at all, so it opens on
any profile with or without a client.

THE ONE ROW THAT ASKS FOR SOMETHING is `unknown`: a reward-shaped window the ear saw and
would NOT close, because its name is not on the whitelist. Those are drawn first and said
in the log, because they are how the whitelist grows — a window nobody adds is a popup
that goes on sitting on the client's screen.

«ЗА ЧТО» is what the panel was playing at the moment the row arrived, and an empty one is
drawn as «не знаю» rather than filled in with a guess: nothing in the client knows why a
reward came.
"""
from __future__ import annotations

import time
from tkinter import ttk

from .base import PanelTab

#: How many rows the page shows. The book keeps ninety days; a page is for reading.
SHOWN = 60

#: What each kind is called on screen — the key, never the word (`CLAUDE.md`).
KIND_KEYS = {
    "reward": "rewards.kind.reward",
    "closed": "rewards.kind.closed",
    "popup": "rewards.kind.popup",
    "unknown": "rewards.kind.unknown",
    "held": "rewards.kind.held",
    "lost": "rewards.kind.lost",
}


class RewardsTab(PanelTab):
    ID = "rewards"
    TITLE_KEY = "tab.rewards"
    ORDER = 255
    LOCALE_NS = ("rewards",)
    WEB_SCREEN = True
    #: Still being written: the ear's behaviour is pinned by tests in a real Lua VM but
    #: has not been confirmed on a live account yet, so the tab stays behind «Разработка»
    #: until `docs/farming.md` says it works (`PanelTab.IN_DEVELOPMENT`).
    IN_DEVELOPMENT = True

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._grid = None

    # -- construction -------------------------------------------------------
    def build(self) -> None:
        frame = self.rt.tr(ttk.LabelFrame(self.parent, padding=8), "rewards.frame")
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        self._grid = ttk.Frame(frame)
        self._grid.pack(fill="x")
        self.rt.tr(ttk.Label(frame, foreground="#888", wraplength=620, justify="left"),
                   "rewards.hint").pack(anchor="w", pady=(8, 0))
        self.redraw()
        # A STATISTIC IS NOT REFRESHED BY HAND (#2633). The book is written when a recipe
        # drains the ear's ring, and it says so — so the page listens instead of offering
        # a button whose only job was to ask again.
        book = getattr(self.rt, "rewards", None)
        if book is not None:
            book.watch(self._booked)

    def _booked(self, _rows) -> None:
        """One drain, booked: repaint on the Tk thread."""
        self.post(self.redraw)

    def shutdown(self) -> None:
        book = getattr(self.rt, "rewards", None)
        if book is not None and hasattr(book, "unwatch"):
            book.unwatch(self._booked)

    # -- reading ------------------------------------------------------------
    def rows(self) -> list:
        """The newest rows, unknown ones first — the only sort order worth having here."""
        book = getattr(self.rt, "rewards", None)
        if book is None:
            return []
        rows = book.recent(SHOWN)
        return sorted(rows, key=lambda r: (r.get("kind") != "unknown",), reverse=False)

    @staticmethod
    def when(row) -> str:
        """The row's own time, off the panel's clock — the game's is only a tie-break."""
        stamp = int(row.get("seen_at") or 0)
        if stamp <= 0:
            return ""
        return time.strftime("%d.%m %H:%M", time.localtime(stamp))

    def why(self, row) -> str:
        """WHAT EARNED IT, or the honest «не знаю» when the panel was playing nothing."""
        return str(row.get("why") or "") or self.t("rewards.why.unknown")

    # -- drawing ------------------------------------------------------------
    def redraw(self) -> None:
        grid = self._grid
        if grid is None:
            return
        for child in grid.winfo_children():
            child.destroy()
        heads = ("rewards.col.when", "rewards.col.kind",
                 "rewards.col.what", "rewards.col.why")
        for col, key in enumerate(heads):
            self.rt.tr(ttk.Label(grid, foreground="#888"), key).grid(
                row=0, column=col, sticky="w", padx=(0, 12), pady=(0, 4))
        rows = self.rows()
        if not rows:
            self.rt.tr(ttk.Label(grid, foreground="#888"), "rewards.empty").grid(
                row=1, column=0, columnspan=len(heads), sticky="w", pady=4)
            return
        for r, row in enumerate(rows, start=1):
            what = row.get("items") or row.get("source") or ""
            cells = (self.when(row), self.t(KIND_KEYS.get(row.get("kind", ""),
                                                          "rewards.kind.other")),
                     str(what), self.why(row))
            for col, text in enumerate(cells):
                ttk.Label(grid, text=text).grid(row=r, column=col, sticky="w",
                                                padx=(0, 12))

    # -- the phone -----------------------------------------------------------
    def web_view(self) -> "dict | None":
        """A card of counts, then a row per popup — and the unknown ones on top.

        No reading of the game: every value here is in this profile's own table already.
        """
        book = getattr(self.rt, "rewards", None)
        rows = self.rows()
        tally = book.tally(rows) if book is not None else {}
        cards = [{
            "title": "rewards.frame",
            "rows": [{"label": KIND_KEYS[kind], "value": str(tally.get(kind, 0))}
                     for kind in ("reward", "closed", "unknown", "popup", "held")],
        }]
        unknown = [r for r in rows if r.get("kind") == "unknown"]
        if unknown:
            cards.append({
                "title": "rewards.unknown.title",
                "rows": [{"label": r.get("source") or "", "value": self.when(r)}
                         for r in unknown[:10]],
            })
        if rows:
            cards.append({
                "title": "rewards.list",
                "rows": [{"label": (r.get("items") or r.get("source") or ""),
                          "value": f"{self.when(r)} · {self.why(r)}"}
                         for r in rows],
            })
        else:
            cards.append({"title": "rewards.list", "empty": "rewards.empty"})
        # NO «ОБНОВИТЬ» (#2633): the rows arrive when the ear's ring is drained and the
        # page is told; a button whose only job is to ask again is what that rule removes.
        return {"cards": cards}


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(RewardsTab))
