"""What every squad is doing right now, and how much stamina is left — read once.

A rally goes out from a squad standing in the base. So does a gather, so does an
attack — and a send with the squad already out is refused by the game minutes after
the operator asked for it, with nothing to show for the wait.

THE GATE IS NOT HERE. Whether a send may go out is a rule of the ability and lives in
the recipe: `actions/create_rally.md` asks before it searches and refuses by name,
`actions/join_rally.md` sieves the squads it was given (CLAUDE.md — the panel is a
player). What lives here is the ANSWER TO «where are they», for everything that merely
wants to know: the line under the rally form, the trigger that repaints it when a march
crosses the wire, and any tab that comes later.

It lives here rather than in the tab for the reason everything else in
`panel/runtime/` does: a tab opened on its own (`python -m panel.tabs.rally`) is handed
the same runtime as the one in the shell, so a reader on the runtime works in both and
a reader inside the tab works in neither. `rt.squads` is built on first ask, exactly
like `rt.schedule` — a profile that never opens a tab that needs it pays nothing.

THE GAME SIDE IS NOT HERE. The reading is `actions/read_squad_state.md`, one line of
DSL, and this module runs it and parses what it said (`CLAUDE.md`: the panel plays
scenarios, it does not assemble Lua). What this module owns is the panel's side of it:
the cache, the poll, the words the states are called by, and the one question a caller
really has — :meth:`SquadReader.at_base`.

A read takes no lease. The daemon serialises chunks anyway and a lease excludes other
LEASES, never a plain run (tools/lib/game_lease.py), so the poll never queues behind an
action and never delays one — which is what lets the strip stay live while a rally is
being raised.
"""
from __future__ import annotations

import threading
import time

#: The scenario that does the reading (`src/lastwar_bot/actions/read_squad_state.md`).
ACTION = "read_squad_state"

#: What `rt.bus` carries a fresh reading under. The payload is a :class:`SquadState`.
TOPIC = "squads"

#: How often the poll re-reads while somebody is watching. A squad's state changes on
#: the minute scale (a march is minutes, a gather is hours), so this is about noticing
#: within a screenful of time, not about tracking a moving dot.
POLL_MS = 15000

#: A reading younger than this answers straight from the cache. Three tabs asking at
#: once — the strip, the gate, the log — is one game read, not three.
FRESH_SEC = 3.0

# ---------------------------------------------------------------------------
# The words the panel calls a squad's state by.
#
# They are the PANEL's categories, not the game's enum: the game has nine formation
# states and twenty-five march statuses, and the person looking at the strip wants to
# know which of half a dozen things is going on. The raw values travel too (`Squad.state`,
# `Squad.status`), so nothing is lost by summarising.
HOME = "home"              # in the base — the only state a send may start from
MARCHING = "marching"      # on its way somewhere
RALLY = "rally"            # in a rally: waiting at the banner, or marching to it
GATHERING = "gathering"    # sitting on a resource tile, collecting
FIGHTING = "fighting"      # attacking, or chasing something that moved
RETURNING = "returning"    # on its way home
STATIONED = "stationed"    # parked out in the world (a building, an alliance flag)
BROKEN = "broken"          # разбит — wiped, and healing or reviving
CAPTURED = "captured"      # taken prisoner
BUSY = "busy"              # out, in a state this list does not name
UNKNOWN = "unknown"        # not read (no daemon, no client, a manager not loaded)

#: Every kind, in the order they are worth showing in — used by the tests and by any
#: tab that wants to draw a legend.
KINDS = (HOME, MARCHING, RALLY, GATHERING, FIGHTING, RETURNING, STATIONED,
         BROKEN, CAPTURED, BUSY, UNKNOWN)

# `MarchStatus` (the game's own enum, read live) → what the panel calls it. The march
# is the specific answer: a squad "out" says nothing, a squad `COLLECTING` says it is
# on a mine and will be for hours.
_BY_STATUS = {
    "STATION": STATIONED,
    "MOVING": MARCHING,
    "ATTACKING": FIGHTING,
    "COLLECTING": GATHERING,
    "COLLECTING_ASSISTANCE": GATHERING,
    "BACK_HOME": RETURNING,
    "TRANSPORT_BACK_HOME": RETURNING,
    "CHASING": FIGHTING,
    "WAIT_RALLY": RALLY,
    "IN_TEAM": RALLY,
    "ASSISTANCE": STATIONED,
    "BUILD_ALLIANCE_BUILDING": STATIONED,
    "BUILD_WORM_HOLE": STATIONED,
    "TREASURE_DIGGING": GATHERING,
    "SAMPLING": GATHERING,
    "PICKING": GATHERING,
    "CROSS_SERVER": MARCHING,
}

