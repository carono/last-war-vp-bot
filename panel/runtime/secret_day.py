"""THE ONE ENTRANCE to this profile's book of star-secret-task days (#1467).

## What it is for

The game does not tell anybody which warzones are having their star-secret-task day: its
config tables carry the star-task counts, the pools and the events screen, and no per-day
plan for a warzone (`docs/research/secret-task-day.md`). What the client IS told is the
activity list of the warzone it stands in — one warzone, never another.

So the panel keeps a book of what it saw, and derives a cycle from it. This module is the
book; `tools/lib/secret_day.py` is the arithmetic, and it is a separate file for the
reason every other model here is: both front-ends draw the same answer, and a model that
imports Tk cannot be tested without a display.

## The rules the book keeps

* **A row is an OBSERVATION, never a prediction.** Nothing computed is ever written back
  into `secret_days` — a schedule that wrote its own guesses into the evidence would agree
  with itself for ever.
* **A disagreement is kept, not resolved.** A person's reading and a lap's count of the
  same warzone on the same day are two rows (the source is part of the key), so the two
  can be compared instead of one silently replacing the other.
* **Per PROFILE.** The book is this profile's database (`rt.store`), like everything else
  an account knows. Which warzone had its day is arguably the same fact for every account
  on the machine — and it is still kept per profile, because what it is DERIVED from is
  this account's laps and this account's readings, and a shared book would mean one
  profile's mistaken mark reaching another account's grid with nothing to trace it by.

## Nothing here asks the game anything

Every observation comes from something the panel was already doing: the scenario
`read_secret_day.md` (which reads the client's own dispatch table for the account's own
warzone), a lap of the map that had to happen anyway, or a person writing down what they
saw. Nothing in this module sends a message.
"""
from __future__ import annotations

import time

from .paths import ensure

ensure()

import secret_day as model                                   # noqa: E402


