"""THE ONE ENTRANCE to this profile's register of players (#1371).

## Why it is on the runtime and not on the tab

The register was born on the «Игроки» tab (#1335) and fed by one thing: the checkpoint
a lap of the map leaves behind. But a lap is not the only place the panel meets a
player. It meets them in the live block of banners, in the chat, in the alliance roster,
on a secret-task tile — every one of those readings already happens, is already paid
for, and was already being thrown away the moment the widget that drew it was redrawn.

So the store moves to where every one of them can reach it, and there is exactly ONE
call that writes:

    rt.players.sighted(records, source=SRC_CHAT)

Five copies of «open the file, merge, save» in five tabs is how two of them end up
disagreeing about what a lap may overwrite. There is one, it is here, and the rules
below are enforced in it rather than remembered by each caller.

## Nothing here asks the game anything. Ever.

**Every source is something the panel is ALREADY told**, and that is the whole bargain
(#1335): a sweep sees thousands of players and a per-player top-up would be thousands of
requests the game never asked for. A feeder passes on what it happened to hear while
doing its own job. A feeder that would have to SEND something to fill a field does not
fill that field; the field stays empty and the page says so.

## What each source is allowed to write

A source may only write the fields it can actually know — :data:`SOURCE_FIELDS`. That is
not bookkeeping, it is the guard the register needs most: the banner block reads a
`power` off every squad standing in a rally, and that is **the marching squad's** power,
not the player's. Merged onto `power` it would quietly overwrite a real profile reading
with a tenth of it. So the banner source may write `march_power` and cannot write
`power` however its records are spelled.

## An unknown never overwrites a known

A record carries what its source happened to see. Everything it does not mention is
dropped on the way in (`incoming`), so a chat line that knows a name and no coordinates
leaves the coordinates alone, and a tile that knows no power leaves an hour-old profile
reading standing. The same sentence as «an empty read removes nothing», one field down.

## Every field remembers where it came from and when

`row["src"]` is `{field: [source, unix seconds]}`. It is stamped when the VALUE CHANGES
(or arrives for the first time) and NOT on every re-confirmation, and that is a
measured decision rather than a shortcut: a lap re-lists four thousand unchanged players
every twenty seconds, and stamping those would rewrite a multi-megabyte file on every
tick for ever. So a field's stamp answers «since when has it been this, and who said
so», and «when was this row last confirmed at all» is `last_seen`, which is what the
table's «Виден» column has always shown.

## A row leaves for one reason and it is a person asking

It used to be inherited from the type underneath (`panel/kept.py`, which accepts
:data:`~panel.kept.PERSON_ASKED` and no other clause). The register is a table now
(#1398), so the invariant is stated here instead — and it is stated the same way:
**there is exactly ONE `DELETE` in this module**, in :meth:`PlayerBook.forget`, which is
what a person's «Забыть» calls. :meth:`PlayerBook.sighted` adds and updates and has no
branch that could remove anything, so a read that came back empty — a busy client, a
session that is not logged in, a lap that collected nothing — still takes nothing away.
`tests/test_players_registry.py` fails if a second `DELETE`, an `UPDATE … SET` over the
whole table, or a `clear()`-shaped method ever appears.

## The storage moved and the rules did not

`players.json` was 11.5 MB and 17 374 rows on a live profile; `panel/kept.py` rewrote
all of it on every change, which during a lap is almost every tick — 1.45 s a time. The
rows are in `panel.db` now (`panel/runtime/store.py`), the page narrows and sorts them
in SQL instead of building seventeen thousand dicts per keystroke, and the old file is
imported once and then kept beside the database as insurance.
"""
from __future__ import annotations

import json
import threading
import time

from . import store as store_mod

