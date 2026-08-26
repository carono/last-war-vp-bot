"""The window's one connection to the machine's service — started and stopped here.

The same shape `panel/runtime/web_control.py` has, and for the same reason: there is ONE
of these per WINDOW rather than one per profile. A window holds several accounts and its
`WebApi` already answers for all of them, so a link per profile would be several
conversations saying the same things about the same panel.

WHY IT IS ALWAYS ON. There is nothing to configure and nothing to switch: a panel that
cannot find a service loses nothing (the window and its own port are untouched), and a
panel that finds one becomes reachable from a door that is up before anybody signs in.
A switch here would be a switch whose OFF position means «be unreachable for no reason»,
and the one knob that matters — whether the service exists at all — is the service's own.

WHAT IT ANNOUNCES is what the service needs to ROUTE and to say who is there: the Windows
login this window runs as, this process's pid, its version, and which profiles are open
right now. The last is a callable rather than a list, because a window opens and closes
profiles while it runs.
"""
from __future__ import annotations

import getpass
import threading

from ..web.api import WebApi
from .service_link import ServiceLink

_LOCK = threading.Lock()
_LINK: "ServiceLink | None" = None


def start(rt, workspace=None) -> "ServiceLink | None":
    """Bring the link up for this window. Idempotent; never raises at the caller."""
    global _LINK                              # noqa: PLW0603 — one per window, like the server
    with _LOCK:
        if _LINK is not None:
            return _LINK
        try:
            link = ServiceLink(
                WebApi(rt),
                session=_login(),
                profiles=lambda: _profiles(workspace, rt),
                version=_version(),
                boot=_boot(),
                log=lambda line: _say(rt, line))
            link.start()
        except Exception as exc:              # noqa: BLE001 — a link, never the panel
            _say(rt, f"[service] not started: {type(exc).__name__}: {exc}")
            return None
        _LINK = link
        return link


def stop() -> None:
    """Let the socket go. Safe to call when nothing was ever started."""
    global _LINK                              # noqa: PLW0603
    with _LOCK:
        link, _LINK = _LINK, None
    if link is not None:
        link.stop()


def state() -> dict:
    """Is this window talking to a service, and how much has it answered?"""
    with _LOCK:
        link = _LINK
    if link is None:
        return {"linked": False, "answered": 0}
    return {"linked": bool(link.connected), "answered": int(link.answered)}


# -- the three readings ------------------------------------------------------
def _login() -> str:
    """WHICH Windows session this window is in — asked, never assumed (`CLAUDE.md`)."""
    try:
        return getpass.getuser()
    except Exception:                         # noqa: BLE001 — a reading
        return ""


def _profiles(workspace, rt) -> list:
    if workspace is not None:
        try:
            return list(workspace.names)
        except Exception:                     # noqa: BLE001 — a reading
            pass
    try:
        return [str(rt.profiles.active)]
    except Exception:                         # noqa: BLE001 — a reading
        return []


def _version() -> str:
    try:
        from . import updates

        return str(updates.version_text() or "")
    except Exception:                         # noqa: BLE001 — a reading
        return ""


def _boot() -> dict:
    """WHICH CODE this process is running — the one reading a version cannot give."""
    try:
        from . import updates

        return dict(updates.boot())
    except Exception:                         # noqa: BLE001 — a reading
        return {}


def _say(rt, line: str) -> None:
    try:
        rt.log.put(line)
    except Exception:                         # noqa: BLE001 — a line, never the panel
        pass
