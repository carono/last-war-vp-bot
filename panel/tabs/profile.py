"""The «Профиль» tab: this character at a glance.

Name, level, power and the resource balance, read live through the warm daemon. The
balance comes from the runtime rather than from here because the resource tracker tallies
the very same reading (panel/runtime/reads.py).

THE WARZONE CARD IS A SCENARIO'S ANSWER and nothing this tab assembled: it plays
`actions/read_server_info.md` and draws the line that comes back
(docs/research/server-info.md). It is the character's own warzone by default — when it
opened, which day of the server today is, when the game-day turns over — and the box
beside it asks the same question about ANY other warzone, which the game answers without
going there. That is the whole reason it is a field and not a fixed row: the interesting
version of «when did that server start» is always about somebody else's.
"""
from __future__ import annotations

import time
from tkinter import ttk

from ..runtime import reads
from ..widgets import ScrollableFrame, font as ui_font
from ._data import RESOURCE_GLYPHS, RESOURCE_ORDER, DataTab, _card, _group, _marker_payloads, _run_lua, _stringvar

#: The scenario that answers «what does the game say about this warzone», and the
#: variable its answer lands in. One ability, one file (`CLAUDE.md`).
WARZONE_ACTION = "read_server_info"
WARZONE_VARIABLE = "server_info"

#: The rows of the warzone card, in the order they are drawn: the locale key of the
#: label, and the field of the scenario's line it shows.
WARZONE_ROWS = (("profile.warzone.id", "server"),
                ("profile.warzone.name", "name"),
                ("profile.warzone.opened", "open_ms"),
                ("profile.warzone.day", "day"),
                ("profile.warzone.day_end", "day_end_ms"))


def _warzone_fields(line: str) -> dict:
    """The scenario's `k=v k=v …` line as a dict. An unparsable chunk is left out."""
    out = {}
    for chunk in (line or "").split():
        key, sep, value = chunk.partition("=")
        if sep:
            out[key] = value
    return out


def _stamp(ms) -> str:
    """A game-clock millisecond as `YYYY-MM-DD HH:MM UTC`; `—` when there is none.

    The milliseconds come off the GAME's clock, which this machine's is not
    (docs/research/game-clock.md) — so nothing here supplies a «now» of its own, and a
    moment is only ever rendered, never compared with `time.time()`.
    """
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(value / 1000.0))


