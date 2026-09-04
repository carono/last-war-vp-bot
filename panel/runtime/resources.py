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

THE WIRE IS THE UPDATE, NOT A CLOCK (#1990, second pass). The balance is HELD BY THE
CLIENT: it is read from the server once, at login (`InitFromNet`), and after that only an
event moves it — every one of which the game announces as `push.resource.item.update`.
That was measured, not assumed: over 45 s of an idle base the client's own writers fired
**zero** times and the numbers came back byte-identical, and one harvest fired
`UpdateResource` **25** times and moved metal by **+718 326**
(`docs/research/base-resources.md` §2a). So this subscribes to that push on the profile's
shared ear (`panel/runtime/wire.py`) and re-reads when it is told to, which is exact
rather than approximate — a poll can only ever be late or wasted.

WHAT A READ COSTS, AND WHY THERE IS STILL A NET. One play was measured on the live client
at **168 / 219 / 260 ms** end to end, and after the pending-storage sweep was added,
**175 / 193 / 195 / 209 ms** — the cost is the panel↔VM round trip, not the work in the
chunk. The link is exclusive, so that is time the schedule and the robberies do not get.
`/api/state` is asked every 2.5 s by an open page, per profile: reading per poll would
hold the link some 8 % of the time. Hence :data:`MIN_GAP_SEC` under the pushes — a
harvest is a BURST of them — and :data:`SAFETY_SEC`, a five-minute floor for what an ear
cannot hear: no capture on this machine, traffic that could not be narrowed to this
profile, a change no push covers.

DEMAND-DRIVEN, NOT A CLOCK. Nothing ticks here except the chain that gives the capture
back. :meth:`state` is what the web route calls, so a panel nobody is looking at
subscribes to nothing and reads nothing — and the first look after a long silence is
served stale-then-fresh: the cached rows go out at once and the refresh lands on the next
poll, because a route that waited for the game would block the page for a quarter of a
second.

NOTHING IS TRUSTED FROM A CLIENT THAT HAS NOT LOGGED IN. That gate is in the SCENARIO,
where it costs nothing: the same chunk reads the game's own clock first and answers an
empty string when it is not an epoch. A client at the login screen answers every question
plausibly and wrongly (`tools/lib/game_clock.py`), and a stock of zeros drawn confidently
on the front page is exactly that failure again.

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

#: THE SAFETY NET, in seconds — how stale a reading may get with no push to say it has
#: moved. Not the update rate: the update is the wire (see :meth:`_on_push`).
#:
#: Five minutes rather than the half minute this started at, and the licence for that is
#: a measurement, not optimism. The balance is HELD BY THE CLIENT and only ever moved by
#: an event: over 45 s of an idle base the client's own writers fired zero times and the
#: numbers came back byte-identical, and one harvest fired `UpdateResource` 25 times and
#: moved metal by +718 326 (docs/research/base-resources.md §2a). A number that cannot
#: drift on its own does not need watching — it needs telling.
SAFETY_SEC = 300.0

#: The floor between two reads, in seconds. A single harvest emits a burst of
#: `push.resource.item.update` — 25 collect replies, several pushes — and the client is
#: still digesting the cascade while they arrive (docs/research/resource-collection.md).
#: One read after the burst is the whole point; twenty-five is the bug that file warns
#: about.
MIN_GAP_SEC = 3.0

#: How long after the last look the ear is kept, in seconds. Checked on a chain of its
#: own so a page somebody closed stops paying for a capture.
WATCH_IDLE_SEC = 120.0

#: The ticker chain that does that check.
WATCH_CHAIN = "resources.watch"

#: How long to wait after a refused play before asking again, in seconds. A refusal is
#: ordinary — the link is exclusive and something else is on it — but `play_async` says
#: so in the log, and at the poll's own pace that is a warning line every 2.5 s for as
#: long as an errand runs, drowning the log somebody opened the page to read.
RETRY_SEC = 15.0

#: The longest a refusal may push the next attempt out to, in seconds.
#:
#: A refusal backs off — the same errand is usually still holding the link a moment
#: later, and asking every fifteen seconds writes the refusal into the log more often
#: than the reading it is failing to take. It backs off to a CEILING and no further:
#: the next attempt is still made, on the next look or the next thing the game says,
#: and a card that has given up for good is exactly the bug this whole thread is about.
RETRY_MAX_SEC = 120.0

#: How long a play may be «in flight» before the panel stops believing in it.
#:
#: THE RESERVATION MUST HAVE A WAY OUT (#2418). `self._reading` is set before the play
#: and cleared by its result — and if that result never comes (the play raised on its
#: worker, the callback was dropped, the link went away mid-run) the flag stays True and
#: `_maybe_refresh` returns at its first line FOR EVER. That is what made the card blank
#: from 2 September: not one refusal, but a refusal that left a state with no exit.
#: Nothing polls for this; the next look simply stops believing a play this old.
READ_LOST_SEC = 90.0

#: How the scenario separates its records and its fields (`read_base_resources.md`).
RECORD_SEP = " #|# "
FIELD_SEP = ";;"

#: Resource type -> the sprite the GAME names for it, read off the client's own config
#: and kept in `tools/data/resource_icons.json` the way `errand_icons.json` is. Loaded
#: once: it is a table of the game's, identical on every machine and for every profile.
_ICONS: "dict | None" = None


def _icon_for(type_id: int) -> str:
    """The sprite name for this resource, or ``""`` when there is none to serve.

    Two things have to be true: the game names a picture for the type, and that picture
    was actually extracted on THIS machine (`tools/extract_item_icons.py`). Neither is
    assumed — a resource with no sprite draws its own name, and never another
    resource's art.
    """
    global _ICONS
    if _ICONS is None:
        _ICONS = {}
        try:
            import json
            import os
            here = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            raw = os.path.join(here, "tools", "data", "resource_icons.json")
            with open(raw, encoding="utf-8") as handle:
                _ICONS = dict((json.load(handle) or {}).get("icons") or {})
        except Exception:                # noqa: BLE001 — no map is no pictures
            _ICONS = {}
    stem = str(_ICONS.get(str(type_id)) or "")
    if not stem:
        return ""
    try:
        import item_icons
        return stem if item_icons.raw_named(stem) else ""
    except Exception:                    # noqa: BLE001 — nothing extracted, no picture
        return ""


def parse(answer: str) -> list:
    """The scenario's one line turned into rows. A malformed record is skipped.

    Skipped rather than guessed at: the reading is seven fields wide and a record that is
    not is a client answering something this panel does not understand — showing six of
    its fields under the seventh one's heading would be a wrong number rather than a
    missing one.
    """
    rows = []
    for record in str(answer or "").split(RECORD_SEP):
        record = record.strip()
        if not record:
            continue
        parts = record.split(FIELD_SEP)
        if len(parts) < 7:
            continue
        try:
            type_id, count, cap, per_hour, base, pending = (
                int(parts[0]), int(parts[1]), int(parts[2]),
                int(parts[3]), int(parts[4]), int(parts[5]))
        except (TypeError, ValueError):
            continue
        rows.append({"type": type_id, "count": count, "max": cap,
                     "per_hour": per_hour, "base": bool(base), "pending": pending,
                     # THE GAME'S OWN PICTURE FOR THIS RESOURCE (#2418), or "" — the
                     # sprite the client's own config names, resolved against what has
                     # actually been extracted on THIS machine. Nothing stands in for a
                     # missing one: a resource with no sprite shows its name.
                     "icon": _icon_for(type_id),
                     "name": FIELD_SEP.join(parts[6:]).strip()})
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
        #: When it went in, so a play whose answer never arrives cannot wedge the card
        #: (see :data:`READ_LOST_SEC`). Monotonic, like every other clock here.
        self._reading_at = 0.0
        #: How many times in a row the link refused. Decides the backoff and nothing
        #: else; a single success clears it.
        self._refusals = 0
        self._failed = False             # the last play answered nothing
        self._hold_until = 0.0           # a refusal backs off until then
        # THE EAR (`panel/runtime/wire.py`): the unsubscribe while it is up, and the flag
        # its callback sets. `_dirty` starts True because nothing has been read yet.
        self._off = None
        self._dirty = True
        self._looked_at = 0.0            # when somebody last asked for the card

    # -- what the route draws -----------------------------------------------
    def state(self, now: float | None = None) -> dict:
        """The rows as they stand, and a refresh booked if they are stale.

        Never blocks and never touches the game on the calling thread: the play is handed
        to a worker by :meth:`~panel.runtime.host.PanelRuntime.play_async`, and this
        answers with whatever is already in memory.

        The play WAITS ITS TURN when somebody asked for it — a page was opened, or the
        game said a balance moved — and is refused when only the safety clock wants it.
        It used to be DETACHED in both cases, which sounds humble and is not: a DETACHED
        play cannot queue at all, so on a panel whose link is busy it is refused every
        time and the card is blank for days (#2418).
        """
        now = self._clock() if now is None else now
        self._looked_at = now
        self._listen()
        self._maybe_refresh(now)
        return {"rows": [dict(row) for row in self._rows],
                # Whether the card is being kept up to date BY THE WIRE rather than by
                # the safety net. A page that says «прочитано 4 минуты назад» beside a
                # live ear is telling the truth twice: nothing has moved, and we would
                # have heard it if it had.
                "watching": self._off is not None,
                # Seconds since the reading was taken, so the page can say «полминуты
                # назад» in its own language. -1 = nothing has been read yet, which is
                # what a page draws as «читаю» rather than as a stock of zero.
                "age": round(now - self._at, 1) if self._at else -1,
                "reading": self._reading}

    def cached(self, now: float | None = None) -> dict:
        """What is already in memory — no ear raised, no refresh booked (#2019).

        :meth:`state` is the card's door and does two things besides answering: it
        subscribes to the wire (which spawns a capture child) and it books a refresh when
        the rows are stale. Both are right for the page the reading is FOR, and both
        would be wrong for a passer-by — the timers page draws a line of «ждёт сбора»
        under one errand, and a page of blocks must not be the reason a profile starts
        listening or the reason the link is taken.

        So this is a look and nothing else. It answers what the last read left, with its
        age, and `age` of -1 means «nothing has ever been read» — which the caller draws
        as no line at all rather than as a stock of zero.
        """
        now = self._clock() if now is None else now
        return {"rows": [dict(row) for row in self._rows],
                "age": round(now - self._at, 1) if self._at else -1}

    # -- the ear -------------------------------------------------------------
    def _listen(self) -> None:
        """Subscribe to «your balance changed», once, on the profile's shared ear.

        `push.resource.item.update` is the game's own announcement that a balance moved,
        and it is the ONLY thing that can move one — so this is the update, and the
        safety net above is only there for what an ear cannot hear (no capture on this
        machine, a client whose traffic could not be narrowed, a change the push does not
        cover).

        LAZY, because the ear is a capture process: `WireHub` spawns the child on the
        first subscription and stops it with the last, so a panel nobody looks at pays
        nothing (`panel/runtime/wire.py`). It goes up when the card is first asked for
        and comes down when nobody has asked for :data:`WATCH_IDLE_SEC`.
        """
        if self._off is not None:
            return
        try:
            self._off = self._rt.wire.subscribe("push.resource.item.update",
                                                self._on_push)
        except Exception:                # noqa: BLE001 — no ear is not no card
            self._off = None
            return
        # …and the chain that takes it down again. On the runtime's own ticker, which is
        # the window's `after` queue or a thread of its own in a panel with no window —
        # this must work headless, and #1976 is the task where assuming otherwise cost a
        # whole feature.
        try:
            self._rt.tick.arm(WATCH_CHAIN, 30_000, self._watch_tick)
        except Exception:                # noqa: BLE001 — an unarmed chain only means
            pass                         #   the ear lives as long as the profile

    def _watch_tick(self) -> None:
        """Still being looked at? If not, give the capture back."""
        if self._clock() - self._looked_at <= WATCH_IDLE_SEC:
            return
        off, self._off = self._off, None
        try:
            self._rt.tick.disarm(WATCH_CHAIN)
        except Exception:                # noqa: BLE001
            pass
        if off is not None:
            try:
                off()
            except Exception:            # noqa: BLE001 — a deaf ear is not a fault
                pass

    def _on_push(self, _command: str = "") -> None:
        """The game says a balance moved. Runs on the CHILD'S READER THREAD.

        A flag and nothing else — no read, no Tk, no lock held for longer than a store.
        The read is taken by whichever poll comes next, which is at most 2.5 s away while
        somebody is looking, and the burst behind a harvest collapses into one because of
        :data:`MIN_GAP_SEC`.
        """
        self._dirty = True

    # -- the refresh ---------------------------------------------------------
    def _maybe_refresh(self, now: float) -> None:
        if self._reading:
            # A PLAY IN FLIGHT — unless it has been «in flight» so long that believing
            # in it is the bug (#2418). Then the reservation is dropped and this look is
            # allowed to ask again; the stale play, if it is somehow still alive, lands
            # on `_from_run` and is simply a reading like any other.
            if now - self._reading_at < READ_LOST_SEC:
                return
            self._reading = False
        if now < self._hold_until:
            return
        if self._at and now - self._at < MIN_GAP_SEC:
            return
        # THE WIRE DECIDES, and the clock is only the fallback: a balance the game has
        # not announced a change to has not changed (§2a of the research), so a card that
        # re-read every half minute was paying for the same nine numbers all evening.
        if self._at and not self._dirty and now - self._at < SAFETY_SEC:
            return
        # WHY THIS READ MAY WAIT, AND WHEN (#2418).
        #
        # It used to give up here: «the link is exclusive and something else is on it»,
        # so the card held off and tried again in fifteen seconds. That was written when
        # a VM call was expensive, and it had a consequence nobody measured until the
        # person asked why «Профиль» was blank — on the live panel timers, rallies and
        # sweeps hold the link almost continuously, so the read was refused every single
        # time it was attempted and «запас базы» said «не прочитано» FROM 2 SEPTEMBER.
        # A reading that is always refused is not a cheap reading; it is no reading, and
        # it is silent about it.
        #
        # Two things changed. The call is ten times cheaper and the link measures 8–19%
        # busy, so waiting for a parking moment costs the game almost nothing. And a
        # DETACHED play cannot wait AT ALL by construction: `play_async` only hangs a
        # demand on the door when the priority outranks the run holding the client
        # (`host.py`), and DETACHED outranks nothing — so it is refused rather than
        # queued, for ever, whatever the retry interval says.
        #
        # So the priority says WHO ASKED, which is what a priority is for:
        #
        #   * somebody opened the page, or the GAME said a balance moved — that is a
        #     press by the contract this panel already keeps for every screen
        #     (`web/api.py::_look`), so it goes in as one and waits its turn behind
        #     whatever is parking;
        #   * the safety sweep — a clock, nobody asked — stays DETACHED and is still
        #     refused while the link is busy, which is right: nothing is waiting on it.
        #
        # Nothing here polls the game. The queue is a look and an event, exactly as
        # before; only the answer to «the link is busy» changed, from «never mind» to
        # «then I will wait».
        asked = bool(not self._at or self._dirty)
        if not asked:
            try:
                if self._rt.game.busy:
                    self._hold_until = now + RETRY_SEC
                    return
            except Exception:            # noqa: BLE001 — an unreadable link is not
                return                   #   a licence to press either
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
        self._reading_at = now
        # CLEARED BEFORE THE PLAY, never after: a push that lands while the read is in
        # flight describes a change that read may have missed, and clearing on the way
        # back would throw it away.
        self._dirty = False
        # THE RESERVATION IS GIVEN BACK ON EVERY ROAD OUT OF HERE (#2418) — the refusal,
        # the raise, and the answer (`_from_run`). It used to be given back on two of
        # the three, and the third is not hypothetical: `play_async` reaches a link, a
        # gate and a worker, any of which can raise, and the flag it left behind is
        # checked at the first line of this method. One escape missed is a card that
        # never reads again for as long as the panel runs.
        started = False
        try:
            started = self._rt.play_async(ACTION, tag="resources", human=False,
                                          priority=(claims.HUMAN if asked
                                                    else claims.DETACHED),
                                          on_result=self._from_run)
        except Exception:                # noqa: BLE001 — a play that would not start is
            started = False              #   a reading not taken, never a wedged card
        if not started:
            # Refused before it reached a worker (busy, held, no client). Not a reading
            # and not a failure to remember — and not the end of it either: the next
            # look or the next thing the game says tries again, a little later each time
            # up to a ceiling, so the refusals do not become the log and the card does
            # not quietly give up.
            self._reading = False
            self._dirty = True
            self._refusals += 1
            self._hold_until = self._clock() + min(
                RETRY_SEC * (2 ** min(self._refusals - 1, 8)), RETRY_MAX_SEC)

    def _from_run(self, outcome) -> None:
        """The play came back: keep what it read, or keep the old rows and say so.

        FIRST LINE GIVES THE RESERVATION BACK, whatever the outcome turns out to be
        (#2418): every road out of this method — a good reading, an empty one, a raise
        while parsing — has to leave the card able to read again.
        """
        self._reading = False
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        rows = parse(got.get("resources", ""))
        if not rows:
            # A CLIENT THAT ANSWERED NOTHING IS NOT A BASE WITH NOTHING ON IT. The old
            # rows stay on screen with their age climbing, which is the honest picture:
            # «this is what it was, and it has not been re-read since».
            self._failed = True
            self._dirty = True           # nothing was read, so the change is still owed
            return
        self._failed = False
        self._refusals = 0               # it got through; the backoff starts over
        self._rows = rows
        self._at = self._clock()

    # -- going away ----------------------------------------------------------
    def shutdown(self) -> None:
        """Give the capture back when the profile closes."""
        self._looked_at = 0.0
        self._watch_tick()
