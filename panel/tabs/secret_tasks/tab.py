"""The «Secret Tasks» tab: the starred hero-dispatch tiles the alliance can raid.

This tab keeps the **starred** secret tasks — the raids worth a march — on screen, each
with a per-second countdown to the moment it becomes raidable, and offers the two things
a person does with one: rob it (`hero.dispatch.steal`) or forward it into chat.

**Where the list comes from — the wire, not a VM scan.** The passive capture
(:mod:`~panel.tabs.secret_tasks.capture`, whose block is on this tab) reads the tiles off
the game stream as the map moves and writes them to a checkpoint every tick, each record
carrying the full coordinates + `completed_at` / `expires_at` a countdown needs. This
tab's ongoing feed is that checkpoint (:meth:`_fetch_scan`): a finding crossing the wire
nudges the tab to merge the freshly-written file, so a tile the capture just saw appears
with a real timer and no game round-trip. The Lua VM is read **once**, as the first-open
snapshot (:meth:`_fetch_vm`), to seed the list before the capture has flushed anything.

When a tile's countdown reaches zero it is raidable: its row is highlighted, and a slow
background poll (~30 s) starts re-reading the game — if the tile is gone (expired or
looted out) the row drops, and while auto-loot is ticked a raidable tile is robbed. That
poll is a targeted per-tile *verify* under auto-loot (a raid spends the scarce daily
budget, so it wants the game's authoritative word, not a stale checkpoint), distinct from
the wire feed that populates the list. It runs only while at least one row is ready, so an
idle tab never touches the daemon.

What is on the tab is an in-memory list for the session, not a store — closing the panel
forgets it, which is fine: the first-open VM snapshot re-seeds it and the wire refills it.

THE THREE STANDING ORDERS ARE THIS TAB'S OWN NOW. The capture, «Автолут ★» and
«Автообъезд карты» used to be checkboxes here whose every variable and every handler
lived on `Panel`; each is a small class beside this one, holding its own child processes
and its own loop (docs/research/panel-tabs-refactor.md §9.1/§9.3). The «уровень от / до»
range doubles as the list's display filter — a starred tile shows only while its level is
inside it, so the operator sees exactly the tiles auto-loot is about to weigh.

THE LIST IS A TABLE (#1209). It was a stack of hand-packed rows, each label carrying its
own width, which is why nothing lined up under anything: a `ttk.Treeview` gives the
columns one width apiece, a heading that sorts, and a header that stays put. The two
row actions moved with it — a click on the **coordinate** column walks the camera to the
tile, and «Собрать» / «Поделиться» act on the selected row, from the strip under the
table and from the right-click menu.

The tab also carries the panel's **«Переход по координатам»**, the block «Главная» lost
in #1183, because this is the tab whose work is coordinates: a tile read off the wire, a
tile a member named in chat, the tile the last jump went to. It jumps through the very
same `rt.game.jump` the table's links use, and remembers where it has been per profile.

Kept Tk-thin: the two game round trips (scan, steal) and the share run on background
threads and degrade gracefully — no daemon, no game, or a manager not loaded yet leaves
the list empty and never crashes the tab.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ...runtime import captures as capturemod
from ...widgets import (NumericEntry, numeric_spinbox, tk_stringvar,
                        font as ui_font)
from ..base import PanelTab, TriggerSpec
from .autoloot import AutoLoot
from .capture import Capture
from .sweep import Sweep

# The star glyph in front of a row and the icons for the two row states: a tile still
# counting down to raidability, and one that is ready to loot now.
STAR_GLYPH = "⭐"
TYPE_GLYPH = "🗡️"
READY_GLYPH = "✅"

# The amber the countdown is drawn in, and the green a ready row switches to.
TIMER_COLOR = "#e0a84f"
READY_COLOR = "#4fe08a"

# The table's columns: (id, locale key of the heading, width in px, anchor, stretch).
# The state column is the one that takes the slack — it carries the longest sentence
# («готово к сбору · истекает через 1:02:03») and the one that varies most by language.
# The server has a column of its own rather than a `#534` glued to the coordinate: it is
# what tells a neighbour's tile from a stranger's at a glance, and it is what «не грабить
# на своём сервере» is about.
COLUMNS = (
    ("coords", "secrettasks.col.coords", 150, "w", False),
    ("server", "secrettasks.col.server", 90, "w", False),
    ("lvl", "secrettasks.col.level", 110, "w", False),
    ("state", "secrettasks.col.state", 250, "w", True),
    ("slots", "secrettasks.col.slots", 90, "center", False),
    ("action", "secrettasks.col.action", 110, "center", False),
)

# The two columns a click DOES something in (task #1209). Named rather than indexed, so
# re-ordering COLUMNS cannot silently make «Ограблено» the link.
LINK_COLUMN = "coords"
ACTION_COLUMN = "action"

# How many jumps the «куда ходил» list remembers. One account's tiles are not another's,
# so it belongs to the profile like every other setting here.
JUMP_HISTORY_MAX = 20

# How often the ready-row poll re-reads the game once a tile is raidable. Slow on
# purpose — a raidable tile lives for minutes, and this is the list's own safety net,
# not the auto-loot watcher.
POLL_MS = 30_000

# The two channels a task can be forwarded to. The room ids are built from the player's
# own server / alliance, read once and cached (see `_self_ids`).
SHARE_ALLIANCE = "alliance"
SHARE_WORLD = "world"


class SecretTasksTab(PanelTab):
    """The starred-secret-task list, its timers, its two actions and its three orders."""

    #: An alliancemate sharing a task is a push, not something to poll for — so the
    #: tab offers the standing order that re-merges the checkpoint when one lands.
    TRIGGERS = (TriggerSpec(name="secret_task_share",
                            event="alliance.share.mission.add",
                            handler="refresh_live"),)

    ID = "secret_tasks"
    TITLE_KEY = "tab.secret_tasks"
    ORDER = 260
    PREFERRED_SIZE = "900x700"
    LOCALE_NS = ("secrettasks", "secret", "sweep", "autoloot", "tabx")
    NEEDS = frozenset({"daemon", "children", "actions"})
    # The capture, the watcher and the sweep are standing orders: they have to be
    # RUNNING, not waiting for somebody to open the tab.
    EAGER = True
    # Identity, deliberately: §5 rule 3 forbids renaming a key in the wave that moves
    # it, so the block spells every one of them exactly as the flat profile did.
    LEGACY_KEYS = {k: k for k in (
        "monitor_kind", "monitor_interval", "secret_monitor",
        "filter_star", "filter_pending", "filter_can_loot",
        "filter_level_from", "filter_level_to",
        "autoloot", "autoloot_level_from", "autoloot_level_to",
        "map_sweep", "sweep_centre_x", "sweep_centre_y")}
    # `autoloot_skip_own_server` and the four `coord_*` keys are NOT here on purpose:
    # they are new to this tab (#1209) and were never spelled flat on the profile, so
    # there is no old spelling to keep in step with.

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        master = rt.root
        self.loaded = False
        self._busy = False
        self._ticking = False
        # uuid (str) -> row record. The record carries the task data, its countdown
        # StringVar and the row's frame, so a tick can update the timer in place and a
        # collect/clear can drop the row without a full re-read.
        self._rows: dict = {}
        # Tasks robbed by hand this session: a rescan must not re-add one the server has
        # not yet dropped from `allianceTask`.
        self._collected: set = set()
        # uuids auto-loot has already fired at this session — one attempt per tile, so a
        # 30-s poll on a spent budget does not re-send every tick.
        self._auto_attempted: set = set()
        # Whether the ready-row poll is currently scheduled.
        self._polling = False
        # Cached (server, allianceId) for the chat room ids — read once, live.
        self._ids = None
        # The player's OWN server, cached the same way: what «не грабить на своём
        # сервере» compares a tile against. 0 = not read yet / unreadable.
        self._own_server = 0
        self._status_var = tk_stringvar(master)
        self._combo = None
        # -- the table ------------------------------------------------------
        self._tree = None
        self._body = None
        self._empty = None
        self._sort = None            # (column id, reversed) once a heading is clicked
        self._collect_btn = self._share_btn = self._goto_btn = None

        # -- the controls the three orders read ------------------------------
        self.monitor_var = tk.BooleanVar(master=master, value=False)
        self.interval_var = tk.StringVar(master=master, value="15")
        self.star_var = tk.BooleanVar(master=master, value=False)
        self.pending_var = tk.BooleanVar(master=master, value=False)
        self.can_loot_var = tk.BooleanVar(master=master, value=False)
        self.filter_from_var = tk.StringVar(master=master)
        self.filter_to_var = tk.StringVar(master=master)
        self.autoloot_var = tk.BooleanVar(master=master, value=False)
        self.level_from_var = tk_stringvar(master)
        self.level_to_var = tk_stringvar(master)
        # «Не грабить на своём сервере»: the robberies are the only thing it gates —
        # a tile at home is still listed, still shareable and still collectable by hand.
        self.skip_own_var = tk.BooleanVar(master=master, value=False)
        self.sweep_var = tk.BooleanVar(master=master, value=False)
        self.sweep_cx_var = tk.StringVar(master=master)
        self.sweep_cy_var = tk.StringVar(master=master)
        self._sweep_hint = None
        self._rule_lbl = None

        # -- «Переход по координатам» ----------------------------------------
        # The server box may be left empty on purpose: a blank one jumps on whatever
        # server the client is looking at, which is what the removed block did through
        # `_jump`'s own fallback. «↻ сервер» fills it in when the number is wanted.
        self.coord_x_var = tk.StringVar(master=master)
        self.coord_y_var = tk.StringVar(master=master)
        self.coord_srv_var = tk.StringVar(master=master)
        self._jump_hist: list = []
        self._jump_hist_var = tk_stringvar(master)
        self._jump_hist_combo = None

        self.capture = Capture(rt, self)
        self.autoloot = AutoLoot(rt, self)
        self.sweep = Sweep(rt, self)

    # -- getting onto the Tk thread ------------------------------------------
    def after(self, func) -> None:
        """Run ``func`` on the Tk thread; a window that has gone simply drops it."""
        try:
            self.rt.root.after(0, func)
        except (tk.TclError, RuntimeError):
            pass

    # -- lifecycle ------------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Start the standing orders this profile asked for — and nothing else.

        This runs at BOOT (the tab is EAGER: a capture has to be listening whether or
        not anybody opens the tab), so it must cost nothing beyond that. The list's own
        seed is a game read and lives in :meth:`on_show`, or every profile would pay a
        VM round trip at start-up for a list nobody has looked at.

        Idempotent — each order returns early when it is already running.
        """
        if self.monitor_var.get():
            self.capture.start()
        if self.autoloot_var.get():
            self.autoloot.start()
        if self.sweep_var.get():
            self.sweep.start()

    def on_show(self) -> None:
        """Somebody opened the tab: start the countdown and seed the list, once.

        The seed is a one-time VM snapshot — the game's parsed table, richest and
        available even before the capture has flushed a checkpoint. After it the wire
        feeds the list (the capture's nudge, «Обновить», the share trigger), which is
        why this is the only game read the tab makes on its own behalf.
        """
        if self.loaded:
            return
        self.loaded = True
        self._start_ticking()
        self._snapshot()

    def on_profile_switch(self) -> None:
        """Bounce all three orders onto the new account.

        Restarting is deliberate: the capture keeps writing to the OLD profile's
        checkpoint, and auto-loot reads that checkpoint and remembers uuids it robbed
        under the old account — a restart clears both.
        """
        self.capture.stop()
        self.autoloot.stop()
        self.sweep.stop()
        # Another account is another server and another alliance: both cached readings
        # would otherwise answer for the profile that has just been left — and the own
        # server is what the robbery prohibition is judged against.
        self._ids = None
        self._own_server = 0
        self._refresh_rule_hints()
        if self.monitor_var.get():
            self.capture.start()
        if self.autoloot_var.get():
            self.autoloot.start()
        if self.sweep_var.get():
            self.sweep.start()

    def on_language_change(self) -> None:
        self._retranslate_combo()
        self._retranslate_headings()
        self._refresh_rule_hints()
        # The rows themselves carry words too («⭐×7», «готово через …»), and a heading
        # is only half the table.
        self._render()

    def panic(self) -> None:
        """«Стоп всё»: every standing order down, and the boxes say so."""
        for var, order in ((self.monitor_var, self.capture),
                           (self.autoloot_var, self.autoloot),
                           (self.sweep_var, self.sweep)):
            var.set(False)
            order.stop()
        self._sync_autoloot_controls()

    def shutdown(self) -> None:
        self.capture.stop()
        self.autoloot.stop()
        self.sweep.stop()
        for name in ("secret_tick", "secret_poll", "secret_nudge",
                     "autoloot_push_restart"):
            self.rt.tick.disarm(name)
        self._ticking = self._polling = False

    # -- persistence ----------------------------------------------------------
    def config(self) -> dict:
        return {
            "monitor_kind": self.kind_index(),
            "monitor_interval": self.interval_var.get(),
            "secret_monitor": bool(self.monitor_var.get()),
            "filter_star": bool(self.star_var.get()),
            "filter_pending": bool(self.pending_var.get()),
            "filter_can_loot": bool(self.can_loot_var.get()),
            "filter_level_from": self.filter_from_var.get(),
            "filter_level_to": self.filter_to_var.get(),
            "autoloot": bool(self.autoloot_var.get()),
            "autoloot_level_from": self.level_from_var.get(),
            "autoloot_level_to": self.level_to_var.get(),
            "autoloot_skip_own_server": bool(self.skip_own_var.get()),
            "map_sweep": bool(self.sweep_var.get()),
            "sweep_centre_x": self.sweep_cx_var.get(),
            "sweep_centre_y": self.sweep_cy_var.get(),
            "coord_x": self.coord_x_var.get(),
            "coord_y": self.coord_y_var.get(),
            "coord_server": self.coord_srv_var.get(),
            "coord_history": list(self._jump_hist),
        }

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        idx = raw.get("monitor_kind", 0)
        if isinstance(idx, int) and 0 <= idx < len(capturemod.CAPTURE_OPTIONS) \
                and self._combo is not None:
            self._combo.current(idx)
        self.interval_var.set(str(raw.get("monitor_interval", "15")))
        self.monitor_var.set(bool(raw.get("secret_monitor", False)))
        self.star_var.set(bool(raw.get("filter_star", False)))
        self.pending_var.set(bool(raw.get("filter_pending", False)))
        self.can_loot_var.set(bool(raw.get("filter_can_loot", False)))
        self.filter_from_var.set(raw.get("filter_level_from", ""))
        self.filter_to_var.set(raw.get("filter_level_to", ""))
        # A profile saved before the display filter and the robbery rule were split has
        # only the one pair — and it was AIMING the robberies as well as narrowing the
        # log. Seeding the auto-loot range from it is what keeps that profile robbing the
        # same levels; without the fallback the rule silently widens to "any level",
        # which is how a robbery gets spent on a level-6 star (#1099).
        self.level_from_var.set(raw.get("autoloot_level_from",
                                        raw.get("filter_level_from", "")))
        self.level_to_var.set(raw.get("autoloot_level_to",
                                      raw.get("filter_level_to", "")))
        self.autoloot_var.set(bool(raw.get("autoloot", False)))
        # Off by default: robbing the whole map is what the tab has always done, and a
        # prohibition nobody asked for would be a silent behaviour change.
        self.skip_own_var.set(bool(raw.get("autoloot_skip_own_server", False)))
        self.sweep_var.set(bool(raw.get("map_sweep", False)))
        self.sweep_cx_var.set(raw.get("sweep_centre_x", ""))
        self.sweep_cy_var.set(raw.get("sweep_centre_y", ""))
        self.coord_x_var.set(str(raw.get("coord_x", "")))
        self.coord_y_var.set(str(raw.get("coord_y", "")))
        self.coord_srv_var.set(str(raw.get("coord_server", "")))
        self._set_jump_history(raw.get("coord_history"))
        self._refresh_rule_hints()
        self._sync_autoloot_controls()

    def persist_vars(self) -> list:
        return [self.monitor_var, self.interval_var, self.star_var, self.pending_var,
                self.can_loot_var, self.filter_from_var, self.filter_to_var,
                self.autoloot_var, self.level_from_var, self.level_to_var,
                self.skip_own_var, self.sweep_var, self.sweep_cx_var, self.sweep_cy_var,
                self.coord_x_var, self.coord_y_var, self.coord_srv_var]

    # -- UI -------------------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                "tab.secret_tasks").pack(side="left")
        self.tr(ttk.Button(bar, width=12, command=self.refresh),
                "tabx.refresh").pack(side="right")
        self.tr(ttk.Button(bar, width=12, command=self._clear),
                "secrettasks.clear").pack(side="right", padx=(0, 6))
        ttk.Label(bar, textvariable=self._status_var, foreground="#888").pack(
            side="right", padx=8)

        self._build_coord_bar()
        self._build_monitor_bar()
        self._build_filter_bar()

        self.tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                          justify="left"), "secrettasks.hint").pack(
            anchor="w", padx=10, pady=(0, 6))

        self._build_table()
        self._refresh_rule_hints()

    # -- «Переход по координатам» ---------------------------------------------
    def _build_coord_bar(self) -> None:
        """The jump block «Главная» lost in #1183, on the tab that lives on coordinates.

        Same three boxes, same «Перейти», same «↻ сервер» and the same per-profile «куда
        ходил» list — and the same `rt.game.jump` underneath, which is what the table's
        coordinate links and a scenario's `JUMP` also walk through.
        """
        box = self.tr(ttk.LabelFrame(self.parent, padding=6), "coord.frame")
        box.pack(fill="x", padx=10, pady=(0, 4))
        self.tr(ttk.Label(box), "coord.x").pack(side="left")
        NumericEntry(box, textvariable=self.coord_x_var, width=7,
                     signed=True).pack(side="left", padx=(2, 8))
        self.tr(ttk.Label(box), "coord.y").pack(side="left")
        NumericEntry(box, textvariable=self.coord_y_var, width=7,
                     signed=True).pack(side="left", padx=(2, 8))
        self.tr(ttk.Label(box), "coord.server").pack(side="left")
        NumericEntry(box, textvariable=self.coord_srv_var,
                     width=7).pack(side="left", padx=(2, 8))
        self.tr(ttk.Button(box, command=self._goto_coord),
                "coord.jump").pack(side="left", padx=4, ipady=2)
        self.tr(ttk.Button(box, command=self._load_current_server),
                "coord.reload_server").pack(side="left", padx=4)
        self._jump_hist_combo = ttk.Combobox(box, textvariable=self._jump_hist_var,
                                             state="readonly", width=18, values=[])
        self._jump_hist_combo.pack(side="right", padx=(4, 0))
        self._jump_hist_combo.bind("<<ComboboxSelected>>", self._on_jump_history)
        self.tr(ttk.Label(box), "coord.history").pack(side="right", padx=(8, 2))
        self._set_jump_history(self._jump_hist)

    def _build_monitor_bar(self) -> None:
        """The capture block: which capture, how often, what reaches the log — and the
        «Автообъезд карты» that keeps it fed."""
        sec = self.tr(ttk.LabelFrame(self.parent, padding=8), "secret.frame")
        sec.pack(fill="x", padx=10, pady=(0, 4))
        row1 = ttk.Frame(sec)
        row1.pack(fill="x")
        self._combo = ttk.Combobox(
            row1, state="readonly", width=20,
            values=[self.t(o["key"]) for o in capturemod.CAPTURE_OPTIONS])
        self._combo.current(0)
        self._combo.pack(side="left", padx=(0, 8))
        # Which capture is a saved choice like any other; a combo has no variable, so it
        # says so itself.
        self._combo.bind("<<ComboboxSelected>>",
                         lambda _e: self.rt.settings.changed(), add="+")
        self.rt.i18n.hook(self._retranslate_combo, key="secret-capture-combo")
        self.tr(ttk.Checkbutton(row1, variable=self.monitor_var,
                                command=self.capture.toggle),
                "secret.monitoring").pack(side="left")
        self.tr(ttk.Label(row1), "secret.interval").pack(side="left", padx=(12, 2))
        numeric_spinbox(row1, from_=1, to=3600, width=5,
                        textvariable=self.interval_var).pack(side="left")
        self.tr(ttk.Label(row1, foreground="#888"), "secret.hint").pack(
            side="left", padx=10)

        row2 = ttk.Frame(sec)
        row2.pack(fill="x", pady=(6, 0))
        self.tr(ttk.Label(row2), "secret.filters").pack(side="left")
        self.tr(ttk.Checkbutton(row2, variable=self.star_var),
                "secret.stars_only").pack(side="left", padx=(6, 0))
        self.tr(ttk.Checkbutton(row2, variable=self.pending_var),
                "secret.pending_only").pack(side="left", padx=(6, 0))
        self.tr(ttk.Checkbutton(row2, variable=self.can_loot_var),
                "secret.can_loot_only").pack(side="left", padx=(6, 0))
        self.tr(ttk.Label(row2), "secret.filter_level_from").pack(
            side="left", padx=(12, 2))
        NumericEntry(row2, textvariable=self.filter_from_var, width=4).pack(side="left")
        self.tr(ttk.Label(row2), "secret.level_to").pack(side="left", padx=(6, 2))
        NumericEntry(row2, textvariable=self.filter_to_var, width=4).pack(side="left")

        # «Автообъезд карты»: the passive scan only learns tiles while the map moves, so
        # this walks the camera over a box around a centre.
        sweep = self.tr(ttk.LabelFrame(sec, padding=6), "sweep.frame")
        sweep.pack(fill="x", pady=(8, 0))
        self.tr(ttk.Checkbutton(sweep, variable=self.sweep_var,
                                command=self.sweep.toggle),
                "sweep.enabled").pack(side="left")
        self.tr(ttk.Label(sweep), "sweep.centre").pack(side="left", padx=(12, 2))
        NumericEntry(sweep, textvariable=self.sweep_cx_var, width=6,
                     signed=True).pack(side="left", padx=(0, 2))
        NumericEntry(sweep, textvariable=self.sweep_cy_var, width=6,
                     signed=True).pack(side="left")
        self._sweep_hint = ttk.Label(sweep, foreground="#888", wraplength=380,
                                     justify="left")
        self._sweep_hint.pack(side="left", padx=(10, 0))

    def _build_filter_bar(self) -> None:
        """The level range, «Автолут ★» and the own-server prohibition — the rule the
        robberies obey.

        The same range doubles as the list's display filter (:meth:`_in_range`), so the
        operator sees exactly the tiles the standing order is about to weigh. «Не грабить
        на своём сервере» is in THIS frame rather than beside the display filters on
        purpose: it gates the robberies and nothing else, and a box that hid tiles would
        be a different feature wearing the same words.
        """
        frame = self.tr(ttk.LabelFrame(self.parent, padding=6), "secret.autoloot.frame")
        frame.pack(fill="x", padx=10, pady=(0, 4))
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        self.tr(ttk.Checkbutton(bar, variable=self.autoloot_var,
                                command=self._on_autoloot_toggle),
                "secret.autoloot").pack(side="left")
        self.tr(ttk.Label(bar), "secret.autoloot.level_from").pack(
            side="left", padx=(12, 2))
        NumericEntry(bar, textvariable=self.level_from_var, width=4).pack(side="left")
        self.tr(ttk.Label(bar), "secret.level_to").pack(side="left", padx=(6, 2))
        NumericEntry(bar, textvariable=self.level_to_var, width=4).pack(side="left")
        self._skip_own_box = self.tr(
            ttk.Checkbutton(bar, variable=self.skip_own_var,
                            command=self._on_skip_own_change),
            "secret.autoloot.skip_own")
        self._skip_own_box.pack(side="left", padx=(16, 0))
        self._sync_autoloot_controls()
        self._rule_lbl = ttk.Label(frame, foreground="#888", wraplength=760,
                                   justify="left")
        self._rule_lbl.pack(fill="x", anchor="w", pady=(4, 0))
        # Typing the range re-filters the shown list (cached — no game round trip), keeps
        # the rule line true, and bounces the event-driven listener onto the new bounds.
        for var in (self.level_from_var, self.level_to_var):
            var.trace_add("write", lambda *_a: self._on_level_filter_change())
        for var in (self.sweep_cx_var, self.sweep_cy_var):
            var.trace_add("write", lambda *_a: self._refresh_rule_hints())
        # The capture's interval is a child-process argument, so a change only takes
        # effect on the next launch: bounce a running one rather than waiting for a
        # manual toggle.
        self.interval_var.trace_add("write", lambda *_a: self._on_interval_change())

    # -- the table -------------------------------------------------------------
    def _build_table(self) -> None:
        """The found secret tasks as a real table: fixed header, sortable, one row deep.

        A `ttk.Treeview` rather than a stack of frames (#1209). The rows used to be packed
        by hand, each label carrying its own width, so nothing lined up under anything and
        a long countdown pushed its neighbours off the row. Here the widths belong to the
        columns, the header stays put while the list scrolls, and a heading sorts.

        What a Treeview cannot hold is a widget, so the two row actions live under it and
        act on the selection — plus the right-click menu, and the coordinate link.
        """
        # The action strip is packed FIRST, against the bottom: pack clips whatever was
        # packed last when the window is short, and the buttons are the one thing on the
        # tab that must never be the part that falls off the edge.
        acts = ttk.Frame(self.parent)
        acts.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        wrap = ttk.Frame(self.parent)
        wrap.pack(fill="both", expand=True, padx=10, pady=(0, 0))
        self._empty = self.tr(ttk.Label(wrap, foreground="#888"), "secrettasks.empty")
        self._body = ttk.Frame(wrap)
        self._body.pack(fill="both", expand=True)

        tree = ttk.Treeview(self._body, columns=[c[0] for c in COLUMNS],
                            show="headings", selectmode="browse")
        bar = ttk.Scrollbar(self._body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        for col, _key, width, anchor, stretch in COLUMNS:
            tree.column(col, width=width, anchor=anchor, stretch=stretch)
        # A ready tile is green and a counting-down one amber, exactly as the packed rows
        # were — the colour is the fastest read on the tab.
        tree.tag_configure("ready", foreground=READY_COLOR)
        tree.tag_configure("waiting", foreground=TIMER_COLOR)
        tree.bind("<Button-1>", self._on_click)
        tree.bind("<Double-Button-1>", self._on_double_click)
        tree.bind("<Button-3>", self._on_right_click)
        tree.bind("<Motion>", self._on_motion)
        tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_actions())
        self._tree = tree
        self._retranslate_headings()

        self._goto_btn = self.tr(ttk.Button(acts, width=12, command=self._goto_selected),
                                 "secrettasks.goto")
        self._goto_btn.pack(side="left")
        self.tr(ttk.Label(acts, foreground="#888"), "secrettasks.click_hint").pack(
            side="left", padx=10)
        self._share_btn = ttk.Button(acts, width=12)
        self._share_btn.configure(command=lambda: self._open_share_menu(
            self._share_btn, self._selected()))
        self.tr(self._share_btn, "secrettasks.share").pack(side="right", padx=(6, 0))
        self._collect_btn = self.tr(ttk.Button(acts, width=12,
                                               command=self._collect_selected),
                                    "secrettasks.collect")
        self._collect_btn.pack(side="right")
        self._sync_actions()

    def _retranslate_headings(self) -> None:
        """(Re)write the column headings and re-arm their sort commands.

        A heading with no entry in :data:`SORT_KEYS` — the action column — gets no
        command: clicking it must not look like it did something.
        """
        if self._tree is None:
            return
        for col, key, _w, _a, _s in COLUMNS:
            try:
                self._tree.heading(col, text=self.t(key),
                                   command=(lambda c=col: self._sort_by(c))
                                   if col in self.SORT_KEYS else "")
            except tk.TclError:
                return

    def _sort_by(self, column: str) -> None:
        """A heading was clicked: sort by it, and flip the direction on a second click."""
        if self._sort and self._sort[0] == column:
            self._sort = (column, not self._sort[1])
        else:
            self._sort = (column, False)
        self._render()

    #: How each column orders. `state` sorts by "how soon this row wants attention" —
    #: the ready ones first, then the shortest countdown — which is what the eye is
    #: after, rather than the alphabet of a translated sentence. The action column is
    #: not in here: a button is not an order, so its heading does not sort.
    SORT_KEYS = {
        "coords": lambda r: (int(r["x"] or 0), int(r["y"] or 0)),
        "server": lambda r: int(r["server"] or 0),
        "lvl": lambda r: int(r["level"] or 0),
        "state": lambda r: (0 if r.get("ready") else 1,
                            (r["expires_at"] if r.get("ready")
                             else r["completed_at"]) or 0),
        "slots": lambda r: int(r["loot_count"] or 0),
    }

    def _sorted_rows(self, rows) -> list:
        """The rows in the order the table shows them.

        Untouched headings keep the order auto-loot prizes them in — the highest star
        first, and within a level the tile that expires soonest — so the tab opens on the
        best raid without anybody having to ask for it.
        """
        if self._sort is None:
            return sorted(rows, key=lambda r: (-int(r["level"] or 0),
                                               r["expires_at"] or float("inf")))
        column, backwards = self._sort
        key = self.SORT_KEYS.get(column)
        if key is None:
            return list(rows)
        return sorted(rows, key=key, reverse=backwards)

    def _row_values(self, row) -> tuple:
        """One row as the cells of the table, in the order COLUMNS declares.

        The coordinate cell is the canonical `X:.. Y:..` token — the same one the log
        prints and `coords.parse` reads back — with the server standing in its own column
        beside it rather than glued to the front of it.
        """
        import coords as coords_fmt
        ready = bool(row.get("ready"))
        return (coords_fmt.fmt(row["x"], row["y"]),
                self.t("secrettasks.server", srv=row["server"]),
                "%s %s" % (READY_GLYPH if ready else TYPE_GLYPH,
                           self.t("secrettasks.stars", n=int(row["level"] or 0))),
                row["timer"].get(),
                self.t("secrettasks.slots", n=int(row["loot_count"] or 0)),
                self.t("secrettasks.collect") if ready else "")

    def _show_empty(self, empty: bool) -> None:
        """Say «нет звёздных секреток» above the table, or take the line away."""
        if self._empty is None:
            return
        try:
            if empty:
                self._empty.pack(before=self._body, anchor="w", pady=(0, 4))
            else:
                self._empty.pack_forget()
        except tk.TclError:
            pass

    # -- what a click on the table does ----------------------------------------
    def _column_at(self, event) -> str:
        """Which column the pointer is over, "" when it is not over a cell."""
        tree = self._tree
        if tree is None or tree.identify("region", event.x, event.y) != "cell":
            return ""
        col = tree.identify_column(event.x)          # "#1" … "#5"
        try:
            return COLUMNS[int(col[1:]) - 1][0]
        except (ValueError, IndexError):
            return ""

    def _row_at(self, event):
        return self._rows.get(self._tree.identify_row(event.y)) if self._tree else None

    def _on_click(self, event) -> None:
        """Two cells do something when clicked; every other one only selects.

        A coordinate is a place you can go, so clicking it walks the camera there. The
        action cell is the row's own «Собрать» — a Treeview cannot hold a button, so the
        cell IS the button, and it is only there on a row the server would let us rob.

        Not bound with a `break`: the click still selects the row, so the strip below
        stays aimed at the tile that was just acted on.
        """
        where = self._column_at(event)
        row = self._row_at(event)
        if row is None:
            return
        if where == LINK_COLUMN:
            self._jump_to_row(row)
        elif where == ACTION_COLUMN and row.get("ready"):
            self._collect(row)

    def _live_cell(self, event) -> bool:
        """Whether the cell under the pointer is one a click would act on."""
        where = self._column_at(event)
        if where == LINK_COLUMN:
            return True
        row = self._row_at(event)
        return where == ACTION_COLUMN and bool(row and row.get("ready"))

    def _on_motion(self, event) -> None:
        """The link cursor over a cell that acts, the ordinary one everywhere else."""
        try:
            self._tree.configure(cursor="hand2" if self._live_cell(event) else "")
        except tk.TclError:
            pass

    def _on_double_click(self, event) -> None:
        """Double-click a ready row to rob it — the one-press collect the rows had."""
        row = self._row_at(event)
        if row is not None and row.get("ready"):
            self._collect(row)

    def _on_right_click(self, event) -> None:
        """The row's own menu, under the pointer: jump, collect, share."""
        tree = self._tree
        iid = tree.identify_row(event.y) if tree is not None else ""
        row = self._rows.get(iid)
        if row is None:
            return
        tree.selection_set(iid)
        menu = tk.Menu(self.rt.root, tearoff=0)
        menu.add_command(label=self.t("secrettasks.goto"),
                         command=lambda: self._jump_to_row(row))
        if row.get("ready"):
            menu.add_command(label=self.t("secrettasks.collect"),
                             command=lambda: self._collect(row))
        menu.add_separator()
        menu.add_command(label=self.t("secrettasks.share_alliance"),
                         command=lambda: self._share(row, SHARE_ALLIANCE))
        menu.add_command(label=self.t("secrettasks.share_world"),
                         command=lambda: self._share(row, SHARE_WORLD))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _selected(self):
        """The row the table's selection is on, or None."""
        tree = self._tree
        if tree is None:
            return None
        picked = tree.selection()
        return self._rows.get(picked[0]) if picked else None

    def _sync_actions(self) -> None:
        """Enable each button of the strip only where it means something.

        «Собрать» on a tile still counting down is a robbery the server would refuse, so
        the button says so by being unavailable rather than by failing afterwards.
        """
        row = self._selected()
        for widget, live in ((self._goto_btn, row is not None),
                             (self._share_btn, row is not None),
                             (self._collect_btn, bool(row and row.get("ready")))):
            if widget is None:
                continue
            try:
                widget.state(("!disabled",) if live else ("disabled",))
            except tk.TclError:
                pass

    def _collect_selected(self) -> None:
        row = self._selected()
        if row is not None and row.get("ready"):
            self._collect(row)

    def _goto_selected(self) -> None:
        row = self._selected()
        if row is not None:
            self._jump_to_row(row)

    def _jump_to_row(self, row) -> None:
        """Walk the camera to one row's tile, and say where it went."""
        import coords as coords_fmt
        x, y, srv = int(row["x"] or 0), int(row["y"] or 0), row["server"] or None
        self.say("secret", "log.coord.clicked", where=coords_fmt.fmt(x, y, srv))
        self._jump(x, y, srv)

    def _retranslate_combo(self) -> None:
        if self._combo is None:
            return
        idx = self._combo.current()
        self._combo.configure(values=[self.t(o["key"])
                                      for o in capturemod.CAPTURE_OPTIONS])
        self._combo.current(idx if idx >= 0 else 0)

    def kind_index(self) -> int:
        """Which capture is selected — 0 when the combo does not exist yet."""
        if self._combo is None:
            return 0
        idx = self._combo.current()
        return idx if idx >= 0 else 0

    def _on_interval_change(self) -> None:
        if not self.rt.settings.loading and self.capture.running:
            self.capture.restart()

    def _on_autoloot_toggle(self) -> None:
        """«Автолут ★» was ticked or cleared: start/stop it, and grey what it owns."""
        self.autoloot.toggle()
        self._sync_autoloot_controls()

    def _sync_autoloot_controls(self) -> None:
        """«Не грабить на своём сервере» is lit only while there are robberies to gate.

        With auto-loot off nothing robs by itself, so the prohibition has nothing to
        forbid — a live-looking box that changes nothing is how a person concludes the
        panel ignored them. The VALUE is kept: ticking auto-loot back on brings the
        prohibition back exactly as it was left.
        """
        box = getattr(self, "_skip_own_box", None)
        if box is None:
            return
        try:
            box.state(("!disabled",) if self.autoloot_var.get() else ("disabled",))
        except tk.TclError:
            pass

    def _on_skip_own_change(self) -> None:
        """«Не грабить на своём сервере» was ticked or cleared.

        The poll re-reads the box every tick, but the push listener is a subprocess
        started with a fixed rule — without the bounce a box ticked while auto-loot is
        running would go on robbing the neighbours it was ticked to protect.
        """
        self._refresh_rule_hints()
        self.autoloot.range_changed()

    # -- jumping ---------------------------------------------------------------
    def _jump(self, x: int, y: int, server) -> None:
        """The one way this tab walks the camera anywhere. Remembers where it went.

        ``server`` may be None — the runtime then jumps on whatever server the client is
        currently looking at, which is what an empty «Сервер» box means.
        """
        if self.rt.game.jump(x, y, server):
            self._remember_jump(x, y, server)

    def _goto_coord(self) -> None:
        """«Перейти»: the three boxes, validated, then the same jump as everything else."""
        x, y = self.coord_x_var.get().strip(), self.coord_y_var.get().strip()
        if not (x.lstrip("-").isdigit() and y.lstrip("-").isdigit()):
            self.say("coord", "log.coord.bad_xy")
            return
        srv = self.coord_srv_var.get().strip()
        self._jump(int(x), int(y), int(srv) if srv.isdigit() else None)

    def _load_current_server(self) -> None:
        """«↻ сервер»: fill the box with the server the client is looking at.

        Off the Tk thread — it is a game round trip — and only ever pressed, never run at
        boot: the block it belonged to cost the panel a read at every start-up (#1183).
        """
        def work() -> None:
            srv = self.rt.game.current_server()
            self.after(lambda: (self.coord_srv_var.set(str(srv)),
                                self.say("coord", "log.server.current", srv=srv)))

        threading.Thread(target=work, daemon=True).start()

    def _remember_jump(self, x: int, y: int, server) -> None:
        """Put a walked-to tile at the top of «куда ходил» (most recent first, capped).

        Hopping between a handful of known tiles — the base, an alliance city, the star
        somebody keeps robbing — is the routine use, and re-typing the triple was the
        whole cost of it.
        """
        import coords as coords_fmt
        token = coords_fmt.fmt(x, y, server)
        history = [t for t in self._jump_hist if t != token]
        history.insert(0, token)
        self._set_jump_history(history[:JUMP_HISTORY_MAX])
        self.rt.settings.changed()

    def _set_jump_history(self, tokens) -> None:
        """Replace the history and repaint the combobox (tolerant of junk in a profile)."""
        self._jump_hist = [str(t) for t in (tokens or []) if str(t).strip()]
        if self._jump_hist_combo is None:
            return
        try:
            self._jump_hist_combo.configure(values=self._jump_hist)
            self._jump_hist_var.set("")
        except tk.TclError:
            pass

    def _on_jump_history(self, _event=None) -> None:
        """A remembered tile was picked: fill the three boxes and go there."""
        import coords as coords_fmt
        hits = coords_fmt.parse(self._jump_hist_var.get())
        self._jump_hist_var.set("")
        if not hits:
            return
        _s, _e, x, y, srv = hits[0]
        self.coord_x_var.set(str(x))
        self.coord_y_var.set(str(y))
        self.coord_srv_var.set(str(srv) if srv else "")
        self._jump(x, y, srv)

    # -- who I am --------------------------------------------------------------
    def own_server(self) -> int:
        """The PLAYER's own server id, cached for the session (0 when unreadable).

        Not the server on screen: an auto-loot run walks the camera into other servers all
        day, so `curServerId` would answer "wherever I am looking". This is the account's
        own one — what «не грабить на своём сервере» compares a tile against — and it
        comes from the same `ChatInterface` read the chat rooms are built from.

        Called from the auto-loot thread, so it must never raise: an unreadable answer is
        0, and the standing order treats that as "do not rob" rather than "rob anything".
        """
        if self._own_server:
            return self._own_server
        try:
            srv, _aid = self._self_ids(self.rt.game.client)
            self._own_server = int(srv or 0)
        except Exception:                     # noqa: BLE001 — no daemon, no game, no id
            self._own_server = 0
        return self._own_server

    def _refresh_rule_hints(self) -> None:
        """Re-render the two "this is what the checkbox will do" lines.

        Both standing orders are invisible otherwise, and an invisible rule is how a
        robbery got spent on a level-6 star.
        """
        for widget, text in ((self._rule_lbl, self.autoloot.rule_text),
                             (self._sweep_hint, self.sweep.rule_text)):
            if widget is None:
                continue
            try:
                widget.configure(text=text())
            except tk.TclError:
                pass

    def _on_level_filter_change(self) -> None:
        """A «уровень от / до» box was typed: re-draw the list against the new range,
        keep the rule line true, and re-aim the listener."""
        self._refresh_rule_hints()
        self.autoloot.range_changed()
        if self._tree is None:
            return
        self._render()
        self._update_status()

    # -- reading the wire / the game ------------------------------------------
    def _snapshot(self) -> None:
        """The one-time first-open seed: read the VM once and merge it."""
        if self._busy:
            return
        self._busy = True
        self._status_var.set(self.t("tabx.loading"))
        threading.Thread(target=self._snapshot_work, daemon=True).start()

    def _snapshot_work(self) -> None:
        try:
            tasks = self._fetch_vm()
        except Exception:                     # noqa: BLE001 — a failed read is an empty tab
            tasks = []
        self.after(lambda: self._merge(tasks))

    def refresh_live(self) -> None:
        """A share landed: re-merge the checkpoint — but only if the tab has been
        opened. An unopened one reads fresh when it is first shown."""
        if self.loaded:
            self.refresh()

    def refresh(self) -> None:
        """Merge the live capture checkpoint (the wire feed) into the list.

        The button, the capture's per-finding nudge and the «secret_task_share» trigger
        all land here. Cheap — a file read, no game round trip — and it only ADDS, so a
        burst of nudges coalesces to nothing worse than a re-merge of the same tiles.
        """
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            tasks = self._fetch_scan()
        except Exception:                     # noqa: BLE001 — a failed read is an empty tab
            tasks = []
        self.after(lambda: self._merge(tasks))

    def _fetch_scan(self) -> list:
        """The live, starred secret tasks off the capture checkpoint — the wire feed.

        `load_fresh_tasks` keeps only tiles the capture re-saw this scan window and
        recomputes `can_loot` / `pending` against the clock, so a file written a while ago
        cannot smuggle a stale tile in. A missing checkpoint (the capture never ran) or a
        malformed one raises and is caught upstream as "no new tiles".
        """
        import lastwar_proto as proto
        tasks = proto.load_fresh_tasks(self.rt.profiles.tasks_json())
        return [t for t in tasks if t.starred]

    def _fetch_vm(self) -> list:
        """The first-open snapshot: every live starred alliance task straight from the VM.

        Every tile on the map with a free slot — the ones already raidable AND the ones
        still counting down — so a row can carry its «готово через …» timer and flip to
        raidable in place.
        """
        import steal_secret_task
        tasks = steal_secret_task._vm_all_alliance_tasks(self.rt.game.evaluator())
        return [t for t in tasks if t.starred]

    def _merge(self, tasks) -> None:
        """Add tiles the list does not have yet; keep the ones it does.

        A rescan only ADDS — an existing row keeps its place and its timer, a tile robbed
        by hand this session is skipped, and nothing already on screen is torn out from
        under the operator. Expiry and the ready-transition are the tick's job.
        """
        self._busy = False
        for t in tasks:
            key = str(t.uuid)
            if key in self._rows or key in self._collected:
                continue
            self._rows[key] = {
                "uuid": t.uuid, "server": t.server_id, "x": t.x, "y": t.y,
                "level": t.level, "cfg_id": t.cfg_id, "loot_count": t.loot_count,
                "expires_at": t.expires_at, "completed_at": t.completed_at,
                # The countdown is still written into a variable of its own rather than
                # straight into the cell: it is what `_refresh_timers` decides, and the
                # table then paints it. A tile off screen (out of the level range) keeps
                # counting all the same.
                "timer": tk_stringvar(self.rt.root), "ready": False,
            }
        self._render()
        # An empty list after a clean read is "no starred tile right now", not "no game" —
        # the scroll's own hint says so, so the status stays blank rather than crying
        # about a game that may be perfectly up.
        self._update_status()
        self._maybe_start_poll()

    # -- drawing ---------------------------------------------------------------
    def _render(self) -> None:
        """Rebuild the table from the current rows, in the order the headings ask for.

        Called on a merge / collect / clear / sort, NOT every second — the countdown is
        written cell by cell by :meth:`_paint_timers`, which costs nothing next to
        emptying and refilling the table.
        """
        tree = self._tree
        if tree is None:
            return
        # A tile merged a moment ago has no countdown written yet, and a cell is drawn
        # once — unlike the old labels, which followed their variable. So the clocks are
        # brought up to date first and the row is drawn with the state it really is in.
        self._refresh_timers()
        # The selection is what the strip's buttons are aimed at; a repaint every time a
        # tile matures must not take it away from under the operator's hand.
        chosen = set(tree.selection())
        for iid in tree.get_children(""):
            tree.delete(iid)
        rows = self._sorted_rows(self._visible_rows())
        for row in rows:
            tree.insert("", "end", iid=str(row["uuid"]), values=self._row_values(row),
                        tags=("ready",) if row.get("ready") else ("waiting",))
        back = [iid for iid in chosen if tree.exists(iid)]
        if back:
            tree.selection_set(back)
        self._show_empty(not rows)
        self._sync_actions()

    def _paint_timers(self) -> None:
        """Write each row's countdown into its cell — the per-second half of the drawing.

        Only the state cell changes as a second passes; the ready-transition is what asks
        for a full :meth:`_render`, because it re-colours the row and re-sorts it.
        """
        tree = self._tree
        if tree is None:
            return
        for key, row in self._rows.items():
            try:
                if tree.exists(key):
                    tree.set(key, "state", row["timer"].get())
            except tk.TclError:
                return

    def _in_range(self, level) -> bool:
        """Whether `level` falls inside the «уровень от / до» range (either end open).

        The bounds are the very range the auto-loot watcher robs at, so the list shows
        exactly the tiles the standing order weighs.
        """
        lo, hi = self.autoloot.levels()
        lvl = int(level or 0)
        if lo is not None and lvl < lo:
            return False
        if hi is not None and lvl > hi:
            return False
        return True

    def _visible_rows(self) -> list:
        return [r for r in self._rows.values() if self._in_range(r["level"])]

    def _update_status(self) -> None:
        n = len(self._visible_rows())
        self._status_var.set(self.t("secrettasks.count", n=n) if n else "")

    # The uuid tail used to have a column of its own. It is gone with the table (#1209):
    # a tile is named by its coordinate and its server everywhere else in the panel — the
    # log line, the chat share, the jump — and an 18-digit id nobody can read out loud
    # was taking the width the countdown needed. The uuid still travels with the row and
    # is what the robbery is sent with; it is simply not what a person is shown.

    # -- the countdown ---------------------------------------------------------
    def _start_ticking(self) -> None:
        if not self._ticking:
            self._ticking = True
            self._tick()

    def _tick(self) -> None:
        """Every second: rewrite each row's timer, drop the expired, flip the matured.

        A tile past `expires_at` is off the map and can no longer be robbed, so it comes
        off the list on its own. A tile whose `completed_at` passes turns raidable: the
        tick repaints it green and wakes the poll. Only a state change repaints.
        """
        try:
            expired, changed = self._refresh_timers()
            for key in expired:
                self._rows.pop(key, None)
            if expired or changed:
                self._render()
                self._update_status()
            else:
                self._paint_timers()
            self._maybe_start_poll()
        finally:
            # Named, so the countdown is one chain however often `_start_ticking` is
            # reached.
            self.rt.tick.arm("secret_tick", 1000, self._tick)

    def _refresh_timers(self) -> tuple:
        """Rewrite every row's timer; return (expired keys, did any ready-state change).

        The countdown runs to `completed_at` — the moment the tile becomes raidable — not
        to expiry: «готово через …» while it is ahead, then «готово к сбору» (with how
        long is left to loot) once it is past. `expires_at` still governs removal.
        """
        import time
        now = int(time.time() * 1000)
        expired, changed = [], False
        for key, row in self._rows.items():
            exp = row["expires_at"]
            if exp is not None and exp <= now:
                expired.append(key)
                continue
            done = row["completed_at"]
            ready = done is not None and done <= now
            if ready != row.get("ready"):
                row["ready"] = ready
                changed = True
            if done is None:
                row["timer"].set(self.t("secrettasks.until_ready", t="—"))
            elif not ready:
                row["timer"].set(self.t("secrettasks.until_ready",
                                        t=_fmt_left(done - now)))
            elif exp is not None:
                row["timer"].set(self.t("secrettasks.ready_expires",
                                        t=_fmt_left(exp - now)))
            else:
                row["timer"].set(self.t("secrettasks.ready"))
        return expired, changed

    # -- the ready-row poll ----------------------------------------------------
    def _maybe_start_poll(self) -> None:
        """Start the slow poll if a row is ready and it is not already running."""
        if self._polling:
            return
        if any(r.get("ready") for r in self._rows.values()):
            self._polling = True
            self.rt.tick.arm("secret_poll", POLL_MS, self._poll_tick)

    def _poll_tick(self) -> None:
        """Re-read the game for the ready rows; reschedule while any remain.

        Off the Tk thread (a daemon round trip), so this only gathers the keys and hands
        the read to a worker. Stops rescheduling the moment no row is ready — an idle tab
        must not keep waking the daemon.
        """
        ready = [k for k, r in self._rows.items() if r.get("ready")]
        if not ready:
            self._polling = False
            return
        threading.Thread(target=self._poll_work, args=(ready,), daemon=True).start()
        self.rt.tick.arm("secret_poll", POLL_MS, self._poll_tick)

    def _poll_work(self, keys: list) -> None:
        try:
            import steal_secret_task
            live = {str(t.uuid): t for t in steal_secret_task._vm_all_alliance_tasks(
                self.rt.game.evaluator())}
        except Exception:                     # noqa: BLE001 — a failed read proves nothing
            live = None
        self.after(lambda: self._poll_apply(keys, live))

    def _poll_apply(self, keys: list, live) -> None:
        """Reconcile the polled ready rows: drop the gone, refresh the rest, then loot.

        A failed read (``live is None``) is not evidence a tile vanished, so it is left
        alone until the next poll. A tile missing from a GOOD read is off the map
        (expired) or looted out (its slots filled), and either way it can no longer be
        robbed — so its row drops. Auto-loot runs last, over the whole refreshed list, so
        it robs by the standing order's rule rather than per-tile.
        """
        if live is None:
            return
        removed = False
        for key in keys:
            row = self._rows.get(key)
            if row is None:
                continue
            task = live.get(key)
            if task is None:
                self._rows.pop(key, None)
                removed = True
                continue
            row["expires_at"] = task.expires_at
            row["completed_at"] = task.completed_at
            row["loot_count"] = task.loot_count
        if self.autoloot_var.get():
            self._auto_loot(live)
        if removed:
            self._render()
            self._update_status()

    def _auto_loot(self, live) -> None:
        """Rob the raidable, in-range rows — but only at the range's TOP level, once each.

        The same rule the watcher obeys, and for the same reason: «от 1 до 7» robs 7-star
        tiles and leaves a 6 alone, because the five daily robberies are the scarce thing
        and one spent on a 6 is one a 7 cannot have until the reset (#1099). The display
        range IS the rob rule — a hidden tile is never robbed — and each tile is attempted
        once a session so a poll on a spent budget does not re-fire.
        """
        candidates = [
            (key, row) for key, row in self._rows.items()
            if row.get("ready") and self._in_range(row["level"])
            and key not in self._auto_attempted and key not in self._collected
            and key in live and live[key].can_loot
        ]
        if not candidates:
            return
        _lo, hi = self.autoloot.levels()
        top = hi if hi is not None else max(int(r["level"] or 0) for _, r in candidates)
        for key, row in candidates:
            if int(row["level"] or 0) != top:
                continue
            self._auto_attempted.add(key)
            self._collect(row)

    # -- actions ---------------------------------------------------------------
    def _collect(self, row) -> None:
        """Rob one tile: `hero.dispatch.steal {uuid, targetServer}`, off the Tk thread.

        The steal is budget-gated in the VM (a spent account sends nothing), so a
        confirmed send is the honest success signal here — whether the server pays out is
        its call, the same as every other route into the robbery.
        """
        key = str(row["uuid"])

        def work():
            ok = False
            try:
                import lua_actions
                lines = self.rt.game.evaluator().run(
                    lua_actions.secret_task_steal(int(row["uuid"]), int(row["server"])),
                    marker="ACT", settle=1.4)
                ok = any("steal_sent" in ln for ln in (lines or []))
            except Exception:                 # noqa: BLE001
                ok = False
            self.after(lambda: self._collect_done(key, ok))

        threading.Thread(target=work, daemon=True).start()

    def _collect_done(self, key: str, ok: bool) -> None:
        if ok:
            self._collected.add(key)
            self._rows.pop(key, None)
            self._render()
            self.rt.put("[secret] " + self.t("secrettasks.collect_ok"))
            self._update_status()
        else:
            self.rt.put("[secret] " + self.t("secrettasks.collect_fail"))

    def _open_share_menu(self, button, row) -> None:
        """Pop the «alliance / world» choice under the «Поделиться» button."""
        if row is None:                       # the button is disabled, but never trust it
            return
        menu = tk.Menu(self.rt.root, tearoff=0)
        menu.add_command(label=self.t("secrettasks.share_alliance"),
                         command=lambda: self._share(row, SHARE_ALLIANCE))
        menu.add_command(label=self.t("secrettasks.share_world"),
                         command=lambda: self._share(row, SHARE_WORLD))
        try:
            x = button.winfo_rootx()
            y = button.winfo_rooty() + button.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _share(self, row, scope: str) -> None:
        """Forward one tile into the alliance or world chat, off the Tk thread.

        Outgoing chat cannot be unsent, but the target is a raidable star the operator
        chose from a menu — the same deliberate act as the in-game share button.
        """
        def work():
            ok = False
            try:
                import chat_share
                ev = self.rt.game.evaluator()
                room = self._room_id(ev, scope)
                att = chat_share.task_attachment({
                    "x": row["x"], "y": row["y"], "srv": row["server"],
                    "uuid": row["uuid"], "cfgId": row["cfg_id"],
                    "name": "", "abbr": ""})
                ok = bool(room) and chat_share.share_point(ev, room, att)
            except Exception:                 # noqa: BLE001
                ok = False
            self.after(lambda: self._share_done(scope, ok))

        threading.Thread(target=work, daemon=True).start()

    def _share_done(self, scope: str, ok: bool) -> None:
        where = self.t("secrettasks.share_alliance" if scope == SHARE_ALLIANCE
                       else "secrettasks.share_world")
        key = "secrettasks.shared_ok" if ok else "secrettasks.share_fail"
        self.rt.put("[secret] " + self.t(key, where=where))

    def _room_id(self, ev, scope: str) -> str:
        srv, aid = self._self_ids(ev)
        if scope == SHARE_WORLD:
            return "country_%s" % srv if srv else ""
        if scope == SHARE_ALLIANCE:
            return "alliance_%s_%s" % (srv, aid) if srv and aid else ""
        return ""

    def _self_ids(self, ev) -> tuple:
        """`(serverId, allianceId)` for the logged-in player — read once, then cached.

        The chat room ids are `country_<server>` and `alliance_<server>_<allianceId>`;
        both come straight off `ChatInterface`. Cached for the session because they do not
        change while the panel is open.
        """
        if self._ids is not None:
            return self._ids
        chunk = (
            "pcall(function() "
            "local uid = ChatInterface.getPlayerUid() "
            "local srv = ChatInterface.getSelfServerId() "
            "local ud = ChatInterface.getUserData(uid) "
            "local aid = ud and ud.allianceId or '' "
            "CS.UnityEngine.Debug.LogError('ACT selfids srv='..tostring(srv)"
            "..' aid='..tostring(aid)) end)"
        )
        srv = aid = ""
        for ln in ev.run(chunk, marker="ACT", settle=1.0) or ():
            if "selfids " not in ln:
                continue
            for tok in ln.split("selfids ", 1)[1].split(" "):
                k, sep, v = tok.partition("=")
                if sep and k == "srv":
                    srv = v.strip()
                elif sep and k == "aid":
                    aid = v.strip()
        if srv or aid:
            self._ids = (srv, aid)            # cache only a real read, retry a blank one
        return (srv, aid)

    def _clear(self) -> None:
        """«Очистить список»: drop the expired and hand-collected rows.

        Expired tiles fall off on their own each second; this is the manual «tidy now»
        that also forgets the session's collected set, so a task robbed earlier can be
        re-listed by the next scan if the server still shows it raidable.
        """
        import time
        now = int(time.time() * 1000)
        for key in list(self._rows):
            exp = self._rows[key]["expires_at"]
            if exp is not None and exp <= now:
                self._rows.pop(key, None)
        self._collected.clear()
        self._render()
        self._update_status()


def _fmt_left(ms: int) -> str:
    """Milliseconds remaining as ``H:MM:SS`` (or ``MM:SS`` under an hour).

    Locale-neutral on purpose: the surrounding «expires in …» carries the language, the
    clock itself does not need translating.
    """
    total = max(0, ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)
