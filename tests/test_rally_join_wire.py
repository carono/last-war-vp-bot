r"""Joining a banner the client has not heard of yet (task #1301), in a real Lua.

«Авторалли отвечает на 5–7 секунде.» Measured over 91 create-pushes on 2026-08-08, the
panel is not what is slow: the push reaches the trigger in 0.005 s and the send leaves
0.3 s later. What is slow is the client — `DataCenter.WorldMarchDataManager:GetAllMarches()`,
which is every reading the join sieve makes, learns about a banner a MEDIAN OF 10 s after
the push announcing it crossed the wire (p25 8.1 s, p75 19.1 s, max 62 s over 31 banners),
and in 23 of 26 late cases only once somebody ELSE had joined it. Until then every run
honestly answered `sent=0 rallies=0 seen=0` and sent nothing.

The push carries the whole of what a join needs from the first byte, so it is parked
alongside the targets and the seat counts and the sieve takes it as an extra candidate.
What this file pins is every way that can go quietly wrong:

  * **the address off the wire is the LEADER's tile**, which is where joiners gather —
    the monster is refused as «invalid end point» and cost this ability weeks
    (docs/research/rally-join.md). A member's own `startId` is that member's base, so the
    fallbacks read the leader's march and nobody else's;
  * **a banner the client already lists stays the client's.** The wire only ever ADDS,
    or one banner becomes two candidates and swallows two squads;
  * **a banner we already have a march in is not re-joined**, and neither is one this run
    has already been refused by;
  * **a banner the wire says is full is not sent to** — the seat filter must see a
    wire-only candidate exactly as it sees a client one;
  * **19-digit uuids survive the round trip.** A teamUuid is 19 digits; an integer VM
    holds it exactly and a float does not, and a send at a rounded uuid reaches nothing
    while returning cleanly — the failure mode this ability already lost weeks to
    (#1237). A candidate that does not survive `tostring(tonumber(t)) == t` is dropped
    rather than sent into the void;
  * **the report says which candidates the client could not have offered**, or
    `seen=0 rallies=2` reads as two numbers that cannot both be true.

    C:\Python312\python.exe tests\test_rally_join_wire.py
    python3 tests/test_rally_join_wire.py           # lupa is enough
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "tools", ROOT / "tools" / "lib", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lua_actions                                  # noqa: E402
import rally_monitor                                # noqa: E402

try:
    import lupa                                     # noqa: E402
except ImportError:                                 # pragma: no cover - optional
    lupa = None


#: Invented values of the right SHAPE. A teamUuid is 19 digits and is the leader's own
#: march uuid plus one; a tile index is `y * 1000 + x`; a server is small. A fixture that
#: only passes against a real account is testing the account (CLAUDE.md).
_TEAM = 1000000000000000002
_LEADER_MARCH = _TEAM - 1
_LEADER_TILE = 500500
_MONSTER_TILE = 505505
_SERVER = 100
_ALLIANCE = "AL1"

#: …and one that a float VM would round away: 25 digits comes back as `1e+24`.
_TOO_BIG = 1000000000000000000000002

#: As much of the client as the chunk touches. The send is RECORDED rather than sent —
#: what matters is which argument carried the tile, the team and the server.
_CLIENT = """
SAID = {}
SENT = {}
NOW = 1700000000000
CS = {UnityEngine = {Debug = {LogError = function(s) SAID[#SAID+1] = tostring(s) end}}}
DataCenter = {}
MarchUtil = {
  SendCreateMarchMessage = function(formation, kind, point, team, a, b, c, server, d)
    SENT[#SENT+1] = {formation = formation, kind = kind, point = point,
                     team = team, server = server}
  end,
}
UITimeManager = {GetInstance = function(self) return {GetServerTime = function(self)
  return NOW end} end}
LuaEntry = {Player = {uid = "1000000000000001", allianceId = 1}}

-- A .NET collection as the chunk walks it: `GetEnumerator()`, `MoveNext()`, `Current`.
function COLL(list)
  return {GetEnumerator = function(self)
    local i = 0
    return setmetatable({}, {__index = function(_, k)
      if k == "Current" then return list[i] end
      if k == "MoveNext" then return function() i = i + 1 return list[i] ~= nil end end
      return nil
    end})
  end}
end
"""


def _march(team, uuid, *, leader=False, ours=False, alliance=_ALLIANCE,
           end_time=0, tile=_LEADER_TILE, monster=_MONSTER_TILE):
    """One entry of the client's own march table."""
    owner = '"1000000000000001"' if ours else '"1000000000000009"'
    return ("{teamUuid = %d, uuid = %d, targetPos = %d, startPos = %d, homePos = %d, "
            "serverId = %d, allianceName = %s, ownerUid = %s, endTime = %d, "
            "targetUuid = %d}"
            % (team, uuid, monster if leader else tile, tile, tile, _SERVER,
               _lua_str(alliance), owner, end_time, 7))


def _lua_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _vm(*, client_marches=(), own_marches=None, squads=((1, 3000),),
        points="", slots="", targets=""):
    """A VM holding the stand-in client, with the run's arguments already parked.

    `own_marches` defaults to ONE march of ours with no team — that is what teaches the
    chunk which alliance is ours (`_RALLY_MINE`), and without it the sieve falls open and
    the test would be measuring the wrong thing.
    """
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    if own_marches is None:
        own_marches = (_march(0, 900000000000000001, ours=True),)
    rows = []
    for slot, soldiers in squads:
        rows.append("{index = %d, uuid = %d, totalSoldierNum = %d, state = 0, "
                    "IsFree = function() return true end, "
                    "ConscriptSoldier = function() end, "
                    "GetAllHeroSoldierCapacity = function() return %d end}"
                    % (slot, 2000000000000000000 + slot, soldiers, soldiers))
    lua.execute("""
DataCenter.ArmyFormationDataManager = {ArmyFormationList = {%s}}
DataCenter.SoldierDataManager = {GetPlayerSoldiersTotalNum = function() return 99999 end}
local ALL = COLL({%s})
local OWN = COLL({%s})
DataCenter.WorldMarchDataManager = {
  GetAllMarches = function(self) return ALL end,
  GetOwnerMarches = function(self) return OWN end,
  GetOwnerFormationMarch = function(self, uid, uuid, ally) return nil end,
}
DataCenter.__lw_rally_squads = {%s}
DataCenter.__lw_rally_points = %s
DataCenter.__lw_rally_slots = %s
DataCenter.__lw_rally_targets = %s
DataCenter.__lw_rally_shut = {}
""" % (", ".join(rows),
       ", ".join(client_marches),
       ", ".join(own_marches),
       ", ".join(str(slot) for slot, _n in squads),
       _lua_str(points), _lua_str(slots), _lua_str(targets)))
    return lua


def _run(lua):
    """Play the join chunk and hand back `(sends, report)`."""
    lua.execute(lua_actions.rally_join_all())
    sends = []
    sent = lua.eval("SENT")
    for i in range(1, len(sent) + 1):
        row = sent[i]
        sends.append({k: row[k] for k in ("formation", "kind", "point", "team", "server")})
    return sends, str(lua.eval("DataCenter.__lw_rally_report") or "")


# -- what the push carries ------------------------------------------------------

#: The create push, with every identifier invented. Shape and field names are the live
#: ones (docs/research/protocol.md); the numbers are not anybody's.
_PUSH = {
    "uuid": _TEAM, "server": _SERVER, "nowServer": _SERVER, "srcServer": _SERVER,
    "attackPointId": _LEADER_TILE, "targetPointId": _MONSTER_TILE,
    "targetContentId": 38, "assemblyMarchMax": 5,
    "leaderMarch": {"uuid": _LEADER_MARCH, "startId": _LEADER_TILE,
                    "path": "%d;%d" % (_LEADER_TILE, _MONSTER_TILE),
                    "targetPos": _MONSTER_TILE, "teamUuid": 0},
    "members": [],
}


def test_join_point_is_the_leaders_tile() -> None:
    assert rally_monitor._join_point(_PUSH) == (_LEADER_TILE, _SERVER)


def test_join_point_falls_back_to_the_leaders_own_march() -> None:
    """`attackPointId` missing → the leader's `startId`, then the first leg of its path."""
    no_field = dict(_PUSH); no_field.pop("attackPointId")
    assert rally_monitor._join_point(no_field) == (_LEADER_TILE, _SERVER)

    no_start = dict(_PUSH); no_start.pop("attackPointId")
    leader = dict(_PUSH["leaderMarch"]); leader.pop("startId")
    no_start["leaderMarch"] = leader
    assert rally_monitor._join_point(no_start) == (_LEADER_TILE, _SERVER)


def test_join_point_never_reads_a_member() -> None:
    """A member's `startId` is that member's OWN base — following it sends the squad to
    an alliancemate's doorstep. With no leader march there is no address at all."""
    orphan = {k: v for k, v in _PUSH.items()
              if k not in ("attackPointId", "leaderMarch")}
    orphan["members"] = [{"startId": 111222, "armyInfo": "", "ownerUid": "1"}]
    assert rally_monitor._join_point(orphan) is None


def test_half_an_address_is_no_address() -> None:
    no_server = {k: v for k, v in _PUSH.items()
                 if k not in ("server", "nowServer", "srcServer")}
    assert rally_monitor._join_point(no_server) is None
    assert rally_monitor._join_point(None) is None


def test_a_brand_new_banner_still_has_a_team_to_be_keyed_by() -> None:
    """The `create` push is the head start, and it used to be the one line thrown away.

    Its leader stands alone, so the game sends his march with `teamUuid = 0` and the tag
    read `solo` — which the panel drops on the floor, because `_on_line` keys everything
    it keeps (address, seats, target) by `team=`. So the address arrived on the earliest
    push and was binned, and the wire's whole advantage was spent waiting for a
    `refresh`, which only comes once somebody ELSE has joined.
    """
    assert str(_PUSH["leaderMarch"]["teamUuid"]) == "0"
    assert rally_monitor._banner_uuid(_PUSH) == str(_TEAM)


def test_the_marches_win_when_they_have_a_team() -> None:
    """A refresh puts the banner on every march; that is the value the rest keys by."""
    joined = dict(_PUSH)
    joined["members"] = [{"teamUuid": _TEAM, "armyInfo": "", "ownerUid": "1000000000000009"}]
    assert rally_monitor._banner_uuid(joined) == str(_TEAM)

    disagree = dict(joined)
    disagree["uuid"] = _TEAM + 7
    assert rally_monitor._banner_uuid(disagree) == str(_TEAM)


def test_no_uuid_anywhere_is_still_solo() -> None:
    bare = {k: v for k, v in _PUSH.items() if k != "uuid"}
    assert rally_monitor._banner_uuid(bare) is None
    assert rally_monitor._banner_uuid(None) is None


# -- what the join does with it -------------------------------------------------

def test_a_banner_only_the_wire_knows_is_joined() -> None:
    """The client's march table is empty and the squad still goes — at the leader's tile."""
    if lupa is None:
        print("  SKIP no lupa"); return
    lua = _vm(points="%d:%d/%d" % (_TEAM, _LEADER_TILE, _SERVER))
    sends, report = _run(lua)
    assert len(sends) == 1, report
    assert sends[0]["team"] == _TEAM, sends
    assert sends[0]["point"] == _LEADER_TILE, sends
    assert sends[0]["server"] == _SERVER, sends
    assert sends[0]["kind"] == 6, sends           # rally, and it is the SECOND argument
    assert "from_wire=[%d]" % _TEAM in report, report


def test_the_client_keeps_the_banners_it_knows() -> None:
    """A team the client already lists is NOT added a second time — one banner, one send."""
    if lupa is None:
        print("  SKIP no lupa"); return
    lua = _vm(client_marches=(_march(_TEAM, _LEADER_MARCH, leader=True),),
              points="%d:%d/%d" % (_TEAM, _LEADER_TILE, _SERVER),
              squads=((1, 3000), (2, 3000)))
    sends, report = _run(lua)
    assert len(sends) == 1, report
    assert "from_wire" not in report, report


def test_a_banner_we_are_already_in_is_left_alone() -> None:
    if lupa is None:
        print("  SKIP no lupa"); return
    lua = _vm(own_marches=(_march(_TEAM, 900000000000000002, ours=True),),
              points="%d:%d/%d" % (_TEAM, _LEADER_TILE, _SERVER))
    sends, report = _run(lua)
    assert sends == [], report


def test_a_banner_the_wire_says_is_full_is_not_sent_to() -> None:
    """The seat filter sees a wire-only candidate exactly as it sees a client one."""
    if lupa is None:
        print("  SKIP no lupa"); return
    lua = _vm(points="%d:%d/%d" % (_TEAM, _LEADER_TILE, _SERVER),
              slots="%d:5/5" % _TEAM)
    sends, report = _run(lua)
    assert sends == [], report
    assert "banner-full" in report, report


def test_a_banner_this_run_was_refused_by_is_not_offered_again() -> None:
    if lupa is None:
        print("  SKIP no lupa"); return
    lua = _vm(points="%d:%d/%d" % (_TEAM, _LEADER_TILE, _SERVER))
    lua.execute("DataCenter.__lw_rally_shut = {['%d'] = true}" % _TEAM)
    sends, report = _run(lua)
    assert sends == [], report


def test_a_uuid_that_does_not_survive_the_round_trip_is_dropped() -> None:
    """A float VM rounds a long uuid; a send at a rounded one reaches nothing and says
    nothing. Dropped rather than sent."""
    if lupa is None:
        print("  SKIP no lupa"); return
    lua = _vm(points="%d:%d/%d" % (_TOO_BIG, _LEADER_TILE, _SERVER))
    sends, report = _run(lua)
    assert sends == [], report
    assert "from_wire" not in report, report


def test_the_wire_candidate_goes_first() -> None:
    """One squad, two banners: the one the client has not caught up with is the fresher,
    and it is the one the squad is spent on."""
    if lupa is None:
        print("  SKIP no lupa"); return
    old_team = _TEAM + 100
    lua = _vm(client_marches=(_march(old_team, old_team - 1, leader=True),),
              points="%d:%d/%d" % (_TEAM, _LEADER_TILE, _SERVER))
    sends, report = _run(lua)
    assert len(sends) == 1, report
    assert sends[0]["team"] == _TEAM, sends


def test_nothing_parked_means_nothing_changes() -> None:
    """No `points` at all — the run behaves exactly as it did before (#1301)."""
    if lupa is None:
        print("  SKIP no lupa"); return
    lua = _vm(client_marches=(_march(_TEAM, _LEADER_MARCH, leader=True),))
    sends, report = _run(lua)
    assert len(sends) == 1, report
    assert "from_wire" not in report, report


def test_the_recipe_declares_and_parks_the_argument() -> None:
    """A recipe that reads `points` but never parks it is a silent no-op."""
    recipe = (ROOT / "src" / "lastwar_bot" / "actions" / "join_rally.md").read_text(
        encoding="utf-8")
    assert "ARGS points" in recipe
    assert 'DataCenter.__lw_rally_points = "{points}"' in recipe


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
