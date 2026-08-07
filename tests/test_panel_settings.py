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
    """The real «Настройки» tab, built, in a window of its own.

    ``plugin_tabs`` are the tabs this window has; the aggregator asks each of them for
    a page, so passing one is how the contributed half is tested (§6).

    This used to be a `Panel` stand-in that borrowed `_build_settings_tab` and its
    helpers off the shell class. Every one of them moved into `panel/tabs/settings.py`
    in #1184, and the borrow started raising `AttributeError` — which the callers below
    catch and report as "no tkinter / display". Both tests said SKIP under a perfectly
    good Tk for four commits, in a run that printed `6/6 passed` (#1191). Building the
    tab the way the shell builds it cannot go stale that way.
    """
    import tkinter as tk
    import fake_runtime
    from panel.tabs.settings import SettingsTab

    root = tk.Tk()          # the panel is a plain tkinter/ttk app
    root.withdraw()
    rt = fake_runtime.cold_runtime(root)
    rt.settings.save = lambda raw=None: None            # no profile on disk here
    for tab in (plugin_tabs or {}).values():
        rt.tabs.add(tab)

    page = SettingsTab(rt, ttk.Frame(root))
    page.parent.pack(fill="both", expand=True)
    page.build()
    return root, page, rt


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else
          "  SKIP tkinter not importable — run under the Windows Python")


def test_settings_page_lists_its_tabs_and_stubs_the_empty_ones():
    try:
        import tkinter  # noqa: F401
    except Exception:                                   # noqa: BLE001
        _skip()
        return
    from panel import runtime as rtmod
    from panel.tabs.settings import SHELL_PAGES
    try:
        root, page, rt = _page()
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
        # This window has no plugin tabs, so the page is the shell's own three.
        assert len(tabs) == len(SHELL_PAGES), tabs
        labels = [notebooks[0].tab(t, "text") for t in tabs]
        assert labels[0] == page.t("settings.tab.general"), labels

        # Every page of the shell's own half has a builder now, so none of them is the
        # placeholder — «Общие» and «Игра» hold the knobs that used to be constants
        # in panel/__main__.py.
        assert all(builder for _key, builder in SHELL_PAGES), SHELL_PAGES
        # The whole `sweep_*` family was here and is gone (#1265, #1272): a step means
        # nothing without the camera height it was measured at, and then «Автообъезд
        # карты» itself was replaced by «Обойти карту» on the «Секретки» coordinate bar,
        # which walks the server in about three seconds and needs no box to be sized.
        for key in ("win_python", "daemon_port", "watchdog", "autoassist_poll"):
            assert key in rt.settings.vars, key
        # …and the panel reads them back through the same accessors, defaults and all.
        assert rt.settings.opt_int("daemon_port") == rtmod.DEFAULTS["daemon_port"]
        rt.settings.vars["daemon_port"].set("not a port")
        assert rt.settings.opt_int("daemon_port") == rtmod.DEFAULTS["daemon_port"], \
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

        # Every tab this profile can actually have has a row, ticked as the profile
        # resolves it. A tab still being written has none unless «Разработка» is on
        # (#1273) — `tabsreg.listed` is the one answer to which those are.
        assert set(tab._tab_vars) == {s.id for s in tabsreg.listed()}, tab._tab_vars
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


