"""The «Инвентарь» tab: the bag drawn the way the game draws it, searchable.

WHAT IT READS. `actions/read_inventory.md` — the panel assembles no Lua of its own. The
list is `DataCenter.ItemData.ItemInfos`, one entry per stack, summed by item id so a cell
is a cell exactly as in the game's own bag. It is not a push: `push.resource.item.update`
only says the numbers moved, and the tab answers it by re-reading (`TRIGGERS`).

WHAT IT DRAWS. Two sprites per cell, the game's own — the item's picture over the frame
its rarity picks (`tools/lib/item_icons.py`, extracted by `tools/extract_item_icons.py`).
A machine that has never run the extraction shows a glyph instead and loses nothing else.

WHAT IT KEEPS. The last reading and the descriptions live in the profile's database
(`rt.store`, the shared `blobs` table): the bag is game data, so `CLAUDE.md` says a table
and not a file, and it is read and written WHOLE, so a named blob and not a table of its
own. Keeping it is what lets the tab open full on a panel whose client is not running —
and what lets a description be asked for once per item instead of 58 KB per refresh.
"""
from __future__ import annotations

import os
from tkinter import ttk

from ..widgets import ScrollableFrame, font as ui_font
from .base import TriggerSpec
from ._data import DataTab, _group, _stringvar

#: What one reading is filed under in the profile's database, and what the descriptions
#: are filed under beside it. Two blobs and not one: the list changes whenever the game
#: says a balance moved, the descriptions never change at all.
BAG_BLOB = "inventory_state"
DESC_BLOB = "inventory_descs"

#: THE BAG'S OWN TABS (#1702) — the set and the order are the client's own `UIBagTab`
#: (`Special = 1, Resource = 2, SpeedUp = 3, Hero = 4, Equip = 5, Gift = 6`); which item
#: falls into which is answered by the READING (`read_inventory.md`), not decided here.
#: «Все» is the panel's own and comes first, because a bag of four hundred rows is most
#: often searched rather than browsed.
BAG_TAB_SPECIAL = 1
BAG_TABS = ((0, "inventory.tab.all"),
            (1, "inventory.tab.special"),
            (2, "inventory.tab.resource"),
            (3, "inventory.tab.speedup"),
            (4, "inventory.tab.hero"),
            (5, "inventory.tab.equip"),
            (6, "inventory.tab.gift"))

#: How many ids one description read asks for. The whole set is ~58 KB of text and the
#: first run of a fresh profile asks for all of it, so it goes in slices — a Lua answer
#: is one line through the daemon and a line has a size somebody eventually finds.
DESC_CHUNK = 60


def parse_items(text: str) -> list:
    """`read_inventory.md`'s one variable into records. Unreadable input is no items.

    The scenario's own format: records separated by « #|# », six fields separated by
    « ;; » with the NAME last, so a name containing the separator costs nothing.
    """
    out = []
    for record in str(text or "").split(" #|# "):
        record = record.strip()
        if not record:
            continue
        fields = record.split(";;", 7)
        if len(fields) < 6:
            continue
        # A reading saved by an older panel is shorter (#1702): six fields is one from
        # before «usable», seven is one from before the bag's own tab. Both keep working —
        # no button, everything in the first tab — until the next refresh.
        if len(fields) == 6:
            fields = fields[:5] + ["0", str(BAG_TAB_SPECIAL)] + fields[5:]
        elif len(fields) == 7:
            fields = fields[:6] + [str(BAG_TAB_SPECIAL)] + fields[6:]
        try:
            item_id = int(fields[0])
        except ValueError:
            continue
        out.append({"id": item_id,
                    "count": _int_or(fields[1]),
                    "colour": _int_or(fields[2]),
                    "type": _int_or(fields[3]),
                    "usable": _int_or(fields[5]) == 1,
                    "tab": _int_or(fields[6], BAG_TAB_SPECIAL) or BAG_TAB_SPECIAL,
                    "icon": fields[4],
                    "name": fields[7] or f"#{item_id}"})
    return out


