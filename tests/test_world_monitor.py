#!/usr/bin/env python3
"""The world monitor: the mine and train decoders, the second listener, the pages.

Task #1289. Four things are worth pinning here and each of them cost something to find:

* **a mine's family and level are ONE packed number** (`f6.f1 = family * 100 + level`),
  and a family nobody has checked against the screen must not be given a name;
* **an alliance train is the truck shape with `type = 2`** — the decoder that keeps the
  trucks deliberately skips it, so the two must not be able to swallow each other;
* **the second listener is an INDEX, not a capture.** Two npcap captures over one
  interface starve each other (044c19f), so this is fed by the task capture's own hooks
  and the test proves the wiring rather than the packets;
* **a world page ages out on the SIGHTING**, because a mine has no other clock and a
  stale one claims to be free long after somebody took it.

Every fixture below is hand-written with invented values of the right SHAPE — no live
reply is pasted in (`CLAUDE.md`). What the tests are about is the field names, the
nesting and the arithmetic, and none of that needs a real account's numbers.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "tools"), str(ROOT / "tools" / "lib")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import lastwar_proto as proto            # noqa: E402
import world_index                       # noqa: E402


# --------------------------------------------------------------------------
# Fixtures — invented, of the shape the wire uses
# --------------------------------------------------------------------------
def _mine_tile(point: int, packed: int, taken_by: str | None = None) -> dict:
    node = {"f1": packed, "f2": 1}
    if taken_by:
        node.update({"f3": 1000000000000001, "f8": taken_by, "f9": 100,
                     "f10": "00000000000000000000000000000001"})
    return {"_protobuf": {"f1": point, "f2": 7, "f6": node, "f102": 100, "f103": 100}}


def _blocks(*tiles) -> dict:
    return {"serverPointArr": [{"serverId": 100, "maxAreaSize": 1000,
                                "points": list(tiles)}]}


def _march(train: dict, leg_from=(10, 20), leg_to=(30, 20),
           start=1000, end=2000) -> dict:
    return {"uuid": 1000000000000002, "ownerUid": "1000000000000003",
            "train": train,
            "_proto": {"_protobuf": {"f9": leg_from[1] * 1000 + leg_from[0],
                                     "f10": leg_to[1] * 1000 + leg_to[0],
                                     "f13": start, "f14": end, "f26": 100,
                                     "f1": "Player1", "f34": "AL1"}}}


def _truck_train() -> dict:
    return {"type": 1, "uuid": 1000000000000004, "uid": "1000000000000003",
            "name": "Player1", "abbr": "AL1", "country": "XX",
            "allianceId": "00000000000000000000000000000002",
            "cfgId": 5035, "arriveTime": 9000, "startPos": 5,
            "baseGoods": {"full": [{"type": 1, "value": 1000},
                                   {"type": 2, "value": 500}]},
            "marchInfo": {"robTimes": 1, "power": 100,
                          "plunderRecord": [{"uid": "1000000000000005"}],
                          "heroInfo": {"1": {"id": 1, "level": 2, "power": 3}}}}


def _alliance_train() -> dict:
    return {"type": 2, "uuid": 1000000000000006, "uid": "1000000000000003",
            "alliancename": "Alliance One", "allianceId":
                "00000000000000000000000000000002",
            "seasonCfgId": 1044, "completeness": 0.75, "arriveTime": 9500,
            "marchInfo": {"giftLv": 12, "robTimes": 1,
                          "carriageList": [
                              {"seatNum": 1,
                               "passengerList": [{"uid": "1000000000000003",
                                                  "name": "Player1"},
                                                 {"uid": "1000000000000005",
                                                  "name": "Player2"}]},
                              {"seatNum": 2, "passengerList": []}]}}


# --------------------------------------------------------------------------
# The mine decoder
# --------------------------------------------------------------------------
def test_a_mine_splits_its_family_and_its_level_out_of_one_number():
    """`f6.f1` is `family * 100 + level` — the whole tile is that one field."""
    payload = _blocks(_mine_tile(24011, 6),        # family 0, level 6
                      _mine_tile(24012, 110),      # family 1, level 10
                      _mine_tile(24013, 203))      # family 2, level 3
    found = list(proto.mines(payload))
    assert [(m.family, m.level) for m in found] == [(0, 6), (1, 10), (2, 3)]
    assert [m.resource for m in found] == ["bread", "iron", "gold"]
    # …and the coordinates are the server-local pair the game shows on screen.
    assert (found[0].x, found[0].y, found[0].server_id) == (11, 24, 100)


def test_a_family_nobody_has_named_stays_unnamed():
    """The fourth family turned up four times in a whole lap — that is not a name.

    A guessed resource name reads exactly like a measured one on the table, and this is
    the row where somebody would have to notice it was invented.
    """
    mine, = proto.mines(_blocks(_mine_tile(24014, 8004)))
    assert mine.family == 80 and mine.level == 4
    assert mine.resource is None, "an unmeasured family was given a name"


def test_free_and_taken_are_readable_without_any_pixels():
    """Occupation is four extra fields on the tile, so «free» needs no OCR."""
    free, taken = proto.mines(_blocks(_mine_tile(24015, 7),
                                      _mine_tile(24016, 7, "1000000000000007")))
    assert free.free is True and free.owner_uid is None
    assert taken.free is False and taken.owner_uid == "1000000000000007"
    assert taken.owner_server == 100


def test_a_mine_is_identified_by_its_tile_and_its_server():
    """It carries no uuid of its own — a gather march targets `uuid = 0`."""
    mine, = proto.mines(_blocks(_mine_tile(24017, 5)))
    assert mine.uuid == "100:24017"


def test_the_mine_filter_narrows_on_what_the_screen_and_the_wire_both_say():
    mines = list(proto.mines(_blocks(_mine_tile(24018, 210),
                                     _mine_tile(24019, 105),
                                     _mine_tile(24020, 6, "1000000000000007"))))
    assert len(proto.filter_mines(mines, resource={"gold"})) == 1
    assert len(proto.filter_mines(mines, resource={1})) == 1       # the wire's family
    assert len(proto.filter_mines(mines, free_only=True)) == 2
    assert len(proto.filter_mines(mines, level={10})) == 1


# --------------------------------------------------------------------------
# Trucks and trains must not swallow each other
# --------------------------------------------------------------------------
def test_the_two_decoders_split_the_march_stream_between_them():
    """`type = 1` is a player's truck and `type = 2` the alliance train.

    They share the march shape, which is exactly why each decoder has to refuse the
    other's: a train has a `carriageList` where a truck has an escort squad, so a caller
    handed the wrong one would special-case every field.
    """
    payload = {"marchInfos": [_march(_truck_train()), _march(_alliance_train())]}
    trucks = list(proto.trucks(payload))
    trains = list(proto.trains(payload))
    assert [t.uuid for t in trucks] == [1000000000000004]
    assert [t.uuid for t in trains] == [1000000000000006]


def test_a_train_counts_its_carriages_and_the_people_in_them():
    payload = {"marchInfos": [_march(_alliance_train())]}
    train, = proto.trains(payload)
    assert (train.seats, train.passengers) == (2, 2)
    assert train.completeness == 0.75 and train.gift_level == 12
    assert train.alliance_name == "Alliance One" and train.alliance_abbr == "AL1"
    assert train.arrive_at == 9500


def test_a_train_is_interpolated_along_the_leg_it_is_on():
    """`startPos` is not where it is and `arriveTime` is not the leg's end.

    The server describes one hop at a time, so the tile a train stands on is never a
    field — it is the leg walked by however much of it has elapsed.
    """
    payload = {"marchInfos": [_march(_alliance_train(), leg_from=(0, 0),
                                     leg_to=(100, 0), start=0, end=1000)]}
    train, = proto.trains(payload)
    train.leg_start_ms, train.leg_end_ms = None, None       # no clock -> the far end
    assert train.position == (100, 0)


# --------------------------------------------------------------------------
# The second listener
# --------------------------------------------------------------------------
def test_the_world_listener_keeps_all_three_kinds_off_the_hooks_it_is_given():
    """It is fed by the task capture's own hooks — no capture and no interface here."""
    index = world_index.WorldIndex()
    now = time.time()
    index.on_blocks(_blocks(_mine_tile(24021, 110)), (), now)
    index.on_response("push.world.march.world.get.new",
                      {"serverMarchArr": [{"marchInfos": [_march(_truck_train()),
                                                          _march(_alliance_train())]}]})
    assert index.counts() == {"mines": 1, "trucks": 1, "trains": 1, "players": 0}
    records = index.records()
    assert records["mines"][0]["resource"] == "iron"
    assert records["trucks"][0]["cargo"] == 1500
    assert records["trains"][0]["seats"] == 2
    # …and every record is stamped with when it was seen, which is what the panel ages
    # a mine out on: a mine has no other clock at all.
    assert all(row["seen_at"] for rows in records.values() for row in rows)


