r"""The four-hourly round that FILLS the ★ list, and the rules that decide where it goes.

The round walks warzones so that «Автолут ★» has something ripe to rob hours later
(#1479). Everything that can be got wrong about it is arithmetic — which warzones are
having their star day, which of them this account may rob on, which ones today has
already walked — so all of it is pinned here, with no game, no Tk and no panel.

The two DSL statements are exercised against stubs: a store that is a dict, a book that
answers a fixed state per warzone, and an interpreter whose one game read is replaced.
That is enough to catch the failures that actually happened in review — a queue popped
from the wrong end, a warzone marked walked before it was chosen, a lap that walks home.

    C:\Python312\python.exe tests\test_star_round.py
    python3 tests/test_star_round.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "lib"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import secret_day                                                # noqa: E402
import star_round as R                                           # noqa: E402

from lastwar_bot import script_engine as SE                      # noqa: E402


# --- stubs ------------------------------------------------------------------
class _Store:
    """The profile's database, as far as this round is concerned: one named row."""

    def __init__(self) -> None:
        self.blobs: dict = {}

    def blob_get(self, name):
        return self.blobs.get(name)

    def blob_set(self, name, value) -> None:
        self.blobs[name] = value


class _Book:
    """The book of star days, answering a fixed state per warzone."""

    def __init__(self, states, day=100) -> None:
        self.states, self.day = states, day

    def today(self, _now_ms=None) -> int:
        return self.day

    def decorate(self, rows, day=None):
        return [{"id": row["id"],
                 "secret_state": self.states.get(int(row["id"]), "plain")}
                for row in rows]


def _interp(store, book, *, home=1000, reach=(), states=None):
    """An interpreter whose only game read answers the home warzone."""
    ctx = SE.new_context(0, lambda _msg: None, store=store, days=book)
    interp = SE.Interpreter(ctx)
    interp._eval_lua_value = lambda _expr: str(home)
    interp._tools_lib_on_path()
    import server_list

    interp._slice = list(reach)
    server_list.same_phase = lambda *_a, **_k: list(reach)        # the phase cut, stubbed
    server_list.load = lambda *_a, **_k: {"servers": {}}
    return interp, ctx


# --- the rule ---------------------------------------------------------------
def test_only_warzones_having_their_star_day_are_walked():
    """The whole point of the round: a plain day has no star tiles to ripen."""
    states = {1001: "day", 1002: "plain", 1003: "post", 1004: "day"}
    got = R.choose([1001, 1002, 1003, 1004], states, 1000, [], 5)
    assert got["servers"] == [1001, 1004] and got["pool"] == 2


def test_home_is_never_walked():
    """Robbing at home is forbidden (#1188), so a lap of it fills the list with nothing."""
    states = {1000: "day", 1001: "day"}
    assert R.choose([1000, 1001], states, 1000, [], 5)["servers"] == [1001]


def test_the_nearest_warzones_come_first():
    states = {s: "day" for s in (1010, 1001, 1005)}
    assert R.choose([1010, 1001, 1005], states, 1000, [], 5)["servers"] == [1001, 1005, 1010]


def test_what_today_already_walked_is_skipped():
    """«не ходить по одним и тем же подряд» — the day must cover different warzones."""
    states = {s: "day" for s in (1001, 1002, 1003)}
    got = R.choose([1001, 1002, 1003], states, 1000, [1001, 1002], 5)
    assert got["servers"] == [1003] and got["fresh"] == 1 and not got["cycled"]


def test_the_circle_starts_again_when_everything_has_been_walked():
    """…and it must not go quiet: the tiles seen this morning have ripened since."""
    states = {s: "day" for s in (1001, 1002)}
    got = R.choose([1001, 1002], states, 1000, [1001, 1002], 5)
    assert got["servers"] == [1001, 1002] and got["cycled"]


def test_nothing_having_its_day_is_an_empty_lap_rather_than_a_wrong_one():
    assert R.choose([1001, 1002], {}, 1000, [], 5) == {
        "servers": [], "pool": 0, "fresh": 0, "cycled": False}


