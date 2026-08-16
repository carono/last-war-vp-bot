r"""THE ONE DOOR to this profile's database (#1398).

## Why there is one

Everything the panel remembers is a file in the profile directory, and most of those
files are a whole list rewritten from scratch on every change. That is fine for the
small ones and it is measurably not fine for the register of players: on a live profile
it is 11.5 MB and 17 374 rows, `json.load` takes 0.97 s, `json.dump` takes 1.45 s, and a
lap of the map changes something on almost every tick — so the panel spent a second and
a half rewriting the same eleven megabytes every twenty seconds, and the «Игроки» page
loaded all of it into memory to filter and sort it in Python.

So the data goes into SQLite. **One database per PROFILE**, in that profile's own
directory, because a profile is a whole panel of its own and its register, its ★ tiles
and its counters are an ACCOUNT's — never the window's and never «the first profile that
opened». There is no module-level connection here and no module-level store: a caller
asks the runtime (`rt.store`), and the runtime hands it the one belonging to the profile
it is running.

## Why it is not `sqlite3.connect` at each call site

Because the two databases that predate this rule (`chat_history_<uid>.db`,
`leaderboard_history.db`) each bake their own `CREATE TABLE IF NOT EXISTS` into the code
that uses them, which means the schema is whatever the last person to edit that file
believed, there is no version, and changing a column is an archaeology exercise. A
schema with versions and migrations is the difference between «the table is what the
code says today» and «the table is what every version of the code since the first one
has agreed to».

So: :data:`MIGRATIONS` is the whole history of the schema, in order, and a database
carries how far it has got in `PRAGMA user_version`. Adding a column is appending a
migration — never editing one that has shipped, and never a `CREATE TABLE` written
somewhere else.

## Several threads, and several processes

Both are real and neither is theoretical. The panel writes from the capture reader's
thread, the banner block's thread, the chat poll and the Tk thread; a standalone tab
(`python -m panel.tabs.players`) is a SECOND PROCESS on the same profile directory, and
so is any tool pointed at it.

What answers that:

* **WAL** (`journal_mode=WAL`) — readers never block the writer and the writer never
  blocks readers, across processes as well as threads. The alternative (the rollback
  journal) locks the whole database for the length of a write, which is exactly the
  freeze this change exists to remove.
* **A busy timeout** (:data:`BUSY_TIMEOUT_MS`) — a second writer waits rather than
  raising «database is locked» at whoever happened to press first.
* **Short transactions.** :meth:`Store.write` is a context manager around
  `BEGIN IMMEDIATE … COMMIT`, and the rule for what goes inside it is: statements, and
  nothing that reads a widget, waits on the game or sleeps. A transaction held open
  across a game read is a lock held for a second and a half, which is the freeze again
  wearing a different hat.
* **One connection per thread**, kept in thread-local storage. A `sqlite3.Connection`
  may not be shared between threads, and `check_same_thread=False` plus a lock is the
  same thing with the contention put back by hand.

## Nothing here writes on the Tk thread

:meth:`Store.submit` hands a callable to this store's single writer thread, and that
thread drains **everything queued into ONE transaction**. A sweep that sees four
thousand players is one commit, not four thousand — which is the second half of the
measurement above: the cost was never the rows, it was doing the whole file per change.

A caller that is already on a background thread may use :meth:`Store.write` directly.
A caller on the Tk thread must not.

## What lives in the database, and what deliberately does not

The inventory is in `docs/panel-storage.md`. In one line: the DATA does (the register,
the ★ list, the counters, the tallies), and the SETTINGS do not (`config.json`, the
timer and trigger catalogues, `rally_limits.json`, `timers_seen.json`) — a person edits
those by hand and «copy the folder and your panel comes with you» has to keep meaning
something. Nor do the logs, the locks, the heartbeat, or the checkpoints a capture CHILD
writes for the panel to read: those are a channel between two processes, rewritten whole
every fifteen seconds, and worth nothing after a restart.
"""
from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager

