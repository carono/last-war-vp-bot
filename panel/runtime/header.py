"""The status header: who this character is, and where they are standing right now.

WHAT IT IS. The strip along the top of the web panel, drawn on every screen: the
character's name, the HQ level, the warzone the client is looking at, and WHERE IN THE
CLIENT the player is — the base, the world map, an operation, and the window on top of
it. It is the one reading on the page that is not about a page: whatever somebody has
opened, the strip says which account is being driven and what its client is showing.

WHERE THE NUMBERS COME FROM. Two scenarios, and not one line of Lua here
(`CLAUDE.md` — the panel plays scenarios, it does not write them):

  * `actions/read_player_profile.md` — the name and the HQ level (#1991). They do not
    move: a name never changes and a level changes a few times a season.
  * `actions/read_player_place.md` — the scene, the window on top, how deep the window
    stack is, the warzone the camera is in and the account's own (#2016).

ONCE, AND THEN NOT AGAIN — THE RULE, NOT AN OPTIMISATION. `CLAUDE.md` («Читаем один раз,
дальше слушаем») forbids a background poll outright: the panel reads a thing when it
first needs it and then waits to be TOLD it changed. A clock is a safety net with a long
interval, never the mechanism, and anything that can only be learnt by asking again is a
conversation with the person, not a decision an agent makes.

So this class reads each half exactly ONCE, on the first look, and then holds what it
read with its age climbing beside it. It had a 10-second refresh for a few hours on
2026-08-27 and that was the violation this paragraph exists to prevent: the strip is on
screen on every page, so its poll would have been the most frequent thing in the panel.

WHAT ONE READ COSTS, measured live end to end through the panel's own runner: **167 / 193
/ 219 ms** for the place — the panel↔VM round trip rather than the work in the chunk,
whose own scan of the window table is 1.0 ms. The link is EXCLUSIVE, so that is time the
schedule, the robberies and the rally joins do not get. `/api/state` is asked every 2.5 s
by every open page: reading the place per poll would have held the link some 8 % of the
time, for ever.

THERE IS NO SUBSCRIPTION TO PUT IN ITS PLACE — YET. The scene and the window stack are
CLIENT state: nobody tells the server that a player opened a screen, so `rt.wire` has
nothing to carry (docs/research/player-place.md §5). Until an in-CLIENT signal is agreed
with the person, the honest strip is one reading with its age on it, and
:meth:`StatusHeader.mark_stale` is the door that signal will come through when there is
one. Nothing in the panel may call it on a timer.

DEMAND-DRIVEN, NOT A CLOCK. Nothing ticks here. :meth:`state` is what the route calls, so
a panel nobody is looking at reads nothing at all, and a page that is opened is served
what is in memory at once — a route that waited for the game would block it for a fifth
of a second.

BOTH PLAYS GO IN AT :data:`~panel.runtime.claims.DETACHED`, below every ordinary errand,
for the same reason the stock's does: a header is a page being looked at, and no line of
it is ever worth making a robbery wait. A busy link is therefore left alone
altogether, first reading included (see :meth:`StatusHeader._may_play` for what forcing
it cost).

NOTHING IS WRITTEN DOWN. Where the player is standing is worth nothing after a restart —
it has moved — so this is memory and not a table in `panel.db` (`CLAUDE.md`, «Game data
lives only in the database», which governs data meant to SURVIVE a restart).

NOTHING IS TRUSTED FROM A CLIENT THAT HAS NOT LOGGED IN. That gate is inside both
scenarios, where it costs nothing: each reads the game's own clock first and answers an
empty string when it is not an epoch. A client at the login screen answers every question
plausibly and wrongly (`tools/lib/game_clock.py`), and «уровень 1, сервер 0» drawn
confidently along the top of every screen is exactly that failure again.
"""
from __future__ import annotations

import time

from . import claims

#: The scenario that answers «who is this character», and the variable it lands in.
WHO_ACTION = "read_player_profile"
WHO_VARIABLE = "player_card"

#: The scenario that answers «where is the player in the client», and its variable.
WHERE_ACTION = "read_player_place"
WHERE_VARIABLE = "player_place"

#: How the two scenarios separate their fields.
FIELD_SEP = ";;"

