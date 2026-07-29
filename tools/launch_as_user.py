r"""Run a process as ANOTHER Windows user, on the CURRENT desktop — no session switch.

Task #1105 — multi-instance. Read this first:

> **The Windows plumbing here works; the game does not run through it.** Any
> ordinary process starts as another user, in this session, drawing on this
> desktop. `LastWar.exe` started the same way is killed by the ACE anti-cheat
> after ~9 s with exit code `0xDEADC0DE` — through every launch route tried,
> alone or beside another client, on this desktop or a private one, and even
> from SYSTEM with a proper primary token. The evidence table and the controls
> are in `docs/research/multi-instance-second-user.md`; running a second client
> still needs a second Windows session. What stays useful is everything else:
> driving *non-game* helpers as another user without leaving this desktop.

Why another Windows user at all
-------------------------------
One Windows user can hold exactly one Last War install and one client profile:
the game lives in ``%LOCALAPPDATA%\FunFly\Last War-Survival Game`` and keeps its
account/state under that same profile. A second account therefore needs a second
Windows user — its own ``%LOCALAPPDATA%``, its own install, its own client data.

The obvious way to get there is a second logon session (a second RDP session, or
fast user switching). That is what this machine did before: session 1 = ``spame``,
session 3 = ``casper``, one client each. It works, but the two clients then live on
*different desktops*, and this bot drives the game with **foreground** input
(``pydirectinput`` — see the input-model note in the repo memory): a window on a
desktop that is not the one attached to the physical console cannot be focused,
clicked or screenshotted from here. Switching sessions to reach it defeats the
point of automating anything.

What this script does instead
-----------------------------
Start the second client **as the other user but inside the current session**, so
its window is an ordinary window on the desktop we already drive:

1. Grant the target user's SID access to the interactive window station
   ``WinSta0`` and the desktop ``Default``. Without this the child process cannot
   open the desktop and dies before it draws anything (or silently renders
   nowhere). These ACEs are volatile — the objects are recreated at every logon,
   so the grant is re-applied on every launch. Undo with ``--revoke``.
2. Launch the game with ``STARTUPINFO.lpDesktop = "WinSta0\Default"`` under a
   token for the other user, via one of two routes:

   * ``--method logon`` (default) — ``CreateProcessWithLogonW`` with
     ``LOGON_WITH_PROFILE``. Needs **no privileges at all**, only the target
     user's password, and it loads that user's profile, so the child sees the
     target's ``%LOCALAPPDATA%``/``%USERPROFILE%`` — exactly what we want. It
     runs the child in the caller's session, which is the whole point.
   * ``--method asuser`` — ``LogonUser`` + ``LoadUserProfile`` +
     ``CreateEnvironmentBlock`` + ``CreateProcessAsUser``. Needs
     ``SeAssignPrimaryTokenPrivilege`` + ``SeIncreaseQuotaPrivilege`` (i.e.
     elevated/SYSTEM), and is the only route when the caller *is* a service,
     where ``CreateProcessWithLogonW`` is forbidden. ``--session`` retargets the
     token at a specific session in that case.

   ``--method auto`` tries ``logon`` first and falls back to ``asuser``.

Credentials
-----------
Never hardcoded and never committed. Resolution order:
``--password`` (discouraged — visible in the process list) → ``--password-env VAR``
(default ``LW_ALT_PASSWORD``) → ``--password-file`` → Windows Credential Manager
(``LastWarVpBot/<domain>\<user>``, DPAPI-encrypted per caller) → interactive
prompt. ``--save-credential`` stores what was entered in Credential Manager so
later runs are non-interactive; ``--forget-credential`` deletes it.

Usage (Windows Python — pywin32 lives there, not in WSL's python3)::

    C:\Python312\python.exe tools\launch_as_user.py --check
    C:\Python312\python.exe tools\launch_as_user.py --list-users
    C:\Python312\python.exe tools\launch_as_user.py --user casper --dry-run
    C:\Python312\python.exe tools\launch_as_user.py --user casper --save-credential
    C:\Python312\python.exe tools\launch_as_user.py --user casper --test    # charmap, not the game
    C:\Python312\python.exe tools\launch_as_user.py --user casper
    C:\Python312\python.exe tools\launch_as_user.py --config accounts.json --all --stagger 60
    C:\Python312\python.exe tools\launch_as_user.py --config accounts.json --user user3
    C:\Python312\python.exe tools\launch_as_user.py --user casper --revoke  # take the grants back

The accounts file is a list of ``{"user", "exe"?, "password"?, "domain"?, "args"?,
"cwd"?}`` — see ``tools/data/accounts.example.json``. Leave ``password`` out and it
comes from Credential Manager, so the file itself holds no secret; leave ``exe`` out
and it resolves to that account's own install. Real account lists are git-ignored.

Importable::

    from launch_as_user import launch_as_user
    pid = launch_as_user("user2", None, r"C:\Games\LastWar\LastWar.exe")  # None => Credential Manager

Known limits (read before blaming the script)
---------------------------------------------
* **ACE kills the game under a foreign token** — see the note at the top. The
  script reports the launch as successful because it *was* successful: the
  process is created and then terminated by the anti-cheat a few seconds later.
  ``--wait`` will show the fresh pid appear and, shortly after, nothing.
* **The exe does not have to be readable by the caller.** The game sits in the
  target user's private profile, which this account cannot open, and the launch
  works anyway: the secondary-logon service resolves and opens the path while
  impersonating the target. ``--check`` therefore reports such a path as
  "unreadable from this account", not as missing — that is expected, not a
  problem. If a launch ever does fail with «Access is denied», point ``--exe``
  at a copy in a shared location.
* **One foreground window at a time.** Two clients on one desktop is fine for
  the game, but this bot's input model is foreground-only — drive the instances
  one at a time, focusing the one you are working with.
* **One account per client.** The game is single-session per *game* account: a
  second login on the same account kicks the first. Two clients means two game
  accounts.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import getpass
import json
import os
import subprocess
import sys
import time

if sys.platform != "win32":
    raise SystemExit(
        "launch_as_user.py needs the Windows Python (pywin32 + Win32 API):\n"
        r"    C:\Python312\python.exe tools\launch_as_user.py --check"
    )

import winreg  # noqa: E402

import win32api  # noqa: E402
import win32con  # noqa: E402
import win32cred  # noqa: E402
import win32process  # noqa: E402
import win32profile  # noqa: E402
import win32security  # noqa: E402
import win32service  # noqa: E402

# ---------------------------------------------------------------- constants --

# Window-station / desktop rights. WINSTA_ALL_ACCESS and the desktop rights are
# not exported by pywin32, so spell them out (winuser.h).
WINSTA_ALL_ACCESS = 0x0000037F
DESKTOP_ALL_ACCESS = 0x000001FF
STANDARD_RIGHTS_REQUIRED = 0x000F0000
GENERIC_ACCESS = 0xF0000000  # GENERIC_READ|WRITE|EXECUTE|ALL

READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
DACL_RW = READ_CONTROL | WRITE_DAC

OBJECT_INHERIT_ACE = 0x01
CONTAINER_INHERIT_ACE = 0x02
NO_PROPAGATE_INHERIT_ACE = 0x04
INHERIT_ONLY_ACE = 0x08

LOGON_WITH_PROFILE = 0x00000001
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NEW_CONSOLE = 0x00000010

DEFAULT_DESKTOP = r"WinSta0\Default"
CRED_PREFIX = "LastWarVpBot"
GAME_SUBDIR = os.path.join("AppData", "Local", "FunFly", "Last War-Survival Game")
PROFILE_LIST = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList"

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("lpReserved", wt.LPWSTR),
        ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD),
        ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD),
        ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD),
        ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wt.HANDLE),
        ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId", wt.DWORD),
    ]


advapi32.CreateProcessWithLogonW.argtypes = [
    wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    wt.LPCWSTR, wt.LPWSTR, wt.DWORD, wt.LPVOID, wt.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION),
]
advapi32.CreateProcessWithLogonW.restype = wt.BOOL


# ------------------------------------------------------------------ helpers --

def _oem(data: bytes) -> str:
    """Decode console output in the OEM code page, never raising on stray bytes."""
    try:
        cp = "cp%d" % kernel32.GetOEMCP()
        return data.decode(cp, errors="replace")
    except Exception:  # noqa: BLE001
        return data.decode("utf-8", errors="replace")


def current_session() -> int:
    sid = wt.DWORD()
    kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(sid))
    return int(sid.value)


def caller_objects() -> tuple[str, str]:
    """(window station, desktop) the caller itself is attached to."""
    user32 = ctypes.windll.user32
    out = []
    for handle in (user32.GetProcessWindowStation(),
                   user32.GetThreadDesktop(kernel32.GetCurrentThreadId())):
        buf = ctypes.create_unicode_buffer(256)
        need = wt.DWORD()
        ok = user32.GetUserObjectInformationW(handle, 2, buf, 512, ctypes.byref(need))
        out.append(buf.value if ok else "?")
    return out[0], out[1]


def resolve_account(name: str, domain: str | None):
    """('DOMAIN', 'user', sid) for a local or domain account, or raise."""
    lookup = name if not domain or domain in (".", "") else f"{domain}\\{name}"
    try:
        sid, dom, _kind = win32security.LookupAccountName(None, lookup)
    except win32security.error as exc:  # noqa: PERF203
        raise SystemExit(f"unknown account {lookup!r}: {exc.strerror}") from exc
    return dom, name, sid


def profile_path(sid) -> str | None:
    """The target user's profile directory, read from HKLM ProfileList.

    Present only once the user has logged on at least once — a never-used
    account has no profile and therefore no game install either.
    """
    text_sid = win32security.ConvertSidToStringSid(sid)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PROFILE_LIST + "\\" + text_sid) as key:
            path, _ = winreg.QueryValueEx(key, "ProfileImagePath")
    except OSError:
        return None
    return win32api.ExpandEnvironmentStrings(path)


def game_paths(profile: str) -> tuple[str, str]:
    """(launcher, game exe) inside a given profile directory."""
    root = os.path.join(profile, GAME_SUBDIR)
    return (os.path.join(root, "LastWarLauncher.exe"),
            os.path.join(root, "Game", "LastWar.exe"))


def readable(path: str) -> bool | None:
    """True/False if we can tell, None when the answer is 'permission denied'.

    ``os.path.exists`` is useless here: it swallows every OSError and answers
    False, so another user's private profile looks identical to a missing
    install. ``os.stat`` tells the two apart.
    """
    try:
        os.stat(path)
        return True
    except FileNotFoundError:
        # A denied *parent* surfaces as PermissionError, so a genuine
        # FileNotFound means we could walk there and the leaf is absent.
        return False
    except PermissionError:
        return None
    except OSError:
        return None


def lastwar_pids() -> set[int]:
    """PIDs of every running LastWar.exe, regardless of owner."""
    try:
        raw = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq LastWar.exe", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    pids = set()
    for line in _oem(raw).splitlines():
        parts = [p.strip('" ') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == "lastwar.exe":
            try:
                pids.add(int(parts[1]))
            except ValueError:
                pass
    return pids


def running_clients() -> list[tuple[str, ...]]:
    """Verbose tasklist rows for LastWar.exe (image, pid, winstation, session, ..., user)."""
    try:
        raw = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq LastWar.exe", "/V", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in _oem(raw).splitlines():
        parts = [p.strip('" ') for p in line.split('","')]
        if len(parts) >= 7 and parts[0].lower() == "lastwar.exe":
            rows.append(tuple(parts))
    return rows


# --------------------------------------------- window station / desktop ACL --

def _signed(mask: int) -> int:
    """Access masks are DWORDs, but pywin32 marshals them through a signed C long.

    ``GENERIC_ACCESS`` (0xF0000000) therefore overflows unless it is handed over
    as the negative number with the same bit pattern — which is also how pywin32
    hands existing ACEs back when reading a DACL.
    """
    return mask - 0x100000000 if mask > 0x7FFFFFFF else mask


def _ace_for(dacl, sid, mask: int, flags: int) -> bool:
    """True when an allow-ACE for `sid` already carries at least `mask`+`flags`."""
    for i in range(dacl.GetAceCount()):
        (ace_type, ace_flags), ace_mask, ace_sid = dacl.GetAce(i)
        if ace_type != win32security.ACCESS_ALLOWED_ACE_TYPE:
            continue
        if ace_sid != sid:
            continue
        have = ace_mask & 0xFFFFFFFF
        want = mask & 0xFFFFFFFF
        if (have & want) == want and (ace_flags & flags) == flags:
            return True
    return False


def _open_winsta(access: int):
    return win32service.OpenWindowStation("WinSta0", False, access)


def _open_desktop(name: str, access: int):
    return win32service.OpenDesktop(name, 0, False, access)


def _apply(handle, aces, sid, dry: bool, log) -> bool:
    """Add the (mask, flags) pairs for `sid` to a user object's DACL. True if changed."""
    sd = win32security.GetUserObjectSecurity(handle, win32security.DACL_SECURITY_INFORMATION)
    dacl = sd.GetSecurityDescriptorDacl()
    if dacl is None:
        raise SystemExit("user object has a NULL DACL — refusing to touch it")
    changed = False
    for mask, flags in aces:
        if _ace_for(dacl, sid, mask, flags):
            log(f"    already granted: mask={mask:#010x} flags={flags:#04x}")
            continue
        changed = True
        log(f"    + allow mask={mask:#010x} flags={flags:#04x}")
        if not dry:
            dacl.AddAccessAllowedAceEx(
                win32security.ACL_REVISION, flags, _signed(mask), sid)
    if changed and not dry:
        sd.SetSecurityDescriptorDacl(1, dacl, 0)
        win32security.SetUserObjectSecurity(
            handle, win32security.DACL_SECURITY_INFORMATION, sd)
    return changed


