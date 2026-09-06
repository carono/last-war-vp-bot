r"""The chat runs whatever the farm is doing, and a typed message is never lost (#2594).

The person's rule, in their own words: «Чат должен всегда работать в отдельном потоке и
его действия ничего не должны блокировать и сам он не зависит от работы сценариев
панели» — and, once the log had been read, the sentence that decided the shape of the
lane: **отправка человека не должна теряться.**

THIS FILE OWNS ONE HALF OF THAT: **отправка человека не должна теряться.** The gate,
the `SHARE` declarations and the ranks a press keeps are pinned next door
(`tests/test_panel_chat_thread.py`); what is pinned here is the queue behind the send
button and the promise it makes.

WHAT WAS MEASURED, on `default`'s own `panel.log` over 2026-09-04..06 (55 h). A send was
`play_async(..., human=True)` straight off the widget's command: the box was cleared, the
claim was refused because something else was driving the client, and the log said «занят
— дождись завершения текущего действия». **Eight times in that window the sentence
somebody had typed ceased to exist.** Nothing else in the panel behaves that way —
everything else refused comes back on the next tick of a clock, and a typed sentence has
no next tick.

No Tk, no game, no daemon, no thread left running: the readings are handed in and the
lane is driven a step at a time.

    C:\Python312\python.exe tests\test_chat_lane.py
    python3 tests/test_chat_lane.py
"""
from __future__ import annotations

TIER = "ui"        # no display of its own, but `panel.runtime` imports Tk on the way in

import sys
import time
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools" / "lib"))

from panel.runtime import chat_outbox as outboxmod  # noqa: E402
from panel.runtime import claims  # noqa: E402
from panel.runtime.actions import Outcome  # noqa: E402


# --- the stand-in -----------------------------------------------------------

class _RT:
    """Everything the gate and the lane lean on, and nothing else.

    `plays` is the script the fake `play_now` follows: one entry per call, either an
    `Outcome` or a callable handed the name. Anything past the end of it succeeds, so a
    test writes only the refusals it is about.
    """

    def __init__(self, profile: str = "alice") -> None:
        self.profiles = types.SimpleNamespace(active=profile)
        self.said: list = []
        self.calls: list = []
        self.plays: list = []
        self.log = types.SimpleNamespace(say=self._say)

    def _say(self, tag: str, key: str, **fmt) -> None:
        self.said.append((key, fmt))

    def say(self, tag: str, key: str, **fmt) -> None:
        self._say(tag, key, **fmt)

    def t(self, key: str, **fmt) -> str:
        return f"<{key}>"

    def dbg(self, component: str = "panel"):
        return types.SimpleNamespace(info=lambda *a, **k: None,
                                     warning=lambda *a, **k: None,
                                     error=lambda *a, **k: None,
                                     debug=lambda *a, **k: None)

    def play_now(self, name: str, args=None, *, tag: str = "action",
                 priority: int = claims.SHARED, human: bool = False, cancel=None):
        self.calls.append({"name": name, "args": dict(args or {}),
                           "priority": priority, "human": human})
        at = len(self.calls) - 1
        if at < len(self.plays):
            step = self.plays[at]
            return step(name) if callable(step) else step
        return Outcome(True)

    def keys(self) -> list:
        return [key for key, _fmt in self.said]


def _lane(rt) -> outboxmod.ChatOutbox:
    return outboxmod.ChatOutbox(rt)


def _drain(lane, rt, limit: int = 40) -> None:
    """Run the lane's loop by hand, one message at a time — no thread, no sleep.

    The lane's own `_loop` is three lines around this: it is the RETRY that is worth
    pinning, not `threading.Thread`, and a test that started one would be timing the
    machine it happens to run on.
    """
    for _ in range(limit):
        if not lane._q:
            return
        item = lane._q[0]
        if not lane._carry(item):
            if lane._q and lane._q[0] is item:
                lane._q.popleft()
    raise AssertionError("the lane never emptied — it is retrying for ever")


def _step(lane) -> None:
    """One pass of the loop, retry or not — for a test that wants to interrupt midway."""
    item = lane._q[0]
    if not lane._carry(item):
        if lane._q and lane._q[0] is item:
            lane._q.popleft()


# --- a typed message is never lost ------------------------------------------

