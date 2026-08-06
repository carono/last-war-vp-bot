r"""The «Чеклист» tab: a board that is READ, and the one lie it must never tell.

The rule this file exists to hold is that a line is done because the GAME says there is
nothing left of it — never because somebody ticked a box, and never because a scenario
was started. So the tests are mostly about the third state: a reading that did not
arrive, a field the client would not answer, an event that is not on today. Each of
those has to come out as «unknown» or «not on today» and NOT as done, because a
checklist that quietly reports a dark client as a finished day is worse than no
checklist at all.

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
    reading = modelmod.parse("base_ready=0 wounded=2 ghost_open=0 donate_left=-")
    done, total = modelmod.progress(modelmod.states(reading))
    assert (done, total) == (1, 2), "an unknown or a closed line was counted"


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


def test_no_errand_carries_a_press_of_any_kind():
    """An errand is a READING. There is nothing on it for a button to hang off.

    The catalogue used to carry a scenario per line and the rows a «Выполнить» — and a
    button that starts something is a button somebody expects to have ticked the line.
    The abilities live on their own tabs; this one only says whether they still need to
    run.
    """
    for errand in modelmod.ERRANDS:
        assert not hasattr(errand, "scenario"), \
            f"«{errand.key}» carries a scenario — the board is a reading, not a remote"
    assert "scenario" not in modelmod.Errand.__slots__


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
    # counted total is exactly the read half — however long the blind half grows.
    done, total = modelmod.progress(modelmod.states(modelmod.parse(FULL),
                                                    modelmod.parse(CODENAME_OPEN)))
    readable = [e for e in modelmod.ERRANDS if e.readable]
    assert total == len(readable), \
        f"{len(modelmod.ERRANDS) - total} lines counted that nobody can read"


# ---------------------------------------------------------------------------
# «Отправка грузовиков» — the first group that is more than a list
# ---------------------------------------------------------------------------
def test_the_trucks_are_the_first_group_and_carry_their_own_line():
    first = modelmod.GROUPS[0]
    assert first.key == modelmod.TRUCKS
    assert first.title_key == "checklist.group.send_trucks"
    assert [e.key for e in first.errands] == ["send_trucks"]
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
    tab = _tab()
    tab.apply_config({"truck_mode": modelmod.TRUCK_MODE_UR_AUTO})
    card = [c for c in tab.web_view()["cards"]
            if c.get("title") == "checklist.group.send_trucks"]
    assert len(card) == 1, "the trucks have no card of their own on the phone"
    rows = {r["label"]: r["value"] for r in card[0]["rows"]}
    assert rows["checklist.trucks.sent"] == "0 / 5"
    assert rows["checklist.trucks.idle"] == "3"

    items = {i["label"]: i for i in card[0]["items"]}
    assert items["checklist.trucks.send"]["pill"] == "checklist.trucks.not_yet"
    assert not items["checklist.trucks.send"].get("actions"), \
        "the phone offers a dispatch the panel cannot do either"
    chosen = [m for m in modelmod.TRUCK_MODES
              if items["checklist.trucks.mode." + m]["pill"] ==
              "checklist.trucks.chosen"]
    assert chosen == [modelmod.TRUCK_MODE_UR_AUTO], chosen


def test_a_game_that_did_not_answer_shows_a_dash_and_not_a_zero():
    tab = _tab("base_ready=0")
    rows = {r["label"]: r["value"]
            for c in tab.web_view()["cards"] for r in c.get("rows") or ()}
    assert rows["checklist.trucks.sent"] == "—"
    assert rows["checklist.trucks.idle"] == "—"


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
    tab._busy = False
    tab._attacking = False
    tab._body = None
    tab._status = None
    tab._refresh_button = None
    tab._codename_button = None
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
    tab = _tab()
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
        keys += [a["label"] for a in card.get("actions") or ()]
    keys += [a["label"] for a in view["actions"]]
    for key in keys:
        assert keyish.match(key), f"«{key}» is a sentence, not a locale key"
        assert key in english, f"«{key}» is in no locale"

    offered = {a["id"] for a in view["actions"]}
    for card in view["cards"]:
        offered |= {a["id"] for a in card.get("actions") or ()}
    for action in offered:
        assert _tab().web_press(action, {}).get("error") != "unknown", \
            f"«{action}» is a dead button"
    assert tab.web_press("no-such-action-ever", {}).get("error") == "unknown"

    # …and the same again with «Кодовое имя» running, because that is when its card
    # grows the one button on this board.
    live = _tab(codename=CODENAME_OPEN)
    ids = {a["id"] for c in live.web_view()["cards"] for a in c.get("actions") or ()}
    assert ids == {"attack_codename"}, ids
    for action in ids:
        assert _tab(codename=CODENAME_OPEN).web_press(action, {}).get("error") is None, \
            f"«{action}» is a dead button"


def test_the_phone_sees_the_same_states_as_the_window_and_no_way_to_tick_one():
    """There is no marking anywhere — not in the window, and not from a bus."""
    tab = _tab("base_ready=0 wounded=2 ghost_open=0 donate_left=-")
    items = _items(tab.web_view())
    assert items["checklist.item.base_resources"]["pill"] == "checklist.state.done"
    assert items["checklist.item.hospital_heal"]["pill"] == "checklist.state.todo"
    assert items["checklist.item.ghost_steals"]["pill"] == "checklist.state.closed"
    assert items["checklist.item.alliance_donate"]["pill"] == "checklist.state.unknown"
    assert items["checklist.item.arena"]["pill"] == "checklist.state.unknown"

    before = [s.state for s in tab.states()]
    for marking in ("toggle", "tick", "done", "mark", "reset", "add", "delete", "run"):
        assert tab.web_press(marking, {"key": "base_resources"}) == {"error": "unknown"}
    assert [s.state for s in tab.states()] == before
    assert tab.rt.played == [], "a press reached the game"


def test_no_row_offers_a_press_on_either_front_end():
    """A ROW is a reading and carries nothing to press. A group may (below)."""
    for codename in (CODENAME_SHUT, CODENAME_OPEN):
        tab = _tab(codename=codename)
        for card in tab.web_view()["cards"]:
            for item in card.get("items") or ():
                assert not item.get("actions"), \
                    f"«{item['label']}» offers a button — a row is a reading"


def test_the_board_wide_press_is_read_it_again_and_nothing_else():
    tab = _tab()
    assert [a["id"] for a in tab.web_view()["actions"]] == ["refresh"]
    assert tab.web_press("refresh", {}) == {"ok": True}
    assert tab.rt.played == [modelmod.ACTION, modelmod.CODENAME_ACTION]


def test_the_codename_press_is_offered_only_while_the_event_is_running():
    """The one button on the board, on both front-ends, and greyed the same way.

    It exists because it was asked for, and it does not tick anything: the row above it
    is still the game's own count, re-read after the attack. What kills it is the event
    being shut — then there is no boss on the map for a press to reach.
    """
    shut = _tab(codename=CODENAME_SHUT)
    assert not [a for c in shut.web_view()["cards"] for a in c.get("actions") or ()]
    assert shut.web_press("attack_codename", {}) == {"error": "closed"}
    assert shut.rt.played == [], "a press reached the game with the event shut"

    live = _tab(codename=CODENAME_OPEN)
    assert live.web_press("attack_codename", {}) == {"ok": True}
    assert live.rt.played == [modelmod.CODENAME_ATTACK]

    # A reading that never arrived is not «running»: unknown must never open a press.
    for blind in (None, modelmod.Reading(error="no daemon")):
        tab = _tab()
        tab._codename = blind
        assert tab.web_press("attack_codename", {}) == {"error": "closed"}
        assert tab.rt.played == []


def test_a_shut_gate_is_worded_by_the_errand_and_the_same_on_both_front_ends():
    """«Сегодня не проводится» is true of Ghost Ops and false of a four-a-day boss.

    So the wording is the errand's, and both registers are built from the one token —
    the window says `checklist.detail.<closed>` and the phone `checklist.state.<closed>`,
    which is what stops the two drifting into saying different things about one row.
    """
    english = json.loads(
        (Path(i18nmod.LOCALES_DIR) / "en.json").read_text(encoding="utf-8"))
    tokens = {e.closed for e in modelmod.ERRANDS}
    assert tokens == {"closed", "not_running"}, tokens
    for token in tokens:
        for family in ("checklist.detail.", "checklist.state."):
            assert family + token in english, f"«{family}{token}» is in no locale"

    assert modelmod.BY_KEY["ghost_steals"].closed == "closed"
    assert modelmod.BY_KEY["codename"].closed == "not_running"

    tab = _tab("ghost_open=0", codename=CODENAME_SHUT)
    pills = {i["label"]: i["pill"] for c in tab.web_view()["cards"]
             for i in c.get("items") or ()}
    assert pills["checklist.item.ghost_steals"] == "checklist.state.closed"
    assert pills["checklist.item.codename"] == "checklist.state.not_running"


def test_the_codename_counter_survives_the_event_being_shut():
    """«0 / 3» greyed, not «—»: the numbers are the last that were true.

    The row is CLOSED and rightly so, but dashing the count while printing the damage
    beside it would say the panel had lost track of one and not the other.
    """
    shut = modelmod.parse(CODENAME_SHUT)
    assert modelmod.state_of(modelmod.BY_KEY["codename"], shut).state == modelmod.CLOSED
    assert modelmod.codename_counter(shut) == (0, 3, 12607399171)


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
    assert tab.rt.played == [modelmod.ACTION, modelmod.CODENAME_ACTION]
    # …and a game that is busy leaves the previous reading alone rather than clearing it.
    busy = _tab(plays=False)
    assert busy.refresh() is False
    assert busy.rt.played == [modelmod.ACTION], "the second read went out anyway"
    assert busy._reading.get("base_ready") == 4
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
    states = {s.key: s.state for s in tab.states()}
    assert states["base_resources"] == modelmod.UNKNOWN
    assert states["codename"] == modelmod.TODO, "the event went dark with the day"

    tab = _tab(raw=FULL)
    tab._codename = modelmod.Reading(error="no daemon", at=1.0)
    states = {s.key: s.state for s in tab.states()}
    assert states["base_resources"] == modelmod.TODO
    assert states["codename"] == modelmod.UNKNOWN
    assert not tab._codename_open(), "a dark event reading opened the press"


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