def grant_desktop_access(sid, desktop: str, dry: bool, log) -> None:
    r"""Let `sid` use WinSta0 and the named desktop.

    Two ACEs on the window station, as the SDK's own sample does: an inherit-only
    generic one (so objects *created inside* the station — clipboard, atoms,
    desktops — are reachable too) and a direct WINSTA_ALL_ACCESS one. The desktop
    gets a single DESKTOP_ALL ACE. Both are lost at logoff, hence re-applied here
    on every launch.
    """
    station = desktop.split("\\")[0] if "\\" in desktop else "WinSta0"
    desk = desktop.split("\\")[-1]
    if station.lower() != "winsta0":
        log(f"[grant] note: non-interactive station {station!r} will not be visible on screen")

    log(f"[grant] window station {station}")
    handle = _open_winsta(DACL_RW)
    _apply(handle,
           [(GENERIC_ACCESS,
             CONTAINER_INHERIT_ACE | INHERIT_ONLY_ACE | OBJECT_INHERIT_ACE),
            (WINSTA_ALL_ACCESS | STANDARD_RIGHTS_REQUIRED,
             NO_PROPAGATE_INHERIT_ACE)],
           sid, dry, log)

    log(f"[grant] desktop {desk}")
    handle = _open_desktop(desk, DACL_RW)
    _apply(handle,
           [(DESKTOP_ALL_ACCESS | STANDARD_RIGHTS_REQUIRED, 0)],
           sid, dry, log)


