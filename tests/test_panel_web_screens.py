r"""A tab's own screen on the phone: the contract, and the thing it exists to stop.

`PanelTab.web_view()` returns a tab as DATA and the browser draws it with one renderer
(`panel/web/static/app.js`). The whole arrangement rests on one distinction, and this
file is what keeps it true:

* `title`, `label`, `empty`, `pill` are **locale keys** — the browser says them out of
  the panel's own table, so a screen is in eleven languages by construction;
* `text`, `value`, `detail`, `note`, `head` are **data** — a player's name, a count, a
  date — and are shown as they are.

Get that backwards once and a Russian sentence reaches somebody running the panel in
Turkish, with nothing to catch it: `tests/test_panel_i18n.py` only reads `.py` for
`t()` / `tr()` calls, and a string returned in a dict is neither.

The other half is CHEAPNESS. `web_view` is called on the Tk thread every time a phone
opens a screen, so it must return what the tab already has and never read the game — a
phone left on a screen would otherwise poll the client all day.

    C:\Python312\python.exe tests\test_panel_web_screens.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import i18n as i18nmod          # noqa: E402
from panel import tabs as tabsreg          # noqa: E402

#: A locale key: dotted, lower-case, no spaces — the same shape the i18n test pins.
_KEYISH = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")

#: Where a KEY is expected, and where DATA is.
_KEY_FIELDS = ("title", "label", "empty", "pill")
_DATA_FIELDS = ("text", "value", "detail", "note", "head")


def _english() -> dict:
    return json.loads((Path(i18nmod.LOCALES_DIR) / "en.json").read_text(encoding="utf-8"))


def _tabs_with_screens() -> list:
    out = []
    for spec in tabsreg.TABS:
        cls = spec.load()
        if getattr(cls, "WEB_SCREEN", False):
            out.append((spec.id, cls))
    return out


def _keys_in(view: dict) -> list:
    """Every locale key a view names, wherever it sits."""
    found = []
    for card in view.get("cards") or ():
        for field in _KEY_FIELDS:
            if card.get(field):
                found.append(card[field])
        for row in card.get("rows") or ():
            if row.get("label"):
                found.append(row["label"])
        for item in card.get("items") or ():
            if item.get("pill"):
                found.append(item["pill"])
            for fact in item.get("facts") or ():
                found.append(fact.get("label", ""))
            for action in item.get("actions") or ():
                found.append(action.get("label", ""))
    for action in view.get("actions") or ():
        found.append(action.get("label", ""))
    return [k for k in found if k]


# ---------------------------------------------------------------------------
def test_the_tabs_that_offer_a_screen_are_the_ones_that_should():
    """Three tabs say no on purpose, and it is a decision rather than an oversight.

    «Настройки» is paths, interpreters and ports — breaking a profile with one thumb is
    easier than fixing it from a bus. «Веб» is the door the person came in through.
    «Develop» is two sniffers for working on the bot itself.
    """
    offered = {tab_id for tab_id, _cls in _tabs_with_screens()}
    for never in ("settings", "web", "develop"):
        assert never not in offered, (
            f"«{never}» offers a phone screen — that was decided against "
            f"(docs/research/panel-web.md §4)")


def test_every_screen_is_made_of_keys_and_data_and_never_of_sentences():
    """The one rule the renderer cannot enforce for itself."""
    english = _english()
    bad = []
    for tab_id, cls in _tabs_with_screens():
        view = _sample_view(cls)
        if view is None:
            continue
        for key in _keys_in(view):
            if not _KEYISH.match(key):
                bad.append(f"{tab_id}: «{key}» is a sentence, not a locale key")
            elif key not in english:
                bad.append(f"{tab_id}: key «{key}» is in no locale")
    assert not bad, "\n  ".join([""] + bad)


def test_a_screen_is_cards_and_nothing_the_renderer_cannot_draw():
    """The shape is small on purpose: four things, and a phone renderer for each."""
    allowed_card = {"title", "head", "rows", "items", "empty", "search"}
    allowed_item = {"text", "detail", "note", "pill", "actions", "facts", "until"}
    for tab_id, cls in _tabs_with_screens():
        view = _sample_view(cls)
        if view is None:
            continue
        assert isinstance(view.get("cards"), list), f"{tab_id}: no cards"
        for card in view["cards"]:
            extra = set(card) - allowed_card
            assert not extra, f"{tab_id}: card has {sorted(extra)}"
            for item in card.get("items") or ():
                extra = set(item) - allowed_item
                assert not extra, f"{tab_id}: item has {sorted(extra)}"


def test_the_data_tabs_hand_over_what_they_already_read():
    """`web_view` must not read the game: it is called every time a phone opens it."""
    from panel.tabs._data import DataTab

    for tab_id, cls in _tabs_with_screens():
        if not issubclass(cls, DataTab):
            continue
        tab = cls.__new__(cls)          # no Tk, no runtime: only the data path
        tab._last_data = None
        tab._busy = False
        view = tab.web_view()
        assert view["cards"], f"{tab_id}: an unread tab says nothing at all"
        assert view["cards"][0].get("empty") == "web.ui.not_read", view


def _sample_view(cls):
    """A view built off a stand-in reading, with no Tk and no game.

    A `DataTab` is asked for its cards directly (that is the only part each of the six
    writes); anything else is skipped here and covered by its own tab's test.
    """
    from panel.tabs._data import DataTab

    if not issubclass(cls, DataTab):
        return None
    tab = cls.__new__(cls)
    tab._last_data = _SAMPLES.get(cls.ID, [])
    tab._busy = False
    try:
        return {"cards": cls.web_cards(tab, tab._last_data), "actions":
                [{"id": "refresh", "label": "tabx.refresh"}]}
    except Exception as exc:            # noqa: BLE001 — a mapping that throws is a fail
        raise AssertionError(f"{cls.ID}: web_cards raised {type(exc).__name__}: {exc}")


#: One plausible reading per tab, in the shape that tab's own `fetch()` returns.
_SAMPLES = {
    "profile": {"nick": "Somebody", "level": "30", "power": "12000000",
                "resources": {"food": 1000, "wood": 2000}},
    "alliance": [{"name": "Somebody", "level": 30, "power": 12000000,
                  "online": True, "offline": 0}],
    "inventory": [{"name": "Speedup 5m", "count": 12, "desc": "five minutes"}],
    "heroes": [{"name": "Somebody", "level": 30, "power": 4000}],
    "accounts": [{"name": "Somebody", "server": 935}],
}


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:                    # noqa: BLE001
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
