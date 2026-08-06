"""Is this client still TALKING to the game server? — the rule, in one place.

A Last War client that has lost its server session goes on looking healthy from the
inside: the window draws, every Lua getter answers (with yesterday's numbers), and every
send returns `true` while nothing arrives. **No reading inside the client can tell**, because
the client itself does not know — it is holding a socket the far end closed. The whole
story is docs/research/server-link-status.md.

The tell is the socket table, and the rule for reading it is small and easy to get wrong:

* a healthy client keeps **half-closed sockets** while it plays — six of them, the losers
  of the gateway race it runs while logging in — so «there is a CLOSE_WAIT» proves
  nothing on its own. An ESTABLISHED game socket is checked FIRST and wins;
* it keeps an ESTABLISHED **loopback pair to itself**, which survives the server hanging
  up. Counting one as proof is exactly the lie this rule exists to stop;
* the **game port moves between builds** (`:17935`, then `:10012`), so the only port rule
  that survives an update is «anything that is not 80 or 443»;
* `TIME_WAIT` is NOT a loss — it is what a clean reconnect leaves behind, and a client
  that reconnects every few hours would otherwise look broken for a minute afterwards.

WHY IT LIVES HERE AND NOT IN THE PANEL. It used to live only in
`panel/runtime/game_process.py`, which meant the only layer that could ask was the one
DRAWING the answer. Everything that SENDS — `script_engine`, every scenario, every
tool — had no way to ask and did not, so a recipe on a stranded client pressed its way
to the end, got `true` from every send, and failed with a believable wrong reason
(#1259 spent a day concluding «the server silently refuses this march» over a client the
panel had already declared dead in its own log). The panel imports the rule from here
now; the engine asks it before it drives anything.

**And so does the READING** (#1260). The rule came over first and the machinery stayed
behind, which left the shared half unable to answer the only question anybody actually
asks — «is THIS client on the server» — without being handed a list of pids it had no way
to obtain. Working out which pids those are is most of the difficulty and all of the
subtlety: which Windows session the client lives in, which of two accounts' clients is
this profile's, and how not to walk the machine four times over for one answer. So
:func:`probe` is here, with the cached walks and the session attribution under it, and a
tool run from a shell gets exactly the reading the status strip gets.

This module answers in **ids, not words**: :class:`Link` is data, and the panel wraps it
in its own locale keys (`panel/runtime/game_process.py`, which is now the wording and
nothing else). Nothing here may grow a translator — that is precisely what kept the
reading locked inside the panel, because a module answering in `panel.i18n.Message`
cannot be imported by anything that is not the panel.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_paths  # noqa: E402

#: The ports the client talks HTTP on all day. Everything else that is remote and not
#: loopback is a candidate for the game gateway — see the module docstring for why this
#: is a port EXCLUSION list and not the game port itself.
NON_GAME_PORTS = frozenset({80, 443})

#: The four things that can honestly be said about a client.
#:
#: * ``ONLINE``  — an ESTABLISHED connection to the game server. The only green one.
#: * ``LOST``    — the process is alive and its sockets say the server hung up. The state
#:                 that used to read as «running»: everything answers, nothing arrives.
#: * ``UNKNOWN`` — alive, and its sockets make no verdict: one still starting up, or a
#:                 machine that will not attribute a foreign process's sockets. NOT a
#:                 fault, and never to be treated as one.
#: * ``OFFLINE`` — no client process at all, whatever the reason.
ONLINE = "online"
LOST = "lost"
UNKNOWN = "unknown"
OFFLINE = "offline"

#: The TCP states a socket sits in once the far end has closed and this one has not.
#: `TIME_WAIT` is deliberately absent — see the module docstring.
HALF_CLOSED = frozenset({"CLOSE_WAIT", "CLOSING", "LAST_ACK",
                         "FIN_WAIT1", "FIN_WAIT2"})


def is_game_socket(c) -> bool:
    """Could this row of the socket table be the connection to the game server?"""
    if not c.raddr or c.raddr.port in NON_GAME_PORTS:
        return False
    ip = c.raddr.ip or ""
    return not (ip.startswith("127.") or ip in ("::1", "0.0.0.0", "::"))


def live_endpoint(sockets) -> "str | None":
    """The established game connection among sockets already read, if there is one."""
    for c in sockets:
        if c.status == "ESTABLISHED" and is_game_socket(c):
            return f"{c.raddr.ip}:{c.raddr.port}"
    return None


def classify(sockets) -> tuple:
    """``(state, endpoint, dead)`` for a client that IS running, from its own sockets.

    Established first — that is the only proof of a live account, and a pile of
    half-closed sockets means nothing beside a live one. Failing that, a half-closed
    game socket is proof of the opposite. With neither, the honest answer is
    :data:`UNKNOWN` and not a guess: a client 45 seconds into starting up has exactly
    those sockets, and so does a machine that will not attribute a foreign process's.
    """
    conn = live_endpoint(sockets)
    if conn:
        return ONLINE, conn, 0
    dead = sum(1 for c in sockets if c.status in HALF_CLOSED and is_game_socket(c))
    return (LOST if dead else UNKNOWN), None, dead


def sockets_of(pids) -> list:
    """Every TCP socket owned by ``pids``, walked fresh — no cache, no psutil for callers.

    For a caller that holds no shared reading of the machine (the script engine, a tool
    run from a shell). The panel has its own cached walk and passes the rows straight to
    :func:`classify`; one uncached walk per scenario run is cheap beside what a scenario
    then does, and being a walk behind is worse here than being slow.

    An empty list back means «could not be read», which :func:`classify` turns into
    ``UNKNOWN`` — never into a loss.
    """
    try:
        import psutil
    except Exception:                      # noqa: BLE001 — no psutil is «cannot tell»
        return []
    wanted = {int(p) for p in pids or ()}
    if not wanted:
        return []
    try:
        return [c for c in psutil.net_connections(kind="tcp") if c.pid in wanted]
    except Exception:                      # noqa: BLE001 — a refused socket table, ditto
        return []


def state_of(pids) -> str:
    """The link state of the given client pids: ONLINE / LOST / UNKNOWN / OFFLINE.

    ``OFFLINE`` when there are no pids at all — there is no client to have a link.
    """
    if not pids:
        return OFFLINE
    return classify(sockets_of(pids))[0]


# ============================================================================
# The reading: WHICH client, and what its sockets say (#1260)
# ============================================================================
#
# Everything above answers «what do these sockets mean». Everything below answers the
# question a caller actually has — «is the client I am about to drive still on the
# server» — and the hard part of it is not the sockets at all. It is knowing which
# process is THIS profile's client on a machine that may be running two of them, in two
# Windows sessions, for two accounts.
#
# It lived in `panel/runtime/game_process.py` until #1260 and could not be borrowed,
# because it answered in the panel's own message type. What is here is the same code
# with the words taken off; the panel puts them back on.

#: How long a MACHINE-WIDE reading is reused (#1226).
#:
#: The three expensive things asked below — the TCP table, the process table and the
#: list of Windows sessions — are facts about the BOX, not about a profile. Every open
#: profile used to ask for all three on its own clock: four profiles meant four walks of
#: a few hundred sockets and a few hundred processes every eight seconds, each of them
#: holding Python's lock while it built the objects, and every one of them producing an
#: answer the others had just produced.
#:
#: So the walk is shared and the verdict is not. Filtering the shared table down to one
#: profile's client is a comprehension over a list already in memory; only the walk is
#: cached, and only for long enough that profiles polling on independent clocks land in
#: the same one. Two seconds against an eight-second poll — the strip can be two seconds
#: stale, which is a quarter of the interval it was already showing.
MACHINE_TTL_SEC = 2.0


class _Shared:
    """One machine-wide reading, taken at most every :data:`MACHINE_TTL_SEC`.

    The lock is held for the WALK, deliberately: a second profile arriving mid-walk
    should wait for the answer being fetched rather than start a second one. That is the
    whole saving.
    """

    __slots__ = ("_fetch", "_lock", "_at", "_value")

    def __init__(self, fetch) -> None:
        self._fetch = fetch
        self._lock = threading.Lock()
        self._at = 0.0
        self._value = None

    def get(self, ttl: float = MACHINE_TTL_SEC):
        now = time.monotonic()
        with self._lock:
            if self._value is not None and (now - self._at) < ttl:
                return self._value
            self._value = self._fetch()
            self._at = time.monotonic()
            return self._value

    def forget(self) -> None:
        """Drop the reading — the next ask walks again. For tests, and for a deliberate
        re-check after something was started or killed."""
        with self._lock:
            self._at, self._value = 0.0, None


#: The default client executable. A profile may name another one — a second client in
#: its own Windows session, or an install somewhere else — so every caller passes it.
#: The default itself is `LW_GAME_EXE`'s answer (tools/lib/game_paths.py) rather than a
#: literal, so the four modules that used to spell it out cannot drift apart again.
GAME_EXE = game_paths.game_exe()

#: The two session states worth a word of their own. A *disconnected* session is a fully
#: working one — that is how the second client is meant to be left (docs/research/
#: multi-instance-rdp.md §3.3) — so it must not read as a fault; anything else is rare
#: enough to be shown as its raw code rather than translated into eight more keys.
WTS_ACTIVE = 0
WTS_DISCONNECTED = 4

#: WHY, for the answers the four states do not explain by themselves. Ids rather than
#: sentences, for the same reason the states are ids: the panel maps them onto locale
#: keys (`game.st.<reason>`), a tool prints them, and neither has to parse English.
#:
#: * ``NOT_FOUND`` — no client process on this desktop.
#: * ``SESSION_NOT_FOUND`` — a session was named, and holds no client.
#: * ``NO_SESSION`` — a session was named and nobody is logged on to it. NOT the same
#:   as «no client»: there is nowhere to look, so nothing may be started here instead.
#: * ``NO_PSUTIL`` — this machine cannot be asked at all.
#: * ``PROBE_ERROR`` — the ask itself blew up; what it said is in `Link.error`.
NOT_FOUND = "not_found"
SESSION_NOT_FOUND = "session_not_found"
NO_SESSION = "no_session"
NO_PSUTIL = "no_psutil"
PROBE_ERROR = "probe_error"


# -- which Windows session ---------------------------------------------------

def sessions() -> "list | None":
    """Every Windows session with its login and state, or ``None`` if it cannot be asked.

    ``None`` is not "no sessions": it is "this machine has no answer" — pywin32 missing,
    or not Windows at all. The two are told apart because they want opposite things said
    to the person, and folding them together is how a panel ends up looking in the wrong
    session in silence.

    Shared between open profiles (:data:`MACHINE_TTL_SEC`): who is logged on to this box
    is one answer, and four profiles asking it four times a poll is four answers that
    were always going to be the same one. A session appearing or disappearing is minutes
    of work by a person; two seconds of staleness cannot be noticed.
    """
    return _SESSIONS.get()


def _read_sessions() -> "list | None":
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


def session_of(user: str) -> "int | None":
    """The id of the Windows session ``user`` is logged on to, or ``None``.

    ``None`` covers both "nobody by that name is logged on" and "this machine cannot
    be asked". Neither is the same as "the game is not running", which is why the
    callers say so in their own words rather than folding it into a plain "not found".
    """
    found = session_info(user)
    return None if found is None else found["id"]


def own_session() -> "int | None":
    """The Windows session THIS process is in, or ``None`` if it cannot be asked.

    ``None`` on anything that is not Windows-with-pywin32, which is what keeps the
    fallback in :func:`pids` honest rather than silent. Asked about our OWN pid, so
    `ProcessIdToSessionId` is enough — the query-rights problem `_pids_in_session`
    documents only bites on somebody else's process.
    """
    try:
        import win32ts
        return int(win32ts.ProcessIdToSessionId(os.getpid()))
    except Exception:                    # noqa: BLE001 — not Windows, or no pywin32
        return None


# -- which processes ---------------------------------------------------------

def _read_names() -> list:
    """``(pid, name)`` for every process on the box — the psutil walk, once."""
    import psutil
    return [(p.info["pid"], (p.info["name"] or ""))
            for p in psutil.process_iter(["pid", "name"])]


def _pids_by_name(game_exe: str) -> "list":
    """Every process called ``game_exe``, whatever session it sits in."""
    want = game_exe.lower()
    return [pid for pid, name in _NAMES.get() if name.lower() == want]


def _pids_in_session(game_exe: str, session: int) -> "list":
    """The clients inside one Windows session.

    Through `WTSEnumerateProcesses`, not `ProcessIdToSessionId`: the latter needs query
    rights on the process, so another user's client comes back as "session 0" — which
    reads as a service and is exactly the process being looked for. tools/rdp_instance.py
    learned the same thing the same way.
    """
    want = game_exe.lower()
    return [pid for sid, pid, name in _WTS.get()
            if sid == session and name.lower() == want]


def _read_wts() -> list:
    """``(session, pid, name)`` for every process on the box — the WTS walk, once.

    Raises exactly as the bare call did on a machine that cannot be asked, because
    :func:`pids` reads that as "try the name instead" and a cached empty list would read
    as "the client is gone".
    """
    import win32ts
    return [(int(sid), int(pid), (name or ""))
            for sid, pid, name, _sid in win32ts.WTSEnumerateProcesses(0, 1, 0)]


def pids(game_exe: str = GAME_EXE, user: "str | None" = None) -> "list":
    """The client's PIDs: the ones in ``user``'s session, or the ones in OURS.

    No user named does not mean "any client on the machine". It means **this desktop's**
    — the session the asking process itself is in — and the difference only shows up once
    there really are two clients, which is exactly what #1206 is for: with the second
    account up in its own session, a profile that named no session reported the OTHER
    account's pid as its own, so both profiles' status strips pointed at one client and
    the console one would never have noticed its own dying.

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


