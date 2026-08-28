r"""The reward-popup ear, run in a real Lua VM — task #2027.

The ability is «catch a reward modal, close it, write down what was in it», and the whole
of it is two wrappers inside the client (`lua_actions.reward_watch_install`). This file
runs them in an actual Lua with a stand-in `UIManager` / `RewardManager`, because the one
thing that must never happen — a window closed that somebody was working in — cannot be
proven by reading the chunk.

What is pinned here:

  * the THREE GUARDS, each one on its own: an unknown window name is recorded and left
    open; a window that opens with no reward show behind it is not touched; a window that
    opens while a recipe holds one of its own is recorded as `held` and left open;
  * a whitelisted window opening right after a reward show IS closed, and the row says so;
  * the reward list itself is read off the show's arguments — «что дали»;
  * the whitelist contains only names the client actually has, and none of the screens
    the panel works inside (the mini-game, the squad screen, a shop, the HUD);
  * the ring is bounded, and what it drops is counted rather than silently lost;
  * the install is idempotent, and the recipe's own drain expression empties it.

    C:\Python312\python.exe tests\test_reward_popups.py
    python3 tests/test_reward_popups.py            # lupa is enough
"""
from __future__ import annotations

import json
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

#: The recipe that installs and drains the ear. Its Lua is read out of the file rather
#: than copied here, so the two cannot drift apart without this test noticing.
RECIPE = ROOT / "src" / "lastwar_bot" / "actions" / "collect_reward_popups.md"

#: The client's own table of window names, dumped live in #1148 and kept as research.
#: Every name the ear may close has to be in it — a whitelist naming a window the game
#: does not have is a line nobody can ever act on.
WINDOW_NAMES = ROOT / "docs" / "research" / "ui-open-data" / "ui_window_names.json"

#: Screens the panel WORKS INSIDE. None of them may ever be whitelisted: closing one is
#: the breakage this design is arranged around (#2021's mini-game holds its window for a
#: whole match, a march holds the squad screen, a purchase holds its dialog).
NEVER = (
    "UIMain", "UICommonShop", "UILWAllianceGift", "UIGGGoMain",
    "UIMoveCity", "UISettingSet", "UILWAlMain",
)

#: A round «now» in the game's own milliseconds, so the three-second span is arithmetic
#: rather than whatever the clock says.
NOW_MS = 1786_305_600_000

#: As much of the client as the two wrappers touch: a UI manager whose class carries
#: `OpenWindow`, a reward manager whose class carries the show-methods, and the clock.
_CLIENT = """
NOW = 0
UITimeManager = { Instance = { GetServerTime = function(self) return NOW end } }

OPENED, CLOSED = {}, {}

local uiclass = {}
uiclass.OpenWindow = function(self, name, ...)
  OPENED[#OPENED + 1] = tostring(name)
  return 'window:' .. tostring(name)
end
uiclass.GetWindow = function(self, name)
  return { Ctrl = { CloseSelf = function(ctrl)
    CLOSED[#CLOSED + 1] = tostring(name)
  end } }
end
UIManager = { Instance = setmetatable({}, {__index = uiclass}) }

SHOWN = {}
local rewardclass = {}
for _, m in ipairs({%(shows)s}) do
  rewardclass[m] = function(self, list) SHOWN[#SHOWN + 1] = m return m end
end
DataCenter = { RewardManager = setmetatable({}, {__index = rewardclass}) }
"""


def _vm():
    """A fresh Lua with the stand-in client and the ear installed."""
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    shows = ",".join(f"'{name}'" for name in lua_actions.REWARD_SHOWS)
    rt.execute(_CLIENT % {"shows": shows})
    rt.execute(f"NOW = {NOW_MS}")
    rt.execute(lua_actions.reward_watch_install())
    return rt


