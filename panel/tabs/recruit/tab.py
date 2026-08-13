"""The «Найм» tab: the two recruit banners, what each can do, and six presses.

**The state is READ, the doing is OFFERED** (`docs/panel-tabs.md`). Every number here is
the game's own answer — is a free pull waiting, when the next one comes, how many
tickets are held, what a pull costs — and there is nothing on this tab a person can tick.
A press plays `actions/recruit_draw.md` and then re-reads; whatever the reading says next
is what the row says next, including «still nothing free».

**Six buttons: x1 / x10 / x100 on each banner.** A pull that cannot be paid for is drawn
DEAD rather than hidden — a banner with no hundred, or an account with nine tickets, is
information; a missing button is a mystery. The free pull is spent by the x1 press when
one is available: that is the scenario's `free = auto`, and the button says so by naming
the price as «бесплатно».

The reverse-engineering — the two messages, why the size is not a flag, and where the
free pull's clock lives — is `docs/research/recruit-draw.md`.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ...widgets import font as ui_font, tk_stringvar
from ..base import PanelTab
from . import model as modelmod

#: What a reading that is not live is drawn in.
_GREY = "#888888"


class RecruitTab(PanelTab):
    """«Найм» — heroes and survivors, one card each, three presses apiece."""

    ID = "recruit"
    TITLE_KEY = "tab.recruit"
    ORDER = 235
    PREFERRED_SIZE = "620x520"
    LOCALE_NS = ("recruit",)
    #: The client, to read the banners; the scenarios, to read WITH and to pull with.
    NEEDS = frozenset({"daemon", "actions"})
    WEB_SCREEN = True

    #: A re-read while the tab is simply open. The free pull's countdown is redrawn from
    #: the same reading every tick, so this is about the tickets moving under it.
    REFRESH_SEC = 180
    #: On being shown again, re-read anything older than this.
    STALE_SEC = 60
    #: How often the countdown and the «прочитано N назад» line are redrawn. FIFTEEN
    #: SECONDS, not one, and the difference is not cosmetic: a repaint is ~20 Tk calls,
    #: it happens in EVERY open profile, and the panel's press budget from the phone is
    #: 1.5 s of the Tk thread (`panel/web/api.py`, `TK_TIMEOUT_SEC`). A tab that wakes
    #: the event loop every second on every profile spends that budget for everybody
    #: else. The countdown it draws is hours long, so a second's precision buys nothing.
    TICK_MS = 15_000
    #: How long after a pull before the banners are re-read. The server answers the pull
    #: first — the scenario has already waited for the account to move — so this is the
    #: margin, not the wait.
    AFTER_DRAW_MS = 1_500

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        #: The last answer from the game. `None` until the first read comes back.
        self._reading = None
        self._busy = False
        self._pulling = False
        self._status = None
        self._body = None
        #: `{(kind, count): button}` — redrawn dead or alive off the reading alone.
        self._buttons: dict = {}
        #: `{(kind, field): StringVar}` — the numbers, so a tick repaints without a
        #: rebuild of the whole board.
        self._values: dict = {}

    # -- the tab ------------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Button(bar, command=self.refresh), "recruit.refresh").pack(side="left")

        self._status = tk_stringvar(self.rt.root)
        ttk.Label(bar, textvariable=self._status, foreground=_GREY).pack(
            side="left", padx=(12, 0))

        self._body = ttk.Frame(self.parent)
        self._body.pack(fill="both", expand=True, padx=6, pady=(6, 10))
        for kind in modelmod.KINDS:
            self._build_banner(kind)
        self._render()

    def _build_banner(self, kind: str) -> None:
        """One banner's block: heading, three readings and the three presses."""
        frame = ttk.LabelFrame(self._body, text=self.t("recruit.kind." + kind))
        frame.pack(fill="x", padx=4, pady=(6, 2))

        for field, label_key in (("free", "recruit.free"),
                                 ("tickets", "recruit.tickets"),
                                 ("total", "recruit.total")):
            row = ttk.Frame(frame)
            row.pack(fill="x", padx=10, pady=1)
            row.columnconfigure(0, weight=1)
            self.tr(ttk.Label(row), label_key).grid(row=0, column=0, sticky="w")
            var = tk_stringvar(self.rt.root)
            self._values[(kind, field)] = var
            ttk.Label(row, textvariable=var, font=ui_font(weight="bold")).grid(
                row=0, column=1, sticky="e", padx=(8, 4))

        press = ttk.Frame(frame)
        press.pack(fill="x", padx=10, pady=(4, 8))
        for count in modelmod.COUNTS:
            button = self.tr(ttk.Button(press, width=10,
                                        command=lambda k=kind, c=count: self.draw(k, c)),
                             "recruit.pull.x%d" % count)
            button.pack(side="left", padx=(0, 6))
            self._buttons[(kind, count)] = button
        cost = tk_stringvar(self.rt.root)
        self._values[(kind, "cost")] = cost
        ttk.Label(press, textvariable=cost, foreground=_GREY).pack(side="left", padx=(8, 0))

    def ensure_loaded(self) -> None:
        """Start the clock and take the first reading, the first time anybody looks."""
        self._tick()
        self.refresh()

    def on_show(self) -> None:
        if self._age() > self.STALE_SEC:
            self.refresh()
        else:
            self._refresh_status()
        self.rt.tick.arm("recruit_poll", self.TICK_MS, self._tick)

    def on_hide(self) -> None:
        """Nobody is looking: stop the clock.

        A countdown redrawn behind another tab is Tk time taken from whatever the person
        IS looking at — and from the 1.5 s a press off the phone has to be answered in.
        `on_show` re-reads anything that went stale meanwhile, so nothing is lost by
        going quiet.
        """
        self.rt.tick.disarm("recruit_poll")

    def on_language_change(self) -> None:
        self._render()

    def on_profile_switch(self) -> None:
        """A different account has different banners and a different free pull."""
        self._reading = None
        self._render()
        self.refresh()

    def panic(self) -> None:
        self.rt.tick.disarm("recruit_poll")
        self.rt.tick.disarm("recruit_after_draw")

    def shutdown(self) -> None:
        self.rt.tick.disarm("recruit_poll")
        self.rt.tick.disarm("recruit_after_draw")

    # -- the reading --------------------------------------------------------
    def _tick(self) -> None:
        """Repaint the countdown, and re-read when the reading has gone stale.

        A tab nobody has drawn yet repaints nothing and asks the game nothing: the clock
        is armed by `ensure_loaded`, which only runs once somebody has looked (`LAZY`,
        docs/panel-tabs.md), and it is disarmed again the moment the tab is hidden.
        """
        try:
            if self._body is None:
                return
            if not self._busy and self._age() >= self.REFRESH_SEC:
                self.refresh()
            else:
                self._render()
        finally:
            self.rt.tick.arm("recruit_poll", self.TICK_MS, self._tick)

    def _age(self) -> float:
        if self._reading is None or not self._reading.at:
            return float("inf")
        return max(0.0, time.time() - self._reading.at)

    def refresh(self) -> bool:
        """Ask the game what the banners can do. `False` if it could not be asked now."""
        if self._busy:
            return False
        self._busy = True
        self._refresh_status()
        started = self.rt.play_async(
            modelmod.READ_ACTION, tag="recruit",
            on_result=self._read_back, on_done=self._read_done)
        if not started:
            self._busy = False
            self._refresh_status()
        return started

    def _read_back(self, outcome) -> None:
        at = time.time()
        if outcome is None or not getattr(outcome, "ok", False):
            reason = getattr(outcome, "reason", "") or ""
            self._reading = modelmod.Reading(error=reason or "failed", at=at)
            return
        ctx = getattr(outcome, "ctx", None)
        raw = (getattr(ctx, "vars", {}) or {}).get(modelmod.READ_VARIABLE)
        self._reading = modelmod.parse(raw, at=at)

    def _read_done(self) -> None:
        self._busy = False
        self._render()

    # -- the press ----------------------------------------------------------
    def draw(self, kind: str, count: int) -> bool:
        """Pull `count` times on `kind` — one scenario, and a re-read afterwards.

        Everything the pull IS lives in `actions/recruit_draw.md`: which banner, whether
        the free one is spent, whether the tickets are there and what to do when the
        server ignores it. This starts it and re-reads; whether anything was recruited is
        the game's answer, never this button's.
        """
        if self._pulling or kind not in modelmod.KINDS or count not in modelmod.COUNTS:
            return False
        self._pulling = True
        self._paint_buttons()
        started = self.rt.play_async(
            modelmod.DRAW_ACTION, {"kind": kind, "count": count}, tag="recruit",
            on_result=self._draw_back, on_done=self._draw_done)
        if not started:
            self._pulling = False
            self._paint_buttons()
            self.say("recruit", "recruit.log.busy")
        return started

    def _draw_back(self, outcome) -> None:
        """Say what came of it — the scenario's own report, never a guess of ours."""
        ctx = getattr(outcome, "ctx", None)
        report = (getattr(ctx, "vars", {}) or {}).get("report") or ""
        if outcome is not None and getattr(outcome, "ok", False):
            self.say("recruit", "recruit.log.pulled", report=report)
        else:
            self.say("recruit", "recruit.log.failed",
                     error=(report or getattr(outcome, "reason", "") or "?"))

    def _draw_done(self) -> None:
        self._pulling = False
        self._paint_buttons()
        #: Re-read rather than counting the pull: what was spent is the server's answer.
        self.rt.tick.arm("recruit_after_draw", self.AFTER_DRAW_MS, self.refresh)

    # -- the board ----------------------------------------------------------
    def _now(self) -> float:
        """The game's clock, carried forward by the seconds since the reading.

        The countdown is against the SERVER's time — the machine's own may be minutes
        out, and «бесплатно через 4:33» is exactly the sentence that must not be.
        """
        if self._reading is None or not self._reading.now:
            return 0.0
        return self._reading.now + self._age()

    def _free_words(self, banner) -> str:
        if banner is None:
            return "—"
        if banner.free:
            return self.t("recruit.free.now")
        if not banner.support:
            return self.t("recruit.free.none")
        left = banner.seconds_left(self._now())
        if left <= 0:
            return self.t("recruit.free.soon")
        return modelmod.hhmm(left)

    def _cost_words(self, banner) -> str:
        if banner is None:
            return ""
        parts = []
        for count in modelmod.COUNTS:
            price = banner.cost(count)
            if price:
                parts.append("x%d·%d" % (count, price))
        return " ".join(parts)

    def _render(self) -> None:
        if self._body is None:
            return
        for kind in modelmod.KINDS:
            banner = self._reading.banner(kind) if self._reading is not None else None
            self._set(kind, "free", self._free_words(banner))
            self._set(kind, "tickets",
                      "—" if banner is None else str(banner.have))
            self._set(kind, "total",
                      "—" if banner is None or not banner.limit
                      else "%d / %d" % (banner.total, banner.limit))
            self._set(kind, "cost", self._cost_words(banner))
        self._paint_buttons()
        self._refresh_status()

    def _set(self, kind: str, field: str, value: str) -> None:
        var = self._values.get((kind, field))
        if var is None:
            return
        try:
            var.set(value)
        except tk.TclError:                 # the window is going away
            pass

    def _paint_buttons(self) -> None:
        """A pull that cannot be paid for is dead — the same gate the press applies."""
        for (kind, count), button in self._buttons.items():
            banner = self._reading.banner(kind) if self._reading is not None else None
            alive = banner is not None and banner.affordable(count) and not self._pulling
            try:
                button.configure(state=("normal" if alive else "disabled"))
            except tk.TclError:             # the window is going away
                pass

    def _refresh_status(self) -> None:
        if self._status is None:
            return
        try:
            self._status.set(self._status_text())
        except tk.TclError:
            pass

    def _status_text(self) -> str:
        if self._busy:
            return self.t("recruit.status.reading")
        if self._reading is None:
            return self.t("recruit.status.never")
        if self._reading.error:
            return self.t("recruit.status.error", error=self._reading.error)
        return self.t("recruit.status.read", ago=modelmod.ago(self._age()))

    # -- the phone's copy ---------------------------------------------------
    def web_view(self) -> "dict | None":
        """The same board and the same six presses — one card per banner.

        Every word is a key and every number is data, so the phone says it in whatever
        language the panel is set to. The presses are offered because the ability IS a
        scenario (`CLAUDE.md`): what the phone runs is what the window runs, argument
        for argument. A pull that cannot be paid for is drawn as a dead row here too,
        for the same reason it is greyed in the window.
        """
        cards = [{"title": None, "rows": [
            {"label": "recruit.web.read",
             "value": (modelmod.ago(self._age())
                       if self._reading is not None and not self._reading.error else "—")}]}]
        for kind in modelmod.KINDS:
            banner = self._reading.banner(kind) if self._reading is not None else None
            rows = [{"label": "recruit.free", "value": self._free_words(banner)},
                    {"label": "recruit.tickets",
                     "value": "—" if banner is None else str(banner.have)}]
            if banner is not None and banner.limit:
                rows.append({"label": "recruit.total",
                             "value": "%d / %d" % (banner.total, banner.limit)})
            cost = self._cost_words(banner)
            if cost:
                rows.append({"label": "recruit.cost", "value": cost})
            card = {"title": "recruit.kind." + kind, "rows": rows}
            actions, dead = [], []
            for count in modelmod.COUNTS:
                entry = {"id": "pull_%s_%d" % (kind, count),
                         "label": "recruit.pull.x%d" % count}
                if banner is not None and banner.affordable(count) and not self._pulling:
                    actions.append(entry)
                else:
                    dead.append({"label": entry["label"], "pill": "recruit.pull.off"})
            if actions:
                card["actions"] = actions
            if dead:
                card["items"] = dead
            cards.append(card)
        return {"cards": cards, "now": time.time(),
                "actions": [{"id": "refresh", "label": "recruit.refresh"}]}

    def web_press(self, action: str, args: dict) -> dict:
        """The same seven presses the window has, and nothing the window has not."""
        if action == "refresh":
            return {"ok": self.refresh()}
        if action.startswith("pull_"):
            _, _, rest = action.partition("_")
            kind, _, count = rest.rpartition("_")
            if kind not in modelmod.KINDS or not count.isdigit():
                return {"error": "unknown"}
            return {"ok": self.draw(kind, int(count))}
        return {"error": "unknown"}
