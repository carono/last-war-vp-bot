"""The SEARCHING of the register — no Tk, no game, no panel.

Everything on this page that is a DECISION rather than a widget lives here, so it can
be run and tested without a window: what a filter means, how a column sorts, and what
the counter counts.

**The register itself moved to the runtime** (`panel/runtime/players.py`, #1371), and
that is the whole point of #1371: a lap of the map is not the only place the panel meets
a player — the live block of banners, the chat, the alliance roster and every tile with
an owner meet one too. They all write through `rt.players.sighted(…)`, and this page is
one of the readers of what they left. The rules that used to be written here — what a
source may overwrite, why an unknown never wins over a known, how a field remembers
where it came from, and that a row leaves only when a PERSON asks — live beside the
store now.

## Two notes, and they are not the same note

* `remark` is the note the GAME holds: the client lets you write one on another player
  and stores it server-side. It arrives once, at login (`user.remark.list`), and the
  command that WRITES one has never been captured — so the panel shows it and never
  touches it. Read-only, from the game, about that player.
* `note` is the mark the PERSON writes here. It exists because the game's own note
  cannot be written from outside the client, and it belongs to this profile's register
  rather than to the account.

Keeping them apart is what stops the panel keeping a second version of a truth the game
already owns: nothing here ever writes into a field a source fills.

## Nothing here ever asks the game anything

**The register takes what the panel is already told and never goes back for more.** Not
on opening the page, not on a filter, not on a sort, not for one row somebody selected.
A sweep sees thousands of players and a top-up per player would be thousands of requests
the game never asked for — so a field no source carried stays empty, and the page SAYS
it is empty rather than fetching it.

That is why the server filter picks a NUMBER rather than «свой / чужой»: which server is
this account's is a question only the client can answer, and asking it would have been
exactly the read this rule forbids. Every row already carries the server its tile was
on, so the box offers those.

The one thing on the page that DOES reach the client is the press on a coordinate, which
jumps the camera there (#1371) — a person asking for something to happen, which is
never what this rule was about (`CLAUDE.md`, «A button that STARTS something is not the
thing being forbidden»).
"""
from __future__ import annotations

import json
import time

from ...runtime.players import (  # noqa: F401  (the page's own vocabulary)
    CHECKPOINT_SOURCES, FIELDS, SOURCES, SRC_ALLIANCE, SRC_CHAT, SRC_MAP,
    SRC_PERSON, SRC_PROFILE, SRC_RALLY, SRC_REMARK, SRC_TILE, PlayerBook,
    provenance_of,
)

#: How old a sighting has to be before «давно не виден» claims it. A week: the map is
#: swept in laps of a few seconds and a base that has not been under one for seven days
#: is either on ground nobody drives over or gone.
STALE_AFTER_SEC = 7 * 24 * 3600

#: The «виден» filter, as (id, seconds) — None means «any age at all».
SEEN_WINDOWS = {
    "any": None,
    "hour": 3600,
    "day": 24 * 3600,
    "week": 7 * 24 * 3600,
}


# ---------------------------------------------------------------------------
# searching
# ---------------------------------------------------------------------------

def _text_of(row: dict) -> str:
    """Everything one row can be searched BY, as one lowercase haystack.

    The name, both spellings of the alliance and the coordinate the way a person types
    it — «612,480» — so one box answers the three searches the page promises instead of
    three boxes each answering one.
    """
    bits = [row.get("name") or "", row.get("alliance_abbr") or "",
            row.get("alliance_name") or "", row.get("note") or "",
            row.get("remark") or ""]
    if row.get("x") is not None and row.get("y") is not None:
        bits.append("%s,%s" % (row["x"], row["y"]))
    return " ".join(bits).casefold()


def _in_range(value, low, high) -> bool:
    if low is not None and (value is None or value < low):
        return False
    if high is not None and (value is None or value > high):
        return False
    return True


