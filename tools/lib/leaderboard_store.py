#!/usr/bin/env python3
r"""A SQLite history of ranking-board snapshots — one timestamped slice per capture.

``scan_leaderboard.py`` reads a ranking board off the wire the moment the client
opens it and rewrites a JSON file with *this run's* rows. That answers "who is on the
board now" but throws yesterday away. This store keeps the slices instead: every time
a board is captured, its rows are written with one shared timestamp — the touch point
— so the boards accumulate a history a reader can walk back through: "the alliance
top-10 a week ago", "how a player's rank moved".

One flat table, exactly the shape task #1134 asked for::

    entries(id, ts, board_type, rank, uid, name, score, raw_json)

`ts` is the capture time shared by every row of one snapshot; `board_type` is the
command that carried the board (`al.rank`, `champion.duel.result.show.rank.list`, …);
`rank` is the placement (the board's own number when it stated one, else its position
in the reply); `raw_json` is the whole decoded row so nothing is lost to the columns.

**An unchanged board is not stored twice.** A board whose rows match its last stored
snapshot (same order, same placements/uids/names/scores) is skipped — the capture
flushes on a timer, so re-opening a screen or a flush while the board sits still would
otherwise fill the history with identical slices. A board that *moved* is a new
snapshot at a new time, which is the point of keeping the history.

The row dicts are exactly what ``LeaderboardIndex.records()`` yields (see
scan_leaderboard.py): ``leaderboard``, ``uid``, ``name``, ``position``,
``list_index``, ``score`` and the rest. Nothing here talks to the wire or the game —
it is a plain file store a test drives with a temp path and a list of dicts.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Iterable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         INTEGER NOT NULL,
    board_type TEXT    NOT NULL,
    rank       INTEGER,
    uid        INTEGER,
    name       TEXT,
    score      INTEGER,
    raw_json   TEXT
);
CREATE INDEX IF NOT EXISTS ix_entries_board ON entries(board_type, ts);
CREATE INDEX IF NOT EXISTS ix_entries_uid   ON entries(uid);
"""


def connect(path: str) -> sqlite3.Connection:
    """Open (creating) the store at ``path`` with the schema applied."""
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _rank(row: dict):
    """The placement: the board's own number when it stated one, else its position."""
    pos = row.get("position")
    return _i(pos) if pos is not None else _i(row.get("list_index"))


def _shaped(rows: list) -> list:
    """The identifying/ranking view of a board's rows, for the change hash."""
    return [{"rank": _rank(r), "uid": _s(r.get("uid")), "name": _s(r.get("name")),
             "score": _i(r.get("score"))} for r in rows]


def _content_hash(rows: list) -> str:
    blob = json.dumps(_shaped(rows), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _last_board_rows(conn: sqlite3.Connection, board_type: str) -> list:
    """The rows of ``board_type``'s newest snapshot, as shaped dicts (or [])."""
    ts_row = conn.execute(
        "SELECT ts FROM entries WHERE board_type = ? ORDER BY ts DESC LIMIT 1",
        (board_type,)).fetchone()
    if not ts_row:
        return []
    cur = conn.execute(
        "SELECT rank, uid, name, score FROM entries WHERE board_type = ? AND ts = ? "
        "ORDER BY id", (board_type, ts_row[0]))
    return [{"rank": r[0], "uid": _s(r[1]), "name": r[2], "score": r[3]}
            for r in cur.fetchall()]


def save_snapshot(conn: sqlite3.Connection, ts: int, board_type: str,
                  rows: Iterable[dict]) -> int:
    """Store one board's rows as a snapshot at ``ts``; skip an unchanged repeat.

    Returns the number of rows written, or ``0`` when the board is identical to its
    last stored snapshot (nothing written) or has no rows.
    """
    rows = [dict(r) for r in rows]
    if not rows:
        return 0
    prev = _last_board_rows(conn, board_type)
    if prev and _content_hash_shaped(prev) == _content_hash(rows):
        return 0                                 # unchanged since last time — skip
    conn.executemany(
        "INSERT INTO entries (ts, board_type, rank, uid, name, score, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(int(ts), board_type, _rank(row), _i(row.get("uid")), _s(row.get("name")),
          _i(row.get("score")), json.dumps(row, ensure_ascii=False, default=str))
         for row in rows])
    conn.commit()
    return len(rows)


def save_records(conn: sqlite3.Connection, records: Iterable[dict],
                 ts: int) -> dict:
    """Save a mixed list of rows (many boards) — one snapshot per board.

    ``records`` is exactly ``LeaderboardIndex.records()``: rows of several boards, each
    with its own ``leaderboard`` key. Grouped by board; each is a snapshot stamped with
    the board's freshest ``seen_at`` (when present) so the touch point is when it crossed
    the wire, else ``ts``. Returns ``{board_type: rows_written}`` for boards stored.
    """
    boards: dict[str, list] = {}
    for row in records:
        board = str(row.get("leaderboard") or "")
        if board:
            boards.setdefault(board, []).append(row)
    saved = {}
    for board, rows in boards.items():
        stamp = max((int(r.get("seen_at") or 0) for r in rows), default=0) or int(ts)
        n = save_snapshot(conn, stamp, board, rows)
        if n:
            saved[board] = n
    return saved


def _content_hash_shaped(shaped: list) -> str:
    blob = json.dumps(shaped, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _s(value):
    return None if value is None else str(value)


def _i(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
