#!/usr/bin/env python3
"""Live monitor for alliance-shared **secret missions** (секретные миссии).

A *secret task* (`secret_task_capture.py`, protocol.md §7, tile `f2 = 17`) is a
hero-dispatch marker the map hands out on `world.get.block` to anyone who pans
over it — you only see one by scrolling the map onto it. A *shared secret
mission* is the other half of the same feature: an ally found a mission worth
raiding, pressed **share**, and the server broadcast it to the whole alliance.
It never rides `world.get.block`. It arrives as its own push, so this monitor
finds missions the map scan never can — nobody has to be looking at that patch
of map, an ally just has to press the button.

Two commands carry them (both decoded by `lastwar_proto.share_missions`):

    push.alliance.share.mission.add        one mission, broadcast live
    get.alliance.share.mission.list        the snapshot pulled on login
                                           (shareMissionArr[])

Each mission carries the same `missionCfgId` / `missionUuid` a task tile would,
so level and the star are read the same way (`cfgId` family 6000 = starred —
and a shared mission is almost always starred, because the star is what a
player bothers to share). What it does *not* carry is the tile's dispatch/loot
state, so this reports "a mission became available to raid", not "you can raid
it right now" — cross-check the uuid against a `secret_task_capture` scan for
that.

Usage (run from WSL — it drives Wireshark's `dumpcap.exe`, same as
`rally_monitor.py`; the game and its traffic are on the Windows side)::

    python3 tools/secret_mission_capture.py                 stream, print each
    python3 tools/secret_mission_capture.py --star          only starred ones
    python3 tools/secret_mission_capture.py --level 7,8      level 7 or 8
    python3 tools/secret_mission_capture.py --server 946     one server only
    python3 tools/secret_mission_capture.py --json out.json  checkpoint to file
    python3 tools/secret_mission_capture.py --duration 3600  stop on a timer
    python3 tools/secret_mission_capture.py --list           interfaces, exit

Every distinct `missionUuid` is announced **once**; a re-broadcast of one
already seen only bumps its share counter, so a chatty alliance does not spam
the log. Passive capture only — active RE is ACE-blocked (see
docs/research/socket-duplication.md).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import live_tshark as lt  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET, LiveDecoder  # noqa: E402
import lastwar_proto as proto  # noqa: E402

C_MISSION = "\x1b[1;33m"  # bold yellow, the "worth raiding" colour


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def _short(value, keep: int = 8) -> str:
    """Trim a long id (alliance hash, uid) for a one-line log."""
    text = str(value) if value is not None else "-"
    return text if len(text) <= keep + 1 else text[:keep] + "…"


def _write_checkpoint(records: list, path: str) -> bool:
    """Rewrite `path` whole with the current mission records. True on success.

    Written in place rather than via an atomic rename for the same reason
    `map_capture.dump_records` is: on Windows `os.replace` raises when anything
    else holds the target open (an editor, a poller), which would kill the run.
    A locked file costs one skipped flush; the next one rewrites it whole.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False)
        return True
    except PermissionError:
        return False


class MissionMonitor(LiveDecoder):
    """LiveDecoder that harvests the alliance-shared secret-mission stream.

    Missions are keyed by `missionUuid`. The first sighting of a uuid that
    passes the filter is announced; later re-broadcasts of the same uuid only
    refresh its record and bump `share_count`, so the log carries one line per
    distinct mission rather than one per broadcast.
    """

    def __init__(self, level=None, star_only=False, server=None,
                 json_path: str | None = None) -> None:
        super().__init__()
        self.level = level
        self.star_only = star_only
        self.server = server
        self.json_path = json_path
        self.frames = 0                 # share frames that decoded to a mission
        self._missions: dict = {}       # uuid -> record dict
        self._announced: set = set()    # uuids already printed

    # -- decode ------------------------------------------------------------

    def emit(self, direction: str, env) -> None:  # LiveDecoder hook
        if direction != "down":
            return
        command = proto.envelope_command(env)
        if command not in proto.SHARE_MISSION_COMMANDS:
            return
        payload = proto.envelope_payload(env)
        missions = list(proto.share_missions(command, payload))
        if not missions:
            return
        self.frames += 1
        now = time.time()
        for mission in missions:
            self._record(mission, command, now)

    def _record(self, mission, command: str, now: float) -> None:
        uuid = mission.uuid
        rec = self._missions.get(uuid)
        if rec is None:
            rec = mission.as_dict()
            rec["starred"] = mission.starred
            rec["first_seen"] = int(now)
            rec["share_count"] = 0
            rec["last_command"] = command
            self._missions[uuid] = rec
        rec["last_seen"] = int(now)
        rec["share_count"] += 1
        rec["last_command"] = command
        self._announce(mission, rec)

    # -- report ------------------------------------------------------------

    def _passes(self, mission) -> bool:
        """The active --level/--star/--server filter, applied to one mission."""
        return bool(proto.filter_share_missions(
            [mission], level=self.level, star_only=self.star_only,
            server=self.server))

    def _announce(self, mission, rec) -> None:
        # One line per distinct uuid, and only for missions the filter keeps.
        if mission.uuid in self._announced or not self._passes(mission):
            return
        self._announced.add(mission.uuid)
        star = f"{C_MISSION} *{C_RESET}" if mission.starred else "  "
        lvl = mission.level if mission.level is not None else "?"
        print(f"{_stamp()} SHARE{star} lvl {str(lvl):>2}  "
              f"server {mission.server_id}  uuid {mission.uuid}  "
              f"cfg {mission.cfg_id}  by {_short(mission.share_uid)}  "
              f"alliance {_short(mission.share_alliance_id)}", flush=True)
        if self.json_path and not _write_checkpoint(self.records(), self.json_path):
            print(f"{C_DIM}  (checkpoint locked, skipped this flush){C_RESET}",
                  flush=True)

    def records(self) -> list:
        """All missions seen so far, as serialisable dicts (newest first)."""
        return sorted(self._missions.values(),
                      key=lambda r: r.get("last_seen", 0), reverse=True)

    def report(self) -> None:
        matched = len(self._announced)
        print(f"\n{C_DIM}{'-' * 64}{C_RESET}")
        print(f"{C_OK}{len(self._missions)} mission(s) shared, "
              f"{matched} matched the filter{C_RESET} "
              f"— from {self.frames} share frame(s)")
        for rec in self.records():
            if rec["uuid"] not in self._announced:
                continue
            star = " *" if rec.get("starred") else "  "
            print(f" {star} lvl {rec.get('level')}  server {rec.get('server_id')}"
                  f"  uuid {rec.get('uuid')}  cfg {rec.get('cfg_id')}"
                  f"  x{rec.get('share_count')}")
        if not self._missions:
            print(f"{C_DIM}No missions were shared while listening. These arrive "
                  f"only when an alliance member presses \"share\" on a secret "
                  f"mission — nothing you can pan the map to force.{C_RESET}")
        if self.json_path:
            if _write_checkpoint(self.records(), self.json_path):
                print(f"{C_OK}wrote {len(self._missions)} mission(s) to "
                      f"{self.json_path}{C_RESET}")
            else:
                print(f"{C_ERR}could not write {self.json_path} — held by another "
                      f"process.{C_RESET}")


