"""The LAST reading of «Мировой поход» — one state, kept where every page finds it.

Written for #2852. The event lives in the «База мирового похода»: a round of fourteen
days with four zones that unlock on days 1, 3, 5 and 7, an auto challenge that climbs
the stages until the lineup loses one, and two lists of rewards
(`docs/research/world-expedition.md`).

NOTHING HERE TICKS. The reading is taken when the client gets into the game
(`bus.GAME_READY`), when the event's own records arrive on the wire — a zone unlocking
(`push.season.tower.open`) and the season's own update — and on the way out of every run
of the errand that plays it. There is no clock and no «Обновить» button anywhere, which
is the rule this module exists to obey (`CLAUDE.md`, «Read once, then LISTEN», and «A
STATISTIC IS NOT REFRESHED BY HAND»).

WHAT IS STORED is the line exactly as the scenario handed it over, plus the moment it
landed::

    {"expedition": "known=1 open=1 zones=4 live=3 unset=0 rewards=0 score=1217
                    next_score=2250 starts=1789005600 ends=1790215199
                    next_zone=1789524000 safe=0 o1=1 f1=466 h1=1 r1=0 …",
     "at": 1789357326.0}

The raw line rather than a parsed dictionary, for the same reason `invasion_live` keeps
what the game said: a panel that learns to read one more field of it tomorrow reads that
field out of what is already written down.
"""
from __future__ import annotations

import re
import threading
import time

from . import bus, claims

#: The row in this profile's `blobs` table. Read and written WHOLE, and small — a blob,
#: not a table of its own (`docs/panel-storage.md`).
BLOB = "expedition_live"

#: The scenario that does the reading, and the variable it leaves the line in.
ACTION = "read_world_expedition"
VARIABLE = "expedition"

#: The errand that plays the event; every run of it refreshes this reading for free.
ERRAND = "world_expedition"

#: The records that move the event. A zone unlocking is the one moment a card can go out
#: of date while nobody is looking; the season's own update carries the rest.
PUSHES = ("push.season.tower.open", "push.season.info.update")

#: The shortest gap between two readings, in seconds. A burst of one push must cost ONE
#: reading — the rule every wire subscriber in this panel obeys.
DEBOUNCE_SEC = 20.0

#: The one-shot first look, armed exactly as `invasion_live` arms its own and for the
#: same reasons: `bus.GAME_READY` is an EDGE, and a panel that has just restarted is
#: refused by its own link gate for as long as the attachment takes. It comes back until
#: a reading LANDS, and no longer.
FIRST_LOOK_MS = 20_000
FIRST_LOOK_TRIES = 90

#: The tick chain the first look uses. One per profile's runtime, like every other.
CHAIN_FIRST = "expedition_first_read"

#: What a numeric field of the line looks like.
_NUM = re.compile(r"\b([a-z_]+\d*)=(-?\d+)\b")


def record(rt, raw) -> None:
    """Keep what a reading of the expedition said. Never raises — it is a tally."""
    try:
        rt.store.blob_set(BLOB, {"expedition": str(raw or ""), "at": time.time()})
    except Exception:                    # noqa: BLE001 — a reading, never the run
        pass


def read(rt) -> dict:
    """The row as it stands, or an empty one."""
    try:
        held = rt.store.blob_get(BLOB)
    except Exception:                    # noqa: BLE001 — a reading, never the page
        held = None
    return held if isinstance(held, dict) else {}


def parse(raw) -> dict:
    """The line's numeric fields. An unreadable line is an empty dict, never a raise."""
    return {k: int(v) for k, v in _NUM.findall(str(raw or ""))}


def state(rt) -> tuple:
    """`(fields, age)` — what a card draws, and how old the reading is.

    `age` is `None` when nothing has ever been read, and the fields are then empty: a
    card with no reading says so in words rather than drawing zeros nobody measured.
    """
    held = read(rt)
    raw = held.get("expedition")
    try:
        at = float(held.get("at") or 0)
    except (TypeError, ValueError):
        at = 0.0
    if not raw:
        return {}, None
    return parse(raw), (max(0.0, time.time() - at) if at else None)


def report(rt, ctx) -> None:
    """Keep whatever a finished run read about the expedition. Never raises."""
    try:
        values = getattr(ctx, "vars", {}) or {}
        raw = values.get(VARIABLE)
    except Exception:                    # noqa: BLE001 — a tally, never the run
        return
    if raw:
        record(rt, raw)


