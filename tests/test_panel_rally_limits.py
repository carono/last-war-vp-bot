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
    assert limits.limit_for("zombie_invasion") == rl.DEFAULT_CAP    # untouched
    assert limits.limit_for("desert_boss") == 0                     # …and still uncapped


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
    # …and a NEW built-in kind is folded into the old file rather than lost, with the
    # number the person asked for: «по умолчанию на всех по 20, на золотых без лимита».
    assert back.limit_for("zombie_invasion") == rl.DEFAULT_CAP
    assert back.limit_for("oni_general") == rl.DEFAULT_CAP
    # «на золотых оставляем без лимита» — and «золотые» is exactly the four the game
    # calls Golden, the Desert Boss («Золотой вожак») among them.
    for golden in ("desert_boss", "golden_defender", "golden_striker",
                   "golden_annihilator"):
        assert back.limit_for(golden) == 0, golden
    # …and the Wandering Mummy Warlord is NOT one of them: «мумию не учитываем», said
    # after a day of it running uncapped. It is an ordinary twenty like everything else.
    assert back.limit_for("wandering_mummy_warlord") == rl.DEFAULT_CAP
    assert "wandering_mummy_warlord" not in rl.UNCAPPED_KINDS
    assert set(rl.UNCAPPED_KINDS) <= set(rl.rally_kinds.KIND_ORDER)
    assert set(rl.DEFAULT_RALLY_LIMITS) == set(rl.rally_kinds.KIND_ORDER)


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
    condition = condition[:condition.index(" local minpool =")]
    decide = lua.execute("return function(kb, cap) %s return capped end" % condition)
    assert decide(19, 20) is False, "a day with one rally left was shut"
    assert decide(20, 20) is True, "the ceiling did not shut the day"
    assert decide(275, 20) is True, "a day long past the ceiling stayed open"
    assert decide(99, 0) is False, "«0» must mean «no ceiling», not «none allowed»"
    # A GATE THAT CANNOT SEE DOES NOT REFUSE: an unreadable counter joins as before.
    assert decide(None, 20) is False, "an unreadable count refused a banner"



def test_the_kinds_are_named_off_the_games_own_config():
    """Every species the caps list knows is recognised by its `name` key (#1317).

    The player asked for a counter per kind and named the ones that matter: «кроме
    Роковой Элиты есть ещё генералы, простые и элитные». The chunk had exactly two
    species, and one of them was mislabelled: `type == 8` is the Doom WALKER line
    («Разрушитель»), while Doom Elite (`300602`) sits under three different types across
    seasons — so the honest identity is the `name` key, not the type.
    """
    import lua_actions

    chunk = lua_actions.rally_join_all()
    for key, kind in (("'2010220'", "general_trial"),
                      ("'challenge_zombie_001'", "general_trial_elite"),
                      ("'300602'", "doom_elite"),
                      ("'monster_boss_name_001'", "doom_walker"),
                      ("'2901012'", "zombie_boss")):
        assert key in chunk and "'%s'" % kind in chunk, (key, kind)
    # …the two events that name their own boss rather than a species on the map.
    assert "AllyDrillDataManager" in chunk and "bossUuid" in chunk, "the drill is not seen"
    assert "'alliance_drill'" in chunk and "'zombie_invasion'" in chunk
    # …and the General's Trial's own activity id, as the fallback for a season that
    # renames its instructors.
    assert "'107'" in chunk, "the trial's activity column is not read"


def test_every_kind_the_game_knows_has_a_name_and_a_label():
    """The whole vocabulary, read off the live config rather than guessed (#1317).

    «Делай всех, кого перечислил.» So the list is every `boss = 1` row of
    `lw_world_monster` grouped by its `name` key — and the labels are the GAME's words for
    them, pulled out of its own tables, because the panel may not name what the game has
    already named.
    """
    import json
    from pathlib import Path

    import rally_kinds as rk

    assert len(rk.KIND_ORDER) > 60, len(rk.KIND_ORDER)
    assert len(set(rk.KIND_ORDER)) == len(rk.KIND_ORDER), "a kind is listed twice"
    # the ones the player named, by the game's own key
    for key, kind in (("300602", "doom_elite"),
                      ("monster_boss_name_001", "doom_walker"),
                      ("2901012", "zombie_boss"),
                      ("2901011", "invading_zombies"),
                      ("season_s4_city_boss_name", "oni_general"),
                      ("season_s3_dark_knight_name", "desert_boss"),
                      ("2010220", "general_trial"),
                      ("challenge_zombie_001", "general_trial_elite"),
                      ("2010221", "general_trial_forces")):
        assert rk.KIND_OF_NAME[key] == kind, (key, rk.KIND_OF_NAME.get(key))
    # …and the six rows the game calls «Роковая Элита» are ONE kind, not six
    doom = [k for k, v in rk.KIND_OF_NAME.items() if v == "doom_elite"]
    assert len(doom) >= 5, doom
    # the two events have no species at all — they are matched off their managers
    for event in rk.EVENT_KINDS:
        assert event in rk.KIND_ORDER
        assert event not in rk.KIND_OF_NAME.values()

    root = Path(__file__).resolve().parents[1]
    for lang in ("en", "ru", "vi"):
        words = json.loads((root / "panel" / "locales" / f"{lang}.json").read_text("utf-8"))
        for kind in rk.KIND_ORDER:
            assert words.get("rally_limit.type." + kind), (lang, kind)


