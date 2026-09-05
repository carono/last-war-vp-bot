r"""The base's live resource stock — the parse, the ordering and the refresh rule.

`panel.runtime.resources` is the one door between the front page and
`actions/read_base_resources.md`. Four things must hold, and each of them was a way the
card could have lied:

* the scenario's line parses into rows, and a malformed record is DROPPED rather than
  half-read (five fields under six headings is a wrong number, not a missing one);
* the pending-to-collect figure survives the parse — it is the half of the card a
  person can act on;
* the biggest stock sorts first, so a card does not open with two season resources
  sitting at zero while gold is below the fold;
* a poll inside the TTL costs no play of the scenario — this route is asked every 2.5 s
  by an open page and the game link is exclusive;
* a play that answers nothing leaves the PREVIOUS rows standing, with their age
  climbing. «Read failed» and «the base is empty» must never draw the same.

No Tk, no game, no clock of its own — the time is an argument::

    python3 tests/test_panel_base_resources.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from panel.runtime import resources as res  # noqa: E402

#: A reading of the shape the scenario really answers with, with invented amounts.
LINE = ("1;;1000;;0;;0;;1;;77;;Metal #|# "
        "14;;2000;;0;;250;;1;;300;;Food #|# "
        "15;;30;;0;;0;;0;;0;;Diamonds #|# "
        "11;;5;;200;;0;;1;;0;;Water")


class _FakeGate:
    def __init__(self, held: str = "") -> None:
        self.held = held

    def blocks(self, _name, human=False):     # noqa: D401 — the runtime's own shape
        return self.held


class _Clock:
    """A hand-wound clock, so the TTL and the age are pinned without sleeping."""

    def __init__(self, at: float = 1000.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


class _FakeLink:
    busy = False


class _FakeWire:
    """The profile's shared ear (`panel/runtime/wire.py`), counted rather than run."""

    def __init__(self) -> None:
        self.subs = 0
        self.live = 0
        self.fire = None

    def subscribe(self, _pattern, on_fire):
        self.subs += 1
        self.live += 1
        self.fire = on_fire

        def off():
            self.live -= 1
        return off


class _FakeTick:
    THREADED = True

    def __init__(self) -> None:
        self.armed = {}

    def arm(self, name, _delay_ms, func):
        self.armed[name] = func

    def disarm(self, name):
        self.armed.pop(name, None)


class _FakeRuntime:
    """Just enough of a PanelRuntime: a gate, a link, and a play that records."""

    def __init__(self, answer: str = LINE, started: bool = True) -> None:
        self.gate = _FakeGate()
        self.game = _FakeLink()
        self.wire = _FakeWire()
        self.tick = _FakeTick()
        self.answer = answer
        self.started = started
        self.plays = 0

    def play_async(self, name, args=None, **kw):
        self.plays += 1
        if not self.started:
            return False
        on_result = kw.get("on_result")
        if on_result is not None:
            on_result(_Outcome(self.answer))
        return True


class _Ctx:
    def __init__(self, answer: str) -> None:
        self.vars = {"resources": answer}


class _Outcome:
    def __init__(self, answer: str) -> None:
        self.ok = True
        self.ctx = _Ctx(answer)


# -- the parse ---------------------------------------------------------------
def test_a_record_becomes_a_row():
    rows = res.parse(LINE)
    by_type = {row["type"]: row for row in rows}
    assert by_type[14]["name"] == "Food"
    assert by_type[14]["count"] == 2000
    assert by_type[14]["per_hour"] == 250
    assert by_type[11]["max"] == 200
    assert by_type[15]["base"] is False
    assert by_type[1]["pending"] == 77       # standing uncollected in the buildings


def test_a_malformed_record_is_dropped_not_half_read():
    rows = res.parse("1;;1000;;0;;0;;1;;77;;Metal #|# 14;;2000;;0 #|#  #|# x;;y;;z;;a;;b;;c;;d")
    assert [row["type"] for row in rows] == [1]


