r"""The star-secret-task day: the derived cycle, and its willingness to be wrong (#1467).

What is pinned here is the whole of what a schedule nobody typed in has to promise:

  * a cycle is FITTED to observations — its length, its word and one offset per warzone —
    and a warzone nobody has watched borrows the offset of its nearest NUMBER neighbour,
    which is the only thing «соседние серверы идут по одному циклу со сдвигом» can mean;
  * there are THREE states, and the middle one survives the round trip: a post-day is
    never rounded into «day» or «plain», because the post-day is what decides whether a
    monitor is worth running;
  * a fact beats the graph, an observation beats the graph, and every answer says WHICH
    of the four it is;
  * an observation the cycle contradicts is reported, not overwritten — a graph that has
    started to lie has to be able to say so;
  * too little data fits nothing at all, rather than fitting everything perfectly;
  * and the day is counted on the GAME's reset moment, not on UTC midnight.

Every warzone number, date and period in this file is INVENTED (`CLAUDE.md`: not one
identifier of a real account is written down) — the shapes are real, the values are not.

Needs nothing but python:

    python3 tests/test_secret_day.py
"""
from __future__ import annotations

TIER = "offline"   # no Tk, no display, no game — a temp database and arithmetic

import importlib.util
import sys
import tempfile
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import secret_day as sd                                          # noqa: E402


def _runtime_module(name: str):
    """Load one file out of `panel/runtime/` WITHOUT importing the panel.

    `panel.runtime.__init__` pulls in the runtime host, which imports Tk, which needs a
    display this test has no business needing. The two modules under test here touch
    neither, so they are loaded under a shim package whose only member is the `paths`
    helper they ask for.
    """
    shim = sys.modules.get("_sd_shim")
    if shim is None:
        shim = types.ModuleType("_sd_shim")
        shim.__path__ = [str(_REPO / "panel" / "runtime")]
        sys.modules["_sd_shim"] = shim
        paths = types.ModuleType("_sd_shim.paths")
        paths.ensure = lambda: None            # tools/lib is on sys.path already
        sys.modules["_sd_shim.paths"] = paths
    full = "_sd_shim.%s" % name
    if full not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            full, _REPO / "panel" / "runtime" / ("%s.py" % name))
        module = importlib.util.module_from_spec(spec)
        sys.modules[full] = module
        spec.loader.exec_module(module)
    return sys.modules[full]


storemod = _runtime_module("store")                              # noqa: E402
bookmod = _runtime_module("secret_day")                          # noqa: E402

#: An invented cycle: two star days, one post-day, four ordinary ones.
CYCLE = (sd.STATE_DAY, sd.STATE_DAY, sd.STATE_POST,
         sd.STATE_PLAIN, sd.STATE_PLAIN, sd.STATE_PLAIN, sd.STATE_PLAIN)

#: An invented block of warzones, each shifted one day from the one before it.
BASE = 1200


def _sightings(servers=(BASE, BASE + 1, BASE + 2), days=range(0, 14)) -> list:
    """What a watcher who looked at those warzones on those days would have written."""
    out = []
    for index, server in enumerate(servers):
        for day in days:
            state = CYCLE[(day - index) % len(CYCLE)]
            out.append(sd.observation(server, day, state, sd.SOURCE_OBSERVED,
                                      seen_at=day * sd.DAY_MS))
    return out


# -- the day, counted the game's way ----------------------------------------
def test_the_day_turns_over_when_the_game_says_it_does() -> None:
    """02:00 UTC is a day boundary here, because that is what the client answered."""
    reset = 2 * 3_600_000                       # the reset falls at 02:00 UTC
    just_before = 20 * sd.DAY_MS + reset - 1
    just_after = 20 * sd.DAY_MS + reset + 1
    assert sd.day_index(just_before, reset) == 19
    assert sd.day_index(just_after, reset) == 20
    starts, ends = sd.day_bounds(20, reset)
    assert starts <= just_after < ends
    assert ends - starts == sd.DAY_MS


