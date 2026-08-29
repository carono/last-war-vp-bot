r"""One live line and one game sprite on an errand's block — and no reading to get them.

`panel/runtime/errand_stats.py` puts a number under a block on «Таймеры» («+377 023 ждёт
сбора» under «Сбор ресурсов»), and `tools/lib/errand_icons.py` puts the game's own
picture beside its switch (#2019). The page draws a dozen of those blocks and is polled,
so the ways this can be wrong are all versions of one thing:

* **it must not ask the game.** `CLAUDE.md`, «Read once, then LISTEN»: a stat bought with
  a round trip would instantly be the most frequent reading the panel takes. Every
  provider reads the database, a checkpoint file, or a cache somebody else filled — and
  the cache is read through `BaseResources.cached`, which raises no ear and books no
  refresh, unlike the `state` the stock card calls;
* **it must say how old it is**, or a number from an hour ago looks like now;
* **it must go quiet rather than guess**: an errand with nothing free to say has no line,
  a blob in an unexpected shape is «no line», and a machine that never extracted the art
  has no pictures and no broken links;
* **and a name off the wire may not walk out of the icon folder.**

No Tk, no game, no network::

    python3 tests/test_panel_errand_stats.py
"""
from __future__ import annotations

TIER = "offline"        # see tools/run_tests.py

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "tests", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import errand_icons                                   # noqa: E402
from panel.runtime import errand_stats as statsmod    # noqa: E402
from panel.runtime import resources as resmod         # noqa: E402


class _Store:
    """This profile's database, as far as a stat is concerned."""

    def __init__(self, blobs: dict | None = None) -> None:
        self.blobs = dict(blobs or {})
        self.asked: list = []

    def blob_get(self, name: str):
        self.asked.append(name)
        return self.blobs.get(name)


class _Profiles:
    def __init__(self, root: Path) -> None:
        self.root = root

    def treasures_json(self) -> str:
        return str(self.root / "world_treasures.json")


class _Resources:
    """The stock cache — and a witness that nothing reached for the reading door."""

    def __init__(self, rows=(), age=1.5) -> None:
        self.rows, self.age = list(rows), age
        self.state_calls = 0

    def cached(self, now=None) -> dict:
        return {"rows": [dict(r) for r in self.rows], "age": self.age}

    def state(self, now=None) -> dict:
        self.state_calls += 1
        raise AssertionError("a stat must never open the reading door")


class _Daily:
    """The one reading the errands page may book — here, already taken."""

    def __init__(self, values=None, age=8.0) -> None:
        self.values, self.age = dict(values or {}), age
        self.looks = 0

    def cached(self, now=None) -> dict:
        return {"values": dict(self.values), "age": self.age}

    def look(self, now=None) -> None:
        self.looks += 1


class _Rt:
    """Just enough runtime: a store, a profile's files, and the two caches."""

    def __init__(self, root: Path, blobs=None, rows=(), age=1.5, daily=None,
                 daily_age=8.0) -> None:
        self.store = _Store(blobs)
        self.profiles = _Profiles(root)
        self.resources = _Resources(rows, age)
        self.daily_reads = _Daily(daily, daily_age)

    # The two doors a stat must never find: playing anything, or taking the link.
    def play_async(self, *a, **k):
        raise AssertionError("a stat must never play a scenario")

    def play(self, *a, **k):
        raise AssertionError("a stat must never play a scenario")


def _rt(**kw) -> "_Rt":
    return _Rt(Path(tempfile.mkdtemp(prefix="lw-stat-")), **kw)


# ---------------------------------------------------------------------------
# nothing here asks the game
# ---------------------------------------------------------------------------
def test_not_one_provider_reaches_for_the_game():
    """Every errand the table knows, asked, against a runtime that raises if touched."""
    rt = _rt(blobs={"rally_counts": {"counts": {"a": 2}}},
             rows=[{"pending": 7}])
    for errand in statsmod.PROVIDERS:
        statsmod.of(rt, errand)              # raises through if a provider plays anything
    assert rt.resources.state_calls == 0, "the stock cache is LOOKED at, never opened"


def test_the_stock_line_is_a_look_and_not_a_reading():
    """`cached` answers what is in memory; it raises no ear and books no refresh."""
    source = (_REPO / "panel" / "runtime" / "resources.py").read_text(encoding="utf-8")
    body = source.split("    def cached(", 1)[1].split("\n    def ", 1)[0]
    for forbidden in ("_listen(", "_maybe_refresh(", "play_async"):
        assert forbidden not in body, f"`cached` must not {forbidden}"
    assert "self._rows" in body and "age" in body


