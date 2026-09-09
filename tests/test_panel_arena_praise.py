r"""The free diamonds both arenas pay for a LIKE, and the card that shows them (#2689).

The person asked for them on the card that takes everything else the game gives away —
«в карточку магазин бесплатно добавь сбор ежедневных бесплатных алмазов на арене шторма
и 3 на 3, для этого нужно лайкать 3 раза топового игрока в рейтинге» — and the ways this
can be wrong are all versions of one thing:

* **the ability is a scenario**, not a routine in the panel (`CLAUDE.md`);
* **it spends nothing and never presses blind**: the gate is the server's own count of
  likes left, and a day with none left sends nothing at all;
* **the card must not ask the game**: the line comes off the reading
  `panel/runtime/arena_live.py` already keeps, and it carries its own age;
* **the reading moves on an EVENT, never on a clock** — the answer to a like;
* **both front-ends get the knob**, because it lives in the errand's own arguments.

And the storm arena's own repair goes with it: a list that has gone stale is answered by
asking for it again, not by ending the run.

No Tk, no game, no network::

    python3 tests/test_panel_arena_praise.py
"""
from __future__ import annotations

TIER = "offline"        # see tools/run_tests.py

import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import arena_live                  # noqa: E402
from panel.runtime import errand_args                 # noqa: E402
from panel.runtime import errand_stats as statsmod    # noqa: E402

ACTIONS = _REPO / "src" / "lastwar_bot" / "actions"
PRAISE = (ACTIONS / "praise_arenas.md").read_text(encoding="utf-8")
SHOP = (ACTIONS / "collect_shop_freebies.md").read_text(encoding="utf-8")
STORM_FIGHT = (ACTIONS / "storm_arena_battles.md").read_text(encoding="utf-8")

#: A reading with likes left on both arenas, and one with the day's already given.
LEFT = ("which=storm open=1 score=1039 rank=358 done=5 need=5 left=5 chest=1 "
        "until=379000 like_storm=3 like_three=2")
DONE = ("which=storm open=1 score=1039 rank=358 done=5 need=5 left=5 chest=1 "
        "until=379000 like_storm=0 like_three=0")
UNREAD = ("which=storm open=1 score=1039 rank=358 done=5 need=5 left=5 chest=1 "
          "until=379000 like_storm=- like_three=-")


class _Store:
    def __init__(self, blobs=None) -> None:
        self.blobs = dict(blobs or {})

    def blob_get(self, name):
        return self.blobs.get(name)

    def blob_set(self, name, value) -> None:
        self.blobs[name] = value


class _Rt:
    """Just enough runtime, and the door a card must never open."""

    def __init__(self, line=None) -> None:
        blobs = {}
        if line is not None:
            blobs[arena_live.BLOB] = {arena_live.VARIABLE: line, "at": time.time() - 4}
        self.store = _Store(blobs)
        self.schedule = type("_S", (), {"timer_catalogue": []})()

    def play_async(self, *a, **k):
        raise AssertionError("the card must never play a scenario")

    def play(self, *a, **k):
        raise AssertionError("the card must never play a scenario")


# ---------------------------------------------------------------------------
# the ability
# ---------------------------------------------------------------------------
def test_the_ability_is_one_scenario_and_it_opens_no_window():
    assert "\nSHARE\n" in PRAISE, "the likes are headless — nothing is tapped"
    for word in ("TAP ", "CLICK", "PRESS ", "JUMP ", "FIND "):
        assert word not in PRAISE, f"a like must not {word.strip()} anything"


def test_the_gate_is_the_servers_own_count_and_a_zero_sends_nothing():
    assert "remainPraise" in PRAISE, "the day's count is what decides"
    assert PRAISE.count("if left == 0 then return") == 2, (
        "each arena must leave without sending when the day's likes are given")


def test_nothing_here_can_spend():
    # The prose says «diamonds» because that is what a like PAYS OUT; what may not be
    # here is anything that could send a purchase or a priced re-roll.
    body = "\n".join(l for l in PRAISE.splitlines() if not l.startswith("#"))
    for word in ("buy", "Buy", "refresh_price", "NewArenaRefresh", "Refresh"):
        assert word not in body, f"a like costs nothing — {word} has no business here"


