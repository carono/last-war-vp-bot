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

THE SHELVES THEMSELVES ARE HERE TOO (#2666), and only on the phone. The person's
decision — «Веб теперь главный инструмент, ему и полный функционал» — makes the web the
front-end while the window is retired, so the goods, their pictures, the price beside
each and the press that buys one are `web_view`'s and the window is left as it was.

WHAT THE SHELVES ARE. Whatever the client is holding: the tabs of the game's own
«Магазин», the decoration shelf, «Сверкающий рынок», and the storefronts that want money
— which are drawn and never pressed, because a purchase for money is not on the wire at
all. The SET is never written down here: `actions/read_shops.md` reports what the account
has and a shelf this panel has no word for is drawn by its number.

NOTHING IS READ ON A CLOCK AND THERE IS NO «ОБНОВИТЬ» FOR THE SHELVES (#2633). They are
read when the client gets into the game and when a balance push says something moved
(`panel/runtime/shops_live.py`), a purchase re-reads on its own way out, and the age of
the reading is drawn beside it.

THE PRIORITIES ARE THE ERRAND'S OWN ARGUMENT. «Автопокупка» is one scenario over one
ordered list, and that list lives in the errand row (`autobuy_shop_goods`, argument
`plan`) exactly as the seven permissions above live in theirs — so the gear on «Таймеры»,
this page and the schedule all edit ONE value.

THE SEVEN KNOBS are what the routine is allowed to take, and they live in ONE place — the
errand's own row on «Таймеры» (`panel/runtime/errand_args.py`). This page is a second
DRAWING of them rather than a second copy: a box ticked here is written through
`Schedule.set_timer_arg`, so the schedule fires with what the page shows and the gear
beside the row shows what the page has (#2017).
"""
from __future__ import annotations

from tkinter import ttk

from ..runtime import shops_live
from ..widgets import tk_stringvar
from .base import PanelTab
from .inventory import cell_url

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

#: THE ABILITY THAT SPENDS, and the argument that holds the order it spends in. One
#: home for the list: the errand's row, which is what the gear on «Таймеры» edits too.
AUTOBUY_ACTION = "autobuy_shop_goods"
BUY_ACTION = "buy_shop_goods"
PLAN_ARG = "plan"

#: The shelves this panel has a word for, by the number the CLIENT numbers them with
#: (`docs/research/shops.md`). A shelf that is not here is drawn by its number rather
#: than by somebody else's name — the set comes from the game, never from this table.
SHELF_KEYS = {"common:1": "shop.kind.diamond",
              "common:2": "shop.kind.vip",
              "common:7": "shop.kind.alliance",
              "common:8": "shop.kind.honour",
              "common:10": "shop.kind.coupon",
              "common:100": "shop.kind.expedition",
              "common:150": "shop.kind.decoration",
              "common:200": "shop.kind.season",
              "market:0": "shop.kind.market"}

#: …and the two families that are not one shelf: what a money storefront is called, and
#: what any other numbered shelf is called.
MONEY_KEY = "shop.kind.money"
OTHER_KEY = "shop.kind.other"

#: How many goods one card draws. A shelf is thirty-odd rows; this is the ceiling that
#: keeps a screen re-read small when a client ever answers with more.
SHELF_MAX = 120

#: What a value looks like before anything has been read. Never a zero: «0 наград» and
#: «ничего не прочитано» are two different things and only one of them is a fact.
UNREAD = "—"


def plan_parse(raw) -> list:
    """The errand's `plan` argument into records: `«common:7:1000012:2»` a piece.

    Shelf, row, and how many of it one run may buy. A piece that cannot be read is
    dropped rather than raised: a list one entry short still buys the rest, and a page
    that raises is a page.
    """
    out: list = []
    for piece in str(raw or "").split(","):
        bits = [b.strip() for b in piece.split(":")]
        if len(bits) < 3 or not bits[0] or not bits[1] or not bits[2]:
            continue
        try:
            count = int(bits[3]) if len(bits) > 3 and bits[3] else 1
        except (TypeError, ValueError):
            count = 1
        # ZERO IS «ALL OF IT» (#2670), not «none»: the person asked for a tick that says
        # «покупать все» beside the one that says how many, and the recipe reads the same
        # number — `count = 0` means «as many as the quota, the purse and the ceilings
        # allow». A row is taken OUT of the order by dropping it, never by a count.
        out.append({"kind": bits[0], "shop": bits[1], "id": bits[2],
                    "count": max(0, count)})
    return out


def plan_text(entries) -> str:
    """The records back into the one string the errand row holds."""
    return ",".join("{kind}:{shop}:{id}:{count}".format(**e) for e in entries)


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
        #: WHICH SHELF THE PHONE IS LOOKING AT. A screen re-read carries the goods of
        #: ONE shelf, never of all of them: two hundred rows with a picture, a price and
        #: a gear each is eighty kilobytes every two and a half seconds, and the person
        #: is reading one shelf. It is the page's own state and lives in the tab's
        #: block, like every other thing a person chose about a page.
        self._pick = ""
        #: What each currency the shelves want is CALLED — the game's own word for it,
        #: filled from the reading. A currency the reading did not name is drawn by its
        #: number, never by a word this panel invented for it.
        self._money: dict = {}

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


    # -- the shelves, and the order the autobuy spends them in -----------------
    #
    # NOTHING HERE ASKS THE GAME. The reading is the profile's own ear
    # (`panel/runtime/shops_live.py`): once when the client gets into the game, once more
    # when a balance moved, and once after a purchase of ours. This only draws it.
    def shelves(self) -> tuple:
        """`(shelves, age)` — the reading, grouped by shelf, in the game's own order.

        A shelf is `(key, title_key, rows)`: how the panel names it to itself, the key
        it is drawn under, and its goods.
        """
        rows, money, age = shops_live.state(self.rt)
        for row in list(rows) + list(money):
            cost, word = str(row.get("cost_id") or ""), str(row.get("cost_name") or "")
            if cost and word:
                self._money[cost] = word
        order: list = []
        held: dict = {}
        for row in list(rows) + list(money):
            key = str(row.get("kind") or "") + ":" + str(row.get("shop") or "0")
            if key not in held:
                held[key] = []
                order.append(key)
            held[key].append(row)
        out = []
        for key in order:
            title = SHELF_KEYS.get(key)
            if title is None:
                title = MONEY_KEY if key.startswith("money:") else OTHER_KEY
            out.append((key, title, held[key]))
        return out, age

    def plan(self) -> list:
        """The autobuy's ordered list, as the errand row holds it right now."""
        sched = getattr(self.rt, "schedule", None)
        if sched is None:
            return []
        return plan_parse(sched.timer_arg(AUTOBUY_ACTION, PLAN_ARG, ""))

    def set_plan(self, entries) -> None:
        """Write the ordered list back into the errand row — the one home it has."""
        sched = getattr(self.rt, "schedule", None)
        if sched is not None:
            sched.set_timer_arg(AUTOBUY_ACTION, PLAN_ARG, plan_text(entries))

    def place_of(self, kind: str, shop: str, ident: str) -> int:
        """Where one row stands in the autobuy's order, 1-based. 0 = not in it."""
        # PER SHELF (#2670): every shop has an order of its own, so «№2» has to mean
        # «second on this shelf». Counted through the other shelves it would be a number
        # nobody looking at this page could check.
        n = 0
        for entry in self.plan():
            if (entry["kind"], entry["shop"]) != (kind, shop):
                continue
            n += 1
            if entry["id"] == ident:
                return n
        return 0

    def count_of(self, kind: str, shop: str, ident: str) -> int:
        """How many of one row the autobuy may take in a run. 1 when it is not in it."""
        for entry in self.plan():
            if (entry["kind"], entry["shop"], entry["id"]) == (kind, shop, ident):
                return entry["count"]
        return 1

    def is_auto(self, kind: str, shop: str, ident: str) -> bool:
        """Is this row in the autobuy's order at all — the tick «Покупать автоматически»."""
        return self.place_of(kind, shop, ident) > 0

    def buys_all(self, kind: str, shop: str, ident: str) -> bool:
        """Does the order say «as many as I can» for this row — `count = 0` (#2670)."""
        for entry in self.plan():
            if (entry["kind"], entry["shop"], entry["id"]) == (kind, shop, ident):
                return int(entry["count"]) == 0
        return False

    def set_auto(self, kind: str, shop: str, ident: str, on) -> None:
        """Put the row in the order, or take it out — the tick, not a typed number.

        A row joins at the END: it is the person's own list, and something they have just
        ticked has no claim on being bought before what they ticked yesterday. Where it
        goes after that is decided by dragging it (#2670).
        """
        want = on not in ("0", "", "false", "False", None, 0, False)
        entries = self.plan()
        here = [e for e in entries
                if (e["kind"], e["shop"], e["id"]) == (kind, shop, ident)]
        if want and not here:
            entries.append({"kind": kind, "shop": shop, "id": ident, "count": 1})
        elif not want and here:
            entries = [e for e in entries
                       if (e["kind"], e["shop"], e["id"]) != (kind, shop, ident)]
        self.set_plan(entries)

    def set_all(self, kind: str, shop: str, ident: str, on) -> None:
        """«Покупать всё» — the row's count becomes 0, which the recipe reads as «as many
        as the quota, the purse and the ceilings allow».

        Ticking it on a row that is not in the order puts it in: asking for all of
        something the errand would never look at is not a state anybody means.
        """
        want = on not in ("0", "", "false", "False", None, 0, False)
        entries = self.plan()
        for entry in entries:
            if (entry["kind"], entry["shop"], entry["id"]) == (kind, shop, ident):
                entry["count"] = 0 if want else max(1, int(entry["count"] or 1))
                self.set_plan(entries)
                return
        if want:
            entries.append({"kind": kind, "shop": shop, "id": ident, "count": 0})
            self.set_plan(entries)

    def set_order(self, ids) -> None:
        """ONE SHELF's order, as the phone dragged it: «kind:shop:id,…».

        What each row BUYS is not in that list and is not touched — only where it stands.
        And only the rows the list NAMES move: the named rows' SLOTS in the plan are kept
        and refilled in the new order, so every other shelf keeps its own order and its
        own places (#2670 — a queue is per shop). A row the phone did not name keeps its
        place too: a screen drawn a moment before a second front-end added something must
        not delete what it never saw.
        """
        want = []
        for piece in str(ids or "").split(","):
            bits = [b.strip() for b in piece.split(":")]
            if len(bits) >= 3:
                want.append(":".join(bits[:3]))
        held = {e["kind"] + ":" + e["shop"] + ":" + e["id"]: e for e in self.plan()}
        moving = [held[key] for key in want if key in held]
        if not moving:
            return
        spots = iter(moving)
        named = set(want)
        out = []
        for entry in self.plan():
            key = entry["kind"] + ":" + entry["shop"] + ":" + entry["id"]
            out.append(next(spots) if key in named else entry)
        self.set_plan(out)

    def set_count(self, kind: str, shop: str, ident: str, count) -> None:
        """How many of one row one run may buy. A row not in the order is left out."""
        try:
            want = max(1, int(str(count).strip() or 1))
        except (TypeError, ValueError):
            return
        entries = self.plan()
        for entry in entries:
            if (entry["kind"], entry["shop"], entry["id"]) == (kind, shop, ident):
                entry["count"] = want
                self.set_plan(entries)
                return

    # -- the two presses that spend --------------------------------------------
    def sold_out(self, kind: str, shop: str, ident: str) -> bool:
        """Has this row's quota run out — read off the LAST reading, never guessed.

        A row the reading does not hold at all is not «sold out»: it is a row the panel
        has not seen, and refusing a press for something it cannot describe would be the
        panel inventing a rule of the game.
        """
        rows, money, _age = shops_live.state(self.rt)
        for row in list(rows) + list(money):
            if (str(row.get("kind") or ""), str(row.get("shop") or "0"),
                    str(row.get("id") or "")) != (kind, shop, ident):
                continue
            limit = int(row.get("limit") or 0)
            return bool(limit) and int(row.get("bought") or 0) >= limit
        return False

    def buy_one(self, kind: str, shop: str, ident: str, count: int = 1) -> bool:
        """Buy one row, now, because a person pressed it. The recipe says the price."""
        return self.rt.play_async(
            BUY_ACTION,
            {"kind": kind, "shop": shop, "product": ident, "count": count},
            tag="shop", human=True, on_done=self._bought)

    # -- the ceilings, one per CURRENCY --------------------------------------------
    #
    # THE PERSON'S CORRECTION (#2670): «у каждого магазина своя валюта». One number over
    # all the shelves added alliance points to diamonds to honour, which is not a sum
    # anybody can mean. So a ceiling belongs to the CURRENCY, it is stored ONCE (the
    # errand's own `caps` argument, exactly like the order), and it is drawn where it is
    # spent — the gear beside the shop's own heading.
    CAPS_ARG = "caps"
    #: What a currency with no ceiling reads as. Not zero: zero is a REAL ceiling that
    #: says «not one of this», and the two must never be spelled the same.
    NO_CAP = -1
    #: The one currency that ships with a ceiling — the diamonds, the irreversible spend
    #: (`CLAUDE.md`), at the 300 already settled for the energy refill. Every other
    #: currency of every shelf is EARNED by playing and cannot be bought, so its own
    #: quota is the limit and a second number would be furniture.
    DIAMONDS = "5"
    DIAMOND_CAP = 300

    def caps(self) -> dict:
        """Every ceiling, as the errand row holds them: `{currency: limit}`.

        A profile written before #2670 has `diamond_cap` and no `caps`; it is READ
        through, not migrated, so nothing is rewritten behind a person who has not
        touched the page.
        """
        sched = getattr(self.rt, "schedule", None)
        raw = sched.timer_arg(AUTOBUY_ACTION, self.CAPS_ARG, "") if sched else ""
        out: dict = {}
        for piece in str(raw or "").split(","):
            money, _sep, limit = piece.partition(":")
            money, limit = money.strip(), limit.strip()
            if not money:
                continue
            try:
                out[money] = int(limit)
            except (TypeError, ValueError):
                continue
        if not out:
            old = sched.timer_arg(AUTOBUY_ACTION, "diamond_cap", self.DIAMOND_CAP) if sched else None
            try:
                out = {self.DIAMONDS: int(old)}
            except (TypeError, ValueError):
                out = {self.DIAMONDS: self.DIAMOND_CAP}
        return out

    def cap_of(self, currency: str) -> int:
        """This currency's ceiling, or `NO_CAP` when it has none."""
        return self.caps().get(str(currency), self.NO_CAP)

    def set_cap(self, currency: str, limit) -> None:
        """Type a ceiling for one currency. `NO_CAP` (or below) takes it away."""
        try:
            want = int(str(limit).strip())
        except (TypeError, ValueError):
            return
        held = self.caps()
        if want < 0:
            held.pop(str(currency), None)
        else:
            held[str(currency)] = want
        sched = getattr(self.rt, "schedule", None)
        if sched is not None:
            sched.set_timer_arg(AUTOBUY_ACTION, self.CAPS_ARG,
                                ",".join("%s:%d" % (money, limit)
                                         for money, limit in held.items()))

    def shelf_money(self, rows) -> str:
        """Which currency this shelf spends — the one its rows are priced in.

        A shelf whose rows disagree (none does today) is named by the first row's: the
        ceiling is per currency, so a mixed shelf simply shows the one it mostly spends
        and the other keeps its own ceiling wherever it IS drawn.
        """
        for row in rows or ():
            money = str(row.get("cost_id") or "")
            if money:
                return money
        return ""

    def autobuy_now(self, pick: str = "") -> bool:
        """Play the autobuy once by hand — over THIS SHELF'S order and no other.

        THE BUTTON BELONGS TO THE SHELF IT IS DRAWN ON (#2670, the person's report: «почему
        я запускаю обмен, первый обмен проходит, но не в том магазине где нажимал»). The
        press used to hand the recipe the WHOLE plan, so a press on the expedition shelf
        walked into the alliance and honour ones as well — buying where it could, and
        being refused where the pay had already gone. That is where the «спам» came from,
        and it is why every check made on the shelf being pressed came back clean.

        The queue is per shop by the person's own decision — «меняем магазин, меняется
        очередь» — so the press is too. The SCHEDULE still walks the whole order: that is
        what a nightly errand is for, and each row carries its own shelf, quota and purse.
        """
        sched = getattr(self.rt, "schedule", None)
        chosen = pick or self._pick or ""
        kind, _sep, shop = chosen.partition(":")
        mine = [e for e in self.plan()
                if not chosen or (e["kind"], e["shop"]) == (kind, shop)]
        plan = plan_text(mine)
        args = {PLAN_ARG: plan}
        if sched is not None:
            # THE CEILINGS, ONE PER CURRENCY (#2670) — never a ban: every shop is in the
            # order, the diamond ones included, and what limits an irreversible spend is
            # how much of THAT currency one run may spend.
            args[self.CAPS_ARG] = ",".join("%s:%d" % (money, limit)
                                           for money, limit in self.caps().items())
        return self.rt.play_async(AUTOBUY_ACTION, args, tag="shop", human=True,
                                  on_done=self._bought)

    def _bought(self, *_a) -> None:
        """A purchase moved a shelf: read it back at once, debounce or no debounce."""
        try:
            self.rt.shops.after_purchase()
        except Exception:                # noqa: BLE001 — a reading, never the press
            pass

    # -- persistence ------------------------------------------------------------
    def config(self) -> dict:
        """The one thing this page keeps: which shelf is open. Everything else is a row
        of the errand it belongs to."""
        return {"pick": self._pick}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._pick = str(raw.get("pick") or "")

    # -- what the errands' own knobs are, and what this page never kept ---------
    #
    # THE SEVEN PERMISSIONS KEEP NOTHING HERE, and neither does the autobuy's order: both
    # are their errand's own arguments, read fresh every time they are asked for. A copy
    # kept on the tab would be a second answer the first time somebody moved the knob from
    # the gear on «Таймеры» or from the phone. What the block above DOES keep is the one
    # thing that is nobody's setting — which shelf this page has open.

    # -- the phone ----------------------------------------------------------------
    #
    # THE WEB IS WHERE THE SHELVES ARE, and the window has none of this on purpose
    # (`CLAUDE.md`: while the migration runs, new goes only into the web). The window
    # keeps the free claims it had.
    def web_view(self) -> "dict | None":
        """The free claims, the shelf picker, and the shelf the person has open."""
        rows = [{"label": key, "value": self.shown(name)} for name, key in ROWS]
        fields = [{"key": key, "label": "shop." + key,
                   "hint": "shop." + key + ".hint", "kind": "switch",
                   "value": self.knob(key)}
                  for key in KNOBS]
        # THE READINGS AND THE PERMISSIONS ARE TWO CARDS (#2670), and that is not a
        # decoration: a screen of more than two cards is drawn as a strip of chips with
        # ONE card open, and the card the strip opens by itself is the one marked
        # `main` — the shelves. Kept as one card the page had exactly two, the strip
        # disappeared, and the shelves stood under seventeen rows of free-claim
        # bookkeeping.
        free = {"title": "shop.frame", "note": "shop.hint", "rows": rows}
        knobs = {"title": "shop.free.knobs", "fields": fields}
        cards = [free, knobs] + self.shelf_cards()
        return {"cards": cards,
                "actions": [{"id": "refresh", "label": "tabx.refresh"},
                            {"id": "collect", "label": "shop.collect"}]}

    def shelf_cards(self) -> list:
        """ONE card: the strip of every shelf the account has, and the goods of the open one.

        IT WAS TWO, AND THE SECOND ONE HID THE FIRST (#2670). The picker used to be a
        card of its own with a dropdown in it, and a screen of several cards draws ONE at
        a time — so the phone opened the shelves card, saw «Магазин бриллиантов» and had
        no way of knowing eleven more shelves were behind a chip called «Магазины». The
        person's report was exactly that: «вижу магазин бриллиантов, других не вижу».

        So the picker is a STRIP on the goods card itself, above the goods, the way the
        game's own shop draws its tabs. Still one shelf's goods in the payload and never
        all of them: two hundred rows with a picture, a price and a gear each is eighty
        kilobytes every two and a half seconds, and a person reads one shelf at a time.
        """
        shelves, age = self.shelves()
        if not shelves:
            return [{"title": "shop.shelves", "empty": "shop.unread"}]
        choices = [{"value": key, "text": self.shelf_name(key, title)}
                   for key, title, _rows in shelves]
        chosen = self._pick if any(self._pick == k for k, _t, _r in shelves) else shelves[0][0]
        rows = next(r for k, _t, r in shelves if k == chosen)
        kind, _sep, shop = chosen.partition(":")
        # EVERY SHELF HAS AN ORDER OF ITS OWN (#2670, the person's correction:
        # «Очередь для автопокупки у каждого магазина своя, не нужно все в одном месте
        # выводить, меняем магазин, меняется очередь»). So the block above the goods is
        # THIS shelf's queue and never a summary of all of them — what other shelves
        # hold stays in the plan, untouched and undrawn, until their own tab is open.
        queue = self.queue_items(kind, shop, rows)
        picked = {e["id"] for e in self.plan()
                  if (e["kind"], e["shop"]) == (kind, shop)}
        rest = [self.good(kind, shop, row, group="shop.rest")
                for row in rows[:SHELF_MAX]
                if str(row.get("id") or "") not in picked]
        # THE CEILING IS DRAWN WHERE IT IS SPENT (#2670): behind the gear beside this
        # shop's own heading, named after the currency this shop takes. A shelf whose
        # currency the game has no word for shows its number — the same honesty the
        # price line keeps.
        money = self.shelf_money(rows)
        word = self.money_name(money)
        # A CURRENCY THE CLIENT HAS NO WORD FOR IS ITS NUMBER, said as one (#2670): the
        # game answers an unresolved key for the diamonds themselves, and «Потолок
        # трат: 5» is not a sentence. «валюта №5» is the same honesty the unnamed
        # shelves keep — a number, spelled as a number, never a name invented here.
        caps = ([{"key": "cap:" + money, "label": "shop.cap",
                  "label_fmt": {"currency": word or self.t("shop.money.other",
                                                           money=money)},
                  "hint": "shop.cap.hint", "kind": "number",
                  "min": self.NO_CAP, "max": 1000000,
                  "value": self.cap_of(money)}]
                if money and kind != "money" else [])
        return [{"title": "shop.shelves",
                 "head": self.t("shop.age", age=int(age)) if age is not None else "",
                 "note": "shop.shelves.hint",
                 "main": True, "layout": "grid", "search": True,
                 "empty": "shop.shelf.empty",
                 "options": caps,
                 "options_title": "shop.caps.title",
                 "fields": [{"key": "pick", "label": "shop.pick", "kind": "chips",
                             "value": chosen, "options": choices}],
                 # THE PRESS CARRIES THE SHELF THE SCREEN IS SHOWING (#2670). Which
                 # shelf is open is the TAB's state, shared by every viewer — so a
                 # second phone, or a tool poking the panel, moves it under the first
                 # one, and the button then spends where somebody else was looking.
                 # The screen sends what it drew; the tab's own pick is the fallback.
                 "actions": [{"id": "autobuy", "label": "shop.autobuy.now",
                              "args": {"pick": chosen}}],
                 "items": queue + rest}]

    def queue_items(self, kind: str, shop: str, rows) -> list:
        """THIS shelf's own order, in ITS order, drawn as goods that can be dragged.

        A row the reading no longer holds is left out rather than drawn as an id: it is a
        row the panel cannot describe, and a tile with a number where a name goes is the
        bug #2666 already fixed once. It stays in the plan all the same — a shelf the
        client has not filled in yet is not a reason to forget what somebody chose.
        """
        held = {str(row.get("id") or ""): row for row in rows}
        out = []
        for entry in self.plan():
            if (entry["kind"], entry["shop"]) != (kind, shop):
                continue
            row = held.get(entry["id"])
            if row is not None:
                out.append(self.good(kind, shop, row, group="shop.queue", drag=True))
        return out

    def shelf_name(self, key: str, title: str) -> str:
        """What a shelf is called on the strip.

        A shelf this panel has a word for is called by it; one it has not is called by
        the NUMBER the client numbers it with — «Магазин №9» — and never by a word made
        up for it. Two unnamed shelves both saying «Магазин» is what the strip looked
        like before (#2670), and two identical chips are one chip nobody can choose.
        """
        if title != OTHER_KEY:
            return self.t(title)
        _kind, _sep, shop = key.partition(":")
        return self.t(OTHER_KEY, shop=shop)

    def money_name(self, currency: str) -> str:
        """What a currency is called. The game's own name when the reading carried one,
        and its number when it did not — never somebody else's word for it."""
        return self._money.get(str(currency)) or ""

    def good(self, kind: str, shop: str, row: dict, *, group: str = "",
             drag: bool = False) -> dict:
        """One row of a shelf as the phone draws it: the picture, the price, the press.

        THE PICTURE IS THE GAME'S OWN and never a stand-in: `cell_url` composes the
        item's sprite inside its rarity frame exactly as the bag does (one function, the
        bag's), and a machine that has not extracted the art sends no `icon` at all —
        the card then draws the one placeholder rather than somebody else's picture.
        """
        ident = str(row.get("id") or "")
        left = max(0, int(row.get("limit") or 0) - int(row.get("bought") or 0))
        # THE PRICE, AND THE CURRENCY WHEN THE GAME HAS A WORD FOR IT. A client that
        # answers with an unresolved key gives the panel nothing to draw, and a number
        # invented for it would be a name this panel made up — so the amount stands
        # alone, on the shelf that is already named after the currency it spends.
        word = self.money_name(str(row.get("cost_id") or ""))
        # THE PRICE IS THE TILE'S OWN LINE (#2670) and not one fact among several: the
        # game draws a shop as a picture with a price under it, and that is what the
        # person asked for — «карточки меньше и квадратные, ближе к игровому виду».
        price = (self.t("shop.free") if not row.get("cost")
                 else self.t("shop.cost", amount=row.get("cost"),
                             currency=word).strip()
                 if word else str(row.get("cost")))
        # SOLD OUT (#2670, the person's words: «Сери иконку предмета, если всё
        # выкуплено»). A row with a quota that has none of it left is finished for this
        # reset: the game greys it, so the panel does too — and says «выкуплено» in
        # place of «осталось 0», which is the same fact spelled as a mark.
        spent = bool(row.get("limit")) and left <= 0
        facts = []
        if spent:
            facts.append({"label": "shop.spent", "value": ""})
        elif row.get("limit"):
            facts.append({"label": "shop.left", "value": str(left)})
        # WHETHER THE ACCOUNT CAN PAY is the GAME's answer, never a sum done here: a
        # price met out of two purses is the client's own arithmetic (`read_shops.md`).
        # A FACT WITH NO VALUE IS A MARK, and its label IS the word — the shape every
        # small tile on this front-end already reads (#1999). «Цена: не хватает» said
        # the same thing twice and wrapped the line it said it on.
        if row.get("cost") and not row.get("afford"):
            facts.append({"label": "shop.short", "value": ""})
        place = self.place_of(kind, shop, ident)
        # A ROW THAT TAKES AS MANY AS IT CAN SAYS SO ON THE TILE (#2670), as a mark: a
        # tick nobody can see from the outside is a tick nobody trusts, and the gear it
        # lives behind is two taps away.
        if place and self.buys_all(kind, shop, ident):
            facts.insert(0, {"label": "shop.all.mark", "value": ""})
        item = {"id": "%s:%s:%s" % (kind, shop, ident),
                "text": str(row.get("name") or ident),
                "detail": (self.t("shop.count", count=row.get("count"))
                           if int(row.get("count") or 0) > 1 else ""),
                "facts": facts,
                "price": price,
                "shape": "picture"}
        if spent:
            # THE TILE IS GREY AND IT DOES NOT PRESS. Both halves matter: a picture that
            # only LOOKS spent while its press still sends `user.shop.buy.new` is a
            # button that answers «нельзя» a second after it was tapped.
            item["dim"] = True
        if group:
            item["group"] = group
        # WHAT CAN BE DRAGGED, AND WHAT IT IS CALLED WHEN IT LANDS. Only a row already in
        # the order: dragging is how the ORDER is set, and a row outside it has no place
        # to be moved to. The name it travels under is the same triple every press here
        # uses, so nothing new has to be matched up on the way back.
        if drag:
            item["drag_id"] = "%s:%s:%s" % (kind, shop, ident)
        picture = cell_url(row.get("icon"), row.get("colour"))
        if picture:
            item["icon"] = picture
        if place:
            item["badge"] = self.t("shop.place", place=place)
        # A MONEY SHELF IS DRAWN AND NEVER PRESSED. The packs are not on the wire at all
        # — no manager holds them and no message buys one — so a button there would be a
        # button that cannot work (docs/research/shops.md).
        if kind != "money":
            # THE KNOBS ARE TWO TICKS AND A NUMBER (#2670), and the person named both
            # ticks: «нужна галка покупать все, и галка покупать автоматически». WHERE a
            # row stands is no longer typed here — it is dragged, which is what the
            # `drag_id` above is for — so the priority box is gone rather than left
            # beside a gesture that contradicts it.
            all_of = self.buys_all(kind, shop, ident)
            item["options"] = [
                {"key": "auto:%s:%s:%s" % (kind, shop, ident), "label": "shop.auto",
                 "hint": "shop.auto.hint", "kind": "switch",
                 "value": self.is_auto(kind, shop, ident)},
                {"key": "all:%s:%s:%s" % (kind, shop, ident), "label": "shop.all",
                 "hint": "shop.all.hint", "kind": "switch", "value": all_of},
                # HOW MANY TO OWN IN ALL, not per run (#2670): the errand tops the row
                # up to this number and stops, counting what the GAME says has been
                # bought — so a row bought by hand in the game counts towards it too.
                {"key": "qty:%s:%s:%s" % (kind, shop, ident), "label": "shop.qty",
                 "hint": "shop.qty.hint", "kind": "number", "min": 1, "max": 9999,
                 "value": max(1, self.count_of(kind, shop, ident))}]
            item["options_title"] = "shop.knobs"
        # A SOLD-OUT ROW KEEPS ITS KNOBS AND LOSES ITS BUTTON (#2670): the quota comes
        # back on the shelf's own reset, and «поставить в очередь на завтра» is exactly
        # the thing a person does while looking at a row they have just used up.
        if kind != "money" and not spent:
            item["actions"] = [
                {"id": "buy", "label": "shop.buy",
                 "args": {"kind": kind, "shop": shop, "id": ident},
                 # A PURCHASE IS IRREVERSIBLE, so it asks first and names the price in
                 # the question — the same shape every spending press on this front-end
                 # has (`CLAUDE.md`).
                 "confirm": "shop.buy.confirm",
                 "confirm_fmt": {"name": str(row.get("name") or ident),
                                 "amount": row.get("cost"),
                                 "currency": word}}]
        return item

    def web_press(self, action: str, args: dict) -> dict:
        """The two free-claim presses, the shelf's own «купить», and one `set`."""
        args = args or {}
        if action == "refresh":
            self.refresh(human=True)
            return {"ok": True}
        if action == "collect":
            self.collect_now()
            return {"ok": True}
        if action == "buy":
            kind = str(args.get("kind") or "")
            shop = str(args.get("shop") or "")
            ident = str(args.get("id") or "")
            if kind == "money" or not ident:
                return {"error": "unknown"}
            # SOLD OUT IS A REFUSAL HERE TOO (#2670). The tile hides its button, and a
            # press that arrives all the same — an older screen in somebody's hand, a
            # second front-end — must not spend: the quota is gone until the reset.
            if self.sold_out(kind, shop, ident):
                return {"ok": False, "reason": "shop.spent"}
            return {"ok": self.buy_one(kind, shop, ident,
                                       self.count_of(kind, shop, ident))}
        if action == "autobuy":
            return {"ok": self.autobuy_now(str(args.get("pick") or ""))}
        if action == "set":
            key = str(args.get("key") or "")
            if key in KNOBS:
                self.set_knob(key, args.get("value"))
                return {"ok": True}
            if key == "pick":
                self._pick = str(args.get("value") or "")
                return {"ok": True}
            # THE WHOLE ORDER, AS THE PHONE DRAGGED IT (#2670). One press for a move,
            # not one per row: what a drag produces is a LIST, and sending it a pair at a
            # time is how two front-ends end up disagreeing about the middle of it.
            if key == "order":
                self.set_order(args.get("value"))
                return {"ok": True}
            if key.startswith("cap:"):
                self.set_cap(key.partition(":")[2], args.get("value"))
                return {"ok": True}
            head, _sep, tail = key.partition(":")
            bits = tail.split(":")
            if head in ("auto", "all", "qty") and len(bits) == 3:
                if head == "auto":
                    self.set_auto(bits[0], bits[1], bits[2], args.get("value"))
                elif head == "all":
                    self.set_all(bits[0], bits[1], bits[2], args.get("value"))
                else:
                    self.set_count(bits[0], bits[1], bits[2], args.get("value"))
                return {"ok": True}
            return {"error": "unknown"}
        return {"error": "unknown"}


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(ShopTab))
