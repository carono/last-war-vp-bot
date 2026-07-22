#!/usr/bin/env python3
"""Live rally (стяг) monitor — harvest the armies out of alliance rallies.

Runs ``dumpcap`` against the game endpoint (port 17935), decodes the
``push.alliance.march.create`` / ``push.alliance.march.refresh`` stream, pulls
every participant's ``armyInfo`` (the base64 protobuf squad — hero ids, tiers,
levels, skills) and writes one JSON line per participant to
``results/rally/monitor.jsonl`` for later analysis.

    python3 tools/rally_monitor.py
    python3 tools/rally_monitor.py --out results/rally/monitor.jsonl
    python3 tools/rally_monitor.py --iface 1 --duration 1800

Each JSONL line::

    {timestamp, teamUuid, ownerUid, ownerName, power, curHp,
     heroes:[{heroId, tier, level, skills:[{skillId, level}]}],
     formation, armyInfoRaw}

On Ctrl+C it prints a short summary: how many distinct rally teams (стяги) and
how many distinct participants were seen.

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
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import live_tshark as lt  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET, LiveDecoder  # noqa: E402
import lastwar_proto as proto  # noqa: E402

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


class RallyMonitor(LiveDecoder):
    """LiveDecoder that harvests + archives the armies behind every rally."""

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
        for march in marches:
            army_pb = _decode_b64_proto(march.get("armyInfo"))
            team = march.get("teamUuid")
            owner = march.get("ownerUid")
            if team:
                self.teams.add(str(team))
                team_here = str(team)
            if owner is not None:
                self.participants.add(str(owner))
            record = {
                "timestamp": ts,
                "teamUuid": str(team) if team is not None else None,
                "ownerUid": owner,
                "ownerName": march.get("ownerName"),
                "power": march.get("power"),
                "curHp": march.get("curHp"),
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
        print(f"{_stamp()} {command}  {tag}  "
              f"participants={len(marches)} [{who}]", flush=True)

    def report(self):
        print(f"\n{C_DIM}{'-' * 64}{C_RESET}")
        print(f"{C_OK}{len(self.teams)} стяг(ов), "
              f"{len(self.participants)} участник(ов){C_RESET} "
              f"— {self.participant_rows} строк(и) из {self.frames} событ.")
        if self.teams:
            print("teams (teamUuid):")
            for team in sorted(self.teams):
                print(f"  {team}")
        print(f"\narchive: {self.out_path}")
        self._out.close()


def main() -> int:
    signal.signal(signal.SIGTERM, lt._terminate)

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"JSONL archive, appended (default {DEFAULT_OUT})")
    ap.add_argument("--iface", help="interface number from `tshark.exe -D`; omitted = all")
    ap.add_argument("--duration", type=int, default=1800,
                    help="stop after N seconds (default 1800 = 30 min)")
    ap.add_argument("--filter", default="host 3.33.246.23 and port 17935",
                    help="capture BPF (default pins the game endpoint)")
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
    targets = [(args.iface, f"iface {args.iface}")] if args.iface else ifaces

    monitor = RallyMonitor(args.out)
    stop = threading.Event()
    print(f"Rally monitor via {os.path.basename(dumpcap)} — "
          f"{len(targets)} iface(s), filter {args.filter!r}, {args.duration}s")
    print(f"{C_DIM}decoding alliance.march.create/refresh armies -> "
          f"{monitor.out_path}  (Ctrl+C to stop){C_RESET}\n")

    procs: list = []
    threads = [
        threading.Thread(target=lt.capture,
                         args=(dumpcap, number, label, monitor, args.filter, stop,
                               False, procs),
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