# -- which sockets -----------------------------------------------------------

def client_sockets(found) -> list:
    """Every TCP socket the OS attributes to these pids — ONE walk of the table.

    THE SEAM, and there is exactly one of it on purpose. The status poll runs every
    eight seconds in the window and every five in the phone's cache, and each reading
    used to be able to walk the table twice: once for the live connection, once for the
    dead ones. `net_connections` is a kernel table rather than a process walk — nothing
    like the 6–7 s of a cold `process_iter` (docs/research/panel-freezes.md §1) — but it
    still holds the interpreter lock while it builds a few hundred objects, and doing
    that twice for one answer is a cost with nothing to show for it.

    An empty list means "nothing of this client's is visible from here", which is NOT
    the same as "this client has no sockets" — a machine that will not attribute a
    foreign process's sockets answers exactly the same way. :func:`classify` is the one
    that must tell those apart, and it does: neither is a loss.

    **A second account's sockets ARE attributed on this machine**, which the comment
    that used to sit in `server_connection` denied: read live on 2026-08-03, the client
    in the second account's own Windows session came back with eight sockets of its own
    and an endpoint of its own gateway. So a second account gets a real verdict rather
    than a permanent «не знаю» — but the empty answer is still handled as its own state,
    because that is a property of the machine and not of this code.

    ONE WALK FOR THE WHOLE WINDOW, too (#1226). The table is the machine's, not this
    profile's: four profiles filtering the same few hundred rows is one walk and four
    comprehensions, not four walks. :data:`MACHINE_TTL_SEC` is what makes polls on
    independent clocks land in the same one. That sharing is the whole difference
    between this and :func:`sockets_of`, which walks fresh for a caller that holds no
    clock of its own.
    """
    known = set(found)
    return [c for c in _CONNECTIONS.get() if c.pid in known]


