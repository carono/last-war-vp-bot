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
#:
#: EVERY KEY ENDS IN THE UUID (#1280). Python's sort is stable, so equal keys keep the
#: order they came IN — and that order is the model's dict, which changes whenever a row
#: is dropped and re-added by a feed. Two tiles of the same level and the same expiry
#: would then swap places for no reason a person can see, under the hand of whoever was
#: reading them. A tie-break nobody can see makes the order the same every draw.
SORT_KEYS = {
    "owner": lambda r: ((r.get("owner_name") or "").lower(), _uuid(r)),
    "coords": lambda r: (int(r["x"] or 0), int(r["y"] or 0), _uuid(r)),
    "server": lambda r: (int(r["server"] or 0), _uuid(r)),
    "lvl": lambda r: (int(r["level"] or 0), _uuid(r)),
    "state": lambda r: (0 if r.get("ready") else 1,
                        (r["expires_at"] if r.get("ready")
                         else r["completed_at"]) or 0,
                        _uuid(r)),
    "slots": lambda r: (int(r["loot_count"] or 0), _uuid(r)),
}


def _uuid(row) -> str:
    """The row's own id as the last word of every sort key — see :data:`SORT_KEYS`."""
    return str(row.get("uuid") or "")

# …AND THE ★ LIST'S OWN EXTRA COLUMN (#1484): when the game last CONFIRMED this row.
#
# Only that list has one, and that is the point of it being separate rather than added to
# the set above. The alliance and ghost pages are re-read from the client whole every time
# they are looked at, so «when was this last verified» is «just now» for every row on
# them and a column saying so would be decoration. The ★ list is the opposite: it is
# filled by a passive capture that only hears a tile while the map is being driven over
# it, so a row can be hours old with nothing on the screen saying which. «Строка, которую
# не сверяли час, и строка, сверенная минуту назад, сейчас выглядят одинаково.»
STAR_COLUMNS = COLUMNS + (
    ("checked", "secrettasks.col.checked", 110, "center", False),
)

#: The ★ list's sort keys: the shared ones plus its own column. A never-verified row
#: sorts FIRST ascending — `0` is older than any timestamp — which is the order the eye
#: wants: least trustworthy at the top.
STAR_SORT_KEYS = dict(SORT_KEYS,
                      checked=lambda r: (int(r.get("checked_at") or 0), _uuid(r)))


