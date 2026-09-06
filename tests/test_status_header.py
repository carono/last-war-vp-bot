r"""The status strip: what it reads, how often, and what it refuses to invent (#2016).

The header is on screen on EVERY page of the web panel, so it is the most-asked reading
in the panel — which is exactly why the things pinned here are pacing and honesty rather
than looks:

* **each half is read ONCE and never on a clock** — `CLAUDE.md`'s «Читаем один раз,
  дальше слушаем»: a second reading happens only when something TELLS the strip it moved,
  and `mark_stale` is the only door that exists;
* **a poll never touches the game on the calling thread** — every read is booked through
  `play_async` at DETACHED, and a busy link or a shut gate books nothing at all;
* **a client that answered nothing is not a client standing nowhere** — the previous
  place stays, with its age climbing, and a header that has never read anything says so
  rather than naming a scene;
* **and the CHARACTER outlives the link altogether** (#2075) — the name, the level and the
  face were written down when they were read, so a lost client, a kick or a restart draws
  the account the panel knows instead of a blank strip, and only a NEW LOGIN asks again;
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


class _Store:
    """The one database, reduced to the row the player card lives in."""

    def __init__(self, card=None) -> None:
        self.card = card

    def blob_get(self, name: str):
        return self.card if name == "player_card" else None

    def blob_set(self, name: str, value) -> None:
        if name == "player_card":
            self.card = dict(value)


class _Runtime:
    """The panel's runtime, reduced to what the header touches."""

    def __init__(self, store=None) -> None:
        self.store = store
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
    assert got == {"nick": "Player1", "level": 35, "uid": "", "pic_ver": 0}, got
    # …and the two fields that find the FACE when the line carries them (#2061).
    got = headermod.parse_who(
        "Player1;;35;;100000000;;[AL1] Alliance One;;67;;0;;0;;1000000000000001;;4")
    assert got["uid"] == "1000000000000001" and got["pic_ver"] == 4, got
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


def test_it_reads_once_and_no_clock_ever_reads_again() -> None:
    """THE RULE: «читаем один раз, дальше слушаем». A page open all evening polls
    /api/state every 2.5 s and must not cost the game a single further question."""
    rt, clock = _Runtime(), _Clock()
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="city;;;;0;;935;;935")
    rt.answers[headermod.WHO_ACTION] = _Outcome(player_card="Player1;;35;;0;;;;0;;0;;0")
    head = _header(rt, clock)
    head.state()
    rt.played.clear()
    for _ in range(1440):                 # an hour of polling at the page's own pace
        clock.now += 2.5
        head.state()
    assert rt.played == [], rt.played
    assert head.state()["age"] > 3500, head.state()   # …and the age says so honestly


def test_only_an_event_takes_a_second_reading() -> None:
    """`mark_stale` is the door the in-client signal will come through — and the only
    one. Nothing in the panel may call it on a timer."""
    rt, clock = _Runtime(), _Clock()
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="city;;;;0;;935;;935")
    rt.answers[headermod.WHO_ACTION] = _Outcome(player_card="Player1;;35;;0;;;;0;;0;;0")
    head = _header(rt, clock)
    head.state()
    rt.played.clear()
    clock.now += 3600
    head.state()
    assert rt.played == [], rt.played
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="world;;UISearch;;1;;935;;935")
    head.mark_stale()                     # something says the player moved
    state = head.state()
    assert [name for name, *_ in rt.played] == [headermod.WHERE_ACTION], rt.played
    assert state["scene"] == "world" and state["age"] == 0, state
    # …and the character is left alone unless the event was about the character.
    assert headermod.WHO_ACTION not in [name for name, *_ in rt.played], rt.played


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
    head.mark_stale()
    clock.now += 30
    state = head.state()
    assert state["scene"] == "world", state          # the old reading, not a blank one
    assert state["age"] >= 30, state


def test_nothing_read_yet_names_no_scene() -> None:
    rt, clock = _Runtime(), _Clock()
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="")
    state = _header(rt, clock).state()
    assert state["scene"] == "" and state["age"] == -1, state
    assert state["nick"] == "" and state["server"] == 0, state


def test_the_character_survives_a_link_that_is_not_there() -> None:
    """#2075: a panel that cannot reach the client draws the account it last read.

    The card was written down on the reading that DID happen, so a closed client, a kick
    or a restart is not «no account» — it is the same account with an old reading.
    """
    card = {"nick": "Player1", "level": 35, "uid": "", "pic_ver": 0}
    rt, clock = _Runtime(_Store(card)), _Clock()
    rt.game.busy = True                       # nothing can be read at all
    state = _header(rt, clock).state()
    assert rt.played == [], rt.played
    assert state["nick"] == "Player1" and state["level"] == 35, state
    # …and the PLACE is not invented from memory: it has moved and nobody knows where.
    assert state["scene"] == "" and state["age"] == -1, state


def test_a_remembered_card_is_a_floor_and_never_a_verdict() -> None:
    """It fills the strip, and the real reading still happens and still wins."""
    rt, clock = _Runtime(_Store({"nick": "Player1", "level": 35})), _Clock()
    rt.answers[headermod.WHO_ACTION] = _Outcome(player_card="Player2;;41;;0;;;;0;;0;;0")
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="city;;;;0;;935;;935")
    state = _header(rt, clock).state()
    assert state["nick"] == "Player2" and state["level"] == 41, state


def test_a_reading_that_came_back_empty_does_not_erase_the_character() -> None:
    """The login screen answers nothing plausibly; that is not «no character»."""
    rt, clock = _Runtime(_Store()), _Clock()
    rt.answers[headermod.WHO_ACTION] = _Outcome(player_card="Player1;;35;;0;;;;0;;0;;0")
    rt.answers[headermod.WHERE_ACTION] = _Outcome(player_place="city;;;;0;;935;;935")
    head = _header(rt, clock)
    head.state()
    rt.answers[headermod.WHO_ACTION] = _Outcome(player_card="")   # kicked, or logged out
    head.mark_stale(place=False, who=True)
    clock.now += 60
    state = head.state()
    assert state["nick"] == "Player1" and state["level"] == 35, state


def test_no_card_written_down_leaves_the_strip_as_empty_as_it_was() -> None:
    rt, clock = _Runtime(_Store()), _Clock()
    rt.game.busy = True
    state = _header(rt, clock).state()
    assert state["nick"] == "" and state["level"] == 0 and state["avatar"] == "", state


def test_entering_the_game_is_what_re_reads_the_character() -> None:
    """The one NEW FACT about a name and a level is a fresh login, and the status poll
    is where it is seen — a transition, never a clock (`CLAUDE.md`)."""
    source = (_REPO / "panel" / "runtime" / "status.py").read_text(encoding="utf-8")
    assert "if playing and self._was_playing is not True:" in source
    assert "rt.header.mark_stale(place=True, who=True)" in source
    assert "self._was_playing = playing" in source


def test_the_route_carries_the_header() -> None:
    """`/api/state` is the one poll the strip rides — never a second one of its own."""
    source = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert '"header": rt.header.state()' in source


def test_a_panel_made_jump_is_the_event_that_refreshes_the_header() -> None:
    """The server in the global header follows a confirmed move, never a timer (#2593)."""
    source = (_REPO / "panel" / "runtime" / "host.py").read_text(encoding="utf-8")
    assert "self.game.on_moved = self.header.mark_stale" in source
    link = (_REPO / "panel" / "runtime" / "link.py").read_text(encoding="utf-8")
    assert 'if answer.get("ok"):' in link and "_call(self.on_moved, None)" in link


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