def _read_connections() -> list:
    """The machine's whole TCP table, or an empty one where it cannot be read."""
    import psutil
    try:
        return list(psutil.net_connections(kind="tcp"))
    except Exception:                        # noqa: BLE001 — a reading, never a crash
        return []


#: The four machine-wide walks, each taken at most every :data:`MACHINE_TTL_SEC` and
#: shared by every open profile. Down here rather than at the top because each names the
#: reader defined above it.
_SESSIONS = _Shared(_read_sessions)
_NAMES = _Shared(_read_names)
_WTS = _Shared(_read_wts)
_CONNECTIONS = _Shared(_read_connections)


def forget_machine_state() -> None:
    """Drop every shared reading, so the next ask walks again.

    For the caller that has just CHANGED what it is about to read — started a client,
    killed one, brought a Windows session up — and for tests, which must not inherit a
    reading taken by the case before them.
    """
    for shared in (_SESSIONS, _NAMES, _WTS, _CONNECTIONS):
        shared.forget()


def endpoint_of(found) -> "str | None":
    """The first game-server TCP endpoint among these pids, if one is established."""
    return live_endpoint(client_sockets(found))


def link_of(found) -> tuple:
    """``(state, endpoint, dead)`` for pids that ARE running — off the SHARED walk.

    :func:`classify` with the socket table filled in from the cache, which is the pairing
    every repeated reading wants (the status strip, the phone). A caller with no clock of
    its own wants :func:`state_of` instead, which walks fresh.
    """
    return classify(client_sockets(found))


