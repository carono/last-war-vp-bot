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
           "golden_send", "golden_home", "golden_confirm", "golden_look",
           "golden_approach_arm", "golden_ride", "golden_eta")


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


def test_the_proof_of_an_attack_is_a_march_and_never_the_purse():
    """#1702, the operator's model: a march appearing IS the attack going out.

    The purse decided this until now and it was wrong twice — the server does not always
    charge the price it quotes (10 quoted, 8 taken, live), and the purse does not only go
    DOWN. A refill mid-chain (56 → 102, live) made three marches that had all gone out
    read as sends nobody received, and the run reported two attacks out of three.
    """
    launched = lua_actions.golden_launched()
    assert "GetOwnerMarches" in launched, "the proof does not look at our marches at all"
    assert "march_before" in launched, \
        "the proof counts marches rather than noticing a NEW one — another squad's rally "\
        "would answer for this attack"
    assert "stamina" not in launched and "p.cost" not in launched, \
        "the send proof is still priced off the purse"
    send = lua_actions.golden_send()
    assert "p.march_before" in send, "the send never writes down what was flying before it"
    body, _ = _source(RECIPE)
    assert launched in body, "the recipe's copy of the send proof is not the module's"


def test_an_energy_refill_in_the_middle_does_not_lose_an_attack():
    """The «purse went down» reading is gone from every gate the chain branches on."""
    body, _ = _source(RECIPE)
    branches = [line.strip() for line in body.splitlines()
                if line.strip().startswith("READ_LUA") and " INTO launched" in line]
    assert branches, "nothing reads the launch proof"
    for line in branches:
        assert "stamina" not in line, \
            "an attack is still declared by the purse — a refill would lose it"
    # …and the tally still RECORDS what it cost, which is what the purse is good for.
    confirm = lua_actions.golden_confirm()
    assert "p.spent" in confirm and "before - " in confirm


def test_a_send_that_never_became_a_march_moves_on_rather_than_ending_the_run():
    """#1702: the commonest refusal is a zombie that was already dead when we asked.

    The client's list is a snapshot; another player gets there first; the server refuses
    an order at a monster that is not there. That is worth the next target — and NOT worth
    an endless one, because a client that has gone deaf refuses everything the same way.
    """
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    assert "TAP golden_miss" in lines, "a refused send has no way out but ending the run"
    i = lines.index("TAP golden_miss")
    tail = lines[i:i + 10]
    assert any(w.startswith("IF misses >") for w in tail), \
        "misses are written down and never acted on — a deaf client would spin for ever"
    assert "ARGS miss_limit" in RECIPE.read_text(encoding="utf-8"), \
        "how many refusals in a row are tolerated is not the operator's to set"
    miss = lua_actions.golden_note_miss()
    assert "p.misses" in miss and "p.pending = nil" in miss
    # …and a refusal asks the client for the armies again: a squad whose army the client
    # has forgotten reads zero soldiers, and the server refuses ITS marches in exactly the
    # same silence as a dead target (#1285, #1702).
    assert "CALL fill_empty_squads" in lines[i:i + 10], \
        "a refused send never asks whether the squad still holds an army"
    assert "p.misses = 0" in lua_actions.golden_confirm(), \
        "the miss streak is never cleared, so two refusals a chain apart end the run"


def test_a_zombie_somebody_else_killed_does_not_stall_the_chain():
    """#1702: the monster going is the proof the attack is OVER — from whoever's hand."""
    gone = lua_actions.golden_gone()
    assert "p.hit" in gone and "GetMonsterListInArea" in gone
    assert "return 1 end" in gone, "nothing to look for must answer «gone»"
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    assert "TAP golden_kill" in lines, "a confirmed kill is never counted"
    assert "TAP golden_kill_drop" in lines, \
        "a zombie that outlives the wait has no way out — the chain would stall on it"
    i = lines.index("TAP golden_kill_drop")
    assert not any(w.startswith("FAIL") for w in lines[i - 3:i + 3]), \
        "another player's kill is treated as a failure of ours"
    assert "p.kills" in lua_actions.golden_note_kill()
    assert "p.kills" not in lua_actions.golden_drop_kill(), \
        "a zombie nobody saw die is counted as ours"


