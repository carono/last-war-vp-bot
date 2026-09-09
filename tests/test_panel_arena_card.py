r"""The arena card says WHICH arena is running and how the account stands in it (#2688).

The person asked for it in those words — «пусть в карточке будет написано, какая сейчас
арена активна и счет нужен» — and the ways it can be wrong are all versions of one thing:

* **the card must not ask the game.** `CLAUDE.md`, «Read once, then LISTEN»: the line is
  read out of `panel/runtime/arena_live.py`, which reads once when the client gets into
  the game and then only at a moment the state is KNOWN to have moved;
* **and there is no clock behind that.** The arena announces nothing, so the next reading
  is booked for the event's own end or the day's reset — a MOMENT, never an interval, and
  never a «Обновить»;
* **the two arenas do not count the same thing.** The 3v3 challenge's day is counted in
  wins and the storm arena's in battles, so neither is drawn as the other;
* **and a field the game would not answer is a dash**, never a zero.

No Tk, no game, no network::

    python3 tests/test_panel_arena_card.py
"""
from __future__ import annotations

TIER = "offline"        # see tools/run_tests.py

import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import arena_live                  # noqa: E402
from panel.runtime import errand_stats as statsmod    # noqa: E402

ACTIONS = _REPO / "src" / "lastwar_bot" / "actions"

STORM = ("which=storm open=1 score=1039 rank=358 done=5 need=5 left=5 chest=1 "
         "until=379000")
THREE = ("which=3v3 open=1 score=967 rank=430 done=- need=- left=24 chest=- "
         "until=470692")
NONE = "which=none open=0 score=- rank=- done=- need=- left=- chest=- until=-"


class _Store:
    def __init__(self, blobs=None) -> None:
        self.blobs = dict(blobs or {})

    def blob_get(self, name):
        return self.blobs.get(name)

    def blob_set(self, name, value) -> None:
        self.blobs[name] = value


class _Timer:
    def __init__(self, name, args) -> None:
        self.name, self.args = name, args


class _Schedule:
    def __init__(self, timers=()) -> None:
        self.timer_catalogue = list(timers)


class _Day:
    def __init__(self, after_sec) -> None:
        self._after = after_sec

    def next_reset_epoch(self, when):
        return float(when) + self._after


class _Tick:
    def __init__(self) -> None:
        self.armed: dict = {}

    def arm(self, name, delay_ms, func) -> None:
        self.armed[name] = int(delay_ms)

    def disarm(self, name) -> None:
        self.armed.pop(name, None)


class _Rt:
    """Just enough runtime, and both doors a card must never open."""

    def __init__(self, line=None, at=None, day_in=9 * 3600.0, wins=5) -> None:
        blobs = {}
        if line is not None:
            blobs[arena_live.BLOB] = {arena_live.VARIABLE: line,
                                      "at": time.time() - 4 if at is None else at}
        self.store = _Store(blobs)
        self.schedule = _Schedule([_Timer("arena_3v3_battles", {"wins": wins})])
        self.day = _Day(day_in)
        self.tick = _Tick()

    def play_async(self, *a, **k):
        raise AssertionError("the card must never play a scenario")

    def play(self, *a, **k):
        raise AssertionError("the card must never play a scenario")


# ---------------------------------------------------------------------------
# the reading
# ---------------------------------------------------------------------------
def test_the_scenario_exists_and_answers_in_one_variable():
    text = (ACTIONS / f"{arena_live.ACTION}.md").read_text(encoding="utf-8")
    assert f"INTO {arena_live.VARIABLE}\n" in text, (
        "the watch reads a variable the scenario does not leave behind")
    assert "\nSHARE\n" in text, "a reading touches no window"
    for word in ("TAP ", "CLICK", "PRESS ", "JUMP "):
        assert word not in text, f"a READ must not {word.strip()} anything"


def test_a_dash_is_not_a_zero():
    fields = arena_live.parse(THREE)
    assert fields["which"] == "3v3" and fields["left"] == 24
    assert "done" not in fields and "need" not in fields, (
        "«the game would not say» must not arrive as a number")
    assert arena_live.parse("")  == {}


