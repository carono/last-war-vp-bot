r"""«Разработка» is four inner pages, and only the open one costs anything (#1415).

WHAT WENT WRONG, measured before it was fixed: the tab packed the sniffers, the update
tick, «Занятость», the scenario list with its editor and the log one under the other into
a single column. Built on the page the panel really gives it, that column asks for 1382
pixels of height — and `pack` hands out the cavity in PACKING ORDER, so the two
`expand=True` blocks in the middle took what was left and the log, packed last, was
allotted a height of ONE PIXEL and never mapped. Not «below the fold»: absent, at every
window size, `side="bottom"` and all.

So the page is a notebook now, and this file pins the four things that must stay true:

  * the tab's own frame holds the header and the notebook and NOTHING else — a block
    packed beside them is a column again, and the next one after it is invisible;
  * every page builds, and its content is really mapped and really has the page's height;
  * a page is built the first time it is LOOKED at, and only the visible one works —
    «Занятость» arms its once-a-second read only while it is on top, and the log pane is
    off the spool while it is not (the spool keeps the history either way, #1391);
  * what a page holds is remembered while it is closed: the script «Сценарии» was left
    on, the log's filter, and which page was open.

Needs Tk and a display, so it SKIPs under the WSL python3 (no tkinter):

    C:\Python312\python.exe tests\test_panel_develop_pages.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_runtime  # noqa: E402


def _tab(height: int = 700):
    """The real tab, drawn into a real window that is never shown to anybody.

    Transparent and off-screen: a test must not steal the foreground on the machine
    that is driving the game with it (`docs/research/profile-isolation.md`, and the
    input model — the client only hears a foreground press).
    """
    import tkinter as tk
    from tkinter import ttk

    from panel.tabs.develop import DevelopTab

    root = tk.Tk()
    root.attributes("-alpha", 0.0)
    root.overrideredirect(True)
    root.geometry(f"1000x{height}+4000+4000")
    rt = fake_runtime.cold_runtime(root)
    frame = ttk.Frame(root)
    frame.pack(fill="both", expand=True)
    tab = DevelopTab(rt, frame)
    rt.tabs.add(tab)
    tab.realize()
    root.update()
    return root, rt, tab, frame


def _close(root) -> None:
    try:
        for job in root.tk.eval("after info").split():
            try:
                root.after_cancel(job)
            except Exception:                       # noqa: BLE001
                pass
    except Exception:                               # noqa: BLE001
        pass
    root.destroy()


def _skip(exc) -> None:
    print(f"  SKIP no display / panel deps: {exc}")


# -- the shape of the page ---------------------------------------------------
def test_the_tab_is_a_header_and_a_notebook_and_nothing_else():
    """A third block beside them is the column coming back, and the column hid the log."""
    try:
        import tkinter  # noqa: F401
        from tkinter import ttk
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        root, _rt, tab, frame = _tab()
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        kids = frame.winfo_children()
        assert len(kids) == 2, [str(k) for k in kids]
        assert isinstance(kids[-1], ttk.Notebook), kids[-1]
        assert kids[-1] is tab._nb
    finally:
        _close(root)


def test_every_page_fills_the_tab_and_is_really_mapped():
    """The old fault, in the one form a test can see: content allotted no height."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    from panel.tabs.develop import PAGES
    try:
        root, _rt, tab, _frame = _tab(height=700)
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        for key in PAGES:
            tab.show_page(key)
            root.update()
            page = tab._frames[key]
            assert page.winfo_height() > 200, (key, page.winfo_height())
            kids = page.winfo_children()
            assert kids, f"{key}: nothing was drawn"
            for kid in kids:
                assert kid.winfo_ismapped(), f"{key}: {kid} was allotted no room"
            drawn = max(k.winfo_y() + k.winfo_height() for k in kids)
            assert drawn <= page.winfo_height() + 1, (key, drawn, page.winfo_height())
    finally:
        _close(root)


