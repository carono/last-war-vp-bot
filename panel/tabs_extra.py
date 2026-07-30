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

from .ctk_widgets import (CTkButton, CTkCheckBox, CTkEntry, CTkFrame, CTkLabel,
                          install_numeric_field, numeric_spinbox)
from .ctk_widgets import CTkLabelFrame

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
class HeroesTab(_DataTab):
    """The hero roster — icon / name / level / stars / squad, plus an empty «Weapon»
    column reserved for a later task. Rows are sorted by squad (1→2→3→no squad),
    then by stars descending, then by level descending, mirroring the in-game
    hero screen.

    BEST-EFFORT, exactly like the Alliance and Inventory tabs: the hero and
    formation managers are not confirmed against a live client, so every read is
    wrapped in ``pcall`` and a field that cannot be read is simply omitted. The
    ``heroId → icon`` mapping is the confirmed one from tools/lib/hero_icons_map.py;
    heroes whose id is not in that table fall back to a glyph and the game's own
    name (or ``#id`` when even that is missing)."""

    COLUMNS = ("heroes.col.icon", "heroes.col.name", "heroes.col.level",
               "heroes.col.stars", "heroes.col.squad", "heroes.col.weapon")
    #: A hero with no squad sorts after squads 1..3.
    _NO_SQUAD = 99
    ICON_PX = 32

    def build(self) -> None:
        body = self._header("tab.heroes")
        self._scroll = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True)
        self._icon_cache: dict = {}

    def fetch(self):
        # BEST-EFFORT: read the roster as «HERO id\tname\tlevel\tstars\tsquad» lines.
        # Squad membership is looked up first (heroId → 1/2/3) off the formation
        # manager, then every hero is dumped with its squad (0 = benched).
        chunk = (
            "local function num(v) return tonumber(v) or 0 end "
            "local squadOf = {} "
            "local F = DataCenter.HeroFormationDataManager or "
            "DataCenter.FormationDataManager or DataCenter.LineupDataManager "
            "if F ~= nil then for idx = 1, 3 do "
            "local ok, arr = pcall(function() return F:GetFormationHeroList(idx) end) "
            "if not ok or type(arr) ~= 'table' then "
            "ok, arr = pcall(function() return F:GetHeroListByFormation(idx) end) end "
            "if not ok or type(arr) ~= 'table' then "
            "ok, arr = pcall(function() return F:GetHeroesByIndex(idx) end) end "
            "if type(arr) == 'table' then for _, h in ipairs(arr) do "
            "local id = num(type(h) == 'table' and (h.heroId or h.id or h.cfgId) or h) "
            "if id ~= 0 then squadOf[id] = idx end "
            "end end end end "
            "local M = DataCenter.HeroDataManager or DataCenter.HeroInfoDataManager or "
            "DataCenter.HeroManager "
            "local ok, list = pcall(function() return M:GetHeroList() end) "
            "if not ok or type(list) ~= 'table' then "
            "ok, list = pcall(function() return M:GetAllHero() end) end "
            "if not ok or type(list) ~= 'table' then "
            "ok, list = pcall(function() return M:GetAllHeroList() end) end "
            "if not ok or type(list) ~= 'table' then "
            "ok, list = pcall(function() return M.heroList end) end "
            "if type(list) == 'table' then for _, h in pairs(list) do "
            "if type(h) == 'table' then "
            "local id = num(h.heroId or h.id or h.cfgId) "
            "local nm = tostring(h.name or h.heroName or '') "
            "local lv = num(h.level or h.lv or h.heroLevel) "
            "local st = num(h.star or h.starLevel or h.starLv or h.grade or h.quality) "
            "local sq = squadOf[id] or 0 "
            "CS.UnityEngine.Debug.LogError('HERO '..id..'\\t'..nm..'\\t'..lv..'\\t'..st..'\\t'..sq) "
            "end end end"
        )
        heroes = []
        for payload in _marker_payloads(_run_lua(self.app, chunk, "HERO"), "HERO"):
            parts = payload.split("\t")
            if len(parts) < 5:
                continue
            heroes.append({
                "id": _int(parts[0]),
                "name": parts[1],
                "level": _int(parts[2]),
                "stars": _int(parts[3]),
                "squad": _int(parts[4]),
            })
        heroes.sort(key=lambda h: (h["squad"] if 1 <= h["squad"] <= 3 else self._NO_SQUAD,
                                   -h["stars"], -h["level"]))
        return heroes

    def render(self, heroes) -> None:
        for child in self._scroll.winfo_children():
            child.destroy()
        for col, key in enumerate(self.COLUMNS):
            self.app._tr(CTkLabel(self._scroll, text_color="#888",
                                  font=ctk.CTkFont(weight="bold")), key).grid(
                row=0, column=col, sticky="w", padx=(0, 16), pady=(0, 6))
        if not heroes:
            self.app._tr(CTkLabel(self._scroll, text_color="#888"),
                         "heroes.empty").grid(row=1, column=0, columnspan=len(self.COLUMNS),
                                              sticky="w", pady=6)
            self._status_var.set(self.app._t("tabx.no_game"))
            return
        for r, hero in enumerate(heroes, start=1):
            icon = self._hero_icon(hero["id"])
            if icon is not None:
                CTkLabel(self._scroll, text="", image=icon).grid(
                    row=r, column=0, padx=(0, 16), pady=2)
            else:
                CTkLabel(self._scroll, text="🦸", font=ctk.CTkFont(size=18)).grid(
                    row=r, column=0, padx=(0, 16), pady=2)
            CTkLabel(self._scroll, text=self._hero_name(hero),
                     font=ctk.CTkFont(weight="bold")).grid(
                row=r, column=1, sticky="w", padx=(0, 16))
            CTkLabel(self._scroll, text=str(hero["level"] or "—")).grid(
                row=r, column=2, sticky="w", padx=(0, 16))
            CTkLabel(self._scroll, text=(f"⭐×{hero['stars']}" if hero["stars"] else "—")).grid(
                row=r, column=3, sticky="w", padx=(0, 16))
            squad = hero["squad"]
            squad_text = str(squad) if 1 <= squad <= 3 else self.app._t("heroes.squad_none")
            CTkLabel(self._scroll, text=squad_text).grid(
                row=r, column=4, sticky="w", padx=(0, 16))
            # Weapon column left blank on purpose — a later task fills it.
            CTkLabel(self._scroll, text="—", text_color="#666").grid(
                row=r, column=5, sticky="w")
        self._status_var.set(self.app._t("heroes.count", n=len(heroes)))

    def _hero_name(self, hero) -> str:
        """The game's own name, else the confirmed internal resName, else ``#id``."""
        if hero["name"]:
            return hero["name"]
        try:
            import hero_icons_map
            res = hero_icons_map.resname_for(hero["id"])
        except Exception:       # noqa: BLE001
            res = None
        if res:
            return res.replace("_", " ")
        return f"#{hero['id']}"

    def _hero_icon(self, hero_id: int):
        """A cached CTkImage for the hero's small icon, or ``None`` (unknown id,
        missing file, or no PIL). Callers draw a glyph when this returns ``None``."""
        if hero_id in self._icon_cache:
            return self._icon_cache[hero_id]
        image = None
        try:
            import hero_icons_map
            path = hero_icons_map.icon_path(hero_id, size="small")
            if path is None:
                path = hero_icons_map.icon_path(hero_id, size="big")
            if path:
                from PIL import Image
                pil = Image.open(path).convert("RGBA")
                image = ctk.CTkImage(light_image=pil, dark_image=pil,
                                     size=(self.ICON_PX, self.ICON_PX))
        except Exception:       # noqa: BLE001 — a missing icon is a glyph, never a crash
            image = None
        self._icon_cache[hero_id] = image
        return image


