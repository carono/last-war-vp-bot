r"""The Street Run planner against track the game itself draws.

The standing guard on this planner is a band at a time: `surfing_battery.py` replays each
layout on its own, from a standing start, at 30 u/s. That is where a change gets caught
breaking a whole class of obstacle — and it is structurally blind to the failure that
actually ends runs, which is arriving in a band in the wrong lane or at the wrong height. A
band that clears from all three start lanes in isolation can still be the band a route dies
in, because a route enters it in a state the isolated replay never puts it in. Both of the
planner faults fixed at #1164 were of exactly that shape.

So this replays whole ROUTES, drawn the way the game draws one: slot by slot out of the pool
that slot has, at the speed steps the schedule gives it (`tools/dev/surfing_tracks.py`). Each
seed is a different 11880 m of track and none of them was tuned against.

What each route is measured against is a FLOOR, not the finish. Some drawn track has no way
through it at all — the pool holds layouts nothing clears at the speed the game runs them —
so demanding the whole 11880 m would be demanding the impossible, and a test that cannot pass
says nothing when it fails. The floors below are one of two things:

  * the route's CEILING, where the exhaustive search has been run over it — the furthest
    anything can get while keeping the same 1.5 m of clearance the planner keeps. That is
    `surfing_battery.py`'s ceiling column, and it costs the better part of an hour a route;
  * otherwise the distance measured when the seed was added, i.e. a plain regression floor
    with no claim that it is the best there is.

A failure says which of two things happened: a route fell below its floor (a regression), or
a route beat a floor pinned as a ceiling — which means the ceiling was measured wrong or the
judge has changed under it. Look before re-pinning either way.

This one is slow: ~7 minutes for the twelve routes, because it runs the real planner through
a real Lua VM over 130 km of track. `SR_TEST_SEEDS=3` cuts it to the first three seeds for a
quick pass; the full set is what a planner change has to be shown against.

    python3 tests/test_street_run_routes.py     # standalone, prints PASS/FAIL
    SR_TEST_SEEDS=3 python3 tests/test_street_run_routes.py
    pytest tests/test_street_run_routes.py      # or under pytest

Exit codes (standalone): 0 = passed, 1 = failed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "tools" / "dev", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
# the track config and the human recordings are addressed relative to the repo root
os.chdir(_REPO)

import surfing_offline as O  # noqa: E402
import surfing_simulate as S  # noqa: E402

# seed -> (floor, is it the searched ceiling). A drawn route is `pool:36:SEED`: 36 bands,
# 11880 m, replayed from the centre lane. The planner lands a metre or two past a ceiling
# because a frame step straddles it — that is not beating it, see CEILING_SLACK.
FLOORS = {
    1: (11880, True),    # searched ceiling: the whole route, and the planner runs all of it
    2: (9039, True),     # searched ceiling: band 27 is a 2004 at 60 u/s, which nothing clears
    3: (11019, True),    # searched ceiling
    4: (11880, True),    # searched ceiling: the whole route
    5: (11880, True),    # searched ceiling: the whole route
    6: (11880, True),    # runs the whole route, which is the only ceiling a route can have
    7: (7390, False),    # measured; dies in a 2004 at 60
    8: (11880, True),    # runs the whole route
    9: (8710, False),    # measured
    10: (11880, True),   # runs the whole route
    11: (1168, False),   # measured; dies in a 312 at 30
    12: (1168, False),   # measured; the search puts this route's ceiling at 1166
}

# The one route a person actually ran, replayed at the ramp they ran it at. Its ceiling was
# searched at #1161 and the planner has sat on it since.
RUN_002_FLOOR = 7386

# How far past a pinned ceiling counts as "reached it" rather than "beat it": the replay
# advances by one frame at a time, so it reports the first z past the end, not the end.
CEILING_SLACK = 5


def _distance(spec: str) -> tuple[float, int]:
    """(how far the planner got, how long the route is) — from the centre lane."""
    order, _note, _first, steps = O.route_plan(spec)
    accel = O.route_accel(spec)
    speed0 = steps[0][1] if steps else 30.0
    zmax = len(order) * S.BAND_PITCH
    rt, _ = O.new_vm({})
    ov, band, hole, roof, _, _ = S.build_field(accel=accel, order=order, speed0=speed0,
                                               steps=steps)
    dist, _dead, _moves = O.run_group(rt, ov, band[0], hole[0], roof[0], 1, speed0, accel,
                                      zmax, steps)
    return dist, zmax


def _seeds() -> list:
    limit = int(os.environ.get("SR_TEST_SEEDS") or 0)
    keys = sorted(FLOORS)
    return keys[:limit] if limit else keys


def test_recorded_run_holds_its_ceiling():
    """run_002 — the only route with a human line behind it, and the oldest measurement."""
    dist, zmax = _distance("run_002")
    assert dist >= RUN_002_FLOOR, (
        f"run_002 fell to {dist:.0f} of {zmax} m, its searched ceiling is {RUN_002_FLOOR}")


def test_drawn_routes_reach_their_floor():
    """Routes the game could lay down at any time, none of them ever tuned against."""
    bad = []
    for seed in _seeds():
        floor, is_ceiling = FLOORS[seed]
        dist, zmax = _distance("pool:36:%d" % seed)
        if dist < floor:
            bad.append("seed %d: %.0f of %d m, floor %d%s"
                       % (seed, dist, zmax, floor, " (its ceiling)" if is_ceiling else ""))
        elif is_ceiling and dist > floor + CEILING_SLACK:
            bad.append("seed %d: %.0f of %d m BEAT its pinned ceiling %d — the ceiling was "
                       "measured wrong, or the judge has changed under it"
                       % (seed, dist, zmax, floor))
    assert not bad, "\n  ".join([""] + bad)


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