def test_nothing_read_is_no_rows():
    assert res.parse("") == []
    assert res.parse(None) == []


def test_the_biggest_stock_comes_first():
    order = [row["type"] for row in res.parse(LINE)]
    # 2000 food, 1000 metal, 30 diamonds, 5 water. Not «what the base produces first»:
    # water is produced and sits at zero all season, and gold is not produced at all and
    # is the biggest number on the card.
    assert order == [14, 1, 15, 11]


# -- the refresh rule --------------------------------------------------------
def test_the_first_look_reads_and_the_next_one_does_not():
    rt, clock = _FakeRuntime(), _Clock()
    stock = res.BaseResources(rt, clock)
    first = stock.state()
    assert rt.plays == 1
    assert len(first["rows"]) == 4
    clock.at += res.SAFETY_SEC - 1
    stock.state()
    assert rt.plays == 1, "with no push, a balance has not moved — do not re-read it"


# -- the wire is the update --------------------------------------------------
def test_a_push_is_what_re_reads_it():
    rt, clock = _FakeRuntime(), _Clock()
    stock = res.BaseResources(rt, clock)
    stock.state()
    assert rt.plays == 1
    clock.at += res.MIN_GAP_SEC + 1
    stock.state()
    assert rt.plays == 1, "nothing said the balance moved"
    rt.wire.fire("push.resource.item.update")     # the game says it did
    stock.state()
    assert rt.plays == 2


def test_a_burst_of_pushes_costs_one_read():
    rt, clock = _FakeRuntime(), _Clock()
    stock = res.BaseResources(rt, clock)
    stock.state()
    for _ in range(25):                           # one harvest = 25 collect replies
        rt.wire.fire("push.resource.item.update")
        stock.state()
    assert rt.plays == 1, "the floor between reads is what makes a harvest affordable"
    clock.at += res.MIN_GAP_SEC + 1
    stock.state()
    assert rt.plays == 2


def test_the_ear_goes_up_once_and_comes_back_down():
    rt, clock = _FakeRuntime(), _Clock()
    stock = res.BaseResources(rt, clock)
    stock.state()
    stock.state()
    assert rt.wire.subs == 1 and rt.wire.live == 1
    assert res.WATCH_CHAIN in rt.tick.armed
    clock.at += res.WATCH_IDLE_SEC + 1            # nobody has looked since
    rt.tick.armed[res.WATCH_CHAIN]()
    assert rt.wire.live == 0, "a page nobody is on must not hold a capture open"
    assert res.WATCH_CHAIN not in rt.tick.armed


def test_a_push_during_a_read_is_not_lost():
    rt, clock = _FakeRuntime(), _Clock()
    stock = res.BaseResources(rt, clock)
    stock.state()                                  # read 1
    rt.wire.fire("push.resource.item.update")      # …describing what read 1 may have missed
    clock.at += res.MIN_GAP_SEC + 1
    stock.state()
    assert rt.plays == 2


def test_a_stale_reading_is_refreshed():
    rt, clock = _FakeRuntime(), _Clock()
    stock = res.BaseResources(rt, clock)
    stock.state()
    clock.at += res.SAFETY_SEC + 1
    stock.state()
    assert rt.plays == 2


def test_a_held_gate_is_not_pressed_into():
    rt, clock = _FakeRuntime(), _Clock()
    rt.gate.held = "gate.held"
    stock = res.BaseResources(rt, clock)
    answer = stock.state()
    assert rt.plays == 0
    assert answer["rows"] == []
    assert answer["age"] == -1, "nothing read yet is not a stock of zero"


def test_a_refusal_backs_off_instead_of_filling_the_log():
    rt, clock = _FakeRuntime(started=False), _Clock()
    stock = res.BaseResources(rt, clock)
    stock.state()
    clock.at += 1
    stock.state()
    assert rt.plays == 1, "a refusal every 2.5 s IS the log the page was opened to read"
    clock.at += res.RETRY_SEC
    stock.state()
    assert rt.plays == 2, "…and it must ask again once the wait is over"


