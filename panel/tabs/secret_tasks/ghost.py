"""The tab's third page: «Операция Призрак» — the weekly co-op event's squads (#1251).

The two pages beside it are about the OTHER robbery. A «секретка» is a hero dispatch on
a player's own tile, taken with `hero.dispatch.steal`; a ghost-recon squad is the weekly
event's, taken with `ghost.recon.steal`. Different commands, different five-a-day
budgets, different lists — which is exactly why the squads want a table of their own
rather than a share of somebody else's.

**One read, and it answers everything the page shows.** The client already knows which
squads are out (`ghost.recon.get.task.list`), so there is nothing to poll and nothing to
pan the map for: `ghost_recon_steal.roster` asks once and hands back the event's state
(open day, robberies left) together with every squad, its level, its rank, when it
finished and the game's own verdict on robbing it. A map scan's checkpoint, when the
«Командный пункт» has ever run one, adds the squads of OTHER alliances the client's own
list cannot know — a file read, not a second round trip.

**The event runs ONE DAY A WEEK.** Six days out of seven the honest answer is «событие
закрыто» and an empty table, which the page says in as many words rather than looking
broken.

**Reading and walking the camera, and no robbery.** Ghost-recon's press is not a
scenario yet — it spends a queue a standalone tool fills (`CLAUDE.md`, #1188) — and the
rule about that debt is that it does not get a fourth doorway. The two it already has
(the «Командный пункт» page and the standing order behind it) stay the only ones; this
page shows what is out there and takes the camera to it.
"""
from __future__ import annotations

from tkinter import ttk

from ...widgets import tk_stringvar
from . import grid

# `GhostreconPointStealType` -> the locale key that spells it out. The same four values
# `lua_actions.GHOST_STEAL_NAMES` logs, said in the person's own language instead.
STATE_KEYS = {
    1: "secrettasks.ghost.state.preview",
    2: "secrettasks.ghost.state.can",
    3: "secrettasks.ghost.state.no_steal",
    4: "secrettasks.ghost.state.not_shown",
}