# ---------------------------------------------------------------------------
# who tells us about a player
# ---------------------------------------------------------------------------
#: A lap of the map — the base tiles a sweep drives over (`tools/lib/world_index.py`).
SRC_MAP = "map"
#: A `get.user.info.multi` reply: the person opened a base in the game, or the client
#: fetched the alliance roster at login. The only place a combat number comes from.
SRC_PROFILE = "profile"
#: The note THIS ACCOUNT has written on that player, as the game holds it.
SRC_REMARK = "remark"
#: The live block of banners — who is standing in a rally right now (#1324).
SRC_RALLY = "rally"
#: A chat message: whoever said it.
SRC_CHAT = "chat"
#: The alliance roster the «Альянс» tab reads.
SRC_ALLIANCE = "alliance"
#: The owner of a tile — a secret task, a ghost-recon point, a mine.
SRC_TILE = "tile"
#: The person at the panel. The only source that may write `note`.
SRC_PERSON = "person"

#: Every source, so a UI can list them and a test can walk them.
SOURCES = (SRC_MAP, SRC_PROFILE, SRC_REMARK, SRC_RALLY, SRC_CHAT, SRC_ALLIANCE,
           SRC_TILE, SRC_PERSON)

# ---------------------------------------------------------------------------
# what a row can hold
# ---------------------------------------------------------------------------
#: The fields a register row can hold. Anything else a feeder carries is dropped on the
#: way in — a store that quietly grew a column would be a store nobody could review.
FIELDS = (
    "uid", "name", "level", "server_id", "x", "y", "uuid", "country",
    "alliance_id", "alliance_abbr", "alliance_name",
    "power", "army_power", "army_kill", "svip_level",
    "head", "march_power", "online",
    "remark", "note", "first_seen", "last_seen", "profile_seen_at", "src",
)

#: The two the register keeps for itself, and the provenance map. No source writes them.
OWN_FIELDS = frozenset({"first_seen", "last_seen", "src"})

#: What a base tile carries. Measured over one recorded whole-server lap of 6 723 of
#: them: the first eight on every single tile, the alliance's uuid and tag on the
#: quarter of players who are in one.
MAP_FIELDS = frozenset({"uid", "name", "level", "server_id", "x", "y", "uuid",
                        "country", "alliance_id", "alliance_abbr", "alliance_name"})

#: …and what ONLY a profile reply carries.
PROFILE_FIELDS = frozenset({"power", "army_power", "army_kill", "svip_level",
                            "profile_seen_at"})

#: Which fields each source may write. A source that hands over anything else has that
#: field dropped — see the module docstring: the banner block's `power` is a SQUAD's.
SOURCE_FIELDS = {
    # The map sweep's checkpoint is not only tiles: the capture folds a profile reply
    # and the account's own notes onto the rows it keeps (`tools/lib/world_index.py`),
    # so the source that reads that file may carry all three. Which is which is said by
    # `field_source` (:data:`CHECKPOINT_SOURCES`) rather than by dropping the fields.
    SRC_MAP: MAP_FIELDS | PROFILE_FIELDS | {"remark"},
    SRC_PROFILE: MAP_FIELDS | PROFILE_FIELDS,
    SRC_REMARK: frozenset({"uid", "remark"}),
    SRC_RALLY: frozenset({"uid", "name", "head", "march_power", "server_id"}),
    SRC_CHAT: frozenset({"uid", "name", "alliance_abbr", "server_id", "head"}),
    SRC_ALLIANCE: frozenset({"uid", "name", "level", "power", "online",
                             "alliance_abbr", "alliance_name"}),
    # NO COORDINATE. A tile with an owner — a secret task, a ghost-recon point, a truck
    # on the road — is somewhere out on the map, nowhere near that player's base, so
    # its position says where their TASK is and nothing about where they live. Writing
    # it would move everybody in the alliance onto their own dispatch points.
    SRC_TILE: frozenset({"uid", "name", "server_id", "alliance_abbr", "alliance_id",
                         "country"}),
    SRC_PERSON: frozenset({"uid", "note"}),
}

#: The map checkpoint is three sources in one file — the tile, the profile reply folded
#: onto it and the account's own note — so its fields are attributed one by one instead
#: of all being called «карта». Handed to `sighted` as `field_source`.
CHECKPOINT_SOURCES = dict(
    {field: SRC_PROFILE for field in PROFILE_FIELDS},
    remark=SRC_REMARK,
)


