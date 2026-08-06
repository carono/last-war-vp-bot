r"""Walk the camera over the map so the passive scan has something to see.

The secret-task capture is a pcap: it only learns tiles from the map responses the
client sends **while the map is moving**. So «Автолут ★» — sold as a standing order
— was only ever as autonomous as the person dragging the map, and both the monitor
and the watcher had to say so in the log ("двигай карту, иначе трафика не будет").
This module is the wrist: a rectangle of waypoints around a centre, walked one
coordinate jump at a time, on a period. A scan sweep becomes a checkbox.

The jump itself is the panel's existing primitive (`lua_actions.jump_to_coord`, the
same call a clickable coordinate in the log uses), so nothing new touches the game
— this only decides **where to look next**.

Three decisions live here, and they are the whole module:

  * **The step is the screen, not the tile.** A jump loads the map blocks around
    where it lands, so stepping by roughly a screenful covers the box in the fewest
    jumps. :data:`DEFAULT_STEP` is deliberately shorter than a screen: overlap costs
    a jump, a gap costs the tiles in it, and only one of those is recoverable.
  * **How big a screenful is comes from the camera, and is not decided here.** The
    height decides how much map one jump asks the server for — ±15 tiles at the game's
    own 105, ±48 at 600, and above 1199 nothing arrives at all — so the step belongs to
    the height. The pair lives in `lua_actions.ZOOM_LEVELS` and is chosen on the
    «Секретки» coordinate bar (docs/research/map-sweep-zoom.md).
  * **Serpentine, not raster.** Row left-to-right then right-to-left, so every
    waypoint is next to the previous one. The camera travels the short way, the
    blocks load contiguously, and the sweep never teleports across the map between
    two neighbouring tiles.

Nothing here imports Tk, and it holds no state: :func:`waypoints` is a pure
function of the box, and the panel keeps the cursor into the list. That makes the
geometry — which is the part that is easy to get quietly wrong — testable without
a display, a daemon or a client.
"""
from __future__ import annotations

import os
import sys

# tools/lib is already on sys.path when the panel imports us; a bare import keeps this
# module usable from a test that only put the repo root there. The zoom ceiling lives
# with the chunk that spends it (`tools/lib/lua_actions.py`) rather than being spelled
# out a second time here.
_TOOLS_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tools", "lib")
if _TOOLS_LIB not in sys.path:
    sys.path.insert(0, _TOOLS_LIB)
import lua_actions      # noqa: E402

# Sanity clamp on a waypoint. The real world map sits well inside this (the same
# bound `tools/lib/coords.py` filters stray numbers with); the clamp only matters
# for a base near an edge, where half the box would otherwise be off the map.
MIN_COORD = 0
MAX_COORD = 2000

# The camera height and the step are ONE decision and live together in
# `lua_actions.ZOOM_LEVELS`, chosen on the «Секретки» coordinate bar (#1265). Nothing
# here holds a height any more: a step read apart from the height it was measured at is
# a number that means nothing, and two knobs that must agree are two knobs that will not.
#
# `DEFAULT_STEP` is what a fresh profile's level sweeps at, kept for the geometry's own
# default argument and for `describe()` — the caller passes the level's real step.
DEFAULT_STEP = lua_actions.ZOOM_LEVELS[lua_actions.DEFAULT_ZOOM_LEVEL][1]
# Half the side of the box, in tiles. 120 with the secret-task level's step of 90 is a
# 4×4 grid — sixteen waypoints, under a minute a pass — over a 241×241 neighbourhood,
# where the old 24/8 pair walked 49×49 in forty-nine jumps. (For the WHOLE map,
# «Обойти карту» is a lap of six seconds and this box is not the tool.)
DEFAULT_RADIUS = 120
# Bounds the UI offers, so a hand-typed number cannot ask for a sweep of one tile
# or one that never comes round again.
MIN_STEP, MAX_STEP = 1, 120
MIN_RADIUS, MAX_RADIUS = 4, 400

# Seconds between two jumps of a sweep. A jump settles ~1.6 s in the panel, and the
# capture needs the responses to arrive and be decoded before the camera moves on;
# below ~2 s the sweep outruns its own point.
DEFAULT_DWELL = 3.0
MIN_DWELL, MAX_DWELL = 1.0, 60.0


def clamp(value: int, low: int = MIN_COORD, high: int = MAX_COORD) -> int:
    return max(low, min(high, int(value)))


def waypoints(cx: int, cy: int, radius: int = DEFAULT_RADIUS,
              step: int = DEFAULT_STEP) -> list[tuple[int, int]]:
    """The box around ``(cx, cy)`` as a serpentine list of coordinates to jump to.

    Both ends of each axis are included, so a box that does not divide evenly by
    the step still has its far edge visited — a sweep that stopped short of the
    edge would leave exactly the band a neighbour's tiles sit in.

    Duplicates are dropped (a radius under one step, or a box clamped against the
    map edge, would otherwise ask for the same jump twice in a row) while the
    serpentine order is kept.
    """
    step = max(MIN_STEP, min(MAX_STEP, int(step)))
    radius = max(0, min(MAX_RADIUS, int(radius)))
    cx, cy = clamp(cx), clamp(cy)

    xs = _axis(cx, radius, step)
    ys = _axis(cy, radius, step)
    out: list[tuple[int, int]] = []
    seen: set = set()
    for row, y in enumerate(ys):
        line = xs if row % 2 == 0 else list(reversed(xs))
        for x in line:
            point = (x, y)
            if point in seen:
                continue
            seen.add(point)
            out.append(point)
    return out


def _axis(centre: int, radius: int, step: int) -> list[int]:
    """One axis of the box: ``centre-radius … centre+radius`` every ``step``, clamped.

    The far end is appended when the step overshoots it, which is what keeps the
    edge of the box inside the sweep.
    """
    low, high = clamp(centre - radius), clamp(centre + radius)
    out: list[int] = []
    value = low
    while value < high:
        out.append(value)
        value += step
    out.append(high)
    # Clamping can fold the last two together (a base at the map edge).
    return sorted(set(out))


def describe(cx: int, cy: int, radius: int, step: int, dwell: float) -> tuple[int, float]:
    """``(jumps, seconds)`` one full pass of this box costs — for the UI's own label.

    The person ticking the box is agreeing to a length of time, so the panel should
    be able to say what it is before the first jump rather than after the last.
    """
    points = waypoints(cx, cy, radius, step)
    return len(points), len(points) * max(MIN_DWELL, float(dwell))
