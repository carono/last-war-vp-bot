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
    profile_health.CLIENT_HUNG: "health.client_hung",
    profile_health.NO_CONNECTION: "health.no_connection",
    profile_health.NO_TRAFFIC: "health.no_traffic",
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
    def update(self, probe, *, plumbing: str = profile_health.PLUMBING_UNASKED,
               server: str = profile_health.SERVER_UNASKED, responding: bool = True,
               error: str = "", maintenance: bool = False):
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
        """
        self._client = getattr(probe, "message", None)
        self._health = profile_health.verdict(
            running=bool(getattr(probe, "running", False)), plumbing=plumbing,
            server=server, responding=bool(responding), error=error,
            maintenance=bool(maintenance))
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
    def read_at(self) -> float:
        """When the last verdict was made; ``0.0`` while nothing has read this profile."""
        return self._at

    def message(self) -> Message:
        """WHY this colour, as a `Message` — the tooltip's first line, and the log's."""
        health = self._health
        key = _WORDS.get(health.reason, "health.no_client")
        return Message(key, health.reason.replace("_", " "), error=health.error or "")

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
        said.append(f"{t('health.tip.server')}: "
                    f"{t(_SERVER_WORDS.get(health.server, 'health.unasked'))}")
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
                "tip": self.lines(t)}
