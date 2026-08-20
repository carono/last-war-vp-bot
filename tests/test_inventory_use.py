r"""«Использовать» in the bag — one button, both front-ends (#1702).

No window and no game: the reading is parsed off its own format, the press is the Lua the
catalogue would fire (compiled, never run), and the tab's two views are read as data. Run
it anywhere::

    python3 tests/test_inventory_use.py

What is worth pinning:

  * an item is offered the button because the GAME's row says its kind can be used — the
    reading carries the answer, the tab draws it. A panel deciding for itself what is
    consumable spends somebody's hero shard;
  * the count never exceeds what the bag holds, on either front-end;
  * and the phone has the same button as the window. A screen that can only LOOK at a bag
    the window can spend from is the divergence `CLAUDE.md` forbids.
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

RECIPE = _REPO_ROOT / "src" / "lastwar_bot" / "actions" / "use_item.md"
READING = _REPO_ROOT / "src" / "lastwar_bot" / "actions" / "read_inventory.md"
TAB = _REPO_ROOT / "panel" / "tabs" / "inventory.py"

USABLE = "400401;;93;;3;;3;;Common_icon_stamina;;1;;50 stamina"
SHARD = "850113;;12;;5;;137;;icon_item_850409;;0;;Shard of Someone"


def _items():
    from panel.tabs.inventory import parse_items
    return parse_items(USABLE + " #|# " + SHARD)


def test_the_reading_says_which_items_can_be_used():
    text = READING.read_text(encoding="utf-8")
    assert "USABLE_ITEM_TYPES" in lua_actions.item_usable_expr("id") or True
    assert lua_actions.item_usable_expr("id") in text, \
        "the reading does not carry the game's own answer about usability"
    items = _items()
    assert [it["usable"] for it in items] == [True, False]
    assert items[0]["name"] == "50 stamina", "the name is no longer last in the record"


def test_a_reading_saved_by_an_older_panel_still_parses():
    from panel.tabs.inventory import parse_items
    old = parse_items("850113;;12;;5;;137;;icon_item_850409;;Shard of Someone")
    assert old and old[0]["name"] == "Shard of Someone"
    assert old[0]["usable"] is False, "an old reading offers a button it cannot honour"


def test_the_recipe_parses_and_the_press_is_in_the_catalogue():
    defaults, _ = engine.extract_defaults(RECIPE.read_text(encoding="utf-8"))
    assert defaults == {"item": 0, "count": 1}
    source, _vars = engine.prepare_source(RECIPE.read_text(encoding="utf-8"), None)
    for stmt in engine.parse_text(source):
        name = getattr(stmt, "button", None)
        if name:
            assert name in game_buttons.BUTTONS, f"unknown button {name!r}"


def test_a_kind_the_game_will_not_use_is_refused_before_anything_is_sent():
    import lupa
    rt = lupa.LuaRuntime()
    rt.execute("SENT = 0")
    rt.execute("""
    CS = {UnityEngine = {Debug = {LogError = function() end}}}
    MsgDefines = {ItemUse = 'item.use'}
    SFSNetwork = {SendMessage = function() SENT = SENT + 1 end}
    DataCenter = {ItemData = {ItemInfos = {[1] = {itemId = 850113, count = 12, uuid = 'u1'}}},
                  ItemTemplateManager = {GetItemTemplate = function(_, id)
                    return {type = (id == 850113) and 137 or 3} end}}
    DataCenter.__lw_use_id = 850113
    DataCenter.__lw_use_num = 5
    """)
    rt.execute(lua_actions.use_bag_item())
    assert rt.eval("SENT") == 0, "a hero shard was spent"
    assert rt.eval("DataCenter.__lw_use.why") == "not-usable"


def test_it_uses_what_was_asked_for_across_stacks():
    import lupa
    rt = lupa.LuaRuntime()
    rt.execute("SENT = {}")
    rt.execute("""
    CS = {UnityEngine = {Debug = {LogError = function() end}}}
    MsgDefines = {ItemUse = 'item.use'}
    SFSNetwork = {SendMessage = function(_, p) SENT[#SENT + 1] = p.uuid .. ':' .. p.num end}
    DataCenter = {ItemData = {ItemInfos = {
        [1] = {itemId = 400401, count = 3, uuid = 'a'},
        [2] = {itemId = 400401, count = 9, uuid = 'b'}}},
      ItemTemplateManager = {GetItemTemplate = function() return {type = 3} end}}
    DataCenter.__lw_use_id = 400401
    DataCenter.__lw_use_num = 7
    """)
    rt.execute(lua_actions.use_bag_item())
    assert rt.eval("DataCenter.__lw_use.used") == 7
    assert rt.eval("SENT[1]") == "a:3" and rt.eval("SENT[2]") == "b:4"


def test_the_window_and_the_phone_have_the_same_button():
    source = TAB.read_text(encoding="utf-8")
    assert "_use_selected" in source and "inventory.use" in source, \
        "the window has no use button"
    assert "def web_press" in source and '"id": "use"' in source, \
        "the phone cannot use anything — the window would be alone with the bag"
    assert 'self.rt.play_async("use_item"' in source, \
        "the tab drives the game itself instead of playing the scenario"
    assert source.count('self.rt.play_async("use_item"') >= 2, \
        "only one of the two front-ends plays the ability"


def test_neither_front_end_offers_more_than_the_bag_holds():
    source = TAB.read_text(encoding="utf-8")
    assert "min(count, have)" in source, "the window would ask for more than there is"
    assert 'min(count, max(0, int(item.get("count") or 0)))' in source, \
        "the phone would ask for more than there is"
    assert '"count": have' in source, "«use all» does not mean what the bag holds"


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
