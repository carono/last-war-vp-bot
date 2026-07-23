#!/usr/bin/env python3
"""Live monitor for **secret missions** — "Операция Призрак" / ghost recon.

The in-game *секретная миссия* is the **Secret Command Post** ("Секретный
командный пункт"), its "Операция Призрак" tab (the helmet icon on the world
screen). It is a co-op weekly activity: an alliance member dispatches a squad
against a target server, teammates join to help, and everyone loots the reward
when the squad returns. It is a different thing from the two lookalikes:

  * a *secret task* (`secret_task_capture.py`, `world.get.block` tile `f2=17`) —
    a hero-dispatch marker you raid off the map;
  * a *shared* task (`alliance.share.mission.*`) — that same tile, pushed to the
    alliance when someone presses "share".

A ghost-recon mission never rides `world.get.block`. It reaches the client two
ways, and this monitor watches both:

  * **polled** — the responses to two commands the client sends when you open the
    panel, decoded by `lastwar_proto.ghost_recon_missions`:

        ghost.recon.get.task.list            your squads + the ones you can loot
        ghost.recon.get.alliance.task.list   the ally-help list ("Команда союзников")

    Each polled mission has a `state` — 0 an empty slot, 2 a squad still out, 3
    done (lootable / help-rewardable). It is announced when it first matters and
    again when it turns **DONE**, keyed by `(uuid, state)` so a walk
    empty→running→done prints each step once, not every refresh.

  * **pushed** — the live `push.ghost.recon.alliance.single` stream (decoded by
    `lastwar_proto.ghost_recon_alliance_push`), the ghost-recon analogue of
    `push.alliance.share.mission.*`. The server pushes one alliance team the
    instant it appears (`add`), changes (`change`, e.g. a helper joins), or ends
    (`remove`). This is the real **detection** path — a team surfaces without the
    panel being open. Each push carries the target server, the `pointId`
    coordinate, the `cfgId`, the owner and the member list, but no numeric
    `state`; the `type` is the state (occupied on add/change, freed on remove).
    A team line prints on `add` and again each time the squad grows (a `change`
    that adds no member is treated as a duplicate); `remove` prints once.

Both streams are **passive**: nothing is sent, only what crosses the wire is
read. Keep the Secret Command Post panel open to feed the polled list; the push
stream needs no interaction.

It captures the same way `secret_task_capture.py` does — straight through the
npcap driver via scapy (`map_capture.start_capture`), with no `dumpcap.exe` or
`tshark.exe` in the loop. **This must run under the Windows Python, not the WSL
one** (WSL2's NAT'd network namespace never sees the game's packets); invoke it
by path::

    /mnt/c/Python312/python.exe tools/secret_mission_capture.py             stream, print each
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --done       only lootable now
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --joinable   only ally-help ones
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --family 6    only that rarity tier
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --server 991  only missions vs 991
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --json out.json  checkpoint to a file
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --list-ifaces    interfaces, exit

Requirements on that interpreter: npcap (ships with Wireshark), plus
`pip install scapy zstandard`.

`--discover` is a diagnostic for when the protocol shifts (the feature is
seasonal): it flags ANY frame whose command/keys look mission-ish and tallies
every command seen, so a new command family can be caught and wired in. It is
how `ghost.recon.*` was found in the first place. Passive capture only — active
RE is ACE-blocked (see docs/research/socket-duplication.md).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET, LiveDecoder  # noqa: E402
from map_capture import (  # noqa: E402
    add_capture_arguments, check_platform, start_capture,
)
import lastwar_proto as proto  # noqa: E402

C_MISSION = "\x1b[1;33m"  # bold yellow, the "worth acting on" colour

# --discover: catch a secret-mission command family the moment it appears on the
# wire — the reason this needs the feature to be live (a Thursday). Any command
# name or top-level payload key matching one of these is flagged, and every
# command name is tallied regardless, so even if the real word is none of these
# the full command inventory of the session is on record. `ghost`/`recon` are in
# here because that is what the live search turned up; widen as leads accumulate.
DISCOVER_PATTERN = re.compile(
    r"mission|secret|\bspy\b|special|\blw\.|dispatch|espionage|intel|"
    r"agent|ghost|recon", re.IGNORECASE)

# What the game calls each `state`, for the log.
STATE_NAME = {
    proto.GHOST_STATE_EMPTY: "empty",
    proto.GHOST_STATE_RUNNING: "running",
    proto.GHOST_STATE_DONE: "DONE",
}


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
    else holds the target open, which would kill the run. A locked file costs
    one skipped flush; the next one rewrites it whole.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False)
        return True
    except PermissionError:
        return False


class MissionMonitor(LiveDecoder):
    """LiveDecoder that harvests the ghost-recon secret-mission stream.

    Missions are keyed by `uuid`. A mission is announced when it first passes
    the filter and again each time its `state` changes (so empty→running→done
    prints once per step); the `(uuid, state)` guard is what stops a refresh
    every few seconds from re-announcing an unchanged mission.
    """

    def __init__(self, level=None, family=None, state=None, server=None,
                 done=False, joinable=False, json_path=None,
                 discover=False, discover_path=None) -> None:
        super().__init__()
        self.level = level
        self.family = family
        self.state = state
        self.server = server
        self.done = done
        self.joinable = joinable
        self.json_path = json_path
        self.frames = 0                 # ghost-recon frames that held missions
        self.push_events = 0            # push.ghost.recon.alliance.single frames
        self._missions: dict = {}       # uuid -> record dict (polled list)
        self._announced: set = set()    # (uuid, state) already printed
        # The live alliance push stream is a distinct source from the polled
        # list — it is alliance members' teams as they appear on the map, not
        # your own Secret Command Post slots — so it gets its own index rather
        # than clobbering the fuller polled records under a shared uuid.
        self._teams: dict = {}          # uuid -> team record (from the push)
        self._team_announced: set = set()  # (uuid, slot, member_count) printed
        # -- discovery state (only touched when discover=True) --
        self.discover_mode = discover
        self.discover_path = discover_path
        self.all_commands: Counter = Counter()
        self.hits: dict = {}
        self._dfh = None
        if discover and discover_path:
            os.makedirs(os.path.dirname(discover_path) or ".", exist_ok=True)
            self._dfh = open(discover_path, "a", encoding="utf-8")

    # -- decode ------------------------------------------------------------

    def emit(self, direction: str, env) -> None:  # LiveDecoder hook
        command = proto.envelope_command(env)
        if self.discover_mode:
            self._discover(direction, command, env)
        if direction != "down":
            return
        payload = proto.envelope_payload(env)
        now = time.time()
        # The live push stream — a team appears/changes/ends in real time. This
        # is the actual *detection* path, the analogue of push.alliance.share.*.
        if command == proto.GHOST_ALLIANCE_PUSH:
            self._on_alliance_push(payload, now)
            return
        if command not in proto.GHOST_RECON_COMMANDS:
            return
        missions = list(proto.ghost_recon_missions(command, payload))
        if not missions:
            return
        self.frames += 1
        for mission in missions:
            self._record(mission, command, now)

    def _record(self, mission, command: str, now: float) -> None:
        uuid = mission.uuid
        rec = self._missions.get(uuid)
        if rec is None:
            rec = mission.as_dict()
            rec["first_seen"] = int(now)
            self._missions[uuid] = rec
        else:
            rec.update(mission.as_dict())  # refresh state/members/steal/timers
        rec["last_seen"] = int(now)
        rec["last_command"] = command
        rec["source"] = "poll"
        self._announce(mission)

    # -- live alliance push ------------------------------------------------

    def _on_alliance_push(self, payload, now: float) -> None:
        """Fold one push.ghost.recon.alliance.single frame into the team index.

        `add`/`change` upsert the team; `remove` drops it (its slot is free
        again). Each is announced through `_announce_team`, which keys on
        `(uuid, kind, member_count)` so a team growing helper by helper prints
        each step but a duplicate frame does not.
        """
        decoded = proto.ghost_recon_alliance_push(payload)
        if decoded is None:
            return
        kind, mission = decoded
        self.push_events += 1
        if kind == "remove":
            # The remove frame carries only the uuid; recover the coordinate,
            # server and cfg from the record being dropped so the log line and
            # the filters still have something to work with.
            rec = self._teams.pop(mission.uuid, None)
            known = proto.GhostReconMission.from_dict(rec) if rec else mission
            self._announce_team("remove", known)
            return
        rec = self._teams.get(mission.uuid)
        if rec is None:
            rec = mission.as_dict()
            rec["first_seen"] = int(now)
            self._teams[mission.uuid] = rec
        else:
            rec.update(mission.as_dict())
        rec["last_seen"] = int(now)
        rec["last_command"] = proto.GHOST_ALLIANCE_PUSH
        rec["push_kind"] = kind
        rec["source"] = "push"
        self._announce_team(kind, mission)

    def _team_passes(self, mission) -> bool:
        """Filter a pushed team. State-based filters exclude it by design.

        The push carries no `state`/`allianceShow`, so `--state`/`--done`/
        `--joinable` cannot be satisfied by a pushed team — a caller asking for
        those wants the polled list, so the push stream stays quiet then. The
        server/family/level filters still apply.
        """
        if self.state or self.done or self.joinable:
            return False
        return bool(proto.filter_ghost_recon(
            [mission], level=self.level, family=self.family, server=self.server))

    def _announce_team(self, kind: str, mission) -> None:
        # add and change are the same dimension — the team's composition — so
        # they dedupe together on member_count: a `change` that did not grow the
        # squad (a reward-state move we cannot see) is not re-announced, but each
        # new helper is. `remove` is its own slot so it always fires once.
        slot = "remove" if kind == "remove" else "team"
        key = (mission.uuid, slot, mission.member_count)
        if key in self._team_announced or not self._team_passes(mission):
            return
        self._team_announced.add(key)
        # add/change = a squad is out, the target server is occupied by its
        # owner; remove = the team is gone and the slot is free again.
        if kind == "remove":
            tag = f"{C_DIM}freed{C_RESET}"
        else:
            tag = f"{C_MISSION}occupied{C_RESET}"
        where = f"({mission.x},{mission.y})" if mission.x is not None else "(?,?)"
        print(f"{_stamp()} team {kind:>6}  {tag}  "
              f"fam {mission.family or '?'} lvl {mission.level or '?'}  "
              f"server {mission.target_server}  {where}  "
              f"members {mission.member_count}  cfg {mission.cfg_id}  "
              f"owner {_short(mission.owner_id)}", flush=True)
        if self.json_path and not _write_checkpoint(self.records(), self.json_path):
            print(f"{C_DIM}  (checkpoint locked, skipped this flush){C_RESET}",
                  flush=True)

    # -- report ------------------------------------------------------------

    def _passes(self, mission) -> bool:
        """The active filter, applied to one mission."""
        return bool(proto.filter_ghost_recon(
            [mission], level=self.level, family=self.family, state=self.state,
            server=self.server, done=self.done, joinable=self.joinable))

    def _announce(self, mission) -> None:
        # Empty slots are never announced on their own — they carry no target
        # and nothing to act on. A caller wanting to see them can pass --state 0.
        if mission.empty and self.state != proto.GHOST_STATE_EMPTY:
            return
        key = (mission.uuid, mission.state)
        if key in self._announced or not self._passes(mission):
            return
        self._announced.add(key)
        tag = ""
        if mission.done:
            tag = f"  {C_MISSION}DONE — lootable{C_RESET}"
        elif mission.running:
            tag = f"  {C_DIM}running{C_RESET}"
        where = f"({mission.x},{mission.y})" if mission.x is not None else "(?,?)"
        print(f"{_stamp()} {STATE_NAME.get(mission.state, mission.state):>7}  "
              f"fam {mission.family or '?'} lvl {mission.level or '?'}  "
              f"server {mission.target_server}  {where}  "
              f"members {mission.member_count}  loot {mission.steal_count}  "
              f"cfg {mission.cfg_id}  owner {_short(mission.owner_id)}"
              f"{tag}", flush=True)
        if self.json_path and not _write_checkpoint(self.records(), self.json_path):
            print(f"{C_DIM}  (checkpoint locked, skipped this flush){C_RESET}",
                  flush=True)

    def records(self) -> list:
        """Everything seen so far — polled missions and pushed teams — newest
        first. Each record's `source` says which stream it came from."""
        combined = list(self._missions.values()) + list(self._teams.values())
        return sorted(combined,
                      key=lambda r: r.get("last_seen", 0), reverse=True)

    def report(self) -> None:
        if self.discover_mode:
            self._discover_report()
        matched = len({uuid for uuid, _state in self._announced})
        done = sum(1 for r in self._missions.values()
                   if r.get("state") == proto.GHOST_STATE_DONE)
        teams_matched = len({key[0] for key in self._team_announced})
        print(f"\n{C_DIM}{'-' * 64}{C_RESET}")
        print(f"{C_OK}{len(self._missions)} mission(s) seen, {matched} matched, "
              f"{done} done/lootable{C_RESET} — from {self.frames} frame(s)")
        for rec in self._missions.values():
            if not any(k[0] == rec["uuid"] for k in self._announced):
                continue
            print(f"  {STATE_NAME.get(rec.get('state'), rec.get('state')):>7}  "
                  f"fam {rec.get('family')} lvl {rec.get('level')}  "
                  f"server {rec.get('target_server')}  loot {rec.get('steal_count')}"
                  f"  cfg {rec.get('cfg_id')}")
        if self.push_events or self._teams:
            print(f"{C_OK}{len(self._teams)} alliance team(s) live, "
                  f"{teams_matched} matched{C_RESET} — from "
                  f"{self.push_events} push event(s)")
            for rec in sorted(self._teams.values(),
                              key=lambda r: r.get("last_seen", 0), reverse=True):
                where = (f"({rec.get('x')},{rec.get('y')})"
                         if rec.get("x") is not None else "(?,?)")
                print(f"  team  fam {rec.get('family')} lvl {rec.get('level')}  "
                      f"server {rec.get('target_server')}  {where}  "
                      f"members {rec.get('member_count')}  cfg {rec.get('cfg_id')}"
                      f"  owner {_short(rec.get('owner_id'))}")
        if not self._missions and not self._teams:
            print(f"{C_DIM}No ghost-recon missions arrived. Open the Secret "
                  f"Command Post → «Операция Призрак» in game so the client "
                  f"fetches them — and the feature only runs on its weekly day."
                  f"{C_RESET}")
        if self.json_path:
            records = self.records()
            if _write_checkpoint(records, self.json_path):
                print(f"{C_OK}wrote {len(records)} record(s) to "
                      f"{self.json_path}{C_RESET}")
            else:
                print(f"{C_ERR}could not write {self.json_path} — held by "
                      f"another process.{C_RESET}")

    # -- discovery ---------------------------------------------------------

    def _discover(self, direction: str, command, env) -> None:
        """Flag any frame that might be a still-unknown secret-mission stream.

        Tallies every command name (so the session's full inventory is on
        record), prints each command the first time it is seen, and highlights +
        archives (to `discover_path`) any whose name or top-level payload keys
        match DISCOVER_PATTERN. On the day this catches a new command, wire its
        name into GHOST_RECON_COMMANDS / ghost_recon_missions() and move on.
        """
        name = command or "<unnamed>"
        first_time = name not in self.all_commands
        self.all_commands[name] += 1
        payload = proto.envelope_payload(env)
        keys = list(payload.keys()) if isinstance(payload, dict) else []
        hay = name + " " + " ".join(str(k) for k in keys)
        matched = bool(DISCOVER_PATTERN.search(hay))
        if first_time and not matched:
            print(f"{_stamp()} {C_DIM}new  {direction:>4}  {name}{C_RESET}",
                  flush=True)
        if not matched:
            return
        if self._dfh is not None:
            try:
                self._dfh.write(json.dumps(
                    {"t": round(time.time(), 3), "dir": direction,
                     "command": command, "payload": payload},
                    ensure_ascii=False, default=repr) + "\n")
                self._dfh.flush()
            except Exception:
                pass
        if name in self.hits:
            return
        self.hits[name] = {"dir": direction, "keys": keys, "payload": payload}
        print(f"{_stamp()} {C_MISSION}HIT{C_RESET} {direction:>4}  {name}  "
              f"keys={keys}", flush=True)

    def _discover_report(self) -> None:
        print(f"\n{C_DIM}{'=' * 64}{C_RESET}")
        total = sum(self.all_commands.values())
        print(f"{C_OK}discover: {len(self.all_commands)} distinct command(s), "
              f"{total} frame(s); {len(self.hits)} matched "
              f"{DISCOVER_PATTERN.pattern!r}{C_RESET}")
        if self.hits:
            print("candidate secret-mission commands:")
            for name, info in sorted(self.hits.items()):
                print(f"  {C_MISSION}{name}{C_RESET}  ({info['dir']})  "
                      f"keys={info['keys']}")
            print(f"{C_DIM}full sample frames appended to "
                  f"{self.discover_path}{C_RESET}")
        else:
            print(f"{C_DIM}nothing matched. Open the secret-mission UI in game "
                  f"and keep the capture running — these appear only when that "
                  f"screen is touched (and only on the day they run).{C_RESET}")
        print("full command inventory (name: count):")
        for name, count in self.all_commands.most_common():
            mark = f"{C_MISSION} <-- match{C_RESET}" if name in self.hits else ""
            print(f"  {count:>5}  {name}{mark}")


