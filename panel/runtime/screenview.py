"""What the CLIENT is looking at right now, held for the page that is looking at it.

WHAT IT IS. The other half of «Карта: схема» (#2018). The first half draws what the panel
has GATHERED — every tile it was ever told about. This one draws what the client can see
at this second: where the camera stands, how high, and which tiles and monsters the world
scene is holding around it. The person asked for exactly that, in these words:
«я хочу, чтобы на вкладку транслировалось текущее схематичное изображение экрана игры, то
что клиент видит по факту».

WHERE THE NUMBERS COME FROM. One scenario, `actions/read_screen_view.md`, and not a line
of Lua here (`CLAUDE.md` — the panel plays scenarios, it does not write them). It reads
and presses nothing: `WorldScene.CurTilePos`, `.Zoom`, `GetLodLevel()`, the point manager's
own window of tiles, the monsters in the same box and this account's marches.

WHY THERE IS A CLOCK HERE AT ALL, WHEN THE RULE FORBIDS ONE. «Читаем один раз, дальше
слушаем» stands, and a broadcast is by definition a repeated reading — so this was put to
the person with its price measured (docs/research/live-screen-view.md) and they answered
«ок, делай по умолчанию». What was agreed is narrow and every part of it matters:

  * **the reading happens only while somebody is LOOKING.** Nothing in the panel ticks:
    this class has no thread, no `after`, no timer. It reads when :meth:`look` is called,
    and the only caller is the route the open page asks — `/api/screen/data`. Close the
    page and the calls stop, so the readings stop. That is the safety catch of the whole
    feature and it is structural rather than promised.
  * **a busy link is skipped, never queued.** The bot's own work outranks a picture: if
    the game is being driven, the tick is dropped and the page goes on showing the last
    reading with its age climbing. Nothing accumulates, so a minute of bot work does not
    end in a minute of catch-up readings.
  * **the play goes in at** :data:`~panel.runtime.claims.DETACHED`, below every ordinary
    errand, exactly as the status strip's and the stock's do.
  * **the age is drawn.** A picture that has stopped moving has to LOOK stopped.

WHAT IT COSTS, measured live (docs/research/live-screen-view.md): 14–15 ms inside the VM
and 0.6–1.2 s of exclusive link for the round trip that carries it. At the default five
seconds that is about a fifth of the link, and only while a page is open — which is the
trade the person took, and the reason the interval is a FIELD rather than a constant: they
said the smoothness-against-link exchange is theirs to make.

THE INTERVAL LIVES IN THE DATABASE, never in a file (`CLAUDE.md`, «Game data lives only in
the database», as amended by the person's «никаких json, все должно быть в базе»): a named
row in this profile's own `panel.db` through :mod:`panel.runtime.store`'s blob door.

WHAT IS NOT HERE, AND IS THE NEXT STEP. An in-CLIENT hook that ANNOUNCES the camera moving
would remove the clock altogether, and it is what the rule actually wants. It is not built
because it is not yet known to be possible: `WorldScene` is C# and xLua cannot wrap a C#
method, so the hook would have to sit on some Lua object that hears about the view moving,
and nobody has looked for one (docs/research/live-screen-view.md §3b — half an hour of
live probing). :meth:`mark_stale` is the door it will come through, and nothing in the
panel may call that on a timer.
"""
from __future__ import annotations

import time

from . import claims

#: The scenario that answers «what is the client looking at», and its variable. THE ONLY
#: scenario this module may play: it reads and presses nothing, which is what keeps the
#: whole tab read-only by construction rather than by good intentions.
ACTION = "read_screen_view"
VARIABLE = "screen_view"

#: How the scenario separates its fields, and the objects inside the seventh.
FIELD_SEP = ";;"

#: Seconds between readings while a page is open. FIVE, and the number is the person's:
#: one reading costs 0.6–1.2 s of an exclusive link, so five seconds spends about a fifth
#: of it while somebody is watching and nothing at all when nobody is. Lower it for a
#: smoother picture and a slower bot; raise it for the opposite. It is a FIELD on the tab
#: — do not re-tune it here, and never on somebody else's behalf.
DEFAULT_INTERVAL = 5.0

#: What the field will accept. The floor is two seconds because a reading takes up to one
#: and a half of them: below that the page would be asking for a reading that the previous
#: one has not finished, which spends the link without making the picture smoother.
MIN_INTERVAL, MAX_INTERVAL = 2.0, 120.0

#: Where the interval is kept — a named row in this profile's `panel.db`.
SETTINGS_BLOB = "worldview_live"

#: How long a reading that never ARRIVED is left alone before it is asked for again. Not
#: a refresh interval: it applies to a play that was refused or answered nothing.
RETRY_SEC = 8.0

#: The kinds the scenario can name in its object list. `m` is a monster and `w` a march of
#: this account's own; the digits are the wire's own `f2` (`docs/research/world-tiles.md`).
POINT_KINDS = {"6": "base", "7": "mine", "11": "stronghold", "17": "secret",
               "25": "alliance", "29": "ghost", "m": "monster", "w": "march"}


