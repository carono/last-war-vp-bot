r"""«СКРЫВАТЬ ПРОСТЫХ МОНСТРОВ» — a display rule, and the rows stay (#1549).

WHAT THIS FILE IS FOR. The operator asked for one switch: «сделай фильтр, скрывать
простых монстров, это `world_monster_boss_*`». The switch itself is four lines; what
needs pinning is the rule it obeys, because this repository has paid for getting it
wrong before — **a filter HIDES, it never drops**. A row held back by a box is still in
the model, still in the checkpoint, and comes straight back when the box is unticked. A
filter that deletes looks identical on screen and is unrecoverable.

So what is pinned here:

  * which prefabs the mask actually covers, measured rather than assumed — live, one
    register answer held 197 ordinary field monsters (`world_monster_boss_bread` 73,
    `_coin_2` 68, `_iron` 56, levels 1…35) against 152 golden zombies;
  * **and the one thing the mask covers that the operator may not have meant**: the
    invasion event's real bosses are `world_monster_boss_invasion`, `_1` and `_2`
    (levels 5…150, `special = 10`, docs/research/golden-zombies.md §1b). They match the
    mask. That is written down as a fact here rather than silently special-cased,
    because the operator named the mask;
  * a row with NO prefab at all is never called plain — hiding what cannot be
    identified is how a list loses the rows nobody can account for;
  * ticking the box changes only what `visible_rows` answers, and `plain_hidden()` says
    how many are being held back;
  * the box survives a restart (it is in the page's own settings block);
  * and the words exist in all eleven locales.

Needs no display: tkinter is stubbed, so this runs under a bare interpreter.

    python3 tests/test_panel_monster_filter.py
"""
from __future__ import annotations

TIER = "pure"      # tkinter is stubbed below — no display, no widgets, no game

import json
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub_tk() -> None:
    """A tkinter that answers everything and draws nothing.

    The page under test is a widget, and the rule under test is arithmetic on a dict.
    Rather than demand a display for the second, the first is given a stand-in — the
    same shape the panel's own «a caller with no runtime» stand-ins take.
    """
    if "tkinter" in sys.modules:
        return

    class _Var:
        def __init__(self, master=None, value=None, **kw):
            self._v = value

        def get(self):
            return self._v

        def set(self, v):
            self._v = v

        def trace_add(self, *a, **k):
            pass

    class _W:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    tk = types.ModuleType("tkinter")
    tk.StringVar = tk.BooleanVar = tk.IntVar = tk.DoubleVar = tk.Variable = _Var
    tk.TclError = type("TclError", (Exception,), {})
    for n in ("Frame", "Label", "Text", "Canvas", "Menu", "Toplevel", "Tk", "Entry",
              "Button", "Listbox", "Scrollbar", "PhotoImage", "Widget", "Misc", "Event"):
        setattr(tk, n, _W)
    for n in ("END", "LEFT", "RIGHT", "TOP", "BOTTOM", "BOTH", "X", "Y", "W", "E", "N",
              "S", "NW", "NE", "SW", "SE", "CENTER", "NORMAL", "DISABLED", "HORIZONTAL",
              "VERTICAL", "WORD", "CHAR", "INSERT"):
        setattr(tk, n, n.lower())
    sys.modules["tkinter"] = tk

    ttk = types.ModuleType("tkinter.ttk")
    for n in ("Frame", "Label", "Button", "Checkbutton", "Entry", "LabelFrame",
              "Notebook", "Treeview", "Scrollbar", "Combobox", "Style", "Separator",
              "Panedwindow", "PanedWindow", "Progressbar", "Radiobutton", "Spinbox",
              "Sizegrip", "Widget"):
        setattr(ttk, n, _W)
    sys.modules["tkinter.ttk"] = ttk
    tk.ttk = ttk

    scrolled = types.ModuleType("tkinter.scrolledtext")
    scrolled.ScrolledText = _W
    sys.modules["tkinter.scrolledtext"] = scrolled

    fontmod = types.ModuleType("tkinter.font")
    fontmod.Font = _W
    fontmod.nametofont = lambda *a, **k: _W()
    fontmod.families = lambda *a, **k: ()
    sys.modules["tkinter.font"] = fontmod

    for extra, names in (("messagebox", ("showerror", "showinfo", "showwarning",
                                         "askyesno", "askokcancel")),
                         ("filedialog", ("askopenfilename", "asksaveasfilename",
                                         "askdirectory")),
                         ("simpledialog", ("askstring",)),
                         ("colorchooser", ("askcolor",))):
        m = types.ModuleType("tkinter." + extra)
        for n in names:
            setattr(m, n, lambda *a, **k: None)
        sys.modules["tkinter." + extra] = m
        setattr(tk, extra, m)


_stub_tk()

from panel.tabs.secret_tasks import world                     # noqa: E402


class _Tab:
    """The two things a grid asks of its tab: a Tk root to hang variables on, and words."""

    def __init__(self) -> None:
        self.rt = types.SimpleNamespace(root=None,
                                        settings=types.SimpleNamespace(changed=lambda: None))

    def t(self, key, **fmt):
        return key

    def tr(self, widget, key, option="text", **fmt):
        return widget

    def sync_page_counts(self):
        pass

    def sync_actions(self):
        pass


