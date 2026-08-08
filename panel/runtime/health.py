"""What the panel SAYS about a profile's one light — the words on the shared rule.

The rule is `tools/lib/profile_health.py` and this is its wording, split exactly as
`game_process.py` is split from `game_link.py` and for the same reason: a module that
answers in :class:`panel.i18n.Message` can only ever be used by the front-end that
message type belongs to.

WHAT IS HERE. One object per open profile, living on its runtime, holding the LAST
verdict the status poll made — the colour, why it is that colour, and the four readings
that decided it. Both front-ends draw out of this one object: the window puts the colour
on the profile's notebook tab and the readings in the tooltip, the phone puts the same
colour on the profile picker and the same readings behind a tap. A second copy of the
bookkeeping is a second answer waiting to disagree with the first (`recovery.py` says
the same thing about the same kind of state).

WHY IT HOLDS THE LAST READING RATHER THAN TAKING ONE. Because a light must cost nothing.
The status poll walks the socket table, pings the daemon and — on its own throttle —
asks the client whether it is in a session; all of that is paid for already, every eight
seconds, by the strip. Anything that DRAWS asks this object and gets the answer the poll
left, so a phone polling every two seconds and a window repainting on every tab switch
add no game reads at all.

**A profile nothing has read yet is AMBER**, with its own reason — never green, and
never red either. That is `profile_health.unread`, and it is the state this object is
born in: a tab drawn before the first poll, a runtime with no window behind it (a tab
launched on its own answers the web routes too), a poll that raised.
"""
from __future__ import annotations

import time

import profile_health

from .. import i18n as i18nmod
from ..i18n import Message

#: The three colours, under the names the shared rule gives them.
OK = profile_health.OK
WARN = profile_health.WARN
BAD = profile_health.BAD

#: Reason id → the locale key of the sentence that says it. One table rather than a
#: ladder of ``if``s, so a reason added to the rule cannot end up with no words: the
#: lookup falls back to `health.unread`, which is what «I have no idea» reads as anyway.
_WORDS = {
    profile_health.HEALTHY: "health.ok",
    profile_health.KICKED: "health.kicked",
    profile_health.CLIENT_OFF: "health.client_off",
    profile_health.LINK_LOST: "health.link_lost",
    profile_health.NOT_LOGGED_IN: "health.not_logged_in",
    profile_health.DAEMON_NONE: "health.daemon_none",
    profile_health.DAEMON_STALE: "health.daemon_stale",
    profile_health.LINK_UNKNOWN: "health.link_unknown",
    profile_health.SESSION_UNKNOWN: "health.session_unknown",
    profile_health.UNREAD: "health.unread",
}

#: The daemon's own reading, worded. The first three are the indicator's existing words
#: — the tooltip must not invent a second vocabulary for a state the strip already names.
_DAEMON_WORDS = {
    profile_health.DAEMON_LIVE: "daemon.warm",
    profile_health.DAEMON_IS_STALE: "daemon.stale",
    profile_health.DAEMON_IS_NONE: "daemon.none",
    profile_health.DAEMON_UNASKED: "health.unasked",
}

#: …and the session reading. «Не спрашивали» is a state of its own here too: the client
#: is only asked while there is a warm daemon and a running client to ask.
_SESSION_WORDS = {
    profile_health.IN_SESSION: "health.session.in",
    profile_health.LOGIN_SCREEN: "health.session.login",
    profile_health.SESSION_CANNOT_TELL: "health.unasked",
}


class ProfileHealth:
    """One profile's light: the last verdict, and the readings behind it.

    Written by whoever polls (the window's status poll), read by both front-ends. Plain
    attributes and no Tk: it is written from the poll's worker thread and read from the
    Tk thread and from the web server's, and a Tk variable touched off the main thread
    is a live bug in this panel (#1295) rather than a theoretical one.
    """

    __slots__ = ("_health", "_client", "_at")

    def __init__(self) -> None:
        self._health = profile_health.unread()
        #: The client's own sentence, as `game_process.probe` worded it — the tooltip's
        #: second line. `None` until something has read this profile.
        self._client: "Message | None" = None
        self._at = 0.0

    # -- writing -------------------------------------------------------------
    def update(self, probe, *, warm: bool, stale: bool, session: str,
               kicked: bool = False):
        """Take one poll's readings and keep the light they make.

        ``probe`` is `panel.runtime.game_process.Probe` — the client's state and the
        sentence for it. ``warm`` / ``stale`` are the pair the status poll already holds
        about the daemon, and they are turned into the rule's own id HERE rather than in
        the window: nothing under `panel/` should have to spell a reading's vocabulary.
        ``session`` is `game_clock.session_state`'s answer.
        """
        self._client = getattr(probe, "message", None)
        self._health = profile_health.verdict(
            link=getattr(probe, "link", profile_health.SESSION_CANNOT_TELL),
            running=bool(getattr(probe, "running", False)),
            daemon=profile_health.daemon_id(bool(warm), bool(stale)),
            session=session, kicked=bool(kicked))
        self._at = time.time()
        return self._health

    def failed(self, error: BaseException | str):
        """The reading itself blew up. Amber with a reason, never green and never red.

        The class of fault #1296 is about: «empty» and «could not read» must not be the
        same answer. The client's last sentence is kept — it is still the newest thing
        anybody knows — but the colour stops claiming anything.
        """
        self._health = profile_health.unread(str(error)[:200])
        self._at = time.time()
        return self._health

    # -- reading -------------------------------------------------------------
    @property
    def current(self):
        return self._health

    @property
    def colour(self) -> str:
        return self._health.colour

    @property
    def read_at(self) -> float:
        """When the last verdict was made; ``0.0`` while nothing has read this profile."""
        return self._at

    def message(self) -> Message:
        """WHY this colour, as a `Message` — the tooltip's first line, and the log's."""
        health = self._health
        key = _WORDS.get(health.reason, "health.unread")
        if health.reason == profile_health.UNREAD and health.error:
            return Message(key, f"not read yet: {health.error}", error=health.error)
        return Message(key, health.reason.replace("_", " "), error=health.error or "")

    def lines(self, t) -> list:
        """The tooltip, in the panel's language: why, and WHICH READING said so.

        Four lines, and the last three are the point. A light with no explanation leaves
        a person looking at red with no way to tell whether to fix the client or the
        daemon — so each reading is named beside its own answer, in the same words the
        status strip uses for it.
        """
        health = self._health
        said = [i18nmod.translated(t, self.message())]
        client = (i18nmod.translated(t, self._client) if self._client is not None
                  else t("health.unasked"))
        said.append(f"{t('health.tip.game')}: {client}")
        said.append(f"{t('health.tip.daemon')}: "
                    f"{t(_DAEMON_WORDS.get(health.daemon, 'health.unasked'))}")
        said.append(f"{t('health.tip.session')}: "
                    f"{t(_SESSION_WORDS.get(health.session, 'health.unasked'))}")
        if health.kicked:
            said.append(t("health.tip.kicked"))
        return said

    def state(self, t) -> dict:
        """The whole light as the phone wants it: a colour id and words already said.

        Worded HERE rather than in the browser, exactly as the client's own status is
        (`panel/web/api.py`): the two front-ends must not word one reading twice, and
        the phone has no locale table for `game.st.*` values that carry a pid and an
        endpoint in them.
        """
        return {"colour": self._health.colour,
                "reason": self._health.reason,
                "text": i18nmod.translated(t, self.message()),
                "tip": self.lines(t)}
