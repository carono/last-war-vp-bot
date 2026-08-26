r"""Starting a program in somebody's Windows SESSION, from a service that has none.

The service runs as LocalSystem in session 0: no desktop, no window station, no
foreground, no screen. The panel needs all four the moment it touches the game — the
client's window, the input, the screenshots, the attach — so a panel started IN session 0
would come up, dial in, and then fail at everything it exists for. It has to be started
in the session a person is signed in to, and this file is the only place that knows how.

## The honest limit, said once here so nobody has to discover it

**A service cannot conjure a session.** `WTSQueryUserToken` hands back the token of a
user who is ALREADY SIGNED IN; with nobody signed in there is no token, no desktop and no
GPU surface, and the game client could not run there either. So:

* somebody signed in (or an RDP session left running, `docs/research/multi-instance-rdp.md`)
  → the service starts the panel there itself, and the machine needs no other help;
* nobody signed in → the service says so and keeps looking. It is not a failure of this
  code and there is no flag that fixes it: a game that draws needs a session that draws.
  Windows' own answer is «sign in», or «leave the session logged on and disconnected».

That is the whole of it. Everything else here is the mechanics.

## Two ways out, chosen by where THIS process is

* **Session 0 (a real service).** `WTSQueryUserToken` → `DuplicateTokenEx` →
  `CreateEnvironmentBlock` → `CreateProcessAsUserW` with `lpDesktop = winsta0\default`.
  Needs `SeTcbPrivilege`, which LocalSystem has and an ordinary account does not.
* **An interactive session (`service.bat`, a test, a person watching it).** There is
  nothing to cross: an ordinary `subprocess.Popen` starts the panel in the session this
  process is already in, which is the session the person is looking at.

`ctypes` again rather than `pywin32`, for the reason `tools/run_service.py` gives at
length: this repository is public and a service that only works where somebody already
had a package is a hard-coded path in another costume.
"""
from __future__ import annotations

import os
import subprocess
import sys

#: What `CreateProcessAsUserW` is told to draw on. The interactive window station and its
#: default desktop — the one a signed-in person is looking at.
DESKTOP = r"winsta0\default"

#: Windows' own name for «this process is a service»: session 0 and nothing else.
SERVICE_SESSION = 0


def is_windows() -> bool:
    return os.name == "nt"


def current_session() -> int:
    """Which Windows session THIS process is in. `-1` where the question has no meaning."""
    if not is_windows():
        return -1
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    pid = kernel32.GetCurrentProcessId()
    out = ctypes.c_ulong(0)
    if not kernel32.ProcessIdToSessionId(pid, ctypes.byref(out)):
        return -1
    return int(out.value)


def console_session() -> int:
    """The session at the machine's own screen, or `-1` when nobody is at it."""
    if not is_windows():
        return -1
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    said = int(kernel32.WTSGetActiveConsoleSessionId())
    return -1 if said == 0xFFFFFFFF else said


#: The connection states a panel can be started in (`WTS_CONNECTSTATE_CLASS`). Active is
#: somebody at the screen; Disconnected is an RDP session left logged on — which HAS a
#: desktop and is exactly how a second client runs here
#: (`docs/research/multi-instance-rdp.md`). Everything else is a session being born,
#: dying, or listening.
USABLE_STATES = (0, 4)


def signed_in_sessions() -> list:
    """Every session a panel could be started in, the console one first.

    Told by the session's STATE and not by whether a token can be got for it: asking for
    the token needs `SeTcbPrivilege`, which the service has and a person's own process
    does not — so a privilege failure here would look exactly like «nobody is signed in»
    and send whoever is reading the log after the wrong thing entirely.
    """
    if not is_windows():
        return []
    import ctypes
    from ctypes import wintypes

    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

    class WTS_SESSION_INFOW(ctypes.Structure):
        _fields_ = [("SessionId", wintypes.DWORD),
                    ("pWinStationName", wintypes.LPWSTR),
                    ("State", ctypes.c_int)]

    ptr = ctypes.POINTER(WTS_SESSION_INFOW)()
    count = wintypes.DWORD(0)
    if not wtsapi32.WTSEnumerateSessionsW(None, 0, 1, ctypes.byref(ptr),
                                          ctypes.byref(count)):
        return []
    try:
        found = []
        for i in range(int(count.value)):
            sid = int(ptr[i].SessionId)
            if sid == SERVICE_SESSION or int(ptr[i].State) not in USABLE_STATES:
                continue
            found.append(sid)
    finally:
        wtsapi32.WTSFreeMemory(ptr)
    console = console_session()
    found.sort(key=lambda sid: (sid != console, sid))
    return found


def _close(handle) -> None:
    import ctypes

    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)


def _user_token(session_id: int):
    """The token of whoever is signed in to ``session_id``, or ``None``."""
    import ctypes
    from ctypes import wintypes

    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    token = wintypes.HANDLE()
    if not wtsapi32.WTSQueryUserToken(wintypes.DWORD(session_id), ctypes.byref(token)):
        return None
    return token


