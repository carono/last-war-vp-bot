#!/usr/bin/env python3
"""Ghost-recon mission scan — a `world.get.block` tile sweep, like secret tasks.

The in-game *секретная миссия* is the **Secret Command Post** ("Секретный
командный пункт"), its "Операция Призрак" tab (the helmet icon on the world
screen): a co-op weekly activity where an alliance member dispatches a squad
against a target server, teammates join to help, and everyone loots the reward
when the squad returns.

An earlier version of this scanner listened on two off-map streams — the
`push.ghost.recon.alliance.single` push and the `ghost.recon.get.*.task.list`
panel polls — on the belief that a ghost-recon squad never rides
`world.get.block`. Task #1010 (`results/task1010/tiles.jsonl`) disproved that: a
dispatched squad **is** drawn on the world map as a tile of type `f2 = 29`,
alongside secret tasks (`f2 = 17`), bases (`6`) and mines (`7`), handed to
anyone who pans over it. So this is now the exact twin of `secret_task_capture.py`
with one thing swapped — it keeps `f2 = 29` ghost-recon tiles instead of `f2 = 17`
secret-task tiles — and everything else is the shared `map_capture.MapIndex`
machinery, subclassed rather than copied: the scapy/npcap transport, the
which-server-is-on-screen election, the periodic progress line, the JSON
checkpoint and the closing summary.

Because a mission is a map tile, **panning the map is what surfaces it** — the
same as a secret task. The tile packs the mission in protobuf field numbers under
`f14` (owner, target server, cfgId rarity tier, state, uuid, coordinates); see
`proto.ghost_recon_tiles` for the field map. The observed live state is `f9 = 3`
(completed / lootable). A tile's own server (`owner_server`) is where the squad
is drawn — the map on screen — while its `target_server` is the different id it
attacks.

    /mnt/c/Python312/python.exe tools/secret_mission_capture.py            stream missions, print them
                                                                           (until Ctrl+C, no file written)
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --seconds 300   stop on a timer instead
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --json out.json also checkpoint to a file
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --json out.json --interval 3
                                                                           flush it every 3s, not 15
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --done      only lootable-now missions
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --family 6  only that rarity tier
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --server 991,992
                                                                           only missions vs 991 or 992
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --dump traffic.jsonl  record every
                                                                           decoded frame as JSONL too
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --list-ifaces   interfaces, then exit

**This must run under the Windows Python, not the WSL one.** WSL2 sits in a
NAT'd VM whose network namespace is not the host's, so an AF_PACKET socket
there sees WSL's own traffic and never a byte of the game's. Requirements on
that interpreter: npcap (ships with Wireshark), plus `pip install scapy
zstandard`. No Administrator prompt is needed when npcap was installed with
"allow non-administrator capture", which is Wireshark's normal setup.

The game only sends `world.get.block` while the map is moving, so a run that
reports zero map responses means nobody was panning — not that the capture is
broken. The feature is also seasonal (it runs weekly), so a run on the wrong
day sees no ghost-recon tiles at all no matter how long it listens. The closing
summary and `diagnose()` tell those cases apart from a deaf capture.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET  # noqa: E402
from map_capture import (  # noqa: E402
    MapIndex, add_capture_arguments, check_platform, diagnose,
    dump_records as dump_missions, human_size, level_set, start_capture,
)

C_MISSION = "\x1b[1;33m"  # bold yellow, the "worth acting on" colour

# Freshness window for the mission index and its checkpoint. A ghost-recon tile
# is re-sent every time the map is panned over it, exactly like a secret task,
# so the same "not re-sent within the window means untrustworthy" rule applies;
# reuse the secret-task constant so the two scans agree on "current".
STALE_AFTER_SECONDS = proto.TASK_FRESH_SECONDS

# There is deliberately no default sink. --json is opt-in so an unattended or
# exploratory run cannot quietly overwrite a checkpoint someone else is reading.


def _int_set(text: str) -> set:
    """`--state 3` or `--state 2,3` → a set of ints (argparse-friendly).

    Raises argparse's own error type so a typo prints the usage line and the
    offending value rather than a traceback — silently dropping an unparsable
    entry would narrow the run to something the user did not ask for.
    """
    out = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"{part!r} is not a number; expected N or a list like 2,3")
    if not out:
        raise argparse.ArgumentTypeError("no value given")
    return out


def _str_set(text: str) -> set:
    """`--family 6` or `--family 4,6` → a set of strings."""
    out = {p.strip() for p in text.split(",") if p.strip()}
    if not out:
        raise argparse.ArgumentTypeError("no value given")
    return out


def _short(value, keep: int = 8) -> str:
    """Trim a long id (owner uid, alliance hash) for a one-line log."""
    text = str(value) if value is not None else "-"
    return text if len(text) <= keep + 1 else text[:keep] + "…"


def _starred(mission) -> bool:
    """The top rarity tier — family "6", the ghost-recon analogue of the
    secret-task star (cfgId family 6000). Marked with a `*` in the log, same as
    a starred task."""
    return mission.family == "6"


class MissionIndex(MapIndex):
    """MapIndex that keeps ghost-recon tiles (`f2 = 29`) instead of secret tasks.

    This is the secret-task index with the tile type swapped. Missions are keyed
    by `(owner_server, uuid)`, the direct analogue of a secret task's
    `(server_id, uuid)`: `owner_server` is the tile's own server (`f102`/`f103`,
    the map the squad is drawn on) and a uuid is only unique within it, so a tile
    from the server just left and one from the server just joined must not
    overwrite each other. (`target_server` is a different thing — the server the
    mission attacks — and is what `--server` filters on.)

    Panning the undebounced client re-sends regions it already asked about, so a
    repeat refreshes a record rather than appending a duplicate, and a tile the
    map stops re-sending is evicted once it falls past `stale_after` — its state
    is no longer trustworthy. A server switch drops everything indexed for the
    map nobody is looking at any more, exactly as the secret-task scan does.
    """

    def __init__(self, stale_after: float = STALE_AFTER_SECONDS) -> None:
        super().__init__()
        self.stale_after = stale_after
        self._missions: dict[tuple, proto.GhostReconMission] = {}
        # Wall-clock of the last time the map re-sent each tile, so stale ones
        # can be evicted rather than served as if still live.
        self._seen_at: dict[tuple, float] = {}

    # -- harvest -----------------------------------------------------------

    def on_blocks(self, payload, blocks, now: float) -> None:
        """Every ghost-recon tile in one decoded map response. `_index_lock`
        is held and `current_server` is already updated for this response."""
        for mission in proto.ghost_recon_tiles(payload):
            key = (mission.owner_server, mission.uuid)
            self._missions[key] = mission
            self._seen_at[key] = now

    def on_server_left(self, server: int) -> None:
        """Drop everything indexed for the map nobody is looking at any more.

        A mission tile carries no live timer we can recompute, but its state was
        read off a map the player has left; keeping it would go on announcing a
        LOOTABLE squad on a server nobody is viewing. Keyed off the *current*
        server rather than the one just left, so a stray third server's tiles go
        with them.
        """
        self._evict(lambda key: key[0] != self.current_server)

    def _evict(self, doomed) -> None:
        """Drop every indexed mission whose key `doomed(key)` accepts.

        Callers hold `_index_lock`.
        """
        for key in [k for k in self._seen_at if doomed(k)]:
            self._missions.pop(key, None)
            self._seen_at.pop(key, None)

    # -- read --------------------------------------------------------------

    @property
    def missions(self) -> list:
        cutoff = time.time() - self.stale_after
        with self._index_lock:
            self._evict(lambda key: self._seen_at[key] < cutoff)
            return list(self._missions.values())

    @property
    def current_missions(self) -> list:
        """Fresh missions on the server the player is currently looking at.

        Before the first unambiguous map response there is no current server
        yet, and everything seen so far is the best answer available.
        """
        server = self.current_server
        if server is None:
            return self.missions
        return [m for m in self.missions if m.owner_server == server]

    @property
    def done_count(self) -> int:
        """Missions in state 3 — completed and lootable right now — on the
        server on screen."""
        return sum(1 for m in self.current_missions if m.done)

    def find(self, **criteria) -> list:
        """Filter the *current* server's missions — never the one just left.

        Empty slots (state 0 — no squad dispatched) are dropped unless the
        caller explicitly asks for state 0, since there is nothing to act on.
        """
        wants_empty = bool(criteria.get("state")) and \
            proto.GHOST_STATE_EMPTY in criteria["state"]
        out = proto.filter_ghost_recon(self.current_missions, **criteria)
        if not wants_empty:
            out = [m for m in out if not m.empty]
        return out

    def records(self) -> list:
        """Fresh missions as serialisable dicts, each stamped with `seen_at`
        (epoch seconds of the last frame that carried the tile).

        Eviction runs here too, so the file never carries a tile already past
        the window.
        """
        cutoff = time.time() - self.stale_after
        with self._index_lock:
            self._evict(lambda key: self._seen_at[key] < cutoff)
            out = []
            for key, mission in self._missions.items():
                record = mission.as_dict()
                record["seen_at"] = int(self._seen_at.get(key, 0))
                out.append(record)
        out.sort(key=lambda r: r.get("seen_at", 0), reverse=True)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_capture_arguments(ap)
    ap.add_argument("--json", default=None,
                    help="checkpoint every mission seen to this file, rewritten "
                         "on every tick (default: no file is written)")
    ap.add_argument("--interval", type=int, default=15,
                    help="seconds between processing ticks — each one prints "
                         "the progress line and rewrites --json if given "
                         "(default 15; lower it for tests)")
    ap.add_argument("--level", type=level_set, metavar="N[,N...]",
                    help="only missions of this level (from cfgId); a "
                         "comma-separated list matches any (--level 3,5)")
    ap.add_argument("--family", type=_str_set, metavar="F[,F...]",
                    help="only missions of this cfgId family / rarity tier "
                         "(4/5/6; a list matches any)")
    ap.add_argument("--state", type=_int_set, metavar="S[,S...]",
                    help="only missions in this state (0 empty, 2 running, "
                         "3 done); a list matches any")
    ap.add_argument("--server", type=_int_set, metavar="N[,N...]",
                    help="only missions targeting this server; a list matches "
                         "any")
    ap.add_argument("--done", action="store_true",
                    help="only completed missions (state 3 — lootable now)")
    args = ap.parse_args()
    # After parsing, so `--help` is readable from the WSL interpreter
    # rather than refused by a check about capturing packets.
    check_platform()

    # Redirected to a file, stdout is block-buffered, so a run watched with
    # `tail -f` shows nothing for minutes and reads as hung.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    index = MissionIndex()
    stop, bpf = start_capture(index, args)

    print("Last War direct capture — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    sink = f" -> {args.json} every {args.interval}s" if args.json else ""
    print(f"{C_DIM}listening {window}{sink} — pan the map over «Операция "
          f"Призрак» squads, or nothing will arrive{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    # (owner_server, uuid, state) already announced. A mission walks running ->
    # done, and each step is worth one line; keying on the state (not the uuid
    # alone) prints the DONE moment a raid decision needs while a refresh of an
    # unchanged mission stays silent. Cleared on a server switch below, since the
    # new server's tiles are a fresh set of lines and a return trip must
    # re-announce what it finds.
    reported: set = set()
    # None means run until interrupted, so every deadline test has to tolerate
    # not having one.
    deadline = time.time() + args.seconds if args.seconds else None
    # One timer for the whole periodic tick — the progress line and the
    # checkpoint flush both fire on the period the user set, never on a
    # hardcoded one.
    last_tick = time.time()
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(1.0)
            # Drained before anything is printed, so the banner separates the
            # old server's lines from the new one's instead of landing amid
            # them.
            for old, new in index.drain_server_changes():
                if old is None:
                    print(f"{C_OK}server {new}{C_RESET} — reading this map\n")
                else:
                    print(f"\n{C_OK}server {old} -> {new}{C_RESET} — dropped "
                          f"everything indexed for {old}; only server {new} "
                          f"is reported from here\n")
                    # The new server's missions are a fresh set of lines, and a
                    # return trip to `old` has to re-announce what it finds
                    # rather than stay silent on keys reported before the move.
                    reported.clear()
            if time.time() - last_tick >= args.interval:
                last_tick = time.time()
                left = (f"…{int(deadline - time.time())}s left"
                        if deadline is not None else "…running")
                where = (f"server {index.current_server}"
                         if index.current_server is not None
                         else "server unknown yet")
                print(f"{C_DIM}  {left} — {where}, "
                      f"{index.blocks_seen} map response(s), "
                      f"{index.tiles_seen} tile(s), "
                      f"{len(index.current_missions)} mission(s), "
                      f"{index.done_count} done{C_RESET}")
                if args.json and not dump_missions(index.records(), args.json):
                    print(f"{C_DIM}  (checkpoint locked, skipped this "
                          f"flush){C_RESET}")
                if index.transcript is not None:
                    # Flushed here rather than per frame, so a reader tailing
                    # the transcript is one tick behind at worst and the
                    # sniffer thread is never blocked on the disk.
                    index.transcript.flush()
                    print(f"{C_DIM}  transcript: "
                          f"{index.transcript.frames} frame(s), "
                          f"{human_size(index.transcript.size())}{C_RESET}")
            for m in index.find(level=args.level, family=args.family,
                                state=args.state, server=args.server,
                                done=args.done):
                # Keyed on what the line actually says — a mission walks
                # running -> done and each state prints once; a refresh of the
                # same state does not re-announce. The server id is in the key
                # because a uuid only identifies a tile within its server.
                key = (m.owner_server, m.uuid, m.state)
                if key in reported:
                    continue
                reported.add(key)
                star = " *" if _starred(m) else "  "
                lvl = f"{m.level:>2}" if m.level is not None else " ?"
                where = (f"({m.x:>4},{m.y:>4})" if m.x is not None
                         else "(   ?,   ?)")
                # Only the actionable state gets a label, exactly as the
                # secret-task scan tags LOOTABLE and nothing else: a dispatched
                # squad still out (state 2) is listed, but unlabelled.
                tag = f"  {C_MISSION}LOOTABLE{C_RESET}" if m.done else ""
                print(f"{star} lvl {lvl}  {where}  "
                      f"server {m.owner_server} -> {m.target_server}  "
                      f"members {m.member_count}  family {m.family or '?'}  "
                      f"cfg {m.cfg_id}  owner {_short(m.owner_id)}{tag}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    everything = index.missions
    # reported holds (owner_server, uuid, state), so one mission can appear under
    # several keys as it walks running -> done; the count is of distinct
    # missions.
    matched = len({(server, uuid) for server, uuid, _state in reported})
    where = (f" on server {index.current_server}"
             if index.current_server is not None else "")
    print(f"\n{len(everything)} mission(s) seen{where}, "
          f"{matched} matched the filter, "
          f"{index.done_count} done/lootable")
    print(f"traffic: {index.delivered} delivered / {index.packets} with "
          f"payload, {index.blocks_seen} map response(s), "
          f"{index.tiles_seen} tile(s), kinds {dict(index.tile_kinds)}")

    diagnose(index, len(everything),
             "Map data arrived but held no ghost-recon missions (no f2=29 "
             "tiles) — pan over «Операция Призрак» squads, and note the feature "
             "is weekly, so a run on the wrong day sees none.")

    if args.json:
        records = index.records()
        if dump_missions(records, args.json):
            print(f"{C_OK}wrote {len(records)} mission(s) to {args.json}{C_RESET}")
        else:
            print(f"{C_ERR}could not write {args.json} — the file is held by "
                  f"another process.{C_RESET} Close whatever has it open and "
                  f"re-run, or point --json somewhere else.")

    if index.transcript is not None:
        index.transcript.close()
        lost = (f", {index.transcript.failed} frame(s) could not be serialised"
                if index.transcript.failed else "")
        print(f"{C_OK}wrote {index.transcript.frames} frame(s) "
              f"({human_size(index.transcript.size())}) to "
              f"{index.transcript.path}{C_RESET}{lost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