def test_a_short_window_still_shows_the_whole_of_a_page():
    """The column starved at 700 px and worse below it; a page does not care."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        root, _rt, tab, _frame = _tab(height=460)
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        for key in ("log", "busy"):
            tab.show_page(key)
            root.update()
            kids = tab._frames[key].winfo_children()
            assert kids and all(k.winfo_ismapped() for k in kids), key
    finally:
        _close(root)


# -- and only the open one costs anything ------------------------------------
def test_a_page_is_built_the_first_time_it_is_looked_at():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        root, _rt, tab, _frame = _tab()
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        assert tab._page_built == set(), "a page was drawn before anybody looked"
        tab.on_show()
        root.update()
        assert tab._page_built == {"log"}, tab._page_built
        tab.show_page("scenarios")
        root.update()
        assert tab._page_built == {"log", "scenarios"}, tab._page_built
        assert tab._scn_list is not None, "the scenario page drew no list"
    finally:
        _close(root)


def test_the_busy_page_only_ticks_while_it_is_the_one_being_read():
    """`BusyView` reads once a second; a debugger nobody is looking at reads never."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    from panel.tabs.develop_busy import TICK
    try:
        root, rt, tab, _frame = _tab()
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        armed = rt.tick._loops
        tab.show_page("busy")
        root.update()
        assert TICK in armed, "the busy block is not reading while it is open"
        tab.show_page("log")
        root.update()
        assert TICK not in armed, "the busy block kept reading behind another page"
        tab.show_page("busy")
        root.update()
        assert TICK in armed, "it did not start again when it was opened again"
        tab.on_hide()
        root.update()
        assert TICK not in armed, "it kept reading after the tab was left"
    finally:
        _close(root)


def test_the_log_pane_leaves_the_spool_when_its_page_is_not_open():
    """The spool keeps the history whether or not a pane draws it (#1391)."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        root, rt, tab, _frame = _tab()
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        tab.show_page("log")
        root.update()
        assert rt.log_spool.pane is tab._log, "the log page drew nothing onto the spool"
        tab.show_page("busy")
        root.update()
        assert rt.log_spool.pane is None, "a hidden log pane is still being written to"
        # …and what happened meanwhile is still there when it comes back.
        rt.log_spool._kept.append(("12:00:00", "[panel] while nobody looked"))
        tab.show_page("log")
        root.update()
        assert rt.log_spool.pane is tab._log
        assert "while nobody looked" in tab._log.text.get("1.0", "end")
    finally:
        _close(root)


# -- what a closed page still remembers --------------------------------------
def test_a_closed_page_keeps_what_the_profile_was_saved_with():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        root, _rt, tab, _frame = _tab()
    except Exception as exc:                        # noqa: BLE001
        return _skip(exc)
    try:
        tab.apply_config({"scenario_selected": "heal_units", "scenario_args": '{"a": 1}',
                          "scenario_interval": "120", "log_filter": "secret",
                          "page": "scenarios"})
        # Nothing has been opened, so nothing may be forgotten either.
        block = tab.config()
        assert block["scenario_selected"] == "heal_units", block
        assert block["log_filter"] == "secret", block
        assert block["page"] == "scenarios", block
        tab.on_show()                       # opens on the page it was saved on
        root.update()
        assert tab._live == "scenarios", tab._live
        assert tab.config()["page"] == "scenarios"
    finally:
        _close(root)


def test_the_page_names_are_keys_in_every_shipped_locale():
    """A page label is a word of the panel's, so all eleven say it (`CLAUDE.md`)."""
    from panel.tabs.develop import PAGES

    locales = sorted((_REPO / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11, [p.name for p in locales]
    for path in locales:
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in PAGES:
            full = f"develop.page.{key}"
            assert table.get(full), f"{path.name} has no {full}"


def test_the_tab_still_has_no_screen_on_the_phone():
    """The standing divergence is untouched by the rearrangement (`CLAUDE.md`)."""
    from panel.tabs import BY_ID

    assert BY_ID["develop"].load().WEB_SCREEN is False


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
