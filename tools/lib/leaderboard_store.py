#!/usr/bin/env python3
r"""A SQLite history of ranking-board snapshots — one timestamped slice per capture.

``scan_leaderboard.py`` reads a ranking board off the wire the moment the client
opens it and rewrites a JSON file with *this run's* rows. That answers "who is on the
board now" but throws yesterday away. This store keeps the slices instead: every time
a board is captured, its rows are written with one shared timestamp — the touch point
— so the boards accumulate a history a reader can walk back through: "the alliance
top-10 a week ago", "how a player's rank moved".

One flat table of rows and one of what was seen::

    entries(id, ts, board_type, rank, uid, name, score, raw_json,
            day, side, scope, alliance, alliance_id, server_id, source, payload_json)
    sightings(id, ts, command, source, verdict, reason, rows_seen, rows_kept, shape_json)

`ts` is the capture time shared by every row of one snapshot; `board_type` is the
command that carried the board (`al.rank`, `champion.duel.result.show.rank.list`, …);
`rank` is the placement (the board's own number when it stated one, else its position
in the reply); `raw_json` is the whole decoded row so nothing is lost to the columns.

The last eight columns are #1304, and every one of them is a thing the store used to
watch go past. `day` is which day of a multi-day event the row belongs to — the alliance
duel scores six of them and the weekly total answers none of the questions people
actually ask. `side` and `alliance_id` are which of the two sides a row is on: a VS
board carries BOTH alliances in one list, and «my hundred and their eighty-two» was a
distinction the reader had to make by squinting at tags. `scope` is whether the row is a
player or an alliance. `source` is `wire` or `game` — read off the socket, or read out of
the client's own memory. And `payload_json` is the row as it ARRIVED, beside the
decoder's flattened view of it, because a decoder only keeps the fields it knows about
and the interesting one is always the field nobody had written a column for yet.

`sightings` is the other half of the same idea, pointed at the messages that were NOT
stored. A reply that does not look like a board is dropped — and used to be dropped in
silence, which is indistinguishable from never having arrived. Now the drop is written
down with the test that caused it and the SHAPE of the row (field names and types, never
values), so «what else came past while this was running» is a question the file answers.

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
import threading
from typing import Iterable

#: One lock for every store this process holds open. The collector writes snapshots from
#: its main loop and sightings from the sniffer thread, and SQLite objects are not
#: thread-safe by themselves — `connect()` therefore opens with `check_same_thread=False`
#: and every write in this module goes through here. Writes are a handful a minute at
#: worst, so one lock for all of them costs nothing worth measuring.
_WRITE_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    board_type  TEXT    NOT NULL,
    rank        INTEGER,
    uid         INTEGER,
    name        TEXT,
    score       INTEGER,
    raw_json    TEXT,
    day         INTEGER,
    side        TEXT,
    scope       TEXT,
    alliance    TEXT,
    alliance_id TEXT,
    server_id   INTEGER,
    source      TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_entries_board ON entries(board_type, ts);
CREATE INDEX IF NOT EXISTS ix_entries_uid   ON entries(uid);

CREATE TABLE IF NOT EXISTS sightings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    command     TEXT    NOT NULL,
    source      TEXT,
    verdict     TEXT    NOT NULL,
    reason      TEXT,
    rows_seen   INTEGER,
    rows_kept   INTEGER,
    shape_json  TEXT
);
CREATE INDEX IF NOT EXISTS ix_sightings_cmd ON sightings(command, ts);
"""

#: The columns added after #1134's original seven. A store written by the older code has
#: the table without them, and `ALTER TABLE ADD COLUMN` is the whole migration: SQLite
#: fills the existing rows with NULL, which is the honest answer for a row recorded
#: before anybody was writing down its day or its side. Nothing is rewritten and nothing
#: is dropped — an old history goes on being readable, one column poorer.
_ADDED_COLUMNS = (
    ("day", "INTEGER"), ("side", "TEXT"), ("scope", "TEXT"), ("alliance", "TEXT"),
    ("alliance_id", "TEXT"), ("server_id", "INTEGER"), ("source", "TEXT"),
    ("payload_json", "TEXT"),
)

#: What `save_sighting` may be told about a message that crossed the collector.
#: «kept» — rows were written; «empty» — read as a board and had no rows; «rejected» —
#: not stored, and `reason` says which test turned it away.
VERDICT_KEPT = "kept"
VERDICT_EMPTY = "empty"
VERDICT_REJECTED = "rejected"


def connect(path: str) -> sqlite3.Connection:
    """Open (creating) the store at ``path`` with the schema applied.

    Also brings an OLDER store up to the current schema — see :data:`_ADDED_COLUMNS`.
    """
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(_SCHEMA)
    have = {row[1] for row in conn.execute("PRAGMA table_info(entries)")}
    for column, kind in _ADDED_COLUMNS:
        if column not in have:
            conn.execute(f"ALTER TABLE entries ADD COLUMN {column} {kind}")
    # After the columns exist, never in the script above: on a store written by the
    # older code the index would be created over a column that is not there yet, and
    # the whole `connect` would fail on a file that is merely old.
    conn.execute("CREATE INDEX IF NOT EXISTS ix_entries_day ON entries(board_type, day)")
    conn.commit()
    return conn


def _rank(row: dict):
    """The placement: the board's own number when it stated one, else its position."""
    pos = row.get("position")
    return _i(pos) if pos is not None else _i(row.get("list_index"))


