r"""Unit tests for the shared-secret-mission decoder and its live monitor.

Unlike ``test_city_world_roundtrip.py`` this needs no game and no Wireshark —
it decodes a frame captured earlier (``results/rob_trap.jsonl``) plus a couple
of synthetic ones, so it runs anywhere:

    python3 tests/test_share_missions.py        # standalone, prints PASS/FAIL
    pytest tests/test_share_missions.py         # or under pytest

Exit codes (standalone): 0 = passed, 1 = failed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lastwar_proto as proto  # noqa: E402
import secret_mission_capture as smc  # noqa: E402

# The one real alliance.share.mission.add frame on record: a starred level-7
# mission on server 946. cfgId 60000701 = family "6000" (starred), level 07.
_CAPTURE = _REPO_ROOT / "results" / "rob_trap.jsonl"


def _real_share_frame():
    """The captured ``push.alliance.share.mission.add`` envelope, or None."""
    if not _CAPTURE.exists():
        return None
    with open(_CAPTURE, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("command") == "push.alliance.share.mission.add":
                return row["envelope"]
    return None


def test_decode_push_add():
    """The live broadcast decodes to one starred level-7 mission."""
    payload = {"missionCfgId": 60000701, "missionUuid": 1394584906709054020,
               "missionCurrentServerId": 946, "shareUid": "1522777203000972",
               "shareAllianceId": "3d4b9dee7b854f4a94810f7bb8b43089",
               "missionPlayerServerId": 946}
    missions = list(proto.share_missions("push.alliance.share.mission.add",
                                         payload))
    assert len(missions) == 1
    m = missions[0]
    assert m.uuid == 1394584906709054020
    assert m.cfg_id == 60000701
    assert m.family == "6000"
    assert m.level == 7
    assert m.server_id == 946
    assert m.owner_server_id == 946
    assert m.starred is True
    assert m.is_special is False


def test_list_command_and_empty():
    """The snapshot command reads ``shareMissionArr``; empty yields nothing."""
    assert list(proto.share_missions("get.alliance.share.mission.list",
                                     {"shareMissionArr": []})) == []
    arr = {"shareMissionArr": [
        {"missionCfgId": 60000701, "missionUuid": 1},
        {"missionCfgId": 50000704, "missionUuid": 2},   # family 5000, unstarred
    ]}
    got = list(proto.share_missions("get.alliance.share.mission.list", arr))
    assert [m.uuid for m in got] == [1, 2]
    assert [m.starred for m in got] == [True, False]


def test_non_share_command_yields_nothing():
    assert list(proto.share_missions("world.get.block",
                                     {"serverPointArr": []})) == []


def test_filter_share_missions():
    arr = {"shareMissionArr": [
        {"missionCfgId": 60000701, "missionUuid": 1, "missionCurrentServerId": 946},  # 6000 L7 star
        {"missionCfgId": 50000504, "missionUuid": 2, "missionCurrentServerId": 946},  # 5000 L5
        {"missionCfgId": 60000801, "missionUuid": 3, "missionCurrentServerId": 999},  # 6000 L8 star
    ]}
    missions = list(proto.share_missions("get.alliance.share.mission.list", arr))
    assert {m.uuid for m in proto.filter_share_missions(missions, star_only=True)} == {1, 3}
    assert {m.uuid for m in proto.filter_share_missions(missions, level={7})} == {1}
    assert {m.uuid for m in proto.filter_share_missions(missions, server=999)} == {3}


def test_roundtrip_as_dict():
    m = proto.ShareMission(uuid=5, cfg_id=60000701, family="6000", level=7,
                           server_id=946, owner_server_id=946,
                           share_uid="u", share_alliance_id="a")
    assert proto.ShareMission.from_dict(m.as_dict()) == m


def test_monitor_dedupes_and_filters():
    """Feeding the same broadcast twice announces once, counts twice."""
    env = _real_share_frame()
    if env is None:  # capture fixture absent — skip this one, keep the rest
        return
    mon = smc.MissionMonitor()
    mon.emit("down", env)
    mon.emit("down", env)
    assert mon.frames == 2
    assert len(mon._missions) == 1
    assert len(mon._announced) == 1
    rec = mon.records()[0]
    assert rec["share_count"] == 2
    assert rec["starred"] is True

    # An "up" frame (client request) is never a shared-mission broadcast.
    up = smc.MissionMonitor()
    up.emit("up", env)
    assert len(up._missions) == 0

    # --level 3 filters this level-7 mission out of the announcements, but it is
    # still recorded (state is kept regardless of the display filter).
    lvl = smc.MissionMonitor(level={3})
    lvl.emit("down", env)
    assert len(lvl._missions) == 1
    assert len(lvl._announced) == 0


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
