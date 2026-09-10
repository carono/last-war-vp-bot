r"""The second count: what the CLIENT got, so our own tally can be subtracted (#2740).

The owner's report is one sentence — «сбор сущностей с карты … максимально стабильным,
чтобы ничего мимо нас из провода не утекало» — and it could not be answered, because
there was only ever ONE count. Everything the panel knows about the map arrives through a
passive pcap child, and a child that misses frames looks exactly like ground with nothing
on it.

So there are two counts now, of the same ground at the same moment:

* the WIRE's, which the capture has always kept (`MapIndex.tile_kinds`) and now says out
  loud every tick (`##KINDS##`);
* the CLIENT's, out of its own `WorldScene.PointManager` (`AUDIT_MAP`).

This pins the halves that can be checked with no game in the room. No Tk, no client::

    python3 tests/test_map_intake_audit.py
    C:\Python312\python.exe tests\test_map_intake_audit.py
"""
from __future__ import annotations

import os
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools" / "lib"))
sys.path.insert(0, str(_REPO / "src"))

TIER = "offline"


def test_the_census_names_every_kind_this_repository_reads():
    """A name means «something here decodes it»; a number means «nobody does yet»."""
    import lastwar_proto as proto

    for kind in (6, proto.MINE_TILE_TYPE, 17, proto.WORLD_TREASURE_TILE_TYPE,
                 proto.ALLIANCE_CITY_TILE_TYPE, proto.GHOST_RECON_TILE_TYPE,
                 proto.ALLIANCE_FACILITY_TILE_TYPE):
        name = proto.tile_kind_name(kind)
        assert not name.startswith("f2="), f"{kind} has a reader and no name: {name}"


def test_the_client_census_is_one_expression_and_says_why_it_cannot_answer():
    """A client that cannot be asked must SAY so — an empty count reads as empty ground."""
    import lua_actions

    chunk = lua_actions.map_intake_census(3)
    assert chunk.startswith("(function()") and chunk.rstrip().endswith("end)()"), (
        "AUDIT_MAP's read must be an expression, so READ_LUA's channel carries it")
    for why in ("why=no-point-manager", "why=no-camera-tile"):
        assert why in chunk, f"the census cannot say {why}"
    assert "GetType().Name" in chunk, (
        "the KIND is the class name of what the point store returns — `pointType` is nil "
        "through this bridge and reflection over the properties comes back empty")
    assert "GetPointInfo" in chunk


def test_the_census_asks_the_box_it_was_given():
    import lua_actions

    assert "local box = 3\n" in lua_actions.map_intake_census(3)
    assert "local box = 40\n" in lua_actions.map_intake_census()


def test_audit_map_parses_with_and_without_a_box():
    from lastwar_bot import script_engine as se

    one = se.parse_text("AUDIT_MAP INTO client")[0]
    assert type(one).__name__ == "AuditMapStmt" and one.box == 40 and one.var == "client"
    two = se.parse_text("AUDIT_MAP BOX 12 INTO seen")[0]
    assert two.box == 12 and two.var == "seen"


def test_the_recipe_walks_before_it_counts_and_refuses_an_unnamed_warzone():
    """A sector read from the base counts nothing, and an empty warzone slot jumps HOME."""
    from lastwar_bot import script_engine as se

    text = (_REPO / "src" / "lastwar_bot" / "actions"
            / "audit_map_intake.md").read_text(encoding="utf-8")
    source, merged = se.prepare_source(text, {"server": 954})
    assert merged["server"] == 954 and merged["zoom"] == 600
    kinds = [type(s).__name__ for s in se.parse_text(source)]
    assert "VisitMapStmt" in kinds and "AuditMapStmt" in kinds
    assert kinds.index("VisitMapStmt") < kinds.index("AuditMapStmt"), (
        "the client is counted before the ground it is counted over has been loaded")
    assert "FAIL" in text and "server == 0" in text


def test_an_unknown_kind_names_its_SHAPE_and_never_a_value():
    """«f2=61: 23» says a kind is leaking past and nothing about what it is (#2740).

    The field names are where decoding starts, and they are shape rather than identity —
    which is exactly why the VALUES may not come with them: this line lands in
    `panel.log`, a file people send each other when something goes wrong.
    """
    import sys as _sys
    import types

    _sys.path.insert(0, str(_REPO / "tools" / "lib"))
    import map_capture

    index = object.__new__(map_capture.MapIndex)
    index.tile_shapes = {}
    blocks = [{"points": [
        {"_protobuf": {"f1": 700200, "f2": 61, "f100": 1000000000000000001,
                       "f102": 8128,
                       "f61": {"f1": "1000000000000001", "f4": 7, "f9": "AL1"}}},
        {"_protobuf": {"f1": 700201, "f2": 7, "f6": {"f1": 3}}},
    ]}]
    map_capture.MapIndex._note_shapes(index, blocks, {61: 1, 7: 1})
    assert set(index.tile_shapes) == {61}, (
        "a kind with a reader needs no shape, and an unknown one does: "
        f"{index.tile_shapes}")
    shape = index.tile_shapes[61]
    assert "f61{f1,f4,f9}" in shape, shape
    for value in ("1000000000000001", "AL1", "8128", "700200"):
        assert value not in shape, f"the shape carries a VALUE: {shape}"
    # …and it is recorded once: a second block of the same kind must not walk it again.
    index.tile_shapes[61] = "sentinel"
    map_capture.MapIndex._note_shapes(index, blocks, {61: 1})
    assert index.tile_shapes[61] == "sentinel"


def test_the_capture_says_the_census_every_tick_rather_than_when_it_exits():
    """The whole point: a capture the panel started never exits, so a census printed only
    in the summary is a census nobody has ever read."""
    tool = (_REPO / "tools" / "secret_task_capture.py").read_text(encoding="utf-8")
    tick = tool[tool.index("while deadline is None"):]
    assert "KINDS_MARKER + " in tick, "the census is not printed on the tick"
    assert "if census != last_census:" in tick, (
        "a cumulative census repeated every tick is a log nobody can read past")


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001 — a test runner
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"ok {name}")
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(1 if failed else 0)