def _strip(handle, sid, dry: bool, log) -> int:
    sd = win32security.GetUserObjectSecurity(handle, win32security.DACL_SECURITY_INFORMATION)
    dacl = sd.GetSecurityDescriptorDacl()
    if dacl is None:
        return 0
    removed = 0
    for i in range(dacl.GetAceCount() - 1, -1, -1):
        (ace_type, _flags), _mask, ace_sid = dacl.GetAce(i)
        if ace_type == win32security.ACCESS_ALLOWED_ACE_TYPE and ace_sid == sid:
            removed += 1
            if not dry:
                dacl.DeleteAce(i)
    if removed and not dry:
        sd.SetSecurityDescriptorDacl(1, dacl, 0)
        win32security.SetUserObjectSecurity(
            handle, win32security.DACL_SECURITY_INFORMATION, sd)
    log(f"    removed {removed} ACE(s)")
    return removed


def revoke_desktop_access(sid, desktop: str, dry: bool, log) -> None:
    """Take back what grant_desktop_access() handed out. Leaves other ACEs alone."""
    station = desktop.split("\\")[0] if "\\" in desktop else "WinSta0"
    desk = desktop.split("\\")[-1]
    log(f"[revoke] window station {station}")
    _strip(_open_winsta(DACL_RW), sid, dry, log)
    log(f"[revoke] desktop {desk}")
    _strip(_open_desktop(desk, DACL_RW), sid, dry, log)


