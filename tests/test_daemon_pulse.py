r"""«Зелёный» = чанк недавно дошёл до игры — правило, без игры (task #1287).

The daemon could always answer its port while nothing it sent reached the client: 194 of
2 073 «warm» readings in one day were taken over a client that was not up-and-online, and
three of them with no client process at all (`docs/research/daemon-architecture.md` §3).

`tools/lib/daemon_pulse.py` is the rule that replaces the inference, and this pins it:

  * a real errand counts as proof, so a busy daemon never probes at all;
  * a failure adds a reason and a strike and never erases the last success — «nothing has
    landed for a while» and «the last thing to land failed» are different states, and
    only one of them is a reason to leave;
  * the reader decides on the AGE first, on the pid second;
  * **a daemon too old to carry an age is not stale for being old** — a warm daemon runs
    for days, and a fix that needs the thing it fixes to be restarted first is a fix for
    tomorrow's incident.

    C:\Python312\python.exe tests\test_daemon_pulse.py
    python3 tests/test_daemon_pulse.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import daemon_pulse  # noqa: E402
from daemon_pulse import Pulse, verdict  # noqa: E402


class Clock:
    """A hand-wound clock — nothing here may depend on a test being fast."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


def _pulse(idle: float = 10.0, leave: int = 3):
    clock = Clock()
    return Pulse(idle_probe=idle, leave_after=leave, clock=clock), clock


# ---------------------------------------------------------------------------
# stamping
# ---------------------------------------------------------------------------

def test_a_fresh_daemon_has_no_age_and_probes_at_once() -> None:
    pulse, _ = _pulse()
    assert pulse.age() is None
    assert pulse.due(), "nothing has ever landed — go and find out"
    assert pulse.state()["last_ok_age"] is None


def test_a_landed_chunk_is_the_proof_and_resets_the_clock() -> None:
    pulse, clock = _pulse(idle=10.0)
    pulse.ok()
    assert pulse.age() == 0.0
    clock.tick(9.0)
    assert not pulse.due(), "nine seconds of silence is not yet worth a probe"
    clock.tick(2.0)
    assert pulse.due()
    pulse.ok()                                   # an ordinary errand landed
    assert not pulse.due(), "real traffic is the proof — a busy daemon never probes"


def test_a_failure_keeps_the_last_success_and_adds_a_reason() -> None:
    pulse, clock = _pulse()
    pulse.ok()
    clock.tick(5.0)
    pulse.failed(RuntimeError("snapshot failed err=5"))
    assert pulse.age() == 5.0, "a failure is not an erasure of the last success"
    assert "snapshot failed err=5" in pulse.state()["probe_error"]
    assert pulse.misses() == 1


def test_a_success_clears_the_reason_and_the_strikes() -> None:
    pulse, _ = _pulse()
    pulse.failed("no")
    pulse.failed("no")
    assert pulse.misses() == 2
    pulse.ok()
    assert pulse.misses() == 0
    assert pulse.state()["probe_error"] is None


# ---------------------------------------------------------------------------
# leaving
# ---------------------------------------------------------------------------

def test_one_failure_is_not_a_reason_to_leave() -> None:
    """A client mid-restart is unreachable for the better part of a minute."""
    pulse, _ = _pulse(leave=3)
    pulse.failed("client restarting")
    assert not pulse.should_leave()
    pulse.failed("still restarting")
    assert not pulse.should_leave()


def test_three_in_a_row_and_the_daemon_stops_holding_the_port() -> None:
    pulse, _ = _pulse(leave=3)
    for _ in range(3):
        pulse.failed("cannot attach")
    assert pulse.should_leave()


def test_a_success_in_between_starts_the_count_again() -> None:
    pulse, _ = _pulse(leave=3)
    pulse.failed("one")
    pulse.failed("two")
    pulse.ok()
    pulse.failed("one again")
    assert not pulse.should_leave(), "the strikes must be CONSECUTIVE"


# ---------------------------------------------------------------------------
# the reader's verdict
# ---------------------------------------------------------------------------

def test_nothing_answered_is_no_daemon() -> None:
    assert verdict({}) == "none"
    assert verdict({"ok": False}) == "none"


def test_a_recent_chunk_is_live() -> None:
    assert verdict({"ok": True, "warm": True, "pid": 100, "last_ok_age": 1.5},
                   running_pid=100) == "live"


def test_an_old_age_is_stale_however_healthy_everything_else_looks() -> None:
    """The reading the whole task exists for: pid agrees, port answers, nothing lands."""
    reply = {"ok": True, "warm": True, "pid": 100,
             "last_ok_age": daemon_pulse.STALE_AFTER_SEC + 1}
    assert verdict(reply, running_pid=100) == "stale"


def test_one_missed_probe_is_not_stale() -> None:
    """A probe that queued behind a real call proves the very thing being asked."""
    reply = {"ok": True, "warm": True, "pid": 100,
             "last_ok_age": daemon_pulse.IDLE_PROBE_SEC + 0.5}
    assert verdict(reply, running_pid=100) == "live"


def test_a_daemon_on_another_client_is_stale_even_with_a_fresh_age() -> None:
    reply = {"ok": True, "warm": True, "pid": 100, "last_ok_age": 0.2}
    assert verdict(reply, running_pid=200) == "stale"


def test_a_daemon_holding_no_client_at_all_is_stale() -> None:
    reply = {"ok": True, "warm": True, "pid": None, "last_ok_age": 0.2}
    assert verdict(reply, running_pid=200) == "stale"


def test_no_client_running_is_nobodys_fault() -> None:
    reply = {"ok": True, "warm": True, "pid": None, "last_ok_age": 0.2}
    assert verdict(reply, running_pid=None) == "live"


def test_a_daemon_too_old_to_carry_an_age_is_judged_the_old_way() -> None:
    """A warm daemon runs for days; it must not be called dead for predating this."""
    old = {"ok": True, "warm": True, "pid": 100}
    assert verdict(old, running_pid=100) == "live"
    assert verdict(old, running_pid=200) == "stale"


def test_a_daemon_that_never_got_a_client_is_stale() -> None:
    assert verdict({"ok": True, "warm": False, "pid": None}, running_pid=100) == "stale"
    assert verdict({"ok": True, "warm": False, "pid": None}) == "stale"


def test_the_wire_may_say_the_pid_as_a_string() -> None:
    reply = {"ok": True, "warm": True, "pid": "100", "last_ok_age": 0.1}
    assert verdict(reply, running_pid="100") == "live"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
