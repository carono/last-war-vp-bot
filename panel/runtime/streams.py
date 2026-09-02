"""A process that cannot print must not die of it.

`pythonw.exe` starts with no console, so `sys.stdout` and `sys.stderr` are ``None`` —
and so are they in any process started DETACHED with nothing put in their place. A
single `print(..., file=sys.stderr)` anywhere on the way up then raises
``AttributeError: 'NoneType' object has no attribute 'write'``, on a process that has
no way to say so. From the outside that is a panel which simply never appeared (#1897).

The panel is full of such prints — they are the only thing that speaks before the
logging is configured — so the streams are made real once, at the top of every
entrypoint, rather than each print being wrapped in a guard nobody will remember to add
next time.
"""
from __future__ import annotations

import io
import os
import sys


def ensure() -> None:
    """Give this process a stdout and a stderr, if it has none. Idempotent."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is not None:
            continue
        try:
            sink = open(os.devnull, "w", encoding="utf-8")
        except OSError:                     # noqa: BLE001 — nowhere to write at all
            sink = io.StringIO()
        setattr(sys, name, sink)
    if getattr(sys, "stdin", None) is None:
        try:
            sys.stdin = open(os.devnull, encoding="utf-8")
        except OSError:
            sys.stdin = io.StringIO()