def test_a_busy_link_holds_the_sweep_back_but_not_a_reading_somebody_asked_for():
    """#2418 reversed half of this, and the half it reversed is the whole bug.

    «A busy link is not pressed into» was pinned here for every read alike. On the live
    panel the link is busy almost continuously, so the FIRST read was refused every time
    and the card was blank for days with nothing saying why. A page being opened is a
    press, and a press waits its turn; a clock is not, and still gives up.
    """
    # Nothing has ever been read: somebody opened the page, so it goes in and waits.
    rt, clock = _FakeRuntime(), _Clock()
    rt.game.busy = True
    stock = res.BaseResources(rt, clock)
    assert stock.state()["rows"], "the first reading was refused because the link was busy"
    assert rt.plays == 1

    # …and once there are numbers on the card, the safety clock alone does not press in.
    clock.at += res.SAFETY_SEC + 1
    stock._dirty = False
    before = rt.plays
    stock.state()
    assert rt.plays == before, "the safety sweep pressed into a busy link"


def test_an_empty_answer_keeps_the_rows_that_were_there():
    rt, clock = _FakeRuntime(), _Clock()
    stock = res.BaseResources(rt, clock)
    stock.state()
    rt.answer = ""                                   # the client answered nothing
    clock.at += res.SAFETY_SEC + 1
    later = stock.state()
    assert len(later["rows"]) == 4, "a failed read is not an empty base"
    assert later["age"] > res.SAFETY_SEC, "…and the age says the reading is old"


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



def test_a_reading_somebody_asked_for_waits_its_turn_instead_of_being_refused():
    """#2418: «запас базы» was blank from 2 September, and nothing said why.

    The read gave up whenever the link was busy and tried again in fifteen seconds. On
    the live panel timers, rallies and sweeps hold the link almost continuously, so it
    was refused EVERY time — and a DETACHED play cannot queue by construction either:
    `host.py::play_async` only hangs a demand on the door when the priority outranks the
    run holding the client, and DETACHED outranks nothing.

    So the priority now says who asked. A page opened or a balance the GAME announced is
    a press by the same contract every screen keeps (`web/api.py::_look`) and waits its
    turn; the safety clock stays DETACHED and is still refused, which is right — nobody
    is waiting on it. Neither path is a poll: the queue is a look and an event, exactly
    as before.
    """
    src = (_REPO_ROOT / "panel" / "runtime" / "resources.py").read_text(encoding="utf-8")
    body = src.split("def _maybe_refresh")[1].split("def _from_run")[0]
    assert "asked = bool(not self._at or self._dirty)" in body, \
        "the read no longer knows whether anybody asked for it"
    assert "if not asked:" in body and "if self._rt.game.busy:" in body, \
        "either every read gives up on a busy link again, or none of them does"
    assert "claims.HUMAN if asked" in body, \
        "a reading somebody asked for is queued where it cannot wait"
    assert "claims.DETACHED" in body, "the safety sweep stopped being the humble one"
    # …and it is still not a clock: nothing here arms a timer of its own.
    assert "tick.arm" not in body and "Timer(" not in body, \
        "the stock read grew a poll"



