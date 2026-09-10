"""The day's tally of what came in — and, kept apart, what the BASE paid (#2743).

WHY IT IS NOT ON A TAB. It was: «Статистика» owned the tracker, the day-keyed store and
the trigger that fills them. That tab is `IN_DEVELOPMENT`, so it is not built at all
unless «Разработка» is on — and a trigger whose work is a tab's method is dead while the
tab is absent. Measured on the live panel of 2026-09-10: `resource_tracker` switched ON
in all three profiles, and not one `resource_stats` row in the whole database. The
tracker had never written anything, and nothing anywhere said so. The same shape as the
ghost order behind a dev-only tab (#2010): an ability the profile cannot reach is an
ability nobody has.

So the book belongs to the RUNTIME, one per profile like the stock reading beside it
(`panel/runtime/resources.py`), and the trigger's handler is bound by `Schedule`
regardless of which tabs a profile has. «Статистика» draws what this holds and owns
nothing.

TWO BOOKS, ONE PUSH. Everything that raises a balance lands in the whole-day tally —
a truck coming home, a gift, a chest, a robbery. The card of «Сбор ресурсов» asks the
narrower question «сколько собрано С БАЗЫ сегодня», and there is no field on the wire
saying where a gain came from: the balance push says a number moved. So the source is
the panel's own knowledge of what it was DOING — `collect_base_resources` running now,
or having run within :data:`COLLECT_CLAIM_SEC` of the moment the gain could first be
priced. A harvest made by a thumb in the game is therefore in the whole-day tally alone,
which is a gap and not a lie.

NOTHING HERE RUNS ON A CLOCK. The only thing that ever calls :meth:`track` is the
game's own «your balance changed» push, through the `resource_tracker` trigger
(`CLAUDE.md`, «Read once, then LISTEN»).
"""
from __future__ import annotations

import time

from .. import resource_stats as statsmod
from . import intake as intakemod
from . import reads

#: The receiver «Занятость» draws for this door (`panel/runtime/intake.py`, #1523). The
#: name it has always had, because the ledger's history is per receiver.
INTAKE_GAINS = "stats.gains"

#: The scenario whose run means a gain came off the base's own production buildings.
COLLECT_ACTION = "collect_base_resources"

#: HOW LONG A HARVEST'S GAINS GO ON ARRIVING once the first of them has been priced, in
#: seconds. One press sends a collect per ready building — 36 of them, live — and the
#: client answers with a burst of balance pushes (`docs/research/resource-collection.md`).
#: The whole burst is one harvest and must be counted as one.
COLLECT_WINDOW_SEC = 45.0

#: HOW LONG A COLLECT MAY WAIT TO BE PRICED, in seconds — and why this is not the same
#: number (#2743, measured live). A gain is priced by DIFFING the balance the panel has
#: read, and that reading is served stale on purpose: `BaseResources` answers out of its
#: cache and refreshes behind the answer. Live, the run finished at 22:32:47, the tracker
#: read at 22:32:53 and still saw the pre-harvest numbers, and the fresh reading landed
#: some fifteen seconds later — so a window measured from the RUN threw the harvest away.
#: The claim is therefore armed by the run and spent by the first gain priced after it,
#: within three minutes. Its cost when it is wrong is one mis-attributed gain — a truck
#: that came home in the same three minutes — and never a lost one: the whole-day tally
#: has every gain either way.
COLLECT_CLAIM_SEC = 180.0

#: What is said on the bus when a gain has been written down, so a page showing the
#: tally repaints without asking anything.
GAINED = "resources.gained"


