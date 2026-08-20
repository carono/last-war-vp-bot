"""WHAT EACH RECEIVER WAS GIVEN AND WHAT BECAME OF IT — the ledger a loss is named from.

WHY THIS EXISTS (#1523). The operator's report was one sentence and it named a class
rather than a page: «обход карты работает, но не все монстры добавляются в грид, события
проглатываются и не обрабатываются. Это вообще повсеместная проблема.» Every attempt to
answer it ran into the same wall — a receiver that drops what it is given looks exactly
like a map that had nothing on it. The capture says how many tiles it decoded, the
listener grid says how many lines came through, and then there is a silence in the middle
where a number should be: **how many of them the panel actually took**.

So every receiver in the panel keeps a row here, and the row is four numbers:

* **seen** — handed to the receiver. Not what the wire carried: what reached the panel's
  own door.
* **kept** — merged into a model, written to a store, drawn. The thing the person asked
  for when they pressed the button.
* **dropped** — deliberately let go, WITH A REASON. A plain tile among starred ones, a
  row on our own server, a level outside the filter: all legitimate, all counted, none of
  them a bug. A drop is only honest when it can be named.
* **lost** — accepted and then thrown away for a reason that is NOT about the event: the
  tab was shut, the panel was busy, the reader raised. **This is the number the report was
  about, and the rule is that it stays at zero.** A receiver that cannot process something
  now queues it; one that queues nothing and drops instead says so here, loudly, where
  «Занятость» draws it.

THE RULE THIS MEASURES, in one sentence: *an accepted event is processed or queued, never
discarded.* #1416 wrote it for the orders — a refused gate parks the fire and asks again —
and this is the same rule for the RECEIVING half. A receiver may legitimately decline an
event (that is `dropped`, with its reason); what it may not do is fail to handle one and
say nothing.

WHAT IT COSTS. A dict lookup and four integer adds under a lock held for microseconds. No
Tk, no I/O, no game — the same three rules `panel/runtime/busy.py` is written under, and
for the same reason: this is read while diagnosing a panel that is already struggling, and
a debugger that joins the queue it is measuring is worse than none.

WHOSE IT IS. **A profile's own**, like the log and the schedule and everything else an
account accumulates (`CLAUDE.md`, «A profile is a whole panel of its own»). It hangs off
`PanelRuntime`, so four open accounts have four ledgers and no row of one can be read as
the other's.

NOT ONE WORD OF IT IS A SENTENCE. Every field is a number or a key; whoever draws it says
the words in whatever language that window is showing.

Read with no window at all:

    python3 tests/test_panel_intake.py
"""
from __future__ import annotations

import threading
import time

#: The reason a `lost` is recorded under when the caller does not name one. A loss with
#: no reason is still a loss, and refusing to record it because the caller was lazy is
#: precisely the silence this module exists to end.
UNKNOWN = "unknown"

#: How long a receiver may say nothing before the row is worth a second look. Same
#: number, and the same caveat, as `busy.LISTENER_QUIET_SEC`: a quiet map genuinely
#: produces nothing, so this colours a row rather than deciding anything.
QUIET_SEC = 300.0


class Counter:
    """One receiver's four numbers, its reasons, and when it last heard anything."""

    __slots__ = ("name", "seen", "kept", "dropped", "lost", "last", "last_in",
                 "reasons", "losses")

    def __init__(self, name: str) -> None:
        self.name = str(name)
        self.seen = 0
        self.kept = 0
        self.dropped = 0
        self.lost = 0
        #: `time.monotonic()` of the last time anything at all was recorded, `0.0` for
        #: never — the same shape `busy.listeners` uses, so the two grids read alike.
        self.last = 0.0
        #: …and the last time something actually ARRIVED (`seen`), which is not the same
        #: question (#1549). A receiver polled every twenty seconds with the client in
        #: the base records a `dropped` every tick, so `last` says «heard from a second
        #: ago» about a page nothing has reached for an hour. The flow strip reads THIS
        #: one, and a badge that said otherwise would be the same lie the strip exists to
        #: end.
        self.last_in = 0.0
        #: `reason -> count` for the deliberate drops, and separately for the losses.
        #: Two dicts rather than one because the two answer different questions: the
        #: first is «what is this receiver filtering out», the second is «what is broken».
        self.reasons: dict = {}
        self.losses: dict = {}

    def as_row(self, now: float) -> dict:
        return {"what": self.name,
                "seen": self.seen, "kept": self.kept,
                "dropped": self.dropped, "lost": self.lost,
                "since": (now - self.last) if self.last else None,
                "since_in": (now - self.last_in) if self.last_in else None,
                "reasons": dict(self.reasons), "losses": dict(self.losses)}


