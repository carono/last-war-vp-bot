"""The tab's second table: every live secret task of the player's own alliance (#1244).

The list above it is a WORKING list — the starred raid targets, gathered over time from
two sources (the capture's checkpoint and the VM), kept across a restart, added to by a
mate's share and emptied by «Очистить список». That is what auto-loot weighs, and it is
narrowed to the stars on purpose: a robbery is one of five a day, so the tiles worth one
are the tiles worth a row.

This one answers a different question — «what does my alliance actually have out right
now?» — so it is not a working list at all but a MIRROR of the game's own table
(`ActDispatchTaskDataManager.allianceTask`), stars and plain tiles alike. It is replaced
whole by every read rather than merged into: a tile the game no longer lists is a tile
that is gone, and nothing here is worth keeping past the answer that produced it. That
is also why it needs no checkpoint of its own — the game is the checkpoint, and the read
that fills this grid is the one `on_show` already makes.

The table itself is deliberately identical to the one above (`grid.py`): same columns,
same countdown, same colours, the same click on a coordinate that walks the camera and
the same click on the action cell that robs the tile. Only the contents differ.

**What the read leaves out.** The chunk behind it (`secret_task_all_alliance`) keeps the
tiles that are still on the map and still have a free loot slot, so a task with all
three slots spent is not here — it is finished for everybody and there is nothing left
to do about it. That is the same rule the grid above hides a 3/3 tile under, minus the
«Показывать исчерпанные» escape hatch, which exists up there only because the WIRE feed
reports spent tiles at all.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ...widgets import tk_stringvar
from . import grid


class AllianceGrid:
    """The alliance's own secret tasks as the same table, filled by the VM read."""

    def __init__(self, tab) -> None:
        self.tab = tab
        # uuid (str) -> the row record `grid.new_row` makes. Replaced wholesale by
        # `apply`; nothing here outlives the game's own answer.
        self._rows: dict = {}
        self._tree = None
        self._body = None
        self._empty = None
        self._sort = None            # (column id, reversed) once a heading is clicked
        self._count_var = tk_stringvar(tab.rt.root)

    # -- building ---------------------------------------------------------------
    def build(self, parent) -> ttk.Frame:
        """The framed table, ready to be added to the tab's split pane."""
        frame = self.tab.tr(ttk.LabelFrame(parent, padding=6), "secrettasks.alliance")
        head = ttk.Frame(frame)
        head.pack(fill="x")
        self.tab.tr(ttk.Label(head, foreground="#888", wraplength=640,
                              justify="left"), "secrettasks.alliance.hint").pack(
            side="left")
        ttk.Label(head, textvariable=self._count_var, foreground="#888").pack(
            side="right")

        wrap = ttk.Frame(frame)
        wrap.pack(fill="both", expand=True, pady=(4, 0))
        self._empty = self.tab.tr(ttk.Label(wrap, foreground="#888"),
                                  "secrettasks.alliance.empty")
        self._body = ttk.Frame(wrap)
        self._body.pack(fill="both", expand=True)

        tree = grid.make_tree(self._body)
        tree.bind("<Button-1>", self._on_click)
        tree.bind("<Double-Button-1>", self._on_double_click)
        tree.bind("<Button-3>", self._on_right_click)
        tree.bind("<Motion>", self._on_motion)
        self._tree = tree
        self.retranslate()
        self._update_count()
        return frame

    def retranslate(self) -> None:
        """(Re)write the headings in the language now on, and re-arm their sorts."""
        if self._tree is None:
            return
        try:
            for col, key, _w, _a, _s in grid.COLUMNS:
                self._tree.heading(col, text=self.tab.t(key))
            grid.heading_command(self._tree, self._sort_by)
        except tk.TclError:
            return

    # -- the list ----------------------------------------------------------------
    def apply(self, tasks) -> None:
        """Replace the grid with what the game's own alliance table just said.

        Wholesale, not a merge (see the module docstring): a tile the read does not
        carry has either expired or filled its last slot, and either way the game is
        the authority on it. A row that IS still there keeps its countdown variable, so
        the cell it is drawn in does not blink on every refresh.
        """
        rows: dict = {}
        for task in tasks or ():
            key = str(task.uuid)
            row = self._rows.get(key)
            if row is None:
                row = grid.new_row(task, tk_stringvar(self.tab.rt.root))
            else:
                row["expires_at"] = task.expires_at
                row["completed_at"] = task.completed_at
                row["loot_count"] = task.loot_count
                row["level"] = task.level
            rows[key] = row
        self._rows = rows
        self.render()

    def clear(self) -> None:
        """Drop every row — the profile switched, or the game went away."""
        self._rows = {}
        self.render()

    def drop(self, key: str) -> None:
        """Forget one tile: it was robbed from either grid and is spent for us."""
        if self._rows.pop(str(key), None) is not None:
            self.render()

    def tick(self) -> None:
        """The per-second half, driven by the tab's own countdown chain.

        Same arithmetic as the grid above — the timers are rewritten, an expired tile
        drops, and only a state change costs a full redraw.
        """
        if self._tree is None:
            return
        expired, changed = grid.refresh_timers(self._rows, self.tab.t)
        for key in expired:
            self._rows.pop(key, None)
        if expired or changed:
            self.render()
        else:
            grid.paint_timers(self._tree, self._rows)

    # -- drawing ------------------------------------------------------------------
    def render(self) -> None:
        """Rebuild the table from the current rows, in the order the headings ask for."""
        tree = self._tree
        if tree is None:
            return
        grid.refresh_timers(self._rows, self.tab.t)
        chosen = set(tree.selection())
        for iid in tree.get_children(""):
            tree.delete(iid)
        rows = grid.sort_rows(list(self._rows.values()), self._sort)
        for row in rows:
            tree.insert("", "end", iid=str(row["uuid"]),
                        values=self.tab._row_values(row), tags=(grid.row_tag(row),))
        back = [iid for iid in chosen if tree.exists(iid)]
        if back:
            tree.selection_set(back)
        self._show_empty(not rows)
        self._update_count()

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
        self._count_var.set(self.tab.t("secrettasks.count", n=len(self._rows))
                            if self._rows else "")

    def _sort_by(self, column: str) -> None:
        """A heading was clicked: sort by it, and flip the direction on a second click."""
        if self._sort and self._sort[0] == column:
            self._sort = (column, not self._sort[1])
        else:
            self._sort = (column, False)
        self.render()

    # -- what a click does ---------------------------------------------------------
    def _row_at(self, event):
        return self._rows.get(self._tree.identify_row(event.y)) if self._tree else None

    def _on_click(self, event) -> None:
        """The same two live cells the grid above has: the coordinate and the action."""
        where = grid.column_at(self._tree, event)
        row = self._row_at(event)
        if row is None:
            return
        if where == grid.LINK_COLUMN:
            self.tab._jump_to_row(row)
        elif where == grid.ACTION_COLUMN and self.tab._collectable(row):
            self.tab._collect(row)

    def _on_double_click(self, event) -> None:
        row = self._row_at(event)
        if row is not None and self.tab._collectable(row):
            self.tab._collect(row)

    def _on_motion(self, event) -> None:
        """The link cursor over a cell that acts, the ordinary one everywhere else."""
        where = grid.column_at(self._tree, event)
        row = self._row_at(event)
        live = where == grid.LINK_COLUMN or (
            where == grid.ACTION_COLUMN and bool(row and self.tab._collectable(row)))
        try:
            self._tree.configure(cursor="hand2" if live else "")
        except tk.TclError:
            pass

    def _on_right_click(self, event) -> None:
        """The row's own menu, under the pointer: jump, collect, share."""
        tree = self._tree
        iid = tree.identify_row(event.y) if tree is not None else ""
        row = self._rows.get(iid)
        if row is None:
            return
        tree.selection_set(iid)
        # Imported here, not at the top: the tab module imports THIS one, so a
        # module-level import back into it would be a circle.
        from .tab import SHARE_ALLIANCE, SHARE_WORLD

        tab = self.tab
        menu = tk.Menu(tab.rt.root, tearoff=0)
        menu.add_command(label=tab.t("secrettasks.goto"),
                         command=lambda: tab._jump_to_row(row))
        if tab._collectable(row):
            menu.add_command(label=tab.t("secrettasks.collect"),
                             command=lambda: tab._collect(row))
        menu.add_separator()
        menu.add_command(label=tab.t("secrettasks.share_alliance"),
                         command=lambda: tab._share(row, SHARE_ALLIANCE))
        menu.add_command(label=tab.t("secrettasks.share_world"),
                         command=lambda: tab._share(row, SHARE_WORLD))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # -- the phone ------------------------------------------------------------------
    def web_items(self) -> list:
        """The rows as the phone's card items — same shape as the grid above's.

        A reading, like everything else this tab hands the web: the robbery still
        spawns its own tool (`CLAUDE.md`, #1188), so neither grid offers a press there.
        """
        import coords

        items = []
        # Ready first, then whatever runs out soonest — the phone's order on the card
        # above, so the two lists on one screen do not read in two different orders.
        for row in sorted(self._rows.values(),
                          key=lambda r: (not r.get("ready"),
                                         r.get("expires_at") or float("inf"))):
            done, exp = row.get("completed_at"), row.get("expires_at")
            items.append({
                "text": coords.fmt(row.get("x"), row.get("y"), row.get("server")),
                "facts": [{"label": "secrettasks.col.level",
                           "value": str(row.get("level"))},
                          {"label": "secrettasks.col.slots",
                           "value": f"{row.get('loot_count')}/3"}],
                "until": ((exp if row.get("ready") else done) or 0) / 1000.0 or None,
                "pill": "secrettasks.ready" if row.get("ready") else None,
            })
        return items
