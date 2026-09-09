"""The «VS» tab: the duel week as six cards, one per day (#2617).

The person asked for it in these words: «Сделай отдельную вкладку VS, там будут такие
же карточки как в таймерах, первая карточка, понедельник, можно сразу 6 карточек
сделать по дням недели».

**It is not a second plan.** The week — what scores on each day, the ceilings each
action spends against, the details, the picks and the sets a day is played from — is
:mod:`panel.tabs.vs_duel`, and this tab IS that one: the same class, the same variables,
the same profile block, drawn under a name a person recognises. What it changes is the
SHAPE the phone sees it in: the week used to be six cards of bare switches, and it is
six cards of the kind «Таймеры» draws now — the picture, the name on one line, the day's
own switch in the corner and everything else behind the gear, which opens in the one
modal this front-end has (`panel/web/app/src/ui/Modal.tsx`, CLAUDE.md).

The window's half is inherited unchanged: the day grid the tab has always drawn. New
work goes into the web (CLAUDE.md, #1976), and there is no control here the window would
otherwise lose.

Nothing on this tab presses anything at the game beyond the one read it inherits —
«Записать дуэль», which is `actions/collect_vs_duel.md` and nothing else.
"""
from __future__ import annotations

import time

from ..runtime import bus
from ..runtime import game_words
from ..runtime import store
from .inventory import cell_url
from .vs_duel import DAYS, VsDuelTab, _Choice, walk_items


def _int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


#: WHAT IS ACTUALLY WIRED, and nothing else is drawn (#2617). The person's words:
#: «делаем функциональный первый день, скрой все параметры, что еще не реализованы».
#: A tick over an ability nobody has written reads as «the bot will do this on Monday»,
#: and the bot will not. So a day draws the knobs named here and no others, and a day
#: with none of them says it is still being written instead of showing dead boxes.
#:
#: The names are `<day>.<action>`, exactly as the plan spells them.
READY: frozenset = frozenset({"mon.drone_chips", "mon.drone_level",
                             "tue.survivor_tickets", "tue.build_collect",
                             "wed.drone_parts", "wed.research_collect"})

#: …and which scenario each of those knobs RUNS, for the button beside it. The panel
#: holds no opinion about what the ability is: it plays the recipe and reports what came
#: back (CLAUDE.md). A ready knob with no recipe here simply has no button.
RUNS: dict = {"mon.drone_chips": "open_drone_chips",
              "mon.drone_level": "upgrade_drone",
              "tue.survivor_tickets": "spend_survivor_tickets",
              "tue.build_collect": "open_ready_buildings",
              "wed.drone_parts": "open_drone_parts",
              "wed.research_collect": "collect_research"}

#: THE CHESTS THE CHIP ABILITY IS ABOUT (#2617) — the three grades the live bag carries,
#: as the bag reads them. They travel to both recipes as an argument, so an account with
#: a fourth grade gets it by editing this line and nothing else.
CHIP_IDS: tuple = ("540201", "540301", "540401")

#: The scenario that counts them without opening any.
CHIP_READ = "read_drone_chips"

#: WEDNESDAY'S OWN BOX, AND IT IS NOT MONDAY'S (#2662). «Сундук Компонента Дрона
#: 1/2/3 ур.» — the three grades the live bag carries — against «Сундук Чипа Навыка»
#: above. The two were confused once already (#2617), so both lists are spelled out
#: beside each other rather than derived from one another.
PART_IDS: tuple = ("630011", "630012", "630013")

#: …and the pair of recipes they travel to, the same way round as the chests: one
#: counts and opens nothing, the other opens every stack in one call.
PART_READ = "read_drone_parts"

#: THE SCIENCE CENTRES, WHAT EACH IS STUDYING, AND WHAT CLOSING ONE WOULD COST (#2662).
#: A read: it collects nothing and spends nothing.
RESEARCH_READ = "read_research_queues"

#: …AND THE ONE PRESS ON WEDNESDAY THAT SPENDS SOMETHING IRREVERSIBLY. Closing a
#: research takes speed-ups out of the bag and they do not come back, so nothing plays
#: it by itself: the row prices the parcel first, the button asks, and the recipe works
#: the parcel out again for itself at the moment of the press
#: (`actions/speedup_research.md`), exactly as the construction one does.
RESEARCH_SPEEDUP = "speedup_research"

#: TUESDAY'S TWO READS, and neither of them presses anything (#2632). The banner's
#: tickets and the buildings that have finished — a page that SHOWS them must be able to
#: ask without spending or opening anything (CLAUDE.md: the panel reads through a
#: scenario or not at all).
TICKETS_READ = "read_survivor_tickets"
BUILDS_READ = "read_ready_buildings"

#: …AND THE ONE PRESS ON THIS PAGE THAT SPENDS SOMETHING IRREVERSIBLY (#2634). Closing a
#: construction takes speed-ups out of the bag and they do not come back, so nothing
#: plays it by itself: the row prices the parcel first, the button asks, and the recipe
#: works the parcel out again for itself at the moment of the press
#: (`actions/finish_building.md`).
BUILD_FINISH = "finish_building"

#: WHAT THE GAME ITSELF SAYS WHEN THESE READINGS MOVE (#2633), and the whole reason
#: this page has no «Обновить» any more. The person's rule: «любые статистики я не
#: должен обновлять, все данные должны подтягиваться при старте клиента, а их изменение
#: проводиться по пушам».
#:
#: * `push.resource.item.update` — a bag count moved. BOTH of Tuesday's numbers and the
#:   chests are bag items (a recruit ticket is an item; so is a chest), and the client
#:   applies the push to its own `ItemInfos` table, which is what the recipes read
#:   (`docs/research/inventory.md`). So the honest re-read is the table, told by the push.
#: * `push.uav.skillchip.changes` — the drone's own chips changed, which is what OPENING
#:   a chest ends in (`docs/research/drone-upgrade.md`).
BAG_PUSH = "push.resource.item.update"
CHIP_PUSH = "push.uav.skillchip.changes"

#: …AND THE BUILD QUEUE'S OWN, WHICH #2633 SAID DID NOT EXIST (#2641). It does:
#: `push.build.queue.info` carries `updateQueues`, one entry per slot the server has
#: changed, with the slot's uuid and its new end time. It is what arrives when a
#: speed-up lands, and it is why the finished buildings can appear on this page without
#: anybody pressing anything. The client does NOT apply it to its own queue — which is
#: the bug this page had — so the re-read is worth taking only because
#: `finish_building.md` writes the server's own number back where the client dropped it.
BUILD_PUSH = "push.build.queue.info"

#: …AND THE TWO THAT SAY A SLOT APPEARED OR WENT AWAY (#2645). `push.build.queue.info`
#: is what a slot that MOVED sends — a speed-up, a new end time — and it is not what
#: arrives when a construction is STARTED or when a finished one is taken. `MsgDefines`
#: names both of those separately (`PushQueueAdd`, `PushQueueDelete`), and without them
#: the page had one door left: the alarm on the earliest slot's own end, which is armed
#: off a reading and therefore never armed at all for a queue that was empty when the
#: last reading was taken. That is the whole of «список готовых зданий не обновляется» —
#: measured on the live panel, four hours between the last reading and the page.
QUEUE_ADD_PUSH = "push.queue.add"
QUEUE_DEL_PUSH = "push.queue.del"

#: …AND THE SCIENCE CENTRES' OWN (#2662). A study that finishes and is taken changes the
#: account's technology, and the server says so — `push.science.change` is the client's
#: own name for it (`MsgDefines`, read off the live game). The queue's two above are what
#: a study STARTED or COLLECTED looks like, so all three are ears on the same list.
SCIENCE_PUSH = "push.science.change"

#: THE HOUR OF «Гонка вооружений», ON THE PAGE THAT SHOWS IT (#2635). The errand's card
#: stands on this page, so the reading behind it is taken here: the phase running now,
#: its three chests as the server flags them, and the points it has scored. It presses
#: nothing and opens nothing — `actions/read_arms_race.md` is a read.
ARMS_READ = "read_arms_race"

#: THE SCORE OF THE DUEL ITSELF (#2645), which is what the page was missing: the person's
#: words — «На вкладке выведи счет, мои очки дуэли и альянса, прогресс сделай как в игре,
#: в виде процентов». One read, no press: the player's own points, both alliances' points
#: and the days each side has won (`actions/read_vs_score.md`).
SCORE_READ = "read_vs_score"

#: …and what the game says when those numbers move: a score that changed announces
#: itself (`docs/research/arms-race.md`). So the points and the chests follow the game
#: rather than a clock, exactly like everything else on this page.
ARMS_PUSH = "push.person.arms.sc.change"

#: How long after a push before the re-read, in milliseconds. Re-armed by every push
#: that arrives inside the window, so a BURST — one harvest emits 25 of them
#: (`docs/research/base-resources.md`) — costs exactly one reading.
PUSH_DELAY_MS = 3_000

#: The tick chains this page owns: the debounce above, the build queue's own alarm, and
#: the one late look that covers a panel started over a client that was already playing.
CHAIN_PUSH = "vs_push"
CHAIN_BUILD = "vs_build_due"
#: …and the build queue's own debounce, separate from the bag's: a slot that moved says
#: nothing about the bag, and re-reading the bag on it would be a question the game did
#: not ask for.
CHAIN_BUILD_PUSH = "vs_build_push"
#: …and the retry under a reading the gate refused: the link can be down at the very
#: moment a slot moves, and the push does not come round a second time.
CHAIN_BUILD_RETRY = "vs_build_retry"
CHAIN_FIRST = "vs_first_read"
#: …and the science queues' own three: the debounce under their pushes, the alarm on the
#: earliest study's own end, and the retry under a reading the gate refused. They are
#: separate from the build queue's for the same reason its own are separate from the
#: bag's: a research that moved says nothing about a construction, and re-reading the
#: other on it would be a question the game did not ask for.
CHAIN_RESEARCH_PUSH = "vs_research_push"
CHAIN_RESEARCH = "vs_research_due"
CHAIN_RESEARCH_RETRY = "vs_research_retry"
#: …and the arms race's two: its own debounce, and the alarm on the border of the hour.
CHAIN_ARMS_PUSH = "vs_arms_push"
CHAIN_ARMS = "vs_arms_due"

