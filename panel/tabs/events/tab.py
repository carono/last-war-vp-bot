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

**The one press here plays a scenario and nothing else.** «Атаковать сейчас» runs
`actions/attack_codename_boss.md`, which finds the boss, finds a squad standing in the
base and sends it. Whether the attack COUNTED is then re-read from the game a moment
later, never inferred from the press returning cleanly — which is the same rule the
checklist works by, stated the other way round: a press may start work, but only a
reading may say it is done.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

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
        """Start the clock and take the first reading, the first time anybody looks."""
        self._tick()
        self.refresh()

    def on_show(self) -> None:
        """Somebody is looking: re-read anything stale and pick the clock back up."""
        if self._age() > self.STALE_SEC:
            self.refresh()
        else:
            self._refresh_status()
        self.rt.tick.arm("events_poll", self.TICK_MS, self._tick)

    def on_language_change(self) -> None:
        self._render()

    def on_profile_switch(self) -> None:
        """A different account is in a different place in the event: forget and re-read."""
        self._reading = None
        self._render()
        self.refresh()

    def panic(self) -> None:
        """«Стоп всё»: stop asking. What is on screen stays, with its age beside it."""
        self.rt.tick.disarm("events_poll")
        self.rt.tick.disarm("events_after_attack")

    def shutdown(self) -> None:
        self.rt.tick.disarm("events_poll")
        self.rt.tick.disarm("events_after_attack")

    # -- the reading --------------------------------------------------------
    def _tick(self) -> None:
        """Repaint the ages, and take a fresh reading when the old one is stale."""
        try:
            if not self._busy and self._age() >= self.REFRESH_SEC:
                self.refresh()
            else:
                self._refresh_status()
        finally:
            self.rt.tick.arm("events_poll", self.TICK_MS, self._tick)

    def _age(self) -> float:
        """Seconds since the last reading; a very large number when there is none."""
        if self._reading is None or not self._reading.at:
            return float("inf")
        return max(0.0, time.time() - self._reading.at)

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

    # -- the one press ------------------------------------------------------
    def attack(self) -> bool:
        """Send a squad at the «Кодовое имя» boss. One attack, one press.

        Everything the attack IS lives in `actions/attack_codename_boss.md` — which boss,
        which squad, what to do when the popup does not open. This starts it and re-reads
        the board afterwards; whether the attack counted is the game's answer, not this
        button's.
        """
        if self._attacking:
            return False
        self._attacking = True
        self._paint_attack_button()
        started = self.rt.play_async(
            modelmod.CODENAME_ATTACK, tag="events",
            on_result=self._attack_back, on_done=self._attack_done)
        if not started:
            self._attacking = False
            self._paint_attack_button()
            self.say("events", "events.codename.log.busy")
        return started

    def _attack_back(self, outcome) -> None:
        """Say what came of it — the scenario's own words, never a guess of ours."""
        if outcome is not None and getattr(outcome, "ok", False):
            self.say("events", "events.codename.log.sent")
        else:
            self.say("events", "events.codename.log.failed",
                     error=(getattr(outcome, "reason", "") or "?"))

    def _attack_done(self) -> None:
        self._attacking = False
        self._paint_attack_button()
        #: Re-read rather than counting the press: the count that matters is the
        #: server's, and it is the only thing that says an attack really went out.
        self.rt.tick.arm("events_after_attack", self.AFTER_ATTACK_MS, self.refresh)

    # -- the board ----------------------------------------------------------
    def codename(self):
        """The codename group against the last reading — what both front-ends draw."""
        return modelmod.codename_state(self._reading)

    def _render(self) -> None:
        if self._body is None:
            return
        self._attack_button = None
        for child in list(self._body.winfo_children()):
            child.destroy()
        for group in modelmod.GROUPS:
            if group.key == modelmod.CODENAME:
                self._render_codename(group)
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
        press.pack(fill="x", padx=28, pady=(4, 6))
        self._attack_button = self.tr(ttk.Button(press, command=self.attack),
                                      "events.codename.attack")
        self._attack_button.pack(side="left")
        self._paint_attack_button()
        self.tr(ttk.Label(press, foreground=_GREY),
                "events.codename.attack.hint").pack(side="left", padx=(10, 0))

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
        """Alive only while the event is running and no attack is already on its way."""
        if self._attack_button is None:
            return
        try:
            alive = self.codename().can_attack and not self._attacking
            self._attack_button.configure(state=("normal" if alive else "disabled"))
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
                                "label": "events.codename.attack"}]
        else:
            card["items"] = [{"label": "events.codename.attack",
                              "pill": "events.codename.attack.off"}]
        return {"cards": [
            {"title": None, "rows": [
                {"label": "events.web.read",
                 "value": (modelmod.ago(self._age()) if self._reading is not None
                           and not self._reading.error else "—")}]},
            card,
        ], "now": time.time(),
            "actions": [{"id": "refresh", "label": "events.refresh"}]}

    def web_press(self, action: str, args: dict) -> dict:
        """«Обновить» and «Атаковать сейчас» — the same two the window has."""
        if action == "refresh":
            return {"ok": self.refresh()}
        if action == "attack_codename":
            if not self.codename().can_attack:
                return {"error": "closed"}
            return {"ok": self.attack()}
        return {"error": "unknown"}
