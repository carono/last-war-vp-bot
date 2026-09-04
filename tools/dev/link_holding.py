"""How long the panel holds the game link, and what it spends the hold on (#2404).

The complaint this answers is «поручения стоят в очереди друг за другом»: the claim in
`panel/runtime/claims.py` is taken for a WHOLE scenario run, while the only part of a
run that genuinely needs the client to itself is the call into the Lua VM. Everything
else — the recipe's own waits, its `IF`s over values it has already read, its logging —
holds an exclusive nobody else can use.

`profiles/<name>/panel.log` is a complete stopwatch and needs no instrumentation added:

    > action: <name>                       a run took the client
      READ_LUA joined = 0                  one step, timestamped
      WAIT 0.5s
    < action: <name> OK|FAILED|HALTED      the run gave it back

So a step's cost is the gap to the NEXT logged line of the same run, a run's cost is the
gap between its two brackets, and the share of the window under a hold is the union of
the run intervals. The log's resolution is one second, which is coarse for a single step
and perfectly good over a window of hours.

Run it before and after a change and compare the two tables:

    python3 tools/dev/link_holding.py --hours 12
    python3 tools/dev/link_holding.py --profile default --from "2026-09-04 00:00:00"
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

#: `2026-09-04 03:03:08 [rally]   READ_LUA joined = 0`
LINE_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \[([^\]]+)\] (.*)$")
#: A tag may carry the errand's own name in front of everything it says —
#: `[timer] alliance_help: > action: help_ally` — and two errands share the `timer` tag,
#: so the name is part of what tells their runs apart.
WHOSE_RE = re.compile(r"^([^\s:\[<>][^:]*): (.*)$")
OPEN_RE = re.compile(r"^> action: (\S+)")
SHUT_RE = re.compile(r"^< action: (\S+)\s*(\S*)")
STEP_RE = re.compile(r"^\s+([A-Z_]+)\b")

#: The DSL statements that put a question or an order ON THE WIRE. Everything else a
#: recipe does is arithmetic over what it has already been told.
VM_STEPS = frozenset({"LUA", "READ_LUA", "TAP", "GAME", "JUMP", "CLICK", "CLICK_AT",
                      "FIND", "PRESS", "DRAG", "TYPE", "START_GAME", "STOP_GAME",
                      "DONATE_ALLIANCE_TECH", "SWEEP", "COLLECT", "RUN_TOOL"})
WAIT_STEPS = frozenset({"WAIT", "SLEEP"})

#: What the panel says when a press could not get in. Counted, not timed — a refusal
#: has no duration, only a victim.
REFUSALS = ("панель занята другой работой", "дождись завершения текущего действия",
            "как только тот уступит")


def parse_stamp(text: str) -> dt.datetime:
    return dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def seek_window(fh, start: dt.datetime) -> None:
    """Binary-search the file for the first line at or after ``start``.

    `panel.log` is never rotated — 800 MB going back weeks on a live profile — so a
    scan from the top costs minutes for a window of hours. The file is chronological,
    which is all a bisection needs.
    """
    lo, hi = 0, os.fstat(fh.fileno()).st_size
    while lo < hi:
        mid = (lo + hi) // 2
        fh.seek(mid)
        fh.readline()                     # discard the partial line
        pos = fh.tell()
        line = fh.readline()
        match = LINE_RE.match(line)
        if match is None or pos >= hi:
            lo = mid + 1
            continue
        if parse_stamp(match.group(1)) < start:
            lo = pos + len(line)
        else:
            hi = mid
    fh.seek(lo)
    fh.readline()


class Run:
    """One scenario run, and where its seconds went.

    THE GAP BELONGS TO THE LINE THAT ENDS IT, not to the one that starts it. A step is
    written to the log once it has HAPPENED — `READ_LUA joined = 0` carries the answer,
    `IF todo == -4 -> False` carries the verdict — so the silence between two lines is
    the cost of the SECOND. Charging it to the first reads every recipe backwards, and
    the tell is a scenario made of nothing but `READ_LUA` reporting zero seconds on the
    wire.

    A `WAIT` is the exception and says so in its own line: it is logged BEFORE it sleeps,
    so the declared seconds are taken out of the following gap and billed to the wait.
    """

    __slots__ = ("name", "tag", "start", "last", "sleep", "steps", "count")

    def __init__(self, name: str, tag: str, start: dt.datetime) -> None:
        self.name, self.tag, self.start = name, tag, start
        self.last = start
        #: Seconds a `WAIT` line has announced and not yet been billed for.
        self.sleep = 0.0
        self.steps: dict = {}
        #: How many steps of each kind the run played — a mean per call is the number
        #: that says whether the hold is «many calls» or «a slow call».
        self.count: dict = {}

    def charge(self, when: dt.datetime, kind: str) -> None:
        secs = max(0.0, (when - self.last).total_seconds())
        self.last = when
        slept = min(secs, self.sleep)
        self.sleep -= slept
        if slept:
            self.steps["wait"] = self.steps.get("wait", 0.0) + slept
        if secs - slept:
            self.steps[kind] = self.steps.get(kind, 0.0) + (secs - slept)
        self.count[kind] = self.count.get(kind, 0) + 1


WAIT_SEC_RE = re.compile(r"^\s+WAIT\s+([\d.]+)\s*s")


def declared_wait(rest: str) -> float:
    """How long a `WAIT` line says it is about to sleep. Zero when it does not say."""
    match = WAIT_SEC_RE.match(rest)
    return float(match.group(1)) if match is not None else 0.0


def bucket(step: str) -> str:
    if step in VM_STEPS:
        return "vm"
    return "local"


def collect(path: str, start: dt.datetime, end: dt.datetime) -> dict:
    open_runs: dict = {}
    done: list = []
    spans: list = []
    refused: dict = {}
    lines = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        seek_window(fh, start)
        for line in fh:
            match = LINE_RE.match(line)
            if match is None:
                continue
            stamp = parse_stamp(match.group(1))
            if stamp < start:
                continue
            if stamp > end:
                break
            lines += 1
            tag, rest = match.group(2), match.group(3)
            whose = WHOSE_RE.match(rest)
            if whose is not None:
                tag, rest = f"{tag}/{whose.group(1)}", whose.group(2)
            opened = OPEN_RE.match(rest)
            if opened is not None:
                open_runs[tag] = Run(opened.group(1), tag, stamp)
                continue
            shut = SHUT_RE.match(rest)
            if shut is not None:
                run = open_runs.pop(tag, None)
                if run is not None:
                    run.charge(stamp, "local")
                    done.append(run)
                    spans.append((run.start, stamp))
                continue
            if any(word in rest for word in REFUSALS):
                refused[tag] = refused.get(tag, 0) + 1
            step = STEP_RE.match(rest)
            run = open_runs.get(tag)
            if run is None:
                continue
            if step is None:
                # A line the run did not write — a push landing in the same tag, a
                # status note. It says nothing about where the seconds went, so it only
                # moves the clock: the gap stays open for the step that closes it.
                continue
            name = step.group(1)
            run.charge(stamp, bucket(name))
            if name in WAIT_STEPS:
                run.sleep += declared_wait(rest)
    return {"runs": done, "spans": spans, "refused": refused, "lines": lines,
            "unclosed": len(open_runs)}


def union(spans: list) -> float:
    """Seconds of the window during which SOMETHING held the client."""
    total, edge = 0.0, None
    for begin, finish in sorted(spans):
        if edge is None or begin > edge:
            total += (finish - begin).total_seconds()
            edge = finish
        elif finish > edge:
            total += (finish - edge).total_seconds()
            edge = finish
    return total


def report(data: dict, start: dt.datetime, end: dt.datetime) -> None:
    window = (end - start).total_seconds()
    per: dict = {}
    for run in data["runs"]:
        row = per.setdefault(run.name, {"n": 0, "held": 0.0, "vm": 0.0, "wait": 0.0,
                                        "local": 0.0, "start": 0.0})
        row["n"] += 1
        row["held"] += sum(run.steps.values())
        for kind, secs in run.steps.items():
            row[kind] = row.get(kind, 0.0) + secs
        row["calls"] = row.get("calls", 0) + run.count.get("vm", 0)
    held = union(data["spans"])
    print(f"window   {start} .. {end}   ({window / 3600:.2f} h, {data['lines']} lines)")
    print(f"held     {held:.0f} s = {100 * held / window:.1f}% of the window"
          f"   ({len(data['runs'])} runs, {data['unclosed']} still open)")
    print()
    print(f"{'scenario':<28}{'runs':>6}{'held s':>10}{'%win':>7}"
          f"{'avg s':>8}{'vm s':>9}{'wait s':>9}{'local s':>9}{'vm%':>6}"
          f"{'calls':>8}{'s/call':>8}")
    for name, row in sorted(per.items(), key=lambda kv: -kv[1]["held"]):
        total = row["held"] or 1.0
        print(f"{name:<28}{row['n']:>6}{row['held']:>10.0f}"
              f"{100 * row['held'] / window:>7.1f}{row['held'] / row['n']:>8.1f}"
              f"{row['vm']:>9.0f}{row['wait']:>9.0f}{row['local'] + row['start']:>9.0f}"
              f"{100 * row['vm'] / total:>6.0f}"
              f"{row.get('calls', 0):>8}"
              f"{row['vm'] / max(1, row.get('calls', 0)):>8.2f}")
    print()
    print("refusals by tag:", ", ".join(
        f"{tag}={n}" for tag, n in sorted(data["refused"].items(), key=lambda kv: -kv[1])))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="default")
    ap.add_argument("--log", default=None, help="a panel.log to read instead")
    ap.add_argument("--hours", type=float, default=12.0)
    ap.add_argument("--from", dest="since", default=None, help="YYYY-MM-DD HH:MM:SS")
    ap.add_argument("--to", dest="until", default=None)
    args = ap.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = args.log or os.path.join(root, "profiles", args.profile, "panel.log")
    if not os.path.exists(path):
        print(f"no such log: {path}", file=sys.stderr)
        return 2
    # The log runs on the GAME's clock, which is not this machine's, so «the last N
    # hours» is measured back from the last line rather than from `now`.
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(max(0, os.fstat(fh.fileno()).st_size - 65536))
        fh.readline()
        last = None
        for line in fh:
            match = LINE_RE.match(line)
            if match is not None:
                last = parse_stamp(match.group(1))
    end = parse_stamp(args.until) if args.until else (last or dt.datetime.now())
    start = parse_stamp(args.since) if args.since else end - dt.timedelta(hours=args.hours)
    report(collect(path, start, end), start, end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
