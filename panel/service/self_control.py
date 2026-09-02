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

WHY IT NOW SAYS WHAT CAME OF IT (#2069). The press answered `ok` and nothing happened:
the detached restarter's output went to `DEVNULL`, so «powershell is not on LocalSystem's
PATH», «the child died with the stopping service» and «it worked» were the same three
sentences of log — a line saying the ask went out, and a two-day-old service pid under it.
`ok` still means «the ask went out» and cannot mean more, so the DIFFERENCE was made
visible instead: the restarter writes its own verdict into `service_restart.log` (which
pid before, which after, or why the SCM refused), and this process arms a watcher that can
only fire if it was never stopped — the honest «did not». It is the rule «Лог-строка ≠
действие» applied to the one press nobody can check by hand, `Restart-Service` from an
ordinary session having no rights.

WHAT IT REFUSES. A service running in the FOREGROUND (`service.bat`, a test, somebody
watching it) is not registered with the SCM under this name, and «restart» there would
stop a service that is not running and start a second copy of one that is. It is answered
`unavailable`, the same word the panel's press uses for a process that is not a panel.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

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


#: The service's own log, and the restarter's beside it. Computed the same way
#: `tools/run_service.py` computes the first, and never written down: a machine that put
#: the log somewhere else says so once, in the variable it already sets.
def log_dir() -> str:
    said = (os.environ.get("LW_SERVICE_LOG") or "").strip()
    if said:
        return os.path.dirname(os.path.abspath(said)) or os.getcwd()
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def restart_log_path() -> str:
    """Where the restarter says what happened to it.

    IT HAS TO BE A FILE OF ITS OWN, and that is the whole of #2069. The restarter's output
    went to `DEVNULL`, so a press that changed nothing looked exactly like a press that
    worked: `{"ok": true}` at the door, one line in `service.log` saying the ask went out,
    and a two-day-old service pid underneath it. Whatever silences it — no `powershell` on
    LocalSystem's `PATH`, a child that died with the stopping service, a stop that hung on
    the handler — is a sentence in here now instead of nothing at all.
    """
    said = (os.environ.get("LW_SERVICE_RESTART_LOG") or "").strip()
    return said or os.path.join(log_dir(), "service_restart.log")


def powershell_path() -> str:
    """PowerShell by full path, falling back to the name.

    A service runs as LocalSystem with the SCM's environment, not a person's, and its
    working directory is the system one. `PATH` is usually enough and is not promised, so
    the interpreter is looked for where Windows keeps it — computed from `SystemRoot`,
    never spelled out for one machine (`CLAUDE.md`).
    """
    root = (os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or "").strip()
    if root:
        full = os.path.join(root, "System32", "WindowsPowerShell", "v1.0",
                            "powershell.exe")
        if os.path.exists(full):
            return full
    return "powershell"


#: How long the restarter waits for the SCM to bring the service back before it says it
#: did not, and how long THIS process waits before saying the same thing from its side.
RESTART_WAIT_SEC = 30
VERDICT_AFTER_SEC = 40


def _script(name: str) -> str:
    """What the restarter does, in one string — and it VERIFIES rather than assuming.

    `Restart-Service` returning is not evidence: the pid is read before the ask and read
    again after it, and the line that lands says which of the two happened. A restart that
    worked has stopped the asking process long before the loop ends, so the «did NOT» line
    only ever gets written when it is true.

    An ask that Windows REFUSES — no such service, no rights — is said and left there:
    waiting out the loop for a stop that was never accepted would put half a minute
    between the press and the reason for it, and the reason is already in hand.

    IT WRITES TO ITS OWN STDOUT, never to the log by name. The two are the same file, and
    a script that opened it a second time got a sharing violation against the handle it
    had been given — silently, because `Out-File` failing inside `try { } catch { }` looks
    exactly like a script that never ran. Everything it says goes out the handle Python
    already opened for it.

    NOT ONE DOUBLE QUOTE IN IT, and that is not tidiness. The script travels as a single
    `-Command` argument, so Windows re-splits it out of one string: every `"` on the way
    has to survive `list2cmdline`, PowerShell's own parser and whatever the SCM's
    environment does in between, and one that does not turns the whole restart into
    silence. `-f` formatting and `Where-Object` say the same things with `'` alone. ASCII
    only in what IT writes, for the same reason — though what Windows hands back may be in
    any language, so the output encoding is set to UTF-8 before a word is said.
    """
    quoted = name.replace("'", "''")
    return (
        "$ErrorActionPreference = 'Continue'; "
        "try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }; "
        f"$name = '{quoted}'; "
        "function Say($m) { ('{0} restarter: {1}' -f "
        "(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) | Write-Output }; "
        "function Svc { Get-CimInstance Win32_Service | "
        "Where-Object { $_.Name -eq $name } | Select-Object -First 1 }; "
        "$was = (Svc).ProcessId; "
        "Say ('asking Windows to restart {0} (pid {1})' -f $name, $was); "
        "try { Restart-Service -Name $name -Force -ErrorAction Stop } "
        "catch { Say ('Restart-Service failed: {0}' -f $_.Exception.Message); "
        "exit 2 }; "
        f"for ($i = 0; $i -lt {RESTART_WAIT_SEC}; $i++) {{ Start-Sleep -Seconds 1; "
        "$now = Svc; "
        "if ($now.State -eq 'Running' -and $now.ProcessId -ne $was) { "
        "Say ('restarted - pid {0} -> {1}' -f $was, $now.ProcessId); exit 0 } }; "
        "$now = Svc; "
        "Say ('did NOT restart - state {0}, pid {1} (was {2})' -f "
        "$now.State, $now.ProcessId, $was); exit 1"
    )


def restarter_command(name: str = "") -> list:
    """The one place the restart is spelled.

    `Restart-Service` rather than two `sc` calls: `sc stop` returns the moment Windows has
    ACCEPTED the stop, so a `sc start` on the next line races it and fails with «the
    service is stopping». PowerShell waits, and it is on every Windows this runs on.
    """
    return [powershell_path(), "-NoProfile", "-NonInteractive", "-Command",
            _script(name or service_name())]


#: «Break away from the job this process is in» (`winbase.h`). Not in `subprocess`, and
#: the reason it is here: a detached child is still a member of its parent's job object,
#: and a job that kills on close takes the restarter down the instant the SCM stops the
#: service — which is the second the restarter is needed most. Asking to leave the job
#: fails with «access denied» where the job forbids it, so it is TRIED and then dropped.
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def _spawn(cmd: list):
    """Start the restarter and let go of it: it has to outlive this process.

    NO `DETACHED_PROCESS`, AND IT IS THE WHOLE BUG (#2069). Measured, one flag at a time,
    against a service name Windows does not have: with the flag the restarter exits **0**
    having done nothing at all — no `Restart-Service`, no line, no error — and without it
    the same command line runs and reports. It was there to make the child outlive this
    process, and it is not what does that: on Windows nothing kills a child when its
    parent goes: `CREATE_NO_WINDOW` gives it no window to flash and
    `CREATE_NEW_PROCESS_GROUP` keeps this process's Ctrl+C off it, which is all that was
    ever needed. A silent exit 0 is exactly how a press could answer `ok` for two days
    while a two-day-old service pid sat under it.

    THE FILE IS STAMPED BEFORE THE CHILD EXISTS, and that is deliberate. An empty
    `service_restart.log` would leave the same question #2069 started with — did anything
    get spawned at all? — so Python writes the exe and the moment down first, and whatever
    the child says lands under it. A file with only that line is itself an answer: the
    process was created and died without a word.

    The line is ASCII on purpose: what Windows hands back through the child arrives in the
    console's own code page, and a file that is ASCII everywhere else reads correctly
    whatever that page turns out to be.
    """
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        handle = open(restart_log_path(), "a", encoding="utf-8", errors="replace")
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} service: spawning "
                     f"{cmd[0]} (pid {os.getpid()}, user {_whoami()})\n")
        handle.flush()
    except OSError:
        handle = None
    out = handle or subprocess.DEVNULL
    child = None
    try:
        try:
            child = subprocess.Popen(cmd, close_fds=True,
                                     creationflags=flags | CREATE_BREAKAWAY_FROM_JOB,
                                     stdin=subprocess.DEVNULL, stdout=out, stderr=out)
        except OSError:
            # The job forbids leaving it. Better a child that may die with us than none.
            child = subprocess.Popen(cmd, close_fds=True, creationflags=flags,
                                     stdin=subprocess.DEVNULL, stdout=out, stderr=out)
    finally:
        if handle is not None:
            handle.close()
    return child


