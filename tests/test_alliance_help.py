r"""Alliance auto-help — what wakes it, and what it sends when it wakes.

The «Авто-помощь союзникам» checkbox (task #1113) keeps an ear on the traffic and fires
one ``al.help.all`` the moment ``push.al.help.new`` lands. Two things in that sentence
can go wrong quietly, and both are tested here:

  * **what wakes it** — only the *inbound* help push. Our own outgoing ``al.help.all``
    must never wake it (that is a loop), and ``push.al.help.update`` is opt-in, since
    the request it refers to was already answered by the press its ``new`` push caused.
  * **what it sends** — nothing at all unless somebody is actually waiting, read from
    *both* gates. The list gate alone is blind to a brand-new request: the push handler
    only bumps the red-point counter and never touches ``GetAllianceHelpList()`` (see
    ``tools/lib/alliance_help.py``), so a helper that trusted the list would sit out
    exactly the request that woke it. Nor is either zero believed on the first read —
    the sniffer decodes the packet before the client has processed it.

No game and no capture: the evaluator is a stub that answers the two Lua reads the
module makes (``list=…num=`` and ``sent=``), and the pushes are hand-built envelopes fed
straight to ``emit``. Run it anywhere::

    python3 tests/test_alliance_help.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import alliance_help  # noqa: E402
import alliance_help_monitor as monitor_mod  # noqa: E402
import lastwar_proto as proto  # noqa: E402


class FakeEval:
    """Evaluator stub: answers the gates from a script, records every press.

    ``gate`` is the sequence of answers the read gives, one per call (the last value
    repeats forever). An entry is either a plain number (the list gate; red point 0), a
    ``(list, red_point)`` pair, or ``None`` for a gate that cannot be read at all.
    """

    def __init__(self, gate, send_error: str | None = None):
        self.gate = list(gate)
        self.send_error = send_error
        self.reads = 0
        self.presses = 0

    def run(self, chunk, marker=None, settle=1.2):
        if "list=" in chunk:
            self.reads += 1
            value = self.gate[min(self.reads, len(self.gate)) - 1]
            if value is None:
                return ["%s list=ERR num=ERR" % alliance_help.MARKER]
            listed, number = value if isinstance(value, tuple) else (value, 0)
            return ["%s list=%s num=%s" % (alliance_help.MARKER, listed, number)]
        if "sent=" in chunk:
            self.presses += 1
            if self.send_error:
                return ["%s sent=ERR:%s" % (alliance_help.MARKER, self.send_error)]
            return ["%s sent=ok" % alliance_help.MARKER]
        raise AssertionError("unexpected chunk: %r" % chunk[:80])


def _push(command: str, **fields):
    """An envelope shaped the way the decoder hands it to ``emit``."""
    return {proto.K_PARAMS: {proto.K_COMMAND: command, proto.K_PARAMS: dict(fields)}}


# -- the press ---------------------------------------------------------------

def test_helps_when_somebody_is_waiting():
    ev = FakeEval(gate=[3])
    assert alliance_help.answer_pending(ev.run, tries=6, gap=0) == 3
    assert ev.presses == 1, "one al.help.all answers the whole list"


def test_a_fresh_request_is_seen_by_the_red_point_alone():
    """The gate that matters for a live push: list 0, counter 1.

    ``PushAlHelpNewMessage`` only does ``SetHelpNum(GetHelpNum()+1)`` — it never adds to
    ``GetAllianceHelpList()``, which is filled by the al.help.all *reply*. A helper that
    gated on the list would therefore decline every request it was woken for, which is
    what a live run actually did before both gates were read.
    """
    ev = FakeEval(gate=[(0, 1)])
    assert alliance_help.answer_pending(ev.run, tries=6, gap=0) == 1
    assert ev.presses == 1, "ignored a request that only the red point knew about"


def test_waits_for_the_client_to_file_the_push():
    """A zero on the first read is the race, not an empty list — keep looking.

    The packet reaches us before ``PushAlHelpNewMessage`` reaches
    ``GetAllianceHelpList()``. Giving up here would decline exactly the request that
    woke the watcher, which is the whole feature.
    """
    ev = FakeEval(gate=[0, 0, (0, 1)])
    assert alliance_help.answer_pending(ev.run, tries=6, gap=0) == 1
    assert ev.reads == 3, ev.reads
    assert ev.presses == 1


def test_quiet_alliance_costs_no_round_trip():
    """Nothing pending after the retries = nothing sent (the #1087 rule)."""
    ev = FakeEval(gate=[0])
    assert alliance_help.answer_pending(ev.run, tries=3, gap=0) == 0
    assert ev.presses == 0, "sent a speculative al.help.all into an empty list"
    assert ev.reads == 3, "gave up before the retry budget was spent"


def test_unreadable_gate_is_not_an_empty_one():
    """Daemon down / game restarting: report it, do not press blind."""
    said = []
    ev = FakeEval(gate=[None])
    assert alliance_help.answer_pending(ev.run, log=said.append, tries=6, gap=0) == 0
    assert ev.presses == 0
    assert ev.reads == 1, "kept retrying an unreachable VM"
    assert said and "unreachable" in said[0], said


def test_failed_press_is_reported_and_counts_as_zero():
    said = []
    ev = FakeEval(gate=[2], send_error="attempt to index a nil value")
    assert alliance_help.answer_pending(ev.run, log=said.append, tries=6, gap=0) == 0
    assert ev.presses == 1
    assert said and "al.help.all failed" in said[0], said


# -- the ear -----------------------------------------------------------------

def _monitor(**kw):
    mon = monitor_mod.AllianceHelpMonitor(**kw)
    mon._wake.clear()
    return mon


def test_only_the_inbound_help_push_wakes_it():
    mon = _monitor()
    mon.emit("down", _push("push.al.help.new", helpId="h1", level=19))
    assert mon._wake.is_set(), "push.al.help.new did not wake the helper"
    assert mon.pushes == 1


def test_our_own_help_never_wakes_it():
    """The up direction carries our own al.help.all — reacting to it is a loop."""
    mon = _monitor()
    mon.emit("up", _push("al.help.all", cmdBaseTime=1785267758008))
    mon.emit("down", _push("al.help.all", allianceId="a"))
    mon.emit("down", _push("push.alliance.march.create", teamUuid=7))
    assert not mon._wake.is_set(), "woken by something that is not a new request"
    assert mon.pushes == 0


def test_update_pushes_are_opt_in():
    mon = _monitor()
    mon.emit("down", _push("push.al.help.update", helpId="h1"))
    assert not mon._wake.is_set(), "an update re-pressed an already-answered request"

    mon = _monitor(with_updates=True)
    mon.emit("down", _push("push.al.help.update", helpId="h1"))
    assert mon._wake.is_set(), "--with-updates did not react to an update"


def test_a_burst_of_requests_is_one_press():
    """Ten requests arriving together are still one al.help.all.

    The worker collects for ``coalesce`` seconds before pressing, so the whole burst is
    answered by the single message that answers the whole list.
    """
    mon = _monitor(coalesce=0.15, cooldown=0.0)
    ev = FakeEval(gate=[5])
    mon._eval = ev
    mon.start()
    try:
        for n in range(10):
            mon.emit("down", _push("push.al.help.new", helpId="h%d" % n))
        deadline = time.time() + 3.0
        while ev.presses == 0 and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.3)          # long enough for a second press to show up if it would
    finally:
        mon.stop()
    assert mon.pushes == 10, mon.pushes
    assert ev.presses == 1, "burst of %d requests cost %d presses" % (10, ev.presses)
    assert mon.helped == 5, mon.helped


