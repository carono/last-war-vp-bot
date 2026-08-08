r"""«Звезда в приоритете, UR только если звёзд нет» — run in a real Lua (task #1292).

The whole priority is three Lua expressions over the alliance's own task table, and this
file runs them in an actual VM with a stand-in dispatch manager — no game, no daemon, no
panel:

  * `assist_next_secret_task()` — WHICH task a press takes. A ready star beats every
    ready UR whatever their levels, and a UR is only taken while there are more helps
    left than there are stars still worth waiting for;
  * `secret_task_assists_pending()` — HOW MANY presses `xall` makes. Ready stars up to
    the budget, then URs into whatever is left after one help is set aside per ripening
    star. Five helps and two ripening stars buy three URs and keep two in hand;
  * `secret_task_assist_scan()` — what the recipe SAYS. The same walk, parked as plain
    numbers, so «жду звезду 7 (готова через 12 мин)» is the game's own arithmetic and not
    the panel's guess.

The bound on the waiting is the other half and is tested as hard as the priority is: a
star is worth a held help only while it can ripen before its own `actEndTime`, before the
daily reset the budget rides on (02:00 UTC) and inside the parked `star_wait_min`. One
that fails any of the three is counted as «late», holds nothing back and is said out loud
— #1272 measured one star per two hundred alliance tasks against thirty-four finished
URs, so a wait with no floor under it is how all five helps are thrown away instead.

    C:\Python312\python.exe tests\test_assist_star_priority.py
    python3 tests/test_assist_star_priority.py            # lupa is enough
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


#: A round «now» well inside a day, so the 02:00 UTC boundary the scan computes is a
#: known number rather than whatever the clock happens to say. 2026-08-08 12:00 UTC —
#: fourteen hours after that day's reset and ten hours before the next one.
NOW_MS = 1786_305_600_000
HOUR = 3600_000

#: As much of the client as the three expressions touch: the dispatch manager with its
#: task table and its daily counter, the server clock, and the two calls a press makes.
_CLIENT = """
DataCenter = { ActDispatchTaskDataManager = {
  allianceTask = {},
  _today = 0,
  _cap = 5,
  GetTodayAssistNum = function(self) return self._today end,
  GetDispatchSetting = function(self, key) return self._cap end,
  DeleteAllianceTasks = function(self, uuid)
    for i, v in ipairs(self.allianceTask) do
      if v.uuid == uuid then table.remove(self.allianceTask, i) return end
    end
  end,
} }
NOW = 0
UITimeManager = { Instance = { GetServerTime = function(self) return NOW end } }
SENT = {}
SFSNetwork = { SendMessage = function(msg, uuid, server)
  SENT[#SENT + 1] = {uuid = uuid, server = server}
end }
MsgDefines = { DispatchAssist = "hero.dispatch.assist" }
LOGGED = {}
CS = { UnityEngine = { Debug = { LogError = function(line)
  LOGGED[#LOGGED + 1] = line
end } } }
"""


def _task(lua, uuid, *, level=6, star=False, colour=5, done=None, expires=None,
          rewarded=0):
    """One row of `allianceTask`, with the config row the rank is read off.

    `done` is when the dispatch finishes (default: an hour ago, i.e. helpable now) and
    `expires` its `actEndTime` (default: this day's reset, which is where the game puts
    almost all of them). Both are absolute game-clock milliseconds, like the real ones.
    """
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


def _vm(*, today=0, cap=5, level_min=0, wait_min=240):
    """A Lua VM holding one dispatch manager, the clock, and the parked rule."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    lua.execute("NOW = %d" % NOW_MS)
    m = lua.eval("DataCenter.ActDispatchTaskDataManager")
    m._today, m._cap = today, cap
    lua.execute(lua_actions.secret_task_assist_rule(level_min, wait_min))
    return lua, m


def _pending(lua) -> int:
    """What `xall` reads between rounds: how many presses the rule still allows."""
    return int(lua.eval(lua_actions.secret_task_assists_pending()))


def _press(lua) -> "dict | None":
    """One press, and what it sent — `None` when it sent nothing."""
    before = int(lua.eval("#SENT"))
    lua.execute(lua_actions.assist_next_secret_task())
    if int(lua.eval("#SENT")) == before:
        return None
    sent = lua.eval("SENT[#SENT]")
    return {"uuid": int(sent.uuid), "server": int(sent.server)}


def _scan(lua) -> dict:
    """The recipe's own reading: the numbers the scan parks for its `READ_LUA`s."""
    lua.execute(lua_actions.secret_task_assist_scan())
    return {name: int(lua.eval(lua_actions.secret_task_star_field(name)))
            for name in ("ready", "ur", "pending", "eta", "level", "late", "left")}


def _needs_lua(name: str) -> bool:
    if lupa is None:
        print(f"       (skipped {name}: no lupa here — pip install lupa)")
        return False
    return True


# -- the priority itself ------------------------------------------------------------

def test_a_ready_star_is_taken_before_a_higher_level_ur():
    """The rule the task is named after. The old rank was `lvl*2+spec`, so a level-7 UR
    outranked a level-6 star and the star — one alliance task in two hundred — was gone
    by the time anybody noticed."""
    if not _needs_lua("a star beats a higher UR"):
        return
    lua, _m = _vm()
    _task(lua, 1001, level=7, star=False, colour=5)      # the best UR there is
    _task(lua, 1002, level=6, star=True, colour=4)       # a lesser star
    assert _press(lua)["uuid"] == 1002, "the UR ate the star's help"


def test_the_best_star_goes_first_when_there_are_several():
    """Among stars the level still decides — «сначала лучшие» never stopped applying."""
    if not _needs_lua("the best star first"):
        return
    lua, _m = _vm()
    _task(lua, 1001, level=4, star=True)
    _task(lua, 1002, level=8, star=True)
    _task(lua, 1003, level=6, star=True)
    assert _press(lua)["uuid"] == 1002


def test_with_no_star_at_all_the_ur_is_taken():
    """«Звёзд нет — довольствуемся UR». The priority is an order, not a prohibition:
    thirty-four finished URs sitting unspent all day is the other way to waste five
    helps."""
    if not _needs_lua("no star, take the UR"):
        return
    lua, _m = _vm()
    _task(lua, 2001, level=5, star=False, colour=5)
    _task(lua, 2002, level=7, star=False, colour=5)
    assert _press(lua)["uuid"] == 2002
    assert _pending(lua) == 1, "the second UR was not counted after the first went"


def test_a_plain_task_is_never_helped():
    """Below UR the daily plan pays nothing, so neither does the rule."""
    if not _needs_lua("a plain task is skipped"):
        return
    lua, _m = _vm()
    _task(lua, 3001, level=9, star=False, colour=4)      # high level, wrong rank
    assert _pending(lua) == 0
    assert _press(lua) is None


# -- the reserve: a ripening star holds a help back ----------------------------------

def test_a_ripening_star_holds_one_help_back():
    """«Квота не тратится на UR, пока есть шанс на звезду» — one help per ripening star,
    and the rest of the budget still goes on URs."""
    if not _needs_lua("a ripening star holds a help"):
        return
    lua, _m = _vm(today=0, cap=5)                        # five helps in hand
    _task(lua, 4001, level=7, star=True, done=NOW_MS + HOUR)   # ripens in an hour
    for uuid in range(4100, 4110):                       # ten URs ready right now
        _task(lua, uuid, level=6, star=False, colour=5)
    assert _pending(lua) == 4, "the reserve for the ripening star was spent on URs"


def test_a_star_for_every_help_leaves_nothing_for_the_ur():
    """Five ripening stars and five helps: the URs wait, and the recipe says so rather
    than quietly doing nothing."""
    if not _needs_lua("the whole budget is reserved"):
        return
    lua, _m = _vm(today=0, cap=5, wait_min=0)            # patience bounded by the day
    for i, uuid in enumerate(range(5001, 5006)):
        _task(lua, uuid, level=7, star=True, done=NOW_MS + (i + 1) * HOUR)
    _task(lua, 5100, level=7, star=False, colour=5)
    assert _pending(lua) == 0
    assert _press(lua) is None, "a UR was helped out of the stars' reserve"
    scan = _scan(lua)
    assert scan["pending"] == 5 and scan["ur"] == 1 and scan["ready"] == 0


def test_a_ready_star_is_still_helped_while_another_ripens():
    """The reserve holds URs back, never the stars themselves."""
    if not _needs_lua("a ready star outruns the reserve"):
        return
    lua, _m = _vm(today=4, cap=5)                        # one help left
    _task(lua, 6001, level=7, star=True, done=NOW_MS + HOUR)   # …and a star coming
    _task(lua, 6002, level=5, star=True)                       # …and one ready now
    assert _pending(lua) == 1
    assert _press(lua)["uuid"] == 6002


# -- the floor under the waiting ------------------------------------------------------

def test_a_star_that_ripens_after_its_own_expiry_holds_nothing():
    """A dispatch that finishes after the tile is gone can never be helped, so waiting
    for it spends the day for nothing."""
    if not _needs_lua("a star that outlives its tile"):
        return
    lua, _m = _vm()
    _task(lua, 7001, level=7, star=True,
          done=NOW_MS + 5 * HOUR, expires=NOW_MS + 2 * HOUR)
    _task(lua, 7100, level=6, star=False, colour=5)
    scan = _scan(lua)
    assert scan["pending"] == 0 and scan["late"] == 1
    assert _press(lua)["uuid"] == 7100, "the UR was held back for a doomed star"


def test_a_star_that_ripens_after_the_daily_reset_holds_nothing():
    """The budget rides on the 02:00 UTC reset: a star maturing after it is a star for
    TOMORROW's five, and today's would be thrown away waiting."""
    if not _needs_lua("a star past the daily reset"):
        return
    lua, _m = _vm(wait_min=0)                            # no bound of our own at all
    # `now` is 12:00 UTC; the reset is ten hours away, this star is eleven.
    _task(lua, 8001, level=7, star=True, done=NOW_MS + 11 * HOUR,
          expires=NOW_MS + 20 * HOUR)
    _task(lua, 8100, level=6, star=False, colour=5)
    scan = _scan(lua)
    assert scan["pending"] == 0 and scan["late"] == 1
    assert _press(lua)["uuid"] == 8100


def test_a_star_beyond_the_wait_bound_holds_nothing():
    """…and the operator's own bound, which is the one that can be shortened when the
    day is nearly over."""
    if not _needs_lua("a star beyond the wait bound"):
        return
    lua, _m = _vm(wait_min=60)                           # an hour of patience
    _task(lua, 9001, level=7, star=True, done=NOW_MS + 3 * HOUR)
    _task(lua, 9100, level=6, star=False, colour=5)
    scan = _scan(lua)
    assert scan["pending"] == 0 and scan["late"] == 1
    assert _press(lua)["uuid"] == 9100
    # …and with the bound lifted the very same star is worth waiting for.
    lua2, _m2 = _vm(wait_min=0)
    _task(lua2, 9001, level=7, star=True, done=NOW_MS + 3 * HOUR)
    _task(lua2, 9100, level=6, star=False, colour=5)
    assert _scan(lua2)["pending"] == 1


def test_a_star_below_the_minimum_level_is_not_waited_for():
    """The level rule bites on the waiting as well as on the pressing — a star nobody
    would help is not a star worth holding a help for."""
    if not _needs_lua("a star below the level bound"):
        return
    lua, _m = _vm(level_min=7)
    _task(lua, 9201, level=3, star=True, done=NOW_MS + HOUR)
    _task(lua, 9202, level=8, star=False, colour=5)
    scan = _scan(lua)
    assert scan["pending"] == 0 and scan["late"] == 0, scan
    assert _press(lua)["uuid"] == 9202


# -- what the recipe says -------------------------------------------------------------

def test_the_scan_says_how_long_the_star_is_and_how_far_off():
    """«жду звезду N (готова через M)» is the game's arithmetic: the nearest ripening
    star's level and its countdown in whole minutes, rounded UP so a star forty seconds
    away is never «через 0 минут» (#1227)."""
    if not _needs_lua("the scan carries the countdown"):
        return
    lua, _m = _vm()
    _task(lua, 9301, level=7, star=True, done=NOW_MS + 90 * 60_000)     # 90 min
    _task(lua, 9302, level=5, star=True, done=NOW_MS + 40_000)          # 40 s
    scan = _scan(lua)
    assert scan["pending"] == 2
    assert scan["eta"] == 1, "40 s rounded down to «ready now»"
    assert scan["level"] == 5, "the countdown named a star other than the nearest"


def test_the_scan_reads_as_empty_before_it_has_run():
    """A recipe whose scan never happened must read «nothing ready, nothing coming»
    rather than fail on a nil index — the `READ_LUA`s are what the branches test."""
    if not _needs_lua("an unscanned manager reads as zero"):
        return
    lua, _m = _vm()
    for name in ("ready", "ur", "pending", "level", "late", "left"):
        assert int(lua.eval(lua_actions.secret_task_star_field(name))) == 0


def test_the_scan_and_the_press_never_disagree():
    """One walk answers both questions, so the number the log shows is the number of
    presses that follow it."""
    if not _needs_lua("the scan matches the presses"):
        return
    lua, _m = _vm(today=1, cap=5)                        # four helps left
    _task(lua, 9401, level=7, star=True)                 # ready star
    _task(lua, 9402, level=6, star=True, done=NOW_MS + HOUR)   # …and one coming
    for uuid in range(9410, 9415):                       # five ready URs
        _task(lua, uuid, level=6, star=False, colour=5)
    scan = _scan(lua)
    assert (scan["ready"], scan["pending"], scan["ur"], scan["left"]) == (1, 1, 5, 4)
    #   1 star now + (4 left - 1 spent on it - 1 reserved) = 3 presses
    assert _pending(lua) == 3
    taken = []
    for _round in range(3):
        got = _press(lua)
        assert got is not None
        taken.append(got["uuid"])
        lua.eval("DataCenter.ActDispatchTaskDataManager")._today += 1
    assert taken[0] == 9401, "the star did not go first"
    assert _pending(lua) == 0
    assert _press(lua) is None, "the reserve was spent after the budget ran out"


def test_a_rewarded_or_expired_task_is_invisible_to_all_of_it():
    """The two states the client's own gate drops: already paid out, and off the map."""
    if not _needs_lua("rewarded and expired are dropped"):
        return
    lua, _m = _vm()
    _task(lua, 9501, level=8, star=True, rewarded=1)
    _task(lua, 9502, level=8, star=True, expires=NOW_MS - HOUR)
    scan = _scan(lua)
    assert (scan["ready"], scan["pending"], scan["late"]) == (0, 0, 0), scan
    assert _press(lua) is None


def _main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
        else:
            print(f"  ok   {name}")
    print("FAILED" if failed else "all good")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
