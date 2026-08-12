r"""The wire's own book of banners — the thing that says WHAT a rally is going for.

A rally's kind is `targetContentId`, and that field is on `push.alliance.march.*` and
in nothing the client keeps. Until #1323 the panel remembered it in one place only —
the «Ралли» tab's dict, filled by that tab's own capture — so a profile whose window
does not show the tab joined banner after banner with no target at all: every one of
them classified as the fallback `monster`, every join counted under that one key, and
every per-kind daily cap the person had set left at zero for good.

What is pinned here:

* the book keeps what it hears, per banner, and a later push that repeats less does
  not TAKE AWAY what an earlier one said;
* an address ages out on its own minute while the banner itself is remembered longer;
* the two sources merge with the tab winning, so a banner known to both appears once;
* the child's fields line parses, and the press's own gate reads the same key it counts
  under — an unnamed monster row lands on the fallback kind rather than on a
  `monster_type_<n>` key nothing can cap.

No Tk, no game, no capture — the clock is an argument::

    python3 tests/test_panel_rally_wire.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools" / "lib", _REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _module(path: Path, name: str):
    """Load one file as a module, without importing its package.

    `panel.runtime.__init__` pulls in the whole runtime and Tk with it, and the book
    under test has neither — which is the point of it living apart from the tab. This
    keeps the test runnable on an interpreter with no tkinter, as every other test in
    this directory is.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rw = _module(_REPO_ROOT / "panel" / "runtime" / "rally_wire.py", "rally_wire")

TEAM = "1000000000000000001"
OTHER = "1000000000000000002"


# -- the book ---------------------------------------------------------------
def test_a_banner_is_remembered_with_everything_it_said():
    book = rw.BannerBook()
    assert book.note({"team": TEAM, "content": "2010710",
                      "slots": "1/5", "join": "468553/935"}, now=100.0)
    assert book.targets() == f"{TEAM}:2010710"
    assert book.slots() == f"{TEAM}:1/5"
    assert book.points(now=100.0) == f"{TEAM}:468553/935"
    assert book.known() == 1


def test_a_later_push_does_not_take_the_target_away():
    # `create` carries the target; a `refresh` of the same banner may carry only the
    # seats. Forgetting the target there is how a named banner becomes unnamed again.
    book = rw.BannerBook()
    book.note({"team": TEAM, "content": "2010710", "join": "468553/935"}, now=10.0)
    book.note({"team": TEAM, "slots": "3/5"}, now=12.0)
    assert book.targets() == f"{TEAM}:2010710"
    assert book.slots() == f"{TEAM}:3/5"


def test_an_address_ages_out_but_the_banner_stays():
    book = rw.BannerBook()
    book.note({"team": TEAM, "content": "2010710", "join": "468553/935"}, now=0.0)
    assert book.points(now=rw.POINT_TTL_SEC - 1) == f"{TEAM}:468553/935"
    assert book.points(now=rw.POINT_TTL_SEC + 1) == ""
    # …and the target is still there: the client's march table has it by then, and the
    # kind is what the budget needs.
    assert book.targets() == f"{TEAM}:2010710"


def test_a_banner_nothing_has_said_anything_about_is_forgotten():
    book = rw.BannerBook()
    book.note({"team": TEAM, "content": "2010710"}, now=0.0)
    book.note({"team": OTHER, "content": "2010711"}, now=rw.BANNER_TTL_SEC + 5)
    assert book.known() == 1, "the old banner should have been dropped"
    assert book.targets() == f"{OTHER}:2010711"


def test_rubbish_is_dropped_rather_than_kept():
    book = rw.BannerBook()
    assert book.note({"team": "solo", "content": "2010710"}) is False
    assert book.note({}) is False
    book.note({"team": TEAM, "join": "nowhere"}, now=1.0)
    assert book.points(now=1.0) == "", "half an address is not an address"
    assert book.known() == 1


# -- the two sources --------------------------------------------------------
def test_the_tab_wins_where_both_know_a_banner():
    merged = rw.merge(f"{TEAM}:111", f"{TEAM}:222,{OTHER}:333")
    pairs = dict(part.split(":") for part in merged.split(","))
    assert pairs[TEAM] == "111", "the tab's own capture is the fresher source"
    assert pairs[OTHER] == "333", "and the ear's banner is not lost"


def test_either_source_may_be_empty():
    assert rw.merge("", f"{TEAM}:222") == f"{TEAM}:222"
    assert rw.merge(f"{TEAM}:111", "") == f"{TEAM}:111"
    assert rw.merge("", "") == ""


# -- the child's line -------------------------------------------------------
def test_the_fields_line_parses():
    fields = rw.parse_fields("team=1 content=2 slots=1/5 join=3/4")
    assert fields == {"team": "1", "content": "2", "slots": "1/5", "join": "3/4"}
    assert rw.parse_fields("") == {}
    assert rw.parse_fields("rubbish") == {}


def test_the_child_builds_that_line_and_names_nobody():
    # The push's own shape, with invented values: what matters is that the four fields
    # come out and that no player, uid or alliance id can ride along.
    import wire_event_monitor as wem

    payload = {"uuid": TEAM, "targetContentId": 2010710, "assemblyMarchMax": 5,
               "attackPointId": 468553, "server": 935,
               "leaderMarch": {"armyInfo": {}, "ownerUid": 1, "ownerName": "Player1",
                               "allianceAbbr": "AL1", "startId": 468553}}
    line = wem._fields_for("push.alliance.march.create", payload)
    assert f"team={TEAM}" in line
    assert "content=2010710" in line
    assert "slots=1/5" in line
    assert "join=468553/935" in line
    for secret in ("Player1", "AL1", "ownerUid", "allianceAbbr"):
        assert secret not in line, f"{secret} must never leave the ear"
    assert wem._fields_for("push.something.else", payload) == ""


# -- the press's own key ----------------------------------------------------
def test_the_gate_looks_up_the_key_the_tally_counts_under():
    # A row `lw_world_monster` cannot NAME used to become `monster_type_<n>`, which is
    # in nobody's vocabulary: no cap, no budget handed over, never shown, never over
    # budget — while the tally counted joins under it all day.
    import lua_actions

    chunk = lua_actions.rally_join_all()
    assert "monster_type_" not in chunk, \
        "an unnamed row must land on a kind the panel can actually cap"
    assert "r.unnamed" in chunk, "…and its type must still reach the report"
    assert "tgt_n" in chunk, "the press must count the targets it was parked"


def test_the_chunk_still_compiles():
    import lua_actions

    try:
        import lupa
    except ImportError:                       # noqa: BLE001 — no Lua here, no check
        return
    runtime = lupa.LuaRuntime()
    ok, err = runtime.execute(
        "return function(s) local f, e = load(s) return (f ~= nil), tostring(e) end"
    )(lua_actions.rally_join_all())
    assert ok, f"the join chunk does not compile: {err}"


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
