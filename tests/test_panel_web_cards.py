r"""One card for every errand, and no second format to add (#2407).

The person's words: «Все карточки в таймерах и триггерах должны быть по новому формату,
если нет картинки, вставляем заглушку, но элементы управления в вид карточек должен быть
единым, больше старый формат не добавляем».

There were three drawings on «Таймеры» before this: a cover in full colour, the game's
own sprite spread over the card under a darkening wash, and — for a row this machine had
neither of — a plain card with no picture, a different height and no ground under its
words. Which one a card got was decided by which files a disk happened to hold, so the
page looked different on two machines running the same commit.

What this file holds is the *rule* rather than the appearance:

* every card on the page comes out of the ONE component (`ui/ErrandCard.tsx`) — a screen
  that spells `<div className="item …">` for itself is the way the second format comes
  back, and it comes back looking finished;
* an errand card is drawn in the cover shape whether or not there is a picture — the
  shape is the format, and it is not asked of the disk;
* no picture means the PLACEHOLDER, not emptiness, and the placeholder is one mark drawn
  by the stylesheet rather than a file that has to exist;
* the panel sends one kind of picture — the fallback on the game's sprite is gone from
  the payload, from the runtime door and from the route.

    C:\Python312\python.exe tests\test_panel_web_cards.py
"""
from __future__ import annotations

TIER = "offline"        # source text only — see tools/run_tests.py

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_APP = _REPO / "panel" / "web" / "app" / "src"


def _read(*parts: str) -> str:
    return (_APP.joinpath(*parts)).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# one component
# ---------------------------------------------------------------------------
def test_the_errands_page_draws_no_card_of_its_own():
    """«Таймеры» hands three kinds of row to one card and spells none itself."""
    view = _read("views", "TimersView.tsx")
    assert "<ErrandCard" in view, "the page must draw the shared card"
    assert view.count("<ErrandCard") == 1, (
        "a timer, a listener and a standing order are ONE block — a second <ErrandCard> "
        "in this file is a second card to keep in step")
    # The way a second format actually arrives: markup written beside the component.
    for spelling in ('className="item', "className={'item", 'className={"item'):
        assert spelling not in view, (
            "a card spelled out in the view rather than taken from ui/ErrandCard.tsx: " +
            spelling)


def test_every_errand_card_is_the_cover_shape_whatever_is_on_the_disk():
    """The shape is the format, so it is never asked whether a picture exists."""
    view = _read("views", "TimersView.tsx")
    assert "\n      cover\n" in view, (
        "the block must hand `cover` to the card unconditionally")
    assert "cover={" not in view, (
        "a card whose shape depends on a value is the old two-drawings arrangement")
    # …and the row no longer carries the flag at all, either way round.
    types = _read("types.ts")
    assert "cover?: boolean" not in types, (
        "TimerRow/TriggerRow/OrderRow must not carry a `cover` flag any more")


# ---------------------------------------------------------------------------
# no picture is not emptiness
# ---------------------------------------------------------------------------
def test_a_card_with_no_picture_wears_the_placeholder():
    """No cover on this machine → the one mark, never a blank slab."""
    card = _read("ui", "ErrandCard.tsx")
    assert "const blank = Boolean(cover) && !icon" in card, (
        "the card must decide the placeholder for itself, not leave it to a caller")
    assert "(blank ? ' blank' : '')" in card, "the placeholder needs its own class"
    assert "(icon || blank ? ' art' : '')" in card, (
        "a placeholder card must still get the layer the picture is painted on")

    css = _read("app.css")
    assert ".item.errand.cover.blank::before {" in css, "the placeholder is undrawn"
    body = css.split(".item.errand.cover.blank::before {", 1)[1].split("}", 1)[0]
    assert "background-image: var(--errand-blank)" in body, (
        "the placeholder must draw the one mark")
    assert "background-color:" in body, "the placeholder needs a ground under the words"
    # ONE MARK, and it is in the stylesheet rather than on the disk: a machine that has
    # never run the art generator has no file to serve, and a card asking for one would
    # draw a broken frame on every poll of the page.
    assert css.count("--errand-blank:") == 2, (
        "one placeholder per palette — dark and light — and no third")
    assert "url(\"data:image/svg+xml," in css.split("--errand-blank:", 1)[1], (
        "the placeholder must be drawn by the stylesheet, never fetched")


