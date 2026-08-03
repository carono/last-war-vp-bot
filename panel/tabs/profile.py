"""The «Профиль» tab: this character at a glance.

Name, level, power and the resource balance, read live through the warm daemon. The
balance comes from the runtime rather than from here because the resource tracker tallies
the very same reading (panel/runtime/reads.py).
"""
from __future__ import annotations

from tkinter import ttk

from ..runtime import reads
from ..widgets import ScrollableFrame, font as ui_font
from ._data import RESOURCE_GLYPHS, RESOURCE_ORDER, DataTab, _card, _group, _marker_payloads, _run_lua, _stringvar


class ProfileTab(DataTab):
    """The player card: nick, level, power and the five resource balances (with a
    glyph icon each). Resources reuse the panel's confirmed reader; nick/level/power
    are best-effort."""

    ID = "profile"
    TITLE_KEY = "tab.profile"
    ORDER = 210
    LOCALE_NS = ('profile', 'tabx')

    def build(self) -> None:
        body = self._header("tab.profile")
        card = self.rt.tr(  # a titled card
            _card(body), "profile.card")
        card.pack(fill="x")
        self._rows: dict = {}
        grid = ttk.Frame(card)
        grid.pack(fill="x", padx=4, pady=4)
        for r, key in enumerate(("profile.nick", "profile.level", "profile.power")):
            self.rt.tr(ttk.Label(grid, foreground="#888"), key).grid(
                row=r, column=0, sticky="w", padx=(0, 12), pady=3)
            var = _stringvar(self.rt)
            var.set("—")
            ttk.Label(grid, textvariable=var,
                     font=ui_font(size=14, weight="bold")).grid(
                row=r, column=1, sticky="w", pady=3)
            self._rows[key] = var

        res = self.rt.tr(_card(body), "profile.resources")
        res.pack(fill="x", pady=(10, 0))
        rgrid = ttk.Frame(res)
        rgrid.pack(fill="x", padx=4, pady=4)
        self._res: dict = {}
        for i, name in enumerate(RESOURCE_ORDER):
            ttk.Label(rgrid, text=RESOURCE_GLYPHS[name],
                     font=ui_font(size=18)).grid(row=i, column=0, padx=(0, 8), pady=2)
            self.rt.tr(ttk.Label(rgrid, foreground="#888"),
                         f"profile.res.{name}").grid(row=i, column=1, sticky="w",
                                                     padx=(0, 12))
            var = _stringvar(self.rt)
            var.set("—")
            ttk.Label(rgrid, textvariable=var).grid(row=i, column=2, sticky="w")
            self._res[name] = var

    def fetch(self):
        data = {"resources": reads.resource_balance(self.rt.game)}
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
        for payload in _marker_payloads(_run_lua(self.rt, chunk, "PROF"), "PROF"):
            parts = payload.split("\t")
            if parts:
                data["nick"] = parts[0]
                data["level"] = parts[1] if len(parts) > 1 else ""
                data["power"] = parts[2] if len(parts) > 2 else ""
            break
        return data

    def web_cards(self, data) -> list:
        """Who this character is, and what is in the bank."""
        who = [("profile.nick", data.get("nick")),
               ("profile.level", data.get("level")),
               ("profile.power", _group(data.get("power")))]
        balance = data.get("resources") or {}
        return [
            {"title": "tab.profile",
             "rows": [{"label": key, "value": str(value or "—")} for key, value in who]},
            {"title": "profile.resources",
             "rows": [{"label": f"profile.res.{name}",
                       "value": _group(balance.get(name)) if name in balance else "—"}
                      for name in RESOURCE_ORDER]},
        ]

    def render(self, data) -> None:
        self._rows["profile.nick"].set(data.get("nick") or "—")
        self._rows["profile.level"].set(data.get("level") or "—")
        self._rows["profile.power"].set(_group(data.get("power")) or "—")
        balance = data.get("resources") or {}
        for name in RESOURCE_ORDER:
            self._res[name].set(_group(balance.get(name)) if name in balance else "—")
        self._status_var.set("" if balance or data.get("nick")
                             else self.rt.t("tabx.no_game"))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(ProfileTab))
