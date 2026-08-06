"""Rotating technical debug log for the control panel.

This is a developer diagnostic, kept apart from the panel's user-facing log — that
one streams into the Tkinter widget (and its per-profile ``panel.log`` mirror). This
file is the record of what the panel *did*: every component's key events, every error
with its traceback, and the systems' state, at DEBUG / INFO / WARNING / ERROR.

One file per profile, ``panel/profiles/<name>/debug.log``, rotated by size (5 MiB ×
3 backups by default) so an overnight session cannot grow it without bound. Every
line is stamped and tagged with the component that wrote it::

    [2026-07-30 16:23:11.123] [INFO] [timers] fired collect_base_resources

Usage. A component asks for its own logger by name and logs to it; the panel wires
the single rotating file under all of them::

    from . import debug_log
    log = debug_log.get_logger("timers")
    log.info("fired %s", name)
    log.error("step failed", exc_info=True)

The panel calls :func:`configure` at start-up and on every profile switch to point
that shared file at the active profile (idempotent — it never stacks two handlers).
Zipping and shipping the files lives next door in :mod:`panel.debug_sender`.

SCOPES. One panel window may hold several profiles open at once (#1206), and each owes
its own ``debug.log``. A *scope* is a name inserted into the logger tree —
``lastwar.panel.<scope>.<component>`` — with that profile's rotating handler on
``lastwar.panel.<scope>``. Two scopes are two files, filled independently::

    log = debug_log.get_logger("timers", scope="alt")
    debug_log.configure(profiles.debug_log("alt"), scope="alt")

An unscoped call means exactly what it always meant: the shared tree, the shared file.
So nothing that has not been given a scope changes behaviour, and a window with one
profile open is unchanged in every respect.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))

# The single global fallback path. In practice the panel points the shared handler
# at the active profile's directory (panel/profiles/<name>/debug.log) via configure().
DEBUG_LOG = os.path.join(PANEL_DIR, "panel_debug.log")

# The parent of every component logger. get_logger("timers") returns the child
# "lastwar.panel.timers"; the one rotating handler lives on this parent and every
# child propagates up to it, so components never touch the file themselves.
ROOT_NAME = "lastwar.panel"

# Rotation defaults — 5 MiB per file, three rolled-over backups (debug.log.1 … .3).
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUPS = 3
DEFAULT_LEVEL = "DEBUG"

# The line format the docstring shows: a millisecond stamp, the level, the component.
_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(component)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
}


def level_of(name) -> int:
    """Map a level name to its ``logging`` constant (DEBUG for anything unknown)."""
    return _LEVELS.get(str(name or "").strip().upper(), logging.DEBUG)


def _scope_name(scope: "str | None") -> str:
    """The logger the handler for ``scope`` sits on — the shared root when unscoped."""
    scope = _clean(scope)
    return f"{ROOT_NAME}.{scope}" if scope else ROOT_NAME


def _clean(part) -> str:
    """A logger-name-safe piece: dots would silently make a whole extra level."""
    return str(part or "").strip().replace(".", "_")


class _ComponentFilter(logging.Filter):
    """Give every record a ``component`` field derived from its logger name.

    ``lastwar.panel.timers`` → ``timers``; the bare ``lastwar.panel`` → ``panel``.
    Without this the ``[%(component)s]`` in the format would raise on a record that
    did not set it, so it is attached to the handler and covers all of them.

    A scoped handler is told its own prefix, so ``lastwar.panel.alt.timers`` reads as
    ``timers`` in ``alt``'s file rather than as ``alt.timers``. The file already IS the
    profile; repeating its name on all forty thousand lines says nothing.
    """

    def __init__(self, prefix: str = ROOT_NAME) -> None:
        super().__init__()
        self.prefix = prefix

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if name == self.prefix:
            record.component = "panel"
        elif name.startswith(self.prefix + "."):
            record.component = name[len(self.prefix) + 1:]
        else:
            record.component = name
        return True


def get_logger(component: str = "panel", scope: "str | None" = None) -> logging.Logger:
    """The debug logger for one component (``timers`` / ``triggers`` / …).

    Configured centrally by :func:`configure`; usable before it is called (records
    are simply dropped until the handler exists), so a module can grab its logger at
    import time and the panel wires the file later.

    ``scope`` names one open profile's own file (see the module docstring); left out,
    this is the shared tree it has always been.
    """
    component = _clean(component) or "panel"
    name = _scope_name(scope)
    if name != ROOT_NAME:
        _seal(name)
    return logging.getLogger(f"{name}.{component}")


def _seal(name: str) -> None:
    """Cut one scope off the shared tree, the moment it exists rather than at `configure`.

    A scoped logger is a CHILD of the shared one, and the shared one is not a neutral
    parent: the first open session has no scope and writes its own `debug.log` through
    it (see the module docstring). So until propagation is turned off, everything a
    SECOND session says travels on up into the FIRST profile's file — real lines about
    the wrong account, in the one place a person looks to find out what theirs did
    (#1250). `configure` does turn it off, but it runs after the session is built, and
    a runtime says plenty while it is coming up.

    The null handler is what keeps the promise the docstring makes about the same gap:
    records before `configure` are *dropped*. Without it a sealed scope with no handler
    yet reaches `logging.lastResort`, which prints to stderr — the same lines, moved
    from the wrong file to the wrong console. `configure` only ever removes handlers it
    marked itself, so this one survives beside the real one.
    """
    root = logging.getLogger(name)
    if root.propagate:
        root.propagate = False
        root.addHandler(logging.NullHandler())


def configure(path: str | None = None, *, max_bytes: int = DEFAULT_MAX_BYTES,
              backups: int = DEFAULT_BACKUPS, level: str = DEFAULT_LEVEL,
              scope: "str | None" = None) -> logging.Logger:
    """Point ``scope``'s rotating handler at ``path``. Idempotent.

    Replaces any handler this module installed on that scope before, so calling it
    again on a profile switch re-points the file without ever stacking two handlers —
    and leaves every OTHER scope's file exactly where it was, which is what lets two
    open profiles each keep their own. Never raises: logging must not be the thing
    that stops the panel, so a directory that cannot be created just leaves the parent
    handler-less (records are dropped) rather than crashing the caller.
    """
    path = path or DEBUG_LOG
    name = _scope_name(scope)
    root = logging.getLogger(name)
    root.setLevel(level_of(level))
    root.propagate = False        # ours alone — never up to the process root logger
    for handler in list(root.handlers):
        if getattr(handler, "_panel_debug", False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:        # noqa: BLE001
                pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=max(0, int(max_bytes)),
            backupCount=max(0, int(backups)), encoding="utf-8")
    except (OSError, ValueError):
        return root
    handler._panel_debug = True      # our marker, so the next configure() finds it
    handler.addFilter(_ComponentFilter(name))
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    root.addHandler(handler)
    return root


def shutdown(scope: "str | None" = None) -> None:
    """Close ``scope``'s rotating handler — called when its window is going away."""
    root = logging.getLogger(_scope_name(scope))
    for handler in list(root.handlers):
        if getattr(handler, "_panel_debug", False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:        # noqa: BLE001
                pass


def log_files(path: str | None = None) -> list[str]:
    """The active debug file plus its rotated backups (``debug.log``, ``.1``, …).

    Newest first: the live file, then ``.1`` (the most recently rolled) onwards —
    which is the order the sender wants when it keeps only the last N.
    """
    path = path or DEBUG_LOG
    files = [path] if os.path.exists(path) else []
    index = 1
    while True:
        backup = f"{path}.{index}"
        if not os.path.exists(backup):
            break
        files.append(backup)
        index += 1
    return files
