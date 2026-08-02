r"""A scenario's own reason for failing has to reach whoever pressed it.

`create_rally.md` distinguishes six failures — no target of that level, a solo target,
an unknown squad, no squad screen, a screen that will not take the squad, everything
pressed and no banner. A caller that only sees a bool trades all of it for "it did not
work", which is why the «Ралли» tab could not be swapped onto `run_action` as the plan
first claimed (docs/research/panel-tabs-refactor.md §8).

`ActionRunner.play()` is the fix: it hands back the FAIL text the scenario itself gave.
No DSL change was needed — `FAIL "…"` already sets `ctx.fail_reason`, and the panel
already shows that text verbatim for every scheduled errand.

Runs anywhere: the scenarios here are written to a temp dir and use only LOG/FAIL/IF,
so nothing touches the game.

    python3 tests/test_panel_action_outcome.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_runtime  # noqa: E402
from panel.runtime.actions import ActionRunner, Outcome  # noqa: E402


def _runner(tmp: Path) -> ActionRunner:
    from lastwar_bot import script_engine as se
    se.ACTIONS_DIR = tmp
    se.DEV_ACTIONS_DIR = tmp / "dev"
    return ActionRunner(log=fake_runtime.RecordingBus())


def test_a_scenario_that_succeeds_reports_no_reason():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "fine.md").write_text('# Fine.\n\nLOG "all good"\n', encoding="utf-8")
        got = _runner(tmp).play("fine")
        assert got.ok is True, got
        assert got.reason == "", got
        assert bool(got) is True                    # usable as a plain condition


def test_the_scenarios_own_words_come_back():
    """Not "it failed" — the sentence the scenario chose."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "nope.md").write_text(
            '# Nope.\n\nFAIL "the search turned up no boss of level 35"\n',
            encoding="utf-8")
        got = _runner(tmp).play("nope")
        assert got.ok is False, got
        assert got.reason == "the search turned up no boss of level 35", got.reason
        assert not got


def test_two_different_failures_are_told_apart():
    """The whole point: six FAILs in create_rally.md must not collapse into one."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "picky.md").write_text(
            '# Picky.\n\n'
            'ARGS mode = 1\n'
            'IF mode == 1\n'
            '    FAIL "what the search returned cannot be rallied"\n'
            'FAIL "the squad screen would not take squad 2"\n',
            encoding="utf-8")
        runner = _runner(tmp)
        first = runner.play("picky", {"mode": 1})
        second = runner.play("picky", {"mode": 2})
        assert first.reason != second.reason, (first.reason, second.reason)
        assert "cannot be rallied" in first.reason, first.reason
        assert "would not take squad" in second.reason, second.reason


def test_a_failure_with_no_words_still_says_where():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "bare.md").write_text("# Bare.\n\nFAIL\n", encoding="utf-8")
        got = _runner(tmp).play("bare")
        assert got.ok is False
        assert "FAIL at line" in got.reason, got.reason


def test_a_scenario_that_blew_up_is_not_dressed_as_a_deliberate_failure():
    """A parse or runtime error is not a FAIL — there is no reason to quote.

    The caller can tell the two apart and say its own generic thing, instead of
    showing an empty quotation as if the scenario had chosen it.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "broken.md").write_text("# Broken.\n\nIF mode == whatever\n    LOG \"x\"\n",
                                       encoding="utf-8")
        got = _runner(tmp).play("broken")
        assert got.ok is False
        assert got.reason == "", got.reason


def test_run_is_unchanged_for_callers_that_only_branch():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "fine.md").write_text('# Fine.\n\nLOG "ok"\n', encoding="utf-8")
        (tmp / "bad.md").write_text('# Bad.\n\nFAIL "no"\n', encoding="utf-8")
        runner = _runner(tmp)
        assert runner.run("fine") is True
        assert runner.run("bad") is False


def test_outcome_is_falsy_but_carries_its_reason():
    out = Outcome(False, "because")
    assert not out and out.reason == "because"
    assert "because" in repr(out)


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
