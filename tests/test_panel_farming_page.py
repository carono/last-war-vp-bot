r"""«Что умеет бот» and `docs/farming*.md` cannot drift apart (#2399).

The person asked for the feature list as a page in the panel, and for the two never
to disagree: «или их вести одновременно или какой-то скрипт, чтобы из доки html
собирался, в общем, чтобы расхождений не было». A promise is not a mechanism, so
this file is the mechanism — it fails the moment the page and the documents say
different things.

Five ways they could drift, and each one is pinned:

* **the page could count for itself.** It does not: the page, the bar in the
  documents and this test all count through `tools/lib/farming_doc.py`, and the
  test proves the number on the page IS the number in the documents;
* **the bar could be stale.** `tools/farming_progress.py --write` redraws it, and a
  commit that forgot to run it is caught here rather than six months later;
* **the two documents could diverge from each other.** English is canonical and
  Russian mirrors it, so a feature added to one and not the other is a lie in
  whichever a person happens to read. Section for section, mark for mark;
* **the page could lose items.** Everything in the documents has to be reachable by
  paging through the screen — a filter that quietly drops fifteen abilities is the
  same divergence in a different shape;
* **the page could put a sentence where a locale key belongs.** Eleven languages,
  as everywhere else in the panel.

Needs no display, no game and no panel: tkinter is stubbed, the documents are read
off disk, and the words are read out of the locale files.

    C:\Python312\python.exe tests\test_panel_farming_page.py
    python3 tests/test_panel_farming_page.py
"""
from __future__ import annotations

TIER = "offline"   # tkinter is stubbed below — no display, no widgets, no game

import json
import re
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub_tk() -> None:
    """A tkinter that answers everything and draws nothing (`test_panel_develop_screen`)."""
    if "tkinter" in sys.modules:
        return

    class _W:
        def __init__(self, *a, **k) -> None:
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    def _module(name: str):
        mod = types.ModuleType(name)
        made: dict = {}

        def _make(attr: str):
            if attr not in made:
                made[attr] = type(attr, (_W,), {})
            return made[attr]

        mod.__getattr__ = _make
        return mod

    tk = _module("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    sys.modules["tkinter"] = tk
    for sub in ("ttk", "font", "messagebox", "simpledialog", "scrolledtext",
                "filedialog"):
        child = _module(f"tkinter.{sub}")
        sys.modules[f"tkinter.{sub}"] = child
        setattr(tk, sub, child)


_stub_tk()

import farming_doc                                        # noqa: E402
from panel import tabs as tabsreg                         # noqa: E402
from panel.tabs.farming import FarmingTab, WEB_PAGE       # noqa: E402

LOCALES = _REPO / "panel" / "locales"
LANGS = sorted(p.stem for p in LOCALES.glob("*.json"))
DOCS = _REPO / "docs"

#: A locale key: dotted, lower-case — the same shape `test_panel_web_screens` pins.
_KEYISH = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")

#: Where a KEY is expected on a card or an item, and where DATA is.
_KEY_FIELDS = ("title", "label", "empty", "pill")


class _Tab(FarmingTab):
    """The tab with no runtime behind it: a language, and the English words."""

    def __init__(self, lang: str = "en") -> None:      # noqa: D107 — a stand-in
        self._table = _english()
        self.rt = types.SimpleNamespace(i18n=types.SimpleNamespace(lang=lang),
                                        root=None)
        # Everything `PanelTab.__init__` and this tab's own would have set.
        self._doc = None
        self._read_at = 0.0
        self._lang = ""
        self._page = 0
        self._section = ""
        self._mark = ""
        self._moved = 0
        self._totals = {}
        self._head_var = None
        self._text = None

    def t(self, key: str, **fmt) -> str:
        assert key in self._table, f"no such locale key: {key}"
        return self._table[key].format(**fmt)

    def say(self, tag: str, key: str, **fmt) -> None:
        self.t(key, **fmt)


def _english() -> dict:
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))


def _keys_in(view: dict) -> list:
    found = []
    for card in view.get("cards") or ():
        for field in _KEY_FIELDS:
            if card.get(field):
                found.append(card[field])
        for row in card.get("rows") or ():
            found.append(row.get("label", ""))
        for field in card.get("options") or ():
            found.append(field.get("label", ""))
        for action in card.get("actions") or ():
            found.append(action.get("label", ""))
        for item in card.get("items") or ():
            for field in _KEY_FIELDS:
                if item.get(field):
                    found.append(item[field])
            for action in item.get("actions") or ():
                found.append(action.get("label", ""))
    for card in view.get("cards") or ():
        if card.get("note"):
            found.append(card["note"])
    for action in view.get("actions") or ():
        found.append(action.get("label", ""))
    return [k for k in found if k]


