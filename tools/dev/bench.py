r"""The numbers to watch, one JSON line per run (#1282, audit §6).

A regression should be a DIFF, not a complaint. The audit listed nine numbers worth
keeping; this measures the four that need no game and appends them to
`results/bench.jsonl` (git-ignored), so «the panel got slower» becomes a `git`-free
before/after instead of a memory.

| # | number | how |
|---|---|---|
| 1 | `import panel.__main__` | a fresh interpreter per sample, so nothing is warm from the last one |
| 2 | first page build / warm page build | the harness `tests/test_panel_page_build.py` already has |
| 3 | undrawn-tab RATIO | tabs made, tabs drawn, and every drawn one EAGER — a ratio, never a count (#1273 broke the count) |
| 9 | test-suite wall time and red count, per tier | `tools/run_tests.py`, opt-in with `--tests` because it is minutes |

The five that are missing need a live client and belong in an acceptance run — chief
among them **#7, lock-seconds per wall-minute at idle**, which is the only number that
can tell «the panel feels slow» from «the client is at 21 fps». It is not measured here
because it cannot be measured without a game; that it is missing is a fact about this
tool, not about the number.

    C:\Python312\python.exe tools\dev\bench.py                  # 1-3
    C:\Python312\python.exe tools\dev\bench.py --tests          # …and the suite
    C:\Python312\python.exe tools\dev\bench.py --samples 5
    python3 tools/dev/bench.py --show                           # the last runs, as a table

Numbers 2 and 3 need Tk and a display; without one they are recorded as `null` rather
than skipped silently, so a row of nulls says «this run could not see them».
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "bench.jsonl"


def _interpreter() -> str:
    return sys.executable


def import_seconds(samples: int) -> dict:
    """#1 — `import panel.__main__`, in a fresh interpreter each time.

    In-process timing would measure the second import, which is a dictionary lookup.
    """
    code = ("import sys, time;"
            "sys.path[:0]=['.','tools/lib','src'];"
            "t=time.perf_counter();"
            "import panel.__main__;"
            "print(time.perf_counter()-t)")
    seen = []
    for _ in range(samples):
        proc = subprocess.run([_interpreter(), "-c", code], cwd=str(REPO),
                              capture_output=True, text=True)
        try:
            seen.append(float(proc.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            continue
    if not seen:
        return {"samples": 0, "median": None, "min": None, "max": None}
    return {"samples": len(seen), "median": round(statistics.median(seen), 3),
            "min": round(min(seen), 3), "max": round(max(seen), 3)}


def page_builds(samples: int) -> dict:
    """#2 and #3 — the page build, and what it drew, from the test harness.

    Four builds in one process is what the audit measured: the first still has the tab
    modules to import, the rest are warm, and the difference between them is the number
    that moves when somebody adds an eager tab.
    """
    sys.path[:0] = [str(REPO), str(REPO / "tools" / "lib"), str(REPO / "src"),
                    str(REPO / "tests")]
    blank = {"first": None, "warm_median": None, "tabs": None, "drawn": None,
             "eager": None, "lazy_all_undrawn": None, "why": None}
    try:
        import test_panel_page_build as harness_mod
    except Exception as exc:                                     # noqa: BLE001
        return {**blank, "why": f"{type(exc).__name__}: {exc}"}

    times, shape = [], {}
    for n in range(max(2, samples)):
        started = time.perf_counter()
        try:
            harness = harness_mod._Harness(staged=False)
        except Exception as exc:                                 # noqa: BLE001
            return {**blank, "why": f"{type(exc).__name__}: {exc}"}
        times.append(time.perf_counter() - started)
        try:
            if not shape:
                app, session = harness.app, harness.session
                with app._on(session):
                    tabs = app._plugin_tabs
                    drawn = {i for i, t in tabs.items() if t.built}
                    eager = {i for i, t in tabs.items() if type(t).EAGER}
                    shape = {"tabs": len(tabs), "drawn": len(drawn),
                             "eager": len(eager),
                             "lazy_all_undrawn": not ((set(tabs) - eager) & drawn)}
        finally:
            harness.close()
    return {"first": round(times[0], 3),
            "warm_median": round(statistics.median(times[1:]), 3),
            **shape, "why": None}


def suite(tiers: tuple) -> dict:
    """#9 — wall time and red count, per tier. Minutes, hence opt-in."""
    out = {}
    for tier in tiers:
        started = time.perf_counter()
        proc = subprocess.run([_interpreter(), "tools/run_tests.py", tier],
                              cwd=str(REPO), capture_output=True, text=True)
        seconds = time.perf_counter() - started
        red = green = None
        for line in proc.stdout.splitlines():
            if "files green" in line:
                head = line.split(" files green")[0].strip()
                try:
                    green, total = (int(x) for x in head.split("/"))
                    red = total - green
                except ValueError:
                    pass
        out[tier] = {"seconds": round(seconds, 1), "green": green, "red": red}
    return out


def show(last: int) -> int:
    if not OUT.exists():
        print(f"nothing recorded yet — {OUT.relative_to(REPO)} does not exist")
        return 1
    rows = [json.loads(ln) for ln in OUT.read_text(encoding="utf-8").splitlines() if ln]
    print(f"{'when':<20} {'import':>8} {'first':>8} {'warm':>8} {'tabs':>10} {'suite':>16}")
    for row in rows[-last:]:
        page = row.get("page") or {}
        tiers = row.get("suite") or {}
        imp = _secs((row.get("import") or {}).get("median"))
        first = _secs(page.get("first"))
        warm = _secs(page.get("warm_median"))
        tabs, drawn = page.get("tabs"), page.get("drawn")
        shape = f"{drawn}/{tabs} drawn" if tabs else "-"
        suite_text = " ".join(f"{t}:{v.get('red')}red" for t, v in tiers.items()) or "-"
        print(f"{row.get('when', '?'):<20} {imp:>8} {first:>8} {warm:>8} "
              f"{shape:>10} {suite_text:>16}")
    return 0


def _secs(value) -> str:
    return f"{value:.2f}s" if isinstance(value, (int, float)) else "-"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record the numbers worth watching.")
    ap.add_argument("--samples", type=int, default=3,
                    help="how many times to measure each number (default 3)")
    ap.add_argument("--tests", action="store_true",
                    help="also run the offline and ui tiers and record their time and "
                         "red count — minutes, not seconds")
    ap.add_argument("--tiers", default="offline,ui",
                    help="which tiers --tests runs (default offline,ui)")
    ap.add_argument("--show", action="store_true", help="print the recorded runs")
    ap.add_argument("--last", type=int, default=10, help="how many rows --show prints")
    ap.add_argument("--note", default="", help="a word about what this run is")
    args = ap.parse_args(argv)

    if args.show:
        return show(args.last)

    row = {
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": args.note,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "os": os.name,
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO),
                                 capture_output=True, text=True).stdout.strip(),
        "import": import_seconds(args.samples),
        "page": page_builds(args.samples),
        "suite": suite(tuple(t for t in args.tiers.split(",") if t)) if args.tests else None,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps(row, ensure_ascii=False, indent=2))
    print(f"\nappended to {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