#: How long to wait before ASKING AGAIN FOR A READING THAT NEVER ARRIVED, in seconds.
#: This is not a refresh interval and must never become one: it applies only while a half
#: has never been read at all — a busy link, a client at the login screen, a refused play
#: — and it stops the moment there is something to show. A reading that exists is never
#: re-taken by a clock (`CLAUDE.md`, «Читаем один раз, дальше слушаем»).
RETRY_SEC = 15.0

#: The scenes `read_player_place.md` can name. Anything else is drawn as unknown.
SCENES = ("city", "world", "pve")


def parse_place(answer: str) -> dict:
    """`read_player_place.md`'s one line as a dict, or ``{}`` when it said nothing.

    A short or unparsable line is dropped whole rather than half-read: the fields are
    positional, so a line with four of them would put the warzone under «окно».
    """
    parts = [chunk.strip() for chunk in str(answer or "").split(FIELD_SEP)]
    if len(parts) < 5 or not parts[0]:
        return {}
    scene = parts[0] if parts[0] in SCENES else "unknown"

    def number(raw: str) -> int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    return {"scene": scene, "window": parts[1], "depth": number(parts[2]),
            "server": number(parts[3]), "home": number(parts[4])}


def parse_who(answer: str) -> dict:
    """The first two fields of `read_player_profile.md`'s line — the name and the level.

    The rest of that line (power, alliance, energy, registration) belongs to the
    «Профиль» screen, which plays the same scenario for itself; the header takes what it
    draws and invents nothing.
    """
    parts = [chunk.strip() for chunk in str(answer or "").split(FIELD_SEP)]
    if len(parts) < 2 or not any(parts[:2]):
        return {}
    try:
        level = int(parts[1])
    except (TypeError, ValueError):
        level = 0
    return {"nick": parts[0], "level": level}


