"""What the day still owes, read off the game — the catalogue and the parser. **No Tk.**

**Nothing here is ticked by a person.** An errand's state is the game's own answer to
«is there any of this left», and the panel only draws it. A hand-ticked box records what
somebody REMEMBERS doing, which is precisely the thing a checklist exists so that nobody
has to; and the first time the two disagree — a collect that was pressed and refused, a
second client that spent the quota — the box is the one that is wrong, with nothing on
screen to say so.

So there are three states and they are not negotiable:

* **done** — the game says there is nothing outstanding (the queue is empty, the daily
  quota is spent);
* **todo** — it says there is, and how much;
* **unknown** — it would not answer. A manager not loaded yet, a client at the login
  screen, a feature this account has not unlocked. **Never drawn as done**, and never as
  zero: «nobody knows» and «nothing left» are different answers and the whole value of a
  read is that it can tell them apart.

A fourth, `closed`, is for an errand that is not on today at all — Ghost Ops runs one day
a week, and on the other six «not done» would be a lie about a thing nobody could do.

The reading itself is `actions/read_daily_checklist.md`, one round trip, one line of
`key=value` pairs. This module holds the catalogue that says what each field MEANS and
the parser that turns the line into states; the tab holds the words and the widgets.

**Two shapes of errand, and the difference matters:**

* a **queue** — «how much work is standing there»: buildings ready to collect, mates
  waiting for help, wounded in the hospital. Zero is done, and it can go back up an hour
  later. This is a state, not a diary: it says «nothing to do now», never «you did it».
* a **quota** — «how much of today's allowance is left»: five robberies, thirty
  donations. Zero is done and STAYS done until the game's day rolls over, which is the
  one case where «done today» is literally what the game means.

The day is the game's (`tools/lib/game_clock.py`), and it is used for exactly one thing:
saying when the quotas come back. Nothing is stored between runs — there is no tick to
keep, because the answer is re-read.
"""
from __future__ import annotations

#: One day, and one hour, in the milliseconds the game counts in.
DAY_MS = 24 * 60 * 60 * 1000
HOUR_MS = 60 * 60 * 1000

#: The scenario that answers all of this in one round trip, and the variable it lands in.
ACTION = "read_daily_checklist"
VARIABLE = "daily"

# -- the four states an errand can be in ------------------------------------
DONE = "done"
TODO = "todo"
UNKNOWN = "unknown"
CLOSED = "closed"

# -- the two shapes ---------------------------------------------------------
QUEUE = "queue"
QUOTA = "quota"


class Errand:
    """One line of the checklist: what it is, and which field of the reading answers it.

    ``field`` names a key of the reading; ``cap`` the field holding the day's allowance
    for a quota; ``gate`` a field that must be 1 for the errand to be on at all (Ghost
    Ops and its one day a week).

    **An empty ``field`` is a line nothing can answer yet** — a real errand of the day
    that this repository has no reading for. It is on the list on purpose and it says
    «состояние неизвестно» for ever, which is the honest thing to show: leaving it out
    would make the checklist look complete while a third of the day is missing from it,
    and putting a tickable box there would be the hand-marking this tab exists without.
    """

    __slots__ = ("key", "title_key", "field", "kind", "cap", "gate")

    def __init__(self, key: str, field: str = "", kind: str = QUEUE, cap: str = "",
                 gate: str = "") -> None:
        self.key = key
        self.title_key = "checklist.item." + key
        self.field = field
        self.kind = kind
        self.cap = cap
        self.gate = gate

    @property
    def readable(self) -> bool:
        """Whether the game has anything to say about this one."""
        return bool(self.field)


#: The errands the game ANSWERS, in the order a day is played: the base first, then the
#: alliance, then what the person has banked, then the two robberies. Every one of these
#: is a live reading and the same expression the matching press is gated on.
READ_ERRANDS: tuple = (
    Errand("base_resources", "base_ready"),
    Errand("trucks", "trucks_ready"),
    Errand("hospital_collect", "healed_ready"),
    Errand("hospital_heal", "wounded"),
    Errand("queues_help", "queues_help"),
    Errand("alliance_help", "help_waiting"),
    Errand("alliance_donate", "donate_left", QUOTA),
    Errand("visitors_recruit", "recruit_pending"),
    Errand("visitors_gifts", "gifts_pending"),
    Errand("skills", "skills_ready"),
    Errand("decorations", "decorations"),
    Errand("secret_steals", "steal_left", QUOTA, cap="steal_cap"),
    Errand("ghost_steals", "ghost_left", QUOTA, cap="ghost_cap", gate="ghost_open"),
)

#: …and the rest of the day, which nothing here can read yet.
#:
#: Taken from the routine as it is actually played (`docs/farming.md`, «The daily
#: routine, point by point») rather than invented, so the two lists stay comparable: what
#: is below is exactly the part of a real day the bot is still blind to. Each one is a
#: candidate for a reading, and moving a line UP from here is the whole way this tab
#: grows — never by giving it a box somebody can tick.
BLIND_ERRANDS: tuple = (
    Errand("send_trucks"),
    Errand("truck_reward"),
    Errand("gather"),
    Errand("secret_missions"),
    Errand("secret_tasks_help"),
    Errand("radar"),
    Errand("rally_joins"),
    Errand("attack_marked"),
    Errand("treasures"),
    Errand("treasure_maps"),
    Errand("alliance_gifts"),
    Errand("chat_gifts"),
    Errand("arms_race"),
    Errand("arena"),
    Errand("tavern"),
    Errand("supplies"),
    Errand("shop"),
    Errand("fireworks"),
    Errand("vip_daily"),
    Errand("battle_pass"),
    Errand("ministry"),
)

