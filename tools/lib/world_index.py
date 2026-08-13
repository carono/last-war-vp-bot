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
* **players** — the `f2 = 6` base tiles, 6 723 of them in that same lap
  (#1335). `lastwar_proto.player_bases`, plus the two things a base tile does
  NOT carry and this listener folds in as they arrive: the combat numbers off a
  `get.user.info.multi` reply (a click on a base, or the alliance roster the
  client fetches at login) and the note the account has written on that player
  (`user.remark.list`, also login-time). The alliance's full NAME comes off the
  alliance's own city tiles the same lap drives past.

  **This checkpoint is a LIVE VIEW and not the register.** It ages out and it is
  capped like every other kind here; what keeps a player for good is the panel's
  own per-profile list, which merges this and never removes a row for a read
  that came back empty (`panel/tabs/players/`, `panel/kept.py`).

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

#: …and how many PLAYERS, which needs a bigger number than the rest: one recorded
#: whole-server lap held 6 723 base tiles and they all arrive inside about three
#: seconds, so the ordinary cap would throw away a quarter of a lap before the
#: panel's register ever saw it. The cost is a checkpoint of a couple of megabytes
#: that lives fifteen minutes; the register on the other side of it is what keeps
#: them, and it keeps them for good.
DEFAULT_MAX_PLAYERS = 20000


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
                 max_per_kind: int = DEFAULT_MAX_PER_KIND,
                 max_players: int = DEFAULT_MAX_PLAYERS) -> None:
        self.stale_after = stale_after
        self.max_per_kind = max_per_kind
        self.max_players = max_players
        self._lock = threading.RLock()
        #: kind -> {key: record}, each record already `as_dict()`-ed and stamped
        #: with `seen_at`, because that is exactly what the checkpoint carries.
        self._kinds: dict = {"mines": {}, "trucks": {}, "trains": {}, "players": {}}
        #: How many records the last `records()` had to drop to the cap, per kind.
        self.dropped: dict = {"mines": 0, "trucks": 0, "trains": 0, "players": 0}
        #: Counters, so «nothing found» and «nothing arrived» stay different
        #: answers — the same reason `MapIndex` counts its blocks.
        self.mines_seen = 0
        self.trucks_seen = 0
        self.trains_seen = 0
        self.players_seen = 0
        #: How many `get.user.info.multi` entries were folded onto a player, and
        #: how many notes the account's own list turned out to hold. Both are the
        #: same distinction the counters above are for: «none arrived» is not
        #: «none matched».
        self.profiles_seen = 0
        self.remarks_known = 0
        #: alliance uuid -> full name, off the alliance's own city tiles. Held
        #: rather than merged once, because a base tile and its alliance's city
        #: arrive in no particular order — and stamped both ways, so whichever
        #: comes second fills the other in.
        self._alliances: dict = {}
        #: uid -> the note THIS ACCOUNT has written on that player, from
        #: `user.remark.list`. It arrives once, at login, before any map data, so
        #: the same holding-and-stamping applies with more force.
        self._remarks: dict = {}

    # -- the two hooks the capture forwards --------------------------------
    def on_blocks(self, payload, blocks, now: float) -> None:
        """Map tiles: the mines and the player bases among them."""
        learned = False
        for uuid, _abbr, name in proto.alliance_names(payload):
            with self._lock:
                learned = learned or self._alliances.get(uuid) != name
                self._alliances[uuid] = name
        if learned:
            # An alliance's city and its members' bases arrive in whatever order the
            # camera drove over them, so a name learned now has to reach the rows that
            # came first. Only when something was actually learned: a lap re-sends the
            # same city tile dozens of times.
            with self._lock:
                for record in self._kinds["players"].values():
                    self._stamp(record)
        for mine in proto.mines(payload):
            record = mine.as_dict()
            record["seen_at"] = int(now)
            with self._lock:
                self._kinds["mines"][mine.uuid] = record
                self.mines_seen += 1
        for base in proto.player_bases(payload):
            record = base.as_dict()
            record["seen_at"] = int(now)
            with self._lock:
                # A tile knows nothing about power, so it must never write the
                # numbers a profile reply left here — the merge goes the other
                # way round (`PlayerBase.merged_with`, `_take_profiles`).
                held = self._kinds["players"].get(base.uid) or {}
                for field in ("power", "army_power", "army_kill", "svip_level",
                              "profile_seen_at"):
                    if held.get(field) is not None:
                        record[field] = held[field]
                self._kinds["players"][base.uid] = self._stamp(record)
                self.players_seen += 1

    def _stamp(self, record: dict) -> dict:
        """Write on `record` the two things no base tile carries.

        The alliance's full name and the note this account has written on that
        player. Mutates and returns the same dict so it can be dropped into an
        assignment. Callers hold `_lock`.
        """
        name = self._alliances.get(record.get("alliance_id"))
        if name:
            record["alliance_name"] = name
        remark = self._remarks.get(str(record.get("uid")))
        if remark is not None:
            record["remark"] = remark
        return record

    def _take_profiles(self, payload) -> None:
        """Fold a `get.user.info.multi` reply onto the players already held.

        The reply carries what no tile does — power, army power, lifetime kills,
        SVIP level — and it arrives because somebody opened a player, or because
        the client fetched the alliance roster at login. Both are equally real.

        A player nobody has swept past is kept all the same, with no coordinates:
        the numbers are the point of the lookup, and the register on the other
        side of this checkpoint has a row for them the moment a lap goes by.
        """
        now = time.time()
        for profile in proto.player_profiles(payload):
            with self._lock:
                held = self._kinds["players"].get(profile.uid)
                if held is not None:
                    base = proto.PlayerBase.from_dict(held).merged_with(profile)
                    record = base.as_dict()
                    record["seen_at"] = held.get("seen_at") or int(now)
                else:
                    record = profile.as_base().as_dict()
                    record["seen_at"] = int(now)
                record["profile_seen_at"] = int(now)
                self._kinds["players"][profile.uid] = self._stamp(record)
                self.profiles_seen += 1

    def _take_remarks(self, payload) -> None:
        """Take this account's own notes on other players (`user.remark.list`).

        Kept by uid alone — a note follows the player and not their base — and
        stamped onto what is already held as well as onto whatever arrives next.
        An entry with no text is a note that was deleted, and clears the field
        rather than leaving stale words on the row.
        """
        with self._lock:
            for uid, remark, _updated in proto.player_remarks(payload):
                if remark is None:
                    self._remarks.pop(uid, None)
                    held = self._kinds["players"].get(uid)
                    if held is not None:
                        held["remark"] = None
                else:
                    self._remarks[uid] = remark
            self.remarks_known = len(self._remarks)
            for record in self._kinds["players"].values():
                self._stamp(record)

    def on_response(self, command, payload) -> None:
        """Everything else the server says: the march stream, and its removals."""
        if command == proto.PROFILE_COMMAND and isinstance(payload, dict):
            self._take_profiles(payload)
            return
        if command == proto.REMARK_COMMAND and isinstance(payload, dict):
            self._take_remarks(payload)
            return
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
                    self._met_owner(record, now)

    def _met_owner(self, record: dict, now: float) -> None:
        """A vehicle's OWNER is a player we have just been told about (#1371).

        A truck carries its owner's uid, nickname, alliance and country — everything a
        base tile does except where they live. So the player is kept, without a
        coordinate: their base is wherever it is, and a lorry on the road says nothing
        about it. **The position is deliberately not written** — that is the truck's,
        and merging it would move the player onto a road.

        Fills only what is missing on a player already held: a base tile is the better
        word for a name and an alliance, and this must never undo it. Callers hold
        `_lock`.
        """
        uid = str(record.get("owner_uid") or "").strip()
        if not uid or not uid.isdigit():
            return
        held = self._kinds["players"].get(uid)
        if held is None:
            held = {"uid": uid, "server_id": record.get("server_id"),
                    "x": None, "y": None, "uuid": None,
                    "name": None, "level": None, "alliance_id": None,
                    "alliance_abbr": None, "country": None,
                    "power": None, "army_power": None, "army_kill": None,
                    "svip_level": None, "remark": None}
            self._kinds["players"][uid] = held
            self.players_seen += 1
        for mine, theirs in (("name", "owner_name"), ("alliance_id", "alliance_id"),
                             ("alliance_abbr", "alliance_abbr"),
                             ("country", "country")):
            if held.get(mine) is None and record.get(theirs) is not None:
                held[mine] = record[theirs]
        held["seen_at"] = int(now)
        self._stamp(held)

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
                # PLAYERS ARE NOT DROPPED, and that is the difference between a
                # place and a thing that moves. A truck goes on being walked down
                # a route it may have left and a mine goes on claiming to be free,
                # on a map nobody is looking at — but a base does not stop being
                # where it was because the camera went to another server, and a
                # lap across two servers is a thing people do on purpose
                # (`tools/scan_players.py` keeps them for the same reason).
                if kind == "players":
                    continue
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
        """`{"mines": […], "trucks": […], "trains": […], "players": […]}`, fresh and capped.

        Eviction runs here, so the file never carries a sighting already past the
        window, and the cap is applied on a ranking that keeps what is worth
        keeping (see `_mine_rank`) rather than on dict order.
        """
        ranks = {"mines": _mine_rank, "trucks": _cargo_rank, "trains": _fresh_rank,
                 "players": _fresh_rank}
        out = {}
        with self._lock:
            self._evict(time.time())
            for kind, records in self._kinds.items():
                cap = self.max_players if kind == "players" else self.max_per_kind
                rows = sorted(records.values(), key=ranks[kind])
                self.dropped[kind] = max(len(rows) - cap, 0)
                out[kind] = rows[:cap]
        return out

    def counts(self) -> dict:
        """How many of each kind are currently held — for the progress line."""
        with self._lock:
            return {kind: len(records) for kind, records in self._kinds.items()}
