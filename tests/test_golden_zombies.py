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



def _chain():
    """The chain's lap AS IT RUNS — every `CALL golden_*` brick expanded in place.

    The hunt is four bricks now (#1702) and the ordering rules the tests below pin — the
    camera before the scan, the scan before the judgement, the check before the send —
    are rules about the ORDER THINGS HAPPEN IN, not about which file they live in. So the
    tests read the flattened lap: it is what the interpreter walks, and a brick that is
    reordered or dropped from the lap shows up here immediately.
    """
    body, _ = _source(RECIPE)
    out = []
    for line in body.splitlines():
        w = line.strip()
        if w.startswith("CALL golden_"):
            sub, _ = _source(_REPO_ROOT / "src" / "lastwar_bot" / "actions"
                             / (w.split()[1] + ".md"))
            out += [x for x in sub.splitlines()]
        else:
            out.append(line)
    text = "\n".join(out)
    # Comments are dropped from the LINE view on purpose: every ordering test below asks
    # «is there a scan within N steps of that camera move», and a paragraph of reasoning
    # between the two is not a step. The text view keeps them.
    return text, [x.strip() for x in out
                  if x.strip() and not x.strip().startswith("#")]


def test_both_recipes_parse_and_declare_what_they_take():
    body, args = _source(RECIPE)
    assert engine.parse_text(body), "the chain parsed to nothing"
    for name in ("squad", "radius", "scan", "limit", "march_wait"):
        assert name in args, f"the chain does not declare {name}"
    assert args["squad"] == 1, "the default squad must be the first slot"
    reading, _ = _source(READING)
    assert engine.parse_text(reading), "the reading parsed to nothing"


def test_every_press_the_chain_plays_is_in_the_catalogue():
    body, _lines = _chain()
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
    assert "GetOwnerFormationMarch" in launched, \
        "the proof does not ask OUR OWN formation what it is carrying"
    assert "GetOwnerMarches" not in launched, \
        "the proof counts any march of the account — a sibling squad confirms our order"
    assert "march_before" in launched, \
        "the proof counts marches rather than noticing a NEW one — another squad's rally "\
        "would answer for this attack"
    assert "stamina" not in launched and "p.cost" not in launched, \
        "the send proof is still priced off the purse"
    send = lua_actions.golden_send()
    assert "p.march_before" in send, "the send never writes down what was flying before it"
    body, _lines = _chain()
    assert launched in body, "the recipe's copy of the send proof is not the module's"


def test_an_energy_refill_in_the_middle_does_not_lose_an_attack():
    """The «purse went down» reading is gone from every gate the chain branches on."""
    body, _lines = _chain()
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
    _body, lines = _brick("golden_send_the_squad")
    assert "TAP golden_miss" in lines, "a refused send has no way out but ending the run"
    i = lines.index("TAP golden_miss")
    tail = lines[i:i + 10]
    assert any(w.startswith("IF misses >") for w in tail), \
        "misses are written down and never acted on — a deaf client would spin for ever"
    brick = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
             / "golden_send_the_squad.md").read_text(encoding="utf-8")
    assert "ARGS miss_limit" in brick, \
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
    body, lines = _chain()
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
    body, lines = _chain()
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
            assert any(w in before for w in ("TAP golden_look_from", "TAP golden_look",
                                             "TAP golden_refresh")), \
                "the scan the pick reads was taken from somewhere else"
    look = lua_actions.golden_look_from()
    assert "_origin(p)" in look, \
        "the camera does not follow the same origin the pick measures from"


def test_the_chain_does_not_hold_the_panel_up():
    """#1702: a run that lasts a march may not be the reason a timer waited."""
    text = RECIPE.read_text(encoding="utf-8")
    assert engine.declares_detach(text), "the chain does not declare DETACH"
    assert engine.action_detached("attack_golden_zombies")


def test_the_last_march_of_a_run_brings_the_squad_home():
    body, _lines = _chain()
    assert "DataCenter.__lw_gold_back = 1" in body, \
        "nothing ever raises «come home» — a run would leave the squad on the map"
    assert "DataCenter.__lw_gold_back = 0" in body, \
        "the chain never switches «come home» off — every march would walk back"
    last = lua_actions.golden_last_march()
    assert "cost * 2" in last, "the last march is not worked out from what is left"


def test_the_recipe_carries_the_CURRENT_copy_of_the_proofs():
    """The DSL has no include, so the recipe embeds the text — and it goes stale (#1702)."""
    body, _lines = _chain()
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
DataCenter = DataCenter or {}
DataCenter.__lw_mon_prefab = nil
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
    body, _lines = _chain()
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
    body, _lines = _chain()
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
    body, lines = _chain()
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
    body, lines = _chain()
    gone = [i for i, w in enumerate(lines) if w.startswith("READ_LUA") and " INTO gone" in w]
    assert gone, "nothing checks whether the zombie went"
    first = min(gone)
    before = lines[:first]
    assert "TAP golden_scan" in before and "TAP golden_look_from" in before, \
        "the kill is judged before the client has been asked about that district"
    kill = lines.index("TAP golden_kill")
    assert kill > first, "the kill is counted before it is checked"


def test_a_dead_target_is_dropped_before_a_send_is_wasted_on_it():
    """#1702: the client's list is a snapshot; the map has moved on since the lap.

    The check survives, and what changed is what it is allowed to conclude. It used to be
    asked with the camera flown onto the target, and that flight was the proof the answer
    meant anything; the flight is gone (the registry is reaped by every scan instead), so
    the proof moved INTO the check — an unread district can no longer say «gone».
    """
    # The check and the send live in different bricks now (#1702), which is the point of
    # the split: the target is armed and proved by `golden_choose_a_target`, and only a
    # brick that never chooses anything is allowed to give an order.
    _body, choose = _brick("golden_choose_a_target")
    _body, send = _brick("golden_send_the_squad")
    assert "TAP golden_drop_target" in choose
    # The lenient «is it on the map» reading moved OUT of the chain and the STRICT one
    # took its place (#1702): before a march is spent, «the client cannot name that uuid»
    # is reason enough to choose again. `golden_here` stays as the module's careful
    # reading for anything that touches the REGISTRY, where the trade runs the other way.
    here = [i for i, w in enumerate(choose)
            if w.startswith("READ_LUA") and " INTO target_live" in w]
    assert here, "nothing asks whether the armed target is still on the map"
    i = min(here)
    _body, judge = _brick("golden_judge_the_kill")
    assert "TAP golden_scan" in judge or "TAP golden_scan" in choose[max(0, i - 12):i], \
        "the target is checked without the client having been asked at all"
    assert not any(w in ("TAP golden_send", "TAP golden_home") for w in choose), \
        "the brick that chooses a target also gives orders"
    assert any(w in ("TAP golden_send", "TAP golden_home") for w in send), \
        "nothing sends the squad at all"
    drop = lua_actions.golden_drop_target()
    assert "p.used" in drop and "p.misses" not in drop, \
        "dropping a dead target counts as a refused order — two of them would end the run"
    check = lua_actions.golden_here()
    assert "HasPointInfo" in check, \
        "the check drops a target without asking whether that district was ever read"
    assert "if not ok then return 1 end" in check, \
        "a read that failed reads as «the zombie is gone» — the row could never come back"


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
    body, lines = _chain()
    assert "IF approach == 1" in lines, "the approach branch is gone from the recipe"
    i = lines.index("IF approach == 1")
    # Sixteen, not twelve: the branch fetches the target's district itself now (#1702) —
    # the chain stopped flying the camera per kill, and the mine hunt still needs it.
    tail = lines[i:i + 20]
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
    body, lines = _chain()
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


def test_the_pick_takes_the_minimum_from_the_origin_and_is_taken_again_later():
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
    # …AND THE ORIGIN AFTER A KILL IS ASKED, NOT ASSUMED (#1702). An anchor is where
    # the run last SENT a squad; whether the next march starts there depends on whether
    # the squad is still standing on it. Both readings were measured live: the redeploy
    # call works at a squad that has landed, and a squad that has killed is normally
    # home again by the time the next order can be given — every march the server priced
    # after a kill was priced from the BASE. So an anchor with nothing standing on it is
    # not an origin, and a chain that measured from one drifted outwards, 46 tiles from
    # home to 119 over six kills.
    rt.execute("DataCenter.__lw_gold.anchor = {x = 150, y = 150}")
    rt.execute("LuaEntry = {Player = {uid = 1, allianceId = 2}} "
               "DataCenter.WorldMarchDataManager = "
               "{GetOwnerFormationMarch = function() return nil end}")
    rt.execute(lua_actions.golden_pick())
    assert rt.eval("DataCenter.__lw_gold.cur.uuid") == 22, \
        "the pick measures from a tile the squad walked away from"
    assert rt.eval("DataCenter.__lw_gold.curfrom") == "home"

    # …and from the anchor the moment the squad IS still standing on it, because then
    # the send re-aims it where it is and the hop really is the hop.
    rt.execute("DataCenter.__lw_gold.anchor = {x = 148, y = 148} "
               "DataCenter.__lw_gold.formation = '77' "
               "DataCenter.WorldMarchDataManager = {GetOwnerFormationMarch = "
               "function() return {teamUuid = '0', status = 'STATION: 0', endTime = 0} "
               "end}")
    rt.execute(lua_actions.golden_pick())
    assert rt.eval("DataCenter.__lw_gold.cur.uuid") == 33, \
        "a squad standing where it killed is walked home instead of hopping"
    assert rt.eval("DataCenter.__lw_gold.curfrom") == "anchor"

    # …and the recipe revisits the choice only when the ground has been PROVEN stale
    # (#1702). It used to re-pick after every kill, behind a camera flight to the
    # candidate; the queue is reaped by every scan now, so what it holds is what the map
    # last said, and the re-pick belongs behind the refresh threshold and nowhere else.
    body, lines = _chain()
    pick = lines.index("TAP golden_pick")
    loop = next(i for i, w in enumerate(lines) if w.startswith("WHILE looking == 1 LIMIT"))
    assert loop < pick, "the pick is not inside the choosing loop — one stale row ends the lap"
    tries = int(lines[loop].rsplit(" ", 1)[-1])
    assert 3 <= tries <= 20, "the chain either gives up on one stale row or spins on them"
    before = lines[:loop]
    assert "IF needs_refresh == 1" in before and "TAP golden_refresh" in before, \
        "the redraw is not behind the staleness threshold — it would re-fly every kill"
    send = [i for i, w in enumerate(lines) if w == "TAP golden_send"]
    assert send and min(send) > loop, "the run sends before it has chosen"


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

    # The other half is what the queue CONTAINS, and the answer changed with the model
    # (#1702). The ring of eighteen camera stops around the base is GONE: one brisk lap
    # is the registry, and what keeps the near ground honest afterwards is that every
    # scan reaps what the map was read at and did not return.
    assert not hasattr(lua_actions, "golden_sweep_home"), \
        "the ring sweep is back — a second walk of the ground the lap already gave"
    body, lines = _chain()
    assert "TAP golden_ring" not in lines, "the recipe still rides the ring around the base"
    assert not any(" INTO swept" in w for w in lines), \
        "the run still waits out a sweep before it may choose"
    scan = lua_actions.golden_scan()
    assert "_goldreap" in scan, "a scan only adds — a killed zombie stays in the queue for ever"