# `ArmyFormationState` → the same, for a squad whose march cannot be resolved. Coarser
# on purpose: this is what is left when the march table has nothing to say.
_BY_STATE = {
    0: HOME,            # Free
    1: MARCHING,        # March
    2: CAPTURED,        # Prison
    3: BROKEN,          # Death
    4: RETURNING,       # GoHome
    5: BROKEN,          # Revival
    6: CAPTURED,        # Prison_PickDNA
    7: STATIONED,       # StationBuilding
    8: BUSY,            # Formation
}

#: The march kinds that ARE a rally, whatever the march happens to be doing this second
#: (`NewMarchType.ASSEMBLY_MARCH` / `CROSS_ASSEMBLY_MARCH`).
_RALLY_MARCHES = ("ASSEMBLY_MARCH", "CROSS_ASSEMBLY_MARCH")


class Squad:
    """One squad slot, as the game last reported it."""

    __slots__ = ("index", "state", "free", "soldiers", "fits", "status", "march",
                 "team", "point", "arrive_ms")

    def __init__(self, index: int, state: int = -1, free: bool = False,
                 soldiers: int = 0, status: str = "", march: str = "",
                 team: str = "0", point: str = "", arrive_ms: int = 0,
                 fits: int = 0) -> None:
        self.index = int(index)
        self.state = int(state)
        self.free = bool(free)
        self.soldiers = int(soldiers)
        #: How many soldiers FIT — what the auto-join compares against, because the
        #: player asked for «только полные отряды» (#1281). `0` when the game has not
        #: said, and then nothing may be concluded from it.
        self.fits = int(fits)
        self.status = status or ""
        self.march = march or ""
        self.team = team or "0"
        self.point = point or ""
        self.arrive_ms = int(arrive_ms)

    @property
    def full(self) -> "bool | None":
        """Is this squad filled to what its heroes can carry? `None` when unknown.

        THREE ANSWERS AND NOT TWO, on purpose: a ceiling the game has not filled in is
        not a full squad and not a short one either, and the auto-join treats it the
        third way — it sends, because a gate that cannot see must not refuse (#1281).
        """
        if self.fits <= 0:
            return None
        return self.soldiers >= self.fits

    @property
    def in_rally(self) -> bool:
        """In a rally — as its leader or as somebody who joined it."""
        return (self.team not in ("", "0", "nil")
                or self.march in _RALLY_MARCHES
                or _BY_STATUS.get(self.status) == RALLY)

    @property
    def kind(self) -> str:
        """One word for what this squad is doing (one of :data:`KINDS`)."""
        if self.state in (2, 3, 5, 6):
            # Wiped or captured beats everything: such a squad has no march, and what
            # it "was doing" is not what the operator needs to hear.
            return _BY_STATE[self.state]
        if self.state == 0 and self.free:
            return HOME
        if self.in_rally:
            return RALLY
        by_status = _BY_STATUS.get(self.status)
        if by_status is not None:
            return by_status
        by_state = _BY_STATE.get(self.state)
        if by_state is not None:
            return by_state
        return UNKNOWN if self.state < 0 else BUSY

    @property
    def at_base(self) -> bool:
        """Standing in the base — the one state a send may start from.

        BOTH halves are required: the game's own idle flag (`IsFree()`) and the state
        being `Free`. They agree in every reading taken so far, and a gate that opens on
        either alone would open on a half-updated one.
        """
        return self.state == 0 and self.free

    def __repr__(self) -> str:                 # pragma: no cover - diagnostics
        return f"<Squad {self.index} {self.kind} state={self.state} {self.status or '-'}>"