def test_the_chain_measures_from_the_squad_and_not_from_home():
    pick = lua_actions.golden_pick()
    assert "p.anchor" in pick, "the pick does not measure from the squad"
    send = lua_actions.golden_send()
    assert "p.anchor = {x = t.x, y = t.y, pid = t.pid}" in send, \
        "the send does not move the anchor to where the squad went"
    # …and the FIRST pick, which has no anchor yet, measures from the BASE'S OWN TILE
    # rather than from whatever tile the camera happens to be over (#1702).
    assert "p.home" in pick, "the first pick does not measure from the base"
    arm = lua_actions.golden_arm()
    assert "_goldhome(" in arm, "the run never works out where the base is"


def test_the_camera_is_put_on_the_origin_before_every_scan():
    """#1702: the enumerator answers out of what the CLIENT has loaded.

    A lap of `scan_map` ends at the far side of the warzone, so a scan taken from there
    knows no zombie near the base and «the nearest» is a five-minute march with a dozen
    sitting beside the house. The camera goes back to the origin of the next pick — the
    base, or the last kill — and only then is the client asked.
    """
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    looks = [i for i, line in enumerate(lines) if line == "TAP golden_look_from"]
    assert looks, "the recipe never puts the camera on the origin"
    for i in looks:
        rest = lines[i + 1:i + 7]
        assert "TAP golden_scan" in rest, \
            "the camera is moved and the client is not re-asked"
    for i, line in enumerate(lines):
        if line == "TAP golden_pick":
            before = lines[max(0, i - 20):i]
            assert "TAP golden_scan" in before, \
                "a pick is made off a list nobody refreshed for this origin"
            assert "TAP golden_look_from" in before or "TAP golden_look" in before, \
                "the scan the pick reads was taken from somewhere else"
    look = lua_actions.golden_look_from()
    assert "p.anchor or p.home" in look, \
        "the camera does not follow the same origin the pick measures from"


def test_the_chain_does_not_hold_the_panel_up():
    """#1702: a run that lasts a march may not be the reason a timer waited."""
    text = RECIPE.read_text(encoding="utf-8")
    assert engine.declares_detach(text), "the chain does not declare DETACH"
    assert engine.action_detached("attack_golden_zombies")


def test_the_last_march_of_a_run_brings_the_squad_home():
    body, _ = _source(RECIPE)
    assert "DataCenter.__lw_gold_back = 1" in body, \
        "nothing ever raises «come home» — a run would leave the squad on the map"
    assert "DataCenter.__lw_gold_back = 0" in body, \
        "the chain never switches «come home» off — every march would walk back"
    last = lua_actions.golden_last_march()
    assert "cost * 2" in last, "the last march is not worked out from what is left"


def test_the_recipe_carries_the_CURRENT_copy_of_the_proofs():
    """The DSL has no include, so the recipe embeds the text — and it goes stale (#1702)."""
    body, _ = _source(RECIPE)
    for name in ("golden_launched", "golden_gone", "golden_report"):
        assert getattr(lua_actions, name)() in body, \
            f"the recipe's copy of {name} is not the module's"


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


def test_the_ride_is_only_taken_when_the_arithmetic_wins():
    """A gather order is faster than an attack one — but not on every hop.

    Measured live on 2026-08-19 with the game's own pricing function: an attack march is
    0.765 tiles a second and a gather march 1.930 — 2.52x. On the live queue the farthest
    of 80 golden zombies was 680 tiles out: 888 s by attack march against 361 s ridden,
    527 s saved. On a target eleven seconds away the plan is dropped, which is what the
    threshold is for.
    """
    arm = lua_actions.golden_approach_arm()
    assert "CalcMarchSpeedByConfig" in arm, "the speeds are guessed rather than priced"
    assert "approach_sec" in arm, "there is no threshold — a short hop would be ridden"
    assert "bestsec = direct" not in arm or "local best, bestsec = nil, direct" in arm, \
        "the plan is kept without being compared against marching straight there"
    assert "if sa <= 0 or sc <= sa then" in arm, \
        "an account with no gathering bonus would still be sent the long way round"
    ride = lua_actions.golden_approach_send()
    assert "MarchTargetType.COLLECT" in ride, "the ride is not a gather order"
    assert "DelayInvoke" in ride, "the ride is not scheduled — it will be dropped"
    assert "false, srv, nil" in ride and ", 1, 0, " in ride, \
        "the ride must not bring the squad home — it has to land beside the target"


