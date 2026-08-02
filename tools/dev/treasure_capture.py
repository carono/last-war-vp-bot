#!/usr/bin/env python3
r"""World-map treasure scan — the `f2 = 21` chests a detect event drops.

The third of the map scans, after `secret_task_capture.py` (`f2 = 17`) and
`secret_mission_capture.py` (`f2 = 29`). A detect-event treasure is a map point
like every other interactable: `world.get.block` hands it to anyone who pans over
it, so panning is what surfaces one — and `push.world.point.update` re-sends it on
every change, which is how the chest flips from *being dug* to *dug* without
anyone panning again.

Both streams are read here, and that matters: the only live treasure ever captured
(task #1107) arrived entirely as pushes. Ten frames carried the chest with no
finisher, the eleventh carried `f11.f7` — the operator uid — in the same second the
alliance got `push.detect.treasure.claim`. That field is the dug flag, and the
whole feature turns on it: a chest still being dug wants a march, a dug one wants
the claim (`detect.event.claim.treasure {uuid, targetServer}`).

    /mnt/c/Python312/python.exe tools/dev/treasure_capture.py                  stream, print, no file
    /mnt/c/Python312/python.exe tools/dev/treasure_capture.py --seconds 300     stop on a timer
    /mnt/c/Python312/python.exe tools/dev/treasure_capture.py --json out.json   checkpoint every tick
    /mnt/c/Python312/python.exe tools/dev/treasure_capture.py --dug             only chests already dug
    /mnt/c/Python312/python.exe tools/dev/treasure_capture.py --list-ifaces     interfaces, then exit

**Windows Python only.** WSL2 sits in a NAT'd VM whose network namespace is not
the host's, so a capture there sees WSL's own traffic and never a byte of the
game's. Requirements: npcap (ships with Wireshark), plus `pip install scapy
zstandard`.

A run that reports zero map responses means nobody was panning — not that the
capture is broken. And a detect event is not always running: on a quiet week there
is no chest on any map no matter how long this listens, which the closing summary
distinguishes from a deaf capture.

Lives in `tools/dev/` on purpose: the decode is confirmed against one recorded
treasure, but no live chest has been scanned off the map since it was written.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# Absolute, not "tools/lib": this script lives in tools/dev/, so the shared library
# is one level up, and it must resolve regardless of the launcher's cwd.
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "lib"))
sys.path.insert(0, _HERE)

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_OK, C_RESET  # noqa: E402
from map_capture import (  # noqa: E402
    MapIndex, add_capture_arguments, check_platform, dump_records, human_size,
    start_capture,
)

C_TREASURE = "\x1b[1;33m"  # bold yellow — the "worth acting on" colour

# A treasure is re-sent whenever the map is panned over it or the point changes, so
# the same "not re-sent within the window means untrustworthy" rule the other two
# scans use applies here; share their constant so all three agree on "current".
STALE_AFTER_SECONDS = proto.TASK_FRESH_SECONDS


class TreasureIndex(MapIndex):
    """MapIndex that keeps treasure points (`f2 = 21`), from blocks AND pushes.

    Keyed by `(server_id, uuid)` like the other two scans — a uuid is unique only
    within its server, so a chest on the server just left must not overwrite one on
    the server just joined.

    The push override is the difference from its siblings. `world.get.block` only
    arrives while the map moves; `push.world.point.update` arrives whenever the
    point changes, and the change that matters — someone finished the dig — is
    exactly the one nobody would be panning for.
    """

    def __init__(self, stale_after: float = STALE_AFTER_SECONDS) -> None:
        super().__init__()
        self.stale_after = stale_after
        self._treasures: dict[tuple, proto.WorldTreasure] = {}
        self._seen_at: dict[tuple, float] = {}
        # Points the pushes said are gone, so a `remove` retires the row instead of
        # leaving it to age out of the window.
        self.removed = 0

    # -- harvest -----------------------------------------------------------

    def on_blocks(self, payload, blocks, now: float) -> None:
        for treasure in proto.world_treasures(payload):
            self._keep(treasure, now)

    def on_response(self, command, payload) -> None:
        """Every server frame that is not a map block — where the pushes land.

        Called with `_index_lock` held (MapIndex.emit), same as `on_blocks`.
        """
        if command != "push.world.point.update":
            return
        now = time.time()
        if isinstance(payload, dict) and payload.get("type") == "remove":
            for point in payload.get("points") or ():
                tile = (point or {}).get("_protobuf") or {}
                if tile.get("f2") != proto.WORLD_TREASURE_TILE_TYPE:
                    continue
                key = (tile.get("f102") or tile.get("f103") or payload.get("sid"),
                       tile.get("f100"))
                if self._treasures.pop(key, None) is not None:
                    self._seen_at.pop(key, None)
                    self.removed += 1
            return
        for treasure in proto.world_treasure_points(command, payload):
            self._keep(treasure, now)

    def _keep(self, treasure, now: float) -> None:
        self._treasures[(treasure.server_id, treasure.uuid)] = treasure
        self._seen_at[(treasure.server_id, treasure.uuid)] = now

    def on_server_left(self, server: int) -> None:
        """Drop what was indexed for the map nobody is looking at any more."""
        self._evict(lambda key: key[0] != self.current_server)

    def _evict(self, doomed) -> None:
        for key in [k for k in self._seen_at if doomed(k)]:
            self._treasures.pop(key, None)
            self._seen_at.pop(key, None)

    # -- read --------------------------------------------------------------

    @property
    def treasures(self) -> list:
        cutoff = time.time() - self.stale_after
        with self._index_lock:
            self._evict(lambda key: self._seen_at[key] < cutoff)
            return list(self._treasures.values())

    @property
    def dug_count(self) -> int:
        """Chests already dug — the ones a claim can be sent for."""
        return sum(1 for t in self.treasures if t.dug)

    def records(self) -> list:
        """Fresh treasures as serialisable dicts, each stamped with `seen_at`."""
        cutoff = time.time() - self.stale_after
        with self._index_lock:
            self._evict(lambda key: self._seen_at[key] < cutoff)
            out = []
            for key, treasure in self._treasures.items():
                record = treasure.as_dict()
                record["seen_at"] = int(self._seen_at.get(key, 0))
                out.append(record)
        out.sort(key=lambda r: r.get("seen_at", 0), reverse=True)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_capture_arguments(ap)
    ap.add_argument("--json", default=None,
                    help="checkpoint every treasure seen to this file, rewritten "
                         "on every tick (default: no file is written)")
    ap.add_argument("--interval", type=int, default=15,
                    help="seconds between processing ticks — each prints the "
                         "progress line and rewrites --json (default 15)")
    ap.add_argument("--dug", action="store_true",
                    help="only chests already dug (a claim can be sent for those); "
                         "the ones still being dug want a march instead")
    args = ap.parse_args()
    # After parsing, so --help / --list-ifaces read from the WSL interpreter rather
    # than being refused by the capture-only platform check.
    check_platform()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                       # noqa: BLE001 — nothing to reconfigure
        pass

    index = TreasureIndex()
    stop, bpf = start_capture(index, args)

    print("Last War treasure scan — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    sink = f" -> {args.json} every {args.interval}s" if args.json else ""
    print(f"{C_DIM}listening {window}{sink} — pan the map over a treasure, or wait "
          f"for a point update on one{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    # (server, uuid, dug) already announced: a chest walks digging -> dug and each
    # step is worth one line, while a mere refresh stays silent.
    reported: set = set()
    deadline = time.time() + args.seconds if args.seconds else None
    last_tick = time.time()
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(1.0)
            for old, new in index.drain_server_changes():
                if old is None:
                    print(f"{C_OK}server {new}{C_RESET} — reading this map\n")
                else:
                    print(f"\n{C_OK}server {old} -> {new}{C_RESET} — dropped "
                          f"everything indexed for {old}\n")
                    reported.clear()
            if time.time() - last_tick >= args.interval:
                last_tick = time.time()
                left = (f"…{int(deadline - time.time())}s left"
                        if deadline is not None else "…running")
                where = (f"server {index.current_server}"
                         if index.current_server is not None else "server unknown yet")
                print(f"{C_DIM}  {left} — {where}, "
                      f"{index.blocks_seen} map response(s), "
                      f"{index.tiles_seen} tile(s), "
                      f"{len(index.treasures)} treasure(s), "
                      f"{index.dug_count} dug{C_RESET}")
                if args.json and not dump_records(index.records(), args.json):
                    print(f"{C_DIM}  (checkpoint locked, skipped this flush){C_RESET}")
                if index.transcript is not None:
                    index.transcript.flush()
                    print(f"{C_DIM}  transcript: {index.transcript.frames} frame(s), "
                          f"{human_size(index.transcript.size())}{C_RESET}")
            for t in index.treasures:
                if args.dug and not t.dug:
                    continue
                key = (t.server_id, t.uuid, t.dug)
                if key in reported:
                    continue
                reported.add(key)
                where = (f"({t.x:>4},{t.y:>4})" if t.x is not None else "(   ?,   ?)")
                tag = f"  {C_TREASURE}DUG{C_RESET}" if t.dug else "  digging"
                print(f"  {where}  server {t.server_id}  «{t.name or '?'}»  "
                      f"{t.alliance_abbr or '-'}  cfg {t.cfg_id}  "
                      f"pid {t.point_id}  uuid {t.uuid}{tag}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    everything = index.treasures
    matched = len({(server, uuid) for server, uuid, _dug in reported})
    where = (f" on server {index.current_server}"
             if index.current_server is not None else "")
    print(f"\n{len(everything)} treasure(s) seen{where}, {matched} reported, "
          f"{index.dug_count} dug now, {index.removed} removed while watching")
    print(f"traffic: {index.delivered} delivered / {index.packets} with payload, "
          f"{index.blocks_seen} map response(s), {index.tiles_seen} tile(s), "
          f"kinds {dict(index.tile_kinds)}")
    if not everything:
        print(f"{C_DIM}No treasure crossed the wire. A detect event is not always "
              f"running, and a chest only appears while the map is panned over it "
              f"or its point changes.{C_RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
