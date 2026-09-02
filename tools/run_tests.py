r"""Run the test suite — three tiers, one exit code (task #1282, audit §4.3).

There are 86 test files here, 1 394 test functions, 36 168 lines — 29 % of the tracked
Python — and until this file there was no command that ran them. Every one is a
self-running script (`AGENTS.md` §8: no pytest, and that stays), so «run the tests» meant
knowing which of the 86 need Tk, which need a display, which need a live game client, and
running the rest by hand. Nobody did, which is how
`test_panel_page_build.py::test_a_page_draws_only_the_tabs_that_have_to_be_there` sat RED
on clean HEAD for a whole task: #1273 hid eleven tabs behind development mode and broke a
#1215 regression guard, and the suite that would have said so could not be run.

## The tiers

    offline   nothing but Python. Parsers, the DSL, the Lua chunks through `lupa`, the
              locales, the hygiene checks. Runs on any machine, in WSL, in CI.
    ui        Tk and a display. The page build, the tab contract, the dialogs, the
              screens. On this project that means the Windows interpreter.
    live      a running game client (and usually a daemon). The acceptance probes.

A test file declares its own tier with a module-level `TIER = "ui"` (or `"live"`) near the
top. **No declaration means `offline`**, deliberately: that is the tier with no
prerequisites, so an undeclared file gets RUN rather than quietly skipped, and it either
passes or tells somebody it needs something. The runner reads the line rather than
importing the module — importing a test file runs it.

A file may also declare `TIMEOUT = 1800` the same way, and one does. A tier says WHAT a
test needs; how long it takes is a separate question, and a file that honestly takes
minutes should not have to lie about its prerequisites to be allowed them. A declaration
can only RAISE the ceiling above `--timeout`, never lower it.

## Running it

    C:\Python312\python.exe tools\run_tests.py                 # the offline tier
    C:\Python312\python.exe tools\run_tests.py ui              # Tk + a display
    C:\Python312\python.exe tools\run_tests.py all             # everything
    python3 tools/run_tests.py offline --jobs 4                # in WSL, in parallel
    python3 tools/run_tests.py --list                          # what is in which tier
    C:\Python312\python.exe tools\run_tests.py ui --only secret # one file, by substring

Exit code is 0 only when every file in the tier passed. A file that times out counts as
red and says so — a hung test is not a pass.

## What it prints, and when

Each file's verdict is printed AND FLUSHED the moment that file finishes, never
collected for the end. The offline tier is a hundred files and minutes of wall clock, so
something outside the run ends it half way often enough to design for: a CI step's limit,
an agent's command timeout, a Ctrl-C. A runner that only speaks at the end says nothing
at all when that happens — exit code 1, no output, and no way to tell a red suite from a
suite that never ran (#2020). A run that did not finish says `INCOMPLETE` and exits
non-zero.

However a run ends, it prints the same summary — how many were green, what was red,
and `INCOMPLETE: n of m file(s) never finished` when it did not get through the list. A
SIGTERM (or SIGHUP) is caught for that reason alone; so is a crash inside the runner
itself, which is reported and then re-raised. And an abort takes the file it landed in
down with it and NAMES it: an orphaned test file here means a panel left running on a
live profile, writing to the account's log (#2002).

Two more traps that made a killed run look green rather than dead:

  * **never pipe this into `tail` / `head` / `grep`** — the exit code you read is the
    pipe's, so a run that printed nothing comes back 0. Redirect to a file instead.
  * a file that leaves a GRANDCHILD behind (a spawned panel, a daemon) leaves it holding
    this process's stdout pipe. `subprocess.run(timeout=…)` kills the test and then waits
    on that pipe for ever, so the runner hangs rather than reporting. Each file gets its
    own process group and a timeout kills the group; a pipe still held after that is
    abandoned, not waited on.

## The one thing to watch

A file that SKIPS what it cannot do still exits 0, and several do exactly that under an
interpreter without Tk («SKIP tkinter not importable»). That is a green line for a test
that did not run, which is why the `ui` tier exists at all: the tiering is what stops the
offline run from reporting a suite it never executed. When a run is finished the runner
prints how many files skipped everything they had, so the number is visible rather than
implied.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

sys.path.insert(0, str(REPO / "tools" / "lib"))
import test_mode                               # noqa: E402  — bare name, see panel/paths.py

# THE RUN ITSELF SAYS SO, and so does every process it starts (#2002). A test file is a
# self-running script and reaches for the same panel, profiles, ports and game client this
# machine farms with; the guards that refuse read this one variable, and it is set here
# rather than by each file so that a child three levels down still sees it.
test_mode.arm()

TIERS = ("offline", "ui", "live")
DEFAULT_TIER = "offline"

#: How long one file may take before it is called red. Most of the suite is seconds and
#: the slowest ordinary file is ~30 s (`test_rally_tool.py`).
DEFAULT_TIMEOUT = 300.0

#: `TIER = "ui"` on a line of its own, anywhere in the file's head.
_TIER_RE = re.compile(r"^TIER\s*=\s*[\"'](offline|ui|live)[\"']", re.M)

#: `TIMEOUT = 1800` on a line of its own — this file's own ceiling, in seconds.
#:
#: One file needs it and the note that used to stand here got the reason wrong: it said
#: the street-run route search «declares itself `live`», and it never has — it needs no
#: client, no daemon and no display, only twelve replays of 11 880 m through a real Lua
#: VM. It is honestly offline and honestly slow (~4.5 min in WSL, longer on Windows),
#: which under one flat 300 s ceiling made it the one file the runner reported as red for
#: being slow. A timed-out file IS red, deliberately (a hung test is not a pass), so the
#: fix is for the ceiling to be the file's rather than for the file to change tier: a
#: tier says WHAT a test needs, never how long it takes.
_TIMEOUT_RE = re.compile(r"^TIMEOUT\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.M)

#: What a self-running test file prints when it declines to do its work. Matched only to
#: COUNT them at the end — never to change an exit code.
_SKIP_RE = re.compile(r"^\s*(SKIP|skip)\b", re.M)


def tier_of(path: Path) -> str:
    """The tier a test file declares, or `offline` when it declares nothing.

    Read as TEXT, on purpose: importing a test module here would run the tests inside
    the runner's own process, which is both wrong and unrecoverable when one of them
    opens a window.
    """
    head = path.read_text(encoding="utf-8", errors="replace")[:8000]
    m = _TIER_RE.search(head)
    return m.group(1) if m else DEFAULT_TIER


def timeout_of(path: Path, default: float = DEFAULT_TIMEOUT) -> float:
    """The ceiling a file declares for itself, or ``default``.

    Read as TEXT for the same reason :func:`tier_of` is. A declaration only ever RAISES
    the ceiling: `--timeout` is what somebody at a keyboard uses to cut a run short, and
    a file must not be able to overrule it downwards from the other side of the repo.
    """
    head = path.read_text(encoding="utf-8", errors="replace")[:8000]
    m = _TIMEOUT_RE.search(head)
    return max(default, float(m.group(1))) if m else default


def discover(only: str | None = None) -> list[Path]:
    files = sorted(p for p in TESTS.glob("test_*.py") if p.is_file())
    if only:
        files = [p for p in files if only in p.name]
    return files


class Result:
    __slots__ = ("path", "code", "seconds", "output")

    def __init__(self, path: Path, code: int, seconds: float, output: str) -> None:
        self.path, self.code, self.seconds, self.output = path, code, seconds, output

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def timed_out(self) -> bool:
        return self.code == -9 or self.code == 124

    @property
    def skipped_everything(self) -> bool:
        """Green, but every line of it was a skip — a pass that ran nothing."""
        return self.ok and bool(_SKIP_RE.search(self.output)) and "passed" in self.output


#: How long the runner waits for a killed file's pipes to close before giving up on
#: them. A test that leaves a GRANDCHILD behind (a spawned panel, a daemon, a helper)
#: leaves that grandchild holding the same stdout pipe, so the ordinary
#: `subprocess.run(timeout=…)` kills the test, then blocks for ever reading a pipe
#: nobody will close. That is a runner that hangs instead of reporting — which, under
#: any outer time limit, is a whole suite that dies having printed nothing.
DRAIN_GRACE = 10.0

#: Every test file this runner has going right now, so an abort can take them with it
#: instead of orphaning them (#2020, and #2002 is what an orphan does on this repo).
_RUNNING: dict = {}
_ABORTED: list = []
_RUNNING_LOCK = threading.Lock()


def run_one(path: Path, timeout: float) -> Result:
    started = time.monotonic()
    popen_kwargs = {}
    if os.name == "posix":
        # Its own process group, so a timeout can take the grandchildren with it.
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, str(path)], cwd=str(REPO),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env={**os.environ,
                                            "PYTHONIOENCODING": "utf-8",
                                            test_mode.ENV: "1"},
                            **popen_kwargs)
    with _RUNNING_LOCK:
        _RUNNING[proc] = path
    try:
        output, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        code = 124
        try:
            output, _ = proc.communicate(timeout=DRAIN_GRACE)
        except subprocess.TimeoutExpired:
            # Something is still holding the pipe. Abandon it rather than wait: the
            # file is red either way and the run has to go on.
            output = ""
            if proc.stdout is not None:
                proc.stdout.close()
        output = (output or "") + f"\nTIMED OUT after {timeout:.0f}s"
    except BaseException:
        # A signal, or anything else that ends the run from outside, arrives HERE —
        # in the wait for the file that is running. Take that file down before the
        # exception travels on, or the abort orphans it (#2002 is what an orphaned
        # test file does on this repo: a panel on the live profile, unwatched).
        _kill_tree(proc)
        with _RUNNING_LOCK:
            _ABORTED.append(path.name)
        raise
    finally:
        with _RUNNING_LOCK:
            _RUNNING.pop(proc, None)
    return Result(path, code, time.monotonic() - started, output or "")


def _kill_everything_still_running() -> list[str]:
    """Take the running test files down on the way out, and name them.

    An aborted run that leaves its children behind leaves them holding this repo's
    live profile, its log and its locks — and nobody is watching them any more.
    """
    with _RUNNING_LOCK:
        left = list(_RUNNING.items())
        names = list(_ABORTED)
        _RUNNING.clear()
        _ABORTED.clear()
    for proc, path in left:
        _kill_tree(proc)
        names.append(path.name)
    return names


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the test AND anything it left running, so its pipe can close.

    The tree, not the process: `proc.kill()` alone leaves the grandchildren holding
    the stdout pipe this runner is reading, and the read then never returns. Windows
    has no process group to signal, so the tree is `taskkill /T` — measured: without
    it a leaked grandchild held the runner for the full 60 s of the test that catches
    this, with the file's own 2 s ceiling long past.
    """
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    else:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
            return
        except Exception:                     # noqa: BLE001 — fall back to the process
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _say(line: str = "") -> None:
    """Print and FLUSH. A pipe is block-buffered, so an unflushed line is a line that
    is lost the moment the run is killed — which is exactly when it was needed."""
    print(line, flush=True)


