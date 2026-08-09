"""What the panel SAYS about a client — the words on top of the shared reading.

The reading itself is `tools/lib/game_link.py` and this module is its wording. That
split is the whole of #1260, and it is worth a paragraph, because for a year this file
looked like the natural home for the answer and quietly was not.

**A live process is not a live account.** A client that has been up since yesterday can
lose its server session and never say so: the window still draws, every Lua getter still
answers — with yesterday's numbers — and requests come back `true` while nothing happens.
The only tell from outside is the socket table, and the answer it gives is one of four
(`game_link.ONLINE` / `LOST` / `UNKNOWN` / `OFFLINE`): «I know the link is broken» and
«I cannot tell yet» are different states, and the second must never be painted as a
fault. All of that — which pids, which Windows session, which sockets, what they mean —
is the shared module's now.

**Why it had to leave.** Because this file answers in :class:`panel.i18n.Message`, and a
module that answers in a front-end's message type can only ever be used by that
front-end. So the panel drew a stranded client in red, wrote «связь с сервером пропала»
in its own log, and went on playing scenarios into it — because `script_engine`, the
scenarios, and every tool run from a shell had no way to ask, and «the gate lives in the
panel» is a rule that only holds while somebody is running the panel (#1259, #1260).

What is here now is exactly what is the PANEL's: turning `game_link.Link` into a sentence
with a locale key (:func:`probe`), the profile settings that say which client is this
one's (:func:`profile_user` and friends), «Проверить» (:func:`check`) and «Поднять
сессию» (:func:`bring_up`). Every name the panel used to reach for still resolves here,
so nothing that was calling this file had to change; they are aliases onto the shared
module rather than second copies, because two implementations of one rule is how the two
answers come apart six months later.

This module still has no translator and must not grow one (the very same reason
`panel/profile.py` gives): it names a key and hands over the values, and «no session for
<that user>» in a Russian panel is the message not being translated at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import game_link

from ..i18n import Message

# -- the shared reading, under the names the panel already used ---------------
#
# Aliases, not re-implementations. Anything that walks the machine, attributes a
# process to a Windows session or reads a socket lives in `tools/lib/game_link.py`;
# what a caller here gets is that exact function under the name it has always spelled.
# A test that stubs the machine stubs it THERE — there is one implementation to stub,
# which is the point of the move.

#: How long a machine-wide reading is shared between open profiles (#1226).
MACHINE_TTL_SEC = game_link.MACHINE_TTL_SEC

#: The default client executable — `LW_GAME_EXE`'s answer, never a literal.
GAME_EXE = game_link.GAME_EXE

#: The four things that can honestly be said about a client. They are ids, not words —
#: the words are the locale keys below, and the colour each is painted in belongs to
#: whoever is drawing (the status strip, the phone's pill).
ONLINE = game_link.ONLINE
LOST = game_link.LOST
UNKNOWN = game_link.UNKNOWN
OFFLINE = game_link.OFFLINE

#: The two session states worth a word of their own. A *disconnected* session is a fully
#: working one — that is how the second client is meant to be left (docs/research/
#: multi-instance-rdp.md §3.3) — so it must not read as a fault; anything else is rare
#: enough to be shown as its raw code rather than translated into eight more keys.
WTS_ACTIVE = game_link.WTS_ACTIVE
WTS_DISCONNECTED = game_link.WTS_DISCONNECTED

sessions = game_link.sessions
session_info = game_link.session_info
session_of = game_link.session_of
own_session = game_link.own_session
pids = game_link.pids
link_of = game_link.link_of
server_connection = game_link.server_connection
forget_machine_state = game_link.forget_machine_state


# -- which client is this profile's ------------------------------------------

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


def local_users() -> tuple:
    """``(logins, error)`` — the accounts of THIS machine, for the login picker.

    Two separate answers, and folding them together is the failure this signature
    exists to prevent: a machine that cannot be asked must NOT come back as «there are
    no accounts». One is a reason to offer typing instead; the other is a fresh install,
    and a picker that shows an empty list for either says nothing about which.

    ``error`` is the exception in the machine's own words — a panel with no pywin32, a
    Windows that refuses the enumeration — for the page to show. Nothing is cached: the
    list costs one API call, and an account added five minutes ago is an account a
    person expects to see (`CLAUDE.md`, «Nothing about one machine is written into the
    code»).
    """
    try:
        import rdp_instance                # noqa: PLC0415 — Windows-only, pywin32
        return list(rdp_instance.local_users()), ""
    except Exception as exc:               # noqa: BLE001 — a page, not a crash
        return [], str(exc) or type(exc).__name__


def profile_pids(settings) -> list:
    """This profile's client pids — for a capture that must decode only ITS account.

    Two clients of the same game dial the same server port, so a packet filter cannot
    tell them apart and every capture on the machine used to decode both: a wire trigger
    in one profile firing off the other's push, an auto-join in one account spending
    squads because the other's alliance raised a banner. The pid is what the capture
    narrows by (`map_capture.OwnPorts`), and this is the one place that answers «which
    client is this profile's» for it.

    NEVER RAISES, and an empty list means «could not tell» — which every caller must
    treat as «capture everything», not as «capture nothing». A profile that goes deaf
    farms nothing and looks exactly like one with nothing to do; a profile that hears
    too much is what we had yesterday.
    """
    try:
        return list(game_link.pids(settings.opt_str("game_exe") or GAME_EXE,
                                   profile_user(settings)))
    except Exception:                    # noqa: BLE001 — no session, no WTS, no psutil
        return []


def capture_narrowing(settings) -> list:
    """The argv that ties a capture child to THIS profile's client, and to no other.

    Every capture the panel spawns takes it — the rally monitor, the wire ear, the
    secret-task and ghost scans, the leaderboard collector — because they all decode
    the same two server ports and a packet filter cannot tell four accounts apart.

    A PID IS A SEED, A SESSION IS THE ANCHOR (#1306). :func:`profile_pids` answers for
    the moment it is asked, and the moment a capture is spawned is the panel's boot —
    when a profile whose client lives in its own Windows session has no client yet. It
    came back empty, «could not tell» meant «hear everything», and it meant it for the
    rest of the run: measured live on 2026-08-09, three of four open profiles were
    running their rally monitor and their wire ear with no narrowing at all. So the
    session goes with the pids, the capture looks them up again on its own clock
    (`map_capture.OwnPorts`), and a client that starts late is picked up rather than
    missed for good.

    Never raises and never comes back empty: a profile that names no Windows session of
    its own says «the session I am in», which is a real anchor and not the absence of
    one.
    """
    user = profile_user(settings)
    args = ["--client-user", user] if user else ["--client-own-session"]
    for pid in profile_pids(settings):
        args += ["--client-pid", str(pid)]
    return args


# -- the reading, worded ------------------------------------------------------

@dataclass(frozen=True)
class Probe:
    """One reading of a profile's client, with the sentence that says it.

    `game_link.Link` plus the one thing the shared module deliberately cannot produce:
    a :class:`panel.i18n.Message`, the English sentence and its locale key in one value,
    for whoever is drawing.

    ``running`` is the old boolean and keeps its old meaning exactly — the process
    exists — because that is what the watchdog acts on and what the schedule gates on,
    and a client that lost the server must NOT be relaunched behind the person's back.
    ``link`` is the other half: the honest word for the strip and for the phone.
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
    """`game_link.probe`, with the panel's words on it.

    Everything about WHAT is true is the shared module's; everything about how it is
    SAID is here. The pair `(running, link)` is the point and is unchanged: "running but
    LOST" is a real state the panel had no way to say, and it is exactly the state a
    client sits in overnight while every timer reports success and nothing at all
    happens in the game.

    ``game_exe`` is a parameter because the executable is a profile setting (an
    install somewhere else); ``user`` is one because the session is
    (tools/rdp_instance.py). No user named means THIS desktop's client — see
    `game_link.pids` for why that is not the same as "whichever client is on this
    machine".
    """
    found = game_link.probe(game_exe, user=user)
    return Probe(found.running, found.link, _worded(found),
                 pid=found.pid, conn=found.conn, dead=found.dead)


#: The state a client is in → the locale key of the sentence, with and without a Windows
#: session named. One table rather than a ladder of ``if``s, so a state that grows a word
#: cannot end up with one in the session half and none in the other.
#:
#: A client that is NOT running is keyed by `Link.reason` instead — «nobody is logged on
#: as that user» and «the game is not running here» are the same `OFFLINE` and want
#: opposite things done about them.
_WORDS = {
    ONLINE: ("game.st.running_at", "game.st.session_running_at"),
    LOST: ("game.st.lost", "game.st.session_lost"),
    UNKNOWN: ("game.st.running", "game.st.session_running"),
}

#: `Link.reason` → the key for a client that is not there. No session half: every one of
#: these either names the user in its own text or has nothing to do with a session.
_OFF_WORDS = {
    game_link.NO_PSUTIL: "game.st.no_psutil",
    game_link.NO_SESSION: "game.st.no_session",
    game_link.SESSION_NOT_FOUND: "game.st.session_not_found",
    game_link.NOT_FOUND: "game.st.not_found",
    game_link.PROBE_ERROR: "game.st.probe_error",
}


def _worded(found) -> Message:
    """The sentence for one `game_link.Link`, in the state the sockets put it in.

    Only what the sentence names goes into the values: a `user` of ``None`` handed to a
    key that has no ``{user}`` in it is a placeholder waiting to print «None» the day
    somebody words that key differently.
    """
    if not found.running:
        return _worded_off(found)
    user, pid, conn = found.user, found.pid, found.conn
    plain, in_session = _WORDS.get(found.link, _WORDS[UNKNOWN])
    fmt = {"pid": pid}
    if user:
        fmt["user"] = user
    if found.link == ONLINE:
        fmt["conn"] = conn
        english = (f"online in {user}'s session (pid {pid}) -> {conn}" if user
                   else f"online (pid {pid}) -> {conn}")
    elif found.link == LOST:
        english = (f"the server connection is lost in {user}'s session (pid {pid})"
                   if user else f"the server connection is lost (pid {pid})")
    else:
        english = (f"running in {user}'s session (pid {pid}), link unconfirmed" if user
                   else f"running (pid {pid}), link unconfirmed")
    return Message(in_session if user else plain, english, **fmt)


def _worded_off(found) -> Message:
    """The sentence for a client that is not running — keyed by WHY, not by the state."""
    key = _OFF_WORDS.get(found.reason, "game.st.not_found")
    if found.reason == game_link.NO_PSUTIL:
        return Message(key, "psutil missing")
    if found.reason == game_link.NO_SESSION:
        return Message(key, f"nobody is logged on as {found.user}", user=found.user)
    if found.reason == game_link.SESSION_NOT_FOUND:
        return Message(key, f"no client in {found.user}'s session", user=found.user)
    if found.reason == game_link.PROBE_ERROR:
        return Message(key, f"probe error: {found.error}", error=found.error)
    return Message(key, "game not found")


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

    The one caller that walks afresh: a person pressing «Проверить» has just changed
    something and is asking whether it took, so the two seconds of sharing every poll
    lives with (:data:`MACHINE_TTL_SEC`) are exactly the two seconds they would not
    understand.
    """
    game_link.forget_machine_state()
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

    if game_link.sessions() is None:
        return {"kind": "unsupported", "user": user}
    found = game_link.session_info(user)
    if found is None:
        return {"kind": "no_session", "user": user}

    out = {"user": user, "session": found["id"], "state": found["state"],
           "exe": exe, "port": port, "clash": clash}
    try:
        here = game_link._pids_in_session(exe, found["id"])
    except Exception as exc:             # noqa: BLE001 — a verdict, not a crash
        return {**out, "kind": "probe_error", "error": exc}
    if not here:
        return {**out, "kind": "no_client"}
    return {**out, "kind": "ok", "pid": here[0]}


# -- «Поднять сессию»: the fix beside the diagnosis (#1231) -------------------

def credential_state(settings) -> dict | None:
    """What Windows holds for logging this profile's session in, or ``None``.

    ``None`` where the question does not arise — no session named, or a machine that
    cannot be asked. The shape otherwise is `rdp_instance.credential_state`'s, and the
    only part the panel draws is whether a password is stored at all: a person who has
    never saved one is about to be asked for it by Windows, and being told so before
    the dialog appears is the difference between a prompt and a surprise.
    """
    user = profile_user(settings)
    if not user:
        return None
    try:
        import rdp_instance                # noqa: PLC0415 — Windows-only, pywin32
        # ASKED ABOUT THIS PROFILE'S OWN ADDRESS (#1263). Windows keys a saved RDP
        # password by the address, so asking about the default one would answer for
        # whichever profile happens to sit there — which is the whole fault this is on
        # the other side of. The address comes off the port, exactly as the bring-up
        # works it out, so the reading and the connection can never disagree.
        port = settings.opt_int("daemon_port", low=1, high=65535)
        return rdp_instance.credential_state(user, rdp_instance.host_for(port))
    except Exception:                      # noqa: BLE001 — a reading, not the page
        return None


def bring_up(settings, say=None) -> int:
    """Create this profile's Windows session and start its client and daemon in it.

    The panel used to refuse this and print a command line for the person to run
    (#1231). It refused for no better reason than that nobody had wired the call: the
    whole sequence is `tools/rdp_instance.py`'s and it has always run unattended —
    session, client, daemon, console back where it was.

    **Blocks for minutes.** An RDP logon, a game launcher that may decide to update, and
    a daemon that waits for the client to finish loading; call it off the Tk thread and
    hand in ``say`` so the person can watch it happen in the log.

    Where the password comes from is not decided here and deliberately so: a *sealed*
    credential is used silently, a *readable* one is sealed on the way past, and with
    neither, Windows itself asks and nothing is stored
    (docs/research/rdp-session-credentials.md). The panel never sees a password in any
    of the three.

    Returns `rdp_instance.bring_up`'s exit code — ``0`` when the second instance
    answered a Lua chunk at the end of it, which is the only proof worth having.
    """
    user = profile_user(settings)
    if not user:
        raise LookupError("this profile's client is the one on this desktop")
    import rdp_instance                    # noqa: PLC0415 — Windows-only, pywin32
    port = settings.opt_int("daemon_port", low=1, high=65535)
    try:
        return rdp_instance.bring_up(user, port, say=say)
    except SystemExit as exc:
        # A command-line tool says "this cannot go on" by leaving; in a panel thread
        # that is a thread that stops with nothing said, because SystemExit is not an
        # Exception and no `except` above catches it.
        raise RuntimeError(str(exc) or "the session could not be brought up") from exc
    finally:
        # The session, the client and the process list have all just changed; the
        # shared reading is up to two seconds old and would tell the person nothing
        # happened (:data:`MACHINE_TTL_SEC`).
        game_link.forget_machine_state()