def test_a_squad_that_is_still_out_is_waited_for_before_the_first_send():
    """#1702: a fresh run has no march of its own parked, so the gate waves it through.

    Live twice in a row: the squad was out from the run before, the first send went out
    at once, the server refused it in silence, and after the second refusal the chain
    stopped — with the pick, the sweep and everything else working perfectly.
    """
    body, lines = _chain()
    out = [i for i, w in enumerate(lines) if w.startswith("READ_LUA") and " INTO squad_out" in w]
    assert out, "nothing asks whether the squad is already out"
    i = out[0]
    tail = lines[i:i + 4]
    assert "IF squad_out == 1" in tail and "TAP golden_eta" in tail, \
        "the answer is read and never acted on"
    # The send lives in its own brick now (#1702), so «before the first send» means
    # «before the loop that calls it», which is stricter and easier to read.
    loop = next(j for j, w in enumerate(lines) if w.startswith("WHILE go == 1"))
    assert i < loop, "the check comes after the lap that would send"
    _own, own_lines = _brick("attack_golden_zombies")
    assert not any(w in ("TAP golden_send", "TAP golden_home") for w in own_lines), \
        "the chain gives an order itself instead of through the send brick"
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
    send = lua_actions.golden_send()
    assert "_freshuuid" in send, "the send uses the uuid the queue is holding"
    assert "dropped=stale" in send, \
        "a target the game no longer knows is still sent at — a wasted order and ten "\
        "seconds of waiting for a march that cannot come"
    assert "GetMonsterListInArea" in send, "nothing re-reads the target before the send"
    for check in (lua_actions.golden_here(), lua_actions.golden_gone()):
        assert "t.key or t.uuid" in check, \
            "a check compares against a reference that may have died"
    body, _lines = _chain()
    assert lua_actions.golden_target_live() in body and lua_actions.golden_gone() in body, \
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
    assert "IsFree()" in stuck and "totalSoldierNum" in stuck, \
        "the reading does not ask the game about our own squad"
    free = lua_actions.golden_unstick()
    assert "OnBackHome" in free, "nothing takes the squad off the ground"
    assert "p.misses = 0" in free, \
        "being stuck counts against the deaf-client streak — a live squad would end the run"
    assert "p.unstuck" in free and "p.unstuck" in lua_actions.golden_report(), \
        "the run does not say how often it had to free the squad"
    # THE READING MOVED IN FRONT OF THE SEND (#1702), and the branch that used to run
    # AFTER one is gone. Dirty ground, a mine being gathered and a march already out are
    # the same fact to a caller — the game will not take an order — so they are asked
    # once, before the order, by `golden_squad_free`. Asking again afterwards was worse
    # than redundant: `canMarch == false` after a send is what an ACCEPTED order looks
    # like, and reading it as dirt is how a squad already walking got re-routed.
    _body, lines = _brick("golden_send_the_squad")
    assert not any(" INTO stuck" in w for w in lines), \
        "the post-send «is it stuck» branch is back"
    i = next(k for k, w in enumerate(lines) if " INTO squad_free" in w)
    window = lines[i:i + 4]
    assert "IF squad_free == 0" in window and "TAP golden_unstick" in window
    send = min(k for k, w in enumerate(lines)
               if w in ("TAP golden_send", "TAP golden_home", "TAP golden_ride"))
    assert i < send, "the ground is ruled out only after the order has been refused"


def test_the_queue_is_refreshed_while_the_squad_is_walking():
    """#1702: eighteen targets thrown away in one run, all of them from one snapshot.

    The ground near a base is farmed by everybody, so a list read once at the start is
    stale by the time the squad reaches the first of it. The march is minutes long and the
    coarse wait is already beating every three seconds — a scan on that beat costs a fifth
    of a second and the queue only grows.
    """
    body, lines = _chain()
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


# ---------------------------------------------------------------------------
# The registry: one lap fills it, and it loses a row only where the map was read
# ---------------------------------------------------------------------------

def _reaper(known, camera=(100, 100)):
    """A lupa runtime with `_goldreap` loaded and a fake `HasPointInfo` oracle.

    `known` is the set of tile ids the client is pretending to hold; anything else makes
    the oracle answer `false`, which is «the client has that district and there is nothing
    of ours in it» — the opposite of «nobody looked», and the two must not be confused.
    """
    import lupa
    rt = lupa.LuaRuntime()
    rt.execute("KNOWN = {}")
    for pid in known:
        rt.execute("KNOWN[%d] = true" % pid)
    rt.execute("WS = {HasPointInfo = function(self, pid) return KNOWN[pid] == true end}")
    rt.execute("CAM = {x = %d, y = %d}" % camera)
    # The helper is a `local function`, so it dies with its chunk — park it globally
    # in the SAME chunk that defines it.
    rt.execute(lua_actions._GOLD_REAP + " REAP = _goldreap")
    return rt


def _reap(rt, targets, present):
    rt.execute("P = {targets = {}}")
    for t in targets:
        rt.execute("P.targets[#P.targets + 1] = {pid = %d, x = %d, y = %d}" % t)
    rt.execute("PRESENT = {}")
    for pid in present:
        rt.execute("PRESENT['%d'] = true" % pid)
    rt.execute("GONE = REAP(P, WS, PRESENT, CAM.x, CAM.y)")
    left = []
    n = int(rt.eval("#P.targets"))
    for i in range(1, n + 1):
        left.append(int(rt.eval("P.targets[%d].pid" % i)))
    return int(rt.eval("GONE")), left


def test_a_row_leaves_the_registry_only_where_the_map_was_actually_read():
    """#1702, and it is THE_LIST_RULE of the secret tasks (#1272) word for word.

    A queued zombie the scan did not return may mean two completely different things, and
    the whole point of the registry is that they are never confused:

      * the client HOLDS that district and did not return it — it is dead, drop it;
      * the client does not hold it, or it is outside the window the client draws around
        the camera — nobody looked, and the row stays.

    A row wrongly kept costs one refused send. A row wrongly dropped is a zombie the chain
    can never come back to, because nothing re-adds what the scan cannot see.
    """
    # 1 is standing there, 2 is dead, 3 sits in a district the client never fetched, and
    # 4 is dead too — but four hundred tiles away, where the client draws nothing.
    rt = _reaper(known={1, 2, 4})
    gone, left = _reap(rt,
                       targets=[(1, 100, 100), (2, 105, 100), (3, 105, 101), (4, 400, 400)],
                       present=[1])
    assert gone == 1, f"the reaping took {gone} rows, not the one the map disowned"
    assert left == [1, 3, 4], f"the registry came back as {left}"

    # …and the counters are what the threshold reads, so they accumulate across scans.
    assert int(rt.eval("P.vanished")) == 1
    assert int(rt.eval("P.since_refresh")) == 1


def test_a_district_nobody_read_never_empties_the_registry():
    """The failure mode this rule exists to stop: a scan that saw nothing wipes the lot.

    An oracle that says «I hold no district at all» is exactly what a client looks like
    while it is loading, changing scene or drawing somewhere else. Under the old
    add-only queue that was harmless; under a reaping one it would be a run that throws
    away the whole lap and reports «not one golden zombie on the map».
    """
    rt = _reaper(known=set())
    gone, left = _reap(rt,
                       targets=[(1, 100, 100), (2, 101, 100), (3, 102, 100)],
                       present=[])
    assert gone == 0, "an unread map emptied the registry"
    assert left == [1, 2, 3]

    # …and the same read against a client that DOES hold the ground says the opposite.
    rt = _reaper(known={1, 2, 3})
    gone, left = _reap(rt, targets=[(1, 100, 100), (2, 101, 100), (3, 102, 100)], present=[])
    assert gone == 3 and left == [], "the map said they are gone and the rows stayed"


def test_the_scan_skips_the_reaping_when_the_read_itself_failed():
    """An empty answer from a read that never happened is «we did not look» (#1702)."""
    scan = lua_actions.golden_scan()
    assert "local read_ok = pcall(function()" in scan, \
        "the scan does not know whether its own read answered"
    assert "if read_ok then" in scan, \
        "the reaping runs on a read that may never have happened"
    assert "present[tostring(pid)] = true" in scan, \
        "the scan records nothing about what it actually saw"


