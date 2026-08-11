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
        self.trophy = (0, 20, 20)

    def up(self):
        return self._types is not None

    def ready(self):
        return self._types is not None

    def evaluator(self):
        types, game = self._types, self

        class _Ev:
            @staticmethod
            def run(chunk, marker=None, settle=None, early=False):
                game.reads += 1
                if marker == "TROPHY":
                    return ["TROPHY %d %d %d" % game.trophy]
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


def test_the_reading_comes_from_the_game_and_never_refuses(monkey=None):
    """THIS is a reading; the door is elsewhere (#1281, #1317).

    The count is not ours to keep — the tally this module used to write said twenty at
    the moment the client's own read eight — so what the panel shows is what the client
    counts, and showing it refuses nothing and says nothing. The day's ceiling does exist
    again since #1317, and it is enforced where the press is: inside `rally_join_all`,
    against this same game-side number.
    """
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"], limits=rl.RallyLimits({"monster": 20}))
        rt.game.trophy = (8, 20, 12)
        assert gate.trophy_progress(rt) == {"done": 8, "max": 20, "left": 12}
        # past the threshold it still answers, and it still is not a refusal.
        rt.game.trophy = (20, 20, 0)
        assert gate.trophy_progress(rt) == {"done": 20, "max": 20, "left": 0}
        assert rt.said == [], "a reading must not say anything about refusing"


def test_a_client_that_cannot_answer_gives_no_reading_rather_than_a_wrong_one():
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), None)                       # no daemon
        assert gate.trophy_progress(rt) == {}


def test_the_gate_answers_yes_to_everything():
    """It is kept only to keep the record wired — it may never refuse a banner (#1281)."""
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"], limits=rl.RallyLimits({"monster": 1}))
        gate.record_joins(rt, ["monster"], 1)          # «spent», in the old meaning
        allowed = gate.join_gate(rt)
        assert allowed, "the gate refused — the daily count is a threshold, not a door"
        assert "monster" in allowed, allowed
        assert rt.said == []
    # …and the half that DID refuse is gone by name, so it cannot come back quietly.
    assert not hasattr(gate, "blocked_types")


def test_the_tally_is_kept_per_kind_and_reads_nothing_back():
    """What each join went to is the panel's own note; the game keeps no such thing."""
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"],
                 limits=rl.RallyLimits({"monster": 20, "zombie_invasion": 0}))
        gate.record_joins(rt, ["zombie_invasion", "monster", "zombie_invasion"], 3)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("monster") == 1, counts
        assert counts.count_for("zombie_invasion") == 2, counts
        # only what the game confirmed is counted, from the front of the list
        gate.record_joins(rt, ["monster", "monster", "monster"], 1)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("monster") == 2, counts


def test_the_chunk_shuts_the_day_on_the_games_count_and_never_on_ours():
    """The day HAS an end again (#1317), and the number that ends it is the game's.

    #1281 took the door out and was right about the tally it took out with it: the
    panel's own count had drifted twelve ahead of the client's and was refusing banners
    the account was entitled to. It was wrong about the door. «Лимит Роковой Элиты стоит
    20, а бот целый день цепляется к стягам» — past the paid twenty a joined squad is a
    squad away from home for nothing, all evening.

    So the ceiling is the person's (`__lw_rally_cap`, `0` = none) and the count is the
    game's (`daily_kill_boss`), and nothing between them is written down here.
    """
    import lua_actions

    chunk = lua_actions.rally_join_all()
    assert "GetKillBossNum" in chunk and "GetRestKillBossNum" in chunk
    assert "trophies=" in chunk
    # The door: the person's ceiling, the game's count, and a banner NAMED as passed over
    # rather than silently dropped — «nothing was sent» must never read as «nothing was
    # out».
    assert "__lw_rally_cap" in chunk, "the ceiling no longer reaches the press"
    assert "day-capped" in chunk, "a banner held back by the day is not named"
    assert "DataCenter.__lw_rally_todo = -4" in chunk, "the recipe is not told the day is done"
    # …and NOT on a tally of ours: the file this module writes is a record of what the
    # joins went for, and no name of it may appear in the press.
    for ours in ("rally_counts", "count_for", "load_counts"):
        assert ours not in chunk, ours

    # The arithmetic itself, run rather than read — the three answers that matter.
    import lupa

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    condition = chunk[chunk.index("local capped ="):]
    condition = condition[:condition.index(" local sent,")]
    decide = lua.execute("return function(kb, cap) %s return capped end" % condition)
    assert decide(19, 20) is False, "a day with one rally left was shut"
    assert decide(20, 20) is True, "the ceiling did not shut the day"
    assert decide(275, 20) is True, "a day long past the ceiling stayed open"
    assert decide(99, 0) is False, "«0» must mean «no ceiling», not «none allowed»"
    # A GATE THAT CANNOT SEE DOES NOT REFUSE: an unreadable counter joins as before.
    assert decide(None, 20) is False, "an unreadable count refused a banner"