def _grid():
    page = world.MonsterGrid(_Tab())
    page._rows = {}
    return page


def _row(uuid: str, kind: str, level: int = 10) -> dict:
    return {"uuid": uuid, "kind_name": kind, "level": level, "x": 1, "y": 2,
            "server": 935, "seen_at": 0.0, "expires_at": None, "completed_at": None}


def _fill(page, *rows) -> None:
    page._rows = {r["uuid"]: r for r in rows}


# ---------------------------------------------------------------------------
# what the mask covers — measured, not assumed
# ---------------------------------------------------------------------------
def test_the_three_resource_bosses_are_plain_and_the_golden_zombie_is_not():
    for kind in ("world_monster_boss_bread", "world_monster_boss_coin_2",
                 "world_monster_boss_iron"):
        assert world.is_plain({"kind_name": kind}), kind
    assert not world.is_plain({"kind_name": "world_monster_general_invasion"})


def test_the_mask_also_covers_the_invasion_bosses_and_that_is_written_down():
    """Not a special case — a FACT, so the next reader does not rediscover it.

    `world_monster_boss_invasion*` are the invasion event's real bosses (levels 5…150).
    They match `world_monster_boss_*` and are therefore hidden by the same box. The
    operator named the mask; if those should stay, the sign is this exact family.
    """
    for kind in ("world_monster_boss_invasion", "world_monster_boss_invasion_1",
                 "world_monster_boss_invasion_2"):
        assert world.is_plain({"kind_name": kind}), kind


def test_a_row_with_no_prefab_is_never_called_plain():
    """A clone the config could not resolve says nothing about what it is."""
    assert not world.is_plain({})
    assert not world.is_plain({"kind_name": ""})
    assert not world.is_plain({"kind_name": "-"})


def test_the_two_sources_spell_a_prefab_differently_and_both_are_matched():
    """The register answers `world_monster_boss_iron`; a drawn clone answers
    `WorldMonster_Boss01`. The game's own lookup normalises both before comparing, and so
    does the box — otherwise it would hide half a page and leave the other half."""
    assert world.is_plain({"kind_name": "world_monster_boss_iron"})
    assert world.is_plain({"kind_name": "WorldMonster_Boss01"})
    assert world.is_plain({"kind_name": "WORLD_MONSTER_BOSS_IRON"})
    # …and a drawn clone that is NOT a boss stays on the table
    assert not world.is_plain({"kind_name": "WorldMonster08"})


# ---------------------------------------------------------------------------
# THE RULE: it hides, it never drops
# ---------------------------------------------------------------------------
def test_hiding_changes_what_is_shown_and_nothing_else():
    page = _grid()
    _fill(page,
          _row("a", "world_monster_boss_iron"),
          _row("b", "world_monster_boss_bread"),
          _row("c", "world_monster_general_invasion"))
    page.hide_plain_var.set(True)
    assert {r["uuid"] for r in page.visible_rows()} == {"c"}
    # …and the model still holds all three, which is the whole rule
    assert set(page._rows) == {"a", "b", "c"}
    assert page.plain_hidden() == 2


def test_unticking_the_box_brings_every_row_straight_back():
    page = _grid()
    _fill(page,
          _row("a", "world_monster_boss_iron"),
          _row("c", "world_monster_general_invasion"))
    page.hide_plain_var.set(True)
    assert len(page.visible_rows()) == 1
    page.hide_plain_var.set(False)
    assert len(page.visible_rows()) == 2
    assert page.plain_hidden() == 0


def test_the_hidden_count_obeys_the_level_range_too():
    """A row already held back by the level boxes is not counted twice as «скрыто»."""
    page = _grid()
    _fill(page,
          _row("a", "world_monster_boss_iron", level=5),
          _row("b", "world_monster_boss_iron", level=30))
    page.hide_plain_var.set(True)
    page.level_from.set("20")
    assert page.plain_hidden() == 1


def test_the_box_is_on_by_default_and_is_saved_with_the_page():
    page = _grid()
    assert page.hide_plain_var.get() is True
    assert page.config()["hide_plain"] is True
    page.apply_config({"hide_plain": False})
    assert page.hide_plain_var.get() is False
    assert page.hide_plain_var in page.persist_vars()


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------
def test_every_word_of_the_filter_is_in_every_shipped_locale():
    keys = ("world.monsters.hide_plain", "world.monsters.plain_hidden",
            "world.monsters.plain_hidden_row", "world.monsters.plain.hide",
            "world.monsters.plain.show")
    locales = sorted((_REPO / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11, [p.name for p in locales]
    for path in locales:
        words = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in words, (path.name, key)


def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    bad = 0
    for t in tests:
        try:
            t()
            print("  ok  ", t.__name__)
        except Exception as exc:                  # noqa: BLE001 — a test runner
            bad += 1
            print("  FAIL", t.__name__, "->", exc)
    print(f"\n{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
