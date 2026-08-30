r"""The «События» tab: a board of the game's events, read rather than remembered.

The rules this file exists to hold are the three the tab was written for:

* an event's state is the GAME's answer — the panel keeps no count of its own, so an
  attack sent from the phone or by the person playing on the screen in front of them
  counts exactly as much as one this panel sent;
* an event that is not running is drawn GREY and never hidden, because a block that
  disappears is indistinguishable from a block nobody has written yet;
* «nobody knows» is not «not running». A reading that never arrived must never come out
  as closed, and it must never open the press.

The other half pins the reading to the press it describes: every expression in
`actions/read_codename_event.md` is the one `tools/lib/lua_actions.py` gates the attack
on, and the two tabs that draw the event name the same two scenarios.

No display and no widget: the catalogue and the parser are Tk-free, and the screen tests
reach the tab class without building one. The tab MODULE still imports tkinter, which the
WSL python does not ship — those tests say SKIP there and run under the Windows one:

    C:\Python312\python.exe tests\test_panel_events.py
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

import lua_actions                                    # noqa: E402
from panel import i18n as i18nmod                     # noqa: E402
from panel.tabs.events import model as modelmod       # noqa: E402
from panel.runtime import squad_picker                # noqa: E402

ACTIONS = _REPO / "src" / "lastwar_bot" / "actions"
READ = ACTIONS / "read_codename_event.md"
ATTACK = ACTIONS / "attack_codename_boss.md"
DAILY = ACTIONS / "attack_codename_daily.md"

#: The reading as the live client answers it while «Кодовое имя» is running…
OPEN = "open=1 attacks=1 need=3 left=2 maxdmg=12607399171 targets=1 until=6042"
#: …and while it is not, which is what the live client answered when this was written.
SHUT = "open=0 attacks=0 need=3 left=3 maxdmg=12607399171 targets=0 until=-"


# ---------------------------------------------------------------------------
# the reading
# ---------------------------------------------------------------------------
def test_the_line_the_game_sends_back_is_read_as_numbers():
    reading = modelmod.parse(OPEN, at=100.0)
    assert reading
    assert reading.get("attacks") == 1
    assert reading.get("maxdmg") == 12607399171
    assert reading.at == 100.0


def test_a_field_the_game_would_not_answer_is_not_a_zero():
    reading = modelmod.parse("open=1 attacks=- need=3")
    assert reading.get("attacks") is None
    assert reading.get("need") == 3


def test_a_reading_that_never_arrived_is_unknown_and_never_closed():
    """The one confusion that would matter: a dark client reading as «not on today»."""
    for blind in (None, modelmod.Reading(error="no daemon"),
                  modelmod.parse("open=- attacks=- need=-")):
        state = modelmod.codename_state(blind)
        assert state.state == modelmod.UNKNOWN
        assert not state.open
        assert not state.done, "unknown was counted as finished"
        # …and it does NOT shut the press. «Nobody knows» is not «you may not»: the
        # scenario holds that gate and refuses in one line, and «Чеклист» draws its
        # nine buttons by the same rule, so the two boards agree.
        assert state.can_attack, "unknown was treated as «the event is shut»"


def test_an_event_that_is_not_running_is_closed_and_its_press_is_shut():
    """CLOSED is the ONE thing that greys the button: the game said there is no boss."""
    state = modelmod.codename_state(modelmod.parse(SHUT))
    assert state.state == modelmod.CLOSED
    assert not state.can_attack
    # …and its numbers are still there to be drawn grey rather than dropped.
    assert state.need == 3 and state.damage == 12607399171


def test_a_running_event_carries_its_counts_and_opens_the_press():
    state = modelmod.codename_state(modelmod.parse(OPEN))
    assert state.state == modelmod.OPEN
    assert state.can_attack
    assert (state.attacks, state.need, state.left) == (1, 3, 2)
    assert not state.done
    assert modelmod.counter(state) == "1 / 3"
    assert modelmod.hhmm(state.seconds) == "1:40"


def test_the_press_stays_alive_after_the_three_are_in():
    """Attempts are NOT rationed — a fourth hit is worth making for the ranking."""
    state = modelmod.codename_state(
        modelmod.parse("open=1 attacks=5 need=3 left=0 maxdmg=7 targets=1 until=60"))
    assert state.done
    assert state.can_attack, "the button died on a quota the game does not have"


def test_the_damage_keeps_its_digits():
    assert modelmod.damage(12607399171) == "12 607 399 171"
    assert modelmod.damage(0) == "0"
    for junk in (None, "", "many"):
        assert modelmod.damage(junk) == "—"


def test_the_counter_says_nothing_rather_than_a_zero_it_does_not_know():
    state = modelmod.codename_state(modelmod.parse("open=1 attacks=- need=-"))
    assert modelmod.counter(state) == "—"
    assert modelmod.hhmm(None) == "—"


# ---------------------------------------------------------------------------
# the scenarios behind it
# ---------------------------------------------------------------------------
def test_the_reading_asks_the_server_before_it_believes_the_answer():
    """#1259: the manager answers «shut» to a client that never asked it.

    `IsBossAvailable()` reads a stage list that only arrives in the reply to
    `user.get.act.boss.march`, so a reading that skips the ask reports a running event
    as shut every single day — which is what it did, and what greyed the whole feature
    out. The ask has to come FIRST and the answer has to be waited for.
    """
    body = [line for line in READ.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    assert body[0] == "TAP codename_fetch", body[0]
    waits = [i for i, line in enumerate(body) if line.startswith("WHILE cn_loaded")]
    answer = [i for i, line in enumerate(body)
              if line.startswith("READ_LUA ") and "INTO %s" % modelmod.CODENAME_VARIABLE in line]
    assert waits and answer, body
    assert waits[0] < answer[0], "the reading answers before the reply has landed"
    # The wait is BOUNDED: on the one day the event does not run there is no stage to
    # send, and an unbounded wait would hang the poll for ever.
    assert "LIMIT" in body[waits[0]], body[waits[0]]


def test_the_reading_changes_nothing_it_only_asks():
    """It runs on a poll, so the one message it sends must be a GET."""
    body = [line for line in READ.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    for line in body:
        for forbidden in ("OnClickStartMarch", "SendLuaMessage", "SendCreateMarchMessage"):
            assert forbidden not in line, f"the reading contains «{forbidden}»"
    for line in body:
        if line.startswith("TAP "):
            assert line == "TAP codename_fetch", f"the reading presses «{line}»"
    assert "SendMessage(MsgDefines.UserGetActBossMarch)" in lua_actions.codename_fetch()


def test_the_reading_is_the_same_expressions_the_press_is_gated_on():
    """One copy of each, so the board and the button can never disagree."""
    text = READ.read_text(encoding="utf-8")
    for name in ("codename_open", "codename_attacks_made", "codename_attacks_needed",
                 "codename_max_damage", "codename_targets", "codename_seconds_left"):
        assert getattr(lua_actions, name)() in text, (
            f"{name}() is no longer what read_codename_event.md reads — "
            f"the board and the press would disagree")


def test_the_reading_answers_every_field_the_tab_draws():
    text = READ.read_text(encoding="utf-8")
    for field in ("open", "attacks", "need", "left", "maxdmg", "targets", "until"):
        assert ("put('%s'" % field) in text, f"the reading does not answer «{field}»"


def test_the_attack_is_a_scenario_and_the_panel_only_plays_it():
    """`CLAUDE.md`: the ability is one file, and the tab runs it by name."""
    assert ATTACK.exists()
    text = ATTACK.read_text(encoding="utf-8")
    # It ASKS before it believes the gate — the manager is empty until it does (#1259).
    assert text.index("TAP codename_fetch") < text.index(lua_actions.codename_open())
    # It gates on the event being open before anything is armed or sent.
    gate = text.index(lua_actions.codename_open())
    for press in ("TAP codename_arm", "TAP codename_send"):
        assert press in text
        assert text.index(press) > gate, f"«{press}» comes before the open gate"
    # …and it opens NOTHING. A person walks five screens; the send needs none of them,
    # and a recipe that flew the camera would need a tile the client may never stream in.
    for gone in ("codename_select", "codename_attack", "codename_squad", "codename_launch",
                 "OnClickWorldPoint", "UIWorldPoint", "UIFormationSelectList"):
        assert gone not in text, f"the attack still walks the UI: «{gone}»"


def test_the_attack_proves_itself_by_ASKING_not_by_waiting():
    """#1259: the count is the server's, and nothing pushes it to the client.

    The first run of this recipe reported «the count did not move» over an attack that
    had gone out and was visible in the game — it polled a number that only changes when
    the client asks. So every turn of the proof loop asks again.
    """
    text = ATTACK.read_text(encoding="utf-8")
    body = [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    loop = [i for i, line in enumerate(body) if line.startswith("WHILE sent < 1")]
    assert loop, body
    inside = body[loop[0] + 1:loop[0] + 3]
    assert "TAP codename_fetch" in inside, inside
    # …and it proves the attack by the SERVER's count rather than by a clean press.
    assert lua_actions.codename_sent() in text


def test_the_presses_the_attack_names_are_buttons_that_exist():
    import game_buttons

    text = ATTACK.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("TAP "):
            continue
        name = line.split()[1]
        assert game_buttons.get(name) is not None, f"«{name}» is not a button"


# ---------------------------------------------------------------------------
# the day's worth of it — the errand a clock plays once a day
# ---------------------------------------------------------------------------
def test_the_daily_errand_is_a_scenario_that_only_calls_the_single_attack():
    """`CLAUDE.md`: the ability is one file, and it is built out of the one beside it.

    The day's run is not a second implementation of an attack — every march it sends is
    `CALL attack_codename_boss`, so the boss, the squad and the proof that the server's
    count moved have exactly one definition. A copy here would be the version that goes
    stale the first time the send changes.
    """
    assert DAILY.exists()
    text = DAILY.read_text(encoding="utf-8")
    body = [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    assert "CALL attack_codename_boss" in body
    for pressed in ("TAP codename_arm", "TAP codename_send"):
        assert pressed not in body, f"the day's run sends for itself: «{pressed}»"


def test_the_daily_errand_asks_the_server_how_many_are_owed():
    """HOW MANY is the game's answer. A three written down here would be the bug.

    An attack made by hand, or from the phone, counts as much as one this panel sent —
    the count is the SERVER's — so the run has to ask before it sends and after each
    send, and stop when the answer says nothing is owed.
    """
    text = DAILY.read_text(encoding="utf-8")
    body = [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    assert body[0] == "TAP codename_fetch", body[0]
    # The same arithmetic the board draws and the clock loops on — one copy, in
    # `lua_actions`, so a panel saying «one left» and a run believing «three» cannot
    # happen.
    assert lua_actions.codename_attacks_left() in text
    assert lua_actions.codename_attacks_left() in READ.read_text(encoding="utf-8")
    # …and the loop is bounded, on the count and on the number of turns.
    loop = [line for line in body if line.startswith("WHILE cn_left")]
    assert loop and "LIMIT" in loop[0], body


def test_a_day_with_nothing_owed_is_a_SUCCESS_and_a_day_half_done_is_not():
    """The two endings a clock reads differently.

    Sunday — the one day «Кодовое имя» does not run — and a day whose attacks are
    already made both STOP: a failure would sit out the retry hold and try again every
    retry period until midnight, for a state that cannot change. A day that still owes
    attacks and could not send one FAILS, so the clock keeps its place and comes back
    for what is still owed instead of writing the day off as done.
    """
    text = DAILY.read_text(encoding="utf-8")
    body = [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    assert sum(1 for line in body if line.startswith("STOP")) == 2, body
    shut = [i for i, line in enumerate(body) if line.startswith("IF cn_open")]
    assert shut and any(body[i].startswith("STOP")
                        for i in range(shut[0], min(shut[0] + 4, len(body))))
    assert any(line.startswith("FAIL") for line in body), body


def test_the_day_is_a_timer_of_a_day_and_the_row_has_a_name():
    """It is in the catalogue as a DAILY errand, off until the operator says otherwise."""
    import json

    from panel import timers as timersmod

    entry = next(t for t in timersmod.DEFAULT_TIMERS
                 if t.name == "attack_codename_daily")
    assert entry.scenario == ("attack_codename_daily",)
    assert entry.interval_sec == 24 * 3600
    assert not entry.enabled, "an errand that marches must not ship switched on"
    # A retry well short of the period: a run fails because a squad is out, and a squad
    # comes home in minutes. Waiting a day would lose the day.
    assert 0 < entry.retry_sec < entry.interval_sec / 10
    assert entry.label_key == "timers.item.attack_codename_daily"
    english = json.loads(
        (Path(i18nmod.LOCALES_DIR) / "en.json").read_text(encoding="utf-8"))
    assert entry.label_key in english
    # The built-in list is the only copy that ships: `profiles/` is the machine's own
    # tree and is not in the repository, so an errand that lived only in the local
    # template would exist on the machine that wrote it and nowhere else. Being here is
    # what makes an already-configured profile adopt it, switched off
    # (`timers.adopt_new_errands`).
    assert timersmod.DEFAULT_TIMERS.index(entry) >= 0


def test_both_tabs_name_the_same_two_scenarios():
    """«Чеклист» draws this event too, and repeats the names rather than importing."""
    from panel.tabs.checklist import model as checklist

    assert checklist.CODENAME_ACTION == modelmod.CODENAME_ACTION
    assert checklist.CODENAME_VARIABLE == modelmod.CODENAME_VARIABLE
    assert checklist.CODENAME_ATTACK == modelmod.CODENAME_ATTACK
    for action in (modelmod.CODENAME_ACTION, modelmod.CODENAME_ATTACK):
        assert (ACTIONS / (action + ".md")).exists()


# ---------------------------------------------------------------------------
# the tab and its phone screen
# ---------------------------------------------------------------------------
class _Skip(Exception):
    """This test needs the tab module, and this python has no tkinter."""


#: A golden-zombie reading with energy to spend, and one without.
GOLDEN_OPEN = "energy=55 cost=10 attacks=5 seen=135 atk=765 col=1930 ratio=252"
GOLDEN_SPENT = "energy=3 cost=10 attacks=0 seen=0"

#: An alliance train with a conductor at the platform and a seat still to be taken, and
#: the same station with no train standing at it.
TRAIN_OPEN = ("open=1 state=2 queued=0 carriage=-1 waiting=57 cars=4 seats=7 "
              "departs=8094 thanked=0 contracts=92")
TRAIN_SHUT = ("open=0 state=0 queued=0 carriage=-1 waiting=0 cars=0 seats=0 "
              "departs=- thanked=- contracts=0")


#: One arms reading of the shape `actions/read_arms_race.md` sends back: a hero phase
#: running, 800 points of the 12 000 the top chest wants, no chest taken yet. Invented,
#: like every fixture here — the shape is what the parser is being asked about, and the
#: digits of a real account have no business in a public repository (`CLAUDE.md`).
ARMS_HERO_PHASE = ("open=1 aid=29 day=7 stage=1 event=120000 name=2000601 sc=800 "
                   "rules=122,121,103 t1=2000 t2=4000 t3=12000 g1=0 g2=0 g3=0 "
                   "until=8134 done=1 d1=1 d2=0 d3=0")
#: …and the same day's six borders, the thing no client volunteers.
ARMS_DAY = ("0:120004:1788055200:1788069600 1:120000:1788069600:1788084000 "
            "2:120001:1788084000:1788098400 3:120002:1788098400:1788112800 "
            "4:120003:1788112800:1788127200 5:120004:1788127200:1788141600")


def _tab_class():
    try:
        from panel.tabs.events.tab import EventsTab
    except ImportError as exc:              # no tkinter: the model tests still ran
        raise _Skip(str(exc)) from None
    return EventsTab


class _Runtime:
    """Just enough runtime for the two paths a screen takes."""

    def __init__(self, plays=True) -> None:
        self.plays = plays
        self.played: list = []
        #: …and what each was played WITH: «which squad went» is a question the golden
        #: presses have to answer (#1702).
        self.args: list = []
        #: The golden-zombie tally lives in `panel.db`; nothing here needs one, and a
        #: `None` store is what `panel/golden_zombies.py` reads as «no history yet».
        self.store = None
        self.settings = _Runtime._Settings()

    def play_async(self, name, *a, **kw) -> bool:
        if not self.plays:
            return False
        self.played.append(name)
        self.args.append(a[0] if a and isinstance(a[0], dict) else {})
        return True

    def t(self, key, **fmt):
        return key

    def say(self, tag, key, **fmt) -> None:
        pass

    #: A profile's settings, only ever asked to write themselves down here. A knob moved
    #: on a tab with no profile behind it must still answer the press.
    class _Settings:
        def __init__(self) -> None:
            self.saves = 0

        def changed(self) -> None:
            self.saves += 1

    def dbg(self, tag):
        """A logger that swallows. A knob saved on a tab with no profile behind it
        warns rather than raises, and the warning has to have somewhere to go."""
        import logging
        return logging.getLogger("test.events." + tag)


def _tab(raw=SHUT, plays=True, golden=GOLDEN_OPEN, train=TRAIN_OPEN,
         arms=ARMS_HERO_PHASE, arms_day=ARMS_DAY):
    cls = _tab_class()
    tab = cls.__new__(cls)
    tab.rt = _Runtime(plays)
    tab._reading = modelmod.parse(raw, at=1.0) if raw is not None else None
    tab._busy = False
    tab._attacking = False
    tab._body = None
    tab._status = None
    tab._attack_button = None
    tab._daily_button = None
    tab._sent_key = None
    # «Под руинами» — no reading of its own; the card carries the last line a run said.
    tab._ruins_said = ""
    tab._ruins_running = False
    # «Золотые зомби» — its own reading, its own press, its own day.
    tab._golden = modelmod.parse(golden, at=1.0) if golden is not None else None
    tab._golden_busy = False
    tab._golden_running = False
    tab._golden_button = None
    tab._golden_target = ""          # what «найти ближайшего» last chose (#1702)
    tab._target_var = None           # the label that shows it beside the buttons
    tab._step_said = ""              # what the last step press answered (#1702)
    tab._step_var = None
    tab._step_ran = ""
    tab._waiting = {}
    tab._squad = modelmod.GOLDEN_SQUAD_DEFAULT
    tab._squad_var = None
    tab._tally = {}
    tab._chain_golden = False
    tab._approach = False
    tab._approach_var = None
    # «Поезд Альянса» — its own reading and its two standing-order knobs.
    tab._train = modelmod.parse(train, at=1.0) if train is not None else None
    tab._train_busy = False
    tab._train_boarding = False
    tab._chain_train = False
    tab._train_carriage = modelmod.TRAIN_CARRIAGE_DEFAULT
    tab._train_tickets = modelmod.TRAIN_TICKETS_DEFAULT
    tab._train_buy = modelmod.TRAIN_BUY_DEFAULT
    tab._train_args_registered = True
    # «Гонка вооружений» — the phase running now, the day's borders, and the one
    # standing order there is: whether the four-hourly run may hire.
    tab._arms = modelmod.parse(arms, at=1.0) if arms is not None else None
    tab._arms_cal = modelmod.arms_calendar(arms_day)
    tab._arms_busy = False
    tab._arms_running = False
    tab._chain_arms = False
    tab._arms_hero = modelmod.ARMS_HERO_DEFAULT
    tab._arms_hero_var = None
    tab._arms_drone = modelmod.ARMS_DRONE_DEFAULT
    tab._arms_drone_var = None
    tab._arms_stamina = modelmod.ARMS_STAMINA_DEFAULT
    tab._arms_squad = modelmod.ARMS_SQUAD_DEFAULT
    tab._arms_args_registered = True
    return tab


def test_the_train_card_says_what_stands_at_the_platform():
    """The phone's train card is the reading, and every word on it is a key."""
    tab = _tab()
    card = _card(tab, "events.group.train")
    rows = {r["label"]: r["value"] for r in card["rows"]}
    assert rows["events.train.platform"] == "events.train.platform.driver"
    assert rows["events.train.fare"] == "events.train.fare.open"
    assert rows["events.train.contracts"] == "92"
    assert rows["events.train.queue"] == "57 / 28"
    assert rows["events.train.seat"] == "—"          # not in a carriage yet
    assert [a["id"] for a in card["actions"]] == ["board_train"]
    # …and the two knobs are FIELDS the phone can set, not buttons it has to walk.
    fields = {f["key"]: f for f in card["fields"]}
    assert fields[modelmod.TRAIN_CARRIAGE_KEY]["kind"] == "number"
    assert (fields[modelmod.TRAIN_CARRIAGE_KEY]["min"],
            fields[modelmod.TRAIN_CARRIAGE_KEY]["max"]) == (1, 4)
    assert (fields[modelmod.TRAIN_TICKETS_KEY]["min"],
            fields[modelmod.TRAIN_TICKETS_KEY]["max"]) == (0, 3)
    # …and spending DIAMONDS is a switch of its own, off, beside the count in the bag.
    assert fields[modelmod.TRAIN_BUY_KEY]["kind"] == "switch"
    assert fields[modelmod.TRAIN_BUY_KEY]["value"] is False