def test_the_tally_never_counts_more_than_the_run_sent():
    """Two drivers, one difference — the count must not be spent twice (#1281).

    `joined` is a DIFFERENCE: our squads in a rally now, less the number when the run
    began. The schedule's trigger and the capture's own reader both play this recipe, so
    a squad that landed from the other one's send between a run's snapshot and its check
    falls inside both differences and both used to record it. Over one live event the
    tally read 53 against 34 confirmed joins and 35 trophies.
    """
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"])
        # One banner sent to, three joins seen: only the one this run sent is counted.
        gate.record_joins(rt, ["doom_elite"], 3)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("doom_elite") == 1, counts
        # A run that sent NOTHING records nothing, whatever difference it saw — that
        # was the actual leak: the second driver reported a join the first one had sent.
        gate.record_joins(rt, [], 2)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("doom_elite") == 1 and counts.count_for("monster") == 0, counts

        # …and a run that sent two and saw two counts both.
        gate.record_joins(rt, ["monster", "monster"], 2)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("monster") == 2, counts


def test_the_join_does_not_start_when_every_squad_it_may_send_is_out():
    """The check is in front of the run, and it is fresh (#1281).

    «Не нужно вообще запускать сценарий авторалли, если все отряды заняты — только стек
    заполнять понапрасну.» A push lands for every banner on the map, and a run that can
    only discover there is nobody to send costs a claim, a context and the queue slot
    behind it. Measured at 0.06–0.10 s on the live client, which is what makes asking
    first cheaper than finding out.
    """
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"])

        class _Ev:
            answer = "FS free=0"

            @staticmethod
            def run(chunk, marker=None, settle=None, early=False):
                _Ev.seen = chunk
                return [_Ev.answer]

        rt.game.evaluator = lambda: _Ev()

        # Nobody home: the errand is not started, and the reason is a locale key.
        assert gate.join_precondition(rt, [1, 2]) == "rally.skip.squads_out"
        # …asked about THOSE squads and no others.
        assert "[1]=true" in _Ev.seen and "[2]=true" in _Ev.seen, _Ev.seen

        # One squad home: the run goes ahead.
        _Ev.answer = "FS free=1"
        assert gate.join_precondition(rt, [1, 2]) is None

        # A GATE THAT CANNOT SEE DOES NOT REFUSE — an unreadable answer lets it run.
        _Ev.answer = "nothing of the sort"
        assert gate.join_precondition(rt, [1]) is None
        rt.game._types = None                       # game not ready at all
        assert gate.free_squads(rt, [1]) is None
        assert gate.join_precondition(rt, [1]) is None


def test_an_empty_squad_is_not_a_busy_one():
    """«Отряд пуст» and «отряд занят» are different answers (#1285, #1281).

    An empty squad is one request away from being full, so it must not stop the run from
    starting — the chunk counts a squad by its STATE and never looks at its soldiers.
    """
    assert "totalSoldierNum" not in gate.FREE_SQUADS_CHUNK, gate.FREE_SQUADS_CHUNK
    assert "IsFree" in gate.FREE_SQUADS_CHUNK and "f.state" in gate.FREE_SQUADS_CHUNK


def test_a_banner_with_no_seat_left_is_never_a_target():
    """A rally still gathering can still be shut, and the chunk must see it (#1281).

    Occupancy is counted in the client's own march list (every member march of a rally is
    in it) and the SIZE comes off the wire — `assemblyMarchMax`, which the client's march
    record drops exactly as it drops `targetContentId`. Nine banners measured live during
    the Marshal event read 5 of 5 while `endTime` still said they were standing.
    """
    import lua_actions

    chunk = lua_actions.rally_join_all()
    assert "__lw_rally_slots" in chunk, "the seats never reach the chunk"
    assert "count_of" in chunk, "occupancy is not counted"
    assert "banner-full" in chunk and "no_seat=[" in chunk, "a shut banner is not named"
    # …and a banner whose size was never heard is NOT filtered: an unheard size is not a
    # full banner, and shutting one that was open costs a join for nothing.
    assert "mx ~= nil and mx > 0 and taken >= mx" in chunk, chunk[:200]
    # A refusal from the server is terminal for the run and named as its own reason.
    assert "__lw_rally_shut" in chunk and "refused-full" in chunk
    assert "__lw_rally_sent_teams" in chunk, "the recipe cannot tell which banners refused"


