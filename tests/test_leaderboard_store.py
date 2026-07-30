r"""The ranking-board history store — snapshots, dedup, and per-board grouping.

`tools/lib/leaderboard_store.py` keeps a SQLite history of ranking boards: one
timestamped snapshot per capture, so the boards accumulate over time instead of the
JSON being overwritten each run (#1134). Two things matter and are pinned here: an
UNCHANGED board is not stored twice (or the history fills with duplicates every flush
while a screen sits still), and a CHANGED board is a new snapshot with a new time (or
there is no history at all). Plus the mixed-records path groups rows by board.

No wire, no game — a temp db and a few dicts::

    python3 tests/test_leaderboard_store.py
"""
from __future__ import annotations

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
    return [{"leaderboard": "al.rank", "entity": "player", "uid": f"u{i}",
             "name": f"p{i}", "position": i + 1, "score": s, "power": s * 10,
             "alliance": "AAA", "list_index": i, "seen_at": 1000 + i}
            for i, s in enumerate(scores)]


def test_a_snapshot_stores_the_board_and_its_rows():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    snap = ls.save_snapshot(conn, "al.rank", _rows(30, 20, 10), captured_at=1234)
    assert snap is not None
    n = conn.execute("SELECT n_rows FROM snapshots WHERE id=?", (snap,)).fetchone()[0]
    assert n == 3
    got = conn.execute("SELECT uid, score FROM entries WHERE snapshot_id=? "
                       "ORDER BY list_index", (snap,)).fetchall()
    assert got == [("u0", 30), ("u1", 20), ("u2", 10)]


def test_an_unchanged_board_is_not_stored_twice():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    first = ls.save_snapshot(conn, "al.rank", _rows(30, 20, 10), captured_at=1000)
    # same rows, later capture time → still a duplicate, skipped.
    again = ls.save_snapshot(conn, "al.rank", _rows(30, 20, 10), captured_at=2000)
    assert first is not None and again is None
    count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    assert count == 1


def test_a_changed_board_is_a_new_snapshot():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    ls.save_snapshot(conn, "al.rank", _rows(30, 20, 10), captured_at=1000)
    ls.save_snapshot(conn, "al.rank", _rows(40, 30, 20), captured_at=2000)   # moved
    snaps = conn.execute("SELECT captured_at FROM snapshots ORDER BY captured_at").fetchall()
    assert [s[0] for s in snaps] == [1000, 2000]                # two slices in history


def test_seen_at_alone_does_not_make_a_new_snapshot():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    a = _rows(30, 20, 10)
    b = _rows(30, 20, 10)
    for r in b:
        r["seen_at"] += 500                                     # only the timestamp moved
    ls.save_snapshot(conn, "al.rank", a, captured_at=1000)
    assert ls.save_snapshot(conn, "al.rank", b, captured_at=2000) is None


def test_empty_rows_store_nothing():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    assert ls.save_snapshot(conn, "al.rank", [], captured_at=1000) is None
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_save_records_groups_by_board():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    mixed = _rows(30, 20)
    other = [{"leaderboard": "champion.duel", "entity": "player", "uid": "c1",
              "name": "d1", "position": 1, "score": 99, "list_index": 0, "seen_at": 5000}]
    saved = ls.save_records(conn, mixed + other, captured_at=1)
    assert set(saved) == {"al.rank", "champion.duel"}
    # the champion board took its own seen_at as the capture time.
    stamp = conn.execute("SELECT captured_at FROM snapshots WHERE leaderboard=?",
                         ("champion.duel",)).fetchone()[0]
    assert stamp == 5000


def test_extra_keeps_unmapped_fields():
    tmp = Path(tempfile.mkdtemp())
    conn = ls.connect(str(tmp / "lb.db"))
    row = _rows(30)[0]
    row["position_source"] = "order"
    row["discovered"] = True
    snap = ls.save_snapshot(conn, "al.rank", [row], captured_at=1)
    extra = conn.execute("SELECT extra FROM entries WHERE snapshot_id=?", (snap,)).fetchone()[0]
    import json
    parsed = json.loads(extra)
    assert parsed["position_source"] == "order" and parsed["discovered"] is True


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
