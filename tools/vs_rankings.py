#!/usr/bin/env python3
r"""Write down the whole alliance duel — both sides, every day, every field.

    python tools/vs_rankings.py                              read and print a summary
    python tools/vs_rankings.py --sqlite profiles/default/leaderboard_history.db
                                                             …and store it
    python tools/vs_rankings.py --no-fetch                   read only what the client
                                                             already holds, send nothing
    python tools/vs_rankings.py --json results/vs.json       dump the raw read as well
    python tools/vs_rankings.py --quiet                      one marker line, no names

The duel («VS») is a week between two alliances on two servers. The passive collector
catches its ranking when somebody opens the screen, and until #1304 wrote down one
number per player for the whole week: no day, no side, and none of the fields the
decoder had no column for.

This asks the client instead. `tools/lib/vs_duel.py` says where it all lives; the short
version is that ONE request — the same one the duel screen sends — brings back every
day of the week with each row stamped with its day, both alliances in the one list, and
the two sides' own per-day scores are already in memory beside it. So the whole week,
broken down, both sides, costs one message and a read.

**It is still only as complete as the week is old.** Days that have not happened have no
rows, and a day the client was never told about (an account that did not log in) comes
back the way the server answers it, which is usually not at all. Running this once a day
is what makes the history complete; running it on Saturday gives Saturday's view of the
week, which is most of it but not the days the server has stopped serving.

The row it writes goes into the same `leaderboard_history.db` the passive collector
uses, under the same board ids, with `source = "game"` to say it was read out of the
client rather than off the wire.

Needs the Lua daemon and a client that is logged in — a duel nobody has loaded reads as
«no duel», and says so rather than storing an empty week.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import leaderboard_store  # noqa: E402
import vs_duel  # noqa: E402
from lua_client import get_evaluator  # noqa: E402

#: The one line `--quiet` prints, for a parent to read instead of the human ones.
#: Counts only — the rows carry names, uids and alliance tags, and a parent that logs
#: what its child says would put every one of them in a file people send each other.
STAT_MARKER = "##VSSTAT##"


def read_duel(fetch: bool = True, settle: float = 2.0) -> dict:
    """Ask the client for the duel and read it back. Returns the parsed state."""
    ev = get_evaluator()
    if fetch:
        # The day ranking first, because a `type = 0` reply is the one that carries
        # every day at once; the week is a second request because the client keeps the
        # two in different places and neither reply fills the other.
        for rank_type in (vs_duel.RANK_DAY, vs_duel.RANK_WEEK):
            ev.run(vs_duel.fetch_chunk(rank_type), marker=vs_duel.MARKER, settle=settle)
    lines = ev.run(vs_duel.read_chunk(), marker=vs_duel.MARKER, settle=settle + 1.0)
    return vs_duel.parse(lines)


def summarise(state: dict) -> dict:
    """Counts only — what came back, with not one identifier in it."""
    players = state.get("players", [])
    days = sorted({p.get("day") for p in players if p.get("day") is not None})
    return {
        "sides": len(state.get("sides", [])),
        "days": len(days),
        "day_rows": sum(1 for p in players if p.get("day") is not None),
        "standing_rows": sum(1 for p in players if p.get("day") is None),
        "side_days": len(state.get("side_days", [])),
        "unread": len(state.get("unread", [])),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", default=None, metavar="PATH",
                    help="append the read to this ranking history "
                         "(tools/lib/leaderboard_store.py); the profile's own is "
                         "profiles/<name>/leaderboard_history.db")
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="also write the raw parsed read to this file")
    ap.add_argument("--no-fetch", dest="fetch", action="store_false",
                    help="send nothing: read only what the client already holds. "
                         "Answers with whatever was last loaded, which after a fresh "
                         "start is usually nothing")
    ap.add_argument("--settle", type=float, default=2.0,
                    help="seconds to wait for each Lua step (default 2.0)")
    ap.add_argument("--quiet", action="store_true",
                    help="print no names — one machine-readable "
                         f"'{STAT_MARKER} …' line instead, for a parent that logs it")
    args = ap.parse_args()

    started = time.time()
    try:
        state = read_duel(fetch=args.fetch, settle=args.settle)
    except Exception as exc:                     # noqa: BLE001 — a dead link is a message
        print(f"the client could not be read: {exc}", file=sys.stderr)
        return 1
    counts = summarise(state)
    elapsed = time.time() - started

    if not state.get("sides") and not state.get("players"):
        # An empty read is a state, not a failure: no duel this week, or a client that
        # has not loaded one. Storing it would write an empty week over a full one.
        print("no alliance duel in this client — nothing was stored. Either the duel "
              "is not running this week, or the client has not loaded it (open the "
              "alliance screen once, or run without --no-fetch).")
        return 0

    stored = {}
    if args.sqlite:
        conn = leaderboard_store.connect(args.sqlite)
        rows = vs_duel.store_records(state, int(time.time()))
        stored = leaderboard_store.save_records(conn, rows, int(time.time()))
        # The read itself is a sighting too — «this is what was asked for, this is what
        # came back», so a week with a missing day says so in the same table the
        # passive collector's rejections are in.
        leaderboard_store.save_sighting(
            conn, int(time.time()), "al.battle.rank.info",
            leaderboard_store.VERDICT_KEPT if stored else leaderboard_store.VERDICT_EMPTY,
            None if stored else "the client answered with no rows",
            rows_seen=len(rows), rows_kept=sum(stored.values()), source="game",
            shape=leaderboard_store.describe_shape(
                (state.get("players") or [{}])[0]))
        for note in state.get("unread", []):
            leaderboard_store.save_sighting(
                conn, int(time.time()), "al.battle.rank.info",
                leaderboard_store.VERDICT_REJECTED,
                f"a line this reader does not understand: {note[:80]}", source="game")
        conn.close()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)

    if args.quiet:
        print(f"{STAT_MARKER}\tsides={counts['sides']}\tdays={counts['days']}"
              f"\trows={counts['day_rows'] + counts['standing_rows']}"
              f"\tsnapshots={len(stored)}", flush=True)
        return 0

    head = state.get("head", {})
    own = vs_duel.own_alliance_id(state)
    print(f"alliance duel — {counts['sides']} side(s), {counts['days']} day(s) with "
          f"rows, {counts['day_rows']} daily row(s), {counts['standing_rows']} "
          f"standing row(s), read in {elapsed:.1f}s")
    if own is None:
        print("  which side is ours could not be told (no opponent named) — the rows "
              "are stored with an empty side rather than a guess")
    for side in state.get("sides", []):
        alliance_id = side.get("allianceId") or side.get("id")
        which = vs_duel.side_of(state, alliance_id) or "?"
        history = sorted(
            ((r.get("day"), r.get("score")) for r in state.get("side_days", [])
             if str(r.get("alliance_id")) == str(alliance_id)),
            key=lambda pair: (pair[0] is None, pair[0]))
        by_day = "  ".join(f"d{day}={score:,}" for day, score in history
                           if isinstance(score, int))
        # `alScore` is TODAY's — the finished days are the ones in `by_day`. Said that
        # way round because reading it as the week's total is the mistake the number
        # invites: it is the biggest figure on the line.
        today = head.get("weekday_index")
        print(f"  [{which}] {side.get('abbr')} #{side.get('serverId')}  "
              f"{by_day}  d{today}={int(side.get('alScore') or 0):,} (today)  "
              f"days won {side.get('win')}")
    if head.get("min_day_score"):
        print(f"  the day's minimum is {int(head['min_day_score']):,}, the week's "
              f"{int(head.get('min_week_score') or 0):,}")
    if stored:
        print(f"stored: " + ", ".join(f"{board} {n} row(s)"
                                      for board, n in sorted(stored.items())))
    elif args.sqlite:
        print("stored nothing — every board is identical to its last snapshot")
    if counts["unread"]:
        print(f"{counts['unread']} line(s) came back that this reader does not "
              f"understand; they are in the `sightings` table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
