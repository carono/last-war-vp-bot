"""The LAST reading of «Сверкающий рынок» — one state, kept where both pages find it.

Written for the two cards on «Таймеры» (#2636). The event has no page of its own, so
there is no tab whose memory could hold the reading and no tab whose poll could take it —
and that is exactly the shape `CLAUDE.md` («A STATISTIC IS NOT REFRESHED BY HAND») asks
for anyway: the reading is taken ONCE when the client gets into the game, again on the
event's own push, and never on a clock. There is no «Обновить» anywhere for it.

WHY IT IS AFFORDABLE AT ALL. The whole record arrives with the activity and the server
keeps it up to date (`docs/research/glittering-market.md`), so
`actions/read_glittering_market.md` is one round trip against the client's own memory and
not one question goes on the wire.

WHAT IS STORED is the reading exactly as the scenario handed it over, plus the moment it
landed::

    {"market": "open=1 starts=… ends=… free=1 goods_free=… coins=… free_item=…",
     "at": 1788859000.0}

The raw line rather than a parsed dictionary, for the same reason `arms_live` keeps what
the game said: a panel that learns to read one more field of it tomorrow reads that field
out of what is already written down, instead of finding a shape somebody froze today.

ON THE RUNTIME AND NOT ON A PAGE, like `firework_wire` and `rally_wire`: a listener that
lives on a tab is absent in every profile that does not draw that tab, and this event has
no tab at all. It is a PROFILE'S OWN, like the log and the schedule (`CLAUDE.md`, «A
profile is a whole panel of its own»).
"""
from __future__ import annotations

import re
import threading
import time

from . import bus, claims

#: The row in this profile's `blobs` table. Read and written WHOLE, and small — a blob,
#: not a table of its own (`docs/panel-storage.md`).
BLOB = "market_live"

#: The scenario that does the reading, and the variable it leaves the line in.
ACTION = "read_glittering_market"
VARIABLE = "market"

#: The one push the event has: the progress score moved, which happens when coins are
#: bought. Everything else about the market changes because WE pressed something, and a
#: press re-reads on its own way out (`collect_glittering_market.md` ends with a read).
PUSH = "push.blue.shop.sc"

#: The shortest gap between two readings, in seconds. A burst of one push must cost ONE
#: reading — the rule every wire subscriber in this panel obeys.
DEBOUNCE_SEC = 20.0

#: The one-shot first look, and how many times it may come back BEFORE it has ever read
#: anything. It is not a poll and it is not a clock over the game: `bus.GAME_READY` is
#: published on the EDGE of entering the game, and a panel restarted over a client that
#: was already playing never sees that edge — the same gap `panel/tabs/vs.py` arms
#: `_first_look` for. The one that bit here is narrower still: the edge DOES arrive after
#: a restart, and the play is refused because the panel's own gate is still amber that
#: early («нет связи с игрой — ничего автоматического не стартует»), and an edge does not
#: come round again. So this waits for the PANEL's link rather than asking the GAME
#: anything, and it stops the moment a reading lands or after the last try.
FIRST_LOOK_MS = 20_000
FIRST_LOOK_TRIES = 6

#: …and how long it may keep WAITING while the panel's own gate is shut, in looks of
#: :data:`FIRST_LOOK_MS`. A shut gate is not a failed reading: after a restart the link
#: to the client is re-made, and on this machine that took over three minutes with three
#: profiles coming up at once. While the gate is held nothing is played at all — the
#: look simply books itself again — so the wait costs a dict lookup a look and not one
#: message to the game. It gives up after this many so that a client which never comes
#: back cannot leave a booking behind for ever.
GATE_WAIT_TRIES = 90

#: The tick chain the first look uses. One per profile's runtime, like every other.
CHAIN_FIRST = "market_first_read"

#: What a numeric field of the line looks like.
_NUM = re.compile(r"\b([a-z_]+)=(-?\d+)\b")


def record(rt, raw) -> None:
    """Keep what a reading of the market said. Never raises — it is a tally."""
    try:
        rt.store.blob_set(BLOB, {"market": str(raw or ""), "at": time.time()})
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
    """The line's fields. Numbers as ints; `free_item` is whatever follows it to the end.

    An unreadable line is an empty dict rather than an exception: a card missing a line
    is a card, and a card raising is a page.
    """
    text = str(raw or "")
    out: dict = {k: int(v) for k, v in _NUM.findall(text)}
    where = text.find("free_item=")
    if where >= 0:
        out["free_item"] = text[where + len("free_item="):].strip()
    return out


def state(rt) -> tuple:
    """`(fields, age)` — what the cards draw, and how old the reading is.

    `age` is `None` when nothing has ever been read, and the fields are then empty: a
    card with no reading says so in words rather than drawing zeros nobody measured.
    """
    held = read(rt)
    raw = held.get("market")
    try:
        at = float(held.get("at") or 0)
    except (TypeError, ValueError):
        at = 0.0
    if not raw:
        return {}, None
    return parse(raw), (max(0.0, time.time() - at) if at else None)


class MarketWatch:
    """This profile's ear for the Glittering Market: one first reading, then the push.

    Nothing here ticks. :meth:`start` subscribes to the two things that can move the
    event — the client entering the game, and the event's own score push — and each of
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
            self._rt.dbg("market").error("could not listen for the game", exc_info=True)
        try:
            self._offs.append(self._rt.wire.subscribe(PUSH, self._on_push))
        except Exception:                # noqa: BLE001 — the push is a bonus
            self._rt.dbg("market").error("could not listen for the push", exc_info=True)
        self._arm_first()

    def _arm_first(self) -> None:
        """Book the one-shot first look. Does nothing where there is no queue at all."""
        try:
            self._rt.tick.arm(CHAIN_FIRST, FIRST_LOOK_MS, self._first_look)
        except Exception:                # noqa: BLE001 — then the ready fact is the only
            pass                         #   door, which is the ordinary case

    def _first_look(self) -> None:
        """Read once if nothing has been read yet, and come back only until it has.

        It does NOT re-arm after a reading lands, and it does not re-arm after the last
        try: what it is waiting out is the few seconds between the panel coming up and
        its own game link being usable, not the game.
        """
        if self._read_once:
            return
        self._waited += 1
        if self._waited > GATE_WAIT_TRIES:
            return
        # A SHUT GATE IS NOT A TRY. Playing into it only prints «нет связи с игрой» once
        # a look, which is noise about a state the panel already knows and is already
        # showing; so the look books itself again and spends nothing.
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
                ACTION, tag="market", priority=claims.BACKGROUND,
                on_result=self._back, on_done=self._done)
        finally:
            if not started:
                # A REFUSAL DOES NOT BURN THE DEBOUNCE. The gate says no while the link
                # is not up yet, and holding the next signal off for twenty seconds
                # because of that is how a panel ends up never reading at all.
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
