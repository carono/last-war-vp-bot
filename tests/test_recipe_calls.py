r"""A `STOP` inside a CALLed recipe stops the CALLER, and that is a live bug shape (#2390).

No game and no window — this reads the recipes themselves. Run it anywhere::

    python3 tests/test_recipe_calls.py

`STOP` "unwinds all enclosing blocks and sub-actions" (docs/dsl.md) and leaves the halt
flag on the shared context, so a sub-recipe that ends its own «nothing to do» branch with
one ends the run that called it. It is easy to write and impossible to see: the sub-recipe
is correct read on its own, the caller is correct read on its own, and the two together
quietly do half the work from the second run of a day onwards.

That is exactly what happened to the golden-zombie hunt. `claim_free_stamina` took the
day's free energy and stopped on the day it had already been taken — which is every run
but the first — so the hunt would have halted before counting the purse, having killed
nothing, with «today's free energy has already been taken» as the last line in the log.

So: a recipe that anything CALLs must END its branches rather than STOP them, unless it is
on the list below WITH a reason. The list is not a licence — it is the audit.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIONS = _REPO_ROOT / "src" / "lastwar_bot" / "actions"

#: Recipes that are CALLed AND still contain a `STOP`, with what is known about each.
#: `perform_arms_race` calls four phase recipes in a row and each of them stops on «not my
#: phase» — so on hero day the drone recipe's stop would end the run before the hero one is
#: reached. It is not this task's to fix and it is not silently blessed either: it is
#: written down here so the next agent finds it already named.
KNOWN = {
    "arms_race_drone": "phase gate; see perform_arms_race — suspected same bug shape",
    "arms_race_hero": "phase gate; last of the four, so its stop ends nothing after it",
    "arms_race_speedup": "phase gate; see perform_arms_race",
    "arms_race_units": "phase gate; see perform_arms_race",
    # These two STOP as the LAST thing their caller would have done anyway, which is why
    # they cost nothing today and are on the audit rather than fixed: `attack_crystal_boss_daily`
    # ends with `CALL collect_crystal_boss_rewards`, and `buy_shop_goods` follows
    # `CALL buy_glitter_market_goods` with a `STOP` of its own. Add a statement after
    # either call and the stop starts eating it.
    "collect_crystal_boss_rewards": "stops on «no chest is waiting»; its one caller ends on the call",
    "buy_glitter_market_goods": "stops on «акция не идёт» / «не покупаю»; its one caller STOPs right after it",
}


def _recipes() -> dict:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(ACTIONS.glob("*.md"))}


def _called_by_somebody(all_text: dict) -> set:
    out = set()
    for text in all_text.values():
        for line in text.splitlines():
            m = re.match(r"\s*CALL\s+(\S+)", line)
            if m:
                out.add(m.group(1))
    return out


def _stop_lines(text: str) -> list:
    return [i for i, line in enumerate(text.splitlines(), 1)
            if re.match(r"\s*STOP\b", line)]


def test_every_called_recipe_exists():
    all_text = _recipes()
    missing = sorted(n for n in _called_by_somebody(all_text) if n not in all_text)
    assert not missing, f"CALLed recipes that do not exist: {missing}"


def test_a_called_recipe_does_not_stop_its_caller():
    all_text = _recipes()
    offenders = {}
    for name in sorted(_called_by_somebody(all_text)):
        if name in KNOWN or name not in all_text:
            continue
        lines = _stop_lines(all_text[name])
        if lines:
            offenders[name] = lines
    assert not offenders, (
        "these recipes are CALLed and contain a STOP, which halts the caller too — "
        f"end the branch with an IF instead: {offenders}")


def test_the_free_energy_claim_ends_rather_than_stops():
    text = _recipes()["claim_free_stamina"]
    assert not _stop_lines(text), (
        "claim_free_stamina STOPs again — the hunt CALLs it before counting the purse, "
        "and on every day whose claim is already taken that ends the hunt")
    assert re.search(r"^IF free_ready == 1$", text, re.M), (
        "the press is no longer behind its own gate — without it the claim is sent on a "
        "day it has already been taken")


def test_the_hunt_and_the_radar_both_take_the_free_energy():
    all_text = _recipes()
    for caller in ("attack_golden_zombies", "radar_full_cycle"):
        assert re.search(r"^CALL claim_free_stamina$", all_text[caller], re.M), (
            f"{caller} no longer takes the day's free energy before it spends any")


def test_the_known_list_is_still_true():
    """A KNOWN entry that has been fixed must leave the list, or it hides the next one."""
    all_text = _recipes()
    stale = sorted(n for n in KNOWN if n in all_text and not _stop_lines(all_text[n]))
    assert not stale, f"these no longer STOP and should leave KNOWN: {stale}"


def test_the_arena_recipes_end_their_branches_rather_than_stop():
    """#2688: both are CALLed by `arena_battles`, which asks which event is open."""
    all_text = _recipes()
    for name in ("arena_3v3_battles", "storm_arena_battles"):
        assert not _stop_lines(all_text[name]), (
            f"{name} STOPs again — `arena_battles` CALLs it, so the halt is the caller's too")


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
