"""The «Secret Tasks» tab: the starred hero-dispatch tiles the alliance can raid.

This tab keeps the **starred** secret tasks — the raids worth a march — on screen, each
with a per-second countdown to the moment it becomes raidable, and offers the two things
a person does with one: rob it (`hero.dispatch.steal`) or forward it into chat.

**Where the list comes from — the wire, not a VM scan.** The passive secret-task capture
(`tools/secret_task_capture.py`, the monitor whose block also lives on this tab now) reads
the tiles off the game stream as the map moves and writes them to a checkpoint every tick,
each record carrying the full coordinates + `completed_at` / `expires_at` a countdown
needs. This tab's ongoing feed is that checkpoint (`_fetch_scan` → `load_fresh_tasks`): a
finding crossing the wire nudges the tab to merge the freshly-written checkpoint, so a tile
the capture just saw appears with a real timer and no game round-trip. The Lua VM
(`ActDispatchTaskDataManager.allianceTask`) is read **once**, as the first-open snapshot
(`_fetch_vm`), to seed the list before the monitor has flushed anything; after that the
wire drives it.

When a tile's countdown reaches zero it is raidable: its row is highlighted, and a slow
background poll (~30 s) starts re-reading the game — if the tile is gone (expired or
looted out) the row drops, and while auto-loot is ticked a raidable tile is robbed. That
poll is a targeted per-tile *verify* under auto-loot (a raid spends the scarce daily
budget, so it wants the game's authoritative word, not a stale checkpoint), distinct from
the wire feed that populates the list. It runs only while at least one row is ready, so an
idle tab never touches the daemon.

What is on the tab is an in-memory list for the session, not a store — closing the panel
forgets it, which is fine: the first-open VM snapshot re-seeds it and the wire refills it.
«Обновить» re-merges the current checkpoint. While the «secret_task_share» trigger is
switched on, an alliancemate sharing a task re-merges too.

The passive-capture monitor block (kind, interval, log filters, «Автообъезд карты») and
the «уровень от / до» range with «Автолут ★» live on this tab now — they used to sit on
the Main tab. Only the *widgets* moved here: their vars and every method (the monitor
start/stop, the sweep) stay on the app, so the settings save/load and the profile-switch
restart are untouched. The «уровень от / до» range doubles as the list's display filter —
a starred tile shows only while its level is inside it. The «Операция Призрак» block
passed through here too and now sits on the «Секретный командный пункт» tab
(panel/command_post.py), beside the rest of that event.

Kept Tk-thin: the two game round trips (scan, steal) and the share run on background
threads and degrade gracefully — no daemon, no game, or a manager not loaded yet leaves
the list empty and never crashes the tab.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from .widgets import NumericEntry, ScrollableFrame, font as ui_font, numeric_spinbox
from .tabs_extra import tk_stringvar

# The star glyph in front of a row and the icons for the two row states: a tile still
# counting down to raidability, and one that is ready to loot now.
STAR_GLYPH = "⭐"
TYPE_GLYPH = "🗡️"
READY_GLYPH = "✅"

# The amber the countdown is drawn in, and the green a ready row switches to.
TIMER_COLOR = "#e0a84f"
READY_COLOR = "#4fe08a"

# How often the ready-row poll re-reads the game once a tile is raidable. Slow on
# purpose — a raidable tile lives for minutes, and this is the tab's own safety net, not
# the app's sub-second auto-loot watcher.
POLL_MS = 30_000

# The two channels a task can be forwarded to. The room ids are built from the
# player's own server / alliance, read once and cached (see `_self_ids`).
SHARE_ALLIANCE = "alliance"
SHARE_WORLD = "world"


class SecretTasksTab:
    """The starred-secret-task list, its per-second timers and its two actions.

    Not a :class:`panel.tabs_extra._DataTab`: the countdown loop, the per-row buttons
    and the collected/expired bookkeeping do not fit the load-once/refresh shape. The
    threading is the same idea, though — :meth:`fetch` runs off the Tk thread and the
    render is marshalled back with ``app.after``.
    """

    def __init__(self, app, parent) -> None:
        self.app = app
        self.parent = parent
        self._loaded = False
        self._busy = False
        self._ticking = False
        # uuid (str) -> row record. The record carries the task data, its countdown
        # StringVar and the row's frame, so a tick can update the timer in place and a
        # collect/clear can drop the row without a full re-read.
        self._rows: dict[str, dict] = {}
        # Tasks robbed by hand this session: a rescan must not re-add one that the
        # server has not yet dropped from `allianceTask`.
        self._collected: set[str] = set()
        # uuids auto-loot has already fired at this session — one attempt per tile, so a
        # 30-s poll on a spent budget does not re-send every tick.
        self._auto_attempted: set[str] = set()
        # Whether the ready-row poll loop is currently scheduled (started when the first
        # row turns raidable, stops when none is left).
        self._polling = False
        # Cached (server, allianceId) for the chat room ids — read once, live.
        self._ids: tuple[str, str] | None = None
        self._status_var = None
        self._build()

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """First time the tab is shown: start the countdown loop and seed the list.

        The seed is a one-time VM snapshot (`_snapshot`) — the game's parsed table,
        richest and available even before the monitor has flushed a checkpoint. After
        it, the wire feeds the list (a monitor nudge / «Обновить» / the share trigger
        all go through :meth:`refresh`, which merges the capture checkpoint).
        """
        if not self._loaded:
            self._loaded = True
            self._start_ticking()
            self._snapshot()

    def _snapshot(self) -> None:
        """The one-time first-open seed: read the VM once and merge it."""
        if self._busy:
            return
        self._busy = True
        if self._status_var is not None:
            self._status_var.set(self.app._t("tabx.loading"))
        threading.Thread(target=self._snapshot_work, daemon=True).start()

    def _snapshot_work(self) -> None:
        try:
            tasks = self._fetch_vm()
        except Exception:                     # noqa: BLE001 — a failed read is an empty tab
            tasks = []
        self.app.after(0, lambda: self._merge(tasks))

    def refresh(self) -> None:
        """Merge the live capture checkpoint (the wire feed) into the list.

        The button, the monitor's per-finding nudge and the «secret_task_share» trigger
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
        self.app.after(0, lambda: self._merge(tasks))

    # -- reading the wire / the game ----------------------------------------
    def _fetch_scan(self) -> list:
        """The live, starred secret tasks off the capture checkpoint — the wire feed.

        `load_fresh_tasks` keeps only tiles the monitor re-saw this scan window and
        recomputes `can_loot` / `pending` against the clock, so a file written a while
        ago cannot smuggle a stale tile in. Each record carries the coordinates and the
        `completed_at` / `expires_at` a row's countdown is drawn from. Only the starred
        ones are kept; the level range narrows the list at render time, not here.

        A missing checkpoint (the monitor never ran) or a malformed one raises and is
        caught upstream as "no new tiles" — the list simply keeps what it has.
        """
        import lastwar_proto as proto
        tasks = proto.load_fresh_tasks(self.app._profiles.tasks_json())
        return [t for t in tasks if t.starred]

    def _fetch_vm(self) -> list:
        """The first-open snapshot: every live starred alliance task straight from the VM.

        `steal_secret_task._vm_all_alliance_tasks` returns every tile on the map with a
        free slot — the ones already raidable AND the ones still counting down — so a row
        can carry its «готово через …» timer and flip to raidable in place. Read once, to
        seed the list before the monitor has anything on the wire; the wire drives it
        after that.
        """
        import lua_client
        import steal_secret_task
        ev = lua_client.get_evaluator(port=self.app._daemon_port())
        tasks = steal_secret_task._vm_all_alliance_tasks(ev)
        return [t for t in tasks if t.starred]

    def _merge(self, tasks) -> None:
        """Add tiles the list does not have yet; keep the ones it does.

        A rescan only ADDS — an existing row keeps its place and its timer, a tile
        robbed by hand this session is skipped, and nothing already on screen is torn
        out from under the operator. Expiry and the ready-transition are the tick's job.
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
                "timer": tk_stringvar(self.app), "frame": None, "ready": False,
            }
        self._render()
        # An empty list after a clean read is "no starred tile right now", not "no
        # game" — the scroll's own hint says so, so the status stays blank rather than
        # crying about a game that may be perfectly up.
        self._update_status()
        self._maybe_start_poll()

    # -- UI -----------------------------------------------------------------
    def _build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.app._tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                     "tab.secret_tasks").pack(side="left")
        self.app._tr(ttk.Button(bar, width=12, command=self.refresh),
                     "tabx.refresh").pack(side="right")
        self.app._tr(ttk.Button(bar, width=12, command=self._clear),
                     "secrettasks.clear").pack(side="right", padx=(0, 6))
        self._status_var = tk_stringvar(self.app)
        ttk.Label(bar, textvariable=self._status_var, foreground="#888").pack(
            side="right", padx=8)

        # The passive-capture monitor block (its findings fill the list below) and the
        # «уровень от / до» range with «Автолут ★» — both moved here off the Main tab.
        # Only the widgets live here (see each builder). The «Операция Призрак» block
        # went on to the «Секретный командный пункт» tab (panel/command_post.py), where
        # the rest of that event lives.
        self._build_monitor_bar()
        self._build_filter_bar()

        self.app._tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                              justify="left"), "secrettasks.hint").pack(
            anchor="w", padx=10, pady=(0, 6))

        self._scroll = ScrollableFrame(self.parent)
        self._scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_monitor_bar(self) -> None:
        """The passive-capture monitor block, moved here off the Main tab.

        Builds the capture-kind combo, its interval, the panel-side log filters and the
        «Автообъезд карты» sweep. Like :meth:`_build_filter_bar`, only the *widgets* live
        here: every var (`_mon_var`, `_interval_var`, the filter vars, the sweep vars) and
        every method (`_toggle_monitor`, `_toggle_sweep`, …) stays on the app, so the
        settings save/load and the profile-switch restart keep reading them where they
        always did. The findings this capture writes to its checkpoint are exactly what
        fills the list below — see :meth:`_fetch_scan`.
        """
        app = self.app
        sec = app._tr(ttk.LabelFrame(self.parent, padding=8), "secret.frame")
        sec.pack(fill="x", padx=10, pady=(0, 4))
        row1 = ttk.Frame(sec)
        row1.pack(fill="x")
        app._mon_combo = ttk.Combobox(
            row1, state="readonly", width=20,
            values=[app._t(o["key"]) for o in app.capture_options])
        app._mon_combo.current(0)
        app._mon_combo.pack(side="left", padx=(0, 8))
        app._tr_hooks.append(app._retranslate_capture_combo)
        app._mon_var = tk.BooleanVar(master=app, value=False)
        app._tr(ttk.Checkbutton(row1, variable=app._mon_var,
                                command=app._toggle_monitor),
                "secret.monitoring").pack(side="left")
        app._tr(ttk.Label(row1), "secret.interval").pack(side="left", padx=(12, 2))
        app._interval_var = tk.StringVar(master=app, value="15")
        numeric_spinbox(row1, from_=1, to=3600, width=5,
                        textvariable=app._interval_var).pack(side="left")
        app._tr(ttk.Label(row1, foreground="#888"), "secret.hint").pack(
            side="left", padx=10)

        row2 = ttk.Frame(sec)
        row2.pack(fill="x", pady=(6, 0))
        app._tr(ttk.Label(row2), "secret.filters").pack(side="left")
        app._star_var = tk.BooleanVar(master=app, value=False)
        app._tr(ttk.Checkbutton(row2, variable=app._star_var),
                "secret.stars_only").pack(side="left", padx=(6, 0))
        app._pending_var = tk.BooleanVar(master=app, value=False)
        app._tr(ttk.Checkbutton(row2, variable=app._pending_var),
                "secret.pending_only").pack(side="left", padx=(6, 0))
        app._can_loot_var = tk.BooleanVar(master=app, value=False)
        app._tr(ttk.Checkbutton(row2, variable=app._can_loot_var),
                "secret.can_loot_only").pack(side="left", padx=(6, 0))
        app._tr(ttk.Label(row2), "secret.filter_level_from").pack(
            side="left", padx=(12, 2))
        app._flt_from_var = tk.StringVar(master=app)
        NumericEntry(row2, textvariable=app._flt_from_var, width=4).pack(side="left")
        app._tr(ttk.Label(row2), "secret.level_to").pack(side="left", padx=(6, 2))
        app._flt_to_var = tk.StringVar(master=app)
        NumericEntry(row2, textvariable=app._flt_to_var, width=4).pack(side="left")

        # «Автообъезд карты»: the passive scan only learns tiles while the map moves, so
        # this walks the camera over a box around a centre. Nested under the monitor
        # frame exactly as on the old Main tab.
        sweep = app._tr(ttk.LabelFrame(sec, padding=6), "sweep.frame")
        sweep.pack(fill="x", pady=(8, 0))
        app._sweep_var = tk.BooleanVar(master=app, value=False)
        app._tr(ttk.Checkbutton(sweep, variable=app._sweep_var,
                                command=app._toggle_sweep),
                "sweep.enabled").pack(side="left")
        app._tr(ttk.Label(sweep), "sweep.centre").pack(side="left", padx=(12, 2))
        app._sweep_cx_var = tk.StringVar(master=app)
        NumericEntry(sweep, textvariable=app._sweep_cx_var, width=6,
                     signed=True).pack(side="left", padx=(0, 2))
        app._sweep_cy_var = tk.StringVar(master=app)
        NumericEntry(sweep, textvariable=app._sweep_cy_var, width=6,
                     signed=True).pack(side="left")
        app._tr(ttk.Button(sweep, command=app._sweep_centre_from_coords),
                "sweep.take_centre").pack(side="left", padx=(4, 0))
        app._sweep_hint = ttk.Label(sweep, foreground="#888", wraplength=380,
                                    justify="left")
        app._sweep_hint.pack(side="left", padx=(10, 0))

    def _build_filter_bar(self) -> None:
        """The level range and auto-loot checkbox — the block that used to sit on Main.

        Only the *widgets* move here; the three vars stay on the app
        (`_autoloot_var`, `_lvl_from_var`, `_lvl_to_var`) because the whole standing-order
        machinery already reads them there — the watcher loop, the settings save/load, the
        rule-hint line. Owning the widgets on this tab and the vars on the app keeps every
        existing consumer working while the boxes move to where their list is shown.

        The same range doubles as the list's display filter (:meth:`_in_range`): a starred
        tile shows only while its level is inside it, so the operator sees exactly the
        tiles auto-loot is about to weigh.
        """
        app = self.app
        app._autoloot_var = tk.BooleanVar(master=app, value=False)
        app._lvl_from_var = tk_stringvar(app)
        app._lvl_to_var = tk_stringvar(app)

        bar = app._tr(ttk.LabelFrame(self.parent, padding=6), "secret.autoloot.frame")
        bar.pack(fill="x", padx=10, pady=(0, 4))
        app._autoloot_chk = app._tr(
            ttk.Checkbutton(bar, variable=app._autoloot_var,
                            command=app._toggle_autoloot), "secret.autoloot")
        app._autoloot_chk.pack(side="left")
        app._tr(ttk.Label(bar), "secret.autoloot.level_from").pack(
            side="left", padx=(12, 2))
        NumericEntry(bar, textvariable=app._lvl_from_var, width=4).pack(side="left")
        app._tr(ttk.Label(bar), "secret.level_to").pack(side="left", padx=(6, 2))
        NumericEntry(bar, textvariable=app._lvl_to_var, width=4).pack(side="left")
        app._autoloot_rule_lbl = ttk.Label(bar, foreground="#888", wraplength=380,
                                           justify="left")
        app._autoloot_rule_lbl.pack(side="left", padx=(10, 0))
        # Re-filter the shown list as the range is typed. The scan stays cached — rows
        # outside the new range just hide, and reappear if it is widened again — so this
        # never touches the game.
        for var in (app._lvl_from_var, app._lvl_to_var):
            var.trace_add("write", lambda *a: self._on_level_filter_change())

    def _render(self) -> None:
        """Rebuild the scroll from the current rows, newest raids on top.

        Sorted the way the auto-loot prizes them: the highest star first, and within a
        level the tile that expires soonest — the one a person would grab before it is
        gone. Called on a merge / collect / clear, NOT every second: the countdown is a
        StringVar the tick loop writes in place.

        Only the rows inside the «уровень от / до» range are drawn — a scan keeps every
        starred tile in memory, so widening the range shows more without a re-read.
        """
        for child in self._scroll.winfo_children():
            child.destroy()
        rows = self._visible_rows()
        if not rows:
            self.app._tr(ttk.Label(self._scroll, foreground="#888"),
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

        The bounds come from `app._autoloot_levels()` — the very range the auto-loot
        watcher robs at — so the list shows exactly the tiles the standing order weighs.
        """
        lo, hi = self.app._autoloot_levels()
        lvl = int(level or 0)
        if lo is not None and lvl < lo:
            return False
        if hi is not None and lvl > hi:
            return False
        return True

    def _visible_rows(self) -> list:
        """The rows the range lets through — what `_render` and the counter show."""
        return [r for r in self._rows.values() if self._in_range(r["level"])]

    def _update_status(self) -> None:
        """Set the header counter to the number of *shown* rows (blank when none)."""
        if self._status_var is None:
            return
        n = len(self._visible_rows())
        self._status_var.set(self.app._t("secrettasks.count", n=n) if n else "")

    def _on_level_filter_change(self) -> None:
        """A «уровень от / до» box was typed: re-draw the list against the new range.

        Cheap and game-free — the scan is cached in `self._rows`, only the visible slice
        changes. Guarded so a range set during settings-load (before the scroll exists)
        is a no-op.
        """
        if getattr(self, "_scroll", None) is None:
            return
        self._render()
        self._update_status()

    # The row is packed left-to-right: icon, stars, coords, countdown, uuid, then the
    # action buttons on the right. Built one row at a time (not a shared grid) so a
    # collect can drop a single row without re-flowing the columns of the rest. A ready
    # tile (its countdown spent) is drawn green with the ✅ glyph and grows its «Собрать»
    # button; a tile still counting down shows only «Поделиться», since collecting one
    # before it matures is a robbery the server would refuse.
    def _row_widget(self, row):
        import coords as coords_fmt
        ready = bool(row.get("ready"))
        frame = ttk.Frame(self._scroll)
        ttk.Label(frame, text=READY_GLYPH if ready else TYPE_GLYPH,
                  font=ui_font(size=15)).pack(side="left", padx=(0, 6))
        stars = ttk.Label(frame, text=self.app._t("secrettasks.stars",
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
        self.app._tr(share, "secrettasks.share").pack(side="right", padx=(4, 0))
        if ready:
            self.app._tr(ttk.Button(frame, width=12,
                                   command=lambda r=row: self._collect(r)),
                         "secrettasks.collect").pack(side="right")
        return frame

    @staticmethod
    def _short_uuid(uuid) -> str:
        """The last 8 digits of a uuid — the full value is 18+ digits and only its
        tail tells two tiles apart on screen."""
        s = str(uuid)
        return "…" + s[-8:] if len(s) > 8 else s

    # -- the countdown ------------------------------------------------------
    def _start_ticking(self) -> None:
        if not self._ticking:
            self._ticking = True
            self._tick()

    def _tick(self) -> None:
        """Every second: rewrite each row's timer, drop the expired, flip the matured.

        A tile that has run out of `expires_at` is off the map and can no longer be
        robbed, so it comes off the list on its own. A tile whose `completed_at` passes
        turns raidable: the tick repaints it green (`_render`) and wakes the poll. Only a
        state change repaints — the second-by-second countdown is a StringVar written in
        place, no widget rebuild.
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
            try:
                self.app.after(1000, self._tick)
            except Exception:                 # noqa: BLE001 — panel gone, stop ticking
                self._ticking = False

    def _refresh_timers(self) -> tuple[list, bool]:
        """Rewrite every row's timer; return (expired keys, did any ready-state change).

        The countdown runs to `completed_at` — the moment the tile becomes raidable —
        not to expiry: «готово через …» while it is ahead, then «готово к сбору» (with
        how long is left to loot) once it is past. `expires_at` still governs removal.
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
                row["timer"].set(self.app._t("secrettasks.until_ready", t="—"))
            elif not ready:
                row["timer"].set(self.app._t("secrettasks.until_ready",
                                             t=_fmt_left(done - now)))
            elif exp is not None:
                row["timer"].set(self.app._t("secrettasks.ready_expires",
                                             t=_fmt_left(exp - now)))
            else:
                row["timer"].set(self.app._t("secrettasks.ready"))
        return expired, changed

    # -- the ready-row poll -------------------------------------------------
    def _maybe_start_poll(self) -> None:
        """Start the slow poll if a row is ready and it is not already running."""
        if self._polling:
            return
        if any(r.get("ready") for r in self._rows.values()):
            self._polling = True
            try:
                self.app.after(POLL_MS, self._poll_tick)
            except Exception:                 # noqa: BLE001 — panel gone
                self._polling = False

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
        try:
            self.app.after(POLL_MS, self._poll_tick)
        except Exception:                     # noqa: BLE001 — panel gone
            self._polling = False

    def _poll_work(self, keys: list) -> None:
        try:
            import lua_client
            import steal_secret_task
            ev = lua_client.get_evaluator(port=self.app._daemon_port())
            live = {str(t.uuid): t for t in steal_secret_task._vm_all_alliance_tasks(ev)}
        except Exception:                     # noqa: BLE001 — a failed read proves nothing
            live = None
        self.app.after(0, lambda: self._poll_apply(keys, live))

    def _poll_apply(self, keys: list, live) -> None:
        """Reconcile the polled ready rows: drop the gone, refresh the rest, then loot.

        A failed read (``live is None``) is not evidence a tile vanished, so it is left
        alone until the next poll. A tile missing from a *good* read is off the map
        (expired) or looted out (its slots filled), and either way it can no longer be
        robbed — so its row drops. A tile still present has its live fields refreshed.
        Auto-loot runs last, over the whole refreshed list, so it robs by the standing
        order's rule rather than per-tile.
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
        if self._autoloot_on():
            self._auto_loot(live)
        if removed:
            self._render()
            self._update_status()

    def _auto_loot(self, live) -> None:
        """Rob the raidable, in-range rows — but only at the range's TOP level, once each.

        The same rule the app's auto-loot watcher obeys, and for the same reason: «от 1
        до 7» robs 7-star tiles and leaves a 6 alone, because the five daily robberies
        are the scarce thing and one spent on a 6 is one a 7 cannot have until the reset
        (#1099). The display range IS the rob rule — a hidden tile is never robbed — and
        each tile is attempted once a session so a poll on a spent budget does not re-fire.
        """
        candidates = [
            (key, row) for key, row in self._rows.items()
            if row.get("ready") and self._in_range(row["level"])
            and key not in self._auto_attempted and key not in self._collected
            and key in live and live[key].can_loot
        ]
        if not candidates:
            return
        _lo, hi = self.app._autoloot_levels()
        top = hi if hi is not None else max(int(r["level"] or 0) for _, r in candidates)
        for key, row in candidates:
            if int(row["level"] or 0) != top:
                continue
            self._auto_attempted.add(key)
            self._collect(row)

    def _autoloot_on(self) -> bool:
        """Whether the «Автолут ★» checkbox (its var lives on the app) is ticked."""
        var = getattr(self.app, "_autoloot_var", None)
        try:
            return bool(var is not None and var.get())
        except Exception:                     # noqa: BLE001
            return False

    # -- actions ------------------------------------------------------------
    def _collect(self, row) -> None:
        """Rob one tile: `hero.dispatch.steal {uuid, targetServer}`, off the Tk thread.

        The steal is budget-gated in the VM (a spent account sends nothing), so a
        confirmed send is the honest success signal here — whether the server pays out
        is its call, the same as every other route into the robbery.
        """
        key = str(row["uuid"])

        def work():
            ok = False
            try:
                import lua_actions
                import lua_client
                ev = lua_client.get_evaluator(port=self.app._daemon_port())
                lines = ev.run(lua_actions.secret_task_steal(int(row["uuid"]),
                                                             int(row["server"])),
                               marker="ACT", settle=1.4)
                ok = any("steal_sent" in ln for ln in (lines or []))
            except Exception:                 # noqa: BLE001
                ok = False
            self.app.after(0, lambda: self._collect_done(key, ok))

        threading.Thread(target=work, daemon=True).start()

    def _collect_done(self, key: str, ok: bool) -> None:
        if ok:
            self._collected.add(key)
            self._rows.pop(key, None)
            self._render()
            self.app._log_put("[secret] " + self.app._t("secrettasks.collect_ok"))
            self._update_status()
        else:
            self.app._log_put("[secret] " + self.app._t("secrettasks.collect_fail"))

    def _open_share_menu(self, button, row) -> None:
        """Pop the «alliance / world» choice under the «Поделиться» button."""
        import tkinter as tk
        menu = tk.Menu(self.app, tearoff=0)
        menu.add_command(label=self.app._t("secrettasks.share_alliance"),
                         command=lambda: self._share(row, SHARE_ALLIANCE))
        menu.add_command(label=self.app._t("secrettasks.share_world"),
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
                import lua_client
                ev = lua_client.get_evaluator(port=self.app._daemon_port())
                room = self._room_id(ev, scope)
                att = chat_share.task_attachment({
                    "x": row["x"], "y": row["y"], "srv": row["server"],
                    "uuid": row["uuid"], "cfgId": row["cfg_id"],
                    "name": "", "abbr": ""})
                ok = bool(room) and chat_share.share_point(ev, room, att)
            except Exception:                 # noqa: BLE001
                ok = False
            self.app.after(0, lambda: self._share_done(scope, ok))

        threading.Thread(target=work, daemon=True).start()

    def _share_done(self, scope: str, ok: bool) -> None:
        where = self.app._t("secrettasks.share_alliance" if scope == SHARE_ALLIANCE
                            else "secrettasks.share_world")
        key = "secrettasks.shared_ok" if ok else "secrettasks.share_fail"
        self.app._log_put("[secret] " + self.app._t(key, where=where))

    def _room_id(self, ev, scope: str) -> str:
        srv, aid = self._self_ids(ev)
        if scope == SHARE_WORLD:
            return "country_%s" % srv if srv else ""
        if scope == SHARE_ALLIANCE:
            return "alliance_%s_%s" % (srv, aid) if srv and aid else ""
        return ""

    def _self_ids(self, ev) -> tuple[str, str]:
        """`(serverId, allianceId)` for the logged-in player — read once, then cached.

        The chat room ids are `country_<server>` and `alliance_<server>_<allianceId>`;
        both come straight off `ChatInterface`. Cached for the session because they do
        not change while the panel is open.
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
