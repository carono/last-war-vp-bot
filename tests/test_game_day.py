r"""The GAME's day boundary, and the daily errand that has to land on it.

`tools/lib/game_day.py` is the arithmetic; `panel/timers.py::next_after` is what a
schedule does with it. Both are pure — no Tk, no game, no clock of their own — so the
whole thing runs anywhere::

    python3 tests/test_game_day.py
    C:\Python312\python.exe tests\test_game_day.py

WHAT IS BEING PINNED, and why each case exists rather than being obvious:

  * the boundary is the SERVER's, not this machine's — the phase comes off the client's
    own `GetTomorrowZero()`, and only its remainder modulo a day is used, so a reading
    taken last week still places today's reset;
  * **23:59 → 00:00, not tomorrow's 23:59.** The whole task (#1333). A daily errand run
    a minute before the reset is due again a minute later, because a minute later is when
    the quota it spends comes back;
  * **00:01 → the NEXT reset**, twenty-three hours and fifty-nine minutes away, and not
    «now» — an errand that has just spent the day's quota must not spin;
  * **exactly at the reset → tomorrow.** Strictly-after, or the errand is due the instant
    it finishes and for ever afterwards;
  * **a panel that slept through three resets fires ONCE**, not three times;
  * a run that STRADDLES the boundary is charged to the day it started in, so the fresh
    quota is not written off by a run that finished forty seconds into it;
  * two profiles on two warzones get two boundaries, with nothing shared;
  * no client to ask falls back to the measured 02:00 UTC rather than refusing to
    schedule;
  * a period that is not a whole number of days is left exactly as it was.
"""
from __future__ import annotations

