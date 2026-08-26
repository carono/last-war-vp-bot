"""What the base is holding right now — the live resource stock, one reading, cached.

WHAT IT IS. The numbers along the top of the game's own screen: how much gold, food,
metal and oil this account has, plus every other resource the client counts. They are
what «Состояние» draws on the phone, and they move by themselves while somebody is
looking at the page — nothing here has an «Обновить» to press (#1990).

WHERE THEY COME FROM. `actions/read_base_resources.md`, and nowhere else. Not one line
of Lua is assembled here: this class plays the scenario and reads what it left in
`outcome.ctx.vars`, which is the rule the whole panel is built on (`CLAUDE.md` — the
panel plays scenarios, it does not write them). The scenario asks the game for the NAME
of each resource too, so nothing in the panel ever labels a number.

WHY IT IS CACHED, AND WHAT THE CACHE COSTS. `/api/state` is the panel's most frequent
question — an open page asks it every 2.5 s, per profile — and one play of the read was
measured on the live client at **168 / 219 / 260 ms** end to end (2026-08-26, three runs
through the web API, timed off `debug.log`). Reading on every poll would therefore hold
the game link some 8 % of the time for as long as a page is open, and the link is
exclusive: that is time the schedule, the triggers and the robberies do not get. So the
reading is taken at most once every :data:`TTL_SEC` and every poll in between is served
from memory, which is ~0.7 % of the link.

DEMAND-DRIVEN, NOT A CLOCK. Nothing ticks here. :meth:`state` is what the web route
calls, so a panel nobody is looking at takes no readings at all — and the first look
after a long silence is served stale-then-fresh: the cached rows go out at once and the
refresh lands on the next poll, because a route that waited for the game would block the
page for a quarter of a second.

NOTHING IS WRITTEN DOWN. A balance is worth nothing after a restart — it has moved — so
this is memory and not a table in `panel.db`. The rule in `CLAUDE.md` («Game data lives
only in the database») governs data that is meant to SURVIVE a restart and be read back
whole; a live reading that must be taken again before it can be trusted is the other
kind, exactly like the link's own status. The DAILY TALLY of what came in is a different
question and does have a store (`panel/resource_stats.py`); this one deliberately keeps
no history at all.
"""
from __future__ import annotations

import time

from . import claims

#: The scenario that does the reading. One door, and the panel's only one.
ACTION = "read_base_resources"

#: How stale a reading may be before the next look pays for a fresh one, in seconds.
#: Chosen against the measurement in the module docstring: at 30 s one read of ~0.2 s
#: costs the game link under 1 % of its time, and a stock figure that is half a minute
#: old is still the same number to a person reading it.
TTL_SEC = 30.0

#: How long to wait after a refused play before asking again, in seconds. A refusal is
#: ordinary — the link is exclusive and something else is on it — but `play_async` says
#: so in the log, and at the poll's own pace that is a warning line every 2.5 s for as
#: long as an errand runs, drowning the log somebody opened the page to read.
RETRY_SEC = 15.0

#: How the scenario separates its records and its fields (`read_base_resources.md`).
RECORD_SEP = " #|# "
FIELD_SEP = ";;"


def parse(answer: str) -> list:
    """The scenario's one line turned into rows. A malformed record is skipped.

    Skipped rather than guessed at: the reading is six fields wide and a record that is
    not is a client answering something this panel does not understand — showing five of
    its fields under the sixth one's heading would be a wrong number rather than a
    missing one.
    """
    rows = []
    for record in str(answer or "").split(RECORD_SEP):
        record = record.strip()
        if not record:
            continue
        parts = record.split(FIELD_SEP)
        if len(parts) < 6:
            continue
        try:
            type_id, count, cap, per_hour, base = (int(parts[0]), int(parts[1]),
                                                   int(parts[2]), int(parts[3]),
                                                   int(parts[4]))
        except (TypeError, ValueError):
            continue
        rows.append({"type": type_id, "count": count, "max": cap,
                     "per_hour": per_hour, "base": bool(base),
                     "name": FIELD_SEP.join(parts[5:]).strip()})
    # BIGGEST FIRST, and it is a SORT rather than a filter: a resource the base does not
    # make is still a resource this account holds, and dropping it would be the panel
    # deciding what the game may report.
    #
    # Not «the base's production first», which was tried and is wrong on this client: two
    # of the resources with a production building sit at zero all season (water,
    # electricity) while gold — the largest number on the screen — has no building at
    # all, so that order opened the card with two zeros and buried what somebody came to
    # look at. Size answers the question «what have I got» without the panel having any
    # opinion about which resource matters. Ties break on the base's own production and
    # then on the game's type order, so a card of zeros still comes out in a stable
    # order rather than shuffling between polls.
    rows.sort(key=lambda row: (-row["count"], 0 if row["base"] else 1, row["type"]))
    return rows


