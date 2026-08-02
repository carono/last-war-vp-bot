"""Is the client running, and what is it talking to?

A `psutil` probe, no Tk and no game link — the panel's status strip asks it, and so does
the ghost-recon watcher before it spends a robbery on a client that is not there. It was
`panel/__main__.py`'s `game_status`; a tab launched on its own cannot import that file
(``python -m panel`` runs it AS ``__main__``), which is the whole reason this package
exists.

**Which client, though.** A second account runs in its own Windows session
(tools/rdp_instance.py), and by process name alone the two are indistinguishable: the
panel driving the second one over `daemon_port` would report the FIRST one's client as
"running" and never notice its own being gone. So a profile may name the session its
client lives in — the login of the user logged on to it — and every probe below then
counts only the clients inside that session.
"""
from __future__ import annotations

#: The default client executable. A profile may name another one — a second client in
#: its own Windows session, or an install somewhere else — so every caller passes it.
GAME_EXE = "LastWar.exe"

_NON_GAME_PORTS = frozenset({80, 443})


# -- which Windows session ---------------------------------------------------

def profile_user(settings) -> str | None:
    """The login of the session this profile's client lives in, or ``None`` for ours.

    The pair of knobs is read in exactly one place: the login means nothing while
    «игра в RDP-сессии» is off, and a caller that reads only one of the two would
    aim the probe at the wrong session the moment the tick is taken off.
    """
    try:
        if not settings.opt_bool("rdp_session"):
            return None
        return settings.opt_str("rdp_user").strip() or None
    except Exception:                    # noqa: BLE001 — a half-typed knob, not a crash
        return None


def session_of(user: str) -> int | None:
    """The Windows session ``user`` is logged on to, or ``None``.

    ``None`` covers both "nobody by that name is logged on" and "this machine cannot
    be asked" (no pywin32, not Windows). Neither is the same as "the game is not
    running", which is why the callers say so in their own words rather than folding
    it into a plain "not found".
    """
    try:
        import win32ts
        for sess in win32ts.WTSEnumerateSessions():
            sid = sess["SessionId"]
            try:
                who = win32ts.WTSQuerySessionInformation(0, sid, win32ts.WTSUserName)
            except Exception:            # noqa: BLE001 — access denied on a foreign one
                continue
            if (who or "").strip().lower() == user.strip().lower():
                return int(sid)
    except Exception:                    # noqa: BLE001
        return None
    return None


def _pids_by_name(game_exe: str) -> list[int]:
    """Every process called ``game_exe``, whatever session it sits in."""
    import psutil
    return [p.info["pid"] for p in psutil.process_iter(["pid", "name"])
            if (p.info["name"] or "").lower() == game_exe.lower()]


def _pids_in_session(game_exe: str, session: int) -> list[int]:
    """The clients inside one Windows session.

    Through `WTSEnumerateProcesses`, not `ProcessIdToSessionId`: the latter needs query
    rights on the process, so another user's client comes back as "session 0" — which
    reads as a service and is exactly the process being looked for. tools/rdp_instance.py
    learned the same thing the same way.
    """
    import win32ts
    return [int(pid) for sid, pid, name, _sid in win32ts.WTSEnumerateProcesses(0, 1, 0)
            if int(sid) == session and (name or "").lower() == game_exe.lower()]


def pids(game_exe: str = GAME_EXE, user: str | None = None) -> list[int]:
    """The client's PIDs — all of them, or only those in ``user``'s session.

    Raises ``LookupError`` when a session was asked for and could not be resolved: an
    unanswerable question must not come back as an empty list, which reads as "the game
    is not running" and would have the watchdog relaunch a client that is alive.
    """
    if not user:
        return _pids_by_name(game_exe)
    session = session_of(user)
    if session is None:
        raise LookupError(f"no session for {user}")
    return _pids_in_session(game_exe, session)


def _endpoint(found) -> str | None:
    """The first game-server TCP endpoint among ``found``, if one is established."""
    import psutil
    known = set(found)
    for c in psutil.net_connections(kind="tcp"):
        if (c.pid in known and c.raddr and c.status == "ESTABLISHED"
                and c.raddr.port not in _NON_GAME_PORTS):
            return f"{c.raddr.ip}:{c.raddr.port}"
    return None


def server_connection(game_exe: str = GAME_EXE, user: str | None = None) -> str | None:
    """The game-server TCP endpoint, if a connection is currently ESTABLISHED.

    Purely supplementary detail. Its absence (VPN off, mid-reconnect, or the OS
    withholding foreign-owned sockets) must NOT be read as "game not running" —
    that is decided by :func:`status` from the process list alone. A client in
    another user's session is exactly that withheld case: the sockets come back
    without a pid, so the endpoint is simply not shown for it.

    The remote port is not stable across builds (:17935 historically, :10012 on
    the current client), so the check is port-agnostic: find the client's PIDs,
    then return the first ESTABLISHED remote address that is not a web port.
    """
    try:
        found = pids(game_exe, user)
        return _endpoint(found) if found else None
    except Exception:                    # noqa: BLE001 — supplementary, never fatal
        return None


def status(game_exe: str = GAME_EXE, user: str | None = None) -> tuple[bool, str]:
    """Whether the game is running, detected by process name (and session) only.

    Detection is deliberately independent of network state: the game is "found"
    whenever its process exists, regardless of VPN presence or whether a TCP
    connection to the game server is currently established. The connection state,
    when available, is appended as supplementary detail.

    ``game_exe`` is a parameter because the executable is a profile setting (an
    install somewhere else); ``user`` is one because the session is
    (tools/rdp_instance.py). The defaults keep every existing caller — and the
    tests — unchanged: no user named means "whichever client is on this machine".

    Returns ``(running, label)``.
    """
    try:
        import psutil  # noqa: F401 — every route below needs it
    except Exception:
        return False, "psutil missing"

    try:
        found = pids(game_exe, user)
    except LookupError as exc:
        # Not "no game": nobody is logged on to that session, so there is nowhere to
        # look. Saying it plainly is what stops the watchdog from starting a client
        # here instead (see `_watchdog_check`).
        return False, str(exc)
    except Exception as exc:
        return False, f"probe error: {exc}"

    if not found:
        return False, f"game not found ({user})" if user else "game not found"

    pid = found[0]
    where = f" in {user}'s session" if user else ""
    conn = _endpoint(found)
    if conn:
        return True, f"running (pid {pid}){where} -> {conn}"
    return True, f"running (pid {pid}){where}"


def profile_status(settings) -> tuple[bool, str]:
    """:func:`status` for the profile ``settings`` describes — its exe, its session.

    The one call a caller wants: the three knobs that decide *which* client is this
    profile's are read together, so no caller can honour the executable and forget
    the session.
    """
    return status(settings.opt_str("game_exe"), user=profile_user(settings))
