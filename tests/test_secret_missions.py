r"""Unit tests for the secret-mission decoders and the live monitor.

Two protocol families are covered, both decoded from frames captured earlier —
no game and no Wireshark needed, so this runs anywhere:

  * ghost recon ("Операция Призрак") — the real *секретная миссия*, captured
    live 2026-07-23 into ``tests/fixtures/ghost_recon_task_list.json``;
  * alliance-shared tasks (``alliance.share.mission.*``) — the related but
    distinct share stream, from inline sample payloads.

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

_GHOST = _REPO_ROOT / "tests" / "fixtures" / "ghost_recon_task_list.json"


# --------------------------------------------------------------------------
# ghost recon — the real secret missions
# --------------------------------------------------------------------------

def _ghost_frame():
    """The captured ``ghost.recon.get.task.list`` frame, or None if absent."""
    if not _GHOST.exists():
        return None
    return json.loads(_GHOST.read_text(encoding="utf-8"))


def test_ghost_decode_real_capture():
    """The real 6-task capture decodes with the states we saw by eye."""
    frame = _ghost_frame()
    if frame is None:
        return  # fixture absent — skip, keep the rest
    missions = list(proto.ghost_recon_missions(frame["command"], frame["payload"]))
    assert len(missions) == 6
    by_uuid = {m.uuid: m for m in missions}

    done = proto.filter_ghost_recon(missions, done=True)
    assert len(done) == 2                          # two completed on screen
    assert all(m.state == proto.GHOST_STATE_DONE for m in done)

    # The one with two looters was state 3 with steal_count 2.
    looted = [m for m in missions if m.steal_count == 2]
    assert len(looted) == 1 and looted[0].done

    # Empty slots: state 0, no coordinate, not joinable.
    empties = [m for m in missions if m.state == proto.GHOST_STATE_EMPTY]
    assert len(empties) == 3
    assert all(m.x is None and not m.joinable for m in empties)

    # Family comes off cfgId; 4/5/6 all present.
    assert {m.family for m in missions} == {"4", "5", "6"}


def test_ghost_filters():
    frame = _ghost_frame()
    if frame is None:
        return
    missions = list(proto.ghost_recon_missions(frame["command"], frame["payload"]))
    # joinable = alliance-visible AND dispatched (running or done)
    joinable = proto.filter_ghost_recon(missions, joinable=True)
    assert all(m.alliance_show and not m.empty for m in joinable)
    # family filter
    fam6 = proto.filter_ghost_recon(missions, family="6")
    assert all(m.family == "6" for m in fam6) and fam6
    # server filter narrows to one target
    one = proto.filter_ghost_recon(missions, server=991)
    assert all(m.target_server == 991 for m in one)


def test_ghost_alliance_command_routes_same():
    """Both ghost-recon commands share the taskList shape."""
    payload = {"taskList": [
        {"uuid": 1, "cfgId": 60306, "state": 3, "targetServer": 991,
         "allianceShow": 1, "pointId": 989166, "memberList": [{}], "stealList": []},
    ]}
    got = list(proto.ghost_recon_missions("ghost.recon.get.alliance.task.list",
                                          payload))
    assert len(got) == 1 and got[0].done and got[0].x == 166 and got[0].y == 989
    # a non-ghost command yields nothing
    assert list(proto.ghost_recon_missions("world.get.block", payload)) == []


def test_ghost_roundtrip_and_from_dict():
    m = proto.GhostReconMission(
        uuid=7, cfg_id=60306, family="6", level=3, state=3, target_server=991,
        owner_id="o", owner_server=935, alliance_id="a", alliance_show=True,
        point_id=989166, x=166, y=989, member_count=5, steal_count=2,
        team_start_time=1, completion_time=2, expire_time=3)
    assert proto.GhostReconMission.from_dict(m.as_dict()) == m


def test_monitor_announces_state_transitions():
    """The monitor announces once per (uuid, state); a state change re-announces."""
    frame = _ghost_frame()
    if frame is None:
        return
    env = {"p": {"p": frame["payload"], "c": frame["command"]}}
    mon = smc.MissionMonitor()
    mon.emit("down", env)
    mon.emit("down", env)                 # identical refresh — no new lines
    first = len(mon._announced)
    assert first > 0
    assert mon.frames == 2                # both frames decoded
    # Re-feeding the identical frame must not grow the announced set.
    assert len(mon._announced) == first
    # Empty slots (state 0) are not announced by default.
    empties = sum(1 for r in mon._missions.values()
                  if r.get("state") == proto.GHOST_STATE_EMPTY)
    assert empties == 3
    assert not any(k[1] == proto.GHOST_STATE_EMPTY for k in mon._announced)

    # A mission that flips to DONE announces again under the new state key.
    uuid = next(u for u, r in mon._missions.items()
                if r.get("state") == proto.GHOST_STATE_RUNNING)
    running_frame = {"p": {"p": {"taskList": [
        {"uuid": uuid, "cfgId": 40307, "state": proto.GHOST_STATE_DONE,
         "targetServer": 972, "allianceShow": 1, "pointId": 5064,
         "memberList": [{}], "stealList": []}]}, "c": frame["command"]}}
    before = len(mon._announced)
    mon.emit("down", running_frame)
    assert len(mon._announced) == before + 1
    assert (uuid, proto.GHOST_STATE_DONE) in mon._announced


def test_monitor_ignores_up_and_other_commands():
    frame = _ghost_frame()
    if frame is None:
        return
    env = {"p": {"p": frame["payload"], "c": frame["command"]}}
    up = smc.MissionMonitor()
    up.emit("up", env)                    # client request direction
    assert len(up._missions) == 0
    other = smc.MissionMonitor()
    other.emit("down", {"p": {"p": {"serverPointArr": []}, "c": "world.get.block"}})
    assert len(other._missions) == 0


# --------------------------------------------------------------------------
# alliance-shared tasks — the related share stream
# --------------------------------------------------------------------------

def test_share_decode_push_add():
    payload = {"missionCfgId": 60000701, "missionUuid": 1394584906709054020,
               "missionCurrentServerId": 946, "shareUid": "1522777203000972",
               "shareAllianceId": "3d4b9dee7b854f4a94810f7bb8b43089",
               "missionPlayerServerId": 946}
    missions = list(proto.share_missions("push.alliance.share.mission.add",
                                         payload))
    assert len(missions) == 1
    m = missions[0]
    assert m.uuid == 1394584906709054020
    assert m.family == "6000" and m.level == 7 and m.starred is True


def test_share_list_and_filters():
    assert list(proto.share_missions("get.alliance.share.mission.list",
                                     {"shareMissionArr": []})) == []
    arr = {"shareMissionArr": [
        {"missionCfgId": 60000701, "missionUuid": 1, "missionCurrentServerId": 946},
        {"missionCfgId": 50000504, "missionUuid": 2, "missionCurrentServerId": 946},
        {"missionCfgId": 60000801, "missionUuid": 3, "missionCurrentServerId": 999},
    ]}
    missions = list(proto.share_missions("get.alliance.share.mission.list", arr))
    assert {m.uuid for m in proto.filter_share_missions(missions, star_only=True)} == {1, 3}
    assert {m.uuid for m in proto.filter_share_missions(missions, level={7})} == {1}
    assert {m.uuid for m in proto.filter_share_missions(missions, server=999)} == {3}


def test_share_roundtrip():
    m = proto.ShareMission(uuid=5, cfg_id=60000701, family="6000", level=7,
                           server_id=946, owner_server_id=946,
                           share_uid="u", share_alliance_id="a")
    assert proto.ShareMission.from_dict(m.as_dict()) == m


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