def incoming(record: dict, source: str, now: float) -> dict:
    """One record as the register takes it — empties dropped, stamped, sieved.

    `seen_at` on a feeder's side means «this source confirmed the player just now»,
    which is exactly what `last_seen` means here, so it is renamed rather than kept
    twice under two names that would drift.
    """
    allowed = SOURCE_FIELDS.get(source) or frozenset()
    out = {}
    for field, value in record.items():
        if field not in FIELDS or field in OWN_FIELDS or field not in allowed:
            continue
        # Zero is a real level and a real coordinate; only None is «did not say».
        if value is None or value == "":
            continue
        out[field] = value
    if out.get("uid") is None:
        return {}
    out["uid"] = str(out["uid"])
    out["last_seen"] = int(record.get("seen_at") or now)
    return out


# ---------------------------------------------------------------------------
# the row as the database holds it
# ---------------------------------------------------------------------------
#: The columns of `players`, in the order the table declares them (`store.MIGRATIONS`,
#: v2). Everything a source may write, plus the three the register keeps for itself.
COLUMNS = (
    "uid", "name", "level", "server_id", "x", "y", "uuid", "country",
    "alliance_id", "alliance_abbr", "alliance_name",
    "power", "army_power", "army_kill", "svip_level",
    "head", "march_power", "online",
    "remark", "note", "first_seen", "last_seen", "profile_seen_at", "src",
)

#: Written with every row and never by hand: the case-folded haystack the text box
#: searches and the case-folded keys the table sorts by. They exist because SQLite's own
#: `LOWER()` is ASCII-only, and most of this register is not — a Cyrillic nickname would
#: match and sort by its raw code points, so «поиск не находит» for half the players.
DERIVED = ("search_text", "name_fold", "alliance_fold", "note_fold")


def _fold(value) -> str:
    return str(value or "").casefold()


def search_text_of(row: dict) -> str:
    """Everything one row can be searched BY, as one case-folded haystack.

    The name, both spellings of the alliance, both notes, and the coordinate the way a
    person types it — «612,480» — so one box answers the searches the page promises
    instead of three boxes each answering one. The same sentence as
    `panel/tabs/players/registry.py::_text_of`, and `tests/test_players_registry.py`
    fails if the two ever stop agreeing.
    """
    bits = [row.get("name") or "", row.get("alliance_abbr") or "",
            row.get("alliance_name") or "", row.get("note") or "",
            row.get("remark") or ""]
    if row.get("x") is not None and row.get("y") is not None:
        bits.append("%s,%s" % (row["x"], row["y"]))
    return " ".join(bits).casefold()


def _derived_of(row: dict) -> dict:
    return {"search_text": search_text_of(row),
            "name_fold": _fold(row.get("name")),
            "alliance_fold": _fold(row.get("alliance_abbr")),
            "note_fold": _fold(row.get("note"))}


def row_of(record) -> dict:
    """One database row as the rest of the panel expects a register row to look.

    `src` comes back out of its JSON, and the derived columns are dropped — they are
    the database's business and nothing outside this module has ever seen them.

    An empty field is kept as `None` rather than left out. Both readings are defensible
    and only one of them is what the callers were written against: `set_note(uid, None)`
    clears a mark, and a page that then reads `row["note"]` to draw the empty box has to
    find the key there.
    """
    row = {key: record[key] for key in COLUMNS if key in record.keys()}
    raw = row.get("src")
    if isinstance(raw, str):
        try:
            row["src"] = json.loads(raw)
        except ValueError:
            row["src"] = {}
    return row


# ---------------------------------------------------------------------------
# what a filter means, in SQL
# ---------------------------------------------------------------------------
#: Which column each sort key orders by, and the tie-break every one of them ends with:
#: without it two players of the same level swap places on every repaint, which reads as
#: a table that will not sit still. The same list as
#: `panel/tabs/players/registry.py::SORT_KEYS`, said in SQL.
SORT_COLUMNS = {
    "name": ("name_fold",),
    "level": ("COALESCE(level, 0)",),
    "power": ("COALESCE(power, 0)",),
    "alliance": ("alliance_fold",),
    "coords": ("COALESCE(x, 0)", "COALESCE(y, 0)"),
    "server": ("COALESCE(server_id, 0)",),
    "seen": ("COALESCE(last_seen, 0)",),
    "note": ("note_fold",),
}

