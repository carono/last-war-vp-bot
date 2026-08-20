r"""`DETACH` — the scenario that must not hold the rest of the panel up (#1702).

No game and no window: the declaration is read off the DSL, the priority is arithmetic in
the claim registry, and the two places that act on it are read out of their own source.
Run it anywhere::

    python3 tests/test_detach.py

What is worth pinning here is the promise the declaration makes, which is easy to ship
half of:

  * a scenario declares it ITSELF — the length of a run is a property of the ability, not
    of the button that happened to press it, and the same file is played by a timer, by
    the window and by the phone;
  * `DETACH` is a declaration, not a step: it is stripped before parsing, exactly as
    `ARGS` is, so it cannot become a statement that runs at some point in the middle;
  * a detached run claims the client BELOW an ordinary errand, so everything outranks it
    — that is what «остальные сценарии продолжают работать штатно» means when one client
    is driven by one run at a time;
  * and it carries the step-aside hook. Without it the priority is a note nobody reads:
    the run holds the claim until it ends and a ten-minute march is a ten-minute queue.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "src", _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lastwar_bot import script_engine as engine  # noqa: E402
from panel.runtime import claims  # noqa: E402

HOST = _REPO_ROOT / "panel" / "runtime" / "host.py"
SCHEDULE = _REPO_ROOT / "panel" / "runtime" / "schedule.py"
ACTIONS = _REPO_ROOT / "panel" / "runtime" / "actions.py"
DSL_DOC = _REPO_ROOT / "docs" / "dsl.md"


def test_a_scenario_declares_it_and_the_declaration_is_not_a_step():
    text = "ARGS squad = 1\n\nDETACH\n\nLOG \"hello\"\n"
    assert engine.declares_detach(text)
    body, _vars = engine.prepare_source(text, None)
    assert "DETACH" not in body, "the declaration was left in the body"
    statements = engine.parse_text(body)
    assert len(statements) == 1, "DETACH became a statement of its own"


def test_a_scenario_without_it_is_not_detached():
    assert not engine.declares_detach("LOG \"hello\"\nTAP heal_all\n")
    assert not engine.action_detached("heal_units")
    assert not engine.action_detached("no_such_scenario_at_all")


def test_the_declaration_is_case_insensitive_like_every_other_keyword():
    assert engine.declares_detach("detach\n")
    assert engine.declares_detach("  Detach  \n")
    assert not engine.declares_detach("DETACHED\n"), \
        "a word that merely starts with it is not the declaration"


def test_the_player_reads_it_off_the_file():
    from panel.runtime.actions import ActionRunner
    assert ActionRunner.detached("attack_golden_zombies")
    assert not ActionRunner.detached("heal_units")


def test_everything_outranks_a_detached_run():
    assert claims.DETACHED < claims.BACKGROUND < claims.EXPRESS < claims.HUMAN
    key = ("test-detach", 1)
    claims.clear()
    try:
        assert claims.acquire(key, "chain", claims.DETACHED) is None
        assert claims.level(key) == claims.DETACHED
        # …and an ORDINARY errand is enough to make it step aside. That is the whole
        # difference from a background run, which a timer may not push out of the way.
        token = claims.demand(key, claims.BACKGROUND, "timer")
        assert claims.wanted(key, claims.DETACHED) == "timer"
        claims.withdraw(key, token)
        assert claims.wanted(key, claims.DETACHED) is None
    finally:
        claims.clear()


def test_the_press_drops_the_priority_and_hands_over_the_step_aside_hook():
    src = HOST.read_text(encoding="utf-8")
    assert "self.actions.detached(name)" in src, \
        "play_async never asks whether the scenario is detached"
    assert "priority = claims.DETACHED" in src, \
        "a detached run claims the client at an ordinary priority"
    assert "self.yield_hook(tag) if detached else None" in src, \
        "a detached run carries no step-aside hook — the priority is a note nobody reads"
    assert re.search(r"yield_to=step_aside", src), \
        "the hook is built and never handed to the run"
    # …and `play` has to take it by name: it always builds the context itself, so a hook
    # left in **kw would reach `run`, which has a context already and drops it.
    assert "yield_to=None, **kw" in ACTIONS.read_text(encoding="utf-8")


def test_the_clock_does_not_block_on_a_detached_errand():
    src = SCHEDULE.read_text(encoding="utf-8")
    assert "_detached_errand" in src and "_run_detached" in src, \
        "the scheduler runs a detached errand on its own thread"
    assert "claims.level(self.rt.game.endpoint()) < claims.BACKGROUND" in src, \
        "an ordinary errand is refused while a detached run holds the client"
    assert "self.rt.play_async(step, self.args(errand), tag=\"timer\"" in src


def test_the_primitive_is_documented():
    doc = DSL_DOC.read_text(encoding="utf-8")
    assert "### `DETACH`" in doc, "the declaration is not in docs/dsl.md"
    assert "claims.DETACHED" in doc, "the doc does not say what it costs the run"


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
