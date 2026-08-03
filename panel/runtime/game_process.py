"""Is the client running, and is it still talking to the server?

**A live process is not a live account.** A client that has been up since yesterday can
lose its server session and never say so: the window still draws, every Lua getter still
answers — with yesterday's numbers — and requests come back `true` while nothing happens.
An hour went into "the event has no attempts today" before anybody looked at the sockets
(docs/research/server-link-status.md). The only tell from outside is there: a healthy client
holds an ESTABLISHED connection to the game server, a stranded one holds sockets in
`CLOSE_WAIT` — the far end hung up and the client has not noticed.

So the answer this module gives is not a boolean. It is one of four
(:func:`probe`, :data:`ONLINE` / :data:`LOST` / :data:`UNKNOWN` / :data:`OFFLINE`), and
the difference between the middle two is the difference between "I know the link is
broken" and "I cannot tell yet" — a client still coming up, or a machine that will not
show us its sockets. The second must never be painted as a fault.

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
gives), and «no session for <that user>» in a Russian panel is the message not being
translated at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import game_paths

from ..i18n import Message

#: The default client executable. A profile may name another one — a second client in
#: its own Windows session, or an install somewhere else — so every caller passes it.
#: The default itself is `LW_GAME_EXE`'s answer (tools/lib/game_paths.py) rather than a
#: literal, so the four modules that used to spell it out cannot drift apart again.
GAME_EXE = game_paths.game_exe()

_NON_GAME_PORTS = frozenset({80, 443})

#: The four things this module can honestly say about a client. They are ids, not
#: words — the words are locale keys, and the colour each is painted in belongs to
#: whoever is drawing (the status strip, the phone's pill).
#:
#: * ``ONLINE`` — an ESTABLISHED connection to the game server. The only green one.
#: * ``LOST`` — the process is alive and its sockets say the server hung up. This is
#:   the state that used to read as "running": everything answers, nothing arrives.
#: * ``UNKNOWN`` — the process is alive and its sockets make no verdict: one still
#:   starting up, or a machine that will not attribute a foreign process's sockets at
#:   all. NOT a fault, and never to be painted as one.
#: * ``OFFLINE`` — no client process at all, whatever the reason.
ONLINE = "online"
LOST = "lost"
UNKNOWN = "unknown"
OFFLINE = "offline"

#: The TCP states a socket sits in once the far end has closed and this one has not.
#: `CLOSE_WAIT` is the one a stranded client is found in — the server said goodbye, the
#: client never read it, and it will sit there until the process dies. The rest are the
#: same half of a handshake seen from a different moment. `TIME_WAIT` is deliberately
#: NOT here: it is what an ordinary, cleanly closed connection leaves behind, and a
#: client that reconnects every few hours would otherwise look broken for a minute
#: after every healthy reconnect.
_HALF_CLOSED = frozenset({"CLOSE_WAIT", "CLOSING", "LAST_ACK",
                          "FIN_WAIT1", "FIN_WAIT2"})

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
    up in its own session, a profile that named no session reported the OTHER
    account's pid as its own,
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


def _is_game_socket(c) -> bool:
    """Could this row of the socket table be the connection to the game server?

    Two things are excluded, and the SECOND one is the whole reason this is a function
    rather than the one-line condition it used to be:

    * the web ports. The client talks HTTP to a CDN all day, and the game port is not
      stable across builds (:17935 historically, :10012 on the current client), so
      "anything that is not 80 or 443" is the only port rule that survives an update.
    * **the loopback.** A live client keeps a pair of ESTABLISHED sockets to ITSELF —
      `127.0.0.1:63203 ↔ 127.0.0.1:63204`, both ends owned by the game — and those
      survive the server hanging up, because nothing about them involves the server.
      Counting one as proof of a live account is precisely the lie this module exists
      to stop: the first live reading taken after it was written returned
      `online -> 127.0.0.1:63203` over a client whose six sockets to the real server
      were half of them CLOSE_WAIT.
    """
    if not c.raddr or c.raddr.port in _NON_GAME_PORTS:
        return False
    ip = c.raddr.ip or ""
    return not (ip.startswith("127.") or ip in ("::1", "0.0.0.0", "::"))


def _client_sockets(found) -> list:
    """Every TCP socket the OS attributes to this client — ONE walk of the table.

    THE SEAM, and there is exactly one of it on purpose. The status poll runs every
    eight seconds in the window and every five in the phone's cache, and each reading
    used to be able to walk the table twice: once for the live connection, once for the
    dead ones. `net_connections` is a kernel table rather than a process walk — nothing
    like the 6–7 s of a cold `process_iter` (docs/research/panel-freezes.md §1) — but it
    still holds the interpreter lock while it builds a few hundred objects, and doing
    that twice for one answer is a cost with nothing to show for it.

    An empty list means "nothing of this client's is visible from here", which is NOT
    the same as "this client has no sockets" — a machine that will not attribute a
    foreign process's sockets answers exactly the same way. :func:`link_of` is the one
    that must tell those apart.

    **A second account's sockets ARE attributed on this machine**, which the comment
    that used to sit in `server_connection` denied: read live on 2026-08-03, the client
    in the second account's own Windows session came back with eight sockets of its own
    and an endpoint of its own gateway. So a second account gets a real verdict rather
    than a permanent «не знаю» — but the empty answer is still handled as its own state,
    because that is a property of the machine and not of this code.
    """
    import psutil
    known = set(found)
    try:
        conns = psutil.net_connections(kind="tcp")
    except Exception:                        # noqa: BLE001 — a reading, never a crash
        return []
    return [c for c in conns if c.pid in known]


def _endpoint(found) -> str | None:
    """The first game-server TCP endpoint among ``found``, if one is established."""
    return _live_endpoint(_client_sockets(found))


def _live_endpoint(mine) -> str | None:
    """The established game connection among sockets already read, if there is one."""
    for c in mine:
        if c.status == "ESTABLISHED" and _is_game_socket(c):
            return f"{c.raddr.ip}:{c.raddr.port}"
    return None


def link_of(found) -> tuple:
    """The link state of a client that IS running: ``(state, endpoint, dead)``.

    Established first, because that is the only proof of a live account, and because a
    pile of half-closed sockets means nothing beside a live one: a healthy client keeps
    six of them to `:10012`, the losers of the gateway race it runs while logging in.

    Failing that, a half-closed game socket is proof of the opposite — :data:`LOST`. The
    far end sent FIN, the client never noticed, and it will sit there until the process
    dies. That is the stranded client exactly (docs/research/server-link-status.md).

    With neither, the honest answer is :data:`UNKNOWN` rather than a guess:

    * a client that is still starting has its web sockets and its own loopback pair and
      no game socket yet, and a launch takes about 45 seconds — long enough for a red
      strip and a log line after every scheduled restart if that were called "lost";
    * a machine that will not attribute a foreign process's sockets shows none of a
      second account's at all, and a permanent red over an account that is playing
      perfectly well is a warning nobody reads by the second day. (This machine DOES
      attribute them — see :func:`_client_sockets` — but that is its answer, not a
      guarantee.)

    So the fourth state is the one that says «I cannot tell», and it is amber.
    """
    mine = _client_sockets(found)
    conn = _live_endpoint(mine)
    if conn:
        return ONLINE, conn, 0
    dead = sum(1 for c in mine if c.status in _HALF_CLOSED and _is_game_socket(c))
    return (LOST if dead else UNKNOWN), None, dead


def server_connection(game_exe: str = GAME_EXE, user: str | None = None) -> str | None:
    """The game-server TCP endpoint, if a connection is currently ESTABLISHED.

    Purely supplementary detail. Its absence (VPN off, mid-reconnect, or an OS that
    will not attribute foreign-owned sockets) must NOT be read as "game not running" —
    that is decided by :func:`status` from the process list alone. What it DOES mean is
    :func:`link_of`'s business, and «not online» is not «not running».

    A client in another Windows session was assumed to be the withheld case here for a
    year, and it is not: read live, the second account answered with its own sockets and
    its own endpoint. The withheld case is still handled — it is just not this one.

    The remote port is not stable across builds (:17935 historically, :10012 on
    the current client), so the check is port-agnostic: find the client's PIDs,
    then return the first ESTABLISHED remote address that is not a web port.
    """
    try:
        found = pids(game_exe, user)
        return _endpoint(found) if found else None
    except Exception:                    # noqa: BLE001 — supplementary, never fatal
        return None


@dataclass(frozen=True)
class Probe:
    """One reading of a profile's client: is it there, and is it still connected.

    ``running`` is the old boolean and keeps its old meaning exactly — the process
    exists — because that is what the watchdog acts on and what the schedule gates on,
    and a client that lost the server must NOT be relaunched behind the person's back.
    ``link`` is the new half: the honest word for the strip and for the phone.
    """

    running: bool
    link: str                    # ONLINE | LOST | UNKNOWN | OFFLINE
    message: Message             # the sentence and its locale key, for whoever draws
    pid: int | None = None
    conn: str | None = None      # the server endpoint, when there is a live one
    dead: int = 0                # half-closed game sockets behind a LOST verdict

    @property
    def online(self) -> bool:
        return self.link == ONLINE


def probe(game_exe: str = GAME_EXE, user: str | None = None) -> Probe:
    """Everything this module can say about one client, in one reading.

    Whether it is *running* is decided by the process list alone — deliberately, and
    unchanged since #1204: a VPN dropping or a socket table this machine will not show
    us is not the client being gone, and treating it as such would have the watchdog
    kill and relaunch a healthy account.

    Whether it is *connected* is then decided by that client's own sockets
    (:func:`link_of`), and it is a separate question with a separate answer. The pair is
    the point: "running but LOST" is a real state the panel had no way to say, and it is
    exactly the state a client sits in overnight while every timer reports success and
    nothing at all happens in the game.

    ``game_exe`` is a parameter because the executable is a profile setting (an
    install somewhere else); ``user`` is one because the session is
    (tools/rdp_instance.py). No user named means THIS desktop's client — see
    :func:`pids` for why that is not the same as "whichever client is on this machine".
    """
    try:
        import psutil  # noqa: F401 — every route below needs it
    except Exception:
        return Probe(False, OFFLINE, Message("game.st.no_psutil", "psutil missing"))

    try:
        found = pids(game_exe, user)
    except LookupError:
        # Not "no game": nobody is logged on to that session, so there is nowhere to
        # look. Saying it plainly is what stops the watchdog from starting a client
        # here instead (see `_watchdog_check`).
        return Probe(False, OFFLINE,
                     Message("game.st.no_session",
                             f"nobody is logged on as {user}", user=user))
    except Exception as exc:
        return Probe(False, OFFLINE,
                     Message("game.st.probe_error", f"probe error: {exc}", error=exc))

    if not found:
        if user:
            return Probe(False, OFFLINE,
                         Message("game.st.session_not_found",
                                 f"no client in {user}'s session", user=user))
        return Probe(False, OFFLINE, Message("game.st.not_found", "game not found"))

    pid = found[0]
    link, conn, dead = link_of(found)
    message = _worded(link, pid, conn, user)
    return Probe(True, link, message, pid=pid, conn=conn, dead=dead)


#: link → the locale key of the sentence, with and without a Windows session named.
#: One table rather than a ladder of ``if``s, so a state that grows a word cannot end
#: up with one in the session half and none in the other.
_WORDS = {
    ONLINE: ("game.st.running_at", "game.st.session_running_at"),
    LOST: ("game.st.lost", "game.st.session_lost"),
    UNKNOWN: ("game.st.running", "game.st.session_running"),
}


def _worded(link: str, pid: int, conn: str | None, user: str | None) -> Message:
    """The sentence for a client that IS running, in the state :func:`link_of` found.

    Only what the sentence names goes into the values: a `user` of ``None`` handed to a
    key that has no ``{user}`` in it is a placeholder waiting to print «None» the day
    somebody words that key differently.
    """
    plain, in_session = _WORDS.get(link, _WORDS[UNKNOWN])
    fmt = {"pid": pid}
    if user:
        fmt["user"] = user
    if link == ONLINE:
        fmt["conn"] = conn
        english = (f"online in {user}'s session (pid {pid}) -> {conn}" if user
                   else f"online (pid {pid}) -> {conn}")
    elif link == LOST:
        english = (f"the server connection is lost in {user}'s session (pid {pid})"
                   if user else f"the server connection is lost (pid {pid})")
    else:
        english = (f"running in {user}'s session (pid {pid}), link unconfirmed" if user
                   else f"running (pid {pid}), link unconfirmed")
    return Message(in_session if user else plain, english, **fmt)


def status(game_exe: str = GAME_EXE, user: str | None = None) -> tuple[bool, str]:
    """:func:`probe`, kept as the pair it always returned: ``(running, label)``.

    Every caller that only asks "is there a client to press buttons in" — the schedule,
    the ghost watcher, the watchdog — wants exactly this and nothing more. The ones that
    draw the answer for a person (the status strip, the phone) call :func:`probe`
    instead, because "running" is the half that was lying to them.
    """
    found = probe(game_exe, user)
    return found.running, found.message


def profile_probe(settings) -> Probe:
    """:func:`probe` for the profile ``settings`` describes — its exe, its session.

    The one call a caller wants: the three knobs that decide *which* client is this
    profile's are read together, so no caller can honour the executable and forget
    the session.
    """
    return probe(settings.opt_str("game_exe"), user=profile_user(settings))


def profile_status(settings) -> tuple[bool, str]:
    """:func:`status` for the profile ``settings`` describes — its exe, its session."""
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