#: The two groups, in the order they are drawn, with the heading each is drawn under.
GROUPS: tuple = (
    ("checklist.group.read", READ_ERRANDS),
    ("checklist.group.blind", BLIND_ERRANDS),
)

ERRANDS: tuple = READ_ERRANDS + BLIND_ERRANDS

BY_KEY = {errand.key: errand for errand in ERRANDS}


def now_ms() -> int:
    """"Now" on the GAME's clock, in milliseconds — falling back to this machine's.

    `game_clock` lives in `tools/lib`, which the panel's runtime puts on the path; it is
    imported lazily so this module stays importable on its own. An unsynced offset is
    zero and the answer is `time.time()`, which is what every process did before the
    clock existed.
    """
    import time

    try:
        import game_clock
    except Exception:                       # noqa: BLE001 — a clock is not worth a crash
        return int(time.time() * 1000)
    try:
        return int(game_clock.now_ms())
    except Exception:                       # noqa: BLE001
        return int(time.time() * 1000)


def seconds_to_reset(stamp_ms=None) -> int:
    """How long until the game's day turns over and the quotas come back."""
    stamp = now_ms() if stamp_ms is None else int(stamp_ms)
    return max(0, ((stamp // DAY_MS + 1) * DAY_MS - stamp) // 1000)


class Reading:
    """One answer from `read_daily_checklist.md`, parsed.

    ``values`` maps a field to a whole number, or to ``None`` for a field the game
    refused — the reading's own `-`. ``error`` is set when the run itself failed, and
    then EVERY errand reads as unknown rather than as done: a scenario that did not run
    has not said that anything is finished.
    """

    __slots__ = ("values", "at", "error")

    def __init__(self, values=None, at: float = 0.0, error: str = "") -> None:
        self.values = dict(values or {})
        #: The panel's own clock when this was read — what «прочитано N назад» counts.
        self.at = at
        self.error = error

    def __bool__(self) -> bool:
        return not self.error and bool(self.values)

    def get(self, field: str):
        """The number, or ``None`` for «the game would not say»."""
        return self.values.get(field) if field else None

    def __repr__(self) -> str:
        return f"<Reading {len(self.values)} fields error={self.error!r}>"


def parse(raw, at: float = 0.0) -> "Reading":
    """Turn the scenario's one line into a :class:`Reading`.

    `key=value` pairs separated by spaces, a `-` for anything the game would not answer.
    Anything unparseable is dropped rather than raised on — this is the client talking,
    and a client that has just been restarted says all sorts of things (`#1227`).
    """
    if raw is None:
        return Reading(error="no reading", at=at)
    values = {}
    for piece in str(raw).split():
        key, _sep, value = piece.partition("=")
        if not key or not _sep:
            continue
        if value == "-" or value == "":
            values[key] = None
            continue
        try:
            values[key] = int(float(value))
        except ValueError:
            values[key] = None
    if not values:
        return Reading(error="unreadable", at=at)
    return Reading(values, at=at)


class ErrandState:
    """What one line of the checklist says right now.

    ``left`` is what the reading gave — outstanding work for a queue, allowance left for
    a quota — and ``used`` / ``cap`` are the quota's two halves when the cap was read.
    ``None`` everywhere means unknown, and the tab draws that as words rather than as a
    number nobody can trust.
    """

    __slots__ = ("errand", "state", "left", "cap")

    def __init__(self, errand, state: str, left=None, cap=None) -> None:
        self.errand = errand
        self.state = state
        self.left = left
        self.cap = cap

    @property
    def key(self) -> str:
        return self.errand.key

    @property
    def used(self):
        """A quota's spent half, when both numbers are known."""
        if self.cap is None or self.left is None:
            return None
        return max(0, self.cap - self.left)

    @property
    def done(self) -> bool:
        return self.state == DONE

    def __repr__(self) -> str:
        return f"<{self.errand.key} {self.state} left={self.left}>"


def state_of(errand, reading) -> "ErrandState":
    """One errand against one reading. Never guesses: no answer is `unknown`."""
    if not errand.readable:
        return ErrandState(errand, UNKNOWN)
    if reading is None or reading.error:
        return ErrandState(errand, UNKNOWN)
    if errand.gate:
        gate = reading.get(errand.gate)
        if gate is None:
            return ErrandState(errand, UNKNOWN)
        if not gate:
            return ErrandState(errand, CLOSED)
    left = reading.get(errand.field)
    if left is None:
        return ErrandState(errand, UNKNOWN)
    cap = reading.get(errand.cap) if errand.cap else None
    return ErrandState(errand, DONE if left <= 0 else TODO, left=left, cap=cap)


def states(reading) -> list:
    """Every errand against one reading, in the catalogue's order."""
    return [state_of(errand, reading) for errand in ERRANDS]


def grouped(reading) -> list:
    """``[(heading key, [state, …]), …]`` — the board as both front-ends draw it."""
    return [(heading, [state_of(errand, reading) for errand in errands])
            for heading, errands in GROUPS]


def progress(states_) -> tuple:
    """``(done, counted)`` — how much of the day is finished.

    An errand nobody could read, and one that is not on today, are left OUT OF BOTH
    halves rather than counted as undone: «3 из 11» when two are unknown says something
    false about the two, and a Ghost Ops day that is not today is not work anybody owes.
    """
    counted = [s for s in states_ if s.state in (DONE, TODO)]
    return sum(1 for s in counted if s.done), len(counted)


def hhmm(seconds) -> str:
    """`5:07` — a countdown short enough to sit at the end of a line."""
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 3600, (seconds % 3600) // 60)


def ago(seconds) -> str:
    """`0:42` — how long ago something was read, in the same shape as the countdown."""
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)
