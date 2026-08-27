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

WHAT A READ COSTS, AND WHY THE TWO ARE PACED DIFFERENTLY. Measured live on this client,
end to end through the panel's own runner: the place read took **167 / 193 / 219 ms**,
which is the panel↔VM round trip rather than the work in the chunk (the chunk's own scan
of the window table is 1.0 ms). The link is EXCLUSIVE — that is time the schedule, the
robberies and the rally joins do not get — and `/api/state` is asked every 2.5 s by every
open page, per profile. Reading the place on every poll would hold the link some 8 % of
the time, for ever, because the header is on screen always. So:

  * :data:`WHERE_GAP_SEC` — the place is re-read at most every 10 s (≈2 % of the link).
    It is the reading that genuinely moves: the panel drives the client all day, and a
    header still saying «база» while a robbery is walking the map is worse than a header
    a few seconds behind.
  * :data:`WHO_GAP_SEC` — the character is re-read at most every 10 minutes. A name and a
    level asked for oftener than that is a round trip spent on an answer that is already
    known.

DEMAND-DRIVEN, NOT A CLOCK. Nothing ticks here. :meth:`state` is what the route calls, so
a panel nobody is looking at reads nothing at all, and the first look after a long
silence is served stale-then-fresh: what is in memory goes out at once and the refresh
lands on the next poll, because a route that waited for the game would block the page for
a fifth of a second.

BOTH PLAYS GO IN AT :data:`~panel.runtime.claims.DETACHED`, below every ordinary errand,
for the same reason the stock's does: a header is a page being looked at, and no line of
it is ever worth making a robbery wait.

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

#: The floor between two place readings, in seconds. See the module docstring: one read
#: is ~0.2 s of the exclusive game link, and the page polls every 2.5 s.
WHERE_GAP_SEC = 10.0

#: The floor between two character readings, in seconds. A name and an HQ level.
WHO_GAP_SEC = 600.0

#: How long to wait after a refused play before asking again. A refusal is ordinary —
#: the link is exclusive — but retrying at the poll's own pace would make the refusal
#: itself the log.
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

    # -- what the route draws -------------------------------------------------
    def state(self, now: float | None = None) -> dict:
        """The header as it stands, with whichever half is stale booked for a re-read.

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
            # Seconds since the PLACE was read — the half that moves — so the strip can
            # fade when it is looking at something old rather than assert it. -1 means
            # nothing has been read at all, which draws as dashes and never as «база».
            "age": round(now - self._where_at, 1) if self._where_at else -1,
            "reading": self._where_reading or self._who_reading,
        }
        return out

    # -- the refresh ----------------------------------------------------------
    def _maybe_read(self, now: float) -> None:
        if not self._may_play():
            return
        if (not self._where_reading and now >= self._where_hold
                and (not self._where_at or now - self._where_at >= WHERE_GAP_SEC)):
            self._where_reading = True
            if not self._play(WHERE_ACTION, self._from_where):
                self._where_reading = False
                self._where_hold = now + RETRY_SEC
        if (not self._who_reading and now >= self._who_hold
                and (not self._who_at or now - self._who_at >= WHO_GAP_SEC)):
            self._who_reading = True
            if not self._play(WHO_ACTION, self._from_who):
                self._who_reading = False
                self._who_hold = now + RETRY_SEC

    def _may_play(self) -> bool:
        """Is the link free, and is this profile allowed to press at all?

        Asked HERE rather than left to the claim and the gate, for the reason
        `panel/runtime/resources.py` records: both of them refuse out loud, and at the
        poll's own pace that is a warning line every 2.5 s for as long as an errand runs,
        drowning the log somebody opened the page to read.
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
            return
        self._where = place
        self._where_at = self._clock()

    def _from_who(self, outcome) -> None:
        self._who_reading = False
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        who = parse_who(got.get(WHO_VARIABLE, ""))
        if not who:
            # Not read, so not remembered as read: the next poll asks again rather than
            # sitting on ten minutes of silence.
            self._who_hold = self._clock() + RETRY_SEC
            return
        self._who = who
        self._who_at = self._clock()
