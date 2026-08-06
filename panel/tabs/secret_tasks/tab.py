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

THE LIST SURVIVES THE PANEL CLOSING (#1242). It used to be in-memory only — closing the
panel forgot it, and the first open of a new session started from a blank table until the
VM snapshot or the wire caught back up. Now every structural change to :attr:`_rows` (a
merge, a collect, a row expiring, the ready-row poll updating one) is checkpointed whole
to the profile's own `secret_tasks_state.json` (:meth:`_persist_rows`), and the tab's
`on_show` reads it back FIRST (:meth:`_load_persisted`) — before the VM snapshot even
starts — so the table is not empty the moment the tab opens. What is restored is not
trusted blind, though: the very next VM snapshot doubles as the actuality check, the
same reconciliation the ready-row poll already does on a live tile — a restored row the
game no longer confirms (expired, looted out, or simply gone while the panel was shut)
is dropped rather than left to mislead, and one it does confirm has its countdown and
loot count brought up to date. A restored row already past its own `expires_at` is
dropped on load, before it is ever drawn.

THE THREE STANDING ORDERS ARE THIS TAB'S OWN NOW. The capture, «Автолут ★» and
«Автообъезд карты» used to be checkboxes here whose every variable and every handler
lived on `Panel`; each is a small class beside this one, holding its own child processes
and its own loop (docs/research/panel-tabs-refactor.md §9.1/§9.3). The «уровень от / до»
range doubles as the list's display filter — a starred tile shows only while its level is
inside it, so the operator sees exactly the tiles auto-loot is about to weigh.

THERE ARE TWO TABLES (#1244). The one described above is a WORKING list — the starred
raids, gathered from two sources, kept across a restart, spent by «Собрать». Under it is
a second, identical table holding the alliance's whole list — every live secret task the
game itself lists, stars and plain tiles alike — because «what has my alliance got out
right now?» is a different question from «what is worth one of my five robberies?».
It costs nothing extra to answer: the very same VM read fills both (`_snapshot_work`),
the stars going up into the working list and the whole reply down into the mirror
(:mod:`~panel.tabs.secret_tasks.alliance`). It keeps no checkpoint of its own — the game
is its checkpoint — and it is replaced whole by every read rather than merged into.

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

import json
import threading
import tkinter as tk
from tkinter import ttk

from ...runtime import captures as capturemod
from ...widgets import (NumericEntry, numeric_spinbox, tk_stringvar,
                        font as ui_font)
from ..base import PanelTab, TriggerSpec
from . import grid
from .alliance import AllianceGrid
from .autoloot import AutoLoot
from .capture import Capture
from .sweep import Sweep

# The table itself — its columns, its colours, its sort keys and its countdown — is
# `grid.py` now (#1244), because the tab draws it TWICE: once for the starred raid
# targets and once for the alliance's own list below them. Re-exported here under the
# names the tab has always used, so nothing that reads this module has to know.
STAR_GLYPH, TYPE_GLYPH, READY_GLYPH = grid.STAR_GLYPH, grid.TYPE_GLYPH, grid.READY_GLYPH
TIMER_COLOR, READY_COLOR = grid.TIMER_COLOR, grid.READY_COLOR
SOON_COLOR, SOON_MS = grid.SOON_COLOR, grid.SOON_MS
COLUMNS = grid.COLUMNS
LINK_COLUMN, ACTION_COLUMN = grid.LINK_COLUMN, grid.ACTION_COLUMN

# How many jumps the «куда ходил» list remembers. One account's tiles are not another's,
# so it belongs to the profile like every other setting here.
JUMP_HISTORY_MAX = 20

# How often the ready-row poll re-reads the game once a tile is raidable. Slow on
# purpose — a raidable tile lives for minutes, and this is the list's own safety net,
# not the auto-loot watcher.
POLL_MS = 30_000

# How often the game's own clock is re-measured (#1227). It is not this machine's
# clock, which was measured eleven seconds slow against it — and the operator had been
# reading 25-30 s of that — so every countdown here is drawn
# against `game_clock`, and this is what keeps it true. Five minutes is far more often
# than a drift of seconds a day needs; the read is one line through the warm daemon.
CLOCK_MS = 5 * 60_000

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
        # The VM read has a flag of its own (#1244): «Обновить» now runs both sources —
        # the checkpoint (cheap, `_busy`) and the game's own table (`_vm_busy`) — and one
        # flag for the two would let the first to start silence the other.
        self._vm_busy = False
        self._ticking = False
        # uuid (str) -> row record. The record carries the task data, its countdown
        # StringVar and the row's frame, so a tick can update the timer in place and a
        # collect/clear can drop the row without a full re-read.
        self._rows: dict = {}
        # Keys `_load_persisted` restored from disk that the next VM snapshot has not
        # yet confirmed live (#1242) — `_merge` reconciles exactly these against it
        # (drop what is no longer there, refresh what still is) rather than treating
        # them as new finds. Cleared the moment that snapshot lands, read or not.
        self._restore_pending: set = set()
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
        self.filter_from_var = tk.StringVar(master=master)
        self.filter_to_var = tk.StringVar(master=master)
        self.autoloot_var = tk.BooleanVar(master=master, value=False)
        self.level_from_var = tk_stringvar(master)
        self.level_to_var = tk_stringvar(master)
        # «Не грабить на своём сервере»: the robberies are the only thing it gates —
        # a tile at home is still listed, still shareable and still collectable by hand.
        self.skip_own_var = tk.BooleanVar(master=master, value=False)
        # «Показывать исчерпанные»: off by default, because a 3/3 tile cannot pay
        # anybody and a list is read with the eyes (#1227). It is a box rather than a
        # silent rule so that a tile vanishing has somewhere to be looked for — the
        # question «did it fill up, or did the bot lose it?» is otherwise unanswerable.
        self.show_spent_var = tk.BooleanVar(master=master, value=False)
        self.sweep_var = tk.BooleanVar(master=master, value=False)
        self.sweep_cx_var = tk.StringVar(master=master)
        self.sweep_cy_var = tk.StringVar(master=master)
        self._sweep_hint = None
        self._rule_lbl = None
        # The words currently on the auto-loot label, so the countdown can leave it
        # alone while they have not changed.
        self._rule_line = None

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
        # The second table (#1244): the alliance's own list, filled by the very same VM
        # read that seeds the one above it — see `_snapshot_work`.
        self.alliance = AllianceGrid(self)

    # -- getting onto the Tk thread ------------------------------------------
    def after(self, func) -> None:
        """Run ``func`` on the Tk thread; a window that has gone simply drops it.

        Through the runtime's hand-over queue rather than `root.after`: the callers are
        the capture's reader, the auto-loot watcher and the sweep, all of them workers,
        and `after` from a worker waits on the event loop that draws every other open
        profile (#1226).
        """
        self.post(func)

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
        """Somebody opened the tab: restore the last session's list, start the
        countdown, and check what was restored against the live game, once.

        `_load_persisted` costs nothing but a file read, so it runs first — the table
        is not empty while the VM snapshot is still in flight (#1242). That snapshot is
        still a one-time read, the game's parsed table, richest and available even
        before the capture has flushed a checkpoint; it now ALSO doubles as the
        actuality check for whatever was just restored (`_merge`). After it the wire
        feeds the list (the capture's nudge, «Обновить», the share trigger), which is
        why this is the only game read the tab makes on its own behalf.
        """
        if self.loaded:
            return
        self.loaded = True
        self._restore_pending = self._load_persisted()
        if self._restore_pending:
            self._render()
            self._update_status()
        self._start_clock_sync()
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
        # THE LIST ITSELF BELONGS TO THE OLD ACCOUNT TOO (#1242): every row's coordinate
        # and server is that profile's map, and left in place it would be checkpointed
        # right back out under the NEW profile's own file the next time anything here
        # writes. Dropped and restored from the new profile's own checkpoint instead —
        # exactly what `on_show` does for a tab opened fresh — but only when this tab has
        # actually been shown; an unopened one has nothing on screen to drop, and
        # `on_show` seeds it from the right profile whenever it next is.
        self._rows.clear()
        self._collected.clear()
        self._auto_attempted.clear()
        self._restore_pending = set()
        # The alliance below belongs to the old account just as much — a different
        # account is a different alliance, and its tiles are not this one's (#1244).
        self.alliance.clear()
        if self.loaded:
            self._restore_pending = self._load_persisted()
            self._render()
            self._update_status()
            self._snapshot()
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
        # is only half the table. Both tables, for the same reason.
        self._render()
        self.alliance.retranslate()
        self.alliance.render()

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
                     "secret_clock", "autoloot_push_restart"):
            self.rt.tick.disarm(name)
        self._ticking = self._polling = False

    # -- persistence ----------------------------------------------------------
    def config(self) -> dict:
        return {
            "monitor_kind": self.kind_index(),
            "monitor_interval": self.interval_var.get(),
            "secret_monitor": bool(self.monitor_var.get()),
            "show_spent": bool(self.show_spent_var.get()),
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
        self.show_spent_var.set(bool(raw.get("show_spent", False)))
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
        return [self.monitor_var, self.interval_var, self.show_spent_var,
                self.filter_from_var, self.filter_to_var,
                self.autoloot_var, self.level_from_var, self.level_to_var,
                self.skip_own_var, self.sweep_var, self.sweep_cx_var, self.sweep_cy_var,
                self.coord_x_var, self.coord_y_var, self.coord_srv_var]

    # -- UI -------------------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                "tab.secret_tasks").pack(side="left")
        self.tr(ttk.Button(bar, width=12, command=self.refresh_both),
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
        self.tr(ttk.Label(row2), "secret.filter_level_from").pack(
            side="left", padx=(0, 2))
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
        """The two tables: the starred raid targets, and the alliance's own list (#1244).

        A `ttk.Treeview` rather than a stack of frames (#1209). The rows used to be packed
        by hand, each label carrying its own width, so nothing lined up under anything and
        a long countdown pushed its neighbours off the row. Here the widths belong to the
        columns, the header stays put while the list scrolls, and a heading sorts.

        What a Treeview cannot hold is a widget, so the two row actions live under it and
        act on the selection — plus the right-click menu, and the coordinate link.

        The second grid is the same table again (`grid.py`, `alliance.py`) with the
        alliance's whole list in it, stars and plain tiles alike. The two share the height
        through a `PanedWindow` rather than splitting it in a fixed ratio: which of the
        two is being read changes by the hour, and dragging the sash is how the operator
        says which one it is right now.
        """
        # The action strip is packed FIRST, against the bottom: pack clips whatever was
        # packed last when the window is short, and the buttons are the one thing on the
        # tab that must never be the part that falls off the edge.
        acts = ttk.Frame(self.parent)
        acts.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        panes = ttk.PanedWindow(self.parent, orient="vertical")
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 0))
        wrap = ttk.Frame(panes)
        panes.add(wrap, weight=3)
        self._empty = self.tr(ttk.Label(wrap, foreground="#888"), "secrettasks.empty")
        self._body = ttk.Frame(wrap)
        self._body.pack(fill="both", expand=True)

        tree = grid.make_tree(self._body)
        tree.bind("<Button-1>", self._on_click)
        tree.bind("<Double-Button-1>", self._on_double_click)
        tree.bind("<Button-3>", self._on_right_click)
        tree.bind("<Motion>", self._on_motion)
        tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_actions())
        self._tree = tree
        self._retranslate_headings()
        panes.add(self.alliance.build(panes), weight=2)

        self._goto_btn = self.tr(ttk.Button(acts, width=12, command=self._goto_selected),
                                 "secrettasks.goto")
        self._goto_btn.pack(side="left")
        # «Показывать исчерпанные» — off by default (#1227). A 3/3 tile has no slot for
        # anybody, so it is only in the way of the eye; the box is here so that a row
        # that disappears can still be accounted for, rather than leaving the operator
        # to wonder whether the list lost it.
        self.tr(ttk.Checkbutton(acts, variable=self.show_spent_var,
                                command=self._on_show_spent),
                "secrettasks.show_spent").pack(side="left", padx=(12, 0))
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

    #: How each column orders — `grid.SORT_KEYS`, kept under the name the headings ask
    #: for it by.
    SORT_KEYS = grid.SORT_KEYS

    def _sorted_rows(self, rows) -> list:
        """The rows in the order the table shows them (`grid.sort_rows`)."""
        return grid.sort_rows(rows, self._sort)

    def _row_values(self, row) -> tuple:
        """One row as the cells of the table, in the order COLUMNS declares.

        The coordinate cell is the canonical `X:.. Y:..` token — the same one the log
        prints and `coords.parse` reads back — with the server standing in its own column
        beside it rather than glued to the front of it.
        """
        import coords as coords_fmt
        ready = bool(row.get("ready"))
        can_take = self._collectable(row)
        return (coords_fmt.fmt(row["x"], row["y"]),
                self.t("secrettasks.server", srv=row["server"]),
                "%s %s" % (READY_GLYPH if ready else TYPE_GLYPH,
                           self.t("secrettasks.stars", n=int(row["level"] or 0))),
                row["timer"].get(),
                self.t("secrettasks.slots", n=int(row["loot_count"] or 0)),
                self.t("secrettasks.collect") if can_take else "")

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
        return grid.column_at(self._tree, event)

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
        elif where == ACTION_COLUMN and self._collectable(row):
            self._collect(row)

    def _live_cell(self, event) -> bool:
        """Whether the cell under the pointer is one a click would act on."""
        where = self._column_at(event)
        if where == LINK_COLUMN:
            return True
        row = self._row_at(event)
        return where == ACTION_COLUMN and bool(row and self._collectable(row))

    def _on_motion(self, event) -> None:
        """The link cursor over a cell that acts, the ordinary one everywhere else."""
        try:
            self._tree.configure(cursor="hand2" if self._live_cell(event) else "")
        except tk.TclError:
            pass

    def _on_double_click(self, event) -> None:
        """Double-click a ready row to rob it — the one-press collect the rows had."""
        row = self._row_at(event)
        if row is not None and self._collectable(row):
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
        if self._collectable(row):
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
                             (self._collect_btn, bool(row and self._collectable(row)))):
            if widget is None:
                continue
            try:
                widget.state(("!disabled",) if live else ("disabled",))
            except tk.TclError:
                pass

    def _collect_selected(self) -> None:
        row = self._selected()
        if row is not None and self._collectable(row):
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

    def _on_show_spent(self) -> None:
        """«Показывать исчерпанные» was flipped: redraw the list, nothing else.

        A pure display rule — it changes no robbery and touches no game. The rows are
        all still in memory either way, so this costs a repaint.
        """
        self.rt.settings.changed()
        self._render()
        self._update_status()

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

    def _autoloot_line(self) -> str:
        """The auto-loot label: what it would rob, and what it is doing about it.

        Two questions, and until #1227 only the first was answered. A standing order that
        finds no star of its level says nothing at all — which reads exactly like one
        that never started, and that is what «автолут не работает совершенно» was.
        """
        return f"{self.autoloot.rule_text()} · {self.autoloot.state_text()}"

    def _refresh_rule_hints(self) -> None:
        """Re-render the two "this is what the checkbox will do" lines.

        Both standing orders are invisible otherwise, and an invisible rule is how a
        robbery got spent on a level-6 star.
        """
        self._rule_line = None                 # say it again even if the words match
        self._refresh_autoloot_line()
        if self._sweep_hint is not None:
            try:
                self._sweep_hint.configure(text=self.sweep.rule_text())
            except tk.TclError:
                pass

    def _refresh_autoloot_line(self) -> None:
        """Redraw the auto-loot label, and only when its words have actually changed.

        The state behind it moves on the watcher's own thread, so the second-by-second
        countdown is what notices; a `configure` per second per profile is exactly the
        kind of Tk traffic #1226 went looking for, and comparing two strings is not.
        """
        if self._rule_lbl is None:
            return
        line = self._autoloot_line()
        if line == self._rule_line:
            return
        self._rule_line = line
        try:
            self._rule_lbl.configure(text=line)
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
        """Read the game's own alliance table once: the seed above, the mirror below.

        One round trip fills both grids (#1244) — the starred tasks are merged into the
        working list, and the whole answer replaces the alliance grid.
        """
        if self._vm_busy:
            return
        self._vm_busy = True
        self._status_var.set(self.t("tabx.loading"))
        threading.Thread(target=self._snapshot_work, daemon=True).start()

    def _snapshot_work(self) -> None:
        try:
            tasks = self._fetch_vm()
            read_ok = True
        except Exception:                     # noqa: BLE001 — a failed read is an empty tab
            tasks, read_ok = [], False
        # A failed read (no daemon, no game up yet — routine right after the panel
        # starts) is not evidence a restored row is gone, exactly like a failed poll
        # read is not (`_poll_apply`) — so nothing restored is reconciled against it,
        # and the pending set survives for whenever a read next succeeds.
        pending = self._restore_pending if read_ok else None
        if read_ok:
            self._restore_pending = set()
        self.after(lambda: self._vm_landed(tasks, pending, read_ok))

    def _vm_landed(self, tasks, pending, read_ok: bool) -> None:
        """The VM read, back on the Tk thread: the stars up, the whole list down.

        The alliance grid is only touched by a read that WORKED. A failed one says
        nothing about the alliance's tasks — emptying the table on it would turn "the
        daemon was busy for a second" into "your alliance has nothing out", which is the
        same lie `_merge` refuses to tell about a restored row.
        """
        self._vm_busy = False
        self._merge([t for t in tasks if t.starred], pending)
        if read_ok:
            self.alliance.apply(tasks)

    def refresh_live(self) -> None:
        """A share landed: re-read both lists — but only if the tab has been opened.

        An unopened one reads fresh when it is first shown. The VM read is in here as
        well as the checkpoint merge because the push that fires this is exactly the
        event that changes the game's own alliance table (#1244).
        """
        if self.loaded:
            self.refresh()
            self._snapshot()

    def refresh_both(self) -> None:
        """«Обновить»: the wire feed for the list above, the game's table for the one below.

        One press, both grids (#1244) — the checkpoint merge costs a file read, the VM
        read one round trip through the warm daemon. They are deliberately NOT one flag:
        each guards its own path, so neither can silently skip because the other happened
        to be in flight.
        """
        self.refresh()
        self._snapshot()

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
        self.after(lambda: self._wire_landed(tasks))

    def _wire_landed(self, tasks) -> None:
        """The checkpoint read, back on the Tk thread — and the flag it was holding.

        Clearing `_busy` is this path's own business rather than `_merge`'s since #1244:
        the VM read merges through the very same method, and one path clearing the
        other's flag is how a refresh in flight quietly gets a second thread.
        """
        self._busy = False
        self._merge(tasks)

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
        """Every live alliance secret task straight from the VM — stars and plain alike.

        Every tile the game still lists with a free slot: the ones already raidable AND
        the ones still counting down, so a row can carry its «готово через …» timer and
        flip to raidable in place.

        Unfiltered since #1244, because the answer feeds BOTH grids: the caller keeps
        the starred ones for the working list above and hands the whole reply to the
        alliance grid below. The star filter used to live here, which is why the lower
        list could not exist without a second round trip.
        """
        import steal_secret_task
        return steal_secret_task._vm_all_alliance_tasks(self.rt.game.evaluator())

    def _merge(self, tasks, verify: "set | None" = None) -> None:
        """Add tiles the list does not have yet; keep the ones it does.

        A rescan only ADDS — an existing row keeps its place and its timer, a tile robbed
        by hand this session is skipped, and nothing already on screen is torn out from
        under the operator. Expiry and the ready-transition are the tick's job.

        A looted-out (3/3) tile is merged like any other and hidden by the display rule
        instead (:meth:`_visible_rows`), so «Показывать исчерпанные» has something to
        show. Only the wire feed carries them at all — the VM read drops them itself.

        ``verify`` is the one exception to "only ADDS" (#1242): the keys `on_show`
        restored from disk, still unconfirmed by a live read. A key in it that IS in
        ``tasks`` is a restored row the game just confirmed — refreshed in place, the
        same fields the ready-row poll refreshes (:meth:`_poll_apply`) — and one that is
        NOT is a restored row the game does not back any more (expired, looted out, or
        simply gone while the panel was shut) and comes off the list rather than sit
        there unconfirmed.

        Whichever read it came from is that read's own affair: the two paths land here
        through `_wire_landed` / `_vm_landed`, and each clears the flag it was holding.
        """
        incoming = {str(t.uuid): t for t in tasks}
        if verify:
            for key in verify:
                row = self._rows.get(key)
                if row is None:                    # already gone some other way
                    continue
                task = incoming.pop(key, None)
                if task is None:
                    self._rows.pop(key, None)
                    continue
                row["expires_at"] = task.expires_at
                row["completed_at"] = task.completed_at
                row["loot_count"] = task.loot_count
        for key, t in incoming.items():
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
                "timer": tk_stringvar(self.rt.root), "ready": False, "soon": False,
            }
        self._render()
        # An empty list after a clean read is "no starred tile right now", not "no game" —
        # the scroll's own hint says so, so the status stays blank rather than crying
        # about a game that may be perfectly up.
        self._update_status()
        self._maybe_start_poll()
        self._persist_rows()

    # -- surviving a restart (#1242) --------------------------------------------
    def _persist_rows(self) -> None:
        """Checkpoint the session list whole, so the panel closing does not forget it.

        Called after every structural change (`_merge`, a collect, an expiry, the
        ready-row poll) — the same "rewrite the whole small file" pattern every other
        profile checkpoint here uses (`panel/profile.py`), not a diff. Only the fields
        `_load_persisted` needs to rebuild a row are kept; the countdown StringVar and
        the `ready`/`soon` flags are UI state, recomputed from `expires_at`/
        `completed_at` the moment the row is drawn again.
        """
        from ...profile import _write_json
        _write_json(self.rt.profiles.secret_tasks_state_json(), [
            {"uuid": r["uuid"], "server": r["server"], "x": r["x"], "y": r["y"],
             "level": r["level"], "cfg_id": r["cfg_id"], "loot_count": r["loot_count"],
             "expires_at": r["expires_at"], "completed_at": r["completed_at"]}
            for r in self._rows.values()])

    def _load_persisted(self) -> set:
        """Read back the last session's list; return the keys still needing a live check.

        A row already past its own `expires_at` is dropped here rather than shown and
        then dropped a moment later by the first tick — there is nothing a live check
        could confirm about a tile the map itself says is gone. Judged against the
        GAME's clock (#1227), like every other timestamp on this tab, not this
        machine's — `game_clock` needs no game read to answer, only the drift it last
        measured (0 the first time this profile is ever opened).

        Malformed or missing (no prior session, or one before #1242) reads as "nothing
        to restore" rather than raising — a checkpoint is a convenience, never a
        requirement the tab depends on to open.
        """
        import game_clock
        try:
            with open(self.rt.profiles.secret_tasks_state_json(), encoding="utf-8") as fh:
                records = json.load(fh)
        except (OSError, ValueError):
            return set()
        if not isinstance(records, list):
            return set()
        now = game_clock.now_ms()
        restored: set = set()
        for rec in records:
            if not isinstance(rec, dict):
                continue
            try:
                uuid = int(rec["uuid"])
            except (KeyError, TypeError, ValueError):
                continue
            exp = rec.get("expires_at")
            if exp is not None and exp <= now:
                continue
            key = str(uuid)
            self._rows[key] = {
                "uuid": uuid, "server": rec.get("server"), "x": rec.get("x"),
                "y": rec.get("y"), "level": rec.get("level"),
                "cfg_id": rec.get("cfg_id"), "loot_count": rec.get("loot_count") or 0,
                "expires_at": exp, "completed_at": rec.get("completed_at"),
                "timer": tk_stringvar(self.rt.root), "ready": False, "soon": False,
            }
            restored.add(key)
        return restored

    # -- the phone ---------------------------------------------------------------
    #
    # READING ONLY, and that is a decision rather than an omission. The robbery on this
    # tab spawns its own tool because the recipe only spends a queue that tool fills
    # (`CLAUDE.md`, task #1188) — a «Ограбить» button on the phone would be a SECOND
    # copy of that debt, in a second place, reached from outside the house. The tiles,
    # their countdowns and how many robberies are left is what somebody away from the
    # machine actually needs: it is what decides whether to go home and press it.
    WEB_SCREEN = True

    def web_view(self) -> "dict | None":
        """The starred tiles as cards, newest deadline first. Reads nothing.

        The rows are already in memory — the capture fills them and the table draws
        them — so this is a dictionary walk, which is what `web_view` is contracted to
        be (panel/tabs/base.py).
        """
        # Both imported here rather than at the top: `coords` lives in tools/lib, which
        # is only on the path once `panel.runtime.paths` has run, and this module is
        # imported before that in a standalone tab.
        import coords
        import game_clock

        # The phone counts down from `now` to `until` and both are epoch SECONDS
        # (panel/tabs/base.py) — the tile's timestamps are the game's MILLISECONDS, so
        # they are divided below. And `now` is the GAME's now: a countdown on the phone
        # is drawn from the same clock the game's own is, or it is off by the drift
        # between the two the same way the window's was (#1227).
        now = game_clock.now_ms() / 1000.0
        items = []
        # The same rows the window draws, under the same rule — the level range AND the
        # looted-out tiles «Показывать исчерпанные» governs (#1227). A phone showing a
        # spent tile the window has taken off the list is the divergence CLAUDE.md
        # forbids, and the worse half of it: whoever is away from the machine cannot
        # check which of the two is right.
        for row in sorted(self._visible_rows(),
                          key=lambda r: (not r.get("ready"),
                                         r.get("expires_at") or float("inf"))):
            facts = [{"label": "secrettasks.col.level", "value": str(row.get("level"))},
                     {"label": "secrettasks.col.slots",
                      "value": f"{row.get('loot_count')}/3"}]
            done, exp = row.get("completed_at"), row.get("expires_at")
            # A spent tile says so instead of saying «готово»: it is on the list only
            # because the box asked for it, and «ready» on a row nobody can rob is the
            # single most misleading word the screen could carry.
            spent = self._spent(row)
            items.append({
                "text": coords.fmt(row.get("x"), row.get("y"), row.get("server")),
                "facts": facts,
                # Ready: how long is left to take it. Not ready: when it becomes one.
                "until": ((exp if row.get("ready") else done) or 0) / 1000.0 or None,
                "pill": ("secrettasks.spent" if spent
                         else "secrettasks.ready" if row.get("ready") else None),
            })
        # What «Автолут ★» is doing, in the same words the window puts under the
        # checkbox. It is the reading somebody away from the machine most needs: the
        # tiles say what is on the map, this says whether anything is going to be taken
        # — and «nothing, the day's five are spent» is not a thing to guess at (#1227).
        state_key, state_datum = self.autoloot.state()
        return {"cards": [{"title": "secret.autoloot.frame",
                           "rows": [{"label": state_key, "value": state_datum}]},
                          {"title": None, "items": items,
                           "empty": "secrettasks.empty"},
                          # The window's second table, as the phone's second card
                          # (#1244): the alliance's whole list, stars and plain tiles
                          # alike. Titled, unlike the one above it, because two
                          # untitled lists of coordinates on one screen are
                          # indistinguishable — and which list a tile is in is the
                          # whole point of there being two.
                          {"title": "secrettasks.alliance",
                           "items": self.alliance.web_items(),
                           "empty": "secrettasks.alliance.empty"}],
                "now": now,
                # The button names what pressing it will do, because a phone has no
                # checkbox to carry the state in: «Показать исчерпанные» while they are
                # hidden, «Скрыть» while they are not.
                "actions": [{"id": "refresh", "label": "tabx.refresh"},
                            {"id": "show_spent",
                             "label": ("secrettasks.hide_spent"
                                       if self.show_spent_var.get()
                                       else "secrettasks.show_spent")},
                            {"id": "clear", "label": "secrettasks.clear"}]}

    def web_press(self, action: str, args: dict) -> dict:
        """«Обновить», and the two display rules the phone may change.

        Still no «Ограбить» — the robbery on this tab spawns its own tool because the
        recipe only spends a queue that tool fills (`CLAUDE.md`, #1188), and a second
        copy of that reached from outside the house is the same debt twice.
        «Показывать исчерпанные» and «Очистить список» decide nothing in the game, only
        the local list, so the phone gets the same two the window has.
        """
        if action == "refresh":
            # The window's «Обновить» refreshes both tables, so the phone's does too.
            self.refresh_both()
            return {"ok": True}
        if action == "show_spent":
            self.post(self._toggle_show_spent)
            return {"ok": True}
        if action == "clear":
            self.post(self._clear)
            return {"ok": True}
        return {"error": "unknown"}

    def _toggle_show_spent(self) -> None:
        """Flip «Показывать исчерпанные» from the phone, on the Tk thread.

        Through the same variable the window's box is bound to, so the two front-ends
        cannot disagree about which way it is set.
        """
        self.show_spent_var.set(not self.show_spent_var.get())
        self._on_show_spent()

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
                        tags=(grid.row_tag(row),))
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
        grid.paint_timers(self._tree, self._rows)

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

    def _spent(self, row) -> bool:
        """Whether the tile has been robbed as often as the game allows.

        Three looters and the tile is finished: there is no slot left for anybody,
        so a robbery on it is a press the server refuses and a row on the list is a
        line that can only mislead — it draws «готово к сбору» like a real target,
        offers the same «Собрать» cell, and sorts among the tiles worth going to
        (#1227). The wire feed is where they come from: the capture reports every
        tile the map re-sent, spent or not, while the VM read drops them itself.
        """
        import lastwar_proto as proto      # lazy: tools/lib is on the path by now
        return int(row.get("loot_count") or 0) >= proto.MAX_LOOTERS

    def _collectable(self, row) -> bool:
        """Whether «Собрать» means anything on this row.

        Ready is not enough once a spent tile can be on screen: with «Показывать
        исчерпанные" ticked a 3/3 row is visible, and it is visible precisely because
        it is finished — pressing it would spend one of the day's five on a robbery the
        server refuses (#1227).
        """
        return bool(row.get("ready")) and not self._spent(row)

    def _visible_rows(self) -> list:
        """The rows the tab shows: inside the level range, and not looted out.

        The second half is what «Показывать исчерпанные» lifts. It is off by default
        because a 3/3 tile cannot pay anybody and only costs the eye a line, and it
        exists at all so that a row that vanishes can be looked for rather than
        guessed at (#1227).
        """
        show_spent = bool(self.show_spent_var.get())
        return [r for r in self._rows.values()
                if self._in_range(r["level"]) and (show_spent or not self._spent(r))]

    def _update_status(self) -> None:
        n = len(self._visible_rows())
        self._status_var.set(self.t("secrettasks.count", n=n) if n else "")

    # The uuid tail used to have a column of its own. It is gone with the table (#1209):
    # a tile is named by its coordinate and its server everywhere else in the panel — the
    # log line, the chat share, the jump — and an 18-digit id nobody can read out loud
    # was taking the width the countdown needed. The uuid still travels with the row and
    # is what the robbery is sent with; it is simply not what a person is shown.

    # -- the game's clock ------------------------------------------------------
    def _start_clock_sync(self) -> None:
        """Learn the game's clock now, and keep learning it while the tab is open.

        Every countdown on this tab is drawn against `game_clock`, and it only knows the
        drift once somebody has measured it. The VM reads the tab already makes carry the
        measurement for free, but a tab fed only by the wire (the capture's checkpoint,
        with no row ready enough to poll) would never make one — and an unmeasured clock
        is the old behaviour, off by however far the game has drifted from this machine.

        One line through the warm daemon, five minutes apart, skipped whenever the game
        is not up. Off the Tk thread, like every other daemon round trip here.
        """
        self._sync_clock()
        self.rt.tick.arm("secret_clock", CLOCK_MS, self._start_clock_sync)

    def _sync_clock(self) -> None:
        if not (self.rt.game.up() and not self.rt.game.busy):
            return

        def work() -> None:
            try:
                import game_clock
                game_clock.read(self.rt.game.evaluator())
            except Exception:                 # noqa: BLE001 — an unread clock is not fatal
                pass

        threading.Thread(target=work, daemon=True).start()

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
            # Only an expiry is a structural change worth a write — `changed` alone is
            # the ready/soon flags flipping, which the checkpoint does not carry and
            # `_load_persisted` recomputes anyway, so writing on it would be a rewrite
            # of the same file every second for no reader to ever see (#1242).
            if expired:
                self._persist_rows()
            # The standing order reports from its own thread; this is where the words
            # under the checkbox catch up with it.
            self._refresh_autoloot_line()
            self._maybe_start_poll()
            # The grid below counts down on the same second as this one — one chain for
            # the tab, not a timer per table.
            self.alliance.tick()
        finally:
            # Named, so the countdown is one chain however often `_start_ticking` is
            # reached.
            self.rt.tick.arm("secret_tick", 1000, self._tick)

    def _refresh_timers(self) -> tuple:
        """Rewrite every row's timer; return (expired keys, did ready/soon change on any).

        The arithmetic is `grid.refresh_timers` — the grid below runs the very same one
        on its own rows every second (#1244).
        """
        return grid.refresh_timers(self._rows, self.t)

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
        self._persist_rows()

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
            if self._collectable(row) and self._in_range(row["level"])
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
            # The same tile can be on both tables — one robbery, so it leaves both.
            self.alliance.drop(key)
            self._render()
            self.rt.put("[secret] " + self.t("secrettasks.collect_ok"))
            self._update_status()
            self._persist_rows()
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
        """«Очистить список» (#1243): wipe every row, on screen and on the checkpoint.

        Not a tidy-up of the stale ones — expired tiles already fall off on their own
        each second, so a button that only swept those away had nothing left to do. This
        empties the table outright and forgets the session's collected set, so a task
        robbed earlier can be re-listed by the next scan if the server still shows it
        raidable. Nothing here is lost for good: the wire feed and the next VM snapshot
        repopulate the list from the live game, same as a fresh «Обновить».

        The alliance table below is deliberately untouched: it accumulates nothing to
        clear — every read replaces it whole — so wiping it would only blank a mirror
        until the next round trip redrew exactly the same rows (#1244).
        """
        self._rows.clear()
        self._collected.clear()
        self._restore_pending = set()
        self._render()
        self._update_status()
        self._persist_rows()


# The countdown's own formatting moved to `grid.py` with the rest of the table (#1244);
# it is still reachable under the name every caller and test here knows it by.
_fmt_left = grid.fmt_left
