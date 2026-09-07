"""The service is the ROOT OF THE PROCESS TREE: stopping it takes everything with it.

    «Питоновские проекты нужно спавнить от службы, чтобы когда я отключаю службу,
      все дочерние скрипты умирали, а не висели в системе»   — the person, #2613

## What was wrong

The service asks its panels to quit and then *leaves alone* whatever is still up
(`panel/service/keeper.py::stop` — «NOT KILLED, on purpose»), which is right: a panel
writing a profile out must not be shot. But the panel is a tree, not a process — the
captures, the sniffers, the robbery tools, the Lua connector — and everything below a
panel that did not manage to go outlived the service that started it. The machine then
had python processes belonging to a service that is stopped, farming with budgets nobody
was counting, holding the game and the web port a restarted service needs.

## What it is now

**A job object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, held by the service process.**
On Windows a process created by a member of a job joins that job, and so does everything
IT creates, however it was started — `subprocess.Popen`, detached, windowless, any of it.
When the last handle to the job closes — which is when the service process ends, for any
reason, including being killed — the kernel terminates every member.

**Except across a session boundary, and that is not a choice (#2616).** A job holds
processes of ONE session, so a panel started into a signed-in session with
`CreateProcessAsUserW` (`panel/service/session.py`) cannot join a job made in session 0:
the implicit join is refused and the CALL ITSELF fails with 5 (`ERROR_ACCESS_DENIED`) —
which is what it did, live, the first time this shipped: «keeper: could not start a panel:
CreateProcessAsUserW 5», repeated, no panel at all. That launch therefore asks for
`CREATE_BREAKAWAY_FROM_JOB` and the panel stays outside the job, exactly as the keeper's
polite stop already assumed. What the job still holds is everything the SERVICE itself
spawns in session 0.

So this is a FLOOR, not a replacement for the orderly shutdown. The order stays exactly
what it was: the SCM's stop reaches `Service.stop`, the keeper asks each panel to quit
through its own socket and waits, and only what is still alive after all that meets the
job. Nothing is killed while anything is still being asked politely.

## Why the job also allows BREAKAWAY

`JOB_OBJECT_LIMIT_BREAKAWAY_OK`, and it is the whole of «do not break the restarts»:
`panel/service/self_control.py` restarts the SERVICE by spawning a PowerShell that runs
`Restart-Service`, and that child must outlive the process that asked — a restarter
inside a kill-on-close job dies the instant the SCM stops the service, i.e. exactly when
it is needed. It already asks for `CREATE_BREAKAWAY_FROM_JOB` and falls back without it;
this flag is what makes the ask succeed.

The PANEL'S own restart (`POST /api/panel`, `panel/runtime/panel_control.py`) asks for
nothing of the sort, so the replacement panel is spawned INSIDE the job and is supervised
and reaped exactly like the panel it replaced. That is what «a panel restarted normally
must not be killed along the way» means here: the job only ever fires when the SERVICE
goes, and a panel restart does not touch the service.

## What it deliberately does not reach

A panel a person started themselves (`panel.bat`) is not a child of the service and never
joins its job — the keeper already leaves such a window alone, and the same holds here.
This kills OUR tree, never a stranger's process.

## Elsewhere

Nothing here is Windows-only in the caller's eyes: on any other platform, and on a
Windows that refuses the job, :func:`hold` returns a report saying so and the service runs
exactly as it did before.
"""
from __future__ import annotations

import os
import sys

#: `winnt.h`. Kill every process in the job when the last handle to it closes.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
#: …and let a child that asks for it leave the job (the service's own restarter).
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
#: `JobObjectExtendedLimitInformation` — the class the two limits above are set through.
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

#: «Do not hold the tree» — for a machine that wants the old behaviour back without a
#: code change, exactly as every other machine-specific answer in this repository is
#: asked for rather than written down (`CLAUDE.md`).
ENV_OFF = "LW_SERVICE_NO_JOB"

#: THE HANDLE IS HELD FOR THE LIFE OF THE PROCESS, and that is the mechanism rather than
#: an implementation detail: the kernel fires the kill when the LAST handle closes, so a
#: handle the garbage collector took back would be a tree that dies while the service is
#: still running.
_HELD = []


def wanted() -> bool:
    """Whether this machine wants the tree held. `LW_SERVICE_NO_JOB=1` says no."""
    said = (os.environ.get(ENV_OFF) or "").strip().lower()
    return said not in ("1", "yes", "true", "on")


def held() -> bool:
    """Is the job already up? A second :func:`hold` is a no-op, not a second job."""
    return bool(_HELD)


def hold(log=None) -> dict:
    """Put THIS process in a kill-on-close job, so its whole tree dies with it.

    Returns what happened — `{"ok": bool, "why": str}` — and never raises: a service that
    could not make a job is a service that runs, minus the floor under it.
    """
    say = log or (lambda line: None)
    if held():
        return {"ok": True, "why": "already"}
    if not wanted():
        say(f"service: the process tree is NOT held ({ENV_OFF} is set) — children will "
            f"outlive this service")
        return {"ok": False, "why": "disabled"}
    if not sys.platform.startswith("win"):
        return {"ok": False, "why": "not_windows"}
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("BasicLimitInformation",
                         JOBOBJECT_BASIC_LIMIT_INFORMATION),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        # THE RETURN TYPES ARE NOT A FORMALITY. `ctypes` defaults to a 32-bit `int`, so a
        # 64-bit handle comes back truncated and `AssignProcessToJobObject` answers 6
        # (`ERROR_INVALID_HANDLE`) — a job made, joined by nobody, and a tree still loose.
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            code = ctypes.get_last_error()
            say(f"service: CreateJobObject failed ({code}) — the tree is not held")
            return {"ok": False, "why": "create_failed", "detail": str(code)}

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                                                 | JOB_OBJECT_LIMIT_BREAKAWAY_OK)
        if not kernel32.SetInformationJobObject(
                job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info)):
            code = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            say(f"service: SetInformationJobObject failed ({code}) — the tree is not held")
            return {"ok": False, "why": "limits_failed", "detail": str(code)}

        if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
            code = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            # 5 is ACCESS_DENIED, which on a Windows older than 8 means «this process is
            # already in somebody else's job and jobs do not nest». Said plainly rather
            # than as a failure: the service works, it just has no floor under it.
            say(f"service: this process could not join a job of its own ({code}) — "
                f"children will outlive the service")
            return {"ok": False, "why": "assign_failed", "detail": str(code)}

        _HELD.append(job)
        say("service: the process tree is held — everything this service starts dies "
            "with it")
        return {"ok": True, "why": "held"}
    except Exception as exc:                  # noqa: BLE001 — a floor, never a failure
        say(f"service: could not hold the process tree ({type(exc).__name__}: {exc})")
        return {"ok": False, "why": "error", "detail": str(exc)}
