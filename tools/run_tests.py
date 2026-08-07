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
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

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


def run_one(path: Path, timeout: float) -> Result:
    started = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, str(path)], cwd=str(REPO),
                              capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        code = 124
        output = (out.decode("utf-8", "replace") if isinstance(out, bytes) else out)
        output += f"\nTIMED OUT after {timeout:.0f}s"
    return Result(path, code, time.monotonic() - started, output)


def _tail(text: str, lines: int = 6) -> list[str]:
    """The last few lines that are not an `ok` — which is what a failure looks like."""
    keep = [ln.rstrip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("ok ")]
    return keep[-lines:]


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

    print(f"{len(wanted)} file(s), tier {args.tier}, {sys.executable}")
    started = time.monotonic()
    results: list[Result] = []

    if args.jobs > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(run_one, p, timeout_of(p, args.timeout)): p
                       for p in wanted}
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())
    else:
        for p in wanted:
            results.append(run_one(p, timeout_of(p, args.timeout)))

    results.sort(key=lambda r: r.path.name)
    for r in results:
        mark = "ok  " if r.ok else "FAIL"
        note = " (timed out)" if r.timed_out else ""
        print(f"  {mark} {r.path.name:<45} {r.seconds:6.1f}s{note}")
        if args.verbose:
            print("".join(f"       | {ln}\n" for ln in r.output.splitlines()))
        elif not r.ok:
            for ln in _tail(r.output):
                print(f"       | {ln}")

    red = [r for r in results if not r.ok]
    hollow = [r for r in results if r.skipped_everything]
    print(f"\n{len(results) - len(red)}/{len(results)} files green "
          f"in {time.monotonic() - started:.0f}s")
    if hollow:
        print(f"{len(hollow)} file(s) green having SKIPPED what they could not run "
              f"here — {', '.join(r.path.name for r in hollow)}")
    if red:
        print("red: " + ", ".join(r.path.name for r in red))
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