def _whoami() -> str:
    """Who this process is to Windows — a reading, never a value written down."""
    try:
        return os.environ.get("USERNAME") or ""
    except Exception:                         # noqa: BLE001
        return ""


def _watch(say, wanted: str, delay: float, child=None) -> None:
    """Say so when the restart did not happen — from the side that can only be alive if it
    did not.

    This runs INSIDE the process that asked to be replaced. Reaching the end of the sleep
    means the SCM never stopped it, so there is nothing to weigh up: the press failed, and
    the log says which log to read for the reason. What the restarter did with itself goes
    in the same line when there is anything to say — a child that has already exited names
    its code, which is the difference between «PowerShell refused» and «something took the
    process away».
    """
    def _said() -> None:
        ended = ""
        try:
            code = None if child is None else child.poll()
            if code is not None:
                ended = f"; the restarter exited with code {code}"
        except Exception:                     # noqa: BLE001 — a reading, never the door
            ended = ""
        say(f"service: «{wanted}» was NOT restarted — this process is still running as "
            f"pid {os.getpid()} {int(delay)}s after the ask{ended}; "
            f"see {restart_log_path()}")

    timer = threading.Timer(delay, _said)
    timer.daemon = True
    timer.start()


def state() -> dict:
    """What the door says about this press — the same shape the panel's controls use."""
    name = service_name()
    return {"name": name, "available": registered(name),
            "controls": [{"id": RESTART, "label": "service.restart",
                          "confirm": "service.restart.confirm", "enabled": True}]
            if registered(name) else []}


