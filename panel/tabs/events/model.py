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

#: «Кристальный босс» — the SAME event with a different manager, and the person said so
#: in those words: «аналогична событию кодового имени, суть та же, 3 атаки». One boss
#: stands on the world map for a window that covers the server day, and the day pays for
#: THREE attacks on it.
#:
#: What is NOT the same as its neighbour, and it is the reason this is a card of its own
#: rather than a second row on that one: attempts here ARE rationed. «Кодовое имя» draws
#: «сделано из трёх» over an unlimited allowance, so a fourth attack there is worth
#: making; this event has three and the server counts them, from whatever hand made
#: them. So the number beside it is what the day still OWES, and the recipe refuses a
#: fourth march rather than spending a squad for nothing.
#:
#: The reading is `actions/read_crystal_boss.md`, the attack `attack_crystal_boss.md`,
#: the day's worth `attack_crystal_boss_daily.md`, and the reverse-engineering is
#: docs/research/crystal-boss.md.
CRYSTAL = "crystal"

#: The scenario that answers it, and the variable it lands in.
CRYSTAL_ACTION = "read_crystal_boss"
CRYSTAL_VARIABLE = "crystal"

#: The two presses: one attack, and the whole day's worth. The second is the errand the
#: clock plays once a day, offered here because a person who has just come back to the
#: machine wants it NOW rather than at the top of the next period — and it costs nothing
#: on a day already played, because it asks the server first.
CRYSTAL_ATTACK = "attack_crystal_boss"
CRYSTAL_DAILY = "attack_crystal_boss_daily"

#: …and the third press, the one #2638 added: the event pays out in CHESTS as well as in
#: the fight — «Weekly Damage Rewards» for the damage record of the week and «Achievement
#: Rewards» for what the account has done in it, both of them the game's own words out of
#: its own tables. They are earned by attacking and then sit there until somebody claims
#: them, which is why the day's errand claims them after its three attacks: the third
#: attack is exactly the moment the week's damage record can have moved.
CRYSTAL_COLLECT = "collect_crystal_boss_rewards"

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

#: Whether the chain rides to a far target on a GATHER order before attacking it. The
#: game prices a march per ORDER — live, a gather march is 2.52x an attack one — so a
#: long haul is worth riding to a mine beside the zombie and paying only the last few
#: tiles at attack speed. A switch rather than a fact, because the two speeds come from
#: separate bonuses and an account that has levelled neither gains nothing.
#:
#: **AND IT SHIPS OFF, WHICH IS A JUDGEMENT ABOUT THE COST OF BEING WRONG (#1702).** A
#: ride is a GATHER order, and a gather order that lands parks the squad on the mine for
#: as long as the mine takes — measured live, 24 762 seconds, during which every attack
#: is refused in silence. The chain now calls a ride off the moment its zombie dies and
#: recalls by the march's own uuid, which is the recall that works on a gather; but the
#: gain is only ever the travel time to a FAR target, and the loss is a whole run and a
#: squad that has to be fetched by hand. Off unless somebody turns it on knowing that.
GOLDEN_APPROACH_KEY = "golden_approach"
GOLDEN_SQUADS: tuple = (1, 2, 3, 4)
GOLDEN_SQUAD_DEFAULT = 1

#: HOW MANY ATTACKS ONE RUN MAY MAKE — the recipe's `limit`, and 0 is «as many as the
#: energy allows», which is the recipe's own default and what the hunt has always done.
#: A knob since #2408: it is the one way to spend half a purse deliberately, and it was
#: reachable from nowhere at all.
GOLDEN_LIMIT_KEY = "golden_limit"
GOLDEN_LIMIT_DEFAULT = 0
GOLDEN_LIMIT_MAX = 200

#: THE SQUARE THE CHAIN WORKS, IN TILES — the recipe's `cluster` (#2390). The queue is
#: cut into squares of this side, the fullest is chosen, and every pick is made inside it
#: until it is empty. 0 goes back to «the nearest zombie anywhere», which is what left the
#: hunt with one target and a full purse once the invasion had moved off the base.
GOLDEN_CLUSTER_KEY = "golden_cluster"
GOLDEN_CLUSTER_DEFAULT = 50
GOLDEN_CLUSTER_MAX = 2000

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

#: «Салют» — the firework a player lights over their own base, which drops gift boxes
#: for everyone who can see it while it burns.
#:
#: THE ONE BLOCK ON THIS BOARD WITH NO READING SCENARIO, and for a reason no reading can
#: fix: a box is announced, taken and gone inside seconds, and the game keeps no answer
#: to «how many did you get today» — `LWFireworkGiftManager.giftUuid2TimeTable` holds
#: the account's lifetime record and nothing per day. So what is drawn here is the WIRE's
#: own history (`panel/runtime/firework_wire.py`): announcements heard, boxes that
#: actually arrived, when the last one did, and how long after the announcement. It is
#: the same standing as the golden-zombie tally above — the panel's record of what it
#: saw happen, never a claim about what the account has.
FIREWORKS = "fireworks"

#: «Поезд альянса» — the trade train that stands at the alliance station.
#:
#: It arrives with nobody driving it, and an R4 or R5 appoints a CONDUCTOR; the queue
#: opens at that moment and the train leaves on a clock. A passenger picks a carriage and
#: offers the conductor a fare — a like, which costs nothing, or up to three Trade
#: Contracts out of the bag. The reading is `actions/read_alliance_train.md` and the
#: press is `actions/board_alliance_train.md`; **the two knobs are the only things on
#: this card a person sets**, and both are a standing order for the wire trigger rather
#: than a press of their own.
TRAIN = "train"

