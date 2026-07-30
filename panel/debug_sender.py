"""Zip the panel's debug logs and (eventually) ship them somewhere.

The other half of the diagnostic feature: :mod:`panel.debug_log` writes the rotating
``debug.log`` (and its backups); this module bundles the last few of them into one zip
and hands it to a destination. The destination is a stub for now — the config field
``debug_send_url`` names it, and until a transport is wired :func:`send` always writes
the archive to disk (so it is ready to hand off by any means) and reports back that
sending is not configured.

Kept apart from :mod:`panel.debug_log` on purpose: one module is "how the panel
records what it did", the other is "how that record leaves the machine", and the
second is the one a real uploader edits.
"""
from __future__ import annotations

import os
import zipfile

from . import debug_log

# How many of the rotated files to bundle by default: the live log plus a couple of
# backups is plenty of context without shipping the whole history every time.
DEFAULT_KEEP = 3


def make_archive(dest: str | None = None, *, path: str | None = None,
                 keep: int = DEFAULT_KEEP) -> str:
    """Zip the newest ``keep`` debug files into ``dest`` (``<path>.zip`` by default).

    Always writes the archive, even when nothing has been logged yet — an empty zip
    is a truthful "nothing was captured" rather than a missing file every caller has
    to special-case.
    """
    path = path or debug_log.DEBUG_LOG
    dest = dest or (path + ".zip")
    files = debug_log.log_files(path)
    if keep is not None and keep >= 0:
        files = files[:keep]
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as bundle:
        for entry in files:
            try:
                bundle.write(entry, arcname=os.path.basename(entry))
            except OSError:
                continue             # a file rotated out from under us — skip it
    return dest


def send(url, *, path: str | None = None, keep: int = DEFAULT_KEEP,
         logger=None) -> tuple[str, str, str]:
    """Zip the debug logs and (eventually) ship them to ``url``.

    Returns ``(status, archive_path, detail)`` where ``status`` is one of
    ``"sent"`` / ``"disabled"`` / ``"stub"``. ``"disabled"`` is an empty ``url`` —
    the person has not asked for sending. No transport is wired yet: this is the seam
    a real uploader fills. The archive is written to disk regardless, so it is always
    ready to hand off by hand.
    """
    logger = logger or debug_log.get_logger("sender")
    archive = make_archive(path=path, keep=keep)
    dest = str(url or "").strip()
    if not dest:
        logger.info("diagnostics archived to %s; sending is off (no debug_send_url)",
                    archive)
        return ("disabled", archive, "no destination configured")
    # >>> Wire the real transport here (HTTP upload / mail / copy) and return "sent". <<<
    logger.info("diagnostics archived to %s; destination %r is not wired yet",
                archive, dest)
    return ("stub", archive, f"destination {dest!r} is not wired yet")
