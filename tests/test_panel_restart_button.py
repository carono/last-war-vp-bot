r"""The client's life is three scenarios, and no front-end may end it by process NAME.

This is a regression guard with a live bug behind it. «⟳ Перезапустить игру» used to
run `taskkill /F /IM LastWar.exe`, which names an IMAGE: on a machine farming two
accounts — one client per Windows session — that closes BOTH, and the second one
belongs to a profile nobody pressed anything for. It was found by restarting the
client for real and watching the ordinary "which client is running" lookup answer
with the other account's process.

The fix is the rule `CLAUDE.md` already states: the ability is one scenario and the
button only plays it. There are three of them now — launch, quit, restart — and they
are pressed from TWO front-ends, so the table that says which scenario each one plays
moved into `panel/runtime/game_control.py` where both read it (#1221). That makes the
guard broader rather than narrower, and it still needs no Tk, no display and no game:

  * every control names a scenario that exists, and `play()` plays it through the
    runtime rather than doing anything itself;
  * the window's presser only asks the question and hands the id over;
  * nothing under `panel/` passes `/IM` to anything — an image-name kill is never the
    right way to end a client here, from any button, and the next one added should
    fail this.

All of it reads the AST rather than the text, which is the difference between a guard
and a nuisance: a comment explaining the old bug (this file, and the shell's own) is
prose, and `taskkill /PID` on a frozen panel is a legitimate kill of ONE process. Only
an argument actually handed to a call counts.

    python3 tests/test_panel_restart_button.py
    C:\Python312\python.exe tests\test_panel_restart_button.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

SHELL = _REPO / "panel" / "__main__.py"
CONTROL = _REPO / "panel" / "runtime" / "game_control.py"
ACTIONS = _REPO / "src" / "lastwar_bot" / "actions"

from panel.runtime import game_control as gamectl   # noqa: E402


def _function(name: str, path: Path | None = None) -> ast.FunctionDef:
    # Resolved at CALL time, not bound into the signature: a default captured at
    # import makes the guard unable to be pointed at anything else — including the
    # old body, which is the only way to find out whether it guards at all.
    path = SHELL if path is None else path
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path.name} has no {name}()")


def _calls(node: ast.AST) -> list:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _attr_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def test_every_lifecycle_press_names_a_scenario_that_exists():
    """Launch, quit and restart are recipes on disk — not a routine spelled out in Python."""
    assert [c.id for c in gamectl.CONTROLS] == ["launch", "quit", "restart"]
    for control in gamectl.CONTROLS:
        assert (ACTIONS / f"{control.scenario}.md").is_file(), \
            f"«{control.id}» plays {control.scenario}, which is not in actions/"


def test_the_press_plays_the_scenario_and_does_nothing_else():
    """One call into the runtime, naming the recipe the table gave it."""
    fn = _function("play", CONTROL)
    played = [c for c in _calls(fn) if _attr_name(c) in ("play_async", "play", "run")]
    assert played, "a lifecycle press no longer plays anything through the runtime"
    # No process ending, no sleeping, no launcher spawning — each of those was in the
    # old button body, and each is a way for the panel to grow back a second, divergent
    # idea of what "restart the client" means.
    called = {_attr_name(c) for c in _calls(fn)}
    for forbidden in ("Popen", "sleep", "kill", "terminate"):
        assert forbidden not in called, \
            f"game_control.play calls {forbidden}() — the recipes own the client now"


def test_neither_front_end_ends_the_client_itself():
    """The window's presser asks the question and hands over an id. That is all it may do.

    The phone's half is `WebApi.game` and is pinned in tests/test_panel_web.py; both
    end at the same `game_control.play`, which is the point of that module.
    """
    fn = _function("_press_game")
    called = {_attr_name(c) for c in _calls(fn)}
    for forbidden in ("Popen", "sleep", "kill", "terminate", "play_async"):
        assert forbidden not in called, \
            f"_press_game calls {forbidden}() — it plays nothing of its own"
    spoken = {n.value for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any("taskkill" in s or "/IM" in s for s in spoken), \
        f"the button is ending the client itself again: {sorted(spoken)}"


def test_nothing_under_panel_kills_by_image_name():
    """`/IM` names an image, and an image is every account's client at once.

    A restart, a watchdog, a cleanup — whatever wants to end the client must name the
    process this profile drives (tools/lib/game_client.py answers that), never the
    executable. There is exactly one machine here with two accounts on it and it is
    the operator's own.
    """
    offenders = []
    for path in sorted((_REPO / "panel").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            for arg in ast.walk(call):
                if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and arg.value.strip().upper() == "/IM"):
                    offenders.append(
                        f"{path.relative_to(_REPO)}:{getattr(call, 'lineno', 0)}")
    assert not offenders, "image-name kill under panel/: " + ", ".join(offenders)


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