def _rows(rt) -> list:
    """Every row the ring holds right now, as `(kind, what)` pairs."""
    out = []
    ring = rt.eval("DataCenter.__lw_rewards.rows")
    for i in range(1, len(ring) + 1):
        stamp, kind, what = str(ring[i]).split("|", 2)
        out.append((kind, what))
    return out


def _drain_expr() -> str:
    """The recipe's own drain, read out of `collect_reward_popups.md`."""
    from lastwar_bot import script_engine
    for stmt in script_engine.parse_file(RECIPE):
        for inner in getattr(stmt, "then_block", []) or []:
            expr = getattr(inner, "expr", "")
            if "B.rows={}" in expr:
                return expr
    raise AssertionError("the recipe no longer drains the ring")


def test_whitelist_is_real_and_narrow() -> None:
    """Every name exists in the client's table, and no working screen is on the list."""
    groups = json.loads(WINDOW_NAMES.read_text(encoding="utf-8"))
    known = {name for names in groups.values() for name in names}
    for name in lua_actions.REWARD_WINDOWS:
        assert name in known, f"{name} is not a window this client has"
        assert "Reward" in name or "Gift" in name, f"{name} is not a reward window"
    for name in NEVER:
        assert name not in lua_actions.REWARD_WINDOWS, f"{name} must never be closed"
    assert len(set(lua_actions.REWARD_WINDOWS)) == len(lua_actions.REWARD_WINDOWS)
    print("ok  whitelist: %d real reward windows, no working screen among them"
          % len(lua_actions.REWARD_WINDOWS))


def test_a_reward_popup_is_closed_and_written_down() -> None:
    """A show, then its window: closed, and the row says what was given."""
    rt = _vm()
    rt.execute("DataCenter.RewardManager:ShowCommonReward("
               "{{id=101,num=2},{itemId=205,count=7}})")
    rt.execute("UIManager.Instance:OpenWindow('UIGiftPackageRewardGet')")
    rows = _rows(rt)
    assert rows[0][0] == "reward", rows
    assert rows[0][1] == "ShowCommonReward|101x2,205x7", rows
    assert ("closed", "UIGiftPackageRewardGet") in rows, rows
    closed = rt.eval("CLOSED")
    assert len(closed) == 1 and closed[1] == "UIGiftPackageRewardGet"
    # …and the game's own call still happened: the wrapper is an ear, not a door.
    assert rt.eval("OPENED")[1] == "UIGiftPackageRewardGet"
    assert rt.eval("SHOWN")[1] == "ShowCommonReward"
    print("ok  a reward popup is closed, and the reward is written down")


def test_the_wrapper_gives_back_what_the_game_returned() -> None:
    """The ear sits in front of EVERY window the client opens — it may change nothing.

    Not a nicety: `OpenWindow`'s result is used by the game's own callers, and a wrapper
    that swallowed it (or that spelled `unpack` in a way this client's Lua does not have)
    would break windows that have nothing to do with rewards.
    """
    rt = _vm()
    got = rt.eval("UIManager.Instance:OpenWindow('UISettingSet')")
    assert str(got) == "window:UISettingSet", got
    assert len(rt.eval("CLOSED")) == 0
    print("ok  the wrapper hands back exactly what the game returned")


def test_an_unknown_window_is_reported_never_closed() -> None:
    """A reward-shaped window nobody has vouched for is a row, not a press."""
    rt = _vm()
    rt.execute("DataCenter.RewardManager:ShowGiftReward({{id=9,num=1}})")
    rt.execute("UIManager.Instance:OpenWindow('UIActGiftBoxRewardNew')")
    assert ("unknown", "UIActGiftBoxRewardNew") in _rows(rt), _rows(rt)
    assert len(rt.eval("CLOSED")) == 0
    print("ok  an unknown reward window is reported and left open")


