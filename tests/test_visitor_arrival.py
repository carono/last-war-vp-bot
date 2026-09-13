r"""A visitor that is still WALKING UP is not an empty queue (#2843).

City visitors are re-created and walk to the gate every time the client enters the
base. Measured live on 2026-09-13 with eight of them queued: at the moment
`scene == city` their models answered `isArrival == nil`, five seconds later `false`,
and at about fifteen seconds all eight `true`. The recipes read their gate a second or
two after the scene switch, so they read a count of zero and pressed nothing — twelve
runs in one day against three presses from the three runs that happened to start in
the base already.

The cure is `TAP <button> xall WITHIN N s` plus a `soon_lua` on the button: a round
that presses nothing asks how many are on their way, and holds on only while that is
above zero. These tests pin both halves — that a queue which is merely not ready yet
is waited out, and that an EMPTY one still costs no waiting at all.

    python3 tests/test_visitor_arrival.py    # standalone, prints PASS/FAIL
    pytest tests/test_visitor_arrival.py     # or under pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "src", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import game_buttons as gb            # noqa: E402
import lua_actions                   # noqa: E402
from lastwar_bot import script_engine as se  # noqa: E402


class FakeGate:
    """A gate that opens after `arrive_after` rounds, with `coming` walking up till then.

    Answers the two chunks an `xall WITHIN` round can send: the gated press (count and
    press in one call) and the `soon_lua` read that follows a round which pressed
    nothing.
    """

    def __init__(self, waiting: int, arrive_after: int, coming: int | None = None) -> None:
        self.waiting = waiting
        self.arrive_after = arrive_after
        self.coming = waiting if coming is None else coming
        self.rounds = 0
        self.soon_reads = 0
        self.presses = 0

    def run(self, chunk, marker=None, settle=1.4, early=False):
        if "ACT gate left=" in chunk:
            self.rounds += 1
            left = self.waiting if self.rounds > self.arrive_after else 0
            out = [f"ACT gate left={left}"]
            if left > 0:
                self.presses += 1
                self.waiting -= 1
                self.coming = max(0, self.coming - 1)
                out.append("ACT fired=1")
            return out
        if marker == "RLUA":
            self.soon_reads += 1
            return [f"RLUA {self.coming}"]
        return []


def _run(script: str, evaluator):
    log: list[str] = []
    ctx = se.Context(hwnd=0, on_event=log.append, evaluator=evaluator)
    ctx.link_checked = True                      # see tests/test_engine_link_gate.py
    se.Interpreter(ctx)._run_block(se.parse_text(script))
    return log


def _fast_poll(fn):
    """Run `fn` with the hold-on nap shortened, so a test never really waits."""
    saved = se.TAP_SOON_POLL_SEC
    se.TAP_SOON_POLL_SEC = 0.01
    try:
        return fn()
    finally:
        se.TAP_SOON_POLL_SEC = saved


def test_parse_within():
    (t,) = se.parse_text("TAP recruit_survivor xall WITHIN 45s")
    assert t.name == "recruit_survivor" and t.count is None and t.within == 45.0
    (plain,) = se.parse_text("TAP recruit_survivor xall")
    assert plain.within == 0.0, "no WITHIN means today's behaviour"


def test_both_visitor_recipes_wait_for_the_walk():
    for name in ("recruit_survivors", "collect_visitor_gifts"):
        body = se.parse_text((_REPO / "src" / "lastwar_bot" / "actions"
                              / f"{name}.md").read_text(encoding="utf-8"))
        taps = [s for s in body if isinstance(s, se.TapStmt)]
        assert taps, f"{name} presses nothing"
        assert all(t.within > 0 for t in taps), (
            f"{name} reads its gate before the visitors have walked up (#2843)")


def test_both_visitor_buttons_can_say_who_is_coming():
    for name in ("recruit_survivor", "collect_visitor_gifts"):
        btn = gb.get(name)
        assert btn.soon_lua, f"{name} cannot tell 'not yet' from 'nobody'"
        assert "not m.isArrival" in btn.soon_lua, f"{name}'s soon count is not the walk"
        assert "m.isArrival and not m.isFinish" in btn.count_lua, (
            f"{name}'s gate must still refuse a visitor that has not arrived")


def test_a_queue_still_walking_is_waited_out():
    # Three visitors, none of them arrived for the first three rounds — the shape of a
    # run that has just switched scene. Without WITHIN this pressed nothing at all.
    ev = FakeGate(waiting=3, arrive_after=3)
    _fast_poll(lambda: _run("TAP recruit_survivor xall WITHIN 45s", ev))
    assert ev.presses == 3, f"expected the queue drained, got {ev.presses} press(es)"
    assert ev.soon_reads >= 3, "the run has to ask who is coming before it waits"


def test_an_empty_queue_costs_no_waiting():
    # Nobody queued and nobody walking: one round, one 'who is coming', and out.
    ev = FakeGate(waiting=0, arrive_after=99, coming=0)
    _fast_poll(lambda: _run("TAP recruit_survivor xall WITHIN 45s", ev))
    assert ev.presses == 0 and ev.rounds == 1, (
        f"an empty base must not be waited on: {ev.rounds} round(s)")
    assert ev.soon_reads == 1, f"expected one soon read, got {ev.soon_reads}"


def test_without_within_nothing_changes():
    ev = FakeGate(waiting=3, arrive_after=3)
    _run("TAP recruit_survivor xall", ev)
    assert ev.presses == 0 and ev.rounds == 1, "a plain xall still stops at a zero gate"
    assert ev.soon_reads == 0, "…and does not ask who is coming"


def test_within_is_refused_where_it_means_nothing():
    for script, why in (("TAP recruit_survivor x3 WITHIN 5s", "a counted press"),
                        ("TAP help_ally_all xall WITHIN 5s", "a button with no soon_lua")):
        try:
            _run(script, FakeGate(waiting=0, arrive_after=0, coming=0))
        except se.ScriptRuntimeError:
            continue
        raise AssertionError(f"WITHIN on {why} must be a clear error")


def test_a_visitor_the_server_has_not_sent_yet_is_nobody_to_wait_for():
    """The queue holds LATER visitors too, and waiting for one waits for nothing.

    Measured live (#2843): a gift entry sat in the queue with a `startTime` 803 seconds
    in the future, `isCreate` unset and every flag nil — the server had scheduled it,
    nobody was outside. Counted as «on the way» it cost every run the whole of its
    `WITHIN` and collected nothing. So all three counts ask whether the visitor's turn
    has COME, and a clock the client would not answer counts everyone rather than hiding
    somebody who is standing there.
    """
    for name in ("visitor_recruit_waiting", "visitor_recruit_coming",
                 "visitor_gift_waiting", "visitor_gift_coming"):
        expr = getattr(lua_actions, name)()
        assert "d.startTime <= __NOW" in expr, f"{name} waits for visitors who are not due"
        assert "__NOW = UITimeManager" in expr, f"{name} has no clock to judge that by"
        assert "__NOW <= 0 or" in expr, f"{name} hides visitors when the clock is silent"
    # …and the press's own gate does not need it: an arrived visitor is due by definition.
    assert "startTime" not in lua_actions.visitor_recruit_pending()


def test_the_coming_count_is_the_same_kinds_as_the_gate():
    # The gift set is derived from the game's own enum by NAME, and both the gate and
    # the walk-up count must be built from that one set — never a second list.
    assert lua_actions._VISITOR_GIFT_SET in lua_actions.visitor_gift_coming()
    assert lua_actions._VISITOR_GIFT_SET in lua_actions.visitor_gift_pending()
    assert "RECRUITMENT" in lua_actions.visitor_recruit_coming()


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