def test_every_wait_is_on_the_marchs_clock_and_not_on_the_squads_state():
    """A squad that has landed at a mine is GATHERING and goes on reading «out».

    Measured live: a ride of 271 seconds left the formation at `state = 1` for 485
    seconds and counting. A chain that waits for the state to clear waits for ever, so
    both waits are on the march's own `endTime` — the server's arrival stamp, which came
    within two seconds of what the speed function predicted.
    """
    body, _ = _source(RECIPE)
    marching = lua_actions.golden_marching()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    # The state may be ASKED — once, to find out whether there is a march to wait for at
    # all when a run starts (#1702) — but nothing may WAIT on it: a squad standing on the
    # ground it has cleared reads «out» for ever.
    for i, line in enumerate(lines):
        if marching in line:
            var = line.rsplit(" INTO ", 1)[-1].strip() if " INTO " in line else ""
            assert var == "squad_out", \
                f"the squad's state is read into {var!r} — only the one-shot question is allowed"
            after = lines[i + 1:i + 4]
            assert not any(w.startswith(("WHILE", "WAIT")) and var in w for w in after), \
                "a wait is gated on the squad's state, which never clears while it gathers"
    assert not any(w.startswith("WHILE") and marching in w for w in lines), \
        "a loop is gated on the squad's state, which never clears while it gathers"
    assert body.count("TAP golden_eta") >= 2, \
        "the arrival clock is not wound after every march the chain sends"
    note = lua_actions.golden_note_eta()
    assert "endTime" in note and "GetOwnerMarches" in note, \
        "the clock is guessed rather than read off the march the server made"


def test_the_ride_looks_at_the_target_before_it_hunts_for_a_mine():
    """`HasPointInfo` can only answer for a district the client has actually loaded."""
    body, _ = _source(RECIPE)
    look = body.index("TAP golden_look")
    plan = body.index("TAP golden_approach_arm")
    assert look < plan, "the mine search runs before the camera has loaded the district"
    arm = lua_actions.golden_approach_arm()
    assert "ResPointInfo" in arm, \
        "the point kind is read as a number — it is an enum and `tonumber` is nil on it"


def test_the_lua_of_every_press_compiles():
    try:
        import lupa
    except ImportError:                      # the offline interpreter is not there
        return
    runtime = lupa.LuaRuntime()
    #: The catalogue's name -> the function behind it, where the two differ.
    behind = {"golden_ride": "golden_approach_send", "golden_eta": "golden_note_eta"}
    for name in PRESSES:
        if name == "golden_home":            # the same chunk as golden_send
            continue
        runtime.compile(getattr(lua_actions, behind.get(name, name))())
    runtime.compile(lua_actions.monster_prefab_lookup() + " return 1")
    for name in ("monster_prefab_probe", "golden_speeds", "golden_approach_planned",
                 "golden_rode", "golden_approach_report", "golden_arrived",
                 "golden_armed", "golden_queued",
                 "golden_found", "golden_picked",
                 "golden_needs_uuid", "golden_marching", "golden_launched", "golden_gone",
                 "golden_can_go", "golden_last_march", "golden_attacks",
                 "golden_spent", "golden_report", "golden_survey", "golden_energy",
                 "golden_attack_cost"):
        runtime.compile("return " + getattr(lua_actions, name)())


def test_the_gap_between_two_kills_carries_no_waiting_nobody_needs():
    """#1702: 13 s between two kills two tiles apart, and 10 of them were ours.

    Measured off the live log, per kill: a two-second camera flight to a district the
    client already held, the 1.5 s settle behind it, a scan whose answer the next lap
    throws away, and an arrival poll in three-second beats for a march that takes three.
    Each of the four is pinned here, because each of them reads as harmless in isolation.
    """
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    # the settle after a look is CONDITIONAL on the look having flown
    for i, line in enumerate(lines):
        if line == "TAP golden_look_from":
            window = lines[i + 1:i + 5]
            assert any(w.startswith("READ_LUA") and "looked_moved" in w for w in window), \
                "the recipe waits for a camera flight without asking whether there was one"
            assert "IF looked_moved == 1" in window
    look = lua_actions.golden_look_from()
    assert "p.looked" in look and "skipped=near" in look, \
        "the look flies the camera even when it is already in the right district"
    # …the arrival wait is two-tier: coarse beats while the march is far, one-second ones
    # for the last few seconds, so a two-tile hop is not rounded up to a three-second beat
    # and a march across the map does not spend a checkpoint a second
    assert [w for w in lines if w == "WAIT 1"], "nothing watches the end of a march closely"
    assert [w for w in lines if w == "WAIT 3"], "the whole flight is polled every second"
    far = [i for i, w in enumerate(lines) if w.startswith("WHILE far == 1")]
    near = [i for i, w in enumerate(lines) if w.startswith("WHILE arrived == 0")]
    assert far and near and min(far) < min(near), \
        "the coarse half of the arrival wait does not come first"
    assert "GOLDEN_ETA_NEAR_MS" in Path(lua_actions.__file__).read_text(encoding="utf-8")
    # …and nothing scans straight after a send, because the next lap scans anyway
    for i, line in enumerate(lines):
        if line == "TAP golden_eta":
            assert lines[i + 1] != "TAP golden_scan", \
                "the queue is rebuilt twice per kill and one of them is thrown away"