#: What the table opens on before anybody clicks a heading.
DEFAULT_SORT = ("seen", True)


def where_of(f: dict, now: float) -> tuple:
    """One filter as `(sql, params)` — the WHERE of every read the page makes.

    **This is the same filter as `panel/tabs/players/registry.py::matches`, said twice
    on purpose.** That one is the readable definition, walks one row and is what a test
    can be argued with; this one is what seventeen thousand rows can afford. Two
    definitions of one thing is a debt, so it is paid the only way that works:
    `tests/test_players_registry.py` runs both over the same rows and the same filters
    and fails on the first disagreement.
    """
    from ..tabs.players import registry as reg          # the windows the «виден» box has
    clauses: list = []
    params: list = []

    text = (f.get("text") or "").strip().casefold()
    if text:
        clauses.append("search_text LIKE ? ESCAPE '\\'")
        params.append("%" + text.replace("\\", "\\\\").replace("%", "\\%")
                      .replace("_", "\\_") + "%")

    for column, low, high in (("level", f.get("level_min"), f.get("level_max")),
                              ("power", f.get("power_min"), f.get("power_max"))):
        # An unknown level is not «below the minimum», it is unknown — and a row with
        # no reading must not pass a bound it was never measured against.
        if low is not None:
            clauses.append(f"({column} IS NOT NULL AND {column} >= ?)")
            params.append(low)
        if high is not None:
            clauses.append(f"({column} IS NOT NULL AND {column} <= ?)")
            params.append(high)

    tag = (f.get("alliance") or "").strip().casefold()
    if tag:
        clauses.append("alliance_fold = ?")
        params.append(tag)

    server = str(f.get("server") or "").strip()
    if server:
        clauses.append("CAST(server_id AS TEXT) = ?")
        params.append(server)

    box = f.get("rect")
    if box:
        x1, y1, x2, y2 = box
        clauses.append("(x IS NOT NULL AND y IS NOT NULL AND x BETWEEN ? AND ? "
                       "AND y BETWEEN ? AND ?)")
        params += [min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)]
    circle = f.get("circle")
    if circle:
        cx, cy, radius = circle
        # Chebyshev, not Euclidean: the map is a grid of squares and «в пределах 20
        # клеток» is how a person reads a march range off it.
        clauses.append("(x IS NOT NULL AND y IS NOT NULL "
                       "AND MAX(ABS(x - ?), ABS(y - ?)) <= ?)")
        params += [cx, cy, radius]

    seen = f.get("seen") or "any"
    if seen == "stale":
        clauses.append("COALESCE(last_seen, 0) <= ?")
        params.append(now - reg.STALE_AFTER_SEC)
    elif seen != "any":
        window = reg.SEEN_WINDOWS.get(seen)
        if window is not None:
            clauses.append("COALESCE(last_seen, 0) >= ?")
            params.append(now - window)

    if f.get("noted"):
        clauses.append("TRIM(COALESCE(note, '')) <> ''")

    return (" AND ".join(clauses) if clauses else "1", params)


def order_of(sort=None) -> str:
    """One sort as an ORDER BY — the same columns and tie-break as `registry.SORT_KEYS`."""
    column, down = sort or DEFAULT_SORT
    columns = SORT_COLUMNS.get(column) or SORT_COLUMNS[DEFAULT_SORT[0]]
    way = "DESC" if down else "ASC"
    return ", ".join(f"{c} {way}" for c in columns) + f", uid {way}"


