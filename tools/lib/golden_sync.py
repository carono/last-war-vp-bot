r"""Keep the golden-zombie recipes carrying the CURRENT Lua of the presses they read.

The DSL has no include: a `READ_LUA <expr> INTO name` line holds a COPY of an expression
that also lives in `tools/lib/lua_actions.py`, and a copy goes stale in silence. It has
done, twice (#1702) — a recipe reading a proof the module had already corrected behaves
exactly like a recipe with a bug, and the diff that would show it is one line of Lua
inside a line of Lua.

So the mapping between a recipe's variable name and the module function that owns it is
written down ONCE, here, and two things use it: this module rewrites the recipes, and
`tests/test_golden_zombies.py` fails when one of them has drifted.

    python3 tools/lib/golden_sync.py            # report what has drifted
    python3 tools/lib/golden_sync.py --write    # …and put the module's copy back

A variable NOT in the table is left alone: plenty of them are one-off readings that
belong to the recipe and to nothing else (`far`, `swept`, `fill_count`).
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lua_actions  # noqa: E402

#: `INTO <name>` -> the `lua_actions` function that owns that expression.
OWNERS = {
    "armed": "golden_armed",
    "arrived": "golden_arrived",
    "attacks": "golden_attacks",
    "cost": "golden_attack_cost",
    "energy": "golden_energy",
    "eta_left": "golden_eta_left",
    "found": "golden_found",
    "go": "golden_can_go",
    "golden_report": "golden_report",
    "gone": "golden_gone",
    "here": "golden_here",
    "last_one": "golden_last_march",
    "launched": "golden_launched",
    "looked_moved": "golden_looked_moved",
    "marching": "golden_march_in_flight",
    "misses": "golden_misses",
    "needs_refresh": "golden_needs_refresh",
    "needs_uuid": "golden_needs_uuid",
    "pick_report": "golden_pick_report",
    "picked": "golden_picked",
    "queued": "golden_queued",
    "refreshed": "golden_refresh_done",
    "ride_report": "golden_approach_report",
    "riding": "golden_approach_planned",
    "sent": "golden_send_now",
    "spent": "golden_spent",
    "squad_free": "golden_squad_free",
    "stuck": "golden_stuck",
    "vanished": "golden_vanished",
}

#: The recipes this covers — the chain and its bricks.
RECIPES = ("attack_golden_zombies", "golden_wait_for_the_march", "golden_judge_the_kill",
           "golden_choose_a_target", "golden_send_the_squad", "golden_attack_target",
           "golden_verify_order")

_LINE = re.compile(r"^(\s*)READ_LUA (.*) INTO (\w+)\s*$")

#: `READ_LUA (0) INTO picked` is not a stale copy of anything — it is the recipe
#: SETTING a flag, which is how the DSL assigns. Those lines are left alone.
_LITERAL = re.compile(r"^\(\s*-?\d+(?:\.\d+)?\s*\)$")


def actions_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "src", "lastwar_bot", "actions")


def drift(text: str) -> list:
    """Every `(line_no, name)` in this source whose copy is not the module's any more."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        m = _LINE.match(line)
        if not m:
            continue
        owner = OWNERS.get(m.group(3))
        if _LITERAL.match(m.group(2).strip()):
            continue
        if owner and m.group(2) != getattr(lua_actions, owner)():
            out.append((n, m.group(3)))
    return out


def sync(text: str) -> str:
    """The same source with every owned expression replaced by the module's copy."""
    out = []
    for line in text.splitlines(True):
        m = _LINE.match(line.rstrip("\n"))
        owner = OWNERS.get(m.group(3)) if m else None
        if owner and _LITERAL.match(m.group(2).strip()):
            owner = None
        if owner:
            line = "%sREAD_LUA %s INTO %s\n" % (m.group(1), getattr(lua_actions, owner)(),
                                               m.group(3))
        out.append(line)
    return "".join(out)


def main(argv) -> int:
    write = "--write" in argv
    bad = 0
    for name in RECIPES:
        path = os.path.join(actions_dir(), name + ".md")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        stale = drift(text)
        if not stale:
            continue
        bad += len(stale)
        for line_no, var in stale:
            print("%s.md:%d  %s is not the module's copy" % (name, line_no, var))
        if write:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(sync(text))
    if bad and write:
        print("rewritten %d expression(s)" % bad)
        return 0
    if bad:
        print("%d stale expression(s) — run with --write" % bad)
        return 1
    print("every recipe carries the module's copy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
