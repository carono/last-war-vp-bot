"""The checklist itself — the list, the ticks, and the day a tick belongs to. **No Tk.**

Split out from the tab for the reason every model here is: a day boundary and a tick are
worth testing without a window, and `tests/test_panel_checklist.py` runs under the WSL
python that has no display.

**A tick is stamped with a DAY, never with «done».** An item remembers the game-day it
was last ticked on, and «done» is the comparison «that day is today». Nothing has to run
at midnight for the list to clear itself: a panel started the next morning, or left open
over the boundary, computes the same answer from the same stamp. A boolean would need
somebody awake at the reset to clear it, and a panel that was closed at the time would
show yesterday's ticks as today's — which is the one way a checklist can actively lie.

The day is the GAME's day, not this computer's (`tools/lib/game_clock.py`): the machine
this was written on runs eleven seconds behind the server, and a checklist judged by the
PC clock would tick over at a different moment from the game whose reset it is about.
The offset is only ever a correction of drift — nobody here reads the game to build a
list — so an unsynced process simply uses the local clock and is no worse off than
before.

`reset_hour` is the hour of the day (UTC) the count rolls over at. Zero is the ordinary
answer; it is a knob because a server's reset is not everybody's midnight, and an
operator who knows theirs is at 02:00 UTC should not have to keep the offset in their
head while reading the list.
"""
from __future__ import annotations

import uuid

#: One day, and one hour, in the milliseconds every clock here counts in.
DAY_MS = 24 * 60 * 60 * 1000
HOUR_MS = 60 * 60 * 1000


def now_ms() -> int:
    """"Now" on the GAME's clock, in milliseconds — falling back to this machine's.

    `game_clock` lives in `tools/lib`, which the panel's runtime puts on the path. It is
    imported lazily so that this module stays importable on its own (a test, a tool), and
    an import that fails is not an error: an unsynced offset is zero and the answer is
    `time.time()`, which is exactly what every process did before the clock existed.
    """
    import time

    try:
        import game_clock
    except Exception:                       # noqa: BLE001 — a clock is not worth a crash
        return int(time.time() * 1000)
    try:
        return int(game_clock.now_ms())
    except Exception:                       # noqa: BLE001
        return int(time.time() * 1000)


