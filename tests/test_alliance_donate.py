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

    Stands in for the game: a donate chunk carries `local n=<k>` and fires as many
    presses as there are attempts left, reporting the tally the way the real chunk does
    (`fired=`). `rest` is the server's view and drops by exactly what landed, so a test
    can tell a batch that spent the quota from one that only claimed to.
    """

    def __init__(self, banked: int) -> None:
        self.chunks: list[str] = []
        self.rest = banked

    def __call__(self, chunk, marker=None, settle=1.4):
        self.chunks.append(chunk)
        if "OnResDonateClick" in chunk:
            want = int(chunk.split("local n=", 1)[1].split()[0])
            fired = min(want, self.rest)
            self.rest -= fired
            return ["DON fired=%d" % fired]
        if "GetResDonateRestCount" in chunk:
            return ["DON rest=%d" % self.rest]
        return []

    @property
    def rounds(self) -> int:
        return sum(1 for c in self.chunks if "OnResDonateClick" in c)

    @property
    def reads(self) -> int:
        return sum(1 for c in self.chunks if "GetResDonateRestCount" in c)


def test_press_donate_spends_every_banked_attempt():
    run = FakeRun(banked=7)
    n = al.press_donate(run, use_gold=False, cap=None, settle_after=0)
    assert n == 7, f"expected 7 presses for 7 banked attempts, got {n}"
    assert run.rest == 0, f"expected the quota spent, {run.rest} left"


def test_press_donate_spends_the_quota_in_one_call():
    """The speed-up: a whole quota is ONE chunk, not one chunk per press.

    A round trip into the game VM costs ~0.15 s and the loop inside it is free, so 7
    banked attempts must cost one donate call (plus the read that sizes it and the read
    that confirms it) — not seven.
    """
    run = FakeRun(banked=7)
    al.press_donate(run, use_gold=False, cap=None, settle_after=0)
    assert run.rounds == 1, f"expected 1 donate call for 7 attempts, got {run.rounds}"
    assert run.reads == 2, f"expected 2 count reads (size it, confirm it), got {run.reads}"


def test_press_donate_stops_when_nothing_is_banked():
    run = FakeRun(banked=0)
    n = al.press_donate(run, use_gold=False, cap=None, settle_after=0)
    assert n == 0 and run.rounds == 0, f"nothing banked must press nothing, got {n}"


def test_press_donate_honours_the_cap():
    run = FakeRun(banked=30)
    n = al.press_donate(run, use_gold=False, cap=3, settle_after=0)
    assert n == 3, f"cap=3 must stop at 3 presses, got {n}"
    assert run.rest == 27, f"expected 27 attempts left untouched, got {run.rest}"


def test_press_donate_gives_up_when_a_round_fires_nothing():
    """A count that will not fall must end the run, not spin on it.

    The real hazard of batching is a round that reports zero presses (the client
    refused, the resources ran out) while the count keeps saying attempts are banked.
    """
    class StuckRun(FakeRun):
        def __call__(self, chunk, marker=None, settle=1.4):
            self.chunks.append(chunk)
            if "OnResDonateClick" in chunk:
                return ["DON fired=0"]
            return ["DON rest=%d" % self.rest]

    run = StuckRun(banked=5)
    n = al.press_donate(run, use_gold=False, cap=None, settle_after=0)
    assert n == 0, f"a round that fires nothing must stop the loop, got {n}"
    assert run.rounds == 1, f"expected exactly one attempted round, got {run.rounds}"


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