# -------------------------------------------------------------- credentials --

def _cred_target(domain: str, user: str) -> str:
    return f"{CRED_PREFIX}/{domain}\\{user}"


def cred_read(domain: str, user: str) -> str | None:
    try:
        cred = win32cred.CredRead(_cred_target(domain, user), win32cred.CRED_TYPE_GENERIC)
    except Exception:  # noqa: BLE001  (pywintypes.error when absent)
        return None
    blob = cred.get("CredentialBlob") or b""
    try:
        return blob.decode("utf-16-le")
    except UnicodeDecodeError:
        return blob.decode("utf-8", errors="replace")


def cred_write(domain: str, user: str, password: str) -> None:
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": _cred_target(domain, user),
        "UserName": f"{domain}\\{user}",
        "CredentialBlob": password,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": "last-war-vp-bot multi-instance launcher (#1105)",
    }, 0)


def cred_delete(domain: str, user: str) -> bool:
    try:
        win32cred.CredDelete(_cred_target(domain, user), win32cred.CRED_TYPE_GENERIC)
        return True
    except Exception:  # noqa: BLE001
        return False


def _password_from_args(args) -> str | None:
    """The non-interactive sources, in order, or None if none of them has it."""
    if args.password is not None:
        return args.password
    if args.password_env:
        value = os.environ.get(args.password_env)
        if value:
            return value
    if args.password_file:
        with open(args.password_file, "r", encoding="utf-8") as fh:
            line = fh.readline().rstrip("\r\n")
        if line:
            return line
    return None


def resolve_password(args, domain: str, user: str) -> str:
    given = _password_from_args(args)
    if given is not None:
        return given
    stored = cred_read(domain, user)
    if stored is not None:
        return stored
    if not sys.stdin or not sys.stdin.isatty():
        raise SystemExit(
            f"no password for {domain}\\{user} and no terminal to ask on.\n"
            f"  set it once:  --user {user} --save-credential   (stored via DPAPI)\n"
            f"  or pass it:   --password-env {args.password_env} / --password-file <path>")
    return getpass.getpass(f"Password for {domain}\\{user}: ")


# ------------------------------------------------------------------ launch ---

def _startupinfo_w(desktop: str, show: int) -> STARTUPINFOW:
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.lpDesktop = desktop
    si.dwFlags = win32con.STARTF_USESHOWWINDOW
    si.wShowWindow = show
    return si