def test_the_kill_is_judged_off_a_district_that_was_just_refreshed():
    """#1702: «gone» read off tiles nobody re-fetched answers «gone» about everything.

    Measured live: the check ran one second after the squad landed, from wherever the
    camera had been, and answered «gone» every time — so the chain moved on while the
    fight was still running and the next send was refused (twice in a row, which ended the
    run). The kill's own tile IS the origin of the next pick, so the look and the scan
    that were already there serve both; the check simply belongs after them.
    """
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    gone = [i for i, w in enumerate(lines) if w.startswith("READ_LUA") and " INTO gone" in w]
    assert gone, "nothing checks whether the zombie went"
    first = min(gone)
    before = lines[:first]
    assert "TAP golden_scan" in before and "TAP golden_look_from" in before, \
        "the kill is judged before the client has been asked about that district"
    kill = lines.index("TAP golden_kill")
    assert kill > first, "the kill is counted before it is checked"


def test_a_dead_target_is_dropped_before_a_send_is_wasted_on_it():
    """#1702: the client's list is a snapshot; the map has moved on since the sweep."""
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    assert "TAP golden_drop_target" in lines
    here = [i for i, w in enumerate(lines) if w.startswith("READ_LUA") and " INTO here" in w]
    assert here, "nothing asks whether the armed target is still on the map"
    i = min(here)
    before = lines[max(0, i - 12):i]
    assert "TAP golden_look" in before and "TAP golden_scan" in before, \
        "the target is checked without looking at it — the answer is the old snapshot"
    send = [j for j, w in enumerate(lines) if w == "TAP golden_send"]
    assert send and min(send) > i, "the check comes after the send it is meant to save"
    drop = lua_actions.golden_drop_target()
    assert "p.used" in drop and "p.misses" not in drop, \
        "dropping a dead target counts as a refused order — two of them would end the run"


def test_the_ride_is_still_wired_and_waits_on_its_own_march():
    """#1702: the approach branch survived the proof rewrite — and needed one fix.

    Both senders have to park the marches that existed before them, because that set is
    what tells the run's own march from another squad's rally afterwards. The attack send
    got it in the rewrite; the RIDE did not, so a ride's wait fell back to «the latest
    march we hold» — which on the first lap of a run is whatever else is out.
    """
    ride = lua_actions.golden_approach_send()
    assert "p.march_before" in ride, \
        "the ride does not park the marches before it — its wait is on somebody else's clock"
    assert "MarchTargetType.COLLECT" in ride, "the ride is not a gather order any more"
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    assert "IF approach == 1" in lines, "the approach branch is gone from the recipe"
    i = lines.index("IF approach == 1")
    tail = lines[i:i + 12]
    assert "TAP golden_approach_arm" in tail and "TAP golden_ride" in tail, \
        "the branch no longer plans or takes the ride"
    assert "TAP golden_eta" in tail, "a ride nobody times is a chain that never resumes"
    # …and the plan is still measured against the direct march, never taken blindly
    arm = lua_actions.golden_approach_arm()
    assert "p.why = 'short'" in arm and "p.why = 'no-mine'" in arm


