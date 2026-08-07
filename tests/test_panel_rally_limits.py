r"""Per-monster-type daily caps on rally auto-join — the limits and the day's count.

`panel.rally_limits` is where a rally auto-join decides whether a type is still under
its daily cap, and where the count of joins is kept and rolled over at midnight. Two
things must not go wrong: a `0` cap means unlimited (not "join zero"), and the count
is a per-DAY budget that resets on a new day rather than a total that grows forever.
Both are pinned here, plus the file round-trips (a hand-edited cap is honoured, junk
is dropped, a new built-in type is folded into an old profile's file) — and the GATE
that spends them, `panel/tabs/rally/limits.py`, which the schedule asks before it lets
the «rally_auto_join» trigger run.

No Tk, no game, and the day is an argument — so this runs anywhere::

    python3 tests/test_panel_rally_limits.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import rally_limits as rl  # noqa: E402
from panel.tabs.rally import limits as gate  # noqa: E402

DAY1 = "2026-07-30"
DAY2 = "2026-07-31"


# -- limits -----------------------------------------------------------------
def test_zero_is_unlimited_not_zero():
    limits = rl.RallyLimits({"zombie_invasion": 0, "monster": 2})
    counts = rl.RallyCounts(DAY1, {"zombie_invasion": 999, "monster": 0})
    # 0 cap: always allowed, however many were joined.
    assert counts.allowed("zombie_invasion", limits, today=DAY1) is True
    # a real cap: allowed until the count reaches it.
    assert counts.allowed("monster", limits, today=DAY1) is True


def test_a_cap_holds_at_its_limit():
    limits = rl.RallyLimits({"monster": 2})
    counts = rl.RallyCounts(DAY1, {"monster": 1})
    assert counts.allowed("monster", limits, today=DAY1) is True
    counts = counts.record("monster", today=DAY1)          # now 2
    assert counts.count_for("monster") == 2
    assert counts.allowed("monster", limits, today=DAY1) is False


def test_a_type_with_no_cap_entry_is_unlimited():
    limits = rl.RallyLimits({"monster": 1})
    counts = rl.RallyCounts(DAY1, {"boss": 500})
    # 'boss' is not in the limits file → limit_for is 0 → unlimited.
    assert limits.limit_for("boss") == 0
    assert counts.allowed("boss", limits, today=DAY1) is True


def test_negative_and_junk_caps_coerce():
    limits = rl.RallyLimits({"monster": -5, "x": "nope", "y": 3.9})
    assert limits.limit_for("monster") == 0                # negative → 0 (unlimited)
    assert limits.limit_for("x") == 0                      # unreadable dropped → 0
    assert limits.limit_for("y") == 3                      # 3.9 → 3


def test_with_limit_writes_one_type_only():
    limits = rl.default_limits().with_limit("monster", 5)
    assert limits.limit_for("monster") == 5
    assert limits.limit_for("zombie_invasion") == 0        # untouched


# -- counts: the day roll ---------------------------------------------------
def test_the_count_resets_on_a_new_day():
    counts = rl.RallyCounts(DAY1, {"monster": 7})
    assert counts.count_for("monster") == 7
    rolled = counts.rolled(today=DAY2)
    assert rolled.date == DAY2 and rolled.count_for("monster") == 0
    # allowed/record roll on their own too:
    limits = rl.RallyLimits({"monster": 3})
    assert counts.allowed("monster", limits, today=DAY2) is True   # yesterday's 7 is gone
    recorded = counts.record("monster", today=DAY2)
    assert recorded.date == DAY2 and recorded.count_for("monster") == 1


# -- files ------------------------------------------------------------------
def test_limits_file_is_seeded_then_round_trips():
    tmp = Path(tempfile.mkdtemp())
    path = str(tmp / "rally_limits.json")
    seeded = rl.load_limits(path)                           # writes the built-ins
    assert seeded.as_dict() == rl.DEFAULT_RALLY_LIMITS
    assert Path(path).exists()
    # a hand edit is honoured on the next read.
    Path(path).write_text(json.dumps({"monster": 9}), encoding="utf-8")
    back = rl.load_limits(path)
    assert back.limit_for("monster") == 9
    # …and a NEW built-in type is folded into the old file rather than lost.
    assert back.limit_for("zombie_invasion") == 0


def test_counts_file_round_trips_and_rolls_on_load():
    tmp = Path(tempfile.mkdtemp())
    path = str(tmp / "rally_counts.json")
    rl.save_counts(rl.RallyCounts(DAY1, {"monster": 4}), path)
    same_day = rl.load_counts(path, today=DAY1)
    assert same_day.count_for("monster") == 4
    next_day = rl.load_counts(path, today=DAY2)             # stale file → rolled empty
    assert next_day.date == DAY2 and next_day.count_for("monster") == 0


# -- the gate the schedule asks (panel/tabs/rally/limits.py) ----------------
class _Profiles:
    def __init__(self, tmp: Path):
        self._tmp = tmp

    def rally_limits_json(self, name=None):
        return str(self._tmp / "rally_limits.json")

    def rally_counts_json(self, name=None):
        return str(self._tmp / "rally_counts.json")


class _Game:
    """A game link that COUNTS what the gate asked it, and answers the classify read.

    The count is the point of it now (#1281): the gate must reach the budget's own two
    files and nothing else. It used to read the whole march table through the VM before
    the join was allowed to start, at 1.3–19 s a call on the live client — a budget check
    that delays the thing it is budgeting past the life of a banner.
    """

    def __init__(self, types_out):
        self._types = types_out
        self.reads = 0

    def up(self):
        return self._types is not None

    def evaluator(self):
        types, game = self._types, self

        class _Ev:
            @staticmethod
            def run(chunk, marker=None, settle=None, early=False):
                assert marker == "RTYPE", marker
                game.reads += 1
                return ["RTYPE=%s" % t for t in types] + ["RTYPE end"]
        return _Ev()


class _Rt:
    """Just enough runtime for the gate: a profile's two files, and a game to read."""

    def __init__(self, tmp: Path, types_out, limits=None):
        self.profiles = _Profiles(tmp)
        self.game = _Game(types_out)
        self.said: list = []
        if limits is not None:
            rl.save_limits(limits, self.profiles.rally_limits_json())

    def say(self, tag, key, **fmt):
        self.said.append(key)


def test_the_gate_never_touches_the_game():
    """The budget is two files. Reading the VM in front of a banner is what cost #1281.

    A whole call into the game VM stood between the push and the recipe, to be told the
    constant this module already knows — the push carries no rally type and every rally
    classifies as the fallback one, so the read answered `monster` and nothing else. The
    call is gone; this is what stops it coming back.
    """
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"], limits=rl.RallyLimits({"monster": 5}))
        assert rl.UNKNOWN_TYPE in gate.join_gate(rt), gate.join_gate(rt)
        assert rt.game.reads == 0, "the gate read the game"


def test_the_gate_lets_a_join_through_with_no_daemon_at_all():
    """A budget is not a lock: nothing about the client decides whether it answers."""
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), None)                                  # no daemon
        assert rl.UNKNOWN_TYPE in gate.join_gate(rt), gate.join_gate(rt)
        assert rt.said == []