# ---------------------------------------------------------------------------
def test_the_bar_in_both_documents_is_the_one_the_counter_draws() -> None:
    """`tools/farming_progress.py --write` has been run since the list last changed.

    Without this, the page and the list below it would still agree — they are the
    same parse — while the BAR at the top of the documents quietly said last
    month's percentage. That is exactly the divergence the person asked to be rid
    of, in the one place a reader looks first.
    """
    stale = []
    for name in farming_doc.TEXT:
        text = (DOCS / name).read_text(encoding="utf-8")
        want, _numbers = farming_doc.block(name, text)
        found = re.search(re.escape(farming_doc.START) + r".*?" + re.escape(farming_doc.END),
                          text, flags=re.S)
        assert found, f"{name}: no progress markers"
        if found.group(0) != want:
            stale.append(name)
    assert not stale, ("the progress bar is out of date in " + ", ".join(stale) +
                       " — run `python3 tools/farming_progress.py --write`")


def test_the_two_documents_are_the_same_list_in_two_languages() -> None:
    """English is canonical and Russian mirrors it — section for section, mark for mark."""
    en = farming_doc.parse((DOCS / "farming.md").read_text(encoding="utf-8"))
    ru = farming_doc.parse((DOCS / "farming.ru.md").read_text(encoding="utf-8"))
    assert len(en["sections"]) == len(ru["sections"]), (
        f"{len(en['sections'])} sections in English, {len(ru['sections'])} in Russian")
    for i, (a, b) in enumerate(zip(en["sections"], ru["sections"])):
        marks_a = [item["mark"] for item in a["items"]]
        marks_b = [item["mark"] for item in b["items"]]
        assert marks_a == marks_b, (
            f"section {i + 1} — «{a['title']}» / «{b['title']}» — differs:\n"
            f"  en {marks_a}\n  ru {marks_b}")
    for field in ("done", "partial", "todo", "total"):
        assert en[field] == ru[field], f"{field}: en {en[field]} ru {ru[field]}"


def test_the_page_shows_the_documents_own_numbers() -> None:
    """The percentage on the screen IS the one written into the documents."""
    for lang, name in (("en", "farming.md"), ("ru", "farming.ru.md")):
        doc = farming_doc.parse((DOCS / name).read_text(encoding="utf-8"))
        view = _Tab(lang).web_view()
        card = view["cards"][0]
        shown = {row["label"]: row["value"] for row in card["rows"]}
        assert shown["farming.done"] == str(doc["done"]), (lang, shown)
        assert shown["farming.partial"] == str(doc["partial"]), (lang, shown)
        assert shown["farming.todo"] == str(doc["todo"]), (lang, shown)
        assert shown["farming.total"] == str(doc["total"]), (lang, shown)
        assert shown["farming.doc"] == name, (lang, shown)
        assert doc["bar"] in card["head"], (lang, card["head"])
        assert f"{doc['pct']}%" in card["head"], (lang, card["head"])


def test_every_feature_in_the_documents_is_reachable_on_the_page() -> None:
    """Page through the screen and get back exactly the list the document holds.

    A filter, a split or a page boundary that dropped a feature would be the same
    divergence in another shape: the documents would say a hundred and eighty-four
    and the page would show a hundred and eighty-one, with nothing to say which.
    """
    for lang, name in (("en", "farming.md"), ("ru", "farming.ru.md")):
        doc = farming_doc.parse((DOCS / name).read_text(encoding="utf-8"))
        tab = _Tab(lang)
        seen = []
        first = tab.web_data("page", {})
        assert first["total"] == doc["total"], (lang, first["total"], doc["total"])
        for page in range(first["pages"]):
            tab._page = page
            answer = tab.web_data("page", {})
            assert answer["page"] == page, (lang, answer["page"], page)
            assert len(answer["items"]) <= WEB_PAGE, (lang, len(answer["items"]))
            seen.extend(answer["items"])
        assert len(seen) == doc["total"], (
            f"{lang}: the page shows {len(seen)} features, the document has "
            f"{doc['total']}")
        marks = {"done": 0, "partial": 0, "todo": 0}
        for item in seen:
            marks[item["pill"].rsplit(".", 1)[-1]] += 1
        assert marks == {"done": doc["done"], "partial": doc["partial"],
                         "todo": doc["todo"]}, (lang, marks)