def test_the_train_knobs_are_what_the_recipe_and_the_trigger_are_handed():
    """Walking the two knobs on the phone changes the ARGS both the press and the wire
    trigger run with — there is one rule, not a phone's and a schedule's."""
    tab = _tab()
    assert tab.train_args() == {"carriage": 1, "tickets": 0, "buy": 0}
    tab.web_press("set", {"key": modelmod.TRAIN_CARRIAGE_KEY, "value": 2})
    tab.web_press("set", {"key": modelmod.TRAIN_TICKETS_KEY, "value": 1})
    assert tab.train_args() == {"carriage": 2, "tickets": 1, "buy": 0}
    # A value the page should not have been able to send lands on the nearest one that
    # exists — never on the game.
    assert tab.web_press("set", {"key": modelmod.TRAIN_TICKETS_KEY,
                                 "value": 99}) == {"ok": False,
                                                   "reason": "web.ui.not_a_number"}
    assert tab.web_press("set", {"key": modelmod.TRAIN_TICKETS_KEY,
                                 "value": "три"}) == {"ok": False,
                                                      "reason": "web.ui.not_a_number"}
    assert tab.tickets() == 1                # refused, not clamped to something else
    assert tab.config()[modelmod.TRAIN_CARRIAGE_KEY] == 2
    assert tab.config()[modelmod.TRAIN_TICKETS_KEY] == 1
    # …and the press plays the recipe WITH them, never a second copy of the rule.
    tab.board_train()
    assert tab.rt.played[-1] == modelmod.TRAIN_BOARD
    assert tab.rt.args[-1] == {"carriage": 2, "tickets": 1, "buy": 0}


