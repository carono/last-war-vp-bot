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
    assert S.summary(data) == {"total": 2, "dated": 1, "undated": 1, "seasoned": 0,
                               "read_at": 1, "dated_at": 2, "seasoned_at": 0}


def test_the_season_chunk_asks_by_name_and_carries_the_own_warzone():
    """The row answers `getValue`, and the client's exact numbers ride along with it."""
    chunk = S.season_chunk([1234, 100])
    assert "GetConfigDataByServerId" in chunk and "getValue" in chunk
    assert "sown" in chunk and "nextSeasonStartTime" in chunk
    assert "%(" not in chunk


def test_the_season_plan_parses_into_four_moments():
    plan = S.parse_seasons(["x SRVLIST spage "
                            "1234~1044~V~2026/03/23 00:00:00~2026/04/06 00:10:00"
                            "~2026/05/25 00:00:00~2026/05/31 23:00:00"])
    row = plan[1234]
    assert row["season_id"] == 1044 and row["step"] == "V"
    assert row["pre_ms"] < row["start_ms"] < row["settle_ms"] < row["end_ms"]
    # …and a row the config left blank is None rather than 1970.
    blank = S.parse_seasons(["x SRVLIST spage 7~0~~~~~"])
    assert blank == {} or blank[7]["pre_ms"] is None


def test_the_stage_is_judged_by_the_four_moments():
    row = {"pre_ms": 100, "start_ms": 200, "settle_ms": 300, "end_ms": 400}
    assert S.stage_of(row, 50) == S.STAGE_OFF
    assert S.stage_of(row, 150) == S.STAGE_PRE
    assert S.stage_of(row, 250) == S.STAGE_SEASON
    assert S.stage_of(row, 350) == S.STAGE_SETTLE
    assert S.stage_of(row, 450) == S.STAGE_OFF
    assert S.stage_of({}, 250) == S.STAGE_UNKNOWN
    # No clock, no verdict — this machine's is not the game's (docs/research/game-clock.md).
    assert S.stage_of(row, None) == S.STAGE_UNKNOWN


def test_between_seasons_the_next_start_is_the_only_moment_left():
    """A warzone that has finished its season has nothing ahead in its own row."""
    row = {"pre_ms": 100, "start_ms": 200, "settle_ms": 300, "end_ms": 400}
    assert S.next_change(row, 450) is None
    row["next_start_ms"] = 900
    assert S.next_change(row, 450) == 900
    assert S.next_change(row, 250) == 300      # …and it never jumps the nearer one


def test_the_own_warzone_numbers_beat_the_calendar_but_keep_it():
    own = S.parse_own_season(["x SRVLIST sown 1234~1775440800000~1780275600000"
                              "~1787536800000~5~133"])
    assert own[1234]["season_no"] == 5 and own[1234]["season_day"] == 133
    data = S.merge({"read_at": 0, "dated_at": 0, "servers": {}},
                   servers=[{"id": 1234, "name": "State#1234", "type": 0, "hot": False}],
                   now=1)
    data = S.merge(data, seasons={1234: {"season_id": 1044, "step": "V", "pre_ms": 1,
                                        "start_ms": 2, "settle_ms": 3, "end_ms": 4}}, now=2)
    data = S.merge(data, seasons=own, now=3)
    season = data["servers"]["1234"]["season"]
    assert season["step"] == "V" and season["pre_ms"] == 1          # kept
    assert season["start_ms"] == 1775440800000                      # overwritten
    assert season["next_start_ms"] == 1787536800000                 # added


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


# -- the picker's slice (#1467, recut in #1471) ------------------------------
DAY = 86_400_000
NOW = 1_000 * DAY


def _list(ids, **season) -> dict:
    """A cache holding just these warzone numbers — invented, like every id here."""
    return {"servers": {str(i): {"id": i, "name": "State#%d" % i,
                                 "season": dict(season)} for i in ids}}


