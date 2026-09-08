r"""«Сверкающий рынок»: the reading is kept, and NOTHING asks for it on a clock (#2636).

The event has no page of its own, so the only thing that can take a reading is the
runtime's own ear. What is pinned here is what that ear must not be allowed to become:

  * a reading is taken when the CLIENT gets into the game and when the event's own push
    says the score moved — and by nothing else. There is no timer here, no `after`, no
    interval, and no route that re-reads because somebody looked at a page;
  * a burst of one push costs ONE reading — the debounce holds, and a reading already
    out is never doubled;
  * a line that came back is parsed for its numbers AND for the free item's name, which
    is text and has spaces in it, so it lives at the end of the line;
  * and the two errands are on the schedule with the switches the rules ask for: the free
    half ON, the half that spends coins OFF.

Needs no display, no game and no database:

    python3 tests/test_market_live.py
"""
from __future__ import annotations

TIER = "unit"

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "tools" / "lib", ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


def _module(path: Path, name: str):
    """Load one file as a module, without importing its package (Tk is not here)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


from panel.runtime import bus as busmod           # noqa: E402 — path wired up above
from panel.runtime import claims as claimsmod     # noqa: E402
from panel.runtime import market_live as market   # noqa: E402

LINE = ("open=1 starts=1788832800 ends=1789351199 restock=1788919200 free=1 "
        "goods_free=118 priced_rows=21 coins=1000 score=0 top=10000 boxes_due=0 "
        "free_count=1 free_item=100 бриллиантов")


class _Store:
    def __init__(self) -> None:
        self.blobs: dict = {}

    def blob_get(self, name: str):
        return self.blobs.get(name)

    def blob_set(self, name: str, value) -> None:
        self.blobs[name] = value


class _Bus:
    def __init__(self) -> None:
        self.subs: dict = {}

    def subscribe(self, topic, func):
        self.subs.setdefault(topic, []).append(func)
        return lambda: self.subs[topic].remove(func)

    def publish(self, topic, payload=None):
        for func in list(self.subs.get(topic, ())):
            func(payload)


class _Wire(_Bus):
    pass


class _Runtime:
    def __init__(self) -> None:
        self.store = _Store()
        self.bus = _Bus()
        self.wire = _Wire()
        self.plays: list = []

    def dbg(self, _tag):
        class _Log:
            def error(self, *_a, **_k):
                pass
        return _Log()

    def play_async(self, name, args=None, **kw):
        self.plays.append((name, kw.get("tag"), kw.get("priority")))
        return True


# -- the line ----------------------------------------------------------------------
def test_the_numbers_and_the_name_both_come_back():
    got = market.parse(LINE)
    assert got["open"] == 1, got
    assert got["goods_free"] == 118, got
    assert got["ends"] == 1789351199, got
    # the free item is TEXT with a space in it, which is why it is last on the line
    assert got["free_item"] == "100 бриллиантов", got


def test_an_unreadable_line_is_an_empty_reading_and_never_a_crash():
    assert market.parse("") == {}
    assert market.parse(None) == {}
    assert market.parse("rubbish") == {}


def test_a_reading_that_was_never_taken_has_no_age():
    rt = _Runtime()
    fields, age = market.state(rt)
    assert fields == {} and age is None, (fields, age)


def test_a_kept_reading_comes_back_with_its_age():
    rt = _Runtime()
    market.record(rt, LINE)
    fields, age = market.state(rt)
    assert fields["coins"] == 1000, fields
    assert age is not None and age >= 0, age


# -- the ear -----------------------------------------------------------------------
def test_the_client_entering_the_game_takes_the_first_reading():
    rt = _Runtime()
    market.MarketWatch(rt).start()
    assert not rt.plays, "nothing may be read before the client is up"
    rt.bus.publish(busmod.GAME_READY)
    assert [p[0] for p in rt.plays] == [market.ACTION], rt.plays
    assert rt.plays[0][2] == claimsmod.BACKGROUND, rt.plays


def test_a_burst_of_pushes_costs_one_reading():
    rt = _Runtime()
    watch = market.MarketWatch(rt)
    watch.start()
    for _ in range(5):
        rt.wire.publish(market.PUSH)
    assert len(rt.plays) == 1, rt.plays


def test_there_is_no_clock_anywhere_in_the_ear():
    """The whole point of #2633: a statistic is not refreshed by hand OR on a timer."""
    source = (ROOT / "panel" / "runtime" / "market_live.py").read_text(encoding="utf-8")
    for banned in ("tick.arm", "after(", "threading.Timer", "Thread(", "while True"):
        assert banned not in source, banned


# -- the schedule ------------------------------------------------------------------
def test_the_free_half_is_on_and_the_spending_half_is_off():
    from panel import timers                      # noqa: PLC0415 — one import, here

    rows = {t.name: t for t in timers.DEFAULT_TIMERS}
    free = rows["collect_glittering_market"]
    paid = rows["buy_glitter_market_goods"]
    assert free.enabled is True, "the free half spends nothing and ships on (#2390)"
    assert paid.enabled is False, "a coin does not come back — it ships off (#2390)"
    assert free.scenario == ("collect_glittering_market",), free.scenario
    assert paid.scenario == ("buy_glitter_market_goods",), paid.scenario


def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    bad = 0
    for t in tests:
        try:
            t()
            print("  ok  ", t.__name__)
        except Exception as exc:                  # noqa: BLE001 — a test runner
            bad += 1
            print("  FAIL", t.__name__, "->", exc)
    print(f"\n{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
