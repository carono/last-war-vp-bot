"""What «Гонка вооружений» paid TODAY, phase by phase — the panel's own book (#2579).

The person asked the card for two things: «сколько сундуков собрано за день», and,
behind the «i», «иконками каждый час события за сегодня и сколько там собрано сундуков
в каждом часе».

WHY A BOOK AND NOT A READING. The game keeps no history of it. Measured live on the
client (probe of #2579): `dataDict` carries the CURRENT phase's three boxes with their
`receive` flags, the day's three, and a `claimStatus` keyed `<day>_<stage>` whose value
is a FLAG — `1` once that phase counts as finished, never a count. A phase that ended an
hour ago is gone; nothing on the client can be asked how many of its boxes were taken.

So the panel writes down what the GAME SAID while each phase was the current one. Every
arms reading that lands — the four-hourly errand's and the person's own «Обновить» on
«События» — is one entry: this stage, this kind, this many of its three boxes taken. No
question is asked to fill it (`CLAUDE.md`, «Read once, then LISTEN»), and a phase nobody
read while it was running is simply absent rather than guessed at.

THE DAY IS THE SERVER'S. The event resets at the warzone's own midnight and this machine
is hours away from it, so the key is `game_day.day_key` exactly as the rally counts and
the fireworks book use it. A book from yesterday answers «nothing today», never
yesterday's numbers.

WHAT IS STORED — one row of `blobs`, per profile, whole::

    {"day": "2026-09-06", "ladder": 3,
     "stages": {"0": {"kind": 120004, "chests": 3, "at": 1788704000.0}, …}}

`ladder` is the DAY's own three boxes (`d1..d3`), which are a separate ladder from the
phases' — the game pays three more for finishing one, two and three phases.
"""
from __future__ import annotations

import time

#: The row in this profile's `blobs` table. Game data, so it is in the database and not
#: a file (`CLAUDE.md`, «Game data lives only in the database»).
BLOB = "arms_chests_day"

#: How many boxes one phase pays, and how many the day's own ladder pays. Both are the
#: game's, read off the live reading rather than assumed — these are only what a book
#: with nothing in it says the ceiling is.
PHASE_CHESTS = 3
DAY_CHESTS = 3


def _day() -> str:
    """Today, as the SERVER counts it — the same key the rally book uses."""
    import datetime
    try:
        import game_clock                     # lazy: tools/lib is on the panel's path
        import game_day
        stamp = game_clock.now_ms()
    except Exception:                         # noqa: BLE001 — no tools path, no game
        stamp = None
    if not stamp:
        return datetime.datetime.utcnow().date().isoformat()
    return game_day.day_key(stamp)


def read(rt) -> dict:
    """Today's book, or an empty one — never yesterday's, never an exception."""
    today = _day()
    try:
        held = rt.store.blob_get(BLOB)
    except Exception:                         # noqa: BLE001 — a reading, never the page
        held = None
    if not isinstance(held, dict) or held.get("day") != today:
        return {"day": today, "ladder": 0, "stages": {}}
    stages = held.get("stages")
    return {"day": today,
            "ladder": _int(held.get("ladder")),
            "stages": dict(stages) if isinstance(stages, dict) else {}}


def record(rt, stage, kind, chests, ladder=None) -> None:
    """Write down what this reading said about the phase that is running.

    Called where an arms reading is APPLIED and nowhere else, so the book costs exactly
    nothing: it is the answer that already arrived, kept.

    A stage's entry only ever grows. A phase pays its boxes one after another and the
    reading that catches it early sees fewer than the one that catches it late; taking
    the larger of the two is right for both, and it also survives the reading that
    arrives during the FIRST seconds of the next phase, when the server has already
    swapped `curStage` but the errand has not yet claimed anything.
    """
    if stage is None:
        return
    book = read(rt)
    key = str(_int(stage))
    was = book["stages"].get(key) if isinstance(book["stages"].get(key), dict) else {}
    taken = max(_int(chests), _int(was.get("chests")))
    book["stages"][key] = {"kind": _int(kind), "chests": taken, "at": time.time()}
    if ladder is not None:
        book["ladder"] = max(_int(ladder), _int(book.get("ladder")))
    try:
        rt.store.blob_set(BLOB, book)
    except Exception:                         # noqa: BLE001 — a tally, never the run
        pass


def total(rt) -> tuple:
    """`(chests, phases_seen, age)` — what the day has paid, as the book knows it.

    `chests` counts the phases' own boxes AND the day's ladder, because that is what a
    person means by «сколько сундуков гонки собрано сегодня»: they all land in the bag.
    `age` is how long ago the freshest entry was written, or `None` for an empty book —
    a book is not a reading, so its age is the age of the newest thing in it.
    """
    book = read(rt)
    stages = book.get("stages") or {}
    chests = _int(book.get("ladder"))
    newest = None
    for row in stages.values():
        if not isinstance(row, dict):
            continue
        chests += _int(row.get("chests"))
        at = row.get("at")
        try:
            at = float(at)
        except (TypeError, ValueError):
            continue
        if at and (newest is None or at > newest):
            newest = at
    age = None if newest is None else max(0.0, time.time() - newest)
    return chests, len(stages), age


def phases(rt, calendar=()) -> list:
    """One row per phase of today, for the sheet behind the «i».

    The CALENDAR decides the order and the hours — it is the day's six windows as the
    server fixed them a week ago — and the book fills in what each of them paid. A phase
    the calendar names and the book has never seen carries `chests: None`, which the
    phone draws as «—»: nobody looked while it was running, and that is not the same as
    «nothing was taken».

    With no calendar at all the book's own stages are listed in their own order, so a
    profile whose «События» page has never been opened still gets the phases it worked.
    """
    book = read(rt)
    stages = book.get("stages") or {}
    out = []
    seen = set()
    for entry in calendar or ():
        try:
            stage, kind, start, end = (int(entry[0]), int(entry[1]),
                                       int(entry[2]), int(entry[3]))
        except (TypeError, ValueError, IndexError):
            continue
        row = stages.get(str(stage))
        seen.add(str(stage))
        out.append({"stage": stage, "kind": kind, "start": start, "end": end,
                    "chests": (_int(row.get("chests"))
                               if isinstance(row, dict) else None),
                    "all": PHASE_CHESTS})
    for key in sorted(stages, key=lambda k: _int(k)):
        if key in seen:
            continue
        row = stages.get(key)
        if not isinstance(row, dict):
            continue
        out.append({"stage": _int(key), "kind": _int(row.get("kind")),
                    "start": 0, "end": 0,
                    "chests": _int(row.get("chests")), "all": PHASE_CHESTS})
    return out


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
