"""Per-run output files under ``results/``.

Long-lived probes (the traffic sniffer, the Lua tracer) used to print to the
terminal only, or to append to one fixed file — so a restart either lost the
previous session or blended two of them into one unreadable log. Every run gets
its own timestamped file instead::

    results/traffic/20260727_181500_traffic.jsonl
    results/traces/20260727_181500_trace.log

A run may also carry a free-text label, asked for by the panel when a sniffer is
started ("what is this session about?"). It lands between the timestamp and the
name, so a directory of runs stays sortable by time yet readable at a glance::

    results/traces/20260728_120000_alliance_raid_trace.log

``results/`` is git-ignored (subdirectories included), so nothing written here
ever reaches a commit.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

# Anything a filesystem (or a human reading a directory listing) would rather
# not see in a name. Whitespace collapses into a single underscore; the rest is
# dropped. Non-ASCII letters survive — labels are typed in Russian.
_LABEL_STRIP = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_LABEL_SPACE = re.compile(r"\s+")


def slug(label: str | None) -> str:
    """Normalise a user-typed run label into a filename fragment.

    Empty, whitespace-only or all-forbidden input gives ``""``, which callers
    treat as "no label" — the name then looks exactly as it did before labels
    existed.
    """
    if not label:
        return ""
    cleaned = _LABEL_SPACE.sub("_", _LABEL_STRIP.sub("", label).strip())
    return cleaned.strip("._")

# tools/lib/run_output.py -> tools/lib -> tools -> <repo>
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(REPO, "results")


def new_run_path(subdir: str, name: str, when: datetime | None = None,
                 label: str | None = None) -> str:
    """Absolute path ``results/<subdir>/<YYYYMMDD_HHMMSS>_[<label>_]<name>``.

    The directory is created if missing. Paths are absolute (derived from this
    file, not from ``os.getcwd()``), so a tool started from anywhere — the panel
    spawns its children with its own working directory — still writes into the
    repo's ``results/``. Two runs starting inside the same second get ``_2``,
    ``_3``, … appended rather than sharing a file.

    ``label`` is optional free text (see :func:`slug`); omitted or empty, the
    name is the plain timestamp form.
    """
    directory = os.path.join(RESULTS, subdir)
    os.makedirs(directory, exist_ok=True)
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    tag = slug(label)
    path = os.path.join(directory, f"{stamp}_{tag}_{name}" if tag else f"{stamp}_{name}")
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base}_{n}{ext}"):
        n += 1
    return f"{base}_{n}{ext}"


def open_run_file(subdir: str, name: str, label: str | None = None):
    """Open a fresh run file for writing; returns ``(handle, path)``.

    Line-buffered and utf-8: these logs are tailed while the run is still going,
    and a run usually ends with SIGTERM/TerminateProcess (the panel's Stop),
    which never flushes a block buffer.
    """
    path = new_run_path(subdir, name, label=label)
    return open(path, "w", encoding="utf-8", buffering=1), path
