"""The tab's «Операция Призрак» pages: my own squads, and my alliancemates' (#1251).

The pages beside them are about the OTHER robbery. A «секретка» is a hero dispatch on
a player's own tile, taken with `hero.dispatch.steal`; a ghost-recon squad is the weekly
event's, taken with `ghost.recon.steal`. Different commands, different five-a-day
budgets, different lists — which is why the squads want tables of their own rather than
a share of somebody else's.

**Two pages, one read.** The client keeps my own squads and the alliance's in a single
list once both have been asked for, so `ghost_recon_steal.roster` answers once and the
tab hands each page the half that is its own (`mine`). They are two tables because they
are two questions — «where are my three out» and «who of the alliance is running what»
— and one table holding both answers neither.

**Nothing here is arithmetic over an id.** The level, the rarity, the star and how many
robberies a tile allows come from the event's own config row, which the client carries
per template; the cfgId is a fallback for a template it has not loaded. That is the
lesson #1244 cost on the other robbery, where home-made digit-splitting invented both a
star and a «level 99».

**The event runs ONE DAY A WEEK.** Six days out of seven the honest answer is «событие
закрыто» and two empty tables, which the pages say in as many words rather than looking
broken.

**Reading and walking the camera, and no robbery.** Ghost-recon's press is not a
scenario yet — it spends a queue a standalone tool fills (`CLAUDE.md`, #1188) — and the
rule about that debt is that it does not get more doorways. The two it already has (the
«Командный пункт» page and the standing order behind it) stay the only ones; these
pages show what is out there and take the camera to it. The tiles of OTHER alliances,
which a map scan finds and these two lists cannot know, are on that tab for the same
reason: they are what a robbery is aimed at, and this is not where robbing happens.
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


class _GhostGrid(grid.TaskGrid):
    """What both ghost pages are: the same table, filled from the same read."""

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
        """Say the event's state in the language now on — nothing before the first read."""
        if not self.status:
            self._status_var.set("")
            return
        self._status_var.set(self.tab.t(
            "secrettasks.ghost.info",
            state=self.tab.t("secrettasks.ghost.open" if self.status.get("open")
                             else "secrettasks.ghost.closed"),
            left=int(self.status.get("left") or 0)))

    def landed(self, status, records) -> None:
        """A read came back: keep what it said about the event, then draw the squads."""
        self.status = status or {}
        self._paint_status()
        self.apply(records)

    # -- what the rows carry over and above the shared shape -----------------------
    def decorate(self, row, record) -> None:
        """The verdict, the readiness it decides, and the tile's own loot capacity.

        A ghost squad has no clock to count down to once it is back — its
        `completionTime` is when it returns and its `actEndTime` is the event's own end
        — so readiness is the GAME's answer rather than arithmetic, and the state cell
        says the verdict in words instead of drawing a broken countdown
        (`grid.refresh_timers`).
        """
        row["mine"] = bool(record.get("mine"))
        row["ready_forced"] = bool(record.get("ready"))
        row["state_key"] = self._state_key(record)
        row["loot_max"] = int(record.get("loot_max") or 0)
        row["owner_server"] = record.get("owner_server")
        # None where the list does not carry it at all — the alliance's own list has no
        # steal list on its records (#1251). «Not answered» and «nobody has robbed it»
        # are different facts, and a 0 would be the wrong one.
        row["loot_count"] = record.get("loot_count")

    def update_row(self, row, record) -> None:
        super().update_row(row, record)
        row["starred"] = bool(record.get("starred"))
        # …and the same «unknown stays unknown» as in `decorate`, which the shared
        # helper cannot know about.
        row["loot_count"] = record.get("loot_count")

    def _state_key(self, record) -> str:
        """The locale key for a row's state cell.

        The game's own `GhostreconPointStealType` for a squad somebody else is running:
        it is the answer to the only question worth asking about one. MY OWN squad is
        labelled by what it is DOING — out, or back — because the robbery verdict about
        my own tile answers a question nobody asked, and answers it «можно грабить»
        (#1251).
        """
        import lastwar_proto as proto

        if record.get("mine"):
            return ("secrettasks.ghost.state.mine_done"
                    if record.get("task_state") == proto.GHOST_STATE_DONE
                    else "secrettasks.ghost.state.not_shown")
        return STATE_KEYS.get(record.get("state"),
                              "secrettasks.ghost.state.not_shown")

    def collectable(self, row) -> bool:
        """Never from here — the ghost robbery lives in «Командный пункт» (#1188).

        Not an oversight: its press spends a queue a standalone tool fills, and another
        copy of that debt, in another place, is the thing the rule about it forbids. The
        row still says whether the game would allow the robbery — that is what the state
        cell is for — and the coordinate still walks the camera there.
        """
        return False

    def row_values(self, row) -> tuple:
        """One squad as the cells of the table.

        The tab's own formatting everywhere it fits, and this list's own in the two
        places a ghost squad is not a secret task: its loot slots are the template's
        rather than a secret task's three, and the action cell is empty because these
        pages do not rob (see :meth:`collectable`).
        """
        import coords as coords_fmt

        ready = bool(row.get("ready"))
        where = coords_fmt.fmt(row["x"], row["y"])
        if row.get("shared"):
            where = "%s %s" % (grid.SHARED_GLYPH, where)
        cap = int(row.get("loot_max") or 0)
        looted = row.get("loot_count")
        if looted is None:
            # Nothing to say: the list this row came from does not carry it. An empty
            # cell is the honest form of «не прочитано» — a 0/3 would read as «nobody
            # has touched it», which is a claim the game never made.
            slots = ""
        elif cap:
            slots = self.tab.t("secrettasks.ghost.slots", n=int(looted), max=cap)
        else:
            slots = self.tab.t("secrettasks.ghost.looted", n=int(looted))
        return (row.get("owner_name") or "",
                where,
                self.tab.t("secrettasks.server", srv=row["server"]),
                "%s %s" % (grid.READY_GLYPH if ready else grid.TYPE_GLYPH,
                           self.tab._rank(row)),
                row["timer"].get(),
                slots,
                "")

    # -- the phone -------------------------------------------------------------------
    def web_items(self) -> list:
        """The squads as the phone's card items — a reading, like every list here."""
        import coords

        items = []
        for row in sorted(self.visible_rows(),
                          key=lambda r: (not r.get("ready"),
                                         r.get("completed_at") or float("inf"))):
            cap = int(row.get("loot_max") or 0)
            looted = row.get("loot_count")
            facts = [{"label": "secrettasks.col.owner",
                      "value": row.get("owner_name") or "—"},
                     {"label": "secrettasks.col.level", "value": self.tab._rank(row)},
                     {"label": "secrettasks.col.state",
                      "value": self.tab.t(row.get("state_key")
                                          or "secrettasks.ghost.state.not_shown")}]
            # …and the loot count only where there is one to give (see `row_values`).
            if looted is not None:
                facts.append({"label": "secrettasks.col.slots",
                              "value": (f"{int(looted)}/{cap}" if cap
                                        else str(int(looted)))})
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

        The window draws the same pair over the table — six days a week it is the only
        thing on these pages worth reading, and «closed» is not something to guess at
        from an empty list.
        """
        return [{"label": "secrettasks.ghost.state_line",
                 "value": self.tab.t("secrettasks.ghost.open" if self.status.get("open")
                                     else "secrettasks.ghost.closed")},
                {"label": "secrettasks.ghost.left",
                 "value": str(int(self.status.get("left") or 0))}]


class GhostGrid(_GhostGrid):
    """MY OWN squads: where my three are, and when each of them is back."""

    TITLE_KEY = "secrettasks.ghost"
    HINT_KEY = "secrettasks.ghost.hint"
    EMPTY_KEY = "secrettasks.ghost.empty"


class GhostMapGrid(_GhostGrid):
    """WHAT A LAP OF THE MAP FOUND — the other sniffer, and the only one that sees
    other alliances (#1251).

    «Это два разных снифа, чужие снифаем по карте, свои из списка.» The two pages
    before this one are read out of the client and hold my own squads and my own
    alliance's; nobody else's is in either, because the client is never told about
    them. A tile scan is what finds those — and they are the ones a robbery is aimed
    at.

    Filled from the capture's own checkpoint (`profiles.ghost_json`), not from the
    game: the child process writes what it decodes off the wire as the map moves, and
    this page merges the file. It was never reaching a table at all until #1251 — the
    capture was launched without a checkpoint to write to, so a full lap of the map
    produced hundreds of decoded tiles, a busy log and no rows anywhere.

    A tile carries no nickname (the wire has the owner's uid and no name), and no
    verdict from the game's own steal gate — that only answers for squads in the
    client's list. Its readiness is its clock, and its level, rarity and star come
    from the event's config table, read once.
    """

    TITLE_KEY = "secrettasks.ghost.map"
    HINT_KEY = "secrettasks.ghost.map.hint"
    EMPTY_KEY = "secrettasks.ghost.map.empty"

    def _state_key(self, record) -> str:          # noqa: D102 — see the base
        return ("secrettasks.ghost.state.map_ready" if record.get("ready")
                else "secrettasks.ghost.state.map_running")


class GhostAllianceGrid(_GhostGrid):
    """WHAT THE ALLIANCE HAS SENT OUT — the list the game's own window draws (#1251).

    Not a filtered copy of the page beside it. That one is `ActGhostreconManager`'s
    `taskList`, which is what THIS account is mixed up in; this one is
    `ActGhostreconAllianceManager.allianceTaskList`, which the game's «задания
    альянса» window reads and which holds the whole alliance at once — live, the two
    were 3 rows and 13.

    **Read from the client, kept current by the push.** Nothing here asks the server:
    the list is already in the client, and `push.ghost.recon.alliance.single`
    (add/change/remove) is what moves it, so the tab's own trigger re-reads the local
    list on each push instead of polling.

    Two things this list does not carry, and which therefore stay blank: how many times
    a tile has been robbed (no steal list on these records) and an expiry. What it does
    carry is the leader's name, which is the whole point of the page's owner column,
    and when the squad set out — the config says how long one is out, so the countdown
    is two read values added rather than a guess.
    """

    TITLE_KEY = "secrettasks.ghost.allies"
    HINT_KEY = "secrettasks.ghost.allies.hint"
    EMPTY_KEY = "secrettasks.ghost.allies.empty"