class SecretDayBook:
    """This profile's observations, and the cycle fitted to them.

    Built by the runtime and reached as `rt.secret_days`. The fit is cached and thrown
    away on every write — it costs a few thousand comparisons and the grid asks for it
    once per draw, so re-fitting on every read would be paid for on every repaint.
    """

    def __init__(self, store, *, reset_ms: int = 0, ages: "dict | None" = None,
                 reset=None) -> None:
        self.store = store
        #: When the game-day turns over — the client's own `GetTomorrowZero`, in
        #: milliseconds, and every reading here is counted off it rather than off UTC
        #: midnight. `reset` is where the profile keeps that number between runs
        #: (`panel/runtime/day_reset.py`), asked rather than remembered: a book that
        #: started every panel at zero counted a warzone that opened between midnight
        #: and the reset as a day older than it is, and the age is the whole basis of
        #: the calendar cycle.
        self._reset_ms = int(reset_ms or 0)
        self._reset = reset
        #: Which boundary the ages below were computed against, so a hook that starts
        #: answering later does not leave them a day out.
        self._ages_reset = None
        self._rows: "list | None" = None
        self._schedule = None
        self._fitted = False
        #: The age cycle and the ages behind it — the same lazy-and-thrown-away pair.
        self._calendar = None
        self._calendared = False
        #: `{warzone: days open today}`. Handed in by a test that must not depend on
        #: which warzones THIS machine happens to have read; read off the machine's list
        #: (:meth:`ages`) in every other caller.
        self._ages: "dict | None" = None if ages is None else dict(ages)
        #: True when the ages were handed in (a test). Then they are used as given and
        #: never recomputed from the machine's warzone list.
        self._ages_given = ages is not None
        #: Rows handed to the writer thread but not necessarily committed yet. A press
        #: redraws the grid in the same tick it was made, and the writer commits a
        #: moment later — without this the row a person just wrote down would be missing
        #: from the answer that press produced, which reads as «панель меня не услышала».
        self._pending: list = []

    # -- what the game says about its own day boundary -----------------------
    @property
    def reset_ms(self) -> int:
        """The game-day boundary: what a reading told us, else what the profile keeps."""
        if self._reset_ms:
            return self._reset_ms
        if self._reset is not None:
            try:
                asked = int(self._reset() or 0)
            except Exception:                                   # noqa: BLE001
                asked = 0
            if asked:
                return asked
        # NOTHING READ YET is not «UTC midnight»: the panel's documented fallback for a
        # day boundary is `game_day.DEFAULT_PHASE_MS`, measured live on a warzone, and
        # using midnight instead ages every warzone that opened in the small hours by a
        # day — which moved four warzones into the wrong phase on the first live run.
        import game_day

        return game_day.DEFAULT_PHASE_MS

    def set_reset(self, day_end_ms) -> None:
        """Remember the game's day boundary, as the client last answered it."""
        try:
            value = int(day_end_ms)
        except (TypeError, ValueError):
            return
        if value > 0:
            self._reset_ms = value

    def today(self, now_ms=None) -> int:
        """Which game-day it is now — the index every row is keyed by."""
        stamp = int(now_ms) if now_ms else int(time.time() * 1000)
        return model.day_index(stamp, self.reset_ms)

    # -- writing --------------------------------------------------------------
    def record(self, server, day, state=model.STATE_UNKNOWN,
               source=model.SOURCE_OBSERVED, stars=None, tiles=None,
               seen_at=None) -> dict:
        """Write down one observation. Returns the row as it was stored.

        Called from the Tk thread as well as from a lap's thread, so the write goes
        through `store.submit` — the queue and its single transaction, never a commit on
        the thread that is drawing.
        """
        row = model.observation(server, day, state, source, stars, tiles,
                                int(seen_at or time.time() * 1000))

        def job(conn) -> None:
            conn.execute(
                "INSERT INTO secret_days"
                "  (server, day, state, source, stars, tiles, seen_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(server, day, source) DO UPDATE SET"
                "   state = excluded.state, stars = excluded.stars,"
                "   tiles = excluded.tiles, seen_at = excluded.seen_at",
                (row["server"], row["day"], row["state"], row["source"],
                 row["stars"], row["tiles"], row["seen_at"]))

        self.store.submit(job)
        self._pending = [row] + [p for p in self._pending
                                 if (p["server"], p["day"], p["source"])
                                 != (row["server"], row["day"], row["source"])]
        self._forget_cache()
        return row

    def saw_tiles(self, server, stars, tiles, day=None, seen_at=None) -> None:
        """A lap of the map counted `stars` starred tiles among `tiles` — add it up.

        THE ONLY SOURCE THAT COSTS NOTHING (#1467). A lap already happens for the ★ page's
        own reasons and every tile it decodes passes through the panel anyway, so the
        tally is a dict and one queued statement — no game read, no extra traffic, and
        nothing on the drawing thread.

        It ACCUMULATES over the game-day rather than replacing: a lap arrives as a burst
        of a hundred small batches, and the last batch on its own would say «2 of 3».
        Re-seeing the same tile on a second lap counts it twice, which leaves the SHARE —
        the only thing a calibration reads — where it was.

        The state is left exactly as it stands. These rows are evidence, not a verdict:
        they become a label only through a calibration learnt from days somebody named
        (`tools/lib/secret_day.py`), and a lap that is told nothing stays `unknown`.
        """
        stars, tiles = int(stars or 0), int(tiles or 0)
        if tiles <= 0:
            return
        when = self.today() if day is None else int(day)
        stamp = int(seen_at or time.time() * 1000)
        server = int(server)

        def job(conn) -> None:
            conn.execute(
                "INSERT INTO secret_days"
                "  (server, day, state, source, stars, tiles, seen_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(server, day, source) DO UPDATE SET"
                "   stars = secret_days.stars + excluded.stars,"
                "   tiles = secret_days.tiles + excluded.tiles,"
                "   seen_at = excluded.seen_at",
                (server, when, model.STATE_UNKNOWN, model.SOURCE_LAP,
                 stars, tiles, stamp))

        self.store.submit(job)
        held = None
        for row in self._pending:
            if (row["server"], row["day"], row["source"]) == (server, when,
                                                              model.SOURCE_LAP):
                held = row
                break
        if held is None:
            self._pending.append(model.observation(server, when, model.STATE_UNKNOWN,
                                                   model.SOURCE_LAP, stars, tiles, stamp))
        else:
            held["stars"] = int(held.get("stars") or 0) + stars
            held["tiles"] = int(held.get("tiles") or 0) + tiles
            held["seen_at"] = stamp
        self._forget_cache()

    def forget(self, server, day, source) -> None:
        """Drop one observation — the only DELETE here, and it is a person asking."""
        def job(conn) -> None:
            conn.execute("DELETE FROM secret_days"
                         " WHERE server = ? AND day = ? AND source = ?",
                         (int(server), int(day), str(source)))

        self.store.submit(job)
        self._pending = [p for p in self._pending
                         if (p["server"], p["day"], p["source"])
                         != (int(server), int(day), str(source))]
        self._forget_cache()

    # -- reading --------------------------------------------------------------
    def observations(self) -> list:
        """Everything on file, freshest day first, including what is still in the queue."""
        if self._rows is None:
            rows = self.store.read().execute(
                "SELECT server, day, state, source, stars, tiles, seen_at"
                "  FROM secret_days ORDER BY day DESC, server ASC").fetchall()
            self._rows = [dict(row) for row in rows]
        held = {(p["server"], p["day"], p["source"]): p for p in self._pending}
        out = [held.pop((r["server"], r["day"], r["source"]), r) for r in self._rows]
        return out + list(held.values())

    def schedule(self):
        """The cycle fitted to the book — `None` while there is too little to fit."""
        if not self._fitted:
            self._schedule = model.fit(self.observations())
            self._fitted = True
        return self._schedule

    # -- the other cycle: the one a warzone's AGE decides ---------------------
    def ages(self) -> dict:
        """`{warzone: how many days it has been open today}`, off the machine's list.

        Computed from the OPENING MOMENT rather than from the `day` the list happens to
        have stored: that number was true on the day somebody pressed «Обновить», and a
        cache a fortnight old would answer a fortnight late. The opening moment does not
        age (`docs/research/server-info.md`), so the count is re-derived here against the
        game's own day boundary every time.
        """
        if self._ages_given:
            return self._ages or {}
        if self._ages is not None and self._ages_reset != self.reset_ms:
            self._ages = None                    # the boundary moved under the ages
        if self._ages is None:
            from .paths import ensure

            ensure()
            import server_list

            out = {}
            today = self.today()
            for row in server_list.rows(server_list.load()):
                opened = row.get("open_ms")
                if not opened:
                    continue
                try:
                    born = model.day_index(int(opened), self.reset_ms)
                except (TypeError, ValueError):
                    continue
                out[int(row["id"])] = today - born + 1      # day 1 is opening day
            self._ages = out
            self._ages_reset = self.reset_ms
        return self._ages

    def calendar(self):
        """The cycle keyed by a warzone's age, or None while it cannot be fitted."""
        if not self._calendared:
            # FITTED, then COMPLETED (#1467). The fit is a plain reading of what was
            # written down; `with_geometry` fills the rest of the word from the phase
            # that carries the star day, because the other two states are DEFINED by
            # their distance from it — the day after it, and every other day. A book
            # that has only ever been told about star days therefore answers all three
            # instead of two «unknown»s, and an observation that argues with the
            # completed word is reported rather than allowed to rewrite it.
            self._calendar = model.with_geometry(
                model.fit_calendar(self.observations(), self.ages(), self.today()))
            self._calendared = True
        return self._calendar

    def _known(self) -> dict:
        """What every answer is given: the age cycle, the ages, and which day is today."""
        return {"calendar": self.calendar(), "ages": self.ages(), "today": self.today()}

    def answer(self, server, day=None, fact=None) -> dict:
        """What that warzone is doing, and when it changes — one dict for both screens.

        `fact` is a state the GAME itself said, when there is one; it wins over
        everything, and the answer says so in `source` (`docs/panel-tabs.md`: a screen is
        data, and «откуда это известно» is part of the data).
        """
        when = self.today() if day is None else int(day)
        rows = self.observations()
        plan = self.schedule()
        known = self._known()
        said = model.answer(plan, rows, server, when, fact=fact, **known)
        turn = model.next_change(plan, rows, server, when, **known)
        said["until_day"] = None if turn is None else turn["day"]
        said["until_state"] = None if turn is None else turn["state"]
        said["until_in_days"] = None if turn is None else turn["in_days"]
        said["until_ms"] = (None if turn is None
                            else model.day_bounds(turn["day"], self.reset_ms)[0])
        said["date"] = model.day_label(when, self.reset_ms)
        return said

    def take_reading(self, got: dict) -> int:
        """Turn what `read_secret_day.md` read into observations. How many were written.

        Here rather than in either front-end because BOTH press it — the window's grid
        and the phone's screen — and a line parsed in two places is a line the two
        eventually disagree about. It also makes the parsing testable without a dialog.
        """
        clock = dict(part.split("=", 1) for part in
                     str(got.get("secret_clock") or "").split() if "=" in part)
        try:
            day_end = int(clock.get("day_end_ms") or 0)
            now = int(clock.get("now_ms") or 0)
        except ValueError:
            return 0
        if now <= 0 or day_end <= 0:
            return 0
        self.set_reset(day_end)
        day = self.today(now)
        written = 0
        for part in str(got.get("secret_counts") or "").split():
            server, _, counts = part.partition("=")
            stars, _, tiles = counts.partition("/")
            try:
                self.record(int(server), day, source=model.SOURCE_GAME,
                            stars=int(stars), tiles=int(tiles), seen_at=now)
            except ValueError:
                continue
            written += 1
        return written

    def decorate(self, rows, day=None) -> list:
        """Add the star-day answer to drawable warzone rows — for BOTH front-ends.

        The window's grid and the phone's screen draw the same rows off the same model
        (`tools/lib/server_list.py`), so the star-day column is added in one place too:
        each row gains the state, where the answer came from and when it turns over, as
        LOCALE KEYS — a front-end says them, this does not
        (`CLAUDE.md`: not one word of the panel is written in the panel).
        """
        when = self.today() if day is None else int(day)
        plan = self.schedule()
        seen = self.observations()
        known = self._known()
        out = []
        for row in rows or ():
            said = model.answer(plan, seen, int(row.get("id") or 0), when, **known)
            turn = model.next_change(plan, seen, int(row.get("id") or 0), when, **known)
            fresh = dict(row)
            fresh["secret_state"] = said["state"]
            fresh["secret_source"] = said["source"]
            fresh["secret_state_key"] = "servers.secret.state.%s" % said["state"]
            fresh["secret_source_key"] = "servers.secret.src.%s" % said["source"]
            fresh["secret_until_day"] = None if turn is None else turn["day"]
            fresh["secret_until"] = ("—" if turn is None
                                     else model.day_label(turn["day"], self.reset_ms))
            fresh["secret_until_state_key"] = (
                None if turn is None else "servers.secret.state.%s" % turn["state"])
            out.append(fresh)
        return out

    def summary(self) -> dict:
        """How much the book holds and how well the cycle explains it."""
        rows = self.observations()
        out = model.summary(self.schedule(), rows)
        out["reset_ms"] = self.reset_ms
        # …and the age cycle beside the fitted one: its length, and how much of the book
        # it argues with. A person judging whether to believe a cell needs both.
        calendar = self.calendar()
        out["calendar_period"] = None if calendar is None else calendar.period
        out["calendar_coverage"] = 0 if calendar is None else calendar.coverage
        out["calendar_conflicts"] = len(model.calendar_conflicts(
            calendar, rows, self.ages(), self.today()))
        out["dated"] = len(self.ages())
        # WHAT THE STATUS LINE SAYS is about the cycle that is actually answering: the
        # per-warzone fit while there is one, the age cycle otherwise — and the count of
        # disagreements covers BOTH, because a person deciding whether to believe a cell
        # is owed every sighting either of them argues with, not the tidier half.
        if out["period"] is None:
            out["period"] = out["calendar_period"]
        out["conflicts"] = len(self.conflicts())
        return out

    def conflicts(self) -> list:
        """Every observation either cycle contradicts — the graph's own alarm."""
        rows = self.observations()
        return (model.conflicts(self.schedule(), rows)
                + model.calendar_conflicts(self.calendar(), rows, self.ages(),
                                           self.today()))

    # -- housekeeping ---------------------------------------------------------
    def _forget_cache(self) -> None:
        self._rows = None
        self._schedule = None
        self._fitted = False
        self._calendar = None
        self._calendared = False
        # NOT the ages: they come from the machine's warzone list and from the game's day
        # boundary, and neither moves because somebody wrote an observation down.
