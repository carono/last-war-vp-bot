r"""A launch ends when the client is READY, not when the clock runs out (task #1399).

What went wrong, in one paragraph. `actions/launch_game.md` waited on `scene != unknown`,
and the scene can only be read through the Lua daemon — which, right after a relaunch, is
the one thing on the machine that is down: it was pinned to the process that just died and
the panel is rebuilding it. Live on 2026-08-14 the client's process was back 8 s after
`START_GAME` and its conversation with the game server 32 s after it, while the daemon
stayed down until 170 s. So the wait sat out its whole 180 s cap and reported a FAILED
launch — twelve times in one evening, over a client the very next scenario read as
`scene == city`.

The fix is a ladder (`Interpreter._client_ready`), and these tests pin its four corners:

  * a sign that arrives early ends the wait early, and the cap is never spent;
  * a sign that never arrives ends the wait at the cap, with a reason that says WHICH
    rung it was stuck on;
  * the strong rung wins: a client that ANSWERS «still loading» is not overruled by a
    socket that happens to be up;
  * the weak rung exists at all: no daemon to ask + a live game socket is ready.

…plus the two things a reader of the recipes would want checked: that the launch really
does wait on this sign, and that nothing on the launch path builds a local `LuaEval` to
answer a poll (an il2cpp attach, seconds apiece, against a client that is still booting).

No Tk, no game, no daemon, no Windows.

    C:\Python312\python.exe tests\test_launch_readiness.py
    python3 tests/test_launch_readiness.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "src"))

try:
    from lastwar_bot import script_engine  # noqa: E402
except Exception as _exc:                  # noqa: BLE001
    script_engine, _WHY = None, _exc

ACTIONS = ROOT / "src" / "lastwar_bot" / "actions"


def _interp(scene=None, vm=True, link="offline", log=None):
    """An interpreter whose three readings are stubbed — no VM, no socket table.

    `scene` is what the game would answer (`'city'` / `'world'` / `'unknown'`), or `None`
    for «the read did not come back». `vm` is whether there is a warm daemon to ask at
    all, and `link` is what the operating system would say about the client's sockets.
    """
    interp = script_engine.Interpreter(
        script_engine.new_context(0, log or (lambda _e: None)))
    interp._scene_reading = lambda: scene
    interp._vm_reachable = lambda: vm
    interp._read_client_link = lambda: link
    return interp


# --- the ladder -------------------------------------------------------------
def test_a_named_scene_is_ready():
    for scene in ("city", "world"):
        assert _interp(scene=scene, vm=True)._client_ready() is True, scene


def test_a_client_that_says_it_is_loading_is_not_ready_however_good_its_socket_is():
    """The strong rung wins — that is what makes it a ladder rather than an OR.

    A client that ANSWERS `unknown` is the game itself saying «no scene yet». Letting the
    socket overrule that would call a launch done at the loading bar, and every errand
    behind it would reach a client that is not in the game.
    """
    interp = _interp(scene="unknown", vm=True, link="online")
    assert interp._client_ready() is False
    assert "loading" in (interp._ready_why or "")


def test_no_daemon_to_ask_plus_a_live_game_socket_is_ready():
    """The rung the whole task is about: readable while the VM is being rebuilt."""
    interp = _interp(scene=None, vm=False, link="online")
    assert interp._client_ready() is True
    assert "link" in (interp._ready_why or ""), interp._ready_why


def test_no_daemon_and_no_client_is_not_ready_and_says_so():
    interp = _interp(scene=None, vm=False, link="offline")
    assert interp._client_ready() is False
    assert "no client" in (interp._ready_why or ""), interp._ready_why


def test_no_daemon_and_a_client_whose_server_hung_up_is_not_ready_and_says_so():
    interp = _interp(scene=None, vm=False, link="lost")
    assert interp._client_ready() is False
    assert "hung up" in (interp._ready_why or ""), interp._ready_why


def test_a_daemon_that_is_there_but_will_not_answer_falls_through_to_the_socket():
    """`vm=True` and a read that came back empty is still «nobody could tell us»."""
    interp = _interp(scene=None, vm=True, link="online")
    assert interp._client_ready() is True


# --- the wait ---------------------------------------------------------------
def _wait(interp, condition="client == ready", timeout=1.0):
    stmt = script_engine.WaitStmt(text=f"WAIT {condition}", line_no=1,
                                  condition=condition, timeout=timeout)
    interp._do_wait(stmt)


def test_the_sign_arriving_early_ends_the_wait_early():
    """The cap is 30 s; the sign lands on the third poll; the wait must not take 30 s."""
    polls = []

    def scene():
        polls.append(1)
        return "city" if len(polls) >= 3 else "unknown"

    interp = _interp(vm=True)
    interp._scene_reading = scene
    started = time.monotonic()
    _wait(interp, timeout=30.0)
    spent = time.monotonic() - started
    assert len(polls) >= 3, polls
    assert spent < 5.0, f"the wait sat out {spent:.1f}s of a 30s cap after the sign landed"


def test_the_sign_never_arriving_ends_at_the_cap_with_a_reason():
    interp = _interp(scene=None, vm=False, link="offline")
    started = time.monotonic()
    try:
        _wait(interp, timeout=1.0)
    except script_engine.ScriptRuntimeError as exc:
        spent = time.monotonic() - started
        assert 0.9 <= spent < 4.0, f"the cap was not the cap: {spent:.1f}s"
        assert "no client" in str(exc), f"no reason in the failure: {exc}"
        return
    raise AssertionError("a client that never came up was reported as ready")


def test_the_wait_says_where_the_time_went():
    """Each rung as it lands, once — the per-step breakdown a slow launch needs."""
    said: list = []
    states = ["offline", "unknown", "online"]

    interp = _interp(scene=None, vm=False, log=said.append)
    interp._read_client_link = lambda: states[min(len(said), len(states) - 1)]
    _wait(interp, timeout=30.0)
    lines = [s.strip() for s in said]
    assert any("no client process is running" in s for s in lines), lines
    assert any("matched" in s for s in lines), lines


# --- the recipes ------------------------------------------------------------
def test_the_launch_waits_on_the_sign_and_not_on_the_scene():
    text = (ACTIONS / "launch_game.md").read_text(encoding="utf-8")
    body = [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    assert "START_GAME" in body, body
    waits = [ln for ln in body if ln.upper().startswith("WAIT ")]
    assert waits == ["WAIT client == ready WITHIN 180s"], waits


def test_nothing_on_the_launch_path_waits_for_the_base_in_particular():
    """`scene == city` is the trap of #1281 and it must not come back to a launch.

    A client that came back on the world map is a client that came back. Every recipe
    that puts one there is read, so a fourth one added tomorrow is covered too.
    """
    for name in ("launch_game", "restart_game", "recover_from_kick", "switch_account"):
        text = (ACTIONS / f"{name}.md").read_text(encoding="utf-8")
        for ln in text.splitlines():
            bare = ln.strip()
            if bare.upper().startswith("WAIT ") and "scene == city" in bare:
                raise AssertionError(f"{name}.md waits for the base: {bare!r}")


def test_the_recovery_names_no_launcher_of_its_own():
    """It calls the one recipe that knows where THIS profile's client lives.

    It used to spell a path — right on the machine it was written on, and a folder that
    cannot exist for a profile whose client is in another Windows session.
    """
    text = (ACTIONS / "recover_from_kick.md").read_text(encoding="utf-8")
    body = [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    assert "CALL launch_game" in body, body
    assert not [ln for ln in body if ln.upper().startswith("LAUNCH ")], body


def test_a_readiness_poll_never_builds_an_evaluator():
    """With no daemon, `_evaluator()` builds a LOCAL LuaEval — an il2cpp attach.

    Seconds apiece, against a client that is still booting, three times a second for as
    long as the wait runs. The ladder asks the port instead and falls to the socket, so
    nothing on this path may reach `_evaluator`.
    """
    import lua_client

    built: list = []
    real_running, real_eval = lua_client.is_running, script_engine.Interpreter._evaluator
    lua_client.is_running = lambda **kw: False
    script_engine.Interpreter._evaluator = lambda _s: built.append(1)
    try:
        interp = script_engine.Interpreter(
            script_engine.new_context(0, lambda _e: None))
        interp._read_client_link = lambda: "online"
        assert interp._vm_reachable() is False
        assert interp._client_ready() is True
    finally:
        lua_client.is_running = real_running
        script_engine.Interpreter._evaluator = real_eval
    assert built == [], "a readiness poll attached to the client to answer itself"


def test_the_socket_walk_is_not_made_three_times_a_second():
    """The cheap rung has to stay cheap: `sockets_of` walks the machine's whole TCP table."""
    walks: list = []
    interp = _interp(scene=None, vm=False)
    interp._read_client_link = lambda: (walks.append(1), "offline")[1]
    for _ in range(20):
        interp._client_link()
    assert len(walks) == 1, f"{len(walks)} socket walks in one burst"


def _main() -> int:
    if script_engine is None:
        print(f"  SKIP the engine will not import here: {_WHY}")
        return 0
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
