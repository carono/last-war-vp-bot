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

    def __init__(self, store, *, reset_ms: int = 0) -> None:
        self.store = store
        #: When the game-day turns over — the client's own `GetTomorrowZero`, in
        #: milliseconds. Zero until somebody tells us (`set_reset`), and then the day
        #: index of every reading is counted off it rather than off UTC midnight.
        self.reset_ms = int(reset_ms or 0)
        self._rows: "list | None" = None
        self._schedule = None
        self._fitted = False
        #: Rows handed to the writer thread but not necessarily committed yet. A press
        #: redraws the grid in the same tick it was made, and the writer commits a
        #: moment later — without this the row a person just wrote down would be missing
        #: from the answer that press produced, which reads as «панель меня не услышала».
        self._pending: list = []

    # -- what the game says about its own day boundary -----------------------
    def set_reset(self, day_end_ms) -> None:
        """Remember the game's day boundary, as the client last answered it."""
        try:
            value = int(day_end_ms)
        except (TypeError, ValueError):
            return
        if value > 0:
            self.reset_ms = value

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

    def answer(self, server, day=None, fact=None) -> dict:
        """What that warzone is doing, and when it changes — one dict for both screens.

        `fact` is a state the GAME itself said, when there is one; it wins over
        everything, and the answer says so in `source` (`docs/panel-tabs.md`: a screen is
        data, and «откуда это известно» is part of the data).
        """
        when = self.today() if day is None else int(day)
        rows = self.observations()
        plan = self.schedule()
        said = model.answer(plan, rows, server, when, fact=fact)
        turn = model.next_change(plan, rows, server, when)
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
        out = []
        for row in rows or ():
            said = model.answer(plan, seen, int(row.get("id") or 0), when)
            turn = model.next_change(plan, seen, int(row.get("id") or 0), when)
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
        return out

    def conflicts(self) -> list:
        """Every observation the fitted cycle contradicts — the graph's own alarm."""
        return model.conflicts(self.schedule(), self.observations())

    # -- housekeeping ---------------------------------------------------------
    def _forget_cache(self) -> None:
        self._rows = None
        self._schedule = None
        self._fitted = False
