r"""Spending bag items for march energy (#1702).

No game: the scenario is parsed off disk, the press is the Lua the catalogue would fire
(compiled, never run), and the arithmetic of «buy exactly this much» is checked against
the real chunk with a fake bag. Run it anywhere::

    python3 tests/test_stamina_items.py

What is worth pinning is the shape of the send and the discipline of the spend:

  * `item.use` takes a TABLE — `{uuid, num}`. Four other shapes were tried live and this
    is the only one the client serialises; the positional pair every other message in
    this repository uses returns cleanly and does nothing;
  * a stack is addressed by its OWN uuid, never by the item id;
  * the run stops SHORT of what it was asked for rather than overshooting it — one item
    more than asked is somebody's inventory spent without being asked;
  * and an item the table does not name is left alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "src", _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lua_actions  # noqa: E402
import game_buttons  # noqa: E402
from lastwar_bot import script_engine as engine  # noqa: E402

RECIPE = _REPO_ROOT / "src" / "lastwar_bot" / "actions" / "use_stamina.md"


def _bag(rt, stacks):
    """A fake bag: `stacks` is [(itemId, count), …]; every send is recorded."""
    rt.execute("SENT = {}")
    rt.execute("""
    LuaEntry = {Player = {stamina = 100}}
    MsgDefines = {ItemUse = 'item.use'}
    CS = {UnityEngine = {Debug = {LogError = function() end}}}
    SFSNetwork = {SendMessage = function(msg, payload)
      SENT[#SENT + 1] = tostring(payload.uuid) .. ':' .. tostring(payload.num)
    end}
    DataCenter = {ItemData = {ItemInfos = {}}}
    """)
    for i, (item_id, count) in enumerate(stacks, start=1):
        rt.execute("DataCenter.ItemData.ItemInfos[%d] = {itemId = %d, count = %d, uuid = 'u%d'}"
                   % (i, item_id, count, i))


def test_the_recipe_parses_and_declares_what_it_takes():
    defaults, _body = engine.extract_defaults(RECIPE.read_text(encoding="utf-8"))
    assert defaults.get("amount") == 1000
    source, _vars = engine.prepare_source(RECIPE.read_text(encoding="utf-8"), None)
    engine.parse_text(source)


def test_every_press_the_recipe_plays_is_in_the_catalogue():
    source, _ = engine.prepare_source(RECIPE.read_text(encoding="utf-8"), None)
    for stmt in engine.parse_text(source):
        name = getattr(stmt, "button", None)
        if name:
            assert name in game_buttons.BUTTONS, f"unknown button {name!r}"


def test_the_send_is_a_table_with_num_and_the_stacks_own_uuid():
    press = lua_actions.use_stamina_items()
    assert "MsgDefines.ItemUse" in press
    assert "{uuid = st.uuid, num = n}" in press, \
        "the send is positional or keyed by the item id — live, that does nothing at all"


def test_it_buys_exactly_what_was_asked_for_biggest_first():
    import lupa
    rt = lupa.LuaRuntime()
    _bag(rt, [(400401, 93), (400402, 476)])          # 93 fifties, 476 tens
    rt.execute("DataCenter.__lw_stam_want = 1000")
    rt.execute(lua_actions.use_stamina_items())
    assert rt.eval("DataCenter.__lw_stam.spent") == 1000
    assert rt.eval("DataCenter.__lw_stam.used") == "400401x20", \
        "a thousand is twenty fifties — the big denomination goes first"
    assert rt.eval("#SENT") == 1


def test_a_short_stack_is_topped_up_from_the_smaller_coin():
    import lupa
    rt = lupa.LuaRuntime()
    _bag(rt, [(400401, 3), (400402, 20)])            # 150 + 200 available
    rt.execute("DataCenter.__lw_stam_want = 200")
    rt.execute(lua_actions.use_stamina_items())
    assert rt.eval("DataCenter.__lw_stam.spent") == 200
    assert rt.eval("DataCenter.__lw_stam.used") == "400401x3,400402x5"


def test_it_stops_short_rather_than_spending_one_item_too_many():
    import lupa
    rt = lupa.LuaRuntime()
    _bag(rt, [(400401, 1)])                          # one fifty, and nothing else
    rt.execute("DataCenter.__lw_stam_want = 30")
    rt.execute(lua_actions.use_stamina_items())
    assert rt.eval("DataCenter.__lw_stam.spent") == 0, \
        "a fifty was spent to buy thirty — the caller asked for a number"
    assert rt.eval("#SENT") == 0


def test_an_item_the_table_does_not_name_is_left_alone():
    import lupa
    rt = lupa.LuaRuntime()
    _bag(rt, [(999999, 500)])                        # something else entirely
    rt.execute("DataCenter.__lw_stam_want = 100")
    rt.execute(lua_actions.use_stamina_items())
    assert rt.eval("#SENT") == 0, "the bag was spent on an item nobody identified"


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
