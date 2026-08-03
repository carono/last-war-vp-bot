r"""Start a process inside an already logged-on Windows session — the SYSTEM half.

Task #1106. `launch_as_user.py` (#1105) starts a process **as another user in the
caller's session**, which is the arrangement ACE refuses to let the game live in.
This tool does the opposite and the game accepts it: it takes the token that is
*already* the interactive logon of session N and starts the process with it, in
session N. Process user and session owner are then the same account — an ordinary
launch, only issued from outside.

The token comes from ``WTSQueryUserToken(session)``, so **no password is needed** and
none is stored anywhere. That call needs ``SeTcbPrivilege``, i.e. the caller must be
SYSTEM; `tools/rdp_instance.py` gets there through a throwaway SYSTEM scheduled task.
Run by hand only from an already-SYSTEM shell:

    C:\Python312\python.exe tools\session_launch.py --session 3 --exe C:\Windows\System32\cmd.exe
    C:\Python312\python.exe tools\session_launch.py --session 3 --game
    C:\Python312\python.exe tools\session_launch.py --list

`--session` accepts a session id or a user name (`--session <login>`). The process is
started on ``WinSta0\Default`` *of that session* — the desktop the session owns,
whether it is on the console, on an RDP connection, or disconnected. A disconnected
session still has a desktop; nothing about the launch requires anyone to be watching.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import game_paths  # noqa: E402

if sys.platform != "win32":
    raise SystemExit(
        "session_launch.py needs the Windows Python (pywin32):\n"
        r"    C:\Python312\python.exe tools\session_launch.py --list")

import win32api  # noqa: E402
import win32con  # noqa: E402
import win32process  # noqa: E402
import win32profile  # noqa: E402
import win32security  # noqa: E402
import win32ts  # noqa: E402

STATE_NAMES = {0: "active", 1: "connected", 2: "connectquery", 3: "shadow",
               4: "disconnected", 5: "idle", 6: "listen", 7: "reset", 8: "down",
               9: "init"}


# ------------------------------------------------------------------ sessions --

def sessions() -> list[dict]:
    """Every session the machine knows about, with its user and state."""
    out = []
    for s in win32ts.WTSEnumerateSessions():
        sid = s["SessionId"]

        def q(info):
            try:
                return win32ts.WTSQuerySessionInformation(0, sid, info)
            except Exception:  # noqa: BLE001 — access denied on foreign sessions
                return ""
        out.append({
            "id": sid,
            "user": q(win32ts.WTSUserName),
            "domain": q(win32ts.WTSDomainName),
            "station": s["WinStationName"],
            "state": STATE_NAMES.get(s["State"], str(s["State"])),
        })
    return out


def resolve_session(spec: str) -> int:
    """A session id, or the id of the session a named user is logged on to."""
    if str(spec).isdigit():
        return int(spec)
    for s in sessions():
        if s["user"].lower() == str(spec).lower():
            return s["id"]
    raise SystemExit(f"no logged-on session for user {spec!r} — "
                     f"sessions: {[(s['id'], s['user'], s['state']) for s in sessions()]}")


def session_user(session: int) -> str:
    for s in sessions():
        if s["id"] == session:
            return s["user"]
    return ""


def profile_of(session: int) -> str:
    """The profile directory of the user logged on to `session`."""
    user = session_user(session)
    if not user:
        raise SystemExit(f"session {session} has no logged-on user")
    # ProfileList is keyed by SID; the account is local on this machine.
    import winreg
    sid, _dom, _kind = win32security.LookupAccountName(None, user)
    text = win32security.ConvertSidToStringSid(sid)
    key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList" + "\\" + text
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
        path, _ = winreg.QueryValueEx(k, "ProfileImagePath")
    return win32api.ExpandEnvironmentStrings(path)


def expand_for(text: str, env) -> str:
    """Expand ``%VAR%`` against ``env`` — the TARGET session's variables, not ours.

    `os.path.expandvars` would use this process's environment, which under a SYSTEM
    scheduled task is SYSTEM's: ``%LOCALAPPDATA%`` there is
    ``C:\\Windows\\system32\\config\\systemprofile\\AppData\\Local``, and the launch
    would go looking for the game inside a service account's profile.

    Names are matched case-insensitively, as Windows does. An unknown variable is left
    standing rather than replaced with nothing — a path with ``%TYPO%`` still in it is
    a mistake somebody can read, whereas one silently missing a segment is not.
    """
    if not text or "%" not in text:
        return text
    lookup = {str(k).upper(): str(v) for k, v in dict(env).items()}
    return re.sub(r"%([^%]+)%",
                  lambda m: lookup.get(m.group(1).upper(), m.group(0)), text)


def game_launcher(session: int) -> str:
    """That session's own copy of the launcher, under that account's profile.

    Not `%LOCALAPPDATA%`: this process is SYSTEM, so expanding it here would name
    SYSTEM's profile. The account's own directory comes from the registry
    (:func:`profile_of`) and the rest is `tools/lib/game_paths.py`'s answer.

    **This process does not inherit the caller's environment.** It is started by a
    scheduled task running as SYSTEM, so `LW_GAME_FOLDER` and friends set in a panel
    are simply not here — which is why `--game-folder` and `--launcher-exe` exist and
    why `game_client` passes them. The environment is still read when nothing is
    passed, for a hand-run from a SYSTEM shell.
    """
    return game_paths.launcher_in_profile(profile_of(session))


# -------------------------------------------------------------------- launch --

def launch_in_session(session: int, exe: str, args: str = "", cwd: str | None = None,
                      desktop: str = r"WinSta0\Default", show: bool = True,
                      env_extra: dict | None = None, log=print) -> int:
    """Start `exe` in `session` under that session's own logon token. Returns the pid.

    Requires SeTcbPrivilege (SYSTEM). The child gets the session user's environment
    block, so ``%LOCALAPPDATA%`` and friends point at *that* user's profile — which is
    the whole point when the second client lives in a second profile.

    **And so does the path to `exe` itself.** That block is the only place on the
    machine where the target account's variables are correct, so `%VAR%` in `exe` and
    `cwd` is expanded against IT rather than against the caller's environment. It
    matters because the caller cannot do this: a panel expanding ``%LOCALAPPDATA%``
    would name the PANEL user's folder and then start it from the other account's
    token. Passing the string through unexpanded and resolving it here is what lets a
    profile say "the game is where it normally is" and mean it per account.

    An absolute path with nothing to expand is untouched, so this costs the ordinary
    case nothing.
    """
    token = win32ts.WTSQueryUserToken(session)
    try:
        primary = win32security.DuplicateTokenEx(
            token, win32security.SecurityImpersonation, win32con.MAXIMUM_ALLOWED,
            win32security.TokenPrimary, None)
    finally:
        token.Close()

    env = win32profile.CreateEnvironmentBlock(primary, False)
    if env_extra:
        env = dict(env)
        env.update(env_extra)

    exe = expand_for(exe, env)
    cwd = expand_for(cwd, env) if cwd else cwd
    if not os.path.exists(exe):
        # Said before the launch rather than after: `CreateProcessAsUser` fails with a
        # bare error code, and "the file is not there" and "the token was refused" read
        # identically in it. SYSTEM can see any account's folders, so this check is
        # meaningful here even though the caller could not have made it.
        raise SystemExit(f"nothing at {exe} in session {session} "
                         f"({session_user(session)})")

    si = win32process.STARTUPINFO()
    si.lpDesktop = desktop
    si.dwFlags = win32con.STARTF_USESHOWWINDOW
    si.wShowWindow = win32con.SW_SHOWNORMAL if show else win32con.SW_HIDE

    cmdline = f'"{exe}"' + (f" {args}" if args else "")
    flags = (win32con.CREATE_UNICODE_ENVIRONMENT | win32con.CREATE_NEW_CONSOLE
             | win32process.CREATE_NEW_PROCESS_GROUP)
    hp, ht, pid, _tid = win32process.CreateProcessAsUser(
        primary, None, cmdline, None, None, False, flags, env,
        cwd or os.path.dirname(exe), si)
    hp.Close()
    ht.Close()
    log(f"[session_launch] pid {pid} in session {session} "
        f"({session_user(session)}): {cmdline}")
    return int(pid)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", help="session id, or the user logged on to it")
    ap.add_argument("--exe", help="program to start")
    ap.add_argument("--args", default="", help="its command line")
    ap.add_argument("--script", help="run this .cmd via cmd.exe /c — spares the caller "
                                     "a level of quoting when the payload has arguments")
    ap.add_argument("--cwd", default=None)
    ap.add_argument("--game", action="store_true",
                    help="start that session's own copy of the launcher")
    # Both default to `tools/lib/game_paths.py`, i.e. to LW_GAME_FOLDER /
    # LW_LAUNCHER_EXE or the ordinary install. They are options and not just
    # environment variables because this process is usually started by a SYSTEM
    # scheduled task, which inherits nothing from whoever asked for the launch.
    ap.add_argument("--game-folder", default=None,
                    help="the game's folder under a user's Local AppData "
                         f"(default: {game_paths.DEFAULT_GAME_FOLDER})")
    ap.add_argument("--launcher-exe", default=None,
                    help=f"the launcher's filename (default: "
                         f"{game_paths.DEFAULT_LAUNCHER_EXE})")
    ap.add_argument("--hidden", action="store_true", help="start minimised/hidden")
    ap.add_argument("--list", action="store_true", help="print the sessions and exit")
    a = ap.parse_args()

    # Put them where `game_launcher` reads them from, so there is one resolver and
    # not a second copy of the join.
    if a.game_folder:
        os.environ["LW_GAME_FOLDER"] = a.game_folder
    if a.launcher_exe:
        os.environ["LW_LAUNCHER_EXE"] = a.launcher_exe

    if a.list or not a.session:
        for s in sessions():
            print(f"  {s['id']:>5}  {s['state']:<13} {s['station']:<12} "
                  f"{(s['domain'] + chr(92) + s['user']) if s['user'] else '-'}")
        return 0

    session = resolve_session(a.session)
    exe, args = a.exe, a.args
    if a.script:
        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "cmd.exe")
        args = f'/c "{a.script}"'
    elif not exe and a.game:
        exe = game_launcher(session)
    if not exe:
        raise SystemExit("nothing to start: pass --exe, --script or --game")
    launch_in_session(session, exe, args, a.cwd, show=not a.hidden)
    return 0


if __name__ == "__main__":
    sys.exit(main())
