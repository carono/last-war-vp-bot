r"""Unit tests for `actions/create_rally.md` — raising a rally as a scenario.

The recipe is driven with a *fake* Lua evaluator that answers its readings the way a
game would, so these need no game, no daemon and no Wireshark, and run anywhere. What
they check is the thing a live run cannot check cheaply: that the flow presses in the
right ORDER, stops at the right STEP when a step goes wrong, and never claims a rally
the game did not show.

    python3 tests/test_rally_create.py     # standalone, prints PASS/FAIL
    pytest tests/test_rally_create.py      # or under pytest

Exit codes (standalone): 0 = passed, 1 = failed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "src", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lastwar_bot import script_engine as se  # noqa: E402

# Which reading a chunk is, by a fragment only that reading contains. Order matters:
# the squad-pick check also mentions the formation windows, so it is matched first.
_READS = (
    ("scene", "SceneUtils.GetIsInWorld"),
    ("armed", ".formation ~= nil) and 1 or 0"),
    ("found", "GetPointBtnEnumName"),
    ("picked", "selectFormationUuid"),
    ("panel", "_isformation(UIManager"),
    ("raised", "GetOwnerMarches"),
)

# Which press a chunk is, by the marker its Lua logs.
_PRESSES = (
    ("arm", "ACT rally_arm"),
    ("search_window", "UIWindowNames.UISearch"),
    ("search", "ACT rally_search"),
    ("banner", "ACT rally_banner"),
    ("squad", "ACT rally_squad"),
    ("launch", "ACT rally_launch"),
    ("close", "CloseSelf"),
)


def _classify(chunk: str, table) -> str | None:
    for name, needle in table:
        if needle in chunk:
            return name
    return None


class FakeRallyGame:
    """Replays a scripted answer per reading, and records every press.

    Each reading is given a list of values returned in turn; the last one repeats, so
    a poll that never moves is written as a single value rather than twelve copies.
    """

    def __init__(self, **answers) -> None:
        self.chunks: list[str] = []
        self.presses: list[str] = []
        self.answers = {k: list(v) if isinstance(v, list) else [v]
                        for k, v in answers.items()}

    def run(self, chunk, marker=None, settle=1.4):
        self.chunks.append(chunk)
        if marker == "RLUA":
            kind = _classify(chunk, _READS)
            queue = self.answers.get(kind)
            if not queue:
                raise AssertionError(f"the recipe read something unscripted: {chunk[:120]}")
            val = queue.pop(0) if len(queue) > 1 else queue[0]
            return [f"RLUA {val}"]
        press = _classify(chunk, _PRESSES)
        if press:
            self.presses.append(press)
        return []


def _run(variables=None, **answers):
    """Run the recipe against a fake game; return (ok, fake, log lines).

    Sleeps are stubbed out — the recipe's waits are what make a real run correct and
    what would make this test take a minute.
    """
    answers.setdefault("scene", "world")
    fake = FakeRallyGame(**answers)
    log: list[str] = []
    ctx = se.Context(hwnd=0, on_event=log.append, evaluator=fake)
    if variables:
        ctx.vars.update(variables)
    old_sleep = se.time.sleep
    se.time.sleep = lambda _s: None
    try:
        ok = se.run_action("create_rally", hwnd=0, ctx=ctx)
    finally:
        se.time.sleep = old_sleep
    return ok, fake, log


# --- the recipe exists and says what it takes -------------------------------------

def test_the_recipe_is_a_blessed_scenario_with_three_arguments():
    """It has to be in actions/ (not dev/) for the Scenarios tab to list it by default."""
    path = se.ACTIONS_DIR / "create_rally.md"
    assert path.exists(), "actions/create_rally.md is missing"
    defaults, _ = se.extract_defaults(path.read_text(encoding="utf-8"))
    assert defaults == {"squad": 1, "level": 35, "target": "boss"}, defaults


def test_the_readings_match_the_library():
    """The expressions inlined in the recipe are the ones lua_actions defines.

    They are written out in full in the recipe so it reads as one flow, which only
    stays true while the two agree — this is the check that they do.
    """
    import lua_actions as la

    source = (se.ACTIONS_DIR / "create_rally.md").read_text(encoding="utf-8")
    assert source.count(la.rally_armed()) == 1
    # The three polled readings appear twice each: once before the loop, once inside it.
    assert source.count(la.rally_target_state()) == 2
    assert source.count(la.rally_panel_ready()) == 2
    assert source.count(la.rally_raised()) == 2
    assert source.count(la.rally_squad_picked()) == 1


def test_every_button_it_presses_exists():
    import game_buttons as gb

    for name in ("rally_arm", "rally_search_window", "rally_search",
                 "rally_banner", "rally_squad", "rally_launch", "close"):
        assert gb.get(name) is not None, f"button {name!r} is missing from the catalogue"


# --- the happy path ---------------------------------------------------------------

def test_a_rally_goes_out_in_the_right_order():
    ok, fake, _log = _run(
        armed=1, found=[0, 1], panel=[0, 1], picked=1, raised=[0, 1],
    )
    assert ok is True
    assert fake.presses == ["arm", "search_window", "search", "banner", "squad", "launch"], \
        fake.presses


def test_it_brings_the_map_up_first():
    """The «лупа» is the world map's search — in the city there is no window to type in."""
    ok, fake, _log = _run(
        scene=["city", "world"], armed=1, found=1, panel=1, picked=1, raised=1,
    )
    assert ok is True
    assert any("ChangeToWorld" in c for c in fake.chunks), \
        "the recipe stayed in the city and searched anyway"


