"""The four world pages: mines, monsters, alliance trains and player trucks (#1289).

The tab already draws five tables of things the map holds — the starred raids, the
alliance's own dispatches, and the three ghost-recon lists. These are the rest of the
map, and they are the same page machinery over different facts:

* **«Шахты»** — every resource node the sniffer has seen, with what it yields, its level
  and whether somebody is already gathering it. The most common thing on the map by a
  wide margin: one recorded whole-server lap held 12 725 mine tiles against 6 723 bases.
* **«Монстры»** — the one list that CANNOT come off the wire. Nothing in any message
  names a monster (docs/research/protocol.md, «Monsters are not on the wire»), so this
  page is filled by a scenario that reads the client's own memory,
  `actions/read_world_monsters.md`, and is therefore as wide as the client's view rather
  than as wide as the map.
* **«Поезда»** — the alliance train, the rare one: three in every recording on disk,
  because it runs as an event rather than all day.
* **«Грузовики»** — the player trucks, which are not tiles either: they ride the march
  stream, and their position has to be interpolated along the leg the server last
  described.

**Three of the four are fed by ONE capture and no new process.** Two npcap captures over
one interface starve each other — measured live, `20 delivered / 0 map response(s)`
against `5117 map response(s)` in the same minute (044c19f) — so the second listener
lives INSIDE the first one's child (`tools/lib/world_index.py`, `--world-json`). What
reaches this module is that child's checkpoint, exactly as `GhostMapGrid` reads the ghost
one.

**A row leaves by its own clock and nothing else** — the rule every list on this tab
follows. For a truck and a train that clock is `arrive_at`, the moment the run ends and
it leaves the map. A mine and a monster have no clock at all, and the honest substitute
is the sighting's own age: a mine's occupancy changes under it, and a monster is drawn
where the client last had it, so a record nobody has re-seen for
:data:`SIGHTING_TTL_SEC` is not kept as if it were current. «Nobody has looked lately» is
still said out loud in the state cell before it goes (`grid.state_text`).

**And there is a cap on what is DRAWN, said out loud.** A lap of the map finds nine
thousand mines; nine thousand rows is a table nobody reads and, worse, nine thousand Tk
calls on the one event loop every open profile shares (#1226). So each page draws its
best :data:`MAX_SHOWN` and counts the rest into «скрыто» beside the counter — the same
number the level boxes are counted into, because a person seeing «показано 500 · скрыто
8503» knows exactly what happened and one seeing «500» does not.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ...widgets import tk_stringvar
from . import grid

#: How long a sighting is drawn for once nothing re-confirms it. The capture's own
#: freshness window (`lastwar_proto.TASK_FRESH_SECONDS`), so the panel and the child
#: agree on what «current» means instead of one of them keeping what the other dropped.
SIGHTING_TTL_SEC = 15 * 60

#: How many rows a world page puts on its table. See the module docstring: the rest are
#: counted into «скрыто», never dropped quietly.
MAX_SHOWN = 500

#: `lw_world_monster.type` — the split the player reads off the screen (#1281). 7 is the
#: zombie line (Invading Zombies / Zombie Boss), 8 the Doom line («Роковая Элита»).
MONSTER_TYPE_KEYS = {
    7: "world.monster.type.zombie",
    8: "world.monster.type.doom",
}

#: WHAT «ПРОСТОЙ МОНСТР» IS, by the only name a row carries (#1549).
#:
#: The prefab, normalised — `lw_world_monster.pic_name`, which is what both monster reads
#: answer with. Everything under this mask is an ordinary field target: live, one register
#: answer held 197 of them (`world_monster_boss_bread` 73, `world_monster_boss_coin_2` 68,
#: `world_monster_boss_iron` 56, levels 1…35) against 152 golden zombies, and nothing else.
#:
#: **ONE CAVEAT, and it is written here rather than discovered later.** The mask also
#: covers `world_monster_boss_invasion`, `_1` and `_2` — the invasion event's real bosses,
#: levels 5…150 (`special = 10`, docs/research/golden-zombies.md §1b). None was on the map
#: when this was measured, because the event was between waves. If those should stay
#: visible the exact sign is the family: the same mask minus anything starting
#: `world_monster_boss_invasion`. It is one line, and it is not guessed at here because
#: the operator named this mask and a filter that quietly means something else is worse
#: than one that means too much.
PLAIN_PREFIX = "world_monster_boss_"

#: The same mask NORMALISED — lower-case with everything but letters and digits dropped.
#: The two monster sources spell a prefab differently: the register answers with the
#: config's own `pic_name` (`world_monster_boss_iron`) and a drawn clone answers with the
#: object's name (`WorldMonster_Boss01`). The game's own lookup normalises both before
#: comparing them (`monster_prefab_lookup` in tools/lib/lua_actions.py), and so does this,
#: or the box would hide the register's rows and leave the drawn ones on the table.
_PLAIN_NORM = "".join(ch for ch in PLAIN_PREFIX if ch.isalnum())


def is_plain(row) -> bool:
    """Whether this row is an ordinary field monster — see :data:`PLAIN_PREFIX`.

    A row with NO prefab name at all is not called plain: a drawn clone the config could
    not resolve says nothing about what it is, and hiding it on a guess is how a list
    loses the rows nobody can account for.
    """
    name = str(row.get("kind_name") or "")
    return "".join(ch for ch in name if ch.isalnum()).lower().startswith(_PLAIN_NORM)


#: What a mine yields — `lastwar_proto.MINE_RESOURCES`, said in the person's language.
#: A family nobody has named (the fourth one, four tiles in a whole lap) says so rather
#: than being given an invented name.
RESOURCE_KEYS = {
    "bread": "world.mine.bread",
    "iron": "world.mine.iron",
    "gold": "world.mine.gold",
}


class _Text:
    """A row's state cell where there is no countdown to draw in it.

    `grid.new_row` wants something with `get`/`set`, and for the tables that DO count
    down that is a Tk variable. A mine has no clock, and nine thousand Tk variables is a
    real cost on the one event loop the open profiles share — so the pages without a
    countdown hand in this instead. The same stand-in the grid tests use, for the same
    reason: nothing here needs a Tk root.
    """

    __slots__ = ("_value",)

    def __init__(self) -> None:
        self._value = ""

    def get(self) -> str:
        return self._value

    def set(self, value) -> None:
        self._value = str(value)


def human_number(value) -> str:
    """A cargo as a person reads it — «14.1M», not «14094000».

    A pure numeric format and therefore one of the few things on this tab that may be a
    literal (`CLAUDE.md`): there is no word in it to translate, and the suffixes are the
    ones the game itself prints beside a resource.
    """
    number = float(value or 0)
    for suffix in ("", "K", "M", "B"):
        if abs(number) < 1000 or suffix == "B":
            return ("%d%s" % (number, suffix) if suffix == ""
                    else "%.1f%s" % (number, suffix))
        number /= 1000.0
    return str(int(value or 0))


def _coords(row) -> str:
    import coords as coords_fmt
    return coords_fmt.fmt(row.get("x"), row.get("y"))


#: The three things a vehicle row can say about its own coordinate. THE POINT OF THE
#: SPLIT is that a live number and a frozen one must not look the same on screen: a
#: person reading a coordinate has no way to tell «this is being walked right now» from
#: «this is where we last heard it» unless the row says which, and the second one used to
#: masquerade as the first for the whole of #1289's life.
LEG_MOVING = "moving"      # inside the hop's window — the coordinate moves every tick
LEG_PARKED = "parked"      # the hop is over and no new one has been pushed: it is still
LEG_NONE = "unknown"       # no hop at all — the coordinate is the last one we were told


def vehicle_leg(row, now_ms=None):
    """`(state, (x, y))` — where a vehicle is, and whether that number is LIVE (#1298).

    One line of arithmetic, and it deliberately is not written here:
    `lastwar_proto.march_position` is what the decoder and the two tables both walk, so
    the panel cannot drift into drawing a truck on a different tile from the one the
    tools report. The panel is only deciding WHEN to ask (every tick), never how.

    `LEG_NONE` with no position rather than a guess when the hop is missing: a checkpoint
    written before the leg was kept has an `x`/`y` and nothing to walk, and overwriting
    that with `(0, 0)` would move every old row to the corner of the map. It is also the
    honest thing to SAY — see `_VehicleGrid.next_stop_text`.

    The clock is the GAME's, never this machine's (`tools/lib/game_clock.py`): over a
    two-minute hop the difference between the two is tiles, which is the whole quantity.
    """
    import game_clock
    import lastwar_proto as proto

    start, end = row.get("leg_start_ms"), row.get("leg_end_ms")
    src, dst = row.get("leg_from") or (), row.get("leg_to") or ()
    if len(src) < 2 or len(dst) < 2:
        return LEG_NONE, None
    now = game_clock.now_ms() if now_ms is None else now_ms
    where = proto.march_position(tuple(src[:2]), tuple(dst[:2]), start, end, now_ms=now)
    running = (start is not None and end is not None and start < end and now < end)
    return (LEG_MOVING if running else LEG_PARKED), where


def vehicle_position(row, now_ms=None):
    """Just the tile of :func:`vehicle_leg` — None when there is no hop to walk."""
    return vehicle_leg(row, now_ms)[1]


class WorldGrid(grid.TaskGrid):
    """One world page: a merged, capped, self-ageing list of one kind of thing."""

    #: The key under `world.json` this page reads, or "" when it is not fed by the
    #: capture at all (the monster page, whose feed is a scenario).
    SOURCE = ""

    #: Whether rows on this page have a clock of their own. False means they age out on
    #: the sighting instead — see the module docstring.
    HAS_CLOCK = False

    def __init__(self, tab) -> None:
        super().__init__(tab)
        # What the last merge said, so the count line can be drawn before the page has
        # ever been opened (`build` runs on first LOOK, not when the page is made).
        self._last_seen = 0.0

    # -- the row's own clock ------------------------------------------------
    def new_timer(self):
        return tk_stringvar(self.tab.rt.root) if self.HAS_CLOCK else _Text()

    def has_countdown(self) -> bool:
        """Only the two vehicle pages ever count down; the other two never repaint."""
        return self.HAS_CLOCK and super().has_countdown()

    # -- merging, never replacing -------------------------------------------
    def apply(self, records) -> None:
        """MERGE what a read said into this page's own list.

        The same rule «Призрак: карта» follows and for the same reason: every source
        here is partial. A lap of the map shows the ground it drove over, and a monster
        read shows what the client had drawn — replacing the table with the last answer
        would make it blink out and back on every tick.
        """
        for record in records or ():
            key = str(record.get("uuid") or "")
            if not key:
                continue
            row = self._rows.get(key)
            if row is None:
                row = grid.new_row(record, self.new_timer())
            else:
                self.update_row(row, record)
            self.decorate(row, record)
            self._rows[key] = row
        self.render()
        self.persist()

    def update_row(self, row, record) -> None:
        """A record we already had, said again: everything about it may have moved."""
        row["x"], row["y"] = record.get("x"), record.get("y")
        row["server"] = record.get("server")
        row["level"] = record.get("level")
        row["expires_at"] = record.get("expires_at")
        row["completed_at"] = record.get("completed_at")

    def decorate(self, row, record) -> None:
        """The facts this page's own columns are drawn from."""
        row["seen_at"] = record.get("seen_at")
        row["state_key"] = self.state_key(row, record)

    def state_key(self, row, record) -> str:
        """The words in the state cell of a row with no countdown."""
        return ""

    # -- ageing out ---------------------------------------------------------
    def tick(self) -> None:
        """The per-second pass: the shared one, plus dropping stale sightings.

        A page with a clock leaves the dropping to `grid.refresh_timers` — a truck's
        `arrive_at` IS its deadline. A page without one drops on the age of the sighting,
        which is the only deadline a mine or a monster has.
        """
        if not self.HAS_CLOCK:
            self._drop_stale()
        super().tick()

    def _drop_stale(self) -> None:
        cutoff = time.time() - SIGHTING_TTL_SEC
        stale = [key for key, row in self._rows.items()
                 if float(row.get("seen_at") or 0) < cutoff]
        for key in stale:
            self._rows.pop(key, None)

    # -- what is drawn ------------------------------------------------------
    def rank(self, row) -> tuple:
        """Which rows survive the display cap. The freshest, by default."""
        return (-float(row.get("seen_at") or 0), str(row.get("uuid") or ""))

    def visible_rows(self) -> list:
        rows = super().visible_rows()
        if len(rows) <= MAX_SHOWN:
            return rows
        return sorted(rows, key=self.rank)[:MAX_SHOWN]

    def collectable(self, row) -> bool:
        """Nothing on these pages is collected — they are readings and a camera.

        A mine is gathered with a squad, a monster is attacked with one and a truck is
        robbed with one; all three are marches, and none of them is an ability this
        repository has yet. When one arrives it will be a scenario, and the button will
        appear here and on the phone in the same commit (`CLAUDE.md`).
        """
        return False

    #: The name this page's row is checkpointed under in `panel.db`'s `blobs` table
    #: (`panel/runtime/store.py`, #1465) — `""` for the three pages that keep no
    #: checkpoint of their own at all (see :meth:`state_path`).
    STATE_BLOB = ""

    def persist(self) -> None:
        """Checkpoint this page's own list, whole — into the database, not a file."""
        if not self.STATE_BLOB:
            return
        try:
            self.tab.rt.store.blob_set(
                self.STATE_BLOB,
                [{k: row.get(k) for k in self.PERSIST_KEYS}
                 for row in self._rows.values()])
        except Exception:                    # noqa: BLE001 — a checkpoint, never the tab
            pass

    #: What survives a restart. Everything the columns are drawn from, and the sighting
    #: time the ageing is judged on.
    PERSIST_KEYS = ("uuid", "server", "x", "y", "level", "seen_at",
                    "expires_at", "completed_at", "until_key")

    def state_path(self) -> str:
        """Where this page's OLD JSON checkpoint used to live, for the one-time import.

        EMPTY FOR THREE OF THE FOUR PAGES, and that is the point. The mine, truck and
        train lists come out of the capture's own checkpoint, which is written every
        tick and survives a restart by itself — a second copy of five thousand mines,
        rewritten on every nudge, is a megabyte of disk per finding and nothing gained.
        The MONSTER page overrides it, because nothing else on disk remembers what a
        read of the client found.
        """
        return ""

    def restore(self) -> None:
        """Read the page's own list back — what the last session had gathered.

        Out of `panel.db`'s `blobs` table now, not a file (#1465). The first restore on
        a profile whose database has never seen this blob brings the old JSON checkpoint
        across, once (`store.blob_import_once`) — a page with no `STATE_BLOB` has
        nothing to restore, same as before.
        """
        if not self.STATE_BLOB:
            return
        from ...runtime.store import blob_import_once

        store = self.tab.rt.store
        records = store.blob_get(self.STATE_BLOB)
        if records is None:
            path = self.state_path()
            if path:
                blob_import_once(store, self.STATE_BLOB, path)
                records = store.blob_get(self.STATE_BLOB)
        if not isinstance(records, list):
            return
        cutoff = time.time() - SIGHTING_TTL_SEC
        alive = [r for r in records if isinstance(r, dict) and r.get("uuid")
                 and float(r.get("seen_at") or 0) >= cutoff]
        if alive:
            self.apply(alive)

    # -- the phone ----------------------------------------------------------
    def web_items(self) -> list:
        """The page's rows as the phone's card items — a reading, like the window's."""
        import coords

        items = []
        for row in grid.sort_rows(self.visible_rows(), self._sort, self.SORT_KEYS):
            exp = row.get("expires_at")
            items.append({
                "text": coords.fmt(row.get("x"), row.get("y"), row.get("server")),
                "facts": self.web_facts(row),
                "until": (exp / 1000.0) if exp else None,
            })
        return items

    def web_facts(self, row) -> list:
        """The row's own facts on the phone — the window's columns, one per line."""
        return [{"label": "secrettasks.col.level",
                 "value": str(int(row.get("level") or 0))}]


# ---------------------------------------------------------------------------
# Mines
# ---------------------------------------------------------------------------
class MineGrid(WorldGrid):
    """Every resource node the sniffer has seen: what it yields, and who has it."""

    CONFIG_KEY = "mines"
    SOURCE = "mines"
    INTAKE = "world.checkpoint"
    TITLE_KEY = "world.mines"
    HINT_KEY = "world.mines.hint"
    EMPTY_KEY = "world.mines.empty"

    COLUMNS = (
        ("coords", "secrettasks.col.coords", 150, "w", False),
        ("server", "secrettasks.col.server", 90, "w", False),
        ("kind", "world.col.resource", 120, "w", False),
        ("lvl", "secrettasks.col.level", 80, "w", False),
        ("state", "secrettasks.col.state", 220, "w", True),
        ("owner", "world.col.taken_by", 170, "w", False),
    )
    SORT_KEYS = {
        "coords": lambda r: (int(r["x"] or 0), int(r["y"] or 0), str(r["uuid"])),
        "server": lambda r: (int(r["server"] or 0), str(r["uuid"])),
        "kind": lambda r: (str(r.get("resource") or ""), str(r["uuid"])),
        "lvl": lambda r: (int(r["level"] or 0), str(r["uuid"])),
        "state": lambda r: (0 if r.get("free") else 1, str(r["uuid"])),
        "owner": lambda r: (str(r.get("owner_uid") or ""), str(r["uuid"])),
    }
    PERSIST_KEYS = WorldGrid.PERSIST_KEYS + ("resource", "family", "free",
                                             "owner_uid", "alliance_id")

    def __init__(self, tab) -> None:
        super().__init__(tab)
        #: «только свободные» — ON for a profile that has never been asked. A mine
        #: somebody is already gathering cannot be marched on, and nine tiles in ten are
        #: free anyway, so the box is what brings the taken ones back rather than what
        #: hides them.
        self.free_var = tk.BooleanVar(master=tab.rt.root, value=True)

    def extra_filters(self, bar) -> None:
        self.tab.tr(ttk.Checkbutton(bar, variable=self.free_var,
                                    command=self.refilter),
                    "world.mines.free_only").pack(side="left", padx=(16, 0))

    def narrow(self, rows) -> list:
        return [r for r in rows if r.get("free")] if self.free_var.get() else rows

    def config(self) -> dict:
        return dict(super().config(), free_only=bool(self.free_var.get()))

    def apply_config(self, raw) -> None:
        super().apply_config(raw)
        grid.take(raw, "free_only", self.free_var)

    def persist_vars(self) -> list:
        return super().persist_vars() + [self.free_var]

    def decorate(self, row, record) -> None:
        super().decorate(row, record)
        row["resource"] = record.get("resource")
        row["family"] = record.get("family")
        row["free"] = bool(record.get("free"))
        row["owner_uid"] = record.get("owner_uid")
        row["alliance_id"] = record.get("alliance_id")

    def state_key(self, row, record) -> str:
        return "world.mine.free" if record.get("free") else "world.mine.taken"

    def rank(self, row) -> tuple:
        """The best mine first when the cap bites: the highest level, then the freshest."""
        return (-int(row.get("level") or 0), -float(row.get("seen_at") or 0),
                str(row.get("uuid") or ""))

    def resource_text(self, row) -> str:
        key = RESOURCE_KEYS.get(row.get("resource"))
        if key:
            return self.tab.t(key)
        # A family the screen has never been checked against: say WHICH one rather than
        # invent a name for it (`lastwar_proto.MINE_RESOURCES`).
        return self.tab.t("world.mine.unknown", family=int(row.get("family") or 0))

    def row_values(self, row) -> tuple:
        return (_coords(row),
                self.tab.t("secrettasks.server", srv=row.get("server")),
                self.resource_text(row),
                str(int(row.get("level") or 0)),
                row["timer"].get(),
                row.get("owner_uid") or "")

    def web_facts(self, row) -> list:
        return [{"label": "world.col.resource", "value": self.resource_text(row)},
                {"label": "secrettasks.col.level",
                 "value": str(int(row.get("level") or 0))},
                {"label": "secrettasks.col.state",
                 "value": self.tab.t(row.get("state_key") or "world.mine.free")}]


# ---------------------------------------------------------------------------
# Monsters
# ---------------------------------------------------------------------------
class MonsterGrid(WorldGrid):
    """What the client can see standing on the map — the only list not off the wire."""

    CONFIG_KEY = "monsters"
    SOURCE = ""                     # a scenario fills this one, not the capture
    INTAKE = "world.monsters"
    TITLE_KEY = "world.monsters"
    HINT_KEY = "world.monsters.hint"
    EMPTY_KEY = "world.monsters.empty"

    COLUMNS = (
        ("coords", "secrettasks.col.coords", 150, "w", False),
        ("server", "secrettasks.col.server", 90, "w", False),
        ("kind", "world.col.species", 190, "w", False),
        ("lvl", "secrettasks.col.level", 80, "w", False),
        ("state", "secrettasks.col.state", 220, "w", True),
    )
    SORT_KEYS = {
        "coords": lambda r: (int(r["x"] or 0), int(r["y"] or 0), str(r["uuid"])),
        "server": lambda r: (int(r["server"] or 0), str(r["uuid"])),
        "kind": lambda r: (int(r.get("monster_type") or 0), str(r["uuid"])),
        "lvl": lambda r: (int(r["level"] or 0), str(r["uuid"])),
        "state": lambda r: (str(r.get("source") or ""), str(r["uuid"])),
    }
    PERSIST_KEYS = WorldGrid.PERSIST_KEYS + ("monster_type", "kind_name",
                                             "cfg_id", "source", "point_id",
                                             "game_uuid")

    #: THE ONE PAGE THAT KEEPS ITS OWN LIST — nothing else remembers it. The other three
    #: are re-read from the capture's checkpoint; a monster read leaves nothing behind
    #: it, so without this the page would be empty every time the panel started and
    #: would stay empty until somebody pressed «Обновить» beside a map with monsters
    #: on it.
    STATE_BLOB = "world_state_monsters"

    #: HOW LONG THE CAMERA STANDS AT EACH STOP OF A MONSTER LAP, in seconds, and it is a
    #: SETTING because the measurement says it is the whole quantity (#1523). One lap of
    #: 121 stops on a live warzone, counting distinct monster tiles:
    #:
    #:     0.05 s ->     22    (the ★ lap's pace — the camera has moved on before the
    #:                           client has drawn anything)
    #:     0.30 s ->     27
    #:     0.60 s ->     33
    #:     1.20 s ->    972    <- a CLIFF, not a slope
    #:     2.50 s ->  1 059    (twice the clock for another nine per cent)
    #:
    #: Somewhere around a second the client's region loader starts keeping up and the same
    #: lap over the same ground goes from tens to a thousand. Everything below that is a
    #: lap that looks like it worked and collects almost nothing — which is exactly what
    #: «монстров тысячи, а в гриде десятки» was. 1.2 s is about 970 monsters for 147 s of
    #: camera; the operator owns the knob either way.
    DEFAULT_PACE = "1.2"

    #: …AND THE HEIGHTS IT WALKS, one lap each, because how many monsters are drawn at
    #: once depends on the height and the ground one stop covers depends on it the other
    #: way. Measured at one view: 105 -> 12 drawn, 300 -> 24, 600 -> 25, 1199 -> 20 — so a
    #: low lap sees more per stop and needs more stops. Neither dominates, which is why
    #: this is a list and not a number.
    DEFAULT_STAGES = "600"

    #: What one stop is worth at a height, so a stage list can be walked with a step that
    #: matches it rather than with one number for all of them. The pairs the lap primitive
    #: already names (`lua_actions.ZOOM_LEVELS`), plus the two heights in between that the
    #: measurement above says are worth offering at all.
    STAGE_STEPS = {105: 24, 300: 45, 600: 90, 900: 135, 1199: 180}

    def state_path(self) -> str:
        """Where this page's OLD JSON checkpoint used to live, for the one-time import."""
        return self.tab.rt.profiles.world_state_json(self.CONFIG_KEY)

    #: HOW OFTEN THE REGISTER IS ASKED WHILE SOMEBODY WALKS THE MAP, in seconds (#1549).
    #: The ask costs 36 ms and touches neither the camera nor the scene
    #: (`actions/poll_world_monsters.md`), and a row ages out after fifteen minutes, so
    #: anything under a minute keeps the page true at a cost that does not show. Twenty
    #: seconds is a compromise between «the row appeared while I was still looking at the
    #: monster» and one more claim on the daemon every tick.
    DEFAULT_FOLLOW = "20"

    def __init__(self, tab) -> None:
        super().__init__(tab)
        #: The two knobs above as the person's own, saved with the page's block.
        self.pace_var = tk_stringvar(tab.rt.root)
        self.pace_var.set(self.DEFAULT_PACE)
        self.stages_var = tk_stringvar(tab.rt.root)
        self.stages_var.set(self.DEFAULT_STAGES)
        #: «Следить за картой» — ON for a profile that has never been asked (#1549).
        #: The page had three buttons and no clock, so walking the map by hand filled the
        #: client's register (176, 177, 321 monsters at three moments of one session) and
        #: left the page showing 1 row. The default is on because a page that only fills
        #: when pressed is the bug this switch answers.
        self.follow_var = tk.BooleanVar(master=tab.rt.root, value=True)
        self.follow_secs_var = tk_stringvar(tab.rt.root)
        self.follow_secs_var.set(self.DEFAULT_FOLLOW)
        #: «Скрывать простых» — ON for a profile that has never been asked. The ordinary
        #: field monsters are most of the page (197 of 349 in the live reading this was
        #: measured on) and the operator asked not to be shown them; the box is what
        #: brings them back rather than what takes them away.
        #:
        #: IT HIDES, IT DOES NOT DROP. Nothing leaves `self._rows`, nothing leaves the
        #: checkpoint: `narrow` is a display rule, so the count beside the box says how
        #: many are being held back and one tick puts them all on the table again.
        self.hide_plain_var = tk.BooleanVar(master=tab.rt.root, value=True)
        #: …and that count, drawn next to the box rather than only in the page's own
        #: «показано / скрыто» pair: a number at the far end of the header answers «is
        #: something hidden», and the question here is «is THIS filter hiding it».
        self.plain_count_var = tk_stringvar(tab.rt.root)

    def extra_filters(self, bar) -> None:
        """The lap's own controls, on the page the lap fills.

        A press that STARTS something, beside readings — which is the ordinary and wanted
        shape (`CLAUDE.md`): the button plays `actions/scan_map_monsters.md` and the page
        then re-reads. It marks nothing.
        """
        from ...widgets import NumericEntry

        self.tab.tr(ttk.Label(bar), "world.monsters.pace").pack(side="left", padx=(16, 2))
        NumericEntry(bar, textvariable=self.pace_var, width=5,
                     decimal=True).pack(side="left")
        self.tab.tr(ttk.Label(bar), "world.monsters.stages").pack(side="left", padx=(10, 2))
        ttk.Entry(bar, textvariable=self.stages_var, width=12).pack(side="left")
        self.tab.tr(ttk.Button(bar, command=self.tab.sweep_monsters),
                    "world.monsters.sweep").pack(side="left", padx=(8, 0))
        # …and the FAST one beside it (#1523): the world's own register instead of a look
        # at what is drawn — 8 s against 147, and the only source that carries the uuid.
        self.tab.tr(ttk.Button(bar, command=self.tab.ask_world_monsters),
                    "world.monsters.ask").pack(side="left", padx=(4, 0))
        # …AND THE CLOCK BESIDE THEM (#1549): the same register, asked by itself while
        # the person walks. A press that starts something is ordinary; what this adds is
        # that nobody has to keep pressing it for the page to stay true.
        self.tab.tr(ttk.Checkbutton(bar, variable=self.follow_var,
                                    command=self.refilter),
                    "world.monsters.follow").pack(side="left", padx=(16, 2))
        NumericEntry(bar, textvariable=self.follow_secs_var, width=4).pack(side="left")
        self.tab.tr(ttk.Label(bar), "world.monsters.follow_secs").pack(side="left",
                                                                      padx=(2, 0))
        # …and the one display rule this page has (#1549): hide the ordinary field
        # monsters. A SECOND LINE of the filter bar, because the first one already holds
        # the level range, the lap's two numbers, three buttons and the follow clock —
        # and a box nobody can find is a box nobody unticks when a row goes missing.
        # `bar.master` is the page frame, and `build_filters` runs before the table is
        # packed, so this lands between the bar and the table.
        row = ttk.Frame(bar.master)
        row.pack(fill="x", pady=(4, 0))
        self.tab.tr(ttk.Checkbutton(row, variable=self.hide_plain_var,
                                    command=self.refilter),
                    "world.monsters.hide_plain").pack(side="left")
        ttk.Label(row, textvariable=self.plain_count_var,
                  foreground="#888").pack(side="left", padx=(6, 0))

    # -- what is SHOWN, which is never what is kept -------------------------
    def narrow(self, rows) -> list:
        """Hold back the ordinary field monsters when the box asks for it (#1549).

        A DISPLAY RULE and nothing else, which is the rule of this repository and the one
        that has cost most when it was got wrong: the rows stay in the model, stay in the
        checkpoint and come straight back when the box is unticked. Only `visible_rows`
        goes through here.
        """
        if not self.hide_plain_var.get():
            return rows
        return [r for r in rows if not is_plain(r)]

    def plain_hidden(self) -> int:
        """How many rows THIS box is holding back — the number beside it."""
        if not self.hide_plain_var.get():
            return 0
        return sum(1 for r in self._rows.values()
                   if is_plain(r) and self.in_level_range(r))

    def _update_count(self) -> None:
        super()._update_count()
        hidden = self.plain_hidden()
        self.plain_count_var.set(
            self.tab.t("world.monsters.plain_hidden", n=hidden) if hidden else "")

    def config(self) -> dict:
        return dict(super().config(), pace=self.pace_var.get(),
                    stages=self.stages_var.get(),
                    follow=bool(self.follow_var.get()),
                    follow_secs=self.follow_secs_var.get(),
                    hide_plain=bool(self.hide_plain_var.get()))

    def apply_config(self, raw) -> None:
        super().apply_config(raw)
        grid.take(raw, "pace", self.pace_var, str)
        grid.take(raw, "stages", self.stages_var, str)
        grid.take(raw, "follow", self.follow_var)
        grid.take(raw, "follow_secs", self.follow_secs_var, str)
        grid.take(raw, "hide_plain", self.hide_plain_var)

    def persist_vars(self) -> list:
        return super().persist_vars() + [self.pace_var, self.stages_var,
                                         self.follow_var, self.follow_secs_var,
                                         self.hide_plain_var]

    def follow_seconds(self) -> int:
        """How often the register is asked, never so often that it is all the panel does.

        A blank box is somebody who has not chosen rather than somebody who chose zero,
        and both fall back to the default. Five seconds is the floor: the ask itself is
        36 ms, but each one takes the profile's game claim, and a claim taken three times
        a second is a claim nothing else can have.
        """
        raw = str(self.follow_secs_var.get()).strip()
        try:
            value = int(float(raw))
        except ValueError:
            return int(self.DEFAULT_FOLLOW)
        return max(5, value) if value > 0 else int(self.DEFAULT_FOLLOW)

    def pace(self) -> float:
        """The seconds-per-stop the person asked for, never below what draws anything.

        A zero would be a lap that collects nothing while looking like it worked, and a
        blank box is a person who has not chosen rather than one who chose zero — so both
        fall back to the default instead of to the fastest possible lap.
        """
        raw = str(self.pace_var.get()).strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            return float(self.DEFAULT_PACE)
        return value if value > 0 else float(self.DEFAULT_PACE)

    def stages(self) -> list:
        """`[(height, step)]` — the laps this page walks, in order.

        A height nobody named falls back to the one the measurement supports, so an empty
        box is still a working lap. A height with no step of its own is walked with the
        nearest one that has: the pairing is what makes a lap complete, and a step from
        another height is a lap with holes in it.
        """
        out = []
        for chunk in str(self.stages_var.get()).replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk.isdigit():
                continue
            height = int(chunk)
            step = self.STAGE_STEPS.get(height)
            if step is None:
                step = self.STAGE_STEPS[min(self.STAGE_STEPS,
                                            key=lambda h: abs(h - height))]
            out.append((height, step))
        return out or [(600, self.STAGE_STEPS[600])]

    def decorate(self, row, record) -> None:
        super().decorate(row, record)
        row["monster_type"] = record.get("monster_type")
        # …and the game's own uuid, which only the register answers with. NEVER cleared
        # by a later read that lacks it: a lap of the drawn clones re-sees the same tile
        # and knows no uuid, and dropping the one the register gave would take the march
        # away from a row that had it (#1523).
        if record.get("game_uuid"):
            row["game_uuid"] = record.get("game_uuid")
        row["kind_name"] = record.get("kind_name") or ""
        row["cfg_id"] = record.get("cfg_id")
        row["source"] = record.get("source")
        row["point_id"] = record.get("point_id")

    def state_key(self, row, record) -> str:
        source = record.get("source")
        if source == "invasion":
            return "world.monster.src.invasion"
        # A row the world's own register answered for — the one kind that carries a uuid
        # and is therefore the one an attack can actually be aimed at (#1523).
        if source == "world":
            return "world.monster.src.world"
        if source == "lap":
            return "world.monster.src.lap"
        return "world.monster.src.scene"

    def rank(self, row) -> tuple:
        """The highest level first — the one worth a rally is the one worth showing."""
        return (-int(row.get("level") or 0), -float(row.get("seen_at") or 0),
                str(row.get("uuid") or ""))

    def species_text(self, row) -> str:
        """What KIND of monster this is: the game's own word where it answered.

        `lw_world_monster.type` is the split the player reads off the screen — 7 the
        zombie line, 8 the Doom line — and it is only answerable for a row that carried
        a config id. One that did not falls back to the drawn object's own name, which
        is all a roaming monster says about itself before it is selected.
        """
        key = MONSTER_TYPE_KEYS.get(int(row.get("monster_type") or 0))
        if key:
            return self.tab.t(key)
        name = row.get("kind_name") or ""
        return name or self.tab.t("world.monster.type.unknown")

    @staticmethod
    def level_text(row) -> str:
        """The level, or a dash for the one the game would not name.

        NOT `0`. A drawn monster carries no config id, so for as long as this page has
        existed every scene-read row showed «0» — including a level-10 golden zombie,
        which is the reading that sent #1519 looking. The recipe now answers `-1` where
        nobody could say, and a dash is what that looks like: it reads as «unknown» to a
        person, sorts to the bottom, and cannot be mistaken for a weak monster.
        """
        level = row.get("level")
        return str(int(level)) if level else "—"

    def row_values(self, row) -> tuple:
        return (_coords(row),
                self.tab.t("secrettasks.server", srv=row.get("server")),
                self.species_text(row),
                self.level_text(row),
                row["timer"].get())

    def web_facts(self, row) -> list:
        return [{"label": "world.col.species", "value": self.species_text(row)},
                {"label": "secrettasks.col.level", "value": self.level_text(row)},
                {"label": "secrettasks.col.state",
                 "value": self.tab.t(row.get("state_key")
                                     or "world.monster.src.scene")}]


# ---------------------------------------------------------------------------
# Trucks and trains — the two that ride the march stream
# ---------------------------------------------------------------------------
def _next_stop_key(row) -> tuple:
    """How the «Следующая точка» heading orders: the rows still moving first.

    A row with no hop sorts last whatever its coordinate says — it is the one row on the
    page whose point is not an answer to «where is it», so it does not belong among the
    ones that are.
    """
    dst = row.get("leg_to") or ()
    ranks = {LEG_MOVING: 0, LEG_PARKED: 1}
    return (ranks.get(row.get("leg_state"), 2),
            int(dst[0]) if len(dst) > 1 else 0,
            int(dst[1]) if len(dst) > 1 else 0,
            str(row.get("uuid") or ""))


class _VehicleGrid(WorldGrid):
    """What a truck and a train share: a leg, an arrival, and an owner.

    **AND THE FACT THAT THEY ARE MOVING** (#1298). Every other row on this tab is a tile
    and stays where it is until the game says otherwise; these two are marches. The
    server never sends a position for one — it sends the hop's two endpoints and the two
    times it runs between, and the client draws the vehicle by walking one towards the
    other on the game's own clock (`lastwar_proto.march_position`).

    So the coordinate on these pages is COMPUTED, on every tick, from the leg the row is
    carrying. It used to be the `x`/`y` the capture wrote down at the moment it decoded
    the frame, which is «where it was when we heard about it» — a truck that had been out
    for ten minutes was drawn on a tile it had left nine minutes earlier, and the row
    never moved again until the server happened to re-send it.
    """

    HAS_CLOCK = True
    #: The leg is what a position is computed FROM, so it survives a restart with the
    #: rest of the row — a checkpointed vehicle goes on moving after it is read back.
    PERSIST_KEYS = WorldGrid.PERSIST_KEYS + ("owner_name", "alliance_abbr",
                                             "leg_from", "leg_to",
                                             "leg_start_ms", "leg_end_ms")

    #: What these two count down TO. Not «готово через …» — there is nothing here to
    #: press when the clock runs out; the vehicle simply reaches its stop and leaves the
    #: map, which is also when the row goes.
    UNTIL_KEY = "world.vehicle.arrives"

    def decorate(self, row, record) -> None:
        super().decorate(row, record)
        row["until_key"] = self.UNTIL_KEY
        row["owner_name"] = record.get("owner_name") or ""
        row["alliance_abbr"] = record.get("alliance_abbr") or ""
        self.set_leg(row, record)

    def update_row(self, row, record) -> None:
        super().update_row(row, record)
        row["owner_name"] = record.get("owner_name") or ""
        self.set_leg(row, record)

    def set_leg(self, row, record) -> None:
        """Take the hop the server last described, and stand the row on it now.

        The `x`/`y` in the record are only a fallback — they are the position the
        capture computed once, when it decoded the frame. A record that carries a leg
        gets its coordinate re-derived immediately, so a row is right the moment it
        lands rather than at the next tick.
        """
        row["leg_from"] = list(record.get("leg_from") or ())
        row["leg_to"] = list(record.get("leg_to") or ())
        row["leg_start_ms"] = record.get("leg_start_ms")
        row["leg_end_ms"] = record.get("leg_end_ms")
        row["leg_state"], where = vehicle_leg(row)
        if where is not None:
            row["x"], row["y"] = where

    def next_stop_text(self, row) -> str:
        """The hop's far end, beside the tile it is on now — «где» and «успею ли» (#1298).

        **IT IS THE NEXT STOP AND NOT THE DESTINATION, and the wording says so.** The
        server describes one hop at a time: a truck watched across two re-sends went
        `A → B` and then `B → C`, so `leg_to` is a waypoint. Where the whole run ENDS is
        not on the wire at all — only `arriveTime` is, which the state cell already counts
        down. Calling this column «Куда» would be inventing a fact the game never sent.

        And it is where the row says whether its coordinate is alive: a hop still running
        reads «→ …», a hop that is over reads «стоит …» — the vehicle really is standing
        there until the next hop is pushed, which is what the client draws too — and a row
        with no hop says outright that its point is the last one we were told, rather than
        letting a frozen number pass for a live one.
        """
        state, _where = vehicle_leg(row)
        dst = row.get("leg_to") or ()
        if state == LEG_NONE or len(dst) < 2:
            return self.tab.t("world.vehicle.leg_unknown")
        import coords as coords_fmt
        where = coords_fmt.fmt(dst[0], dst[1])
        return self.tab.t("world.vehicle.leg_moving" if state == LEG_MOVING
                          else "world.vehicle.leg_parked", where=where)

    def advance(self) -> bool:
        """Walk every row along its leg — the per-second half of «where is it NOW».

        Cheap by construction: no game, no server and no file, just the game clock and
        two endpoints per row. What it costs is the redraw it asks for, and only when a
        row has actually changed tile — a truck crossing thirty tiles in two minutes
        moves a cell about every four seconds, not four times a second.
        """
        moved = False
        for row in self._rows.values():
            state, where = vehicle_leg(row)
            if where is not None and (where[0], where[1]) != (row.get("x"), row.get("y")):
                row["x"], row["y"] = where
                moved = True
            # …and the moment a hop ENDS the coordinate stops changing, which is exactly
            # when the row has to stop claiming to be moving. Without this the cell would
            # freeze still reading «→ …» — the very confusion the split is for.
            if state != row.get("leg_state"):
                row["leg_state"] = state
                moved = True
        return moved

    def rank(self, row) -> tuple:
        return (row.get("expires_at") or float("inf"), str(row.get("uuid") or ""))


class TruckGrid(_VehicleGrid):
    """The player trucks — where each one is now, how full, and how long it is out."""

    CONFIG_KEY = "trucks"
    SOURCE = "trucks"
    INTAKE = "world.checkpoint"
    TITLE_KEY = "world.trucks"
    HINT_KEY = "world.trucks.hint"
    EMPTY_KEY = "world.trucks.empty"

    COLUMNS = (
        ("owner", "secrettasks.col.owner", 150, "w", False),
        ("coords", "secrettasks.col.coords", 150, "w", False),
        # …and the far end of the hop it is on, beside the tile it is on NOW (#1298):
        # one answers «где», the other «успею ли», and asking for the second separately
        # is a round trip for something already in the row.
        ("next", "world.col.next_stop", 170, "w", False),
        ("server", "secrettasks.col.server", 90, "w", False),
        ("kind", "world.col.tier", 120, "w", False),
        ("state", "secrettasks.col.state", 200, "w", True),
        ("cargo", "world.col.cargo", 110, "center", False),
        ("robs", "world.col.robs", 90, "center", False),
    )
    SORT_KEYS = {
        "owner": lambda r: ((r.get("owner_name") or "").lower(), str(r["uuid"])),
        "coords": lambda r: (int(r["x"] or 0), int(r["y"] or 0), str(r["uuid"])),
        "next": _next_stop_key,
        "server": lambda r: (int(r["server"] or 0), str(r["uuid"])),
        "kind": lambda r: (str(r.get("tier") or ""), int(r["level"] or 0),
                           str(r["uuid"])),
        "state": lambda r: (r.get("expires_at") or 0, str(r["uuid"])),
        "cargo": lambda r: (int(r.get("cargo") or 0), str(r["uuid"])),
        "robs": lambda r: (int(r.get("rob_times") or 0), str(r["uuid"])),
    }
    PERSIST_KEYS = _VehicleGrid.PERSIST_KEYS + ("tier", "tier_name", "cargo",
                                                "rob_times", "free_robs")

    def decorate(self, row, record) -> None:
        super().decorate(row, record)
        row["tier"] = record.get("tier")
        row["tier_name"] = record.get("tier_name") or ""
        row["cargo"] = record.get("cargo") or 0
        row["rob_times"] = record.get("rob_times") or 0
        row["free_robs"] = record.get("free_robs")

    def update_row(self, row, record) -> None:
        super().update_row(row, record)
        row["cargo"] = record.get("cargo") or 0
        row["rob_times"] = record.get("rob_times") or 0

    def rank(self, row) -> tuple:
        """The fattest haul first — the raid order `filter_trucks` already prizes."""
        return (-int(row.get("cargo") or 0), int(row.get("rob_times") or 0),
                str(row.get("uuid") or ""))

    def tier_text(self, row) -> str:
        """«ур. N, <grade>» — and the grade names have never been checked by eye.

        `lastwar_proto.TRUCK_TIER_NAMES` is an inference from the cargo ordering: what
        the evidence establishes is the ORDER, not which colour the client paints each
        rank. So the tier number is said as well as its name, and the number is the part
        to trust.
        """
        name = str(row.get("tier_name") or row.get("tier") or "")
        return self.tab.t("world.truck.tier", level=int(row.get("level") or 0),
                          tier=name)

    def row_values(self, row) -> tuple:
        return (row.get("owner_name") or "",
                _coords(row),
                self.next_stop_text(row),
                self.tab.t("secrettasks.server", srv=row.get("server")),
                self.tier_text(row),
                row["timer"].get(),
                human_number(row.get("cargo")),
                "%d/%d" % (int(row.get("rob_times") or 0), 4))

    def web_facts(self, row) -> list:
        return [{"label": "world.col.next_stop", "value": self.next_stop_text(row)},
                {"label": "world.col.tier", "value": self.tier_text(row)},
                {"label": "world.col.cargo",
                 "value": human_number(row.get("cargo"))},
                {"label": "world.col.robs",
                 "value": "%d/%d" % (int(row.get("rob_times") or 0), 4)}]


class TrainGrid(_VehicleGrid):
    """The alliance train — whose it is, how many are aboard, and when it arrives."""

    CONFIG_KEY = "trains"
    SOURCE = "trains"
    INTAKE = "world.checkpoint"
    TITLE_KEY = "world.trains"
    HINT_KEY = "world.trains.hint"
    EMPTY_KEY = "world.trains.empty"

    COLUMNS = (
        ("owner", "world.col.alliance", 170, "w", False),
        ("coords", "secrettasks.col.coords", 150, "w", False),
        ("next", "world.col.next_stop", 170, "w", False),
        ("server", "secrettasks.col.server", 90, "w", False),
        ("kind", "world.col.carriages", 130, "w", False),
        ("state", "secrettasks.col.state", 200, "w", True),
        ("cargo", "world.col.fullness", 110, "center", False),
    )
    SORT_KEYS = {
        "owner": lambda r: ((r.get("alliance_abbr") or "").lower(), str(r["uuid"])),
        "coords": lambda r: (int(r["x"] or 0), int(r["y"] or 0), str(r["uuid"])),
        "next": _next_stop_key,
        "server": lambda r: (int(r["server"] or 0), str(r["uuid"])),
        "kind": lambda r: (int(r.get("passengers") or 0), str(r["uuid"])),
        "state": lambda r: (r.get("expires_at") or 0, str(r["uuid"])),
        "cargo": lambda r: (float(r.get("completeness") or 0), str(r["uuid"])),
    }
    PERSIST_KEYS = _VehicleGrid.PERSIST_KEYS + ("alliance_name", "seats",
                                                "passengers", "completeness",
                                                "gift_level", "rob_times")

    def decorate(self, row, record) -> None:
        super().decorate(row, record)
        row["alliance_name"] = record.get("alliance_name") or ""
        row["seats"] = record.get("seats") or 0
        row["passengers"] = record.get("passengers") or 0
        row["completeness"] = record.get("completeness")
        row["gift_level"] = record.get("gift_level")
        row["rob_times"] = record.get("rob_times") or 0

    def update_row(self, row, record) -> None:
        super().update_row(row, record)
        row["completeness"] = record.get("completeness")
        row["rob_times"] = record.get("rob_times") or 0

    def fullness_text(self, row) -> str:
        """How much of it is still aboard — the game's own `completeness`, as a percent."""
        share = row.get("completeness")
        if share is None:
            return ""
        return "%d%%" % int(round(float(share) * 100))

    def row_values(self, row) -> tuple:
        return (row.get("alliance_abbr") or row.get("alliance_name") or "",
                _coords(row),
                self.next_stop_text(row),
                self.tab.t("secrettasks.server", srv=row.get("server")),
                self.tab.t("world.train.carriages",
                           seats=int(row.get("seats") or 0),
                           people=int(row.get("passengers") or 0)),
                row["timer"].get(),
                self.fullness_text(row))

    def web_facts(self, row) -> list:
        return [{"label": "world.col.next_stop", "value": self.next_stop_text(row)},
                {"label": "world.col.alliance",
                 "value": row.get("alliance_name") or row.get("alliance_abbr") or ""},
                {"label": "world.col.carriages",
                 "value": self.tab.t("world.train.carriages",
                                     seats=int(row.get("seats") or 0),
                                     people=int(row.get("passengers") or 0))},
                {"label": "world.col.fullness", "value": self.fullness_text(row)}]


# ---------------------------------------------------------------------------
# Turning what the sources say into what a row is made of
# ---------------------------------------------------------------------------
def mine_records(raw) -> list:
    """The world checkpoint's mines, in the shape a row is built from."""
    out = []
    for item in raw or ():
        if not isinstance(item, dict):
            continue
        out.append({"uuid": item.get("uuid"), "server": item.get("server_id"),
                    "x": item.get("x"), "y": item.get("y"),
                    "level": item.get("level"), "resource": item.get("resource"),
                    "family": item.get("family"), "free": bool(item.get("free")),
                    "owner_uid": item.get("owner_uid"),
                    "alliance_id": item.get("alliance_id"),
                    "seen_at": item.get("seen_at")})
    return out


def _leg(item) -> dict:
    """The hop a vehicle is on, carried through to the row (#1298).

    THE FIELDS THAT WERE BEING DROPPED. The checkpoint has always had them — the
    decoder writes `leg_from` / `leg_to` / `leg_start_ms` / `leg_end_ms` beside the
    `x`/`y` it computed off them — and these two builders took the computed pair and
    left the leg behind, which is exactly why the tables froze a truck on the tile it
    was standing on when the frame arrived.
    """
    return {"leg_from": item.get("leg_from"), "leg_to": item.get("leg_to"),
            "leg_start_ms": item.get("leg_start_ms"),
            "leg_end_ms": item.get("leg_end_ms")}


def truck_records(raw) -> list:
    """…and its trucks. `arrive_at` becomes the row's own deadline (`expires_at`)."""
    out = []
    for item in raw or ():
        if not isinstance(item, dict):
            continue
        out.append(dict({"uuid": item.get("uuid"), "server": item.get("server_id"),
                         "x": item.get("x"), "y": item.get("y"),
                         "level": item.get("level"), "tier": item.get("tier"),
                         "tier_name": item.get("tier_name"),
                         "owner_name": item.get("owner_name"),
                         "alliance_abbr": item.get("alliance_abbr"),
                         "cargo": item.get("cargo"),
                         "rob_times": item.get("rob_times"),
                         "free_robs": item.get("free_robs"),
                         "expires_at": item.get("arrive_at"),
                         "seen_at": item.get("seen_at")}, **_leg(item)))
    return out


def train_records(raw) -> list:
    """…and its alliance trains."""
    out = []
    for item in raw or ():
        if not isinstance(item, dict):
            continue
        out.append(dict({"uuid": item.get("uuid"), "server": item.get("server_id"),
                         "x": item.get("x"), "y": item.get("y"),
                         "owner_name": item.get("owner_name"),
                         "alliance_abbr": item.get("alliance_abbr"),
                         "alliance_name": item.get("alliance_name"),
                         "seats": item.get("seats"),
                         "passengers": item.get("passengers"),
                         "completeness": item.get("completeness"),
                         "gift_level": item.get("gift_level"),
                         "rob_times": item.get("rob_times"),
                         "expires_at": item.get("arrive_at"),
                         "seen_at": item.get("seen_at")}, **_leg(item)))
    return out


def parse_monsters(text, server=None, now=None) -> list:
    """`actions/read_world_monsters.md`'s one variable, as records.

    The scenario answers with records separated by « | », each a run of `key=value`
    pairs (its own docstring has the shape). Parsed here rather than in the tab for the
    reason every parser on this tab is a plain function: it is testable without a Tk
    root, and it is where a change in the scenario's wording is noticed.

    A row is keyed by its TILE and its server, because a drawn monster carries no uuid
    until it is selected — the same identity a mine has, and for the same reason.
    """
    now = time.time() if now is None else now
    out = []
    for chunk in str(text or "").split("|"):
        fields = {}
        for token in chunk.split():
            name, _, value = token.partition("=")
            if _:
                fields[name] = value
        pid = fields.get("pid")
        if not pid or not pid.isdigit():
            continue
        def number(name):
            raw = fields.get(name) or ""
            return int(raw) if raw.lstrip("-").isdigit() else 0
        # -1 is the reading's own «nobody could say» (`read_world_monsters.md`), and it
        # is kept apart from a level all the way to the cell: «уровень 0» over a level-10
        # zombie is a lie, and a lie is worse than a dash (#1519).
        level = number("level")
        # THE GAME'S OWN UUID, kept beside the tile key and never instead of it (#1523).
        # A drawn clone has none until it is selected, so the ROW is still identified by
        # its tile — but the world's own register (`SCAN_MONSTERS`) answers with the real
        # uuid, and that is the one field a march cannot be sent without. Carried through
        # so an ability that attacks a monster has it without asking again, and left out
        # rather than zeroed when nobody could say.
        game_uuid = str(fields.get("uuid") or "").strip()
        out.append({
            "uuid": "%s:%s" % (server or 0, pid),
            "game_uuid": game_uuid if game_uuid.isdigit() and game_uuid != "0" else None,
            "point_id": int(pid),
            "server": server,
            "x": number("x"), "y": number("y"),
            "level": (level if level > 0 else None),
            "monster_type": number("type"),
            "cfg_id": number("cfg") or None,
            "kind_name": fields.get("kind") or "",
            "source": fields.get("src") or "scene",
            "seen_at": int(now),
        })
    return out