# ---------------------------------------------------------------------------
class AccountsTab(_DataTab):
    """The characters this login can switch between — the in-game «Account» screen.

    Every character you have logged into is listed with its server, zone, HQ level
    and name; the one you are playing right now is highlighted and carries no button.
    Each of the others has a «Switch» button that reconnects the client to that
    character — exactly what tapping the row in the game does. Because a switch tears
    down the current session and reconnects, the button asks for confirmation first.

    The read is CONFIRMED against a live client (tools/account_switch.py); the switch
    reproduces the game's own select handler. Degrades to an empty state with no
    daemon, no game, or before the account manager has loaded."""

    COLUMNS = ("accounts.col.name", "accounts.col.server", "accounts.col.zone",
               "accounts.col.level", "accounts.col.action")
    #: A faint tint on the row of the character currently in play.
    _CURRENT_BG = "#2a4d33"

    def build(self) -> None:
        body = self._header("tab.accounts")
        self._scroll = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True)
        self.app._tr(CTkLabel(self.parent, text_color="#888", wraplength=640,
                              justify="left"),
                     "accounts.hint").pack(anchor="w", padx=10, pady=(0, 10))

    def fetch(self):
        try:
            import account_switch      # tools/ is on sys.path once the panel started
            import lua_client
            ev = lua_client.get_evaluator(port=self.app._daemon_port())
            return account_switch.read_accounts(ev)
        except Exception:              # noqa: BLE001 — a failed read is an empty tab
            return []

    def render(self, rows) -> None:
        for child in self._scroll.winfo_children():
            child.destroy()
        for col, key in enumerate(self.COLUMNS):
            self.app._tr(CTkLabel(self._scroll, text_color="#888",
                                  font=ctk.CTkFont(weight="bold")), key).grid(
                row=0, column=col, sticky="w", padx=(0, 16), pady=(0, 6))
        if not rows:
            self.app._tr(CTkLabel(self._scroll, text_color="#888"),
                         "accounts.empty").grid(row=1, column=0, columnspan=len(self.COLUMNS),
                                                sticky="w", pady=6)
            self._status_var.set(self.app._t("tabx.no_game"))
            return
        for r, acc in enumerate(rows, start=1):
            current = acc.get("is_current")
            name = acc.get("nickname") or f"#{acc.get('gameUid', '')}"
            weight = "bold" if current else "normal"
            CTkLabel(self._scroll, text=name,
                     font=ctk.CTkFont(weight=weight)).grid(
                row=r, column=0, sticky="w", padx=(0, 16), pady=2)
            CTkLabel(self._scroll, text=str(acc.get("serverid", ""))).grid(
                row=r, column=1, sticky="w", padx=(0, 16))
            CTkLabel(self._scroll, text=acc.get("zone", ""), text_color="#888").grid(
                row=r, column=2, sticky="w", padx=(0, 16))
            CTkLabel(self._scroll, text=str(acc.get("level") or "—")).grid(
                row=r, column=3, sticky="w", padx=(0, 16))
            if current:
                self.app._tr(CTkLabel(self._scroll, text_color="#5cd679",
                                      font=ctk.CTkFont(weight="bold")),
                             "accounts.current").grid(row=r, column=4, sticky="w")
            else:
                self.app._tr(
                    CTkButton(self._scroll, width=12,
                              command=lambda a=acc: self._switch(a)),
                    "accounts.switch").grid(row=r, column=4, sticky="w")
        n = sum(1 for a in rows if a.get("is_current"))
        self._status_var.set(self.app._t("accounts.count", n=len(rows) - n))

    def _switch(self, acc: dict) -> None:
        """Confirm, then reconnect the client to ``acc`` on a background thread."""
        if self._busy:
            return
        from tkinter import messagebox
        name = acc.get("nickname") or acc.get("serverid")
        if not messagebox.askyesno(
                self.app._t("tab.accounts"),
                self.app._t("accounts.confirm", name=name, server=acc.get("serverid")),
                parent=self.app):
            return
        self._busy = True
        self._status_var.set(self.app._t("accounts.switching"))
        serverid = acc.get("serverid")
        threading.Thread(target=self._switch_work, args=(serverid, name),
                         daemon=True).start()

    def _switch_work(self, serverid, name) -> None:
        state = ""
        try:
            import account_switch
            import lua_client
            ev = lua_client.get_evaluator(port=self.app._daemon_port())
            state = account_switch.switch_account(ev, serverid)
        except Exception:              # noqa: BLE001
            state = ""
        self.app.after(0, lambda: self._switch_done(serverid, name, state))

    def _switch_done(self, serverid, name, state) -> None:
        self._busy = False
        if state == "sent":
            self.app._log_put(self.app._t("accounts.switched", name=name,
                                          server=serverid))
        else:
            self.app._log_put(self.app._t("accounts.switch_fail", name=name,
                                          state=state or "?"))
        # The client is reconnecting; give it a moment, then reread the list.
        self.app.after(4000, self.refresh)


