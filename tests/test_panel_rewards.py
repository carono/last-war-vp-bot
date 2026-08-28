r"""The book behind the reward-popup ear — task #2027.

The ear is in the client and is tested in a real Lua VM next door
(`tests/test_reward_popups.py`). This file is the panel's half: the drain line the recipe
prints, parsed into rows, attributed to whatever the panel was playing, and written into
this profile's own table.

What is pinned here:

  * the recipe's marker and the book's marker are the SAME word — the two are a wire
    format between a `.md` file and a `.py` one, and nothing else would notice a rename;
  * a drain line becomes rows, whatever tag and stamp the log put in front of it;
  * «за что» is the scenario the panel was playing, and an EMPTY field when it was
    playing nothing — never a guess;
  * an unknown reward window is said out loud once per name, because that row is the
    only one a person has to act on;
  * the rows land in the database, and one profile cannot see another's.

    C:\Python312\python.exe tests\test_panel_rewards.py
    python3 tests/test_panel_rewards.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "tools", ROOT / "tools" / "lib", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime.activity import Activity          # noqa: E402
from panel.runtime.rewards import MARK, RewardBook    # noqa: E402
from panel.runtime.store import Store                 # noqa: E402

RECIPE = ROOT / "src" / "lastwar_bot" / "actions" / "collect_reward_popups.md"

#: A drain exactly as the recipe prints it, through the log's own formatting.
LINE = ('2026-08-28 16:00:36 [timer]   LOG "reward_popups: '
        '1756402331000|reward|ShowCommonReward|101x2,205x7 ;; '
        '1756402331080|closed|UIGiftPackageRewardGet"')


class _Bus:
    """As much of the LogBus as the book uses: a tap, and lines to feed it."""

    def __init__(self) -> None:
        self.taps: list = []
        self.said: list = []

    def tap(self, func):
        self.taps.append(func)
        return lambda: self.taps.remove(func)

    def put(self, line: str) -> None:
        for func in list(self.taps):
            func(line)

    def say(self, tag: str, key: str, **fmt) -> None:
        self.said.append((tag, key, fmt))


def test_the_recipe_and_the_book_say_the_same_word() -> None:
    """The marker is a wire format between a `.md` and a `.py`."""
    text = RECIPE.read_text(encoding="utf-8")
    assert MARK in text, "the recipe no longer prints the marker the book listens for"
    assert " ;; " in text, "the recipe no longer joins its rows the way the book splits"
    print("ok  the recipe and the book agree on the marker")


def test_a_drain_line_becomes_rows() -> None:
    bus = _Bus()
    book = RewardBook(bus, say=bus.say)
    book.listen()
    bus.put(LINE)
    rows = book.recent(10)
    kinds = [r["kind"] for r in rows]
    assert kinds == ["reward", "closed"], rows
    assert rows[0]["source"] == "ShowCommonReward"
    assert rows[0]["items"] == "101x2,205x7"
    assert rows[1]["source"] == "UIGiftPackageRewardGet"
    # …and a line that is not a drain passes straight through.
    bus.put("2026-08-28 16:00:40 [timer] ничего интересного")
    assert len(book.recent(10)) == 2
    print("ok  a drain line becomes rows, and nothing else does")


def test_why_is_the_play_or_nothing_at_all() -> None:
    """«За что» is what the panel was playing — and «не знаю» when it was playing nothing."""
    bus, activity = _Bus(), Activity("sooperj")
    book = RewardBook(bus, activity=activity, say=bus.say)
    book.listen()
    bus.put(LINE)
    assert all(r["why"] == "" for r in book.recent(10)), "a guess was written down"
    with activity.step("activity.action", name="assist_secret_task"):
        bus.put(LINE)
    fresh = book.recent(2)
    assert all(r["why"] == "assist_secret_task" for r in fresh), fresh
    print("ok  «за что» is the play, and empty when there was none")


def test_an_unknown_window_is_said_once_per_name() -> None:
    bus = _Bus()
    book = RewardBook(bus, say=bus.say)
    book.listen()
    for _ in range(3):
        bus.put('[timer] LOG "reward_popups: 1|unknown|UIActGiftBoxRewardNew"')
    keys = [(k, f.get("window")) for _tag, k, f in bus.said]
    assert keys == [("rewards.unknown", "UIActGiftBoxRewardNew")], bus.said
    print("ok  an unknown reward window is said once, by name")


def test_rows_land_in_the_database_and_stay_in_their_profile() -> None:
    home = tempfile.mkdtemp()
    path = os.path.join(home, "panel.db")
    mine, theirs = Store(path, "sooperj"), Store(path, "casper")
    bus = _Bus()
    book = RewardBook(bus, store=mine, activity=None, say=bus.say)
    book.listen()
    bus.put(LINE)
    mine.flush()
    rows = mine.rewards_recent(10)
    assert [r["kind"] for r in rows] == ["closed", "reward"], rows
    assert theirs.rewards_recent(10) == [], "a row leaked into another account"
    assert mine.rewards_count(kind="closed") == 1
    # …and the book reads back out of the database rather than out of memory.
    assert book.recent(10)[0]["source"] in ("UIGiftPackageRewardGet", "ShowCommonReward")
    mine.close()
    theirs.close()
    print("ok  the rows are in the database, and one profile cannot see another's")


def test_pruning_forgets_only_the_old() -> None:
    home = tempfile.mkdtemp()
    store = Store(os.path.join(home, "panel.db"), "sooperj")
    now = int(time.time())
    store.rewards_add([{"at": 1, "seen_at": now - 400 * 24 * 3600, "kind": "reward",
                        "source": "old", "items": "", "why": ""},
                       {"at": 2, "seen_at": now, "kind": "reward",
                        "source": "new", "items": "", "why": ""}])
    store.flush()
    store.rewards_prune(now - 90 * 24 * 3600)
    store.flush()
    left = [r["source"] for r in store.rewards_recent(10)]
    assert left == ["new"], left
    store.close()
    print("ok  pruning forgets the old rows and keeps the rest")


def main() -> int:
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
    print("\nall reward-book checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
