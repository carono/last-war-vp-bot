r"""The process list must not be read by opening four hundred handles (task #1214).

`psutil.process_iter(["pid", "name"])` is the obvious way to ask what is running, and on
Windows `Process.name()` is `basename(exe())` — one `OpenProcess` per process. Measured
on the machine this was written on, 389 processes:

    psutil.process_iter(["pid", "name"])            3.96 s
    psutil.process_iter(["pid", "name", "cmdline"]) 7.66 s
    win32ts.WTSEnumerateProcesses(0, 1, 0)          0.027 s

That is not merely slow, it is slow WHILE HOLDING PYTHON'S LOCK, so a walk on a
background thread makes everything the Tk thread does ten to forty times slower: one ttk
widget 1 ms → 37–74 ms, a tab that builds in 180 ms → nine seconds
(docs/research/panel-freezes.md §1). The stall sampler named the frame outright —
`meanwhile 100% — panel-child-sweep: _pswindows.py:758 exe`.

Three things are pinned here.

* **`proc_table` prefers the cheap enumeration** and falls back to psutil only where the
  cheap one cannot be had — and the fallback is a fallback, not a silent second walk.
* **The sweep narrows before it opens.** `children.sweep` asks for names, keeps the
  pythons, and only then opens the handful that can possibly be a panel child. Opening a
  process that is plainly not ours is the whole cost this task removed.
* **Nothing that runs in the panel's own process spells `psutil.process_iter`.** That is
  the guard: the cure is one import away from being undone by the next person who wants
  a process list, and a source scan is the only thing that notices.

No Windows, no Tk and no game needed — the machine is stubbed.

    C:\Python312\python.exe tests\test_proc_table.py
    python3 tests/test_proc_table.py
    C:\Python312\python.exe tests\test_proc_table.py --bench   # the timings above, here
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import ast
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import proc_table                                  # noqa: E402

try:                                               # the WSL python3 has no tkinter, and
    from panel.runtime import children             # the runtime package imports it
except Exception as _exc:                          # noqa: BLE001
    children, _WHY = None, _exc


# ---------------------------------------------------------------------------
# the module itself
# ---------------------------------------------------------------------------
class _Swap:
    """Put stand-ins on a module for the length of a `with`, and take them off again."""

    def __init__(self, module, **names) -> None:
        self._module, self._names = module, names
        self._saved: dict = {}

    def __enter__(self):
        for name, value in self._names.items():
            self._saved[name] = getattr(self._module, name, None)
            setattr(self._module, name, value)
        return self

    def __exit__(self, *_exc) -> None:
        for name, value in self._saved.items():
            setattr(self._module, name, value)


def test_names_prefers_the_cheap_enumeration() -> None:
    """With `wts_rows` answering, psutil is never imported at all."""
    rows = [(1, 10, "explorer.exe"), (2, 20, "python.exe")]
    with _Swap(proc_table, wts_rows=lambda: list(rows)):
        assert proc_table.names() == [(10, "explorer.exe"), (20, "python.exe")], \
            proc_table.names()


def test_names_falls_back_when_the_box_cannot_be_asked() -> None:
    """A machine with no pywin32 still gets an answer — the expensive one is the only
    one there is, and no answer at all would read as «nothing is running»."""
    def refuse():
        raise OSError("no win32ts here")

    with _Swap(proc_table, wts_rows=refuse):
        found = proc_table.names()
    assert isinstance(found, list), found
    assert any(pid == os.getpid() for pid, _name in found), \
        "the fallback did not find this very process"


def test_names_never_raises() -> None:
    """Neither route available is an empty list, not an exception: every caller of this
    treats «could not be read» as a reading, and a crash would take a cleanup with it."""
    def refuse():
        raise OSError("nothing to walk with")

    saved = sys.modules.get("psutil")
    sys.modules["psutil"] = None                   # an import that yields nothing usable
    try:
        with _Swap(proc_table, wts_rows=refuse):
            assert proc_table.names() == [], "an unaskable machine did not answer []"
    finally:
        if saved is None:
            sys.modules.pop("psutil", None)
        else:
            sys.modules["psutil"] = saved


def test_pids_named_is_case_insensitive() -> None:
    rows = [(1, 10, "LastWar.exe"), (1, 11, "lastwar.exe"), (1, 12, "notepad.exe")]
    with _Swap(proc_table, wts_rows=lambda: list(rows)):
        assert proc_table.pids_named("LASTWAR.EXE") == [10, 11]
        assert proc_table.pids_named("nothing.exe") == []


# ---------------------------------------------------------------------------
# the sweep: narrow first, then open
# ---------------------------------------------------------------------------
class _Proc:
    """One process, as the sweep asks about it."""

    def __init__(self, pid, name="python.exe", owner=None, started=100.0,
                 cmd=None) -> None:
        self.pid, self._name, self._owner = pid, name, owner
        self._started, self._cmd = started, cmd or ["python.exe", "tools/thing.py"]
        self.running = True

    def name(self):
        return self._name

    def is_running(self):
        return self.running

    def status(self):
        return "running"

    def environ(self):
        return {} if self._owner is None else {children.OWNER_VAR: str(self._owner)}

    def cmdline(self):
        return list(self._cmd)

    def create_time(self):
        return self._started

    def children(self, recursive=False):
        return []

    def terminate(self):
        self.running = False

    def kill(self):
        self.running = False


class _Psutil:
    """A stand-in psutil that records WHICH pids were opened — the point of the test."""

    STATUS_ZOMBIE = "zombie"

    def __init__(self, procs) -> None:
        self.procs = {p.pid: p for p in procs}
        self.opened: list = []

    def Process(self, pid):                        # noqa: N802 — psutil's own spelling
        self.opened.append(int(pid))
        try:
            return self.procs[int(pid)]
        except KeyError:
            raise LookupError(f"no process {pid}") from None

    def wait_procs(self, procs, timeout=None):
        return [p for p in procs if not p.running], [p for p in procs if p.running]


def _sweep_machine():
    """The stubbed box: two non-pythons, an orphan, a live panel's child, a stranger."""
    mine = os.getpid()
    names = [(10, "explorer.exe"), (11, "LastWar.exe"),
             (20, "python.exe"), (21, "pythonw.exe"), (30, "python.exe"),
             (mine, "python.exe")]
    procs = [_Proc(20, owner=999, started=200.0, cmd=["python.exe", "tools/robber.py"]),
             _Proc(21, name="pythonw.exe", owner=500, started=200.0),
             _Proc(30, owner=None, started=200.0),
             _Proc(500, started=100.0)]            # the live owner, older than its child
    return names, _Psutil(procs)