def test_spending_diamonds_is_a_second_permission_and_starts_off():
    """The number says what the fare should be; the box says whether money may reach it."""
    tab = _tab()
    assert tab.buy_missing() is False
    assert tab.train_args()["buy"] == 0
    assert tab.web_press("set", {"key": modelmod.TRAIN_BUY_KEY,
                                 "value": True}) == {"ok": True, "buy": True}
    assert tab.train_args()["buy"] == 1
    assert tab.config()[modelmod.TRAIN_BUY_KEY] is True
    # …and it survives a profile's saved block the way the other two do.
    fresh = _tab()
    fresh.apply_config(tab.config())
    assert fresh.buy_missing() is True and fresh.tickets() == tab.tickets()


def test_a_fare_that_costs_something_asks_before_it_is_paid():
    """A like is free and goes straight through; contracts leave the bag, so they ask."""
    free = _card(_tab(), "events.group.train")
    board = [a for a in free["actions"] if a["id"] == "board_train"][0]
    assert "confirm" not in board
    tab = _tab()
    tab._train_tickets = 3
    paid = [a for a in _card(tab, "events.group.train")["actions"]
            if a["id"] == "board_train"][0]
    assert paid["confirm"] == "events.train.board.confirm"


def test_a_station_with_no_train_still_gets_its_card():
    """Closed is drawn, not hidden — «нечего делать» must not look like «панель не знает»."""
    card = _card(_tab(train=TRAIN_SHUT), "events.group.train")
    rows = {r["label"]: r["value"] for r in card["rows"]}
    assert rows["events.state"] == "events.train.state.closed"
    assert rows["events.train.platform"] == "events.train.platform.none"
    assert "actions" not in card