class SquadState:
    """A whole reading: every squad, the stamina pool, and when it was taken."""

    __slots__ = ("squads", "stamina", "stamina_max", "stamina_full_ms", "at", "error",
                 "pool")

    def __init__(self, squads=None, stamina: int = -1, stamina_max: int = 0,
                 stamina_full_ms: int = 0, error: str = "", at: float | None = None,
                 pool: int = 0) -> None:
        self.squads = list(squads or ())
        #: Soldiers the base owns in total. It is what tells «this squad has not been
        #: topped up» from «there are not enough soldiers to fill one», and the second
        #: of those is why the auto-join can go quiet for days (#1281).
        self.pool = int(pool)
        self.stamina = int(stamina)
        self.stamina_max = int(stamina_max)
        self.stamina_full_ms = int(stamina_full_ms)
        self.error = error or ""
        self.at = time.time() if at is None else float(at)

    @property
    def ok(self) -> bool:
        """Whether this reading may be gated on. An empty or failed one may not."""
        return not self.error and bool(self.squads)

    def squad(self, index: int):
        """The squad in slot ``index``, or ``None`` when it was not in the reading."""
        for squad in self.squads:
            if squad.index == int(index):
                return squad
        return None

    def easiest_squad(self):
        """The squad closest to being fillable — the one with the smallest ceiling.

        Which one the message names matters: telling somebody they are short for their
        ROOMIEST squad overstates what they have to train. The smallest ceiling is the
        first one that will start joining again, so it is the number worth working
        towards. ``None`` when no ceiling was read.
        """
        known = [s for s in self.squads if s.fits > 0]
        return min(known, key=lambda s: s.fits) if known else None

    @property
    def short_of_troops(self) -> bool:
        """Can the base not fill even its roomiest squad? Then nothing will be sent.

        The one reading behind «почему автостяг молчит»: with «только полные отряды»
        asked for explicitly (#1281), a base below the smallest ceiling sends nothing at
        all, and the answer is the barracks rather than the bot. False while any ceiling
        is unknown — an unread gate says nothing, it does not accuse.
        """
        fits = [s.fits for s in self.squads if s.fits > 0]
        return bool(fits) and self.pool > 0 and self.pool < min(fits)

    def kind(self, index: int) -> str:
        """What slot ``index`` is doing, `unknown` when this reading does not say."""
        squad = self.squad(index)
        return squad.kind if squad is not None else UNKNOWN

    def age(self) -> float:
        return max(0.0, time.time() - self.at)

    def __repr__(self) -> str:                 # pragma: no cover - diagnostics
        if self.error:
            return f"<SquadState error={self.error!r}>"
        return (f"<SquadState {len(self.squads)} squads "
                f"stamina={self.stamina}/{self.stamina_max}>")


def parse(raw: str) -> SquadState:
    """Turn what `read_squad_state.md` said into a :class:`SquadState`.

    The format is one line of « | »-separated records of `key=value` tokens: the first
    is the account (`stamina` / `max` / `full`), the rest are squads (`squad=` and its
    fields). Written this way — rather than as JSON — because it is also what a person
    reads in the log when the recipe is run by hand.

    Anything unreadable is dropped rather than guessed at: a record without a slot
    number is not a squad, and a reading with no squads in it is not gated on
    (:attr:`SquadState.ok`).
    """
    if not isinstance(raw, str) or not raw.strip():
        return SquadState(error="empty")
    squads, stamina, stamina_max, full, pool = [], -1, 0, 0, 0
    for record in raw.split("|"):
        fields = {}
        for token in record.split():
            key, sep, value = token.partition("=")
            if sep:
                fields[key.strip()] = value.strip()
        if not fields:
            continue
        if "squad" in fields:
            index = _int(fields.get("squad"), 0)
            if index <= 0:
                continue
            squads.append(Squad(
                index=index,
                state=_int(fields.get("state"), -1),
                free=fields.get("free") == "1",
                soldiers=_int(fields.get("soldiers"), 0),
                status=_name(fields.get("status")),
                march=_name(fields.get("march")),
                team=fields.get("team") or "0",
                point=_name(fields.get("point")),
                arrive_ms=_int(fields.get("arrive"), 0),
                fits=_int(fields.get("fits"), 0)))
        elif "stamina" in fields:
            stamina = _int(fields.get("stamina"), -1)
            stamina_max = _int(fields.get("max"), 0)
            full = _int(fields.get("full"), 0)
            pool = _int(fields.get("pool"), 0)
    if not squads:
        return SquadState(error="no squads")
    squads.sort(key=lambda s: s.index)
    return SquadState(squads=squads, stamina=stamina, stamina_max=stamina_max,
                      stamina_full_ms=full, pool=pool)


def _int(raw, default: int) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _name(raw) -> str:
    """A name field the recipe writes «-» in when the game had nothing to say."""
    text = (raw or "").strip()
    return "" if text in ("", "-", "nil") else text


