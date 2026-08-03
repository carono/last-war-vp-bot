"""The world-map treasure decode (`f2 = 21`) and the scan that indexes it.

Everything here runs against the one live treasure ever captured — task #1107,
trimmed into ``tests/fixtures/world_treasure_points.json``: the chest while it was
still being dug, the frame its finisher appeared in, and the
``push.detect.treasure.claim`` broadcast that says who finished it.

That pair of point frames is the whole point of the fixture. The dug/digging split
is a single field (`f11.f7`, the operator uid) that is absent in one and present in
the other, and the feature turns on it: a chest still being dug wants a march, a dug
one wants the claim. A decode that got it backwards would send the wrong press at a
real treasure, and there is no second capture to catch that with.

    /mnt/c/Python312/python.exe tests/test_world_treasures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import lastwar_proto as proto  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "world_treasure_points.json"


def _frames() -> list:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["frames"]


def _points() -> list:
    return [f for f in _frames() if f["command"] == "push.world.point.update"]


def test_a_treasure_point_decodes_whole():
    first = _points()[0]
    got = list(proto.world_treasure_points(first["command"], first["payload"]))
    assert len(got) == 1, got
    t = got[0]
    assert t.uuid == 1397117530950313784
    assert t.cfg_id == "25193"
    assert t.server_id == 935
    assert t.point_id == 500553
    assert t.name == "Uzilla"
    assert t.alliance_abbr == "ALLY"
    assert t.owner_uid == "1000000000015935"
    # The coordinates are unpacked the way every other tile in the module is; the
    # game's own IndexToTilePos answers one lower on x (see the module comment), so
    # this is pinned deliberately rather than left to drift.
    assert (t.x, t.y) == (553, 500)


def test_the_finisher_is_what_says_it_is_dug():
    """The whole dug/digging split, against the two frames that differ by it."""
    points = _points()
    digging = next(iter(proto.world_treasure_points(points[0]["command"],
                                                    points[0]["payload"])))
    dug = next(iter(proto.world_treasure_points(points[-1]["command"],
                                                points[-1]["payload"])))
    assert digging.operator_uid is None and digging.dug is False
    assert dug.dug is True
    # …and it is the same person the claim broadcast names.
    claim = next(f for f in _frames() if f["command"] == "push.detect.treasure.claim")
    assert dug.operator_uid == claim["payload"]["operator"]["uid"]
    assert dug.uuid == claim["payload"]["uuid"]


def test_a_removed_point_is_not_a_treasure():
    """A `remove` update means the chest is gone — yielding it would list a ghost."""
    frame = _points()[0]
    payload = dict(frame["payload"], type="remove")
    assert list(proto.world_treasure_points(frame["command"], payload)) == []
    # And a frame that is not a point update yields nothing at all.
    assert list(proto.world_treasure_points("push.mail", frame["payload"])) == []


def test_block_and_push_paths_agree():
    """The same point, wrapped as a `world.get.block` response, decodes the same."""
    frame = _points()[-1]
    point = frame["payload"]["points"][0]
    block_payload = {"serverPointArr": [{"maxAreaSize": 1000, "points": [point]}]}
    from_block = next(iter(proto.world_treasures(block_payload)))
    from_push = next(iter(proto.world_treasure_points(frame["command"],
                                                      frame["payload"])))
    assert from_block.as_dict() == from_push.as_dict()


def test_a_record_round_trips_through_the_checkpoint():
    frame = _points()[-1]
    original = next(iter(proto.world_treasure_points(frame["command"],
                                                     frame["payload"])))
    again = proto.WorldTreasure.from_dict(original.as_dict())
    assert again.as_dict() == original.as_dict()
    assert again.dug is True


def test_the_checkpoint_loader_drops_what_the_map_stopped_re_sending():
    import tempfile
    import time
    frame = _points()[-1]
    treasure = next(iter(proto.world_treasure_points(frame["command"],
                                                     frame["payload"])))
    now = time.time()
    fresh = treasure.as_dict() | {"seen_at": int(now)}
    stale = treasure.as_dict() | {"uuid": 1, "seen_at": int(now - 9999)}
    undated = treasure.as_dict() | {"uuid": 2}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump([fresh, stale, undated], fh)
        path = fh.name
    kept = proto.load_fresh_treasures(path, now=now)
    assert [t.uuid for t in kept] == [treasure.uuid], [t.uuid for t in kept]


def test_the_scan_index_walks_digging_to_dug():
    """The capture tool's index: one chest, one row, and the dug flag flips in place."""
    sys.path.insert(0, str(ROOT / "tools" / "dev"))
    try:
        import treasure_capture
    except Exception as exc:            # noqa: BLE001 — scapy is Windows-only here
        print(f"  SKIP no capture stack: {exc}")
        return
    index = treasure_capture.TreasureIndex()
    points = _points()
    for frame in points:
        index.on_response(frame["command"], frame["payload"])
    assert len(index.treasures) == 1, index.treasures
    assert index.dug_count == 1
    records = index.records()
    assert len(records) == 1 and records[0]["seen_at"] > 0
    # A `remove` for the same point retires the row rather than leaving it to age.
    index.on_response("push.world.point.update",
                      dict(points[-1]["payload"], type="remove"))
    assert index.treasures == [] and index.removed == 1


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
