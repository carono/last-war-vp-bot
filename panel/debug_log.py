"""Rotating technical debug log for the control panel.

This is a developer diagnostic, kept apart from the per-profile ``panel.log`` that
mirrors the human-facing log widget. Where ``panel.log`` is the record of what the
bot said, this file is the record of what the panel *did*: every log line at its
severity, every uncaught error with its traceback, and a running snapshot of the
systems' state (daemon, timers, triggers, dashboard) at DEBUG. It is rotated by
size so an overnight session cannot grow it without bound.

The panel owns one debug file per profile (next to that profile's ``panel.log``),
re-pointed when the active profile changes — :func:`setup` is idempotent for
exactly that reason. Levels are the standard DEBUG / INFO / WARNING / ERROR.

The auto-send half zips the current debug file together with its rotated backups
and hands the archive to a configured destination. No transport is wired yet:
:func:`send_archive` always writes the archive to disk (so it can be handed off by
any means) and reports back that the destination is a stub until one is chosen —
the config field that names it is ``debug_send_dest`` on the Settings page.
"""
from __future__ import annotations

import logging
import os
import zipfile
from logging.handlers import RotatingFileHandler

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))

# The single global fallback path. In practice the panel points the logger at the
# active profile's directory (panel/profiles/<name>/debug.log) via setup(path=...).
DEBUG_LOG = os.path.join(PANEL_DIR, "panel_debug.log")

# One shared logger; setup() swaps its file handler rather than making a new one,
# so re-pointing on a profile switch never leaves two handlers writing at once.
LOGGER_NAME = "lastwar.panel"

# Rotation defaults — mirrored into SETTINGS_DEFAULTS so a profile can override them.
DEFAULT_MAX_KB = 2048        # 2 MiB per file before it rolls over
DEFAULT_BACKUPS = 5          # debug.log + debug.log.1 … debug.log.5
DEFAULT_LEVEL = "DEBUG"

# Where the auto-send archive goes. TBD — no transport is wired; this is the config
# field the person points somewhere, and send_archive refuses politely until it does.
DEFAULT_DESTINATION = ""

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


def get_logger() -> logging.Logger:
    """The shared panel debug logger (configured by :func:`setup`)."""
    return logging.getLogger(LOGGER_NAME)


def setup(path: str | None = None, *, max_kb: int = DEFAULT_MAX_KB,
          backups: int = DEFAULT_BACKUPS, level: str = DEFAULT_LEVEL) -> logging.Logger:
    """Point the shared logger at ``path`` with size rotation. Idempotent.

    Replaces any handler this module installed before, so calling it again on a
    profile switch (or a settings edit) re-points the file and re-reads the caps
    without ever stacking two handlers. Never raises: logging must not be the thing
    that stops the panel, so a directory that cannot be created just leaves the
    logger handler-less (it swallows records) rather than crashing the caller.
    """
    path = path or DEBUG_LOG
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level_of(level))
    logger.propagate = False        # ours alone — never up to the root logger
    for handler in list(logger.handlers):
        if getattr(handler, "_panel_debug", False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:        # noqa: BLE001
                pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=max(0, int(max_kb)) * 1024,
            backupCount=max(0, int(backups)), encoding="utf-8")
    except (OSError, ValueError):
        return logger
    handler._panel_debug = True      # our marker, so the next setup() finds it
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    return logger


def shutdown(logger: logging.Logger | None = None) -> None:
    """Close our file handler(s) — called when the panel is going away."""
    logger = logger or get_logger()
    for handler in list(logger.handlers):
        if getattr(handler, "_panel_debug", False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:        # noqa: BLE001
                pass


def log_files(path: str | None = None) -> list[str]:
    """The active debug file plus its rotated backups (``debug.log``, ``.1``, …)."""
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


def make_archive(dest: str | None = None, *, path: str | None = None) -> str:
    """Zip the debug file and its backups into ``dest`` (``<path>.zip`` by default).

    Always writes the archive, even when there is nothing to log yet — an empty zip
    is a truthful "nothing was captured" rather than a missing file the caller has
    to special-case.
    """
    path = path or DEBUG_LOG
    dest = dest or (path + ".zip")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as bundle:
        for entry in log_files(path):
            try:
                bundle.write(entry, arcname=os.path.basename(entry))
            except OSError:
                continue             # a file rotated out from under us — skip it
    return dest


def send_archive(destination, *, path: str | None = None,
                 logger: logging.Logger | None = None) -> tuple[str, str, str]:
    """Zip the debug log and (eventually) ship it to ``destination``.

    Returns ``(status, archive_path, detail)`` where ``status`` is one of
    ``"sent"`` / ``"no_dest"`` / ``"stub"``. No transport is wired yet: this is the
    seam a real uploader fills. The archive is written to disk regardless, so it is
    always ready to hand off by any means the person has.
    """
    logger = logger or get_logger()
    archive = make_archive(path=path)
    dest = str(destination or "").strip()
    if not dest:
        logger.warning("debug archive ready at %s, but no destination is configured",
                       archive)
        return ("no_dest", archive, "no destination configured")
    # >>> Wire the real transport here (upload / mail / copy) and return "sent". <<<
    logger.info("debug archive ready at %s; destination %r is not wired yet",
                archive, dest)
    return ("stub", archive, f"destination {dest!r} is not wired yet")
