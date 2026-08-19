"""«Занятость» — the busy debugger, drawn on «Разработка» (#1392).

WHAT IT IS FOR. A panel that is not doing what it was told looks exactly like a panel
that is idle: the log is quiet because nothing HAPPENED, the window redraws because the
Tk thread is fine, and the errand somebody is waiting for is sitting behind a claim
another profile took four minutes ago. This block answers, at one instant, «чем панель
занята и кто кого ждёт» — the threads at work, the queue behind them, the claims and who
is queued for them, the timers and what is overdue, and a short list of the signs a jam
leaves.

WHERE THE DATA COMES FROM: `panel/runtime/busy.py::snapshot`, which reads dicts under
locks that are already held for microseconds and touches neither Tk nor the game. This
file is the drawing and nothing else.

**SEVERAL GRIDS, NOT ONE** (#1500). The block used to be one `ttk.Treeview` with a
«show: …» picker to narrow it to a single kind of row — an improvement over the wall of
text it replaced (#1415), but still one shape of table asked to answer for listeners,
timers, claims and threads at once, whose columns mean genuinely different things: a
listener's «сколько раз» is not a claim's «отказов», and a timer's «когда следующий
заход» is not a run's «какой шаг». So the page is now :data:`GROUPS` — one titled grid
per kind of thing, stacked in a scrollable column, each with the columns that kind
actually has. A GRID THAT WOULD BE EMPTY STILL SHOWS — one row saying «— nothing»
(:data:`busy.none`) — rather than vanishing, because a section that disappeared reads as
«таких у нас нет», and that is not what an empty listener list means.

**THE LONG AND THE STUCK COLOUR THEMSELVES.** A row past :data:`SLOW_SEC` is amber and
anything the snapshot already calls a jam — an overdue timer, a late tick, a verdict — is
red, in every grid alike. That is the whole point of the rearrangement: the jam is
visible before a word of it is read.

EVERY GRID REWRITTEN IN PLACE, and only when something moved: each grid's rows are
compared with what is on screen and an identical snapshot touches no widget at all. Forty
labels re-configured once a second is the Tk cost the panel spent #1226 getting rid of,
and a `Treeview` repopulated for nothing is the same bill, paid per grid now instead of
once.

THE CLIPBOARD IS STILL SENTENCES (:meth:`lines`). A jam is usually REPORTED rather than
fixed on the spot, and «идёт: restart_game (200 с)» reads in a chat where a tab-separated
row does not — so «Скопировать» renders the same snapshot as the text the block used to
be, and `tests/test_panel_busy.py` still holds that rendering to its locale keys.

THREE THINGS IT DELIBERATELY DOES NOT DO:

* **it does not watch when nobody is looking.** The refresh is armed on `on_show` and
  disarmed on `on_hide`, and the tick is skipped while the tick box is off. An
  observation that runs all day to describe a fault that lasts a minute is a cost with no
  reader;
* **it does not ask the game anything.** The whole point is to explain a panel that is
  not answering — a read would join the very queue being measured;
* **it does not go to the phone.** «Разработка» declares `WEB_SCREEN = False`, and that
  is the tab's standing exception rather than a new one (`CLAUDE.md`,
  `docs/panel-tabs.md`). What a jam looks like from a phone is a different question and
  is asked of the person before anything is drawn.

The claim registry and the thread list are process-wide on purpose — that is what they
ARE (`panel/runtime/claims.py`) — so every row of them says whose it is and the rows of
the profile doing the looking are marked and sorted first.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ..runtime import busy as busymod
from ..widgets import ScrollableFrame

#: How often the block re-reads while it is being watched. A second is the resolution of
#: everything it shows (a step, a wait, a queue) and one snapshot is dict reads.
REFRESH_MS = 1000

#: The name the refresh chain is armed under. One chain per name (panel/runtime/tick.py).
TICK = "develop_busy"

#: How many rows one section may draw before the CLIPBOARD text says «…and N more». The
#: grids themselves are not capped that way — each one scrolls and sorts on its own,
#: which is what a cap was standing in for while the block was a fixed-height `Text`.
ROWS = 8

#: The urgency levels, as locale keys — `claims.BACKGROUND` / `EXPRESS` / `HUMAN`.
LEVELS = {0: "busy.level.background", 1: "busy.level.express", 2: "busy.level.human"}

#: Every kind of row `rows()` produces, and the order a jam is asked about — still what
#: :meth:`lines` walks section by section for the clipboard text.
SECTIONS = ("jam", "runs", "queue", "claims", "listeners", "intake", "timers",
            "slowest", "threads")

#: **THE GRIDS**, in the order they are stacked on the page. Each entry is
#: ``(key, title-locale-key, sections, columns)``:
#:
#: * `sections` — which of :data:`SECTIONS` a row must belong to for this grid;
#: * `columns` — ``(field, header-locale-key, width, right-aligned?, form)`` per column,
#:   where `form` says how the cell is rendered: ``"text"`` (shown as it is — data, per
#:   `CLAUDE.md`), ``"secs"`` (an int, or blank for `None`) or ``"key"`` (a locale key,
#:   said through `t()`, blank for an empty string).
#:
#: **ЛИСТЕНЕРЫ отдельно, ТАЙМЕРЫ отдельно, и т.д.** (#1500) — a first cut folded the
#: errand queue into the timers grid, and the very next ask was «где посмотреть очередь
#: живьём» (#1500, part two): «в очереди» is what a «отработать сейчас» press answers
#: with, and the person pressing it wants the ROW, not a merged table's leftovers. So the
#: queue is its own grid — what is running, what waits behind it and why, what is held
#: because the game's own claim is somebody else's, what is parked behind a shut gate and
#: for how much longer, and what just left and how it ended — reading `queue_state()`
#: straight (`panel/timers.py`) rather than a copy of it, per «не заводи второй источник
#: правды». `timers` keeps only the clock — the catalogue's own due/overdue reading.
GROUPS = (
    ("listeners", "busy.group.listeners", ("listeners",), (
        ("what", "busy.col.what", 170, False, "text"),
        ("who", "busy.col.kind", 90, False, "text"),
        ("detail", "busy.col.detail", 340, False, "text"),
        ("secs", "busy.col.secs", 90, True, "secs"),
        ("level", "busy.col.heard", 70, True, "text"),
        ("status", "busy.col.status", 130, False, "key"),
    )),
    ("intake", "busy.group.intake", ("intake",), (
        ("what", "busy.col.what", 170, False, "text"),
        ("seen", "busy.col.seen", 90, True, "text"),
        ("kept", "busy.col.kept", 90, True, "text"),
        ("dropped", "busy.col.dropped", 100, True, "text"),
        ("lost", "busy.col.lost", 90, True, "text"),
        ("detail", "busy.col.detail", 260, False, "text"),
        ("secs", "busy.col.secs", 80, True, "secs"),
        ("status", "busy.col.status", 130, False, "key"),
    )),
    ("queue", "busy.group.queue", ("queue",), (
        ("what", "busy.col.what", 180, False, "text"),
        ("who", "busy.col.queued_by", 90, False, "text"),
        ("detail", "busy.col.detail", 380, False, "text"),
        ("secs", "busy.col.secs", 80, True, "secs"),
        ("status", "busy.col.status", 130, False, "key"),
    )),
    ("timers", "busy.group.timers", ("timers",), (
        ("what", "busy.col.what", 190, False, "text"),
        ("who", "busy.col.who", 130, False, "text"),
        ("detail", "busy.col.detail", 300, False, "text"),
        ("secs", "busy.col.secs", 80, True, "secs"),
        ("status", "busy.col.status", 140, False, "key"),
    )),
    ("jam", "busy.section.jam", ("jam",), (
        ("detail", "busy.col.detail", 560, False, "text"),
        ("status", "busy.col.status", 120, False, "key"),
    )),
    ("runs", "busy.section.runs", ("runs",), (
        ("what", "busy.col.what", 190, False, "text"),
        ("who", "busy.col.who", 130, False, "text"),
        ("detail", "busy.col.detail", 340, False, "text"),
        ("secs", "busy.col.secs", 80, True, "secs"),
        ("status", "busy.col.status", 140, False, "key"),
    )),
    ("claims", "busy.section.claims", ("claims",), (
        ("what", "busy.col.what", 150, False, "text"),
        ("who", "busy.col.who", 160, False, "text"),
        ("detail", "busy.col.detail", 240, False, "text"),
        ("secs", "busy.col.secs", 80, True, "secs"),
        ("level", "busy.col.level", 110, False, "key"),
        ("status", "busy.col.status", 120, False, "key"),
    )),
    ("slowest", "busy.section.slowest", ("slowest",), (
        ("what", "busy.col.what", 190, False, "text"),
        ("who", "busy.col.who", 130, False, "text"),
        ("detail", "busy.col.detail", 340, False, "text"),
        ("secs", "busy.col.secs", 80, True, "secs"),
        ("status", "busy.col.status", 140, False, "key"),
    )),
    ("threads", "busy.section.threads", ("threads",), (
        ("what", "busy.col.what", 260, False, "text"),
        ("detail", "busy.col.detail", 460, False, "text"),
        ("status", "busy.col.status", 120, False, "key"),
    )),
)

#: How many rows each grid shows before it scrolls. A jam grid is rarely more than a
#: couple of lines; the errand queue, the listeners and the timers are where the length
#: is — the queue grid tallest of all, since it also carries the errands that just left.
GROUP_HEIGHT = {"jam": 3, "runs": 4, "claims": 4, "slowest": 4, "threads": 6,
                "listeners": 6, "intake": 6, "timers": 8, "queue": 10}

#: Anything that has been going on this long is drawn amber. A press a person is waiting
#: for is answered in seconds, an errand in tens of them; a minute is where «it is
#: working» turns into «is it stuck?», which is the question this block exists to answer.
SLOW_SEC = 60

#: What the two marked states look like. Foreground only, so a theme that draws its rows
#: dark does not end up with black text on a pale stripe.
MARKS = {"slow": "#a06a00", "stuck": "#c62828"}

#: How much of a DSL step is shown. A step is the line as the recipe wrote it, and a
#: `READ_LUA` step is a whole Lua chunk — measured live at 1 700 characters, which is
#: forty lines of the block for one row and every other section pushed off the screen.
#: What identifies the step is its beginning, so the beginning is what is kept.
STEP_CHARS = 110


def _step(text: str) -> str:
    """One step, short enough to read beside the others. Data, so it is cut, not said."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= STEP_CHARS else text[:STEP_CHARS - 1] + "…"