class ResourceBook:
    """One profile's two day-keyed tallies, and the push that fills them."""

    def __init__(self, rt) -> None:
        self.rt = rt
        self._stats = None
        self._base = None
        # The last balance seen, so a push's gain is `current - last`. Empty until the
        # first read establishes a baseline — no gain is counted then, because there is
        # nothing to diff against.
        self._last: dict = {}
        # When `collect_base_resources` was last seen running — the ARM — and when the
        # first gain after it was priced, which opens the burst window.
        self._collect_at = 0.0
        self._claim_from = 0.0

    # -- the two books -------------------------------------------------------
    def _path(self) -> "str | None":
        try:
            return self.rt.profiles.resource_stats_json()
        except Exception:                # noqa: BLE001 — a path, never the gain
            return None

    def _load(self) -> None:
        self._stats = statsmod.load_stats_from_store(self.rt.store, self._path())
        self._base = statsmod.load_stats_from_store(
            self.rt.store, None, statsmod.BASE_BLOB)

    @property
    def stats(self):
        """The whole-day tally — everything that raised a balance."""
        if self._stats is None:
            self._load()
        return self._stats

    @property
    def base(self):
        """The same shape, holding only what the base's own buildings paid."""
        if self._base is None:
            self._load()
        return self._base

    def refresh(self) -> None:
        """Re-read both books from the database."""
        self._load()

    def on_profile_switch(self) -> None:
        """Another account's numbers are not this one's — and neither is its baseline."""
        self._stats = self._base = None
        self._last = {}
        self._collect_at = self._claim_from = 0.0

    # -- the day, and where a gain came from ---------------------------------
    def day(self) -> "str | None":
        """The GAME day a gain belongs to, or `None` when nobody can say.

        `CLAUDE.md`, «A DAY'S STATISTIC IS A HISTORY»: the boundary that zeroes a counter
        is the warzone's own reset and not this computer's midnight, so it is the one
        that names the row. A profile that has never had a client to ask answers `None`,
        and the tally then falls back on the PC's date rather than losing the gain.
        """
        try:
            return self.rt.day.day_key()
        except Exception:                # noqa: BLE001 — a key, never the gain
            return None

    def note_running(self, now: "float | None" = None) -> None:
        """ARM the claim if the base harvest is on the client right now.

        Called on EVERY balance push, gain or no gain, and that is the point (#2743): a
        push that could not be priced — the reading behind it was stale — is the very
        push that arrives while the harvest is running. Arming only when a gain is
        priced means the harvest is never seen at all, which is what the live run of
        22:32 did.
        """
        now = time.time() if now is None else float(now)
        try:
            names = {getattr(run, "name", "") for run in self.rt.interrupts.running()}
        except Exception:                # noqa: BLE001 — a source, never the gain
            return
        if COLLECT_ACTION in names:
            self._collect_at = now

    def from_base(self, now: "float | None" = None) -> bool:
        """Was this gain the base's own harvest? — the panel's own knowledge, free.

        Nothing on the wire says where a gain came from, so the only honest answer is
        what the panel was DOING. Two clocks, and the reason for the second is measured
        rather than assumed (:data:`COLLECT_CLAIM_SEC`): the run ARMS a claim
        (:meth:`note_running`), the first gain priced after it SPENDS the claim, and the
        rest of that burst rides the window the spending opened. A harvest made by a
        thumb in the game arms nothing and is in the whole-day tally alone — a gap, not
        a lie.
        """
        now = time.time() if now is None else float(now)
        self.note_running(now)
        # The rest of a burst that has already been claimed.
        if self._claim_from and now - self._claim_from <= COLLECT_WINDOW_SEC:
            return True
        if self._collect_at and now - self._collect_at <= COLLECT_CLAIM_SEC:
            # The first gain after the run — spend the arm and open the window.
            self._claim_from = now
            self._collect_at = 0.0
            return True
        return False

    # -- the trigger's handler ------------------------------------------------
    def track(self) -> None:
        """One balance-changed push: read the balance and tally what went up.

        The gain is `current - last` per resource (positive only): the push says a
        balance moved, not by how much, so the tracker diffs. The first read of a session
        is a baseline.
        """
        take = intakemod.of(self.rt).at(INTAKE_GAINS)
        take.seen()
        # ARMED ON EVERY PUSH, before anything can return (#2743). A push whose reading
        # was stale prices no gain and is exactly the one that arrives while the harvest
        # is running: arming it here is what lets the gain that lands fifteen seconds
        # later still be credited to the base.
        self.note_running()
        current = reads.resource_balance(self.rt)
        if not current:
            # A PUSH THAT COULD NOT BE PRICED IS A LOSS, not an empty answer (#1523).
            # The push says a balance MOVED; the amount only exists in the reading taken
            # right after it, so a read that failed takes the gain with it and no later
            # read can recover it.
            take.lost(1, reason="no_reading")
            return
        gains = statsmod.positive_deltas(current, self._last)
        self._last = current
        if not gains:
            # The baseline read of a session, or a push about something that did not go
            # up. Both are answers rather than faults — declined, with the reason.
            take.dropped(1, reason="no_gain")
            return
        take.kept()
        day = self.day()
        self._stats = self.stats.add(gains, day)
        statsmod.save_stats_to_store(self.rt.store, self._stats)
        # …AND THE SAME GAINS AGAIN, in the base's own book, when the panel knows this
        # was its harvest. Two books rather than one column with a flag: the card of
        # «Сбор ресурсов» asks one question and «Статистика» asks the other, and neither
        # has to filter the other's rows.
        if self.from_base():
            self._base = self.base.add(gains, day)
            statsmod.save_stats_to_store(
                self.rt.store, self._base, statsmod.BASE_BLOB)
        try:
            self.rt.say("trigger", "triggers.log.resource_gain",
                        what=", ".join(f"{k} +{v}" for k, v in gains.items()))
        except Exception:                # noqa: BLE001 — a line, never the gain
            pass
        try:
            self.rt.bus.publish(GAINED, dict(gains))
        except Exception:                # noqa: BLE001 — a repaint, never the gain
            pass


def register(schedule) -> None:
    """Bind the tracker to the `resource_tracker` trigger, whatever tabs this profile
    has. Called once, from `Schedule` — the same door `panel/runtime/panel_orders.py`
    uses for an ability that belongs to no tab."""
    book = getattr(schedule.rt, "resource_book", None)
    if book is None:
        return
    schedule.bind("resource_tracker", book.track, needs_game=True)
