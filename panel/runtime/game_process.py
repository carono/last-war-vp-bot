"""Is the client running, and what is it talking to?

A `psutil` probe, no Tk and no game link — the panel's status strip asks it, and so does
the ghost-recon watcher before it spends a robbery on a client that is not there. It was
`panel/__main__.py`'s `game_status`; a tab launched on its own cannot import that file
(``python -m panel`` runs it AS ``__main__``), which is the whole reason this package
exists.
"""
from __future__ import annotations

#: The default client executable. A profile may name another one — a second client in
#: its own Windows session, or an install somewhere else — so every caller passes it.
GAME_EXE = "LastWar.exe"

_NON_GAME_PORTS = frozenset({80, 443})


def server_connection(game_exe: str = GAME_EXE) -> str | None:
    """The game-server TCP endpoint, if a connection is currently ESTABLISHED.

    Purely supplementary detail. Its absence (VPN off, mid-reconnect, or the OS
    withholding foreign-owned sockets) must NOT be read as "game not running" —
    that is decided by :func:`status` from the process list alone.

    The remote port is not stable across builds (:17935 historically, :10012 on
    the current client), so the check is port-agnostic: find lastwar.exe's PIDs,
    then return the first ESTABLISHED remote address that is not a web port.
    """
    try:
        import psutil
        pids = {p.info["pid"] for p in psutil.process_iter(["pid", "name"])
                if (p.info["name"] or "").lower() == game_exe.lower()}
        if not pids:
            return None
        for c in psutil.net_connections(kind="tcp"):
            if (c.pid in pids and c.raddr and c.status == "ESTABLISHED"
                    and c.raddr.port not in _NON_GAME_PORTS):
                return f"{c.raddr.ip}:{c.raddr.port}"
    except Exception:
        return None
    return None


def status(game_exe: str = GAME_EXE) -> tuple[bool, str]:
    """Whether the game is running, detected by process name only.

    Detection is deliberately independent of network state: the game is "found"
    whenever its process exists, regardless of VPN presence or whether a TCP
    connection to the game server is currently established. The connection state,
    when available, is appended as supplementary detail.

    ``game_exe`` is a parameter because the executable is a profile setting (a
    second client in its own Windows session, an install somewhere else); the
    default keeps every existing caller — and the tests — unchanged.

    Returns ``(running, label)``.
    """
    try:
        import psutil
    except Exception:
        return False, "psutil missing"

    pid = None
    try:
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() == game_exe.lower():
                pid = proc.pid
                break
    except Exception as exc:
        return False, f"probe error: {exc}"

    if pid is None:
        return False, "game not found"

    conn = server_connection(game_exe)
    if conn:
        return True, f"running (pid {pid}) -> {conn}"
    return True, f"running (pid {pid})"