def test_no_show_no_close() -> None:
    """A whitelisted window that opens on its own is somebody's press, not a reward."""
    rt = _vm()
    rt.execute("UIManager.Instance:OpenWindow('UIGiftPackageRewardGet')")
    assert _rows(rt) == [], _rows(rt)
    assert len(rt.eval("CLOSED")) == 0
    # …and the same window three seconds after a show is out of the span as well.
    rt.execute("DataCenter.RewardManager:ShowCommonReward({{id=1,num=1}})")
    rt.execute(f"NOW = {NOW_MS + lua_actions.REWARD_WINDOW_MS + 1}")
    rt.execute("UIManager.Instance:OpenWindow('UIGiftPackageRewardGet')")
    assert len(rt.eval("CLOSED")) == 0
    print("ok  a window with no reward behind it is never touched")


def test_a_hold_stops_every_close() -> None:
    """A recipe holding a window of its own is obeyed even for a whitelisted name."""
    rt = _vm()
    rt.execute(lua_actions.reward_watch_hold(10))
    rt.execute("DataCenter.RewardManager:ShowCommonReward({{id=1,num=1}})")
    rt.execute("UIManager.Instance:OpenWindow('UIGiftPackageRewardGet')")
    assert ("held", "UIGiftPackageRewardGet") in _rows(rt), _rows(rt)
    assert len(rt.eval("CLOSED")) == 0
    # …and letting go puts it back exactly as it was.
    rt.execute(lua_actions.reward_watch_hold(0))
    rt.execute("DataCenter.RewardManager:ShowCommonReward({{id=1,num=1}})")
    rt.execute("UIManager.Instance:OpenWindow('UIGiftPackageRewardGet')")
    assert len(rt.eval("CLOSED")) == 1
    print("ok  a held window is left alone, and the hold lifts cleanly")


def test_a_hold_nobody_lifts_expires() -> None:
    """A recipe that arms something and returns cannot deafen the ear for ever."""
    rt = _vm()
    rt.execute(lua_actions.reward_watch_hold(10))
    rt.execute(f"NOW = {NOW_MS + 10 * 60_000 + 1}")
    rt.execute("DataCenter.RewardManager:ShowCommonReward({{id=1,num=1}})")
    rt.execute("UIManager.Instance:OpenWindow('UIGiftPackageRewardGet')")
    assert len(rt.eval("CLOSED")) == 1, "the hold outlived its own deadline"
    print("ok  a hold nobody lifted expires on its own")


def test_the_ring_is_bounded_and_says_what_it_dropped() -> None:
    """A client nobody drains loses rows — and counts them instead of hiding them."""
    rt = _vm()
    over = lua_actions.REWARD_RING + 5
    rt.execute("for i = 1, %d do "
               "DataCenter.RewardManager:ShowSingleReward({{id=i,num=1}}) end" % over)
    assert len(_rows(rt)) == lua_actions.REWARD_RING
    assert int(rt.eval("DataCenter.__lw_rewards.lost")) == over - lua_actions.REWARD_RING
    print("ok  the ring is bounded and the loss is counted")


def test_install_is_idempotent_and_the_recipe_drains() -> None:
    """A second install changes nothing; the recipe's own expression empties the ring."""
    rt = _vm()
    rt.execute(lua_actions.reward_watch_install())
    rt.execute("DataCenter.RewardManager:ShowCommonReward({{id=1,num=3}})")
    rt.execute("UIManager.Instance:OpenWindow('UIGiftPackageRewardGet')")
    assert len(rt.eval("SHOWN")) == 1, "the show ran twice — a wrapper wrapped a wrapper"
    blob = str(rt.eval(_drain_expr()))
    assert "reward|ShowCommonReward|1x3" in blob, blob
    assert "closed|UIGiftPackageRewardGet" in blob, blob
    assert _rows(rt) == [], "the drain left rows behind"
    print("ok  a second install is a no-op, and the recipe's drain empties the ring")


def main() -> int:
    if lupa is None:
        print("SKIP no lupa in this interpreter")
        return 0
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
    print("\nall reward-popup checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
