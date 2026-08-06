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

ACTIONS = _REPO / "src" / "lastwar_bot" / "actions"
READ = ACTIONS / "read_codename_event.md"
ATTACK = ACTIONS / "attack_codename_boss.md"

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

    def play_async(self, name, *a, **kw) -> bool:
        if not self.plays:
            return False
        self.played.append(name)
        return True

    def t(self, key, **fmt):
        return key

    def say(self, tag, key, **fmt) -> None:
        pass


def _tab(raw=SHUT, plays=True):
    cls = _tab_class()
    tab = cls.__new__(cls)
    tab.rt = _Runtime(plays)
    tab._reading = modelmod.parse(raw, at=1.0) if raw is not None else None
    tab._busy = False
    tab._attacking = False
    tab._body = None
    tab._status = None
    tab._attack_button = None
    return tab


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
                                 "actions"}
            keys += [k for k in (card.get("title"), card.get("empty")) if k]
            keys += [r["label"] for r in card.get("rows") or ()]
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


def test_the_phone_is_offered_the_attack_only_while_the_event_is_running():
    shut = _tab(SHUT)
    assert not [a for c in shut.web_view()["cards"] for a in c.get("actions") or ()]
    assert shut.web_press("attack_codename", {}) == {"error": "closed"}
    assert shut.rt.played == [], "a press reached the game with the event shut"

    live = _tab(OPEN)
    ids = [a["id"] for c in live.web_view()["cards"] for a in c.get("actions") or ()]
    assert ids == ["attack_codename"]
    assert live.web_press("attack_codename", {}) == {"ok": True}
    assert live.rt.played == [modelmod.CODENAME_ATTACK]


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