def test_the_tab_is_registered_and_says_who_it_is():
    from panel import tabs as tabsreg

    spec = tabsreg.BY_ID.get("events")
    assert spec is not None, "the tab is not in the registry"
    cls = _tab_class()
    assert cls.TITLE_KEY == spec.title_key == "tab.events"
    assert cls.WEB_SCREEN is True
    assert cls.AGGREGATES_TABS == spec.aggregates is False
    assert not cls.EAGER, "a board nobody has opened must not read the game at boot"


def test_the_screen_is_keys_and_data_and_every_button_is_answered():
    keyish = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    english = json.loads(
        (Path(i18nmod.LOCALES_DIR) / "en.json").read_text(encoding="utf-8"))
    for raw in (SHUT, OPEN, None):
        tab = _tab(raw)
        view = tab.web_view()
        keys = []
        offered = {a["id"] for a in view["actions"]}
        keys += [a["label"] for a in view["actions"]]
        for card in view["cards"]:
            assert set(card) <= {"title", "head", "rows", "items", "empty", "search",
                                 "actions", "fields", "note"}
            keys += [k for k in (card.get("title"), card.get("empty"),
                                 card.get("note")) if k]
            keys += [r["label"] for r in card.get("rows") or ()]
            # A knob's label and hint are words; its key and value are data, and its
            # kind is one the renderer knows (docs/panel-tabs.md).
            for field in card.get("fields") or ():
                assert field["kind"] in ("switch", "number", "text", "choice",
                                         squad_picker.KIND)
                keys += [k for k in (field.get("label"), field.get("hint")) if k]
                assert not keyish.match(str(field["key"])), \
                    "a knob's key is data, not a locale key"
            for item in card.get("items") or ():
                assert "text" not in item, \
                    "a title of the panel's own must be a key, not data"
                keys += [k for k in (item.get("label"), item.get("pill")) if k]
            keys += [a["label"] for a in card.get("actions") or ()]
            offered |= {a["id"] for a in card.get("actions") or ()}
        for key in keys:
            assert keyish.match(key), f"«{key}» is a sentence, not a locale key"
            assert key in english, f"«{key}» is in no locale"
        for action in offered:
            assert _tab(raw).web_press(action, {}).get("error") != "unknown", \
                f"«{action}» is a dead button"
        assert tab.web_press("no-such-action-ever", {}).get("error") == "unknown"


