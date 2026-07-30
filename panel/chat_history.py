r"""Local SQLite store for captured chat history.

The chat monitor (``tools/chat_reader.py``) streams one record per message; the
panel writes each into this store and, at startup, reads only the newest page per
tab back out of it — older chunks page in on scroll. That keeps a long history off
the (slow) Text widget and off memory until the reader actually asks for it.

Schema (table ``messages``):

    id         INTEGER  primary key
    ts         REAL     message serverTime, epoch seconds (sort key)
    uid        TEXT     sender uid
    name       TEXT     sender display name
    text       TEXT     rendered message text
    room       TEXT     room id (country_* / alliance_* / custom_lang_* / *_v2)
    raw_json   TEXT     the whole record as captured (avatar fields, seq id, …)

``chat_type`` is stored alongside as an indexed helper so a tab can page its own
messages without re-deriving the bucket from ``room`` in SQL; it is redundant with
``raw_json`` and never read back from the row itself.

Single-threaded by construction: only the Tk thread writes (draining the reader
queue) and reads (startup / scroll), so one connection is enough.
"""
from __future__ import annotations

import json
import os
import sqlite3

# The per-tab bucket, derived from the room id exactly as tools/chat_reader.py does.
# Kept here too so a record that reaches the store without one (older raw_json) is
# still filed under the right tab.
def classify_room(room_id: str) -> str:
    if not room_id or room_id == "nil":
        return "other"
    if room_id.startswith("country_"):
        return "world"
    if room_id.startswith("custom_lang_"):
        return "national"
    if room_id.startswith("alliance_"):
        return "alliance"
    if room_id.endswith("_v2"):
        return "dm"
    return "other"


class ChatHistoryStore:
    """A thin SQLite wrapper: append a record, read the newest page, page older."""

    def __init__(self, db_path: str) -> None:
        self.path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # check_same_thread=False is defensive; access is single-threaded in practice.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS messages(
                   id        INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts        REAL,
                   uid       TEXT,
                   name      TEXT,
                   text      TEXT,
                   room      TEXT,
                   chat_type TEXT,
                   raw_json  TEXT)"""
        )
        # Fast per-tab paging by time.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_type_ts ON messages(chat_type, ts)")
        # A message is parsed once per (room, uid, ts, text) — the identity the
        # reader and the old JSONL loader dedupe on. A unique index makes the insert
        # idempotent, so re-importing or a double-write cannot duplicate a row.
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_identity "
            "ON messages(room, uid, ts, text)")
        self._conn.commit()

    # -- writing ------------------------------------------------------------
    def append(self, record: dict) -> None:
        """Insert one captured record (idempotent on its natural identity)."""
        room = str(record.get("room_id") or "")
        chat_type = record.get("chat_type") or classify_room(room)
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO messages(ts, uid, name, text, room, chat_type, raw_json) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (float(record.get("ts") or 0.0),
                 str(record.get("sender_uid") or ""),
                 str(record.get("sender_name") or ""),
                 str(record.get("msg") or ""),
                 room, chat_type,
                 json.dumps(record, ensure_ascii=False)),
            )
            self._conn.commit()
        except sqlite3.Error:
            # A store write must never take the live monitor down; a lost row is a
            # far smaller failure than a crashed panel.
            pass

    def import_jsonl(self, path: str) -> int:
        """One-time migration: fold an existing chat_log.jsonl into the store.

        Idempotent (the unique identity index drops repeats), so calling it again
        is harmless. Returns the number of rows the file contributed.
        """
        if not path or not os.path.isfile(path):
            return 0
        before = self.count()
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(rec, dict) and rec.get("room_id"):
                        self.append(rec)
        except OSError:
            return 0
        return self.count() - before

    # -- reading ------------------------------------------------------------
    def recent(self, chat_type: str, limit: int) -> list[dict]:
        """The newest ``limit`` records for a tab, oldest→newest (render order)."""
        rows = self._conn.execute(
            "SELECT raw_json FROM messages WHERE chat_type=? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (chat_type, int(limit)),
        ).fetchall()
        return [r for r in (_load(row[0]) for row in reversed(rows)) if r is not None]

    def older(self, chat_type: str, before_ts: float, limit: int) -> list[dict]:
        """Up to ``limit`` records for a tab strictly older than ``before_ts``.

        Oldest→newest, so a caller prepends them above what it already shows.
        """
        rows = self._conn.execute(
            "SELECT raw_json FROM messages WHERE chat_type=? AND ts<? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (chat_type, float(before_ts), int(limit)),
        ).fetchall()
        return [r for r in (_load(row[0]) for row in reversed(rows)) if r is not None]

    def has_older(self, chat_type: str, before_ts: float) -> bool:
        """Whether any record for a tab is older than ``before_ts``."""
        row = self._conn.execute(
            "SELECT 1 FROM messages WHERE chat_type=? AND ts<? LIMIT 1",
            (chat_type, float(before_ts)),
        ).fetchone()
        return row is not None

    def count(self, chat_type: str | None = None) -> int:
        if chat_type is None:
            row = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_type=?", (chat_type,)
            ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


def _load(raw: str) -> dict | None:
    try:
        rec = json.loads(raw)
        return rec if isinstance(rec, dict) else None
    except (TypeError, ValueError):
        return None
