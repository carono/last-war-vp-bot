"""The LAST reading of «Вторжение зомби» — one state, kept where every page finds it.

Written for #2647: «карточка с золотыми зомби работает и без события вторжение зомби,
нужно учитывать и не гонять в пустую». The golden zombies are the invasion's own
monsters and exist only while it runs, so a hunt started outside its window walked the
whole opening — the world scene, a squad refill, the day's free energy, a refill bought
for diamonds, a lap of the map — to discover an empty list.

TWO GATES, AND THEY ANSWER DIFFERENT QUESTIONS. The ABILITY's gate is in the recipe,
where `CLAUDE.md` says it belongs (`actions/attack_golden_zombies.md` opens with
`CALL read_zombie_invasion` and stops on a closed one). This module is the SCHEDULE's:
while the panel already knows the event is shut, the errand is not started at all —
no claim, no context, no reading — which is the same shape #2636 gave the market's
first look, and the reason a shut window costs nothing at all rather than one reading
an hour.

NOTHING HERE TICKS. The reading is taken when the client gets into the game
(`bus.GAME_READY`), when the invasion's own record arrives on the wire, and when a hunt
run reads it on its way past. A reading that has gone stale is treated as NO reading, so
the errand runs and refreshes it: the panel never holds a run back on the strength of
something it cannot vouch for.

WHAT IS STORED is the line exactly as the scenario handed it over, plus the moment it
landed::

    {"invasion": "open=0 inv=0 act=0 starts=0 ends=0 season=6 day=16 next_day=57
                  next_at=1792375200 seen=0 asked=1",
     "at": 1788883372.0}

The raw line rather than a parsed dictionary, for the same reason `market_live` keeps
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
BLOB = "invasion_live"

#: The scenario that does the reading, and the variable it leaves the line in.
ACTION = "read_zombie_invasion"
VARIABLE = "invasion"

#: The errand this holds back while the event is shut.
ERRAND = "attack_golden_zombies"

#: What the schedule says when it holds that errand back.
SKIP_KEY = "timers.log.skip_invasion_off"

#: The record the invasion travels in. The client asks for it at login and the server
#: sends it again when the event moves, so it is the one signal there is.
PUSH = "monster.invasion.act.info"

#: The shortest gap between two readings, in seconds. A burst of one push must cost ONE
#: reading — the rule every wire subscriber in this panel obeys.
DEBOUNCE_SEC = 20.0

#: HOW LONG A CLOSED READING IS TRUSTED, in seconds. Longer than the hunt's own hour, so
#: an ordinary evening costs no run at all; short enough that a panel left up for days
#: cannot sit out a whole invasion on the strength of one old answer. A reading older
#: than this is treated as no reading: the errand runs, the recipe's own gate stops it
#: in one round trip, and the store is refreshed by that very run.
STALE_SEC = 6 * 3600.0

#: The one-shot first look, exactly as `market_live` arms it and for the same reasons:
#: `bus.GAME_READY` is an EDGE, and a panel that has just restarted is refused by its own
#: link gate for as long as the attachment takes.
FIRST_LOOK_MS = 20_000
FIRST_LOOK_TRIES = 6
GATE_WAIT_TRIES = 90

#: The tick chain the first look uses. One per profile's runtime, like every other.
CHAIN_FIRST = "invasion_first_read"

#: What a numeric field of the line looks like.
_NUM = re.compile(r"\b([a-z_]+)=(-?\d+)\b")


def record(rt, raw) -> None:
    """Keep what a reading of the invasion said. Never raises — it is a tally."""
    try:
        rt.store.blob_set(BLOB, {"invasion": str(raw or ""), "at": time.time()})
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
    raw = held.get("invasion")
    try:
        at = float(held.get("at") or 0)
    except (TypeError, ValueError):
        at = 0.0
    if not raw:
        return {}, None
    return parse(raw), (max(0.0, time.time() - at) if at else None)


def precondition(rt, now: float | None = None):
    """Why the golden hunt must not even be STARTED — or ``None`` to let it run.

    Three ways to answer «let it run», and every one of them is deliberate:

    * **no reading, or one that has gone stale.** The panel does not know, and holding a
      run back on ignorance is how an event gets missed for a whole window. The run
      itself refreshes the store on its way past.
    * **the reading says the invasion is on.** Nothing to hold back.
    * **the moment the reading NAMED as the next window has passed.** The estimate came
      out of the game's own season day, and the one thing it cannot do is tell us the
      invasion has started — so the first run after it goes and looks.
    """
    fields, age = state(rt)
    if not fields or age is None or age > STALE_SEC:
        return None
    if int(fields.get("open", 0) or 0) == 1:
        return None
    at = float(now if now is not None else time.time())
    nxt = int(fields.get("next_at", 0) or 0)
    if nxt and at >= nxt:
        return None
    return SKIP_KEY


def wire(rt) -> None:
    """Hold the hunt's errand back while this profile knows the event is shut.

    On the runtime rather than on «События», like the rally's own standing rules
    (`rally_orders.py`): a profile that does not draw that tab still has the errand, and
    a gate that lived on the page would be absent exactly where nobody is watching.
    """
    schedule = getattr(rt, "schedule", None)
    if schedule is None or not hasattr(schedule, "register_precondition"):
        return
    schedule.register_precondition(ERRAND, lambda: precondition(rt))
    # …AND EVERY RUN OF IT REFRESHES THE READING. The recipe reads the invasion as its
    # first act, so the freshest answer in the panel is the one the run just took —
    # taking it again on a clock would be the poll this rule exists to prevent.
    if hasattr(schedule, "register_report"):
        schedule.register_report(ERRAND, lambda ctx: report(rt, ctx))


def report(rt, ctx) -> None:
    """Keep whatever the finished hunt read about the invasion. Never raises."""
    try:
        values = getattr(ctx, "vars", {}) or {}
        raw = values.get(VARIABLE)
    except Exception:                    # noqa: BLE001 — a tally, never the run
        return
    if raw:
        record(rt, raw)


class InvasionWatch:
    """This profile's ear for «Вторжение зомби»: one first reading, then the record.

    Nothing here ticks. :meth:`start` subscribes to the two things that can move the
    event — the client entering the game, and the invasion's own record arriving — and
    each of them books ONE reading, debounced.
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
        """Listen, and register the schedule's own gate. Safe to call twice."""
        if self._offs:
            return
        try:
            self._offs.append(self._rt.bus.subscribe(bus.GAME_READY, self._on_ready))
        except Exception:                # noqa: BLE001 — the panel still works
            self._rt.dbg("invasion").error("could not listen for the game",
                                           exc_info=True)
        try:
            self._offs.append(self._rt.wire.subscribe(PUSH, self._on_push))
        except Exception:                # noqa: BLE001 — the record is a bonus
            self._rt.dbg("invasion").error("could not listen for the record",
                                           exc_info=True)
        try:
            wire(self._rt)
        except Exception:                # noqa: BLE001 — then the recipe's gate is the
            self._rt.dbg("invasion").error("could not gate the hunt",  # only one, and it
                                           exc_info=True)              # is the real one
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
        # A SHUT GATE IS NOT A TRY (#2636): playing into it only prints «нет связи с
        # игрой» once a look, about a state the panel already knows.
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
                ACTION, tag="invasion", priority=claims.BACKGROUND,
                on_result=self._back, on_done=self._done)
        finally:
            if not started:
                # A REFUSAL DOES NOT BURN THE DEBOUNCE (#2636).
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