class PlayerBook:
    """Everyone this profile has met, however it met them, kept for good.

    Backed by this profile's database (`panel/runtime/store.py`, #1398) — it used to be
    a `panel/kept.py` list in `players.json`, and on a live profile that had become
    11.5 MB rewritten from scratch on almost every tick of a lap. **The rules did not
    change with the storage, and that is the point of them being written here rather
    than in the file format:**

    * :meth:`sighted` adds and updates and **never removes**, whatever the read was
      missing — an empty read merges nothing and takes nothing away;
    * a source may only write the fields it can actually know (:data:`SOURCE_FIELDS`);
    * an unknown never overwrites a known;
    * and a row leaves for ONE reason, which is a person asking (:meth:`forget`).
      There is exactly one `DELETE` in this module and `tests/test_players_registry.py`
      fails if a second one appears.
    """

    def __init__(self, store, legacy_path: str = "") -> None:
        self.store = store
        #: `players.json` as it was, so the first run can bring it in. Kept beside the
        #: database afterwards (`store.import_once`), never deleted.
        self.legacy_path = legacy_path
        # Feeders run on their own threads — a capture's reader, the banner block's
        # read, the chat poll. The database is safe for all of them by itself (WAL, one
        # connection per thread); this serialises the READ-COMPARE-WRITE of a merge,
        # which is what makes «an unknown never overwrites a known» hold when two
        # sources report one player at the same moment.
        self._lock = threading.RLock()
        self._imported = False

    # -- the one-time move out of players.json ---------------------------------------
    def ensure_imported(self) -> int:
        """Bring `players.json` in, once, without losing a row. Returns how many.

        Runs on whatever thread asks first; the panel warms it on its boot thread so the
        window never pays for it (`panel/runtime/host.py::_warm`). Everything about
        «once, and never over a later edit» is `store.import_once`.
        """
        with self._lock:
            if self._imported:
                return 0
            self._imported = True
            if not self.legacy_path:
                return 0
            return store_mod.import_once(self.store, "players", self.legacy_path,
                                         _load_legacy, self._insert_many)

    def _ready(self):
        if not self._imported:
            self.ensure_imported()
        return self.store

    @staticmethod
    def _insert_many(conn, rows) -> int:
        """Write whole rows, for the import only. Not a merge — see :meth:`sighted`."""
        payload = []
        for row in rows:
            if not isinstance(row, dict) or row.get("uid") is None:
                continue
            row = dict(row)
            row["uid"] = str(row["uid"])
            payload.append(_values_of(row))
        conn.executemany(_INSERT_SQL, payload)
        return len(payload)

    # -- reading ---------------------------------------------------------------------
    def rows(self) -> list:
        """Every row. **Whole-table reads are for a test and for nothing else** — the
        page asks :meth:`search`, which narrows and sorts in the database."""
        return [row_of(r) for r in
                self._ready().read().execute("SELECT * FROM players")]

    def search(self, f: dict | None = None, sort=None, limit: int | None = None,
               now: float | None = None) -> list:
        """The rows a filter keeps, sorted, at most `limit` of them — **in SQL**.

        This is what the table draws from. It used to be `apply_filter(book.rows())`
        followed by `sort_rows`, which on a live register meant seventeen thousand dicts
        built, walked and sorted in Python for every keystroke in the search box.
        """
        where, params = where_of(f or {}, time.time() if now is None else now)
        sql = f"SELECT * FROM players WHERE {where} ORDER BY {order_of(sort)}"
        if limit is not None:
            sql += " LIMIT ?"
            params = list(params) + [int(limit)]
        return [row_of(r) for r in self._ready().read().execute(sql, params)]

    def count(self, f: dict | None = None, now: float | None = None) -> int:
        """How many rows a filter keeps — without building one of them."""
        where, params = where_of(f or {}, time.time() if now is None else now)
        return int(self._ready().read().execute(
            f"SELECT COUNT(*) c FROM players WHERE {where}", params).fetchone()["c"])

    def get(self, uid) -> dict | None:
        row = self._ready().read().execute(
            "SELECT * FROM players WHERE uid = ?", (str(uid),)).fetchone()
        return None if row is None else row_of(row)

    def __len__(self) -> int:
        return int(self._ready().read().execute(
            "SELECT COUNT(*) c FROM players").fetchone()["c"])

    # -- THE ONE WRITE ---------------------------------------------------------------
    def sighted(self, records, source: str, now: float | None = None,
                field_source: dict | None = None) -> int:
        """Merge what one source has just seen. **Adds and updates; never removes.**

        `field_source` names a different source for particular fields — the map
        checkpoint uses it because the file it writes is three sources in one
        (:data:`CHECKPOINT_SOURCES`).

        Returns how many rows were added or changed, so a caller can say «the lap
        brought 412 new faces» rather than «something happened».

        One SELECT for everything this batch mentions and one statement to write it
        back: a lap hands over four thousand rows at a time, and a round trip per row is
        what made the file version cost a second and a half.
        """
        if source not in SOURCE_FIELDS:
            raise ValueError(
                f"{source!r} is not a source. The register's sources are {SOURCES} — "
                f"add yours there, with the fields it is allowed to write, rather "
                f"than here.")
        now = time.time() if now is None else now
        incoming_rows = []
        for record in records or ():
            if not isinstance(record, dict):
                continue
            row = incoming(record, source, now)
            if row:
                incoming_rows.append(row)
        if not incoming_rows:
            # AND THAT IS THE WHOLE OF «an empty read removes nothing»: there is no
            # branch below this that could delete anything, and none above it either.
            return 0
        with self._lock:
            store = self._ready()
            held = self._held({row["uid"] for row in incoming_rows})
            merged = []
            for row in incoming_rows:
                record = held.get(row["uid"])
                # THE COMMON CASE IS «nothing has changed», and it is common by a long
                # way: a capture re-lists every tile it can see every fifteen seconds,
                # so a lap over an unchanged map is four thousand rows that all end at
                # the `continue` below. It is therefore compared against the raw
                # `sqlite3.Row` — indexable by column name — and the dict is built only
                # for the rows that actually moved. Measured on the live register: 137 ms
                # to build four thousand dicts, 21 ms not to.
                if record is not None and all(record[f] == v for f, v in row.items()
                                              if f != "src"):
                    continue
                was = None if record is None else row_of(record)
                if was is None:
                    # `first_seen` is written once and never again.
                    row = dict(row, first_seen=row["last_seen"])
                elif all(was.get(f) == v for f, v in row.items()):
                    # NOTHING NEW ABOUT THIS PLAYER, so nothing is written. A checkpoint
                    # re-lists the same sighting every tick for as long as it is fresh
                    # (#1335): without this the panel said «карта добавила или обновила
                    # 103» every twenty seconds, over a map on which nothing had moved.
                    continue
                row["src"] = self._provenance(was, row, source, field_source, now)
                # An unknown never overwrites a known: what this source did not mention
                # is taken from the row already held, not left NULL.
                merged.append(dict(was or {}, **row))
            if not merged:
                return 0
            with store.write() as conn:
                conn.executemany(_INSERT_SQL, [_values_of(r) for r in merged])
            return len(merged)

    def _held(self, uids: set) -> dict:
        """The rows this batch is about, in as few statements as SQLite will take.

        999 is SQLite's own ceiling on host parameters in the versions this has to run
        on; a lap of four thousand players is therefore five statements rather than four
        thousand.
        """
        out: dict = {}
        conn = self.store.read()
        keys = list(uids)
        for start in range(0, len(keys), 900):
            chunk = keys[start:start + 900]
            marks = ",".join("?" * len(chunk))
            for record in conn.execute(
                    f"SELECT * FROM players WHERE uid IN ({marks})", chunk):
                # The raw row, NOT a dict — see :meth:`sighted` for why.
                out[record["uid"]] = record
        return out

    @staticmethod
    def _provenance(held, row: dict, source: str, field_source, now: float) -> dict:
        """The row's `src` map after this sighting.

        Stamped for a field whose VALUE CHANGED or which is new, and left alone for one
        merely re-confirmed — see the module docstring: stamping every confirmation
        would rewrite the whole register on every tick of every lap.
        """
        src = dict((held or {}).get("src") or {})
        stamp = int(now)
        for field, value in row.items():
            if field in OWN_FIELDS or field == "uid":
                continue
            if held is not None and held.get(field) == value:
                continue
            who = (field_source or {}).get(field) or source
            src[field] = [who, stamp]
        return src

    # -- what a person writes --------------------------------------------------------
    def set_note(self, uid, text: str | None) -> bool:
        """Write (or clear) THIS PROFILE's own mark on a player.

        A mark on a player the register has never heard of is refused rather than
        filed: a row with a note and no name is not a player, and the press that could
        make one is a bug somewhere else.
        """
        with self._lock:
            held = self.get(uid)
            if held is None:
                return False
            text = (text or "").strip() or None
            src = dict(held.get("src") or {})
            src["note"] = [SRC_PERSON, int(time.time())]
            row = dict(held, uid=str(uid), note=text, src=src)
            with self.store.write() as conn:
                conn.execute(_INSERT_SQL, _values_of(row))
            return True

    def forget(self, uid) -> bool:
        """THE ONE WAY A ROW LEAVES — a person asked (:data:`~panel.kept.PERSON_ASKED`).

        The only `DELETE` in this module, and it is here because a person pressed
        «Забыть». A read that came back empty, a lap that collected nothing, a client
        that was not logged in: none of them reaches this call, and none of them has a
        way to. `tests/test_players_registry.py` fails on a second one appearing.
        """
        with self._lock:
            store = self._ready()
            with store.write() as conn:
                cur = conn.execute("DELETE FROM players WHERE uid = ?", (str(uid),))
            return bool(cur.rowcount)

    # -- what the page tells about itself --------------------------------------------
    def alliances(self) -> list:
        """Every alliance tag in the register, once each, in alphabetical order."""
        return [r["alliance_abbr"] for r in self._ready().read().execute(
            "SELECT DISTINCT alliance_abbr FROM players "
            "WHERE TRIM(COALESCE(alliance_abbr, '')) <> '' ORDER BY alliance_fold")]

    def servers(self) -> list:
        """Every server number in the register, ascending."""
        return [r["server_id"] for r in self._ready().read().execute(
            "SELECT DISTINCT server_id FROM players "
            "WHERE server_id IS NOT NULL ORDER BY server_id")]


