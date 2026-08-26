r"""«Разработка» on the phone: the jam travels, the recording does not (#1976).

The tab said `WEB_SCREEN = False` and it was one of the three written-down divergences.
The person ended it — «сделать экран» — and the split inside it is what this file pins,
because the reason each half went the way it did is the part that will be forgotten:

  * **«Занятость» travels whole.** It is a read of dicts under locks, it asks the game
    nothing, and «почему панель ничего не делает» is the one question somebody away from
    the machine cannot ask any other way. The cards are the window's own grids, off the
    same `rows()`, so a section added to one reaches both;
  * **the sniffer pair is a reading and carries no press.** Starting it asks for a label
    in a message box, stopping it asks whether to keep the run — two modals raised on a
    machine nobody is standing at. A press naming one is answered «unknown» rather than
    doing half of it;
  * **the update channel travels as a switch**, because it is one boolean of the checkout
    with nothing to confirm.

Needs no display and no game: tkinter is stubbed, the snapshot is taken off a runtime
with nothing in it, and the words are read out of the locale files.

    C:\Python312\python.exe tests\test_panel_develop_screen.py
    python3 tests/test_panel_develop_screen.py
"""
from __future__ import annotations

TIER = "offline"   # tkinter is stubbed below — no display, no widgets, no game

import json
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub_tk() -> None:
    """A tkinter that answers everything and draws nothing (`test_panel_monster_filter`)."""
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

from panel.runtime import busy as busymod                    # noqa: E402
from panel.runtime.activity import Activity                  # noqa: E402
from panel.runtime.interrupt import Interrupts               # noqa: E402
from panel.runtime.tick import Ticker                        # noqa: E402
from panel.tabs.develop import DevelopTab                    # noqa: E402
from panel.tabs.develop_busy import BusyView, GROUPS         # noqa: E402

LOCALES = _REPO / "panel" / "locales"
LANGS = sorted(p.stem for p in LOCALES.glob("*.json"))
NEW_KEYS = ("develop.sniff.idle", "develop.web.reading_only")

#: Where a key is expected on a card, and where data is (`test_panel_web_screens`).
_KEY_FIELDS = ("title", "empty", "label", "pill")


class _Widget:
    def after(self, _delay, func):
        return 1

    def after_cancel(self, job) -> None:
        pass


class _Runtime:
    def __init__(self) -> None:
        self.profiles = type("P", (), {"active": "alice"})()
        self.interrupts = Interrupts()
        self.activity = Activity(name="alice")
        self.tick = Ticker(_Widget())
        self.game = type("G", (), {"endpoint": lambda self: ("127.0.0.1", 47654)})()
        self._schedule = None
        self.root = None


class _Tab:
    def __init__(self, rt, table: dict) -> None:
        self.rt = rt
        self._table = table

    def t(self, key: str, **fmt) -> str:
        assert key in self._table, f"no such locale key: {key}"
        return self._table[key].format(**fmt)


def _english() -> dict:
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))


def _cards() -> list:
    rt = _Runtime()
    return BusyView(_Tab(rt, _english())).web_cards(busymod.snapshot(rt))


# ---------------------------------------------------------------------------
def test_the_phone_gets_one_card_per_grid_the_window_stacks() -> None:
    titles = [card["title"] for card in _cards()]
    assert titles == [title for _key, title, _s, _c in GROUPS], titles


def test_a_grid_with_nothing_in_it_still_shows() -> None:
    """A card that vanished reads «таких нет» — which an empty listener list is not."""
    for card in _cards():
        assert card.get("empty") == "busy.none", card
        assert isinstance(card.get("items"), list)


def test_every_word_on_the_cards_is_a_key_and_every_value_is_data() -> None:
    english = _english()
    for card in _cards():
        for field in _KEY_FIELDS:
            if card.get(field):
                assert card[field] in english, f"{card[field]} is in no locale"
        for item in card["items"]:
            for field in _KEY_FIELDS:
                if item.get(field):
                    assert item[field] in english, f"{item[field]} is in no locale"
            for fact in item.get("facts") or ():
                assert fact["label"] in english, fact


def test_the_tab_offers_a_screen_now() -> None:
    assert DevelopTab.WEB_SCREEN is True, (
        "«Разработка» has no phone screen — the divergence was ended in #1976")


def test_the_only_knob_the_screen_carries_is_the_update_channel() -> None:
    tab = DevelopTab.__new__(DevelopTab)
    for never in ("sniff", "trace", "scenario", "loop", "page"):
        assert tab.web_press("set", {"key": never, "value": True}) == {"error": "unknown"}, (
            f"«{never}» is pressable from the phone — it opens a box at the machine")
    for never in ("start", "stop", "save"):
        assert tab.web_press(never, {}) == {"error": "unknown"}, never


def test_the_recording_says_whether_it_is_running_and_nothing_else() -> None:
    tab = DevelopTab.__new__(DevelopTab)
    tab._sniff_proc = tab._trace_proc = None
    assert tab._sniffing() is False
    tab._trace_proc = object()            # one half is enough — `_sync_sniff_var`'s rule
    assert tab._sniffing() is True


def test_the_new_words_are_in_all_eleven_locales() -> None:
    missing = [f"{lang}: {key}" for lang in LANGS
               for key in NEW_KEYS
               if key not in json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))]
    assert not missing, "\n  ".join([""] + missing)


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