def test_a_kind_switched_off_is_left_alone_and_nothing_is_counted_for_it():
    """The filter: «к этим цепляйся, к тем нет», decided inside the press (#1317).

    A filter and not a budget — the kind of a banner is known before a squad leaves, so
    nothing has to be counted and there is nothing to drift. An empty filter is «go for
    everything», which is what a profile that has never touched the list says.
    """
    import lupa

    import lua_actions

    chunk = lua_actions.rally_join_all()
    assert "__lw_rally_kind_skip" in chunk, "the filter never reaches the press"
    assert "kind-off" in chunk, "a banner left alone is not named"
    assert "kind_off=[" in chunk, "the run does not say which kinds it left alone"
    # …and the species table is IN the press, so a season's boss is data rather than a
    # new branch of Lua.
    assert "KIND_OF_NAME" in chunk and "['300602']='doom_elite'" in chunk

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    parse = lua.execute(
        "return function(text) local off = {} "
        "for k in string.gmatch(tostring(text or ''), '[^,]+') do off[k] = true end "
        "return off end")
    off = parse("oni_general,doom_walker")
    assert off["oni_general"] and off["doom_walker"]
    assert off["doom_elite"] is None, "an unnamed kind was switched off"
    assert parse("")["doom_elite"] is None, "an empty filter stopped a banner"


def test_a_kind_with_its_day_spent_holds_its_banner_and_says_which():
    """The per-kind budget refuses inside the press, and one press cannot double-spend.

    The panel supplies the numbers — nothing in the client counts per species, which is
    why this is the one budget that can drift (#1317) — and the DECISION is here, where
    the kind of each banner is already known.
    """
    import lupa

    import lua_actions

    chunk = lua_actions.rally_join_all()
    assert "__lw_rally_kind_left" in chunk, "the per-kind budget never reaches the press"
    assert "kind-capped" in chunk, "a banner held back by its kind is not named"

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    parse = lua.execute(
        "return function(text) local kind_left = {} "
        "for pair in string.gmatch(tostring(text or ''), '[^,]+') do "
        "local k, n = string.match(pair, '([%w_]+):(%-?%d+)') "
        "if k ~= nil then kind_left[k] = tonumber(n) end end return kind_left end")
    left = parse("doom_elite:2,general_trial:0,zombie_boss:-1")
    assert left["doom_elite"] == 2 and left["general_trial"] == 0
    assert left["zombie_boss"] == -1, "«no cap» must survive the trip as -1"

    # the decision the send loop makes with them, in the chunk's own words
    decide = lua.execute(
        "return function(left) "
        "if left ~= nil and left >= 0 and left <= 0 then return 'held' end "
        "return 'sent' end")
    assert decide(0) == "held", "a spent kind was joined"
    assert decide(2) == "sent"
    assert decide(-1) == "sent", "«no cap» refused a banner"
    assert decide(None) == "sent", "a kind nobody capped refused a banner"


def test_a_renamed_kind_keeps_the_number_somebody_typed():
    """`doom_elite` counted the Doom WALKER, so the value travels rather than the key.

    The label said «Роковая Элита» and the key counted type 8, which is «Разрушитель».
    Both readings of what the person meant are honoured for a CAP — the number lands on
    both rows — and for a COUNT only on the row that was really being counted, or today's
    Doom Walkers would spend a Doom Elite budget nothing was spent from (#1317).
    """
    limits = rl.migrate_kinds({"doom_elite": 20, "monster": 5})
    assert limits["doom_walker"] == 20 and limits["doom_elite"] == 20, limits
    assert limits["monster"] == 5

    # A COUNT moves rather than being copied: one join has to appear exactly once, or the
    # sum the game's own daily count is checked against is doubled for ever (#1317).
    counts = rl.migrate_kinds({"doom_elite": 28}, tally=True)
    assert counts["doom_walker"] == 28, counts
    assert "doom_elite" not in counts, counts
    assert sum(counts.values()) == 28, counts

    # a profile edited since the rename keeps what the person typed there
    kept = rl.migrate_kinds({"doom_elite": 20, "doom_walker": 3})
    assert kept["doom_walker"] == 3, kept


