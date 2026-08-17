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

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import i18n as i18nmod          # noqa: E402
from panel import tabs as tabsreg          # noqa: E402
from panel.tabs.base import PanelTab       # noqa: E402

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
            if item.get("label"):
                found.append(item["label"])
            for fact in item.get("facts") or ():
                found.append(fact.get("label", ""))
            for action in item.get("actions") or ():
                found.append(action.get("label", ""))
                # A press that asks for a WORD (#1335) names the box's title the same
                # way it names its own label — a key, said by the browser.
                found.append(action.get("prompt", ""))
    for action in view.get("actions") or ():
        found.append(action.get("label", ""))
        found.append(action.get("prompt", ""))
    return [k for k in found if k]


# ---------------------------------------------------------------------------
def test_the_tabs_that_offer_a_screen_are_the_ones_that_should():
    """Two tabs say no on purpose, and it is a decision rather than an oversight.

    «Настройки» is paths, interpreters and ports — breaking a profile with one thumb is
    easier than fixing it from a bus. «Develop» is two sniffers for working on the bot
    itself. There were THREE until #1313: «Веб» was the third, and it is now a menu
    entry rather than a tab — see the test below, which is where its half of this
    decision went.
    """
    offered = {tab_id for tab_id, _cls in _tabs_with_screens()}
    for never in ("settings", "develop"):
        assert never not in offered, (
            f"«{never}» offers a phone screen — that was decided against "
            f"(docs/research/panel-web.md §4)")


def test_the_remote_controls_own_settings_are_reachable_from_the_window_only():
    """The door the person came in through is not opened from the far side (#1313).

    The knobs moved off a tab and onto the menu bar, because one server answers for
    every open profile and its port, token and certificate are the WINDOW's. What did
    not change is the divergence: locking yourself out with one thumb is easier than
    walking back to the machine to undo it. So there is no `web` tab to grow a screen,
    and the API has no route of its own for any of this.
    """
    assert "web" not in {spec.id for spec in tabsreg.TABS}, (
        "the «Веб» tab is back — its settings belong to the window (#1313)")
    api = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert "web_control" not in api, (
        "the API reaches the remote control's own settings — a phone that can move the "
        "port or the token is a phone that can lock the person out of the panel")


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
    # `actions` is a card's own footer of buttons (`app.js`, `pressButton`) — the same
    # shape as the screen-wide ones, drawn under the card they belong to. «Кодовое имя»
    # is the first block to need one: the press belongs to that event and not to the
    # whole board (#1257).
    allowed_card = {"title", "head", "rows", "items", "empty", "search", "actions"}
    # `avatar` is a LINK to the panel's own picture route, not bytes and not a word: the
    # «Ралли» screen draws the face of everybody standing in a banner, out of the game
    # client's own cache (#1324). The renderer draws it as an <img> and drops it if it
    # will not load, so an item that has one degrades to the item without one.
    # `icon` is the same thing for a picture the GAME composed rather than a photograph
    # — an inventory cell, a rarity frame with the item drawn on it (#1469). Square and
    # un-cropped where a face is round, and it degrades the same way.
    allowed_item = {"text", "label", "detail", "note", "pill", "actions", "facts",
                    "until", "avatar", "icon"}
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
        # The tab's OWN view, not one assembled here: the actions it offers have to
        # come from the tab, or the dead-button guard would be checking the harness.
        return cls.web_view(tab)
    except Exception as exc:            # noqa: BLE001 — a mapping that throws is a fail
        raise AssertionError(f"{cls.ID}: web_view raised {type(exc).__name__}: {exc}")


#: One plausible reading per tab, in the shape that tab's own `fetch()` returns.
_SAMPLES = {
    "profile": {"nick": "Somebody", "level": "30", "power": "12000000",
                "resources": {"food": 1000, "wood": 2000}},
    "alliance": [{"name": "Somebody", "level": 30, "power": 12000000,
                  "online": True, "offline": 0}],
    "inventory": [{"id": 400204, "name": "Speedup 5m", "count": 12, "colour": 3,
                   "type": 0, "icon": "icon_item_400204"}],
    "heroes": [{"name": "Somebody", "level": 30, "power": 4000}],
    "accounts": [{"name": "Somebody", "server": 935}],
}


def test_a_button_offered_on_a_screen_has_a_handler_that_answers_for_it():
    """A dead button is the half-done mirror this CAN be caught.

    «Any edit to a tab travels to the web at the same time» (`CLAUDE.md`) is a property
    of a DIFF and no snapshot test can see it. What a snapshot CAN see is the commonest
    way the mirror ends up half done: an action offered in `web_view` that `web_press`
    knows nothing about. On the phone that is a button which does nothing at all and
    says «unknown» — the exact failure a person cannot diagnose from a bus.
    """
    dead = []
    for tab_id, cls in _tabs_with_screens():
        view = _sample_view(cls)
        if view is None:
            continue
        offered = [a.get("id") for a in view.get("actions") or ()]
        for card in view.get("cards") or ():
            for item in card.get("items") or ():
                offered += [a.get("id") for a in item.get("actions") or ()]
        if not offered:
            continue
        assert cls.web_press is not PanelTab.web_press, (
            f"{tab_id}: offers {offered} and never overrides web_press")
        tab = cls.__new__(cls)
        for action in offered:
            answer = _press(tab, action)
            assert answer.get("error") != "unknown", (
                f"{tab_id}: «{action}» is offered on the screen and web_press does not "
                f"know it — a button that does nothing")
        # …and something invented is still refused, so «unknown» means what it says.
        assert _press(tab, "no-such-action-ever").get("error") == "unknown", (
            f"{tab_id}: web_press accepts anything at all")


def _press(tab, action: str) -> dict:
    """`web_press` on a bare instance: only the routing, never the work.

    The handlers here reach the runtime (a refresh spawns a thread), which a bare
    instance has none of — so anything that gets PAST the routing is treated as
    accepted. What is being asserted is that the action is recognised, not that it runs.
    """
    try:
        return tab.web_press(action, {}) or {}
    except Exception:                   # noqa: BLE001 — it got past the routing
        return {"ok": True}


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