def test_a_command_the_listener_was_never_told_about_costs_a_lookup():
    """`on_response` sees most of the traffic, so an unlisted name must decode nothing.

    The example used to be `get.user.info.multi`, which the listener now DOES read —
    that reply is where a player's power comes from (#1335) — so it has been swapped
    for one nothing here has ever heard of. The point is unchanged: a name off the list
    must not be decoded because the payload happens to look decodable.
    """
    index = world_index.WorldIndex()
    index.on_response("no.such.command.ever", {"marchInfos": [_march(_truck_train())]})
    assert index.counts()["trucks"] == 0


def test_a_march_that_ended_takes_its_vehicle_off_the_list():
    index = world_index.WorldIndex()
    index.on_response("push.world.march.new", _march(_truck_train()))
    assert index.counts()["trucks"] == 1
    # The del names the MARCH, not the truck — which is why both are matched.
    index.on_response("push.world.march.del", {"uuid": 1000000000000002})
    assert index.counts()["trucks"] == 0


def test_leaving_a_server_drops_what_belongs_to_the_map_nobody_is_looking_at():
    """A truck goes on being interpolated and a mine goes on claiming to be free."""
    index = world_index.WorldIndex()
    index.on_blocks(_blocks(_mine_tile(24022, 5)), (), time.time())
    index.on_server_left(100, 200)
    assert index.counts()["mines"] == 0