def _tail(text: str, lines: int = 6) -> list[str]:
    """The last few lines that are not an `ok` — which is what a failure looks like."""
    keep = [ln.rstrip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("ok ")]
    return keep[-lines:]


class _Signalled(BaseException):
    """A signal that ends the run — carried as an exception so the summary still prints.

    `BaseException` on purpose: nothing in here may swallow it by catching `Exception`.
    """

    def __str__(self) -> str:                        # "stopped by SIGTERM"
        return str(self.args[0]) if self.args else "a signal"


@contextlib.contextmanager
def _stop_signals():
    """Turn SIGTERM (and SIGHUP where there is one) into an exception we can report on.

    An outer limit — a CI step, an agent's command timeout, a `kill` — arrives as a
    SIGTERM, and the default disposition ends the process on the spot: no summary, no
    list of what had passed, and an exit status nobody can tell from a red suite. The
    whole point of #2020 is that a killed run says so.
    """
    # SIGBREAK is the Windows half of this: there is no catchable SIGTERM there (a
    # `TerminateProcess` cannot be handled at all), and Ctrl-Break is what a console
    # or a parent sends when it wants a process to end and be able to say so.
    names = [n for n in ("SIGTERM", "SIGHUP", "SIGBREAK") if hasattr(signal, n)]
    saved = {}

    def raise_it(signum, _frame):
        raise _Signalled(signal.Signals(signum).name)

    for name in names:
        sig = getattr(signal, name)
        try:
            saved[sig] = signal.signal(sig, raise_it)
        except (ValueError, OSError):
            pass                                     # not the main thread, or no such
    try:
        yield names
    finally:
        for sig, was in saved.items():
            try:
                signal.signal(sig, was)
            except (ValueError, OSError):
                pass