def checked_text(checked_at, now: int, t) -> str:
    """The «Сверено» cell: how long ago the game last confirmed this row.

    `checked_at` is on the GAME's clock in milliseconds, like every other timestamp on
    this tab, and `now` must be too (`game_clock.now_ms`) — the machine this was written
    on ran eleven seconds slow against the game's own clock (#1227), and an age is a
    subtraction of two clocks that had better be the same one.

    **Nothing is drawn as a dash.** A row that has never been verified says so in words:
    a dash in an age column reads as «нечего показывать», which the eye finishes as «всё
    в порядке», and the rows this list gets wrong are precisely the ones nothing has ever
    checked. That was asked for in exactly those terms (#1484).
    """
    if not checked_at:
        return t("secrettasks.checked.never")
    age = max(0, (int(now) - int(checked_at)) // 1000)
    if age < 60:
        return t("secrettasks.checked.now")
    if age < 3600:
        return t("secrettasks.checked.min", n=age // 60)
    return t("secrettasks.checked.hour", n=age // 3600)


def make_tree(parent, columns=None) -> ttk.Treeview:
    """The Treeview both grids are: the same columns, widths and row colours.

    Packed with its scrollbar into ``parent``; the bindings are the caller's, because
    what a click MEANS is the grid's own business even though where it lands is not.

    ``columns`` defaults to the secret-task set every page on this tab was built for.
    The world pages (#1289) hand in their own — a mine has a resource and a truck has a
    cargo, and neither has an owner's dispatch level — which is the whole reason the
    column set moved from a module constant to an argument.
    """
    columns = COLUMNS if columns is None else columns
    tree = ttk.Treeview(parent, columns=[c[0] for c in columns],
                        show="headings", selectmode="browse")
    bar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    for col, _key, width, anchor, stretch in columns:
        tree.column(col, width=width, anchor=anchor, stretch=stretch)
    # A ready tile is green and a counting-down one amber, exactly as the packed rows
    # were — the colour is the fastest read on the tab.
    tree.tag_configure("ready", foreground=READY_COLOR)
    tree.tag_configure("waiting", foreground=TIMER_COLOR)
    tree.tag_configure("soon", foreground=SOON_COLOR)
    return tree


def heading_command(tree, sort_by, columns=None, keys=None) -> None:
    """(Re)arm the sort command of every heading that has an order to sort in."""
    columns = COLUMNS if columns is None else columns
    keys = SORT_KEYS if keys is None else keys
    for col, _key, _w, _a, _s in columns:
        tree.heading(col, command=(lambda c=col: sort_by(c))
                     if col in keys else "")


def column_at(tree, event, columns=None) -> str:
    """Which column the pointer is over, "" when it is not over a cell."""
    columns = COLUMNS if columns is None else columns
    if tree is None or tree.identify("region", event.x, event.y) != "cell":
        return ""
    col = tree.identify_column(event.x)          # "#1" … "#6"
    try:
        return columns[int(col[1:]) - 1][0]
    except (ValueError, IndexError):
        return ""


def sort_rows(rows, sort, keys=None) -> list:
    """The rows in the order the headings ask for.

    ``sort`` is ``(column id, reversed)`` once a heading has been clicked, and None
    while none has: an untouched table keeps the order auto-loot prizes them in — the
    highest star first, and within a level the tile that expires soonest — so it opens
    on the best raid without anybody having to ask for it.
    """
    keys = SORT_KEYS if keys is None else keys
    if sort is None:
        return sorted(rows, key=lambda r: (-int(r["level"] or 0),
                                           r["expires_at"] or float("inf"),
                                           _uuid(r)))
    column, backwards = sort
    key = keys.get(column)
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
        row["timer"].set(state_text(row, now, t))
    return expired, changed


def state_text(row, now: int, t) -> str:
    """One row's state cell, from the row and a clock. NO side effects (#1272).

    Split out of :func:`refresh_timers` so that the DISPLAY can be rewritten far more
    often than the model is recomputed. The once-a-second pass owns everything that
    changes a row — the ready flip, the soon colour, the expiry — and calls this at the
    end of it; the four-times-a-second repaint (:func:`repaint_countdowns`) calls this
    and nothing else, which is why it may run that often at all.

    `ready` is READ off the row here rather than derived: whose job it is to flip is the
    whole distinction above.
    """
    done, exp, ready = row["completed_at"], row["expires_at"], bool(row.get("ready"))
    if row.get("until_key") and exp is not None:
        # A row that counts down to something OTHER than being raidable (#1289): a truck
        # and a train count down to arriving, which is when they leave the map. Same
        # clock, same formatting, its own word — «прибудет через …» rather than «готово
        # через …», which would promise the person something to press.
        state = t(row["until_key"], t=fmt_left(exp - now))
    elif done and not ready:
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
        # A ★ row can no longer get here: one with no completion time is refused at the
        # model's door (`SecretTasksTab._merge`, #1272), because it can never become
        # raidable and so can never be a target. The branch stays for the ghost lists,
        # whose rows legitimately have neither a clock nor a verdict yet.
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
    return state


def count_text(t, shown: int, hidden: int) -> str:
    """«секреток: N · скрыто фильтрами: M» — one wording for every list here (#1272).

    SAID EVEN AT ZERO, and that is the whole reason it exists. An empty table with no
    number on it reads as «ничего не нашли», and it is routinely not: one live account
    had every star it could see sitting on its own server, so the raid page went blank on
    open while the model held thirty-four rows (#1251). «0 · скрыто 34» is a different
    sentence from «0», and only one of them is true.
    """
    line = t("secrettasks.count", n=shown)
    if hidden:
        line = "%s · %s" % (line, t("secrettasks.hidden", n=hidden))
    return line


def has_countdown(rows) -> bool:
    """Is any of these rows counting down? — what the fast repaint is armed on (#1272).

    A tab whose lists are all empty, or all «нет данных» ghost rows, has nothing to draw
    four times a second, and four wake-ups a second per open profile is a real share of
    the one event loop they share (#1226).
    """
    return any(r["completed_at"] is not None or r["expires_at"] is not None
               for r in rows.values())


def repaint_countdowns(tree, rows, t) -> None:
    """Rewrite the state cell of every row that is counting down — DISPLAY ONLY (#1272).

    «Те, что уже можно грабить, должны обновляться несколько раз в секунду.» A countdown
    redrawn once a second is a countdown a second late for most of every second, and a
    raidable tile is the one row where that is read as the list being stale.

    So this runs four times a second and the once-a-second pass stays where it was. It
    may, because of what it does NOT do: it drops nothing, it flips no `ready` and no
    `soon`, it re-sorts nothing, it re-reads nothing and it asks the game for nothing —
    the state is already in the model, and what is late is the drawing of it. Everything
    that CHANGES a row is still one pass a second, and that is what keeps this cheap
    enough to run at all.

    Two things keep it from being a storm. A row with neither clock has nothing to count
    down and is skipped whole (the ghost lists' «нет данных» rows). And a cell is written
    only when its TEXT has actually changed — the countdown moves in whole seconds, so in
    the steady state three passes out of four cost a string comparison and no Tk call at
    all. That matters more than it sounds: with four profiles open the shared event loop
    is what the panel runs out of first (#1226), and an unconditional `tree.set` per row
    per pass is precisely the traffic that ran it out.
    """
    if tree is None:
        return
    import game_clock
    now = game_clock.now_ms()
    for key, row in rows.items():
        if row["completed_at"] is None and row["expires_at"] is None:
            continue
        state = state_text(row, now, t)
        if state == row["timer"].get():
            continue
        row["timer"].set(state)
        try:
            if tree.exists(key):
                tree.set(key, "state", state)
        except tk.TclError:
            return


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


def sync_tree(tree, rows, values_of, tag_of, columns=None) -> None:
    """Bring the table to `rows` by CHANGING it, never by emptying and refilling (#1272).

    «И грид стирается и потом снова обновляется» — the old draw deleted every row and
    inserted every row again, so a refresh was a table that blinked out and came back,
    and whatever the eye was on moved out from under it. Nothing about a state read asks
    for that: a read moves a loot count, an expiry and a handful of rows in or out, and
    the other ninety are the rows they already were.

    So this is a diff. A row that is on the table and still wanted keeps its identity —
    its `iid`, its place in the scroll, its selection — and only the CELLS whose text has
    actually changed are written. A row that is no longer wanted is deleted, one that has
    appeared is inserted at the position it sorts to, and one that has merely moved is
    moved. In the steady state, where a poll confirms what was already there, this writes
    nothing at all.

    `values_of(row)` gives the cells in `COLUMNS` order and `tag_of(row)` the colour tag;
    both are the caller's, because the ★ list and the pages format differently.
    """
    if tree is None:
        return
    try:
        want = [str(row["uuid"]) for row in rows]
        wanted = set(want)
        for iid in list(tree.get_children("")):
            if iid not in wanted:
                tree.delete(iid)
        columns = [c[0] for c in (COLUMNS if columns is None else columns)]
        for index, (iid, row) in enumerate(zip(want, rows)):
            values = tuple(values_of(row))
            tag = tag_of(row)
            if not tree.exists(iid):
                tree.insert("", index, iid=iid, values=values, tags=(tag,))
                continue
            # Only the cells that moved. A `tree.set` per cell per redraw is exactly the
            # traffic that made four open profiles share one slow event loop (#1226).
            current = tuple(tree.item(iid, "values") or ())
            for pos, column in enumerate(columns):
                new = values[pos] if pos < len(values) else ""
                # A cell the row does not carry reads as EMPTY, not as «unknown» — a
                # grid whose `values_of` is shorter than COLUMNS (the ghost pages leave
                # the action cell off) would otherwise be written on every single draw,
                # which is the blinking this diff exists to stop (#1280).
                old = current[pos] if pos < len(current) else ""
                if str(old) != str(new):
                    tree.set(iid, column, new)
            if tuple(tree.item(iid, "tags") or ()) != (tag,):
                tree.item(iid, tags=(tag,))
            if tree.index(iid) != index:
                tree.move(iid, "", index)
    except tk.TclError:
        return


def paint_timers(tree, rows, t=None) -> None:
    """Write each row's countdown into its cell — the per-second half of the drawing.

    Only the state cell changes as a second passes; the ready-transition is what asks
    for a full redraw, because it re-colours the row and re-sorts it.

    ``t``, when given, also ages the «Сверено» cell (#1484) — the ★ list's own column,
    which counts UP from the last time the game confirmed the row. It changes at most
    once a minute per row, so the text is built, compared with what the cell already
    says, and written only when it has really moved: a `tree.set` per row per second is
    exactly the traffic that runs the shared event loop out with four profiles open
    (#1226). A grid with no such column passes nothing and pays nothing.
    """
    if tree is None:
        return
    now = None
    if t is not None:
        import game_clock
        now = game_clock.now_ms()
    for key, row in rows.items():
        try:
            if not tree.exists(key):
                continue
            tree.set(key, "state", row["timer"].get())
            if now is None:
                continue
            text = checked_text(row.get("checked_at"), now, t)
            if text != row.get("checked_text"):
                row["checked_text"] = text
                tree.set(key, "checked", text)
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


def take(raw, key, var, cast=bool) -> bool:
    """Apply ``raw[key]`` to ``var`` — and leave the live value alone when it is absent.

    A SAVED BLOCK THAT DOES NOT MENTION A BOX IS NOT A BLOCK THAT SAYS «OFF». The two
    read the same through `dict.get(key, default)` and they are opposite facts: a
    profile written before this page existed, a legacy block (`Settings.tab_config`
    falls back to the flat keys, which carry no `grids` at all) and a `{}` handed to a
    page whose key is missing all say «nothing is known about this box» — and answering
    that with the default is how a box a person ticked ticks itself off again later,
    with nothing on screen to explain it.

    Every save writes every key of a page's `config()`, so an UNTICKED box is stored as
    `false` and comes back unticked: the fact and the silence stay different.
    """
    if not isinstance(raw, dict) or key not in raw:
        return False
    var.set(cast(raw[key]))
    return True


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

    #: The table's own columns and the order each of them sorts in. Class attributes
    #: rather than the module constants they default to, because the world pages
    #: (#1289) are the same page machinery over a different set of facts — a mine has a
    #: resource where a task has an owner. Every helper below is handed these, so a
    #: subclass changes the table by naming two things and nothing else.
    COLUMNS = COLUMNS
    SORT_KEYS = SORT_KEYS

    #: The key this page's own settings are stored under, so two pages' filters never
    #: land in one another's slot (#1251).
    CONFIG_KEY = ""

    #: WHICH RECEIVER FEEDS THIS PAGE — a name in `panel/runtime/intake.py`, or `""` for
    #: a page nothing streams into (#1549). Naming one is what puts the flow strip above
    #: the table: «идут ли данные, берём ли мы их, когда пришло последнее». An empty
    #: table cannot say which of those it is, and four different failures drawing one
    #: blank page is what «грид не заполняется» has meant every time it was reported.
    INTAKE = ""

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
        # The flow strip above the table (#1549) — the receiver's own numbers, in words.
        # Made here and drawn in `build`, like everything else on a LAZY page.
        self._flow_var = tk_stringvar(tab.rt.root)
        self._flow_label = None

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
        self.build_flow(frame)
        self.build_filters(frame)

        wrap = ttk.Frame(frame)
        wrap.pack(fill="both", expand=True, pady=(4, 0))
        self._empty = self.tab.tr(ttk.Label(wrap, foreground="#888"), self.EMPTY_KEY)
        self._body = ttk.Frame(wrap)
        self._body.pack(fill="both", expand=True)

        tree = make_tree(self._body, self.COLUMNS)
        tree.bind("<Button-1>", self._on_click)
        tree.bind("<Double-Button-1>", self._on_double_click)
        tree.bind("<Button-3>", self._on_right_click)
        tree.bind("<Motion>", self._on_motion)
        tree.bind("<<TreeviewSelect>>", lambda _e: self.tab.sync_actions())
        self._tree = tree
        self.retranslate()
        self._update_count()
        return frame

    # -- the flow strip (#1549) -----------------------------------------------
    def build_flow(self, parent) -> None:
        """«Идут ли данные» — one line between the hint and the boxes.

        Only for a page that names an :attr:`INTAKE`. A page filled by a press and
        nothing else has no stream to report on, and a strip saying «ни разу» for ever
        would be noise rather than an answer.
        """
        if not self.INTAKE:
            return
        self._flow_label = ttk.Label(parent, textvariable=self._flow_var)
        self._flow_label.pack(fill="x", anchor="w", pady=(3, 0))
        self.refresh_flow()

    def flow_badge(self) -> dict:
        """This page's receiver, as `panel/runtime/flow.py` sees it. Never raises."""
        from ...runtime import flow

        return flow.badge(self.tab.rt, self.INTAKE)

    def refresh_flow(self) -> None:
        """Rewrite the strip from the ledger — called on the page's own second."""
        if not self.INTAKE or self._flow_label is None:
            return
        from ...runtime import flow

        said = flow.line(self.flow_badge())
        self._flow_var.set(self.tab.t(said["key"], **said["fmt"]))
        try:
            self._flow_label.configure(foreground=said["colour"])
        except tk.TclError:
            pass

    def web_flow(self) -> "dict | None":
        """The same badge for the phone — the card's `flow`, or None for a page with no
        stream behind it. Data, never words: the browser says them out of `/api/i18n`."""
        if not self.INTAKE:
            return None
        from ...runtime import flow

        said = flow.line(self.flow_badge())
        return {"key": said["key"], "fmt": said["fmt"], "colour": said["colour"],
                "state": self.flow_badge().get("state")}

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
        # …and THIS page's own «Очистить список», on THIS page (#1298). One button over
        # nine tables could only ever mean one of them, and it meant the ★ list — so a
        # person looking at «Поезда» pressed «Очистить» and watched nothing happen.
        self.tab.tr(ttk.Button(bar, width=12, command=self.clear_pressed),
                    "secrettasks.clear").pack(side="right")
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
        take(raw, "level_from", self.level_from, str)
        take(raw, "level_to", self.level_to, str)

    def persist_vars(self) -> list:
        return [self.level_from, self.level_to]

    def retranslate(self) -> None:
        """(Re)write the headings in the language now on, and re-arm their sorts."""
        if self._tree is None:
            return
        try:
            for col, key, _w, _a, _s in self.COLUMNS:
                self._tree.heading(col, text=self.tab.t(key))
            heading_command(self._tree, self._sort_by, self.COLUMNS, self.SORT_KEYS)
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

    def clear_pressed(self) -> None:
        """«Очистить список» ON THIS PAGE, and nowhere near its neighbours (#1298).

        THE THIRD WAY A ROW LEAVES, and the only other legal one: `THE_LIST_RULE`
        says a row goes when its own clock runs out or when the game says the tile is
        not there — this is a person asking, out loud, for this one table. It is not a
        reason to touch any other, so it does not: nine tables, nine buttons, and a
        press on one of them is answerable by looking at the table it sits on.

        Nothing is lost for good. Every list here is refilled by its own feed — the
        capture's checkpoint, a VM read, a push — so the press empties what is drawn
        and the next read brings back whatever is still true.
        """
        self.clear()
        # …and the checkpoint too, where this page keeps one. A page that emptied on
        # screen and came back whole on the next start would make the press a lie.
        self.persist()

    def persist(self) -> None:
        """Checkpoint this page's own list. Nothing for a page that is re-read whole."""

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

    def has_countdown(self) -> bool:
        """Whether this page has a clock running — the fast chain's own gate (#1272)."""
        return has_countdown(self._rows)

    def repaint(self) -> None:
        """The four-times-a-second half: the countdowns, and nothing else (#1272).

        Driven by the tab's own fast chain, the same way `tick` is driven by its slow
        one — one pair of chains for the tab, not a pair per table. Everything that could
        change a row (expiry, the ready flip, the marks) stays in `tick`; this only
        redraws what is already decided, which is what makes it affordable at that rate.
        """
        repaint_countdowns(self._tree, self._rows, self.tab.t)

    def tick(self) -> None:
        """The per-second half, driven by the tab's own countdown chain.

        Same arithmetic as the ★ list — the timers are rewritten, an expired tile drops,
        and only a state change costs a full redraw.
        """
        if self._tree is None:
            return
        self.refresh_flow()
        moved = self.advance()
        expired, changed = self._refresh_timers()
        for key in expired:
            self._rows.pop(key, None)
        if expired or changed or moved:
            self.render()
        else:
            paint_timers(self._tree, self._rows)

    def advance(self) -> bool:
        """Whatever moves under a row between two reads — `True` if a cell changed.

        `paint_timers` rewrites the state column and nothing else, which is right for a
        list whose rows stand still: a tile is where it is until the game says otherwise.
        A truck and a train do NOT stand still (#1298), so their page walks each row
        along its leg here and says so, and the second's tick redraws the table instead
        of only its clocks. Nothing to move on the other pages, so nothing moves.
        """
        return False

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
        """Bring the table to the current rows — cell by cell, never by emptying it.

        The diff is `sync_tree`, the same one the ★ list draws through (#1272): a page
        that blinks its whole table on every read is a page whose selection and scroll
        position move under the hand reading it.
        """
        tree = self._tree
        if tree is None:
            return
        self._refresh_timers()
        rows = sort_rows(self.visible_rows(), self._sort, self.SORT_KEYS)
        sync_tree(tree, rows, self.row_values, row_tag, self.COLUMNS)
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

    def counts(self) -> tuple:
        """`(shown, hidden)` — what this page draws, and what its own boxes hold back.

        «Hidden» is every row of the model this page's filters keep off the table: its
        level range, and whatever :meth:`narrow` adds. It is not a detail — a page that
        goes blank because a box is ticked looks exactly like a page that read nothing.
        """
        shown = len(self.visible_rows())
        return shown, max(len(self._rows) - shown, 0)

    def _update_count(self) -> None:
        shown, hidden = self.counts()
        self._count_var.set(count_text(self.tab.t, shown, hidden))
        # …and the same pair on the notebook's own tab, so it is readable without
        # opening the page (#1272).
        self.tab.sync_page_counts()

    def _sort_by(self, column: str) -> None:
        """A heading was clicked: sort by it, and flip the direction on a second click."""
        if column not in self.SORT_KEYS:
            return
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
        where = column_at(self._tree, event, self.COLUMNS)
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
        where = column_at(self._tree, event, self.COLUMNS)
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