def _shaped(rows: list) -> list:
    """The identifying/ranking view of a board's rows, for the change hash.

    The DAY is in it, and it has to be: one pull of the alliance duel brings six days
    of the same 182 players, and a hash blind to the day would read days 2..6 as
    «the board again, unchanged» and store only the first.

    **It compares what is STORED, not what was offered** — hence `_i` on the uid, the
    same coercion the column does. An alliance's id is hex, so it does not fit the
    integer column and lands there as NULL; hashing the offered string against the
    stored NULL made every alliance board differ from itself, and six days of finished
    history were rewritten on every run. `alliance_id` is in the hash for the same
    reason from the other side: it is where a hex id actually survives, so it is what
    tells two alliance rows apart once the uid has become NULL for both.
    """
    return [{"rank": _rank(r), "uid": _i(r.get("uid")), "name": _s(r.get("name")),
             "score": _i(r.get("score")), "day": _i(r.get("day")),
             "alliance_id": _s(r.get("alliance_id"))} for r in rows]


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
        "SELECT rank, uid, name, score, day, alliance_id FROM entries "
        "WHERE board_type = ? AND ts = ? ORDER BY id", (board_type, ts_row[0]))
    return [{"rank": r[0], "uid": r[1], "name": r[2], "score": r[3], "day": r[4],
             "alliance_id": r[5]} for r in cur.fetchall()]


def save_snapshot(conn: sqlite3.Connection, ts: int, board_type: str,
                  rows: Iterable[dict]) -> int:
    """Store one board's rows as a snapshot at ``ts``; skip an unchanged repeat.

    Returns the number of rows written, or ``0`` when the board is identical to its
    last stored snapshot (nothing written) or has no rows.
    """
    rows = [dict(r) for r in rows]
    if not rows:
        return 0
    with _WRITE_LOCK:
        return _insert_snapshot(conn, int(ts), board_type, rows)


def _insert_snapshot(conn, ts: int, board_type: str, rows: list) -> int:
    prev = _last_board_rows(conn, board_type)
    if prev and _content_hash_shaped(prev) == _content_hash(rows):
        return 0                                 # unchanged since last time — skip
    conn.executemany(
        "INSERT INTO entries (ts, board_type, rank, uid, name, score, raw_json, "
        "day, side, scope, alliance, alliance_id, server_id, source, payload_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(int(ts), board_type, _rank(row), _i(row.get("uid")), _s(row.get("name")),
          _i(row.get("score")), json.dumps(
              {k: v for k, v in row.items() if k != "raw"},
              ensure_ascii=False, default=str),
          _i(row.get("day")), _s(row.get("side")),
          _s(row.get("scope") or row.get("entity")), _s(row.get("alliance")),
          _s(row.get("alliance_id")), _i(row.get("server_id")),
          _s(row.get("source")), _payload(row))
         for row in rows])
    conn.commit()
    return len(rows)


def _payload(row: dict):
    """The row EXACTLY as it arrived — the server's own dict, or the game's.

    The columns are a reading of a row; this is the row. It is kept apart from
    `raw_json` (which is the decoder's flattened view) because the two answer different
    questions, and because for two years the flattened one was all there was: a field
    the decoder had no column for — a hero id, a head skin, a chat bubble, whatever the
    next event adds — was seen once and thrown away. Anything the sender did not carry
    a payload for stores NULL rather than a copy of the flattened view, so «nobody
    recorded it» and «it arrived empty» stay different answers.
    """
    payload = row.get("raw")
    if not isinstance(payload, (dict, list)) or not payload:
        return None
    return json.dumps(payload, ensure_ascii=False, default=str)


def save_sighting(conn: sqlite3.Connection, ts: int, command: str, verdict: str,
                  reason: str | None = None, rows_seen: int = 0, rows_kept: int = 0,
                  source: str = "wire", shape=None) -> None:
    """Write down that ``command`` was seen, and what became of it.

    THE SILENT DROP IS THE BUG THIS EXISTS FOR. The collector reads a reply, decides it
    is not a board — fewer than three rows, no uid, no name, a command on the
    not-a-ranking list — and says nothing at all, so a message that carries the very
    numbers somebody is looking for is indistinguishable from a message that never
    arrived. Every decision now lands here: what was seen, how many rows were in it,
    whether they were written, and WHICH test turned it away.

    ``shape`` is the row's field names and value types — never its values. It is what
    makes a rejection actionable («this reply had `day` and `score` and no `uid`»)
    without putting anybody's name or id in a table that outlives the run.
    """
    with _WRITE_LOCK:
        conn.execute(
            "INSERT INTO sightings (ts, command, source, verdict, reason, rows_seen, "
            "rows_kept, shape_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (int(ts), str(command), source, verdict, reason, int(rows_seen),
             int(rows_kept), json.dumps(shape, ensure_ascii=False, sort_keys=True)
             if shape else None))
        conn.commit()


def describe_shape(row) -> dict:
    """``{field: type}`` for one row — the shape, with not one value in it.

    Used for :func:`save_sighting`'s ``shape``. A nested dict or list is reported as its
    kind and length only, so a whole reply can be described without a single identifier
    of an account crossing into the store's own bookkeeping.
    """
    if not isinstance(row, dict):
        return {"_kind": type(row).__name__}
    out = {}
    for key, value in row.items():
        if isinstance(value, dict):
            out[str(key)] = f"dict[{len(value)}]"
        elif isinstance(value, list):
            out[str(key)] = f"list[{len(value)}]"
        else:
            out[str(key)] = type(value).__name__
    return out


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
