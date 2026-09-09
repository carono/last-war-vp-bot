"""The LAST reading of the arena building — one state, kept where the card finds it.

Written for the arena card on «Таймеры» (#2688), and the person asked for exactly two
things on it: **which arena is running right now, and the score**. Both are read out of
the game and neither is a schedule written down here — the building runs ONE event at a
time (the 3v3 challenge and «Арена Шторма») and swaps it when the old one ends, so the
question «which» has to be asked of the two managers' own windows every time.

THE RULE THIS MODULE OBEYS. `CLAUDE.md`, «Read once, then LISTEN» and «A STATISTIC IS NOT
REFRESHED BY HAND»: the reading is taken ONCE when the client gets into the game, and
after that only at a moment the state is KNOWN to have moved. There is no «Обновить»
anywhere for it and there is no clock behind it.

AND THE ARENA HAS NO PUSH, which is why this one has an alarm where `market_live` has a
subscription. The score moves when a battle is fought — ours, which is the errand and
which re-reads on its way out, or somebody else's against us, which the server does not
announce. So the two moments that are known are the ones the person named: **the event's
own end**, when the building swaps what it is running, and **the day's reset**, when the
attempts come back. The reading books itself for whichever of the two is nearer and for
nothing else — one alarm, at a moment, never an interval (`docs/research/arena-3v3.md`,
`docs/research/storm-arena.md`).

WHAT IS STORED is the line exactly as the scenario handed it over, plus when it landed::

    {"arena": "which=storm open=1 score=1039 rank=358 done=5 …", "at": 1788971000.0}

The raw line rather than a parsed dictionary, for the reason `market_live` keeps what the
game said: a panel that learns to read one more field of it tomorrow reads that field out
of what is already written down instead of a shape somebody froze today.

ON THE RUNTIME AND NOT ON A PAGE, like `market_live` and `invasion_live`: the arena has
no tab of its own, its card lives on «Таймеры», and a listener that lives on a tab is
absent in every profile that does not draw that tab. It is a PROFILE'S OWN (`CLAUDE.md`,
«A profile is a whole panel of its own»).
"""
from __future__ import annotations

import re
import threading
import time

from . import bus, claims

#: The row in this profile's `blobs` table. Read and written WHOLE, and small — a blob,
#: not a table of its own (`docs/panel-storage.md`).
BLOB = "arena_live"

#: The scenario that does the reading, and the variable it leaves the line in.
ACTION = "read_arena"
VARIABLE = "arena"

#: The shortest gap between two readings, in seconds. Two signals arriving together —
#: the game coming up and an alarm falling due — must cost ONE reading.
DEBOUNCE_SEC = 20.0

#: The one-shot first look, armed exactly as `market_live` arms it and for the same
#: reason: `bus.GAME_READY` arrives while the panel's own gate is still shut after a
#: restart, the play is refused, and an edge does not come round again.
FIRST_LOOK_MS = 20_000
FIRST_LOOK_TRIES = 6
GATE_WAIT_TRIES = 90

#: The tick chains this watch owns: the first look, and the one alarm.
CHAIN_FIRST = "arena_first_read"
CHAIN_NEXT = "arena_next_read"

#: The floor and the ceiling on that alarm, in seconds. The floor keeps an event whose
#: window has just this second closed from booking a reading a second later, over and
#: over; the ceiling is there because a reading a day away is a reading nothing would
#: notice was never taken, and re-arming a whole day is free.
SOONEST_SEC = 60.0
FURTHEST_SEC = 6 * 60 * 60.0

#: What a field of the line looks like. `which` is a word; everything else is a number
#: or the dash that means «the game would not say».
_FIELD = re.compile(r"\b([a-z_]+)=(-?\d+|-|[a-z0-9]+)\b")


def record(rt, raw) -> None:
    """Keep what a reading of the arena said. Never raises — it is a reading."""
    try:
        rt.store.blob_set(BLOB, {"arena": str(raw or ""), "at": time.time()})
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
    """The line's fields — `which` as a word, the rest as ints, a dash left out.

    A field the game would not answer is ABSENT rather than zero: «nobody knows» and
    «none» are different answers and the whole value of a reading is telling them apart.
    """
    out: dict = {}
    for key, value in _FIELD.findall(str(raw or "")):
        if value == "-":
            continue
        if key == "which":
            out[key] = value
            continue
        try:
            out[key] = int(value)
        except ValueError:
            out[key] = value
    return out


