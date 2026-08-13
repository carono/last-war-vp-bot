"""«Игроки» — the register of everyone this account's laps of the map have seen (#1335).

## What fills it, and what it costs

Nothing of its own. A lap of the map (`actions/scan_map.md`) makes the client fetch
every tile it drives over, the profile's ONE capture decodes those answers already, and
a player's base is simply one of the tile kinds in them — so this page adds no process,
no npcap handle and no game read to a sweep. The second listener inside that capture
(`tools/lib/world_index.py`) keeps what it hears in the profile's `world_map.json`, and
this page merges from there on a slow tick.

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

## Both front-ends

The window has the table, the filters and the two writes. The phone has the same list
under the renderer's own search box, the same filters as cycling presses (one state:
a press moves the very variables the window's boxes are bound to), and the same two
writes — the mark through a prompting action, the forgetting through a press that asks
once and does the deed on the second press within half a minute, which is the phone's
version of the window's confirmation dialog.
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ...widgets import tk_stringvar
from ..base import PanelTab
from . import registry as reg

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

#: …and how many the phone gets, which is smaller again: the whole screen is rebuilt
#: into the DOM on every poll.
MAX_WEB = 60

#: The columns, in order: (id, width, anchor).
COLUMNS = (
    ("name", 150, "w"),
    ("level", 45, "center"),
    ("power", 90, "e"),
    ("alliance", 70, "w"),
    ("coords", 110, "w"),
    ("server", 55, "center"),
    ("seen", 90, "w"),
    ("note", 160, "w"),
)

#: What the «уровень» press steps through on the phone, and what the window's two
#: boxes hold. The same list, so the two front-ends cannot drift into meaning
#: different things by «30+».
LEVEL_STEPS = (None, 20, 25, 30, 35)
#: …and the same for power, in millions.
POWER_STEPS = (None, 1_000_000, 10_000_000, 50_000_000, 100_000_000)
SERVER_STEPS = ("any", "home", "other")
SEEN_STEPS = ("any", "hour", "day", "week", "stale")

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
    #: The register itself needs nothing — it is fed by the capture the «Секретки» tab
    #: already runs, and read off a file. The daemon is asked ONE question, once: which
    #: server is this account's, so «свой / чужой» can mean something.
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
        self._registry = reg.PlayerRegistry(self.rt.profiles.players_json())
        self._sort = reg.DEFAULT_SORT
        self._home_server = None
        self._home_asked = False
        self._shown = 0
        self._hidden = 0
        self._merging = False
        self._armed_forget = (None, 0.0)
        # The filter, as ONE dict the window's variables write into and the phone's
        # presses move. Two front-ends, one state (`docs/panel-tabs.md`).
        self._filter = {"text": "", "level_min": None, "level_max": None,
                        "power_min": None, "power_max": None, "alliance": "",
                        "server": "any", "rect": None, "circle": None,
                        "seen": "any", "noted": False}
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
        self._server_box = ttk.Combobox(line, width=10, state="readonly",
                                        values=[self.t("players.server." + s)
                                                for s in SERVER_STEPS])
        self._server_box.current(0)
        self._server_box.bind("<<ComboboxSelected>>",
                              lambda _e: self._on_choice("server", SERVER_STEPS,
                                                         self._server_box.current()))
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

        self._noted = tk.BooleanVar(master=self.rt.root, value=False)
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
        self._tree = tree
        self._label_headings()

    def _build_footer(self, root) -> None:
        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=(6, 0))
        self._count = tk_stringvar(self.rt.root)
        ttk.Label(bar, textvariable=self._count).pack(side="left")
        self.tr(ttk.Button(bar, command=self._forget), "players.forget").pack(
            side="right")
        self.tr(ttk.Button(bar, command=self._edit_note), "players.note.edit").pack(
            side="right", padx=(0, 6))

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
        self._merge_async()
        if not self._home_asked:
            self._home_asked = True
            threading.Thread(target=self._read_home_server, daemon=True).start()

    def on_language_change(self) -> None:
        self._label_headings()
        if self._tree is not None:
            self._server_box.configure(values=[self.t("players.server." + s)
                                               for s in SERVER_STEPS])
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
    def _read_home_server(self) -> None:
        """Which server is THIS account's — the one question the register cannot answer.

        Off the Tk thread, once, and only if the client is up: «свой / чужой сервер» is
        a filter and not a reason to wake a daemon. When the game will not say, the
        clause simply cannot be applied (`registry.matches`), which is the honest
        answer rather than a guess that quietly hides half the map.
        """
        try:
            if not self.rt.game.up():
                return
            server = self.rt.game.current_server()
        except Exception:                                   # noqa: BLE001
            return
        if str(server).isdigit():
            self.post(lambda: self._set_home(int(server)))

    def _set_home(self, server: int) -> None:
        self._home_server = server
        self._render()

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
                    added = self._registry.absorb(rows)
        except Exception as exc:                            # noqa: BLE001
            self.rt.say("players", "players.log.merge_failed", error=exc)
        finally:
            self._merging = False
        if added:
            self.rt.say("players", "players.log.merged", added=added,
                        total=len(self._registry))
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
        self._render()

    def _on_choice(self, key: str, steps, index: int) -> None:
        self._filter[key] = steps[max(index, 0)]
        self._render()

    def _reset_filters(self) -> None:
        for var in self._vars.values():
            var.set("")
        self._noted.set(False)
        self._filter.update({"server": "any", "seen": "any", "rect": None,
                             "circle": None})
        if self._tree is not None:
            self._server_box.current(0)
            self._seen_box.current(0)
        self._render()

    def visible(self) -> list:
        """The rows the filter keeps, sorted — what BOTH front-ends draw from."""
        rows = reg.apply_filter(self._registry.rows(), self._filter,
                                home_server=self._home_server)
        return reg.sort_rows(rows, self._sort)

    def _sort_by(self, column: str) -> None:
        if column not in reg.SORT_KEYS:
            return
        down = not self._sort[1] if self._sort and self._sort[0] == column else True
        self._sort = (column, down)
        self._label_headings()
        self._render()

    # -- drawing ------------------------------------------------------------
    def _render(self) -> None:
        if not self.built or self._tree is None:
            return
        rows = self.visible()
        total = len(self._registry)
        self._shown = min(len(rows), MAX_SHOWN)
        self._hidden = total - self._shown
        self._tree.delete(*self._tree.get_children())
        now = time.time()
        for row in rows[:MAX_SHOWN]:
            self._tree.insert("", "end", iid=str(row.get("uid")),
                              values=self._cells(row, now))
        self._count.set(self.t("players.counter", shown=self._shown,
                               hidden=max(self._hidden, 0)))
        tags = self._registry.alliances()
        self._alliance_box.configure(values=[""] + tags)

    def _cells(self, row: dict, now: float) -> tuple:
        return (row.get("name") or "—",
                row.get("level") if row.get("level") is not None else "—",
                human_power(row.get("power")),
                row.get("alliance_abbr") or "",
                self.coords_of(row),
                row.get("server_id") if row.get("server_id") is not None else "—",
                self.ago(now - float(row.get("last_seen") or 0)),
                self.note_of(row))

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

    # -- the two writes -----------------------------------------------------
    def _selected(self) -> str | None:
        if self._tree is None:
            return None
        chosen = self._tree.selection()
        return chosen[0] if chosen else None

    def _edit_note(self) -> None:
        uid = self._selected()
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
        """Write the person's own mark — the one field no lap of the map may touch."""
        ok = self._registry.set_note(uid, text)
        if ok:
            self._render()
        return ok

    def _forget(self) -> None:
        uid = self._selected()
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
        sort = (raw or {}).get("sort")
        if isinstance(sort, (list, tuple)) and len(sort) == 2:
            self._sort = (str(sort[0]), bool(sort[1]))
        if self.built:
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
        self._server_box.current(SERVER_STEPS.index(self._filter.get("server", "any")))
        self._seen_box.current(SEEN_STEPS.index(self._filter.get("seen", "any")))

    def persist_vars(self) -> list:
        """The filter boxes — and NOTHING at all until the tab has been drawn.

        A tab nobody has opened has no variables to trace (`PanelTab.LAZY`), and the
        container asks every tab for this list whether or not it drew one.
        """
        if not self.built:
            return []
        return list(self._vars.values()) + [self._noted]

    # -- the phone's copy ---------------------------------------------------
    def web_view(self) -> dict:
        """The same register, the same filter, the same two writes.

        `search: true` hands the card to the renderer's own text box, which is the
        phone's version of «Поиск» — it filters the ITEMS already drawn, so this view
        stays cheap however hard somebody types.

        The filters are presses that STEP through the same lists the window's boxes
        hold, and they move the very same `self._filter`: one state, two views
        (`docs/panel-tabs.md`). A phone that narrows to «35, свой сервер» leaves the
        window's boxes reading exactly that.
        """
        rows = self.visible()
        shown = rows[:MAX_WEB]
        now = time.time()
        items = [self._web_item(row, now) for row in shown]
        head = {"title": "tab.players",
                "rows": self._web_filter_rows(len(shown)),
                "actions": self._web_filter_actions()}
        card = {"title": "players.web.list", "search": True, "items": items,
                "empty": "players.empty"}
        return {"cards": [head, card], "now": now,
                "actions": [{"id": "refresh", "label": "players.refresh"},
                            {"id": "reset", "label": "players.filters.reset"}]}

    def _web_filter_rows(self, on_screen: int) -> list:
        """WHERE EACH FILTER STANDS, in words, above the buttons that step it.

        The renderer says a button's label with no arguments, so a cycling button
        cannot spell its own value — and a cycle whose current value is invisible is a
        control nobody can use. So the state is read off these rows and the buttons only
        move it, which is also how the window reads: boxes above, «Сбросить» beside.
        """
        return [
            {"label": "players.web.total", "value": str(len(self._registry))},
            {"label": "players.web.shown",
             "value": self.t("players.counter", shown=on_screen,
                             hidden=max(len(self._registry) - on_screen, 0))},
            {"label": "players.filter.level", "value": self._step_value("level_min")},
            {"label": "players.filter.power",
             "value": human_power(self._filter.get("power_min"))},
            {"label": "players.filter.server",
             "value": self.t("players.server." + (self._filter.get("server") or "any"))},
            {"label": "players.filter.seen",
             "value": self.t("players.seen." + (self._filter.get("seen") or "any"))},
            {"label": "players.filter.noted",
             "value": self.t("players.on" if self._filter.get("noted")
                             else "players.off")},
        ]

    def _step_value(self, key: str) -> str:
        value = self._filter.get(key)
        return "—" if value is None else str(value)

    def _web_filter_actions(self) -> list:
        """Every filter the window has, as a press that steps to the next value.

        A phone has no pair of number boxes worth typing into on a bus, so the ranges
        are offered as the steps people actually pick — and the window keeps the boxes,
        which is the same state said two ways rather than two states. Where it stands
        is on the rows above (`_web_filter_rows`).
        """
        return [
            {"id": "level", "label": "players.web.level"},
            {"id": "power", "label": "players.web.power"},
            {"id": "server", "label": "players.web.server"},
            {"id": "seen", "label": "players.web.seen"},
            {"id": "noted", "label": "players.web.noted"},
        ]

    def _web_item(self, row: dict, now: float) -> dict:
        uid = str(row.get("uid"))
        detail = " · ".join(bit for bit in (
            str(row.get("level")) if row.get("level") is not None else "",
            human_power(row.get("power")) if row.get("power") else "",
            ("[%s]" % row["alliance_abbr"]) if row.get("alliance_abbr") else "",
            self.coords_of(row),
            self.ago(now - float(row.get("last_seen") or 0)),
        ) if bit)
        item = {"text": row.get("name") or uid, "detail": detail,
                "actions": [
                    {"id": "note", "label": "players.note.edit",
                     "prompt": "players.note.prompt.short",
                     "value": row.get("note") or "", "args": {"uid": uid}},
                    {"id": "forget", "label": "players.forget",
                     "args": {"uid": uid}}]}
        note = self.note_of(row)
        if note:
            item["note"] = note
        return item

    def web_press(self, action: str, args: dict) -> dict:
        """The window's presses, and nothing the window has not got."""
        args = args or {}
        if action == "refresh":
            return {"ok": self.refresh()}
        if action == "reset":
            self._reset_filters() if self.built else self._filter.update(
                {"text": "", "level_min": None, "level_max": None,
                 "power_min": None, "power_max": None, "alliance": "",
                 "server": "any", "rect": None, "circle": None, "seen": "any",
                 "noted": False})
            return {"ok": True}
        if action in ("level", "power", "server", "seen", "noted"):
            return {"ok": self._step_filter(action)}
        if action == "note":
            uid = str(args.get("uid") or "")
            if not self.set_note(uid, args.get("text")):
                return {"ok": False, "reason": "players.web.no_such_row"}
            return {"ok": True}
        if action == "forget":
            return self._web_forget(str(args.get("uid") or ""))
        return {"error": "unknown"}

    def _step_filter(self, which: str) -> bool:
        """Move one filter to its next value, on both front-ends at once."""
        if which == "noted":
            self._filter["noted"] = not self._filter["noted"]
            if self.built:
                # Writing the variable is what redraws: it is traced (`_var`).
                self._noted.set(self._filter["noted"])
            return True
        if which in ("server", "seen"):
            steps = SERVER_STEPS if which == "server" else SEEN_STEPS
            index = (steps.index(self._filter.get(which, "any")) + 1) % len(steps)
            self._filter[which] = steps[index]
            if self.built:
                box = self._server_box if which == "server" else self._seen_box
                box.current(index)
                self._render()
            return True
        steps = LEVEL_STEPS if which == "level" else POWER_STEPS
        key = "level_min" if which == "level" else "power_min"
        current = self._filter.get(key)
        # A number typed into the window's box that is on no step — 27, say — steps to
        # the first real one rather than raising: the two front-ends offer different
        # granularities of the same filter on purpose.
        index = (steps.index(current) + 1) % len(steps) if current in steps else 1
        self._filter[key] = steps[index]
        if self.built:
            self._vars[key].set("" if steps[index] is None else str(steps[index]))
        return True

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