def test_the_day_rolls_on_the_servers_boundary_not_this_machines():
    """A daily budget resets when the SERVER's day turns (#1317).

    The client answers it exactly (`GetTomorrowZero()`), the PC clock does not — it was
    eleven seconds out when `game_clock` was written, and the boundary is 02:00 UTC on
    the warzone this was measured on rather than local midnight.
    """
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "counts.json")
        store = rl.RallyCounts("2026-08-11", {"doom_elite": 3}, path, day_end_ms=2_000)
        # before the boundary the tally stands, whatever the date string says
        assert store.rolled(today="2026-08-12", now_ms=1_999).count_for("doom_elite") == 3
        # …and past it the day is empty, even on the same date string
        assert store.rolled(today="2026-08-11", now_ms=2_001).count_for("doom_elite") == 0

        # The stamp survives a save/load round trip, and so does the tally under it —
        # with a boundary that has NOT passed, because a load rolls against the game's
        # clock and a day that ended is meant to come back empty.
        future = rl.RallyCounts("2026-08-11", {"doom_elite": 3}, path,
                                day_end_ms=4_000_000_000_000)
        rl.save_counts(future, path)
        again = rl.load_counts(path, today="2026-08-11")
        assert again.day_end_ms == 4_000_000_000_000, again.day_end_ms
        assert again.count_for("doom_elite") == 3, again.counts

        # …and a stamp that HAS passed empties the day on the next read, whatever the
        # date string in the file says.
        rl.save_counts(store, path)
        assert rl.load_counts(path, today="2026-08-11").count_for("doom_elite") == 0

        # a store that has never been able to ask a client still rolls on the date
        blind = rl.RallyCounts("2026-08-10", {"monster": 2}, path)
        assert blind.rolled(today="2026-08-11").count_for("monster") == 0


def test_what_each_kind_has_left_is_what_the_recipe_is_handed():
    """`kind:left,…`, with «no cap» left out — the shape the press parses (#1317)."""
    with tempfile.TemporaryDirectory() as td:
        rt = _Rt(Path(td), ["monster"],
                 limits=rl.RallyLimits({"doom_elite": 3, "monster": 0}))
        gate.record_joins(rt, ["doom_elite", "doom_elite"], 2)
        rt.game.trophy = (2, 20, 18)          # the game agrees two rallies happened
        left = dict(part.split(":") for part in gate.kind_left(rt).split(",") if part)
        assert left["doom_elite"] == "1", left
        assert "monster" not in left, "an uncapped kind must not be named at all"
        # …and a kind whose day is gone says 0 rather than dropping out of the list
        gate.record_joins(rt, ["doom_elite"], 1)
        rt.game.trophy = (3, 20, 17)
        left = dict(part.split(":") for part in gate.kind_left(rt).split(",") if part)
        assert left["doom_elite"] == "0", left

        # AND THE RECONCILIATION (#1317): while OUR tally runs ahead of the game's own
        # count, no per-kind door refuses anything — #1281's twelve-ahead tally is exactly
        # what that prevents. The game's total ceiling still guards the other direction.
        rt.game.trophy = (1, 20, 19)          # the game says one; we think three
        assert gate.ahead_of_game(rt) is True
        assert gate.kind_left(rt) == "", "a banner was refused on a number the game denies"
        summary = gate.day_summary(rt)
        assert summary["kinds"] == 3 and summary["game"] == 1 and summary["drift"] == 2

        # …a client that cannot be asked neither refuses nor relaxes on a guess
        rt.game._types = None
        assert gate.ahead_of_game(rt) is False
        assert gate.day_summary(rt)["game"] == -1


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