def _via_logon(user, domain, password, exe, cmdline, cwd, desktop, flags, log) -> int:
    """CreateProcessWithLogonW — no privileges needed, profile loaded, same session."""
    si = _startupinfo_w(desktop, win32con.SW_SHOWNORMAL)
    pi = PROCESS_INFORMATION()
    buf = ctypes.create_unicode_buffer(cmdline, len(cmdline) + 1)
    ok = advapi32.CreateProcessWithLogonW(
        user, domain, password,
        LOGON_WITH_PROFILE,
        exe, buf,
        flags,
        None,           # NULL env => the TARGET user's profile environment
        cwd,
        ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateProcessWithLogonW failed: "
                           f"{win32api.FormatMessage(err).strip()} (win32 error {err})")
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    log(f"[logon] started pid={pi.dwProcessId} on {desktop}")
    return int(pi.dwProcessId)


def _enable_privilege(name: str) -> bool:
    try:
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY)
        luid = win32security.LookupPrivilegeValue(None, name)
        win32security.AdjustTokenPrivileges(
            token, False, [(luid, win32con.SE_PRIVILEGE_ENABLED)])
        return win32api.GetLastError() == 0
    except Exception:  # noqa: BLE001
        return False


def _via_token(user, domain, password, exe, cmdline, cwd, desktop,
               flags, session, log) -> int:
    """LogonUser + LoadUserProfile + CreateProcessAsUser — the privileged route."""
    for priv in ("SeAssignPrimaryTokenPrivilege", "SeIncreaseQuotaPrivilege"):
        log(f"[asuser] enable {priv}: {'ok' if _enable_privilege(priv) else 'NOT held'}")

    token = win32security.LogonUser(
        user, domain, password,
        win32con.LOGON32_LOGON_INTERACTIVE, win32con.LOGON32_PROVIDER_DEFAULT)
    primary = win32security.DuplicateTokenEx(
        token, win32security.SecurityImpersonation, win32con.MAXIMUM_ALLOWED,
        win32security.TokenPrimary, None)

    target_session = current_session() if session is None else session
    try:
        win32security.SetTokenInformation(
            primary, win32security.TokenSessionId, target_session)
        log(f"[asuser] token session -> {target_session}")
    except Exception as exc:  # noqa: BLE001
        log(f"[asuser] could not set token session ({exc}); token keeps its own")

    handle = win32profile.LoadUserProfile(primary, {"UserName": user})
    env = win32profile.CreateEnvironmentBlock(primary, False)

    si = win32process.STARTUPINFO()
    si.lpDesktop = desktop
    si.dwFlags = win32con.STARTF_USESHOWWINDOW
    si.wShowWindow = win32con.SW_SHOWNORMAL
    try:
        pi = win32process.CreateProcessAsUser(
            primary, exe, cmdline, None, None, False,
            flags | CREATE_UNICODE_ENVIRONMENT, env, cwd, si)
    finally:
        # The profile stays mounted for the child; unloading here would yank it.
        del handle
    log(f"[asuser] started pid={pi[2]} on {desktop}")
    return int(pi[2])


def launch_as_user(username, password, exe_path, domain=None, *, args="",
                   cwd=None, desktop=DEFAULT_DESKTOP, method="logon",
                   grant=True, session=None, log=print) -> int:
    """Start `exe_path` as `username` on `desktop`, in the caller's session.

    The importable entry point — grants the account access to the window station
    and desktop (unless `grant=False`), then runs one of the two routes:

    * ``method="logon"``  — CreateProcessWithLogonW; no privileges, works for a
      plain user. The default, and the only one that works unelevated.
    * ``method="asuser"`` — CreateProcessAsUser; needs SeAssignPrimaryToken,
      i.e. SYSTEM. `session` retargets the token (default: this session).
    * ``method="auto"``   — try "logon", fall back to "asuser".

    `password` may be None, in which case it comes from Credential Manager
    (`LastWarVpBot/<domain>\\<user>`). Returns the new pid; raises OSError /
    pywintypes.error if every route failed.

    Beware: a successful return means Windows created the process, not that it
    survived. ACE terminates the game itself a few seconds in — see the note at
    the top of this module.
    """
    dom, user, sid = resolve_account(username, domain)
    if password is None:
        password = cred_read(dom, user)
        if password is None:
            raise SystemExit(f"no password for {dom}\\{user}: pass one, or store it "
                             f"with --user {user} --save-credential")
    if grant:
        grant_desktop_access(sid, desktop, False, log)

    exe_path = os.path.expandvars(exe_path)
    cmdline = f'"{exe_path}"' + (f" {args}" if args else "")
    cwd = cwd or os.path.dirname(exe_path)
    flags = CREATE_NEW_CONSOLE

    last = None
    for route in {"logon": ["logon"], "asuser": ["asuser"],
                  "auto": ["logon", "asuser"]}[method]:
        try:
            if route == "logon":
                return _via_logon(user, dom, password, exe_path, cmdline,
                                  cwd, desktop, flags, log)
            return _via_token(user, dom, password, exe_path, cmdline,
                              cwd, desktop, flags, session, log)
        except Exception as exc:  # noqa: BLE001
            last = exc
            log(f"[{route}] failed: {exc}")
    raise last