#: The scenario that answers the train, and the variable it lands in.
TRAIN_ACTION = "read_alliance_train"
TRAIN_VARIABLE = "train"

#: …and the one press: board a carriage and pay the fare. Every gate is inside it.
TRAIN_BOARD = "board_alliance_train"

#: The two saved knobs — which carriage to queue in, and what to offer the conductor.
#: Both are about THIS account, so they live in the tab's own block (`tabs.config.events`)
#: and travel with the profile.
TRAIN_CARRIAGE_KEY = "train_carriage"
TRAIN_TICKETS_KEY = "train_tickets"

#: The carriages a passenger may board. Four on every train seen so far; the recipe
#: clamps to what the train in front of it actually has, so a fifth costs nothing here.
TRAIN_CARRIAGES: tuple = (1, 2, 3, 4)
TRAIN_CARRIAGE_DEFAULT = 1

#: What may be offered: `0` is a like and free, `1..3` are Trade Contracts. The game's own
#: floor and ceiling (`GetThanksItemMin` / `GetThanksItemMax`) are 1 and 3.
TRAIN_TICKETS: tuple = (0, 1, 2, 3)
TRAIN_TICKETS_DEFAULT = 0

#: Whether the missing contracts may be BOUGHT for diamonds when the bag is short.
#:
#: **Off, and it is a separate answer from the number on purpose.** The number says what
#: the fare should be; this says whether the panel may reach into the player's diamonds
#: to make it up — two different permissions, and the operator asked for them apart:
#: «даем выбор, сколько билетов давать от 0 до 3 и галку, докупать, если не хватает».
#: With it off, a short bag simply pays less. With it on, the purchase is capped by the
#: NUMBER and never goes a contract past it, and every purchase names itself in the log
#: with what it cost — an allowed spend is still a spend, and a silent one is not allowed
#: even when the box is ticked (`CLAUDE.md`).
TRAIN_BUY_KEY = "train_buy"
TRAIN_BUY_DEFAULT = False

#: The platform states the game has. Boarding is possible from `WITH_DRIVER` upwards:
#: below it there is nobody driving and the queue is not open.
TRAIN_NO_TRAIN = 0
TRAIN_NO_DRIVER = 1
TRAIN_WITH_DRIVER = 2
TRAIN_WITH_PASSENGER = 3

#: The groups, in the order they are drawn. One so far, and the shape is what matters:
#: a second event is one entry here, one `Group`, and its own reading.
#: «Гонка вооружений» — six four-hour phases a day, each paying points for ONE kind of
#: progress, on a schedule the server fixed a week ahead.
#:
#: The card exists because the event is unreadable without it: the client volunteers the
#: phase running NOW and nothing else, so «what comes next» is a question a person
#: otherwise answers by opening the game. The calendar is one message away and the
#: reading sends it (`actions/read_arms_race.md`), which is what lets this card draw the
#: whole day and lets the errand book its next turn on a phase BORDER instead of
#: grinding a period against an event that changes five times a day.
#:
#: Nothing here is counted by the panel. `sc` is the server's own tally, so points made
#: from the phone or by the person playing are already in it — the same rule the rest of
#: this board goes by. The research is docs/research/arms-race.md.
ARMS = "arms"

#: The scenario that answers it, and the two variables it lands in — the phase running
#: now, and the day's six borders.
ARMS_ACTION = "read_arms_race"
ARMS_VARIABLE = "arms"
ARMS_DAY_VARIABLE = "arms_day"

#: The press: do what the phase running now pays for, then book the border.
ARMS_ERRAND = "perform_arms_race"

#: …and the PUSH-DRIVEN half of the drone hour (#2661). A march of ours ending is
#: `push.world.march.del`, and this trigger answers it by playing `arms_race_drone`
#: again — «отряд вернулся — сразу отправляем его снова». The errand above keeps its turn
#: on the phase border as the safety net for a profile whose wire ear is down.
ARMS_RELAY = "arms_drone_relay"

#: …and the same order on the push that is OURS rather than the world's: the server says
#: when THIS account's arms score moves, which during the drone hour is a banner of ours
#: resolving. Same recipe, same gates — two events, not two behaviours.
ARMS_RELAY_SCORE = "arms_drone_score"

#: Which squads that order may spend. All four, and deliberately not the single squad the
#: card names: a squad still in the air is skipped rather than failing the hour, which is
#: what «работать поотрядно» means. One string, in the form the recipe's `ARGS squads`
#: reads, so the card and the standing order cannot hold two answers.
ARMS_RELAY_SQUADS = "1,2,3,4"

#: …and the one phase that has a recipe, played on its own by the button beside it.
ARMS_HERO_ACTION = "arms_race_hero"

#: The five kinds of phase, by the id the server sends. The NAMES are the game's own and
#: are copied out of its tables into the locales (`docs/game-glossary.md`); a kind the
#: server invents tomorrow draws its bare id rather than a guess.
ARMS_HERO = 120000
ARMS_BUILD = 120001
ARMS_UNIT = 120002
ARMS_TECH = 120003
ARMS_DRONE = 120004
ARMS_KINDS: dict = {
    ARMS_HERO: "events.arms.kind.hero",
    ARMS_BUILD: "events.arms.kind.build",
    ARMS_UNIT: "events.arms.kind.unit",
    ARMS_TECH: "events.arms.kind.tech",
    ARMS_DRONE: "events.arms.kind.drone",
}

#: …and the one for the drone phase, which is paid for in STAMINA and in the day's own
#: rallies: the points come from raising banners and nothing else (#2065).
ARMS_DRONE_ACTION = "arms_race_drone"