def test_a_day_is_labelled_off_the_games_clock_and_not_the_machines() -> None:
    """The label is derived from the same bounds, so it cannot drift from the index."""
    reset = 2 * 3_600_000
    assert sd.day_label(0, reset) == "1970-01-01"
    assert sd.day_label(1, reset) == "1970-01-02"


# -- the fit -----------------------------------------------------------------
def test_the_cycle_is_found_and_the_neighbours_come_out_shifted() -> None:
    """Nothing is told the period or the offsets; both fall out of the sightings."""
    schedule = sd.fit(_sightings())
    assert schedule is not None
    assert schedule.period == len(CYCLE)
    assert schedule.clash == 0
    shifts = [schedule.offsets[BASE + n] for n in range(3)]
    steps = {(shifts[n + 1] - shifts[n]) % schedule.period for n in range(2)}
    assert steps == {1}, f"the neighbours are not one day apart: {shifts}"


def test_too_little_data_fits_nothing() -> None:
    """Two sightings on one day fit every period perfectly and mean nothing."""
    assert sd.fit([sd.observation(BASE, 3, sd.STATE_DAY)]) is None
    assert sd.fit([sd.observation(BASE, 3, sd.STATE_DAY),
                   sd.observation(BASE + 1, 3, sd.STATE_PLAIN)]) is None


def test_a_phase_nobody_has_seen_stays_unknown() -> None:
    """A gap in the word answers «не знаю», not the tidiest of the three states."""
    seen = [sd.observation(BASE, day, CYCLE[day % len(CYCLE)]) for day in (0, 1, 2)]
    seen += [sd.observation(BASE + 1, day, CYCLE[(day - 1) % len(CYCLE)])
             for day in (1, 2, 3)]
    schedule = sd.fit(seen, periods=(len(CYCLE),))
    assert schedule is not None
    unseen = [p for p in range(schedule.period) if p not in schedule.pattern]
    assert unseen, "this fixture is meant to leave phases unvisited"
    assert schedule.pattern.get(unseen[0], sd.STATE_UNKNOWN) == sd.STATE_UNKNOWN


# -- the three states, and the middle one -----------------------------------
def test_the_post_day_is_a_state_of_its_own() -> None:
    """It is neither «day» nor «plain» on the way in or on the way out."""
    schedule = sd.fit(_sightings())
    states = {schedule.state(BASE, day) for day in range(schedule.period)}
    assert states == set(sd.STATES)
    post_day = next(day for day in range(20) if CYCLE[day % len(CYCLE)] == sd.STATE_POST)
    assert schedule.state(BASE, post_day) == sd.STATE_POST


# -- what an answer says about itself ---------------------------------------
def test_a_fact_beats_an_observation_which_beats_the_graph() -> None:
    """The four sources, in order, each labelled as what it is."""
    seen = _sightings()
    schedule = sd.fit(seen)
    said = sd.answer(schedule, seen, BASE, 3, fact=sd.STATE_DAY)
    assert (said["state"], said["source"]) == (sd.STATE_DAY, sd.SOURCE_GAME)
    said = sd.answer(schedule, seen, BASE, 3)
    assert said["source"] == sd.SOURCE_OBSERVED
    said = sd.answer(schedule, seen, BASE, 99)
    assert said["source"] == sd.SOURCE_SCHEDULE


def test_an_unwatched_warzone_borrows_its_nearest_neighbour_and_says_so() -> None:
    """The borrowing is in the answer — never passed off as something anybody saw."""
    seen = _sightings()
    schedule = sd.fit(seen)
    said = sd.answer(schedule, seen, BASE + 7, 40)
    assert said["source"] == sd.SOURCE_NEIGHBOUR
    assert said["neighbour"] == BASE + 2 and said["distance"] == 5
    assert said["state"] in sd.STATES


def test_nothing_known_is_answered_as_nothing_known() -> None:
    """No schedule and no sighting is `unknown` — not a state with a shrug attached."""
    said = sd.answer(None, [], BASE, 5)
    assert (said["state"], said["source"]) == (sd.STATE_UNKNOWN, sd.SOURCE_UNKNOWN)


