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

#: …and the whole day's worth, which the clock plays once a day and this tab offers as a
#: second press. It asks the server how many attacks the day still owes and sends only
#: those, so pressing it after two by hand costs one march and pressing it twice costs
#: nothing the second time. The single attack above is kept beside it on purpose: a
#: better ranking is bought by attacking MORE than the day owes, and that is a decision
#: the person makes one march at a time.
CODENAME_DAILY = "attack_codename_daily"

#: The reading behind the «Золотые зомби» group, and the variable it lands in.
GOLDEN_ACTION = "read_golden_zombies"
GOLDEN_VARIABLE = "golden"

#: …and the chain one press starts: scan the map, then attack the nearest golden
#: zombie to wherever the squad is standing, until the energy runs out.
GOLDEN_ATTACK = "attack_golden_zombies"

#: Which squad the chain sends, by the SLOT the player sees. Saved in the tab's own
#: block (`tabs.config.events`), because it is a choice about THIS account and not
#: about the machine.
GOLDEN_SQUAD_KEY = "golden_squad"
GOLDEN_SQUADS: tuple = (1, 2, 3, 4)
GOLDEN_SQUAD_DEFAULT = 1

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

#: «Золотые зомби» — the invasion event's small monster, config id 1030000.
#:
#: Nothing here is rationed by the day: what the chain can do is bounded by the
#: ENERGY purse and by how many of them the client has loaded, which is why the two
#: numbers under the heading are «energy / price» and «seen», and never «N of M made
#: today». The day's tally is drawn separately and is the PANEL's own history of what
#: it sent — never a claim about what the account did (`panel/golden_zombies.py`).
GOLDEN = "golden"

#: The groups, in the order they are drawn. One so far, and the shape is what matters:
#: a second event is one entry here, one `Group`, and its own reading.
GROUPS: tuple = (Group(CODENAME), Group(GOLDEN))


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


class GoldenState:
    """What the golden-zombie hunt has to work with right now — the whole group.

    ``energy`` is the purse, ``cost`` what the game charges for one attack, ``attacks``
    how many that buys and ``seen`` how many golden zombies the CLIENT knows about.
    ``None`` anywhere means the game would not answer, and the tab draws that as words.

    ``seen`` has a third answer the others do not: **-1 is «could not be asked»** — the
    base is on screen and the world's own controller only exists on the map. It is kept
    distinct from 0 all the way to the widget, because «nobody looked» and «none there»
    lead a person to do different things.
    """

    __slots__ = ("state", "energy", "cost", "attacks", "seen")

    def __init__(self, state: str, energy=None, cost=None, attacks=None,
                 seen=None) -> None:
        self.state = state
        self.energy = energy
        self.cost = cost
        self.attacks = attacks
        self.seen = seen

    @property
    def open(self) -> bool:
        return self.state == OPEN

    @property
    def can_attack(self) -> bool:
        """May the chain be started?

        Only a reading that SAYS the purse cannot pay for one march kills the button.
        UNKNOWN leaves it alive, exactly as «Кодовое имя» does and for the same reason:
        the ability holds its own gates (`CLAUDE.md`), and a panel refusing on its own
        behalf is a second, worse copy of them that the two front-ends then disagree on.
        """
        return self.state != CLOSED

    def __repr__(self) -> str:
        return f"<golden {self.state} energy={self.energy} seen={self.seen}>"


def golden_state(reading) -> "GoldenState":
    """The golden-zombie group against one reading. No answer is `unknown`, never `closed`."""
    if reading is None or reading.error:
        return GoldenState(UNKNOWN)
    energy = reading.get("energy")
    cost = reading.get("cost")
    if energy is None or cost is None:
        return GoldenState(UNKNOWN, energy=energy, cost=cost,
                           attacks=reading.get("attacks"), seen=reading.get("seen"))
    state = OPEN if (cost > 0 and energy >= cost) else CLOSED
    return GoldenState(state, energy=energy, cost=cost,
                       attacks=reading.get("attacks"), seen=reading.get("seen"))


def energy(state) -> str:
    """`55 / 10` — what is in the purse against what one attack costs."""
    if state.energy is None or state.cost is None:
        return "—"
    return "%d / %d" % (state.energy, state.cost)


def seen(state) -> str:
    """How many are known — `—` for «could not be asked», which is not the same as none."""
    if state.seen is None or state.seen < 0:
        return "—"
    return str(state.seen)


def affordable(state) -> str:
    """How many attacks the purse still buys."""
    if state.attacks is None:
        return "—"
    return str(state.attacks)


def tally(row) -> str:
    """`6 · 60` — the day's attacks and the energy they cost, as this panel sent them."""
    row = row or {}
    return "%d · %d" % (int(row.get("attacks", 0) or 0), int(row.get("spent", 0) or 0))


def squad_of(raw) -> int:
    """A saved squad slot, clamped to one that exists. Anything odd reads as the first."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return GOLDEN_SQUAD_DEFAULT
    return value if value in GOLDEN_SQUADS else GOLDEN_SQUAD_DEFAULT
