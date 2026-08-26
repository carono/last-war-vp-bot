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

#: How a state looks in the window. A glyph is not a word — it needs no translating and
#: is the same in every language, which is why these three are literals and the sentence
#: beside them is a key.
_GLYPH = {
    modelmod.OPEN:    ("●", "#4caf50"),
    modelmod.CLOSED:  ("—", "#888888"),
    modelmod.UNKNOWN: ("?", "#888888"),
}

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
        self._tick()
        self.refresh_both()

    def on_show(self) -> None:
        """Somebody is looking: re-read anything stale and pick the clock back up."""
        if self._age() > self.STALE_SEC:
            self.refresh_both()
        else:
            self._refresh_status()
            if self._age_of(self._golden) > self.STALE_SEC:
                self.refresh_golden()
        self.rt.tick.arm("events_poll", self.TICK_MS, self._tick)

    def on_language_change(self) -> None:
        self._render()

    def on_profile_switch(self) -> None:
        """A different account is in a different place in the event: forget and re-read."""
        self._reading = None
        self._golden = None
        self._tally = None
        self._render()
        self.refresh_both()

    def panic(self) -> None:
        """«Стоп всё»: stop asking. What is on screen stays, with its age beside it."""
        self.rt.tick.disarm("events_poll")
        self.rt.tick.disarm("events_after_attack")
        self.rt.tick.disarm("events_after_hunt")

    def shutdown(self) -> None:
        self.rt.tick.disarm("events_poll")
        self.rt.tick.disarm("events_after_attack")
        self.rt.tick.disarm("events_after_hunt")

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

    def _play(self, scenario: str, sent_key: str) -> bool:
        """Start one of the two, with the sentence its finish will be reported in.

        One press at a time, whichever it is: both drive the same client at the same
        boss, and two at once would be two runs racing for the same free squad.
        """
        if self._attacking:
            return False
        self._attacking = True
        self._sent_key = sent_key
        self._paint_attack_button()
        started = self.rt.play_async(
            scenario, tag="events", human=True,
            on_result=self._attack_back, on_done=self._attack_done)
        if not started:
            self._attacking = False
            self._sent_key = None
            self._paint_attack_button()
            self.say("events", "events.codename.log.busy")
        return started

    def _attack_back(self, outcome) -> None:
        """Say what came of it — the scenario's own words, never a guess of ours."""
        if outcome is not None and getattr(outcome, "ok", False):
            self.say("events", self._sent_key or "events.codename.log.sent")
        else:
            self.say("events", "events.codename.log.failed",
                     error=(getattr(outcome, "reason", "") or "?"))

    def _attack_done(self) -> None:
        self._attacking = False
        self._sent_key = None
        self._paint_attack_button()
        #: Re-read rather than counting the press: the count that matters is the
        #: server's, and it is the only thing that says an attack really went out.
        self.rt.tick.arm("events_after_attack", self.AFTER_ATTACK_MS, self.refresh)

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
        return {modelmod.GOLDEN_SQUAD_KEY: self.squad(),
                modelmod.GOLDEN_APPROACH_KEY: self.approach()}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._squad = modelmod.squad_of(raw.get(modelmod.GOLDEN_SQUAD_KEY))
        self._approach = bool(raw.get(modelmod.GOLDEN_APPROACH_KEY, False))
        try:
            if self._squad_var is not None:
                self._squad_var.set(str(self._squad))
            if self._approach_var is not None:
                self._approach_var.set(self._approach)
        except tk.TclError:                 # the window is going away
            pass

    def persist_vars(self) -> list:
        return [v for v in (self._squad_var, self._approach_var) if v is not None]

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

        # …and the same board for «Золотые зомби», including the squad, which is a
        # CHOICE and therefore has to be reachable from the phone too: a control the
        # window has and the phone does not is a control the person on the move cannot
        # find (`CLAUDE.md`). The chain is a scenario, so the press travels with it.
        gold = self.golden()
        gcard = {"title": "events.group." + modelmod.GOLDEN, "rows": [
            {"label": "events.state", "value": self._golden_words(gold)},
            {"label": "events.golden.energy", "value": modelmod.energy(gold)},
            {"label": "events.golden.affordable", "value": modelmod.affordable(gold)},
            {"label": "events.golden.seen", "value": modelmod.seen(gold)},
            {"label": "events.golden.speed", "value": modelmod.speed(gold)},
            {"label": "events.golden.today", "value": modelmod.tally(self.today())},
            {"label": "events.golden.squad", "value": str(self.squad())},
            {"label": "events.golden.approach",
             "value": self.t("events.golden.approach."
                             + ("on" if self.approach() else "off"))},
            {"label": "events.golden.target",
             "value": self._golden_target or self.t("events.golden.target.none")},
            {"label": "events.golden.said",
             "value": self.t(self._step_said) if self._step_said else "—"},
        ]}
        if gold.can_attack and not self._golden_running:
            gcard["actions"] = [{"id": "hunt_golden", "label": "events.golden.hunt"},
                                {"id": "squad_next",
                                 "label": "events.golden.squad.next"},
                                {"id": "approach_toggle",
                                 "label": "events.golden.approach.toggle"}]
            gcard["actions"] += [{"id": action, "label": key}
                                 for action, _scenario, key in self.STEPS]
        else:
            gcard["items"] = [{"label": "events.golden.hunt",
                               "pill": "events.codename.attack.off"}]

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

        return {"cards": [
            {"title": None, "rows": [
                {"label": "events.web.read",
                 "value": (modelmod.ago(self._age()) if self._reading is not None
                           and not self._reading.error else "—")}]},
            card,
            gcard,
            fcard,
        ], "now": time.time(),
            "actions": [{"id": "refresh", "label": "events.refresh"},
                        # …AND «ПРОРЫВ ОБОРОНЫ» (#1976), the Sunday mini-game. One recipe
                        # with its own defaults, played by the schedule for months — and a
                        # schedule is not a home: it runs without anybody asking, and
                        # «сыграй его сейчас» had nowhere to be pressed
                        # (`tests/test_scenario_homes.py`). Here, among the events.
                        {"id": "frontline", "label": "events.frontline.play",
                         "confirm": "events.frontline.confirm"}]}

    def web_press(self, action: str, args: dict) -> dict:
        """The same three presses the window has, and nothing the window has not."""
        if action == "refresh":
            return {"ok": self.refresh_both(human=True)}
        if action == "collect_fireworks":
            return {"ok": self.collect_fireworks()}
        if action == "frontline":
            # The recipe's own defaults — how many rounds, how deep each lane goes — are
            # `ARGS` of the file and the panel holds no second opinion (`CLAUDE.md`).
            return {"ok": self.rt.play_async("play_frontline_breakthrough",
                                             tag="events", human=True)}
        if action in ("attack_codename", "daily_codename"):
            if not self.codename().can_attack:
                return {"error": "closed"}
            return {"ok": self.attack() if action == "attack_codename" else self.daily()}
        if action == "squad_next":
            # Picking the squad is a SETTING, not a press at the game: it changes what
            # the next hunt sends and nothing else. One button that walks the slots
            # rather than four that look alike — the row above says which one is on, and
            # the window's drop-down and this agree because both read `squad()`.
            slots = list(modelmod.GOLDEN_SQUADS)
            wanted = slots[(slots.index(self.squad()) + 1) % len(slots)]
            self._squad = wanted
            if self._squad_var is not None:
                try:
                    self._squad_var.set(str(wanted))
                except tk.TclError:         # the window is going away
                    pass
            return {"ok": True, "squad": wanted}
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
        if action == "hunt_golden":
            if not self.golden().can_attack:
                return {"error": "closed"}
            return {"ok": self.hunt()}
        return {"error": "unknown"}
