"""What the panel SAYS about a profile's one light — the words on the shared rule.

The rule is `tools/lib/profile_health.py` and this is its wording, split exactly as
`game_process.py` is split from `game_link.py` and for the same reason: a module that
answers in :class:`panel.i18n.Message` can only ever be used by the front-end that
message type belongs to.

WHAT IS HERE. One object per open profile, living on its runtime, holding the LAST
verdict the status poll made — the colour, why it is that colour, and the readings that
decided it. Both front-ends draw out of this one object: the window puts the colour on
the profile's notebook tab and the readings in the tooltip, the phone puts the same
colour on the profile picker and the same readings behind a tap. A second copy of the
bookkeeping is a second answer waiting to disagree with the first.

WHY IT HOLDS THE LAST READING RATHER THAN TAKING ONE. Because a light must cost nothing.
The status poll finds the client, reads how long ago a chunk landed and — on its own
throttle — asks the game server a question only it can answer; all of that is paid for
already by the strip. Anything that DRAWS asks this object and gets the answer the poll
left, so a phone polling every two seconds adds no game reads at all.

**THREE COLOURS AND NO FOURTH** (#1911). A profile nothing has read yet is RED — «no
client until something says there is one» — and the first poll corrects it within eight
seconds. Amber means one thing only: there IS a client and its traffic is not there, and
the tooltip says which of the two halves failed.
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
#: ladder of ``if``s, so a reason added to the rule cannot end up with no words.
_WORDS = {
    profile_health.TRAFFIC: "health.traffic",
    profile_health.NO_CLIENT: "health.no_client",
    profile_health.NO_SESSION: "health.no_session",
    profile_health.CLIENT_HUNG: "health.client_hung",
    profile_health.NO_CONNECTION: "health.no_connection",
    profile_health.NO_TRAFFIC: "health.no_traffic",
    profile_health.NOT_IN_GAME: "health.not_in_game",
    profile_health.KICKED: "health.kicked",
    profile_health.MAINTENANCE: "health.maintenance",
}

#: Does a chunk land in the client's Lua VM — our own plumbing, worded.
_PLUMBING_WORDS = {
    profile_health.LANDING: "health.plumbing.landing",
    profile_health.NOT_LANDING: "health.plumbing.not_landing",
    profile_health.PLUMBING_UNASKED: "health.unasked",
}

#: …and whether the game SERVER answers, which is the only thing that earns green.
_SERVER_WORDS = {
    profile_health.ANSWERING: "health.server.answering",
    profile_health.SILENT: "health.server.silent",
    profile_health.SERVER_UNASKED: "health.unasked",
}


def _span(t, seconds: float) -> str:
    """«5 мин» — a span in the panel's own words, off the keys the phone already uses.

    One vocabulary for the two front-ends: `web.ui.unit.*` is what the browser says and
    what this says, so «4 мин назад» reads the same in the window and on the phone.
    """
    n = max(0, int(round(seconds)))
    if n < 60:
        return t("web.ui.unit.sec", n=n)
    if n < 3600:
        return t("web.ui.unit.min", n=int(round(n / 60)))
    if n < 86400:
        return t("web.ui.unit.hour", n=int(round(n / 3600)))
    return t("web.ui.unit.day", n=int(round(n / 86400)))


class ProfileHealth:
    """One profile's light: the last verdict, and the readings behind it.

    Written by whoever polls (the window's status poll), read by both front-ends. Plain
    attributes and no Tk: it is written from the poll's worker thread and read from the
    Tk thread and from the web server's, and a Tk variable touched off the main thread
    is a live bug in this panel (#1295) rather than a theoretical one.
    """

    __slots__ = ("_health", "_client", "_at", "_server_at", "_user")

    def __init__(self) -> None:
        self._health = profile_health.unread()
        #: The client's own sentence, as `game_process.probe` worded it — the tooltip's
        #: second line. `None` until something has read this profile.
        self._client: "Message | None" = None
        self._at = 0.0
        #: …and the session's login, for the same reason (see :meth:`update`).
        self._user = ""
        #: When the game SERVER last answered — `0.0` while it never has. Green rests on
        #: that moment (#2061), so both front-ends draw its age beside the colour.
        self._server_at = 0.0

    # -- writing -------------------------------------------------------------
    def update(self, probe, *, plumbing: str = profile_health.PLUMBING_UNASKED,
               server: str = profile_health.SERVER_UNASKED, responding: bool = True,
               error: str = "", maintenance: bool = False,
               in_game: "bool | None" = None, kicked: bool = False,
               server_at: float = 0.0):
        """Take one poll's readings and keep the light they make.

        ``probe`` is `panel.runtime.game_process.Probe` — whether a client of this
        profile is running, and the sentence for it. ``plumbing`` is whether a chunk has
        landed lately (`panel.runtime.link.GameLink.plumbing`), ``server`` whether the
        game server has answered an active probe lately. Both are readings somebody else
        already took: drawing may never be the thing that spends a round trip.

        ``maintenance`` is «the client is showing the game's own «server under
        maintenance» message» (`tools/lib/game_maintenance.py`, #1982). It only ever
        NARROWS the amber the light was going to be anyway — nothing broken, nothing to
        fix, wait — so a profile whose server answers stays green with it set.

        ``kicked`` is «the client is showing the game's own «вход с другого устройства»
        modal» (`tools/lib/game_kick.py`, #2061), and it is the one reading that OUTRANKS
        green: a taken account goes on answering out of what it last received, so the
        probe inside its shelf life would otherwise leave the light green while nothing
        at all is arriving. The person's words: «состояние зеленым быть не может, т.к.
        трафика нет».

        ``in_game`` is the same shape and for the same reason (#2060): ``False`` only
        when the CLIENT said so, ``None`` when nobody could ask. It turns the amber a
        person cannot read — «нет связи», which is equally what our own broken plumbing
        looks like — into «клиент запущен, но в игру не вошёл».
        """
        self._client = getattr(probe, "message", None)
        #: The Windows login this profile looks in, kept for the SENTENCE (#2677):
        #: «нет сессии Windows — пользователь {user} не залогинен» names it, and a
        #: `Message` built without it prints the placeholder itself.
        self._user = str(getattr(probe, "user", "") or "")
        self._server_at = float(server_at or 0.0)
        self._health = profile_health.verdict(
            running=bool(getattr(probe, "running", False)), plumbing=plumbing,
            server=server, responding=bool(responding), error=error,
            maintenance=bool(maintenance), in_game=in_game, kicked=bool(kicked),
            session_missing=bool(getattr(probe, "no_session", False)))
        self._at = time.time()
        return self._health

    def failed(self, error: BaseException | str):
        """The reading itself blew up — the light says «no client» and names the fault.

        There is no colour for «could not read» any more (#1911): three colours means
        three, and the honest thing to show for a reading that never came is the same
        thing an absent client shows, with the error in the tooltip.
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
    def server_age(self) -> float:
        """Seconds since the server last answered — `-1.0` while it never has (#2061).

        The reading GREEN rests on, and the one a colour cannot carry: an answer four
        minutes old and one four seconds old paint the same dot. Both front-ends draw it,
        and neither works it out for itself.
        """
        return time.time() - self._server_at if self._server_at else -1.0

    @property
    def read_at(self) -> float:
        """When the last verdict was made; ``0.0`` while nothing has read this profile."""
        return self._at

    def message(self) -> Message:
        """WHY this colour, as a `Message` — the tooltip's first line, and the log's."""
        health = self._health
        key = _WORDS.get(health.reason, "health.no_client")
        return Message(key, health.reason.replace("_", " "),
                       error=health.error or "", user=self._user)

    def lines(self, t) -> list:
        """The tooltip, in the panel's language: why, and WHICH READING said so.

        Four lines, and the last three are the point. Amber with no explanation leaves a
        person unable to tell whether to restart the client or to go and find our bug —
        so each reading is named beside its own answer.
        """
        health = self._health
        said = [i18nmod.translated(t, self.message())]
        client = (i18nmod.translated(t, self._client) if self._client is not None
                  else t("health.unasked"))
        said.append(f"{t('health.tip.game')}: {client}")
        said.append(f"{t('health.tip.plumbing')}: "
                    f"{t(_PLUMBING_WORDS.get(health.plumbing, 'health.unasked'))}")
        # …AND HOW LONG AGO IT ANSWERED (#2061). The window has the same right to it as
        # the phone: green rests on a moment with a five-minute shelf life, and the
        # tooltip is where this front-end says WHICH READING decided the colour.
        answered = t(_SERVER_WORDS.get(health.server, "health.unasked"))
        age = self.server_age
        if age >= 0:
            answered += " · " + t("web.ui.ago", span=_span(t, age))
        said.append(f"{t('health.tip.server')}: {answered}")
        if health.error:
            said.append(f"{t('health.tip.error')}: {health.error}")
        return said

    def state(self, t) -> dict:
        """The whole light as the phone wants it: a colour id and words already said.

        Worded HERE rather than in the browser, exactly as the client's own status is
        (`panel/web/api.py`): the two front-ends must not word one reading twice.
        """
        return {"colour": self._health.colour,
                "reason": self._health.reason,
                "text": i18nmod.translated(t, self.message()),
                # HOW OLD THE ANSWER IS (#2061) — a number of seconds, worded by whoever
                # draws it. Green has a five-minute shelf life, so a light with no age on
                # it is a statement about a moment presented as a statement about now.
                "server_age": round(self.server_age, 1),
                "tip": self.lines(t)}
