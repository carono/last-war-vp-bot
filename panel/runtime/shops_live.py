"""The LAST reading of the shops — one state, kept where every page and errand finds it.

Written for «Магазин» (#2666), and shaped exactly like :mod:`panel.runtime.market_live`
because the discipline is the same one `CLAUDE.md` states twice: «A STATISTIC IS NOT
REFRESHED BY HAND». The shelves are read ONCE when the client gets into the game, again
whenever a purchase of ours moved something, and never on a clock. There is no
«Обновить» for them anywhere.

WHY IT IS AFFORDABLE. Every row of every shop is already in the client's own memory —
`DataCenter.CommonShopManager.goodsShopDic` for the eight tabs of the game's «Магазин»,
the decoration shelf beside them, and `LWTitaniumBlueStoreManager` for «Сверкающий
рынок». `actions/read_shops.md` is therefore one round trip against that memory and not
one question goes on the wire.

ON THE RUNTIME AND NOT ON THE TAB. The page draws the reading, but the AUTOBUY errand
spends it, and an errand must work in a profile whose «Магазин» tab is switched off. So
the ear belongs to the profile, like the log and the schedule (`CLAUDE.md`, «A profile is
a whole panel of its own»).

WHAT IS STORED is what the scenario handed over, plus the moment it landed::

    {"shops": "<the packed line>", "money": "<the money shelves, packed>",
     "purses": "<one record per currency>", "at": 1788859000.0}

The raw lines rather than a parsed structure, for the reason `market_live` keeps what the
game said: a panel that learns to read one more field of it tomorrow reads that field out
of what is already written down.
"""
from __future__ import annotations

import threading
import time

from . import bus, claims

#: The row in this profile's `blobs` table. Read and written WHOLE — a blob, not a table
#: of its own (`docs/panel-storage.md`): a shelf is a few hundred rows and every reading
#: replaces the whole of it.
BLOB = "shops_live"

#: The scenario that does the reading, and the variables it leaves the lines in.
ACTION = "read_shops"
VARIABLES = ("shops", "money", "purses")

#: The push that says a balance moved. A shelf's own counters (what is left of a quota)
#: move only when WE buy something, and a purchase re-reads on its own way out — so this
#: is here for the currency a player earned while the panel was watching, and it is
#: debounced hard because a harvest emits 25 of them.
PUSH = "push.resource.item.update"

#: The shortest gap between two readings, in seconds. A burst of one push must cost ONE
#: reading — the rule every wire subscriber in this panel obeys. Longer than the market's
#: twenty because this push is the noisiest one in the game.
DEBOUNCE_SEC = 120.0

#: The one-shot first look, exactly as `market_live` arms it and for the same reason:
#: `bus.GAME_READY` is an EDGE, and the panel's own gate is still amber when it arrives
#: after a restart. See that module for the whole of the reasoning.
FIRST_LOOK_MS = 20_000
FIRST_LOOK_TRIES = 6
GATE_WAIT_TRIES = 90

#: The tick chain the first look uses. One per profile's runtime, like every other.
CHAIN_FIRST = "shops_first_read"

#: How the scenario packs what it read: records, and the fields inside one. The NAME is
#: last in a record so a name holding the separator costs nothing.
RECORD_SEP = " #|# "
FIELD_SEP = ";;"

#: The fields of one row, in the order `read_shops.md` writes them.
FIELDS = ("kind", "shop", "id", "item", "icon", "colour", "count",
          "cost_id", "cost", "limit", "bought", "reset", "afford",
          "cost_name", "name")

#: …and the fields of one PURSE (#2830), which is a record per CURRENCY rather than per
#: row: what the shelves are paid in, how much of it there is, its own picture and the
#: game's own word for it. `have` of -1 is «the client will not show it» and is never
#: drawn as a zero — the same honesty the price line keeps.
PURSE_FIELDS = ("cost_id", "have", "icon", "name")


def record(rt, values: dict) -> None:
    """Keep what a reading said. Never raises — it is a tally, not a run."""
    try:
        held = {name: str(values.get(name) or "") for name in VARIABLES}
        held["at"] = time.time()
        rt.store.blob_set(BLOB, held)
    except Exception:                    # noqa: BLE001 — a reading, never the run
        pass


