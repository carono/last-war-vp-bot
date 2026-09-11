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
narrower question «сколько собрано С БАЗЫ сегодня», and the balance push does not answer
it: it says a number moved.

WHAT DOES ANSWER IT IS THE GAME'S OWN FRAME (#2746b). Collecting one production building
is `building.production.collect`, one per building — the same frame whether a person taps
the green bubble or the panel plays the sweep — so the ear
(`panel/runtime/wire.py`) hears a harvest WHOEVER made it, and a gain priced inside
:data:`COLLECT_CLAIM_SEC` of one is the base's production. A truck, a gift, a chest and
a robbery are other commands entirely.

This replaces the claim the book was built on and which was wrong in principle — «our
run was playing», which can only ever count the harvests the panel itself made. The
person's words: «Ищи пуши, я могу и в игре руками собрать ресурсы, они должны
учитываться». The run register is kept as the FALLBACK for a profile with no ear: no
capture on this machine, or traffic that could not be narrowed to this account.

NOTHING HERE RUNS ON A CLOCK. Three things fill the book, and every one of them is an
EVENT (`CLAUDE.md`, «Read once, then LISTEN»): the game's own «your balance changed»
push, through the `resource_tracker` trigger; a fresh reading landing; and the harvest
RUN itself starting or ending on the register.

