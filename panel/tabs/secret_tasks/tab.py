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

Kept Tk-thin: the two game round trips (scan, steal) and the share run on background
threads and degrade gracefully — no daemon, no game, or a manager not loaded yet leaves
the list empty and never crashes the tab.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ...runtime import captures as capturemod
from ...widgets import (NumericEntry, ScrollableFrame, numeric_spinbox,
                        tk_stringvar, font as ui_font)
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
        self._status_var = tk_stringvar(master)
        self._scroll = None
        self._combo = None

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
        self.sweep_var = tk.BooleanVar(master=master, value=False)
        self.sweep_cx_var = tk.StringVar(master=master)
        self.sweep_cy_var = tk.StringVar(master=master)
        self._sweep_hint = None
        self._rule_lbl = None

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
        """Start the standing orders this profile asked for, and seed the list.

        The seed is a one-time VM snapshot — the game's parsed table, richest and
        available even before the capture has flushed a checkpoint. After it the wire
        feeds the list. Idempotent: the shell calls this at boot (the orders have to be
        running whether or not anybody opens the tab) and again on first show.
        """
        if self.monitor_var.get():
            self.capture.start()
        if self.autoloot_var.get():
            self.autoloot.start()
        if self.sweep_var.get():
            self.sweep.start()
        if not self.loaded:
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
        self._refresh_rule_hints()
        if self.monitor_var.get():
            self.capture.start()
        if self.autoloot_var.get():
            self.autoloot.start()
        if self.sweep_var.get():
            self.sweep.start()

    def on_language_change(self) -> None:
        self._retranslate_combo()
        self._refresh_rule_hints()

    def panic(self) -> None:
        """«Стоп всё»: every standing order down, and the boxes say so."""
        for var, order in ((self.monitor_var, self.capture),
                           (self.autoloot_var, self.autoloot),
                           (self.sweep_var, self.sweep)):
            var.set(False)
            order.stop()

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
            "map_sweep": bool(self.sweep_var.get()),
            "sweep_centre_x": self.sweep_cx_var.get(),
            "sweep_centre_y": self.sweep_cy_var.get(),
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
        self.sweep_var.set(bool(raw.get("map_sweep", False)))
        self.sweep_cx_var.set(raw.get("sweep_centre_x", ""))
        self.sweep_cy_var.set(raw.get("sweep_centre_y", ""))
        self._refresh_rule_hints()

    def persist_vars(self) -> list:
        return [self.monitor_var, self.interval_var, self.star_var, self.pending_var,
                self.can_loot_var, self.filter_from_var, self.filter_to_var,
                self.autoloot_var, self.level_from_var, self.level_to_var,
                self.sweep_var, self.sweep_cx_var, self.sweep_cy_var]

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

        self._build_monitor_bar()
        self._build_filter_bar()

        self.tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                          justify="left"), "secrettasks.hint").pack(
            anchor="w", padx=10, pady=(0, 6))

        self._scroll = ScrollableFrame(self.parent)
        self._scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._refresh_rule_hints()

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
        """The level range and «Автолут ★» — the rule the robberies obey.

        The same range doubles as the list's display filter (:meth:`_in_range`), so the
        operator sees exactly the tiles the standing order is about to weigh.
        """
        bar = self.tr(ttk.LabelFrame(self.parent, padding=6), "secret.autoloot.frame")
        bar.pack(fill="x", padx=10, pady=(0, 4))
        self.tr(ttk.Checkbutton(bar, variable=self.autoloot_var,
                                command=self.autoloot.toggle),
                "secret.autoloot").pack(side="left")
        self.tr(ttk.Label(bar), "secret.autoloot.level_from").pack(
            side="left", padx=(12, 2))
        NumericEntry(bar, textvariable=self.level_from_var, width=4).pack(side="left")
        self.tr(ttk.Label(bar), "secret.level_to").pack(side="left", padx=(6, 2))
        NumericEntry(bar, textvariable=self.level_to_var, width=4).pack(side="left")
        self._rule_lbl = ttk.Label(bar, foreground="#888", wraplength=380,
                                   justify="left")
        self._rule_lbl.pack(side="left", padx=(10, 0))
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
        if self._scroll is None:
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
                "timer": tk_stringvar(self.rt.root), "frame": None, "ready": False,
            }
        self._render()
        # An empty list after a clean read is "no starred tile right now", not "no game" —
        # the scroll's own hint says so, so the status stays blank rather than crying
        # about a game that may be perfectly up.
        self._update_status()
        self._maybe_start_poll()

    # -- drawing ---------------------------------------------------------------
    def _render(self) -> None:
        """Rebuild the scroll from the current rows, the best raids on top.

        Sorted the way auto-loot prizes them: the highest star first, and within a level
        the tile that expires soonest. Called on a merge / collect / clear, NOT every
        second — the countdown is a StringVar the tick writes in place.
        """
        if self._scroll is None:
            return
        for child in self._scroll.winfo_children():
            child.destroy()
        rows = self._visible_rows()
        if not rows:
            self.tr(ttk.Label(self._scroll, foreground="#888"),
                    "secrettasks.empty").grid(row=0, column=0, sticky="w", pady=6)
            return
        rows = sorted(rows, key=lambda r: (-int(r["level"] or 0),
                                           r["expires_at"] or float("inf")))
        for r in rows:
            r["frame"] = self._row_widget(r)
            r["frame"].pack(fill="x", pady=1)
        self._refresh_timers()

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

    # The row is packed left-to-right: icon, stars, coords, countdown, uuid, then the
    # action buttons on the right. Built one row at a time (not a shared grid) so a
    # collect can drop a single row without re-flowing the columns of the rest. A ready
    # tile is drawn green with the ✅ glyph and grows its «Собрать» button; one still
    # counting down shows only «Поделиться», since collecting it early is a robbery the
    # server would refuse.
    def _row_widget(self, row):
        import coords as coords_fmt
        ready = bool(row.get("ready"))
        frame = ttk.Frame(self._scroll)
        ttk.Label(frame, text=READY_GLYPH if ready else TYPE_GLYPH,
                  font=ui_font(size=15)).pack(side="left", padx=(0, 6))
        stars = ttk.Label(frame, text=self.t("secrettasks.stars",
                                             n=int(row["level"] or 0)),
                          font=ui_font(weight="bold"), width=52)
        if ready:
            stars.configure(foreground=READY_COLOR)
        stars.pack(side="left", padx=(0, 8))
        ttk.Label(frame, text=coords_fmt.fmt(row["x"], row["y"], row["server"]),
                  width=110).pack(side="left", padx=(0, 8))
        ttk.Label(frame, textvariable=row["timer"],
                  foreground=READY_COLOR if ready else TIMER_COLOR,
                  width=150, anchor="w").pack(side="left", padx=(0, 8))
        ttk.Label(frame, text=self._short_uuid(row["uuid"]), foreground="#888").pack(
            side="left", padx=(0, 8))
        share = ttk.Button(frame, width=12)
        share.configure(command=lambda b=share, r=row: self._open_share_menu(b, r))
        self.tr(share, "secrettasks.share").pack(side="right", padx=(4, 0))
        if ready:
            self.tr(ttk.Button(frame, width=12,
                               command=lambda r=row: self._collect(r)),
                    "secrettasks.collect").pack(side="right")
        return frame

    @staticmethod
    def _short_uuid(uuid) -> str:
        """The last 8 digits of a uuid — the full value is 18+ digits and only its tail
        tells two tiles apart on screen."""
        s = str(uuid)
        return "…" + s[-8:] if len(s) > 8 else s

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
