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
    assert window < claim <= 120.0, (
        "a stale reading needs longer than a burst — and a claim wide enough to hold "
        "another errand's resource packs is how the card came out three times over "
        "(#2746e)")
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
        self.seq = 1
        self.vars: dict = {}

    def listen(self, func):
        self.listeners.append(func)
        return lambda: self.listeners.remove(func)

    def changed(self) -> None:
        for func in list(self.listeners):
            func()

    def running(self) -> list:
        class _Ctx:
            def __init__(self, vars):
                self.vars = vars

        class _R:
            def __init__(self, name, seq, vars):
                self.name = name
                self.seq = seq
                self.ctx = _Ctx(vars)
        # …CARRYING WHAT THE HARVEST SAID IT WAS ABOUT TO COLLECT (#2747). The real
        # register hands out `Run`s, and the size the sweep read off the game before it
        # pressed anything lives in `run.ctx.vars` — a fake that leaves it out cannot
        # tell whether the budget is armed at all.
        return [_R(n, self.seq, dict(self.vars)) for n in self.names]


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
        self.data: dict = {"rows": [], "items": []}

    def ask(self) -> None:
        self.asked += 1

    def cached(self) -> dict:
        return self.data

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
    assert late.from_base(now=1000.0 + rb.COLLECT_CLAIM_SEC - 10.0) is True, (
        "a gain priced while the claim is open is still that harvest's")
    # …and so is the one after it, which is the whole of the fix.
    assert late.from_base(now=1000.0 + rb.COLLECT_CLAIM_SEC - 1.0) is True, (
        "the second burst of one harvest was dropped")
    assert late.from_base(now=1000.0 + rb.COLLECT_CLAIM_SEC
                          + rb.COLLECT_WINDOW_SEC - 2.0) is True, (
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


def test_the_baseline_is_booked_at_START_UP_and_not_only_on_the_edge():
    """#2747, measured live: the panel was restarted at 09:46:38, the first reading did
    not land until 09:49:02, and the harvest at 09:48:38 became the baseline.

    One `ask` at the busiest moment a panel ever has is refused by the link and never
    asked again, so the baseline rides the same one-shot chain a harvest uses."""
    from panel.runtime import resource_book as rb

    book = _book()
    book.watch()
    assert len(book.rt.tick.armed) == len(rb.HARVEST_READS), (
        "the panel came up and booked no reading to diff against")
    for _name, (_delay, func) in sorted(book.rt.tick.armed.items()):
        func()
    assert book.rt.resources.asked == len(rb.HARVEST_READS)


def test_the_baseline_is_taken_when_the_client_gets_into_the_game():
    """#2746, measured live: the panel came up at 06:41, nothing read the balance until
    a harvest at 07:02:36 asked for one, and that harvest's own gains BECAME the
    baseline — a diff cannot price its first reading, so the whole harvest counted zero.

    `CLAUDE.md`, «A STATISTIC IS NOT REFRESHED BY HAND»: the first reading is taken on
    `bus.GAME_READY` and on a link that came back, never on a clock. Since #2747 it
    books the one-shot chain rather than a single `ask`, because one ask at the busiest
    moment a panel ever has is refused by the link and never asked again.
    """
    from panel.runtime import bus as busmod
    from panel.runtime import resource_book as rb

    book = _book()
    book.watch()
    book.rt.tick.armed.clear()                 # the start-up booking, already proved
    book.rt.bus.publish(busmod.GAME_READY, None)
    assert len(book.rt.tick.armed) == len(rb.HARVEST_READS), (
        "the appearance took no baseline")
    for _name, (_delay, func) in sorted(book.rt.tick.armed.items()):
        func()
    assert book.rt.resources.asked == len(rb.HARVEST_READS)


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


def test_another_errands_resource_packs_are_not_the_bases():
    """#2746e, measured live on 2026-09-11 — the over-count that replaced the under-count.

    `collect_base_resources` ran at 08:16:16. `heal_units` opened resource packs to pay
    for the heal at 08:16:55, and the packs' gains landed 154 s and 183 s after the
    harvest. With a three-minute claim both were credited to the base's card: 32.5M food
    that no building had produced, on a day whose real harvest was about 13M.
    """
    book = _book()
    book.rt.interrupts.names = ["collect_base_resources"]
    book.note_running(now=1000.0)
    book.rt.interrupts.names = []
    assert book.from_base(now=1000.0) is True, "the harvest's own gain"
    # …and then a long silence while the heal opens its packs, and their gains:
    assert book.from_base(now=1000.0 + 154.0) is False, (
        "a heal's resource packs are not what the base's buildings produced")
    assert book.from_base(now=1000.0 + 183.0) is False


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


# -- how much of what follows is the harvest's (#2747) ------------------------
def test_the_harvest_states_its_own_size_before_it_presses_anything():
    """The scenario reads `GetBuildingCurrStorage` BEFORE the sweep and says so.

    Without it the panel only knows WHEN a harvest happened, never how big it was, and
    every prize that lands in the window is charged to the base.
    """
    src = (Path(__file__).resolve().parent.parent / "src" / "lastwar_bot" / "actions"
           / "collect_base_resources.md").read_text(encoding="utf-8")
    assert "INTO harvest_pending" in src, "the sweep does not say what it is worth"
    assert src.index("INTO harvest_pending") < src.index("TAP collect_base_resources"), (
        "the size has to be read BEFORE a single building is collected")
    assert "GetBuildingCurrStorage" in src


def test_a_prize_landing_inside_the_window_is_not_the_bases():
    """#2747, measured on the live panel of 2026-09-11: the base's card showed 34
    «Запчастей дрона» where the base makes about seven a day.

    `collect_base_resources` ended at 08:44:37 and 08:54:07; two arms-race prizes of
    twenty drone parts each landed at 08:45:44 and 08:55:50 — outside the minute's claim
    and inside the burst chain behind it, so both were credited to the base.
    """
    book = _book()
    book.watch()
    book.rt.interrupts.vars = {"harvest_pending": "14=1000 #|# i7038=1"}
    book.rt.interrupts.names = ["collect_base_resources"]
    book.rt.interrupts.changed()
    book.rt.interrupts.names = []
    book.rt.interrupts.changed()

    assert book._budget == {"food": 1000, "item:7038": 1}, "the budget was not armed"
    assert book._claim({"food": 1000, "item:7038": 1}) == {"food": 1000, "item:7038": 1}
    # …and the prize that arrives a minute later, inside the window, gets nothing.
    assert book._claim({"item:7038": 20}) == {}, (
        "an arms-race prize was charged to the base's production")
    assert book._claim({"item:630011": 20}) == {}, (
        "a chest the base never makes has no budget at all")


def test_a_harvest_bigger_than_it_said_is_still_capped():
    """A cascade that keeps arriving cannot pay more than the buildings were holding."""
    book = _book()
    book.watch()
    book.rt.interrupts.vars = {"harvest_pending": "1=500"}
    book.rt.interrupts.names = ["collect_base_resources"]
    book.rt.interrupts.changed()
    assert book._claim({"metal": 300}) == {"metal": 300}
    assert book._claim({"metal": 300}) == {"metal": 200}, "the budget is spent, not reset"
    assert book._claim({"metal": 300}) == {}


def test_one_sweep_arms_one_budget_however_many_frames_it_makes():
    """36 buildings is 36 `building.production.collect` frames and ONE harvest."""
    book = _book()
    book.watch()
    book.rt.interrupts.vars = {"harvest_pending": "1=500"}
    book.rt.interrupts.names = ["collect_base_resources"]
    book.rt.interrupts.changed()
    for _ in range(36):
        book.rt.wire.say("building.production.collect")
    assert book._budget == {"metal": 500}, "every frame re-armed the budget"


def test_a_harvest_made_by_hand_is_a_LIST_of_keys_and_not_a_cap():
    """#2746d stands: a thumb on the green bubbles counts. It states no size, so the
    last reading's `pending` says only WHICH keys the base was holding (#2747).

    Measured live: the person collected five hero-experience lines by hand at 10:04:56
    on 2026-09-11, the game paid 302 400, and the card wrote 183 600 — the reading the
    cap came from was minutes old and had the same five lines at 36 720 each.
    """
    book = _book()
    book.watch()
    book.rt.resources.data = {
        "rows": [{"type": 14, "pending": 2600}],
        "items": [{"id": 8001, "pending": 183600}, {"id": 630011, "pending": 0}]}
    book.rt.wire.say("building.production.collect")
    assert book._budget == {"food": 2600, "item:8001": 183600}
    assert book._claim({"item:8001": 302400}) == {"item:8001": 302400}, (
        "a stale cap threw away two fifths of a real harvest")
    # …and the second burst of the same sweep is not refused for having spent it
    assert book._claim({"item:8001": 1000}) == {"item:8001": 1000}
    # …while a key the base was not holding still gets nothing, which is the whole point
    assert book._claim({"item:630011": 20, "item:7038": 20}) == {}


def test_a_sweep_the_panel_played_is_still_capped_exactly():
    book = _book()
    book.watch()
    book.rt.interrupts.vars = {"harvest_pending": "i8001=164160"}
    book.rt.interrupts.names = ["collect_base_resources"]
    book.rt.interrupts.changed()
    assert book._claim({"item:8001": 164160}) == {"item:8001": 164160}
    assert book._claim({"item:8001": 164160}) == {}, (
        "the run stated its own size and it is a CAP")


def test_the_base_book_is_written_through_the_budget():
    src = (Path(__file__).resolve().parent.parent
           / "panel" / "runtime" / "resource_book.py").read_text(encoding="utf-8")
    assert "self._claim(gains)" in src, "the base book takes the gain uncapped"
    assert "self._base = self.base.add(mine, day)" in src



# -- forgetting one day, through the book that owns it (#2747) ----------------
def test_one_day_is_forgotten_and_the_others_are_not():
    from panel import resource_stats as rs

    stats = rs.ResourceStats({}).add({"metal": 100}, DAY1).add({"metal": 5}, DAY2)
    cut = stats.without(DAY2)
    assert cut.dates() == [DAY1]
    assert cut.on(DAY1)["metal"] == 100, "the history beside it was thrown away"
    assert stats.without("2000-01-01") is stats, "a day with no row costs a save"


def test_the_reset_goes_through_the_book_and_not_the_database():
    """#2747: the runtime holds both tallies in memory and writes them back WHOLE on the
    next gain, so a row deleted under a running panel is silently undone."""
    from panel.runtime import resource_book as rb

    src = (Path(__file__).resolve().parent.parent
           / "panel" / "runtime" / "resource_book.py").read_text(encoding="utf-8")
    assert "def clear_day(" in src, "there is no way to reset a day through the book"
    api = (Path(__file__).resolve().parent.parent
           / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert '"/api/resources/reset"' in api, "the reset is reachable from nowhere"
    assert "book.clear_day(" in api, "the door writes the row behind the book's back"
    assert rb.GAINED in ("resources.gained",)


def test_clearing_a_day_drops_the_base_book_and_keeps_the_whole_tally():
    from panel import resource_stats as rs
    from panel.runtime import resource_book as rb

    book = _book()
    book.rt.store = _Store()
    book.rt.day = _Day(DAY1)
    book._stats = rs.ResourceStats({}).add({"item:7038": 56}, DAY1)
    book._base = rs.ResourceStats({}).add({"item:7038": 34}, DAY1)

    dropped = book.clear_day()
    assert dropped["day"] == DAY1
    assert dropped["base"] == {"item:7038": 34}
    assert dropped["stats"] == {}, "the whole-day tally was cleared without being asked"
    assert book.base.dates() == [], "the base's row survived the reset"
    assert book.stats.on(DAY1)["item:7038"] == 56

    book._base = rs.ResourceStats({}).add({"item:7038": 34}, DAY1)
    both = book.clear_day(whole=True)
    assert both["stats"] == {"item:7038": 56}
    assert book.stats.dates() == []


class _Store:
    def __init__(self) -> None:
        self.blobs: dict = {}

    def blob_get(self, name):
        return self.blobs.get(name)

    def blob_set(self, name, data) -> None:
        self.blobs[name] = data


class _Day:
    def __init__(self, key) -> None:
        self._key = key

    def day_key(self) -> str:
        return self._key



def test_a_sweeps_tail_does_not_arm_a_second_budget():
    """#2747, measured live: the run of 09:52:13 said it was about to collect 63 687
    food and 174 screws; frames kept arriving after it left the register, the hand
    fallback re-armed off the reading's own `pending`, and the card ended the minute on
    77 332 food and 219 screws."""
    book = _book()
    book.watch()
    book.rt.interrupts.vars = {"harvest_pending": "14=63687 #|# i7001=174"}
    book.rt.interrupts.names = ["collect_base_resources"]
    book.rt.interrupts.changed()
    book.rt.interrupts.names = []
    book.rt.interrupts.changed()
    assert book._budget == {"food": 63687, "item:7001": 174}

    # …the run is gone, the cascade is not, and the reading says a fresh pile is standing
    book.rt.resources.data = {"rows": [{"type": 14, "pending": 99999}],
                              "items": [{"id": 6001, "pending": 173}]}
    book._budget_at = book._budget_at - (HAND_LATER := 100.0)
    book.rt.wire.say("building.production.collect")
    assert book._budget == {"food": 63687, "item:7001": 174}, (
        "the tail of one sweep armed a second budget for the same harvest")
    assert book._claim({"item:6001": 173}) == {}, (
        "a key the harvest never claimed was credited to the base")


def test_a_budget_does_not_outlive_the_harvest():
    from panel.runtime import resource_book as rb

    book = _book()
    book.watch()
    book.rt.interrupts.vars = {"harvest_pending": "14=1000"}
    book.rt.interrupts.names = ["collect_base_resources"]
    book.rt.interrupts.changed()
    book._budget_at = book._budget_at - (rb.HARVEST_MAX_SEC + 1)
    assert book._claim({"food": 1000}) == {}, "an hour-old budget was still spendable"


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