def parse_view(answer: str) -> dict:
    """`read_screen_view.md`'s one line as a picture, or ``{}`` when it said nothing.

    A short line is dropped whole rather than half-read: the fields are positional, so a
    line with six of them would put the camera's height under «радиус».
    """
    parts = [chunk.strip() for chunk in str(answer or "").split(FIELD_SEP)]
    if len(parts) < 9 or not parts[0]:
        return {}

    def number(raw: str, fallback=0):
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return fallback

    objects = []
    for chunk in (parts[7] + "," + parts[8]).split(","):
        bits = chunk.split(":")
        if len(bits) != 3:
            continue
        kind = POINT_KINDS.get(bits[0])
        if kind is None:
            continue
        objects.append({"k": kind, "x": number(bits[1]), "y": number(bits[2])})
    return {"scene": parts[0], "server": number(parts[1]),
            "x": number(parts[2]), "y": number(parts[3]),
            "zoom": number(parts[4]), "lod": number(parts[5]),
            "radius": number(parts[6], 20), "objects": objects}


class LiveScreen:
    """One profile's live view of its client — held, aged, and read only when looked at.

    The tab owns one. It has no thread and no clock of its own: :meth:`look` is called by
    the route an OPEN page asks, and a page nobody has open asks nothing.
    """

    def __init__(self, rt, clock=time.time) -> None:
        self._rt = rt
        self._clock = clock
        self._view: dict = {}
        self._at = 0.0
        self._reading = False
        self._hold = 0.0
        self._reads = 0            #: how many readings were taken — the test's own proof
        self._skipped = 0          #: …and how many ticks the bot's work cost us

    # -- what the page draws --------------------------------------------------
    def state(self, now: float | None = None) -> dict:
        """The picture as it stands. Reads NOTHING — see :meth:`look` for that."""
        now = self._clock() if now is None else now
        out = dict(self._view)
        out["age"] = round(now - self._at, 1) if self._at else -1
        out["reading"] = self._reading
        out["interval"] = self.interval()
        out["reads"] = self._reads
        out["skipped"] = self._skipped
        return out

    # -- the reading ----------------------------------------------------------
    def look(self, now: float | None = None, force: bool = False) -> dict:
        """The open page asked. Book a reading if one is DUE, then answer with what we have.

        `force` is a person's press — «Обновить» — and skips the interval but not the busy
        test: a press must not take the link away from an errand either.
        """
        now = self._clock() if now is None else now
        due = force or not self._at or (now - self._at) >= self.interval()
        if due and not self._reading and now >= self._hold:
            if self._may_play():
                self._reading = True
                if not self._play():
                    self._reading = False
                    self._hold = now + RETRY_SEC
            else:
                # THE BOT'S WORK WINS. The tick is dropped, not queued: a picture must
                # never take the link from a robbery, and a queue would spend the link
                # catching up on readings nobody is waiting for any more.
                self._skipped += 1
        return self.state(now)

    def mark_stale(self) -> None:
        """Somebody knows the view moved — read it on the next look, interval or not.

        The door the in-client hook will come through when there is one, and the same
        contract the status strip's has: called BY AN EVENT, never by a clock.
        """
        self._at = 0.0
        self._hold = 0.0

    # -- the knob -------------------------------------------------------------
    def interval(self) -> float:
        """Seconds between readings while a page is open — this profile's own, from the
        database."""
        held = self._blob().get("interval")
        try:
            value = float(held)
        except (TypeError, ValueError):
            return DEFAULT_INTERVAL
        return max(MIN_INTERVAL, min(MAX_INTERVAL, value))

    def set_interval(self, value) -> bool:
        """Move it. A value that is not a number is REFUSED rather than rounded to one."""
        try:
            wanted = float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return False
        if wanted <= 0:
            return False
        wanted = max(MIN_INTERVAL, min(MAX_INTERVAL, wanted))
        block = self._blob()
        block["interval"] = wanted
        return self._write(block)

    # -- the plumbing ---------------------------------------------------------
    def _blob(self) -> dict:
        store = getattr(self._rt, "store", None)
        if store is None:
            return dict(getattr(self, "_memory", {}) or {})
        try:
            held = store.blob_get(SETTINGS_BLOB)
        except Exception:                # noqa: BLE001 — a reading, never the panel
            return {}
        return dict(held) if isinstance(held, dict) else {}

    def _write(self, block: dict) -> bool:
        store = getattr(self._rt, "store", None)
        if store is None:
            # No database (a tab opened on its own in a test): the value is held for this
            # process and not pretended to be saved.
            self._memory = dict(block)
            return True
        try:
            store.blob_set(SETTINGS_BLOB, block)
            return True
        except Exception:                # noqa: BLE001 — one knob, never the panel
            return False

    def _may_play(self) -> bool:
        """Is the link free, and may this profile press at all?

        Asked here rather than left to the claim for the reason the header records: both
        refuse OUT LOUD, and a page asking every few seconds would fill the log with
        «занят» lines about a picture nobody is troubled by.
        """
        try:
            if self._rt.game.busy:
                return False
        except Exception:                # noqa: BLE001 — an unreadable link is not a
            return False                 #   licence to press either
        try:
            if self._rt.gate.blocks(ACTION, human=False):
                return False
        except Exception:                # noqa: BLE001
            return False
        return True

    def _play(self) -> bool:
        try:
            return bool(self._rt.play_async(ACTION, tag="screen", human=False,
                                            priority=claims.DETACHED,
                                            on_result=self._landed))
        except Exception:                # noqa: BLE001 — a picture is never a fault
            return False

    def _landed(self, outcome) -> None:
        """The reading came back — or did not, and the old picture stays with its age on."""
        self._reading = False
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        view = parse_view(got.get(VARIABLE, ""))
        if not view:
            self._hold = self._clock() + RETRY_SEC
            return
        self._view = view
        self._at = self._clock()
        self._reads += 1
