r"""The schematic map's data: what it draws, what it refuses to draw, what it costs.

`panel/runtime/worldscene.py` assembles the picture the «Карта: схема» tab paints
(#2018). It is a comparison tool — the whole point is to hold our model of the map up
beside the real client — so the ways it can be wrong are the ways a comparison tool
must never be wrong:

* **it must not ask the game.** Every source is a file or a table already on this
  profile's disk; a scene that reached for the client would be the background poll
  `CLAUDE.md` forbids, on a page that is open for as long as somebody is comparing;
* **it must not go quiet when a source renames a field.** Eight sources written by six
  authors spell the same fact three ways, and a strict reader answering «пусто» for one
  of them looks exactly like «панель ничего не знает про эту область»;
* **it must not silently drop half the map.** What the cap leaves out is counted;
* **and the scene must not ride the screen's poll** — that is why the tab answers for
  it through `web_data` rather than putting it in `web_view`.

No Tk, no game, no network — a temp profile directory and a real store::

    python3 tests/test_panel_worldscene.py
"""
from __future__ import annotations

TIER = "offline"        # see tools/run_tests.py

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import worldscene  # noqa: E402
from panel.runtime.store import Store, GHOST_MAP_STATE, SECRET_TASKS_STATE  # noqa: E402


class _Profiles:
    """Where this profile keeps its checkpoints — the two the scene reads."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def world_json(self) -> str:
        return str(self.root / "world_map.json")

    def treasures_json(self) -> str:
        return str(self.root / "world_treasures.json")


class _Rt:
    """Just enough runtime: a profile's files and a profile's database.

    A REAL store, not a stand-in — the blob names and the monsters table are half of
    what this module reads, and a fake that answered them would be testing itself.
    """

    def __init__(self, root: Path) -> None:
        self.profiles = _Profiles(root)
        self.store = Store(str(root / "panel.db"))

    def dbg(self, component: str = "panel"):
        raise AssertionError("the scene must not need a logger")


def _fresh() -> "_Rt":
    root = Path(tempfile.mkdtemp(prefix="lw-worldscene-"))
    return _Rt(root)


def _write(path: str, value) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh)


def _world(rt, **kinds) -> None:
    _write(rt.profiles.world_json(),
           {"mines": [], "trucks": [], "trains": [], "players": [], **kinds})


# -- what it draws ----------------------------------------------------------
def test_every_source_reaches_the_scene_under_its_own_kind():
    rt = _fresh()
    _world(rt,
           mines=[{"x": 10, "y": 20, "server_id": 1, "level": 5, "resource": "iron"}],
           players=[{"x": 11, "y": 21, "server_id": 1, "name": "Player1", "level": 30}],
           trucks=[{"x": 12, "y": 22, "server_id": 1, "owner_name": "Player2"}],
           trains=[{"x": 13, "y": 23, "server_id": 1, "alliance_abbr": "AL1"}])
    rt.store.blob_set(SECRET_TASKS_STATE, [{"x": 14, "y": 24, "server": 1, "level": 8}])
    rt.store.blob_set(GHOST_MAP_STATE, [{"x": 15, "y": 25, "server": 1, "level": 4}])
    _write(rt.profiles.treasures_json(), [{"x": 16, "y": 26, "server_id": 1}])
    rt.store.monsters_upsert([{"uuid": "m1", "x": 17, "y": 27, "server": 1,
                               "level": 20, "seen_at": int(time.time()),
                               "kind_name": "world_monster_boss_iron"}])
    rt.store.flush()      # the writer is a thread; the scene reads what is committed

    scene = worldscene.scene(rt)
    kinds = {o["k"] for o in scene["objects"]}
    assert kinds == set(worldscene.KINDS), f"missing kinds: {set(worldscene.KINDS) - kinds}"
    assert scene["counts"]["mine"] == 1, scene["counts"]
    # The bounds are what the canvas opens fitted to, so they have to hold every dot.
    assert scene["bounds"] == {"x0": 10, "y0": 20, "x1": 17, "y1": 27}, scene["bounds"]


def test_a_record_with_no_place_is_not_on_a_map():
    """A truck's owner is kept without a coordinate on purpose (`world_index.py`)."""
    rt = _fresh()
    _world(rt, players=[{"x": None, "y": None, "name": "Player1"},
                        {"x": 5, "y": 6, "name": "Player2"}])
    scene = worldscene.scene(rt)
    assert scene["counts"]["base"] == 1, scene["counts"]
    assert scene["objects"][0]["n"] == "Player2"