def test_the_filters_narrow_and_never_invent() -> None:
    """A section chosen on the page is that section of the document, and no more."""
    doc = farming_doc.parse((DOCS / "farming.md").read_text(encoding="utf-8"))
    section = doc["sections"][0]
    tab = _Tab("en")
    assert tab.web_press("pick", {"section": section["title"]}) == {"ok": True}
    assert tab.web_data("page", {})["total"] == section["total"]
    assert tab.web_press("set", {"key": "mark", "value": "done"}) == {"ok": True}
    assert tab.web_data("page", {})["total"] == section["done"]
    assert tab.web_press("set", {"key": "nonsense", "value": 1}) == {"error": "unknown"}
    assert tab.web_press("nonsense", {}) == {"error": "unknown"}


def test_the_search_box_narrows_the_whole_list() -> None:
    """What is typed narrows the documents, not the twenty-five already drawn."""
    tab = _Tab("en")
    whole = tab.web_data("page", {})["total"]
    narrowed = tab.web_data("page", {"needle": "alliance"})
    assert 0 < narrowed["total"] < whole, (narrowed["total"], whole)


def test_the_screen_is_made_of_keys_and_data_and_never_of_sentences() -> None:
    """Eleven languages by construction — the same rule every other screen keeps."""
    english = _english()
    bad = []
    for key in _keys_in(_Tab("en").web_view()):
        if not _KEYISH.match(key):
            bad.append(f"«{key}» is a sentence, not a locale key")
        elif key not in english:
            bad.append(f"key «{key}» is in no locale")
    assert not bad, "\n  ".join([""] + bad)


def test_every_button_the_screen_offers_is_answered() -> None:
    """A dead button is the commonest half-done mirror, and it is catchable."""
    tab = _Tab("en")
    view = tab.web_view()
    offered = [action["id"] for action in view.get("actions") or ()]
    for card in view["cards"]:
        offered += [action["id"] for action in card.get("actions") or ()]
        for item in card.get("items") or ():
            offered += [action["id"] for action in item.get("actions") or ()]
    if any(card.get("options") for card in view["cards"]):
        offered.append("set")
    for action in sorted(set(offered)):
        answer = _Tab("en").web_press(action, {"key": "mark", "value": "",
                                               "section": ""})
        assert answer.get("error") != "unknown", f"«{action}» is a dead button"


def test_the_page_is_a_registered_tab_that_needs_nothing() -> None:
    """It reads a file — no daemon, no child, no schedule — so it costs a profile nothing."""
    spec = {s.id: s for s in tabsreg.TABS}.get("farming")
    assert spec is not None, "the «Что умеет бот» tab is not in the registry"
    assert spec.title_key == FarmingTab.TITLE_KEY == "tab.farming"
    assert not FarmingTab.NEEDS, FarmingTab.NEEDS
    assert FarmingTab.WEB_SCREEN is True


def test_the_page_holds_no_copy_of_the_list() -> None:
    """Not one feature is written down in the panel — the whole point of the task."""
    source = (_REPO / "panel" / "tabs" / "farming.py").read_text(encoding="utf-8")
    doc = (DOCS / "farming.md").read_text(encoding="utf-8")
    stolen = [item["text"][:40] for section in farming_doc.parse(doc)["sections"]
              for item in section["items"] if item["text"][:40] in source]
    assert not stolen, ("the tab has a copy of the feature list in it: " + str(stolen))
    # …and it does not know what a mark LOOKS like either: the emoji belong to
    # `farming_doc`, which is where the counting rule is. Prose may name them —
    # this looks for one used as a VALUE, in quotes.
    for mark in farming_doc.MARKS:
        for quoted in (f"'{mark}'", f'"{mark}"'):
            assert quoted not in source, (
                f"«{mark}» is a literal in the tab — the marks belong to farming_doc")


def test_the_new_words_are_in_all_eleven_locales() -> None:
    keys = sorted(set(_keys_in(_Tab("en").web_view())) |
                  {"tab.farming", "farming.frame", "farming.hint", "farming.reread",
                   "farming.head", "farming.any"})
    missing = [f"{lang}: {key}" for lang in LANGS for key in keys
               if key not in json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))]
    assert not missing, "\n  ".join([""] + missing)
    assert len(LANGS) == 11, LANGS


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
