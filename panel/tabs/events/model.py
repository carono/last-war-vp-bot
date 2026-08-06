"""What the game's events are doing right now — the catalogue and the parser. **No Tk.**

**Nothing here is a guess and nothing here is a memory.** An event's state is the game's
own answer, the way the «Чеклист» rows are: what is running, how much of it has been
done, and what the person has to show for it. There is no box to tick and no counter the
panel keeps for itself — the moment the panel kept its own count, an attack sent from the
phone or by the person playing on the screen in front of them would stop being counted.

So there are three states and they are not negotiable:

* **open** — the event is running right now and can be acted on;
* **closed** — it is not on at the moment. Drawn GREY rather than hidden: an event that
  vanishes from the board looks exactly like an event nobody has written yet, and the
  person cannot tell «nothing to do» from «this panel does not know about it»;
* **unknown** — the game would not answer. A manager not loaded, a client still at the
  login screen, an account that has not unlocked the event. **Never drawn as closed**:
  «nobody knows» and «not on today» are different answers.

**The board is groups, one per event**, in the order they matter to a day — the same
shape «Чеклист» settled on (#1249), for the same reason: an event is more than a row. It
has a state, a couple of numbers, sometimes a press, and it needs a heading of its own so
the numbers underneath it are unambiguous.

The first group is «Кодовое имя» (:data:`CODENAME`), the world-boss event. The reading is
`actions/read_codename_event.md`, one round trip, one line of `key=value` pairs; this
module holds what each field MEANS and the tab holds the words and the widgets.
"""
from __future__ import annotations

#: The scenario that answers the codename event, and the variable it lands in.
CODENAME_ACTION = "read_codename_event"
CODENAME_VARIABLE = "codename"

#: The scenario one press of «Атаковать сейчас» plays. One attack, one squad.
CODENAME_ATTACK = "attack_codename_boss"

# -- the three states an event can be in ------------------------------------
OPEN = "open"
CLOSED = "closed"
UNKNOWN = "unknown"


class Group:
    """One block of the board: an event, its heading and everything drawn under it.

    ``key`` is what the tab tests to decide which widgets go under the heading — the
    widgets themselves stay in the tab, because this module has no Tk. What a group is
    NOT is a thing the person edits: the board is the game's list of events, not
    somebody's notes about them.
    """

    __slots__ = ("key", "title_key")

    def __init__(self, key: str) -> None:
        self.key = key
        #: The game's own name for the event, translated into all eleven by the locale
        #: files out of the client's own tables (`docs/game-glossary.md`) — the panel
        #: may not invent a name for something the game has already named.
        self.title_key = "events.group." + key

    def __repr__(self) -> str:
        return f"<Group {self.key}>"


#: «Кодовое имя» — the world-boss event, and the first group of the board.
#:
#: The game puts one boss on the world map for a few hours at a time and asks for three
#: attacks on it. Attempts themselves are UNLIMITED (the event's own rules say so, and
#: the client agrees), so what the day owes is a count being REACHED rather than an
#: allowance being spent — which is why the number beside it is «сделано из трёх» and
#: never «осталось из пяти».
CODENAME = "codename"

#: The groups, in the order they are drawn. One so far, and the shape is what matters:
#: a second event is one entry here, one `Group`, and its own reading.
GROUPS: tuple = (Group(CODENAME),)


