"""Free-text notes attached to a sniffer run — "what the player did".

A run file is named by its start time plus a short label
(``tools/lib/run_output.py``), which is enough to find it again and nothing
like enough to analyse it: a trace is a list of Lua class names, and without
knowing which buttons were pressed, in what order, and what changed afterwards,
the analysis starts by interrogating the operator (see
``docs/skills/sniff.md`` §8.4).

So the panel asks once, right after the sniffer is stopped, and stores the
answer *next to* each run file of that session — same base name, ``_desc.txt``
instead of the file's own kind::

    results/traces/20260728_171425_Сбор_ресурсов_trace.log
    results/traces/20260728_171425_Сбор_ресурсов_desc.txt        <- the description
    results/traffic/20260728_171426_Сбор_ресурсов_traffic.jsonl
    results/traffic/20260728_171426_Сбор_ресурсов_desc.txt

The same text is written beside every file of the run, so whichever half you
open first, the description is one directory listing away. The file holds the
operator's words and nothing else: it is read straight into an analysis prompt
("what the player did"), and a header would have to be stripped there.

The panel's other answer is "delete": a run that recorded the wrong thing is
noise in a directory that is read by hand, so :func:`discard_run` removes the
files and their descriptions.

``results/`` is git-ignored, descriptions included — nothing here reaches a commit.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_output import RESULTS  # noqa: E402  (same directory, bare-name import)

# What replaces `_trace.log` / `_traffic.jsonl` in a run file's name to give the
# description beside it. A distinct kind of its own, so a glob for the run files
# never picks a description up and vice versa.
NOTE_SUFFIX = "_desc.txt"

# Run files as written by run_output.new_run_path():
#   <YYYYMMDD_HHMMSS>[_<label>]_<kind>[_<n>].<ext>
# The trailing `_<n>` is the same-second collision suffix; it is part of the
# file name but not of the session's identity.
_RUN_NAME = re.compile(
    r"^(?P<stamp>\d{8}_\d{6})(?:_(?P<label>.*?))?"
    r"_(?P<kind>traffic|trace)(?:_(?P<dup>\d+))?\.(?:jsonl|log)$")

# Where each kind of run file lives, relative to results/.
KIND_DIRS = {"traffic": "traffic", "trace": "traces"}

# The two children of one sniff session start ~1 s apart (npcap opens its
# interfaces while the tracer is still installing hooks), so their file names
# carry *different* timestamps. Grouping the files of one run therefore matches
# on the label plus a window, not on an equal stamp. Generous: the tracer can
# take a while to attach when the daemon is cold.
PAIR_WINDOW = 120.0


def parse_run_name(path: str) -> dict | None:
    """Split a run file name into ``{stamp, label, kind, dup}``; None if it is not one."""
    m = _RUN_NAME.match(os.path.basename(path))
    if not m:
        return None
    return {"stamp": m.group("stamp"), "label": m.group("label") or "",
            "kind": m.group("kind"), "dup": m.group("dup")}


def note_path(run_path: str) -> str:
    """Path of the description beside ``run_path`` (whether it exists or not).

    The run file's own kind is what gets replaced, so both halves of a session
    point at a name built the same way — ``…_Сбор_ресурсов_trace.log`` and
    ``…_Сбор_ресурсов_traffic.jsonl`` become ``…_Сбор_ресурсов_desc.txt`` in
    their respective directories. A name that is not a run file (a hand-made
    one, say) keeps its stem and just gains the suffix.
    """
    path = os.path.abspath(run_path)
    directory, name = os.path.split(path)
    info = parse_run_name(name)
    if info:
        tag = f"_{info['label']}" if info["label"] else ""
        # The same-second collision suffix travels with the name: two runs that
        # started in one second must not share one description.
        dup = f"_{info['dup']}" if info["dup"] else ""
        return os.path.join(directory, f"{info['stamp']}{tag}{dup}{NOTE_SUFFIX}")
    return os.path.splitext(path)[0] + NOTE_SUFFIX


def write_note(run_paths, description: str, label: str | None = None,
               when: datetime | None = None) -> list[str]:
    """Write the description beside every file of the run; returns the paths written.

    Files that no longer exist are skipped (a child may have failed before
    opening its own), and an empty description writes nothing at all — a note
    saying nothing is worse than no note, because it looks like an answer.

    ``label`` and ``when`` are accepted for the caller's convenience (the panel
    knows both) but do not enter the file: it holds the operator's words alone,
    ready to be pasted into an analysis prompt.
    """
    paths = [p for p in run_paths if p and os.path.exists(p)]
    text = description.strip()
    if not paths or not text:
        return []
    written = []
    for path in paths:
        dest = note_path(path)
        try:
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError:
            continue          # one unwritable note must not lose the others
        written.append(dest)
    return written


def read_note(run_path: str) -> str | None:
    """The description recorded for ``run_path``, or None if the run has none."""
    try:
        with open(note_path(run_path), encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def run_stats(path: str) -> dict:
    """``{"size": bytes, "records": n}`` for one run file — what the panel shows.

    ``records`` counts what the file is made of: decoded frames in a traffic
    transcript (one JSON object per line) and traced calls in a Lua trace
    (``XSCALL`` lines; the tracer's own status lines are not calls). It is the
    honest answer to "did this run actually record anything", which a byte count
    alone is not — a transcript of nothing but keepalives is still kilobytes.
    """
    out = {"size": 0, "records": 0}
    try:
        out["size"] = os.path.getsize(path)
    except OSError:
        return out
    kind = (parse_run_name(path) or {}).get("kind")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if kind == "trace":
                    out["records"] += "XSCALL" in line
                elif line.strip():
                    out["records"] += 1
    except OSError:
        pass
    return out


def discard_run(run_paths) -> list[str]:
    """Delete the run's files and their descriptions; returns what was removed."""
    gone = []
    for path in run_paths:
        if not path:
            continue
        for target in (path, note_path(path)):
            try:
                os.remove(target)
            except OSError:
                continue
            gone.append(target)
    return gone


def list_runs(results: str | None = None) -> list[dict]:
    """Every recorded sniff session, newest first.

    Returns ``{"stamp", "label", "files": {kind: path}, "description": str|None}``.
    The two halves of a session are matched by label within :data:`PAIR_WINDOW`
    seconds of each other (their timestamps differ, see the constant); a half
    whose partner is missing is a run of its own, which is exactly how it should
    read — half a session is what was recorded.
    """
    root = results or RESULTS
    found = []
    for kind, subdir in KIND_DIRS.items():
        directory = os.path.join(root, subdir)
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            info = parse_run_name(name)
            if info:
                info["path"] = os.path.join(directory, name)
                found.append(info)
    found.sort(key=lambda i: (i["stamp"], i["kind"]))

    runs: list[dict] = []
    for info in found:
        run = runs[-1] if runs else None
        if (run is None or run["label"] != info["label"]
                or info["kind"] in run["files"]
                or _age(info["stamp"]) - _age(run["stamp"]) > PAIR_WINDOW):
            run = {"stamp": info["stamp"], "label": info["label"], "files": {},
                   "description": None}
            runs.append(run)
        run["files"][info["kind"]] = info["path"]
        if run["description"] is None:
            run["description"] = read_note(info["path"])
    runs.reverse()
    return runs


def _age(stamp: str) -> float:
    """A run stamp as epoch seconds (for the pairing window)."""
    return datetime.strptime(stamp, "%Y%m%d_%H%M%S").timestamp()
