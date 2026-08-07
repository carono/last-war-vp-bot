#!/usr/bin/env python3
"""The world-map listener: mines, trucks and alliance trains off the same stream.

**This is a second listener and NOT a second capture, and the difference was
measured rather than reasoned about.** Two npcap captures over one interface do
not share the traffic — the second one gets a trickle. Live (#1188, 044c19f) a
hand-started capture reported `20 delivered / 0 map response(s)` for a whole map
lap while the panel's own instance, in that same minute, was at `5117 map
response(s), 918999 tile(s)`. A capture starved like that reads exactly like a
deaf client, which is how it was believed twice.

So the wire is read ONCE per client and handed to as many indexes as want it.
`MapIndex` (map_capture.py) already decodes every frame and calls `on_blocks` /
`on_response` on its subclass; this class is a plain object the subclass forwards
those two calls to, so adding a listener costs no process, no interface and no
packet. `secret_task_capture.py --world-json PATH` is the wiring.

What it keeps, and where each came from — all three measured off a recorded
whole-server lap at height 600 (`results/lv_a600.jsonl`, 244 map responses):

* **mines** — `world.get.block` tiles with `f2 = 7`, 12 725 of them in that lap
  (9 003 distinct, 8 914 of them free). `lastwar_proto.mines`.
* **trucks** — not tiles at all: marches whose `f11` is 37, carrying a `train`
  object with `type = 1`. 36 distinct in the lap. `lastwar_proto.trucks`.
* **alliance trains** — the same march shape with `train.type = 2`, which the
  truck decoder deliberately skips. Rare: 3 in every recording on disk.
  `lastwar_proto.trains`.

**Monsters are NOT here, and that is not an omission.** Nothing on the wire
names one — checked across incremental pans, a full district load, the login
snapshot, `push.world.point.update` and a server switch, roughly 2000 unique
tiles, zero objects above the 1..10 mine level range while levels 12..28 were on
screen throughout (docs/research/protocol.md, «Monsters are not on the wire»).
Monster placement is computed client-side, so the monster list is read out of the
game's own VM instead — `actions/read_world_monsters.md`.
"""
from __future__ import annotations

import threading
import time

import lastwar_proto as proto

#: How long a sighting is trusted for. A mine's occupancy changes under it — the
#: tile says who is gathering right now and nothing about who will be in an hour
#: — and a truck's position is INTERPOLATED along the leg the server last
#: described, so one that stopped being re-sent goes on gliding down a route it
#: may have left. Both read as live data long after they stopped being any, which
#: is what the window is for. The same fifteen minutes the task index uses.
STALE_AFTER_SECONDS = proto.TASK_FRESH_SECONDS

#: How many of each kind the checkpoint may carry. A whole-server lap finds nine
#: thousand mines, and a file that size rewritten every tick is a real cost on
#: the disk and on whoever reads it. When the cap bites, the freshest and highest
#: are what survive — and the capture SAYS how many it dropped, because a silent
#: truncation reads as «that is all there was».
DEFAULT_MAX_PER_KIND = 5000


def _mine_rank(record: dict) -> tuple:
    """What survives the cap first: the highest level, then the freshest."""
    return (-int(record.get("level") or 0), -float(record.get("seen_at") or 0))


def _cargo_rank(record: dict) -> tuple:
    """…and for a truck, the fattest haul, then the freshest — the raid order."""
    return (-int(record.get("cargo") or 0), -float(record.get("seen_at") or 0))


def _fresh_rank(record: dict) -> tuple:
    return (-float(record.get("seen_at") or 0),)


