r"""The account dashboard and the map sweep — the two decisions behind the strip
and the wrist, both without a display, a daemon or a client.

Neither module touches Tk or the game, which is the point: what is easy to get
quietly wrong here is *the geometry* (a sweep that misses a band of tiles finds
nothing and says nothing) and *the reading* (a budget that could not be read must
never look like a budget of zero). Both are plain functions, so both are tested.

    C:\Python312\python.exe tests\test_panel_dashboard.py
    python3 tests/test_panel_dashboard.py            # no tkinter needed
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import dashboard as dashmod          # noqa: E402
from panel import mapsweep as sweepmod          # noqa: E402


# -- the dashboard ---------------------------------------------------------

def test_every_reading_is_in_the_one_chunk():
    """One round trip for the whole strip, each reading in its own pcall.

    A call into the VM costs ~0.15 s and the loop inside it is free, so thirteen
    readings must not be thirteen calls. And a manager that is not loaded yet
    (the hospital before the base screen, ghost recon outside its event days)
    must cost that one reading rather than the strip.
    """
    chunk = dashmod.build_chunk()
    assert chunk.count("P('") == len(dashmod.READINGS), chunk.count("P('")
    # One guard, applied to every reading — not one pcall per reading written out,
    # and not none. (Some of the expressions carry a pcall of their own, so counting
    # the word would tell us nothing; the helper is what matters.)
    assert chunk.count("local function P(k, f) local ok, v = pcall(f)") == 1, chunk[:200]
    assert chunk.count("Debug.LogError") == 1, "more than one answer line"
    for reading in dashmod.READINGS:
        assert f"P('{reading.key}'" in chunk, reading.key


def test_a_reading_that_failed_is_not_a_reading_of_zero():
    """`?` and `0` are opposite news and must never collapse into one."""
    line = ("DASH secret_steals=3 ghost_steals=0 donate=? help_waiting=4 "
            "wounded=681 healed=1 visitors=2 visitor_gifts=0 skills=3 "
            "rally_joins=0 treasures=0 help_queues=1 free_queues=2")
    values = dashmod.parse(["noise before", line, "noise after"])
    assert values["secret_steals"] == 3
    assert values["ghost_steals"] == 0
    assert values["donate"] is None, "an unreadable expression became a number"
    assert values["wounded"] == 681
    # A key the line never mentioned reads the same way — "no reading".
    assert dashmod.parse(["DASH donate=5"])["wounded"] is None


def test_lua_prints_a_count_either_way():
    """Lua 5.1 says `3.0` and 5.3 says `3`; the strip must show 3 for both."""
    assert dashmod.parse(["DASH donate=12"])["donate"] == 12
    assert dashmod.parse(["DASH donate=12.0"])["donate"] == 12
    assert isinstance(dashmod.parse(["DASH donate=12.0"])["donate"], int)
    # Anything that is not a number at all is no reading, not a crash.
    assert dashmod.parse(["DASH donate=nil"])["donate"] is None
    assert dashmod.parse([])["donate"] is None
    assert dashmod.parse(["nothing here at all"])["donate"] is None


def test_the_latest_answer_wins():
    """Two answers in one read (an overlapping poll) must not show the older."""
    values = dashmod.parse(["DASH donate=1", "DASH donate=9"])
    assert values["donate"] == 9, values["donate"]


def test_budgets_stay_on_the_strip_at_zero_and_queues_drop_off_it():
    """«кражи 0» is the news; «ждут помощи 0» is the normal state.

    A strip of ten zeroes is a strip nobody reads, and the whole question it
    answers is "does today need me at all".
    """
    values = {key: 0 for key in dashmod.KEYS}
    shown = {reading.key for reading, _v in dashmod.visible(values)}
    budgets = {r.key for r in dashmod.READINGS if not r.quiet_at_zero}
    assert shown == budgets, shown
    assert budgets, "no reading is marked as a budget"

    # An unreadable queue is KEPT: a dead daemon must be visible from here.
    values["help_waiting"] = None
    shown = {reading.key for reading, _v in dashmod.visible(values)}
    assert "help_waiting" in shown, shown

    # …and anything with work in it is shown, of course.
    values["help_waiting"] = 4
    assert ("help_waiting", 4) in [(r.key, v) for r, v in dashmod.visible(values)]


def test_every_reading_has_a_label_in_both_locales():
    import json
    for lang in ("ru", "en"):
        have = json.load(open(_REPO / "panel" / "locales" / f"{lang}.json",
                              encoding="utf-8"))
        for reading in dashmod.READINGS:
            assert reading.label_key in have, (lang, reading.label_key)


# -- the map sweep ---------------------------------------------------------

def test_the_sweep_covers_the_whole_box_including_its_far_edge():
    """A pass that stopped short of the edge would leave exactly the band a
    neighbour's tiles sit in — so both ends of each axis are visited."""
    points = sweepmod.waypoints(100, 100, radius=24, step=8)
    xs = {x for x, _y in points}
    ys = {y for _x, y in points}
    for axis in (xs, ys):
        assert min(axis) == 76 and max(axis) == 124, sorted(axis)
    assert len(points) == 49, len(points)

    # A radius the step does not divide evenly still reaches the edge.
    uneven = sweepmod.waypoints(100, 100, radius=10, step=8)
    assert min(x for x, _ in uneven) == 90 and max(x for x, _ in uneven) == 110, uneven


def test_the_walk_is_serpentine_so_the_camera_never_teleports():
    """Row left-to-right then right-to-left: every waypoint is next to the last.

    A raster scan would jump the whole width of the box between two rows, which
    both wastes the travel and loads the blocks out of order.
    """
    points = sweepmod.waypoints(100, 100, radius=24, step=8)
    row = 7                                    # 7x7 box
    assert points[row - 1][0] == points[row][0], (points[row - 1], points[row])
    assert points[0][0] < points[row - 1][0]   # first row runs one way…
    assert points[row][0] > points[2 * row - 1][0]   # …the second, the other


def test_a_base_at_the_map_edge_does_not_ask_for_tiles_off_the_map():
    points = sweepmod.waypoints(2, 2, radius=24, step=8)
    assert all(sweepmod.MIN_COORD <= x <= sweepmod.MAX_COORD for x, _y in points)
    assert all(sweepmod.MIN_COORD <= y <= sweepmod.MAX_COORD for _x, y in points)
    # Clamping folds waypoints together; the same jump must not be asked for twice.
    assert len(points) == len(set(points)), points


def test_degenerate_boxes_are_one_jump_not_none():
    assert sweepmod.waypoints(50, 50, radius=0, step=8) == [(50, 50)]
    # A hand-typed step of nonsense is bounded, not obeyed.
    assert sweepmod.waypoints(50, 50, radius=24, step=0)
    assert sweepmod.waypoints(50, 50, radius=24, step=10 ** 6)


def test_the_ui_can_say_what_a_pass_costs_before_the_first_jump():
    """The person ticking the box is agreeing to a length of time."""
    jumps, seconds = sweepmod.describe(500, 500, 24, 8, 3.0)
    assert jumps == 49
    assert seconds == 49 * 3.0
    # A dwell below the floor is clamped, so the estimate is never a fantasy.
    _jumps, floored = sweepmod.describe(500, 500, 24, 8, 0.01)
    assert floored == 49 * sweepmod.MIN_DWELL


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
