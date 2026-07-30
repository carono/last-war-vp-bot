"""Three read-only tabs for the panel: Alliance, Profile, Inventory.

Each is a small class that builds its UI into a tab frame and refreshes on demand
— lazily (the panel calls :meth:`ensure_loaded` the first time the tab is shown) and
on a «Обновить» button. The heavy lifting (reading the live game through the warm
daemon) runs on a background thread and always degrades gracefully: no daemon, no
game, or a manager that is not loaded yet shows an empty state, never a crash.

Kept out of ``panel/__main__.py`` on purpose — the wiring there is only «make the
frame, add it to the notebook, hand it to a class here». The data reads are
BEST-EFFORT: the exact Lua accessors for level/power, the inventory and the alliance
roster are not confirmed against a live client, so each is wrapped in ``pcall`` and a
field that cannot be read is simply omitted. Resources reuse the panel's own
``_read_resource_balance`` (panel/__main__.py), which the resource tracker already relies on.
"""
from __future__ import annotations

import threading

import customtkinter as ctk

from .ctk_widgets import CTkButton, CTkEntry, CTkFrame, CTkLabel

# Resource keys, in display order, with a glyph fallback for the icon.
RESOURCE_GLYPHS = {"food": "🍖", "wood": "🌲", "metal": "⚙️", "oil": "🛢️", "gold": "🪙"}
RESOURCE_ORDER = ("food", "wood", "metal", "oil", "gold")


def _run_lua(app, chunk: str, marker: str, settle: float = 0.6):
    """Run ``chunk`` through the warm daemon and return the Player.log lines that
    carry ``marker``. Returns ``[]`` on any failure (no daemon / no game / error)."""
    try:
        import lua_client       # tools/lib is on sys.path once the panel has imported
        ev = lua_client.get_evaluator(port=app._daemon_port())
        return ev.run(chunk, marker=marker, settle=settle) or []
    except Exception:       # noqa: BLE001 — a failed read is an empty tab, never a crash
        return []


def _marker_payloads(lines, marker: str):
    """Every ``<marker> …`` line's payload, in order."""
    out = []
    for line in lines or ():
        _head, sep, tail = line.partition(marker + " ")
        if sep:
            out.append(tail.rstrip("\n"))
    return out


