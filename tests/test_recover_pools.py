r"""«Вернуть» — the pools a secret task or a truck left behind, checked without a game (#2605).

Run it anywhere::

    python3 tests/test_recover_pools.py

Both windows carry the button and one manager answers for both, so the two halves are
written once and told apart by a `kind`. What is pinned here is the part a live run cannot
tell you it got wrong:

* **the Lua compiles.** A claim that does not parse fails as a line in a log nobody reads
  at the time, and the pools go on expiring.
* **a closed feature answers `nil`, never `0`.** «Nothing to take» and «this account
  cannot take anything» must not draw the same, which is the trap the locked trade station
  set once already (`docs/research/truck-dispatch.md`).
* **a claim is judged by the LIST, not by the send.** Both recipes ask for the pools
  again and read the count a second time — #2585 is the run that reported success while
  sending nothing at all.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools" / "lib"))
sys.path.insert(0, str(_REPO_ROOT))

import lua_actions                                        # noqa: E402

ACTIONS = _REPO_ROOT / "src" / "lastwar_bot" / "actions"
KINDS = ("tasks", "trucks")


def _buttons() -> dict:
    import game_buttons

    return game_buttons.BUTTONS


def test_the_lua_of_both_halves_compiles():
    """Every expression and every press, through a real Lua parser."""
    try:
        import lupa
    except ImportError:                                    # pragma: no cover
        print("  (no lupa here — the compile half is skipped)")
        return
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    chunks = [("ask", lua_actions.recover_pools_ask())]
    for kind in KINDS:
        chunks.append((kind + " left",
                       "local x = " + lua_actions.recover_pools_left(kind)))
        chunks.append((kind + " claim", lua_actions.recover_claim_all(kind)))
        chunks.append((kind + " sent",
                       "local x = " + lua_actions.recover_pools_sent(kind)))
    bad = []
    for name, chunk in chunks:
        try:
            rt.compile(chunk)
        except Exception as exc:                           # noqa: BLE001
            bad.append(f"{name}: {exc}")
    assert not bad, "these recover chunks are not valid Lua:\n" + "\n".join(bad)


def test_a_closed_feature_answers_a_dash_and_not_a_zero():
    """`IsDispatchRecoverOpen` / `IsTrainRecoverOpen` gate the count, and the miss is nil."""
    for kind in KINDS:
        expr = lua_actions.recover_pools_left(kind)
        assert "if not open then return nil end" in expr, kind
    assert "IsDispatchRecoverOpen" in lua_actions.recover_pools_left("tasks")
    assert "IsTrainRecoverOpen" in lua_actions.recover_pools_left("trucks")


def test_only_an_unclaimed_pool_is_counted_and_only_one_is_claimed_per_send():
    """A claimed pool comes back with `state = 1`; the claim takes one `customId`."""
    for kind in KINDS:
        assert "row.state==nil" in lua_actions.recover_pools_left(kind), kind
        claim = lua_actions.recover_claim_all(kind)
        assert "row.state==nil" in claim, kind
        assert "(row.customId)" in claim, kind
    assert "ClaimDispatchRecoverReward" in lua_actions.recover_claim_all("tasks")
    assert "ClaimTrainRecoverReward" in lua_actions.recover_claim_all("trucks")


def test_the_kind_is_one_of_two_and_a_typo_is_refused():
    """A caller that invents a third kind fails loudly rather than building empty Lua."""
    for maker in (lua_actions.recover_pools_left, lua_actions.recover_claim_all,
                  lua_actions.recover_pools_sent):
        try:
            maker("wagons")
        except ValueError:
            continue
        raise AssertionError(maker.__name__ + " accepted a kind that does not exist")


def test_the_three_presses_are_declared_and_relay_what_they_did():
    """A button per half plus the one that asks — and each claim says what it sent."""
    buttons = _buttons()
    for name in ("ask_recover_pools", "claim_recover_tasks", "claim_recover_trucks"):
        assert name in buttons, name
    assert buttons["claim_recover_tasks"].relay == ("rec_tasks",)
    assert buttons["claim_recover_trucks"].relay == ("rec_trucks",)


def test_both_recipes_claim_and_then_count_again():
    """The two abilities that own the two windows, and neither believes its own send."""
    for recipe, button in (("collect_secret_tasks.md", "claim_recover_tasks"),
                           ("send_trucks.md", "claim_recover_trucks")):
        text = (ACTIONS / recipe).read_text(encoding="utf-8")
        assert "TAP " + button in text, recipe
        # asked for before the press and again after it, so the count that is reported
        # is the LIST's rather than the send's
        assert text.count("TAP ask_recover_pools") >= 2, recipe
        assert "INTO recover_was" in text and "INTO recover_left" in text, recipe


def test_the_reading_reaches_the_daily_checklist_for_both_cards():
    """The two live numbers the cards draw come off the one chunk everything rides on."""
    text = (ACTIONS / "read_daily_checklist.md").read_text(encoding="utf-8")
    for field in ("recover_tasks", "recover_trucks"):
        assert "put('%s'," % field in text, field
    assert "IsDispatchRecoverOpen" in text and "IsTrainRecoverOpen" in text


def _run_standalone() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
