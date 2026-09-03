"""The «События» tab: what the game's events are doing, one block per event.

**Nothing on this tab is marked by hand.** Every number is a READING — the game's own
answer — and the panel draws it and nothing else. The panel keeps no count of its own,
deliberately: the moment it did, an attack sent from the phone or by the person playing
on the screen in front of them would stop being counted, and the board would be confidently
wrong rather than merely late.

**An event that is not running is drawn GREY, not hidden.** That is the whole reason this
tab is groups rather than a list of live things: a block that disappears when its event
ends looks exactly like a block nobody has written yet, and there is no way for a person
to tell «nothing to do here today» from «this panel does not know about that event». So
«Кодовое имя» keeps its heading, its numbers stay on screen as the last thing that was
true, and its button greys out.

**The first group is «Кодовое имя»** — the game's own name for it (key `100086` in the
client's tables; `docs/game-glossary.md`), the world-boss event. The game puts one boss on
the world map for a few hours at a time and asks for three attacks on it; attempts
themselves are not rationed, and only the biggest single hit counts for the daily ranking.
So the two numbers worth showing are exactly the two the person is playing for: how many
attacks have gone out, and the biggest hit.

**Where the state comes from.** One scenario, `actions/read_codename_event.md`, one round
trip, one line of `key=value` pairs — the panel assembles no Lua and holds no gate
(`CLAUDE.md`). It is re-read when the tab is first opened, every few minutes while it is
open, and whenever the person presses «Обновить».

**Both presses here play a scenario and nothing else.** «Атаковать сейчас» runs
`actions/attack_codename_boss.md`, which finds the boss, finds a squad standing in the
base and sends it. «Выполнить дневную норму» runs `actions/attack_codename_daily.md` —
the same attack, repeated until the day owes no more — and is the very errand the clock
plays once a day (`timers.item.attack_codename_daily`), offered here because a person who
has just sat down wants it now rather than at the top of the next period. HOW MANY is the
scenario's question to the server and never a number this tab keeps, so the day's press is
safe to lean on: on a day already played it sends nothing. Whether an attack COUNTED is
then re-read from the game, never inferred from the press returning cleanly.

**The second group is «Золотые зомби»** — the invasion event's small monster (config id
1030000), which the chain `actions/attack_golden_zombies.md` hunts: it scans the map,
sends the chosen squad at the nearest one, and then at the nearest one to WHERE THAT
SQUAD IS, until the energy runs out. The reading is `actions/read_golden_zombies.md` —
the energy, what the game charges for one attack, how many that buys and how many golden
zombies the client currently knows about.

**The squad is chosen here, and it is the only thing on this tab a person sets.** It is a
choice about the account, so it lives in the tab's own saved block and travels with the
profile; everything else under the heading is still a reading. Beside it is the DAY's
tally — how many marches this panel sent and what they cost — which is the panel's own
history of its own presses (`panel/golden_zombies.py`) and never a claim about what the
account did. The live energy line above it is the truth about the purse; a person
attacking by hand spends from the same one and is not in the tally at all.

That is the rule both boards share: **the state is read, the doing is offered.** A press
may start work; only a reading may say it is done. «Чеклист» draws the same press on its
own «Кодовое имя» row, plays the same scenario, and greys it on the same terms — the
event being CLOSED, and nothing else.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ... import golden_zombies as goldmod
from ...runtime import claims
from ...widgets import ScrollableFrame, font as ui_font, tk_stringvar
from ..base import PanelTab
from . import model as modelmod
from ...runtime import statevar
from ...runtime import errand_options as errandopts
from ...runtime import squad_picker

#: How a state looks in the window. A glyph is not a word — it needs no translating and
#: is the same in every language, which is why these three are literals and the sentence
#: beside them is a key.
_GLYPH = {
    modelmod.OPEN:    ("●", "#4caf50"),
    modelmod.CLOSED:  ("—", "#888888"),
    modelmod.UNKNOWN: ("?", "#888888"),
}

def _whole(raw):
    """A whole number out of whatever the page sent, or ``None``.

    A field's value arrives as data and the page is not the only thing that can send it,
    so a value that is not a number — or is one the card never offered — is REFUSED with
    a reason rather than clamped to something the person did not choose. Clamping is
    right when a saved file is read back (`model.carriage_of`); it is wrong here, because
    it would answer «сделано» to a fare nobody asked for.
    """
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


#: What a greyed-out block is drawn in. The event is not on; the numbers beside it are
#: the last that were true, and they should not read as live.
_GREY = "#888888"
_LIVE = ""


class EventsTab(PanelTab):
    """The game's events, the state of each, and the one press there is so far."""

    ID = "events"
    TITLE_KEY = "tab.events"
    ORDER = 25
    PREFERRED_SIZE = "760x560"
    LOCALE_NS = ("events",)
    #: The client, to read; the scenarios, to read WITH and to attack with.
    NEEDS = frozenset({"daemon", "actions"})
    WEB_SCREEN = True

    #: A re-read while the tab is simply open. Three minutes: far cheaper than the
    #: reading is worth (one round trip, ~0.2 s) and far more often than a window.
    REFRESH_SEC = 180
    #: On being shown again, re-read anything older than this rather than the full period.
    STALE_SEC = 60
    #: How often the status line's «прочитано N назад» and the countdown are redrawn.
    TICK_MS = 15_000
    #: How long after an attack goes out before the board is re-read. The server has to
    #: answer `UserGetActBossMarch` before the count moves, and the scenario has already
    #: waited for that — this is the margin, not the wait.
    AFTER_ATTACK_MS = 2_000

    #: Declared on the CLASS and not only in ``__init__``: the base's own constructor
    #: restores the saved block before the lines below run, and the restore reaches for
    #: these two. A tab that has never been drawn has no widgets, so ``None`` is the
    #: honest answer at that moment rather than an attribute error (#2065).
    _arms_speedup_var = None
    _arms_speedup = modelmod.ARMS_SPEEDUP_DEFAULT
    _arms_minutes = modelmod.ARMS_MINUTES_DEFAULT
    _arms_units = modelmod.ARMS_UNITS_DEFAULT
    _arms_soldiers = modelmod.ARMS_SOLDIERS_DEFAULT
    _arms_free_minutes = modelmod.ARMS_FREE_MINUTES_DEFAULT

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        #: The last answer from the game. `None` until the first read comes back.
        self._reading = None
        self._busy = False
        self._attacking = False
        self._body = None
        self._status = None
        self._attack_button = None
        self._daily_button = None
        #: Which of the two presses is on its way, so the sentence that comes back names
        #: the right one. `None` while nothing is running.
        self._sent_key = None
        #: …and the sentence a FAILURE is reported in, and what to re-read afterwards:
        #: four presses share this one runner and they belong to two different events.
        self._failed_key = "events.codename.log.failed"
        self._after_press = None

        # -- «Под руинами» ---------------------------------------------------
        #: The last line the descent's own reader brought back, verbatim. Nothing is
        #: read to draw the card (`CLAUDE.md` — read once, then listen): the numbers
        #: appear when a person plays a run or asks for them.
        self._ruins_said = ""
        self._ruins_running = False

        # -- «Ящик с сюрпризом»: the packet of free diamonds a box sometimes drops ----
        #: The last line `read_lucky_packet` brought back, verbatim, and the last one the
        #: ear answered with. Nothing is read to DRAW the card (`CLAUDE.md` — read once,
        #: then listen): the numbers appear when a person asks or when a press comes back.
        self._lucky_said = ""
        self._lucky_watch_said = ""
        self._lucky_running = False

        # -- «Золотые зомби» ------------------------------------------------
        #: Its own reading, on its own clock: the two events answer different questions
        #: and one being unreadable must not blank the other.
        self._golden = None
        self._golden_busy = False
        self._golden_running = False
        self._golden_button = None
        #: The tile «Найти ближайшего» last chose, in the panel's coordinate token
        #: (`tools/lib/coords.py`) — the window's log makes it clickable, and the card
        #: shows it on both front-ends (#1702).
        self._golden_target = ""
        #: The seconds between two orders, as the RUN counted them — its average and
        #: its last (#2390). Zero means «no run has sent two orders yet», which the
        #: card draws as «—» rather than as a fast lap.
        self._golden_lap = 0
        self._golden_lap_last = 0
        #: The label that shows it beside the buttons — made in `build()`, `None` in a
        #: tab nobody has opened.
        self._target_var = None
        #: What the last step press came back with, as a locale key. The scenarios say
        #: their reasons in the log; this puts the last one where the buttons are,
        #: because «ничего не происходит» is what a refusal looks like from across the
        #: room (#1702).
        self._step_said = ""
        self._step_var = None
        #: Which step press is in flight, so what follows it can be armed when it ENDS.
        self._step_ran = ""
        #: Presses that arrived while the client was busy, one slot per button: they are
        #: retried until they go in, because «нажал — будет выполнено» (#1702). A second
        #: press of the SAME button replaces the waiting one; different buttons wait
        #: side by side.
        self._waiting: dict = {}
        #: The squad the chain sends, by the slot the player sees. A plain int until
        #: `build()` makes the widget — a tab nobody has opened still has to be able to
        #: answer `config()` (`docs/panel-tabs.md`).
        self._squad = modelmod.GOLDEN_SQUAD_DEFAULT
        self._squad_var = None
        #: Whether the chain rides to a far target on a gather order first. OFF until
        #: the game lets a squad leave a mine without walking home: the ride itself is
        #: measured and worth minutes, and the attack from the far end is refused in
        #: silence (#1519).
        self._approach = False
        self._approach_var = None
        #: The day's tally, read out of `panel.db` the first time anybody looks.
        self._tally = None
        #: Whether the golden reading should follow the codename one home.
        self._chain_golden = False

        # -- «Кристальный босс» ----------------------------------------------
        #: Its own reading, taken at the end of the same chain: the card answers a
        #: different event from every other one on this board, and one of them being
        #: unreadable must not blank the rest.
        self._crystal = None
        self._crystal_busy = False
        self._chain_crystal = False

        # -- «Поезд альянса» ------------------------------------------------
        #: Its own reading, on its own clock, for the same reason the other two have
        #: one: the station answers a question neither of them asks, and an unreadable
        #: train must not blank the boss board.
        self._train = None
        self._train_busy = False
        self._train_boarding = False
        #: Whether the train reading should follow the golden one home.
        self._chain_train = False
        #: The two knobs. Plain ints and NOT Tk variables on purpose: the wire trigger
        #: reads them off the scheduler's own thread through `register_args`, and a Tk
        #: variable read from there raises «main thread is not in main loop» — which is
        #: exactly what cost the rally auto-join its first fire after every start-up
        #: (#1416, `panel/tabs/rally/autorally.py`).
        self._train_carriage = modelmod.TRAIN_CARRIAGE_DEFAULT
        self._train_tickets = modelmod.TRAIN_TICKETS_DEFAULT
        #: …and whether the panel may make a short fare up out of the player's DIAMONDS.
        #: A separate answer from the number beside it, and off: the number says what the
        #: fare should be, this says whether money may be spent to reach it.
        self._train_buy = modelmod.TRAIN_BUY_DEFAULT
        #: …and whether the trigger has been told where to read them. Idempotent.
        self._train_args_registered = False
        self._register_train_args()

        # -- «Гонка вооружений» ---------------------------------------------
        #: Its own reading, on its own clock, like the other three. The phase running
        #: now arrives with it; the day's six borders come in a SECOND variable, because
        #: the calendar is a list and this board's `Reading` holds whole numbers.
        self._arms = None
        self._arms_cal: tuple = ()
        self._arms_busy = False
        self._arms_running = False
        #: Whether the arms reading should follow the train one home.
        self._chain_arms = False
        #: Whether the errand's hero phase may hire. A plain bool and NOT a Tk variable,
        #: for the reason the train's knobs are not either: the scheduler reads it off
        #: its own thread through `register_args`, and a Tk variable read from there
        #: raises «main thread is not in main loop» (#1416).
        self._arms_hero = modelmod.ARMS_HERO_DEFAULT
        self._arms_hero_var = None
        #: …and the drone phase's three: whether it may raise at all, the stamina it may
        #: spend doing it, and which squad carries the banners.
        self._arms_drone = modelmod.ARMS_DRONE_DEFAULT
        self._arms_drone_var = None
        self._arms_stamina = modelmod.ARMS_STAMINA_DEFAULT
        self._arms_speedup = modelmod.ARMS_SPEEDUP_DEFAULT
        self._arms_speedup_var = None
        self._arms_minutes = modelmod.ARMS_MINUTES_DEFAULT
        self._arms_units = modelmod.ARMS_UNITS_DEFAULT
        self._arms_soldiers = modelmod.ARMS_SOLDIERS_DEFAULT
        self._arms_free_minutes = modelmod.ARMS_FREE_MINUTES_DEFAULT
        self._arms_squad = modelmod.ARMS_SQUAD_DEFAULT
        self._arms_args_registered = False
        self._register_arms_args()

    # -- the tab ------------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Button(bar, command=lambda: self.refresh(human=True)),
                "events.refresh").pack(side="left")

        self._status = tk_stringvar(self.rt.root)
        ttk.Label(bar, textvariable=self._status, foreground=_GREY).pack(
            side="left", padx=(12, 0))

        self._body = ScrollableFrame(self.parent)
        self._body.pack(fill="both", expand=True, padx=6, pady=(6, 10))
        self._render()

    def ensure_loaded(self) -> None:
        """Start the clock and take the first readings, the first time anybody looks."""
        self._register_train_args()
        self._register_arms_args()
        self._tick()
        self.refresh_both()

    def _register_train_args(self) -> None:
        """Let the «alliance_train_board» trigger read the two knobs LIVE. Idempotent.

        Without it the trigger would fire with whatever `args` its catalogue row was
        written with, and the card and the standing order would drift apart the first
        time somebody moved the carriage — the phone showing one rule and the push
        obeying another, with nothing on screen to say which had just run.
        """
        if self._train_args_registered:
            return
        schedule = getattr(self.rt, "schedule", None)
        if schedule is None or not hasattr(schedule, "register_args"):
            return                              # a tab opened on its own
        schedule.register_args("alliance_train_board", self.train_args)
        self._train_args_registered = True

    def _register_arms_args(self) -> None:
        """Let the «perform_arms_race» errand read the hero switch LIVE. Idempotent.

        Same reason as the train's: without it the errand fires with whatever its
        catalogue row was written with, and the card and the standing order drift apart
        the first time somebody moves the switch — the phone showing one rule and the
        four-hourly run obeying another.
        """
        if self._arms_args_registered:
            return
        schedule = getattr(self.rt, "schedule", None)
        if schedule is None or not hasattr(schedule, "register_args"):
            return                              # a tab opened on its own
        schedule.register_args(modelmod.ARMS_ERRAND, self.arms_args)
        self._arms_args_registered = True

    def arms_args(self) -> dict:
        """The arms errand's ARGS as this card has them right now.

        `rallies` is the one value the card does not own: it is what the DAY's own rally
        budget still allows, read out of the rally tab's books at the moment the errand
        fires. The arms race gets no allowance of its own, on purpose — an event that
        quietly overspends the caps the person set is exactly what #2051 put them there
        to stop, and a drone phase that therefore scores nothing is the right outcome.
        """
        return {"hero": 1 if self.arms_hero() else 0,
                "drone": 1 if self.arms_drone() else 0,
                "speedup": 1 if self.arms_speedup() else 0,
                "minutes": self.arms_minutes(),
                "units": 1 if self.arms_units() else 0,
                "soldiers": self.arms_soldiers(),
                "free_minutes": self.arms_free_minutes(),
                "stamina": self.arms_stamina(),
                "rallies": self.arms_rallies(),
                "squad": self.arms_squad()}

    def arms_rallies(self) -> int:
        """How many rallies the day's budget still leaves the drone phase.

        A budget that cannot be READ answers 0 — «nothing left» rather than «no ceiling»
        — because the cost of being wrong runs one way only: a run handed a number it
        should not have had spends the person's rallies and cannot give them back.
        """
        try:
            from ..rally import limits as rallygate
            limits, counts = rallygate.read(self.rt)
            left = counts.left_for(modelmod.ARMS_RALLY_KIND, limits)
        except Exception as exc:            # noqa: BLE001 — a number, never the run
            self.rt.dbg("events").warning("arms rally budget unreadable: %s", exc)
            return 0
        if left < 0:
            return modelmod.ARMS_RALLIES_UNCAPPED
        return max(0, int(left))

    def arms_drone(self) -> bool:
        """May the errand's drone phase raise banners?"""
        if self._arms_drone_var is not None:
            try:
                return bool(self._arms_drone_var.get())
            except tk.TclError:            # the window is going away
                pass
        return bool(self._arms_drone)

    def arms_stamina(self) -> int:
        """The most stamina one drone run may spend. The person's number, clamped."""
        return modelmod.arms_stamina_of(self._arms_stamina)

    def arms_speedup(self) -> bool:
        """May the errand's building / units / research phases spend speed-ups?"""
        if self._arms_speedup_var is not None:
            try:
                return bool(self._arms_speedup_var.get())
            except tk.TclError:            # the window is going away
                pass
        return bool(self._arms_speedup)

    def arms_minutes(self) -> int:
        """The most minutes of speed-up one such run may spend. Clamped."""
        return modelmod.arms_minutes_of(self._arms_minutes)

    def arms_units(self) -> bool:
        """May the errand's unit phase collect the batches and start new ones?

        A switch of its own rather than a second reading of `arms_speedup`: what the unit
        phase spends is RESOURCES, and an account saving them for a building says no to
        this one while leaving the speed-ups alone.
        """
        return bool(self._arms_units)

    def arms_soldiers(self) -> int:
        """The most soldiers ONE unit-phase run may put into training. Clamped."""
        return modelmod.arms_soldiers_of(self._arms_soldiers)

    def arms_free_minutes(self) -> int:
        """The minutes a unit-phase run may spend freeing a busy barracks. Clamped."""
        return modelmod.arms_free_minutes_of(self._arms_free_minutes)

    def arms_squad(self) -> int:
        """Which squad raises the drone phase's banners, by the slot the player sees."""
        return modelmod.squad_of(self._arms_squad)

    def errand_options(self) -> dict:
        """What the standing orders on this board will do when they fire (#2017).

        Two errands: whether the arms-race run may hire in the hero phase, and the
        train's three. The three knobs were on this card and nowhere else, so «Таймеры» — the tab that
        says whether `alliance_train_board` is even listening — showed a name and no way
        to say which carriage, what fare, or whether to buy the missing contracts. They
        are the same values the card edits and the same the recipe reads at fire time
        (`train_args`): plain attributes here, so a tab nobody has opened has them.
        """
        return {
            modelmod.ARMS_ERRAND: (
                errandopts.Option(modelmod.ARMS_HERO_KEY, "events.arms.hero",
                                  errandopts.SWITCH,
                                  hint_key="events.arms.hero.hint",
                                  get=self.arms_hero,
                                  set=lambda on: self.set_arms_option(
                                      modelmod.ARMS_HERO_KEY, on)),
                errandopts.Option(modelmod.ARMS_DRONE_KEY, "events.arms.drone",
                                  errandopts.SWITCH,
                                  hint_key="events.arms.drone.hint",
                                  get=self.arms_drone,
                                  set=lambda on: self.set_arms_option(
                                      modelmod.ARMS_DRONE_KEY, on)),
                errandopts.Option(modelmod.ARMS_STAMINA_KEY, "events.arms.stamina",
                                  errandopts.NUMBER,
                                  hint_key="events.arms.stamina.hint",
                                  low=modelmod.ARMS_STAMINA_MIN,
                                  high=modelmod.ARMS_STAMINA_MAX,
                                  get=self.arms_stamina,
                                  set=lambda v: self.set_arms_option(
                                      modelmod.ARMS_STAMINA_KEY, v)),
                errandopts.Option(modelmod.ARMS_SPEEDUP_KEY, "events.arms.speedup",
                                  errandopts.SWITCH,
                                  hint_key="events.arms.speedup.hint",
                                  get=self.arms_speedup,
                                  set=lambda on: self.set_arms_option(
                                      modelmod.ARMS_SPEEDUP_KEY, on)),
                errandopts.Option(modelmod.ARMS_MINUTES_KEY, "events.arms.minutes",
                                  errandopts.NUMBER,
                                  hint_key="events.arms.minutes.hint",
                                  low=modelmod.ARMS_MINUTES_MIN,
                                  high=modelmod.ARMS_MINUTES_MAX,
                                  get=self.arms_minutes,
                                  set=lambda v: self.set_arms_option(
                                      modelmod.ARMS_MINUTES_KEY, v)),
                errandopts.Option(modelmod.ARMS_UNITS_KEY, "events.arms.units",
                                  errandopts.SWITCH,
                                  hint_key="events.arms.units.hint",
                                  get=self.arms_units,
                                  set=lambda on: self.set_arms_option(
                                      modelmod.ARMS_UNITS_KEY, on)),
                errandopts.Option(modelmod.ARMS_SOLDIERS_KEY, "events.arms.soldiers",
                                  errandopts.NUMBER,
                                  hint_key="events.arms.soldiers.hint",
                                  low=modelmod.ARMS_SOLDIERS_MIN,
                                  high=modelmod.ARMS_SOLDIERS_MAX,
                                  get=self.arms_soldiers,
                                  set=lambda v: self.set_arms_option(
                                      modelmod.ARMS_SOLDIERS_KEY, v)),
                errandopts.Option(modelmod.ARMS_FREE_MINUTES_KEY,
                                  "events.arms.free_minutes",
                                  errandopts.NUMBER,
                                  hint_key="events.arms.free_minutes.hint",
                                  low=modelmod.ARMS_FREE_MINUTES_MIN,
                                  high=modelmod.ARMS_FREE_MINUTES_MAX,
                                  get=self.arms_free_minutes,
                                  set=lambda v: self.set_arms_option(
                                      modelmod.ARMS_FREE_MINUTES_KEY, v)),
                errandopts.Option(modelmod.ARMS_SQUAD_KEY, "events.arms.squad",
                                  errandopts.SQUADS, single=True,
                                  get=lambda: [self.arms_squad()],
                                  set=lambda v: self.set_arms_option(
                                      modelmod.ARMS_SQUAD_KEY, v)),),
            "alliance_train_board": (
            errandopts.Option("train_carriage", "events.train.carriage.set",
                              errandopts.NUMBER,
                              low=min(modelmod.TRAIN_CARRIAGES),
                              high=max(modelmod.TRAIN_CARRIAGES),
                              get=self.carriage,
                              set=lambda v: self.set_train_option(
                                  modelmod.TRAIN_CARRIAGE_KEY, v)),
            errandopts.Option("train_tickets", "events.train.tickets.set",
                              errandopts.NUMBER,
                              hint_key="events.train.tickets.hint",
                              low=min(modelmod.TRAIN_TICKETS),
                              high=max(modelmod.TRAIN_TICKETS),
                              get=self.tickets,
                              set=lambda v: self.set_train_option(
                                  modelmod.TRAIN_TICKETS_KEY, v)),
            errandopts.Option("train_buy", "events.train.buy", errandopts.SWITCH,
                              hint_key="events.train.buy.hint",
                              get=self.buy_missing,
                              set=lambda on: self.set_train_option(
                                  modelmod.TRAIN_BUY_KEY, on)))}

    def _train_knob_saved(self) -> None:
        """One of the three moved — ask for the profile to be written (#2010).

        `config()` hands these back whether or not this tab was ever drawn, so the save
        is all that is needed; without it a knob moved from the phone was silently gone
        at the next restart. Asked for, never insisted on: a tab opened on its own has
        no settings binder behind it, and a knob is not worth a crash.
        """
        # INTO THE BLOCK FIRST. An undrawn tab hands back the block it was GIVEN rather
        # than what `config()` reads (`PanelTab.stored_config`), and in a panel with no
        # window no tab is ever drawn — so without this the save writes the old value
        # over the new one.
        try:
            self.remember({modelmod.TRAIN_CARRIAGE_KEY: self.carriage(),
                           modelmod.TRAIN_TICKETS_KEY: self.tickets(),
                           modelmod.TRAIN_BUY_KEY: self.buy_missing()})
            self.rt.settings.changed()
        except Exception:                  # noqa: BLE001 — a save, never the card
            pass

    def set_train_option(self, key: str, value) -> bool:
        """Move one of the three, wherever it was pressed — card, gear or phone.

        ONE PATH: this is the card's own press, so a value the model will not have is
        REFUSED there rather than clamped here — «4 билета» must not quietly become 3
        and spend a contract nobody offered.
        """
        return bool(self.web_press("set", {"key": key, "value": value}).get("ok"))

    def train_args(self) -> dict:
        """The boarding recipe's ARGS as this card has them right now."""
        return {"carriage": self.carriage(), "tickets": self.tickets(),
                "buy": 1 if self.buy_missing() else 0}

    def on_show(self) -> None:
        """Somebody is looking: re-read anything stale and pick the clock back up."""
        if self._age() > self.STALE_SEC:
            self.refresh_both()
        else:
            self._refresh_status()
            if self._age_of(self._golden) > self.STALE_SEC:
                self.refresh_golden()
            elif self._age_of(self._train) > self.STALE_SEC:
                self.refresh_train()
            elif self._age_of(self._arms) > self.STALE_SEC:
                self.refresh_arms()
        self.rt.tick.arm("events_poll", self.TICK_MS, self._tick)

    def on_hide(self) -> None:
        """Nobody is looking any more: stop the clock (#2393).

        Until the web had a look at all, this pair did not matter — the window armed
        `events_poll` on show and simply never stopped it, which on a machine with a
        window is a poll behind a page somebody had opened once. It matters now, because
        the phone opens this board and puts itself in a pocket: a clock left running
        there is a read of five events every three minutes that nobody asked for, which
        is precisely what «нет активных действий в фоне» forbids.

        The readings themselves are KEPT, with their ages: what is on screen when a page
        is left is still the truth about when it was read.
        """
        self.rt.tick.disarm("events_poll")

    def on_language_change(self) -> None:
        self._render()

    def on_profile_switch(self) -> None:
        """A different account is in a different place in the event: forget and re-read."""
        self._reading = None
        self._golden = None
        self._train = None
        self._arms = None
        self._crystal = None
        #: …and the calendar with it: a week of borders belongs to the account that was
        #: told them, and another account's day starts and ends somewhere else.
        self._arms_cal = ()
        self._tally = None
        self._render()
        self.refresh_both()

    def panic(self) -> None:
        """«Стоп всё»: stop asking. What is on screen stays, with its age beside it."""
        self.rt.tick.disarm("events_poll")
        self.rt.tick.disarm("events_after_attack")
        self.rt.tick.disarm("events_after_hunt")
        self.rt.tick.disarm("events_after_board")
        self.rt.tick.disarm("events_after_arms")

    def shutdown(self) -> None:
        self.rt.tick.disarm("events_poll")
        self.rt.tick.disarm("events_after_attack")
        self.rt.tick.disarm("events_after_hunt")
        self.rt.tick.disarm("events_after_board")
        self.rt.tick.disarm("events_after_arms")

    # -- the reading --------------------------------------------------------
    def _tick(self) -> None:
        """Repaint the ages, and take a fresh reading when the old one is stale."""
        try:
            if not self._busy and self._age() >= self.REFRESH_SEC:
                self.refresh_both()
            else:
                self._refresh_status()
                if (not self._golden_busy
                        and self._age_of(self._golden) >= self.REFRESH_SEC):
                    self.refresh_golden()
                elif (not self._train_busy
                        and self._age_of(self._train) >= self.REFRESH_SEC):
                    self.refresh_train()
                elif (not self._arms_busy
                        and self._age_of(self._arms) >= self.REFRESH_SEC):
                    self.refresh_arms()
                elif (not self._crystal_busy
                        and self._age_of(self._crystal) >= self.REFRESH_SEC):
                    self.refresh_crystal()
        finally:
            self.rt.tick.arm("events_poll", self.TICK_MS, self._tick)

    def _age(self) -> float:
        """Seconds since the last reading; a very large number when there is none."""
        return self._age_of(self._reading)

    @staticmethod
    def _age_of(reading) -> float:
        """The same, for whichever of the two readings is being asked about."""
        if reading is None or not reading.at:
            return float("inf")
        return max(0.0, time.time() - reading.at)

    def refresh(self, human: bool = False) -> bool:
        """Ask the game what the events are doing. `False` if it could not be asked now.

        `human` is «Обновить»; the poll and the after-a-press re-reads leave it False,
        so a board nobody is pressing stops asking a client that is not there (#1910).

        A refusal — something else is driving the game — leaves the previous reading and
        its age on screen, which is the honest answer: it is what we know, and how old.
        """
        if self._busy:
            return False
        self._busy = True
        self._refresh_status()
        started = self.rt.play_async(
            modelmod.CODENAME_ACTION, tag="events", human=human,
            on_result=self._read_back, on_done=self._read_done)
        if not started:
            self._busy = False
            self._refresh_status()
        return started

    def refresh_both(self, human: bool = False) -> bool:
        """Take both readings, one after the other rather than both at once.

        Only one scenario may drive the client at a time, so a second read fired beside
        the first is refused outright — and a refusal leaves the old answer on screen,
        which for a board that has never been read means «неизвестно» for ever. So the
        golden reading is hung on the codename one's finish, and taken on its own when
        the codename one could not be started at all.
        """
        self._chain_golden = True
        self._chain_train = True
        self._chain_arms = True
        self._chain_crystal = True
        if self.refresh(human=human):
            return True
        self._chain_golden = False
        return self.refresh_golden(human=human)

    def _read_back(self, outcome) -> None:
        """The scenario finished (on the Tk thread). Its variable IS the board."""
        at = time.time()
        if outcome is None or not getattr(outcome, "ok", False):
            reason = getattr(outcome, "reason", "") or ""
            self._reading = modelmod.Reading(error=reason or "failed", at=at)
        else:
            ctx = getattr(outcome, "ctx", None)
            raw = (getattr(ctx, "vars", {}) or {}).get(modelmod.CODENAME_VARIABLE)
            self._reading = modelmod.parse(raw, at=at)

    def _read_done(self) -> None:
        self._busy = False
        self._render()
        #: …and the OTHER reading, now that the client is free again. The two are
        #: separate scenarios and only one may drive the game at a time — fired
        #: together, the second is refused with «занято» and the board keeps saying
        #: «неизвестно» for ever (#1519).
        if self._chain_golden:
            self._chain_golden = False
            self.refresh_golden()

    # -- the two presses ----------------------------------------------------
    def attack(self) -> bool:
        """Send a squad at the «Кодовое имя» boss. One attack, one press.

        Everything the attack IS lives in `actions/attack_codename_boss.md` — which boss,
        which squad, what to do when the popup does not open. This starts it and re-reads
        the board afterwards; whether the attack counted is the game's answer, not this
        button's.
        """
        return self._play(modelmod.CODENAME_ATTACK, "events.codename.log.sent")

    def daily(self) -> bool:
        """Make the day's attacks — as many as the day still owes, and no more.

        The clock's errand, offered here as a press because a person who has just come
        back to the machine wants it NOW rather than at the top of the next period. What
        «the day still owes» means is the scenario's business
        (`actions/attack_codename_daily.md`): it asks the server what has already been
        made, from whatever hand made it, and sends only the difference — so this press
        is safe to lean on and does nothing at all on a day already played.
        """
        return self._play(modelmod.CODENAME_DAILY, "events.codename.log.daily")

    def _play(self, scenario: str, sent_key: str,
              failed_key: str = "events.codename.log.failed",
              busy_key: str = "events.codename.log.busy",
              after=None) -> bool:
        """Start one of the two, with the sentence its finish will be reported in.

        One press at a time, whichever it is — and that now covers the crystal boss's
        two as well: all four drive the same client and want the same free squad, so a
        second press while one is in flight is refused rather than raced.

        `after` is what to re-read when it ends, because the count that says an attack
        happened is the SERVER's and belongs to whichever event was attacked.
        """
        if self._attacking:
            return False
        self._attacking = True
        self._sent_key = sent_key
        self._failed_key = failed_key
        self._after_press = after
        self._paint_attack_button()
        started = self.rt.play_async(
            scenario, tag="events", human=True,
            on_result=self._attack_back, on_done=self._attack_done)
        if not started:
            self._attacking = False
            self._sent_key = None
            self._after_press = None
            self._paint_attack_button()
            self.say("events", busy_key)
        return started

    def _attack_back(self, outcome) -> None:
        """Say what came of it — the scenario's own words, never a guess of ours."""
        if outcome is not None and getattr(outcome, "ok", False):
            self.say("events", self._sent_key or "events.codename.log.sent")
        else:
            self.say("events", self._failed_key or "events.codename.log.failed",
                     error=(getattr(outcome, "reason", "") or "?"))

    def _attack_done(self) -> None:
        self._attacking = False
        self._sent_key = None
        after, self._after_press = self._after_press, None
        self._paint_attack_button()
        #: Re-read rather than counting the press: the count that matters is the
        #: server's, and it is the only thing that says an attack really went out.
        self.rt.tick.arm("events_after_attack", self.AFTER_ATTACK_MS,
                         after or self.refresh)

    # -- «Золотые зомби»: its reading, its press, its day -------------------
    def refresh_golden(self, human: bool = False) -> bool:
        """Ask the game what the hunt has to work with. `False` if it could not be asked.

        `human` as everywhere on this tab: the button sets it, the poll does not (#1910).

        A refusal — something else is driving the client, usually the chain itself — is
        left showing the previous reading and its age, which is the honest answer.
        """
        if self._golden_busy:
            return False
        self._golden_busy = True
        started = self.rt.play_async(
            modelmod.GOLDEN_ACTION, tag="events", human=human,
            on_result=self._golden_back, on_done=self._golden_done)
        if not started:
            self._golden_busy = False
        return started

    def _golden_back(self, outcome) -> None:
        at = time.time()
        if outcome is None or not getattr(outcome, "ok", False):
            reason = getattr(outcome, "reason", "") or ""
            self._golden = modelmod.Reading(error=reason or "failed", at=at)
        else:
            ctx = getattr(outcome, "ctx", None)
            raw = (getattr(ctx, "vars", {}) or {}).get(modelmod.GOLDEN_VARIABLE)
            self._golden = modelmod.parse(raw, at=at)

    def _golden_done(self) -> None:
        self._golden_busy = False
        self._render()
        #: …and the THIRD reading, for the reason the second one is chained here: only
        #: one scenario may drive the client at a time, and a read fired beside another
        #: is refused outright — which for a card that has never been read means
        #: «неизвестно» for ever.
        if self._chain_train:
            self._chain_train = False
            self.refresh_train()

    # -- «Поезд альянса»: its reading, its two knobs, its one press ---------
    def refresh_train(self, human: bool = False) -> bool:
        """Ask the game what stands at the alliance station. `False` if it could not be asked.

        `human` as everywhere on this tab: the button sets it, the poll does not, so a
        card nobody is pressing stops asking a client that is not there (#1910).
        """
        if self._train_busy:
            return False
        self._train_busy = True
        started = self.rt.play_async(
            modelmod.TRAIN_ACTION, tag="events", human=human,
            on_result=self._train_back, on_done=self._train_done)
        if not started:
            self._train_busy = False
        return started

    def _train_back(self, outcome) -> None:
        at = time.time()
        if outcome is None or not getattr(outcome, "ok", False):
            reason = getattr(outcome, "reason", "") or ""
            self._train = modelmod.Reading(error=reason or "failed", at=at)
        else:
            ctx = getattr(outcome, "ctx", None)
            raw = (getattr(ctx, "vars", {}) or {}).get(modelmod.TRAIN_VARIABLE)
            self._train = modelmod.parse(raw, at=at)

    def _train_done(self) -> None:
        self._train_busy = False
        self._render()
        #: …and the FOURTH reading, chained for the same reason the others are.
        if self._chain_arms:
            self._chain_arms = False
            self.refresh_arms()

    # -- «Гонка вооружений»: the phase, the day, and the one press ----------
    def refresh_arms(self, human: bool = False) -> bool:
        """Ask the game which phase is running and what the day looks like.

        The reading SENDS the calendar get (`actions/read_arms_race.md`), which is what
        makes the day's six borders knowable at all — but it is still one round trip and
        it presses nothing, so it sits on the same clock as the rest of this board.
        """
        if self._arms_busy:
            return False
        self._arms_busy = True
        started = self.rt.play_async(
            modelmod.ARMS_ACTION, tag="events", human=human,
            on_result=self._arms_back, on_done=self._arms_done)
        if not started:
            self._arms_busy = False
        return started

    def _arms_back(self, outcome) -> None:
        at = time.time()
        if outcome is None or not getattr(outcome, "ok", False):
            reason = getattr(outcome, "reason", "") or ""
            self._arms = modelmod.Reading(error=reason or "failed", at=at)
            return
        ctx = getattr(outcome, "ctx", None)
        values = getattr(ctx, "vars", {}) or {}
        self._arms = modelmod.parse(values.get(modelmod.ARMS_VARIABLE), at=at)
        #: The calendar is kept even when the phase itself was unreadable: a day whose
        #: borders are known is worth drawing whatever the current phase says, and the
        #: borders do not go stale — the server fixed them a week ago.
        calendar = modelmod.arms_calendar(values.get(modelmod.ARMS_DAY_VARIABLE))
        if calendar:
            self._arms_cal = calendar

    def _arms_done(self) -> None:
        self._arms_busy = False
        self._render()
        #: …and the last of the chain. Only one scenario may drive the client at a
        #: time, so every reading on this board follows the previous one home rather
        #: than being fired beside it (#1519).
        if self._chain_crystal:
            self._chain_crystal = False
            self.refresh_crystal()

    # -- «Кристальный босс»: its reading and its two presses ----------------
    def refresh_crystal(self, human: bool = False) -> bool:
        """Ask the game what the crystal boss is doing. `False` if it could not be asked.

        The reading SENDS the event's own get before it reads anything
        (`actions/read_crystal_boss.md`): the manager boots with no boss and no counter,
        and answers a panel that has not asked exactly as it would on a day the event
        were shut. That trap cost «Кодовое имя» a whole feature for a day (#1259).
        """
        if self._crystal_busy:
            return False
        self._crystal_busy = True
        started = self.rt.play_async(
            modelmod.CRYSTAL_ACTION, tag="events", human=human,
            on_result=self._crystal_back, on_done=self._crystal_done)
        if not started:
            self._crystal_busy = False
        return started

    def _crystal_back(self, outcome) -> None:
        at = time.time()
        if outcome is None or not getattr(outcome, "ok", False):
            reason = getattr(outcome, "reason", "") or ""
            self._crystal = modelmod.Reading(error=reason or "failed", at=at)
            return
        ctx = getattr(outcome, "ctx", None)
        raw = (getattr(ctx, "vars", {}) or {}).get(modelmod.CRYSTAL_VARIABLE)
        self._crystal = modelmod.parse(raw, at=at)

    def _crystal_done(self) -> None:
        self._crystal_busy = False
        self._render()

    def crystal(self):
        """The crystal card against the last reading — what both front-ends draw."""
        return modelmod.crystal_state(self._crystal)

    def attack_crystal(self) -> bool:
        """Send a squad at the «Кристальный босс». One attack, one press.

        Everything the attack IS lives in `actions/attack_crystal_boss.md` — which boss,
        which squad, and the proof that the server's own count moved. This starts it and
        re-reads the card afterwards.
        """
        return self._play(modelmod.CRYSTAL_ATTACK, "events.crystal.log.sent",
                          failed_key="events.crystal.log.failed",
                          busy_key="events.crystal.log.busy",
                          after=self.refresh_crystal)

    def daily_crystal(self) -> bool:
        """Make the day's three attacks — as many as the day still owes, and no more.

        The clock's errand, offered as a press for the person who has just come back to
        the machine. What «still owes» means is the scenario's business: it asks the
        server what has already been made, from whatever hand made it, so this is safe to
        lean on and does nothing at all on a day already played.
        """
        return self._play(modelmod.CRYSTAL_DAILY, "events.crystal.log.daily",
                          failed_key="events.crystal.log.failed",
                          busy_key="events.crystal.log.busy",
                          after=self.refresh_crystal)

    def arms(self):
        """The arms card against the last reading — what both front-ends draw."""
        return modelmod.arms_state(self._arms, self._arms_cal)

    def arms_hero(self) -> bool:
        """May the errand's hero phase hire? The widget wins while the tab is drawn."""
        if self._arms_hero_var is not None:
            try:
                return bool(self._arms_hero_var.get())
            except tk.TclError:            # the window is going away
                pass
        return bool(self._arms_hero)

    def set_arms_option(self, key: str, value) -> bool:
        """The gear on «Таймеры» writing this card's own knob (`CLAUDE.md`)."""
        return bool(self.web_press("set", {"key": key, "value": value}).get("ok"))

    def play_arms(self, action: str) -> bool:
        """Play the errand by hand, or the hero phase on its own.

        Both are scenarios and both hold their own gates — the ceiling, the phase kind,
        whether the tickets cover a hire — so the panel does not re-decide any of that
        here (`CLAUDE.md`). What it does is refuse to start a SECOND one on top of the
        first, which is a fact about this tab and not about the game.
        """
        if self._arms_running:
            return False
        self._arms_running = True
        # THE SAME ARGS THE SCHEDULE FIRES WITH, whichever of the two is played. The
        # drone recipe raises nothing without a rally allowance, and a press that left
        # it out would look like a press that did not work — the ceilings belong to the
        # ability and the numbers come from here (`CLAUDE.md`).
        started = self.rt.play_async(action, self.arms_args(), tag="events", human=True,
                                     on_done=self._arms_played)
        if not started:
            self._arms_running = False
        return started

    def _arms_played(self) -> None:
        self._arms_running = False
        self.rt.tick.arm("events_after_arms", self.AFTER_ATTACK_MS, self.refresh_arms)

    def train(self):
        """The train card against the last reading — what both front-ends draw."""
        return modelmod.train_state(self._train)

    def carriage(self) -> int:
        """Which carriage the standing order queues in."""
        return modelmod.carriage_of(self._train_carriage)

    def tickets(self) -> int:
        """What the standing order offers the conductor — `0` is the free like."""
        return modelmod.tickets_of(self._train_tickets)

    def buy_missing(self) -> bool:
        """May a short fare be made up out of diamonds? Off unless somebody said so."""
        return bool(self._train_buy)

    def board_train(self) -> bool:
        """Press «Сесть в вагон» — one scenario, and then the card re-reads itself.

        A press that STARTS something, which is the ordinary and wanted kind: the rows
        above it move when the READING moves, and a run that boarded nothing leaves them
        exactly where they were (`CLAUDE.md`). Everything the ability IS — whether there
        is a conductor, whether we are aboard already, whether the fare has been paid and
        how much of it the bag can afford — lives in the recipe, which is also what the
        wire trigger plays.
        """
        if self._train_boarding:
            self.say("events", "events.train.log.busy")
            return False
        self._train_boarding = True
        started = self.rt.play_async(
            modelmod.TRAIN_BOARD, self.train_args(), tag="events", human=True,
            on_result=self._board_back, on_done=self._board_done)
        if not started:
            self._train_boarding = False
            self.say("events", "events.train.log.busy")
        return started

    def _board_back(self, outcome) -> None:
        """Say what came of it — the recipe's own reason, never a guess of ours."""
        if outcome is not None and getattr(outcome, "ok", False):
            self.say("events", "events.train.log.done")
        else:
            self.say("events", "events.train.log.failed",
                     error=(getattr(outcome, "reason", "") or "?"))

    def _board_done(self) -> None:
        self._train_boarding = False
        #: Re-read rather than counting the press: whether we are really in a carriage
        #: and whether the fare really left is the game's answer, not this button's.
        self.rt.tick.arm("events_after_board", self.AFTER_ATTACK_MS, self.refresh_train)

    def golden(self):
        """The golden group against the last reading — what both front-ends draw."""
        return modelmod.golden_state(self._golden)

    def squad(self) -> int:
        """Which squad the chain sends, from the widget when there is one.

        The widget is the setting while the tab is drawn and the saved value is the
        setting when it is not — the same rule «Таймеры» settled on
        (`docs/panel-tabs.md`).
        """
        if self._squad_var is not None:
            try:
                return modelmod.squad_of(self._squad_var.get())
            except tk.TclError:            # the window is going away
                pass
        return modelmod.squad_of(self._squad)

    def _set_golden_squad(self, wanted: int) -> dict:
        """Pick the squad the hunt sends — a SETTING, and it presses nothing (#2062).

        The window's drop-down and the phone's picker are two drawings of one value, so
        both end here and the tab is saved by its own trace.
        """
        if wanted not in modelmod.GOLDEN_SQUADS:
            return {"error": "unknown"}
        self._squad = wanted
        if self._squad_var is not None:
            try:
                self._squad_var.set(str(wanted))
            except tk.TclError:             # the window is going away
                pass
        self.rt.settings.changed()
        return {"ok": True, "squad": wanted}

    def approach(self) -> bool:
        """Is the fast approach on? The widget while the tab is drawn, the saved value else."""
        if self._approach_var is not None:
            try:
                return bool(self._approach_var.get())
            except tk.TclError:            # the window is going away
                pass
        return bool(self._approach)

    #: The chain taken apart into presses — one step each, so a person can press one
    #: and look at what happened before pressing the next (#1702). The operator asked for
    #: exactly this: «не просто "бить зомби", а по этапам». Every one of them is a
    #: scenario played through `run_action`, like every other button in this panel.
    STEPS = (("find_golden", "golden_find_target", "events.golden.step.find"),
             ("attack_golden", "golden_attack_target", "events.golden.step.attack"),
             ("recall_golden", "golden_recall_squad", "events.golden.step.recall"),
             ("state_golden", "golden_squad_report", "events.golden.step.state"),
             ("goto_golden", "golden_goto_target", "events.golden.step.goto"),
             ("forget_golden", "golden_forget_target", "events.golden.step.forget"),
             ("rescan_golden", "scan_map", "events.golden.step.rescan"))

    def _step_back(self, outcome) -> None:
        """Keep what a step FOUND, when it found anything.

        Only one of them reports a place: «найти ближайшего» parks the tile it chose, and
        the card shows it until the next press changes it. Everything else a step has to
        say is already in the log, which both front-ends draw.
        """
        ctx = getattr(outcome, "ctx", None)
        where = (getattr(ctx, "vars", {}) or {}).get("where")
        if where:
            self._golden_target = str(where)
            self._paint_target()
        # …AND WHAT FOLLOWS A PRESS FOLLOWS ITS END, NOT A STOPWATCH (#1702). The
        # camera flight after «найти» was armed 300 ms after the press and refused every
        # single time — «занят — дождись завершения текущего действия», because the find
        # itself was still holding the client. From the outside that is a button that
        # prints a coordinate and does nothing, which is exactly what was reported.
        if self._step_ran == "find_golden" and getattr(outcome, "ok", False):
            self._after(200, "golden_goto_target")
        self._step_ran = ""
        self._step_said = self._outcome_key(outcome)
        if str(getattr(outcome, "reason", "") or "") == "target gone":
            # The card must not go on naming a tile the game says is empty (#1702).
            self._golden_target = ""
            self._paint_target()
        self._paint_step()

    #: What a step's own halt reason means, in words a person reads. The scenarios stop
    #: with these exact strings; anything else is shown as the run's own text.
    SAID = {"target gone": "events.golden.said.gone",
            "no army": "events.golden.said.noarmy",
            "squad busy": "events.golden.said.busy",
            "nothing chosen": "events.golden.said.none",
            "no target": "events.golden.said.empty",
            "no squad": "events.golden.said.nosquad"}

    def _outcome_key(self, outcome) -> str:
        """The line to show beside the buttons after a press. Empty when it went well."""
        if outcome is not None and getattr(outcome, "ok", False):
            return "events.golden.said.ok"
        reason = str(getattr(outcome, "reason", "") or "").strip()
        return self.SAID.get(reason, "events.golden.said.failed")

    def _paint_step(self) -> None:
        """Put the last press's answer in the row of buttons."""
        var = getattr(self, "_step_var", None)
        if var is None:
            return
        try:
            var.set(self.t(self._step_said) if self._step_said else "")
        except tk.TclError:                 # the window is going away
            pass

    def _retry_soon(self, delay_ms: int = 1500) -> None:
        """Try the waiting presses again shortly, until they go in.

        A second and a half rather than a fraction of one: a press waits behind whatever
        is driving the client — a timer, the auto-rally, another tab's poll — and those
        last seconds, not milliseconds. Retrying faster only fills the log with «занято»
        (live, twelve refusals in seven seconds) without the press going in any sooner.
        """
        tick = getattr(self.rt, "tick", None)
        if tick is None or not hasattr(tick, "arm"):
            return
        try:
            tick.arm("golden-queue", delay_ms, self._drain_waiting)
        except Exception:                   # noqa: BLE001 — a panel going down
            pass

    def _drain_waiting(self) -> None:
        """Play whatever is still waiting; keep the ones the client is still busy for."""
        if not self._waiting:
            return
        for action in list(self._waiting):
            self._waiting.pop(action, None)
            if not self.step(action):       # step() re-queues it if it is refused again
                self._waiting[action] = True
        if self._waiting:
            self._retry_soon()

    def _after(self, delay_ms: int, scenario: str) -> None:
        """Play a scenario in a moment, on the panel's own clock.

        Two of the step presses answer before their last act is done — the find has its
        coordinate before the camera flies there, and the attack has its order away
        before the client draws the march. Holding the button open for either is time
        the person spends looking at work that is finished (#1702).
        """
        tick = getattr(self.rt, "tick", None)
        if tick is None or not hasattr(tick, "arm"):
            return
        try:
            tick.arm("golden-after", delay_ms,
                     lambda: self.rt.play_async(scenario, tag="events",
                                                priority=claims.BACKGROUND,
                                                on_result=self._step_back))
        except Exception:                   # noqa: BLE001 — a panel going down
            pass

    def _verify_after(self, delay_ms: int) -> None:
        """Ask, a few seconds on, whether the last order became a real march."""
        self._after(delay_ms, "golden_verify_order")

    def _paint_target(self) -> None:
        """Put the chosen tile beside the buttons — where the operator asked for it.

        The log makes a coordinate clickable wherever it appears, but the log is a
        different part of the window from the presses, and «найти» and «атаковать» are
        pressed together (#1702). So the tile sits in the row of buttons, and clicking it
        flies there — the same flight «Перейти к выбранному» plays, because there is only
        ever one way to do a thing in this panel.
        """
        var = getattr(self, "_target_var", None)
        if var is None:
            return
        try:
            var.set(self._golden_target or self.t("events.golden.target.none"))
        except tk.TclError:                 # the window is going away
            pass

    def step(self, action: str) -> bool:
        """Play one step of the hunt. The log is where its answer lands, on purpose.

        A step reports in words — which zombie was chosen and how far, what the game did
        with the order, what the squads are doing — and words belong in the log, which
        both the window and the phone already show. Nothing here keeps a second copy of
        the game's state.
        """
        row = next((r for r in self.STEPS if r[0] == action), None)
        if row is None:
            return False
        self._step_ran = action
        args = {"squad": self.squad()}
        if row[1] == "scan_map":
            args = {}
        elif row[1] == "golden_attack_target":
            args["approach"] = 1 if self.approach() else 0
        if action == "attack_golden":
            # THE PROOF FOLLOWS THE PRESS (#1702). The order is scheduled inside one call
            # and the press answers at once; four seconds later the panel asks whether it
            # became a real march and recalls it if the server never confirmed one. The
            # person gets their button back immediately and hears about a phantom a
            # moment later — instead of watching a spinner for the good news.
            self._verify_after(4000)
        if action == "forget_golden":
            # Shown as forgotten the moment it is asked for: the scenario cannot fail in
            # a way that leaves a target chosen, and a card still naming one would be
            # the panel disagreeing with the game about something the person just did.
            self._golden_target = ""
            self._paint_target()
        started = bool(self.rt.play_async(row[1], args, tag="events", human=True,
                                          on_result=self._step_back))
        if started:
            self._waiting.pop(action, None)
            return True
        # THE PRESS IS NOT LOST (#1702). Something else is driving the client — a timer,
        # the auto-rally, the press before this one — and the operator's rule is that a
        # button pressed is a button obeyed: «нажал — будет выполнено». So it waits its
        # turn and says so, and the newest press of the same button replaces the one
        # waiting rather than piling up behind it.
        self._waiting[action] = True
        self._step_said = "events.golden.said.queued"
        self._paint_step()
        self._retry_soon()
        return True

    def hunt(self) -> bool:
        """Start the chain: scan the map, then attack until the energy runs out.

        Everything the hunt IS lives in `actions/attack_golden_zombies.md` — which
        zombie, how near is near, when to stop. This starts it with the chosen squad and
        files what it reports; whether an attack counted is the SERVER's answer (the
        energy it charged), never this button's.
        """
        if self._golden_running:
            self.say("events", "events.golden.log.busy")
            return False
        self._golden_running = True
        self._paint_golden_button()
        started = self.rt.play_async(
            modelmod.GOLDEN_ATTACK,
            {"squad": self.squad(), "approach": 1 if self.approach() else 0},
            tag="events", human=True,
            on_result=self._hunt_back, on_done=self._hunt_done)
        if not started:
            self._golden_running = False
            self._paint_golden_button()
            self.say("events", "events.golden.log.busy")
        return started

    def _hunt_back(self, outcome) -> None:
        """File the run's own report, and say what came of it in the run's own words."""
        report = {}
        ctx = getattr(outcome, "ctx", None)
        raw = (getattr(ctx, "vars", {}) or {}).get("golden_report")
        if raw:
            report = goldmod.parse_report(raw)
        self._golden_lap = int(report.get("lap", 0) or 0)
        self._golden_lap_last = int(report.get("laplast", 0) or 0)
        if outcome is not None and getattr(outcome, "ok", False):
            self._file_run(report)
            self.say("events", "events.golden.log.done",
                     attacks=report.get("attacks", 0), spent=report.get("spent", 0),
                     found=report.get("found", 0))
        else:
            self.say("events", "events.golden.log.failed",
                     error=(getattr(outcome, "reason", "") or "?"))

    def _hunt_done(self) -> None:
        self._golden_running = False
        self._paint_golden_button()
        #: Re-read rather than counting the press: the purse is the game's, and it is the
        #: only thing that says what the chain really spent.
        self.rt.tick.arm("events_after_hunt", self.AFTER_ATTACK_MS, self.refresh_golden)

    def _file_run(self, report: dict) -> None:
        """Fold one finished run into the day's row in `panel.db`.

        A run that sent nothing still counts as a run — that is a fact about the day
        worth keeping — but adds no attacks and no energy, because it made neither.
        """
        try:
            days = goldmod.add_run(self._days(), report)
            goldmod.save(self.rt.store, days)
            self._tally = days
        except Exception as exc:                # noqa: BLE001 — a store that is closing
            self.rt.dbg("events").warning("golden tally not stored: %s", exc)

    def _days(self) -> dict:
        """The tally, read out of the database the first time anybody wants it."""
        if self._tally is None:
            try:
                self._tally = goldmod.load(self.rt.store)
            except Exception:                   # noqa: BLE001 — a store that is closing
                self._tally = {}
        return self._tally

    def today(self) -> dict:
        """Today's row of the tally — zeros on a day this panel has sent nothing."""
        return goldmod.day_row(self._days())

    # -- the board ----------------------------------------------------------
    def codename(self):
        """The codename group against the last reading — what both front-ends draw."""
        return modelmod.codename_state(self._reading)

    def _render(self) -> None:
        if self._body is None:
            return
        self._attack_button = None
        self._daily_button = None
        for child in list(self._body.winfo_children()):
            child.destroy()
        for group in modelmod.GROUPS:
            if group.key == modelmod.CODENAME:
                self._render_codename(group)
            elif group.key == modelmod.GOLDEN:
                self._render_golden(group)
            elif group.key == modelmod.FIREWORKS:
                self._render_fireworks(group)
            elif group.key == modelmod.ARMS:
                self._render_arms(group)
        self._refresh_status()

    def _render_codename(self, group) -> None:
        """«Кодовое имя»: the heading, the state, the two numbers and the press."""
        state = self.codename()
        grey = _GREY if state.state != modelmod.OPEN else _LIVE

        head = ttk.Frame(self._body)
        head.pack(fill="x", padx=6, pady=(10, 2))
        glyph, colour = _GLYPH.get(state.state, _GLYPH[modelmod.UNKNOWN])
        ttk.Label(head, text=glyph, foreground=colour, width=2).pack(side="left")
        self.tr(ttk.Label(head, font=ui_font(weight="bold"),
                          foreground=grey or "#000000"), group.title_key).pack(side="left")
        ttk.Label(head, text=self._state_words(state), foreground=_GREY).pack(
            side="left", padx=(10, 0))

        rows = ttk.Frame(self._body)
        rows.pack(fill="x", padx=4, pady=(0, 2))
        self._row(rows, "events.codename.attacks", modelmod.counter(state), grey)
        self._row(rows, "events.codename.damage", modelmod.damage(state.damage), grey)
        if state.state == modelmod.OPEN:
            self._row(rows, "events.codename.until", modelmod.hhmm(state.seconds), grey)

        press = ttk.Frame(self._body)
        press.pack(fill="x", padx=28, pady=(4, 2))
        self._attack_button = self.tr(ttk.Button(press, command=self.attack),
                                      "events.codename.attack")
        self._attack_button.pack(side="left")
        self.tr(ttk.Label(press, foreground=_GREY),
                "events.codename.attack.hint").pack(side="left", padx=(10, 0))

        # …and the day's worth, the same errand the clock plays once a day. Beside the
        # single attack rather than instead of it: the day's three earn the reward, and
        # anything past them buys a better damage ranking one march at a time.
        daily = ttk.Frame(self._body)
        daily.pack(fill="x", padx=28, pady=(0, 6))
        self._daily_button = self.tr(ttk.Button(daily, command=self.daily),
                                     "events.codename.daily")
        self._daily_button.pack(side="left")
        self.tr(ttk.Label(daily, foreground=_GREY),
                "events.codename.daily.hint").pack(side="left", padx=(10, 0))
        self._paint_attack_button()

    def _render_golden(self, group) -> None:
        """«Золотые зомби»: the heading, the readings, the squad and the one press."""
        state = self.golden()
        grey = _GREY if state.state != modelmod.OPEN else _LIVE

        head = ttk.Frame(self._body)
        head.pack(fill="x", padx=6, pady=(14, 2))
        glyph, colour = _GLYPH.get(state.state, _GLYPH[modelmod.UNKNOWN])
        ttk.Label(head, text=glyph, foreground=colour, width=2).pack(side="left")
        self.tr(ttk.Label(head, font=ui_font(weight="bold"),
                          foreground=grey or "#000000"), group.title_key).pack(side="left")
        ttk.Label(head, text=self._golden_words(state), foreground=_GREY).pack(
            side="left", padx=(10, 0))

        rows = ttk.Frame(self._body)
        rows.pack(fill="x", padx=4, pady=(0, 2))
        self._row(rows, "events.golden.energy", modelmod.energy(state), grey)
        self._row(rows, "events.golden.affordable", modelmod.affordable(state), grey)
        self._row(rows, "events.golden.seen", modelmod.seen(state), grey)
        self._row(rows, "events.golden.speed", modelmod.speed(state), grey)
        self._row(rows, "events.golden.today", modelmod.tally(self.today()), grey)

        # The one thing on this board a person SETS. A slot, because a slot is what the
        # game shows them — the formation uuid the send needs is the scenario's business
        # and is looked up there (docs/research/rally-squad-identity.md).
        pick = ttk.Frame(self._body)
        pick.pack(fill="x", padx=28, pady=(6, 2))
        self.tr(ttk.Label(pick), "events.golden.squad").pack(side="left")
        # The choice survives a redraw: the widget is remade on every language change
        # and every reading, and a `set()` that did not read the widget first would put
        # the saved value back over what the person had just picked.
        self._squad = self.squad()
        if self._squad_var is None:
            self._squad_var = tk_stringvar(self.rt.root)
        self._squad_var.set(str(self._squad))
        ttk.Combobox(pick, textvariable=self._squad_var, width=4, state="readonly",
                     values=[str(n) for n in modelmod.GOLDEN_SQUADS]).pack(
                         side="left", padx=(8, 0))

        # …and whether the long haul is ridden on a gather order first. It is a choice
        # about how the chain travels, so it sits beside the squad rather than in the
        # scenario's defaults.
        if self._approach_var is None:
            self._approach_var = statevar.boolean(self.rt.root)
        self._approach = self.approach()
        self._approach_var.set(self._approach)
        self.tr(ttk.Checkbutton(pick, variable=self._approach_var),
                "events.golden.approach").pack(side="left", padx=(16, 0))

        press = ttk.Frame(self._body)
        press.pack(fill="x", padx=28, pady=(4, 8))
        self._golden_button = self.tr(ttk.Button(press, command=self.hunt),
                                      "events.golden.hunt")
        self._golden_button.pack(side="left")
        self.tr(ttk.Label(press, foreground=_GREY),
                "events.golden.hunt.hint").pack(side="left", padx=(10, 0))
        self._paint_golden_button()

        # …and the same chain taken apart, one press per step (#1702). The phone draws
        # the same five out of `STEPS`, so neither front-end can grow a step the other
        # does not have (CLAUDE.md, «An edit travels between the window and the web»).
        steps = ttk.Frame(self._body)
        steps.pack(fill="x", padx=28, pady=(0, 8))
        for action, _scenario, key in self.STEPS:
            self.tr(ttk.Button(steps, command=lambda a=action: self.step(a)),
                    key).pack(side="left", padx=(0, 6))

        # …and the tile that was found, in the same row as the presses and clickable:
        # the panel's own coordinate token, and a click is the flight (#1702).
        if self._target_var is None:
            self._target_var = tk_stringvar(self.rt.root)
        self._paint_target()
        link = ttk.Label(steps, textvariable=self._target_var, foreground="#1a6fb5",
                         cursor="hand2")
        link.pack(side="left", padx=(12, 0))
        link.bind("<Button-1>", lambda _e: self.step("goto_golden"))

        # …and what the last press answered, in the same row. A scenario that refuses
        # says why in the log; this is the same sentence where the finger is (#1702).
        if self._step_var is None:
            self._step_var = tk_stringvar(self.rt.root)
        self._paint_step()
        ttk.Label(steps, textvariable=self._step_var, foreground=_GREY).pack(
            side="left", padx=(12, 0))

    # -- «Салют» -------------------------------------------------------------
    def fireworks(self) -> dict:
        """This profile's firework book, as numbers. Never asks the game anything.

        The book hangs off the runtime and is filled by the ear, so it answers on a
        profile with no window open on this tab and on one with no game running at all —
        which is the whole reason it lives there and not here.
        """
        book = getattr(self.rt, "fireworks", None)
        if book is None:
            return {}
        try:
            return dict(book.tally())
        except Exception:                       # noqa: BLE001 — a reading, never the tab
            return {}

    def fireworks_days(self, limit: int = 7) -> list:
        book = getattr(self.rt, "fireworks", None)
        if book is None:
            return []
        try:
            return list(book.history(limit))
        except Exception:                       # noqa: BLE001 — a reading, never the tab
            return []

    def collect_fireworks(self) -> bool:
        """Press «Забрать сейчас» — one scenario, and then the block re-reads itself.

        A press that STARTS something, which is the ordinary and wanted kind: the row
        above it moves when the READING moves, and a run that took nothing leaves it
        exactly where it was (`CLAUDE.md`).
        """
        started = self.rt.play_async("collect_fireworks", tag="events", human=True,
                                     on_done=lambda: self.post(self._render))
        if not started:
            self.say("events", "events.codename.log.busy")
        return started

    def _render_fireworks(self, group) -> None:
        """«Салют»: what the ear heard, what actually arrived, and when.

        No state glyph and no «открыто / закрыто»: a firework is not a window in the day,
        it is somebody else lighting one, and the honest heading is the count of what has
        been heard today.
        """
        tally = self.fireworks()
        heard = int(tally.get("heard") or 0)
        grey = _LIVE if heard else _GREY

        head = ttk.Frame(self._body)
        head.pack(fill="x", padx=6, pady=(10, 2))
        glyph, colour = _GLYPH.get(modelmod.OPEN if heard else modelmod.UNKNOWN,
                                   _GLYPH[modelmod.UNKNOWN])
        ttk.Label(head, text=glyph, foreground=colour, width=2).pack(side="left")
        self.tr(ttk.Label(head, font=ui_font(weight="bold"),
                          foreground=grey or "#000000"), group.title_key).pack(side="left")

        rows = ttk.Frame(self._body)
        rows.pack(fill="x", padx=4, pady=(0, 2))
        self._row(rows, "events.fireworks.today", str(int(tally.get("taken") or 0)), grey)
        self._row(rows, "events.fireworks.heard", str(heard), grey)
        self._row(rows, "events.fireworks.last",
                  modelmod.when(tally.get("last_ts") or 0.0), grey)
        self._row(rows, "events.fireworks.react",
                  modelmod.reaction(tally.get("react_last", -1),
                                    tally.get("react_best", -1)), grey)
        self._row(rows, "events.fireworks.refused",
                  str(int(tally.get("refused") or 0)), grey)
        self._row(rows, "events.fireworks.month",
                  str(int(tally.get("taken_all") or 0)), grey)

        days = self.fireworks_days()
        if days:
            hist = ttk.Frame(self._body)
            hist.pack(fill="x", padx=4, pady=(2, 2))
            self.tr(ttk.Label(hist, foreground=_GREY), "events.fireworks.history").pack(
                anchor="w", padx=22)
            for row in days:
                line = ttk.Frame(hist)
                line.pack(fill="x", padx=22, pady=1)
                line.columnconfigure(0, weight=1)
                ttk.Label(line, text=row["day"], foreground=_GREY).grid(
                    row=0, column=0, sticky="w")
                ttk.Label(line, text=str(row["taken"]), font=ui_font(weight="bold"),
                          foreground=_GREY).grid(row=0, column=1, sticky="e", padx=(8, 8))

        press = ttk.Frame(self._body)
        press.pack(fill="x", padx=28, pady=(4, 6))
        self.tr(ttk.Button(press, command=self.collect_fireworks),
                "events.fireworks.collect").pack(side="left")
        self.tr(ttk.Label(press, foreground=_GREY),
                "events.fireworks.collect.hint").pack(side="left", padx=(10, 0))

    def _arms_kind_words(self, kind) -> str:
        """The phase's name, or its bare id when the server invents a sixth kind.

        A kind nobody has a name for is drawn as its NUMBER rather than as «неизвестно»:
        the number is what the log and the research will call it, and it is the one thing
        that lets a person say which phase they were looking at.
        """
        if kind is None:
            return "—"
        key = modelmod.ARMS_KINDS.get(kind)
        return self.t(key) if key else str(kind)

    def _render_arms(self, group) -> None:
        """«Гонка вооружений»: the phase running now, the day's six, and the presses."""
        state = self.arms()
        grey = _GREY if state.state != modelmod.OPEN else _LIVE

        head = ttk.Frame(self._body)
        head.pack(fill="x", padx=6, pady=(10, 2))
        glyph, colour = _GLYPH.get(state.state, _GLYPH[modelmod.UNKNOWN])
        ttk.Label(head, text=glyph, foreground=colour, width=2).pack(side="left")
        self.tr(ttk.Label(head, font=ui_font(weight="bold"),
                          foreground=grey or "#000000"), group.title_key).pack(side="left")
        ttk.Label(head, text=self._state_words(state), foreground=_GREY).pack(
            side="left", padx=(10, 0))

        rows = ttk.Frame(self._body)
        rows.pack(fill="x", padx=4, pady=(0, 2))
        self._row(rows, "events.arms.phase", self._arms_kind_words(state.kind), grey)
        self._row(rows, "events.arms.points", modelmod.arms_points(state), grey)
        self._row(rows, "events.arms.chests", modelmod.arms_chests(state), grey)
        self._row(rows, "events.arms.day_chests", modelmod.arms_day_chests(state), grey)
        self._row(rows, "events.arms.day",
                  "—" if state.done is None else "%d / 6" % state.done, grey)
        if state.state == modelmod.OPEN:
            self._row(rows, "events.arms.until", modelmod.hhmm(state.seconds), grey)

        # THE DAY, WHICH IS THE WHOLE REASON THE READING SENDS THE CALENDAR GET. Six
        # lines: the window in the reader's own clock and what that phase pays for. The
        # one running now is drawn live and the rest grey, so «what is on at four» is a
        # glance rather than a trip into the game.
        if state.phases:
            plan = ttk.Frame(self._body)
            plan.pack(fill="x", padx=4, pady=(2, 2))
            self.tr(ttk.Label(plan, foreground=_GREY), "events.arms.calendar").pack(
                anchor="w", padx=22)
            for stage, kind, start, end in state.phases:
                live = (state.stage is not None and stage == state.stage
                        and state.state == modelmod.OPEN)
                tint = _LIVE if live else _GREY
                line = ttk.Frame(plan)
                line.pack(fill="x", padx=22, pady=1)
                line.columnconfigure(0, weight=1)
                ttk.Label(line, text=modelmod.arms_phase_clock(start, end),
                          foreground=tint or "#000000").grid(row=0, column=0, sticky="w")
                ttk.Label(line, text=self._arms_kind_words(kind),
                          font=ui_font(weight="bold" if live else "normal"),
                          foreground=tint or "#000000").grid(row=0, column=1, sticky="e",
                                                             padx=(8, 8))

        # WHETHER THE FOUR-HOURLY RUN MAY HIRE. A standing order and not a press: the
        # errand fires on the phase border, which is the one minute in four hours when
        # nobody is at the machine.
        if self._arms_hero_var is None:
            self._arms_hero_var = statevar.boolean(self.rt.root)
        self._arms_hero = self.arms_hero()
        self._arms_hero_var.set(self._arms_hero)
        knob = ttk.Frame(self._body)
        knob.pack(fill="x", padx=28, pady=(4, 0))
        self.tr(ttk.Checkbutton(knob, variable=self._arms_hero_var),
                "events.arms.hero").pack(side="left")
        if self._arms_drone_var is None:
            self._arms_drone_var = statevar.boolean(self.rt.root)
        self._arms_drone = self.arms_drone()
        self._arms_drone_var.set(self._arms_drone)
        self.tr(ttk.Checkbutton(knob, variable=self._arms_drone_var),
                "events.arms.drone").pack(side="left", padx=(16, 0))
        self.tr(ttk.Label(knob, foreground=_GREY),
                "events.arms.stamina").pack(side="left", padx=(16, 0))
        ttk.Label(knob, text=str(self.arms_stamina()),
                  font=ui_font(weight="bold")).pack(side="left", padx=(6, 0))

        press = ttk.Frame(self._body)
        press.pack(fill="x", padx=28, pady=(4, 6))
        self.tr(ttk.Button(press, command=lambda: self.play_arms(modelmod.ARMS_ERRAND)),
                "events.arms.play").pack(side="left")
        play = modelmod.ARMS_PLAYS.get(state.kind)
        if play is not None:
            if state.kind == modelmod.ARMS_HERO:
                phase_key = "events.arms.hire"
            elif state.kind in modelmod.ARMS_MINUTE_KINDS:
                phase_key = "events.arms.spend"
            elif state.kind == modelmod.ARMS_UNIT:
                phase_key = "events.arms.train"
            else:
                phase_key = "events.arms.raise"
            self.tr(ttk.Button(press, command=lambda: self.play_arms(play)),
                    phase_key).pack(side="left", padx=(8, 0))
        else:
            # A PHASE WITH NO RECIPE GETS NO BUTTON, and the reason is said out loud
            # rather than left as an absence: the other four phases spend the player's
            # own speed-ups, drone data or troops and their ceilings have not been
            # agreed. A button there would report success for doing nothing.
            self.tr(ttk.Label(press, foreground=_GREY),
                    "events.arms.no_recipe").pack(side="left", padx=(8, 0))

    def _arms_knob_saved(self) -> None:
        """The switch moved — ask for the profile to be written, both front-ends alike."""
        try:
            self.remember({modelmod.ARMS_HERO_KEY: self.arms_hero(),
                           modelmod.ARMS_DRONE_KEY: self.arms_drone(),
                           modelmod.ARMS_STAMINA_KEY: self.arms_stamina(),
                           modelmod.ARMS_SPEEDUP_KEY: self.arms_speedup(),
                           modelmod.ARMS_MINUTES_KEY: self.arms_minutes(),
                           modelmod.ARMS_UNITS_KEY: self.arms_units(),
                           modelmod.ARMS_SOLDIERS_KEY: self.arms_soldiers(),
                           modelmod.ARMS_FREE_MINUTES_KEY: self.arms_free_minutes(),
                           modelmod.ARMS_SQUAD_KEY: self.arms_squad()})
        except Exception as exc:                # noqa: BLE001 — a profile going away
            self.rt.dbg("events").warning("arms knob not saved: %s", exc)

    def _paint_golden_button(self) -> None:
        """Dead while a chain is on its way, and while the purse cannot pay for one march."""
        try:
            alive = self.golden().can_attack and not self._golden_running
            if self._golden_button is not None:
                self._golden_button.configure(state=("normal" if alive else "disabled"))
        except tk.TclError:                 # the window is going away
            pass

    def _golden_words(self, state) -> str:
        if state.state == modelmod.OPEN:
            return self.t("events.golden.state.open")
        if state.state == modelmod.CLOSED:
            return self.t("events.golden.state.closed")
        return self.t("events.state.unknown")

    def _train_words(self, state) -> str:
        if state.state == modelmod.OPEN:
            return self.t("events.train.state.open")
        if state.state == modelmod.CLOSED:
            return self.t("events.train.state.closed")
        return self.t("events.state.unknown")

    def _train_platform_words(self, state) -> str:
        """What stands at the platform, in words: the game's own four states."""
        table = {modelmod.TRAIN_NO_TRAIN: "events.train.platform.none",
                 modelmod.TRAIN_NO_DRIVER: "events.train.platform.nodriver",
                 modelmod.TRAIN_WITH_DRIVER: "events.train.platform.driver",
                 modelmod.TRAIN_WITH_PASSENGER: "events.train.platform.riding"}
        key = table.get(state.platform)
        return self.t(key) if key else self.t("events.state.unknown")

    def _train_fare_words(self, state) -> str:
        """Has the fare been paid for this train? The GAME's answer, never a tally here."""
        if state.thanked is None:
            return "—"
        return self.t("events.train.fare." + ("paid" if state.thanked else "open"))

    def _row(self, parent, label_key: str, value: str, grey: str) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=22, pady=1)
        frame.columnconfigure(0, weight=1)
        self.tr(ttk.Label(frame, foreground=grey or "#000000"), label_key).grid(
            row=0, column=0, sticky="w")
        ttk.Label(frame, text=value, font=ui_font(weight="bold"),
                  foreground=grey or "#000000").grid(row=0, column=1, sticky="e",
                                                     padx=(8, 8))

    def _paint_attack_button(self) -> None:
        """Both presses: dead while one is on its way, and while the event is shut.

        The same gate for the two of them — the day's errand cannot send an attack the
        single press cannot send either, and a button that looks alive on a Sunday only
        buys the person a failure to read.
        """
        try:
            alive = self.codename().can_attack and not self._attacking
            for button in (self._attack_button, self._daily_button):
                if button is not None:
                    button.configure(state=("normal" if alive else "disabled"))
        except tk.TclError:                 # the window is going away
            pass

    def _state_words(self, state) -> str:
        if state.state == modelmod.OPEN:
            return self.t("events.state.open")
        if state.state == modelmod.CLOSED:
            return self.t("events.state.closed")
        return self.t("events.state.unknown")

    def _refresh_status(self) -> None:
        if self._status is None:
            return
        try:
            self._status.set(self._status_text())
        except tk.TclError:                 # the window is going away
            pass

    def _status_text(self) -> str:
        if self._busy:
            return self.t("events.status.reading")
        if self._reading is None:
            return self.t("events.status.never")
        if self._reading.error:
            return self.t("events.status.error", error=self._reading.error)
        return self.t("events.status.read", ago=modelmod.ago(self._age()))

    # -- what this tab saves ------------------------------------------------
    def config(self) -> dict:
        """The one setting on this board: which squad the golden-zombie chain sends.

        Read through :meth:`squad` so the widget wins while the tab is drawn and the
        restored value answers when it is not — a tab nobody has opened must still hand
        back what it was given (`docs/panel-tabs.md`).
        """
        return {modelmod.ARMS_HERO_KEY: self.arms_hero(),
                modelmod.ARMS_DRONE_KEY: self.arms_drone(),
                modelmod.ARMS_STAMINA_KEY: self.arms_stamina(),
                modelmod.ARMS_SPEEDUP_KEY: self.arms_speedup(),
                modelmod.ARMS_MINUTES_KEY: self.arms_minutes(),
                modelmod.ARMS_SQUAD_KEY: self.arms_squad(),
                modelmod.GOLDEN_SQUAD_KEY: self.squad(),
                modelmod.GOLDEN_APPROACH_KEY: self.approach(),
                modelmod.TRAIN_CARRIAGE_KEY: self.carriage(),
                modelmod.TRAIN_TICKETS_KEY: self.tickets(),
                modelmod.TRAIN_BUY_KEY: self.buy_missing()}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._arms_hero = bool(raw.get(modelmod.ARMS_HERO_KEY,
                                       modelmod.ARMS_HERO_DEFAULT))
        self._arms_drone = bool(raw.get(modelmod.ARMS_DRONE_KEY,
                                        modelmod.ARMS_DRONE_DEFAULT))
        self._arms_stamina = modelmod.arms_stamina_of(
            raw.get(modelmod.ARMS_STAMINA_KEY, modelmod.ARMS_STAMINA_DEFAULT))
        self._arms_speedup = bool(raw.get(modelmod.ARMS_SPEEDUP_KEY,
                                          modelmod.ARMS_SPEEDUP_DEFAULT))
        self._arms_minutes = modelmod.arms_minutes_of(
            raw.get(modelmod.ARMS_MINUTES_KEY, modelmod.ARMS_MINUTES_DEFAULT))
        self._arms_units = bool(raw.get(modelmod.ARMS_UNITS_KEY,
                                        modelmod.ARMS_UNITS_DEFAULT))
        self._arms_soldiers = modelmod.arms_soldiers_of(
            raw.get(modelmod.ARMS_SOLDIERS_KEY, modelmod.ARMS_SOLDIERS_DEFAULT))
        self._arms_free_minutes = modelmod.arms_free_minutes_of(
            raw.get(modelmod.ARMS_FREE_MINUTES_KEY,
                    modelmod.ARMS_FREE_MINUTES_DEFAULT))
        self._arms_squad = modelmod.squad_of(raw.get(modelmod.ARMS_SQUAD_KEY))
        self._squad = modelmod.squad_of(raw.get(modelmod.GOLDEN_SQUAD_KEY))
        self._approach = bool(raw.get(modelmod.GOLDEN_APPROACH_KEY, False))
        self._train_carriage = modelmod.carriage_of(raw.get(modelmod.TRAIN_CARRIAGE_KEY))
        self._train_tickets = modelmod.tickets_of(raw.get(modelmod.TRAIN_TICKETS_KEY))
        self._train_buy = bool(raw.get(modelmod.TRAIN_BUY_KEY,
                                       modelmod.TRAIN_BUY_DEFAULT))
        try:
            if self._squad_var is not None:
                self._squad_var.set(str(self._squad))
            if self._approach_var is not None:
                self._approach_var.set(self._approach)
            if self._arms_hero_var is not None:
                self._arms_hero_var.set(self._arms_hero)
            if self._arms_drone_var is not None:
                self._arms_drone_var.set(self._arms_drone)
            if self._arms_speedup_var is not None:
                self._arms_speedup_var.set(self._arms_speedup)
        except tk.TclError:                 # the window is going away
            pass

    def persist_vars(self) -> list:
        return [v for v in (self._squad_var, self._approach_var, self._arms_hero_var,
                            self._arms_drone_var, self._arms_speedup_var)
                if v is not None]

    # -- the phone's copy ---------------------------------------------------
    def web_view(self) -> "dict | None":
        """The same board, from the same reading — one card per event.

        The numbers are DATA and every word is a key, so the phone says them in whatever
        language the panel is set to. The «Атаковать сейчас» press is offered because the
        ability IS a scenario (`CLAUDE.md`): what the phone runs is what the window runs.
        A closed event still gets its card, greyed the only way a card can be — its state
        said in words — for the same reason the window does not hide it.
        """
        state = self.codename()
        rows = [
            {"label": "events.state", "value": self._state_words(state)},
            {"label": "events.codename.attacks", "value": modelmod.counter(state)},
            {"label": "events.codename.damage", "value": modelmod.damage(state.damage)},
        ]
        if state.state == modelmod.OPEN:
            rows.append({"label": "events.codename.until",
                         "value": modelmod.hhmm(state.seconds)})
        card = {"title": "events.group." + modelmod.CODENAME, "rows": rows}
        if state.can_attack and not self._attacking:
            card["actions"] = [{"id": "attack_codename",
                                "label": "events.codename.attack"},
                               {"id": "daily_codename",
                                "label": "events.codename.daily"}]
        else:
            card["items"] = [{"label": "events.codename.attack",
                              "pill": "events.codename.attack.off"},
                             {"label": "events.codename.daily",
                              "pill": "events.codename.attack.off"}]

        # …and «Кристальный босс», the same event with a different manager and three
        # attacks the SERVER counts. The number that matters is what the day still owes,
        # not what this panel sent: an attack made from the game itself is already in it.
        # Both presses travel because both are recipes (`CLAUDE.md`), and the card is
        # drawn on the phone only — new work goes to the web while the window is being
        # retired (#1976), and the reading is what the window already has no room for.
        cr = self.crystal()
        crows = [
            {"label": "events.state", "value": self._state_words(cr)},
            {"label": "events.crystal.attacks", "value": modelmod.counter(cr)},
            {"label": "events.crystal.left", "value": modelmod.crystal_left(cr)},
            {"label": "events.crystal.hp", "value": modelmod.health(cr)},
        ]
        if cr.state == modelmod.OPEN:
            crows.append({"label": "events.crystal.until",
                          "value": modelmod.hhmm(cr.seconds)})
        ccard = {"title": "events.group." + modelmod.CRYSTAL, "rows": crows}
        if cr.can_attack and not self._attacking:
            ccard["actions"] = [{"id": "attack_crystal",
                                 "label": "events.crystal.attack"},
                                {"id": "daily_crystal",
                                 "label": "events.crystal.daily"}]
        else:
            ccard["items"] = [{"label": "events.crystal.attack",
                               "pill": "events.codename.attack.off"},
                              {"label": "events.crystal.daily",
                               "pill": "events.codename.attack.off"}]

        # …and the same board for «Золотые зомби», including the squad, which is a
        # CHOICE and therefore has to be reachable from the phone too: a control the
        # window has and the phone does not is a control the person on the move cannot
        # find (`CLAUDE.md`). The chain is a scenario, so the press travels with it.
        gold = self.golden()
        # THE CARD OF THE NEW SHAPE (#2390): a tile with the state on a pill, the facts
        # in words under it, and every KNOB behind the gear — the one modal, never a
        # second one (`CLAUDE.md`). It replaces nine buttons and a picker standing in a
        # row above the numbers they belong to: on a phone that was two screens of
        # controls before the first fact.
        facts = [
            {"label": "events.golden.energy", "value": modelmod.energy(gold)},
            {"label": "events.golden.affordable", "value": modelmod.affordable(gold)},
            {"label": "events.golden.seen", "value": modelmod.seen(gold)},
            # HOW LONG ONE ZOMBIE TAKES, WHICH IS THE THING THAT WAS WRONG (#2390). The
            # complaint was «очень медленно», and no reading on this card could answer
            # it: the run said what it sent and never how long between. The number is
            # the game's own — the seconds between one order being confirmed and the
            # next — and «—» while a run has sent fewer than two, because one order has
            # no lap.
            {"label": "events.golden.lap", "value": modelmod.lap(self._golden_lap,
                                                                self._golden_lap_last)},
            {"label": "events.golden.speed", "value": modelmod.speed(gold)},
            {"label": "events.golden.today", "value": modelmod.tally(self.today())},
            {"label": "events.golden.target",
             "value": self._golden_target or self.t("events.golden.target.none")},
            {"label": "events.golden.said",
             "value": self.t(self._step_said) if self._step_said else "—"},
        ]
        # WHICH SQUAD GOES, AS THE PICKER EVERY OTHER PAGE DRAWS (#2062) — the player's
        # own four with the heroes standing in them, and one of them picked, because the
        # hunt sends one. It replaces a button that WALKED the slots: «Отряд 3» is one
        # touch here and was three there, and neither said what was standing in it.
        #
        # …and the ride is a SWITCH beside it now and not a press (#2390). It was a
        # button that toggled a setting, which reads as «do it» and is not: nothing
        # happens at the game when it is pressed, and the next hunt travels differently.
        options = [squad_picker.field(
            self.rt, modelmod.GOLDEN_SQUAD_KEY, "squads.title", [self.squad()],
            single=True),
            {"key": modelmod.GOLDEN_APPROACH_KEY, "label": "events.golden.approach",
             "hint": "events.golden.approach.hint", "kind": "switch",
             "value": bool(self.approach())}]
        gitem = {"label": "events.group." + modelmod.GOLDEN,
                 "pill": ("events.golden.state.open" if gold.state == modelmod.OPEN
                          else "events.golden.state.closed"
                          if gold.state == modelmod.CLOSED else "events.state.unknown"),
                 "facts": facts,
                 "options": options,
                 "options_title": "events.golden.options"}
        if gold.can_attack and not self._golden_running:
            gitem["actions"] = [{"id": "hunt_golden", "label": "events.golden.hunt"}]
            gitem["actions"] += [{"id": action, "label": key}
                                 for action, _scenario, key in self.STEPS]
        gcard = {"title": "events.group." + modelmod.GOLDEN, "layout": "cards",
                 "items": [gitem]}

        # …and «Салют», which needs no reading at all: the book is filled by the ear and
        # is already in memory, so this card answers on a phone whose game is asleep. The
        # press is the same scenario the window plays, so it travels (`CLAUDE.md`).
        fw = self.fireworks()
        fcard = {"title": "events.group." + modelmod.FIREWORKS, "rows": [
            {"label": "events.fireworks.today", "value": str(int(fw.get("taken") or 0))},
            {"label": "events.fireworks.heard", "value": str(int(fw.get("heard") or 0))},
            {"label": "events.fireworks.last",
             "value": modelmod.when(fw.get("last_ts") or 0.0)},
            {"label": "events.fireworks.react",
             "value": modelmod.reaction(fw.get("react_last", -1),
                                        fw.get("react_best", -1))},
            {"label": "events.fireworks.refused",
             "value": str(int(fw.get("refused") or 0))},
            {"label": "events.fireworks.month",
             "value": str(int(fw.get("taken_all") or 0))},
        ],
            # The history goes in `items` and not in `rows`: a row's label is a KEY the
            # browser translates, and a date is data. An item's `text` is the free half
            # of the card (docs/panel-tabs.md), which is exactly what a day is.
            "items": [{"text": row["day"], "detail": str(row["taken"])}
                      for row in self.fireworks_days()],
            "actions": [{"id": "collect_fireworks",
                         "label": "events.fireworks.collect"}]}

        # …and «Поезд альянса», whose two knobs are the only things on it a person sets.
        # They are a STANDING ORDER and not a press: the wire trigger reads them at the
        # moment the conductor is appointed (`Schedule.register_args`), which is the one
        # second in the day when boarding actually matters and nobody is at the machine.
        # The press beside them plays the same recipe by hand.
        tr = self.train()
        tcard = {"title": "events.group." + modelmod.TRAIN, "rows": [
            {"label": "events.state", "value": self._train_words(tr)},
            {"label": "events.train.platform", "value": self._train_platform_words(tr)},
            {"label": "events.train.seat", "value": modelmod.train_seat(tr)},
            {"label": "events.train.queue", "value": modelmod.train_queue(tr)},
            {"label": "events.train.departs",
             "value": modelmod.hhmm(tr.departs) if tr.departs is not None else "—"},
            {"label": "events.train.fare", "value": self._train_fare_words(tr)},
            {"label": "events.train.contracts",
             "value": ("—" if tr.contracts is None else str(tr.contracts))},
        ],
            # THE TWO KNOBS ARE FIELDS, NOT PRESSES (#1993). They are the standing order
            # our own watcher obeys when the conductor's push lands, which is the one
            # minute in the day nobody is at the machine — so they have to be SET from
            # the phone rather than walked one step per tap. `kind` is the type they were
            # declared with and the bounds are the game's own: four carriages, and a fare
            # of nothing (a like) up to the three contracts the game itself allows.
            "fields": [
                {"key": modelmod.TRAIN_CARRIAGE_KEY,
                 "label": "events.train.carriage.set", "kind": "number",
                 "value": self.carriage(),
                 "min": modelmod.TRAIN_CARRIAGES[0],
                 "max": modelmod.TRAIN_CARRIAGES[-1]},
                {"key": modelmod.TRAIN_TICKETS_KEY,
                 "label": "events.train.tickets.set",
                 "hint": "events.train.tickets.hint", "kind": "number",
                 "value": self.tickets(),
                 "min": modelmod.TRAIN_TICKETS[0],
                 "max": modelmod.TRAIN_TICKETS[-1]},
                # …AND WHETHER MONEY MAY BE SPENT TO REACH THAT NUMBER, which is a
                # separate permission and starts off. The count of contracts the account
                # actually holds is a row on this same card, right above — so the person
                # ticking this can see what it is likely to cost them.
                {"key": modelmod.TRAIN_BUY_KEY, "label": "events.train.buy",
                 "hint": "events.train.buy.hint", "kind": "switch",
                 "value": self.buy_missing()}]}
        if tr.can_board and not self._train_boarding:
            board = {"id": "board_train", "label": "events.train.board"}
            if self.tickets() > 0:
                # The fare leaves the bag when this is answered, so it asks first — the
                # same rule the rally join goes by. Diamonds are never in it: the recipe
                # clamps the fare to the contracts actually held (`CLAUDE.md`).
                board["confirm"] = "events.train.board.confirm"
            tcard["actions"] = [board]
        else:
            tcard["items"] = [{"label": "events.train.board",
                               "pill": "events.codename.attack.off"}]

        # …and «Под руинами», the seasonal descent. Attempts are not limited and only
        # the best depth is ranked, so the card carries what the last run reached and a
        # press that plays another one. The whole ability is one recipe: the autopilot
        # lives inside the game on its own tick, and the panel only starts it and asks
        # afterwards how it went (docs/research/beneath-ruins.md).
        rcard = {"title": "events.group.ruins", "rows": [
            {"label": "events.ruins.result",
             "value": self._ruins_said or "—"}],
            "actions": [{"id": "ruins_play", "label": "events.ruins.play",
                         "confirm": "events.ruins.confirm"},
                        {"id": "ruins_read", "label": "events.ruins.read"}]}

        # …and «Гонка вооружений», which is the one card on this board whose whole
        # point is what comes NEXT: the six phases of the day, with the one running now
        # marked. That list exists because the reading sends the calendar get — nothing
        # else on the client knows it (docs/research/arms-race.md).
        arms = self.arms()
        acard = {"title": "events.group." + modelmod.ARMS, "rows": [
            {"label": "events.state", "value": self._state_words(arms)},
            {"label": "events.arms.phase",
             "value": self._arms_kind_words(arms.kind)},
            {"label": "events.arms.points", "value": modelmod.arms_points(arms)},
            {"label": "events.arms.chests", "value": modelmod.arms_chests(arms)},
            {"label": "events.arms.day_chests",
             "value": modelmod.arms_day_chests(arms)},
            {"label": "events.arms.day",
             "value": ("—" if arms.done is None else "%d / 6" % arms.done)},
            # HOW OLD THIS CARD IS, and its own age rather than the board's (#2393).
            # The strip at the top of the screen carries the age of the CODENAME
            # reading; the arms one is a separate scenario on a separate chain, and a
            # phase that changed while this reading did not is exactly the failure that
            # brought the task — «текущий час не работает» over numbers that were true
            # three days ago and said so nowhere.
            {"label": "events.arms.read",
             "value": (modelmod.ago(self._age_of(self._arms))
                       if self._arms is not None and not self._arms.error else "—")},
        ]}
        if arms.state == modelmod.OPEN:
            acard["rows"].append({"label": "events.arms.until",
                                  "value": modelmod.hhmm(arms.seconds)})
        if arms.phases:
            # The NAME is the label and the clock is the value, and that way round for a
            # reason: a label is a locale key on this front-end and «07:00–11:00» is
            # data. A kind the server invents tomorrow says so in words and carries its
            # id in the value, rather than putting a bare number where a key belongs.
            items = []
            for _stage, kind, start, end in arms.phases:
                key = modelmod.ARMS_KINDS.get(kind)
                clock = modelmod.arms_phase_clock(start, end)
                items.append({"label": key or "events.arms.kind.other",
                              "value": clock if key else "%s · %s" % (clock, kind)})
            acard["items"] = items
        # THE SWITCH IS A FIELD, not a press: it is the rule our own four-hourly run
        # obeys when it fires on a phase border, which is exactly the minute nobody is
        # at the machine (`CLAUDE.md`).
        acard["fields"] = [
            {"key": modelmod.ARMS_HERO_KEY, "label": "events.arms.hero",
             "hint": "events.arms.hero.hint", "kind": "switch",
             "value": self.arms_hero()},
            {"key": modelmod.ARMS_DRONE_KEY, "label": "events.arms.drone",
             "hint": "events.arms.drone.hint", "kind": "switch",
             "value": self.arms_drone()},
            # THE 300 IS A FIELD AND NOT A CONSTANT, because it is the person's number
            # («час дрона, 300 энергии, это стамина, тратим только стягами») and an
            # account whose bar is a different size will want a different one.
            {"key": modelmod.ARMS_SPEEDUP_KEY, "label": "events.arms.speedup",
             "hint": "events.arms.speedup.hint", "kind": "switch",
             "value": self.arms_speedup()},
            {"key": modelmod.ARMS_MINUTES_KEY, "label": "events.arms.minutes",
             "hint": "events.arms.minutes.hint", "kind": "number",
             "value": self.arms_minutes(),
             "min": modelmod.ARMS_MINUTES_MIN, "max": modelmod.ARMS_MINUTES_MAX},
            {"key": modelmod.ARMS_UNITS_KEY, "label": "events.arms.units",
             "hint": "events.arms.units.hint", "kind": "switch",
             "value": self.arms_units()},
            {"key": modelmod.ARMS_SOLDIERS_KEY, "label": "events.arms.soldiers",
             "hint": "events.arms.soldiers.hint", "kind": "number",
             "value": self.arms_soldiers(),
             "min": modelmod.ARMS_SOLDIERS_MIN, "max": modelmod.ARMS_SOLDIERS_MAX},
            {"key": modelmod.ARMS_FREE_MINUTES_KEY, "label": "events.arms.free_minutes",
             "hint": "events.arms.free_minutes.hint", "kind": "number",
             "value": self.arms_free_minutes(),
             "min": modelmod.ARMS_FREE_MINUTES_MIN,
             "max": modelmod.ARMS_FREE_MINUTES_MAX},
            {"key": modelmod.ARMS_STAMINA_KEY, "label": "events.arms.stamina",
             "hint": "events.arms.stamina.hint", "kind": "number",
             "value": self.arms_stamina(),
             "min": modelmod.ARMS_STAMINA_MIN, "max": modelmod.ARMS_STAMINA_MAX},
            squad_picker.field(self.rt, modelmod.ARMS_SQUAD_KEY, "events.arms.squad",
                               [self.arms_squad()], single=True)]
        if not self._arms_running:
            acts = [{"id": "play_arms", "label": "events.arms.play"}]
            if arms.kind == modelmod.ARMS_HERO:
                # Hiring spends the player's recruit tickets, so it asks first — the
                # same rule the train's fare and the rally join go by. Diamonds are
                # never in it: the recipe refuses a hire the tickets will not cover.
                acts.append({"id": "phase_arms", "label": "events.arms.hire",
                             "confirm": "events.arms.hire.confirm"})
            elif arms.kind == modelmod.ARMS_DRONE:
                # …and raising sends squads out of the base and spends the day's own
                # rallies, so it asks too. What it may spend is the two ceilings above
                # and the rally budget the card does not own.
                acts.append({"id": "phase_arms", "label": "events.arms.raise",
                             "confirm": "events.arms.raise.confirm"})
            elif arms.kind == modelmod.ARMS_UNIT:
                # …and a batch spends the base's own resources, so it asks too. What it
                # may spend is the «солдат» ceiling above, and the barracks decide the
                # rest: each is asked for the size the game has already accepted for it.
                acts.append({"id": "phase_arms", "label": "events.arms.train",
                             "confirm": "events.arms.train.confirm"})
            elif arms.kind in modelmod.ARMS_MINUTE_KINDS:
                # …and pouring minutes into a queue spends the player's own speed-ups,
                # which is the one thing here that cannot be got back. It asks, and what
                # it may spend is the «минут» ceiling above and the phase's top chest.
                acts.append({"id": "phase_arms", "label": "events.arms.spend",
                             "confirm": "events.arms.spend.confirm"})
            acard["actions"] = acts
        else:
            acard["items"] = (acard.get("items") or []) + [
                {"label": "events.arms.play", "pill": "events.codename.attack.off"}]

        # …and «Ящик с сюрпризом», the packet of free diamonds a surprise box sometimes
        # drops. The bonus is a red packet given away in the ALLIANCE chat, once, inside
        # an hour of the drop — it costs the account nothing and an hour later it is gone,
        # which is why the card leads with the minutes left rather than with a count.
        #
        # THE CARD READS NOTHING BY ITSELF. There is no clock behind it and there must not
        # be: the drop is announced by a command nobody has named yet, so the ear
        # (`actions/watch_lucky_packet.md`) is what will make this card live, and until it
        # has heard one drop the honest thing is a reading with a press beside it
        # (`CLAUDE.md` — «read once, then LISTEN»).
        lstate = modelmod.lucky_state(self._lucky_said)
        lcard = {"title": "events.group." + modelmod.LUCKY, "rows": [
            {"label": "events.state",
             "value": self.t("events.lucky.state." + lstate)},
            {"label": "events.lucky.left",
             "value": modelmod.lucky_left(self._lucky_said)},
            {"label": "events.lucky.watch",
             "value": self._lucky_watch_said or "—"},
        ],
            "actions": [{"id": "lucky_read", "label": "events.lucky.read"},
                        {"id": "lucky_watch", "label": "events.lucky.arm"}]}
        if lstate == modelmod.OPEN and not self._lucky_running:
            # It goes to the whole alliance and cannot be taken back, so it asks first —
            # the same rule the train's fare and the rally's join go by.
            lcard["actions"].insert(0, {"id": "lucky_share",
                                        "label": "events.lucky.share",
                                        "confirm": "events.lucky.confirm"})

        return {"cards": [
            {"title": None, "rows": [
                {"label": "events.web.read",
                 "value": (modelmod.ago(self._age()) if self._reading is not None
                           and not self._reading.error else "—")}]},
            card,
            ccard,
            gcard,
            tcard,
            fcard,
            lcard,
            rcard,
            acard,
        ], "now": time.time(),
            "actions": [{"id": "refresh", "label": "events.refresh"},
                        # …AND «ПРОРЫВ ОБОРОНЫ» (#1976), the Sunday mini-game. One recipe
                        # with its own defaults, played by the schedule for months — and a
                        # schedule is not a home: it runs without anybody asking, and
                        # «сыграй его сейчас» had nowhere to be pressed
                        # (`tests/test_scenario_homes.py`). Here, among the events.
                        {"id": "frontline", "label": "events.frontline.play",
                         "confirm": "events.frontline.confirm"}]}

    def ruins(self, play: bool) -> dict:
        """Play the descent, or ask how the last run went.

        Both are the same recipe pair (`play_beneath_ruins` arms the autopilot inside
        the game, `read_beneath_ruins` says what it reached), so the press is one
        `play_async` and the answer is the reading the run left in its own variables.
        """
        if play and self._ruins_running:
            return {"ok": False, "reason": "events.ruins.busy"}
        name = "play_beneath_ruins" if play else "read_beneath_ruins"
        if play:
            self._ruins_running = True

        def came(outcome) -> None:
            got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
            said = str(got.get("armed") or got.get("run") or "").strip()
            if said:
                self._ruins_said = said.replace("true :: ", "")
            self._ruins_running = False

        return {"ok": self.rt.play_async(name, tag="events", human=True,
                                         on_result=came)}

    def lucky(self, what: str) -> dict:
        """Read the packet, give it away, or arm the ear — one scenario each.

        THE PRESS IS THE PHONE'S AND THE WINDOW HAS NONE, which is the migration's rule
        and not an omission (#1976, #2397): new work goes into the web while Tk is being
        retired. Giving the packet away is visible to the whole alliance and cannot be
        taken back, so the card asks first — the same rule the train's fare goes by.
        """
        name = {"read": modelmod.LUCKY_READ, "share": modelmod.LUCKY_SHARE,
                "watch": modelmod.LUCKY_WATCH}.get(what)
        if name is None:
            return {"error": "unknown"}
        if what == "share":
            self._lucky_running = True

        def came(outcome) -> None:
            got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
            said = str(got.get(modelmod.LUCKY_VARIABLE) or "").strip()
            if said:
                self._lucky_said = said
            heard = str(got.get(modelmod.LUCKY_WATCH_VARIABLE)
                        or got.get("state") or "").strip()
            if heard:
                self._lucky_watch_said = heard
            self._lucky_running = False

        return {"ok": self.rt.play_async(name, tag="events", human=True,
                                         on_result=came)}

    def web_press(self, action: str, args: dict) -> dict:
        """The same three presses the window has, and nothing the window has not."""
        if action == "refresh":
            return {"ok": self.refresh_both(human=True)}
        if action in ("ruins_play", "ruins_read"):
            return self.ruins(action == "ruins_play")
        if action in ("lucky_read", "lucky_share", "lucky_watch"):
            return self.lucky(action.split("_", 1)[1])
        if action == "collect_fireworks":
            return {"ok": self.collect_fireworks()}
        if action == "play_arms":
            return {"ok": self.play_arms(modelmod.ARMS_ERRAND)}
        if action == "phase_arms":
            # The gate is the recipe's — it refuses a phase of another kind in one line.
            # What is checked here is only that the panel can NAME the phase as one it
            # has a recipe for: a press over an unreadable phase would ask the game to
            # act on something nobody could say the name of.
            play = modelmod.ARMS_PLAYS.get(self.arms().kind)
            if play is None:
                return {"error": "closed"}
            return {"ok": self.play_arms(play)}
        if action == "frontline":
            # The recipe's own defaults — how many rounds, how deep each lane goes — are
            # `ARGS` of the file and the panel holds no second opinion (`CLAUDE.md`).
            return {"ok": self.rt.play_async("play_frontline_breakthrough",
                                             tag="events", human=True)}
        if action in ("attack_codename", "daily_codename"):
            if not self.codename().can_attack:
                return {"error": "closed"}
            return {"ok": self.attack() if action == "attack_codename" else self.daily()}
        if action in ("attack_crystal", "daily_crystal"):
            # The same gate the card draws by, and no second one: what «the day still
            # owes» is belongs to the recipe, which asks the server and refuses in one
            # line. All this checks is that the game has not SAID there is no boss.
            if not self.crystal().can_attack:
                return {"error": "closed"}
            return {"ok": (self.attack_crystal() if action == "attack_crystal"
                           else self.daily_crystal())}
        if action == "squad_next":
            # THE BUTTON THAT WALKED THE SLOTS, kept for the page a phone already has
            # open (#2062). The card draws the picker now — one touch, and the faces say
            # which squad it is — and both ends write the same setting.
            slots = list(modelmod.GOLDEN_SQUADS)
            wanted = slots[(slots.index(self.squad()) + 1) % len(slots)]
            return self._set_golden_squad(wanted)
        if action == "approach_toggle":
            # A setting, like the squad: it changes how the next hunt travels and
            # presses nothing at the game.
            self._approach = not self.approach()
            if self._approach_var is not None:
                try:
                    self._approach_var.set(self._approach)
                except tk.TclError:         # the window is going away
                    pass
            return {"ok": True, "approach": self._approach}
        if any(action == row[0] for row in self.STEPS):
            # A step is playable whenever the client is: it is one press at the game,
            # and the whole point of having them is to try them when the chain will not.
            return {"ok": self.step(action)}
        if action == "board_train":
            if not self.train().can_board:
                return {"error": "closed"}
            return {"ok": self.board_train()}
        if action == "set":
            # The two train knobs, moved by the renderer's own field control. A SETTING
            # and not a press at the game: it changes what the next boarding — by hand or
            # on the conductor's push — will do, and presses nothing now. Both are
            # clamped by the model, so a value the page should not have been able to send
            # lands on the nearest one that exists rather than on the game.
            key = str((args or {}).get("key") or "")
            raw = (args or {}).get("value")
            if key == modelmod.TRAIN_CARRIAGE_KEY:
                number = _whole(raw)
                if number is None or number not in modelmod.TRAIN_CARRIAGES:
                    return {"ok": False, "reason": "web.ui.not_a_number"}
                self._train_carriage = number
                self._train_knob_saved()
                return {"ok": True, "carriage": self._train_carriage}
            if key == modelmod.TRAIN_TICKETS_KEY:
                number = _whole(raw)
                if number is None or number not in modelmod.TRAIN_TICKETS:
                    return {"ok": False, "reason": "web.ui.not_a_number"}
                self._train_tickets = number
                self._train_knob_saved()
                return {"ok": True, "tickets": self._train_tickets}
            if key == modelmod.GOLDEN_APPROACH_KEY:
                # THE RIDE, AS A SWITCH (#2390). It was a press that walked a setting,
                # which reads as «do it now» and never was: nothing leaves the base when
                # it is thrown, and the next hunt travels by mine instead of marching.
                # The old press is still answered above, for a page a phone already has.
                self._approach = bool(raw)
                if self._approach_var is not None:
                    try:
                        self._approach_var.set(self._approach)
                    except tk.TclError:      # the window is going away
                        pass
                return {"ok": True, "approach": self._approach}
            if key == modelmod.GOLDEN_SQUAD_KEY:
                # ONE SQUAD, and the picker sends the list it drew (#2062). A press
                # naming none is refused rather than silently sending squad 1 — the hunt
                # has to send something, and inventing which is not the panel's call.
                picked = squad_picker.chosen_from(raw)
                if len(picked) != 1:
                    return {"error": "unknown"}
                return self._set_golden_squad(picked[0])
            if key == modelmod.ARMS_HERO_KEY:
                self._arms_hero = bool(raw)
                if self._arms_hero_var is not None:
                    try:
                        self._arms_hero_var.set(self._arms_hero)
                    except tk.TclError:     # the window is going away
                        pass
                self._arms_knob_saved()
                return {"ok": True, "hero": self._arms_hero}
            if key == modelmod.ARMS_DRONE_KEY:
                self._arms_drone = bool(raw)
                if self._arms_drone_var is not None:
                    try:
                        self._arms_drone_var.set(self._arms_drone)
                    except tk.TclError:     # the window is going away
                        pass
                self._arms_knob_saved()
                return {"ok": True, "drone": self._arms_drone}
            if key == modelmod.ARMS_SPEEDUP_KEY:
                self._arms_speedup = bool(raw)
                if self._arms_speedup_var is not None:
                    try:
                        self._arms_speedup_var.set(self._arms_speedup)
                    except tk.TclError:     # the window is going away
                        pass
                self._arms_knob_saved()
                return {"ok": True, "speedup": self._arms_speedup}
            if key == modelmod.ARMS_UNITS_KEY:
                self._arms_units = bool(raw)
                self._arms_knob_saved()
                return {"ok": True, "units": self._arms_units}
            if key == modelmod.ARMS_SOLDIERS_KEY:
                # Refused rather than clamped, the same rule as the minute fuse: a
                # ceiling that silently became another number is a ceiling nobody set,
                # and this one stands in front of the base's own resources.
                number = _whole(raw)
                if (number is None or number < modelmod.ARMS_SOLDIERS_MIN
                        or number > modelmod.ARMS_SOLDIERS_MAX):
                    return {"ok": False, "reason": "web.ui.not_a_number"}
                self._arms_soldiers = number
                self._arms_knob_saved()
                return {"ok": True, "soldiers": self._arms_soldiers}
            if key == modelmod.ARMS_FREE_MINUTES_KEY:
                # Refused rather than clamped, like every other ceiling on this card.
                number = _whole(raw)
                if (number is None or number < modelmod.ARMS_FREE_MINUTES_MIN
                        or number > modelmod.ARMS_FREE_MINUTES_MAX):
                    return {"ok": False, "reason": "web.ui.not_a_number"}
                self._arms_free_minutes = number
                self._arms_knob_saved()
                return {"ok": True, "free_minutes": self._arms_free_minutes}
            if key == modelmod.ARMS_MINUTES_KEY:
                # Refused rather than clamped, for the same reason as the stamina one
                # below — and this ceiling stands in front of the player's speed-ups,
                # which is the one thing on this card that cannot be got back.
                number = _whole(raw)
                if (number is None or number < modelmod.ARMS_MINUTES_MIN
                        or number > modelmod.ARMS_MINUTES_MAX):
                    return {"ok": False, "reason": "web.ui.not_a_number"}
                self._arms_minutes = number
                self._arms_knob_saved()
                return {"ok": True, "minutes": self._arms_minutes}
            if key == modelmod.ARMS_STAMINA_KEY:
                # REFUSED RATHER THAN CLAMPED, the rule the train's fare goes by: a
                # ceiling that silently became something else is a ceiling the person
                # did not set.
                number = _whole(raw)
                if (number is None or number < modelmod.ARMS_STAMINA_MIN
                        or number > modelmod.ARMS_STAMINA_MAX):
                    return {"ok": False, "reason": "web.ui.not_a_number"}
                self._arms_stamina = number
                self._arms_knob_saved()
                return {"ok": True, "stamina": self._arms_stamina}
            if key == modelmod.ARMS_SQUAD_KEY:
                # ONE squad — a run raises its banners with one, and inventing which is
                # not the panel's call (#2062).
                picked = squad_picker.chosen_from(raw)
                if len(picked) != 1:
                    return {"error": "unknown"}
                self._arms_squad = modelmod.squad_of(picked[0])
                self._arms_knob_saved()
                return {"ok": True, "squad": self._arms_squad}
            if key == modelmod.TRAIN_BUY_KEY:
                self._train_buy = bool(raw)
                self._train_knob_saved()
                return {"ok": True, "buy": self._train_buy}
            return {"error": "unknown"}
        if action == "hunt_golden":
            if not self.golden().can_attack:
                return {"error": "closed"}
            return {"ok": self.hunt()}
        return {"error": "unknown"}