def test_a_sighting_nobody_reconfirms_is_evicted_rather_than_served():
    index = world_index.WorldIndex(stale_after=60)
    index.on_blocks(_blocks(_mine_tile(24023, 5)), (), time.time() - 3600)
    assert index.records()["mines"] == []


def test_the_cap_keeps_the_best_and_says_how_many_it_dropped():
    """A whole-server lap finds nine thousand mines. A silent cut reads as «that is all»."""
    index = world_index.WorldIndex(max_per_kind=2)
    now = time.time()
    for n, packed in enumerate((201, 205, 210)):
        index.on_blocks(_blocks(_mine_tile(24100 + n, packed)), (), now)
    kept = index.records()["mines"]
    assert [row["level"] for row in kept] == [10, 5], kept
    assert index.dropped["mines"] == 1


# --------------------------------------------------------------------------
# The capture is told to run it — one child, two listeners
# --------------------------------------------------------------------------
def test_the_task_capture_forwards_every_hook_to_the_world_listener():
    """The wiring, which is the whole «one capture, several consumers» decision.

    Not the packets: those are `map_capture`'s and are tested where they live. What
    matters here is that a frame reaching the task index also reaches the world one —
    because the alternative, a second capture, was measured getting a trickle.
    """
    import secret_task_capture as capture

    index = object.__new__(capture.TaskIndex)
    index._tasks, index._seen_at = {}, {}
    index._shared_json = None
    index.shares_marked = 0
    index.current_server = 100
    index.world = world_index.WorldIndex()

    index.on_blocks(_blocks(_mine_tile(24024, 110)), (), time.time())
    index.on_response("push.world.march.new", _march(_truck_train()))
    assert index.world.counts() == {"mines": 1, "trucks": 1, "trains": 0,
                                    "players": 0}


