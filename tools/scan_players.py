#!/usr/bin/env python3
"""Sweep player bases off the map, passively, and write them to JSON.

Same transport as `secret_task_capture.py` — scapy talks to the npcap driver
directly, so no `dumpcap.exe` and no `tshark.exe` are spawned. Protocol logic
is imported from lastwar_proto.py and the capture plus the server election
from map_capture.py; nothing here is reimplemented.

What it keeps is the `f2 = 6` tile: a player's base, carrying their public
profile inline (protocol.md §7). Name, HQ level and alliance come straight off
the wire, so a sweep needs neither OCR nor a single profile screen opened.

    python tools/scan_players.py                          stream bases, print them
                                                          (until Ctrl+C, no file written)
    python tools/scan_players.py --seconds 300            stop on a timer instead
    python tools/scan_players.py --json players.json      also checkpoint to a file
    python tools/scan_players.py --json players.json --interval 3
                                                          flush it every 3s, not 15
    python tools/scan_players.py --alliance VP            only that alliance's bases
    python tools/scan_players.py --level 30               only HQ 30
    python tools/scan_players.py --level 30,31            HQ 30 or 31
    python tools/scan_players.py --list-ifaces            interfaces, then exit

**This must run under the Windows Python, not the WSL one.** WSL2 sits in a
NAT'd VM whose network namespace is not the host's, so an AF_PACKET socket
there sees WSL's own traffic and never a byte of the game's. From WSL, invoke
the Windows interpreter by path:

    /mnt/c/Python312/python.exe tools/scan_players.py --seconds 300

Requirements on that interpreter: npcap (ships with Wireshark), plus
`pip install scapy zstandard`.

The game only sends `world.get.block` while the map is moving, so a run that
reports zero map responses means nobody was panning — not that the capture is
broken. The counters tell those two apart.

Two ways this differs from the task capture, both because a base is not a
timer:

  * a base is kept for the whole run, and a server change does not drop what
    was collected before it. A task's dispatch clock keeps ticking once you
    pan away, so a stale task lies; a base's name and level do not go stale
    that fast, and a sweep across several servers is the point of the tool.
    `seen_at` on every record says when the map last confirmed it;
  * `--alliance` and `--level` narrow what is *collected*, not just what is
    printed, so the file and the console always agree.

Each run rewrites `--json` from scratch — it is this run's result, not a
database that grows across runs. Point successive sweeps at different files
if you want to keep both.
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
    MapIndex, add_capture_arguments, check_platform, diagnose, dump_records,
    level_set, start_capture,
)


class PlayerIndex(MapIndex):
    """MapIndex that keeps player bases.

    Bases are keyed by `(server_id, uid)`. The client does not debounce, so
    panning re-sends regions it already asked about and a repeat has to
    refresh a record rather than append a duplicate — the refreshed tile is
    the newer truth about the player's level and alliance. The server id is in
    the key because a uid identifies a player, and the same player's base can
    only be on one server at a time, but two servers can be swept in one run
    and a base that moved should not silently overwrite where it used to be.

    Nothing is evicted. A base does not go stale the way a dispatch timer
    does, and a sweep that dropped a server's bases the moment the player
    jumped away would collect nothing across a multi-server run.
    """

    def __init__(self, level=None, alliance=None) -> None:
        super().__init__()
        self.level = level
        self.alliance = alliance
        self._bases: dict[tuple, proto.PlayerBase] = {}
        # Wall-clock of the last time the map re-sent each base, so a reader
        # can tell a base confirmed a minute ago from one seen once an hour in.
        self._seen_at: dict[tuple, float] = {}
        # Bases the filter threw away, so "0 collected" can be told apart from
        # "3000 seen, none of them yours".
        self.rejected = 0
        # The printable line last announced per base — see take_new().
        self._reported: dict[tuple, tuple] = {}

    def on_blocks(self, payload, blocks, now: float) -> None:
        found = list(proto.player_bases(payload))
        kept = proto.filter_players(found, level=self.level,
                                    alliance=self.alliance)
        self.rejected += len(found) - len(kept)
        for base in kept:
            key = (base.server_id, base.uid)
            self._bases[key] = base
            self._seen_at[key] = now

    @property
    def bases(self) -> list:
        with self._index_lock:
            return list(self._bases.values())

    @property
    def current_bases(self) -> list:
        """Bases on the server the player is currently looking at.

        Before the first unambiguous map response there is no current server
        yet, and everything seen so far is the best answer available.
        """
        server = self.current_server
        if server is None:
            return self.bases
        return [b for b in self.bases if b.server_id == server]

    def records(self) -> list:
        """Every base as a serialisable dict, each stamped with `seen_at`.

        `seen_at` is epoch seconds on the capture host — when the map last
        re-sent the tile, not when the file was written.
        """
        with self._index_lock:
            out = []
            for key, base in self._bases.items():
                record = base.as_dict()
                record["seen_at"] = int(self._seen_at.get(key, 0))
                out.append(record)
        # Newest confirmation first within a server, so a reader skimming the
        # file sees what the sweep just passed over.
        out.sort(key=lambda r: (r["server_id"] or 0, -r["seen_at"]))
        return out

    def take_new(self) -> list:
        """Bases whose printable line changed since the last call.

        Keyed on what the line actually says rather than on the uid alone: a
        base that levels up or switches alliance mid-sweep is news, and keying
        by uid would print the old line once and suppress the update forever.
        """
        out = []
        with self._index_lock:
            for key, base in self._bases.items():
                line = (base.level, base.alliance_abbr, base.x, base.y)
                if self._reported.get(key) == line:
                    continue
                self._reported[key] = line
                out.append(base)
        out.sort(key=lambda b: (-(b.level or 0), b.uid))
        return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_capture_arguments(ap)
    ap.add_argument("--json", default=None,
                    help="checkpoint every base collected to this file, "
                         "rewritten on every tick (default: no file is written)")
    ap.add_argument("--interval", type=int, default=15,
                    help="seconds between processing ticks — each one prints "
                         "the progress line and rewrites --json if given "
                         "(default 15; lower it for tests)")
    ap.add_argument("--level", type=level_set, metavar="N[,N...]",
                    help="only bases at this HQ level; a comma-separated list "
                         "matches any of them (--level 30,31)")
    ap.add_argument("--alliance", metavar="ABBR",
                    help="only bases of this alliance, by its abbreviation "
                         "(case-insensitive)")
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

    index = PlayerIndex(level=args.level, alliance=args.alliance)
    stop, bpf = start_capture(index, args)

    print("Last War player sweep — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    narrowing = []
    if args.alliance:
        narrowing.append(f"alliance {args.alliance}")
    if args.level:
        narrowing.append("level " + ",".join(str(n) for n in sorted(args.level)))
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    sink = f" -> {args.json} every {args.interval}s" if args.json else ""
    scope = f" — collecting only {' and '.join(narrowing)}" if narrowing else ""
    print(f"{C_DIM}listening {window}{sink}{scope} — pan the map, or nothing "
          f"will arrive{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    # None means run until interrupted, so every deadline test has to tolerate
    # not having one.
    deadline = time.time() + args.seconds if args.seconds else None
    last_tick = time.time()
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(1.0)
            # Drained before anything is printed, so the banner separates one
            # server's lines from the next instead of landing amid them.
            for old, new in index.drain_server_changes():
                if old is None:
                    print(f"{C_OK}server {new}{C_RESET} — reading this map\n")
                else:
                    print(f"\n{C_OK}server {old} -> {new}{C_RESET} — bases "
                          f"collected on {old} are kept\n")
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
                      f"{len(index.bases)} base(s) collected "
                      f"({len(index.current_bases)} here){C_RESET}")
                if args.json and not dump_records(index.records(), args.json):
                    print(f"{C_DIM}  (checkpoint locked, skipped this "
                          f"flush){C_RESET}")
            for base in index.take_new():
                tag = f"[{base.alliance_abbr}]" if base.alliance_abbr else ""
                print(f"  HQ {base.level if base.level is not None else '??':>2}"
                      f"  ({base.x:>4},{base.y:>4})  server {base.server_id}"
                      f"  {tag:>8} {base.name or '?'}"
                      f"  uid {base.uid}  {base.country or ''}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    everything = index.bases
    servers = sorted({b.server_id for b in everything if b.server_id})
    print(f"\n{len(everything)} base(s) collected across "
          f"{len(servers)} server(s) {servers or ''}"
          + (f", {index.rejected} tile(s) dropped by the filter"
             if index.rejected else ""))
    print(f"traffic: {index.delivered} delivered / {index.packets} with payload, "
          f"{index.blocks_seen} map response(s), {index.tiles_seen} tile(s), "
          f"kinds {dict(index.tile_kinds)}")

    diagnose(index, len(everything),
             "Map data arrived but held no player bases you asked for (no "
             "f2=6 tiles passed the filter) — pan over inhabited ground, or "
             "widen --alliance/--level.")

    if args.json:
        records = index.records()
        if dump_records(records, args.json):
            print(f"{C_OK}wrote {len(records)} base(s) to {args.json}{C_RESET}")
        else:
            print(f"{C_ERR}could not write {args.json} — the file is held by "
                  f"another process.{C_RESET} Close whatever has it open and "
                  f"re-run, or point --json somewhere else.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
