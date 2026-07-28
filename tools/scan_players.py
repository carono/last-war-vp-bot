#!/usr/bin/env python3
"""Sweep player bases off the map, passively, and write them to JSON.

Same transport as `secret_task_capture.py` — scapy talks to the npcap driver
directly, so no `dumpcap.exe` and no `tshark.exe` are spawned. Protocol logic
is imported from lastwar_proto.py and the capture plus the server election
from map_capture.py; nothing here is reimplemented.

What it keeps is the `f2 = 6` tile: a player's base, carrying their public
profile inline (protocol.md §7). Name, HQ level and alliance come straight off
the wire, so a sweep needs neither OCR nor a single profile screen opened.

**Clicking a base while the sweep runs adds its combat stats.** The click
makes the client ask `get.user.info.multi` for that uid, and the reply carries
what no tile does — `power`, `armyPower`, `armyKill`, `svipLevel`. Those are
folded into the record the sweep already has, or filed as a new one if the
click landed on a player whose tile was never passed over (then `x`/`y` are
null and the console prints "click" where coordinates would go). Order does
not matter: clicking before or after the tile arrives converges on the same
record. Batched replies — an alliance roster the client fetches at login —
are taken just as seriously; the numbers are equally real.

    python tools/scan_players.py                          stream bases, print them
                                                          (until Ctrl+C, no file written)
    python tools/scan_players.py --seconds 300            stop on a timer instead
    python tools/scan_players.py --json players.json      also checkpoint to a file
    python tools/scan_players.py --json players.json --interval 3
                                                          flush it every 3s, not 15
    python tools/scan_players.py --alliance VP            only that alliance's bases
    python tools/scan_players.py --level 30               only HQ 30
    python tools/scan_players.py --level 30,31            HQ 30 or 31
    python tools/scan_players.py --name kot               only names containing "kot"
    python tools/scan_players.py --uid 123456             only that player
    python tools/scan_players.py --uid 123456,789012      either of them
    python tools/scan_players.py --dump results/traffic.jsonl
                                                          also record every frame
    python tools/scan_players.py --list-ifaces            interfaces, then exit

**Your own notes on players are merged in too, as `remark`.** The client keeps
them server-side and fetches the whole list with `user.remark.list` — but only
**once, at login**. So start the scan *before* logging in, or the list never
crosses the wire and no record gets a note. They are keyed by uid alone (a
note follows the player, not their base), and most of them are for players a
given run never sees: of the 869 notes in the saved capture, 276 landed on a
collected record.

Fields per record: uid, name, level (HQ), alliance_id, alliance_abbr, country,
x, y, server_id, uuid, seen_at — plus power, army_power, army_kill, svip_level
and profile_seen_at on any record a click answered for, and remark where you
wrote a note.

`--dump` is the other half of a clicking session: it writes **every** decoded
frame, both directions, as JSONL, so a run spent clicking around can be mined
afterwards for whatever else the client asks and the server answers. The
sweep's own JSON only keeps what this tool understands; the transcript keeps
everything it does not.

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
  * `--alliance`, `--level`, `--name` and `--uid` narrow what is *collected*,
    not just what is printed, so the file and the console always agree. They
    apply to clicked profiles too, so a click on someone outside the filter is
    dropped rather than smuggled into a narrowed sweep. Several of them
    together is an "and": `--name kot --level 30` keeps only HQ-30 bases whose
    name contains "kot".

`--name` is a substring and ignores case — names carry spacing and decoration
nobody retypes exactly. `--uid` is the other extreme: an exact id, which is
what you want once a run has already told you which player to follow. Neither
lets a base arrive that the map never sent: a `--uid` sweep still needs someone
to pan over that player's ground (or to click them) before anything is
collected.

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

sys.path.insert(0, "tools/lib")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET  # noqa: E402
from map_capture import (  # noqa: E402
    MapIndex, add_capture_arguments, check_platform, diagnose, dump_records,
    human_size, level_set, start_capture,
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

    def __init__(self, level=None, alliance=None, name=None, uid=None) -> None:
        super().__init__()
        self.level = level
        self.alliance = alliance
        self.name = name
        self.uid = uid
        self._bases: dict[tuple, proto.PlayerBase] = {}
        # Wall-clock of the last time the map re-sent each base, so a reader
        # can tell a base confirmed a minute ago from one seen once an hour in.
        self._seen_at: dict[tuple, float] = {}
        # ...and when a profile reply last answered for it, which is a
        # different question: a base re-seen every second may still carry
        # power numbers from one click ten minutes ago.
        self._profile_at: dict[tuple, float] = {}
        # Bases the filter threw away, so "0 collected" can be told apart from
        # "3000 seen, none of them yours".
        self.rejected = 0
        # The printable line last announced per base — see take_new().
        self._reported: dict[tuple, tuple] = {}
        # How many profile replies were folded in, split by what they did. A
        # sweep where the user clicked twenty bases and nothing was enriched
        # is a bug; one where nothing was clicked is not.
        self.profiles_merged = 0
        self.profiles_added = 0
        # Notes keyed by uid alone — a note follows the player, not their base,
        # so it has no server id and applies on whichever server they turn up.
        # Held rather than merged once, because the client sends the whole list
        # at login, before any map data: a merge that only touched records
        # already collected would apply almost none of them.
        self._remarks: dict[str, str] = {}
        self.remarks_known = 0

    def _keep(self, players: list) -> list:
        """The subset of `players` this run was asked to collect.

        One place for every narrowing flag, so a tile and a clicked profile can
        never disagree about who belongs in the sweep.
        """
        return proto.filter_players(players, level=self.level,
                                    alliance=self.alliance, name=self.name,
                                    uid=self.uid)

    def on_blocks(self, payload, blocks, now: float) -> None:
        found = list(proto.player_bases(payload))
        kept = self._keep(found)
        self.rejected += len(found) - len(kept)
        for base in kept:
            key = (base.server_id, base.uid)
            existing = self._bases.get(key)
            # A profile fetched earlier holds numbers this tile cannot, so the
            # tile must not overwrite it — merge the other way round instead.
            merged = (base.merged_with(self._as_profile(existing))
                      if existing is not None and existing.has_profile
                      else base)
            self._bases[key] = self._stamp_remark(merged)
            self._seen_at[key] = now

    def on_response(self, command, payload) -> None:
        """Fold in the two replies that say more than the map does."""
        if command == proto.REMARK_COMMAND:
            self._take_remarks(payload)
        elif command == proto.PROFILE_COMMAND:
            self._take_profiles(payload)

    def _take_remarks(self, payload) -> None:
        """Take the notes you wrote on other players, from `user.remark.list`.

        The client asks for these once at login, a page at a time, so they
        normally land before a single map response. They are kept keyed by uid
        and stamped onto records both now and as those records arrive.

        Callers hold `_index_lock`.
        """
        cleared = set()
        for target_uid, remark, _updated in proto.player_remarks(payload):
            if remark is None:
                # An entry with no text means the note was deleted. Never seen
                # from the real server — all 869 notes in the capture had text,
                # and a deleted one is more likely to be absent from the list
                # than present and empty — but if it does arrive it has to
                # clear the record rather than leave stale text on it.
                self._remarks.pop(target_uid, None)
                cleared.add(target_uid)
            else:
                self._remarks[target_uid] = remark
        self.remarks_known = len(self._remarks)
        # Whatever is already collected gets stamped immediately; the rest is
        # handled as records arrive.
        for base in self._bases.values():
            if base.uid in cleared:
                base.remark = None
            self._stamp_remark(base)

    def _stamp_remark(self, base):
        """Write your note on that player onto `base`, if you wrote one.

        Mutates and returns the same object, so it can be dropped into an
        assignment. A record with no note keeps `remark` as None rather than
        an empty string — "no note" and "an empty note" would otherwise be
        indistinguishable in the JSON.

        Callers hold `_index_lock`.
        """
        remark = self._remarks.get(base.uid)
        if remark is not None:
            base.remark = remark
        return base

    @property
    def remarked(self) -> int:
        """How many collected records carry one of your notes."""
        with self._index_lock:
            return sum(1 for b in self._bases.values() if b.remark)

    def _take_profiles(self, payload) -> None:
        """Fold in a `get.user.info.multi` reply — clicking a base sends one.

        The reply carries power, army power, lifetime kills and SVIP level,
        which no map tile does. Batched replies (an alliance roster fetched at
        login) are the same shape and are taken just as seriously; the numbers
        are equally real, only the reason the client asked differs.

        Callers hold `_index_lock`.
        """
        now = time.time()
        for profile in proto.player_profiles(payload):
            key = self._key_for(profile)
            existing = self._bases.get(key)
            if existing is not None:
                self._bases[key] = self._stamp_remark(
                    existing.merged_with(profile))
                self.profiles_merged += 1
            else:
                # A base the sweep never passed over — clicked from a search,
                # a chat link, or a roster. Kept without coordinates rather
                # than dropped: the numbers are the point of the lookup.
                base = profile.as_base()
                if not self._keep([base]):
                    self.rejected += 1
                    continue
                self._bases[key] = self._stamp_remark(base)
                self.profiles_added += 1
            self._seen_at[key] = now
            self._profile_at[key] = now

    def _key_for(self, profile) -> tuple:
        """Where this profile belongs in the index.

        `(server_id, uid)` normally, and the two sources agree on the server:
        across the saved captures every one of the 59 uids seen as both a tile
        and a profile matched. The fallback is for the case that agreement
        cannot cover — a player who teleported between the tile sighting and
        the click — where keying strictly would file the same player twice.
        A uid is globally unique, so a single existing record for it is
        unambiguous; two would not be, and then the strict key is right.

        Callers hold `_index_lock`.
        """
        key = (profile.server_id, profile.uid)
        if key in self._bases:
            return key
        elsewhere = [k for k in self._bases if k[1] == profile.uid]
        return elsewhere[0] if len(elsewhere) == 1 else key

    @staticmethod
    def _as_profile(base) -> proto.PlayerProfile:
        """The profile half of an existing record, for re-merging onto it."""
        return proto.PlayerProfile(
            uid=base.uid, server_id=base.server_id, name=None, level=None,
            alliance_id=None, alliance_abbr=None, country=None,
            power=base.power, army_power=base.army_power,
            army_kill=base.army_kill, svip_level=base.svip_level,
        )

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

        `seen_at` is epoch seconds on the capture host — when the map or a
        profile reply last confirmed the record, not when the file was
        written. `profile_seen_at` is there only on records a profile reply
        answered for, so a reader can tell power numbers from one click ten
        minutes ago apart from ones fetched a second ago.
        """
        with self._index_lock:
            out = []
            for key, base in self._bases.items():
                record = base.as_dict()
                record["seen_at"] = int(self._seen_at.get(key, 0))
                if key in self._profile_at:
                    record["profile_seen_at"] = int(self._profile_at[key])
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
                # `power` is in the line because a click that answers for a
                # base already printed is exactly the news worth reprinting.
                line = (base.level, base.alliance_abbr, base.x, base.y,
                        base.power, base.remark)
                if self._reported.get(key) == line:
                    continue
                self._reported[key] = line
                out.append(base)
        out.sort(key=lambda b: (-(b.level or 0), b.uid))
        return out