def test_the_gate_returns_the_type_still_under_its_cap():
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster", "monster"],
                 limits=rl.RallyLimits({"monster": 5}))
        assert rl.UNKNOWN_TYPE in gate.join_gate(rt), gate.join_gate(rt)
        assert rt.said == []


def test_a_run_that_joined_nothing_spends_none_of_the_day():
    """The budget counts JOINS, not runs (#1281).

    A rally re-announces itself on the wire every few seconds and the trigger fires on
    each; most of those runs find nothing to do. The gate used to read the game and so
    could only say «yes» when a rally was actually out — now that it answers from the
    counts file, counting the run would empty a day's budget over a quiet map.
    """
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"], limits=rl.RallyLimits({"monster": 5}))
        gate.record_joins(rt, [rl.UNKNOWN_TYPE], 0)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for(rl.UNKNOWN_TYPE) == 0, counts
        # …and a run that joined TWO rallies in one press costs two — one entry per
        # squad it sent, which is the shape the chunk hands back.
        gate.record_joins(rt, [rl.UNKNOWN_TYPE, rl.UNKNOWN_TYPE], 2)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for(rl.UNKNOWN_TYPE) == 2, counts


def test_the_gate_refuses_the_whole_join_once_every_type_is_capped():
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"],
                 limits=rl.RallyLimits({"monster": 1, "zombie_invasion": 1,
                                        "alliance_drill": 1}))
        gate.record_joins(rt, ["monster", "zombie_invasion", "alliance_drill"], 3)
        assert gate.join_gate(rt) == []
        assert rt.said == ["triggers.log.rally_capped"], rt.said
        # …and the count landed in the profile's own file, not merely in memory.
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("monster") == 1