class GhostGrid(grid.TaskGrid):
    """The ghost-recon squads as the same table, filled by the event's own read."""

    TITLE_KEY = "secrettasks.ghost"
    HINT_KEY = "secrettasks.ghost.hint"
    EMPTY_KEY = "secrettasks.ghost.empty"

    def __init__(self, tab) -> None:
        super().__init__(tab)
        # The last read's answer about the event itself: whether today is its day and
        # how many of the five robberies are left. Drawn over the table, and the
        # reason an empty table is not a mystery six days a week.
        self.status: dict = {}
        self._status_var = tk_stringvar(tab.rt.root)

    # -- the event's own line ---------------------------------------------------------
    def build_filters(self, parent) -> None:
        """Not a filter but the same place: whether the event is on, and what is left."""
        ttk.Label(parent, textvariable=self._status_var,
                  foreground="#888").pack(anchor="w", pady=(4, 0))
        self._paint_status()

    def retranslate(self) -> None:
        super().retranslate()
        self._paint_status()

    def _paint_status(self) -> None:
        """Say the event's state in the language now on — «—» before the first read."""
        if not self.status:
            self._status_var.set("")
            return
        self._status_var.set(self.tab.t(
            "secrettasks.ghost.info",
            state=self.tab.t("secrettasks.ghost.open" if self.status.get("open")
                             else "secrettasks.ghost.closed"),
            left=int(self.status.get("left") or 0)))

    # -- the read ------------------------------------------------------------------
    def fetch(self) -> tuple:
        """`(status, records)` — off the Tk thread, called by the tab's worker.

        One game round trip (the dump carries the event's state on its own first line)
        plus the scan checkpoint, which is a file. A closed event still asks: «why is
        this empty» has an answer worth reading, and it is in the status.
        """
        import ghost_recon_steal as ghost_tool

        return ghost_tool.roster(self.tab.rt.game.evaluator(),
                                 scanned=self._scanned())

    def _scanned(self) -> list:
        """The map scan's squads, as dump-shaped records. No checkpoint, no extra rows.

        The game's per-tile gate only answers for a squad in the client's own list, so
        a foreign alliance's tile off the map has no verdict from it — its readiness is
        the clock instead, which `GhostReconMission.can_loot` has already worked out.
        """
        import lastwar_proto as proto
        try:
            missions = proto.load_fresh_ghost_recon(self.tab.rt.profiles.ghost_json())
        except Exception:              # noqa: BLE001 — no file, or a half-written one
            return []
        out = []
        for m in missions:
            if m.uuid is None or m.empty:
                continue
            out.append({"uuid": str(m.uuid), "cfg": m.cfg_id or 0,
                        "srv": m.owner_server or m.target_server or 0,
                        "x": m.x or 0, "y": m.y or 0,
                        "done": m.completion_time or 0, "ends": m.expire_time or 0,
                        "looted": m.steal_count, "can": bool(m.can_loot),
                        "scanned": True})
        return out

    def landed(self, status, records) -> None:
        """A read came back: keep what it said about the event, then draw the squads."""
        self.status = status or {}
        self._paint_status()
        self.apply(records)

    # -- what the rows carry over and above the shared shape -----------------------
    def decorate(self, row, record) -> None:
        """The verdict, the readiness it decides, and whether the squad is my own.

        A ghost squad has no clock to count down to — its `completionTime` is zero
        until it is back, and its `actEndTime` is the event's own end — so readiness is
        the GAME's answer rather than arithmetic, and the state cell says the verdict
        in words instead of drawing a broken countdown (`grid.refresh_timers`).
        """
        row["mine"] = bool(record.get("mine"))
        row["scanned"] = bool(record.get("scanned"))
        row["ready_forced"] = bool(record.get("ready"))
        row["state_key"] = self._state_key(record)

    def update_row(self, row, record) -> None:
        super().update_row(row, record)
        row["starred"] = bool(record.get("starred"))

    @staticmethod
    def _state_key(record) -> str:
        """The locale key for a row's state cell.

        A row read from the client carries the game's own `GhostreconPointStealType`
        and is labelled with it. A row that came off the map has no such verdict, so it
        is labelled off the clock and says «с карты», rather than borrowing a word the
        game did not say.

        MY OWN squad is labelled by what it is DOING — out, or back — rather than by
        the robbery verdict, which for my own tile answers a question nobody asked and
        answers it «можно грабить» (#1251).
        """
        import lastwar_proto as proto

        if record.get("scanned"):
            return ("secrettasks.ghost.state.map_ready" if record.get("ready")
                    else "secrettasks.ghost.state.map_running")
        if record.get("mine"):
            return ("secrettasks.ghost.state.mine_done"
                    if record.get("task_state") == proto.GHOST_STATE_DONE
                    else "secrettasks.ghost.state.not_shown")
        return STATE_KEYS.get(record.get("state"),
                              "secrettasks.ghost.state.not_shown")

    def collectable(self, row) -> bool:
        """Never from here — the ghost robbery lives in «Командный пункт» (#1188).

        Not an oversight: its press spends a queue a standalone tool fills, and a
        third copy of that debt, in a third place, is the thing the rule about it
        forbids. The row still says whether the game would allow the robbery — that is
        what the state cell is for — and the coordinate still walks the camera there.
        """
        return False

    def row_values(self, row) -> tuple:
        """One squad as the cells of the table.

        The tab's own formatting everywhere it fits, and this list's own in the two
        places it does not: a ghost tile's loot slots are the template's rather than a
        secret task's three, and the action cell is empty because this page does not
        rob (see :meth:`collectable`).
        """
        import coords as coords_fmt

        ready = bool(row.get("ready"))
        where = coords_fmt.fmt(row["x"], row["y"])
        if row.get("shared"):
            where = "%s %s" % (grid.SHARED_GLYPH, where)
        owner = (self.tab.t("secrettasks.ghost.own") if row.get("mine") else "")
        return (owner,
                where,
                self.tab.t("secrettasks.server", srv=row["server"]),
                "%s %s" % (grid.READY_GLYPH if ready else grid.TYPE_GLYPH,
                           self.tab._rank(row)),
                row["timer"].get(),
                self.tab.t("secrettasks.ghost.looted",
                           n=int(row["loot_count"] or 0)),
                "")

    # -- the phone -------------------------------------------------------------------
    def web_items(self) -> list:
        """The squads as the phone's card items — a reading, like every list here."""
        import coords

        items = []
        for row in sorted(self.visible_rows(),
                          key=lambda r: (not r.get("ready"),
                                         r.get("completed_at") or float("inf"))):
            facts = [{"label": "secrettasks.col.level", "value": self.tab._rank(row)},
                     {"label": "secrettasks.col.state",
                      "value": self.tab.t(row.get("state_key")
                                          or "secrettasks.ghost.state.not_shown")},
                     {"label": "secrettasks.col.slots",
                      "value": str(int(row.get("loot_count") or 0))}]
            if row.get("mine"):
                facts.append({"label": "secrettasks.ghost.own", "value": ""})
            done, exp = row.get("completed_at"), row.get("expires_at")
            items.append({
                "text": coords.fmt(row.get("x"), row.get("y"), row.get("server")),
                "facts": facts,
                "until": ((exp if row.get("ready") else done) or 0) / 1000.0 or None,
                "pill": "secrettasks.ready" if row.get("ready") else None,
            })
        return items

    def web_rows(self) -> list:
        """The event itself, as the card's own two lines: is it open, and how many left.

        The window draws the same pair beside the table's count — six days a week it is
        the only thing on this page worth reading, and «closed» is not something to
        guess at from an empty list.
        """
        return [{"label": "secrettasks.ghost.state_line",
                 "value": self.tab.t("secrettasks.ghost.open" if self.status.get("open")
                                     else "secrettasks.ghost.closed")},
                {"label": "secrettasks.ghost.left",
                 "value": str(int(self.status.get("left") or 0))}]