def _card(tab, title):
    """One card of the screen, by its title key."""
    for card in tab.web_view()["cards"]:
        if card.get("title") == title:
            return card
    raise AssertionError("no card titled %r" % title)


def _card_actions(tab, title):
    """The action ids offered on one card of the screen — the others are not the point."""
    for card in tab.web_view()["cards"]:
        if card.get("title") == title:
            return [a["id"] for a in card.get("actions") or ()]
    return []


def test_the_phone_is_offered_the_attack_only_while_the_event_is_running():
    shut = _tab(SHUT)
    assert _card_actions(shut, "events.group.codename") == []
    assert shut.web_press("attack_codename", {}) == {"error": "closed"}
    assert shut.web_press("daily_codename", {}) == {"error": "closed"}
    assert shut.rt.played == [], "a press reached the game with the event shut"

    live = _tab(OPEN)
    assert _card_actions(live, "events.group.codename") == ["attack_codename",
                                                           "daily_codename"]
    assert live.web_press("attack_codename", {}) == {"ok": True}
    assert live.rt.played == [modelmod.CODENAME_ATTACK]

    day = _tab(OPEN)
    assert day.web_press("daily_codename", {}) == {"ok": True}
    assert day.rt.played == [modelmod.CODENAME_DAILY]


def test_the_phone_hunts_golden_zombies_only_while_the_purse_can_pay():
    """The same rule as the boss: a reading that SAYS «no energy» kills the button."""
    spent = _tab(golden=GOLDEN_SPENT)
    assert _card_actions(spent, "events.group.golden") == []
    assert spent.web_press("hunt_golden", {}) == {"error": "closed"}
    assert spent.rt.played == [], "a hunt reached the game with an empty purse"

    live = _tab(golden=GOLDEN_OPEN)
    # …and beside the chain, the chain taken apart: one press per step, so a person can
    # find a zombie, look at what was chosen, and only then send anything at it (#1702).
    STEPS = ["find_golden", "attack_golden", "recall_golden", "state_golden",
             "goto_golden", "forget_golden", "rescan_golden"]
    assert _card_actions(live, "events.group.golden") == [
        "hunt_golden", "approach_toggle"] + STEPS
    assert live.web_press("hunt_golden", {}) == {"ok": True}
    assert live.rt.played == [modelmod.GOLDEN_ATTACK]

    # …and a reading nobody could take leaves it alive: «nobody knows» is not «you may
    # not», and the scenario holds its own gates.
    unknown = _tab(golden=None)
    assert _card_actions(unknown, "events.group.golden") == [
        "hunt_golden", "approach_toggle"] + STEPS


def test_every_step_of_the_hunt_is_a_scenario_the_phone_can_press():
    """The chain taken apart, one button per step (#1702).

    The operator asked for it after watching the whole chain misbehave: «не просто "бить
    зомби", а по этапам» — find the nearest and LOOK at what was chosen, then attack that
    one and see what the game said. Each step is a scenario played through `run_action`,
    each is on the phone as well as in the window, and «атаковать выбранного» sends at
    the target already parked rather than picking one for itself.
    """
    from pathlib import Path as _Path

    tab = _tab(golden=GOLDEN_OPEN)
    for action, scenario, key in tab.STEPS:
        tab.rt.played.clear()
        assert tab.web_press(action, {}) == {"ok": True}, action
        assert tab.rt.played == [scenario], f"{action} played {tab.rt.played}"
        recipe = (_Path(__file__).resolve().parents[1] / "src" / "lastwar_bot"
                  / "actions" / f"{scenario}.md")
        assert recipe.exists(), f"{action} names a scenario that is not there"
        assert key.startswith("events.golden.step."), key


def test_forgetting_the_target_empties_what_the_card_shows_at_once():
    """«Забыть цель» — asked for so that «атаковать» cannot fire at a stale choice.

    The card stops naming a zombie the moment the press is made rather than when the
    scenario comes back: the run cannot fail in a way that leaves one chosen, and a card
    still showing one would be the panel disagreeing with the game about something the
    person has just done (#1702).
    """
    tab = _tab(golden=GOLDEN_OPEN)
    tab._golden_target = "#935 X:585 Y:411"
    assert tab.web_press("forget_golden", {}) == {"ok": True}
    assert tab._golden_target == ""
    assert tab.rt.played == ["golden_forget_target"]
    row = next(r for c in tab.web_view()["cards"] if c.get("title") == "events.group.golden"
               for r in c["rows"] if r["label"] == "events.golden.target")
    assert row["value"] == tab.t("events.golden.target.none")


def test_attacking_uses_the_squad_the_panel_shows_and_the_target_already_fixed():
    """«Берём выбранный отряд и бьём зафиксированную цель» — the operator (#1702).

    The squad travels with the press, so changing it on the tab between «найти» and
    «атаковать» changes which squad goes; and the recipe points the run at it with
    `golden_use_squad` rather than re-arming, because arming builds the run's state from
    nothing and would throw the fixed target away.
    """
    from pathlib import Path as _Path
    import sys as _sys
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    tab = _tab(golden=GOLDEN_OPEN)
    tab._squad = 3
    assert tab.web_press("attack_golden", {}) == {"ok": True}
    assert tab.rt.played == ["golden_attack_target"]
    assert tab.rt.args and tab.rt.args[-1].get("squad") == 3, tab.rt.args

    recipe = (_Path(__file__).resolve().parents[1] / "src" / "lastwar_bot" / "actions"
              / "golden_attack_target.md").read_text(encoding="utf-8")
    # The squad, the forgetting of the last order and the may-I are one call now (#1702).
    assert lua_actions.golden_send_now() in recipe, \
        "the press does not point at the tab's squad"
    assert "TAP golden_arm" not in recipe, "re-arming would forget the fixed target"
    assert lua_actions.golden_order_line() in recipe, \
        "what goes to the game is not printed before it goes"
    assert "TAP golden_pick" not in recipe, "the attack picks a target of its own"