def launch(cmd: list, *, cwd: str = "", session_id: int = -1, log=None) -> dict:
    """Start ``cmd``. In a user session when this process has none of its own.

    Returns what happened, in words the caller can log and the tests can read:
    ``{"ok": True, "pid": …, "session": …, "how": "asuser"|"popen"}`` or
    ``{"ok": False, "why": "no_session"|"no_token"|"failed", "detail": …}``.

    Never raises: a supervisor that dies because a launch failed is worse than one that
    keeps trying, and «nobody is signed in» is an ordinary state of a machine, not a bug.
    """
    say = log or (lambda line: None)
    cmd = [str(part) for part in cmd]
    here = current_session()
    if not is_windows() or here != SERVICE_SESSION:
        # An interactive process starting another in its own session: nothing to cross.
        try:
            proc = subprocess.Popen(cmd, cwd=cwd or None, close_fds=True)
        except OSError as exc:
            say(f"keeper: could not start the panel: {exc}")
            return {"ok": False, "why": "failed", "detail": str(exc)}
        return {"ok": True, "pid": proc.pid, "session": here, "how": "popen"}

    wanted = int(session_id) if int(session_id) >= 0 else -1
    sessions = [wanted] if wanted >= 0 else signed_in_sessions()
    if not sessions:
        return {"ok": False, "why": "no_session"}
    last = {"ok": False, "why": "no_token"}
    for sid in sessions:
        said = _launch_as_user(cmd, cwd=cwd, session_id=sid, log=say)
        if said.get("ok") or said.get("why") not in ("no_token",):
            return said
        last = said
    return last if sessions else {"ok": False, "why": "no_session"}


def _launch_as_user(cmd: list, *, cwd: str, session_id: int, log) -> dict:
    """`CreateProcessAsUserW` into ``session_id`` — the session-0 half of :func:`launch`."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)

    TOKEN_DUPLICATE, TOKEN_QUERY, TOKEN_ASSIGN_PRIMARY = 0x0002, 0x0008, 0x0001
    TOKEN_ADJUST_DEFAULT, TOKEN_ADJUST_SESSIONID = 0x0080, 0x0100
    SecurityImpersonation, TokenPrimary = 2, 1
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                    ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                    ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                    ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD),
                    ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
                    ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
                    ("hStdError", wintypes.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    token = _user_token(session_id)
    if token is None:
        # 1314 is `ERROR_PRIVILEGE_NOT_HELD` — «this process is not SYSTEM», which is a
        # different sentence from «nobody is signed in» and must not be said as if it
        # were. 1008 / 5 are the ordinary «that session has no user».
        code = ctypes.get_last_error()
        why = "no_privilege" if code == 1314 else "no_token"
        return {"ok": False, "why": why, "session": session_id, "detail": str(code)}

    primary = wintypes.HANDLE()
    env = ctypes.c_void_p()
    try:
        rights = (TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ASSIGN_PRIMARY
                  | TOKEN_ADJUST_DEFAULT | TOKEN_ADJUST_SESSIONID)
        if not advapi32.DuplicateTokenEx(token, rights, None, SecurityImpersonation,
                                         TokenPrimary, ctypes.byref(primary)):
            return {"ok": False, "why": "failed", "session": session_id,
                    "detail": f"DuplicateTokenEx {ctypes.get_last_error()}"}
        if not userenv.CreateEnvironmentBlock(ctypes.byref(env), primary, False):
            env = ctypes.c_void_p()          # the person's own environment is a nicety

        info = STARTUPINFOW()
        info.cb = ctypes.sizeof(STARTUPINFOW)
        info.lpDesktop = DESKTOP
        out = PROCESS_INFORMATION()
        line = subprocess.list2cmdline(cmd)
        flags = CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW | DETACHED_PROCESS
        ok = advapi32.CreateProcessAsUserW(
            primary, None, ctypes.create_unicode_buffer(line), None, None, False,
            flags, env if env else None, (cwd or None), ctypes.byref(info),
            ctypes.byref(out))
        if not ok:
            return {"ok": False, "why": "failed", "session": session_id,
                    "detail": f"CreateProcessAsUserW {ctypes.get_last_error()}"}
        pid = int(out.dwProcessId)
        _close(out.hProcess)
        _close(out.hThread)
        return {"ok": True, "pid": pid, "session": session_id, "how": "asuser"}
    finally:
        if env:
            userenv.DestroyEnvironmentBlock(env)
        if primary:
            _close(primary)
        _close(token)


def panel_command(profiles=None, *, python: str = "", module: str = "panel.headless",
                  extra=None) -> list:
    """The command line that starts a panel — the ONE place it is spelled.

    `sys.executable` is the interpreter the SERVICE runs under, which is the one the
    installer registered, which is the machine's own answer to «which Python» — asked
    rather than written down (`CLAUDE.md`). Under `pythonw.exe` the panel is windowless
    exactly as the service is, and that is what is wanted: the panel's front-end is the
    web, and a console nobody is looking at is a console nobody closes.
    """
    exe = str(python or sys.executable or "python")
    cmd = [exe, "-m", str(module or "panel.headless")]
    for name in (profiles or []):
        cmd += ["--profile", str(name)]
    cmd += [str(part) for part in (extra or [])]
    return cmd
