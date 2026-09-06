"""How many alliance gifts were taken TODAY — the panel's own book (#2588).

WHY A BOOK AND NOT A READING. The game answers «сколько ждёт» for free once the list has
been asked for, and it answers nothing at all about what was taken: a claimed gift keeps
its place in `giftInfoList` with `receiveState` flipped, and nothing carries a date. So
the day's take is the panel writing down what the RUN said — `collect_alliance_gifts`
counts the unclaimed gifts before and after its claim, and the difference is a number the
game itself will never be asked for again.

Nothing here costs a question (`CLAUDE.md`, «Read once, then LISTEN»): the entry is made
out of a run that had already happened.

THE DAY IS THE SERVER'S, exactly as in `arms_book.py` — this machine's midnight is hours
from the warzone's, and a book from yesterday answers «nothing today» rather than
yesterday's number.

WHAT IS STORED — one row of `blobs`, per profile, whole (game data, so the database and
never a file)::

    {"day": "2026-09-06", "took": 46, "runs": 2, "at": 1788712000.0}
"""
from __future__ import annotations

import time

#: The row in this profile's `blobs` table.
BLOB = "alliance_gifts_day"


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _day() -> str:
    """Today, as the SERVER counts it — the same key the arms and rally books use."""
    import datetime
    try:
        import game_clock                     # lazy: tools/lib is on the panel's path
        import game_day
        stamp = game_clock.now_ms()
    except Exception:                         # noqa: BLE001 — no tools path, no game
        stamp = None
    if not stamp:
        return datetime.datetime.utcnow().date().isoformat()
    return game_day.day_key(stamp)


def read(rt) -> dict:
    """Today's book, or an empty one — never yesterday's, never an exception."""
    today = _day()
    try:
        held = rt.store.blob_get(BLOB)
    except Exception:                         # noqa: BLE001 — a tally, never the page
        held = None
    if not isinstance(held, dict) or held.get("day") != today:
        return {"day": today, "took": 0, "runs": 0, "at": None}
    return {"day": today, "took": _int(held.get("took")),
            "runs": _int(held.get("runs")), "at": held.get("at")}


def note(rt, ctx) -> None:
    """Add what one finished run took. Handed the run's own context and nothing else.

    `gift_took` is the recipe's own answer — the unclaimed count before the claim minus
    the one after — so a run that found both chests empty adds a run and no gifts, and a
    run whose claim did nothing has already FAILed before this is reached.
    """
    got = (getattr(ctx, "vars", None) or {})
    if "gift_took" not in got:
        return
    took = max(0, _int(got.get("gift_took")))
    book = read(rt)
    book["took"] += took
    book["runs"] += 1
    book["at"] = time.time()
    try:
        rt.store.blob_set(BLOB, book)
    except Exception:                         # noqa: BLE001 — a tally, never the run
        pass


def today(rt) -> int:
    """Gifts taken since the server's midnight, as the book knows it."""
    return _int(read(rt).get("took"))


def wire(rt) -> None:
    """Have the schedule tell this book about every finished run of the errand.

    Called where the schedule is built (`PanelRuntime.schedule`), because this errand has
    no tab of its own to do the wiring the way «События» does for the arms book.
    """
    schedule = getattr(rt, "schedule", None)
    if schedule is None or not hasattr(schedule, "register_report"):
        return
    schedule.register_report("collect_alliance_gifts", lambda ctx: note(rt, ctx))
