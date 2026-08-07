"""The «Ралли» tab itself: raise a rally, and hear about the ones others raised.

One subject, two halves, and until now they lived in two files: the create form was a
class taking the app, the monitor was four widgets and six handlers on `Panel` itself
(docs/research/panel-tabs-refactor.md §10, wave 2). Both are here, built from the
runtime and nothing else — which is what lets the whole thing be opened on its own:

    C:\\Python312\\python.exe -m panel.tabs.rally --profile main

**Raising one.** The player picks what to rally — a «Роковая Элита» or an ordinary
world monster — sets the level (1–200 for both, as high as a season goes: typed into
the box, or one press on the button of a level actually rallied at), ticks the squads
that should each raise a rally, and a repeat count; «Запустить» then loops «find a
target of that kind and level → raise the rally with the next squad», N times over, and
«Стоп» interrupts it. The daily per-type cap (panel/rally_limits.py) is honoured — a run
stops when the «monster» budget for today is spent.

The game work is `actions/create_rally.md` — the scenario is the ability and this tab
only plays it (CLAUDE.md), so what a repeat that came to nothing says is the
SCENARIO's own words: it names every way a rally fails and the tab quotes the one it
gave rather than re-diagnosing the game itself. That includes the first of them —
**a squad that is not in the base cannot raise a rally**; the recipe asks before it
searches, and refuses saying whether the squad is marching, gathering, standing in
another rally, wiped or captured. The tab holds no such gate of its own.

**Where the squads are.** The line under the form says what each squad is doing and how
much stamina is left. It is read by `panel/runtime/squads.py` — on the RUNTIME, so this
tab reads it the same way whether it is in the shell or opened on its own — and it is
repainted from two places: a poll while somebody is looking at the tab, and the
«squad_state» trigger, which fires the moment a march message crosses the wire.

**Hearing about one.** A child process reads `push.alliance.march.*` off the wire; a
march carrying a `team=` is a rally, and the first line about each banner can be written
down, can ring a bell, and — if the operator asks for it — can be joined with the squads
«Автосбор» allows.

Those are THREE switches over ONE capture and they are not the same switch (#1237).
«Монитор стягиваний» means «write the armies down», and that is the whole of it — a
statistics file, for reading later. «Оповещать» and «Присоединяться сам» want the same
stream and nothing of the file. The capture is reference-counted against all three: it
comes up for whichever is on, stays up while any of them is, and the archive is written
only when the monitor box is ticked. Joining by itself therefore works with the monitor
off, which is what the person asking for it meant by it.

**«Автосбор»** — the squads a join may spend, the alliance drill, the banner-carrier and
the daily caps — is on THIS tab, under the switches that spend it. It was a page inside
«Настройки» until #1237, where the aggregator failed to draw it at all and nobody could
see the setting that made the joining work.
"""
from __future__ import annotations

import os
import threading
from tkinter import ttk

from ...runtime import game_process
from ...runtime import log as logmod
from ...runtime.paths import TOOLS, repo_rel
from ...widgets import (ScrollableFrame, install_numeric_field, tk_stringvar,
                        font as ui_font)
from ..base import PanelTab, TriggerSpec
from . import autorally as autorallymod
from . import limits as rallylimits
from .autorally import AutoRallyPage

# ---------------------------------------------------------------------------
# The two things a rally can be raised on: a «Роковая Элита» (searched under the
# «лупа»'s Boss tab) and an ordinary world monster (its Monster tab).
RALLY_KIND_ELITE, RALLY_KIND_MONSTER = "boss", "monster"
RALLY_KINDS = (RALLY_KIND_ELITE, RALLY_KIND_MONSTER)
# The level either of them may be searched at. One range for both kinds: a season puts
# levels far above the old elite ceiling on the map, and the game answers with whatever
# it has, so the tab offers the whole span and lets an empty answer say "not there".
# Same range as actions/create_rally.md and tools/rally_create.py SEARCH_LEVEL_RANGE.
RALLY_LEVEL_MIN, RALLY_LEVEL_MAX = 1, 200
# The levels a rally is actually raised on, each a button of its own beside the level
# box. Two hundred levels on a slider meant a drag and a squint to land on one of them,
# and the four that matter are always the same four.
RALLY_QUICK_LEVELS = (30, 35, 60, 120)
RALLY_SQUADS = (1, 2, 3, 4)
# A «Роковая Элита» rally is an ordinary-monster rally, so it counts against the
# "monster" daily cap in panel/rally_limits.py (DEFAULT_RALLY_LIMITS).
RALLY_ELITE_TYPE = "monster"
# Seconds to pause between two sends so the previous banner settles before the next
# find; interruptible by Stop.
RALLY_BETWEEN_S = 6.0


def _kind_key(base: str, kind: str) -> str:
    """The locale key of a status line for the rallied kind.

    Elite and monster do not share a wording in Russian (gender and case differ, so a
    substituted noun would read wrong), so the lines that name the target have a
    separate key per kind: `rally_tab.searching` / `rally_tab.searching_monster`.
    """
    return "rally_tab." + base + ("" if kind == RALLY_KIND_ELITE else "_" + kind)


def _switch(on) -> str:
    """The locale key for a switch's state, for a pill on the phone's copy of the tab."""
    return "rally.state.on" if on else "rally.state.off"


class _Stopped(Exception):
    """Raised inside the run loop when Stop was pressed — unwinds to the finally."""


