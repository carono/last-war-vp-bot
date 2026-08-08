r"""The ranking-board history store — flat snapshots, dedup, per-board grouping (#1134).

`tools/lib/leaderboard_store.py` keeps a SQLite history of ranking boards in one flat
table `entries(id, ts, board_type, rank, uid, name, score, raw_json)`: every capture
writes the board's rows with one shared ts. Two things matter and are pinned here: an
UNCHANGED board is not stored twice (the capture flushes on a timer, so identical
slices would pile up), and a CHANGED board is a new snapshot with a new ts. Plus the
mixed-records path groups rows by board and the columns are filled from the decoded row.

No wire, no game::

    python3 tests/test_leaderboard_store.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import leaderboard_store as ls  # noqa: E402


def _rows(*scores):
    """A board of rows: (uid, name, score) with an ascending list_index."""
    return [{"leaderboard": "al.rank", "entity": "player", "uid": 100 + i,
             "name": f"p{i}", "position": i + 1, "score": s, "power": s * 10,
             "list_index": i, "seen_at": 1000 + i}
            for i, s in enumerate(scores)]


def test_a_snapshot_stores_rows_with_one_ts_and_the_schema():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    n = ls.save_snapshot(conn, 1234, "al.rank", _rows(30, 20, 10))
    assert n == 3
    got = conn.execute("SELECT ts, board_type, rank, uid, name, score, raw_json "
                       "FROM entries ORDER BY id").fetchall()
    assert [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in got] == [
        (1234, "al.rank", 1, 100, "p0", 30),
        (1234, "al.rank", 2, 101, "p1", 20),
        (1234, "al.rank", 3, 102, "p2", 10)]
    # raw_json keeps the whole decoded row
    assert json.loads(got[0][6])["power"] == 300


def test_an_unchanged_board_is_not_stored_twice():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    assert ls.save_snapshot(conn, 1000, "al.rank", _rows(30, 20, 10)) == 3
    assert ls.save_snapshot(conn, 2000, "al.rank", _rows(30, 20, 10)) == 0   # same → skip
    assert conn.execute("SELECT COUNT(DISTINCT ts) FROM entries").fetchone()[0] == 1


def test_a_changed_board_is_a_new_snapshot():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    ls.save_snapshot(conn, 1000, "al.rank", _rows(30, 20, 10))
    ls.save_snapshot(conn, 2000, "al.rank", _rows(40, 30, 20))               # moved
    ts = [r[0] for r in conn.execute("SELECT DISTINCT ts FROM entries ORDER BY ts")]
    assert ts == [1000, 2000]


def test_empty_rows_store_nothing():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    assert ls.save_snapshot(conn, 1, "al.rank", []) == 0
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_rank_falls_back_to_list_index_when_no_position():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    rows = _rows(30, 20)
    for r in rows:
        r["position"] = None                     # board stated no number
    ls.save_snapshot(conn, 1, "al.rank", rows)
    ranks = [r[0] for r in conn.execute("SELECT rank FROM entries ORDER BY id")]
    assert ranks == [0, 1]                        # the list_index instead


def test_save_records_groups_by_board_and_stamps_by_seen_at():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    other = [{"leaderboard": "champion.duel", "uid": 7, "name": "d1",
              "position": 1, "score": 99, "list_index": 0, "seen_at": 5000}]
    saved = ls.save_records(conn, _rows(30, 20) + other, ts=1)
    assert set(saved) == {"al.rank", "champion.duel"}
    stamp = conn.execute("SELECT ts FROM entries WHERE board_type='champion.duel'").fetchone()[0]
    assert stamp == 5000                          # took the board's own seen_at


def _vs_rows(day, *scores):
    """A VS board's rows: both sides in one list, the way the duel really sends them.

    Every value is invented and looks it — the repository holds no real uid, name,
    alliance id or server (CLAUDE.md).
    """
    out = []
    for i, score in enumerate(scores):
        side = "own" if i % 2 == 0 else "enemy"
        out.append({
            "leaderboard": "al.battle.rank.info/type=0", "entity": "player",
            "scope": "player", "uid": 1000000000000001 + i, "name": f"Player{i}",
            "position": i + 1, "list_index": i, "score": score, "day": day,
            "side": side, "alliance": "AL1" if side == "own" else "AL2",
            "alliance_id": "a" * 32 if side == "own" else "b" * 32,
            "server_id": 900 + i % 2, "source": "game", "seen_at": 7000,
            "raw": {"uid": 1000000000000001 + i, "name": f"Player{i}",
                    "score": score, "day": day, "headSkinId": 20000 + i},
        })
    return out


def test_the_day_and_the_side_land_in_their_own_columns():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    ls.save_records(conn, _vs_rows(3, 50, 40) + _vs_rows(4, 60, 30), ts=1)
    got = conn.execute("SELECT day, side, scope, alliance, alliance_id, server_id, "
                       "source FROM entries ORDER BY day, rank").fetchall()
    assert [(r[0], r[1]) for r in got] == [(3, "own"), (3, "enemy"),
                                           (4, "own"), (4, "enemy")]
    assert got[0][2] == "player" and got[0][3] == "AL1" and got[0][6] == "game"
    assert got[0][4] == "a" * 32 and got[0][5] == 900


def test_two_days_of_the_same_players_are_two_snapshots_not_one():
    """The alliance duel sends the whole week at once — day 4 must not read as day 3."""
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    # The SAME players and the SAME scores, on two different days: without the day in
    # the change hash the second board is «unchanged» and is silently thrown away.
    ls.save_snapshot(conn, 1, "al.battle.rank.info/type=0", _vs_rows(3, 50, 40))
    assert ls.save_snapshot(conn, 2, "al.battle.rank.info/type=0",
                            _vs_rows(4, 50, 40)) == 2
    assert conn.execute("SELECT COUNT(DISTINCT day) FROM entries").fetchone()[0] == 2


def test_the_row_the_server_sent_is_kept_beside_the_decoded_one():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    ls.save_snapshot(conn, 1, "al.battle.rank.info/type=0", _vs_rows(3, 50))
    raw, payload = conn.execute(
        "SELECT raw_json, payload_json FROM entries").fetchone()
    # A field no column knows about survives in the payload and only there — the point
    # of keeping it at all.
    assert json.loads(payload)["headSkinId"] == 20000
    assert "headSkinId" not in json.loads(raw)
    assert "raw" not in json.loads(raw)           # not stored twice


def test_a_board_that_is_hex_identified_still_dedups_against_itself():
    """An alliance id does not fit the integer uid column, and used to break the hash.

    The column keeps NULL, the offered row keeps the hex string, and comparing one
    against the other made every alliance board differ from itself — six days of
    finished history rewritten on every single run.
    """
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    rows = [{"leaderboard": "al.battle.vs.alliances/day=2", "entity": "alliance",
             "scope": "alliance", "uid": "a" * 32, "alliance_id": "a" * 32,
             "name": "Alliance One", "score": 1234, "day": 2, "list_index": 0,
             "seen_at": 10}]
    assert ls.save_snapshot(conn, 1, "al.battle.vs.alliances/day=2", rows) == 1
    assert ls.save_snapshot(conn, 2, "al.battle.vs.alliances/day=2", rows) == 0


def test_what_was_turned_away_is_written_down_with_its_reason():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    ls.save_sighting(conn, 99, "some.reply", ls.VERDICT_REJECTED,
                     "no ranking-shaped list in the reply", rows_seen=0,
                     shape=ls.describe_shape({"total": 5, "list": [1, 2],
                                              "who": "Player1"}))
    got = conn.execute("SELECT ts, command, verdict, reason, shape_json "
                       "FROM sightings").fetchone()
    assert got[:4] == (99, "some.reply", "rejected",
                       "no ranking-shaped list in the reply")
    shape = json.loads(got[4])
    # The SHAPE, never the values: a reader learns the reply had a `who` string and a
    # two-element list, and learns nothing about whose name was in it.
    assert shape == {"total": "int", "list": "list[2]", "who": "str"}
    assert "Player1" not in got[4]


def test_a_store_written_by_the_older_code_is_brought_forward():
    """The seven-column table of #1134 gains the new columns and keeps its rows."""
    import sqlite3
    tmp = Path(tempfile.mkdtemp())
    path = str(tmp / "old.db")
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER "
        "NOT NULL, board_type TEXT NOT NULL, rank INTEGER, uid INTEGER, name TEXT, "
        "score INTEGER, raw_json TEXT);")
    old.execute("INSERT INTO entries (ts, board_type, rank, uid, name, score) "
                "VALUES (1, 'al.rank', 1, 42, 'Player1', 7)")
    old.commit()
    old.close()

    conn = ls.connect(path)
    kept = conn.execute("SELECT ts, name, score, day, side FROM entries").fetchone()
    assert kept == (1, "Player1", 7, None, None)   # the old row, one column poorer
    assert ls.save_snapshot(conn, 2, "al.rank", _vs_rows(1, 5)) == 1


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
