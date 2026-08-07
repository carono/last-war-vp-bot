#!/usr/bin/env python3
r"""Event-driven auto-loot for *shared* secret tasks — rob the instant the push lands.

Why this exists
---------------
The panel's «Автолут ★» watcher (see ``panel/__main__.py`` and
``tools/steal_secret_task.py``) is a **poll**: it re-reads the client's task list and
a capture checkpoint every couple of seconds. That is fast enough for a tile that has
been sitting on the map, but it loses the race for the case the feature is really about
— an alliance member pressing "share" on a freshly-raidable secret task. The share is
broadcast to the whole alliance as ``push.alliance.share.mission.add`` (plain-TCP game
leg, passively decodable — see ``docs/research/protocol.md`` "Shared secret missions"
and the ``project_shared_secret_missions`` memory), and a human watching the game sees
it and marches on it in the same second. A 2 s poll that has to notice it *after the
fact* always comes second.

This tool closes that gap by being genuinely **event-driven**: it passively sniffs the
game stream, and the moment a ``push.alliance.share.mission.add`` frame crosses the wire
it decodes it, applies the same star / level rule the panel auto-loot uses, and fires
``hero.dispatch.steal`` through the warm Lua daemon straight away. Reaction is a wire
frame plus one daemon round-trip — well under a second — so the bot reaches the tile
before a person reading the same broadcast could.

The push carries exactly what a robbery needs, so there is no coordinate-to-uuid
resolve step in the path: ``missionUuid`` is the dispatch task's uuid and
``missionCurrentServerId`` is the server the tile sits on (``targetServer``). The
per-tile conditions the server owns (my own past loots, the protect window, three loot
slots, sector range) stay its call and come back as an errorCode, the same as every
other route into ``hero.dispatch.steal``; a refused robbery leaves ``todayStealNum``
unchanged and costs nothing.

It is a *complement* to the poll, not a replacement: the poll still covers enemy tiles
the map sweep panned over and tasks already present before this listener started. The
two are safe to run together — the daily budget is enforced server-side and read live
before every send, and a redundant attempt at a tile the other path already took is
simply refused.

Usage (run under the Windows Python so it can both capture and reach the daemon)
--------------------------------------------------------------------------------
    C:\Python312\python.exe tools\secret_share_autoloot.py
    C:\Python312\python.exe tools\secret_share_autoloot.py --star-max --level-min 1 --level-max 7
    C:\Python312\python.exe tools\secret_share_autoloot.py --seconds 1800
    C:\Python312\python.exe tools\secret_share_autoloot.py --dry-run     # decode + decide, never send
    C:\Python312\python.exe tools\secret_share_autoloot.py --list-ifaces

**Windows Python only.** WSL2 sits in a NAT'd VM whose network namespace is not the
host's, so a capture there sees WSL's own traffic and never a byte of the game's (see
``map_capture.check_platform``). Requirements: npcap (ships with Wireshark), plus
``pip install scapy zstandard``.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# Absolute, not "tools/lib": the shared modules resolve the same no matter what cwd the
# launcher (panel, daemon, shell) started us in.
sys.path.insert(0, os.path.join(_HERE, "lib"))
sys.path.insert(0, _HERE)

import coords  # noqa: E402  (canonical #server X:x Y:y token — clickable in the panel log)
import lastwar_proto as proto  # noqa: E402
import lua_actions  # noqa: E402
import share_marks  # noqa: E402  (the «already shared» mark this listener also writes)
import lua_client  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET, LiveDecoder  # noqa: E402
from map_capture import add_capture_arguments, check_platform, start_capture  # noqa: E402

MARKER = "ACT"
C_HIT = "\x1b[1;33m"  # bold yellow — the "worth acting on" colour, like the monitors

# The one command that means "an ally just made a raidable secret task available".
# Matched exactly (not as a substring) — the `.list` login snapshot is a backlog, not a
# live event, and re-robbing yesterday's backlog on every reconnect is not what this is
# for. See lastwar_proto.SHARE_MISSION_COMMANDS.
SHARE_ADD = "push.alliance.share.mission.add"


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def mission_passes(mission, star_max: bool, level_min, level_max) -> bool:
    """Does this one shared mission match the auto-loot rule?

    The same rule the panel poll applies (``steal_secret_task._select_targets``), reduced
    to a single mission because a push arrives one at a time:

      * ``star_max`` keeps only starred missions (family 6000, the ones worth sharing);
      * ``level_min`` / ``level_max`` are the panel's «уровень от / до» — a hard gate;
      * with ``star_max`` **and** a ``level_max`` set, that cap *is* the level robbed
        («от 1 до 7» robs 7s and leaves a 6), so a starred mission below the cap is held
        — the day's five robberies are the scarce thing, not the targets.

    A mission whose cfgId did not split into a level is only ever taken when the star
    rule is off: an unknown level cannot be gated, and guessing would be how a budget
    gets spent on the wrong tile.
    """
    if star_max and not mission.starred:
        return False
    if mission.level is None:
        return not star_max
    if level_min is not None and mission.level < level_min:
        return False
    if level_max is not None and mission.level > level_max:
        return False
    if star_max and level_max is not None and mission.level != level_max:
        return False
    return True


class ShareAutoloot(LiveDecoder):
    """LiveDecoder that robs a shared secret task the instant its push is decoded.

    A plain LiveDecoder, not a MapIndex: the share rides ``push.alliance.share.mission.*``
    rather than ``world.get.block`` map tiles, so none of the map-scan machinery applies
    — ``map_capture.start_capture`` drives ``emit`` for every frame regardless.
    """

    def __init__(self, ev, star_max: bool, level_min, level_max,
                 limit: int, dry_run: bool, shared_json: str | None = None):
        super().__init__()
        self._ev = ev
        # Where «this task has already been shared» is recorded (#1245), or None to
        # record nothing. Written for EVERY share this listener decodes, before the
        # auto-loot rule is consulted: a mission outside the rule is still a mission
        # the alliance has already been told about, and the mark is what stops the
        # person forwarding it a second time.
        self._shared_json = shared_json
        self.marked = 0
        self._star_max = star_max
        self._level_min = level_min
        self._level_max = level_max
        self._limit = limit
        self._dry_run = dry_run
        # The own server, resolved lazily on the first push that matters and then kept:
        # the listener is started with the panel (often before the game is logged in), so
        # asking at start-up would answer "unknown" for the whole run.
        self._own = 0
        # (uuid, server) already acted on this run: a push can repeat, and a refused
        # tile stays shared, so without this the same doomed target is retried on every
        # duplicate frame. A fresh run forgets them again.
        self._seen: set = set()
        self.hits = 0            # missions that matched the rule
        self.robbed = 0          # robberies actually sent
        self._budget_spent = False

    # -- the live hook -----------------------------------------------------

    def emit(self, direction, env):  # LiveDecoder hook, called per frame
        command = proto.envelope_command(env) or ""
        if command != SHARE_ADD:
            return
        payload = proto.envelope_payload(env)
        for mission in proto.share_missions(command, payload):
            self._consider(mission)

    def _consider(self, mission) -> None:
        uuid, server = mission.uuid, mission.server_id
        if not uuid or not server:
            # No target to name — a malformed or partial push. Say so at DIM so a
            # genuinely empty frame is visible in a trace without being alarming.
            print(f"{_stamp()} {C_DIM}share push with no uuid/server — skipped"
                  f"{C_RESET}", flush=True)
            return
        # The mark first, and unconditionally: whether this mission is worth one of the
        # day's five robberies is a separate question from whether the alliance has
        # already been shown it (#1245).
        if self._shared_json and share_marks.mark(
                self._shared_json, uuid, share_marks.VIA_GAME,
                str(mission.share_uid or "")):
            self.marked += 1
        star = "*" if mission.starred else " "
        lvl = mission.level if mission.level is not None else "?"
        where = coords.fmt(0, 0, server).split()[0]  # "#<server>" prefix for the log
        label = f"{star} lvl {lvl}  {where}  cfg {mission.cfg_id}  uuid {uuid}"

        if not mission_passes(mission, self._star_max, self._level_min, self._level_max):
            print(f"{_stamp()} {C_DIM}share: {label} — outside the rule, left alone"
                  f"{C_RESET}", flush=True)
            return
        # UNCONDITIONAL (#1188). This listener fires on the share push itself, before
        # any list has a row to filter, so it is the fastest way there is to rob at
        # home — and the game fines the player for that. There is no flag left that
        # could withhold the check.
        if not self._allowed_server(server):
            return
        if (uuid, server) in self._seen:
            return
        self._seen.add((uuid, server))
        self.hits += 1
        print(f"{_stamp()} {C_HIT}SHARE MATCH{C_RESET}  {label}", flush=True)
        self._rob(uuid, server, label)

    # -- «не грабить на своём сервере» -------------------------------------

    def _allowed_server(self, server: int) -> bool:
        """Whether a tile on ``server`` may be robbed under the own-server prohibition.

        The own server is asked for at the first push that gets this far, not at start-up:
        the panel spawns this listener as it boots, and a client not logged in yet would
        answer "unknown" once and be believed for the rest of the run.

        An own server that still cannot be read refuses the robbery. The prohibition is
        the point of the flag — letting it lapse because a read failed is exactly the
        silent widening the level gate was bitten by (#1099).
        """
        if not self._own:
            import steal_secret_task              # tools/, the robbery policy lives there
            self._own = steal_secret_task.own_server(self._ev)
        if not self._own:
            print(f"{_stamp()} {C_DIM}own server unreadable — not robbing "
                  f"#{server} while «skip own server» is on{C_RESET}", flush=True)
            return False
        if server == self._own:
            print(f"{_stamp()} {C_DIM}share on the own server #{server} — left alone"
                  f"{C_RESET}", flush=True)
            return False
        return True

    # -- the robbery -------------------------------------------------------

    def _rob(self, uuid: int, server: int, label: str) -> None:
        if self._dry_run:
            print(f"{_stamp()} {C_DIM}dry-run: would rob {label}{C_RESET}", flush=True)
            return
        if self.robbed >= self._limit:
            print(f"{_stamp()} {C_DIM}session cap ({self._limit}) reached — not sending"
                  f"{C_RESET}", flush=True)
            return
        try:
            left = self._steals_left()
        except Exception as exc:                      # noqa: BLE001
            print(f"{_stamp()} {C_ERR}daemon unreachable ({exc}) — cannot rob {label}"
                  f"{C_RESET}", flush=True)
            self._seen.discard((uuid, server))        # let a later push retry it
            return
        if left <= 0:
            if not self._budget_spent:
                self._budget_spent = True
                print(f"{_stamp()} {C_DIM}the day's robberies are spent — listening on, "
                      f"will rob again after the reset{C_RESET}", flush=True)
            return
        self._budget_spent = False
        self._ev.run(lua_actions.secret_task_steal(uuid, server), MARKER, 1.0)
        self.robbed += 1
        now_left = self._steals_left()
        print(f"{_stamp()} {C_OK}robbed{C_RESET} {label}  "
              f"(budget {left} -> {now_left})", flush=True)
        self._dismiss_reward()

    def _steals_left(self) -> int:
        chunk = ('CS.UnityEngine.Debug.LogError("ACT left="..tostring(%s))'
                 % lua_actions.secret_task_steals_left())
        for ln in self._ev.run(chunk, MARKER, 0.8):
            if "left=" in ln:
                try:
                    return int(float(ln.split("left=", 1)[1].split()[0]))
                except (ValueError, IndexError):
                    return 0
        return 0

    def _dismiss_reward(self) -> None:
        """Close the reward window a successful robbery raises, so it does not sit on
        top of the map — the same press ``steal_secret_task.py`` uses after a run."""
        try:
            import game_buttons
            button = game_buttons.get("dismiss_steal_reward")
            if button is not None:
                self._ev.run(button.lua, MARKER, button.wait)
        except Exception:                             # noqa: BLE001 — cleanup is best-effort
            pass

    def report(self) -> None:
        print(f"\n{C_DIM}{'-' * 56}{C_RESET}")
        print(f"{C_OK}{self.hits} shared mission(s) matched, "
              f"{self.robbed} robbery/robberies sent{C_RESET} "
              f"from {self.packets} packet(s) with payload")
        # Counted apart from the hits on purpose: a mission outside the rule is marked
        # as shared and never robbed, so the two numbers answer different questions.
        if self._shared_json:
            print(f"{self.marked} share(s) marked in {self._shared_json}")
        if not self.hits:
            print(f"{C_DIM}No shared secret task matched — the push only arrives when an "
                  f"alliance member presses share on a raidable one while capturing."
                  f"{C_RESET}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # Shared transport flags (--iface, --list-ifaces, --seconds, --all-tcp). No --dump:
    # this decoder writes no transcript.
    add_capture_arguments(ap, include_dump=False)
    ap.add_argument("--star-max", action="store_true",
                    help="starred tasks only, and — with --level-max — only at that top "
                         "level (the panel's auto-loot rule)")
    ap.add_argument("--level-min", type=int, metavar="N",
                    help="never rob below level N (the panel's «уровень от»)")
    ap.add_argument("--level-max", type=int, metavar="N",
                    help="never rob above level N («уровень до»); with --star-max this IS "
                         "the level robbed, nothing lower")
    ap.add_argument("--limit", type=int, default=5,
                    help="stop sending after this many robberies this run (default 5, the "
                         "daily cap; the server enforces the real budget regardless)")
    ap.add_argument("--skip-own-server", action="store_true",
                    help="accepted and ignored: the player's own server is never robbed, "
                         "with or without it (#1188). Kept so older call sites keep "
                         "working")
    ap.add_argument("--dry-run", action="store_true",
                    help="decode and decide, but never send a robbery (for verifying the "
                         "wire path without spending the budget)")
    ap.add_argument("--shared-json", default=None, metavar="PATH",
                    help="append a mark to this file for every shared secret task seen, "
                         "whoever shared it and whether or not the rule takes it "
                         "(default: shares are not recorded)")
    args = ap.parse_args()
    # After parsing, so --help / --list-ifaces read from the WSL interpreter rather than
    # being refused by the capture-only platform check.
    check_platform()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass

    # The daemon evaluator is resolved up front so the first matching push does not pay
    # the hijack cost inline. A dry run still resolves it, so a "the daemon is down"
    # problem surfaces before a real share arrives rather than during it.
    ev = lua_client.get_evaluator()

    monitor = ShareAutoloot(ev, star_max=args.star_max, level_min=args.level_min,
                            level_max=args.level_max, limit=args.limit,
                            dry_run=args.dry_run,
                            shared_json=args.shared_json)
    stop, bpf = start_capture(monitor, args)

    print("Shared-secret-task auto-loot — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    rule = "starred" if args.star_max else "any"
    span = ("%s..%s" % (args.level_min if args.level_min is not None else "",
                        args.level_max if args.level_max is not None else "")) or "any"
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    mode = " (dry-run — nothing is sent)" if args.dry_run else ""
    own = ", own server left alone"          # always (#1188)
    print(f"{C_DIM}rule: {rule}, level {span}{own}; robbing on {SHARE_ADD}{mode}\n"
          f"listening {window} — an ally must share a secret task for anything to "
          f"arrive{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    deadline = time.time() + args.seconds if args.seconds else None
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    monitor.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