def test_the_kinds_are_the_games_own_species():
    """Type 7 and type 8 are different keys, and an unseen type names itself (#1281).

    `lw_world_monster.type` is the split the player reads off the screen: 7 is the zombie
    line, 8 is the Doom line («Роковая Элита»). Counting both as `monster` is what made
    the budget one bucket, and the chunk classifies for real now.
    """
    import lua_actions

    chunk = lua_actions.rally_join_all()
    # the id comes off the WIRE — the client's march record does not carry it
    assert "__lw_rally_targets" in chunk
    assert "lw_world_monster" in chunk
    # …and the two species land in two keys, with an unseen one naming itself
    assert "'doom_elite'" in chunk, "type 8 has no key of its own"
    assert "tonumber(ty) == 8" in chunk and "tonumber(ty) == 7" in chunk
    assert "'monster_type_'" in chunk, "an unknown type must name itself, not become monster"
    # a banner nobody heard the push for is counted, and SAID
    assert "return 'monster', false end" in chunk
    assert "unclassified=" in chunk
    # AN UNKNOWN ROW ANSWERS EMPTY, NOT NIL. Asked live for an id the table has never
    # heard of, `getValue` came back with '' — and the first version of the branch above
    # turned that into the key `monster_type_` with nothing after it. Empty is «no
    # answer»: it has to fall through to the unheard-of case, and the numeric guard
    # keeps anything non-numeric from becoming a species with a blank name.
    assert "tostring(ty) == '' then ty = nil" in chunk
    assert "tonumber(ty) ~= nil" in chunk
    # …and the report says what each squad went for
    assert "going_for=[" in chunk


def test_doom_elite_is_a_key_of_its_own_with_its_own_budget():
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"])
        limits = rl.load_limits(rt.profiles.rally_limits_json())
        assert "doom_elite" in limits.types(), limits.types()
        gate.record_joins(rt, ["doom_elite", "monster", "doom_elite"], 3)
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("doom_elite") == 2, counts
        assert counts.count_for("monster") == 1, counts


class _Ctx:
    """A finished run, wearing only what the accounting reads off it."""

    def __init__(self, **vars_) -> None:
        self.vars = dict(vars_)


def test_one_rule_counts_a_run_whichever_driver_played_it():
    """`record_run` is the ONE writer, and it reads the run rather than being told (#1281).

    Two things play `join_rally`: the schedule's «rally_auto_join» trigger and the «Ралли»
    tab's own reader. The arithmetic used to live in the schedule, so every join the
    tab's driver made went unrecorded — over one live window `rally_counts` read 11
    against 13 confirmed joins.
    """
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"])
        # …one entry per squad the run sent, in the order it sent them
        assert gate.record_run(rt, _Ctx(kinds="doom_elite,monster", joined=2)) == 2
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("doom_elite") == 1, counts
        assert counts.count_for("monster") == 1, counts

        # NEVER MORE THAN THIS RUN SENT. `joined` is a difference, so a squad the OTHER
        # driver sent that lands mid-run falls inside both runs' differences.
        assert gate.record_run(rt, _Ctx(kinds="monster", joined=3)) == 1
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("monster") == 2, counts

        # …and a run that sent nothing writes nothing, whatever it saw.
        assert gate.record_run(rt, _Ctx(kinds="", joined=1)) == 0
        assert gate.record_run(rt, _Ctx(kinds="monster", joined=0)) == 0
        counts = rl.load_counts(rt.profiles.rally_counts_json())
        assert counts.count_for("monster") == 2, counts

        # A run whose variables never arrived is a run that did nothing, not a crash.
        assert gate.record_run(rt, _Ctx()) == 0
        assert gate.record_run(rt, _Ctx(kinds="monster", joined="—")) == 0


def test_both_drivers_reach_the_same_writer():
    """The schedule's hook and the tab's own play call one function, not two copies."""
    import inspect

    main_src = Path("panel/__main__.py").read_text(encoding="utf-8")
    assert "rallygate.record_run(rt, ctx)" in main_src, \
        "the schedule's record hook no longer goes through the one writer"
    tab_src = Path("panel/tabs/rally/tab.py").read_text(encoding="utf-8")
    assert "rallygate.record_run(self.rt, out.ctx)" in tab_src, \
        "the tab's own driver plays the join without counting it"
    # …and the schedule keeps no opinion of its own about what a join is worth.
    sched_src = Path("panel/runtime/schedule.py").read_text(encoding="utf-8")
    assert "def _kinds" not in sched_src and "def _did" not in sched_src, \
        "the counting rule grew back in the schedule, where only one driver reaches it"
    assert "record(ctx)" in sched_src, sched_src[:0]
    assert len(inspect.signature(gate.record_run).parameters) == 2


def test_a_profile_written_before_the_doom_key_grows_it():
    """The vocabulary grew; an old profile's file must not stay one bucket short."""
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"], limits=rl.RallyLimits({"monster": 20}))
        limits = rl.load_limits(rt.profiles.rally_limits_json())
        assert limits.limit_for("monster") == 20
        assert "doom_elite" in limits.types(), limits.types()


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
