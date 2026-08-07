"""The «Герои» tab: the roster, with icons.

Each hero's id resolves to a sprite pulled out of the game's own bundles where one is
known (tools/hero_icons_map.py); the mapping is incomplete because the config that holds
it is encrypted, so an unknown id draws its number instead of guessing a face.
"""
from __future__ import annotations

from tkinter import ttk

from ..widgets import ScrollableFrame, font as ui_font
from ._data import DataTab, _group, _int, _marker_payloads, _run_lua, _stringvar

class HeroesTab(DataTab):
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

    ID = "heroes"
    TITLE_KEY = "tab.heroes"
    ORDER = 230
    #: Still being written: hidden unless «Разработка» is on (#1273). The mark
    #: comes off when this tab's abilities are proven live and said so in
    #: `docs/farming.md` (`PanelTab.IN_DEVELOPMENT`).
    IN_DEVELOPMENT = True
    LOCALE_NS = ('heroes', 'tabx')

    COLUMNS = ("heroes.col.icon", "heroes.col.name", "heroes.col.level",
               "heroes.col.stars", "heroes.col.squad", "heroes.col.weapon")
    #: A hero with no squad sorts after squads 1..3.
    _NO_SQUAD = 99
    ICON_PX = 32

    def build(self) -> None:
        body = self._header("tab.heroes")
        self._scroll = ScrollableFrame(body)
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
        for payload in _marker_payloads(_run_lua(self.rt, chunk, "HERO"), "HERO"):
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

    def web_cards(self, heroes) -> list:
        """The roster. No icons on the phone yet — they are files the page cannot
        reach without a route of their own, and a name and a level answer the question
        somebody actually asks away from the machine."""
        items = []
        for hero in heroes or ():
            items.append({"text": str(hero.get("name") or "?"),
                          "detail": " · ".join(x for x in (
                              str(hero.get("level") or ""),
                              _group(hero.get("power")) or "") if x)})
        return [{"title": "tab.heroes", "items": items, "search": True,
                 "empty": "tabx.no_game"}]

    def render(self, heroes) -> None:
        for child in self._scroll.winfo_children():
            child.destroy()
        for col, key in enumerate(self.COLUMNS):
            self.rt.tr(ttk.Label(self._scroll, foreground="#888",
                                  font=ui_font(weight="bold")), key).grid(
                row=0, column=col, sticky="w", padx=(0, 16), pady=(0, 6))
        if not heroes:
            self.rt.tr(ttk.Label(self._scroll, foreground="#888"),
                         "heroes.empty").grid(row=1, column=0, columnspan=len(self.COLUMNS),
                                              sticky="w", pady=6)
            self._status_var.set(self.rt.t("tabx.no_game"))
            return
        for r, hero in enumerate(heroes, start=1):
            icon = self._hero_icon(hero["id"])
            if icon is not None:
                ttk.Label(self._scroll, text="", image=icon).grid(
                    row=r, column=0, padx=(0, 16), pady=2)
            else:
                ttk.Label(self._scroll, text="🦸", font=ui_font(size=18)).grid(
                    row=r, column=0, padx=(0, 16), pady=2)
            ttk.Label(self._scroll, text=self._hero_name(hero),
                     font=ui_font(weight="bold")).grid(
                row=r, column=1, sticky="w", padx=(0, 16))
            ttk.Label(self._scroll, text=str(hero["level"] or "—")).grid(
                row=r, column=2, sticky="w", padx=(0, 16))
            ttk.Label(self._scroll, text=(f"⭐×{hero['stars']}" if hero["stars"] else "—")).grid(
                row=r, column=3, sticky="w", padx=(0, 16))
            squad = hero["squad"]
            squad_text = str(squad) if 1 <= squad <= 3 else self.rt.t("heroes.squad_none")
            ttk.Label(self._scroll, text=squad_text).grid(
                row=r, column=4, sticky="w", padx=(0, 16))
            # Weapon column left blank on purpose — a later task fills it.
            ttk.Label(self._scroll, text="—", foreground="#666").grid(
                row=r, column=5, sticky="w")
        self._status_var.set(self.rt.t("heroes.count", n=len(heroes)))

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
        """A cached PhotoImage for the hero's small icon, or ``None`` (unknown id,
        missing file, or no PIL). Callers draw a glyph when this returns ``None``.
        The cache also keeps the PhotoImage alive (Tk does not hold a Python ref)."""
        if hero_id in self._icon_cache:
            return self._icon_cache[hero_id]
        image = None
        try:
            import hero_icons_map
            path = hero_icons_map.icon_path(hero_id, size="small")
            if path is None:
                path = hero_icons_map.icon_path(hero_id, size="big")
            if path:
                from PIL import Image, ImageTk
                pil = Image.open(path).convert("RGBA").resize(
                    (self.ICON_PX, self.ICON_PX))
                image = ImageTk.PhotoImage(pil)
        except Exception:       # noqa: BLE001 — a missing icon is a glyph, never a crash
            image = None
        self._icon_cache[hero_id] = image
        return image


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(HeroesTab))
