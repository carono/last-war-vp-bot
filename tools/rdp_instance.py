r"""A second Last War client in its own Windows session, driven over TCP from this one.

Task #1106, the sequel to #1105. That task established that a second client **cannot**
run as another user inside this session — ACE kills it after ~9 s with `0xDEADC0DE`
(docs/research/multi-instance-second-user.md). What ACE does accept is the ordinary
arrangement: one Windows session per client, each client owned by the session's own
logged-on user. The catch used to be that a client on another desktop is out of reach
of this bot's foreground input.

It is not out of reach of the Lua daemon. Everything headless — the whole
`tools/lua_actions.py` surface, dispatch, alliance, chat, marches — goes through
`XLuaManager.SafeDoString` in the game's own process, and the daemon that drives it
answers on a TCP port. TCP is machine-wide, not session-bound, so a daemon in session 3
is reachable from session 1 exactly like a local one:

    session 1 (spame, console)          session 4 (casper, disconnected)
    ├─ LastWar.exe  ── daemon :47654    ├─ LastWar.exe  ── daemon :47655
    └─ this script  ────────────────────────── TCP ───────────┘

so any existing tool drives the second client with one environment variable:

    LW_DAEMON_PORT=47655 C:\Python312\python.exe tools\dispatch_tasks.py

Proven live: that command listed 181 dispatch tasks out of the second account while the
first client reported its own 209. The full write-up, with the traps, is in
docs/research/multi-instance-rdp.md.

How the session is built
------------------------
1. **The session.** If the target user has no session, one is created by connecting to
   this machine's own RDP listener with credentials taken from Credential Manager.
   Not to `localhost` — mstsc recognises its own machine and hangs up before the server
   sees anything; `127.0.0.2` is the same machine by another name and goes through.
2. **The client.** Started by `tools/session_launch.py` from a throwaway SYSTEM
   scheduled task: `WTSQueryUserToken(session)` hands over the token that already *is*
   that session's interactive logon, so the client runs as the session's own user, with
   that user's profile and install. That is what ACE wants and what #1105 could not
   give it. No password is involved and none is stored.
3. **The daemon.** Same route, one `lua_daemon.py --port <port>`, logging to
   `results/logs/`. It attaches to the client of its own session, so it cannot grab the
   other instance's and it survives a client restart.
4. **The session is left disconnected.** The RDP client is closed; a disconnected
   session keeps its desktop, its processes and its rendering device, and nothing here
   needs anyone to be looking at it.

> **The console.** This machine runs RDP Wrapper, so the console never moved in any run:
> both sessions stay connected. On a stock Windows client SKU step 1 takes the console
> away until the RDP client is closed, so `--bring-up` runs the whole sequence unattended
> and calls `tscon <console session> /dest:console` at the end (`--no-restore` opts out).
> If it ever dies in the middle, `--restore-console` puts the console back on its own.
>
> **Headless only.** Foreground input and screenshots reach the console desktop, never
> the second session. The second instance is driven through the Lua daemon or not at all.

Usage (Windows Python — pywin32 lives there, not in WSL's python3)::

    C:\Python312\python.exe tools\rdp_instance.py --status
    C:\Python312\python.exe tools\rdp_instance.py --bring-up            # the whole sequence
    C:\Python312\python.exe tools\rdp_instance.py --bring-up --no-rdp   # session already exists
    C:\Python312\python.exe tools\rdp_instance.py --ping
    C:\Python312\python.exe tools\rdp_instance.py --lua "print(1+1)"
    C:\Python312\python.exe tools\rdp_instance.py --restore-console
    C:\Python312\python.exe tools\rdp_instance.py --stop                # daemon + client, session stays
    C:\Python312\python.exe tools\rdp_instance.py --logoff              # end the session too

Elevation. Everything privileged goes through one silent UAC elevation (this machine's
`ConsentPromptBehaviorAdmin=0`) and, for the SYSTEM parts, a scheduled task that is
created, run and deleted in the same breath.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "lib"))

DEFAULT_USER = "casper"
DEFAULT_PORT = 47655
# NOT "localhost": mstsc recognises its own machine and hangs up before the server ever
# sees the connection (RDPClient event 1024 -> 1026 "reason 1800", nothing at all in the
# server logs). Any *other* address of the same machine goes through — 127.0.0.2 is the
# one that needs no adapter and no name resolution.
DEFAULT_SERVER = "127.0.0.2"
CRED_PREFIX = "LastWarVpBot"          # shared with tools/launch_as_user.py
RDP_CRED_TARGET = "TERMSRV/{server}"  # where mstsc looks for saved credentials

WIN = os.environ.get("SystemRoot", r"C:\Windows")
CMD = os.path.join(WIN, "System32", "cmd.exe")
POWERSHELL = os.path.join(WIN, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
MSTSC = os.path.join(WIN, "System32", "mstsc.exe")
PYTHON = sys.executable if sys.platform == "win32" else r"C:\Python312\python.exe"

WORK = os.path.join(tempfile.gettempdir(), "lwbot")
LOGDIR = os.path.join(REPO, "results", "logs")


def log(msg: str) -> None:
    print(f"[rdp] {msg}", flush=True)


# ------------------------------------------------------------ elevation/SYSTEM --

def _work_paths(tag: str) -> tuple[str, str, str]:
    os.makedirs(WORK, exist_ok=True)
    stem = os.path.join(WORK, f"{tag}-{os.getpid()}-{int(time.time() * 1000) % 100000}")
    return stem + ".cmd", stem + ".out", stem + ".done"


def _write_cmd(path: str, body: list[str], out: str, done: str) -> None:
    """A .cmd whose whole body is captured, with a marker file to say it finished."""
    # `exit`, not `exit /b`: a payload run by the scheduler has been seen to linger as a
    # session-0 cmd.exe otherwise, and one of those puts a 0xc0000142 box on the desktop.
    text = ["@echo off", f'if exist "{done}" del "{done}"',
            f'call :body > "{out}" 2>&1', f'echo EXIT:%ERRORLEVEL%>>"{out}"',
            f'type nul > "{done}"', "exit", ":body"] + body
    with open(path, "w", encoding="cp866", errors="replace") as fh:
        fh.write("\r\n".join(text) + "\r\n")


def _read_out(out: str) -> tuple[int, str]:
    try:
        with open(out, "r", encoding="cp866", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return -1, ""
    rc = -1
    for line in text.splitlines():
        if line.startswith("EXIT:"):
            try:
                rc = int(line[5:].strip())
            except ValueError:
                pass
    return rc, text


def run_elevated(body: list[str], tag: str = "elev", timeout: float = 180.0,
                 quiet: bool = False) -> tuple[int, str]:
    """Run cmd lines with a high-integrity token. Returns (exit code, output)."""
    script, out, done = _work_paths(tag)
    _write_cmd(script, body, out, done)
    ps = ("$ErrorActionPreference='Stop'; Start-Process -Verb RunAs -WindowStyle Hidden "
          f"-Wait -FilePath '{CMD}' -ArgumentList '/c','\"{script}\"'")
    proc = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", ps],
                          capture_output=True, timeout=timeout)
    deadline = time.time() + 15
    while not os.path.exists(done) and time.time() < deadline:
        time.sleep(0.2)
    rc, text = _read_out(out)
    if rc != 0 and not quiet:
        err = (proc.stderr or b"").decode("cp866", "replace").strip()
        log(f"elevated {tag} rc={rc} {err}")
    for p in (script, out, done):
        try:
            os.remove(p)
        except OSError:
            pass
    return rc, text


def run_as_system(body: list[str], tag: str = "sys", timeout: float = 300.0
                  ) -> tuple[int, str]:
    """Run cmd lines as SYSTEM, through a scheduled task that is deleted afterwards.

    SYSTEM is needed for exactly two things here: `WTSQueryUserToken` (starting a
    process inside another session) and `tscon` (moving a session to the console).
    """
    payload, out, done = _work_paths(tag + "-payload")
    _write_cmd(payload, body, out, done)
    task = f"LWBot-{tag}-{os.getpid()}"
    waits = int(max(4, timeout))
    driver = [
        f'schtasks /create /tn {task} /tr "cmd /c \\"{payload}\\"" /sc once '
        f'/st 00:00 /sd 01/01/2099 /ru SYSTEM /rl HIGHEST /f',
        f"schtasks /run /tn {task}",
        f'for /L %%i in (1,1,{waits}) do @(if not exist "{done}" ping -n 2 127.0.0.1 >nul)',
        f"schtasks /delete /tn {task} /f",
    ]
    rc_drv, drv_text = run_elevated(driver, tag=tag + "-driver", timeout=timeout + 60)
    rc, text = _read_out(out)
    if rc == -1 and not os.path.exists(done):
        log(f"SYSTEM task {task} produced nothing (driver rc={rc_drv}):\n{drv_text}")
    for p in (payload, out, done):
        try:
            os.remove(p)
        except OSError:
            pass
    return rc, text


def system_python(args: list[str], tag: str, cwd: str = REPO,
                  timeout: float = 300.0) -> tuple[int, str]:
    """Run one of this repo's tools as SYSTEM."""
    line = f'"{PYTHON}" ' + " ".join(f'"{a}"' if " " in a else a for a in args)
    return run_as_system([f'cd /d "{cwd}"', line], tag=tag, timeout=timeout)