def _level_set(text: str):
    """`--level 7` or `--level 7,8` → a set of ints (argparse-friendly)."""
    out = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"{part!r} is not a level; expected a number or list like 7,8")
    if not out:
        raise argparse.ArgumentTypeError("no level given")
    return out


def main() -> int:
    signal.signal(signal.SIGTERM, lt._terminate)

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", default=None,
                    help="checkpoint every mission seen to this file, rewritten "
                         "on each new sighting (default: no file written)")
    ap.add_argument("--level", type=_level_set, metavar="N[,N...]",
                    help="only missions of this level (read from cfgId); a "
                         "comma-separated list matches any of them")
    ap.add_argument("--star", action="store_true",
                    help="only starred missions (cfgId family 6000)")
    ap.add_argument("--server", type=int, default=None,
                    help="only missions whose tile currently sits on this "
                         "server (missionCurrentServerId)")
    ap.add_argument("--iface", help="interface number from `dumpcap -D`; "
                                    "omitted = capture on all of them")
    ap.add_argument("--list", action="store_true", dest="list_ifaces",
                    help="list capture interfaces, then exit")
    ap.add_argument("--duration", type=int, default=1800,
                    help="stop after N seconds (default 1800 = 30 min)")
    ap.add_argument("--filter", default="tcp port 17935",
                    help="capture BPF (default pins the game port)")
    ap.add_argument("--tshark", help="path to tshark.exe")
    ap.add_argument("--dumpcap", help="path to dumpcap.exe")
    args = ap.parse_args()

    tshark = lt.find_binary("tshark.exe", args.tshark)
    dumpcap = lt.find_binary("dumpcap.exe", args.dumpcap) or tshark
    if not tshark or not dumpcap:
        print(f"{C_ERR}Wireshark not found (tshark.exe/dumpcap.exe).{C_RESET}",
              file=sys.stderr)
        return 1

    ifaces = lt.list_interfaces(tshark)
    if not ifaces:
        print(f"{C_ERR}no capture interfaces found{C_RESET}", file=sys.stderr)
        return 1
    if args.list_ifaces:
        for number, label in ifaces:
            print(f"  {number}  {label}")
        return 0
    targets = [(args.iface, f"iface {args.iface}")] if args.iface else ifaces

    monitor = MissionMonitor(level=args.level, star_only=args.star,
                             server=args.server, json_path=args.json)
    stop = threading.Event()
    sink = f" -> {args.json}" if args.json else ""
    print(f"Secret-mission monitor via {os.path.basename(dumpcap)} — "
          f"{len(targets)} iface(s), filter {args.filter!r}, {args.duration}s")
    print(f"{C_DIM}listening for alliance.share.mission broadcasts{sink}  "
          f"(Ctrl+C to stop) — these arrive when an ally shares a mission, "
          f"not when you move the map{C_RESET}\n")

    procs: list = []
    threads = [
        threading.Thread(target=lt.capture,
                         args=(dumpcap, number, label, monitor, args.filter,
                               stop, False, procs),
                         daemon=True)
        for number, label in targets
    ]
    for thread in threads:
        thread.start()

    deadline = time.time() + args.duration
    try:
        while not stop.is_set() and time.time() < deadline:
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for proc in procs:
            try:
                proc.kill()
            except Exception:
                pass
        for thread in threads:
            thread.join(timeout=2)

    monitor.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