def _int_set(text: str):
    """`--level 3` or `--level 3,5` → a set of ints (argparse-friendly)."""
    out = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"{part!r} is not a number; expected N or a list like 3,5")
    if not out:
        raise argparse.ArgumentTypeError("no value given")
    return out


def _str_set(text: str):
    """`--family 6` or `--family 4,6` → a set of strings."""
    out = {p.strip() for p in text.split(",") if p.strip()}
    if not out:
        raise argparse.ArgumentTypeError("no value given")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # The shared scapy transport flags (--iface / --list-ifaces / --seconds /
    # --all-tcp), same as secret_task_capture.py. --dump is a MapIndex-only
    # feature, so it is not offered here.
    add_capture_arguments(ap, include_dump=False)
    ap.add_argument("--json", default=None,
                    help="checkpoint every mission seen to this file, rewritten "
                         "on each announcement (default: no file written)")
    ap.add_argument("--level", type=_int_set, metavar="N[,N...]",
                    help="only missions of this level (from cfgId; a list "
                         "matches any)")
    ap.add_argument("--family", type=_str_set, metavar="F[,F...]",
                    help="only missions of this cfgId family / rarity tier "
                         "(4/5/6; a list matches any)")
    ap.add_argument("--state", type=_int_set, metavar="S[,S...]",
                    help="only missions in this state (0 empty, 2 running, "
                         "3 done)")
    ap.add_argument("--server", type=_int_set, metavar="N[,N...]",
                    help="only missions targeting this server")
    ap.add_argument("--done", action="store_true",
                    help="only completed missions (state 3 — lootable now)")
    ap.add_argument("--joinable", action="store_true",
                    help="only alliance-visible dispatched missions an ally can "
                         "help; combine with --done for either")
    ap.add_argument("--discover", action="store_true",
                    help="discovery mode: flag ANY frame whose command name or "
                         "payload keys look mission-ish, tally every command, "
                         "and append matched frames to --discover-out. Use when "
                         "the protocol shifts (the feature is seasonal).")
    ap.add_argument("--discover-out",
                    default=os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "results", "task1004", "discover.jsonl"),
                    help="where --discover appends matched frames (JSONL)")
    args = ap.parse_args()
    # After parsing, so `--help` is readable from the WSL interpreter rather
    # than refused by the capture-platform check.
    check_platform()

    # Redirected to a file, stdout is block-buffered, so a run watched with
    # `tail -f` shows nothing for minutes and reads as hung.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    monitor = MissionMonitor(
        level=args.level, family=args.family, state=args.state,
        server=args.server, done=args.done, joinable=args.joinable,
        json_path=args.json, discover=args.discover,
        discover_path=args.discover_out)
    # Same capture call secret_task_capture.py uses — scapy/npcap, no dumpcap.
    # Exits the process on --list-ifaces or a missing scapy.
    stop, bpf = start_capture(monitor, args)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    sink = f" -> {args.json}" if args.json else ""
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    print(f"Secret-mission monitor — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}   "
          f"listening {window}")
    if args.discover:
        print(f"{C_MISSION}DISCOVER mode{C_RESET}{C_DIM}: flagging any "
              f"mission/secret/ghost/recon frame, tallying every command -> "
              f"{args.discover_out}. Open the Secret Command Post in game."
              f"{C_RESET}\n")
    else:
        print(f"{C_DIM}decoding ghost.recon.get.task.list / "
              f".get.alliance.task.list + push.ghost.recon.alliance.single"
              f"{sink} (Ctrl+C to stop) — open «Операция Призрак» in game to "
              f"feed the polled list; teams push live on their own{C_RESET}\n")

    # None means run until interrupted, so the deadline test tolerates no timer.
    deadline = time.time() + args.seconds if args.seconds else None
    last_tick = time.time()
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(0.3)
            if args.discover and time.time() - last_tick >= 15:
                last_tick = time.time()
                left = (f"…{int(deadline - time.time())}s left"
                        if deadline is not None else "…running")
                print(f"{C_DIM}  {left} — {monitor.packets} game "
                      f"frame(s), {len(monitor.all_commands)} distinct "
                      f"command(s), {len(monitor.hits)} match(es){C_RESET}",
                      flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    monitor.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
