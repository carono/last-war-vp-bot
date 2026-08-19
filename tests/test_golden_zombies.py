r"""The golden-zombie chain — the recipe, the presses behind it, and the day's tally.

No game and no panel window: the recipe is parsed off disk, the presses are the Lua the
catalogue would fire (compiled, never run), and the tally is plain arithmetic. Run it
anywhere::

    python3 tests/test_golden_zombies.py

What is worth pinning here is the part that cost the live session its afternoon (#1519):

  * the zombie is identified by a CONFIG ID and never by a picture, so the id has to be
    in the whitelist the enumerator is given and nowhere else;
  * an attack is counted only when the SERVER charged the energy for it — a send returns
    cleanly whether or not it was honoured (docs/research/world-monsters.md, Findings 13
    and 16), and two whole runs reported «sent» over marches that never left;
  * the last march of a run brings the squad home, because every one before it
    deliberately leaves it standing on the map;
  * the day's tally sums the marches and does NOT sum the sightings — the same zombie
    seen by two runs is one zombie;
  * a monster the game would not put a level on reads as «nobody could say» all the way
    to the cell, and never as level ZERO — «уровень 0» over a level-10 golden zombie is
    the reading that started this.
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
from panel import golden_zombies as tally  # noqa: E402
from panel.tabs.secret_tasks import world as worldmod  # noqa: E402

RECIPE = _REPO_ROOT / "src" / "lastwar_bot" / "actions" / "attack_golden_zombies.md"
READING = _REPO_ROOT / "src" / "lastwar_bot" / "actions" / "read_golden_zombies.md"
READING_MONSTERS = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
                    / "read_world_monsters.md")

#: The presses the recipe plays, and the order they only make sense in.
PRESSES = ("golden_arm", "golden_scan", "golden_pick", "golden_touch", "golden_grab",
           "golden_send", "golden_home", "golden_confirm")


def _source(path: Path, variables=None):
    return engine.prepare_source(path.read_text(encoding="utf-8"), variables or {})


def test_both_recipes_parse_and_declare_what_they_take():
    body, args = _source(RECIPE)
    assert engine.parse_text(body), "the chain parsed to nothing"
    for name in ("squad", "radius", "scan", "limit", "march_wait"):
        assert name in args, f"the chain does not declare {name}"
    assert args["squad"] == 1, "the default squad must be the first slot"
    reading, _ = _source(READING)
    assert engine.parse_text(reading), "the reading parsed to nothing"


def test_every_press_the_chain_plays_is_in_the_catalogue():
    body, _ = _source(RECIPE)
    played = {line.split()[1] for line in body.splitlines()
              if line.strip().upper().startswith("TAP ")}
    for name in played:
        assert name in game_buttons.BUTTONS, f"{name} is played and not in the catalogue"
    for name in PRESSES:
        assert name in game_buttons.BUTTONS, f"{name} is missing from the catalogue"


def test_the_zombie_is_a_config_id_and_never_a_picture():
    """Identity is a row of the game's config, reached two ways and hard-coded neither.

    The config id is the identity; the PREFAB name is how a drawn clone is matched back
    to it, and that name is read out of the config's own `pic_name` column at run time —
    never spelled out here. What must never appear is a look at the monster's APPEARANCE:
    the icon, the sprite, the colour in its name.
    """
    assert lua_actions.GOLDEN_ZOMBIE_CFG == 1030000
    scan = lua_actions.golden_scan()
    assert "_goldids()" in scan, "the scan must take its whitelist from the config"
    assert "'pic_name'" in scan, "the scan does not ask the config what the prefab is"
    arm = lua_actions.golden_arm()
    assert str(lua_actions.GOLDEN_ZOMBIE_CFG) in arm, "the arm does not park the id"
    for banned in ("worldmap_icon", "huang", "world_monster_general_invasion"):
        assert banned not in scan, \
            f"the scan is looking at {banned} — a re-skin or a rename would break it"


def test_the_send_is_scheduled_on_the_main_thread():
    """A cold send from the hijack thread is built and then dropped by the server."""
    send = lua_actions.golden_send()
    assert "DelayInvoke" in send, "the send is not scheduled — it will be dropped"
    assert "SendCreateMarchMessage" in send
    assert "ATTACK_MONSTER" in send and "CROSS_ATTACK_MONSTER" in send, \
        "a target on another warzone needs the cross-server march type"


def test_the_send_does_not_count_the_attack_and_the_confirm_does():
    send = lua_actions.golden_send()
    assert "p.attacks = (tonumber(p.attacks) or 0) + 1" not in send, \
        "the send counts its own press — that is what reported five attacks over none"
    assert "p.pending" in send, "the send must leave something for the confirm to prove"
    confirm = lua_actions.golden_confirm()
    assert "p.attacks = (tonumber(p.attacks) or 0) + 1" in confirm
    assert "p.spent" in confirm


def test_the_proof_of_an_attack_is_the_energy_the_server_took():
    settled = lua_actions.golden_settled()
    assert "p.before" in settled and "p.cost" in settled, \
        "the proof must be the purse moving by the price of one attack"
    assert "stamina" in settled, "the purse is the player's stamina"


def test_the_chain_measures_from_the_squad_and_not_from_home():
    pick = lua_actions.golden_pick()
    assert "p.anchor" in pick, "the pick does not measure from the squad"
    send = lua_actions.golden_send()
    assert "p.anchor = {x = t.x, y = t.y}" in send, \
        "the send does not move the anchor to where the squad went"


def test_the_last_march_of_a_run_brings_the_squad_home():
    body, _ = _source(RECIPE)
    assert "DataCenter.__lw_gold_back = 1" in body, \
        "nothing ever raises «come home» — a run would leave the squad on the map"
    assert "DataCenter.__lw_gold_back = 0" in body, \
        "the chain never switches «come home» off — every march would walk back"
    last = lua_actions.golden_last_march()
    assert "cost * 2" in last, "the last march is not worked out from what is left"


def test_the_energy_is_asked_and_never_kept():
    go = lua_actions.golden_can_go()
    assert "stamina" in go, "the loop's gate does not ask the game for the energy"
    assert "p.energy" not in go, "the gate is reading a number we wrote down ourselves"


def test_the_reading_says_could_not_ask_apart_from_none_there():
    survey = lua_actions.golden_survey()
    assert "local seen = -1" in survey, \
        "a survey taken off the map must not report «none found»"


def test_a_report_becomes_numbers_and_a_day_adds_up():
    row = tally.parse_report(
        "found=143 attacks=6 spent=60 cost=10 energy=45 queued=137 squad=1")
    assert row["attacks"] == 6 and row["spent"] == 60 and row["found"] == 143
    assert tally.parse_report("attacks=nonsense") == {}, "a non-number was invented"
    assert tally.parse_report(None) == {}

    days = tally.add_run({}, row, "2026-08-19")
    days = tally.add_run(days, tally.parse_report("found=90 attacks=2 spent=20"),
                         "2026-08-19")
    today = tally.day_row(days, "2026-08-19")
    assert today["attacks"] == 8, "the marches are not summed"
    assert today["spent"] == 80, "the energy is not summed"
    assert today["found"] == 143, "the sightings were summed — the same zombie twice"
    assert today["runs"] == 2

    assert tally.day_row({}, "2026-08-19") == {"attacks": 0, "spent": 0,
                                               "found": 0, "runs": 0}
    other = tally.add_run(days, row, "2026-08-20")
    assert other["2026-08-19"]["attacks"] == 8, "a new day rewrote the old one"


#: A stand-in for `lw_world_monster`: the golden zombie's three rows, which agree on
#: everything, and its boss's two, which do not agree on the level. The shape is the one
#: `LocalController:getTable` really answers with — `{index = <column -> id>, data =
#: <id -> row>}` — read live on 2026-08-19.
_CONFIG_STUB = """
local rows = {
  [1030000] = {[1]=1030000, [2]=10, [3]=7, [4]=9,  [40]='world_monster_general_invasion'},
  [1030001] = {[1]=1030001, [2]=10, [3]=7, [4]=9,  [40]='world_monster_general_invasion'},
  [1030002] = {[1]=1030002, [2]=10, [3]=7, [4]=9,  [40]='world_monster_general_invasion'},
  [1030003] = {[1]=1030003, [2]=5,  [3]=7, [4]=10, [40]='world_monster_boss_invasion'},
  [1030004] = {[1]=1030004, [2]=75, [3]=7, [4]=10, [40]='world_monster_boss_invasion'},
}
-- The column NUMBERS come from `getLine(id):getMetaData()` and the ROWS from
-- `getTable().data` — two readings this repository is certain of. `getTable().index`
-- looks like it should answer the first and does not: every lookup through it was nil
-- and the map built itself empty, in silence, through two panel restarts (#1519).
LocalController = {instance = function()
  return {
    getTable = function(_, _name) return {index = {}, data = rows} end,
    getLine = function(_, _t, _id)
      return {getMetaData = function()
        return {pic_name={40,'string'}, level={2,'int'},
                type={3,'int'}, special={4,'int'}}
      end}
    end,
    getValue = function(_, _t, id, field, _d)
      local r = rows[id]
      if r == nil then return nil end
      if field == 'pic_name' then return r[40] end
      if field == 'level' then return r[2] end
      if field == 'type' then return r[3] end
      return r[4]
    end,
  }
end}
_G.__LW_MON_PREFAB = nil
"""


def _lua_with_config():
    """A Lua runtime holding the config stub above, or `None` where lupa is absent."""
    try:
        import lupa
    except ImportError:
        return None
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(_CONFIG_STUB)
    return runtime


def test_a_prefab_answers_only_where_its_config_rows_agree():
    """The level of a prefab standing for one monster; nothing for one standing for many."""
    runtime = _lua_with_config()
    if runtime is None:
        return
    read = runtime.eval("(function() %s local m = _monmap() "
                        "local g = m['worldmonstergeneralinvasion'] "
                        "local b = m['worldmonsterbossinvasion'] "
                        "return g.level, g.type, g.n, b.level, b.type end)"
                        % lua_actions.monster_prefab_lookup())
    g_level, g_type, g_rows, b_level, b_type = read()
    assert g_level == 10 and g_type == 7, "the golden zombie's own level was not read"
    assert g_rows == 3, "the three rows behind the prefab were not all found"
    assert "getMetaData()" in lua_actions.monster_prefab_lookup(), \
        "the column numbers come from a reading that has never been shown to answer"
    assert b_level is None, \
        "a prefab spanning levels 5..75 invented one — that is the same lie in a new place"
    assert b_type == 7, "a field the rows DO agree on must still be answered"


def test_the_monsters_read_carries_the_CURRENT_copy_of_the_lookup():
    """The recipe embeds the prefab map's builder, so it can go stale — and it did.

    The DSL has no include, so `read_world_monsters.md` holds a COPY of
    `monster_prefab_lookup()`. Live, the copy was two fixes behind while the module was
    right, every level read `-1`, and the fix looked like it had failed (#1519). The copy
    is regenerated from the module; this is what says so.
    """
    body = READING_MONSTERS.read_text(encoding="utf-8")
    assert lua_actions.monster_prefab_lookup() in body, \
        ("the recipe's copy of the prefab lookup has drifted from the module — "
         "regenerate it from `lua_actions.monster_prefab_lookup()`")


def test_the_map_cached_in_the_game_carries_the_version_that_built_it():
    """A panel restart does not clear the game's Lua globals — the cache must say so.

    The fix for the level column was restarted into TWICE and went on answering from the
    empty map the broken builder had parked in `_G`, because the game VM had not gone
    anywhere (#1519). A cache in the VM is stale until proven otherwise.
    """
    lookup = lua_actions.monster_prefab_lookup()
    assert "c.v == %d" % lua_actions.MON_MAP_VERSION in lookup, \
        "the cache is read back without checking which code wrote it"
    assert "v = %d" % lua_actions.MON_MAP_VERSION in lookup, \
        "the cache is written without stamping the code that wrote it"


def test_the_scan_matches_the_golden_prefab_and_not_merely_the_word_invasion():
    scan = lua_actions.golden_scan()
    assert "_goldpic()" in scan, "the scan does not ask the config what a golden one looks like"
    assert "string.find(string.lower(nm), 'invasion')" not in scan, \
        "«the name contains invasion» is also true of the level 5..75 boss"
    assert "_goldids()" in scan, \
        "the whitelist is one config id — the prefab stands for three of them"


def test_a_level_nobody_could_read_is_a_dash_and_never_a_zero():
    rows = worldmod.parse_monsters(
        "src=scene pid=535614 x=614 y=535 uuid=0 cfg=0 type=0 level=-1 kind=WorldMonster05"
        " | src=scene pid=535615 x=615 y=535 uuid=0 cfg=1030000 type=7 level=10"
        " kind=WorldMonster_General_invasion", server=100)
    assert len(rows) == 2
    unknown, golden = rows[0], rows[1]
    assert unknown["level"] is None, "«nobody could say» came through as a number"
    assert golden["level"] == 10
    assert worldmod.MonsterGrid.level_text(unknown) == "—"
    assert worldmod.MonsterGrid.level_text(golden) == "10"
    # …and a row saved by an older panel, which wrote a literal 0, stops lying too.
    assert worldmod.MonsterGrid.level_text({"level": 0}) == "—"


def test_the_lua_of_every_press_compiles():
    try:
        import lupa
    except ImportError:                      # the offline interpreter is not there
        return
    runtime = lupa.LuaRuntime()
    for name in PRESSES:
        if name == "golden_home":            # the same chunk as golden_send
            continue
        runtime.compile(getattr(lua_actions, name)())
    runtime.compile(lua_actions.monster_prefab_lookup() + " return 1")
    for name in ("monster_prefab_probe", "golden_armed", "golden_queued",
                 "golden_found", "golden_picked",
                 "golden_needs_uuid", "golden_marching", "golden_settled",
                 "golden_can_go", "golden_last_march", "golden_attacks",
                 "golden_spent", "golden_report", "golden_survey", "golden_energy",
                 "golden_attack_cost"):
        runtime.compile("return " + getattr(lua_actions, name)())


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
