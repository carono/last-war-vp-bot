"""The tab's second table: what the player's own alliance is running right now (#1244).

The list above it is a WORKING list — the starred raid targets, gathered over time from
two sources (the capture's checkpoint and the VM), kept across a restart, added to by a
mate's share and emptied by «Очистить список». That is what auto-loot weighs, and it is
narrowed to the stars on purpose: a robbery is one of five a day, so the tiles worth one
are the tiles worth a row.

This one answers a different question — «WHICH OF MY ALLIANCEMATES IS RUNNING WHAT» —
and so it is not a working list at all but a MIRROR of the game's own
`ActDispatchTaskDataManager.allianceTask`: one row per task an alliance member has out,
with the member's name on it, its rank, when it finishes and how many times it has been
robbed already. Nothing is filtered out of it — not the plain tiles the star rule drops,
not the ones already robbed three times, not the one-per-player special class — because
every one of them is somebody's task and the question is what they are all doing.

It is replaced whole by every read rather than merged into: a task the game no longer
lists has ended, and nothing here is worth keeping past the answer that produced it.
That is also why it needs no checkpoint of its own — the game is the checkpoint.

The read is its own (`dispatch_tasks.alliance_roster`, driven from the tab's
`_roster`), because the raid read cannot answer this: it is filtered to the robbable and
it carries no owner name at all. It is also the tab's slowest round trip, which is why
it happens when the tab is opened, when «Обновить» is pressed and when the profile
changes — and NOT on a mate's share, which changes the raid list rather than who is
running what.

The table itself is deliberately identical to the one above (`grid.py`): same columns,
same countdown, same colours, the same click on a coordinate that walks the camera and
the same click on the action cell that robs the tile. Only the contents differ — and the
owner column, which the list above leaves empty because a tile off the wire has no name
attached to it.
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
    def apply(self, records) -> None:
        """Replace the grid with what the game's own alliance table just said.

        ``records`` are `dispatch_tasks.alliance_roster`'s. Wholesale, not a merge (see
        the module docstring): a task the read does not carry has ended, and the game is
        the authority on that. A row that IS still there keeps its countdown variable, so
        the cell it is drawn in does not blink on every refresh.
        """
        rows: dict = {}
        for record in records or ():
            key = str(record["uuid"])
            row = self._rows.get(key)
            if row is None:
                row = grid.new_row(record, tk_stringvar(self.tab.rt.root))
            else:
                row["expires_at"] = record.get("expires_at")
                row["completed_at"] = record.get("completed_at")
                row["loot_count"] = record.get("loot_count") or 0
                row["level"] = record.get("level")
                row["owner_name"] = record.get("owner_name") or ""
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
        expired, changed = self._refresh_timers()
        for key in expired:
            self._rows.pop(key, None)
        if expired or changed:
            self.render()
        else:
            grid.paint_timers(self._tree, self._rows)

    def _refresh_timers(self) -> tuple:
        """The countdowns, with the «уже поделились» mark stamped on first (#1245).

        The very same two steps the table above takes (`SecretTasksTab._refresh_timers`)
        — one store of shared tiles, read by both grids, so a task marked on one of them
        is marked on the other in the same second.
        """
        marked = self.tab.shared.apply(self._rows)
        expired, changed = grid.refresh_timers(self._rows, self.tab.t)
        return expired, changed or marked

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
            # Who is running it comes first: on the phone this list is read to find
            # a name, the way the window's list is read to find a countdown.
            facts = [{"label": "secrettasks.col.owner",
                      "value": row.get("owner_name") or "—"},
                     # The rank the window draws in its own cell — the star only
                     # where the game puts one (#1244), never as decoration.
                     {"label": "secrettasks.col.level",
                      "value": self.tab._rank(row)},
                     {"label": "secrettasks.col.slots",
                      "value": f"{row.get('loot_count')}/3"}]
            # …and the same «уже поделились» the window draws on this table (#1245):
            # the glyph on the coordinate, the words in the line under it.
            text = coords.fmt(row.get("x"), row.get("y"), row.get("server"))
            if row.get("shared"):
                text = "%s %s" % (grid.SHARED_GLYPH, text)
                facts.append({"label": "secrettasks.shared_mark", "value": ""})
            items.append({
                "text": text,
                "facts": facts,
                "until": ((exp if row.get("ready") else done) or 0) / 1000.0 or None,
                "pill": "secrettasks.ready" if row.get("ready") else None,
            })
        return items
