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
never out of a second reading of the sources — so its block is drawn ON THE ★ PAGE, over
that list, rather than as a strip above the whole notebook (#1271). What each page SHOWS
is that page's own «уровень от / до», which re-aims no robbery at all.

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
import re
import threading
import time
import tkinter as tk
from tkinter import ttk

from ...widgets import NumericEntry, tk_stringvar, font as ui_font
from ..base import PanelTab, TriggerSpec
from . import grid
from .alliance import AllianceGrid
from .autoassist import AutoAssist
from .autoloot import AutoLoot
from .capture import Capture
from .ghost import GhostAllianceGrid, GhostGrid, GhostMapGrid
from .shared import SharedMarks

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

# How often a RAIDABLE row is re-read from the game. «Проверять их очень часто ПОСЛЕ
# того, как они готовы» (#1272) — and it used to be thirty seconds, on the theory that a
# raidable tile lives for minutes. It does not: it lives until the first person reaches
# it, and half a minute of «готово к сбору» about a tile somebody else emptied is the
# list lying to whoever is looking at it.
#
# Three seconds, and it costs nothing when there is nothing ready: the chain is armed
# only while some row is (`_maybe_start_poll`), and one round is one chunk through the
# warm daemon. What it can and cannot testify about is `_answerable`'s business — this is
# only how often it asks.
POLL_MS = 3_000

# How often the countdowns are REDRAWN, as opposed to recomputed (#1272). «Те, что уже
# можно грабить, должны обновляться несколько раз в секунду»: a cell rewritten once a
# second is a second late for most of every second, and on a raidable tile that reads as
# a list that has stopped moving.
#
# Four times a second is affordable only because of what this pass is not. It draws; it
# does not decide. Nothing expires here, no row flips to ready, nothing is re-sorted and
# the game is not asked anything — all of that stays in the once-a-second pass below, and
# a cell is touched only when its text has really changed. See
# `grid.repaint_countdowns`.
LIVE_MS = 250

# How long the per-tile read waits for the SERVER's replies, and how often it looks
# (#1272). This is the one wait on the state read that is not the panel's own slowness:
# `world.get.detail.new` goes out per tile and each reply lands when it lands.
#
# It used to be a flat `sleep(1.2)` followed by a 1.0 s settle, paid in full even when
# every answer was already in — three of the four seconds a press cost. Now the read-back
# is repeated every :data:`DETAIL_POLL_SEC` and stops the moment every asked tile has a
# real answer, so a handful of ready rows on a warm client is a fraction of a second and
# the ceiling is only reached when the server really is silent. The ceiling itself is
# what the old sleep-plus-settle came to, so nothing that used to answer stops answering.
DETAIL_WAIT_MS = 2_200
DETAIL_POLL_SEC = 0.12

# How often the list re-checks ITSELF against the game, and how much of it at a time
# (#1280). «Обновить состояние» is a press, and the complaint that produced this was that
# the automatic half only ever looked at the rows that were already ready — so a tile
# somebody else emptied an hour ago went on saying «готово через 40 минут» until a hand
# pressed something.
#
# A SLICE, not the list. The read holds the game while it runs, so twenty tiles — one
# probe chunk and one read-back — is what one turn costs, and a ninety-row list comes
# round in about two minutes. The rows whose state lives seconds are not waiting for this:
# they are at the front of every slice AND asked about every :data:`POLL_MS` by the poll.
STATE_MS = 30_000
STATE_SLICE = 20

# How long BEFORE a tile matures «Собрать» is already offered (#1272). A star is taken
# in the first moment it is takeable — «счёт может идти на микросекунды, потому что много
# желающих уже кликают» — and a button that appears at the instant of readiness is one
# nobody can have a finger over.
#
# Pressing inside the window does NOT throw a robbery at the server early: the send waits
# out the remainder and goes at the moment the tile matures, which is what a person
# cannot do by hand and is the whole reason the early button is worth having. A premature
# `hero.dispatch.steal` is answered with a tip and nothing else — the daily counter is
# the SERVER's number and comes back only on the success branch of the reply
# (`DispatchStealMessage:HandleMessage`), so a refusal spends nothing — but it also robs
# nothing, and a button that looked like a robbery and was none would be worse than no
# button.
#
# Ten seconds because that is what was asked for, and because it is the span a person can
# actually hold a finger over. The STANDING ORDER does not get this window (`_raidable`):
# a machine gains nothing from pressing early.
EARLY_MS = 10_000

# …and how long before it the STANDING ORDER starts pressing (#1272). A couple of
# seconds, and deliberately NOT the ten above.
#
# THE TWO WINDOWS ARE DIFFERENT ON PURPOSE. DO NOT UNIFY THEM. Ten seconds is what a
# person asked for and what a person needs: time to see the row, move the mouse and hold
# still. Ten seconds of a MACHINE pressing seven times a second is seventy round trips
# spent on a tile that cannot answer yet — «10 секунд для автолута это вечность». Two is
# what the race needs and no more: the recipe presses from here until the server says
# yes, and every press before the tile matures is free (the reply is a tip, the counter
# does not move, nothing is spent) but not free of a round trip.
#
# It is a PICK window rather than a press window: the watcher's poll and the run's start
# sit between noticing a tile and pressing it, so the number is what makes the first
# press land at about two seconds out, not what the first press is timed to.
AUTO_EARLY_MS = 2_500

# What a robbery the SERVER answered looks like in the recipe's own output. The daily
# counter moving is the only honest «it worked»: `hero.dispatch.steal` gets a tip back
# when the tile is not ready, not in reach or already full, and a frame leaving the
# client proves none of that. Said by `actions/steal_secret_task.md`; reword it there and
# here in the same breath.
TAKEN_MARK = "steal_taken"

#: …and the per-target verdict the recipe emits as it drops each one: `ACT steal_done
#: uuid=<u> how=<taken|gone|unanswered>`. `gone` is the server saying there is nothing
#: there any more — «задание уже взято», «больше не доступно», «срок истёк» — which is
#: the one absence that IS evidence about a particular tile, whoever found it. It is the
#: exception `_answerable` is deliberately not: that rule is about a tile missing from a
#: LIST, this is the server answering about the tile itself.
DONE_LINE = re.compile(r"steal_done uuid=(\d+) how=(\w+)")

# How often the game's own clock is re-measured (#1227). It is not this machine's
# clock, which was measured eleven seconds slow against it — and the operator had been
# reading 25-30 s of that — so every countdown here is drawn
# against `game_clock`, and this is what keeps it true. Five minutes is far more often
# than a drift of seconds a day needs; the read is one line through the warm daemon.
CLOCK_MS = 5 * 60_000

# How often the ★ sniffer flushes what it has decoded, in seconds. ONE, and there is no
# box for it any more (#1272): the capture exists so that a starred tile is known while
# it is still worth robbing, and a fifteen-second flush was fourteen seconds of a tile
# sitting undiscovered for no gain anybody could name. A profile that wants another
# number still carries `monitor_interval` and it is still honoured — it is simply not
# something the tab asks about.
DEFAULT_INTERVAL = "1"

# WHERE A ROW CAME FROM, and therefore WHICH READ IS ALLOWED TO TAKE IT AWAY (#1272).
#
# This exists because a read that could not see a tile was deleting it. The VM read that
# seeds and verifies this list walks `ActDispatchTaskDataManager.allianceTask` — MY OWN
# alliance's tasks. Measured live: 170 tasks, 170 of them my alliance's, all 170 on the
# home server — and the raid list drops the home server on the way in (#1188), so on that
# account the VM read yields NOTHING AT ALL. The list is filled by the map capture, which
# finds strangers' tiles across the whole map, and every one of those was then dropped by
# «the VM read did not carry it». That is the whole of «увидел список на секунду — и он
# пропал»: not a race, a certainty, every start-up.
#
# So a row remembers its source and a read may only testify about its own. The capture's
# tiles are outside the VM read's scope; an absence there is not evidence.
SOURCE_VM = "vm"        # seeded / confirmed by the client's own alliance table
SOURCE_WIRE = "wire"    # found by the passive capture, or restored from its checkpoint

#: **THE RULE OF THIS LIST. READ IT BEFORE REMOVING A ROW ANYWHERE (#1272).**
#:
#: The ★ list is the operator's own record of what they have found. It is paid for with
#: laps of the map and it is not reproducible: a tile nobody drives past again is gone
#: for good. Three times in one day it was emptied by three different mistakes — a read
#: that could not see the rows deleting them, a lap wiping them before it started, and a
#: rescan discarding what it had — so the rule is written once, here, and every site that
#: removes a row says which of its two clauses it is exercising.
#:
#: **A ROW LEAVES THIS LIST FOR EXACTLY TWO REASONS:**
#:
#: 1. **The task is over.** Its own `expires_at` has passed — the game's clock, not
#:    ours — and there is nothing on the map any more. That is `_tick`.
#: 2. **The game said it is not there.** An ANSWER about that particular tile: the
#:    server's «задание уже взято / больше не доступно / срок истёк» (`_drop_gone`), or
#:    a per-tile read that came back with no detail while a control point proved the
#:    answers were arriving (`_state_landed`), or a live read that both COULD see the row
#:    and did not carry it (`_merge`, `_poll_apply`, gated by `_answerable`).
#:
#: **EVERYTHING ELSE IS A FILTER.** A tile robbed three times, one at home, one outside
#: the level range, one the boxes narrow away — all of those are still IN the list and
#: only kept off the screen, which is why «Показывать исчерпанные» can bring them back
#: and why the counter says how many are hidden.
#:
#: **AND NOTHING EMPTIES IT.** Not opening the tab, not a lap of the map, not starting or
#: stopping a monitor, not a failed read, not an empty one, not a restart. The two
#: exceptions are not exceptions to this: «Очистить список» is a person asking for it in
#: so many words, and a PROFILE SWITCH is another account's map — that list is kept in
#: that account's own checkpoint and comes back with it.
#:
#: A row we robbed ourselves obeys clause 1 and nothing else: it is kept, marked, without
#: «Собрать», so it can still be shared, and «уже взято» is the answer our own robbery
#: earned rather than evidence against it.
THE_LIST_RULE = "expiry, or the game saying the tile is not there — nothing else"

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
    LOCALE_NS = ("secrettasks", "secret", "autoloot", "autoassist", "tabx")
    NEEDS = frozenset({"daemon", "children", "actions"})
    # The capture and the two watchers are standing orders: they have to be RUNNING,
    # not waiting for somebody to open the tab.
    EAGER = True
    # Identity, deliberately: §5 rule 3 forbids renaming a key in the wave that moves
    # it, so the block spells every one of them exactly as the flat profile did.
    LEGACY_KEYS = {k: k for k in (
        "monitor_kind", "monitor_interval", "secret_monitor",
        "filter_level_from", "filter_level_to",
        "autoloot", "autoloot_level_from", "autoloot_level_to")}
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
        # …and the unattended state re-check (#1280), which is the SAME read «Обновить
        # состояние» makes and therefore needs a flag of its own: sharing `_vm_busy` with
        # it would let a background turn swallow a press, or a share push's snapshot.
        self._state_busy = False
        # Where the rotation had got to — see `_state_sweep`.
        self._state_cursor = 0
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
        # …and the uuids with a press already in flight (#1272). A press made inside the
        # ten-second window waits out the remainder before sending, and the row keeps
        # offering «Собрать» throughout — it is still counting down — so without this a
        # second press would arm a second send at the same instant.
        self._pressing: set = set()
        # Which uuids the standing order has already fired at is the standing order's own
        # book now (`AutoLoot._seen`, #1256) — there is one watcher and one place a
        # target is chosen, so there is one place to remember what has been tried.
        # Whether the ready-row poll is currently scheduled.
        self._polling = False
        # …and whether the fast countdown repaint is (#1272). Two chains, two questions:
        # this one only DRAWS, four times a second, and it is armed while there is a
        # clock running anywhere on the tab.
        self._living = False
        # …and whether a lap of the map is walking right now (#1272): the one button says
        # «Обойти карту» or «Остановить» by it, and a second press is the stop.
        self._sweeping = False
        self._sweep_btn = None
        # Cached (server, allianceId) for the chat room ids — read once, live.
        self._ids = None
        # The player's OWN server, cached the same way: what the home-server
        # prohibition compares a tile against. 0 = not read yet / unreadable.
        self._own_server = 0
        #: «home is unreadable, so the raid list admits nothing» — said once per spell
        #: of not knowing rather than once per feed (`_abroad_only`).
        self._warned_no_own_feed = False
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
        # HOW OFTEN THE SNIFFER FLUSHES, AND IT IS NOT ON SCREEN ANY MORE (#1272). One
        # second is what the capture is for — a tile is worth knowing about the moment it
        # lands, and every slower number was a way of finding out late. A machine that
        # genuinely needs it slower still says so, in the profile's `monitor_interval`;
        # what went away is the box, not the setting.
        self.interval_var = tk.StringVar(master=master, value=DEFAULT_INTERVAL)
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
        # «Автопомощь» and its own minimum level (#1272). A SECOND budget and a second
        # standing order, on the alliance page because that is the list it spends itself
        # over — the same reasoning that moved «Автолут ★» onto the ★ page (#1271).
        self.autoassist_var = tk.BooleanVar(master=master, value=False)
        self.assist_level_var = tk_stringvar(master)
        self._assist_lbl = None
        self._assist_line = None
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
        # The LAP's height (#1272) — «тайл» is not one of them any more, and the default
        # is the one that actually collects secret tasks. A jump takes no height at all.
        self._zoom_level = lua_actions.SWEEP_LEVELS[0]
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
        # …and the alliance page's own standing order (#1272), which spends a DIFFERENT
        # daily budget on a DIFFERENT command: five helps a day through
        # `hero.dispatch.assist`, over the alliance's own finished tasks.
        self.autoassist = AutoAssist(rt, self)
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
        the capture's reader and the two standing orders' watchers, all of them workers,
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
        if self.autoassist_var.get():
            self.autoassist.start()

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
        self._state_sweep()
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
        self.autoassist.stop()
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
        # NOT a wipe (`THE_LIST_RULE`): this is another ACCOUNT's map. The rows that
        # leave here are kept in the old profile's own checkpoint and come straight back
        # with it; the new profile's own list is read in below.
        self._rows.clear()
        self._collected.clear()
        # …and what the standing order had already fired at belongs to that account's
        # map, not this one's (#1256). A press waiting out its ten seconds belongs to the
        # old client too (#1272): the worker will fire into whatever is there and be
        # refused, and the set must not keep the tile un-pressable afterwards.
        self.autoloot._seen.clear()
        self._pressing.clear()
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
        if self.autoassist_var.get():
            self.autoassist.start()

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
                book.tab(index, text=self._page_label(index, key))
        except tk.TclError:
            return

    def panic(self) -> None:
        """«Стоп всё»: every standing order down, and the boxes say so."""
        self._was = {}
        for name, var, order in (("monitor", self.monitor_var, self.capture),
                                 ("ghost", self.ghost_map.monitor_var, self.ghost_capture),
                                 ("autoloot", self.autoloot_var, self.autoloot),
                                 ("autoassist", self.autoassist_var, self.autoassist)):
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
                          ("autoassist", self.autoassist_var)):
            if was.get(name):
                var.set(True)

    def shutdown(self) -> None:
        self.capture.stop()
        self.ghost_capture.stop()
        self.autoloot.stop()
        self.autoassist.stop()
        for name in ("secret_tick", "secret_live", "secret_poll", "secret_nudge",
                     "secret_clock", "secret_state", "autoloot_push_restart"):
            self.rt.tick.disarm(name)
        self._ticking = self._polling = self._living = False
        self._state_busy = False

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
            # …and the alliance page's own order and its own minimum (#1272). A second
            # key rather than a shared one: the two budgets are different commands with
            # different daily caps, and a level worth one of five robberies abroad is not
            # necessarily a level worth one of five helps at home.
            "autoassist": bool(self.autoassist_var.get()),
            "autoassist_level_min": self.assist_level_var.get(),
            "coord_x": self.coord_x_var.get(),
            "coord_y": self.coord_y_var.get(),
            "coord_server": self.coord_srv_var.get(),
            "coord_history": list(self._jump_hist),
            "coord_zoom": self._zoom_level,
        }

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self.interval_var.set(str(raw.get("monitor_interval") or DEFAULT_INTERVAL))
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
        # «Автопомощь» (#1272). `map_sweep` / `sweep_centre_x` / `sweep_centre_y` are
        # read from no profile any more and written to none: «Автообъезд карты» is gone,
        # and a profile that still carries the three keeps them as dead weight rather
        # than being rewritten behind the person's back.
        self.autoassist_var.set(bool(raw.get("autoassist", False)))
        self.assist_level_var.set(str(raw.get("autoassist_level_min") or ""))
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
                self.autoassist_var, self.assist_level_var,
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
        # NOTHING ABOUT ONE LIST STANDS OVER ALL FIVE (#1271, #1272). «Автолут ★» went
        # onto the ★ page with the list it robs; «Мониторинг ★-секреток» has followed it
        # there, and «Автообъезд карты» is gone altogether — «Обойти карту» on the
        # coordinate bar walks the whole server in about three seconds (#1265), which is
        # what the pass-and-rest loop had been approximating for a year.

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
        self._sweep_btn = self.tr(ttk.Button(box, command=self._sweep_once),
                                  "coord.sweep_now")
        self._sweep_btn.pack(side="left", padx=(8, 0), ipady=2)
        # «Обновить состояние» — the FIRST stage of keeping the ★ list true (#1272), and
        # a hand on it before any of it is automatic. It re-asks the game about the rows
        # that are ALREADY on the list — how many times each has been robbed, whether the
        # tile is still there at all — and it is not a map scan: «Обойти карту» beside it
        # is what FINDS tiles, this is what CHECKS the ones already found.
        self.tr(ttk.Button(box, command=self.refresh_state),
                "coord.refresh_state").pack(side="left", padx=(6, 0), ipady=2)
        self._jump_hist_combo = ttk.Combobox(box, textvariable=self._jump_hist_var,
                                             state="readonly", width=18, values=[])
        self._jump_hist_combo.pack(side="right", padx=(4, 0))
        self._jump_hist_combo.bind("<<ComboboxSelected>>", self._on_jump_history)
        self.tr(ttk.Label(box), "coord.history").pack(side="right", padx=(8, 2))
        self._set_jump_history(self._jump_hist)
        self._sync_zoom_combo()

    def _build_filter_bar(self, parent) -> None:
        """«Автолут ★», its one level box and the line saying what the rule will do.

        ON THE ★ PAGE, WITH THE LIST IT ROBS (#1271). It used to be a strip above the
        whole notebook, which said «this governs the tab» when it governs one of five
        tables: the ghost pages have their own robbery and their own switches, and a
        person looking at «Операция Призрак» read a level box that had nothing to do with
        what was on screen. `parent` is the ★ page's frame, and the block is the first
        thing on it — the same position on the glass it had before, one level in.

        ONE BOX, AND IT IS A MINIMUM (#1256). The range it replaces read as two bounds
        and behaved as one: only its top was ever robbed, so a raidable level-6 star sat
        there untouched under «от 1 до 7». «Минимальный уровень 6» robs the 6 and every
        7 above it, best first.

        Separate from the page's own «Фильтры: уровень от / до» below it on purpose
        (#1099): that pair is a pair of eyes and this one is a budget. The home server
        is not among the two — it is refused when the model is built, and there is no
        box that can allow it (#1188).
        """
        frame = self.tr(ttk.LabelFrame(parent, padding=6), "secret.autoloot.frame")
        frame.pack(fill="x", pady=(0, 4))
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        self.tr(ttk.Checkbutton(bar, variable=self.autoloot_var,
                                command=self._on_autoloot_toggle),
                "secret.autoloot").pack(side="left")
        self.tr(ttk.Label(bar), "secret.autoloot.level_min").pack(
            side="left", padx=(12, 2))
        NumericEntry(bar, textvariable=self.level_min_var, width=4).pack(side="left")
        # Narrower than the strip it replaces: the page sits inside the notebook's own
        # padding, so a label still demanding 760 px would widen the whole window.
        self._rule_lbl = ttk.Label(frame, foreground="#888", wraplength=720,
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
        # The capture's interval is a child-process argument, so a change only takes
        # effect on the next launch: bounce a running one rather than waiting for a
        # manual toggle. There is no box for it any more (#1272) — this is what carries a
        # `monitor_interval` typed into the profile while the panel is up.
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
        # The standing order first, then the eyes, then the list (#1271): «Автолут ★»
        # spends the day's robberies on THIS table, so it is read where the table is.
        self._build_filter_bar(stars)
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
        # …the count lands on it as soon as the page has rows (`sync_page_counts`); at
        # build time every list is still empty, so the bare name is the honest label.

    def _build_star_filters(self, parent) -> None:
        """The ★ page's own box: «Скрывать со своего сервера», ON by default (#1251).

        A DISPLAY rule and nothing else — it hides rows and robs nothing. The auto-loot
        frame directly above it is the other half: it spends the day's robberies and
        hides nothing, and a home tile is refused there whatever this box says (#1188).
        A tile at home stays shareable, jumpable and collectable by hand either way.
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

        # …and the SECRET-TASK sniffer's own switch, on the page it feeds — AND NOWHERE
        # ELSE NOW (#1272). It was drawn twice for a while (#1264, the same variable in
        # two places) because moving it off the frame above had left that frame standing
        # with its old title and only the map sweep inside, and whoever had been pressing
        # «Мониторинг» there reported the switch gone. The frame itself is gone now, so
        # there is nothing left for the copy to reassure: one box, on the page whose list
        # it fills, beside the rule that spends what it finds.
        #
        # NO INTERVAL BESIDE IT (#1272). It flushes every second — see `DEFAULT_INTERVAL`
        # — and a profile that wants another number says so in `monitor_interval`.
        mon = ttk.Frame(parent)
        mon.pack(fill="x", pady=(0, 4))
        self.tr(ttk.Checkbutton(mon, variable=self.monitor_var,
                                command=self.capture.toggle),
                "secret.monitoring.stars").pack(side="left")
        self.tr(ttk.Label(mon, foreground="#888", wraplength=520,
                          justify="left"), "secret.hint").pack(side="left", padx=10)

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
        # …and so does a tile WE have robbed (#1272), in front of the share mark and in
        # front of the token, which stays untouched behind both: a robbed row is kept
        # precisely so it can still be jumped to and still be shared, and a cell that
        # stopped parsing would take the first of those away.
        if row.get("robbed"):
            where = "%s %s" % (grid.ROBBED_GLYPH, where)
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
        """The lap's heights as words, in the order the camera pulls back."""
        import lua_actions
        return [self.t(f"coord.zoom.{name}") for name in lua_actions.SWEEP_LEVELS]

    def _zoom_names(self) -> list:
        """What the box may hold — the LAP's heights, and «тайл» is not one (#1272).

        A lap at the tile view needs a 24-tile step: **88 seconds of camera against 6**,
        and it finds nothing the 600 lap does not. It was on the list only because this
        one box also decided how high a JUMP landed, so anybody who wanted to land
        somewhere readable signed up for the 88-second sweep without knowing it. Jumps
        take no height any more, so the box is the lap's alone. A profile still holding
        «тайл» is moved to the first of these by `_sync_zoom_combo`.
        """
        import lua_actions
        return list(lua_actions.SWEEP_LEVELS)

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

    # -- «Обновить состояние»: re-ask the game about the rows already on the list ----
    def refresh_state(self) -> None:
        """Re-read the STATE of every row on the ★ list, readiest first (#1272).

        STAGE ONE OF KEEPING THE LIST TRUE, and deliberately a button rather than a
        clock: «давай идти по этапам… сделай кнопку, которая будет обновлять состояние».
        The automatic version comes after this one is seen to work.

        It is NOT a map scan. «Обойти карту» finds tiles; this checks the ones already
        found — the loot count, whether the tile is still there, its expiry — which is
        the half nothing could answer. The alliance table the tab already reads covers
        only MY alliance's tasks (live: 189, none starred, all at home), so for the
        strangers' tiles that make up this list it says nothing at all; the per-tile
        answer is the one a marker tap gets, `world.get.detail.new`.

        EVERY ROW, READIEST FIRST (#1280). It was narrowed to the raidable ones because a
        press cost four seconds of held game (#1272); the press costs a fraction of that
        now — one chunk asks about every tile at once and the read-back ends as soon as
        the replies land — so the narrowing bought nothing and hid what the button is
        for: «работает только по готовым строкам, а не по всему списку». The order is
        still readiest-first, so a read cut short by a slow VM has answered the rows whose
        state lives seconds before it stops.

        The 3-second poll keeps the narrow scope (`_state_targets(hot=True)`) — that one
        runs unattended and a press does not.
        """
        if self._vm_busy:
            return
        targets = self._state_targets()
        if not targets:
            # An empty list — and saying so is the honest answer to a press, rather than
            # a round trip that reports «проверено 0».
            self.say("secret", "log.secret.state_none")
            return
        self._vm_busy = True
        self._status_var.set(self.t("tabx.loading"))
        self._read_state(targets)

    def _read_state(self, targets, auto: bool = False) -> None:
        """Ask the game about these rows, off the Tk thread. One place, two callers."""
        keys = [str(r["uuid"]) for r in targets]
        tiles = [(int(r["x"] or 0), int(r["y"] or 0), int(r["server"] or 0))
                 for r in targets]
        threading.Thread(target=self._state_work, args=(keys, tiles, auto),
                         daemon=True).start()

    # -- and the same read, unattended, a slice at a time (#1280) ---------------
    def _state_sweep(self) -> None:
        """Re-check the WHOLE list by rotating through it, :data:`STATE_SLICE` at a time.

        «Обновить состояние» is a press, and a list that is only true when somebody
        presses is a list that lies for as long as nobody does. The 3-second poll cannot
        be that check — it asks the alliance table alone, which cannot testify about a
        stranger's tile at all — so this is the same two-part read the button makes,
        aimed at a slice of the list and moved on one slice at a time.

        A slice rather than the lot because the read holds the game while it runs: twenty
        tiles is one chunk and one read-back, and a ninety-row list comes round about
        every two minutes at :data:`STATE_MS`. The raidable rows are at the front of every
        slice regardless — `_state_targets` sorts them there — and they are asked about
        far more often by the poll anyway.

        Skipped whole while a press is already reading, while the game is down, and while
        the list is empty. It is a re-check, never a feed: nothing here can ADD a row.
        """
        try:
            if self._state_busy or self._vm_busy or not self._rows:
                return
            if not (self.rt.game.up() and not self.rt.game.busy):
                return
            rows = self._state_targets()
            if not rows:
                return
            start = self._state_cursor % len(rows)
            take = min(STATE_SLICE, len(rows))
            targets = (rows + rows)[start:start + take]
            self._state_cursor = (start + len(targets)) % len(rows)
            self._state_busy = True
            self._read_state(targets, auto=True)
        finally:
            self.rt.tick.arm("secret_state", STATE_MS, self._state_sweep)

    def _state_targets(self, hot: bool = False) -> list:
        """The rows a state read is about, readiest first.

        `hot=True` is the narrow set the unattended chains use: the very gate the standing
        order aims by (:meth:`_raidable`) — ready, or within :data:`AUTO_EARLY_MS` of
        maturing, and not a tile nobody can take (3/3, or one we have robbed). That is
        what the 3-second poll asks about and what arms it at all.

        `hot=False` — the default, and what a PRESS gets — is the WHOLE list (#1280).
        Every row on this tab is a tile that may have been emptied, looted out or taken
        off the map since it was found, and a state read that skips them is a list that
        can only be corrected by driving the map again.

        Readiest first either way, because when the read is cut short by a slow VM the
        rows worth having are the ones already at the front.

        Everything OFF this list is untouched by the read, which is the other half of the
        rule the tab is built on: a row nobody asked about cannot be dropped by an answer
        nobody got (:data:`THE_LIST_RULE`).
        """
        rows = [r for r in self._rows.values() if not hot or self._raidable(r)]
        return sorted(rows, key=lambda r: (not r.get("ready"),
                                           r.get("completed_at") or float("inf")))

    def _state_work(self, keys: list, tiles: list, auto: bool = False) -> None:
        """The round trips, off the Tk thread: the alliance table, then the tiles.

        WHAT THE WAITING COSTS, MEASURED (#1272). Every read here used to sit out a fixed
        settle — 1.1 s for the alliance table, 0.6 s for the probe, a bare `sleep(1.2)`
        for the replies and 1.0 s for the read-back — so a press could not answer in less
        than 3.9 s however fast the VM was, and it held the game lease for all of it,
        which is what made the OTHER buttons feel stuck too. The answer of a chunk is in
        the log ~30 ms after the call returns (`lua_eval.collect`), and each of these
        chunks ends by printing a line of its own, so the settle is now a DEADLINE with a
        sentinel to end it early: `VT_END` for the table, `detail_asked` for the probe,
        `DT_CONTROL` for the read-back. The replies from the server are the one wait that
        is real, and it is polled rather than slept through — as soon as every asked tile
        has an answer, the read is over.
        """
        import lua_actions
        live, seen, control = None, {}, False
        try:
            ev = self.rt.game.evaluator()
            # 1. The alliance table — the only thing that carries a LOOT COUNT.
            import steal_secret_task
            live = {str(t.uuid): t
                    for t in steal_secret_task._vm_all_alliance_tasks(ev)}
            if tiles:
                # 2. …and the per-tile answer for everything else. One chunk to ask, then
                #    read the replies back as they land.
                ev.run(lua_actions.secret_task_detail_probe(tiles), marker="ACT",
                       settle=0.6, sentinel="detail_asked")
                seen, control = self._read_details(ev, len(tiles))
        except Exception:                     # noqa: BLE001 — a failed read proves nothing
            live = None
        self.after(lambda: self._state_landed(keys, live, seen, control, auto))

    def _read_details(self, ev, asked: int) -> tuple:
        """Read the probe's replies back, stopping as soon as they have all landed.

        The server answers each `world.get.detail.new` on its own, so there IS a wait
        here — but it is a wait for an ANSWER, not a fixed sleep, and it used to be both:
        1.2 s of sleeping plus a 1.0 s settle, whatever had already arrived. Now the
        read-back is repeated on a short pause until every asked tile has a REAL answer,
        and out of the loop at :data:`DETAIL_WAIT_MS` whether they all do or not.

        A nought is not an answer to wait no longer on, and that is the trap this loop
        has to walk around: the chunk prints a `DT` line for every tile it was asked
        about whether the reply has arrived or not, and `uuid=0` means both «there is
        nothing on that tile» and «nothing has come back yet». So only a nonzero uuid
        ends the wait early; a tile still reading nought when the deadline passes is
        handed over as the nought it is, exactly as the old fixed sleep handed it over,
        and what it MEANS is decided by the control point in :meth:`_state_landed`.
        """
        import lua_actions
        deadline = time.monotonic() + DETAIL_WAIT_MS / 1000.0
        seen, control = {}, False
        while True:
            time.sleep(DETAIL_POLL_SEC)
            for ln in ev.run(lua_actions.secret_task_detail_read(), marker="ACT",
                             settle=1.0, sentinel="DT_CONTROL") or ():
                body = ln[4:] if ln.startswith("ACT ") else ln
                if body.startswith("DT_CONTROL"):
                    control = body.strip().endswith("ok=1")
                elif body.startswith("DT "):
                    f = dict(kv.split("=", 1) for kv in body[3:].split() if "=" in kv)
                    seen[int(f.get("i") or 0)] = int(f.get("uuid") or 0)
            answered = sum(1 for uuid in seen.values() if uuid)
            if answered >= asked or time.monotonic() >= deadline:
                return seen, control

    def _state_landed(self, keys, live, seen, control: bool, auto: bool = False) -> None:
        """Apply what came back, and say what it changed.

        `auto` marks the unattended pass (:meth:`_state_sweep`): it clears its own flag
        and stays quiet unless it actually changed something, because a line every thirty
        seconds saying «проверено 20 · обновлено 0» is a log nobody can read.

        WHAT IT CAN AND CANNOT REFRESH, said plainly because it was asked (#1272). The
        loot count lives in exactly two places: the client's own alliance table, which
        holds MY alliance's tasks and nothing else, and the map itself — the stealer list
        rides on the `world.get.block` tile and is decoded by the passive capture. The
        per-tile read used here carries neither (45 fields, and `reward` is its only
        list), and the game's own marker does not draw n/3 at all, so there is no UI path
        to follow to one. For a stranger's tile — which is most of this list — n/3 moves
        when a LAP re-reads the map with the monitor on, and this button confirms that
        the tile still exists. It does not pretend to more than that.

        THE TWO KINDS OF ABSENCE, KEPT APART (#1272). A row missing from the alliance
        table means nothing unless that table could have carried it (`_answerable`, and
        the rule that stopped the list being wiped every start-up). A tile the SERVER
        answered about with no detail — with the control point proving the answers were
        arriving — is the other thing entirely: there is nothing there, and the row goes.
        """
        if auto:
            self._state_busy = False
        else:
            self._vm_busy = False
        checked = len(keys)
        updated = gone = unconfirmed = 0
        for index, key in enumerate(keys, start=1):
            row = self._rows.get(key)
            if row is None:
                continue
            task = (live or {}).get(key)
            if task is not None:
                # The loot count, and the clocks that go with it — «сколько раз уже
                # ограбили», which is what the alliance table is for.
                if (row.get("loot_count") != task.loot_count
                        or row.get("expires_at") != task.expires_at
                        or row.get("completed_at") != task.completed_at):
                    updated += 1
                row["loot_count"] = task.loot_count
                row["expires_at"] = task.expires_at
                row["completed_at"] = task.completed_at
                row["seen_at"] = time.time()
                continue
            answer = seen.get(index)
            if answer is None:                       # the probe never ran for this one
                unconfirmed += 1
                continue
            if answer == int(row["uuid"]):
                # STILL THERE — and that is ALL this answer says. The per-tile read
                # carries no stealer list (45 fields, measured: `reward` is its only
                # list), so for a stranger's tile it cannot move n/3 and must not be
                # counted as if it had. «Обновлено» means a value changed; this is
                # «проверено», which the same line already reports.
                row["seen_at"] = time.time()
                continue
            if not control:
                # Nothing came back for the control either: the answers were not
                # arriving, and an absence proves nothing. Exactly the mistake #1272
                # spent a morning undoing.
                unconfirmed += 1
                continue
            if row.get("robbed"):                    # kept for sharing, as ever
                continue
            # `THE_LIST_RULE` clause 2 — asked about this tile, told there is nothing
            # there, and the control point proved the answers were arriving.
            self._rows.pop(key, None)
            gone += 1
        if not auto or updated or gone:
            self.say("secret", "log.secret.state_done", checked=checked, updated=updated,
                     gone=gone, unconfirmed=unconfirmed)
        self._render()
        self._update_status()
        self._persist_rows()

    def _sweep_once(self) -> None:
        """«Обойти карту» — and «Остановить» while one is walking (#1272).

        The ability is `actions/scan_map.md` and the panel only plays it — the waypoints,
        the timer that walks them and the height they are walked at all live in the
        scenario and its primitive (`CLAUDE.md`). What the tab decides is WHEN.

        IT DOES NOT EMPTY THE LIST. It did, for one commit, because that seemed to make
        the table one honest moment instead of a blend of two — and it cost the operator
        their finds, which is the third time this list has lost data and the third
        different reason. There is one rule now and it is above (:data:`THE_LIST_RULE`):
        a lap FILLS the list, like every other feed, and nothing about pressing a button
        makes a row stop existing.

        AND IT CAN BE STOPPED. A lap hands every waypoint to the game's own timer at once
        — there is nothing to call back — so «Остановить» bumps the run token those
        closures check (`lua_actions.fast_map_sweep_stop`) and the camera stays where it
        got to. Without it a lap at the wrong height is 88 seconds of a panel that looks
        hung, which is exactly what was reported.

        The lap only produces traffic; something has to be listening to it, which is the
        ★ monitor. Saying so is the difference between «nothing was found» and «nothing
        was written down».
        """
        if self._sweeping:
            self._sweep_stop()
            return
        import lua_actions
        height, step = lua_actions.zoom_level(self._zoom_level)
        if not (self.capture.running or self.ghost_capture.running):
            self.say("coord", "log.coord.sweep_unwatched")
        seconds = lua_actions.fast_sweep_seconds(step) + 2
        self.say("coord", "log.coord.sweeping",
                 level=self.t(f"coord.zoom.{self._zoom_level}"), secs=int(seconds))
        started = self.rt.play_async(
            "scan_map", {"zoom": height, "step": step}, tag="coord",
            on_start=lambda: self.post(self._sweep_began),
            on_done=self._sweep_ended)
        if not started:
            self._sweep_ended()

    def _sweep_began(self) -> None:
        """The lap is walking: the button becomes «Остановить» and says so."""
        self._sweeping = True
        self._retitle_sweep()

    def _sweep_ended(self) -> None:
        """…and back, whether it finished, was stopped, or never started."""
        self._sweeping = False
        self.post(self._retitle_sweep)

    def _sweep_stop(self) -> None:
        """Disown the waypoints still pending — the press that was missing."""
        self.say("coord", "log.coord.sweep_stopped")

        def work() -> None:
            try:
                import lua_actions
                self.rt.game.evaluator().run(lua_actions.fast_map_sweep_stop(),
                                             marker="ACT", settle=0.6)
            except Exception:                 # noqa: BLE001 — a stop is never fatal
                pass

        threading.Thread(target=work, daemon=True).start()
        self._sweep_ended()

    def _retitle_sweep(self) -> None:
        """One button, two words — «Обойти карту» / «Остановить»."""
        if self._sweep_btn is None:
            return
        try:
            self.tr(self._sweep_btn,
                    "coord.sweep_stop" if self._sweeping else "coord.sweep_now")
        except tk.TclError:
            pass

    def _jump(self, x: int, y: int, server) -> None:
        """The one way this tab walks the camera anywhere. Remembers where it went.

        ``server`` may be None — the runtime then jumps on whatever server the client is
        currently looking at, which is what an empty «Сервер» box means.

        NO HEIGHT TRAVELS WITH IT (#1272). Every coordinate jump in the panel lands at
        the tile view and that is decided inside `GameLink.jump`, not here — «это для
        ЛЮБЫХ переходов по координатам». This tab used to pass its «Зум» box in, so a
        coordinate clicked in a table arrived at a different height from the same
        coordinate clicked in the log, and the box that caused it looked like a display
        preference. The box is about the LAP now, and only the lap.
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
        self._assist_line = None
        self._refresh_autoloot_line()
        self._refresh_assist_line()

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

    def _assist_line_text(self) -> str:
        """«Автопомощь» in one line: what it would help with, and what it is doing."""
        return f"{self.autoassist.rule_text()} · {self.autoassist.state_text()}"

    def _refresh_assist_line(self) -> None:
        """Redraw the auto-help label, and only when its words have actually changed.

        Same shape as the auto-loot one directly above and for the same reason: the state
        moves on the watcher's thread, the countdown is what notices, and a `configure`
        per second per profile is the Tk traffic #1226 went looking for.
        """
        if self._assist_lbl is None:
            return
        line = self._assist_line_text()
        if line == self._assist_line:
            return
        self._assist_line = line
        try:
            self._assist_lbl.configure(text=line)
        except tk.TclError:
            pass

    def _on_autoassist_toggle(self) -> None:
        """«Автопомощь» was ticked or cleared: start/stop it (#1272)."""
        self.rt.settings.changed()
        self.autoassist.toggle()
        self._refresh_rule_hints()

    def _on_assist_level_change(self) -> None:
        """The help rule's own minimum was typed: keep its line true, remember it.

        Nothing is re-spawned — unlike «Автолут ★», this order has no sniffer of its own
        and re-reads the rule on every tick.
        """
        self.rt.settings.changed()
        self._refresh_rule_hints()

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
        self._merge(tasks, pending, source=SOURCE_VM)

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
        return self._abroad_only([t for t in tasks if t.starred])

    def _abroad_only(self, tasks) -> list:
        """Drop every tile on the account's OWN server — THE FEED'S OWN GATE (#1188).

        This list is the raid list, and a raid at home is forbidden outright: the game
        fines the player for it. `rob_candidates` refuses one too, and that was not
        enough, because a row that is on the list AT ALL is a row some path can reach.
        It was reachable: `on_show` fires `_prime_own_server` on a thread and
        `_snapshot` immediately after, so the first feed can land while the own server
        is still unknown — and everything that judges a row against home (the display
        rule, the standing order) reads «unknown» as «nothing is home». Live that showed
        up as home tiles appearing in the grid for about a second and then vanishing as
        the priming caught up, and one second is long enough for a 2-second poll to
        take one.

        So the gate moved to where the rows COME IN, ahead of the model rather than in
        front of each consumer of it. Both feeds run off the Tk thread, so asking the
        game here costs the window nothing — and `own_server()` reads live when the
        cache is cold, which is what removes the race rather than narrowing it.

        AN UNREADABLE OWN SERVER ADMITS NOTHING. «I cannot tell home from abroad» must
        never come out as «none of it is home», which is the exact shape of the bug
        above. The list stays empty and says why, once.
        """
        mine = self.own_server()
        if not mine:
            if not self._warned_no_own_feed:
                self._warned_no_own_feed = True
                self.say("secret", "log.secret.no_own_server_feed")
            return []
        self._warned_no_own_feed = False
        return [t for t in tasks if int(getattr(t, "server_id", 0) or 0) != mine]

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
        return self._abroad_only([t for t in tasks if t.starred])

    def _answerable(self, row, answered: bool, source: str) -> bool:
        """May THIS read take THIS row away? (#1272)

        The question nothing was asking, and the answer that was assumed to be «yes».
        Two rules, and the first is the one that cost the operator a map lap:

        * **A read may only testify about its own source.** The VM read walks my
          alliance's own task table; a tile the capture found on the far side of the map
          is not in it and never was, so its absence there says nothing whatever. Only a
          row this same source put on the list may be reconciled against it.
        * **An empty answer testifies about nothing at all.** A read that came back with
          no rows is «I have nothing to say», not «none of them exists» — and on an
          account whose whole alliance sits at home it is what the raid read returns
          every single time, because the home server is dropped on the way in.

        Everything else about how a row leaves is untouched: it expires on its own clock,
        it goes when the server confirms we robbed it, and a read that CAN see it and
        does not carry it still drops it.
        """
        if not answered:
            return False
        return row.get("source", SOURCE_WIRE) == source

    def _merge(self, tasks, verify: "set | None" = None,
               source: str = SOURCE_WIRE) -> None:
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
        # A TILE WITH NO FINISH TIME NEVER ENTERS THE MODEL (#1272). The wire decoder
        # reads it off the tile's `f3` and a tile that does not carry one comes through
        # as `None` (`lastwar_proto.tasks_from_blocks`), so the list grew rows that drew
        # «готово через —» for ever: `ready` is «completed_at is set and past», so such a
        # row can never mature, can never be robbed, can never expire on its own clock
        # and can never be worth going to. It is not a target with a missing field — it
        # is not a target.
        #
        # Refused HERE, at the model's one door, rather than hidden by the table. Both
        # feeds land in this method (`_wire_landed` / `_vm_landed`) and so will the next
        # one, and everything downstream — the standing order, the phone, the checkpoint
        # — reads the model rather than the table. The VM feed never produced one anyway
        # (`secret_task_all_alliance` demands `done > 0`); it is the pcap that can.
        tasks = [t for t in tasks if t.completed_at]
        incoming = {str(t.uuid): t for t in tasks}
        # Whether the read said ANYTHING, measured before the loop starts popping matches
        # out of `incoming` — otherwise a read that carried exactly the rows it confirmed
        # would look empty by the time the last one was checked.
        answered = bool(incoming)
        if verify:
            for key in verify:
                row = self._rows.get(key)
                if row is None:                    # already gone some other way
                    continue
                task = incoming.pop(key, None)
                if task is None:
                    if not self._answerable(row, answered, source):
                        continue
                    # …and we never drop one we robbed (#1272). Same exception, same
                    # reason as the ready-row poll's: our own robbery is what most often
                    # takes a tile out of the read, and the row is kept for the share it
                    # is still good for. Its `expires_at` still ends it on the next tick.
                    if row.get("robbed"):
                        continue
                    # `THE_LIST_RULE` clause 2 — a read that COULD have carried this row
                    # (`_answerable`, just above) and did not.
                    self._rows.pop(key, None)
                    continue
                row["expires_at"] = task.expires_at
                row["completed_at"] = task.completed_at
                row["loot_count"] = task.loot_count
        for key, t in incoming.items():
            row = self._rows.get(key)
            if row is not None:
                # A ROW ALREADY HERE IS REFRESHED, NOT SKIPPED (#1272). It used to be
                # skipped outright — «a rescan only ADDS» — and that threw away the one
                # reading that carries how many times a STRANGER's tile has been robbed.
                # Live report: «обновляй не обновляй — кол-во ограблений не меняется, и
                # полностью ограбленные не исчезают». Both were this line: the count
                # never rose, so `_spent` never became true and a 3/3 tile stayed on the
                # list looking raidable.
                #
                # THE COUNT ONLY EVER RISES, which is what makes this safe without a
                # timestamp. A tile is robbed 0 -> 1 -> 2 -> 3 and never un-robbed, so
                # `max` takes a fresher reading and cannot be fooled by a stale record
                # the capture happens to resend — which is what the old rule was guarding
                # against. Everything the PANEL knows and the wire does not — the robbed
                # mark, the share mark, where the row came from — is left alone.
                row["loot_count"] = max(int(row.get("loot_count") or 0),
                                        int(t.loot_count or 0))
                if row.get("completed_at") is None:
                    row["completed_at"] = t.completed_at
                if row.get("expires_at") is None:
                    row["expires_at"] = t.expires_at
                row["seen_at"] = time.time()
                continue
            if key in self._collected:
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
                # …and WHICH FEED put it here (#1272), which is what decides whose
                # absence is allowed to take it away again. See `_answerable`.
                "source": source,
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
             "starred": bool(r.get("starred", True)),
             # …AND WHICH FEED FOUND IT (#1272). Without it every restored row came back
             # as «the VM read's», and the first VM read — which on a home-bound alliance
             # carries nothing at all — deleted the lot.
             "source": r.get("source", SOURCE_WIRE),
             # …AND WHETHER WE ROBBED IT (#1272). A robbed row is kept on the list so it
             # can still be shared, and a restart that forgot the mark would put back a
             # row offering «Собрать» on a tile the server has already refused us once.
             "robbed": bool(r.get("robbed"))}
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
            # …and a row with no finish time is not restored either (#1272). It cannot
            # mature, so it would sit there drawing «готово через —» until the panel was
            # shut. Only a checkpoint written before the gate above can hold one.
            if not rec.get("completed_at"):
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
                # A checkpoint written before #1272 says nothing about where its rows
                # came from, and the safe answer is the CAPTURE's: a wire row is never
                # verified away by a read that cannot see it, which is exactly the
                # mistake this defaults against.
                "source": rec.get("source") or SOURCE_WIRE,
                # …and a row robbed before the restart comes back robbed (#1272), which
                # is what keeps «Собрать» off it. The uuid goes into `_collected` with
                # it: that set is what a later capture is checked against, so without it
                # a feed could re-add an unmarked copy the moment this row expired.
                "robbed": bool(rec.get("robbed")),
                "timer": tk_stringvar(self.rt.root), "ready": False, "soon": False,
            }
            if rec.get("robbed"):
                self._collected.add(key)
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
            # …and the robbed mark beside it (#1272), because a robbed row STAYS on the
            # list now and the phone shows the same list. Without the mark the screen
            # would carry a «готово к сбору» tile that is not a target any more, which is
            # precisely the misreading the window's mark exists to prevent. There was
            # never a «Собрать» here to take away — the phone has read this list and
            # pressed nothing on it since #1188 — so the mirroring is the mark alone.
            robbed = bool(row.get("robbed"))
            if robbed:
                facts.append({"label": "secrettasks.robbed_mark", "value": ""})
            done, exp = row.get("completed_at"), row.get("expires_at")
            # A spent tile says so instead of saying «готово»: it is on the list only
            # because the box asked for it, and «ready» on a row nobody can rob is the
            # single most misleading word the screen could carry.
            spent = self._spent(row)
            text = coords.fmt(row.get("x"), row.get("y"), row.get("server"))
            if robbed:
                text = "%s %s" % (grid.ROBBED_GLYPH, text)
            if row.get("shared"):
                text = "%s %s" % (grid.SHARED_GLYPH, text)
            items.append({
                "text": text,
                "facts": facts,
                # Ready: how long is left to take it. Not ready: when it becomes one.
                "until": ((exp if row.get("ready") else done) or 0) / 1000.0 or None,
                # Robbed outranks both other pills: «готово» on a tile we have taken is
                # the one word the phone must not say, and «исчерпана» is about the tile
                # while this is about us.
                # …and the ten-second window the window's «Собрать» appears in (#1272).
                # The phone gets the READING and no button — the robbery on this tab is
                # still a hand-driven press the web may not carry (#1188) — but it says
                # so at the same instant the button appears, which is what «то же на
                # телефоне» can honestly mean here.
                "pill": ("secrettasks.robbed_mark" if robbed
                         else "secrettasks.spent" if spent
                         else "secrettasks.ready" if row.get("ready")
                         else "secrettasks.collect_soon"
                         if self._collectable(row) else None),
            })
        hidden = self._hidden_at_home()
        # What «Автолут ★» is doing, in the same words the window puts under the
        # checkbox. It is the reading somebody away from the machine most needs: the
        # tiles say what is on the map, this says whether anything is going to be taken
        # — and «nothing, the day's five are spent» is not a thing to guess at (#1227).
        # It stays the card DIRECTLY ABOVE the ★ one, which is where the window now
        # draws it too: inside the ★ page, over the list it robs (#1271). A screen
        # scrolls where a window switches pages, so the adjacency is the whole of the
        # mirroring — and there is still no button here. The phone READS the standing
        # order; starting a robbery from it stays forbidden (#1188).
        state_key, state_datum = self.autoloot.state()
        low = self.autoloot.level_min()
        # …and the same pair for the other standing order (#1272), read here so the card
        # below is a dictionary walk like everything else on this screen.
        assist_state, assist_datum = self.autoassist.state()
        assist_low = self.autoassist.level_min()
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
                           # How many are on the card, and how many the boxes are
                           # holding back (#1272) — with the home-server rule named
                           # separately, because it is the one most easily forgotten.
                           "rows": (self._count_rows()
                                    + ([{"label": "secrettasks.filter.hide_own",
                                         "value": str(hidden)}] if hidden else [])),
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
                          # …and «Автопомощь» directly above the list it helps, the way
                          # «Автолут ★» sits above the ★ one (#1272). A card of its own
                          # rather than rows on the alliance card: it is a standing order
                          # with a budget, not a filter, and the phone is where somebody
                          # checks whether today's five have gone.
                          {"title": "autoassist.frame",
                           "rows": [{"label": "autoassist.level_min",
                                     "value": (str(assist_low) if assist_low is not None
                                               else self.t("autoassist.any_level"))},
                                    {"label": assist_state, "value": assist_datum}],
                           # A press the phone MAY make: the whole ability is
                           # `actions/assist_secret_task.md` and nothing spawns a tool
                           # first, so there is no hand-driven half to copy out of the
                           # house (`CLAUDE.md`, #1188). It turns the standing order on
                           # and off — the window's checkbox, in the phone's idiom.
                           "actions": [{"id": "autoassist",
                                        "label": ("autoassist.off"
                                                  if self.autoassist_var.get()
                                                  else "autoassist.on")}]},
                          {"title": "secrettasks.alliance",
                           "items": self.alliance.web_items(),
                           "rows": self._count_rows(self.alliance),
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
                           "rows": self.ghost.web_rows() + self._count_rows(self.ghost),
                           "items": self.ghost.web_items(),
                           "empty": "secrettasks.ghost.empty",
                           "actions": [self._ghost_monitor_action()]},
                          {"title": "secrettasks.ghost.allies",
                           "items": self.ghost_allies.web_items(),
                           "rows": self._count_rows(self.ghost_allies),
                           "empty": "secrettasks.ghost.allies.empty"},
                          # …and the sniffer's own card, where its tiles land (#1251).
                          {"title": "secrettasks.ghost.map",
                           "items": self.ghost_map.web_items(),
                           "rows": self._count_rows(self.ghost_map),
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
                            # «Обновить состояние» (#1272) — the same press the window
                            # grew, and one the phone MAY make: it re-reads what is
                            # already on the list and robs nothing. The robbery is still
                            # the one press this screen does not carry (#1188).
                            {"id": "refresh_state", "label": "coord.refresh_state"},
                            {"id": "zoom",
                             "label": f"coord.zoom.{self._zoom_level}"},
                            {"id": "sweep_now", "label": "coord.sweep_now"}]}

    def _count_rows(self, page=None) -> list:
        """One card's «Показано / Скрыто» pair, for the phone (#1272).

        The same two numbers the window puts on the notebook tab, said the way a card
        says facts: a bare label and a value. «Скрыто» only appears when something IS
        hidden — a zero beside it would be noise — but «Показано» is always there,
        including at zero, which is the case the counter exists for.
        """
        shown, hidden = page.counts() if page is not None else self.counts()
        rows = [{"label": "secrettasks.shown_label", "value": str(shown)}]
        if hidden:
            rows.append({"label": "secrettasks.hidden_label", "value": str(hidden)})
        return rows

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
        if action == "autoassist":
            # The window's own checkbox, flipped from the phone (#1272). Through the same
            # handler a finger goes through, so the two front-ends cannot end up with the
            # box saying one thing and the watcher doing another.
            self.post(self._toggle_autoassist)
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
        if action == "refresh_state":
            self.post(self.refresh_state)
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

    def _toggle_autoassist(self) -> None:
        """Flip «Автопомощь» from the phone, on the Tk thread (#1272)."""
        self.autoassist_var.set(not self.autoassist_var.get())
        self._on_autoassist_toggle()

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
        """Bring the table to the current rows — by CHANGING it, not by refilling it.

        Called on a merge / collect / clear / sort, NOT every second — the countdown is
        written cell by cell by :meth:`_paint_timers`.

        IT IS A DIFF NOW (#1272), and the complaint that made it one was «грид стирается
        и потом снова обновляется». The old draw deleted every row and inserted every row
        back, so a state read blanked the table in front of whoever was reading it, moved
        the scroll and took the selection off the row their hand was on. `grid.sync_tree`
        writes only the cells whose text changed, inserts only what is new and moves only
        what has re-sorted; a poll that confirms what was already there now writes nothing
        at all. The selection needs no saving and restoring either — the rows it is on are
        never deleted any more.
        """
        tree = self._tree
        if tree is None:
            return
        # A tile merged a moment ago has no countdown written yet, and a cell is drawn
        # once — unlike the old labels, which followed their variable. So the clocks are
        # brought up to date first and the row is drawn with the state it really is in.
        self._refresh_timers()
        rows = self._sorted_rows(self._visible_rows())
        grid.sync_tree(tree, rows, self._row_values, grid.row_tag)
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

        The rule, in order: the tile is raidable (ready, not looted out, **and not one we
        have already robbed** — all three are :meth:`_raidable`, the STRICT gate, not the
        hand's :meth:`_collectable` with its ten-second window), it wears a star
        (every row of this list does, by construction), its level is at or above
        «минимальный уровень», and **it is on somebody else's server**. Robbed by hand
        this session (`_collected`) is excluded twice over, and deliberately so: the row
        now STAYS on the list once it has been robbed (#1272), so the exclusion has to
        live in the model rather than in the fact that the row went away. The set catches
        it while the flag catches the row, and `_collectable` is where both are asked.

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
                and self._raidable(row)
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

    def _takeable(self, row) -> bool:
        """The half of the gate both answers share: nothing here can be robbed at all.

        A 3/3 tile has no slot for anybody, so a press on it is one the server refuses
        (#1227), and one WE have robbed is refused for the same reason a second time
        (#1272) — it is on screen only so that it can still be shared. Neither the hand
        nor the standing order may aim at either.
        """
        return not self._spent(row) and not row.get("robbed")

    def _raidable(self, row) -> bool:
        """What «Автолут ★» aims at — ready, or about to be (#1272).

        NOT the same window as the hand's, and that is not an oversight to be tidied
        away. See :data:`AUTO_EARLY_MS` beside :data:`EARLY_MS` for why one is two
        seconds and the other ten; the short version is that ten seconds of a machine
        pressing seven times a second is seventy round trips a tile cannot answer, and a
        person needs those ten seconds to get a finger onto the button.

        Everything else about the gate is the strict one and stays here: a looted-out
        tile and one we have already robbed are not targets (`_takeable`), and the home
        server is excluded where the rows come in and again in `rob_candidates`. The
        early window widens WHEN, never WHAT.
        """
        if not self._takeable(row):
            return False
        if row.get("ready"):
            return True
        import game_clock
        left = int(row["completed_at"] or 0) - game_clock.now_ms()
        return 0 < left <= AUTO_EARLY_MS

    def _collectable(self, row) -> bool:
        """Whether «Собрать» is offered on this row — THE HAND'S gate (#1272).

        Ten seconds EARLY, and that is the point of it. A raidable star is taken in the
        first moment it exists — «там счёт может идти на микросекунды, потому что много
        желающих уже кликают» — and a button that appears at the instant of readiness is
        a button nobody can be holding a finger over. So it appears while the tile is
        still counting down, inside :data:`EARLY_MS` of maturing.

        The press that lands in that window is not thrown at the server early: it waits
        out the remainder on its own worker and sends at the moment the tile matures
        (:meth:`_collect`). That is what makes the early button worth having rather than
        a lie — a premature `hero.dispatch.steal` is answered with a tip and nothing
        else, so pressing early without the wait would look like a robbery and be none.

        THE ONE PLACE THAT ANSWER IS GIVEN. The action cell, the cursor over it, the
        double click, the strip's «Собрать» and the right-click menu of every page all
        come through here (`TaskGrid.collectable`), so a rule added here is a rule none
        of them can be missing. The standing order is deliberately NOT among them — it
        asks :meth:`_raidable`, one line up, and the split is the whole of «окно только
        для человека».
        """
        if not self._takeable(row):
            return False
        if row.get("ready"):
            return True
        # …and the window. `completed_at` is always set on this list (a tile without one
        # never enters the model, #1272), and the clock is the GAME's, like every other
        # judgement on this tab (#1227) — a window measured against a machine eleven
        # seconds out is a window that opens at the wrong moment.
        import game_clock
        left = int(row["completed_at"] or 0) - game_clock.now_ms()
        return 0 < left <= EARLY_MS

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

        A tile WE robbed is shown whatever «Показывать исчерпанные» says (#1272). It is
        on the list for a different reason from the rest of it — not «go and rob this»
        but «tell the alliance about this» — and the moment a robbery pushes the tile to
        3/3 the spent rule would take it away again, which is the disappearance this
        change exists to stop. It carries the robbed mark and offers no «Собрать», so it
        cannot be mistaken for a target.
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
                and (show_spent or not self._spent(r) or r.get("robbed"))
                and not (mine and int(r["server"] or 0) == mine)]

    def counts(self) -> tuple:
        """`(shown, hidden)` for the ★ page — the same pair every grid answers (#1272).

        «Hidden» is everything the page's own rules keep off the table, not just the
        home-server one: the level range and «Показывать исчерпанные» hide rows too, and
        a table that went blank because of any of them looks the same from the outside.
        """
        shown = len(self._visible_rows())
        return shown, max(len(self._rows) - shown, 0)

    def _update_status(self) -> None:
        """«секреток: N · скрыто фильтрами: M», on the ★ page and on its notebook tab.

        A box that empties the table without saying so is indistinguishable from a tab
        that read nothing (#1251): one live account has every star it can see on its
        own server, and the whole list going blank on first open is exactly what that
        looks like. The count says which of the two it is — and it is said at zero as
        well, which is the case it exists for.

        The home-server rule keeps a line of its own beside it: it is the one hiding
        rule a person is most likely to have forgotten is on.
        """
        shown, hidden = self.counts()
        line = grid.count_text(self.t, shown, hidden)
        at_home = self._hidden_at_home()
        if at_home:
            line = "%s · %s" % (line, self.t("secrettasks.hidden_own", n=at_home))
        self._status_var.set(line)
        self.sync_page_counts()

    def sync_page_counts(self) -> None:
        """Put each page's count on its own notebook tab (#1272).

        THE NUMBER GOES IN THE LABEL, because that is what «видно, не открывая её» means
        and because a `ttk.Notebook` label is a plain string this tab already rewrites on
        every language change — so it costs one `book.tab(…, text=…)` per page and no new
        widget at all. Five lists, five numbers, readable at a glance.
        """
        book = self._pages
        if book is None:
            return
        try:
            for index, key in enumerate(self._page_keys):
                book.tab(index, text=self._page_label(index, key))
        except tk.TclError:
            return

    def _page_label(self, index: int, key: str) -> str:
        """One notebook tab's words: its name, and what it is holding right now."""
        page = {1: self.alliance, 2: self.ghost, 3: self.ghost_allies,
                4: self.ghost_map}.get(index)
        try:
            shown, hidden = page.counts() if page is not None else self.counts()
        except Exception:                     # noqa: BLE001 — a label is never a failure
            return self.t(key)
        if not (shown or hidden):
            return self.t(key)
        return "%s · %d%s" % (self.t(key), shown, "+%d" % hidden if hidden else "")

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

    def _maybe_start_live(self) -> None:
        """Start the fast repaint if anything is counting down and it is not running.

        Gated rather than unconditional, and for the reason the ready-row poll is gated:
        four wake-ups a second times every open profile is a real share of the one event
        loop they share (#1226), and a tab with an empty list has nothing to draw. It
        stops itself the moment the last countdown goes.
        """
        if self._living:
            return
        if self._has_countdown():
            self._living = True
            self.rt.tick.arm("secret_live", LIVE_MS, self._live_tick)

    def _has_countdown(self) -> bool:
        """Is there a row anywhere on this tab with a clock still running?"""
        return (grid.has_countdown(self._rows)
                or any(page.has_countdown() for page in self._grid_pages()))

    def _live_tick(self) -> None:
        """Redraw the countdowns — every table on the tab, four times a second (#1272).

        ONE CHAIN FOR THE TAB, like the second-by-second one: five tables counting down
        on five chains of their own would be five wake-ups where one does.

        It is a drawing pass and nothing else. `grid.repaint_countdowns` says what that
        buys and what it costs; the short version is that everything able to change a row
        happens in :meth:`_tick`, once a second, exactly as it did before.
        """
        try:
            grid.repaint_countdowns(self._tree, self._rows, self.t)
            for page in self._grid_pages():
                page.repaint()
        finally:
            if self._has_countdown():
                self.rt.tick.arm("secret_live", LIVE_MS, self._live_tick)
            else:
                self._living = False
        # NOTHING ELSE BELONGS IN HERE. Two lines of `__init__` were pasted below this
        # `finally` — `_sweeping = False` and `_sweep_btn = None` — and they ran four
        # times a second: «Обойти карту» could never stay «Остановить», the button
        # reference was dropped so `_retitle_sweep` had nothing to rename, and the second
        # press started a second lap that the game claim then refused as «занято».

    def _tick(self) -> None:
        """Every second: rewrite each row's timer, drop the expired, flip the matured.

        A tile past `expires_at` is off the map and can no longer be robbed, so it comes
        off the list on its own. A tile whose `completed_at` passes turns raidable: the
        tick repaints it green and wakes the poll. Only a state change repaints.
        """
        try:
            expired, changed = self._refresh_timers()
            for key in expired:
                # `THE_LIST_RULE` clause 1 — the task is over, by the game's own clock.
                # The ONLY removal that needs no answer from anybody.
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
            self._refresh_assist_line()
            self._maybe_start_poll()
            # …and the drawing chain beside it, which is what makes a raidable tile's
            # countdown move four times a second instead of once (#1272).
            self._maybe_start_live()
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
        """Start the slow poll if a row is raidable and it is not already running."""
        if self._polling:
            return
        if self._state_targets(hot=True):
            self._polling = True
            self.rt.tick.arm("secret_poll", POLL_MS, self._poll_tick)

    def _poll_tick(self) -> None:
        """Re-read the game for the raidable rows; reschedule while any remain.

        Off the Tk thread (a daemon round trip), so this only gathers the keys and hands
        the read to a worker. Stops rescheduling the moment nothing is raidable — an idle
        tab must not keep waking the daemon.

        THE HOT ROWS ONLY: ready, or inside the standing order's early window. It used to
        be `ready` alone, which is the one row set that is provably too late — the
        two-and-a-half seconds before a tile matures are exactly when its loot count is
        worth knowing. The REST of the list is re-checked by `_state_sweep`, on its own
        slower clock and with the per-tile read this poll does not make (#1280).
        """
        keys = [str(r["uuid"]) for r in self._state_targets(hot=True)]
        if not keys:
            self._polling = False
            return
        threading.Thread(target=self._poll_work, args=(keys,), daemon=True).start()
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

        A ROW WE ROBBED IS NOT DROPPED HERE (#1272), and the exception matters more than
        it looks. Our own robbery is the very thing most likely to fill the tile's last
        slot, so the read that follows it thirty seconds later is exactly the read that
        stops carrying it — and the row would vanish anyway, half a minute after the
        change that was made to keep it. It is kept for what is left of it: a raid worth
        telling the alliance about. Its own clock still ends it — `refresh_timers` drops
        every row at `expires_at`, robbed or not — so this is a stay of execution and not
        a row that lives for ever.

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
                # THE SAME READ, THE SAME SCOPE, THE SAME RULE (#1272). This poll reads
                # my alliance's own task table, so it can no more testify about a tile
                # the capture found across the map than the start-up snapshot could — and
                # it was dropping them every thirty seconds, quietly, for the whole
                # session. `_answerable` is the one place that question is answered.
                if not self._answerable(row, bool(live), SOURCE_VM):
                    continue
                if row.get("robbed"):
                    continue
                # `THE_LIST_RULE` clause 2 — same gate, same reasoning, on the poll's
                # own thirty-times-slower clock.
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
        """Rob one tile — by playing `actions/steal_secret_task.md` over it (#1272).

        THE HAND AND THE STANDING ORDER PRESS THE SAME WAY NOW. This used to build its
        own `hero.dispatch.steal` and send it once, which is the last hand-driven press
        this tab had; it is one call into `rt.actions` and the queue travels as an
        argument. What that buys is not tidiness: the recipe SPAMS. It presses again and
        again, as fast as the channel allows, and stops the moment the SERVER confirms —
        which is what a race decided in fractions of a second needs, and what a single
        send from here could never be.

        A press inside the ten-second window holds only the part of it the spam cannot
        reach. Pressing early is free — the server answers «ещё не готово», the daily
        counter does not move and nothing is spent — but it is not free of a round trip,
        so the worker sleeps until the tile is `AUTO_EARLY_MS` from maturing and lets the
        recipe do the rest. At most `EARLY_MS` of sleep, by construction: that is the
        widest the button is ever offered in.

        The sleep is on the worker and not on a Tk timer: this method already ran its
        round trip on a thread, the wait is bounded, and the Tk thread is the one thing on
        this panel that must never be asked to wait for anything (#1226).

        SUCCESS IS THE SERVER'S ANSWER, NOT THE SEND. `steal_taken` is the recipe's own
        confirmation read — the daily counter having moved — and it is what `_collect_done`
        is given. A `steal_sent` line proves a frame left the client and nothing more.

        ONE PRESS AT A TIME PER TILE. The row goes on offering «Собрать» while the wait
        runs — it is still counting down, and the gate has no idea a press is in flight —
        so a second press would arm a second run at the same instant. `_pressing` is what
        makes the extra presses free.
        """
        key = str(row["uuid"])
        if key in self._pressing:
            return
        self._pressing.add(key)
        # Read here, on the Tk thread, from the row the person actually clicked: by the
        # time the worker wakes the row may have been refreshed under it.
        import game_clock
        left = int(row["completed_at"] or 0) - game_clock.now_ms()
        hold = min(max(left - AUTO_EARLY_MS, 0), EARLY_MS) / 1000.0
        if hold:
            self.say("secret", "log.secret.collect_armed",
                     secs=max(1, int(round(hold))))
        queue = "{uuid=%d,server=%d}" % (int(row["uuid"]), int(row["server"] or 0))

        def work():
            taken = False
            try:
                if hold:
                    time.sleep(hold)

                def put(msg) -> None:
                    nonlocal taken
                    line = str(msg)
                    self.rt.put(f"[secret] {line}")
                    if TAKEN_MARK in line:
                        taken = True
                    # …and the tile the server says is gone comes off the list, whoever
                    # found it (#1272). Pressed by hand or by the standing order, one
                    # answer, one place that acts on it.
                    for uuid, how in DONE_LINE.findall(line):
                        if how == "gone":
                            self.after(lambda u=uuid: self._drop_gone(u))

                self.rt.actions.play("steal_secret_task", {"queue": queue},
                                     on_event=put)
            except Exception:                 # noqa: BLE001
                taken = False
            self.after(lambda: self._collect_done(key, taken))

        threading.Thread(target=work, daemon=True).start()

    def _drop_gone(self, key: str) -> None:
        """The server said this tile is not there: take the row off the list (#1272).

        THE ONE ABSENCE THAT IS EVIDENCE. `_answerable` refuses to delete a row for
        missing from a read that could not see it, and that rule stands — it is what
        stopped the list being wiped every start-up. This is the other case entirely: not
        «it was not in the answer» but «the answer was about this tile, and it said there
        is nothing there». «Задание уже взято», «больше не доступно», «срок истёк».

        A row we robbed OURSELVES is kept, marked, exactly as before: it is on the list
        so that it can still be shared, and our own robbery is the likeliest reason the
        server would now call it taken.
        """
        row = self._rows.get(str(key))
        if row is None or row.get("robbed"):
            return
        # `THE_LIST_RULE` clause 2 — the server answered about THIS tile and said it is
        # not there.
        self._rows.pop(str(key), None)
        self.say("secret", "log.secret.gone")
        self._render()
        self._update_status()
        self._persist_rows()

    def _collect_done(self, key: str, ok: bool) -> None:
        """A robbery came back: MARK the row, never remove it (#1272).

        It used to be popped off the list, and that threw away the half of the tile that
        was still worth something. A raid worth one of the day's five is precisely the
        raid worth telling the alliance about — «хочу потом поделиться этой секреткой» —
        and «Поделиться» needs a row under the cursor. So the row stays, wearing the
        robbed mark, with its coordinate still clickable and its share menu still there;
        what goes is «Собрать», through :meth:`_collectable`, because there is nothing
        left here for US to take.

        `_collected` is kept beside the flag rather than replaced by it. They answer
        different questions: the flag is «this row has been robbed» and travels with the
        row (onto the screen, into the checkpoint), while the set is «this uuid was
        robbed this session» and outlives the row — it is what stops a later capture
        re-adding an unmarked copy of a tile that has since dropped off the list.
        """
        self._pressing.discard(key)
        if ok:
            self._collected.add(key)
            row = self._rows.get(key)
            if row is not None:
                row["robbed"] = True
            # The same tile can be on both tables — one robbery, so both are marked.
            self.alliance.mark_robbed(key)
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

        THE ONE WAY TO EMPTY THIS LIST, and it stays that way (`THE_LIST_RULE`). Nothing
        else may do it — not a lap, not a read, not a restart — because everything else
        is the panel deciding on the operator's behalf that what they found is no longer
        worth keeping, and it has been wrong about that three times.
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
