"""The LAST reading of «Гонка вооружений» — one state, kept where both pages find it.

Written for the card on «VS» (#2635), which asks for three things the errand's row never
carried: the hour running now, the three chests of that hour as the game flags them, and
the points the server has for it. All three already arrive in one reading
(`actions/read_arms_race.md`), and the only reason the card could not draw them was that
the answer lived in ONE tab's memory — «События», which is polled while somebody is
looking at it and holds nothing at all on a panel where that page is switched off.

So the reading is kept here, in this profile's own database (`CLAUDE.md`, «Game data
lives only in the database»), and everything that takes one writes it down: the
«События» card, and the «VS» tab whose reads are the ones #2633 asks for — once when the
client gets into the game, then on the event's own push, then on the border of the hour.
Whoever DRAWS it — the errand's row on «VS», the sheet behind its «i» — reads this and
asks the game nothing.

WHAT IS STORED is the reading exactly as the scenario handed it over, plus the calendar
and the moment it landed::

    {"arms": "open=1 aid=29 day=7 stage=1 event=120000 … sc=800 …",
     "day": "0:120004:1788055200:1788069600 …", "at": 1788704000.0}

The raw line rather than a parsed dictionary, for the same reason `arms_book` keeps what
the game said: a panel that learns to read one more field of it tomorrow reads that field
out of what is already written down, instead of finding a shape somebody froze today.

THE CALENDAR SURVIVES A READING THAT BROUGHT NONE. The six borders were fixed by the
server a week ago and do not go stale, while the phase's own line can come back empty
from a client that is still coming up — so a reading with no calendar keeps the one that
is already here rather than blanking the day.
"""
from __future__ import annotations

import time

#: The row in this profile's `blobs` table. Read and written WHOLE, and small — a blob,
#: not a table of its own (`docs/panel-storage.md`).
BLOB = "arms_live"


def record(rt, raw_arms, raw_day="") -> None:
    """Keep what a reading of the arms race said. Never raises — it is a tally."""
    try:
        held = read(rt)
        row = {"arms": str(raw_arms or ""),
               "day": str(raw_day or "") or str(held.get("day") or ""),
               "at": time.time()}
        rt.store.blob_set(BLOB, row)
    except Exception:                    # noqa: BLE001 — a reading, never the run
        pass


def read(rt) -> dict:
    """The row as it stands, or an empty one. Never yesterday's problem: the phase's own
    line carries the day and the stage, so a stale reading says so by its AGE rather than
    by being thrown away — «прочитано 5 ч назад» is the truth and an empty card is not.
    """
    try:
        held = rt.store.blob_get(BLOB)
    except Exception:                    # noqa: BLE001 — a reading, never the page
        held = None
    if not isinstance(held, dict):
        return {}
    return held


def state(rt, calendar=()):
    """`(ArmsState, age)` — the card both front-ends draw, and how old it is.

    `age` is `None` when nothing has ever been read, and the state is then the model's
    own «unknown», which draws as words rather than as zeros. `calendar` is what the
    caller already has (the «События» tab holds one while it is open) and is used only
    where the stored reading brought none.
    """
    from ..tabs.events import model as eventsmod       # noqa: PLC0415 — one model

    held = read(rt)
    raw = held.get("arms")
    at = held.get("at")
    try:
        at = float(at)
    except (TypeError, ValueError):
        at = 0.0
    days = eventsmod.arms_calendar(held.get("day")) or tuple(calendar or ())
    if not raw:
        return eventsmod.arms_state(None, days), None
    reading = eventsmod.parse(raw, at=at)
    age = max(0.0, time.time() - at) if at else None
    return eventsmod.arms_state(reading, days), age
