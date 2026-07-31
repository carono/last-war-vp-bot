"""The Alliance / Profile / Inventory tabs (panel/tabs_extra.py).

Pure helpers (number grouping, marker-line extraction) are tested directly. The
tab widgets need Tk, so they are built on a tkinter root and only checked to
construct and lazy-load without raising; the live data reads degrade to an empty
state off the game and are not asserted here. Skips without a Tk display.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panel import tabs_extra as tx  # noqa: E402


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else "  SKIP no tkinter")


def test_group_formats_numbers_and_passes_text_through():
    assert tx._group(1234567) == "1,234,567"
    assert tx._group("1000") == "1,000"
    assert tx._group("1,000") == "1,000"
    assert tx._group(None) == "" and tx._group("") == ""
    assert tx._group("abc") == "abc"        # non-numbers pass through


def test_marker_payloads_extracts_each_line():
    lines = ["noise", "ALLY Bob\t9\t100\t1\t0", "x ALLY", "ALLY Al\t3\t50\t0\t42"]
    got = tx._marker_payloads(lines, "ALLY")
    assert got == ["Bob\t9\t100\t1\t0", "Al\t3\t50\t0\t42"], got
    assert tx._marker_payloads([], "ALLY") == []


def test_tabs_build_and_lazy_load_without_raising():
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return

    class _App(tk.Tk):
        """A minimal panel stand-in: i18n echo, no daemon."""
        def _t(self, key, **fmt):
            return key
        def _tr(self, widget, key, option="text", **fmt):
            try:
                widget.configure(**{option: key})
            except Exception:                           # noqa: BLE001
                pass
            return widget
        def _daemon_port(self):
            return 47999
        def _daemon_up(self):
            return False
        def _read_resource_balance(self):
            return {}

    try:
        app = _App()
        app.withdraw()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        for cls in (tx.AllianceTab, tx.ProfileTab, tx.InventoryTab):
            frame = ttk.Frame(app)
            tab = cls(app, frame)
            assert not tab._loaded, "must not load before shown"
            # No daemon → fetch returns empty; render must not raise.
            tab.render(tab.fetch())
            tab.ensure_loaded()
            assert tab._loaded, "ensure_loaded should mark it loaded"
            tab.ensure_loaded()                          # idempotent
        # inventory search filter is pure-ish: empty list stays empty
        inv = tx.InventoryTab(app, ttk.Frame(app))
        inv._items = [{"name": "Wood chest", "count": "3", "desc": "d"}]
        inv._query.set("wood"); inv._redraw()
        inv._query.set("zzz"); inv._redraw()             # filters everything out
    finally:
        app.destroy()


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