def test_what_follows_a_press_is_armed_when_the_press_ENDS():
    """The flight after «найти» was on a stopwatch and lost the race every time (#1702).

    Armed 300 ms after the press, it landed while the find still held the client and the
    panel refused it — «занят — дождись завершения текущего действия» — so the button
    printed a coordinate and the camera never moved. From the outside: «перестал
    работать вовсе».
    """
    tab = _tab(golden=GOLDEN_OPEN)

    class _Done:
        ok = True
        reason = ""
        ctx = None

    armed: list = []
    tab._after = lambda delay, scenario: armed.append((delay, scenario))
    tab.step("find_golden")
    assert armed == [], "the follow-up is armed before the press has finished"
    tab._step_back(_Done())
    assert armed and armed[0][1] == "golden_goto_target", armed
    # …and a find that failed does not fly anywhere.
    armed.clear()
    tab.step("find_golden")
    tab._step_back(type("F", (), {"ok": False, "reason": "no target", "ctx": None})())
    assert armed == [], "a failed find still flies the camera somewhere"


def test_a_press_that_lands_on_a_busy_client_waits_instead_of_being_lost():
    """«Кнопки срабатывают через раз… нужно чтобы чётко: нажал — будет выполнено» (#1702).

    A press can land while a timer, the auto-rally or the press before it is driving the
    client. It used to be refused, and from the outside that is a button that works
    every third or fifth time. Now it waits its turn, says so, and goes in when the
    client is free — and a second press of the same button replaces the waiting one
    rather than piling up behind it.
    """
    tab = _tab(golden=GOLDEN_OPEN, plays=False)     # the client refuses everything
    retries: list = []
    tab._retry_soon = lambda *a, **k: retries.append(True)

    assert tab.step("find_golden") is True, "a refused press reports failure to the user"
    assert tab._waiting == {"find_golden": True}
    assert tab._step_said == "events.golden.said.queued"
    tab.step("find_golden")
    assert tab._waiting == {"find_golden": True}, "the same button queued twice"
    tab.step("attack_golden")
    assert set(tab._waiting) == {"find_golden", "attack_golden"}, \
        "one button's wait cancelled another's"

    # …and when the client frees up, the waiting presses go in and the queue empties.
    tab.rt.plays = True
    tab._drain_waiting()
    assert tab._waiting == {}, tab._waiting
    assert set(tab.rt.played) == {"golden_find_target", "golden_attack_target"}


def test_the_squad_the_phone_picks_is_the_squad_the_window_sends():
    """One setting, two front-ends: the pick walks the slots and both read `squad()`."""
    tab = _tab()
    assert tab.squad() == modelmod.GOLDEN_SQUAD_DEFAULT
    first = tab.web_press("squad_next", {})
    assert first == {"ok": True, "squad": 2}
    assert tab.squad() == 2
    assert tab.config()[modelmod.GOLDEN_SQUAD_KEY] == 2
    assert tab.rt.played == [], "picking a squad is a setting, not a press at the game"

    # …and it wraps rather than running off the end of the slots that exist.
    for _ in modelmod.GOLDEN_SQUADS:
        tab.web_press("squad_next", {})
    assert tab.squad() in modelmod.GOLDEN_SQUADS

    tab.apply_config({modelmod.GOLDEN_SQUAD_KEY: 3})
    assert tab.squad() == 3
    tab.apply_config({modelmod.GOLDEN_SQUAD_KEY: 99})
    assert tab.squad() == modelmod.GOLDEN_SQUAD_DEFAULT, \
        "a slot that does not exist must not be sent anywhere"


def test_the_fast_approach_is_a_switch_on_both_front_ends():
    """The ride is a choice about how the chain TRAVELS, so it is set, not inferred."""
    tab = _tab()
    assert tab.approach() is False, \
        "the ride ships off — the attack from the far end is refused in silence (#1519)"
    assert tab.config()[modelmod.GOLDEN_APPROACH_KEY] is False
    assert tab.web_press("approach_toggle", {}) == {"ok": True, "approach": True}
    assert tab.approach() is True
    assert tab.rt.played == [], "a switch pressed something at the game"
    tab.apply_config({modelmod.GOLDEN_APPROACH_KEY: False})
    assert tab.approach() is False
    # …and the phone SAYS which way it is set, in words rather than a bare true/false.
    rows = {r["label"]: r["value"] for c in tab.web_view()["cards"]
            for r in c.get("rows") or ()}
    assert rows["events.golden.approach"] == "events.golden.approach.off"


def test_the_two_march_speeds_reach_the_board_as_numbers_a_person_reads():
    """The reading carries thousandths; the row shows two decimals and the gain."""
    st = modelmod.golden_state(modelmod.parse(GOLDEN_OPEN))
    assert modelmod.speed(st) == "0.77 / 1.93 · ×2.5"
    blank = modelmod.golden_state(modelmod.parse("energy=55 cost=10"))
    assert modelmod.speed(blank) == "—", "a speed nobody read must not print as zero"


def test_the_golden_board_never_reads_could_not_ask_as_none_found():
    """`seen = -1` is «the base is on screen», and it is not zero zombies."""
    silent = modelmod.golden_state(modelmod.parse("energy=55 cost=10 attacks=5 seen=-1"))
    assert modelmod.seen(silent) == "—"
    none = modelmod.golden_state(modelmod.parse("energy=55 cost=10 attacks=5 seen=0"))
    assert modelmod.seen(none) == "0"


def test_a_closed_event_still_has_its_card_on_the_phone():
    """Grey, never hidden — the same rule the window is drawn by."""
    for raw in (SHUT, None):
        titles = [c.get("title") for c in _tab(raw).web_view()["cards"]]
        assert "events.group.codename" in titles, titles