#: The file inside the profile directory. One per profile, never one per window.
DB_FILE = "panel.db"

#: How long a writer waits for another writer before giving up. Generous on purpose:
#: the competing writer is another thread of this panel, or a standalone tab in another
#: process, and both finish in milliseconds. A person seeing «database is locked»
#: because two of our own threads met is a bug report about nothing.
BUSY_TIMEOUT_MS = 15_000

#: The Python-side timeout, in seconds. Belt and braces with the pragma above — the
#: pragma governs the retry loop inside SQLite, this one governs `connect`.
CONNECT_TIMEOUT = BUSY_TIMEOUT_MS / 1000.0

#: How long the writer waits for company before committing what it already has. Ten
#: milliseconds is below anything a person can see and above the gap between two rows
#: of the same burst — a lap of the map submits thousands in a tight loop, and without a
#: window the writer keeps up with them one transaction at a time, which is the per-row
#: cost this layer was built to remove.
BATCH_LINGER = 0.01

#: …and the ceiling on one transaction, so a producer that never stops cannot hold the
#: write lock open indefinitely against the other profile-mates and processes.
BATCH_MAX = 2_000


# ---------------------------------------------------------------------------
# the schema, as a history rather than as a statement
# ---------------------------------------------------------------------------
#: Every version of the schema, in order, each one a SEQUENCE OF STATEMENTS that takes
#: the database from the version before it to this one. **Append only.** A migration
#: that has shipped has run on somebody's live profile, and editing it would leave two
#: databases both calling themselves version N with different columns in them.
#:
#: Index 0 is version 1, index 1 is version 2, and so on; the database's own
#: `PRAGMA user_version` says how many of them it has had.
#:
#: A sequence of statements rather than one script, because `executescript` COMMITS
#: whatever transaction is open before it runs — which would drop the write lock this
#: migration is holding precisely so that two panels opening one profile cannot both
#: decide the schema is missing.
MIGRATIONS: tuple = (
    # -- v1: the bookkeeping every later version leans on ---------------------------
    (
        """CREATE TABLE meta (
               key   TEXT PRIMARY KEY,
               value TEXT NOT NULL
           )""",
    ),
    # -- v2: the register of players (`panel/runtime/players.py`, was players.json) --
    (
        """CREATE TABLE players (
               uid             TEXT PRIMARY KEY,
               name            TEXT,
               level           INTEGER,
               server_id       INTEGER,
               x               INTEGER,
               y               INTEGER,
               -- NO TYPE, and that is deliberate: a tile's uuid arrives as an integer
               -- and other sources spell one as text, and a TEXT column would quietly
               -- store 111 as '111' — so the row read back would differ from the row
               -- just written, every sighting would look like news, and the register
               -- would rewrite itself on every tick of a lap. BLOB affinity keeps a
               -- value exactly as it was handed over.
               uuid,
               country         TEXT,
               alliance_id     TEXT,
               alliance_abbr   TEXT,
               alliance_name   TEXT,
               power           INTEGER,
               army_power      INTEGER,
               army_kill       INTEGER,
               svip_level      INTEGER,
               head            TEXT,
               march_power     INTEGER,
               online          INTEGER,
               remark          TEXT,
               note            TEXT,
               first_seen      INTEGER,
               last_seen       INTEGER,
               profile_seen_at INTEGER,
               -- The provenance map, `{field: [source, when]}`. JSON because it is read
               -- for ONE row at a time (the detail card) and never searched by.
               src             TEXT,
               -- Derived, written with the row and never by hand: the case-folded
               -- haystack the text box searches, and the case-folded sort keys. SQLite's
               -- own LOWER() is ASCII-only, so a Cyrillic nickname would sort and match
               -- by its raw code points — which is most of this register.
               search_text     TEXT,
               name_fold       TEXT,
               alliance_fold   TEXT,
               note_fold       TEXT
           )""",
        # What the page actually orders and narrows by. `last_seen` first because the
        # table opens on it (the freshest sighting), and every sort ends on `uid`.
        "CREATE INDEX ix_players_last_seen ON players(last_seen)",
        "CREATE INDEX ix_players_name      ON players(name_fold)",
        "CREATE INDEX ix_players_alliance  ON players(alliance_fold)",
        "CREATE INDEX ix_players_server    ON players(server_id)",
        "CREATE INDEX ix_players_level     ON players(level)",
        "CREATE INDEX ix_players_power     ON players(power)",
    ),
    # -- v3: repair the two shapes v2 shipped in -------------------------------------
    #
    # THIS IS THE RULE ABOVE, DEMONSTRATED. v2 was written with `uuid TEXT`, run on a
    # live profile, then corrected to a typeless column and run on another — and an hour
    # later there were two databases both calling themselves version 2, one storing a
    # tile's uuid as the integer it arrived as and one silently converting it to text.
    # That is not cosmetic: the merge compares what it just read against what is held,
    # so 111 never equals '111', every sighting looks like news, and the register
    # rewrites those rows on every tick of every lap — the exact cost the move was made
    # to remove.
    #
    # The repair is a new version rather than another edit, because that is the only
    # thing that can reach a database which has already run the wrong one. It rebuilds
    # the table with the intended column and carries an all-digit text uuid back to the
    # integer it was; a database that was already right is rebuilt into the same shape,
    # which costs one pass and settles the question for both.
    (
        "ALTER TABLE players RENAME TO players_v2",
        """CREATE TABLE players (
               uid             TEXT PRIMARY KEY,
               name            TEXT,
               level           INTEGER,
               server_id       INTEGER,
               x               INTEGER,
               y               INTEGER,
               uuid,
               country         TEXT,
               alliance_id     TEXT,
               alliance_abbr   TEXT,
               alliance_name   TEXT,
               power           INTEGER,
               army_power      INTEGER,
               army_kill       INTEGER,
               svip_level      INTEGER,
               head            TEXT,
               march_power     INTEGER,
               online          INTEGER,
               remark          TEXT,
               note            TEXT,
               first_seen      INTEGER,
               last_seen       INTEGER,
               profile_seen_at INTEGER,
               src             TEXT,
               search_text     TEXT,
               name_fold       TEXT,
               alliance_fold   TEXT,
               note_fold       TEXT
           )""",
        """INSERT INTO players
           SELECT uid, name, level, server_id, x, y,
                  CASE WHEN uuid IS NULL THEN NULL
                       WHEN typeof(uuid) = 'text' AND uuid <> ''
                            AND uuid NOT GLOB '*[^0-9]*' THEN CAST(uuid AS INTEGER)
                       ELSE uuid END,
                  country, alliance_id, alliance_abbr, alliance_name,
                  power, army_power, army_kill, svip_level,
                  head, march_power, online, remark, note,
                  first_seen, last_seen, profile_seen_at, src,
                  search_text, name_fold, alliance_fold, note_fold
             FROM players_v2""",
        "DROP TABLE players_v2",
        "CREATE INDEX ix_players_last_seen ON players(last_seen)",
        "CREATE INDEX ix_players_name      ON players(name_fold)",
        "CREATE INDEX ix_players_alliance  ON players(alliance_fold)",
        "CREATE INDEX ix_players_server    ON players(server_id)",
        "CREATE INDEX ix_players_level     ON players(level)",
        "CREATE INDEX ix_players_power     ON players(power)",
    ),
    # -- v4: the shared home for a whole-list checkpoint (#1465) ---------------------
    #
    # Every list here (`panel/kept.py`'s ★ tiles, the ghost map's own list, a world
    # page's own list, the rally day-counters) is read and written WHOLE — never a row
    # at a time, never queried by a WHERE clause — which is exactly what `players` was
    # NOT: that table earned its own columns and indexes because a lap of the map reads
    # and sorts it by name, alliance, level, power. Nothing here is sorted or searched
    # inside the database; the table is a place for the same whole-blob write the panel
    # already did to a file, done through `store.write()`'s transaction instead of a
    # tmp-file rename — same cost, same shape, and now inside the ONE place every other
    # piece of this profile's state already lives.
    #
    # One table, not one per list: a NEW list-shaped store (the next ★-style page this
    # bot grows) is a new `name` in this table, not a new migration — the same way a
    # new PLAYER is a new row in `players`, not a new migration. `docs/panel-storage.md`
    # says which names are in use and what each one holds.
    (
        """CREATE TABLE blobs (
               name       TEXT PRIMARY KEY,
               data       TEXT NOT NULL,
               updated_at INTEGER NOT NULL
           )""",
    ),
    # -- v5: what a warzone did on a day, so a cycle can be DERIVED from it (#1467) ---
    #
    # A table of its own rather than a name in `blobs`, and the rule above is the reason:
    # this one IS searched by a `WHERE` clause — by warzone, by day, and by both — every
    # time the «Серверы» grid draws a row or the phone opens the screen, and the fit walks
    # it whole. `blobs` is for a list read and written whole and never queried; this is
    # the other kind (`docs/panel-storage.md`).
    #
    # The primary key carries the SOURCE on purpose. A person's own reading and a map
    # lap's count of the same warzone on the same day may disagree, and that disagreement
    # is the most useful row in the table — collapsing them onto one key would let the
    # later write silently become the truth. Nothing here is ever overwritten by a
    # PREDICTION: the schedule is computed from these rows and never written back into
    # them (`tools/lib/secret_day.py`).
    (
        """CREATE TABLE secret_days (
               server   INTEGER NOT NULL,
               -- The game-day INDEX, counted off the game's own reset moment rather
               -- than any midnight — `secret_day.day_index`, and the reset is the
               -- client's `GetTomorrowZero` (docs/research/game-clock.md).
               day      INTEGER NOT NULL,
               -- One of `day` / `post` / `plain`, or `unknown` when only the counts
               -- below were recorded and no calibration had labelled them yet.
               state    TEXT NOT NULL,
               -- `game` / `observed` / `lap` — where the row came from, in its own words.
               source   TEXT NOT NULL,
               stars    INTEGER,
               tiles    INTEGER,
               seen_at  INTEGER NOT NULL,
               PRIMARY KEY (server, day, source)
           )""",
        "CREATE INDEX ix_secret_days_day ON secret_days(day)",
    ),
)

