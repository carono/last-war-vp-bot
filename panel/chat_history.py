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


def dm_peer_uid(room: str, self_uid: str = "") -> str:
    """The OTHER party's uid in a DM room `custom_<a>_<b>_v2`.

    A DM room id carries both participants' uids (uids are all-digit, so the split
    is unambiguous). With ``self_uid`` known, the peer is simply the uid that is not
    ours; without it we fall back to the first uid, which is the peer under the
    ``custom_<peer>_<self>_v2`` convention `chat_share.dm_room` builds.
    """
    room = str(room or "")
    if not (room.startswith("custom_") and room.endswith("_v2")):
        return ""
    mid = room[len("custom_"):-len("_v2")]
    parts = [p for p in mid.split("_") if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    a, b = parts[0], parts[-1]
    su = str(self_uid or "")
    if su and su == a:
        return b
    if su and su == b:
        return a
    return a


#: The schema's whole history, in order, the same discipline `panel/runtime/store.py`
#: holds `players` to (#1465): each entry is a sequence of statements that takes the
#: database from the version before it to this one, and a database carries how far it
#: has got in `PRAGMA user_version`. **Append only** — a migration that has shipped has
#: run on somebody's live profile, and editing it would leave two databases both calling
#: themselves version N with different columns in them. This module keeps its own
#: connection and its own tiny runner (:func:`_migrate`) rather than going through
#: `panel.runtime.store.Store`: a chat store is opened once per character on the Tk
#: thread and read back a page at a time, never batched or shared across processes the
#: way a profile's `panel.db` is, so the extra machinery buys nothing here — only the
#: DISCIPLINE (a numbered history, not an `IF NOT EXISTS` edited in place) is shared.
MIGRATIONS: tuple = (
    (
        """CREATE TABLE messages(
               id        INTEGER PRIMARY KEY AUTOINCREMENT,
               ts        REAL,
               uid       TEXT,
               name      TEXT,
               text      TEXT,
               room      TEXT,
               chat_type TEXT,
               raw_json  TEXT)""",
        # Fast per-tab paging by time.
        "CREATE INDEX idx_type_ts ON messages(chat_type, ts)",
        # A message is parsed once per (room, uid, ts, text) — the identity the reader
        # and the old JSONL loader dedupe on. A unique index makes the insert idempotent,
        # so re-importing or a double-write cannot duplicate a row.
        "CREATE UNIQUE INDEX idx_identity ON messages(room, uid, ts, text)",
    ),
)


def _migrate(conn: sqlite3.Connection, migrations: tuple = MIGRATIONS) -> None:
    """Bring `conn` from whatever `PRAGMA user_version` it is at up to `len(migrations)`.

    A database ahead of this code (a newer panel's) is left untouched — the same refusal
    `Store.connect` makes, for the same reason: running against a schema this code does
    not know would silently ignore a column a newer version filled.

    A file written by the code BEFORE this rule — `CREATE TABLE IF NOT EXISTS`, no
    `PRAGMA user_version` ever set — reads as version 0 like a brand new file, and
    running v1's `CREATE TABLE messages(...)` on it would fail on the table already
    being there. So a version-0 database with `messages` already in it is ADOPTED: it is
    marked version 1 without replaying the statement, exactly the shape #1465 found it
    in. Every live `chat_history_<uid>.db` goes through this exactly once.
    """
    have = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if have > len(migrations):
        raise RuntimeError(
            f"chat history at schema {have}, this panel only knows {len(migrations)} — "
            "update the panel before opening this profile's chat.")
    if have == 0 and conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
            ).fetchone() is not None:
        conn.execute("PRAGMA user_version = 1")
        have = 1
    for version, statements in enumerate(migrations[have:], start=have + 1):
        for stmt in statements:
            conn.execute(stmt)
        conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()