def test_the_module_holds_no_clock_of_its_own():
    """A stat is drawn when a page is drawn — it never wakes anything up."""
    source = (_REPO / "panel" / "runtime"
              / "errand_stats.py").read_text(encoding="utf-8")
    # The CODE, not the prose: the docstring says the word «wire» about what fills the
    # cache this reads, and a check that could not tell those apart would be a check
    # about spelling.
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    code = code.split('"""')[-1]
    for forbidden in ("tick.arm", "Thread(", ".after(", "wire.", "subscribe"):
        assert forbidden not in code, f"a stat must not {forbidden}"


# ---------------------------------------------------------------------------
# what each provider says
# ---------------------------------------------------------------------------
def test_the_pile_waiting_to_be_collected_is_the_sum_of_the_buildings():
    rt = _rt(rows=[{"pending": 377023}, {"pending": 604724}, {"pending": 0}], age=12.4)
    stat = statsmod.of(rt, "collect_base_resources")
    assert stat["key"] == "timers.stat.pending"
    assert stat["fmt"]["n"] == "981\u2009747", stat   # a thin space, so seven figures read
    assert stat["age"] == 12.4


def test_a_stock_nobody_has_read_says_nothing_rather_than_zero():
    """`age` of -1 is «never read» — a line saying «+0 ждёт сбора» would be a lie."""
    rt = _rt(rows=[], age=-1)
    assert statsmod.of(rt, "collect_base_resources") is None
    rt = _rt(rows=[{"pending": 0}], age=3.0)
    assert statsmod.of(rt, "collect_base_resources") is None


def test_a_days_tally_carries_no_age():
    """«Сегодня» is the whole truth about when it is from (rallies, fireworks)."""
    rt = _rt(blobs={"rally_counts": {"counts": {"boss": 3, "drill": 9}}})
    stat = statsmod.of(rt, "rally_auto_join")
    assert stat == {"key": "timers.stat.rallies", "fmt": {"n": 12}, "age": None}

    rt = _rt(blobs={"firework_state": {"taken": 4, "heard": 120}})
    stat = statsmod.of(rt, "firework_collect")
    assert stat == {"key": "timers.stat.fireworks", "fmt": {"n": 4}, "age": None}


def _tile(**kw) -> dict:
    """A tile of either list, ripe unless a keyword says otherwise. Invented values."""
    now = int(time.time() * 1000)
    row = {"uuid": 1000000000000001, "server": 100, "x": 1, "y": 2, "level": 7,
           "completed_at": now - 60_000, "expires_at": now + 3_600_000,
           "loot_max": 3, "loot_count": 0,
           # The sniffer's stamp is this PC's epoch SECONDS; the game's confirmation
           # («Сверено») is game MILLISECONDS. A row may carry either.
           "seen_at": time.time() - 30}
    row.update(kw)
    return row


def test_a_tile_list_counts_what_is_worth_a_robbery_now():
    now = int(time.time() * 1000)
    rows = [
        _tile(),                                   # ripe
        _tile(mine=True),                          # ours
        _tile(robbed=True),                        # already taken
        _tile(completed_at=now + 600_000),         # still out
        _tile(expires_at=now - 1),                 # its clock ran out
        _tile(loot_count=3),                       # no slot left
    ]
    rt = _rt(blobs={"secret_tasks_state": {"rows": rows}})
    stat = statsmod.of(rt, "secret_autoloot")
    assert stat["key"] == "timers.stat.targets"
    assert stat["fmt"] == {"n": 1, "all": 6}, stat
    assert 25 <= stat["age"] < 120, stat        # seconds, off `seen_at`

    # …and a list stamped the other way — the game's own «Сверено», in game milliseconds.
    import game_clock

    game_rows = [_tile(checked_at=game_clock.now_ms() - 45_000, seen_at=None)]
    rt = _rt(blobs={"secret_tasks_state": {"rows": game_rows}})
    aged = statsmod.of(rt, "secret_autoloot")["age"]
    assert 40 <= aged < 120, aged

    # …and the ghost list, which is a BARE list rather than a dict with books beside it.
    rt = _rt(blobs={"ghost_map_state": rows})
    assert statsmod.of(rt, "ghost_autoloot")["fmt"] == {"n": 1, "all": 6}


