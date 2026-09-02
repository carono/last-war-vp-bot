"""«Игроки» — the register of everyone this account has met (#1335, #1371).

## What fills it, and what it costs

Nothing of its own. A lap of the map (`actions/scan_map.md`) makes the client fetch
every tile it drives over, the profile's ONE capture decodes those answers already, and
a player's base is simply one of the tile kinds in them — so this page adds no process,
no npcap handle and no game read to a sweep. The second listener inside that capture
(`tools/lib/world_index.py`) keeps what it hears in the profile's `world_map.json`, and
this page merges from there on a slow tick.

**And a lap is no longer the only source** (#1371). Everywhere else the panel already
meets a player — the live block of banners, the chat, the alliance roster, the owner of
a secret-task or ghost-recon tile — now writes into the same register through the ONE
entrance on the runtime, `rt.players.sighted(records, source=…)`. None of them sends
anything: each passes on what it happened to hear while doing its own job, and a source
may only write the fields it can actually know (`panel/runtime/players.py`). Every field
remembers who said it and when, which is what the «Откуда» column and «Подробно» show.

**And it asks the game for nothing, ever** — that is the second half of the bargain.
Not on opening the page, not behind a filter, not behind a sort, not for the row
somebody selected. A sweep sees thousands of players and a top-up per player would be
thousands of requests nobody asked for, so an empty field stays empty and the page says
«нет данных» rather than sending for it.

What a base tile carries, measured over one recorded whole-server lap of 6 723 of them:
the player's uid, name, HQ level, country, coordinates, server and the tile's uuid on
every single one; their alliance's uuid and TAG on the quarter of them who are in an
alliance. What it does not carry is any combat number — power, army power, lifetime
kills and SVIP level are only ever in a `get.user.info.multi` reply, which the client
sends when a base is OPENED (and in a batch for the alliance roster at login). Those
are folded in when they happen to arrive; nothing here asks for them per player,
because a lap sees seven thousand players and seven thousand lookups is not a sweep,
it is an attack on the server.

The alliance's full NAME is on the alliance's own city tiles, which the same lap drives
past — joined by the alliance uuid, so it is exact. It only covers the alliances that
own a city (11 of 107 in that lap), which is why the tag is what the table sorts by.

## The rule of the list

**A row leaves for exactly one reason: a person asked.** Not a lap that found nobody,
not a capture that was not running, not a restart, not the tab being opened. All of
those are «this read said nothing», and the whole of `panel/kept.py` exists because
three of them were once treated as «gone» (#1282). Everything else the page does to
narrow what is on screen is a FILTER — «давно не виден» hides a row and never removes
it. The rule and its reasoning live beside the model, in `registry.py`.

## Two notes, never one

`remark` is the note the GAME holds on that player: written in the client, stored
server-side, and arriving here once at login. The panel shows it and never writes it —
the command that sets one has never been captured, so a panel that «kept it in step»
would be keeping a second version of a truth it cannot see. `note` is this profile's
own mark, written here by the person and by nothing else; no lap may touch it.

The COLUMN shows whichever of them there is (`note_of`), and «Только с меткой» narrows
by that same column rather than by one of the two notes behind it (#1968).

## Both front-ends

The window has the table, the filters, the two writes, a coordinate that jumps the
camera when it is clicked and a «Подробно» that says where every field came from. The
phone has the same list under the renderer's own search box, the same filters as cycling
presses (one state: a press moves the very variables the window's boxes are bound to),
the same two writes — the mark through a prompting action, the forgetting through a
press that asks once and does the deed on the second press within half a minute, which
is the phone's version of the window's confirmation dialog — and the same two new
presses, «Перейти» and «Подробно», the second of which opens the same list as a card at
the top of the screen.

## The phone draws CARDS, and it can sort and search the register (#2119)

The list is not a table on the phone: nine columns is nine columns nobody reads on a
handset, so each player is the same card an errand is drawn as
(`panel/web/app/src/ui/ErrandCard.tsx`) — their own face out of the client's picture
cache behind it, their name on one line, the level, power, alliance, place and «когда
виден» under it, and the four presses on one row. The faces are resolved on a worker and
never in `web_view`: the first lookup for a uid walks a few thousand md5 sums.

**And the phone can move the SORT, which is what «грид не обновляется» turned out to
be.** The sort is saved with the profile, so one press of the «Игрок» heading at the
machine left it «by name, ascending» for good — and the phone, which had headings
neither to press nor to read, showed the same sixty names out of three hundred thousand
on every poll while the register behind them grew by hundreds a minute. Nothing was
stale and nothing was broken; the list was SORTED and no front-end said by what. The
renderer's own search box narrows only what is already drawn, so «Поиск» is a press too:
it writes the same `text` filter the window's box writes, and the narrowing happens in
the database.

## …and it PAGES the register, a thousand at a time (#2133)

#2119 said what was wrong and fixed half of it. The other half was the sixty. Measured
live while the report was being made: the capture's checkpoint held 203 fresh players,
the merge wrote 9 743 sightings in an hour, and the saved sort was «по имени, по
возрастанию» — so the first sixty names of the alphabet were on screen, and they are the
first sixty names of the alphabet whatever the map does. «Обновление данных игроков не
работает при обходе карты» was a page of sixty telling the truth about a register of
326 000.

Three things came out of it, and each is a rule rather than a repair:

* **A page is a thousand** (:data:`WEB_PAGE`), cut in SQL with a `LIMIT … OFFSET`, and
  the pager is two presses on the list card with «страница N из M» beside them.
* **A page does not ride the poll.** A thousand cards is some six hundred kilobytes and
  the screen is re-read every two and a half seconds, so the card carries `paged` and no
  items, and the phone fetches them off `/api/screen/data` (:meth:`PlayersTab.web_data`)
  when the card's STAMP moves. The stamp moves when a merge wrote rows, when the page
  turned, when the sort or a filter changed, and when a face arrived — so a lap of the
  map refreshes the cards BY ITSELF, and a lap that found nothing costs one unchanged
  integer.
* **The sort is two dropdowns**, not two cycling presses. A cycle whose next value nobody
  can see is a control people press until it lands, and nine columns is eight presses and
  eight re-reads to reach «мощь».

## …and the grid is DRIVEN FROM THE GRID (#2308)

#2133 left the page right and the controls wrong, and the person said so: «Управление
гридом с игроками максимально ущербное, интерфейс ужасен, это не работоспособно
абсолютно». What was above the list was a whole card of its own — two sort dropdowns,
six cycling filter presses and seven readings — so the first player stood a scroll below
the top of the screen, and the two controls that decide which thousand of three hundred
thousand are drawn were four taps away from the thousand.

So there is ONE card now, and it is the grid:

* **the sort is a row of small buttons over the rows**, one per column, and a press flips
  THAT column between ascending and descending — the window's own gesture, a click on a
  table heading. The button the list stands by wears its arrow, so the row says where it
  is without anybody pressing anything;
* **the filters are the grid's own knobs, behind the gear beside its heading**, in the
  one modal this front-end has. Dropdowns rather than cycles: a control has to say where
  the next press lands;
* **the server filter exists at last** — the warzones the register has actually seen,
  read on the worker that answers for a page and kept for a minute
  (:data:`SERVERS_GOOD_FOR`), because a `DISTINCT` over three hundred thousand rows is
  not a question for the loop every open profile's window shares.

**And a base's card is what a person reads at a glance.** The mark rides the NAME
(«Метку выводим у имени»), «Откуда» is gone from the card, and so are the four buttons:
what is left is who, what level, how strong, whose alliance, where and when they were
last seen. Everything else — every field with who said it and how long ago, and the
presses that act on the row — is behind an «i» in the top-right corner, in the same one
modal, FETCHED when it is opened. Nothing is lost: a press in a sheet one tap away is
still a press the phone has, and a dozen provenance lines times a page of a thousand
would have doubled what the page costs so that one of them could be read.

## The one thing here that touches the client

The coordinate press, and nothing else (#1371). Jumping the camera to a tile is a person
asking for something to HAPPEN, which is never what «this page asks the game nothing»
was about — that rule is about topping a row up behind somebody's back. The panel has
one coordinate mechanism (`tools/lib/coords.py` + `rt.game.jump`), used by the log, the
chat and every table that prints a tile, and this table uses that one rather than a
second of its own.
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ...widgets import tk_stringvar
from ..base import PanelTab
from . import registry as reg
from ...runtime import statevar

#: How often the page merges the capture's checkpoint into the register while somebody
#: is looking at it. A lap of the map takes about three seconds and the capture flushes
#: its checkpoint every fifteen, so anything faster than the flush is a file read that
#: cannot have anything new in it.
MERGE_EVERY_MS = 20_000

#: How many rows the table draws. A whole server is seven thousand players, and seven
#: thousand Tk rows is a table nobody reads on the one event loop every open profile
#: shares (#1226). The rest are counted into «скрыто», out loud, because a silent
#: truncation reads as «that is all there was».
MAX_SHOWN = 400

#: …AND HOW MANY THE PHONE GETS AT A TIME — one PAGE of the register (#2133).
#:
#: It was sixty, on the reasoning that the whole screen is rebuilt into the DOM on every
#: poll. That reasoning was sound about the POLL and wrong about the page, and it is
#: what «данные игроков не обновляются при обходе карты» actually was: sixty rows out of
#: three hundred and twenty-six thousand, under a sort saved as «по имени, по
#: возрастанию», are the same sixty names for ever. The lap ran, the register took nine
#: thousand seven hundred sightings an hour, and not one of them could reach the screen.
#:
#: So the page is a thousand, and the poll is no longer what carries it: a card that
#: declares `paged` is fetched off `/api/screen/data` (`web_data`) when its STAMP moves,
#: which is when a merge wrote something, when the page turned, or when the sort or a
#: filter changed. A lap that adds nothing changes no stamp and costs nothing.
WEB_PAGE = 1000

#: How long :meth:`PlayersTab.web_data` may spend resolving faces it has not seen before.
#: A uid nobody has looked up costs about 10 ms (`tools/lib/player_faces.py` hashes
#: `uid_0` … `uid_4000`), so a thousand fresh ones would be ten seconds of an HTTP
#: worker. A page therefore fills in over a few readings and the ones already found are
#: free — and a card with no picture draws its words, which is the honest answer.
FACE_BUDGET_SEC = 1.0

#: The columns, in order: (id, width, anchor).
COLUMNS = (
    ("name", 150, "w"),
    ("level", 45, "center"),
    ("power", 90, "e"),
    ("alliance", 70, "w"),
    ("coords", 110, "w"),
    ("server", 55, "center"),
    ("seen", 90, "w"),
    ("source", 90, "w"),
    ("note", 160, "w"),
)

#: WHAT THE PHONE'S «Сортировка» STEPS THROUGH — the sortable columns, in the window's
#: own order, taken from :data:`COLUMNS` rather than written out a second time. The
#: window sorts by pressing a heading and the phone had no way to sort at all, which is
#: what «грид не обновляется» turned out to be (#2119): a sort saved as «по имени» from
#: one press at the machine left the phone showing the same sixty names out of three
#: hundred thousand for ever, with nothing on the screen saying why.
SORT_STEPS = tuple(col for col, _w, _a in COLUMNS if col in reg.SORT_KEYS)

#: HOW LONG A CACHED LIST OF SERVERS IS GOOD FOR (#2308). The server filter is a
#: dropdown of every warzone the register has seen, and «every warzone the register has
#: seen» is a `DISTINCT` over three hundred thousand rows — far too dear to run on the
#: Tk thread every time the phone re-reads the screen. So it is read on the worker that
#: answers for a page and kept, and a warzone met in the last minute joins the list on
#: the next page fetch rather than instantly.
SERVERS_GOOD_FOR = 60.0

#: The column a click JUMPS from. A coordinate printed anywhere in the panel is a place
#: you can go (`panel/widgets.py`, the log's own links), and a table that prints one and
#: cannot be clicked is the odd one out rather than the careful one.
COORD_COLUMN = "coords"

#: What the «уровень» press steps through on the phone, and what the window's two
#: boxes hold. The same list, so the two front-ends cannot drift into meaning
#: different things by «30+».
LEVEL_STEPS = (None, 20, 25, 30, 35)
#: …and the same for power, in millions.
POWER_STEPS = (None, 1_000_000, 10_000_000, 50_000_000, 100_000_000)
#: The server filter's steps are the servers the REGISTER holds — worked out when the
#: press is made, never a table here. `""` is «any».
SEEN_STEPS = ("any", "hour", "day", "week", "stale")

#: Every filter at «any» — the one spelling of it, used to make the state and to
#: reset it. Two spellings disagreed about what «any server» is within an hour of
#: existing.
BLANK_FILTER = {"text": "", "level_min": None, "level_max": None,
                "power_min": None, "power_max": None, "alliance": "",
                "server": "", "rect": None, "circle": None,
                "seen": "any", "noted": False}

#: How long a «Забыть» press from the phone stays armed. Long enough to press twice on
#: purpose, short enough that a phone left in a pocket disarms itself.
FORGET_ARMED_SEC = 30


def human_power(value) -> str:
    """A power as a person reads it — «12.4M», not «12408311».

    A pure numeric format and one of the few literals allowed on a panel tab
    (`CLAUDE.md`): there is no word in it to translate.
    """
    number = float(value or 0)
    if not number:
        return "—"
    for suffix in ("", "K", "M", "B"):
        if abs(number) < 1000 or suffix == "B":
            return "%d%s" % (number, suffix) if suffix == "" else "%.1f%s" % (number, suffix)
        number /= 1000.0
    return str(int(value or 0))


class PlayersTab(PanelTab):
    ID = "players"
    TITLE_KEY = "tab.players"
    ORDER = 260
    LOCALE_NS = ("players",)
    #: The daemon, and ONLY for the coordinate press (#1371). Nothing on this page READS
    #: the game — not on opening, not behind a filter, not behind a sort, not for a
    #: selected row; a field no source carried stays empty and says so, and
    #: `tests/test_players_registry.py` fails on the day anything here asks the client a
    #: question. What the daemon is for is the person clicking a tile to go there.
    NEEDS = frozenset({"daemon"})
    PREFERRED_SIZE = "1040x640"
    WEB_SCREEN = True
    #: EAGER, and this is the one thing about the tab that had to be measured live: the
    #: capture's checkpoint holds a sighting for fifteen minutes, so a lap driven by the
    #: schedule at three in the morning is gone long before anybody clicks this page. A
    #: register that only collects while somebody is watching it is not a register. What
    #: `ensure_loaded` starts is therefore something that has to be RUNNING — the merge —
    #: and it reads a file on a worker thread and never the game, which is the bar the
    #: contract test holds an EAGER tab to.
    EAGER = True

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        # EVERYTHING ANSWERABLE BEFORE ANYBODY LOOKS lives here (`PanelTab.LAZY`): the
        # phone can open this screen without the window ever having drawn the tab.
        # THE RUNTIME'S register, not one of this tab's own (#1371): the banner block,
        # the chat and the alliance roster write into the same book, and a second
        # instance over the same file would be two caches of one truth.
        self._registry = rt.players
        self._sort = reg.DEFAULT_SORT
        self._shown = 0
        self._hidden = 0
        self._merging = False
        self._armed_forget = (None, 0.0)
        # The filter, as ONE dict the window's variables write into and the phone's
        # presses move. Two front-ends, one state (`docs/panel-tabs.md`).
        self._filter = dict(BLANK_FILTER)
        #: uid -> the link to that player's face, `""` when there is none to draw. Filled
        #: on a worker and never in `web_view`: the first lookup for a uid walks a few
        #: thousand md5 sums (`tools/lib/player_faces.py`), and `web_view` runs on the Tk
        #: thread every open profile shares.
        self._faces = {}
        #: WHICH PAGE OF THE REGISTER THE PHONE IS ON, counted from zero (#2133). State
        #: rather than a query parameter so that everything which INVALIDATES a page —
        #: a filter, a sort, a search — resets it in the one place it is set
        #: (:meth:`_turned`), instead of in each of the six presses that move one.
        self._page = 0
        #: WHAT SAYS THE LIST HAS MOVED. Anything that changes what a page holds bumps
        #: it, and the phone re-fetches the page only when it has changed — that is what
        #: puts a lap of the map back on the screen without a card of a thousand players
        #: riding the two-and-a-half-second poll.
        self._stamp = 0
        #: THE SERVERS THE FILTER OFFERS, and WHEN they were read (#2308). A `DISTINCT`
        #: over the whole register is a question for a worker, never for the loop every
        #: open profile's window shares — so the list is refreshed inside
        #: :meth:`web_data` and merely read here.
        self._server_list = []
        self._server_read = 0.0
        self._tree = None
        self._vars = {}

    # -- the widgets --------------------------------------------------------
    def build(self) -> None:
        root = ttk.Frame(self.parent)
        root.pack(fill="both", expand=True, padx=8, pady=6)

        self._build_search(root)
        self._build_filters(root)
        self._build_table(root)
        self._build_footer(root)
        self._render()

    def _var(self, name: str, value: str = "") -> tk.StringVar:
        var = tk_stringvar(self.rt.root)
        var.set(value)
        var.trace_add("write", lambda *_a: self._on_filter_changed())
        self._vars[name] = var
        return var

    def _build_search(self, root) -> None:
        bar = ttk.Frame(root)
        bar.pack(fill="x")
        self.tr(ttk.Label(bar), "players.search").pack(side="left")
        ttk.Entry(bar, textvariable=self._var("text"), width=28).pack(
            side="left", padx=(4, 6))
        # What the one box searches, said out loud rather than left to be guessed: a
        # search that silently covers three things reads as a search that covers one.
        self.tr(ttk.Label(bar), "players.search.hint").pack(side="left", padx=(0, 10))
        self.tr(ttk.Button(bar, command=self.refresh), "players.refresh").pack(
            side="right")
        self.tr(ttk.Button(bar, command=self._reset_filters),
                "players.filters.reset").pack(side="right", padx=(0, 6))

    def _build_filters(self, root) -> None:
        box = ttk.LabelFrame(root, text="")
        self.tr(box, "players.filters")
        box.pack(fill="x", pady=(6, 4))

        line = ttk.Frame(box)
        line.pack(fill="x", padx=6, pady=(4, 2))
        self.tr(ttk.Label(line), "players.filter.level").pack(side="left")
        ttk.Entry(line, textvariable=self._var("level_min"), width=4).pack(side="left")
        ttk.Label(line, text="–").pack(side="left")
        ttk.Entry(line, textvariable=self._var("level_max"), width=4).pack(
            side="left", padx=(0, 10))

        self.tr(ttk.Label(line), "players.filter.power").pack(side="left")
        ttk.Entry(line, textvariable=self._var("power_min"), width=10).pack(side="left")
        ttk.Label(line, text="–").pack(side="left")
        ttk.Entry(line, textvariable=self._var("power_max"), width=10).pack(
            side="left", padx=(0, 10))

        self.tr(ttk.Label(line), "players.filter.alliance").pack(side="left")
        self._alliance_box = ttk.Combobox(line, textvariable=self._var("alliance"),
                                          width=8, values=[""])
        self._alliance_box.pack(side="left", padx=(0, 10))

        self.tr(ttk.Label(line), "players.filter.server").pack(side="left")
        # Filled from the register on every repaint (`_render`): the numbers are in the
        # rows already, so the box can offer them without asking the client anything.
        self._server_box = ttk.Combobox(line, width=10, state="readonly",
                                        values=[self.t("players.server.any")])
        self._server_box.current(0)
        self._server_box.bind("<<ComboboxSelected>>",
                              lambda _e: self._pick_server(self._server_box.current()))
        self._server_box.pack(side="left")

        line2 = ttk.Frame(box)
        line2.pack(fill="x", padx=6, pady=(2, 5))
        self.tr(ttk.Label(line2), "players.filter.rect").pack(side="left")
        for name in ("x1", "y1", "x2", "y2"):
            ttk.Entry(line2, textvariable=self._var(name), width=5).pack(side="left")
        ttk.Label(line2, text=" ").pack(side="left")

        self.tr(ttk.Label(line2), "players.filter.circle").pack(side="left", padx=(6, 0))
        for name in ("cx", "cy", "cr"):
            ttk.Entry(line2, textvariable=self._var(name), width=5).pack(side="left")

        self.tr(ttk.Label(line2), "players.filter.seen").pack(side="left", padx=(12, 0))
        self._seen_box = ttk.Combobox(line2, width=14, state="readonly",
                                      values=[self.t("players.seen." + s)
                                              for s in SEEN_STEPS])
        self._seen_box.current(0)
        self._seen_box.bind("<<ComboboxSelected>>",
                            lambda _e: self._on_choice("seen", SEEN_STEPS,
                                                       self._seen_box.current()))
        self._seen_box.pack(side="left", padx=(4, 10))

        self._noted = statevar.boolean(self.rt.root, False)
        self._noted.trace_add("write", lambda *_a: self._on_filter_changed())
        self.tr(ttk.Checkbutton(line2, variable=self._noted),
                "players.filter.noted").pack(side="left")

    def _build_table(self, root) -> None:
        holder = ttk.Frame(root)
        holder.pack(fill="both", expand=True)
        tree = ttk.Treeview(holder, columns=[c[0] for c in COLUMNS],
                            show="headings", selectmode="browse")
        bar = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        for col, width, anchor in COLUMNS:
            tree.column(col, width=width, anchor=anchor, stretch=(col in ("name", "note")))
            tree.heading(col, command=lambda c=col: self._sort_by(c))
        tree.bind("<Double-1>", lambda _e: self._edit_note())
        tree.bind("<Button-1>", self._on_click)
        self._tree = tree
        self._label_headings()

    def _on_click(self, event) -> None:
        """A click in the coordinate column jumps the camera there.

        The panel has ONE coordinate mechanism and this is it: the cell holds the same
        canonical token the log prints, `coords.parse` reads it back, and `rt.game.jump`
        does what the log's own link does (`panel/widgets.py`). Nothing here knows how
        to spell a coordinate or how to reach a tile — that would be the second
        mechanism this rule exists to prevent.
        """
        if self._tree is None or self._tree.identify("region", event.x, event.y) != "cell":
            return
        column = self._tree.identify_column(event.x)
        try:
            name = COLUMNS[int(column[1:]) - 1][0]
        except (ValueError, IndexError):
            return
        if name != COORD_COLUMN:
            return
        row = self._registry.get(self._tree.identify_row(event.y)) or {}
        self._jump(self.coords_of(row))

    def _jump(self, token: str) -> bool:
        """Go to a coordinate token — the person pressed something (`CLAUDE.md`).

        Off the Tk thread: a jump is a game round trip, and the event loop is shared by
        every open profile's window. Returns whether there was anything to go to.
        """
        import coords as coords_fmt
        hits = coords_fmt.parse(token or "")
        if not hits:
            return False
        _s, _e, x, y, server = hits[0]
        threading.Thread(target=self.rt.game.jump, args=(x, y, server),
                         daemon=True).start()
        return True

    def _build_footer(self, root) -> None:
        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=(6, 0))
        self._count = tk_stringvar(self.rt.root)
        ttk.Label(bar, textvariable=self._count).pack(side="left")
        self.tr(ttk.Button(bar, command=self._forget), "players.forget").pack(
            side="right")
        self.tr(ttk.Button(bar, command=self._edit_note), "players.note.edit").pack(
            side="right", padx=(0, 6))
        self.tr(ttk.Button(bar, command=self._show_details), "players.details").pack(
            side="right", padx=(0, 6))
        self.tr(ttk.Button(bar, command=self._jump_selected), "players.goto").pack(
            side="right", padx=(0, 6))
        # What the coordinate column does, said out loud: a link nobody knows is there
        # is a link nobody presses.
        self.tr(ttk.Label(bar), "players.coords.hint").pack(side="left", padx=(12, 0))

    def _label_headings(self) -> None:
        if self._tree is None:
            return
        for col, _w, _a in COLUMNS:
            mark = ""
            if self._sort and self._sort[0] == col:
                mark = " ▼" if self._sort[1] else " ▲"
            self._tree.heading(col, text=self.t("players.col." + col) + mark)

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Start the slow merge. Idempotent — `rt.tick` names its loops.

        Here rather than in `on_show` because the register is the point of the tab:
        a lap driven from the schedule while nobody is looking at this page still has
        to end up in it, or the list would only ever hold what somebody watched arrive.
        """
        self._tick()

    def on_show(self) -> None:
        """Somebody is looking: merge what the capture has, and NOTHING else.

        No read of the game lives on this tab at all — not here, not behind a filter,
        not behind a sort, not for a selected row. See `registry`, «Nothing here ever
        asks the game anything».
        """
        self._merge_async()

    def on_language_change(self) -> None:
        self._label_headings()
        if self._tree is not None:
            self._seen_box.configure(values=[self.t("players.seen." + s)
                                             for s in SEEN_STEPS])
            self._render()

    def shutdown(self) -> None:
        self.rt.tick.disarm("players.merge")

    def _tick(self) -> None:
        """Merge, then re-arm: `rt.tick.arm` fires once and the loop is the caller's."""
        self._merge_async()
        self.rt.tick.arm("players.merge", MERGE_EVERY_MS, self._tick)

    # -- the feed -----------------------------------------------------------
    def refresh(self) -> bool:
        """«Обновить» — merge now rather than on the next slow tick."""
        self._merge_async()
        return True

    def _merge_async(self) -> None:
        """Read the capture's checkpoint and merge it, OFF the Tk thread.

        A whole-server lap is seven thousand rows and the merge rewrites the register's
        file; doing that on the event loop would stall every open profile's window
        (`docs/panel-tabs.md`, «Coming back from a background thread»).
        """
        if self._merging:
            return
        self._merging = True
        threading.Thread(target=self._merge_work, daemon=True).start()

    def _merge_work(self) -> None:
        added = 0
        try:
            rows = reg.load_checkpoint(self.rt.profiles.world_json())
            if rows:
                with self.rt.activity.step("players.merging", n=len(rows)):
                    # THE ONE ENTRANCE, like every other source (#1371). The checkpoint
                    # is three sources in one file — the tile, the profile reply folded
                    # onto it and the account's own note — so its fields are attributed
                    # one by one rather than all being called «карта».
                    added = self._registry.sighted(
                        rows, source=reg.SRC_MAP,
                        field_source=reg.CHECKPOINT_SOURCES)
        except Exception as exc:                            # noqa: BLE001
            self.rt.say("players", "players.log.merge_failed", error=exc)
        finally:
            self._merging = False
        if added:
            self.rt.say("players", "players.log.merged", added=added,
                        total=len(self._registry))
            # THE LAP REACHES THE PHONE (#2133). The window repaints below; the web's
            # page of a thousand is fetched on its own and only when this moves, so
            # without this line a lap could write nine thousand sightings an hour into
            # the register and the cards on screen would never once change.
            self._moved()
        self.post(self._render)

    # -- filtering ----------------------------------------------------------
    def _number(self, name: str):
        raw = (self._vars[name].get() or "").strip() if name in self._vars else ""
        try:
            return int(raw)
        except ValueError:
            return None

    def _on_filter_changed(self) -> None:
        """Pull the widgets into the ONE filter dict, then repaint."""
        self._filter["text"] = self._vars["text"].get() if "text" in self._vars else ""
        self._filter["alliance"] = (self._vars["alliance"].get()
                                    if "alliance" in self._vars else "")
        for key in ("level_min", "level_max", "power_min", "power_max"):
            self._filter[key] = self._number(key)
        rect = [self._number(n) for n in ("x1", "y1", "x2", "y2")]
        self._filter["rect"] = tuple(rect) if all(v is not None for v in rect) else None
        circle = [self._number(n) for n in ("cx", "cy", "cr")]
        self._filter["circle"] = (tuple(circle) if all(v is not None for v in circle)
                                  else None)
        self._filter["noted"] = bool(self._noted.get())
        self._turned()
        self._render()

    def _on_choice(self, key: str, steps, index: int) -> None:
        self._filter[key] = steps[max(index, 0)]
        self._turned()
        self._render()

    def server_steps(self) -> list:
        """«Any», then every server the REGISTER holds — never a list written here.

        Which servers matter is a property of where the laps have been, and the rows
        already say. Both front-ends step through this same list, so the box and the
        phone's button can never offer different servers.
        """
        return [""] + [str(s) for s in self._registry.servers()]

    def _pick_server(self, index: int) -> None:
        steps = self.server_steps()
        self._filter["server"] = steps[max(index, 0)] if index < len(steps) else ""
        self._turned()
        self._render()

    def _reset_filters(self) -> None:
        """Every filter back to «any» — ONE definition, whether the tab is drawn or not.

        The phone can press «Сбросить» on a tab nobody has ever opened, so the state is
        cleared first and the widgets follow only if there are any — `drawn`, never
        `built`: a headless panel realizes this tab and draws none of it (#2074), and
        the flag that used to be asked here was true in exactly that case. It was written the
        other way round once, with the undrawn case spelling the defaults out a second
        time, and the two spellings promptly disagreed about what «any server» is.
        """
        self._filter.update(BLANK_FILTER)
        self._turned()
        if not self.drawn:
            return
        for var in self._vars.values():
            var.set("")
        self._noted.set(False)
        self._server_box.current(0)
        self._seen_box.current(0)
        self._render()

    def visible(self, limit: int = MAX_SHOWN) -> list:
        """The rows the filter keeps, sorted, at most `limit` — what BOTH front-ends draw.

        **Narrowed and sorted in the database** (#1398). It used to be
        `apply_filter(book.rows())` and then `sort_rows`, which on the live register
        meant seventeen thousand dicts built, walked and sorted in Python — on the Tk
        thread, for every keystroke in the search box. The filter itself did not change:
        `registry.matches` is still the readable definition of it, and
        `tests/test_players_registry.py` fails the moment it and the SQL disagree.
        """
        return self._registry.search(self._filter, self._sort, limit=limit)

    # -- what the phone's page is made of -----------------------------------
    def _moved(self) -> None:
        """The list holds something else now — let the phone know to come and look.

        Called by everything that changes WHAT a page contains: a merge that wrote
        rows, a filter, a sort, a page turn, a mark, a forgetting. It is a counter and
        not a hash of the page: the point is «different from last time», and a thousand
        rows hashed on every merge would be the cost the fetch is being moved to avoid.
        """
        self._stamp += 1

    def _turned(self, page: int = 0) -> None:
        """Go to `page`, and say the list moved. THE ONE PLACE THE PAGE IS SET.

        A narrowed filter, a new sort or a typed search leave page 200 pointing at rows
        that are not there any more, so every one of them comes through here and lands
        on the first page. Six presses each remembering to do that is five that will
        eventually forget.
        """
        self._page = max(int(page or 0), 0)
        self._moved()

    def _sort_by(self, column: str) -> None:
        if column not in reg.SORT_KEYS:
            return
        down = not self._sort[1] if self._sort and self._sort[0] == column else True
        self._set_sort(column, down)

    def _set_sort(self, column: str, down: bool) -> None:
        """The sort moved — ONE definition of it, on both front-ends (#2119).

        The window presses a heading and the phone steps through :data:`SORT_STEPS`; both
        end here, so the headings' arrows say what the phone's row says and neither can
        drift into meaning something the other does not.
        """
        self._sort = (column, bool(down))
        # A NEW ORDER IS A NEW FIRST PAGE (#2133): page 40 of «по имени» is nobody's
        # page 40 of «по мощи», and landing there shows a thousand strangers.
        self._turned()
        if self.drawn:
            self._label_headings()
            self._render()

    def sort_name(self) -> str:
        """What the sort is called, as a person reads it: «Виден ↓»."""
        column, down = self._sort or reg.DEFAULT_SORT
        return self.t("players.col." + column) + (" \u2193" if down else " \u2191")

    # -- drawing ------------------------------------------------------------
    def _render(self) -> None:
        if not self.drawn or self._tree is None:
            return
        rows = self.visible()
        total = len(self._registry)
        self._shown = min(len(rows), MAX_SHOWN)
        self._hidden = total - self._shown
        # WHO WAS SELECTED SURVIVES THE REPAINT (#1371). The table is rebuilt whole
        # every twenty seconds by the merge, and a `delete` drops the selection with the
        # rows — so a person who picked a player and reached for «Метка» pressed a
        # button that silently did nothing, roughly one time in three. Nothing on screen
        # said why, which is how «метка не ставится» reads from the other side.
        chosen = self._selected()
        self._tree.delete(*self._tree.get_children())
        now = time.time()
        for row in rows[:MAX_SHOWN]:
            self._tree.insert("", "end", iid=str(row.get("uid")),
                              values=self._cells(row, now))
        if chosen and self._tree.exists(chosen):
            self._tree.selection_set(chosen)
            self._tree.focus(chosen)
        self._count.set(self.t("players.counter", shown=self._shown,
                               hidden=max(self._hidden, 0)))
        self._alliance_box.configure(values=[""] + self._registry.alliances())
        steps = self.server_steps()
        self._server_box.configure(
            values=[self.t("players.server.any")] + steps[1:])
        picked = self._filter.get("server") or ""
        self._server_box.current(steps.index(picked) if picked in steps else 0)

    def _cells(self, row: dict, now: float) -> tuple:
        return (row.get("name") or "—",
                row.get("level") if row.get("level") is not None else "—",
                human_power(row.get("power")),
                row.get("alliance_abbr") or "",
                self.coords_of(row),
                row.get("server_id") if row.get("server_id") is not None else "—",
                self.ago(now - float(row.get("last_seen") or 0)),
                self.freshest(row, now),
                self.note_of(row))

    def freshest(self, row: dict, now: float) -> str:
        """Who told us the newest thing about this player, and how long ago (#1371).

        The column answers the question a register of several sources raises the moment
        it has them: «откуда это вообще известно». The whole breakdown, field by field,
        is one press away in «Подробно» — this is the one line of it that fits in a
        table, and the phone says the same line under each name.
        """
        known = reg.provenance_of(row)
        if not known:
            return ""
        _field, _value, who, when = known[0]
        if not who:
            return ""
        name = self.t("players.src." + who)
        return name if not when else "%s · %s" % (name, self.ago(now - when))

    @staticmethod
    def coords_of(row: dict) -> str:
        """The row's tile as the panel's one coordinate token, so a log line links it."""
        import coords as coords_fmt
        if row.get("x") is None or row.get("y") is None:
            return ""
        return coords_fmt.fmt(row["x"], row["y"], row.get("server_id"))

    def note_of(self, row: dict) -> str:
        """This profile's mark, and the game's own note behind it when there is one."""
        mine = (row.get("note") or "").strip()
        theirs = (row.get("remark") or "").strip()
        if mine and theirs:
            return self.t("players.note.both", mine=mine, game=theirs)
        return mine or theirs

    def ago(self, seconds: float) -> str:
        """«12 мин», «3 ч», «5 дн» — how long since the map last confirmed the row."""
        seconds = max(seconds, 0)
        if seconds < 90:
            return self.t("players.ago.now")
        if seconds < 3600:
            return self.t("players.ago.minutes", n=int(seconds // 60))
        if seconds < 24 * 3600:
            return self.t("players.ago.hours", n=int(seconds // 3600))
        return self.t("players.ago.days", n=int(seconds // 86400))

    # -- the two writes, and the two presses that only look --------------------
    def _selected(self) -> str | None:
        if self._tree is None:
            return None
        chosen = self._tree.selection()
        return chosen[0] if chosen else None

    def _needs_row(self) -> str | None:
        """The selected uid, SAYING SO when there is none.

        A press with nothing selected used to return in silence, which is
        indistinguishable from a press that did not work — and that is precisely how
        «метка не ставится» was reported (#1371).
        """
        uid = self._selected()
        if uid is None:
            self.say("players", "players.log.no_row")
        return uid

    def _jump_selected(self) -> None:
        """«Перейти» — the button beside the table, same jump as clicking the cell."""
        uid = self._needs_row()
        if uid is None:
            return
        if not self._jump(self.coords_of(self._registry.get(uid) or {})):
            self.say("players", "players.log.no_coords")

    def details_lines(self, uid) -> list:
        """Every known field of one player as «поле · значение · источник · когда».

        Built once and said twice — the window's dialog and the phone's card are the
        same list (`CLAUDE.md`, both front-ends) — and it is what makes the register
        readable now that half a dozen sources write into it: «мощность» means one thing
        when the game answered about that player an hour ago and another when a banner
        mentioned them last week.
        """
        row = self._registry.get(uid) or {}
        now = time.time()
        out = []
        for field, value, who, when in reg.provenance_of(row):
            if field == "src":
                continue
            shown = human_power(value) if field in ("power", "army_power",
                                                    "march_power") else str(value)
            out.append(self.t("players.details.line",
                              field=self.t("players.field." + field),
                              value=shown,
                              source=self.t("players.src." + who) if who
                              else self.t("players.src.unknown"),
                              ago=self.ago(now - when) if when
                              else self.t("players.src.unknown")))
        return out

    def _show_details(self) -> None:
        uid = self._needs_row()
        if uid is None:
            return
        row = self._registry.get(uid) or {}
        lines = self.details_lines(uid) or [self.t("players.details.empty")]
        messagebox.showinfo(self.t("players.details.title", name=row.get("name") or uid),
                            "\n".join(lines), parent=self.parent)

    def _edit_note(self) -> None:
        uid = self._needs_row()
        if uid is None:
            return
        row = self._registry.get(uid) or {}
        text = simpledialog.askstring(
            self.t("players.note.title"),
            self.t("players.note.prompt", name=row.get("name") or ""),
            initialvalue=row.get("note") or "", parent=self.parent)
        if text is None:
            return
        self.set_note(uid, text)

    def set_note(self, uid, text: str | None) -> bool:
        """Write the person's own mark — the one field no source may touch."""
        ok = self._registry.set_note(uid, text)
        if ok:
            self.say("players", "players.log.noted", uid=uid)
            self._moved()
            self._render()
        return ok

    def _forget(self) -> None:
        uid = self._needs_row()
        if uid is None:
            return
        row = self._registry.get(uid) or {}
        if not messagebox.askyesno(self.t("players.forget.title"),
                                   self.t("players.forget.ask",
                                          name=row.get("name") or uid),
                                   parent=self.parent):
            return
        self.forget(uid)

    def forget(self, uid) -> bool:
        """THE ONE WAY A ROW LEAVES: a person asked (`registry`, `PERSON_ASKED`)."""
        ok = self._registry.forget(uid)
        if ok:
            self.rt.say("players", "players.log.forgotten", uid=uid)
            self._moved()
            self._render()
        return ok

    # -- persistence --------------------------------------------------------
    def config(self) -> dict:
        """The filter and the sort — the register itself has a file of its own."""
        return {"filter": dict(self._filter), "sort": list(self._sort)}

    def apply_config(self, raw: dict) -> None:
        saved = (raw or {}).get("filter")
        if isinstance(saved, dict):
            for key in self._filter:
                if key in saved:
                    self._filter[key] = saved[key]
        # A SAVED FILTER IS NOT TRUSTED, and this is not hypothetical: a profile
        # written by yesterday's build held `server = "any"`, which today means «only
        # the server literally called any» — and the page came up showing «показано 0 ·
        # скрыто 4259» with no way to tell an empty register from a filter nobody could
        # see. A restored value the code cannot mean is the blank one.
        server = str(self._filter.get("server") or "").strip()
        self._filter["server"] = server if server.isdigit() else ""
        if self._filter.get("seen") not in SEEN_STEPS:
            self._filter["seen"] = "any"
        sort = (raw or {}).get("sort")
        if isinstance(sort, (list, tuple)) and len(sort) == 2:
            self._sort = (str(sort[0]), bool(sort[1]))
        # A RESTORED SORT IS A LIST THAT HAS MOVED, and a page number from before the
        # panel restarted means nothing against it.
        self._turned()
        if self.drawn:
            self._filter_to_widgets()
            self._label_headings()
            self._render()

    def _filter_to_widgets(self) -> None:
        """Put a restored filter back onto the boxes, without writing the profile."""
        self._vars["text"].set(self._filter.get("text") or "")
        self._vars["alliance"].set(self._filter.get("alliance") or "")
        for key in ("level_min", "level_max", "power_min", "power_max"):
            value = self._filter.get(key)
            self._vars[key].set("" if value is None else str(value))
        for group, names in ((self._filter.get("rect"), ("x1", "y1", "x2", "y2")),
                             (self._filter.get("circle"), ("cx", "cy", "cr"))):
            for i, name in enumerate(names):
                self._vars[name].set("" if not group else str(group[i]))
        self._noted.set(bool(self._filter.get("noted")))
        steps = self.server_steps()
        chosen = self._filter.get("server") or ""
        self._server_box.current(steps.index(chosen) if chosen in steps else 0)
        self._seen_box.current(SEEN_STEPS.index(self._filter.get("seen", "any")))

    def persist_vars(self) -> list:
        """The filter boxes — and NOTHING at all until the tab has been drawn.

        A tab nobody has opened has no variables to trace (`PanelTab.LAZY`), and the
        container asks every tab for this list whether or not it drew one.
        """
        if not self.drawn:
            return []
        return list(self._vars.values()) + [self._noted]

    # -- the phone's copy ---------------------------------------------------
    def web_view(self) -> dict:
        """ONE CARD: the controls of the grid, standing on the grid itself (#2308).

        The person's words: «Управление гридом с игроками максимально ущербное… Кнопки
        фильтра должны быть небольшие, клик по ним это переключение по
        возрастанию/убыванию соответствующего фильтра, фильтры к гриду перенеси».

        What that is, item by item, and why each was wrong before:

        * **The sort is a row of small buttons over the grid**, one per column, and a
          press flips THAT column between ascending and descending. It was two dropdowns
          (#2133) standing in a card of their own above the list — two controls, four
          taps and a scroll to reach «мощь по убыванию», and neither of them beside the
          rows they order.
        * **The filters moved onto the list card**, behind its own gear, in the ONE
          modal this front-end has (`CLAUDE.md`). They were six cycling presses in that
          same separate card, and a cycle whose next value nobody can see is a control
          people press until it lands.
        * **The server filter is a real one at last** — a dropdown of the warzones the
          register has actually seen, read on a worker and kept (:data:`SERVERS_GOOD_FOR`).

        The head card is gone with them: a card of readings above the grid is what put
        the first player below the fold on a phone, and everything it said is either on
        the grid's own head (how many there are) or behind its gear (what is narrowing
        them).
        """
        now = time.time()
        # CARDS, NOT A TABLE (#2119) — the same card an errand is drawn as
        # (`ui/ErrandCard.tsx`). AND ITS ITEMS ARE NOT HERE (#2133): `paged` says «this
        # card's rows come off `/api/screen/data`, and only when `stamp` moves».
        card = {"title": "players.web.list", "search": True, "layout": "cards",
                "paged": {"kind": "page", "size": WEB_PAGE,
                          "stamp": str(self._stamp)},
                "empty": "players.empty",
                "rows": self._web_filter_rows(),
                # THE FILTERS, ON THE GRID, BEHIND ITS OWN GEAR (#2308).
                "options": self._web_filter_fields(),
                "options_title": "players.filters",
                # …AND THE SORT, AS SMALL BUTTONS DIRECTLY OVER THE ROWS.
                "sorts": self._web_sorts(),
                "actions": [{"id": "page_prev", "label": "players.web.page.prev"},
                            {"id": "page_next", "label": "players.web.page.next"}]}
        return {"cards": [card], "now": now,
                "actions": [{"id": "refresh", "label": "players.refresh"},
                            {"id": "reset", "label": "players.filters.reset"}]}

    def _faces_for(self, rows) -> None:
        """Resolve the faces of the rows on this page — ON THE WORKER, with a budget.

        A face costs a walk of a few thousand md5 sums the first time a uid is asked
        (`tools/lib/player_faces.py`), so a page of a thousand strangers is ten seconds.
        This runs inside :meth:`web_data`, which is already off the Tk thread, and it
        stops after :data:`FACE_BUDGET_SEC`: the cards at the top of the page — the ones
        a person is looking at — get their picture now, and the rest fill in over the
        next few readings because what was found is kept. A player with no picture is
        remembered as having none, so nobody is looked for twice.

        Nothing here asks the GAME anything — the pictures are files the client
        downloaded for itself, and the register's rule stands unbroken.
        """
        from ...runtime import player_card
        until = time.monotonic() + FACE_BUDGET_SEC
        found = False
        for row in rows:
            uid = str(row.get("uid"))
            if uid in self._faces:
                continue
            if time.monotonic() > until:
                break
            try:
                self._faces[uid] = player_card.face_link(uid, head=row.get("head"))
            except Exception:                # noqa: BLE001 — a picture, never the page
                self._faces[uid] = ""
            found = True
        # A FACE THAT ARRIVED IS A REASON TO COME BACK, and the only one: when a page has
        # no strangers left this stops moving and the phone stops fetching.
        if found:
            self._moved()

    def _web_filter_rows(self) -> list:
        """WHAT IS NARROWING THE GRID, in words, on the grid's own card.

        A FILTER AT «ЛЮБОЙ» IS NOT SHOWN (#2119, measured). Seven rows saying «любой
        сервер», «когда угодно», «нет», «—» filled the whole first screen of an iPhone,
        so the first player stood below the fold. A filter that narrows nothing is not a
        reading — it is furniture. What is set appears the moment it is set, which is
        exactly when somebody asks «почему список такой короткий»; where to change it is
        the gear beside the heading.
        """
        # HOW MANY THE FILTER LEFT is NOT here: it needs a COUNT over the filter, and
        # this method runs on the Tk thread every open profile shares. The page, how many
        # there are and how many the filter kept ride the page's own answer instead
        # (:meth:`web_data`), which is on a worker.
        rows = [
            {"label": "players.web.total", "value": str(len(self._registry))},
        ]
        text = (self._filter.get("text") or "").strip()
        if text:
            rows.append({"label": "players.filter.text", "value": text})
        if self._filter.get("level_min") is not None:
            rows.append({"label": "players.filter.level",
                         "value": self._step_value("level_min")})
        if self._filter.get("power_min") is not None:
            rows.append({"label": "players.filter.power",
                         "value": human_power(self._filter.get("power_min"))})
        if self._filter.get("server"):
            rows.append({"label": "players.filter.server",
                         "value": str(self._filter.get("server"))})
        if (self._filter.get("seen") or "any") != "any":
            rows.append({"label": "players.filter.seen",
                         "value": self.t("players.seen." + self._filter["seen"])})
        if self._filter.get("noted"):
            rows.append({"label": "players.filter.noted", "value": self.t("players.on")})
        return rows

    def _step_value(self, key: str) -> str:
        value = self._filter.get(key)
        return "—" if value is None else str(value)

    def web_servers(self) -> list:
        """The warzones the server filter offers — the LAST list a worker read (#2308).

        Never read here: `DISTINCT server_id` over three hundred thousand rows is a
        question for the thread that answers for a page, and this runs on the loop every
        open profile's window shares. A register that has not been paged through yet
        offers whichever server is already picked and «любой», which is the honest
        answer rather than a stall.
        """
        servers = list(self._server_list)
        picked = str(self._filter.get("server") or "")
        if picked and picked not in servers:
            servers.append(picked)
        return servers

    def _read_servers(self) -> None:
        """Refresh :meth:`web_servers` — ON A WORKER, at most once a minute."""
        now = time.monotonic()
        if self._server_list and now - self._server_read < SERVERS_GOOD_FOR:
            return
        try:
            self._server_list = [str(s) for s in self._registry.servers()]
        except Exception:                    # noqa: BLE001 — a dropdown, never the page
            self._server_list = []
        self._server_read = now

    def _web_filter_fields(self) -> list:
        """EVERY FILTER THE WINDOW HAS, as the knobs this front-end already draws.

        `choice` and `switch` are `ui/FieldRow.tsx` — nothing new is written and the
        moved value travels back through the screen's own `set` press. They open behind
        the grid's gear, in the one modal (`CLAUDE.md`), because a form of five controls
        standing open above a list is the list starting below the fold.

        The window keeps its typed boxes: the same state said two ways, which is the
        rule these two front-ends are built on, and a phone has no pair of number boxes
        worth typing into on a bus.
        """
        f = self._filter
        levels = [{"value": "" if v is None else str(v),
                   "text": "—" if v is None else "%d+" % v} for v in LEVEL_STEPS]
        powers = [{"value": "" if v is None else str(v),
                   "text": "—" if v is None else human_power(v) + "+"}
                  for v in POWER_STEPS]
        servers = [{"value": "", "text": self.t("players.server.any")}]
        servers += [{"value": s, "text": s} for s in self.web_servers()]
        return [
            {"key": "f_server", "label": "players.filter.server", "kind": "choice",
             "value": str(f.get("server") or ""), "options": servers},
            {"key": "f_level", "label": "players.filter.level", "kind": "choice",
             "value": "" if f.get("level_min") is None else str(f["level_min"]),
             "options": levels},
            {"key": "f_power", "label": "players.filter.power", "kind": "choice",
             "value": "" if f.get("power_min") is None else str(f["power_min"]),
             "options": powers},
            {"key": "f_seen", "label": "players.filter.seen", "kind": "choice",
             "value": f.get("seen") or "any",
             "options": [{"value": s, "text": self.t("players.seen." + s)}
                         for s in SEEN_STEPS]},
            {"key": "f_noted", "label": "players.filter.noted", "kind": "switch",
             "value": bool(f.get("noted"))},
        ]

    def _web_sorts(self) -> list:
        """THE SORT, AS SMALL BUTTONS OVER THE GRID (#2308).

        One per sortable column, and a press flips THAT column between ascending and
        descending — exactly what clicking a heading does in the window, which is where
        this shape comes from. `dir` is «which way, for the column the list is actually
        sorted by» and empty for all the others, so the row says where it stands without
        anybody pressing anything.

        It replaces the two dropdowns of #2133, which replaced two cycling presses of
        #2119. The dropdowns were right that a control must say where it stands and
        wrong about where they stood: a separate card above the list, four taps from the
        rows they order.
        """
        column, down = self._sort or reg.DEFAULT_SORT
        return [{"key": name, "label": "players.col." + name,
                 "dir": ("desc" if down else "asc") if name == column else ""}
                for name in SORT_STEPS]

    def details_rows(self, uid) -> list:
        """The same lines as :meth:`details_lines`, as label-and-value pairs.

        What the «i» in a card's corner opens (#2308). The window says the list in a
        message box, one sentence a line; a modal has two columns, so the field's NAME
        is a locale key the phone translates and everything else — the value, who said
        it and how long ago — is data.
        """
        row = self._registry.get(uid) or {}
        now = time.time()
        out = []
        for field, value, who, when in reg.provenance_of(row):
            if field == "src":
                continue
            shown = human_power(value) if field in ("power", "army_power",
                                                    "march_power") else str(value)
            out.append({"label": "players.field." + field,
                        "value": self.t("players.details.value", value=shown,
                                        source=self.t("players.src." + who) if who
                                        else self.t("players.src.unknown"),
                                        ago=self.ago(now - when) if when
                                        else self.t("players.src.unknown"))})
        return out

    def web_data(self, kind: str, args: dict) -> "dict | None":
        """ONE PAGE OF THE REGISTER — a thousand cards, off the Tk thread (#2133).

        The person asked for pages of a thousand, and a thousand cards is some six
        hundred kilobytes: far too much to ride the screen's two-and-a-half-second poll,
        which is what `web_data` exists for. So the card in the view carries `paged` and
        no items, and this answers with them when the phone comes to ask.

        **On an HTTP worker thread**, so it touches no widget and no Tk variable — the
        register's own database and the picture cache, both of which are safe there and
        both of which take long enough to be felt on the loop four open profiles share.

        `needle` is what the person typed into the renderer's search box. It narrows the
        WHOLE register here rather than the page already drawn, which is the difference
        between «нет такого игрока» and finding them: a box that searches a thousand of
        three hundred and twenty-six thousand rows answers about the thousand.

        `details` is the second reading, and it is fetched RATHER THAN CARRIED (#2308):
        everything known about one player, with who said it and when, is a dozen lines,
        and a dozen lines times a page of a thousand would double what the fetch above
        costs so that a person could read one of them.
        """
        if kind == "details":
            return self._web_details(str((args or {}).get("uid") or ""))
        if kind != "page":
            return None
        needle = str((args or {}).get("needle") or "").strip()
        # The typed word does not overwrite the saved filter — it narrows on top of what
        # the page already stands at, and stops narrowing when the box is cleared.
        chosen = dict(self._filter, text=needle) if needle else dict(self._filter)
        now = time.time()
        total = self._registry.count(chosen, now=now)
        pages = max(1, -(-total // WEB_PAGE))
        # A PAGE PAST THE END IS THE LAST PAGE, never an empty screen: a filter typed
        # while standing on page 200 leaves the number pointing at nothing, and «пусто»
        # about a register that plainly has rows is the worst answer available.
        page = min(max(self._page, 0), pages - 1)
        rows = self._registry.search(chosen, self._sort, limit=WEB_PAGE,
                                     offset=page * WEB_PAGE, now=now)
        self._faces_for(rows)
        # THE SERVER FILTER'S OWN LIST, read here because here is a worker (#2308).
        self._read_servers()
        items = [self._web_item(row, now) for row in rows]
        # EVERY COORDINATE ON A CARD IS A PLACE TO GO (#1982). The screen route marks
        # its own payload (`panel/web/coordlinks.py`); this one is answered by a
        # different route, so it marks its own — otherwise a player's place would be a
        # link on every list in the panel except the register of players.
        from ...web import coordlinks
        for item in items:
            coordlinks.mark_item(item)
        return {"items": items, "page": page, "pages": pages, "total": total,
                "size": WEB_PAGE}

    def _web_details(self, uid: str) -> dict:
        """WHAT THE «i» OPENS: every field of one player, and what may be done to them.

        The presses live here rather than on the card — the person's words: «Убираем все
        кнопки. Добавляем аккуратный i в правом верхнем углу, которая вызывает модалку с
        подробными данными базы». Four buttons under every card is four buttons times a
        thousand, and none of them is what a person came to the grid to read. They are
        not LOST, which would be a control the window has and the phone has not: they
        stand in the sheet the «i» opens, beside the data they act on.
        """
        row = self._registry.get(uid)
        if row is None:
            return {"error": "unknown"}
        rows = self.details_rows(uid)
        if not rows:
            rows = [{"label": "players.details",
                     "value": self.t("players.details.empty")}]
        from ...web import coordlinks
        for line in rows:
            coordlinks.mark_row(line)
        return {"title": str(row.get("name") or uid), "rows": rows,
                "actions": [
                    {"id": "note", "label": "players.note.edit",
                     "prompt": "players.note.prompt.short",
                     "value": row.get("note") or "", "args": {"uid": uid}},
                    {"id": "goto", "label": "players.goto", "args": {"uid": uid}},
                    {"id": "forget", "label": "players.forget",
                     "args": {"uid": uid}}]}

    def _web_item(self, row: dict, now: float) -> dict:
        """ONE BASE, AS A CARD — a name with its mark, one line of facts, and an «i».

        The person's words (#2308): «Метку выводим у имени, убираем комментарий, откуда
        данные. Убираем все кнопки. Добавляем аккуратный i в правом верхнем углу».

        So: the mark rides the NAME as a badge, because a mark is the reason somebody
        looks a player up; «откуда» is gone from the card and lives in the sheet, where
        it is one line among the dozen it belongs with; and the four presses are gone
        with it. What is left on the card is what a person reads at a glance — who,
        what level, how strong, whose alliance, where, and when they were last seen.
        """
        uid = str(row.get("uid"))
        detail = " · ".join(bit for bit in (
            str(row.get("level")) if row.get("level") is not None else "",
            human_power(row.get("power")) if row.get("power") else "",
            ("[%s]" % row["alliance_abbr"]) if row.get("alliance_abbr") else "",
            self.coords_of(row),
            self.ago(now - float(row.get("last_seen") or 0)),
        ) if bit)
        item = {"text": row.get("name") or uid, "detail": detail,
                # The face the client itself downloaded, as a LINK — the browser fetches
                # each one once. `""` until the worker has looked, and `""` for good when
                # the player uploaded nothing and their built-in avatar is one the sprite
                # table cannot place: then the card draws its words and no picture, which
                # is the honest answer rather than somebody else's art.
                "avatar": self._faces.get(uid) or "",
                # THE «i» IN THE CORNER, and what is behind it is FETCHED rather than
                # carried: `kind` and `args` are what the phone asks `/api/screen/data`
                # for when the sheet is opened, so a page of a thousand pays nothing for
                # the one somebody reads.
                "info": {"kind": "details", "args": {"uid": uid},
                         "title": str(row.get("name") or uid)}}
        note = self.note_of(row)
        if note:
            # AT THE NAME (#2308), not on the line of facts under it.
            item["badge"] = note
        return item

    def web_press(self, action: str, args: dict) -> dict:
        """The window's presses, and nothing the window has not got."""
        args = args or {}
        if action == "refresh":
            return {"ok": self.refresh()}
        if action == "reset":
            self._reset_filters()
            return {"ok": True}
        if action == "sort":
            # A SMALL BUTTON PER COLUMN, and a press flips that column's direction
            # (#2308) — the very thing clicking a heading does in the window, which is
            # why both ends here are `_sort_by`.
            key = str(args.get("key") or "")
            if key not in reg.SORT_KEYS:
                return {"ok": False, "reason": "players.web.no_such_sort"}
            self._sort_by(key)
            return {"ok": True}
        if action == "set":
            # ONE handler for this tab's knobs, which is the contract every screen's
            # `set` press keeps. Since #2308 they are the FILTERS, behind the grid's own
            # gear; the sort left for buttons of its own.
            key = str(args.get("key") or "")
            if key.startswith("f_"):
                return self._set_filter(key[2:], args.get("value"))
            return {"error": "unknown"}
        if action in ("page_prev", "page_next"):
            # THE EDGE IS SAID, never silently ignored: a press that does nothing and
            # answers «готово» is how a person concludes the list is stuck — which is
            # the very report this task began as.
            if action == "page_prev":
                if self._page <= 0:
                    return {"ok": False, "reason": "players.web.page.first"}
                self._turned(self._page - 1)
                return {"ok": True}
            total = self._registry.count(self._filter)
            if (self._page + 1) * WEB_PAGE >= total:
                return {"ok": False, "reason": "players.web.page.last"}
            self._turned(self._page + 1)
            return {"ok": True}
        if action == "note":
            uid = str(args.get("uid") or "")
            # A PRESS THAT CARRIES NO TEXT AT ALL IS NOT «СТЕРЕТЬ» (#1371). The
            # renderer's item buttons used to ignore `prompt` and post the action's own
            # arguments, so every «Метка» from a phone arrived with no `text` key, was
            # read as an empty note, cleared the mark and answered «готово». Live that
            # was 4 259 rows and not one mark on any of them. The renderer is fixed
            # (`panel/web/app/src`); this refuses the shape outright, because the
            # next renderer will be written by somebody who has not read that fix.
            if "text" not in args:
                return {"ok": False, "reason": "players.web.no_text"}
            if not self.set_note(uid, args.get("text")):
                return {"ok": False, "reason": "players.web.no_such_row"}
            return {"ok": True}
        if action == "goto":
            row = self._registry.get(str(args.get("uid") or "")) or {}
            if not self._jump(self.coords_of(row)):
                return {"ok": False, "reason": "players.web.no_coords"}
            return {"ok": True}
        if action == "forget":
            return self._web_forget(str(args.get("uid") or ""))
        return {"error": "unknown"}

    def _set_filter(self, which: str, value) -> dict:
        """Move one filter from the phone's gear — ONE state, both front-ends (#2308).

        The window's boxes are written from the same dict afterwards, so a phone that
        narrows to «35+, сервер 100» leaves the window reading exactly that. A value the
        code cannot mean is refused out loud rather than stored: a filter nobody can see
        and nobody meant is how «показано 0 · скрыто 4259» happened once already.
        """
        text = "" if value is None else str(value)
        if which == "server":
            self._filter["server"] = text if text.isdigit() else ""
        elif which == "seen":
            if text not in SEEN_STEPS:
                return {"ok": False, "reason": "players.web.no_such_filter"}
            self._filter["seen"] = text
        elif which == "noted":
            self._filter["noted"] = value is True or text.lower() in ("1", "true")
        elif which in ("level", "power"):
            steps = LEVEL_STEPS if which == "level" else POWER_STEPS
            key = "level_min" if which == "level" else "power_min"
            if not text:
                self._filter[key] = None
            else:
                try:
                    number = int(text)
                except ValueError:
                    return {"ok": False, "reason": "players.web.no_such_filter"}
                if number not in steps:
                    return {"ok": False, "reason": "players.web.no_such_filter"}
                self._filter[key] = number
        else:
            return {"error": "unknown"}
        self._turned()
        if self.drawn:
            # The window follows: writing a traced variable is what repaints it (`_var`).
            self._filter_to_widgets()
            self._render()
        return {"ok": True}

    def _web_forget(self, uid: str) -> dict:
        """The phone's version of the window's «точно?» — ask once, act on the second.

        A row is given up for one reason and it has to be a DELIBERATE one; a renderer
        with no confirm dialog would otherwise turn a thumb landing badly into a lost
        mark. The arming expires by itself, so a phone put away disarms.
        """
        armed, when = self._armed_forget
        if armed != uid or time.time() - when > FORGET_ARMED_SEC:
            self._armed_forget = (uid, time.time())
            return {"ok": False, "reason": "players.forget.confirm"}
        self._armed_forget = (None, 0.0)
        if not self.forget(uid):
            return {"ok": False, "reason": "players.web.no_such_row"}
        return {"ok": True}


if __name__ == "__main__":
    from ..base import run_tab
    raise SystemExit(run_tab(PlayersTab))
