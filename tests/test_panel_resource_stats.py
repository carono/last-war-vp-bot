r"""Daily tally of resources gained — the diff, the day roll, and the file.

`panel.resource_stats` turns a stream of balance readings into a day-keyed tally of
what went UP. Three things must hold: only INCREASES are counted (a spend, and the
first reading with no baseline, add nothing), a new day is a new row rather than a
reset (the history accumulates), and the file round-trips. All pinned here.

No Tk, no game, the day is an argument::

    python3 tests/test_panel_resource_stats.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from panel import resource_stats as rs  # noqa: E402

DAY1 = "2026-07-30"
DAY2 = "2026-07-31"


# -- the diff ---------------------------------------------------------------
def test_only_increases_are_counted():
    last = {"food": 100, "wood": 100, "gold": 100}
    cur = {"food": 150, "wood": 80, "gold": 100}          # food up, wood down, gold flat
    assert rs.positive_deltas(cur, last) == {"food": 50}


def test_no_baseline_means_no_gain():
    # A resource missing from `last` (first reading) is not counted as gained.
    assert rs.positive_deltas({"food": 999}, {}) == {}
    assert rs.positive_deltas({"food": 999}, {"wood": 1}) == {}


def test_junk_values_are_ignored():
    assert rs.positive_deltas({"food": "x"}, {"food": 1}) == {}


# -- the tally + day roll ---------------------------------------------------
def test_gains_accumulate_within_a_day():
    stats = rs.ResourceStats({})
    stats = stats.add({"food": 100}, today=DAY1)
    stats = stats.add({"food": 50, "gold": 5}, today=DAY1)
    assert stats.on(DAY1) == {"food": 150, "wood": 0, "metal": 0, "oil": 0, "gold": 5}


def test_a_new_day_is_a_new_row_history_kept():
    stats = rs.ResourceStats({}).add({"food": 100}, today=DAY1)
    stats = stats.add({"food": 30}, today=DAY2)
    assert stats.on(DAY1)["food"] == 100          # yesterday untouched
    assert stats.on(DAY2)["food"] == 30
    assert stats.dates() == [DAY2, DAY1]          # newest first


def test_empty_gains_change_nothing():
    stats = rs.ResourceStats({"2026-01-01": {"food": 5}})
    same = stats.add({}, today=DAY1)
    assert same is stats                          # a spend-only push is a no-op
    # a delta dict with only non-positive values is empty too
    assert stats.add({"food": 0, "wood": -3}, today=DAY1) is stats


def test_unknown_resource_keys_are_dropped():
    stats = rs.ResourceStats({}).add({"food": 10, "banana": 99}, today=DAY1)
    assert stats.on(DAY1)["food"] == 10
    assert "banana" not in stats.as_dict().get(DAY1, {})


# -- the file ---------------------------------------------------------------
def test_file_round_trips():
    tmp = Path(tempfile.mkdtemp())
    path = str(tmp / "resource_stats.json")
    rs.save_stats(rs.ResourceStats({}).add({"gold": 7}, today=DAY1), path)
    back = rs.load_stats(path)
    assert back.on(DAY1)["gold"] == 7
    # the file is the documented shape
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    assert raw[DAY1]["gold"] == 7


def test_a_missing_file_loads_empty():
    tmp = Path(tempfile.mkdtemp())
    stats = rs.load_stats(str(tmp / "nope.json"))
    assert stats.dates() == []


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
