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
