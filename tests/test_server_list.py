r"""The list of every warzone the game has: its chunks, its parser and its cache (#1418).

No game, no Tk, no panel — `tools/lib/server_list.py` is Lua TEXT, a parser and a JSON
file, which is exactly why the view the two front-ends draw lives there too. Runs under
any python:

    C:\Python312\python.exe tests\test_server_list.py
    python3 tests/test_server_list.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "lib"))

import server_list as S                                          # noqa: E402


def test_the_read_is_paged_and_says_the_total_first():
    """A caller must be able to size the job before it has read any of it."""
    lines = ["x SRVLIST n=2558",
             "x SRVLIST page 3~State#3~0~0;5~State#5~8~1"]
    assert S.total(lines) == 2558
    rows = S.parse_page(lines)
    assert [r["id"] for r in rows] == [3, 5]
    assert rows[1] == {"id": 5, "name": "State#5", "type": 8, "hot": True}


def test_a_client_that_never_answered_reads_as_minus_one_and_not_as_zero():
    """«No list» and «a list of none» must not look the same to the caller."""
    assert S.total(["x SRVLIST n=-1"]) == -1
    assert S.total([]) == -1
    assert S.parse_page(["x SRVLIST n=-1"]) == []


def test_the_date_read_drops_what_is_not_a_clock():
    """A zero is what an unasked warzone looks like, and it is not day one of 1970."""
    dates = S.parse_dates(["y SRVLIST dpage 3~1687335831000~1153;9~0~-1"])
    assert dates == {3: {"open_ms": 1687335831000, "day": 1153}}


def test_a_narrowed_date_read_asks_only_about_the_batch_it_was_given():
    """The client's dictionary keeps every earlier batch — re-reading it all is quadratic."""
    narrow = S.read_dates_chunk([7, 8], 0, 120)
    assert "pick[" in narrow and "{7,8}" in narrow
    wide = S.read_dates_chunk(None, 0, 120)
    assert "pick[" not in wide
    # …and neither is left holding an unformatted placeholder.
    assert "%(" not in narrow and "%(" not in wide


def test_nothing_on_file_is_ever_forgotten():
    """An interrupted read brings back a PREFIX. Written over the file, it would lose
    every warzone past it — so a fold is the only way the cache is ever changed."""
    first = S.merge({"read_at": 0, "dated_at": 0, "servers": {}},
                    servers=[{"id": 1, "name": "State#1", "type": 0, "hot": False},
                             {"id": 2, "name": "State#2", "type": 0, "hot": False}],
                    now=100)
    short = S.merge(first, servers=[{"id": 1, "name": "State#1", "type": 0, "hot": False}],
                    now=200)
    assert [r["id"] for r in S.rows(short)] == [1, 2]
    assert short["read_at"] == 200


def test_the_dates_accumulate_across_runs():
    """They arrive in batches of a few hundred, over several presses."""
    data = S.merge({"read_at": 0, "dated_at": 0, "servers": {}},
                   servers=[{"id": 1, "name": "State#1", "type": 0, "hot": False},
                            {"id": 2, "name": "State#2", "type": 0, "hot": False}], now=1)
    data = S.merge(data, dates={1: {"open_ms": 1700000000000, "day": 10}}, now=2)
    assert S.undated(data) == [2]
    data = S.merge(data, dates={2: {"open_ms": 1710000000000, "day": 5}}, now=3)
    assert S.undated(data) == []
    assert S.rows(data)[0]["day"] == 10          # the first batch was not overwritten


def test_the_cache_round_trips_through_a_file():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "sub", "servers.json")
        data = S.merge({"read_at": 0, "dated_at": 0, "servers": {}},
                       servers=[{"id": 3, "name": "State#3", "type": 0, "hot": False}],
                       now=7)
        S.save(data, path)
        assert json.load(open(path, encoding="utf-8"))["servers"]["3"]["name"] == "State#3"
        assert S.load(path)["read_at"] == 7
    # …and a machine that has never read anything gets an empty list, never an error.
    assert S.load(os.path.join(folder, "gone.json"))["servers"] == {}


def test_the_view_is_what_both_front_ends_draw():
    """One filter, one sort, one rendering — the window's grid and the phone's screen."""
    data = S.merge({"read_at": 0, "dated_at": 0, "servers": {}},
                   servers=[{"id": 3, "name": "State#3", "type": 0, "hot": False},
                            {"id": 40, "name": "State#40", "type": 8, "hot": True}],
                   now=1)
    data = S.merge(data, dates={3: {"open_ms": 1687335831000, "day": 1153}}, now=2)
    rows = S.view_rows(data)
    assert [r["id"] for r in rows] == [3, 40]
    assert rows[0]["opened"] == "2023-06-21" and rows[0]["kind_key"] == "servers.kind.ordinary"
    assert rows[1]["opened"] == "—" and rows[1]["kind_key"] == "servers.kind.other"
    assert [r["id"] for r in S.view_rows(data, needle="#40")] == [40]
    assert [r["id"] for r in S.view_rows(data, undated_only=True)] == [40]
    # A missing day sorts last whichever way the column is turned — «unknown» is not
    # «zero», and a grid that mixes the two reads as a warzone opened today.
    assert [r["id"] for r in S.sorted_rows(rows, "day", down=True)] == [3, 40]
    assert S.summary(data) == {"total": 2, "dated": 1, "undated": 1,
                               "read_at": 1, "dated_at": 2}


def _main() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print("  ok   %s" % test.__name__)
        except AssertionError as exc:
            failed += 1
            print("  FAIL %s: %s" % (test.__name__, exc))
        except Exception as exc:                 # noqa: BLE001
            failed += 1
            print("  ERROR %s: %s: %s" % (test.__name__, type(exc).__name__, exc))
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