#: One upsert, used by every write here — the import, a merge and a person's note alike.
#: `ON CONFLICT … DO UPDATE` rather than `INSERT OR REPLACE`, because REPLACE deletes
#: the old row first and a register whose writes are deletes-and-inserts is one `ON
#: DELETE` away from being a register that loses rows.
_ALL_COLUMNS = COLUMNS + DERIVED
_INSERT_SQL = (
    "INSERT INTO players(" + ", ".join(_ALL_COLUMNS) + ") "
    "VALUES(" + ", ".join("?" * len(_ALL_COLUMNS)) + ") "
    "ON CONFLICT(uid) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in _ALL_COLUMNS if c != "uid")
)


def _values_of(row: dict) -> tuple:
    """One row as the parameters of :data:`_INSERT_SQL`."""
    full = dict(row, **_derived_of(row))
    out = []
    for column in _ALL_COLUMNS:
        value = full.get(column)
        if column == "src":
            value = json.dumps(value or {}, ensure_ascii=False)
        elif isinstance(value, bool):
            value = int(value)
        out.append(value)
    return tuple(out)


def _load_legacy(path: str):
    """`players.json` as it was written by `panel/kept.py` — a list of row dicts.

    `None` for a file that is not there or cannot be read, which
    :func:`~panel.runtime.store.import_once` treats as «nothing happened» rather than as
    «imported, and it was empty». The difference matters exactly once, and that once is
    a profile whose file is momentarily locked while the panel starts.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def provenance_of(row: dict) -> list:
    """One row as `(field, value, source, when)`, freshest first — for both front-ends.

    The window's «Подробно» dialog and the phone's detail card are the same list said
    twice, so it is built once and here. A field with no stamp — everything written
    before this existed — is reported with an empty source rather than a guessed one.
    """
    src = row.get("src") or {}
    out = []
    for field in FIELDS:
        if field in OWN_FIELDS or field == "uid":
            continue
        value = row.get(field)
        if value is None or value == "":
            continue
        who, when = (src.get(field) or ["", 0])[:2]
        out.append((field, value, who or "", float(when or 0)))
    out.sort(key=lambda item: (-item[3], item[0]))
    return out
