r"""The Settings page — its sub-tabs, and the auto-rally one that drives a recipe.

The page is an AGGREGATOR: the shell's own sub-tabs come from `SETTINGS_TABS` («Общие»
and «Игра», holding the knobs that used to be constants in the panel's own source, read
back through `_opt_*`), and then every plugin tab that declares a `SETTINGS_PAGE_KEY`
contributes one of its own (docs/research/panel-tabs-refactor.md §6).

«Авторалли» is the first of those: it belongs to the «Ралли» tab
(panel/tabs/rally/autorally.py) and travels with it, so a profile without rally has no
auto-rally settings either. It is still tested here, because a settings page is what it
is — and two of its rules are easy to break and quiet when broken:

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
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:                                        # the WSL python3 has no tkinter
    from tkinter import ttk
except Exception:                           # noqa: BLE001
    ttk = None


def _page(plugin_tabs: dict | None = None):
    """A Panel stand-in with the Settings page really built.

    ``plugin_tabs`` are the tabs this window has; the aggregator asks each of them for
    a page, so passing one is how the contributed half is tested (§6).
    """
    import logging
    import tkinter as tk
    import fake_runtime
    from panel import runtime as rtmod
    import panel.__main__ as pm

    root = tk.Tk()          # the panel is a plain tkinter/ttk app
    root.withdraw()

    class _Page:
        def __init__(self):
            self._i18n = rtmod.Translator("ru")
            self.saves = 0
            # The Settings page's knobs live in one dict of Tk variables created
            # before any tab is built (see Panel.__init__), and «Общие» / «Игра»
            # bind their rows to it. Without them neither tab can be built, and the
            # page under test is the page with both of them filled.
            self._settings: dict = {}
            self._plugin_tabs: dict = dict(plugin_tabs or {})
            self._opt_vars: dict = {}

        _t = pm.Panel._t
        _tr = pm.Panel._tr
        _hook = pm.Panel._hook
        _opt = pm.Panel._opt
        _opt_int = pm.Panel._opt_int
        _opt_float = pm.Panel._opt_float
        _sweep_box = pm.Panel._sweep_box
        _opt_row = pm.Panel._opt_row
        _build_settings_tab = pm.Panel._build_settings_tab
        _build_general_settings = pm.Panel._build_general_settings
        _build_debug_log_settings = pm.Panel._build_debug_log_settings
        _build_game_settings = pm.Panel._build_game_settings
        _refresh_sweep_settings_hint = pm.Panel._refresh_sweep_settings_hint

        def _save_settings(self):
            self.saves += 1

        def _say(self, *a, **k):
            pass

        def _send_debug_archive(self):
            """The «Отправить диагностику» button's command — never pressed here."""

    page = _Page()
    page._dbg = logging.getLogger("test-settings")
    # The knobs come from the binder, exactly as the panel's do: one variable per
    # default, created before any tab is built.
    binder = fake_runtime.attach_binder(page)
    page._opt_vars = binder.create_vars(root, pm._settings_var)
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
        # The page's tab strip is a ttk.Notebook.
        notebooks = [w for w in root.winfo_children()[0].winfo_children()
                     if isinstance(w, ttk.Notebook)]
        assert notebooks, "the settings page has no notebook"
        tabs = notebooks[0].tabs()
        # This stand-in has no plugin tabs, so the page is the shell's own two.
        assert len(tabs) == len(pm.SETTINGS_TABS), tabs
        labels = [notebooks[0].tab(t, "text") for t in tabs]
        assert labels[0] == page._t("settings.tab.general"), labels

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