def _summarise(results: list, wanted: list, started: float) -> None:
    """What passed, what did not, and what never ran — printed on every way out."""
    red = [r for r in results if not r.ok]
    _say(f"\n{len(results) - len(red)}/{len(results)} files green "
         f"in {time.monotonic() - started:.0f}s")
    if len(results) != len(wanted):
        _say(f"INCOMPLETE: {len(wanted) - len(results)} of {len(wanted)} file(s) "
             f"never finished")
    if red:
        _say("red: " + ", ".join(sorted(r.path.name for r in red)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run the test suite by tier. Exit 0 only when the tier is green.")
    ap.add_argument("tier", nargs="?", default=DEFAULT_TIER,
                    choices=(*TIERS, "all"),
                    help="which tier to run (default: offline)")
    ap.add_argument("--only", help="run just the files whose name contains this")
    ap.add_argument("--jobs", type=int, default=1,
                    help="run this many files at once. Safe for `offline`; leave at 1 "
                         "for `ui` (windows) and `live` (one client, one lease)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                    help=f"seconds per file before it counts as red "
                         f"(default {DEFAULT_TIMEOUT:.0f})")
    ap.add_argument("--list", action="store_true",
                    help="print each file and its tier, run nothing")
    ap.add_argument("--verbose", action="store_true",
                    help="print each file's whole output, not just a failure's tail")
    args = ap.parse_args(argv)

    files = discover(args.only)
    tiers = {p: tier_of(p) for p in files}

    if args.list:
        for tier in TIERS:
            named = [p for p in files if tiers[p] == tier]
            print(f"\n{tier} ({len(named)})")
            for p in named:
                print(f"  {p.name}")
        return 0

    wanted = [p for p in files if args.tier == "all" or tiers[p] == args.tier]
    if not wanted:
        print(f"nothing to run: no file in tier {args.tier!r}"
              + (f" matching {args.only!r}" if args.only else ""))
        # A `--only` that matches nothing is a typo and stays an error. A TIER that is
        # empty is not: `live` holds only whatever declares itself so, and after #1284
        # moved the last one out (it needed no client and never had) there is none. An
        # empty tier has no failures in it, which is what the exit code is about.
        return 1 if args.only else 0

    _say(f"{len(wanted)} file(s), tier {args.tier}, {sys.executable}")
    started = time.monotonic()
    results: list[Result] = []

    def report(r: Result) -> None:
        """Say how one file went, the moment it is known.

        Printed AS THE RUN GOES, never collected for the end: a suite that takes
        minutes gets killed by whatever outer limit the caller has — a CI step, an
        agent's command timeout, a person's patience — and a runner that only speaks
        at the end says NOTHING at all when that happens. Exit code 1, no output, no
        way to tell a red suite from a killed one (#2020).
        """
        mark = "ok  " if r.ok else "FAIL"
        note = " (timed out)" if r.timed_out else ""
        _say(f"  {mark} {r.path.name:<45} {r.seconds:6.1f}s{note}")
        if args.verbose:
            for ln in r.output.splitlines():
                _say(f"       | {ln}")
        elif not r.ok:
            for ln in _tail(r.output):
                _say(f"       | {ln}")

    def run_and_report(path: Path) -> Result:
        """One file, whatever happens to it.

        A crash INSIDE the runner — the pool's worker raising, `MemoryError`, a broken
        pipe — used to travel up as a bare traceback with no file name in it, and under
        `--jobs` it took the run down having named nothing. It is a red line with a
        cause on it now, and the run goes on: what killed one file is exactly the thing
        somebody needs to see next to the file's name.
        """
        try:
            return run_one(path, timeout_of(path, args.timeout))
        except MemoryError:                          # the worker died, not the test
            return Result(path, 137, 0.0, "the runner ran out of memory on this file")
        except Exception as exc:                     # noqa: BLE001
            return Result(path, 1, 0.0,
                          f"the runner itself failed on this file: "
                          f"{type(exc).__name__}: {exc}")

    stopped = ""
    try:
        with _stop_signals() as why:
            if args.jobs > 1:
                # Completion order, not alphabetical: a line is worth more when it is
                # printed than when it is sorted.
                with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
                    futures = {pool.submit(run_and_report, p): p for p in wanted}
                    for fut in concurrent.futures.as_completed(futures):
                        r = fut.result()
                        results.append(r)
                        report(r)
            else:
                for p in wanted:
                    r = run_and_report(p)
                    results.append(r)
                    report(r)
            del why
    except KeyboardInterrupt:
        stopped = "interrupted (Ctrl-C)"
    except _Signalled as sig:
        stopped = f"stopped by {sig}"
    except BaseException as exc:                     # noqa: BLE001 — then re-raised
        # Anything else at all: say what it was and what had passed BEFORE the traceback
        # goes out. A runner that dies quietly is the whole of #2020.
        _say(f"\nthe runner died: {type(exc).__name__}: {exc}")
        killed = _kill_everything_still_running()
        if killed:
            _say(f"stopped mid-file, and took it down: {', '.join(sorted(killed))}")
        _summarise(results, wanted, started)
        raise
    if stopped:
        _say(f"\n{stopped}")
        killed = _kill_everything_still_running()
        if killed:
            _say(f"stopped mid-file, and took it down: {', '.join(sorted(killed))}")

    # The same summary an aborted run prints, so the two can never drift apart: a
    # partial run must be as loud about what it did as a finished one.
    _summarise(results, wanted, started)
    hollow = [r for r in results if r.skipped_everything]
    if hollow:
        _say(f"{len(hollow)} file(s) green having SKIPPED what they could not run "
             f"here — {', '.join(r.path.name for r in hollow)}")
    red = [r for r in results if not r.ok]
    return 1 if (red or stopped or len(results) != len(wanted)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