class BusyView:
    """The «Занятость» block: a control strip and one titled, sortable grid per kind.

    Built by :class:`~panel.tabs.develop.DevelopTab`, which owns the page; kept apart in
    its own module so the tab file stays about the sniffer and the scenarios.
    """

    def __init__(self, tab) -> None:
        self.tab = tab
        self.rt = tab.rt
        self._trees: dict = {}                # group key -> ttk.Treeview
        self._watch = None
        self._foot = None                     # the «ждут окна: N» line under the bar
        self._shown: dict = {}                # group key -> what is on screen already
        self._rows: list = []                 # the flat rows behind every grid
        self._sort: dict = {}                 # group key -> (column, descending)
        self._steps = busymod.StepWatch()
        self._visible = False

    # -- drawing --------------------------------------------------------------
    def build(self, parent, framed: bool = True) -> None:
        """Draw the block into ``parent``.

        ``framed`` puts the titled box back around it — it is what the block wore while
        it shared a column with everything else on «Разработка». On a page of its own the
        page's own name already says «Занятость», and a second copy of the word costs a
        row of a debugger that is read in a hurry (#1415).
        """
        box = (self.tab.tr(ttk.LabelFrame(parent, padding=8), "busy.frame") if framed
               else ttk.Frame(parent, padding=8))
        box.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        bar = ttk.Frame(box)
        bar.pack(fill="x")
        self._watch = tk.BooleanVar(master=self.rt.root, value=True)
        self.tab.tr(ttk.Checkbutton(bar, variable=self._watch,
                                    command=self._on_watch), "busy.watch").pack(
            side="left")
        self.tab.tr(ttk.Button(bar, command=self.refresh), "busy.refresh").pack(
            side="left", padx=(8, 0))
        self.tab.tr(ttk.Button(bar, command=self._copy), "busy.copy").pack(
            side="left", padx=(4, 0))

        self._foot = ttk.Label(box, foreground="#888")
        self._foot.pack(anchor="w", pady=(4, 0))

        scroll = ScrollableFrame(box)
        scroll.pack(fill="both", expand=True, pady=(6, 0))

        self._trees = {}
        for key, title, _sections, columns in GROUPS:
            gframe = self.tab.tr(ttk.LabelFrame(scroll, padding=6), title)
            gframe.pack(fill="x", expand=False, padx=2, pady=(0, 8))
            wrap = ttk.Frame(gframe)
            wrap.pack(fill="both", expand=True)
            tree = ttk.Treeview(wrap, columns=[c[0] for c in columns], show="headings",
                                selectmode="extended", height=GROUP_HEIGHT.get(key, 6))
            vbar = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=vbar.set)
            tree.pack(side="left", fill="both", expand=True)
            vbar.pack(side="right", fill="y")
            for field, _head_key, width, right, _form in columns:
                tree.column(field, width=width, minwidth=50,
                           stretch=(field == "detail"), anchor="e" if right else "w")
                tree.heading(field, command=lambda c=field, gk=key: self._sort_by(gk, c))
            for mark, colour in MARKS.items():
                tree.tag_configure(mark, foreground=colour)
            self._trees[key] = tree

        self._retitle_columns()
        self.rt.i18n.hook(self._retitle_columns, key="busy-columns")

        self.tab.tr(ttk.Label(box, foreground="#888", wraplength=660, justify="left"),
                    "busy.hint").pack(anchor="w", pady=(6, 0))
        self.refresh()

    def _retitle_columns(self) -> None:
        """Every grid's headings, in whatever language is on — plus its own sort arrow."""
        for key, _title, _sections, columns in GROUPS:
            tree = self._trees.get(key)
            if tree is None:
                continue
            column, down = self._sort.get(key, ("", False))
            for field, head_key, _w, _r, _form in columns:
                mark = (" ▼" if down else " ▲") if field == column else ""
                try:
                    tree.heading(field, text=self.tab.t(head_key) + mark)
                except tk.TclError:
                    return

    def _sort_by(self, group: str, column: str) -> None:
        """Click a heading: sort THAT grid by it, and again to turn it round.

        The seconds sort as NUMBERS — the column that matters most is the one a
        string sort would order 100, 12, 9. Every grid keeps its own sort, so clicking
        «секунд» on the timers grid does not touch the listeners grid beside it.
        """
        current, down = self._sort.get(group, ("", False))
        self._sort[group] = (column, not down if column == current else False)
        self._retitle_columns()
        self._shown.pop(group, None)
        self._draw(self._rows)

    # -- lifecycle ------------------------------------------------------------
    def on_show(self) -> None:
        self._visible = True
        self.refresh()
        self._arm()

    def on_hide(self) -> None:
        self._visible = False
        self.rt.tick.disarm(TICK)

    def shutdown(self) -> None:
        self.rt.tick.disarm(TICK)

    def on_language_change(self) -> None:
        self._shown = {}                      # every word is a key: say them again
        self._retitle_columns()
        self.refresh()

    def _arm(self) -> None:
        if self._visible and self._watch is not None and self._watch.get():
            self.rt.tick.arm(TICK, REFRESH_MS, self._tick)

    def _on_watch(self) -> None:
        if self._watch.get():
            self._arm()
        else:
            self.rt.tick.disarm(TICK)

    def _tick(self) -> None:
        self.refresh()
        self._arm()

    # -- the reading ----------------------------------------------------------
    def refresh(self) -> None:
        """Take one snapshot and draw it. On the Tk thread, and cheap enough to be."""
        if not self._trees:
            return
        snap = busymod.snapshot(self.rt)
        self._steps.feed(snap)
        self._rows = self.rows(snap)
        self._draw(self._rows, posted=int(snap.get("posted", 0)))

    def _draw(self, rows: list, posted: "int | None" = None) -> None:
        """Put `rows` into every grid — sorted per grid, and only where something moved."""
        if not self._trees:
            return
        if posted is not None:
            self._say_posted(posted)
        for key, _title, sections, columns in GROUPS:
            tree = self._trees.get(key)
            if tree is None:
                continue
            grows = self._sorted_group(key, [r for r in rows if r["section"] in sections],
                                       columns)
            shown = (tuple(self._cells_for(r, columns) + (r["mark"],) for r in grows)
                    if grows else (self._empty_row(columns),))
            if shown == self._shown.get(key):
                continue                      # nothing moved: do not touch the widget
            self._shown[key] = shown
            try:
                tree.delete(*tree.get_children())
                for cells in shown:
                    tree.insert("", "end", values=cells[:-1],
                                tags=(cells[-1],) if cells[-1] else ())
            except tk.TclError:
                pass                           # the tab is going away

    def _empty_row(self, columns: tuple) -> tuple:
        """A grid with nothing in it still says so (#1500) — it does not just vanish."""
        cells = (self.tab.t("busy.none"),) + tuple("" for _ in columns[1:])
        return cells + ("",)

    def _say_posted(self, count: int) -> None:
        try:
            self._foot.configure(text=self.tab.t("busy.posted", count=count))
        except (tk.TclError, AttributeError):
            pass

    def _cells_for(self, row: dict, columns: tuple) -> tuple:
        """One row as the strings ONE grid shows — words said, data as it is."""
        t = self.tab.t
        out = []
        for field, _head_key, _w, _r, form in columns:
            if field == "secs":
                secs = row.get("secs")
                out.append("" if secs is None else str(int(secs)))
            elif form == "key":
                value = row.get(field)
                out.append(t(value) if value else "")
            else:
                out.append(str(row.get(field) or ""))
        return tuple(out)

    def _sorted_group(self, group: str, rows: list, columns: tuple) -> list:
        """By the clicked column, or — by default — the order the rows were built in.

        The order `rows()` builds a section in is already meaningful (overdue timers
        first, the longest wait first), so an unsorted grid is not «random», it is the
        section's own priority.
        """
        column, down = self._sort.get(group, ("", False))
        if not column:
            return rows
        if column == "secs":
            # As NUMBERS. A string sort here reads 100 · 12 · 9 and buries the row the
            # whole grid is being sorted to find.
            return sorted(rows, key=lambda r: (r.get("secs") is None,
                                               float(r.get("secs") or 0)), reverse=down)
        index = {f: i for i, (f, *_rest) in enumerate(columns)}[column]
        return sorted(rows, key=lambda r: self._cells_for(r, columns)[index].lower(),
                     reverse=down)

    def _copy(self) -> None:
        """Put the snapshot on the clipboard — a jam is usually reported, not fixed.

        As SENTENCES (:meth:`lines`), not as a grid's cells: what is pasted goes into
        a chat or a task, where «идёт: restart_game (200 с)» is read and a row of
        tab-separated fields is not.
        """
        try:
            text = "\n".join(self.lines(busymod.snapshot(self.rt)))
            self.rt.root.clipboard_clear()
            self.rt.root.clipboard_append(text)
        except tk.TclError:
            return
        self.tab.say("panel", "busy.copied")

    # -- the rows ---------------------------------------------------------------
    def rows(self, snap: dict) -> list:
        """The whole snapshot as rows — the drawing's own data, and a test's.

        Each row is ``{"section", "what", "who", "detail", "secs", "level", "status",
        "mark"}``. `status` is always a locale key, said through `t()`; `level` is a
        locale key EXCEPT on a `listeners` row, where it carries the raw «сколько раз
        слышали» count instead (see :data:`GROUPS` — that grid's own column reads it as
        text, not as a key). `what`, `who` and `detail` are data — a script's name, a
        profile, a step — and are shown as they are (`CLAUDE.md`). `mark` is "", "slow"
        or "stuck", and is what makes a jam visible without reading a word.
        """
        t = self.tab.t
        out: list = []

        def add(section, what="", who="", detail="", secs=None, level="", status="",
                mark="") -> None:
            if mark != "stuck" and secs is not None and secs >= SLOW_SEC:
                mark = "slow"
            out.append({"section": section, "what": what, "who": who, "detail": detail,
                        "secs": None if secs is None else int(secs), "level": level,
                        "status": status, "mark": mark})

        # What the snapshot itself already calls a jam — red, and first.
        for verdict in busymod.verdicts(snap):
            add("jam", detail=t(verdict["key"], **verdict["fmt"]),
                status="busy.status.jam", mark="stuck")

        for run in snap["runs"]:
            add("runs", what=run["name"], who=run["tag"] or "?",
                detail=_step(run["step"]), secs=run["secs"],
                status=("busy.status.stopping" if run.get("asked")
                        else "busy.status.running"))
        for step in snap["steps"]:
            add("runs", detail=t(step["key"], **step["fmt"]), secs=step["secs"],
                status="busy.status.running")

        out.extend(self._queue_rows(snap))
        out.extend(self._claim_rows(snap))
        out.extend(self._listener_rows(snap))
        out.extend(self._intake_rows(snap))
        out.extend(self._timer_rows(snap))

        for row in snap["slowest"]:
            add("slowest", what=row["name"], who=row.get("tag") or "?",
                secs=row.get("secs", 0), status="busy.status.done")
        for row in self._steps.top():
            add("slowest", what=row["name"], detail=_step(row["step"]),
                secs=row["secs"], status="busy.status.done")

        for row in snap["threads"]:
            add("threads", what=row["name"], detail=row["where"],
                status="busy.status.live")
        return out

    def _listener_rows(self, snap: dict) -> list:
        """WHAT THIS PROFILE IS LISTENING TO, one row each — the listeners grid (#1416).

        The question the other grids cannot answer. They say what the panel is DOING;
        this says what should have woken it — and, beside each one, whether anything has
        actually come through it and how long ago. A subscription that is up and has
        never heard a thing is indistinguishable from a working one until it is asked to
        say so, and that is what «пропускаются события» looks like from the inside.

        The columns carry the three things the operator asked for: «что» is the stream
        or the event, «подробность» is what it is FOR (the listener's own description,
        plus the last thing it heard), and «состояние» is one of four — running and
        hearing, running and silent for a while, running and never heard anything at
        all, or not running.

        `секунд` is the age of the last thing heard, so a grid sorted by it puts the
        stalest listener at one end and the busiest at the other.
        """
        t = self.tab.t
        rows: list = []
        for row in snap.get("listeners") or ():
            since = row.get("since")
            heard = int(row.get("heard") or 0)
            if not row.get("alive"):
                status, mark = "busy.status.off", "stuck"
            elif not heard:
                # Up, and nothing has ever arrived. Not a fault by itself — a trigger
                # for an event that has not happened is in exactly this state — and the
                # one reading a person cannot get any other way.
                status, mark = "busy.listen.never", ""
            elif since is not None and since >= busymod.LISTENER_QUIET_SEC:
                status, mark = "busy.listen.quiet", "slow"
            else:
                status, mark = "busy.listen.hearing", ""
            detail = t(row["desc"]) if row.get("desc") else ""
            last = str(row.get("detail") or "")
            if last and last != row.get("what"):
                detail = f"{detail} · {last}" if detail else last
            rows.append({"section": "listeners",
                         "what": str(row.get("what") or ""),
                         "who": t("busy.listen.kind." + str(row.get("kind") or "wire")),
                         "detail": detail,
                         # The COUNT belongs beside the row it describes, and the number
                         # column is the age: «слышал 412 раз, последний раз 3 с назад»
                         # is the whole reading, and it is two different numbers.
                         "secs": None if since is None else int(since),
                         "level": str(heard) if heard else "",
                         "status": status,
                         # A listener is never «slow» for being quiet in the ordinary
                         # sense the other sections mean, so the mark is set above rather
                         # than derived from the seconds by `add`.
                         "mark": mark})
        return rows

    def _intake_rows(self, snap: dict) -> list:
        """WHAT EACH RECEIVER DID WITH WHAT IT HEARD — the other half of the row above.

        The listeners grid says whether anything ARRIVED; this says whether the panel
        took it (#1523). The two were never the same question and the gap between them
        is where «события проглатываются» lived: a capture reporting 25 563 tiles and a
        table that grew by nothing are two perfectly healthy-looking listener rows.

        Four numbers per receiver, and only one of them is ever a fault:

        * **принято** — reached this door;
        * **взято** — merged into a model, a store or a table;
        * **отброшено** — declined ON PURPOSE, with a reason (a plain tile among starred
          ones, a row on our own server). Legitimate, and the reasons are in «подробность»
          so a page that shows nothing can be read rather than guessed at;
        * **потеряно** — accepted and then thrown away for a reason that is not about the
          event. Red, always, at any count: an accepted event is processed or queued,
          never discarded.
        """
        t = self.tab.t
        rows: list = []
        for row in snap.get("intake") or ():
            lost = int(row.get("lost") or 0)
            dropped = int(row.get("dropped") or 0)
            seen = int(row.get("seen") or 0)
            since = row.get("since")
            if lost:
                status, mark = "busy.intake.losing", "stuck"
            elif not seen:
                status, mark = "busy.intake.never", ""
            elif since is not None and since >= busymod.LISTENER_QUIET_SEC:
                status, mark = "busy.intake.quiet", "slow"
            else:
                status, mark = "busy.intake.taking", ""
            # WHY, as the receiver's own reason words — data, not sentences: they are
            # the ledger's keys and the whole point is that a drop can be named.
            why = dict(row.get("losses") or {})
            why.update(row.get("reasons") or {})
            detail = " · ".join(f"{name}: {count}"
                                for name, count in sorted(why.items()))
            rows.append({"section": "intake",
                         "what": str(row.get("what") or ""),
                         "seen": str(seen), "kept": str(int(row.get("kept") or 0)),
                         "dropped": str(dropped) if dropped else "",
                         "lost": str(lost) if lost else "",
                         "detail": detail,
                         "secs": None if since is None else int(since),
                         "level": "", "who": "",
                         "status": status, "mark": mark})
        return rows

    def _queue_rows(self, snap: dict) -> list:
        """The live queue, one row per errand — «где посмотреть очередь живьём» (#1500).

        Reads `snap["queue"]` — `panel/timers.py::TimerScheduler.queue_state()`, asked
        straight, not copied — so this grid shows the SAME queue the worker is actually
        working off, in the shape it already keeps: what runs, what waits behind it and
        why, what is turned away because the game's own claim is somebody else's right
        now (cross-referenced against `snap["claims"]`, the one place that says WHO),
        what is parked behind a shut gate and for how much longer (#1416's own
        guarantee — a refusal PARKS a fire rather than dropping it), and what just left
        the queue and how it ended, so a row a person was told «в очереди» about does
        not simply stop answering.

        The ORDER is not one priority number pretending the queue is a line: it is
        running, then what is blocked (held behind the claim, parked behind the gate —
        both need a look), then what is genuinely waiting its FIFO turn, then express
        errands running off to the side of the queue entirely, then the recent past.
        That is the real shape of a single-worker queue with a side door and a
        gate — not a straight line, and drawn as what it is rather than invented as one.
        """
        t = self.tab.t
        queue = snap.get("queue") or {}
        rows: list = []

        def add(**kw) -> None:
            kw.setdefault("section", "queue")
            secs = kw.get("secs")
            if kw.get("mark") != "stuck" and secs is not None and secs >= SLOW_SEC:
                kw["mark"] = "slow"
            rows.append({"what": "", "who": "", "detail": "", "secs": None, "level": "",
                         "status": "", "mark": "", **kw})

        if not queue:
            # The status column already says it; a `detail` repeating the same words is
            # the wall of text this block stopped being.
            add(status="busy.status.off")
            return rows

        def by_word(scheduled, by) -> str:
            if scheduled:
                return t("busy.queued_by.timer")
            if by == "trigger":
                return t("busy.queued_by.trigger")
            return t("busy.queued_by.hand")

        holder = next((row["owner"] for row in snap.get("claims") or ()
                      if row.get("client")), "")

        if queue.get("running"):
            step = next((r["step"] for r in snap.get("runs") or ()
                        if r["name"] == queue["running"]), "")
            add(what=queue["running"], detail=_step(step),
                secs=queue.get("running_secs", 0), status="busy.status.running")
        for name in queue.get("express") or ():
            add(what=name, detail=t("busy.queue.detail.express"),
                status="busy.status.express")
        for item in queue.get("waiting") or ():
            # WHY IT WAITS: the worker is single-file, so everything behind the one
            # running errand waits for exactly one reason — its own turn.
            ahead = (t("busy.queue.detail.ahead", name=queue["running"])
                    if queue.get("running") else "")
            add(what=item["name"], who=by_word(item.get("scheduled"), item.get("by")),
                detail=ahead, secs=item["secs"], status="busy.status.queued")
        for name in queue.get("held") or ():
            # WHY IT WAITS: the panel's own single runner turned it down as busy — most
            # often the game's claim is somebody else's, named here when it is.
            detail = (t("busy.queue.detail.holder", owner=holder) if holder
                     else t("busy.queue.detail.busy"))
            add(what=name, detail=detail, status="busy.status.held", mark="slow")
        for item in queue.get("gated") or ():
            # A FIRE WAITING FOR A DOOR, not for the worker (#1416). It is not «в
            # очереди» — the queue would have run it — and leaving it out of this
            # reading is what made a delayed event indistinguishable from a lost one.
            reason = t(item["reason"]) if item.get("reason") else t("busy.status.gated")
            expires = t("busy.queue.detail.expires",
                       secs=int(item.get("expires_in", 0)))
            add(what=item["name"], who=by_word(item.get("scheduled"), item.get("by")),
                detail=f"{reason} · {expires}", secs=item["secs"],
                status="busy.status.gated",
                mark="stuck" if item.get("expires_in", 0) <= 60 else "slow")
        for item in queue.get("recent") or ():
            # WHAT IT TURNED INTO — nothing that left the queue is silent about it
            # (#1500). Amber for the two outcomes worth a second look; plain for the
            # ordinary ones.
            outcome = item.get("outcome", "")
            add(what=item["name"], who=by_word(item.get("scheduled"), item.get("by")),
                secs=item["secs"], status=f"busy.status.{outcome}" if outcome else "",
                mark="slow" if outcome in ("failed", "gate_expired") else "")
        if not rows:
            add(status="busy.status.idle" if queue.get("alive") else "busy.status.off")
        return rows

    def _claim_rows(self, snap: dict) -> list:
        """Who holds the game, who is queued behind them, and for how long.

        The registry is process-wide on purpose (`panel/runtime/claims.py`), so the rows
        of the profile doing the looking are marked — that is what `mine` is for.
        """
        t = self.tab.t
        rows: list = []
        for row in snap["claims"]:
            refused = int(row.get("refused", 0))
            rows.append({"section": "claims", "what": _key(row["key"]),
                         "who": ("★ " if row.get("mine") else "") + str(row["owner"]),
                         "detail": (t("busy.detail.refused", count=refused)
                                    if refused else ""),
                         "secs": int(row["secs"]), "level": "",
                         "status": "busy.status.holding",
                         "mark": "slow" if row["secs"] >= SLOW_SEC else ""})
        for row in snap["waiting"]:
            rows.append({"section": "claims", "what": _key(row["key"]),
                         "who": str(row["owner"]), "detail": "",
                         "secs": int(row["secs"]),
                         "level": LEVELS.get(row["level"], "busy.level.background"),
                         "status": "busy.status.waiting",
                         "mark": "slow" if row["secs"] >= SLOW_SEC else ""})
        return rows

    def _timer_rows(self, snap: dict) -> list:
        t = self.tab.t
        rows: list = []
        for row in snap["timers"]:
            last = (time.strftime("%H:%M", time.localtime(row["last"])) if row["last"]
                    else "—")
            overdue = row["due_in"] < 0
            rows.append({"section": "timers", "what": row["name"],
                         "who": t(f"busy.state.{row['state']}"),
                         "detail": t("busy.detail.last", last=last),
                         "secs": int(abs(row["due_in"])), "level": "",
                         "status": ("busy.status.overdue" if overdue
                                    else "busy.status.due"),
                         "mark": "stuck" if overdue else ""})
        for row in snap["ticks"]:
            if row["due_in"] < 0:
                rows.append({"section": "timers", "what": row["name"], "who": "",
                             "detail": t("busy.detail.tick"),
                             "secs": int(-row["due_in"]), "level": "",
                             "status": "busy.status.overdue", "mark": "stuck"})
        return rows

    # -- the lines ------------------------------------------------------------
    def lines(self, snap: dict) -> list:
        """The whole block as text: sections of `t(key, …)`, in order of suspicion.

        Separate from :meth:`refresh` so a test can read what the debugger would show
        without a window (`tests/test_panel_busy.py`). Kept as the eight sections of
        `SECTIONS` rather than the seven grids of `GROUPS` — the clipboard is read in a
        chat, where «очередь» and «таймеры» are still two different questions even
        though the screen answers them in one grid.
        """
        t = self.tab.t
        out: list = []

        def section(key: str, rows: list) -> None:
            out.append(f"== {t(key)} ==")
            out.extend(rows[:ROWS] if rows else [t("busy.none")])
            if len(rows) > ROWS:
                out.append(t("busy.more", count=len(rows) - ROWS))
            out.append("")

        section("busy.section.jam",
                [t(v["key"], **v["fmt"]) for v in busymod.verdicts(snap)])

        runs = []
        for run in snap["runs"]:
            key = "busy.run.stopping" if run.get("asked") else "busy.run"
            runs.append(t(key, name=run["name"], who=run["tag"] or "?",
                          secs=int(run["secs"]), step=_step(run["step"]) or "—"))
        for step in snap["steps"]:
            runs.append(t("busy.step", what=t(step["key"], **step["fmt"]),
                          secs=int(step["secs"])))
        section("busy.section.runs", runs)

        section("busy.section.queue", self._queue_lines(snap.get("queue") or {}))
        section("busy.section.claims", self._claim_lines(snap))
        section("busy.section.listeners", self._listener_lines(snap))
        section("busy.section.intake", self._intake_lines(snap))
        section("busy.section.timers", self._timer_lines(snap))
        section("busy.section.slowest", self._slow_lines(snap))
        section("busy.section.threads",
                [t("busy.thread", name=row["name"], where=row["where"])
                 for row in snap["threads"]])
        out.append(t("busy.posted", count=int(snap.get("posted", 0))))
        return out

    def _listener_lines(self, snap: dict) -> list:
        """The listeners as sentences — what the clipboard carries (#1416).

        A jam is usually REPORTED rather than fixed at the keyboard, and «★-цели —
        слушает, тихо 940 с» is a line somebody can paste into a chat, which a row of
        tab-separated cells is not.
        """
        t = self.tab.t
        rows = []
        for row in snap.get("listeners") or ():
            what = str(row.get("what") or "")
            desc = t(row["desc"]) if row.get("desc") else ""
            kind = t("busy.listen.kind." + str(row.get("kind") or "wire"))
            since, heard = row.get("since"), int(row.get("heard") or 0)
            if not row.get("alive"):
                rows.append(t("busy.listen.line.off", what=what, kind=kind, desc=desc))
            elif not heard:
                rows.append(t("busy.listen.line.never", what=what, kind=kind, desc=desc))
            else:
                rows.append(t("busy.listen.line.heard", what=what, kind=kind, desc=desc,
                              count=heard, secs=int(since or 0)))
        return rows

    def _intake_lines(self, snap: dict) -> list:
        """The receivers as sentences — «★-тайлы: принято 25563, взято 41, потеряно 0».

        Same reason as `_listener_lines`: a jam is reported rather than fixed at the
        keyboard, and the receiver that is dropping things has to survive being pasted
        into a chat.
        """
        t = self.tab.t
        rows = []
        for row in snap.get("intake") or ():
            why = dict(row.get("losses") or {})
            why.update(row.get("reasons") or {})
            rows.append(t("busy.intake.line",
                          what=str(row.get("what") or ""),
                          seen=int(row.get("seen") or 0),
                          kept=int(row.get("kept") or 0),
                          dropped=int(row.get("dropped") or 0),
                          lost=int(row.get("lost") or 0),
                          why=", ".join(f"{k}: {v}" for k, v in sorted(why.items()))))
        return rows

    def _queue_lines(self, queue: dict) -> list:
        t = self.tab.t
        if not queue:
            return [t("busy.queue.off")]
        rows = []
        if queue.get("running"):
            rows.append(t("busy.queue.running", name=queue["running"],
                          secs=int(queue.get("running_secs", 0))))
        if queue.get("express"):
            rows.append(t("busy.queue.express", names=", ".join(queue["express"])))
        for item in queue.get("waiting", []):
            rows.append(t("busy.queue.waiting", name=item["name"],
                          secs=int(item["secs"])))
        if queue.get("held"):
            rows.append(t("busy.queue.held", names=", ".join(queue["held"]),
                          secs=int(queue.get("hold_secs", 0))))
        for item in queue.get("gated") or ():
            rows.append(t("busy.queue.gated", name=item["name"],
                          secs=int(item["secs"])))
        if not rows:
            rows.append(t("busy.queue.idle" if queue.get("alive")
                          else "busy.queue.off"))
        return rows

    def _claim_lines(self, snap: dict) -> list:
        t = self.tab.t
        rows = []
        for row in snap["claims"]:
            mark = "→ " if row.get("mine") else "  "
            # `lock=`, never `key=`: the words are said through `t(key, **fmt)`, whose
            # own first argument is called `key` — a placeholder of that name collides
            # with it and every one of these lines fails with «multiple values for
            # argument». The same trap `interrupt.asked` walked into with `tag`.
            rows.append(mark + t("busy.claim", lock=_key(row["key"]),
                                 owner=row["owner"], secs=int(row["secs"]),
                                 refused=int(row.get("refused", 0))))
        for row in snap["waiting"]:
            rows.append("  " + t("busy.wait", lock=_key(row["key"]),
                                 owner=row["owner"], secs=int(row["secs"]),
                                 level=t(LEVELS.get(row["level"],
                                                    "busy.level.background"))))
        return rows

    def _timer_lines(self, snap: dict) -> list:
        t = self.tab.t
        rows = []
        for row in snap["timers"]:
            last = time.strftime("%H:%M", time.localtime(row["last"])) if row["last"] \
                else "—"
            key = "busy.timer.overdue" if row["due_in"] < 0 else "busy.timer"
            rows.append(t(key, name=row["name"], secs=int(abs(row["due_in"])),
                          last=last, state=t(f"busy.state.{row['state']}")))
        for row in snap["ticks"]:
            if row["due_in"] < 0:
                rows.append(t("busy.tick.late", name=row["name"],
                              secs=int(-row["due_in"])))
        return rows

    def _slow_lines(self, snap: dict) -> list:
        t = self.tab.t
        rows = [t("busy.slow.run", name=row["name"], who=row.get("tag") or "?",
                  secs=int(row.get("secs", 0)))
                for row in snap["slowest"]]
        rows += [t("busy.slow.step", name=row["name"], step=_step(row["step"]),
                   secs=int(row["secs"]))
                 for row in self._steps.top()]
        return rows


def _key(key) -> str:
    """A claim key as one short word: a client is its port, the foreground is its name."""
    if isinstance(key, tuple):
        return ":".join(str(part) for part in key)
    return str(key)
