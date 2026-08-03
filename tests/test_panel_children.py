r"""Nothing the panel starts outlives it (#1212).

A monitor is a sniffer with a robbery budget attached: two of them listening to the same
stream spend the day's five raids between them and neither knows the other is there. The
panel used to leave them behind twice over — a child whose tab forgot to stop it simply
stayed, and a panel that was KILLED rather than closed left every one of them running
for ever. Each restart added another set.

What is pinned here:

  * a child is written down the moment it starts, monitored or raw, and `stop_all()`
    ends every one of them and takes the file with it;
  * a child a tab never stopped is stopped anyway — that is the whole point of the
    factory owning them;
  * the orphans of a run that is GONE are ended on the next start — off the record it
    left, and off the stamp each child carries when there is no record (which is what
    reaches the runs from before any of this existed);
  * …and only those. A live owner's children — a second panel, a standalone tab open
    beside this one — are left strictly alone, and so are a stranger that merely
    inherited a recycled pid and anything the panel never started at all;
  * two profiles are two files: closing one profile's runtime does not touch the other's
    children.

Needs psutil (the panel's own dependency) and runs real processes, so it is the one
panel test that is about the operating system rather than about widgets:

    C:\Python312\python.exe tests\test_panel_children.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import children as childrenmod          # noqa: E402
from panel.runtime.children import ChildFactory            # noqa: E402

#: A child that does nothing for long enough to be caught doing it.
SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]


# ---------------------------------------------------------------------------
# doubles and helpers
# ---------------------------------------------------------------------------
class _Log:
    """A LogBus that only remembers."""

    def __init__(self) -> None:
        self.lines: list = []
        self.said: list = []

    def put(self, line: str) -> None:
        self.lines.append(line)

    def say(self, tag: str, key: str, **fmt) -> None:
        self.said.append((tag, key, fmt))


def _factory(directory=None, log=None) -> ChildFactory:
    return ChildFactory(log=log or _Log(), cwd=str(_REPO), python=lambda: sys.executable,
                        port=lambda: 47654, schedule=None,
                        registry=(lambda: str(directory)) if directory else None)


def _alive(pid: int) -> bool:
    import psutil
    try:
        proc = psutil.Process(int(pid))
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except Exception:                                      # noqa: BLE001
        return False


def _gone(pid: int, within: float = 8.0) -> bool:
    deadline = time.time() + within
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _sleeper(owner=None) -> subprocess.Popen:
    """A live process nobody owns — stands in for a previous run's monitor.

    ``owner`` stamps it the way the factory stamps a child of its own, which is what
    the machine-wide sweep goes by.
    """
    env = dict(os.environ)
    env.pop(childrenmod.OWNER_VAR, None)
    if owner is not None:
        env[childrenmod.OWNER_VAR] = str(owner)
    return subprocess.Popen(SLEEPER, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env=env)


def _dead_pid() -> int:
    """A pid that is certainly not running — a previous run's panel."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"], stdout=subprocess.DEVNULL)
    proc.wait(timeout=30)
    return proc.pid


def _write_registry(directory: str, owner: int, entries: list) -> str:
    path = childrenmod.registry_path(directory, owner)
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"owner": owner, "children": entries}, fh)
    return path


def _entry(proc, tag: str = "autoloot", ctime=...) -> dict:
    import psutil
    if ctime is ...:
        ctime = psutil.Process(proc.pid).create_time()
    return {"pid": proc.pid, "tag": tag, "cmd": list(SLEEPER), "ctime": ctime}


# ---------------------------------------------------------------------------
# the factory owns what it starts
# ---------------------------------------------------------------------------
def test_a_raw_child_is_written_down_and_ended_by_stop_all() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        factory = _factory(tmp)
        proc = factory.spawn_raw(list(SLEEPER), "autoloot")
        assert proc is not None, "the child did not start"
        path = childrenmod.registry_path(tmp)
        assert os.path.exists(path), "the child was not written down"
        listed = json.load(open(path, encoding="utf-8"))["children"]
        assert [c["pid"] for c in listed] == [proc.pid], listed
        assert listed[0]["tag"] == "autoloot" and listed[0]["ctime"], listed

        assert factory.stop_all() == 1
        assert _gone(proc.pid), "the child outlived stop_all()"
        assert not os.path.exists(path), "the registry file was left behind"


def test_a_monitored_child_is_owned_the_same_way() -> None:
    """`spawn()` hands back a monitor a tab may forget to stop — the factory does not."""
    with tempfile.TemporaryDirectory() as tmp:
        factory = _factory(tmp)
        exited: list = []
        mon = factory.spawn("secret", list(SLEEPER), on_exit=lambda: exited.append(1))
        assert mon.start(), "the monitor did not start"
        pid = mon.pid
        assert [c.pid for c in factory.live] == [pid]

        factory.stop_all()
        assert _gone(pid), "the monitored child outlived stop_all()"
        time.sleep(0.3)
        # It was told to go, so its death is not news: nothing tries to untick a
        # checkbox on a window that is already closing.
        assert not exited, "on_exit fired for a death the panel asked for"