def test_the_count_is_held_inside_the_operators_bounds():
    """5-10 per lap, whatever a hand-edited timer asks for."""
    states = {1000 + n: "day" for n in range(1, 30)}
    ids = sorted(states)
    assert len(R.choose(ids, states, 1000, [], 1)["servers"]) == R.COUNT_MIN
    assert len(R.choose(ids, states, 1000, [], 99)["servers"]) == R.COUNT_MAX
    assert len(R.choose(ids, states, 1000, [], "nonsense")["servers"]) == R.COUNT_MIN


def test_the_state_it_walks_is_the_books_own_word_for_the_star_day():
    """One string in two files; a rename in either must not silently empty the round."""
    assert R.STATE_DAY == secret_day.STATE_DAY


# --- the round's memory -----------------------------------------------------
def test_a_walked_warzone_is_written_down_and_read_back():
    store = _Store()
    R.mark(store, 100, 1001)
    R.mark(store, 100, 1002)
    assert R.walked_on(R.load(store), 100) == [1001, 1002]


def test_the_memory_belongs_to_a_GAME_day_and_not_to_a_calendar_one():
    """A day that has turned over empties it by itself — nothing has to clean up."""
    store = _Store()
    R.mark(store, 100, 1001)
    assert R.walked_on(R.load(store), 101) == []
    R.mark(store, 101, 1005)
    assert R.walked_on(R.load(store), 101) == [1005]


def test_a_restarted_circle_forgets_what_it_walked():
    """Otherwise the second time round would be filtered by the first and pick nothing."""
    store = _Store()
    R.mark(store, 100, 1001)
    R.note_lap(store, 100, cycled=True)
    assert R.walked_on(R.load(store), 100) == []
    assert R.load(store)["laps"] == 1


def test_junk_in_the_row_reads_as_a_round_that_has_walked_nothing():
    store = _Store()
    store.blobs[R.BLOB] = ["not", "a", "dict"]
    assert R.load(store) == {"day": 0, "walked": [], "laps": 0}
    assert R.load(None) == {"day": 0, "walked": [], "laps": 0}


# --- the two statements -----------------------------------------------------
def test_the_pick_fills_the_registers_the_recipe_reports_by():
    store, book = _Store(), _Book({1001: "day", 1002: "day", 1003: "plain"})
    interp, ctx = _interp(store, book, reach=[1000, 1001, 1002, 1003])
    interp._run_stmt(SE.parse_text("PICK_STAR_SERVERS COUNT 5")[0])
    assert ctx.vars["STAR_HOME"] == 1000
    assert ctx.vars["STAR_POOL"] == 2
    assert ctx.vars["STAR_PICKED"] == 2 == ctx.vars["STAR_LEFT"]
    assert ctx.vars["STAR_SERVERS"] == "1001,1002" == ctx.vars["STAR_CHOSEN"]
    assert ctx.vars["STAR_WALKED"] == 0 and ctx.vars["STAR_CYCLED"] == 0


def test_the_pop_takes_the_head_marks_it_and_leaves_the_rest():
    store, book = _Store(), _Book({1001: "day", 1002: "day"})
    interp, ctx = _interp(store, book, reach=[1001, 1002])
    interp._run_stmt(SE.parse_text("PICK_STAR_SERVERS")[0])
    interp._run_stmt(SE.parse_text("NEXT_STAR_SERVER")[0])
    assert ctx.vars["STAR_SERVER"] == 1001
    assert ctx.vars["STAR_SERVERS"] == "1002" and ctx.vars["STAR_LEFT"] == 1
    assert R.walked_on(R.load(store), ctx.vars["STAR_DAY"]) == [1001]
    # …and what it POPPED stays readable for the report, which runs after the queue
    # has been emptied.
    assert ctx.vars["STAR_CHOSEN"] == "1001,1002"