def _merge(*parts) -> dict:
    """Several `_list`s as one cache."""
    out = {"servers": {}}
    for part in parts:
        out["servers"].update(part["servers"])
    return out


#: A season that ENDED before `NOW` — the lull the picker's own account is standing in.
LULL = {"step": "IV", "pre_ms": NOW - 90 * DAY, "start_ms": NOW - 80 * DAY,
        "settle_ms": NOW - 20 * DAY, "end_ms": NOW - 10 * DAY}
#: The same numeral, still being PLAYED — same season, different stage.
PLAYING = {"step": "IV", "pre_ms": NOW - 30 * DAY, "start_ms": NOW - 20 * DAY,
           "settle_ms": NOW + 20 * DAY, "end_ms": NOW + 30 * DAY}
#: A different season altogether, and mid-flight.
NEXT_ONE = {"step": "V", "pre_ms": NOW - 30 * DAY, "start_ms": NOW - 20 * DAY,
            "settle_ms": NOW + 20 * DAY, "end_ms": NOW + 30 * DAY}


def test_the_slice_is_the_warzones_in_our_own_season_phase() -> None:
    """«Ограничивать сезоном или соответствующим межсезоньем» — the operator's rule."""
    data = _merge(_list(range(1000, 1010), **LULL),
                  _list(range(1010, 1020), **PLAYING))
    assert S.same_phase(data, 1003, NOW) == list(range(1000, 1010))


def test_the_same_season_in_a_different_stage_is_a_different_phase() -> None:
    """Half a numeral can be mid-season while the other half is months past it."""
    data = _merge(_list(range(1000, 1004), **LULL),
                  _list(range(1004, 1008), **PLAYING))
    assert S.phase_of(data["servers"]["1000"], NOW)[0] == \
        S.phase_of(data["servers"]["1004"], NOW)[0]          # the same numeral…
    assert S.phase_of(data["servers"]["1000"], NOW) != \
        S.phase_of(data["servers"]["1004"], NOW)             # …and not the same phase
    assert 1004 not in S.same_phase(data, 1000, NOW)


def test_a_different_season_is_never_in_the_slice() -> None:
    data = _merge(_list([1000, 1001], **PLAYING), _list([1002, 1003], **NEXT_ONE))
    assert S.same_phase(data, 1000, NOW) == [1000, 1001]


def test_the_high_block_is_in_when_it_shares_the_phase() -> None:
    """Unlike the numeric window this replaces: the cut is availability, not distance.

    A season row groups warzones from the high «State#8xxx» block with ordinary ones, so
    a cell offering that jump is telling the truth (#1471).
    """
    data = _merge(_list(range(1000, 1004), **LULL), _list([9001, 9002], **LULL))
    assert S.same_phase(data, 1000, NOW) == [1000, 1001, 1002, 1003, 9001, 9002]


def test_the_edge_of_the_slice_is_computed_and_never_written_down() -> None:
    """Move the clock past the neighbours' season end and they join us — nothing else."""
    data = _merge(_list([1000], **LULL), _list([1001], **PLAYING))
    assert S.same_phase(data, 1000, NOW) == [1000]
    later = NOW + 40 * DAY
    assert S.same_phase(data, 1000, later) == [1000, 1001]


def test_nothing_read_is_an_empty_slice_rather_than_every_warzone() -> None:
    """An empty grid says «nothing read yet»; a full one would claim warzones nobody checked."""
    assert S.same_phase(_list([7, 8, 9]), 8, NOW) == []          # no season rows at all
    assert S.same_phase(_list([7, 8, 9], **LULL), 8, None) == []  # no game clock
    assert S.same_phase(_list([7, 8, 9], **LULL), 42, NOW) == []  # not a warzone we hold
    assert S.same_phase({"servers": {}}, 8, NOW) == []


if __name__ == "__main__":
    raise SystemExit(_main())