def test_the_expensive_refresh_waits_for_two_to_five_disappearances():
    """The operator's rule: «зумить не нужно после каждого раза, только если 2–5 пропали».

    The camera stands on the kills, so the ordinary scan after each one is a current
    picture nearly always. The redraw is the expensive half and it is bought only once the
    picture has been PROVEN stale — never on a clock, and never per kill.
    """
    import lupa
    assert 2 <= lua_actions.GOLDEN_REFRESH_AFTER <= 5, \
        "the default threshold is outside the band the operator asked for"
    defaults, _rest = engine.extract_defaults(RECIPE.read_text(encoding="utf-8"))
    assert 2 <= defaults["refresh_after"] <= 5, \
        "the recipe's own default is outside the 2–5 band"

    gate = lua_actions.golden_needs_refresh()
    for since, limit, want in ((0, 3, 0), (2, 3, 0), (3, 3, 1), (9, 3, 1),
                               (2, 2, 1), (5, 5, 1), (9, 0, 0)):
        rt = lupa.LuaRuntime()
        rt.execute("DataCenter = {__lw_gold = {since_refresh = %d}, "
                   "__lw_gold_refresh_after = %d}" % (since, limit))
        got = int(rt.eval(gate))
        assert got == want, \
            f"{since} gone against a threshold of {limit} answered {got}, wanted {want}"

    # …and the refresh puts the counter back, so the next one is a whole threshold away.
    refresh = lua_actions.golden_refresh()
    assert "p.since_refresh = 0" in refresh, \
        "the counter is never cleared — every scan after the first refresh would refresh again"
    # And it DWELLS, because that is the only thing that loads a district (#1702). One
    # look does not: standing 488 tiles out after a lap, the client said «0 golden zombies
    # within 300 tiles of the base», and thirteen camera stops turned that into «17, the
    # nearest 14 tiles away». So the refresh is a short ring on the game's own timer —
    # and a short one: fewer stops than the sweep it replaced, around the ORIGIN of the
    # next pick rather than around the base for its own sake.
    assert "MoveToWorldPoint" in refresh and "GetMonsterListInArea" in refresh, \
        "the refresh does not move the camera and read at every stop — it loads nothing"
    assert "DelayInvoke" in refresh, "the ring is walked by round trips, not by the game"
    # …AROUND THE LAST KILL, which is where the next march starts from (#1702). This
    # read HOME for a day, on the measured grounds that a landed army could not be
    # redeployed and every kill was therefore a round trip from the base. That was true
    # of `SendCreateMarchMessage` and not of the game: `SendChangeMarchToServer` re-aims
    # a squad standing on the tile it cleared, live, so the ground worth loading is the
    # ground around the squad again.
    assert "_origin(p)" in refresh, \
        "the refresh is aimed away from where the next march actually starts"
    assert lua_actions.GOLDEN_REFRESH_STOPS + 1 <= 12, \
        "the refresh is as long a walk as the ring it replaced"
    assert 6.0 <= lua_actions.golden_refresh_seconds() <= 12.0, \
        "the refresh either cannot finish or costs more than the sweep it replaced"

    # …and the recipe WAITS for the ring instead of guessing how long it takes.
    body, lines = _chain()
    for i, w in enumerate(lines):
        if w != "TAP golden_refresh":
            continue
        after = lines[i + 1:i + 6]
        assert any(" INTO refreshed" in x for x in after), \
            "a refresh nobody waits for is a scan taken while the camera is still walking"


def test_the_map_is_walked_ONCE_and_never_again():
    """«Беглого просмотра карты достаточно… не нужно потом второй раз ходить» (#1702).

    One lap fills the registry. What used to follow it — a second walk of eighteen camera
    stops in rings around the base, and a flight to the candidate before every single kill
    — is gone, and the reaping is what replaced both.
    """
    body, lines = _chain()
    # TWICE, AND THE SECOND ONE IS THE DROUGHT'S (#1702). The rule this test exists for
    # is «not once per kill»: what it forbade was the ring of eighteen camera stops and
    # the flight before every attack. A sweep goes stale, though — live, after three
    # empty pauses the queue's 139 far rows were every one of them a ghost — so a pause
    # that has already waited four and a half minutes may walk the map again.
    assert lines.count("CALL scan_map") <= 2, \
        "the recipe walks the whole map more than the run and its droughts need"
    assert "INTO drought" in body, \
        "the second sweep is not gated on the ground having stayed empty"
    assert not any(w.startswith("SWEEP_MAP") for w in lines), \
        "the recipe laps the map itself, on top of the one lap it calls for"
    lap = lines.index("CALL scan_map")
    loop = next(i for i, w in enumerate(lines) if w.startswith("WHILE go == 1"))
    assert lap < loop, "the lap is inside the chain — it would run once per kill"
    assert "TAP golden_ring" not in lines and "TAP golden_refresh" in lines, \
        "the ring is still there, or nothing replaced it"
    # The chain's own camera work: the origin of the next pick, and the ride's district.
    # Not the candidate, and not on every lap.
    body_after = lines[loop:]
    assert body_after.count("TAP golden_look") <= 1, \
        "the chain still flies to its candidate on every kill"


# ---------------------------------------------------------------------------
# The chain is four bricks, and the three faults the operator named (#1702)
# ---------------------------------------------------------------------------

BRICKS = ("golden_wait_for_the_march", "golden_judge_the_kill",
          "golden_choose_a_target", "golden_send_the_squad")


def _brick(name):
    path = _REPO_ROOT / "src" / "lastwar_bot" / "actions" / (name + ".md")
    body, _ = _source(path)
    return body, [line.strip() for line in body.splitlines()
                  if line.strip() and not line.strip().startswith("#")]


def test_the_chain_is_four_bricks_each_runnable_on_its_own():
    """The operator's method, and the reason for it: «тестировать ЧАСТИ, а не всё в одном
    цикле за раз, иначе любой небольшой сбой — и мы зависаем».

    Each brick is a scenario in its own right, so a hunt that stumbles is debugged one
    press at a time. The chain only assembles them, and it assembles them in the order of
    the facts: nothing is chosen while the squad is still walking, nothing is judged
    before the march has landed, nothing is sent at a target that has not been checked.
    """
    body, lines = _brick("attack_golden_zombies")
    loop = next(i for i, w in enumerate(lines) if w.startswith("WHILE go == 1"))
    calls = [w.split()[1] for w in lines[loop:] if w.startswith("CALL ")]
    assert calls == list(BRICKS), f"the chain's lap is {calls}"
    for i, w in enumerate(lines[loop:], loop):
        assert not w.startswith("TAP "), \
            f"the chain still presses {w!r} itself instead of through a brick"
    for name in BRICKS:
        brick_body, brick_lines = _brick(name)
        assert engine.parse_text(brick_body), f"{name} parsed to nothing"
        assert brick_lines, f"{name} is empty"
        assert not any(w.startswith("CALL " + name) for w in brick_lines), \
            f"{name} calls itself"


def test_no_order_is_given_to_a_squad_that_cannot_take_one():
    """«Залипание на шахте», and the invariant that ends it (#1702).

    Measured live on the chosen squad the moment after a ride landed:

        squad=2 state=1 canMarch=false soldiers=2631
        marches=2   m0 endTime=…452468   m1 endTime=…929588   now=…393277

    — the second march is **109 minutes** out. That is a mine being gathered, and every
    attack sent into that window is refused in silence. The old chain proved it the
    expensive way: ten seconds of launch polling, a target written off, and the next one
    tried, for as long as the run lasted.

    So the send brick asks first, and a squad that cannot march is RECALLED rather than
    shouted at.
    """
    _body, lines = _brick("golden_send_the_squad")
    free = lines.index(next(w for w in lines if " INTO squad_free" in w))
    send = min(i for i, w in enumerate(lines)
               if w in ("TAP golden_send", "TAP golden_home", "TAP golden_ride"))
    assert free < send, "the squad is ordered about before anybody asks whether it can move"
    gate = lines[free:free + 4]
    assert "IF squad_free == 0" in gate, "the reading is taken and not acted on"
    assert "TAP golden_unstick" in gate, "a squad that cannot march is not recalled"

    # …and the reading itself is the client's own answer about our own formation.
    expr = lua_actions.golden_squad_free()
    assert "IsFree()" in expr and "tonumber(f.state)" in expr and "p.formation" in expr, \
        "the gate does not ask the game's own idea of a free squad"
    assert "canMarch" not in expr, \
        "the gate is back on canMarch, which a headless session never sees recomputed"
    import lupa

    def ask(state=0, idle=True, soldiers=100):
        rt = lupa.LuaRuntime()
        rt.execute("DataCenter = {__lw_gold = {formation = '77'}, "
                   "ArmyFormationDataManager = {ArmyFormationList = "
                   "{{uuid = '77', state = %d, totalSoldierNum = %d, "
                   "IsFree = function() return %s end}}}}"
                   % (state, soldiers, "true" if idle else "false"))
        return int(rt.eval(expr))

    assert ask() == 1
    assert ask(state=1) == 0, "a marching squad reads as free"
    assert ask(idle=False) == 0, "the game says not idle and the gate sends anyway"
    # «ОТРЯД ЗАНЯТ, НО ЭТО НЕ ТАК» (#1702) — the reading that started this, live, on a
    # squad standing at home with a full army:
    #
    #     squad=2 state=0 free=1 soldiers=2631 status=- march=- team=0
    #     squad2 state=0 canMarch=false soldiers=2631        (what the old gate asked)
    #
    # `canMarch` is recomputed by the real dispatch render and by nothing else, so a
    # headless session reads whatever it was left at — false, for ever, on every squad.
    rt = lupa.LuaRuntime()
    rt.execute("DataCenter = {__lw_gold = {formation = '77'}, "
               "ArmyFormationDataManager = {ArmyFormationList = "
               "{{uuid = '77', state = 0, totalSoldierNum = 2631, canMarch = false, "
               "IsFree = function() return true end}}}}")
    assert int(rt.eval(expr)) == 1, \
        "a squad standing at home with 2631 soldiers still reads as busy"
    # «CANNOT MARCH» IS TWO FACTS (#1702). Measured live on a client that had just
    # restarted: `squad3 state=0 canMarch=false soldiers=0` — a squad standing AT HOME,
    # free, whose army the client had never fetched. Reading that as «busy» waits two
    # minutes and stops the hunt on a perfectly good squad.
    assert ask(soldiers=0) == -2, \
        "a squad whose army the client has forgotten reads as busy — the hunt would wait it out"
    rt = lupa.LuaRuntime()          # …and a squad nobody can find is «ask again», not «no»
    rt.execute("DataCenter = {__lw_gold = {formation = '77'}, "
               "ArmyFormationDataManager = {ArmyFormationList = {}}}")
    assert int(rt.eval(expr)) == -1, "an unreadable squad reads as a refusal"

    # …and the wait brick acts on the difference rather than lumping them together.
    _body, wait = _brick("golden_wait_for_the_march")
    assert "IF squad_free == -2" in wait and "CALL fill_empty_squads" in wait, \
        "an army the client has forgotten is waited out instead of asked for"


def test_one_ride_that_ends_in_a_gather_switches_the_ride_off_for_the_run():
    """One such ride is a mistake; two would be a policy (#1702).

    A ride is a GATHER order. If the squad comes back «cannot march» after it lands, the
    ride has parked the hunt for as long as the mine takes — so the fuse blows, the squad
    is recalled, and the rest of the run is plain attack marches. The person's own setting
    is untouched: this is a fuse inside one run, not a preference being overridden.
    """
    body, lines = _brick("golden_send_the_squad")
    ride = lines.index("TAP golden_ride")
    # The window is wider than it was: the ride's own wait now asks, on every beat,
    # whether the zombie it is riding to is still there (#1702) — the operator watched
    # a ride land on a mine for a target somebody else had killed on the way.
    tail = lines[ride:ride + 30]
    assert any(" INTO squad_free" in w for w in tail), \
        "nothing asks whether the ride ended in a gather"
    assert "TAP golden_no_ride" in tail, "a ride that parks the squad may happen again"
    assert "TAP golden_unstick" in tail, "the squad is left working the mine"

    # …and the planner honours the fuse, so no branch in the recipe has to.
    import lupa
    arm = lua_actions.golden_approach_arm()
    rt = lupa.LuaRuntime()
    rt.execute("CS = {UnityEngine = {Debug = {LogError = function() end}}}")
    rt.execute("DataCenter = {__lw_gold = {no_ride = 1, cur = {pid = 1, x = 1, y = 1}}}")
    rt.execute(arm)
    assert rt.eval("DataCenter.__lw_gold.approach") is None, \
        "the planner still plans a ride after the fuse has blown"
    assert rt.eval("DataCenter.__lw_gold.why") == "no-ride"


