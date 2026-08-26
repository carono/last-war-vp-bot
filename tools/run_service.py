r"""Start the panel's service — from a path, and, when Windows starts it, AS A SERVICE.

    "<pythonw>" "<repo>\tools\run_service.py" --service     what `sc create` registers
    "<python>"  "<repo>\tools\run_service.py"               the same thing in a window

A service is started by the Service Control Manager with the system directory as its
working directory and no `PYTHONPATH` of its own, so `-m panel.service` finds nothing:
the repository is not on `sys.path` and `sc` has nowhere to say that it should be. So
this file puts the repository it lives in on the path and hands over.

WHICH REPOSITORY is the one this file is IN — never a path written down anywhere. The
installer (`service_install.bat`) expands it from its own location at install time, so
the registration names the machine it was made on and the repository names nobody.

## Why `--service` exists, and what it cost to leave it out

**A Windows service is a PROTOCOL, not a process that happens to be started by Windows.**
Within seconds of launching it, the process must connect to the SCM
(`StartServiceCtrlDispatcher`), register a control handler and report `SERVICE_RUNNING`.
A program that merely runs — however correctly — never says a word, and the SCM waits its
full timeout and then declares the start failed. From outside it looks exactly like a hang
on start-up, and the System log says so in two lines:

    7009  Превышение времени ожидания (120000 мс) при ожидании подключения службы …
    7000  Сбой при запуске службы … из-за ошибки

That is what this file did for its first day: registered, started, hung, 1053. The fix is
the dialogue itself, and it is written here in `ctypes` against `advapi32` rather than
with `pywin32` ON PURPOSE — this repository is public and gets installed on other people's
computers (`CLAUDE.md`, «Nothing about one machine is written into the code»). `pywin32`
happens to be installed on the machine this was written on; a service that only starts
where somebody already had it is the same class of mistake as a hard-coded path. Nothing
below imports anything that is not in the standard library.

**The heavy imports happen AFTER the dispatcher connects**, inside `ServiceMain`, for the
same reason: everything before that call is time the SCM spends waiting for a process that
has not introduced itself yet.

## Where it says things

A service has no console, and under `pythonw.exe` it has no stdout worth the name either,
so the log is a FILE whose path is COMPUTED — `LW_SERVICE_LOG`, or `service.log` beside
`service.json` in the repository root. It is deliberately not the panel's log: this
process runs as LocalSystem in session 0 and has no profile, no account and no window,
and a line of its landing in some user's `panel.log` would be a lie about who wrote it.

## Whether LocalSystem can do the job

It can, and the reason is what the service IS: a door and a port. It listens on
`127.0.0.1:9762` for panels that dial OUT to it, serves the web port for people, reads and
writes `service.json` beside this file, and never touches the game, a window, a desktop or
a user's profile. Loopback and a listening socket work in session 0; the repository must
be on a drive LocalSystem can see (a local disk — never a mapped network drive or a
`subst`), which the installer says out loud when a start fails.
"""
from __future__ import annotations

import os
import sys
import time
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

#: The SCM's own states and controls, spelled here so that nothing has to be imported to
#: read this file (`winsvc.h`).
SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_STOPPED, SERVICE_START_PENDING = 1, 2
SERVICE_STOP_PENDING, SERVICE_RUNNING = 3, 4
ACCEPT_STOP, ACCEPT_SHUTDOWN = 0x01, 0x04
CONTROL_STOP, CONTROL_INTERROGATE, CONTROL_SHUTDOWN = 1, 4, 5
NO_ERROR, ERROR_SERVICE_SPECIFIC_ERROR = 0, 1066
#: «You were not started by the SCM» — the one failure that means «run in the foreground».
ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063


def log_path() -> str:
    """The service's own log — asked for, then computed. Never inherited."""
    said = (os.environ.get("LW_SERVICE_LOG") or "").strip()
    return said or os.path.join(REPO, "service.log")


#: A log nobody reads for months should not fill a disk. One roll, at this size.
LOG_MAX_BYTES = 4 * 1024 * 1024