# -- when it turns over ------------------------------------------------------
def test_the_next_change_is_a_day_and_a_state() -> None:
    """«Когда сменится» is the first day ahead whose answer is a different word."""
    seen = _sightings()
    schedule = sd.fit(seen)
    today = 100
    now = sd.answer(schedule, seen, BASE, today)["state"]
    turn = sd.next_change(schedule, seen, BASE, today)
    assert turn is not None
    assert turn["state"] != now
    assert 1 <= turn["in_days"] <= schedule.period
    for step in range(1, turn["in_days"]):
        assert sd.answer(schedule, seen, BASE, today + step)["state"] == now


def test_nothing_is_promised_about_a_turn_that_cannot_be_seen() -> None:
    """An unknown state today has no next change, and does not invent one."""
    assert sd.next_change(None, [], BASE, 4) is None


# -- the self-check ----------------------------------------------------------
def test_an_observation_the_graph_contradicts_is_reported_not_swallowed() -> None:
    """This is the whole licence for a derived schedule: it can say it is wrong."""
    seen = _sightings()
    assert sd.conflicts(sd.fit(seen), seen) == []
    odd_day = 30
    seen.append(sd.observation(BASE, odd_day,
                               sd.STATE_DAY if CYCLE[odd_day % len(CYCLE)] != sd.STATE_DAY
                               else sd.STATE_PLAIN))
    schedule = sd.fit(seen)
    clash = sd.conflicts(schedule, seen)
    assert clash, "a sighting against the cycle has to surface"
    assert clash[0]["server"] == BASE and clash[0]["day"] == odd_day
    assert clash[0]["observed"] != clash[0]["predicted"]
    assert sd.summary(schedule, seen)["conflicts"] == len(clash)


# -- counted evidence, and thresholds nobody typed in -----------------------
def test_the_thresholds_are_learnt_from_labelled_days_or_there_are_none() -> None:
    """No calibration without both ends of the scale — a rule fitted to one side lies."""
    counted = [sd.observation(BASE, 0, sd.STATE_DAY, stars=60, tiles=200),
               sd.observation(BASE, 1, sd.STATE_POST, stars=20, tiles=200),
               sd.observation(BASE, 2, sd.STATE_PLAIN, stars=2, tiles=200)]
    learnt = sd.calibrate(counted)
    assert learnt and learnt["day"] > learnt["post"] > 0
    assert sd.calibrate(counted[:1]) is None


def test_counts_become_a_state_only_once_the_scale_is_known() -> None:
    """An unlabelled lap is evidence; it turns into a label when calibration exists."""
    counted = [sd.observation(BASE, 0, sd.STATE_DAY, stars=60, tiles=200),
               sd.observation(BASE, 1, sd.STATE_POST, stars=20, tiles=200),
               sd.observation(BASE, 2, sd.STATE_PLAIN, stars=2, tiles=200)]
    fresh = sd.observation(BASE + 4, 9, sd.STATE_UNKNOWN, sd.SOURCE_OBSERVED,
                           stars=55, tiles=200)
    assert sd.classify(fresh, None) == sd.STATE_UNKNOWN
    grown = {(o["server"], o["day"]): o for o in sd.with_learnt_states(counted + [fresh])}
    became = grown[(BASE + 4, 9)]
    assert became["state"] == sd.STATE_DAY and became["learnt"] is True


def test_an_observation_with_no_counts_and_no_label_stays_out_of_the_fit() -> None:
    """«Я посмотрел и не понял» must not become a phase of the cycle."""
    seen = _sightings()
    seen.append(sd.observation(BASE + 3, 5, sd.STATE_UNKNOWN))
    schedule = sd.fit(seen)
    assert BASE + 3 not in schedule.offsets


# -- the book: the profile's own database ------------------------------------
def _book():
    """A book on a throwaway database — the real store, the real migrations."""
    tmp = tempfile.mkdtemp(prefix="secretday-")
    store = storemod.Store(str(Path(tmp) / "panel.db"))
    book = bookmod.SecretDayBook(store, reset_ms=2 * 3_600_000)
    return book, store


