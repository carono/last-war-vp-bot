r"""Daily tally of resources gained — the diff, the day roll, and the file.

`panel.resource_stats` turns a stream of balance readings into a day-keyed tally of
what went UP. Three things must hold: only INCREASES are counted (a spend, and the
first reading with no baseline, add nothing), a new day is a new row rather than a
reset (the history accumulates), and the file round-trips. All pinned here.

No Tk, no game, the day is an argument::

    python3 tests/test_panel_resource_stats.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from panel import resource_stats as rs  # noqa: E402

DAY1 = "2026-07-30"
DAY2 = "2026-07-31"


# -- the diff ---------------------------------------------------------------
def test_only_increases_are_counted():
    last = {"food": 100, "metal": 100, "gold": 100}
    cur = {"food": 150, "metal": 80, "gold": 100}         # food up, metal down, gold flat
    assert rs.positive_deltas(cur, last) == {"food": 50}


def test_no_baseline_means_no_gain():
    # A resource missing from `last` (first reading) is not counted as gained.
    assert rs.positive_deltas({"food": 999}, {}) == {}
    assert rs.positive_deltas({"food": 999}, {"metal": 1}) == {}


def test_junk_values_are_ignored():
    assert rs.positive_deltas({"food": "x"}, {"food": 1}) == {}


# -- the tally + day roll ---------------------------------------------------
def test_gains_accumulate_within_a_day():
    stats = rs.ResourceStats({})
    stats = stats.add({"food": 100}, today=DAY1)
    stats = stats.add({"food": 50, "gold": 5}, today=DAY1)
    assert stats.on(DAY1) == {"food": 150, "metal": 0, "oil": 0, "gold": 5}


def test_a_new_day_is_a_new_row_history_kept():
    stats = rs.ResourceStats({}).add({"food": 100}, today=DAY1)
    stats = stats.add({"food": 30}, today=DAY2)
    assert stats.on(DAY1)["food"] == 100          # yesterday untouched
    assert stats.on(DAY2)["food"] == 30
    assert stats.dates() == [DAY2, DAY1]          # newest first


def test_empty_gains_change_nothing():
    stats = rs.ResourceStats({"2026-01-01": {"food": 5}})
    same = stats.add({}, today=DAY1)
    assert same is stats                          # a spend-only push is a no-op
    # a delta dict with only non-positive values is empty too
    assert stats.add({"food": 0, "metal": -3}, today=DAY1) is stats


def test_an_item_the_base_pays_in_is_kept_beside_the_four():
    # #2744: the tally used to be a fixed set of four columns, and everything else was
    # thrown away. The base also pays in ITEMS — drone parts, gears, the pet's papers —
    # keyed by the game's own item id, so any key that arrives with a gain is written
    # down and the four keep their place only in the ORDER `on` hands them back.
    stats = rs.ResourceStats({}).add({"food": 10, "item:7038": 4}, today=DAY1)
    row = stats.on(DAY1)
    assert row["food"] == 10 and row["item:7038"] == 4
    assert list(row)[:4] == list(rs.RESOURCES)


def test_an_items_gain_is_diffed_exactly_as_a_resources_is():
    assert rs.positive_deltas({"item:7038": 9}, {"item:7038": 5}) == {"item:7038": 4}
    assert rs.positive_deltas({"item:7038": 3}, {"item:7038": 5}) == {}


# -- the file ---------------------------------------------------------------
def test_file_round_trips():
    tmp = Path(tempfile.mkdtemp())
    path = str(tmp / "resource_stats.json")
    rs.save_stats(rs.ResourceStats({}).add({"gold": 7}, today=DAY1), path)
    back = rs.load_stats(path)
    assert back.on(DAY1)["gold"] == 7
    # the file is the documented shape
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    assert raw[DAY1]["gold"] == 7


def test_a_missing_file_loads_empty():
    tmp = Path(tempfile.mkdtemp())
    stats = rs.load_stats(str(tmp / "nope.json"))
    assert stats.dates() == []



# -- the base's own book, and the day it is filed under (#2743) --------------
class _Store:
    def __init__(self) -> None:
        self.blobs: dict = {}

    def blob_get(self, name):
        return self.blobs.get(name)

    def blob_set(self, name, value) -> None:
        self.blobs[name] = value


def test_the_base_tally_is_a_row_of_its_own_and_imports_no_file():
    """What the base paid is not what the day took: two books, never one (#2743).

    A truck coming home, a gift, a chest and a robbery all raise a balance and all land
    in the whole-day tally. The card of «Сбор ресурсов» asks a narrower question, so it
    reads a narrower book — and that book never had a pre-#1465 file to be carried
    across, so `None` is a legal path and imports nothing.
    """
    store = _Store()
    assert rs.BASE_BLOB != rs.STATS_BLOB
    base = rs.load_stats_from_store(store, None, rs.BASE_BLOB)
    assert base.dates() == []
    rs.save_stats_to_store(store, base.add({"metal": 100}, today=DAY1), rs.BASE_BLOB)
    assert store.blobs[rs.BASE_BLOB][DAY1]["metal"] == 100
    assert rs.STATS_BLOB not in store.blobs, "the whole-day tally was not touched"


def test_a_gain_is_filed_under_the_games_day_and_not_this_computers():
    """`CLAUDE.md`, «A DAY'S STATISTIC IS A HISTORY» — the boundary that zeroes the
    counter is the warzone's own reset, so it is the one that names the row (#2743).

    The tracker is on a Tk tab, so what is pinned here is the CALL: it asks the
    profile's own day and hands it to `add`, and the PC's date is only what is left when
    no client has ever answered.
    """
    src = (Path(__file__).resolve().parent.parent
           / "panel" / "runtime" / "resource_book.py").read_text(encoding="utf-8")
    assert "self.rt.day.day_key()" in src, "the tally is keyed by this PC's date again"
    assert ".add(gains, day)" in src, "the day is read and then not used"
    assert "datetime.date.today" not in src


def test_only_a_harvest_the_panel_made_is_credited_to_the_base():
    """Nothing on the wire says where a gain came from, so the panel says what it DID.

    The window is the burst a single press makes — 36 collects and a tail of pushes —
    and nothing wider: a truck arriving a minute later must not land in the base's book.
    """
    src = (Path(__file__).resolve().parent.parent
           / "panel" / "runtime" / "resource_book.py").read_text(encoding="utf-8")
    assert 'COLLECT_ACTION = "collect_base_resources"' in src
    assert "self.rt.interrupts.running()" in src, "the source is guessed rather than read"
    import re
    window = float(re.search(r"COLLECT_WINDOW_SEC = ([0-9.]+)", src).group(1))
    assert 10.0 <= window <= 90.0, "the window is a burst, not a minute of trading"
    claim = float(re.search(r"COLLECT_CLAIM_SEC = ([0-9.]+)", src).group(1))
    assert window < claim <= 600.0, "a stale reading needs longer than a burst"



def test_the_tracker_belongs_to_no_tab():
    """#2743: it was «Статистика»'s method, and that tab is `IN_DEVELOPMENT`.

    Measured on the live panel of 2026-09-10: `resource_tracker` switched ON in all
    three profiles and not one `resource_stats` row in the database — the trigger fired
    into a handler nothing had bound. So the book is the runtime's and the schedule
    binds it whatever tabs a profile has.
    """
    root = Path(__file__).resolve().parent.parent
    tab = (root / "panel" / "tabs" / "stats.py").read_text(encoding="utf-8")
    assert "TRIGGERS" not in tab, "the tab owns the tracker again"
    schedule = (root / "panel" / "runtime" / "schedule.py").read_text(encoding="utf-8")
    assert "resource_book.register(self)" in schedule, "nothing binds the handler"
    book = (root / "panel" / "runtime" / "resource_book.py").read_text(encoding="utf-8")
    assert 'schedule.bind("resource_tracker"' in book
    host = (root / "panel" / "runtime" / "host.py").read_text(encoding="utf-8")
    assert "ResourceBook(self)" in host, "no profile has a book"



class _Runs:
    def __init__(self) -> None:
        self.names: list = []

    def running(self) -> list:
        class _R:
            def __init__(self, name):
                self.name = name
        return [_R(n) for n in self.names]


class _Schedule:
    """The panel's own record of when it last ran an errand (`panel/timers.py`)."""

    def __init__(self) -> None:
        self.runs: dict = {}
        self.store = self

    def last_run(self, name: str) -> float:
        return float(self.runs.get(name, 0.0))


class _Rt:
    def __init__(self) -> None:
        self.interrupts = _Runs()
        self.schedule = _Schedule()


def _book():
    from panel.runtime.resource_book import ResourceBook
    return ResourceBook(_Rt())


def test_a_harvest_is_claimed_by_the_first_gain_priced_after_it():
    """#2743, measured live: the reading a gain is diffed from is served STALE.

    The run finished at 22:32:47, the tracker read at 22:32:53 and still saw the
    pre-harvest numbers, and the fresh reading landed some fifteen seconds later. So the
    run ARMS a claim and the first gain priced within `COLLECT_CLAIM_SEC` spends it —
    a window measured from the run itself threw the harvest away.
    """
    from panel.runtime import resource_book as rb

    book = _book()
    book.rt.interrupts.names = ["collect_base_resources"]
    assert book.from_base(now=1000.0) is True          # priced while it runs

    late = _book()
    late.rt.interrupts.names = ["collect_base_resources"]
    late.note_running(now=1000.0)        # a push arrives while it runs and prices nothing
    late.rt.interrupts.names = []
    assert late.from_base(now=1000.0 + 100.0) is True, \
        "a gain priced a minute and a half later is still that harvest's"

    # …and the rest of the burst rides the window the claim opened.
    assert late.from_base(now=1000.0 + 100.0 + rb.COLLECT_WINDOW_SEC - 1) is True


def test_a_gain_with_no_harvest_behind_it_is_not_the_bases():
    """A truck, a gift, a chest: the whole-day tally has them and the base's book does
    not. And a claim expires — three minutes after the run, nothing is credited."""
    from panel.runtime import resource_book as rb

    book = _book()
    assert book.from_base(now=1000.0) is False

    stale = _book()
    stale.rt.interrupts.names = ["collect_base_resources"]
    stale.note_running(now=1000.0)
    stale.rt.interrupts.names = []
    assert stale.from_base(now=1000.0 + rb.COLLECT_CLAIM_SEC + 1) is False

    spent = _book()
    spent.rt.interrupts.names = ["collect_base_resources"]
    spent.note_running(now=1000.0)
    spent.rt.interrupts.names = []
    spent.from_base(now=1010.0)                         # the claim is spent here
    assert spent.from_base(now=1010.0 + rb.COLLECT_WINDOW_SEC + 1) is False, \
        "the burst window closes and nothing else is credited to that harvest"



def test_the_gain_is_priced_when_the_READING_lands_and_not_when_the_push_does():
    """#2743, measured live: the push and the amount are two different moments.

    `BaseResources` answers out of its cache and refreshes behind the answer, so the
    balance the tracker diffs on the push is the one from BEFORE the harvest. The run
    ended at 22:38:24, the tracker read the stale numbers the same second, and the fresh
    reading landed some fifteen seconds later with no push left to price it — an empty
    book over a base that had just been collected.
    """
    root = Path(__file__).resolve().parent.parent
    res = (root / "panel" / "runtime" / "resources.py").read_text(encoding="utf-8")
    assert "bus.RESOURCES_READ" in res, "a fresh reading tells nobody"
    book = (root / "panel" / "runtime" / "resource_book.py").read_text(encoding="utf-8")
    assert "busmod.RESOURCES_READ" in book, "the tally does not listen for the reading"
    assert "cached=True" in book, \
        "a book that has just been told a reading landed must LOOK, not read again"



def test_a_run_that_has_just_ENDED_still_arms_the_claim():
    """#2743, measured live: the reading lands a second after the run leaves the
    register, so «is it running» alone sees nothing. The panel's own record of the last
    run says the same thing a second later, and that is what arms the claim."""
    from panel.runtime import resource_book as rb

    book = _book()
    book.rt.schedule.runs["collect_base_resources"] = 1000.0
    assert book.from_base(now=1001.0) is True

    old = _book()
    old.rt.schedule.runs["collect_base_resources"] = 1000.0
    assert old.from_base(now=1000.0 + rb.COLLECT_CLAIM_SEC + 1) is False


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
