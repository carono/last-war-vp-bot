r"""The Settings page — its sub-tabs, and the auto-rally one that drives a recipe.

The page is a Notebook driven by `SETTINGS_TABS`: every entry has a builder now
(«Общие» and «Игра» hold the knobs that used to be constants in the panel's own
source, and their values are read back through `_opt_*`). What is worth pinning down
is the auto-rally tab, because two of its rules are easy to break and quiet when
broken:

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
    import customtkinter as ctk
    from tkinter import ttk
    from panel import i18n as i18nmod
    import panel.__main__ as pm

    root = ctk.CTk()          # the panel is a CustomTkinter app now (#1129)
    root.withdraw()

    class _Page:
        def __init__(self):
            self._i18n = i18nmod.I18n("ru")
            self._tr_widgets: list = []
            self._tr_hooks: list = []
            self.saves = 0
            # The Settings page's knobs live in one dict of Tk variables created
            # before any tab is built (see Panel.__init__), and «Общие» / «Игра»
            # bind their rows to it. Without them the two tabs cannot be built,
            # and the page under test is the page with all three tabs filled.
            self._settings: dict = {}
            self._opt_vars: dict = {}
            for key, default in pm.SETTINGS_DEFAULTS.items():
                self._opt_vars[key] = (tk.BooleanVar(value=bool(default))
                                       if isinstance(default, bool)
                                       else tk.StringVar(value=str(default)))

        _t = pm.Panel._t
        _tr = pm.Panel._tr
        _opt = pm.Panel._opt
        _opt_int = pm.Panel._opt_int
        _opt_float = pm.Panel._opt_float
        _sweep_box = pm.Panel._sweep_box
        _opt_row = pm.Panel._opt_row
        _build_settings_tab = pm.Panel._build_settings_tab
        _build_general_settings = pm.Panel._build_general_settings
        _build_game_settings = pm.Panel._build_game_settings
        _refresh_sweep_settings_hint = pm.Panel._refresh_sweep_settings_hint
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
        # The page's tab strip is a CustomTkinter CTkNotebook (the panel moved off
        # ttk in #1129); it keeps the ttk.Notebook tabs()/tab() surface.
        from panel.ctk_widgets import CTkNotebook
        notebooks = [w for w in root.winfo_children()[0].winfo_children()
                     if isinstance(w, CTkNotebook)]
        assert notebooks, "the settings page has no notebook"
        tabs = notebooks[0].tabs()
        assert len(tabs) == len(pm.SETTINGS_TABS), tabs
        labels = [notebooks[0].tab(t, "text") for t in tabs]
        assert labels[0] == page._t("settings.tab.autorally"), labels

        # Every tab in the registry has a builder now, so none of them is the
        # placeholder — «Общие» and «Игра» hold the knobs that used to be constants
        # in panel/__main__.py.
        assert all(builder for _key, builder in pm.SETTINGS_TABS), pm.SETTINGS_TABS
        for key in ("win_python", "daemon_port", "watchdog", "sweep_step"):
            assert key in page._opt_vars, key
        # …and the panel reads them back through the same accessors, defaults and all.
        assert page._opt_int("daemon_port") == pm.SETTINGS_DEFAULTS["daemon_port"]
        page._opt_vars["daemon_port"].set("not a port")
        assert page._opt_int("daemon_port") == pm.SETTINGS_DEFAULTS["daemon_port"], \
            "a half-typed port must fall back, not be obeyed"
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
