r"""The boot's readings are spread out, not fired all at once (#2678).

`bus.GAME_READY` is the one moment every push-driven board takes its first reading
(#2633), so all of them read at once: ten chunks inside thirty seconds of a client that
has just got into the game, each one an attach — a suspend of the game's main thread, a
redirect of its RIP and a restore. That first minute is when the client dies; six of
nine measured restarts killed it 59-95 s in (`docs/research/client-crashes.md`), and
#2667 spread the errands for exactly this reason and left the tabs' first readings as
the one burst it did not take.

What is pinned here:

* the first listener is told AT ONCE — a spread that delayed even the first reading
  would be lag with nothing bought for it;
* the rest are booked on the clock, `SPREAD_SEC` apart, each on a name of its own;
* nothing is dropped: every listener is told, in the order it subscribed;
* a listener that unsubscribed before its turn is skipped, not called on a dead tab;
* an ORDINARY topic is still delivered whole and at once — a push, a capture line and a
  collect finishing are events, and `CLAUDE.md` forbids holding those back;
* a bus with no clock (a test, a bare harness) delivers whole, as it always did.

    python3 tests/test_panel_bus_spread.py
    C:\Python312\python.exe tests\test_panel_bus_spread.py
"""
from __future__ import annotations

TIER = "offline"   # no Tk, no game — a stub clock and a list of calls

import importlib
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# `panel.runtime.__init__` pulls in the host and with it Tk; the bus needs neither, so
# the package is stood up as a bare namespace over the same directory.
_pkg = sys.modules.setdefault("panel", types.ModuleType("panel"))
_pkg.__path__ = [str(_REPO / "panel")]
_rt = sys.modules.setdefault("panel.runtime", types.ModuleType("panel.runtime"))
_rt.__path__ = [str(_REPO / "panel" / "runtime")]
bus = importlib.import_module("panel.runtime.bus")


class Clock:
    """`Ticker.arm`'s contract, with the firing left to the test."""

    def __init__(self) -> None:
        self.booked: list = []          # (name, delay_ms, func)

    def arm(self, name: str, delay_ms: int, func) -> None:
        self.booked.append((name, int(delay_ms), func))

    def run_all(self) -> None:
        for _name, _ms, func in list(self.booked):
            func()


def _bus_with_clock():
    clock = Clock()
    return bus.EventBus(widget=None, arm=clock.arm), clock


def test_the_first_reading_is_not_delayed():
    b, clock = _bus_with_clock()
    heard: list = []
    for i in range(4):
        b.subscribe(bus.GAME_READY, lambda _p, i=i: heard.append(i))
    b.publish(bus.GAME_READY)
    assert heard == [0], f"the boot still fired in a burst: {heard}"
    assert len(clock.booked) == 3, "the other three were not booked on the clock"


def test_nothing_is_dropped_and_the_order_is_kept():
    b, clock = _bus_with_clock()
    heard: list = []
    for i in range(4):
        b.subscribe(bus.GAME_READY, lambda _p, i=i: heard.append(i))
    b.publish(bus.GAME_READY)
    clock.run_all()
    assert heard == [0, 1, 2, 3], f"a listener was lost or reordered: {heard}"


def test_they_are_a_spread_apart_and_each_on_its_own_name():
    b, clock = _bus_with_clock()
    for _ in range(4):
        b.subscribe(bus.GAME_READY, lambda _p: None)
    b.publish(bus.GAME_READY)
    gaps = [ms for _n, ms, _f in clock.booked]
    step = int(bus.SPREAD_SEC * 1000)
    assert gaps == [step, 2 * step, 3 * step], f"not one spread apart: {gaps}"
    names = [n for n, _ms, _f in clock.booked]
    assert len(set(names)) == len(names), \
        "two turns share a booking name, so one cancels the other"


def test_a_listener_that_left_is_not_called_on_its_turn():
    b, clock = _bus_with_clock()
    heard: list = []
    b.subscribe(bus.GAME_READY, lambda _p: heard.append("first"))
    off = b.subscribe(bus.GAME_READY, lambda _p: heard.append("gone"))
    b.publish(bus.GAME_READY)
    off()                                  # the tab was switched off in the meantime
    clock.run_all()
    assert heard == ["first"], f"a dead listener was called anyway: {heard}"


def test_an_ordinary_topic_is_still_delivered_whole():
    b, clock = _bus_with_clock()
    heard: list = []
    for i in range(3):
        b.subscribe("something.happened", lambda _p, i=i: heard.append(i))
    b.publish("something.happened")
    assert heard == [0, 1, 2], "an event was held back — only the boot may be spread"
    assert clock.booked == [], "an event booked a delay"


def test_no_clock_means_no_spread():
    """A bare harness has nothing to book on, and every listener is still told."""
    b = bus.EventBus()
    heard: list = []
    for i in range(3):
        b.subscribe(bus.GAME_READY, lambda _p, i=i: heard.append(i))
    b.publish(bus.GAME_READY)
    assert heard == [0, 1, 2]


def test_one_listener_is_never_worth_a_spread():
    b, clock = _bus_with_clock()
    heard: list = []
    b.subscribe(bus.GAME_READY, lambda _p: heard.append(1))
    b.publish(bus.GAME_READY)
    assert heard == [1] and clock.booked == []


def test_a_deaf_listener_does_not_stop_the_rest():
    b, clock = _bus_with_clock()
    heard: list = []

    def _raise(_p):
        raise RuntimeError("the tab is gone")

    b.subscribe(bus.GAME_READY, _raise)
    b.subscribe(bus.GAME_READY, lambda _p: heard.append("after"))
    b.publish(bus.GAME_READY)
    clock.run_all()
    assert heard == ["after"]


def test_only_the_boot_is_on_the_spread_list():
    assert bus.SPREAD_TOPICS == frozenset({bus.GAME_READY}), \
        "an EVENT was put on the spread list — those are answered in seconds or not " \
        "at all (CLAUDE.md, «Nothing starts in a burst»)"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
