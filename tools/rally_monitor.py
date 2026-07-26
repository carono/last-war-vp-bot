#!/usr/bin/env python3
"""Live rally (стяг) monitor — harvest the armies out of alliance rallies.

Decodes the ``push.alliance.march.create`` / ``push.alliance.march.refresh``
stream, pulls every participant's ``armyInfo`` (the base64 protobuf squad — hero
ids, tiers, levels, skills) and writes one JSON line per participant to
``results/rally/monitor.jsonl`` for later analysis.

    /mnt/c/Python312/python.exe tools/rally_monitor.py
    /mnt/c/Python312/python.exe tools/rally_monitor.py --seconds 300
    /mnt/c/Python312/python.exe tools/rally_monitor.py --out results/rally/monitor.jsonl
    /mnt/c/Python312/python.exe tools/rally_monitor.py --iface \\Device\\NPF_... --seconds 1800
    /mnt/c/Python312/python.exe tools/rally_monitor.py --list-ifaces   interfaces, then exit

Each JSONL line::

    {timestamp, teamUuid, ownerUid, ownerName, power, curHp,
     heroes:[{heroId, tier, level, skills:[{skillId, level}]}],
     formation, armyInfoRaw}

On Ctrl+C (or the ``--seconds`` timer) it prints a short summary: how many
distinct rally teams (стяги) and how many distinct participants were seen.

Transport is scapy/npcap via ``map_capture.start_capture`` — the same
driver-only path as ``secret_task_capture.py`` and ``secret_mission_capture.py``,
with no ``dumpcap.exe`` or ``tshark.exe`` spawned. Unlike those two this is *not*
a ``world.get.block`` map scan: a rally rides the ``push.alliance.march.*`` push
stream, so ``RallyMonitor`` stays a plain ``LiveDecoder`` rather than a
``MapIndex`` — ``LiveDecoder.feed_packet`` and ``start_capture`` both drive a
LiveDecoder that is not a MapIndex, so nothing here needs the map machinery
(server election, tile blocks) that the map scanners subclass.

**This must run under the Windows Python, not the WSL one.** WSL2 sits in a
NAT'd VM whose network namespace is not the host's, so a capture there sees
WSL's own traffic and never a byte of the game's — see
``map_capture.check_platform()``. Requirements on that interpreter: npcap
(ships with Wireshark), plus ``pip install scapy zstandard``.

Field semantics inside ``armyInfo`` are **inferred structurally** — the game
ships no ``.proto`` (see docs/research/protocol.md §7). The best-effort mapping
below (``tier``/``level``/``skills``) is the current reading; the full decoded
protobuf is kept verbatim in ``armyInfoRaw`` on every line so the mapping can be
re-derived offline if it turns out wrong.

Passive capture only — active RE is ACE-blocked (see socket-duplication.md).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# Absolute, not "tools/lib": the shared modules resolve the same no matter what
# cwd the launcher (panel, daemon, shell) started us in.
sys.path.insert(0, os.path.join(_HERE, "lib"))
sys.path.insert(0, _HERE)

import coords  # noqa: E402  (canonical #server X:x Y:y token — clickable in the panel log)
import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_OK, C_RESET, LiveDecoder  # noqa: E402
from map_capture import (  # noqa: E402
    add_capture_arguments, check_platform, start_capture,
)

# The rally stream. Matched as a substring against the decoded command name so
# "alliance.march.create" also catches the push.-prefixed form, and the same for
# refresh. remove carries no armyInfo (bare {teamUuid, isCancel}) so it is left
# out — a rally launching does not add an army snapshot.
WANT = (
    "alliance.march.create",
    "alliance.march.refresh",
)

# A hero list uses ids 50006..50022; 1000000 is the air-support / drone slot
# that rides in the same squad list but is not a hero.
_DRONE_ID = 1000000

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "results", "rally", "monitor.jsonl",
)

C_RALLY = "\x1b[1;33m"  # bold yellow


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def _decode_b64_proto(text):
    """base64 → protobuf dict, or None if ``text`` is not a proto blob."""
    if not isinstance(text, str) or len(text) < 8:
        return None
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    decoded = proto.parse_protobuf(raw)
    return decoded or None


def _as_list(value):
    """A protobuf repeated field collapses to a bare dict when it occurs once."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _heroes(army_pb) -> list:
    """The per-hero squad rows out of a decoded ``armyInfo``.

    Squad list lives at ``f2.f2``. Per row (best-effort, names unverified):
    ``f1``=heroId, ``f3``=tier (star), ``f2``=level, ``f17``=skills
    (``[{f1:skillId, f2:level}]``). The drone slot (``f1``==1000000) is skipped.
    """
    squads = _as_list(((army_pb or {}).get("f2") or {}).get("f2"))
    out = []
    for row in squads:
        if not isinstance(row, dict):
            continue
        hero_id = row.get("f1")
        if hero_id == _DRONE_ID:
            continue
        skills = [
            {"skillId": s.get("f1"), "level": s.get("f2")}
            for s in _as_list(row.get("f17")) if isinstance(s, dict)
        ]
        out.append({
            "heroId": hero_id,
            "tier": row.get("f3"),
            "level": row.get("f2"),
            "skills": skills,
        })
    return out


