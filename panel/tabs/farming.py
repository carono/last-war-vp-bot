"""The «Что умеет бот» tab: the feature list, built from the documents themselves.

WHAT THE PAGE IS FOR. `docs/farming.md` (canonical) and `docs/farming.ru.md` (its
mirror) are the record of what the bot can actually do — a hundred and eighty-four
abilities, each marked ✅ / 🟡 / ❌. That record was readable only by opening the
repository, so the person driving the panel could not answer «сколько уже готово и
что нового» without leaving it. This page answers it.

ONE SOURCE OF TRUTH, AND IT IS THE DOCUMENTS. Not one word of the list is written
here. The page is BUILT on every look from `tools/lib/farming_doc.py`, which is the
same module `tools/farming_progress.py` counts and draws the bar with — so the
percentage on the screen and the bar in the documents are one number arrived at
once, and there is nothing that can drift. A page typed out beside the documents
would be a second copy of the list, and the first day the two disagreed nobody
could tell which was right; `tests/test_panel_farming_page.py` fails if they ever do.

WHY IT IS RENDERED AND NOT BUILT INTO AN ARTEFACT. The alternative was a script
that compiles the markdown into a file the panel serves. It was rejected for one
reason: an artefact can be STALE, and a stale one looks exactly like a fresh one.
Rendering costs a file read on the person's own look — no game, no database, no
clock — and a document edited a minute ago is on the page the next time somebody
opens it, with no build step anybody can forget.

TWO DOCUMENTS, ELEVEN LANGUAGES. The panel speaks eleven; the feature list is
written in two. Russian reads the Russian document and every other language reads
the English one (`farming_doc.doc_for`). Nothing is machine-translated on the fly:
a sentence nobody wrote and nobody can review, in front of a person deciding
whether an ability works, is worse than an English sentence they can read. Which
document is on screen is a reading on the page, so nobody is left guessing. Every
word the PANEL itself says here is a locale key in all eleven, as always.

READ ONCE, THEN THE PERSON ASKS. The document is read on the first look
(`on_show`) and thereafter only when somebody presses «Обновить». `web_view` hands
over what is already held; the long list does not ride the phone's poll at all —
the card says `paged` and the rows come off `web_data` on a worker, and only when
the stamp moves (`docs/panel-tabs.md`).
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ..widgets import tk_stringvar
from .base import PanelTab

#: How many features one page of the list holds. The renderer draws a paged card
#: whole, so this is what actually lands on the phone at once.
WEB_PAGE = 25

#: The four numbers the first card shows, in the order they are read: the field of
#: the parsed document, and the locale key that names it.
TOTALS = (("done", "farming.done"),
          ("partial", "farming.partial"),
          ("todo", "farming.todo"),
          ("total", "farming.total"))

#: The value of a filter that narrows nothing.
ANY = ""


def _split(text: str) -> tuple:
    """One bullet as a headline and the rest of its prose.

    The documents write every feature the same way — a short name, an em dash, and
    then what it does — so the headline is what a person scans and the remainder is
    what they read when one of them is the answer. Splitting here is what keeps a
    page of twenty-five features readable on a phone; nothing is dropped.
    """
    head, sep, rest = text.partition(" — ")
    if not sep:
        return text, ""
    # A name that ran on into a subordinate clause keeps its comma when the dash is
    # taken away — «Применение навыков, которым не нужна цель,» — and a heading that
    # ends in a comma reads as a sentence somebody cut off.
    return head.rstrip(",;:"), rest.strip()


class FarmingTab(PanelTab):
    ID = "farming"
    TITLE_KEY = "tab.farming"
    ORDER = 15
    LOCALE_NS = ("farming",)
    NEEDS = frozenset()
    WEB_SCREEN = True

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._doc: dict | None = None
        self._read_at = 0.0
        self._lang = ""
        self._page = 0
        self._section = ANY
        self._mark = ANY
        self._moved = 0
        self._totals: dict = {}
        self._head_var = None
        self._text = None

    # -- the document -------------------------------------------------------
    def _read(self) -> dict:
        """The feature list for the language the panel is in — one file read.

        No game, no database, no widget: safe on the Tk thread and on a worker
        alike, which is what lets `web_data` answer a page without a hand-off.
        """
        from ..runtime import paths as _paths
        _paths.ensure()                   # tools/lib, where `farming_doc` lives
        import farming_doc
        lang = self.rt.i18n.lang
        doc = farming_doc.read(lang)
        self._doc = doc
        self._lang = lang
        self._read_at = time.time()
        self._moved += 1
        return doc

    def doc(self) -> dict:
        """What is held, reading it once if nothing has been read yet."""
        if self._doc is None or self._lang != self.rt.i18n.lang:
            return self._read()
        return self._doc

    def refresh(self, human: bool = False) -> None:
        self._read()
        self._paint()
        if human:
            self.say("farming", "farming.reread")

    def on_show(self) -> None:
        if self._doc is None:
            self.refresh()

    def on_language_change(self) -> None:
        # The list itself changes language with the panel — a Russian page and an
        # English list would be the one thing this page cannot explain.
        self._doc = None
        self._page = 0
        self._section = ANY
        self._moved += 1

    # -- what the list looks like once the filters have had it ---------------
    def _rows(self) -> list:
        """Every feature the filters leave, with the section it came from."""
        out = []
        for section in self.doc()["sections"]:
            if self._section and section["title"] != self._section:
                continue
            for item in section["items"]:
                if self._mark and item["state"] != self._mark:
                    continue
                out.append((section["title"], item))
        return out

    # -- drawing (the window) ------------------------------------------------
    def build(self) -> None:
        frame = self.tr(ttk.LabelFrame(self.parent, padding=8), "farming.frame")
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        self._head_var = tk_stringvar(self.rt.root)
        ttk.Label(frame, textvariable=self._head_var).pack(anchor="w")
        self.tr(ttk.Label(frame, foreground="#888", wraplength=620, justify="left"),
                "farming.hint").pack(anchor="w", pady=(4, 6))
        box = ttk.Frame(frame)
        box.pack(fill="both", expand=True)
        self._text = tk.Text(box, wrap="word", height=24, state="disabled")
        bar = ttk.Scrollbar(box, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=bar.set)
        self._text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(6, 0))
        self.tr(ttk.Button(buttons, command=lambda: self.refresh(human=True)),
                "tabx.refresh").pack(side="left")
        self._paint()

    def _paint(self) -> None:
        """Put what is held into the window's own widgets, if they exist yet."""
        if self._head_var is None or self._text is None:
            return
        doc = self.doc()
        self._head_var.set(doc["bar"] + "  " + self.t(
            "farming.head", pct=doc["pct"], done=doc["done"], total=doc["total"]))
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        for section in doc["sections"]:
            self._text.insert("end", "\n%s  (%d/%d)\n" % (
                section["title"], section["done"], section["total"]))
            for item in section["items"]:
                self._text.insert("end", "  %s %s\n" % (item["mark"], item["text"]))
        self._text.configure(state="disabled")

    # -- the phone's copy ----------------------------------------------------
    def web_view(self) -> dict:
        """THREE CARDS: how much is done, where it is, and the list itself.

        The first screen answers «сколько готово», the tiles say which part of the
        game the work sits in, and the list is `paged` — a hundred and eighty-four
        prose descriptions are some seventy kilobytes, and the screen's poll is two
        and a half seconds, so the two do not mix (`docs/panel-tabs.md`).
        """
        doc = self.doc()
        rows = [{"label": key, "value": str(doc[field])} for field, key in TOTALS]
        rows.append({"label": "farming.doc", "value": doc["doc"]})
        progress = {"title": "farming.web.progress",
                    "head": doc["bar"] + "  " + self.t(
                        "farming.head", pct=doc["pct"], done=doc["done"],
                        total=doc["total"]),
                    "note": "farming.note",
                    "rows": rows}
        tiles = {"title": "farming.sections", "layout": "tiles",
                 "empty": "farming.empty",
                 # «10 из 20» AND NOT «10/20» (measured on the phone): the panel marks
                 # every coordinate it sends (`panel/web/coordlinks.py`), and «10/20» is
                 # a coordinate — the count on a tile was drawn as a link that walks the
                 # camera somewhere nobody asked about.
                 "items": [{"text": section["title"],
                            "detail": self.t("farming.of", done=section["done"],
                                             total=section["total"]),
                            "actions": [{"id": "pick", "label": "farming.pick",
                                         "args": {"section": section["title"]}}]}
                           for section in self.doc()["sections"]]}
        listing = {"title": "farming.list", "search": True,
                   "paged": {"kind": "page", "size": WEB_PAGE,
                             "stamp": self._stamp()},
                   "empty": "farming.empty",
                   "options": self._fields(),
                   "options_title": "farming.filters",
                   "actions": [{"id": "page_prev", "label": "farming.page.prev"},
                               {"id": "page_next", "label": "farming.page.next"}]}
        return {"cards": [progress, tiles, listing], "now": time.time(),
                "actions": [{"id": "refresh", "label": "tabx.refresh"}]}

    def _stamp(self) -> str:
        """What has to have moved before the phone asks for the page again."""
        return "%s:%s:%d:%s:%s" % (self._moved, self._lang, self._page,
                                   self._section, self._mark)

    def _fields(self) -> list:
        """The two knobs behind the list's gear: which section, and which mark."""
        sections = [{"value": ANY, "text": self.t("farming.any")}]
        sections += [{"value": s["title"], "text": s["title"]}
                     for s in self.doc()["sections"]]
        marks = [{"value": ANY, "text": self.t("farming.any")}]
        marks += [{"value": state, "text": self.t("farming.state." + state)}
                  for state in ("done", "partial", "todo")]
        return [{"key": "section", "label": "farming.filter.section",
                 "kind": "choice", "value": self._section, "options": sections},
                {"key": "mark", "label": "farming.filter.mark",
                 "kind": "choice", "value": self._mark, "options": marks}]

    def web_data(self, kind: str, args: dict) -> "dict | None":
        """ONE PAGE OF THE LIST — off the Tk thread, as the contract requires.

        `needle` is what was typed into the renderer's search box, and it narrows
        the WHOLE list here rather than the page already drawn: a box that searched
        the twenty-five in hand would answer about the twenty-five.
        """
        if kind != "page":
            return None
        needle = str((args or {}).get("needle") or "").strip().lower()
        rows = self._rows()
        if needle:
            rows = [(title, item) for title, item in rows
                    if needle in item["text"].lower() or needle in title.lower()]
        total = len(rows)
        pages = max(1, -(-total // WEB_PAGE))
        # A page past the end is the LAST page: a filter set while standing on page
        # five leaves the number pointing at nothing, and «пусто» over a list that
        # plainly has rows is the worst answer available.
        page = min(max(self._page, 0), pages - 1)
        chunk = rows[page * WEB_PAGE:(page + 1) * WEB_PAGE]
        return {"items": [self._item(title, item) for title, item in chunk],
                "page": page, "pages": pages, "total": total, "size": WEB_PAGE}

    def _item(self, section: str, item: dict) -> dict:
        """One feature as a row: what it is, where it lives, and how far along."""
        head, rest = _split(item["text"])
        row = {"text": head, "detail": section,
               "pill": "farming.state." + item["state"]}
        if rest:
            row["note"] = rest
        return row

    def web_press(self, action: str, args: dict) -> dict:
        args = args or {}
        if action == "refresh":
            self.refresh(human=True)
            return {"ok": True}
        if action == "pick":
            self._section = str(args.get("section") or ANY)
            self._page = 0
            self._moved += 1
            return {"ok": True}
        if action in ("page_prev", "page_next"):
            self._page = max(0, self._page + (1 if action == "page_next" else -1))
            self._moved += 1
            return {"ok": True}
        if action == "set":
            key, value = str(args.get("key") or ""), str(args.get("value") or "")
            if key == "section":
                self._section = value
            elif key == "mark":
                self._mark = value
            else:
                return {"error": "unknown"}
            self._page = 0
            self._moved += 1
            return {"ok": True}
        return {"error": "unknown"}

    # -- persistence ---------------------------------------------------------
    def config(self) -> dict:
        return {"section": self._section, "mark": self._mark}

    def apply_config(self, raw: dict) -> None:
        self._section = str((raw or {}).get("section") or ANY)
        self._mark = str((raw or {}).get("mark") or ANY)


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(FarmingTab))