def server_connection(game_exe: str = GAME_EXE,
                      user: "str | None" = None) -> "str | None":
    """The game-server TCP endpoint, if a connection is currently ESTABLISHED.

    Purely supplementary detail. Its absence (VPN off, mid-reconnect, or an OS that
    will not attribute foreign-owned sockets) must NOT be read as "game not running" —
    that is decided by :func:`probe` from the process list alone. What it DOES mean is
    :func:`classify`'s business, and «not online» is not «not running».

    A client in another Windows session was assumed to be the withheld case here for a
    year, and it is not: read live, the second account answered with its own sockets and
    its own endpoint. The withheld case is still handled — it is just not this one.

    The remote port is not stable across builds (:17935 historically, :10012 on
    the current client), so the check is port-agnostic: find the client's PIDs,
    then return the first ESTABLISHED remote address that is not a web port.
    """
    try:
        found = pids(game_exe, user)
        return endpoint_of(found) if found else None
    except Exception:                    # noqa: BLE001 — supplementary, never fatal
        return None


# -- the whole answer, in one value ------------------------------------------

@dataclass(frozen=True)
class Link:
    """One reading of a client: is it there, and is it still connected.

    ``running`` is the old boolean and keeps its old meaning exactly — the process
    exists — because that is what the watchdog acts on and what the schedule gates on,
    and a client that lost the server must NOT be relaunched behind the person's back.
    ``link`` is the other half: the honest word for the strip, for the phone, and for
    anything that is about to send.

    ``reason`` names WHY when the state alone does not say it (:data:`NOT_FOUND` and its
    neighbours), and it is an id rather than a sentence — the words belong to whoever is
    drawing. ``user`` carries the Windows session the reading was taken in, because
    every sentence that mentions one needs it and re-deriving it is how the two halves
    come apart.

    ``looked`` is the quietly important one. It is False where this machine could not
    have known about the client at all — no `psutil` — and a caller that reads that as
    «the client is gone» will refuse to work anywhere but the box the game is on.
    Nothing here can tell that apart from a real absence, so it is said out loud instead
    of guessed at.
    """

    running: bool
    link: str                    # ONLINE | LOST | UNKNOWN | OFFLINE
    reason: str = ""             # NOT_FOUND | SESSION_NOT_FOUND | NO_SESSION | …
    pid: "int | None" = None
    conn: "str | None" = None    # the server endpoint, when there is a live one
    dead: int = 0                # half-closed game sockets behind a LOST verdict
    user: "str | None" = None    # the Windows session this reading was taken in
    error: str = ""              # what blew up, when `reason` is PROBE_ERROR
    looked: bool = True          # could this machine be asked at all?

    @property
    def online(self) -> bool:
        return self.link == ONLINE