class StatusHeader:
    """One profile's header: the cache, and the rule for refreshing each half."""

    def __init__(self, rt, clock=time.time) -> None:
        self._rt = rt
        # WHAT THE TIME IS, as a callable: a test drives the gaps and the age without
        # sleeping, and nothing here has a clock of its own to disagree with the route's.
        self._clock = clock
        self._who: dict = {}
        self._where: dict = {}
        self._who_at = 0.0               # when each half was read, 0 = never
        self._where_at = 0.0
        self._who_reading = False        # a play is in flight
        self._where_reading = False
        self._who_hold = 0.0             # a refusal backs off until then
        self._where_hold = 0.0
        # «THIS WANTS READING» — set at birth and by :meth:`mark_stale`, cleared by a
        # reading that arrived. Kept apart from the stamps above on purpose: an event
        # that asks for a fresh reading must not make the reading the strip is CURRENTLY
        # showing look ageless, and a read that then failed must leave the old one on
        # screen with its true age.
        self._where_want = True
        self._who_want = True

    # -- what the route draws -------------------------------------------------
    def state(self, now: float | None = None) -> dict:
        """The header as it stands, and the ONE reading booked if it has not happened.

        Never blocks and never touches the game on the calling thread: the plays are
        handed to a worker by :meth:`~panel.runtime.host.PanelRuntime.play_async`, and
        this answers with whatever is already in memory.
        """
        now = self._clock() if now is None else now
        self._maybe_read(now)
        out = {
            "nick": str(self._who.get("nick") or ""),
            "level": int(self._who.get("level") or 0),
            "scene": str(self._where.get("scene") or ""),
            "window": str(self._where.get("window") or ""),
            "depth": int(self._where.get("depth") or 0),
            "server": int(self._where.get("server") or 0),
            "home": int(self._where.get("home") or 0),
            # Seconds since the PLACE was read. It is not a freshness ornament any more
            # but the strip's central fact: this reading was taken once and nothing
            # re-takes it, so the page SAYS how old it is and the person judges it. -1
            # means nothing has been read at all, which draws as words and never as
            # «база».
            "age": round(now - self._where_at, 1) if self._where_at else -1,
            "reading": self._where_reading or self._who_reading,
        }
        return out

    # -- being told it moved ---------------------------------------------------
    def mark_stale(self, place: bool = True, who: bool = False) -> None:
        """Somebody knows the reading is out of date — take it again on the next look.

        THE ONLY WAY A SECOND READING IS EVER TAKEN, and it exists so that the eventual
        in-client signal has a door to come through. It must be called BY AN EVENT — a
        push, a hook, a scenario this panel itself played that moved the client — and
        never by a clock, which is the whole of `CLAUDE.md`'s «Читаем один раз, дальше
        слушаем».
        """
        if place:
            self._where_want = True
            self._where_hold = 0.0
        if who:
            self._who_want = True
            self._who_hold = 0.0

    # -- the one reading -------------------------------------------------------
    def _maybe_read(self, now: float) -> None:
        """Read a half that has NEVER been read. There is no refresh here on purpose.

        `_where_want` / `_who_want` are «somebody asked for this», raised once at birth
        and afterwards only by :meth:`mark_stale`. There is no clock in this method and
        none may be added: the retry below is for a reading that never ARRIVED, not for
        one that got old.
        """
        want_where = self._where_want and not self._where_reading and now >= self._where_hold
        want_who = self._who_want and not self._who_reading and now >= self._who_hold
        if not (want_where or want_who) or not self._may_play():
            return
        if want_where:
            self._where_reading = True
            if not self._play(WHERE_ACTION, self._from_where):
                self._where_reading = False
                self._where_hold = now + RETRY_SEC
        if want_who:
            self._who_reading = True
            if not self._play(WHO_ACTION, self._from_who):
                self._who_reading = False
                self._who_hold = now + RETRY_SEC

    def _may_play(self) -> bool:
        """Is the link free, and is this profile allowed to press at all?

        A BUSY LINK IS WAITED OUT, INCLUDING FOR THE ONE AND ONLY READING, and that was
        tried the other way round first. Forcing the first read through — on the grounds
        that a strip which has never read anything is worth one queued play — costs TWO
        «занят — дождись завершения текущего действия» warnings per attempt, because
        `play_async` refuses out loud; at one attempt every :data:`RETRY_SEC` that is a
        pair of warning lines a quarter-minute, for as long as the boot errands run,
        written into the log somebody opened to read something else. So the strip waits,
        says «игра ещё не прочитана» while it does, and fills on the first gap in the
        link — measured at under a minute on a settled panel, where the link was busy on
        6 polls out of 24.

        Asked HERE rather than left to the claim and the gate, for the reason
        `panel/runtime/resources.py` records: both of them refuse out loud, and a page
        being opened repeatedly would otherwise write a warning line each time.
        """
        try:
            if self._rt.game.busy:
                return False
        except Exception:                # noqa: BLE001 — an unreadable link is not a
            return False                 #   licence to press either
        try:
            if self._rt.gate.blocks(WHERE_ACTION, human=False):
                return False
        except Exception:                # noqa: BLE001 — a gate that cannot answer
            return False                 #   is not a licence to press
        return True

    def _play(self, action: str, landed) -> bool:
        try:
            return bool(self._rt.play_async(action, tag="header", human=False,
                                            priority=claims.DETACHED,
                                            on_result=landed))
        except Exception:                # noqa: BLE001 — a header is never a fault
            return False

    def _from_where(self, outcome) -> None:
        """The place came back: keep it, or keep the old one with its age climbing.

        A client that answered nothing is not a client standing nowhere — the previous
        reading stays on screen and `age` says how old it is, which is the honest picture
        and the one thing a strip of dashes could not say.
        """
        self._where_reading = False
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        place = parse_place(got.get(WHERE_VARIABLE, ""))
        if not place:
            # Nothing came back, so nothing is answered: the want stays up and the retry
            # applies. What must NOT happen is the old reading being cleared — see the
            # method's docstring.
            self._where_hold = self._clock() + RETRY_SEC
            return
        self._where = place
        self._where_at = self._clock()
        self._where_want = False

    def _from_who(self, outcome) -> None:
        self._who_reading = False
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        who = parse_who(got.get(WHO_VARIABLE, ""))
        if not who:
            # Not read, so not remembered as read: the want stays up and the next look
            # after the backoff asks again.
            self._who_hold = self._clock() + RETRY_SEC
            return
        self._who = who
        self._who_at = self._clock()
        self._who_want = False