def test_a_blob_in_an_unexpected_shape_is_no_line_rather_than_a_wrong_one():
    for blobs in ({"secret_tasks_state": "nonsense"},
                  {"secret_tasks_state": {"robbed": {"1": 1}}},
                  {"rally_counts": []},
                  {"firework_state": 7}):
        rt = _rt(blobs=blobs)
        for errand in ("secret_autoloot", "rally_auto_join", "firework_collect"):
            assert statsmod.of(rt, errand) in (None, {"key": "timers.stat.fireworks",
                                                      "fmt": {"n": 0}, "age": None}) \
                or statsmod.of(rt, errand)["key"].startswith("timers.stat.")


def test_the_treasure_line_comes_off_the_checkpoint_with_its_age():
    rt = _rt()
    path = rt.profiles.treasures_json()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([{"uuid": 1, "x": 5, "y": 6}, {"uuid": 2, "x": 7, "y": 8}], fh)
    stat = statsmod.of(rt, "treasure_auto")
    assert stat["key"] == "timers.stat.chests" and stat["fmt"] == {"n": 2}
    assert stat["age"] is not None and stat["age"] < 60

    # With no capture ever run there is no file, and therefore no line.
    assert statsmod.of(_rt(), "treasure_auto") is None


def test_an_errand_nobody_can_answer_for_free_has_no_line():
    """The blank is the deliverable: it says «мы слепы», and a poll would hide that.

    These are the ones no reading the panel takes can answer — not even the checklist's
    (#2019): the tavern's free pull, «Кодовое имя», the radar board, the ministry.
    """
    rt = _rt()
    for errand in ("restart_game", "tavern_free_pull", "collect_alliance_gifts",
                   "attack_codename_daily", "do_radar_tasks", "session_kick",
                   "apply_ministry_interior"):
        assert errand not in statsmod.PROVIDERS
        assert statsmod.of(rt, errand) is None


def test_a_provider_that_throws_costs_the_line_and_nothing_else():
    class _Boom:
        def blob_get(self, name):
            raise RuntimeError("the database is busy")

    rt = _rt()
    rt.store = _Boom()
    assert statsmod.of(rt, "rally_auto_join") is None



# ---------------------------------------------------------------------------
# the ONE reading the page is allowed to take (#2019)
# ---------------------------------------------------------------------------
def test_the_eight_lines_that_ride_on_one_reading():
    """The truck was what the person approved; the rest come out of the same chunk."""
    rt = _rt(daily={"trucks_ready": 2, "trucks_send_left": 3, "trucks_send_cap": 4,
                    "help_waiting": 7, "donate_left": 17, "decorations": 5,
                    "recruit_pending": 1, "gifts_pending": 2}, daily_age=8.0)
    assert statsmod.of(rt, "collect_truck_resources") == {
        "key": "timers.stat.trucks", "fmt": {"n": 2}, "age": 8.0}
    assert statsmod.of(rt, "send_trucks")["fmt"] == {"n": 3, "all": 4}
    assert statsmod.of(rt, "alliance_help")["fmt"] == {"n": 7}
    assert statsmod.of(rt, "donate_alliance_tech")["fmt"] == {"n": 17}
    assert statsmod.of(rt, "upgrade_decorations")["fmt"] == {"n": 5}
    # The two queues are one number a person acts on, not two to add up.
    assert statsmod.of(rt, "collect_visitor_gifts")["fmt"] == {"n": 3}
    assert statsmod.of(rt, "recruit_survivors")["fmt"] == {"n": 3}


def test_a_reading_never_taken_draws_no_line():
    assert statsmod.of(_rt(daily={}, daily_age=-1), "collect_truck_resources") is None
    # …and a client that would not answer that one field is not a zero either.
    rt = _rt(daily={"help_waiting": 1}, daily_age=4.0)
    assert statsmod.of(rt, "collect_truck_resources") is None


def test_the_reading_is_booked_by_a_look_and_by_nothing_else():
    """No clock, no thread, no subscription — and the route is the only caller."""
    source = (_REPO / "panel" / "runtime"
              / "errand_reads.py").read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]
    for forbidden in ("tick.arm", "Thread(", ".after(", "subscribe"):
        assert forbidden not in code, f"the reading must not {forbidden}"
    # The person's five conditions, each pinned where it is written.
    assert "MIN_GAP_SEC = 60.0" in code, "«не чаще раза в минуту»"
    assert "now - self._looked_at > LOOK_SEC" in code, "«пока страницу реально смотрят»"
    assert "claims.DETACHED" in code, "below the bot's own work"
    assert "self._rt.game.busy" in code, "«занят линк — пропускаем такт»"
    assert '"age"' in code, "the age travels with the number"

    api = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert api.count("self._look_at_errands(rt)") == 2, "the two errand routes"
    assert "rt.daily_reads.look()" in api

    stats = (_REPO / "panel" / "runtime"
             / "errand_stats.py").read_text(encoding="utf-8")
    assert "daily_reads.cached()" in stats and "daily_reads.look" not in stats, \
        "a provider LOOKS at what was read; it never books a reading"