def test_the_two_arenas_are_not_drawn_as_each_other():
    storm = statsmod.of(_Rt(STORM), "arena_3v3_battles")
    assert storm["key"] == "timers.stat.arena.storm", storm
    assert storm["fmt"]["done"] == 5 and storm["fmt"]["need"] == 5, storm
    assert storm["fmt"]["score"] == 1039 and storm["fmt"]["rank"] == 358, storm
    three = statsmod.of(_Rt(THREE), "arena_3v3_battles")
    assert three["key"] == "timers.stat.arena.3v3", three
    # …and the 3v3's target is the ERRAND's own argument, because the server carries none
    assert three["fmt"]["need"] == 5 and three["fmt"]["done"] == "—", three
    assert statsmod.of(_Rt(THREE, wins=3), "arena_3v3_battles")["fmt"]["need"] == 3


def test_a_shut_building_says_so_and_an_unread_one_does_not_guess():
    shut = statsmod.of(_Rt(NONE), "arena_3v3_battles")
    assert shut["key"] == "timers.stat.arena.closed", shut
    blank = statsmod.of(_Rt(None), "arena_3v3_battles")
    assert blank is None or blank["key"] != "timers.stat.arena.closed", (
        "a reading nobody has taken must never be drawn as «the arena is shut»")


def test_the_line_carries_its_age():
    stat = statsmod.of(_Rt(STORM, at=time.time() - 600), "arena_3v3_battles")
    assert 590 < stat["age"] < 700, stat


def test_every_word_of_it_is_a_key_in_all_eleven_locales():
    keys = ("timers.stat.arena.closed", "timers.stat.arena.storm",
            "timers.stat.arena.3v3")
    for path in sorted((_REPO / "panel" / "locales").glob("*.json")):
        words = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in words, f"{path.name} is missing {key}"


# ---------------------------------------------------------------------------
# …and nothing behind it is a clock
# ---------------------------------------------------------------------------
def test_the_next_reading_is_booked_for_a_moment_and_not_an_interval():
    """The event's end, or the day's reset — whichever is nearer, and nothing else."""
    rt = _Rt(day_in=9 * 3600.0)
    watch = arena_live.ArenaWatch(rt)
    watch._book_next(arena_live.parse(STORM))         # until=379000, reset in 9 h
    assert rt.tick.armed[arena_live.CHAIN_NEXT] == int(arena_live.FURTHEST_SEC * 1000)
    rt = _Rt(day_in=1200.0)
    watch = arena_live.ArenaWatch(rt)
    watch._book_next(arena_live.parse(STORM))         # the reset is the nearer one now
    assert rt.tick.armed[arena_live.CHAIN_NEXT] == int((1200.0 + 5.0) * 1000)


def test_an_event_that_has_just_closed_cannot_book_a_reading_a_second_later():
    rt = _Rt(day_in=1.0)
    arena_live.ArenaWatch(rt)._book_next({"until": 1})
    assert rt.tick.armed[arena_live.CHAIN_NEXT] == int(arena_live.SOONEST_SEC * 1000)


def test_a_reading_that_said_nothing_books_nothing():
    rt = _Rt()
    rt.day = None                                     # …and no day boundary either
    arena_live.ArenaWatch(rt)._book_next({})
    assert arena_live.CHAIN_NEXT not in rt.tick.armed


def test_the_module_holds_no_clock_of_its_own():
    source = (_REPO / "panel" / "runtime" / "arena_live.py").read_text(encoding="utf-8")
    for forbidden in ("Timer(", "sleep(", "while True"):
        assert forbidden not in source, f"a watch must not {forbidden}"


def test_the_watch_is_started_by_the_runtime_and_not_by_a_page():
    host = (_REPO / "panel" / "runtime" / "host.py").read_text(encoding="utf-8")
    assert "self.arena.start()" in host, "nothing starts the arena's ear"
    assert "from .arena_live import ArenaWatch" in host


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
