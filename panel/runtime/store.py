r"""THE ONE DOOR to the panel's ONE database (#1398, #2025).

## Why there is one

Everything the panel remembers is a file in the profile directory, and most of those
files are a whole list rewritten from scratch on every change. That is fine for the
small ones and it is measurably not fine for the register of players: on a live profile
it is 11.5 MB and 17 374 rows, `json.load` takes 0.97 s, `json.dump` takes 1.45 s, and a
lap of the map changes something on almost every tick — so the panel spent a second and
a half rewriting the same eleven megabytes every twenty seconds, and the «Игроки» page
loaded all of it into memory to filter and sort it in Python.

So the data goes into SQLite. **ONE database for the whole panel** since #2025 —
`profiles/panel.db`, one level above the profile directories — and every row in it says
which profile it belongs to.

It was one database per profile until then, in that profile's own directory, and the
isolation was the FILE. That is the strongest isolation there is; it is also why a
rename was a directory move, a delete was an `rmtree` that could half-happen, and one
account's settings and one account's data could end up disagreeing about that account's
own name. The person asked for the merge in those words: «меньше проблем с целостностью
и консистентностью будет».

What did NOT change is the rule the file was enforcing. A profile is still a whole panel
of its own, its register, its ★ tiles and its counters are still an ACCOUNT's — never the
window's and never «the first profile that opened» — and what enforces it now is
:data:`PROFILE_COLUMN`: the tables are named `all_…`, a store carries the profile it was
built for, and the old table names are per-connection VIEWS scoped to that profile. A
query that forgets the profile is not a leak, it is either already filtered or an error.

There is still no module-level connection here and no module-level store: a caller asks
the runtime (`rt.store`), and the runtime hands it the one belonging to the profile it is
running.

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
* **`BEGIN IMMEDIATE` before the schema version is even read** (:meth:`Store._migrate`).
  Since #2025 the competing opener is not merely another process on one profile — it is
  every open profile of every panel on this machine, all opening the same file, possibly
  for the first time. Two of them reading «version 0» and both running migration 1 is
  what the write lock makes impossible: the loser waits, re-reads, and finds the work
  done.
* **A newer database is refused, not migrated backwards** (:class:`StoreTooNew`) — and
  that matters more with one file than it did with many, because now ONE panel started
  from a newer checkout would otherwise take every account with it.

## Nothing here writes on the Tk thread

:meth:`Store.submit` hands a callable to this store's single writer thread, and that
thread drains **everything queued into ONE transaction**. A sweep that sees four
thousand players is one commit, not four thousand — which is the second half of the
measurement above: the cost was never the rows, it was doing the whole file per change.

A caller that is already on a background thread may use :meth:`Store.write` directly.
A caller on the Tk thread must not.

## What lives in the database, and what deliberately does not

The inventory is in `docs/panel-storage.md`. In one line: the data does, and **so do the
settings** — the person's decision, «Никаких json, все должно быть в базе» (#2017, and
#2025 for the panel's own). An earlier version of this docstring said the opposite and
named `config.json`, the catalogues and the caps as files a person edits by hand; that
half is gone.

What is still a file, and is not a settings store: the logs (appended to, never rewritten
whole, so they never had the cost this layer removes), the locks and the heartbeat (the
panel's note about itself), and the checkpoints a capture CHILD writes for the panel to
read — a channel between two processes, rewritten whole every fifteen seconds, worth
nothing after a restart, and the one thing that must NOT become durable.
"""
from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import unicodedata
from contextlib import contextmanager

#: The file name of the ONE database (#2025). It used to be one of these inside every
#: profile directory; it is now a single file one level above them, `profiles/panel.db`
#: — see :data:`PROFILE_COLUMN` for what keeps the accounts apart inside it.
DB_FILE = "panel.db"

#: The column every profile-owned table carries, and the whole of this file's isolation.
#:
#: THE POINT IS THAT FORGETTING IT IS IMPOSSIBLE, not that nobody has forgotten it yet
#: (#1306 cost four accounts a day of decoding each other's traffic). So the real tables
#: are named `all_<something>` and are never what a caller writes, and every connection
#: this store opens carries TEMP VIEWS under the OLD names — `players`, `blobs`,
#: `monsters`, `secret_days`, `meta` — each one `SELECT * FROM all_… WHERE profile =
#: '<this store's profile>'`.
#:
#: A query that says `FROM players` is therefore scoped whether or not its author
#: thought about it, and a WRITE that says `INTO players` fails loudly («cannot modify
#: … which is a view») instead of silently landing in everybody's account. The writes
#: this module makes name `all_players` and pass the profile themselves.
PROFILE_COLUMN = "profile"

#: The profile name the PANEL's own rows are filed under — the settings that belong to
#: the window rather than to an account (`profiles/settings.json`, the shipped catalogue
#: templates). A colon cannot survive `panel.profile.sanitize`, so no account can ever
#: be called this and collide with it.
PANEL_SCOPE = ":panel"

#: The tables a profile owns, each mapped to the temp view a caller sees. `all_profiles`
#: is deliberately absent: the list of accounts belongs to the panel, not to any one of
#: them, and it is reached through :class:`PanelStore` instead.
SCOPED_TABLES = {
    "meta": "all_meta",
    "players": "all_players",
    "blobs": "all_blobs",
    "secret_days": "all_secret_days",
    "monsters": "all_monsters",
    "reward_popups": "all_reward_popups",
    "day_stats": "all_day_stats",
    "favourites": "all_favourites",
}

#: «Призрак: карта»'s own list, by name — the one blob TWO tabs meet over (#2010).
#:
#: «Секретки» owns it: its map page fills it from the sniffer and saves it whole
#: (`GhostMapGrid.STATE_BLOB`). «Командный пункт» READS it, because the standing order
#: that spends the day's five robberies has to choose out of the list the panel is
#: showing — the same rule the ★ robbery has obeyed since #1256. The name lives here so
#: neither tab has to import the other: a tab talks to the runtime and to nothing else
#: (`docs/panel-tabs.md`), and two copies of a string is how they come to disagree.
GHOST_MAP_STATE = "ghost_map_state"

