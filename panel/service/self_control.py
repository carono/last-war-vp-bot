r"""The SERVICE's own life — putting it back on the code that is now on disk (#1994).

`panel/runtime/panel_control.py` is this for the panel, and the reason it exists applies
here word for word: a running process holds the code it imported, so a committed fix
reaches it through a fresh interpreter and through nothing else. The panel has had a press
for that since #1258. The service had none — and it is the process that answers the door,
holds the register and owns the panels.

WHAT THAT COST, the day this was written. The panel-side half of #1994 was delivered and
proved in one restart. The service-side half — the register saying which CODE each panel
is running, and the press that names ONE panel — could not be delivered at all: the
service was started by Windows hours earlier, `sc stop` needs rights an ordinary session
does not have, and there was no way in from the door it was itself serving. The same
sentence the panel's own press was written under: a knob nobody can reach is worse than
one somebody can get wrong.

WHY IT ASKS WINDOWS RATHER THAN EXITING. A service that ends itself is a service that is
gone: `sc failure` restarts one that DIED, and a clean stop is not a death. So the press
spawns a detached restarter that outlives the process and asks the SCM to do it properly
— stop, wait for stopped, start. The service runs as LocalSystem, which is exactly the
account that may.

WHAT IT REFUSES. A service running in the FOREGROUND (`service.bat`, a test, somebody
watching it) is not registered with the SCM under this name, and «restart» there would
stop a service that is not running and start a second copy of one that is. It is answered
`unavailable`, the same word the panel's press uses for a process that is not a panel.
"""
from __future__ import annotations

import os
import subprocess

#: The name the installer registers, asked for rather than written down — a machine that
#: registered it under another name sets the variable, exactly as everywhere else
#: (`CLAUDE.md`, «Nothing about one machine is written into the code»). The same chain
#: `service_install.bat` and `tools/run_service.py` already use.
DEFAULT_NAME = "LastWarBot"

#: The id the press travels under, like the panel's two.
RESTART = "restart"


def service_name() -> str:
    return (os.environ.get("LW_SERVICE_NAME") or "").strip() or DEFAULT_NAME


def is_windows() -> bool:
    return os.name == "nt"


def registered(name: str = "", run=None) -> bool:
    """Does the SCM know a service by this name on this machine?

    Asked of Windows rather than assumed from «we are in session 0»: a service run in the
    foreground for a person to watch is in a session too, and a machine that never ran
    `service_install.bat` has nothing to restart.
    """
    if not is_windows():
        return False
    runner = run or _run
    try:
        return runner(["sc", "query", name or service_name()]) == 0
    except Exception:                         # noqa: BLE001 — a reading, never the door
        return False


def _run(cmd: list) -> int:
    return subprocess.run(cmd, capture_output=True, timeout=15).returncode


def _spawn(cmd: list) -> None:
    """Start the restarter and let go of it: it has to outlive this process."""
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.Popen(cmd, close_fds=True, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def restarter_command(name: str = "") -> list:
    """The one place the restart is spelled.

    `Restart-Service` rather than two `sc` calls: `sc stop` returns the moment Windows has
    ACCEPTED the stop, so a `sc start` on the next line races it and fails with «the
    service is stopping». PowerShell waits, and it is on every Windows this runs on.
    """
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command",
            f"Restart-Service -Name '{name or service_name()}' -Force"]


def state() -> dict:
    """What the door says about this press — the same shape the panel's controls use."""
    name = service_name()
    return {"name": name, "available": registered(name),
            "controls": [{"id": RESTART, "label": "service.restart",
                          "confirm": "service.restart.confirm", "enabled": True}]
            if registered(name) else []}


def restart(*, log=None, spawn=None, name: str = "") -> dict:
    """Ask Windows to stop this service and start it again. Never kills anything.

    Comes back in the front-ends' shared vocabulary: ``ok`` it is happening,
    ``unavailable`` this process is not a registered service and there is nothing for the
    SCM to restart.
    """
    say = log or (lambda line: None)
    wanted = name or service_name()
    if not registered(wanted):
        return {"ok": False, "unavailable": True, "name": wanted}
    # SAID BEFORE IT HAPPENS, because in a moment there is nothing left to say it with.
    say(f"service: restarting «{wanted}» — asking Windows to stop and start it")
    try:
        (spawn or _spawn)(restarter_command(wanted))
    except Exception as exc:                  # noqa: BLE001 — the door stays up
        say(f"service: could not ask for a restart: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": "failed", "detail": str(exc)}
    return {"ok": True, "id": RESTART, "name": wanted}