def test_the_placeholder_is_not_somebody_elses_picture():
    """It is a frame, not an ability's icon borrowed because it looked close enough."""
    css = _read("app.css")
    mark = css.split("--errand-blank:", 1)[1].split(";", 1)[0]
    assert "/api/" not in mark, "the placeholder must not reach for a picture route"
    assert "errandicon" not in mark and "heroicon" not in mark


# ---------------------------------------------------------------------------
# one kind of picture, all the way down
# ---------------------------------------------------------------------------
def test_the_panel_sends_one_kind_of_picture_and_no_fallback():
    api = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert api.count("artmod.cover_for(") == 3, "timers, triggers and the orders"
    assert "artmod.name_for(" not in api, (
        "the sprite fallback is the old format — a row with no cover sends nothing")

    art = (_REPO / "panel" / "runtime" / "errand_art.py").read_text(encoding="utf-8")
    assert "def name_for(" not in art, (
        "the door onto the sprite is gone with the drawing that used it")
    assert "def cover_for(" in art and "def cover_focus(" in art

    server = (_REPO / "panel" / "web" / "server.py").read_text(encoding="utf-8")
    route = server.split("def _errandicon", 1)[1].split("def _monstericon", 1)[0]
    assert "cover_named(" in route, "the route serves the covers"
    assert "file_named(" not in route, (
        "the route must not serve the sprite an errand card no longer draws")


# ---------------------------------------------------------------------------
# the two signs of the foot (#2579)
# ---------------------------------------------------------------------------
def test_the_gear_stands_beside_the_run_sign_and_not_in_the_head():
    """«кнопку шестеренку перемести к кнопке запуска, выровняй по правому краю».

    Both signs travel as `acts`, which the card draws in the FOOT; the head keeps the
    «i» and the switch. What this pins is the thing that would silently undo it: a gear
    handed in as `infoNode` (the head corner) instead.
    """
    view = _read("views", "TimersView.tsx")
    gear = view.split("function useGear", 1)[1].split("\n}", 1)[0]
    assert 'className="go icon"' in gear, "the gear is a sign, drawn like its neighbour"
    assert "acts={[gear.button, run].filter(Boolean)}" in view, (
        "the gear must travel in the foot row, beside «▶»")
    assert "infoNode={gear" not in view, "…and never into the head corner"
    card = _read("ui", "ErrandCard.tsx")
    # The foot is where `acts` land on a cover card, and the reading takes what is left
    # of the line — which is what puts the signs against the right edge.
    assert "{cover ? <Reading stat={stat} queued={queued} /> : null}\n            {row}" \
        in card, "the reading leads the foot row and the signs follow it"


def test_the_signs_are_one_control_and_cost_no_height():
    """Same size, same shape, a visible press — and never a rule keyed on a cursor."""
    css = _read("app.css")
    body = css.split(".item.errand .errand-acts .go.icon {", 1)[1].split("}", 1)[0]
    assert "border-radius: 999px" in body, "the signs are discs"
    assert "width: var(--tap)" in body and "height: var(--tap)" in body, (
        "a sign is the tap target it always was — the card's height depends on it")
    assert ":hover" not in css, "a phone has no cursor"
    assert ".item.errand .errand-acts .go.icon:active {" in css, (
        "a press a thumb covers must still be visible")
    # THE PRIMARY ONE IS MARKED BY A CLASS, not by where it sits: a card with no knobs
    # has one sign and it is «▶».
    assert ".item.errand .errand-acts .go.icon.run {" in css
    view = _read("views", "TimersView.tsx")
    assert "'go icon run'" in view


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
