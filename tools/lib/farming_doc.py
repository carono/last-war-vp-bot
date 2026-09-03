r"""`docs/farming*.md` read as data — the ONE parser of the feature list.

WHY IT EXISTS. The feature list is written in two markdown files
(`docs/farming.md`, canonical, and `docs/farming.ru.md`, its mirror) and it is
also a page in the panel («Что умеет бот», `panel/tabs/farming.py`). A page typed
out by hand beside the documents would be a second copy of the same list, and the
first day the two disagreed there would be no way to tell which of them was
right. So the page is BUILT from the documents and nothing else is written down:
this module is what turns a document into sections, items and marks.

THE SAME NUMBERS, NOT MERELY EQUAL ONES. `tools/farming_progress.py` — the script
that redraws the progress bar inside both documents — counts through :func:`counts`
and renders through :func:`bar` here, and the panel's page reads the very same
functions. There is one counting rule in this repository, and it is in this file.

WHAT COUNTS AS AN ITEM is unchanged from the day the bar was written: a top-level
bullet that opens with one of the three marks (``- ✅ ``, ``- 🟡 ``, ``- ❌ ``).
The daily-routine tables at the bottom of both documents are a second view of the
same abilities, so counting them would count everything twice.

    python3 -c "import sys; sys.path.insert(0, 'tools/lib'); import farming_doc; \
                print(farming_doc.read('en')['pct'])"
"""
from __future__ import annotations

import os
import re

#: The three marks, in the order a person reads them.
DONE, PARTIAL, TODO = "✅", "🟡", "❌"
MARKS = (DONE, PARTIAL, TODO)

#: The word the panel and the tests use for each mark — a mark is an emoji on the
#: page and a name in the code, and nothing outside this module spells the emoji.
NAMES = {DONE: "done", PARTIAL: "partial", TODO: "todo"}

#: How many cells the bar has. The documents have always had twenty.
CELLS = 20

#: The markers the bar lives between, at the top of both documents.
START, END = "<!-- progress:start -->", "<!-- progress:end -->"

#: A feature bullet. Top level only — a nested one is a note about its parent.
ITEM = re.compile(r"^- (✅|🟡|❌) ", re.M)

#: A heading, with its level.
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")

#: Which document each language reads. The panel ships eleven languages and the
#: feature list is written in two, so everything that is not Russian reads the
#: English one — see :func:`doc_for`.
DOCS = {"en": "farming.md", "ru": "farming.ru.md"}

#: Where the documents are: `<repo>/docs`.
DOCS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs")

#: Per-file wording of the bar's own two lines. The EN copy is canonical and the
#: RU one mirrors it, which is why the two are spelled out rather than translated.
TEXT = {
    "farming.md": ("{bar}  **{pct}%** — {done} of {total}\n\n"
                   "🟩 {done} done · 🟨 {partial} partly · 🟥 {todo} not automated"),
    "farming.ru.md": ("{bar}  **{pct}%** — {done} из {total}\n\n"
                      "🟩 {done} готово · 🟨 {partial} частично · 🟥 {todo} не реализовано"),
}


def doc_for(lang: str) -> str:
    """The document a given panel language reads.

    THE HONEST ANSWER, and it is deliberately not a clever one. The panel speaks
    eleven languages; the feature list is written in two. Machine-translating a
    feature description on the fly would put sentences nobody wrote and nobody
    can review in front of a person who is deciding whether an ability works —
    so Russian reads the Russian document and every other language reads the
    English one, which is the canonical copy anyway. The page says which
    document it is showing, so a German reader is never left guessing why the
    prose is in English.
    """
    return DOCS.get(lang, DOCS["en"])


def path_for(lang: str) -> str:
    return os.path.join(DOCS_DIR, doc_for(lang))


def counts(text: str) -> tuple:
    """``(done, partial, todo, total)`` for one document's text."""
    marks = ITEM.findall(text)
    done = marks.count(DONE)
    partial = marks.count(PARTIAL)
    return done, partial, len(marks) - done - partial, len(marks)


def bar(done: int, partial: int, total: int) -> str:
    """The twenty-cell bar, exactly as both documents carry it."""
    if not total:
        return "🟥" * CELLS
    green = round(done / total * CELLS)
    yellow = round(partial / total * CELLS)
    red = max(0, CELLS - green - yellow)
    return "🟩" * green + "🟨" * yellow + "🟥" * red


def block(name: str, text: str) -> tuple:
    """The whole `<!-- progress:start -->…<!-- progress:end -->` block, and its numbers."""
    done, partial, todo, total = counts(text)
    pct = round(done / total * 100) if total else 0
    body = TEXT[name].format(bar=bar(done, partial, total), pct=pct,
                             done=done, partial=partial, todo=todo, total=total)
    return f"{START}\n{body}\n{END}", (done, partial, todo, total, pct)


def _clean(text: str) -> str:
    """One bullet as a person reads it: no markdown links, no emphasis, no code ticks.

    The page draws this as DATA (`docs/panel-tabs.md`), so what leaves here has to
    be a sentence rather than markup — a link to another document is a link the
    phone cannot follow, and its target is a path a reader has no use for.
    """
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)   # [words](path) -> words
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    text = text.replace("«", "«").replace("\n", " ")
    return re.sub(r"\s{2,}", " ", text).strip()


def parse(text: str) -> dict:
    """One document as sections of marked items.

    A section is the nearest heading above an item, whatever its level — the two
    documents put most features under a `###` and one group under a `##`, and
    which of the two it is says nothing a reader needs.
    """
    sections: list = []
    current: dict | None = None
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        head = HEADING.match(line)
        if head:
            current = {"title": _clean(head.group(2)), "level": len(head.group(1)),
                       "items": []}
            sections.append(current)
            i += 1
            continue
        mark = line[2:3] if line[:2] == "- " else ""
        if mark in MARKS and line[3:4] == " ":
            body = [line[4:]]
            # A bullet may wrap over several lines; a following line that is
            # indented and not itself a bullet is more of the same sentence.
            i += 1
            while i < len(lines) and lines[i][:2] in ("  ", "\t") and \
                    not lines[i].strip().startswith("- "):
                body.append(lines[i].strip())
                i += 1
            if current is None:
                current = {"title": "", "level": 0, "items": []}
                sections.append(current)
            current["items"].append({"mark": mark, "state": NAMES[mark],
                                     "text": _clean(" ".join(body))})
            continue
        i += 1
    done, partial, todo, total = counts(text)
    kept = [s for s in sections if s["items"]]
    for section in kept:
        marks = [item["mark"] for item in section["items"]]
        section["done"] = marks.count(DONE)
        section["partial"] = marks.count(PARTIAL)
        section["todo"] = marks.count(TODO)
        section["total"] = len(marks)
    return {"sections": kept, "done": done, "partial": partial, "todo": todo,
            "total": total, "pct": round(done / total * 100) if total else 0,
            "bar": bar(done, partial, total)}


def read(lang: str = "en") -> dict:
    """The feature list for one panel language, straight off the document.

    Reading a file is what this costs, and it happens when somebody opens the
    page or presses «Обновить» — never on a clock. It touches no game and no
    database, so it is safe on any thread.
    """
    name = doc_for(lang)
    path = os.path.join(DOCS_DIR, name)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    data = parse(text)
    data["doc"] = name
    data["lang"] = "ru" if name == DOCS["ru"] else "en"
    data["mtime"] = os.path.getmtime(path)
    return data