def test_the_ear_is_installed_under_its_own_name():
    # The two readings guard their hooks with an `armed` flag, so a wrapper hung on one of
    # their names is silently NOT installed and the run measures nothing (#2688).
    assert "__lw_praise" in PRAISE
    assert "__lw_a3v3" not in PRAISE and "__lw_storm" not in PRAISE


def test_the_shop_errand_plays_it_behind_its_own_tick():
    assert "ARGS arena_praise = 1" in SHOP, "a new ability ships switched on"
    assert "IF arena_praise == 1\n    CALL praise_arenas" in SHOP, (
        "the card's routine must PLAY the ability, never re-implement it")


def test_the_knob_is_in_the_one_place_errand_arguments_live():
    keys = [str(opt.get("key")) for opt in errand_args.SPEC["collect_shop_freebies"]]
    assert "arena_praise" in keys, "the gear on «Таймеры» must offer it"
    page = (_REPO / "panel" / "tabs" / "shop.py").read_text(encoding="utf-8")
    knobs = page.split("KNOBS = (")[1].split(")")[0]
    assert "arena_praise" in knobs, "…and the page draws the same one"


# ---------------------------------------------------------------------------
# the card
# ---------------------------------------------------------------------------
def test_the_card_says_what_is_left_on_both_arenas_and_how_old_it_is():
    line = statsmod.of(_Rt(LEFT), "collect_shop_freebies")
    assert line["key"] == "timers.stat.shop.likes", line
    assert line["fmt"] == {"storm": 3, "three": 2}, line
    assert line["age"] is not None and line["age"] >= 0, line


def test_a_day_whose_likes_are_given_says_so_rather_than_drawing_zeros():
    line = statsmod.of(_Rt(DONE), "collect_shop_freebies")
    assert line["key"] == "timers.stat.shop.likes_done", line


def test_an_unread_count_is_never_a_zero():
    fields = arena_live.parse(UNREAD)
    assert "like_storm" not in fields and "like_three" not in fields
    line = statsmod.of(_Rt(UNREAD), "collect_shop_freebies")
    assert line["key"] != "timers.stat.shop.likes_done", (
        "«nobody said» must not be reported as «all given»")


def test_the_reading_carries_the_two_counts():
    text = (ACTIONS / f"{arena_live.ACTION}.md").read_text(encoding="utf-8")
    assert "like_storm=" in text and "like_three=" in text


def test_the_reading_listens_for_the_answer_to_a_like_and_never_polls():
    src = (_REPO / "panel" / "runtime" / "arena_live.py").read_text(encoding="utf-8")
    assert 'PRAISE = "arena.praise"' in src, "the one event this reading can hear"
    assert "self._rt.wire.subscribe(PRAISE" in src, "…and it has to be subscribed to"
    assert "_on_praise" in src


def test_every_word_of_it_is_a_locale_key_in_every_shipped_locale():
    import json

    keys = ("shop.arena_praise", "shop.arena_praise.hint",
            "timers.stat.shop.likes", "timers.stat.shop.likes_done")
    locales = sorted((_REPO / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11, locales
    for path in locales:
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in table, f"{path.name} has no {key}"
            assert table[key].strip(), f"{path.name}: {key} is empty"


# ---------------------------------------------------------------------------
# the storm arena's stale list
# ---------------------------------------------------------------------------
def test_a_stale_opponent_list_is_re_asked_and_does_not_end_the_run():
    assert "tips_38" in STORM_FIGHT and "battlelist" in STORM_FIGHT, (
        "the refusal that means «the list moved» has to be recognised")
    assert "B.relist = 1" in STORM_FIGHT, "…and answered by asking for the list again"
    assert "tries < 3" in STORM_FIGHT, "…a bounded number of times"
    stale = STORM_FIGHT.split("local stale =")[1].split("end")[0]
    assert "B.strikes" not in stale, (
        "a battle that cost nothing must not count towards the two that stop a run")


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