#: What the code in this checkout expects. A database above it was written by a NEWER
#: panel — see :meth:`Store.connect` for why that is refused rather than migrated back.
CODE_VERSION = len(MIGRATIONS)


class StoreTooNew(RuntimeError):
    """The database was written by a newer panel than this one.

    Raised rather than «handled», because the alternatives are both worse than stopping:
    running against a schema we do not know silently ignores columns a newer version
    filled, and migrating backwards deletes them. A person who has run a newer panel on
    this profile updates this one; nothing is lost either way.
    """


class Store:
    """One profile's database — connections, schema and the writer thread.

    Built by the runtime and reached as `rt.store`. Nothing constructs one at module
    level: a store belongs to a profile, and a module-level one belongs to whichever
    profile happened to import first, which is the bug `docs/research/profile-isolation.md`
    is a list of.
    """

    def __init__(self, path: str, *, migrations: tuple = MIGRATIONS) -> None:
        self.path = path
        self._migrations = tuple(migrations)
        #: One connection per thread. A `sqlite3.Connection` is not thread-safe, and
        #: sharing one behind a lock is the same object with the contention added back.
        self._local = threading.local()
        #: Every connection this store has opened, so :meth:`close` can shut them.
        #: Touched under `_lock`; the connections themselves are used only by the
        #: thread that opened them.
        self._open: list = []
        self._lock = threading.RLock()
        #: The schema is brought up to date once per PROCESS, not once per thread.
        self._migrated = False
        #: The writer thread and its queue, started on the first :meth:`submit`.
        self._jobs: "queue.Queue | None" = None
        self._writer: "threading.Thread | None" = None
        self._stopping = False
        #: How many jobs the writer has run and how many transactions it took, so the
        #: batching can be asserted by a test rather than believed.
        self.jobs_done = 0
        self.batches_done = 0

    # -- connecting ------------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        """This thread's connection, opened and migrated on first ask.

        `isolation_level=None` turns off the driver's implicit transactions: every write
        here says `BEGIN IMMEDIATE` for itself (:meth:`write`), so the lock is taken when
        we mean it and held for as long as we say rather than until whenever the driver
        decides to commit.
        """
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=CONNECT_TIMEOUT,
                               isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        # Readers and the writer stop blocking each other, in this process and in the
        # standalone tab running beside it. The mode is a property of the FILE, not of
        # the connection, so it is set once and only when it is not already right:
        # switching it needs a moment's exclusive lock, and that one statement is
        # exempt from the busy timeout above — every thread doing it on the way in is
        # how eight of them opening at once raised «database is locked» on a database
        # that was already in the mode they wanted.
        if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                # Somebody else is mid-switch. Theirs lands, and this connection reads
                # the file in whatever mode it ends up in — which is the same mode.
                pass
        # A commit does not wait for the platter. The failure this gives up on is
        # «the machine lost power mid-commit»; what it buys is that a sweep's commit
        # costs microseconds rather than a disk revolution. The data here is a
        # convenience — every row of it can be seen again by looking at the map again.
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._open.append(conn)
        self._local.conn = conn
        if not self._migrated:
            self._migrate(conn)
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Bring the schema up to :data:`CODE_VERSION`, once, safely against a rival.

        `BEGIN IMMEDIATE` before reading the version is the whole trick: two panels
        opening one profile at the same moment would otherwise both read «version 0» and
        both run migration 1. The write lock makes the loser wait and re-read, by which
        time the version says the work is done.
        """
        with self._lock:
            if self._migrated:
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                have = int(conn.execute("PRAGMA user_version").fetchone()[0])
                if have > len(self._migrations):
                    raise StoreTooNew(
                        f"{self.path} is at schema version {have}; this panel knows "
                        f"{len(self._migrations)}. Update the panel — migrating a "
                        f"database backwards would delete what the newer one wrote.")
                for version in range(have + 1, len(self._migrations) + 1):
                    step = self._migrations[version - 1]
                    for statement in ((step,) if isinstance(step, str) else step):
                        conn.execute(statement)
                    # Not a parameter: PRAGMA takes a literal. The value is an int from
                    # `range`, so there is nothing here a caller could bend.
                    conn.execute(f"PRAGMA user_version={int(version)}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            self._migrated = True

    def version(self) -> int:
        """What schema version this database is at."""
        return int(self.connect().execute("PRAGMA user_version").fetchone()[0])

    # -- writing ---------------------------------------------------------------------
    @contextmanager
    def write(self):
        """One short transaction. Yields the connection; commits, or rolls back whole.

            with store.write() as conn:
                conn.executemany("INSERT INTO … VALUES(?, ?)", rows)

        **NOT from the Tk thread** — use :meth:`submit`. And nothing inside that reads a
        widget, asks the game or sleeps: what is held for the length of this block is the
        write lock of every process on this profile.
        """
        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            # A failed migration of a thousand rows leaves none of them, which is the
            # only outcome a caller can reason about. A half-written store is the thing
            # `panel/kept.py` wrote atomically to avoid, and it is not lost here.
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        conn.execute("COMMIT")

    def read(self) -> sqlite3.Connection:
        """A connection for SELECTs. Under WAL a reader needs no transaction at all."""
        return self.connect()

    # -- writing from the Tk thread ---------------------------------------------------
    def submit(self, job) -> None:
        """Run `job(conn)` on this store's writer thread, batched with whatever else is
        queued into ONE transaction.

        This is what a tab, a trigger or anything else on the Tk thread calls. The
        batching is the point and it is what the measurement asked for: a lap of the map
        hands over thousands of rows in a burst, and the cost of a burst is the number of
        COMMITs, not the number of rows.
        """
        self._ensure_writer().put(job)

    def _ensure_writer(self) -> "queue.Queue":
        with self._lock:
            if self._jobs is None:
                self._jobs = queue.Queue()
                self._writer = threading.Thread(
                    target=self._drain, name=f"store-{os.path.basename(self.path)}",
                    daemon=True)
                self._writer.start()
            return self._jobs

    def _drain(self) -> None:
        jobs = self._jobs
        assert jobs is not None
        while True:
            job = jobs.get()
            if job is _STOP:
                return
            batch = [job]
            # Everything that arrives within the linger joins this transaction. The
            # window is needed because a producer submitting in a loop is SLOWER than
            # this thread: draining as fast as they arrive gives one transaction per
            # job, which is the per-row cost `submit` exists to avoid. Bounded, so the
            # first job is never held hostage to a second one that may never come.
            deadline = time.monotonic() + BATCH_LINGER
            while len(batch) < BATCH_MAX:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                try:
                    nxt = jobs.get(timeout=left)
                except queue.Empty:
                    break
                if nxt is _STOP:
                    self._run_batch(batch)
                    return
                batch.append(nxt)
            self._run_batch(batch)

    def _run_batch(self, batch: list) -> None:
        try:
            with self.write() as conn:
                for job in batch:
                    job(conn)
        except Exception:                                          # noqa: BLE001
            # One bad job must not take the batch's siblings with it, so the batch is
            # retried one at a time. A job that fails alone is dropped with its
            # traceback — the caller is a background write with nobody waiting on it,
            # and raising here would only kill the writer thread for every later one.
            for job in batch:
                try:
                    with self.write() as conn:
                        job(conn)
                except Exception:                                  # noqa: BLE001
                    self._failed(job)
                else:
                    self.jobs_done += 1
                    self.batches_done += 1
            return
        self.jobs_done += len(batch)
        self.batches_done += 1

    def _failed(self, job) -> None:
        """A single job that failed on its own. Overridden by the runtime to log it."""

    def flush(self, timeout: float = 30.0) -> bool:
        """Wait until the writer has run everything queued. Returns whether it did.

        For a test, for a shutdown, and for the one place a person's press has to be on
        disk before the next thing reads it back.
        """
        with self._lock:
            jobs = self._jobs
        if jobs is None:
            return True
        done = threading.Event()
        jobs.put(lambda _conn: done.set())
        return done.wait(timeout)

    # -- the key/value corner ---------------------------------------------------------
    def meta_get(self, key: str, default: str | None = None) -> str | None:
        row = self.read().execute("SELECT value FROM meta WHERE key = ?",
                                  (str(key),)).fetchone()
        return default if row is None else row["value"]

    def meta_set(self, key: str, value: str) -> None:
        with self.write() as conn:
            conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (str(key), str(value)))

    # -- a whole-list checkpoint, kept as one row --------------------------------------
    def blob_get(self, name: str):
        """The named list/dict, decoded — or `None` when nothing has been saved yet.

        Synchronous: every reader here loads once, at start or at restore, the way
        `players.py` reads `players.json` before the writer thread exists.
        """
        row = self.read().execute("SELECT data FROM blobs WHERE name = ?",
                                  (str(name),)).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["data"])
        except ValueError:
            return None

    def blob_set(self, name: str, value) -> None:
        """Checkpoint `value` (JSON-able) under `name`, replacing whatever was there.

        Synchronous, like :meth:`meta_set` — one small `BEGIN IMMEDIATE … COMMIT`, the
        same cost the tmp-file-then-rename it replaces always had. Every blob here is a
        few rows to a few hundred, never the megabytes `players` was measured at
        (`panel/runtime/store.py`'s own docstring), so there is nothing to batch: a
        caller that returns from this call has its checkpoint on disk, exactly as it did
        when this was a JSON file written on the same thread.
        """
        payload = json.dumps(value, ensure_ascii=False)
        stamp = int(time.time())
        with self.write() as conn:
            conn.execute(
                "INSERT INTO blobs(name, data, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET data = excluded.data, "
                "updated_at = excluded.updated_at",
                (str(name), payload, stamp))

    # -- closing ----------------------------------------------------------------------
    def close(self) -> None:
        """Stop the writer and close every connection this store opened."""
        with self._lock:
            jobs, self._jobs = self._jobs, None
            writer, self._writer = self._writer, None
            conns, self._open = list(self._open), []
        if jobs is not None:
            jobs.put(_STOP)
        if writer is not None:
            writer.join(timeout=10.0)
        for conn in conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._local = threading.local()
        self._migrated = False


