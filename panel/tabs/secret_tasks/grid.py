"""The table every secret-task list on this tab is drawn as, and its arithmetic.

The tab has THREE grids now (#1251) and they are deliberately the same table three
times: the same columns in the same order, the same countdown in the state cell, the
same amber / yellow / green a row is painted in, the same click on a coordinate that
walks the camera. What differs is only what is IN each of them — the ★ list keeps the
starred raid targets the wire feed and the VM agree on, the alliance one mirrors the
game's own alliance table whole (stars and plain tiles alike), and the ghost one holds
the weekly «Операция Призрак» squads.

They are PAGES of a notebook rather than panes of a splitter (#1251): three tables
sharing one height by dragging a sash is three tables nobody can read, and which of
them is being looked at is a question with one answer at a time.

So everything that is about the TABLE rather than about any one list lives here: the
column set, the colours, the sort keys, the per-second countdown, the "which cell is
under the pointer" question — and :class:`TaskGrid`, the framed page the alliance and
ghost lists both are. The helpers stay plain functions taking the rows and the
translator, because that is what makes them testable without a Tk root, and every one
of them was tested that way.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ...widgets import NumericEntry, tk_stringvar

# The star glyph in front of a row and the icons for the two row states: a tile still
# counting down to raidability, and one that is ready to loot now.
STAR_GLYPH = "⭐"
TYPE_GLYPH = "🗡️"
READY_GLYPH = "✅"

# The tile has already been forwarded to the alliance — from this panel or by somebody
# pressing share in the game itself (#1245). In front of the coordinate, where the eye
# lands first: the question it answers is «have they been shown this one already?», and
# it has to be answerable without reading the whole row. The words are in the state
# cell beside it, because a glyph on its own is a rebus.
SHARED_GLYPH = "📣"

# WE HAVE ROBBED THIS TILE, AND IT STAYS ON THE LIST (#1272). A robbed row used to be
# taken off the table outright, which threw away the one thing still worth having: the
# tile is a raid worth TELLING the alliance about, and «Поделиться» needs a row to be
# pressed on. So the robbery marks instead of removing — the glyph in front of the
# coordinate the way the share mark is, the words in the state cell beside it — and
# what goes away is «Собрать», because there is nothing left here for US to take.
ROBBED_GLYPH = "💰"

# The amber the countdown is drawn in, and the green a ready row switches to.
TIMER_COLOR = "#e0a84f"
READY_COLOR = "#4fe08a"

# A row under ten minutes from the moment it needs attention — either about to become
# raidable, or about to expire while still raidable — turns this yellow instead, so it
# stands out from the rest of a list that is otherwise always shown in full (#1241).
SOON_COLOR = "#e0d84f"
SOON_MS = 10 * 60_000

# The rarity the game paints a dispatch task in, read off its own config row
# (`lw_dispatch_tasks.color`) rather than guessed from the cfgId. Live on 200 alliance
# tasks: family 3 -> 3, family 4 -> 4, families 5 and 6 -> 5. The top of that ramp is
# what the game calls UR, which is the filter «UR» on the alliance page (#1251).
#
# A record whose config the client has not loaded carries no colour at all (0) and is
# judged by its cfgId family instead — the same fallback `alliance_roster` keeps for
# the level and the star. Families "5000"/"6000" are the two UR ones.
UR_COLOUR = 5
UR_FAMILIES = frozenset({"5000", "6000"})


def is_ur(row) -> bool:
    """Whether the game draws this task at its top rarity — «UR».

    The config's own `color` when the client has it, the cfgId family when it does not.
    A row with neither is not called UR: a filter that answers «yes» when it does not
    know is a filter that hides nothing while claiming to.
    """
    colour = int(row.get("colour") or 0)
    if colour:
        return colour >= UR_COLOUR
    cfg = str(row.get("cfg_id") or "")
    return len(cfg) >= 5 and cfg[:-4] in UR_FAMILIES

# The table's columns: (id, locale key of the heading, width in px, anchor, stretch).
# The state column is the one that takes the slack — it carries the longest sentence
# («готово к сбору · истекает через 1:02:03») and the one that varies most by language.
# The server has a column of its own rather than a `#534` glued to the coordinate: it is
# what tells a neighbour's tile from a stranger's at a glance, and it is what «не грабить
# на своём сервере» is about.
COLUMNS = (
    # Who dispatched the task. Filled for the alliance table below, where the whole
    # question is «which of my alliancemates is running what» (#1244), and empty in the
    # table above — a tile found on the wire or read off the raid list carries no name,
    # and an empty cell is the honest way to say so.
    ("owner", "secrettasks.col.owner", 140, "w", False),
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

#: How each column orders. `state` sorts by "how soon this row wants attention" —
#: the ready ones first, then the shortest countdown — which is what the eye is
#: after, rather than the alphabet of a translated sentence. The action column is
#: not in here: a button is not an order, so its heading does not sort.
SORT_KEYS = {
    "owner": lambda r: (r.get("owner_name") or "").lower(),
    "coords": lambda r: (int(r["x"] or 0), int(r["y"] or 0)),
    "server": lambda r: int(r["server"] or 0),
    "lvl": lambda r: int(r["level"] or 0),
    "state": lambda r: (0 if r.get("ready") else 1,
                        (r["expires_at"] if r.get("ready")
                         else r["completed_at"]) or 0),
    "slots": lambda r: int(r["loot_count"] or 0),
}


def make_tree(parent) -> ttk.Treeview:
    """The Treeview both grids are: the same columns, widths and row colours.

    Packed with its scrollbar into ``parent``; the bindings are the caller's, because
    what a click MEANS is the grid's own business even though where it lands is not.
    """
    tree = ttk.Treeview(parent, columns=[c[0] for c in COLUMNS],
                        show="headings", selectmode="browse")
    bar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    for col, _key, width, anchor, stretch in COLUMNS:
        tree.column(col, width=width, anchor=anchor, stretch=stretch)
    # A ready tile is green and a counting-down one amber, exactly as the packed rows
    # were — the colour is the fastest read on the tab.
    tree.tag_configure("ready", foreground=READY_COLOR)
    tree.tag_configure("waiting", foreground=TIMER_COLOR)
    tree.tag_configure("soon", foreground=SOON_COLOR)
    return tree


def heading_command(tree, sort_by) -> None:
    """(Re)arm the sort command of every heading that has an order to sort in."""
    for col, _key, _w, _a, _s in COLUMNS:
        tree.heading(col, command=(lambda c=col: sort_by(c))
                     if col in SORT_KEYS else "")


def column_at(tree, event) -> str:
    """Which column the pointer is over, "" when it is not over a cell."""
    if tree is None or tree.identify("region", event.x, event.y) != "cell":
        return ""
    col = tree.identify_column(event.x)          # "#1" … "#6"
    try:
        return COLUMNS[int(col[1:]) - 1][0]
    except (ValueError, IndexError):
        return ""


def sort_rows(rows, sort) -> list:
    """The rows in the order the headings ask for.

    ``sort`` is ``(column id, reversed)`` once a heading has been clicked, and None
    while none has: an untouched table keeps the order auto-loot prizes them in — the
    highest star first, and within a level the tile that expires soonest — so it opens
    on the best raid without anybody having to ask for it.
    """
    if sort is None:
        return sorted(rows, key=lambda r: (-int(r["level"] or 0),
                                           r["expires_at"] or float("inf")))
    column, backwards = sort
    key = SORT_KEYS.get(column)
    if key is None:
        return list(rows)
    return sorted(rows, key=key, reverse=backwards)


def row_tag(row) -> str:
    """The colour tag one row is drawn with: soon beats ready beats still-counting."""
    return "soon" if row.get("soon") else "ready" if row.get("ready") else "waiting"


def new_row(record, timer) -> dict:
    """One roster record as the row a grid keeps — the shape both lists share.

    ``record`` is a mapping in the shape `dispatch_tasks.alliance_roster` returns; the
    working list above builds its rows straight from a `SecretTask` instead, and the two
    shapes meet here, in the keys every drawing helper below reads.

    ``timer`` is the row's own countdown variable; the caller makes it, because a grid
    with no Tk root behind it (a test) hands in a stand-in.
    """
    return {"uuid": record["uuid"], "server": record.get("server"),
            "x": record.get("x"), "y": record.get("y"),
            "level": record.get("level"), "cfg_id": record.get("cfg_id"),
            "loot_count": record.get("loot_count") or 0,
            "expires_at": record.get("expires_at"),
            "completed_at": record.get("completed_at"),
            "owner_name": record.get("owner_name") or "",
            # What the game paints the tile — its rarity — straight off the config row
            # the record carries (#1251). Kept on the row rather than recomputed at
            # filter time, because it is what the «UR» box asks about every redraw.
            "colour": record.get("colour") or 0,
            # Whether the GAME draws a star on this tile (#1244, live report). The list
            # above is starred-only by construction; the roster below holds every task
            # the alliance has out, and a row wearing a star the player cannot see in
            # the game is worse than no mark at all.
            "starred": bool(record.get("starred")),
            # Whether the alliance has already been shown this tile (#1245). Not read
            # off the record — a tile knows nothing about who has talked about it — but
            # stamped on afterwards by `SharedMarks.apply` from the profile's own store,
            # which is where the panel's shares and the game's own meet.
            #
            # `robbed` is the same kind of fact and the same kind of not-off-the-record
            # (#1272): the wire cannot say WHO robbed a tile, only how many have. It is
            # stamped by our own successful robbery and it is what takes «Собрать» off
            # the row while leaving «Поделиться» and the coordinate exactly where they
            # were — the whole reason a robbed row is no longer removed.
            "timer": timer, "ready": False, "soon": False, "shared": False,
            "robbed": False}


def refresh_timers(rows, t) -> tuple:
    """Rewrite every row's timer; return (expired keys, did ready/soon change on any row).

    The countdown runs to `completed_at` — the moment the tile becomes raidable — not
    to expiry: «готово через …» while it is ahead, then «готово к сбору» (with how
    long is left to loot) once it is past. `expires_at` still governs removal.

    Against the GAME's clock, not this computer's (#1227). Both timestamps are stamped
    by the game, and the machine's own clock was measured eleven seconds slow against
    it — so a countdown drawn from `time.time()` disagreed with the one the game draws
    beside it by however far the drift had got, which the operator was reading as
    25-30 s.
    """
    import game_clock
    now = game_clock.now_ms()
    expired, changed = [], False
    for key, row in rows.items():
        exp = row["expires_at"]
        if exp is not None and exp <= now:
            expired.append(key)
            continue
        done = row["completed_at"]
        # A ghost-recon squad's readiness is the GAME's own verdict, not a clock: the
        # event's tiles carry no completion time until the squad is back, and the
        # client answers «robbable / not» itself (#1251). A row that hands one in
        # (`ready_forced`) is believed; every other row is judged by its countdown, as
        # it always was.
        forced = row.get("ready_forced")
        ready = bool(forced) if forced is not None else (done is not None and done <= now)
        if ready != row.get("ready"):
            row["ready"] = ready
            changed = True
        # «Soon»: under ten minutes from whatever this row is waiting on next — being
        # raidable while it still counts down, losing its loot once it is raidable.
        # Recomputed every second like the ready flag, and a flip repaints the row the
        # same way a flip of `ready` does — the colour is the whole point (#1241).
        soon = (not ready and done is not None and done - now < SOON_MS) or \
               (ready and exp is not None and exp - now < SOON_MS)
        if soon != row.get("soon"):
            row["soon"] = soon
            changed = True
        if done and not ready:
            state = t("secrettasks.until_ready", t=fmt_left(done - now))
        elif ready and exp is not None:
            state = t("secrettasks.ready_expires", t=fmt_left(exp - now))
        elif ready:
            state = t("secrettasks.ready")
        elif row.get("state_key"):
            # Nothing to count down to, but the game has a word for this row — the
            # ghost list's `GhostreconPointStealType` (#1251). Saying it beats «готово
            # через —», which reads as a broken clock rather than as a verdict.
            state = t(row["state_key"])
        else:
            state = t("secrettasks.until_ready", t="—")
        # «уже поделились» rides in the state cell rather than a column of its own
        # (#1245). It is the cell rewritten every second, so a mark that landed since
        # the last full redraw — an alliancemate pressing share in the game — shows
        # within the second without the table being rebuilt.
        if row.get("shared"):
            state = "%s · %s" % (state, t("secrettasks.shared_mark"))
        # «уже ограбили» rides in the same cell, for the same reason and beside the same
        # mark (#1272). It is what a row keeps INSTEAD of disappearing, so it has to say
        # so in words: a «готово к сбору» row with no «Собрать» cell and nothing
        # explaining why reads as a bug, which is exactly what a silent glyph would be.
        if row.get("robbed"):
            state = "%s · %s" % (state, t("secrettasks.robbed_mark"))
        # HOW OLD THIS ROW'S INFORMATION IS, when it is old (#1251). The capture only
        # fills the list; a row nobody has driven the map past for a while is still a
        # row, and the honest thing is to SAY that rather than to hide it. Judged on the
        # machine's clock because `seen_at` is stamped there, not by the game.
        stale = _stale_minutes(row.get("seen_at"))
        if stale:
            state = "%s · %s" % (state, t("secrettasks.seen_ago", n=stale))
        row["timer"].set(state)
    return expired, changed


#: How old a row's information has to be before the state cell says so, in seconds.
#: The same fifteen minutes the capture's own scan window used to DROP a row after —
#: kept as the threshold for a WORD, which is all it should ever have been (#1251).
STALE_AFTER = 15 * 60


def _stale_minutes(seen_at) -> int:
    """Whole minutes since the capture last saw this row, or 0 while that is recent."""
    if not seen_at:
        return 0
    age = time.time() - float(seen_at)
    return int(age // 60) if age > STALE_AFTER else 0


def paint_timers(tree, rows) -> None:
    """Write each row's countdown into its cell — the per-second half of the drawing.

    Only the state cell changes as a second passes; the ready-transition is what asks
    for a full redraw, because it re-colours the row and re-sorts it.
    """
    if tree is None:
        return
    for key, row in rows.items():
        try:
            if tree.exists(key):
                tree.set(key, "state", row["timer"].get())
        except tk.TclError:
            return


def fmt_left(ms: int) -> str:
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


class TaskGrid:
    """One page of the tab's notebook: the table above, filled by a read of its own.

    The alliance list (#1244) and the ghost-recon list (#1251) are both this class with
    a different read behind them and a different set of boxes over them, because every
    part that is not the read is identical — the rows are replaced whole by each answer,
    they count down on the tab's own second, a coordinate walks the camera, a heading
    sorts and a right-click offers what the list can actually do.

    What a subclass says for itself: the words at the top (`TITLE_KEY`, `HINT_KEY`,
    `EMPTY_KEY`), which rows the boxes let through (:meth:`visible_rows`), whether a row
    can be robbed from here (:meth:`collectable`) and what the right-click menu offers.
    """

    #: The frame's heading, the grey line under it, and what it says with nothing in it.
    TITLE_KEY = ""
    HINT_KEY = ""
    EMPTY_KEY = ""

    #: The key this page's own settings are stored under, so two pages' filters never
    #: land in one another's slot (#1251).
    CONFIG_KEY = ""

    def __init__(self, tab) -> None:
        self.tab = tab
        # EVERY page carries its own level range (#1251). One range on top of the tab
        # meant «уровень от / до» narrowed lists it had nothing to do with — the ghost
        # squads are levels 3-5 and the secret tasks 1-7, so one pair of boxes could
        # not be right for both. A blank box is no bound, as everywhere else here.
        self.level_from = tk_stringvar(tab.rt.root)
        self.level_to = tk_stringvar(tab.rt.root)
        # uuid (str) -> the row record `new_row` makes. Replaced wholesale by `apply`;
        # nothing here outlives the game's own answer.
        self._rows: dict = {}
        self._tree = None
        self._body = None
        self._empty = None
        self._sort = None            # (column id, reversed) once a heading is clicked
        self._count_var = tk_stringvar(tab.rt.root)

    # -- building ---------------------------------------------------------------
    def build(self, parent) -> "ttk.Frame":
        """The framed table, ready to be added as a page of the tab's notebook."""
        frame = self.tab.tr(ttk.LabelFrame(parent, padding=6), self.TITLE_KEY)
        head = ttk.Frame(frame)
        head.pack(fill="x")
        self.tab.tr(ttk.Label(head, foreground="#888", wraplength=640,
                              justify="left"), self.HINT_KEY).pack(side="left")
        ttk.Label(head, textvariable=self._count_var, foreground="#888").pack(
            side="right")
        self.build_filters(frame)

        wrap = ttk.Frame(frame)
        wrap.pack(fill="both", expand=True, pady=(4, 0))
        self._empty = self.tab.tr(ttk.Label(wrap, foreground="#888"), self.EMPTY_KEY)
        self._body = ttk.Frame(wrap)
        self._body.pack(fill="both", expand=True)

        tree = make_tree(self._body)
        tree.bind("<Button-1>", self._on_click)
        tree.bind("<Double-Button-1>", self._on_double_click)
        tree.bind("<Button-3>", self._on_right_click)
        tree.bind("<Motion>", self._on_motion)
        tree.bind("<<TreeviewSelect>>", lambda _e: self.tab.sync_actions())
        self._tree = tree
        self.retranslate()
        self._update_count()
        return frame

    def build_filters(self, parent) -> None:
        """The page's own boxes, between the hint and the table.

        The level range is every page's, so it is drawn here; a subclass adds its own
        beside it by overriding :meth:`extra_filters`.
        """
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(4, 0))
        self.tab.tr(ttk.Label(bar), "secrettasks.filters").pack(side="left", padx=(0, 8))
        self.tab.tr(ttk.Label(bar), "secret.filter_level_from").pack(side="left",
                                                                    padx=(0, 2))
        NumericEntry(bar, textvariable=self.level_from, width=4).pack(side="left")
        self.tab.tr(ttk.Label(bar), "secret.level_to").pack(side="left", padx=(6, 2))
        NumericEntry(bar, textvariable=self.level_to, width=4).pack(side="left")
        self.extra_filters(bar)
        for var in (self.level_from, self.level_to):
            var.trace_add("write", lambda *_a: self.refilter())

    def extra_filters(self, bar) -> None:
        """Whatever else THIS page filters by, beside the level range. None by default."""

    def in_level_range(self, row) -> bool:
        """Whether a row is inside this page's own level range (blank box = no bound)."""
        level = int(row.get("level") or 0)
        low, high = str(self.level_from.get()).strip(), str(self.level_to.get()).strip()
        if low.isdigit() and level < int(low):
            return False
        if high.isdigit() and level > int(high):
            return False
        return True

    def config(self) -> dict:
        """This page's own settings, under its own key (#1251)."""
        return {"level_from": self.level_from.get(), "level_to": self.level_to.get()}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self.level_from.set(str(raw.get("level_from", "")))
        self.level_to.set(str(raw.get("level_to", "")))

    def persist_vars(self) -> list:
        return [self.level_from, self.level_to]

    def retranslate(self) -> None:
        """(Re)write the headings in the language now on, and re-arm their sorts."""
        if self._tree is None:
            return
        try:
            for col, key, _w, _a, _s in COLUMNS:
                self._tree.heading(col, text=self.tab.t(key))
            heading_command(self._tree, self._sort_by)
        except tk.TclError:
            return

    # -- the list ----------------------------------------------------------------
    def apply(self, records) -> None:
        """Replace the grid with what the read just said.

        Wholesale, not a merge: a task the read does not carry has ended, and the game
        is the authority on that. A row that IS still there keeps its countdown
        variable, so the cell it is drawn in does not blink on every refresh.
        """
        rows: dict = {}
        for record in records or ():
            key = str(record["uuid"])
            row = self._rows.get(key)
            if row is None:
                row = new_row(record, tk_stringvar(self.tab.rt.root))
            else:
                self.update_row(row, record)
            self.decorate(row, record)
            rows[key] = row
        self._rows = rows
        self.render()

    def update_row(self, row, record) -> None:
        """Bring a row that is still in the read up to date, keeping its timer."""
        row["expires_at"] = record.get("expires_at")
        row["completed_at"] = record.get("completed_at")
        row["loot_count"] = record.get("loot_count") or 0
        row["level"] = record.get("level")
        row["owner_name"] = record.get("owner_name") or ""
        row["colour"] = record.get("colour") or 0

    def decorate(self, row, record) -> None:
        """Whatever this list carries over and above the shared shape. Nothing here."""

    def clear(self) -> None:
        """Drop every row — the profile switched, or the game went away."""
        self._rows = {}
        self.render()

    def mark_robbed(self, key: str) -> None:
        """Stamp one tile as robbed by us, wherever it is drawn.

        It used to be `drop` — the row came off this table too, because a tile we had
        just robbed was «spent for us». It is not: a raid worth one of the day's five is
        exactly the raid worth telling the alliance about, and «Поделиться» has to be
        pressed on a row (#1272). The same tile can be on two tables at once, so both are
        marked by the one robbery, the same way one share marks both.
        """
        row = self._rows.get(str(key))
        if row is not None and not row.get("robbed"):
            row["robbed"] = True
            self.render()

    def tick(self) -> None:
        """The per-second half, driven by the tab's own countdown chain.

        Same arithmetic as the ★ list — the timers are rewritten, an expired tile drops,
        and only a state change costs a full redraw.
        """
        if self._tree is None:
            return
        expired, changed = self._refresh_timers()
        for key in expired:
            self._rows.pop(key, None)
        if expired or changed:
            self.render()
        else:
            paint_timers(self._tree, self._rows)

    def _refresh_timers(self) -> tuple:
        """The countdowns, with the «уже поделились» mark stamped on first (#1245).

        The very same two steps the ★ list takes (`SecretTasksTab._refresh_timers`) —
        one store of shared tiles, read by every grid, so a task marked on one of them
        is marked on the others in the same second.
        """
        marked = self.tab.shared.apply(self._rows)
        expired, changed = refresh_timers(self._rows, self.tab.t)
        return expired, changed or marked

    # -- what the boxes let through -----------------------------------------------
    def visible_rows(self) -> list:
        """The rows this page shows: inside its own level range, and whatever else its
        own boxes ask for (:meth:`narrow`)."""
        return self.narrow([r for r in self._rows.values() if self.in_level_range(r)])

    def narrow(self, rows) -> list:
        """A subclass's own display rules, applied after the level range."""
        return rows

    def collectable(self, row) -> bool:
        """Whether «Собрать» means anything on a row of THIS list."""
        return self.tab._collectable(row)

    def row_values(self, row) -> tuple:
        """One row as the cells of the table — the tab's own formatting by default."""
        return self.tab._row_values(row)

    # -- drawing ------------------------------------------------------------------
    def render(self) -> None:
        """Rebuild the table from the current rows, in the order the headings ask for."""
        tree = self._tree
        if tree is None:
            return
        self._refresh_timers()
        chosen = set(tree.selection())
        for iid in tree.get_children(""):
            tree.delete(iid)
        rows = sort_rows(self.visible_rows(), self._sort)
        for row in rows:
            tree.insert("", "end", iid=str(row["uuid"]),
                        values=self.row_values(row), tags=(row_tag(row),))
        back = [iid for iid in chosen if tree.exists(iid)]
        if back:
            tree.selection_set(back)
        self._show_empty(not rows)
        self._update_count()
        self.tab.sync_actions()

    def _show_empty(self, empty: bool) -> None:
        if self._empty is None:
            return
        try:
            if empty:
                self._empty.pack(before=self._body, anchor="w", pady=(0, 4))
            else:
                self._empty.pack_forget()
        except tk.TclError:
            pass

    def _update_count(self) -> None:
        n = len(self.visible_rows())
        self._count_var.set(self.tab.t("secrettasks.count", n=n) if n else "")

    def _sort_by(self, column: str) -> None:
        """A heading was clicked: sort by it, and flip the direction on a second click."""
        if self._sort and self._sort[0] == column:
            self._sort = (column, not self._sort[1])
        else:
            self._sort = (column, False)
        self.render()

    def refilter(self) -> None:
        """A box on this page was flipped: redraw under the new rule, read nothing."""
        self.tab.rt.settings.changed()
        self.render()

    # -- what a click does ---------------------------------------------------------
    def selected(self):
        """The row this page's selection is on, or None."""
        tree = self._tree
        if tree is None:
            return None
        picked = tree.selection()
        return self._rows.get(picked[0]) if picked else None

    def _row_at(self, event):
        return self._rows.get(self._tree.identify_row(event.y)) if self._tree else None

    def _on_click(self, event) -> None:
        """The two live cells: the coordinate, and the action where there is one."""
        where = column_at(self._tree, event)
        row = self._row_at(event)
        if row is None:
            return
        if where == LINK_COLUMN:
            self.tab._jump_to_row(row)
        elif where == ACTION_COLUMN and self.collectable(row):
            self.tab._collect(row)

    def _on_double_click(self, event) -> None:
        row = self._row_at(event)
        if row is not None and self.collectable(row):
            self.tab._collect(row)

    def _on_motion(self, event) -> None:
        """The link cursor over a cell that acts, the ordinary one everywhere else."""
        where = column_at(self._tree, event)
        row = self._row_at(event)
        live = where == LINK_COLUMN or (
            where == ACTION_COLUMN and bool(row and self.collectable(row)))
        try:
            self._tree.configure(cursor="hand2" if live else "")
        except tk.TclError:
            pass

    def _on_right_click(self, event) -> None:
        """The row's own menu, under the pointer."""
        tree = self._tree
        iid = tree.identify_row(event.y) if tree is not None else ""
        row = self._rows.get(iid)
        if row is None:
            return
        tree.selection_set(iid)
        menu = tk.Menu(self.tab.rt.root, tearoff=0)
        self.fill_menu(menu, row)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def fill_menu(self, menu, row) -> None:
        """What the right-click offers. «Перейти» is the one every list has."""
        menu.add_command(label=self.tab.t("secrettasks.goto"),
                         command=lambda: self.tab._jump_to_row(row))
