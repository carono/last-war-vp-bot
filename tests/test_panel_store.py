r"""The one door to a profile's database (`panel/runtime/store.py`, #1398).

What this pins is not «SQLite works». It is the four promises the layer was asked for,
each of which is a way the old whole-file JSON could quietly lose data or freeze the
window:

  * **a versioned schema**, migrated forward once and never re-run, and a database from
    a NEWER panel refused rather than migrated backwards;
  * **concurrent writers**, threads and separate PROCESSES both, with nobody raising
    «database is locked» and nobody losing a row;
  * **batching** — a burst of jobs costs one transaction, which is the whole answer to
    «a lap of the map hands over thousands of rows»;
  * **all or nothing** — a transaction that raises leaves the database exactly as it was,
    and an import that is interrupted leaves neither the rows nor the mark that says
    they are in.

And the two rules the data itself has, which the database must not become a new way
around: an import loses nothing, and the file it read stays on disk beside it.

Needs neither Tk, a display nor a game.

    C:\Python312\python.exe tests\test_panel_store.py
    python3 tests/test_panel_store.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import store as storemod                          # noqa: E402
from panel.runtime.store import Store, StoreTooNew, import_once      # noqa: E402

#: A schema history of our own, so the tests do not have to be rewritten every time the
#: real one grows a version. Same shape: index 0 is version 1.
_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);",
    "CREATE TABLE rows_ (uid TEXT PRIMARY KEY, name TEXT);",
    "ALTER TABLE rows_ ADD COLUMN level INTEGER;",
)


def _store(schema=_SCHEMA) -> Store:
    tmp = tempfile.mkdtemp()
    return Store(str(Path(tmp) / "panel.db"), migrations=schema)


# ---------------------------------------------------------------------------
# the schema is a history, not a statement
# ---------------------------------------------------------------------------
def test_a_fresh_database_lands_on_the_newest_version() -> None:
    store = _store()
    assert store.version() == len(_SCHEMA), \
        "a new database must be migrated all the way up on its first connect"
    cols = {r["name"] for r in store.read().execute("PRAGMA table_info(rows_)")}
    assert cols == {"uid", "name", "level"}, \
        f"the third migration did not run: {cols}"
    store.close()


def test_an_old_database_is_carried_forward_and_keeps_its_rows() -> None:
    """The point of versions: an upgrade adds the column and touches nothing else."""
    old = _store(_SCHEMA[:2])
    with old.write() as conn:
        conn.execute("INSERT INTO rows_(uid, name) VALUES(?, ?)", ("1", "Player1"))
    assert old.version() == 2
    old.close()

    new = Store(old.path, migrations=_SCHEMA)
    assert new.version() == 3, "the upgrade did not run"
    row = new.read().execute("SELECT * FROM rows_").fetchone()
    assert (row["uid"], row["name"], row["level"]) == ("1", "Player1", None), \
        "the upgrade lost or changed a row it should not have touched"
    new.close()


def test_a_newer_database_is_refused_rather_than_migrated_backwards() -> None:
    """A panel that does not know a column must not run against it — and never DROP it.

    «Handle it gracefully» here means silently ignoring what a newer version wrote, and
    the graceful-looking alternative (migrate down) deletes it. Stopping costs an update.
    """
    ahead = _store(_SCHEMA)
    ahead.connect()                       # a Store does not touch the file until asked
    ahead.close()
    behind = Store(ahead.path, migrations=_SCHEMA[:1])
    try:
        behind.connect()
    except StoreTooNew:
        pass
    else:
        raise AssertionError("a database from a newer panel was opened anyway")


def test_a_migration_runs_once_however_many_threads_open_it() -> None:
    """Two panels opening one profile at the same moment is a real thing (a standalone
    tab is a second process), and «both read version 0» is how a table gets created
    twice. The write lock is what stops it — a re-run raises «table already exists»."""
    tmp = tempfile.mkdtemp()
    path = str(Path(tmp) / "panel.db")
    errors: list = []

    def open_it() -> None:
        try:
            Store(path, migrations=_SCHEMA).connect()
        except Exception as exc:                                     # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=open_it) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"opening one database eight times over raised: {errors}"


# ---------------------------------------------------------------------------
# several writers, and none of them «database is locked»
# ---------------------------------------------------------------------------
def test_many_threads_write_and_not_one_row_is_lost() -> None:
    store = _store()
    errors: list = []

    def writer(base: int) -> None:
        try:
            for i in range(50):
                with store.write() as conn:
                    conn.execute("INSERT INTO rows_(uid, name) VALUES(?, ?)",
                                 (f"{base}-{i}", "Player1"))
        except Exception as exc:                                     # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"a concurrent write raised: {errors}"
    total = store.read().execute("SELECT COUNT(*) c FROM rows_").fetchone()["c"]
    assert total == 400, f"eight threads wrote 400 rows and {total} arrived"
    store.close()


def test_a_second_process_writes_the_same_database() -> None:
    """A standalone tab (`python -m panel.tabs.players`) IS a second process on the same
    profile directory. WAL plus a busy timeout is what makes that ordinary rather than a
    «database is locked» somebody sees once a week and cannot reproduce."""
    store = _store()
    with store.write() as conn:
        conn.execute("INSERT INTO rows_(uid, name) VALUES('mine', 'Player1')")
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from panel.runtime.store import Store\n"
        "s = Store(%r, migrations=%r)\n"
        "with s.write() as c:\n"
        "    c.executemany('INSERT INTO rows_(uid, name) VALUES(?, ?)',\n"
        "                  [(f'theirs-{i}', 'Player2') for i in range(100)])\n"
        "s.close()\n" % (str(_REPO), store.path, _SCHEMA)
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, f"the second process failed: {done.stderr}"
    total = store.read().execute("SELECT COUNT(*) c FROM rows_").fetchone()["c"]
    assert total == 101, f"101 rows were written by two processes and {total} arrived"
    store.close()


def test_the_database_is_in_wal_mode() -> None:
    """Not a style choice: under the rollback journal a write locks the whole file for
    its duration, which is the freeze this layer exists to remove."""
    store = _store()
    mode = store.read().execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal", f"journal_mode is {mode!r}, not WAL"
    store.close()


# ---------------------------------------------------------------------------
# batching, which is the measurement the change was asked for
# ---------------------------------------------------------------------------
def test_a_burst_of_jobs_costs_one_transaction() -> None:
    """A lap of the map hands over thousands of rows in a burst. The cost of a burst is
    the number of COMMITs, and if it were one per row this layer would be slower than
    the file it replaced."""
    store = _store()
    for i in range(500):
        store.submit(lambda conn, i=i: conn.execute(
            "INSERT INTO rows_(uid, name) VALUES(?, ?)", (str(i), "Player1")))
    assert store.flush(), "the writer thread did not drain in time"
    total = store.read().execute("SELECT COUNT(*) c FROM rows_").fetchone()["c"]
    assert total == 500, f"500 jobs were submitted and {total} rows arrived"
    assert store.batches_done < 100, \
        (f"500 queued jobs took {store.batches_done} transactions — they are not being "
         f"batched, which is the whole reason `submit` exists")
    store.close()


def test_one_bad_job_does_not_take_its_neighbours_with_it() -> None:
    """A batch is a convenience, never a shared fate: a job that fails must not delete
    the work of the ones that happened to be queued beside it."""
    store = _store()
    failures: list = []
    store._failed = failures.append                                 # noqa: SLF001
    store.submit(lambda conn: conn.execute(
        "INSERT INTO rows_(uid, name) VALUES('good-1', 'Player1')"))
    store.submit(lambda conn: conn.execute("INSERT INTO nosuchtable VALUES(1)"))
    store.submit(lambda conn: conn.execute(
        "INSERT INTO rows_(uid, name) VALUES('good-2', 'Player2')"))
    assert store.flush(), "the writer thread did not drain in time"
    uids = {r["uid"] for r in store.read().execute("SELECT uid FROM rows_")}
    assert uids == {"good-1", "good-2"}, \
        f"the good jobs did not survive their bad neighbour: {uids}"
    assert len(failures) == 1, f"the failure was not reported: {failures}"
    store.close()


# ---------------------------------------------------------------------------
# all or nothing
# ---------------------------------------------------------------------------
def test_a_transaction_that_raises_leaves_nothing_behind() -> None:
    store = _store()
    with store.write() as conn:
        conn.execute("INSERT INTO rows_(uid, name) VALUES('before', 'Player1')")
    try:
        with store.write() as conn:
            conn.executemany("INSERT INTO rows_(uid, name) VALUES(?, ?)",
                             [(str(i), "Player2") for i in range(100)])
            raise RuntimeError("the game went away halfway through")
    except RuntimeError:
        pass
    uids = {r["uid"] for r in store.read().execute("SELECT uid FROM rows_")}
    assert uids == {"before"}, \
        f"a rolled-back transaction left rows behind: {len(uids)} of them"
    store.close()


# ---------------------------------------------------------------------------
# moving a JSON file in, once, losing nothing
# ---------------------------------------------------------------------------
def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _insert(conn, rows) -> int:
    conn.executemany("INSERT OR REPLACE INTO rows_(uid, name) VALUES(?, ?)",
                     [(str(r["uid"]), r.get("name")) for r in rows])
    return len(rows)


def _written(directory: Path, rows) -> str:
    path = directory / "old.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return str(path)


def test_an_import_moves_every_row_and_keeps_the_file() -> None:
    """The file is INSURANCE and stays on disk. An import that misread a field is
    answered by opening it; a delete is answered by nothing."""
    store = _store()
    here = Path(store.path).parent
    rows = [{"uid": str(1000000000000000 + i), "name": f"Player{i}"} for i in range(500)]
    path = _written(here, rows)

    moved = import_once(store, "rows", path, _load, _insert)
    assert moved == 500, f"{moved} of 500 rows were imported"
    total = store.read().execute("SELECT COUNT(*) c FROM rows_").fetchone()["c"]
    assert total == 500, f"{total} of 500 rows are in the database"
    assert not os.path.exists(path), "the old file was left in place to be re-imported"
    kept = path + storemod.IMPORTED_SUFFIX
    assert os.path.exists(kept), "the old file was DELETED rather than kept beside"
    assert _load(kept) == rows, "the kept copy is not what was imported"
    store.close()


def test_an_import_runs_once_and_never_undoes_a_later_edit() -> None:
    """The second start must not put the file back over what a person has since done —
    the mark is what makes «import on first launch» safe to leave in the code for ever."""
    store = _store()
    here = Path(store.path).parent
    path = _written(here, [{"uid": "1", "name": "Player1"}])
    import_once(store, "rows", path, _load, _insert)
    with store.write() as conn:
        conn.execute("UPDATE rows_ SET name = 'renamed by a person' WHERE uid = '1'")
    # …and the file comes back, exactly as a restored backup or a stale copy would.
    _written(here, [{"uid": "1", "name": "Player1"}])

    again = import_once(store, "rows", path, _load, _insert)
    assert again == 0, "the import ran a second time"
    name = store.read().execute("SELECT name FROM rows_").fetchone()["name"]
    assert name == "renamed by a person", "a re-run import overwrote a person's edit"
    store.close()


def test_a_missing_or_broken_file_is_not_a_completed_import() -> None:
    """«The read came back empty» concludes nothing (`panel/kept.py`). Marking it done
    would ignore for ever a file that turns up a second later."""
    store = _store()
    here = Path(store.path).parent
    missing = str(here / "nothing.json")
    assert import_once(store, "rows", missing, _load, _insert) == 0
    assert store.meta_get("import:rows") is None, \
        "a missing file was recorded as an import that had been done"
    # …and now it exists.
    path = _written(here, [{"uid": "1", "name": "Player1"}])
    os.replace(path, missing)
    assert import_once(store, "rows", missing, _load, _insert) == 1, \
        "the file that turned up later was never imported"
    store.close()


def test_an_interrupted_import_leaves_neither_the_rows_nor_the_mark() -> None:
    """Half an import is the one outcome nobody can reason about. The rows and the mark
    that says they are in go in ONE transaction, so a panel killed halfway starts clean."""
    store = _store()
    here = Path(store.path).parent
    path = _written(here, [{"uid": str(i), "name": "Player1"} for i in range(10)])

    def explodes(conn, rows):
        _insert(conn, rows[:5])
        raise RuntimeError("killed halfway")

    try:
        import_once(store, "rows", path, _load, explodes)
    except RuntimeError:
        pass
    total = store.read().execute("SELECT COUNT(*) c FROM rows_").fetchone()["c"]
    assert total == 0, f"an interrupted import left {total} rows behind"
    assert store.meta_get("import:rows") is None, \
        "an interrupted import was marked as done — the rest would never arrive"
    assert os.path.exists(path), "an interrupted import moved the file away anyway"
    # And the next start does it properly.
    assert import_once(store, "rows", path, _load, _insert) == 10
    store.close()


# ---------------------------------------------------------------------------
# a profile is a whole panel of its own
# ---------------------------------------------------------------------------
def test_there_is_no_store_at_module_level() -> None:
    """A store belongs to a profile. One held in a module global belongs to whichever
    profile imported first, which is the whole of `docs/research/profile-isolation.md`."""
    for name, value in vars(storemod).items():
        assert not isinstance(value, Store), \
            (f"panel.runtime.store.{name} is a Store at module level — a profile's "
             f"database must be reached through `rt.store` and nowhere else")


def test_two_profiles_are_two_databases() -> None:
    a, b = _store(), _store()
    with a.write() as conn:
        conn.execute("INSERT INTO rows_(uid, name) VALUES('1', 'Player1')")
    assert b.read().execute("SELECT COUNT(*) c FROM rows_").fetchone()["c"] == 0, \
        "one profile's write turned up in another profile's database"
    a.close()
    b.close()


def _run() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:                              # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