class Reading:
    """One answer from a reading scenario, parsed.

    ``values`` maps a field to a whole number, or to ``None`` for a field the game
    refused — the reading's own `-`. ``error`` is set when the run itself failed, and
    then everything reads as unknown rather than as closed: a scenario that did not run
    has not said that anything is off.
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
    """Turn a scenario's one line into a :class:`Reading`.

    `key=value` pairs separated by spaces, a `-` for anything the game would not answer.
    Anything unparseable is dropped rather than raised on — this is the client talking,
    and a client that has just been restarted says all sorts of things.
    """
    if raw is None:
        return Reading(error="no reading", at=at)
    values = {}
    for piece in str(raw).split():
        key, sep, value = piece.partition("=")
        if not key or not sep:
            continue
        if value in ("-", ""):
            values[key] = None
            continue
        try:
            values[key] = int(float(value))
        except ValueError:
            values[key] = None
    if not values:
        return Reading(error="unreadable", at=at)
    return Reading(values, at=at)


class CodenameState:
    """What «Кодовое имя» says right now — the whole group, in one object.

    ``attacks`` is how many have gone out in the current window and ``need`` how many
    earn the reward; ``left`` is what is still owed. ``damage`` is the biggest single
    hit, which is the number the daily ranking is made of. ``None`` anywhere means the
    game would not answer, and the tab draws that as words rather than as a number
    nobody can trust.
    """

    __slots__ = ("state", "attacks", "need", "left", "damage", "targets", "seconds")

    def __init__(self, state: str, attacks=None, need=None, left=None, damage=None,
                 targets=None, seconds=None) -> None:
        self.state = state
        self.attacks = attacks
        self.need = need
        self.left = left
        self.damage = damage
        self.targets = targets
        #: Seconds left in the open window, when there is one.
        self.seconds = seconds

    @property
    def open(self) -> bool:
        return self.state == OPEN

    @property
    def done(self) -> bool:
        """Are the three attacks in? ``False`` while nobody knows — never a guess."""
        return self.left is not None and self.left <= 0

    @property
    def can_attack(self) -> bool:
        """May «Атаковать сейчас» be pressed?

        Not «while the three are still owed»: a fourth attack is allowed and worth
        making — attempts are not rationed and only the biggest single hit counts for
        the ranking — so the button stays alive after the third.

        What kills it is the game having SAID there is no boss on the map: `CLOSED`, and
        only that. **UNKNOWN leaves it alive**, the same rule «Чеклист» draws its nine
        buttons by: «nobody knows» is not «you may not», and the ability holds its own
        gates (`CLAUDE.md`) — the scenario is the thing that knows whether it can run,
        and it refuses in one line if it cannot. A panel refusing on its own behalf
        would be a second, worse copy of that gate, and the two front-ends would end up
        with different ideas of when a press is allowed.
        """
        return self.state != CLOSED

    def __repr__(self) -> str:
        return f"<codename {self.state} {self.attacks}/{self.need} dmg={self.damage}>"


def codename_state(reading) -> "CodenameState":
    """The codename group against one reading. Never guesses: no answer is `unknown`."""
    if reading is None or reading.error:
        return CodenameState(UNKNOWN)
    is_open = reading.get("open")
    if is_open is None:
        return CodenameState(UNKNOWN)
    state = OPEN if is_open else CLOSED
    return CodenameState(
        state,
        attacks=reading.get("attacks"),
        need=reading.get("need"),
        left=reading.get("left"),
        damage=reading.get("maxdmg"),
        targets=reading.get("targets"),
        seconds=reading.get("until"),
    )


def damage(value) -> str:
    """`12 607 399 171` — a hit big enough to need its digits grouped.

    A number, not a word: the separator is a space in every language the panel ships
    and nothing here is translated. Rounding it to «12.6B» would be a second opinion
    about the one figure the daily ranking is decided on, so the digits stay.
    """
    if value is None:
        return "—"
    try:
        n = int(value)
    except (TypeError, ValueError):
        return "—"
    return "{:,}".format(n).replace(",", " ")


def counter(state) -> str:
    """`1 / 3` — attacks made against attacks that earn the reward."""
    if state.attacks is None or state.need is None:
        return "—"
    return "%d / %d" % (state.attacks, state.need)


def hhmm(seconds) -> str:
    """`2:07` — a countdown short enough to sit at the end of a line."""
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 3600, (seconds % 3600) // 60)


def ago(seconds) -> str:
    """`0:42` — how long ago something was read, in the same shape as the countdown."""
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)