class ProfileTab(DataTab):
    """The player card: nick, level, power and the five resource balances (with a
    glyph icon each). Resources reuse the panel's confirmed reader; nick/level/power
    are best-effort."""

    ID = "profile"
    TITLE_KEY = "tab.profile"
    ORDER = 210
    #: Still being written: hidden unless «Разработка» is on (#1273). The mark
    #: comes off when this tab's abilities are proven live and said so in
    #: `docs/farming.md` (`PanelTab.IN_DEVELOPMENT`).
    IN_DEVELOPMENT = True
    LOCALE_NS = ('profile', 'tabx')
    #: The warzone card is a scenario's answer, so this tab needs one to play.
    NEEDS = frozenset({"daemon", "actions"})

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        #: Which warzone the card is about: 0 is «the one this character plays in»,
        #: which is the only one the client can answer without asking the server.
        self._warzone_ask = 0

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

        zone = self.rt.tr(_card(body), "profile.warzone")
        zone.pack(fill="x", pady=(10, 0))
        zgrid = ttk.Frame(zone)
        zgrid.pack(fill="x", padx=4, pady=4)
        self._zone: dict = {}
        for r, (key, field) in enumerate(WARZONE_ROWS):
            self.rt.tr(ttk.Label(zgrid, foreground="#888"), key).grid(
                row=r, column=0, sticky="w", padx=(0, 12), pady=3)
            var = _stringvar(self.rt)
            var.set("—")
            ttk.Label(zgrid, textvariable=var).grid(row=r, column=1, sticky="w", pady=3)
            self._zone[field] = var

        ask = ttk.Frame(zone)
        ask.pack(fill="x", padx=4, pady=(0, 6))
        self.rt.tr(ttk.Label(ask, foreground="#888"), "profile.warzone.ask").pack(
            side="left", padx=(0, 8))
        self._zone_entry = ttk.Entry(ask, width=8)
        self._zone_entry.pack(side="left")
        self.rt.tr(ttk.Button(ask, width=12, command=self._ask_warzone),
                   "profile.warzone.go").pack(side="left", padx=6)
        self.rt.tr(ttk.Button(ask, width=12, command=self._ask_own_warzone),
                   "profile.warzone.mine").pack(side="left")

    # -- the warzone question -----------------------------------------------
    def _ask_warzone(self) -> None:
        """Ask about the warzone typed in the box; an empty or silly box asks about ours.

        The number is not validated beyond «is it a number»: which warzones exist is the
        game server's business, and it answers a warzone it does not serve with an error
        that names nothing at all (docs/research/server-info.md), which the scenario turns
        into an honest «unknown» rather than a guess.
        """
        typed = ""
        try:
            typed = self._zone_entry.get().strip()
        except Exception:                   # noqa: BLE001 — a box, never the tab
            typed = ""
        self.ask_warzone(typed)

    def _ask_own_warzone(self) -> None:
        self.ask_warzone("")

    def ask_warzone(self, typed) -> bool:
        """Point the card at a warzone and re-read. `False` when nothing was asked.

        Shared by the window's button and the phone's press, so the two cannot answer
        differently — the phone types into a prompt, the window into a box, and both end
        up here (`CLAUDE.md`: an edit travels in both directions).
        """
        text = str(typed or "").strip()
        try:
            server = int(text) if text else 0
        except ValueError:
            return False
        self._warzone_ask = max(0, server)
        self.refresh()
        return True

    def _read_warzone(self) -> dict:
        """Play the scenario and hand back its line, split into fields.

        Off the Tk thread — `fetch()` is where this is called from — and it asks the game
        exactly once, whatever the card is pointed at: a foreign warzone the client has
        already been told about answers out of its own cache, without another question on
        the wire.
        """
        outcome = self.rt.actions.play(WARZONE_ACTION, {"server": self._warzone_ask},
                                       tag="profile")
        if outcome is None or not getattr(outcome, "ok", False):
            return {}
        ctx = getattr(outcome, "ctx", None)
        return _warzone_fields((getattr(ctx, "vars", {}) or {}).get(WARZONE_VARIABLE))

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
        data["warzone"] = self._read_warzone()
        return data

    @staticmethod
    def _zone_value(zone: dict, field: str) -> str:
        """One row of the warzone card as it is shown — dates rendered, the rest as read."""
        raw = (zone or {}).get(field)
        if field.endswith("_ms"):
            return _stamp(raw)
        if raw in (None, "", "-"):
            return "—"
        return str(raw)

    def web_cards(self, data) -> list:
        """Who this character is, what is in the bank, and which warzone all of it is in."""
        who = [("profile.nick", data.get("nick")),
               ("profile.level", data.get("level")),
               ("profile.power", _group(data.get("power")))]
        balance = data.get("resources") or {}
        zone = data.get("warzone") or {}
        return [
            {"title": "tab.profile",
             "rows": [{"label": key, "value": str(value or "—")} for key, value in who]},
            {"title": "profile.resources",
             "rows": [{"label": f"profile.res.{name}",
                       "value": _group(balance.get(name)) if name in balance else "—"}
                      for name in RESOURCE_ORDER]},
            {"title": "profile.warzone",
             "rows": [{"label": key, "value": self._zone_value(zone, field)}
                      for key, field in WARZONE_ROWS]},
        ]

    def web_view(self) -> "dict | None":
        """The tab's cards, plus the one press the window's box is — asking about
        another warzone. The phone types it into a prompt (`panel/web/static/app.js`)."""
        view = super().web_view()
        if view is not None:
            view.setdefault("actions", []).append(
                {"id": "warzone", "label": "profile.warzone.go",
                 "prompt": "profile.warzone.ask",
                 "value": str(getattr(self, "_warzone_ask", 0) or "")})
        return view

    def web_press(self, action: str, args: dict) -> dict:
        """«Обновить», and the warzone question the window has beside its card."""
        if action != "warzone":
            return super().web_press(action, args)
        if not self.ask_warzone((args or {}).get("text")):
            return {"error": "refused", "reason": "profile.warzone.not_a_number"}
        return {"ok": True, "busy": True}

    def render(self, data) -> None:
        self._rows["profile.nick"].set(data.get("nick") or "—")
        self._rows["profile.level"].set(data.get("level") or "—")
        self._rows["profile.power"].set(_group(data.get("power")) or "—")
        balance = data.get("resources") or {}
        for name in RESOURCE_ORDER:
            self._res[name].set(_group(balance.get(name)) if name in balance else "—")
        zone = data.get("warzone") or {}
        for _key, field in WARZONE_ROWS:
            self._zone[field].set(self._zone_value(zone, field))
        self._status_var.set("" if balance or data.get("nick")
                             else self.rt.t("tabx.no_game"))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(ProfileTab))