def test_an_accepted_order_is_never_written_off_as_a_refusal():
    """«Меняет маршрут, когда уже идёт на зомби» — and it was the PROOF that was wrong.

    The march list belongs to the client, and the client lists a march when it gets round
    to it. A send that was accepted but not yet listed read as a refusal, so the chain
    wrote the target off and ordered the squad somewhere else — re-routing a squad that
    was already walking. The squad going busy is the same proof, and it is instant: the
    chain never sends unless the squad is free, so «busy now» can only be the order we
    just gave.
    """
    import lupa
    proof = lua_actions.golden_launched()
    assert "IsFree()" in proof, "the proof still waits on the client's own bookkeeping"
    assert "canMarch" not in proof, "the proof is back on a flag nothing recomputes"

    def answer(own_march, free, team="0"):
        rt = lupa.LuaRuntime()
        rt.execute("LuaEntry = {Player = {uid = 1, allianceId = 2}} "
                   "DataCenter = {__lw_gold = {pending = 1, formation = '77', "
                   "march_before = {}}, WorldMarchDataManager = "
                   "{GetOwnerFormationMarch = function() return %s end}, "
                   "ArmyFormationDataManager = {ArmyFormationList = "
                   "{{uuid = '77', state = %d, IsFree = function() return %s end}}}}"
                   % ("{uuid = 'new', teamUuid = '%s'}" % team if own_march else "nil",
                      0 if free else 1, "true" if free else "false"))
        return int(rt.eval(proof))

    assert answer(True, True) == 1, "our own squad's new march is not proof enough"
    assert answer(False, False) == 1, \
        "a squad that has gone busy still reads as a send nobody received"
    assert answer(False, True) == 0, \
        "a squad that is free with no march reads as a launch — that is a refusal"
    # A BANNER IS NOT OUR ORDER (#1702). The auto-join puts our squad in somebody's rally
    # and the march it gets carries `endTime = 0` — exactly what a phantom of our own
    # carries. The teamUuid is what tells them apart, and without it the four-second
    # check confirms an attack that was refused.
    assert answer(True, True, team="1000000000000000001") == 0, \
        "a squad standing in a rally reads as the attack we just ordered"

    # …and the branch that used to fire after a failed send is gone, because it asked the
    # same question with the opposite meaning.
    body, lines = _brick("golden_send_the_squad")
    assert not any(" INTO stuck" in w for w in lines), \
        "the post-send «is it stuck» branch is back — it reads an accepted order as dirt"


def test_the_gap_after_an_attack_is_kept_short_on_purpose():
    """«Медлительность после завершения атаки» — measured, then spent down (#1702).

    From `arrived = 1` to the next order leaving: **9 seconds median** over the old
    chain's last laps (8, 9, 9, 10, 10, 10), and 3–4 once the per-kill re-aim went. What
    is left is polls, and they are pinned here so nobody quietly puts a second back.
    """
    _body, judge = _brick("golden_judge_the_kill")
    settle = judge.index("WAIT 0.8")
    assert judge[settle - 1] == "IF looked_moved == 1", \
        "the settle is paid on every lap instead of only when the camera really flew"
    _body, send = _brick("golden_send_the_squad")
    assert "WAIT 0.4" in send, "the launch proof is polled coarsely on the hot path"
    # THE PATIENCE CAME DOWN TOO, and deliberately (#1702). The proof is instant when the
    # order was taken — the squad goes busy the moment the game accepts it — so the whole
    # of this poll is time spent on orders that were REFUSED, and live half the sends of a
    # run were refusals at zombies somebody else had already killed. Six seconds is still
    # far longer than the server takes to answer; what it is not is ten seconds of
    # patience that only ever pays out on failure.
    poll = next(w for w in send if w.startswith("WHILE launched == 0 LIMIT"))
    beats = int(poll.rsplit(" ", 1)[-1])
    assert 5.0 <= beats * 0.4 <= 7.0, \
        "the launch proof waits either less than a server round trip or a refusal's worth"
    assert "IsFree()" in lua_actions.golden_launched(), \
        "the patience was cut without the instant half of the proof to justify it"

    # …and the ride's camera flight is bought only when the sums ask for it.
    look = send.index("TAP golden_look")
    assert any(w.startswith("IF needs_district ==") for w in send[max(0, look - 3):look]), \
        "the hunt flies to its candidate on every lap again — it costs three seconds a kill"


def test_every_recipe_carries_the_modules_copy_of_every_shared_expression():
    """The DSL has no include, so a `READ_LUA` line is a COPY, and copies go stale (#1702).

    It has happened twice, and both times it looked like a bug in the chain rather than a
    line of Lua that had been corrected somewhere else. The mapping lives in
    `tools/lib/golden_sync.py`; this is the half that fails when a copy has drifted.

        python3 tools/lib/golden_sync.py --write
    """
    sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import golden_sync

    stale = []
    for name in golden_sync.RECIPES:
        path = _REPO_ROOT / "src" / "lastwar_bot" / "actions" / (name + ".md")
        if not path.exists():
            continue
        stale += [(name, line, var)
                  for line, var in golden_sync.drift(path.read_text(encoding="utf-8"),
                                                     name)]
    assert not stale, \
        "stale copies (run tools/lib/golden_sync.py --write): %r" % (stale,)


def test_the_hunt_never_waits_out_a_march_that_is_not_its_own():
    """The other half of «залипание на шахте», and it is a WAIT rather than a send (#1702).

    Measured live on the chosen squad: two marches out, the second one's own clock **109
    minutes** away — a mine being gathered. The hunt's own hops are seconds and its
    longest ride is a minute, so a clock that far out is never this chain's march. The old
    wait sat in front of it for as long as `march_wait` allowed, doing nothing, and that
    reads from outside exactly like a hung bot.
    """
    import lupa
    assert 60 <= lua_actions.GOLDEN_WAIT_CEILING <= 300, \
        "the ceiling is either shorter than a legitimate ride or long enough to hang on"
    left = lua_actions.golden_eta_left()
    for parked, now, want in ((None, 1000, -1), (61000, 1000, 60), (1000, 61000, -60)):
        rt = lupa.LuaRuntime()
        rt.execute("DataCenter = {__lw_gold = {%s}} "
                   "UITimeManager = {Instance = {GetServerTime = function() return %d end}}"
                   % ("" if parked is None else ("eta_ms = %d" % parked), now))
        assert int(rt.eval(left)) == want

    # …AND NEVER ABOUT A MARCH THIS HUNT ORDERED (#1702). Applied to our own march the
    # ceiling does the opposite of its job: live, a ride the planner had quoted at 40
    # seconds was really flying for 213, the guard read it as «not ours» and recalled it —
    # the chain cancelling its own order mid-flight.
    rt = lupa.LuaRuntime()
    rt.execute("DataCenter = {__lw_gold = {eta_ms = 999000, pending = 1}} "
               "UITimeManager = {Instance = {GetServerTime = function() return 1000 end}}")
    assert int(rt.eval(left)) == -1, \
        "the ceiling can recall the hunt's own march — it would cancel its own attack"

    _body, wait = _brick("golden_wait_for_the_march")
    i = next(k for k, w in enumerate(wait) if " INTO eta_left" in w)
    guard = wait[i:i + 4]
    assert any(w.startswith("IF eta_left >") for w in guard), \
        "the reading is taken and the hunt waits anyway"
    assert "TAP golden_unstick" in guard, "a march that is not ours is waited out, not ended"

    # …AND THE LINE IT PRINTS CARRIES NO NUMBER (#1702). `{name}` in a `LOG` is filled in
    # from the values the recipe was CALLED with, so a reading taken two lines above is
    # not the one that gets printed: live, this line said «-1 more seconds» about a march
    # the `READ_LUA` had just answered 200 for, and the log was read for hours as proof
    # that the clock was broken.
    said = next(w for w in guard if w.startswith("LOG "))
    assert "{" not in said, \
        "the recall line prints a reading from a lap ago and calls it this one"

    # …and the recall drops the clock with it, or the guard fires again for ever.
    assert "p.eta_ms = nil" in lua_actions.golden_unstick(), \
        "the recall leaves the clock it was triggered by standing"


def test_the_chain_waits_for_a_session_before_it_touches_the_scene():
    """A restarted client answers everything plausibly from the login screen (#1702).

    Every other brick of this chain opens with `WAIT client == ready`; the chain itself
    opened by switching scenes. Measured tonight: two runs started within thirty seconds
    of a fresh client, and both times the log's next entry was «клиент пропал — процесса
    игры больше нет». Correlation rather than proof — but a run that cannot be played yet
    should say so rather than drive a half-loaded client into the world map.
    """
    _body, lines = _brick("attack_golden_zombies")
    ready = next(k for k, w in enumerate(lines) if w.startswith("WAIT client == ready"))
    scene = next(k for k, w in enumerate(lines) if w.startswith("IF scene != world"))
    assert ready < scene, "the run changes scene on a client that may not be in play yet"