def test_a_source_that_spells_the_server_differently_is_still_read():
    """`server_id` / `server` / `owner_server` — see the module docstring."""
    rt = _fresh()
    _world(rt, mines=[{"x": 1, "y": 1, "server": 77}])
    rt.store.blob_set(SECRET_TASKS_STATE, [{"x": 2, "y": 2, "server_id": 77}])
    scene = worldscene.scene(rt)
    assert {o["s"] for o in scene["objects"]} == {77}, scene["objects"]
    assert scene["servers"] == [77], scene["servers"]


def test_a_half_written_checkpoint_is_a_moment_old_and_never_an_error():
    """A capture child rewrites these whole every tick; a reader may catch one mid-write."""
    rt = _fresh()
    with open(rt.profiles.world_json(), "w", encoding="utf-8") as fh:
        fh.write('{"mines": [{"x": 1,')
    scene = worldscene.scene(rt)
    assert scene["counts"]["mine"] == 0, scene["counts"]


# -- what it refuses to hide ------------------------------------------------
def test_what_the_cap_leaves_out_is_counted_and_said():
    rt = _fresh()
    _world(rt, mines=[{"x": i, "y": 0, "server_id": 1} for i in range(50)])
    scene = worldscene.scene(rt, max_per_kind=10)
    assert scene["counts"]["mine"] == 10, scene["counts"]
    assert scene["hidden"]["mine"] == 40, scene["hidden"]
    assert len(scene["objects"]) == 10


def test_one_warzone_can_be_asked_for_on_its_own():
    rt = _fresh()
    _world(rt, mines=[{"x": 1, "y": 1, "server_id": 1},
                      {"x": 2, "y": 2, "server_id": 2}])
    scene = worldscene.scene(rt, server=2)
    assert [o["x"] for o in scene["objects"]] == [2], scene["objects"]


def test_a_stale_monster_is_not_drawn_as_if_it_were_current():
    rt = _fresh()
    _world(rt)
    old = int(time.time()) - worldscene.SIGHTING_TTL_SEC - 60
    rt.store.monsters_upsert([{"uuid": "m1", "x": 1, "y": 1, "server": 1, "seen_at": old}])
    rt.store.flush()
    assert worldscene.scene(rt)["counts"]["monster"] == 0


# -- what it costs ----------------------------------------------------------
def test_the_overview_counts_without_building_a_single_object():
    """The card and the window row want eight numbers, not thirty thousand dicts."""
    rt = _fresh()
    _world(rt, mines=[{"x": i, "y": 0} for i in range(2000)])
    rt.store.blob_set(GHOST_MAP_STATE, [{"x": 1, "y": 1}])
    over = worldscene.overview(rt)
    assert over["counts"]["mine"] == 2000, over["counts"]
    assert over["counts"]["ghost"] == 1, over["counts"]
    assert "world_map" in over["ages"] and over["ages"]["world_map"] is not None


def test_an_age_is_none_when_nothing_has_ever_been_read():
    rt = _fresh()
    over = worldscene.overview(rt)
    assert over["ages"]["world_map"] is None, over["ages"]
    assert over["counts"] == dict.fromkeys(worldscene.KINDS, 0), over["counts"]