class _DataTab:
    """A tab that loads once when first shown and refreshes on a button.

    Subclasses fill :meth:`build` (UI), :meth:`fetch` (background, returns data) and
    :meth:`render` (Tk thread, paints the data). :meth:`fetch` runs off the Tk thread.
    """

    def __init__(self, app, parent):
        self.app = app
        self.parent = parent
        self._loaded = False
        self._busy = False
        self._status_var = None
        self.build()

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """First time the tab is shown: kick off the initial load."""
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        if self._status_var is not None:
            self._status_var.set(self.app._t("tabx.loading"))
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            data = self.fetch()
        except Exception as exc:        # noqa: BLE001
            self.app.after(0, lambda e=exc: self._finish_error(e))
            return
        self.app.after(0, lambda: self._finish_ok(data))

    def _finish_ok(self, data) -> None:
        self._busy = False
        try:
            self.render(data)
        except Exception:               # noqa: BLE001 — a render slip must not wedge the tab
            if self._status_var is not None:
                self._status_var.set(self.app._t("tabx.error"))

    def _finish_error(self, exc) -> None:
        self._busy = False
        if self._status_var is not None:
            self._status_var.set(self.app._t("tabx.error"))

    # -- small helpers for subclasses ---------------------------------------
    def _header(self, title_key: str):
        """A title row with a «Обновить» button and a status label; returns the body
        frame the subclass fills."""
        bar = CTkFrame(self.parent, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.app._tr(CTkLabel(bar, font=ctk.CTkFont(size=15, weight="bold")),
                     title_key).pack(side="left")
        self.app._tr(CTkButton(bar, width=12, command=self.refresh),
                     "tabx.refresh").pack(side="right")
        self._status_var = tk_stringvar(self.app)
        CTkLabel(bar, textvariable=self._status_var, text_color="#888").pack(
            side="right", padx=8)
        body = CTkFrame(self.parent, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        return body

    # subclasses override these
    def build(self) -> None: ...
    def fetch(self): ...
    def render(self, data) -> None: ...


def tk_stringvar(app):
    import tkinter as tk
    return tk.StringVar(master=app, value="")


# ---------------------------------------------------------------------------
class AllianceTab(_DataTab):
    """Alliance roster — name / level / power / online / last seen — in a scrollable
    grid. A stub for now: presence comes from `al.rank` (the roster screen), which the
    panel cannot sample passively, so an empty read shows a hint to open the roster."""

    COLUMNS = ("alliance.col.name", "alliance.col.level", "alliance.col.power",
               "alliance.col.status", "alliance.col.seen")

    def build(self) -> None:
        body = self._header("tab.alliance")
        self._scroll = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True)
        self.app._tr(CTkLabel(self.parent, text_color="#888", wraplength=640,
                              justify="left"),
                     "alliance.hint").pack(anchor="w", padx=10, pady=(0, 10))

    def fetch(self):
        # BEST-EFFORT: try a couple of plausible roster managers; log one line per
        # member as «ALLY name\tlevel\tpower\tonline\toffLineTime».
        chunk = (
            "local M = DataCenter.AllianceMemberDataManager or "
            "DataCenter.AllianceDataManager "
            "local ok, list = pcall(function() return M:GetMemberList() end) "
            "if not ok or type(list) ~= 'table' then "
            "ok, list = pcall(function() return M.memberList end) end "
            "if type(list) == 'table' then for _, m in ipairs(list) do "
            "local n = tostring(m.name or m.playerName or '?') "
            "local lv = tostring(m.level or m.lv or 0) "
            "local pw = tostring(m.power or m.armyPower or 0) "
            "local on = (m.online and 1 or 0) "
            "local off = tostring(m.offLineTime or 0) "
            "CS.UnityEngine.Debug.LogError('ALLY '..n..'\\t'..lv..'\\t'..pw..'\\t'..on..'\\t'..off) "
            "end end"
        )
        rows = []
        for payload in _marker_payloads(_run_lua(self.app, chunk, "ALLY"), "ALLY"):
            parts = payload.split("\t")
            if len(parts) >= 5:
                rows.append(parts[:5])
        return rows

    def render(self, rows) -> None:
        for child in self._scroll.winfo_children():
            child.destroy()
        for col, key in enumerate(self.COLUMNS):
            self.app._tr(CTkLabel(self._scroll, text_color="#888",
                                  font=ctk.CTkFont(weight="bold")), key).grid(
                row=0, column=col, sticky="w", padx=(0, 16), pady=(0, 6))
        if not rows:
            self.app._tr(CTkLabel(self._scroll, text_color="#888"),
                         "alliance.empty").grid(row=1, column=0, columnspan=5,
                                                sticky="w", pady=6)
            self._status_var.set("")
            return
        for r, (name, level, power, online, off) in enumerate(rows, start=1):
            status = self.app._t("alliance.online" if online == "1"
                                 else "alliance.offline")
            seen = "" if online == "1" else self._fmt_seen(off)
            for col, text in enumerate((name, level, _group(power), status, seen)):
                CTkLabel(self._scroll, text=text).grid(
                    row=r, column=col, sticky="w", padx=(0, 16), pady=1)
        self._status_var.set(self.app._t("alliance.count", n=len(rows)))

    def _fmt_seen(self, off_ms: str) -> str:
        try:
            off = int(off_ms)
        except (TypeError, ValueError):
            return ""
        if off <= 0:
            return ""
        import time
        mins = max(0, int((time.time() * 1000 - off) // 60000))
        if mins < 60:
            return self.app._t("alliance.seen_min", n=mins)
        if mins < 1440:
            return self.app._t("alliance.seen_hour", n=mins // 60)
        return self.app._t("alliance.seen_day", n=mins // 1440)


# ---------------------------------------------------------------------------
class ProfileTab(_DataTab):
    """The player card: nick, level, power and the five resource balances (with a
    glyph icon each). Resources reuse the panel's confirmed reader; nick/level/power
    are best-effort."""

    def build(self) -> None:
        body = self._header("tab.profile")
        card = self.app._tr(  # a titled card
            _card(body), "profile.card")
        card.pack(fill="x")
        self._rows: dict = {}
        grid = CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=4, pady=4)
        for r, key in enumerate(("profile.nick", "profile.level", "profile.power")):
            self.app._tr(CTkLabel(grid, text_color="#888"), key).grid(
                row=r, column=0, sticky="w", padx=(0, 12), pady=3)
            var = tk_stringvar(self.app)
            var.set("—")
            CTkLabel(grid, textvariable=var,
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
                row=r, column=1, sticky="w", pady=3)
            self._rows[key] = var

        res = self.app._tr(_card(body), "profile.resources")
        res.pack(fill="x", pady=(10, 0))
        rgrid = CTkFrame(res, fg_color="transparent")
        rgrid.pack(fill="x", padx=4, pady=4)
        self._res: dict = {}
        for i, name in enumerate(RESOURCE_ORDER):
            CTkLabel(rgrid, text=RESOURCE_GLYPHS[name],
                     font=ctk.CTkFont(size=18)).grid(row=i, column=0, padx=(0, 8), pady=2)
            self.app._tr(CTkLabel(rgrid, text_color="#888"),
                         f"profile.res.{name}").grid(row=i, column=1, sticky="w",
                                                     padx=(0, 12))
            var = tk_stringvar(self.app)
            var.set("—")
            CTkLabel(rgrid, textvariable=var).grid(row=i, column=2, sticky="w")
            self._res[name] = var

    def fetch(self):
        data = {"resources": self.app._read_resource_balance()}
        # BEST-EFFORT: nick / level / power off a role manager, each in its own pcall.
        chunk = (
            "local function S(m) local ok, v = pcall(m) "
            "if ok and v ~= nil then return tostring(v) end return '' end "
            "local R = DataCenter.RoleDataManager or DataCenter.PlayerDataManager "
            "local nick = S(function() return R:GetName() end) "
            "if nick == '' then nick = S(function() return R.name end) end "
            "local lv = S(function() return R:GetLevel() end) "
            "if lv == '' then lv = S(function() return R.level end) end "
            "local pw = S(function() return R:GetPower() end) "
            "if pw == '' then pw = S(function() return R.power end) end "
            "CS.UnityEngine.Debug.LogError('PROF '..nick..'\\t'..lv..'\\t'..pw)"
        )
        for payload in _marker_payloads(_run_lua(self.app, chunk, "PROF"), "PROF"):
            parts = payload.split("\t")
            if parts:
                data["nick"] = parts[0]
                data["level"] = parts[1] if len(parts) > 1 else ""
                data["power"] = parts[2] if len(parts) > 2 else ""
            break
        return data

    def render(self, data) -> None:
        self._rows["profile.nick"].set(data.get("nick") or "—")
        self._rows["profile.level"].set(data.get("level") or "—")
        self._rows["profile.power"].set(_group(data.get("power")) or "—")
        balance = data.get("resources") or {}
        for name in RESOURCE_ORDER:
            self._res[name].set(_group(balance.get(name)) if name in balance else "—")
        self._status_var.set("" if balance or data.get("nick")
                             else self.app._t("tabx.no_game"))


# ---------------------------------------------------------------------------
class InventoryTab(_DataTab):
    """The bag: icon (glyph fallback), name, count, description, with a search box
    that filters by name. Items are read best-effort from the item/bag manager."""

    def build(self) -> None:
        top = CTkFrame(self.parent, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 4))
        self.app._tr(CTkLabel(top, font=ctk.CTkFont(size=15, weight="bold")),
                     "tab.inventory").pack(side="left")
        self.app._tr(CTkButton(top, width=12, command=self.refresh),
                     "tabx.refresh").pack(side="right")
        self._status_var = tk_stringvar(self.app)
        CTkLabel(top, textvariable=self._status_var, text_color="#888").pack(
            side="right", padx=8)

        searchrow = CTkFrame(self.parent, fg_color="transparent")
        searchrow.pack(fill="x", padx=10, pady=(0, 6))
        self.app._tr(CTkLabel(searchrow), "inventory.search").pack(side="left")
        self._query = tk_stringvar(self.app)
        self._query.trace_add("write", lambda *_: self._redraw())
        CTkEntry(searchrow, textvariable=self._query).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        self._scroll = ctk.CTkScrollableFrame(self.parent, fg_color="transparent")
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
        for payload in _marker_payloads(_run_lua(self.app, chunk, "ITEM"), "ITEM"):
            parts = payload.split("\t")
            if parts and parts[0]:
                items.append({
                    "name": parts[0],
                    "count": parts[1] if len(parts) > 1 else "",
                    "desc": parts[2] if len(parts) > 2 else "",
                })
        return items

    def render(self, items) -> None:
        self._items = items
        self._status_var.set(self.app._t("inventory.count", n=len(items)) if items
                             else self.app._t("tabx.no_game"))
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
            self.app._tr(CTkLabel(scroll, text_color="#888"),
                         "inventory.empty").grid(row=0, column=0, sticky="w", pady=6)
            return
        for r, it in enumerate(shown):
            CTkLabel(scroll, text="📦", font=ctk.CTkFont(size=16)).grid(
                row=r, column=0, padx=(0, 8), pady=2)
            CTkLabel(scroll, text=it["name"],
                     font=ctk.CTkFont(weight="bold")).grid(
                row=r, column=1, sticky="w", padx=(0, 12))
            CTkLabel(scroll, text=f"×{_group(it['count'])}").grid(
                row=r, column=2, sticky="w", padx=(0, 12))
            if it["desc"]:
                CTkLabel(scroll, text=it["desc"], text_color="#888",
                         wraplength=360, justify="left").grid(
                    row=r, column=3, sticky="w")


# ---------------------------------------------------------------------------
def _card(parent):
    """A bordered card frame (a plain CTkLabelFrame carries a title via _tr)."""
    from .ctk_widgets import CTkLabelFrame
    return CTkLabelFrame(parent, padding=8)


def _group(value) -> str:
    """A number with thousands separators; passes through non-numbers unchanged."""
    if value in (None, ""):
        return ""
    try:
        return f"{int(str(value).replace(',', '').strip()):,}"
    except (TypeError, ValueError):
        return str(value)
