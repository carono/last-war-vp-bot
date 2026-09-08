r"""A day of thread hijacks, added up by who asked for them (#2656).

The exposure is known and it is large: on one profile 43 969 hijacks in 401 minutes —
110 a minute, ~3.8 for every step of DSL the panel ran. Every one of them suspends the
game's main thread, redirects its RIP into an allocated page and puts it back, and two
thirds of the client's crashes land within five seconds of one
(`docs/research/client-crashes.md`).

«3.8 per step» sizes the problem and does not address it: it is not worth changing a
call path until it is known WHICH path. So the hijack counts itself by the label its
caller already passes (`tools/lib/hijack_call.py::STATS["by_label"]`), the link writes
the minute's tally into the profile's debug log, and this adds a day of those lines up.

    python3 tools/hijack_tally.py --profile <name>
    python3 tools/hijack_tally.py --profile <name> --day 2026-09-08
    C:\Python312\python.exe tools\hijack_tally.py --log <path to debug.log>

It reads the rotated logs too (`debug.log`, `debug.log.1`, …), because a busy profile
fills one in a few hours and a day is the unit worth looking at.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import game_paths  # noqa: E402

#: `[2026-09-08 20:46:10.117] [INFO] [link] hijack labels 60s: a=12 b=3`
_LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d) [\d:.]+\].*hijack labels [\d.]+s: (.*)$")
#: …and its neighbour, the whole-minute total, kept as a cross-check.
_TOTAL = re.compile(r"^\[(\d{4}-\d\d-\d\d) [\d:.]+\].*\bhijacks (\d+) in ")
#: One `label=count` pair. A label may hold anything but whitespace and the `=` sign.
_PAIR = re.compile(r"(\S+)=(\d+)")


def tally(lines, day: str | None = None) -> tuple[dict, int, int]:
    """Add up `label=count` pairs. Returns (by label, labelled total, minute total)."""
    by: dict[str, int] = {}
    labelled = 0
    total = 0
    for line in lines:
        m = _TOTAL.match(line)
        if m and (day is None or m.group(1) == day):
            total += int(m.group(2))
            continue
        m = _LINE.match(line)
        if not m or (day is not None and m.group(1) != day):
            continue
        for name, count in _PAIR.findall(m.group(2)):
            n = int(count)
            by[name] = by.get(name, 0) + n
            labelled += n
    return by, labelled, total


def logs_for(profile: str) -> list[Path]:
    d = Path(game_paths.repo_dir()) / "profiles" / profile
    return sorted(p for p in d.glob("debug.log*") if p.is_file())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", help="whose debug logs to read")
    ap.add_argument("--log", action="append", default=[], help="a log by path; repeatable")
    ap.add_argument("--day", help="only this date, YYYY-MM-DD (default: every day in them)")
    ap.add_argument("--top", type=int, default=30, help="how many labels to print")
    args = ap.parse_args()

    paths = [Path(p) for p in args.log] or (logs_for(args.profile) if args.profile else [])
    if not paths:
        ap.error("name a --profile or a --log")

    by: dict[str, int] = {}
    labelled = total = 0
    for path in paths:
        if not path.is_file():
            print(f"[tally] no such log: {path}", file=sys.stderr)
            continue
        with path.open("rb") as fh:
            part, part_n, part_total = tally(
                (raw.decode("utf-8", "replace") for raw in fh), args.day)
        for name, n in part.items():
            by[name] = by.get(name, 0) + n
        labelled += part_n
        total += part_total

    if not by:
        print("nothing counted — is the panel new enough to write «hijack labels»?")
        return 1
    when = args.day or "the whole of these logs"
    print(f"{labelled} hijacks with a label over {when}"
          + (f"  (the minute totals say {total})" if total else ""))
    print("\n   count   share  label")
    for name, n in sorted(by.items(), key=lambda kv: -kv[1])[:args.top]:
        print(f"  {n:>6}  {100 * n / labelled:5.1f}%  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
