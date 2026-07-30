r"""Unit tests for the secret-mission decoders.

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
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lastwar_proto as proto  # noqa: E402

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


def _ghost_tile(uuid, *, completion, start, expire, state=3, cfg=40301,
                server=1057, packed=401994):
    """One `f2 = 29` tile shaped like the real world.get.block capture."""
    return {"_protobuf": {
        "f1": packed, "f2": 29, "f100": uuid, "f102": server, "f103": server,
        "f14": {"f1": "owner", "f2": cfg, "f3": completion, "f5": [{}],
                "f6": 1032, "f7": expire, "f8": "hex", "f9": state,
                "f10": 2147483647000, "f11": start}}}


def test_ghost_tile_field_mapping_not_swapped():
    """The tile's f3 is completionTime and f11 is teamStartTime, not the reverse.

    The poll proves completionTime > teamStartTime; on the tile f3 > f11, so a
    naive f3->start / f11->completion read is backwards. Guard the correct map.
    """
    payload = {"serverPointArr": [{"maxAreaSize": 1000, "points": [
        _ghost_tile(1, completion=2000, start=1000, expire=9000)]}]}
    m = list(proto.ghost_recon_tiles(payload))[0]
    assert m.completion_time == 2000   # f3, the later time (squad returns)
    assert m.team_start_time == 1000   # f11, the earlier time (dispatched)
    assert m.expire_time == 9000       # f7, the weekly window end


def test_ghost_tile_lootable_gated_on_clock_not_f9():
    """LOOTABLE follows the completion timer, not the always-3 tile state (f9).

    Both tiles carry f9 = 3 — the state that used to be trusted as "done" and
    wrongly flagged a still-running squad as lootable. Only the one whose
    completionTime is already in the past is can_loot.
    """
    now = int(time.time() * 1000)
    hour = 3600 * 1000
    payload = {"serverPointArr": [{"maxAreaSize": 1000, "points": [
        _ghost_tile(10, completion=now - hour, start=now - 2 * hour,
                    expire=now + hour),                       # squad back
        _ghost_tile(11, completion=now + hour, start=now - hour,
                    expire=now + 2 * hour),                   # still out
        _ghost_tile(12, completion=now - 2 * hour, start=now - 3 * hour,
                    expire=now - hour),                       # back but expired
    ]}]}
    missions = {m.uuid: m for m in proto.ghost_recon_tiles(payload)}
    assert all(m.state == 3 for m in missions.values())       # f9 says done for all
    assert missions[10].can_loot is True
    assert missions[11].can_loot is False                     # completion ahead
    assert missions[12].can_loot is False                     # expired off the map
    lootable = proto.filter_ghost_recon(list(missions.values()), can_loot=True)
    assert {m.uuid for m in lootable} == {10}


def _push(kind, **info):
    """A push.ghost.recon.alliance.single payload — add/change carry info,
    remove carries only uuid."""
    if kind == "remove":
        return {"type": "remove", "uuid": info["uuid"]}
    return {"type": kind, "info": info}


def test_ghost_alliance_push_decode():
    """add/change decode a mission from `info`; remove carries just the uuid."""
    add = _push("add", targetServer=992, pointId=16284, cfgId=50307,
                ownerId="1000000000000002", uuid=1397117489703528332,
                memberList=[{}], teamStartTime=1784801597335)
    kind, m = proto.ghost_recon_alliance_push(add)
    assert kind == "add"
    assert m.uuid == 1397117489703528332 and m.target_server == 992
    assert m.cfg_id == 50307 and m.family == "5"
    assert m.x == 284 and m.y == 16          # pointId 16284 -> y*1000+x
    assert m.member_count == 1 and m.owner_id == "1000000000000002"

    change = _push("change", targetServer=992, pointId=16284, cfgId=50307,
                   ownerId="1000000000000002", uuid=1397117489703528332,
                   memberList=[{}, {}, {}])
    kind, m = proto.ghost_recon_alliance_push(change)
    assert kind == "change" and m.member_count == 3

    kind, m = proto.ghost_recon_alliance_push(_push("remove", uuid=42))
    assert kind == "remove" and m.uuid == 42

    # Unknown / malformed shapes decode to None, not an exception.
    assert proto.ghost_recon_alliance_push({"type": "other"}) is None
    assert proto.ghost_recon_alliance_push({"type": "add"}) is None
    assert proto.ghost_recon_alliance_push("nonsense") is None


# --------------------------------------------------------------------------
# alliance-shared tasks — the related share stream
# --------------------------------------------------------------------------

def test_share_decode_push_add():
    payload = {"missionCfgId": 60000701, "missionUuid": 1394584906709054020,
               "missionCurrentServerId": 946, "shareUid": "1000000000000001",
               "shareAllianceId": "00000000000000000000000000000000",
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


def _checkpoint(tmp_path, tasks) -> str:
    """Write `tasks` as a capture checkpoint the auto-loot reader will accept."""
    now = time.time()
    records = []
    for t in tasks:
        rec = t.as_dict()
        rec["seen_at"] = int(now)
        records.append(rec)
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _task(uuid: int, cfg_id: int, family: str, level: int, looted=()) -> "proto.SecretTask":
    """A raidable tile: dispatch finished a minute ago, expires in an hour."""
    now_ms = int(time.time() * 1000)
    return proto.SecretTask(
        uuid=uuid, server_id=534, x=100 + uuid, y=200, level=level,
        cfg_id=cfg_id, family=family, looted_by=tuple(looted), owner_uid="u%d" % uuid,
        alliance_id="a", expires_at=now_ms + 3_600_000, completed_at=now_ms - 60_000)


def test_autoloot_takes_only_starred_tasks_of_the_best_level(tmp_path=None):
    """The panel's auto-loot rule: stars only, and only the highest level found.

    The day's five robberies are the scarce thing, not the targets — an attempt spent
    on a level-5 plain tile is one a level-7 star cannot have until the daily reset.
    So a plain task must never be picked up as a consolation, however raidable, and a
    starred level-6 must lose to a starred level-7 in the same scan.
    """
    import tempfile
    from pathlib import Path as _Path
    tmp_path = _Path(tmp_path or tempfile.mkdtemp())
    import steal_secret_task as steal

    tasks = [
        _task(1, 50000704, "5000", 7),    # unstarred family, top level — must be skipped
        _task(2, 60000601, "6000", 6),    # starred, but not the best level
        _task(3, 60000701, "6000", 7),    # starred, best level -> the target
        _task(4, 60000702, "6000", 7, looted=("x", "y", "z")),  # 3/3, not raidable
    ]
    picked = steal.targets_from_scan(_checkpoint(tmp_path, tasks), limit=5,
                                     star_max=True, say=lambda _m: None)
    assert [uuid for uuid, _srv, _label in picked] == [3], picked


def test_autoloot_robs_the_filter_top_level_and_nothing_lower(tmp_path=None):
    """«от 1 до 7» means level 7 — a level-6 star is not a consolation prize.

    Live case (2026-07-29 14:15): the range said 6..7, the day's last robberies
    were being saved for 7s, and the only raidable star was a 6 — which got
    robbed, because the rule took "the best level found" instead of the level the
    filter asked for. The scarce thing is the five daily attempts, not the
    targets: one spent on a 6 is one a 7 cannot have until the reset.
    """
    import tempfile
    from pathlib import Path as _Path
    tmp_path = _Path(tmp_path or tempfile.mkdtemp())
    import steal_secret_task as steal

    tasks = [
        _task(1, 60000501, "6000", 5),    # starred, below the filter's top
        _task(2, 60000601, "6000", 6),    # starred, below the filter's top
        _task(3, 60000801, "6000", 8),    # starred, above the range
    ]
    checkpoint = _checkpoint(tmp_path, tasks)

    said = []
    picked = steal.targets_from_scan(checkpoint, limit=5, star_max=True,
                                     level_min=1, level_max=7, say=said.append)
    assert picked == [], picked                    # neither the 6 nor the 5 stands in
    assert any("no starred task at level 7" in m for m in said), said

    # The 7 shows up -> that is the target, and the lower stars stay untouched.
    tasks.append(_task(4, 60000701, "6000", 7))
    picked = steal.targets_from_scan(_checkpoint(tmp_path, tasks), limit=5,
                                     star_max=True, level_min=1, level_max=7,
                                     say=lambda _m: None)
    assert [uuid for uuid, _srv, _label in picked] == [4], picked


def test_autoloot_level_range_is_a_hard_gate(tmp_path=None):
    """The range bounds what may be robbed at all, not just what is printed."""
    import tempfile
    from pathlib import Path as _Path
    tmp_path = _Path(tmp_path or tempfile.mkdtemp())
    import steal_secret_task as steal

    tasks = [
        _task(1, 60000501, "6000", 5),
        _task(2, 60000601, "6000", 6),
        _task(3, 60000801, "6000", 8),    # starred, above the range -> never a target
    ]
    checkpoint = _checkpoint(tmp_path, tasks)
    picked = steal.targets_from_scan(checkpoint, limit=5, star_max=True,
                                     level_min=5, level_max=6, say=lambda _m: None)
    assert [uuid for uuid, _srv, _label in picked] == [2], picked

    # No «до» set: no target level is configured, so the best found in range
    # stands in for it (and the level-8 star above the open end still wins).
    said = []
    fallback = steal.targets_from_scan(checkpoint, limit=5, star_max=True,
                                       level_min=6, say=said.append)
    assert [uuid for uuid, _srv, _label in fallback] == [3], fallback
    assert any("no «до» set" in m for m in said), said
    unbounded = steal.targets_from_scan(checkpoint, limit=5, star_max=True,
                                        say=lambda _m: None)
    assert [uuid for uuid, _srv, _label in unbounded] == [3], unbounded


def test_autoloot_does_nothing_without_a_star(tmp_path=None):
    """No star in the scan -> no target at all (the button is a no-op, not a fallback)."""
    import tempfile
    from pathlib import Path as _Path
    tmp_path = _Path(tmp_path or tempfile.mkdtemp())
    import steal_secret_task as steal

    said = []
    tasks = [_task(1, 400703, "40", 7), _task(2, 50000704, "5000", 7)]
    picked = steal.targets_from_scan(_checkpoint(tmp_path, tasks), limit=5,
                                     star_max=True, say=said.append)
    assert picked == []
    assert any("no starred task" in m for m in said), said


def _vt(uuid: int, cfg_id: int, srv: int = 534, steals: int = 0) -> str:
    """One `ACT VT …` line, as `secret_task_raidable_alliance()` emits for a raidable tile."""
    now = int(time.time() * 1000)
    return ("ACT VT uuid=%d cfg=%d srv=%d x=%d y=200 steals=%d done=%d exp=%d"
            % (uuid, cfg_id, srv, 100 + uuid, steals, now - 60_000, now + 3_600_000))


class _FakeEv:
    """A daemon/LuaEval stand-in: `run()` returns canned VT lines for any chunk."""

    def __init__(self, lines):
        self.lines = list(lines)

    def run(self, chunk, marker=None, settle=1.2):
        return list(self.lines)


def test_autoloot_from_vm_parses_and_applies_the_same_rule():
    """`targets_from_vm` parses the live-VM lines and picks by the same star-max rule.

    The VM source is the #1124 fast path: the same rule as the checkpoint, applied to
    the client's own alliance tasks. A parsed level-7 star wins; a plain family and a
    3/3 tile are not targets, and the level gate still bounds what may be robbed.
    """
    import steal_secret_task as steal

    ev = _FakeEv([
        _vt(1, 50000704),                    # unstarred family — skipped
        _vt(2, 60000601),                    # starred level 6 — below the top
        _vt(3, 60000701),                    # starred level 7 — the target
        _vt(4, 60000701, steals=3),          # 3/3, not raidable (dropped by can_loot)
    ])
    picked = steal.targets_from_vm(ev, limit=5, star_max=True, say=lambda _m: None)
    assert [uuid for uuid, _srv, _label in picked] == [3], picked

    # The level gate is hard here too: «от 1 до 6» leaves the 7 alone and takes the 6.
    picked = steal.targets_from_vm(ev, limit=5, star_max=True, level_min=1, level_max=6,
                                   say=lambda _m: None)
    assert [uuid for uuid, _srv, _label in picked] == [2], picked


def _mission(uuid, cfg_id, server=946):
    """A shared secret mission as the push carries it (level/family off the cfgId)."""
    family, level, _ = proto.split_cfg_id(cfg_id)
    return proto.ShareMission(uuid=uuid, cfg_id=cfg_id, family=family, level=level,
                              server_id=server, owner_server_id=server,
                              share_uid="u", share_alliance_id="a")


def test_share_autoloot_rule_matches_the_poll():
    """`mission_passes` is the poll's star-max rule reduced to one pushed mission."""
    import secret_share_autoloot as sa

    star7 = _mission(1, 60000701)      # starred level 7
    star6 = _mission(2, 60000601)      # starred level 6
    plain7 = _mission(3, 50000704)     # unstarred family, level 7

    # star-max, no cap: any starred mission is a target, a plain one is not.
    assert sa.mission_passes(star7, True, None, None)
    assert sa.mission_passes(star6, True, None, None)
    assert not sa.mission_passes(plain7, True, None, None)

    # «от 1 до 7»: the cap IS the level robbed — the 6 is held for a 7.
    assert sa.mission_passes(star7, True, 1, 7)
    assert not sa.mission_passes(star6, True, 1, 7)
    # «от 1 до 6»: now the 6 is the target and the 7 is above the range.
    assert sa.mission_passes(star6, True, 1, 6)
    assert not sa.mission_passes(star7, True, 1, 6)


