#!/usr/bin/env python3
"""Live rally (стяг) / alliance-march watcher.

Thin wrapper over the existing capture transport in ``live_tshark.py`` and the
protocol decoder in ``live_sniffer.py``: it captures the game endpoint live and
prints only the alliance-march / alert commands, flagging any march that rides a
rally team (``teamUuid != 0``) as it crosses the wire.

    python3 tools/watch_rally.py                 # 10 min on every interface
    python3 tools/watch_rally.py --iface 1 --duration 600
    python3 tools/watch_rally.py --pcap out.pcapng   # also archive raw frames

The live reassembly can drop the odd frame; the raw pcap (``--pcap``) is the
authoritative record — decode it afterwards with::

    python3 tools/lastwar_proto.py out.pcapng --grep 'alliance.march|world.march.new'
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections import Counter

sys.path.insert(0, "tools/lib")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import live_tshark as lt  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET, LiveDecoder  # noqa: E402
import lastwar_proto as proto  # noqa: E402

# Commands the interface's rally UI is built on. Matched as a substring against
# the decoded command name, so "alliance.march" also catches
# push.alliance.march.create/refresh/remove and "world.march.new" the per-member
# broadcast (but NOT push.world.march.world.get.new, kept out on purpose — it is
# the map's monster stream, far noisier and not the alliance feed).
WANT = (
    "alliance.alert.info",
    "lw.alliance.alert",
    "alliance.march",
    "world.march.new",
)

C_RALLY = "\x1b[1;33m"  # bold yellow — a non-zero teamUuid stands out


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def _team_uuids(payload: dict):
    """Every non-zero teamUuid reachable in one decoded alliance/march payload.

    A rally id surfaces in several places depending on the command: the top
    level (world.march.new), the leaderMarch, and each members[] entry. Collect
    them all so a rally is flagged whichever command carried it.
    """
    seen = set()
    if not isinstance(payload, dict):
        return seen
    top = payload.get("teamUuid")
    if top:
        seen.add(top)
    lead = payload.get("leaderMarch")
    if isinstance(lead, dict) and lead.get("teamUuid"):
        seen.add(lead["teamUuid"])
    for member in payload.get("members") or ():
        if isinstance(member, dict) and member.get("teamUuid"):
            seen.add(member["teamUuid"])
    info = payload.get("info")
    if isinstance(info, dict) and info.get("teamUuid"):
        seen.add(info["teamUuid"])
    return seen


class RallyWatcher(LiveDecoder):
    """LiveDecoder that prints only the alliance feed and highlights rallies."""

    def __init__(self, log_path: str | None = None):
        super().__init__()
        self.matched = 0
        self.rally_teams: dict[int, set] = {}  # teamUuid -> distinct ownerUids
        self.by_command: Counter = Counter()
        self._log = open(log_path, "w", encoding="utf-8") if log_path else None

    def emit(self, direction, env):  # LiveDecoder hook
        command = proto.envelope_command(env) or "(keepalive)"
        if not any(tag in command for tag in WANT):
            return
        payload = proto.envelope_payload(env)
        self.matched += 1
        self.by_command[command] += 1

        teams = _team_uuids(payload)
        # Track the distinct owners behind each rally id — ≥2 owners on one
        # teamUuid is the definition of a coordinated rally, not a solo march.
        owner = None
        if isinstance(payload, dict):
            owner = (payload.get("ownerUid")
                     or (payload.get("leaderMarch") or {}).get("ownerUid")
                     or payload.get("attackUid"))
        for team in teams:
            bucket = self.rally_teams.setdefault(team, set())
            if owner is not None:
                bucket.add(str(owner))

        arrow = "<--" if direction == "down" else "-->"
        if teams:
            tag = f"{C_RALLY}RALLY teamUuid={','.join(str(t) for t in teams)}{C_RESET}"
        else:
            tag = f"{C_DIM}solo teamUuid=0{C_RESET}"
        summary = self._summary(command, payload)
        line = f"{_stamp()} {arrow} {command}  {tag}  {summary}"
        print(line, flush=True)
        if self._log:
            self._log.write(json.dumps(
                {"t": time.time(), "dir": direction, "command": command,
                 "teamUuids": [str(t) for t in teams], "payload": payload},
                ensure_ascii=False) + "\n")
            self._log.flush()

    @staticmethod
    def _summary(command: str, payload) -> str:
        if not isinstance(payload, dict):
            return ""
        if command.endswith(("create", "refresh")) and "leaderMarch" in payload:
            lead = payload.get("leaderMarch") or {}
            members = payload.get("members") or []
            return (f"leader={lead.get('ownerName')!r} "
                    f"target={payload.get('targetPointId')} "
                    f"members={len(members)} "
                    f"max={payload.get('assemblyMarchMax')} "
                    f"light={payload.get('teamHasLight')}")
        if command.endswith("remove"):
            return (f"uuid={payload.get('uuid')} teamUuid={payload.get('teamUuid')} "
                    f"isCancel={payload.get('isCancel')}")
        info = payload.get("info")
        if isinstance(info, dict):
            payload = info
        return (f"owner={payload.get('ownerName') or payload.get('ownerUid')} "
                f"uuid={payload.get('uuid')} target={payload.get('target')}")

    def report(self):
        print(f"\n{C_DIM}{'-' * 64}{C_RESET}")
        print(f"{self.matched} alliance/march message(s) matched.")
        if self.by_command:
            print("by command:")
            for name, count in self.by_command.most_common():
                print(f"  {count:<5} {name}")
        rallies = {t: o for t, o in self.rally_teams.items() if o}
        if rallies:
            print("\nrally teams seen (teamUuid -> distinct owners):")
            for team, owners in sorted(rallies.items(), key=lambda kv: -len(kv[1])):
                tag = f"{C_OK}  <-- multi-member RALLY{C_RESET}" if len(owners) > 1 else ""
                print(f"  {team}: {len(owners)} owner(s){tag}")
        else:
            print(f"{C_DIM}no non-zero teamUuid seen — no rally during this window.{C_RESET}")
        if self._log:
            self._log.close()


def main() -> int:
    signal.signal(signal.SIGTERM, lt._terminate)

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iface", help="interface number from `tshark.exe -D`; omitted = all")
    ap.add_argument("--duration", type=int, default=600,
                    help="stop after N seconds (default 600 = 10 min)")
    ap.add_argument("--filter", default="host 3.33.246.23 and port 17935",
                    help="capture BPF (default pins the game endpoint)")
    ap.add_argument("--log", help="append every matched message as JSONL here")
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

    decoder = RallyWatcher(args.log)
    stop = threading.Event()
    print(f"Rally watcher via {os.path.basename(dumpcap)} — "
          f"{len(targets)} iface(s), filter {args.filter!r}, {args.duration}s")
    print(f"{C_DIM}printing alliance.alert / alliance.march / world.march.new; "
          f"{C_RALLY}bold = teamUuid != 0 (rally){C_RESET}\n")

    procs: list = []
    threads = [
        threading.Thread(target=lt.capture,
                         args=(dumpcap, number, label, decoder, args.filter, stop,
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

    decoder.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
