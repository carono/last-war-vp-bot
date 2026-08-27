r"""The status strip: what it reads, how often, and what it refuses to invent (#2016).

The header is on screen on EVERY page of the web panel, so it is the most-asked reading
in the panel — which is exactly why the things pinned here are pacing and honesty rather
than looks:

* **the two halves are paced apart** — the place at most every 10 s, the character at
  most every 10 minutes, because one moves all day and the other never does;
* **a poll never touches the game on the calling thread** — every read is booked through
  `play_async` at DETACHED, and a busy link or a shut gate books nothing at all;
* **a client that answered nothing is not a client standing nowhere** — the previous
  place stays, with its age climbing, and a header that has never read anything says so
  rather than naming a scene;
* **and the route carries it**, so the phone gets it without a second poll.

Needs no game and no display: the runtime here is a stand-in that records what it was
asked to play.

    C:\Python312\python.exe tests\test_status_header.py
"""
from __future__ import annotations

TIER = "offline"        # no game, no Tk — see tools/run_tests.py

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel.runtime import claims                    # noqa: E402
from panel.runtime import header as headermod       # noqa: E402


class _Link:
    def __init__(self) -> None:
        self.busy = False


class _Gate:
    def __init__(self) -> None:
        self.shut = False

    def blocks(self, _action: str, human: bool = False) -> bool:
        return self.shut


class _Outcome:
    """What `play_async` hands back — a context whose `vars` hold what a recipe left."""

    def __init__(self, **variables) -> None:
        self.ctx = type("Ctx", (), {"vars": dict(variables)})()


class _Runtime:
    """The panel's runtime, reduced to what the header touches."""

    def __init__(self) -> None:
        self.game = _Link()
        self.gate = _Gate()
        self.played: list = []
        self.answers: dict = {}          # action -> the outcome the play lands with

    def play_async(self, action, args=None, *, tag="", human=False,
                   priority=None, on_result=None, **_kw) -> bool:
        self.played.append((action, priority, tag, human))
        landed = self.answers.get(action)
        if landed is not None and on_result is not None:
            on_result(landed)
        return True


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _header(rt, clock):
    return headermod.StatusHeader(rt, clock=clock)


def test_place_line_is_read_as_written() -> None:
    """The five fields of `read_player_place.md`, and no guessing at a short line."""
    got = headermod.parse_place("world;;UILWAlMain;;2;;935;;900")
    assert got == {"scene": "world", "window": "UILWAlMain", "depth": 2,
                   "server": 935, "home": 900}, got
    # An empty window is the ordinary case — the player is looking at the scene itself.
    assert headermod.parse_place("city;;;;0;;935;;935")["window"] == ""
    # A scene the panel does not know is `unknown`, never passed through as a word.
    assert headermod.parse_place("lobby;;;;0;;1;;1")["scene"] == "unknown"
    # …and half a line is dropped whole rather than read into the wrong fields.
    assert headermod.parse_place("world;;UIMain;;1") == {}
    assert headermod.parse_place("") == {}


def test_who_line_takes_the_two_fields_it_draws() -> None:
    got = headermod.parse_who("Player1;;35;;100000000;;[AL1] Alliance One;;67;;0;;0")
    assert got == {"nick": "Player1", "level": 35}, got
    assert headermod.parse_who("") == {}


def test_both_halves_are_read_on_the_first_look() -> None:
    rt, clock = _Runtime(), _Clock()
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="world;;UISearch;;1;;935;;935")
    rt.answers[headermod.WHO_ACTION] = _Outcome(
        player_card="Player1;;35;;100000000;;[AL1] Alliance One;;67;;0;;0")
    state = _header(rt, clock).state()
    assert state["nick"] == "Player1" and state["level"] == 35, state
    assert state["scene"] == "world" and state["window"] == "UISearch", state
    assert state["server"] == 935 and state["home"] == 935, state
    assert state["age"] == 0, state
    # BOTH PLAYS GO IN BELOW EVERY ERRAND: a header is a page being looked at.
    assert [name for name, *_ in rt.played] == [headermod.WHERE_ACTION,
                                                headermod.WHO_ACTION], rt.played
    assert all(priority == claims.DETACHED for _n, priority, *_ in rt.played), rt.played


def test_the_place_is_paced_and_the_character_is_paced_far_slower() -> None:
    """The whole reason this class exists: /api/state is asked every 2.5 s."""
    rt, clock = _Runtime(), _Clock()
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="city;;;;0;;935;;935")
    rt.answers[headermod.WHO_ACTION] = _Outcome(player_card="Player1;;35;;0;;;;0;;0;;0")
    head = _header(rt, clock)
    head.state()
    rt.played.clear()
    for _ in range(3):                    # 7.5 s of polling at the page's own pace
        clock.now += 2.5
        head.state()
    assert rt.played == [], rt.played     # …and not one question asked
    clock.now += 2.5                      # now the place is due, and only the place
    head.state()
    assert [name for name, *_ in rt.played] == [headermod.WHERE_ACTION], rt.played
    rt.played.clear()
    clock.now += headermod.WHO_GAP_SEC    # …and much later, the character too
    head.state()
    assert headermod.WHO_ACTION in [name for name, *_ in rt.played], rt.played


def test_a_busy_link_or_a_shut_gate_asks_nothing() -> None:
    """Even with nothing read yet: `play_async` refuses a busy link OUT LOUD, twice, and
    a strip that kept asking would write the log instead of reading the game."""
    rt, clock = _Runtime(), _Clock()
    rt.game.busy = True
    head = _header(rt, clock)
    assert head.state()["age"] == -1
    assert rt.played == [], rt.played
    rt.game.busy = False
    rt.gate.shut = True
    head.state()
    assert rt.played == [], rt.played


def test_a_client_that_answered_nothing_keeps_the_last_place_and_ages_it() -> None:
    rt, clock = _Runtime(), _Clock()
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="world;;;;0;;935;;935")
    head = _header(rt, clock)
    head.state()
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="")   # login screen
    clock.now += headermod.WHERE_GAP_SEC + 1
    state = head.state()
    assert state["scene"] == "world", state          # the old reading, not a blank one
    assert state["age"] > headermod.WHERE_GAP_SEC, state


def test_nothing_read_yet_names_no_scene() -> None:
    rt, clock = _Runtime(), _Clock()
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="")
    state = _header(rt, clock).state()
    assert state["scene"] == "" and state["age"] == -1, state
    assert state["nick"] == "" and state["server"] == 0, state


def test_the_route_carries_the_header() -> None:
    """`/api/state` is the one poll the strip rides — never a second one of its own."""
    source = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert '"header": rt.header.state()' in source


def test_the_scenario_exists_and_the_panel_writes_no_lua_for_it() -> None:
    recipe = (_REPO / "src" / "lastwar_bot" / "actions" / "read_player_place.md")
    assert recipe.exists(), "the ability is a scenario (CLAUDE.md)"
    assert "INTO player_place" in recipe.read_text(encoding="utf-8")
    module = (_REPO / "panel" / "runtime" / "header.py").read_text(encoding="utf-8")
    for forbidden in ("pcall(", "SceneUtils", "UIManager"):
        assert forbidden not in module, f"the panel assembles no Lua: {forbidden}"


def _run() -> int:
    failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
            print(f"ok   {name}")
        except Exception as exc:                     # noqa: BLE001 — a test report
            failed += 1
            print(f"FAIL {name}: {exc}")
    print("all good" if not failed else f"{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
