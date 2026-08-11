r"""How LATE the gift is taken — the acceptance criterion, measured (task #1318).

«Как только есть информация о сокровище, она должна быть строго зафиксирована, таймер
работать с наивысшим приоритетом, отслеживать время завершения раскопки и в ту же
микросекунду забирать сокровище… ВСЕ сокровища всегда забраны в первую секунду.»

That is a NUMBER, so this file measures it instead of describing it. Both models are run
against the same chest, the same clock and the same Lua — the errand's real chunks, in a
real Lua interpreter — and the only difference between them is WHO ASKS and HOW OFTEN:

  * **the panel** — what the errand had before. `panel/triggers.py` polls every 10 s with a
    20 s cooldown behind it, so the claim can only leave on one of those visits, and a dig
    that finishes a moment after one waits out the whole of the next gap;
  * **the watch** — what it has now. `A.tick` lives in the game VM, the game's own timer
    calls it five times a second, and a dig deadline that is near is pinned with a one-shot
    scheduled AT that millisecond (`TREASURE_DUE_ARM_MS`).

The measurement is the errand's own `lag` — the milliseconds between the chest becoming
takeable and the first claim for it leaving — because that is the number the panel puts on
screen and the one a live session will be judged by. Nothing here mocks it: the value comes
out of the same code the client runs.

WHAT THIS FILE IS NOT. It is not a live confirmation. The clock is simulated, so what it
measures is the DESIGN's latency — the cadence at which the question gets asked — and not
the client's answer time on the day. The live number is `lag=`/`worst=` on «Командный
пункт» and in the errand's own report; this pins the part that can be got wrong offline,
which is every part that was.

    C:\Python312\python.exe tests\test_treasure_timing.py
    python3 tests/test_treasure_timing.py            # lupa is enough
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
_SERVER = 100
_HOME_TILE = 500500          # the base: (499, 500)
_CHEST = (505, 502)

#: How long the squad walks and then digs, in the simulated game's own milliseconds. Both
#: models see exactly the same march.
_WALK_MS = 40_000
_DIG_MS = 60_000

#: The panel's own cadence, straight out of `panel/triggers.py`: it looks every ten seconds
#: and then sits out a twenty-second cooldown, so between two claims there can be thirty.
_POLL_SEC = 10
_COOLDOWN_SEC = 20

#: What the player asked for, in milliseconds. «В первую секунду.»
_CRITERION_MS = 1000

_CLIENT = """
SAID = {}
MARCHED = {}
CLAIMED = {}
TIMERS = {}
CS = {UnityEngine = {Debug = {LogError = function(s) SAID[#SAID+1] = tostring(s) end},
                     Vector2Int = function(x, y) return {x = x, y = y} end}}
NOW = 1785322473766
DataCenter = {}
SFSNetwork = {
  SendMessage = function(cmd, a, b, ...)
    if cmd == "detect.event.claim.treasure" then
      CLAIMED[#CLAIMED+1] = {uuid = a, server = b, at = NOW}
    end
    return "sent" end,
  HandleMessage = function(cmd, obj, ...) return "handled" end,
}
SFSObject = {GetKeys = function(o) return o.__keys end,
             GetData = function(o, k) return o[k] end}
MsgDefines = {DetectEventClaimTreasure = "detect.event.claim.treasure",
              GetFormationSoldier = "formation.get.soldier"}
REWARD_UP = false
UIWindowNames = {UIGiftPackageRewardGet = "UIGiftPackageRewardGet"}
UIManager = {Instance = {IsWindowOpen = function(self, name) return REWARD_UP end}}
-- THE GAME'S OWN TIMER, as much of it as the errand uses: a delay in SECONDS and a
-- callback. The driver below fires them when the simulated clock reaches them, which is
-- what makes the one-shot pinned to a dig deadline measurable rather than merely written.
TimerManager = {GetInstance = function()
  return {DelayInvoke = function(self, fn, delay)
    TIMERS[#TIMERS+1] = {at = NOW + math.floor((tonumber(delay) or 0) * 1000), fn = fn}
  end} end}
MarchUtil = {
  SendCreateMarchMessage = function(formation, target, pid, uuid, a, b, c, server, d)
    MARCHED[#MARCHED+1] = {formation = formation, target = target, pid = pid}
    -- The squad leaves: it walks, then it digs, and the dig carries its own deadline —
    -- `MarchStatus.TREASURE_DIGGING` with an `endTime` (docs/research/squad-state.md).
    MARCH = {formation = formation, left = NOW}
  end,
}
SceneUtils = {
  TilePosToIndex = function(v) return v.y * 1000 + v.x + 1 end,
  IndexToTilePos = function(i) return {x = (i - 1) %% 1000, y = math.floor((i - 1) / 1000)} end,
  GetIsInWorld = function() return true end,
}
UITimeManager = {Instance = {GetServerTime = function(self) return NOW end}}
ChatInterface = {getServerTime = function() return math.floor(NOW / 1000) end}
LuaEntry = {Player = {uid = "1000000000000001", allianceId = 1, serverId = %d,
                      world_main_pos = %d}}
MARCH = nil
WALK, DIG = %d, %d
DataCenter.ArmyFormationDataManager = {ArmyFormationList = {
  {index = 1, uuid = 2000000000000000001, totalSoldierNum = 3000}}}
DataCenter.WorldMarchDataManager = {
  -- The march as the client answers for it: absent until the squad leaves, MOVING while it
  -- walks, TREASURE_DIGGING with the dig's deadline while it digs, and gone once the dig
  -- is over. `tostring()` on the status gives `NAME: value`, which is the shape the live
  -- client's enums come back as.
  GetOwnerFormationMarch = function(self, uid, uuid, ally)
    if MARCH == nil then return nil end
    local walked = NOW - MARCH.left
    if walked < WALK then
      return {status = "MOVING: 1", endTime = MARCH.left + WALK}
    elseif walked < WALK + DIG then
      return {status = "TREASURE_DIGGING: 19", endTime = MARCH.left + WALK + DIG}
    end
    return nil
  end,
}
""" % (_SERVER, _HOME_TILE, _WALK_MS, _DIG_MS)


def _needs_lua(what: str) -> bool:
    if lupa is None:
        print(f"  skip {what}: lupa is not installed")
        return False
    return True


def _vm():
    """A Lua VM with the client stand-in, the hook installed and the errand armed."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    lua.execute(lua_actions.treasure_watch_install())
    lua.execute("DataCenter.__lw_treasure_squads = {1}")
    lua.execute(lua_actions.treasure_auto_arm_parked())
    return lua


def _announce(lua) -> None:
    """The chat post that announces the chest — the errand's first door."""
    blob = ('{"shareType":27,"y":%d,"x":%d,"uuid":%d,"worldType":0,"worldId":0,'
            '"sid":%d,"treasureId":"25195","oname":"1000000000000001"}'
            % (_CHEST[1], _CHEST[0], _UUID, _SERVER))
    lua.execute('SFSNetwork.HandleMessage("world.treasure.share.chat", '
                '{__keys={"msg","attachmentId"}, msg="?", attachmentId=%s})'
                % ("'" + blob + "'"))


def _advance(lua, ms: int) -> None:
    """Move the game's clock, firing every timer that falls due on the way.

    Firing them IN ORDER matters: the errand schedules a one-shot at a dig's deadline, and
    a driver that jumped the clock and then fired it would measure its own laziness.
    """
    target = int(lua.eval("NOW")) + int(ms)
    while True:
        due = lua.eval("(function() local best = nil for i, t in ipairs(TIMERS) do "
                       "if best == nil or t.at < TIMERS[best].at then best = i end end "
                       "if best == nil then return nil end return TIMERS[best].at end)()")
        if due is None or int(due) > target:
            break
        lua.execute("NOW = %d" % int(due))
        lua.execute("(function() local best = nil for i, t in ipairs(TIMERS) do "
                    "if best == nil or t.at < TIMERS[best].at then best = i end end "
                    "if best == nil then return end "
                    "local t = table.remove(TIMERS, best) pcall(t.fn) end)()")
    lua.execute("NOW = %d" % target)


def _lag(lua):
    """The errand's own measurement: takeable → first claim, in milliseconds."""
    value = lua.eval("DataCenter.__lw_treasure_auto.lag_ms")
    return None if value is None else int(value)


def _claims(lua) -> list:
    return [dict(c.items()) for c in lua.eval("CLAIMED").values()]


def _watch(lua) -> None:
    """The watch, as the game runs it: `A.tick` on the game's own timer."""
    lua.execute(lua_actions.treasure_reaper_start())


def _run(lua, seconds: int, press_every: "int | None") -> None:
    """Let `seconds` of game time pass, pressing the panel's step every `press_every`."""
    step = lua_actions.treasure_auto_step()
    left = seconds
    grain = press_every if press_every else 1
    while left > 0:
        chunk = min(grain, left)
        _advance(lua, chunk * 1000)
        if press_every:
            lua.execute(step)
        left -= chunk


def _one_chest(watch: bool, press_every: "int | None", dig_ms: int = _DIG_MS):
    """March at one chest and take it. Returns `(lag_ms, claims)`.

    `dig_ms` is how long the dig lasts, and it is the knob the sweep below turns: WHERE in
    the panel's poll gap the deadline falls is the whole of that model's luck, so one
    sample of it says nothing. A dig one second longer lands one second further into the
    gap.
    """
    lua = _vm()
    lua.execute("DIG = %d" % int(dig_ms))
    _announce(lua)
    lua.execute(lua_actions.treasure_auto_step())        # the squad goes out
    if watch:
        _watch(lua)
    #: the whole walk and the whole dig, and a minute after it
    _run(lua, (_WALK_MS + int(dig_ms)) // 1000 + 60, press_every)
    return _lag(lua), _claims(lua)


# ---------------------------------------------------------------------------
def test_the_panel_alone_takes_a_chest_late_and_the_watch_takes_it_at_once():
    """THE MEASUREMENT, both models, one chest — and the whole point of the task.

    The panel-only model is the errand as it was: the claim can only leave when a poll
    comes round, so the lag is however much of that gap the dig happened to land in. The
    watch is the errand as it is: a one-shot pinned to the dig's own deadline, checked five
    times a second besides.
    """
    if not _needs_lua("the two models, measured"):
        return
    panel_lag, panel_claims = _one_chest(watch=False,
                                         press_every=_POLL_SEC + _COOLDOWN_SEC)
    watch_lag, watch_claims = _one_chest(watch=True, press_every=None)
    print("        panel only : first claim %s ms after the dig ended (%d claims)"
          % (panel_lag, len(panel_claims)))
    print("        with watch : first claim %s ms after the dig ended (%d claims)"
          % (watch_lag, len(watch_claims)))
    assert panel_lag is not None and watch_lag is not None, (panel_lag, watch_lag)
    #: the panel alone is late by a whole poll gap — that is the bug, stated as a number
    assert panel_lag > _CRITERION_MS, (
        "the panel-only model was expected to miss the first second; if this fails the "
        "cadence in `panel/triggers.py` changed and the comparison is no longer honest")
    #: …and the watch is inside the first second, which is the criterion
    assert watch_lag <= _CRITERION_MS, watch_lag
    assert watch_lag < panel_lag, (watch_lag, panel_lag)


def test_every_chest_is_taken_in_the_first_second_wherever_its_dig_ends():
    """«ВСЕ сокровища ВСЕГДА забраны в первую секунду» — so one sample is not an answer.

    Where a dig's deadline falls inside the panel's poll gap is pure luck, and a single
    measurement of a lucky one would read as a working errand. This sweeps the deadline
    across the WHOLE gap, one second at a time, and reports the worst of each model. The
    worst is the number the criterion is about: an errand that takes nine chests instantly
    and the tenth half a minute late has not met it.
    """
    if not _needs_lua("the whole poll gap, swept"):
        return
    gap = _POLL_SEC + _COOLDOWN_SEC
    panel, watch = [], []
    for phase in range(gap):
        dig = _DIG_MS + phase * 1000
        panel.append(_one_chest(watch=False, press_every=gap, dig_ms=dig)[0])
        watch.append(_one_chest(watch=True, press_every=None, dig_ms=dig)[0])
    assert all(v is not None for v in panel + watch), (panel, watch)
    print("        panel only : worst %d ms · mean %d ms · best %d ms  (over %d chests)"
          % (max(panel), sum(panel) // len(panel), min(panel), len(panel)))
    print("        with watch : worst %d ms · mean %d ms · best %d ms  (over %d chests)"
          % (max(watch), sum(watch) // len(watch), min(watch), len(watch)))
    #: THE CRITERION, on every one of them and not on the average
    assert max(watch) <= _CRITERION_MS, max(watch)
    #: …and the model it replaced misses it on most of the gap, which is why it was replaced
    assert max(panel) > _CRITERION_MS, max(panel)
    assert sum(1 for v in panel if v > _CRITERION_MS) > len(panel) // 2, panel


def test_the_claim_leaves_in_the_same_frame_the_dig_ends():
    """«В ту же микросекунду.» The one-shot is the difference between «within a fifth of a
    second» and «at the millisecond», and it is what a near deadline is pinned with."""
    if not _needs_lua("the one-shot at the deadline"):
        return
    lag, claims = _one_chest(watch=True, press_every=None)
    assert claims, "no claim was ever sent"
    #: the watch's own period is a fifth of a second; the one-shot is what makes it exact
    assert lag == 0, ("the claim did not leave in the frame the dig ended", lag)


def test_the_watch_keeps_trying_until_the_chest_is_paid():
    """A refused claim is silent, so «it went out» is not «it arrived». The watch tries
    again on a ramp until the reward window comes up — and stops the moment it does."""
    if not _needs_lua("the retry ramp"):
        return
    lua = _vm()
    _announce(lua)
    lua.execute(lua_actions.treasure_auto_step())
    _watch(lua)
    _run(lua, (_WALK_MS + _DIG_MS) // 1000 + 120, None)
    tried = len(_claims(lua))
    assert tried >= 5, ("the watch gave up on a chest that was still on the map", tried)
    #: …and the server pays: the reward window comes up and the chest is spent
    lua.execute("REWARD_UP = true")
    _advance(lua, 1000)
    after = len(_claims(lua))
    _run(lua, 120, None)
    assert len(_claims(lua)) == after, "the watch went on claiming a chest it had been paid"
    assert int(lua.eval("DataCenter.__lw_treasure_auto.paid_all or 0")) == 1


def test_the_watch_stops_itself_when_there_is_nothing_left_to_work():
    """A self-rescheduling timer inside somebody else's game has to end. The panel's poll
    re-arms it; a panel that has been closed leaves nothing running."""
    if not _needs_lua("the watch ends"):
        return
    lua = _vm()
    _watch(lua)
    assert lua.eval("DataCenter.__lw_treasure_auto.reap_on") is True
    _run(lua, lua_actions.TREASURE_REAP_STOP_SEC + 60, None)
    assert lua.eval("DataCenter.__lw_treasure_auto.reap_on") is False
    #: …and it comes back on the next arm, with the queue untouched
    _watch(lua)
    assert lua.eval("DataCenter.__lw_treasure_auto.reap_on") is True


def _main() -> int:
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
    raise SystemExit(_main())