def test_the_arguments_reach_the_game():
    ok, fake, _log = _run(
        {"squad": 3, "level": 120, "target": "monster"},
        armed=1, found=1, panel=1, picked=1, raised=1,
    )
    assert ok is True
    parked = [c for c in fake.chunks if "__lw_rally_create = {" in c]
    assert len(parked) == 1, fake.chunks
    assert "squad = 3" in parked[0] and "level = 120" in parked[0] \
        and 'kind = "monster"' in parked[0], parked[0]


# --- every way it is allowed to give up -------------------------------------------

def test_an_unknown_squad_stops_before_anything_is_opened():
    """A squad the game does not know must not leave a target popup open on the map."""
    ok, fake, _log = _run(armed=0)
    assert ok is False
    assert fake.presses == ["arm"], fake.presses


def test_a_search_that_finds_nothing_fails_and_tidies_up():
    ok, fake, _log = _run(armed=1, found=0)
    assert ok is False
    assert "banner" not in fake.presses, fake.presses
    assert fake.presses[-1] == "close", "the search window was left open"


def test_a_solo_target_is_not_rallied():
    """«Атаковать» instead of «Стягивание» — no amount of pressing makes that a rally."""
    ok, fake, _log = _run(armed=1, found=-1)
    assert ok is False
    assert "banner" not in fake.presses, fake.presses
    assert fake.presses[-1] == "close", "the target window was left open"


def test_no_squad_screen_means_nothing_is_launched():
    ok, fake, _log = _run(armed=1, found=1, panel=0)
    assert ok is False
    assert "squad" not in fake.presses and "launch" not in fake.presses, fake.presses


def test_a_squad_the_screen_will_not_take_is_never_launched():
    ok, fake, _log = _run(armed=1, found=1, panel=1, picked=0)
    assert ok is False
    assert "launch" not in fake.presses, fake.presses
    assert fake.presses[-1] == "close", "the squad screen was left open"


def test_pressed_but_no_banner_is_a_failure_not_a_success():
    """The press returning cleanly proves nothing — only a rally of ours appearing does."""
    ok, fake, _log = _run(armed=1, found=1, panel=1, picked=1, raised=0)
    assert ok is False
    assert fake.presses[-1] == "launch", fake.presses


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
