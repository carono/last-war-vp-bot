"""When THIS profile's warzone starts a new day — one holder per open profile.

`tools/lib/game_day.py` does the arithmetic and knows nothing; this holds the one number
the arithmetic needs — the client's own `GetTomorrowZero()` — and keeps it where it
belongs: **in the profile's own directory, read from the profile's own client**.

WHY IT IS NOT A MODULE-LEVEL NUMBER. A window holds several profiles and they are not on
one warzone. «Профиль — это полностью независимый инстанс панели», and the boundary a
daily errand is anchored to is an ACCOUNT's answer, not a machine's: park it in a global
and the first profile to read one decides when everybody else's day turns over. So this
object is built per runtime, re-pointed on a profile switch exactly as the last-run store
is, and persisted to `<profile>/day_reset.json` so a fresh panel starts knowing what the
last one learnt.

WHAT IT COSTS. One Lua round trip, at most every :data:`REFRESH_SEC`, and only ever from
a caller that has already established the client is up (`Schedule.gate`). The reading it
takes does not go stale in any way that matters — only the boundary's PHASE is used, and
that moves when a warzone does, not when a day does — so re-reading is hygiene rather
than necessity.

WHAT HAPPENS WITH NO CLIENT. Nothing waits and nothing fails. An unread profile answers
out of its stored reading; a profile that has never had one answers out of
`game_day.DEFAULT_PHASE_MS` (02:00 UTC, measured live on one warzone, #1188). A daily
errand therefore keeps firing on a plausible boundary through an evening with the game
shut, which is the only behaviour worth having: refusing to schedule until a client can
be asked would mean a panel that comes up to a dead client never runs the errand that
would restart it.
"""
from __future__ import annotations

import json
import os
import time

import game_day

#: How old a reading may get before the next chance is taken to replace it. Six hours:
#: four cheap reads a day against a number that changes when the account moves warzone,
#: which is to say approximately never. The point of re-reading at all is that «never» is
#: not «impossible».
REFRESH_SEC = 6 * 3600

#: What the read is given to answer in. Same shape as every other one-value Lua read in
#: the panel — a marker, a line, a number.
MARKER = "DAYEND"


class DayReset:
    """This profile's server-day boundary: what was last read, and what follows from it."""

    __slots__ = ("rt", "_path", "_boundary_ms", "_read_at", "_asked_at")

    def __init__(self, rt, path: "str | None" = None) -> None:
        self.rt = rt
        self._boundary_ms = 0
        self._read_at = 0.0
        # When a read was last ATTEMPTED, which is not when one last succeeded: a client
        # that cannot answer must not be asked once a tick for the rest of the evening.
        self._asked_at = 0.0
        self._path = ""
        self.set_path(path if path is not None else self._default_path())

    # -- where it lives ------------------------------------------------------
    def _default_path(self) -> str:
        try:
            return self.rt.profiles.day_reset_json()
        except Exception:                    # noqa: BLE001 — a bare runtime in a test
            return ""

    @property
    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        """Point at another profile's file and read it — what a profile switch calls.

        The in-memory reading is dropped with the path, deliberately: keeping the
        previous account's boundary would be exactly the leak this class exists to stop.
        """
        self._path = str(path or "")
        self._boundary_ms, self._read_at, self._asked_at = 0, 0.0, 0.0
        self._load()

    def _load(self) -> None:
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        try:
            boundary = int(data.get("day_end_ms") or 0)
            read_at = float(data.get("read_at") or 0.0)
        except (TypeError, ValueError):
            return
        if boundary >= game_day.EPOCH_FLOOR_MS:
            self._boundary_ms, self._read_at = boundary, read_at

    def _save(self) -> None:
        if not self._path:
            return
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump({"day_end_ms": self._boundary_ms,
                           "read_at": self._read_at}, fh)
        except OSError:
            pass                             # a cached number, never the schedule

    # -- what is known -------------------------------------------------------
    def boundary_ms(self) -> int:
        """The client's last answer to «when does this day end», or ``0`` for none."""
        return self._boundary_ms

    def synced(self) -> bool:
        """Whether the boundary is a reading rather than the built-in fallback."""
        return self._boundary_ms >= game_day.EPOCH_FLOOR_MS

    def note(self, day_end_ms) -> bool:
        """Record one reading. ``False`` for anything that is not a clock (#1227)."""
        try:
            boundary = int(day_end_ms or 0)
        except (TypeError, ValueError):
            return False
        if boundary < game_day.EPOCH_FLOOR_MS:
            return False
        self._boundary_ms, self._read_at = boundary, time.time()
        self._save()
        return True

    # -- what follows from it ------------------------------------------------
    def next_reset_epoch(self, after_epoch_sec: float) -> float:
        """First server midnight strictly after ``after_epoch_sec``, in local seconds."""
        return game_day.next_reset_epoch(after_epoch_sec, self._boundary_ms)

    def seconds_to_reset(self, now_epoch_sec: "float | None" = None) -> int:
        """How long until the quotas come back — what a «до сброса» reading shows."""
        now = time.time() if now_epoch_sec is None else float(now_epoch_sec)
        return game_day.seconds_to_reset(game_day.to_game_ms(now), self._boundary_ms)

    def day_key(self, now_epoch_sec: "float | None" = None) -> str:
        """The GAME day that moment falls in, ``YYYY-MM-DD`` — a key for a daily tally."""
        now = time.time() if now_epoch_sec is None else float(now_epoch_sec)
        return game_day.day_key(game_day.to_game_ms(now), self._boundary_ms)

    # -- asking the client ---------------------------------------------------
    def stale(self, now: "float | None" = None) -> bool:
        """Is it worth spending a round trip on a fresh reading?"""
        now = time.time() if now is None else float(now)
        if now - self._asked_at < REFRESH_SEC:
            return False
        return now - self._read_at >= REFRESH_SEC

    def refresh(self, force: bool = False) -> bool:
        """Ask THIS profile's client when its day ends. ``True`` if a reading landed.

        Only ever called from somewhere that has already established the client is up,
        and throttled on top of that (:data:`REFRESH_SEC`) — a failed read counts against
        the throttle just as a successful one does, so a client that answers nothing is
        asked four times a day rather than every twenty seconds.

        Never raises: an unread boundary leaves the stored one in force, and a profile
        that has never had one falls back to 02:00 UTC.
        """
        if not force and not self.stale():
            return False
        self._asked_at = time.time()
        try:
            import lua_actions

            chunk = ("CS.UnityEngine.Debug.LogError('%s '..tostring(%s))"
                     % (MARKER, lua_actions.server_day_end()))
            lines = self.rt.game.evaluator().run(chunk, marker=MARKER, settle=0.4,
                                                 early=True)
        except Exception:                    # noqa: BLE001 — a stamp, never the schedule
            return False
        for line in lines or ():
            if MARKER + " " in line:
                tail = line.split(MARKER + " ", 1)[1].split()[0]
                try:
                    return self.note(int(float(tail)))
                except (TypeError, ValueError):
                    return False
        return False