#: …and the ONE recipe behind the other three, because they are one ability: building,
#: units and research all pay for MINUTES of speed-up poured into a queue, and only the
#: queue and the message differ (#2065).
ARMS_SPEEDUP_ACTION = "arms_race_speedup"

#: …and the unit phase's own, which spends RESOURCES rather than anything out of the bag:
#: it collects the barracks that have finished and starts the biggest batch each free one
#: will take. 28 points a level-9 soldier, measured live (#2065).
ARMS_UNIT_ACTION = "arms_race_units"

#: Which kinds the panel can act on — all five now. The list decides whether a BUTTON is
#: offered, so it is here rather than in the tab; a phase the server invents tomorrow is
#: not in it and draws «no recipe» rather than a button that reports success for doing
#: nothing.
ARMS_AUTOMATED: tuple = (ARMS_HERO, ARMS_BUILD, ARMS_UNIT, ARMS_TECH, ARMS_DRONE)

#: What each automated phase is played by, so neither front-end has to know.
ARMS_PLAYS: dict = {ARMS_HERO: ARMS_HERO_ACTION,
                    ARMS_BUILD: ARMS_SPEEDUP_ACTION,
                    ARMS_UNIT: ARMS_UNIT_ACTION,
                    ARMS_TECH: ARMS_SPEEDUP_ACTION,
                    ARMS_DRONE: ARMS_DRONE_ACTION}

#: The phases whose points are MINUTES, kept apart from the other two because the button
#: over them asks a different question and spends a different thing.
#:
#: «Прогресс юнита» is deliberately NOT among them, and it is not an oversight. Its
#: points are not bought with minutes at all: the person's design is «ускорить, чтобы
#: ОСВОБОДИТЬ очередь → собрать готовых → поставить максимум 9 уровня», so what it
#: spends is the player's RESOURCES and its ceiling is counted in SOLDIERS. It has a
#: recipe of its own since the training send was proven live — two barracks started on
#: 500 each and the phase score moved 0 → 28 000 in the same minute (#2065).
ARMS_MINUTE_KINDS: tuple = (ARMS_BUILD, ARMS_TECH)

#: Whether the errand's hero phase may hire. Saved in this tab's own block, because it
#: is a decision about THIS account; how MANY hires is the recipe's `ARGS pulls`.
ARMS_HERO_KEY = "arms_hero"
ARMS_HERO_DEFAULT = True

#: …and the same for the drone phase, whose ceiling is a NUMBER the person named: «час
#: дрона, 300 энергии, это стамина, тратим только стягами».
ARMS_DRONE_KEY = "arms_drone"
ARMS_DRONE_DEFAULT = True
ARMS_STAMINA_KEY = "arms_stamina"
ARMS_STAMINA_DEFAULT = 300
#: The bounds of that ceiling. Zero is a legal answer and means «raise nothing»; the top
#: is a whole day's stamina bar several times over, so the field never argues with an
#: account whose bar is bigger than this one's.
ARMS_STAMINA_MIN = 0
ARMS_STAMINA_MAX = 2000

#: Whether the errand's building / units / research phases may spend speed-ups, and the
#: most minutes ONE run may pour into a queue. OFF by default and small by default: the
#: items are the player's own, and the first live run of each of those phases is the
#: person's, with a ceiling they chose (`CLAUDE.md`). The minutes are a FUSE rather than
#: a target: what a phase really needs is read from the live threshold and the live rate
#: every run, and this only says «whatever you worked out, no more than this».
ARMS_SPEEDUP_KEY = "arms_speedup"
ARMS_SPEEDUP_DEFAULT = False
ARMS_MINUTES_KEY = "arms_minutes"
ARMS_MINUTES_DEFAULT = 6000
#: The bounds of that FUSE. Zero is a legal answer and means «spend nothing at all».
#:
#: It is deliberately NOT the target and deliberately not 3 000. «Финиш зависит от уровня
#: героя, не нужно хардкодить 3000 минут, нужно читать текущий календарь» — the top
#: chest's threshold belongs to the player and the phase (a research phase read 30 000
#: where an earlier hero phase read 12 000), so what a run needs is worked out every time
#: from the live threshold and the live rate. 600 five-minute speed-ups — 3 000 minutes —
#: is what that arithmetic came to for THIS account on THIS phase, and it is a fact to
#: check against rather than a number to keep.
#:
#: The default is twice that, so the fuse does not bite during ordinary work; it exists
#: for the day the threshold or the rate is misread, and the log prints what was wanted
#: beside what was spent so a fuse that bit is visible at once.
ARMS_MINUTES_MIN = 0
ARMS_MINUTES_MAX = 20000

#: Whether the errand's unit phase may collect the finished batches and start new ones,
#: and the most soldiers ONE run may put into training. A SEPARATE switch from the
#: speed-up one, because it spends a different thing: resources out of the base rather
#: than items out of the bag, and an account that is saving for a building wants to say
#: no to one without saying no to the other. OFF by default, like every knob here that
#: spends something.
ARMS_UNITS_KEY = "arms_units"
ARMS_UNITS_DEFAULT = False
ARMS_SOLDIERS_KEY = "arms_soldiers"
#: AND ITS DEFAULT IS «NO CEILING», deliberately. A ceiling nobody asked for is a way for
#: the panel to stop the thing the person asked it to do: a floor of ours cost most of a
#: unit phase once, and the rule that came out of it is «страховка, которую придумали МЫ,
#: не имеет права блокировать то, что человек прямо просил». **What the maximum is, is
#: the GAME's answer** — the recipe asks each barracks for the size the game has already
#: accepted for it and lets the server refuse. This field exists for the person who wants
#: a ceiling, and it is 0 until they say otherwise.
#:
#: A thousand is what one live run put in, over two barracks, for 28 000 of that phase's
#: 75 000 — a fact to check a ceiling against rather than a number to keep.
ARMS_SOLDIERS_DEFAULT = 0
ARMS_SOLDIERS_MIN = 0
ARMS_SOLDIERS_MAX = 100000

