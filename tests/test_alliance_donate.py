r"""Unit tests for the alliance-tech donate core (tools/lib/alliance_science.py).

The loop that spends the daily donate attempts is driven with a *fake* Lua evaluator,
so these need no game, no daemon and no network.

    python3 tests/test_alliance_donate.py    # standalone, prints ok/FAIL
    pytest tests/test_alliance_donate.py     # or under pytest

Exit codes (standalone): 0 = passed, 1 = failed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "tools" / "lib",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import alliance_science as al  # noqa: E402


class FakeRun:
    """Records every chunk; answers a count read with the *real* remaining attempts.

    `rest` is the server's view: it starts at `banked` and drops by one for every press
    that lands, so a test can tell an assumed countdown from a re-read one.
    """

    def __init__(self, banked: int) -> None:
        self.chunks: list[str] = []
        self.rest = banked

    def __call__(self, chunk, marker=None, settle=1.4):
        self.chunks.append(chunk)
        if "GetResDonateRestCount" in chunk:
            return ["DON rest=%d" % self.rest]
        if "OnResDonateClick" in chunk:
            self.rest = max(0, self.rest - 1)
            return ["DON pressed one"]
        return []

    @property
    def presses(self) -> int:
        return sum(1 for c in self.chunks if "OnResDonateClick" in c)

    @property
    def reads(self) -> int:
        return sum(1 for c in self.chunks if "GetResDonateRestCount" in c)


def test_press_donate_spends_every_banked_attempt():
    run = FakeRun(banked=7)
    n = al.press_donate(run, use_gold=False, cap=None, settle_after=0)
    assert n == 7, f"expected 7 presses for 7 banked attempts, got {n}"
    assert run.presses == 7, f"expected 7 press chunks, got {run.presses}"
    assert run.rest == 0, f"expected the quota spent, {run.rest} left"


def test_press_donate_batches_the_count_reads():
    """The speed-up: the count is read once per batch, not before every press.

    One press spends exactly one attempt, so between reads the loop may assume the
    countdown; 7 attempts at a batch of 5 must still cost exactly 7 presses, paid for
    with 2 reads instead of 8.
    """
    run = FakeRun(banked=7)
    al.press_donate(run, use_gold=False, cap=None, settle_after=0, recheck_every=5)
    assert run.presses == 7, f"expected 7 presses, got {run.presses}"
    assert run.reads == 2, f"expected 2 count reads (one per batch of 5), got {run.reads}"


def test_press_donate_stops_when_nothing_is_banked():
    run = FakeRun(banked=0)
    n = al.press_donate(run, use_gold=False, cap=None, settle_after=0)
    assert n == 0 and run.presses == 0, f"nothing banked must press nothing, got {n}"


def test_press_donate_honours_the_cap():
    run = FakeRun(banked=30)
    n = al.press_donate(run, use_gold=False, cap=3, settle_after=0, recheck_every=5)
    assert n == 3, f"cap=3 must stop at 3 presses, got {n}"
    assert run.rest == 27, f"expected 27 attempts left untouched, got {run.rest}"


def test_press_donate_recheck_every_zero_is_treated_as_one():
    """A bad `recheck_every` must not turn into a division by zero or a read-free loop."""
    run = FakeRun(banked=3)
    n = al.press_donate(run, use_gold=False, cap=None, settle_after=0, recheck_every=0)
    assert n == 3, f"expected 3 presses, got {n}"
    assert run.reads == 4, f"recheck_every=0 must read every press (+1 to stop), got {run.reads}"


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
