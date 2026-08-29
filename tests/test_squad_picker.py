r"""The squad picker: the one control every «which squads» is drawn with (#2062).

What this pins is the CONTRACT the person asked for, not the pixels:

  * a field declares itself as one control (`kind = "squads"`) with a tile per slot, so a
    site cannot go back to drawing its own row of boxes and stay in step;
  * the value is the slots that are ON, and it survives a round trip through whatever a
    front-end sends («1,3», `[1, 3]`, «3;1») — the whole list, never a diff;
  * a hero nobody can name draws NO face, and never a stand-in one — the rule the icon
    routes have kept since the monsters (`CLAUDE.md`);
  * the reading is asked for ONCE and never on a clock, which is the panel's rule for
    anything the game has no event for.

Needs neither Tk, a display nor a game.

    C:\Python312\python.exe tests\test_squad_picker.py
    python3 tests/test_squad_picker.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for extra in (str(_REPO), str(_REPO / "tools" / "lib")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from panel.runtime import squad_picker  # noqa: E402


class _Outcome:
    def __init__(self, raw):
        self.ok = True
        self.reason = ""
        self.ctx = type("Ctx", (), {"vars": {"squad_heroes": raw}})()


class _Actions:
    """Plays nothing: it counts, and hands back a canned reading."""

    def __init__(self, raw):
        self.raw, self.plays = raw, 0

    def play(self, name, *a, **kw):
        assert name == squad_picker.ACTION, name
        self.plays += 1
        return _Outcome(self.raw)


class _Bus:
    def __init__(self):
        self.said = []

    def publish(self, topic, payload):
        self.said.append((topic, payload))


class _Game:
    def ready(self, *a, **kw):
        return True


class _Squads:
    """`rt.squads`, holding one reading — the picker reads it and asks the game nothing."""

    class _State:
        ok = True

        @staticmethod
        def kind(index):
            return "home" if index == 1 else "marching"

    @staticmethod
    def latest():
        return _Squads._State()


class _RT:
    def __init__(self, raw=""):
        self.actions = _Actions(raw)
        self.bus = _Bus()
        self.game = _Game()
        self.squads = _Squads()


# Invented ids and stems, of the shape the game answers with — never a live reply
# (`CLAUDE.md`, «Not one identifier of a real account is written down»).
READING = ("squad=1 heroes=50001:Hero_One,50002:Hero_Two "
           "| squad=2 heroes=50003:Hero_Three "
           "| squad=3 heroes= "
           "| squad=4 heroes=1000000:")


def test_a_reading_is_parsed_into_slots_and_the_drone_is_not_a_hero():
    heroes = squad_picker.parse(READING)
    assert sorted(heroes) == [1, 2, 3, 4], heroes
    assert heroes[1] == [(50001, "Hero_One"), (50002, "Hero_Two")]
    assert heroes[3] == []
    # The drone slot carries no portrait and is not a hero (`docs/research/hero-icons.md`).
    assert heroes[4] == []


def test_junk_is_dropped_rather_than_guessed_at():
    assert squad_picker.parse("") == {}
    assert squad_picker.parse("stamina=101 max=120") == {}
    assert squad_picker.parse("squad=x heroes=1:a") == {}
    assert squad_picker.parse("squad=1 heroes=nonsense") == {1: []}


def test_whatever_a_front_end_sends_becomes_the_same_list():
    for sent in ("1,3", "3;1", " 1 , 3 ", [1, 3], ("3", "1"), {1, 3}):
        assert squad_picker.chosen_from(sent) == [1, 3], sent
    # A slot that does not exist is dropped, never clamped onto a neighbour.
    assert squad_picker.chosen_from("0,5,2") == [2]
    assert squad_picker.chosen_from(None) == []


def test_the_field_is_one_control_with_a_tile_per_squad():
    rt = _RT(READING)
    field = squad_picker.field(rt, "squads", "squads.title", [1, 3])
    assert field["kind"] == "squads" and field["key"] == "squads"
    assert field["value"] == "1,3"
    assert [tile["n"] for tile in field["squads"]] == [1, 2, 3, 4]
    assert [tile["on"] for tile in field["squads"]] == [True, False, True, False]
    # The caption comes off the reading the panel already had — no game read of its own.
    assert field["squads"][0]["state"] == "home"
    assert field["squads"][1]["state"] == "marching"


def test_one_squad_where_one_is_picked():
    rt = _RT(READING)
    field = squad_picker.field(rt, "golden_squad", "squads.title", [2], single=True)
    assert field["single"] is True and field["value"] == "2"
    # …and a page whose slots are not 1..4 says so rather than drawing a fourth tile.
    field = squad_picker.field(rt, "treasure_squad", "squads.title", [1],
                               single=True, squads=(1, 2, 3))
    assert [tile["n"] for tile in field["squads"]] == [1, 2, 3]


def test_only_the_first_hero_is_drawn_and_nobody_stands_in_for_him():
    """ONE face per tile, the game's own first, and no understudy (#2062).

    The person looked at three portraits crowded into a tile and asked for one: «оставляй
    спрайт первого героя, сейчас там мешанина». So a squad answers with at most one link,
    and when the hero in position 1 has no picture the answer is «no picture» rather than
    the hero standing behind him — a tile is read as «this is who leads that squad».
    """
    assert squad_picker.FACES == 1

    class _Named(dict):
        pass

    rt = _RT(READING)
    reader = squad_picker.reader(rt)
    reader.read()
    # Both heroes of squad 1 were read; the tile is offered at most one of them.
    assert reader.latest()[1] == [(50001, "Hero_One"), (50002, "Hero_Two")]
    assert len(reader.faces(1)) <= 1

    # The first hero has no picture, the second would have had one: the answer is neither.
    rt2 = _RT("squad=1 heroes=99999999:,50002:Hero_Two")
    reader2 = squad_picker.reader(rt2)
    reader2.read()
    assert reader2.faces(1) == []


def test_a_hero_nobody_can_name_draws_no_face():
    """No picture is the honest answer; a stand-in face is the forbidden one."""
    rt = _RT("squad=1 heroes=99999999:")
    reader = squad_picker.reader(rt)
    reader.read()
    assert reader.faces(1) == []


def test_the_reading_is_asked_for_once_and_never_on_a_clock():
    rt = _RT(READING)
    reader = squad_picker.reader(rt)
    reader.read()
    reader.read()
    assert rt.actions.plays == 2, "read() plays when it is called, and only then"
    # Drawing does not play anything once a reading has landed: a screen the phone polls
    # must not become a question at the game (`CLAUDE.md`, «Read once, then LISTEN»).
    before = rt.actions.plays
    for _ in range(5):
        squad_picker.field(rt, "squads", "squads.title", [1])
    assert rt.actions.plays == before
    # …and the reader has no poll of its own to start.
    assert not hasattr(reader, "start"), "a picker never arms a clock"


def _run() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:                              # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
