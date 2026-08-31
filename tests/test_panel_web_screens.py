r"""A tab's own screen on the phone: the contract, and the thing it exists to stop.

`PanelTab.web_view()` returns a tab as DATA and the browser draws it with one renderer
(`panel/web/app/src`). The whole arrangement rests on one distinction, and this
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


#: The registry by id — for a test that asks ONE tab a question and does not want the
#: other nineteen imported to find it. (It was used before it existed: two tests reached
#: for `BY_ID` and the file has no display in WSL, so nobody ran into the `NameError`.)
BY_ID = {spec.id: spec for spec in tabsreg.TABS}


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
        # A KNOB'S OWN LABEL IS A KEY TOO (#1976). Since a card may SET as well as show,
        # most of what a screen says is now in its fields — «Дуэль» alone declares a
        # hundred of them — and none of it was being read here.
        for field in card.get("fields") or ():
            if field.get("label"):
                found.append(field["label"])
        for action in card.get("actions") or ():
            found.append(action.get("label", ""))
            found.append(action.get("prompt", ""))
            found.append(action.get("confirm", ""))
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
        # A press that ASKS FIRST names its question the same way (#1976).
        found.append(action.get("confirm", ""))
    return [k for k in found if k]


# ---------------------------------------------------------------------------
def test_every_tab_offers_a_screen_and_the_last_two_exceptions_are_gone():
    """THERE WERE THREE, AND THERE ARE NONE (#1976), each ended by the person who made it.

    «Веб» stopped being a tab at all in #1313 — its knobs belong to the window, see the
    test below. «Настройки» kept its divergence for as long as there were two front-ends
    and the window was the safe one; with the window going away, a knob with no screen is
    a knob nobody can reach, which is worse than one somebody can get wrong. What survives
    of that decision lives INSIDE the screen: the four values that decide which client a
    profile drives — the two machine paths, the port and the Windows session — are
    readings there and not fields.

    «Разработка» was the last one, and it was ended the same way: it says «two sniffers
    for working on the bot itself», which was never true of «Занятость» — «почему панель
    ничего не делает» is exactly the question somebody away from the machine cannot ask
    any other way. The tab is still `DEFAULT_ENABLED = False` and still hidden unless the
    profile is in development mode, so a panel that has not asked for it is handed
    nothing; what the screen does NOT carry is pinned below.
    """
    offered = {tab_id for tab_id, _cls in _tabs_with_screens()}
    assert "develop" in offered, (
        "«Разработка» has no phone screen — the divergence was ended in #1976")
    assert "settings" in offered, (
        "«Настройки» has no phone screen — with one front-end left that is a page "
        "nobody can reach (#1976)")


def test_the_recording_pair_is_pressed_by_ITS_OWN_ids_and_no_others():
    """The sniffers travel whole since #2072, and only under their own names.

    They used to be words alone: starting a recording asked for a label in a message box
    and stopping it opened the keep-or-throw-away prompt, both modals raised on a machine
    nobody is standing at — and the live panel has no window at all, so the switch was
    one nobody could throw. Both questions are ARGUMENTS of the press now
    (`sniff_start` / `sniff_stop` / `sniff_discard`, `args.text`), so nothing on the path
    raises a box. What is pinned here is that nothing ELSE became pressable: a knob named
    «sniff» is still not a knob of this screen, and the bare verbs are still nobody's.
    """
    cls = BY_ID["develop"].load()
    tab = cls.__new__(cls)
    for never in ("sniff", "trace", "scenario", "loop"):
        answer = tab.web_press("set", {"key": never, "value": True})
        assert answer == {"error": "unknown"}, (
            f"«{never}» is not a knob of this screen: {answer}")
    for never in ("start", "stop", "save"):
        assert tab.web_press(never, {}) == {"error": "unknown"}, never
    tab._sniff_proc = tab._trace_proc = None
    assert tab.web_press("sniff_stop", {"text": "x"}) == {
        "ok": False, "reason": "develop.web.not_running"}


def test_the_settings_screen_refuses_what_decides_which_client_is_driven():
    """What decides WHICH CLIENT a profile drives is a reading, never a field (#1976).

    A thumb-slip on the daemon port or the Windows session points a profile at somebody
    else's account or at nothing at all — and the panel's three statuses go on saying
    everything is fine, because from the panel's side it IS. The machine paths are not
    even a person's answer to give (`tools/lib/game_paths.py`).

    Asked of the PRESS rather than of the view, because the press is the half that
    matters: a field that is not drawn cannot be tapped, but a request can still be
    made by hand, and «unknown» is the answer that keeps the reasoning true either way.
    """
    tab = BY_ID["settings"].load().__new__(BY_ID["settings"].load())
    for never in ("win_python", "launcher", "game_exe", "daemon_port", "rdp_session",
                  "rdp_user"):
        answer = tab.web_press("set", {"key": never, "value": 1})
        assert answer == {"error": "unknown"}, (
            f"«{never}» can be set from the phone — that is the one part of the old "
            f"«Настройки» divergence that still holds (#1976): {answer}")


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
    # `fields` and `note` are the settings shape (#1976): a card that SETS rather than
    # shows. A field is a knob — its own id, a label key, a kind and a value — and the
    # renderer draws the control the kind names.
    # `layout` is how a card's ITEMS are drawn (#1999, #2119): absent or `rows` is the
    # wide row a list has always been, `tiles` is a wrap of small buttons for a card
    # whose items are places, and `cards` is the card an errand is drawn as — a picture
    # behind it, the name on one line, a switch in the corner — for a card whose items
    # have a FACE. Only those three: the renderer knows no fourth, and a card asking for
    # one would silently fall back to rows.
    allowed_card = {"title", "head", "rows", "items", "empty", "search", "actions",
                    "fields", "note", "flow", "layout"}
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
            assert card.get("layout", "rows") in ("rows", "tiles", "cards"), (
                f"{tab_id}: card layout {card.get('layout')!r}")
            for item in card.get("items") or ():
                extra = set(item) - allowed_item
                assert not extra, f"{tab_id}: item has {sorted(extra)}"


def test_a_list_of_places_is_drawn_as_buttons_and_names_cards_that_exist():
    """The ★ list, the robbery list and their neighbours are TILES, not rows (#1999).

    The person's words: «карта, секретки грабеж: делаем не грид с секретками в одну
    строку, а небольшие кнопки с минимальной информацией». Two tabs declare which of
    their cards that applies to (`TILE_CARDS`) and one loop attaches it, so what can go
    wrong is not the drawing — it is the TABLE going stale: a card renamed, and its entry
    left behind, silently putting the longest list on the screen back into rows.

    So both halves are pinned. Every name in a table must be a real locale key, and —
    where there is a display to build a page with — must actually be the title of a card
    that tab hands over.
    """
    english = _english()
    tabled = [(tab_id, cls) for tab_id, cls in _tabs_with_screens()
              if getattr(cls, "TILE_CARDS", None)]
    assert tabled, "nobody declares TILE_CARDS any more — was the table renamed?"
    bad = []
    for tab_id, cls in tabled:
        for title in cls.TILE_CARDS:
            if title not in english:
                bad.append(f"{tab_id}: TILE_CARDS names «{title}», which is in no locale")
    assert not bad, "\n  ".join([""] + bad)

    harness = _page()
    if harness is None:
        return
    stale = []
    try:
        app, session = harness.app, harness.session
        with app._on(session):
            for tab_id, cls in tabled:
                tab = session.rt.tabs.get(tab_id)
                if tab is None:
                    continue                    # not in this profile — nothing to draw
                view = tab.web_view() or {}
                cards = view.get("cards") or []
                titles = {card.get("title") for card in cards}
                for title in cls.TILE_CARDS:
                    if title not in titles:
                        stale.append(f"{tab_id}: TILE_CARDS names «{title}», "
                                     f"which is no card of this tab")
                for card in cards:
                    want = "tiles" if card.get("title") in cls.TILE_CARDS else "rows"
                    got = card.get("layout", "rows")
                    if got != want:
                        stale.append(f"{tab_id}: «{card.get('title')}» is drawn as "
                                     f"{got}, not {want}")
    finally:
        harness.close()
    assert not stale, "\n  ".join([""] + stale)


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


def test_the_base_stock_is_the_profile_screens_card_and_asking_for_it_is_the_ear():
    """#1990, second pass: the live stock left «Состояние» for «Профиль».

    Two things have to hold at once, and the second is the one that would have gone
    unnoticed for months. The card is on THIS screen — and BUILDING it is what calls
    `BaseResources.state()`, which is both the reading and the SUBSCRIPTION to
    `push.resource.item.update` (`panel/runtime/resources.py`). A card copied across
    without that call draws a balance nothing ever updates, and looks perfectly healthy
    doing it.

    It also pins the two halves of the renderer's contract on this card: the resource's
    NAME is the game's own word and travels as data, while everything the panel says
    about it — the heading, the age line, «слежу за событиями игры» — is a key.
    """
    from panel.tabs.profile import ProfileTab

    asked = []

    class _Stock:
        def state(self):
            asked.append(1)
            return {"rows": [{"type": 2, "count": 1234567, "max": 0, "per_hour": 0,
                              "base": False, "pending": 4200, "name": "Gold coins"}],
                    "watching": True, "age": 7.4, "reading": False}

    class _Rt:
        def __init__(self) -> None:
            self.resources = _Stock()

        def t(self, key, **fmt):         # the runtime's own shape; the key IS the answer
            return key

    tab = ProfileTab.__new__(ProfileTab)
    tab.rt = _Rt()
    tab._last_data = None
    tab._busy = False
    view = ProfileTab.web_view(tab)
    assert asked, "the card was drawn without asking BaseResources — the ear never rises"
    card = (view.get("cards") or [None])[0]
    assert card and card.get("title") == "web.ui.res.head", card
    assert card["flow"]["key"] == "web.ui.res.age", card["flow"]
    assert card["flow"]["fmt"]["sec"] == 7, card["flow"]
    assert card["note"] == "web.ui.res.live", card
    item = (card.get("items") or [None])[0]
    assert item and item["text"] == "Gold coins", item      # the GAME's word, as data
    assert "1,234,567" in item["detail"], item
    assert item.get("note"), "the pending figure is the half of the card one can act on"


def test_an_unreadable_stock_costs_the_profile_screen_nothing():
    """A runtime with no resources object is a missing card, never a missing screen."""
    from panel.tabs.profile import ProfileTab

    tab = ProfileTab.__new__(ProfileTab)
    tab._last_data = None
    tab._busy = False                    # …and no `rt` at all
    view = ProfileTab.web_view(tab)
    assert view and view.get("cards"), view
    assert all(c.get("title") != "web.ui.res.head" for c in view["cards"]), view


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


def _page():
    """A real window with a real page in it, or ``None`` where there is no display.

    Borrowed from `tests/test_panel_page_build.py` rather than grown a second time —
    the same harness `tests/test_panel_web.py` uses for the two facts it has about the
    window. Only a Tk failure is a skip: anything the page build itself raises belongs
    to that file and would be hidden here.
    """
    sys.path.insert(0, str(_REPO / "tests"))
    try:
        import tkinter as tk

        import test_panel_page_build as pagebuild

        tk.Tk().destroy()
    except Exception:                               # noqa: BLE001 — no display
        return None
    try:
        return pagebuild._Harness(staged=False)
    except Exception:                               # noqa: BLE001
        return None


def test_every_screen_builds_on_a_real_page_and_says_only_keys():
    """THE ONE THE SNAPSHOT TESTS ABOVE CANNOT ASK (#1976).

    Everything above is built off a stand-in reading with no Tk, which only a `DataTab`
    can be given — so twelve tabs offer a screen and six of them were never asked to
    produce one at all. «Дуэль» read `item.label_key` and `amount.label_key` for months;
    no item has either (the attribute is `label`), so the screen raised on any day with
    anything ticked, and every test in this file passed because none of them ever called
    that `web_view`.

    So: a real page, every tab that offers a screen DRAWN exactly as the API draws it
    (`rt.tabs.get`, which realises it — #1215), and its own view asked for. Two things
    are asserted, and they are the two that have actually gone wrong: it must not raise,
    and every word in it must be a key that exists.
    """
    harness = _page()
    if harness is None:
        return
    english = _english()
    broke, bad = [], []
    try:
        app, session = harness.app, harness.session
        with app._on(session):
            for tab_id, _cls in _tabs_with_screens():
                tab = session.rt.tabs.get(tab_id)
                if tab is None:
                    continue                    # not in this profile — nothing to draw
                try:
                    view = tab.web_view()
                except Exception as exc:        # noqa: BLE001 — that IS the finding
                    broke.append(f"{tab_id}: web_view raised "
                                 f"{type(exc).__name__}: {exc}")
                    continue
                if not isinstance(view, dict):
                    continue                    # a tab may answer «nothing to show»
                for key in _keys_in(view):
                    if not _KEYISH.match(key):
                        bad.append(f"{tab_id}: «{key}» is a sentence, not a locale key")
                    elif key not in english:
                        bad.append(f"{tab_id}: key «{key}» is in no locale")
    finally:
        harness.close()
    assert not broke, "\n  ".join([""] + broke)
    assert not bad, "\n  ".join([""] + bad)


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