class Intake:
    """Every receiver's ledger for one profile. Thread-safe, no Tk, no I/O, no game.

    Used through :meth:`at`, which hands out a small recorder bound to one receiver's
    name, so the call at the point of loss reads like the thing it is recording:

        take = rt.intake.at("world.monsters")
        take.seen(len(records))
        take.lost(len(records), "tab_closed")

    A caller with no runtime behind it (a standalone tab, a test) is handed
    :class:`NullIntake` instead, which answers every method and counts nothing — so no
    receiver ever has to ask whether the ledger is there.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict = {}

    # -- recording -----------------------------------------------------------
    def _row(self, name: str) -> Counter:
        row = self._rows.get(name)
        if row is None:
            row = self._rows[name] = Counter(name)
        return row

    def seen(self, name: str, n: int = 1) -> None:
        """``n`` events reached this receiver's door."""
        if n <= 0:
            return
        with self._lock:
            row = self._row(name)
            row.seen += int(n)
            row.last = row.last_in = time.monotonic()

    def kept(self, name: str, n: int = 1) -> None:
        """``n`` of them went into a model, a store or a table."""
        if n <= 0:
            return
        with self._lock:
            row = self._row(name)
            row.kept += int(n)
            row.last = time.monotonic()

    def dropped(self, name: str, n: int = 1, reason: str = UNKNOWN) -> None:
        """``n`` were declined ON PURPOSE, for a reason that is about the EVENT."""
        if n <= 0:
            return
        with self._lock:
            row = self._row(name)
            row.dropped += int(n)
            row.reasons[reason] = row.reasons.get(reason, 0) + int(n)
            row.last = time.monotonic()

    def lost(self, name: str, n: int = 1, reason: str = UNKNOWN) -> None:
        """``n`` were accepted and then thrown away for a reason that is NOT the event's.

        **The number the whole module exists for.** Anything counted here is a bug in the
        receiver, not a fact about the map — so it is recorded even while it is being
        fixed, because a loss nobody can see is one nobody reports.
        """
        if n <= 0:
            return
        with self._lock:
            row = self._row(name)
            row.lost += int(n)
            row.losses[reason] = row.losses.get(reason, 0) + int(n)
            row.last = time.monotonic()

    # -- a recorder bound to one receiver ------------------------------------
    def at(self, name: str) -> "Take":
        return Take(self, name)

    # -- reading -------------------------------------------------------------
    def report(self, now: "float | None" = None) -> list:
        """Every receiver's row, the ones LOSING things first. No words, only numbers."""
        now = time.monotonic() if now is None else now
        with self._lock:
            rows = [row.as_row(now) for row in self._rows.values()]
        rows.sort(key=lambda row: (-row["lost"], row["what"]))
        return rows

    def lost_total(self) -> int:
        """How many events this profile has thrown away — the one-number version."""
        with self._lock:
            return sum(row.lost for row in self._rows.values())

    def clear(self) -> None:
        """Forget everything — another account's receivers are not this one's (#1306)."""
        with self._lock:
            self._rows.clear()


class Take:
    """A recorder bound to one receiver's name, so the call site names it only once."""

    __slots__ = ("_ledger", "_name")

    def __init__(self, ledger, name: str) -> None:
        self._ledger, self._name = ledger, str(name)

    @property
    def name(self) -> str:
        return self._name

    def seen(self, n: int = 1) -> None:
        self._ledger.seen(self._name, n)

    def kept(self, n: int = 1) -> None:
        self._ledger.kept(self._name, n)

    def dropped(self, n: int = 1, reason: str = UNKNOWN) -> None:
        self._ledger.dropped(self._name, n, reason)

    def lost(self, n: int = 1, reason: str = UNKNOWN) -> None:
        self._ledger.lost(self._name, n, reason)


class NullIntake:
    """The ledger a runtime-less caller gets: answers everything, counts nothing.

    So a receiver never writes `if self.rt.intake is not None` — which is the shape that
    lets an instrumented path quietly stop being instrumented.
    """

    def seen(self, name: str, n: int = 1) -> None:
        pass

    def kept(self, name: str, n: int = 1) -> None:
        pass

    def dropped(self, name: str, n: int = 1, reason: str = UNKNOWN) -> None:
        pass

    def lost(self, name: str, n: int = 1, reason: str = UNKNOWN) -> None:
        pass

    def at(self, name: str) -> "Take":
        return Take(self, name)

    def report(self, now: "float | None" = None) -> list:
        return []

    def lost_total(self) -> int:
        return 0

    def clear(self) -> None:
        pass


def of(rt) -> "Intake | NullIntake":
    """The ledger belonging to ``rt`` — a real one, or the counting-nothing stand-in."""
    found = getattr(rt, "intake", None)
    return found if found is not None else NullIntake()
