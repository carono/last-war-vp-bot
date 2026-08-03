"""Is the client running, and what is it talking to?

A `psutil` probe, no Tk and no game link — the panel's status strip asks it, and so does
the ghost-recon watcher before it spends a robbery on a client that is not there. It was
`panel/__main__.py`'s `game_status`; a tab launched on its own cannot import that file
(``python -m panel`` runs it AS ``__main__``), which is the whole reason this package
exists.

**Which client, though.** A second account runs in its own Windows session
(tools/rdp_instance.py), and by process name alone the two are indistinguishable: the
panel driving the second one over `daemon_port` would report the FIRST one's client as
"running" and never notice its own being gone. So a profile may name the session its
client lives in — the login of the user logged on to it — and every probe below then
counts only the clients inside that session.

**Every answer names itself.** What comes back is shown in the status strip, so it is a
:class:`panel.i18n.Message`: the English sentence and its locale key in one value. This
module has no translator and must not grow one (the very same reason `panel/profile.py`
gives), and «no session for casper» in a Russian panel is the message not being
translated at all.
"""
from __future__ import annotations

from ..i18n import Message

#: The default client executable. A profile may name another one — a second client in
#: its own Windows session, or an install somewhere else — so every caller passes it.
GAME_EXE = "LastWar.exe"

_NON_GAME_PORTS = frozenset({80, 443})

#: The two session states worth a word of their own. A *disconnected* session is a fully
#: working one — that is how the second client is meant to be left (docs/research/
#: multi-instance-rdp.md §3.3) — so it must not read as a fault; anything else is rare
#: enough to be shown as its raw code rather than translated into eight more keys.
WTS_ACTIVE = 0
WTS_DISCONNECTED = 4


# -- which Windows session ---------------------------------------------------

def profile_user(settings) -> str | None:
    """The login of the session this profile's client lives in, or ``None`` for ours.

    The pair of knobs is read in exactly one place: the login means nothing while
    «игра в RDP-сессии» is off, and a caller that reads only one of the two would
    aim the probe at the wrong session the moment the tick is taken off.
    """
    try:
        if not settings.opt_bool("rdp_session"):
            return None
        return settings.opt_str("rdp_user").strip() or None
    except Exception:                    # noqa: BLE001 — a half-typed knob, not a crash
        return None


def sessions() -> "list | None":
    """Every Windows session with its login and state, or ``None`` if it cannot be asked.

    ``None`` is not "no sessions": it is "this machine has no answer" — pywin32 missing,
    or not Windows at all. The two are told apart because they want opposite things said
    to the person, and folding them together is how a panel ends up looking in the wrong
    session in silence.
    """
    try:
        import win32ts
        found = []
        for sess in win32ts.WTSEnumerateSessions():
            sid = sess["SessionId"]
            try:
                who = win32ts.WTSQuerySessionInformation(0, sid, win32ts.WTSUserName)
            except Exception:            # noqa: BLE001 — access denied on a foreign one
                who = ""
            found.append({"id": int(sid), "user": (who or "").strip(),
                          "state": int(sess.get("State", -1))})
        return found
    except Exception:                    # noqa: BLE001
        return None


def session_info(user: str) -> "dict | None":
    """The session ``user`` is logged on to — ``{id, user, state}`` — or ``None``."""
    for sess in sessions() or ():
        if sess["user"].lower() == user.strip().lower():
            return sess
    return None


def session_of(user: str) -> int | None:
    """The id of the Windows session ``user`` is logged on to, or ``None``.

    ``None`` covers both "nobody by that name is logged on" and "this machine cannot
    be asked". Neither is the same as "the game is not running", which is why the
    callers say so in their own words rather than folding it into a plain "not found".
    """
    found = session_info(user)
    return None if found is None else found["id"]


def _pids_by_name(game_exe: str) -> list[int]:
    """Every process called ``game_exe``, whatever session it sits in."""
    import psutil
    return [p.info["pid"] for p in psutil.process_iter(["pid", "name"])
            if (p.info["name"] or "").lower() == game_exe.lower()]


