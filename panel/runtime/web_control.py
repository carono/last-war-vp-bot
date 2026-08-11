"""The remote control as a setting of the WINDOW, not of an account (#1313).

There has only ever been ONE web server per panel: it answers for every profile the
window has open, the page has a switcher at the top and every route takes a profile
(`panel/web/api.py`). What did not match that was where its knobs lived — on a tab, and
therefore in a profile's `config.json`, one copy per account. A window with three
profiles open held three answers to a question with one subject, obeyed whichever of
them switched on first, and showed the other two «профиль «X» обслуживает, порт N» as
though that were an ordinary state of affairs rather than the shape of the mistake.

`CLAUDE.md` makes every value answer two questions, and the first is «is there one of
this per MACHINE or one per ACCOUNT?». A socket is the machine's. So the block moved to
`profiles/settings.json` beside `active_profile` and `open_profiles`
(`panel/profile.py`), the tab became a menu entry (`panel/runtime/web_dialog.py`), and
this module is the one place that turns the setting into a running server.

WHAT IS HERE AND WHAT IS NOT. Here: the knobs, their defaults, the token, and starting
and stopping the socket to match. Not here: any widget (the dialog draws them), and any
route (the server and the API already exist and know nothing about this file).

WHOSE LOG SAYS IT. A start, a stop and a refusal are said with `rt.say` into the profile
that is on screen when it happens — the panel's own doing rather than an account's, but
a person watching one profile's log is the person who just pressed the button. The
server's own running commentary (a sign-in, a wrong token) is unchanged and still goes
through the runtime it was started with; `log_message` alone belongs to the window
(`panel/web/server.py`, #1306).
"""
from __future__ import annotations

import secrets
import ssl
import threading

from .. import profile as profilemod
from ..web import server as webmod

#: How much randomness a generated token carries. Sixteen bytes is twenty-two URL-safe
#: characters: the link carries them, so nobody types them, and a forwarded port means
#: the guessing may be done from anywhere rather than from the sofa.
TOKEN_BYTES = 16

#: The tag every line about the remote control is logged under.
TAG = "web"

#: The knobs, and what each means when it has never been set. `port` and `host` are
#: asked of the modules that own those answers rather than spelled here — the port has a
#: machine-wide variable in front of it (`tools/lib/game_paths.py`).
_KEYS = ("enabled", "port", "host", "token", "cert", "key")

#: The one server this process has, and the lock around starting it. Process-wide for
#: the same reason `panel/runtime/panel_control.py`'s handler is: there is one window
#: here, and this is a fact about it rather than about a runtime.
_LOCK = threading.RLock()
_SERVER = None


# -- the setting ------------------------------------------------------------
def defaults() -> dict:
    """A panel that has never been configured: off, on this machine's port, no token."""
    return {"enabled": False, "port": str(webmod.default_port()),
            "host": webmod.DEFAULT_HOST, "token": "", "cert": "", "key": ""}


def settings() -> dict:
    """The panel-wide knobs, with anything unset filled in from :func:`defaults`.

    Reading is also what brings an older panel's answer across: the migration runs at
    most once per installation and is a no-op on every call after it
    (`panel/profile.py::migrate_web_settings`).
    """
    profilemod.migrate_web_settings()
    values = defaults()
    stored = profilemod.web_settings()
    for key in _KEYS:
        if key in stored and stored[key] is not None:
            values[key] = bool(stored[key]) if key == "enabled" else str(stored[key])
    return values


def save(values: dict) -> dict:
    """Write the knobs down for the whole panel and hand back what was stored."""
    current = settings()
    for key in _KEYS:
        if key in values:
            current[key] = bool(values[key]) if key == "enabled" else str(values[key])
    profilemod.set_web_settings(current)
    return current


def new_token() -> str:
    """A fresh token, saved. Every phone that had the old one is logged out by it."""
    return save({"token": secrets.token_urlsafe(TOKEN_BYTES)})["token"]


def port_number(values: "dict | None" = None) -> int:
    """The port as a number — this machine's default for anything unreadable."""
    values = settings() if values is None else values
    try:
        return max(1, min(65535, int(str(values.get("port", "")).strip())))
    except (TypeError, ValueError):
        return webmod.default_port()