def test_a_task_index_built_without_one_is_still_a_task_index():
    """The default has to be «no world listener», not «raises on the first frame»."""
    import secret_task_capture as capture

    index = object.__new__(capture.TaskIndex)
    index._shared_json = None
    index.shares_marked = 0
    index.on_response("anything.at.all", {})       # must not raise
    assert capture.TaskIndex.world is None


# --------------------------------------------------------------------------
# The pages
# --------------------------------------------------------------------------
def test_the_monster_read_is_parsed_into_rows_keyed_by_their_tile():
    """A drawn monster carries no uuid until it is selected — the tile is its identity."""
    from panel.tabs.secret_tasks import world

    text = ("src=invasion pid=24025 x=25 y=24 uuid=1000000000000008 cfg=1030000 "
            "type=7 level=19 kind=invasion | "
            "src=scene pid=24026 x=26 y=24 uuid=0 cfg=0 type=0 level=22 "
            "kind=WorldMonster01")
    rows = world.parse_monsters(text, server=100, now=1000)
    assert [r["uuid"] for r in rows] == ["100:24025", "100:24026"]
    assert rows[0]["monster_type"] == 7 and rows[0]["level"] == 19
    assert rows[1]["kind_name"] == "WorldMonster01" and rows[1]["source"] == "scene"
    assert rows[1]["cfg_id"] is None, "a zero cfg id is «not answered», not an id"


def test_a_monster_line_without_a_tile_is_not_a_row():
    """Every other field may be missing; without a tile there is nothing to draw."""
    from panel.tabs.secret_tasks import world

    assert world.parse_monsters("src=scene level=3 kind=x") == []
    assert world.parse_monsters("") == []


def test_the_checkpoint_becomes_rows_with_the_arrival_as_the_deadline():
    """A truck's `arrive_at` IS its clock — the moment it leaves the map."""
    from panel.tabs.secret_tasks import world

    mines = world.mine_records([{"uuid": "100:1", "server_id": 100, "x": 1, "y": 2,
                                 "level": 7, "resource": "gold", "family": 2,
                                 "free": True, "seen_at": 10}])
    assert mines[0]["server"] == 100 and mines[0]["resource"] == "gold"
    trucks = world.truck_records([{"uuid": 5, "server_id": 100, "x": 1, "y": 2,
                                   "arrive_at": 12345, "cargo": 100,
                                   "seen_at": 10}])
    assert trucks[0]["expires_at"] == 12345


def test_each_world_page_draws_its_own_columns():
    """The pages are the same machinery over different facts, and the facts differ.

    A mine has a resource where a task has an owner's dispatch level; if the column set
    were still a module constant every page would draw the secret-task table.
    """
    from panel.tabs.secret_tasks import grid, world

    kinds = {"mines": world.MineGrid, "monsters": world.MonsterGrid,
             "trains": world.TrainGrid, "trucks": world.TruckGrid}
    for key, page in kinds.items():
        assert page.CONFIG_KEY == key
        assert page.COLUMNS is not grid.COLUMNS, key
        ids = [c[0] for c in page.COLUMNS]
        assert ids.count("coords") == 1 and ids.count("state") == 1, ids
        # Every column that sorts has a key, and every key names a column — a heading
        # that sorts by nothing is a heading that does nothing when it is clicked.
        assert set(page.SORT_KEYS) <= set(ids), key
        assert grid.LINK_COLUMN in ids, key


