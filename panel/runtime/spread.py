"""Do several things one at a time instead of all at once (#2678).

The panel's own rule, written in `CLAUDE.md` after #2667: «Nothing starts in a burst».
A boot is when everything the panel holds is at once overdue, and each of those things is
a chunk in the game — an attach, which suspends the client's main thread, redirects its
RIP and puts it back. That minute is when the client dies: six of nine measured restarts
killed it 59-95 s in (`docs/research/client-crashes.md`).

The errands got their spread in #2667 and the boot's READINGS did not, on the grounds
that delaying a board shows a number a minute older than it could be. The person decided
otherwise, in their words: «Да, разноси, сделай правило, пусть лаг будет, нет веской
причины все разом делать».

So: the first thing happens AT ONCE — a spread that delayed even the first would be lag
bought for nothing — and the rest are booked on the panel's own clock, :data:`SPREAD_SEC`
apart. Nothing is dropped and nothing is re-ordered.

Two callers so far, and they are the two shapes this has:

* :class:`~panel.runtime.bus.EventBus` spreads the LISTENERS of `GAME_READY`, so ten tabs
  do not all take their first reading in the same second;
* a tab whose one listener takes SEVERAL readings spreads those too (`panel/tabs/vs.py`),
  because a burst inside one handler is the same burst — the live log of 2026-09-09 has
  seven `read_*` of one tab inside four milliseconds.

What may NOT be spread is anything fired by an event: a push, a person's press, a rally
banner. Those are answered in seconds or not at all.
"""
from __future__ import annotations

import itertools

#: How far apart the steps of a spread are, in seconds. A board is at worst a few tens of
#: seconds older than it could be, on a reading the wire keeps current afterwards.
SPREAD_SEC = 6.0

#: Booking names have to be unique or `Ticker.arm` cancels the previous one — a spread
#: that shared a name would run only its last step.
_seq = itertools.count(1)


def spread(arm, calls, gap: float = SPREAD_SEC, tag: str = "spread") -> int:
    """Run ``calls[0]`` now and book the rest ``gap`` apart. Returns how many were booked.

    ``arm`` is the clock's one-shot booker (`panel/runtime/tick.py::Ticker.arm`). With no
    clock — a bare harness, a tab standing on its own — everything runs at once, which is
    what the panel did before this existed and is never worse than not running at all.

    A call that raises does not stop the rest: these are readings, and one board that
    cannot be drawn is not the other boards' problem.
    """
    todo = [c for c in calls if c is not None]
    if not todo:
        return 0
    _run(todo[0])
    if arm is None:
        for call in todo[1:]:
            _run(call)
        return 0
    booked = 0
    for i, call in enumerate(todo[1:], start=1):
        name = f"{tag}.{next(_seq)}"
        try:
            arm(name, int(i * gap * 1000), lambda c=call: _run(c))
            booked += 1
        except Exception:                    # noqa: BLE001 — a clock that will not book
            _run(call)                       #   still owes the step its turn
    return booked


def _run(call) -> None:
    try:
        call()
    except Exception:                        # noqa: BLE001 — one step, not the spread
        pass
