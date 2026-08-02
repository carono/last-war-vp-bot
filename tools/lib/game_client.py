r"""Which game client this profile drives, and how to close it.

Everything else in the bot only ever needs the client to be *up*. A restart needs the
opposite half: which process to end, and whether it really went away. That is not the
same question as "is a LastWar.exe running", and answering it by process name is how a
two-account box loses the wrong client — one Windows session per client
(docs/research/multi-instance-rdp.md), and `taskkill /IM LastWar.exe` ends both.

So the target is resolved from the narrowest evidence first:

  1. **The daemon's own attachment.** One daemon per client, one port per daemon, and
     the port is this profile's setting — so the process `tools/lua_daemon.py` is
     hijacking on that port IS the client this profile drives. Nothing else on the
     machine can be confused for it.
  2. ``LW_GAME_PID`` — the same override every tool honours.
  3. The client in the caller's own Windows session (`il2cpp_probe.find_game_pid`),
     falling back to any client at all, which is the single-instance case unchanged.

Dependency-light on purpose: `lua_client` (sockets and JSON) always, `psutil` and the
il2cpp probe only when a call actually needs them, so importing this from a test on
Linux costs nothing and fails nowhere.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lua_client  # noqa: E402

#: The client executable. A profile may name another one (an install somewhere else),
#: which is why the process-name fallbacks take it as a parameter.
GAME_EXE = "LastWar.exe"

#: How long a closed client is given to actually disappear. TerminateProcess is not
#: instant — the Unity process unwinds its own handles first — and starting the
#: launcher over a client that is still exiting is how a relaunch ends up with no
#: window at all.
CLOSE_TIMEOUT_SEC = 30.0

# Windows: no console window for the taskkill fallback.
_NO_WINDOW = 0x08000000


def attached_pid(port: "int | None" = None) -> "int | None":
    """The client the warm daemon on ``port`` is attached to, or ``None``.

    ``None`` means "nothing warm there to ask" — a daemon that is down, one that never
    resolved a client, or a version too old to answer. Every one of those is a reason
    to fall back rather than to guess.
    """
    port = int(port if port is not None else lua_client.PORT)
    if not lua_client.is_running(port=port):
        return None
    # An unleased client: asking what a daemon is attached to must never be refused
    # because somebody else is holding the game, nor renew a lease of our own.
    return lua_client.DaemonClient(port=port, token="").target_pid()


def running_pid(game_exe: str = GAME_EXE) -> "int | None":
    """The client process to drive right now, by the ordinary rules.

    ``LW_GAME_PID`` first, then the client in this Windows session, then any client.
    That is `il2cpp_probe.find_game_pid`, which is what a fresh `LuaEval` would pick —
    so a restart waits for exactly the process the next action will attach to.
    """
    try:
        import il2cpp_probe
    except Exception:                        # noqa: BLE001 — not on Windows, no probe
        return _first_pid_by_name(game_exe)
    try:
        return int(il2cpp_probe.find_game_pid())
    except BaseException:                    # noqa: BLE001 — SystemExit("not running")
        return None


def target_pid(port: "int | None" = None, game_exe: str = GAME_EXE) -> "int | None":
    """The client this profile drives: the daemon's, or the ordinary reading."""
    return attached_pid(port) or running_pid(game_exe)


def alive(pid: "int | None") -> bool:
    """Is that pid still a running process?"""
    if not pid:
        return False
    try:
        import psutil
    except Exception:                        # noqa: BLE001
        return True                          # cannot tell — assume it is still there
    try:
        proc = psutil.Process(int(pid))
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except Exception:                        # noqa: BLE001 — gone, or not ours to see
        return False


def close(pid: int, timeout: float = CLOSE_TIMEOUT_SEC) -> bool:
    """End the client at ``pid`` and wait for it to go. ``True`` once it has.

    Force, not a polite close: the point of a scheduled restart is to end a client
    that may well be wedged behind a modal, and a WM_CLOSE it is not answering would
    turn the errand into a five-minute wait for nothing.
    """
    pid = int(pid)
    try:
        import psutil
    except Exception:                        # noqa: BLE001 — Windows without psutil
        return _taskkill(pid, timeout)
    try:
        proc = psutil.Process(pid)
    except Exception:                        # noqa: BLE001 — already gone
        return True
    try:
        proc.kill()
    except Exception:                        # noqa: BLE001 — gone between the two lines
        pass
    try:
        proc.wait(timeout=timeout)
    except Exception:                        # noqa: BLE001 — psutil.TimeoutExpired
        return not alive(pid)
    return True


def wait_gone(pid: "int | None", timeout: float = CLOSE_TIMEOUT_SEC) -> bool:
    """Wait until ``pid`` is not running any more. ``True`` if it went."""
    deadline = time.time() + float(timeout)
    while alive(pid):
        if time.time() >= deadline:
            return False
        time.sleep(0.5)
    return True


# -- fallbacks ---------------------------------------------------------------

def _first_pid_by_name(game_exe: str) -> "int | None":
    try:
        import psutil
    except Exception:                        # noqa: BLE001
        return None
    try:
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() == game_exe.lower():
                return proc.pid
    except Exception:                        # noqa: BLE001
        return None
    return None


def _taskkill(pid: int, timeout: float) -> bool:
    """Windows without psutil: end one PID (never an image name — see the header)."""
    if sys.platform != "win32":
        return False
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, creationflags=_NO_WINDOW, timeout=timeout)
    except Exception:                        # noqa: BLE001
        return False
    return True
