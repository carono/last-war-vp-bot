r"""What a heal costs, and which packs pay for it — offline, on a stubbed client (#2085).

No game and no window: the bill chunk and the pack-opening chunk are RUN under lupa
against a client made of the same shapes the live one answered with, so the arithmetic
and — much more importantly — the refusals are pinned::

    python3 tests/test_hospital_bill.py

What is worth pinning:

  * the bill names the resources the WOUNDED TYPES charge (`rescue_consume`), prices the
    portion by that list and reads the balances beside it;
  * a portion prices only the soldiers it will actually send, highest tier first — the
    same order the heal itself spends;
  * a price that could not be read is -1 and never 0, and nothing is opened for it;
  * the bag opens only when asked, only for a shortfall, only for the packs the GAME's
    own plan names, and never for an item that is not a resource pack.

The last four are the whole safety of the feature: each one of them, got wrong, spends
somebody's inventory on a guess.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "src", _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lua_actions  # noqa: E402

try:
    import lupa  # noqa: E402
except Exception:                                    # pragma: no cover - no lupa here
    lupa = None


#: A client with two wounded types, two resources and a bag — the same shapes the live
#: one answered with on 2026-09-02, with invented ids and amounts.
_CLIENT = r"""
DataCenter = {}
DataCenter.HospitalManager = {allHospital = {
  [3013] = {armyId = 3013, dead = 100},
  [3014] = {armyId = 3014, dead = 10},
}}
DataCenter.ItemData = {ItemInfos = {
  {itemId = 400202, uuid = 'u1', count = 3},
  {itemId = 400202, uuid = 'u2', count = 5},
  {itemId = 400204, uuid = 'u3', count = 2},
}}
DataCenter.ItemTemplateManager = {}
function DataCenter.ItemTemplateManager:GetItemTemplate(id)
  local kinds = {[400202] = 3, [400204] = 3, [850113] = 137}
  return {id = id, type = kinds[id] or 137}
end

LOCAL_ROWS = {
  [3013] = '1;10|14;10',
  [3014] = '1;100|14;100',
}
LocalController = {}
function LocalController.instance()
  return {getValue = function(self, table_, id, field) return LOCAL_ROWS[id] end}
end

OWN = {[1] = 500, [14] = 5000}
CommonUtil = {}
function CommonUtil.GetOwnCountByCommonCostType(kind, id)
  if kind ~= 1 then return 0 end
  return OWN[id] or 0
end
function CommonUtil.GetResourceNameByType(id)
  return ({[1] = 'Metal', [14] = 'Food'})[id] or ('res' .. tostring(id))
end

PLAN = {}
LWResourceLackUtil = {}
function LWResourceLackUtil:GetResItemsToSupplementDatas(res, lack)
  return PLAN[res] or {}
end

