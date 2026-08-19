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
from ...widgets import ScrollableFrame, font as ui_font, tk_stringvar
from ..base import PanelTab
from . import model as modelmod

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
        #: The squad the chain sends, by the slot the player sees. A plain int until
        #: `build()` makes the widget — a tab nobody has opened still has to be able to
        #: answer `config()` (`docs/panel-tabs.md`).
        self._squad = modelmod.GOLDEN_SQUAD_DEFAULT
        self._squad_var = None
        #: The day's tally, read out of `panel.db` the first time anybody looks.
        self._tally = None
        #: Whether the golden reading should follow the codename one home.
        self._chain_golden = False

    # -- the tab ------------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Button(bar, command=self.refresh), "events.refresh").pack(side="left")

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

    def refresh(self) -> bool:
        """Ask the game what the events are doing. `False` if it could not be asked now.

        A refusal — something else is driving the game — leaves the previous reading and
        its age on screen, which is the honest answer: it is what we know, and how old.
        """
        if self._busy:
            return False
        self._busy = True
        self._refresh_status()
        started = self.rt.play_async(
            modelmod.CODENAME_ACTION, tag="events",
            on_result=self._read_back, on_done=self._read_done)
        if not started:
            self._busy = False
            self._refresh_status()
        return started

    def refresh_both(self) -> bool:
        """Take both readings, one after the other rather than both at once.

        Only one scenario may drive the client at a time, so a second read fired beside
        the first is refused outright — and a refusal leaves the old answer on screen,
        which for a board that has never been read means «неизвестно» for ever. So the
        golden reading is hung on the codename one's finish, and taken on its own when
        the codename one could not be started at all.
        """
        self._chain_golden = True
        if self.refresh():
            return True
        self._chain_golden = False
        return self.refresh_golden()

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
            scenario, tag="events",
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
    def refresh_golden(self) -> bool:
        """Ask the game what the hunt has to work with. `False` if it could not be asked.

        A refusal — something else is driving the client, usually the chain itself — is
        left showing the previous reading and its age, which is the honest answer.
        """
        if self._golden_busy:
            return False
        self._golden_busy = True
        started = self.rt.play_async(
            modelmod.GOLDEN_ACTION, tag="events",
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
            modelmod.GOLDEN_ATTACK, {"squad": self.squad()}, tag="events",
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

        press = ttk.Frame(self._body)
        press.pack(fill="x", padx=28, pady=(4, 8))
        self._golden_button = self.tr(ttk.Button(press, command=self.hunt),
                                      "events.golden.hunt")
        self._golden_button.pack(side="left")
        self.tr(ttk.Label(press, foreground=_GREY),
                "events.golden.hunt.hint").pack(side="left", padx=(10, 0))
        self._paint_golden_button()

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
        return {modelmod.GOLDEN_SQUAD_KEY: self.squad()}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._squad = modelmod.squad_of(raw.get(modelmod.GOLDEN_SQUAD_KEY))
        if self._squad_var is not None:
            try:
                self._squad_var.set(str(self._squad))
            except tk.TclError:             # the window is going away
                pass

    def persist_vars(self) -> list:
        return [self._squad_var] if self._squad_var is not None else []

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
            {"label": "events.golden.today", "value": modelmod.tally(self.today())},
            {"label": "events.golden.squad", "value": str(self.squad())},
        ]}
        if gold.can_attack and not self._golden_running:
            gcard["actions"] = [{"id": "hunt_golden", "label": "events.golden.hunt"},
                                {"id": "squad_next",
                                 "label": "events.golden.squad.next"}]
        else:
            gcard["items"] = [{"label": "events.golden.hunt",
                               "pill": "events.codename.attack.off"}]

        return {"cards": [
            {"title": None, "rows": [
                {"label": "events.web.read",
                 "value": (modelmod.ago(self._age()) if self._reading is not None
                           and not self._reading.error else "—")}]},
            card,
            gcard,
        ], "now": time.time(),
            "actions": [{"id": "refresh", "label": "events.refresh"}]}

    def web_press(self, action: str, args: dict) -> dict:
        """The same three presses the window has, and nothing the window has not."""
        if action == "refresh":
            return {"ok": self.refresh_both()}
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
        if action == "hunt_golden":
            if not self.golden().can_attack:
                return {"error": "closed"}
            return {"ok": self.hunt()}
        return {"error": "unknown"}
