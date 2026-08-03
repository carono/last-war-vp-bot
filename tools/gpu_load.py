r"""Measure what the game client actually costs the video card.

Task #1219. The question the tool answers is "does this client draw the GPU, and how
much", per process and averaged over a window rather than sampled once — a single
reading of a game that renders in bursts is noise.

Two readings are taken side by side because they answer different halves:

* **Per-process** — the Windows ``GPU Engine`` performance counters, the same source
  Task Manager's *GPU* column uses. They are the only per-process figure available on a
  WDDM driver: ``nvidia-smi`` reports ``N/A`` for utilisation per process, and it does
  not even list a process that lives in another Windows session. The counters do.
  Instance names look like
  ``pid_153576_luid_0x00000000_0x0000fafa_phys_0_eng_0_engtype_3D`` — the engine type
  (``3D``, ``Copy``, ``VideoDecode``, …) is summed per pid.
* **Whole card** — ``nvidia-smi``: utilisation, board power and SM clock. Power is the
  honest number for "is the card working"; utilisation only says an engine was busy at
  all, so a client that renders 3 % of a frame and one that renders all of it can both
  read 100 %.

Usage (Windows Python — WSL's python3 has no access to the counters)::

    C:\Python312\python.exe tools\gpu_load.py --seconds 20
    C:\Python312\python.exe tools\gpu_load.py --seconds 20 --pid 153576 --pid 159492
    C:\Python312\python.exe tools\gpu_load.py --seconds 20 --label "minimised"
    C:\Python312\python.exe tools\gpu_load.py --seconds 20 --json

With no ``--pid`` every ``LastWar.exe`` currently running is measured, in every Windows
session. ``--label`` is echoed into the output so a series of runs stays readable.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time

POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
NVIDIA_SMI = r"C:\Windows\System32\nvidia-smi.exe"
TASKLIST = r"C:\Windows\System32\tasklist.exe"

# pid_153576_luid_0x00000000_0x0000fafa_phys_0_eng_0_engtype_3D
_INSTANCE = re.compile(
    r"^pid_(?P<pid>\d+)_luid_[0-9a-fx]+_[0-9a-fx]+_phys_(?P<phys>\d+)"
    r"_eng_(?P<eng>\d+)_engtype_(?P<engtype>.+)$",
    re.I,
)


def _run(cmd: list[str], timeout: float = 120.0) -> str:
    out = subprocess.run(
        cmd, capture_output=True, timeout=timeout, text=True, errors="replace"
    )
    return out.stdout


def game_pids() -> dict[int, str]:
    """Every LastWar.exe running, mapped to the Windows session it lives in."""
    found: dict[int, str] = {}
    text = _run([TASKLIST, "/FO", "CSV", "/NH"])
    for line in text.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) < 3 or "lastwar.exe" not in parts[0].lower():
            continue
        try:
            found[int(parts[1])] = f"{parts[2]}/{parts[3]}" if len(parts) > 3 else parts[2]
        except ValueError:
            continue
    return found


def sample_engines(seconds: int, interval: float = 1.0) -> list[dict]:
    """Average the GPU Engine counters over a window, one row per (pid, engtype)."""
    samples = max(1, int(round(seconds / interval)))
    script = (
        "$ErrorActionPreference='Stop';"
        f"(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' "
        f"-SampleInterval {max(1, int(interval))} -MaxSamples {samples}) | "
        "ForEach-Object { $_.CounterSamples } | "
        "Where-Object { $_.CookedValue -gt 0 } | "
        "ForEach-Object { $_.InstanceName + '|' + $_.CookedValue }"
    )
    text = _run([POWERSHELL, "-NoProfile", "-Command", script], timeout=seconds + 90)

    totals: dict[tuple[int, str], float] = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        name, _, value = line.partition("|")
        m = _INSTANCE.match(name.strip())
        if not m:
            continue
        try:
            pct = float(value.strip().replace(",", "."))
        except ValueError:
            continue
        key = (int(m.group("pid")), m.group("engtype").lower())
        totals[key] = totals.get(key, 0.0) + pct

    # The counters are per-sample percentages; divide by the number of samples taken.
    return [
        {"pid": pid, "engtype": engtype, "percent": total / samples}
        for (pid, engtype), total in sorted(totals.items())
    ]


def sample_card(seconds: int, interval: float = 1.0) -> dict:
    """Whole-card utilisation, power and clock, averaged over the same window."""
    rows: list[tuple[float, float, float, float]] = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        text = _run(
            [
                NVIDIA_SMI,
                "--query-gpu=utilization.gpu,power.draw,clocks.sm,memory.used",
                "--format=csv,noheader,nounits",
            ],
            timeout=30,
        )
        line = text.strip().splitlines()[0] if text.strip() else ""
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4:
            try:
                rows.append(tuple(float(p) for p in parts))  # type: ignore[arg-type]
            except ValueError:
                pass
        time.sleep(interval)
    if not rows:
        return {}
    n = len(rows)
    return {
        "samples": n,
        "util_percent": sum(r[0] for r in rows) / n,
        "power_w": sum(r[1] for r in rows) / n,
        "clock_sm_mhz": sum(r[2] for r in rows) / n,
        "memory_used_mib": sum(r[3] for r in rows) / n,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=int, default=20, help="length of the window")
    ap.add_argument(
        "--pid",
        type=int,
        action="append",
        default=[],
        help="measure this pid (repeatable); default is every LastWar.exe",
    )
    ap.add_argument("--label", default="", help="echoed into the output")
    ap.add_argument("--all", action="store_true", help="report every process, not just the game")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    games = game_pids()
    wanted = set(args.pid) or set(games)

    card = {}
    engines: list[dict] = []

    # The card poll runs first and the counters second; each takes the full window, so
    # the two do not overlap. Overlapping them would make the PowerShell child a
    # measurable load of its own inside the nvidia-smi window.
    card = sample_card(args.seconds)
    engines = sample_engines(args.seconds)

    per_pid: dict[int, dict] = {}
    for row in engines:
        if not args.all and row["pid"] not in wanted:
            continue
        entry = per_pid.setdefault(
            row["pid"], {"pid": row["pid"], "session": games.get(row["pid"], "?"), "engines": {}, "total": 0.0}
        )
        entry["engines"][row["engtype"]] = round(row["percent"], 2)
        entry["total"] += row["percent"]

    result = {
        "label": args.label,
        "seconds": args.seconds,
        "card": card,
        "processes": sorted(per_pid.values(), key=lambda e: -e["total"]),
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.label:
        print(f"== {args.label} ==")
    if card:
        print(
            f"card: util {card['util_percent']:.1f}%  power {card['power_w']:.1f} W  "
            f"sm {card['clock_sm_mhz']:.0f} MHz  vram {card['memory_used_mib']:.0f} MiB"
            f"  ({card['samples']} samples over {args.seconds}s)"
        )
    if not per_pid:
        print("no GPU activity recorded for the requested processes")
    for entry in result["processes"]:
        engines_text = "  ".join(f"{k}={v:.2f}%" for k, v in sorted(entry["engines"].items()))
        print(
            f"pid {entry['pid']:>7} [{entry['session']}]  total {entry['total']:6.2f}%   {engines_text}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
