"""The «Профиль» tab: this character at a glance.

Name, level, power and the resource balance, read live through the warm daemon. The
balance comes from the runtime rather than from here because the resource tracker tallies
the very same reading (panel/runtime/reads.py).

THE LIVE STOCK IS THIS TAB'S, and it used to be the front page's (#1990, second pass).
It moved because «Состояние» answers one question — is the client alive and does the
server answer — and a balance is not part of it, while «this character at a glance» is
exactly where a balance belongs. What moved with it is the EAR: `BaseResources.state()`
is what subscribes to `push.resource.item.update` and what marks the card as looked at,
so the subscription now rises when somebody opens THIS screen and is given back two
minutes after the last look (`panel/runtime/resources.py`). Had only the card moved, the
front page would have gone on paying for a capture nobody was reading and this screen
would have drawn a balance nothing was updating.

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
from urllib.parse import quote

from ._data import (RESOURCE_GLYPHS, RESOURCE_ORDER, DataTab, _card, _group,
                    _short, _stringvar)

#: The scenario that answers «what does the game say about this warzone», and the
#: variable its answer lands in. One ability, one file (`CLAUDE.md`).
WARZONE_ACTION = "read_server_info"
WARZONE_VARIABLE = "server_info"

#: The scenario that answers «who is this character» — name, HQ level and power — and the
#: variable its answer lands in. One ability, one file (`CLAUDE.md`).
CARD_ACTION = "read_player_profile"
CARD_VARIABLE = "player_card"

#: The fields of the scenario's line, in the order it writes them. The tab's own three
#: rows are the first three; the rest are drawn on the phone's card (`CLAUDE.md`: while
#: the window is being retired, new goes only into the web).
CARD_FIELDS = ("nick", "level", "power", "alliance",
               "stamina", "stamina_full_ms", "reg_ms")

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
    glyph icon each). Both readings are a scenario's answer — `read_player_profile.md`
    for the character, `read_base_resources.md` behind the runtime's balance."""

    ID = "profile"
    TITLE_KEY = "tab.profile"
    ORDER = 210
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
                                      human=True,
                                       tag="profile")
        if outcome is None or not getattr(outcome, "ok", False):
            return {}
        ctx = getattr(outcome, "ctx", None)
        return _warzone_fields((getattr(ctx, "vars", {}) or {}).get(WARZONE_VARIABLE))

    def _read_card(self) -> dict:
        """Play the character-card scenario and hand back its three fields.

        Off the Tk thread, like every other read here. What used to be in its place was a
        hand-written chunk from before «everything is a scenario»: it asked
        `DataCenter.RoleDataManager` (and `PlayerDataManager`) for `GetName` / `GetLevel`
        / `GetPower`, each in its own `pcall`, and neither manager exists in this client —
        so every branch fell through and the card drew three dashes for as long as it had
        existed (#1991, the same lesson `panel/runtime/reads.py` records for the balance).
        """
        outcome = self.rt.actions.play(CARD_ACTION, human=True, tag="profile")
        if outcome is None or not getattr(outcome, "ok", False):
            return {}
        ctx = getattr(outcome, "ctx", None)
        line = (getattr(ctx, "vars", {}) or {}).get(CARD_VARIABLE) or ""
        parts = str(line).split(";;")
        if len(parts) < len(CARD_FIELDS) or not any(part.strip() for part in parts):
            return {}
        return {name: parts[i].strip() for i, name in enumerate(CARD_FIELDS)}

    def fetch(self):
        data = {"resources": reads.resource_balance(self.rt)}
        data.update(self._read_card())
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

    def _energy(self, data) -> str:
        """The energy purse, and when it fills — one row, because they are one fact.

        The purse refills with TIME, so this is the one reading on the card that is stale
        the moment it is drawn; the moment it is full comes from the game beside it, which
        is what makes the number worth anything. A purse that is already full says so
        rather than showing an epoch of 0.
        """
        purse = str(data.get("stamina") or "").strip()
        if not purse:
            return "—"
        try:
            full = int(data.get("stamina_full_ms") or 0)
        except (TypeError, ValueError):
            full = 0
        if full <= 0:
            return self.t("profile.stamina.full_now", n=purse)
        return self.t("profile.stamina.filling", n=purse, when=_stamp(full))

    def web_cards(self, data) -> list:
        """Who this character is, what is in the bank, and which warzone all of it is in.

        THE PHONE'S CARD CARRIES MORE THAN THE WINDOW'S, and that is the migration rather
        than a divergence (`CLAUDE.md`: while Tk is being retired, new goes only into the
        web). Everything added here is a thing the GAME states — the alliance's tag and
        name as the game itself composes them, the energy purse with the moment it fills,
        the day the character was registered. Nothing is worked out here: the fractional
        «days played» the client also offers would have to be rounded to be shown, and a
        rounded number is the panel's arithmetic wearing the game's authority.
        """
        who = [("profile.nick", data.get("nick")),
               ("profile.level", data.get("level")),
               ("profile.power", _group(data.get("power"))),
               ("profile.alliance", data.get("alliance")),
               ("profile.stamina", self._energy(data) if data else None),
               ("profile.registered", _stamp(data.get("reg_ms")) if data else None)]
        zone = data.get("warzone") or {}
        # …and no card of the five tracker resources: the LIVE stock card
        # (:meth:`_stock_card`) says the same numbers and eight more, with the game's own
        # name on each and an age under them. Two lists of the same balance on one screen
        # is one list too many, and the first time they disagreed there would be nothing
        # to settle it with.
        return [
            {"title": "tab.profile",
             "rows": [{"label": key, "value": str(value or "—")} for key, value in who]},
            {"title": "profile.warzone",
             "rows": [{"label": key, "value": self._zone_value(zone, field)}
                      for key, field in WARZONE_ROWS]},
        ]

    def _stock_card(self) -> "dict | None":
        """WHAT THE BASE IS HOLDING, live — the card that used to open «Состояние».

        Every row is `actions/read_base_resources.md`'s answer said back, and the NAME is
        the game's own, already in the player's language: nothing here maps a resource
        onto a word of the panel's, which is the only way «золото» and «хлеб» can be
        right given that the client's own field names call them `wood` and `money`.

        THERE IS NO «ОБНОВИТЬ» ON IT and it is not on a clock either. Asking for it is
        what raises the ear on `push.resource.item.update` and what keeps it up
        (`panel/runtime/resources.py`) — so this call IS the subscription, and the card
        re-reads when the game says a balance moved. The line under the heading says how
        old the reading is, because a number with no age on it cannot be told from one
        that stopped moving an hour ago; the note above it says the ear is up, which is
        the difference between «ничего не менялось» and «никто не смотрел».

        Reads no game on this thread: `state()` answers out of memory and books the play
        on a worker, which is the contract every screen is held to (`panel/tabs/base.py`).
        """
        try:
            stock = self.rt.resources.state() or {}
        except Exception:                # noqa: BLE001 — one card, never the screen
            return None
        rows = stock.get("rows") or []
        age = stock.get("age", -1)
        if stock.get("reading"):
            flow = {"key": "web.ui.res.reading", "fmt": {}}
        elif age is None or age < 0:
            flow = {"key": "web.ui.res.never", "fmt": {}}
        else:
            flow = {"key": "web.ui.res.age", "fmt": {"sec": int(round(age))}}
        items = []
        for row in rows:
            # DATA, not keys: the name is the game's, and the count is grouped here
            # rather than in the browser because the same card is drawn in both.
            detail = _group(row.get("count"))
            if row.get("max"):
                detail += " " + self.t("web.ui.res.cap", max=_group(row.get("max")))
            if row.get("per_hour"):
                detail += " · " + self.t("web.ui.res.rate",
                                         rate=_group(row.get("per_hour")))
            item = {"text": str(row.get("name") or ""), "detail": detail,
                    # THE HEADER OF THE GAME, ON THIS CARD (#2418): a picture and a
                    # short number, and the pair is the whole row. `short` is what the
                    # pill shows; `detail` above is the exact figure, which the pill
                    # carries as its title and the window still prints in full.
                    "short": _short(row.get("count"))}
            picture = str(row.get("icon") or "")
            if picture:
                item["icon"] = "/api/itemicon?name=" + quote(picture)
            # What one press of «Сбор ресурсов» would add — the game's own figure per
            # building, summed by what that building makes. Silent at zero.
            if row.get("pending"):
                item["note"] = self.t("web.ui.res.pending", n=_group(row.get("pending")))
            items.append(item)
        # `pills`: pairs of picture-and-number laid across the width and wrapped, the
        # way the game's own header lays nine balances over three short rows. A
        # front-end that does not know the layout draws the rows as it always did —
        # every item still carries its `text` and `detail`.
        card = {"title": "web.ui.res.head", "items": items, "layout": "pills",
                "empty": "web.ui.res.empty", "flow": flow}
        if stock.get("watching"):
            card["note"] = "web.ui.res.live"
        return card

    def web_view(self) -> "dict | None":
        """The tab's cards, plus the one press the window's box is — asking about
        another warzone. The phone types it into a prompt (`panel/web/app/src`).

        The stock goes FIRST and outside :meth:`web_cards`, on purpose twice over: it is
        what somebody opens this screen for, and it must be drawn even before the tab's
        own first reading has come back — `web_cards` is not called at all until then,
        and an ear that only rises after a background fetch is an ear that misses the
        first minute of every look.
        """
        view = super().web_view()
        if view is not None:
            stock = self._stock_card()
            if stock is not None:
                view["cards"] = [stock] + list(view.get("cards") or [])
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
