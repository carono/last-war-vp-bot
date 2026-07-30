r"""Per-monster-type daily caps on rally auto-join — the limits and the day's count.

`panel.rally_limits` is where a rally auto-join decides whether a type is still under
its daily cap, and where the count of joins is kept and rolled over at midnight. Two
things must not go wrong: a `0` cap means unlimited (not "join zero"), and the count
is a per-DAY budget that resets on a new day rather than a total that grows forever.
Both are pinned here, plus the file round-trips (a hand-edited cap is honoured, junk
is dropped, a new built-in type is folded into an old profile's file).

No Tk, no game, and the day is an argument — so this runs anywhere::

    python3 tests/test_panel_rally_limits.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from panel import rally_limits as rl  # noqa: E402

DAY1 = "2026-07-30"
DAY2 = "2026-07-31"


# -- limits -----------------------------------------------------------------
def test_zero_is_unlimited_not_zero():
    limits = rl.RallyLimits({"zombie_invasion": 0, "monster": 2})
    counts = rl.RallyCounts(DAY1, {"zombie_invasion": 999, "monster": 0})
    # 0 cap: always allowed, however many were joined.
    assert counts.allowed("zombie_invasion", limits, today=DAY1) is True
    # a real cap: allowed until the count reaches it.
    assert counts.allowed("monster", limits, today=DAY1) is True


def test_a_cap_holds_at_its_limit():
    limits = rl.RallyLimits({"monster": 2})
    counts = rl.RallyCounts(DAY1, {"monster": 1})
    assert counts.allowed("monster", limits, today=DAY1) is True
    counts = counts.record("monster", today=DAY1)          # now 2
    assert counts.count_for("monster") == 2
    assert counts.allowed("monster", limits, today=DAY1) is False


def test_a_type_with_no_cap_entry_is_unlimited():
    limits = rl.RallyLimits({"monster": 1})
    counts = rl.RallyCounts(DAY1, {"boss": 500})
    # 'boss' is not in the limits file → limit_for is 0 → unlimited.
    assert limits.limit_for("boss") == 0
    assert counts.allowed("boss", limits, today=DAY1) is True


def test_negative_and_junk_caps_coerce():
    limits = rl.RallyLimits({"monster": -5, "x": "nope", "y": 3.9})
    assert limits.limit_for("monster") == 0                # negative → 0 (unlimited)
    assert limits.limit_for("x") == 0                      # unreadable dropped → 0
    assert limits.limit_for("y") == 3                      # 3.9 → 3


def test_with_limit_writes_one_type_only():
    limits = rl.default_limits().with_limit("monster", 5)
    assert limits.limit_for("monster") == 5
    assert limits.limit_for("zombie_invasion") == 0        # untouched


# -- counts: the day roll ---------------------------------------------------
def test_the_count_resets_on_a_new_day():
    counts = rl.RallyCounts(DAY1, {"monster": 7})
    assert counts.count_for("monster") == 7
    rolled = counts.rolled(today=DAY2)
    assert rolled.date == DAY2 and rolled.count_for("monster") == 0
    # allowed/record roll on their own too:
    limits = rl.RallyLimits({"monster": 3})
    assert counts.allowed("monster", limits, today=DAY2) is True   # yesterday's 7 is gone
    recorded = counts.record("monster", today=DAY2)
    assert recorded.date == DAY2 and recorded.count_for("monster") == 1


# -- files ------------------------------------------------------------------
def test_limits_file_is_seeded_then_round_trips():
    tmp = Path(tempfile.mkdtemp())
    path = str(tmp / "rally_limits.json")
    seeded = rl.load_limits(path)                           # writes the built-ins
    assert seeded.as_dict() == rl.DEFAULT_RALLY_LIMITS
    assert Path(path).exists()
    # a hand edit is honoured on the next read.
    Path(path).write_text(json.dumps({"monster": 9}), encoding="utf-8")
    back = rl.load_limits(path)
    assert back.limit_for("monster") == 9
    # …and a NEW built-in type is folded into the old file rather than lost.
    assert back.limit_for("zombie_invasion") == 0


def test_counts_file_round_trips_and_rolls_on_load():
    tmp = Path(tempfile.mkdtemp())
    path = str(tmp / "rally_counts.json")
    rl.save_counts(rl.RallyCounts(DAY1, {"monster": 4}), path)
    same_day = rl.load_counts(path, today=DAY1)
    assert same_day.count_for("monster") == 4
    next_day = rl.load_counts(path, today=DAY2)             # stale file → rolled empty
    assert next_day.date == DAY2 and next_day.count_for("monster") == 0


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