def test_both_boards_grey_the_press_on_exactly_the_same_terms():
    """One button, two tabs, one rule — CLOSED and nothing else.

    They are separate models on purpose (one draws events, the other a day), so the rule
    they share is the thing worth pinning: an event the game has SAID is shut kills the
    press on both, and a reading nobody could take kills it on neither.
    """
    from panel.tabs.checklist import model as checklist

    for raw, pressable in ((OPEN, True), (SHUT, False), (None, True)):
        here = modelmod.codename_state(
            modelmod.parse(raw) if raw is not None else None).can_attack
        row = checklist.state_of(
            checklist.BY_KEY["codename"],
            checklist.parse(raw) if raw is not None else None)
        there = row.state != checklist.CLOSED
        assert here is there is pressable, (raw, here, there)


def test_the_press_is_not_started_twice_over():
    tab = _tab(OPEN)
    assert tab.attack() is True
    assert tab.attack() is False, "a second press went out while the first was running"
    assert tab.rt.played == [modelmod.CODENAME_ATTACK]


def test_the_board_refreshes_itself_and_says_so_when_it_cannot():
    tab = _tab()
    assert tab.refresh() is True
    assert tab.rt.played == [modelmod.CODENAME_ACTION]
    busy = _tab(plays=False)
    assert busy.refresh() is False
    assert busy._reading.get("need") == 3, "a refused read cleared what was known"
    assert busy._busy is False, "a refused read left the tab thinking it is reading"


def test_a_read_that_failed_is_recorded_as_a_failure_not_as_a_closed_event():
    class _Outcome:
        def __init__(self, ok, raw=None, reason=""):
            self.ok, self.reason = ok, reason
            self.ctx = type("C", (), {"vars": {modelmod.CODENAME_VARIABLE: raw}})()

    tab = _tab()
    tab._read_back(_Outcome(False, reason="no daemon"))
    assert tab._reading.error == "no daemon"
    assert tab.codename().state == modelmod.UNKNOWN

    tab._read_back(_Outcome(True, raw=OPEN))
    assert tab.codename().state == modelmod.OPEN
    assert not tab._reading.error


def test_the_day_of_the_arms_race_is_read_as_six_borders():
    """The calendar line is parsed into the day's phases, and rubbish is dropped."""
    day = modelmod.arms_calendar(ARMS_DAY)
    assert len(day) == 6
    assert day[1] == (1, modelmod.ARMS_HERO, 1788069600, 1788084000)
    # A client that has just restarted says all sorts of things; none of it raises.
    assert modelmod.arms_calendar("nonsense 1:2:3 4:5:6:seven") == ()
    assert modelmod.arms_calendar(None) == ()


def test_an_arms_phase_nobody_could_read_is_unknown_and_never_closed():
    """No answer is «nobody knows» — the same rule the rest of this board goes by."""
    unknown = modelmod.arms_state(None)
    assert unknown.state == modelmod.UNKNOWN
    assert unknown.kind is None and unknown.score is None
    # …and «unknown» has no recipe by definition, so no press is offered over it.
    assert unknown.automated is False


def test_the_arms_card_says_the_phase_the_day_and_the_one_switch():
    """The phone's arms card is the reading, and every word on it is a key."""
    tab = _tab()
    card = _card(tab, "events.group.arms")
    rows = {r["label"]: r["value"] for r in card["rows"]}
    assert rows["events.arms.phase"] == "events.arms.kind.hero"
    assert rows["events.arms.chests"] == "0 / 3"
    assert rows["events.arms.day"] == "1 / 6"
    assert "events.arms.until" in rows            # the phase is running
    # THE DAY'S SIX PHASES — the whole reason the reading sends the calendar get.
    assert len(card["items"]) == 6
    assert card["items"][1]["label"] == "events.arms.kind.hero"
    # …and the switch is a FIELD, because it is a standing order and not a press.
    fields = {f["key"]: f for f in card["fields"]}
    assert fields[modelmod.ARMS_HERO_KEY]["kind"] == "switch"
    assert fields[modelmod.ARMS_HERO_KEY]["value"] is True
    # Hiring spends the player's tickets, so the phone asks before it goes.
    hire = [a for a in card["actions"] if a["id"] == "phase_arms"]
    assert hire and hire[0]["confirm"] == "events.arms.hire.confirm"


def test_a_minute_phase_spends_speed_ups_and_asks_before_it_does():
    """The three middle phases are ONE recipe: minutes poured into a queue (#2065).

    They used to have no press at all, because the sends could not be read and the
    ceiling had not been agreed. Both are settled now — the phase asks first, because
    a speed-up is the one thing on this card that cannot be got back.
    """
    for kind in (120001, 120003):
        phase = ARMS_HERO_PHASE.replace("event=120000", "event=%d" % kind)
        tab = _tab(arms=phase)
        card = _card(tab, "events.group.arms")
        press = [a for a in card["actions"] if a["id"] == "phase_arms"]
        assert press, kind
        assert press[0]["label"] == "events.arms.spend"
        assert press[0]["confirm"] == "events.arms.spend.confirm"
        assert tab.web_press("phase_arms", {}) == {"ok": True}
        assert tab.rt.played == [modelmod.ARMS_SPEEDUP_ACTION]
        # …and it was played WITH its ceiling, because the recipe pours nothing without
        # one: the switch is OFF by default and the minutes are deliberately small.
        args = tab.rt.args[0]
        assert args["speedup"] == 0
        assert args["minutes"] == modelmod.ARMS_MINUTES_DEFAULT
    # …the UNIT phase asks a different question, because it spends a different thing:
    # the base's own resources, bounded by a ceiling counted in soldiers rather than in
    # minutes. It got its recipe when the training send was proven live (#2065).
    unit = ARMS_HERO_PHASE.replace("event=120000", "event=%d" % modelmod.ARMS_UNIT)
    tab = _tab(arms=unit)
    card = _card(tab, "events.group.arms")
    press = [a for a in card["actions"] if a["id"] == "phase_arms"]
    assert press and press[0]["label"] == "events.arms.train"
    assert press[0]["confirm"] == "events.arms.train.confirm"
    assert tab.web_press("phase_arms", {}) == {"ok": True}
    assert tab.rt.played == [modelmod.ARMS_UNIT_ACTION]
    args = tab.rt.args[0]
    assert args["units"] == 0                  # switched off until the person says so
    assert args["soldiers"] == modelmod.ARMS_SOLDIERS_DEFAULT
    # …and a phase the server invents tomorrow still gets no press, only the errand.
    other = ARMS_HERO_PHASE.replace("event=120000", "event=129999")
    tab = _tab(arms=other)
    card = _card(tab, "events.group.arms")
    assert [a["id"] for a in card["actions"]] == ["play_arms"]
    assert tab.web_press("phase_arms", {}) == {"error": "closed"}
    assert tab.web_press("play_arms", {}) == {"ok": True}
    assert modelmod.ARMS_ERRAND in tab.rt.played