def test_a_child_that_ended_on_its_own_leaves_the_list_and_the_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        factory = _factory(tmp)
        quick = factory.spawn_raw([sys.executable, "-c", "pass"], "scan")
        assert quick is not None
        quick.wait(timeout=30)
        assert factory.live == [], "a dead child is still listed as running"
        assert not os.path.exists(childrenmod.registry_path(tmp)), \
            "the file still names a process that has ended"


# ---------------------------------------------------------------------------
# what the last run left behind
# ---------------------------------------------------------------------------
def test_the_orphans_of_a_run_that_is_gone_are_ended() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        orphan, dead = _sleeper(), _dead_pid()
        try:
            path = _write_registry(tmp, dead, [_entry(orphan)])
            log = _Log()
            assert childrenmod.reap(tmp, say=log.say) == 1
            assert _gone(orphan.pid), "an orphan of the last run is still running"
            assert not os.path.exists(path), "the dead run's file was left behind"
            assert any(key == "log.children.orphan" for _t, key, _f in log.said), \
                log.said
        finally:
            orphan.kill()


def test_one_child_that_will_not_be_judged_does_not_abort_the_cleanup() -> None:
    """A process ending mid-kill is ordinary, and used to throw out of the whole reap.

    It cost a live run: `wait_procs` raised `NoSuchProcess`, the second orphan was left
    running and the dead panel's file stayed on disk to be re-read for ever (#1212).
    """
    with tempfile.TemporaryDirectory() as tmp:
        first, second = _sleeper(), _sleeper()
        dead = _dead_pid()
        try:
            path = _write_registry(tmp, dead, [_entry(first), _entry(second)])
            boom = {"n": 0}
            real = childrenmod._kill_tree

            def flaky(pid, **kw):                 # the first kill dies of a vanished pid
                boom["n"] += 1
                if boom["n"] == 1:
                    import psutil
                    raise psutil.NoSuchProcess(pid)
                return real(pid, **kw)

            childrenmod._kill_tree = flaky
            try:
                assert childrenmod.reap(tmp) == 1, "the survivor was not ended"
            finally:
                childrenmod._kill_tree = real
            assert _gone(second.pid), "the second orphan outlived the first one's failure"
            assert not os.path.exists(path), "the dead run's file was left to be re-read"
        finally:
            for proc in (first, second):
                try:
                    proc.kill()
                except Exception:                 # noqa: BLE001
                    pass


def test_a_live_owner_keeps_its_own_children() -> None:
    """A second panel, or a standalone tab open beside this one, is not ours to tidy."""
    with tempfile.TemporaryDirectory() as tmp:
        owner, child = _sleeper(), _sleeper()
        try:
            path = _write_registry(tmp, owner.pid, [_entry(child)])
            assert childrenmod.reap(tmp) == 0
            time.sleep(0.3)
            assert _alive(child.pid), "another panel's monitor was killed"
            assert os.path.exists(path), "another panel's file was removed"
        finally:
            owner.kill()
            child.kill()


def test_an_owner_younger_than_its_child_is_a_reissued_number() -> None:
    """The pid is alive and is a python — and it started AFTER the child it «owns».

    Windows hands a pid back within minutes and this box spawns pythons by the dozen,
    so a dead panel's number reappearing as somebody else's python read as «still
    running» and spared the orphan for ever. Caught live (#1212).
    """
    with tempfile.TemporaryDirectory() as tmp:
        orphan = _sleeper()                       # the child: started FIRST
        time.sleep(1.2)
        impostor = _sleeper()                     # a python that took the number later
        try:
            _write_registry(tmp, impostor.pid, [_entry(orphan)])
            assert childrenmod.reap(tmp) == 1, "the reissued number spared the orphan"
            assert _gone(orphan.pid)
            assert _alive(impostor.pid), "the stranger holding the number was killed"
        finally:
            orphan.kill()
            impostor.kill()


def test_our_own_file_is_never_reaped() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mine = _sleeper()
        try:
            path = _write_registry(tmp, os.getpid(), [_entry(mine)])
            assert childrenmod.reap(tmp) == 0
            assert _alive(mine.pid) and os.path.exists(path)
        finally:
            mine.kill()


def test_a_recycled_pid_is_left_alone() -> None:
    """The pid is there, the process is somebody else's — the start time says so."""
    with tempfile.TemporaryDirectory() as tmp:
        stranger = _sleeper()
        try:
            _write_registry(tmp, _dead_pid(), [_entry(stranger, ctime=1.0)])
            assert childrenmod.reap(tmp) == 0
            time.sleep(0.3)
            assert _alive(stranger.pid), "a stranger holding a recycled pid was killed"
        finally:
            stranger.kill()


# ---------------------------------------------------------------------------
# the machine-wide sweep — for a run that left no record at all
# ---------------------------------------------------------------------------
def test_a_stamped_child_of_a_dead_panel_is_swept_up() -> None:
    orphan = _sleeper(owner=_dead_pid())
    try:
        log = _Log()
        assert childrenmod.sweep(say=log.say) >= 1
        assert _gone(orphan.pid), "a stamped orphan survived the sweep"
    finally:
        orphan.kill()


