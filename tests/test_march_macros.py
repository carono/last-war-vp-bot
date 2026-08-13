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

Nothing here talks to the game — the listener is driven with a fake runtime and a fake
foreground title — but it is not Tk-free, whatever this paragraph said when it was
written: `from panel.runtime import hotkeys` runs `panel/runtime/__init__.py`, which
imports the host, which imports the settings binder, which imports tkinter. So the file
is `ui` and it says so; run under an interpreter without Tk it did not skip, it failed
on `ModuleNotFoundError: tkinter` (#1284).

    C:\Python312\python.exe tests\test_march_macros.py
"""
from __future__ import annotations

TIER = "ui"        # Tk (not a display) — see tools/run_tests.py

import sys
import time
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
    assert "DataCenter.__lw_macro = {squad = 3, stale = 180}" in source
    # …and the defaults are squad 1 and three minutes, so a bare run is still a run.
    source, merged = script_engine.prepare_source(
        SEND.read_text(encoding="utf-8"), None)
    assert merged["squad"] == 1
    assert merged["stale"] == 180
    assert "DataCenter.__lw_macro = {squad = 1, stale = 180}" in source


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


def test_the_send_recipe_refuses_every_way_a_target_can_fail():
    text = SEND.read_text(encoding="utf-8")
    assert "IF sent_ok == 0" in text        # nothing clicked and no screen open
    assert "IF sent_ok == -1" in text       # no squad with that number
    assert "IF sent_ok == -2" in text       # screen open, target unreadable
    assert "IF sent_ok == -3" in text       # the screen's own launch raised
    assert "IF sent_ok == -4" in text       # the click is older than `stale`
    assert "IF sent_ok == -5" in text       # a kind the macro does not march on
    assert "IF sent_ok == -6" in text       # a rally-only monster
    assert "IF sent_ok == -7" in text       # no longer on the world map
    assert "IF sent_ok == -8" in text       # another account clicked it
    assert "IF sent < 1" in text            # pressed and nothing went out


def test_neither_recipe_asks_the_game_anything_before_it_presses():
    """#1290: a round trip in front of a key press is the latency the person feels.

    Both recipes park what they need, press ONCE, and read the answer back afterwards.
    A `READ_LUA` that lands before the `TAP` is a question standing between the key and
    the march — which is exactly the shape this task was sent to remove.
    """
    for path in (SEND, REPEAT):
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
        kinds = [l.split()[0].upper() for l in lines]
        assert "TAP" in kinds, path.name
        first_tap = kinds.index("TAP")
        assert "READ_LUA" not in kinds[:first_tap], (
            f"{path.name} asks the game something before it presses")
        assert kinds.count("TAP") == 1, f"{path.name} presses more than once"


def test_the_repeat_recipe_takes_no_arguments():
    text = REPEAT.read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "ARGS " not in body, "«the same again» is the whole ability"
    assert "IF ready == 0" in text
    assert "IF ready == -1" in text


def test_neither_key_stands_and_counts_after_it_has_sent():
    """The tail was the whole of «CapsLock reacts after three seconds» (#1328).

    Measured live before the fix: `TAP=+0.08 ready=+0.14 … end=+3.42` — everything past
    +0.2 s was the march-count poll, and the run holds the game claim for all of it, so
    the next key waited behind it too. Both keys press and end now; the verdict on a send
    is read by the NEXT press off the count this one wrote down.
    """
    for path in (SEND, REPEAT):
        body = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        # …up to the open-screen branch, which MAY still wait: nobody presses a second key
        # at a screen they opened by hand.
        hot = body[:next((i for i, l in enumerate(body)
                          if l.startswith("IF sent_ok == 1")), len(body))]
        for slow in ("WHILE", "WAIT "):
            assert not any(l.startswith(slow) for l in hot), (
                f"{path.name} stands still on the hot path — the next key pays for it")


def test_a_send_leaves_on_the_next_tick_not_a_third_of_a_second_later():
    """It has to leave from the GAME's thread; how long it waits for one is a budget."""
    for chunk in (lua_actions.macro_send(), lua_actions.macro_repeat()):
        assert "DelayInvoke" in chunk
        assert "end, 0.05)" in chunk
        assert "end, 0.3)" not in chunk


def test_the_send_still_writes_down_the_count_it_will_be_judged_by():
    """Deferred is not dropped — both keys record `before`, and both report `prev`."""
    for chunk in (lua_actions.macro_send(), lua_actions.macro_repeat()):
        assert "GetOwnerMarches" in chunk
        assert ".prev" in chunk and ".say" in chunk
        assert "previous press: " in chunk


# ---------------------------------------------------------------------------
# the presses
# ---------------------------------------------------------------------------
def test_the_two_buttons_are_in_the_catalogue():
    for name in ("macro_send", "macro_repeat"):
        assert game_buttons.get(name) is not None, name
        assert name in game_buttons.names()


def test_neither_button_sits_out_a_pause_after_pressing():
    """#1290: a `wait` is a sleep with the game claim held, and both recipes measure.

    Two seconds each was two seconds in which the NEXT key press answered «занят» —
    and the march they were waiting for is counted by the recipe anyway.
    """
    for name in ("macro_send", "macro_repeat"):
        assert game_buttons.get(name).wait == 0.0, name


def test_the_send_reads_the_screen_and_resolves_the_squad():
    lua = lua_actions.macro_send()
    for field in ("targetType", "targetPoint", "targetUuid", "targetServerId",
                  "timeIndex", "autoBackHome"):
        assert field in lua, f"the send does not read {field}"
    assert "UIFormationSelectListV2" in lua and "UIFormationSelectListNew" in lua
    assert "ArmyFormationList" in lua        # squad number -> formation uuid
    assert "tonumber(c.targetUuid)" not in lua, (
        "the target is the one value that must reach the send unchanged")
    assert "NeedTakeArmy" not in lua, (
        "called bare it answers true, and a send with needSoldier=true creates no "
        "march — #1283 lost an afternoon to it")


def test_the_send_presses_the_games_own_button_in_the_same_chunk_it_read():
    lua = lua_actions.macro_send()
    assert "OnCheckTime" in lua, "an OPEN screen is still pressed, not re-sent"
    assert "SetSelectFormationUuid" in lua
    # …and it writes the march down BEFORE pressing: the screen closes itself.
    assert lua.index("__lw_macro_last") < lua.index("OnCheckTime")
    # …and the reading of the screen is in the SAME chunk as the press (#1290), so
    # nothing can close it in between.
    assert lua.index("targetUuid") < lua.index("OnCheckTime")


def test_the_screen_is_tried_before_the_clicked_target():
    """A person who opened the squad screen went that way on purpose (#1328).

    Its target is fresher than a tile's and carries a rally's wait slot, so the screen
    wins whenever there is one; the pin is what answers when there is not.
    """
    lua = lua_actions.macro_send()
    assert lua.index("_findscreen()") < lua.index("__lw_macro_pick")


def test_the_send_tells_its_refusals_apart():
    lua = lua_actions.macro_send()
    for verdict in ("p.result = 0", "p.result = -1", "p.result = -2",
                    "p.result = -3", "p.result = -4", "p.result = -5",
                    "p.result = -6", "p.result = -7", "p.result = -8",
                    "p.result = 1", "p.result = 2"):
        assert verdict in lua, verdict
    assert "result" in lua_actions.macro_result()


# ---------------------------------------------------------------------------
# the click watcher (#1328)
# ---------------------------------------------------------------------------
def test_the_click_is_caught_by_wrapping_the_popups_own_controller():
    """The pin is made by the CLICK, not by the panel going looking afterwards.

    Wrapping `UIWorldPointCtrl:InitData` on the CLASS table catches every instance and
    therefore every click there is — a finger on the map, `OnClickWorldPoint`, a jump out
    of the magnifier — with nothing polled and no timer left running in somebody's game.
    """
    lua = lua_actions.macro_pick_arm()
    assert "UIWindowNames.UIWorldPoint" in lua
    assert "cls.InitData" in lua and "__lw_pick_orig" in lua
    assert "DataCenter.__lw_macro_pick" in lua
    # …once, and never a wrapper around a wrapper.
    assert "rawget(cls, '__lw_pick_orig')" in lua
    # …and the game's own method runs FIRST and unprotected: a popup that opened blank
    # because a macro was listening would be worse than anything this fixes.
    assert lua.index("table.pack(orig(s, ...))") < lua.index("__lw_pick_read(s)")
    assert "table.unpack(r, 1, r.n)" in lua, "InitData's own answer is handed back"


def test_the_watcher_is_armed_by_the_press_itself():
    """A client that restarted between two presses is watched again, at no round trip."""
    assert "__lw_pick_orig" in lua_actions.macro_send()


def test_the_kind_of_target_is_read_out_of_the_games_own_enums():
    """Never a number copied into this repository: a season renumbers them (#1328)."""
    lua = lua_actions.macro_pick_arm()
    assert "WorldPointUIType" in lua and "MarchTargetType" in lua
    for name in ("U.Monster", "U.Boss", "U.City", "U.CollectPoint", "U.CollectArmy"):
        assert name in lua, name
    for name in ("M.ATTACK_MONSTER", "M.ATTACK_CITY", "M.COLLECT",
                 "M.ATTACK_ARMY_COLLECT"):
        assert name in lua, name


def test_a_rally_only_monster_is_never_marched_on_by_a_key():
    """`canAttack == 0` is the game's own «this one needs a banner» (world-monsters.md).

    And `GetMonsterData` is asked WITH the uuid: called bare it answers a stub whose
    `canAttack` is 0, and every monster would read as rally-only.
    """
    lua = lua_actions.macro_pick_arm()
    assert "s:GetMonsterData(s.uuid)" in lua
    assert "p.can == 1" in lua
    assert "p.result = -6" in lua_actions.macro_send()


def test_the_players_own_base_is_not_a_target():
    lua = lua_actions.macro_pick_arm()
    assert "p.mine" in lua and "ownerUid" in lua
    assert "if p.mine == 0 then p.mtt = tonumber(M.ATTACK_CITY) end" in lua


def test_every_open_moves_the_pin_and_the_press_is_what_judges():
    """The target must FOLLOW the person, and the second live session is why (#1328).

    Telling an errand's popup from a finger was tried and cannot be done: `InitData` runs
    when the SERVER's reply lands, so the opener is long gone from the stack, and the test
    read «scripted» off this watcher's own two frames — answering that to everything. A
    scripted open was then not kept, so the pin froze on whatever got in first and the key
    marched on the original target however often the person clicked elsewhere.

    So: every open is recorded, and the press refuses by KIND. That is the safe way round —
    a pin that sometimes refuses to move is a squad marching at a target nobody chose.
    """
    read = lua_actions.macro_pick_arm()
    assert ("if p.point ~= nil then DataCenter.__lw_macro_pick = p end" in read), (
        "a click must always move the pin")
    for gone in ("debug.getinfo", "short_src", "p.script"):
        assert gone not in read, f"{gone} cannot answer who opened a popup — see #1328"
    assert "p.result = -9" not in lua_actions.macro_send()
    # …and the keeping lives in the READER, which every arming re-assigns — not in the
    # wrapper, which is installed once and would carry yesterday's bug for ever on a
    # client that is already running.
    assert "pcall(function() DataCenter.__lw_pick_read(s) end)" in read


def test_the_wrapper_can_be_replaced_on_a_client_that_is_already_running():
    """A client runs for days and the panel restarts several times a day (#1328).

    «Installed once, for ever» meant a live client kept yesterday's wrapper whatever the
    code said — and wrapping the wrapper only leaves the old body underneath, still doing
    the old thing. A version puts the GAME's own method back first.
    """
    read = lua_actions.macro_pick_arm()
    assert "__lw_pick_ver" in read
    assert "cls.InitData = cls.__lw_pick_orig cls.__lw_pick_orig = nil" in read


def test_a_pin_goes_stale_by_time_scene_and_account():
    """Three ways a clicked target stops being the target, and each says which (#1328)."""
    lua = lua_actions.macro_send()
    assert "GetServerSeconds" in lua, "the GAME's clock, never the PC's"
    assert "p.stale" in lua and "or 180" in lua
    assert "GetIsInWorld" in lua
    assert "LuaEntry.Player.uid" in lua and "LuaEntry.Player.serverId" in lua


def test_the_clicked_target_is_marched_on_with_no_window_at_all():
    lua = lua_actions.macro_send()
    assert "SendCreateMarchMessage" in lua
    assert "DelayInvoke" in lua, "a cold send is created and dropped"
    assert "OpenWindow" not in lua, "the squad screen is what #1328 exists to avoid"
    assert "OnClickStartMarch" not in lua, "that IS the squad screen, opened by hand"
    assert ", 1, 1, false, _sv, nil)" in lua, "needSoldier=false, as every proven send"
    # …and the popup the click opened is closed by ITS OWN controller, never by
    # DestroyAllWindow, which takes the HUD with it and does not give it back.
    assert "CloseSelf" in lua and "DestroyAllWindow" not in lua


def test_a_press_does_not_spend_the_click():
    """Three keys in a row put three squads on one target — what a boss is clicked for."""
    lua = lua_actions.macro_send()
    tail = lua[lua.index("p.result = 2"):]
    assert "__lw_macro_pick = nil" not in lua
    assert "__lw_macro_pick" not in tail


def _block(text: str, head: str) -> list:
    """The indented body under `head` — the recipe's own blocks, as lines."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == head)
    out = []
    for l in lines[start + 1:]:
        if l.strip() and not l.startswith(" "):
            break
        if l.strip() and not l.lstrip().startswith("#"):
            out.append(l.strip())
    return out


def test_the_clicked_path_does_not_stand_and_wait_for_its_march():
    """The run holds the game claim, and a key pressed while it is held is refused.

    Seven seconds of counting marches after the first send is seven seconds in which the
    second and third keys did nothing — which is «the macro works once» (#1328, live). The
    verdict is deferred to the next press instead, off the count this one wrote down.
    """
    text = SEND.read_text(encoding="utf-8")
    body = _block(text, "IF sent_ok == 2")
    assert body, "the clicked path has no block of its own"
    for slow in ("WHILE", "WAIT", "GetOwnerMarches"):
        assert not any(l.startswith(slow) or slow in l for l in body), (
            f"{slow} is in the clicked path — the next key press pays for it")
    assert sum(1 for l in body if l.startswith("READ_LUA")) == 1
    # …and the open-screen path may still wait: nobody presses a second key at a screen.
    assert any("WHILE sent < 1" in l for l in _block(text, "IF sent_ok == 1"))


def test_the_next_press_reports_what_the_last_one_achieved():
    """Deferred is not dropped: a send that quietly did nothing is still reported."""
    lua = lua_actions.macro_send()
    assert "_L.pin == 1" in lua and "p.prev = p.before - _L.before" in lua
    assert "previous press: " in lua
    assert "(DataCenter.__lw_macro or {}).say" in SEND.read_text(encoding="utf-8")


def test_the_delayed_send_carries_its_own_copy_of_the_arguments():
    """…and BECAUSE three keys in a row are the point, the send may not read the shared
    table a third of a second later: press two would overwrite what press one is about to
    march with."""
    lua = lua_actions.macro_send()
    assert "SendCreateMarchMessage(_f, _t, _pt, _tg, 1, 1, false, _sv, nil)" in lua
    assert "local _f, _t, _pt, _tg, _sv = " in lua


def test_a_pin_never_reaches_the_panels_log_with_an_account_in_it():
    """The pin holds a uid and an ownerUid so it can tell accounts apart — and neither
    is ever printed. What the log gets is the kind and the tile."""
    lua = lua_actions.macro_send()
    marker = lua[lua.index('CS.UnityEngine.Debug.LogError("ACT macro_send squad='):]
    for secret in ("p.who", "q.who", "ownerUid", "p.mine"):
        assert secret not in marker, secret


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


def test_both_chunks_are_lua_a_client_would_accept():
    """Compile them offline — the merge of #1290 put a `(function() … end)()` in each.

    A press that is not valid Lua fails the way this repository's worst failures fail:
    `SafeDoString` swallows it, the marker line never lands, and the recipe reports the
    ordinary «no march went out». Compiling them here costs nothing and needs no game.
    """
    try:
        import lupa
    except ImportError:                       # noqa: PERF203 — an absent lupa is not a fault
        return
    runtime = lupa.LuaRuntime()
    for name in ("macro_send", "macro_repeat", "macro_result", "macro_repeat_result",
                 "macro_repeat_ready", "macro_sent", "macro_repeat_sent",
                 "macro_pick_arm", "macro_pick_result", "macro_pick_desc"):
        chunk = getattr(lua_actions, name)()
        # An expression-shaped helper is compiled as one; a press is a block.
        source = f"return {chunk}" if chunk.lstrip().startswith("(") else chunk
        try:
            runtime.compile(source)
        except Exception as exc:              # noqa: BLE001 — the message is the point
            raise AssertionError(f"{name} is not valid Lua: {exc}") from exc


def test_the_immediately_invoked_block_cannot_be_read_as_a_call():
    """The one shape Lua's grammar is genuinely ambiguous about, pinned in both chunks.

    `(function() … end)()` after a statement whose last token is a NAME or a `)` parses
    as a call OF that thing — valid Lua that compiles, and dies at runtime with «attempt
    to call a number value», which the compile test above cannot see. Both chunks end the
    statement before it in a numeric literal, and a literal is not something Lua will try
    to call. Anybody rearranging those lines has to keep that true, or write a `;`.
    """
    assert "p.result = 0 (function()" in lua_actions.macro_send()
    assert "m.result = 0 (function()" in lua_actions.macro_repeat()


def test_the_repeat_parks_which_of_the_three_it_did():
    lua = lua_actions.macro_repeat()
    for verdict in ("m.result = 0", "m.result = -1", "m.result = 1"):
        assert verdict in lua, verdict
    assert "result" in lua_actions.macro_repeat_result()
    # …and the reading with nothing sent is still there for a caller that wants to ASK.
    for verdict in ("return 0", "return -1", "return 1"):
        assert verdict in lua_actions.macro_repeat_ready()


# ---------------------------------------------------------------------------
# the listener
# ---------------------------------------------------------------------------
class _FakeGame:
    """The claim, as a list of answers: each `claimed_by()` takes the next one."""

    def __init__(self, owners=()) -> None:
        self.owners = list(owners)
        self.asked = 0

    def claimed_by(self):
        self.asked += 1
        return self.owners.pop(0) if self.owners else ""


class _FakeRuntime:
    def __init__(self, owners=()) -> None:
        self.said: list[tuple] = []
        self.played: list[tuple] = []
        self.game = _FakeGame(owners)

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


def test_three_presses_in_a_row_all_reach_the_game():
    """The ability, in one test: click once, press 1, 2, 3 — three squads go (#1328).

    It did not. The first press held the client while its run stood counting marches, and
    the panel refuses a press that finds the client claimed, so keys two and three
    answered «занят» and nothing moved. The worker holds a key back for its turn now
    instead of throwing it away.
    """
    rt = _FakeRuntime()
    listener = _listener(rt)
    for vk in (0x31, 0x32, 0x33):
        listener._press(vk)
    assert rt.played == [(hk.SEND_ACTION, {"squad": 1}, hk.TAG),
                         (hk.SEND_ACTION, {"squad": 2}, hk.TAG),
                         (hk.SEND_ACTION, {"squad": 3}, hk.TAG)]


def test_a_press_waits_for_the_run_in_front_of_it_and_is_not_thrown_away():
    rt = _FakeRuntime(owners=["macro", "macro", "macro"])   # busy, busy, busy, then free
    listener = _listener(rt)
    listener._press(0x32)
    assert rt.game.asked >= 4, "the press gave up without waiting for its turn"
    assert rt.played == [(hk.SEND_ACTION, {"squad": 2}, hk.TAG)]


def test_a_press_gives_up_waiting_rather_than_hanging_on_a_stuck_claim():
    """A key held longer than a breath is a key the person has given up on."""
    held = ["someone"] * 10_000
    rt = _FakeRuntime(owners=held)
    listener = _listener(rt)
    was, hk.TURN_WAIT_SEC = hk.TURN_WAIT_SEC, 0.2
    try:
        started = time.monotonic()
        listener._press(0x31)
        waited = time.monotonic() - started
    finally:
        hk.TURN_WAIT_SEC = was
    assert waited < 2.0, f"waited {waited:.1f}s on a claim that never frees"
    # …and the press is still MADE — refusing it is the runtime's answer to give, in the
    # log, not something this thread decides by dropping the key silently.
    assert rt.played == [(hk.SEND_ACTION, {"squad": 1}, hk.TAG)]


def test_a_runtime_with_no_claim_to_read_is_not_a_reason_to_wait():
    class _Bare(_FakeRuntime):
        def __init__(self):
            super().__init__()
            del self.game
    rt = _Bare()
    _listener(rt)._press(0x31)
    assert rt.played == [(hk.SEND_ACTION, {"squad": 1}, hk.TAG)]


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