def test_a_second_lap_the_same_day_walks_the_other_warzones():
    """The acceptance criterion, end to end: a day covers different warzones."""
    store, book = _Store(), _Book({s: "day" for s in (1001, 1002, 1003, 1004)})
    seen = []
    for _lap in range(2):
        interp, ctx = _interp(store, book, reach=[1001, 1002, 1003, 1004])
        interp._run_stmt(SE.parse_text("PICK_STAR_SERVERS COUNT 5")[0])
        while ctx.vars["STAR_LEFT"] > 0:
            interp._run_stmt(SE.parse_text("NEXT_STAR_SERVER")[0])
            seen.append(ctx.vars["STAR_SERVER"])
    # Every warzone in reach is walked once before any of them is walked twice — which
    # is «за день таймер должен покрыть РАЗНЫЕ зоны» stated as a test.
    assert sorted(seen[:4]) == [1001, 1002, 1003, 1004]
    assert len(seen) == 8 and sorted(seen[4:]) == [1001, 1002, 1003, 1004]


def test_a_client_that_will_not_say_where_home_is_stops_the_round():
    """A login screen answers -1, and a grid anchored on that is warzones nobody can rob."""
    store, book = _Store(), _Book({1001: "day"})
    interp, _ctx = _interp(store, book, home=-1, reach=[1001])
    try:
        interp._run_stmt(SE.parse_text("PICK_STAR_SERVERS")[0])
    except SE.ScriptRuntimeError as exc:
        assert "home" in str(exc)
    else:                                                        # pragma: no cover
        raise AssertionError("a home-less client was allowed to pick warzones")


def test_the_primitives_refuse_a_run_that_has_no_panel_behind_it():
    """`PICK_STAR_SERVERS` reads THIS PROFILE's book; a shell run has none to read."""
    interp, _ctx = _interp(None, None, reach=[1001])
    try:
        interp._run_stmt(SE.parse_text("PICK_STAR_SERVERS")[0])
    except SE.ScriptRuntimeError as exc:
        assert "panel" in str(exc)
    else:                                                        # pragma: no cover
        raise AssertionError("a shell run chose warzones out of nothing")


def test_a_pop_with_an_empty_queue_says_so_instead_of_sweeping_the_wrong_map():
    store, book = _Store(), _Book({})
    interp, _ctx = _interp(store, book, reach=[])
    try:
        interp._run_stmt(SE.parse_text("NEXT_STAR_SERVER")[0])
    except SE.ScriptRuntimeError as exc:
        assert "PICK_STAR_SERVERS" in str(exc)
    else:                                                        # pragma: no cover
        raise AssertionError("an empty queue popped a warzone")


def test_an_unknown_modifier_is_a_parse_error():
    """The sweep's own rule: a silently dropped option walks the wrong number of laps."""
    try:
        SE.parse_text("PICK_STAR_SERVERS COUNT 5 EVERY 3")
    except SE.ScriptParseError:
        return
    raise AssertionError("PICK_STAR_SERVERS swallowed an option it does not know")


# --- the recipes ------------------------------------------------------------
def test_the_recipes_parse_and_the_loop_can_reach_the_whole_queue():
    """A `LIMIT` under the model's ceiling would silently leave warzones unwalked."""
    for name in ("sweep_star_servers", "sweep_one_star_server"):
        path = SE.resolve_action(name)
        assert path is not None, name
        source, _args = SE.prepare_source(path.read_text(encoding="utf-8"), {})
        statements = SE.parse_text(source)
        assert statements, name
    text = SE.resolve_action("sweep_star_servers").read_text(encoding="utf-8")
    limit = [ln for ln in text.splitlines() if ln.strip().startswith("WHILE STAR_LEFT")]
    assert limit and int(limit[0].split("LIMIT")[1]) >= R.COUNT_MAX


def test_the_round_is_a_timer_that_comes_back_through_the_day():
    """Four hours, off by default, and its scenario is the one the tests above parse."""
    sys.path.insert(0, ROOT)
    from panel import timers as T

    row = {t.name: t for t in T.DEFAULT_TIMERS}["sweep_star_servers"]
    assert row.scenario == ("sweep_star_servers",)
    assert row.interval_sec == 4 * 3600 and not row.enabled
    assert R.COUNT_MIN <= int(row.args["count"]) <= R.COUNT_MAX


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
