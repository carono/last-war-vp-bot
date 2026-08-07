r"""The keyboard macros (#1283): five keys, two recipes, and where the target comes from.

What this file exists to hold:

* **the target is READ, never passed.** The whole ability rests on one fact about the
  client — by the time the squad-selection screen is up, it already holds `targetType`,
  `targetPoint`, `targetUuid` and `targetServerId` — so if a rewrite ever starts
  building a target in the panel, or asking the person for one, these tests fail;
* **keys 1..4 press the game's own launch button**, `OnCheckTime`, and CapsLock sends
  directly. The two are different on purpose (one has a screen to press, the other has
  none), and each is pinned here;
* **1 2 3 4 are never swallowed and CapsLock always is** — the one keyboard side effect
  the design accepts, written down so it cannot be widened by accident;
* **nothing fires unless the GAME is the foreground window.**

Offline: the catalogue, the recipes and the listener are all Tk-free and none of them
talks to the game here — the listener is driven with a fake runtime and a fake
foreground title.

    C:\Python312\python.exe tests\test_march_macros.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import game_buttons                                   # noqa: E402
import lua_actions                                    # noqa: E402
from lastwar_bot import script_engine                 # noqa: E402
from panel.runtime import hotkeys as hk               # noqa: E402

ACTIONS = _REPO / "src" / "lastwar_bot" / "actions"
SEND = ACTIONS / "march_selected_squad.md"
REPEAT = ACTIONS / "march_repeat_last.md"


# ---------------------------------------------------------------------------
# the recipes
# ---------------------------------------------------------------------------
def _parse(path: Path, variables=None):
    source, merged = script_engine.prepare_source(
        path.read_text(encoding="utf-8"), variables)
    return script_engine.parse_text(source), merged


def test_both_recipes_parse():
    for path in (SEND, REPEAT):
        statements, _ = _parse(path)
        assert statements, f"{path.name} parsed to nothing"


def test_both_recipes_have_a_russian_title():
    for path in (SEND, REPEAT):
        head = path.read_text(encoding="utf-8").splitlines()[:2]
        assert head[0].startswith("# "), path.name
        assert head[1].startswith("# ru:"), f"{path.name} has no # ru: title"


def test_the_squad_travels_as_an_argument_and_is_parked_by_the_recipe():
    """`TAP` carries no arguments, so the number the key named is parked in the VM."""
    source, merged = script_engine.prepare_source(
        SEND.read_text(encoding="utf-8"), {"squad": 3})
    assert merged["squad"] == 3
    assert "DataCenter.__lw_macro = {squad = 3}" in source
    # …and the default is squad 1, so a bare run is still a run.
    source, merged = script_engine.prepare_source(
        SEND.read_text(encoding="utf-8"), None)
    assert merged["squad"] == 1
    assert "DataCenter.__lw_macro = {squad = 1}" in source


def test_the_send_recipe_never_builds_a_target_of_its_own():
    """The target is read off the open screen — the recipe must not invent one.

    A recipe that started passing coordinates, a uuid or a target type would be a
    second answer to «what is being marched on», and the game's own screen is the first.
    """
    text = SEND.read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    for forbidden in ("ARGS uuid", "ARGS target", "ARGS point", "ARGS server",
                      "JUMP ", "SendCreateMarchMessage"):
        assert forbidden not in body, f"{forbidden} has no business in {SEND.name}"


def test_the_send_recipe_refuses_every_way_the_screen_can_fail():
    text = SEND.read_text(encoding="utf-8")
    assert "IF armed == 0" in text          # no screen open — nothing was chosen
    assert "IF armed == -1" in text         # no squad with that number
    assert "IF armed == -2" in text         # screen open, target unreadable
    assert "IF sent < 1" in text            # pressed and nothing went out


def test_the_repeat_recipe_takes_no_arguments():
    text = REPEAT.read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "ARGS " not in body, "«the same again» is the whole ability"
    assert "IF ready == 0" in text
    assert "IF ready == -1" in text
    assert "IF sent < 1" in text


def test_both_recipes_prove_themselves_by_the_march_count():
    """A press that returned cleanly proves the call ran, never that a march went out."""
    for path in (SEND, REPEAT):
        text = path.read_text(encoding="utf-8")
        assert "GetOwnerMarches" in text, path.name
        assert "INTO sent" in text, path.name


# ---------------------------------------------------------------------------
# the presses
# ---------------------------------------------------------------------------
def test_the_three_buttons_are_in_the_catalogue():
    for name in ("macro_arm", "macro_launch", "macro_repeat"):
        assert game_buttons.get(name) is not None, name
        assert name in game_buttons.names()


def test_the_arm_reads_the_screen_and_resolves_the_squad():
    lua = lua_actions.macro_arm()
    for field in ("targetType", "targetPoint", "targetUuid", "targetServerId",
                  "timeIndex", "autoBackHome"):
        assert field in lua, f"the arm does not read {field}"
    assert "UIFormationSelectListV2" in lua and "UIFormationSelectListNew" in lua
    assert "ArmyFormationList" in lua        # squad number -> formation uuid
    assert "tonumber(c.targetUuid)" not in lua, (
        "the target is the one value that must reach the send unchanged")
    assert "NeedTakeArmy" not in lua, (
        "called bare it answers true, and a send with needSoldier=true creates no "
        "march — #1283 lost an afternoon to it")


def test_the_launch_presses_the_games_own_button():
    lua = lua_actions.macro_launch()
    assert "OnCheckTime" in lua, "keys 1..4 replace the mouse, not the game's checks"
    assert "SetSelectFormationUuid" in lua
    assert "SendCreateMarchMessage" not in lua
    # …and it writes the march down BEFORE pressing: the screen closes itself.
    assert lua.index("__lw_macro_last") < lua.index("OnCheckTime")


def test_a_rally_is_never_repeated_by_a_plain_send():
    """The one target type the direct send is not proven for — and the client died on it.

    Both halves refuse: the reading the recipe gates on, and the press itself, because a
    press is reachable from a scenario nobody has read.
    """
    assert "IsRallyMarch" in lua_actions.macro_repeat_ready()
    assert "return -1" in lua_actions.macro_repeat_ready()
    assert "IsRallyMarch" in lua_actions.macro_repeat()


def test_neither_macro_ever_asks_for_soldiers():
    """`needSoldier=false` is what every proven send in the repo passes — see the arm."""
    assert ", false, m.server, nil)" in lua_actions.macro_repeat()
    assert "NeedTakeArmy" not in lua_actions.macro_repeat()


def test_the_repeat_sends_directly_and_opens_nothing():
    lua = lua_actions.macro_repeat()
    assert "SendCreateMarchMessage" in lua
    assert "DelayInvoke" in lua, "a cold send is created and dropped"
    assert "OpenWindow" not in lua and "GotoWorldPos" not in lua
    assert "__lw_macro_last" in lua


def test_the_armed_reading_tells_the_three_refusals_apart():
    expr = lua_actions.macro_armed()
    for verdict in ("return 0", "return -2", "return -1", "return 1"):
        assert verdict in expr


# ---------------------------------------------------------------------------
# the listener
# ---------------------------------------------------------------------------
class _FakeRuntime:
    def __init__(self) -> None:
        self.said: list[tuple] = []
        self.played: list[tuple] = []

    def say(self, tag, key, **fmt):
        self.said.append((tag, key, fmt))

    def play_async(self, name, args=None, *, tag="action"):
        self.played.append((name, args, tag))
        return True

    def dbg(self, _component="panel"):
        raise AssertionError("nothing here should need the debug log")


def _listener(rt, *, front=True):
    listener = hk.HotkeyListener(lambda: rt, title="Test Game Window")
    listener.game_in_front = lambda: front            # no Windows, no window
    return listener


def test_each_digit_plays_the_send_recipe_with_its_own_squad():
    for vk, squad in ((0x31, 1), (0x32, 2), (0x33, 3), (0x34, 4),
                      (0x61, 1), (0x64, 4)):
        rt = _FakeRuntime()
        _listener(rt)._press(vk)
        assert rt.played == [(hk.SEND_ACTION, {"squad": squad}, hk.TAG)], vk
        assert rt.said[0][1] == "log.macro.send"
        assert rt.said[0][2] == {"squad": squad}


def test_capslock_plays_the_repeat_recipe_with_no_arguments():
    rt = _FakeRuntime()
    _listener(rt)._press(0x14)
    assert rt.played == [(hk.REPEAT_ACTION, None, hk.TAG)]
    assert rt.said[0][1] == "log.macro.repeat"


def test_only_capslock_is_taken_away_from_the_game():
    listener = _listener(_FakeRuntime())
    assert listener._swallow(0x14) is True
    for vk in (0x31, 0x32, 0x33, 0x34, 0x61, 0x64, 0x41, 0x0D):
        assert listener._swallow(vk) is False, hex(vk)


def test_a_press_with_no_runtime_to_send_it_does_nothing():
    listener = hk.HotkeyListener(lambda: None, title="Test Game Window")
    listener.game_in_front = lambda: True
    listener._press(0x31)                     # must not raise


def test_the_window_title_decides_whether_the_game_is_in_front():
    listener = hk.HotkeyListener(lambda: None, title="Last War Test Window")
    saved = hk._foreground_title
    try:
        hk._foreground_title = lambda: "Last War Test Window"
        assert listener.game_in_front() is True
        hk._foreground_title = lambda: "Notepad"
        assert listener.game_in_front() is False
        hk._foreground_title = lambda: ""
        assert listener.game_in_front() is False
    finally:
        hk._foreground_title = saved


def test_a_listener_that_cannot_name_the_window_never_fires():
    """No title means no way to tell the game from a text editor — so it stays quiet."""
    listener = hk.HotkeyListener(lambda: None, title="")
    assert listener.game_in_front() is False


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:                    # noqa: BLE001
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