#: …and the ★ list beside it, for the same reason (#2018). «Секретки» fills and saves
#: it; the schematic map (`panel/runtime/worldscene.py`) paints it. One name, in the
#: place both of them already talk to.
SECRET_TASKS_STATE = "secret_tasks_state"

#: THE DRONE'S CHIP CHESTS — what the bag holds of each grade, and how many of each this
#: account has opened (#2617). The tally is the only part that cannot be re-read from the
#: game: a chest that is open is gone, so the count of them exists nowhere but here.
DRONE_CHIPS = "drone_chips"

#: THE SURVIVORS' RECRUIT TICKETS (#2632) — what the banner holds and how many this
#: account has SPENT today. The first half is a reading with its age beside it; the
#: second is the panel's own fact, for the same reason the chip tally is: a ticket that
#: is spent is gone, and nothing in the client remembers how many went today.
SURVIVOR_TICKETS = "survivor_tickets"

#: THE BUILDINGS THAT HAVE FINISHED AND ARE WAITING TO BE OPENED (#2632) — the list
#: `actions/read_ready_buildings.md` read, kept so a fresh panel draws the page before
#: anybody presses «Обновить». Re-readable from the game at any moment, with its age on
#: the page, which is what makes a stale one visibly stale.
READY_BUILDINGS = "ready_buildings"

#: THE DRONE'S COMPONENT CHESTS (#2662) — the duel's WEDNESDAY box, and not Monday's.
#: «Сундук Компонента Дрона 1/2/3 ур.» is a different item family from «Сундук Чипа
#: Навыка» ([[DRONE_CHIPS]] above), and the two have been confused once already, so they
#: are kept apart here too: what the bag holds of each grade, and how many of each this
#: account has opened. The tally is the only part that cannot be re-read from the game.
DRONE_PARTS = "drone_parts"

#: THE RESEARCH QUEUES — the player's own science centres, what each is studying, and
#: what it would cost to close the one that is running (#2662). Re-readable from the game
#: whenever the client is in it; kept only so a page opened on a phone draws the last
#: answer with its age beside it instead of a blank.
RESEARCH_QUEUES = "research_queues"