def log(line: str) -> None:
    """One stamped line into the service's log, and never an exception at the caller."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        path = log_path()
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            try:
                os.replace(path, path + ".1")
            except OSError:
                pass
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")
    except OSError:
        pass
    if sys.stdout is not None:                 # a window, when there is one
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass


def _run_as_service() -> int:
    """Speak the SCM's protocol, and run the service between «running» and «stop».

    Returns 1063 when the process was NOT started by the SCM, which is how the caller
    below tells «somebody ran this by hand with `--service`» from a real failure.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class SERVICE_STATUS(ctypes.Structure):
        _fields_ = [("dwServiceType", wintypes.DWORD),
                    ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD),
                    ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD),
                    ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD)]

    SERVICE_MAIN = ctypes.WINFUNCTYPE(None, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.LPWSTR))
    HANDLER_EX = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.LPVOID, wintypes.LPVOID)

    class SERVICE_TABLE_ENTRY(ctypes.Structure):
        _fields_ = [("lpServiceName", wintypes.LPWSTR),
                    ("lpServiceProc", SERVICE_MAIN)]

    advapi32.RegisterServiceCtrlHandlerExW.restype = wintypes.SERVICE_STATUS_HANDLE
    advapi32.RegisterServiceCtrlHandlerExW.argtypes = [wintypes.LPCWSTR, HANDLER_EX,
                                                       wintypes.LPVOID]
    advapi32.SetServiceStatus.argtypes = [wintypes.SERVICE_STATUS_HANDLE,
                                          ctypes.POINTER(SERVICE_STATUS)]

    import threading
    state = {"handle": None, "checkpoint": 0, "service": None}
    stopping = threading.Event()

    def report(current: int, *, wait_ms: int = 0, exit_code: int = 0) -> None:
        """Tell the SCM where we are. A pending state must move its checkpoint on."""
        handle = state["handle"]
        if not handle:
            return
        status = SERVICE_STATUS()
        status.dwServiceType = SERVICE_WIN32_OWN_PROCESS
        status.dwCurrentState = current
        status.dwControlsAccepted = (ACCEPT_STOP | ACCEPT_SHUTDOWN
                                     if current == SERVICE_RUNNING else 0)
        status.dwWin32ExitCode = exit_code
        status.dwServiceSpecificExitCode = 0
        if current in (SERVICE_START_PENDING, SERVICE_STOP_PENDING):
            state["checkpoint"] += 1
            status.dwCheckPoint = state["checkpoint"]
        else:
            state["checkpoint"] = 0
            status.dwCheckPoint = 0
        status.dwWaitHint = wait_ms
        advapi32.SetServiceStatus(handle, ctypes.byref(status))

    def handler(control, event_type, event_data, context):   # noqa: ARG001 — SCM's shape
        if control in (CONTROL_STOP, CONTROL_SHUTDOWN):
            log(f"service: control {control} — stopping")
            report(SERVICE_STOP_PENDING, wait_ms=20000)
            stopping.set()
        elif control == CONTROL_INTERROGATE:
            report(SERVICE_RUNNING)
        return NO_ERROR

    def service_main(argc, argv):                            # noqa: ARG001 — SCM's shape
        # The name means nothing to an OWN_PROCESS service, but the handler must be
        # registered before anything else is attempted: from here on a failure can be
        # REPORTED, and before it there is nothing to report to.
        name = (os.environ.get("LW_SERVICE_NAME") or "LastWarBot").strip()
        state["handle"] = advapi32.RegisterServiceCtrlHandlerExW(name, c_handler, None)
        if not state["handle"]:
            log(f"service: RegisterServiceCtrlHandlerExW failed "
                f"({ctypes.get_last_error()})")
            return
        report(SERVICE_START_PENDING, wait_ms=30000)
        try:
            # AFTER the dispatcher connected, never before: an import that takes seconds
            # is seconds the SCM spends waiting for a process that has not spoken yet.
            from panel.service.host import Service, load_config

            report(SERVICE_START_PENDING, wait_ms=30000)
            service = Service(load_config(), log=log)
            service.start()
            state["service"] = service
        except BaseException:                    # noqa: BLE001 — the log is the only witness
            log("service: could not start\n" + traceback.format_exc())
            report(SERVICE_STOPPED, exit_code=ERROR_SERVICE_SPECIFIC_ERROR)
            return
        report(SERVICE_RUNNING)
        log("service: running")
        stopping.wait()
        try:
            service.stop()
        except BaseException:                    # noqa: BLE001 — going away anyway
            log("service: stop raised\n" + traceback.format_exc())
        log("service: stopped")
        report(SERVICE_STOPPED)

    # KEPT ALIVE ON PURPOSE. A callback the garbage collector takes back is a crash the
    # moment Windows calls it, and both of these are held only by C from here on.
    c_handler = HANDLER_EX(handler)
    c_main = SERVICE_MAIN(service_main)
    table = (SERVICE_TABLE_ENTRY * 2)()
    table[0].lpServiceName = "LastWarPanelService"
    table[0].lpServiceProc = c_main
    table[1].lpServiceName = None
    table[1].lpServiceProc = ctypes.cast(None, SERVICE_MAIN)

    if not advapi32.StartServiceCtrlDispatcherW(table):
        return ctypes.get_last_error()
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--service" in argv:
        argv.remove("--service")
        try:
            code = _run_as_service()
        except BaseException:                    # noqa: BLE001 — nobody else will see it
            log("service: the dispatcher itself failed\n" + traceback.format_exc())
            return 1
        if code == ERROR_FAILED_SERVICE_CONTROLLER_CONNECT:
            # Run by hand with `--service`. Say what happened rather than exiting mute,
            # then do the useful thing instead of nothing.
            log("service: not started by Windows — running in the foreground instead")
        elif code:
            log(f"service: StartServiceCtrlDispatcher failed ({code})")
            return 1
        else:
            return 0

    from panel.service.host import main as host_main       # noqa: PLC0415 — foreground only
    return host_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