#: …and the minutes that run may spend FREEING a barracks that is still training. A
#: separate number from the speed-up fuse of the minutes phases, because it buys a
#: different thing: not points, but an empty barracks to start a scoring batch in.
#:
#: 0 by default even though the send is proven (one five-minute piece moved a barracks by
#: exactly 300 s on a test account): what it spends is the player's own speed-ups, and
#: every knob here that spends something starts at «nothing» until the person says
#: otherwise. A run given 0 simply trains into whatever is already free.
ARMS_FREE_MINUTES_KEY = "arms_free_minutes"
ARMS_FREE_MINUTES_DEFAULT = 0
ARMS_FREE_MINUTES_MIN = 0
ARMS_FREE_MINUTES_MAX = 20000

#: Which squad raises the drone phase's banners, by the slot the player sees.
ARMS_SQUAD_KEY = "arms_squad"
ARMS_SQUAD_DEFAULT = 1

#: THE DRONE PHASE HAS NO RALLY ALLOWANCE, AND MUST NOT BE GIVEN ONE (#2574). It used to
#: spend out of the elite group's daily cap in `panel/rally_limits.py`; that book counts
#: JOINS — how many of somebody else's banners the «rally_auto_join» trigger may take
#: today — and this phase RAISES banners instead. The person's words: «Автостяги с
#: дроном никак не связаны, на стяги, что мы создаем лимитов нет». The game charges a
#: raise in stamina and caps it nowhere, so the run's ceilings are the stamina, the
#: phase's top chest and the squad, and nothing here hands it a number.


def arms_stamina_of(value) -> int:
    """A stamina ceiling that came out of a file or off a phone, clamped to the field."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ARMS_STAMINA_DEFAULT
    return max(ARMS_STAMINA_MIN, min(ARMS_STAMINA_MAX, number))


def arms_free_minutes_of(value) -> int:
    """A freeing ceiling that came out of a file or off a phone, clamped to the field."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ARMS_FREE_MINUTES_DEFAULT
    return max(ARMS_FREE_MINUTES_MIN, min(ARMS_FREE_MINUTES_MAX, number))


def arms_soldiers_of(value) -> int:
    """A training ceiling that came out of a file or off a phone, clamped to the field."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ARMS_SOLDIERS_DEFAULT
    return max(ARMS_SOLDIERS_MIN, min(ARMS_SOLDIERS_MAX, number))


def arms_minutes_of(value) -> int:
    """A speed-up ceiling that came out of a file or off a phone, clamped to the field."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ARMS_MINUTES_DEFAULT
    return max(ARMS_MINUTES_MIN, min(ARMS_MINUTES_MAX, number))

GROUPS: tuple = (Group(CODENAME), Group(CRYSTAL), Group(GOLDEN),
                 Group(FIREWORKS), Group(ARMS))


def when(stamp: float) -> str:
    """A unix stamp as `дд.мм чч:мм`, or `—` when nothing has happened yet.

    Local time on purpose: this is «когда я его забрал», read by the person sitting at
    the machine, and the game's own clock (`tools/lib/game_clock.py`) answers a different
    question — which SERVER day a thing belongs to, which is what `day` already carries.
    """
    try:
        stamp = float(stamp or 0.0)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0.0:
        return "—"
    import datetime as _dt                              # noqa: PLC0415 — one format
    return _dt.datetime.fromtimestamp(stamp).strftime("%d.%m %H:%M")


def reaction(last: int, best: int) -> str:
    """`120 мс (лучшее 90)` — how fast the announcement was answered, or `—`.

    Milliseconds because that is the size the answer turned out to be: the press is made
    inside the client, in the same call that delivered the announcement
    (`actions/watch_fireworks.md`), so this number is a network round trip and not a
    panel's reaction time.
    """
    try:
        last, best = int(last), int(best)
    except (TypeError, ValueError):
        return "—"
    if last < 0:
        return "—"
    return f"{last} ms" if best < 0 or best == last else f"{last} ms ({best} ms)"


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


