r"""The list that cannot be wiped by accident (`panel/kept.py`, #1282).

Three data losses in one day were one class: an empty or failed read used as authority to
delete rows somebody had paid for with laps of the map. #1272 fixed it for one list, in
prose. This is the same invariant as a TYPE, and what follows is what «in a type» has to
mean if it is to be worth more than the prose:

  * there is no `clear()` and no way to assign the contents — the wipe fails where it is
    written, not in production;
  * a removal names one of three reasons, and a store refuses the ones it did not
    declare;
  * «the read came back empty» is not one of the reasons, and merging an empty read
    removes nothing;
  * and the file on disk survives a restart, because a checkpoint nobody can read back
    protects nothing.

Needs neither Tk, a display nor a game.

    C:\Python312\python.exe tests\test_panel_kept.py
    python3 tests/test_panel_kept.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.kept import (ALL_REASONS, EXPIRED, GAME_SAID_GONE,  # noqa: E402
                        PERSON_ASKED, Kept)


def _store(**kw) -> "Kept":
    tmp = tempfile.mkdtemp()
    return Kept(str(Path(tmp) / "rows.json"), **kw)


def _rows(*uuids) -> list:
    return [{"uuid": u, "note": f"row {u}"} for u in uuids]


def test_there_is_no_way_to_empty_it() -> None:
    """Not «a discouraged method» — no method. A wipe does not compile.

    The three losses were each one line that replaced the contents. Every name that line
    could plausibly have used is checked here, because the next one will be written by
    somebody who has not read `panel/kept.py`.
    """
    store = _store()
    for forbidden in ("clear", "wipe", "reset", "empty", "truncate", "set_rows",
                      "replace", "__setitem__"):
        assert not hasattr(store, forbidden), \
            f"Kept grew a {forbidden}() — that is the hole this type exists to close"


def test_a_removal_has_to_name_a_reason_the_store_accepts() -> None:
    store = _store(accepts=(EXPIRED,))
    store.merge(_rows("a", "b"))
    for wrong in (GAME_SAID_GONE, PERSON_ASKED):
        try:
            store.drop("a", wrong)
        except ValueError as exc:
            assert "does not remove rows" in str(exc), exc
        else:
            raise AssertionError(f"{wrong} was accepted by a store that never declared it")
    assert len(store) == 2, "a refused removal must not remove anything"
    assert store.drop("a", EXPIRED) is True
    assert len(store) == 1


def test_a_reason_that_is_not_one_of_the_three_is_not_a_reason() -> None:
    """Including the one that caused all three losses, spelled out."""
    store = _store()
    store.merge(_rows("a"))
    for made_up in ("READ_WAS_EMPTY", "", "expired", None):
        try:
            store.drop("a", made_up)
        except ValueError:
            continue
        raise AssertionError(f"{made_up!r} was taken for a removal reason")
    assert len(store) == 1


def test_an_empty_read_takes_nothing_away() -> None:
    """The exact shape of `7885032`, `a1bf34b` and `1511c48`: a read that said nothing.

    A busy client, a session that is not logged in, an answer that went elsewhere — all
    of them arrive here as an empty list, and every one of them used to mean «delete
    what you have».
    """
    store = _store()
    store.merge(_rows("a", "b", "c"))
    for nothing in ([], (), None, [{"no_key": 1}], ["not a dict"]):
        store.merge(nothing)
        assert len(store) == 3, f"{nothing!r} removed rows"


def test_a_merge_updates_a_row_without_losing_the_fields_it_did_not_carry() -> None:
    """A partial read is an UPDATE, not a replacement: the fields it did not mention
    were true a moment ago and are still the best answer there is."""
    store = _store()
    store.merge([{"uuid": "a", "level": 30, "owner": "Player1"}])
    store.merge([{"uuid": "a", "level": 31}])
    row = store.get("a")
    assert row["level"] == 31, row
    assert row["owner"] == "Player1", "a field the second read never mentioned was lost"


def test_a_person_asking_is_the_only_clause_that_may_empty_it() -> None:
    """«Очистить список» is a real press and must keep working — through the door that
    says what it is, with a predicate written at that press."""
    store = _store()
    store.merge(_rows("a", "b", "c"))
    assert store.drop_where(lambda _r: True, PERSON_ASKED) == 3
    assert len(store) == 0
    assert store.rows() == []


def test_expiry_removes_the_rows_it_names_and_no_others() -> None:
    store = _store()
    store.merge([{"uuid": "a", "expires_at": 10}, {"uuid": "b", "expires_at": 400},
                 {"uuid": "c", "expires_at": 0}])
    gone = store.drop_where(lambda r: 0 < (r.get("expires_at") or 0) <= 100, EXPIRED)
    assert gone == 1
    assert {r["uuid"] for r in store.rows()} == {"b", "c"}


def test_it_comes_back_after_a_restart() -> None:
    store = _store()
    store.merge(_rows("a", "b"))
    again = Kept(store.path, key="uuid").load()
    assert {r["uuid"] for r in again.rows()} == {"a", "b"}
    assert again.get("a")["note"] == "row a"


def test_a_broken_file_is_an_empty_list_and_not_a_crash() -> None:
    """A checkpoint that cannot be read must not take the panel down — and must not be
    mistaken for «the game says these are gone» either: it removes nothing, it simply
    has nothing to give back."""
    store = _store()
    Path(store.path).write_text("{ this is not a list", encoding="utf-8")
    assert store.rows() == []
    store.merge(_rows("a"))
    assert len(store) == 1


def test_a_store_may_keep_only_the_fields_it_names() -> None:
    store = _store(fields=("uuid", "level"))
    store.merge([{"uuid": "a", "level": 30, "widget": object()}])
    assert store.get("a") == {"uuid": "a", "level": 30}
    on_disk = json.loads(Path(store.path).read_text(encoding="utf-8"))
    assert on_disk == [{"uuid": "a", "level": 30}]


def test_a_store_cannot_declare_a_reason_that_does_not_exist() -> None:
    try:
        _store(accepts=("BECAUSE_I_SAID_SO",))
    except ValueError as exc:
        assert "not a removal reason" in str(exc), exc
    else:
        raise AssertionError("a made-up clause was accepted at construction")
    assert set(ALL_REASONS) == {EXPIRED, GAME_SAID_GONE, PERSON_ASKED}


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
