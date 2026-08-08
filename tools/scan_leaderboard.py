#!/usr/bin/env python3
"""Collect the game's ranking screens, passively, while you open them.

Same transport as `scan_players.py` — scapy talks to the npcap driver
directly, so no `dumpcap.exe` and no `tshark.exe` are spawned. Protocol logic
is imported from lastwar_proto.py and the capture from map_capture.py; nothing
here reimplements either.

Unlike the map sweep this tool cannot make anything happen. A ranking crosses
the wire **only when you open it in the client**: the whole board arrives in
one reply, so the workflow is to start the scan and then walk the rankings you
want — alliance, champion duel, event boards — one screen at a time. A run
where nothing was opened reports nothing, and says so rather than looking
broken.

    python tools/scan_leaderboard.py                      stream rows, print them
                                                          (until Ctrl+C, no file written)
    python tools/scan_leaderboard.py --seconds 300        stop on a timer instead
    python tools/scan_leaderboard.py --json ranks.json    also checkpoint to a file
    python tools/scan_leaderboard.py --json ranks.json --interval 3
                                                          flush it every 3s, not 15
    python tools/scan_leaderboard.py --board al.rank      only that board
    python tools/scan_leaderboard.py --known-only         skip boards found by shape
    python tools/scan_leaderboard.py --sqlite hist.db --quiet
                                                          collect silently: counts on a
                                                          marker line, no player rows
                                                          (what the panel's trigger runs)
    python tools/scan_leaderboard.py --dump results/traffic.jsonl
                                                          also record every frame
    python tools/scan_leaderboard.py --list-ifaces        interfaces, then exit

**Boards nobody has decoded are collected too.** Two are described in
lastwar_proto.py because two are what the saved captures hold; every other
ranking screen is recognised by shape — a list of at least three players each
carrying a uid, a name and a score or rank column. Those rows are marked
`discovered` in the JSON, so a reader can tell a column the protocol file
vouches for from one a heuristic picked. Replayed against both saved captures
the shape test found the two real boards and nothing else, but a board it has
never seen is still a guess; `--known-only` is there when you want only the
sure thing.

**`position` is often null, and that is the honest answer.** The field called
`rank` is the placement on some boards and something else entirely on others —
in `al.rank` it is the alliance role (R1..R5), and that board arrives in no
sorted order at all, because the client sorts it locally by whichever column
you picked. So a position is reported only where it can be had honestly, and
`position_source` says how it was arrived at:

    "field"   the board numbered the row itself — and the numbers were
              checked to really be 1..N in order before being believed
              (champion duel: 1..32)
    "order"   the board stated no number, but the server sorted the list, so
              the index is the placement (alliance ranking: 44 entries,
              strictly descending by fightpower)
    null      neither, so `position` is null too rather than invented

`list_index` is always there: it says where the row sat in the frame, which is
a fact, not a claim.

**Not every board is about players.** The alliance ranking's rows are
alliances — `uid` is an alliance id and `name` is the alliance's name, with
the tag in `alliance` and the R5 nowhere in the record. `entity` says which
kind a row is, and it matters: joining an alliance id against a player uid
would be nonsense.

A board id carries a variant where one command serves several rankings:
`rank.get/type=2` is the alliance board, so opening `rank.get` at another type
files its own board instead of deduping into this one. `--board rank.get`
matches every variant of it; `--board rank.get/type=2` selects just the one.

Fields per record: leaderboard, leaderboard_label, entity, uid, name,
server_id, position, position_source, list_index, score, score_field, power,
alliance, discovered, seen_at.

Rows are keyed by `(uid, leaderboard)`, so re-opening a board refreshes what
it says about a player rather than appending them again, and the same player
appearing on two different boards is two records — which is the point, since
their score on each means a different thing. `score_field` names the column
the number came from, because a board's score is whatever that board counts;
comparing across boards without reading it would be nonsense. The big counters
arrive inconsistently typed — `rank.get` sent `fightpower` as a number and
`armyKill` as a string in the same entry — so they are parsed either way and
`score` is always an int.

**This must run under the Windows Python, not the WSL one.** WSL2 sits in a
NAT'd VM whose network namespace is not the host's, so an AF_PACKET socket
there sees WSL's own traffic and never a byte of the game's. From WSL, invoke
the Windows interpreter by path:

    /mnt/c/Python312/python.exe tools/scan_leaderboard.py --seconds 300

Requirements on that interpreter: npcap (ships with Wireshark), plus
`pip install scapy zstandard`.

Each run rewrites `--json` from scratch — it is this run's result, not a
database that grows across runs. Point successive runs at different files if
you want to keep both.
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
import leaderboard_store  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET  # noqa: E402
from map_capture import (  # noqa: E402
    MapIndex, add_capture_arguments, check_platform, dump_records, human_size,
    start_capture,
)

#: The one line `--quiet` prints on a tick, for a parent to read instead of the
#: human ones: `##LBSTAT##\tboards=2\trows=100\tsnapshots=3`. It carries COUNTS and
#: nothing else — no name, no uid — because the parent that reads it (the panel's
#: leaderboard trigger) writes what it hears into a log people send each other.
STAT_MARKER = "##LBSTAT##"


class LeaderboardIndex(MapIndex):
    """MapIndex that keeps ranking rows instead of map tiles.

    Everything of interest arrives through `on_response`: a board is a reply
    to a command the client sends when you open the screen, never a map block.
    `on_blocks` is therefore left doing nothing — but the class still derives
    from MapIndex, because the server election underneath it is what stamps
    which map you were on, and because `--dump` lives there.

    Rows are keyed by `(uid, leaderboard)`. Nothing is evicted: a board you
    opened ten minutes ago is still what that board said, and a run that
    dropped it the moment you navigated away would collect one screen.
    """

    def __init__(self, boards=None, known_only=False) -> None:
        super().__init__()
        self.boards = boards
        self.known_only = known_only
        self._rows: dict[tuple, proto.LeaderboardEntry] = {}
        self._seen_at: dict[tuple, float] = {}
        # The printable line last announced per row — see take_new().
        self._reported: dict[tuple, tuple] = {}
        # How many replies were read as boards, keyed by board, so the summary
        # can say which screens were opened and how often.
        self.boards_seen: dict[str, int] = {}
        # Rows a --board filter threw away, so "nothing collected" can be told
        # apart from "collected, none of them the board you asked for".
        self.rejected = 0

    def on_response(self, command, payload) -> None:
        """Every server reply that is not a map block — a board may be in it.

        Callers hold `_index_lock`.
        """
        if self.known_only and command not in proto.LEADERBOARDS:
            return
        now = time.time()
        rows = list(proto.leaderboard_entries(command, payload))
        if not rows:
            return
        kept = 0
        for row in rows:
            if self.boards is not None and not self._wanted(row.board):
                self.rejected += 1
                continue
            key = (row.uid, row.board)
            self._rows[key] = row
            self._seen_at[key] = now
            kept += 1
        if kept:
            self.boards_seen[rows[0].board] = self.boards_seen.get(
                rows[0].board, 0) + 1

    def _wanted(self, board: str) -> bool:
        """Whether `--board` asked for this board.

        The bare command matches every variant of it, because a board id can
        carry one (`rank.get/type=2`) and `--board rank.get` is what somebody
        reading the command list would naturally type. Naming the variant
        outright still selects just that one.
        """
        return any(board == want or board.startswith(want + "/")
                   for want in self.boards)

    @property
    def rows(self) -> list:
        with self._index_lock:
            return list(self._rows.values())

    def records(self) -> list:
        """Every row as a serialisable dict, each stamped with `seen_at`.

        `seen_at` is epoch seconds on the capture host — when the board last
        said this, not when the file was written. It matters more here than on
        a map sweep: two rows from the same board can be minutes apart if you
        opened it twice, and a score is exactly the kind of thing that moves.
        """
        with self._index_lock:
            out = []
            for key, row in self._rows.items():
                record = row.as_dict()
                record["seen_at"] = int(self._seen_at.get(key, 0))
                out.append(record)
        # Grouped by board, then by placement where there is one, then by
        # score — so the file reads the way the screen did.
        out.sort(key=lambda r: (r["leaderboard"],
                                r["position"] if r["position"] is not None
                                else r["list_index"],
                                -(r["score"] or 0)))
        return out

    def take_new(self) -> list:
        """Rows whose printable line changed since the last call.

        Keyed on what the line says rather than on the uid: re-opening a board
        after an hour is worth reprinting only where something moved, and
        keying by uid alone would print each player once and then suppress
        every update to their score forever.
        """
        out = []
        with self._index_lock:
            for key, row in self._rows.items():
                line = (row.position, row.score, row.power, row.name)
                if self._reported.get(key) == line:
                    continue
                self._reported[key] = line
                out.append(row)
        out.sort(key=lambda r: (r.board,
                                r.position if r.position is not None
                                else r.list_index))
        return out


def board_set(text: str) -> set:
    """Parse `--board` — one command name or a comma-separated list of them.

    Not validated against LEADERBOARDS: the whole point of the shape test is
    that a board can be collected before it is described, and refusing a name
    this file has not heard of would make those boards unfilterable.
    """
    boards = {part.strip() for part in text.split(",") if part.strip()}
    if not boards:
        raise argparse.ArgumentTypeError("no board given")
    return boards


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_capture_arguments(ap)
    ap.add_argument("--json", default=None,
                    help="checkpoint every row collected to this file, "
                         "rewritten on every tick (default: no file is written)")
    ap.add_argument("--sqlite", default=None, metavar="PATH",
                    help="accumulate a HISTORY of the boards in this SQLite file: "
                         "each time a board is captured it is saved as a timestamped "
                         "snapshot (unchanged repeats are skipped), so the slices "
                         "build up over runs instead of --json overwriting them "
                         "(tools/lib/leaderboard_store.py)")
    ap.add_argument("--interval", type=int, default=15,
                    help="seconds between processing ticks — each one prints "
                         "the progress line and rewrites --json if given "
                         "(default 15; lower it for tests)")
    ap.add_argument("--board", type=board_set, metavar="NAME[,NAME...]",
                    help="only these boards, by the command that carries them "
                         "(--board al.rank)")
    ap.add_argument("--known-only", action="store_true",
                    help="collect only the boards lastwar_proto.py describes, "
                         "skipping any found by shape")
    ap.add_argument("--quiet", action="store_true",
                    help="print no rows and no human tick line — one machine-readable "
                         f"'{STAT_MARKER} boards=… rows=… snapshots=…' per tick "
                         "instead. For a parent that logs what this child says: the "
                         "row lines carry player names and uids, and a long run "
                         "prints a tick every --interval seconds, so an unattended "
                         "collector would fill somebody's log with both")
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

    index = LeaderboardIndex(boards=args.board, known_only=args.known_only)
    # The history store, if asked for — opened once and written on every tick and at
    # the end (a snapshot per board, unchanged repeats skipped). Opened up front so a
    # bad path fails now, not after a long run.
    store = None
    if args.sqlite:
        try:
            store = leaderboard_store.connect(args.sqlite)
        except Exception as exc:                 # noqa: BLE001 — a bad path is a message
            print(f"{C_ERR}cannot open the SQLite history {args.sqlite}: {exc}{C_RESET}",
                  file=sys.stderr)
            return 1
    stop, bpf = start_capture(index, args)

    print("Last War leaderboard scan — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    sink = f" -> {args.json} every {args.interval}s" if args.json else ""
    scope = f" — only {', '.join(sorted(args.board))}" if args.board else ""
    known = ", described boards only" if args.known_only else ""
    print(f"{C_DIM}listening {window}{sink}{scope}{known} — open a ranking in "
          f"the game, or nothing will arrive{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    # None means run until interrupted, so every deadline test has to tolerate
    # not having one.
    deadline = time.time() + args.seconds if args.seconds else None
    last_tick = time.time()
    announced: set = set()
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(1.0)
            if time.time() - last_tick >= args.interval:
                last_tick = time.time()
                left = (f"…{int(deadline - time.time())}s left"
                        if deadline is not None else "…running")
                if not args.quiet:
                    print(f"{C_DIM}  {left} — {len(index.boards_seen)} board(s) "
                          f"opened, {len(index.rows)} row(s) collected{C_RESET}")
                if args.json and not dump_records(index.records(), args.json):
                    if not args.quiet:
                        print(f"{C_DIM}  (checkpoint locked, skipped this "
                              f"flush){C_RESET}")
                if index.transcript is not None:
                    # Flushed here rather than per frame, so a reader tailing
                    # the transcript is one tick behind at worst and the
                    # sniffer thread is never blocked on the disk.
                    index.transcript.flush()
                    if not args.quiet:
                        print(f"{C_DIM}  transcript: "
                              f"{index.transcript.frames} frame(s), "
                              f"{human_size(index.transcript.size())}{C_RESET}")
                saved = ()
                if store is not None:
                    saved = leaderboard_store.save_records(
                        store, index.records(), int(time.time()))
                    if saved and not args.quiet:
                        print(f"{C_DIM}  history: +{len(saved)} snapshot(s) "
                              f"({', '.join(sorted(saved))}){C_RESET}")
                if args.quiet:
                    # Counts only, one line, for the parent to roll up. The board
                    # names are left out too: they are safe, but the parent has no
                    # use for them and a shorter line is a cheaper pipe.
                    print(f"{STAT_MARKER}\tboards={len(index.boards_seen)}"
                          f"\trows={len(index.rows)}\tsnapshots={len(saved)}",
                          flush=True)
            for row in index.take_new():
                if args.quiet:
                    # THE ROWS ARE THE PII: a name and a uid on every one. Still
                    # drained — `take_new` is what marks a row as reported, so
                    # skipping the call would make the next tick print the whole
                    # board again — but never printed.
                    continue
                if row.board not in announced:
                    announced.add(row.board)
                    tag = (f" {C_DIM}(found by shape — position and score are "
                           f"a guess){C_RESET}" if row.discovered else "")
                    print(f"\n{C_OK}{row.board_label}{C_RESET} "
                          f"{C_DIM}[{row.board}]{C_RESET}{tag}")
                # Blank rather than a number where the board never said: see
                # the module docstring on why a position is often unknowable.
                # A position taken from the order of the reply rather than
                # stated by the board is dimmed, so the two are never read as
                # the same claim.
                if row.position is None:
                    place = f"{C_DIM}·{row.list_index:<3}{C_RESET}"
                elif row.position_source == "order":
                    place = f"{C_DIM}#{row.position:<3}{C_RESET}"
                else:
                    place = f"#{row.position:<3}"
                score = (f"  {row.score_field} {row.score:,}"
                         if row.score is not None else "")
                power = f"  power {row.power:,}" if row.power is not None else ""
                where = f"  server {row.server_id}" if row.server_id else ""
                tag = f"  [{row.alliance}]" if row.alliance else ""
                # An alliance's uid is an alliance id, not a player's, and the
                # column is labelled so nobody joins the two sets on it.
                ident = "id" if row.entity == "alliance" else "uid"
                print(f"  {place} {row.name or '?'}  {ident} {row.uid}"
                      f"{tag}{where}{score}{power}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    everything = index.rows
    described = sum(1 for r in everything if not r.discovered)
    print(f"\n{len(everything)} row(s) collected across "
          f"{len(index.boards_seen)} board(s)"
          + (f", {index.rejected} row(s) dropped by --board"
             if index.rejected else ""))
    for board, times in sorted(index.boards_seen.items()):
        rows = sum(1 for r in everything if r.board == board)
        opened = "once" if times == 1 else f"{times} times"
        print(f"  {board}: {rows} row(s), read {opened}")
    if everything and described != len(everything):
        print(f"{C_DIM}{len(everything) - described} of them come from boards "
              f"found by shape rather than described in lastwar_proto.py — "
              f"they carry \"discovered\": true. Re-run with --known-only for "
              f"the described boards alone.{C_RESET}")
    print(f"traffic: {index.delivered} delivered / {index.packets} with payload")

    # Not map_capture's diagnose(): its empty case is about the map not
    # scrolling, and this tool never wanted map data in the first place. A
    # silent run here means no ranking was opened, which is a different
    # instruction to whoever is watching.
    if index.delivered and not index.packets:
        print(f"{C_ERR}npcap delivered {index.delivered} packet(s) but none "
              f"decoded as TCP-with-payload.{C_RESET} That is scapy failing to "
              f"map the datalink type — check for an 'Unable to guess datalink "
              f"type' warning above.")
    elif not index.delivered:
        print(f"{C_ERR}No packets at all.{C_RESET} Either the game is not "
              f"running, or npcap cannot see this interface — try "
              f"--list-ifaces and pin one with --iface.")
    elif not everything:
        print(f"{C_DIM}Packets arrived but no ranking did. A board only "
              f"crosses the wire when you open its screen in the client — "
              f"walk the ranking screens while the scan runs. If you did open "
              f"one, it is a board neither described nor shaped like the "
              f"known two: re-run with --dump and look for the reply that "
              f"carried it.{C_RESET}")

    if args.json:
        records = index.records()
        if dump_records(records, args.json):
            print(f"{C_OK}wrote {len(records)} row(s) to {args.json}{C_RESET}")
        else:
            print(f"{C_ERR}could not write {args.json} — the file is held by "
                  f"another process.{C_RESET} Close whatever has it open and "
                  f"re-run, or point --json somewhere else.")

    if store is not None:
        # A last flush, then the running total so the history's growth is visible.
        saved = leaderboard_store.save_records(store, index.records(), int(time.time()))
        total = store.execute("SELECT COUNT(DISTINCT ts || board_type) "
                              "FROM entries").fetchone()[0]
        note = f" (+{len(saved)} on the final flush)" if saved else ""
        print(f"{C_OK}history: {total} snapshot(s) in {args.sqlite}{note}{C_RESET}")
        store.close()

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