class ChatHistoryStore:
    """A thin SQLite wrapper: append a record, read the newest page, page older."""

    def __init__(self, db_path: str) -> None:
        self.path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # check_same_thread=False is defensive; access is single-threaded in practice.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        _migrate(self._conn)
        # Running total, so the panel can show "N messages" on every one-second
        # refresh without a COUNT(*) over the whole table each time. Filled on the
        # first read and kept up to date by the inserts below.
        self._total: int | None = None

    # -- writing ------------------------------------------------------------
    def _insert(self, record: dict) -> int:
        """Queue one record for insert (idempotent); the caller commits.

        Returns how many rows it actually added — 0 when the identity index has
        already seen this message — which is what keeps :meth:`total` honest.
        """
        room = str(record.get("room_id") or "")
        chat_type = record.get("chat_type") or classify_room(room)
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO messages(ts, uid, name, text, room, chat_type, raw_json) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (float(record.get("ts") or 0.0),
             str(record.get("sender_uid") or ""),
             str(record.get("sender_name") or ""),
             str(record.get("msg") or ""),
             room, chat_type,
             json.dumps(record, ensure_ascii=False)),
        )
        added = int(cur.rowcount or 0)
        if added and self._total is not None:
            self._total += added
        return added

    def append(self, record: dict) -> None:
        """Insert one captured record (idempotent on its natural identity)."""
        try:
            self._insert(record)
            self._conn.commit()
        except sqlite3.Error:
            # A store write must never take the live monitor down; a lost row is a
            # far smaller failure than a crashed panel.
            pass

    def import_jsonl(self, path: str) -> int:
        """One-time migration: fold an existing chat_log.jsonl into the store.

        Idempotent (the unique identity index drops repeats), so calling it again
        is harmless. One transaction for the whole file, so a large legacy log does
        not stall startup with a commit per line. Returns the rows it contributed.
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
                        try:
                            self._insert(rec)
                        except sqlite3.Error:
                            continue
            self._conn.commit()
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

    # -- one DM conversation (a single room) --------------------------------
    def recent_room(self, room: str, limit: int) -> list[dict]:
        """The newest ``limit`` records of one room, oldest→newest (render order)."""
        rows = self._conn.execute(
            "SELECT raw_json FROM messages WHERE room=? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (room, int(limit)),
        ).fetchall()
        return [r for r in (_load(row[0]) for row in reversed(rows)) if r is not None]

    def older_room(self, room: str, before_ts: float, limit: int) -> list[dict]:
        """Up to ``limit`` records of one room older than ``before_ts`` (oldest→newest)."""
        rows = self._conn.execute(
            "SELECT raw_json FROM messages WHERE room=? AND ts<? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (room, float(before_ts), int(limit)),
        ).fetchall()
        return [r for r in (_load(row[0]) for row in reversed(rows)) if r is not None]

    def has_older_room(self, room: str, before_ts: float) -> bool:
        """Whether any record of one room is older than ``before_ts``."""
        row = self._conn.execute(
            "SELECT 1 FROM messages WHERE room=? AND ts<? LIMIT 1",
            (room, float(before_ts)),
        ).fetchone()
        return row is not None

    # -- the DM contact list ------------------------------------------------
    def dm_contacts(self, self_uid: str = "") -> list[dict]:
        """One entry per DM peer, newest conversation first.

        Each entry is ``{room, peer_uid, name, head_pic_ver, last_text, last_ts,
        last_mine}``: enough to draw a contact row (avatar, name, last message,
        time) and to open the conversation. ``name``/``head_pic_ver`` come from the
        most recent message the PEER authored (so the avatar is theirs, not ours);
        with only our own outgoing messages the uid stands in for the name.
        """
        self_uid = str(self_uid or "")
        rooms = self._conn.execute(
            "SELECT room FROM messages WHERE chat_type='dm' GROUP BY room"
        ).fetchall()
        out: list[dict] = []
        for (room,) in rooms:
            last = self._conn.execute(
                "SELECT text, ts, uid FROM messages WHERE room=? "
                "ORDER BY ts DESC, id DESC LIMIT 1", (room,),
            ).fetchone()
            if last is None:
                continue
            last_text, last_ts, last_uid = last[0] or "", last[1] or 0, str(last[2] or "")
            peer = dm_peer_uid(room, self_uid)
            name, head_pic_ver = (peer or room), ""
            prow = self._conn.execute(
                "SELECT raw_json FROM messages WHERE room=? AND uid=? "
                "ORDER BY ts DESC, id DESC LIMIT 1", (room, peer),
            ).fetchone()
            if prow is not None:
                pr = _load(prow[0]) or {}
                name = pr.get("sender_name") or name
                head_pic_ver = pr.get("head_pic_ver") or ""
            out.append({
                "room": room, "peer_uid": peer, "name": name,
                "head_pic_ver": head_pic_ver, "last_text": last_text,
                "last_ts": last_ts, "last_mine": last_uid == self_uid,
            })
        out.sort(key=lambda c: c["last_ts"], reverse=True)
        return out

    def count(self, chat_type: str | None = None) -> int:
        if chat_type is None:
            row = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_type=?", (chat_type,)
            ).fetchone()
        return int(row[0]) if row else 0

    def total(self) -> int:
        """How many messages the store holds — counted once, then kept in step.

        The panel asks for this once a second to label the chat tab. As a plain
        :meth:`count` that was a full scan of a table that only ever grows, on the
        Tk thread, so the label got more expensive the longer the history got.
        """
        if self._total is None:
            self._total = self.count()
        return self._total

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
