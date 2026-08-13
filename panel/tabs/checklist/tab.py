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

**No ROW has a press on it, and none ever will.** An errand is done because the game says
so, and a «Выполнить» beside a line is a button somebody expects to have ticked that
line. What a GROUP may carry is a different matter (below); the rows stay readings.

**The state is READ; the doing is OFFERED.** Those are the two halves of the rule and
they are not in tension. Every errand that IS an ability the bot has carries a button —
«Выполнить» on nine of them, «Атаковать сейчас» on «Кодовое имя», which differs by a
locale key and nothing else — and pressing it plays the scenario and then re-reads the
board. **The tick follows the GAME, never the press**: a row that stays red after a press
is telling the truth about the game rather than failing to notice a click, and an errand
somebody did in the game itself goes green here without anybody pressing anything.

That is the whole distinction, and it is worth keeping sharp because it is the difference
between this board and a to-do list: a button may START work; only a reading may say it
is DONE.

**The list is fixed in code and the person does not edit it**, in the window or on the
phone. It is the day, not somebody's notes about the day.

**A group can be more than a heading over a list** (#1249). «Отправка грузовиков» is the
first of them: the counter the game answers («0 из 5» sent today, and how many could go
this minute), the press that will spend it, and the setting that says how the trucks are
to be improved before they go. It is FIRST on the board because it is the errand with the
shortest fuse — an idle fleet earns nothing and the allowance dies with the game's day.

**Its press is drawn and disabled, and that is the honest state of it.** There is no
dispatch scenario yet, so there is nothing for a button to play; a button that answered
«not yet» when pressed would be the same emptiness with a click in front of it. The
setting beside it manages only itself for now — the profile keeps it, and the day the
ability lands it is what the ability will be told to do.

**The last group is the part nothing can read yet** — the radar, the arena, the alliance
gifts, the treasures, the shop. Those lines say «состояние неизвестно» and will keep
saying it until a reading exists for them: they are on the board rather than left off it
because a checklist that quietly drops a third of the day looks finished when it is not,
and because each of them is a candidate for the next reading (`docs/farming.md` is where
the routine they come from is written down). Moving a line up out of that group is how
this tab grows — never by giving it a box.

**The blocks stand three to a row** (`COLUMNS`), in columns of equal width, and the three
columns are declared even while one block is all there is — so a group that comes back
takes the empty place beside its neighbour instead of everything jumping a third of the
tab sideways. Nothing here measures a column to decide how to wrap: the wrap is a
constant (`WRAP_PX`), for the reason written beside it. The phone keeps its cards one
under another, which is the shape of a phone rather than a difference of opinion
(`web_view`).

**Only one group is on right now** (#1275): «Кодовое имя». The other three are switched
off in the catalogue (`model.Group.shown`) rather than deleted, and the board is put back
one group at a time as each one's lines are watched answering truthfully in a live game —
the same bar a feature clears before it earns its ✅ in `docs/farming.md`. A group that is
off is off everywhere at once: no block here, no card on the phone, no press from either,
no line in «сделано N из M», and not even the round trip that would read it (`refresh`
plays only the scenarios the shown groups need). That is what makes it safe to leave the
code standing — an off group cannot half-exist.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ...widgets import ScrollableFrame, font as ui_font, tk_stringvar
from ..base import PanelTab
from . import model as modelmod

#: How many groups stand side by side. The board is read at a glance rather than
#: scrolled: a day is a couple of dozen lines, and three columns of blocks put the whole
#: of it on one screen where one column put a third of it there.
COLUMNS = 3

#: How wide a line inside a block may run before it is wrapped, in pixels — **a constant,
#: and it stays one** (#1211/#1215). The obvious version of this is to wrap each label to
#: the width its column turns out to have, which means a `<Configure>` handler that
#: re-wraps and so re-lays-out, which means the next `<Configure>`: «Дуэль VS» paid 2.3
#: seconds of page build for exactly that, and needed an idle-time coalescer, a style per
#: frame and a «is it already this wide» guard to get out of it. A fixed number costs one
#: measurement per label and cannot feed itself. It is a little narrower than a third of
#: the tab at its usual width, so a wrapped line does not push its own column wider.
WRAP_PX = 170

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
#:
#: `train.data` is the trade station's own state and it carries the two halves of the
#: truck counter: the client asks for it as `train.data` and the server pushes it back as
#: `push.train.data`, so ONE pattern hears both. `train.send` and `train.batch.send` are
#: the dispatches themselves — heard so that a truck sent from the phone, from the game
#: on another screen or by the person standing at the machine moves the counter here
#: within seconds instead of at the next poll. Without them the one number on this board
#: that a person changes by hand would be the stalest thing on it.
WIRE_PATTERNS = ("al.help", "visitor", "hospital",
                 "train.data", "train.send", "train.batch.send")

#: …and which reading each of them is news FOR. The tab listens for the shown groups only
#: (#1275): a push that would re-read a scenario no group is drawn from costs the capture
#: a filter all day and this board nothing. «Кодовое имя» has no push of its own — the
#: event's numbers are polled — so its entry is empty on purpose rather than missing.
WIRE_PATTERNS_BY_SOURCE = {
    modelmod.DAILY: WIRE_PATTERNS,
    modelmod.CODENAME: (),
}


class ChecklistTab(PanelTab):
    """The day's errands, the game's answer to each, and a countdown to the reset."""

    ID = "checklist"
    TITLE_KEY = "tab.checklist"
    ORDER = 20
    #: Three columns of blocks want the width, and the width was measured rather than
    #: guessed: with every group switched on and the longest of the eleven languages in
    #: them, the board asks for 975 px (`COLUMNS`, #1275). Below that the columns are
    #: squeezed and the widest block — the trucks' three radio buttons, which ttk cannot
    #: wrap — is clipped.
    PREFERRED_SIZE = "1000x700"
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
        #: …and the event's own, which is a second scenario because it is a second
        #: ability: «События» reads it too, and one copy of the Lua is what keeps the
        #: two tabs from ever showing different numbers for the same boss.
        self._codename = None
        #: Errands whose scenario is in flight, so a second press cannot start it twice.
        self._running: set = set()
        self._busy = False
        self._body = None
        self._status = None
        self._refresh_button = None
        self._wire_off: list = []
        #: How the trucks are to be improved before they go — a choice, not a reading,
        #: so it is a variable the profile keeps rather than something re-read.
        self._truck_mode = tk_stringvar(self.rt.root)
        self._truck_mode.set(modelmod.TRUCK_MODE_DEFAULT)

    # -- the tab ------------------------------------------------------------
    #: The style a group's frame wears — the heading in bold, so a block is found at a
    #: glance in a list of them. One style rather than a font on every heading: the
    #: blocks are rebuilt on every reading.
    BLOCK_STYLE = "Checklist.TLabelframe"

    def build(self) -> None:
        ttk.Style(self.parent).configure(self.BLOCK_STYLE + ".Label",
                                         font=ui_font(weight="bold"))
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
        self._codename = None
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
    def _patterns(self) -> tuple:
        """The pushes this board still cares about — the shown groups' and no others."""
        sources = modelmod.visible_sources()
        return tuple(pattern
                     for source, patterns in WIRE_PATTERNS_BY_SOURCE.items()
                     if source in sources for pattern in patterns)

    def _listen(self) -> None:
        """Subscribe to the pushes worth re-reading on. Idempotent."""
        if self._wire_off:
            return
        for pattern in self._patterns():
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

    def _readings(self) -> dict:
        """Each reading by the source that answers it — the pair `model` asks for."""
        return {modelmod.DAILY: self._reading, modelmod.CODENAME: self._codename}

    def _age(self) -> float:
        """Seconds since the OLDEST reading the board is still drawn from.

        The oldest rather than the newest: «прочитано N назад» is a promise about the
        whole board, and the stalest thing on it is what makes that promise true. A
        reading no shown group needs is left out of the sum entirely — it is not being
        taken, so its age says nothing about what is on screen (#1275) — and so is one
        that failed, because an attempt that answered nothing is not a reading.
        """
        sources = modelmod.visible_sources()
        stamps = [reading.at for source, reading in self._readings().items()
                  if source in sources and reading is not None and reading.at
                  and not reading.error]
        if not stamps:
            return float("inf")
        return max(0.0, time.time() - min(stamps))

    def _read_ago(self) -> str:
        """«0:42», or a dash when nothing the board draws has been read yet."""
        age = self._age()
        return "—" if age == float("inf") else modelmod.ago(age)

    def refresh(self) -> bool:
        """Ask the game what the day still owes. `False` if it could not be asked now.

        One scenario per reading a SHOWN group is drawn from, played one after the other
        through the runtime under the claim. A refusal — something else is driving the
        game — leaves the previous reading and its age on screen, which is the honest
        answer: it is what we know, and how old it is.

        While a source has no shown group its scenario is skipped rather than played and
        thrown away (#1275) — a poll every few minutes for numbers nobody is shown is a
        round trip an hour for a blank.
        """
        if self._busy:
            return False
        self._busy = True
        self._refresh_status()
        if modelmod.DAILY not in modelmod.visible_sources():
            return self._read_codename()
        started = self.rt.play_async(
            modelmod.ACTION, tag="checklist",
            on_result=self._read_back, on_done=self._read_codename)
        if not started:
            self._busy = False
            self._refresh_status()
        return started

    def _read_back(self, outcome) -> None:
        """The scenario finished (on the Tk thread). Its variables ARE the board."""
        self._reading = self._parsed(outcome, modelmod.VARIABLE)

    def _read_codename(self) -> bool:
        """The day is in; ask the event next.

        A second round trip rather than a second block bolted onto the first: the event
        reading is an ability of its own, played by «События» as well, and copying its
        Lua into the daily scenario is exactly how two front-ends come to disagree about
        one number. A VM call is about 0.15 s and this runs every few minutes.
        """
        if modelmod.CODENAME not in modelmod.visible_sources():
            self._read_done()
            return False
        started = self.rt.play_async(
            modelmod.CODENAME_ACTION, tag="checklist",
            on_result=self._codename_back, on_done=self._read_done)
        if not started:
            # A game that is busy is not an answer: the last one stays, and the status
            # line says how old it is. Recording «busy» as the event's reading would
            # blank the one group on the board because something else took the claim.
            self._read_done()
        return started

    def _codename_back(self, outcome) -> None:
        self._codename = self._parsed(outcome, modelmod.CODENAME_VARIABLE)

    def _parsed(self, outcome, variable: str):
        """One scenario's answer as a :class:`~.model.Reading`, failure included."""
        at = time.time()
        if outcome is None or not getattr(outcome, "ok", False):
            reason = getattr(outcome, "reason", "") or ""
            return modelmod.Reading(error=reason or "failed", at=at)
        ctx = getattr(outcome, "ctx", None)
        return modelmod.parse((getattr(ctx, "vars", {}) or {}).get(variable), at=at)

    def _read_done(self) -> None:
        self._busy = False
        self._render()

    # -- doing the errand ---------------------------------------------------
    def run(self, key: str) -> bool:
        """Play the scenario this errand is, then re-read. The tick follows the GAME.

        **This is the whole of «выполнение можно вызывать»**, and it is one mechanism for
        every line that has an ability — «Выполнить» on the nine ordinary ones,
        «Атаковать сейчас» on «Кодовое имя», which differs by a locale key and nothing
        else. A press starts work; what the row SAYS afterwards is the reading that
        follows, so a line that stays red after a press is telling the truth about the
        game rather than failing to notice a click.

        `False` when the errand has no scenario, is on a group that is switched off
        (#1275), is already running, or the game is busy — `play_async` holds the claim
        and says «busy» in the log for itself.

        The hidden half is checked HERE rather than at the widgets, because the widgets
        are only one of the two doors: `web_press` reaches this method with a key off the
        wire, and a phone that could name a row the window does not draw would be exactly
        the front-end drift the rule forbids.
        """
        errand = modelmod.BY_KEY.get(key)
        if (errand is None or not errand.runnable or key in self._running
                or not modelmod.is_visible(key)):
            return False
        self._running.add(key)
        self._render()
        title = self.t(errand.title_key)
        self.say("checklist", "checklist.log.run", title=title)
        started = self.rt.play_async(
            errand.scenario, tag="checklist",
            on_result=lambda outcome, title=title: self._ran_back(outcome, title),
            on_done=lambda key=key: self._ran(key))
        if not started:
            self._ran(key)
        return started

    def _ran_back(self, outcome, title: str) -> None:
        """Say what came of it — the scenario's own words, never a guess of ours."""
        if outcome is not None and getattr(outcome, "ok", False):
            self.say("checklist", "checklist.log.ran", title=title)
        else:
            self.say("checklist", "checklist.log.failed", title=title,
                     error=(getattr(outcome, "reason", "") or "?"))

    def _ran(self, key: str) -> None:
        """The scenario is over: forget it and ask the game what changed."""
        self._running.discard(key)
        self._render()
        self.refresh()

    # -- the board ----------------------------------------------------------
    def states(self) -> list:
        """Every errand against the last readings — what both front-ends draw."""
        return modelmod.states(self._reading, self._codename)

    def _render(self) -> None:
        """Draw one framed block per SHOWN group, three to a row.

        A block rather than a bold line over a run of rows: with three of the four groups
        off (#1275) the board is short, and the groups that come back come back one at a
        time — a frame with the group's name on it says where one ends and the next
        begins without anybody counting rows. Every future group is drawn by this same
        loop, so «as «Кодовое имя» looks» is not a thing to copy but the only shape there
        is.

        **Three columns, and the columns are declared whether or not anything stands in
        them.** `uniform` is what makes them the same width: without it the one block
        there is today would take the whole tab and then shrink to a third of it the day
        a second one appears, which is the layout jumping under somebody who has just
        learned where things are. With it, a block occupies its third from the first
        group onwards and the rest of the row is simply empty — the shape of the finished
        board, drawn early.

        What this deliberately does NOT do is measure anything: the wrap inside a block
        is :data:`WRAP_PX`, a constant, and there is no `<Configure>` handler here. See
        that constant for what the alternative cost «Дуэль VS».
        """
        if self._body is None:
            return
        for child in list(self._body.winfo_children()):
            child.destroy()
        for column in range(COLUMNS):
            self._body.columnconfigure(column, weight=1, uniform="checklist.group")
        for index, (group, states) in enumerate(
                modelmod.grouped(self._reading, self._codename)):
            block = self.tr(ttk.LabelFrame(self._body, labelanchor="nw",
                                           style=self.BLOCK_STYLE), group.title_key)
            block.grid(row=index // COLUMNS, column=index % COLUMNS, sticky="nsew",
                       padx=(6, 0), pady=(8, 2))
            for state in states:
                self._render_row(state, block)
            if group.key == modelmod.TRUCKS:
                self._render_trucks(block)
            elif group.key == modelmod.CODENAME:
                self._render_codename(states[0], block)
        self._refresh_status()

    def _render_codename(self, state, parent) -> None:
        """«Кодовое имя»: the two numbers the person is playing for.

        No press of its own — the row above already carries one, drawn by the same code
        that draws the other nine and labelled «Атаковать сейчас» because that is what
        the errand's `run_key` says. The counter is the group's own quota drawn large
        enough to read across the room, and the damage beside it is the figure the
        event's daily ranking is decided on.
        """
        attacks, need, dmg = modelmod.codename_counter(self._codename)
        counter = ttk.Frame(parent)
        counter.pack(fill="x", padx=10, pady=(0, 6))
        self._fact(counter, "checklist.codename.attacks",
                   ("—" if attacks is None or need is None
                    else "%d / %d" % (attacks, need)), bold=True)
        self._fact(counter, "checklist.codename.damage", modelmod.damage(dmg))

    def _fact(self, parent, key: str, value: str, bold: bool = False) -> None:
        """«Атак сегодня: 1 / 3» — a named number, on a line of its own.

        A line each rather than two pairs side by side: a block is a third of the tab
        wide (:data:`COLUMNS`), and «наибольший урон» beside a twelve-digit number does
        not fit in that at any language. Stacked, they cannot be clipped by a narrow
        column, and reading down a column of names is easier than reading along a row of
        them anyway.
        """
        line = ttk.Frame(parent)
        line.pack(fill="x", pady=1)
        self.tr(ttk.Label(line, foreground="#888", wraplength=WRAP_PX,
                          justify="left"), key).pack(side="left")
        number = ttk.Label(line, text=value)
        if bold:
            number.configure(font=ui_font(weight="bold"))
        number.pack(side="left", padx=(6, 0))

    def _render_trucks(self, parent) -> None:
        """«Отправка грузовиков»: the counter, the press, and how to improve them first.

        The first group of the board that is more than a list of rows. The counter is
        the group's own quota drawn large enough to read across the room; the press is
        DISABLED and says why; the three modes are a choice this tab keeps.
        """
        box = ttk.Frame(parent)
        box.pack(fill="x", padx=4, pady=(2, 6))

        counter = ttk.Frame(box)
        counter.pack(fill="x", padx=6, pady=(0, 2))
        self._fact(counter, "checklist.trucks.sent", self._truck_sent(), bold=True)
        self._fact(counter, "checklist.trucks.idle", self._truck_idle())

        press = ttk.Frame(box)
        press.pack(fill="x", padx=6, pady=(2, 2))
        # DISABLED, and that is the whole state of it: there is no dispatch scenario
        # yet, so there is nothing for a press to play (`CLAUDE.md` — an ability is a
        # scenario and the panel only plays them). A button that answered «not yet»
        # when pressed would be the same emptiness with an extra click in front of it;
        # a greyed one says so before anybody reaches for it. The phone shows the same
        # button in the same state (`web_view`), and the day the scenario lands both
        # come alive in the same commit.
        self.tr(ttk.Button(press, state="disabled"),
                "checklist.trucks.send").pack(anchor="w")
        # Under the button rather than beside it: «пока нельзя, нет сценария» is a
        # sentence, and a sentence does not stand next to a button in a third of a tab.
        self.tr(ttk.Label(press, foreground="#888", wraplength=WRAP_PX,
                          justify="left"), "checklist.trucks.not_yet").pack(
            anchor="w", pady=(2, 0))

        modes = ttk.Frame(box)
        modes.pack(fill="x", padx=6, pady=(4, 0))
        self.tr(ttk.Label(modes, wraplength=WRAP_PX, justify="left"),
                "checklist.trucks.mode").pack(anchor="w")
        for mode in modelmod.TRUCK_MODES:
            self.tr(ttk.Radiobutton(modes, value=mode, variable=self._truck_mode),
                    "checklist.trucks.mode." + mode).pack(anchor="w", padx=(12, 0))

    def _truck_sent(self) -> str:
        """«0 / 5», or a dash when the game did not answer. Digits need no language."""
        sent, cap, _idle = modelmod.truck_counter(self._reading)
        if sent is None or cap is None:
            return "—"
        return "%d / %d" % (sent, cap)

    def _truck_idle(self) -> str:
        _sent, _cap, idle = modelmod.truck_counter(self._reading)
        return "—" if idle is None else str(idle)

    def _render_row(self, state, parent) -> None:
        """One errand: the mark and its name, then what is left and the press under it.

        Two lines rather than one. A block is a third of the tab wide now, and the four
        things a row carries — a glyph, a name that is a sentence in some languages, a
        count and a button — do not stand side by side in that. The name gets the width
        (wrapped at :data:`WRAP_PX`, a constant); the count and the press share the line
        below it, which is also where the eye looks for «and how much of it is left».
        """
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=4, pady=(1, 4))
        frame.columnconfigure(1, weight=1)

        glyph, colour = _GLYPH.get(state.state, _GLYPH[modelmod.UNKNOWN])
        ttk.Label(frame, text=glyph, foreground=colour, width=2).grid(
            row=0, column=0, sticky="nw")
        self.tr(ttk.Label(frame, wraplength=WRAP_PX, justify="left"),
                state.errand.title_key).grid(
            row=0, column=1, columnspan=2, sticky="w", padx=(4, 4))
        ttk.Label(frame, text=self._detail(state), foreground="#888",
                  wraplength=WRAP_PX, justify="left").grid(
            row=1, column=1, sticky="w", padx=(4, 4))
        if state.errand.runnable:
            button = self.tr(ttk.Button(
                frame, width=16,
                command=lambda key=state.key: self.run(key)), state.errand.run_key)
            button.grid(row=1, column=2, sticky="e")
            if not self._may_run(state):
                button.state(["disabled"])

    def _may_run(self, state) -> bool:
        """Whether this row's button is alive.

        Dead while its scenario is already in flight, and dead when the errand is CLOSED
        — «Кодовое имя» between windows, Ghost Ops on the six days it is dark — because
        then the game has SAID there is nothing to reach and greying says so before
        anybody presses.

        **UNKNOWN leaves it alive**, and that is deliberate: «nobody knows» is not «you
        may not», and the ability holds its own gates (`CLAUDE.md`) — the scenario is
        the thing that knows whether it can run, and it says so in the log. A panel that
        refused on its own behalf would be a second, worse copy of that gate.
        """
        return state.key not in self._running and state.state != modelmod.CLOSED

    def _detail(self, state) -> str:
        """The words beside a row: what is left, in the panel's language."""
        if state.state == modelmod.UNKNOWN:
            return self.t("checklist.detail.unknown")
        if state.state == modelmod.CLOSED:
            # The errand's own wording — «сегодня не проводится» is true of Ghost Ops
            # and false of an event that opens again in two hours.
            return self.t("checklist.detail." + state.errand.closed)
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

    def _until_reset(self) -> str:
        """«2:05» — how long the quotas have left, on THIS profile's server day (#1333).

        One method because both front-ends draw it, and one boundary because both must
        draw the SAME number: the window's status line under the board and the phone's
        «до сброса» row. The boundary is the profile's own — two accounts can be on two
        warzones, so it comes off `rt.day` and never off a constant.
        """
        boundary = 0
        try:
            boundary = self.rt.day.boundary_ms()
        except Exception:                    # noqa: BLE001 — falls back to 02:00 UTC
            pass
        return modelmod.hhmm(modelmod.seconds_to_reset(day_end_ms=boundary))

    def _status_text(self) -> str:
        """«сделано 1 из 3 · прочитано 0:12 назад» — over the SHOWN groups only.

        Which reading it speaks for follows the board: a source no group is drawn from is
        not being taken, so neither its age nor its failure is news about anything on
        screen (#1275).
        """
        left = self._until_reset()
        if self._busy:
            return self.t("checklist.status.reading")
        sources = modelmod.visible_sources()
        live = [reading for source, reading in self._readings().items()
                if source in sources and reading is not None]
        if not live:
            return self.t("checklist.status.never")
        failed = next((reading for reading in live if reading.error), None)
        if failed is not None:
            return self.t("checklist.status.error", error=failed.error, left=left)
        done, total = modelmod.progress(self.states())
        return self.t("checklist.status.read", done=done, total=total,
                      ago=self._read_ago(), left=left)

    # -- remembering the one choice on the board ----------------------------
    def config(self) -> dict:
        """The tab as the profile keeps it — one line, because there is one choice.

        Nothing else on this board is stored: every row is a reading, and a reading
        that was written down would be a reading somebody could disagree with.
        """
        return {"truck_mode": modelmod.truck_mode(self._truck_mode.get())}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._truck_mode.set(modelmod.truck_mode(raw.get("truck_mode")))

    def persist_vars(self) -> list:
        return [self._truck_mode]

    # -- the phone's copy ---------------------------------------------------
    def web_view(self) -> "dict | None":
        """The same board, drawn from the same reading — one card per group.

        The numbers are DATA (a count, «2/5»); the state is a `pill` and every word is a
        key, so the phone says them in whatever language the panel is set to.

        **Every press the window has, the phone has** — «Обновить», and one per errand
        that is a scenario, carrying the errand's key in its args. It plays exactly what
        the window plays and marks exactly as much as the window marks, which is nothing:
        the reading that follows is what moves the row.

        **And exactly the groups the window draws**, because both ask `model.grouped`
        (#1275). A group switched off has no card here, no rows in the progress count and
        no press — the phone cannot reach what the machine does not show.

        **The cards stay one under another, and that is not the window falling out of
        step with the phone.** The window stands its blocks three to a row (`COLUMNS`)
        because it has a thousand pixels across and a day is two dozen lines; a phone has
        a column of about four hundred and scrolls, so the same three-across would be
        three unreadable slivers. What must match between the two front-ends is WHAT is
        there — every group, every reading, every press — and that is what `grouped`
        guarantees. How many of them stand side by side is the shape of the glass, not a
        fact about the game, so **do not «align» this with the window's three columns.**
        """
        done, total = modelmod.progress(self.states())
        cards = [{"title": None, "rows": [
            {"label": "checklist.web.progress", "value": "%d/%d" % (done, total)},
            {"label": "checklist.web.until_reset",
             "value": self._until_reset()},
            {"label": "checklist.web.read", "value": self._read_ago()},
        ]}]
        for group, states in modelmod.grouped(self._reading, self._codename):
            card = {"title": group.title_key, "empty": "checklist.empty",
                    "items": [self._web_item(s) for s in states]}
            if group.key == modelmod.TRUCKS:
                card["rows"] = self._web_truck_rows()
                card["items"] += self._web_truck_items()
            elif group.key == modelmod.CODENAME:
                card["rows"] = self._web_codename_rows()
            cards.append(card)
        return {"cards": cards, "now": time.time(),
                "actions": [{"id": "refresh", "label": "checklist.refresh"}]}

    def _web_codename_rows(self) -> list:
        """The group's two numbers, exactly as the window draws them under the row.

        The press is not here: it is on the ROW, like every other errand's, because
        «Атаковать сейчас» is an ordinary errand button with an unusual verb (`.model`).
        The phone gets it from `_web_item` along with the other nine.
        """
        attacks, need, dmg = modelmod.codename_counter(self._codename)
        return [{"label": "checklist.codename.attacks",
                 "value": ("—" if attacks is None or need is None
                           else "%d / %d" % (attacks, need))},
                {"label": "checklist.codename.damage",
                 "value": modelmod.damage(dmg)}]

    def _web_truck_rows(self) -> list:
        """The group's counter, as the window draws it above the same rows."""
        return [{"label": "checklist.trucks.sent", "value": self._truck_sent()},
                {"label": "checklist.trucks.idle", "value": self._truck_idle()}]

    def _web_truck_items(self) -> list:
        """The press and the three modes — the same two things, and no button.

        **The press is here and it carries no action**, exactly as the window's is drawn
        greyed: there is no dispatch scenario yet, and `web_press` runs scenarios and
        nothing else (`CLAUDE.md`). A phone that could press it would be reaching for an
        ability the machine does not have either.

        The mode is a READING here and a radio in the window — the same shape «Ралли»
        settled on for its switches. The phone can see which of the three is on, which is
        what somebody away from the machine needs; changing what the dispatch will spend
        belongs where the person can see the fleet.
        """
        chosen = modelmod.truck_mode(self._truck_mode.get())
        items = [{"label": "checklist.trucks.send", "pill": "checklist.trucks.not_yet"}]
        items += [{"label": "checklist.trucks.mode." + mode,
                   "pill": ("checklist.trucks.chosen" if mode == chosen
                            else "checklist.trucks.unchosen")}
                  for mode in modelmod.TRUCK_MODES]
        return items

    def _web_item(self, state) -> dict:
        # The pill is the state, except that a CLOSED errand says it in its own words —
        # the same distinction the window draws (`_detail`), so the two agree.
        item = {"label": state.errand.title_key,
                "pill": ("checklist.state." + (state.errand.closed
                                                if state.state == modelmod.CLOSED
                                                else state.state))}
        if state.state in (modelmod.DONE, modelmod.TODO):
            item["detail"] = (
                "%d/%d" % (state.used, state.cap)
                if state.errand.kind == modelmod.QUOTA and state.used is not None
                else str(state.left))
        # The same press the window draws on this row, offered on the same terms
        # (`_may_run`) — the phone must not be able to reach what the machine cannot.
        if state.errand.runnable and self._may_run(state):
            item["actions"] = [{"id": "run", "label": state.errand.run_key,
                                "args": {"key": state.key}}]
        return item

    def web_press(self, action: str, args: dict) -> dict:
        """«Обновить», and playing one errand. There is still nothing here to MARK.

        The two presses the window has and no others. `run` reaches the same
        :meth:`run` — same gate, same scenario, same re-read — so a phone cannot start
        anything the machine could not, and cannot tick anything either way.
        """
        if action == "refresh":
            return {"ok": self.refresh()}
        if action == "run":
            return {"ok": self.run(str((args or {}).get("key") or ""))}
        return {"error": "unknown"}