def day_of(stamp_ms, reset_hour: int = 0) -> int:
    """Which game-day `stamp_ms` falls in, counting days from the epoch."""
    return int((int(stamp_ms) - hour_of(reset_hour) * HOUR_MS) // DAY_MS)


def next_reset_ms(stamp_ms, reset_hour: int = 0) -> int:
    """When the day `stamp_ms` is in ends — the moment every tick goes out."""
    return (day_of(stamp_ms, reset_hour) + 1) * DAY_MS + hour_of(reset_hour) * HOUR_MS


def hour_of(value) -> int:
    """An hour of the day, whatever was typed into the box. Out of range is 0."""
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return 0
    return hour if 0 <= hour <= 23 else 0


class Item:
    """One errand of the day: what it is, what plays it, and when it was last done."""

    __slots__ = ("uid", "title", "scenario", "done_day")

    def __init__(self, title: str, scenario: str = "", uid: str = "",
                 done_day: "int | None" = None) -> None:
        self.uid = uid or uuid.uuid4().hex[:8]
        self.title = title
        #: The name of an `actions/*.md`, or "" for something the person does by hand.
        self.scenario = scenario or ""
        #: The game-day this was last ticked on; `None` for never.
        self.done_day = done_day

    def is_done(self, day: int) -> bool:
        return self.done_day is not None and int(self.done_day) == int(day)

    def as_dict(self) -> dict:
        return {"uid": self.uid, "title": self.title, "scenario": self.scenario,
                "done_day": self.done_day}

    @classmethod
    def from_dict(cls, raw) -> "Item | None":
        """One saved item, or `None` if what was on disk is not one.

        A profile is a file a person may edit, so anything unreadable is dropped rather
        than raised on: a checklist that refuses to open is worse than one short of a
        line somebody broke by hand.
        """
        if not isinstance(raw, dict):
            return None
        title = str(raw.get("title") or "").strip()
        if not title:
            return None
        day = raw.get("done_day")
        try:
            day = int(day) if day is not None else None
        except (TypeError, ValueError):
            day = None
        return cls(title, str(raw.get("scenario") or ""),
                   uid=str(raw.get("uid") or ""), done_day=day)


class Checklist:
    """The list of a profile's daily errands and the state of today's ticks."""

    def __init__(self, items=None, reset_hour: int = 0) -> None:
        self.items: list = list(items or ())
        self.reset_hour = hour_of(reset_hour)

    # -- the day ------------------------------------------------------------
    def today(self, stamp_ms=None) -> int:
        return day_of(now_ms() if stamp_ms is None else stamp_ms, self.reset_hour)

    def seconds_to_reset(self, stamp_ms=None) -> int:
        stamp = now_ms() if stamp_ms is None else int(stamp_ms)
        return max(0, (next_reset_ms(stamp, self.reset_hour) - stamp) // 1000)

    # -- the list -----------------------------------------------------------
    def get(self, uid: str) -> "Item | None":
        for item in self.items:
            if item.uid == uid:
                return item
        return None

    def add(self, title: str, scenario: str = "") -> "Item | None":
        """Append an errand. A blank title is not one, and is refused."""
        title = (title or "").strip()
        if not title:
            return None
        item = Item(title, scenario)
        self.items.append(item)
        return item

    def remove(self, uid: str) -> bool:
        item = self.get(uid)
        if item is None:
            return False
        self.items.remove(item)
        return True

    def move(self, uid: str, delta: int) -> bool:
        """Shift one errand up or down. A move off either end is simply not made.

        The order is the order the routine is played in, which is why this exists at
        all — a checklist read top to bottom is a checklist that matches what the person
        actually does next.
        """
        item = self.get(uid)
        if item is None:
            return False
        at = self.items.index(item)
        to = at + int(delta)
        if not 0 <= to < len(self.items):
            return False
        self.items.pop(at)
        self.items.insert(to, item)
        return True

    # -- the ticks ----------------------------------------------------------
    def set_done(self, uid: str, done: bool, day=None) -> bool:
        item = self.get(uid)
        if item is None:
            return False
        item.done_day = (self.today() if day is None else int(day)) if done else None
        return True

    def toggle(self, uid: str, day=None) -> "bool | None":
        """Flip one tick and answer with what it now is. `None` — no such item."""
        item = self.get(uid)
        if item is None:
            return None
        today = self.today() if day is None else int(day)
        done = not item.is_done(today)
        item.done_day = today if done else None
        return done

    def clear(self, day=None) -> int:
        """Untick everything ticked today and answer with how many were.

        Only TODAY's ticks: an item stamped with an older day already reads as not done,
        and forgetting the stamp would lose the only record of when it was last played.
        """
        today = self.today() if day is None else int(day)
        cleared = 0
        for item in self.items:
            if item.is_done(today):
                item.done_day = None
                cleared += 1
        return cleared

    def done_count(self, day=None) -> int:
        today = self.today() if day is None else int(day)
        return sum(1 for item in self.items if item.is_done(today))

    # -- what the profile keeps ---------------------------------------------
    def as_config(self) -> dict:
        return {"items": [item.as_dict() for item in self.items],
                "reset_hour": self.reset_hour}

    @classmethod
    def from_config(cls, raw) -> "Checklist":
        raw = raw if isinstance(raw, dict) else {}
        items = []
        seen = set()
        for entry in raw.get("items") or ():
            item = Item.from_dict(entry)
            if item is None:
                continue
            # A hand-edited profile can hold the same uid twice, and then every press
            # would act on whichever came first — the other row would look dead.
            while item.uid in seen:
                item.uid = uuid.uuid4().hex[:8]
            seen.add(item.uid)
            items.append(item)
        return cls(items, raw.get("reset_hour", 0))


def hhmm(seconds) -> str:
    """`5:07` — a countdown short enough to sit at the end of a line."""
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 3600, (seconds % 3600) // 60)
