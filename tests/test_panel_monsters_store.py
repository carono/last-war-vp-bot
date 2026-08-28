r"""The monster page's own table (`panel/runtime/store.py`, #1963).

What this pins is the reason the table exists, not «SQLite works». The page used to keep
its list as ONE row of `blobs` — the whole list, re-serialised and written synchronously
from the Tk thread on every poll. Measured on a live profile: 31 828 rows, 9.8 MB of
JSON, 0.20–0.32 s a write, five times a minute, per profile with the follow clock on.

So the promises here are the ones that make a row-at-a-time store worth having:

  * **a poll writes what it saw**, and leaves every other row where it was;
  * **the game's own uuid survives a read that does not carry one** — a lap of the drawn
    clones re-sees a tile the world register had already named, and blanking the column
    would take the march away from a row that had one (#1523);
  * **the ageing is a DELETE**, not a rewrite of everything that survived it;
  * **the old homes come across, once** — the `blobs` row of #1465 and the JSON file
    that predates it — and the megabytes do not stay behind pretending to be a
    checkpoint somebody still reads.

Needs neither Tk, a display nor a game.

    C:\Python312\python.exe tests\test_panel_monsters_store.py
    python3 tests/test_panel_monsters_store.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime.store import (MIGRATIONS, Store,                   # noqa: E402
                                 monsters_import_blob_once)


def _store() -> Store:
    """A real database on the real schema — the table is the thing under test."""
    tmp = tempfile.mkdtemp()
    return Store(str(Path(tmp) / "panel.db"), "Player1", migrations=MIGRATIONS)


def _row(uuid: str, **over) -> dict:
    row = {"uuid": uuid, "server": 100, "x": 500, "y": 500, "level": 5,
           "seen_at": int(time.time()), "expires_at": None, "completed_at": None,
           "until_key": None, "monster_type": 7, "kind_name": "monster_a",
           "cfg_id": 5101001, "source": "world", "point_id": 225940,
           "game_uuid": "1000000000000001"}
    row.update(over)
    return row


def _by_uuid(store: Store) -> dict:
    return {r["uuid"]: r for r in store.monsters_all()}


# ---------------------------------------------------------------------------
# a poll writes what it saw
# ---------------------------------------------------------------------------
def test_an_upsert_touches_its_own_rows_and_no_others() -> None:
    store = _store()
    store.monsters_upsert([_row("100:1"), _row("100:2")])
    store.flush()
    store.monsters_upsert([_row("100:2", level=42)])
    store.flush()
    rows = _by_uuid(store)
    assert len(rows) == 2, f"expected the two rows, got {sorted(rows)}"
    assert rows["100:2"]["level"] == 42, "the sighting did not update the row"
    assert rows["100:1"]["level"] == 5, "a row nobody saw was rewritten anyway"
    store.close()


def test_the_games_own_uuid_survives_a_read_that_does_not_carry_one() -> None:
    """#1523's rule, now enforced by the column instead of only by the model."""
    store = _store()
    store.monsters_upsert([_row("100:1", game_uuid="1000000000000001")])
    store.flush()
    store.monsters_upsert([_row("100:1", source="lap", game_uuid=None)])
    store.flush()
    row = _by_uuid(store)["100:1"]
    assert row["game_uuid"] == "1000000000000001", \
        f"the lap blanked the uuid a march needs: {row['game_uuid']!r}"
    assert row["source"] == "lap", "everything else should still be the newer reading"
    store.close()


def test_a_row_with_no_key_is_dropped_rather_than_stored_under_nothing() -> None:
    store = _store()
    store.monsters_upsert([_row(""), {"server": 100}, _row("100:1")])
    store.flush()
    assert sorted(_by_uuid(store)) == ["100:1"], "a keyless reading got in"
    store.close()


# ---------------------------------------------------------------------------
# the ageing is a DELETE
# ---------------------------------------------------------------------------
def test_pruning_drops_the_stale_and_keeps_the_fresh() -> None:
    now = int(time.time())
    store = _store()
    store.monsters_upsert([_row("100:old", seen_at=now - 3600),
                           _row("100:new", seen_at=now),
                           _row("100:blank", seen_at=None)])
    store.flush()
    store.monsters_prune(now - 900)
    store.flush()
    left = sorted(_by_uuid(store))
    assert left == ["100:new"], f"the ageing kept the wrong rows: {left}"
    store.close()


def test_reading_back_can_ask_for_the_fresh_ones_only() -> None:
    now = int(time.time())
    store = _store()
    store.monsters_upsert([_row("100:old", seen_at=now - 3600), _row("100:new")])
    store.flush()
    fresh = [r["uuid"] for r in store.monsters_all(cutoff=now - 900)]
    assert fresh == ["100:new"], f"the cutoff let a stale sighting through: {fresh}"
    assert store.monsters_count() == 2, "the cutoff must narrow the READ, not delete"
    store.close()


def test_replacing_the_list_is_what_empties_the_table() -> None:
    """«Очистить список» — the press whose whole point is that the disk empties too."""
    store = _store()
    store.monsters_upsert([_row("100:1"), _row("100:2")])
    store.flush()
    store.monsters_replace([])
    store.flush()
    assert store.monsters_count() == 0, "the press left rows behind on disk"
    store.close()


# ---------------------------------------------------------------------------
# the old homes come across, once
# ---------------------------------------------------------------------------
def test_the_old_blob_is_carried_across_and_then_is_gone() -> None:
    store = _store()
    store.blob_set("world_state_monsters", [_row("100:1"), _row("100:2")])
    moved = monsters_import_blob_once(store)
    assert moved == 2, f"the import carried {moved} rows, not the two in the blob"
    assert sorted(_by_uuid(store)) == ["100:1", "100:2"], "the rows did not arrive"
    assert store.blob_get("world_state_monsters") is None, \
        "the megabytes stayed behind, still looking like a live checkpoint"
    store.close()


def test_the_import_runs_once_and_never_overwrites_what_happened_since() -> None:
    store = _store()
    store.blob_set("world_state_monsters", [_row("100:1", level=5)])
    monsters_import_blob_once(store)
    store.monsters_upsert([_row("100:1", level=42)])
    store.flush()
    store.blob_set("world_state_monsters", [_row("100:1", level=5)])
    assert monsters_import_blob_once(store) == 0, "the import ran a second time"
    assert _by_uuid(store)["100:1"]["level"] == 42, \
        "a stale checkpoint overwrote what the page has read since"
    store.close()


def test_a_profile_older_than_the_blob_imports_from_its_file_and_keeps_it() -> None:
    store = _store()
    path = str(Path(tempfile.mkdtemp()) / "world_state_monsters.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([_row("100:1")], fh)
    assert monsters_import_blob_once(store, "world_state_monsters", path) == 1
    assert sorted(_by_uuid(store)) == ["100:1"], "the file did not come across"
    assert Path(path + ".imported").exists(), \
        "the file it read was not kept beside the database"
    store.close()


def test_nothing_anywhere_is_not_marked_done() -> None:
    """An empty read concludes nothing — a checkpoint appearing later must still land."""
    store = _store()
    assert monsters_import_blob_once(store) == 0
    store.blob_set("world_state_monsters", [_row("100:1")])
    assert monsters_import_blob_once(store) == 1, \
        "an empty first look marked the import done for ever"
    store.close()


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