def test_a_far_first_pick_widens_the_look_before_it_is_marched():
    """76 opening picks: median 47 tiles, tail 569 — and the ring covers about 160 (#1702).

    Beyond that «the nearest golden zombie» means «the nearest of the ones the client
    happens to be holding», which after a lap of the map is whatever district the lap
    ended in. The measurement this rests on is already in :data:`GOLDEN_REFRESH_RING`:
    standing 488 tiles out, the client answered `0` within 300 tiles of the base and,
    thirteen dwell stops later, `17` — the nearest of them 14 tiles from the front door.

    So a far opening answer buys another ring rather than a march. At the speed the game
    quotes an attack march, 569 tiles is over ten minutes; a ring is nine seconds.
    """
    import lupa
    assert lua_actions.GOLDEN_FIRST_FAR >= 2 * lua_actions.GOLDEN_REFRESH_RING, \
        "the run widens its ring over distances the ring can already see"
    assert lua_actions.GOLDEN_RING_MAX > lua_actions.GOLDEN_REFRESH_RING

    # The ring is a number the run may raise, and it is read rather than compiled in.
    ring = lua_actions.golden_refresh()
    assert "p.ring_now" in ring, "the ring cannot be widened within a run"
    assert "ring_now = nil" in lua_actions.golden_arm(), \
        "a new run inherits the last one's widened ring and pays for its map"

    widen = lua_actions.golden_widen_ring()
    for start, want in ((None, 2 * lua_actions.GOLDEN_REFRESH_RING),
                        (lua_actions.GOLDEN_RING_MAX, lua_actions.GOLDEN_RING_MAX)):
        rt = lupa.LuaRuntime()
        rt.execute("CS = {UnityEngine = {Debug = {LogError = function() end}}} "
                   "DataCenter = {__lw_gold = {%s}}"
                   % ("" if start is None else ("ring_now = %d" % start)))
        rt.execute(widen)
        assert int(rt.eval("DataCenter.__lw_gold.ring_now")) == want

    # …and the reading it acts on is «how long would the next march be», asked of the
    # queue before anything is chosen.
    best = lua_actions.golden_best_dist()
    rt = lupa.LuaRuntime()
    rt.execute("DataCenter = {__lw_gold = {home = {x = 100, y = 100}, used = {}, "
               "targets = {{pid = 1, x = 130, y = 140}, {pid = 2, x = 103, y = 104}}}}")
    assert int(rt.eval(best)) == 5, "the nearest queued target is not the one measured"
    rt = lupa.LuaRuntime()
    rt.execute("DataCenter = {__lw_gold = {home = {x = 1, y = 1}, used = {}, targets = {}}}")
    assert int(rt.eval(best)) == -1, "an empty queue answers a distance"

    # …and the recipe widens BEFORE the chain starts marching, not inside the loop.
    body, lines = _brick("attack_golden_zombies")
    i = next(k for k, w in enumerate(lines) if " INTO best_far" in w)
    loop = next(k for k, w in enumerate(lines) if w.startswith("WHILE go == 1"))
    assert i < loop, "the widening happens after the first march has already gone out"
    widening = lines[i:loop]
    assert any(w.startswith("WHILE best_far > ") for w in widening), \
        "the far answer is read and marched at anyway"
    assert "TAP golden_widen_ring" in widening and "TAP golden_refresh" in widening, \
        "the run widens nothing — it just asks again over the same ground"


def test_the_second_chain_is_the_first_one_with_its_state_renamed():
    """Two squads hunt at once, and they share the client and nothing else (#1702).

    The chain keeps its whole run in one table in the game VM, so a second run of the
    same recipes would overwrite the first one's target between statements. The twin
    (`tools/lib/golden_twin.py`) renames the STATE and changes nothing else, which is
    only safe for as long as it is regenerated: a twin that has drifted is a squad
    hunting yesterday's logic, and nothing in the game would say so.
    """
    sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import golden_twin

    assert not golden_twin.drift(), \
        "stale twin recipes (run tools/lib/golden_twin.py --write)"

    twin = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "attack_golden_zombies2.md").read_text(encoding="utf-8")
    assert "__lw_gold2" in twin, "the twin runs on the first chain's state"
    assert "DataCenter.__lw_gold " not in twin and "DataCenter.__lw_gold=" not in twin, \
        "the twin still touches the first chain's table"
    assert "TAP golden_" not in twin and "CALL golden_" not in twin, \
        "the twin presses the first chain's buttons"

    # …and every press it names exists.
    sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import game_buttons
    for line in twin.splitlines():
        if line.strip().startswith("TAP "):
            name = line.split()[1]
            assert name in game_buttons.BUTTONS, "the twin presses %s, which does not exist" % name


def test_a_squad_that_has_landed_is_re_targeted_where_it_stands():
    """The measurement that pays for the whole chain, and the wrong turn on the way (#1702).

    Where the time goes, over twenty minutes of two squads hunting::

        free -> order away     median   5 s
        order -> free again    median  64 s and 115 s

    Our own overhead is the five seconds. The rest is the squad standing on the tile it
    cleared — `state=1 status=STATION team=0 arrive=0`, which is exactly what `back = 0`
    asks for — and the win is to order it again from there instead of walking it home.

    **It was written down as impossible, and that was our bug.** Two sends at a stationed
    squad left the purse unmoved (1941 before, 1941 three minutes later), and the reading
    taken from it — «the game refuses to redeploy a landed army» — survived a day.
    `SendCreateMarchMessage` creates a march FROM THE BASE. The dispatch screen uses a
    different door::

        MarchUtil.SendChangeMarchToServer(marchUuid, targetType, targetPoint,
                                          targetUuid, backHome, targetServerId,
                                          destroyTimeIndex)

    Seven arguments (`debug.getinfo` says so), message `world.march.change`. Live on
    2026-08-22 at a squad reading `status=STATION: 0 end=0`: purse 1871 -> 1861, and the
    march turned MOVING onto a zombie 23 tiles away with no step homewards.

    The lesson is the one this repository keeps paying for: **a refusal the person
    playing by hand cannot reproduce is a bug in the sender, not a rule of the game.**
    """
    import lupa

    send = lua_actions.golden_send()
    assert "SendChangeMarchToServer" in send, \
        "the send walks the squad home between kills again"
    assert "SendCreateMarchMessage" in send, \
        "a squad standing in the BASE has no march to re-target — both doors are needed"

    can = lua_actions.golden_can_order()
    assert can != lua_actions.golden_squad_free(), \
        "the gate is the rally's again, and a landed squad is called busy"

    def answer(free, march, ours=None):
        rt = lupa.LuaRuntime()
        rt.execute("LuaEntry = {Player = {uid = 1, allianceId = 2}} "
                   "DataCenter = {__lw_gold = {formation = '77'%s}, "
                   "WorldMarchDataManager = "
                   "{GetOwnerFormationMarch = function() return %s end}, "
                   "ArmyFormationDataManager = {ArmyFormationList = "
                   "{{uuid = '77', state = %d, totalSoldierNum = 100, "
                   "IsFree = function() return %s end}}}}"
                   % ("" if ours is None else (", own_march = '%s'" % ours),
                      march, 0 if free else 1, "true" if free else "false"))
        return int(rt.eval(can))

    landed = "{teamUuid = '0', status = 'STATION: 0', endTime = 0}"
    flying = "{teamUuid = '0', status = 'MOVING: 1', endTime = 99000}"
    banner = "{teamUuid = '1000000000000000001', status = 'IN_TEAM: 7', endTime = 0}"
    mining = "{uuid = '900', teamUuid = '0', status = 'COLLECTING: 3', endTime = 99000}"

    assert answer(True, "nil") == 1, "a squad standing at home is refused an order"
    assert answer(False, landed) == 1, \
        "the squad standing where it killed is walked home instead of re-aimed"
    assert answer(False, flying) == 0, "a march still on its way is ordered over"
    assert answer(False, banner) == 0, \
        "the hunt walks its squad out of somebody's alliance rally"
    assert answer(False, "nil") == 0, \
        "a busy squad with no march of its own is ordered about anyway"

    # …AND A SQUAD WORKING A MINE, which is the case the operator does by hand (#1702).
    # Proven live: rode onto a free mine (`COLLECTING: 3`, endTime 5.6 hours out), aimed
    # the same march at another — same uuid, target 425441 -> 420470, COLLECTING ->
    # MOVING, no walk home. That is «залипание на шахте» answered as well.
    assert answer(False, mining, ours="900") == 1, \
        "the hunt's own squad is left stuck on the ore it rode to"
    # …but only when the march is the RUN'S OWN. A squad the PLAYER sent to gather is
    # theirs, and yanking it off the ore to hit a zombie is not this recipe's call.
    assert answer(False, mining) == 0, \
        "the hunt takes a gathering squad the player sent, off its mine"
    assert answer(False, mining, ours="901") == 0, \
        "any gathering march is treated as the run's own"


def test_two_squads_are_never_sent_at_the_same_zombie():
    """The one thing the two chains DO share, because not sharing it wastes a lap (#1702).

    A second order at a zombie already being marched at is refused in silence, so the
    lap costs a march's worth of waiting and buys nothing. The claim table is spelled
    without the `__lw_gold` prefix on purpose: that prefix is exactly what the twin
    renames, so a renamed claims table would leave each run agreeing only with itself.
    """
    import lupa
    assert "__lw_zclaims" in lua_actions._GOLD_CLAIMS
    assert "__lw_gold" not in "__lw_zclaims", "the claim table would be renamed by the twin"
    assert lua_actions.GOLDEN_CLAIM_SEC >= 60, \
        "a claim expires so fast that both squads can still be sent at one tile"

    # A tile another squad is on is skipped; our own, and a stale one, are not.
    probe = ("(function() " + lua_actions._GOLD_P +
             "return (_goldfree(p, 42) and 1 or 0) end)()")
    def answer(claim):
        rt = lupa.LuaRuntime()
        rt.execute("UITimeManager = {Instance = {GetServerTime = function() return 1000000 end}} "
                   "DataCenter = {__lw_gold = {squad = 3}, __lw_zclaims = %s}" % claim)
        return int(rt.eval(probe))

    assert answer("{}") == 1, "an unclaimed tile is refused"
    assert answer("{['42'] = {sq = 3, at = 999000}}") == 1, \
        "a run will not go back to a tile it claimed itself"
    assert answer("{['42'] = {sq = 2, at = 999000}}") == 0, \
        "both squads are sent at one zombie, and the second order is refused in silence"
    stale = 1000000 - (lua_actions.GOLDEN_CLAIM_SEC + 60) * 1000
    assert answer("{['42'] = {sq = 2, at = %d}}" % stale) == 1, \
        "a run that died mid-march locks its last target out for the rest of the night"

    # …and the send is what writes the claim down.
    assert "_goldclaim(p, t.pid)" in lua_actions.golden_send(), \
        "a march goes out without telling the other run where it went"


