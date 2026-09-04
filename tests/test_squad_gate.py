r"""A squad that is out means SKIP — never a wait and never a poll (#2404).

The operator's rule, in their words: «Если мы отправили отряд по одному сценарию, другой
сценарий, использующий этот же отряд, просто должен перезапуститься позже или пропустить
свою очередь».

What that has to mean in code, and what this file pins:

  * the question is asked from the errand's OWN arguments — `squads` (a list) or `squad`
    (one) — so a new ability that picks squads is gated the day it is written;
  * it is asked where every other precondition is — `Schedule.gate`, before anything is
    claimed, a context made or a scenario parsed — so an errand with nothing to send
    never joins the queue at all;
  * a held errand RETURNS — there is no sleep, no retry loop and no clock armed for it;
  * **it never reads the game.** A refused errand is parked and re-offered, so a gate
    that took a reading would become a question at the client every few seconds. It
    decides off the reading the panel already has, and a reading that is missing or
    older than `FRESH_SEC` decides nothing at all;
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


class Squad:
    def __init__(self, at_base) -> None:
        self.at_base = at_base


class State:
    """What `SquadReader.latest()` hands back, as far as the gate is concerned."""

    def __init__(self, home: dict, ok: bool = True, age: float = 1.0) -> None:
        self.home, self.ok, self._age = home, ok, age

    def age(self) -> float:
        return self._age

    def squad(self, slot):
        at_base = self.home.get(slot)
        return None if at_base is None else Squad(at_base)


class Reader:
    def __init__(self, state) -> None:
        self.state = state
        self.reads = 0

    def latest(self):
        return self.state

    def read(self, force: bool = False):      # the gate must never reach for this
        self.reads += 1
        raise AssertionError("the squad gate read the game — it may only look at the "
                             "reading the panel already has")

    at_base = read


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
    reader = Reader(State({1: False, 2: False}))
    assert gate.held(Runtime(reader), {"squads": [1, 2]}) == (1, 2)


def test_one_slot_at_home_is_work_to_do():
    reader = Reader(State({1: False, 2: True}))
    assert gate.held(Runtime(reader), {"squads": [1, 2]}) == (), \
        "an errand with a squad left to send must not be skipped"


def test_the_case_the_rule_was_written_for():
    # The arms race and the rally auto-join share slot 1. The join sent it; the arms race
    # fires while it is still marching and must skip in a fraction of a second — not
    # claim the client, not send, and not ask the game whether it came back.
    reader = Reader(State({1: False}))
    away = gate.held(Runtime(reader), {"squad": 1})
    assert away == (1,)
    assert gate.said(away) == "1"


def test_a_gate_that_cannot_see_never_refuses():
    assert gate.held(Runtime(Reader(State({1: None}))), {"squad": 1}) == (), \
        "a slot the reading does not name must never read as «the squad is out»"
    assert gate.held(Runtime(None), {"squad": 1}) == ()
    assert gate.held(Runtime(Reader(None)), {"squad": 1}) == (), "nothing read yet"
    assert gate.held(Runtime(Reader(State({1: False}, ok=False))), {"squad": 1}) == ()
    assert gate.held(Runtime(Reader(State({}))), {"squads": [1, 2]}) == ()


def test_a_reading_too_old_to_trust_decides_nothing():
    stale = State({1: False}, age=gate.FRESH_SEC + 1)
    assert gate.held(Runtime(Reader(stale)), {"squad": 1}) == (), \
        "a squad that may have come home an hour ago must not hold the next tick"
    fresh = State({1: False}, age=gate.FRESH_SEC - 1)
    assert gate.held(Runtime(Reader(fresh)), {"squad": 1}) == (1,)


def test_the_gate_never_reads_the_game():
    # `Reader.read` / `at_base` raise: a refused errand is parked and re-offered, so a
    # gate that reached for the client would be a poll invented in the name of the rule
    # against waiting.
    reader = Reader(State({1: False, 2: False}))
    assert gate.held(Runtime(reader), {"squads": [1, 2]}) == (1, 2)
    assert reader.reads == 0


def test_an_errand_that_spends_no_squad_is_never_held():
    reader = Reader(State({1: False, 2: False, 3: False, 4: False}))
    assert gate.held(Runtime(reader), {"level": 30}) == ()


def test_a_reader_that_raises_is_not_the_reason_an_errand_did_not_run():
    class Broken:
        def latest(self):
            raise RuntimeError("no client")

    assert gate.held(Runtime(Broken()), {"squads": [1, 2]}) == ()


# ---------------------------------------------------------------------------
# neither a wait nor a poll
# ---------------------------------------------------------------------------
def test_one_reading_answers_the_whole_question():
    reader = Reader(State({1: True, 2: False}))
    assert gate.held(Runtime(reader), {"squads": [1, 2]}) == ()
    assert reader.reads == 0


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


def test_the_question_is_asked_where_the_other_preconditions_are():
    source = (_REPO / "panel" / "runtime" / "schedule.py").read_text(encoding="utf-8")
    start = source.index("    def gate(self")
    body = source[start:source.index("    def _refresh_day")]
    assert "_squads_away" in body, \
        "the squad question belongs with every other «may this even start» — asked " \
        "before anything is claimed, a context is made or a scenario is parsed"
    assert "if check is None and self._squads_away(name)" in body, \
        "an errand with a precondition of its own answers this better — the rally " \
        "auto-join asks the game at the moment of the decision — and two answers to " \
        "one question hold a run by the worse-informed of them"
    for claimed in ("claim(", "claim_soon(", "actions.context("):
        assert claimed not in body, \
            f"«{claimed}» while merely deciding whether to start — the whole point is " \
            "that a held errand costs nothing"
    run = source[source.index("    def run_errand"):source.index("    def _squads_away")]
    assert "_squads_away" not in run, \
        "asked twice is asked in the wrong place once"


def test_the_reading_is_refreshed_by_an_event_and_never_by_a_clock():
    source = (_REPO / "panel" / "runtime" / "schedule.py").read_text(encoding="utf-8")
    body = source[source.index("    def _squads_moved"):source.index("    def _is_recovery")]
    code = "\n".join(line for line in body.split("\n")
                     if not line.lstrip().startswith("#"))
    assert "refresh_async" in code
    for banned in ("tick.arm", "time.sleep", "while ", "after("):
        assert banned not in code, \
            f"«{banned}» — the squad reading follows the event that moved a squad, " \
            "never a clock of its own"
    for hook in ("self._squads_moved(name)",):
        assert source.count(hook) == 2, \
            "both the ordinary path and the detached one must say a squad has moved"


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