class SquadReader:
    """The one place the panel asks where its squads are.

    Four ways in, and they are for four different callers:

    * :meth:`read` — blocking, off the Tk thread, for the caller about to act on the
      answer (the rally loop, before it sends). ``force=True`` when it must be current.
    * :meth:`latest` — whatever was last read, instantly, for a caller that is drawing.
    * :meth:`watch` — a callback per reading, and the poll runs for as long as somebody
      is watching. Stop watching and the polling stops with the last watcher, so a tab
      nobody has open costs no game reads.
    * :meth:`refresh_async` — «something happened, look again», from the Tk thread and
      without blocking it. This is what the «squad_state» trigger calls when a march
      message crosses the wire, and what a tab calls after spending a squad.
    """

    def __init__(self, rt) -> None:
        self._rt = rt
        self._state: SquadState | None = None
        self._lock = threading.Lock()      # one read at a time
        self._reading = False              # a poll's read is in flight
        self._watchers = 0
        self._polling = False
        self._interval = POLL_MS

    # -- reading ------------------------------------------------------------
    def latest(self):
        """The last reading, or ``None`` if there has not been one."""
        return self._state

    def read(self, force: bool = False) -> SquadState:
        """Read the game (or answer from the cache) and publish. BLOCKS — not on Tk.

        A second caller arriving while a read is in flight waits for it and gets that
        one rather than starting another: the game answers once, everybody hears it.
        """
        cached = self._state
        if not force and cached is not None and cached.age() < FRESH_SEC:
            return cached
        waiting_since = time.time()
        with self._lock:
            cached = self._state
            if cached is not None:
                if cached.at >= waiting_since:
                    # Somebody else's read landed while this one waited for the lock,
                    # so it is newer than the request — including a forced one.
                    return cached
                if not force and cached.age() < FRESH_SEC:
                    return cached
            state = self._read_now()
            self._state = state
        self._publish(state)
        return state

    def _read_now(self) -> SquadState:
        """Play the scenario and parse it. Never raises — a failure is a reading too."""
        game = getattr(self._rt, "game", None)
        try:
            if game is None or not game.ready():
                return SquadState(error="offline")
        except Exception as exc:                # noqa: BLE001 — a cold link may refuse
            return SquadState(error=str(exc))
        try:
            # Silent on purpose: a poll every fifteen seconds must not write a line to
            # the log each time. Run it from the «Сценарии» tab and it talks normally.
            outcome = self._rt.actions.play(ACTION, on_event=lambda msg: None)
        except Exception as exc:                # noqa: BLE001 — never the caller's problem
            return SquadState(error=str(exc))
        ctx = getattr(outcome, "ctx", None)
        raw = (getattr(ctx, "vars", {}) or {}).get("squads") if ctx is not None else None
        if not outcome.ok or not isinstance(raw, str):
            return SquadState(error=outcome.reason or "unreadable")
        return parse(raw)

    def refresh_async(self, force: bool = True) -> None:
        """Read on a worker thread and let the watchers hear about it. Safe from Tk."""
        if self._reading:
            return
        self._reading = True

        def work() -> None:
            try:
                self.read(force=force)
            finally:
                self._reading = False

        threading.Thread(target=work, daemon=True).start()

    # -- the poll ------------------------------------------------------------
    def watch(self, func):
        """Hear every reading. Returns the callable that stops listening.

        The poll is reference-counted against these: the first watcher starts it, the
        last one to go stops it. A tab therefore watches in `on_show` and lets go in
        `on_hide` / `shutdown`, and a profile whose «Ралли» tab is never opened never
        reads the game for it.
        """
        off = self._rt.bus.subscribe(TOPIC, func)
        self._watchers += 1
        self.start()

        def _off() -> None:
            off()
            self._watchers = max(0, self._watchers - 1)
            if self._watchers == 0:
                self.stop()
        return _off

    def start(self, interval_ms: int | None = None) -> None:
        """Begin polling (idempotent — `rt.tick` is armed by name, so twice is once)."""
        if interval_ms:
            self._interval = int(interval_ms)
        if self._polling or getattr(self._rt, "root", None) is None:
            # No Tk root means no `after` queue to poll on — a harness, or a headless
            # test. `read()` still works; only the repetition needs a window.
            return
        self._polling = True
        self._rt.tick.arm(TOPIC, 1, self._tick)

    def stop(self) -> None:
        self._polling = False
        try:
            self._rt.tick.disarm(TOPIC)
        except Exception:                       # noqa: BLE001 — the window may be gone
            pass

    def _tick(self) -> None:
        if not self._polling:
            return
        self.refresh_async()
        self._rt.tick.arm(TOPIC, self._interval, self._tick)

    def _publish(self, state: SquadState) -> None:
        try:
            self._rt.bus.publish(TOPIC, state)
        except Exception:                       # noqa: BLE001 — a deaf listener is not
            pass                                # the reader's problem

    # -- the question everybody actually asks --------------------------------
    def at_base(self, index: int, force: bool = False):
        """Is squad ``index`` standing in the base?

        ``True`` / ``False`` off a reading, and ``None`` when there is no reading to
        answer with — no daemon, no client, nothing parsed. ``None`` is deliberately
        not ``False``: a gate that cannot see must not claim the squad is out, and a
        caller decides for itself whether to send anyway or to wait.
        """
        state = self.read(force=force)
        if not state.ok:
            return None
        squad = state.squad(index)
        if squad is None:
            return None
        return squad.at_base
