r"""Which game client this profile drives, and how to start and close it.

Everything else in the bot only ever needs the client to be *up*. A restart needs the
opposite half: which process to end, and whether it really went away. That is not the
same question as "is a LastWar.exe running", and answering it by process name is how a
two-account box loses the wrong client — one Windows session per client
(docs/research/multi-instance-rdp.md), and `taskkill /IM LastWar.exe` ends both.

Starting one has the same trap the other way round. A launcher spawned from here lands
on THIS desktop, so a profile whose client lives in another Windows session would get a
third client in front of whoever is using the machine while its own account went on
farming nothing. :func:`start` is the half that knows the difference.

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
import game_paths  # noqa: E402
import lua_client  # noqa: E402
import proc_table  # noqa: E402

#: The client executable. A profile may name another one (an install somewhere else),
#: which is why the process-name fallbacks take it as a parameter — and why the default
#: is `LW_GAME_EXE`'s answer rather than a literal (tools/lib/game_paths.py).
GAME_EXE = game_paths.game_exe()

#: How long a closed client is given to actually disappear. TerminateProcess is not
#: instant — the Unity process unwinds its own handles first — and starting the
#: launcher over a client that is still exiting is how a relaunch ends up with no
#: window at all.
CLOSE_TIMEOUT_SEC = 30.0

#: How long a launch into another session waits for the client to appear. Generous on
#: purpose: a cold start behind a launcher update is minutes, and the alternative to
#: waiting is reporting a failure over a client that is on its way up.
START_TIMEOUT_SEC = 300.0

#: How long the SYSTEM hop itself is given — the scheduled task, not the game. It
#: returns as soon as `CreateProcessAsUser` has, so this only ever fires when the
#: elevation never happened at all.
SYSTEM_HOP_TIMEOUT_SEC = 180.0

#: How often the wait below looks for the new client.
_POLL_SEC = 3.0

# Windows: no console window for the taskkill fallback.
_NO_WINDOW = 0x08000000


def default_launcher() -> str:
    """The launcher on THIS desktop — `LW_LAUNCHER`, or the ordinary install.

    Resolved on every call rather than frozen at import, so setting the variable and
    running is enough. THIS desktop's, and only this desktop's: a second account's
    launcher is resolved inside that account's session, not here.
    """
    return game_paths.launcher()


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
    """The client of THIS Windows session — never another session's.

    ``LW_GAME_PID`` still wins, because that is somebody saying which client they
    mean. What is deliberately NOT here is `find_game_pid`'s last resort, "any
    client at all": that fallback is right for a reader (better the wrong client
    than no client) and catastrophic for a restart, which does not read a process
    but ENDS it. Proven the hard way — with the client of this session killed, the
    ordinary lookup answered with the second account's client, running in another
    Windows session. One more step down that path is a closed session for an
    account nobody asked about.

    A process this token cannot open its session id for is not ours: being unable
    to ask is itself the answer, and it is the answer a foreign session gives.
    """
    forced = os.environ.get("LW_GAME_PID")
    if forced:
        try:
            pid = int(forced)
        except (TypeError, ValueError):
            return None
        return pid if alive(pid) else None
    pids = session_pids(game_exe)
    return pids[0] if pids else None


def session_pids(game_exe: str = GAME_EXE) -> list:
    """Every client running in the caller's own Windows session (usually one).

    The names come from `tools/lib/proc_table.py` — one enumeration that opens nothing —
    and only the processes that ARE clients are then asked which session they sit in.
    Walking them with `psutil.process_iter` opened a handle per process and cost four
    seconds of held interpreter lock, which starves the panel's window for as long as it
    runs (docs/research/panel-freezes.md §1); this runs in the panel's process, on a
    background thread, at every restart and every force-close (#1214).
    """
    probe, mine = None, None
    try:
        # The one implementation of the session lookup in the repo — a ctypes call
        # around ProcessIdToSessionId. Duplicating it here would be a second thing
        # to keep right.
        import il2cpp_probe as probe        # noqa: PLC0415
        mine = probe._session_of(os.getpid())
    except Exception:                        # noqa: BLE001 — not Windows: no sessions
        probe = None
    out = []
    for pid in proc_table.pids_named(game_exe):
        if probe is None:                    # nothing to filter by — every client is ours
            out.append(pid)
            continue
        try:
            if probe._session_of(pid) == mine:
                out.append(pid)
        except Exception:                    # noqa: BLE001 — cannot ask ⇒ not ours
            continue
    return out


def target_pid(port: "int | None" = None, game_exe: str = GAME_EXE,
               user: "str | None" = None, log=None) -> "int | None":
    """The client this profile drives: the daemon's, or the ordinary reading.

    ``user`` names the Windows session the client lives in, and it makes this function
    strictly narrower rather than wider — which is the point, because the caller that
    needs it most is a force-close.

    Without it, both routes answer with THIS desktop's client whenever the profile's
    own is not found: `running_pid` is documented as "the client of this session", and
    for a profile whose client is in session 4 this session's client is the NEIGHBOUR'S.
    A restart would then end the game in front of the person.

    The daemon's own attachment is checked against the session for the same reason, and
    it is not a theoretical worry: a daemon started on the wrong desktop binds the right
    port and hijacks the wrong client (that is what `GameLink` had to be taught, #1218).
    Its answer is believed only when the process it names really is in the session this
    profile plays in; otherwise it is ignored and said out loud, because a port pointing
    at another session's game is a fault, not a fallback.
    """
    say = log or (lambda _msg: None)
    if not user:
        return attached_pid(port) or running_pid(game_exe)

    session = session_of(user)
    if session is None:
        say(f"nobody is logged on as {user} — no client of this profile's to find")
        return None
    here = session_pids_of(session, game_exe)
    attached = attached_pid(port)
    if attached is not None and attached not in here:
        say(f"the daemon on port {port} is attached to pid {attached}, which is NOT in "
            f"{user}'s session — ignoring it")
        attached = None
    return attached or (here[0] if here else None)


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


def close(pid: int, timeout: float = CLOSE_TIMEOUT_SEC, user: "str | None" = None,
          log=None) -> bool:
    """End the client at ``pid`` and wait for it to go. ``True`` once it has.

    Force, not a polite close: the point of a scheduled restart is to end a client
    that may well be wedged behind a modal, and a WM_CLOSE it is not answering would
    turn the errand into a five-minute wait for nothing.

    ``user`` names the Windows session the client lives in, and it exists because a
    client in ANOTHER account's session is not this process's to terminate: an
    unelevated panel gets ACCESS_DENIED out of `OpenProcess(PROCESS_TERMINATE)`,
    measured, not assumed. So that case is retried through one elevated `taskkill`,
    which is the smallest privilege that does the job — a restart needs a high-integrity
    token, not SYSTEM (which is what starting a process inside a session needs, and is
    the heavier hop of the two).

    The fallback is gated on a session being NAMED rather than tried on any refusal:
    a profile on this desktop that cannot kill its own client has something else wrong,
    and a surprise elevation prompt is not the way to find out.
    """
    say = log or (lambda _msg: None)
    pid = int(pid)
    if not alive(pid):
        return True
    if _close_here(pid, timeout, say):
        return True
    if not user:
        return False
    say(f"pid {pid} belongs to {user}'s session — ending it with an elevated taskkill")
    return _close_elevated(pid, timeout, say)


def _close_here(pid: int, timeout: float, say) -> bool:
    """Terminate ``pid`` with the rights this process already has."""
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
    except psutil.AccessDenied:
        # Not a failure to report yet: another account owns it, and there is a
        # bigger hammer. Said out loud because it is the one interesting step.
        say(f"pid {pid} refused TerminateProcess — another account owns it")
        return False
    except Exception:                        # noqa: BLE001 — gone between the two lines
        pass
    return wait_gone(pid, timeout)


def _close_elevated(pid: int, timeout: float, say) -> bool:
    """Terminate ``pid`` through one silent elevation. By PID — never an image name."""
    _tools_on_path()
    import rdp_instance                      # noqa: PLC0415 — Windows-only

    rc, text = rdp_instance.run_elevated([f"taskkill /F /PID {pid}"], tag="quit",
                                         timeout=max(60.0, float(timeout)))
    say(f"taskkill rc={rc}: {' '.join(text.split())[:200]}")
    return wait_gone(pid, timeout)


def wait_gone(pid: "int | None", timeout: float = CLOSE_TIMEOUT_SEC) -> bool:
    """Wait until ``pid`` is not running any more. ``True`` if it went."""
    deadline = time.time() + float(timeout)
    while alive(pid):
        if time.time() >= deadline:
            return False
        time.sleep(0.5)
    return True


# -- starting it -------------------------------------------------------------
#
# Two routes, and the profile picks which by naming a Windows session or not:
#
#   * **No session named — this desktop.** `subprocess.Popen`, exactly what the DSL's
#     `LAUNCH` has always done, and what every single-account box keeps doing.
#   * **A session named — that session,** through `tools/session_launch.py`, which
#     starts the launcher under the token that is ALREADY that session's interactive
#     logon. That is the only arrangement the game's anti-cheat lets a second client
#     live in (docs/research/multi-instance-rdp.md): process user and session owner are
#     the same account, the launch is merely issued from outside. `WTSQueryUserToken`
#     needs SeTcbPrivilege, so the call goes through the SYSTEM hop
#     `tools/rdp_instance.py` already owns — one silent elevation and a throwaway
#     scheduled task, the same route `--bring-up` takes.
#
# The wait afterwards is for the CLIENT, not the launcher: what `session_launch` starts
# is `LastWarLauncher.exe`, which updates itself, then the game, and only then spawns
# `LastWar.exe`. Returning at the launcher would report a start that has not happened.


def _tools_on_path() -> None:
    """Put `tools/` on `sys.path` — `tools/lib` is already there (see the top)."""
    tools = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if tools not in sys.path:
        sys.path.insert(0, tools)


def session_of(user: str) -> "int | None":
    """The id of the Windows session ``user`` is logged on to, or ``None``.

    ``None`` is "nobody by that name is logged on" — which is a state to say out loud
    rather than to launch into: the session has to exist before anything can be started
    inside it (`tools/rdp_instance.py --bring-up` makes one).
    """
    _tools_on_path()
    import session_launch                     # noqa: PLC0415 — Windows-only
    want = str(user).strip().lower()
    for sess in session_launch.sessions():
        if (sess.get("user") or "").strip().lower() == want:
            return int(sess["id"])
    return None


def session_pids_of(session: int, game_exe: str = GAME_EXE) -> list:
    """Every client inside one Windows session — another user's included.

    `WTSEnumerateProcesses` — through `proc_table.wts_rows`, the one spelling of it —
    rather than `ProcessIdToSessionId`, for the reason tools/rdp_instance.py records:
    the latter needs query rights on the process, so a foreign user's client comes back
    as "session 0", which reads as a service and is exactly the process being looked
    for. (`session_pids` above is the other half of the same question, asked about OUR
    session, which is the one a ctypes call can answer.)
    """
    return [pid for sid, pid, name in proc_table.wts_rows()
            if sid == int(session) and (name or "").lower() == game_exe.lower()]


# There WAS a `_shared_path()` here, and it was the wrong shape of answer. It asked
# "does this path mean the same file in any session?" and threw away everything that
# did not — so a per-user launcher was silently replaced by the default install, and
# an account could only be given a custom path in absolute form. The path is not ours
# to judge: it is expanded in the session that will run it, where its variables are
# correct (`tools/session_launch.py::expand_for`), and here it is passed on untouched.


def start(launcher: "str | None" = None, user: "str | None" = None,
          timeout: float = START_TIMEOUT_SEC, game_exe: str = GAME_EXE,
          log=None) -> "int | None":
    """Start the client this profile drives. The client's pid when it can be known.

    ``user`` is the login of the Windows session the client lives in; ``None`` means
    this desktop, where nothing is waited for — the launcher is fire-and-forget and the
    caller's own readiness test (`WAIT scene == city`) is what says the base is up.

    Raises ``FileNotFoundError`` when the launcher is not where the path says (a
    configuration mistake, not a condition to retry), ``LookupError`` when nobody is
    logged on as ``user``, and ``TimeoutError`` when the client never appeared.
    """
    say = log or (lambda _msg: None)
    if user and str(user).strip():
        return _start_in_session(str(user).strip(), launcher, timeout, game_exe, say)
    _start_here(launcher or default_launcher(), say)
    return None


def _start_here(launcher: str, say) -> None:
    """The single-account case, unchanged: spawn the launcher as a detached child."""
    path = os.path.expanduser(os.path.expandvars(launcher))
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    subprocess.Popen([path], cwd=os.path.dirname(path) or None, close_fds=True)
    say(f"launcher started on this desktop: {path}")


def _start_in_session(user: str, launcher: "str | None", timeout: float,
                      game_exe: str, say) -> int:
    session = session_of(user)
    if session is None:
        # There is nothing to start a client INSIDE. Creating the session is a
        # different and much heavier act — an RDP connection, saved credentials, and
        # the console changing hands while it happens — so this names the one command
        # that does it rather than doing it behind a «Запустить игру» press. A
        # DISCONNECTED session is not this case: it is a working session with a
        # desktop of its own, and the launch below goes into it unchanged.
        raise LookupError(
            f"nobody is logged on as {user} — bring the session up first: "
            f"tools\\rdp_instance.py --bring-up --user {user}")
    found = session_pids_of(session, game_exe)
    if found:
        # Not an error and not a second launch: the recipe's job is to get to "the
        # client is up", and finding it already there is that job done.
        say(f"a client is already running in {user}'s session (pid {found[0]})")
        return found[0]

    _tools_on_path()
    import rdp_instance                       # noqa: PLC0415 — Windows-only

    # WHICH launcher, said in a form that survives the trip. The hop below runs as
    # SYSTEM out of a scheduled task and inherits NOTHING from here — not the
    # environment, not the caller's account — so anything the answer depends on travels
    # on the command line or does not travel at all.
    #
    # A configured path goes VERBATIM, unexpanded. `%LOCALAPPDATA%` in it belongs to the
    # account that will run the game, not to us: expanding it here would name the PANEL
    # user's folder and hand that to the other account's token. `session_launch` expands
    # it against the target session's own environment block, which is the one place on
    # the machine where those variables are right.
    raw = (launcher or os.environ.get("LW_LAUNCHER") or "").strip() or None
    args = ["tools\\session_launch.py", "--session", str(session)]
    if raw:
        args += ["--exe", raw]
    else:
        # Nothing configured, which is the case that has to work by itself: the account
        # is named, so its profile directory is a registry lookup on the far side and
        # the rest is the ordinary install. Adding a second account is a tick and a
        # login, never a path typed by hand.
        args += ["--game",
                 "--game-folder", game_paths.game_folder(),
                 "--launcher-exe", game_paths.launcher_exe()]
    say(f"starting the launcher in {user}'s session ({session}) through SYSTEM")
    rc, text = rdp_instance.system_python(args, tag="game",
                                          timeout=SYSTEM_HOP_TIMEOUT_SEC)
    say(f"session_launch rc={rc}: {' '.join(text.split())[-200:]}")

    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        found = session_pids_of(session, game_exe)
        if found:
            say(f"client pid {found[0]} in {user}'s session")
            return found[0]
        time.sleep(_POLL_SEC)
    raise TimeoutError(f"no client in {user}'s session after {timeout:.0f}s "
                       f"(the launcher may still be updating)")


# -- fallbacks ---------------------------------------------------------------

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