def test_the_lap_of_the_map_is_harvested_where_it_ENDS():
    """#1702 regression: «not one golden zombie» over a warzone full of them.

    The map lap loads district after district and the client keeps what it has LOADED. The
    camera-onto-the-origin rule went in front of the first scan, so the run flew home
    BEFORE asking — and the entire catch of the lap had been evicted by the time it did.
    Live, from the panel's own button: a full lap, then `queued = 0`, then a FAIL, while
    the panel's own monster registry was holding four hundred.

    So the lap is harvested where it ends, and the queue — which only ever grows — is
    topped up again once the camera is on the origin.
    """
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    lap = lines.index("CALL scan_map")
    nxt = [i for i, w in enumerate(lines[lap:], lap)
           if w in ("TAP golden_scan", "TAP golden_look_from")]
    assert nxt and lines[nxt[0]] == "TAP golden_scan", \
        "the camera leaves before the lap's catch is taken — the queue comes back empty"
    look = lines.index("TAP golden_look_from")
    assert any(w == "TAP golden_scan" for w in lines[look:look + 8]), \
        "the queue is never topped up around the origin"
    # …and every lap of the chain does the same: take what is here, then move.
    loop = [i for i, w in enumerate(lines) if w == "TAP golden_look_from"]
    for i in loop:
        assert "TAP golden_scan" in lines[max(0, i - 3):i] or i == look, \
            "a camera move throws away what the client is holding right now"


def test_the_pick_takes_the_minimum_from_home_and_is_taken_again_once_more_is_known():
    """#1702: «выбрана НЕ ближайшая цель» — and the sort was never the problem.

    Run offline, against the real Lua of `golden_pick` with a made-up queue: the first
    pick of a run measures from the BASE and returns the smallest of them, cross-server
    arithmetic and all. What went wrong live is what was IN the queue — the client knows
    only the districts it has loaded, so the choice was the minimum over a partial map:
    500 tiles out, while a scan taken once the camera was on that target turned up one at
    484. So the recipe looks at its first choice, scans, and chooses again over the bigger
    queue — a second pick from the same origin can only be nearer.
    """
    import lupa
    rt = lupa.LuaRuntime()
    rt.execute("CS = {UnityEngine = {Debug = {LogError = function() end}}}")
    rt.execute("""
    DataCenter = {__lw_gold = {home = {x = 100, y = 100}, server = 1, used = {},
      targets = {{pid = 1, x = 130, y = 100, uuid = 11},
                 {pid = 2, x = 110, y = 100, uuid = 22},
                 {pid = 3, x = 150, y = 150, uuid = 33}}}}
    """)
    rt.execute(lua_actions.golden_pick())
    assert rt.eval("DataCenter.__lw_gold.cur.uuid") == 22, "the pick is not the nearest to home"
    assert rt.eval("DataCenter.__lw_gold.curfrom") == "home"
    assert rt.eval("DataCenter.__lw_gold.curdist") == 10
    # …and once a kill has happened the origin is that kill, not the base again.
    rt.execute("DataCenter.__lw_gold.anchor = {x = 150, y = 150}")
    rt.execute(lua_actions.golden_pick())
    assert rt.eval("DataCenter.__lw_gold.cur.uuid") == 33, "the chain went back to measuring from home"
    assert rt.eval("DataCenter.__lw_gold.curfrom") == "anchor"

    # …and the recipe picks TWICE: once off what is known, then again once the target's
    # own district has been scanned.
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    picks = [i for i, w in enumerate(lines) if w == "TAP golden_pick"]
    assert len(picks) >= 2, "the choice is never revisited after the district is loaded"
    first, second = picks[0], picks[1]
    between = lines[first:second]
    assert "TAP golden_look" in between and "TAP golden_scan" in between, \
        "the second pick reads the same queue as the first — it would choose the same"
    send = [i for i, w in enumerate(lines) if w == "TAP golden_send"]
    assert send and min(send) > second, "the run sends before it has re-picked"


def test_the_base_tile_is_solved_from_anywhere_on_the_map():
    """#1702: at five hundred tiles out the guess missed and the run lost its origin.

    The oracle answers whole tiles, so the two squared readings the guess is built from
    carry a rounding error worth several tiles at long range. A fixed ±3 sweep then found
    nothing, `p.home` stayed nil, and every pick fell back to asking the oracle per target
    — which still measures from the base, but says `origin=nil` in the log and cannot be
    compared with the chain's own arithmetic. Run offline against a fake oracle that
    rounds exactly as the game does.
    """
    import lupa
    for camera in ((894, 891), (566, 473), (10, 990)):
        rt = lupa.LuaRuntime()
        rt.execute("CS = {UnityEngine = {Vector2Int = function(x, y) return {x = x, y = y} end}}")
        rt.execute("""
        HOME = {x = 564, y = 468}
        SceneUtils = {TileDistanceToMyHome = function(pid)
          local x, y = math.floor(pid / 10000), pid %% 10000
          local dx, dy = x - HOME.x, y - HOME.y
          return math.floor(math.sqrt(dx * dx + dy * dy) + 0.5)
        end}
        WS = {CurTilePos = {x = %d, y = %d},
              TilePosToIndex = function(self, t) return t.x * 10000 + t.y end}
        """ % camera)
        rt.execute(lua_actions._GOLD_HOME + " RESULT = _goldhome(WS, 1)")
        found = rt.eval("RESULT")
        assert found is not None, f"no base tile found with the camera at {camera}"
        assert (found.x, found.y) == (564, 468), \
            f"the base came out at {(found.x, found.y)} with the camera at {camera}"


