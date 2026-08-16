"""«Серверы» as a menu entry: every warzone the game has, in one grid (#1418).

The game opens warzones continuously — 2 558 of them the day this was written — so this
is a READING and not a table shipped with the panel: `actions/read_server_list.md` asks
the client for the list (`cross.server.ls`), and, when asked to, for the moment each of
them opened (`get.other.server.info`, docs/research/server-info.md). The panel presses
the scenario and draws what came back; it assembles no Lua of its own (`CLAUDE.md`).

IT IS A MENU ENTRY AND NOT A TAB, for the same reason «Веб» is: the list belongs to the
GAME, not to an account. Every profile open in this window would draw the same 2 558
rows out of the same file, and a per-profile copy of one fact is how two of them end up
disagreeing. So the cache is the machine's (`cache/servers.json`,
`tools/lib/server_list.py`) and the window shows it once.

THE PHONE HAS THE SAME LIST — `panel/web/api.py` serves it as the `servers` screen and
draws it with the ordinary renderer, off the SAME model (`tools/lib/server_list.py`)
and with the same four presses. This is not a divergence: it is one reading behind two
front-ends, which is what `CLAUDE.md` asks for. What the phone does not get is the
window's column sorting, because the web renderer has no columns — it gets the same
rows, filtered, as items.

WHICH PROFILE PLAYS IT. The scenario needs a client, and this dialog belongs to the
window rather than to an account, so it is played by whichever profile is on screen when
the button is pressed — exactly as «Веб» says its lines in that profile's log. Reading
the file needs no profile at all.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .paths import ensure

ensure()

import game_clock                                  # noqa: E402  (tools/lib, after ensure)
import server_list as model                       # noqa: E402

from server_list import COLUMNS                    # noqa: E402

#: The one dialog this process has open, if any — a second «Серверы» raises it rather
#: than drawing a second grid over the same file.
_OPEN = None

#: How many rows are drawn at once. A Treeview with 2 558 rows inserts them in about a
#: second, which is a second the window spends frozen every time the filter changes — so
#: the grid draws a page and says how many it is standing on.
PAGE = 300


def open_dialog(parent, rt_get, t) -> "tk.Toplevel | None":
    """Show the grid. ``rt_get()`` is the profile on screen NOW — see the module note."""
    global _OPEN
    if _OPEN is not None:
        try:
            _OPEN.deiconify()
            _OPEN.lift()
            _OPEN.focus_force()
            return _OPEN
        except tk.TclError:                 # it was closed behind our back
            _OPEN = None

    win = tk.Toplevel(parent)
    _OPEN = win
    win.title(t("servers.title"))
    win.transient(parent)
    win.geometry("760x560")
    _Grid(win, rt_get, t)

    def gone(event=None) -> None:
        # ONLY THE WINDOW'S OWN destruction, not a child's: `<Destroy>` bubbles, so every
        # row the grid throws away on a repaint would otherwise report the dialog closed
        # and the next «Серверы» would open a second one over the first.
        global _OPEN
        if event is None or event.widget is win:
            _OPEN = None

    win.bind("<Destroy>", gone)
    return win


class _Grid:
    """The window's half: a search box, a page of rows, and the two presses."""

    def __init__(self, win, rt_get, t) -> None:
        self.win = win
        self.rt_get = rt_get
        self.t = t
        self.data = model.load()
        self.offset = 0
        self.sort_field = "id"
        self.sort_down = False
        self.busy = False

        bar = ttk.Frame(win, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text=t("servers.search")).pack(side="left")
        self.needle = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.needle, width=16)
        entry.pack(side="left", padx=(6, 12))
        entry.bind("<KeyRelease>", lambda _e: self.repaint(reset=True))
        self.only_undated = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text=t("servers.only_undated"),
                        variable=self.only_undated,
                        command=lambda: self.repaint(reset=True)).pack(side="left")
        ttk.Button(bar, text=t("servers.refresh"),
                   command=self.refresh).pack(side="right")
        ttk.Button(bar, text=t("servers.fetch_dates"),
                   command=self.fetch_dates).pack(side="right", padx=6)

        # THE STAR-SECRET-TASK DAY (#1467). The game ships no plan for it, so the panel
        # keeps a book of what was seen and derives the cycle from it — these are the two
        # ways the book grows: read the client's own counts, or write down what the
        # selected warzone is doing today. Neither marks anything «done»: a row here is
        # an OBSERVATION, and the schedule is recomputed from all of them
        # (`panel/runtime/secret_day.py`, `CLAUDE.md`).
        star = ttk.Frame(win, padding=(10, 0, 10, 6))
        star.pack(fill="x")
        ttk.Label(star, text=t("servers.secret.mark")).pack(side="left")
        for state, key in (("day", "servers.secret.state.day"),
                           ("post", "servers.secret.state.post"),
                           ("plain", "servers.secret.state.plain")):
            ttk.Button(star, text=t(key), width=12,
                       command=lambda s=state: self.mark(s)).pack(side="left", padx=(6, 0))
        ttk.Button(star, text=t("servers.secret.read"),
                   command=self.read_secret).pack(side="right")
        self.secret_line = tk.StringVar()
        ttk.Label(star, textvariable=self.secret_line,
                  foreground="#888").pack(side="right", padx=8)

        # THE FOOT IS PACKED BEFORE THE GRID, and that is not a style choice: `pack`
        # hands out what is left over in the order it is called, so a grid that says
        # `expand=True` first takes the whole middle and the status line underneath it
        # is squeezed to nothing.
        foot = ttk.Frame(win, padding=(10, 0, 10, 10))
        foot.pack(side="bottom", fill="x")
        self.status = tk.StringVar()
        ttk.Label(foot, textvariable=self.status, foreground="#888").pack(side="left")
        ttk.Button(foot, text=t("servers.more"), command=self.more).pack(side="right")

        self.tree = ttk.Treeview(win, columns=[c[1] for c in COLUMNS], show="headings")
        for key, field, width, _numeric in COLUMNS:
            self.tree.heading(field, text=t(key),
                              command=lambda f=field: self.sort_by(f))
            self.tree.column(field, width=width, anchor="w")
        bar_y = ttk.Scrollbar(win, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar_y.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 8))
        bar_y.pack(side="left", fill="y", pady=(0, 8), padx=(0, 10))
        self.repaint()

    # -- drawing ------------------------------------------------------------
    def rows(self) -> list:
        # THE GAME's clock decides the stage, not this machine's: the two were eleven
        # seconds apart when `game_clock` was written, and a stage boundary judged on the
        # wrong one is the same class of bug as a countdown that disagrees with the game.
        rows = model.view_rows(self.data, self.needle.get(),
                               self.only_undated.get(), now_ms=game_clock.now_ms())
        rows = self.with_secret(rows)
        return model.sorted_rows(rows, self.sort_field, self.sort_down)

    def book(self):
        """The star-day book of the profile ON SCREEN, or None when there is none.

        Per profile, exactly like the presses below: this dialog belongs to the window
        and the book belongs to an account, because what it is derived from is that
        account's laps and readings (`panel/runtime/secret_day.py`).
        """
        rt = self.rt_get()
        return None if rt is None else rt.secret_days

    def with_secret(self, rows) -> list:
        """The star-day answer on every row, or an empty one when no profile is open."""
        book = self.book()
        if book is None:
            return [dict(row, secret="—", secret_until="—") for row in rows]
        out = []
        for row in book.decorate(rows):
            row["secret"] = self.t("servers.secret.cell",
                                   state=self.t(row["secret_state_key"]),
                                   source=self.t(row["secret_source_key"]))
            out.append(row)
        return out

    def repaint(self, reset: bool = False) -> None:
        if reset:
            self.offset = 0
        rows = self.rows()
        self.tree.delete(*self.tree.get_children())
        for row in rows[:self.offset + PAGE]:
            self.tree.insert("", "end", values=(
                row["id"], row["name"], self.t(row["kind_key"]),
                row["opened"], "—" if row["day"] is None else row["day"],
                row["step"] or "—", self.t(row["stage_key"]), row["until"],
                row.get("secret") or "—", row.get("secret_until") or "—"))
        shown = min(len(rows), self.offset + PAGE)
        totals = model.summary(self.data)
        self.status.set(self.t("servers.status", shown=shown, found=len(rows),
                               total=totals["total"], dated=totals["dated"]))
        self.repaint_secret()

    def repaint_secret(self) -> None:
        """The one line that says how much the derived schedule is worth right now."""
        book = self.book()
        if book is None:
            self.secret_line.set("")
            return
        facts = book.summary()
        self.secret_line.set(self.t(
            "servers.secret.status", seen=facts["observations"],
            servers=facts["servers"], days=facts["days"],
            period="—" if facts["period"] is None else facts["period"],
            clash=facts["conflicts"]))

    def more(self) -> None:
        self.offset += PAGE
        self.repaint()

    def sort_by(self, field: str) -> None:
        self.sort_down = not self.sort_down if self.sort_field == field else False
        self.sort_field = field
        self.repaint(reset=True)

    # -- the two presses ----------------------------------------------------
    def refresh(self) -> None:
        """Re-read the list from the game: new warzones appear, none disappear."""
        self.play({"store": "", "dates": 0}, "servers.log.list")

    def fetch_dates(self) -> None:
        """Ask when the still-undated warzones opened — thousands of messages, batched.

        Bounded by what is missing, so pressing it twice does not ask the server for
        anything it has already answered.
        """
        missing = len(model.undated(self.data))
        if not missing:
            self.status.set(self.t("servers.all_dated"))
            return
        self.play({"store": "", "dates": missing}, "servers.log.dates")

    # -- the star-secret-task day -------------------------------------------
    def selected_server(self) -> int:
        """The warzone of the row the person has selected, or 0 if none is."""
        chosen = self.tree.selection()
        if not chosen:
            return 0
        try:
            return int(self.tree.item(chosen[0], "values")[0])
        except (IndexError, TypeError, ValueError):
            return 0

    def mark(self, state: str) -> None:
        """Write down what the selected warzone is doing TODAY.

        An observation, not a tick: nothing here says a job was done, and the schedule
        stays derived from every row rather than from this one (`CLAUDE.md` — a press may
        start something, and may never mark something the game is the authority on; the
        game is not the authority on this, it never says it).
        """
        book = self.book()
        server = self.selected_server()
        if book is None or not server:
            self.status.set(self.t("servers.secret.no_row"))
            return
        book.record(server, book.today(), state, source="observed",
                    seen_at=game_clock.now_ms())
        rt = self.rt_get()
        if rt is not None:
            rt.say("servers", "servers.secret.log.marked", server=server,
                   state=self.t("servers.secret.state.%s" % state))
        self.repaint()

    def read_secret(self) -> None:
        """Play `read_secret_day.md` and write down what the client was holding.

        The counts are evidence rather than a verdict — how many of the alliance's live
        dispatch tasks on each warzone are starred — and they become a state only once
        labelled days exist to calibrate them against (`tools/lib/secret_day.py`).
        """
        rt = self.rt_get()
        book = self.book()
        if rt is None or book is None or self.busy:
            return
        self.busy = True
        self.status.set(self.t("servers.working"))
        rt.say("servers", "servers.secret.log.read")

        def done(outcome=None) -> None:
            self.busy = False
            got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
            written = book.take_reading(got)
            if rt is not None:
                rt.say("servers", "servers.secret.log.recorded", count=written)
            try:
                self.repaint()
            except tk.TclError:                 # the dialog was closed while it ran
                pass

        started = rt.play_async("read_secret_day", args={"server": 0}, tag="servers",
                                on_done=done)
        if not started:
            self.busy = False
            self.status.set(self.t("servers.busy"))

    def play(self, args: dict, log_key: str) -> None:
        rt = self.rt_get()
        if rt is None or self.busy:
            return
        self.busy = True
        self.status.set(self.t("servers.working"))
        rt.say("servers", log_key)

        def done(_outcome=None) -> None:
            self.busy = False
            self.data = model.load()
            try:
                self.repaint()
            except tk.TclError:             # the dialog was closed while it ran
                pass

        started = rt.play_async("read_server_list", args=args, tag="servers",
                                on_done=done)
        if not started:
            self.busy = False
            self.status.set(self.t("servers.busy"))
