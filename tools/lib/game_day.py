"""The GAME's day, which does not turn over at this machine's midnight.

Everything the game gives out once a day — five robberies, a codename attack, an
alliance donation quota, a checklist of errands — comes back at ONE moment: the
warzone's own 00:00. That moment is not midnight anywhere in particular. Measured
live on this account's warzone it is **02:00 UTC** (`GetTomorrowZero()` answered
`2026-08-07 02:00:00 UTC`, and 597 of 636 tile expiries shared `01:59:59` —
docs/research/ghost-recon-steal.md §4.1, rally-join.md §858), and there is nothing
saying every warzone shares it.

WHY A MODULE AND NOT ANOTHER `+ 86400`. A daily errand whose next run is «the last
run plus twenty-four hours» drifts forward by however long the run took and by
however long the panel was asleep, and it only has to drift past the reset once to
lose a whole day's quota: the errand fires at 00:01, the day's five robberies are
spent, and the next fire is at 00:01 TOMORROW — one minute after the quota it was
meant to spend came back and twenty-three hours and fifty-nine minutes before it is
touched again. Anchoring on the reset instead makes the schedule self-correcting: a
run at 23:59 is followed by one at 00:00, a minute later, because that is when there
is something to do again.

The arithmetic here is deliberately pure — no state, no I/O, no clock of its own.
Two things are handed IN:

* ``day_end_ms`` — the client's own answer to «when does this day end»
  (`lua_actions.server_day_end()` -> `UITimeManager:GetInstance():GetTomorrowZero()`).
  Only its PHASE is used — where in a UTC day the boundary falls — so a reading taken
  last week still places today's boundary exactly. Zero, missing or implausible falls
  back to :data:`DEFAULT_PHASE_MS`;
* the moment being asked about, in the GAME's milliseconds. `tools/lib/game_clock.py`
  is what turns this machine's clock into those (the two were eleven seconds apart when
  it was written, and it is the PC that is wrong).

**One warzone's boundary is not another's**, so nothing here is remembered between
calls. Whoever holds a reading holds it per PROFILE — `panel/runtime/day_reset.py` is
the panel's holder, one per open profile, persisted in that profile's own directory.
"""
from __future__ import annotations

DAY_MS = 24 * 60 * 60 * 1000
DAY_SEC = 24 * 60 * 60

#: Where the server's midnight falls when nobody has been able to ask the client —
#: 02:00 UTC, measured live (#1188). A FALLBACK and never an authority: it is one
#: warzone's answer, and the client's own `GetTomorrowZero()` beats it whenever there
#: is one to be had.
DEFAULT_RESET_HOUR_UTC = 2
DEFAULT_PHASE_MS = DEFAULT_RESET_HOUR_UTC * 60 * 60 * 1000

#: Anything below this is not an epoch clock at all — the same floor `game_clock` uses,
#: and for the same reason: a client that has not logged in answers questions about time
#: with its own uptime, cheerfully and without an error (#1227). A boundary of 6 280 648
#: would put every reset in 1970.
EPOCH_FLOOR_MS = 1_500_000_000_000


def phase_ms(day_end_ms=0) -> int:
    """Where in a UTC day the server's midnight falls, in ms — ``0 … DAY_MS-1``.

    Taken from the client's own boundary rather than from its date, so a reading of any
    age still places today's reset: the boundary moves a day at a time and its remainder
    modulo a day does not move at all.
    """
    try:
        boundary = int(day_end_ms or 0)
    except (TypeError, ValueError):
        return DEFAULT_PHASE_MS
    if boundary < EPOCH_FLOOR_MS:
        return DEFAULT_PHASE_MS
    return boundary % DAY_MS


def next_reset_ms(now_ms, day_end_ms=0) -> int:
    """The first server midnight **strictly after** ``now_ms``, on the game's clock.

    Strictly, and that is the edge case a daily timer stands or falls on: an errand that
    finishes at the reset instant belongs to the day that has just begun, so its next
    turn is tomorrow's boundary. With «at or after» the same errand would be due the
    moment it finished, and every tick after that, for ever.
    """
    now = int(now_ms)
    phase = phase_ms(day_end_ms)
    return ((now - phase) // DAY_MS + 1) * DAY_MS + phase


def previous_reset_ms(now_ms, day_end_ms=0) -> int:
    """The server midnight **at or before** ``now_ms`` — the start of the current day."""
    now = int(now_ms)
    phase = phase_ms(day_end_ms)
    return ((now - phase) // DAY_MS) * DAY_MS + phase


def seconds_to_reset(now_ms, day_end_ms=0) -> int:
    """How long until the quotas come back, in whole seconds. Never negative."""
    return max(0, (next_reset_ms(now_ms, day_end_ms) - int(now_ms)) // 1000)


def day_key(now_ms, day_end_ms=0) -> str:
    """The GAME day ``now_ms`` falls in, as ``YYYY-MM-DD`` — a key a tally can be filed under.

    The date of the day's START, so a counter written at 01:00 UTC and one written at
    03:00 UTC on the same calendar date land in DIFFERENT days when the boundary is at
    02:00 — which is the whole point, because the game gave the second one a fresh quota.
    """
    import datetime

    start = previous_reset_ms(now_ms, day_end_ms)
    when = datetime.datetime.fromtimestamp(start / 1000.0, datetime.timezone.utc)
    return when.date().isoformat()


# -- the bridge between the game's clock and this machine's --------------------
#
# A schedule is kept in local `time.time()` seconds — that is what `last_run` is written
# in and what a tick compares against — while a reset is a moment on the GAME's clock.
# The two are the same instant seen through two clocks that were eleven seconds apart
# when `game_clock` was written, so the conversion is explicit rather than assumed.


def offset_ms() -> int:
    """How far ahead of this machine the game's clock runs; ``0`` when nobody has asked.

    Read through `game_clock`, lazily and never fatally: a process with no `tools/lib`
    on its path, or one that has never had a client to ask, is neither better nor worse
    off than it was before this existed — the reset simply lands on the machine's own
    reckoning of 02:00 UTC, out by whatever the drift is.
    """
    try:
        import game_clock
    except Exception:                       # noqa: BLE001 — a clock is not worth a crash
        return 0
    try:
        return int(game_clock.offset_ms())
    except Exception:                       # noqa: BLE001
        return 0


def to_game_ms(local_epoch_sec, offset=None) -> int:
    """Local ``time.time()`` seconds -> the same instant in the game's milliseconds."""
    off = offset_ms() if offset is None else int(offset)
    return int(float(local_epoch_sec) * 1000) + off


def to_local_sec(game_ms, offset=None) -> float:
    """The game's milliseconds -> the same instant as local ``time.time()`` seconds."""
    off = offset_ms() if offset is None else int(offset)
    return (int(game_ms) - off) / 1000.0


def next_reset_epoch(after_epoch_sec, day_end_ms=0) -> float:
    """The first server midnight strictly after ``after_epoch_sec``, in LOCAL seconds.

    What a schedule wants: it keeps its records in `time.time()` and needs a wall clock
    to compare a tick against. The offset is read once and used for both conversions, so
    a sample landing between them cannot move the answer.
    """
    off = offset_ms()
    return to_local_sec(next_reset_ms(to_game_ms(after_epoch_sec, off), day_end_ms), off)
