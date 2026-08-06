"""The «Чеклист» tab: what the day still owes, read off the game rather than ticked.

**Nothing on this tab is marked by hand.** Every line is a READING — the game's own
answer to «is there any of this left» — and the panel draws it and nothing else. A box a
person ticks records what they REMEMBER doing, and remembering is the job the checklist
was supposed to take away; worse, the first time the two disagree (a collect the server
refused, a quota the second client spent, a heal that never went out) the box is the one
that is wrong and there is nothing on screen to say so.

So a line is done when the game says there is nothing outstanding, to-do when it says
there is and how much, **unknown** when it would not answer, and «not on today» for
Ghost Ops on the six days a week it is dark. Unknown is never drawn as done and never as
zero: «nobody knows» and «nothing left» are different answers, and telling them apart is
the entire value of reading instead of ticking (:mod:`.model`).

**Where the state comes from.** One scenario, `actions/read_daily_checklist.md`, one
round trip, one line of `key=value` pairs — the panel assembles no Lua and holds no gate
(`CLAUDE.md`). It is re-read: when the tab is first opened, every few minutes while it is
open, when a push that changes one of these facts crosses the wire, and whenever the
person presses «Обновить». Every count in it is the SAME expression the matching press is
gated on, so the checklist and the button can never disagree about how much work there is.

**There is no press on this tab except «Обновить»,** and that one only reads again. No
box to tick, no «Выполнить»: an errand is done because the game says so, and a button
that started something would be a button somebody expects to have ticked a line. The
abilities themselves live where they always did — on their own tabs and in «Таймеры» —
and this is the board that says whether they still need to run.

**The list is fixed in code and the person does not edit it**, in the window or on the
phone. It is the day, not somebody's notes about the day.

**The second half of the list is the part nothing can read yet** — sending the trucks
out, the radar, the arena, the alliance gifts, the treasures, the shop. Those lines say
«состояние неизвестно» and will keep saying it until a reading exists for them: they are
on the board rather than left off it because a checklist that quietly drops a third of
the day looks finished when it is not, and because each of them is a candidate for the
next reading (`docs/farming.md` is where the routine they come from is written down).
Moving a line up into the read group is how this tab grows — never by giving it a box.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ...widgets import ScrollableFrame, font as ui_font, tk_stringvar
from ..base import PanelTab
from . import model as modelmod

#: How a state looks in the window. A glyph is not a word — it needs no translating and
#: is the same in every language, which is why these four are literals and the sentence
#: beside them is a key.
_GLYPH = {
    modelmod.DONE:    ("✓", "#4caf50"),
    modelmod.TODO:    ("•", "#e0a84f"),
    modelmod.UNKNOWN: ("?", "#888888"),
    modelmod.CLOSED:  ("—", "#888888"),
}

#: The pushes worth re-reading on. Chosen for the facts that ARRIVE while nobody is
#: looking — a mate asking for help, a visitor turning up, a heal finishing — because
#: those are the ones a three-minute poll shows late. Everything else is caught by the
#: poll and by «Обновить»; a wider set would mean carrying more of the game's chatter
#: through the one capture all day for a board that is already never more than minutes
#: stale (`panel/runtime/wire.py`).
WIRE_PATTERNS = ("al.help", "visitor", "hospital")


class ChecklistTab(PanelTab):
    """The day's errands, the game's answer to each, and a countdown to the reset."""

    ID = "checklist"
    TITLE_KEY = "tab.checklist"
    ORDER = 20
    PREFERRED_SIZE = "760x620"
    LOCALE_NS = ("checklist",)
    #: The client, to read; the scenarios, to read WITH; the capture, to
    #: hear a push. All three are what a board that is true rather than remembered costs.
    NEEDS = frozenset({"daemon", "actions", "children"})
    WEB_SCREEN = True

    #: A re-read while the tab is simply open. Three minutes: far cheaper than the
    #: reading is worth (one round trip, ~0.2 s) and far more often than a day.
    REFRESH_SEC = 180
    #: On being shown again, re-read anything older than this rather than the full period.
    STALE_SEC = 60
    #: How often the status line's «прочитано N назад» and the countdown are redrawn.
    TICK_MS = 15_000
    #: A push is a hint, not a reading: wait this long so a burst of them costs one read.
    PUSH_DELAY_MS = 3_000

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        #: The last answer from the game. `None` until the first read comes back.
        self._reading = None
        self._busy = False
        self._body = None
        self._status = None
        self._refresh_button = None
        self._wire_off: list = []

    # -- the tab ------------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self._refresh_button = self.tr(ttk.Button(bar, command=self.refresh),
                                       "checklist.refresh")
        self._refresh_button.pack(side="left")

        self._status = tk_stringvar(self.rt.root)
        ttk.Label(bar, textvariable=self._status, foreground="#888").pack(
            side="left", padx=(12, 0))

        self._body = ScrollableFrame(self.parent)
        self._body.pack(fill="both", expand=True, padx=6, pady=(6, 10))
        self._render()

    def ensure_loaded(self) -> None:
        """Start listening, start the clock, and take the first reading.

        Not EAGER, so this runs the first time somebody opens the tab — a profile that
        never looks at the checklist pays nothing for it, and one that does gets a board
        that is true within a second of arriving.
        """
        self._listen()
        self._tick()
        self.refresh()

    def on_show(self) -> None:
        """Somebody is looking: re-read anything stale, and pick the watch back up.

        Re-arming here is what brings the tab back after «Стоп всё» — `panic` stops it
        asking, and coming back to the tab is the person saying to carry on. Both calls
        are idempotent, so an ordinary show costs a dictionary lookup.
        """
        self._listen()
        if self._age() > self.STALE_SEC:
            self.refresh()
        else:
            self._refresh_status()
        self.rt.tick.arm("checklist_poll", self.TICK_MS, self._tick)

    def on_language_change(self) -> None:
        self._render()

    def on_profile_switch(self) -> None:
        """A different account owes a different day: forget the reading and re-read."""
        self._reading = None
        self._render()
        self.refresh()

    def panic(self) -> None:
        """«Стоп всё»: stop asking, and stop listening.

        Both, because a push would otherwise arm the next read a second later and the
        board would carry on polling a game the person has just told the panel to leave
        alone. What is already on screen stays, and the status line says how old it is.
        Opening the tab again picks both back up (:meth:`on_show`).
        """
        self.rt.tick.disarm("checklist_poll")
        self.rt.tick.disarm("checklist_push")
        self._unlisten()

    def shutdown(self) -> None:
        self.rt.tick.disarm("checklist_poll")
        self.rt.tick.disarm("checklist_push")
        self._unlisten()

    # -- hearing the game ---------------------------------------------------
    def _listen(self) -> None:
        """Subscribe to the pushes worth re-reading on. Idempotent."""
        if self._wire_off:
            return
        for pattern in WIRE_PATTERNS:
            try:
                self._wire_off.append(self.rt.wire.subscribe(pattern, self._on_push))
            except Exception as exc:        # noqa: BLE001 — no capture is not fatal
                self.say("checklist", "checklist.log.no_wire", error=exc)
                break

    def _unlisten(self) -> None:
        """Close this tab's ear. The capture stops with its last subscriber."""
        for off in self._wire_off:
            try:
                off()
            except Exception:               # noqa: BLE001 — the ear is already closed
                pass
        self._wire_off.clear()

    def _on_push(self, command) -> None:
        """A push crossed (on the capture's reader thread — never draw from here).

        `None` is the ear closing rather than a command; the next poll re-reads anyway,
        so there is nothing to do about it but not treat it as news.
        """
        if command is None:
            return
        self.post(self._push_soon)

    def _push_soon(self) -> None:
        """Re-read shortly. Re-armed by each push, so a burst costs ONE reading."""
        self.rt.tick.arm("checklist_push", self.PUSH_DELAY_MS, self.refresh)

    # -- the reading --------------------------------------------------------
    def _tick(self) -> None:
        """Repaint the ages, and take a fresh reading when the old one is stale."""
        try:
            if not self._busy and self._age() >= self.REFRESH_SEC:
                self.refresh()
            else:
                self._refresh_status()
        finally:
            self.rt.tick.arm("checklist_poll", self.TICK_MS, self._tick)

    def _age(self) -> float:
        """Seconds since the last reading; a very large number when there is none."""
        if self._reading is None or not self._reading.at:
            return float("inf")
        return max(0.0, time.time() - self._reading.at)

    def refresh(self) -> bool:
        """Ask the game what the day still owes. `False` if it could not be asked now.

        One scenario, played through the runtime under the claim. A refusal — something
        else is driving the game — leaves the previous reading and its age on screen,
        which is the honest answer: it is what we know, and how old it is.
        """
        if self._busy:
            return False
        self._busy = True
        self._refresh_status()
        started = self.rt.play_async(
            modelmod.ACTION, tag="checklist",
            on_result=self._read_back, on_done=self._read_done)
        if not started:
            self._busy = False
            self._refresh_status()
        return started

    def _read_back(self, outcome) -> None:
        """The scenario finished (on the Tk thread). Its variables ARE the board."""
        at = time.time()
        if outcome is None or not getattr(outcome, "ok", False):
            reason = getattr(outcome, "reason", "") or ""
            self._reading = modelmod.Reading(error=reason or "failed", at=at)
        else:
            ctx = getattr(outcome, "ctx", None)
            raw = (getattr(ctx, "vars", {}) or {}).get(modelmod.VARIABLE)
            self._reading = modelmod.parse(raw, at=at)

    def _read_done(self) -> None:
        self._busy = False
        self._render()

    # -- the board ----------------------------------------------------------
    def states(self) -> list:
        """Every errand against the last reading — what both front-ends draw."""
        return modelmod.states(self._reading)

    def _render(self) -> None:
        if self._body is None:
            return
        for child in list(self._body.winfo_children()):
            child.destroy()
        for heading, states in modelmod.grouped(self._reading):
            self.tr(ttk.Label(self._body, font=ui_font(weight="bold")),
                    heading).pack(anchor="w", padx=6, pady=(10, 2))
            for state in states:
                self._render_row(state)
        self._refresh_status()

    def _render_row(self, state) -> None:
        frame = ttk.Frame(self._body)
        frame.pack(fill="x", padx=4, pady=1)
        frame.columnconfigure(1, weight=1)

        glyph, colour = _GLYPH.get(state.state, _GLYPH[modelmod.UNKNOWN])
        ttk.Label(frame, text=glyph, foreground=colour, width=2).grid(
            row=0, column=0, sticky="w")
        self.tr(ttk.Label(frame), state.errand.title_key).grid(
            row=0, column=1, sticky="w", padx=(4, 8))
        ttk.Label(frame, text=self._detail(state), foreground="#888").grid(
            row=0, column=2, sticky="e", padx=(0, 8))

    def _detail(self, state) -> str:
        """The words beside a row: what is left, in the panel's language."""
        if state.state == modelmod.UNKNOWN:
            return self.t("checklist.detail.unknown")
        if state.state == modelmod.CLOSED:
            return self.t("checklist.detail.closed")
        if state.errand.kind == modelmod.QUOTA:
            if state.used is not None:
                return self.t("checklist.detail.quota", used=state.used, cap=state.cap)
            return self.t("checklist.detail.left", n=state.left)
        if state.done:
            return self.t("checklist.detail.nothing")
        return self.t("checklist.detail.left", n=state.left)

    def _refresh_status(self) -> None:
        if self._status is None:
            return
        try:
            self._status.set(self._status_text())
        except tk.TclError:                 # the window is going away
            pass

    def _status_text(self) -> str:
        left = modelmod.hhmm(modelmod.seconds_to_reset())
        if self._busy:
            return self.t("checklist.status.reading")
        if self._reading is None:
            return self.t("checklist.status.never")
        if self._reading.error:
            return self.t("checklist.status.error", error=self._reading.error,
                          left=left)
        done, total = modelmod.progress(self.states())
        return self.t("checklist.status.read", done=done, total=total,
                      ago=modelmod.ago(self._age()), left=left)

    # -- the phone's copy ---------------------------------------------------
    def web_view(self) -> "dict | None":
        """The same board, drawn from the same reading — one card per group.

        The numbers are DATA (a count, «2/5»); the state is a `pill` and every word is a
        key, so the phone says them in whatever language the panel is set to. The only
        press on either front-end is «Обновить», because the only press there IS is
        «read it again».
        """
        done, total = modelmod.progress(self.states())
        cards = [{"title": None, "rows": [
            {"label": "checklist.web.progress", "value": "%d/%d" % (done, total)},
            {"label": "checklist.web.until_reset",
             "value": modelmod.hhmm(modelmod.seconds_to_reset())},
            {"label": "checklist.web.read",
             "value": (modelmod.ago(self._age()) if self._reading is not None
                       and not self._reading.error else "—")},
        ]}]
        for heading, states in modelmod.grouped(self._reading):
            cards.append({"title": heading, "empty": "checklist.empty",
                          "items": [self._web_item(s) for s in states]})
        return {"cards": cards, "now": time.time(),
                "actions": [{"id": "refresh", "label": "checklist.refresh"}]}

    def _web_item(self, state) -> dict:
        item = {"label": state.errand.title_key,
                "pill": "checklist.state." + state.state}
        if state.state in (modelmod.DONE, modelmod.TODO):
            item["detail"] = (
                "%d/%d" % (state.used, state.cap)
                if state.errand.kind == modelmod.QUOTA and state.used is not None
                else str(state.left))
        return item

    def web_press(self, action: str, args: dict) -> dict:
        """«Обновить», and nothing else. There is nothing here to mark or to spend."""
        if action == "refresh":
            return {"ok": self.refresh()}
        return {"error": "unknown"}