# ---------------------------------------------------------------- inspection --

def sessions() -> list[dict]:
    import session_launch  # noqa: PLC0415 — Windows-only import, keeps --help portable
    return session_launch.sessions()


def session_of(user: str) -> dict | None:
    for s in sessions():
        if s["user"].lower() == user.lower():
            return s
    return None


def console_session() -> int:
    """The session that should own the console — this one, whoever is running us."""
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    sid = ctypes.c_ulong()
    k32.ProcessIdToSessionId(k32.GetCurrentProcessId(), ctypes.byref(sid))
    return int(sid.value)


def clients() -> list[dict]:
    """Every LastWar.exe with its session and owner.

    Through `WTSEnumerateProcesses`, not `ProcessIdToSessionId`: the latter needs query
    rights on the process, so another user's client comes back as "session 0" — which
    reads as a service and is exactly the process we are looking for.
    """
    import psutil
    import win32ts
    by_session = {s["id"]: s["user"] for s in sessions()}
    out = []
    for session, pid, name, _sid in win32ts.WTSEnumerateProcesses(0, 1, 0):
        # Exactly the client: LastWarLauncher.exe and LastWarSync.exe also start with
        # "lastwar", and pinning the daemon to the launcher gets a daemon that never warms.
        if (name or "").lower() != "lastwar.exe":
            continue
        # The SID that comes back for another user's process is not a usable PySID here;
        # the session's logged-on user is the same answer and always available.
        who = by_session.get(int(session)) or "?"
        try:
            age = int(time.time() - psutil.Process(pid).create_time())
        except Exception:  # noqa: BLE001
            age = -1
        out.append({"pid": pid, "session": int(session), "user": who, "age": age})
    return out