def test_the_tabs_page_writes_the_profile_and_asks_for_a_restart():
    """«Настройки → Вкладки» is the UI over `tabs.enabled` — the point of the refactor.

    Unticking one has to REACH THE PROFILE (or the next start builds it again) and has
    to say that a restart is what applies it: a tab brings up its own standing orders
    when it is built, so taking one down mid-flight is a different job.
    """
    if ttk is None:
        _skip()
        return
    try:
        import tkinter as tk
        import fake_runtime
        from panel import tabs as tabsreg
        from panel.tabs.settings import SettingsTab
        root = tk.Tk()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    root.withdraw()
    try:
        rt = fake_runtime.cold_runtime(root)
        saved = {}
        rt.settings.values = saved
        rt.settings.save = lambda raw=None: None        # no profile on disk here
        tab = SettingsTab(rt, ttk.Frame(root))
        tab._build_tabs_settings(ttk.Frame(root))

        # Every registered tab has a row, ticked as the profile resolves it.
        assert set(tab._tab_vars) == {s.id for s in tabsreg.TABS}, tab._tab_vars
        assert tab._tab_vars["rally"].get() is True
        assert tab._tab_vars["develop"].get() is False, "a default-off tab starts off"

        tab._tab_vars["rally"].set(False)
        tab._save_tab_choice()
        assert "rally" not in saved["tabs"]["enabled"], saved["tabs"]
        # …and `known` goes with it, or the next start would read the unticked tab as
        # one that did not exist yet and switch it back on.
        assert "rally" in saved["tabs"]["known"], saved["tabs"]
        assert [s.id for s in tabsreg.resolve(
            enabled=saved["tabs"]["enabled"],
            known=saved["tabs"]["known"])].count("rally") == 0
        assert tab._tabs_note.cget("text") == rt.t("settings.tabs.restart")
    finally:
        root.destroy()


def test_a_tab_contributes_its_own_settings_page():
    """«Авторалли» is drawn by the rally tab, so it is there when rally is, and not
    when it is not (docs/research/panel-tabs-refactor.md §6)."""
    if ttk is None:
        _skip()
        return

    class _Contributor:
        ID = "rally"
        SETTINGS_PAGE_KEY = "settings.tab.autorally"

        def __init__(self):
            self.drawn = []

        def settings_page(self, parent):
            self.drawn.append(parent)

    tab = _Contributor()
    try:
        root, page, pm = _page({"rally": tab})
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        nb = [w for w in root.winfo_children()[0].winfo_children()
              if isinstance(w, ttk.Notebook)][0]
        labels = [nb.tab(t, "text") for t in nb.tabs()]
        assert len(labels) == len(pm.SETTINGS_TABS) + 1, labels
        assert labels[-1] == page._t("settings.tab.autorally"), labels
        assert tab.drawn, "the tab was never asked to draw its page"
    finally:
        root.destroy()

    # …and a window without that tab has no auto-rally page at all.
    try:
        root, page, pm = _page()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        nb = [w for w in root.winfo_children()[0].winfo_children()
              if isinstance(w, ttk.Notebook)][0]
        labels = [nb.tab(t, "text") for t in nb.tabs()]
        assert page._t("settings.tab.autorally") not in labels, labels
    finally:
        root.destroy()


def test_drill_squads_cycle_and_only_one_carries_the_banner():
    try:
        import tkinter  # noqa: F401
    except Exception:                                   # noqa: BLE001
        _skip()
        return
    try:
        root, page, ar = _autorally_page()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        off, on, flag = ar.DRILL_OFF, ar.DRILL_ON, ar.DRILL_FLAG
        assert set(page._drill_state.values()) == {off}, page._drill_state

        # out -> in -> leading -> out
        page.cycle_drill_squad(1)
        assert page._drill_state[1] == on
        page.cycle_drill_squad(1)
        assert page._drill_state[1] == flag
        assert page._drill_buttons[1].cget("text").endswith("🚩")
        page.cycle_drill_squad(1)
        assert page._drill_state[1] == off
        assert page.saves == 3, "each click must persist"

        # With the banner taken, another squad's cycle skips it: out -> in -> out.
        page.cycle_drill_squad(2)
        page.cycle_drill_squad(2)                      # 2 leads
        assert page._drill_state[2] == flag
        page.cycle_drill_squad(3)
        assert page._drill_state[3] == on
        page.cycle_drill_squad(3)
        assert page._drill_state[3] == off, "a click stole the banner from squad 2"
        assert page._drill_state[2] == flag, "squad 2 lost the banner to a click elsewhere"

        # Setting it explicitly does move it — and leaves the old holder in, not out.
        page._drill_state[3] = ar.DRILL_ON
        page.cycle_drill_squad(2)                      # 2: flag -> out, banner free
        assert page._drill_state[2] == off
        page.cycle_drill_squad(3)                      # 3: in -> leading
        assert page._drill_state[3] == flag
        page.cycle_drill_squad(1)
        page.cycle_drill_squad(1)                      # 1 wants it, 3 has it
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
        root, page, ar = _autorally_page()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        # A fresh page saves "nothing chosen" rather than something surprising.
        blank = page.config()
        assert blank["squads"] == [] and blank["drill"]["squads"] == []
        assert blank["drill"]["flagship"] is None, blank

        page._squad_vars[1].set(True)
        page._squad_vars[3].set(True)
        page._drill_on_var.set(True)
        page._drill_banner_var.set(True)
        page.cycle_drill_squad(2)                      # 2 joins
        page.cycle_drill_squad(4)
        page.cycle_drill_squad(4)                      # 4 leads
        saved = page.config()
        assert saved["squads"] == [1, 3], saved
        assert saved["drill"] == {"enabled": True, "create_banner": True,
                                  "squads": [2, 4], "flagship": 4}, saved

        # Loading it back reproduces the page exactly.
        page.apply_config(saved)
        assert page.config() == saved
        assert page._drill_state[4] == ar.DRILL_FLAG
        assert page._drill_buttons[2].cget("text").endswith("✓")

        # A hand-edited config cannot smuggle in two banners or a leader that is
        # not even in the squad list.
        page.apply_config({"squads": [2], "drill": {"squads": [1, 2],
                                                               "flagship": 3}})
        assert page.config()["drill"]["flagship"] is None
        assert list(page._drill_state.values()).count(ar.DRILL_FLAG) == 0

        # Junk in the file is "nothing chosen", not a crash.
        page.apply_config({"squads": "1,2", "drill": "yes"})
        assert page.config()["squads"] == []
        page.apply_config(None)
        assert page.config()["drill"]["squads"] == []
    finally:
        root.destroy()


