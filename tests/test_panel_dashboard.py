r"""The account dashboard — the strip, without a display, a daemon or a client.

The module touches neither Tk nor the game, which is the point: what is easy to
get quietly wrong here is *the reading* — a budget that could not be read must
never look like a budget of zero — and that is a plain function, so it is tested.

The map sweep used to be tested here beside it. Both the walk and its geometry
(`panel/mapsweep.py`) are gone with «Автообъезд карты» (#1272): «Обойти карту»
schedules the jumps inside the game and covers the whole server in about three
seconds (#1265), so there is no serpentine waypoint list left to get wrong.

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