#: How long after the tab exists before it checks whether the client is ALREADY in the
#: game, in milliseconds. Not a poll: it fires once and never re-arms — the wire's own
#: moment (`bus.GAME_READY`) is the mechanism, and this only covers the panel that was
#: restarted under a client that never went away.
FIRST_LOOK_MS = 20_000

#: HOW A REFUSED FIRST READING COMES BACK. The gate holds every scenario while the
#: light is not green (`panel/runtime/gate.py`), and a client that has just got into the
#: game is exactly when the light is still catching up — so the first reading can be
#: refused, and the moment it is read on does not come round again until the next login.
#: These are the net: a retry a minute, ten of them, and then it waits for a push like
#: everything else. Not a poll — it stops the moment a reading lands.
FIRST_RETRY_MS = 60_000
FIRST_TRIES = 10

#: THE SAME NET UNDER THE QUEUE'S OWN READING (#2645). A push that arrives while the
#: client is between logins is answered «нет связи с игрой» and the reading is simply
#: lost — the live panel did exactly that twice in one afternoon and then showed a list
#: four hours old. A refused read is asked again a minute later, ten times, and stops the
#: moment one lands; it is not a poll — nothing arms it but a refusal.
BUILD_RETRY_MS = 60_000
BUILD_RETRIES = 10

#: How many readings a full round is — the two kinds of chest, the tickets, the build
#: queue, the science queues, the arms race and the duel's own score. The retry stops
#: when they have all answered.
FIRST_READS = 7

#: The floor between two «read the whole page» rounds, in seconds. A profile can be told
#: it is ready more than once inside a second (the bus is not de-duplicated), and three
#: scenarios per telling is three round trips of an exclusive link for the same numbers.
READ_ALL_GAP_SEC = 20.0

#: The longest a single build alarm may sleep, in seconds. A construction can be a day
#: long and a `after()` that far out is a promise nobody should make, so the wait is
#: served in hour-long legs — and a leg that arrives early re-arms WITHOUT reading
#: anything, so the game is asked once, at the moment the slot is actually due.
BUILD_LEG_SEC = 3_600.0

#: The same for the arms race's own alarm. A phase is four hours long and its end is a
#: number the server already handed over (`until`), so the hour is not watched for — it
#: is slept until, in legs, and the reading is taken once when it turns over.
ARMS_LEG_SEC = 3_600.0

#: WHAT THE PRESS INSIDE THE SHEET CALLS ITSELF (#2624). The switch above it already
#: says what the ability IS — «Открыть чипы дрона» — so the button says what pressing it
#: does now, and the two do not read as one control written twice.
RUN_LABELS: dict = {"mon.drone_chips": "vs.chips.open_all",
                    "mon.drone_level": "vs.drone.raise_now",
                    "tue.survivor_tickets": "vs.tickets.spend_now",
                    "tue.build_collect": "vs.builds.open_all",
              "wed.drone_parts": "vs.parts.open_all",
              "wed.research_collect": "vs.research.collect_all"}