class _StealEv:
    """A daemon stand-in for the share listener: records chunks, fakes the budget read."""

    def __init__(self, left=5):
        self.chunks = []
        self.left = left

    def run(self, chunk, marker=None, settle=1.2):
        self.chunks.append(chunk)
        if "ACT left=" in chunk:               # the _steals_left() probe
            return ["ACT left=%d" % self.left]
        return []


def test_share_autoloot_robs_once_on_a_matching_push():
    """A matching push fires exactly one robbery; a repeat and a non-match fire none."""
    import secret_share_autoloot as sa

    ev = _StealEv(left=5)
    mon = sa.ShareAutoloot(ev, star_max=True, level_min=1, level_max=7,
                           limit=5, dry_run=False)

    mon._consider(_mission(111, 60000701))     # starred level 7 -> robbed
    assert mon.robbed == 1, mon.robbed
    assert any("steal_sent uuid=111" in c and "946" in c for c in ev.chunks), ev.chunks

    # Same tile pushed again (or echoed): dedup, no second robbery.
    mon._consider(_mission(111, 60000701))
    assert mon.robbed == 1, mon.robbed

    # A starred level-6 under «до 7» is left alone; a plain tile too.
    mon._consider(_mission(222, 60000601))
    mon._consider(_mission(333, 50000704))
    assert mon.robbed == 1, mon.robbed


def test_share_autoloot_holds_when_budget_spent():
    """With no robberies left, a matching push is not sent and the tile can retry later."""
    import secret_share_autoloot as sa

    ev = _StealEv(left=0)
    mon = sa.ShareAutoloot(ev, star_max=True, level_min=None, level_max=None,
                           limit=5, dry_run=False)
    mon._consider(_mission(444, 60000701))
    assert mon.robbed == 0, mon.robbed
    # No DispatchSteal was sent — only the budget probe ran.
    assert not any("steal_sent" in c for c in ev.chunks), ev.chunks


def test_share_autoloot_dry_run_never_sends():
    """--dry-run decodes and decides but sends no robbery (budget-safe verification)."""
    import secret_share_autoloot as sa

    ev = _StealEv(left=5)
    mon = sa.ShareAutoloot(ev, star_max=True, level_min=None, level_max=None,
                           limit=5, dry_run=True)
    mon._consider(_mission(555, 60000701))
    assert mon.robbed == 0, mon.robbed
    assert ev.chunks == [], ev.chunks          # not even the budget probe runs


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