def read(rt) -> dict:
    """The row as it stands, or an empty one."""
    try:
        held = rt.store.blob_get(BLOB)
    except Exception:                    # noqa: BLE001 — a reading, never the page
        held = None
    return held if isinstance(held, dict) else {}


def parse_rows(raw) -> list:
    """The packed line into records. An unreadable field is dropped, never raised.

    A record the scenario could not fill completely is kept as far as it goes: a shelf
    missing one row is a shelf, a page raising is a page.
    """
    out: list = []
    for chunk in str(raw or "").split(RECORD_SEP):
        if not chunk.strip():
            continue
        parts = chunk.split(FIELD_SEP)
        if len(parts) < len(FIELDS):
            parts = parts + [""] * (len(FIELDS) - len(parts))
        row = dict(zip(FIELDS, parts))
        for key in ("colour", "count", "cost", "limit", "bought", "reset", "afford"):
            try:
                row[key] = int(str(row[key]).strip() or 0)
            except (TypeError, ValueError):
                row[key] = 0
        out.append(row)
    return out


def parse_purses(raw) -> list:
    """The packed purse line into records. Same discipline as :func:`parse_rows`."""
    out: list = []
    for chunk in str(raw or "").split(RECORD_SEP):
        if not chunk.strip():
            continue
        parts = chunk.split(FIELD_SEP)
        if len(parts) < len(PURSE_FIELDS):
            parts = parts + [""] * (len(PURSE_FIELDS) - len(parts))
        row = dict(zip(PURSE_FIELDS, parts))
        try:
            row["have"] = int(str(row["have"]).strip() or 0)
        except (TypeError, ValueError):
            row["have"] = -1
        if str(row.get("cost_id") or "").strip():
            out.append(row)
    return out


def purses(rt) -> dict:
    """`{currency: {"have": int, "icon": str, "name": str}}` — the last reading (#2830).

    Empty until something has been read, which is the honest answer: a balance nobody
    has read is not a zero.
    """
    out: dict = {}
    for row in parse_purses(read(rt).get("purses")):
        out[str(row.get("cost_id") or "")] = {
            "have": int(row.get("have") or 0),
            "icon": str(row.get("icon") or ""),
            "name": str(row.get("name") or "")}
    return out


def state(rt) -> tuple:
    """`(rows, money, age)` — what the page draws, and how old the reading is.

    `age` is `None` when nothing has ever been read, and everything else is then empty:
    a page with no reading says so in words rather than drawing zeros nobody measured.
    """
    held = read(rt)
    try:
        at = float(held.get("at") or 0)
    except (TypeError, ValueError):
        at = 0.0
    rows = parse_rows(held.get("shops"))
    money = parse_rows(held.get("money"))
    return rows, money, (max(0.0, time.time() - at) if at else None)


class ShopWatch:
    """This profile's ear for the shops: one first reading, then what moves them.

    Nothing here ticks. :meth:`start` subscribes to the client entering the game and to
    the balance push, and each of them books ONE reading, debounced. A panel whose client
    is not up reads nothing, for ever.
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
            self._rt.dbg("shops").error("could not listen for the game", exc_info=True)
        try:
            self._offs.append(self._rt.wire.subscribe(PUSH, self._on_push))
        except Exception:                # noqa: BLE001 — the push is a bonus
            self._rt.dbg("shops").error("could not listen for the push", exc_info=True)
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
                ACTION, tag="shops", priority=claims.BACKGROUND,
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
        if values.get("shops") or values.get("money") or values.get("purses"):
            record(self._rt, values)
            self._read_once = True

    def after_purchase(self, outcome=None) -> None:
        """A purchase of ours moved a shelf: read it back, debounce or no debounce.

        The one place the gap is deliberately skipped. A person who has just spent
        something is looking at the page, and a quota that still says «осталось 3» after
        the third copy was bought is the panel telling them something untrue.
        """
        with self._lock:
            self._last = 0.0
        self.refresh("bought")