def test_only_the_page_with_no_file_behind_it_keeps_one():
    """Three of the four are re-read from the capture's checkpoint — copying it is cost.

    Five thousand mines rewritten on every finding is a megabyte of disk per nudge and
    nothing gained; a monster read leaves no file at all, so that page has to keep one or
    it starts empty every session.
    """
    from panel.tabs.secret_tasks import world

    class _Tab:
        rt = type("rt", (), {"profiles": type("p", (), {
            "world_state_json": staticmethod(lambda page, name=None: "/tmp/%s" % page)})})

    for page in (world.MineGrid, world.TrainGrid, world.TruckGrid):
        assert page.state_path(object.__new__(page)) == "", page.CONFIG_KEY
    monsters = object.__new__(world.MonsterGrid)
    monsters.tab = _Tab()
    assert monsters.state_path().endswith("monsters")


def test_a_march_is_walked_along_its_leg_and_clamped_at_both_ends():
    """The server sends a hop, never a position — so the tile is arithmetic (#1298).

    One function for the truck, the train and the panel's own tables: three copies of
    five lines is three places for them to disagree about where a truck is.
    """
    walk = proto.march_position
    # Before the leg starts it is still standing where the leg starts…
    assert walk((10, 20), (30, 20), 1000, 2000, now_ms=500) == (10, 20)
    assert walk((10, 20), (30, 20), 1000, 2000, now_ms=1500) == (20, 20)
    # …and after it ends it is parked at the far end until the next hop is pushed,
    # which is what the client draws in the gap too.
    assert walk((10, 20), (30, 20), 1000, 2000, now_ms=9999) == (30, 20)
    # A leg with no times at all is not a guess: the destination is the honest answer.
    assert walk((10, 20), (30, 40), None, None, now_ms=1500) == (30, 40)
    assert walk((10, 20), (30, 40), 2000, 1000, now_ms=1500) == (30, 40)


def test_a_vehicle_row_carries_its_leg_and_moves_between_reads():
    """THE BUG #1298 IS ABOUT: the row was frozen where the capture first heard it.

    `Truck.as_dict()` computes an `x`/`y` once, at decode time, and the two record
    builders took that pair and dropped the leg it was computed from — so a truck ten
    minutes into a run was drawn on the tile it had left nine minutes earlier and never
    moved again until the server happened to re-send it.
    """
    from panel.tabs.secret_tasks import world

    raw = {"uuid": 5, "server_id": 100, "x": 10, "y": 20, "arrive_at": 9000,
           "leg_from": [10, 20], "leg_to": [30, 20],
           "leg_start_ms": 1000, "leg_end_ms": 2000, "seen_at": 10}
    record = world.truck_records([raw])[0]
    assert record["leg_from"] == [10, 20] and record["leg_end_ms"] == 2000
    # …and the same for a train, which rides the very same march shape.
    train = world.train_records([dict(raw, uuid=6)])[0]
    assert train["leg_to"] == [30, 20] and train["leg_start_ms"] == 1000

    row = dict(record, leg_from=[10, 20], leg_to=[30, 20])
    assert world.vehicle_position(row, now_ms=1500) == (20, 20)
    assert world.vehicle_position(row, now_ms=9999) == (30, 20)
    # A row with no leg is left where it is rather than moved to the corner of the map:
    # a checkpoint written before the leg was kept has an `x`/`y` and nothing to walk.
    assert world.vehicle_position({"x": 1, "y": 2}) is None

    # …and `advance` is what the second's tick calls: it moves the row and says so, so
    # the table redraws instead of only repainting its clocks.
    page = object.__new__(world.TruckGrid)
    page._rows = {"5": row}
    moved = page.advance()
    assert moved is True and (row["x"], row["y"]) == world.vehicle_position(row)
    # The leg survives a restart — a checkpointed vehicle goes on moving after it is
    # read back, which it cannot do without the four fields.
    for field in ("leg_from", "leg_to", "leg_start_ms", "leg_end_ms"):
        assert field in world.TruckGrid.PERSIST_KEYS, field
        assert field in world.TrainGrid.PERSIST_KEYS, field