def test_a_zombie_sixty_tiles_from_the_base_beats_one_five_hundred_away():
    """#1702, the operator's own sighting: «ближайший монстр примерно (620,494)».

    Home is (564,468), so that one is 62 tiles out — against the 500-tile target the chain
    had chosen. Two halves to it, and both are pinned here.

    The arithmetic half, offline against the real Lua: a candidate at 62 tiles must win
    over one at 500, whatever order the queue happens to be in.
    """
    import lupa
    rt = lupa.LuaRuntime()
    rt.execute("CS = {UnityEngine = {Debug = {LogError = function() end}}}")
    rt.execute("""
    DataCenter = {__lw_gold = {home = {x = 564, y = 468}, server = 935, used = {},
      targets = {{pid = 1, x = 801, y = 908, uuid = 11},
                 {pid = 2, x = 620, y = 494, uuid = 22},
                 {pid = 3, x = 894, y = 891, uuid = 33}}}}
    """)
    rt.execute(lua_actions.golden_pick())
    assert rt.eval("DataCenter.__lw_gold.cur.uuid") == 22, \
        "the pick took a target 500 tiles out over one at 62"
    assert rt.eval("DataCenter.__lw_gold.curdist") == 62

    # The other half is what the queue CONTAINS: the client answers about the window it
    # has drawn — roughly sixty tiles — so the near ground has to be walked, not glanced
    # at from the base. Live, a camera move to the operator's tile turned up twelve
    # golden zombies within sixty tiles that no scan of the run had ever seen.
    sweep = lua_actions.golden_sweep_home()
    assert "GetMonsterListInArea" in sweep and "MoveToWorldPoint" in sweep, \
        "the near sweep does not move the camera and read at every stop"
    assert "DelayInvoke" in sweep, "the ring is walked by round trips, not by the game"
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    assert "TAP golden_ring" in lines, "nothing sweeps the ground around the base"
    ring = lines.index("TAP golden_ring")
    pick = min(i for i, w in enumerate(lines) if w == "TAP golden_pick")
    assert ring < pick, "the first pick is made before the near ground has been swept"
    assert any(w.startswith("READ_LUA") and " INTO swept" in w for w in lines[ring:pick]), \
        "the run picks while the sweep is still walking"


def test_a_squad_that_is_still_out_is_waited_for_before_the_first_send():
    """#1702: a fresh run has no march of its own parked, so the gate waves it through.

    Live twice in a row: the squad was out from the run before, the first send went out
    at once, the server refused it in silence, and after the second refusal the chain
    stopped — with the pick, the sweep and everything else working perfectly.
    """
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    out = [i for i, w in enumerate(lines) if w.startswith("READ_LUA") and " INTO squad_out" in w]
    assert out, "nothing asks whether the squad is already out"
    i = out[0]
    tail = lines[i:i + 4]
    assert "IF squad_out == 1" in tail and "TAP golden_eta" in tail, \
        "the answer is read and never acted on"
    first_send = min(j for j, w in enumerate(lines) if w in ("TAP golden_send", "TAP golden_home"))
    assert i < first_send, "the check comes after the send it is meant to hold back"
    assert lua_actions.golden_marching() in "\n".join(lines), \
        "the recipe's copy of the squad reading is not the module's"