# ---------------------------------------------------------------- accounts ---

def load_accounts(path: str) -> list[dict]:
    r"""Read an accounts file: a list of {"user", "password"?, "exe"?, "domain"?, "args"?}.

    ``password`` is optional and better left out — without it the password comes
    from Credential Manager, so the file holds no secret and can live anywhere.
    ``exe`` is optional too: omitted, it resolves to that account's own
    ``%LOCALAPPDATA%\FunFly\...\LastWarLauncher.exe``.

        [
          {"user": "user2"},
          {"user": "user3", "exe": "C:\\Games\\LastWar\\LastWar.exe"}
        ]
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):                 # tolerate {"accounts": [...]}
        data = data.get("accounts", [])
    if not isinstance(data, list):
        raise SystemExit(f"{path}: expected a list of accounts")
    out = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or not item.get("user"):
            raise SystemExit(f"{path}: entry {i} has no \"user\"")
        out.append(item)
    return out


def account_exe(entry: dict, sid, which: str) -> str:
    """The executable for one accounts-file entry: explicit, or that user's install."""
    if entry.get("exe"):
        return os.path.expandvars(entry["exe"])
    profile = profile_path(sid)
    if not profile:
        raise SystemExit(f"{entry['user']} has no profile on this machine — log in as "
                         f"that user once, install the game, then retry")
    launcher, client = game_paths(profile)
    return launcher if which == "launcher" else client


# ----------------------------------------------------------------- reports ---

def report_check(args, log) -> None:
    station, desk = caller_objects()
    log("== caller ==")
    log(f"  user           : {win32api.GetUserNameEx(win32api.NameSamCompatible)}")
    log(f"  session        : {current_session()}")
    log(f"  winsta/desktop : {station}\\{desk}")
    log(f"  can edit WinSta0 DACL: {'yes' if _probe_dacl() else 'no'}")

    log("== running clients ==")
    rows = running_clients()
    if not rows:
        log("  (no LastWar.exe running)")
    for row in rows:
        pid, winsta, sess, user = row[1], row[2], row[3], row[6]
        log(f"  pid={pid:<8} session={sess:<3} station={winsta:<12} user={user}")

    if not args.user:
        log("== target ==")
        log("  (pass --user <name> for a per-account report; --list-users to see who exists)")
        return

    domain, user, sid = resolve_account(args.user, args.domain)
    log("== target ==")
    log(f"  account : {domain}\\{user}")
    log(f"  sid     : {win32security.ConvertSidToStringSid(sid)}")
    profile = profile_path(sid)
    log(f"  profile : {profile or 'NONE — this account has never logged on'}")
    if profile:
        launcher, game = game_paths(profile)
        for label, path in (("launcher", launcher), ("game", game)):
            state = readable(path)
            mark = {True: "present", False: "MISSING",
                    None: "unreadable from this account (grant read access or use --exe)"}[state]
            log(f"  {label:<8}: {mark}")
            log(f"            {path}")
    log(f"  credential in Credential Manager: "
        f"{'yes' if cred_read(domain, user) is not None else 'no'}")
    log("  desktop grants:")
    _report_grants(sid, args.desktop, log)


def _probe_dacl() -> bool:
    try:
        _open_winsta(DACL_RW)
        return True
    except Exception:  # noqa: BLE001
        return False


def _report_grants(sid, desktop: str, log) -> None:
    desk = desktop.split("\\")[-1]
    try:
        for label, handle, wanted in (
            ("WinSta0", _open_winsta(READ_CONTROL),
             [(GENERIC_ACCESS, CONTAINER_INHERIT_ACE | INHERIT_ONLY_ACE | OBJECT_INHERIT_ACE),
              (WINSTA_ALL_ACCESS | STANDARD_RIGHTS_REQUIRED, NO_PROPAGATE_INHERIT_ACE)]),
            (desk, _open_desktop(desk, READ_CONTROL),
             [(DESKTOP_ALL_ACCESS | STANDARD_RIGHTS_REQUIRED, 0)]),
        ):
            sd = win32security.GetUserObjectSecurity(
                handle, win32security.DACL_SECURITY_INFORMATION)
            dacl = sd.GetSecurityDescriptorDacl()
            have = all(_ace_for(dacl, sid, m, f) for m, f in wanted) if dacl else False
            log(f"    {label:<10}: {'granted' if have else 'not granted'}")
    except Exception as exc:  # noqa: BLE001
        log(f"    (could not read: {exc})")