def test_a_send_refused_because_the_client_is_busy_waits_and_then_goes():
    """THE PROMISE. «Занят» is not an answer to a person — it is a «not yet» (#2594)."""
    rt = _RT()
    rt.plays = [Outcome(False, "<busy>"), Outcome(False, "<busy>")]
    lane = _lane(rt)
    assert lane.send({"text": "hi"}, "hi", "country_1") is True
    _drain(lane, rt)
    assert len(rt.calls) == 3, f"the lane gave up after {len(rt.calls)} tries"
    assert rt.keys().count("chat.send.waiting") == 2
    assert "chat.send.sent" in rt.keys()
    assert lane.waiting() == 0


def test_the_message_and_its_room_survive_every_retry():
    """A retry re-sends the SAME sentence into the SAME room — not a fresh empty one."""
    rt = _RT()
    rt.plays = [Outcome(False, "<busy>"), Outcome(False, "<busy>")]
    lane = _lane(rt)
    lane.send({"text": "hello there"}, "hello there", "alliance_1")
    _drain(lane, rt)
    for call in rt.calls:
        assert call["args"] == {"text": "hello there", "room": "alliance_1"}, call
        assert call["priority"] == claims.HUMAN, "a person's message was demoted"
        assert call["human"] is True


def test_two_messages_leave_in_the_order_they_were_typed():
    """One queue and one consumer — never two workers racing for the same room."""
    rt = _RT()
    rt.plays = [Outcome(False, "<busy>")]
    lane = _lane(rt)
    lane.send({"text": "first"}, "first", "country_1")
    lane.send({"text": "second"}, "second", "country_1")
    _drain(lane, rt)
    sent = [call["args"]["text"] for call in rt.calls]
    assert sent == ["first", "first", "second"], sent


def test_a_second_message_says_there_is_a_queue_and_the_first_does_not():
    """A line about the plumbing on every press is the noise this codebase relearns."""
    rt = _RT()
    lane = _lane(rt)
    lane.send({"text": "a"}, "a", "country_1")
    assert "chat.send.queued" not in rt.keys()
    lane.send({"text": "b"}, "b", "country_1")
    assert rt.keys().count("chat.send.queued") == 1


def test_a_refusal_the_recipe_itself_gave_is_not_retried():
    """«The game said no» is an answer; asking again would get the same one."""
    rt = _RT()
    rt.plays = [Outcome(False, "the room is not one this client is sitting in")]
    lane = _lane(rt)
    lane.send({"text": "hi"}, "hi", "custom_group_1")
    _drain(lane, rt)
    assert len(rt.calls) == 1, "a scenario's own refusal was retried"
    assert "chat.send.failed" in rt.keys()
    assert "chat.send.waiting" not in rt.keys()


def test_a_send_that_keeps_being_refused_is_given_up_on_out_loud():
    """A hold that outlasts a person's patience ENDS, and says so with the reason."""
    rt = _RT()
    rt.plays = [Outcome(False, "<busy>")] * 4
    lane = _lane(rt)
    lane.send({"text": "hi"}, "hi", "country_1")
    lane._q[0]["at"] = time.monotonic() - outboxmod.HOLD_SEC - 1.0
    _drain(lane, rt)
    assert len(rt.calls) == 1
    assert "chat.send.gave_up" in rt.keys()
    assert lane.waiting() == 0, "a given-up message stayed on the queue for ever"


def test_a_message_typed_under_another_profile_is_never_posted_here():
    """«A profile is a whole panel of its own» — a queue that outlives a switch is #1306."""
    rt = _RT(profile="alice")
    rt.plays = [Outcome(False, "<busy>")]
    lane = _lane(rt)
    lane.send({"text": "hi"}, "hi", "alliance_1")
    _step(lane)                        # one refusal, so it is still queued
    rt.profiles.active = "bob"
    _drain(lane, rt)
    assert len(rt.calls) == 1, "alice's sentence was posted into bob's alliance"
    assert "chat.send.dropped_profile" in rt.keys()


def test_a_send_with_no_room_is_refused_at_the_door():
    """Nowhere to go is REFUSED, never redirected (#2418) — and never queued."""
    rt = _RT()
    lane = _lane(rt)
    assert lane.send({"text": "hi"}, "hi", "") is False
    assert lane.waiting() == 0


# --- what the lane must NOT do ----------------------------------------------

def test_the_lane_holds_no_claim_of_its_own():
    """It owns a queue, not a claim: the chat is never what a farming run waits behind."""
    claims.clear()
    rt = _RT()
    rt.plays = [Outcome(False, "<busy>")]
    lane = _lane(rt)
    lane.send({"text": "hi"}, "hi", "country_1")
    _drain(lane, rt)
    assert claims.held() == {}, claims.held()


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


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