def test_a_missing_database_does_not_take_the_page_down():
    """A profile whose store cannot be opened still gets a page with zeroes on it."""

    class _Broken(_Rt):
        @property
        def store(self):        # noqa: D401 — the point is that it raises
            raise RuntimeError("no database")

    root = Path(tempfile.mkdtemp(prefix="lw-worldscene-"))
    rt = _Broken.__new__(_Broken)
    rt.profiles = _Profiles(root)
    over = worldscene.overview(rt)
    assert over["counts"]["monster"] == 0, over["counts"]


# -- the contract with the phone --------------------------------------------
def test_the_scene_is_not_in_the_screen_that_is_polled():
    """`web_view` rides the phone's poll; the scene must be asked for separately."""
    view_source = (_REPO_ROOT / "panel" / "tabs" / "worldview.py").read_text(encoding="utf-8")
    body = view_source.split("def web_view", 1)[1].split("def web_data", 1)[0]
    assert "worldscene.scene" not in body, \
        "the scene would then travel on every poll of an open screen"
    assert "worldscene.scene" in view_source.split("def web_data", 1)[1], \
        "the map has to come from somewhere"


# -- where we have looked ---------------------------------------------------
def test_coverage_is_folded_out_of_the_checkpoint_and_kept():
    """The child forgets when it dies; the panel is what accumulates."""
    rt = _fresh()
    now = int(time.time())
    _world(rt, coverage={"cell": 25, "sizes": {"1": 1000},
                         "cells": [{"s": 1, "cx": 4, "cy": 7, "t": now, "v": 0}]})
    first = worldscene.scene(rt)["coverage"]
    assert first["cells"] == [{"s": 1, "cx": 4, "cy": 7, "t": now, "v": 0}], first
    assert first["sizes"] == {"1": 1000}, first

    # …and the checkpoint going away does not un-sweep the ground.
    _world(rt)
    again = worldscene.scene(rt)["coverage"]
    assert again["cells"] == first["cells"], again


def test_a_cell_heard_from_higher_up_keeps_the_lowest_height():
    """Above the task height the map sends bases and no tasks (map-sweep-zoom)."""
    rt = _fresh()
    now = int(time.time())
    _world(rt, coverage={"cell": 25, "sizes": {"1": 1000},
                         "cells": [{"s": 1, "cx": 1, "cy": 1, "t": now, "v": 0}]})
    worldscene.scene(rt)
    _world(rt, coverage={"cell": 25, "sizes": {"1": 1000},
                         "cells": [{"s": 1, "cx": 1, "cy": 1, "t": now + 60, "v": 3}]})
    cells = worldscene.scene(rt)["coverage"]["cells"]
    assert cells[0]["v"] == 0, cells
    assert cells[0]["t"] == now + 60, cells


def test_swept_ground_is_inside_what_the_canvas_opens_fitted_to():
    """Empty swept ground is a FINDING, so cropping the view to the dots would hide it."""
    rt = _fresh()
    _world(rt, mines=[{"x": 10, "y": 10, "server_id": 1}],
           coverage={"cell": 25, "sizes": {"1": 1000},
                     "cells": [{"s": 1, "cx": 30, "cy": 30, "t": int(time.time()), "v": 0}]})
    bounds = worldscene.scene(rt)["bounds"]
    assert bounds["x1"] >= 30 * 25, bounds


def test_a_block_that_wraps_the_map_edge_does_not_paint_the_whole_warzone():
    """`x0 > x1` means «both ends», never «everything between» (`proto.area_holds`)."""
    import world_index

    index = world_index.WorldIndex()
    size = 1000
    low, high = 0 * size + 990, 40 * size + 5      # (990, 0) .. (5, 40)
    index._cover({"serverPointArr": [{"serverId": 1, "maxAreaSize": size,
                                      "leftBottom": low, "rightTop": high,
                                      "viewLvl": 0, "points": []}]}, time.time())
    cells = index.coverage()["cells"]
    columns = {row["cx"] for row in cells}
    cell = world_index.COVERAGE_CELL
    assert max(columns) == (size - 1) // cell, columns
    assert 0 in columns, columns
    # …and nothing in the middle of the map, which is the failure being guarded against.
    assert not any(cell * 5 <= column * cell <= size - cell * 5 for column in columns), columns