def client_in(session: int) -> dict | None:
    for c in clients():
        if c["session"] == session:
            return c
    return None


def daemon_rpc(req: dict, port: int, timeout: float = 30.0) -> dict:
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode("utf-8", "replace").splitlines()[0])
    finally:
        s.close()


def daemon_state(port: int) -> dict:
    try:
        return daemon_rpc({"op": "ping"}, port, timeout=5)
    except (OSError, ValueError, IndexError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def status(user: str, port: int) -> dict:
    st = {"sessions": sessions(), "clients": clients(),
          "console_session": console_session(),
          "target_user": user, "port": port,
          "target_session": session_of(user), "daemon": daemon_state(port)}
    log(f"console session: {st['console_session']}")
    for s in st["sessions"]:
        mark = " <= target" if s["user"].lower() == user.lower() else ""
        log(f"  session {s['id']:>5}  {s['state']:<13} {s['station']:<10} "
            f"{s['user'] or '-'}{mark}")
    for c in st["clients"]:
        log(f"  client pid {c['pid']:>7}  session {c['session']}  {c['user']}  "
            f"up {c['age']}s")
    d = st["daemon"]
    log(f"  daemon :{port} -> " + ("warm" if d.get("warm") else
                                   "up but cold" if d.get("ok") else
                                   f"down ({d.get('error', '')})"))
    return st


# ------------------------------------------------------------------ the RDP --

def rdp_credential(user: str, server: str) -> str:
    """Copy the stored account password into the credential mstsc reads. Returns target."""
    import win32cred
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import launch_as_user as LAU
    dom, name, _sid = LAU.resolve_account(user, None)
    password = LAU.cred_read(dom, name)
    if password is None:
        raise SystemExit(
            f"no stored password for {dom}\\{name}. Save it once:\n"
            rf"    C:\Python312\python.exe tools\launch_as_user.py --user {name} "
            "--save-credential")
    target = RDP_CRED_TARGET.format(server=server)
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": target,
        "UserName": f"{dom}\\{name}",
        "CredentialBlob": password,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": "last-war-vp-bot second instance over RDP (#1106)",
    }, 0)
    log(f"credential {target} set for {dom}\\{name}")
    return f"{dom}\\{name}"


