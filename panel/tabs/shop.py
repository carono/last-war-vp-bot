"""The «Магазин» tab: what the shop hands over for nothing, and one press that takes it.

WHAT THE PAGE IS FOR. The shop has a lot of tabs and almost all of them want money. This
page answers the one question a person actually has to ask every day — «есть ли там
что-нибудь бесплатное прямо сейчас» — and offers the press that takes it. Seven readings
and nothing else: today's free gift on the week-card page, the daily reward of the week
cards the account already holds, what a running month card owes for today, and the
levels of every event battle pass («Акция») that are earned and not yet claimed.

NOTHING IS EVER BOUGHT FROM HERE. The boundary is the ability's, not the page's: only
what costs nothing is claimed — no diamonds, no gold bricks, no honour, no coupons. The
census of every shop tab and what each one sells is `docs/research/shop-free-claims.md`.

NOTHING HERE DRIVES THE GAME. Both presses are scenarios (`CLAUDE.md`):
`read_shop_freebies` for the readings and `collect_shop_freebies` for the routine, and
the routine ends with the same reading block, so a run started from the phone moves the
numbers in the window and nothing asks the game twice.

READ ONCE, THEN THE PERSON ASKS. The first look at the page reads the shop once
(`ensure_loaded`), and after that the numbers only move when somebody presses «Обновить»
or the errand fires. There is no clock here: both gates are the client's own record, kept
up to date by the server's own pushes, and a page that re-read itself every minute would
be a background poll of the game link (`CLAUDE.md`).

THE SEVEN KNOBS are what the routine is allowed to take, and they live in ONE place — the
errand's own row on «Таймеры» (`panel/runtime/errand_args.py`). This page is a second
DRAWING of them rather than a second copy: a box ticked here is written through
`Schedule.set_timer_arg`, so the schedule fires with what the page shows and the gear
beside the row shows what the page has (#2017).
"""
from __future__ import annotations

from tkinter import ttk

from ..widgets import tk_stringvar
from .base import PanelTab

#: The two scenarios this page plays, and the whole of what it knows about the game.
READ_ACTION = "read_shop_freebies"
COLLECT_ACTION = "collect_shop_freebies"

#: The errand the schedule runs, and the row that HOLDS the two permissions.
ERRAND = COLLECT_ACTION

#: The two permissions, and what they mean when the row says nothing — the scenario's own
#: `ARGS` defaults, so a profile that has never touched them behaves as the recipe does.
KNOBS = ("free_gift", "card_daily", "month_card", "battle_pass",
         "decoration_free", "recharge_free", "golloes_free")

#: The readings, in the order the page draws them: the scenario's variable and the locale
#: key that names it. `free_due` is drawn through its own formatter.
ROWS = (("free_due", "shop.free_due"),
        ("cards_due", "shop.cards_due"),
        ("cards_held", "shop.cards_held"),
        ("month_due", "shop.month_due"),
        ("pass_due", "shop.pass_due"),
        ("pass_acts", "shop.pass_acts"),
        ("dec_due", "shop.dec_due"),
        ("week_free_due", "shop.week_free_due"),
        ("golloes_due", "shop.golloes_due"),
        ("due", "shop.due"))

#: What a value looks like before anything has been read. Never a zero: «0 наград» and
#: «ничего не прочитано» are two different things and only one of them is a fact.
UNREAD = "—"