def test_a_squad_nothing_will_free_is_brought_home_instead_of_waited_on():
    """The OTHER way the hunt sat still, and the ceiling cannot see it (#1702).

    Measured live on the chosen squad, and it ended a run with `attacks=0`::

        squad=2 state=1 free=0 soldiers=2631 status=STATION march=NORMAL team=0
                point=494542 arrive=0

    Out, so no order may be given; nothing to wait for, because it has already landed and
    is STANDING there. The wait then spent its whole allowance — 300 beats, ten minutes —
    on a reading that would have been identical an hour later.
    """
    import lupa
    parked = lua_actions.golden_parked()

    def answer(free, march):
        rt = lupa.LuaRuntime()
        rt.execute("LuaEntry = {Player = {uid = 1, allianceId = 2}} "
                   "DataCenter = {__lw_gold = {formation = '77'}, "
                   "WorldMarchDataManager = "
                   "{GetOwnerFormationMarch = function() return %s end}, "
                   "ArmyFormationDataManager = {ArmyFormationList = "
                   "{{uuid = '77', state = %d, IsFree = function() return %s end}}}}"
                   % (march, 0 if free else 1, "true" if free else "false"))
        return int(rt.eval(parked))

    landed = "{teamUuid = '0', status = 'STATION: 0', endTime = 0}"
    flying = "{teamUuid = '0', status = 'MOVING: 1', endTime = 99000}"
    banner = "{teamUuid = '1000000000000000001', status = 'IN_TEAM: 7', endTime = 0}"

    # …AND A LANDED MARCH IS NO LONGER ONE OF THEM (#1702). It was, for as long as the
    # only send this repository had could not redeploy an army that had arrived. The
    # squad standing on the tile it cleared is given its next order where it stands now,
    # so recalling it would throw away the saving the whole chain is built on.
    assert answer(False, landed) == 0, \
        "the squad standing where it killed is recalled instead of being re-aimed"
    assert answer(False, "nil") == 1, \
        "a busy squad the game holds no march for is waited on — nothing will free it"
    assert answer(False, flying) == 0, \
        "a march still on its way is recalled instead of waited out"
    # A BANNER ENDS BY ITSELF, and recalling it quits somebody's rally for them.
    assert answer(False, banner) == 0, \
        "the hunt walks its squad out of an alliance rally"
    assert answer(True, landed) == 0, \
        "a squad the game says is free is recalled anyway"

    # …and the recipe acts on it BEFORE the ten-minute wait, or the reading buys nothing.
    _body, wait = _brick("golden_wait_for_the_march")
    i = next(k for k, w in enumerate(wait) if " INTO parked" in w)
    loop = next(k for k, w in enumerate(wait) if w.startswith("WHILE squad_free == 0 LIMIT"))
    assert i < loop, "the parked reading is taken after the wait it exists to skip"
    assert "TAP golden_unstick" in wait[i:loop], "the squad is left standing where it is"


def test_a_lap_does_not_begin_until_the_squad_is_free():
    """One rule for every reason a squad will not take an order (#1702).

    Still walking, working a mine, standing on dirty ground, recalled a moment ago — the
    send does not care which, it cares whether the next order will be accepted. So the
    wait brick ends on that question and nothing else, bounded, with the bound spoken:
    a hunt that waits for ever is the thing being fixed.
    """
    _body, wait = _brick("golden_wait_for_the_march")
    i = max(k for k, w in enumerate(wait) if " INTO squad_free" in w)
    loop = next(w for w in wait if w.startswith("WHILE squad_free == 0 LIMIT"))
    beats = int(loop.rsplit(" ", 1)[-1])
    # TEN MINUTES IS THE CEILING NOW (#1702): «busy for two minutes» ended four runs
    # of one morning, and a squad is busy because a rally, a gather or the person
    # has it — all of which end by themselves in minutes.
    assert 30 <= beats <= 300, "the patience is either a blink or a hang"
    tail = wait[i:]
    assert any(w.startswith("LOG ") for w in tail), \
        "a run that gives up on a busy squad does so in silence"
    assert "READ_LUA (0) INTO go" in tail, \
        "the run carries on sending orders at a squad that will not take them"


def test_a_failure_says_the_numbers_it_is_about():
    """#1702, off the live log: «nothing was sent — {golden_report}».

    `{name}` was filled in for `LOG` and not for `FAIL`, which is backwards — a log line
    is one of hundreds and a failure reason is the sentence the panel shows and a person
    reads. The report it was naming was sitting in the variables at the time.
    """
    ctx = engine.new_context(0, lambda _m: None)
    interp = engine.Interpreter(ctx)
    ctx.vars["report"] = "found=183 attacks=0"
    for stmt, attr, flag in ((engine.FailStmt(text="", line_no=1,
                                              reason="nothing was sent — {report}"),
                              "fail_reason", "failed"),
                             (engine.StopStmt(text="", line_no=1,
                                              reason="stopped — {report}"),
                              "halt_reason", "halt")):
        try:
            interp._run_stmt(stmt)
        except Exception:                # noqa: BLE001 — the signal is the point
            pass
        assert "found=183" in getattr(ctx, attr), \
            f"{attr} lost the numbers it was about: {getattr(ctx, attr)!r}"
        setattr(ctx, flag, False)


def test_the_ride_is_skipped_once_after_a_recall():
    """A recalled squad is at neither origin the chain measures from (#1702).

    Every distance the hunt works out is measured from `anchor or home`, and a squad that
    has just been recalled is at neither — it is wherever the cancelled order left it,
    walking. The planner then prices BOTH the direct march and the ride off the wrong
    origin, so the comparison it makes is meaningless: live, a ride quoted at 40 seconds
    was still flying after two hundred. The next send is therefore a plain attack march,
    and the ride resumes after it.
    """
    import lupa
    assert "p.skip_ride = 1" in lua_actions.golden_unstick(), \
        "a recall leaves the next ride to be priced from an origin the squad is not at"
    arm = lua_actions.golden_approach_arm()
    rt = lupa.LuaRuntime()
    rt.execute("CS = {UnityEngine = {Debug = {LogError = function() end}}}")
    rt.execute("DataCenter = {__lw_gold = {skip_ride = 1, cur = {pid = 1, x = 1, y = 1}}}")
    rt.execute(arm)
    assert rt.eval("DataCenter.__lw_gold.approach") is None, "the ride was planned anyway"
    assert rt.eval("DataCenter.__lw_gold.why") == "after-recall"
    # …ONCE. The flag clears itself, or a single recall would end riding for the run —
    # which is what the FUSE is for, and it is a different decision with a different cause.
    assert int(rt.eval("DataCenter.__lw_gold.skip_ride")) == 0, \
        "one recall switches the ride off for good"


def test_a_stale_row_costs_a_pick_and_not_a_whole_lap():
    """Measured live: nine of fifteen laps of a run ended in `dropped=stale` (#1702).

    The client had already forgotten those uuids, and the SEND was where that came out —
    so a whole lap had been spent choosing, checking and arming a target that could never
    be marched at. The same question asked at the moment of choosing costs a fifth of a
    second and the answer is «pick again», in the same lap.

    Strict here and lenient in the registry, and the asymmetry is the point: this is one
    target a march is about to be spent on, while a REGISTRY row wrongly dropped is a
    zombie nothing can re-add.
    """
    import lupa
    live = lua_actions.golden_target_live()
    assert "_freshuuid" in live, "the strict check is not the one the send makes"
    assert "HasPointInfo" not in live, \
        "the strict check borrowed the registry's leniency — it would arm dead targets"

    _body, choose = _brick("golden_choose_a_target")
    i = next(k for k, w in enumerate(choose) if " INTO target_live" in w)
    tail = choose[i:i + 6]
    assert "TAP golden_drop_target" in tail, "a target the client cannot name is armed anyway"
    assert "IF target_live == 1" in tail, "the reading is taken and not acted on"

    # A DROP IS A PROVEN DISAPPEARANCE and feeds the same threshold the reaping does
    # (#1702). Live, one lap dropped six stale rows and sent nothing: the corner had been
    # farmed out while the squad was walking, and nothing was telling the threshold.
    drop = lua_actions.golden_drop_target()
    assert "p.since_refresh" in drop and "p.vanished" in drop, \
        "a row the client cannot name is dropped without anything noticing the ground is bad"
    after = choose[i:i + 14]
    assert any(w.startswith("IF needs_refresh ==") for w in after), \
        "the ground is only redrawn on the NEXT lap — this one would drop six and send none"

    # …and nothing in the brick that CHOOSES is allowed to give an order.
    assert not any(w in ("TAP golden_send", "TAP golden_home", "TAP golden_ride")
                   for w in choose), "the choosing brick gives orders"


