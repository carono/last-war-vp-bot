r"""The speed-up parcel that closes a construction, run OFFLINE (#2634).

Both chunks — the one `read_ready_buildings.md` prices a running slot with and the one
`finish_building.md` spends by — are plain Lua over the client's own tables, so they can
be run against a made-up bag with no game anywhere near: `lupa` compiles the chunk out of
the recipe file itself, so what is tested is the shipped text and not a copy of it.

What it pins is the rule the parcel is chosen by (CLAUDE.md, «arms_race_speedup.md»):
specialised before universal, small denominations before large, the last piece allowed to
overshoot — and **one entry per item id**, because the overshoot used to stand beside the
entry of its own denomination and made a row read «5017×1 min + 1×1 min».

    python3 tests/test_finish_building_plan.py
"""
from __future__ import annotations

TIER = "offline"     # no Tk, no game — see tools/run_tests.py

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ROOT / "src" / "lastwar_bot" / "actions"

#: A bag of the shape the game hands over: `speedUpType` 7 building, 1 universal, and
#: `para3` — what one piece is worth in SECONDS — arriving as a STRING, which is how the
#: client really answers it. The counts are invented and look it.
BAG = [(200210, 7, "60", 10), (200211, 7, "300", 4), (200213, 7, "3600", 2),
       (200200, 1, "60", 50), (200201, 1, "300", 50)]


def _lua():
    try:
        import lupa
    except Exception as exc:                       # noqa: BLE001 — no lupa, no test
        print(f"  SKIP no lupa: {exc}")
        return None
    return lupa.LuaRuntime(unpack_returned_tuples=True)


def _world(lua, left: int, bag=BAG):
    """The handful of globals the chunks touch, with one slot running for `left` seconds."""
    lua.execute("""
        NewQueueType = {Default = 0}
        NewQueueState = {Free = 0, Prepare = 1, Work = 2, Finish = 3}
        UITimeManager = {GetInstance = function() return {GetServerSeconds =
            function() return 1000000 end} end}
        DataCenter = {QueueDataManager = {queueDic = {}}, ItemData = {}, BuildManager = {
            GetBuildingDataByUuid = function(_, _) return {itemId = 10209000, level = 34} end,
            GetBuildIconPath = function(_, _, _) return 'Assets/x/UI_building_10209000' end,
            GetBuildingNameByUuid = function(_, _) return 'Works' end}}
    """)
    lua.execute("DataCenter.QueueDataManager.queueDic = {[1] = {type = 0, state = 2, "
                "itemId = '1000000000000001', uuid = '2000000000000001', endTime = (1000000 + %d) * 1000}}"
                % left)
    rows = ", ".join("{itemId = %d, speedUpType = %d, para3 = '%s', count = %d}" % row
                     for row in bag)
    lua.execute("local rows = {%s} DataCenter.ItemData.GetItemsByType = "
                "function(_, _) return rows end" % rows)


def _chunk(recipe: str, into: str) -> str:
    """The `READ_LUA … INTO <name>` of a shipped recipe, as a runnable expression.

    `lupa.eval` wraps what it is given in a `return` of its own, so the expression
    travels bare.
    """
    for line in (ACTIONS / recipe).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^READ_LUA\s+(.+)\s+INTO\s+%s\s*$" % into, line.strip())
        if m:
            return m.group(1)
    raise AssertionError(f"{recipe} no longer answers {into}")


def _parcel(answer: str) -> list:
    """`uuid|id|lv|icon|name|left|covered|plan` -> the plan, as tuples."""
    parts = answer.split("|")
    return [tuple(int(x) for x in bit.split(":")) for bit in parts[7].split("+") if bit]


# ---------------------------------------------------------------------------
def test_the_parcel_is_specialised_first_small_first_and_covers_the_build():
    lua = _lua()
    if lua is None:
        return
    _world(lua, 1000)
    answer = lua.eval(_chunk("read_ready_buildings.md", "building_builds"))
    row = str(answer).split(" ;; ")[0]
    assert row.split("|")[5] == "1000", row
    assert row.split("|")[6] == "1", "the bag can close a build of 1000 s"
    plan = _parcel(row)
    # Specialised before universal, and small before large INSIDE each kind — the
    # order the entries are taken in, which is the order they are written in.
    order = [(-own, sec) for _id, _n, sec, own in plan]
    assert order == sorted(order), "specialised first, small first: %s" % plan
    # …and the hour-long specialised piece is NOT spent on a build with 1000 s left:
    # two universal minutes are the cheaper way to the same closed construction.
    assert 200213 not in [item[0] for item in plan], plan
    assert sum(n * sec for _id, n, sec, _o in plan) >= 1000, plan


def test_the_overshooting_piece_is_folded_into_its_own_denomination():
    """The row says «11×1 min», never «10×1 min + 1×1 min» (#2634)."""
    lua = _lua()
    if lua is None:
        return
    # 610 s against ten one-minute pieces and nothing else: 600 s of them, then one more.
    _world(lua, 610, bag=[(200210, 7, "60", 20)])
    row = str(lua.eval(_chunk("read_ready_buildings.md", "building_builds"))).split(" ;; ")[0]
    plan = _parcel(row)
    assert len(plan) == 1, "one entry per item id: %s" % plan
    assert plan[0][:3] == (200210, 11, 60), plan
    assert row.split("|")[6] == "1"


def test_a_bag_that_cannot_close_it_says_so_and_the_press_refuses():
    lua = _lua()
    if lua is None:
        return
    _world(lua, 100000, bag=[(200210, 7, "60", 3)])
    row = str(lua.eval(_chunk("read_ready_buildings.md", "building_builds"))).split(" ;; ")[0]
    assert row.split("|")[6] == "0", "three minutes do not close a day-long build"
    # …and the press works the same sum out for itself and sends nothing.
    lua.execute("DataCenter.__lw_fin = {uuid = '1000000000000001'}")
    assert int(lua.eval(_chunk("finish_building.md", "finish_go"))) == 0
    why = str(lua.eval("DataCenter.__lw_fin.why"))
    assert "short of closing this construction" in why, why


def test_the_press_plans_one_send_per_denomination():
    lua = _lua()
    if lua is None:
        return
    _world(lua, 610, bag=[(200210, 7, "60", 20)])
    lua.execute("DataCenter.__lw_fin = {uuid = '1000000000000001'}")
    assert int(lua.eval(_chunk("finish_building.md", "finish_go"))) == 1
    assert int(lua.eval("#DataCenter.__lw_fin.plan")) == 1
    assert int(lua.eval("DataCenter.__lw_fin.plan[1].num")) == 11
    assert int(lua.eval("DataCenter.__lw_fin.num")) == 11


def test_it_refuses_a_building_that_is_not_running():
    lua = _lua()
    if lua is None:
        return
    _world(lua, 610)
    lua.execute("DataCenter.__lw_fin = {uuid = '1000000000000009'}")
    assert int(lua.eval(_chunk("finish_building.md", "finish_go"))) == 0
    assert "not under construction" in str(lua.eval("DataCenter.__lw_fin.why"))


def _main() -> int:
    bad = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            bad += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{'all green' if not bad else str(bad) + ' failed'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
