r"""One light per profile: is this account actually being played — the rule, alone.

A person with four accounts open cannot read four status strips at once, so the panel
puts **one colour on each profile's tab** (#1299). Green, amber, red — and the whole
difficulty is in what may be allowed to be green, because a light is read in a glance
and a wrong green is never looked at twice.

**GREEN IS A GUARANTEE, NOT A GUESS.** Every state below that cannot distinguish two
things is amber. That is not caution for its own sake: every incident in
`docs/research/server-link-status.md` §5 is one reading standing in for another, and each
of them produced exactly the output a healthy system produces. The four that are ruled
out here by construction:

* **a live socket of the wrong conversation.** The client keeps a control channel on a
  port of its own, and for a night one of those vouched for a game link whose every
  socket was half-closed (§2.2). `game_link.classify` is the reading, and it judges each
  conversation on its own — this module never looks at a socket itself;
* **a daemon that answers its port while nothing it sends lands.** «Warm» is a
  `socket.connect`; 9 % of «warm» readings over one measured day were taken while the
  client was not up-and-online (`docs/research/daemon-architecture.md` §3).
  `daemon_pulse.verdict` is the reading — the age of the last chunk that actually
  reached the game — and its middle answer is amber here, never green;
* **a client at the login screen.** It answers everything, plausibly: no alliance tasks,
  own server `-1`, all five robberies unspent (#1227). It cannot say what time it is,
  and `game_clock.session_state` is that question — with «could not ask» kept apart from
  «asked, and it is not in a session»;
* **an account taken by another device.** The kick survives every one of the readings
  above: one conversation stays up, the daemon goes on landing chunks, and the clock
  offset was set when the session began and outlives it (§5.3). `game_kick.read` is the
  reading, and only a positive one is acted on.

**AND «COULD NOT READ» IS ITS OWN COLOUR.** A reading that never arrived, or that blew
up, is amber with its own reason (:data:`UNREAD`) — not green, and not red either. The
two were folded together once and the person was told a backoff had fired on a reading
that had gone (#1296).

WHY IT IS HERE AND NOT IN THE PANEL. Same reason as `game_link.py`: the panel is one
reader of this and a tool run from a shell is another, and two implementations of one
rule is how two answers come apart six months later. This module answers in **ids** —
the colour and the reason are strings the caller words for itself. Nothing here may grow
a translator.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_clock  # noqa: E402
import game_link  # noqa: E402

#: The three colours, as ids. The pixels are the front-end's: the window paints a dot on
#: the notebook tab, the phone a CSS class on the picker, and neither of them decides
#: WHICH one — that is this module's only job.
#:
#: * ``OK``   — everything a reading can prove is proved: the client is on the game's own
#:              conversation, it says it is in a session, it is not kicked, and a chunk
#:              reached the game within the last few seconds.
#: * ``WARN`` — it works in part, or it cannot be told apart from working. A daemon that
#:              is down or holding a client that has gone; a link with no verdict; a
#:              session that could not be asked about; a reading that never came.
#: * ``BAD``  — it is not being played: no client, a dead link, a login screen, a kick.
OK = "ok"
WARN = "warn"
BAD = "bad"

#: WHY, as ids. Ordered here the way :func:`verdict` decides — worst first — because the
#: order IS the rule and a reader of this file should see it before the code.
#:
#: The pairing of reason to colour is the whole design and each one is an answer to
#: «what would the person do about it»:
#:
#: * ``KICKED``        — the account is being played somewhere else. Nothing to do here.
#: * ``CLIENT_OFF``    — there is no client process. Start it.
#: * ``LINK_LOST``     — the client holds a socket the server closed. Restart the client.
#: * ``NOT_LOGGED_IN`` — the client is up and sitting at the login screen. Log in.
#: * ``DAEMON_NONE``   — nothing answers the daemon's port. The game plays on; the panel
#:                       cannot press anything. PARTLY working, hence amber.
#: * ``DAEMON_STALE``  — the daemon answers and nothing it sends lands. Same colour, same
#:                       reason: the account is fine, the driving is not.
#: * ``LINK_UNKNOWN``  — the sockets make no verdict: a client 45 seconds into starting
#:                       up, or a machine that will not attribute its sockets. NOT a
#:                       fault, and never to be painted as one.
#: * ``SESSION_UNKNOWN``— the client could not be asked whether it is in a session.
#: * ``UNREAD``        — nothing has read this profile yet, or the reading failed.
KICKED = "kicked"
CLIENT_OFF = "client_off"
LINK_LOST = "link_lost"
NOT_LOGGED_IN = "not_logged_in"
DAEMON_NONE = "daemon_none"
DAEMON_STALE = "daemon_stale"
LINK_UNKNOWN = "link_unknown"
SESSION_UNKNOWN = "session_unknown"
UNREAD = "unread"
HEALTHY = "ok"

#: The daemon's three answers, under the names `daemon_pulse.verdict` gives them. Spelled
#: here so a caller can hand this module an id without importing the panel's copy.
DAEMON_LIVE = "live"
DAEMON_IS_STALE = "stale"
DAEMON_IS_NONE = "none"
#: …and a fourth for the caller that did not ask (a front-end drawing a profile whose
#: poll has not run yet). It is not «none»: nothing was asked, so nothing may be blamed.
DAEMON_UNASKED = "unasked"

#: The session reading, under `game_clock.session_state`'s names — the same aliasing, and
#: for the same reason.
IN_SESSION = game_clock.IN_SESSION
LOGIN_SCREEN = game_clock.LOGIN_SCREEN
SESSION_CANNOT_TELL = game_clock.CANNOT_TELL


@dataclass(frozen=True)
class Health:
    """One profile's light: the colour, why it is that colour, and what was read.

    The readings are carried along rather than thrown away, because a light with no
    explanation is half a tool: a person seeing red has to know whether to fix the
    client or the daemon, and the only honest answer is the reading that decided it.
    Every field is an id — the words belong to whoever draws.
    """

    colour: str
    reason: str
    link: str = game_link.UNKNOWN
    running: bool = False
    daemon: str = DAEMON_UNASKED
    session: str = SESSION_CANNOT_TELL
    kicked: bool = False
    error: str = ""              # what blew up, when the reason is UNREAD

    @property
    def ok(self) -> bool:
        return self.colour == OK


def verdict(*, link: str, running: bool, daemon: str = DAEMON_UNASKED,
            session: str = SESSION_CANNOT_TELL, kicked: bool = False,
            error: str = "", read: bool = True) -> Health:
    """The one light for one profile, from readings somebody else has already taken.

    Deliberately a pure function of ids: no socket, no round trip, no clock. Everything
    it judges is read by the callers that were reading it anyway — the panel's status
    poll takes all four every eight seconds — so a light costs nothing beyond what the
    status strip already cost.

    ``read`` is «has anything read this profile at all»: ``False`` is the state a tab
    is in before its first poll, and it is amber, not green and not red.

    THE ORDER IS THE RULE, and it is «what would the person do about it», worst first:

    1. **could not read** → amber. A reading that never came proves nothing either way.
    2. **kicked** → red. It outranks every other reason: the account is somewhere else,
       and every reading below can look perfectly healthy while it is (§5.3).
    3. **no client** → red.
    4. **link lost** → red. Positive evidence the server hung up.
    5. **at the login screen** → red. The process is up and the account is not playing.
    6. **daemon down / stale** → amber. The game plays; the panel cannot drive it.
    7. **link unknown** → amber. No verdict is not a fault (`game_link.classify`).
    8. **session not asked** → amber. The last thing between «looks fine» and «is fine».
    9. otherwise green.

    Steps 6 and 7 sit in that order on purpose: with the daemon down the session cannot
    be asked at all, so it would otherwise be the daemon's fault reported as a mystery.
    """
    def made(colour: str, reason: str) -> Health:
        return Health(colour, reason, link=link, running=bool(running), daemon=daemon,
                      session=session, kicked=bool(kicked), error=error)

    if not read or error:
        return made(WARN, UNREAD)
    if kicked:
        return made(BAD, KICKED)
    if not running or link == game_link.OFFLINE:
        return made(BAD, CLIENT_OFF)
    if link == game_link.LOST:
        return made(BAD, LINK_LOST)
    if session == LOGIN_SCREEN:
        return made(BAD, NOT_LOGGED_IN)
    if daemon == DAEMON_IS_NONE:
        return made(WARN, DAEMON_NONE)
    if daemon == DAEMON_IS_STALE:
        return made(WARN, DAEMON_STALE)
    if daemon != DAEMON_LIVE:
        # NOBODY ASKED about the daemon — a front-end drawing a profile whose poll has
        # not run, or a caller that has only half the readings. That is the same amber
        # as «not read yet», and it is the answer a green light must never be given by
        # default: an argument left out may not be worth more than an argument that
        # came back healthy.
        return made(WARN, UNREAD)
    if link != game_link.ONLINE:
        return made(WARN, LINK_UNKNOWN)
    if session != IN_SESSION:
        return made(WARN, SESSION_UNKNOWN)
    return made(OK, HEALTHY)


def unread(error: str = "") -> Health:
    """The light of a profile nothing has read yet — amber, with its own reason.

    Its own constructor rather than a bare :func:`verdict` call, because «nobody has
    asked» is a state three callers need to produce (a front-end drawing a profile
    before its first poll, a poll that raised, a runtime with no window behind it) and
    it must look the same from all three.
    """
    return Health(WARN, UNREAD, error=str(error or ""))


def daemon_id(warm: bool, stale: bool) -> str:
    """The daemon's reading as an id, from the pair the panel's status poll already holds.

    `GameLink.health` answers in the same three words; this is for the caller that has
    only the booleans (`up()` and the pid comparison beside it) and would otherwise
    invent a fourth spelling of them.
    """
    if not warm:
        return DAEMON_IS_NONE
    return DAEMON_IS_STALE if stale else DAEMON_LIVE