def test_a_lap_waits_for_the_hunts_own_march_and_not_for_can_march():
    """`canMarch` is true while our march is in flight — measured, not assumed (#1702).

    Live on 2026-08-21, seconds after a send, `dev/golden_squad_state.md` printed
    `squad2 state=1 canMarch=true` beside `marches=1 [left=71s]`. The gate that let a lap
    begin read `canMarch`, so it passed while the squad was still walking; every send
    that followed was refused in silence and the chain wrote the target off as «gone».
    One run attacked once and burned four targets that way.

    So the wait watches the MARCH — the uuid the send parked — and the recipe must carry
    the module's own copy of that question.
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "golden_wait_for_the_march.md").read_text(encoding="utf-8")
    assert "INTO marching" in text, "the wait no longer asks whether our march is out"
    assert lua_actions.golden_march_in_flight() in text, "the recipe's copy has drifted"
    assert "WHILE marching == 1" in text, "the reading is taken and then not waited on"
    assert text.index("INTO marching") < text.index("INTO squad_free"), \
        "the march is asked about after canMarch, which is the order that failed"


def test_no_lap_orders_anything_into_a_dead_link():
    """A hunt is minutes long and the link is only read when a run STARTS (#1702).

    Live on 2026-08-21 the client went deaf mid-run, the chain went on sending, and the
    squad was left on a march the server never answered — `endTime=0` beside a real
    `startTime`, which is «застрял в текстурах» seen from the data. From inside the
    client nothing says so: every getter answers and every send returns cleanly.
    """
    text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "golden_wait_for_the_march.md").read_text(encoding="utf-8")
    assert "WAIT client == ready" in text, "a lap no longer checks the link"
    assert text.index("WAIT client == ready") < text.index("INTO marching"), \
        "the link is checked after the lap has already begun waiting on a march"


def test_an_empty_lap_pauses_instead_of_ending_the_run():
    """Both ways a lap comes up empty are answered by waiting, and the wait is bounded.

    Measured over the morning of 2026-08-21: almost every run of the day ended on one of
    two lines — «no zombie within reach» and «several sends in a row went nowhere» — the
    best of them after 19 kills in 38 minutes, with 7 505 energy still in the purse. Both
    mean the ground has been farmed out, and the invasion refills it in a couple of
    minutes (#1702).
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "golden_send_the_squad.md").read_text(encoding="utf-8")
    assert "TAP golden_breathe" in text, "a stalled lap no longer pauses"
    assert text.count("TAP golden_stall_mark") == 2, \
        "both empty laps — no target, and a streak of refusals — must mark the stall"
    assert lua_actions.golden_breathers_left() in text, "the pause is unbounded"
    assert "no pauses left" in text, "nothing ends the run when the patience runs out"
    # …and the ending is still reachable: the run stops when the pauses are used up.
    assert "READ_LUA (0) INTO go" in text


def test_the_chain_creates_no_new_lua_globals():
    """The client REFUSES a new global, and says so in its own log (#1702).

    `GlobalProtect.lua:54` is a `__newindex` metamethod on `_G`, and every attempt is a
    Lua error the client writes down —

        Lua 全局变量 '__LW_GOLD_WS' 不可<新增/修改>

    — while the assignment silently does not happen. So the cache the chain thought it
    was keeping was rebuilt on every call, and the game logged an error each time. State
    goes on `DataCenter`, which is an existing table and takes new fields quietly.
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    bad = [name for name in dir(lua_actions)
           if name.startswith("golden") and callable(getattr(lua_actions, name))]
    for name in bad:
        fn = getattr(lua_actions, name)
        try:
            text = fn()
        except TypeError:
            continue
        assert "_G.__LW" not in str(text), f"{name} writes a new Lua global"
    for recipe in ("attack_golden_zombies", "golden_wait_for_the_march",
                   "golden_judge_the_kill", "golden_choose_a_target",
                   "golden_send_the_squad", "read_golden_zombies"):
        text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
                / f"{recipe}.md").read_text(encoding="utf-8")
        assert "_G.__LW" not in text, f"{recipe} writes a new Lua global"


def test_the_lap_waits_for_the_fight_and_never_orders_over_one():
    """«Прыгает с монстра на монстра» — the operator, watching the game (#1702).

    Two halves make it impossible now. The target is fixed when the ORDER is sent, not
    when the client's march list catches up with it — that list lags, and lap after lap
    the six-second launch poll ran out while the squad really was walking. And the wait
    for the zombie to leave the map is given the march's own budget instead of sixteen
    seconds, so a fight is waited out rather than judged «still standing».
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    assert "p.hit = p.pending" in lua_actions.golden_send(), \
        "the target is not fixed at the moment the order goes out"
    judge = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
             / "golden_judge_the_kill.md").read_text(encoding="utf-8")
    loop = next(line for line in judge.splitlines()
                if line.startswith("WHILE gone == 0 LIMIT"))
    assert int(loop.rsplit(" ", 1)[-1]) >= 60, \
        "the fight is not waited out — the chain will order over one in progress"


def test_a_press_checks_the_link_and_takes_back_a_march_with_no_clock():
    """The button had no link gate, and the chain's own gate does not cover it (#1702).

    A press into a client the server has hung up on draws a march locally that is never
    confirmed — `endTime = 0` beside a real `startTime` — and the squad stands painted
    mid-move refusing every order after it. The operator has now seen that twice, and it
    is not a state ordinary play produces.

    So a press reads the link before it orders anything, and afterwards checks for a
    march with no arrival time and takes it back rather than leaving it in the game.
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "golden_attack_target.md").read_text(encoding="utf-8")
    assert "WAIT client == ready" in text, "the press orders without reading the link"
    assert text.index("WAIT client == ready") < text.index(lua_actions.golden_send_now()), \
        "the link is read after the order has gone"
    # THE PROOF MOVED OUT OF THE PRESS (#1702): waiting for the client to draw the march
    # is five seconds of a button that has already done its work, so the panel plays
    # `golden_verify_order` a few seconds later and recalls a phantom then.
    verify = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
              / "golden_verify_order.md").read_text(encoding="utf-8")
    assert lua_actions.golden_phantom_marches() in verify, "nothing looks for a phantom march"
    assert "TAP golden_unstick" in verify, "a phantom march is found and then left there"
    # …and both are narrow: a RALLY march of the player's own has no arrival clock
    # either, and neither the check nor the recall may touch it (#1702, measured live —
    # a rally sat in the same list with `endTime = 0` minutes after the first version
    # of this shipped).
    for lua in (lua_actions.golden_phantom_marches(), lua_actions.golden_unstick()):
        assert "p.march_uuid" in lua, "our own order is not told apart from a rally"


def test_a_single_press_comes_home_and_gives_up_on_a_zombie_that_dies_en_route():
    """«Цели не было, отряд доехал и застрял» — the operator, watching it happen (#1702).

    The chain leaves a squad standing where it killed on purpose: the next pick is
    measured from there and the next order is seconds away. A press is not a chain. Its
    march carries the game's own «come home when you are done», and while it walks the
    tile is watched — a zombie somebody else kills on the way turns the rest of the march
    into a walk to an empty square, so the march is called back instead.
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "golden_attack_target.md").read_text(encoding="utf-8")
    assert "false, srv, nil) end) " in lua_actions.golden_send_now()
    assert ", 1, 1, false, srv, nil)" in lua_actions.golden_send_now(), \
        "a single attack no longer carries «come home when you are done»"
    # THE WATCH MOVED OUT OF THE PRESS (#1702). It stayed until the operator pointed out
    # that a button which waits out a whole march is not a button: «должен реагировать
    # мгновенно, и на повторные клики тоже». So the press ends when the order is away,
    # and the chain — which is the thing that has minutes to spend — keeps the watch.
    chain = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
             / "golden_judge_the_kill.md").read_text(encoding="utf-8")
    assert lua_actions.golden_gone() in chain, "nothing watches the target any more"


def test_the_same_zombie_can_be_attacked_again_after_the_squad_is_turned_round():
    """«Один раз пошёл, я его развернул — и второй раз не смог отправить» (#1702).

    The run remembers its last order — the march uuid it parked, the proof it was
    waiting on, and the tile written into `used`, which is how the CHAIN avoids walking
    back round its own kills. For a hand press all three are in the way: the person is
    looking at that zombie and pressing attack again.
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    clear = lua_actions.golden_clear_order()
    assert "p.march_uuid = nil" in clear and "p.pending = nil" in clear
    assert "p.used[tostring(p.cur.pid)] = nil" in clear, \
        "the tile stays marked as attacked, so the same zombie cannot be sent at twice"
    assert "p.cur = nil" not in clear, "clearing the order also throws the target away"
    # …and neither does the recall: pressing «Вернуть отряд» and then «Атаковать
    # выбранного» must send at the same zombie again (#1702).
    assert "p.cur = nil" not in lua_actions.golden_unstick(), \
        "the recall throws the fixed target away"
    recall = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
              / "golden_recall_squad.md").read_text(encoding="utf-8")
    assert "TAP golden_arm" not in recall, \
        "the recall re-arms, and arming builds the run from nothing — the target is lost"
    assert "TAP golden_use_squad" in recall

    text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "golden_attack_target.md").read_text(encoding="utf-8")
    # FOLDED INTO ONE CALL (#1702): pointing at the squad, forgetting the previous order
    # and asking whether one may go are a single question now — «мгновенно» is mostly a
    # matter of not asking the VM five things it could answer in one breath.
    send = lua_actions.golden_send_now()
    assert send in text, "the press no longer checks and orders in one call"
    assert "p.march_uuid = nil" in send and "p.used[tostring(p.cur.pid)] = nil" in send
    assert "return -4 end " in send, \
        "a zombie the client can no longer name is still ordered at"
    assert "p.targets = keep p.cur = nil" in send, \
        "the dead row stays in the registry, so the next «найти» offers the same tile"


def test_finding_measures_from_where_the_squad_was_left_and_looks_there():
    """«Перекидывает далеко, хотя рядом с ним есть зомби» — the operator (#1702).

    Two faults, one after the other. Arming builds the run from nothing, and «найти
    ближайшего» arms on every press — so it forgot that the squad had been left standing
    in the field and measured from the base. And the client only holds what the camera
    has been shown, so even with the right origin the registry can hold none of the
    zombies beside the squad: the ground there has to be asked about first.
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    assert "p.anchor = _keep.anchor" in lua_actions.golden_arm(), \
        "arming forgets where the squad was left"
    text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "golden_find_target.md").read_text(encoding="utf-8")
    # THREE CALLS NOW, NOT FOURTEEN (#1702): the preparation decides the origin inside
    # the VM and says whether the squad is out, and the flight to it is paid only then.
    assert lua_actions.golden_find_now() in text, "the preparation is not one call"
    assert "IF ready == 1" in text
    look = text.index("TAP golden_look_from")
    pick = text.index(lua_actions.golden_pick_and_report())
    assert look < pick, "the ground around the squad is asked about after the choice"
    assert "p.anchor = p.last_sent" in lua_actions.golden_find_now(), \
        "a squad in the field is not measured from where it was sent"