def restart(*, log=None, spawn=None, name: str = "", watch=None,
            verdict_after: float = VERDICT_AFTER_SEC) -> dict:
    """Ask Windows to stop this service and start it again. Never kills anything.

    Comes back in the front-ends' shared vocabulary: ``ok`` it is happening,
    ``unavailable`` this process is not a registered service and there is nothing for the
    SCM to restart.

    ``ok`` HAS ALWAYS MEANT «THE ASK WENT OUT», never «it happened» — which is the trap
    #2069 fell into, and it is the same one «Лог-строка ≠ действие» names. What is new is
    that the difference becomes visible without anybody going and looking at
    `Win32_Process`: the restarter writes its own verdict into
    `service_restart.log`, and this process writes the opposite verdict from here if it is
    still alive to write anything.
    """
    say = log or (lambda line: None)
    wanted = name or service_name()
    if not registered(wanted):
        return {"ok": False, "unavailable": True, "name": wanted}
    # SAID BEFORE IT HAPPENS, because in a moment there is nothing left to say it with.
    say(f"service: restarting «{wanted}» — asking Windows to stop and start it; "
        f"the restarter says what came of it in {restart_log_path()}")
    try:
        child = (spawn or _spawn)(restarter_command(wanted))
    except Exception as exc:                  # noqa: BLE001 — the door stays up
        say(f"service: could not ask for a restart: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": "failed", "detail": str(exc)}
    (watch or _watch)(say, wanted, verdict_after, child)
    return {"ok": True, "id": RESTART, "name": wanted,
            "log": restart_log_path(), "asked": True}