#: The sentinel that ends the writer thread. Not `None`, which a caller could submit.
_STOP = object()


# ---------------------------------------------------------------------------
# moving a JSON file in, once, without losing anything
# ---------------------------------------------------------------------------
#: What the old file is renamed to once its contents are in the database. It stays
#: **beside** the database rather than being deleted: an import that turns out to have
#: misread a field is answered by a person opening the file, and a delete is answered by
#: nothing. Small enough to keep for good — the largest of them is 11 MB, once.
IMPORTED_SUFFIX = ".imported"


def import_once(store: Store, mark: str, path: str, load, insert) -> int:
    """Move one JSON file into the database, exactly once, keeping the file.

    `mark` is the name this import is remembered by in `meta`; `load(path)` reads the
    old file and returns rows; `insert(conn, rows)` writes them. Returns how many rows
    were imported, or 0 when there was nothing to do.

    The order matters and is the whole safety of it:

    1. the mark is checked — an import that has run does not run again, so a person's
       later edits are never overwritten by a stale file;
    2. the rows are read and written **in one transaction with the mark**, so a panel
       killed halfway leaves a database with neither the rows nor the mark, and the next
       start imports cleanly rather than half-again;
    3. only THEN is the file renamed to `<name>.imported`, and a rename that fails is
       not an error — the mark already says the work is done.
    """
    if store.meta_get(f"import:{mark}"):
        return 0
    rows = load(path)
    if rows is None:
        # The file is not there, or could not be read. NOT an empty import: marking it
        # done would mean a file that appears a second later is ignored for ever, and
        # «the read came back empty» is not a reason to conclude anything (`panel/kept.py`).
        return 0
    with store.write() as conn:
        count = insert(conn, rows)
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (f"import:{mark}", str(int(time.time()))))
    try:
        if os.path.exists(path):
            os.replace(path, path + IMPORTED_SUFFIX)
    except OSError:
        pass
    return count


def blob_import_once(store: Store, name: str, path: str) -> bool:
    """Move one whole-list checkpoint file into `blobs`, exactly once, keeping the file.

    The shared way every ★-style list adopts the database: `panel/tabs/secret_tasks/
    tab.py` (name `secret_tasks_state`), `.../ghost.py` (`ghost_map_state`), `.../
    world.py` (`world_state_monsters`) and `panel/rally_limits.py` (`rally_counts`) all
    call this once, at restore, before reading `store.blob_get(name)` — so a profile
    opened by a NEWER panel for the first time carries its file across instead of
    starting blank, and every later start finds the mark and does nothing.
    """
    def load(p):
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def insert(conn, value) -> int:
        conn.execute(
            "INSERT INTO blobs(name, data, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET data = excluded.data, "
            "updated_at = excluded.updated_at",
            (str(name), json.dumps(value, ensure_ascii=False), int(time.time())))
        return 1

    return bool(import_once(store, f"blob:{name}", path, load, insert))
