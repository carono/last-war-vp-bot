r"""The auto-treasure errand, run in a real Lua (task #1296).

«Мне нужен триггер, реагирующий на уведомления о сокровищах с автоматической
отправкой ближайшего отряда и сбор подарка.» The chest is announced in alliance chat,
the client's own hook turns that announcement into a target, and one press marches a
squad onto it and claims the gift once the alliance has dug it.

What this file pins is everything checkable without a game, and every place the design
can go quietly wrong:

  * **an announcement becomes a target, once.** The share arrives as a chat post whose
    `attachmentId` is a JSON blob; the harvest reads it out of whichever field carries it
    and turns the `x`/`y` into the tile the march is aimed at. The SAME chest announced
    twice — which happens, because a share is repeated and echoed — must not become two
    targets, or two squads go to one tile;
  * **19-digit ids survive.** The game's Lua is 5.3 with integer arithmetic, so a uuid
    parsed out of the blob must come back digit for digit. A float would send a march at
    a chest that does not exist;
  * **the march goes out with the target type in the SECOND argument** and the tile in
    the third — the shape the 2026-08-07 trace confirmed, and the one a filter reading
    the first argument gets wrong every time;
  * **a chest on another server is a CROSS march** (182, not 50);
  * **`push.detect.treasure.claim` is «this chest is dug», never «somebody took it».**
    Every digger claims their own gift, so the broadcast is the gate that opens the
    claim — reading it as a loss would give the reward away;
  * **the claim waits, and its fallback waits for TWO things.** No claim before the dig is
    heard, or before the grace has run out **and** the squad's march is over — a chest far
    from the base outlasts any grace worth having, and a claim sent into a march in flight
    is refused;
  * **a refused claim is SILENT** — no message tip, no window, no thrown error, and a reply
    under the same command name with nothing readable in it (measured live on 2026-08-08).
    So the send is not the proof: a chest is spent when the reward window comes up shortly
    after, and a chest whose tries all ran out is written off as `claim-unconfirmed` rather
    than as taken. This is the one that was got wrong first and cost the reward in exactly
    the case the grace existed for;
  * **the queue is spent, not grown.** A finished chest is pruned, an expired one is
    written off, and a run finds no free squad without throwing;
  * **the poll is true when nothing is listening.** A client restart wipes the VM and the
    hook with it, and an errand that only asked about targets would then be deaf for ever;
  * **stopping the debug ring does not unhook the ear** the auto errand listens with.

    C:\Python312\python.exe tests\test_treasure_auto.py
    python3 tests/test_treasure_auto.py            # lupa is enough
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "tools", ROOT / "tools" / "lib", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lua_actions  # noqa: E402

try:
    import lupa                                     # noqa: E402
except ImportError:                                 # pragma: no cover - optional
    lupa = None


#: Invented ids of the right SHAPE — a uuid is 19 digits, a server is small, a tile index
#: is `y * 1000 + x + 1`. A fixture that only passes against a real account is testing the
#: account (CLAUDE.md).
_UUID = 1000000000000000001
_OTHER_UUID = 1000000000000000002
_SERVER = 100
_FAR_SERVER = 200
_HOME_TILE = 500500          # the base: (499, 500)
_NEAR = (505, 502)
_FAR = (560, 470)

#: As much of the client as the errand touches. The march and the claim are RECORDED
#: rather than sent, because what this file is checking is the shape of the call: which
#: argument carries the target type, which the tile, which the uuid.
_CLIENT = """
SAID = {}
MARCHED = {}
CLAIMED = {}
CS = {UnityEngine = {Debug = {LogError = function(s) SAID[#SAID+1] = tostring(s) end},
                     Vector2Int = function(x, y) return {x = x, y = y} end}}
NOW = 1785322473766
DataCenter = {}
SFSNetwork = {
  SendMessage = function(cmd, a, b, ...)
    if cmd == "detect.event.claim.treasure" then
      CLAIMED[#CLAIMED+1] = {uuid = a, server = b}
    end
    return "sent" end,
  HandleMessage = function(cmd, obj, ...) return "handled" end,
}
SFSObject = {
  GetKeys = function(o) return o.__keys end,
  GetData = function(o, k) return o[k] end,
}
MsgDefines = {DetectEventClaimTreasure = "detect.event.claim.treasure"}
REWARD_UP = false
UIWindowNames = {UIGiftPackageRewardGet = "UIGiftPackageRewardGet"}
UIManager = {Instance = {IsWindowOpen = function(self, name) return REWARD_UP end}}
MarchUtil = {
  SendCreateMarchMessage = function(formation, target, pid, uuid, a, b, c, server, d)
    MARCHED[#MARCHED+1] = {formation = formation, target = target, pid = pid,
                           uuid = uuid, server = server}
  end,
}
SceneUtils = {
  TilePosToIndex = function(v) return v.y * 1000 + v.x + 1 end,
  IndexToTilePos = function(i) return {x = (i - 1) %% 1000, y = math.floor((i - 1) / 1000)} end,
}
UITimeManager = {Instance = {GetServerTime = function(self) return NOW end}}
ChatInterface = {getServerTime = function() return math.floor(NOW / 1000) end}
LuaEntry = {Player = {uid = "1000000000000001", allianceId = 1, serverId = %d,
                      world_main_pos = %d}}
""" % (_SERVER, _HOME_TILE)


def _squads(lua, spec) -> None:
    """Give the client a squad list: `(slot, soldiers, marching)` per entry."""
    rows = []
    for slot, soldiers, marching in spec:
        rows.append("{index = %d, uuid = %d, totalSoldierNum = %d, __out = %s}"
                    % (slot, 2000000000000000000 + slot, soldiers,
                       "true" if marching else "false"))
    lua.execute("""
DataCenter.ArmyFormationDataManager = {ArmyFormationList = {%s}}
DataCenter.WorldMarchDataManager = {
  GetOwnerFormationMarch = function(self, uid, uuid, ally)
    for _, f in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do
      if f.uuid == uuid and f.__out then return {teamUuid = 0} end
    end
    return nil end,
}
""" % ", ".join(rows))


def _vm(squads=((1, 3000, False), (2, 3000, False), (3, 3000, False)),
        allowed=(1, 2, 3, 4), grace: int = 240):
    """A Lua VM with the client stand-in, the hook installed and the errand armed."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    _squads(lua, squads)
    lua.execute(lua_actions.treasure_watch_install())
    lua.execute("DataCenter.__lw_treasure_squads = {%s} "
                "DataCenter.__lw_treasure_grace = %d"
                % (", ".join(str(s) for s in allowed), grace))
    lua.execute(lua_actions.treasure_auto_arm_parked())
    return lua


def _announce(lua, uuid=_UUID, xy=_NEAR, server=_SERVER, key="attachmentId",
              plain: bool = False, cfg: int = 25195) -> None:
    """The chat post that announces a chest, with the blob under `key`.

    Field order and spacing are the client's own (`shareType` first, `x`/`y` in the
    middle) so the parser is exercised against the shape rather than against a tidy one.
    """
    blob = ('{"shareType":27,"y":%d,"x":%d,"uuid":%d,"worldType":0,"worldId":0,'
            '"sid":%d,"treasureId":"%d","oname":"1000000000000001"}'
            % (xy[1], xy[0], uuid, server, cfg))
    body = ('{msg="?", %s=%s}' % (key, _lua_str(blob)) if plain
            else '{__keys={"msg","%s"}, msg="?", %s=%s}' % (key, key, _lua_str(blob)))
    lua.execute('SFSNetwork.HandleMessage("world.treasure.share.chat", %s)' % body)


def _lua_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _dug(lua, uuid=_UUID, plain: bool = True, cfg: int = 25195) -> None:
    """The alliance's own feed: one of these per member who has finished digging.

    `plain` is the shape an INCOMING message really has — a bare Lua table, with no
    `__keys` for `SFSObject.GetKeys` to find. Proven live on 2026-08-08 by probing a real
    `push.detect.treasure.claim`: `KEYS[] PAIRS[operator=table uuid=…]`. The default is
    the real one; `plain=False` is the SFSObject shape an outgoing message has.
    """
    body = ('{uuid=%d, operator={}, treasureId=%d}' % (uuid, cfg) if plain
            else '{__keys={"uuid","operator"}, uuid=%d, operator={}, treasureId=%d}'
                 % (uuid, cfg))
    lua.execute('SFSNetwork.HandleMessage("push.detect.treasure.claim", %s)' % body)


def _reward(lua, up: bool = True) -> None:
    """The `UIGiftPackageRewardGet` the client raises on a claim the server PAID — the one
    observable difference between a paid claim and a refused one."""
    lua.execute("REWARD_UP = %s" % ("true" if up else "false"))


def _came_home(lua, slot: int = 1) -> None:
    """The squad's march is over: it has dug and come back, so the chest can be claimed."""
    lua.execute("for _, f in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) "
                "do if f.index == %d then f.__out = false end end" % slot)


def _dug_and_home(lua, slot: int = 1) -> None:
    """The squad goes out, IS SEEN out, and comes home — our own part of the dig, done.

    THE SHAPE EVERY CLAIM NOW NEEDS (#1318). A march that was never seen at all is not a
    march that is over: it is a send the client dropped in silence, and the errand re-sends
    rather than claiming into an empty road. So a test that wants a chest claimed has to
    let the march exist first, which is also what the game does — a dig march is out for
    seconds at the very least, and the watch looks five times a second.
    """
    _still_marching(lua, slot=slot)
    _step(lua)                       # …seen out
    _came_home(lua, slot=slot)


def _march_answered(lua) -> None:
    """Let the server's answer to the march arrive — or its absence become believable.

    A squad whose march the server has not confirmed yet still reads FREE (#1296, measured
    live: the send at 21:01:50 and `free=3 busy=0` five seconds later, on a march that was
    on its way). So the errand does not believe «no march» until either one has been seen
    or the settle has passed — and since #1318 a march that was NEVER seen is read as a
    send the client dropped, not as a squad that has been and come back. Advancing the
    clock like this is therefore how a test asks for the RE-SEND, not for a claim.
    """
    lua.execute("NOW = NOW + %d" % ((lua_actions.TREASURE_MARCH_SETTLE_SEC + 1) * 1000))


def _still_marching(lua, slot: int = 1) -> None:
    """The squad this target was sent with is still in the air."""
    lua.execute("for _, f in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) "
                "do if f.index == %d then f.__out = true end end" % slot)


def _step(lua) -> str:
    lua.execute(lua_actions.treasure_auto_step())
    return str(lua.eval(lua_actions.treasure_auto_report()))


def _marched(lua) -> list:
    return [dict(m.items()) for m in lua.eval("MARCHED").values()]


def _claims(lua) -> list:
    return [dict(c.items()) for c in lua.eval("CLAIMED").values()]


def _queued(lua) -> int:
    """Chests still to be WORKED — not the length of the list.

    A finished chest is kept in `targets` until its ttl runs out so the next lap of the
    map recognises it instead of starting it over (#1296), so «how long is the list» and
    «how much is left to do» stopped being the same number.
    """
    return int(lua.eval("(function() local n = 0 "
                        "for _, t in ipairs(DataCenter.__lw_treasure_auto.targets or {}) "
                        "do if not t.done then n = n + 1 end end return n end)()"))


def _spent(lua) -> int:
    """Chests already finished and held only so they are not queued a second time."""
    return int(lua.eval("(function() local n = 0 "
                        "for _, t in ipairs(DataCenter.__lw_treasure_auto.targets or {}) "
                        "do if t.done then n = n + 1 end end return n end)()"))


def _needs_lua(what: str) -> bool:
    if lupa is None:                                # pragma: no cover - optional
        print(f"  skip {what}: lupa is not installed")
        return False
    return True


def test_an_announcement_becomes_one_target_with_the_right_tile():
    """The blob is parsed out of whatever field carries it, and the tile is computed the
    way every other tile read computes it. The uuid is 19 digits and must survive as an
    integer: a float here aims the march at a chest that does not exist."""
    if not _needs_lua("an announcement becomes a target"):
        return
    lua = _vm()
    _announce(lua)
    assert _queued(lua) == 1
    t = lua.eval("DataCenter.__lw_treasure_auto.targets[1]")
    assert str(lua.eval("string.format('%d', DataCenter.__lw_treasure_auto"
                        ".targets[1].uuid)")) == str(_UUID)
    assert (int(t["x"]), int(t["y"])) == _NEAR
    assert int(t["pid"]) == _NEAR[1] * 1000 + _NEAR[0] + 1
    assert int(t["server"]) == _SERVER


def test_the_same_chest_announced_again_is_not_a_second_target():
    """A share is repeated and echoed, and two targets for one chest means two squads on
    one tile — one of them spent for nothing."""
    if not _needs_lua("a repeat is not a second target"):
        return
    lua = _vm()
    _announce(lua)
    _announce(lua)
    _announce(lua, key="someOtherField")
    assert _queued(lua) == 1
    assert int(lua.eval("DataCenter.__lw_treasure_auto.news")) == 1


def test_a_message_without_a_share_blob_is_ignored():
    """The hook sees every treasure message there is. Only the one carrying a shareType
    with a uuid is an announcement; a reward info reply is not, and must not become a
    target aimed at tile 1."""
    if not _needs_lua("no blob, no target"):
        return
    lua = _vm()
    lua.execute('SFSNetwork.HandleMessage("detect.event.get.treasure.claim.info", '
                '{__keys={"reward"}, reward="x"})')
    lua.execute('SFSNetwork.HandleMessage("world.treasure.share.chat", '
                '{__keys={"msg"}, msg="just words"})')
    assert _queued(lua) == 0


def test_the_nearest_chest_is_worked_first_and_gets_the_lowest_free_squad():
    """«Nearest» can only be earned on the CHEST — a free squad has no position of its
    own and is standing in the base, so every one of them is the same distance away. The
    ordering is by the chest's distance from the base, and the report says so."""
    if not _needs_lua("the nearest chest first"):
        return
    lua = _vm()
    _announce(lua, uuid=_OTHER_UUID, xy=_FAR)
    _announce(lua, uuid=_UUID, xy=_NEAR)
    _step(lua)
    marched = _marched(lua)
    assert len(marched) == 2, marched
    #: the near chest first, and with squad 1
    assert str(marched[0]["uuid"]) == str(_UUID), marched
    assert marched[0]["formation"] == 2000000000000000001, marched
    assert str(marched[1]["uuid"]) == str(_OTHER_UUID), marched
    assert marched[1]["formation"] == 2000000000000000002, marched


def test_the_march_carries_the_target_type_second_and_the_tile_third():
    """The shape the 2026-08-07 trace confirmed. A reader — or a writer — that puts the
    type first sends a 19-digit number where the type belongs and the march goes nowhere."""
    if not _needs_lua("the march's argument order"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    m = _marched(lua)[0]
    assert m["target"] == lua_actions.MARCH_DETECT_TREASURE, m
    assert int(m["pid"]) == _NEAR[1] * 1000 + _NEAR[0] + 1, m
    assert int(m["server"]) == _SERVER, m


def test_a_chest_on_another_server_is_a_cross_march():
    """182, not 50. Same call, one argument different, and the wrong one is a march the
    server drops."""
    if not _needs_lua("a cross-server chest"):
        return
    lua = _vm()
    _announce(lua, server=_FAR_SERVER)
    _step(lua)
    m = _marched(lua)[0]
    assert m["target"] == lua_actions.MARCH_CROSS_DETECT_TREASURE, m
    assert int(m["server"]) == _FAR_SERVER, m


def test_no_claim_before_the_dig_is_heard():
    """A claim on a chest still being dug pays nothing. The squad goes out and the run
    says «digging» until the alliance's feed arrives or the grace runs out."""
    if not _needs_lua("no claim before the dig"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _still_marching(lua, slot=1)
    report = _step(lua)
    assert _claims(lua) == []
    assert "waiting=1" in report and ":marching" in report, report


def test_the_alliance_feed_opens_the_claim_rather_than_closing_it():
    """`push.detect.treasure.claim` is one per member who FINISHED — every digger claims
    their own gift. Read as «somebody took it» the reward would be given away; read as
    «this chest is dug and payable», it is the gate."""
    if not _needs_lua("the feed is a gate, not a loss"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _dug_and_home(lua)
    #: …and the claim leaves in the frame the feed arrives (#1886): the hook runs the
    #: watch itself, so the gift is not waiting for the next tick or the next press.
    _dug(lua)
    claims = _claims(lua)
    assert len(claims) == 1, claims
    assert str(claims[0]["uuid"]) == str(_UUID), claims
    assert int(claims[0]["server"]) == _SERVER, claims
    report = _step(lua)
    assert "claim1" in report, report


def test_the_grace_waits_for_the_march_to_be_over_as_well_as_for_the_clock():
    """THE HOLE THE GRACE HAD. A chest far from the base outlasts any grace worth having,
    and a claim sent while the squad is still walking is refused in SILENCE — no tip, no
    window, no error — so the chest used to be written off in exactly the case the grace
    was added for. The fallback now needs both: the clock, and the march being over."""
    if not _needs_lua("the grace waits for the march"):
        return
    lua = _vm(grace=60)
    _announce(lua)
    _step(lua)
    _still_marching(lua, slot=1)
    lua.execute("NOW = NOW + 61000")
    report = _step(lua)
    assert _claims(lua) == [], "a claim went out while the squad was still in the air"
    assert ":marching" in report, report
    assert _queued(lua) == 1, "the chest must survive to be claimed when the squad lands"
    #: …and once it lands, the same clock claims it
    _came_home(lua, slot=1)
    _step(lua)
    assert len(_claims(lua)) == 1, _claims(lua)


def test_the_dig_feed_does_not_claim_over_a_march_still_in_flight():
    """THE OTHER HALF OF THAT HOLE, and the one that cost the first chest this account
    ever had of its own (#1296).

    The grace learned to wait for the march; the DIG FEED did not. `t.dug` skipped the
    march test entirely, on the reading that a dug chest is a claimable one. It is not — a
    chest the ALLIANCE has dug is not a chest THIS account has dug, and the server refuses
    the claim until our own squad has done its part. Live, on a chest twelve tiles from
    home: march at 20:55:41, first claim at 20:55:43 with the squad barely out of the
    base, and all four tries spent inside 124 s — every one refused in the silence a
    refusal comes in — before the chest was written off as `claim-unconfirmed`.

    So the feed is a gate on the chest, never a bypass of our own legs.
    """
    if not _needs_lua("the dig feed does not overrule a march"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)                                   # the squad goes out
    _still_marching(lua, slot=1)
    _dug(lua)                                    # the alliance finishes while it walks
    report = _step(lua)
    assert _claims(lua) == [], "the dig feed claimed over a march still in the air"
    assert "dug-still-marching" in report, report
    assert int(lua.eval("DataCenter.__lw_treasure_auto.targets[1].tries or 0")) == 0, \
        "a try was burned on a claim that could not be paid"
    assert _queued(lua) == 1, report
    #: …and the moment the squad is home, the feed's chest is claimed at once — no grace
    #: to sit out, which is what the feed is FOR.
    _came_home(lua, slot=1)
    _step(lua)
    assert len(_claims(lua)) == 1, _claims(lua)


def test_a_march_the_server_has_not_answered_yet_is_not_a_march_that_is_over():
    """AND THE SAME GATE HAS TO SURVIVE THE CLIENT'S OWN LAG (#1296).

    Gating the claim on «is our squad marching?» is only worth anything if the answer is
    trustworthy, and for the first seconds after a send it is not: a squad whose march the
    server has not confirmed yet still reads FREE. Measured live — the send at 21:01:50,
    and the report five seconds later saying `free=3 busy=0` on a march that was on its
    way. The first version of the fix read that as «the march is over», claimed, and was
    refused exactly as before.

    So the absence of a march is believed only once one has been SEEN, or once the settle
    has passed — and until then the note says `march-unanswered` rather than pretending to
    know.
    """
    if not _needs_lua("an unanswered march is not a finished one"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)                                   # the send goes out…
    _dug(lua)                                    # …and the alliance finishes at once
    #: the client has not answered the march yet — the squad still reads free
    report = _step(lua)
    assert _claims(lua) == [], "claimed into a march the server had not answered yet"
    assert "march-unanswered" in report, report
    #: the answer arrives: the squad is out, so the claim keeps waiting for it
    _still_marching(lua, slot=1)
    report = _step(lua)
    assert _claims(lua) == [], report
    assert "dug-still-marching" in report, report
    #: …and once it is home, the claim goes
    _came_home(lua, slot=1)
    _step(lua)
    assert len(_claims(lua)) == 1, _claims(lua)


def test_a_march_that_is_never_seen_at_all_is_re_sent_and_not_claimed_over():
    """«Отправка отряда — тоже работает через раз» (#1318), and this is what that was.

    The client drops a march for a formation it thinks is already committed, WITHOUT a
    word: no error, no reply, nothing on screen. The old reading gave that silence twenty
    seconds and then treated it as a squad that had been and come back — so the claim went
    out into a road nobody had walked, was refused in the silence a refusal comes in, and
    the chest was written off with the send never having happened at all.

    A march that has never been seen is therefore a send to make again. Three sightings of
    an empty road are needed before the silence is believed, because a client the watch is
    not running on is only looked at when the panel presses.
    """
    if not _needs_lua("a march that never left"):
        return
    lua = _vm()
    _announce(lua)
    report = _step(lua)
    assert len(_marched(lua)) == 1, report
    #: one empty look is not enough to condemn a send — a client the watch is not running
    #: on is only looked at when the panel presses, and a near chest could have been
    #: marched, dug and walked home between two of those.
    report = _step(lua)
    assert "resent" not in report, report
    #: …but an empty road that has been looked at three times, and for longer than the
    #: server has ever taken to answer, is a send that never happened.
    _march_answered(lua)
    for _ in range(3):
        report = _step(lua)
        if "resent=1" in report:
            break
    assert "resent=1" in report, report
    assert _claims(lua) == [], "claimed over a march that never existed"
    _step(lua)
    assert len(_marched(lua)) == 2, _marched(lua)


def test_a_spent_chest_is_not_queued_again_by_the_next_lap():
    """A FINISHED CHEST IS REMEMBERED, NOT FORGOTTEN — the second half of the same live
    failure (#1296).

    The prune dropped every `done` target, and the harvest looks for duplicates among the
    targets it can see. So the lap five minutes later found the chest it had just written
    off, queued it as `new`, sent a SECOND squad at it and burned four more claims — round
    and round for as long as the chest lay on the map. A spent chest now stays in the list
    until its ttl runs out: the step skips it, the harvest knows it, and the report counts
    it apart so `queued=` still means work left.
    """
    if not _needs_lua("a spent chest is not re-queued"):
        return
    lua = _scan_vm()
    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    _walk(lua)
    assert _queued(lua) == 1

    #: worked to the end and paid for — the squad goes out, is seen out, and comes home
    _step(lua)
    assert len(_marched(lua)) == 1, _marched(lua)
    _still_marching(lua, slot=1)
    _step(lua)
    _came_home(lua, slot=1)
    _dug(lua, uuid=_OTHER_UUID)
    _step(lua)
    _reward(lua)
    report = _step(lua)
    assert "paid=1" in report, report
    assert _queued(lua) == 0 and _spent(lua) == 1, report

    #: the chest is still lying on the map, so the next lap finds it again — and must
    #: recognise it rather than start it over.
    _reward(lua, up=False)
    _walk(lua)
    assert _queued(lua) == 0, _targets(lua)
    scan = str(lua.eval(lua_actions.treasure_scan_report()))
    #: `done-with=` since #1898 — the ledger recognises a finished chest whether or not it
    #: is still in the list, so the answer no longer depends on the prune having run.
    assert "new=0" in scan, scan
    assert "already-queued=1" in scan or "done-with=1" in scan, scan
    report = _step(lua)
    assert len(_marched(lua)) == 1, "a second squad was sent at a chest already paid for"
    assert "spent=1" in report, report


def test_a_claim_is_proven_by_the_reward_window_and_not_by_the_send():
    """A refused claim returns exactly like a paid one, so the send cannot be the proof.
    The chest is spent when the reward window comes up shortly after — and stays queued
    until it does."""
    if not _needs_lua("payment is the reward window"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _dug_and_home(lua)
    report = _step(lua)
    assert "claim1" in report, report
    assert _queued(lua) == 1, "a sent claim is not a paid claim"
    _reward(lua)
    report = _step(lua)
    assert "paid=1" in report, report
    assert _queued(lua) == 0


def test_a_claim_that_never_pays_is_tried_again_until_the_chest_is_gone():
    """«Продолжать попытки, пока сокровище не будет взято или не исчезнет» (#1318).

    THE CAP WAS THE BUG. Four tries used to end a chest — and «claim-unconfirmed» is a
    chest still lying on the map, still ours, still worth a send. So there is no cap any
    more: the ramp spaces the tries out and the only two ends are the reward (or the
    server's own «claim repeat») and the chest going off the map. What must never happen
    is the chest being recorded as TAKEN on the strength of a send.
    """
    if not _needs_lua("a claim that never pays"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _dug_and_home(lua)
    for _ in range(8):
        _step(lua)
        lua.execute("NOW = NOW + 16000")      # past the ramp's longest step
    assert len(_claims(lua)) > lua_actions.TREASURE_RESEND_TRIES + 4, _claims(lua)
    assert _queued(lua) == 1, "a chest still on the map must still be worked"
    assert int(lua.eval("DataCenter.__lw_treasure_auto.paid_all or 0")) == 0, \
        "nothing was paid, so nothing may be counted as paid"
    #: …and it ends when the chest does, not when a counter does
    lua.execute("NOW = NOW + %d" % ((lua_actions.TREASURE_TARGET_TTL_SEC + 1) * 1000))
    report = _step(lua)
    assert "expired=1" in report, report
    assert _queued(lua) == 0


def test_a_sent_claim_waits_its_retry_out_rather_than_going_every_tick():
    """A refusal says nothing, so the retry is on a clock. Four tries inside one minute
    would be four tries spent while the alliance is still digging."""
    if not _needs_lua("the retry is on a clock"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _dug_and_home(lua)
    _step(lua)
    assert len(_claims(lua)) == 1
    lua.execute("NOW = NOW + 100")
    report = _step(lua)
    assert len(_claims(lua)) == 1, "a second claim went out inside the cooldown"
    assert "claimed-waiting" in report, report
    #: the ramp's FIRST step is short on purpose — the interesting refusal is the one that
    #: raced the server by a fraction of a second — and its last is long, because a chest
    #: that has refused eight times will refuse a ninth.
    lua.execute("NOW = NOW + %d" % (lua_actions.TREASURE_CLAIM_RAMP_MS[0] + 50))
    _step(lua)
    assert len(_claims(lua)) == 2, _claims(lua)


def test_a_reward_window_long_after_the_claim_is_not_taken_as_payment():
    """The window is the client's for every reward there is. Read late it would mark a
    chest paid because something else was collected."""
    if not _needs_lua("a stale reward window"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _dug(lua)
    _step(lua)
    lua.execute("NOW = NOW + %d" % ((lua_actions.TREASURE_PAID_WINDOW_SEC + 5) * 1000))
    _reward(lua)
    report = _step(lua)
    assert "paid=1" not in report, report


def test_a_chest_older_than_its_ttl_is_written_off():
    """A chest is on the map for minutes. Keeping it for ever means marching squads at an
    empty tile, and the write-off is named in the report rather than being silent."""
    if not _needs_lua("a chest expires"):
        return
    lua = _vm()
    _announce(lua)
    lua.execute("DataCenter.__lw_treasure_auto.ttl = 60")
    lua.execute("NOW = NOW + 61000")
    report = _step(lua)
    assert _marched(lua) == []
    assert "expired=1" in report, report
    assert _queued(lua) == 0


def test_no_free_squad_is_a_note_and_not_a_failure():
    """Every squad out is an ordinary evening, not a fault — and the chest stays queued so
    the next tick can send the squad that comes home."""
    if not _needs_lua("no free squad"):
        return
    lua = _vm(squads=((1, 3000, True), (2, 0, False)))
    _announce(lua)
    report = _step(lua)
    assert _marched(lua) == []
    assert "no-free-squad" in report, report
    assert "busy=1" in report and "empty=1" in report, report
    assert _queued(lua) == 1


def test_only_the_allowed_slots_are_spent():
    """The squads a run may spend are the player's choice, parked ahead of the press the
    same way the rally's are."""
    if not _needs_lua("the allowed slots"):
        return
    lua = _vm(allowed=(3,))
    _announce(lua)
    _step(lua)
    assert _marched(lua)[0]["formation"] == 2000000000000000003, _marched(lua)


def test_the_poll_is_true_when_nothing_is_listening():
    """A client restart wipes the VM and the hook with it. An errand that only asked
    about targets would wait for ever for a chest it cannot hear, so «nobody is
    listening» is work in its own right — and false once armed with nothing queued."""
    if not _needs_lua("the poll's two truths"):
        return
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    _squads(lua, ((1, 3000, False),))
    assert lua.eval(lua_actions.treasure_auto_check()) is True
    lua.execute(lua_actions.treasure_watch_install())
    lua.execute(lua_actions.treasure_auto_arm_parked())
    assert lua.eval(lua_actions.treasure_auto_check()) is False
    _announce(lua)
    assert lua.eval(lua_actions.treasure_auto_check()) is True
    _step(lua)
    _dug_and_home(lua)
    _dug(lua)
    _step(lua)                      # the claim goes out — and is not yet proof
    assert lua.eval(lua_actions.treasure_auto_check()) is True
    _reward(lua)                    # …the reward window is
    _step(lua)
    assert lua.eval(lua_actions.treasure_auto_check()) is False


def test_stopping_the_debug_ring_leaves_the_errand_its_ear():
    """Two consumers, one hook. Unhooking because the debug page stopped recording would
    leave the errand deaf with nothing on screen to say so — so the doors go back only
    when nobody is listening, and the reply says which."""
    if not _needs_lua("the ring stops, the ear stays"):
        return
    lua = _vm()
    lua.execute(lua_actions.treasure_watch_stop())
    said = list(lua.eval("SAID").values())
    assert "hooked=1" in said[-1] and "auto=1" in said[-1], said[-1]
    _announce(lua)
    assert _queued(lua) == 1
    #: and with the errand switched off too, the doors do go back
    lua.execute(lua_actions.treasure_auto_disarm())
    lua.execute(lua_actions.treasure_watch_stop())
    said = list(lua.eval("SAID").values())
    assert "hooked=0" in said[-1], said[-1]
    _announce(lua, uuid=_OTHER_UUID)
    assert _queued(lua) == 1


def test_the_disarm_keeps_a_chest_that_is_halfway_through():
    """Off means «stop turning announcements into targets», not «forget the squad you
    already sent»: a chest with our squad on it is still worth finishing."""
    if not _needs_lua("disarm keeps the queue"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    lua.execute(lua_actions.treasure_auto_disarm())
    assert _queued(lua) == 1
    _announce(lua, uuid=_OTHER_UUID, xy=_FAR)
    assert _queued(lua) == 1


def test_the_recipe_names_the_presses_it_needs():
    """The ability is one scenario and the panel only plays it, so the recipe has to name
    buttons that exist — a typo here is a run that fails at the press."""
    if not _needs_lua("the recipe's presses"):
        return
    import game_buttons                                     # noqa: E402
    from lastwar_bot import script_engine as se             # noqa: E402

    src = (ROOT / "src" / "lastwar_bot" / "actions" / "auto_treasure.md").read_text(
        encoding="utf-8")
    defaults, rest = se.extract_defaults(src)
    assert set(defaults) == {"squads", "grace", "ttl", "look"}, defaults
    for name, value in defaults.items():
        rest = rest.replace("{%s}" % name, se.render_value(value))
    program = se.parse_text(rest)

    def _taps(steps):
        """Every press, INCLUDING the ones inside a branch — the retry that fetches an
        army lives in an `IF`, and a check that only walked the top level would pass over
        a button name that does not exist."""
        for step in steps:
            if isinstance(step, se.TapStmt):
                yield step.name
            for attr in ("body", "then_block", "else_block", "steps"):
                inner = getattr(step, attr, None)
                if inner:
                    yield from _taps(inner)

    pressed = list(_taps(program))
    #: arm, the look around and the harvest of what it saw, the step, the retry after an
    #: army was fetched, and the pass that looks for the reward window a claim's payment
    #: shows up as. There is no lap here any more (#1296): the whole-server walk is a
    #: recipe somebody presses by hand, and nothing in this one calls it.
    #: …and there is one press FEWER than there was (#1318). The recipe used to sleep a
    #: second and a half after a claim and press again, because that was the only way to
    #: see the reward window. The watch inside the game looks five times a second, so the
    #: confirmation — and every retry after it — happens there instead.
    assert pressed == ["treasure_auto_arm", "treasure_look", "treasure_scan_harvest",
                       "treasure_auto_step", "treasure_auto_step",
                       "dismiss_treasure_reward"], pressed
    for name in pressed:
        assert name in game_buttons.BUTTONS, name

    #: …and the errand CALLS nothing: the lap used to be a `CALL` on a period, and that
    #: period is what was deleted. The manual lap is still a recipe and its presses are
    #: checked the same way, because the button it presses must still exist.
    def _calls(steps):
        for step in steps:
            if isinstance(step, se.CallStmt):
                yield step.action_name
            for attr in ("body", "then_block", "else_block", "steps"):
                inner = getattr(step, attr, None)
                if inner:
                    yield from _calls(inner)

    called = list(_calls(program))
    assert called == [], called
    scan_src = (ROOT / "src" / "lastwar_bot" / "actions"
                / "scan_treasures.md").read_text(encoding="utf-8")
    scan_defaults, scan_rest = se.extract_defaults(scan_src)
    for name, value in scan_defaults.items():
        scan_rest = scan_rest.replace("{%s}" % name, se.render_value(value))
    scan_pressed = list(_taps(se.parse_text(scan_rest)))
    assert scan_pressed == ["treasure_scan_start", "treasure_scan_harvest"], scan_pressed
    for name in scan_pressed:
        assert name in game_buttons.BUTTONS, name


def test_a_squad_that_reads_empty_is_asked_about_rather_than_refused():
    """The client's soldier count is a reply cache (#1285): the same squads read 3123 and
    then 0 with the army untouched in the game. A run with a chest and no squad to send
    must ASK — refusing on a number nobody has fetched is refusing on nothing."""
    if not _needs_lua("an empty squad is asked about"):
        return
    lua = _vm(squads=((1, 0, False), (2, 0, False)))
    lua.execute("ASKED = {} "
                "MsgDefines.GetFormationSoldier = 'formation.get.soldier' "
                "local orig = SFSNetwork.SendMessage "
                "SFSNetwork.SendMessage = function(cmd, a, ...) "
                "if cmd == 'formation.get.soldier' then ASKED[#ASKED+1] = a end "
                "return orig(cmd, a, ...) end")
    _announce(lua)
    report = _step(lua)
    assert "asked-for-army" in report, report
    assert len(list(lua.eval("ASKED").values())) == 2, report
    #: and once the army is back, the same press sends without another announcement
    lua.execute("for _, f in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) "
                "do f.totalSoldierNum = 3000 end")
    _step(lua)
    assert len(_marched(lua)) == 1, _marched(lua)


def test_a_run_with_a_squad_does_not_ask_for_an_army():
    """The fetch is off the fast path: a chest that has a squad to send must not pay for
    a request it does not need."""
    if not _needs_lua("no needless army request"):
        return
    lua = _vm()
    _announce(lua)
    report = _step(lua)
    assert "asked-for-army" not in report, report


def test_a_chest_nobody_shared_is_still_claimed():
    """WHAT THE FIRST LIVE CHEST TAUGHT (#1296). The alliance dug a treasure for twenty
    minutes and not one `world.treasure.share.chat` crossed the wire — the share is
    something a PLAYER does, and often nobody does it. The dig broadcast arrives anyway,
    once per member who finishes, and it carries the uuid: enough to CLAIM, never enough
    to march (there is no tile in it). So the target is parked claim-only and taken.

    That is the path that actually took the live chest, by hand, before this existed.
    """
    if not _needs_lua("a chest nobody shared"):
        return
    lua = _vm()
    _dug(lua, plain=True)                 # no announcement at all, only the dig feed
    assert _queued(lua) == 1, "the dig broadcast alone must produce a target"
    report = _step(lua)
    assert _marched(lua) == [], "there is no tile in a dig broadcast — nothing to march at"
    claims = _claims(lua)
    assert len(claims) == 1, claims
    assert str(claims[0]["uuid"]) == str(_UUID), claims
    assert "claim1" in report and "dig-feed" in report, report
    #: and it is spent on the reward window like any other
    _reward(lua)
    _step(lua)
    assert _queued(lua) == 0


def test_a_shared_chest_is_not_duplicated_by_its_own_dig_feed():
    """Both doors lead to one target. A chest announced in chat AND dug by the alliance
    must not become two — one squad's worth of work claimed twice."""
    if not _needs_lua("one chest, two doors"):
        return
    lua = _vm()
    _announce(lua)
    _dug(lua, plain=True)
    assert _queued(lua) == 1, "the same chest arrived twice and became two targets"
    t = lua.eval("DataCenter.__lw_treasure_auto.targets[1]")
    assert t["dug"] is not None
    assert not t["claim_only"], "a shared chest has a tile — it must still be marched at"



def test_a_push_is_read_although_it_carries_no_sfsobject_keys():
    """THE SHAPE A REAL PUSH HAS, and the bug it hid until a live chest (#1296).

    An OUTGOING message is an SFSObject and answers `SFSObject.GetKeys`. An incoming one,
    by the time `HandleMessage` sees it, is a plain Lua table that answers nothing —
    probed live against a real `push.detect.treasure.claim`: `KEYS[] PAIRS[operator=table
    uuid=…]`. So every push the ring recorded came out with empty fields, and the
    harvest — which read the dig gate with `SFSObject.GetData(obj, "uuid")` — could never
    see a uuid at all. The gate that opens the claim was dead and nothing said so.
    """
    if not _needs_lua("a plain-table push"):
        return
    lua = _vm()
    _announce(lua, plain=True)                    # the announcement, plain-table shape
    assert _queued(lua) == 1, "a plain-table share must still become a target"
    _step(lua)
    _dug_and_home(lua)
    _dug(lua, plain=True)                         # …and the dig gate off a plain table
    t = lua.eval("DataCenter.__lw_treasure_auto.targets[1]")
    assert t["dug"] is not None, "the dig broadcast was not read off a plain table"
    report = _step(lua)
    assert "claim1" in report, report


def test_both_message_shapes_reach_the_ring():
    """The ring is the debug page's, and it had the same blind spot: `f=""` on every push
    it ever recorded. Both shapes now come through with their fields."""
    if not _needs_lua("both shapes in the ring"):
        return
    import json as _json

    lua = _vm()
    _dug(lua, plain=True)
    _dug(lua, uuid=_OTHER_UUID, plain=False)
    feed = _json.loads(str(lua.eval(lua_actions.treasure_watch_drain())))
    #: The claim each of those provokes rides the ring too, since #1886 — the hook claims
    #: in the frame it hears — so the two pushes are the INCOMING half of it.
    fields = [item["f"] for item in feed["items"] if item["d"] == "in"]
    assert len(fields) == 2, feed
    assert all("uuid=" in f for f in fields), fields



def test_the_poll_marker_is_read_back_the_way_the_game_writes_it():
    """THE BUG THIS ERRAND WAS BLOCKED BY, and it was not in this errand.

    A poll trigger's check is asked with a chunk that logs `TRIGCHK=true|false`, and the
    reading of that line lowered the haystack while spelling the needle in the marker's
    own capitals — `"TRIGCHK=true" in "trigchk=true"` is False for every reading there
    can be. So `Schedule.poll` answered «nothing to do» to a game that was plainly saying
    yes, and NO poll trigger had ever fired: not `session_kick`, not this one. Nothing in
    any log said so, because a poll that does not fire writes nothing — which is exactly
    what a quiet minute looks like.

    Found live: the same chunk run by hand returned `['TRIGCHK=true']` while the panel's
    own verdict on those very lines was False. Pinned here on the real shape the daemon
    hands back — and on the case-flipped ones, since either side may be lowered by
    whatever carries the line.
    """
    from panel import triggers as triggersmod                # noqa: E402

    assert triggersmod.poll_said_yes(["TRIGCHK=true"]) is True
    assert triggersmod.poll_said_yes(["trigchk=true"]) is True
    assert triggersmod.poll_said_yes(["noise", "TRIGCHK=true", "noise"]) is True
    assert triggersmod.poll_said_yes(["TRIGCHK=false"]) is False
    assert triggersmod.poll_said_yes([]) is False
    assert triggersmod.poll_said_yes(None) is False
    #: …and the chunk that produces those lines names the same marker
    chunk = triggersmod.poll_chunk("1 == 1")
    assert triggersmod.POLL_MARKER + "=" in chunk, chunk
    assert "pcall" in chunk, "a check that throws must read as no, not take the watch down"


def test_a_poll_check_that_is_true_survives_the_whole_round_trip():
    """The two halves together, over a real Lua: the chunk the panel sends, the line the
    client writes, the verdict the panel reads. Either half alone can be right while the
    pair is broken — which is what happened."""
    if not _needs_lua("the poll round trip"):
        return
    from panel import triggers as triggersmod                # noqa: E402

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    _squads(lua, ((1, 3000, False),))
    lua.execute(triggersmod.poll_chunk(lua_actions.treasure_auto_check()))
    said = list(lua.eval("SAID").values())
    assert triggersmod.poll_said_yes(said) is True, said       # nothing listening yet
    lua.execute(lua_actions.treasure_watch_install())
    lua.execute(lua_actions.treasure_auto_arm_parked())
    lua.execute("SAID = {}")
    lua.execute(triggersmod.poll_chunk(lua_actions.treasure_auto_check()))
    said = list(lua.eval("SAID").values())
    assert triggersmod.poll_said_yes(said) is False, said      # armed, nothing queued


def test_the_trigger_polls_the_errand_and_runs_the_recipe():
    """The catalogue entry is the whole wiring: a poll (the announcement rides a TLS chat
    channel this repository cannot sniff, so a wire listener is deaf by construction),
    the check the errand answers, and the one recipe it plays."""
    if not _needs_lua("the trigger's wiring"):
        return
    from panel import triggers as triggersmod                # noqa: E402

    entry = [t for t in triggersmod.DEFAULT_TRIGGERS if t.name == "treasure_auto"]
    assert len(entry) == 1, [t.name for t in triggersmod.DEFAULT_TRIGGERS]
    trigger = entry[0]
    assert trigger.kind == triggersmod.KIND_POLL
    assert trigger.check == lua_actions.treasure_auto_check()
    assert trigger.scenario == ("auto_treasure",)
    assert trigger.enabled is False, "an errand that acts is opt-in"
    assert trigger.immediate is True, "a chest is a race — it does not wait in the queue"
    assert trigger.label_key == "triggers.item.treasure_auto"


# ---------------------------------------------------------------------------
# The third door: a lap of the map (#1296)
# ---------------------------------------------------------------------------
#
# «Скрытые сокровища не собираются, если они просто на карте … должно сканироваться
# карта на предмет сокровищ, а не только слушаться пуш шаринга.» The two doors above are
# both somebody TELLING the client about a chest; neither of them looks at the map, so a
# chest merely lying there reaches neither. The lap is what looks.
#
# What the stand-in below reproduces is the ONE property the design turns on, measured
# live: `WorldScene.PointManager` only holds what is IN VIEW. So the reading has to ride
# the lap, one box per waypoint, and a test that let the whole map be readable from a
# standing camera would pass over exactly the mistake that matters.

#: A small square server, so a lap is four waypoints rather than a hundred and
#: twenty-one. The arithmetic is the game's own: `pid = y * size + x + 1`, checked
#: against `SceneUtils.TilePosToIndex` on the live client at four coordinates.
_MAP = 40
_CHEST_AT = (31, 27)
#: …and one on the other side of it, for the case where the chat share got there first.
_SHARED_AT = (11, 9)


def _scan_vm(chests=((_CHEST_AT, _OTHER_UUID, _SERVER, False),), world: bool = True):
    """A VM with a map under it: a point manager that answers only near the camera.

    Each `chests` entry is `((x, y), uuid, server, dug)`. Everything else on the map is
    an ordinary tile of another kind, which is what makes «found nothing» and «looked at
    nothing» different answers.
    """
    lua = _vm()
    lua.execute("""
WORLD = %s
JUMPS = {}
SCHEDULED = {}
CAMERA = {x = -999, y = -999}
SceneUtils.GetIsInWorld = function() return WORLD end
CS.UnityEngine.Vector3 = function(x, y, z) return {x = x, y = y, z = z} end
CS.UnityEngine.Object = {FindObjectsOfType = function() return {Length = 0} end}
DataCenter.ActDispatchTaskDataManager = DataCenter.ActDispatchTaskDataManager or {}
GoToUtil = {GotoWorldPos = function(v, h, a, b, srv)
  JUMPS[#JUMPS+1] = {x = (v.x - 1) / 2, y = (v.z - 1) / 2, zoom = h, server = srv}
  CAMERA = {x = (v.x - 1) / 2, y = (v.z - 1) / 2}
end}
TimerManager = {GetInstance = function()
  return {DelayInvoke = function(self, fn, at)
    SCHEDULED[#SCHEDULED+1] = {fn = fn, at = at, i = #SCHEDULED}
  end}
end}
CHESTS = {}
-- THE POINT MANAGER ONLY KNOWS WHAT IS IN VIEW. Anything further than the camera's own
-- reach answers nil, exactly as the live one does once the camera has jumped away.
_G.WS = {CurTilePos = {x = 0, y = 0}, TileCount = {x = %d, y = %d},
         PointManager = {GetPointInfo = function(self, pid)
  local x, y = (pid - 1) %% %d, math.floor((pid - 1) / %d)
  if math.abs(x - CAMERA.x) > 12 or math.abs(y - CAMERA.y) > 12 then return nil end
  local chest = CHESTS[pid]
  if chest ~= nil then return chest end
  return {PointType = 6}
end}}
""" % ("true" if world else "false", _MAP, _MAP, _MAP, _MAP))
    for (x, y), uuid, server, dug in chests:
        lua.execute("CHESTS[%d] = {PointType = %d, uuid = %d, serverId = %d, "
                    "expireTime = NOW_EXPIRE, allianceAbbr = 'AL1', ownerUid = %s}"
                    .replace("NOW_EXPIRE", "1786199155709")
                    % (y * _MAP + x + 1, lua_actions.TREASURE_POINT_TYPE, uuid, server,
                       ("'1000000000000009'" if dug else "nil")))
    return lua


def _park_camera(lua, x: int, y: int) -> None:
    """Put the camera on a tile WITHOUT a jump — where an ordinary player left it.

    The look around reads `WorldScene.CurTilePos` and the box around it; the stand-in
    point manager answers near `CAMERA`. Both are set here, so a test can say «we happen
    to be standing here» without the errand having moved anything.
    """
    lua.execute("CAMERA = {x = %d, y = %d} _G.WS.CurTilePos = {x = %d, y = %d}"
                % (x, y, x, y))


def _walk(lua) -> None:
    """Run the lap the game's timer was handed, in the order it would run it."""
    lua.execute(lua_actions.treasure_scan_sweep())
    lua.execute("""
local queue = {}
for _, item in ipairs(SCHEDULED) do queue[#queue+1] = item end
table.sort(queue, function(a, b)
  if a.at == b.at then return a.i < b.i end
  return a.at < b.at end)
for _, item in ipairs(queue) do item.fn() end
""")
    lua.execute(lua_actions.treasure_scan_harvest())


def _park_scan(lua, **cfg) -> None:
    """Park what the recipe parks — a `TAP` takes no arguments of its own."""
    parts = ", ".join("%s = %s" % (k, v) for k, v in cfg.items())
    lua.execute("DataCenter.__lw_treasure_scan_cfg = {%s}" % parts)


def _targets(lua) -> list:
    return [dict(t.items())
            for t in lua.eval("DataCenter.__lw_treasure_auto.targets").values()]


def test_the_look_around_finds_a_chest_without_moving_anything():
    """WHAT REPLACED THE LAP (#1296), and the two halves of why it is allowed to run on
    every tick.

    «Убирай обход, он не нужен, нужно просто слушать всегда окружение, т.к. 99% кладов
    находятся в улье, а не на карте.» The whole-server walk was measured twice — 19 chests
    and then 21, **ours zero both times** — at 48 s of camera every five minutes. What is
    kept is the reading: when the client is out on the map anyway, whatever is in the box
    around it comes home for free.

    So: it finds the chest under the camera, and it JUMPS NOWHERE. The second half is the
    one that stops this quietly becoming the lap again under a new name.
    """
    if not _needs_lua("the look around"):
        return
    lua = _scan_vm()
    _park_camera(lua, *_CHEST_AT)
    lua.execute(lua_actions.treasure_look_around())
    lua.execute(lua_actions.treasure_scan_harvest())

    assert list(lua.eval("JUMPS").values()) == [], "the look moved the camera"
    assert list(lua.eval("SCHEDULED").values()) == [], "the look scheduled a walk"
    targets = _targets(lua)
    assert len(targets) == 1, targets
    found = targets[0]
    assert int(found["uuid"]) == _OTHER_UUID, found
    assert (int(found["x"]), int(found["y"])) == _CHEST_AT, found
    assert found["src"] == "scan", found
    assert int(lua.eval("DataCenter.__lw_treasure_scan.tiles")) > 100

    #: …and standing somewhere else, it sees nothing — the point manager only holds what
    #: the client has been answered about, which is the whole limit this design accepts.
    lua2 = _scan_vm()
    _park_camera(lua2, _CHEST_AT[0] + 400, _CHEST_AT[1] + 400)
    lua2.execute(lua_actions.treasure_look_around())
    lua2.execute(lua_actions.treasure_scan_harvest())
    assert _targets(lua2) == [], "a chest was seen from the other side of the server"


def test_the_look_around_is_silent_in_the_city():
    """The point manager belongs to the world scene, so in the city there is nothing to
    read — and the run says which of «nothing there» and «not looking» it was."""
    if not _needs_lua("the look around in the city"):
        return
    lua = _scan_vm(world=False)
    _park_camera(lua, *_CHEST_AT)
    lua.execute(lua_actions.treasure_look_around())
    assert str(lua.eval("DataCenter.__lw_treasure_scan.why")) == "not-in-world"
    assert int(lua.eval("DataCenter.__lw_treasure_scan.tiles")) == 0
    assert list(lua.eval("JUMPS").values()) == []


def test_a_lap_of_the_map_finds_a_chest_nobody_announced():
    """The whole point of the third door. Nothing is shared and nothing is dug — the chest
    is just lying there — and the lap comes home with its uuid AND its tile, which is the
    pair a march needs and the dig feed can never give."""
    if not _needs_lua("a lap finds a chest"):
        return
    lua = _scan_vm()
    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    _walk(lua)

    targets = _targets(lua)
    assert len(targets) == 1, targets
    found = targets[0]
    assert int(found["uuid"]) == _OTHER_UUID, found
    assert (int(found["x"]), int(found["y"])) == _CHEST_AT, found
    assert int(found["pid"]) == _CHEST_AT[1] * _MAP + _CHEST_AT[0] + 1, found
    assert int(found["server"]) == _SERVER, found
    assert found["src"] == "scan", found
    assert found.get("dug") is None, "no finisher on it — the lap says nothing else"
    #: the chest's OWN deadline travels with it: the map knows when it goes away, and
    #: that beats any age the errand could keep for itself.
    assert int(found["expire"]) == 1786199155709, found
    #: …and the run says what it looked at, so «no chest on the map» and «the client knew
    #: no tiles at all» stay different answers.
    report = str(lua.eval(lua_actions.treasure_scan_report()))
    assert "new=1" in report and "tiles=" in report, report
    assert int(lua.eval("DataCenter.__lw_treasure_scan.tiles")) > 100, report


def test_a_dead_world_scene_is_found_again_rather_than_kept():
    """A destroyed Unity object answers `nil` instead of throwing, so the cache guard has
    to look at the VALUE. Caught live: a lap reported 121 waypoints scheduled and 0 read,
    because `_G.WS` was a WorldScene from a session that had ended and every member of it
    — `PointManager`, `TileCount`, `CurTilePos` — was `nil` with nothing saying why."""
    if not _needs_lua("a dead scene is re-found"):
        return
    lua = _scan_vm()
    #: the live scene, put aside, and a dead one in its place — dead exactly as Unity
    #: leaves one: an object that answers, and answers nothing.
    lua.execute("""
ALIVE = _G.WS
FOUND = 0
_G.WS = {}
CS.UnityEngine.Object = {FindObjectsOfType = function()
  FOUND = FOUND + 1
  return {Length = 1, [0] = setmetatable(ALIVE, {__index = {
    GetType = function() return {Name = "WorldScene"} end}})}
end}
typeof = function(x) return x end
""")
    lua.execute(lua_actions.FIND_WORLD_SCENE
                + 'SCENE_BACK = (WS ~= nil and WS.PointManager ~= nil)')
    assert bool(lua.eval("SCENE_BACK")) is True, "the dead scene was kept"
    assert int(lua.eval("FOUND")) == 1, "it was not looked for"


def test_a_chest_of_another_alliance_is_not_queued():
    """The lap's most important gate, and it was learned the expensive way: the first live
    lap found nineteen chests and the account could take none of them — every claim came
    back `errorCode 801354 — player not in same alliance`. A detect-event treasure is
    placed by ONE alliance's event and dug by ITS members, so a foreign chest is a squad
    spent on a tile the server will not pay for, however plainly it is drawn on the map."""
    if not _needs_lua("a foreign chest is skipped"):
        return
    lua = _scan_vm(chests=((_CHEST_AT, _OTHER_UUID, _SERVER, False),
                           (_SHARED_AT, _UUID, _SERVER, False)))
    #: the client's own alliance is a 32-character uuid; one chest is ours, one is not.
    lua.execute("LuaEntry.Player.allianceId = 'a0000000000000000000000000000001' "
                "CHESTS[%d].allianceId = 'a0000000000000000000000000000001' "
                "CHESTS[%d].allianceId = 'b0000000000000000000000000000002'"
                % (_CHEST_AT[1] * _MAP + _CHEST_AT[0] + 1,
                   _SHARED_AT[1] * _MAP + _SHARED_AT[0] + 1))
    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    _walk(lua)

    targets = _targets(lua)
    assert len(targets) == 1, targets
    assert int(targets[0]["uuid"]) == _OTHER_UUID, targets

    #: AND THE THREE NUMBERS ARE SAID APART. «Found 2» on its own promises two gifts and
    #: is worth one; on the live map it was 19 found and 1 takeable. Both the sentence
    #: and the reading the panel draws lead with the split.
    report = str(lua.eval(lua_actions.treasure_scan_report()))
    assert "found=2" in report and "ours=1" in report and "foreign=1" in report, report
    counts = str(lua.eval(lua_actions.treasure_scan_counts()))
    assert "found=2" in counts and "ours=1" in counts and "foreign=1" in counts, counts
    assert "ago=0" in counts, counts


def test_a_map_that_has_never_been_walked_is_not_a_map_with_nothing_on_it():
    """`ago=-1`, and it is the same rule as everywhere else today: «no lap has been walked
    in this client» and «a lap found nothing» must not share a zero. The panel draws the
    two as different sentences."""
    if not _needs_lua("never walked is not empty"):
        return
    lua = _scan_vm()
    counts = str(lua.eval(lua_actions.treasure_scan_counts()))
    assert "ago=-1" in counts, counts
    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    _walk(lua)
    assert "ago=0" in str(lua.eval(lua_actions.treasure_scan_counts()))


def test_a_chest_that_is_already_dug_is_claimed_before_a_squad_is_spent_on_it():
    """THE SUCCESS RECORDING THAT WAS MISSING (#1886, live 2026-08-23). `ownerUid` used to
    open the claim without closing the march — a dug chest was MARCHED at first, on the
    grounds that no chest had ever been caught without the field and a gate needs a
    success recording. One arrived and it cost a hundred seconds: the chest was seen
    already dug the second the client reached the map, four marches were sent at it and
    not one ever appeared (`march-unanswered`), and the blind claim the resend ladder
    finally reached was paid on its FIRST try — `lag=99974ms`.

    So the order is the other way round now: the claim goes first and no squad is spent
    while it is being tried."""
    if not _needs_lua("a dug chest is claimed first"):
        return
    lua = _scan_vm(chests=((_CHEST_AT, _OTHER_UUID, _SERVER, True),))
    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    _walk(lua)
    assert _targets(lua)[0].get("dug") is not None, _targets(lua)
    report = _step(lua)
    assert _marched(lua) == [], _marched(lua)
    claims = _claims(lua)
    assert len(claims) == 1, claims
    assert str(claims[0]["uuid"]) == str(_OTHER_UUID), claims
    assert "claim1" in report, report


def test_the_dig_broadcast_is_answered_in_the_frame_it_arrives():
    """«Клад должен быть собран МГНОВЕННО.» The wire has exactly one hearable dig signal —
    `push.detect.treasure.claim`, one per member who finishes — and until #1886 hearing it
    only STAMPED the chest: the claim itself waited for the game-side watch (a fifth of a
    second) or for the panel's next press (ten seconds and a cooldown). The hook now runs
    the watch itself, so the claim leaves on the message that opened it.

    No press anywhere in this test: the broadcast arrives and the gift is asked for."""
    if not _needs_lua("the broadcast is answered at once"):
        return
    lua = _vm()
    _dug(lua, plain=True)
    claims = _claims(lua)
    assert len(claims) == 1, "the claim must leave inside the hook, not at the next tick"
    assert str(claims[0]["uuid"]) == str(_UUID), claims


def test_the_tile_flipping_to_dug_is_noticed_without_anybody_saying_so():
    """THE THIRD WATCHER, and the only one that needs nobody to speak (#1886). A tile flip
    cannot be HEARD — the map stream is decoded on the C# side and never reaches the Lua a
    hook can wrap — so the watch READS the chest's own point five times a second instead.
    A dig nobody broadcast is caught in a fifth of a second rather than at the next press."""
    if not _needs_lua("the tile is watched"):
        return
    lua = _scan_vm(chests=((_CHEST_AT, _OTHER_UUID, _SERVER, False),))
    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    _walk(lua)
    _step(lua)                                   # still being dug — a squad goes
    assert len(_marched(lua)) == 1, _marched(lua)
    assert _targets(lua)[0].get("dug") is None, _targets(lua)
    #: the client has to be holding that tile for its point manager to answer at all —
    #: live as well as here, which is why this watcher is a backstop and not the gate.
    _park_camera(lua, *_CHEST_AT)
    #: the alliance finishes and says nothing at all — only the tile changes
    lua.execute("CHESTS[%d].ownerUid = '1000000000000009'"
                % (_CHEST_AT[1] * _MAP + _CHEST_AT[0] + 1))
    lua.execute("if DataCenter.__lw_treasure_auto.tick then "
                "DataCenter.__lw_treasure_auto.tick() end")
    t = _targets(lua)[0]
    assert t.get("dug") is not None, t
    assert str(t.get("dug_by")) == "tile", t


def test_the_status_when_it_was_heard_is_written_down_as_the_plan():
    """The branch is a decision taken once, at the moment the chest is heard, and it is
    readable afterwards: `claim` for a chest already dug, `march` for one still being dug.
    A branch rediscovered by whoever looks next is a branch that can disagree with itself."""
    if not _needs_lua("the plan is written down"):
        return
    dug = _scan_vm(chests=((_CHEST_AT, _OTHER_UUID, _SERVER, True),))
    _park_scan(dug, server=_SERVER, step=20, every=0, lag=0)
    _walk(dug)
    assert str(_targets(dug)[0].get("plan")) == "claim", _targets(dug)

    digging = _scan_vm(chests=((_CHEST_AT, _OTHER_UUID, _SERVER, False),))
    _park_scan(digging, server=_SERVER, step=20, every=0, lag=0)
    _walk(digging)
    assert str(_targets(digging)[0].get("plan")) == "march", _targets(digging)
    _step(digging)
    assert len(_marched(digging)) == 1, _marched(digging)


def test_the_run_says_how_long_the_chest_waited_from_being_heard():
    """`lag` measures from the chest becoming takeable, which is the errand's own half.
    The player's sentence is «услышали — собрали», so the whole distance is measured too
    and printed beside it — a number, not an impression."""
    if not _needs_lua("heard-to-claim is reported"):
        return
    lua = _vm()
    _dug(lua, plain=True)                        # heard and claimed in one instant
    _reward(lua)
    report = _step(lua)
    assert "heard-to-claim=0ms" in report, report
    watch = str(lua.eval(lua_actions.treasure_reaper_state()))
    assert "hear=0" in watch, watch


def test_a_dug_chest_the_server_refuses_gets_its_squad_after_the_ramp():
    """…and the claim-first is a TRY, not a verdict. `ownerUid` says «this chest has been
    worked», never «this account may have it», so a chest that swallows the whole ramp in
    silence is handed back to the march path — the old order, one ramp late, which is what
    the case #1296 measured (a chest the ALLIANCE dug and we had not) actually needs."""
    if not _needs_lua("a refused claim-first still marches"):
        return
    lua = _scan_vm(chests=((_CHEST_AT, _OTHER_UUID, _SERVER, True),))
    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    _walk(lua)
    #: every claim refused — the silence a refusal comes in, over and over.
    for _ in range(lua_actions.TREASURE_CLAIM_FIRST_TRIES):
        _step(lua)
        lua.execute("NOW = NOW + %d" % (max(lua_actions.TREASURE_CLAIM_RAMP_MS) + 1))
    assert len(_claims(lua)) == lua_actions.TREASURE_CLAIM_FIRST_TRIES, _claims(lua)
    assert _marched(lua) == [], "no squad while the claim is still being tried"
    #: …and only then does a squad go.
    _step(lua)
    assert len(_marched(lua)) == 1, _marched(lua)


def test_a_dig_feed_that_arrives_while_our_squad_walks_still_waits_for_it():
    """The claim-first is for a chest that arrives already dug with NO squad out. A march
    already in flight keeps the rule #1296 bought: the alliance having dug it is not this
    account having dug it, and a claim sent into a march on the road is refused."""
    if not _needs_lua("a march in flight is not overruled"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)                                   # the squad goes out
    _still_marching(lua, slot=1)
    _dug(lua)                                    # …and the alliance finishes meanwhile
    report = _step(lua)
    assert _claims(lua) == [], _claims(lua)
    assert "dug-still-marching" in report, report


def test_the_lap_reads_each_box_after_its_own_jump():
    """The point manager only holds what is in view, so a lap that read every box from
    where it started would find nothing. This is that mistake, made on purpose: the
    scrapes are run WITHOUT the jumps and the chest must stay unseen."""
    if not _needs_lua("the box follows the camera"):
        return
    lua = _scan_vm()
    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    lua.execute(lua_actions.treasure_scan_sweep())
    #: every other scheduled call is a scrape (jump, scrape, jump, scrape …) — run only
    #: those, so the camera never moves.
    lua.execute("for i, item in ipairs(SCHEDULED) do if i % 2 == 0 then item.fn() end end")
    lua.execute(lua_actions.treasure_scan_harvest())
    assert _targets(lua) == [], _targets(lua)


def test_a_chest_the_dig_feed_named_gets_its_tile_from_the_lap():
    """The two doors carry different halves of the same chest and must not make two of it.
    The broadcast gives a uuid and no tile — `claim_only`, nothing to march at — and the
    lap is what fills the tile in. One target, upgraded, marchable."""
    if not _needs_lua("the dig feed and the lap agree"):
        return
    lua = _scan_vm()
    _dug(lua, uuid=_OTHER_UUID)
    before = _targets(lua)
    assert len(before) == 1 and before[0]["claim_only"] is True, before
    assert int(before[0]["pid"]) == 0, before

    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    _walk(lua)

    after = _targets(lua)
    assert len(after) == 1, after
    assert int(after[0]["pid"]) == _CHEST_AT[1] * _MAP + _CHEST_AT[0] + 1, after
    assert after[0]["claim_only"] is False, after
    assert after[0]["src"] == "dig-feed+scan", after
    assert "upgraded=1" in str(lua.eval(lua_actions.treasure_scan_report()))


def test_a_chest_already_announced_is_not_queued_twice_by_the_lap():
    """A chest shared into chat carries its tile already. The lap must recognise it and
    leave it alone — two targets is two squads on one tile."""
    if not _needs_lua("the lap does not duplicate"):
        return
    lua = _scan_vm(chests=((_SHARED_AT, _UUID, _SERVER, False),))
    _announce(lua, uuid=_UUID, xy=_SHARED_AT)
    assert _queued(lua) == 1
    _park_scan(lua, server=_SERVER, step=20, every=0, lag=0)
    _walk(lua)
    assert _queued(lua) == 1, _targets(lua)
    assert "already-queued=1" in str(lua.eval(lua_actions.treasure_scan_report()))


def test_the_lap_is_refused_in_the_city_and_between_periods():
    """Three questions, and each of them is a lap not walked: the point manager belongs to
    the world scene, the period is minutes because a chest is out for minutes, and a
    period of zero is «never»."""
    if not _needs_lua("the lap's gate"):
        return
    lua = _scan_vm(world=False)
    _park_scan(lua, every_sec=300)
    lua.execute(lua_actions.treasure_scan_ask())
    assert int(lua.eval("DataCenter.__lw_treasure_scan_due")) == 0, "not in the world"

    lua.execute("WORLD = true")
    lua.execute(lua_actions.treasure_scan_ask())
    assert int(lua.eval("DataCenter.__lw_treasure_scan_due")) == 1, "in the world, never run"
    #: …and asking again in the same minute does not walk a second lap: deciding it was
    #: due STAMPED the clock.
    lua.execute(lua_actions.treasure_scan_ask())
    assert int(lua.eval("DataCenter.__lw_treasure_scan_due")) == 0, "the period holds"

    lua.execute("NOW = NOW + 301000")
    lua.execute(lua_actions.treasure_scan_ask())
    assert int(lua.eval("DataCenter.__lw_treasure_scan_due")) == 1, "the period passed"

    _park_scan(lua, every_sec=0)
    lua.execute("NOW = NOW + 3600000")
    lua.execute(lua_actions.treasure_scan_ask())
    assert int(lua.eval("DataCenter.__lw_treasure_scan_due")) == 0, "zero is off"


def test_being_out_in_the_world_is_not_work_by_itself():
    """The errand answers what it HEARD, and nothing else (#2390).

    «We are on the map» used to answer «yes» here (#1296), on the grounds that looking is
    one box of the point manager. What ran was the whole errand: measured beside a
    golden-zombie chain, which holds the client in the world for as long as it lasts, 53
    runs in 44 minutes and 42 % of the client, every one of them ending «nothing was sent
    this run» against a day whose allowance was already full.

    So an armed errand with an empty queue is quiet — in the world exactly as in the
    city — and only a chest it can name gets the client.
    """
    if not _needs_lua("the poll no longer asks whether we are on the map"):
        return
    lua = _scan_vm()
    lua.execute(lua_actions.treasure_watch_install())
    lua.execute(lua_actions.treasure_auto_arm_parked())
    assert bool(lua.eval(lua_actions.treasure_auto_check())) is False, \
        "an armed errand with nothing queued must not take the client"

    #: …and looking, which is still what a run does, does not make the next tick true
    lua.execute(lua_actions.treasure_look_around())
    assert bool(lua.eval(lua_actions.treasure_auto_check())) is False, "still nothing heard"

    #: the city was never the difference — an empty queue is idle in both scenes
    lua.execute("WORLD = false")
    assert bool(lua.eval(lua_actions.treasure_auto_check())) is False, "not in the world"


# ---------------------------------------------------------------------------
# The clock is gone; the ear is the way in (#1886)
# ---------------------------------------------------------------------------
#
# «Таймеры с сокровищем нужно переделать, убираем как таймер, он всё равно работает
# плохо, оставляем только слушатель сокровищ и исходим от этого — услышали, отправляем
# отряд или собираем.» The row is deleted rather than switched off: a scenario that still
# exists is one a stale profile file goes on playing for ever, so the retirement has to
# reach the FILE and carry the operator's switch to the listener that replaced it.


def test_the_clock_is_gone_and_names_the_listener_that_replaced_it():
    """No `auto_treasure` row in the catalogue any more, and the name is retired rather
    than merely absent — an absent one comes back the moment a stale template is read."""
    from panel import timers as timersmod
    from panel.runtime import settings_files

    assert not [t for t in timersmod.DEFAULT_TIMERS if t.name == "auto_treasure"], \
        "the errand is a listener's now, not a clock's"
    assert timersmod.RETIRED_ERRANDS.get("auto_treasure") == "treasure_auto"


def test_a_profile_that_had_the_clock_on_keeps_having_the_job_done(tmp=None):
    """The row goes, the switch travels, and neither comes back on the next launch.

    Everything a live profile had is here: the retired row switched ON, an ordinary row
    beside it, and a local template still offering the retired one — which is exactly the
    installation that would otherwise re-adopt it a day later.
    """
    import json, tempfile                                    # noqa: E402
    from panel import timers as timersmod                    # noqa: E402
    from panel import triggers as triggersmod                # noqa: E402
    from panel.runtime import settings_files                  # noqa: E402

    home = Path(tempfile.mkdtemp())
    rows = [{"name": "auto_treasure", "scenario": "auto_treasure",
             "interval_sec": 300, "enabled": True},
            {"name": "collect_base_resources", "scenario": "collect_base_resources",
             "enabled": True}]
    profile = home / "timers.json"
    profile.write_text(json.dumps(rows), encoding="utf-8")
    template = home / "template.json"
    template.write_text(json.dumps(rows), encoding="utf-8")

    kept = timersmod.TEMPLATE_FILE
    timersmod.TEMPLATE_FILE = str(template)
    try:
        catalogue = timersmod.load_profile_catalogue(str(profile))
        assert "auto_treasure" not in catalogue.names(), catalogue.names()
        assert catalogue.retired_on == ("auto_treasure",), catalogue.retired_on
        # …out of the store the catalogue lives in — a row since #2017.
        written = [e["name"] for e in settings_files.read(str(profile))]
        assert "auto_treasure" not in written, written
        seen = json.load(open(timersmod.seen_path(str(profile)), encoding="utf-8"))
        assert "auto_treasure" in seen, "…or a stale template hands it straight back"

        #: and a second launch is a quiet one: nothing to retire, nothing to announce
        again = timersmod.load_profile_catalogue(str(profile))
        assert "auto_treasure" not in again.names(), again.names()
        assert again.retired_on == (), again.retired_on
    finally:
        timersmod.TEMPLATE_FILE = kept

    #: the switch itself travels — the listener is turned on once, and only once, so a
    #: person who deliberately switches it off afterwards keeps it off
    trig_template = home / "trig_template.json"
    trig_template.write_text(json.dumps(
        [{"name": "treasure_auto", "scenario": "auto_treasure", "kind": "poll",
          "check": "true", "enabled": False}]), encoding="utf-8")
    triggers = home / "triggers.json"
    triggers.write_text(trig_template.read_text(encoding="utf-8"), encoding="utf-8")
    kept = triggersmod.TEMPLATE_FILE
    triggersmod.TEMPLATE_FILE = str(trig_template)
    try:
        assert triggersmod.turn_on(str(triggers), ("treasure_auto",)) == ("treasure_auto",)
        rows = {e["name"]: e for e in settings_files.read(str(triggers))}
        assert rows["treasure_auto"]["enabled"] is True
        assert triggersmod.turn_on(str(triggers), ("treasure_auto",)) == ()
    finally:
        triggersmod.TEMPLATE_FILE = kept


def test_a_poll_is_told_about_in_words_rather_than_in_lua():
    """A poll's log line names the trigger and its beat, never the check.

    Live, every one of these read «слушаю (function() local D = DataCenter …»: the whole
    Lua expression dumped where a sentence belongs. Unreadable is as good as untrue for
    somebody trying to tell a listener that heard nothing from one that was never up.
    """
    from panel import triggers as triggersmod                # noqa: E402

    said = []
    watcher = triggersmod.TriggerWatcher(
        catalogue=lambda: triggersmod.default_catalogue(), config=dict, spawn=None,
        submit=lambda *a, **k: "queued",
        log=lambda key, **fmt: said.append((key, fmt)))
    poll = next(t for t in triggersmod.DEFAULT_TRIGGERS if t.name == "treasure_auto")
    wire = next(t for t in triggersmod.DEFAULT_TRIGGERS if not t.is_poll)

    watcher._say(poll, "triggers.log.on")
    key, fmt = said[-1]
    assert key == "triggers.log.on_poll", said
    assert fmt == {"name": "treasure_auto", "sec": poll.interval_sec}, fmt

    watcher._say(wire, "triggers.log.fire")
    key, fmt = said[-1]
    assert key == "triggers.log.fire", said        # a wire trigger is unchanged
    assert fmt["event"] == wire.signal()


def test_the_recipe_says_what_it_heard_and_not_only_what_it_pressed():
    """A listener that cannot say «heard N, did this» is «работает плохо», only silent."""
    src = (ROOT / "src" / "lastwar_bot" / "actions" / "auto_treasure.md").read_text(
        encoding="utf-8")
    assert "INTO ear" in src, "the run has to read the ear's own tally"
    assert "the ear so far: {ear}" in src, "…and say it in the log, every run"
    assert "nothing was sent this run ({ear})" in src, \
        "a quiet run is the one that most needs the counts on the line"


# ---------------------------------------------------------------------------
#
# «treasure_auto пытается забрать уже ИСЧЕЗНУВШИЙ подарок» (#1898).
#
# The errand hammered a chest that was not there: measured on a live client, 25 claims
# over 287 s, and the server answered every one of them with `E100123 treasure is null`.
# Nothing was wrong with the hearing or the timing that #1886 bought — what was wrong is
# that the ANSWER was thrown away. A code was read with `tonumber`, and two of the four
# codes this reply carries are not numbers, so the verdict arrived as `nil` and the retry
# ramp went on as if the server had said nothing at all. Silence again (#1884).
#
# What is pinned below is the whole of the way out: the codes are compared as TEXT, the
# two that mean «not there» and «not dug yet» are acted on, the ground can say the same
# thing without anybody being asked, and a chest struck out by any of them cannot come
# back through any of the three doors.


def _refused(lua, code, msg="", uuid=None) -> None:
    """The server's answer to the claim that has just gone out.

    It comes back under the same command name and names no chest, which is why the hook
    pins it on whichever target claimed last. `uuid` is here only to make a test able to
    say «this answer is about a DIFFERENT chest» — the wire never carries one.
    """
    if uuid is not None:
        lua.execute("DataCenter.__lw_treasure_auto.claim_uuid = '%d'" % uuid)
    lua.execute('SFSNetwork.HandleMessage("detect.event.claim.treasure", '
                '{errorCode=%s, errorMsg=%s})'
                % (_lua_str(str(code)), _lua_str(str(msg))))


def _why(lua, uuid=_UUID):
    """How a target ended, or `None` while it is still being worked."""
    for t in _targets(lua):
        if str(t.get("uuid")) == str(uuid):
            return t.get("why")
    return None


def test_the_server_saying_the_chest_is_not_there_ends_the_work_at_once():
    """`E100123 treasure is null` is a VERDICT, and it was being dropped (#1898).

    This is the live bug in one test: the chest is claimed, the server says there is no
    such chest, and before this fix the ramp went on claiming until the ttl — 25 sends
    over 287 s on the client that reported it. One answer is enough.
    """
    if not _needs_lua("the server saying the chest is gone"):
        return
    lua = _vm()
    _dug(lua)                                   # the dig feed: a claim-only target
    assert len(_claims(lua)) == 1, "the chest is claimed the second it is heard"

    _refused(lua, lua_actions.TREASURE_ERR_TREASURE_NULL, "treasure is null")
    report = _step(lua)

    assert _why(lua) == "gone", _targets(lua)
    assert "gone=1" in report, report
    assert "the chest is not there any more" in report, report
    assert _queued(lua) == 0, "nothing is left to work"

    #: …and no further send, however long the errand is left running
    before = len(_claims(lua))
    for _ in range(8):
        lua.execute("NOW = NOW + 16000")
        _step(lua)
    assert len(_claims(lua)) == before, _claims(lua)


def test_a_refusal_code_that_is_not_a_number_survives_the_journey():
    """The mechanism of #1898, pinned on its own so the fix cannot be undone by a tidy-up.

    `tonumber("E100123")` is `nil`. The hook used to store that, so the code the server
    took the trouble to send never reached the target it was about, and no line anywhere
    said a verdict had been discarded.
    """
    if not _needs_lua("a refusal code that is not a number"):
        return
    lua = _vm()
    _dug(lua)
    lua.execute('SFSNetwork.HandleMessage("detect.event.claim.treasure", '
                '{errorCode="E100123", errorMsg="treasure is null"})')
    stamped = lua.eval("(function() for _, t in ipairs("
                       "DataCenter.__lw_treasure_auto.targets) do return t.err end end)()")
    assert str(stamped) == "E100123", stamped


def test_the_two_numeric_verdicts_still_end_a_chest():
    """The codes that always worked go on working now they are compared as text."""
    if not _needs_lua("the numeric verdicts"):
        return
    for code, want in ((lua_actions.TREASURE_ERR_CLAIM_REPEAT, "already-had-it"),
                       (lua_actions.TREASURE_ERR_NOT_IN_ALLIANCE, "foreign")):
        lua = _vm()
        _dug(lua)
        _refused(lua, code)
        _step(lua)
        assert _why(lua) == want, (code, _targets(lua))


def test_the_server_saying_the_dig_is_not_over_takes_the_dug_stamp_off():
    """`detect_dig_err_01 treasure not complete` is the OPPOSITE verdict (#1898).

    The claim-first branch (#1886) is a guess made off `ownerUid`; this is the server
    correcting it. A chest that is there and not yet dug must go back on the march path
    rather than go on being claimed — and it must not be written off either.
    """
    if not _needs_lua("the server saying the dig is not over"):
        return
    lua = _vm()
    _announce(lua)                               # a chest with a tile: it CAN be marched at
    lua.execute("for _, t in ipairs(DataCenter.__lw_treasure_auto.targets) do "
                "t.dug, t.plan = NOW, 'claim' end")
    _step(lua)
    assert len(_claims(lua)) >= 1, "the claim-first branch was taken"

    _refused(lua, lua_actions.TREASURE_ERR_NOT_COMPLETE, "treasure not complete")
    _step(lua)

    target = _targets(lua)[0]
    assert not target.get("done"), target
    assert target.get("dug") is None, "the dug stamp was the thing the server denied"
    assert target.get("plan") == "march", target
    assert _queued(lua) == 1


def test_a_chest_the_game_said_is_gone_cannot_come_back_through_any_door():
    """Idempotence on all three doors at once (#1898).

    A finished chest is kept in the list for a ttl and then pruned, and every one of the
    three doors would hand it back as news afterwards — the dig feed repeats once per
    member, a share is posted by a person minutes late, and the ground goes on drawing the
    tile. The ledger is what they share.
    """
    if not _needs_lua("the ledger the three doors read"):
        return
    lua = _vm()
    _dug(lua)
    _refused(lua, lua_actions.TREASURE_ERR_TREASURE_NULL, "treasure is null")
    _step(lua)
    heard = int(lua.eval("DataCenter.__lw_treasure_auto.news"))

    #: the list is pruned, so `targets` can no longer answer for this chest
    lua.execute("NOW = NOW + %d" % ((lua_actions.TREASURE_TARGET_TTL_SEC + 1) * 1000))
    _step(lua)
    assert _spent(lua) == 0, "the prune has dropped it"

    _dug(lua)                                    # door 1: the dig feed says it again
    _announce(lua)                               # door 2: somebody shares it late
    assert int(lua.eval("DataCenter.__lw_treasure_auto.news")) == heard, _targets(lua)
    assert _queued(lua) == 0, _targets(lua)
    assert len(_claims(lua)) == 1, "and not one further claim leaves"


def test_the_look_does_not_re_open_a_chest_the_errand_has_finished_with():
    """Door three: the ground goes on drawing a chest this account has been paid for."""
    if not _needs_lua("the third door and the ledger"):
        return
    lua = _scan_vm(chests=(((_CHEST_AT), _OTHER_UUID, _SERVER, True),))
    _park_camera(lua, *_CHEST_AT)
    lua.execute(lua_actions.treasure_look_around())
    lua.execute(lua_actions.treasure_scan_harvest())
    assert _queued(lua) == 1, _targets(lua)

    _step(lua)                                   # …the claim leaves, and is refused
    _refused(lua, lua_actions.TREASURE_ERR_CLAIM_REPEAT)
    _step(lua)
    assert _why(lua, _OTHER_UUID) == "already-had-it", _targets(lua)
    lua.execute("NOW = NOW + %d" % ((lua_actions.TREASURE_TARGET_TTL_SEC + 1) * 1000))
    _step(lua)

    lua.execute(lua_actions.treasure_look_around())
    lua.execute(lua_actions.treasure_scan_harvest())
    report = str(lua.eval(lua_actions.treasure_scan_report()))
    assert "done-with=1" in report, report
    assert _queued(lua) == 0, _targets(lua)


def test_a_tile_the_client_holds_and_which_has_no_chest_writes_the_target_off():
    """The second way the game says «цели больше нет», and it needs nobody to ask (#1898).

    A chest waiting for a squad is never claimed, so the server never gets the chance to
    answer `E100123` about it. The ground can: the look already reads the box the camera
    is in, and a tracked tile the point manager ANSWERED about and which no longer carries
    a treasure is the map saying the same thing for free.
    """
    if not _needs_lua("a tile that no longer carries the chest"):
        return
    lua = _scan_vm(chests=(((_CHEST_AT), _OTHER_UUID, _SERVER, False),))
    _park_camera(lua, *_CHEST_AT)
    lua.execute(lua_actions.treasure_look_around())
    lua.execute(lua_actions.treasure_scan_harvest())
    assert _queued(lua) == 1, _targets(lua)

    #: somebody else finished it and the point is gone — the tile answers as plain ground
    lua.execute("CHESTS[%d] = nil" % (_CHEST_AT[1] * _MAP + _CHEST_AT[0] + 1))
    lua.execute(lua_actions.treasure_look_around())
    lua.execute(lua_actions.treasure_scan_harvest())

    assert _why(lua, _OTHER_UUID) == "tile-gone", _targets(lua)
    report = str(lua.eval(lua_actions.treasure_scan_report()))
    assert "vanished=1" in report, report
    assert _queued(lua) == 0
    assert _marched(lua) == [], "and no squad was ever spent on it"


def test_a_tile_the_client_cannot_answer_for_says_nothing_at_all():
    """The safety the whole reading rests on: an unloaded tile is not an answer.

    The point manager returns `nil` both for «there is nothing here» and for «I am not
    holding this ground», and reading the second as the first would throw away a live
    chest the camera merely walked away from. So the look records which tracked tiles it
    got an answer about, and only those may be struck out.
    """
    if not _needs_lua("an unloaded tile"):
        return
    lua = _scan_vm(chests=(((_CHEST_AT), _OTHER_UUID, _SERVER, False),))
    _park_camera(lua, *_CHEST_AT)
    lua.execute(lua_actions.treasure_look_around())
    lua.execute(lua_actions.treasure_scan_harvest())
    assert _queued(lua) == 1

    #: the camera walks away — the chest is still there, the client just cannot see it
    _park_camera(lua, 2, 2)
    lua.execute(lua_actions.treasure_look_around())
    lua.execute(lua_actions.treasure_scan_harvest())

    assert _why(lua, _OTHER_UUID) is None, _targets(lua)
    assert _queued(lua) == 1, "a chest out of view is not a chest that is gone"


def test_a_live_chest_is_still_claimed_the_instant_it_is_heard():
    """The thing #1898 must not break: «услышали — собрали» in a fraction of a second.

    Every verdict above is a way of STOPPING; the errand's whole worth is in how fast it
    starts. A chest heard already dug is claimed inside the hook that heard it, and no
    ledger, no code and no tile reading may stand in front of that.
    """
    if not _needs_lua("the fast path"):
        return
    lua = _vm()
    _dug(lua)
    assert len(_claims(lua)) == 1, _claims(lua)
    assert int(lua.eval("DataCenter.__lw_treasure_auto.hear_ms")) == 0, \
        "heard and claimed are the same instant"


# --- the day's reward allowance (#1965) -------------------------------------------

def _day_manager(lua, groups=((602, 10, True), (39, 9, False)), reset_in_ms=3600000):
    """The client's own books on the day's rewards, as `ActDetectTreasureDataManager`.

    Shaped after a live read on 2026-08-25, while the refusals were arriving: `dailyGot`
    is one counter per treasure GROUP and `CheckTreasureReachDailyLimit` answers per
    group — `602` full and `39` not, in the same read. The ids here are that shape and not
    that account's numbers, which is the point: what the test pins is one-full-one-not, not
    which group anybody happened to be digging.
    """
    got = ", ".join("[%d] = %d" % (g, n) for g, n, _ in groups)
    full = ", ".join("[%d] = %s" % (g, "true" if f else "false") for g, _, f in groups)
    lua.execute("""
DataCenter.ActDetectTreasureDataManager = {
  dailyGot = {%s},
  __full = {%s},
  activity_detect_dig_times_expire = NOW + %d,
  CheckTreasureReachDailyLimit = function(self, group)
    return self.__full[group] and true or false end,
}
""" % (got, full, int(reset_in_ms)))


def _day_state(lua) -> dict:
    return {k: v for k, v in lua.eval(
        "(function() local A = DataCenter.__lw_treasure_auto "
        "return {full = A.day_full and 1 or 0, held = A.t_held or 0, "
        "until_ms = A.day_until or 0, groups = A.day_groups or '', "
        "refused = A.limit_all or 0} end)()").items()}


def test_the_day_limit_holds_the_chest_instead_of_claiming_it_into_the_dark():
    """The live bug (#1965): «вы достигли дневного лимита вознаграждений», then nothing.

    The server answers a claim with `activity_sports_uitips_015 day times limit N`, which
    is the day's REWARDS being spent and says nothing whatever about the tile. Before this,
    the code fell through every verdict and the retry ramp went on claiming — the same
    silence #1898 was about, one code later.
    """
    if not _needs_lua("the day limit holds a chest"):
        return
    lua = _vm()
    _day_manager(lua)
    _dug(lua)
    assert len(_claims(lua)) == 1, "the chest is claimed the second it is heard"

    _refused(lua, lua_actions.TREASURE_ERR_DAY_LIMIT, "day times limit 2")
    report = _step(lua)

    assert _why(lua) is None, "the chest is HELD, not written off — it is still there"
    assert _queued(lua) == 1, _targets(lua)
    assert "held=1" in report, report
    assert int(_day_state(lua)["refused"]) == 1, _day_state(lua)

    #: …and not one further claim, however long the errand is left running
    before = len(_claims(lua))
    for _ in range(8):
        lua.execute("NOW = NOW + 16000")
        _step(lua)
    assert len(_claims(lua)) == before, _claims(lua)


def test_the_hold_lets_go_by_itself_when_the_game_says_the_day_turned_over():
    """No restart and no hand on the panel: the hold is measured against the GAME's stamp.

    `activity_detect_dig_times_expire` is the reset the client itself keeps — read live as
    the ordinary 02:00 UTC boundary — so the day turning over lifts every hold at once.
    """
    if not _needs_lua("the hold ends at the reset"):
        return
    lua = _vm()
    #: well inside the target's own ttl — this test is about the hold, not about a chest
    #: that sat on the list too long
    _day_manager(lua, reset_in_ms=600000)
    _dug(lua)
    _refused(lua, lua_actions.TREASURE_ERR_DAY_LIMIT, "day times limit 2")
    _step(lua)
    before = len(_claims(lua))

    #: the day turns over — and the client's counters go back with it
    lua.execute("NOW = NOW + 700000")
    _day_manager(lua, groups=((602, 0, False), (39, 0, False)))
    _step(lua)

    assert len(_claims(lua)) > before, "the chest is claimed again after the reset"
    assert _queued(lua) == 1, _targets(lua)


def test_one_group_being_full_does_not_stand_the_whole_errand_down():
    """The measurement that decided the design (#1965).

    The allowance is counted per treasure GROUP: read live, `602` was full and `39` was
    not, in the same breath as the refusals. So a refusal is a verdict on the chest it was
    sent for and never on the map — a chest of the group with room is still worth a squad.
    """
    if not _needs_lua("one group full"):
        return
    lua = _vm()
    _day_manager(lua, groups=((602, 10, True), (39, 9, False)))
    _dug(lua)
    _refused(lua, lua_actions.TREASURE_ERR_DAY_LIMIT, "day times limit 2")
    _step(lua)

    state = _day_state(lua)
    assert int(state["full"]) == 0, state
    assert "/full" in str(state["groups"]), state

    #: a second chest, of ANOTHER type, heard after the refusal — claimed exactly as
    #: before: the refusal shut the type it was about and nothing wider (#2092)
    before = len(_claims(lua))
    _dug(lua, uuid=_OTHER_UUID, cfg=25196)
    assert len(_claims(lua)) > before, "the group with room is still worked"


def test_every_counter_full_stops_the_sending_and_says_so_in_words():
    """And when there is genuinely nothing left to be paid for, the errand says it.

    A stalled queue that explains itself is the whole of requirement #1884: no chest is
    claimed, no squad is spent, and the line names the day rather than leaving a person to
    work it out from a report full of `waiting=`.
    """
    if not _needs_lua("every counter full"):
        return
    lua = _vm()
    _day_manager(lua, groups=((602, 10, True), (39, 10, True)))
    _announce(lua)                       # a chest with a TILE — a squad could go
    report = _step(lua)

    assert _marched(lua) == [], "no squad is spent on a chest that cannot be paid for"
    assert _claims(lua) == [], _claims(lua)
    assert "day-limit=[" in report, report
    assert "дневной лимит наград исчерпан" in report, report
    assert int(_day_state(lua)["full"]) == 1, _day_state(lua)


def test_a_client_that_counts_nothing_is_not_a_client_that_is_full():
    """`dailyGot` is filled by a REPLY, so a fresh client tracks no group at all (#1116).

    Reading that as «the day is spent» would stand the errand down on a client nobody had
    asked yet — the same fresh-client trap the treasure finder already carries.
    """
    if not _needs_lua("a client that counts nothing"):
        return
    lua = _vm()
    _day_manager(lua, groups=())
    _dug(lua)
    _step(lua)

    assert int(_day_state(lua)["full"]) == 0, _day_state(lua)
    assert len(_claims(lua)) >= 1, "nothing stands in the way of an ordinary claim"


def test_a_chest_the_day_is_holding_is_not_a_reason_to_wake_the_errand():
    """«Исключать такие сокровища из обхода» — the poll's half of it (#1965).

    A held chest is unfinished and stays unfinished until the reset, so counting it as work
    would turn the trigger into a clock that runs the recipe every few seconds to do
    nothing. The world clause is untouched: looking at the box the camera is in costs a
    hundredth of a second and finds chests for tomorrow.
    """
    if not _needs_lua("a held chest is not work"):
        return
    lua = _vm()
    _day_manager(lua, groups=((602, 10, True), (39, 10, True)), reset_in_ms=600000)
    _dug(lua)
    _refused(lua, lua_actions.TREASURE_ERR_DAY_LIMIT, "day times limit 2")
    _step(lua)

    assert _queued(lua) == 1, "the chest is still on the list — it is held, not spent"
    assert bool(lua.eval(lua_actions.treasure_auto_check())) is False, \
        "nothing to do until the day resets"

    #: …and the same chest is work again the moment the game says the day turned over
    lua.execute("NOW = NOW + 700000")
    _day_manager(lua, groups=((602, 0, False), (39, 0, False)))
    lua.execute("DataCenter.__lw_treasure_auto.tick()")
    assert bool(lua.eval(lua_actions.treasure_auto_check())) is True, "after the reset"


# --- the type is excluded, not the chest (#2092) -----------------------------------

def _types(lua) -> dict:
    """Which treasure types the errand is holding shut, and what shut them."""
    bad = lua.eval("DataCenter.__lw_treasure_auto.day_bad or {}")
    return {str(k): str(v) for k, v in (bad.items() if bad is not None else [])}


def test_the_refused_type_is_shut_for_the_day_and_not_only_the_refused_chest():
    """The repeat of the request (#2092): «исключить из слушателя этот тип сокровища».

    The allowance is counted per treasure TYPE, so a refusal is a verdict on the KIND of
    chest and never on the tile. Holding the one chest that was refused left every other
    chest of that kind — the ones already on the list, and every one the ears brought in
    afterwards — to be marched at, dug and claimed until each was refused in its own turn.
    """
    if not _needs_lua("the refused type is shut"):
        return
    lua = _vm()
    _day_manager(lua, groups=((25195, 10, False), (25196, 0, False)))
    _dug(lua, cfg=25195)
    assert len(_claims(lua)) == 1

    _refused(lua, lua_actions.TREASURE_ERR_DAY_LIMIT, "day times limit 2")
    _step(lua)
    assert _types(lua) == {"25195": "server"}, _types(lua)

    #: a SECOND chest of the same type, heard after the refusal — no claim, no squad
    before, marched = len(_claims(lua)), len(_marched(lua))
    _announce(lua, uuid=_OTHER_UUID, cfg=25195)
    report = _step(lua)

    assert len(_claims(lua)) == before, _claims(lua)
    assert len(_marched(lua)) == marched, "no squad is spent on a type that cannot pay"
    assert "day-types=[25195/server" in report, report
    assert _why(lua, _OTHER_UUID) is None, "it is held, not written off — it is still there"


def test_a_chest_of_another_type_is_worked_exactly_as_before():
    """The other half of the same measurement: the allowance is PER type.

    Shutting the whole errand on one refusal writes off a type that still has room — which
    is why the exclusion is keyed by the chest's own cfg id and by nothing wider.
    """
    if not _needs_lua("another type is still worked"):
        return
    lua = _vm()
    _day_manager(lua, groups=((25195, 10, False), (25196, 0, False)))
    _dug(lua, cfg=25195)
    _refused(lua, lua_actions.TREASURE_ERR_DAY_LIMIT, "day times limit 2")
    _step(lua)

    before = len(_claims(lua))
    _dug(lua, uuid=_OTHER_UUID, cfg=25196)
    assert len(_claims(lua)) > before, "the type with room is still claimed at once"


def test_the_type_the_client_says_is_spent_is_shut_before_any_refusal():
    """The client keeps the same books, so the first refusal need not be paid for twice.

    `CheckTreasureReachDailyLimit` is the game's own verdict per type; a chest of a type it
    calls spent is held the moment it is heard, with nothing sent at the server to find out.
    """
    if not _needs_lua("the client's own verdict shuts a type"):
        return
    lua = _vm()
    _day_manager(lua, groups=((25195, 10, True), (25196, 0, False)))
    _announce(lua, cfg=25195)
    report = _step(lua)

    assert _marched(lua) == [], "no squad on a type the client itself calls spent"
    assert _claims(lua) == [], _claims(lua)
    assert _types(lua) == {"25195": "client"}, _types(lua)
    assert "day-types=[25195/client" in report, report
    assert bool(lua.eval(lua_actions.treasure_auto_check())) is False, \
        "and it is not a reason to wake the errand either"


def test_the_shut_type_opens_again_when_the_game_says_the_day_turned_over():
    """Until the next reset, and the reset is the GAME's — never this machine's clock."""
    if not _needs_lua("the type opens after the reset"):
        return
    lua = _vm()
    _day_manager(lua, groups=((25195, 10, False), (25196, 0, False)),
                 reset_in_ms=600000)
    _dug(lua, cfg=25195)
    _refused(lua, lua_actions.TREASURE_ERR_DAY_LIMIT, "day times limit 2")
    _step(lua)
    before = len(_claims(lua))

    lua.execute("NOW = NOW + 700000")
    _day_manager(lua, groups=((25195, 0, False), (25196, 0, False)))
    _step(lua)

    assert _types(lua) == {}, _types(lua)
    assert len(_claims(lua)) > before, "the chest of that type is claimed again"


def _run() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:                            # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}: {exc}")
        else:
            print(f"  ok   {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