def test_a_seed_of_ours_that_changed_is_carried_across_but_a_typed_number_is_not():
    """«Мумию не учитываем» has to reach the profiles that were seeded uncapped (#1317).

    The Wandering Mummy Warlord shipped with no cap for a day, so every profile opened in
    that day holds a `0` nobody chose — and a profile's own file wins over the built-ins,
    which is right for a number somebody typed and wrong for one this module put there.

    So the value moves ONLY if it is still the old seed, and only once: the file is
    rewritten at the new version, or a person setting it back by hand in the JSON would
    be undone at the next start-up.
    """
    tmp = Path(tempfile.mkdtemp())
    path = str(tmp / "rally_limits.json")
    # A profile written while the mummy was uncapped — version 2, the seed's own 0.
    Path(path).write_text(json.dumps({"v": 2, "monster": 20,
                                      "wandering_mummy_warlord": 0,
                                      "golden_defender": 0}), encoding="utf-8")
    back = rl.load_limits(path)
    assert back.limit_for("wandering_mummy_warlord") == rl.DEFAULT_CAP
    # …the Golden line was not touched: it is still uncapped on purpose.
    assert back.limit_for("golden_defender") == 0
    # …and the file now says so, so the migration cannot run twice.
    stored = json.loads(Path(path).read_text(encoding="utf-8"))
    assert stored["v"] == rl.FILE_VERSION
    assert stored["wandering_mummy_warlord"] == rl.DEFAULT_CAP

    # A NUMBER SOMEBODY TYPED IS NEVER MOVED, whatever it is.
    other = str(tmp / "typed.json")
    Path(other).write_text(json.dumps({"v": 2, "wandering_mummy_warlord": 7}),
                           encoding="utf-8")
    assert rl.load_limits(other).limit_for("wandering_mummy_warlord") == 7
    # …and a file already at the new version is left exactly as it is, including a 0
    # the person chose for themselves after the reseed.
    now = str(tmp / "now.json")
    Path(now).write_text(json.dumps({"v": rl.FILE_VERSION,
                                     "wandering_mummy_warlord": 0}), encoding="utf-8")
    assert rl.load_limits(now).limit_for("wandering_mummy_warlord") == 0


def test_the_soldier_floor_refuses_the_whole_run_and_never_on_an_unread_pool():
    """One door over the run, judged on the base's own pool (#1317).

    «Сделай проверку для отправки войск: наполненность не одного отряда, а всех трёх.
    Если на 3 отряда солдат не хватает, не присоединяемся.» Soldiers are ONE pool and
    every squad draws from it, so the per-squad ceiling cannot answer it — filling the
    first squad is what empties the base for the second. The person set the shape of the
    answer too: an absolute number they read off their own base, and marching soldiers do
    not count towards it.
    """
    import lua_actions
    import lupa

    chunk = lua_actions.rally_join_all()
    assert "__lw_rally_min_soldiers" in chunk, "the floor no longer reaches the press"
    assert "GetPlayerSoldiersTotalNum" in chunk, "the pool it is judged against is gone"
    assert "low-on-soldiers(" in chunk, "a banner held back by the floor is not named"
    assert "DataCenter.__lw_rally_todo = -5" in chunk, "the recipe is not told the base is low"
    assert "soldiers='..pool..'/'..minpool" in chunk, "the report hides one of the numbers"

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    condition = chunk[chunk.index("local minpool ="):]
    condition = condition[:condition.index(" local kind_left =")]
    decide = lua.execute("return function(pool, floor) "
                         "local DataCenter = {__lw_rally_min_soldiers = floor} "
                         "%s return short_pool end" % condition)
    assert decide(5000, 9000) is True, "a base under the floor still joined"
    assert decide(9000, 9000) is False, "a base exactly at the floor was refused"
    assert decide(12000, 9000) is False, "a full base was refused"
    assert decide(0, 9000) is False, "an unread pool refused a banner"
    assert decide(200, 0) is False, "«0» must mean «no floor», not «join nothing»"

    # THE ORDER OF THE ENDINGS. The floor outranks every squad-shaped verdict — fetching
    # an army for a squad that may not be spent is a call spent on a refused run — and
    # the day's ceiling outranks the floor, because «сегодня всё» is the more final of
    # the two.
    assert chunk.index("DataCenter.__lw_rally_todo = -5") < \
        chunk.index("if capped then DataCenter.__lw_rally_todo = -4 end"), \
        "a spent day is overwritten by a low base"

    recipe = Path("src/lastwar_bot/actions/join_rally.md").read_text(encoding="utf-8")
    assert "ARGS min_soldiers = 0" in recipe, "the recipe does not declare the floor"
    assert 'DataCenter.__lw_rally_min_soldiers = tonumber("{min_soldiers}")' in recipe, \
        "the floor is not parked where the press reads it"
    assert recipe.index("IF todo == -5") < recipe.index("IF todo == -3"), \
        "the low base is reported as an under-strength squad"


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