def _autorally_page(build: bool = True):
    """The «Авторалли» page on a cold runtime, and a counter of what it persists.

    It is the rally tab's page (panel/tabs/rally/autorally.py), so it is built the way
    the tab builds it: state in the constructor, widgets in `build`. Nothing here
    touches the game — the page has no reason to.
    """
    import tkinter as tk
    from tkinter import ttk
    import fake_runtime
    from panel.tabs.rally import autorally as ar

    root = tk.Tk()          # a plain tkinter/ttk app
    root.withdraw()
    rt = fake_runtime.cold_runtime(root)
    page = ar.AutoRallyPage(rt)
    page.saves = 0
    # A tri-state button is not a Tk variable, so it says so instead of being traced.
    rt.settings.on_change = lambda: setattr(page, "saves", page.saves + 1)
    if build:
        page.build(ttk.Frame(root))
    return root, page, ar


def test_create_rally_squad_is_a_single_banner_and_a_bounded_level():
    try:
        import tkinter  # noqa: F401
    except Exception:                                   # noqa: BLE001
        _skip()
        return
    try:
        root, page, ar = _autorally_page()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        # Blank at the start, level at the floor.
        assert page._create_flagship is None
        assert page.create_elite_level() == ar.RALLY_ELITE_MIN

        # blank -> 🚩, and each click persists.
        page.cycle_create_squad(2)
        assert page._create_flagship == 2 and page.saves == 1
        assert page._create_buttons[2].cget("text").endswith("🚩")

        # Only one banner: picking another moves it, it is never in two places.
        page.cycle_create_squad(3)
        assert page._create_flagship == 3
        assert not page._create_buttons[2].cget("text").endswith("🚩")

        # Clicking the holder clears it.
        page.cycle_create_squad(3)
        assert page._create_flagship is None

        # The level is clamped, not obeyed blindly.
        page._create_elite_var.set(str(ar.RALLY_ELITE_MAX + 5))
        assert page.create_elite_level() == ar.RALLY_ELITE_MAX
        page._create_elite_var.set("0")
        assert page.create_elite_level() == ar.RALLY_ELITE_MIN
        page._create_elite_var.set("not a level")
        assert page.create_elite_level() == ar.RALLY_ELITE_MIN

        # It round-trips through the profile block, and junk falls back to safe.
        page._create_elite_var.set("17")
        page.cycle_create_squad(4)
        assert page.config()["create"] == {"flagship": 4, "elite_level": 17}
        page.apply_config({"create": {"flagship": 1, "elite_level": 22}})
        assert page._create_flagship == 1 and page.create_elite_level() == 22
        assert page._create_buttons[1].cget("text").endswith("🚩")
        page.apply_config({"create": {"flagship": 99, "elite_level": "x"}})
        assert page._create_flagship is None
        assert page.create_elite_level() == ar.RALLY_ELITE_MIN
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