WHY THE THIRD ONE EXISTS (#2746). The person's report: «не может за день быть всего по
миллиону ресурсов, столько в час собирается». Measured on the live panel of 2026-09-11,
the counter was short for two separate reasons, and neither was arithmetic:

* `default` harvested six times between 01:03 and 06:06 and priced NOT ONE of them. Its
  `resource_tracker` listener had died at 00:42 («слушатель завершился»), and the card's
  own reading is demand-driven — nobody had the page open, so the ear was down and no
  reading was ever taken to diff against. The whole day's tally was one hour's worth.
* `sooperj` priced thirteen gains against fifteen harvests, and its base book held 7.66M
  food where the log's own gain lines beside those runs sum to over 11M — the claim was
  SPENT by the first gain of a harvest and every later burst fell outside.

So the run arms the claim through the register (which does not care who pressed), every
gain inside the window is counted rather than only the first, and the end of a run ASKS
for the readings that price it. Nothing polls: a harvest the panel made is a thing the
panel knows it did.
"""
from __future__ import annotations

import time

from .. import resource_stats as statsmod
from . import bus as busmod
from . import intake as intakemod
from . import reads

#: The receiver «Занятость» draws for this door (`panel/runtime/intake.py`, #1523). The
#: name it has always had, because the ledger's history is per receiver.
INTAKE_GAINS = "stats.gains"

#: The scenario whose run means a gain came off the base's own production buildings.
#: A FALLBACK since #2746b: what actually says «this came off the base» is the GAME, on
#: the wire (:data:`COLLECT_COMMAND`). This is what is left when there is no ear — no
#: capture on this machine, traffic that could not be narrowed to this profile.
COLLECT_ACTION = "collect_base_resources"

#: WHAT THE GAME ITSELF SAYS WHEN A PRODUCTION BUILDING IS COLLECTED (#2746b). The
#: person's words: «Ищи пуши, я могу и в игре руками собрать ресурсы, они должны
#: учитываться». They are right, and the claim this book was built on was wrong in
#: principle: «our run was playing» can only ever count the harvests the PANEL made.
#:
#: Collecting one building is one frame — `building.production.collect`, one per
#: building, upstream, and the server answers on the same name
#: (`docs/research/protocol.md`, trapped live while a person tapped the green bubbles by
#: hand). So the ear hears a harvest whoever made it: a thumb on the base screen and the
#: panel's own sweep are the same frame, which is exactly the distinction the card needs
#: and the one the run register cannot make.
#:
#: It is also what makes the SOURCE the game's word rather than the panel's guess: a
#: truck coming home, a gift, a chest and a robbery are other commands entirely, so a
#: gain priced inside this window is the base's production and nothing else's.
COLLECT_COMMAND = "building.production.collect"

#: HOW LONG A HARVEST'S GAINS GO ON ARRIVING once the first of them has been priced, in
#: seconds. One press sends a collect per ready building — 36 of them, live — and the
#: client answers with a burst of balance pushes (`docs/research/resource-collection.md`).
#: The whole burst is one harvest and must be counted as one.
#:
#: IT IS NO LONGER A CLAIM THAT IS SPENT (#2746). It used to be: the FIRST gain priced
#: after a run took the claim, opened this window, and everything that arrived after the
#: window was the day's tally alone. Measured on the live panel of 2026-09-11, that threw
#: away about a third of what the base paid — `sooperj` collected fifteen times and its
#: base book held 7.66M food where the log's own gain lines near those runs sum to over
#: 11M. A harvest's gains arrive in several bursts, and a counter that takes the first
#: and drops the rest is not a counter. So EVERY gain priced inside
#: :data:`COLLECT_CLAIM_SEC` of the run is the harvest's, and this is what each one
#: pushes the window out by — bounded, because a harvest cannot go on arriving for ever.
COLLECT_WINDOW_SEC = 45.0

#: WHEN A READING IS ASKED FOR AFTER A HARVEST, in seconds from the moment the run left
#: the register (#2746). Three of them, because the client answers a harvest with a
#: cascade rather than a number: measured live, a run that ended at 22:32:47 was still
#: unpriced at 22:32:53 and the fresh balance landed some fifteen seconds later.
#:
#: This is the half of the fix that has nothing to do with attribution. The card's door
#: reads on a LOOK or on a push, so a panel nobody has open — whose capture ear is
#: therefore down — harvests the base and takes no reading at all: `default` made six
#: runs between 01:03 and 06:06 on 2026-09-11 and priced none of them. A reading asked
#: for by the run that moved the balance is an EVENT, which is exactly what `CLAUDE.md`
#: («Read once, then LISTEN») asks for and never a poll.
HARVEST_READS = (2.0, 20.0, 45.0)

#: The one-shot chains those readings are booked on (`panel/runtime/tick.py`).
READ_CHAIN = "resources.harvest"

#: THE BOUND ON A HARVEST, in seconds from the run. A cascade that is still arriving
#: past :data:`COLLECT_CLAIM_SEC` keeps the window open (each gain pushes it out by
#: :data:`COLLECT_WINDOW_SEC`), and without a ceiling a busy account whose balance moves
#: every half minute would credit its whole day's trading to the base's card. Ten
#: minutes is far longer than any measured harvest and far shorter than an errand round.
HARVEST_MAX_SEC = 600.0

#: HOW LONG A BUDGET READ OFF A HAND HARVEST STAYS ARMED, in seconds (#2747). A harvest
#: the panel played states its own size in a variable; one made with a thumb states
#: nothing at all, so the budget is taken from the last reading's `pending` on the first
#: collect frame and left alone while the frames keep coming — a sweep of 36 buildings
#: is one harvest and must arm one budget, not 36.
HAND_BUDGET_SEC = 45.0

#: HOW LONG A COLLECT MAY WAIT TO BE PRICED, in seconds — and why this is not the same
#: number (#2743, measured live). A gain is priced by DIFFING the balance the panel has
#: read, and that reading is served stale on purpose: `BaseResources` answers out of its
#: cache and refreshes behind the answer. Live, the run finished at 22:32:47, the tracker
#: read at 22:32:53 and still saw the pre-harvest numbers, and the fresh reading landed
#: some fifteen seconds later — so a window measured from the RUN threw the harvest away.
#: The claim is therefore armed by the run, and every gain priced inside it is that
#: harvest's.
#:
#: IT WAS THREE MINUTES, AND THREE MINUTES IS WIDE ENOUGH TO SWALLOW ANOTHER ERRAND
#: (#2746e). Its cost when it is wrong was written down here as «one mis-attributed gain
#: — a truck that came home in the same three minutes», and that was measured on the live
#: panel of 2026-09-11 and is far dearer than a truck: `collect_base_resources` ran at
#: 08:16:16, `heal_units` opened resource packs to pay for the heal at 08:16:55, and the
#: packs' own gains landed at 08:18:50 and 08:19:19 — 154 s and 183 s after the harvest,
#: inside the claim and inside the burst chain behind it. 32.5M food, 30.8M metal and
#: 23.2M gold of PACKS were credited to the base's card, on a day whose real harvest was
#: about 13M food. The person's complaint was a card that was short; a card that is three
#: times over is the same bug wearing the other face.
#:
#: Sixty seconds is what the measurement supports, and it is affordable because the other
#: half of #2746 removed the reason the window was wide: the run now ASKS for readings at
#: :data:`HARVEST_READS` — 2 s, 20 s and 45 s — so a harvest is priced inside 45 s
#: instead of waiting for whoever next opens a page. Live, the three runs of 08:16, 08:43
#: and 08:44 were priced 0 s, 2 s and 2 s after the run. A cascade that is genuinely
#: still arriving is not cut off by this: every gain pushes the window out by
#: :data:`COLLECT_WINDOW_SEC`, bounded by :data:`HARVEST_MAX_SEC`.
COLLECT_CLAIM_SEC = 60.0

#: WHERE THE GAME'S OWN WORDS FOR THE BASE'S ITEM PAYMENTS ARE KEPT (#2744), so a card
#: drawn before the first reading of a session still has a name and a picture for
#: «Запчасти дрона» instead of an item id. It is what the LAST reading said and nothing
#: else — a label, never a count — and it is refreshed whenever a reading lands.
LABELS_BLOB = "resource_item_labels"

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
        # The last moment the base harvest was known to be ON the client — its start,
        # every moment it was still there, and the moment it left. Never zeroed by a
        # gain: every gain priced within `COLLECT_CLAIM_SEC` of it is that harvest's
        # (#2746), and the burst window only ever pushes it further out.
        self._collect_at = 0.0
        # Whether the run is on the register right now, so the edges can be seen.
        self._collect_live = False
        # When the last gain was credited to the harvest, so a cascade that is still
        # arriving past the claim is still that harvest's — bounded by HARVEST_MAX_SEC.
        self._burst_at = 0.0
        # WHAT THIS HARVEST SAID IT WAS ABOUT TO PAY, per key, minus what has already
        # been credited to the base's book (#2747). A window alone cannot tell a
        # harvest's own cascade from a prize that landed inside it; a budget can, because
        # the game stated the size before a single building was collected.
        self._budget: dict = {}
        # When it was armed, and off which run — so the 36 frames of one sweep arm one
        # budget and a second harvest arms a fresh one.
        self._budget_at = 0.0
        self._budget_seq = None
        # Whether the budget is the harvest's OWN statement (a run read it off the game
        # one line before pressing) or a guess off the last reading (a harvest made with
        # a thumb). An exact budget is a CAP; a guessed one is only a list of the keys
        # the base was known to be holding — see :meth:`_claim` (#2747).
        self._budget_exact = False
        # The run currently doing the harvesting, kept for its `ctx.vars`: the size is
        # read there, and by the time the run leaves the register the handle is gone.
        self._collect_run = None
        self._off = None
        # The register's own «a run started or ended» (`panel/runtime/interrupt.py`) —
        # the ONE signal that does not care who pressed. A run started from the phone,
        # from `/api/actions/run` or by a person's thumb never touches the schedule's
        # record of last runs, so a book armed off that record alone credited nothing to
        # the base for any of them.
        self._off_runs = None
        # …and the first reading of an appearance, which is what a diff needs before it
        # can price anything at all (`watch`).
        self._off_ready = None
        # …and the ear that hears the GAME say a building was collected, by whoever.
        self._off_wire = None
        # The last set of item labels written down, so an unchanged one costs no write.
        self._labels: dict = {}

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
        self._labels = {}
        self._collect_at = self._burst_at = 0.0
        self._collect_live = False
        self._budget = {}
        self._budget_at = 0.0
        self._budget_seq = None
        self._budget_exact = False
        self._collect_run = None

    def clear_day(self, day: "str | None" = None, whole: bool = False) -> dict:
        """Forget ONE game day's row, through the book that owns it (#2747).

        WHY IT CANNOT BE DONE TO THE DATABASE. The book holds both tallies in memory and
        writes the WHOLE object back on the next gain, so a row deleted under a running
        panel comes back the moment the base pays anything — the edit is not refused, it
        is silently undone a minute later. The reset therefore belongs here, where the
        in-memory copy and the row are changed together.

        ``whole`` also clears the day in the everything-that-came-in tally; by default
        only the base's own book is touched, which is what the errand card draws.

        Returns ``{"base": {…}, "stats": {…}}`` — what was actually dropped, so the
        caller can say what it did rather than «готово».
        """
        day = day or self.day() or statsmod._today()
        dropped = {"day": day, "base": dict(self.base.as_dict().get(day) or {}),
                   "stats": {}}
        book = self.base.without(day)
        if book is not self._base:
            self._base = book
            statsmod.save_stats_to_store(self.rt.store, self._base, statsmod.BASE_BLOB)
        if whole:
            dropped["stats"] = dict(self.stats.as_dict().get(day) or {})
            total = self.stats.without(day)
            if total is not self._stats:
                self._stats = total
                statsmod.save_stats_to_store(self.rt.store, self._stats)
        # …and the page repaints off the same signal a gain sends, so nobody has to know
        # a reset is a different kind of change.
        try:
            self.rt.bus.publish(GAINED, {})
        except Exception:                # noqa: BLE001 — a repaint, never the reset
            pass
        return dropped

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
        """ARM the claim if the base harvest is on the client, or has just been.

        TWO WAYS OF SEEING IT, and the second is what the live run of 22:43 needed
        (#2743). A gain is priced when the READING lands, and by then the run is usually
        over — measured: the run ended at 22:43:42 and the reading landed at 22:43:43,
        already off the register. So the panel's own record of when it last ran the
        errand arms the claim too, which is the same fact a second later.

        Called on EVERY balance push and on every reading, gain or no gain: a push that
        could not be priced is exactly the push that arrives while the harvest runs.
        """
        now = time.time() if now is None else float(now)
        try:
            names = {getattr(run, "name", "") for run in self.rt.interrupts.running()}
        except Exception:                # noqa: BLE001 — a source, never the gain
            names = set()
        if COLLECT_ACTION in names:
            self._collect_at = now
            return
        try:
            last = float(self.rt.schedule.store.last_run(COLLECT_ACTION) or 0.0)
        except Exception:                # noqa: BLE001 — a source, never the gain
            return
        if last and now - last <= COLLECT_CLAIM_SEC and last > self._collect_at:
            self._collect_at = last

    def from_base(self, now: "float | None" = None) -> bool:
        """Was this gain the base's own harvest? — the panel's own knowledge, free.

        Nothing on the wire says where a gain came from, so the only honest answer is
        what the panel was DOING: a gain priced while `collect_base_resources` is on the
        client, or within :data:`COLLECT_CLAIM_SEC` of the last moment the GAME said a
        production building was collected (:data:`COLLECT_COMMAND`) — which is the same
        frame for a thumb on the base screen and for the panel's own sweep, so a harvest
        made by hand is counted exactly like one the panel made (#2746b).

        NO CLAIM IS SPENT ANY MORE (#2746). The first gain used to take the arm and
        everything after it fell outside; a harvest arrives in several bursts, so that
        counted one of them and dropped the rest. Now every gain inside the window is
        counted and pushes the window out by :data:`COLLECT_WINDOW_SEC`, so a cascade
        that is still arriving is still the harvest's — bounded by
        :data:`HARVEST_MAX_SEC`, because a cascade cannot go on for ever and a busy
        account's ordinary trading must not be swept into the base's book.
        """
        now = time.time() if now is None else float(now)
        self.note_running(now)
        if self._collect_live:
            self._burst_at = now
            return True
        if not self._collect_at:
            return False
        if now - self._collect_at > HARVEST_MAX_SEC:
            return False
        if now - self._collect_at <= COLLECT_CLAIM_SEC:
            self._burst_at = now
            return True
        # Past the claim, and the cascade is STILL arriving: one burst after another
        # with no gap wider than the burst itself is one harvest, up to the bound above.
        if self._burst_at and now - self._burst_at <= COLLECT_WINDOW_SEC:
            self._burst_at = now
            return True
        return False

    # -- the run that moved the balance --------------------------------------
    def watch(self) -> None:
        """Listen for the harvest starting and ending, whoever started it (#2746).

        Idempotent, and it asks the game nothing: the register tells its listeners that
        something changed and they look. This is what arms the claim now — the schedule's
        record of last runs only knows the runs the SCHEDULE made, so a harvest played
        from the phone or from `/api/actions/run` armed nothing at all.
        """
        if self._off_runs is not None:
            return
        try:
            self._off_runs = self.rt.interrupts.listen(self._runs_changed)
        except Exception:                # noqa: BLE001 — a listener, never the gain
            self._off_runs = None
        # …AND THE GAME'S OWN WORD FOR A HARVEST (#2746b), which is what makes a collect
        # made BY HAND in the game count exactly as the panel's own does. The ear is one
        # capture per profile and this profile already subscribes to
        # `push.resource.item.update` through the `resource_tracker` trigger, so the
        # pattern costs no second child (`panel/runtime/wire.py`).
        if self._off_wire is None:
            try:
                self._off_wire = self.rt.wire.subscribe(COLLECT_COMMAND,
                                                        self._on_collect_wire)
            except Exception:            # noqa: BLE001 — no ear leaves the run register
                self._off_wire = None    #   as the fallback, which is what it is for
        # …AND THE BASELINE, taken when the client gets into the game (#2746). A tally
        # built by DIFFING balances cannot price its first reading — there is nothing to
        # diff it against — so whatever moved between the panel starting and that first
        # reading is swallowed whole. Measured live on 2026-09-11: the panel came up at
        # 06:41, nothing read the balance until a harvest at 07:02:36 asked for one, and
        # that harvest's own gains became the baseline and were counted as zero.
        #
        # `CLAUDE.md` («A STATISTIC IS NOT REFRESHED BY HAND») names the moment for
        # exactly this: `bus.GAME_READY`, the edge where the client is up and logged in,
        # heard again when a lost link comes back — which is the other moment everything
        # this holds may have moved unheard.
        # THREE CHANCES AND NOT ONE (#2747), and it is booked HERE as well as on the
        # edge. Measured on the live panel of 2026-09-11: the panel was restarted at
        # 09:46:38, the first reading of the session did not land until 09:49:02, and
        # the harvest at 09:48:38 — 332K metal, 352K food, 512K hero experience — became
        # the baseline and was counted as zero. A single `ask` at the busiest moment a
        # panel ever has is refused by the link and never asked again, so the baseline
        # rides the same one-shot chain a harvest uses: 2 s, 20 s and 45 s.
        #
        # …and `watch()` books it too, because a panel that comes up to a client ALREADY
        # in the game may have missed the edge entirely — the book subscribes when the
        # schedule is built, and `GAME_READY` is published by a poll that may have run
        # first. The chain is idempotent: three armings of the same names are three
        # readings, not nine.
        self._post(self._book_reads)
        if self._off_ready is not None:
            return
        try:
            self._off_ready = self.rt.bus.subscribe(
                busmod.GAME_READY, lambda _p=None: self._book_reads())
        except Exception:                # noqa: BLE001 — a baseline, never the gain
            self._off_ready = None

    # -- how much of what follows is the harvest's ---------------------------
    def _arm_budget(self, run=None, now: "float | None" = None) -> None:
        """State what this harvest is worth, so nothing else can be charged to it.

        TWO SOURCES, and the first is exact (#2747). A harvest the panel played reads
        `GetBuildingCurrStorage` off every production line BEFORE it presses anything
        and leaves the sum in :data:`~panel.runtime.reads.HARVEST_VAR`; that is the
        number the sweep is about to bring in, per resource and per item. A harvest made
        with a thumb states nothing, so the budget falls back on the last reading's own
        `pending`, which is the same number however stale the reading was.

        Armed ONCE per harvest: the run's sequence number pins the first, and a hand
        sweep of 36 frames is held together by :data:`HAND_BUDGET_SEC`. Re-arming on
        every frame would hand a 36-building sweep 36 budgets, which is the same leak
        the window had, wearing a budget's clothes.
        """
        now = time.time() if now is None else float(now)
        seq = getattr(run, "seq", None) if run is not None else None
        if seq is not None:
            if seq == self._budget_seq:
                return
            raw = (getattr(getattr(run, "ctx", None), "vars", None) or {}).get(
                reads.HARVEST_VAR)
            if raw in (None, ""):
                # The read has not landed yet — the sweep is one line further up. The
                # next collect frame asks again, and the frames are what the sweep makes.
                return
            self._budget_seq = seq
            self._budget = reads.parse_harvest(raw)
            self._budget_exact = True
            self._budget_at = now
            return
        if self._budget_seq is not None and now - self._budget_at <= HARVEST_MAX_SEC:
            # THE TAIL OF A SWEEP THE PANEL ITSELF PLAYED (#2747), and it must not arm a
            # second budget for the same harvest. Measured live: the run of 09:52:13 said
            # it was about to collect 63 687 food and 174 screws; frames kept arriving
            # after it left the register, the fallback re-armed off the reading's own
            # `pending`, and the card ended the minute on 77 332 food and 219 screws —
            # the same over-count the budget exists to stop, let in through the door
            # meant for a thumb. A run's own statement is authoritative for the whole
            # window, and the window is bounded by the same ceiling a harvest is.
            return
        if self._budget and now - self._budget_at <= HAND_BUDGET_SEC:
            return                       # the same hand sweep, still arriving
        self._budget_seq = None
        self._budget = reads.pending_balance(self.rt)
        self._budget_exact = False
        self._budget_at = now

    def _live_collect_run(self):
        """The harvest on the register right now, or `None`."""
        try:
            for run in self.rt.interrupts.running():
                if getattr(run, "name", "") == COLLECT_ACTION:
                    return run
        except Exception:                # noqa: BLE001 — a source, never the gain
            return None
        return None

    def _claim(self, gains: dict) -> dict:
        """What of ``gains`` this harvest still has room for — and spend that room.

        A key the harvest never said it would pay gets nothing, which is the whole point:
        a chest of drone parts opened a minute after the sweep is not the base's
        production however close to it it landed.
        """
        out: dict = {}
        # A BUDGET IS A HARVEST'S, AND A HARVEST ENDS (#2747). The window gate already
        # bounds this, but its clock is moved by every collect frame the ear hears —
        # including another account's tail — so the budget carries its own ceiling.
        if not self._budget or time.time() - self._budget_at > HARVEST_MAX_SEC:
            return out
        for key, amount in (gains or {}).items():
            try:
                left = int(self._budget.get(key, 0))
                amount = int(amount)
            except (TypeError, ValueError):
                continue
            if left <= 0 or amount <= 0:
                continue
            if not self._budget_exact:
                # A HARVEST MADE WITH A THUMB, and the guess is a LIST and not a CAP
                # (#2747). The person collected five hero-experience lines by hand at
                # 10:04:56 on 2026-09-11; the game paid 302 400 and the card wrote down
                # 183 600, because the only statement of size available was a reading
                # taken minutes earlier, when the same five lines held 36 720 each
                # instead of 60 480. Capping by a number that is stale BY CONSTRUCTION
                # loses two fifths of a real harvest, which is far worse than the thing
                # the cap is for.
                #
                # So a guessed budget decides only WHICH keys the base was known to be
                # holding — which is what actually stops a chest of drone parts or an
                # arms-race prize being charged to production — and the amount is taken
                # whole. It is not spent either: one hand sweep answers in several
                # bursts and each of them is the same harvest.
                out[key] = amount
                continue
            take = min(amount, left)
            self._budget[key] = left - take
            out[key] = take
        return out

    def _on_collect_wire(self, _command: str = "") -> None:
        """The game says a production building was collected. ANY thread, no game call.

        One frame per building, so a sweep of 36 says this many times — which costs
        nothing: the arm is a timestamp and the readings are re-armed one-shot chains, so
        the burst collapses into the last frame's booking (`panel/runtime/tick.py`).
        """
        self._collect_at = time.time()
        self._arm_budget(self._collect_run or self._live_collect_run())
        self._post(self._book_reads)

    def _runs_changed(self) -> None:
        """A run started or ended. Called on whatever thread reported it."""
        now = time.time()
        run = self._live_collect_run()
        live = run is not None
        if live:
            # KEPT WHILE IT RUNS, and asked again on every frame: the size is read one
            # line before the sweep presses anything, so the handle has to outlive the
            # moment the run entered the register (#2747).
            self._collect_run = run
            self._arm_budget(run, now)
        if live == self._collect_live:
            return
        self._collect_live = live
        self._collect_at = now
        self._burst_at = 0.0
        if live:
            # CLOSE THE BOOKS ON WHAT CAME BEFORE, for nothing: whatever the last
            # reading already showed is not this harvest's, and crediting it to the base
            # is how an hour of trucks and gifts would land on the harvest card.
            self._post(self._flush_baseline)
        else:
            self._arm_budget(self._collect_run, now)
            self._collect_run = None
            self._post(self._book_reads)

    def _post(self, func) -> None:
        """Get onto the panel's own thread — a listener is called on any thread."""
        try:
            self.rt.tick.post(func)
        except Exception:                # noqa: BLE001 — no ticker means no window;
            try:                         #   then do it here, which is where it already is
                func()
            except Exception:            # noqa: BLE001
                pass

    def _flush_baseline(self) -> None:
        """Price what is already in the cache as NOT the harvest's. Reads nothing."""
        self._record(reads.resource_balance(self.rt, cached=True), base=False)

    def _book_reads(self) -> None:
        """Ask for a reading after the harvest — the half of the fix that is not
        attribution (:data:`HARVEST_READS`). Without it a panel nobody is looking at
        takes no reading at all and the harvest is never priced."""
        for index, delay in enumerate(HARVEST_READS):
            try:
                self.rt.tick.arm(f"{READ_CHAIN}:{index}", int(delay * 1000),
                                 self._ask_read)
            except Exception:            # noqa: BLE001 — an unbooked reading is one
                pass                     #   the next push or look still takes

    def _ask_read(self) -> None:
        """One booked reading. The answer arrives as `RESOURCES_READ` and is priced
        there, like every other reading."""
        try:
            self.rt.resources.ask()
        except Exception:                # noqa: BLE001 — a reading, never the gain
            pass

    # -- the fresh reading -----------------------------------------------------
    def listen(self) -> None:
        """Price the tally when a FRESH balance reading lands (#2743).

        The push is not the moment: `BaseResources` answers out of its cache and refreshes
        behind the answer, so the reading the tracker diffs against is the one from BEFORE
        the harvest. Measured live — the run ended 22:38:24, the tracker read at 22:38:24
        and saw the old numbers, and the fresh ones landed some fifteen seconds later with
        no push left to price them. So the tally listens for the reading itself.

        Idempotent: called from :meth:`track`, which the trigger fires on every push.
        """
        if self._off is not None:
            return
        try:
            self._off = self.rt.bus.subscribe(busmod.RESOURCES_READ,
                                              lambda _p=None: self.on_reading())
        except Exception:                # noqa: BLE001 — a subscription, never the gain
            self._off = None

    def on_reading(self) -> None:
        """A fresh reading has landed: price whatever it moved. A LOOK, never a read."""
        self._remember_labels()
        self._record(reads.resource_balance(self.rt, cached=True))

    def _remember_labels(self) -> None:
        """Keep the game's own name and picture for each item the base pays in (#2744).

        Written down because a page can be drawn before this session has read anything —
        after a restart, or on a profile whose client is not up — and an id is not a word
        anybody reads. Only written when it MOVED: a blob rewritten on every reading
        would be a write per balance push for a table that changes when the base is
        rebuilt.
        """
        labels = reads.item_labels(self.rt)
        if not labels or labels == self._labels:
            return
        self._labels = labels
        try:
            self.rt.store.blob_set(LABELS_BLOB, labels)
        except Exception:                # noqa: BLE001 — a label, never the gain
            pass

    def _record(self, current: dict, base: "bool | None" = None) -> "dict | None":
        """Diff `current` against the last balance and write the gains down.

        ``base`` overrides the panel's own judgement of where the gain came from:
        `False` is the baseline flush taken as a harvest STARTS, whose gains are by
        definition everything that happened BEFORE it (#2746).
        """
        if not current:
            return None
        gains = statsmod.positive_deltas(current, self._last)
        self._last = current
        if not gains:
            return None
        day = self.day()
        self._stats = self.stats.add(gains, day)
        statsmod.save_stats_to_store(self.rt.store, self._stats)
        # …AND THE SAME GAINS AGAIN, in the base's own book, when the panel knows this
        # was its harvest. Two books rather than one column with a flag: the card of
        # «Сбор ресурсов» asks one question and «Статистика» asks the other, and neither
        # has to filter the other's rows.
        # …CAPPED BY WHAT THE HARVEST SAID IT WAS WORTH (#2747). The window says WHEN a
        # gain could be the harvest's; the budget says HOW MUCH of it can be, and a key
        # the harvest never claimed gets nothing at all. The person's report: 34
        # «Запчастей дрона» on a base that makes about seven a day — two arms-race prizes
        # of twenty, landing a minute after the sweep, inside the burst chain.
        mine = self._claim(gains) if (self.from_base() if base is None
                                      else bool(base)) else {}
        if mine:
            self._base = self.base.add(mine, day)
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
        return gains

    def shutdown(self) -> None:
        """Let the reading, the ear and the register go when the profile closes."""
        if self._off_wire is not None:
            try:
                self._off_wire()
            except Exception:            # noqa: BLE001
                pass
            self._off_wire = None
        if self._off_ready is not None:
            try:
                self._off_ready()
            except Exception:            # noqa: BLE001
                pass
            self._off_ready = None
        if self._off_runs is not None:
            try:
                self._off_runs()
            except Exception:            # noqa: BLE001
                pass
            self._off_runs = None
        for index in range(len(HARVEST_READS)):
            try:
                self.rt.tick.disarm(f"{READ_CHAIN}:{index}")
            except Exception:            # noqa: BLE001
                pass
        if self._off is not None:
            try:
                self._off()
            except Exception:            # noqa: BLE001
                pass
            self._off = None

    # -- the trigger's handler ------------------------------------------------
    def track(self) -> None:
        """One balance-changed push: book a fresh reading and price what it shows.

        The push says a balance MOVED, not by how much, so this asks the reading door
        (which answers out of the cache and refreshes behind the answer) and prices
        whatever is there. The amount usually arrives with the reading that follows —
        :meth:`on_reading` — and that is what actually fills the tally.
        """
        take = intakemod.of(self.rt).at(INTAKE_GAINS)
        take.seen()
        # ARMED ON EVERY PUSH, before anything can return (#2743). A push whose reading
        # was stale prices no gain and is exactly the one that arrives while the harvest
        # is running: arming it here is what lets the gain that lands later still be
        # credited to the base.
        self.note_running()
        # …and the tally listens for the reading itself from now on.
        self.listen()
        current = reads.resource_balance(self.rt)
        if not current:
            # A PUSH THAT COULD NOT BE PRICED IS A LOSS, not an empty answer (#1523):
            # the amount only exists in the reading taken around it.
            take.lost(1, reason="no_reading")
            return
        if self._record(current) is None:
            # The baseline read of a session, a push about something that did not go up,
            # or — the ordinary case — a reading that has not caught up yet, which
            # :meth:`on_reading` prices the moment it does.
            take.dropped(1, reason="no_gain")
            return
        take.kept()


def register(schedule) -> None:
    """Bind the tracker to the `resource_tracker` trigger, whatever tabs this profile
    has. Called once, from `Schedule` — the same door `panel/runtime/panel_orders.py`
    uses for an ability that belongs to no tab."""
    book = getattr(schedule.rt, "resource_book", None)
    if book is None:
        return
    schedule.bind("resource_tracker", book.track, needs_game=True)
    # …AND THE TWO THINGS THAT DO NOT DEPEND ON THAT TRIGGER AT ALL (#2746). Measured on
    # the live panel of 2026-09-11: `default`'s `resource_tracker` listener died at
    # 00:42 («слушатель завершился — больше не слежу») and the six harvests that followed
    # were never priced — the day's tally stopped at one hour's worth of food while the
    # base went on paying. A tally that only counts while a trigger happens to be alive
    # is not a tally, so the book listens to the RUN REGISTER and to the reading itself,
    # both of which are the runtime's own and cost the game nothing.
    book.watch()
    book.listen()
