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
import threading

#: Set by `panel/runtime/updates.py::relaunch`: how many seconds this process may keep
#: writing into the capture file its parent opened for it.
CAPTURE_ENV = "LW_PANEL_CAPTURE_SEC"


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
    cap_capture()


def _stop_capturing() -> None:
    """Point fds 1 and 2 at nowhere — the boot is over and the capture has what it needs."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:                       # noqa: BLE001 — nothing to flush
        pass
    try:
        spare = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        for fd in (1, 2):
            try:
                os.dup2(spare, fd)
            except OSError:
                pass
    finally:
        try:
            os.close(spare)
        except OSError:
            pass


def cap_capture() -> None:
    """Stop writing into the parent's capture file once the boot has had its chance.

    THE CAPTURE IS FOR A BOOT, NOT FOR A LIFETIME (#1897). The replacement's stdout is a
    file the panel it replaced opened for it, and the panel prints tens of kilobytes an
    hour once it is running — a capture nobody closed is a file that grows for as long
    as the panel lives. So the process closes its own: a daemon timer, armed only when
    the parent asked for one, that hands fds 1 and 2 to `os.devnull` afterwards.

    Nothing is lost that this is for: an import error, a refused profile, a traceback on
    the way up all happen in the first seconds.
    """
    try:
        seconds = float(os.environ.pop(CAPTURE_ENV, "") or 0)
    except ValueError:
        return
    if seconds <= 0:
        return
    timer = threading.Timer(seconds, _stop_capturing)
    timer.daemon = True
    timer.start()