class VsTab(VsDuelTab):
    """The duel plan, drawn as a card per day of the week."""

    ID = "vs"
    TITLE_KEY = "tab.vs"
    ORDER = 330
    #: It replaces the tab it inherits from, which never left development mode, so it
    #: arrives switched ON like every new ability (CLAUDE.md, #2390). Nothing here
    #: spends anything: the plan is a set of choices, and the one press is a read.
    IN_DEVELOPMENT = False
    DEFAULT_ENABLED = True
    #: Its own key for the title, and the week's words are the ones it inherits.
    LOCALE_NS = ("vsduel", "vs")

    def __init__(self, rt, parent) -> None:
        """…and the week is LOADED here, which is not a nicety on this front-end.

        A block is applied by `restore`, and the panel that actually runs — the headless
        one behind the web (`panel/headless.py`) — calls it only for a block that is not
        empty. A profile that has never saved this tab therefore never had `apply_config`
        called at all, and the variables kept what `__init__` gave them: the day switch
        on and every action off. The window hides that by loading the week when it draws
        it; the phone has no drawing, so it read «0 / 4» over a plan the panel would have
        played in full. So the sets are put into the variables the moment the tab exists.

        The old block is where it looks first. «Дуэль VS» never left development mode, so
        most profiles have none — but one that DOES had a week typed into it, and a
        rename of the page is not a reason to hand somebody an empty one. From this tab's
        first save on, `restore` brings its own block and this seeding is overwritten.
        """
        super().__init__(rt, parent)
        #: What the store says about the chip chests — read on first need, never on a
        #: clock (CLAUDE.md, «Read once, then LISTEN»). `None` until it has been asked.
        self._chips = None
        #: …and the same for Tuesday's two: the survivors' banner and the buildings that
        #: have finished. `None` until either has been asked for the first time.
        self._tickets = None
        self._builds = None
        #: …and the duel's own score (#2645). `None` until it has been asked for once.
        self._score = None
        #: WEDNESDAY'S TWO (#2662): the component chests and the science centres. Read
        #: on first need like everything else on this page, `None` until asked.
        self._parts = None
        self._research = None
        #: …and the science queues' own alarm and net, the twins of the build queue's:
        #: a study announces its own end in the reading, and a refused reading is asked
        #: again rather than lost.
        self._research_due: "float | None" = None
        self._research_tries = 0
        #: THE EAR AND ITS ALARM (#2633). Nothing here reads on a clock: the first
        #: reading is taken when the client gets into the game (`bus.GAME_READY`), and
        #: after that the wire says when a number moved. `_build_due` is the one
        #: exception the person decided on — the build queue announces nothing, so its
        #: own `endTime` is the alarm, which is a known moment and not a question.
        self._wire_off: list = []
        self._build_due: "float | None" = None
        #: How many times a refused queue reading has been asked again, reset by the
        #: answer that lands (#2645).
        self._build_tries = 0
        #: …and the border of the arms race's own hour, which is the other moment with
        #: no push behind it: the phase's end is in the reading itself.
        self._arms_due: "float | None" = None
        #: The first reading's own bookkeeping: when the last full round was played,
        #: how many have been tried, and which of the three have actually answered.
        self._read_all_at = 0.0
        self._tries = 0
        self._first_ok: set = set()
        try:
            self._ready_off = self.rt.bus.subscribe(bus.GAME_READY, self._on_game_ready)
        except Exception:                # noqa: BLE001 — a board, never the panel
            self._ready_off = None
        try:
            self.rt.tick.arm(CHAIN_FIRST, FIRST_LOOK_MS, self._first_look)
        except Exception:                # noqa: BLE001 — no clock only means the ready
            pass                         #   fact is the only door, which is the normal one
        try:
            old = self.rt.settings.tab_config("vs_duel")
        except Exception:                # noqa: BLE001 — a profile, never the panel
            old = {}
        self.apply_config(old if isinstance(old, dict) else {})

    # -- the chests, counted -----------------------------------------------------
    #
    # WHAT IS KEPT AND WHY. The bag can always be re-read from the game; the number of
    # chests this account has OPENED cannot — an open chest is gone, and nothing in the
    # client remembers it. So the tally is the panel's own fact and lives in the database
    # with every other one (CLAUDE.md, `store.DRONE_CHIPS`), while the bag half is a
    # reading with its age beside it: read on a press, never on a clock.

    def _word(self, text) -> str:
        """A name the GAME wrote, in the language the PANEL is in (#2645).

        The client resolves a building's or an item's name in ITS own language, so a
        panel switched to another one used to draw them in the client's — the person's
        report was «вещи не переведены на языки». The game's own tables answer it
        (`panel/runtime/game_words.py`), never a translation of ours, and a name they
        cannot place comes back exactly as the game said it.
        """
        try:
            return game_words.say(text, self.rt.i18n.lang,
                                  scope=str(self.rt.profiles.active or ""))
        except Exception:                    # noqa: BLE001 — a word, never the page
            return "" if text is None else str(text)

    def _ago(self, stamp: int) -> str:
        """«3 мин» — how old a reading is, in the coarsest unit that still says something.

        Every unit is a locale key: a reading whose age reads «3 min» in a Russian panel
        is a word written in the code (CLAUDE.md).
        """
        gap = max(0, int(time.time()) - int(stamp))
        if gap < 60:
            return self.t("vs.age.sec", n=gap)
        if gap < 3600:
            return self.t("vs.age.min", n=gap // 60)
        if gap < 86400:
            return self.t("vs.age.hour", n=gap // 3600)
        return self.t("vs.age.day", n=gap // 86400)

    def _chips_state(self) -> dict:
        """What the store holds about the chests: the tally, the last reading, its age."""
        if self._chips is None:
            state = None
            try:
                state = self.rt.store.blob_get(store.DRONE_CHIPS)
            except Exception:                # noqa: BLE001 — a reading, never the tab
                state = None
            self._chips = state if isinstance(state, dict) else {}
        return self._chips

    def _chips_save(self, state: dict) -> None:
        self._chips = state
        try:
            self.rt.store.blob_set(store.DRONE_CHIPS, state)
        except Exception:                    # noqa: BLE001 — a checkpoint, never the tab
            pass

    def _chips_rows_back(self, outcome) -> None:
        """`read_drone_chips` came back — keep what it said, in the store.

        The row is the GAME's: the count, the rarity, the icon file and the name in the
        client's own language. Nothing here translates any of it (docs/panel-tabs.md).
        """
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        raw = str(variables.get("chips_rows") or "")
        rows = []
        for piece in raw.split(";;"):
            parts = [bit.strip() for bit in piece.split("|")]
            if len(parts) < 5 or not parts[0].isdigit():
                continue
            rows.append({"id": parts[0], "count": _int(parts[1]),
                         "colour": _int(parts[2]), "icon": parts[3],
                         "name": parts[4]})
        if not rows:
            return
        state = dict(self._chips_state())
        state["rows"] = rows
        state["at"] = int(time.time())
        self._chips_save(state)
        self._first_ok.add("chips")

    def _chips_opened_back(self, outcome) -> None:
        """`open_drone_chips` came back — add what it opened to the tally, by grade.

        `chips_per_id` is the recipe's own line («540201:31,540401:3») and never a guess
        of ours: a run that opened nothing adds nothing, and a run the server refused
        never gets here.
        """
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        raw = str(variables.get("chips_per_id") or "")
        state = dict(self._chips_state())
        opened = dict(state.get("opened") or {})
        moved = False
        for piece in raw.split(","):
            item, _, count = piece.partition(":")
            item, count = item.strip(), _int(count)
            if not item.isdigit() or count <= 0:
                continue
            opened[item] = _int(opened.get(item)) + count
            moved = True
        if not moved:
            return
        state["opened"] = opened
        # …and the bag has just changed, so what is drawn beside the tally is stale.
        # It is not re-read here: the next press asks, and until then the age says so.
        state["spent_at"] = int(time.time())
        self._chips_save(state)

    def _chips_rows(self) -> list:
        """One row per grade: the game's own picture, its name, what is held and opened.

        The drawing itself is `_chest_rows`, shared with Wednesday's component chests
        (#2662) — two different boxes, one shape of reading.
        """
        return self._chest_rows(self._chips_state(), CHIP_IDS)

    def _chips_note(self) -> str:
        """How old the count is — data, said in this profile's own language."""
        when = _int(self._chips_state().get("at"))
        if not when:
            return self.t("vs.chips.never")
        return self.t("vs.chips.read_at", ago=self._ago(when))

    # -- Wednesday: the drone's component chests --------------------------------
    #
    # THE SAME SPLIT AS MONDAY'S CHIPS, and deliberately not the same store: «Сундук
    # Компонента Дрона» and «Сундук Чипа Навыка» are two item families, they are opened
    # on two different days, and a tally that mixed them would answer neither question.
    # What the bag holds is re-readable from the game; how many this account has OPENED
    # is not, because an open chest is gone.

    def _parts_state(self) -> dict:
        """What the store holds about the component chests: the tally and its age."""
        if self._parts is None:
            try:
                state = self.rt.store.blob_get(store.DRONE_PARTS)
            except Exception:                # noqa: BLE001 — a reading, never the tab
                state = None
            self._parts = state if isinstance(state, dict) else {}
        return self._parts

    def _parts_save(self, state: dict) -> None:
        self._parts = state
        try:
            self.rt.store.blob_set(store.DRONE_PARTS, state)
        except Exception:                    # noqa: BLE001 — a checkpoint, never the tab
            pass

    def _parts_rows_back(self, outcome) -> None:
        """`read_drone_parts` came back — keep what it said, in the store."""
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        rows = self._grades(str(variables.get("parts_rows") or ""))
        if not rows:
            return
        state = dict(self._parts_state())
        state["rows"] = rows
        state["at"] = int(time.time())
        self._parts_save(state)
        self._first_ok.add("parts")

    def _parts_opened_back(self, outcome) -> None:
        """`open_drone_parts` came back — add what it opened to the tally, by grade."""
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        state = dict(self._parts_state())
        opened = self._tally(state.get("opened"), str(variables.get("parts_per_id") or ""))
        if opened is None:
            return
        state["opened"] = opened
        state["spent_at"] = int(time.time())
        self._parts_save(state)

    @staticmethod
    def _grades(raw: str) -> list:
        """`id|count|colour|icon|name` -> the rows of one kind of chest, as the game said.

        Shared by both days on purpose: the chip chests and the component chests are
        different boxes, but a grade is a grade and the reading has one shape.
        """
        rows = []
        for piece in raw.split(";;"):
            parts = [bit.strip() for bit in piece.split("|")]
            if len(parts) < 5 or not parts[0].isdigit():
                continue
            rows.append({"id": parts[0], "count": _int(parts[1]),
                         "colour": _int(parts[2]), "icon": parts[3],
                         "name": parts[4]})
        return rows

    @staticmethod
    def _tally(held, raw: str):
        """«630011:31,630013:3» added to what was counted before, or `None` for nothing.

        A run that opened nothing adds nothing, and a run the server refused never gets
        here — so `None` means «do not write anything down», not «zero».
        """
        opened = dict(held or {})
        moved = False
        for piece in raw.split(","):
            item, _, count = piece.partition(":")
            item, count = item.strip(), _int(count)
            if not item.isdigit() or count <= 0:
                continue
            opened[item] = _int(opened.get(item)) + count
            moved = True
        return opened if moved else None

    def _parts_rows(self) -> list:
        """One row per grade of component chest: picture, name, what is held and opened."""
        return self._chest_rows(self._parts_state(), PART_IDS)

    def _chest_rows(self, state: dict, ids: tuple) -> list:
        """The rows of a chest reading, whichever day's it is.

        A grade the game has no picture for on this machine is drawn WITHOUT one, never
        with somebody else's (`panel/tabs/inventory.py::cell_url`, the same rule every
        picture route here keeps).
        """
        rows = state.get("rows") if isinstance(state.get("rows"), list) else []
        opened = state.get("opened") or {}
        out = []
        for row in rows or [{"id": item, "count": None, "colour": 0, "icon": "",
                             "name": ""} for item in ids]:
            item_id = str(row.get("id") or "")
            picture = cell_url(str(row.get("icon") or ""), row.get("colour"))
            count = row.get("count")
            entry = {"text": self._word(row.get("name")) or item_id,
                     "facts": [{"label": "vs.chips.in_bag",
                                "value": "\u2014" if count is None else str(count)},
                               {"label": "vs.chips.opened",
                                "value": str(_int(opened.get(item_id)))}]}
            if picture:
                entry["icon"] = picture
            out.append(entry)
        return out

    def _parts_note(self) -> str:
        """How old the count is — data, said in this profile's own language."""
        when = _int(self._parts_state().get("at"))
        if not when:
            return self.t("vs.parts.never")
        return self.t("vs.parts.read_at", ago=self._ago(when))

    # -- Wednesday: the science centres ----------------------------------------
    #
    # A LIST THAT IS RE-READ AND NEVER GUESSED, exactly like the build queue. The panel
    # keeps what the last reading said with its age beside it; whether a study may be
    # collected, and what closing one costs, are the recipes' own business.

    def _research_state(self) -> dict:
        if self._research is None:
            try:
                state = self.rt.store.blob_get(store.RESEARCH_QUEUES)
            except Exception:                # noqa: BLE001 — a reading, never the tab
                state = None
            self._research = state if isinstance(state, dict) else {}
        return self._research

    def _research_save(self, state: dict) -> None:
        self._research = state
        try:
            self.rt.store.blob_set(store.RESEARCH_QUEUES, state)
        except Exception:                    # noqa: BLE001 — a checkpoint, never the tab
            pass

    def _research_back(self, outcome) -> None:
        """`read_research_queues` came back — keep the centres, idle ones included.

        An EMPTY answer is kept too, for the same reason the build queue's is: «nothing
        is studying» is a state, and a page holding the last non-empty list would offer
        to collect a research that has already been taken. A run that did not HAPPEN is
        a different thing again and is not written down at all.
        """
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        if "research_rows" not in variables:
            return
        state = dict(self._research_state())
        state["rows"] = self._parse_research(str(variables.get("research_rows") or ""))
        state["at"] = int(time.time())
        self._research_save(state)
        self._first_ok.add("research")
        self._research_tries = 0
        try:
            self.rt.tick.disarm(CHAIN_RESEARCH_RETRY)
        except Exception:                    # noqa: BLE001
            pass
        self._arm_research_alarm(_int(variables.get("next_research_sec"), -1))

    @staticmethod
    def _parse_research(raw: str) -> list:
        """`uuid|id|lv|icon|name|left|state|covered|plan` -> one row per science centre.

        `state` is the GAME's: 1 a study that has finished and is waiting, 0 one that is
        running, 2 a centre standing idle. A line the recipe did not print in that shape
        is dropped rather than guessed at — a half-read parcel priced on a screen is an
        irreversible spend nobody agreed to.
        """
        rows = []
        for piece in raw.split(";;"):
            parts = [bit.strip() for bit in piece.split("|")]
            if len(parts) < 7 or not parts[0].isdigit():
                continue
            plan = []
            for bit in (parts[8] if len(parts) > 8 else "").split("+"):
                cut = bit.split(":")
                if len(cut) < 4 or not cut[0].strip().isdigit():
                    continue
                plan.append({"id": cut[0].strip(), "num": _int(cut[1]),
                             "sec": _int(cut[2]), "own": _int(cut[3])})
            rows.append({"uuid": parts[0], "id": parts[1], "level": _int(parts[2]),
                         "icon": parts[3], "name": parts[4], "left": _int(parts[5]),
                         "state": _int(parts[6]),
                         "covered": _int(parts[7] if len(parts) > 7 else 0) == 1,
                         "plan": plan})
        return rows

    def _research_rows(self) -> list:
        """One row per science centre — what it studies, how long it has left, its press.

        The order is the one a person reads it in: what is READY first (there is
        something to do about it), then what is running, earliest first, then the centres
        standing idle.
        """
        rows = self._research_state().get("rows")
        rows = rows if isinstance(rows, list) else []
        order = {1: 0, 0: 1, 2: 2}
        out = []
        for row in sorted(rows, key=lambda r: (order.get(_int(r.get("state")), 3),
                                               _int(r.get("left")))):
            out.append(self._research_row(row))
        return out

    def _research_row(self, row: dict) -> dict:
        """One centre, as the phone draws it."""
        uuid = str(row.get("uuid") or "")
        state = _int(row.get("state"))
        name = self._word(row.get("name")) or str(row.get("id") or "")
        entry = {"text": name if state != 2 else self.t("vs.research.idle"),
                 # THE PICTURE IS HALF THE CARD, the way the finished buildings are
                 # drawn (#2645): a technology is recognised by its own art first.
                 "shape": "picture",
                 "facts": [{"label": "vs.research.level",
                            "value": str(_int(row.get("level")))}],
                 "actions": []}
        picture = self._research_icon(str(row.get("icon") or ""))
        if picture:
            entry["icon"] = picture
        if state == 1:
            entry["facts"].append({"label": "vs.research.left",
                                   "value": self.t("vs.research.ready")})
            entry["actions"].append({"id": "collect_one", "args": {"uuid": uuid},
                                     "label": "vs.research.collect"})
        elif state == 0:
            entry["facts"].append({"label": "vs.research.left",
                                   "value": self._span(_int(row.get("left")))})
            entry["facts"].append({"label": "vs.research.cost", "value": self._cost(row)})
            entry["actions"].append({"id": "speed_one", "args": {"uuid": uuid},
                                     "label": "vs.research.speedup",
                                     # IT ASKS FIRST, because the speed-ups do not come
                                     # back — the same guard the construction press has.
                                     "confirm": "vs.research.speedup.confirm",
                                     # …and a bag that cannot close it offers a dead
                                     # button rather than a spend that buys nothing.
                                     "disabled": not row.get("covered")})
        else:
            entry["facts"].append({"label": "vs.research.left",
                                   "value": self.t("vs.research.nothing")})
        return entry

    @staticmethod
    def _research_icon(stem: str) -> "str | None":
        """A technology's own sprite as the phone asks for it, or nothing at all.

        A LINK and never bytes, and never somebody else's picture: the sprite is looked
        up by NAME in the extracted art (`item_icons.raw_named`, the route the resources
        already use), and a technology this machine has no picture for is drawn without
        one rather than with a stand-in.
        """
        import urllib.parse as _url

        stem = (stem or "").strip()
        if not stem:
            return None
        try:
            import item_icons                # noqa: PLC0415 — one lookup
        except Exception:                    # noqa: BLE001 — no extraction is no picture
            return None
        name = stem if stem.lower().endswith(".png") else stem + ".png"
        if not item_icons.raw_named(name):
            return None
        return "/api/itemicon?name=" + _url.quote(name)

    def _research_ready(self) -> int:
        """How many centres are waiting to be collected — what «Собрать все» is about."""
        rows = self._research_state().get("rows")
        rows = rows if isinstance(rows, list) else []
        return sum(1 for row in rows if _int(row.get("state")) == 1)

    def _research_note(self) -> str:
        when = _int(self._research_state().get("at"))
        if not when:
            return self.t("vs.research.never")
        return self.t("vs.research.read_at", ago=self._ago(when))

    # -- Tuesday: the survivors' tickets ---------------------------------------
    #
    # THE SAME SPLIT AS THE CHESTS. What the banner holds can be re-read from the game at
    # any moment and carries the age of its reading; how many tickets went TODAY cannot —
    # a ticket that is spent is gone, and the count of them exists nowhere but here. So
    # the tally is the panel's own fact, kept in the database with every other one, and
    # it is keyed by the GAME's day (`rt.day.day_key`) rather than this machine's: with
    # the reset at the warzone's own midnight the two disagree for two hours out of
    # twenty-four, and «потрачено сегодня» read on the wrong side of that is a lie.

    def _tickets_state(self) -> dict:
        """What the store holds about the banner: the count, the tally, the age."""
        if self._tickets is None:
            try:
                state = self.rt.store.blob_get(store.SURVIVOR_TICKETS)
            except Exception:                # noqa: BLE001 — a reading, never the tab
                state = None
            self._tickets = state if isinstance(state, dict) else {}
        return self._tickets

    def _tickets_save(self, state: dict) -> None:
        self._tickets = state
        try:
            self.rt.store.blob_set(store.SURVIVOR_TICKETS, state)
        except Exception:                    # noqa: BLE001 — a checkpoint, never the tab
            pass

    def _today(self) -> str:
        """The GAME day, so a tally resets when the warzone does and not at midnight."""
        try:
            return self.rt.day.day_key()
        except Exception:                    # noqa: BLE001 — a half-built runtime
            return ""

    def _tickets_back(self, outcome) -> None:
        """`read_survivor_tickets` came back — keep what the banner said."""
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        have = _int(variables.get("worker_tickets"), -1)
        if have < 0:
            return                           # «nobody knows» is never drawn as a zero
        state = dict(self._tickets_state())
        state["have"] = have
        state["free"] = 1 if _int(variables.get("worker_free")) else 0
        state["at"] = int(time.time())
        self._tickets_save(state)
        self._first_ok.add("tickets")

    def _tickets_spent_back(self, outcome) -> None:
        """`spend_survivor_tickets` came back — add what it spent to today's tally.

        `tickets_spent` is the recipe's own line and never a guess of ours: a run that
        spent nothing adds nothing, and a run the client refused never gets here.
        """
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        spent = _int(variables.get("tickets_spent"))
        state = dict(self._tickets_state())
        day = self._today()
        if state.get("day") != day:
            state["day"], state["spent"] = day, 0
        if spent > 0:
            state["spent"] = _int(state.get("spent")) + spent
        after = _int(variables.get("tickets_after"), -1)
        if after >= 0:
            state["have"] = after
            state["at"] = int(time.time())
        self._tickets_save(state)

    def _tickets_facts(self) -> list:
        """«Билетов N · Потрачено сегодня M» — the two numbers the person asked for."""
        state = self._tickets_state()
        have = state.get("have")
        spent = _int(state.get("spent")) if state.get("day") == self._today() else 0
        return [{"label": "vs.tickets.have",
                 "value": "\u2014" if have is None else str(_int(have))},
                {"label": "vs.tickets.spent_today", "value": str(spent)}]

    def _tickets_note(self) -> str:
        """How old the count is — data, said in this profile's own language."""
        when = _int(self._tickets_state().get("at"))
        if not when:
            return self.t("vs.tickets.never")
        return self.t("vs.tickets.read_at", ago=self._ago(when))

    # -- Tuesday: the buildings that have finished ------------------------------
    #
    # A LIST THAT IS RE-READ AND NEVER GUESSED. A finished building is a slot of the
    # game's own build queue, so the panel keeps only what the last reading said, with
    # its age beside it, and «Открыть» plays the recipe that reads the queue again for
    # itself. The panel holds no gate: whether it is the arms race's building hour lives
    # in `actions/open_ready_buildings.md`, which is the only thing that opens anything.

    def _builds_state(self) -> dict:
        if self._builds is None:
            try:
                state = self.rt.store.blob_get(store.READY_BUILDINGS)
            except Exception:                # noqa: BLE001 — a reading, never the tab
                state = None
            self._builds = state if isinstance(state, dict) else {}
        return self._builds

    def _builds_save(self, state: dict) -> None:
        self._builds = state
        try:
            self.rt.store.blob_set(store.READY_BUILDINGS, state)
        except Exception:                    # noqa: BLE001 — a checkpoint, never the tab
            pass

    def _builds_back(self, outcome) -> None:
        """`read_ready_buildings` came back — keep the list, empty or not.

        An EMPTY answer is kept too, which is the difference from the chests: «nothing is
        waiting» is the state the «Открыть все» button goes dead on, and a page that held
        the last non-empty list would offer to open buildings that are already open.
        """
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        if "ready_builds" not in variables:
            # A RUN THAT DID NOT HAPPEN IS NOT AN EMPTY QUEUE (#2633). The gate refuses
            # a scenario while the light is not green and the recipe then leaves nothing
            # behind — and «nothing waiting», stamped with the time, is exactly what a
            # person would read as a fresh answer.
            return
        raw = str(variables.get("ready_builds") or "")
        rows = []
        for piece in raw.split(";;"):
            parts = [bit.strip() for bit in piece.split("|")]
            if len(parts) < 5 or not parts[0].isdigit():
                continue
            rows.append({"uuid": parts[0], "id": parts[1], "level": _int(parts[2]),
                         "icon": parts[3], "name": parts[4]})
        state = dict(self._builds_state())
        state["rows"] = rows
        # …AND WHAT IS STILL BUILDING, out of the same reading (#2634): the same five
        # fields, how long the slot still has to run, whether the bag can close it and
        # the parcel that would. The plan is the GAME's arithmetic, not the panel's —
        # nothing here decides which speed-up is spent.
        state["building"] = self._parse_building(str(variables.get("building_builds")
                                                     or ""))
        state["at"] = int(time.time())
        self._builds_save(state)
        self._first_ok.add("builds")
        # The reading landed, so the net under it comes down (#2645).
        self._build_tries = 0
        try:
            self.rt.tick.disarm(CHAIN_BUILD_RETRY)
        except Exception:                    # noqa: BLE001
            pass
        # …AND THE NEXT ALARM, out of the same answer. The recipe says how long the
        # earliest slot still has to run, so the panel knows the exact second the list
        # will be wrong and asks then — never in between (#2633).
        self._arm_build_alarm(_int(variables.get("next_ready_sec"), -1))

    @staticmethod
    def _parse_building(raw: str) -> list:
        """`uuid|id|lv|icon|name|left|covered|plan` -> the rows of running constructions.

        A line the recipe did not print in that shape is dropped rather than guessed at:
        a half-read parcel priced on a screen is an irreversible spend nobody agreed to.
        """
        rows = []
        for piece in raw.split(";;"):
            parts = [bit.strip() for bit in piece.split("|")]
            if len(parts) < 7 or not parts[0].isdigit():
                continue
            plan = []
            for bit in (parts[7] if len(parts) > 7 else "").split("+"):
                cut = bit.split(":")
                if len(cut) < 4 or not cut[0].strip().isdigit():
                    continue
                plan.append({"id": cut[0].strip(), "num": _int(cut[1]),
                             "sec": _int(cut[2]), "own": _int(cut[3])})
            rows.append({"uuid": parts[0], "id": parts[1], "level": _int(parts[2]),
                         "icon": parts[3], "name": parts[4], "left": _int(parts[5]),
                         "covered": _int(parts[6]) == 1, "plan": plan})
        return rows

    def _span(self, seconds: int) -> str:
        """«4 ч» — a stretch of time in the coarsest unit that still says something.

        The same words the age of a reading is said in, and every one of them a key.
        """
        gap = max(0, int(seconds))
        if gap < 60:
            return self.t("vs.age.sec", n=gap)
        if gap < 3600:
            return self.t("vs.age.min", n=gap // 60)
        if gap < 86400:
            return self.t("vs.age.hour", n=gap // 3600)
        return self.t("vs.age.day", n=gap // 86400)

    def _cost(self, row: dict) -> str:
        """«16×5 мин + 1×15 мин» — what closing this construction would take out of the bag.

        The person's rule for an irreversible spend: it is NAMED before it is made
        (CLAUDE.md). A bag that cannot close the build says so instead of pricing a
        parcel that would be spent for nothing.
        """
        pieces = [self.t("vs.builds.piece", n=_int(item.get("num")),
                         min=max(1, _int(item.get("sec")) // 60))
                  for item in (row.get("plan") or []) if _int(item.get("num")) > 0]
        if not row.get("covered") or not pieces:
            return self.t("vs.builds.short")
        return " + ".join(pieces)

    def _building_rows(self) -> list:
        """One row per construction that is still running — its price, and its press.

        The earliest first, which is the order the recipe priced them in: two
        constructions over one bag are priced against what the first would leave, so the
        second's parcel is honest rather than counted twice.
        """
        state = self._builds_state()
        rows = state.get("building") if isinstance(state.get("building"), list) else []
        out = []
        for row in rows or []:
            uuid = str(row.get("uuid") or "")
            entry = {"text": self._word(row.get("name"))
                             or str(row.get("id") or ""),
                     "shape": "picture",
                     "facts": [{"label": "vs.builds.level",
                                "value": str(_int(row.get("level")))},
                               {"label": "vs.builds.left",
                                "value": self._span(_int(row.get("left")))},
                               {"label": "vs.builds.cost", "value": self._cost(row)}],
                     "actions": [{"id": "finish_one", "args": {"uuid": uuid},
                                  "label": "vs.builds.finish",
                                  # IT ASKS FIRST, because the speed-ups do not come
                                  # back — the same guard a rally join carries.
                                  "confirm": "vs.builds.finish.confirm",
                                  # …and a bag that cannot close it offers a dead
                                  # button rather than a spend that buys nothing.
                                  "disabled": not row.get("covered")}]}
            picture = self._build_icon(str(row.get("icon") or ""))
            if picture:
                entry["icon"] = picture
            out.append(entry)
        return out

    @staticmethod
    def _build_icon(stem: str) -> "str | None":
        """One building's own sprite as the phone asks for it, or nothing at all.

        A LINK and never bytes, exactly as `cell_url` is one. A building the game named a
        picture for that this machine has not extracted draws WITHOUT one, never with
        somebody else's (the rule every picture route here keeps).
        """
        import urllib.parse as _url

        try:
            import building_icons
        except Exception:                    # noqa: BLE001 — no extraction is no picture
            return None
        name = building_icons.name_for(stem)
        if not name:
            return None
        return "/api/buildingicon?icon=" + _url.quote(name)

    def _builds_rows(self) -> list:
        """One row per finished building — the game's picture, its level, its own press.

        Sorted by level, highest first (the person's words: «сортировка по уровню»), and
        the name is the GAME's, in whatever language the client is in.
        """
        state = self._builds_state()
        rows = state.get("rows") if isinstance(state.get("rows"), list) else []
        out = []
        for row in sorted(rows or [], key=lambda r: -_int(r.get("level"))):
            uuid = str(row.get("uuid") or "")
            entry = {"text": self._word(row.get("name"))
                             or str(row.get("id") or ""),
                     # THE PICTURE IS HALF THE CARD (#2645) — the person's words:
                     # «Рисунки зданий увеличь, в половину карточки». A building is
                     # recognised by its own art before its name is read.
                     "shape": "picture",
                     "facts": [{"label": "vs.builds.level",
                                "value": str(_int(row.get("level")))}],
                     "actions": [{"id": "open_one", "args": {"uuid": uuid},
                                  "label": "vs.builds.open"}]}
            picture = self._build_icon(str(row.get("icon") or ""))
            if picture:
                entry["icon"] = picture
            out.append(entry)
        return out

    def _builds_note(self) -> str:
        when = _int(self._builds_state().get("at"))
        if not when:
            return self.t("vs.builds.never")
        return self.t("vs.builds.read_at", ago=self._ago(when))

    #: The arms race phase that pays for «Строительство Города», and the only hour in
    #: which `open_ready_buildings.md` will hand a finished building over.
    BUILD_HOUR_KIND = 120001

    def _builds_gate(self) -> str:
        """Why «Открыть» may do nothing right now — said as a state, not as a failure.

        A finished building keeps until somebody takes it, and taking it pays building
        points that only one hour of the arms race is paying for — so the recipe refuses
        the claim in any other hour (`actions/open_ready_buildings.md`, the person's
        words: «открываем только в час стройки гонки вооружений»). A row that quietly
        does nothing reads as a broken button, so the page says which of the two it is
        (#2641). The gate itself stays where it belongs: nothing here decides anything.
        """
        from ..runtime import arms_live               # noqa: PLC0415 — one reading

        try:
            state, age = arms_live.state(self.rt)
        except Exception:                    # noqa: BLE001 — a reading, never the page
            return ""
        if age is None or state.kind is None:
            return self.t("vs.builds.gate.unknown")
        if _int(state.kind) == self.BUILD_HOUR_KIND:
            return self.t("vs.builds.gate.now")
        return self.t("vs.builds.gate.wait")

    # -- the duel's own score --------------------------------------------------
    #
    # THE ONE READING THIS PAGE IS NAMED AFTER (#2645), and the last one it did not have:
    # the player's own points, both alliances' points, and how the two sides stand — the
    # bar the game itself draws, said in the percentages the person asked for.
    #
    # THERE IS NO PUSH BEHIND IT that we have seen. So it follows the rule the same way
    # everything else here does: read once when the client gets into the game, kept with
    # its AGE beside it, and re-read as the direct consequence of a press somebody made
    # («Записать дуэль» is the read of the week). Nothing asks the game on a clock, and a
    # reading that has stopped moving is visibly old rather than quietly wrong.

    def _score_state(self) -> dict:
        if self._score is None:
            try:
                state = self.rt.store.blob_get(store.VS_SCORE)
            except Exception:                # noqa: BLE001 — a reading, never the tab
                state = None
            self._score = state if isinstance(state, dict) else {}
        return self._score

    def _read_score(self) -> None:
        """Ask what the duel stands at. The one door to that reading."""
        self.rt.play_async(SCORE_READ, tag="vs", on_result=self._score_back)

    def _score_back(self, outcome) -> None:
        """`read_vs_score` came back — keep what it said, in the store.

        A run the gate refused leaves nothing behind, and a blank stamped with the time
        would age-stamp «неизвестно» as a fresh answer (#2633).
        """
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        raw = str(variables.get("vs_score") or "").strip()
        if not raw:
            return
        state = {"at": int(time.time())}
        for piece in raw.split(" "):
            key, _, value = piece.partition("=")
            if key:
                state[key] = value
        self._score = state
        try:
            self.rt.store.blob_set(store.VS_SCORE, state)
        except Exception:                    # noqa: BLE001 — a checkpoint, never the tab
            pass
        self._first_ok.add("score")

    @staticmethod
    def _side(raw) -> dict:
        """`AL1|1000000|1` -> the side, or an empty one when the game named nobody."""
        parts = [bit.strip() for bit in str(raw or "").split("|")]
        if len(parts) < 3:
            return {}
        return {"abbr": parts[0], "score": _int(parts[1]), "win": _int(parts[2])}

    @staticmethod
    def _share(ours: int, theirs: int) -> int:
        """Our half of the duel, in whole percent — the game's own bar, as a number."""
        total = max(0, ours) + max(0, theirs)
        if total <= 0:
            return 0
        return int(round(100.0 * max(0, ours) / total))

    def _score_card(self) -> dict:
        """«Счёт»: my points, both alliances' points, and the two shares in percent.

        WHAT IS UNKNOWN IS NOT DRAWN AS A ZERO. A side the game has not named is left out
        rather than shown at nought, which would read as «мы проигрываем всухую».
        """
        state = self._score_state()
        rows = []
        mine = _int(state.get("mine"), -1)
        rows.append({"label": "vs.score.mine",
                     "value": "\u2014" if mine < 0 else f"{mine:,}".replace(",", "\u2009")})
        # …AND HOW FAR ALONG THE PERSONAL LADDER THAT IS (#2645). The milestones are the
        # game's own list; the percentage is against the LAST of them, which is what the
        # bar in the game fills up to.
        targets = [_int(bit) for bit in str(state.get("target") or "").split(",")
                   if bit.strip().isdigit()]
        if mine >= 0 and targets:
            top = max(targets)
            done = min(100, int(round(100.0 * mine / top))) if top > 0 else 0
            rows.append({"label": "vs.score.mine.progress",
                         "value": self.t("vs.score.percent", n=done)})
        us, them = self._side(state.get("us")), self._side(state.get("them"))
        if us:
            share = self._share(us["score"], them.get("score", 0)) if them else 100
            rows.append({"label": "vs.score.us",
                         "value": self.t("vs.score.side", who=us["abbr"],
                                         score=f"{us['score']:,}".replace(",", "\u2009"),
                                         n=share)})
        if them:
            share = 100 - self._share(us.get("score", 0), them["score"]) if us else 100
            rows.append({"label": "vs.score.them",
                         "value": self.t("vs.score.side", who=them["abbr"],
                                         score=f"{them['score']:,}".replace(",", "\u2009"),
                                         n=share)})
        if us or them:
            rows.append({"label": "vs.score.days",
                         "value": f"{us.get('win', 0)} : {them.get('win', 0)}"})
        # HOW OLD THE ANSWER IS, AS A ROW OF ITS OWN. A card's `note` is a locale KEY on
        # this front-end and this is DATA — «прочитано 3 мин назад» — so it travels as a
        # row's value, which is where data belongs (docs/panel-tabs.md).
        when = _int(state.get("at"))
        rows.append({"label": "vs.score.read",
                     "value": self.t("vs.score.never") if not when
                     else self._ago(when)})
        return {"title": "vs.score", "rows": rows}

    # -- read once, then listen ------------------------------------------------
    #
    # THE RULE, IN THE PERSON'S OWN WORDS (#2633): «я ожидаю, что любые статистики я не
    # должен обновлять, все данные должны подтягиваться при старте клиента, а их
    # изменение проводиться по пушам». So this page has no «Обновить» at all. Every
    # number on it is taken once, when the client gets into the game, and moved after
    # that by the game's own announcements — which is what `CLAUDE.md` has always asked
    # for and what a refresh button quietly replaced.
    #
    # Nothing here ticks for its own sake. The three chains are a DEBOUNCE (a burst of
    # pushes must cost one reading), the build queue's ALARM (a known moment, see
    # `_arm_build_alarm`) and ONE late look for a panel restarted under a client that
    # was already playing.

    def _on_game_ready(self, _payload=None) -> None:
        """The client is in the game — raise the ear and take the first reading."""
        self._listen()
        self._read_all()

    def _first_look(self) -> None:
        """Fires ONCE, and only matters when the panel was restarted mid-game.

        `bus.GAME_READY` is published on the edge of entering the game, so a panel that
        came up over a client which was already playing would never hear it and would
        draw whatever the store remembered until the next login. This asks the link that
        one question and then never runs again — it does not re-arm.
        """
        try:
            ready = bool(self.rt.game.ready())
        except Exception:                    # noqa: BLE001 — a look, never the tab
            ready = False
        if ready:
            self._on_game_ready()

    def _listen(self) -> None:
        """Subscribe to the pushes these numbers move on. Idempotent."""
        if self._wire_off:
            return
        for pattern in (BAG_PUSH, CHIP_PUSH):
            try:
                self._wire_off.append(self.rt.wire.subscribe(pattern, self._on_push))
            except Exception:                # noqa: BLE001 — no capture is not no page:
                break                        #   the reading stands with its age on it
        # …AND THE ARMS RACE'S OWN, ON ITS OWN HANDLER (#2635). A score that moved says
        # nothing about the bag, and re-reading the bag on it would be a question the
        # game did not ask for — one push, one reading.
        try:
            self._wire_off.append(self.rt.wire.subscribe(ARMS_PUSH, self._on_arms_push))
        except Exception:                    # noqa: BLE001 — no ear, the age says so
            pass
        # …AND THE BUILD QUEUE'S OWN (#2641). A slot the server moved announces itself,
        # so the finished buildings appear on the page without a press — which is what
        # the person asked for and what this page could not do while nobody listened.
        # …AND THE SLOT THAT APPEARED OR WENT AWAY (#2645), on the same handler and
        # therefore on the same debounce: starting a construction is what arms the alarm
        # that catches it finishing, and without this the alarm was never armed for a
        # queue that had been empty.
        for pattern in (BUILD_PUSH, QUEUE_ADD_PUSH, QUEUE_DEL_PUSH):
            try:
                self._wire_off.append(self.rt.wire.subscribe(pattern,
                                                             self._on_build_push))
            except Exception:                # noqa: BLE001 — no ear, the age says so
                break
        # …AND THE SAME TWO FOR THE SCIENCE CENTRES (#2662). A queue that appeared or
        # went away is what a research STARTED or COLLECTED looks like on the wire, and
        # it is the door that arms the alarm on the study's own end. Its own handler and
        # therefore its own debounce: a build slot moving says nothing about a study.
        for pattern in (QUEUE_ADD_PUSH, QUEUE_DEL_PUSH, SCIENCE_PUSH):
            try:
                self._wire_off.append(self.rt.wire.subscribe(pattern,
                                                             self._on_research_push))
            except Exception:                # noqa: BLE001 — no ear, the age says so
                break

    def _unlisten(self) -> None:
        """Close this page's ear. The capture stops with its last subscriber."""
        for off in self._wire_off:
            try:
                off()
            except Exception:                # noqa: BLE001 — already closed
                pass
        self._wire_off.clear()

    def _on_push(self, command) -> None:
        """A push crossed — ON THE CAPTURE'S READER THREAD, so nothing is done here.

        `None` is the ear closing rather than a command; the subscription stays and the
        next sync brings the capture back, so there is nothing to do but not treat it as
        news.
        """
        if command is None:
            return
        self.post(self._push_soon)

    def _push_soon(self) -> None:
        """Re-read shortly. Re-armed by each push, so a burst costs ONE reading."""
        try:
            self.rt.tick.arm(CHAIN_PUSH, PUSH_DELAY_MS, self._read_bag)
        except Exception:                    # noqa: BLE001 — no clock, read at once
            self._read_bag()

    def _on_build_push(self, command) -> None:
        """A build queue slot moved — on the reader thread, so nothing is done here."""
        if command is None:
            return
        self.post(self._build_push_soon)

    def _build_push_soon(self) -> None:
        """Re-read the queue shortly. Re-armed by each push, so a burst costs ONE read."""
        try:
            self.rt.tick.arm(CHAIN_BUILD_PUSH, PUSH_DELAY_MS, self._read_builds)
        except Exception:                    # noqa: BLE001 — no clock, read at once
            self._read_builds()

    def _read_builds(self) -> None:
        """What has finished and what is still building. The one door to that reading.

        A reading the gate refuses is not lost (#2645): the push that asked for it does
        not come round again, so a refusal arms one retry a minute later. The chain is
        re-armed by the next refusal and disarmed by the answer, so a client that is
        simply away costs ten questions and then nothing.
        """
        if self.rt.play_async(BUILDS_READ, tag="vs", on_result=self._builds_back):
            return
        self._build_tries += 1
        if self._build_tries > BUILD_RETRIES:
            return
        try:
            self.rt.tick.arm(CHAIN_BUILD_RETRY, BUILD_RETRY_MS, self._read_builds)
        except Exception:                    # noqa: BLE001 — no clock, no net
            pass

    def _read_bag(self) -> None:
        """What the bag holds: the tickets, the chip chests and the component chests.

        Not the buildings and not the science centres: a construction or a study
        finishing moves no item, and asking for either on somebody else's push is
        exactly the wasted question this rule forbids.
        """
        self.rt.play_async(CHIP_READ, args={"ids": ",".join(CHIP_IDS)}, tag="vs",
                           on_result=self._chips_rows_back)
        self.rt.play_async(PART_READ, args={"ids": ",".join(PART_IDS)}, tag="vs",
                           on_result=self._parts_rows_back)
        self.rt.play_async(TICKETS_READ, tag="vs", on_result=self._tickets_back)

    def _read_research(self) -> None:
        """What every science centre is studying. The one door to that reading.

        The same net the build queue has under it (#2645): a reading the gate refuses is
        not lost, because the push that asked for it does not come round again.
        """
        if self.rt.play_async(RESEARCH_READ, tag="vs", on_result=self._research_back):
            return
        self._research_tries += 1
        if self._research_tries > BUILD_RETRIES:
            return
        try:
            self.rt.tick.arm(CHAIN_RESEARCH_RETRY, BUILD_RETRY_MS, self._read_research)
        except Exception:                    # noqa: BLE001 — no clock, no net
            pass

    def _on_research_push(self, command) -> None:
        """A science queue moved — on the reader thread, so nothing is done here."""
        if command is None:
            return
        self.post(self._research_push_soon)

    def _research_push_soon(self) -> None:
        """Re-read shortly. Re-armed by each push, so a burst costs ONE reading."""
        try:
            self.rt.tick.arm(CHAIN_RESEARCH_PUSH, PUSH_DELAY_MS, self._read_research)
        except Exception:                    # noqa: BLE001 — no clock, read at once
            self._read_research()

    def _arm_research_alarm(self, next_sec: int) -> None:
        """Wake when the earliest study is due. `-1` — nothing is studying, no alarm.

        The twin of the build queue's alarm and it is here for the same reason: a study
        that finishes announces nothing anybody can be sure of, and its own end is a
        second the server already handed over — so it is slept until rather than
        watched for (CLAUDE.md, «Read once, then LISTEN»).
        """
        if next_sec is None or next_sec < 0:
            self._research_due = None
            try:
                self.rt.tick.disarm(CHAIN_RESEARCH)
            except Exception:                # noqa: BLE001
                pass
            return
        self._research_due = time.time() + max(0, int(next_sec)) + 1.0
        self._research_tick()

    def _research_tick(self) -> None:
        """A leg of the wait, or the reading it was waiting for."""
        due = self._research_due
        if due is None:
            return
        left = due - time.time()
        if left > 0:
            try:
                self.rt.tick.arm(CHAIN_RESEARCH, int(min(left, BUILD_LEG_SEC) * 1000),
                                 self._research_tick)
            except Exception:                # noqa: BLE001 — no clock, no alarm
                self._research_due = None
            return
        self._research_due = None
        self._read_research()

    def _research_after_press(self, _outcome=None) -> None:
        """A study was collected or closed — so the list on the page is out of date.

        Read again once, as the direct consequence of the press a person just made, and
        never on a clock.
        """
        self._read_research()

    # -- «Гонка вооружений»: the hour, its chests and its points -----------------
    #
    # The card is the errand's own row (`ui/ErrandCard`), drawn at the top of this page,
    # and what it draws comes from here. Three doors and not one of them is a poll: the
    # client getting into the game, the event's own push, and the border of the hour —
    # which is a second the server already named, so it is slept until rather than
    # watched for (`_arm_arms_alarm`).

    def _on_arms_push(self, command) -> None:
        """The score moved — on the capture's reader thread, so nothing is done here."""
        if command is None:
            return
        self.post(self._arms_push_soon)

    def _arms_push_soon(self) -> None:
        """Re-read shortly. Re-armed by each push, so a burst costs ONE reading."""
        try:
            self.rt.tick.arm(CHAIN_ARMS_PUSH, PUSH_DELAY_MS, self._read_arms)
        except Exception:                    # noqa: BLE001 — no clock, read at once
            self._read_arms()

    def _read_arms(self) -> None:
        """Ask which phase is running, what it has paid and what it has scored."""
        self.rt.play_async(ARMS_READ, tag="vs", on_result=self._arms_back)

    def _arms_back(self, outcome) -> None:
        """The reading landed: keep it, book its chests, and set the hour's alarm.

        The reading is kept where BOTH pages find it (`panel/runtime/arms_live.py`) —
        the card on this page and the sheet behind its «i» read that one state, and
        «События» writes the same row when its own card is read.
        """
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        raw = variables.get("arms")
        if not raw:
            # A RUN THAT DID NOT HAPPEN IS NOT A CLOSED EVENT (#2633). The gate refuses
            # a scenario while the light is not green and the recipe leaves nothing
            # behind; writing that down would age-stamp «неизвестно» as a fresh answer.
            return
        from ..runtime import arms_book, arms_live       # noqa: PLC0415 — one reading
        arms_live.record(self.rt, raw, variables.get("arms_day"))
        self._first_ok.add("arms")
        state, _age = arms_live.state(self.rt)
        # WHAT THIS HOUR HAS PAID, WRITTEN DOWN WHILE IT IS STILL RUNNING (#2579): the
        # client keeps no history of a phase that ended, so a chest nobody saw taken is
        # a chest nobody can ask about afterwards.
        if state.stage is not None:
            try:
                arms_book.record(self.rt, state.stage, state.kind,
                                 sum(1 for v in state.taken if v),
                                 ladder=sum(1 for v in state.day_taken if v))
            except Exception:                # noqa: BLE001 — a tally, never the run
                pass
        self._arm_arms_alarm(state.seconds)

    def _arm_arms_alarm(self, left) -> None:
        """Wake when the hour turns over. `None` — nobody knows, so no alarm."""
        try:
            left = int(left)
        except (TypeError, ValueError):
            left = -1
        if left < 0:
            self._arms_due = None
            try:
                self.rt.tick.disarm(CHAIN_ARMS)
            except Exception:                # noqa: BLE001
                pass
            return
        # Two seconds of grace: the phase's own end is the server's second, and asking
        # on the exact tick of it is asking a hair before the next one has started.
        self._arms_due = time.time() + left + 2.0
        self._arms_tick()

    def _arms_tick(self) -> None:
        """A leg of the wait, or the reading it was waiting for."""
        due = self._arms_due
        if due is None:
            return
        left = due - time.time()
        if left > 0:
            try:
                self.rt.tick.arm(CHAIN_ARMS, int(min(left, ARMS_LEG_SEC) * 1000),
                                 self._arms_tick)
            except Exception:                # noqa: BLE001 — no clock, no alarm
                self._arms_due = None
            return
        self._arms_due = None
        self._read_arms()

    def _read_all(self) -> None:
        """The whole page, once — the bag and the build queue.

        Rate-limited by :data:`READ_ALL_GAP_SEC`, because being told «ready» twice in a
        second is ordinary and three scenarios a telling is not.
        """
        now = time.time()
        if now - self._read_all_at < READ_ALL_GAP_SEC:
            return
        self._read_all_at = now
        self._tries += 1
        self._read_bag()
        self._read_builds()
        # …AND THE SCIENCE CENTRES (#2662), the reading Wednesday's own list is drawn
        # from. After this one the queue's own pushes and its alarm move it.
        self._read_research()
        # …AND THE HOUR OF THE ARMS RACE (#2635), which is the first reading of the card
        # standing at the top of this page. After this one the game says when it moved.
        self._read_arms()
        # …AND THE SCORE OF THE DUEL (#2645), which is what this whole page is about.
        self._read_score()
        # …AND THE NET UNDER IT. A scenario refused by the gate answers nothing and says
        # so in the log; the edge that started this does not come round again, so a page
        # that was unlucky once would stay on yesterday's numbers all day. This asks
        # again, a minute later, until every reading has answered or the tries run out.
        self._arm_retry()

    def _arm_retry(self) -> None:
        if len(self._first_ok) >= FIRST_READS or self._tries >= FIRST_TRIES:
            return
        try:
            self.rt.tick.arm(CHAIN_FIRST, FIRST_RETRY_MS, self._retry)
        except Exception:                    # noqa: BLE001 — no clock, no net
            pass

    def _retry(self) -> None:
        """One more attempt at the first reading, if any of it is still missing."""
        if len(self._first_ok) >= FIRST_READS:
            return
        self._read_all_at = 0.0              # a retry is not held by its own floor
        self._read_all()

    # -- the one reading with no push behind it --------------------------------
    #
    # The build queue announces NOTHING: the server sets the slot to `Finish` and no
    # command crosses the wire (`docs/research/ready-buildings.md`). It was taken to the
    # person rather than answered with a poll, and the decision was «по endTime слота» —
    # the slot already carries the second it is due, so the panel sleeps until exactly
    # that second and asks once. A day-long construction is waited out in hour-long
    # legs, and a leg that arrives early re-arms without asking the game anything.

    def _arm_build_alarm(self, next_sec: int) -> None:
        """Wake when the earliest slot is due. `-1` — nothing is building, so no alarm."""
        if next_sec is None or next_sec < 0:
            self._build_due = None
            try:
                self.rt.tick.disarm(CHAIN_BUILD)
            except Exception:                # noqa: BLE001
                pass
            return
        # A second of grace: the slot is set to `Finish` by the server, and asking on the
        # exact tick of its own clock is asking a hair too early.
        self._build_due = time.time() + max(0, int(next_sec)) + 1.0
        self._build_tick()

    def _build_tick(self) -> None:
        """A leg of the wait, or the reading it was waiting for."""
        due = self._build_due
        if due is None:
            return
        left = due - time.time()
        if left > 0:
            try:
                self.rt.tick.arm(CHAIN_BUILD, int(min(left, BUILD_LEG_SEC) * 1000),
                                 self._build_tick)
            except Exception:                # noqa: BLE001 — no clock, no alarm
                self._build_due = None
            return
        self._build_due = None
        self._read_builds()

    def shutdown(self) -> None:
        """Give the ear and the alarms back — a listener outliving its tab is a leak."""
        for chain in (CHAIN_PUSH, CHAIN_BUILD, CHAIN_BUILD_PUSH, CHAIN_BUILD_RETRY,
                      CHAIN_FIRST, CHAIN_ARMS_PUSH, CHAIN_ARMS, CHAIN_RESEARCH,
                      CHAIN_RESEARCH_PUSH, CHAIN_RESEARCH_RETRY):
            try:
                self.rt.tick.disarm(chain)
            except Exception:                # noqa: BLE001
                pass
        self._unlisten()
        off, self._ready_off = getattr(self, "_ready_off", None), None
        if off is not None:
            try:
                off()
            except Exception:                # noqa: BLE001
                pass
        super().shutdown()

    # -- the phone's copy ------------------------------------------------------
    def web_view(self) -> "dict | None":
        """The week as cards, the last read, and the sets.

        Every card is a DAY: its switch on the card itself (the one thing a day is
        about), how much of it is ticked and which set it is played from on the line of
        facts, and the day's actions, ceilings, details and picks behind the gear. The
        knobs are the very fields the inherited screen sent — they travel back through
        the same `set` press, so nothing about what a knob MEANS lives here.
        """
        self._paint_collected()
        cards = [self._score_card(),
                 {"title": "vs.week", "layout": "cards",
                  # THE SCREEN OPENS ON THE WEEK (#2621) — the person's words: «в vs
                  # основным экраном делай неделю». Four cards would otherwise be drawn
                  # as a summary of tiles first, and the week — which is what this page
                  # IS — would be one tap away.
                  "main": True,
                  "items": [self._web_day_item(day) for day, _items in DAYS]},
                 {"title": "vsduel.collect",
                  "rows": [{"label": "vsduel.collect.last",
                            "value": self._collected.get()}]},
                 self._web_sets_card()]
        return {"cards": cards,
                "actions": [{"id": "collect", "label": "vsduel.collect"}]}

    def _web_day_item(self, day: str) -> dict:
        """One day, as the card an errand is drawn as — and NOTHING is added to the card.

        The person's words (#2624): «Ты куда мне кнопки налепил, это всё в параметрах, и
        я сказал у карточки точно такой же шаблон как в таймерах должен быть. Жмем
        шестеренку, видим галку открывать чипы, под ним кнопка открыть все и список чипов
        со статистикой».

        So the card is exactly what «Таймеры» draws — the picture, the name, the day's
        own switch in the corner, the gear — and everything else is INSIDE the gear, one
        block per ability: its switch, the press that runs it now, and what it is about.
        """
        fields = self._web_day_card(day)["fields"]
        # The first field IS the day's own switch (`_web_day_card`), and it belongs on
        # the card rather than behind its gear (#2068): a row's one switch is the thing
        # the row is about.
        toggle = fields[0]
        knobs = {self._plain_key(f.get("key")): f for f in fields[1:]}
        # NO LINE OF PROSE ON THE CARD (#2645). It carried «Действия 2 / 2 · Набор
        # Накопление» — two facts about the PLAN, on a card whose whole subject is the
        # day and its switch. The person's words: «На карточках в vs убери текстовое
        # поле, оно не ясно к чему». Both readings are still reachable where they belong:
        # what the day is set to plays out inside the gear, and the sets are their own
        # card on the same page.
        item = {"label": f"vsduel.day.{day}", "shape": "cover", "toggle": toggle}
        groups = []
        for action in self._day_actions(day):
            name = f"{day}.{action.key}"
            if name not in READY:
                continue                  # an unwired box is not offered at all
            group = {"title": action.label,
                     "fields": [knobs[name]] if name in knobs else [],
                     "actions": []}
            if name in RUNS:
                group["actions"].append({"id": "run", "args": {"key": name},
                                         "label": RUN_LABELS.get(name, action.label)})
            if action.key == "drone_chips":
                # …and under the press, what it is about: one row per grade, with the
                # game's own picture, how many are in the bag and how many were opened.
                group["items"] = self._chips_rows()
                # NO «Обновить» (#2633). The count moves by itself: it is read when the
                # client gets into the game and again whenever the game says a bag count
                # changed. The note under it carries the age, so a reading that somehow
                # stopped moving is visibly old rather than quietly wrong.
                group["note"] = self._chips_note()
            if action.key == "survivor_tickets":
                # THE STATISTICS THE PERSON ASKED FOR (#2632): «сколько билетов, сколько
                # потратили сегодня». One row, two numbers, and the age of the reading
                # under it — a stale count is visibly stale rather than quietly wrong.
                group["items"] = [{"label": "vs.tickets.stats",
                                   "facts": self._tickets_facts()}]
                group["note"] = self._tickets_note()
            if action.key == "build_collect":
                # THE FINISHED BUILDINGS, one row each — the game's own picture, the
                # level, and its own «Открыть». «Открыть все» goes dead when there is
                # nothing waiting, which is the person's own words: «кнопка открыть все,
                # если есть, что открывать, иначе дисаблед».
                # THE FINISHED ONES FIRST, THEN WHAT IS STILL BUILDING (#2634) — one
                # list of the same rows, and the second half carries the price of
                # closing it and the press that pays it.
                rows = self._builds_rows()
                group["items"] = rows + self._building_rows()
                for press in group["actions"]:
                    if press.get("id") == "run":
                        press["disabled"] = not rows
                note = self._builds_note()
                # …AND WHETHER «Открыть» CAN DO ANYTHING THIS HOUR (#2641). The button
                # stays live — the gate is the recipe's — but a press that is going to
                # be refused says so beforehand instead of looking broken.
                gate = self._builds_gate() if rows else ""
                group["note"] = f"{note} · {gate}" if gate else note
            if action.key == "drone_parts":
                # WEDNESDAY'S OWN CHESTS (#2662), drawn exactly as Monday's are: one row
                # per grade, the game's own picture, what the bag holds and how many were
                # opened. Different box, same shape — and no «Обновить»: the count moves
                # when the game says a bag count moved.
                group["items"] = self._parts_rows()
                group["note"] = self._parts_note()
            if action.key == "research_collect":
                # THE SCIENCE CENTRES AND WHAT EACH IS STUDYING (#2662). A study that has
                # finished carries «Собрать»; one that is running carries «Ускорить» with
                # what closing it would take out of the bag written beside it — an
                # irreversible spend is NAMED before it is made (CLAUDE.md), and a bag
                # that cannot close it offers a dead button rather than a wasted parcel.
                group["items"] = self._research_rows()
                ready = self._research_ready()
                for press in group["actions"]:
                    if press.get("id") == "run":
                        press["disabled"] = not ready
                group["note"] = self._research_note()
            groups.append(group)
        if groups:
            item["options_groups"] = groups
            item["options_title"] = f"vsduel.day.{day}"
        else:
            # A DAY NOBODY HAS WIRED SAYS SO, in one word, rather than offering knobs
            # that decide nothing.
            item["pill"] = "vs.day.soon"
        return item

    @staticmethod
    def _plain_key(key) -> str:
        """`plan.mon.drone_chips` -> `mon.drone_chips`; a ceiling keeps its own name."""
        text = str(key or "")
        return text[len("plan."):] if text.startswith("plan.") else text

    def _day_actions(self, day: str) -> list:
        """The day's actions in the order the plan lists them, its own picks left out."""
        return [item for item in walk_items(dict(DAYS)[day])
                if not isinstance(item, _Choice)]

    def web_press(self, action, args) -> dict:
        """The week's own presses, plus «run this one now» (#2617).

        The button plays the recipe the knob names and nothing else: no gate of the
        ability lives here, and the panel does not decide what «opening the chip chests»
        is (CLAUDE.md). A day switched off is not a refusal either — the person pressed
        it themselves, and a press is not the schedule.
        """
        if action == "open_one":
            # ONE BUILDING, named by the row that drew it. The gate is the recipe's, so a
            # press outside the arms race's building hour is refused by the ability and
            # not by the panel — and the reading is re-taken either way, because a run
            # that opened nothing must not leave the row looking opened.
            uuid = str((args or {}).get("uuid") or "")
            if not uuid.isdigit():
                return {"error": "unknown"}
            return {"ok": self.rt.play_async(
                RUNS["tue.build_collect"], args={"uuid": uuid}, tag="vs", human=True,
                on_result=self._builds_after_open)}
        if action == "finish_one":
            # AN IRREVERSIBLE SPEND, NAMED ONE AT A TIME. The panel holds no part of the
            # ability: which speed-ups close this construction, whether the bag can, and
            # what happens when the server drops the send are all
            # `actions/finish_building.md`'s (CLAUDE.md). The reading is taken again
            # either way — a run that closed nothing must not leave the row looking shut.
            uuid = str((args or {}).get("uuid") or "")
            if not uuid.isdigit():
                return {"error": "unknown"}
            return {"ok": self.rt.play_async(
                BUILD_FINISH, args={"uuid": uuid}, tag="vs", human=True,
                on_result=self._builds_after_open)}
        if action == "collect_one":
            # ONE STUDY, named by the row that drew it. Collecting is not a spend, so it
            # asks nothing — and the list is re-read either way, because a run that
            # collected nothing must not leave the row looking taken.
            uuid = str((args or {}).get("uuid") or "")
            if not uuid.isdigit():
                return {"error": "unknown"}
            return {"ok": self.rt.play_async(
                RUNS["wed.research_collect"], args={"uuid": uuid}, tag="vs", human=True,
                on_result=self._research_after_press)}
        if action == "speed_one":
            # AN IRREVERSIBLE SPEND, NAMED ONE AT A TIME — the research twin of
            # «Завершить» on a construction. Which speed-ups close this study and
            # whether the bag can are `actions/speedup_research.md`'s business, never
            # the panel's.
            uuid = str((args or {}).get("uuid") or "")
            if not uuid.isdigit():
                return {"error": "unknown"}
            return {"ok": self.rt.play_async(
                RESEARCH_SPEEDUP, args={"uuid": uuid}, tag="vs", human=True,
                on_result=self._research_after_press)}
        if action != "run":
            return super().web_press(action, args)
        name = str((args or {}).get("key") or "")
        recipe = RUNS.get(name) if name in READY else None
        if recipe is None:
            return {"error": "unknown"}
        extra = {}
        if name == "mon.drone_chips":
            # The ids the page draws are the ids the run opens — one list, never two.
            extra = {"args": {"ids": ",".join(CHIP_IDS)},
                     "on_result": self._chips_opened_back}
        if name == "tue.survivor_tickets":
            extra = {"on_result": self._tickets_spent_back}
        if name == "tue.build_collect":
            extra = {"on_result": self._builds_after_open}
        if name == "wed.drone_parts":
            # The ids the page draws are the ids the run opens — one list, never two.
            extra = {"args": {"ids": ",".join(PART_IDS)},
                     "on_result": self._parts_opened_back}
        if name == "wed.research_collect":
            extra = {"on_result": self._research_after_press}
        return {"ok": self.rt.play_async(recipe, tag="vs", human=True, **extra)}

    def _builds_after_open(self, outcome) -> None:
        """A building was opened — so the list the page is showing is out of date.

        The reading is taken again, once, as the direct consequence of the press a person
        just made — never on a clock (CLAUDE.md, «Read once, then LISTEN»). Without it the
        row a press has already taken goes on being offered as though nothing happened,
        and «Открыть все» stays lit over an empty queue.
        """
        self._read_builds()


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(VsTab))
