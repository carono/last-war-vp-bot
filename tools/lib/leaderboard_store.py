#!/usr/bin/env python3
r"""A SQLite history of ranking-board snapshots — one timestamped slice per capture.

``scan_leaderboard.py`` reads a ranking board off the wire the moment the client
opens it and rewrites a JSON file with *this run's* rows. That answers "who is on the
board now" but throws yesterday away. This store keeps the slices instead: every time
a board is captured it is written as one **snapshot** stamped with the capture time,
so the boards accumulate a history a reader can walk back through — "the alliance
top-10 a week ago", "how this player's rank moved".

Two tables, plain SQLite, no ORM:

  * ``snapshots(id, leaderboard, captured_at, n_rows, content_hash)`` — one row per
    saved slice of one board;
  * ``entries(snapshot_id, list_index, entity, uid, name, position, score, power,
    alliance, extra)`` — the board's rows, as decoded, tied to their snapshot.

**Identical back-to-back slices are not stored twice.** A board that has not changed
since its last snapshot (same rows, same order — a ``content_hash`` over them) is
skipped, so re-opening the same screen, or a capture that flushes every few seconds
while the board sits still, does not fill the history with duplicates. A board that
*has* moved is a new snapshot with a new time. That makes the history a record of
*changes*, which is the point of keeping it.

The row dicts are exactly what ``LeaderboardIndex.records()`` yields (see
scan_leaderboard.py) — ``leaderboard``, ``entity``, ``uid``, ``name``, ``position``,
``score``, ``power``, ``alliance``, ``list_index`` and the rest — so a caller passes
them straight through; any field the schema does not name is kept verbatim in
``extra`` as JSON so nothing decoded is lost.

Nothing here talks to the wire or the game; it is a plain file store a test drives
with a temp path and a list of dicts.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Iterable

# Columns lifted into their own fields for querying; everything else on a row dict
# rides along in `extra` as JSON so no decoded value is dropped.
_ENTRY_COLS = ("list_index", "entity", "uid", "name", "position", "score",
               "power", "alliance")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    leaderboard  TEXT    NOT NULL,
    captured_at  INTEGER NOT NULL,
    n_rows       INTEGER NOT NULL,
    content_hash TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    list_index   INTEGER,
    entity       TEXT,
    uid          TEXT,
    name         TEXT,
    position     INTEGER,
    score        INTEGER,
    power        INTEGER,
    alliance     TEXT,
    extra        TEXT
);
CREATE INDEX IF NOT EXISTS ix_snap_board  ON snapshots(leaderboard, captured_at);
CREATE INDEX IF NOT EXISTS ix_entry_snap  ON entries(snapshot_id);
CREATE INDEX IF NOT EXISTS ix_entry_uid   ON entries(uid);
"""


def connect(path: str) -> sqlite3.Connection:
    """Open (creating) the store at ``path`` with the schema applied."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _content_hash(rows: list) -> str:
    """A stable hash of a board's rows, so an unchanged board is recognised.

    Over the identifying/ranking fields in list order — not `seen_at`, which moves
    every capture and would make every slice look new. `json.dumps(sort_keys)` keeps
    it stable across dict orderings.
    """
    shaped = [
        {k: row.get(k) for k in ("list_index", "entity", "uid", "name",
                                 "position", "score", "power", "alliance")}
        for row in rows
    ]
    blob = json.dumps(shaped, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def last_hash(conn: sqlite3.Connection, leaderboard: str) -> "str | None":
    """The ``content_hash`` of the newest snapshot of ``leaderboard`` (or ``None``)."""
    cur = conn.execute(
        "SELECT content_hash FROM snapshots WHERE leaderboard = ? "
        "ORDER BY captured_at DESC, id DESC LIMIT 1", (leaderboard,))
    row = cur.fetchone()
    return row[0] if row else None


def save_snapshot(conn: sqlite3.Connection, leaderboard: str, rows: Iterable[dict],
                  captured_at: int) -> "int | None":
    """Store one board as a timestamped snapshot; skip an unchanged repeat.

    Returns the new snapshot id, or ``None`` when the board is identical to its last
    stored snapshot (nothing written) or has no rows (nothing to store).
    """
    rows = [dict(r) for r in rows]
    if not rows:
        return None
    digest = _content_hash(rows)
    if last_hash(conn, leaderboard) == digest:
        return None                              # unchanged since last time — skip
    cur = conn.execute(
        "INSERT INTO snapshots (leaderboard, captured_at, n_rows, content_hash) "
        "VALUES (?, ?, ?, ?)", (leaderboard, int(captured_at), len(rows), digest))
    snap_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO entries (snapshot_id, list_index, entity, uid, name, position, "
        "score, power, alliance, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(snap_id, row.get("list_index"), _s(row.get("entity")), _s(row.get("uid")),
          _s(row.get("name")), _i(row.get("position")), _i(row.get("score")),
          _i(row.get("power")), _s(row.get("alliance")),
          json.dumps({k: v for k, v in row.items() if k not in _ENTRY_COLS},
                     ensure_ascii=False, default=str))
         for row in rows])
    conn.commit()
    return snap_id


def save_records(conn: sqlite3.Connection, records: Iterable[dict],
                 captured_at: int) -> dict:
    """Save a mixed list of rows (many boards) — one snapshot per board.

    ``records`` is exactly ``LeaderboardIndex.records()``: rows of several boards, each
    carrying its own ``leaderboard`` key. They are grouped by board and each board is a
    snapshot. Returns ``{leaderboard: snapshot_id}`` for the boards that were stored
    (an unchanged board is left out).
    """
    boards: dict[str, list] = {}
    for row in records:
        board = str(row.get("leaderboard") or "")
        if board:
            boards.setdefault(board, []).append(row)
    saved = {}
    for board, rows in boards.items():
        # Prefer the board's own freshest `seen_at` as the capture time when present,
        # so a snapshot is stamped when the board actually crossed the wire.
        stamp = max((int(r.get("seen_at") or 0) for r in rows), default=0) or captured_at
        snap_id = save_snapshot(conn, board, rows, stamp)
        if snap_id is not None:
            saved[board] = snap_id
    return saved


def _s(value):
    return None if value is None else str(value)


def _i(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