def test_the_arms_switch_is_one_value_drawn_in_two_places():
    """The gear on «Таймеры» and the card write the SAME knob, and the errand reads it."""
    tab = _tab()
    assert tab.arms_args()["hero"] == 1
    assert tab.web_press("set", {"key": modelmod.ARMS_HERO_KEY,
                                 "value": False})["ok"] is True
    assert tab.arms_hero() is False
    assert tab.arms_args()["hero"] == 0
    # …and the row on «Таймеры» is the same setter, not a second copy of the value.
    options = {o.key: o for o in tab.errand_options()[modelmod.ARMS_ERRAND]}
    assert set(options) == {modelmod.ARMS_HERO_KEY, modelmod.ARMS_DRONE_KEY,
                            modelmod.ARMS_STAMINA_KEY, modelmod.ARMS_SPEEDUP_KEY,
                            modelmod.ARMS_MINUTES_KEY, modelmod.ARMS_UNITS_KEY,
                            modelmod.ARMS_SOLDIERS_KEY, modelmod.ARMS_SQUAD_KEY}
    options[modelmod.ARMS_HERO_KEY].write(tab.rt, True)
    assert tab.arms_hero() is True
    # …and the same for the switch that stands in front of the player's speed-ups: one
    # value, the card and the gear both writing it, and the errand reading it at fire
    # time rather than off the catalogue row it was written with.
    assert tab.arms_args()["speedup"] == 0
    options[modelmod.ARMS_SPEEDUP_KEY].write(tab.rt, True)
    assert tab.arms_speedup() is True
    assert tab.arms_args()["speedup"] == 1
    # A ceiling is REFUSED rather than quietly clamped, the rule the stamina one goes by.
    assert tab.web_press("set", {"key": modelmod.ARMS_MINUTES_KEY,
                                 "value": modelmod.ARMS_MINUTES_MAX + 1})["ok"] is False
    assert tab.web_press("set", {"key": modelmod.ARMS_MINUTES_KEY,
                                 "value": 120})["ok"] is True
    assert tab.arms_args()["minutes"] == 120
    # The unit phase's own pair goes the same way — a SEPARATE switch, because it spends
    # the base's resources rather than items out of the bag, and its ceiling counts
    # soldiers and is refused rather than clamped.
    assert tab.arms_args()["units"] == 0
    options[modelmod.ARMS_UNITS_KEY].write(tab.rt, True)
    assert tab.arms_units() is True
    assert tab.arms_args()["units"] == 1
    assert tab.web_press("set", {"key": modelmod.ARMS_SOLDIERS_KEY,
                                 "value": modelmod.ARMS_SOLDIERS_MAX + 1})["ok"] is False
    assert tab.web_press("set", {"key": modelmod.ARMS_SOLDIERS_KEY,
                                 "value": 250})["ok"] is True
    assert tab.arms_args()["soldiers"] == 250


def test_the_drone_phase_is_raised_and_never_past_the_days_rally_caps():
    """«Тратим только стягами» — and the day's own caps are what bounds it (#2065)."""
    drone = ARMS_HERO_PHASE.replace("event=120000", "event=120004")
    tab = _tab(arms=drone)
    card = _card(tab, "events.group.arms")
    # The press is offered, and it asks first: raising sends a squad out of the base.
    press = [a for a in card["actions"] if a["id"] == "phase_arms"]
    assert press and press[0]["label"] == "events.arms.raise"
    assert press[0]["confirm"] == "events.arms.raise.confirm"
    assert tab.web_press("phase_arms", {}) == {"ok": True}
    assert tab.rt.played == [modelmod.ARMS_DRONE_ACTION]
    # …and it was played WITH the ceilings, because the recipe raises nothing without
    # them: a rally allowance that could not be read is handed over as ZERO, never as
    # «no ceiling» (there is no rally tab behind this fake runtime).
    args = tab.rt.args[0]
    assert args["stamina"] == modelmod.ARMS_STAMINA_DEFAULT
    assert args["rallies"] == 0
    assert args["drone"] == 1


def test_the_stamina_ceiling_is_refused_rather_than_quietly_changed():
    """A ceiling that silently became something else is a ceiling nobody set."""
    tab = _tab()
    assert tab.web_press("set", {"key": modelmod.ARMS_STAMINA_KEY,
                                 "value": 120})["ok"] is True
    assert tab.arms_stamina() == 120
    for bad in ("сто", None, modelmod.ARMS_STAMINA_MAX + 1, -1):
        assert tab.web_press(
            "set", {"key": modelmod.ARMS_STAMINA_KEY, "value": bad})["ok"] is False
    assert tab.arms_stamina() == 120, "a refused value moved the ceiling anyway"


def test_the_drone_recipe_holds_its_own_ceilings():
    """The gates are in the ability, not in the panel (`CLAUDE.md`)."""
    text = (Path(__file__).resolve().parents[1] / "src" / "lastwar_bot" / "actions"
            / "arms_race_drone.md").read_text(encoding="utf-8")
    assert "ARGS stamina = 300" in text
    assert "ARGS rallies = 0" in text
    # No allowance means no banner — silence is a refusal, never a licence.
    assert "IF rallies == 0" in text and "STOP" in text
    # The phase kind is checked, and the price is ASKED rather than written down.
    assert "IF arms_event != 120004" in text
    assert "GetCostStaminaByTargetType" in text
    # …and nothing in it names a score rule: the server only hands over the CURRENT
    # phase's rules, so the recipe judges by whether the score actually moved.
    assert "score did not move" in text


def test_the_score_never_reads_as_a_place_to_go():
    """A grouped «400 / 12 000» is a TILE to the phone's coordinate marker (#1982)."""
    import sys as _sys
    from pathlib import Path as _Path
    for _p in (_Path(__file__).resolve().parents[1] / "tools" / "lib",):
        if str(_p) not in _sys.path:
            _sys.path.insert(0, str(_p))
    from panel.web import coordlinks
    said = modelmod.arms_points(modelmod.arms_state(modelmod.parse(ARMS_HERO_PHASE)))
    assert said == "800 / 12000", said
    assert coordlinks.parts(said) is None, "the phase's score became a jump link"


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
