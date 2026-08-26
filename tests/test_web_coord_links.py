r"""EVERY COORDINATE THE PHONE SHOWS IS A PLACE TO GO (#1982).

The person's rule: «любые координаты должны быть кликабельны и приводить к переходу на
них в игре». The window has had this since it had a log — a coordinate in a line is a
link (`panel/runtime/log_view.py`) — and the phone drew the same strings as text.

WHAT IS PINNED HERE. The marking, which is the half that could go quietly wrong: it runs
on the panel side, off the ONE parser this repository has (`tools/lib/coords.py`), so the
browser never decides what a coordinate is. In particular a `0/3` loot count and a bare
comma pair are NOT places, and a string with nothing in it is left completely alone —
otherwise every payload would grow a field per line for nothing.

No game, no panel, no browser:

    python3 tests/test_web_coord_links.py
"""
from __future__ import annotations

TIER = "pure"

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.web import coordlinks  # noqa: E402


# --- the marking ------------------------------------------------------------
def test_a_canonical_coordinate_becomes_one_place_and_nothing_else():
    said = coordlinks.parts("#935 X:961 Y:399")
    assert said == [{"c": {"x": 961, "y": 399, "server": 935,
                           "text": "#935 X:961 Y:399"}}], said


def test_the_words_around_it_survive_in_order():
    said = coordlinks.parts("клад @[512,640|300] рядом")
    assert [list(p)[0] for p in said] == ["t", "c", "t"], said
    assert said[0]["t"] == "клад "
    assert said[2]["t"] == " рядом"
    assert said[1]["c"]["server"] == 300


def test_a_coordinate_with_no_server_says_so_with_a_zero():
    """Zero means «wherever the client is looking» — the recipe's own ELSE branch."""
    said = coordlinks.parts("X:512 Y:640")
    assert said[0]["c"]["server"] == 0, said


def test_a_loot_count_is_not_a_place():
    assert coordlinks.parts("Ограблено 0/3 · Сверено 58 мин назад") is None


def test_prose_costs_nothing_at_all():
    """`None` is what keeps the payload the size it was: the caller adds no field."""
    assert coordlinks.parts("сервер отвечает — всё работает") is None
    assert coordlinks.parts("") is None
    assert coordlinks.parts(None) is None


# --- where it is applied ----------------------------------------------------
def test_a_screen_is_marked_everywhere_a_person_can_read_one():
    view = {
        "cards": [{
            "head": "рядом с #935 X:100 Y:200",
            "rows": [{"label": "some.key", "value": "#935 X:1 Y:2"},
                     {"label": "some.key", "value": "нечего показать"}],
            "items": [{"text": "#955 X:961 Y:399",
                       "detail": "у X:5 Y:6",
                       "note": "ничего",
                       "facts": [{"label": "col.level", "value": "⭐×7"},
                                 {"label": "col.where", "value": "@[7,8|955]"}]}],
        }],
    }
    marked = coordlinks.mark_screen(view)
    card = marked["cards"][0]
    assert card["head_parts"][1]["c"]["x"] == 100
    assert card["rows"][0]["value_parts"][0]["c"]["y"] == 2
    assert "value_parts" not in card["rows"][1], "prose grew a field"
    item = card["items"][0]
    assert item["text_parts"][0]["c"]["server"] == 955
    assert item["detail_parts"][1]["c"]["x"] == 5
    assert "note_parts" not in item
    assert "value_parts" not in item["facts"][0], "a star is not a coordinate"
    assert item["facts"][1]["value_parts"][0]["c"]["server"] == 955


def test_a_log_line_is_marked_the_same_way():
    row = coordlinks.mark_line({"n": 7, "text": "стяг на #935 X:1 Y:2", "sev": ""})
    assert row["n"] == 7 and row["text_parts"][1]["c"]["x"] == 1


def test_a_label_is_never_parsed():
    """A locale key is not prose: `secrettasks.col.level` holds no places."""
    view = {"cards": [{"title": "secrettasks.col.level",
                       "rows": [{"label": "a.key.1/2", "value": "нет"}]}]}
    card = coordlinks.mark_screen(view)["cards"][0]
    assert "title_parts" not in card
    assert "label_parts" not in card["rows"][0]


# --- the ability it presses -------------------------------------------------
def test_the_press_plays_a_recipe_and_the_recipe_takes_the_place():
    """A press is a press: the phone plays `goto_coord`, it does not write Lua."""
    recipe = (_REPO / "src" / "lastwar_bot" / "actions" / "goto_coord.md").read_text("utf-8")
    for wanted in ("ARGS x", "ARGS y", "ARGS server", "IF server > 0",
                   "JUMP {x}, {y}, {server}", "JUMP {x}, {y}"):
        assert wanted in recipe, wanted
    ui = (_REPO / "panel" / "web" / "app" / "src" / "ui" / "Coord.tsx").read_text("utf-8")
    assert "'/api/actions/run'" in ui and "goto_coord" in ui, "the phone presses something else"
    assert "confirm(" not in ui, "a jump spends nothing and must not ask"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
