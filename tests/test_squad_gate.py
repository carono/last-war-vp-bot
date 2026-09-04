r"""A squad that is out means SKIP — never a wait and never a poll (#2404).

The operator's rule, in their words: «Если мы отправили отряд по одному сценарию, другой
сценарий, использующий этот же отряд, просто должен перезапуститься позже или пропустить
свою очередь».

What that has to mean in code, and what this file pins:

  * the question is asked from the errand's OWN arguments — `squads` (a list) or `squad`
    (one) — so a new ability that picks squads is gated the day it is written;
  * it is asked BEFORE the client is claimed, so an errand with nothing to send never
    joins the queue at all (`panel/runtime/schedule.py::run_errand`);
  * a held errand RETURNS — there is no sleep, no retry loop and no clock armed for it;
  * one reading answers the whole question, not one per slot and not one per errand;
  * and a gate that cannot see never refuses: an unreadable squad state runs exactly as
    it did before this existed.

Needs no display and no game: the module under test is imported straight off its file,
so nothing of the panel package (and nothing of tkinter) is pulled in.

    python3 tests/test_squad_gate.py
"""
from __future__ import annotations

TIER = "pure"

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "squad_gate_under_test", _REPO / "panel" / "runtime" / "squad_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


class Reader:
    """A squad reader that answers off a dict and counts how often it was asked."""

    def __init__(self, home: dict) -> None:
        self.home = home
        self.asked: list = []

    def at_base(self, slot):
        self.asked.append(slot)
        return self.home.get(slot)


class Runtime:
    def __init__(self, reader) -> None:
        self.squads = reader


# ---------------------------------------------------------------------------
# which slots an errand spends
# ---------------------------------------------------------------------------
def test_the_slots_come_from_the_errands_own_arguments():
    assert gate.slots({"squads": [2, 3]}) == (2, 3)
    assert gate.slots({"squad": 1}) == (1,)
    assert gate.slots({"squads": ["4", 4, 2]}) == (4, 2), "repeats and strings"
    assert gate.slots({}) == ()
    assert gate.slots({"squads": []}) == ()


def test_a_slot_that_is_not_a_slot_is_dropped_rather_than_raised():
    # These come from a settings page and from an errand's JSON. A gate is not the place
    # to fail a run over one, and a slot nobody has would answer `None` and switch the
    # whole gate off for that errand.
    assert gate.slots({"squads": [1, 9, 0, -2, "x", None]}) == (1,)


# ---------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------
def test_every_slot_out_holds_the_errand():
    reader = Reader({1: False, 2: False})
    assert gate.held(Runtime(reader), {"squads": [1, 2]}) == (1, 2)


def test_one_slot_at_home_is_work_to_do():
    reader = Reader({1: False, 2: True})
    assert gate.held(Runtime(reader), {"squads": [1, 2]}) == (), \
        "an errand with a squad left to send must not be skipped"


def test_the_case_the_rule_was_written_for():
    # The arms race and the rally auto-join share slot 1. The join sent it; the arms race
    # fires while it is still marching and must skip in a fraction of a second — not
    # claim the client, not send, and not ask the game whether it came back.
    reader = Reader({1: False})
    away = gate.held(Runtime(reader), {"squad": 1})
    assert away == (1,)
    assert gate.said(away) == "1"


def test_a_gate_that_cannot_see_never_refuses():
    assert gate.held(Runtime(Reader({1: None})), {"squad": 1}) == (), \
        "no reading must never read as «the squad is out»"
    assert gate.held(Runtime(None), {"squad": 1}) == ()
    assert gate.held(Runtime(Reader({})), {"squads": [1, 2]}) == ()


def test_an_errand_that_spends_no_squad_is_never_held():
    reader = Reader({1: False, 2: False, 3: False, 4: False})
    assert gate.held(Runtime(reader), {"level": 30}) == ()
    assert reader.asked == [], "an errand with no squads must not cost a reading"


def test_a_reader_that_raises_is_not_the_reason_an_errand_did_not_run():
    class Broken:
        def at_base(self, slot):
            raise RuntimeError("no client")

    assert gate.held(Runtime(Broken()), {"squads": [1, 2]}) == ()


# ---------------------------------------------------------------------------
# neither a wait nor a poll
# ---------------------------------------------------------------------------
def test_the_verdict_asks_once_per_slot_and_stops_at_the_first_one_home():
    reader = Reader({1: True, 2: False})
    assert gate.held(Runtime(reader), {"squads": [1, 2]}) == ()
    assert reader.asked == [1], \
        "the answer was known at the first slot — asking on is a call for nothing"


def test_the_gate_holds_no_loop_and_no_sleep():
    """Read as a TREE, not as text — the prose in this module says «while» about the
    game, and a rule enforced by substring is a rule that fails on its own docstring."""
    import ast

    tree = ast.parse((_REPO / "panel" / "runtime" / "squad_gate.py")
                     .read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.While, ast.AsyncFor)), \
            "a loop in the squad gate — a held errand waits for its own next tick"
        if isinstance(node, ast.Call):
            said = ast.unparse(node.func)
            for banned in ("sleep", "arm", "after", "retry", "wait"):
                assert banned not in said.lower(), \
                    f"«{said}» in the squad gate — it answers and returns, it never waits"


def test_the_question_is_asked_before_the_client_is_claimed():
    source = (_REPO / "panel" / "runtime" / "schedule.py").read_text(encoding="utf-8")
    start = source.index("def run_errand")
    body = source[start:source.index("def _squads_away")]
    asked = body.index("_squads_away")
    for claim in ("self.rt.game.claim(", "self.rt.game.claim_soon("):
        assert asked < body.index(claim), \
            "the squad gate must be asked before the claim — an errand with nothing to " \
            "send may not join the queue at all"
    assert asked < body.index("_detached_errand"), \
        "a detached errand spends a squad too (the golden hunt)"


def test_the_line_it_says_is_a_key_in_every_locale():
    import json
    locales = sorted((_REPO / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11
    for path in locales:
        words = json.loads(path.read_text(encoding="utf-8"))
        said = words.get("timers.log.squad_busy")
        assert said, f"{path.name} has no «the squad is away» line"
        assert "{name}" in said and "{squads}" in said, path.name


def _main() -> int:
    bad = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("  ok  ", name)
        except AssertionError as exc:
            bad += 1
            print("  FAIL", name, exc)
    total = sum(1 for n in globals() if n.startswith("test_"))
    print(f"\n{total - bad}/{total} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
