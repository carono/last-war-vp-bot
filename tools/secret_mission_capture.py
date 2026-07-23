#!/usr/bin/env python3
"""Ghost-recon mission index — built exactly like `secret_task_capture.py`.

The in-game *секретная миссия* is the **Secret Command Post** ("Секретный
командный пункт"), its "Операция Призрак" tab (the helmet icon on the world
screen): a co-op weekly activity where an alliance member dispatches a squad
against a target server, teammates join to help, and everyone loots the reward
when the squad returns. It is a different thing from the two lookalikes:

  * a *secret task* (`secret_task_capture.py`, `world.get.block` tile `f2=17`) —
    a hero-dispatch marker you raid off the map;
  * a *shared* task (`alliance.share.mission.*`) — that same tile, pushed to the
    alliance when someone presses "share".

This scanner is `secret_task_capture.py` with one thing swapped: it keeps
ghost-recon missions instead of secret-task tiles, and prints them in the same
shape. Everything else — the scapy/npcap transport, the which-server-is-on-screen
election, the periodic progress line, the JSON checkpoint, the closing summary —
is the shared `map_capture.MapIndex` machinery, subclassed rather than copied.

The one real difference is *where the entity lives on the wire*. A secret task
rides `world.get.block`, so panning the map is what surfaces it. A ghost-recon
mission never rides `world.get.block`; it reaches the client two other ways,
both of which `MapIndex` hands to `on_response()`:

  * **pushed** — `push.ghost.recon.alliance.single`, the live alliance-team
    stream. The server pushes one team the instant it appears (`add`), changes
    (`change`, e.g. a helper joins) or ends (`remove`). This is the real
    detection path: a squad surfaces without the panel being open, which is what
    renders the mission markers you see while walking the map.
  * **polled** — `ghost.recon.get.task.list` / `.get.alliance.task.list`, the
    responses the client sends only when you *open* the panel. Opening "Операция
    Призрак" is what fetches the full list (your own slots and the ally-help
    ones); a mission already on the map puts nothing on the wire by itself.

So keep the run going and play as usual — pushed teams print on their own — and
open the Secret Command Post whenever you want the polled list refreshed. The
server-on-screen election still runs off `world.get.block` as you pan, so the
progress line and the banner name the map you are looking at, exactly as the
secret-task scan does; a mission's own `server` column is its *target* server,
not the one on screen.

    /mnt/c/Python312/python.exe tools/secret_mission_capture.py            stream missions, print them
                                                                           (until Ctrl+C, no file written)
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --seconds 300   stop on a timer instead
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --json out.json also checkpoint to a file
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --json out.json --interval 3
                                                                           flush it every 3s, not 15
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --done      only lootable-now missions
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --joinable  only ally-help ones
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --family 6  only that rarity tier
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --server 991,992
                                                                           only missions vs 991 or 992
    /mnt/c/Python312/python.exe tools/secret_mission_capture.py --list-ifaces   interfaces, then exit

**This must run under the Windows Python, not the WSL one.** WSL2 sits in a
NAT'd VM whose network namespace is not the host's, so an AF_PACKET socket
there sees WSL's own traffic and never a byte of the game's. Requirements on
that interpreter: npcap (ships with Wireshark), plus `pip install scapy
zstandard`. No Administrator prompt is needed when npcap was installed with
"allow non-administrator capture", which is Wireshark's normal setup.

The feature is seasonal (it runs weekly), so a run on the wrong day sees no
missions at all no matter how long it listens. The closing summary tells that
apart from a broken capture.
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
    MapIndex, add_capture_arguments, check_platform,
    dump_records as dump_missions, human_size, start_capture,
)

C_MISSION = "\x1b[1;33m"  # bold yellow, the "worth acting on" colour


def _int_set(text: str) -> set:
    """`--level 3` or `--level 3,5` → a set of ints (argparse-friendly).

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
                f"{part!r} is not a number; expected N or a list like 3,5")
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
    """MapIndex that keeps ghost-recon missions instead of secret-task tiles.

    A ghost-recon mission never rides `world.get.block`, so `on_blocks` stays
    the inherited no-op: its only effect here is that the base class keeps the
    server-on-screen election running as the player pans, exactly as the
    secret-task scan relies on it. The missions arrive on two other streams,
    both delivered to `on_response()`:

      * `push.ghost.recon.alliance.single` — the live alliance-team push
        (`add`/`change` upsert a team, `remove` drops it), the real detection
        path;
      * `ghost.recon.get.task.list` / `.get.alliance.task.list` — the panel
        polls, the full list.

    Missions are keyed by `uuid`, which the wire treats as globally unique
    across servers (a mission names its own `targetServer`), so — unlike a
    secret-task tile, keyed `(server_id, uuid)` because a uuid is only unique
    within a server — there is nothing to disambiguate. There is also no stale
    eviction: a task is evicted when the map stops re-sending it, but a mission
    is not re-sent by panning, so it stays indexed until a `remove` push ends it
    or the run does. A server switch does **not** drop missions either — they
    are alliance-wide, not bound to the map on screen.
    """

    def __init__(self) -> None:
        super().__init__()
        self._missions: dict[int, proto.GhostReconMission] = {}
        # Wall-clock of the last frame that carried each mission, and which
        # stream it came from — both stamped onto the JSON checkpoint.
        self._seen_at: dict[int, float] = {}
        self._source: dict[int, str] = {}
        # Counters for the progress line and the closing summary. `packets` /
        # `blocks_seen` come from the base class; these two are the ghost-recon
        # streams specifically, so a run can say whether the panel was polled
        # and whether any team pushed.
        self.push_seen = 0    # push.ghost.recon.alliance.single frames folded in
        self.poll_seen = 0    # get.*.task.list responses that carried a taskList

    # -- harvest -----------------------------------------------------------

    def on_response(self, command: str | None, payload) -> None:
        """Any non-`world.get.block` server frame. `_index_lock` is held.

        This is where every ghost-recon mission enters the index — the push
        stream and the two panel polls. Everything else the server says is
        ignored.
        """
        now = time.time()
        if command == proto.GHOST_ALLIANCE_PUSH:
            decoded = proto.ghost_recon_alliance_push(payload)
            if decoded is None:
                return
            self.push_seen += 1
            kind, mission = decoded
            if kind == "remove":
                # The team ended (completed / expired / recalled); its slot is
                # free again. Drop it so the closing count reflects what is still
                # live, mirroring the secret-task eviction.
                self._missions.pop(mission.uuid, None)
                self._seen_at.pop(mission.uuid, None)
                self._source.pop(mission.uuid, None)
                return
            self._store(mission, now, "push")
        elif command in proto.GHOST_RECON_COMMANDS:
            missions = list(proto.ghost_recon_missions(command, payload))
            if not missions:
                return
            self.poll_seen += 1
            for mission in missions:
                self._store(mission, now, "poll")

    def _store(self, mission, now: float, source: str) -> None:
        """Upsert one mission. A push carries fewer fields than a poll, so a
        later poll enriches a team first seen on the push; keep the newest of
        each. Callers hold `_index_lock`."""
        self._missions[mission.uuid] = mission
        self._seen_at[mission.uuid] = now
        self._source[mission.uuid] = source

    # -- read --------------------------------------------------------------

    @property
    def missions(self) -> list:
        with self._index_lock:
            return list(self._missions.values())

    @property
    def done_count(self) -> int:
        """Missions in state 3 — completed and lootable right now."""
        with self._index_lock:
            return sum(1 for m in self._missions.values() if m.done)

    def find(self, **criteria) -> list:
        """Filter the indexed missions. Empty slots (state 0 — no target, no
        members) are dropped unless the caller explicitly asks for state 0,
        since there is nothing to act on."""
        wants_empty = bool(criteria.get("state")) and \
            proto.GHOST_STATE_EMPTY in criteria["state"]
        out = proto.filter_ghost_recon(self.missions, **criteria)
        if not wants_empty:
            out = [m for m in out if not m.empty]
        return out

    def records(self) -> list:
        """Missions as serialisable dicts, each stamped with `seen_at` (epoch
        seconds of the last frame that carried it) and `source` (push/poll),
        newest first."""
        with self._index_lock:
            out = []
            for uuid, mission in self._missions.items():
                record = mission.as_dict()
                record["seen_at"] = int(self._seen_at.get(uuid, 0))
                record["source"] = self._source.get(uuid, "poll")
                out.append(record)
        out.sort(key=lambda r: r.get("seen_at", 0), reverse=True)
        return out


