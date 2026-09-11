"""The panel's buttons ON TOP of the client's window — the helper, and its two presses.

This is `panel/runtime/game_control.py` for a front-end rather than for the client: a
tiny table both front-ends read, so «Кнопки поверх игры» cannot come to mean one thing in
the window and another on the phone, plus the start and the stop of the process that
draws them (`tools/game_overlay.py`).

WHY A PROCESS AND NOT A WINDOW OF OURS. A panel run by the machine's service has no
window at all (`panel/headless.py`), and a window is the one thing a panel cannot grow on
demand: Tk is either the process's main loop or it is nothing. The overlay therefore is
its own process, started into the session the panel is already standing in — the same
place, and for the same reason, that the keyboard macros had to be (#2767).

WHAT IT IS NOT ALLOWED TO BE. It is a FRONT-END. It presses `/api/actions/run` over the
panel's ordinary door with the ordinary token, exactly as the phone does, and holds no
gate, no Lua and no game step of its own (`CLAUDE.md`). Nothing here — and nothing in the
helper — knows what «collect the base» means; the ability is
`src/lastwar_bot/actions/collect_base_resources.md` and always was.

ONE OVERLAY PER PROFILE, and the child factory is what says so: the process is spawned
through `rt.children`, which is per profile, written down per profile and reaped per
profile (`panel/runtime/children.py`). So «is it up» is «has THIS profile got a live child
with this tag», never a module-level flag — an answer shared between two open accounts is
the isolation rule broken in the quietest possible way.

A PROFILE WHOSE CLIENT IS IN ANOTHER WINDOWS SESSION CANNOT HAVE ONE YET, and is told so
rather than handed a bar that would draw over the wrong desktop. Starting a window in
another session needs that session's own token (`tools/session_launch.py`, and SYSTEM to
use it); until that is wired, the honest answer is a refusal with a reason.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import game_process, paths

# `web_control` is imported INSIDE the two functions that need it, never here: it reaches
# `panel/web/server.py`, which imports `panel/web/api.py`, which imports this module —
# and at import time that circle is a half-built `WebApi` rather than an error anybody
# can read.

#: The tag the child is spawned under — and therefore the answer to «is it up».
TAG = "overlay"

#: The ids a press travels under, in the window and on the wire.
SHOW = "show"
HIDE = "hide"

#: The helper itself.
TOOL = os.path.join(paths.REPO, "tools", "game_overlay.py")


@dataclass(frozen=True)
class Control:
    """One press about the overlay, in both front-ends."""

    id: str
    #: The word on the button — the SAME key in the window and in the browser.
    label: str
    #: Said in the log before it happens.
    saying: str
    #: Does this press want an overlay to be up already?
    wants_running: bool


CONTROLS = (
    Control(SHOW, "overlay.show", "log.overlay.starting", False),
    Control(HIDE, "overlay.hide", "log.overlay.stopping", True),
)

BY_ID = {control.id: control for control in CONTROLS}


def get(action: str):
    return BY_ID.get(action)


def supported() -> bool:
    """A desktop to draw on. Windows only — everywhere else there is no client either."""
    return os.name == "nt"


def child(rt):
    """This profile's live overlay child, or ``None``."""
    try:
        for kid in rt.children.live:
            if getattr(kid, "tag", "") == TAG and getattr(kid, "alive", False):
                return kid
    except Exception:                      # noqa: BLE001 — a reading, never the panel
        return None
    return None


def running(rt) -> bool:
    return child(rt) is not None


def door() -> tuple:
    """``(url, token)`` for the panel's own web door — whoever is actually answering it.

    The panel's server when this process is the one holding the port, and the MACHINE's
    service when the door has been handed over to it (`panel/runtime/web_control.py`,
    #2068). Loopback in both cases: the helper stands on this machine, so the address it
    is given must be one that does not depend on which network the phone is on.
    """
    from . import web_control

    server = web_control.serving()
    if server is not None:
        token = str(getattr(server, "token", "") or "")
        port = int(server.bound_port() or web_control.port_number())
        return f"{web_control.scheme()}://127.0.0.1:{port}", token
    try:
        from ..service import host as servicehost

        config = servicehost.load_config()
        scheme = "https" if str(config.get("certfile") or "").strip() else "http"
        return (f"{scheme}://127.0.0.1:{int(config.get('port') or 0)}",
                str(config.get("token") or ""))
    except Exception:                      # noqa: BLE001 — no door is an answer too
        return "", ""


def state(rt) -> dict:
    """What both front-ends draw: is it up, and which press applies."""
    up = running(rt)
    return {
        "running": up,
        "supported": supported(),
        "controls": [{"id": c.id, "label": c.label,
                      "enabled": supported() and (up == c.wants_running)}
                     for c in CONTROLS],
    }


def play(rt, action: str) -> dict:
    """Carry out one press. ``{"ok": …}``, with a REASON whenever it is False."""
    control = get(action)
    if control is None:
        return {"error": "unknown"}
    if not supported():
        return {"ok": False, "reason": "unsupported"}
    if control.id == HIDE:
        kid = child(rt)
        if kid is None:
            return {"ok": True, "running": False}
        rt.say(TAG, control.saying)
        try:
            kid.stop()
        except Exception:                  # noqa: BLE001 — it is on its way out
            pass
        return {"ok": True, "running": False}
    if running(rt):
        return {"ok": True, "running": True}
    if game_process.profile_user(rt.settings) is not None:
        # Another Windows session's desktop is not this process's to draw on.
        rt.say(TAG, "log.overlay.other_session")
        return {"ok": False, "reason": "other_session"}
    url, token = door()
    if not url:
        rt.say(TAG, "log.overlay.no_door")
        return {"ok": False, "reason": "no_door"}
    name = str(getattr(getattr(rt, "profiles", None), "active", "") or "")
    cmd = [rt.children.python(), "-u", TOOL, "--profile", name, "--url", url]
    # THE TOKEN IS PASSED ONLY WHEN THIS PROCESS IS THE DOOR. A command line is in every
    # process list and in the panel's own `children-<pid>.json`, so the ordinary case —
    # the machine's service holding the port — lets the helper read `service.json` for
    # itself instead of carrying the secret past two files that need not hold it.
    from . import web_control

    if token and web_control.serving() is not None:
        cmd += ["--token", token]
    rt.say(TAG, control.saying)
    kid = rt.children.spawn(TAG, cmd)
    if not kid.start():
        return {"ok": False, "reason": "failed"}
    return {"ok": True, "running": True}