# ---------------------------------------------------------------------------
# the kinds: an uncapped one must not spend a capped one's day (#1281)
# ---------------------------------------------------------------------------

def test_an_uncapped_kind_keeps_the_door_open_for_itself_alone():
    """`zombie_invasion` is configured uncapped because the event does not ration it.

    The gate used to ask about ONE key, so the day the ordinary twenty were gone the
    auto-join refused invasion bosses too — and, worse, counted them under `monster`
    while it still let them through, which is what spent the twenty in the first place.
    """
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"],
                 limits=rl.RallyLimits({"monster": 1, "zombie_invasion": 0}))
        gate.record_joins(rt, ["monster"], 1)             # the day's one is spent
        allowed = gate.join_gate(rt)
        assert "monster" not in allowed, allowed
        assert "zombie_invasion" in allowed, allowed
        assert rt.said == [], "a run that may still join something must not say capped"
        # …and the recipe is told which keys to skip, which is the half that stops a squad.
        assert gate.blocked_types(rt) == ["monster"], gate.blocked_types(rt)


def test_every_kind_at_its_cap_is_the_only_thing_that_stops_the_run():
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"],
                 limits=rl.RallyLimits({"monster": 1, "zombie_invasion": 1,
                                        "alliance_drill": 1}))
        gate.record_joins(rt, ["monster", "zombie_invasion", "alliance_drill"], 3)
        assert gate.join_gate(rt) == []
        assert rt.said == ["triggers.log.rally_capped"], rt.said


def test_each_join_is_counted_under_the_kind_it_actually_was():
    """The run hands back one kind per squad it sent, in order — not «one join».

    Counting them all under the gate's first key is what made an invasion boss spend an
    ordinary monster's budget, with the config saying in as many words that it should
    not be capped at all.
    """
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"],
                 limits=rl.RallyLimits({"monster": 20, "zombie_invasion": 0}))
        gate.record_joins(rt, ["zombie_invasion", "monster", "zombie_invasion"], 3)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("monster") == 1, counts
        assert counts.count_for("zombie_invasion") == 2, counts
        # An uncapped key is still under its (absent) cap however many are recorded.
        limits = rl.RallyLimits({"monster": 20, "zombie_invasion": 0})
        assert counts.allowed("zombie_invasion", limits) is True


def test_only_the_joins_the_game_confirmed_are_counted():
    """Three sends and one confirmed join costs one, from the front of the list."""
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"], limits=rl.RallyLimits({"monster": 20}))
        gate.record_joins(rt, ["monster", "monster", "monster"], 1)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("monster") == 1, counts


def test_the_chunk_classifies_by_the_events_own_list_and_says_when_it_cannot():
    """The three endings the classifier has, pinned as text — the Lua needs a game.

    `monsterId` and `monsterType` read 0 on every leader march on the map, so the rally
    itself cannot say what it is; the event's own monster lists can, and «nobody could
    tell» has to be a sentence rather than a silent fallback to `monster`.
    """
    import lua_actions

    chunk = lua_actions.rally_join_all()
    assert "ActivityMonsterInvasionDataManager" in chunk
    assert "selfMonsters" in chunk and "aliMonsters" in chunk
    assert "'zombie_invasion'" in chunk, "the invasion kind is never returned"
    assert "inv_ok" in chunk, "nothing tells «not an invasion boss» from «could not read»"
    assert "unclassified=" in chunk, "an unreadable event list must be said, not assumed"
    # …and a banner whose kind is spent is skipped BEFORE the send, named.
    assert "capped-" in chunk
    # …and the event's own allowance is shown beside ours rather than replacing it.
    assert "game_attackNum=" in chunk

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
