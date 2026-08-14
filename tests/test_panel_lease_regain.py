r"""A run whose DAEMON restarted underneath it gets its lease back (#1411).

A scenario is handed the game's lease ONCE, when its context is built
(`panel/runtime/host.py::game_target` → `Context.game_token`). That was enough while the
only way to lose a lease was to give it away — a run that parks for a press knows it let
go, and `yield_hook` hands it a fresh token on the way back (tests/test_panel_priority.py).

The other way needs nobody's consent: the daemon restarts, and the new one starts holding
no lease at all. The token on the context then names a lease that does not exist, every
chunk is refused with `lease lost — it expired or was taken by nobody`, and NOTHING in the
run re-reads the token — so the game stays deaf until the scenario ends. Live on
2026-08-14 an autoassist run got exactly that, and `launch_game` spent the last ten
seconds of its cap failing to read a scene off a daemon that had been warm for three of
them — because `_eval_lua_value` reads a refusal as «could not ask».

Three pieces, one per layer, and this file holds them apart:

  * `Interpreter._run_lua` retries a `LeaseLost` chunk ONCE, and only after the hook says
    the lease is ours again — a second refusal means somebody else holds the game;
  * `GameLink.regain` asks the daemon for a NEW lease, and puts the dead token back when
    the answer is no (an empty token is «unleased», which is let straight through the
    daemon's own gate — the one outcome worse than a refusal);
  * `PanelRuntime.regain_hook` writes the new token onto the context and drops the
    evaluator built with the old one — the same two lines `yield_hook` ends on.

    python3 tests/test_panel_lease_regain.py
    C:\Python312\python.exe tests\test_panel_lease_regain.py
"""
from __future__ import annotations

# `ui`: `panel.runtime.host` pulls the package in, and the package pulls tkinter.
TIER = "ui"

import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "tools" / "lib"),
           str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lua_client                              # noqa: E402
from lastwar_bot import script_engine          # noqa: E402


class _Log:
    def __init__(self) -> None:
        self.said: list = []

    def say(self, tag, key, **fmt) -> None:
        self.said.append(key)

    def put(self, line) -> None:
        self.said.append(("put", line))


class _Evaluator:
    """A daemon client that refuses every chunk until it is handed the live token."""

    def __init__(self, live: str) -> None:
        self.live, self.token, self.runs = live, "", 0

    def run(self, chunk, marker=None, settle=1.2, early=False, sentinel=None):
        self.runs += 1
        if self.token != self.live:
            raise lua_client.LeaseLost(
                "lease lost — it expired or was taken by nobody")
        return [f"{marker} ok"]


# ---------------------------------------------------------------------------
# the interpreter: one retry, and only for this one refusal
# ---------------------------------------------------------------------------
def _interpreter(ctx, evaluator=None):
    """An interpreter whose `_evaluator()` is ``evaluator``, however often it is dropped.

    The retry rebuilds the evaluator — that is the point of dropping it — and a rebuild
    here would go looking for a daemon, or fall back to a local `LuaEval` and try to
    attach to a game. The stub answers instead, and carries the token the hook gave it.
    """
    interp = script_engine.Interpreter(ctx)
    if evaluator is not None:
        interp._evaluator = lambda: evaluator
    return interp


def test_a_lost_lease_is_regained_and_the_chunk_goes_in_on_the_retry():
    ev = _Evaluator(live="new")
    ctx = script_engine.new_context(game_token="dead")

    def regain(c):
        c.game_token = "new"
        ev.token = "new"                       # what the panel's link does to its client
        return True

    ctx.regain = regain
    out = _interpreter(ctx, ev)._run_lua("print(1)", marker="ACT")

    assert out == ["ACT ok"], out
    assert ev.runs == 2, f"the chunk went in {ev.runs} time(s), not twice"
    assert ctx.game_token == "new", ctx.game_token


