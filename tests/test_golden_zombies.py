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
    seen by two runs is one zombie.
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

RECIPE = _REPO_ROOT / "src" / "lastwar_bot" / "actions" / "attack_golden_zombies.md"
READING = _REPO_ROOT / "src" / "lastwar_bot" / "actions" / "read_golden_zombies.md"

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
    assert lua_actions.GOLDEN_ZOMBIE_CFG == 1030000
    scan = lua_actions.golden_scan()
    assert "p.cfg" in scan, "the scan must take the id from the run's own state"
    arm = lua_actions.golden_arm()
    assert str(lua_actions.GOLDEN_ZOMBIE_CFG) in arm, "the arm does not park the id"
    for banned in ("worldmap_icon", "pic_name", "huang"):
        assert banned not in scan, \
            f"the scan is looking at {banned} — a re-skin would break it"


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
    for name in ("golden_armed", "golden_queued", "golden_found", "golden_picked",
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