def test_the_reservation_is_given_back_on_every_road_out():
    """#2418, the root of it: a reservation with no way out.

    `_reading` is set before the play and cleared by its result. It was cleared on the
    refusal and on the answer — and NOT when `play_async` itself raised, and not when the
    answer never came. Either leaves the flag True, and `_maybe_refresh` returns at its
    first line for as long as the panel runs: one missed escape and the card never reads
    again. That is why the base stock was blank from 2 September.
    """
    # A play that raises on the way in leaves nothing behind.
    rt, clock = _FakeRuntime(), _Clock()

    def boom(*_a, **_k):
        raise RuntimeError("no link")

    rt.play_async = boom
    stock = res.BaseResources(rt, clock)
    stock.state()
    assert stock._reading is False, "a play that raised left the card reserved for ever"

    # A play whose answer never arrives is not believed past READ_LOST_SEC.
    rt2, clock2 = _FakeRuntime(), _Clock()
    rt2.play_async = lambda *a, **k: True          # accepted, and never answers
    stock2 = res.BaseResources(rt2, clock2)
    stock2.state()
    assert stock2._reading is True, "the play was not marked in flight at all"
    clock2.at += res.READ_LOST_SEC - 1
    plays = [0]
    def counting(*_a, **_k):
        plays[0] += 1
        return True
    rt2.play_async = counting
    stock2.state()
    assert plays[0] == 0, "a play in flight was asked for a second time straight away"
    clock2.at += 2
    stock2.state()
    assert plays[0] == 1, "a play whose answer never came wedged the card for ever"


def test_a_refusal_backs_off_to_a_ceiling_and_never_gives_up():
    """A refusal is «later», never «never» — and «later» has a ceiling (#2418).

    Asking again every fifteen seconds writes the refusal into the log more often than
    the reading it is failing to take; asking never is the bug this thread is about. So
    the gap doubles up to :data:`RETRY_MAX_SEC`, and one success starts it over.
    """
    rt, clock = _FakeRuntime(started=False), _Clock()
    stock = res.BaseResources(rt, clock)
    gaps = []
    for _ in range(12):
        before = stock._hold_until
        stock.state()
        if stock._hold_until > before:
            gaps.append(round(stock._hold_until - clock.at, 3))
        clock.at = stock._hold_until + 0.001
    assert gaps[0] == res.RETRY_SEC, gaps
    assert gaps[1] > gaps[0], "the gap does not grow"
    assert max(gaps) <= res.RETRY_MAX_SEC, "the backoff has no ceiling"
    assert gaps[-1] == res.RETRY_MAX_SEC, "the backoff stopped short of its ceiling"
    # …and it never stops trying: every one of those was another attempt.
    assert rt.plays == len(gaps), "the card gave up instead of retrying later"
    # A reading that gets through starts the backoff over.
    rt.started = True
    clock.at = stock._hold_until + 1
    stock.state()
    assert stock._refusals == 0, "a success did not clear the backoff"


def test_every_named_sprite_is_a_bare_name_and_a_missing_one_draws_a_letter():
    """#2418: «картинки ресурсов не прогружаются».

    The map is what the route is asked for, and the route resolves a BARE sprite name
    inside one folder (`item_icons.raw_named`). A path or a suffix in it is a 404 that
    looks exactly like «not extracted», which is the shape the live bug had.

    The other half is honesty about what cannot be drawn: a type whose picture was never
    extracted on this machine answers `""` and the pill draws the resource's own letter.
    Water is the standing example — its config names no `big_icon` at all and no sprite
    of the name it falls back to exists anywhere in the client's index — and it must
    never borrow another resource's art.
    """
    import json
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "tools", "data", "resource_icons.json"),
              encoding="utf-8") as handle:
        icons = (json.load(handle) or {}).get("icons") or {}
    assert icons, "the map is empty"
    for type_id, stem in icons.items():
        assert str(type_id).isdigit(), type_id
        assert stem == os.path.basename(stem), f"{stem} is a path, not a sprite name"
        assert not stem.lower().endswith(".png"), f"{stem} carries a suffix"
    assert len(set(icons.values())) == len(icons), \
        "two resources share one picture — one of them is wearing the other's art"
    # …and a stem nothing was extracted for is no picture rather than a broken link.
    res._ICONS = None
    saved = sys.modules.get("item_icons")
    class _Nothing:
        @staticmethod
        def raw_named(_name):
            return None
    sys.modules["item_icons"] = _Nothing
    try:
        assert res._icon_for(next(iter(icons))) == ""
    finally:
        if saved is not None:
            sys.modules["item_icons"] = saved
        else:
            sys.modules.pop("item_icons", None)
        res._ICONS = None


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
