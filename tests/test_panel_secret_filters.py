r"""The ★ list is drawn whole, narrowed by chips, and remembers which chip (#2740).

Three complaints in one sentence from the person: «при обходе карты, секретки не
появляются во вкладке, только после рефреша страницы. Убрать пагинацию на секретках.
Добавить фильтр-кнопки: готовые. При смене вкладки, фильтры должны сохраняться.»

The first two are one fault. The panel's answer to `/api/screen` was measured growing
live — 69 items to 82 during one lap — so nothing was missing from it; what the phone did
was cut the card to thirty tiles with «Показать ещё» under them, and a lap brings tiles in
wherever the sort puts them. New ones landed under the cut, and the list looked frozen.

No Tk and no client — the methods here are pure and the rest is read off the source::

    python3 tests/test_panel_secret_filters.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import types

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

TIER = "offline"

def _stub_tk() -> None:
    """Borrowed whole from `tests/test_panel_monster_filter.py` — see its own note.

    The rules under test are a pure method and the text of two files; demanding a display
    for either would make this a test nobody runs on the machine they are editing on.
    """
    from test_panel_monster_filter import _stub_tk as borrow

    borrow()


sys.path.insert(0, str(_REPO / "tests"))
_stub_tk()

_TAB = _REPO / "panel" / "tabs" / "secret_tasks" / "tab.py"
_SCREEN = _REPO / "panel" / "web" / "app" / "src" / "views" / "ScreenView.tsx"

#: The cards that hold a list of tiles this task is about. `world.*` is deliberately NOT
#: here: those carry five hundred rows apiece and are a different question.
_WHOLE_CARDS = ("secrettasks.page.stars", "secrettasks.alliance", "secrettasks.ghost",
                "secrettasks.ghost.allies", "secrettasks.ghost.map")


def _filters(tally, total):
    """`_star_filters` off the class, with only the constant it reads standing in."""
    from panel.tabs.secret_tasks.tab import SecretTasksTab

    stub = types.SimpleNamespace(STAR_FILTERS=SecretTasksTab.STAR_FILTERS)
    return SecretTasksTab._star_filters(stub, tally, total)


def test_every_secret_task_list_is_drawn_whole():
    """«Убрать пагинацию на секретках» — and it is the same fault as «не появляются»."""
    text = _TAB.read_text(encoding="utf-8")
    for title in _WHOLE_CARDS:
        head = text.index('"title": "%s"' % title)
        # As far as the card's own items, which is where its flags stand.
        body = text[head:head + 2600]
        assert '"whole": True' in body, (
            f"{title} is still cut into pages")


def test_the_chips_always_offer_a_way_back_and_never_an_empty_one():
    chips = _filters({"ready": 3, "waiting": 12}, 15)
    assert chips[0]["id"] == "" and chips[0]["count"] == 15, chips
    assert [c["id"] for c in chips] == ["", "ready", "waiting"], chips
    # A state with nothing in it is not offered: pressing it would empty the card and
    # say nothing.
    assert [c["id"] for c in _filters({}, 0)] == [""]
    assert all(c["count"] for c in _filters({"robbed": 2}, 2))


def test_ready_is_the_first_chip_after_all():
    """It is the one the person asked for by name, and the only one that is a decision."""
    from panel.tabs.secret_tasks.tab import SecretTasksTab

    assert SecretTasksTab.STAR_FILTERS[0][0] == "ready"


def test_every_chip_label_is_a_key_that_exists_in_every_locale():
    from panel.tabs.secret_tasks.tab import SecretTasksTab

    keys = ["web.ui.filter.all"] + [label for _id, label in SecretTasksTab.STAR_FILTERS]
    locales = sorted((_REPO / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11, locales
    for path in locales:
        words = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in words, f"{path.name} has no {key}"


def test_a_row_carries_exactly_one_chip_word():
    """The tag is what the row IS, in the order the pill already decides."""
    text = _TAB.read_text(encoding="utf-8")
    tag = text[text.index('tag = ("robbed" if robbed'):]
    tag = tag[:tag.index("\n\n")] if "\n\n" in tag[:400] else tag[:400]
    for word in ("robbed", "spent", "ready", "waiting"):
        assert '"%s"' % word in tag, f"{word} is not one of the chips a row can wear"


def test_the_count_beside_the_heading_is_what_can_be_taken():
    """«Счетчик во вкладке с секретками выводим только готовые» — the panel says which.

    A list of eighty-two tiles of which twelve are ripe is answered by «12»: the number is
    read as «сколько мне тут есть», and the total is the one figure that does not say it.
    Nothing is hidden — the whole tally is on the chips beside it.
    """
    text = _TAB.read_text(encoding="utf-8")
    head = text.index('"title": "secrettasks.page.stars"')
    body = text[head:head + 2600]
    assert '"count": int(tally.get("ready") or 0)' in body, (
        "the ★ card counts its rows again instead of what can be taken")
    screen = _SCREEN.read_text(encoding="utf-8")
    assert "function cardCount(card: ViewCard): number" in screen, (
        "the front-end has no way to draw a count the panel chose")
    assert "if (typeof card.count === 'number') return card.count" in screen
    # …and a card that sends none is counted by its rows, exactly as before.
    assert "return (card.items || []).length" in screen


def test_a_ready_tile_is_coloured_and_the_colour_lives_in_the_stylesheet():
    """«Готовые карточки секретки измени цветом» — the panel names the state, the
    front-end paints it with the palette it already has. No colour in the panel, no
    second theme, and only «готово» is lifted: a wall in which everything is coloured is
    a wall in which nothing is."""
    text = _TAB.read_text(encoding="utf-8")
    assert '{"tone": "ok"} if tag == "ready"' in text, (
        "a ready tile carries no tone, or something other than ready does")
    # …and the panel names a STATE, never a colour: no CSS anywhere in the tab, and the
    # only tone word it uses is one the stylesheet has a rule for.
    import re

    for colour in ("rgb(", "var(--", "color-mix("):
        assert colour not in text, f"a colour has been written into the panel: {colour}"
    assert not re.search(r"#[0-9a-fA-F]{6}\b", text), "a hex colour is in the panel"
    used = set(re.findall(r'"tone": "(\w+)"', text))
    assert used <= {"ok", "warn", "bad"}, used
    screen = _SCREEN.read_text(encoding="utf-8")
    assert "' tone-' + item.tone" in screen, "the tile does not wear the tone"
    css = (_REPO / "panel" / "web" / "app" / "src" / "app.css").read_text(encoding="utf-8")
    for tone in ("ok", "warn", "bad"):
        assert ".mini.tone-%s {" % tone in css, f"tone-{tone} has no colour"
        assert "var(--%s)" % tone in css.split(".mini.tone-%s {" % tone)[1][:200], (
            f"tone-{tone} does not use the palette this stylesheet already has")


def test_every_table_carries_its_own_level_range_on_the_phone():
    """The knob that hid a whole table from the front-end that could not reach it (#2740).

    Measured live: «Шахты» held 381 mines and drew 0, because that page's own «уровень от»
    was 10 and a seasonal warzone's mines are all below it. The window has the two boxes;
    the card had neither. That is the shape #2010 and #2024 already named twice — a knob
    only Tk can move is a knob nobody can move — and it reads on the phone as «ничего не
    нашли», which is the one thing a page must never say untruthfully.
    """
    text = _TAB.read_text(encoding="utf-8")
    pages = ("self.alliance", "self.ghost", "self.ghost_allies", "self.ghost_map",
             "self.mines", "self.monsters", "self.trains", "self.trucks")
    for page in pages:
        assert "self._grid_level_fields(%s)" % page in text, (
            f"{page} draws no level range on its card")
    # …and a press on either box reaches the page's own variable, so the two front-ends
    # hold ONE value.
    assert "def _grid_level_write(self, key: str, value)" in text
    assert 'key != "%s%s" % (page.CONFIG_KEY, suffix)' in text
    assert "moved = self._grid_level_write(key, args.get(\"value\"))" in text, (
        "nothing routes the press to the page's box")


def test_the_chip_survives_leaving_the_page_and_is_held_in_ONE_place():
    """«При смене вкладки фильтры должны сохраняться» — and without a second copy."""
    text = _SCREEN.read_text(encoding="utf-8")
    assert "const chipHeld = new Map<string, string>()" in text, (
        "the chip is back to useState, so it is forgotten when the screen changes")
    assert "chipHeld.set(chipKey, id)" in text, "a press does not reach the one place"
    assert "chipHeld.get(chipKey)" in text, "the card does not read it back"
    # …and nothing is sent to the panel about it: which chip a thumb pressed is screen
    # state for this session, not an account setting.
    held = text[text.index("const chipKey ="):text.index("const filters = card.filters")]
    for sent in ("press(", "post(", "/api/"):
        assert sent not in held, f"the chip is being sent to the panel: {sent}"


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001 — a test runner
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"ok {name}")
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(1 if failed else 0)
