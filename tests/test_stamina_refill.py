"""The diamond refill of march energy, and the memory that switches it off (#2390).

No game and no panel window: the recipe is parsed off disk, the press is the Lua the
catalogue holds, and the memory runs against a real database in a temporary folder.

    C:\\Python312\\python.exe tests\\test_stamina_refill.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT))

from lastwar_bot import script_engine as engine   # noqa: E402
import game_buttons                               # noqa: E402
import lua_actions                                # noqa: E402

ACTIONS = ROOT / "src" / "lastwar_bot" / "actions"


def _parsed(name: str):
    src = engine.prepare_source((ACTIONS / f"{name}.md").read_text(encoding="utf-8"), {})
    if isinstance(src, tuple):
        src = src[0]
    return engine.parse_text(src)


def _text(name: str) -> str:
    return (ACTIONS / f"{name}.md").read_text(encoding="utf-8")


def test_the_recipe_parses_and_presses_only_a_catalogued_button():
    stmts = _parsed("buy_stamina_refill")
    assert stmts, "the refill parsed to nothing"
    body = _text("buy_stamina_refill")
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("TAP "):
            name = line.split()[1]
            assert name in game_buttons.BUTTONS, f"{name} is not in the catalogue"


def test_it_never_stops_its_caller():
    """It is CALLed by the hunt and by the radar, and `STOP` unwinds the caller too."""
    body = _text("buy_stamina_refill")
    for line in body.splitlines():
        assert not line.strip().startswith("STOP"), (
            "a STOP here would halt the hunt on every day the refill was already bought")


def test_the_gate_is_the_count_of_refills_and_never_a_guessed_price():
    """The price is unreadable, so the recipe must not pretend to have read one."""
    gate = lua_actions.stamina_refill_bought_today()
    assert "playerStaminaGoldNum" in gate
    assert "GetTomorrowZero" in gate, "the count is only good with the server's own day"
    body = _text("buy_stamina_refill")
    assert "refills_today == 0" in body, "it must buy only when none was bought today"


def test_the_price_is_read_off_the_purse_after_the_fact():
    paid = lua_actions.stamina_refill_paid()
    assert "LuaEntry.Player.gold" in paid, "diamonds are `gold` on the player"
    assert "return -1" in paid, "an unknowable price must not read as free"


def test_the_hunt_and_the_radar_take_the_free_one_first():
    for name in ("attack_golden_zombies", "attack_golden_zombies2", "radar_full_cycle"):
        body = _text(name)
        free = body.index("CALL claim_free_stamina")
        buy = body.index("CALL buy_stamina_refill")
        assert free < buy, f"{name} buys before it claims the free one"


def _store(tmp: str):
    from panel.runtime import store as storemod
    return storemod.Store(os.path.join(tmp, storemod.DB_FILE), "default")


def test_remember_and_recall_survive_a_new_run():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        try:
            ctx = engine.Context(hwnd=0, store=store)
            run = engine.Interpreter(ctx)
            for stmt in engine.parse_text("RECALL nothing_yet INTO seen\n"):
                run._run_stmt(stmt)
            assert ctx.vars["seen"] == "", "an unwritten fact must read as empty"

            ctx.vars["paid"] = "410"
            for stmt in engine.parse_text("REMEMBER stamina_refill_block FROM paid\n"):
                run._run_stmt(stmt)

            # …and a WHOLLY NEW run, the way the next lap of the panel would see it.
            later = engine.Context(hwnd=0, store=store)
            engine.Interpreter(later)._run_stmt(
                engine.parse_text("RECALL stamina_refill_block INTO blocked\n")[0])
            assert later.vars["blocked"] == "410"
        finally:
            store.close()


def test_a_run_with_no_profile_remembers_nothing_and_does_not_crash():
    ctx = engine.Context(hwnd=0)
    run = engine.Interpreter(ctx)
    run._run_stmt(engine.parse_text("REMEMBER x = 1\n")[0])
    run._run_stmt(engine.parse_text("RECALL x INTO y\n")[0])
    assert ctx.vars["y"] == ""


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as exc:                       # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {exc}")
    print("—", "all green" if not failed else f"{failed} failed")
    sys.exit(1 if failed else 0)