# -- the socket -------------------------------------------------------------
def serving():
    """The server this process is running, or ``None``.

    Asked of `panel/web/server.py`'s own registry rather than of the variable below, so
    that a server started some other way — a test, a tab launched on its own — is seen
    too and never bound over.
    """
    with _LOCK:
        if _SERVER is not None and _SERVER.running:
            return _SERVER
    return webmod.serving_any()


def running() -> bool:
    return serving() is not None


def apply(rt) -> bool:
    """Make the running state match the setting. The one place that starts or stops.

    Never raises at the caller: a taken port is the ordinary failure (a panel that has
    just closed has not let go yet) and it belongs in the log and on the dialog's label,
    not in a traceback out of a checkbox. A failure switches the setting OFF, so the
    state on the dialog and the state on the machine cannot disagree.

    Returns whether a server is listening when it is done.
    """
    global _SERVER
    values = settings()
    if not values["enabled"]:
        stop(rt)
        return False
    with _LOCK:
        if _SERVER is not None and _SERVER.running:
            return True
        # Somebody else's server on this port — a test's, or a tab started on its own.
        # One socket is the whole point, so there is nothing to add.
        if webmod.serving_any() is not None:
            return True
        token = values["token"] or new_token()
        try:
            server = webmod.WebServer(rt, host=values["host"].strip(),
                                      port=port_number(values), token=token,
                                      certfile=values["cert"].strip(),
                                      keyfile=values["key"].strip())
            server.start()
        except OSError:
            _SERVER = None
            save({"enabled": False})
            _say(rt, "web.log.busy", port=port_number(values))
            return False
        except (ssl.SSLError, ValueError) as exc:
            # A certificate that will not load is the likely one, and it must not
            # quietly become plain HTTP — the person believes they have TLS.
            _SERVER = None
            save({"enabled": False})
            _say(rt, "web.log.cert_error", error=exc)
            return False
        except Exception as exc:            # noqa: BLE001 — never the window
            _SERVER = None
            save({"enabled": False})
            _say(rt, "web.log.error", error=exc)
            return False
        _SERVER = server
    _say(rt, "web.log.started", port=server.bound_port())
    return True


def restart(rt) -> bool:
    """The port or the token was retyped: let the socket go and bind it again."""
    stop(rt, quiet=True)
    return apply(rt)


def stop(rt=None, *, quiet: bool = False) -> None:
    """Let the port go. Safe to call when nothing was ever started."""
    global _SERVER
    with _LOCK:
        server, _SERVER = _SERVER, None
    if server is None:
        return
    server.stop()
    if not quiet:
        _say(rt, "web.log.stopped")


def follow(workspace) -> None:
    """Re-point the server at a profile that is still open, if its own was closed.

    The server answers for every open profile through the workspace, but it keeps ONE
    runtime as the fallback for a request that names no profile and as the place its own
    commentary is said. That runtime used to be whichever profile switched the server
    on, and closing that profile left the fallback pointing at a session that has shut
    its log, its schedule and its game link down.
    """
    with _LOCK:
        server = _SERVER
    if server is None or workspace is None:
        return
    live = [s for s in getattr(workspace, "sessions", [])]
    if any(getattr(s, "rt", None) is server.rt for s in live):
        return
    current = getattr(workspace, "current", None)
    rt = getattr(current, "rt", None)
    if rt is None:
        return
    server.rt = rt
    server.api.rt = rt
    server.owner = str(getattr(getattr(rt, "profiles", None), "active", "") or "")


# -- what the dialog shows --------------------------------------------------
def scheme() -> str:
    """`https` or `http` — of whoever is SERVING, never of the fields on the dialog.

    An `http://` link to a TLS-only server fails in a way nobody diagnoses on a phone,
    and so does the other way round. With nothing bound at all the saved certificate is
    the best guess there is.
    """
    server = serving()
    if server is not None:
        return server.scheme
    return "https" if settings()["cert"].strip() else "http"


def address() -> str:
    """The link to type into a phone: the machine's address, port and token."""
    server = serving()
    values = settings()
    host = webmod.addresses()[0]
    token = server.token if server is not None else values["token"].strip()
    port = server.bound_port() if server is not None else port_number(values)
    tail = f"/?token={token}" if token else "/"
    return f"{scheme()}://{host}:{port}{tail}"


def _say(rt, key: str, **fmt) -> None:
    """One line in the panel's log — and silence rather than a crash without a runtime."""
    try:
        rt.say(TAG, key, **fmt)
    except Exception:                        # noqa: BLE001 — a log line, never the panel
        pass