def _formation(army_pb):
    """The formation / preset id — ``armyInfo.f2.f13`` (varies per owner)."""
    return ((army_pb or {}).get("f2") or {}).get("f13")


def _iter_marches(obj):
    """Yield every march-shaped dict (one carrying an ``armyInfo`` field).

    Reaches ``leaderMarch`` and each ``members[]`` entry of an alliance.march
    envelope wherever they sit in the decoded payload.
    """
    if isinstance(obj, dict):
        if "armyInfo" in obj and ("ownerUid" in obj or "ownerName" in obj):
            yield obj
        for val in obj.values():
            yield from _iter_marches(val)
    elif isinstance(obj, list):
        for val in obj:
            yield from _iter_marches(val)


def _march_target(march):
    """Best-effort (x, y, server|None) of a rally's target from a march dict.

    Rally participants all march to the same point, so any one march yields it. Covers the
    known march-position encodings: a named packed point id, explicit x/y, or the raw
    protobuf `f9`/`f10` legs (as trucks / world marches carry them; `_unpack_march_pos`
    decodes `y*1000+x`). Returns None when no coordinate is present.
    """
    if not isinstance(march, dict):
        return None
    for key in ("pointId", "point", "targetPoint", "targetPointId"):
        pos = proto._unpack_march_pos(march.get(key))
        if pos and pos != (0, 0):
            return pos[0], pos[1], march.get("targetServer") or march.get("serverId")
    x = march.get("targetX", march.get("x"))
    y = march.get("targetY", march.get("y"))
    if isinstance(x, int) and isinstance(y, int) and (x or y):
        return x, y, march.get("targetServer") or march.get("serverId")
    raw = march.get("_proto")
    info = getattr(raw, "_protobuf", None) if raw is not None else None
    if isinstance(info, dict):
        pos = proto._unpack_march_pos(info.get("f10")) or proto._unpack_march_pos(info.get("f9"))
        if pos and pos != (0, 0):
            return pos[0], pos[1], info.get("f26") or march.get("serverId")
    return None