class RallyTab(PanelTab):
    """Raising a rally, and the monitor that notices somebody else's."""

    ID = "rally"
    TITLE_KEY = "tab.rally"
    ORDER = 300
    PREFERRED_SIZE = "760x620"
    # The monitor has to be listening before the rally goes out, not from whenever
    # somebody happens to open the tab.
    EAGER = True
    LOCALE_NS = ("rally_tab", "rally", "autorally", "rally_limit", "log.rally",
                 "squads")
    NEEDS = frozenset({"daemon", "children", "actions"})
    # The flat keys this tab's settings used to be spelled with, so a profile that
    # predates the per-tab block keeps every value it had (§5 rule 1).
    LEGACY_KEYS = {"form": "rally_tab", "autorally": "autorally",
                   "monitor": "rally_monitor", "alert": "rally_alert",
                   "autojoin": "rally_autojoin"}
    #: A squad's state changes when a march does, and the game says so on the wire the
    #: moment it happens. The poll in `panel/runtime/squads.py` is the floor — fifteen
    #: seconds, so nothing is ever stale for long; this is the standing ear that makes
    #: the line change AS the squad leaves or lands. The pattern is the bare word
    #: `march` because every command that moves a squad carries it
    #: (`world.march.formation.new`, `push.alliance.march.refresh`, …) and the handler
    #: is cheap: it asks the runtime's reader to re-read, on a worker, taking no lease.
    TRIGGERS = (TriggerSpec(name="squad_state", event="march",
                            handler="refresh_squads"),)

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        import tkinter as tk

        master = rt.root
        self._run_stop = None       # threading.Event while a run is in flight, else None
        self._done = 0              # rallies raised in the current/last run (the status)
        self._proc = None           # the capture child, while it is running
        self._archiving = False     # …and whether it was launched writing the archive
        # teamUuids already alerted on this session. A rally emits create AND refresh
        # events, and an alert per event would ring four times for one стяг.
        self._seen: set = set()
        # WHAT EACH BANNER IS GOING FOR: `teamUuid -> targetContentId`, off the capture's
        # own line. The push carries it and the client's march record does not — 25 of the
        # push's 33 fields survive into `GetAllMarches()` and this is not one of them
        # (#1281) — so the wire is the only place a rally's KIND can be known before a
        # squad is sent, and this is where the panel keeps what it heard.
        self._targets: dict = {}
        # HOW BIG EACH BANNER IS: `teamUuid -> assemblyMarchMax`, off the same line. Also
        # wire-only, and the reason the player asked for this: a rally that has not left
        # yet can still have no seat free, and nothing in the client's own march record
        # says so. Measured during the Marshal event: nine banners, every one 5 of 5, and
        # every squad we owned was being sent at one of them (#1281).
        self._slots: dict = {}
        # …and what the JOIN has tried, per teamUuid: `(attempts, last-attempt)`. Kept
        # apart from `_seen` because they answer different questions — one banner is one
        # bell, but one banner may well be worth a second attempt at joining (#1281).
        self._join_at: dict = {}
        self._kind_var = tk.StringVar(master=master, value=RALLY_KIND_ELITE)
        # The box and the quick-pick buttons share this one variable: each button is a
        # radio whose value is its level, so pressing it writes the number into the box,
        # and a level typed by hand lights the matching button back up. `_level()` is the
        # one place that turns whatever it holds into a level.
        self._level_var = tk.StringVar(master=master, value=str(RALLY_LEVEL_MIN))
        self._repeats_var = tk.StringVar(master=master, value="1")
        self._squad_vars: dict = {s: tk.BooleanVar(master=master, value=False)
                                  for s in RALLY_SQUADS}
        self._status_var = tk_stringvar(master)
        # WHERE THE SQUADS ARE, and the stamina left (panel/runtime/squads.py). Read by
        # the runtime, not by this tab: the same reading gates the run and paints the
        # line, and a tab opened on its own gets it exactly as the shell does.
        self._squads_var = tk_stringvar(master)
        self._squads_off = None     # the unsubscribe, while this tab is on screen
        self._monitor_var = tk.BooleanVar(master=master, value=True)
        self._alert_var = tk.BooleanVar(master=master, value=True)
        # «Присоединяться сам» IS the «rally_auto_join» standing order, shown here as
        # well as on the Timers tab — not a second switch beside it (#1281). There used
        # to be two, stored in two files, driving two different halves, with no rule
        # saying which won: the same shape as the two sets of autoloot rules (#1272) and
        # the two rally counters. This variable is a VIEW of the trigger's state and a
        # setter for it; nothing about it is stored in this tab's own block any more.
        self._autojoin_var = tk.BooleanVar(master=master, value=False)
        self._hint = None
        self._quick_buttons: dict = {}
        # «Автосбор» — built here, drawn by `build()` onto this tab. Constructed in the
        # constructor and not in the draw, because its squad list is what the auto-join
        # spends and a profile applies its config before anything is on screen.
        self.autorally = AutoRallyPage(rt)

    # -- UI -----------------------------------------------------------------
    def build(self) -> None:
        # Everything on this tab is fixed-height and stacked; on a short window the
        # monitor block used to be the one that fell off the bottom edge.
        scroll = ScrollableFrame(self.parent)
        scroll.pack(fill="both", expand=True)
        body = scroll

        bar = ttk.Frame(body)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                "tab.rally").pack(side="left")

        self._build_form(body)
        self._build_monitor(body)
        # «Автосбор» — the squads a join may spend, the drill, the banner-carrier and
        # the daily caps. It was a page inside «Настройки» until #1237: everything on
        # it is about rallies, none of it is a knob of the panel, and the switch that
        # SPENDS the list is six lines above it here. It is drawn UNDER the switches
        # on purpose, so the tab reads «join by itself: on» and then «with these».
        autorally = ttk.Frame(body)
        autorally.pack(fill="x", padx=10, pady=(0, 6))
        self.autorally.build(autorally)

        self.tr(ttk.Label(body, foreground="#888", wraplength=640, justify="left"),
                "rally_tab.hint").pack(anchor="w", padx=10, pady=(0, 10))

    def _build_form(self, parent) -> None:
        """«Создать ралли»: what to rally, at what level, with which squads, how often."""
        form = ttk.LabelFrame(parent, padding=8)
        self.tr(form, "rally_tab.frame")
        form.pack(fill="x", padx=10, pady=(0, 8))

        krow = ttk.Frame(form)
        krow.pack(fill="x")
        self.tr(ttk.Label(krow), "rally_tab.kind").pack(side="left", padx=(0, 6))
        for kind in RALLY_KINDS:
            self.tr(ttk.Radiobutton(krow, value=kind, variable=self._kind_var),
                    "rally_tab.kind_" + kind).pack(side="left", padx=(0, 10))

        lrow = ttk.Frame(form)
        lrow.pack(fill="x", pady=(6, 0))
        self.tr(ttk.Label(lrow), "rally_tab.level").pack(side="left", padx=(0, 6))
        # A digits-only box for any level in the range, and a button per level a rally is
        # actually raised on — one press, no dragging. The buttons are radios over the same
        # variable, so the pressed one is always the level the box holds (and none looks
        # pressed while the box holds some other level, which is the truth).
        level_entry = ttk.Entry(lrow, width=5, textvariable=self._level_var,
                                font=ui_font(weight="bold"))
        install_numeric_field(level_entry)
        # Leaving the box writes back the level the run would actually use, so a typed
        # «999» never sits there while the search goes out on 200 — the reading and the
        # number on screen are the same thing or the tab is lying about what it will do.
        level_entry.bind("<FocusOut>", self._normalise_level, add="+")
        level_entry.bind("<Return>", self._normalise_level, add="+")
        level_entry.pack(side="left")
        ttk.Label(lrow, text="(%d–%d)" % (RALLY_LEVEL_MIN, RALLY_LEVEL_MAX),
                  foreground="#888").pack(side="left", padx=(6, 0))
        self.tr(ttk.Label(lrow), "rally_tab.level_quick").pack(side="left", padx=(14, 4))
        for quick in RALLY_QUICK_LEVELS:
            btn = ttk.Radiobutton(lrow, text=str(quick), value=str(quick), width=4,
                                  variable=self._level_var, style="Toolbutton")
            btn.pack(side="left", padx=2)
            self._quick_buttons[quick] = btn

        srow = ttk.Frame(form)
        srow.pack(fill="x", pady=(6, 0))
        self.tr(ttk.Label(srow), "rally_tab.squads").pack(side="left", padx=(0, 6))
        for squad in RALLY_SQUADS:
            ttk.Checkbutton(srow, text=str(squad),
                            variable=self._squad_vars[squad]).pack(side="left", padx=4)

        rrow = ttk.Frame(form)
        rrow.pack(fill="x", pady=(6, 0))
        self.tr(ttk.Label(rrow), "rally_tab.repeats").pack(side="left", padx=(0, 6))
        entry = ttk.Entry(rrow, width=6, textvariable=self._repeats_var)
        install_numeric_field(entry)
        entry.pack(side="left")

        # Where every squad is, and how much stamina is left. Above the buttons because
        # it is what «Запустить» is about to be judged against: a rally only goes out
        # from a squad standing in the base, and this is the line that says which ones
        # are. Repainted by the runtime's reader, not by anything this tab reads.
        qrow = ttk.Frame(form)
        qrow.pack(fill="x", pady=(8, 0))
        self.tr(ttk.Label(qrow), "squads.title").pack(side="left", padx=(0, 6))
        ttk.Label(qrow, textvariable=self._squads_var, foreground="#888",
                  wraplength=560, justify="left").pack(side="left")
        self._render_squads(self.rt.squads.latest())

        # A squad reading zero soldiers is usually a squad the client has not asked the
        # server about, and the whole of that is one scenario (#1285). The button STARTS
        # it and marks nothing: the line above moves when the READING moves.
        frow = ttk.Frame(form)
        frow.pack(fill="x", pady=(4, 0))
        self.tr(ttk.Button(frow, command=self._fill_squads),
                "rally_tab.fill_squads").pack(side="left")

        brow = ttk.Frame(form)
        brow.pack(fill="x", pady=(8, 0))
        self._launch_btn = self.tr(ttk.Button(brow, command=self._launch),
                                   "rally_tab.launch")
        self._launch_btn.pack(side="left")
        self._stop_btn = self.tr(ttk.Button(brow, command=self._stop_run),
                                 "rally_tab.stop")
        self._stop_btn.pack(side="left", padx=(6, 0))
        self._set_running(False)

        ttk.Label(form, textvariable=self._status_var, foreground="#888").pack(
            anchor="w", pady=(8, 0))

    def _build_monitor(self, parent) -> None:
        """The push-driven rally watcher: listen, alert, join.

        Beside the form that raises one, because it is the same subject seen from the
        other end (#1183) — and the switches are this tab's own now, not the shell's.
        """
        rally = self.tr(ttk.LabelFrame(parent, padding=8), "rally.frame")
        rally.pack(fill="x", padx=10, pady=(0, 6))
        top = ttk.Frame(rally)
        top.pack(fill="x")
        self.tr(ttk.Checkbutton(top, variable=self._monitor_var,
                                command=self._sync_capture),
                "rally.monitor").pack(side="left")
        # A rally is worth minutes and the alert used to be one log line that scrolled
        # past. Now it is a line the log paints as news, a bell, and — if the operator
        # asks for it — the join itself. All three ride one capture and none of them
        # owns it: they say what they want and `_sync_capture` decides.
        self.tr(ttk.Checkbutton(top, variable=self._alert_var,
                                command=self._sync_capture),
                "rally.alert").pack(side="left", padx=(12, 0))
        self.tr(ttk.Checkbutton(top, variable=self._autojoin_var,
                                command=self._on_autojoin_click),
                "rally.autojoin").pack(side="left", padx=(12, 0))
        self.tr(ttk.Button(top, command=self.join_now),
                "rally.join_now").pack(side="right")
        # Hint shows the active profile's rally log; refreshed on language/profile change.
        self._hint = ttk.Label(rally, foreground="#888", wraplength=620, justify="left")
        self._hint.pack(anchor="w", pady=(4, 0))
        self._refresh_hint()
        self.rt.i18n.hook(self._refresh_hint, key="rally-log-path")

    def _refresh_hint(self) -> None:
        """Say which file this profile's monitor writes to (path, in the log's language)."""
        if self._hint is None:
            return
        import tkinter as tk

        try:
            # repo_rel, not os.path.relpath: a profile directory on another drive makes
            # the bare call RAISE, and a display helper must never break the UI.
            self._hint.configure(
                text=self.t("rally.hint", path=repo_rel(self.rt.profiles.rally_log())))
        except tk.TclError:
            pass

    # -- lifecycle -----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Start the monitor if this profile had it on. There is no lazy data read here.

        Idempotent: the shell calls it once at boot (a capture must run whether or not
        anybody opens the tab) and again the first time the tab is shown. EAGER, so
        joining by itself works in a profile whose «Ралли» tab is never opened.
        """
        self._sync_capture()

    def on_show(self) -> None:
        """Somebody is looking: keep the squad line live for as long as they are.

        Watching is what starts the runtime's poll, and letting go is what stops it —
        so the game is only read for this while the tab is actually on screen. The run
        loop does not depend on it: it reads for itself, forced, before every send.
        """
        if self._squads_off is None:
            self._squads_off = self.rt.squads.watch(self._on_squads)
        # The box is a VIEW of the standing order, and the Timers tab draws the same
        # one — so it is re-read whenever somebody looks here, or the two would show
        # different things until this tab happened to be rebuilt (#1281).
        self._show_autojoin()

    def on_hide(self) -> None:
        self._unwatch_squads()

    def _unwatch_squads(self) -> None:
        off, self._squads_off = self._squads_off, None
        if off is not None:
            off()

    # -- the phone ------------------------------------------------------------
    #
    # A rally happens while you are away — that is the whole reason this screen exists.
    # It shows where the squads are and how much stamina is left, which is what decides
    # whether joining is even possible, and it offers the one press that is already a
    # scenario. Nothing here reads the game: the squad state is the runtime's own
    # reading (panel/runtime/squads.py), polled by the service and handed over as it is.
    WEB_SCREEN = True

    def web_view(self) -> "dict | None":
        state = self.rt.squads.latest()
        squads = []
        for squad in getattr(state, "squads", ()) or ():
            squads.append({
                "text": str(squad.index),
                "pill": f"squads.kind.{squad.kind}",
                "facts": ([{"label": "rally_tab.soldiers",
                            "value": str(squad.soldiers)}] if squad.soldiers else []),
                # A squad that has somewhere to be says when it gets there.
                "until": (squad.arrive_ms / 1000.0) if squad.arrive_ms else None,
            })
        cards = [{"title": "squads.title", "items": squads,
                  "empty": "squads.unread"}]
        if getattr(state, "stamina", -1) >= 0:
            cards.append({"title": None, "rows": [
                {"label": "rally_tab.stamina",
                 "value": f"{state.stamina}/{state.stamina_max}"}]})
        cards.append(self._web_autojoin_card())
        cards.append(self._web_autorally_card())
        return {"cards": cards, "now": __import__("time").time(),
                "actions": [{"id": "refresh", "label": "tabx.refresh"},
                            # The window's own «Наполнить отряды», mirrored: a squad
                            # reading zero is what stops a join, and the person holding
                            # the phone is exactly the one who cannot walk to the machine
                            # to press it (#1285).
                            {"id": "fill", "label": "rally_tab.fill_squads"}]}

    def _web_autojoin_card(self) -> dict:
        """The three switches, one per line, each saying on or off. READINGS.

        THE ANSWER TO «the boxes are ticked and nothing happens» (#1237), which is the
        one question this screen could not answer. Where the squads are it already
        showed; whether anything was going to be SENT to them lived only in the window,
        so a person away from the machine saw three squads standing at home beside a
        rally nobody joined and no way to tell which switch was the quiet one.

        Three lines and not one, because they are three separate things now: the archive
        is written or it is not, the bell rings or it does not, the join goes out or it
        does not, and any of them can be the reason nothing is happening.
        """
        return {
            "title": "rally.frame",
            "items": [
                {"label": "rally.monitor",
                 "pill": _switch(self._monitor_var.get())},
                {"label": "rally.alert",
                 "pill": _switch(self._alert_var.get())},
                {"label": "rally.autojoin",
                 "pill": _switch(self._autojoin_on())},
            ],
        }

    def _web_autorally_card(self) -> dict:
        """«Автосбор» as the phone sees it — the same block the tab now draws.

        It moved onto the tab in #1237 and so it has to be here: a control the window
        has and the phone does not is a control the person on the bus cannot see the
        state of, and this block is precisely the state that decides whether the
        auto-join does anything at all.

        Readings, no switches — the same line `web_press` holds. Every value is either
        digits (which need no translating) or a key; a cap is «spent/allowed», which is
        what silently stopped the joining once already.
        """
        page = self.autorally
        drill = [s for s in RALLY_SQUADS
                 if page._drill_state.get(s, autorallymod.DRILL_OFF)
                 != autorallymod.DRILL_OFF]
        limits, counts = rallylimits.read(self.rt)
        rows = [{"label": "rally_limit.type." + key,
                 "value": "%d/%d" % (counts.count_for(key), limits.limit_for(key))}
                for key in limits.types()]
        return {
            "title": "autorally.frame",
            "items": [
                ({"label": "autorally.squads",
                  # The digits are DATA and the same in every language; «none» is a
                  # word, so it is a key on the pill rather than a sentence in a value.
                  "detail": ", ".join(str(s) for s in self.join_squads())}
                 if self.join_squads() else
                 {"label": "autorally.squads", "pill": "rally.state.none"}),
                ({"label": "autorally.drill.squads",
                  "detail": ", ".join(str(s) for s in drill)}
                 if page._drill_on_var.get() and drill else
                 {"label": "autorally.drill.squads",
                  "pill": _switch(page._drill_on_var.get()) if not drill
                  else "rally.state.off"}),
                ({"label": "autorally.create.squads",
                  "detail": str(page._create_flagship)}
                 if page._create_flagship else
                 {"label": "autorally.create.squads", "pill": "rally.state.none"}),
                {"label": "autorally.create.elite",
                 "detail": str(page.create_elite_level())},
            ],
            "rows": rows,
        }

    def web_press(self, action: str, args: dict) -> dict:
        """«Обновить» — the squad reader's own asynchronous read, nothing else.

        …and «Наполнить отряды», the window's own press, which is a scenario and sends
        nobody anywhere: it asks the game for the army of every squad reading zero
        (#1285). Safe from a bus in a way a join is not — nothing leaves the base.

        Joining a rally from the phone is deliberately NOT here yet: the join is a
        send with squads chosen for it, and choosing them is «Автосбор» above — a
        reading here, editable only at the machine. A wrong squad sent from a bus is a
        squad that is not home when the next rally lands.
        """
        if action == "fill":
            return {"ok": self.rt.play_async(
                "fill_empty_squads", {"squads": list(RALLY_SQUADS)}, tag="fill_squads",
                on_done=lambda *_: self.rt.squads.refresh_async())}
        if action != "refresh":
            return {"error": "unknown"}
        self.rt.squads.refresh_async()
        return {"ok": True}

    def refresh_squads(self) -> None:
        """The «squad_state» trigger fired: read the squads again, off the Tk thread.

        Handed to the schedule as this tab's handler (`TRIGGERS`), and called on the Tk
        thread — so it must not block. `refresh_async` spawns the worker, and whoever is
        watching hears the reading through the bus.
        """
        self.rt.squads.refresh_async()

    def _on_squads(self, state) -> None:
        """A fresh reading arrived (on the Tk thread — the bus delivers there)."""
        self._render_squads(state)

    def _render_squads(self, state) -> None:
        """Put a reading into the line under the form."""
        import tkinter as tk

        try:
            self._squads_var.set(self._squads_text(state))
        except tk.TclError:                        # the window is going away
            pass

    def _squads_text(self, state) -> str:
        """One line: what each squad is doing, and the stamina pool.

        A reading that failed says so rather than showing an empty list — «nothing is
        out» and «nothing could be read» must never look the same, because the second
        one is what lets the run send anyway.
        """
        if state is None or not state.ok:
            return self.t("squads.unread")
        items = " · ".join(
            self.t("squads.item", index=squad.index,
                   state=self.t("squads.kind." + squad.kind))
            for squad in state.squads)
        pool = ("%d/%d" % (state.stamina, state.stamina_max)
                if state.stamina >= 0 and state.stamina_max > 0 else "?")
        return self.t("squads.strip", squads=items, stamina=pool)

    def on_profile_switch(self) -> None:
        """Bounce the capture onto the new profile, and re-read its caps.

        Restarting is deliberate: a running capture keeps writing to the OLD profile's
        log, so a switch has to redirect it.
        """
        self._stop_capture()
        self._refresh_hint()
        self.autorally.reload_limits()
        self._sync_capture()

    def on_language_change(self) -> None:
        self._refresh_hint()

    def panic(self) -> None:
        """«Стоп всё»: the capture off, and a run in flight asked to stop."""
        self._was = {"monitor": bool(self._monitor_var.get()),
                     "alert": bool(self._alert_var.get()),
                     "autojoin": bool(self._autojoin_var.get())}
        self._monitor_var.set(False)
        self._alert_var.set(False)
        self._set_autojoin(False)          # «Стоп всё» stops the standing order too
        self._stop_capture()
        self._stop_run()

    def resume(self) -> None:
        """«Включить обратно»: the standing orders that WERE standing, and no others.

        A run that was asked to stop stays stopped — starting it again is a press, not
        an undo.
        """
        was, self._was = getattr(self, "_was", None), None
        if not was:
            return
        self._monitor_var.set(was["monitor"])
        self._alert_var.set(was["alert"])
        self._set_autojoin(was["autojoin"])

    def shutdown(self) -> None:
        self._stop_run()
        self._stop_capture()
        self._unwatch_squads()

    # -- reading the controls ----------------------------------------------
    def _kind(self) -> str:
        """What is being rallied: `boss` (Fatal Elite) or `monster` (ordinary monster)."""
        kind = self._kind_var.get()
        return kind if kind in RALLY_KINDS else RALLY_KIND_ELITE

    def _level(self) -> int:
        """The level in the box as a whole number, inside the range whatever it holds.

        An empty box, junk, or a profile saved when the level was a slider float ("35.0")
        all read as a level here rather than as an error — the box is the only thing the
        run is aimed with, so it always answers with one.
        """
        try:
            level = round(float(self._level_var.get()))
        except Exception:                          # noqa: BLE001 — TclError on junk too
            return RALLY_LEVEL_MIN
        return max(RALLY_LEVEL_MIN, min(RALLY_LEVEL_MAX, level))

    def _normalise_level(self, _event=None) -> None:
        """Put the level the run would use back into the box (on leaving it / on Enter)."""
        level = str(self._level())
        if self._level_var.get() != level:
            self._level_var.set(level)

    def _repeats(self) -> int:
        try:
            return max(1, int(self._repeats_var.get()))
        except (TypeError, ValueError):
            return 1

    def _selected_squads(self) -> list:
        return [s for s in RALLY_SQUADS if self._squad_vars[s].get()]

    def join_squads(self) -> list:
        """The squads «Авторалли» allows a join to spend (the page's own list)."""
        return self.autorally.join_squads()

    # -- remembering the choices -------------------------------------------
    def config(self) -> dict:
        """The tab as it is stored in the profile.

        The form is read through the same readers the run is aimed with, so what is
        saved is exactly what «Запустить» would have used.
        """
        return {
            "form": {
                "kind": self._kind(),
                "level": self._level(),
                "squads": self._selected_squads(),
                "repeats": self._repeats(),
            },
            "autorally": self.autorally.config(),
            "monitor": bool(self._monitor_var.get()),
            "alert": bool(self._alert_var.get()),
            # NO «autojoin» HERE ANY MORE. The auto-join is the «rally_auto_join»
            # standing order and lives in the profile's `triggers.json`; storing a
            # second copy beside it is what made two boxes disagree (#1281).
        }

    def apply_config(self, raw) -> None:
        """Restore the tab from a profile's block; anything odd falls back to the default
        rather than being trusted (a hand-edited config cannot aim a run)."""
        raw = raw if isinstance(raw, dict) else {}
        form = raw.get("form")
        form = form if isinstance(form, dict) else {}
        kind = form.get("kind")
        self._kind_var.set(kind if kind in RALLY_KINDS else RALLY_KIND_ELITE)
        level = form.get("level")
        if not isinstance(level, (int, float)) or isinstance(level, bool):
            level = RALLY_LEVEL_MIN
        level = max(RALLY_LEVEL_MIN, min(RALLY_LEVEL_MAX, int(level)))
        self._level_var.set(str(level))
        squads = form.get("squads")
        squads = squads if isinstance(squads, list) else []
        for squad, var in self._squad_vars.items():
            var.set(squad in squads)
        repeats = form.get("repeats")
        if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
            repeats = 1
        self._repeats_var.set(str(repeats))

        self.autorally.apply_config(raw.get("autorally"))
        # The monitor is on unless the profile says otherwise: a capture nobody asked
        # to switch off is what makes the alert work on the day it matters.
        self._monitor_var.set(bool(raw.get("monitor", True)))
        self._alert_var.set(bool(raw.get("alert", True)))
        # …and the auto-join is READ from the standing order rather than from this
        # block. A profile written before they were one carries its old value over
        # once — a switch somebody left on must not be lost to a refactor.
        legacy = raw.get("autojoin")
        if legacy is None:
            self._show_autojoin()
        else:
            # …and the old key is CARRIED OVER AND THEN REMOVED, in that order. Left in
            # place it would be read again on the next start and put the standing order
            # back on after somebody had deliberately switched it off — a stale copy
            # resurrecting the state it was replaced by is worse than the two switches
            # were (#1281).
            if bool(legacy) and not self._autojoin_on():
                self._set_autojoin(True)
            else:
                self._show_autojoin()
            try:
                self.rt.settings.set_tab_config(self.ID, self.config(),
                                                self.LEGACY_KEYS)
            except Exception:             # noqa: BLE001 — a tab opened on its own
                pass

    def persist_vars(self) -> list:
        """Every control a change of has to be written to the profile (the container
        traces these; the tab itself never saves, so a profile switch can set them
        quietly)."""
        return [self._kind_var, self._level_var, self._repeats_var,
                self._monitor_var, self._alert_var, self._autojoin_var,
                *self._squad_vars.values(), *self.autorally.persist_vars()]

    # -- start / stop --------------------------------------------------------
    def _launch(self) -> None:
        if self._run_stop is not None:             # a run is already in flight
            return
        squads = self._selected_squads()
        if not squads:
            self._status("rally_tab.no_squads")
            return
        self._run_stop = threading.Event()
        self._done = 0
        self._set_running(True)
        threading.Thread(
            target=self._run_loop,
            args=(self._run_stop, self._kind(), self._level(), squads, self._repeats()),
            daemon=True).start()

    def _fill_squads(self) -> None:
        """«Наполнить отряды» — play the scenario and let the reader repaint the line.

        A press that STARTS something, which is the allowed kind (CLAUDE.md): it marks
        nothing and keeps no count of its own. The squad line above is redrawn by
        `panel/runtime/squads.py` when it reads the game again, so a squad that stays at
        zero after this stays at zero on screen — which is the truth about that squad.
        """
        self.rt.play_async("fill_empty_squads", {"squads": list(RALLY_SQUADS)},
                           tag="fill_squads",
                           on_done=lambda *_: self.rt.squads.refresh_async())

    def _stop_run(self) -> None:
        if self._run_stop is not None:
            self._run_stop.set()

    def _set_running(self, running: bool) -> None:
        """Enable Stop and disable Launch while a run is in flight (Tk thread)."""
        try:
            self._launch_btn.configure(state="disabled" if running else "normal")
            self._stop_btn.configure(state="normal" if running else "disabled")
        except Exception:                          # noqa: BLE001 — widget may be gone
            pass

    # -- the loop ------------------------------------------------------------
    def _run_loop(self, stop, kind, level, squads, repeats) -> None:
        """find a `kind` of `level` → raise a rally with each squad, `repeats` times over.

        One send at a time under the runtime's game claim; the daily «monster» cap gates
        it and Stop unwinds it. Runs off the Tk thread; all UI through `after`.
        """
        total = repeats * len(squads)
        try:
            limits, counts = rallylimits.read(self.rt)
            for rep in range(1, repeats + 1):
                for squad in squads:
                    if stop.is_set():
                        raise _Stopped
                    if not counts.allowed(RALLY_ELITE_TYPE, limits):
                        self._status("rally_tab.capped",
                                     cap=limits.limit_for(RALLY_ELITE_TYPE))
                        raise _Stopped
                    self._status(_kind_key("searching", kind),
                                 level=level, rep=rep, total=repeats)
                    out = self._one_send(stop, kind, level, squad)
                    if out is None:                # Stop pressed while waiting for busy
                        raise _Stopped
                    if out.ok:
                        counts = rallylimits.record(self.rt, counts, RALLY_ELITE_TYPE)
                        self._done += 1
                        self._log(_kind_key("raised", kind), squad=squad, level=level)
                        self._status("rally_tab.progress",
                                     done=self._done, total=total, squad=squad)
                        # That squad has just left the base — say so on the line rather
                        # than leaving it stale until the next poll.
                        self.rt.squads.refresh_async()
                    elif out.reason:
                        # The scenario's own sentence. It names six different ways a
                        # rally comes to nothing, and it is the authority on which one
                        # this was — the tab repeats it rather than guessing again.
                        self._status("rally_tab.refused", reason=out.reason)
                    else:
                        # No reason at all means the scenario BROKE rather than decided.
                        self._status("rally_tab.error_short")
                    if stop.wait(RALLY_BETWEEN_S):
                        raise _Stopped
            self._status("rally_tab.finished", done=self._done)
        except _Stopped:
            self._status("rally_tab.stopped", done=self._done)
        except Exception as exc:                   # noqa: BLE001 — never crash the panel
            self._log("rally_tab.error", error=exc)
            self._status("rally_tab.error_short")
        finally:
            self._run_stop = None
            self._after(lambda: self._set_running(False))

    def _one_send(self, stop, kind, level, squad):
        """One rally, played as the scenario. ``None`` if Stop won the wait for the game.

        Waits (interruptibly) for the game claim rather than skipping the iteration, so
        a timer coming due does not cost a repeat.
        """
        while not self.rt.game.claim("panel/rally"):
            self._status("rally_tab.busy")
            if stop.wait(2.0):
                return None
        try:
            return self.rt.actions.play(
                "create_rally",
                {"squad": squad, "level": level, "target": kind},
                on_event=lambda msg: self.rt.put(f"[rally] {msg}"), cancel=stop)
        finally:
            self.rt.game.release()

    # -- the capture, and the three switches that want it ---------------------
    #
    # ONE CAPTURE, THREE REASONS, AND THEY ARE NOT THE SAME SWITCH (#1237). A rally
    # rides `push.alliance.march.*`, and reading that stream is the only way the panel
    # hears one has gone out. Three things on this tab want to hear it:
    #
    #   * «Монитор стягиваний» — write the armies down (the JSONL archive). That IS the
    #     monitor, and it is all of it: statistics, in a file, for reading later.
    #   * «Оповещать» — say so in the log and ring.
    #   * «Присоединяться сам» — join it.
    #
    # They were wired as one because the archive-writer happened to be the thing
    # spawning the capture, so joining by itself needed a statistics file nobody asked
    # for, and switching the statistics off silently switched the joining off too. The
    # capture is now reference-counted against all three: it comes up for whichever of
    # them is on and stays up while ANY of them is, and the archive is written only
    # when the monitor box — the one that means «write it down» — is ticked.
    def _capture_wants(self) -> tuple:
        """``(wanted, archive)`` — whether to listen at all, and whether to write."""
        archive = bool(self._monitor_var.get())
        return (archive or bool(self._alert_var.get())
                or bool(self._autojoin_var.get())), archive

    #: The standing order this tab's «Присоединяться сам» box shows and sets. One
    #: state, two places that draw it — the Timers tab's own row is the other.
    AUTOJOIN_TRIGGER = "rally_auto_join"

    def _autojoin_on(self) -> bool:
        """Is the auto-join standing order on? Asked of the schedule, never remembered."""
        try:
            return bool(self.rt.schedule.trigger_enabled(self.AUTOJOIN_TRIGGER))
        except Exception:                 # noqa: BLE001 — a tab opened on its own
            return bool(self._autojoin_var.get())

    def _set_autojoin(self, on: bool) -> None:
        """Move the one state, and the box that shows it, together."""
        self._autojoin_var.set(bool(on))
        try:
            self.rt.schedule.set_trigger_enabled(self.AUTOJOIN_TRIGGER, bool(on))
        except Exception:                 # noqa: BLE001 — a tab opened on its own
            pass

    def _show_autojoin(self) -> None:
        """Re-read the box from the state, for when it was moved somewhere else."""
        self._autojoin_var.set(self._autojoin_on())

    def _on_autojoin_click(self) -> None:
        """The box was clicked: move the standing order, then the capture it needs."""
        self._set_autojoin(bool(self._autojoin_var.get()))
        self._sync_capture()

    def _sync_capture(self) -> None:
        """Bring the capture up, take it down, or re-point it — whatever the boxes say.

        Idempotent, and the ONE place the child's lifetime is decided: every switch
        calls this and none of them starts or stops anything itself. A change of the
        archive half restarts the child, because whether it writes is an argument it
        was launched with.
        """
        wanted, archive = self._capture_wants()
        if not wanted:
            self._stop_capture()
            return
        if self._proc is not None and self._archiving == archive:
            return
        if self._proc is not None:
            self._stop_capture()
        self._start_capture(archive)

    def _start_capture(self, archive: bool) -> None:
        out = self.rt.profiles.rally_log()         # per-profile log
        if archive:
            try:
                os.makedirs(os.path.dirname(out), exist_ok=True)
            except Exception:                      # noqa: BLE001 — the child says so too
                pass
            self.say("rally", "log.rally.started", path=repo_rel(out))
        else:
            # Listening for the joining and the alert, writing nothing — said in as
            # many words, or a capture running with «Монитор» unticked reads as a bug.
            self.say("rally", "log.rally.listening")
        cmd = [self.rt.children.python(), "-u",
               os.path.join(TOOLS, "rally_monitor.py")]
        # no --all-tcp: auto-detect the narrow game port, as the other captures do.
        cmd += ["--out", out] if archive else ["--no-archive"]
        # …and only THIS profile's client. Two accounts dial the same server port, so
        # without this the capture hears both alliances and the auto-join spends this
        # account's squads on the other one's banner. Empty when it cannot be told,
        # which keeps the old machine-wide behaviour rather than going deaf.
        for pid in game_process.profile_pids(self.rt.settings):
            cmd += ["--client-pid", str(pid)]
        mon = self.rt.children.spawn("rally", cmd,
                                     on_line=self._on_line, on_exit=self._on_exit)
        if not mon.start():
            # The capture is what the LISTENING switches ride, so a child that will
            # not start takes those down — leaving one ticked would promise a bell
            # that has nothing to ring for.
            #
            # THE STANDING ORDER IS NOT ONE OF THEM, and that correction cost a live
            # regression the same evening it was written (#1281): the auto-join is a
            # wire trigger of the schedule's and joins perfectly well with no capture
            # at all — it only loses the seats and the target's kind, which the capture
            # is the only source of. Switching it off here wrote «off» into the profile
            # for a reason that has nothing to do with whether the person wants to join.
            self._monitor_var.set(False)
            self._alert_var.set(False)
            if self._autojoin_on():
                self.say("rally", "rally.blind")
            return
        self._proc, self._archiving = mon, archive

    def _on_exit(self) -> None:
        self.say("rally", "log.rally.ended")
        self._proc = None
        self._monitor_var.set(False)
        self._alert_var.set(False)
        # …and the standing order stays exactly where the person left it (above).
        if self._autojoin_on():
            self.say("rally", "rally.blind")

    def _stop_capture(self) -> None:
        mon, self._proc = self._proc, None
        if mon is not None:
            self.say("rally", "log.rally.stopped")
            mon.stop()

    # -- the rally alert: a rally is worth minutes ---------------------------
    #
    # The monitor's line used to scroll past in a log six producers write to, and that
    # was the whole of it: the «Авторалли» page said which squads may go and NOTHING
    # read it. Now a rally can (a) be announced loudly, (b) be joined with one press,
    # and (c) be joined by itself.
    #
    # `team=<uuid>` in the monitor's own output is what makes a march a rally — a solo
    # march is tagged `solo` (tools/rally_monitor.py). The uuid is also the
    # de-duplicator: a rally emits create AND refresh events.
    def _on_line(self, line: str) -> bool:
        # The monitor's own line first, then the alert about it — the other way round
        # reads as an alert with no event under it.
        if line:
            self.rt.put(f"[rally] {line}")
        clean = logmod.strip_ansi(line)
        if "team=" not in clean:
            return False                  # a solo march, or a progress line
        team = clean.split("team=")[1].split()[0].strip()
        if not team:
            return False
        if "content=" in clean:
            content = clean.split("content=")[1].split()[0].strip()
            if content and content.isdigit():
                self._targets[team] = content
        if "slots=" in clean:
            seats = clean.split("slots=")[1].split()[0].strip()
            taken, _, cap = seats.partition("/")
            if cap.isdigit() and int(cap) > 0:
                self._slots[team] = cap
        # THE BELL IS ONE PER BANNER; THE JOIN IS NOT (#1281). `_seen` used to gate both,
        # and it was marked HERE — before the join had been tried — so a join the game
        # was too busy to start, or one every squad was out for, was never tried again
        # for that banner. That is one of the ways a rally went by with nothing said.
        #
        # So the mark now covers what it is honestly about: the ALERT. A banner
        # re-announces itself on the wire every few seconds and nobody wants the bell
        # each time. The JOIN gets its own, bounded, retry — see `_may_join_again`.
        fresh = team not in self._seen
        self._seen.add(team)
        if fresh and self._alert_var.get():
            self.say("rally", "rally.alert.fired", team=team)
            self._bell()
        if self._autojoin_var.get() and self._may_join_again(team):
            if self._nobody_to_send():
                return False
            self._after(self.join_now)
        return False                      # already logged above

    def _nobody_to_send(self) -> bool:
        """Is every squad the auto-join may spend out? Then it does not START (#1281).

        THIS TAB IS THE SECOND DRIVER, and the first version of the check missed it: the
        schedule's «rally_auto_join» trigger is not the only thing that plays the join —
        the capture's own reader raises one for every banner it hears, on a thread of its
        own, and that path never passes the schedule's gate. Measured live on the Marshal
        event: 41 pushes, 34 runs, and four of the six that joined something came through
        HERE rather than through the trigger.

        The reading is the same one and costs the same 0.06–0.10 s, it is taken fresh at
        the moment of the decision, and the reason lands in the schedule's roll-up so
        both drivers share one counter instead of each keeping its own.
        """
        reason = rallylimits.join_precondition(self.rt, self.join_squads())
        if not reason:
            return False
        try:
            self.rt.schedule.timers.note_skip("rally_auto_join", reason)
        except Exception:                 # noqa: BLE001 — a tab on its own has no schedule
            self.say("rally", reason)
        return True

    #: How long after an attempt at one banner the next may be made, and how many
    #: attempts a banner is worth. A rally re-announces itself every few seconds; joining
    #: on every push would be a press per push, and giving up after the first would be
    #: the bug this replaces. The recipe refuses a rally we are already in by itself, so
    #: a wasted retry costs two calls and says «nothing to join».
    JOIN_RETRY_SEC = 12.0
    JOIN_TRIES = 3

    def _may_join_again(self, team: str) -> bool:
        """May the auto-join have another go at ``team`` right now?

        Called from the capture's reader thread, which is the only writer of `_join_at`.
        """
        import time as _time

        tried, last = self._join_at.get(team, (0, 0.0))
        now = _time.monotonic()
        if tried >= self.JOIN_TRIES or now - last < self.JOIN_RETRY_SEC:
            return False
        self._join_at[team] = (tried + 1, now)
        return True

    def join_now(self) -> None:
        """Join the rallies that are out, with the squads the settings page allows.

        This is what makes the «Авторалли» page real: its squad list IS the recipe's
        `squads` argument. With no squad ticked the join would be a silent no-op that
        looked like it had worked, so it refuses and says which page to visit.
        """
        squads = self.join_squads()
        if not squads:
            self.say("rally", "rally.no_squads")
            return
        self.say("rally", "rally.joining",
                 squads=", ".join(str(s) for s in squads))
        threading.Thread(target=self._join_work, args=(squads,), daemon=True).start()

    #: How long a join waits for the game to be free before giving the place up. A rally
    #: is seconds long during an event and the claim is held by short things — a status
    #: read, a timer's errand, the auto-join TRIGGER doing the same job from the other
    #: side — so dropping the join the instant the game is busy threw away rallies that
    #: were free again a moment later. Measured on a live event: two banners in one
    #: minute lost to «занят», with the claim let go within a second of each (#1237).
    JOIN_CLAIM_WAIT_SEC = 4.0

    def _join_work(self, squads) -> None:
        """The join itself, off the Tk thread and under the game claim.

        Which of the ticked squads may actually be spent is the RECIPE's business
        (`actions/join_rally.md` keeps only the ones standing in the base and fails
        saying so when none is) — the tab hands over what the operator ticked and
        repeats what came back.

        WAITS FOR THE GAME rather than dropping the rally. Safe to block here: this runs
        on a worker of its own, never on Tk. Only when the wait runs out does it say so
        and let the banner go — and then it says it once, not per attempt.
        """
        import time as _time

        deadline = _time.time() + self.JOIN_CLAIM_WAIT_SEC
        while not self.rt.game.claim("panel/rally-join"):
            if _time.time() >= deadline:
                self.say("rally", "busy")
                return
            _time.sleep(0.15)
        try:
            out = self.rt.actions.play("join_rally", {"squads": squads},
                                       on_event=lambda msg: self.rt.put(f"[rally] {msg}"))
            if not out.ok and out.reason:
                self.say("rally", "rally_tab.refused", reason=out.reason)
        except Exception as exc:                   # noqa: BLE001 — never crash the panel
            self.say("rally", "rally_tab.error", error=exc)
        finally:
            self.rt.game.release()
        # The join has spent squads — the line under the form is stale until it is read.
        self.rt.squads.refresh_async()

    # -- talking to the panel (always from a worker thread) ------------------
    def _after(self, func) -> None:
        """Run ``func`` on the Tk thread; a window that has gone simply drops it.

        Through the runtime's hand-over queue rather than `root.after`: this tab's
        callers are all workers, and `after` from a worker waits on the event loop that
        draws every other open profile (#1226).
        """
        self.post(func)

    def _bell(self) -> None:
        import tkinter as tk

        try:
            self.rt.root.bell()
        except (tk.TclError, RuntimeError):
            pass

    def _status(self, key: str, **fmt) -> None:
        text = self.t(key, **fmt)
        self._after(lambda: self._status_var.set(text))

    def _log(self, key: str, **fmt) -> None:
        self._after(lambda: self.say("rally", key, **fmt))


def target_map(rt) -> str:
    """`team:contentId,…` for the banners this profile has HEARD about (#1281).

    The recipe parks it and the chunk resolves each id in `lw_world_monster` for the
    target's type and level — which is what «на кого идёт стяг» means, and what the
    budget's keys are filled from. Empty when the tab is not in this window: the join
    then classifies what it can (the invasion event's own lists) and says «unclassified»
    for the rest rather than calling it all `monster`.
    """
    tab = rt.tabs.get(RallyTab.ID) if rt.tabs is not None else None
    known = dict(getattr(tab, "_targets", {}) or {}) if tab is not None else {}
    return ",".join(f"{team}:{content}" for team, content in known.items())


def slot_map(rt) -> str:
    """`team:seats,…` — how many marches each banner holds, for the banners we heard.

    The join uses it with the occupancy it counts itself in the client's march list: a
    banner whose seats are all taken is not a candidate and is named `banner-full` in the
    run's report. A banner whose size was never heard is NOT filtered — an unheard size is
    not a full banner, and the refusal path is what catches those (#1281).
    """
    tab = rt.tabs.get(RallyTab.ID) if rt.tabs is not None else None
    known = dict(getattr(tab, "_slots", {}) or {}) if tab is not None else {}
    return ",".join(f"{team}:{cap}" for team, cap in known.items())


def join_squads(rt) -> list:
    """The squads an auto-join may spend, whether or not the tab is in this window.

    The «rally_auto_join» trigger fires on the schedule, and the schedule runs in a
    profile that may not show the «Ралли» tab at all — so the live page answers when it
    is there and the saved profile block answers when it is not (§5).
    """
    tab = rt.tabs.get(RallyTab.ID) if rt.tabs is not None else None
    if tab is not None:
        return tab.join_squads()
    block = rt.settings.tab_config(RallyTab.ID, RallyTab.LEGACY_KEYS)
    saved = block.get("autorally")
    raw = (saved or {}).get("squads") if isinstance(saved, dict) else None
    return [int(s) for s in raw] if isinstance(raw, list) else []