#: THE DUEL'S SCORE (#2645) — the player's own points, the two alliances' points and the
#: days each side has won, exactly as `actions/read_vs_score.md` read them. Re-readable
#: from the game whenever the client is in it, kept only so a page opened on a phone
#: draws the last answer with its age beside it instead of a blank.
VS_SCORE = "vs_score"

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
    # -- v6: the monsters the client has drawn, a ROW at a time (#1963) ---------------
    #
    # THE LIST THAT OUTGREW `blobs`, and the measurement is the whole argument. The
    # monster page kept its list under the name `world_state_monsters`, which is the
    # right home for a store that is read and written WHOLE — and this one stopped being
    # that. Live, on an ordinary profile:
    #
    #     31 828 rows · 9 805 183 bytes of JSON · rewritten on EVERY poll (every 5 s)
    #     one rewrite = 0.20–0.32 s, and it ran on the Tk thread of the whole window
    #
    # That is a fifth of a second of frozen panel, five times a minute, per profile with
    # the follow clock on — the «панель тормозит» of #1963. `blob_set`'s own docstring
    # promised «a few rows to a few hundred, never the megabytes»; this was a hundred
    # times over it.
    #
    # So it earns its own table, on the same rule `players` and `secret_days` earned
    # theirs (`docs/panel-storage.md`): a poll touches the fifty to fifteen hundred rows
    # it just saw and writes THOSE, the ageing is a `DELETE … WHERE seen_at < ?` instead
    # of a rewrite of everything that survived it, and «только текущая зона» is a `WHERE
    # server = ?` rather than a filter in Python over thirty thousand dicts.
    #
    # `uuid` is TEXT here and not typeless like `players.uuid`: this page's key is the
    # page's OWN composite («<server>:<point id>»), made by the reader, never a number
    # off the wire. The game's own uuid — the one a march can be aimed at, and the one
    # only the world register answers with — is `game_uuid` beside it.
    (
        """CREATE TABLE monsters (
               uuid         TEXT PRIMARY KEY,
               server       INTEGER,
               x            INTEGER,
               y            INTEGER,
               level        INTEGER,
               seen_at      INTEGER,
               expires_at   INTEGER,
               completed_at INTEGER,
               until_key    TEXT,
               monster_type INTEGER,
               kind_name    TEXT,
               cfg_id       INTEGER,
               source       TEXT,
               point_id     INTEGER,
               game_uuid    TEXT
           )""",
        # `seen_at` first: the ageing pass walks it every poll and the page ranks on it.
        "CREATE INDEX ix_monsters_seen_at ON monsters(seen_at)",
        "CREATE INDEX ix_monsters_server  ON monsters(server)",
        "CREATE INDEX ix_monsters_level   ON monsters(level)",
    ),
    # -- v7: the mark the «Метка» column SHOWS, so the heading can order by it (#1971) -
    #
    # The column draws two notes — the person's own mark and the game's note behind it
    # (`players.mark_of`) — and it sorted by `note_fold`, the person's mark alone. On a
    # live register with 884 game notes and not one mark of its own that is 323 000 rows
    # whose key is the empty string: pressing the heading sorted by the tie-break and the
    # table did not move.
    #
    # `fold()` is this store's own function (`Store.connect`) and not SQLite's `LOWER`,
    # which is ASCII-only — most of what people write in these notes is not.
    (
        "ALTER TABLE players ADD COLUMN mark_fold TEXT",
        """UPDATE players
              SET mark_fold = fold(
                  COALESCE(NULLIF(TRIM(COALESCE(note, '')), ''),
                           TRIM(COALESCE(remark, ''))))""",
        "CREATE INDEX ix_players_mark ON players(mark_fold)",
    ),
    # -- v8: ONE database for every profile, keyed by which one (#2025) ----------------
    #
    # THE PERSON'S DECISION, in their words: «Давай сделаем одну базу на всех и конфиги и
    # профили, вынеси ее на уровень выше, из профилей, меньше проблем с целостностью и
    # консистентностью будет». Until now every profile had a `panel.db` of its own in its
    # own directory, and the isolation was the FILE — which is the strongest isolation
    # there is and also the reason a rename, a delete and a settings write had to be
    # right in three places at once.
    #
    # So the isolation becomes logical, and the whole of this migration is about making
    # it as hard to get wrong as a separate file was:
    #
    # * every table is renamed to `all_<name>` and grows a `profile` column, FIRST in the
    #   primary key — so a row cannot exist without saying whose it is;
    # * every index is re-made with `profile` first, so the narrowing a page does still
    #   uses one and never walks another account's rows to find its own;
    # * and the old names come back as per-connection TEMP VIEWS scoped to one profile
    #   (:data:`PROFILE_COLUMN`), which is what makes «forgot the filter» impossible
    #   rather than merely absent.
    #
    # Rows already in the file being migrated are the PANEL's: this file is `profiles/
    # panel.db`, which before this change held nothing but the panel-wide catalogue
    # templates that #2017 moved into it. Each profile's OWN database is a separate file
    # and is carried across by an import, never by this migration.
    (
        """CREATE TABLE all_meta (
               profile TEXT NOT NULL,
               key     TEXT NOT NULL,
               value   TEXT NOT NULL,
               PRIMARY KEY (profile, key)
           )""",
        "INSERT INTO all_meta(profile, key, value) "
        "  SELECT ':panel', key, value FROM meta",
        "DROP TABLE meta",
        """CREATE TABLE all_players (
               profile         TEXT NOT NULL,
               uid             TEXT NOT NULL,
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
               note_fold       TEXT,
               mark_fold       TEXT,
               PRIMARY KEY (profile, uid)
           )""",
        "INSERT INTO all_players SELECT ':panel', * FROM players",
        "DROP TABLE players",
        "CREATE INDEX ix_players_last_seen ON all_players(profile, last_seen)",
        "CREATE INDEX ix_players_name      ON all_players(profile, name_fold)",
        "CREATE INDEX ix_players_alliance  ON all_players(profile, alliance_fold)",
        "CREATE INDEX ix_players_server    ON all_players(profile, server_id)",
        "CREATE INDEX ix_players_level     ON all_players(profile, level)",
        "CREATE INDEX ix_players_power     ON all_players(profile, power)",
        "CREATE INDEX ix_players_mark      ON all_players(profile, mark_fold)",
        """CREATE TABLE all_blobs (
               profile    TEXT NOT NULL,
               name       TEXT NOT NULL,
               data       TEXT NOT NULL,
               updated_at INTEGER NOT NULL,
               PRIMARY KEY (profile, name)
           )""",
        "INSERT INTO all_blobs SELECT ':panel', * FROM blobs",
        "DROP TABLE blobs",
        """CREATE TABLE all_secret_days (
               profile  TEXT NOT NULL,
               server   INTEGER NOT NULL,
               day      INTEGER NOT NULL,
               state    TEXT NOT NULL,
               source   TEXT NOT NULL,
               stars    INTEGER,
               tiles    INTEGER,
               seen_at  INTEGER NOT NULL,
               PRIMARY KEY (profile, server, day, source)
           )""",
        "INSERT INTO all_secret_days SELECT ':panel', * FROM secret_days",
        "DROP TABLE secret_days",
        "CREATE INDEX ix_secret_days_day ON all_secret_days(profile, day)",
        """CREATE TABLE all_monsters (
               profile      TEXT NOT NULL,
               uuid         TEXT NOT NULL,
               server       INTEGER,
               x            INTEGER,
               y            INTEGER,
               level        INTEGER,
               seen_at      INTEGER,
               expires_at   INTEGER,
               completed_at INTEGER,
               until_key    TEXT,
               monster_type INTEGER,
               kind_name    TEXT,
               cfg_id       INTEGER,
               source       TEXT,
               point_id     INTEGER,
               game_uuid    TEXT,
               PRIMARY KEY (profile, uuid)
           )""",
        "INSERT INTO all_monsters SELECT ':panel', * FROM monsters",
        "DROP TABLE monsters",
        "CREATE INDEX ix_monsters_seen_at ON all_monsters(profile, seen_at)",
        "CREATE INDEX ix_monsters_server  ON all_monsters(profile, server)",
        "CREATE INDEX ix_monsters_level   ON all_monsters(profile, level)",
        # -- and the thing that makes a profile a profile (#2025) --------------------
        #
        # WHAT A PROFILE IS, now that `config.json` is not it. The panel used to answer
        # «is this directory an account» by looking for that file (#1306); it asks this
        # table instead. The directory is still there — logs, captures, locks, the
        # things that are not game data — but it is no longer the RECORD of an account,
        # so a rename is one `UPDATE` and a delete is one transaction instead of a file
        # move that half-happened.
        #
        # No `profile` column here, and that is not an oversight: this table IS the list
        # of profiles, and it belongs to the panel. It is reached through
        # :class:`PanelStore` and never through a profile's own scope.
        """CREATE TABLE profiles (
               name       TEXT PRIMARY KEY,
               -- This profile's own tab blocks, as JSON — what `config.json` held. The
               -- default profile's is the base every other one is a diff against, which
               -- is unchanged: only where it is written down has moved.
               config     TEXT NOT NULL DEFAULT '{}',
               created_at INTEGER NOT NULL
           )""",
    ),
    # -- v9: what the game gave, and what the panel was doing at the time (#2027) ------
    #
    # The reward popups the client raises on its own — a help given to an alliancemate's
    # secret task, a gift collected, a truck brought home. The ear inside the client
    # (`tools/lib/lua_actions.py::reward_watch_install`) closes them and says what was in
    # them; this is where those rows land, because anything the game told the panel is a
    # row in the database and never a file (`CLAUDE.md`).
    #
    # A TABLE rather than a blob, by the rule #1963 wrote down: this grows without bound,
    # is written a row at a time as rewards arrive, and is read back narrowed («the last
    # fifty», «the unknown windows»). A blob would be re-serialised whole on every drain.
    (
        """CREATE TABLE all_reward_popups (
               profile TEXT NOT NULL,
               -- The GAME's own clock, in milliseconds, as the ear stamped it. Zero for
               -- a row the ear could not stamp (a client that answered no time at all).
               at      INTEGER NOT NULL,
               -- …and the panel's, so a row is still orderable when the game's is 0.
               seen_at INTEGER NOT NULL,
               -- `reward` (what was given), `closed` / `popup` / `unknown` / `held`
               -- (what happened to the window), `lost` (rows the ring dropped).
               kind    TEXT NOT NULL,
               -- The reward method, or the window's name — whichever this row is about.
               source  TEXT NOT NULL,
               -- The reward list as the client had it: `<id>x<count>`, comma separated.
               items   TEXT NOT NULL DEFAULT '',
               -- WHAT THE PANEL WAS PLAYING when the row arrived, and empty when it was
               -- playing nothing. Empty means «не знаю» and is drawn as such: nothing in
               -- the client knows why a reward came, so a guess written here would be
               -- indistinguishable from a fact.
               why     TEXT NOT NULL DEFAULT ''
           )""",
        "CREATE INDEX ix_reward_popups_seen ON all_reward_popups(profile, seen_at)",
        "CREATE INDEX ix_reward_popups_kind ON all_reward_popups(profile, kind)",
    ),
    # -- v10: the search haystack loses its accents, and so does the needle (#2385) ----
    #
    # A nickname spelled with an umlaut could only be found by typing the umlaut, and on
    # a phone nobody does — so «нет такого игрока» was said about a row that had been in
    # the register for days and was seen again three minutes ago. `search_text` is
    # written flattened from now on (`players.flatten`); this is the three hundred
    # thousand rows that were written before it.
    #
    # `flat()` is lent to SQL by `Store.connect` for the same reason `fold()` is: a
    # migration has no Python to reach for, and SQLite's own text functions are ASCII.
    # Flattening what is already there is enough — the column was case folded when it
    # was written, and dropping the marks off that is what a fresh write would produce.
    (
        "UPDATE all_players SET search_text = flat(search_text)",
    ),
    # -- v11: a day's statistic is a HISTORY, not one number overwritten (#2705) -------
    #
    # The person's rule, in their words: «Когда мы собираем какую либо статистику по
    # дню … то это все должно храниться в базе и исторически сохраняться, чтобы при
    # желании строить графики» (`CLAUDE.md`, «A DAY'S STATISTIC IS A HISTORY»). A counter
    # zeroed at the day boundary answers «сколько сегодня» and destroys every other
    # question anybody will ever ask of it; the day beside the number costs one column.
    #
    # `day` is the GAME's day and never the PC's calendar (`panel/runtime/day_reset.py`):
    # the boundary that zeroes a counter is the one that has to name the row, and the two
    # stores that got this wrong file part of one game day under each of two dates
    # (`docs/panel-storage.md`, «Daily statistics»).
    #
    # The profile is FIRST in the key for the reason every other table here has it: a
    # write that forgets the account must fail rather than land in all of them.
    (
        """CREATE TABLE all_day_stats (
               profile TEXT NOT NULL,
               -- `YYYY-MM-DD` of the warzone's own day.
               day     TEXT NOT NULL,
               -- `trucks_sent`, `secret_tasks_taken`, `sweep_bench_ms`…
               name    TEXT NOT NULL,
               -- REAL, because half of these are counts and half are measurements.
               value   REAL NOT NULL DEFAULT 0,
               -- When the row was last touched, so «сегодня» can say how fresh it is.
               at      INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (profile, day, name)
           )""",
        "CREATE INDEX ix_day_stats_name ON all_day_stats(profile, name, day)",
    ),

    # -- v12: the players a person marked, so a register of 300 000 has a short list --
    #
    # A mark is a POINT WRITE on one player and it is read back as «who is on the list»,
    # so it is a table rather than a named blob: a blob is the shape for a store that is
    # read and written WHOLE (`CLAUDE.md`, «what is the unit of a WRITE»), and starring
    # one player would rewrite every star there is.
    #
    # It is a table OF ITS OWN and not a column on `all_players` for the reason the two
    # notes are kept apart: a mark belongs to the PERSON and a row of `all_players` is
    # merged by every source that ever meets that player. A column there would have to
    # survive an upsert written by a lap of the map, and «the star that a sweep cleared»
    # is a bug nobody would find for months.
    #
    # `uid` and not a name: names change, and a mark that follows a name follows whoever
    # takes it next.
    (
        """CREATE TABLE all_favourites (
               profile TEXT NOT NULL,
               uid     TEXT NOT NULL,
               -- When it was marked, so a list of stars can be ordered by newest.
               at      INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (profile, uid)
           )""",
    ),
)