def rdp_file(user_qualified: str, server: str, width: int, height: int) -> str:
    """A .rdp that connects without asking anything — no cert prompt, no credential box."""
    path = os.path.join(WORK, f"{user_qualified.split(chr(92))[-1]}.rdp")
    os.makedirs(WORK, exist_ok=True)
    body = [
        f"full address:s:{server}",
        f"username:s:{user_qualified}",
        "prompt for credentials:i:0",
        "promptcredentialonce:i:1",
        "authentication level:i:0",     # do not stop on the self-signed host cert
        "enablecredsspsupport:i:1",
        "screen mode id:i:1",           # windowed: the console stays usable
        f"desktopwidth:i:{width}",
        f"desktopheight:i:{height}",
        "session bpp:i:32",
        "smart sizing:i:1",
        "audiomode:i:2",                # no audio redirection
        "redirectclipboard:i:0",
        "redirectprinters:i:0",
        "redirectcomports:i:0",
        "redirectsmartcards:i:0",
        "drivestoredirect:s:",
        "autoreconnection enabled:i:1",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\r\n".join(body) + "\r\n")
    return path


# mstsc asks two questions on the way in, and both have to be answered without a human:
# the .rdp file is unsigned ("cannot identify the publisher"), and on a client SKU the
# console user is about to be kicked off ("another user is signed in"). `allow_unsigned`
# removes the first for good; the clicker below is the belt-and-braces for both.
AFFIRMATIVE = ("подключить", "connect", "да", "yes", "ок", "ok")
CHECKBOX_HINTS = ("больше не выводить", "don't ask me again", "do not ask me again")


def allow_unsigned_rdp() -> None:
    """Policy: .rdp files from unknown publishers open without a prompt."""
    key = r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services"
    run_elevated([f'reg add "{key}" /v AllowUnsignedFiles /t REG_DWORD /d 1 /f',
                  f'reg add "{key}" /v TrustedCertThumbprints /t REG_SZ /d "" /f'],
                 tag="rdppolicy", timeout=60, quiet=True)


def click_dialogs(seconds: float = 120.0, process: str = "mstsc.exe") -> None:
    """Tick 'do not ask again' and press the affirmative button on `process` dialogs.

    Runs in a thread while the connection is being made. Standard dialog buttons take
    BM_CLICK from another process, so this needs no foreground input and does not fight
    with whatever the bot is doing on the desktop.
    """
    import win32con
    import win32gui
    import win32process
    import psutil
    deadline = time.time() + seconds
    seen = set()
    while time.time() < deadline:
        pids = {p.pid for p in psutil.process_iter(["name"])
                if (p.info["name"] or "").lower() == process}
        if not pids:
            time.sleep(0.5)
            continue
        dialogs = []

        def collect(hwnd, acc):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in pids and win32gui.GetClassName(hwnd) == "#32770":
                acc.append(hwnd)
            return True

        win32gui.EnumWindows(collect, dialogs)
        for dlg in dialogs:
            buttons = []
            win32gui.EnumChildWindows(dlg, lambda h, a: a.append(h) or True, buttons)
            target = None
            for h in buttons:
                if win32gui.GetClassName(h) != "Button":
                    continue
                text = win32gui.GetWindowText(h).replace("&", "").strip().lower()
                if any(hint in text for hint in CHECKBOX_HINTS) and h not in seen:
                    win32gui.SendMessage(h, win32con.BM_CLICK, 0, 0)
                    seen.add(h)
                elif text in AFFIRMATIVE and target is None:
                    target = (h, text)
            if target and target[0] not in seen:
                log(f"dialog «{win32gui.GetWindowText(dlg)}» -> «{target[1]}»")
                win32gui.SendMessage(target[0], win32con.BM_CLICK, 0, 0)
                seen.add(target[0])
        time.sleep(0.7)


def rdp_connect(user: str, server: str = DEFAULT_SERVER, width: int = 1600, height: int = 900,
                wait: float = 180.0) -> dict:
    """Create a session for `user` by connecting to this machine's own RDP listener."""
    qualified = rdp_credential(user, server)
    allow_unsigned_rdp()
    path = rdp_file(qualified, server, width, height)
    log(f"mstsc {server} as {qualified} — the console goes away until --restore-console")
    import threading
    threading.Thread(target=click_dialogs, args=(wait,), daemon=True).start()
    subprocess.Popen([MSTSC, path], close_fds=True)
    deadline = time.time() + wait
    while time.time() < deadline:
        s = session_of(user)
        if s and s["state"] in ("active", "connected"):
            log(f"session {s['id']} up for {user} ({s['state']})")
            return s
        time.sleep(2)
    raise SystemExit(f"no session for {user} after {wait:.0f}s — is mstsc showing a "
                     f"dialog? Check with --status")


def kill_mstsc() -> None:
    subprocess.run([os.path.join(WIN, "System32", "taskkill.exe"), "/F", "/IM",
                    "mstsc.exe"], capture_output=True)


def restore_console(target: int | None = None) -> bool:
    """Put `target` (default: our own session) back on the physical console."""
    target = console_session() if target is None else target
    for s in sessions():
        # tscon answers 7045 ("access denied") for a session that is already there,
        # which reads like a permission problem and is not one.
        if s["id"] == target and s["station"].lower() == "console" and s["state"] == "active":
            log(f"session {target} already owns the console")
            return True
    rc, text = run_as_system([f"tscon {target} /dest:console"], tag="tscon", timeout=60)
    ok = rc == 0
    log(f"tscon {target} /dest:console -> {'ok' if ok else 'FAILED'}: "
        f"{' '.join(text.split())[:200]}")
    return ok


# ------------------------------------------------------------------ bring-up --

def start_client(session: int, timeout: float = 300.0) -> dict:
    existing = client_in(session)
    if existing:
        log(f"client already in session {session}: pid {existing['pid']}")
        return existing
    rc, text = system_python(["tools\\session_launch.py", "--session", str(session),
                              "--game"], tag="game", timeout=120)
    log(f"launcher start rc={rc}: {' '.join(text.split())[:300]}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        c = client_in(session)
        if c:
            log(f"client pid {c['pid']} in session {session}")
            return c
        time.sleep(3)
    raise SystemExit(f"no LastWar.exe in session {session} after {timeout:.0f}s "
                     f"(the launcher may still be updating — retry --bring-up)")


def daemon_script(session: int, port: int) -> str:
    """The .cmd the second session runs: our daemon on that session's own port.

    No `--pid`: the daemon picks the client of the session it runs in
    (`il2cpp_probe.find_game_pid`), so it survives a client restart inside that session.
    """
    os.makedirs(LOGDIR, exist_ok=True)
    log_path = os.path.join(LOGDIR, f"lua_daemon_{port}.log")
    # Under the repo, not under %TEMP%: this one is read by the *other* user, and one
    # profile's temp directory is unreadable from another account (cmd.exe then dies with
    # 0xc0000142 and leaves nothing behind to explain itself).
    path = os.path.join(LOGDIR, f"daemon-{port}.cmd")
    with open(path, "w", encoding="cp866", errors="replace") as fh:
        fh.write("\r\n".join([
            "@echo off",
            f'cd /d "{REPO}"',
            f'"{PYTHON}" tools\\lua_daemon.py --port {port} >> "{log_path}" 2>&1',
        ]) + "\r\n")
    return path


def start_daemon(session: int, port: int, timeout: float = 120.0,
                 say=None) -> bool:
    """Bring this repo's Lua daemon up INSIDE ``session``, on ``port``.

    ``say`` is where the running commentary goes. It defaults to this tool's
    own stdout, which is right for a command line and useless to the panel:
    a windowed panel has no console, so a caller that wants these lines in
    its log hands one in (panel/runtime/daemon.py does).
    """
    log = say or globals()["log"]
    if daemon_state(port).get("ok"):
        log(f"daemon already listening on {port}")
    else:
        script = daemon_script(session, port)
        rc, text = system_python(["tools\\session_launch.py", "--session", str(session),
                                  "--script", script, "--cwd", REPO, "--hidden"],
                                 tag="daemon", timeout=120)
        log(f"daemon start rc={rc}: {' '.join(text.split())[:300]}")
        deadline = time.time() + timeout
        while time.time() < deadline and not daemon_state(port).get("ok"):
            time.sleep(2)
    st = daemon_state(port)
    if not st.get("ok"):
        log(f"daemon on {port} did not come up: {st.get('error')}")
        return False
    if not st.get("warm"):
        log("daemon up but cold — the client was probably still loading; reloading")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if daemon_rpc({"op": "reload"}, port, timeout=90).get("warm"):
                    break
            except OSError:
                pass
            time.sleep(5)
    st = daemon_state(port)
    log(f"daemon :{port} {'warm' if st.get('warm') else 'still cold'}")
    return bool(st.get("warm"))


def bring_up(user: str, port: int, server: str, width: int, height: int,
             use_rdp: bool = True, restore: bool = True) -> int:
    s = session_of(user)
    if s:
        log(f"session {s['id']} for {user} already exists ({s['state']})")
    elif not use_rdp:
        log(f"no session for {user} and --no-rdp given — nothing to do")
        return 2
    # Everything from the connect onwards is inside the try: once the RDP client is
    # started this session may lose the console, and it has to get it back even if the
    # sequence blows up half way through.
    warm = False
    try:
        if s is None:
            s = rdp_connect(user, server, width, height)
        client = start_client(s["id"])
        log(f"client pid {client['pid']} in session {s['id']}")
        warm = start_daemon(s["id"], port)
    finally:
        if restore:
            kill_mstsc()
            restore_console()
    time.sleep(2)
    status(user, port)
    if not warm:
        return 1
    lines = daemon_rpc({"op": "run", "chunk": SMOKE_CHUNK, "marker": "RDPINST",
                        "settle": 1.5}, port, timeout=60).get("lines", [])
    for ln in lines:
        log(f"smoke: {ln}")
    return 0 if lines else 1


# Scene name alone proves nothing — it stays "Launch" in a fully loaded client, in both
# instances. The root-object count does: a client sitting on the splash has a handful,
# one that is in the game has the city (or the world) hanging off the same scene.
SMOKE_CHUNK = (
    "local sc = CS.UnityEngine.SceneManagement.SceneManager.GetActiveScene() "
    "CS.UnityEngine.Debug.LogError('RDPINST alive scene='..tostring(sc.name)"
    "..' roots='..tostring(sc:GetRootGameObjects().Length))"
)


# ---------------------------------------------------------------- tear-down --

def stop(user: str, port: int, logoff: bool = False) -> int:
    s = session_of(user)
    if not s:
        log(f"no session for {user}")
        return 0
    try:
        daemon_rpc({"op": "shutdown"}, port, timeout=10)
        log(f"daemon :{port} shut down")
    except OSError:
        log(f"daemon :{port} was not answering")
    c = client_in(s["id"])
    if c:
        rc, _ = run_elevated([f'taskkill /F /PID {c["pid"]}'], tag="killgame", timeout=60)
        log(f"client pid {c['pid']} killed (rc={rc})")
    if logoff:
        rc, text = run_as_system([f"logoff {s['id']}"], tag="logoff", timeout=60)
        log(f"session {s['id']} logged off (rc={rc}) {' '.join(text.split())[:120]}")
    return 0


# --------------------------------------------------------------------- main --

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", default=DEFAULT_USER, help="the second client's Windows user")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="its Lua daemon port")
    ap.add_argument("--server", default=DEFAULT_SERVER,
                    help=f"RDP target — this machine by another loopback address "
                         f"(default {DEFAULT_SERVER}; see the note above)")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--status", action="store_true", help="sessions, clients, daemon")
    ap.add_argument("--bring-up", action="store_true",
                    help="session -> client -> daemon -> console back")
    ap.add_argument("--no-rdp", action="store_true",
                    help="never create a session; use an existing one only")
    ap.add_argument("--no-restore", action="store_true",
                    help="leave the console with the other session (debugging)")
    ap.add_argument("--restore-console", action="store_true",
                    help="re-attach this session to the physical console")
    ap.add_argument("--ping", action="store_true", help="is the second daemon warm?")
    ap.add_argument("--lua", help="run a Lua chunk in the second client")
    ap.add_argument("--marker", default="RDPINST", help="log marker for --lua")
    ap.add_argument("--stop", action="store_true", help="stop daemon + client")
    ap.add_argument("--logoff", action="store_true", help="…and log the session off")
    a = ap.parse_args()

    if sys.platform != "win32":
        raise SystemExit(r"run under the Windows Python: C:\Python312\python.exe "
                         r"tools\rdp_instance.py --status")

    if a.restore_console:
        return 0 if restore_console() else 1
    if a.stop or a.logoff:
        return stop(a.user, a.port, logoff=a.logoff)
    if a.lua:
        r = daemon_rpc({"op": "run", "chunk": a.lua, "marker": a.marker, "settle": 1.5},
                       a.port, timeout=90)
        if not r.get("ok"):
            log(f"error: {r.get('error')}")
            return 1
        for ln in r.get("lines", []):
            print(ln)
        return 0
    if a.ping:
        st = daemon_state(a.port)
        log(f"daemon :{a.port} {st}")
        return 0 if st.get("warm") else 1
    if a.bring_up:
        return bring_up(a.user, a.port, a.server, a.width, a.height,
                        use_rdp=not a.no_rdp, restore=not a.no_restore)
    status(a.user, a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
