"""The LAST reading of «Судный день» — one state, kept where every page finds it.

Written for #2842, and shaped exactly like :mod:`panel.runtime.market_live`, for the same
reasons: the event has no page whose opening could take the first reading, and a board of
readings is never refreshed by hand (`CLAUDE.md`, «A STATISTIC IS NOT REFRESHED BY HAND»).
So the reading is taken ONCE when the client gets into the game, again on the event's own
push, and on nothing else. There is no «Обновить» for it anywhere.

WHAT THE EVENT IS. A Sunday's run of achievements — the game announces its window with
the activity itself, and pays out an achievement's gift when it is claimed. The list is
the one part of it the client does not keep, so a reading asks for it once
(`actions/read_doomsday.md`, `docs/research/doomsday.md`).

WHAT IS STORED is the line the scenario handed over, plus the moment it landed::

    {"doomsday": "known=1 open=1 starts=… ends=… quests=41 taken=38 pending=3 red=0",
     "at": 1789279000.0}

The raw line rather than a parsed dictionary, for the reason `market_live` keeps what the
game said: a panel that learns to read one more field of it tomorrow reads that field out
of what is already written down, instead of finding a shape somebody froze today.
"""
from __future__ import annotations

import re
import threading
import time

from . import bus, claims

#: The row in this profile's `blobs` table. Read and written WHOLE, and small — a blob,
#: not a table of its own (`docs/panel-storage.md`).
BLOB = "doomsday_live"

#: The scenario that does the reading, and the variable it leaves the line in.
ACTION = "read_doomsday"
VARIABLE = "doomsday"

#: The one push the event has: an achievement of it moved. It is what makes a gift
#: appear, so it is also the only moment a reading can go out of date by itself —
#: everything else about the event changes because WE pressed something, and a press
#: re-reads on its own way out (`collect_doomsday_gifts.md` ends with a read).
PUSH = "push.doomsday.quest"

#: The shortest gap between two readings, in seconds. A burst of one push must cost ONE
#: reading — the rule every wire subscriber in this panel obeys.
DEBOUNCE_SEC = 20.0

#: The one-shot first look, and how many times it may come back BEFORE it has ever read
#: anything. Not a poll and not a clock over the game: `bus.GAME_READY` is published on
#: the EDGE of entering the game, and the play made on that edge is refused while the
#: panel's own gate is still amber. `market_live` explains the whole of it — this holds
#: the same numbers so that two ears started together behave the same way.
FIRST_LOOK_MS = 20_000
FIRST_LOOK_TRIES = 6
GATE_WAIT_TRIES = 90

#: The tick chain the first look uses. One per profile's runtime, like every other.
CHAIN_FIRST = "doomsday_first_read"

#: What a numeric field of the line looks like.
_NUM = re.compile(r"\b([a-z_]+)=(-?\d+)\b")


def record(rt, raw) -> None:
    """Keep what a reading of the event said. Never raises — it is a tally."""
    try:
        rt.store.blob_set(BLOB, {"doomsday": str(raw or ""), "at": time.time()})
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
    """The line's fields, as ints. An unreadable line is an empty dict, never a raise."""
    return {k: int(v) for k, v in _NUM.findall(str(raw or ""))}


def state(rt) -> tuple:
    """`(fields, age)` — what the card draws, and how old the reading is.

    `age` is `None` when nothing has ever been read, and the fields are then empty: a
    card with no reading says so in words rather than drawing zeros nobody measured.
    """
    held = read(rt)
    raw = held.get("doomsday")
    try:
        at = float(held.get("at") or 0)
    except (TypeError, ValueError):
        at = 0.0
    if not raw:
        return {}, None
    return parse(raw), (max(0.0, time.time() - at) if at else None)


class DoomsdayWatch:
    """This profile's ear for «Судный день»: one first reading, then the push.

    Nothing here ticks. :meth:`start` subscribes to the two things that can move the
    event — the client entering the game, and the event's own quest push — and each of
    them books ONE reading, debounced. A panel whose client is not up reads nothing, for
    ever.
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
            self._rt.dbg("doomsday").error("could not listen for the game", exc_info=True)
        try:
            self._offs.append(self._rt.wire.subscribe(PUSH, self._on_push))
        except Exception:                # noqa: BLE001 — the push is a bonus
            self._rt.dbg("doomsday").error("could not listen for the push", exc_info=True)
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

    def stop(self) -> None:
        for off in self._offs:
            try:
                off()
            except Exception:            # noqa: BLE001 — leaving, never raising
                pass
        self._offs = []

    # -- the two things that move it -----------------------------------------
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
                ACTION, tag="doomsday", priority=claims.BACKGROUND,
                on_result=self._back, on_done=self._done)
        finally:
            if not started:
                # A refusal does not burn the debounce — `market_live` explains why.
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