class CrystalState:
    """What «Кристальный босс» says right now — the whole card, in one object.

    ``attacks`` is how many of the day's have been made and ``need`` how many it pays
    for; ``left`` is what is still owed, and it is the SERVER's own number, so an attack
    made from the phone or by the person playing is already in it. ``health`` is what the
    boss has left as a percentage of what it started the window with. ``None`` anywhere
    means the game would not answer, and the card draws that as words rather than as a
    number nobody can trust.
    """

    __slots__ = ("state", "attacks", "need", "left", "health", "targets", "seconds",
                 "bonus", "bonus_taken", "bonus_total", "weekly_taken",
                 "daily", "daily_taken", "daily_made", "daily_need")

    def __init__(self, state: str, attacks=None, need=None, left=None, health=None,
                 targets=None, seconds=None, bonus=None, bonus_taken=None,
                 bonus_total=None, weekly_taken=None, daily=None, daily_taken=None,
                 daily_made=None, daily_need=None) -> None:
        self.state = state
        self.attacks = attacks
        self.need = need
        self.left = left
        self.health = health
        self.targets = targets
        #: Seconds left in the open window, when there is one.
        self.seconds = seconds
        #: The event's CHESTS (#2638). It pays out along two lists of its own, and the
        #: game names them itself: «Weekly Damage Rewards», one chest per segment of the
        #: week's damage record, and «Achievement Rewards», one per achievement.
        #:
        #: ``bonus`` is what can be claimed RIGHT NOW over both of them — the number the
        #: card leads with, because it is the only one anybody acts on. ``weekly_taken``
        #: is how many damage segments have already been claimed this week, and
        #: ``bonus_taken`` / ``bonus_total`` are the achievements taken against the
        #: achievements there are. ``None`` anywhere is «the game would not say», which
        #: is never drawn as a zero.
        self.bonus = bonus
        self.bonus_taken = bonus_taken
        self.bonus_total = bonus_total
        self.weekly_taken = weekly_taken
        #: …and the THIRD chest (#2702), which is a different shape from the two lists:
        #: one a DAY, whose whole gate is «the day's attacks are made».
        #:
        #: ``daily`` is the client's own verdict on whether it can be claimed right now
        #: and ``daily_taken`` whether it has already been taken today. They are not
        #: opposites — a day whose attacks are not in yet is neither — which is why both
        #: are held rather than one being derived from the other. ``daily_made`` /
        #: ``daily_need`` are the attacks toward it, as the CHEST'S own data counts them.
        #: ``None`` anywhere is «the game would not say», never a zero.
        self.daily = daily
        self.daily_taken = daily_taken
        self.daily_made = daily_made
        self.daily_need = daily_need

    @property
    def open(self) -> bool:
        return self.state == OPEN

    @property
    def done(self) -> bool:
        """Are the day's attacks in? ``False`` while nobody knows — never a guess."""
        return self.left is not None and self.left <= 0

    @property
    def can_attack(self) -> bool:
        """May «Атаковать сейчас» be pressed?

        The same rule the rest of this board goes by: only the game having SAID there is
        no boss — `CLOSED` — kills the button. **A day already played does NOT**, even
        though the recipe will refuse it: the ability holds its own gates (`CLAUDE.md`),
        and a panel that made its own copy of «осталось 0» would refuse over a reading a
        minute old while the server had already turned the day over. The refusal is one
        line in the log and costs nothing; a button that is dead when the game would have
        allowed the press costs the day's reward.
        """
        return self.state != CLOSED

    @property
    def can_collect(self) -> bool:
        """May «Забрать бонусы» be pressed — has the game SAID there is one waiting?

        The other way round from the attack button, and deliberately: an attack is worth
        offering over a reading nobody could take, because the recipe asks the server
        itself and refuses in one line. A claim over a list the game has never described
        would press nothing at all, so the button appears when a chest has been COUNTED —
        and `None`, «nobody knows», is not a count.

        Since #2702 it also covers the DAY'S chest, which the same recipe claims: three
        chests with three separate gates, and the button is offered when ANY of them has
        been said to be waiting. A press over the other two being empty is not a wasted
        one — the recipe reads each gate for itself and says so in one line.
        """
        return bool(self.bonus) or bool(self.daily)

    def __repr__(self) -> str:
        return (f"<crystal {self.state} {self.attacks}/{self.need} hp={self.health} "
                f"bonus={self.bonus}>")


def crystal_state(reading) -> "CrystalState":
    """The crystal-boss card against one reading. Never guesses: no answer is `unknown`."""
    if reading is None or reading.error:
        return CrystalState(UNKNOWN)
    is_open = reading.get("open")
    if is_open is None:
        return CrystalState(UNKNOWN)
    return CrystalState(
        OPEN if is_open else CLOSED,
        attacks=reading.get("made"),
        need=reading.get("need"),
        left=reading.get("left"),
        health=reading.get("hp"),
        targets=reading.get("targets"),
        seconds=reading.get("until"),
        bonus=reading.get("bonus"),
        bonus_taken=reading.get("achdone"),
        bonus_total=reading.get("achall"),
        weekly_taken=reading.get("wdone"),
        daily=reading.get("daily"),
        daily_taken=reading.get("dtaken"),
        daily_made=reading.get("dmade"),
        daily_need=reading.get("dneed"),
    )


def crystal_left(state) -> str:
    """`2` — attacks the day still owes, or `—` for «the game would not say»."""
    return "—" if state.left is None else str(state.left)


def crystal_bonus(state) -> str:
    """`2` — chests waiting to be claimed, or `—` for «the game would not say» (#2638)."""
    return "—" if state.bonus is None else str(state.bonus)


def crystal_achievements(state) -> str:
    """`5 / 7` — achievement chests already taken against how many there are."""
    if state.bonus_taken is None or state.bonus_total is None:
        return "—"
    return "%d / %d" % (state.bonus_taken, state.bonus_total)


def crystal_weekly_taken(state) -> str:
    """`108` — damage segments of this week whose chest has already been claimed."""
    return "—" if state.weekly_taken is None else str(state.weekly_taken)


def crystal_daily(state, t) -> str:
    """What the DAY'S chest is doing, in the words a person uses about it (#2702).

    Four answers and they are not a scale: «есть, забирай» when the game says it can be
    claimed, «забран» when it has been taken today, «3 / 3» — the attacks toward it —
    while it is neither, and «—» when the game would not say. `t` is the tab's own
    translator, because three of the four are words rather than numbers.
    """
    if state.daily:
        return t("events.crystal.daily.chest.ready")
    if state.daily_taken:
        return t("events.crystal.daily.chest.taken")
    if state.daily_made is None or state.daily_need is None:
        return "—"
    return "%d / %d" % (state.daily_made, state.daily_need)


