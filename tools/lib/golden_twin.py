r"""A SECOND golden-zombie chain, so two squads can hunt at once (#1702).

The chain keeps its whole run in ONE table in the game VM — `DataCenter.__lw_gold`:
the queue, the anchor, the chosen target, the order in flight. That is exactly right for
one squad and fatal for two: a second run of the same recipes would overwrite the first
one's target between statements, and the two squads would end up ordered at each other's
zombies and recalling each other's marches.

Making the state per-squad would mean threading a key through some sixty builders, and
the operator's need was «сжечь энергию сегодня». So the twin is made the mechanical way
instead: **every reference to the state table is renamed**, and nothing else changes.
`__lw_gold` -> `__lw_gold2` covers the table itself and every argument parked beside it
(`__lw_gold_squad`, `__lw_gold_back`, `__lw_gold_ws`, …), because all of them are built
from the same constant. The twin therefore runs the SAME logic over its own state, and
the two runs share nothing except the client and the map.

What they must NOT share is a target, and that is the one thing added rather than
renamed: :data:`CLAIMS` is a table both runs write to, deliberately spelled so the rename
does not touch it, and the pick skips a tile the other run has already been sent at.

    python3 tools/lib/golden_twin.py --write    # regenerate the twin recipes
    python3 tools/lib/golden_twin.py            # …and fail if they have drifted

`tests/test_golden_zombies.py` runs the second form, so a change to the original chain
that has not been mirrored is a red test rather than a squad hunting yesterday's logic.
"""
from __future__ import annotations

import os
import re
import sys

#: The state table the twin uses instead of `DataCenter.__lw_gold`.
TWIN_STATE = "__lw_gold2"

#: Where the two runs agree not to tread on each other. NOT renamed by the transform —
#: the name deliberately avoids the `__lw_gold` prefix, so both copies see one table.
CLAIMS = "__lw_zclaims"

#: The recipes that make up the chain, and what the twin's copy is called.
RECIPES = {
    "attack_golden_zombies": "attack_golden_zombies2",
    "golden_attack_target": "golden2_attack_target",
    "golden_choose_a_target": "golden2_choose_a_target",
    "golden_find_target": "golden2_find_target",
    "golden_forget_target": "golden2_forget_target",
    "golden_goto_target": "golden2_goto_target",
    "golden_judge_the_kill": "golden2_judge_the_kill",
    "golden_recall_squad": "golden2_recall_squad",
    "golden_send_the_squad": "golden2_send_the_squad",
    "golden_squad_report": "golden2_squad_report",
    "golden_verify_order": "golden2_verify_order",
    "golden_wait_for_the_march": "golden2_wait_for_the_march",
}

_TAP = re.compile(r"\b(TAP|CALL) golden_")
_CALL_CHAIN = re.compile(r"\bCALL golden_")


def twin_lua(text: str) -> str:
    """The one transform: every reference to the run's state table is renamed."""
    return text.replace("__lw_gold", TWIN_STATE)


def twin_recipe(text: str) -> str:
    """A recipe's twin — its state renamed, and its presses and calls pointed at twins."""
    out = twin_lua(text)
    out = out.replace("TAP golden_", "TAP golden2_")
    out = out.replace("CALL golden_", "CALL golden2_")
    # …and the two title lines say which chain this is, because the panel lists a
    # recipe by its title and two identical ones are indistinguishable in the window.
    lines = out.split("\n")
    for i, line in enumerate(lines[:3]):
        if line.startswith("# ru:"):
            lines[i] = line.rstrip() + " (второй отряд)"
        elif line.startswith("# "):
            lines[i] = line.rstrip() + " (the second squad)"
    return "\n".join(lines)


def actions_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "src", "lastwar_bot", "actions")


def expected() -> dict:
    """`twin file name -> what its contents should be`, straight off the originals."""
    out = {}
    for src, dst in RECIPES.items():
        path = os.path.join(actions_dir(), src + ".md")
        with open(path, encoding="utf-8") as fh:
            out[dst] = twin_recipe(fh.read())
    return out


def drift() -> list:
    """Every twin whose file is not what the original says it should be."""
    bad = []
    for name, want in expected().items():
        path = os.path.join(actions_dir(), name + ".md")
        try:
            with open(path, encoding="utf-8") as fh:
                have = fh.read()
        except FileNotFoundError:
            bad.append(name)
            continue
        if have != want:
            bad.append(name)
    return bad


def write() -> int:
    for name, text in expected().items():
        with open(os.path.join(actions_dir(), name + ".md"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(text)
    return len(RECIPES)


def main(argv) -> int:
    if "--write" in argv:
        print("wrote %d twin recipe(s)" % write())
        return 0
    bad = drift()
    for name in bad:
        print("%s.md is not what the original says it should be" % name)
    if bad:
        print("%d stale twin(s) — run with --write" % len(bad))
        return 1
    print("every twin is in step with its original")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
