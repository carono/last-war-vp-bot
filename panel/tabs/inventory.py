"""The «Инвентарь» tab: what is in the bag, searchable.

Read live through the warm daemon and redrawn on every keystroke in the search box —
which is why the rows are built and destroyed constantly, and why the translation
registry holds its widgets weakly (panel/runtime/i18n.py).
"""
from __future__ import annotations

from tkinter import ttk

from ..widgets import ScrollableFrame, install_numeric_field, font as ui_font
from .base import TriggerSpec
from ._data import DataTab, _group, _marker_payloads, _run_lua, _stringvar

class InventoryTab(DataTab):
    """The bag: icon (glyph fallback), name, count, description, with a search box
    that filters by name. Items are read best-effort from the item/bag manager."""

    #: The bag changes without anybody pressing anything, so the tab offers the
    #: standing order that keeps it live — and it is only offered while the tab is
    #: here to be repainted (§3.2).
    TRIGGERS = (TriggerSpec(name="inventory_refresh",
                            event="push.resource.item.update", handler="refresh_live"),)

    ID = "inventory"
    TITLE_KEY = "tab.inventory"
    ORDER = 220
    #: Still being written: hidden unless «Разработка» is on (#1273). The mark
    #: comes off when this tab's abilities are proven live and said so in
    #: `docs/farming.md` (`PanelTab.IN_DEVELOPMENT`).
    IN_DEVELOPMENT = True
    LOCALE_NS = ('inventory', 'tabx')

    def build(self) -> None:
        top = ttk.Frame(self.parent)
        top.pack(fill="x", padx=10, pady=(10, 4))
        self.rt.tr(ttk.Label(top, font=ui_font(size=15, weight="bold")),
                     "tab.inventory").pack(side="left")
        self.rt.tr(ttk.Button(top, width=12, command=self.refresh),
                     "tabx.refresh").pack(side="right")
        self._status_var = _stringvar(self.rt)
        ttk.Label(top, textvariable=self._status_var, foreground="#888").pack(
            side="right", padx=8)

        searchrow = ttk.Frame(self.parent)
        searchrow.pack(fill="x", padx=10, pady=(0, 6))
        self.rt.tr(ttk.Label(searchrow), "inventory.search").pack(side="left")
        self._query = _stringvar(self.rt)
        self._query.trace_add("write", lambda *_: self._redraw())
        ttk.Entry(searchrow, textvariable=self._query).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        self._scroll = ScrollableFrame(self.parent)
        self._scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._items: list = []

    def fetch(self):
        # BEST-EFFORT: read the bag as «ITEM name\tcount\tdesc» lines.
        chunk = (
            "local M = DataCenter.ItemDataManager or DataCenter.BagDataManager "
            "local ok, list = pcall(function() return M:GetItemList() end) "
            "if not ok or type(list) ~= 'table' then "
            "ok, list = pcall(function() return M:GetAllItem() end) end "
            "if not ok or type(list) ~= 'table' then "
            "ok, list = pcall(function() return M.itemList end) end "
            "if type(list) == 'table' then for _, it in ipairs(list) do "
            "local nm = tostring(it.name or it.itemName or it.id or '?') "
            "local ct = tostring(it.count or it.num or it.amount or 0) "
            "local ds = tostring(it.desc or it.description or '') "
            "CS.UnityEngine.Debug.LogError('ITEM '..nm..'\\t'..ct..'\\t'..ds) "
            "end end"
        )
        items = []
        for payload in _marker_payloads(_run_lua(self.rt, chunk, "ITEM"), "ITEM"):
            parts = payload.split("\t")
            if parts and parts[0]:
                items.append({
                    "name": parts[0],
                    "count": parts[1] if len(parts) > 1 else "",
                    "desc": parts[2] if len(parts) > 2 else "",
                })
        return items

    def web_cards(self, items) -> list:
        """The bag. Searchable on the phone by the renderer, not by this tab."""
        rows = [{"text": str(it.get("name") or "?"),
                 "detail": _group(it.get("count")),
                 "note": str(it.get("desc") or "")} for it in items or ()]
        return [{"title": "tab.inventory", "items": rows, "search": True,
                 "empty": "tabx.no_game"}]

    def render(self, items) -> None:
        self._items = items
        self._status_var.set(self.rt.t("inventory.count", n=len(items)) if items
                             else self.rt.t("tabx.no_game"))
        self._redraw()

    def _redraw(self) -> None:
        scroll = getattr(self, "_scroll", None)
        if scroll is None:
            return
        for child in scroll.winfo_children():
            child.destroy()
        query = (self._query.get() or "").strip().lower()
        shown = [it for it in self._items
                 if not query or query in it["name"].lower()]
        if not shown:
            self.rt.tr(ttk.Label(scroll, foreground="#888"),
                         "inventory.empty").grid(row=0, column=0, sticky="w", pady=6)
            return
        for r, it in enumerate(shown):
            ttk.Label(scroll, text="📦", font=ui_font(size=16)).grid(
                row=r, column=0, padx=(0, 8), pady=2)
            ttk.Label(scroll, text=it["name"],
                     font=ui_font(weight="bold")).grid(
                row=r, column=1, sticky="w", padx=(0, 12))
            ttk.Label(scroll, text=f"×{_group(it['count'])}").grid(
                row=r, column=2, sticky="w", padx=(0, 12))
            if it["desc"]:
                ttk.Label(scroll, text=it["desc"], foreground="#888",
                         wraplength=360, justify="left").grid(
                    row=r, column=3, sticky="w")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(InventoryTab))