#: THE SCHEMA AS IT STOOD WHEN EVERY PROFILE HAD A DATABASE OF ITS OWN (#2025).
#:
#: Frozen at v7 on purpose and never extended again: it is not a schema anything is
#: written with any more, it is the shape :func:`import_profile_db_once` has to be able
#: to READ. A profile shut down on an older panel may be at any version up to 7, so the
#: importer opens its file with exactly this history, lets the ordinary machinery bring
#: it up to 7, and copies the rows out. Extending it would migrate a file we are about
#: to retire.
LEGACY_MIGRATIONS = MIGRATIONS[:7]

#: What the code in this checkout expects. A database above it was written by a NEWER
#: panel — see :meth:`Store.connect` for why that is refused rather than migrated back.
CODE_VERSION = len(MIGRATIONS)


def _fold(value) -> str:
    """`str.casefold`, and what «fold» means everywhere in this panel.

    Said here as well as in `panel/runtime/players.py` because a store must not import a
    page's vocabulary to open a connection — one line, and the test that matters is that
    the two agree (`tests/test_players_registry.py`).
    """
    return str(value or "").casefold()


def _flat(value) -> str:
    """`fold`, and the accents dropped too — what the SEARCH compares (#2385).

    The twin of `panel/runtime/players.py::flatten`, here for the same reason `_fold` is
    here: a store must not import a page's vocabulary to open a connection, and a
    migration has no Python to reach for. One line each, and
    `tests/test_players_registry.py` fails the moment the two stop agreeing.
    """
    text = unicodedata.normalize("NFD", _fold(value))
    return unicodedata.normalize(
        "NFC", "".join(ch for ch in text if not unicodedata.combining(ch)))


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

    def __init__(self, path: str, profile: str, *,
                 migrations: tuple = MIGRATIONS) -> None:
        # REQUIRED, and positional on purpose (#2025): there is one file now, so a store
        # built without saying whose it is would be every account's at once. There is no
        # default that could be right — «the active profile» is exactly the module-level
        # answer `docs/research/profile-isolation.md` is a list of.
        profile = str(profile or "")
        if not profile:
            raise ValueError("a store belongs to a profile; none was named")
        self.path = path
        self.profile = profile
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
        # SQLite's own LOWER() is ASCII-only, and most of what this panel stores is not
        # — so the case-folded columns are folded in Python on the way in. A MIGRATION
        # has no Python to reach for, so the same fold is lent to SQL here. Deterministic
        # on purpose: it lets SQLite use it in an index or a partial one.
        conn.create_function("fold", 1, _fold, deterministic=True)
        # …and the same fold with the accents dropped, which is what the search box
        # compares (#2385, `panel/runtime/players.py::flatten`).
        conn.create_function("flat", 1, _flat, deterministic=True)
        with self._lock:
            self._open.append(conn)
        self._local.conn = conn
        if not self._migrated:
            self._migrate(conn)
        self._scope(conn)
        return conn

    def _scope(self, conn: sqlite3.Connection) -> None:
        """Hang this profile's TEMP VIEWS on one connection (:data:`PROFILE_COLUMN`).

        Per connection because a temp view is per connection, and that is the useful
        half: two profiles sharing one file in one process each get their own `players`,
        and neither of them can name the other's rows by accident.
        """
        literal = "'" + self.profile.replace("'", "''") + "'"
        have = {row[0] for row in conn.execute(
            "SELECT name FROM main.sqlite_master WHERE type = 'table'")}
        for view, table in SCOPED_TABLES.items():
            # Only over a table that is there. A store built on a test's own schema
            # (`Store(path, profile, migrations=…)`) has none of these, and a view over
            # a missing table would make opening it an error rather than a smaller
            # database.
            if table in have:
                conn.execute(f"CREATE TEMP VIEW IF NOT EXISTS {view} AS "
                             f"SELECT * FROM main.{table} WHERE profile = {literal}")

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
            conn.execute(META_UPSERT, (self.profile, str(key), str(value)))

    # -- a whole-list checkpoint, kept as one row --------------------------------------
    # -- a day's statistic, kept as a history (#2705) ---------------------------------
    def day_stat_set(self, day: str, name: str, value) -> None:
        """Write `value` for this profile's `day` — the LAST word about that day.

        For a reading rather than a count: a benchmark taken twice today is the machine
        as it is now, not twice as fast. A tally uses :meth:`day_stat_add`.

        OFF THE CALLER'S THREAD, through the writer (`CLAUDE.md`: «the write goes through
        `store.submit`, never straight from Tk»). A statistic is never what a caller is
        waiting on, so nobody pays a transaction for it.
        """
        stamp = int(time.time())
        row = (self.profile, str(day), str(name), float(value), stamp)

        def job(conn):
            conn.execute(
                "INSERT INTO all_day_stats(profile, day, name, value, at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(profile, day, name) DO UPDATE SET "
                "value = excluded.value, at = excluded.at", row)

        self.submit(job)

    def day_stat_add(self, day: str, name: str, amount=1) -> None:
        """Add to this profile's tally for `day`, starting it at zero if it is new.

        THE UPSERT IS THE WHOLE POINT: it cannot reach yesterday and it cannot reach
        another account, so a day turning over is a new ROW rather than a counter being
        wiped. «Сегодня» stays a `SELECT` and the history is the by-product.
        """
        stamp = int(time.time())
        row = (self.profile, str(day), str(name), float(amount), stamp)

        def job(conn):
            conn.execute(
                "INSERT INTO all_day_stats(profile, day, name, value, at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(profile, day, name) DO UPDATE SET "
                "value = all_day_stats.value + excluded.value, at = excluded.at", row)

        self.submit(job)

    def day_stat(self, day: str, name: str, default=0.0) -> float:
        """What this profile's `day` says about `name`, or `default` if it says nothing."""
        row = self.read().execute(
            "SELECT value FROM day_stats WHERE day = ? AND name = ?",
            (str(day), str(name))).fetchone()
        return float(row["value"]) if row is not None else float(default)

    def day_stat_history(self, name: str, limit: int = 90) -> list:
        """`[(day, value, at), …]` newest first — the graph the rule exists for."""
        rows = self.read().execute(
            "SELECT day, value, at FROM day_stats WHERE name = ? "
            "ORDER BY day DESC LIMIT ?", (str(name), int(limit))).fetchall()
        return [(str(r["day"]), float(r["value"]), int(r["at"])) for r in rows]

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
            conn.execute(BLOB_UPSERT, (self.profile, str(name), payload, stamp))

    def blob_submit(self, name: str, value) -> None:
        """Checkpoint `value` under `name` OFF THE CALLER'S THREAD (#2660).

        Same row, same shape, same replace-the-lot semantics as :meth:`blob_set` — the
        difference is who pays. The ★ list, the ghost map and the world pages checkpoint
        themselves every time a capture tick moves a row, which on a busy map is every
        few hundred milliseconds, and they do it from the Tk thread: the serialisation
        and the COMMIT are milliseconds each and they are milliseconds the window is not
        drawing in. Handed to the writer, they are batched with whatever else is queued
        and cost the page nothing.

        THE VALUE MUST NOT BE MUTATED AFTERWARDS — it is serialised later, on the writer.
        Every caller here builds a fresh snapshot for the purpose, which is the only
        shape this is for. When the very next thing a caller does is READ the blob back,
        use :meth:`blob_set`: a queued write has not landed yet.
        """
        profile, key = self.profile, str(name)

        def job(conn) -> None:
            conn.execute(BLOB_UPSERT, (profile, key,
                                       json.dumps(value, ensure_ascii=False),
                                       int(time.time())))

        self.submit(job)

    # -- the monsters the client has drawn (#1963) -------------------------------------
    #
    # A ROW at a time, and that is the whole difference from the blob this replaced: a
    # poll writes what it just saw, not the thirty thousand rows that were already there.
    # Every write here goes through :meth:`submit`, so the Tk thread hands the rows over
    # and returns — nothing on this page is worth a frozen window.
    MONSTER_COLUMNS = ("uuid", "server", "x", "y", "level", "seen_at",
                       "expires_at", "completed_at", "until_key", "monster_type",
                       "kind_name", "cfg_id", "source", "point_id", "game_uuid")

    #: …and the two statements that write them, with `profile` in front of the lot. The
    #: rows handed to either of these come from :meth:`_monster_values`, which puts this
    #: store's profile at the head of every tuple — so there is no call site here that
    #: could pass the columns without it.
    MONSTER_INSERT = ("INSERT INTO all_monsters(profile, "
                      + ", ".join(MONSTER_COLUMNS) + ") VALUES("
                      + ", ".join("?" * (len(MONSTER_COLUMNS) + 1)) + ")")
    MONSTER_REPLACE = "INSERT OR REPLACE " + MONSTER_INSERT[len("INSERT "):]

    def _monster_values(self, rows) -> list:
        """The rows as tuples in :data:`MONSTER_COLUMNS` order, skipping the keyless."""
        out = []
        for row in rows or ():
            uuid = str(row.get("uuid") or "")
            if not uuid:
                continue
            values = [self.profile, uuid]
            for name in self.MONSTER_COLUMNS[1:]:
                value = row.get(name)
                out_value = value
                if name in ("kind_name", "source", "until_key", "game_uuid"):
                    out_value = None if value is None else str(value)
                elif value is not None:
                    try:
                        out_value = int(value)
                    except (TypeError, ValueError):
                        out_value = None
                values.append(out_value)
            out.append(tuple(values))
        return out

    def monsters_upsert(self, rows) -> None:
        """Write these sightings, leaving every other row alone.

        `game_uuid` is COALESCEd rather than overwritten, for the same reason the page
        never clears it in the model (#1523): a lap of the drawn clones re-sees a tile
        the world register had already named and knows no uuid of its own, and letting
        that read blank the column would take the march away from a row that had one.
        """
        values = self._monster_values(rows)
        if not values:
            return
        sets = ", ".join(f"{c} = excluded.{c}" for c in self.MONSTER_COLUMNS[1:]
                         if c != "game_uuid")
        sql = (f"{self.MONSTER_INSERT} "
               f"ON CONFLICT(profile, uuid) DO UPDATE SET {sets}, "
               f"game_uuid = COALESCE(excluded.game_uuid, all_monsters.game_uuid)")
        self.submit(lambda conn: conn.executemany(sql, values))

    def monsters_replace(self, rows) -> None:
        """The whole list, replaced — what «Очистить список» needs and nothing else."""
        values = self._monster_values(rows)
        sql = self.MONSTER_REPLACE
        profile = self.profile

        def job(conn) -> None:
            conn.execute("DELETE FROM all_monsters WHERE profile = ?", (profile,))
            if values:
                conn.executemany(sql, values)

        self.submit(job)

    def monsters_prune(self, cutoff: float) -> None:
        """Drop every sighting older than `cutoff` — the ageing, as one statement."""
        self.submit(lambda conn: conn.execute(
            "DELETE FROM all_monsters WHERE profile = ?"
            "   AND (seen_at IS NULL OR seen_at < ?)",
            (self.profile, int(cutoff))))

    def monsters_all(self, *, cutoff: float | None = None) -> list:
        """Every sighting still worth drawing, freshest first, as plain dicts."""
        sql = f"SELECT {', '.join(self.MONSTER_COLUMNS)} FROM monsters"
        args: tuple = ()
        if cutoff is not None:
            sql += " WHERE seen_at >= ?"
            args = (int(cutoff),)
        sql += " ORDER BY seen_at DESC"
        return [dict(zip(self.MONSTER_COLUMNS, row))
                for row in self.read().execute(sql, args).fetchall()]

    def monsters_count(self) -> int:
        row = self.read().execute("SELECT COUNT(*) FROM monsters").fetchone()
        return int(row[0]) if row else 0

    # -- the reward popups the client raised, and what the panel was doing (#2027) -----
    #
    # A DRAIN at a time, off whatever thread the log line arrived on — which is why these
    # go through :meth:`submit` like the monsters do: a reward can land while the person
    # is dragging the map, and a write on the Tk thread is a frame nobody gets back.
    REWARD_COLUMNS = ("at", "seen_at", "kind", "source", "items", "why")

    REWARD_INSERT = ("INSERT INTO all_reward_popups(profile, "
                     + ", ".join(REWARD_COLUMNS) + ") VALUES("
                     + ", ".join("?" * (len(REWARD_COLUMNS) + 1)) + ")")

    def rewards_add(self, rows) -> None:
        """Book these rows. Each is a dict in :data:`REWARD_COLUMNS`; `why` may be empty.

        Empty `why` is «не знаю» and is stored as such: the client cannot say why a
        reward arrived, so the only honest source for it is what the panel was playing —
        and when it was playing nothing, the honest answer is nothing.
        """
        values = []
        for row in rows or ():
            values.append((self.profile,
                           int(row.get("at") or 0), int(row.get("seen_at") or 0),
                           str(row.get("kind") or ""), str(row.get("source") or ""),
                           str(row.get("items") or ""), str(row.get("why") or "")))
        if not values:
            return
        sql = self.REWARD_INSERT

        def job(conn) -> None:
            conn.executemany(sql, values)
        self.submit(job)

    def rewards_recent(self, limit: int = 50, *, kind: str = "") -> list:
        """The newest rows first, as plain dicts. `kind` narrows to one sort of row."""
        sql = f"SELECT {', '.join(self.REWARD_COLUMNS)} FROM reward_popups"
        args: tuple = ()
        if kind:
            sql += " WHERE kind = ?"
            args = (str(kind),)
        # A VIEW has no `rowid`, so the game's own stamp is the tie-break —
        # several rows of one drain share a second of panel clock.
        sql += " ORDER BY seen_at DESC, at DESC LIMIT ?"
        rows = self.read().execute(sql, args + (int(limit),)).fetchall()
        return [dict(zip(self.REWARD_COLUMNS, row)) for row in rows]

    def rewards_count(self, *, kind: str = "") -> int:
        sql = "SELECT COUNT(*) FROM reward_popups"
        args: tuple = ()
        if kind:
            sql += " WHERE kind = ?"
            args = (str(kind),)
        row = self.read().execute(sql, args).fetchone()
        return int(row[0]) if row else 0

    def rewards_prune(self, cutoff: float) -> None:
        """Forget rows older than `cutoff` (a `time.time`). Nothing else touches them."""
        profile, when = self.profile, int(cutoff)

        def job(conn) -> None:
            conn.execute("DELETE FROM all_reward_popups WHERE profile = ? "
                         "AND seen_at < ?", (profile, when))
        self.submit(job)

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