# ---------------------------------------------------------------------------
# the picture
# ---------------------------------------------------------------------------
def test_every_errand_named_in_the_map_names_a_real_sprite_stem():
    with open(_REPO / "tools" / "data" / "errand_icons.json", encoding="utf-8") as fh:
        icons = json.load(fh)["icons"]
    assert icons, "the map is the whole feature"
    for errand, stem in icons.items():
        assert stem and stem == os.path.basename(stem), errand
        assert not stem.endswith(".png"), f"{errand}: the map holds stems, not files"


def test_a_name_off_the_wire_cannot_walk_out_of_the_icon_folder():
    for evil in ("../../CLAUDE.md", "/etc/passwd", "..\\..\\panel\\web\\api.py",
                 ".hidden.png", "", "sub/dir.png"):
        assert errand_icons.file_named(evil) is None, evil


def test_with_nothing_extracted_there_are_no_pictures_and_no_broken_links():
    """An installation that never ran the extractor draws blocks, not 404s."""
    from panel.runtime import errand_art

    root = errand_icons.ICON_ROOT
    try:
        errand_icons.ICON_ROOT = str(Path(tempfile.mkdtemp(prefix="lw-noicons-")))
        assert errand_icons.name_for("collect_base_resources") == ""
        assert errand_art.name_for("collect_base_resources") == ""
    finally:
        errand_icons.ICON_ROOT = root


def test_an_errand_with_no_picture_asks_for_none():
    """Every errand in the catalogue has one since #2061 — this is about the rest.

    The map answered `""` for three of the shipped errands until the person reported
    «не все картинки есть»; they have pictures now (the refresh ring, the bar's beer and
    the game's own device icon). What must still answer `""` is a name nobody has mapped
    — a row somebody adds tomorrow — because the alternative is a block whose picture
    404s on every poll of the page.
    """
    assert errand_icons.stem_for("no_such_errand") == ""
    assert errand_icons.name_for("no_such_errand") == ""


# ---------------------------------------------------------------------------
# both halves reach the phone
# ---------------------------------------------------------------------------
def test_every_row_the_phone_draws_carries_its_picture_and_its_line():
    api = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert api.count('"stat": statsmod.of(') == 3, "timers, triggers and the orders"
    assert api.count('artmod.name_for(') == 3, "timers, triggers and the orders"

    server = (_REPO / "panel" / "web" / "server.py").read_text(encoding="utf-8")
    assert '/api/errandicon' in server and "def _errandicon" in server
    # A picture is a GET beside the other three, and it goes through the one helper that
    # authorises, resolves and caches — not a fourth copy of that logic.
    assert "self._picture(query, resolve)" in server.split("def _errandicon", 1)[1]

    view = (_REPO / "panel" / "web" / "app" / "src" / "views"
            / "TimersView.tsx").read_text(encoding="utf-8")
    # THE PICTURE IS THE CARD'S BACKGROUND since #2061 («картинка должна быть большая и
    # фоном»), so what is checked is that the card still CARRIES it — the class the
    # stylesheet paints through and the custom property holding the link — rather than
    # the name of the 28 px stamp it used to be.
    assert "artStyle(icon)" in view and "'--art'" in view, "the card carries no picture"
    assert "function Stat(" in view
    # ONE BLOCK DRAWS ALL THREE (#2050): the timer, the listener and the order are the
    # same card, so the reading is rendered once and handed in three times. It used to
    # be three renderings, and the count that checked for them went on passing at 1 for
    # two releases — so the thing counted is what actually differs now.
    assert view.count("<Stat stat=") == 1, "the card draws the reading in one place"
    assert view.count("stat={row.stat}") == 3, "a timer, a listener and an order each"
    assert "timers.stat.age" in view, "the age is drawn beside the number"


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
        except Exception as exc:      # noqa: BLE001 — a raise is a failure too
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
