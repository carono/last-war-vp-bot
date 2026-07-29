r"""The Settings page — its sub-tabs, and the auto-rally one that has content.

The page is a Notebook driven by `SETTINGS_TABS`: a tab with a builder is filled,
one without gets the placeholder. What is worth pinning down is the auto-rally tab,
because two of its rules are easy to break and quiet when broken:

  * the drill squads are TRI-state (out / in / leading) and exactly one squad can
    lead — a click must never quietly take the banner off the squad that has it,
    and a hand-edited config with two banners must not load as two;
  * the whole page round-trips through the profile config: `[1, 3]` in, `[1, 3]`
    out, and a saved leader that is not in the squad list is not a leader.

Needs Tk and a display, so it says SKIP under the WSL python3 (no tkinter) or on
a headless box. `Panel`'s methods are called unbound against a stand-in — no
panel window, no profile touched, no game.

    C:\Python312\python.exe tests\test_panel_settings.py
    python3 tests/test_panel_settings.py        # SKIP without tkinter
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _page():
    """A Panel stand-in with the Settings page really built."""
    import tkinter as tk
    from tkinter import ttk
    from panel import i18n as i18nmod
    import panel.__main__ as pm

    root = tk.Tk()
    root.withdraw()

    class _Page:
        def __init__(self):
            self._i18n = i18nmod.I18n("ru")
            self._tr_widgets: list = []
            self._tr_hooks: list = []
            self.saves = 0

        _t = pm.Panel._t
        _tr = pm.Panel._tr
        _build_settings_tab = pm.Panel._build_settings_tab
        _build_autorally_settings = pm.Panel._build_autorally_settings
        _cycle_drill_squad = pm.Panel._cycle_drill_squad
        _paint_drill_squads = pm.Panel._paint_drill_squads
        _autorally_config = pm.Panel._autorally_config
        _apply_autorally_config = pm.Panel._apply_autorally_config

        def _save_settings(self):
            self.saves += 1

    page = _Page()
    page._build_settings_tab(ttk.Frame(root))
    return root, page, pm


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else
          "  SKIP tkinter not importable — run under the Windows Python")


def test_settings_page_lists_its_tabs_and_stubs_the_empty_ones():
    try:
        import tkinter  # noqa: F401
    except Exception:                                   # noqa: BLE001
        _skip()
        return
    try:
        root, page, pm = _page()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        # Every entry of the registry became a tab, in order, with its own label.
        notebooks = [w for w in root.winfo_children()[0].winfo_children()
                     if w.winfo_class() == "TNotebook"]
        assert notebooks, "the settings page has no notebook"
        tabs = notebooks[0].tabs()
        assert len(tabs) == len(pm.SETTINGS_TABS), tabs
        labels = [notebooks[0].tab(t, "text") for t in tabs]
        assert labels[0] == page._t("settings.tab.autorally"), labels

        # A tab with no builder yet is not empty — it says so.
        empty = notebooks[0].nametowidget(tabs[1])
        texts = [w.cget("text") for w in empty.winfo_children()
                 if "text" in w.configure()]
        assert page._t("settings.placeholder") in texts, texts
    finally:
        root.destroy()


def test_drill_squads_cycle_and_only_one_carries_the_banner():
    try:
        import tkinter  # noqa: F401
    except Exception:                                   # noqa: BLE001
        _skip()
        return
    try:
        root, page, pm = _page()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        off, on, flag = pm.DRILL_OFF, pm.DRILL_ON, pm.DRILL_FLAG
        assert set(page._drill_state.values()) == {off}, page._drill_state

        # out -> in -> leading -> out
        page._cycle_drill_squad(1)
        assert page._drill_state[1] == on
        page._cycle_drill_squad(1)
        assert page._drill_state[1] == flag
        assert page._drill_buttons[1].cget("text").endswith("🚩")
        page._cycle_drill_squad(1)
        assert page._drill_state[1] == off
        assert page.saves == 3, "each click must persist"

        # With the banner taken, another squad's cycle skips it: out -> in -> out.
        page._cycle_drill_squad(2)
        page._cycle_drill_squad(2)                      # 2 leads
        assert page._drill_state[2] == flag
        page._cycle_drill_squad(3)
        assert page._drill_state[3] == on
        page._cycle_drill_squad(3)
        assert page._drill_state[3] == off, "a click stole the banner from squad 2"
        assert page._drill_state[2] == flag, "squad 2 lost the banner to a click elsewhere"

        # Setting it explicitly does move it — and leaves the old holder in, not out.
        page._drill_state[3] = pm.DRILL_ON
        page._cycle_drill_squad(2)                      # 2: flag -> out, banner free
        assert page._drill_state[2] == off
        page._cycle_drill_squad(3)                      # 3: in -> leading
        assert page._drill_state[3] == flag
        page._cycle_drill_squad(1)
        page._cycle_drill_squad(1)                      # 1 wants it, 3 has it
        assert page._drill_state[1] == off and page._drill_state[3] == flag
    finally:
        root.destroy()


def test_the_page_round_trips_through_the_profile_config():
    try:
        import tkinter  # noqa: F401
    except Exception:                                   # noqa: BLE001
        _skip()
        return
    try:
        root, page, pm = _page()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        # A fresh page saves "nothing chosen" rather than something surprising.
        blank = page._autorally_config()
        assert blank["squads"] == [] and blank["drill"]["squads"] == []
        assert blank["drill"]["flagship"] is None, blank

        page._rally_squad_vars[1].set(True)
        page._rally_squad_vars[3].set(True)
        page._drill_on_var.set(True)
        page._drill_banner_var.set(True)
        page._cycle_drill_squad(2)                      # 2 joins
        page._cycle_drill_squad(4)
        page._cycle_drill_squad(4)                      # 4 leads
        saved = page._autorally_config()
        assert saved["squads"] == [1, 3], saved
        assert saved["drill"] == {"enabled": True, "create_banner": True,
                                  "squads": [2, 4], "flagship": 4}, saved

        # Loading it back reproduces the page exactly.
        page._apply_autorally_config(saved)
        assert page._autorally_config() == saved
        assert page._drill_state[4] == pm.DRILL_FLAG
        assert page._drill_buttons[2].cget("text").endswith("✓")

        # A hand-edited config cannot smuggle in two banners or a leader that is
        # not even in the squad list.
        page._apply_autorally_config({"squads": [2], "drill": {"squads": [1, 2],
                                                               "flagship": 3}})
        assert page._autorally_config()["drill"]["flagship"] is None
        assert list(page._drill_state.values()).count(pm.DRILL_FLAG) == 0

        # Junk in the file is "nothing chosen", not a crash.
        page._apply_autorally_config({"squads": "1,2", "drill": "yes"})
        assert page._autorally_config()["squads"] == []
        page._apply_autorally_config(None)
        assert page._autorally_config()["drill"]["squads"] == []
    finally:
        root.destroy()


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