class PanelStore(Store):
    """The one database opened for the PANEL — the window's own state, and the LIST.

    Two quite different things, and it holds both because both are answers to «what does
    this machine have» rather than «what does this account have»:

    * the panel-wide settings — which profile is showing, which are open, the language,
      the web block, the update channel — kept as ordinary blobs under
      :data:`PANEL_SCOPE`, so the same `blob_get`/`blob_set` that a profile uses works
      here with no second mechanism to keep right;
    * the `profiles` table, which since #2025 is WHAT MAKES A PROFILE A PROFILE. It has
      no `profile` column and no temp view over it: the list of accounts is not any one
      account's, and a profile's own store cannot reach it at all.
    """

    def __init__(self, path: str, *, migrations: tuple = MIGRATIONS) -> None:
        super().__init__(path, PANEL_SCOPE, migrations=migrations)

    # -- the list of accounts ----------------------------------------------------------
    def profiles(self) -> list:
        """Every profile this panel has, in the order the database keeps them."""
        return [row["name"] for row in
                self.read().execute("SELECT name FROM profiles ORDER BY name")]

    def profile_exists(self, name: str) -> bool:
        return self.read().execute("SELECT 1 FROM profiles WHERE name = ?",
                                   (str(name),)).fetchone() is not None

    def profile_add(self, name: str, config=None) -> bool:
        """Register `name`, leaving an existing one alone. True when it was new."""
        payload = json.dumps(config if isinstance(config, dict) else {},
                             ensure_ascii=False)
        with self.write() as conn:
            cur = conn.execute(
                "INSERT INTO profiles(name, config, created_at) VALUES(?, ?, ?) "
                "ON CONFLICT(name) DO NOTHING",
                (str(name), payload, int(time.time())))
        return bool(cur.rowcount)

    def profile_config(self, name: str) -> dict:
        """This profile's own tab blocks — `{}` when it has none and when there is no
        such profile, which are the same answer `config.json` gave by being absent."""
        row = self.read().execute("SELECT config FROM profiles WHERE name = ?",
                                  (str(name),)).fetchone()
        if row is None:
            return {}
        try:
            value = json.loads(row["config"])
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def profile_set_config(self, name: str, config: dict) -> None:
        """Write this profile's own blocks, registering it if it is new."""
        payload = json.dumps(config if isinstance(config, dict) else {},
                             ensure_ascii=False)
        with self.write() as conn:
            conn.execute(
                "INSERT INTO profiles(name, config, created_at) VALUES(?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET config = excluded.config",
                (str(name), payload, int(time.time())))

    def profile_rename(self, old: str, new: str) -> None:
        """Move an account — the row AND every row it owns — in ONE transaction.

        This is the whole reason the person asked for one database (#2025): a rename
        used to be a directory move, and a directory move that half-happens leaves an
        account whose settings and whose data disagree about its own name.
        """
        old, new = str(old), str(new)
        with self.write() as conn:
            conn.execute("UPDATE profiles SET name = ? WHERE name = ?", (new, old))
            for table in SCOPED_TABLES.values():
                conn.execute(f"UPDATE {table} SET profile = ? WHERE profile = ?",
                             (new, old))

    def profile_drop(self, name: str) -> None:
        """Forget an account and everything of its own, in one transaction."""
        name = str(name)
        with self.write() as conn:
            conn.execute("DELETE FROM profiles WHERE name = ?", (name,))
            for table in SCOPED_TABLES.values():
                conn.execute(f"DELETE FROM {table} WHERE profile = ?", (name,))