def own_session() -> int | None:
    """The Windows session THIS process is in, or ``None`` if it cannot be asked.

    ``None`` on anything that is not Windows-with-pywin32, which is what keeps the
    fallback in :func:`pids` honest rather than silent. Asked about our OWN pid, so
    `ProcessIdToSessionId` is enough — the query-rights problem `_pids_in_session`
    documents only bites on somebody else's process.
    """
    try:
        import os

        import win32ts
        return int(win32ts.ProcessIdToSessionId(os.getpid()))
    except Exception:                    # noqa: BLE001 — not Windows, or no pywin32
        return None


def _pids_in_session(game_exe: str, session: int) -> list[int]:
    """The clients inside one Windows session.

    Through `WTSEnumerateProcesses`, not `ProcessIdToSessionId`: the latter needs query
    rights on the process, so another user's client comes back as "session 0" — which
    reads as a service and is exactly the process being looked for. tools/rdp_instance.py
    learned the same thing the same way.
    """
    import win32ts
    return [int(pid) for sid, pid, name, _sid in win32ts.WTSEnumerateProcesses(0, 1, 0)
            if int(sid) == session and (name or "").lower() == game_exe.lower()]


def pids(game_exe: str = GAME_EXE, user: str | None = None) -> list[int]:
    """The client's PIDs: the ones in ``user``'s session, or the ones in OURS.

    No user named does not mean "any client on the machine". It means **this desktop's**
    — the session the panel itself is in — and the difference only shows up once there
    really are two clients, which is exactly what #1206 is for: with the second account
    up in session 4, a profile that named no session reported casper's pid as its own,
    so both profiles' status strips pointed at one client and the console one would
    never have noticed its own dying.

    The fallback to a name-only search is for a machine that cannot be asked (not
    Windows, no pywin32) — there, one session is the only session and the old answer is
    the right one.

    Raises ``LookupError`` when a session was NAMED and could not be resolved: an
    unanswerable question must not come back as an empty list, which reads as "the game
    is not running" and would have the watchdog relaunch a client that is alive. Our own
    session is not in that class — it is unanswerable only where sessions do not exist.
    """
    if user:
        session = session_of(user)
        if session is None:
            raise LookupError(f"no session for {user}")
        return _pids_in_session(game_exe, session)
    here = own_session()
    if here is None:
        return _pids_by_name(game_exe)
    try:
        return _pids_in_session(game_exe, here)
    except Exception:                    # noqa: BLE001 — WTS refused; a name is better
        return _pids_by_name(game_exe)   #                than nothing at all


def _endpoint(found) -> str | None:
    """The first game-server TCP endpoint among ``found``, if one is established."""
    import psutil
    known = set(found)
    for c in psutil.net_connections(kind="tcp"):
        if (c.pid in known and c.raddr and c.status == "ESTABLISHED"
                and c.raddr.port not in _NON_GAME_PORTS):
            return f"{c.raddr.ip}:{c.raddr.port}"
    return None


def server_connection(game_exe: str = GAME_EXE, user: str | None = None) -> str | None:
    """The game-server TCP endpoint, if a connection is currently ESTABLISHED.

    Purely supplementary detail. Its absence (VPN off, mid-reconnect, or the OS
    withholding foreign-owned sockets) must NOT be read as "game not running" —
    that is decided by :func:`status` from the process list alone. A client in
    another user's session is exactly that withheld case: the sockets come back
    without a pid, so the endpoint is simply not shown for it.

    The remote port is not stable across builds (:17935 historically, :10012 on
    the current client), so the check is port-agnostic: find the client's PIDs,
    then return the first ESTABLISHED remote address that is not a web port.
    """
    try:
        found = pids(game_exe, user)
        return _endpoint(found) if found else None
    except Exception:                    # noqa: BLE001 — supplementary, never fatal
        return None