class WorldIndex:
    """Mines, trucks and trains, kept for as long as a sighting is worth trusting.

    Fed by whichever `MapIndex` subclass owns the capture: `on_blocks` for the map
    responses and `on_response` for everything else the server says. Both are
    called with the owner's `_index_lock` held, so this keeps a lock of its own
    only for the readers (`records`), which run on the printing thread.
    """

    #: Which commands carry a march — and therefore a truck or a train. The same
    #: three `tools/dev/scan_trucks.py` listens on, kept as a set so an unlisted
    #: command costs a lookup rather than a decode: `on_response` sees every
    #: non-map frame the server sends, which is most of the traffic.
    MARCH_COMMANDS = frozenset({
        "push.world.march.world.get.new",
        "push.world.march.new",
        "world.get.march.infos",
    })

    #: …and the one that takes a march away again.
    MARCH_GONE = "push.world.march.del"

    def __init__(self, stale_after: float = STALE_AFTER_SECONDS,
                 max_per_kind: int = DEFAULT_MAX_PER_KIND) -> None:
        self.stale_after = stale_after
        self.max_per_kind = max_per_kind
        self._lock = threading.RLock()
        #: kind -> {key: record}, each record already `as_dict()`-ed and stamped
        #: with `seen_at`, because that is exactly what the checkpoint carries.
        self._kinds: dict = {"mines": {}, "trucks": {}, "trains": {}}
        #: How many records the last `records()` had to drop to the cap, per kind.
        self.dropped: dict = {"mines": 0, "trucks": 0, "trains": 0}
        #: Counters, so «nothing found» and «nothing arrived» stay different
        #: answers — the same reason `MapIndex` counts its blocks.
        self.mines_seen = 0
        self.trucks_seen = 0
        self.trains_seen = 0

    # -- the two hooks the capture forwards --------------------------------
    def on_blocks(self, payload, blocks, now: float) -> None:
        """Map tiles: the mines among them."""
        for mine in proto.mines(payload):
            record = mine.as_dict()
            record["seen_at"] = int(now)
            with self._lock:
                self._kinds["mines"][mine.uuid] = record
                self.mines_seen += 1

    def on_response(self, command, payload) -> None:
        """Everything else the server says: the march stream, and its removals."""
        if command == self.MARCH_GONE:
            self._forget_march(payload)
            return
        if command not in self.MARCH_COMMANDS or not isinstance(payload, dict):
            return
        now = time.time()
        for kind, decode in (("trucks", proto.trucks), ("trains", proto.trains)):
            for item in decode(payload):
                record = item.as_dict()
                record["seen_at"] = int(now)
                with self._lock:
                    self._kinds[kind][str(item.uuid)] = record
                    if kind == "trucks":
                        self.trucks_seen += 1
                    else:
                        self.trains_seen += 1

    def _forget_march(self, payload) -> None:
        """A march ended — the truck or train reached its stop, or was wiped.

        The del carries the MARCH uuid, not the vehicle's, so both are matched:
        a record whose `march_uuid` or own `uuid` is named goes.
        """
        if not isinstance(payload, dict):
            return
        gone = str(payload.get("uuid") or "")
        if not gone:
            return
        with self._lock:
            for kind in ("trucks", "trains"):
                for key, record in list(self._kinds[kind].items()):
                    if str(record.get("march_uuid") or "") == gone or key == gone:
                        self._kinds[kind].pop(key, None)

    def on_server_left(self, server: int, current) -> None:
        """The player moved off `server`: drop what belongs to the map they left.

        The same rule the task index follows and for the same reason — a truck
        goes on being interpolated along its route, and a mine goes on claiming
        to be free, on a map nobody is looking at. Keyed off the CURRENT server
        rather than the one just left, so a stray third server's records go too.
        """
        with self._lock:
            for kind, records in self._kinds.items():
                for key, record in list(records.items()):
                    if record.get("server_id") != current:
                        records.pop(key, None)

    # -- what the checkpoint carries ---------------------------------------
    def _evict(self, now: float) -> None:
        cutoff = now - self.stale_after
        for records in self._kinds.values():
            for key, record in list(records.items()):
                if float(record.get("seen_at") or 0) < cutoff:
                    records.pop(key, None)

    def records(self) -> dict:
        """`{"mines": [...], "trucks": [...], "trains": [...]}`, fresh and capped.

        Eviction runs here, so the file never carries a sighting already past the
        window, and the cap is applied on a ranking that keeps what is worth
        keeping (see `_mine_rank`) rather than on dict order.
        """
        ranks = {"mines": _mine_rank, "trucks": _cargo_rank, "trains": _fresh_rank}
        out = {}
        with self._lock:
            self._evict(time.time())
            for kind, records in self._kinds.items():
                rows = sorted(records.values(), key=ranks[kind])
                self.dropped[kind] = max(len(rows) - self.max_per_kind, 0)
                out[kind] = rows[:self.max_per_kind]
        return out

    def counts(self) -> dict:
        """How many of each kind are currently held — for the progress line."""
        with self._lock:
            return {kind: len(records) for kind, records in self._kinds.items()}