#: The sentinel that ends the writer thread. Not `None`, which a caller could submit.
_STOP = object()


#: The two upserts that reach a scoped table by its REAL name, with the profile as the
#: first parameter. Written once here rather than at each call site, because «the same
#: statement with the profile left off» is precisely the mistake `PROFILE_COLUMN` exists
#: to make impossible — a caller cannot leave off a parameter the statement demands.
META_UPSERT = ("INSERT INTO all_meta(profile, key, value) VALUES(?, ?, ?) "
               "ON CONFLICT(profile, key) DO UPDATE SET value = excluded.value")
BLOB_UPSERT = ("INSERT INTO all_blobs(profile, name, data, updated_at) "
               "VALUES(?, ?, ?, ?) ON CONFLICT(profile, name) DO UPDATE SET "
               "data = excluded.data, updated_at = excluded.updated_at")


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
        conn.execute(META_UPSERT,
                     (store.profile, f"import:{mark}", str(int(time.time()))))
    try:
        if os.path.exists(path):
            os.replace(path, path + IMPORTED_SUFFIX)
    except OSError:
        pass
    return count


def blob_import_once(store: Store, name: str, path: str) -> bool:
    """Move one whole-list checkpoint file into `blobs`, exactly once, keeping the file.

    The shared way every ★-style list adopts the database: `panel/tabs/secret_tasks/
    tab.py` (name `secret_tasks_state`), `.../ghost.py` (`ghost_map_state`) and
    `panel/rally_limits.py` (`rally_counts`) all call this once, at restore, before
    reading `store.blob_get(name)` — so a profile opened by a NEWER panel for the first
    time carries its file across instead of starting blank, and every later start finds
    the mark and does nothing.

    The monster page used to be on this list under `world_state_monsters`; it has a
    table of its own since #1963 and comes across through
    :func:`monsters_import_blob_once` instead.
    """
    def load(p):
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def insert(conn, value) -> int:
        conn.execute(BLOB_UPSERT, (store.profile, str(name),
                                   json.dumps(value, ensure_ascii=False),
                                   int(time.time())))
        return 1

    return bool(import_once(store, f"blob:{name}", path, load, insert))


