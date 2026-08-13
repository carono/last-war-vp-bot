"""The register of players, and the searching of it — no Tk, no game, no panel.

Everything on this page that is a DECISION rather than a widget lives here, so it can
be run and tested without a window: what a sweep is allowed to write onto a row, what a
filter means, and what the counter counts.

## The rule of this list

**A row leaves for one reason and it is a person asking.** Not a lap that drove past
nobody, not a capture that was not running, not a client that was not logged in, not a
panel that was restarted, not a tab being opened. Those are all the same event — «this
read said nothing» — and treating one of them as «that player is gone» is exactly the
loss `panel/kept.py` was written after (#1282, three in one day). So the store is a
:class:`~panel.kept.Kept` that accepts :data:`~panel.kept.PERSON_ASKED` and nothing
else: `drop` for any other reason raises where it is written.

Everything else a page might want to hide is a FILTER — «давно не виден» is a way of
showing a row, never a way of removing one.

## Two notes, and they are not the same note

* `remark` is the note the GAME holds: the client lets you write one on another player
  and stores it server-side. It arrives once, at login (`user.remark.list`), and the
  command that WRITES one has never been captured — so the panel shows it and never
  touches it. Read-only, from the game, about that player.
* `note` is the mark the PERSON writes here. It exists because the game's own note
  cannot be written from outside the client, and it belongs to this profile's register
  rather than to the account.

Keeping them apart is what stops the panel keeping a second version of a truth the game
already owns: nothing here ever writes into a field a sweep fills.

## Nothing here ever asks the game anything

**The register takes what a lap already brings and never goes back for more.** Not on
opening the page, not on a filter, not on a sort, not for one row somebody selected. A
sweep sees thousands of players and a top-up per player would be thousands of requests
the game never asked for — so a field the map did not carry stays empty, and the page
SAYS it is empty rather than fetching it.

That is why the server filter picks a NUMBER rather than «свой / чужой»: which server is
this account's is a question only the client can answer, and asking it would have been
exactly the read this rule forbids. Every row already carries the server its tile was
on, so the box offers those.

The combat numbers are the same bargain from the other side: they arrive only when the
person opens a player IN THE GAME, or when the client fetches the alliance roster at
login. The register keeps them when they pass by and never sends for them.

## Why a sweep may not write None

A base tile carries no combat numbers and a capture that has just started has heard no
notes, so both arrive as `None` on a perfectly good record. Merged as they stand they
would erase a power read an hour ago and a note read at login. So :func:`incoming`
drops the empty fields on the way in: an unknown never overwrites a known, which is the
same sentence as «an empty read removes nothing», one field down.
"""
from __future__ import annotations

import json
import os
import time

from ...kept import PERSON_ASKED, Kept

#: The fields a register row can hold. Anything else a checkpoint carries is dropped on
#: the way in — a store that quietly grew a column would be a store nobody could review.
FIELDS = (
    "uid", "name", "level", "server_id", "x", "y", "uuid", "country",
    "alliance_id", "alliance_abbr", "alliance_name",
    "power", "army_power", "army_kill", "svip_level",
    "remark", "note", "first_seen", "last_seen", "profile_seen_at",
)

#: What a sweep is allowed to write. `note` is deliberately NOT here: the person's own
#: mark is written by the person and by nothing else, so no lap can touch it however
#: the wire spells that player's name tomorrow.
FROM_GAME = tuple(f for f in FIELDS if f not in ("note", "first_seen", "last_seen"))

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


def incoming(record: dict, now: float | None = None) -> dict:
    """One checkpoint record as the register takes it — empties dropped, stamped.

    `seen_at` on the capture's side means «the map or a profile reply last confirmed
    this», which is exactly what `last_seen` means here, so it is renamed rather than
    kept twice under two names that would drift.
    """
    now = time.time() if now is None else now
    out = {}
    for field in FROM_GAME:
        value = record.get(field)
        # Zero is a real level and a real coordinate; only None is «did not say».
        if value is not None and value != "":
            out[field] = value
    if out.get("uid") is None:
        return {}
    out["uid"] = str(out["uid"])
    out["last_seen"] = int(record.get("seen_at") or now)
    return out


class PlayerRegistry:
    """Everyone this profile's laps have driven past, kept for good.

    A thin layer over :class:`~panel.kept.Kept`: the file, the key and the one removal
    reason are decided here so that no caller has to remember them, and the two writes
    a person can make — a mark, a forgetting — are the only two methods that change a
    row's own fields.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._kept = Kept(path, key="uid", accepts=(PERSON_ASKED,))

    # -- reading ---------------------------------------------------------------------
    def rows(self) -> list:
        return self._kept.rows()

    def get(self, uid) -> dict | None:
        return self._kept.get(uid)

    def __len__(self) -> int:
        return len(self._kept)

    # -- what a lap adds -------------------------------------------------------------
    def absorb(self, records, now: float | None = None) -> int:
        """Merge what a capture has seen. **Adds and updates; never removes.**

        Returns how many rows were added or changed, so a caller can say «the lap
        brought 412 new faces» rather than «something happened».
        """
        now = time.time() if now is None else now
        fresh = []
        for record in records or ():
            if not isinstance(record, dict):
                continue
            row = incoming(record, now)
            if not row:
                continue
            held = self._kept.get(row["uid"])
            if held is None:
                # `first_seen` is written once and never again — the merge updates a row
                # field by field, so writing it every time would move it forward.
                row["first_seen"] = row["last_seen"]
            elif all(held.get(field) == value for field, value in row.items()):
                # NOTHING NEW ABOUT THIS PLAYER, so nothing is merged and the file is
                # not rewritten. The checkpoint re-lists the same sighting every tick
                # for as long as it is fresh, and `Kept.merge` compares a row it is
                # GIVEN against the row it HOLDS — which carries `first_seen` and the
                # person's own mark besides, so the two are never equal and every
                # single tick counted as a change. Live that was «карта добавила или
                # обновила 103» every twenty seconds, for ever, over an unchanged map.
                continue
            fresh.append(row)
        return self._kept.merge(fresh)

    # -- what a person writes --------------------------------------------------------
    def set_note(self, uid, text: str | None) -> bool:
        """Write (or clear) THIS PROFILE's own mark on a player.

        A mark on a player the register has never heard of is refused rather than
        filed: a row with a note and no name is not a player, and the press that could
        make one is a bug somewhere else.
        """
        row = self._kept.get(uid)
        if row is None:
            return False
        text = (text or "").strip()
        self._kept.merge([{"uid": str(uid), "note": text or None}])
        return True

    def forget(self, uid) -> bool:
        """THE ONE WAY A ROW LEAVES — a person asked for it (`PERSON_ASKED`).

        The store accepts no other reason, so this is not a convention but the only
        call that compiles.
        """
        return self._kept.drop(uid, PERSON_ASKED)

    # -- what the page tells about itself --------------------------------------------
    def alliances(self) -> list:
        """Every alliance tag in the register, once each, in alphabetical order."""
        tags = {(row.get("alliance_abbr") or "").strip()
                for row in self._kept.rows()}
        return sorted(t for t in tags if t)

    def servers(self) -> list:
        """Every server number in the register, ascending."""
        found = {row.get("server_id") for row in self._kept.rows()}
        return sorted(s for s in found if isinstance(s, int))

    def file_size(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0


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
