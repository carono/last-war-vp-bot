r"""The «Чеклист» tab: a board that is READ, and the one lie it must never tell.

The rule this file exists to hold is **«состояние считается из игры, но выполнение можно
вызывать»**, and it has two halves that are easy to collapse into one another:

* a line is done because the GAME says there is nothing left of it — never because
  somebody ticked a box, and never because a scenario was started;
* but a line that IS an ability the bot has carries a button, and pressing it is
  perfectly ordinary. The press starts work; the reading that follows moves the row.

Collapsing the second into the first is what happened once already: «a button that
starts something is a button somebody expects to have MARKED the line» sounded right,
the nine «Выполнить» went (#1239), and the board became a thing you could only look at.
The tests below therefore pin BOTH halves — that nothing marks, and that the presses
are there and reach the scenarios.

So most of them are about the third state: a reading that did not arrive, a field the
client would not answer, an event that is not on. Each has to come out as «unknown» or
«not running» and NOT as done, because a checklist that quietly reports a dark client as
a finished day is worse than no checklist at all.

A third half, added later (#1275): **a group can be switched OFF**, and off has to mean
off everywhere at once. The board went up faster than its lines could be watched working
in a live game, so it is put back one group at a time — «Кодовое имя» is the only one on
— and the tests below pin what «off» costs: no block in the window, no card on the phone,
no press from either, no line in «сделано N из M», and not even the round trip that would
read it. What they also pin is that off is not GONE: the catalogue keeps every group in
its order, so a group returns for one word rather than for an afternoon in the git log.

The other half pins the reading itself to the presses it describes: every count in
`actions/read_daily_checklist.md` is the same expression `tools/lib/lua_actions.py`
gates the matching press on, so the board and the button can never disagree about how
much work there is.

No display and no widget: the catalogue and the parser are Tk-free, and the screen tests
reach the tab class without building one. The tab MODULE still imports tkinter, which the
WSL python does not ship — those tests say SKIP there and run under the Windows one:

    C:\Python312\python.exe tests\test_panel_checklist.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lua_actions                                     # noqa: E402
from panel import i18n as i18nmod                      # noqa: E402
from panel.tabs.checklist import model as modelmod     # noqa: E402

SCENARIO = _REPO / "src" / "lastwar_bot" / "actions" / "read_daily_checklist.md"
CODENAME_SCENARIO = (_REPO / "src" / "lastwar_bot" / "actions"
                     / "read_codename_event.md")

#: The event reading, as the live client answers it while «Кодовое имя» is running.
CODENAME_OPEN = "open=1 attacks=1 need=3 left=2 maxdmg=12607399171 targets=1 until=6042"
#: …and while it is not, which is the state the board is in most of the week.
CODENAME_SHUT = "open=0 attacks=0 need=3 left=3 maxdmg=12607399171 targets=0 until=-"

#: A reading with everything answered — the shape the live game sends back.
FULL = ("base_ready=4 trucks_ready=0 donate_left=17 help_waiting=0 recruit_pending=2 "
        "gifts_pending=0 skills_ready=1 wounded=0 healed_ready=0 queues_help=3 "
        "decorations=0 steal_left=2 steal_cap=5 ghost_open=1 ghost_left=5 ghost_cap=5 "
        "trucks_send_left=5 trucks_send_cap=5 trucks_idle=3")


# ---------------------------------------------------------------------------
# the reading
# ---------------------------------------------------------------------------
def test_the_line_the_game_sends_back_is_read_as_numbers():
    reading = modelmod.parse(FULL, at=100.0)
    assert reading, "a full reading did not come out as one"
    assert reading.get("base_ready") == 4
    assert reading.get("steal_cap") == 5
    assert reading.at == 100.0


def test_a_field_the_game_would_not_answer_is_not_a_zero():
    """`-` means «nobody knows» and zero means «nothing left». Never the same thing."""
    reading = modelmod.parse("base_ready=- wounded=0")
    assert reading.get("base_ready") is None
    assert reading.get("wounded") == 0
    assert modelmod.state_of(modelmod.BY_KEY["base_resources"], reading).state == \
        modelmod.UNKNOWN
    assert modelmod.state_of(modelmod.BY_KEY["hospital_heal"], reading).state == \
        modelmod.DONE


def test_a_reading_that_never_arrived_leaves_every_line_unknown():
    """The one that matters: a dark client must not read as a finished day."""
    for reading in (None, modelmod.Reading(error="no daemon"), modelmod.parse(None),
                    modelmod.parse("")):
        states = modelmod.states(reading)
        assert states, "the catalogue came back empty"
        assert all(s.state == modelmod.UNKNOWN for s in states), \
            [s for s in states if s.state != modelmod.UNKNOWN]
        assert modelmod.progress(states) == (0, 0), "unknown lines were counted"


def test_junk_in_the_middle_costs_one_field_and_not_the_line():
    reading = modelmod.parse("base_ready=4 nonsense wounded=x healed_ready=1")
    assert reading.get("base_ready") == 4
    assert reading.get("wounded") is None
    assert reading.get("healed_ready") == 1


# ---------------------------------------------------------------------------
# the states
# ---------------------------------------------------------------------------
def test_a_queue_is_done_when_there_is_nothing_standing_in_it():
    reading = modelmod.parse(FULL)
    base = modelmod.state_of(modelmod.BY_KEY["base_resources"], reading)
    assert base.state == modelmod.TODO and base.left == 4
    trucks = modelmod.state_of(modelmod.BY_KEY["trucks"], reading)
    assert trucks.state == modelmod.DONE and trucks.left == 0


def test_a_quota_is_done_when_the_days_allowance_is_spent():
    spent = modelmod.parse("steal_left=0 steal_cap=5")
    state = modelmod.state_of(modelmod.BY_KEY["secret_steals"], spent)
    assert state.state == modelmod.DONE
    assert (state.used, state.cap) == (5, 5)

    part = modelmod.state_of(modelmod.BY_KEY["secret_steals"],
                             modelmod.parse("steal_left=2 steal_cap=5"))
    assert part.state == modelmod.TODO
    assert (part.used, part.cap) == (3, 5)

    # A cap the game would not give leaves «used» unsaid rather than invented.
    capless = modelmod.state_of(modelmod.BY_KEY["secret_steals"],
                                modelmod.parse("steal_left=2 steal_cap=-"))
    assert capless.state == modelmod.TODO and capless.used is None


def test_an_event_that_is_not_on_today_is_not_an_errand_anybody_failed():
    """Ghost Ops runs one day a week; «not done» on the other six is a lie."""
    shut = modelmod.state_of(modelmod.BY_KEY["ghost_steals"],
                             modelmod.parse("ghost_open=0 ghost_left=5 ghost_cap=5"))
    assert shut.state == modelmod.CLOSED
    open_ = modelmod.state_of(modelmod.BY_KEY["ghost_steals"],
                              modelmod.parse("ghost_open=1 ghost_left=5 ghost_cap=5"))
    assert open_.state == modelmod.TODO
    # …and a gate the client would not answer is unknown, never «closed».
    assert modelmod.state_of(modelmod.BY_KEY["ghost_steals"],
                             modelmod.parse("ghost_open=- ghost_left=5")).state == \
        modelmod.UNKNOWN


def test_progress_counts_only_the_lines_that_were_actually_answered():
    """An unknown line and a closed one are in neither half of «сделано N из M»."""
    day = modelmod.parse(FULL)
    # The board's own lines are the shown groups', so the counting is checked there.
    assert modelmod.progress(modelmod.states(day, modelmod.parse(CODENAME_SHUT))) == \
        (0, 0), "an event that is not on was counted as work somebody owes"
    assert modelmod.progress(modelmod.states(day, None)) == (0, 0), \
        "a line nobody could read was counted"
    assert modelmod.progress(modelmod.states(day, modelmod.parse(CODENAME_OPEN))) == \
        (0, 1)
    done = modelmod.parse("open=1 attacks=3 need=3 left=0 maxdmg=5 targets=1 until=60")
    assert modelmod.progress(modelmod.states(day, done)) == (1, 1)
    # …and the raw counting rule, over states built by hand, so it holds for the groups
    # that are still switched off (#1275) and will be counted again when they come back.
    by_hand = [modelmod.state_of(e, modelmod.parse(
        "base_ready=0 wounded=2 ghost_open=0 donate_left=-"))
        for e in (modelmod.BY_KEY["base_resources"], modelmod.BY_KEY["hospital_heal"],
                  modelmod.BY_KEY["ghost_steals"], modelmod.BY_KEY["alliance_donate"])]
    assert modelmod.progress(by_hand) == (1, 2), "an unknown or a closed line was counted"


# ---------------------------------------------------------------------------
# which groups are on the board at all (#1275)
# ---------------------------------------------------------------------------
def test_only_the_groups_that_are_switched_on_reach_the_board():
    """One group is drawn — and the other three are OFF, not deleted.

    The board went up faster than its lines could be watched working in a live game, so
    it is put back a group at a time as each is confirmed. What this pins is that «off»
    means off everywhere at once — no line in the states, no line in the progress — and
    that the catalogue still holds every group, so switching one back on is one word.
    """
    assert [g.key for g in modelmod.visible()] == [modelmod.CODENAME]
    assert [g.key for g in modelmod.GROUPS] == [modelmod.TRUCKS, modelmod.CODENAME,
                                                "read", "blind"], \
        "a hidden group was deleted instead of switched off — it cannot come back now"
    for group in modelmod.GROUPS:
        assert isinstance(group.shown, bool)
        assert group.errands, f"«{group.key}» lost its errands"

    board = [s.key for s in modelmod.states(modelmod.parse(FULL),
                                            modelmod.parse(CODENAME_OPEN))]
    assert board == ["codename"], board
    # …and the errands of a hidden group are still there to be read by anybody who asks.
    assert modelmod.BY_KEY["base_resources"].readable
    assert modelmod.state_of(modelmod.BY_KEY["base_resources"],
                             modelmod.parse(FULL)).state == modelmod.TODO


def test_a_line_of_a_hidden_group_cannot_be_pressed_from_either_front_end():
    """Off in the window is off on the phone — the press is gated in `run`, not at a widget."""
    assert modelmod.is_visible("codename")
    for hidden in ("base_resources", "skills", "send_trucks", "ministry",
                   "alliance_gifts"):
        assert not modelmod.is_visible(hidden), hidden
        tab = _tab(codename=CODENAME_OPEN)
        assert tab.run(hidden) is False, f"«{hidden}» is off the board and ran anyway"
        assert tab.rt.played == [], f"«{hidden}» reached the game"
        assert tab.web_press("run", {"key": hidden}) == {"ok": False}


def test_the_blocks_stand_three_to_a_row_and_nothing_measures_a_column():
    """The layout, and the trap under it (#1211/#1215).

    Three uniform columns is the shape; what this really guards is the SECOND half —
    that no `<Configure>` handler ever appears here to wrap a label to the width its
    column turned out to have. That is the loop «Дуэль VS» paid 2.3 seconds of page
    build for: wrapping re-lays-out, the re-layout fires `<Configure>`, and getting out
    of it took an idle-time coalescer, a style per frame and a «already this wide» guard.
    A constant wrap costs one measurement per label and cannot feed itself.

    Measured before and after the columns went in, same machine, back to back: the board
    as shipped stays at 55–65 ms, and the whole day with every group switched on came out
    at 429–448 ms against 481–772 ms in one column. The columns are not a cost.
    """
    tabmod = _tab_module()
    assert tabmod.COLUMNS == 3
    assert isinstance(tabmod.WRAP_PX, int) and tabmod.WRAP_PX > 0

    source = (_REPO / "panel" / "tabs" / "checklist" / "tab.py").read_text(
        encoding="utf-8")
    # The CODE, not the prose: the constant's own comment names the trap it avoids, and
    # a test that could not tell the two apart would forbid explaining anything.
    for trap in ('bind("<Configure>"', ".winfo_width()", ".winfo_reqwidth()",
                 "after_idle("):
        assert trap not in source, (
            f"«{trap}» is back on the checklist: a wrap that measures its column is the "
            f"loop #1211 spent 2.3 s a page build in — keep WRAP_PX a constant")
    assert 'uniform="checklist.group"' in source, "the columns stopped being equal"


def test_the_board_reads_only_the_scenarios_the_shown_groups_need():
    """A poll for numbers nobody is drawn is a round trip an hour for a blank."""
    assert modelmod.visible_sources() == frozenset({modelmod.CODENAME})
    tab = _tab()
    assert tab.refresh() is True
    assert tab.rt.played == [modelmod.CODENAME_ACTION], tab.rt.played
    from panel.tabs.checklist import tab as tabmod
    assert tabmod.WIRE_PATTERNS_BY_SOURCE[modelmod.DAILY] == tabmod.WIRE_PATTERNS
    assert tab._patterns() == (), \
        "the board still listens for pushes about groups it does not draw"


def test_the_countdown_is_to_the_games_next_day():
    day = modelmod.DAY_MS
    assert modelmod.seconds_to_reset(20_000 * day) == 24 * 3600
    assert modelmod.seconds_to_reset(20_000 * day + 23 * modelmod.HOUR_MS) == 3600
    assert modelmod.hhmm(5 * 3600 + 7 * 60) == "5:07"
    assert modelmod.ago(75) == "1:15"


# ---------------------------------------------------------------------------
# the reading and the presses cannot drift apart
# ---------------------------------------------------------------------------
def test_every_count_on_the_board_is_the_one_the_press_is_gated_on():
    """The checklist copies `lua_actions`' expressions rather than inventing its own.

    If this fails, somebody changed a count in one place: re-generate the scenario, do
    not «fix» the test. A board that says four buildings are ready where the press finds
    none is the one bug this whole design is meant to make impossible.
    """
    text = SCENARIO.read_text(encoding="utf-8")
    for name in ("base_collect_ready_count", "trucks_ready_count",
                 "alliance_donate_rest", "alliance_help_waiting",
                 "visitor_recruit_pending", "visitor_gift_pending",
                 "occupation_skills_ready_count", "hospital_wounded_count",
                 "hospital_healed_ready", "queues_needing_help",
                 "decoration_upgrade_ready_count", "secret_task_steals_left",
                 "secret_task_steal_cap", "ghost_recon_is_open",
                 "ghost_recon_steals_left", "ghost_recon_steal_cap",
                 "truck_dispatch_left", "truck_dispatch_cap",
                 "truck_dispatch_ready"):
        expr = getattr(lua_actions, name)()
        assert expr in text, (
            f"{name}() is no longer what read_daily_checklist.md reads — "
            f"the board and the press would disagree")


def test_the_scenario_answers_every_field_the_catalogue_asks_about():
    """Every field a group asks for is answered by the scenario that group reads.

    TWO scenarios reach this board now (#1257): the day's errands, and «Кодовое имя»,
    which «События» reads as well. A group names its own source, so a field that moved
    between the two is a failure here rather than a row that quietly says «unknown».
    """
    texts = {modelmod.DAILY: SCENARIO.read_text(encoding="utf-8"),
             modelmod.CODENAME: CODENAME_SCENARIO.read_text(encoding="utf-8")}
    for group in modelmod.GROUPS:
        text = texts[group.source]
        for errand in group.errands:
            for field in (errand.field, errand.cap, errand.gate):
                if field:
                    assert ("put('%s'" % field) in text, (
                        f"«{errand.key}» reads {field}, which "
                        f"{group.source} does not answer")
    assert "INTO %s" % modelmod.VARIABLE in texts[modelmod.DAILY]
    assert "INTO %s" % modelmod.CODENAME_VARIABLE in texts[modelmod.CODENAME]
    for action in (modelmod.ACTION, modelmod.CODENAME_ACTION, modelmod.CODENAME_ATTACK):
        assert (_REPO / "src" / "lastwar_bot" / "actions" / (action + ".md")).exists(), \
            f"«{action}» is named by the board and is not a scenario"


def test_the_scenario_is_a_read_and_presses_nothing():
    """It runs on a poll and on a push, so it must never change anything."""
    body = [line for line in SCENARIO.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    assert len(body) == 1 and body[0].startswith("READ_LUA "), body
    for forbidden in ("TAP ", "SendMessage", "SendCollect", "OnClick", "SendLuaMessage"):
        assert forbidden not in body[0], f"the reading contains «{forbidden}»"


def test_the_state_is_read_and_the_doing_is_offered():
    """The rule, in the shape the catalogue has to hold it.

    Nothing here is ticked by hand — there is no `done` field, no setter, no way for the
    panel to record an opinion of its own. But an errand the bot HAS an ability for
    carries the scenario that plays it, and the two are not in tension: pressing starts
    work, the board is re-read, and the row follows the game.
    """
    for errand in modelmod.ERRANDS:
        for marking in ("done", "ticked", "mark", "set_done", "complete"):
            assert not hasattr(errand, marking), \
                f"«{errand.key}» carries «{marking}» — a line is read, never recorded"
        assert isinstance(errand.scenario, str)
        assert errand.runnable == bool(errand.scenario)
        if errand.runnable:
            assert (_REPO / "src" / "lastwar_bot" / "actions"
                    / (errand.scenario + ".md")).exists(), \
                f"«{errand.key}» names a scenario that does not exist"
            assert errand.run_key.startswith("checklist."), errand.run_key


def test_the_nine_errands_with_an_ability_offer_it_and_the_four_without_do_not():
    """Which lines have a button is a decision, not an accident — so it is pinned.

    The four without: `trucks` and `queues_help` have no ability at all yet, and the two
    robberies have one that only SPENDS a queue their own tool has to park the targets in
    first (#1188) — a press from this board would succeed and rob nothing.
    """
    runnable = [e.key for e in modelmod.READ_ERRANDS if e.runnable]
    assert runnable == ["base_resources", "hospital_collect", "hospital_heal",
                        "alliance_help", "alliance_donate", "visitors_recruit",
                        "visitors_gifts", "skills", "decorations"], runnable
    silent = [e.key for e in modelmod.READ_ERRANDS if not e.runnable]
    assert silent == ["trucks", "queues_help", "secret_steals", "ghost_steals"], silent

    # …and «Кодовое имя» is one of them and not a special case: a scenario and a
    # run_key, the same two fields, differing only in the verb on the button.
    codename = modelmod.BY_KEY["codename"]
    assert codename.scenario == modelmod.CODENAME_ATTACK
    assert codename.run_key == "checklist.codename.attack"

    # Three of the blind group CAN be run, and which three is a decision too (#1247).
    # Blind is a statement about what can be seen, and the two halves fail apart: the
    # bot empties the base's resource truck, claims the alliance gifts and applies for
    # the ministry post without being able to read any of the three afterwards. The row
    # still says «неизвестно» before the press and after it — nothing was read, so
    # nothing is claimed — but the ability is reachable without «Разработка», which is
    # off unless a profile asks for it.
    blind = [e.key for e in modelmod.BLIND_ERRANDS if e.runnable]
    assert blind == ["truck_reward", "alliance_gifts", "ministry"], blind
    assert modelmod.BY_KEY["ministry"].run_key == "checklist.run.ministry"


def test_a_line_nothing_can_read_says_so_and_never_anything_else():
    """The blind half of the day is on the board, honestly labelled.

    Left off, the checklist would look finished with a third of the routine missing from
    it; given a box, it would be the hand-marking this tab exists without. So it is a row
    that says «unknown» whatever the reading says, and is counted in neither half.
    """
    assert modelmod.BLIND_ERRANDS, "the blind half of the day vanished"
    for errand in modelmod.BLIND_ERRANDS:
        assert not errand.readable and not errand.field
        for reading in (None, modelmod.parse(FULL), modelmod.Reading(error="x")):
            assert modelmod.state_of(errand, reading).state == modelmod.UNKNOWN
    # A full reading answers every readable line and none of the blind ones, so the
    # counted total is exactly the read half of what is DRAWN — however long the blind
    # half grows, and whichever groups are switched on at the time (#1275).
    done, total = modelmod.progress(modelmod.states(modelmod.parse(FULL),
                                                    modelmod.parse(CODENAME_OPEN)))
    readable = [e for e in modelmod.visible_errands() if e.readable]
    assert total == len(readable), \
        f"{len(modelmod.visible_errands()) - total} lines counted that nobody can read"


# ---------------------------------------------------------------------------
# «Отправка грузовиков» — the first group that is more than a list
# ---------------------------------------------------------------------------
def test_the_trucks_are_the_first_group_and_carry_their_own_line():
    first = modelmod.GROUPS[0]
    assert first.key == modelmod.TRUCKS
    assert first.title_key == "checklist.group.send_trucks"
    assert [e.key for e in first.errands] == ["send_trucks"]
    # …and it is the first group that will come BACK: switched off until its line has
    # been watched working live (#1275), and still first in the order when it is on.
    assert first.shown is False
    # …and it left the blind half, because it is read now.
    assert "send_trucks" not in [e.key for e in modelmod.BLIND_ERRANDS]
    assert modelmod.BY_KEY["send_trucks"].readable


def test_the_counter_is_the_quotas_own_two_halves():
    """«0 из 5» is `used` of `cap` — the same numbers the row under it is drawn from."""
    sent, cap, idle = modelmod.truck_counter(modelmod.parse(FULL))
    assert (sent, cap, idle) == (0, 5, 3)
    spent = modelmod.parse("trucks_send_left=0 trucks_send_cap=5 trucks_idle=0")
    assert modelmod.truck_counter(spent) == (5, 5, 0)
    assert modelmod.state_of(modelmod.BY_KEY["send_trucks"], spent).state == \
        modelmod.DONE


def test_a_locked_trade_station_is_never_drawn_as_nothing_sent_yet():
    """The one lie this reading could tell: a feature the account has not unlocked.

    The client answers «0 dispatched» whether the station is idle or absent, so the
    scenario returns a dash for a locked one and the board must show that as unknown —
    an errand nobody can ever finish is not a to-do.
    """
    locked = modelmod.parse("trucks_send_left=- trucks_send_cap=- trucks_idle=-")
    assert modelmod.state_of(modelmod.BY_KEY["send_trucks"], locked).state == \
        modelmod.UNKNOWN
    assert modelmod.truck_counter(locked) == (None, None, None)
    for reading in (None, modelmod.Reading(error="no daemon")):
        assert modelmod.truck_counter(reading) == (None, None, None)


def test_the_scenario_answers_the_field_beside_the_quota():
    text = SCENARIO.read_text(encoding="utf-8")
    assert ("put('%s'" % modelmod.TRUCK_IDLE_FIELD) in text


def test_the_three_modes_are_exclusive_and_default_to_spending_nothing():
    assert modelmod.TRUCK_MODES == (modelmod.TRUCK_MODE_UR_MANUAL,
                                    modelmod.TRUCK_MODE_UR_AUTO,
                                    modelmod.TRUCK_MODE_SLEIGH_AUTO)
    assert len(set(modelmod.TRUCK_MODES)) == 3
    # An automatic refresh spends contracts and diamonds; a profile nobody asked does not.
    assert modelmod.TRUCK_MODE_DEFAULT == modelmod.TRUCK_MODE_UR_MANUAL
    for junk in (None, "", "по-своему", 7, True, ["ur_auto"]):
        assert modelmod.truck_mode(junk) == modelmod.TRUCK_MODE_DEFAULT
    for mode in modelmod.TRUCK_MODES:
        assert modelmod.truck_mode(mode) == mode


def test_the_mode_is_kept_by_the_profile_and_nothing_else_is():
    tab = _tab()
    assert tab.config() == {"truck_mode": modelmod.TRUCK_MODE_DEFAULT}
    tab.apply_config({"truck_mode": modelmod.TRUCK_MODE_SLEIGH_AUTO})
    assert tab.config() == {"truck_mode": modelmod.TRUCK_MODE_SLEIGH_AUTO}
    # A hand-edited profile cannot put the tab in a mode it has no words for.
    tab.apply_config({"truck_mode": "whatever"})
    assert tab.config() == {"truck_mode": modelmod.TRUCK_MODE_DEFAULT}
    tab.apply_config("not a dict")
    assert tab.config() == {"truck_mode": modelmod.TRUCK_MODE_DEFAULT}
    assert tab.persist_vars() == [tab._truck_mode]


def test_the_phone_sees_the_counter_the_press_and_the_mode_that_is_on():
    """The trucks' card is OFF with its group — and is whole for the day it comes back.

    While the group is hidden (#1275) the phone must not carry a card the window does not
    draw, so what is pinned here is both halves: nothing on the screen, and the rows and
    items the screen is built from still saying the right things.
    """
    tab = _tab()
    tab.apply_config({"truck_mode": modelmod.TRUCK_MODE_UR_AUTO})
    assert not [c for c in tab.web_view()["cards"]
                if c.get("title") == "checklist.group.send_trucks"], \
        "a switched-off group has a card on the phone the window does not draw"

    rows = {r["label"]: r["value"] for r in tab._web_truck_rows()}
    assert rows["checklist.trucks.sent"] == "0 / 5"
    assert rows["checklist.trucks.idle"] == "3"

    items = {i["label"]: i for i in tab._web_truck_items()}
    assert items["checklist.trucks.send"]["pill"] == "checklist.trucks.not_yet"
    assert not items["checklist.trucks.send"].get("actions"), \
        "the phone offers a dispatch the panel cannot do either"
    chosen = [m for m in modelmod.TRUCK_MODES
              if items["checklist.trucks.mode." + m]["pill"] ==
              "checklist.trucks.chosen"]
    assert chosen == [modelmod.TRUCK_MODE_UR_AUTO], chosen


def test_a_game_that_did_not_answer_shows_a_dash_and_not_a_zero():
    tab = _tab("base_ready=0", codename=None)
    rows = {r["label"]: r["value"]
            for c in tab.web_view()["cards"] for r in c.get("rows") or ()}
    assert rows["checklist.codename.attacks"] == "—"
    assert rows["checklist.codename.damage"] == "—"
    assert rows["checklist.web.read"] == "—"
    # …and the hidden group's own counter says the same rather than a zero.
    assert tab._truck_sent() == "—" and tab._truck_idle() == "—"


def test_the_board_hears_a_truck_go_out_rather_than_waiting_for_the_poll():
    _tab_class()                        # SKIP where there is no tkinter, as the rest do
    from panel.tabs.checklist import tab as tabmod

    for pattern in ("train.data", "train.send", "train.batch.send"):
        assert pattern in tabmod.WIRE_PATTERNS, pattern


def test_every_word_the_board_can_say_is_in_every_locale():
    """The item titles are built from the catalogue, so no scanner would see them."""
    shipped = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in Path(i18nmod.LOCALES_DIR).glob("*.json")}
    wanted = [e.title_key for e in modelmod.ERRANDS]
    wanted += [heading for heading, _errands in modelmod.GROUPS]
    wanted += ["checklist.state." + s for s in
               (modelmod.DONE, modelmod.TODO, modelmod.UNKNOWN, modelmod.CLOSED)]
    wanted += ["checklist.trucks." + s for s in
               ("sent", "idle", "send", "not_yet", "mode", "chosen", "unchosen")]
    wanted += ["checklist.trucks.mode." + m for m in modelmod.TRUCK_MODES]
    for lang, table in sorted(shipped.items()):
        missing = [k for k in wanted if k not in table]
        assert not missing, f"{lang}.json does not translate {missing}"


# ---------------------------------------------------------------------------
# the tab, and the phone
# ---------------------------------------------------------------------------
class _Tick:
    def __init__(self) -> None:
        self.armed: dict = {}

    def arm(self, name, ms, fn) -> None:
        self.armed[name] = (ms, fn)

    def disarm(self, name) -> None:
        self.armed.pop(name, None)


class _Runtime:
    """What a press reaches for. No Tk, no game, no claim."""

    def __init__(self, plays=True) -> None:
        self.tick = _Tick()
        self.said: list = []
        self.played: list = []
        self._plays = plays

    def t(self, key, **fmt) -> str:
        return key

    def say(self, tag, key, **fmt) -> None:
        self.said.append(key)

    def play_async(self, name, args=None, **kw) -> bool:
        """Record the scenario, and finish it the way the real runtime does.

        `on_done` is fired because the tab CHAINS on it — the board's refresh plays the
        day's reading and then the event's. A stub that never finished a run would have
        let the second read quietly never happen, which is exactly the bug worth
        catching here. `on_result` is NOT fired: these tests set the readings by hand,
        and a stand-in outcome would overwrite the state under test.
        """
        self.played.append(name)
        if not self._plays:
            return False
        done = kw.get("on_done")
        if done is not None:
            done()
        return True


class _Skip(Exception):
    """This test needs the tab module, and this python has no tkinter."""


def _tab_class():
    try:
        from panel.tabs.checklist.tab import ChecklistTab
    except ImportError as exc:              # no tkinter: the model tests still ran
        raise _Skip(str(exc)) from None
    return ChecklistTab


def _tab_module():
    """The tab MODULE — for the constants the layout is made of."""
    _tab_class()                            # SKIP where there is no tkinter
    from panel.tabs.checklist import tab as tabmod
    return tabmod


class _Var:
    """A Tk variable's two methods, with no Tk under them."""

    def __init__(self, value="") -> None:
        self._value = value

    def get(self):
        return self._value

    def set(self, value) -> None:
        self._value = value


def _tab(raw=FULL, plays=True, codename=CODENAME_SHUT):
    """A tab holding its two readings and nothing else — the path both screens take."""
    cls = _tab_class()
    tab = cls.__new__(cls)
    tab.rt = _Runtime(plays)
    tab._reading = modelmod.parse(raw, at=1.0) if raw is not None else None
    tab._codename = modelmod.parse(codename, at=1.0) if codename is not None else None
    tab._running = set()
    tab._busy = False
    tab._body = None
    tab._status = None
    tab._refresh_button = None
    tab._wire_off = []
    tab._truck_mode = _Var(modelmod.TRUCK_MODE_DEFAULT)
    return tab


def _items(view) -> dict:
    """Every line of a screen, by its title key."""
    out = {}
    for card in view["cards"]:
        for item in card.get("items") or ():
            out[item["label"]] = item
    return out


def test_the_screen_is_keys_and_data_and_every_button_is_answered():
    keyish = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    english = json.loads(
        (Path(i18nmod.LOCALES_DIR) / "en.json").read_text(encoding="utf-8"))
    # The event is RUNNING here, so the screen carries both presses it can ever carry.
    tab = _tab(codename=CODENAME_OPEN)
    view = tab.web_view()

    keys = []
    for card in view["cards"]:
        assert set(card) <= {"title", "head", "rows", "items", "empty", "search",
                             "actions"}
        keys += [k for k in (card.get("title"), card.get("empty")) if k]
        keys += [r["label"] for r in card.get("rows") or ()]
        for item in card.get("items") or ():
            assert set(item) <= {"text", "label", "detail", "note", "pill", "actions",
                                 "facts", "until"}
            assert "text" not in item, \
                "a title of the panel's own must be a key, not data"
            keys += [item["label"], item["pill"]]
            keys += [a["label"] for a in item.get("actions") or ()]
        keys += [a["label"] for a in card.get("actions") or ()]
    keys += [a["label"] for a in view["actions"]]
    for key in keys:
        assert keyish.match(key), f"«{key}» is a sentence, not a locale key"
        assert key in english, f"«{key}» is in no locale"

    offered = {a["id"] for a in view["actions"]}
    for card in view["cards"]:
        offered |= {a["id"] for a in card.get("actions") or ()}
        for item in card.get("items") or ():
            offered |= {a["id"] for a in item.get("actions") or ()}
    assert offered == {"refresh", "run"}, offered
    for action in offered:
        assert _tab().web_press(action, {}).get("error") != "unknown", \
            f"«{action}» is a dead button"
    assert tab.web_press("no-such-action-ever", {}).get("error") == "unknown"


def test_the_phone_sees_the_same_states_as_the_window_and_no_way_to_tick_one():
    """There is no marking anywhere — not in the window, and not from a bus."""
    assert _items(_tab(codename=CODENAME_OPEN).web_view())[
        "checklist.item.codename"]["pill"] == "checklist.state.todo"
    assert _items(_tab(codename=CODENAME_SHUT).web_view())[
        "checklist.item.codename"]["pill"] == "checklist.state.not_running"
    assert _items(_tab(codename=None).web_view())[
        "checklist.item.codename"]["pill"] == "checklist.state.unknown"

    tab = _tab("base_ready=0 wounded=2 ghost_open=0 donate_left=-")
    items = _items(tab.web_view())
    # …and a group that is switched off is on neither front-end (#1275), whatever the
    # game answered about its lines.
    for hidden in ("base_resources", "hospital_heal", "ghost_steals",
                   "alliance_donate", "arena"):
        assert "checklist.item." + hidden not in items, hidden

    before = [s.state for s in tab.states()]
    # Nothing on this screen MARKS. `run` is not in this list: it plays an ability and
    # then re-reads, which is the opposite of recording an opinion (its own test above).
    for marking in ("toggle", "tick", "done", "mark", "reset", "add", "delete"):
        assert tab.web_press(marking, {"key": "base_resources"}) == {"error": "unknown"}
    assert [s.state for s in tab.states()] == before
    assert tab.rt.played == [], "a press reached the game"


def test_the_phone_is_offered_exactly_the_presses_the_window_draws():
    """One mechanism, two front-ends, the same gate — never one ahead of the other."""
    for codename in (CODENAME_SHUT, CODENAME_OPEN):
        tab = _tab(codename=codename)
        offered = {i["label"]: i["actions"][0] for c in tab.web_view()["cards"]
                   for i in c.get("items") or () if i.get("actions")}
        drawn = {s.errand.title_key: s for s in tab.states()
                 if s.errand.runnable and tab._may_run(s)}
        assert set(offered) == set(drawn), (
            "the phone and the window disagree about which rows can be pressed: "
            f"{sorted(set(offered) ^ set(drawn))}")
        for key, action in offered.items():
            assert action["id"] == "run"
            assert action["label"] == drawn[key].errand.run_key
            assert action["args"]["key"] == drawn[key].key


def test_pressing_plays_the_scenario_and_re_reads_and_marks_nothing():
    """The whole rule in one path: a press starts an ability; a READING moves the row."""
    tab = _tab(codename=CODENAME_OPEN)
    before = [s.state for s in tab.states()]
    assert tab.run("codename") is True
    # …the ability, then the reading the board is drawn from — and nothing else.
    assert tab.rt.played == [modelmod.CODENAME_ATTACK, modelmod.CODENAME_ACTION]
    # The row did not move: the stub answers no reading, so the board is what it was.
    assert [s.state for s in tab.states()] == before

    # A line with no ability cannot be pressed, from either front-end.
    for silent in ("trucks", "queues_help", "secret_steals", "ghost_steals", "arena"):
        blank = _tab()
        assert blank.run(silent) is False
        assert blank.rt.played == [], f"«{silent}» reached the game"
    assert _tab().run("no-such-errand") is False


def test_a_scenario_in_flight_cannot_be_started_twice():
    """Two presses on one row is one run — and the button says so by going dead."""
    class _Slow(_Runtime):
        def play_async(self, name, args=None, **kw):
            self.played.append(name)
            return True                     # never finishes: on_done is not called

    tab = _tab(codename=CODENAME_OPEN)
    tab.rt = _Slow(True)
    assert tab.run("codename") is True
    assert tab.run("codename") is False, "a second press started the same run again"
    assert tab.rt.played == [modelmod.CODENAME_ATTACK]
    state = {s.key: s for s in tab.states()}["codename"]
    assert not tab._may_run(state), "the row stayed pressable while its run was going"
    assert not [i for c in tab.web_view()["cards"] for i in c.get("items") or ()
                if i["label"] == "checklist.item.codename" and i.get("actions")], \
        "the phone still offered a run that is already going"


def test_the_board_wide_press_is_read_it_again_and_nothing_else():
    tab = _tab()
    assert [a["id"] for a in tab.web_view()["actions"]] == ["refresh"]
    assert tab.web_press("refresh", {}) == {"ok": True}
    # One reading, because one group is drawn. The day's comes back with its groups.
    assert tab.rt.played == [modelmod.CODENAME_ACTION]


def test_the_codename_press_is_offered_only_while_the_event_is_running():
    """Greyed when the game has SAID there is no boss — and on both front-ends alike."""
    shut = _tab(codename=CODENAME_SHUT)
    state = {s.key: s for s in shut.states()}["codename"]
    assert state.state == modelmod.CLOSED
    assert not shut._may_run(state)
    assert shut.run("codename") is True, \
        "run() is the mechanism, not the gate — the widget is what greys"
    # …and the phone is not offered it, which is the gate that matters from outside.
    assert not [i for c in _tab(codename=CODENAME_SHUT).web_view()["cards"]
                for i in c.get("items") or ()
                if i["label"] == "checklist.item.codename" and i.get("actions")]

    live = _tab(codename=CODENAME_OPEN)
    assert live.web_press("run", {"key": "codename"}) == {"ok": True}
    assert live.rt.played[0] == modelmod.CODENAME_ATTACK

    # A reading that never arrived is not «running», but it is not «shut» either: the
    # row is UNKNOWN, the press stays available, and the SCENARIO refuses if it must.
    for blind in (None, modelmod.Reading(error="no daemon")):
        tab = _tab()
        tab._codename = blind
        state = {s.key: s for s in tab.states()}["codename"]
        assert state.state == modelmod.UNKNOWN
        assert tab._may_run(state), "unknown was treated as «you may not»"


def test_the_codename_block_is_the_events_own_numbers_and_stays_when_it_is_shut():
    """Grey, never hidden — and «сделано из трёх» rather than «осталось из пяти»."""
    live = modelmod.parse(CODENAME_OPEN)
    assert modelmod.codename_counter(live) == (1, 3, 12607399171)
    assert modelmod.state_of(modelmod.BY_KEY["codename"], live).state == modelmod.TODO

    shut = modelmod.parse(CODENAME_SHUT)
    assert modelmod.state_of(modelmod.BY_KEY["codename"], shut).state == \
        modelmod.CLOSED, "an event that is not on must not read as undone"

    done = modelmod.parse("open=1 attacks=3 need=3 left=0 maxdmg=5 targets=1 until=60")
    assert modelmod.state_of(modelmod.BY_KEY["codename"], done).state == modelmod.DONE
    assert modelmod.codename_counter(done) == (3, 3, 5)

    for blind in (None, modelmod.Reading(error="no daemon"),
                  modelmod.parse("open=- attacks=- need=- left=- maxdmg=-")):
        assert modelmod.state_of(modelmod.BY_KEY["codename"], blind).state == \
            modelmod.UNKNOWN
        assert modelmod.codename_counter(blind)[0] is None

    assert modelmod.damage(12607399171) == "12 607 399 171"
    assert modelmod.damage(None) == "—"

    # The block is on the board whatever the event is doing — never dropped from it.
    for reading in (live, shut, None):
        keys = [g.key for g, _ in modelmod.grouped(modelmod.parse(FULL), reading)]
        assert modelmod.CODENAME in keys


def test_the_board_refreshes_itself_and_says_so_when_it_cannot():
    tab = _tab()
    assert tab.refresh() is True
    assert tab.rt.played == [modelmod.CODENAME_ACTION]
    # …and a game that is busy leaves the previous readings alone rather than clearing
    # them: something else holding the claim is not the game saying the board is empty.
    busy = _tab(plays=False)
    assert busy.refresh() is False
    assert busy.rt.played == [modelmod.CODENAME_ACTION]
    assert busy._reading.get("base_ready") == 4
    assert busy._codename.get("attacks") == 0 and not busy._codename.error
    assert busy._busy is False, "a refused read left the tab thinking it is reading"


def test_a_read_that_failed_is_recorded_as_a_failure_not_as_an_empty_day():
    class _Outcome:
        def __init__(self, ok, raw=None, reason=""):
            self.ok, self.reason = ok, reason
            self.ctx = type("C", (), {"vars": {modelmod.VARIABLE: raw}})()

    tab = _tab(codename=None)
    tab._read_back(_Outcome(False, reason="no daemon"))
    assert tab._reading.error == "no daemon"
    assert all(s.state == modelmod.UNKNOWN for s in tab.states())

    tab._read_back(_Outcome(True, raw=FULL))
    assert tab._reading.get("steal_left") == 2
    assert not tab._reading.error


def test_one_reading_failing_says_nothing_about_the_other():
    """Two scenarios reach this board, and a failure of one is not a failure of both.

    The day's reading going dark must not blank «Кодовое имя», and the event's going
    dark must not blank the day. Each line is answered by its own source or by nothing.
    """
    tab = _tab(raw=None, codename=CODENAME_OPEN)
    tab._reading = modelmod.Reading(error="no daemon", at=1.0)
    assert {s.key: s.state for s in tab.states()}["codename"] == modelmod.TODO, \
        "the event went dark with the day"

    tab = _tab(raw=FULL)
    tab._codename = modelmod.Reading(error="no daemon", at=1.0)
    assert {s.key: s.state for s in tab.states()}["codename"] == modelmod.UNKNOWN
    # …and the day's own lines still read off the day's answer, for the groups that are
    # switched off now and for the moment one of them is switched back on.
    assert modelmod.state_of(modelmod.BY_KEY["base_resources"],
                             tab._reading).state == modelmod.TODO
    assert modelmod.state_of(modelmod.BY_KEY["base_resources"],
                             tab._codename).state == modelmod.UNKNOWN


def test_the_tab_is_registered_and_says_who_it_is():
    from panel import tabs as tabsreg

    spec = tabsreg.BY_ID.get("checklist")
    assert spec is not None, "the tab is not in the registry"
    cls = _tab_class()
    assert cls.TITLE_KEY == spec.title_key == "tab.checklist"
    assert cls.WEB_SCREEN is True
    assert cls.AGGREGATES_TABS == spec.aggregates is False
    assert not cls.EAGER, "a board nobody has opened must not read the game at boot"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except _Skip as exc:
            print(f"  SKIP {test.__name__}: {exc}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:                    # noqa: BLE001
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed or skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