class ShopTab(PanelTab):
    ID = "shop"
    TITLE_KEY = "tab.shop"
    ORDER = 63
    LOCALE_NS = ("shop",)
    WEB_SCREEN = True

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._values = {name: UNREAD for name, _key in ROWS}
        self._vars: dict = {}
        self._status_var = None
        self._status_key = ""
        self._loaded = False
        self._boxes: dict = {}

    # -- drawing -------------------------------------------------------------
    def build(self) -> None:
        frame = self.tr(ttk.LabelFrame(self.parent, padding=8), "shop.frame")
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        grid = ttk.Frame(frame)
        grid.pack(fill="x")
        for row, (name, key) in enumerate(ROWS):
            self.tr(ttk.Label(grid, foreground="#888"), key).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=1)
            var = tk_stringvar(self.rt.root)
            var.set(self.shown(name))
            self._vars[name] = var
            ttk.Label(grid, textvariable=var).grid(row=row, column=1, sticky="w")
        self._status_var = tk_stringvar(self.rt.root)
        self._status_var.set(self.t(self._status_key) if self._status_key else "")
        ttk.Label(frame, textvariable=self._status_var, foreground="#888").pack(
            anchor="w", pady=(6, 0))
        knobs = ttk.Frame(frame)
        knobs.pack(fill="x", pady=(6, 0))
        for key in KNOBS:
            var = tk_stringvar(self.rt.root)
            var.set("1" if self.knob(key) else "0")
            self._boxes[key] = var
            self.tr(ttk.Checkbutton(knobs, variable=var, onvalue="1", offvalue="0",
                                    command=lambda k=key: self._on_box(k)),
                    "shop." + key).pack(anchor="w")
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(8, 0))
        self.tr(ttk.Button(bar, command=lambda: self.refresh(human=True)),
                "tabx.refresh").pack(side="left")
        self.tr(ttk.Button(bar, command=self.collect_now), "shop.collect").pack(
            side="left", padx=(6, 0))
        self.tr(ttk.Label(frame, foreground="#888", wraplength=620, justify="left"),
                "shop.hint").pack(anchor="w", pady=(8, 0))

    # -- what a reading looks like on screen ----------------------------------
    def shown(self, name: str) -> str:
        """One reading as a person reads it: «да / нет» for the gift, a count for the rest."""
        raw = self._values.get(name, UNREAD)
        if raw == UNREAD:
            return UNREAD
        if name in ("free_due", "month_due", "dec_due", "week_free_due",
                    "golloes_due"):
            return self.t("shop.yes" if str(raw) not in ("0", "") else "shop.no")
        return str(raw)

    # -- the knobs, and where their values really live -------------------------
    #
    # NOWHERE HERE, deliberately: the value is the errand row's own argument, read fresh
    # every time it is asked for. A copy kept on the tab would be a second answer the
    # first time somebody moved the knob from the gear on «Таймеры» or from the phone.
    def knob(self, key: str) -> bool:
        sched = getattr(self.rt, "schedule", None)
        if sched is None:
            return True
        value = sched.timer_arg(ERRAND, key, 1)
        return str(value) not in ("0", "", "False", "false", "None")

    def free_gift(self) -> bool:
        """May the routine take today's free gift from the week-card page."""
        return self.knob("free_gift")

    def card_daily(self) -> bool:
        """May the routine claim the daily reward of the cards already held."""
        return self.knob("card_daily")

    def month_card(self) -> bool:
        """May the routine claim what a running month card owes for today."""
        return self.knob("month_card")

    def battle_pass(self) -> bool:
        """May the routine take the ladder of every event battle pass that is running."""
        return self.knob("battle_pass")

    def decoration_free(self) -> bool:
        """May the routine spend the decoration shop's own free attempt."""
        return self.knob("decoration_free")

    def recharge_free(self) -> bool:
        """May the routine take today's free reward of the recharge page."""
        return self.knob("recharge_free")

    def golloes_free(self) -> bool:
        """May the routine take the golloes camp's daily free one."""
        return self.knob("golloes_free")

    def set_knob(self, key: str, on) -> None:
        """Move one knob — from this page, from the phone, or from the gear on «Таймеры»."""
        value = on not in ("0", "", "false", "False", None, 0, False)
        sched = getattr(self.rt, "schedule", None)
        if sched is not None:
            sched.set_timer_arg(ERRAND, key, 1 if value else 0)
        var = self._boxes.get(key)
        if var is not None:
            self.post(lambda: var.set("1" if value else "0"))

    def _on_box(self, key: str) -> None:
        var = self._boxes.get(key)
        if var is not None:
            self.set_knob(key, var.get())

    def args(self) -> dict:
        """The seven permissions as the scenario's `ARGS`. Nothing else is passed."""
        return {key: 1 if self.knob(key) else 0 for key in KNOBS}

    # -- playing the two scenarios ---------------------------------------------
    def ensure_loaded(self) -> None:
        """The first LOOK at the page reads the shop once, and never again by itself."""
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def refresh(self, human: bool = False) -> None:
        """Read the shop. Opens nothing, buys nothing, presses nothing."""
        self._status("shop.loading")
        self.rt.play_async(READ_ACTION, tag="shop", human=human,
                           on_result=self.from_run)

    def collect_now(self) -> None:
        """Play the ability once, with the two permissions as they stand here."""
        self._status("shop.collecting")
        self.rt.play_async(COLLECT_ACTION, self.args(), tag="shop", human=True,
                           on_result=self.from_run)

    def from_run(self, outcome) -> None:
        """Draw the page off the run's OWN variables — the scenario already read them."""
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        if not got.get("known"):
            self._status("shop.no_game")
            return
        self._values = {name: str(got.get(name, UNREAD)) for name, _key in ROWS}
        self._status("")
        self.post(self._paint)

    def _paint(self) -> None:
        for name, _key in ROWS:
            var = self._vars.get(name)
            if var is not None:
                var.set(self.shown(name))

    def _status(self, key: str, **fmt) -> None:
        self._status_key = key
        text = self.t(key, **fmt) if key else ""
        var = self._status_var
        if var is not None:
            self.post(lambda: var.set(text))

    # -- persistence ------------------------------------------------------------
    #
    # THE TAB KEEPS NOTHING. Its two knobs are the errand row's arguments and the row is
    # written by the schedule; a block of its own here would be the second home this page
    # exists not to have.

    # -- the phone ----------------------------------------------------------------
    def web_view(self) -> "dict | None":
        """One card: the readings, the seven permissions as fields, and the two presses."""
        rows = [{"label": key, "value": self.shown(name)} for name, key in ROWS]
        fields = [{"key": key, "label": "shop." + key,
                   "hint": "shop." + key + ".hint", "kind": "switch",
                   "value": self.knob(key)}
                  for key in KNOBS]
        card = {"title": "shop.frame", "note": "shop.hint",
                "rows": rows, "fields": fields}
        return {"cards": [card],
                "actions": [{"id": "refresh", "label": "tabx.refresh"},
                            {"id": "collect", "label": "shop.collect"}]}

    def web_press(self, action: str, args: dict) -> dict:
        """Two presses and one `set`; anything else is «unknown» rather than a guess."""
        if action == "refresh":
            self.refresh(human=True)
            return {"ok": True}
        if action == "collect":
            self.collect_now()
            return {"ok": True}
        if action == "set":
            key = str((args or {}).get("key") or "")
            if key not in KNOBS:
                return {"error": "unknown"}
            self.set_knob(key, (args or {}).get("value"))
            return {"ok": True}
        return {"error": "unknown"}


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(ShopTab))
