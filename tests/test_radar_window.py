#!/usr/bin/env python3
"""One pass per refresh window — the radar's own pacing (#2390).

The operator's rule, in their words: «Радар обновляется раз в 4 часа, один раз выполнили
задания и все, ждем обновления». Before this the errand ran on a clock and worked the same
board over and over inside one window — measured on a live panel at 1344 s of the client
over 44 minutes, 51 % of the wall clock, beside a chain that yields to everything.

Offline against the real Lua: the stamp is the game's own `detectInfo.nextRefreshTime`,
read out of the client's copy with no request; a finished cycle parks it; a cycle that was
cut short parks nothing and the window is worked again.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "tools" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lua_actions                                          # noqa: E402

try:
    import lupa                                             # noqa: E402
except ImportError:                                         # pragma: no cover
    lupa = None

_CLIENT = """
CS = {UnityEngine = {Debug = {LogError = function() end}}}
DataCenter = {RadarCenterDataManager = {detectInfo = {nextRefreshTime = 1000000, eventNum = 0}}}
"""


def _vm():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    return lua


def _skip(what: str) -> bool:
    if lupa is None:
        print("  skip %s — no lupa" % what)
        return True
    return False


def test_the_window_is_worked_once_and_then_left_alone():
    if _skip("the refresh window"):
        return
    lua = _vm()
    assert int(lua.eval(lua_actions.radar_next_refresh())) == 1000000
    assert int(lua.eval(lua_actions.radar_window_done())) == 0, "never worked yet"

    lua.execute(lua_actions.radar_window_mark())
    assert int(lua.eval(lua_actions.radar_window_done())) == 1, \
        "a finished cycle must keep the errand off the client for this window"

    #: …and the game moving its own stamp is what opens the next pass — no clock
    lua.execute("DataCenter.RadarCenterDataManager.detectInfo.nextRefreshTime = 2000000")
    assert int(lua.eval(lua_actions.radar_window_done())) == 0, \
        "the refresh happened: the board is worth a pass again"


def test_a_cycle_that_was_cut_short_leaves_the_window_open():
    """The mark is the LAST step of the recipe, so a crash, a lost lease or a client that
    went away parks nothing — and the next tick works the window rather than skipping it."""
    if _skip("an interrupted cycle"):
        return
    lua = _vm()
    assert int(lua.eval(lua_actions.radar_window_done())) == 0
    #: a run that got as far as reading the board and no further
    lua.eval(lua_actions.radar_next_refresh())
    assert int(lua.eval(lua_actions.radar_window_done())) == 0, \
        "nothing was parked, so nothing may be skipped"


def test_a_board_nobody_can_read_is_never_skipped():
    """0 is «the client could not answer», and the cautious reading of that is «work»."""
    if _skip("an unreadable board"):
        return
    lua = _vm()
    lua.execute("DataCenter.RadarCenterDataManager = nil")
    assert int(lua.eval(lua_actions.radar_next_refresh())) == 0
    assert int(lua.eval(lua_actions.radar_window_done())) == 0


def test_the_recipe_gates_on_the_window_and_marks_it_at_the_end():
    """The wiring, not the Lua: the gate is the FIRST thing the recipe does and the mark is
    after the last press — a run that stops early must not claim the window."""
    text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "radar_full_cycle.md").read_text(encoding="utf-8")
    assert "INTO window_done" in text and "IF window_done == 1" in text, text[:400]
    assert "TAP radar_mark_window" in text
    gate = text.index("INTO window_done")
    for press in ("TAP radar_read_board", "TAP radar_claim", "TAP radar_march"):
        if press in text:
            assert gate < text.index(press), "%s runs before the gate" % press
    assert text.index("TAP radar_mark_window") > text.rindex("TAP radar_claim"), \
        "the window is marked after the work, never before it"


def _run() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  ok   %s" % name)
            except AssertionError as exc:
                fails += 1
                print("  FAIL %s: %s" % (name, exc))
    total = len([n for n in globals() if n.startswith("test_")])
    print("\n%d/%d passed" % (total - fails, total))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_run())
