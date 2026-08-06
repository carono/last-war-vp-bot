#!/usr/bin/env python3
"""Unfiltered `world.get.block` tile dump, cross-referenced with ghost recon.

Premise under test (task #1010): the claim that a ghost-recon mission ("Операция
Призрак") can be found by a *tile scan* the way a secret task is — i.e. that the
mission's target tile shows up in `world.get.block` when you pan the map over its
coordinate. The two things we already know ride completely different transports:

  * a **secret task** IS a `world.get.block` tile (`f2 = 17`), handed to anyone
    who pans over it — `tools/secret_task_capture.py`;
  * a **ghost-recon mission** arrives only through `ghost.recon.*` polls and the
    `push.ghost.recon.alliance.single` stream — `tools/secret_mission_capture.py`.
    It carries a `pointId` (server-local `y*1000+x`) and a `targetServer`, so it
    HAS a map coordinate even if nothing was ever seen at that coordinate on the
    map wire.

This tool takes no side. It records **every** tile of **every** `f2` kind with
NO filter on `f2` or family — the full raw protobuf of each — and in parallel
learns the active ghost-recon missions off the same connection. At each tick and
at exit it cross-references the two: for every known mission it looks for a tile
at the mission's `(x, y, targetServer)` and for a tile whose `f100` uuid equals
the mission uuid. If the claim holds, a match appears and its `f2` kind plus raw
fields are exactly "what distinguishes a ghost-recon tile". If none ever does —
across a run where the player demonstrably walked over the mission (the mission
was live in the ghost-recon panel, and the map was panning over its coordinate,
both of which the counters below prove) — that is the evidence the claim is
false and the mission tile simply is not on `world.get.block`.

    /mnt/c/Python312/python.exe tools/ghost_recon_tile_dump.py --seconds 300
                                              dump tiles + missions for 5 min
    ... --tiles tiles.jsonl                   record every tile (decoded, raw
                                              protobuf) as JSONL for offline diff
    ... --dump frames.jsonl                   also keep the full frame transcript
                                              (both directions) — inherited flag
    ... --near-only                           print only tiles that match a mission
                                              (coordinate or uuid) — the signal,
                                              without the whole map as noise
    ... --list-ifaces                         interfaces, then exit

Runs under the **Windows** Python, same as every other capture here (WSL's NAT'd
namespace never sees the game's packets). Requires npcap + `pip install scapy
zstandard` on that interpreter. Open the ghost-recon panel once so the client
polls `ghost.recon.get.task.list` (that is how the mission list is learned), then
pan the map back and forth across the mission's coordinate.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections import Counter

sys.path.insert(0, "tools/lib")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET  # noqa: E402
from map_capture import (  # noqa: E402
    MapIndex, add_capture_arguments, block_servers, check_platform,
    dump_records, human_size, start_capture,
)

# Kinds we already have a decoder/name for (protocol.md §"Object types"). A tile
# whose f2 is NOT in here is a genuine unknown — the first place a ghost-recon
# tile would hide if the claim were true and it simply used a new type byte.
KNOWN_KINDS = {
    6: "player base",
    7: "resource mine",
    11: "stronghold/fortress",
    17: "secret task / hero dispatch",
    21: "alliance HQ",
    25: "named facility",
    29: "ghost recon squad (Операция Призрак)",  # confirmed task #1010
    35: "named facility (fixed grid)",
}


def _nested_cfgids(raw, depth=0):
    """Yield every `f2` int found *below* the tile's top level.

    The top-level `f2` is the tile type (kept separately); a `f2` nested inside
    a detail block (`f10.f2` on a task, and the like) is a cfgId. Walking the
    whole structure rather than hard-coding `f10.f2` keeps it honest for a tile
    kind we have never decoded — a ghost tile could nest its cfgId anywhere.
    """
    if isinstance(raw, dict):
        for key, val in raw.items():
            if depth > 0 and str(key) == "f2" and isinstance(val, int):
                yield val
            yield from _nested_cfgids(val, depth + 1)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            yield from _nested_cfgids(item, depth + 1)


def _parse_target(spec):
    """`"967:15:414"` -> `(967, 15, 414)`; `"15:414"` -> `(None, 15, 414)`."""
    parts = [p.strip() for p in spec.split(":")]
    if len(parts) == 3:
        return int(parts[0]), int(parts[1]), int(parts[2])
    if len(parts) == 2:
        return None, int(parts[0]), int(parts[1])
    raise argparse.ArgumentTypeError(
        "target must be SERVER:X:Y or X:Y, e.g. 967:15:414")


def _decode_cfg(cfg):
    """`(family, level)` for a GHOST cfgId — the level the game shows, not the digits.

    `split_cfg_id` reads `MM` straight and answers 1/2/3 where the client's own template
    says 3/4/5; the mapping is `MM + 2` and it lives in `proto.ghost_recon_level`
    (#1137). Splitting it by hand here made this dump the one place that disagreed with
    every other ghost reading — the same class of drift that had the secret-task tool
    calling a level-7 tile «level 99» (#1267).

    Still arithmetic, because a dump reads TILES off the map and a tile carries a cfgId
    and nothing else. Where the client's list is what is being read, the template's own
    `level` column is (`lua_actions.ghost_recon_templates_dump`).
    """
    family, level = proto.ghost_recon_level(cfg)
    return family, level


def _jsonable(value):
    """Best-effort convert a decoded protobuf value into something json-safe.

    The decoder hands back plain dicts/lists/ints/strings, but bytes can slip
    through on an unrecognised field; str() them rather than fail the whole
    dump. Keeps the structure otherwise intact so an offline `jq` pass sees the
    real field numbers.
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


class TileDumpIndex(MapIndex):
    """Keeps every tile raw, plus every ghost-recon mission it overhears.

    Tiles are keyed by `(server_id, uuid)` when the tile carries an `f100`
    uuid, else by `(server_id, packed_f1)` — the map re-sends a region every
    time it is panned, so a stable key refreshes a record rather than piling up
    duplicates, the same reasoning as `secret_task_capture.TaskIndex`. Nothing
    is dropped by kind: the point of this index is the tiles the task index
    throws away.
    """

    def __init__(self) -> None:
        super().__init__()
        # key -> raw tile record (dict). See _tile_record for the shape.
        self._tiles: dict[tuple, dict] = {}
        # uuid -> mission dict, learned from ghost.recon.* and the push.
        self._missions: dict[int, dict] = {}
        # Optional JSONL sink for every tile, set from --dump.
        self._sink = None
        self._sink_count = 0

    # -- tiles -------------------------------------------------------------

    def on_blocks(self, payload, blocks, now: float) -> None:
        for block in blocks:
            area = block.get("maxAreaSize") or 1000
            server = block.get("serverId")
            for point in block.get("points") or ():
                tile = point.get("_protobuf") or {}
                record = self._tile_record(tile, server, area, now)
                key = (record["server_id"], record["uuid"]
                       if record["uuid"] is not None else ("f1", record["f1"]))
                self._tiles[key] = record
                if self._sink is not None:
                    self._sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                    self._sink_count += 1

    def _tile_record(self, tile, server, area, now) -> dict:
        packed = tile.get("f1") or 0
        f2 = tile.get("f2")
        return {
            "seen_at": int(now),
            "server_id": tile.get("f102") or tile.get("f103") or server,
            "block_server_id": server,
            "uuid": tile.get("f100"),
            "f2": f2,
            "kind": KNOWN_KINDS.get(f2, f"UNKNOWN({f2})"),
            "x": packed % area,
            "y": packed // area,
            "f1": packed,
            "area": area,
            # The whole tile, verbatim, so nothing is lost to this schema. This
            # is what makes the dump authoritative: any field a ghost tile might
            # use is here even if this tool never names it.
            "raw": _jsonable(tile),
        }

    # -- ghost recon (learned off the same connection) ---------------------

    def on_response(self, command, payload) -> None:
        if command == proto.GHOST_ALLIANCE_PUSH:
            decoded = proto.ghost_recon_alliance_push(payload)
            if decoded is not None:
                kind, mission = decoded
                if kind == "remove":
                    self._missions.pop(mission.uuid, None)
                else:
                    self._remember_mission(mission)
            return
        if command in proto.GHOST_RECON_COMMANDS:
            for mission in proto.ghost_recon_missions(command, payload):
                self._remember_mission(mission)

    def _remember_mission(self, mission) -> None:
        # A polled row with a real target overwrites a bare push remove/stub;
        # keep the richest version keyed by uuid.
        self._missions[mission.uuid] = {
            "uuid": mission.uuid,
            "cfg_id": mission.cfg_id,
            "family": mission.family,
            "level": mission.level,
            "state": mission.state,
            "x": mission.x,
            "y": mission.y,
            "point_id": mission.point_id,
            "target_server": mission.target_server,
            "owner_id": mission.owner_id,
            "owner_server": mission.owner_server,
            "alliance_id": mission.alliance_id,
        }

    # -- views -------------------------------------------------------------

    @property
    def tiles(self) -> list:
        with self._index_lock:
            return list(self._tiles.values())

    @property
    def missions(self) -> list:
        with self._index_lock:
            return list(self._missions.values())

    def matches(self) -> list:
        """Cross-reference: tiles that line up with a known mission.

        Two independent tests, because either alone would be a lead:
          * **uuid** — a tile whose `f100` equals a mission uuid is the mission,
            beyond doubt;
          * **coordinate** — a tile at the mission's `(x, y)` on its
            `targetServer`. Coordinates are server-local `y*1000+x` on both
            sides (protocol.md §"Coordinates"), so they compare directly with no
            lift. A coordinate hit without a uuid hit still tells us the map
            draws *something* where the mission is.
        """
        with self._index_lock:
            tiles = list(self._tiles.values())
            missions = list(self._missions.values())
        by_uuid = {t["uuid"]: t for t in tiles if t["uuid"] is not None}
        by_coord: dict[tuple, list] = {}
        for t in tiles:
            by_coord.setdefault((t["server_id"], t["x"], t["y"]), []).append(t)

        out = []
        for m in missions:
            hit_uuid = by_uuid.get(m["uuid"])
            hit_coord = []
            if m["x"] is not None and m["target_server"] is not None:
                hit_coord = by_coord.get(
                    (m["target_server"], m["x"], m["y"]), [])
            if hit_uuid or hit_coord:
                out.append({"mission": m, "by_uuid": hit_uuid,
                            "by_coord": hit_coord})
        return out

    def near(self, server, x, y, radius) -> list:
        """Every captured tile within `radius` cells of `(x, y)` on `server`.

        Chebyshev distance (a square window), because a "±5" radius is how the
        request came in and a square is what the map hands out anyway. When
        `server` is None the filter is coordinate-only — useful if the target
        server was never positively identified but the player was over the
        right cell. Returned nearest-first, each with its `dist` stamped.
        """
        out = []
        for t in self.tiles:
            if server is not None and t["server_id"] != server:
                continue
            if t["x"] is None or t["y"] is None:
                continue
            dist = max(abs(t["x"] - x), abs(t["y"] - y))
            if dist <= radius:
                out.append({**t, "dist": dist})
        out.sort(key=lambda t: t["dist"])
        return out

    def vocabulary(self) -> tuple:
        """`(f2_counts, cfgid_counts)` over every captured tile.

        `f2_counts` is the top-level tile-type byte — the unfiltered census the
        task asks for. `cfgid_counts` gathers every *nested* `f2` value (the
        cfgId a task/mission tile carries in its detail block, e.g. `f10.f2`),
        decoded to `family/level` where possible. A ghost tile, if it exists,
        should surface here as a cfgId whose family is a ghost tier (4/5/6),
        distinct from the secret-task star family (6000).
        """
        f2_counts: Counter = Counter()
        cfgid_counts: Counter = Counter()
        for t in self.tiles:
            f2_counts[t["f2"]] += 1
            for cfg in _nested_cfgids(t["raw"]):
                cfgid_counts[cfg] += 1
        return f2_counts, cfgid_counts

    def open_sink(self, path) -> bool:
        try:
            self._sink = open(path, "w", encoding="utf-8")
            return True
        except OSError:
            return False

    def close_sink(self) -> None:
        if self._sink is not None:
            self._sink.flush()
            self._sink.close()


def _print_match(match) -> None:
    m = match["mission"]
    where = (f"server {m['target_server']} ({m['x']},{m['y']})"
             if m["x"] is not None else f"server {m['target_server']} (no point)")
    print(f"{C_OK}>>> ghost mission uuid {m['uuid']}  cfg {m['cfg_id']}  "
          f"fam {m['family']} lvl {m['level']}  state {m['state']}  "
          f"{where}{C_RESET}")
    if match["by_uuid"]:
        t = match["by_uuid"]
        print(f"    {C_OK}UUID MATCH{C_RESET} — tile f2={t['f2']} "
              f"({t['kind']}) at ({t['x']},{t['y']}) server {t['server_id']}")
        print(f"    raw: {json.dumps(t['raw'], ensure_ascii=False)}")
    for t in match["by_coord"]:
        if match["by_uuid"] and t["uuid"] == match["by_uuid"]["uuid"]:
            continue  # already printed as the uuid hit
        print(f"    {C_OK}COORD MATCH{C_RESET} — tile f2={t['f2']} "
              f"({t['kind']}) uuid {t['uuid']} at ({t['x']},{t['y']}) "
              f"server {t['server_id']}")
        print(f"    raw: {json.dumps(t['raw'], ensure_ascii=False)}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_capture_arguments(ap)
    ap.add_argument("--tiles", default=None, metavar="FILE",
                    help="append every decoded tile (raw protobuf) to this "
                         "JSONL file for offline analysis (distinct from the "
                         "inherited --dump frame transcript)")
    ap.add_argument("--near-only", action="store_true",
                    help="print only tiles matching a known mission (by "
                         "coordinate or uuid); skip the per-kind histogram spam")
    ap.add_argument("--interval", type=int, default=15,
                    help="seconds between progress ticks (default 15)")
    ap.add_argument("--target", type=_parse_target, default=None,
                    metavar="S:X:Y",
                    help="a known mission cell, e.g. 967:15:414 (or X:Y for "
                         "any server) — every tick and at exit, dump every "
                         "captured tile within --radius of it, in full")
    ap.add_argument("--radius", type=int, default=20,
                    help="Chebyshev radius (cells) around --target to report "
                         "(default 20)")
    args = ap.parse_args()
    check_platform()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    index = TileDumpIndex()
    if args.tiles and not index.open_sink(args.tiles):
        print(f"{C_ERR}cannot open {args.tiles} for writing{C_RESET}")
        return 1

    stop, bpf = start_capture(index, args)
    print("Ghost-recon tile dump — ALL f2 kinds, no filter")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    print(f"{C_DIM}listening {window} — open the ghost-recon panel once, then "
          f"pan over the mission coordinate{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

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
                    print(f"\n{C_OK}server {old} -> {new}{C_RESET}\n")

            # Matches are printed as they appear, once each, regardless of tick.
            for match in index.matches():
                m = match["mission"]
                key = (m["uuid"],
                       match["by_uuid"] is not None,
                       tuple(sorted(t["uuid"] or t["f1"]
                                    for t in match["by_coord"])))
                if key in reported:
                    continue
                reported.add(key)
                _print_match(match)

            if time.time() - last_tick >= args.interval:
                last_tick = time.time()
                left = (f"…{int(deadline - time.time())}s left"
                        if deadline is not None else "…running")
                kinds = Counter()
                for t in index.tiles:
                    kinds[t["f2"]] += 1
                unknown = {k: v for k, v in kinds.items()
                           if k not in KNOWN_KINDS}
                print(f"{C_DIM}  {left} — {index.blocks_seen} map response(s), "
                      f"{len(index.tiles)} distinct tile(s), "
                      f"{len(index.missions)} ghost mission(s) learned, "
                      f"{len(reported)} match(es){C_RESET}")
                if not args.near_only:
                    named = {KNOWN_KINDS.get(k, f"UNKNOWN({k})"): v
                             for k, v in sorted(kinds.items(),
                                                key=lambda kv: -kv[1])}
                    print(f"{C_DIM}  kinds: {named}{C_RESET}")
                if unknown:
                    print(f"  {C_OK}UNKNOWN f2 kinds present: {dict(unknown)}"
                          f"{C_RESET} — candidate ghost-recon tiles")
                if args.target:
                    ts, tx, ty = args.target
                    nearby = index.near(ts, tx, ty, args.radius)
                    where = f"server {ts}" if ts is not None else "any server"
                    print(f"  {C_OK}{len(nearby)} tile(s) within {args.radius} "
                          f"of ({tx},{ty}) on {where}{C_RESET}"
                          + (f" — nearest at ({nearby[0]['x']},"
                             f"{nearby[0]['y']}) d{nearby[0]['dist']} "
                             f"f2={nearby[0]['f2']}" if nearby else ""))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    tiles = index.tiles
    missions = index.missions
    matches = index.matches()
    kinds = Counter(t["f2"] for t in tiles)
    print(f"\n{len(tiles)} distinct tile(s) over {index.blocks_seen} map "
          f"response(s); kinds "
          f"{ {KNOWN_KINDS.get(k, f'UNKNOWN({k})'): v for k, v in kinds.items()} }")
    print(f"{len(missions)} ghost-recon mission(s) learned, "
          f"{len(matches)} tile/mission match(es)")

    if not missions:
        print(f"{C_DIM}No ghost-recon mission was learned — open the "
              f"'Операция Призрак' panel so the client polls the list, then "
              f"re-run. Without a known mission there is nothing to match "
              f"tiles against.{C_RESET}")
    elif not matches:
        # The whole point of the run: missions were known, tiles were dumped,
        # and NOTHING lined up. State it plainly rather than as a null result.
        print(f"{C_OK}Result: the {len(missions)} known mission(s) matched NO "
              f"tile — neither by uuid nor by coordinate. On this run the "
              f"ghost-recon mission was NOT present on world.get.block. Confirm "
              f"the map was actually panned over the mission's coordinate "
              f"(tiles at that x,y should appear above) before concluding."
              f"{C_RESET}")
        for m in missions:
            here = [t for t in tiles
                    if t["server_id"] == m["target_server"]
                    and t["x"] == m["x"] and t["y"] == m["y"]]
            print(f"  mission uuid {m['uuid']} target server "
                  f"{m['target_server']} ({m['x']},{m['y']}): "
                  f"{len(here)} tile(s) captured at that exact cell")

    # -- unfiltered vocabulary: every f2 and every cfgId seen ---------------
    f2_counts, cfgid_counts = index.vocabulary()
    print(f"\n{C_OK}== unique f2 (tile type) values =={C_RESET}")
    for k, v in sorted(f2_counts.items(), key=lambda kv: -kv[1]):
        print(f"  f2={k}  x{v}  {KNOWN_KINDS.get(k, 'UNKNOWN — candidate')}")
    print(f"{C_OK}== unique nested cfgId values =={C_RESET}")
    if not cfgid_counts:
        print("  (none — no task/mission-shaped tile carried a nested cfgId)")
    for cfg, v in sorted(cfgid_counts.items(), key=lambda kv: -kv[1]):
        fam, lvl = _decode_cfg(cfg)
        note = ""
        if fam in (4, 5, 6):
            note = f"  {C_OK}<- ghost-tier family {fam}{C_RESET}"
        elif fam == 6000:
            note = "  (secret-task star family)"
        print(f"  cfgId={cfg}  x{v}  family={fam} level={lvl}{note}")

    # -- the coordinate the task actually asked about -----------------------
    if args.target:
        ts, tx, ty = args.target
        nearby = index.near(ts, tx, ty, args.radius)
        where = f"server {ts}" if ts is not None else "any server"
        print(f"\n{C_OK}== tiles within {args.radius} cells of ({tx},{ty}) on "
              f"{where} =={C_RESET}  ({len(nearby)} found)")
        if not nearby:
            print(f"{C_DIM}  nothing captured near that cell — was the map "
                  f"actually panned over ({tx},{ty})? A zero here with "
                  f"{index.blocks_seen} map response(s) means the viewport "
                  f"never covered it.{C_RESET}")
        for t in nearby:
            print(f"\n  d{t['dist']}  ({t['x']},{t['y']}) server {t['server_id']}"
                  f"  f2={t['f2']} ({t['kind']})  uuid {t['uuid']}")
            print(f"  {json.dumps(t['raw'], ensure_ascii=False)}")

    if args.tiles:
        index.close_sink()
        print(f"\n{C_OK}wrote {index._sink_count} tile record(s) to "
              f"{args.tiles}{C_RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