def test_the_table_arrives_with_a_migration_and_not_by_hand() -> None:
    """A new kind of game data is a schema version, never a `CREATE TABLE` somewhere."""
    book, store = _book()
    assert store.version() == storemod.CODE_VERSION
    names = {row[0] for row in store.read().execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    assert "secret_days" in names
    assert book.observations() == []
    store.close()


def test_a_person_and_a_lap_disagreeing_are_two_rows() -> None:
    """The source is part of the key, so the later write cannot become the only truth."""
    book, store = _book()
    book.record(BASE, 10, sd.STATE_DAY, source=sd.SOURCE_OBSERVED)
    book.record(BASE, 10, sd.STATE_PLAIN, source=sd.SOURCE_GAME)
    store.flush()
    rows = [r for r in book.observations() if r["day"] == 10]
    assert len(rows) == 2
    assert {r["state"] for r in rows} == {sd.STATE_DAY, sd.STATE_PLAIN}
    store.close()


def test_a_mark_is_answerable_before_the_writer_has_committed() -> None:
    """The press redraws in the same tick; the row must be in the answer it produced."""
    book, store = _book()
    book.record(BASE, book.today(), sd.STATE_DAY)
    said = book.answer(BASE)
    assert (said["state"], said["source"]) == (sd.STATE_DAY, sd.SOURCE_OBSERVED)
    store.close()


def test_the_scenarios_two_lines_become_observations() -> None:
    """`read_secret_day.md`'s own output — the shape both front-ends hand to the book."""
    book, store = _book()
    written = book.take_reading({
        "secret_clock": "own=1200 asked=1200 now_ms=1700000000000"
                        " day_end_ms=1700028000000",
        "secret_counts": "1200=7/120 1201=0/9"})
    store.flush()
    assert written == 2
    rows = {r["server"]: r for r in book.observations()}
    assert rows[BASE]["stars"] == 7 and rows[BASE]["tiles"] == 120
    assert rows[BASE]["source"] == sd.SOURCE_GAME
    # …and the day boundary the client named is the one every row was counted against.
    assert book.reset_ms == 1700028000000
    assert rows[BASE]["day"] == sd.day_index(1700000000000, 1700028000000)
    store.close()


def test_a_reading_from_a_client_with_no_clock_is_not_written_down() -> None:
    """The login screen answers plausibly and wrongly; day zero of 1970 is not evidence."""
    book, store = _book()
    assert book.take_reading({"secret_clock": "own=-1 asked=-1 now_ms=0 day_end_ms=0",
                              "secret_counts": "1200=0/0"}) == 0
    assert book.observations() == []
    store.close()


def test_every_drawn_row_carries_the_answer_as_locale_keys() -> None:
    """Both front-ends draw off `decorate`, and neither is handed a sentence."""
    book, store = _book()
    for row in _sightings():
        book.record(row["server"], row["day"], row["state"], row["source"])
    store.flush()
    drawn = book.decorate([{"id": BASE}, {"id": BASE + 9}])
    assert drawn[0]["secret_state_key"].startswith("servers.secret.state.")
    assert drawn[0]["secret_source_key"] == "servers.secret.src.schedule"
    assert drawn[1]["secret_source_key"] == "servers.secret.src.neighbour"
    assert all(not str(row["secret_until"]).endswith("None") for row in drawn)
    store.close()


def test_the_book_says_how_much_it_disagrees_with_itself() -> None:
    """The summary is what a person judges the graph by, before believing a cell."""
    book, store = _book()
    for row in _sightings():
        book.record(row["server"], row["day"], row["state"], row["source"])
    store.flush()
    facts = book.summary()
    assert facts["servers"] == 3 and facts["days"] == 14
    assert facts["period"] == len(CYCLE) and facts["conflicts"] == 0
    store.close()


if __name__ == "__main__":
    failed = 0
    for name, func in sorted(dict(globals()).items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
            print(f"ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:              # noqa: BLE001
            failed += 1
            print(f"ERR  {name}: {exc!r}")
    print("—", "all green" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
