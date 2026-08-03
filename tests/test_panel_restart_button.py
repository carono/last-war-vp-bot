r"""The shell may not end the game by process NAME — not from any button.

This is a regression guard with a live bug behind it. «⟳ Перезапустить игру» used to
run `taskkill /F /IM LastWar.exe`, which names an IMAGE: on a machine farming two
accounts — one client per Windows session — that closes BOTH, and the second one
belongs to a profile nobody pressed anything for. It was found by restarting the
client for real and watching the ordinary "which client is running" lookup answer
with the other account's process.

The fix is the rule `CLAUDE.md` already states: the ability is one scenario
(`actions/restart_game.md`, which ends the client THIS profile drives and waits for
the base to come back), and the button only plays it. So the test asks two things of
the shell's source, and neither needs Tk, a display or a game:

  * `_restart_game` plays the scenario through the runtime, and nothing else;
  * nothing under `panel/` passes `/IM` to anything — an image-name kill is never the
    right way to end a client here, from any button, and the next one added should
    fail this.

Both read the AST rather than the text, which is the difference between a guard and a
nuisance: a comment explaining the old bug (this file, and the shell's own) is prose,
and `taskkill /PID` on a frozen panel is a legitimate kill of ONE process. Only an
argument actually handed to a call counts.

    python3 tests/test_panel_restart_button.py
    C:\Python312\python.exe tests\test_panel_restart_button.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
SHELL = _REPO / "panel" / "__main__.py"


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


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _attr_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def test_the_restart_button_plays_the_scenario():
    """One call into the runtime, naming the recipe — not a routine spelled out here."""
    fn = _function("_restart_game")
    played = [c for c in _calls(fn) if _attr_name(c) in ("play_async", "play", "run")]
    assert played, "the button no longer plays anything through the runtime"
    names = [a.value for c in played for a in c.args if isinstance(a, ast.Constant)]
    assert "restart_game" in names, \
        f"the button must play actions/restart_game.md, not {names}"


def test_the_restart_button_kills_nothing_itself():
    """No process ending, no sleeping, no launcher spawning — that is the recipe's job.

    Each of these was in the old body, and each is a way for the panel to grow back a
    second, divergent idea of what "restart the client" means.
    """
    fn = _function("_restart_game")
    called = {_attr_name(c) for c in _calls(fn)}
    for forbidden in ("Popen", "sleep", "kill", "terminate"):
        assert forbidden not in called, \
            f"_restart_game calls {forbidden}() — the recipe owns the restart now"
    # The AST, so the comment explaining the old bug is not mistaken for the bug.
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
