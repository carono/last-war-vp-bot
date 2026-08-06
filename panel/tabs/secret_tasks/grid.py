"""The table both secret-task lists on this tab are drawn as, and its arithmetic.

The tab has TWO grids now (#1244) and they are deliberately the same table twice: the
same columns in the same order, the same countdown in the state cell, the same amber /
yellow / green a row is painted in, the same click on a coordinate that walks the
camera and the same click on the action cell that robs the tile. What differs is only
what is IN each of them — the upper one keeps the starred raid targets the wire feed
and the VM agree on, the lower one mirrors the game's own alliance table whole, stars
and plain tiles alike.

So everything that is about the TABLE rather than about either list lives here: the
column set, the colours, the sort keys, the per-second countdown and the "which cell is
under the pointer" question. :mod:`~panel.tabs.secret_tasks.tab` and
:mod:`~panel.tabs.secret_tasks.alliance` both work off this module, which is also why it
exists as a module rather than as a base class — a helper that takes the rows and the
translator is testable without a Tk root, and both grids were.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# The star glyph in front of a row and the icons for the two row states: a tile still
# counting down to raidability, and one that is ready to loot now.
STAR_GLYPH = "⭐"
TYPE_GLYPH = "🗡️"
READY_GLYPH = "✅"

# The amber the countdown is drawn in, and the green a ready row switches to.
TIMER_COLOR = "#e0a84f"
READY_COLOR = "#4fe08a"

# A row under ten minutes from the moment it needs attention — either about to become
# raidable, or about to expire while still raidable — turns this yellow instead, so it
# stands out from the rest of a list that is otherwise always shown in full (#1241).
SOON_COLOR = "#e0d84f"
SOON_MS = 10 * 60_000

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


def new_row(task, timer) -> dict:
    """One `SecretTask` as the record a grid keeps — the shape both lists share.

    ``timer`` is the row's own countdown variable; the caller makes it, because a grid
    with no Tk root behind it (a test) hands in a stand-in.
    """
    return {"uuid": task.uuid, "server": task.server_id, "x": task.x, "y": task.y,
            "level": task.level, "cfg_id": task.cfg_id,
            "loot_count": task.loot_count, "expires_at": task.expires_at,
            "completed_at": task.completed_at,
            "timer": timer, "ready": False, "soon": False}


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
        ready = done is not None and done <= now
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
        if done is None:
            row["timer"].set(t("secrettasks.until_ready", t="—"))
        elif not ready:
            row["timer"].set(t("secrettasks.until_ready", t=fmt_left(done - now)))
        elif exp is not None:
            row["timer"].set(t("secrettasks.ready_expires", t=fmt_left(exp - now)))
        else:
            row["timer"].set(t("secrettasks.ready"))
    return expired, changed


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
