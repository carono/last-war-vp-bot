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
    cap = float(re.search(r"HARVEST_MAX_SEC = ([0-9.]+)", src).group(1))
    assert claim < cap <= 3600.0, "a harvest that never ends is the account's trading"



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
        self.listeners: list = []

    def listen(self, func):
        self.listeners.append(func)
        return lambda: self.listeners.remove(func)

    def changed(self) -> None:
        for func in list(self.listeners):
            func()

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


class _Tick:
    """`panel/runtime/tick.py` as far as the book uses it: post and one-shot chains."""

    def __init__(self) -> None:
        self.armed: dict = {}
        self.posted: list = []

    def post(self, func) -> None:
        self.posted.append(func)
        func()

    def arm(self, name: str, delay_ms: int, func) -> None:
        self.armed[name] = (delay_ms, func)

    def disarm(self, name: str) -> None:
        self.armed.pop(name, None)


class _Resources:
    def __init__(self) -> None:
        self.asked = 0

    def ask(self) -> None:
        self.asked += 1

    def cached(self) -> dict:
        return {"rows": [], "items": []}

    def state(self) -> dict:
        return self.cached()


class _Bus:
    def __init__(self) -> None:
        self.subs: dict = {}

    def subscribe(self, topic, func):
        self.subs.setdefault(topic, []).append(func)
        return lambda: self.subs[topic].remove(func)

    def publish(self, topic, payload=None) -> None:
        for func in list(self.subs.get(topic, ())):
            func(payload)


class _Wire:
    def __init__(self) -> None:
        self.subs: dict = {}

    def subscribe(self, pattern, func):
        self.subs[pattern] = func
        return lambda: self.subs.pop(pattern, None)

    def say(self, pattern) -> None:
        self.subs[pattern](pattern)


class _Rt:
    def __init__(self) -> None:
        self.wire = _Wire()
        self.bus = _Bus()
        self.interrupts = _Runs()
        self.schedule = _Schedule()
        self.tick = _Tick()
        self.resources = _Resources()


def _book():
    from panel.runtime.resource_book import ResourceBook
    return ResourceBook(_Rt())


def test_every_gain_of_a_harvest_is_counted_and_not_only_the_first():
    """#2746: the claim used to be SPENT by the first gain priced after a run.

    A harvest answers in several bursts, so that counted one of them and left the rest
    in the whole-day tally alone. Measured on the live panel of 2026-09-11: `sooperj`
    collected fifteen times and its base book held 7.66M food where the log's own gain
    lines beside those runs sum to over 11M.
    """
    from panel.runtime import resource_book as rb

    book = _book()
    book.rt.interrupts.names = ["collect_base_resources"]
    assert book.from_base(now=1000.0) is True          # priced while it runs

    late = _book()
    late.rt.interrupts.names = ["collect_base_resources"]
    late.note_running(now=1000.0)        # a push arrives while it runs and prices nothing
    late.rt.interrupts.names = []
    assert late.from_base(now=1000.0 + 100.0) is True, (
        "a gain priced a minute and a half later is still that harvest's")
    # …and so is the one after it, which is the whole of the fix.
    assert late.from_base(now=1000.0 + 150.0) is True, (
        "the second burst of one harvest was dropped")
    assert late.from_base(now=1000.0 + 150.0 + rb.COLLECT_WINDOW_SEC - 1) is True, (
        "a cascade still arriving past the claim is still the harvest's")


def test_a_gain_with_no_harvest_behind_it_is_not_the_bases():
    """A truck, a gift, a chest: the whole-day tally has them and the base's book does
    not. And the window closes — nothing is credited to a harvest that is over."""
    from panel.runtime import resource_book as rb

    book = _book()
    assert book.from_base(now=1000.0) is False

    stale = _book()
    stale.rt.interrupts.names = ["collect_base_resources"]
    stale.note_running(now=1000.0)
    stale.rt.interrupts.names = []
    assert stale.from_base(now=1000.0 + rb.HARVEST_MAX_SEC + 1) is False

    quiet = _book()
    quiet.rt.interrupts.names = ["collect_base_resources"]
    quiet.note_running(now=1000.0)
    quiet.rt.interrupts.names = []
    quiet.from_base(now=1010.0)                         # one burst, and then silence
    assert quiet.from_base(now=1000.0 + rb.COLLECT_CLAIM_SEC
                           + rb.COLLECT_WINDOW_SEC + 1) is False, (
        "the burst window closes and nothing else is credited to that harvest")


