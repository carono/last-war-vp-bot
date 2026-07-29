"""Free-text notes attached to a sniffer run — "what the player did".

A run file is named by its start time plus a short label
(``tools/lib/run_output.py``), which is enough to find it again and nothing
like enough to analyse it: a trace is a list of Lua class names, and without
knowing which buttons were pressed, in what order, and what changed afterwards,
the analysis starts by interrogating the operator (see
``docs/skills/sniff.md`` §8.4).

So the panel asks once, right after the sniffer is stopped, and stores the
answer *next to* each run file of that session::

    results/traces/20260728_171425_Сбор_ресурсов_trace.log
    results/traces/20260728_171425_Сбор_ресурсов_trace.note.md   <- the note
    results/traffic/20260728_171426_Сбор_ресурсов_traffic.jsonl
    results/traffic/20260728_171426_Сбор_ресурсов_traffic.note.md

The same note is written beside every file of the run, so whichever half you
open first, the description is one directory listing away. It is Markdown —
readable as-is — with the description under a fixed heading, so
:func:`read_note` can hand just the description back to a tool.

The panel's other answer is "delete": a run that recorded the wrong thing is
noise in a directory that is read by hand, so :func:`discard_run` removes the
files and their notes.

``results/`` is git-ignored, notes included — nothing here reaches a commit.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_output import RESULTS  # noqa: E402  (same directory, bare-name import)

# Sibling of a run file: same stem, this suffix. `.note.md` and not `.md`, so a
# glob for the run files themselves (`*_trace.log`, `*_traffic.jsonl`) never
# picks a note up, and a glob for notes never picks anything else.
NOTE_SUFFIX = ".note.md"

# The description lives under this heading. Everything above it is metadata the
# note carries for a human reader; everything below it is what the operator
# typed, verbatim.
BODY_HEADING = "## What the player did"

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
    """Path of the note that belongs beside ``run_path`` (whether it exists or not)."""
    base, _ext = os.path.splitext(os.path.abspath(run_path))
    return base + NOTE_SUFFIX


def render_note(run_paths: list[str], description: str, label: str | None = None,
                when: datetime | None = None) -> str:
    """The Markdown a note file holds. Pure — the writing is :func:`write_note`."""
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    title = (label or "").strip() or "no label"
    lines = [f"# Sniffer run — {title}", "",
             f"- label: {title}",
             f"- saved: {stamp}",
             "- files:"]
    for path in run_paths:
        lines.append(f"  - {_display(path)}")
    lines += ["", BODY_HEADING, "", description.strip(), ""]
    return "\n".join(lines)


def write_note(run_paths, description: str, label: str | None = None,
               when: datetime | None = None) -> list[str]:
    """Write the same note beside every run file; returns the note paths written.

    Files that no longer exist are skipped (a child may have failed before
    opening its own), and an empty description writes nothing at all — a note
    saying nothing is worse than no note, because it looks like an answer.
    """
    paths = [p for p in run_paths if p and os.path.exists(p)]
    if not paths or not description.strip():
        return []
    text = render_note(paths, description, label=label, when=when)
    written = []
    for path in paths:
        dest = note_path(path)
        try:
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            continue          # one unwritable note must not lose the others
        written.append(dest)
    return written


def read_note(run_path: str) -> str | None:
    """The description recorded for ``run_path``, or None if the run has no note.

    A note whose heading is missing (hand-written, or a future format) is
    returned whole rather than dropped — the caller wants context, and stale
    metadata lines are cheaper than losing the description.
    """
    path = note_path(run_path)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    head, sep, body = text.partition(BODY_HEADING)
    return (body if sep else text).strip() or None


def discard_run(run_paths) -> list[str]:
    """Delete the run's files and their notes; returns what was actually removed."""
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


def _display(path: str) -> str:
    """A run path as it reads in a note: relative to the repo when it is inside it."""
    repo = os.path.dirname(RESULTS)
    try:
        rel = os.path.relpath(os.path.abspath(path), repo)
    except ValueError:                      # different drive on Windows
        return path
    return path if rel.startswith("..") else rel.replace(os.sep, "/")
