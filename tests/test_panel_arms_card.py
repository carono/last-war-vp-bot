r"""The hour of «Гонка вооружений», on the face of its card (#2635).

The person asked for it in these words: «Вверх то не настолько, уж под ссылками, перед
карточками vs просто. В карточке гонки выведи текущий час, сундуки которые взяты, прямо
как в игре, 3 сундука, серые и цветные, в зависимости от того взяты или нет. Так же
текущие очки гонки. Саму карточку обновляем, пусть картинка меняется в соответствии с
часом гонки».

Four things are pinned here, and each of them is a rule this repository already has:

* the reading is ONE state both pages write and neither re-asks
  (`panel/runtime/arms_live.py`) — «одно состояние, несколько мест, где его рисуют»;
* it is taken when the client gets into the game, moved by the event's own push and by
  the border of the hour, and by no clock and no «Обновить» (#2633);
* an unknown chest is a DASH and never a zero — the difference between «nobody asked»
  and «nothing was taken» is the whole reason the card exists;
* and the card stands UNDER the screen's links rather than over them.

    C:\Python312\python.exe tests\test_panel_arms_card.py
"""
from __future__ import annotations

TIER = "offline"        # no game, no Tk — a dict, a source file and a reading

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools" / "lib"))

from panel.runtime import arms_live                      # noqa: E402
from panel.web.api import WebApi                         # noqa: E402

#: A reading of the shape `actions/read_arms_race.md` hands over. Invented values of the
#: right shape, never an account's own (`CLAUDE.md`).
READING = ("open=1 aid=29 day=3 stage=1 event=120001 name=2000601 sc=800 "
           "rules=122,121,103 t1=2000 t2=4000 t3=12000 g1=1 g2=0 g3=0 "
           "until=5400 done=1 d1=1 d2=0 d3=0")
CALENDAR = "0:120004:1788055200:1788069600 1:120001:1788069600:1788084000"


class _Store:
    def __init__(self) -> None:
        self.rows: dict = {}

    def blob_get(self, name: str):
        return self.rows.get(name)

    def blob_set(self, name: str, value) -> None:
        self.rows[name] = value


class _Rt:
    def __init__(self) -> None:
        self.store = _Store()
        self.tabs = None

    def play_async(self, *a, **k):
        raise AssertionError("drawing the card must never play a scenario")


# ---------------------------------------------------------------------------
# the reading, kept where both pages find it
# ---------------------------------------------------------------------------
def test_the_reading_is_kept_whole_and_read_back_as_the_card():
    rt = _Rt()
    arms_live.record(rt, READING, CALENDAR)
    state, age = arms_live.state(rt)
    assert state.open and state.kind == 120001 and state.stage == 1
    assert state.score == 800 and state.taken == (1, 0, 0)
    assert state.seconds == 5400
    assert len(state.phases) == 2, "the day's borders travel with it"
    assert age is not None and age < 60, "and the card can say how old it is"


def test_a_reading_with_no_calendar_keeps_the_one_already_known():
    """The six borders were fixed a week ago; a half-loaded client must not blank them."""
    rt = _Rt()
    arms_live.record(rt, READING, CALENDAR)
    arms_live.record(rt, READING, "")
    state, _age = arms_live.state(rt)
    assert len(state.phases) == 2


def test_nothing_read_is_unknown_and_not_a_closed_event():
    rt = _Rt()
    state, age = arms_live.state(rt)
    assert not state.open and state.kind is None and state.taken == ()
    assert age is None, "an age nobody has is None, never «прочитано только что»"


def test_the_reading_never_asks_the_game_anything():
    source = (_REPO / "panel" / "runtime" / "arms_live.py").read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]
    for banned in ("play_async", "run_action", "LUA", "SendMessage"):
        assert banned not in code, f"{banned} in a module that only KEEPS an answer"


# ---------------------------------------------------------------------------
# the card
# ---------------------------------------------------------------------------
def test_the_card_carries_the_hour_its_chests_and_its_points():
    rt = _Rt()
    arms_live.record(rt, READING, CALENDAR)
    card = WebApi._arms_card(rt, "perform_arms_race")
    now = card["arms"]
    assert now["label"] == "events.arms.kind.build", "the hour, as a locale KEY"
    assert now["clock"], "…with its own window in the reader's time"
    assert now["points"] == "800 / 12000", "the score against the top chest, ungrouped"
    assert now["chests"] == [1, 0, 0], "one flag per chest, the server's own"
    assert now["until"] == 5400
    assert now["age"] is not None


