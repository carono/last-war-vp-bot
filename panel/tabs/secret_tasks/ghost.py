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

**Reading and walking the camera, and no robbery.** Ghost-recon's press is a scenario
now, but it still spawns a tool to park its targets first (`CLAUDE.md`, #1188) — and the
rule about that half is that it does not get more doorways. The two it already has (the
«Командный пункт» page and the standing order behind it) stay the only ones; these
pages show what is out there and take the camera to it. The tiles of OTHER alliances,
which a map scan finds and these two lists cannot know, are on that tab for the same
reason: they are what a robbery is aimed at, and this is not where robbing happens.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ...widgets import numeric_spinbox, tk_stringvar
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

    #: «Только звезда», as a class attribute so a page built without `__init__` — a
    #: test's, or anything reading `visible_rows` before the boxes exist — is a page
    #: with the box OFF rather than one that raises on the first draw.
    star_var = None

    def __init__(self, tab) -> None:
        super().__init__(tab)
        # The last read's answer about the event itself: whether today is its day and
        # how many of the five robberies are left. Drawn over the table, and the
        # reason an empty table is not a mystery six days a week.
        self.status: dict = {}
        self._status_var = tk_stringvar(tab.rt.root)
        # «Только звезда» over THIS page's list. Off by default, like the alliance
        # page's: a table that hides most of itself before anybody asked is not a
        # table of what is out there. A ghost squad's star is the event config's own
        # answer (`ghost_recon_steal`), never arithmetic over the cfgId — the same
        # rule the module docstring states.
        self.star_var = tk.BooleanVar(master=tab.rt.root, value=False)
        # WHO MOVED IT — the box was reported ticking itself off «через какое-то время»
        # and nothing in this tab could be shown to do it, so the variable says so
        # itself. One debug line per change, with the six frames above it: a person
        # pressing it looks like `_toggle_star` / a Tk callback, and anything else
        # names whatever really wrote the default over a live value. Costs a formatted
        # string per press and nothing at all while nobody presses.
        try:
            self.star_var.trace_add("write", self._star_moved)
        except AttributeError:                  # a stand-in variable in a test
            pass

    def _star_moved(self, *_args) -> None:
        import traceback

        try:
            value = bool(self.star_var.get())
        except Exception:                       # noqa: BLE001 — a variable being torn down
            return
        where = "".join(traceback.format_stack(limit=7)[:-1]).strip().replace("\n", " | ")
        self.tab.rt.dbg("secret").info("%s star_only -> %s, from: %s",
                                       self.CONFIG_KEY, value, where)

    # -- the event's own line ---------------------------------------------------------
    def build_filters(self, parent) -> None:
        """This page's own filters — and, above them, whether the event is on at all.

        `super()` FIRST and not instead: the level range belongs to every page (#1251),
        and an override that forgot to call it left three pages with no filters and no
        monitor switch at all.
        """
        ttk.Label(parent, textvariable=self._status_var,
                  foreground="#888").pack(anchor="w", pady=(4, 0))
        self._paint_status()
        super().build_filters(parent)

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

    # -- the boxes --------------------------------------------------------------------
    def extra_filters(self, bar) -> None:
        """«Звезда», on every ghost page — the star is what a robbery is aimed at.

        Each page keeps its own box (its own `CONFIG_KEY`), exactly as the level range
        does since #1251: it narrows THIS list, and a box that reached across the three
        pages would be a different feature wearing the same word.
        """
        self.tab.tr(ttk.Checkbutton(bar, variable=self.star_var,
                                    command=self.refilter),
                    "secrettasks.filter.star").pack(side="left", padx=(16, 0))

    def narrow(self, rows) -> list:
        """What the box lets through — everything while it is not ticked."""
        if self.star_var is not None and self.star_var.get():
            rows = [r for r in rows if r.get("starred")]
        return rows

    def config(self) -> dict:
        return dict(super().config(),
                    star_only=bool(self.star_var is not None and self.star_var.get()))

    def apply_config(self, raw) -> None:
        """Take what the block SAYS, and never a default over a live value.

        A block that does not mention `star_only` is a profile that has not been asked
        about this box — a legacy block (`Settings.tab_config` falls back to the flat
        keys, which have no `grids` at all), a page added after the profile was last
        written, a `{}` handed to a page whose key is missing. Reading a missing key as
        «off» is how a box ticks itself off «через какое-то время»: everything else on
        the tab keeps working, and the one thing that moved is the thing nobody
        touched. The key is written on every save, so a box somebody DID untick comes
        back unticked — `star_only: false` is present and is applied.
        """
        super().apply_config(raw)
        grid.take(raw, "star_only", self.star_var)

    def persist_vars(self) -> list:
        return super().persist_vars() + [self.star_var]

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

        Not an oversight: its press SPENDS a queue a standalone tool has to park the
        targets in, and another copy of those two steps, in another place, is the thing
        the rule about it forbids. The
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

    def persist(self) -> None:
        """Only the map page keeps a checkpoint of its own; the others are re-read."""

    # -- OUR list, which a read only FILLS (#1251) ------------------------------------
    def apply(self, records) -> None:
        """MERGE a read into this page's own list — never replace it.

        «Мониторинг только наполняет наши таблицы, дальше это наши данные.» Every
        source here is partial: a lap of the map shows the patch it drove over, and even
        the client's own lists were watched emptying mid-event (13 rows, then 1, then
        0) as squads returned and the server re-sent less. Replacing the table with the
        last answer made it blink; keeping it makes the panel's list the panel's.

        A row leaves by THIS list's rules and no others: its own clock runs out
        (`grid.refresh_timers` drops an expired one), or it is robbed. «Nobody has
        re-read it lately» is not a reason — that is `seen_at`, which the row SAYS.
        """
        for record in records or ():
            key = str(record["uuid"])
            row = self._rows.get(key)
            if row is None:
                # Through the grid module, like the base class: one place makes a row's
                # countdown variable, which is what lets a test stand in for it.
                row = grid.new_row(record, grid.tk_stringvar(self.tab.rt.root))
            else:
                self.update_row(row, record)
            self.decorate(row, record)
            self._rows[key] = row
        self.render()
        self.persist()

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

    CONFIG_KEY = "ghost"
    TITLE_KEY = "secrettasks.ghost"
    HINT_KEY = "secrettasks.ghost.hint"
    EMPTY_KEY = "secrettasks.ghost.empty"

    def extra_filters(self, bar) -> None:
        """The ghost sniffer's switch, on the page whose NAME people look under (#1264).

        This page does not own that capture — «Призрак: карта» does, and the tiles it
        finds land there. It is drawn here because «Операция Призрак» is what a person
        searching for ghost monitoring reads first, and finding no switch on it they
        report the switch missing rather than opening the fifth page.

        **The same `monitor_var` and the same toggle as the map page**, never a second
        one: one variable behind two checkbuttons is one switch drawn twice, and Tk
        moves both whichever is pressed. Two independent boxes over one capture would
        disagree the first time anything else changed the state — the day the capture
        stops on its own, for instance — and then neither would be believable. See
        docs/panel-tabs.md, «One state, several places».

        `super()` first, so this page keeps «Звезда» — an override that draws only its
        own box is how a filter goes missing from one page of three.
        """
        super().extra_filters(bar)
        self.tab.tr(ttk.Checkbutton(bar, variable=self.tab.ghost_map.monitor_var,
                                    command=self.tab.ghost_capture.toggle),
                    "secret.monitoring.ghost").pack(side="left", padx=(16, 0))


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

    CONFIG_KEY = "ghost_map"
    TITLE_KEY = "secrettasks.ghost.map"
    HINT_KEY = "secrettasks.ghost.map.hint"
    EMPTY_KEY = "secrettasks.ghost.map.empty"

    def __init__(self, tab) -> None:
        super().__init__(tab)
        # The ghost sniffer's own switch and its own interval, both this page's (#1251).
        self.monitor_var = tk.BooleanVar(master=tab.rt.root, value=False)
        self.interval_var = tk_stringvar(tab.rt.root)
        self.interval_var.set("15")

    def _state_key(self, record) -> str:          # noqa: D102 — see the base
        return ("secrettasks.ghost.state.map_ready" if record.get("ready")
                else "secrettasks.ghost.state.map_running")

    def decorate(self, row, record) -> None:
        super().decorate(row, record)
        # How old this row's information is. Kept on the row so the state cell can say
        # it, and checkpointed with the rest.
        row["seen_at"] = record.get("seen_at")

    def update_row(self, row, record) -> None:
        super().update_row(row, record)
        row["x"], row["y"] = record.get("x"), record.get("y")
        row["server"] = record.get("server")
        row["completed_at"] = record.get("completed_at")
        row["expires_at"] = record.get("expires_at")
        row["loot_count"] = record.get("loot_count")


    #: This list's row in `panel.db`'s `blobs` table (`panel/runtime/store.py`, #1465).
    STATE_BLOB = "ghost_map_state"

    # -- surviving a restart ----------------------------------------------------------
    def persist(self) -> None:            # noqa: D102 — overrides the no-op above
        """Checkpoint this page's own list, whole — into the database, not a file."""
        try:
            self.tab.rt.store.blob_set(
                self.STATE_BLOB,
                [{k: row.get(k) for k in
                  ("uuid", "server", "owner_server", "target_server", "x", "y",
                   "cfg_id", "level", "starred", "colour", "loot_max",
                   "loot_count", "completed_at", "expires_at", "owner_uid",
                   "alliance_id", "members", "seen_at", "ready")}
                 for row in self._rows.values()])
        except Exception:                     # noqa: BLE001 — a checkpoint, never the tab
            pass

    def restore(self) -> None:
        """Read the page's own list back — what the last session had gathered.

        A row already past its own expiry is dropped here rather than drawn and then
        dropped a second later, exactly as the ★ list does it. The first restore on a
        profile whose database has never seen this blob brings its old
        `ghost_map_state.json` across, once (`store.blob_import_once`).
        """
        import game_clock
        from ...runtime.store import blob_import_once

        store = self.tab.rt.store
        records = store.blob_get(self.STATE_BLOB)
        if records is None:
            blob_import_once(store, self.STATE_BLOB,
                             self.tab.rt.profiles.ghost_map_state_json())
            records = store.blob_get(self.STATE_BLOB)
        if not isinstance(records, list):
            return
        now = game_clock.now_ms()
        alive = [r for r in records if isinstance(r, dict) and r.get("uuid")
                 and not (r.get("expires_at") and r["expires_at"] <= now)]
        if alive:
            self.apply(alive)

    # -- this page's own sniffer ------------------------------------------------------
    def extra_filters(self, bar) -> None:
        """The GHOST capture's own switch, on the page it feeds (#1251).

        One switch per sniffer, not one with a dropdown: the two capture different
        things into different checkpoints, and whoever is watching ghost tiles almost
        never wants the secret-task capture stopped in the same breath. The interval is
        this capture's own too — it is what its child is launched with.

        Drawn a second time on «Операция Призрак» (:meth:`GhostGrid.extra_filters`,
        #1264) out of THIS variable. The interval stays here alone: it belongs to the
        capture this page owns, and a number in two places invites two answers where a
        checkbutton bound to one variable cannot have them.

        `super()` first, for «Звезда»: this is the page the star box matters most on —
        a lap of the map brings back everyone's tiles, and the starred ones are what a
        robbery is aimed at.
        """
        super().extra_filters(bar)
        self.tab.tr(ttk.Checkbutton(bar, variable=self.monitor_var,
                                    command=self.tab.ghost_capture.toggle),
                    "secret.monitoring.ghost").pack(side="left", padx=(16, 0))
        self.tab.tr(ttk.Label(bar), "secret.interval").pack(
            side="left", padx=(12, 2))
        numeric_spinbox(bar, from_=1, to=3600, width=5,
                        textvariable=self.interval_var).pack(side="left")
        # A capture is launched with its interval, so a change only lands on the next
        # start: bounce a running one rather than waiting for a manual toggle.
        self.interval_var.trace_add(
            "write", lambda *_a: self.tab._on_ghost_interval_change())

    def config(self) -> dict:
        return dict(super().config(), monitor=bool(self.monitor_var.get()),
                    interval=self.interval_var.get())

    def apply_config(self, raw) -> None:
        super().apply_config(raw)
        # …and the sniffer's own switch the same way (`grid.take`): a block that does
        # not mention it must not stop a capture that is running.
        grid.take(raw, "monitor", self.monitor_var)
        grid.take(raw, "interval", self.interval_var, str)

    def persist_vars(self) -> list:
        return super().persist_vars() + [self.monitor_var, self.interval_var]


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

    CONFIG_KEY = "ghost_allies"
    TITLE_KEY = "secrettasks.ghost.allies"
    HINT_KEY = "secrettasks.ghost.allies.hint"
    EMPTY_KEY = "secrettasks.ghost.allies.empty"
