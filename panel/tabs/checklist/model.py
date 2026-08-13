"""What the day still owes, read off the game — the catalogue and the parser. **No Tk.**

**The state is READ; the doing is OFFERED.** An errand's state is the game's own answer
to «is there any of this left», and the panel only draws it — there is no box anybody can
tick. But an errand the bot has an ability for carries a BUTTON, and pressing it plays
that ability and then re-reads the board: the two halves are not in tension, because what
moves a line is always the reading and never the press (:attr:`Errand.scenario`).

A hand-ticked box would record what somebody REMEMBERS doing, which is precisely the
thing a checklist exists so that nobody has to; and the first time the two disagree — a
collect that was pressed and refused, a second client that spent the quota — the box is
the one that is wrong, with nothing on screen to say so. A press changes none of that: it
starts work, the game answers, and the row follows the answer.

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

**The lines are gathered into GROUPS** (:class:`Group`), and a group can be more than a
heading over a list. «Отправка грузовиков» is the first of the richer kind: it carries a
counter of its own («0 из 5» — the same quota its row is drawn from), the press that will
spend it, and the setting that says how the trucks are to be improved before they go. The
widgets for all of that live in :mod:`.tab`; what is here is the catalogue, the numbers
and the three modes, so they can be tested under a python with no display.

**A group can also be OFF** (`Group.shown`, #1275), and three of the four are: the board
draws «Кодовое имя» and nothing else until the rest have been watched answering truthfully
in a live game. Off is not deleted — the group keeps its place, its fields and its
scenarios, and comes back with one word — but while it is off it exists on neither
front-end and in neither half of «сделано N из M». Everything a screen asks for goes
through :func:`visible`, so the flag is honoured once rather than in four places.

The day is the game's (`tools/lib/game_clock.py`), and it is used for exactly one thing:
saying when the quotas come back. Nothing is stored between runs — there is no tick to
keep, because the answer is re-read. The one thing that IS stored is the truck setting,
and the profile holds it: it is a choice, not a reading.
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
    """One line of the checklist: what it is, which field answers it, what plays it.

    ``field`` names a key of the reading; ``cap`` the field holding the day's allowance
    for a quota; ``gate`` a field that must be 1 for the errand to be on at all (Ghost
    Ops and its one day a week).

    **An empty ``field`` is a line nothing can answer yet** — a real errand of the day
    that this repository has no reading for. It is on the list on purpose and it says
    «состояние неизвестно» for ever, which is the honest thing to show: leaving it out
    would make the checklist look complete while a third of the day is missing from it,
    and putting a tickable box there would be the hand-marking this tab exists without.

    ``scenario`` is an `actions/*.md` the panel may PLAY for this errand, or ``""``.
    **The state is read and the doing is offered** — the two halves of the rule, and
    they are not in tension: pressing plays the ability and then the board is re-read, so
    the line follows the GAME and never the press. A row that stays red after a press is
    information, not a bug. An errand with no scenario is a perfectly good line: the
    reading is worth having whether or not the bot can act on it yet.

    **The two are independent, in both directions.** A ``field`` with no ``scenario`` is
    the common case above; a ``scenario`` with no ``field`` is the other one, and it is
    just as legitimate — the bot can do the thing and cannot see it (see
    :data:`BLIND_ERRANDS`). Such a row says «состояние неизвестно» before the press and
    after it, which is the truth: nothing was read, so nothing may be claimed.

    ``run_key`` is the button's own wording. Most say «Выполнить»; «Кодовое имя» says
    «Атаковать сейчас», because that is what its scenario does — the same mechanism, a
    different verb.

    ``closed`` is HOW a shut gate is worded — the tail of `checklist.detail.<closed>` in
    the window and of `checklist.state.<closed>` on the phone, so the two front-ends say
    the same thing in their own two registers. The default «сегодня не проводится» is
    right for Ghost Ops (one day a week) and wrong for an event that opens and shuts
    several times a day, so an errand may name its own.
    """

    __slots__ = ("key", "title_key", "field", "kind", "cap", "gate", "closed",
                 "scenario", "run_key")

    def __init__(self, key: str, field: str = "", kind: str = QUEUE, cap: str = "",
                 gate: str = "", closed: str = "closed", scenario: str = "",
                 run_key: str = "checklist.run") -> None:
        self.key = key
        self.title_key = "checklist.item." + key
        self.field = field
        self.kind = kind
        self.cap = cap
        self.gate = gate
        self.closed = closed
        self.scenario = scenario
        self.run_key = run_key

    @property
    def readable(self) -> bool:
        """Whether the game has anything to say about this one."""
        return bool(self.field)

    @property
    def runnable(self) -> bool:
        """Whether there is an ability the panel can play for this one."""
        return bool(self.scenario)


#: «Отправка грузовиков» — the trade station's fleet, and the first group of the board
#: to be more than a list of lines (#1249).
#:
#: A quota like any other: `trucks_send_left` of `trucks_send_cap`, so the counter beside
#: the group («0 из 5») is the SAME reading the row is drawn from and the two cannot
#: disagree. There is no gate field — an account whose trade station is still locked gets
#: a dash out of the scenario rather than a zero, and a dash is «unknown» (above), which
#: is what a feature this account does not have honestly looks like.
TRUCK_ERRANDS: tuple = (
    Errand("send_trucks", "trucks_send_left", QUOTA, cap="trucks_send_cap"),
)

#: The field beside the quota: how many trucks could go out RIGHT NOW. Not an errand of
#: its own — it is the same errand's «and this much of it can be done this minute», which
#: is what a person deciding whether to open the game actually wants.
TRUCK_IDLE_FIELD = "trucks_idle"

# -- how the trucks are to be improved before they go ------------------------
#: The three ways of raising a truck's rarity before it is dispatched, exactly as the
#: game offers them («Супер режим», `super_trucklaunch_*`): to UR by hand, to UR by
#: itself, or all the way to the Reindeer Sleigh Ride by itself.
#:
#: **The setting manages ITSELF and nothing else so far.** There is no dispatch scenario
#: yet, so nothing reads this to act on; it is stored in the profile and drawn, and the
#: day the ability lands it is what the ability will be told to do. Kept here rather than
#: in the tab so it is Tk-free and testable.
TRUCK_MODE_UR_MANUAL = "ur_manual"
TRUCK_MODE_UR_AUTO = "ur_auto"
TRUCK_MODE_SLEIGH_AUTO = "sleigh_auto"

TRUCK_MODES: tuple = (TRUCK_MODE_UR_MANUAL, TRUCK_MODE_UR_AUTO, TRUCK_MODE_SLEIGH_AUTO)

#: What a profile that has never been asked does: nothing by itself. An automatic refresh
#: spends Trade Contracts and diamonds, and a default that spends is a default nobody
#: chose.
TRUCK_MODE_DEFAULT = TRUCK_MODE_UR_MANUAL


def truck_mode(raw) -> str:
    """The stored mode, or the default — never something the panel cannot draw."""
    return raw if raw in TRUCK_MODES else TRUCK_MODE_DEFAULT


#: The errands the game ANSWERS, in the order a day is played: the base first, then the
#: alliance, then what the person has banked, then the two robberies. Every one of these
#: is a live reading and the same expression the matching press is gated on.
#:
#: Nine of the thirteen carry a scenario and therefore a button. The four that do not,
#: and why — because «no button» has to be a reason and not an oversight:
#:
#: * `trucks` and `queues_help` — no ability exists for either yet. The reading is
#:   still worth having, which is the whole point of `scenario` being optional.
#: * `secret_steals` and `ghost_steals` — the scenarios exist, and they are deliberately
#:   NOT offered here. Each only SPENDS a queue that its own tool has to park the targets
#:   in first (#1188, `CLAUDE.md`), so a press from this board with an empty queue would
#:   run, succeed and rob nothing — a button that reports success for doing nothing is
#:   worse than no button. They belong to «Командный пункт» and «Секретки», where the
#:   targets are chosen and the two steps are played in order.
READ_ERRANDS: tuple = (
    Errand("base_resources", "base_ready", scenario="collect_base_resources"),
    Errand("trucks", "trucks_ready"),
    Errand("hospital_collect", "healed_ready", scenario="heal_units"),
    Errand("hospital_heal", "wounded", scenario="heal_units"),
    Errand("queues_help", "queues_help"),
    Errand("alliance_help", "help_waiting", scenario="help_ally"),
    Errand("alliance_donate", "donate_left", QUOTA, scenario="donate_alliance_tech"),
    Errand("visitors_recruit", "recruit_pending", scenario="recruit_survivors"),
    Errand("visitors_gifts", "gifts_pending", scenario="collect_visitor_gifts"),
    Errand("skills", "skills_ready", scenario="occupation_skills"),
    Errand("decorations", "decorations", scenario="upgrade_decorations"),
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
#:
#: **Three of them carry a scenario all the same** (#1247), and that pair — a press with
#: no reading beside it — is deliberate rather than a half-finished row. Blind is a
#: statement about what can be SEEN, and the two halves fail independently: the bot can
#: empty the base's resource truck, claim the alliance gifts and apply for a ministry
#: post, and can see none of the three afterwards. Refusing the button until the reading
#: exists would punish the player for a gap in the reverse-engineering, and the only
#: other door to those three was the script list on «Разработка» — a tab that is off
#: unless a profile asks for it, so for an ordinary panel the abilities were simply
#: unreachable.
#:
#: What such a line says stays honest: «состояние неизвестно» before the press and after
#: it, because the row follows the reading and there is none. The scenario is what knows
#: whether it may run and says so in the log (`tab._may_run`) — `apply_ministry_interior`
#: refuses while another post is held or the cooldown is running, and names the reason.
#: A press here is «сделай», never «отметь».
BLIND_ERRANDS: tuple = (
    Errand("truck_reward", scenario="collect_truck_resources"),
    Errand("gather"),
    Errand("secret_missions"),
    Errand("secret_tasks_help"),
    Errand("radar"),
    Errand("rally_joins"),
    Errand("attack_marked"),
    Errand("treasures"),
    Errand("treasure_maps"),
    Errand("alliance_gifts", scenario="collect_alliance_gifts"),
    Errand("chat_gifts"),
    Errand("arms_race"),
    Errand("arena"),
    Errand("tavern"),
    Errand("supplies"),
    Errand("shop"),
    Errand("fireworks"),
    Errand("vip_daily"),
    Errand("battle_pass"),
    # The ability the panel has is for ONE post, so the button says «Подать заявку»
    # rather than «Выполнить» over a choice nobody made: the recipe asks for Secretary
    # of Interior and nothing else (`actions/apply_ministry_interior.md`, and the game's
    # own name for the post is in `docs/game-glossary.md`).
    Errand("ministry", scenario="apply_ministry_interior",
           run_key="checklist.run.ministry"),
)

#: «Кодовое имя» — the world-boss event, and the SECOND group of the board to be more
#: than a list of lines (#1257). The game's own name for it (key `100086` in the client's
#: tables; `docs/game-glossary.md`), and the panel may not invent another.
#:
#: The event puts one boss on the world map for a few hours at a time and asks for THREE
#: attacks on it. Attempts themselves are unlimited — the event's own rules say so, and
#: the client agrees — so what the day owes is a count being REACHED rather than an
#: allowance being spent. That still fits a quota exactly: the reading answers
#: `left = need - attacks`, so `used` comes out as attacks made and `cap` as the three
#: that earn the reward, and the counter beside the group and the row under it are the
#: same two numbers by construction.
#:
#: `open` is the gate, and it is the whole reason this group can be grey: outside a
#: window there is no boss on the map, «not done» would be a lie about a thing nobody
#: could do, and every count beside it is last window's.
CODENAME = "codename"

#: The reading, and the attack — the SAME two scenarios «События» plays
#: (`panel/tabs/events/model.py`). Named again here rather than imported so neither tab
#: has to exist for the other to work: a profile may have «Чеклист» on and «События» off,
#: or the other way round, and a board that depended on a tab being switched on would
#: fail in the one way nobody looks for. `tests/test_panel_events.py` fails if the two
#: pairs of names ever stop matching.
CODENAME_ACTION = "read_codename_event"
CODENAME_VARIABLE = "codename"
CODENAME_ATTACK = "attack_codename_boss"

#: «Атаковать сейчас» is an ORDINARY errand button — a `scenario` and a `run_key`, the
#: same two fields the other nine use. It was a special case for about an hour and that
#: was the wrong shape: an event with a press is not a different KIND of line, it is a
#: line whose ability happens to be an attack, and the day a second event has one it
#: should cost a tuple entry rather than another block of widgets.
CODENAME_ERRANDS: tuple = (
    Errand("codename", "left", QUOTA, cap="need", gate="open",
           # «сегодня не проводится» is Ghost Ops's wording and it is wrong here: this
           # boss stands FOUR times a day, so «not on today» would be a false statement
           # about the next window, which may be two hours away.
           closed="not_running",
           scenario=CODENAME_ATTACK, run_key="checklist.codename.attack"),
)

#: The two fields beside the quota. `attacks` is the quota's own spent half, named again
#: so the counter can be read WITHOUT the gate (see :func:`codename_counter`); `maxdmg` is
#: the biggest single hit — not an errand, since nothing about it is ever «done», but it
#: is the number the daily ranking is made of and the one the person is really playing
#: for once the three attacks are in.
CODENAME_ATTACKS_FIELD = "attacks"
CODENAME_DAMAGE_FIELD = "maxdmg"

#: Where a group's numbers come from. Two readings reach this board now: the daily one
#: (`read_daily_checklist`) and the event one (`read_codename_event`), because they are
#: separate abilities with separate lives — the event's is read by «События» too, and
#: one copy of a Lua expression is what keeps the two tabs from ever disagreeing.
DAILY = "daily"


class Group:
    """One block of the board: a heading and the errands drawn under it.

    A group used to be a pair — a heading key and a tuple — and it is a class now
    because a block can be MORE than its lines (#1249). «Отправка грузовиков» carries a
    counter of its own, the press that will spend it, and the setting that says how the
    trucks are to be improved first; the rest carry nothing but their rows. What a group
    is NOT is a thing the person edits: the board is the day, in the order a day is
    played, and it is fixed in code (:mod:`.tab`).

    ``key`` is what the tab tests to decide whether it draws anything extra under the
    heading; the widgets themselves stay in the tab, because this module has no Tk.
    ``source`` names which reading its numbers come from (:data:`DAILY` for all but the
    event groups).

    ``shown`` is whether the board draws it AT ALL (#1275). A group that is off is not
    deleted — it keeps its place in :data:`GROUPS`, its errands, its fields and its
    scenarios — it simply reaches neither front-end: no block in the window, no card on
    the phone, no line in «сделано N из M», and no press. **Bringing one back is that one
    word**, which is the whole reason it is a flag rather than a commented-out block: a
    group returns when its errands have been watched working in the live game, exactly
    the way a feature earns its ✅ in `docs/farming.md`, and a restore that costs a git
    archaeology dig is a restore nobody does.
    """

    __slots__ = ("key", "title_key", "errands", "source", "shown")

    def __init__(self, key: str, errands, source: str = DAILY,
                 shown: bool = True) -> None:
        self.key = key
        self.title_key = "checklist.group." + key
        self.errands = tuple(errands)
        self.source = source
        self.shown = bool(shown)

    def __iter__(self):
        """So a group still unpacks as `(heading, errands)` where that reads better."""
        return iter((self.title_key, self.errands))

    def __repr__(self) -> str:
        return f"<Group {self.key} ({len(self.errands)})>"


#: The key of the one group that is more than a list — the tab hangs the counter, the
#: press and the setting off it, and nothing else may be recognised by name.
TRUCKS = "send_trucks"

#: The groups, in the order they are drawn — every one of them, shown or not.
#:
#: The trucks go FIRST: it is the errand with the shortest fuse on it — the fleet is idle
#: until it is sent and the allowance dies with the game's day — and it is the one block
#: of the board that can be acted on from the board itself.
#: «Кодовое имя» comes SECOND, straight after the trucks and before everything read off
#: the base: it is the only errand on the board with a wall-clock deadline that is not
#: the end of the day. The boss stands for a few hours and then goes, so a block that sat
#: below twenty rows of base chores would be seen after the window had shut.
#:
#: **Three of the four are off (#1275), and «Кодовое имя» is the only one drawn.** The
#: board went up faster than its lines could be watched working, and a row nobody has
#: seen answer truthfully in a live game is a row that may be lying with a tick on it —
#: which is precisely the failure this tab exists to prevent. So the day is put back a
#: group at a time: a group is switched on when its errands have been confirmed against
#: the running game, the same bar a feature clears before it earns its ✅ in
#: `docs/farming.md`. The ORDER above is the order they will come back in, and each is
#: one `shown=True` away.
GROUPS: tuple = (
    Group(TRUCKS, TRUCK_ERRANDS, shown=False),
    Group(CODENAME, CODENAME_ERRANDS, source=CODENAME),
    Group("read", READ_ERRANDS, shown=False),
    Group("blind", BLIND_ERRANDS, shown=False),
)

ERRANDS: tuple = (TRUCK_ERRANDS + CODENAME_ERRANDS + READ_ERRANDS + BLIND_ERRANDS)

BY_KEY = {errand.key: errand for errand in ERRANDS}


def visible() -> tuple:
    """The groups the board actually draws, in the catalogue's order.

    Everything a front-end asks for goes through here — the window's blocks, the phone's
    cards, the presses, the progress. A hidden group is therefore hidden ONCE, in
    :data:`GROUPS`, rather than in the four places that would each have to remember.
    """
    return tuple(group for group in GROUPS if group.shown)


def visible_errands() -> tuple:
    """Every errand of every shown group — what the board can draw and press."""
    return tuple(errand for group in visible() for errand in group.errands)


def is_visible(key: str) -> bool:
    """Whether this errand is on the board at all.

    What the press is gated on: an errand of a hidden group must not be reachable by
    naming its key from the phone, or the group would be off in the window and on
    everywhere else.
    """
    return any(errand.key == key for errand in visible_errands())


def visible_sources() -> frozenset:
    """The readings the board still needs — one entry per shown group's ``source``.

    A scenario whose every group is off is not played: the board polls every few minutes
    and re-reads on a push, and reading numbers nobody is drawn would be paying a round
    trip a poll for a blank. It comes back with its group, since the set is computed and
    not written down.
    """
    return frozenset(group.source for group in visible())


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


def seconds_to_reset(stamp_ms=None, day_end_ms=0) -> int:
    """How long until the game's day turns over and the quotas come back.

    THE GAME'S MIDNIGHT, NOT UTC'S (#1333). This used to divide the clock by a day and
    call the remainder «до сброса», which puts the boundary at 00:00 UTC — two hours out
    on the warzone this was measured on, in the direction that matters: the board said
    «2:00 до сброса» while the quotas had already been back for two hours.

    ``day_end_ms`` is the client's own `GetTomorrowZero()`, handed in by the tab out of
    the profile's :class:`panel.runtime.day_reset.DayReset`. Zero falls back to the
    measured 02:00 UTC, which is what a profile that has never had a client to ask gets.
    """
    stamp = now_ms() if stamp_ms is None else int(stamp_ms)
    try:
        import game_day
    except Exception:                       # noqa: BLE001 — a countdown is not a crash
        return max(0, ((stamp // DAY_MS + 1) * DAY_MS - stamp) // 1000)
    return game_day.seconds_to_reset(stamp, day_end_ms)


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


def _sources(reading, codename) -> dict:
    """Which reading each group's numbers come from. Two of them now, and no more.

    A group asks for its source by name rather than being handed one, so a third
    reading is a `Group(..., source=...)` and one entry here — not a new positional
    argument threaded through every caller.
    """
    return {DAILY: reading, CODENAME: codename}


def states(reading, codename=None) -> list:
    """Every errand of every SHOWN group, in the catalogue's order.

    The board, not the catalogue: a hidden group's lines are drawn nowhere, so counting
    them in «сделано N из M» would be a total nobody can see the parts of.
    """
    src = _sources(reading, codename)
    return [state_of(errand, src[group.source])
            for group in visible() for errand in group.errands]


def grouped(reading, codename=None) -> list:
    """``[(group, [state, …]), …]`` — the board as both front-ends draw it."""
    src = _sources(reading, codename)
    return [(group, [state_of(errand, src[group.source]) for errand in group.errands])
            for group in visible()]


def codename_counter(reading) -> tuple:
    """``(attacks, need, damage)`` for «Кодовое имя» — any of them ``None``.

    The counter the group wears, «1 из 3»: how many attacks have gone out at the boss,
    how many earn the reward, and the biggest single hit.

    **Read straight off the fields rather than through the gated row**, and that is the
    difference between «—» and «0 / 3» on the six-sevenths of the week the boss is not
    standing. The row is CLOSED then, and rightly — nothing is owed while there is
    nothing to attack — but the numbers themselves are still the last thing that was
    true, and the damage beside them is drawn whatever the gate says. Dashing one and
    printing the other would say the panel had lost track of the count.

    ``None`` still stays ``None`` all the way to the words: «nobody knows» must never be
    drawn as a zero.
    """
    if reading is None or reading.error:
        return None, None, None
    return (reading.get(CODENAME_ATTACKS_FIELD),
            reading.get(CODENAME_ERRANDS[0].cap),
            reading.get(CODENAME_DAMAGE_FIELD))


def damage(value) -> str:
    """`12 607 399 171` — a hit big enough to need its digits grouped.

    A number, not a word: the separator is a space in every language the panel ships.
    Rounding it to «12.6B» would be a second opinion about the one figure the event's
    daily ranking is decided on, so the digits stay.
    """
    if value is None:
        return "—"
    try:
        return "{:,}".format(int(value)).replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def truck_counter(reading) -> tuple:
    """``(sent, cap, idle)`` for «Отправка грузовиков» — any of them ``None``.

    The counter the group wears, «0 из 5»: how many trade trucks have gone out today,
    how many may, and how many could go this minute. It is the QUOTA's own two halves
    rather than a second reading of the same thing, so the counter and the row under it
    cannot say different numbers — and ``None`` stays ``None`` all the way to the words,
    because «nobody knows» must never be drawn as a zero.
    """
    state = state_of(TRUCK_ERRANDS[0], reading)
    idle = reading.get(TRUCK_IDLE_FIELD) if reading is not None else None
    return state.used, state.cap, idle


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
