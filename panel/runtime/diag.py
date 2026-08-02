"""Packing the debug logs and handing them off — one copy, for both the pressers.

Two places ask for the same archive: the «Настройки» tab's «Отправить диагностику»
button, and the shell's "send the log to the developer" dialog. The routine used to be
a method on the panel window that both reached for; wave 5 of #1184 moved it into the
tab, and the dialog's button was left calling a method that no longer existed — a
`AttributeError` at the one press that exists to report a problem (#1191).

So it lives here instead, where neither owns it: a function over the runtime, callable
from the shell, from a tab, and from `python -m panel.tabs.settings` alike.
"""
from __future__ import annotations

import threading

from .. import debug_log as dbgmod
from .. import debug_sender as dbgsender
from .paths import repo_rel


def send_archive(rt) -> None:
    """Zip this profile's debug logs and hand them to `debug_send_url`.

    The destination is a stub for now (no transport wired), so this always produces the
    zip and reports where it went — an empty URL means "do not send", which is not an
    error: the archive is still written for a by-hand hand-off.

    Packing reads a rotated log that may be megabytes, so it happens on a thread; every
    line it reports is posted back onto the Tk thread.
    """
    url = rt.settings.opt_str("debug_send_url")
    path = rt.profiles.debug_log()
    rt.say("debug", "log.debug.packing")

    def work():
        try:
            status, archive, _detail = dbgsender.send(
                url, path=path, logger=dbgmod.get_logger("sender"))
        except Exception as exc:  # noqa: BLE001
            # BOUND, not captured: Python deletes the `except` name when the block
            # ends, so a lambda closing over it raised NameError at the one moment
            # this line exists for — reporting that the send failed.
            rt.root.after(0, lambda e=exc: rt.say("debug", "log.debug.failed", error=e))
            return
        rel = repo_rel(archive)

        def done():
            if status == "disabled":
                rt.say("debug", "log.debug.no_dest", path=rel)
            elif status == "sent":
                rt.say("debug", "log.debug.sent", dest=url, path=rel)
            else:                     # "stub" — archive is ready, transport is not
                rt.say("debug", "log.debug.stub", path=rel, dest=url)
        rt.root.after(0, done)

    threading.Thread(target=work, daemon=True).start()
