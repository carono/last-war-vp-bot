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

Two decisions live here, and they are the whole module:

  * **The step is the screen, not the tile.** A jump loads the map blocks around
    where it lands, so stepping by roughly a screenful covers the box in the fewest
    jumps. :data:`DEFAULT_STEP` is deliberately shorter than a screen: overlap costs
    a jump, a gap costs the tiles in it, and only one of those is recoverable.
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

# Sanity clamp on a waypoint. The real world map sits well inside this (the same
# bound `tools/lib/coords.py` filters stray numbers with); the clamp only matters
# for a base near an edge, where half the box would otherwise be off the map.
MIN_COORD = 0
MAX_COORD = 2000

# How far apart two waypoints are, in tiles. Shorter than one screen of the world
# map on purpose (see the module docstring): the sweep would rather jump twice than
# leave a band of tiles nobody asked the server about.
DEFAULT_STEP = 8
# Half the side of the box, in tiles. 24 with a step of 8 is a 7×7 grid — 49
# waypoints, a couple of minutes a pass — which is the neighbourhood a base's
# secret tasks and treasures actually appear in.
DEFAULT_RADIUS = 24
# Bounds the UI offers, so a hand-typed number cannot ask for a sweep of one tile
# or one that never comes round again.
MIN_STEP, MAX_STEP = 1, 64
MIN_RADIUS, MAX_RADIUS = 4, 256

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