def status(game_exe: str = GAME_EXE, user: str | None = None) -> tuple[bool, str]:
    """Whether the game is running, detected by process name (and session) only.

    Detection is deliberately independent of network state: the game is "found"
    whenever its process exists, regardless of VPN presence or whether a TCP
    connection to the game server is currently established. The connection state,
    when available, is appended as supplementary detail.

    ``game_exe`` is a parameter because the executable is a profile setting (an
    install somewhere else); ``user`` is one because the session is
    (tools/rdp_instance.py). No user named means THIS desktop's client — see
    :func:`pids` for why that is not the same as "whichever client is on this machine".

    The label is a :class:`Message` — the English sentence with its locale key — so the
    strip showing it says it in the panel's language.

    Returns ``(running, label)``.
    """
    try:
        import psutil  # noqa: F401 — every route below needs it
    except Exception:
        return False, Message("game.st.no_psutil", "psutil missing")

    try:
        found = pids(game_exe, user)
    except LookupError:
        # Not "no game": nobody is logged on to that session, so there is nowhere to
        # look. Saying it plainly is what stops the watchdog from starting a client
        # here instead (see `_watchdog_check`).
        return False, Message("game.st.no_session",
                              f"nobody is logged on as {user}", user=user)
    except Exception as exc:
        return False, Message("game.st.probe_error", f"probe error: {exc}", error=exc)

    if not found:
        if user:
            return False, Message("game.st.session_not_found",
                                  f"no client in {user}'s session", user=user)
        return False, Message("game.st.not_found", "game not found")

    pid = found[0]
    conn = _endpoint(found)
    if user and conn:
        return True, Message("game.st.session_running_at",
                             f"running in {user}'s session (pid {pid}) -> {conn}",
                             user=user, pid=pid, conn=conn)
    if user:
        return True, Message("game.st.session_running",
                             f"running in {user}'s session (pid {pid})",
                             user=user, pid=pid)
    if conn:
        return True, Message("game.st.running_at", f"running (pid {pid}) -> {conn}",
                             pid=pid, conn=conn)
    return True, Message("game.st.running", f"running (pid {pid})", pid=pid)


def profile_status(settings) -> tuple[bool, str]:
    """:func:`status` for the profile ``settings`` describes — its exe, its session.

    The one call a caller wants: the three knobs that decide *which* client is this
    profile's are read together, so no caller can honour the executable and forget
    the session.
    """
    return status(settings.opt_str("game_exe"), user=profile_user(settings))


# -- «Проверить»: the answer in full, before anything depends on it -----------

def port_clash(settings) -> bool:
    """Does this profile look into another session while talking to THIS desktop?

    The cheap half of :func:`check` — three knobs and no Windows call — because it is
    re-read on every keystroke in the port box. A profile in that state reads one
    client's process list and presses buttons in another, which looks like the game
    ignoring the panel rather than like a setting.
    """
    import lua_client                     # noqa: PLC0415 — the default port lives there
    if not profile_user(settings):
        return False
    try:
        return settings.opt_int("daemon_port", low=1, high=65535) == lua_client.DEFAULT_PORT
    except Exception:                    # noqa: BLE001 — a half-typed port
        return False


def check(settings) -> dict:
    """Everything the session settings can be wrong about, in one reading.

    The status strip says whether the client is there; this says *why not*, and it is
    the difference between a profile that works and one that quietly farms nothing.
    Four things can be wrong, and they want four different acts from the person:

    * the box is ticked and no login typed — nothing to look for;
    * nobody is logged on as that login — the session is not up (`--bring-up`);
    * the session is up and holds no client — start the client inside it;
    * the session and the client are both there, but the profile's daemon port is the
      default one, which is THIS desktop's daemon. That profile would then read one
      client's process list and press buttons in another — the single most confusing
      state the pair of settings can be in, and invisible without saying so.

    Returns ``{"kind": …}`` and the numbers behind it; the words are the caller's, so
    this stays free of the UI's language (`panel/tabs/settings.py` maps kind → key).
    """
    user = profile_user(settings)
    if not user:
        # Ticked with nothing typed is not the same as not ticked: one is a setting
        # half made, the other is a deliberate "this desktop".
        ticked = False
        try:
            ticked = bool(settings.opt_bool("rdp_session"))
        except Exception:                # noqa: BLE001
            pass
        return {"kind": "no_login" if ticked else "off"}

    exe = settings.opt_str("game_exe")
    port = settings.opt_int("daemon_port", low=1, high=65535)
    clash = port_clash(settings)

    if sessions() is None:
        return {"kind": "unsupported", "user": user}
    found = session_info(user)
    if found is None:
        return {"kind": "no_session", "user": user}

    out = {"user": user, "session": found["id"], "state": found["state"],
           "exe": exe, "port": port, "clash": clash}
    try:
        here = _pids_in_session(exe, found["id"])
    except Exception as exc:             # noqa: BLE001 — a verdict, not a crash
        return {**out, "kind": "probe_error", "error": exc}
    if not here:
        return {**out, "kind": "no_client"}
    return {**out, "kind": "ok", "pid": here[0]}
