r"""«What is the panel doing right now» — the strip along the bottom (#1208).

A panel that is thinking looks exactly like a panel that has hung: opening a profile
builds fifteen tabs, a daemon takes half a minute to come up, a scenario holds the game
for minutes, and until this none of it was said anywhere a person could see. What has
to hold:

  * a step is a KEY and its arguments, never a sentence — the words are said by whoever
    draws them, in whatever language that window is showing;
  * several steps may be live at once (a thread per profile at boot, an errand firing
    while a tab is being built), and «what is it doing» is the NEWEST of them — with
    whatever is still running underneath coming back into view when that one ends;
  * a step ends whatever happens, including when the work raises;
  * listeners are told on the reporting thread, one that raises does not stop the rest,
    and nothing here may be the reason an errand fails;
  * the two things that block for whole seconds report by themselves, so a tab launched
    on its own gets the same strip for free: bringing the daemon up
    (`panel/runtime/daemon.py`) and playing a scenario (`panel/runtime/actions.py`);
  * and the shell's staged page build (`panel/__main__.py::_stage`) runs its steps under
    the session they belong to, stops when that session is closed, and lets one step
    fail without dropping the rest of the page.

Tk-free — none of this is about widgets. Runs anywhere:

    python3 tests/test_panel_activity.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
import threading
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime.activity import Activity           # noqa: E402


# -- the object itself ------------------------------------------------------
def test_nothing_running_is_nothing_shown() -> None:
    act = Activity()
    assert act.current() is None
    assert not act.busy()


def test_a_step_is_a_key_and_its_arguments() -> None:
    act = Activity()
    with act.step("activity.tab.build", tab="Чат") as step:
        assert step.key == "activity.tab.build"
        assert step.fmt == {"tab": "Чат"}
        assert act.current() is step
    assert act.current() is None


def test_the_newest_live_step_is_the_one_shown() -> None:
    act = Activity()
    first = act.begin("activity.daemon.start", port=47654)
    second = act.begin("activity.action", name="heal_units")
    assert act.current() is second
    # …and when it ends, what is still running underneath comes back by itself.
    act.end(second)
    assert act.current() is first
    act.end(first)
    assert act.current() is None


def test_a_step_ends_even_when_the_work_raises() -> None:
    act = Activity()
    try:
        with act.step("activity.action", name="boom"):
            raise RuntimeError("the game said no")
    except RuntimeError:
        pass
    assert act.current() is None


def test_ending_twice_is_harmless_and_so_is_ending_nothing() -> None:
    act = Activity()
    step = act.begin("activity.cmd")
    act.end(step)
    act.end(step)
    act.end(None)
    assert act.current() is None


def test_clear_forgets_everything_left_running() -> None:
    act = Activity()
    act.begin("activity.action", name="one")
    act.begin("activity.action", name="two")
    assert len(act) == 2
    act.clear()                       # «Стоп всё»
    assert act.current() is None


def test_listeners_hear_both_ends_and_a_deaf_one_is_not_fatal() -> None:
    act = Activity()
    heard: list = []
    act.listen(lambda: (_ for _ in ()).throw(ValueError("deaf")))
    off = act.listen(lambda: heard.append(act.current()))
    with act.step("activity.dashboard"):
        pass
    assert len(heard) == 2                       # begun, then ended
    assert heard[0] is not None and heard[1] is None
    off()
    with act.step("activity.dashboard"):
        pass
    assert len(heard) == 2                       # unsubscribed, and it stayed that way


def test_two_threads_reporting_at_once_keep_both_steps() -> None:
    act = Activity()
    ready, go = threading.Barrier(3), threading.Event()

    def worker(name: str) -> None:
        step = act.begin("activity.action", name=name)
        ready.wait(5)
        go.wait(5)
        act.end(step)

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    ready.wait(5)
    assert len(act) == 2, "one reporter overwrote the other"
    go.set()
    for t in threads:
        t.join(5)
    assert act.current() is None


def test_a_step_seq_orders_across_two_activities() -> None:
    """Two profiles, two activities — the window shows the newer step of the two."""
    first, second = Activity("main"), Activity("alt")
    older = first.begin("activity.daemon.start", port=47654)
    newer = second.begin("activity.tab.build", tab="Ралли")
    assert newer.seq > older.seq


# -- the two things that block, reporting by themselves ----------------------
class _Log:
    def say(self, *a, **kw) -> None:
        pass

    def put(self, *a, **kw) -> None:
        pass


def test_the_daemon_says_it_is_starting_one() -> None:
    import panel.runtime.daemon as daemonmod
    from panel.runtime.daemon import GameLink

    act = Activity()
    seen: list = []
    act.listen(lambda: seen.append(act.current()))
    link = GameLink(port=lambda: 47999, python=lambda: sys.executable, log=_Log(),
                    env=dict, cwd=str(_REPO), daemon_script="nope.py", activity=act)
    # Nothing there, and nothing started. `health` rather than `up`, because «is there a
    # daemon» stopped being a question about the port the moment a daemon could answer
    # one while holding a client that had gone (#1286).
    link.health = lambda client_pid=None: daemonmod.DAEMON_NONE
    link.up = lambda fresh=False: False
    link._python = lambda: "no-such-interpreter-anywhere"
    assert link.ensure() is False
    keys = [s.key for s in seen if s is not None]
    assert "activity.daemon.start" in keys, keys
    assert act.current() is None, "the step outlived the work it described"


def test_a_daemon_already_warm_reports_nothing() -> None:
    import panel.runtime.daemon as daemonmod
    from panel.runtime.daemon import GameLink

    act = Activity()
    link = GameLink(port=lambda: 47999, python=lambda: sys.executable, log=_Log(),
                    env=dict, cwd=str(_REPO), daemon_script="nope.py", activity=act)
    link.health = lambda client_pid=None: daemonmod.DAEMON_LIVE
    link.up = lambda fresh=False: True
    seen: list = []
    act.listen(lambda: seen.append(act.current()))
    assert link.ensure() is True
    assert not seen, "a step for work that did not happen"


def test_a_scenario_names_itself_while_it_plays() -> None:
    from panel.runtime.actions import ActionRunner

    act = Activity()
    runner = ActionRunner(log=_Log(), activity=act)
    seen: list = []
    act.listen(lambda: seen.append(act.current()))
    # No such scenario: `run` still goes through the interpreter, which answers false.
    # What is pinned here is the STEP, not the outcome.
    try:
        runner.run("no_such_scenario_at_all")
    except Exception:                             # noqa: BLE001 — the interpreter's
        pass
    keys = [s.key for s in seen if s is not None]
    assert keys and keys[0] == "activity.action", keys
    assert seen[0].fmt == {"name": "no_such_scenario_at_all"}
    assert act.current() is None


# -- the shell's staged page build -------------------------------------------
class _Session:
    def __init__(self, name: str) -> None:
        self.name = name
        self.state: dict = {}


class _Workspace:
    def __init__(self, *sessions) -> None:
        self._by_name = {s.name: s for s in sessions}

    def get(self, name):
        return self._by_name.get(name)

    def close(self, name) -> None:
        self._by_name.pop(name, None)


class _Shell:
    """`_stage` / `_stage_one` / `_session_alive` lifted off the window they live on.

    The three of them touch no widget — which is the point: the staging discipline is
    testable without a display, and it is the part a mistake in is invisible (a step
    silently skipped, or one run under the wrong profile).
    """

    _stage = None          # filled in below, from the real class

    def __init__(self, workspace) -> None:
        self._workspace = workspace
        self.entered: list = []
        self.later: list = []

    # the two things the real one gets from Tk and from SessionScoped
    def after(self, _ms, func):
        self.later.append(func)

    class _Scope:
        def __init__(self, shell, session) -> None:
            self.shell, self.session = shell, session

        def __enter__(self):
            self.shell.entered.append(self.session)
            return self.session

        def __exit__(self, *exc) -> bool:
            return False

    def _on(self, session):
        return self._Scope(self, session)

    class _Dbg:
        def error(self, *a, **kw) -> None:
            pass

    _dbg = _Dbg()

    def pump(self) -> None:
        """Run whatever the last step scheduled, the way a mainloop turn would."""
        while self.later:
            self.later.pop(0)()


def _shell_with_real_staging(workspace) -> "_Shell":
    from panel import __main__ as shellmod

    shell = _Shell(workspace)
    for name in ("_stage", "_stage_one", "_session_alive"):
        setattr(_Shell, name, getattr(shellmod.Panel, name))
    return shell


def test_a_staged_build_runs_every_step_under_its_own_session() -> None:
    session = _Session("main")
    shell = _shell_with_real_staging(_Workspace(session))
    done: list = []
    steps = [lambda i=i: done.append(i) for i in range(4)]
    shell._stage(session, steps, True)
    shell.pump()
    assert done == [0, 1, 2, 3]
    assert shell.entered == [session] * 4, "a step ran outside its profile"


def test_an_unstaged_build_runs_the_same_steps_straight_through() -> None:
    session = _Session("main")
    shell = _shell_with_real_staging(_Workspace(session))
    done: list = []
    shell._stage(session, [lambda i=i: done.append(i) for i in range(3)], False)
    assert done == [0, 1, 2], "the boot path must not need an event loop"
    assert not shell.later


def test_closing_the_profile_mid_build_stops_the_rest_of_it() -> None:
    session = _Session("main")
    workspace = _Workspace(session)
    shell = _shell_with_real_staging(workspace)
    done: list = []

    def close_it() -> None:
        done.append("closed")
        workspace.close("main")

    shell._stage(session, [close_it] + [lambda i=i: done.append(i) for i in range(3)],
                 True)
    shell.pump()
    assert done == ["closed"], "the page went on being built after it was closed"


def test_one_step_that_raises_does_not_drop_the_rest_of_the_page() -> None:
    session = _Session("main")
    shell = _shell_with_real_staging(_Workspace(session))
    done: list = []

    def boom() -> None:
        raise RuntimeError("this tab is broken")

    shell._stage(session, [boom, lambda: done.append("after")], True)
    shell.pump()
    assert done == ["after"]


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