def state(rt) -> tuple:
    """`(fields, age)` — what the card draws, and how old the reading is.

    `age` is `None` when nothing has ever been read, and the fields are then empty: a
    card with no reading says so in words rather than drawing zeros nobody measured.
    """
    held = read(rt)
    raw = held.get(VARIABLE)
    try:
        at = float(held.get("at") or 0)
    except (TypeError, ValueError):
        at = 0.0
    if not raw:
        return {}, None
    return parse(raw), (max(0.0, time.time() - at) if at else None)


class ArenaWatch:
    """This profile's ear for the arena: one first reading, then one alarm at a time.

    Nothing here ticks. :meth:`start` listens for the client entering the game; every
    reading books the NEXT one for the moment the state is known to move — the event's
    own end or the day's reset, whichever is nearer. A panel whose client is not up
    reads nothing, for ever.
    """

    def __init__(self, rt) -> None:
        self._rt = rt
        self._lock = threading.Lock()
        self._last = 0.0
        self._busy = False
        self._offs: list = []
        self._read_once = False
        self._tries = 0
        self._waited = 0

    # -- wiring --------------------------------------------------------------
    def start(self) -> None:
        """Listen. Safe to call twice — the second call adds nothing."""
        if self._offs:
            return
        try:
            self._offs.append(self._rt.bus.subscribe(bus.GAME_READY, self._on_ready))
        except Exception:                # noqa: BLE001 — the panel still works
            self._rt.dbg("arena").error("could not listen for the game", exc_info=True)
        self._arm_first()

    def stop(self) -> None:
        for off in self._offs:
            try:
                off()
            except Exception:            # noqa: BLE001 — leaving, never raising
                pass
        self._offs = []
        for chain in (CHAIN_FIRST, CHAIN_NEXT):
            try:
                self._rt.tick.disarm(chain)
            except Exception:            # noqa: BLE001 — leaving, never raising
                pass

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
        self._waited += 1
        if self._waited > GATE_WAIT_TRIES:
            return
        held = False
        try:
            held = bool(self._rt.gate.held())
        except Exception:                # noqa: BLE001 — no gate means: just look
            held = False
        if held:
            self._arm_first()
            return
        if self._tries >= FIRST_LOOK_TRIES:
            return
        self._tries += 1
        self.refresh("first")
        if not self._read_once:
            self._arm_first()

    def _on_ready(self, _payload=None) -> None:
        self.refresh("game")

    # -- the alarm ------------------------------------------------------------
    def _book_next(self, fields: dict) -> None:
        """Arm ONE reading, at the nearer of the event's end and the day's reset.

        Neither is a guess: `until` is the event's own remaining seconds as the game
        counts them, and the reset is this profile's own day boundary. A state with
        neither — no arena at all, a reading that failed — books nothing, and the game
        coming back is then the only door, which is the honest answer.
        """
        whens = []
        rest = fields.get("until")
        if isinstance(rest, int) and rest > 0:
            whens.append(float(rest))
        try:
            now = time.time()
            whens.append(max(0.0, float(self._rt.day.next_reset_epoch(now)) - now))
        except Exception:                # noqa: BLE001 — a day nobody could name
            pass
        whens = [w for w in whens if w > 0]
        if not whens:
            return
        delay = min(min(whens) + 5.0, FURTHEST_SEC)
        if delay < SOONEST_SEC:
            delay = SOONEST_SEC
        try:
            self._rt.tick.arm(CHAIN_NEXT, int(delay * 1000), self._on_alarm)
        except Exception:                # noqa: BLE001 — then the game's own edge is it
            pass

    def _on_alarm(self) -> None:
        self.refresh("alarm")

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
                ACTION, tag="arena", priority=claims.BACKGROUND,
                on_result=self._back, on_done=self._done)
        finally:
            if not started:
                # A REFUSAL DOES NOT BURN THE DEBOUNCE — `market_live` explains why.
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
            self._book_next(parse(raw))