def matches(row: dict, f: dict, now: float) -> bool:
    """Does one row pass the whole filter? Every clause is an «and».

    `f` is the filter as the page holds it — every key optional, and a missing or empty
    one means «any». It is a plain dict rather than a class so that the window's
    variables, the phone's presses and a test can all build one the same way.
    """
    text = (f.get("text") or "").strip().casefold()
    if text and text not in _text_of(row):
        return False

    if not _in_range(row.get("level"), f.get("level_min"), f.get("level_max")):
        return False
    if not _in_range(row.get("power"), f.get("power_min"), f.get("power_max")):
        return False

    tag = (f.get("alliance") or "").strip().casefold()
    if tag and (row.get("alliance_abbr") or "").casefold() != tag:
        return False

    # THE SERVER IS PICKED BY NUMBER, not as «own / other» — and that is a decision
    # rather than a simplification. «Свой» is a question only the game can answer, so
    # the page would have had to ask the client which server it is on the first time
    # anybody opened it: a read of the game for a filter, on a tab whose whole point is
    # that it costs a sweep nothing. The numbers are in the register already (every row
    # carries the server its tile was on), so the box offers exactly those.
    server = str(f.get("server") or "").strip()
    if server and str(row.get("server_id")) != server:
        return False

    x, y = row.get("x"), row.get("y")
    box = f.get("rect")
    if box:
        x1, y1, x2, y2 = box
        if x is None or y is None:
            return False
        if not (min(x1, x2) <= x <= max(x1, x2)
                and min(y1, y2) <= y <= max(y1, y2)):
            return False
    circle = f.get("circle")
    if circle:
        cx, cy, radius = circle
        if x is None or y is None:
            return False
        # Chebyshev distance, not Euclidean: the map is a grid of squares and «в
        # пределах 20 клеток» is how a person reads a march range off it.
        if max(abs(x - cx), abs(y - cy)) > radius:
            return False

    seen = f.get("seen") or "any"
    last = float(row.get("last_seen") or 0)
    if seen == "stale":
        if now - last < STALE_AFTER_SEC:
            return False
    elif seen != "any":
        window = SEEN_WINDOWS.get(seen)
        if window is not None and now - last > window:
            return False

    if f.get("noted") and not (row.get("note") or "").strip():
        return False
    return True


def apply_filter(rows, f: dict, now: float | None = None) -> list:
    """The rows a filter keeps, in the order they were given."""
    now = time.time() if now is None else now
    return [r for r in rows if matches(r, f, now)]


#: How each column is ordered, and the tie-break every one of them ends with: without
#: it two players of the same level swap places on every repaint, which reads as a
#: table that will not sit still.
SORT_KEYS = {
    "name": lambda r: ((r.get("name") or "").casefold(), str(r.get("uid"))),
    "level": lambda r: (int(r.get("level") or 0), str(r.get("uid"))),
    "power": lambda r: (int(r.get("power") or 0), str(r.get("uid"))),
    "alliance": lambda r: ((r.get("alliance_abbr") or "").casefold(),
                           str(r.get("uid"))),
    "coords": lambda r: (int(r.get("x") or 0), int(r.get("y") or 0),
                         str(r.get("uid"))),
    "server": lambda r: (int(r.get("server_id") or 0), str(r.get("uid"))),
    "seen": lambda r: (float(r.get("last_seen") or 0), str(r.get("uid"))),
    "note": lambda r: ((r.get("note") or "").casefold(), str(r.get("uid"))),
}

#: What the table opens on before anybody clicks a heading: the freshest sighting
#: first, which is «what the last lap found» without needing a word for it.
DEFAULT_SORT = ("seen", True)


def sort_rows(rows, sort=None) -> list:
    """`sort` is `(column, descending)`; None means :data:`DEFAULT_SORT`."""
    column, down = sort or DEFAULT_SORT
    key = SORT_KEYS.get(column) or SORT_KEYS[DEFAULT_SORT[0]]
    return sorted(rows, key=key, reverse=bool(down))


def load_checkpoint(path: str) -> list:
    """The `players` list out of the capture's world checkpoint, or an empty one.

    A missing, half-written or locked file is an EMPTY answer and never an error: the
    capture rewrites it whole every tick, and the register merges — so a read that
    caught the file mid-replace costs one tick and takes nothing away.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        rows = data.get("players")
        return rows if isinstance(rows, list) else []
    return []
