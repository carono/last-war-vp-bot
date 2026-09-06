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

DEMAND-DRIVEN, NOT A CLOCK. Nothing ticks here. :meth:`state` is what first raises the
demand, and :meth:`on_settled` spends it when a busy boot errand releases the link. A
panel nobody is looking at therefore reads nothing at all, while a page that looked once
cannot be starved by a continuously busy green client. The route itself is still served
from memory at once — waiting for the game there would block it for a fifth of a second.

BOTH PLAYS GO IN AT :data:`~panel.runtime.claims.DETACHED`, below every ordinary errand,
for the same reason the stock's does: a header is a page being looked at, and no line of
it is ever worth making a robbery wait. A busy link is therefore left alone
altogether, first reading included (see :meth:`StatusHeader._may_play` for what forcing
it cost).

THE PLACE IS MEMORY, THE CHARACTER IS REMEMBERED. Where the player is standing is worth
nothing after a restart — it has moved — so that half is memory and not a table in
`panel.db` (`CLAUDE.md`, «Game data lives only in the database», which governs data meant
to SURVIVE a restart). The character is the opposite: a name never changes and a level
changes a few times a season, so it is written down on every reading and picked up again
on the first look (:meth:`StatusHeader._seed`, `panel/runtime/player_card.py`). That is
what stops a lost link, a kick (#2071) or a restart from emptying the strip about an
account the panel knows: nothing is CLEARED by a failure — a reading that came back with
nothing leaves the last one on screen, and only a better reading replaces it (#2075).

A NEW LOGIN IS A NEW FACT, and it is the one thing that re-reads the character. The status
poll already knows when a client goes from the login screen into the game
(`panel/runtime/status.py`), and it opens the door below on that transition — an EVENT, not
a clock.

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

#: A header read is two short Lua questions (measured 167–219 ms). If its result never
#: reaches us, the in-flight bit is not evidence for ever: after this ceiling the next
#: free-link event may book it again. This is the same lost-reservation rule as the
#: resource reading; it is recovery from a missing callback, not a refresh clock.
READ_LOST_SEC = 30.0

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
    """The name, the level, and WHO this is — from `read_player_profile.md`'s line.

    The rest of that line (power, alliance, energy, registration) belongs to the
    «Профиль» screen, which plays the same scenario for itself; the header takes what it
    draws and invents nothing.

    The last two fields are the character's id and which upload of their picture is
    current (#2061). They are what finds the AVATAR on disk — a uid alone does not name
    the file — and they are read here rather than asked for separately because the
    header was playing this scenario already. Neither leaves the panel: what travels to
    the front-end is a link into `/api/avatar` (`panel/runtime/player_card.py`).

    A line written before those fields existed simply has none, and answers `0`/`""`,
    which draws as an account with no face.
    """
    parts = [chunk.strip() for chunk in str(answer or "").split(FIELD_SEP)]
    if len(parts) < 2 or not any(parts[:2]):
        return {}

    def number(raw: str) -> int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    return {"nick": parts[0], "level": number(parts[1]),
            "uid": parts[7] if len(parts) > 7 else "",
            "pic_ver": number(parts[8]) if len(parts) > 8 else 0}


class StatusHeader:
    """One profile's header: the cache, and the rule for refreshing each half."""

    def __init__(self, rt, clock=time.time) -> None:
        self._rt = rt
        # WHAT THE TIME IS, as a callable: a test drives the gaps and the age without
        # sleeping, and nothing here has a clock of its own to disagree with the route's.
        self._clock = clock
        self._who: dict = {}
        #: The player's own face, as a link — worked out ONCE per reading, on the worker
        #: thread that took it. Finding a photo walks a few thousand md5 sums the first
        #: time a character is asked about (`tools/lib/player_photos.py`), and `state()`
        #: is called by every poll of every open page: that is the one place it may not
        #: happen.
        self._avatar = ""
        self._where: dict = {}
        self._who_at = 0.0               # when each half was read, 0 = never
        self._where_at = 0.0
        self._who_reading = False        # a play is in flight
        self._where_reading = False
        self._who_reading_at = 0.0
        self._where_reading_at = 0.0
        self._who_hold = 0.0             # a refusal backs off until then
        self._where_hold = 0.0
        # «THIS WANTS READING» — set at birth and by :meth:`mark_stale`, cleared by a
        # reading that arrived. Kept apart from the stamps above on purpose: an event
        # that asks for a fresh reading must not make the reading the strip is CURRENTLY
        # showing look ageless, and a read that then failed must leave the old one on
        # screen with its true age.
        self._where_want = True
        self._who_want = True
        # WHETHER THE LAST KNOWN CARD HAS BEEN PICKED UP YET (#2075). The name, the level
        # and the face were written down the last time this account WAS read
        # (`panel/runtime/player_card.py`), so a panel whose client is closed, kicked or
        # not started yet draws the character it knows instead of a blank strip. Done on
        # the first look rather than here, because `rt.store` opens the database lazily
        # and a runtime is built before its profile has one.
        self._seeded = False

    # -- what the route draws -------------------------------------------------
    def state(self, now: float | None = None) -> dict:
        """The header as it stands, and the ONE reading booked if it has not happened.

        Never blocks and never touches the game on the calling thread: the plays are
        handed to a worker by :meth:`~panel.runtime.host.PanelRuntime.play_async`, and
        this answers with whatever is already in memory.
        """
        now = self._clock() if now is None else now
        self._seed()
        self._maybe_read(now)
        out = {
            "nick": str(self._who.get("nick") or ""),
            "level": int(self._who.get("level") or 0),
            # THE FACE, as a link and never as bytes or as an id (#2061). Empty for a
            # character who never uploaded a photo: the client's own object carries no
            # head-icon id, so «no picture» is the honest answer and the page draws the
            # account's initial rather than somebody else's art.
            "avatar": self._avatar,
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
    def confirm_server(self, server) -> None:
        """Install the warzone a completed jump already confirmed.

        This runs synchronously in the link's completion chain, before the jump button
        is released. It is not a read and books no read: asking the game for a fact the
        landing answer already contains creates exactly the stale-header gap this door
        closes (#2593).
        """
        try:
            server = int(server or 0)
        except (TypeError, ValueError):
            return
        if server <= 0:
            return
        self._where["server"] = server
        self._where_at = self._clock()
        self._where_want = False
        self._where_hold = 0.0

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

    def on_settled(self) -> None:
        """A game run just released the link: spend the first free gap on the header.

        This is the missing half of demand-driven reading. `/api/state` may look while
        every boot errand has the link and be refused forever; release is the event that
        proves it is free. No timer and no extra game poll is introduced.
        """
        self._maybe_read(self._clock())

    # -- what was known before this panel started ------------------------------
    def _seed(self) -> None:
        """The last card this account was read with, before the game is asked (#2075).

        WHY THERE IS ONE. The character half of the strip is not a place: a name does not
        change, and a level changes a few times a season, so what was read once is still
        true when the link goes down, when the account is kicked (#2071) and after the
        panel restarts. It was already being written down for the account picker, and the
        header was the one reader that ignored it — so a lost client emptied the strip and
        the person was shown «no account» about an account the panel knew perfectly well.

        It is a FLOOR and never a verdict: the wants stay up, so the first free moment on
        the link still takes a real reading and overwrites this one. A card with no name is
        no card, and leaves the strip exactly as empty as it was.
        """
        if self._seeded:
            return
        self._seeded = True
        try:
            from . import player_card as cardmod

            card = cardmod.recall(getattr(self._rt, "store", None))
        except Exception:                # noqa: BLE001 — a memory, never the page
            return
        nick = str(card.get("nick") or "")
        if not nick:
            return
        self._who = {"nick": nick, "level": int(card.get("level") or 0),
                     "uid": str(card.get("uid") or ""),
                     "pic_ver": int(card.get("pic_ver") or 0)}
        # …and the face with it. The lookup walks the face folder once per process and is
        # a dictionary hit ever after (`player_card.face_link`), and this runs on the
        # route that already resolves exactly this link for every CLOSED profile in the
        # account list — never on the Tk thread, which does not call `state()` at all.
        try:
            self._avatar = cardmod.face_link(self._who["uid"], self._who["pic_ver"])
        except Exception:                # noqa: BLE001 — a picture, never the page
            self._avatar = ""

    # -- the one reading -------------------------------------------------------
    def _maybe_read(self, now: float) -> None:
        """Read a half that has NEVER been read. There is no refresh here on purpose.

        `_where_want` / `_who_want` are «somebody asked for this», raised once at birth
        and afterwards only by :meth:`mark_stale`. There is no clock in this method and
        none may be added: the retry below is for a reading that never ARRIVED, not for
        one that got old.
        """
        # A callback can be lost when a worker loses its lease or its UI hand-off during
        # shutdown. Its boolean is a reservation, not a permanent fact: let it expire.
        if (self._where_reading and self._where_reading_at
                and now - self._where_reading_at >= READ_LOST_SEC):
            self._where_reading = False
        if (self._who_reading and self._who_reading_at
                and now - self._who_reading_at >= READ_LOST_SEC):
            self._who_reading = False
        want_where = self._where_want and not self._where_reading and now >= self._where_hold
        want_who = self._who_want and not self._who_reading and now >= self._who_hold
        if not (want_where or want_who) or not self._may_play():
            return
        if want_where:
            self._where_reading = True
            self._where_reading_at = now
            if not self._play(WHERE_ACTION, self._from_where):
                self._where_reading = False
                self._where_hold = now + RETRY_SEC
        if want_who:
            self._who_reading = True
            self._who_reading_at = now
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
        self._where_reading_at = 0.0
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
        self._who_reading_at = 0.0
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        who = parse_who(got.get(WHO_VARIABLE, ""))
        if not who:
            # Not read, so not remembered as read: the want stays up and the next look
            # after the backoff asks again. What must NOT happen is the name and the level
            # being cleared (#2075) — a client at the login screen, or one that has just
            # been kicked, is not an account with no character. The strip keeps what it
            # knows until something better arrives.
            self._who_hold = self._clock() + RETRY_SEC
            return
        self._who = who
        self._who_at = self._clock()
        self._who_want = False
        # …AND IT IS WRITTEN DOWN (#2061), so this account can be drawn in the picker
        # with its name, its level and its face even when its profile is closed or
        # belongs to another window. One row per profile in the one database, written on
        # a reading that was happening anyway — see `panel/runtime/player_card.py`.
        try:
            from . import player_card as cardmod

            cardmod.remember(getattr(self._rt, "store", None), who.get("nick", ""),
                             who.get("level", 0), who.get("uid", ""),
                             who.get("pic_ver", 0), self._clock())
            # …and the face is resolved HERE, on this worker, for the reason the
            # attribute's own note gives: the lookup is thousands of md5 sums the first
            # time and a dictionary hit ever after.
            self._avatar = cardmod.face_link(who.get("uid", ""), who.get("pic_ver", 0))
        except Exception:                     # noqa: BLE001 — a note, never the reading
            pass