class RallyMonitor(LiveDecoder):
    """LiveDecoder that harvests + archives the armies behind every rally.

    A plain LiveDecoder, not a MapIndex: rallies arrive on the
    ``push.alliance.march.*`` push stream rather than as ``world.get.block`` map
    tiles, so none of the map-scan machinery (server election, tile blocks)
    applies. ``map_capture.start_capture`` drives it all the same — the scapy
    sniffer calls ``LiveDecoder.feed_packet`` regardless of the subclass.
    """

    def __init__(self, out_path: str):
        super().__init__()
        self.frames = 0
        self.participant_rows = 0
        self.teams: set = set()          # distinct non-zero teamUuids (стяги)
        self.participants: set = set()   # distinct ownerUids
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        self._out = open(out_path, "a", encoding="utf-8")  # append: accumulate
        self.out_path = out_path

    def emit(self, direction, env):  # LiveDecoder hook
        command = proto.envelope_command(env) or ""
        if not any(tag in command for tag in WANT):
            return
        payload = proto.envelope_payload(env)
        marches = list(_iter_marches(payload))
        if not marches:
            return
        self.frames += 1
        ts = time.time()
        team_here = None
        names = []
        target = None
        for march in marches:
            army_pb = _decode_b64_proto(march.get("armyInfo"))
            team = march.get("teamUuid")
            owner = march.get("ownerUid")
            if team:
                self.teams.add(str(team))
                team_here = str(team)
            if owner is not None:
                self.participants.add(str(owner))
            mt = _march_target(march)
            target = target or mt
            record = {
                "timestamp": ts,
                "teamUuid": str(team) if team is not None else None,
                "ownerUid": owner,
                "ownerName": march.get("ownerName"),
                "power": march.get("power"),
                "curHp": march.get("curHp"),
                "x": mt[0] if mt else None,
                "y": mt[1] if mt else None,
                "targetServer": mt[2] if mt else None,
                "heroes": _heroes(army_pb),
                "formation": _formation(army_pb),
                "armyInfoRaw": army_pb,
            }
            self._out.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.participant_rows += 1
            names.append(march.get("ownerName") or owner)
        self._out.flush()

        who = ", ".join(str(n) for n in names if n) or "-"
        tag = (f"{C_RALLY}team={team_here}{C_RESET}" if team_here
               else f"{C_DIM}solo{C_RESET}")
        where = f"  {coords.fmt(target[0], target[1], target[2])}" if target else ""
        print(f"{_stamp()} {command}  {tag}  "
              f"participants={len(marches)} [{who}]{where}", flush=True)

    def report(self):
        print(f"\n{C_DIM}{'-' * 64}{C_RESET}")
        print(f"{C_OK}{len(self.teams)} стяг(ов), "
              f"{len(self.participants)} участник(ов){C_RESET} "
              f"— {self.participant_rows} строк(и) из {self.frames} событ.")
        if self.teams:
            print("teams (teamUuid):")
            for team in sorted(self.teams):
                print(f"  {team}")
        print(f"\n{self.packets} packet(s) with payload; archive: {self.out_path}")
        if not self.frames:
            print(f"{C_DIM}No rally events decoded — rallies ride "
                  f"push.alliance.march.*, which only arrives when an alliance "
                  f"rally is actually launched or refreshed while capturing."
                  f"{C_RESET}")
        self._out.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # The shared transport flags (--iface, --list-ifaces, --seconds, --all-tcp),
    # same as the map scanners. --dump is a MapIndex-only transcript feature, so
    # it is not offered here — this decoder's emit() would write nothing to it.
    add_capture_arguments(ap, include_dump=False)
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"JSONL archive, appended (default {DEFAULT_OUT})")
    args = ap.parse_args()
    # After parsing, so `--help` is readable from the WSL interpreter rather
    # than refused by the capture-only platform check.
    check_platform()

    # Redirected to a file, stdout is block-buffered, so a run watched with
    # `tail -f` shows nothing for minutes and reads as hung.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    monitor = RallyMonitor(args.out)
    stop, bpf = start_capture(monitor, args)

    print("Rally monitor — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    print(f"{C_DIM}decoding alliance.march.create/refresh armies -> "
          f"{monitor.out_path}\nlistening {window} — a rally must be launched or "
          f"refreshed for anything to arrive{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    # None means run until interrupted, so the deadline test tolerates not
    # having one.
    deadline = time.time() + args.seconds if args.seconds else None
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    monitor.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