def report_users(log) -> None:
    """Local accounts that own a profile, and whether a Last War install is visible."""
    log("== local profiles ==")
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PROFILE_LIST) as root:
        index = 0
        while True:
            try:
                text_sid = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if not text_sid.startswith("S-1-5-21-"):
                continue
            try:
                sid = win32security.ConvertStringSidToSid(text_sid)
                name, dom, _ = win32security.LookupAccountSid(None, sid)
            except Exception:  # noqa: BLE001
                name, dom = "(orphaned)", "?"
            profile = profile_path(sid) or ""
            state = readable(os.path.join(profile, GAME_SUBDIR)) if profile else False
            mark = {True: "game installed", False: "no game",
                    None: "private (cannot tell)"}[state]
            log(f"  {dom}\\{name:<16} {mark:<24} {profile}")


# --------------------------------------------------------------------- CLI ---

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="launch_as_user.py",
        description="Start Last War as another Windows user on the current desktop.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage")[-1])
    p.add_argument("--user", help="target Windows account (e.g. casper)")
    p.add_argument("--domain", default=".",
                   help="account domain; '.' (default) means this machine")
    p.add_argument("--exe", help="override the executable to start")
    p.add_argument("--args", default="", help="extra command line for the executable")
    p.add_argument("--cwd", help="working directory (defaults to the exe's folder)")
    p.add_argument("--game", choices=("launcher", "client"), default="launcher",
                   help="launcher (LastWarLauncher.exe, default) or client (Game/LastWar.exe)")
    p.add_argument("--desktop", default=DEFAULT_DESKTOP,
                   help=r'target desktop (default "WinSta0\Default" — the one you are looking at)')
    p.add_argument("--method", choices=("auto", "logon", "asuser"), default="logon",
                   help="logon = CreateProcessWithLogonW (default, no privileges); "
                        "asuser = CreateProcessAsUser (needs SeAssignPrimaryToken); auto = try both")
    p.add_argument("--session", type=int,
                   help="session id for the asuser route (default: this session)")
    p.add_argument("--password", help="target password (AVOID: visible in the process list)")
    p.add_argument("--password-env", default="LW_ALT_PASSWORD",
                   help="environment variable holding the password (default LW_ALT_PASSWORD)")
    p.add_argument("--password-file", help="file whose first line is the password")
    p.add_argument("--save-credential", action="store_true",
                   help="store the password in Windows Credential Manager and exit")
    p.add_argument("--forget-credential", action="store_true",
                   help="delete the stored credential and exit")
    p.add_argument("--test", action="store_true",
                   help="launch charmap.exe instead of the game — proves the desktop plumbing")
    p.add_argument("--grant-only", action="store_true",
                   help="apply the WinSta0/desktop grants and exit, launching nothing")
    p.add_argument("--revoke", action="store_true",
                   help="remove this tool's WinSta0/desktop grants for the user and exit")
    p.add_argument("--no-grant", action="store_true",
                   help="skip the grants (they are already in place, or you manage them yourself)")
    p.add_argument("--config", metavar="accounts.json",
                   help='accounts file: [{"user": "...", "exe"?, "password"?, "domain"?, "args"?}]'
                        " — omit the password and it comes from Credential Manager")
    p.add_argument("--all", action="store_true",
                   help="launch every account in --config (one instance each)")
    p.add_argument("--stagger", type=int, default=0, metavar="SEC",
                   help="seconds to wait between --all launches (a cold start is heavy)")
    p.add_argument("--check", action="store_true", help="report the environment and exit")
    p.add_argument("--list-users", action="store_true",
                   help="list local accounts with profiles and exit")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would happen, change nothing, start nothing")
    p.add_argument("--wait", type=int, default=0, metavar="SEC",
                   help="after launching, wait up to SEC for a new LastWar.exe to appear")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    def log(msg: str) -> None:
        print(msg, flush=True)

    if args.list_users:
        report_users(log)
        return 0
    if args.check:
        report_check(args, log)
        return 0

    # ---- accounts file: launch every entry (--all) or one named entry (--user)
    if args.config:
        accounts = load_accounts(args.config)
        if args.all:
            log(f"[config] {args.config}: {len(accounts)} account(s) — "
                f"{', '.join(a['user'] for a in accounts)}")
            rc = 0
            for i, entry in enumerate(accounts):
                if i:
                    log("")
                    if args.stagger:
                        log(f"[config] waiting {args.stagger}s before the next one")
                        time.sleep(args.stagger)
                try:
                    if _launch_one(args, entry, log) != 0:
                        rc = 1
                # SystemExit is not an Exception — a bad entry must not abort the rest
                except (SystemExit, Exception) as exc:  # noqa: BLE001
                    log(f"[config] {entry['user']}: {exc}")
                    rc = 1
            return rc
        if args.user:
            match = [a for a in accounts if a["user"].lower() == args.user.lower()]
            if not match:
                log(f"error: {args.user!r} is not in {args.config}")
                return 2
            return _launch_one(args, match[0], log)
        log("error: --config needs --all, or --user to pick one entry from it")
        return 2
    if args.all:
        log("error: --all needs --config <accounts.json>")
        return 2

    if not args.user:
        build_parser().print_usage()
        log("error: --user is required (or use --config/--check/--list-users)")
        return 2

    domain, user, sid = resolve_account(args.user, args.domain)

    if args.forget_credential:
        log(f"credential for {domain}\\{user}: "
            f"{'deleted' if cred_delete(domain, user) else 'none stored'}")
        return 0
    if args.save_credential:
        password = _password_from_args(args)
        if password is None:
            password = getpass.getpass(f"Password for {domain}\\{user}: ")
        cred_write(domain, user, password)
        log(f"stored credential for {domain}\\{user} "
            f"(target {_cred_target(domain, user)}, DPAPI-protected)")
        return 0

    if args.revoke:
        revoke_desktop_access(sid, args.desktop, args.dry_run, log)
        return 0

    return _launch_one(args, {"user": args.user, "domain": args.domain}, log)