class BaseResources:
    """One profile's live stock: the cache, and the rule for refreshing it."""

    def __init__(self, rt, clock=time.time) -> None:
        self._rt = rt
        # WHAT THE TIME IS, as a callable: a test drives the TTL and the age without
        # sleeping, and nothing here has a clock of its own to disagree with the route's.
        self._clock = clock
        self._rows: list = []
        self._at = 0.0                   # when the rows were read, 0 = never
        self._reading = False            # a play is in flight
        self._failed = False             # the last play answered nothing
        self._hold_until = 0.0           # a refusal backs off until then

    # -- what the route draws -----------------------------------------------
    def state(self, now: float | None = None) -> dict:
        """The rows as they stand, and a refresh booked if they are stale.

        Never blocks and never touches the game on the calling thread: the play is handed
        to a worker by :meth:`~panel.runtime.host.PanelRuntime.play_async`, and this
        answers with whatever is already in memory.

        The play goes in at :data:`~panel.runtime.claims.DETACHED` — below every ordinary
        errand — because it is a page being looked at and nothing else: a stock figure is
        never worth making a robbery or a rally join wait for it.
        """
        now = self._clock() if now is None else now
        self._maybe_refresh(now)
        return {"rows": [dict(row) for row in self._rows],
                # Seconds since the reading was taken, so the page can say «полминуты
                # назад» in its own language. -1 = nothing has been read yet, which is
                # what a page draws as «читаю» rather than as a stock of zero.
                "age": round(now - self._at, 1) if self._at else -1,
                "reading": self._reading}

    # -- the refresh ---------------------------------------------------------
    def _maybe_refresh(self, now: float) -> None:
        if self._reading or now < self._hold_until:
            return
        if self._at and now - self._at < TTL_SEC:
            return
        # THE LINK IS EXCLUSIVE AND SOMETHING ELSE IS ON IT. Asked here rather than left
        # to the claim, for the same reason as the gate below: the refusal is a warning
        # line, and this poll would write one every 2.5 s for the length of an errand.
        try:
            if self._rt.game.busy:
                self._hold_until = now + RETRY_SEC
                return
        except Exception:                # noqa: BLE001 — an unreadable link is not
            return                       #   a licence to press either
        # ASKED BEFORE IT IS PLAYED, and silently. `play_async` gates too and says so in
        # the log — which for a poll this regular would be a refusal line every half
        # minute for as long as a stopped profile's page is open, drowning the log the
        # person opened the page to read.
        try:
            if self._rt.gate.blocks(ACTION, human=False):
                return
        except Exception:                # noqa: BLE001 — a gate that cannot answer
            return                       #   is not a licence to press
        self._reading = True
        started = self._rt.play_async(ACTION, tag="resources", human=False,
                                      priority=claims.DETACHED,
                                      on_result=self._from_run)
        if not started:
            # Refused before it reached a worker (busy, held, no client). Not a reading
            # and not a failure to remember — but not something to retry two and a half
            # seconds later either, or the refusal itself becomes the log.
            self._reading = False
            self._hold_until = self._clock() + RETRY_SEC

    def _from_run(self, outcome) -> None:
        """The play came back: keep what it read, or keep the old rows and say so."""
        self._reading = False
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        rows = parse(got.get("resources", ""))
        if not rows:
            # A CLIENT THAT ANSWERED NOTHING IS NOT A BASE WITH NOTHING ON IT. The old
            # rows stay on screen with their age climbing, which is the honest picture:
            # «this is what it was, and it has not been re-read since».
            self._failed = True
            return
        self._failed = False
        self._rows = rows
        self._at = self._clock()
