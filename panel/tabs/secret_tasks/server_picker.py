"""«Куда идти сегодня» — the warzones around ours, coloured by their star-secret day.

The operator asked for it in one sentence: a magnifier beside the «Сервер» box, a grid of
warzones like the one a player-made cycle chart draws, and a click that GOES there rather
than filling a field in.

**What the grid knows.** Each cell is a warzone a robbery is POSSIBLE on
(`server_list.same_phase` — the warzones standing in the same season and the same stage
of it as ours, #1471). It was a run of consecutive numbers around us to begin with, which
drew plenty of cells the game does not open to this account: «показывается от начала
сервера, а там грабить нельзя». A cell's colour is the state this profile's book answers
for it TODAY — the star day, the day after it, an ordinary day, or nothing known — and the
line under the grid says how many of each there are. Nothing here reads the game: the
slice is the season plan already on disk and the states come out of `rt.secret_days`,
which is arithmetic over rows already on disk.

**A click is a jump.** The same `rt.game.jump` every coordinate in the panel walks
through, at the coordinates the tab's own boxes are holding — so «the same tile on the
next warzone» is one click — and the middle of the map when they are empty. The window
closes on the way, because the point of the grid is to leave it.

**The phone has the same grid**, drawn as items on the ★ tab's own screen with the same
states and the same press behind them (`SecretTasksTab.web_view` / `web_press`); this file
is the window's half only.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

#: How many cells go on one row of the grid. Sixteen keeps a hundred-odd warzones inside
#: a window a person can read without scrolling, at the width the numbers need.
COLUMNS = 16

#: The colour of a cell per state. Yellow for the star day is the one the player-made
#: charts use and the one the operator's own screenshot showed, so it is the one a person
#: already reads without a legend; the legend is under the grid anyway.
COLOURS = {"day": "#ffd24d", "post": "#ffe9a8", "plain": "#eceff1",
           "unknown": "#f7f7f7"}

#: …and the ink, so the two pale ones stay legible.
INK = {"day": "#3a2f00", "post": "#4a3c00", "plain": "#37474f", "unknown": "#9e9e9e"}

#: The one picker a window has open, so a second press raises the first rather than
#: drawing a second grid over the same book.
_OPEN = None


def open_picker(tab) -> "tk.Toplevel | None":
    """Show the grid for `tab`'s profile. A second press raises what is already open."""
    global _OPEN
    if _OPEN is not None:
        try:
            _OPEN.deiconify()
            _OPEN.lift()
            _OPEN.focus_force()
            return _OPEN
        except tk.TclError:                      # closed behind our back
            _OPEN = None
    win = tk.Toplevel(tab.parent)
    _OPEN = win
    win.title(tab.t("secrettasks.picker.title"))
    win.transient(tab.parent.winfo_toplevel())
    _Grid(win, tab)

    def gone(event=None) -> None:
        global _OPEN
        if event is None or event.widget is win:
            _OPEN = None

    win.bind("<Destroy>", gone)
    return win


class _Grid:
    """The window's half: a legend, a grid of warzones, and one line of counts."""

    def __init__(self, win, tab) -> None:
        self.win = win
        self.tab = tab
        self.rt = tab.rt

        head = ttk.Frame(win, padding=(10, 8, 10, 4))
        head.pack(fill="x")
        tab.tr(ttk.Label(head), "secrettasks.picker.hint").pack(side="left")
        tab.tr(ttk.Button(head, command=self.repaint),
               "secrettasks.picker.refresh").pack(side="right")

        # WHICH SLICE THIS IS, in words (#1471). The grid is no longer «the numbers next
        # to ours» but «the warzones the game opens to us today», and a person cannot tell
        # one from the other by looking at the cells — so the rule is written above them.
        self.slice = tk.StringVar()
        band = ttk.Frame(win, padding=(10, 0, 10, 4))
        band.pack(fill="x")
        ttk.Label(band, textvariable=self.slice).pack(side="left")

        legend = ttk.Frame(win, padding=(10, 0, 10, 6))
        legend.pack(fill="x")
        for state in ("day", "post", "plain"):
            box = tk.Label(legend, text="  ", background=COLOURS[state],
                           relief="solid", borderwidth=1)
            box.pack(side="left", padx=(0, 4))
            tab.tr(ttk.Label(legend), "servers.secret.state.%s" % state).pack(
                side="left", padx=(0, 12))

        self.body = ttk.Frame(win, padding=(10, 0, 10, 6))
        self.body.pack(fill="both", expand=True)

        foot = ttk.Frame(win, padding=(10, 0, 10, 10))
        foot.pack(fill="x")
        self.status = tk.StringVar()
        ttk.Label(foot, textvariable=self.status, foreground="#888").pack(side="left")
        self.repaint()

    # -- drawing --------------------------------------------------------------
    def view(self) -> dict:
        """The slice and its cells — the phone's own reading too.

        Built by the tab so the two front-ends cannot drift: `SecretTasksTab.picker_view`
        is what `web_view` draws as well.
        """
        return self.tab.picker_view()

    def repaint(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        view = self.view()
        rows = view["rows"]
        self.slice.set(self.tab.t("secrettasks.picker.slice", step=view["step"],
                                  stage=self.tab.t(view["stage_key"]),
                                  first=view["first"], last=view["last"]))
        tally = {"day": 0, "post": 0, "plain": 0, "unknown": 0}
        for index, row in enumerate(rows):
            state = row.get("state") or "unknown"
            tally[state] = tally.get(state, 0) + 1
            cell = tk.Button(self.body, text=str(row["server"]), width=5,
                             background=COLOURS.get(state, COLOURS["unknown"]),
                             foreground=INK.get(state, INK["unknown"]),
                             relief="ridge", borderwidth=1,
                             command=lambda s=row["server"]: self.go(s))
            cell.grid(row=index // COLUMNS, column=index % COLUMNS,
                      padx=1, pady=1, sticky="ew")
        for column in range(COLUMNS):
            self.body.grid_columnconfigure(column, weight=1)
        self.status.set(self.tab.t("secrettasks.picker.status", total=len(rows),
                                   day=tally["day"], post=tally["post"],
                                   plain=tally["plain"]))

    # -- the press ------------------------------------------------------------
    def go(self, server: int) -> None:
        """Walk the camera to that warzone and close — «при клике сразу переходим»."""
        self.tab.jump_to_server(server)
        try:
            self.win.destroy()
        except tk.TclError:                      # already gone
            pass