def probe(game_exe: str = GAME_EXE, user: "str | None" = None) -> Link:
    """Everything that can honestly be said about one client, in one reading.

    Whether it is *running* is decided by the process list alone — deliberately, and
    unchanged since #1204: a VPN dropping or a socket table this machine will not show
    us is not the client being gone, and treating it as such would have the watchdog
    kill and relaunch a healthy account.

    Whether it is *connected* is then decided by that client's own sockets
    (:func:`classify`), and it is a separate question with a separate answer. The pair is
    the point: "running but LOST" is a real state nothing had a way to say, and it is
    exactly the state a client sits in overnight while every timer reports success and
    nothing at all happens in the game.

    ``game_exe`` is a parameter because the executable is a setting (an install
    somewhere else); ``user`` is one because the Windows session is
    (tools/rdp_instance.py). No user named means THIS desktop's client — see :func:`pids`
    for why that is not the same as "whichever client is on this machine".

    Measured at 46–67 ms on a live machine with two clients up
    (docs/research/server-link-status.md §3.2), and it must never grow into a
    `process_iter`.
    """
    try:
        import psutil  # noqa: F401 — every route below needs it
    except Exception:  # noqa: BLE001
        return Link(False, OFFLINE, NO_PSUTIL, user=user, looked=False)

    try:
        found = pids(game_exe, user)
    except LookupError:
        # Not "no game": nobody is logged on to that session, so there is nowhere to
        # look. Saying it plainly is what stops the watchdog from starting a client
        # on this desktop instead.
        return Link(False, OFFLINE, NO_SESSION, user=user)
    except Exception as exc:               # noqa: BLE001 — a verdict, never a crash
        return Link(False, OFFLINE, PROBE_ERROR, user=user, error=str(exc))

    if not found:
        return Link(False, OFFLINE, SESSION_NOT_FOUND if user else NOT_FOUND, user=user)

    state, conn, dead = link_of(found)
    return Link(True, state, pid=found[0], conn=conn, dead=dead, user=user)