def test_a_second_burst_waits_out_the_cooldown():
    """Two separate wake-ups inside the cooldown are still one press until it expires.

    Coalescing alone only merges what arrives in the same 0.4 s window; the cooldown is
    the floor that keeps a busy alliance from turning into a stream of up-frames. Run
    with a 1 s floor so the test does not sit for five.
    """
    assert monitor_mod.COOLDOWN == 5.0, "the documented rate limit changed"
    mon = _monitor(coalesce=0.05, cooldown=1.0)
    ev = FakeEval(gate=[1])
    mon._eval = ev
    mon.start()
    try:
        mon.emit("down", _push("push.al.help.new", helpId="a"))
        _await(lambda: ev.presses == 1)
        mon.emit("down", _push("push.al.help.new", helpId="b"))
        time.sleep(0.4)                      # comfortably inside the 1 s floor
        assert ev.presses == 1, "pressed again before the cooldown was out"
        _await(lambda: ev.presses == 2)
    finally:
        mon.stop()
    assert ev.presses == 2, "the request that arrived during the cooldown was dropped"


def _await(done, timeout: float = 4.0) -> None:
    deadline = time.time() + timeout
    while not done() and time.time() < deadline:
        time.sleep(0.02)


def test_dry_run_sends_nothing():
    mon = _monitor(dry_run=True)
    ev = FakeEval(gate=[4])
    mon._eval = ev
    assert mon.help_now() == 0
    assert ev.presses == 0 and ev.reads == 0, "--dry-run touched the game"


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
