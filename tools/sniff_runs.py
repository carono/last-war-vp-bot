#!/usr/bin/env python3
r"""List recorded sniffer sessions with the operator's description of each.

Every panel sniff session leaves two files — the wire transcript
(`results/traffic/*_traffic.jsonl`) and the Lua trace
(`results/traces/*_trace.log`) — plus, when the operator answered the panel's
"what did you do in the game?" prompt, a note beside each of them
(`tools/lib/run_notes.py`).

**Run this before analysing a trace.** The description is the context the two
files lack: which buttons were pressed, in what order, what changed afterwards.
Without it the analysis starts by interrogating the operator
(`docs/skills/sniff.md` §8.4); with it, it starts at §8.5.

    python3 tools/sniff_runs.py                 # every run, newest first
    python3 tools/sniff_runs.py --last 5
    python3 tools/sniff_runs.py ресурс          # runs whose label/description match
    python3 tools/sniff_runs.py --undescribed   # runs still missing a description
    python3 tools/sniff_runs.py --json

Headless runs (`live_sniffer.py` / `lua_trace.py` started by hand) get no panel
prompt, so their description can be attached afterwards — by default to the
newest run, or to the newest one matching a filter:

    python3 tools/sniff_runs.py --describe "alliance -> gifts -> collect all"
    python3 tools/sniff_runs.py подарки --describe "opened gifts, pressed collect x3"

Reads nothing from the game and needs no Windows Python: it is a directory
listing. Exit code 1 when a filter matched nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import run_notes  # noqa: E402


def _matches(run: dict, needle: str) -> bool:
    hay = " ".join([run["label"], run.get("description") or ""]).lower()
    return needle.lower() in hay


def _size(path: str) -> str:
    try:
        n = os.path.getsize(path)
    except OSError:
        return "missing"
    return f"{n / 1024:.0f} KB" if n >= 1024 else f"{n} B"


def _print(run: dict, repo: str) -> None:
    label = run["label"].replace("_", " ") or "(no label)"
    print(f"{run['stamp']}  {label}")
    for kind in ("trace", "traffic"):
        path = run["files"].get(kind)
        if path:
            print(f"    {kind:<8} {os.path.relpath(path, repo)}  ({_size(path)})")
        else:
            print(f"    {kind:<8} —")
    desc = run.get("description")
    if desc:
        for line in desc.splitlines():
            print(f"    | {line}")
    else:
        print("    | (no description — ask the operator, see sniff.md §8.4)")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("filter", nargs="?", help="substring of the label or description")
    ap.add_argument("--last", type=int, metavar="N", help="only the N newest runs")
    ap.add_argument("--undescribed", action="store_true",
                    help="only runs that carry no description yet")
    ap.add_argument("--describe", metavar="TEXT",
                    help="attach TEXT to the newest matching run (writes its note)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    repo = os.path.dirname(_HERE)
    runs = run_notes.list_runs()
    if args.filter:
        runs = [r for r in runs if _matches(r, args.filter)]
    if args.undescribed:
        runs = [r for r in runs if not r.get("description")]
    if not runs:
        print("no matching runs under results/", file=sys.stderr)
        return 1

    if args.describe:
        run = runs[0]                      # list_runs() is newest first
        written = run_notes.write_note(list(run["files"].values()), args.describe,
                                       label=run["label"])
        if not written:
            print("nothing written — the run's files are gone", file=sys.stderr)
            return 1
        run["description"] = args.describe
        for path in written:
            print(f"note: {os.path.relpath(path, repo)}")
        return 0

    if args.last:
        runs = runs[:args.last]
    if args.json:
        print(json.dumps(runs, ensure_ascii=False, indent=2))
        return 0
    for run in runs:
        _print(run, repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