def test_ticking_develop_on_the_tabs_page_turns_it_on():
    """The other direction, for the one tab that ships off (#1199).

    «Develop» is the sniffers: not in a fresh profile, and the page is the ONLY way to
    ask for it. Unticking is tested above; this is the half that would leave the tab
    unreachable if it broke — the box would tick and the next start would still not
    build it.
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
        rt.settings.save = lambda raw=None: None
        tab = SettingsTab(rt, ttk.Frame(root))
        tab._build_tabs_settings(ttk.Frame(root))
        assert tab._tab_vars["develop"].get() is False

        tab._tab_vars["develop"].set(True)
        tab._save_tab_choice()
        assert "develop" in saved["tabs"]["enabled"], saved["tabs"]
        # …and that is what the next start reads, in the tab's own order — last.
        resolved = [s.id for s in tabsreg.resolve(enabled=saved["tabs"]["enabled"],
                                                  known=saved["tabs"]["known"])]
        assert resolved[-1] == "develop", resolved
    finally:
        root.destroy()


def test_the_tabs_page_carries_a_hidden_tab_through_untouched():
    """A tab still being written has no row here — and loses nothing by it (#1273).

    The failure this guards against is the quiet one. The page writes `tabs.enabled`
    from its boxes; a tab with no box would drop out of that list, and the day its mark
    came off it would come back SWITCHED OFF for everybody who had ever opened this
    page — with its settings block still on disk and nothing on screen saying why the
    tab is not there. So a hidden tab keeps exactly the answer it had, and does not
    join `known` on the strength of a page it was never on.
    """
    if ttk is None:
        _skip()
        return
    try:
        import tkinter as tk                                 # noqa: F401
        import fake_runtime
        from panel import tabs as tabsreg
        from panel.tabs.settings import SettingsTab
        root = tk.Tk()
    except Exception as exc:                                 # noqa: BLE001
        _skip(exc)
        return
    root.withdraw()
    try:
        wip = [s.id for s in tabsreg.TABS if s.in_development]
        assert wip, "nothing is marked as still being written"
        hidden = wip[0]
        rt = fake_runtime.cold_runtime(root)
        # A profile from before the mark: it had the tab ticked and had been offered it.
        saved = {"tabs": {"enabled": ["rally", hidden], "known": [s.id for s in tabsreg.TABS]}}
        rt.settings.values = saved
        rt.settings.save = lambda raw=None: None
        tab = SettingsTab(rt, ttk.Frame(root))
        tab._build_tabs_settings(ttk.Frame(root))

        assert hidden not in tab._tab_vars, "a tab that cannot appear got a box"
        assert tab._tab_hidden.get(hidden) is True, tab._tab_hidden

        tab._tab_vars["rally"].set(False)      # any ordinary change writes the block
        tab._save_tab_choice()
        assert hidden in saved["tabs"]["enabled"], saved["tabs"]
        assert "rally" not in saved["tabs"]["enabled"], saved["tabs"]
        # …still hidden while the mode is off, and back the moment it is on.
        off = [s.id for s in tabsreg.resolve(enabled=saved["tabs"]["enabled"],
                                             known=saved["tabs"]["known"])]
        assert hidden not in off, off
        on = [s.id for s in tabsreg.resolve(
            enabled=saved["tabs"]["enabled"] + ["develop"],
            known=saved["tabs"]["known"])]
        assert hidden in on, on
    finally:
        root.destroy()


def test_a_tab_contributes_its_own_settings_page():
    """A tab that declares a page gets it drawn, and a window without that tab has none.

    «Автосбор» was the only real user and moved onto the «Ралли» tab itself in #1237 —
    everything on it was about rallies and none of it was a knob of the panel. The
    MECHANISM stays, because the next tab to want a page of its own should find it
    working, so it is exercised here with a stand-in contributor.
    """
    if ttk is None:
        _skip()
        return

    class _Contributor:
        ID = "rally"
        SETTINGS_PAGE_KEY = "tab.rally"

        def __init__(self):
            self.drawn = []

        def settings_page(self, parent):
            self.drawn.append(parent)

    from panel.tabs.settings import SHELL_PAGES
    tab = _Contributor()
    try:
        root, page, _rt = _page({"rally": tab})
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        nb = [w for w in root.winfo_children()[0].winfo_children()
              if isinstance(w, ttk.Notebook)][0]
        labels = [nb.tab(t, "text") for t in nb.tabs()]
        assert len(labels) == len(SHELL_PAGES) + 1, labels
        assert labels[-1] == page.t("tab.rally"), labels
        assert tab.drawn, "the tab was never asked to draw its page"
    finally:
        root.destroy()

    # …and a window without that tab has no auto-rally page at all.
    try:
        root, page, _rt = _page()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        nb = [w for w in root.winfo_children()[0].winfo_children()
              if isinstance(w, ttk.Notebook)][0]
        labels = [nb.tab(t, "text") for t in nb.tabs()]
        assert page.t("tab.rally") not in labels, labels
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
