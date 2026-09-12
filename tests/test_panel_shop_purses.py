r"""Чем платим и сколько этого есть — the shop's currencies, with a shelf that wants two.

The person's words (#2830): «В магазинах выведи картинку валюты и сумму баланса, обрати
внимание, что в кристаллическом магазине сразу 2 валюты используются».

What is pinned here:

* the reading carries a record per CURRENCY, and «the client will not show it» (-1)
  survives the trip as itself rather than as a zero;
* a shelf reports EVERY currency its rows are priced in, in the order they name them —
  the code it replaced took the first one and called it «the shop's currency»;
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
from panel.tabs.shop import ShopTab                   # noqa: E402

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
    assert 'for each in moneys' in shop, "one ceiling per currency, not one per shelf"


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