def test_a_live_coordinate_and_a_frozen_one_do_not_look_the_same():
    """The row says whether its own number is alive — «где» beside «успею ли» (#1298).

    A coordinate walked along a running hop and one left over from the last thing the
    server said are the same six characters on screen, and only one of them is an answer
    to «where is it». So the leg's far end is drawn beside the tile, and it is the leg's
    STATE that is said there: moving, standing, or «we were never told the route».

    It is the NEXT STOP and not the destination, and the wording has to keep that
    straight: the server describes one hop at a time (a truck went `A → B` then `B → C`
    across two re-sends), and where the whole run ends is not on the wire at all.
    """
    from panel.tabs.secret_tasks import world

    row = {"uuid": 5, "leg_from": [10, 20], "leg_to": [30, 20],
           "leg_start_ms": 1000, "leg_end_ms": 2000}
    assert world.vehicle_leg(row, now_ms=1500)[0] == world.LEG_MOVING
    # The hop is over and no new one has been pushed: the vehicle really is standing at
    # the far end — that is what the client draws too — so «стоит», not «→».
    assert world.vehicle_leg(row, now_ms=5000)[0] == world.LEG_PARKED
    assert world.vehicle_leg({"x": 1, "y": 2})[0] == world.LEG_NONE

    page = object.__new__(world.TruckGrid)
    page.tab = type("t", (), {"t": staticmethod(lambda key, **fmt: key)})()
    assert page.next_stop_text({"x": 1, "y": 2}) == "world.vehicle.leg_unknown"

    # …and the flip from «moving» to «standing» is a CELL CHANGE with no movement behind
    # it, so `advance` has to report it or the row would freeze still claiming to move.
    parked = dict(row, x=30, y=20, leg_state=world.LEG_MOVING)
    page._rows = {"5": parked}
    assert page.advance() is True
    assert parked["leg_state"] == world.LEG_PARKED
    assert page.advance() is False, "a settled row must not ask for a redraw every tick"

    # Both vehicle pages draw it, and the heading sorts — a column that does nothing when
    # it is clicked is a column that lies about being one.
    for grid_cls in (world.TruckGrid, world.TrainGrid):
        ids = [c[0] for c in grid_cls.COLUMNS]
        assert "next" in ids and "next" in grid_cls.SORT_KEYS, grid_cls.CONFIG_KEY
        labels = {c[0]: c[1] for c in grid_cls.COLUMNS}
        assert labels["next"] == "world.col.next_stop"
    # A row with no route sorts last whatever its coordinate says: it is the one row whose
    # point is not an answer to «where is it».
    assert world._next_stop_key({"uuid": 1, "leg_state": world.LEG_MOVING,
                                 "leg_to": [9, 9]}) < world._next_stop_key(
        {"uuid": 2, "leg_state": world.LEG_NONE, "leg_to": []})


def test_a_page_that_stands_still_never_claims_to_have_moved():
    """`advance` costs a redraw, so only the two pages that move may ask for one."""
    from panel.tabs.secret_tasks import grid, world

    for page in (world.MineGrid, world.MonsterGrid):
        still = object.__new__(page)
        still._rows = {"1": {"x": 1, "y": 2}}
        assert still.advance() is False, page.CONFIG_KEY
    assert grid.TaskGrid.advance(object.__new__(grid.TaskGrid)) is False


def test_a_cargo_is_written_the_way_a_person_reads_one():
    from panel.tabs.secret_tasks import world

    assert world.human_number(0) == "0"
    assert world.human_number(999) == "999"
    assert world.human_number(14094000) == "14.1M"


def test_the_capture_is_asked_for_the_world_checkpoint_in_the_same_child():
    """One capture, two listeners — the panel must never launch a second (044c19f)."""
    src = (ROOT / "panel" / "tabs" / "secret_tasks" / "capture.py").read_text(
        encoding="utf-8")
    assert "--world-json" in src
    assert "world_json()" in src
    # …and it rides the SECRET-TASK capture, never a third script of its own.
    head, _, _tail = src.partition("--world-json")
    assert "SECRET_TASK_CAPTURE" in head


def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print("FAIL %s: %s" % (test.__name__, exc))
        else:
            print("ok %s" % test.__name__)
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