TIER = "offline"   # no Tk, no display, no game — see tools/run_tests.py

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (str(_REPO), str(_REPO / "tools" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import game_day                                          # noqa: E402
from panel import timers as timersmod                    # noqa: E402

DAY = game_day.DAY_MS
HOUR = 3600 * 1000

#: A plausible epoch, on a day boundary in UTC. 20 000 days after the epoch is
#: 2024-10-04, comfortably past `EPOCH_FLOOR_MS` and easy to count from by hand.
DAY0 = 20_000 * DAY

#: What a client on the measured warzone answers `GetTomorrowZero()` with: the next
#: 02:00 UTC. Invented from DAY0 rather than pasted out of a live reply.
BOUNDARY = DAY0 + 2 * HOUR

#: …and a second warzone, whose day turns eleven hours later. Also invented — the point
#: is only that it is NOT the first one's.
BOUNDARY_B = DAY0 + 13 * HOUR


# -- the arithmetic ----------------------------------------------------------
def test_the_phase_is_the_servers_and_survives_a_stale_reading():
    """Only the remainder modulo a day is used, so an old reading still places today."""
    assert game_day.phase_ms(BOUNDARY) == 2 * HOUR
    # …the same boundary read a fortnight ago places the same reset
    assert game_day.phase_ms(BOUNDARY - 14 * DAY) == 2 * HOUR
    assert game_day.phase_ms(BOUNDARY_B) == 13 * HOUR


def test_no_reading_falls_back_to_the_measured_boundary_not_to_utc_midnight():
    """A profile that has never had a client to ask still schedules on 02:00 UTC.

    Midnight UTC is the answer that LOOKS right and is two hours out on the warzone this
    was measured on — which is exactly the bug the checklist's «до сброса» had.
    """
    assert game_day.phase_ms(0) == game_day.DEFAULT_PHASE_MS
    assert game_day.DEFAULT_PHASE_MS == 2 * HOUR
    # …and so does one whose client answered with its own uptime (#1227)
    assert game_day.phase_ms(6_280_648) == game_day.DEFAULT_PHASE_MS
    assert game_day.phase_ms("nonsense") == game_day.DEFAULT_PHASE_MS


def test_the_next_reset_is_strictly_after_the_moment_asked_about():
    """At the boundary itself the answer is TOMORROW's, or a daily errand never settles."""
    assert game_day.next_reset_ms(BOUNDARY, BOUNDARY) == BOUNDARY + DAY
    assert game_day.next_reset_ms(BOUNDARY - 1, BOUNDARY) == BOUNDARY
    assert game_day.next_reset_ms(BOUNDARY + 1, BOUNDARY) == BOUNDARY + DAY
    # …and well before it, the same day's
    assert game_day.next_reset_ms(BOUNDARY - 5 * HOUR, BOUNDARY) == BOUNDARY


def test_the_previous_reset_is_at_or_before_and_names_the_day():
    assert game_day.previous_reset_ms(BOUNDARY, BOUNDARY) == BOUNDARY
    assert game_day.previous_reset_ms(BOUNDARY - 1, BOUNDARY) == BOUNDARY - DAY
    # An hour BEFORE the boundary is still the previous game day, whatever the UTC date
    # says — which is the whole reason a daily tally cannot use `date.today()`.
    assert game_day.day_key(BOUNDARY - HOUR, BOUNDARY) != \
        game_day.day_key(BOUNDARY + HOUR, BOUNDARY)


def test_seconds_to_reset_counts_to_the_servers_midnight():
    assert game_day.seconds_to_reset(BOUNDARY - 2 * HOUR, BOUNDARY) == 7200
    assert game_day.seconds_to_reset(BOUNDARY, BOUNDARY) == 24 * 3600


def test_the_offset_is_applied_once_and_in_the_right_direction():
    """The game's clock ran ELEVEN SECONDS ahead of this machine when it was measured."""
    assert game_day.to_game_ms(1000.0, offset=11_000) == 1_011_000
    assert game_day.to_local_sec(1_011_000, offset=11_000) == 1000.0


# -- what a schedule does with it -------------------------------------------
class _Day:
    """A profile's day boundary, with no runtime and no client behind it.

    The same one method `panel/runtime/day_reset.py` offers the scheduler, so what is
    pinned here is the contract and not the holder.
    """

    def __init__(self, boundary_ms: int) -> None:
        self.boundary = boundary_ms

    def next_reset_epoch(self, after_epoch_sec: float) -> float:
        # No `game_clock` sample in a test process, so the offset is zero and local
        # seconds ARE the game's — which is the unsynced state a fresh panel starts in.
        return game_day.next_reset_ms(int(after_epoch_sec * 1000), self.boundary) / 1000.0


def _sec(ms: int) -> float:
    return ms / 1000.0


def test_a_run_a_minute_before_the_reset_is_due_a_minute_later():
    """THE case in the task. «Выполнили в 23:59 — следующий срок 00:00.»

    Not tomorrow's 23:59, which is what `last + 86400` gives and which loses the whole
    day's quota that arrives sixty seconds after the run.
    """
    day = _Day(BOUNDARY)
    at_2359 = _sec(BOUNDARY - 60_000)
    assert timersmod.next_after(at_2359, 86400, day) == _sec(BOUNDARY)
    # …and the plain-period answer it replaces, for contrast
    assert timersmod.next_after(at_2359, 86400, None) == at_2359 + 86400


def test_a_run_a_minute_after_the_reset_waits_for_the_next_one():
    """«Выполнили в 00:01 — следующий срок ближайший СЛЕДУЮЩИЙ сброс.»

    Not «now»: the run has just spent today's quota, and an errand that came due the
    moment it finished would spin against the game for the rest of the day.
    """
    day = _Day(BOUNDARY)
    at_0001 = _sec(BOUNDARY + 60_000)
    assert timersmod.next_after(at_0001, 86400, day) == _sec(BOUNDARY + DAY)
    assert timersmod.next_after(at_0001, 86400, day) - at_0001 == 24 * 3600 - 60


def test_a_run_exactly_at_the_reset_belongs_to_the_day_that_just_started():
    day = _Day(BOUNDARY)
    assert timersmod.next_after(_sec(BOUNDARY), 86400, day) == _sec(BOUNDARY + DAY)


def test_the_point_of_the_change_the_fire_does_not_drift_forward():
    """Ten days of «+24 h» walks the fire right around the clock; anchoring does not.

    This is the failure mode in one assertion: each run takes ninety seconds, so the plain
    period moves the fire fifteen minutes later over ten days and eventually steps over a
    reset. The anchored one lands on the same boundary every time.
    """
    day = _Day(BOUNDARY)
    drifting = anchored = _sec(BOUNDARY - 3600)        # an hour before the reset
    for _ in range(10):
        drifting = timersmod.next_after(drifting, 86400, None) + 90
        anchored = timersmod.next_after(anchored, 86400, day) + 90
    assert drifting > _sec(BOUNDARY + 9 * DAY) + 800     # walked ~15 min forward
    # …the anchored one is 90 s past a boundary, exactly as it was on day one
    assert (anchored * 1000 - BOUNDARY) % DAY == 90_000


def test_a_panel_that_slept_through_three_resets_fires_once_not_three_times():
    """A missed boundary is in the past, so the errand is due NOW — and only once.

    There is no queue of skipped days to work off: the run writes down a new anchor and
    the next boundary after THAT is tomorrow's.
    """
    day = _Day(BOUNDARY)
    slept_from = _sec(BOUNDARY - HOUR)
    woke_at = _sec(BOUNDARY + 3 * DAY + HOUR)
    due = timersmod.next_after(slept_from, 86400, day)
    assert due <= woke_at                                # due at once
    # the run happens; the very next turn is a whole boundary away, not two more now
    after = timersmod.next_after(woke_at, 86400, day)
    assert after == _sec(BOUNDARY + 4 * DAY)
    assert after > woke_at


def test_two_profiles_on_two_warzones_get_two_boundaries():
    """Nothing is shared: the boundary is an ACCOUNT's answer, handed in per call."""
    a, b = _Day(BOUNDARY), _Day(BOUNDARY_B)
    ran = _sec(DAY0 + 1 * HOUR)
    assert a.next_reset_epoch(ran) == _sec(BOUNDARY)
    assert b.next_reset_epoch(ran) == _sec(BOUNDARY_B)
    assert timersmod.next_after(ran, 86400, a) != timersmod.next_after(ran, 86400, b)


def test_no_boundary_at_all_still_schedules_rather_than_refusing():
    """An unreadable clock leaves 02:00 UTC in force — a timer never stops on a reading."""
    day = _Day(0)
    ran = _sec(DAY0 + 1 * HOUR)
    assert day.next_reset_epoch(ran) == _sec(DAY0 + 2 * HOUR)


def test_only_whole_days_are_anchored():
    """36 hours is a period somebody typed, not a daily errand — leave it alone."""
    day = _Day(BOUNDARY)
    ran = _sec(BOUNDARY - HOUR)
    assert timersmod.is_daily(86400) and timersmod.is_daily(3 * 86400)
    assert not timersmod.is_daily(3600) and not timersmod.is_daily(129600)
    assert timersmod.next_after(ran, 3600, day) == ran + 3600
    assert timersmod.next_after(ran, 129600, day) == ran + 129600


def test_a_multi_day_period_lands_on_a_boundary_too():
    """«Every three days» is the first reset after the run, plus two more whole days."""
    day = _Day(BOUNDARY)
    ran = _sec(BOUNDARY - HOUR)
    assert timersmod.next_after(ran, 3 * 86400, day) == _sec(BOUNDARY + 2 * DAY)


# -- the run that straddles the boundary ------------------------------------
def test_a_run_that_straddles_the_reset_is_charged_to_the_day_it_started_in():
    """Started at 23:59:40, finished at 00:00:20 — the NEW day's quota is still owed.

    Anchoring on the finish would say «this run belongs to the new day» about a run that
    spent the old one's, and the fresh quota would sit untouched for twenty-four hours —
    the very loss this change exists to stop, reintroduced by forty seconds of rounding.
    """
    began = _sec(BOUNDARY - 20_000)
    done = _sec(BOUNDARY + 20_000)
    anchor = timersmod._day_anchor({"began_at": began, "last_run": done})
    assert anchor == began
    assert timersmod.next_after(anchor, 86400, _Day(BOUNDARY)) == _sec(BOUNDARY)


def test_a_record_written_before_began_at_existed_still_schedules():
    """An old `timers_last_run.json` has no `began_at` — fall back to the finish."""
    assert timersmod._day_anchor({"last_run": 1234.0}) == 1234.0
    assert timersmod._day_anchor({}) == 0.0
    # …and a `began_at` left over from a LATER attempt is not trusted over the finish
    assert timersmod._day_anchor({"began_at": 9000.0, "last_run": 1234.0}) == 1234.0


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