# ---------------------------------------------------------------------------
# The elite-monster level a created rally may target, and the squads offered. Kept
# in step with panel/__main__.py's RALLY_ELITE_* / RALLY_SQUADS (the «Авторалли»
# settings page uses the same range and slots).
RALLY_ELITE_MIN, RALLY_ELITE_MAX = 1, 35
RALLY_SQUADS = (1, 2, 3, 4)
# A «Роковая Элита» rally is an ordinary-monster rally, so it counts against the
# "monster" daily cap in panel/rally_limits.py (DEFAULT_RALLY_LIMITS).
RALLY_ELITE_TYPE = "monster"
# Seconds to pause between two sends so the previous banner settles before the next
# find; interruptible by Stop.
RALLY_BETWEEN_S = 6.0


class _Stopped(Exception):
    """Raised inside the run loop when Stop was pressed — unwinds to the finally."""


class RallyTab:
    """The «Ралли» tab: raise a rally on a «Роковая Элита», one squad each, N times.

    The player picks an elite level, ticks the squads that should each raise a rally,
    and a repeat count; «Запустить» then loops «search the map «лупа» for an elite of
    that level → raise the rally with the next squad», N times over, and «Стоп»
    interrupts it. A status line narrates each step and the daily per-type cap
    (panel/rally_limits.py) is honoured — a run stops when the «monster» budget for
    today is spent.

    The game work is tools/rally_create.py (search + create); this tab is the loop, the
    controls and the bookkeeping around it. It runs on a background thread, takes the
    panel's shared game-busy flag for each send so it never races the timers or a jump,
    and touches Tk only through ``app.after``.

    ⚠ The create step is UNPROVEN (the «Стягивание» create wire was never sniffed —
    tools/rally_create.py). The tab is fully usable; whether a banner actually goes out
    must be confirmed in the live game.
    """

    def __init__(self, app, parent):
        self.app = app
        self.parent = parent
        self._stop = None          # threading.Event while a run is in flight, else None
        self._done = 0             # rallies raised in the current/last run (for the status)
        import tkinter as tk
        self._level_var = tk.StringVar(master=app, value=str(RALLY_ELITE_MIN))
        self._repeats_var = tk.StringVar(master=app, value="1")
        self._squad_vars: dict[int, tk.BooleanVar] = {
            s: tk.BooleanVar(master=app, value=False) for s in RALLY_SQUADS}
        self._status_var = tk_stringvar(app)
        self.build()

    # -- UI -----------------------------------------------------------------
    def build(self) -> None:
        bar = CTkFrame(self.parent, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.app._tr(CTkLabel(bar, font=ctk.CTkFont(size=15, weight="bold")),
                     "tab.rally").pack(side="left")

        form = CTkLabelFrame(self.parent, padding=8)
        self.app._tr(form, "rally_tab.frame")
        form.pack(fill="x", padx=10, pady=(0, 8))

        lrow = CTkFrame(form)
        lrow.pack(fill="x")
        self.app._tr(CTkLabel(lrow), "rally_tab.level").pack(side="left", padx=(0, 6))
        numeric_spinbox(lrow, from_=RALLY_ELITE_MIN, to=RALLY_ELITE_MAX, width=5,
                        textvariable=self._level_var).pack(side="left")

        srow = CTkFrame(form)
        srow.pack(fill="x", pady=(6, 0))
        self.app._tr(CTkLabel(srow), "rally_tab.squads").pack(side="left", padx=(0, 6))
        for squad in RALLY_SQUADS:
            CTkCheckBox(srow, text=str(squad),
                        variable=self._squad_vars[squad]).pack(side="left", padx=4)

        rrow = CTkFrame(form)
        rrow.pack(fill="x", pady=(6, 0))
        self.app._tr(CTkLabel(rrow), "rally_tab.repeats").pack(side="left", padx=(0, 6))
        # The task asks for install_numeric_field specifically: a plain entry made
        # digits-only (no bounds), unlike the level's bounded spinbox.
        entry = CTkEntry(rrow, width=6, textvariable=self._repeats_var)
        install_numeric_field(entry)
        entry.pack(side="left")

        brow = CTkFrame(form)
        brow.pack(fill="x", pady=(8, 0))
        self._launch_btn = self.app._tr(
            CTkButton(brow, command=self._launch), "rally_tab.launch")
        self._launch_btn.pack(side="left")
        self._stop_btn = self.app._tr(
            CTkButton(brow, command=self._stop_run), "rally_tab.stop")
        self._stop_btn.pack(side="left", padx=(6, 0))
        self._set_running(False)

        CTkLabel(form, textvariable=self._status_var, text_color="#888").pack(
            anchor="w", pady=(8, 0))
        self.app._tr(CTkLabel(self.parent, text_color="#888", wraplength=640,
                              justify="left"), "rally_tab.hint").pack(
            anchor="w", padx=10, pady=(0, 10))

    # -- reading the controls ----------------------------------------------
    def _level(self) -> int:
        try:
            level = int(self._level_var.get())
        except (TypeError, ValueError):
            return RALLY_ELITE_MIN
        return max(RALLY_ELITE_MIN, min(RALLY_ELITE_MAX, level))

    def _repeats(self) -> int:
        try:
            return max(1, int(self._repeats_var.get()))
        except (TypeError, ValueError):
            return 1

    def _selected_squads(self) -> list:
        return [s for s in RALLY_SQUADS if self._squad_vars[s].get()]

    # -- start / stop -------------------------------------------------------
    def _launch(self) -> None:
        if self._stop is not None:                 # a run is already in flight
            return
        squads = self._selected_squads()
        if not squads:
            self._status("rally_tab.no_squads")
            return
        self._stop = threading.Event()
        self._done = 0
        self._set_running(True)
        threading.Thread(
            target=self._run_loop,
            args=(self._stop, self._level(), squads, self._repeats()),
            daemon=True).start()

    def _stop_run(self) -> None:
        if self._stop is not None:
            self._stop.set()

    def _set_running(self, running: bool) -> None:
        """Enable Stop and disable Launch while a run is in flight (Tk thread)."""
        try:
            self._launch_btn.configure(state="disabled" if running else "normal")
            self._stop_btn.configure(state="normal" if running else "disabled")
        except Exception:                          # noqa: BLE001 — widget may be gone
            pass

    # -- the loop -----------------------------------------------------------
    def _run_loop(self, stop, level, squads, repeats) -> None:
        """find elite of `level` → raise a rally with each squad, `repeats` times over.

        One send at a time under the panel's game-busy flag; the daily «monster» cap
        gates it and Stop unwinds it. Runs off the Tk thread; all UI via `app.after`.
        """
        total = repeats * len(squads)
        try:
            from . import rally_limits as rl
            limits = rl.load_limits(self.app._profiles.rally_limits_json())
            counts = rl.load_counts(self.app._profiles.rally_counts_json())
            for rep in range(1, repeats + 1):
                for squad in squads:
                    if stop.is_set():
                        raise _Stopped
                    if not counts.allowed(RALLY_ELITE_TYPE, limits):
                        self._status("rally_tab.capped",
                                     cap=limits.limit_for(RALLY_ELITE_TYPE))
                        raise _Stopped
                    self._status("rally_tab.searching", level=level, rep=rep, total=repeats)
                    res = self._one_send(stop, level, squad)
                    if res is None:                # Stop pressed while waiting for busy
                        raise _Stopped
                    if res.get("ok"):
                        counts = counts.record(RALLY_ELITE_TYPE)
                        rl.save_counts(counts, self.app._profiles.rally_counts_json())
                        self._done += 1
                        self._log("rally_tab.raised", squad=squad, level=level)
                        self._status("rally_tab.progress",
                                     done=self._done, total=total, squad=squad)
                    elif res.get("reason") == "no_elite":
                        self._status("rally_tab.no_elite", level=level)
                    elif res.get("reason") == "no_formation":
                        self._status("rally_tab.no_formation", squad=squad)
                    else:
                        self._status("rally_tab.not_armed", squad=squad)
                    if stop.wait(RALLY_BETWEEN_S):
                        raise _Stopped
            self._status("rally_tab.finished", done=self._done)
        except _Stopped:
            self._status("rally_tab.stopped", done=self._done)
        except Exception as exc:                   # noqa: BLE001 — never crash the panel
            self._log("rally_tab.error", error=exc)
            self._status("rally_tab.error_short")
        finally:
            self._stop = None
            self.app.after(0, lambda: self._set_running(False))

    def _one_send(self, stop, level, squad):
        """One find+create under the shared busy flag. ``None`` if Stop won the wait.

        Waits (interruptibly) for the game-busy flag rather than skipping the
        iteration, so a timer coming due does not cost a repeat.
        """
        while not self.app._claim_busy():
            self._status("rally_tab.busy")
            if stop.wait(2.0):
                return None
        try:
            import lua_client
            import rally_create
            ev = lua_client.get_evaluator(port=self.app._daemon_port())
            try:
                return rally_create.create_on_level(ev, level, squad)
            finally:
                try:
                    ev.close()
                except Exception:                  # noqa: BLE001
                    pass
        finally:
            self.app._release_busy()

    # -- talking to the panel (always from the worker thread) ---------------
    def _status(self, key: str, **fmt) -> None:
        text = self.app._t(key, **fmt)
        self.app.after(0, lambda: self._status_var.set(text))

    def _log(self, key: str, **fmt) -> None:
        self.app.after(0, lambda: self.app._say("rally", key, **fmt))


# ---------------------------------------------------------------------------
def _card(parent):
    """A bordered card frame (a plain CTkLabelFrame carries a title via _tr)."""
    from .ctk_widgets import CTkLabelFrame
    return CTkLabelFrame(parent, padding=8)


def _int(value) -> int:
    """Parse an integer, returning 0 on anything unparseable."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _group(value) -> str:
    """A number with thousands separators; passes through non-numbers unchanged."""
    if value in (None, ""):
        return ""
    try:
        return f"{int(str(value).replace(',', '').strip()):,}"
    except (TypeError, ValueError):
        return str(value)