def uid_set(text: str) -> set:
    """Parse `--uid` — one uid or a comma-separated list of them.

    Kept as text rather than numbers: a uid is a str everywhere else here, it
    is an identifier and not a quantity, and parsing it as an int would refuse
    a perfectly good id the day the server issues one that is not all digits.
    Refuses an empty selection the way `level_set` does — an argument that
    narrowed to nothing would quietly collect nothing all run.
    """
    uids = {part.strip() for part in text.split(",") if part.strip()}
    if not uids:
        raise argparse.ArgumentTypeError("no uid given")
    return uids


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
    ap.add_argument("--name", metavar="TEXT",
                    help="only players whose name contains this text "
                         "(case-insensitive substring, not a whole name)")
    ap.add_argument("--uid", type=uid_set, metavar="UID[,UID...]",
                    help="only these players, by exact uid; a comma-separated "
                         "list matches any of them (--uid 123456,789012)")
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

    index = PlayerIndex(level=args.level, alliance=args.alliance,
                        name=args.name, uid=args.uid)
    stop, bpf = start_capture(index, args)

    print("Last War player sweep — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    narrowing = []
    if args.alliance:
        narrowing.append(f"alliance {args.alliance}")
    if args.level:
        narrowing.append("level " + ",".join(str(n) for n in sorted(args.level)))
    if args.name:
        narrowing.append(f"names containing {args.name!r}")
    if args.uid:
        narrowing.append("uid " + ",".join(sorted(args.uid)))
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
                      f"({len(index.current_bases)} here), "
                      f"{index.profiles_merged + index.profiles_added} "
                      f"profile(s) looked up, "
                      f"{index.remarked} noted{C_RESET}")
                if args.json and not dump_records(index.records(), args.json):
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
            for base in index.take_new():
                tag = f"[{base.alliance_abbr}]" if base.alliance_abbr else ""
                # A base known only from a click has no coordinates, so the
                # column reads "click" rather than a pair of empty brackets.
                where = (f"({base.x:>4},{base.y:>4})" if base.x is not None
                         else "     click  ")
                # Only shown once a profile has answered — a blank column is
                # "not looked up", which a zero would misrepresent.
                stats = (f"  {C_OK}power {base.power:,}{C_RESET}"
                         f"  army {base.army_power:,}"
                         f"  kills {base.army_kill:,}"
                         f"  svip {base.svip_level}"
                         if base.has_profile else "")
                note = f"  {C_OK}<{base.remark}>{C_RESET}" if base.remark else ""
                print(f"  HQ {base.level if base.level is not None else '??':>2}"
                      f"  {where}  server {base.server_id}"
                      f"  {tag:>8} {base.name or '?'}"
                      f"  uid {base.uid}  {base.country or ''}{note}{stats}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    everything = index.bases
    servers = sorted({b.server_id for b in everything if b.server_id})
    profiled = sum(1 for b in everything if b.has_profile)
    print(f"\n{len(everything)} base(s) collected across "
          f"{len(servers)} server(s) {servers or ''}"
          + (f", {index.rejected} tile(s) dropped by the filter"
             if index.rejected else ""))
    print(f"{profiled} of them carry profile stats "
          f"({index.profiles_merged} folded into a base already collected, "
          f"{index.profiles_added} known only from a lookup)")
    if index.remarks_known:
        print(f"{index.remarked} of them carry one of your notes "
              f"({index.remarks_known} note(s) in the account's list, most on "
              f"players this run never saw)")
    else:
        print(f"{C_DIM}No notes were received: the client sends "
              f"user.remark.list once at login, so start the scan before "
              f"logging in to have them.{C_RESET}")
    print(f"traffic: {index.delivered} delivered / {index.packets} with payload, "
          f"{index.blocks_seen} map response(s), {index.tiles_seen} tile(s), "
          f"kinds {dict(index.tile_kinds)}")

    diagnose(index, len(everything),
             "Map data arrived but held no player bases you asked for (no "
             "f2=6 tiles passed the filter) — pan over inhabited ground, or "
             "widen --alliance/--level/--name/--uid.")
    if everything and not profiled:
        print(f"{C_DIM}No profile stats: nothing was clicked during the run, "
              f"or the clicks landed on something other than a base. Power, "
              f"army power and kills only arrive in a get.user.info.multi "
              f"reply, which the client sends when you open a player."
              f"{C_RESET}")

    if args.json:
        records = index.records()
        if dump_records(records, args.json):
            print(f"{C_OK}wrote {len(records)} base(s) to {args.json}{C_RESET}")
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