def test_the_sweep_leaves_a_live_panels_children_alone() -> None:
    """Ours carries our own pid; a second panel's carries one that is still running."""
    mine, neighbour = _sleeper(owner=os.getpid()), _sleeper()
    theirs = _sleeper(owner=neighbour.pid)
    try:
        childrenmod.sweep()
        time.sleep(0.3)
        assert _alive(mine.pid), "the sweep killed this panel's own child"
        assert _alive(theirs.pid), "the sweep killed another live panel's child"
    finally:
        for proc in (mine, neighbour, theirs):
            proc.kill()


def test_the_sweep_does_not_touch_what_the_panel_never_started() -> None:
    """No stamp, no claim — a tool a person is running by hand, and the Lua daemon."""
    stranger = _sleeper()
    try:
        childrenmod.sweep()
        time.sleep(0.3)
        assert _alive(stranger.pid), "the sweep killed an unstamped process"
    finally:
        stranger.kill()


def test_the_sweep_runs_in_a_process_of_its_own() -> None:
    """A thread would starve the panel: the walk holds Python's lock for ~6 s.

    Six or seven seconds during which one ttk widget costs 37–74 ms instead of 1 ms
    (docs/research/panel-freezes.md §1). So the sweep is a CHILD, and what it killed
    comes back as marker lines the panel says in its own language.
    """
    with tempfile.TemporaryDirectory() as tmp:
        orphan = _sleeper(owner=_dead_pid())
        log = _Log()
        factory = _factory(tmp, log)
        try:
            factory.reap()                        # file pass here, sweep in a child
            child = [c for c in factory.live if "_cli" in " ".join(c.cmd)]
            assert child, [c.cmd for c in factory.live]
            assert _gone(orphan.pid, within=60), "the child sweep did not end the orphan"
            # …and the panel said it, from the marker rather than from the child's words
            for _ in range(100):
                if any(k == "log.children.orphan" for _t, k, _f in log.said):
                    break
                time.sleep(0.1)
            assert any(k == "log.children.orphan" for _t, k, _f in log.said), log.said
        finally:
            factory.stop_all()
            orphan.kill()


def test_a_child_that_ends_during_the_boot_still_reports_it() -> None:
    """`after()` from the reader thread raises while the window is still booting.

    The panel pumps `update()` by hand until every profile is up, and a Tk call from
    another thread during those seconds raises «main thread is not in main loop». It
    killed the reader thread with a traceback on stderr and lost the callback — which,
    for a capture, is the checkbox that says it is still running (#1212).
    """
    from panel import childmon as childmonmod

    def refuses(_delay, _func):
        raise RuntimeError("main thread is not in main loop")

    done: list = []
    mon = childmonmod.ChildMonitor(
        [sys.executable, "-c", "pass"], "boot", log=lambda _l: None, cwd=str(_REPO),
        on_exit=lambda: done.append(1), schedule=refuses)
    assert mon.start()
    for _ in range(100):
        if done:
            break
        time.sleep(0.05)
    assert done, "the child ended and nobody was told"


def test_the_factory_stamps_its_children_and_the_daemons_environment_stays_clean() -> None:
    factory = _factory(None)
    assert factory.child_env()[childrenmod.OWNER_VAR] == str(os.getpid())
    # `env()` is what the Lua daemon is launched with, and it is detached on purpose.
    assert childrenmod.OWNER_VAR not in factory.env()


# ---------------------------------------------------------------------------
# two profiles are two sets of children
# ---------------------------------------------------------------------------
def test_two_profiles_keep_their_children_apart() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        first, second = os.path.join(tmp, "one"), os.path.join(tmp, "two")
        os.makedirs(first)
        os.makedirs(second)
        a, b = _factory(first), _factory(second)
        pa = a.spawn_raw(list(SLEEPER), "autoloot")
        pb = b.spawn_raw(list(SLEEPER), "autoloot")
        assert pa is not None and pb is not None
        try:
            assert os.path.exists(childrenmod.registry_path(first))
            assert os.path.exists(childrenmod.registry_path(second))
            a.stop_all()
            assert _gone(pa.pid), "the closed profile's child stayed"
            time.sleep(0.3)
            assert _alive(pb.pid), "closing one profile killed the other's child"
            assert os.path.exists(childrenmod.registry_path(second))
        finally:
            b.stop_all()
            for proc in (pa, pb):
                try:
                    proc.kill()
                except Exception:                          # noqa: BLE001
                    pass


def test_a_factory_with_no_registry_still_owns_its_children() -> None:
    """The harness case: nothing is written down, everything is still stopped."""
    factory = _factory(None)
    proc = factory.spawn_raw(list(SLEEPER), "chat")
    assert proc is not None
    assert factory.stop_all() == 1
    assert _gone(proc.pid)


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
        except Exception as exc:                           # noqa: BLE001
            failed += 1
            print(f"  ERR  {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