class ExpeditionWatch:
    """This profile's ear for «Мировой поход»: one first reading, then the record.

    Nothing here ticks. :meth:`start` subscribes to the things that can move the event —
    the client entering the game, a zone unlocking, the season's own update — and each of
    them books ONE reading, debounced.
    """

    def __init__(self, rt) -> None:
        self._rt = rt
        self._lock = threading.Lock()
        self._last = 0.0
        self._busy = False
        self._offs: list = []
        self._read_once = False
        self._tries = 0

    # -- wiring --------------------------------------------------------------
    def start(self) -> None:
        """Listen, and hook the errand's own report. Safe to call twice."""
        if self._offs:
            return
        try:
            self._offs.append(self._rt.bus.subscribe(bus.GAME_READY, self._on_ready))
        except Exception:                # noqa: BLE001 — the panel still works
            self._rt.dbg("expedition").error("could not listen for the game",
                                             exc_info=True)
        for command in PUSHES:
            try:
                self._offs.append(self._rt.wire.subscribe(command, self._on_push))
            except Exception:            # noqa: BLE001 — the record is a bonus
                self._rt.dbg("expedition").error("could not listen for %s" % command,
                                                 exc_info=True)
        # …AND EVERY RUN OF THE ERRAND REFRESHES THE READING. The recipe reads the event
        # as its first and last act, so the freshest answer in the panel is the one the
        # run just took — taking it again on a clock would be the poll the rule forbids.
        schedule = getattr(self._rt, "schedule", None)
        if schedule is not None and hasattr(schedule, "register_report"):
            try:
                schedule.register_report(ERRAND, lambda ctx: report(self._rt, ctx))
            except Exception:            # noqa: BLE001 — then the ear is the only door
                self._rt.dbg("expedition").error("could not hook the errand",
                                                 exc_info=True)
        self._arm_first()

    def _arm_first(self) -> None:
        """Book the one-shot first look. Does nothing where there is no queue at all."""
        try:
            self._rt.tick.arm(CHAIN_FIRST, FIRST_LOOK_MS, self._first_look)
        except Exception:                # noqa: BLE001 — then the ready fact is the only
            pass                         #   door, which is the ordinary case

    def _first_look(self) -> None:
        """Read once if nothing has been read yet, and come back only until it has."""
        if self._read_once:
            return
        self._tries += 1
        if self._tries > FIRST_LOOK_TRIES:
            return
        # A SHUT GATE COSTS NOTHING AT ALL: playing into it only prints «нет связи с
        # игрой» once a look, about a state the panel already knows and is showing.
        held = False
        try:
            held = bool(self._rt.gate.held())
        except Exception:                # noqa: BLE001 — no gate means: just look
            held = False
        if held:
            self._arm_first()
            return
        self.refresh("first")
        if not self._read_once:
            self._arm_first()

    def stop(self) -> None:
        for off in self._offs:
            try:
                off()
            except Exception:            # noqa: BLE001 — leaving, never raising
                pass
        self._offs = []

    # -- the things that move it ---------------------------------------------
    def _on_ready(self, _payload=None) -> None:
        self.refresh("game")

    def _on_push(self, _command="") -> None:
        # On the ear's reader thread: book a reading and get out of the way.
        self.refresh("push")

    # -- the reading ----------------------------------------------------------
    def refresh(self, why: str = "") -> bool:
        """Take one reading, unless one is already out or one was taken just now."""
        now = time.time()
        with self._lock:
            if self._busy or (now - self._last) < DEBOUNCE_SEC:
                return False
            self._busy = True
            self._last = now
        started = False
        try:
            started = self._rt.play_async(
                ACTION, tag="expedition", priority=claims.BACKGROUND,
                on_result=self._back, on_done=self._done)
        finally:
            if not started:
                # A REFUSAL DOES NOT BURN THE DEBOUNCE.
                with self._lock:
                    self._last = 0.0
                self._done()
        return started

    def _done(self, *_a) -> None:
        with self._lock:
            self._busy = False

    def _back(self, outcome) -> None:
        if outcome is None or not getattr(outcome, "ok", False):
            return
        ctx = getattr(outcome, "ctx", None)
        values = getattr(ctx, "vars", {}) or {}
        raw = values.get(VARIABLE)
        if raw:
            record(self._rt, raw)
            self._read_once = True
