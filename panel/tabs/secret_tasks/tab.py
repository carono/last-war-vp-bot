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
and its own loop (docs/research/panel-tabs-refactor.md §9.1/§9.3). «Автолут ★» is aimed
by ONE number — «минимальный уровень», this level and everything above it (#1256) — and
it picks its targets out of THIS TAB'S LIST (:meth:`SecretTasksTab.rob_candidates`),
never out of a second reading of the sources. What each page SHOWS is that page's own
«уровень от / до», which re-aims no robbery at all.

THERE ARE THREE TABLES, AND THEY ARE PAGES (#1244, #1251). The one described above is a
WORKING list — the starred raids, gathered from two sources, kept across a restart,
spent by «Собрать». Beside it:

* **«Секретки альянса»** (:mod:`~panel.tabs.secret_tasks.alliance`) — a mirror of the
  game's own table answering a different question: WHICH OF MY ALLIANCEMATES IS RUNNING
  WHAT. One row per task an alliance member has out, with the member's name on it, its
  rank, when it finishes and how many times it has been robbed. The READ filters nothing
  out, because every one of them is somebody's task; what the eye is shown is the two
  boxes over it, «UR» and «Звезда» (#1251). It keeps no checkpoint of its own — the game
  is its checkpoint — and is replaced whole by every read.
* **«Операция Призрак»** (:mod:`~panel.tabs.secret_tasks.ghost`) — the weekly co-op
  event's squads: the same table again, with the game's own verdict in the state cell
  instead of a countdown, and no robbery of its own (#1188).

They were stacked under one another in a splitter and are a NOTEBOOK now (#1251): three
tables sharing one height by dragging a sash is three tables nobody can read, and which
of them is being looked at is a question with one answer at a time.

Each has a read of its own and none can be shared: the raid read (:meth:`_snapshot`) is
filtered to the robbable and carries no owner name, the roster (:meth:`_roster`) is the
tab's slowest round trip, and the ghost list (:meth:`_ghost`) is a different event
altogether. All three run when the tab is opened, on «Обновить» and on a profile switch
— and NOT on a mate's share, which changes the raid list rather than the other two.

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

from ...widgets import (NumericEntry, numeric_spinbox, tk_stringvar,
                        font as ui_font)
from ..base import PanelTab, TriggerSpec
from . import grid
from .alliance import AllianceGrid
from .autoloot import AutoLoot
from .capture import Capture
from .ghost import GhostAllianceGrid, GhostGrid, GhostMapGrid
from .shared import SharedMarks
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
    #: The alliance's ghost squads are a push too (#1251): the client keeps the whole
    #: list itself and `push.ghost.recon.alliance.single` is what changes it, so the
    #: page re-reads LOCAL state on each one and asks the server nothing.
    TRIGGERS = (TriggerSpec(name="secret_task_share",
                            event="alliance.share.mission.add",
                            handler="refresh_live"),
                TriggerSpec(name="ghost_recon_alliance",
                            event="push.ghost.recon.alliance.single",
                            handler="refresh_ghost_allies"))

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
    # `autoloot_level_from` / `autoloot_level_to` are kept above to READ a profile
    # written before the range became one minimum (#1256) — `apply_config` migrates
    # them. Nothing writes them any more: the rule is `autoloot_level_min`.
    # `autoloot_skip_own_server` and the four `coord_*` keys are NOT here on purpose:
    # they are new to this tab (#1209) and were never spelled flat on the profile, so
    # there is no old spelling to keep in step with.

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        master = rt.root
        self.loaded = False
        self._busy = False
        # Three reads, three flags (#1244): «Обновить» runs the checkpoint (cheap,
        # `_busy`), the raid list off the VM (`_vm_busy`) and the alliance roster
        # (`_roster_busy`). One flag between them would let whichever started first
        # silence the other two.
        self._vm_busy = False
        self._roster_busy = False
        # …and the ghost-recon page's own read (#1251), which is a fourth source with
        # a fourth failure mode: a weekly event that is shut six days out of seven.
        self._ghost_busy = False
        # The event's config table, read once per session (see `_ghost_work`).
        self._ghost_config = None
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
        # Which uuids the standing order has already fired at is the standing order's own
        # book now (`AutoLoot._seen`, #1256) — there is one watcher and one place a
        # target is chosen, so there is one place to remember what has been tried.
        # Whether the ready-row poll is currently scheduled.
        self._polling = False
        # Cached (server, allianceId) for the chat room ids — read once, live.
        self._ids = None
        # The player's OWN server, cached the same way: what «не грабить на своём
        # сервере» compares a tile against. 0 = not read yet / unreadable.
        self._own_server = 0
        self._status_var = tk_stringvar(master)
        # -- the table ------------------------------------------------------
        self._tree = None
        self._body = None
        self._empty = None
        self._sort = None            # (column id, reversed) once a heading is clicked
        self._collect_btn = self._share_btn = self._goto_btn = None
        # The notebook the three tables are pages of, and its page frames in the order
        # they were added — so a language change can rewrite the tab labels, which are
        # the one piece of text a `ttk.Notebook` will not take a variable for (#1251).
        self._pages = None
        self._page_keys: list = []

        # -- the controls the three orders read ------------------------------
        self.monitor_var = tk.BooleanVar(master=master, value=False)
        self.interval_var = tk.StringVar(master=master, value="15")
        self.filter_from_var = tk.StringVar(master=master)
        self.filter_to_var = tk.StringVar(master=master)
        self.autoloot_var = tk.BooleanVar(master=master, value=False)
        # ONE box, and it is a MINIMUM (#1256): «грабим этот уровень и всё, что выше».
        # It was a range whose top was the level actually robbed, which meant «от 1 до 7»
        # left a raidable 6 alone for ever — two boxes where only one of them decided
        # anything. Deliberately NOT the same setting as the ★ page's display filter
        # below: narrowing what is on screen still re-aims no robbery (#1099).
        self.level_min_var = tk_stringvar(master)
        # There is no «Не грабить на своём сервере» box any more (#1188). The home
        # server is never a target, full stop — see `rob_candidates`. A tile at home is
        # still listed, still shareable and still collectable by hand; what went away is
        # the ability to spend one of the day's five on a neighbour by leaving a box
        # unticked. «Скрывать со своего сервера» (`hide_own_var`) is a different thing
        # and is untouched: that one decides what the TABLE shows.
        # «Показывать исчерпанные»: off by default, because a 3/3 tile cannot pay
        # anybody and a list is read with the eyes (#1227). It is a box rather than a
        # silent rule so that a tile vanishing has somewhere to be looked for — the
        # question «did it fill up, or did the bot lose it?» is otherwise unanswerable.
        self.show_spent_var = tk.BooleanVar(master=master, value=False)
        # «Скрывать со своего сервера»: ON by default (#1251), and a DISPLAY rule only.
        # A neighbour's tile at home is not what this list is read for — the raids worth
        # a march are the ones abroad — so it starts out of the way and the box is what
        # brings it back. Deliberately NOT the same setting as «Не грабить на своём
        # сервере» above, which gates the ROBBERIES and hides nothing: mixing the two is
        # how a rule about spending five raids a day silently became a rule about what
        # is on screen.
        self.hide_own_var = tk.BooleanVar(master=master, value=True)
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
        # How far back the camera sits when this tab moves it (#1265). An id from
        # `lua_actions.ZOOM_LEVELS` — «tile» is the game's own jump height, which is
        # what every jump did before this and so is what it still does by default.
        # Imported here and not at the top for the reason `web_view` gives: tools/lib
        # is only on the path once `panel.runtime.paths` has run.
        import lua_actions
        self._zoom_level = lua_actions.DEFAULT_ZOOM_LEVEL
        self._zoom_label_var = tk_stringvar(master)
        self._zoom_combo = None

        self.alliance = AllianceGrid(self)
        # The third and fourth pages (#1251): the weekly event's squads — mine, and my
        # alliancemates'. Two tables, ONE read: the client keeps both in a single list
        # and `mine` is what tells them apart, so the tab splits the answer rather than
        # asking twice.
        self.ghost = GhostGrid(self)
        self.ghost_allies = GhostAllianceGrid(self)
        # …and the OTHER sniffer (#1251): what a lap of the map found, which is the
        # only one of the three that sees other alliances at all.
        self.ghost_map = GhostMapGrid(self)

        # TWO SNIFFERS, TWO SWITCHES (#1251). The secret-task capture belongs to the ★
        # page and the ghost one to the map page; either may run while the other does
        # not, and each remembers its own interval. It used to be one capture with a
        # dropdown, which meant switching sniffer stopped the one you were watching.
        self.capture = Capture(rt, self, index=0, switch=self.monitor_var,
                               interval=self.interval_var)
        self.ghost_capture = Capture(rt, self, index=1,
                                     switch=self.ghost_map.monitor_var,
                                     interval=self.ghost_map.interval_var)
        self.autoloot = AutoLoot(rt, self)
        self.sweep = Sweep(rt, self)
        # The second table (#1244): what the alliancemates are running, filled by its
        # own read — see `_roster`.

        # Which tiles the alliance has already been shown (#1245). The tables read it,
        # the panel's own «Поделиться» writes it, and so do the two capture children —
        # which is what makes a share pressed in the GAME show up here.
        self.shared = SharedMarks(rt)

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
        # …and the ghost sniffer, whose switch lives on its own page (#1251). Two
        # independent orders: a profile may have either, both or neither ticked.
        if self.ghost_map.monitor_var.get():
            self.ghost_capture.start()
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
        why this is the only game read the tab makes on its own behalf for THAT list.

        The alliance roster below is read here too and nowhere automatic (#1244): it is
        the tab's slowest round trip, and it answers a question nobody is asking while
        the tab is shut.
        """
        if self.loaded:
            return
        self.loaded = True
        self._restore_pending = self._load_persisted()
        if self._restore_pending:
            self._render()
            self._update_status()
        # …and the map page's own list, for the same reason: it is the panel's list, so
        # it survives the panel closing (#1251).
        self.ghost_map.restore()
        self._start_clock_sync()
        self._start_ticking()
        self._prime_own_server()
        self._snapshot()
        self._roster()
        self._ghost()

    def on_profile_switch(self) -> None:
        """Bounce all three orders onto the new account.

        Restarting is deliberate: the capture keeps writing to the OLD profile's
        checkpoint, and auto-loot reads that checkpoint and remembers uuids it robbed
        under the old account — a restart clears both.
        """
        self.capture.stop()
        self.ghost_capture.stop()
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
        # …and what the standing order had already fired at belongs to that account's
        # map, not this one's (#1256).
        self.autoloot._seen.clear()
        self._restore_pending = set()
        # The roster belongs to the old account just as much — a different account
        # is a different alliance, and those are not this one's alliancemates (#1244).
        self.alliance.clear()
        # …and so do the ghost lists: another account has its own event budget, its own
        # squads out and, quite possibly, another alliance running them (#1251).
        self.ghost.clear()
        self.ghost_allies.clear()
        self.ghost_map.clear()
        if self.loaded:
            self.ghost_map.restore()
        # …and so do the shares: «уже поделились» is about an alliance chat this account
        # is not in (#1245). Dropped rather than re-read, because the new profile's own
        # file is read by the next countdown pass anyway.
        self.shared.clear()
        if self.loaded:
            self._restore_pending = self._load_persisted()
            self._render()
            self._update_status()
            self._prime_own_server()
            self._snapshot()
            self._roster()
            self._ghost()
        self._refresh_rule_hints()
        if self.monitor_var.get():
            self.capture.start()
        if self.autoloot_var.get():
            self.autoloot.start()
        if self.sweep_var.get():
            self.sweep.start()

    def on_language_change(self) -> None:
        self._retranslate_headings()
        self._retranslate_pages()
        self._refresh_rule_hints()
        # The rows themselves carry words too («⭐×7», «готово через …»), and a heading
        # is only half the table. Every table, for the same reason.
        self._render()
        for page in (self.alliance, self.ghost, self.ghost_allies,
                     self.ghost_map):
            page.retranslate()
            page.render()

    def _retranslate_pages(self) -> None:
        """Rewrite the notebook's own tab labels (#1251).

        A `ttk.Notebook` takes a string and not a variable, so its labels are the one
        piece of text on this tab that a language change has to go and fetch by hand.
        """
        book = self._pages
        if book is None:
            return
        try:
            for index, key in enumerate(self._page_keys):
                book.tab(index, text=self.t(key))
        except tk.TclError:
            return

    def panic(self) -> None:
        """«Стоп всё»: every standing order down, and the boxes say so."""
        self._was = {}
        for name, var, order in (("monitor", self.monitor_var, self.capture),
                                 ("ghost", self.ghost_map.monitor_var, self.ghost_capture),
                                 ("autoloot", self.autoloot_var, self.autoloot),
                                 ("sweep", self.sweep_var, self.sweep)):
            self._was[name] = bool(var.get())
            var.set(False)
            order.stop()

    def resume(self) -> None:
        """«Включить обратно»: put back exactly the standing orders that were standing.

        Ticking the box is what starts the order — the same path a finger takes — so
        nothing here has to know how any of the four are run.
        """
        was, self._was = getattr(self, "_was", None), None
        if not was:
            return
        for name, var in (("monitor", self.monitor_var),
                          ("ghost", self.ghost_map.monitor_var),
                          ("autoloot", self.autoloot_var),
                          ("sweep", self.sweep_var)):
            if was.get(name):
                var.set(True)

    def shutdown(self) -> None:
        self.capture.stop()
        self.ghost_capture.stop()
        self.autoloot.stop()
        self.sweep.stop()
        for name in ("secret_tick", "secret_poll", "secret_nudge",
                     "secret_clock", "autoloot_push_restart"):
            self.rt.tick.disarm(name)
        self._ticking = self._polling = False

    # -- persistence ----------------------------------------------------------
    def config(self) -> dict:
        return {
            # The ★ page's own sniffer. `monitor_kind` is gone with the dropdown
            # (#1251): each sniffer has a switch of its own now, and «which one is
            # selected» is not a question any more.
            "monitor_interval": self.interval_var.get(),
            "secret_monitor": bool(self.monitor_var.get()),
            # …and every page's own filters, each under its own key, so switching one
            # on cannot reach into another's (#1251).
            "grids": {page.CONFIG_KEY: page.config()
                      for page in self._grid_pages()},
            "show_spent": bool(self.show_spent_var.get()),
            # The three display rules the pages carry (#1251) — what is SHOWN, never
            # what is robbed. The robbery's own rule is `autoloot_skip_own_server`
            # below, and the two are kept apart on purpose.
            "hide_own_server": bool(self.hide_own_var.get()),
            "filter_level_from": self.filter_from_var.get(),
            "filter_level_to": self.filter_to_var.get(),
            "autoloot": bool(self.autoloot_var.get()),
            # One number now (#1256) — the lowest level worth one of the day's five.
            "autoloot_level_min": self.level_min_var.get(),
            "map_sweep": bool(self.sweep_var.get()),
            "sweep_centre_x": self.sweep_cx_var.get(),
            "sweep_centre_y": self.sweep_cy_var.get(),
            "coord_x": self.coord_x_var.get(),
            "coord_y": self.coord_y_var.get(),
            "coord_server": self.coord_srv_var.get(),
            "coord_history": list(self._jump_hist),
            "coord_zoom": self._zoom_level,
        }

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self.interval_var.set(str(raw.get("monitor_interval", "15")))
        blocks = raw.get("grids") if isinstance(raw.get("grids"), dict) else {}
        for page in self._grid_pages():
            page.apply_config(blocks.get(page.CONFIG_KEY, {}))
        # A profile saved while the two sniffers were ONE box with a dropdown carries
        # `secret_monitor` and `monitor_kind` (#1251). Which capture that switch meant
        # is what `monitor_kind` said, so it is honoured once, here, and then each
        # sniffer keeps its own box: index 1 was the ghost one.
        was_on = bool(raw.get("secret_monitor", False))
        was_ghost = raw.get("monitor_kind") == 1
        if "grids" not in raw and was_on and was_ghost:
            self.ghost_map.monitor_var.set(True)
            self.ghost_map.interval_var.set(str(raw.get("monitor_interval", "15")))
            self.monitor_var.set(False)
        else:
            self.monitor_var.set(was_on and not was_ghost if "grids" not in raw
                                 else was_on)
        self.show_spent_var.set(bool(raw.get("show_spent", False)))
        # ON for a profile that has never been asked (#1251): a raid at home is not
        # what this list is read for, and the box is how somebody says otherwise.
        self.hide_own_var.set(bool(raw.get("hide_own_server", True)))
        # A profile written before the pages kept their own settings spelled these two
        # flat; the page's own block wins where there is one (#1251).
        if "grids" not in raw:
            self.alliance.ur_var.set(bool(raw.get("alliance_ur_only", False)))
            self.alliance.star_var.set(bool(raw.get("alliance_star_only", False)))
        self.filter_from_var.set(raw.get("filter_level_from", ""))
        self.filter_to_var.set(raw.get("filter_level_to", ""))
        # The range became one MINIMUM (#1256), and the migration has to preserve what
        # the profile was actually robbing rather than what it looked like it was: under
        # the old rule the level robbed was the range's TOP («от 1 до 7» robbed 7s and
        # left 6s alone), so the old «до» is the new minimum. Only where it was blank
        # does the old «от» stand in — that profile really was robbing from there up.
        # Older still (before the display filter and the robbery rule were split) there
        # is only the display pair, and it WAS aiming the robberies too; seeding from it
        # is what keeps such a profile robbing the same levels instead of silently
        # widening to «any level», which is how a robbery gets spent on a 6 (#1099).
        self.level_min_var.set(str(
            raw.get("autoloot_level_min")
            or raw.get("autoloot_level_to")
            or raw.get("autoloot_level_from")
            or raw.get("filter_level_to")
            or raw.get("filter_level_from")
            or ""))
        self.autoloot_var.set(bool(raw.get("autoloot", False)))
        # `autoloot_skip_own_server` is READ from no profile and written to none (#1188).
        # A profile that still carries it keeps it as dead weight rather than being
        # rewritten behind the person's back, and it decides nothing: the home server is
        # excluded whatever it says.
        self.sweep_var.set(bool(raw.get("map_sweep", False)))
        self.sweep_cx_var.set(raw.get("sweep_centre_x", ""))
        self.sweep_cy_var.set(raw.get("sweep_centre_y", ""))
        self.coord_x_var.set(str(raw.get("coord_x", "")))
        self.coord_y_var.set(str(raw.get("coord_y", "")))
        self.coord_srv_var.set(str(raw.get("coord_server", "")))
        self._set_jump_history(raw.get("coord_history"))
        self._zoom_level = str(raw.get("coord_zoom") or self._zoom_level)
        self._sync_zoom_combo()
        self._refresh_rule_hints()

    def _grid_pages(self) -> tuple:
        """The pages that keep settings of their own — every table but the ★ one.

        The ★ page's boxes are the tab's own variables (they predate the split and the
        profile spells them flat), so it is not in here; everything it saves is above.
        """
        return (self.alliance, self.ghost, self.ghost_allies, self.ghost_map)

    def persist_vars(self) -> list:
        pages = [v for page in self._grid_pages() for v in page.persist_vars()]
        return pages + [self.monitor_var, self.interval_var, self.show_spent_var,
                self.hide_own_var,
                self.filter_from_var, self.filter_to_var,
                self.autoloot_var, self.level_min_var,
                self.sweep_var, self.sweep_cx_var, self.sweep_cy_var,
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
        # HOW FAR BACK THE CAMERA SITS, on the bar that moves it (#1265). It governs
        # every jump this tab makes and the lap beside it, and the three choices are
        # named by what they are FOR: one tile to read, the height secret tasks still
        # arrive at, and the height that collects bases and nothing else.
        self.tr(ttk.Label(box), "coord.zoom").pack(side="left", padx=(12, 2))
        self._zoom_combo = ttk.Combobox(box, textvariable=self._zoom_label_var,
                                        state="readonly", width=16,
                                        values=self._zoom_choices())
        self._zoom_combo.pack(side="left")
        self._zoom_combo.bind("<<ComboboxSelected>>", self._on_zoom_choice)
        self.tr(ttk.Button(box, command=self._sweep_once),
                "coord.sweep_now").pack(side="left", padx=(8, 0), ipady=2)
        self._jump_hist_combo = ttk.Combobox(box, textvariable=self._jump_hist_var,
                                             state="readonly", width=18, values=[])
        self._jump_hist_combo.pack(side="right", padx=(4, 0))
        self._jump_hist_combo.bind("<<ComboboxSelected>>", self._on_jump_history)
        self.tr(ttk.Label(box), "coord.history").pack(side="right", padx=(8, 2))
        self._set_jump_history(self._jump_hist)
        self._sync_zoom_combo()

    def _build_monitor_bar(self) -> None:
        """The ★ sniffer's switch where the eye goes for it, and the map sweep.

        THE SWITCHES BELONG TO THEIR PAGES (#1251). One «Мониторинг» box with a dropdown
        beside it meant choosing which sniffer to watch STOPPED the other one, and one
        «уровень от / до» narrowed lists it had nothing to do with — ghost squads are
        levels 3-5 where secret tasks run 1-7. Each page carries its own switch, its own
        interval and its own range.

        AND THE ★ ONE IS DRAWN HERE AS WELL (#1264). Moving it off this frame left the
        frame standing with its old title and only the sweep inside, so whoever had been
        pressing «Мониторинг» here for months found nothing and reported the switch
        gone — it was four hundred pixels down, inside a page of a five-page notebook.
        **This is the SAME `monitor_var` and the same `capture.toggle`, not a second
        box**: Tk drives every checkbutton bound to one variable, so the two are one
        switch drawn twice and cannot disagree. Do not «tidy» either away — see
        docs/panel-tabs.md, «One state, several places».

        The sweep stays shared on purpose: it is one camera, it feeds both captures at
        once, and two boxes driving one camera would fight each other.
        """
        sec = self.tr(ttk.LabelFrame(self.parent, padding=8), "secret.frame")
        sec.pack(fill="x", padx=10, pady=(0, 4))

        mon = ttk.Frame(sec)
        mon.pack(fill="x", pady=(0, 6))
        self.tr(ttk.Checkbutton(mon, variable=self.monitor_var,
                                command=self.capture.toggle),
                "secret.monitoring.stars").pack(side="left")
        self.tr(ttk.Label(mon), "secret.interval").pack(side="left", padx=(12, 2))
        numeric_spinbox(mon, from_=1, to=3600, width=5,
                        textvariable=self.interval_var).pack(side="left")
        self.tr(ttk.Label(mon, foreground="#888", wraplength=520,
                          justify="left"), "secret.hint").pack(side="left", padx=10)

        # «Автообъезд карты»: the passive scan only learns tiles while the map moves, so
        # this walks the camera over a box around a centre.
        sweep = self.tr(ttk.LabelFrame(sec, padding=6), "sweep.frame")
        sweep.pack(fill="x")
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
        """«Автолут ★», its one level box and the own-server prohibition — the rule the
        robberies obey.

        ONE BOX, AND IT IS A MINIMUM (#1256). The range it replaces read as two bounds
        and behaved as one: only its top was ever robbed, so a raidable level-6 star sat
        there untouched under «от 1 до 7». «Минимальный уровень 6» robs the 6 and every
        7 above it, best first.

        Separate from the ★ page's own «Фильтры: уровень от / до» on purpose (#1099):
        that pair is a pair of eyes and this one is a budget. «Не грабить на своём
        сервере» is in THIS frame for the same reason — it gates the robberies and hides
        nothing.
        """
        frame = self.tr(ttk.LabelFrame(self.parent, padding=6), "secret.autoloot.frame")
        frame.pack(fill="x", padx=10, pady=(0, 4))
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        self.tr(ttk.Checkbutton(bar, variable=self.autoloot_var,
                                command=self._on_autoloot_toggle),
                "secret.autoloot").pack(side="left")
        self.tr(ttk.Label(bar), "secret.autoloot.level_min").pack(
            side="left", padx=(12, 2))
        NumericEntry(bar, textvariable=self.level_min_var, width=4).pack(side="left")
        self._rule_lbl = ttk.Label(frame, foreground="#888", wraplength=760,
                                   justify="left")
        self._rule_lbl.pack(fill="x", anchor="w", pady=(4, 0))
        # Typing the minimum keeps the rule line true and bounces the event-driven
        # listener onto it. It re-draws nothing: the rule aims the ROBBERIES, and what
        # is on the table is the page's own filters' business (#1099, #1251).
        self.level_min_var.trace_add("write", lambda *_a: self._on_level_filter_change())
        # The DISPLAY range redraws the table on the spot too (#1244). It governs what
        # the list shows as well as what the log prints, so a box typed into and nothing
        # happening on the table is the very confusion this fix is about.
        for var in (self.filter_from_var, self.filter_to_var):
            var.trace_add("write", lambda *_a: self._on_display_filter_change())
        for var in (self.sweep_cx_var, self.sweep_cy_var):
            var.trace_add("write", lambda *_a: self._refresh_rule_hints())
        # The capture's interval is a child-process argument, so a change only takes
        # effect on the next launch: bounce a running one rather than waiting for a
        # manual toggle.
        self.interval_var.trace_add("write", lambda *_a: self._on_interval_change())

    # -- the table -------------------------------------------------------------
    def _build_table(self) -> None:
        """The three tables, as the three pages of a notebook (#1251).

        A `ttk.Treeview` rather than a stack of frames (#1209). The rows used to be packed
        by hand, each label carrying its own width, so nothing lined up under anything and
        a long countdown pushed its neighbours off the row. Here the widths belong to the
        columns, the header stays put while the list scrolls, and a heading sorts.

        What a Treeview cannot hold is a widget, so the row actions live under it and act
        on the selection — plus the right-click menu, and the coordinate link.

        The tables used to share the height through a `PanedWindow`. Two of them barely
        did; three cannot — a table with a fifth of a window is a table nobody reads, and
        the answer to «which of these am I looking at» is one page at a time. The strip
        of actions below stays ONE strip and follows the page on top, so «Собрать» is
        never aimed at a row on a table that is not on screen.
        """
        # The action strip is packed FIRST, against the bottom: pack clips whatever was
        # packed last when the window is short, and the buttons are the one thing on the
        # tab that must never be the part that falls off the edge.
        acts = ttk.Frame(self.parent)
        acts.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        book = ttk.Notebook(self.parent)
        book.pack(fill="both", expand=True, padx=10, pady=(0, 0))
        self._pages = book
        self._page_keys = []

        stars = ttk.Frame(book, padding=6)
        self._add_page(stars, "secrettasks.page.stars")
        self._empty = self.tr(ttk.Label(stars, foreground="#888"), "secrettasks.empty")
        self._build_star_filters(stars)
        self._body = ttk.Frame(stars)
        self._body.pack(fill="both", expand=True)

        tree = grid.make_tree(self._body)
        tree.bind("<Button-1>", self._on_click)
        tree.bind("<Double-Button-1>", self._on_double_click)
        tree.bind("<Button-3>", self._on_right_click)
        tree.bind("<Motion>", self._on_motion)
        tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_actions())
        self._tree = tree
        self._retranslate_headings()
        self._add_page(self.alliance.build(book), "secrettasks.page.alliance")
        self._add_page(self.ghost.build(book), "secrettasks.page.ghost")
        self._add_page(self.ghost_allies.build(book), "secrettasks.page.ghost_allies")
        self._add_page(self.ghost_map.build(book), "secrettasks.page.ghost_map")
        # Switching pages re-aims the strip below at whatever the new page has selected.
        book.bind("<<NotebookTabChanged>>", lambda _e: self.sync_actions())

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

    def _add_page(self, frame, key: str) -> None:
        """Add one page to the notebook and remember the key its label is said from."""
        self._pages.add(frame, text=self.t(key))
        self._page_keys.append(key)

    def _build_star_filters(self, parent) -> None:
        """The ★ page's own box: «Скрывать со своего сервера», ON by default (#1251).

        A DISPLAY rule and nothing else. «Не грабить на своём сервере» in the auto-loot
        frame above gates the ROBBERIES and hides nothing; this hides rows and robs
        nothing. Two settings, two places, deliberately — a tile at home stays
        shareable, jumpable and collectable by hand whichever way this box is set.
        """
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 4))
        self.tr(ttk.Label(bar), "secrettasks.filters").pack(side="left", padx=(0, 8))
        self.tr(ttk.Label(bar), "secret.filter_level_from").pack(side="left", padx=(0, 2))
        NumericEntry(bar, textvariable=self.filter_from_var, width=4).pack(side="left")
        self.tr(ttk.Label(bar), "secret.level_to").pack(side="left", padx=(6, 2))
        NumericEntry(bar, textvariable=self.filter_to_var, width=4).pack(side="left")
        self.tr(ttk.Checkbutton(bar, variable=self.hide_own_var,
                                command=self._on_hide_own_change),
                "secrettasks.filter.hide_own").pack(side="left", padx=(16, 0))

        # …and the SECRET-TASK sniffer's own switch, on the page it feeds (#1251) — the
        # SAME variable as the copy in «Секретные задания» above (#1264), so whichever
        # one is pressed, both move. Same label too: two boxes reading the same words
        # and moving together say «one switch» where two spellings would say «two».
        mon = ttk.Frame(parent)
        mon.pack(fill="x", pady=(0, 4))
        self.tr(ttk.Checkbutton(mon, variable=self.monitor_var,
                                command=self.capture.toggle),
                "secret.monitoring.stars").pack(side="left")
        self.tr(ttk.Label(mon), "secret.interval").pack(side="left", padx=(12, 2))
        numeric_spinbox(mon, from_=1, to=3600, width=5,
                        textvariable=self.interval_var).pack(side="left")

    def _on_hide_own_change(self) -> None:
        """The box was flipped: redraw the ★ list, read nothing, rob nothing."""
        self.rt.settings.changed()
        self._render()
        self._update_status()

    def _current_page(self):
        """The grid on the page now open, or None while the ★ page is (it is the tab).

        The strip of buttons below the notebook is one strip for three pages, so it has
        to know which table it is aimed at — otherwise «Собрать» acts on a row the
        person cannot see.
        """
        book = self._pages
        if book is None:
            return None
        try:
            index = book.index(book.select())
        except (tk.TclError, ValueError):
            return None
        return {1: self.alliance, 2: self.ghost, 3: self.ghost_allies,
                4: self.ghost_map}.get(index)

    def sync_actions(self) -> None:
        """Public name for the strip's re-aim — the pages call it when they redraw."""
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

    def _rank(self, row) -> str:
        """One row's level, wearing a star only if the GAME draws one (#1244).

        Both front-ends say it the same way — the window's level cell and the phone's
        «Уровень» fact — so a tile cannot look like a star on one and a plain task on
        the other.
        """
        level = int(row.get("level") or 0)
        key = "secrettasks.stars" if row.get("starred") else "secrettasks.level"
        return self.t(key, n=level)

    def _row_values(self, row) -> tuple:
        """One row as the cells of the table, in the order COLUMNS declares.

        The coordinate cell is the canonical `X:.. Y:..` token — the same one the log
        prints and `coords.parse` reads back — with the server standing in its own column
        beside it rather than glued to the front of it.

        The owner cell is empty on a row that does not know one (#1244): the wire feed
        and the raid read carry no name, so the table above leaves the column blank
        rather than filling it with a guess.

        THE STAR IS DRAWN ONLY WHERE THE GAME DRAWS ONE (#1244, live report). The level
        cell used to read «⭐×7» on every row, because the star glyph was part of the
        LEVEL format — honest in the list above, where every row is a starred raid by
        construction, and a plain lie in the roster below, where 167 of 200 tasks carry
        no star in the game at all. A row the game does not star now says its level and
        nothing more.

        And the level is the level the GAME gives, not the one the cfgId's digits spell:
        `60009903` reads as «99» by arithmetic and is a level-7 task of another type,
        which is what «есть "особое задание", это не особое, это такое же 7 уровня»
        was about. The roster's records carry the config's own answer
        (`dispatch_tasks.alliance_roster`), so there is nothing left here to name.

        A tile the alliance has already been shown carries `SHARED_GLYPH` in front of
        its coordinate (#1245) — the words are in the state cell, this is what makes the
        answer readable down a column. The token itself is left untouched behind it, so
        `coords.parse` still finds it and the cell still jumps the camera.
        """
        import coords as coords_fmt
        ready = bool(row.get("ready"))
        can_take = self._collectable(row)
        rank = self._rank(row)
        where = coords_fmt.fmt(row["x"], row["y"])
        if row.get("shared"):
            where = "%s %s" % (grid.SHARED_GLYPH, where)
        return (row.get("owner_name") or "",
                where,
                self.t("secrettasks.server", srv=row["server"]),
                "%s %s" % (READY_GLYPH if ready else TYPE_GLYPH, rank),
                row["timer"].get(),
                self.t("secrettasks.slots", n=int(row["loot_count"] or 0)),
                self.t("secrettasks.collect") if can_take else "")

    def _show_empty(self, empty: bool) -> None:
        """Say «нет звёздных секреток» above the table, or take the line away.

        And when the table is empty because the home-server rule EMPTIED it, say that
        instead (#1251). One live account had every star it could see on its own
        server: the list went blank on open, the count said «скрыто: 34» in grey off to
        the side, and the whole thing read as a tab that had failed to read anything.
        The sentence in the middle of the empty table is the one that gets read.
        """
        if self._empty is None:
            return
        hidden = self._hidden_at_home() if empty else 0
        try:
            if empty:
                # `tr` re-registers the label under the key it is showing NOW, so a
                # language switch redraws whichever of the two sentences is up.
                self.tr(self._empty,
                        "secrettasks.empty_hidden" if hidden else "secrettasks.empty",
                        n=hidden)
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
        """The row the OPEN page's selection is on, or None.

        One strip of buttons serves three pages (#1251), so what it acts on is whatever
        is selected on the page in front of the person — not whatever was left selected
        on a table two pages back.
        """
        page = self._current_page()
        if page is not None:
            return page.selected()
        tree = self._tree
        if tree is None:
            return None
        picked = tree.selection()
        return self._rows.get(picked[0]) if picked else None

    def _sync_actions(self) -> None:
        """Enable each button of the strip only where it means something.

        «Собрать» on a tile still counting down is a robbery the server would refuse, so
        the button says so by being unavailable rather than by failing afterwards. On a
        page that does not rob at all — the ghost list, whose press lives in «Командный
        пункт» (#1188) — it stays out, and so does «Поделиться»: a ghost squad is not
        what a secret-task share posts.
        """
        page = self._current_page()
        row = self._selected()
        can_take = bool(row) and (page.collectable(row) if page is not None
                                  else self._collectable(row))
        can_share = bool(row) and page not in (self.ghost, self.ghost_allies,
                                              self.ghost_map)
        for widget, live in ((self._goto_btn, row is not None),
                             (self._share_btn, can_share),
                             (self._collect_btn, can_take)):
            if widget is None:
                continue
            try:
                widget.state(("!disabled",) if live else ("disabled",))
            except tk.TclError:
                pass

    def _collect_selected(self) -> None:
        """«Собрать» on the strip — against the page's own rule about robbing (#1251)."""
        page = self._current_page()
        row = self._selected()
        if row is None:
            return
        if page.collectable(row) if page is not None else self._collectable(row):
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

    def _on_interval_change(self) -> None:
        """The ★ page's own interval was typed: bounce ITS capture, not the other one."""
        if not self.rt.settings.loading and self.capture.running:
            self.capture.restart()

    def _on_ghost_interval_change(self) -> None:
        """…and the same for the ghost sniffer's own interval (#1251)."""
        if not self.rt.settings.loading and self.ghost_capture.running:
            self.ghost_capture.restart()

    def _on_show_spent(self) -> None:
        """«Показывать исчерпанные» was flipped: redraw the list, nothing else.

        A pure display rule — it changes no robbery and touches no game. The rows are
        all still in memory either way, so this costs a repaint.
        """
        self.rt.settings.changed()
        self._render()
        self._update_status()

    def _on_autoloot_toggle(self) -> None:
        """«Автолут ★» was ticked or cleared: start/stop it.

        Nothing is greyed alongside it any more: the one control that used to hang off
        this box was «Не грабить на своём сервере», and the prohibition it carried is
        unconditional now (#1188).
        """
        self.autoloot.toggle()

    # -- jumping ---------------------------------------------------------------
    # -- how far back the camera sits (#1265) ----------------------------------
    def _zoom_choices(self) -> list:
        """The zoom levels as words, in the order the camera pulls back."""
        import lua_actions
        return [self.t(f"coord.zoom.{name}") for name in lua_actions.ZOOM_LEVELS]

    def _zoom_names(self) -> list:
        import lua_actions
        return list(lua_actions.ZOOM_LEVELS)

    def _sync_zoom_combo(self) -> None:
        """Put the current level's word in the box — after a load, or a language change."""
        names = self._zoom_names()
        if self._zoom_level not in names:
            self._zoom_level = names[0]
        self._zoom_label_var.set(self.t(f"coord.zoom.{self._zoom_level}"))
        if self._zoom_combo is not None:
            try:
                self._zoom_combo.configure(values=self._zoom_choices())
            except tk.TclError:                     # the page is going away
                pass

    def _on_zoom_choice(self, _event=None) -> None:
        """A level was picked: remember it, and say what it means in one line."""
        import lua_actions
        chosen = self._zoom_label_var.get()
        for name in self._zoom_names():
            if self.t(f"coord.zoom.{name}") == chosen:
                self._zoom_level = name
                break
        height, step = lua_actions.zoom_level(self._zoom_level)
        self.rt.settings.changed()
        self.say("coord", "log.coord.zoom", level=self.t(f"coord.zoom.{self._zoom_level}"),
                 height=height, step=step)

    def _sweep_once(self) -> None:
        """«Обойти карту»: one lap of the whole server at the chosen height.

        The ability is `actions/scan_map.md` and the panel only plays it — the waypoints,
        the timer that walks them and the height they are walked at all live in the
        scenario and its primitive (`CLAUDE.md`). What the tab decides is WHEN, and with
        which of the three levels the bar is set to.

        The lap only produces traffic; something has to be listening to it, which is the
        ★ monitor. Saying so is the difference between «nothing was found» and «nothing
        was written down».
        """
        import lua_actions
        height, step = lua_actions.zoom_level(self._zoom_level)
        if not (self.capture.running or self.ghost_capture.running):
            self.say("coord", "log.coord.sweep_unwatched")
        seconds = lua_actions.fast_sweep_seconds(step) + 2
        self.say("coord", "log.coord.sweeping",
                 level=self.t(f"coord.zoom.{self._zoom_level}"), secs=int(seconds))
        self.rt.play_async("scan_map", {"zoom": height, "step": step}, tag="coord")

    def _jump(self, x: int, y: int, server) -> None:
        """The one way this tab walks the camera anywhere. Remembers where it went.

        ``server`` may be None — the runtime then jumps on whatever server the client is
        currently looking at, which is what an empty «Сервер» box means.

        The height is the bar's own choice and applies to EVERY jump this tab makes,
        including a coordinate clicked in the table: two ways to reach the same tile that
        arrived at different zooms would be the sort of difference nobody can explain
        afterwards. «Тайл» is the default and is what the jump always did (#1265).
        """
        import lua_actions
        height, _step = lua_actions.zoom_level(self._zoom_level)
        if self.rt.game.jump(x, y, server, zoom=height):
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
        """«Минимальный уровень» was typed: keep the rule line true and re-aim the
        listener. Nothing on the table moves — the rule spends robberies, it does not
        hide rows (#1099, #1256)."""
        self.rt.settings.changed()
        self._refresh_rule_hints()
        self.autoloot.range_changed()

    def _on_display_filter_change(self) -> None:
        """A «Фильтры: уровень от / до» box was typed: redraw the list under the new
        bounds and remember them. No game round trip — every row is already in memory,
        and the log picks the same pair up on its next line."""
        self.rt.settings.changed()
        if self._tree is None:
            return
        self._render()
        self._update_status()

    # -- reading the wire / the game ------------------------------------------
    def _snapshot(self) -> None:
        """The one-time first-open seed of the raid list: read the VM once and merge it.

        The table below has a read of its own (:meth:`_roster`) — this one is filtered
        to the robbable stars and carries no owner name, so it cannot answer for it.
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
        self.after(lambda: self._vm_landed(tasks, pending))

    def _vm_landed(self, tasks, pending) -> None:
        """The VM read, back on the Tk thread — the working list's own seed."""
        self._vm_busy = False
        self._merge(tasks, pending)

    # -- the alliance roster (#1244) -------------------------------------------
    def _roster(self) -> None:
        """Read what the alliance is running, for the table below. Off the Tk thread.

        A read of its own rather than a share of the raid read above: what that one
        answers is «which tiles may I rob», and it is filtered to say so — the dispatch
        finished, a slot free, and only the stars kept. The question down here is «who of
        my alliancemates is running what», so nothing may be filtered out of it, and it
        needs the one thing the raid read does not carry at all: the owner's name.
        """
        if self._roster_busy:
            return
        self._roster_busy = True
        threading.Thread(target=self._roster_work, daemon=True).start()

    def _roster_work(self) -> None:
        try:
            import dispatch_tasks
            rows, ok = dispatch_tasks.alliance_roster(self.rt.game.evaluator()), True
        except Exception:                     # noqa: BLE001 — no daemon, no game, no list
            rows, ok = [], False
        self.after(lambda: self._roster_landed(rows, ok))

    def _roster_landed(self, rows, ok: bool) -> None:
        """Hand the read to the table below — but only a read that WORKED.

        A failed one says nothing about the alliance's tasks. Emptying the table on it
        would turn «the daemon was busy for a second» into «your alliance has nothing
        out», which is the same lie `_merge` refuses to tell about a restored row.
        """
        self._roster_busy = False
        if ok:
            self.alliance.apply(rows)

    # -- the ghost-recon lists (#1251) ------------------------------------------
    def _ghost(self) -> None:
        """Read the weekly event's squads — for BOTH ghost pages. Off the Tk thread.

        One round trip for two tables: the client keeps my own squads and my
        alliancemates' in a single list, and the dump carries the event's own state —
        open day, robberies left — on its first line, so the pages' status and both
        their row sets come from the same answer (`ghost_recon_steal.roster`). Six days
        a week that answer is «closed» and two empty lists, which the pages say rather
        than looking broken.
        """
        if self._ghost_busy:
            return
        self._ghost_busy = True
        threading.Thread(target=self._ghost_work, daemon=True).start()

    def _ghost_work(self) -> None:
        try:
            import ghost_recon_steal as ghost_tool
            evaluator = self.rt.game.evaluator()
            # Neither read asks the SERVER anything (#1251): the client already holds
            # both lists and the pushes keep them current, so `refresh=False`. The
            # window's own «задания альянса» re-requests on open; the panel does not
            # need to, and a tab that re-requested on every push would be chattier than
            # the game itself.
            status, mine = ghost_tool.roster(evaluator, refresh=False)
            # …with one exception, and only when the local list is EMPTY: a client
            # whose event window has not been opened this session was never sent the
            # alliance list at all, and «never asked» would show as «nothing out».
            allies = ghost_tool.alliance_roster(evaluator, seed_if_empty=True)
            # THE OTHER SNIFFER (#1251): what a lap of the map found. A file the
            # capture child writes, plus the event's config table so a tile says the
            # level and the star the game gives rather than its cfgId's digits. The
            # config is read once and kept — it cannot change under a running client.
            if self._ghost_config is None:
                self._ghost_config = ghost_tool.templates(evaluator)
            found = ghost_tool.map_roster(self.rt.profiles.ghost_json(),
                                          self._ghost_config)
            ok = True
        except Exception:                     # noqa: BLE001 — no daemon, no game, no event
            status, mine, allies, found, ok = {}, [], [], [], False
        self.after(lambda: self._ghost_landed(status, mine, allies, found, ok))

    def _ghost_landed(self, status, mine, allies, found, ok: bool) -> None:
        """Hand each ghost page its own list — a read that WORKED, at least.

        A failed one says nothing about the event, exactly as a failed roster read says
        nothing about the alliance: emptying the tables on it would turn «the daemon was
        busy» into «nobody has a squad out».

        The two lists come from two different managers and answer two different
        questions — «where are my own three» and «what has the alliance sent out» —
        which is why they are two pages. What lands here is already split; the tab only
        keeps my own rows out of the alliance page, since the client puts a squad of
        mine in both when I am the one who started it.
        """
        self._ghost_busy = False
        if not ok:
            return
        self.ghost.landed(status, [r for r in mine if r.get("mine")])
        self.ghost_allies.landed(status, [r for r in allies if not r.get("mine")])
        self.ghost_map.landed(status, found)

    def refresh_ghost_map(self) -> None:
        """Re-merge the tile capture's checkpoint. A file read, no game, no server.

        The capture rewrites it every tick while the map moves, so this is what turns a
        lap of the map into rows — and it is cheap enough to run whenever the tab is
        refreshed (#1251).
        """
        if not self.loaded:
            return

        def work() -> None:
            try:
                import ghost_recon_steal as ghost_tool
                rows = ghost_tool.map_roster(self.rt.profiles.ghost_json(),
                                             self._ghost_config or {})
            except Exception:                 # noqa: BLE001 — no file yet, or a broken one
                return
            self.after(lambda: self.ghost_map.landed(self.ghost_map.status, rows))

        threading.Thread(target=work, daemon=True).start()

    def refresh_ghost_allies(self) -> None:
        """A push moved the alliance's ghost list: re-read it, locally, and redraw.

        This is what «читай из пушей» means in practice (#1251) — the push itself
        carries one squad, but the client has already applied it to the list the window
        draws, so the honest thing to re-read is that list. No server round trip, and
        nothing at all while the tab has never been opened.
        """
        if not self.loaded:
            return
        threading.Thread(target=self._ghost_allies_work, daemon=True).start()

    def _ghost_allies_work(self) -> None:
        try:
            import ghost_recon_steal as ghost_tool
            rows = ghost_tool.alliance_roster(self.rt.game.evaluator())
            ok = True
        except Exception:                     # noqa: BLE001 — no daemon, no game
            rows, ok = [], False
        if ok:
            self.after(lambda: self.ghost_allies.landed(self.ghost_allies.status,
                                                        [r for r in rows
                                                         if not r.get("mine")]))

    # -- who I am, read once ------------------------------------------------------
    def _prime_own_server(self) -> None:
        """Learn the account's own server once, off the Tk thread (#1251).

        «Скрывать со своего сервера» judges every row against it on every redraw, and
        the reader behind it goes to the game while the answer is unknown — which on
        the Tk thread would be a round trip per repaint. So it is asked for here, once,
        beside the reads the tab already makes, and the redraw only ever consults the
        cached number. An unreadable answer stays 0 and hides nothing.
        """
        if self._own_server:
            return

        def work() -> None:
            srv = self.own_server()
            if srv:
                self.after(lambda: (self._render(), self._update_status()))

        threading.Thread(target=work, daemon=True).start()

    def refresh_live(self) -> None:
        """A share landed: re-merge the checkpoint and re-read the raid list.

        Only if the tab has been opened — an unopened one reads fresh when it is first
        shown. The roster below is deliberately NOT re-read here: a mate SHARING a raid
        does not change who is running what, and that read is the expensive one.
        """
        if self.loaded:
            self.refresh()
            self._snapshot()

    def refresh_both(self) -> None:
        """«Обновить»: every source the tab has, in one press.

        The checkpoint merge (a file read), the raid list off the VM, the alliance
        roster (#1244) and the ghost-recon list (#1251). Each guards its own path with
        its own flag, so none of them can silently skip because another happened to be
        in flight.
        """
        self.refresh()
        self._snapshot()
        self._roster()
        self._ghost()

    def refresh(self) -> None:
        """Merge the live capture checkpoint (the wire feed) into the list.

        The button, the capture's per-finding nudge and the «secret_task_share» trigger
        all land here. Cheap — a file read, no game round trip — and it only ADDS, so a
        burst of nudges coalesces to nothing worse than a re-merge of the same tiles.
        """
        # The tile capture's own findings ride the same nudge (#1251): whichever
        # capture is selected, re-merging its checkpoint is a file read, and this is
        # what turns a lap of the map into rows on the ghost-map page.
        self.refresh_ghost_map()
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
        """Everything the capture has checkpointed — the wire feed into OUR list.

        NO FRESHNESS WINDOW HERE ANY MORE (#1251). The capture is a SOURCE: its job is
        to bring findings into the tab's own list and stop there. What happens to a row
        afterwards is the list's own business — it is kept, checkpointed across a
        restart, and removed when THIS tab's rules say so: the task expired, it was
        robbed, or a live read stopped confirming it (`_merge`, `_tick`,
        `_poll_apply`). Dropping a row because nobody has driven the map past it for
        fifteen minutes made a lap of the map show nothing at all half an hour later,
        which is exactly the wrong way round.

        The window still governs a ROBBERY, which is a different question with a
        different cost — that gate lives in the auto-loot watcher, not here.

        THE STAR AND THE LEVEL ARE RE-ASKED OF THE GAME HERE (#1188). The capture wrote
        them from the cfgId's digits, because it decodes a pcap in a child process with
        no client in it — and the digits call a `60009903` template «level 99, starred»
        where the game's own config row calls it «level 7, not starred» (#1267). This
        list is what the standing order spends the day's five raids out of, so it may
        not carry a guessed star: `apply_cfg_rank` asks `lw_dispatch_tasks` for every
        DISTINCT template on the checkpoint — a handful of ids, one round trip — and the
        filter below then means the game's word rather than the decoder's.

        Off the Tk thread, like everything else this method does (`_scan_work` runs it),
        so the round trip costs the window nothing. A client that cannot answer leaves
        the digits in place, which is exactly where they were before.

        A missing checkpoint (the capture never ran) or a malformed one raises and is
        caught upstream as "no new tiles".
        """
        import lastwar_proto as proto
        import steal_secret_task
        tasks = proto.load_fresh_tasks(self.rt.profiles.tasks_json(),
                                       max_age_seconds=None)
        try:
            fixed = steal_secret_task.apply_cfg_rank(self.rt.game.evaluator(), tasks,
                                                     say=lambda _m: None)
        except Exception:            # noqa: BLE001 — no daemon, no game: keep the digits
            fixed = 0
        if fixed:
            # Said in the panel's own words, not the tool's: the child's line is English
            # by construction and this one is read by whoever is watching the tab.
            self.say("secret", "log.secret.cfg_reranked", n=fixed)
        return [t for t in tasks if t.starred]

    def _fetch_vm(self) -> list:
        """The first-open snapshot: every live starred alliance task straight from the VM.

        Every tile on the map with a free slot — the ones already raidable AND the ones
        still counting down — so a row can carry its «готово через …» timer and flip to
        raidable in place.

        This is the RAID list, and the star filter is part of what it means. What the
        alliance is running, plain tiles and all, is a different question with a read of
        its own (:meth:`_roster`).
        """
        import steal_secret_task
        tasks = steal_secret_task._vm_all_alliance_tasks(self.rt.game.evaluator())
        return [t for t in tasks if t.starred]

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
                # Starred by construction: both feeds of THIS list keep only the
                # tiles the game draws a star on (#1244), so a row here always wears
                # one — unlike the roster below, where most rows do not.
                "starred": True,
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
             "expires_at": r["expires_at"], "completed_at": r["completed_at"],
             # …AND THE STAR (#1267). It used to be left out and re-derived from the
             # cfgId on the way back in, which is the third copy of the rule #1244
             # replaced: a tile the game calls level 7 whose digits read `99` was
             # accepted by both feeds and then dropped by the restore, so a restart
             # quietly shortened the list it had just promised to keep.
             "starred": bool(r.get("starred", True))}
            for r in self._rows.values()])

    def _load_persisted(self) -> set:
        """Read back the last session's list; return the keys still needing a live check.

        A row already past its own `expires_at` is dropped here rather than shown and
        then dropped a moment later by the first tick — there is nothing a live check
        could confirm about a tile the map itself says is gone. Judged against the
        GAME's clock (#1227), like every other timestamp on this tab, not this
        machine's — `game_clock` needs no game read to answer, only the drift it last
        measured (0 the first time this profile is ever opened).

        A row that is not STARRED is dropped here too (#1244). Both feeds are
        starred-only, so a plain tile in the checkpoint is a leftover of an older
        version — but it is restored blind, and once restored it sits on the table for
        the rest of the session looking exactly like a raid worth going to. One live
        profile's file had 153 rows in it, three of them level-4 plain tiles that no
        feed on this tab could have put there this year.

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
            # What the LIST decided when the row was live outranks anything re-derived
            # here (#1267). Only a checkpoint written before the star was kept — an
            # older panel's — falls through to the digits.
            starred = (bool(rec["starred"]) if "starred" in rec
                       else _starred_cfg(rec.get("cfg_id")))
            if not starred:
                continue
            key = str(uuid)
            self._rows[key] = {
                "uuid": uuid, "server": rec.get("server"), "x": rec.get("x"),
                "y": rec.get("y"), "level": rec.get("level"),
                "cfg_id": rec.get("cfg_id"), "loot_count": rec.get("loot_count") or 0,
                "expires_at": exp, "completed_at": rec.get("completed_at"),
                # Restored rows are starred too — anything else was dropped above.
                "starred": True,
                "timer": tk_stringvar(self.rt.root), "ready": False, "soon": False,
            }
            restored.add(key)
        return restored

    # -- the phone ---------------------------------------------------------------
    #
    # READING ONLY, and that is a decision rather than an omission. The robbery on this
    # tab presses through `actions/steal_secret_task.md` now, but it still spawns a tool
    # first to PARK the chosen tiles — the recipe cannot fill the queue it spends
    # (`CLAUDE.md`, task #1188) — and a «Ограбить» button on the phone would carry that
    # spawn outside the house, which is the half of the ability `web_press` may not run. The tiles,
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
            facts = [{"label": "secrettasks.col.level", "value": self._rank(row)},
                     {"label": "secrettasks.col.slots",
                      "value": f"{row.get('loot_count')}/3"}]
            # The same mark the window puts on the row (#1245): the glyph on the
            # coordinate, the words in the line under it. Whoever is reading the phone
            # is the one most likely to forward a tile twice — they cannot see the
            # alliance chat they would be posting into.
            if row.get("shared"):
                facts.append({"label": "secrettasks.shared_mark", "value": ""})
            done, exp = row.get("completed_at"), row.get("expires_at")
            # A spent tile says so instead of saying «готово»: it is on the list only
            # because the box asked for it, and «ready» on a row nobody can rob is the
            # single most misleading word the screen could carry.
            spent = self._spent(row)
            text = coords.fmt(row.get("x"), row.get("y"), row.get("server"))
            if row.get("shared"):
                text = "%s %s" % (grid.SHARED_GLYPH, text)
            items.append({
                "text": text,
                "facts": facts,
                # Ready: how long is left to take it. Not ready: when it becomes one.
                "until": ((exp if row.get("ready") else done) or 0) / 1000.0 or None,
                "pill": ("secrettasks.spent" if spent
                         else "secrettasks.ready" if row.get("ready") else None),
            })
        hidden = self._hidden_at_home()
        # What «Автолут ★» is doing, in the same words the window puts under the
        # checkbox. It is the reading somebody away from the machine most needs: the
        # tiles say what is on the map, this says whether anything is going to be taken
        # — and «nothing, the day's five are spent» is not a thing to guess at (#1227).
        state_key, state_datum = self.autoloot.state()
        low = self.autoloot.level_min()
        return {"cards": [{"title": "secret.autoloot.frame",
                           # The RULE as well as the state (#1256): the window draws the
                           # two side by side under the checkbox, and «минимальный
                           # уровень» is the one number that decides where the day's five
                           # go — reading «сторожит» without it says nothing about what
                           # is about to be spent.
                           "rows": [{"label": "secret.autoloot.level_min",
                                     "value": (str(low) if low is not None
                                               else self.t("secret.autoloot.any_level"))},
                                    {"label": state_key, "value": state_datum}]},
                          # The window's pages, as the phone's cards (#1244, #1251) — a
                          # screen scrolls where a window switches. EACH CARD CARRIES
                          # ITS OWN PAGE'S SWITCHES, for the same reason the window
                          # stopped having one strip on top: a press has to say which
                          # list it is about.
                          {"title": "secrettasks.page.stars", "items": items,
                           "rows": ([{"label": "secrettasks.filter.hide_own",
                                      "value": str(hidden)}] if hidden else []),
                           "empty": "secrettasks.empty",
                           # …and the button says WHAT it turns on (#1264). «Включить
                           # мониторинг» on a screen with two of them is a button whose
                           # meaning depends on which card it happens to be under, and a
                           # phone is scrolled past the titles.
                           "actions": [{"id": "monitor",
                                        "label": ("secret.monitoring.stars.off"
                                                  if self.monitor_var.get()
                                                  else "secret.monitoring.stars.on")},
                                       {"id": "show_spent",
                                        "label": ("secrettasks.hide_spent"
                                                  if self.show_spent_var.get()
                                                  else "secrettasks.show_spent")},
                                       {"id": "hide_own",
                                        "label": ("secrettasks.filter.show_own"
                                                  if self.hide_own_var.get()
                                                  else "secrettasks.filter.hide_own")},
                                       {"id": "clear", "label": "secrettasks.clear"}]},
                          {"title": "secrettasks.alliance",
                           "items": self.alliance.web_items(),
                           "empty": "secrettasks.alliance.empty",
                           "actions": [{"id": "ur_only",
                                        "label": ("secrettasks.filter.ur_off"
                                                  if self.alliance.ur_var.get()
                                                  else "secrettasks.filter.ur_on")},
                                       {"id": "star_only",
                                        "label": ("secrettasks.filter.star_off"
                                                  if self.alliance.star_var.get()
                                                  else "secrettasks.filter.star_on")}]},
                          # The two ghost cards carry the event's own facts as well as
                          # their squads: six days a week «событие закрыто» IS the
                          # reading, and an empty list without it is a mystery.
                          # …and the ghost switch is on BOTH ghost cards (#1264), the
                          # window's two boxes said in the phone's own idiom. The same
                          # `id`, so both are the same press through the same branch of
                          # `web_press` into the same variable — the phone cannot grow a
                          # second state here any more than the window can.
                          {"title": "secrettasks.ghost",
                           "rows": self.ghost.web_rows(),
                           "items": self.ghost.web_items(),
                           "empty": "secrettasks.ghost.empty",
                           "actions": [self._ghost_monitor_action()]},
                          {"title": "secrettasks.ghost.allies",
                           "items": self.ghost_allies.web_items(),
                           "empty": "secrettasks.ghost.allies.empty"},
                          # …and the sniffer's own card, where its tiles land (#1251).
                          {"title": "secrettasks.ghost.map",
                           "items": self.ghost_map.web_items(),
                           "empty": "secrettasks.ghost.map.empty",
                           "actions": [self._ghost_monitor_action()]}],
                "now": now,
                # What is left at the bottom is what belongs to the WHOLE tab.
                #
                # «Зум» and «Обойти карту» are here because the window put them on the
                # coordinate bar, which belongs to the whole tab too (#1265). The lap is
                # a scenario (`actions/scan_map.md`) and nothing else, so it is a press
                # the phone may make — unlike «Ограбить» above, which parks its targets
                # with a spawned tool first. The level cycles rather than offering three
                # buttons: it is one setting with three values, and a screen that shows
                # which one is on and moves to the next is how the other switches on this
                # tab already read.
                "actions": [{"id": "refresh", "label": "tabx.refresh"},
                            {"id": "zoom",
                             "label": f"coord.zoom.{self._zoom_level}"},
                            {"id": "sweep_now", "label": "coord.sweep_now"}]}

    def _ghost_monitor_action(self) -> dict:
        """The ghost sniffer's button, built once and drawn on both ghost cards (#1264).

        A method rather than two literals for the reason the whole change exists: the
        NEXT thing done to this button — a different word, a confirmation, a state — is
        done once and lands in both places, instead of landing in one and quietly
        splitting the pair.
        """
        return {"id": "ghost_monitor",
                "label": ("secret.monitoring.ghost.off"
                          if self.ghost_map.monitor_var.get()
                          else "secret.monitoring.ghost.on")}

    def web_press(self, action: str, args: dict) -> dict:
        """«Обновить», and the two display rules the phone may change.

        Still no «Ограбить» — the robbery on this tab presses through a scenario, but it
        parks its targets with a spawned tool first (`CLAUDE.md`, #1188), and a second
        copy of THAT reached from outside the house is the same debt twice.
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
        if action == "hide_own":
            self.post(self._toggle_hide_own)
            return {"ok": True}
        if action == "monitor":
            self.post(lambda: self._toggle_capture(self.monitor_var, self.capture))
            return {"ok": True}
        if action == "ghost_monitor":
            self.post(lambda: self._toggle_capture(self.ghost_map.monitor_var,
                                                   self.ghost_capture))
            return {"ok": True}
        if action in ("ur_only", "star_only"):
            self.post(lambda: self._toggle_alliance_filter(action))
            return {"ok": True}
        if action == "clear":
            self.post(self._clear)
            return {"ok": True}
        if action == "zoom":
            # The window's own field, moved on by one — so the two front-ends cannot
            # disagree about how far back the camera is going to sit.
            self.post(self._cycle_zoom)
            return {"ok": True}
        if action == "sweep_now":
            self.post(self._sweep_once)
            return {"ok": True}
        return {"error": "unknown"}

    def _cycle_zoom(self) -> None:
        """Next zoom level, on the Tk thread — the phone's version of the window's box."""
        names = self._zoom_names()
        try:
            nxt = names[(names.index(self._zoom_level) + 1) % len(names)]
        except ValueError:                        # a level that no longer exists
            nxt = names[0]
        self._zoom_level = nxt
        self._sync_zoom_combo()
        self._on_zoom_choice()

    def _toggle_show_spent(self) -> None:
        """Flip «Показывать исчерпанные» from the phone, on the Tk thread.

        Through the same variable the window's box is bound to, so the two front-ends
        cannot disagree about which way it is set.
        """
        self.show_spent_var.set(not self.show_spent_var.get())
        self._on_show_spent()

    def _toggle_capture(self, var, capture) -> None:
        """Flip one sniffer's own switch from the phone, on the Tk thread (#1251).

        The window's own variable, so the two front-ends cannot disagree — and the
        capture it belongs to, so switching the ghost sniffer on from a phone does not
        stop the secret-task one.
        """
        var.set(not var.get())
        capture.toggle()
        self.rt.settings.changed()

    def _toggle_hide_own(self) -> None:
        """Flip «Скрывать со своего сервера» from the phone (#1251).

        The window's own box, not a copy of it — a phone that hid rows the machine
        still shows is exactly the divergence the two front-ends must not have.
        """
        self.hide_own_var.set(not self.hide_own_var.get())
        self._on_hide_own_change()

    def _toggle_alliance_filter(self, action: str) -> None:
        """Flip «UR» or «Звезда» on the alliance page from the phone (#1251)."""
        var = self.alliance.ur_var if action == "ur_only" else self.alliance.star_var
        var.set(not var.get())
        self.alliance.refilter()

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
        """Whether `level` is inside the DISPLAY range — «Фильтры: уровень от / до».

        The same pair the capture's log filter reads (`Capture.passes`), and that is the
        whole point of it (#1244): what is printed and what is on the table have to be
        one set. They were two — this asked the AUTO-LOOT range instead — so a profile
        filtering the log at 5-7 while robbing at 7-7 saw level-5 stars in the log and an
        empty place where their rows should have been.

        Inclusive at both ends, and an empty box is no bound at all.
        """
        return self._within(level, self.filter_from_var.get(), self.filter_to_var.get())

    def _in_rob_range(self, level) -> bool:
        """Whether `level` is worth a robbery — «Автолут ★»'s own «минимальный уровень».

        One bound, and it is the bottom (#1256): this level and everything above it. An
        empty box is no bound at all.

        Separate from the display filter on purpose (#1099): narrowing what is printed
        must not silently re-aim the five robberies a day, and widening it must not
        hand them a level nobody asked to spend one on.
        """
        low = self.autoloot.level_min()
        return low is None or int(level or 0) >= low

    def has_rows(self) -> bool:
        """Whether OUR list holds anything at all — the watcher's «есть ли источник».

        Asked instead of "is there a checkpoint / is the VM up" (#1256): the sources are
        the list's business, and an empty list is the one honest answer to «there is
        nothing to weigh yet», whichever of them has not arrived.
        """
        return bool(self._rows)

    def rob_candidates(self) -> list:
        """The rows «Автолут ★» would rob right now, best level first — OUR list only.

        THE ONE PLACE THE STANDING ORDER'S TARGETS ARE CHOSEN (#1256). Everything it
        weighs is a row of this tab's model: filled by the capture off the wire, seeded
        by the client's own tables, updated by the alliance pushes, and re-verified
        against the game by the ready-row poll, which drops what it can no longer
        confirm. The watcher used to re-read those sources for itself through a copy of
        the rule, so the list and the robberies could disagree about the very same map.

        The rule, in order: the tile is raidable (ready, and not looted out —
        :meth:`_collectable`), it wears a star (every row of this list does, by
        construction), its level is at or above «минимальный уровень», and **it is on
        somebody else's server**. Robbed by hand this session (`_collected`) is excluded
        for the obvious reason.

        THE HOME SERVER IS NEVER A TARGET, and that is not a setting (#1188). It used to
        be one, shipped OFF, so the standing order robbed the neighbours unless somebody
        had thought to forbid it — and the price of that is not an error anybody sees but
        one of the day's five quietly spent in the wrong place (#1099). An own server
        that cannot be READ (0) makes this list EMPTY rather than unfiltered: «I don't
        know which one is home» must never come out as «none of them is».

        NOT filtered by what the table happens to be showing: the display boxes are a
        pair of eyes, and somebody narrowing them to read something must not thereby
        change which tiles the day's five are spent on. «Скрывать со своего сервера» is
        one of those eyes and is unrelated to the prohibition above.
        """
        skip = self.autoloot.skip_server()
        if not skip:
            return []
        rows = [row for key, row in self._rows.items()
                if key not in self._collected
                and self._collectable(row)
                and row.get("starred")
                and self._in_rob_range(row.get("level"))
                # A KNOWN server that is not home. `0` is «the row never carried one»,
                # and a row that cannot say where it is must not be robbed on the
                # strength of not saying «here» — the same reason an unreadable own
                # server empties the list above.
                and int(row.get("server") or 0) not in (0, skip)]
        # Best first, and among equals the tile with the most slots left: it is the one
        # most likely to still be there when the send lands.
        rows.sort(key=lambda r: (-int(r.get("level") or 0),
                                 int(r.get("loot_count") or 0)))
        return rows

    @staticmethod
    def _within(level, low: str, high: str) -> bool:
        """`level` against a pair of typed bounds; a blank or junk box is no bound."""
        lvl = int(level or 0)
        low, high = str(low).strip(), str(high).strip()
        if low.isdigit() and lvl < int(low):
            return False
        if high.isdigit() and lvl > int(high):
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
        """The rows the ★ page shows: in the level range, not looted out, not at home.

        «Показывать исчерпанные» lifts the second rule. It is off by default because a
        3/3 tile cannot pay anybody and only costs the eye a line, and it exists at all
        so that a row that vanishes can be looked for rather than guessed at (#1227).

        «Скрывать со своего сервера» is the third, ON by default (#1251) — the raids
        worth a march are the ones abroad. It is a DISPLAY rule: the tile it hides is
        still robbed by hand, still shared and still jumped to, and the robberies obey
        their own «Не грабить на своём сервере» over in the auto-loot frame.

        A server the account's own could not be read from (0) hides nothing: a rule
        that cannot tell home from abroad must not guess that everything is home.
        """
        show_spent = bool(self.show_spent_var.get())
        # The CACHED reading only (`_own_server`), never `own_server()`: this runs on
        # the Tk thread on every redraw, and the reader behind that method goes to the
        # game whenever the answer is still unknown. It is primed once per profile by
        # `_prime_own_server`, off the Tk thread, alongside the reads the tab already
        # makes — so this rule costs no round trip of its own.
        mine = self._own_server if self.hide_own_var.get() else 0
        return [r for r in self._rows.values()
                if self._in_range(r["level"])
                and (show_spent or not self._spent(r))
                and not (mine and int(r["server"] or 0) == mine)]

    def _update_status(self) -> None:
        """«секреток: N» — and how many of them the home-server rule is holding back.

        A box that empties the table without saying so is indistinguishable from a tab
        that read nothing (#1251): one live account has every star it can see on its
        own server, and the whole list going blank on first open is exactly what that
        looks like. The count says which of the two it is.
        """
        n = len(self._visible_rows())
        hidden = self._hidden_at_home()
        line = self.t("secrettasks.count", n=n) if n else ""
        if hidden:
            mark = self.t("secrettasks.hidden_own", n=hidden)
            line = "%s · %s" % (line, mark) if line else mark
        self._status_var.set(line)

    def _hidden_at_home(self) -> int:
        """How many rows «Скрывать со своего сервера» is keeping off the table."""
        if not (self.hide_own_var.get() and self._own_server):
            return 0
        show_spent = bool(self.show_spent_var.get())
        return sum(1 for r in self._rows.values()
                   if self._in_range(r["level"])
                   and (show_spent or not self._spent(r))
                   and int(r["server"] or 0) == self._own_server)

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
            # The other pages count down on the same second as this one — one chain for
            # the tab, not a timer per table.
            self.alliance.tick()
            self.ghost.tick()
            self.ghost_allies.tick()
            self.ghost_map.tick()
        finally:
            # Named, so the countdown is one chain however often `_start_ticking` is
            # reached.
            self.rt.tick.arm("secret_tick", 1000, self._tick)

    def _refresh_timers(self) -> tuple:
        """Rewrite every row's timer; return (expired keys, did ready/soon change on any).

        The arithmetic is `grid.refresh_timers` — the grid below runs the very same one
        on its own rows every second (#1244).

        The «уже поделились» mark is stamped on first (#1245), because the state cell
        the timer writes carries it: a share pressed in the GAME reaches the panel as a
        line appended to the profile's store by a capture child, so a flip of that flag
        counts as a change worth redrawing exactly like a tile maturing does.
        """
        marked = self.shared.apply(self._rows)
        expired, changed = grid.refresh_timers(self._rows, self.t)
        return expired, changed or marked

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
        """Reconcile the polled ready rows: drop the gone, refresh the rest.

        A failed read (``live is None``) is not evidence a tile vanished, so it is left
        alone until the next poll. A tile missing from a GOOD read is off the map
        (expired) or looted out (its slots filled), and either way it can no longer be
        robbed — so its row drops.

        THE ROBBERY IS NOT HERE ANY MORE (#1256). This poll used to rob as well as
        verify, through a second copy of the rule and a direct `hero.dispatch.steal` of
        its own — a third doorway into the ability, on a thirty-second clock, beside the
        watcher's. What it does now is the half it is good at: it is the actuality check
        the list is kept true by, and «Автолут ★» chooses out of the list it leaves
        behind (:meth:`rob_candidates`).
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
        if removed:
            self._render()
            self._update_status()
        self._persist_rows()

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
            self.after(lambda: self._share_done(row, scope, ok))

        threading.Thread(target=work, daemon=True).start()

    def _share_done(self, row, scope: str, ok: bool) -> None:
        """Say what happened — and, if it went, remember that this tile has been shown.

        The mark is the same fact a share pressed in the game leaves behind (#1245), so
        it goes into the same store; both tables draw it, and the redraw is immediate
        rather than on the next tick, because the operator is looking at the row they
        just shared.
        """
        where = self.t("secrettasks.share_alliance" if scope == SHARE_ALLIANCE
                       else "secrettasks.share_world")
        key = "secrettasks.shared_ok" if ok else "secrettasks.share_fail"
        self.rt.put("[secret] " + self.t(key, where=where))
        if ok and row is not None:
            self.shared.mark_panel(row.get("uuid"))
            self._render()
            self.alliance.render()

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


def _starred_cfg(cfg_id) -> bool:
    """Whether a stored `cfgId` is a starred tile — `lastwar_proto`'s rule, not a copy.

    ONLY FOR A CHECKPOINT THAT DOES NOT SAY (#1267). Since #1244 the star is the game's
    `is_special` column and the digits are the fallback; a checkpoint written by this
    panel carries `starred` and is believed. This answers for the one written before it
    did — where re-deriving is all there is, and where it was silently dropping tiles
    the game calls level 7 because their digits read `99`.
    """
    import lastwar_proto as proto

    try:
        _family, _level, starred = proto.task_rank(cfg_id)
    except (TypeError, ValueError):
        return False                      # unusable id — never a row worth drawing
    return starred
