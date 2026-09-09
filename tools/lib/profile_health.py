r"""One light per profile, and there are exactly THREE of them — the rule, alone.

**The panel IS the link.** There is no daemon to be up, no watcher to be elected, no
supervisor to report on: a running panel holds the client itself, so «the panel works»
and «the connection works» are one sentence. What is left to say about a profile is the
only thing a person can act on:

======  ==========================================  ================================
colour  what it means                                what to do
======  ==========================================  ================================
RED     no client process was found                  start the client
AMBER   there is a client and no traffic from it     it is BROKEN — see below
GREEN   the game server answered us                  nothing
======  ==========================================  ================================

**AMBER IS A DIAGNOSIS, NEVER A RESTING STATE.** The operator's words, and they are the
whole design: «если клиент жив, но нет сигнала, значит одно из двух: или клиент завис,
или косяк в реализации подключения, и это нужно исправлять». So amber always carries
WHICH of the two it is, because the cures are opposites — one is a client to restart,
the other is our own code to fix, and restarting a client over our own bug is six
pointless relaunches (#1268) done again.

The two are told apart by two INDEPENDENT readings, and neither of them is a socket:

* **does a chunk land?** The panel runs one trivial line in the client's Lua VM and it
  comes back. No server is involved, so this is a reading of OUR plumbing — the attach,
  the hijack, the il2cpp resolution — and of nothing else.
* **does the SERVER answer?** Ask the game about a warzone that is not this account's.
  Its own it answers out of its own memory; a foreign one is a real round trip, and a
  client whose socket the far end has closed cannot make it. Measured on a healthy
  client: 27 answers out of 27, every one inside a second (#1910).

  (The server CLOCK is not a substitute and was tried: `GetServerTime()` is the local
  tick plus an offset fixed at login, so it advances happily in a client that is
  receiving nothing.)

Which gives the ladder in :func:`verdict`, and the three amber reasons it can name:

* :data:`CLIENT_HUNG`    — nothing lands and the client's own window is not answering
                           Windows either. The process is wedged: restart it.
* :data:`NO_CONNECTION`  — nothing lands and the client is otherwise alive. **That is
                           ours.** Say so, fix it, and never restart a client over it.
* :data:`NO_TRAFFIC`     — chunks land and the server does not answer. The client is
                           deaf: restart it.
* :data:`NOT_IN_GAME`    — chunks land, the server does not answer, and the client has
                           told us ITSELF that it is not logged in: asked what time it
                           is, it handed out its own uptime instead of a clock
                           (`game_clock.LOGIN_SCREEN`, #1299). A narrowing of
                           `NO_TRAFFIC` in the one direction a person cannot see from
                           «нет связи»: the panel is fine, the client is up, and the
                           account is sitting outside the game — stuck at login, or
                           waiting on a door that is shut (#2060).
* :data:`KICKED`         — chunks land and the client is showing the game's own «вход с
                           другого устройства» modal (`tools/lib/game_kick.py`, key
                           `E100083`). **The one reason that outranks green** (#2061):
                           the account is being played somewhere else, this client is
                           off the server, and the last probe that answered says nothing
                           about now. Restarting is not the cure either — a kick has an
                           author, so `panel/runtime/recovery.py` leaves it alone — but
                           the light may not say «всё хорошо» while nothing arrives.
* :data:`MAINTENANCE`    — chunks land, the server does not answer, and the client is
                           showing the game's OWN «server under maintenance» message
                           (`tools/lib/game_maintenance.py`). Nothing is broken and
                           there is nothing to fix: the door is shut, wait. It is a
                           NARROWING of `NO_TRAFFIC` and never of green — a server that
                           has just answered is playing, whatever dialog is on screen —
                           because the expensive mistake here is telling somebody their
                           working account is closed (#1982).

WHAT IS DELIBERATELY NOT HERE ANY MORE (#1911). The socket table decides nothing: it
cannot say which conversation is the game, and for a whole night it called a healthy
client dead while the server was answering every probe. `unknown`, `unread`,
`not confirmed`, `daemon none`, `daemon stale`, `up but no client`, `online/offline/lost`
are all gone with it. A reading nobody has taken yet is AMBER — «есть клиент, трафик не
доказан» — and not a fourth colour, because a fourth colour is a colour nobody reads.

WHY IT IS HERE AND NOT IN THE PANEL. The panel is one reader of this and a tool run from
a shell is another, and two implementations of one rule is how two answers come apart six
months later. This module answers in **ids**: the colour and the reason are strings the
caller words for itself. Nothing here may grow a translator.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The three colours, as ids. The pixels are the front-end's — the window paints a dot on
#: the notebook tab, the phone a CSS class on the picker — and neither decides WHICH one.
OK = "ok"
WARN = "warn"
BAD = "bad"

#: WHY, as ids. Four, and each names an act.
NO_CLIENT = "no_client"          # red:   there is no client process
NO_SESSION = "no_session"        # red:   …and nobody is logged on to the session it needs
CLIENT_HUNG = "client_hung"      # amber: it is there and it is wedged
NO_CONNECTION = "no_connection"  # amber: OUR side cannot drive it
NO_TRAFFIC = "no_traffic"        # amber: we drive it and the server says nothing
NOT_IN_GAME = "not_in_game"      # amber: it drives fine and says it is not logged in
KICKED = "kicked"                # amber: the account was taken by another device (#2061)
MAINTENANCE = "maintenance"      # amber: the server is SHUT — wait, do not fix (#1982)
TRAFFIC = "traffic"              # green

#: Does a chunk reach the client's Lua VM? Our own plumbing, no server involved.
LANDING = "landing"
NOT_LANDING = "not_landing"
PLUMBING_UNASKED = "plumbing_unasked"

#: Does the game SERVER answer? The foreign-warzone probe, and nothing inferred.
ANSWERING = "answering"
SILENT = "silent"
SERVER_UNASKED = "server_unasked"


@dataclass(frozen=True)
class Health:
    """One profile's light: the colour, why, and the readings that decided it.

    The readings are carried along rather than thrown away — a light with no explanation
    leaves a person looking at amber with no way to tell whether to restart the client or
    to open the log and find our bug. Every field is an id; the words belong to whoever
    draws.
    """

    colour: str
    reason: str
    running: bool = False
    plumbing: str = PLUMBING_UNASKED
    server: str = SERVER_UNASKED
    responding: bool = True
    error: str = ""              # what the last attempt to drive the client said

    @property
    def ok(self) -> bool:
        return self.colour == OK


def verdict(*, running: bool, plumbing: str = PLUMBING_UNASKED,
            server: str = SERVER_UNASKED, responding: bool = True,
            error: str = "", maintenance: bool = False,
            in_game: "bool | None" = None, kicked: bool = False,
            session_missing: bool = False) -> Health:
    """The one light for one profile, from readings somebody else has already taken.

    A pure function of ids: no socket, no round trip, no clock. Everything it judges is
    read by the callers that were reading it anyway, so drawing a light costs nothing.

    THE ORDER IS THE RULE, worst first:

    1. **no client process** → red. Nothing else can be true or false about it, and
       it is NARROWED by ``session_missing`` (#2677): a profile that drives a client in
       another Windows session, with nobody logged on to it, has no client and no way to
       get one — no crash, no kick, nothing on this machine to restart. Same colour,
       because the account is equally not playing; a different reason, because the act is
       a person's (bring the session up) and not the panel's.
    2. **a chunk does not land, and the window is hung** → amber, the client is wedged.
    3. **a chunk does not land** → amber, and it is OUR fault until proven otherwise.
    4. **the client is showing the game's own «вход с другого устройства» modal** →
       amber, and it is named (#2061). **Above green, and it is the only narrowing that
       is** — the person's words: «состояние зеленым быть не может, т.к. трафика нет».
       A kicked client has been taken off the server: it goes on drawing, its getters
       answer out of what they last received and its sends return `true` while nothing
       arrives (`tools/lib/game_kick.py`), so a probe that answered before the kick is
       still inside its shelf life and green means «somebody else is playing this
       account». Maintenance and «not logged in» sit BELOW green because there a green
       light is a client that is demonstrably talking; here it is a stale reading.
    5. **the server answered** → green. The only thing that earns it.
    6. **the client is showing the game's own maintenance message** → amber, and it is
       named: the server is shut. Below green on purpose (#1982), see above.
    7. **the client says it is not logged in** → amber, and it is named too (#2060).
       ``in_game`` is `game_clock`'s three-valued answer and only ``False`` counts: that
       is the client's OWN evidence (it answered, with an uptime instead of a clock).
       ``None`` means nobody could ask, which is not evidence of anything and falls
       through to the amber below — the two must never be folded together.
    8. otherwise → amber. Chunks land, the server has not answered — or has not been
       asked yet, which is the same amber: an unasked question is not a green light.
    """
    def made(colour: str, reason: str) -> Health:
        return Health(colour, reason, running=bool(running), plumbing=plumbing,
                      server=server, responding=bool(responding), error=error)

    if not running:
        return made(BAD, NO_SESSION if session_missing else NO_CLIENT)
    if plumbing == NOT_LANDING:
        return made(WARN, CLIENT_HUNG if not responding else NO_CONNECTION)
    if kicked:
        return made(WARN, KICKED)
    if server == ANSWERING:
        return made(OK, TRAFFIC)
    if maintenance:
        return made(WARN, MAINTENANCE)
    if in_game is False:
        return made(WARN, NOT_IN_GAME)
    return made(WARN, NO_TRAFFIC)


def unread(error: str = "") -> Health:
    """A profile nothing has read yet: there is no client until something says there is.

    Red rather than amber, and that is the change #1911 made deliberate: amber means «a
    client is there and the traffic is not», so it may not double as «I have not looked».
    A front-end drawing before the first poll shows the same thing a closed game shows,
    and the first poll — eight seconds at the outside — corrects it.
    """
    return Health(BAD, NO_CLIENT, error=error)