def test_a_target_uuid_is_fetched_again_before_it_is_sent():
    """#1702: «<invalid c# object>» — the queue was holding dead references.

    A monster's uuid is a C# Int64 handed over by the enumerator; what a queue entry keeps
    is a reference to it. Measured live: the FIRST target of a run sends and marches, and
    the second one — picked from an entry made minutes earlier — printed
    `B=<invalid c# object>,<invalid c# object> uuid=<invalid c# object>` and its send never
    became a march. That is the whole of «the server refuses an attack from a mine»: the
    server was being sent nothing at all.

    It cannot be kept as a Lua number (nineteen digits), so the queue keeps the text and
    the live object is fetched again at the moment of the send.
    """
    scan = lua_actions.golden_scan()
    assert "key = tostring(uuid)" in scan, "the scan keeps no stable copy of the uuid"
    assert "math.floor(tile.x + 0.5)" in scan, \
        "the tile is stored as a C# field read, which dies with the enumerator"
    sweep = lua_actions.golden_sweep_home()
    assert "key = tostring(uuid)" in sweep, "the ring sweep keeps dead references"
    send = lua_actions.golden_send()
    assert "_freshuuid" in send, "the send uses the uuid the queue is holding"
    assert "dropped=stale" in send, \
        "a target the game no longer knows is still sent at — a wasted order and ten "\
        "seconds of waiting for a march that cannot come"
    assert "GetMonsterListInArea" in send, "nothing re-reads the target before the send"
    for check in (lua_actions.golden_here(), lua_actions.golden_gone()):
        assert "t.key or t.uuid" in check, \
            "a check compares against a reference that may have died"
    body, _ = _source(RECIPE)
    assert lua_actions.golden_here() in body and lua_actions.golden_gone() in body, \
        "the recipe's copies of the checks are older than the module's"


def test_a_squad_that_cannot_act_where_it_stands_is_walked_off_it():
    """#1702, the operator's rule of the game: DIRTY GROUND takes no orders.

    A squad standing on the fouled tiles the invasion leaves accepts neither an attack nor
    a move, and refuses in exactly the same silence as a dead target — so the chain used to
    count it against the «the client has gone deaf» streak and stop with a live squad, a
    live target and a working link.

    The reading is the client's own about OUR formation: an army that is there and a
    `canMarch` the game says is false. The answer is to take the squad off that ground and
    carry on from the base, counted apart and clearing the streak.
    """
    stuck = lua_actions.golden_stuck()
    assert "canMarch" in stuck and "totalSoldierNum" in stuck, \
        "the reading does not ask the game about our own squad"
    free = lua_actions.golden_unstick()
    assert "OnBackHome" in free, "nothing takes the squad off the ground"
    assert "p.misses = 0" in free, \
        "being stuck counts against the deaf-client streak — a live squad would end the run"
    assert "p.unstuck" in free and "p.unstuck" in lua_actions.golden_report(), \
        "the run does not say how often it had to free the squad"
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    assert stuck in "\n".join(lines), "the recipe's copy of the reading is not the module's"
    i = next(k for k, w in enumerate(lines) if w.startswith("READ_LUA") and " INTO stuck" in w)
    window = lines[i:i + 10]
    assert "IF stuck == 1" in window and "TAP golden_unstick" in window
    assert "ELSE" in window and "TAP golden_miss" in window, \
        "a refusal that is NOT the ground no longer counts as a miss at all"
    miss = lines.index("TAP golden_miss")
    assert miss > i, "the miss is counted before the ground is ruled out"


def test_the_queue_is_refreshed_while_the_squad_is_walking():
    """#1702: eighteen targets thrown away in one run, all of them from one snapshot.

    The ground near a base is farmed by everybody, so a list read once at the start is
    stale by the time the squad reaches the first of it. The march is minutes long and the
    coarse wait is already beating every three seconds — a scan on that beat costs a fifth
    of a second and the queue only grows.
    """
    body, _ = _source(RECIPE)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    far = next(i for i, w in enumerate(lines) if w.startswith("WHILE far == 1"))
    inside = lines[far:far + 10]
    assert "TAP golden_scan" in inside, \
        "the queue is not refreshed while the squad marches — it goes stale in flight"
    # …and the run is more patient about refusals than it was: three ended runs with a
    # live squad, a live link and a hundred targets left.
    defaults, _rest = engine.extract_defaults(RECIPE.read_text(encoding="utf-8"))
    assert defaults.get("miss_limit", 0) >= 6, \
        "a handful of dead targets in a row still ends the run"
    # …and a run may live long enough to spend a whole purse: a thousand stamina is a
    # hundred attacks, and every lap that drops a dead target or frees a stuck squad is a
    # lap too (#1702).
    assert any(w.startswith("WHILE go == 1 LIMIT") and int(w.rsplit(" ", 1)[-1]) >= 200
               for w in lines), "the chain is capped below what one purse buys"


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