def parse_descs(text: str) -> dict:
    """`read_inventory_desc.md`'s answer into ``{id: description}``."""
    out = {}
    for record in str(text or "").split(" #|# "):
        record = record.strip()
        if not record:
            continue
        head, sep, tail = record.partition(";;")
        if not sep:
            continue
        try:
            out[str(int(head))] = tail
        except ValueError:
            continue
    return out


def _int_or(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def cell_url(icon: str, colour) -> "str | None":
    """One cell as the phone asks for it: ``/api/itemicon?cell=<file name>``.

    A LINK and never bytes, for the reason `roster.face_url` is one: `web_view` runs on
    every poll, and a bag of several hundred pictures inside the view would be megabytes
    a minute. The picture is composed here (once, cached on disk) and the browser
    fetches each one exactly once.
    """
    import urllib.parse as _url

    try:
        import item_icons
    except Exception:                       # noqa: BLE001 — no extraction is a glyph
        return None
    path = item_icons.cell(icon, colour)
    if not path:
        return None
    return "/api/itemicon?cell=" + _url.quote(os.path.basename(path))


class InventoryTab(DataTab):
    """The bag: a grid of the game's own cells, a search box, and one item in detail."""

    #: The bag changes without anybody pressing anything, so the tab offers the
    #: standing order that keeps it live — and it is only offered while the tab is
    #: here to be repainted (§3.2).
    TRIGGERS = (TriggerSpec(name="inventory_refresh",
                            event="push.resource.item.update", handler="refresh_live"),)

    ID = "inventory"
    TITLE_KEY = "tab.inventory"
    ORDER = 220
    LOCALE_NS = ('inventory', 'tabx')

    #: Cells per row, and how wide one is drawn. The game's plate is 162×170, so a cell
    #: is a little taller than it is wide and the count sits under the picture.
    COLUMNS = 8
    CELL_PX = 56

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._items: list = []
        self._descs: dict = {}
        #: Ids the game answered nothing for, this session only — see `_fetch_descs`.
        self._no_desc: set = set()
        self._images: dict = {}
        self._selected = None
        self._loaded_store = False
        self._redraw_after = None

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Draw what the database already holds BEFORE reading the game.

        A bag read costs a round trip and a running client; the last one costs neither,
        and a tab that opens full and then refreshes is the difference between «пусто»
        and «вот твой инвентарь» on a panel whose client is still starting.
        """
        if not self._loaded_store:
            self._loaded_store = True
            saved = self._blob(BAG_BLOB)
            self._descs = {k: v for k, v in (self._blob(DESC_BLOB) or {}).items() if v}
            if isinstance(saved, list) and saved:
                self._last_data = saved
                self.render(saved)
        super().ensure_loaded()

    def build(self) -> None:
        top = ttk.Frame(self.parent)
        top.pack(fill="x", padx=10, pady=(10, 4))
        self.rt.tr(ttk.Label(top, font=ui_font(size=15, weight="bold")),
                   "tab.inventory").pack(side="left")
        self.rt.tr(ttk.Button(top, width=12, command=self.refresh),
                   "tabx.refresh").pack(side="right")
        self._status_var = _stringvar(self.rt)
        ttk.Label(top, textvariable=self._status_var, foreground="#888").pack(
            side="right", padx=8)

        # THE BAG'S OWN TABS (#1702), in the game's own order. Radio buttons rather than a
        # notebook: they cost one widget each against a page each, and the grid below is
        # already the thing that repaints.
        tabrow = ttk.Frame(self.parent)
        tabrow.pack(fill="x", padx=10, pady=(0, 4))
        self._tab_var = _stringvar(self.rt)
        self._tab_var.set("0")
        for number, key in BAG_TABS:
            self.rt.tr(ttk.Radiobutton(tabrow, value=str(number),
                                       variable=self._tab_var,
                                       command=self._redraw_soon), key).pack(side="left")

        searchrow = ttk.Frame(self.parent)
        searchrow.pack(fill="x", padx=10, pady=(0, 6))
        self.rt.tr(ttk.Label(searchrow), "inventory.search").pack(side="left")
        self._query = _stringvar(self.rt)
        self._query.trace_add("write", lambda *_: self._redraw_soon())
        ttk.Entry(searchrow, textvariable=self._query).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        # The detail line: what the picture cannot say. It is filled by clicking a cell
        # and holds the same three things the phone's row does — name, count, text.
        detail = ttk.Frame(self.parent)
        detail.pack(fill="x", padx=10, pady=(0, 4))
        self._detail_name = _stringvar(self.rt)
        self._detail_text = _stringvar(self.rt)
        ttk.Label(detail, textvariable=self._detail_name,
                  font=ui_font(weight="bold")).pack(side="left")
        ttk.Label(detail, textvariable=self._detail_text, foreground="#888",
                  wraplength=520, justify="left").pack(side="left", padx=(10, 0))

        # THE USE ROW (#1702). The bag's own button, for the item the grid has selected:
        # how many, and «Использовать». It is disabled until something usable is picked,
        # because a button that answers «этот предмет не используется» after the press is
        # a button that looked like it would work.
        userow = ttk.Frame(self.parent)
        userow.pack(fill="x", padx=10, pady=(0, 6))
        self._use_label = self.rt.tr(ttk.Label(userow), "inventory.use.count")
        self._use_label.pack(side="left")
        self._use_count = _stringvar(self.rt)
        self._use_count.set("1")
        self._use_spin = ttk.Spinbox(userow, from_=1, to=1, width=8,
                                     textvariable=self._use_count)
        self._use_spin.pack(side="left", padx=(6, 8))
        self._use_button = self.rt.tr(
            ttk.Button(userow, width=16, command=self._use_selected), "inventory.use")
        self._use_button.pack(side="left")
        self._use_button.state(["disabled"])
        self._use_spin.state(["disabled"])

        self._scroll = ScrollableFrame(self.parent)
        self._scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.rt.tr(ttk.Label(self._scroll, foreground="#888"),
                   "inventory.empty").grid(row=0, column=0, sticky="w", pady=6)

    # -- the reading --------------------------------------------------------
    def fetch(self):
        """Play `read_inventory.md`, then ask for the descriptions still unknown.

        Runs on `DataTab`'s background thread, so both plays are ordinary blocking
        calls into `rt.actions` — the same way «Секретные задачи» reads its monsters.
        """
        if not self._game_ready():
            return self._last_data if isinstance(self._last_data, list) else []
        items = parse_items(self._play("read_inventory", "items"))
        if not items:
            return self._last_data if isinstance(self._last_data, list) else []
        self._fetch_descs([it["id"] for it in items])
        self._save(BAG_BLOB, items)
        return items

    def _game_ready(self) -> bool:
        try:
            return bool(self.rt.game.ready())
        except Exception:                   # noqa: BLE001 — no game is an old reading
            return False

    def _play(self, name: str, variable: str, args: "dict | None" = None) -> "str | None":
        """Play a read scenario and hand back the one variable it filled.

        ``None`` means the read did not happen — no daemon, a refusal, an exception —
        as against ``""``, which is the game answering «nothing». The caller must not
        confuse the two: writing a failed read into the cache would remember «this item
        has no description» for as long as the profile lives.
        """
        try:
            outcome = self.rt.actions.play(name, args or {}, human=True,
                                           on_event=lambda _m: None)
        except Exception:                   # noqa: BLE001 — a read, never the window
            return None
        ctx = getattr(outcome, "ctx", None)
        raw = (getattr(ctx, "vars", {}) or {}).get(variable)
        return raw if (getattr(outcome, "ok", False) and isinstance(raw, str)) else None

    def _fetch_descs(self, ids) -> None:
        """Ask for the description of every id this profile has not seen before.

        Slice by slice, and a slice that did not come back is left UNASKED rather than
        written down as «no description» — otherwise one failed read silently blanks
        those items for the life of the profile.
        """
        wanted = [str(i) for i in ids
                  if str(i) not in self._descs and str(i) not in self._no_desc]
        if not wanted:
            return
        learned = False
        for start in range(0, len(wanted), DESC_CHUNK):
            slice_ = wanted[start:start + DESC_CHUNK]
            answer = self._play("read_inventory_desc", "descs",
                                {"ids": ",".join(slice_)})
            if answer is None:
                continue
            found = parse_descs(answer)
            # ONLY THE TEXT IS KEPT ON DISK. An id the client answered nothing for is
            # remembered for this session and no longer, because «empty» is the answer a
            # read that half-failed also gives — and one of those, written down, would
            # blank those items for the life of the profile. Six items out of four
            # hundred genuinely have no description, so the re-ask costs one slice at
            # the next start-up and buys back every profile that cached a bad run.
            self._descs.update({k: v for k, v in found.items() if v})
            self._no_desc.update(one for one in slice_ if not found.get(one))
            learned = True
        if learned:
            self._save(DESC_BLOB, self._descs)

    # -- the profile's database ---------------------------------------------
    def _blob(self, name: str):
        try:
            store = self.rt.store
        except Exception:                   # noqa: BLE001 — a tab opened on its own
            return None
        if store is None:
            return None
        try:
            return store.blob_get(name)
        except Exception:                   # noqa: BLE001
            return None

    def _save(self, name: str, value) -> None:
        try:
            store = self.rt.store
            if store is not None:
                store.blob_set(name, value)
        except Exception:                   # noqa: BLE001 — a cache, never the reading
            pass

    # -- the window ---------------------------------------------------------
    def render(self, items) -> None:
        self._items = items or []
        if not self._items:
            self._status_var.set(self.rt.t("tabx.no_game"))
        elif self._icons_ready():
            self._status_var.set(self.rt.t("inventory.count", n=len(self._items)))
        else:
            # The list is real and the pictures are not there — a machine that has
            # never run the extraction. Say which of the two it is, or the glyphs read
            # as «the bag failed» (`tools/extract_item_icons.py`).
            self._status_var.set(self.rt.t("inventory.no_icons"))
        self._redraw()

    @staticmethod
    def _icons_ready() -> bool:
        try:
            import item_icons
            return bool(item_icons.available())
        except Exception:                   # noqa: BLE001
            return False

    def _redraw_soon(self) -> None:
        """Repaint a quarter of a second after the LAST keystroke, not after each one.

        A grid of several hundred cells is a couple of thousand widgets destroyed and
        made again, and Tk work from this thread is what every open profile queues
        behind (docs/research/panel-freezes.md). Typing five letters should cost one
        repaint, not five.
        """
        pending = getattr(self, "_redraw_after", None)
        if pending is not None:
            try:
                self.parent.after_cancel(pending)
            except Exception:               # noqa: BLE001 — an id Tk has already run
                pass
        self._redraw_after = self.parent.after(250, self._redraw)

    def _redraw(self) -> None:
        self._redraw_after = None
        scroll = getattr(self, "_scroll", None)
        if scroll is None:
            return
        for child in scroll.winfo_children():
            child.destroy()
        query = (self._query.get() or "").strip().lower()
        shown = [it for it in self._items
                 if (not query or query in str(it.get("name", "")).lower())
                 and self._in_tab(it)]
        if not shown:
            self.rt.tr(ttk.Label(scroll, foreground="#888"),
                       "inventory.empty").grid(row=0, column=0, sticky="w", pady=6)
            return
        for index, item in enumerate(shown):
            self._draw_cell(scroll, item, index // self.COLUMNS, index % self.COLUMNS)

    def _in_tab(self, item) -> bool:
        """Is this item in the category the window is showing? «Все» (0) is everything."""
        try:
            wanted = int(self._tab_var.get() or 0)
        except Exception:                   # noqa: BLE001 — the window is going away
            return True
        return wanted == 0 or int(item.get("tab") or BAG_TAB_SPECIAL) == wanted

    def _draw_cell(self, parent, item, row: int, column: int) -> None:
        """One cell: the game's two sprites, the count under them, the name as a hint."""
        cell = ttk.Frame(parent)
        cell.grid(row=row, column=column, padx=3, pady=3, sticky="n")
        image = self._cell_image(item)
        if image is not None:
            face = ttk.Label(cell, image=image)
        else:
            face = ttk.Label(cell, text="📦", font=ui_font(size=20))
        face.pack()
        ttk.Label(cell, text=self._short(item.get("count")),
                  font=ui_font(size=8)).pack()
        name = ttk.Label(cell, text=self._clip(item.get("name")),
                         font=ui_font(size=8), foreground="#888",
                         wraplength=self.CELL_PX + 8, justify="center")
        name.pack()
        for widget in (cell, face, name):
            widget.bind("<Button-1>", lambda _e, it=item: self._select(it))

    def _select(self, item) -> None:
        self._selected = item
        self._detail_name.set(
            f"{item.get('name', '')} ×{_group(item.get('count'))}")
        self._detail_text.set(self._descs.get(str(item.get("id")), ""))
        self._arm_use(item)

    def _arm_use(self, item) -> None:
        """Point the use row at ``item`` — or grey it out when it cannot be used."""
        if getattr(self, "_use_button", None) is None:
            return
        have = max(0, int(item.get("count") or 0))
        usable = bool(item.get("usable")) and have > 0
        state = "!disabled" if usable else "disabled"
        self._use_button.state([state])
        self._use_spin.state([state])
        if usable:
            # The count is capped by what is in the bag: a spinbox that offers to use a
            # hundred of something there are three of is a promise the game will refuse.
            self._use_spin.configure(from_=1, to=have)
            self._use_count.set("1")

    def _use_selected(self) -> None:
        """Play `use_item.md` for the selected cell, then re-read the bag.

        The panel decides nothing about what the press MEANS: which item, how many, and
        whether the kind can be used at all are the scenario's business (`CLAUDE.md`).
        """
        item = self._selected or {}
        item_id = int(item.get("id") or 0)
        have = max(0, int(item.get("count") or 0))
        try:
            count = int(str(self._use_count.get() or "1").strip() or 1)
        except ValueError:
            count = 1
        count = max(1, min(count, have))
        if item_id <= 0 or not item.get("usable") or count <= 0:
            return
        self._use_button.state(["disabled"])
        self.rt.play_async("use_item", {"item": item_id, "count": count},
                           tag="inventory", human=True, on_result=self._used,
                           on_done=lambda: self._arm_use(self._selected or {}))

    def _used(self, outcome) -> None:
        """Say what the run reported, in its own words, and re-read the bag."""
        ctx = getattr(outcome, "ctx", None)
        report = str((getattr(ctx, "vars", {}) or {}).get("use_report") or "")
        if getattr(outcome, "ok", False):
            self.say("inventory", "inventory.use.done", report=report)
        else:
            reason = str(getattr(outcome, "reason", "") or report or "?")
            self.say("inventory", "inventory.use.failed", error=reason)
        self.refresh()

    def _cell_image(self, item):
        """A cached Tk image of the composed cell, or ``None`` (no extraction, no PIL).

        The cache also keeps the image alive — Tk holds no Python reference — and it is
        keyed by what the picture IS, so the same shard frame is composed once however
        many times the search box repaints it.
        """
        key = (item.get("icon"), item.get("colour"))
        if key in self._images:
            return self._images[key]
        image = None
        try:
            import item_icons
            path = item_icons.cell(item.get("icon"), item.get("colour"), self.CELL_PX)
            if path:
                from PIL import Image, ImageTk
                image = ImageTk.PhotoImage(Image.open(path).convert("RGBA"))
        except Exception:                   # noqa: BLE001 — a missing picture is a glyph
            image = None
        self._images[key] = image
        return image

    @staticmethod
    def _short(count) -> str:
        """The count as the game prints it on a cell: 999, 12.3K, 4.5M."""
        try:
            number = int(count)
        except (TypeError, ValueError):
            return str(count or "")
        if number >= 1_000_000:
            return f"{number / 1_000_000:.1f}M"
        if number >= 10_000:
            return f"{number / 1000:.1f}K"
        return str(number)

    @staticmethod
    def _clip(name, limit: int = 22) -> str:
        text = str(name or "")
        return text if len(text) <= limit else text[:limit - 1] + "…"

    # -- the phone ----------------------------------------------------------
    def web_cards(self, items) -> list:
        """The bag, one row per cell — the same picture the window draws.

        A LIST and not a grid because the phone has one renderer and every screen is
        made of the same rows; what matters for «the two front-ends say the same thing»
        is that the row carries the same composed cell, the same count and the same
        description the window shows when you click one.
        """
        rows = []
        descs = getattr(self, "_descs", None) or {}
        for item in items or ():
            row = {"text": str(item.get("name") or ""),
                   "detail": "×" + _group(item.get("count")),
                   "note": descs.get(str(item.get("id")), "")}
            picture = cell_url(item.get("icon"), item.get("colour"))
            if picture:
                row["icon"] = picture
            # THE SAME BUTTON THE WINDOW HAS (#1702), and the same choice of how many.
            # The window offers a spinbox and the phone three quick amounts, because one
            # thumb on a list of two hundred rows is not a numeric field — the ABILITY is
            # the same one and the press plays the same scenario with the same argument.
            have = max(0, int(item.get("count") or 0))
            if item.get("usable") and have > 0:
                row["actions"] = [
                    {"id": "use", "label": "inventory.use.one",
                     "args": {"item": item.get("id"), "count": 1}},
                ]
                if have >= 10:
                    row["actions"].append(
                        {"id": "use", "label": "inventory.use.ten",
                         "args": {"item": item.get("id"), "count": 10}})
                row["actions"].append(
                    {"id": "use", "label": "inventory.use.all",
                     "args": {"item": item.get("id"), "count": have}})
            rows.append(row)
        # THE SAME TABS THE WINDOW HAS, drawn the way a thumb can hit them: one CARD per
        # category (#1702). The phone's renderer draws a card as a titled block, so the
        # bag arrives already divided and scrolling to «Ускорения» is a flick rather than
        # a hunt for a four-pixel tab. Empty categories are left out entirely — a heading
        # over nothing is a row of noise on a screen that has none to spare.
        by_tab: dict = {}
        for row, item in zip(rows, items or ()):
            by_tab.setdefault(int(item.get("tab") or BAG_TAB_SPECIAL), []).append(row)
        cards = []
        for number, key in BAG_TABS:
            if number == 0:
                continue
            here = by_tab.get(number) or []
            if here:
                cards.append({"title": key, "items": here, "search": True,
                              "empty": "inventory.empty"})
        if not cards:
            cards = [{"title": "tab.inventory", "items": [], "search": True,
                      "empty": "inventory.empty"}]
        return cards

    def web_press(self, action: str, args) -> dict:
        """«Использовать» from the phone — the same scenario the window plays.

        The count is checked against what the bag holds HERE as well as in the scenario:
        the phone's own copy of a row can be minutes old, and a press that asks for a
        hundred of something there are three of should spend three rather than be refused.
        """
        if action != "use":
            # …and everything else is still the base tab's — «Обновить» above all, which
            # every data screen offers and which this override would otherwise swallow.
            return super().web_press(action, args)
        data = args or {}
        try:
            item_id = int(data.get("item") or 0)
            count = int(data.get("count") or 0)
        except (TypeError, ValueError):
            return {"error": "bad_args"}
        item = next((it for it in (self._last_data or ())
                     if int(it.get("id") or 0) == item_id), None)
        if item is None or not item.get("usable"):
            return {"error": "not_usable"}
        count = max(1, min(count, max(0, int(item.get("count") or 0))))
        if item_id <= 0:
            return {"error": "bad_args"}
        return {"ok": self.rt.play_async("use_item", {"item": item_id, "count": count},
                                         tag="inventory", human=True,
                                         on_result=self._used)}


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(InventoryTab))