SENT = {}
MsgDefines = {ItemUse = 'item.use'}
SFSNetwork = {}
function SFSNetwork.SendMessage(kind, payload)
  SENT[#SENT + 1] = {kind = kind, uuid = payload.uuid, num = payload.num}
end

CS = {UnityEngine = {Debug = {LogError = function(_) end}}}
"""


def _lua(portion=0, chests=0, plan=None, no_ctrl=True):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    if no_ctrl:
        # the window controller is absent offline; the bill must survive that, because
        # the number it would give is a COMPARISON and never what the run pays by.
        lua.execute("package = {loaded = {}} function require(_) error('no ui') end")
    lua.execute("DataCenter.__lw_heal_portion = %d" % portion)
    lua.execute("DataCenter.__lw_heal_chests = %d" % chests)
    for res, rows in (plan or {}).items():
        lua.execute("PLAN[%d] = {%s}"
                    % (res, ", ".join("{itemId = %d, count = %d}" % (i, n) for i, n in rows)))
    return lua


def _bill(lua):
    lua.execute(lua_actions.hospital_heal_bill())
    return lua.eval(lua_actions.hospital_bill_report())


def _row(lua, name):
    """The bill's row for one resource, as a plain dict."""
    out = {}
    n = int(lua.eval("#DataCenter.__lw_heal_bill.res"))
    for i in range(1, n + 1):
        r = lua.eval("DataCenter.__lw_heal_bill.res[%d]" % i)
        out[r["name"]] = {"need": int(r["need"]), "own": int(r["own"]), "lack": int(r["lack"])}
    return out[name]


def test_the_bill_prices_every_wounded_soldier_by_its_own_type():
    lua = _lua()
    _bill(lua)
    # 100 x 10 + 10 x 100 = 2000, of each resource the two types name
    assert _row(lua, "Metal") == {"need": 2000, "own": 500, "lack": 1500}
    assert _row(lua, "Food") == {"need": 2000, "own": 5000, "lack": 0}


def test_a_portion_prices_only_the_soldiers_it_will_send_and_the_best_first():
    lua = _lua(portion=10)
    _bill(lua)
    # the ceiling is spent on the HIGHEST type first: ten of 3014, at 100 each
    assert _row(lua, "Metal")["need"] == 1000
    assert int(lua.eval("DataCenter.__lw_heal_bill.sent")) == 10
    assert int(lua.eval("DataCenter.__lw_heal_bill.all")) == 110


def test_a_type_the_config_cannot_price_is_not_invented():
    lua = _lua()
    lua.execute("LOCAL_ROWS[3014] = nil")
    _bill(lua)
    assert _row(lua, "Metal")["need"] == 1000, "a soldier with no price list was priced anyway"


def test_an_empty_hospital_costs_nothing_and_says_so():
    lua = _lua()
    lua.execute("DataCenter.HospitalManager.allHospital = {}")
    assert _bill(lua) == "nothing to pay for"


def test_a_bill_that_could_not_be_read_is_not_a_free_heal():
    lua = _lua()
    lua.execute("DataCenter.HospitalManager = nil")
    said = _bill(lua)
    assert said.startswith("unknown"), said
    assert int(lua.eval("#DataCenter.__lw_heal_bill.res")) == 0


def _open(lua):
    lua.execute(lua_actions.hospital_open_res_packs())
    return lua.eval(lua_actions.hospital_packs_report())


def test_nothing_is_opened_unless_the_run_was_told_it_may():
    lua = _lua(chests=0, plan={1: [(400202, 2)]})
    _bill(lua)
    assert "not asked" in _open(lua)
    assert int(lua.eval("#SENT")) == 0


def test_nothing_is_opened_on_a_bill_that_was_never_read():
    lua = _lua(chests=1, plan={1: [(400202, 2)]})
    lua.execute("DataCenter.HospitalManager = nil")
    _bill(lua)
    said = _open(lua)
    assert "opened nothing" in said, said
    assert int(lua.eval("#SENT")) == 0


def test_the_shortfall_is_covered_by_the_packs_the_game_itself_names():
    lua = _lua(chests=1, plan={1: [(400202, 6)]})
    _bill(lua)
    said = _open(lua)
    # six asked for, and the stacks are spent in turn: 3 out of the first, 3 of the second
    assert "asked=6 opened=6" in said, said
    sent = [(lua.eval("SENT[%d].uuid" % i), int(lua.eval("SENT[%d].num" % i)))
            for i in range(1, int(lua.eval("#SENT")) + 1)]
    assert sent == [("u1", 3), ("u2", 3)], sent


def test_a_resource_that_is_not_short_is_left_alone():
    lua = _lua(chests=1, plan={1: [(400202, 6)], 14: [(400204, 99)]})
    _bill(lua)
    said = _open(lua)
    assert "400204" not in said, "a resource the base has plenty of was paid for anyway"


def test_an_item_the_plan_names_that_is_not_a_resource_pack_is_refused():
    lua = _lua(chests=1, plan={1: [(850113, 4)]})
    _bill(lua)
    said = _open(lua)
    assert "not-a-pack" in said, said
    assert int(lua.eval("#SENT")) == 0, "a hero shard was spent on a heal"


def test_a_bag_that_runs_out_says_so_rather_than_pretending():
    lua = _lua(chests=1, plan={1: [(400202, 20)]})
    _bill(lua)
    said = _open(lua)
    assert "opened=8 ran-out" in said, said


def _main() -> int:
    if lupa is None:
        print("lupa is not installed — nothing to run")
        return 0
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    bad = 0
    for t in tests:
        try:
            t()
            print("  ok   %s" % t.__name__)
        except Exception as exc:                       # noqa: BLE001
            bad += 1
            print("  FAIL %s: %s: %s" % (t.__name__, type(exc).__name__, exc))
    print("\n%d/%d passed" % (len(tests) - bad, len(tests)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