def test_the_retry_happens_once_and_the_refusal_is_raised_after_it():
    """A second «lease lost» means somebody ELSE holds the game now.

    Pressing on beside them is the one thing the lease exists to prevent, so the run
    stops — and it stops with the daemon's own refusal rather than with a fresh error of
    the panel's invention.
    """
    ev = _Evaluator(live="never handed out")
    ctx = script_engine.new_context(game_token="dead")
    ctx.regain = lambda c: True                # says yes, gets nothing

    try:
        _interpreter(ctx, ev)._run_lua("print(1)", marker="ACT")
    except lua_client.LeaseLost:
        pass
    else:
        raise AssertionError("a run that cannot hold the client went on pressing it")
    assert ev.runs == 2, f"the chunk went in {ev.runs} time(s) — the retry is not once"


def test_a_run_with_no_hook_is_exactly_as_it_was():
    """A script from a shell, a test, a harness: the refusal is raised, nothing retried."""
    ev = _Evaluator(live="new")
    ctx = script_engine.new_context()
    assert ctx.regain is None

    try:
        _interpreter(ctx, ev)._run_lua("print(1)", marker="ACT")
    except lua_client.LeaseLost:
        pass
    else:
        raise AssertionError("the refusal was swallowed")
    assert ev.runs == 1, ev.runs


def test_every_other_failure_is_untouched():
    """Only `LeaseLost` is retried — a bad chunk, a client that is gone, a dead socket.

    Retrying those would double every real failure's cost and hide none of them: the
    daemon has already decided, and the second answer is the first one again.
    """
    tried = []

    class _Broken:
        def run(self, chunk, marker=None, settle=1.2, early=False, sentinel=None):
            tried.append(chunk)
            raise RuntimeError("attempt to index a nil value")

    ctx = script_engine.new_context()
    ctx.regain = lambda c: (_ for _ in ()).throw(
        AssertionError("a broken chunk asked for a new lease"))
    try:
        _interpreter(ctx, _Broken())._run_lua("print(1)")
    except RuntimeError as exc:
        assert "nil value" in str(exc), exc
    assert len(tried) == 1, tried


def test_a_hook_that_raises_leaves_the_original_refusal_to_be_reported():
    ev = _Evaluator(live="new")
    ctx = script_engine.new_context(game_token="dead")
    ctx.regain = lambda c: (_ for _ in ()).throw(OSError("no daemon"))

    try:
        _interpreter(ctx, ev)._run_lua("print(1)")
    except lua_client.LeaseLost:
        pass
    except OSError:
        raise AssertionError("the hook's own failure replaced the refusal worth reading")
    assert ev.runs == 1, ev.runs


def test_the_evaluator_built_with_the_dead_token_is_dropped():
    """The interpreter drops it as well as the hook, because it is this side that knows
    a retry is coming — a cached connection would carry the dead token straight back."""
    ctx = script_engine.new_context(game_token="dead")
    ctx.evaluator = _Evaluator(live="new")
    ctx.regain = lambda c: True                # a hook that forgets to drop it
    interp = _interpreter(ctx)
    assert interp._regain_lease() is True
    assert ctx.evaluator is None


# ---------------------------------------------------------------------------
# the link: a NEW lease, and a dead token put back when the answer is no
# ---------------------------------------------------------------------------
def _link(client, port: int = 47654):
    from panel.runtime import daemon as daemonmod

    link = daemonmod.GameLink(
        port=lambda: port, python=lambda: "python", log=_Log(),
        env=lambda: {}, cwd=".", daemon_script="x", name=lambda: "alice")
    link.client = client
    link.up = lambda fresh=False: True
    return link


class _DaemonClient:
    """The lease half of `lua_client.DaemonClient`, over a daemon that has just booted."""

    def __init__(self, granting: "str | None" = "fresh") -> None:
        self.token, self.granting, self.asked = "", granting, []
        self.port = 47654

    def acquire(self, owner, ttl=120.0):
        self.asked.append((owner, self.token))
        if self.granting is None:
            return None
        self.token = self.granting
        return self.token

    def lease_state(self) -> dict:
        return {"owner": "bob/timer", "held_sec": 3}