def health(state) -> str:
    """`72%` — what the boss has left, or `—`. A share and not a bar: the card is a line
    of text on both front-ends, and a percentage is the whole of what a person wants.
    """
    return "—" if state.health is None else "%d%%" % state.health


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

    __slots__ = ("state", "energy", "cost", "attacks", "seen", "atk", "col", "ratio")

    def __init__(self, state: str, energy=None, cost=None, attacks=None,
                 seen=None, atk=None, col=None, ratio=None) -> None:
        self.state = state
        self.energy = energy
        self.cost = cost
        self.attacks = attacks
        self.seen = seen
        #: What the game prices an attack march and a gather march at, and the one over
        #: the other. Tenths, because the reading carries them as thousandths of a tile
        #: per second and nobody reads that.
        self.atk = atk
        self.col = col
        self.ratio = ratio

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
    speeds = {"atk": reading.get("atk"), "col": reading.get("col"),
              "ratio": reading.get("ratio")}
    if energy is None or cost is None:
        return GoldenState(UNKNOWN, energy=energy, cost=cost,
                           attacks=reading.get("attacks"), seen=reading.get("seen"),
                           **speeds)
    state = OPEN if (cost > 0 and energy >= cost) else CLOSED
    return GoldenState(state, energy=energy, cost=cost,
                       attacks=reading.get("attacks"), seen=reading.get("seen"),
                       **speeds)


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


def speed(state) -> str:
    """`0.77 / 1.93 · x2.5` — the attack march, the gather march, and the gain.

    The reading carries them as thousandths (the game's own number times a thousand, so
    they survive the `key=value` line as whole numbers); a person wants two decimals and
    the ratio, which is the only part of it that decides anything.
    """
    if not state.atk or not state.col:
        return "—"
    atk, col = state.atk / 1000.0, state.col / 1000.0
    ratio = (state.ratio or 0) / 100.0
    return "%.2f / %.2f · ×%.1f" % (atk, col, ratio)


def lap(average: int, last: int) -> str:
    """`38 с · 31` — the seconds between two orders, as the run itself counted them.

    The average first, because it is the number that says whether a hunt is quick; the
    most recent one after it, because a chain that is speeding up or bogging down says so
    there first. **A run that sent fewer than two orders has no lap at all** and this
    answers «—», the same way every other reading here refuses to invent a number: one
    order tells you nothing about the gap between orders, and a `0 с` on this card would
    read as the fastest hunt there has ever been.
    """
    average, last = int(average or 0), int(last or 0)
    if average <= 0:
        return "—"
    if last > 0 and last != average:
        return "%d · %d" % (average, last)
    return str(average)


def tally(row) -> str:
    """`6 · 60` — the day's attacks and the energy they cost, as this panel sent them."""
    row = row or {}
    return "%d · %d" % (int(row.get("attacks", 0) or 0), int(row.get("spent", 0) or 0))


def whole_of(raw, fallback: int, low: int, high: int) -> int:
    """A saved whole number, held inside its bounds (#2408).

    A HALF-TYPED BOX IS NEVER OBEYED — the rule the rest of the panel already keeps
    (`panel/runtime/opt_value.py`): a blank «лимит атак» read as 0 would be a different
    ability, and a stray letter in the square's side would silently unpick the clustering
    that #2390 was written for.
    """
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, value))


def squad_of(raw) -> int:
    """A saved squad slot, clamped to one that exists. Anything odd reads as the first."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return GOLDEN_SQUAD_DEFAULT
    return value if value in GOLDEN_SQUADS else GOLDEN_SQUAD_DEFAULT


class TrainState:
    """What the alliance train says right now — the whole card, in one object.

    ``platform`` is the game's own platform state (:data:`TRAIN_NO_TRAIN` …
    :data:`TRAIN_WITH_PASSENGER`); ``queued`` whether WE are in a carriage and
    ``carriage`` which one, as the player sees them. ``thanked`` is whether the fare has
    been paid for this train — by this panel or by the person playing, because it is read
    off the game and never counted here. ``None`` anywhere means the game would not
    answer, and the card draws that as words rather than as a number nobody can trust.
    """

    __slots__ = ("state", "platform", "queued", "carriage", "waiting", "cars", "seats",
                 "departs", "thanked", "contracts")

    def __init__(self, state: str, platform=None, queued=None, carriage=None,
                 waiting=None, cars=None, seats=None, departs=None, thanked=None,
                 contracts=None) -> None:
        self.state = state
        self.platform = platform
        self.queued = queued
        self.carriage = carriage
        self.waiting = waiting
        self.cars = cars
        self.seats = seats
        self.departs = departs
        self.thanked = thanked
        self.contracts = contracts

    @property
    def open(self) -> bool:
        return self.state == OPEN

    @property
    def boardable(self) -> bool:
        """Has a conductor been appointed? ``False`` while nobody knows — never a guess."""
        return self.platform is not None and self.platform >= TRAIN_WITH_DRIVER

    @property
    def can_board(self) -> bool:
        """May «Сесть в вагон» be pressed?

        Only the game SAYING the station is shut kills it, the same rule the two boards
        above draw their buttons by: the ability holds its own gates (`CLAUDE.md`), and a
        panel refusing on its own behalf is a second, worse copy of them that the two
        front-ends then disagree on. Being aboard already does not kill it either — the
        press is a clean no-op then, and it is also how the fare gets paid on a train
        somebody boarded by hand.
        """
        return self.state != CLOSED

    def __repr__(self) -> str:
        return f"<train {self.state} platform={self.platform} queued={self.queued}>"


def train_state(reading) -> "TrainState":
    """The train card against one reading. No answer is `unknown`, never `closed`."""
    if reading is None or reading.error:
        return TrainState(UNKNOWN)
    is_open = reading.get("open")
    if is_open is None:
        return TrainState(UNKNOWN)
    return TrainState(
        OPEN if is_open else CLOSED,
        platform=reading.get("state"),
        queued=reading.get("queued"),
        carriage=reading.get("carriage"),
        waiting=reading.get("waiting"),
        cars=reading.get("cars"),
        seats=reading.get("seats"),
        departs=reading.get("departs"),
        thanked=reading.get("thanked"),
        contracts=reading.get("contracts"),
    )


def carriage_of(raw) -> int:
    """A saved carriage number, clamped to one that exists. Anything odd reads as the first."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return TRAIN_CARRIAGE_DEFAULT
    return value if value in TRAIN_CARRIAGES else TRAIN_CARRIAGE_DEFAULT


