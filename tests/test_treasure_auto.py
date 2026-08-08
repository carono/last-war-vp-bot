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
              plain: bool = False) -> None:
    """The chat post that announces a chest, with the blob under `key`.

    Field order and spacing are the client's own (`shareType` first, `x`/`y` in the
    middle) so the parser is exercised against the shape rather than against a tidy one.
    """
    blob = ('{"shareType":27,"y":%d,"x":%d,"uuid":%d,"worldType":0,"worldId":0,'
            '"sid":%d,"treasureId":"25195","oname":"1000000000000001"}'
            % (xy[1], xy[0], uuid, server))
    body = ('{msg="?", %s=%s}' % (key, _lua_str(blob)) if plain
            else '{__keys={"msg","%s"}, msg="?", %s=%s}' % (key, key, _lua_str(blob)))
    lua.execute('SFSNetwork.HandleMessage("world.treasure.share.chat", %s)' % body)


def _lua_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _dug(lua, uuid=_UUID, plain: bool = True) -> None:
    """The alliance's own feed: one of these per member who has finished digging.

    `plain` is the shape an INCOMING message really has — a bare Lua table, with no
    `__keys` for `SFSObject.GetKeys` to find. Proven live on 2026-08-08 by probing a real
    `push.detect.treasure.claim`: `KEYS[] PAIRS[operator=table uuid=…]`. The default is
    the real one; `plain=False` is the SFSObject shape an outgoing message has.
    """
    body = ('{uuid=%d, operator={}}' % uuid if plain
            else '{__keys={"uuid","operator"}, uuid=%d, operator={}}' % uuid)
    lua.execute('SFSNetwork.HandleMessage("push.detect.treasure.claim", %s)' % body)


def _reward(lua, up: bool = True) -> None:
    """The `UIGiftPackageRewardGet` the client raises on a claim the server PAID — the one
    observable difference between a paid claim and a refused one."""
    lua.execute("REWARD_UP = %s" % ("true" if up else "false"))


def _came_home(lua, slot: int = 1) -> None:
    """The squad's march is over: it has dug and come back, so the chest can be claimed."""
    lua.execute("for _, f in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) "
                "do if f.index == %d then f.__out = false end end" % slot)


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
    return int(lua.eval("#(DataCenter.__lw_treasure_auto.targets or {})"))


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
    report = _step(lua)
    assert _claims(lua) == []
    assert "waiting=1" in report and ":digging" in report, report


def test_the_alliance_feed_opens_the_claim_rather_than_closing_it():
    """`push.detect.treasure.claim` is one per member who FINISHED — every digger claims
    their own gift. Read as «somebody took it» the reward would be given away; read as
    «this chest is dug and payable», it is the gate."""
    if not _needs_lua("the feed is a gate, not a loss"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _dug(lua)
    report = _step(lua)
    claims = _claims(lua)
    assert len(claims) == 1, claims
    assert str(claims[0]["uuid"]) == str(_UUID), claims
    assert int(claims[0]["server"]) == _SERVER, claims
    assert "claimed=1" in report, report


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
    assert "still-marching" in report, report
    assert _queued(lua) == 1, "the chest must survive to be claimed when the squad lands"
    #: …and once it lands, the same clock claims it
    _came_home(lua, slot=1)
    _step(lua)
    assert len(_claims(lua)) == 1, _claims(lua)


def test_a_claim_is_proven_by_the_reward_window_and_not_by_the_send():
    """A refused claim returns exactly like a paid one, so the send cannot be the proof.
    The chest is spent when the reward window comes up shortly after — and stays queued
    until it does."""
    if not _needs_lua("payment is the reward window"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _dug(lua)
    report = _step(lua)
    assert "claim1" in report, report
    assert _queued(lua) == 1, "a sent claim is not a paid claim"
    _reward(lua)
    report = _step(lua)
    assert "paid=1" in report, report
    assert _queued(lua) == 0


def test_a_claim_that_never_pays_is_written_off_as_unconfirmed_not_as_claimed():
    """Four silent refusals are still four refusals. What must not happen is the chest
    being recorded as taken: «claimed» would read as a reward that was never had."""
    if not _needs_lua("an unconfirmed claim"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _dug(lua)
    for _ in range(6):
        _step(lua)
        lua.execute("NOW = NOW + 26000")      # past the retry cooldown
    assert len(_claims(lua)) == lua_actions.TREASURE_CLAIM_TRIES, _claims(lua)
    report = _step(lua)
    assert "claim-unconfirmed" in report or _queued(lua) == 0, report
    assert _queued(lua) == 0


def test_a_sent_claim_waits_its_retry_out_rather_than_going_every_tick():
    """A refusal says nothing, so the retry is on a clock. Four tries inside one minute
    would be four tries spent while the alliance is still digging."""
    if not _needs_lua("the retry is on a clock"):
        return
    lua = _vm()
    _announce(lua)
    _step(lua)
    _dug(lua)
    _step(lua)
    assert len(_claims(lua)) == 1
    report = _step(lua)
    assert len(_claims(lua)) == 1, "a second claim went out inside the cooldown"
    assert "claim-sent-waiting" in report, report
    lua.execute("NOW = NOW + %d" % ((lua_actions.TREASURE_CLAIM_RETRY_SEC + 1) * 1000))
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
    assert set(defaults) == {"squads", "grace", "ttl"}, defaults
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
    #: arm, the step, the retry after an army was fetched, and the pass that looks for
    #: the reward window a claim's payment shows up as.
    assert pressed == ["treasure_auto_arm", "treasure_auto_step", "treasure_auto_step",
                       "treasure_auto_step", "dismiss_treasure_reward"], pressed
    for name in pressed:
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
    fields = [item["f"] for item in feed["items"]]
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