def test_the_link_asks_for_a_new_lease_rather_than_re_claiming_a_dead_one():
    client = _DaemonClient(granting="fresh")
    client.token = "dead"
    link = _link(client)

    assert link.regain("timer") is True
    assert client.token == "fresh", client.token
    # The dead token is NOT sent: a re-claim of a lease the new daemon never issued is a
    # different question from «may I have one», and only the second one has an answer.
    assert client.asked == [("alice/timer", "")], client.asked
    assert link.token == "fresh", link.token


def test_a_lease_that_is_somebody_else_s_leaves_the_dead_token_in_place():
    """An empty token is not «no lease» — it is «unleased», and the daemon lets an
    unleased run straight through to drive the game beside its new owner
    (`tools/lib/game_lease.py::check_run`). So a refusal goes on being a refusal."""
    client = _DaemonClient(granting=None)
    client.token = "dead"
    link = _link(client)

    assert link.regain("timer") is False
    assert client.token == "dead", client.token
    assert "busy.elsewhere" in link._log.said, link._log.said


def test_no_daemon_on_the_port_is_a_no():
    client = _DaemonClient(granting="fresh")
    client.token = "dead"
    link = _link(client)
    link.up = lambda fresh=False: False

    assert link.regain("timer") is False
    assert client.asked == [], "a daemon that is not there was asked for a lease"
    assert client.token == "dead", client.token


def test_a_link_with_no_client_says_no_rather_than_pretending():
    link = _link(None)
    assert link.regain("timer") is False


# ---------------------------------------------------------------------------
# the hook: the same two lines the park ends on, plus a line in the log
# ---------------------------------------------------------------------------
def test_the_hook_hands_the_run_the_new_token_and_drops_the_old_evaluator():
    from panel.runtime.host import PanelRuntime

    said = []
    game = types.SimpleNamespace(regain=lambda tag: True, token="fresh")
    stub = types.SimpleNamespace(
        game=game,
        log=types.SimpleNamespace(say=lambda tag, key, **fmt: said.append(key)),
        t=lambda key, **fmt: key)
    ctx = script_engine.new_context()
    ctx.game_token, ctx.evaluator = "dead", object()

    assert PanelRuntime.regain_hook(stub, "timer")(ctx) is True
    assert ctx.game_token == "fresh", ctx.game_token
    assert ctx.evaluator is None, "the run kept an evaluator built with the old lease"
    assert said == ["lease.regained"], said


def test_the_hook_says_so_and_answers_no_when_the_lease_is_gone_for_good():
    from panel.runtime.host import PanelRuntime

    said = []
    game = types.SimpleNamespace(regain=lambda tag: False, token="")
    stub = types.SimpleNamespace(
        game=game,
        log=types.SimpleNamespace(say=lambda tag, key, **fmt: said.append(key)),
        t=lambda key, **fmt: key)
    ctx = script_engine.new_context()
    ctx.game_token = "dead"

    assert PanelRuntime.regain_hook(stub, "timer")(ctx) is False
    assert said == ["lease.gone"], said
    # …and the dead token is left alone: the run is about to be stopped by the refusal
    # the interpreter is still holding, and an emptied token would drive unleased.
    assert ctx.game_token == "dead", ctx.game_token


def test_every_context_the_panel_builds_carries_the_hook():
    """The runner, not the callers: a press, a timer's errand and an auto-order all build
    their contexts through :meth:`ActionRunner.context`, and a daemon restart is nobody's
    to remember."""
    from panel.runtime.actions import ActionRunner

    made = []
    real = script_engine.new_context

    def spy(**kw):
        made.append(kw)
        return real(**kw)

    hook = lambda ctx: True                    # noqa: E731
    runner = ActionRunner(log=_Log(), regain=hook)
    script_engine.new_context = spy
    try:
        runner.context()
        # …and a caller that brings its own keeps it: `setdefault`, not an overwrite.
        runner.context(regain=None)
    finally:
        script_engine.new_context = real

    assert made[0]["regain"] is hook, made[0]
    assert made[1]["regain"] is None, made[1]


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
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f"  ERR  {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
