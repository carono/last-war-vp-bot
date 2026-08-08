r"""The star sprint — the last seconds of a star's countdown, in a real Lua (task #1294).

Live acceptance of the star priority (#1292) measured the hole this closes: the day's
only ripe star was gone from the alliance list in UNDER TWO MINUTES, taken by
alliancemates, and `star_ready` never read non-zero on a single five-minute poll. The
reserve worked — a help was being held for it — and the help was still not spent.

The fix does not poll faster. The task carries its own `completionTime`, so the moment it
matures is known hours ahead; the panel sleeps until a few seconds before and then plays
`actions/assist_star_sprint.md`, which presses until the SERVER answers. This file runs
the Lua half of that in an actual VM with a stand-in dispatch manager — no game, no
daemon, no panel:

  * `secret_task_assist_sprint_arm()` — WHICH task is armed. A ready star if there is
    one, otherwise the nearest ripening one, and never a UR;
  * `secret_task_assist_sprint_pending()` — whether to press AGAIN. The gate `xall`
    re-reads: a target, a budget, no confirmation yet, no terminal refusal, and the
    window still open;
  * `secret_task_assist_sprint_press()` — the press, which must leave its target armed;
  * `secret_task_assist_sprint_verdict()` — which of the three things happened, and how
    many presses it took, which is the measurement the change is judged by.

    C:\Python312\python.exe tests\test_assist_star_sprint.py
    python3 tests/test_assist_star_sprint.py            # lupa is enough
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


#: The same round «now» the priority test uses — 2026-08-08 12:00 UTC, well inside a day.
NOW_MS = 1786_305_600_000
HOUR = 3600_000

#: As much of the client as the sprint touches. `UIUtil.ShowTipsId` is real here because
#: the sprint reads the server's refusal through it: the hook the arming installs is a
#: pass-through wrapper, and a test that stubbed it out would not be testing the loop's
#: only way of hearing «somebody else got there first».
_CLIENT = """
DataCenter = { ActDispatchTaskDataManager = {
  allianceTask = {},
  _today = 0,
  _cap = 5,
  GetTodayAssistNum = function(self) return self._today end,
  GetDispatchSetting = function(self, key) return self._cap end,
  DeleteAllianceTasks = function(self, uuid) end,
} }
NOW = 0
UITimeManager = { Instance = { GetServerTime = function(self) return NOW end } }
SENT = {}
SFSNetwork = { SendMessage = function(msg, uuid, server)
  SENT[#SENT + 1] = {uuid = uuid, server = server}
end }
MsgDefines = { DispatchAssist = "hero.dispatch.assist" }
TIPS = {}
UIUtil = { ShowTipsId = function(id) TIPS[#TIPS + 1] = id end }
LOGGED = {}
CS = { UnityEngine = { Debug = { LogError = function(line)
  LOGGED[#LOGGED + 1] = line
end } } }
"""


def _task(lua, uuid, *, level=7, star=True, colour=5, done=None, expires=None,
          rewarded=0):
    """One row of `allianceTask`. `done` in the future = still counting down."""
    lua.execute("""
      local m = DataCenter.ActDispatchTaskDataManager
      m.allianceTask[#m.allianceTask + 1] = {
        uuid = %d, targetServer = 300, completionTime = %d, actEndTime = %d,
        rewarded = %d,
        cfg = { _lvl = %d, _spec = %d, _colour = %d,
                getValue = function(self, key)
                  if key == "level" then return self._lvl end
                  if key == "is_special" then return self._spec end
                  return self._colour
                end },
      }
    """ % (uuid,
           NOW_MS - HOUR if done is None else done,
           NOW_MS + 10 * HOUR if expires is None else expires,
           rewarded, level, 1 if star else 0, colour))


def _vm(*, today=0, cap=5, level_min=0, window_sec=20):
    """A Lua VM with the dispatch manager, the clock, the rule and the sprint window."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    lua.execute("NOW = %d" % NOW_MS)
    m = lua.eval("DataCenter.ActDispatchTaskDataManager")
    m._today, m._cap = today, cap
    lua.execute(lua_actions.secret_task_assist_rule(level_min, 0))
    lua.execute("DataCenter.ActDispatchTaskDataManager.__lw_assist_window_ms = %d"
                % (window_sec * 1000))
    return lua, m


def _arm(lua) -> "dict | None":
    """Arm the sprint; return the target it chose, or None when it found nothing."""
    lua.execute(lua_actions.secret_task_assist_sprint_arm())
    target = lua.eval("DataCenter.ActDispatchTaskDataManager.__lw_assist_target")
    if target is None:
        return None
    return {"uuid": int(target.uuid), "server": int(target.server),
            "level": int(target.level)}


def _pending(lua) -> int:
    """The gate `xall` re-reads between presses: 1 = press this one again."""
    return int(lua.eval(lua_actions.secret_task_assist_sprint_pending()))


def _press(lua) -> int:
    """One press. Returns how many frames have left the client in total."""
    lua.execute(lua_actions.secret_task_assist_sprint_press())
    return int(lua.eval("#SENT"))


def _spam(lua, rounds=10) -> int:
    """Press while the gate allows, up to a cap — what `TAP … xall` does."""
    n = 0
    while n < rounds and _pending(lua):
        _press(lua)
        n += 1
    return n


def _verdict(lua) -> dict:
    """Close the sprint and read back the line it says."""
    lua.execute(lua_actions.secret_task_assist_sprint_verdict())
    line = lua.eval("LOGGED[#LOGGED]")
    out = {}
    for pair in str(line).split()[1:]:
        key, _, value = pair.partition("=")
        out[key] = value
    return out


def _tip(lua, key) -> None:
    """The server refusing, through the game's own tip door."""
    lua.execute("UIUtil.ShowTipsId(%r)" % key)


def _needs_lua(name: str) -> bool:
    if lupa is None:
        print(f"       (skipped {name}: no lupa here — pip install lupa)")
        return False
    return True


# -- what gets armed ------------------------------------------------------------------

def test_the_nearest_ripening_star_is_armed_before_it_matures():
    """The whole point: the sprint is played EARLY, so at arming time the star it came
    for has not finished yet. A recipe that could only arm ready tasks would arrive at
    the same moment the five-minute poll does."""
    if not _needs_lua("a ripening star is armed"):
        return
    lua, _m = _vm()
    _task(lua, 1001, level=7, star=True, done=NOW_MS + 90 * 1000)   # 90 s out
    _task(lua, 1002, level=7, star=True, done=NOW_MS + 3 * 1000)    # 3 s out — this one
    assert _arm(lua)["uuid"] == 1002


def test_a_ready_star_outranks_a_ripening_one():
    """One already matured beats one that is about to: it can be taken NOW, and every
    second it waits is a second an alliancemate is pressing at it."""
    if not _needs_lua("a ready star wins"):
        return
    lua, _m = _vm()
    _task(lua, 2001, level=6, star=True, done=NOW_MS + 2 * 1000)
    _task(lua, 2002, level=6, star=True, done=NOW_MS - 1000)        # ripe
    assert _arm(lua)["uuid"] == 2002


def test_a_ur_is_never_sprinted_at():
    """A UR is not worth a spam loop — thirty-four of them sat unhelped in one live
    reading, and the ordinary recipe spends those at its own pace."""
    if not _needs_lua("no UR in a sprint"):
        return
    lua, _m = _vm()
    _task(lua, 3001, level=9, star=False, colour=5)
    _task(lua, 3002, level=9, star=False, colour=5, done=NOW_MS + 2000)
    assert _arm(lua) is None
    assert _pending(lua) == 0


def test_a_spent_day_arms_nothing():
    """Five helps gone is five helps gone; a sprint on a spent budget would press
    against a gate the server has already closed."""
    if not _needs_lua("a spent day arms nothing"):
        return
    lua, _m = _vm(today=5)
    _task(lua, 4001, star=True, done=NOW_MS + 2000)
    assert _arm(lua) is None


def test_a_star_below_the_minimum_level_is_not_armed():
    """«Минимальный уровень» is one rule read in one place — the sprint obeys the same
    number the ordinary order does."""
    if not _needs_lua("the level rule holds"):
        return
    lua, _m = _vm(level_min=7)
    _task(lua, 5001, level=6, star=True, done=NOW_MS + 2000)
    assert _arm(lua) is None


# -- the loop -------------------------------------------------------------------------

def test_the_target_survives_its_own_press_so_it_can_be_pressed_again():
    """The opposite of the ordinary help, which drops its task before sending so `xall`
    moves on. Here pressing the SAME task again is the entire point."""
    if not _needs_lua("the target stays armed"):
        return
    lua, _m = _vm()
    _task(lua, 6001, star=True, done=NOW_MS + 5 * 1000)
    _arm(lua)
    _press(lua)
    _press(lua)
    assert int(lua.eval("#SENT")) == 2
    assert lua.eval("DataCenter.ActDispatchTaskDataManager.__lw_assist_target") is not None
    assert _pending(lua) == 1, "the loop stopped though the server had said nothing"


def test_the_loop_stops_the_moment_the_server_confirms():
    """`todayAssistNum` moving is the only honest «it worked» — it reaches the client on
    the reply's success branch and nowhere else."""
    if not _needs_lua("a confirmation ends it"):
        return
    lua, m = _vm()
    _task(lua, 7001, star=True, done=NOW_MS - 1000)
    _arm(lua)
    _press(lua)
    m._today = 1                      # the reply landed
    assert _pending(lua) == 0
    assert _verdict(lua)["how"] == "taken"


def test_a_lost_race_is_terminal_and_says_so():
    """«Спасибо, но задача уже решена с помощью других лиц» IS the lost race, and it must
    stop the loop: pressing on is asking a question the server has answered."""
    if not _needs_lua("a lost race stops it"):
        return
    lua, _m = _vm()
    _task(lua, 8001, star=True, done=NOW_MS - 1000)
    _arm(lua)
    _press(lua)
    _tip(lua, "dispatch_des028")
    assert _pending(lua) == 0
    verdict = _verdict(lua)
    assert verdict["how"] == "gone"
    assert verdict["tip"] == "dispatch_des028"


def test_an_unknown_tip_leaves_the_loop_pressing():
    """A tip we have not met must not be read as a refusal — that is the rule the
    robbery's own list follows, and «ещё не готово» would be exactly such a tip."""
    if not _needs_lua("an unknown tip is not terminal"):
        return
    lua, _m = _vm()
    _task(lua, 9001, star=True, done=NOW_MS + 3000)
    _arm(lua)
    _press(lua)
    _tip(lua, "dispatch_des999")
    assert _pending(lua) == 1


def test_the_window_stops_a_star_that_never_matures():
    """The bound the clock cannot give: a mate who cancelled the task leaves a countdown
    that never ends, and without this the spam would run out the button's cap every
    single time."""
    if not _needs_lua("the window closes"):
        return
    lua, _m = _vm(window_sec=10)
    _task(lua, 10001, star=True, done=NOW_MS + 5 * 60 * 1000)
    _arm(lua)
    assert _pending(lua) == 1
    lua.execute("NOW = %d" % (NOW_MS + 11 * 1000))          # the window has closed
    assert _pending(lua) == 0
    assert _verdict(lua)["how"] == "unanswered"


def test_the_verdict_counts_the_presses_it_took():
    """The measurement the change is judged by: how many attempts a star costs. A sprint
    that presses forty times to lose every race is a different answer from one that
    presses three to win."""
    if not _needs_lua("the presses are counted"):
        return
    lua, m = _vm()
    _task(lua, 11001, star=True, done=NOW_MS + 2000)
    _arm(lua)
    _press(lua)
    _press(lua)
    _press(lua)
    m._today = 1
    verdict = _verdict(lua)
    assert verdict["presses"] == "3", verdict
    assert verdict["lvl"] == "7", verdict


def test_the_arming_resets_the_tip_left_by_the_last_sprint():
    """Two stars in one day: the second must not read the first one's refusal and give up
    without pressing at all."""
    if not _needs_lua("the tip mailbox is cleared"):
        return
    lua, _m = _vm()
    _task(lua, 12001, star=True, done=NOW_MS + 2000)
    _arm(lua)
    _tip(lua, "dispatch_des028")
    assert _pending(lua) == 0
    _arm(lua)                                   # the next star, later in the day
    assert _pending(lua) == 1


def test_a_press_before_the_star_matures_is_still_sent():
    """Pressing early is free — the reply's error branch raises a tip and never touches
    the counter — and being already pressing is the only way to be first."""
    if not _needs_lua("an early press is sent"):
        return
    lua, _m = _vm()
    _task(lua, 13001, star=True, done=NOW_MS + 9 * 1000)
    _arm(lua)
    assert _spam(lua, rounds=4) == 4
    assert int(lua.eval("#SENT")) == 4
    sent = lua.eval("SENT[1]")
    assert int(sent.uuid) == 13001 and int(sent.server) == 300


# -- what the scan hands the scheduler -------------------------------------------------

def test_the_scan_says_the_countdown_in_seconds():
    """Minutes are what a person reads; the schedule needs seconds. «Через 2 мин» is not
    a number anything can aim at when the star lives two minutes."""
    if not _needs_lua("the countdown is in seconds"):
        return
    lua, _m = _vm()
    _task(lua, 14001, level=7, star=True, done=NOW_MS + 95 * 1000)
    lua.execute(lua_actions.secret_task_assist_scan())
    assert int(lua.eval(lua_actions.secret_task_star_field("eta_sec"))) == 95
    assert int(lua.eval(lua_actions.secret_task_star_field("eta"))) == 2


def test_the_countdown_is_minus_one_when_no_star_is_coming():
    """The same «nothing to wait for» the minutes say, so the panel schedules nothing
    rather than an appointment at the epoch."""
    if not _needs_lua("no star, no countdown"):
        return
    lua, _m = _vm()
    _task(lua, 15001, star=False, colour=5)
    lua.execute(lua_actions.secret_task_assist_scan())
    assert int(lua.eval(lua_actions.secret_task_star_field("eta_sec"))) == -1


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            bad += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