def tickets_of(raw) -> int:
    """A saved fare, clamped to what the game accepts. Anything odd reads as the free like."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return TRAIN_TICKETS_DEFAULT
    return value if value in TRAIN_TICKETS else TRAIN_TICKETS_DEFAULT


def train_seat(state) -> str:
    """`вагон 2` as a number, or `—` while we are in none."""
    if state.carriage is None or state.carriage < 1:
        return "—"
    return str(state.carriage)


def train_queue(state) -> str:
    """`57 / 28` — how many are queued against how many seats the train has."""
    if state.waiting is None:
        return "—"
    if not state.cars or not state.seats:
        return str(state.waiting)
    return "%d / %d" % (state.waiting, state.cars * state.seats)


class ArmsState:
    """What «Гонка вооружений» says right now — the whole card, in one object.

    ``kind`` is the phase's id (:data:`ARMS_KINDS`), ``score`` the points the SERVER has
    for this phase, ``targets`` the three chest totals and ``taken`` which of them are
    already claimed. ``None`` anywhere is «the game would not say» and is drawn as words
    — never as a zero, which on this card would read as «you have done nothing» when the
    truth is «nobody asked».
    """

    __slots__ = ("state", "day", "stage", "kind", "score", "targets", "taken",
                 "seconds", "done", "day_taken", "phases")

    def __init__(self, state: str, day=None, stage=None, kind=None, score=None,
                 targets=(), taken=(), seconds=None, done=None, day_taken=(),
                 phases=()) -> None:
        self.state = state
        self.day = day
        self.stage = stage
        self.kind = kind
        self.score = score
        #: The three chest totals of the phase, smallest first.
        self.targets = tuple(targets)
        #: …and 1 for each of them already claimed.
        self.taken = tuple(taken)
        self.seconds = seconds
        #: How many of the day's six phases count as finished.
        self.done = done
        #: The day's own three chests, claimed or not.
        self.day_taken = tuple(day_taken)
        #: The day's calendar: `(stage, kind, start, end)` per phase, oldest first.
        self.phases = tuple(phases)

    @property
    def open(self) -> bool:
        return self.state == OPEN

    @property
    def automated(self) -> bool:
        """Is there a recipe for the phase running now?

        `False` while nobody knows — an unknown phase has no recipe by definition, and
        offering the press anyway would ask the game to act on a phase the panel could
        not name.
        """
        return self.kind in ARMS_AUTOMATED

    @property
    def top(self):
        """The biggest chest total of this phase, or ``None``."""
        return max(self.targets) if self.targets else None

    def __repr__(self) -> str:
        return f"<arms {self.state} kind={self.kind} score={self.score}>"


def arms_state(reading, calendar=()) -> "ArmsState":
    """The arms card against one reading. No answer is `unknown`, never `closed`."""
    if reading is None or reading.error or not reading.values:
        return ArmsState(UNKNOWN, phases=tuple(calendar))
    get = reading.get
    running = get("open")
    state = OPEN if running else (UNKNOWN if running is None else CLOSED)
    return ArmsState(
        state,
        day=get("day"), stage=get("stage"), kind=get("event"), score=get("sc"),
        targets=tuple(v for v in (get("t1"), get("t2"), get("t3")) if v is not None),
        taken=tuple(v for v in (get("g1"), get("g2"), get("g3")) if v is not None),
        seconds=get("until"), done=get("done"),
        day_taken=tuple(v for v in (get("d1"), get("d2"), get("d3")) if v is not None),
        phases=tuple(calendar))


def arms_calendar(raw) -> tuple:
    """`0:120004:1788055200:1788069600 …` → `((stage, kind, start, end), …)`.

    Anything unparseable is dropped rather than raised on: this is the client talking,
    and a client that has just been restarted says all sorts of things.
    """
    out = []
    for piece in str(raw or "").split():
        parts = piece.split(":")
        if len(parts) != 4:
            continue
        try:
            out.append(tuple(int(p) for p in parts))
        except ValueError:
            continue
    return tuple(out)


def arms_chests(state) -> str:
    """`1 / 3` — how many of the phase's three chests have been claimed."""
    if not state.targets:
        return "—"
    return "%d / %d" % (sum(1 for v in state.taken if v), len(state.targets))


def arms_day_chests(state) -> str:
    """`3 / 3` — the DAY's own ladder of boxes, as the game counts it.

    A separate reading from `arms_chests`, which is the phase's three: this one is the
    ladder that runs across the whole day and is the thing a person means by «сколько
    сундуков гонки собрано за сегодня». **It is the server's own flag on each box**
    (`day_rewards[i].receive`), never a tally the panel keeps — a count of presses would
    drift the first time a claim was refused, and the panel drawing its own bookkeeping
    beside the game's is the mistake this repository has already made once.
    """
    if not state.day_taken:
        return "—"
    return "%d / %d" % (sum(1 for v in state.day_taken if v), len(state.day_taken))