def _diagnose(index: MissionIndex, found: int) -> None:
    """Explain a thin result, so "nothing found" is never ambiguous.

    The secret-task scan calls `map_capture.diagnose`, but that one's "no map
    data — keep dragging the map" branch is wrong here: a ghost-recon mission
    does not ride the map, so panning surfaces nothing. This is the same idea
    with the last branch corrected — a quiet stream is told apart from a deaf
    capture, and the fix named for each.
    """
    if index.delivered and not index.packets:
        print(f"{C_ERR}npcap delivered {index.delivered} packet(s) but none "
              f"decoded as TCP-with-payload.{C_RESET} That is scapy failing to "
              f"map the datalink type — check for an 'Unable to guess datalink "
              f"type' warning above.")
    elif not index.delivered:
        print(f"{C_ERR}No packets at all.{C_RESET} Either the game is not "
              f"running, or npcap cannot see this interface — try "
              f"--list-ifaces and pin one with --iface, and run under "
              f"/mnt/c/Python312/python.exe (not the WSL one).")
    elif found:
        return
    else:
        print(f"{C_DIM}Game traffic arrived but carried no ghost-recon mission. "
              f"A mission already on the map puts nothing on the wire by "
              f"itself:\n"
              f"  • open the Secret Command Post → «Операция Призрак» to poll "
              f"the list — that is the only thing that fetches it;\n"
              f"  • push.ghost.recon.alliance.single is edge-triggered "
              f"(add/change/remove of an alliance team), so a squad dispatched "
              f"before you started emits no add.\n"
              f"The feature is also weekly — a run on the wrong day sees "
              f"none.{C_RESET}")


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
    ap.add_argument("--level", type=_int_set, metavar="N[,N...]",
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
    ap.add_argument("--joinable", action="store_true",
                    help="only alliance-visible dispatched missions an ally can "
                         "help; combine with --done for either")
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
    print(f"{C_DIM}listening {window}{sink} — teams push live as you play; "
          f"open «Операция Призрак» to poll the full list{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    # (uuid, state) already announced. A mission walks running -> done, and each
    # step is worth one line; keying on the state (not the uuid alone) prints
    # the DONE moment a raid decision needs while a refresh of an unchanged
    # mission stays silent. Not cleared on a server switch: a mission is
    # alliance-wide, not tied to the map on screen.
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
            # old server's context from the new one's rather than landing amid
            # the mission lines. Informational only here — missions are not
            # dropped on a switch, since they do not belong to the map.
            for old, new in index.drain_server_changes():
                if old is None:
                    print(f"{C_OK}server {new}{C_RESET} — now on this map\n")
                else:
                    print(f"\n{C_OK}server {old} -> {new}{C_RESET} — now "
                          f"viewing server {new}\n")
            if time.time() - last_tick >= args.interval:
                last_tick = time.time()
                left = (f"…{int(deadline - time.time())}s left"
                        if deadline is not None else "…running")
                where = (f"server {index.current_server}"
                         if index.current_server is not None
                         else "server unknown yet")
                print(f"{C_DIM}  {left} — {where}, "
                      f"{index.blocks_seen} map response(s), "
                      f"{index.push_seen} push(es), "
                      f"{index.poll_seen} poll(s), "
                      f"{len(index.missions)} mission(s), "
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
                                done=args.done, joinable=args.joinable):
                # Keyed on what the line actually says — a mission walks
                # running -> done and each state prints once; a refresh of the
                # same state does not re-announce. The steal count is
                # deliberately NOT in the key: a mission can be looted by many,
                # so a rising count is not a new event, unlike a secret task
                # where it means the tile was taken.
                key = (m.uuid, m.state)
                if key in reported:
                    continue
                reported.add(key)
                star = " *" if _starred(m) else "  "
                lvl = f"{m.level:>2}" if m.level is not None else " ?"
                where = (f"({m.x:>4},{m.y:>4})" if m.x is not None
                         else "(   ?,   ?)")
                if m.done:
                    tag = f"  {C_MISSION}LOOTABLE{C_RESET}"
                elif m.running:
                    tag = f"  {C_OK}RUNNING{C_RESET}"
                else:
                    tag = ""
                print(f"{star} lvl {lvl}  {where}  "
                      f"server {m.target_server}  members {m.member_count}  "
                      f"loot {m.steal_count}  family {m.family or '?'}  "
                      f"cfg {m.cfg_id}  owner {_short(m.owner_id)}{tag}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    everything = index.missions
    # reported holds (uuid, state), so one mission can appear under several
    # keys as it walks running -> done; the count is of distinct missions.
    matched = len({uuid for uuid, _state in reported})
    print(f"\n{len(everything)} mission(s) seen, "
          f"{matched} matched the filter, "
          f"{index.done_count} done/lootable")
    print(f"traffic: {index.delivered} delivered / {index.packets} with "
          f"payload, {index.push_seen} push(es), {index.poll_seen} poll(s), "
          f"{index.blocks_seen} map response(s)")

    _diagnose(index, len(everything))

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