def _launch_one(args, entry: dict, log) -> int:
    """Run one account: grants, path resolution, password, launch, optional wait."""
    domain, user, sid = resolve_account(entry["user"], entry.get("domain") or args.domain)

    if not args.no_grant:
        grant_desktop_access(sid, args.desktop, args.dry_run, log)
    if args.grant_only:
        return 0

    # ---- what to start
    if args.test:
        # charmap, not notepad: notepad.exe is an execution alias for the Store
        # app, which refuses a non-NULL lpDesktop and surfaces its UI in another
        # process — it proves nothing. charmap is a plain Win32 binary.
        exe = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "charmap.exe")
    elif entry.get("exe") or args.exe:
        exe = os.path.expandvars(entry.get("exe") or args.exe)
    else:
        exe = account_exe(entry, sid, args.game)

    extra = entry.get("args") or args.args
    cwd = entry.get("cwd") or args.cwd or os.path.dirname(exe)
    cmdline = f'"{exe}"' + (f" {extra}" if extra else "")
    flags = CREATE_NEW_CONSOLE

    log(f"[plan] user    : {domain}\\{user}")
    log(f"[plan] exe     : {exe}")
    log(f"[plan] cwd     : {cwd}")
    log(f"[plan] desktop : {args.desktop}")
    log(f"[plan] method  : {args.method}")
    state = readable(exe)
    if state is False:
        log("[plan] WARNING: that path does not exist as far as this account can see")
    elif state is None:
        log("[plan] note: path is inside a private profile, so this account cannot verify "
            "it - that is fine, the logon service opens it as the target user")

    if args.dry_run:
        log("[dry-run] nothing was started")
        return 0

    password = entry.get("password") or resolve_password(args, domain, user)
    before = lastwar_pids()

    attempts = {"logon": ["logon"], "asuser": ["asuser"], "auto": ["logon", "asuser"]}[args.method]
    pid, last_error = None, None
    for method in attempts:
        try:
            if method == "logon":
                pid = _via_logon(user, domain, password, exe, cmdline,
                                 cwd, args.desktop, flags, log)
            else:
                pid = _via_token(user, domain, password, exe, cmdline,
                                 cwd, args.desktop, flags, args.session, log)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log(f"[{method}] failed: {exc}")
    if pid is None:
        log(f"launch failed: {last_error}")
        return 1

    if args.wait:
        log(f"[wait] up to {args.wait}s for a new LastWar.exe …")
        deadline = time.monotonic() + args.wait
        fresh: set[int] = set()
        while time.monotonic() < deadline:
            fresh = lastwar_pids() - before
            if fresh:
                log(f"[wait] new client pid(s): {sorted(fresh)}")
                break
            time.sleep(2)
        else:
            log("[wait] no new LastWar.exe yet — a cold start with the updater can take "
                "minutes; check with --check")

        # Appearing is not surviving: ACE kills the client a few seconds in, so a
        # bare "it started" reads as success when it is not. Watch the pid a while
        # longer and say plainly whether it is still there. Liveness is read from
        # the process list on purpose — OpenProcess on another user's process is
        # denied unelevated, and GetExitCodeProcess on the resulting NULL handle
        # silently leaves the exit code at STILL_ACTIVE, i.e. it lies.
        if fresh:
            watch = min(30, max(10, args.wait))
            log(f"[wait] watching them for {watch}s (ACE kills the game ~9s in) …")
            end = time.monotonic() + watch
            while time.monotonic() < end:
                gone = fresh - lastwar_pids()
                if gone:
                    log(f"[wait] pid(s) {sorted(gone)} DIED — the usual ACE 0xDEADC0DE; "
                        f"see docs/research/multi-instance-second-user.md")
                    return 1
                time.sleep(2)
            log(f"[wait] still running after {watch}s: {sorted(fresh)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
