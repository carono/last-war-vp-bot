r"""Чем платим и сколько этого есть — the shop's currencies, with a shelf that wants two.

The person's words (#2830): «В магазинах выведи картинку валюты и сумму баланса, обрати
внимание, что в кристаллическом магазине сразу 2 валюты используются».

What is pinned here:

* the reading carries a record per CURRENCY, and «the client will not show it» (-1)
  survives the trip as itself rather than as a zero;
* a shelf reports EVERY currency its rows are priced in, in the order they name them —
  the code it replaced took the first one and called it «the shop's currency»;
* a currency is the PAIR (type, item) where the type does not name it: `currencyType` 7
  means «paid with an item», and six shelves spend six different items under it;
* the balance is drawn short («12.34M», the format the collect card already uses) with
  the whole number in the title, and a currency with no picture draws no picture;
* there is ONE pill component on the front-end and the shelf card uses that one.

    C:\Python312\python.exe tests\test_panel_shop_purses.py
"""
from __future__ import annotations

TIER = "offline"        # no game, no Tk — see tools/run_tests.py

import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _stub_tk() -> None:
    """A tkinter that answers everything and draws nothing — only so this can RUN."""
    if "tkinter" in sys.modules:
        return

    class _W:
        def __init__(self, *a, **k) -> None:
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    def _module(name: str):
        mod = types.ModuleType(name)
        made: dict = {}

        def _make(attr: str):
            if attr not in made:
                made[attr] = type(attr, (_W,), {})
            return made[attr]

        mod.__getattr__ = _make
        return mod

    tk = _module("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    sys.modules["tkinter"] = tk
    for sub in ("ttk", "font", "messagebox", "simpledialog", "scrolledtext",
                "filedialog"):
        child = _module("tkinter." + sub)
        sys.modules["tkinter." + sub] = child
        setattr(tk, sub, child)


_stub_tk()

from panel.runtime import shops_live                  # noqa: E402
from panel.tabs.shop import ShopTab, order_shelves    # noqa: E402

_APP = _REPO / "panel" / "web" / "app" / "src"


class _Tab:
    """A ShopTab far enough to answer about currencies and nothing else."""

    def __init__(self, purses: dict) -> None:
        self._purses = purses
        self._money: dict = {}

    shelf_moneys = ShopTab.shelf_moneys
    purse_pills = ShopTab.purse_pills
    money_name = ShopTab.money_name
    purse_icon = ShopTab.purse_icon

    def purses(self) -> dict:
        return self._purses

    def t(self, key: str, **fmt) -> str:
        return key + (("|" + repr(sorted(fmt.items()))) if fmt else "")


# ---------------------------------------------------------------------------
# the reading
# ---------------------------------------------------------------------------
def test_a_purse_is_one_record_per_currency():
    read = shops_live.parse_purses(
        "5;;32093;;icon_diamond;;Бриллианты #|# 1004;;90630;;icon_al;;Очки альянса")
    assert [row["cost_id"] for row in read] == ["5", "1004"]
    assert read[0]["have"] == 32093 and read[0]["icon"] == "icon_diamond"
    assert read[1]["name"] == "Очки альянса"


def test_a_balance_the_client_will_not_show_stays_minus_one():
    """-1 is «не видно», and it must never arrive as a zero: they are different facts."""
    read = shops_live.parse_purses("40;;-1;;;;")
    assert read and read[0]["have"] == -1


def test_a_reading_that_said_nothing_is_no_purses_at_all():
    assert shops_live.parse_purses("") == []
    assert shops_live.parse_purses(None) == []


def test_the_purses_ride_the_shelves_own_reading():
    """No second scenario and no clock: one variable of `read_shops`."""
    assert "purses" in shops_live.VARIABLES
    recipe = (_REPO / "src" / "lastwar_bot" / "actions" / "read_shops.md").read_text(
        encoding="utf-8")
    assert "INTO purses" in recipe


# ---------------------------------------------------------------------------
# a shelf may want two
# ---------------------------------------------------------------------------
def test_a_shelf_reports_every_currency_its_rows_are_priced_in():
    """The crystal shop spends two, and both are named — in the rows' own order."""
    rows = [{"cost_id": "5"}, {"cost_id": "1004"}, {"cost_id": "5"}]
    assert _Tab({}).shelf_moneys(rows) == ["5", "1004"]


def test_a_currency_is_the_pair_when_the_type_does_not_name_it():
    """`currencyType` 7 is «an item», not a currency — the item id is part of the key."""
    assert shops_live.money_key({"cost_id": "7", "cost_item": "900002"}) == "7:900002"
    assert shops_live.money_key({"cost_id": "5", "cost_item": ""}) == "5"
    assert shops_live.money_key({"cost_id": "0", "cost_item": "1"}) == ""


def test_two_items_of_one_type_are_two_currencies():
    """Measured live: six shelves all answered type 7 and spent six different items."""
    rows = [{"cost_id": "7", "cost_item": "900002"},
            {"cost_id": "7", "cost_item": "900010"},
            {"cost_id": "7", "cost_item": "900002"}]
    assert _Tab({}).shelf_moneys(rows) == ["7:900002", "7:900010"]


def test_the_pair_is_named_by_the_item_the_reading_named():
    tab = _Tab({"7:900002": {"have": 3242, "icon": "", "name": "Жетон"}})
    pill = tab.purse_pills(["7:900002"])[0]
    assert pill["text"] == "Жетон" and pill["short"] == "3.24K"


def test_a_row_with_no_price_names_no_currency():
    """A money storefront prices nothing, and `0` is not a currency."""
    assert _Tab({}).shelf_moneys([{"cost_id": "0"}, {"cost_id": ""}]) == []


# ---------------------------------------------------------------------------
# what the card draws
# ---------------------------------------------------------------------------
def test_a_pill_is_the_picture_the_short_number_and_the_whole_one():
    tab = _Tab({"5": {"have": 12_345_678, "icon": "", "name": "Бриллианты"}})
    pill = tab.purse_pills(["5"])[0]
    assert pill["text"] == "Бриллианты"
    assert pill["short"] == "12.35M", pill
    assert pill["detail"].replace("\u00a0", "") == "12345678"


def test_a_currency_the_client_will_not_show_says_so_instead_of_zero():
    tab = _Tab({"40": {"have": -1, "icon": "", "name": "Честь"}})
    pill = tab.purse_pills(["40"])[0]
    assert pill["short"] == "—"
    assert pill["detail"] == "shop.purse.hidden"


def test_the_honour_is_called_what_the_game_calls_it():
    """#2832: the client's resource manager will not name type 40, the game's own
    config does — `aps_resources` row 1005 → locale key 457008 — so the panel says
    «Очки чести» out of its own table and never «валюта №40»."""
    import json

    pill = _Tab({"40": {"have": 17_600, "icon": "", "name": ""}}).purse_pills(["40"])[0]
    assert pill["text"] == "shop.money.honor", pill
    for path in sorted((_REPO / "panel" / "locales").glob("*.json")):
        said = json.loads(path.read_text(encoding="utf-8"))
        assert said.get("shop.money.honor"), path.name


def test_a_currency_nothing_has_read_yet_is_not_a_zero_either():
    pill = _Tab({}).purse_pills(["7"])[0]
    assert pill["short"] == "—"
    assert pill["detail"] == "shop.purse.unread"
    assert pill["text"].startswith("shop.money.other")


def test_a_currency_with_no_extracted_sprite_draws_no_picture():
    """Never a stand-in: a machine that has not extracted the art sends no icon."""
    pill = _Tab({"5": {"have": 1, "icon": "", "name": "Б"}}).purse_pills(["5"])[0]
    assert "icon" not in pill


# ---------------------------------------------------------------------------
# one pill, drawn once
# ---------------------------------------------------------------------------
def test_the_front_end_has_exactly_one_pill_component():
    view = (_APP / "views" / "ScreenView.tsx").read_text(encoding="utf-8")
    assert view.count("function ResPill(") == 1
    assert view.count('className="pill-res"') == 1, (
        "a second pill spelled out beside the component is the second control this "
        "repository forbids (CLAUDE.md)")
    assert "card.pills" in view, "a card's own currencies must be drawn"


def test_the_shelf_card_sends_its_currencies():
    shop = (_REPO / "panel" / "tabs" / "shop.py").read_text(encoding="utf-8")
    assert '"pills": self.purse_pills(moneys)' in shop
    assert "for each in moneys" in shop, "one ceiling per currency, not one per shelf"
    assert 'caps.append({"key": "cap:" + kind_of' in shop, (
        "the ceiling is written per currency TYPE, which is what the autobuy recipe "
        "counts by — two item currencies of one type share it")


def test_no_recipe_prices_a_shelf_against_what_it_sells():
    """`resourceitem_id` is the item a row HANDS OVER, and no purse may count it (#2830)."""
    actions = _REPO / "src" / "lastwar_bot" / "actions"
    for name in ("read_shops.md", "autobuy_shop_goods.md", "buy_shop_goods.md"):
        text = (actions / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if not (line.startswith("READ_LUA ") or line.startswith("LUA ")):
                continue        # prose may name the field; only the CODE may not use it
            assert "resourceitem_id" not in line, (
                name + " still reads resourceitem_id as a currency — it is what the row "
                "sells (the honour shelf carries four different ones)")


def test_the_honour_purse_and_the_diamond_one_are_where_the_game_keeps_them():
    recipe = (_REPO / "src" / "lastwar_bot" / "actions" / "read_shops.md").read_text(
        encoding="utf-8")
    assert "GetHonorScore" in recipe, "honour is its own reading, not a resource type"
    assert "LuaEntry.Player.gold" in recipe, "the diamonds are the player's gold"


# ---------------------------------------------------------------------------
# the order the chips stand in (#2830)
# ---------------------------------------------------------------------------
def test_the_chips_stand_in_the_order_the_person_asked_for():
    """Diamonds, VIP, alliance, honour, expedition, season, decoration, coupons."""
    game = ["common:9", "common:1", "money:1", "common:200", "market:0",
            "common:10", "common:2", "common:7", "common:11", "common:8",
            "common:100", "common:150"]
    assert order_shelves(game)[:8] == ["common:1", "common:2", "common:7", "common:8",
                                       "common:100", "common:200", "common:150",
                                       "common:10"]


def test_the_rest_keep_the_game_s_own_order_at_the_tail():
    """A shelf nobody has named, and the money storefronts, stay behind — in place."""
    game = ["common:9", "common:1", "money:1", "market:0", "common:11"]
    assert order_shelves(game) == ["common:1", "common:9", "money:1", "market:0",
                                   "common:11"]


def test_a_shelf_the_account_has_not_got_moves_nothing():
    assert order_shelves(["common:8", "common:1"]) == ["common:1", "common:8"]
    assert order_shelves([]) == []


def test_nothing_is_ordered_by_a_translated_name():
    """The order is the shelf's own number — a name is eleven different orders."""
    shop = (_REPO / "panel" / "tabs" / "shop.py").read_text(encoding="utf-8")
    head = shop.partition("SHELF_ORDER = ")[2].partition(")")[0]
    assert "shop.kind" not in head, "the order must not be written in locale keys"
    assert "common:1" in head


# ---------------------------------------------------------------------------
# the balance keeps up by itself (#2830)
# ---------------------------------------------------------------------------
def test_the_ear_hears_BOTH_halves_of_the_balance_news():
    """A subscription is a CONTAINS match, so one pattern has to cover both pushes.

    The item currencies move on `push.resource.item.update`; the diamonds and the honour
    are not items and move on `push.resource.info`. Hearing only the first is what left
    the honour pill saying 7 700 while the client held 16 200.
    """
    assert shops_live.PUSH == "push.resource."
    for command in ("push.resource.item.update", "push.resource.info"):
        assert shops_live.PUSH in command


def test_one_burst_still_costs_one_reading():
    """The wider pattern may not buy a second clock: the debounce is one per watch."""
    assert shops_live.DEBOUNCE_SEC >= 120.0


# ---------------------------------------------------------------------------
# the currency beside the PRICE, on the goods tile (#2830)
# ---------------------------------------------------------------------------
def test_the_price_carries_the_currency_s_own_picture():
    """With a picture the word leaves the line and stays in the title — see `good`."""
    shop = (_REPO / "panel" / "tabs" / "shop.py").read_text(encoding="utf-8")
    assert '"price_icon"' in shop and '"price_note"' in shop
    view = (_APP / "views" / "ScreenView.tsx").read_text(encoding="utf-8")
    assert "item.price_note || item.price" in view, "the full price must be the title"
    assert "item.price_icon ?" in view


def test_a_currency_with_no_sprite_keeps_its_word_on_the_line():
    """Nothing stands in for a missing picture, and the line may not go blank either."""
    tab = _Tab({"40": {"have": 7700, "icon": "", "name": ""}})
    pills = tab.purse_pills(["40"])
    assert pills and "icon" not in pills[0]
    assert pills[0]["short"] and pills[0]["text"]


def test_the_purse_reading_is_held_for_one_drawing_only():
    """Forty blob reads a shelf is what the memo exists to stop — and it is DROPPED."""
    shop = (_REPO / "panel" / "tabs" / "shop.py").read_text(encoding="utf-8")
    assert "_purse_memo" in shop and "def forget_purses" in shop
    body = shop.partition("def shelf_cards")[2]
    assert "self.forget_purses()" in body.partition("def ")[0]


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:      # noqa: BLE001 — a raise is a failure too
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
