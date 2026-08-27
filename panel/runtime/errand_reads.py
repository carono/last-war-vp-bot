"""The ONE reading the timers page is allowed to take, and the rules it obeys (#2019).

WHY THERE IS ONE AT ALL. Every other line on «Таймеры» comes off something the panel
already had (`panel/runtime/errand_stats.py`). One did not and was asked for daily: the
truck's bubble — «стоит ли сейчас жать «Сбор с грузовика»». It has no push, nothing
caches it, and the only way to know is to look. So it was taken to the person rather than
written, and the person's answer was: **«Ок, делай» — читать при ОТКРЫТИИ страницы, не
чаще раза в минуту, только пока страницу реально смотрят, приоритетом ниже работы бота,
занят линк — пропускаем такт, возраст показан рядом с числом.** Those five conditions are
this module, one to a rule below, and none of them may be relaxed without asking again.

WHY THE READING IS THE WHOLE CHECKLIST AND NOT THE TRUCK ALONE. `read_daily_checklist.md`
already exists, already answers the truck's bubble (`trucks_ready`), and answers a dozen
other questions in the SAME chunk — the cost of a play is the panel↔VM round trip, not
the work inside it (measured on the resource read: 175 ms for six readings against 168 for
one). So the approved cost buys the truck and gives the rest away: help waiting, donations
left, visitors at the gate, decoration steps, trade trucks still to send. Reading only the
truck would cost exactly the same and answer less.

WHAT IT IS NOT. Not a clock and not a watcher: nothing here ticks. A read can only be
booked from inside :meth:`look`, which the timers route calls when a page ASKS for the
rows — so a panel nobody is looking at reads nothing, for ever, and closing the page stops
it within :data:`LOOK_SEC` (`CLAUDE.md`, «Read once, then LISTEN — and nothing runs in the
background unasked»).

THE INTERVAL, and why exactly this one: the answers move on the scale of minutes (a truck
arrives, a donation window opens), the page is looked at for seconds at a time, and the
link is exclusive — one read a minute is under 0.4 % of it. **Do not shorten it because a
number looked stale**: a stale number with its age beside it is the honest picture, and
the age is drawn for exactly that reason.
"""
from __future__ import annotations

import time

from . import claims

#: The scenario that does the reading — the checklist's own, played whole.
ACTION = "read_daily_checklist"

#: The floor between two reads, in seconds. The person's own number: «не чаще раза в
#: минуту».
MIN_GAP_SEC = 60.0

#: How long a look counts for. The page polls every few seconds, so anything above the
#: poll keeps a read booked while somebody is there; a shut page stops asking and this is
#: how long until the last look expires and nothing is read again.
LOOK_SEC = 90.0

#: How long to wait after a refusal — a busy link, a shut gate, a play that would not
#: start. Long enough that the refusal is not itself the thing being repeated.
RETRY_SEC = 60.0


class DailyReads:
    """One profile's checklist reading: the cache, the look, and the once-a-minute rule.

    Held by the runtime as `rt.daily_reads`, exactly like `rt.resources` — per PROFILE
    and never module-level, because it reads THIS account's client (`CLAUDE.md`, «A
    profile is a whole panel of its own»).
    """

    def __init__(self, rt, clock=time.time) -> None:
        self._rt = rt
        self._clock = clock
        self._values: dict = {}
        self._at = 0.0                   # when the values were read, 0 = never
        self._reading = False
        self._hold_until = 0.0
        self._looked_at = 0.0

    # -- what the page sees --------------------------------------------------
    def cached(self, now: float | None = None) -> dict:
        """What was last read, with its age. `age` of -1 means «never read»."""
        now = self._clock() if now is None else now
        return {"values": dict(self._values),
                "age": round(now - self._at, 1) if self._at else -1}

    def look(self, now: float | None = None) -> None:
        """Somebody is looking at the page — book a read if one is due.

        Called by the route that draws the errands and by nothing else. This is the
        whole of «при открытии страницы»: no clock, no thread, no subscription.
        """
        now = self._clock() if now is None else now
        self._looked_at = now
        self._maybe_read(now)

    # -- the read ------------------------------------------------------------
    def _maybe_read(self, now: float) -> None:
        if self._reading or now < self._hold_until:
            return
        # NOT UNLESS SOMEBODY IS ACTUALLY THERE. `look` is the only caller, so this is
        # belt and braces — and it is what makes a stale look (a page left open in a
        # background tab that stopped polling) fail to book anything.
        if now - self._looked_at > LOOK_SEC:
            return
        if self._at and now - self._at < MIN_GAP_SEC:
            return
        # THE LINK IS EXCLUSIVE AND SOMETHING ELSE IS ON IT — skip the tick rather than
        # queue behind it. The bot's own work is worth more than a line on a page, which
        # is the person's condition and the reason for `DETACHED` below as well.
        try:
            if self._rt.game.busy:
                self._hold_until = now + RETRY_SEC
                self._why("the link is busy")
                return
        except Exception as exc:         # noqa: BLE001 — an unreadable link is not a
            self._why("the link cannot be read: %s" % exc)
            return                       #   licence to press
        # ASKED SILENTLY: `play_async` gates too and writes a refusal line, which for a
        # page that is open for minutes would fill the log the person came to read.
        try:
            held = self._rt.gate.blocks(ACTION, human=False)
            if held:
                self._why("the gate holds it: %s" % held)
                return
        except Exception as exc:         # noqa: BLE001
            self._why("the gate cannot answer: %s" % exc)
            return
        self._reading = True
        started = self._rt.play_async(ACTION, tag="errand-stats", human=False,
                                      priority=claims.DETACHED,
                                      on_result=self._from_run)
        if not started:
            self._reading = False
            self._hold_until = now + RETRY_SEC
            self._why("the play would not start")

    def _why(self, reason: str) -> None:
        """Why a look booked nothing — on the profile's own debug channel, never the log.

        A skip that says nothing is indistinguishable from a feature that does not work,
        and that is exactly what it cost the first time: the page drew no line and there
        was no way to tell a busy link from a bug. `dbg` and not `say`, because this is a
        page being polled and it must not write into what a person reads.
        """
        try:
            self._rt.dbg("errand-stats").debug("no reading booked: %s", reason)
        except Exception:                # noqa: BLE001 — a debug line, never the page
            pass

    def _from_run(self, outcome) -> None:
        """The play came back: keep what it read, or keep the old values and age them.

        A client that answered nothing is not a base with nothing on it — the previous
        numbers stay with their age climbing, which is the honest picture and the reason
        the age is drawn at all.
        """
        self._reading = False
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        raw = got.get("daily")
        values = _parse(raw)
        if not values:
            return
        self._values = values
        self._at = self._clock()


def _parse(raw) -> dict:
    """`k=v k=v` into `{k: int}` — the checklist's own shape, `-` for «would not say».

    Parsed here rather than imported from the tab: `panel/runtime/` must not depend on a
    tab being installed, and this is four lines of the same rule (`model.parse`).
    """
    values: dict = {}
    for piece in str(raw or "").split():
        key, sep, value = piece.partition("=")
        if not key or not sep or value in ("-", ""):
            continue
        try:
            values[key] = int(float(value))
        except ValueError:
            continue
    return values