def arms_points(state) -> str:
    """`800 / 12000` — the points scored against the top chest of the phase.

    THE DIGITS ARE NOT GROUPED, and that is not a style choice. The phone marks every
    coordinate in a value as a place to go (#1982, `panel/web/coordlinks.py`), and a
    grouped `400 / 12 000` reads to that parser as «400 / 12» — a real tile — followed by
    the stray «000». A score turning into a jump link is a press that moves the camera,
    so the separator goes rather than the link.
    """
    if state.score is None:
        return "—"
    top = state.top
    if top is None:
        return str(state.score)
    return "%d / %d" % (state.score, top)


def arms_phase_clock(start: int, end: int) -> str:
    """`08:00–12:00` — one phase's window, in the reader's own local time.

    The borders are the SERVER's seconds and are shown as the clock the person reads,
    for the same reason :func:`when` is local: this answers «when do I have to be here»,
    not «which server day does this belong to».
    """
    import datetime as _dt                              # noqa: PLC0415 — one format
    try:
        a = _dt.datetime.fromtimestamp(int(start)).strftime("%H:%M")
        b = _dt.datetime.fromtimestamp(int(end)).strftime("%H:%M")
    except (TypeError, ValueError, OSError):
        return "—"
    return f"{a}–{b}"


#: «Ящик с сюрпризом» — the packet of free diamonds a surprise box sometimes drops.
#:
#: The bonus is a red packet the player may give away in the ALLIANCE chat, once, inside
#: an hour of the drop; the diamonds are the server's, so giving it away costs the account
#: nothing and an hour later it is gone whether anybody pressed anything or not.
#:
#: Nothing listens for a drop, and that is the person's own decision (#2397): «слушать
#: сейчас бесполезно, редкое событие». What looks instead is the run that OPENED a box
#: (`actions/use_item.md`, `actions/open_explorer_chests.md`) and the `lucky_share` errand
#: every half hour — both readings local, neither one a question to the server.
LUCKY = "lucky"

#: The two scenarios behind it: what is there, and give it away.
LUCKY_READ = "read_lucky_packet"
LUCKY_SHARE = "share_lucky_packet"

#: The variable the reading lands in.
LUCKY_VARIABLE = "lucky"


def lucky_fields(said: str) -> dict:
    """`have=1 live=1 min=48 alliance=1` → a dict of whole numbers.

    A field the reading did not say is absent rather than zero: «нет пакета» and «никто
    не спрашивал» are different answers, and the card draws them differently.
    """
    out: dict = {}
    for chunk in str(said or "").split():
        name, _, value = chunk.partition("=")
        try:
            out[name] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def lucky_state(said: str) -> str:
    """Which of the three states the packet is in, for the card's own pill."""
    got = lucky_fields(said)
    if not got:
        return UNKNOWN
    if int(got.get("live", 0)) > 0:
        return OPEN
    return CLOSED


def lucky_left(said: str) -> str:
    """`48` — the minutes left of the hour, or `—` when there is nothing to share.

    The number and nothing else: the unit belongs to the row's LABEL, which is a locale
    key, so «мин» is not written in Python in one language (`CLAUDE.md`).
    """
    got = lucky_fields(said)
    minutes = int(got.get("min", -1))
    if not got or minutes < 0 or int(got.get("live", 0)) <= 0:
        return "—"
    return str(minutes)


#: «Чужие пакеты в чате» — the other side of the surprise box (#2405).
#:
#: Somebody else's lucky packet is announced in chat as `post = 611`, and everybody who
#: presses in time gets a share of it. The share is free — the diamonds are the server's
#: — and the packet is emptied by whoever presses first, so the ability is an EAR rather
#: than a clock: `watch_red_packets` hooks the client's own chat ingress and presses
#: inside the call that delivered the announcement (`CLAUDE.md`, «Read once, then LISTEN»).
RED = "redpacket"

#: The three scenarios behind it: arm the ear, say what it heard, sweep by hand.
RED_WATCH = "watch_red_packets"
RED_READ = "read_red_packet_watch"
RED_COLLECT = "collect_red_packets"

#: The variable the reading lands in — and the one ARMING lands in, which is a shorter
#: sentence about the same ear.
RED_VARIABLE = "watch"
RED_ARMED = "armed"


def red_fields(said: str) -> dict:
    """`on=1 heard=3 taken=2 today=2 max=10` → a dict of whole numbers.

    The same shape as :func:`lucky_fields`, and the same rule: a field the reading did
    not say is absent rather than zero, because «караул не стоит» and «караул стоит и
    ничего не слышал» are different answers.
    """
    out: dict = {}
    for chunk in str(said or "").split():
        name, _, value = chunk.partition("=")
        try:
            out[name] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def red_state(said: str) -> str:
    """Is the ear standing? `open` when it is, `closed` when it is not, else `unknown`."""
    got = red_fields(said)
    if not got:
        return UNKNOWN
    return OPEN if int(got.get("on", 0)) > 0 else CLOSED


def red_today(said: str) -> str:
    """`2 / 10` — packets taken today against the day's ceiling, as the CLIENT counts.

    Never a tally the panel keeps: the client's own `GetRedPacketGetNum` is the one
    authority, exactly as the fireworks card uses `giftUuid2TimeTable` (#1899).
    """
    got = red_fields(said)
    today = int(got.get("today", -1))
    ceiling = int(got.get("max", -1))
    if today < 0:
        return "—"
    if ceiling <= 0:
        return str(today)
    return f"{today} / {ceiling}"


def red_caught(said: str) -> str:
    """`3 → 2` — announcements heard by the ear and presses that left it."""
    got = red_fields(said)
    if not got:
        return "—"
    return f"{int(got.get('heard', 0))} → {int(got.get('taken', 0))}"