def test_the_find_never_offers_a_zombie_the_client_cannot_name():
    """«Указал на пустое место… не хотел никак обновлять реестр» (#1702).

    Collapsing the pick into one call took the liveness check out with it, and the same
    dead tile came back six presses in a row — the log is unambiguous:

        16:50:33  found a golden zombie: #935 X:541 Y:497 … queued=177
        16:50:38  found a golden zombie: #935 X:541 Y:497 … queued=177
        16:50:47  found a golden zombie: #935 X:541 Y:497 … queued=177

    …while «атаковать выбранного» refused the very same tile with «target gone». The two
    halves of one button disagreeing is worse than either being wrong.
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    pick = lua_actions.golden_pick_and_report()
    assert "_freshuuid" in pick, "the pick offers a target without asking whether it exists"
    assert "p.targets = keep" in pick, "a dead row is left in the registry to come back"
    assert "for _try = 1, 12 do" in pick, "one dead row ends the search instead of the next"
    # …and a far candidate is still taken on trust: «not there» from a district the
    # client has evicted says nothing about the zombie.
    assert "near = (math.sqrt(dx * dx + dy * dy) <= 40)" in pick
    assert "dropped=" in pick, "the reaping is silent — a press cannot say what it struck out"


def test_a_found_zombie_is_confirmed_on_its_own_ground_before_it_is_announced():
    """«Плохо фильтрует монстров, которые пропали» (#1702).

    The pick verifies what is near the camera and takes the rest on trust — right for
    filling a queue, wrong for an ANSWER, and the operator kept being shown tiles that
    were empty by the time he looked at them. So the chosen one is asked about on its
    own ground before it is announced, and a candidate the client cannot see from here
    is flown to and asked again.

    Three answers, kept apart on purpose (THE_LIST_RULE, #1272): alive, gone — struck
    out, because the game looked straight at that ground — and «cannot tell», which
    changes nothing about the row.
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    confirm = lua_actions.golden_confirm_current()
    # …and «is the client holding that ground» is ASKED, not guessed from the camera:
    # `CurTilePos` does not follow a jump, so a forty-tile heuristic made everything far
    # permanently unconfirmable (#1702).
    # …and the three cases are told apart by the AREA LIST, because `HasPointInfo` is
    # false for a monster tile and `CurTilePos` lags a jump — measured with the camera
    # parked exactly on a candidate: `holds=false camera=874,895 area_n=1` (#1702).
    assert "if wide <= 0 then return -1 end end" in confirm, \
        "an empty box is read as death instead of «nothing loaded there»"
    assert ", 60, ids, res)" in confirm, \
        "an unloaded district is not told apart from a district with no zombies left"
    assert "if mine then" in confirm, "the zombie's own uuid is not what confirms it"
    assert "p.targets = keep p.cur = nil" in confirm, "a zombie proven gone is kept"
    assert "t.at = os.time() t.seen = 1" in confirm, "a confirmation is not recorded"
    assert "at = os.time()" in lua_actions.golden_scan(), "rows are not stamped with a time"

    text = (_REPO_ROOT / "src" / "lastwar_bot" / "actions"
            / "golden_find_target.md").read_text(encoding="utf-8")
    assert confirm in text, "the find announces a target it never confirmed"
    # AN UNCONFIRMED TILE IS NOT AN ANSWER AT ALL (#1702). Announcing it with a warning
    # beside it still flew the camera to empty ground — measured on the tile the button
    # itself had offered: `area: n=0`, `point: not-loaded`, no monster record.
    # …and an unconfirmed tile is OFFERED with the truth attached rather than refused:
    # measured, the area list is not filled by the camera at all, so «cannot tell» is the
    # ordinary answer for anything the last sweep did not sit on (#1702). The gate that
    # matters is the attack, which re-reads the uuid at send time.
    assert "not confirmed (the client cannot see that ground from here)" in text, \
        "an unconfirmed target is offered as if it had been seen"
    assert "return -4 end " in lua_actions.golden_send_now(), \
        "the attack does not re-check the target at send time"
    assert lua_actions.golden_age_line() in text, "the answer does not say how old the row is"


def test_the_seven_buttons_are_one_chain_and_the_round_presses_them_all():
    """The JOINS, not the pieces — «почему постоянная деградация?!» (#1702).

    Every fix in this task was proved by pressing the one button it touched, and the
    suite stayed green over buttons that had stopped working: the find would hand back a
    target the attack refused, or the attack would answer «no army» on every first press.
    What was missing was a test of the SEAMS.

    So: the find parks a target and the attack sends at THAT and nothing else, the
    attack invents no target of its own, «no army» is cured inside one press instead of
    asking the person to press again, and `dev/golden_button_round.md` presses all seven
    in the order a person does — which is what has to be run live before a commit.
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
    import lua_actions                       # noqa: PLC0415

    actions = _REPO_ROOT / "src" / "lastwar_bot" / "actions"
    find = (actions / "golden_find_target.md").read_text(encoding="utf-8")
    attack = (actions / "golden_attack_target.md").read_text(encoding="utf-8")

    # the seam: one parks `p.cur`, the other sends at `p.cur` and never picks
    assert "p.cur = best" in lua_actions.golden_pick_and_report(), "the find parks nothing"
    assert "if p.cur == nil then return -3 end" in lua_actions.golden_send_now(), \
        "the attack does not send at what the find parked"
    assert "TAP golden_pick" not in attack and "golden_pick_and_report" not in attack, \
        "the attack chooses a target of its own"

    # «no army» is cured inside the press, not handed back to the person
    assert attack.count(lua_actions.golden_send_now()) >= 2, \
        "the send is not retried after the army is fetched"
    assert "CALL fill_empty_squads" in attack

    # …and the round exists, and presses every one of the seven
    round_md = (actions / "dev" / "golden_button_round.md").read_text(encoding="utf-8")
    for step in ("scan_map", "golden_find_target", "golden_goto_target",
                 "golden_attack_target", "golden_squad_report", "golden_recall_squad",
                 "golden_forget_target"):
        assert f"CALL {step}" in round_md, f"the round never presses {step}"


def test_a_squad_is_busy_because_the_game_says_so_and_never_because_of_can_march():
    """«В логи пишется, что ОТРЯД ЗАНЯТ, но это НЕ ТАК» (#1702).

    Read live off a squad standing at home with a full army::

        squad=2 state=0 free=1 soldiers=2631 status=- march=- team=0

    and the same squad, in the same breath, through the gate this chain used to ask::

        squad2 state=0 canMarch=false soldiers=2631

    `canMarch` is false on EVERY formation of a headless session — it is recomputed by
    the real dispatch render and by nothing else (docs/research/world-monsters.md,
    Finding 11, «a red herring»). So a gate built on it calls a free squad busy for ever,
    and the whole rest of this repository already knew better: `create_rally.md`,
    `read_squad_state.md` and the rally limits all ask `state == 0` together with the
    game's own `IsFree()`. The golden family was the one place that did not.
    """
    actions = _REPO_ROOT / "src" / "lastwar_bot" / "actions"
    for path in sorted(actions.glob("golden_*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue                      # prose may name the field it stopped using
            assert "canMarch" not in line, (
                f"{path.name}:{number} decides something from canMarch, which is false "
                "for every squad of a headless session")

    # …and what replaced it asks the two things the game answers honestly.
    for name in ("golden_attack_target", "golden_send_the_squad",
                 "golden_wait_for_the_march"):
        text = (actions / f"{name}.md").read_text(encoding="utf-8")
        assert "IsFree()" in text, f"{name} never asks the game's own idle flag"
        assert "tonumber(f.state)" in text, f"{name} never reads the squad's state"


def test_the_proof_of_a_send_is_our_own_squads_march_and_not_any_march_at_all():
    """A march is ours when OUR formation is on it — a banner and a sibling are not.

    The launch used to be confirmed by any march that had appeared in
    `GetOwnerMarches()` since the send. That list holds every squad of the account, so an
    auto-join raising a second squad inside the four seconds the panel waits confirmed an
    order that had been refused. It asks the formation for its own march now, and a march
    standing in a banner (`teamUuid ~= 0`) is not the order we just gave — the two look
    alike from outside, both carrying `endTime = 0`.
    """
    actions = _REPO_ROOT / "src" / "lastwar_bot" / "actions"
    for name in ("golden_verify_order", "golden_send_the_squad"):
        text = (actions / f"{name}.md").read_text(encoding="utf-8")
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        assert "GetOwnerFormationMarch" in code, (
            f"{name} still proves the send off the whole march list")
        assert "GetOwnerMarches" not in code.split("p.march_before")[0], (
            f"{name} still counts any march of the account as its own proof")
        assert "teamUuid" in code, f"{name} would take a banner for its own order"


def test_every_press_of_the_hunt_is_lua_the_game_could_actually_run():
    """A press that will not compile answers `None`, and the recipe stops on it.

    Live, this exact failure::

        READ_LUA sent = None
        < action: golden_attack_target FAILED — variable 'sent' = None is not numeric

    The cause is worth pinning because it is silent and it is Python, not Lua: several of
    these builders are assembled as one string literal and then `%`-formatted, and `+`
    binds LOOSER than `%`. Splitting such a literal to concatenate a constant leaves every
    earlier fragment unformatted — the `%(gold)s` placeholders travel into the game as
    literal text, and the chunk does not parse. A constant used inside a `%`-formatted
    builder has to travel through the dict, never through `+`.
    """
    import lupa
    rt = lupa.LuaRuntime()
    checked = 0
    for name in sorted(dir(lua_actions)):
        if not name.startswith("golden"):
            continue
        try:
            expr = getattr(lua_actions, name)()
        except TypeError:                 # takes arguments — not a bare press
            continue
        if not isinstance(expr, str) or not expr.lstrip().startswith("("):
            continue
        assert "%(" not in expr, (
            f"{name} carries an unformatted placeholder — a split literal was "
            "%-formatted, and `+` binds looser than `%`")
        checked += 1
        try:
            rt.compile("return " + expr)
        except Exception as exc:          # noqa: BLE001 — the message is the report
            raise AssertionError(f"{name} is not valid Lua: {exc}") from None
    assert checked > 20, "the sweep found almost no presses — it is looking in the wrong place"


def test_a_free_squad_with_no_army_is_asked_for_one_and_never_sent_empty():
    """The order of the two questions, pinned — they used to be nested the other way.

    While the gate read `canMarch`, «no army» hid behind it: a squad the client held no
    soldiers for happened to answer `canMarch = false` as well, so asking «can it march»
    first still reached the soldier count. Asking the GAME instead removed that accident —
    a squad with no army is `state = 0` and `IsFree() = true`, free by every reading there
    is — and the same nesting would have sent an empty formation at a zombie, which the
    server refuses in silence.

    Live, the press that caught it::

        sending: squad=2 ... soldiers=0 ... call=SendCreateMarchMessage/ATTACK_MONSTER
    """
    send = lua_actions.golden_send_now()
    army = send.index("tonumber(p.soldiers) or 0) <= 0 then return -2")
    busy = send.index("if not can then return 0 end")
    assert army < busy, \
        "the send acts on «free» before it counts the soldiers — an empty squad goes out"

    # …and the standalone gate answers the same way round.
    expr = lua_actions.golden_squad_free()
    import lupa

    def ask(state=0, idle=True, soldiers=100):
        rt = lupa.LuaRuntime()
        rt.execute("DataCenter = {__lw_gold = {formation = '77'}, "
                   "ArmyFormationDataManager = {ArmyFormationList = "
                   "{{uuid = '77', state = %d, totalSoldierNum = %d, "
                   "IsFree = function() return %s end}}}}"
                   % (state, soldiers, "true" if idle else "false"))
        return int(rt.eval(expr))

    assert ask(soldiers=0) == -2, "a free squad with no army reads as ready to be sent"
    assert ask(state=1, soldiers=0) == -2, \
        "a squad that is out AND has no army is worth asking for the army first"
    assert ask() == 1, "a squad at home with an army is refused"


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