def test_a_harvest_that_never_stops_arriving_is_the_accounts_own_trading():
    """The window is held open by the gains themselves, so it needs a ceiling."""
    from panel.runtime import resource_book as rb

    book = _book()
    book.rt.interrupts.names = ["collect_base_resources"]
    book.note_running(now=1000.0)
    book.rt.interrupts.names = []
    now = 1000.0
    while now < 1000.0 + rb.HARVEST_MAX_SEC - rb.COLLECT_WINDOW_SEC:
        now += rb.COLLECT_WINDOW_SEC - 1
        assert book.from_base(now=now) is True
    assert book.from_base(now=1000.0 + rb.HARVEST_MAX_SEC + 1) is False, (
        "an hour of trading would be credited to the base's card")


def test_a_run_nobody_scheduled_still_arms_the_claim():
    """#2746: `/api/actions/run` and a person's press never touch the schedule's record
    of last runs, so a book armed off that record alone credited them nothing. The RUN
    REGISTER is the one signal that does not care who pressed."""
    book = _book()
    book.watch()
    book.rt.interrupts.names = ["collect_base_resources"]
    book.rt.interrupts.changed()
    book.rt.interrupts.names = []
    book.rt.interrupts.changed()
    assert book._collect_at > 0.0, "the register said nothing to the book"
    assert book.from_base() is True


def test_a_reading_is_ASKED_FOR_when_the_harvest_ends():
    """#2746, measured live: `default` harvested six times between 01:03 and 06:06 on
    2026-09-11 and priced NOT ONE of them — nobody had the page open, so the card's ear
    was down and no reading was ever taken to diff against."""
    from panel.runtime import resource_book as rb

    book = _book()
    book.watch()
    book.rt.interrupts.names = ["collect_base_resources"]
    book.rt.interrupts.changed()
    book.rt.interrupts.names = []
    book.rt.interrupts.changed()
    assert len(book.rt.tick.armed) == len(rb.HARVEST_READS), (
        "the harvest ended and no reading was booked")
    for _name, (_delay, func) in sorted(book.rt.tick.armed.items()):
        func()
    assert book.rt.resources.asked == len(rb.HARVEST_READS)

    res = (Path(__file__).resolve().parent.parent
           / "panel" / "runtime" / "resources.py").read_text(encoding="utf-8")
    assert "def ask(" in res, "there is no way to ask for a reading"


def test_a_harvest_made_BY_HAND_in_the_game_is_counted_too():
    """#2746b, the person's words: «Ищи пуши, я могу и в игре руками собрать ресурсы,
    они должны учитываться».

    «Our run was playing» can only ever count the harvests the PANEL made. What says
    «this came off the base» is the game: `building.production.collect`, one frame per
    building, the same whether a thumb taps the green bubble or the panel sweeps.
    """
    from panel.runtime import resource_book as rb

    book = _book()
    book.watch()
    assert rb.COLLECT_COMMAND in book.rt.wire.subs, "nobody is listening for a harvest"
    assert book.from_base() is False               # nothing has happened yet
    book.rt.wire.say(rb.COLLECT_COMMAND)           # …a person taps a bubble
    assert book.from_base() is True, "a hand-made harvest is not counted"
    # …and it books the readings that price it, exactly as the panel's own run does.
    assert len(book.rt.tick.armed) == len(rb.HARVEST_READS)


def test_the_baseline_is_taken_when_the_client_gets_into_the_game():
    """#2746, measured live: the panel came up at 06:41, nothing read the balance until
    a harvest at 07:02:36 asked for one, and that harvest's own gains BECAME the
    baseline — a diff cannot price its first reading, so the whole harvest counted zero.

    `CLAUDE.md`, «A STATISTIC IS NOT REFRESHED BY HAND»: the first reading is taken on
    `bus.GAME_READY` and on nothing else.
    """
    from panel.runtime import bus as busmod

    book = _book()
    book.watch()
    book.rt.bus.publish(busmod.GAME_READY, None)
    assert book.rt.resources.asked == 1, "the appearance took no baseline"


def test_the_book_does_not_depend_on_the_trigger_staying_alive():
    """#2746, measured live: `default`'s `resource_tracker` listener died at 00:42 and
    the tally stopped dead. The register and the reading are the runtime's own."""
    src = (Path(__file__).resolve().parent.parent
           / "panel" / "runtime" / "resource_book.py").read_text(encoding="utf-8")
    assert "book.watch()" in src and "book.listen()" in src, (
        "the book is armed only by the trigger again")
    assert "self.rt.interrupts.listen(" in src


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