def test_sweep_opens_only_the_pythons() -> None:
    """Nothing is asked of `explorer.exe` — narrowing on the cheap table is the fix."""
    names, ps = _sweep_machine()
    with _Swap(children, proc_table=type("T", (), {"names": staticmethod(
            lambda: list(names))}), _psutil=lambda: ps):
        children.sweep()
    assert 10 not in ps.opened and 11 not in ps.opened, \
        f"a process that cannot be a panel child was opened: {sorted(set(ps.opened))}"
    assert {20, 21, 30} <= set(ps.opened), \
        f"a python was skipped: {sorted(set(ps.opened))}"


def test_sweep_still_ends_exactly_the_orphans() -> None:
    """…and the narrowing changed nothing about WHICH children are ended."""
    names, ps = _sweep_machine()
    said: list = []
    with _Swap(children, proc_table=type("T", (), {"names": staticmethod(
            lambda: list(names))}), _psutil=lambda: ps):
        killed = children.sweep(say=lambda *a, **kw: said.append(kw))
    assert killed == 1, f"expected one orphan ended, got {killed}"
    assert not ps.procs[20].running, "the orphan is still running"
    assert ps.procs[21].running, "a live panel's child was taken away from it"
    assert ps.procs[30].running, "an unstamped process was killed"
    assert said and said[0].get("pid") == 20, said


# ---------------------------------------------------------------------------
# and the guard that keeps it from coming back
# ---------------------------------------------------------------------------
#: What runs inside the panel's own process and must therefore never walk the machine
#: the expensive way. Everything under `panel/`, plus the three shared modules the panel
#: imports and calls on its own threads: the link probe (the status poll, every eight
#: seconds), the client lookup (`script_engine`'s restarts and force-closes) and the RDP
#: bring-up (a button, with a dialog-clicking thread that loops twice a second).
GUARDED = ["panel", "tools/lib/game_link.py", "tools/lib/game_client.py",
           "tools/rdp_instance.py"]

#: The one place the expensive walk is allowed to be spelled — as the fallback, for a
#: machine where nothing cheaper can be had.
HOME = "tools/lib/proc_table.py"


def _guarded_files():
    for entry in GUARDED:
        path = ROOT / entry
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*.py")
                              if "__pycache__" not in p.parts)
        else:
            yield path


def _walks(path) -> bool:
    """Does this file CALL `psutil.process_iter`?

    Read as code, not as text: every one of these files now says the words in a docstring
    explaining why it does not do it, and a grep would fail on the explanation. What is
    being banned is the call.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                            # noqa: PERF203 — not ours to judge
        return False
    return any(isinstance(node, ast.Attribute) and node.attr == "process_iter"
               for node in ast.walk(tree))


def test_nothing_in_the_panel_walks_the_expensive_way() -> None:
    guilty = [str(p.relative_to(ROOT)).replace(os.sep, "/")
              for p in _guarded_files() if _walks(p)]
    assert not guilty, (
        f"{', '.join(guilty)} walks the machine with psutil.process_iter — that is "
        f"four seconds of held interpreter lock in the panel's process. Ask "
        f"{HOME} for the names and open only what you need.")


def test_the_expensive_walk_still_has_a_home() -> None:
    """The fallback must not be «tidied away»: a box with no pywin32 has nothing else."""
    text = (ROOT / HOME).read_text(encoding="utf-8")
    assert "psutil" in text and "process_iter" in text, \
        f"{HOME} lost its fallback — a machine without pywin32 now answers «nothing is " \
        f"running», which reads as «the client is gone»"


# ---------------------------------------------------------------------------
def _bench() -> None:
    """The measurement this task was decided on, repeatable on any machine."""
    import psutil

    t = time.perf_counter()
    cheap = proc_table.names()
    cheap_sec = time.perf_counter() - t

    t = time.perf_counter()
    walk = list(psutil.process_iter(["pid", "name"]))
    walk_sec = time.perf_counter() - t

    # Plain ASCII, deliberately: this prints to whatever console the operator has, and
    # a Windows one is cp1251 here — an em dash or a multiplication sign ends the run in
    # a UnicodeEncodeError instead of a number.
    print(f"  proc_table.names()                  {cheap_sec:7.3f} s  ({len(cheap)})")
    print(f"  psutil.process_iter(pid, name)      {walk_sec:7.3f} s  ({len(walk)}) "
          f"- cold; the second call is cached and costs nothing")
    if cheap_sec > 0:
        print(f"  ratio                               {walk_sec / cheap_sec:7.1f}x")


def _main() -> int:
    if "--bench" in sys.argv:
        _bench()
        return 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    if children is None:
        print(f"  the runtime package will not import here: {_WHY}")
        print("  …running everything that does not need it")
        tests = [t for t in tests if not t.__name__.startswith("test_sweep_")]
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
