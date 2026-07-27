"""Per-run output files under ``results/``.

Long-lived probes (the traffic sniffer, the Lua tracer) used to print to the
terminal only, or to append to one fixed file — so a restart either lost the
previous session or blended two of them into one unreadable log. Every run gets
its own timestamped file instead::

    results/traffic/20260727_181500_traffic.jsonl
    results/traces/20260727_181500_trace.log

``results/`` is git-ignored (subdirectories included), so nothing written here
ever reaches a commit.
"""
from __future__ import annotations

import os
from datetime import datetime

# tools/lib/run_output.py -> tools/lib -> tools -> <repo>
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(REPO, "results")


def new_run_path(subdir: str, name: str, when: datetime | None = None) -> str:
    """Absolute path ``results/<subdir>/<YYYYMMDD_HHMMSS>_<name>``, unique.

    The directory is created if missing. Paths are absolute (derived from this
    file, not from ``os.getcwd()``), so a tool started from anywhere — the panel
    spawns its children with its own working directory — still writes into the
    repo's ``results/``. Two runs starting inside the same second get ``_2``,
    ``_3``, … appended rather than sharing a file.
    """
    directory = os.path.join(RESULTS, subdir)
    os.makedirs(directory, exist_ok=True)
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(directory, f"{stamp}_{name}")
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base}_{n}{ext}"):
        n += 1
    return f"{base}_{n}{ext}"


def open_run_file(subdir: str, name: str):
    """Open a fresh run file for writing; returns ``(handle, path)``.

    Line-buffered and utf-8: these logs are tailed while the run is still going,
    and a run usually ends with SIGTERM/TerminateProcess (the panel's Stop),
    which never flushes a block buffer.
    """
    path = new_run_path(subdir, name)
    return open(path, "w", encoding="utf-8", buffering=1), path