def test_only_the_arms_race_gets_any_of_it():
    rt = _Rt()
    arms_live.record(rt, READING, CALENDAR)
    assert WebApi._arms_card(rt, "collect_resources") == {}


def test_an_unread_hour_shows_no_chests_rather_than_three_empty_ones():
    """Three grey chests over an hour nobody read would say «ничего не взято»."""
    rt = _Rt()
    arms_live.record(rt, "open=0 aid=- day=- stage=- event=- sc=- t1=- g1=-", "")
    card = WebApi._arms_card(rt, "perform_arms_race")
    now = card.get("arms") or {}
    assert now.get("chests") is None and not now.get("points")


def test_the_picture_follows_the_hour_and_never_borrows_another():
    """A kind the machine has a sprite for wears it; one it does not keeps the cover."""
    api = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert 'arms.get("arms") or {}).get("icon") or artmod.cover_for' in api, (
        "the hour's own picture, and the errand's cover where there is none")
    live = (_REPO / "panel" / "runtime" / "arms_art.py").read_text(encoding="utf-8")
    assert "return \"\"" in live, "a phase with no picture answers with none"


# ---------------------------------------------------------------------------
# how it is read — and how it is not
# ---------------------------------------------------------------------------
def test_the_hour_is_read_at_the_client_on_the_push_and_at_the_border():
    tab = (_REPO / "panel" / "tabs" / "vs.py").read_text(encoding="utf-8")
    assert 'ARMS_READ = "read_arms_race"' in tab
    assert 'ARMS_PUSH = "push.person.arms.sc.change"' in tab
    assert "self._read_arms()" in tab, "the ready round takes it too"
    assert "_arm_arms_alarm" in tab and "CHAIN_ARMS" in tab, (
        "the border of the hour is a known second, so it is slept until")
    assert "def _arms_push_soon" in tab, "a burst of pushes costs one reading"


def test_the_two_pages_write_the_same_row_and_neither_keeps_its_own():
    events = (_REPO / "panel" / "tabs" / "events" / "tab.py").read_text(encoding="utf-8")
    assert "arms_live.record(" in events, "«События» writes what its own card read"
    api = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert "arms_live.state(rt" in api, "…and the card reads that one row"


def test_the_card_has_no_refresh_of_its_own():
    """#2633: a board of readings has no «Обновить» — the age is what it owes instead."""
    card = (_REPO / "panel" / "web" / "app" / "src" / "ui"
            / "ErrandCard.tsx").read_text(encoding="utf-8")
    hour = card.split("function ArmsHour", 1)[1].split("function Reading", 1)[0]
    assert "onClick" not in hour, "the hour is a reading, not a press"
    assert "timers.stat.age" in hour, "…and it says how old it is"


# ---------------------------------------------------------------------------
# where it stands
# ---------------------------------------------------------------------------
def test_the_card_stands_under_the_links_and_over_the_weeks_cards():
    app = (_REPO / "panel" / "web" / "app" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "lead={" in app, "the card travels INTO the screen rather than above it"
    screen = (_REPO / "panel" / "web" / "app" / "src" / "views"
              / "ScreenView.tsx").read_text(encoding="utf-8")
    body = screen.split("export function ScreenPage", 1)[1]
    assert 'className="tiles lead"' in body
    assert body.index('className="chips"') < body.index('className="tiles lead"'), (
        "under the strip of links")
    assert body.index('className="tiles lead"') < body.index("drawn.map("), (
        "…and before the screen's own cards")


def test_the_chests_are_drawn_and_never_somebody_elses_sprite():
    card = (_REPO / "panel" / "web" / "app" / "src" / "ui"
            / "ErrandCard.tsx").read_text(encoding="utf-8")
    assert "function Chest(" in card and "<svg" in card
    css = (_REPO / "panel" / "web" / "app" / "src" / "app.css").read_text(encoding="utf-8")
    assert ".chest.on" in css and ".chest {" in css, "grey until taken, gold once it is"


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except Exception as exc:                        # noqa: BLE001
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
