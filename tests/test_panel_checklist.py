r"""The «Чеклист» tab: the day boundary, the ticks, and what the phone may do with them.

No display and no widget: the list is :mod:`panel.tabs.checklist.model`, and the screen
tests reach the tab class without ever building one. The tab MODULE still imports
tkinter, which the WSL python does not ship — those tests say SKIP there and run under
the Windows one, where the whole file passes:

    C:\Python312\python.exe tests\test_panel_checklist.py

The one test worth reading twice is the last: the phone gets ticking, running and the
reset, and NOT the editing. That is an agreed divergence rather than an unfinished
mirror (`CLAUDE.md`, «An edit travels between the window and the web»), and a rule
nobody has pinned is a rule the next agent will «fix» by adding a button the renderer
cannot draw.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import i18n as i18nmod                      # noqa: E402
from panel.tabs.checklist import model as modelmod     # noqa: E402

DAY = modelmod.DAY_MS
HOUR = modelmod.HOUR_MS


# ---------------------------------------------------------------------------
# the day
# ---------------------------------------------------------------------------
def test_the_day_turns_over_at_the_hour_the_operator_set():
    """Midnight UTC by default, and wherever the box says otherwise."""
    midnight = 20_000 * DAY                      # any whole day, exactly at 00:00
    assert modelmod.day_of(midnight) == 20_000
    assert modelmod.day_of(midnight - 1) == 19_999
    assert modelmod.day_of(midnight + DAY - 1) == 20_000

    # With the reset at 02:00 UTC, 01:59 still belongs to the day before.
    assert modelmod.day_of(midnight + 1 * HOUR, reset_hour=2) == 19_999
    assert modelmod.day_of(midnight + 2 * HOUR, reset_hour=2) == 20_000
    assert modelmod.next_reset_ms(midnight + 3 * HOUR, reset_hour=2) == \
        midnight + DAY + 2 * HOUR

    # An hour that is not one is 0 rather than an exception: it is a typed-in box.
    for junk in ("", "x", None, -1, 24, 99):
        assert modelmod.hour_of(junk) == 0, junk


def test_a_tick_is_stamped_with_a_day_so_yesterday_is_not_today():
    """The whole reason a tick is a day and not a boolean.

    Nothing runs at the reset — the panel may have been closed all night — so «done»
    has to be a comparison the next morning makes for itself.
    """
    lst = modelmod.Checklist([modelmod.Item("collect the base", uid="a")])
    lst.set_done("a", True, day=100)
    assert lst.done_count(100) == 1
    assert lst.done_count(101) == 0, "yesterday's tick is showing as today's"
    assert not lst.get("a").is_done(101)


def test_the_reset_only_clears_todays_ticks():
    """An older stamp already reads as undone, and is the only record of when."""
    lst = modelmod.Checklist([modelmod.Item("a", uid="1"), modelmod.Item("b", uid="2")])
    lst.set_done("1", True, day=100)
    lst.set_done("2", True, day=99)
    assert lst.clear(day=100) == 1
    assert lst.get("1").done_day is None
    assert lst.get("2").done_day == 99, "an old stamp was thrown away"


def test_toggle_answers_with_what_the_box_now_is():
    lst = modelmod.Checklist([modelmod.Item("a", uid="1")])
    assert lst.toggle("1", day=7) is True
    assert lst.toggle("1", day=7) is False
    assert lst.toggle("nobody", day=7) is None


def test_the_countdown_is_the_time_left_of_the_day():
    lst = modelmod.Checklist(reset_hour=0)
    midnight = 20_000 * DAY
    assert lst.seconds_to_reset(midnight) == 24 * 3600
    assert lst.seconds_to_reset(midnight + 23 * HOUR) == 3600
    assert modelmod.hhmm(5 * 3600 + 7 * 60 + 30) == "5:07"
    assert modelmod.hhmm(-1) == "0:00"


# ---------------------------------------------------------------------------
# the list
# ---------------------------------------------------------------------------
def test_the_order_is_the_order_the_routine_is_played_in():
    lst = modelmod.Checklist([modelmod.Item("a", uid="1"), modelmod.Item("b", uid="2"),
                              modelmod.Item("c", uid="3")])
    assert lst.move("3", -1) is True
    assert [i.uid for i in lst.items] == ["1", "3", "2"]
    assert lst.move("1", -1) is False, "a move off the top was made anyway"
    assert lst.move("2", 1) is False
    assert [i.uid for i in lst.items] == ["1", "3", "2"]


def test_a_nameless_errand_is_refused():
    lst = modelmod.Checklist()
    assert lst.add("   ") is None
    assert lst.add("") is None
    assert not lst.items
    assert lst.add(" heal the wounded ").title == "heal the wounded"


def test_the_profile_survives_a_round_trip_and_a_hand_edit():
    lst = modelmod.Checklist(reset_hour=2)
    one = lst.add("collect the base", "collect_base_resources")
    lst.add("say hello in chat")
    lst.set_done(one.uid, True, day=42)

    back = modelmod.Checklist.from_config(json.loads(json.dumps(lst.as_config())))
    assert back.reset_hour == 2
    assert [i.title for i in back.items] == ["collect the base", "say hello in chat"]
    assert back.get(one.uid).scenario == "collect_base_resources"
    assert back.get(one.uid).done_day == 42

    # A profile is a file a person may edit. Nothing in it may raise.
    broken = modelmod.Checklist.from_config(
        {"items": ["not a dict", {"title": ""}, {}, {"title": "fine", "done_day": "x"}],
         "reset_hour": "not an hour"})
    assert [i.title for i in broken.items] == ["fine"]
    assert broken.items[0].done_day is None
    assert broken.reset_hour == 0
    assert modelmod.Checklist.from_config(None).items == []

    # …including the same uid twice, which would make one of the two rows dead.
    twice = modelmod.Checklist.from_config(
        {"items": [{"title": "a", "uid": "same"}, {"title": "b", "uid": "same"}]})
    assert len({i.uid for i in twice.items}) == 2


# ---------------------------------------------------------------------------
# the phone
# ---------------------------------------------------------------------------
class _Settings:
    def __init__(self) -> None:
        self.saves = 0

    def changed(self) -> None:
        self.saves += 1


class _Runtime:
    """The three things a press reaches for. No Tk, no game, no claim."""

    def __init__(self) -> None:
        self.settings = _Settings()
        self.said: list = []
        self.played: list = []

    def say(self, tag, key, **fmt) -> None:
        self.said.append((tag, key))

    def play_async(self, name, args=None, **kw) -> bool:
        self.played.append(name)
        return True


class _Skip(Exception):
    """This test needs the tab module, and this python has no tkinter."""


def _tab_class():
    """`ChecklistTab`, or a skip — the WSL python ships no tkinter to import it with."""
    try:
        from panel.tabs.checklist.tab import ChecklistTab
    except ImportError as exc:              # no tkinter: the model tests still ran
        raise _Skip(str(exc)) from None
    return ChecklistTab


def _tab(items=()):
    """A tab with its list and nothing else — the path `web_view`/`web_press` take."""
    ChecklistTab = _tab_class()

    tab = ChecklistTab.__new__(ChecklistTab)
    tab.rt = _Runtime()
    tab._list = modelmod.Checklist(list(items))
    tab._body = None
    tab._status = None
    tab._hour_var = None
    tab._rows = {}
    tab._drawn_day = None
    tab._running = set()
    return tab


def test_the_screen_is_keys_and_data_and_every_button_is_answered():
    """The same two rules `tests/test_panel_web_screens.py` holds every screen to —
    which cannot check this tab, because its sampler only knows the `DataTab` six."""
    import re

    ChecklistTab = _tab_class()

    keyish = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    english = json.loads(
        (Path(i18nmod.LOCALES_DIR) / "en.json").read_text(encoding="utf-8"))

    tab = _tab([modelmod.Item("collect the base", "collect_base_resources", uid="1"),
                modelmod.Item("send the trucks", uid="2")])
    view = tab.web_view()
    card = view["cards"][0]
    assert [i["text"] for i in card["items"]] == ["collect the base", "send the trucks"]

    keys = [card["title"], card["empty"]]
    keys += [r["label"] for r in card["rows"]]
    for item in card["items"]:
        keys.append(item["pill"])
        keys += [a["label"] for a in item["actions"]]
    keys += [a["label"] for a in view["actions"]]
    for key in keys:
        assert keyish.match(key), f"«{key}» is a sentence, not a locale key"
        assert key in english, f"«{key}» is in no locale"

    # And nothing the renderer cannot draw.
    assert set(card) <= {"title", "head", "rows", "items", "empty", "search"}
    for item in card["items"]:
        assert set(item) <= {"text", "label", "detail", "note", "pill", "actions",
                             "facts", "until"}

    offered = [a["id"] for a in view["actions"]]
    for item in card["items"]:
        offered += [a["id"] for a in item["actions"]]
    for action in set(offered):
        answer = ChecklistTab.web_press(_tab([modelmod.Item("x", "some_scenario",
                                                            uid="1")]),
                                        action, {"uid": "1"})
        assert answer.get("error") != "unknown", f"«{action}» is a dead button"
    assert tab.web_press("no-such-action-ever", {}).get("error") == "unknown"


def test_a_tick_from_the_phone_is_the_same_tick_as_in_the_window():
    tab = _tab([modelmod.Item("collect the base", uid="1")])
    assert tab.web_press("toggle", {"uid": "1"}) == {"ok": True}
    assert tab._list.done_count() == 1
    assert tab.rt.settings.saves == 1, "the profile was never told"
    tab.web_press("toggle", {"uid": "1"})
    assert tab._list.done_count() == 0
    assert tab.web_press("toggle", {"uid": "nobody"}) == {"error": "unknown"}

    tab.web_press("toggle", {"uid": "1"})
    assert tab.web_press("reset", {}) == {"ok": True}
    assert tab._list.done_count() == 0


def test_a_row_with_a_scenario_plays_that_scenario_and_nothing_else():
    """The panel plays scenarios and writes none (`CLAUDE.md`): the name goes to the
    runtime as it was typed, and a row with no scenario has nothing to press."""
    tab = _tab([modelmod.Item("collect the base", "collect_base_resources", uid="1"),
                modelmod.Item("by hand", uid="2")])
    assert tab.web_press("run", {"uid": "1"}) == {"ok": True}
    assert tab.rt.played == ["collect_base_resources"]
    assert tab.web_press("run", {"uid": "2"}) == {"ok": False}
    assert tab.rt.played == ["collect_base_resources"], "an empty scenario was played"

    # A scenario that failed leaves the box alone; one that worked ticks it.
    class _Outcome:
        def __init__(self, ok):
            self.ok = ok

    tab._ran("1", _Outcome(False))
    assert tab._list.done_count() == 0
    tab._ran("1", _Outcome(True))
    assert tab._list.done_count() == 1


def test_the_phone_may_tick_run_and_reset_and_may_not_edit_the_list():
    """THE AGREED DIVERGENCE, pinned so it cannot be quietly widened either way.

    The web renderer has no text field at all (`panel/web/static/app.js`), so adding,
    renaming, re-ordering and deleting stay in the window. That was agreed with the
    operator and written into `CLAUDE.md` and `docs/panel-tabs.md`; if a later change
    gives the phone an editing button, this test is where the decision gets re-taken.
    """
    tab = _tab([modelmod.Item("collect the base", "collect_base_resources", uid="1")])
    view = tab.web_view()
    offered = {a["id"] for a in view["actions"]}
    for item in view["cards"][0]["items"]:
        offered |= {a["id"] for a in item["actions"]}
    assert offered == {"toggle", "run", "reset"}, offered

    before = [i.title for i in tab._list.items]
    for editing in ("add", "edit", "delete", "remove", "move", "rename"):
        assert tab.web_press(editing, {"uid": "1", "title": "something"}) == \
            {"error": "unknown"}, f"the phone can «{editing}»"
    assert [i.title for i in tab._list.items] == before


def test_the_tab_is_registered_and_says_who_it_is():
    from panel import tabs as tabsreg

    spec = tabsreg.BY_ID.get("checklist")
    assert spec is not None, "the tab is not in the registry"
    cls = _tab_class()
    assert cls.TITLE_KEY == spec.title_key == "tab.checklist"
    assert cls.WEB_SCREEN is True
    assert cls.AGGREGATES_TABS == spec.aggregates is False


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
