"""The tab's alliance page: what the player's own alliance is running right now (#1244).

The ★ page beside it is a WORKING list — the starred raid targets, gathered over time
from two sources (the capture's checkpoint and the VM), kept across a restart, added to
by a mate's share and emptied by «Очистить список». That is what auto-loot weighs, and
it is narrowed to the stars on purpose: a robbery is one of five a day, so the tiles
worth one are the tiles worth a row.

This one answers a different question — «WHICH OF MY ALLIANCEMATES IS RUNNING WHAT» —
and so it is not a working list at all but a MIRROR of the game's own
`ActDispatchTaskDataManager.allianceTask`: one row per task an alliance member has out,
with the member's name on it, its rank, when it finishes and how many times it has been
robbed already. The READ filters nothing out — not the plain tiles the star rule drops,
not the ones already robbed three times — because every one of them is somebody's task
and the question is what they are all doing.

What the EYE is shown is the operator's own choice, and that is what the two boxes over
the table are (#1251): «UR» keeps the top rarity, «Звезда» keeps the tasks the game
draws a star on. Both are off by default — the mirror shows the whole alliance until
somebody says otherwise — and both are display rules only: they hide rows, they change
no robbery and they touch no game.

THIS PAGE IS A MIRROR, AND DELIBERATELY THE ONLY ONE. It is replaced whole by every
read rather than merged into — the operator's own ruling, confirmed when the rest of
the tab was moved the other way (#1251): «Задания альянса списком, всё верно, он один
и всегда актуален, чего нет, значит протухло.» The read hands over the entire table
every time (200 tasks live from 52 members), so a task it stops listing has ended, and
a row kept past that answer would be a raid that no longer exists.

Every OTHER page here accumulates, because no read of theirs can restate the whole
truth: a lap of the map shows the patch it drove over, and the client's own ghost lists
were watched emptying mid-event as squads came home. **Do not make this one accumulate
to match them.** `tests/test_panel_secret_tasks.py` fails if it starts to — the
distinction is the point, not an oversight.

Not accumulating is also why it needs no checkpoint of its own: the game is the
checkpoint.

The read is its own (`dispatch_tasks.alliance_roster`, driven from the tab's
`_roster`), because the raid read cannot answer this: it is filtered to the robbable and
it carries no owner name at all. It is also the tab's slowest round trip, which is why
it happens when the tab is opened, when «Обновить» is pressed and when the profile
changes — and NOT on a mate's share, which changes the raid list rather than who is
running what.

The table itself is the one every page here draws (`grid.TaskGrid`): same columns, same
countdown, same colours, the same click on a coordinate that walks the camera and the
same click on the action cell that robs the tile. Only the contents differ — and the
owner column, which the ★ page leaves empty because a tile off the wire has no name
attached to it.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import grid


class AllianceGrid(grid.TaskGrid):
    """The alliance's own secret tasks as the same table, filled by the VM read."""

    CONFIG_KEY = "alliance"
    TITLE_KEY = "secrettasks.alliance"
    HINT_KEY = "secrettasks.alliance.hint"
    EMPTY_KEY = "secrettasks.alliance.empty"

    def __init__(self, tab) -> None:
        super().__init__(tab)
        # The two display rules over this table (#1251). Off by default: a mirror that
        # hides most of what it mirrors before anybody asks it to is not a mirror.
        self.ur_var = tk.BooleanVar(master=tab.rt.root, value=False)
        self.star_var = tk.BooleanVar(master=tab.rt.root, value=False)

    # -- the boxes ----------------------------------------------------------------
    def extra_filters(self, bar) -> None:
        """«UR» and «Звезда», beside this page's own level range.

        On the page rather than on the tab, like every filter here since #1251: they
        narrow THIS list and nothing else, and a box that reached across pages would be
        a different feature wearing the same two words.
        """
        self.tab.tr(ttk.Checkbutton(bar, variable=self.ur_var,
                                    command=self.refilter),
                    "secrettasks.filter.ur").pack(side="left", padx=(16, 0))
        self.tab.tr(ttk.Checkbutton(bar, variable=self.star_var,
                                    command=self.refilter),
                    "secrettasks.filter.star").pack(side="left", padx=(12, 0))

    def narrow(self, rows) -> list:
        """The rows the two boxes let through — everything while neither is ticked."""
        if self.ur_var.get():
            rows = [r for r in rows if grid.is_ur(r)]
        if self.star_var.get():
            rows = [r for r in rows if r.get("starred")]
        return rows

    def config(self) -> dict:
        return dict(super().config(), ur_only=bool(self.ur_var.get()),
                    star_only=bool(self.star_var.get()))

    def apply_config(self, raw) -> None:
        super().apply_config(raw)
        raw = raw if isinstance(raw, dict) else {}
        self.ur_var.set(bool(raw.get("ur_only", False)))
        self.star_var.set(bool(raw.get("star_only", False)))

    def persist_vars(self) -> list:
        return super().persist_vars() + [self.ur_var, self.star_var]

    # -- what a right-click offers -------------------------------------------------
    def fill_menu(self, menu, row) -> None:
        """Jump, collect where the tile allows it, and the two ways of sharing it."""
        # Imported here, not at the top: the tab module imports THIS one, so a
        # module-level import back into it would be a circle.
        from .tab import SHARE_ALLIANCE, SHARE_WORLD

        tab = self.tab
        super().fill_menu(menu, row)
        if self.collectable(row):
            menu.add_command(label=tab.t("secrettasks.collect"),
                             command=lambda: tab._collect(row))
        menu.add_separator()
        menu.add_command(label=tab.t("secrettasks.share_alliance"),
                         command=lambda: tab._share(row, SHARE_ALLIANCE))
        menu.add_command(label=tab.t("secrettasks.share_world"),
                         command=lambda: tab._share(row, SHARE_WORLD))

    # -- the phone ------------------------------------------------------------------
    def web_items(self) -> list:
        """The rows as the phone's card items — same shape, and under the same boxes.

        A reading, like everything else this tab hands the web: the robbery still spawns
        its own tool to park the targets before the recipe presses (`CLAUDE.md`, #1188),
        so no grid offers a press there.
        """
        import coords

        items = []
        # Ready first, then whatever runs out soonest — the phone's order on the card
        # above, so the lists on one screen do not read in different orders.
        for row in sorted(self.visible_rows(),
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