#: The tables a profile's own database held, and the columns to carry across. Spelled
#: out rather than `SELECT *`, because the shared table has `profile` in front and the
#: old one does not — and because a column added to `all_…` later must not silently
#: change what an old file is read for.
_LEGACY_TABLES = {
    "meta": ("key", "value"),
    "players": None,             # every column it has — worked out from the old file
    "blobs": ("name", "data", "updated_at"),
    "secret_days": ("server", "day", "state", "source", "stars", "tiles", "seen_at"),
    "monsters": None,
}


def import_profile_db_once(store: Store, path: str) -> dict:
    """Carry ONE profile's own old `panel.db` into the shared one, exactly once (#2025).

    `store` is that profile's view of the shared database; `path` is the file that used
    to be its own. Returns `{table: rows}` for what was carried — `{}` when there was
    nothing to do, which is also what every later call returns.

    **This is a move of DATA, not of a schema.** What is in one of these files is the
    register of players, the monsters the client drew, the ★ list, the ghost tiles, the
    map coverage and the day counters — everything the panel would otherwise appear to
    have forgotten the first time it opened on one database. Losing any of it is not
    recoverable by looking again: the register only ever grows, and the day counters are
    what stop a quota being spent twice.

    The order is the safety of it, and it is the same order every other import here uses:

    1. the mark is checked, in THIS profile's scope — an import that has run does not run
       again, so nothing written since can be overwritten by a stale file;
    2. the rows are read and written with `INSERT OR IGNORE`, so anything already in the
       shared database wins over what the old file says, and the mark lands in the SAME
       transaction — a panel killed halfway leaves neither and the next start imports
       cleanly rather than half again;
    3. only THEN is the file renamed to `panel.db.imported`, with its WAL and shared-memory
       companions, and a rename that fails is not an error — the mark already says the
       work is done.

    The file is KEPT. An import that turns out to have misread a column is answered by
    opening it; a delete is answered by nothing.
    """
    if store.meta_get("import:profile_db"):
        return {}
    if not os.path.exists(path) or os.path.abspath(path) == os.path.abspath(store.path):
        # No old file — a profile made after #2025. NOT marked done: a file that turns
        # up later (a folder copied in from another machine) must still be imported.
        return {}
    # Opened with the OLD history, so a profile last written by an older panel is
    # brought up to the shape this reads and not one step further.
    old = Store(path, store.profile, migrations=LEGACY_MIGRATIONS)
    counts: dict = {}
    try:
        source = old.connect()
        have = {row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        payload = {}
        for table, columns in _LEGACY_TABLES.items():
            if table not in have:
                continue
            if columns is None:
                columns = tuple(row[1] for row in
                                source.execute(f"PRAGMA table_info({table})"))
            names = ", ".join(columns)
            rows = [tuple(row) for row in
                    source.execute(f"SELECT {names} FROM {table}")]
            if rows:
                payload[table] = (columns, rows)
        if payload:
            with store.write() as conn:
                # ASKED AGAIN, INSIDE THE LOCK, and it is not superstition: two runtimes
                # in one window can build a store for the same profile at the same
                # moment, both read «not imported» and both do the work. `INSERT OR
                # IGNORE` made that harmless — it was measured live on a profile of
                # 23 386 players and not one row doubled — but it is twenty thousand
                # rows written twice, and with two PANELS it would be two processes.
                # `BEGIN IMMEDIATE` is already held here, so the loser reads the mark.
                beaten = conn.execute(
                    "SELECT 1 FROM all_meta WHERE profile = ? AND key = ?",
                    (store.profile, "import:profile_db")).fetchone() is not None
                for table, (columns, rows) in ({} if beaten else payload).items():
                    target = SCOPED_TABLES[table]
                    # Only the columns the shared table actually has: an old file cannot
                    # carry one it never knew, and must not fail over one we dropped.
                    known = {row[1] for row in conn.execute(
                        f"PRAGMA table_info({target})")}
                    keep = [i for i, c in enumerate(columns) if c in known]
                    names = ", ".join(columns[i] for i in keep)
                    marks = ", ".join("?" * (len(keep) + 1))
                    conn.executemany(
                        f"INSERT OR IGNORE INTO {target}(profile, {names}) "
                        f"VALUES({marks})",
                        [(store.profile,) + tuple(row[i] for i in keep)
                         for row in rows])
                    counts[table] = len(rows)
                if not beaten:
                    conn.execute(META_UPSERT, (store.profile, "import:profile_db",
                                               str(int(time.time()))))
        else:
            store.meta_set("import:profile_db", str(int(time.time())))
    finally:
        old.close()
    for suffix in ("", "-wal", "-shm"):
        try:
            if os.path.exists(path + suffix):
                os.replace(path + suffix, path + IMPORTED_SUFFIX + suffix)
        except OSError:
            pass
    return counts


def monsters_import_blob_once(store: Store, name: str = "world_state_monsters",
                              path: str = "") -> int:
    """Carry the monster page's OLD whole-list checkpoint into its own table, once.

    Two homes to come from, in the order a profile could be in (#1963):

    1. the `blobs` row the page kept between #1465 and #1963 — the 9.8 MB of JSON this
       change exists to stop rewriting;
    2. failing that, the JSON FILE that predates #1465, for a profile that has been shut
       since before the blob existed.

    The blob row is dropped in the same transaction as the mark, so the megabytes do not
    sit in the database for ever pretending to be a checkpoint somebody still reads. The
    FILE is kept, renamed, exactly like every other import here — a person can open it.

    Returns how many rows were carried across; 0 when there was nothing to do, which is
    also what a second call returns.
    """
    if store.meta_get("import:monsters"):
        return 0
    rows = store.blob_get(name)
    from_blob = isinstance(rows, list)
    if not from_blob and path:
        try:
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError):
            rows = None
    if not isinstance(rows, list):
        # Nothing anywhere. NOT marked done: a profile whose page has simply never been
        # filled must still import if an old checkpoint turns up on the next start.
        return 0
    values = store._monster_values(r for r in rows if isinstance(r, dict))
    with store.write() as conn:
        if values:
            conn.executemany(store.MONSTER_REPLACE, values)
        conn.execute("DELETE FROM all_blobs WHERE profile = ? AND name = ?",
                     (store.profile, str(name)))
        conn.execute(META_UPSERT,
                     (store.profile, "import:monsters", str(int(time.time()))))
    if not from_blob and path:
        try:
            if os.path.exists(path):
                os.replace(path, path + IMPORTED_SUFFIX)
        except OSError:
            pass
    return len(values)