def test_the_map_width_arrives_with_the_coverage_and_nothing_else_knew_it():
    import world_index

    index = world_index.WorldIndex()
    index._cover({"serverPointArr": [{"serverId": 7, "maxAreaSize": 1200,
                                      "leftBottom": 0, "rightTop": 1200 * 3 + 3,
                                      "viewLvl": 0, "points": []}]}, time.time())
    assert index.coverage()["sizes"] == {"7": 1200}


# -- read-only, and impossible to make otherwise ----------------------------
def test_the_map_screen_offers_no_press_at_all():
    """READ-ONLY is the person's condition, so it is pinned rather than merely true."""
    source = (_REPO_ROOT / "panel" / "tabs" / "worldview.py").read_text(encoding="utf-8")
    for forbidden in ("play_async", "rt.actions", "run_action", "lua", "web_press"):
        assert forbidden not in source, f"the map tab must not be able to {forbidden}"
    # …and the tab defines no press handler at all, so every press falls through to
    # `PanelTab.web_press`, whose answer is «панель не знает такого нажатия».
    assert "def web_press" not in source
    # Nor does the screen offer a button to press: no `actions` anywhere in the view.
    view = source.split("def web_view", 1)[1].split("def web_data", 1)[0]
    assert '"actions"' not in view, "a read-only screen has no buttons on it"


def test_the_data_route_can_only_read():
    """`/api/screen/data` is a GET, and the tab answers no kind but its own."""
    api = (_REPO_ROOT / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    get_half = api.split('if method == "GET"', 1)[1].split('elif method == "POST"', 1)[0]
    assert "/api/screen/data" in get_half, "the scene route must be a GET"
    assert "/api/screen/data" not in api.split('elif method == "POST"', 1)[1]

    # …and the tab answers no kind but its own — anything else is a 404, never a guess.
    source = (_REPO_ROOT / "panel" / "tabs" / "worldview.py").read_text(encoding="utf-8")
    data = source.split("def web_data", 1)[1]
    assert 'if kind != "map":' in data and "return None" in data


def test_the_four_kinds_are_what_records_holds_and_coverage_rides_beside_them():
    """`records()` is kind -> rows, and every reader walks its values as such.

    Coverage went INTO that mapping when it was added and broke the world monitor's own
    test: `all(row["seen_at"] for rows in records.values() for row in rows)` walked a
    dict of cells as if it were a list of sightings. It is the checkpoint's own key
    instead — the file carries it, the mapping does not.
    """
    import world_index

    index = world_index.WorldIndex()
    index._cover({"serverPointArr": [{"serverId": 1, "maxAreaSize": 1000,
                                      "leftBottom": 0, "rightTop": 1000 * 40 + 40,
                                      "viewLvl": 0, "points": []}]}, time.time())
    records = index.records()
    assert set(records) == {"mines", "trucks", "trains", "players"}, sorted(records)
    for rows in records.values():
        assert isinstance(rows, list), records
    checkpoint = index.checkpoint()
    assert checkpoint["coverage"]["cells"], checkpoint["coverage"]
    assert set(checkpoint) == set(records) | {"coverage"}, sorted(checkpoint)


def test_the_world_checkpoint_is_written_from_the_one_call_that_carries_coverage():
    """The capture writes `checkpoint()`; `records()` there would drop the sweep."""
    source = (_REPO_ROOT / "tools" / "secret_task_capture.py").read_text(encoding="utf-8")
    assert "dump_tasks(world.checkpoint(), args.world_json)" in source
    assert "dump_tasks(world.records(), args.world_json)" not in source


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
