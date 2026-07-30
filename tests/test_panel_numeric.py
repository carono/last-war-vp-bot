"""The panel-wide numeric-field rule (panel/ctk_widgets.py):

Fields that expect a number take only digits on the keystroke (a leading '-' for
a coordinate, one '.' for a float), while copy/cut/paste keep working — a paste
is filtered to a number, never blocked.

The typing predicate and the paste filter are pure functions, tested directly.
The wiring (validatecommand installed; paste filters through the clipboard) is
tested on a real widget, but WITHOUT synthesising a keystroke — headless key
events are unreliable, so the paste path is invoked directly (it is what Ctrl+V
runs). Needs the Windows Python with a working Tk display; skips otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panel.ctk_widgets import is_number, filter_number  # noqa: E402


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else
          "  SKIP tkinter not importable — run under the Windows Python")


def test_is_number_accepts_only_numbers():
    # Plain integer.
    assert is_number("") and is_number("0") and is_number("123")
    assert not is_number("12a") and not is_number("1 2") and not is_number("1.5")
    assert not is_number("-5") and not is_number("+5")
    # Signed (coordinates): one leading minus, nothing else.
    assert is_number("-", signed=True) and is_number("-42", signed=True)
    assert is_number("42", signed=True)
    assert not is_number("4-2", signed=True) and not is_number("--4", signed=True)
    # Decimal (float knobs): one dot.
    assert is_number(".", decimal=True) and is_number("2.", decimal=True)
    assert is_number("2.5", decimal=True)
    assert not is_number("2.5.5", decimal=True) and not is_number("2,5", decimal=True)
    assert is_number("-3.5", signed=True, decimal=True)


def test_filter_number_keeps_the_number_and_drops_the_rest():
    assert filter_number("1a2!3 4b") == "1234"
    assert filter_number("abc") == ""
    assert filter_number("-9x9", signed=True) == "-99"
    assert filter_number("-9x9") == "99"                 # minus dropped when unsigned
    assert filter_number("1a.2.3b", decimal=True) == "1.23"    # only the first dot
    assert filter_number("1a.2.3b") == "123"                   # dot dropped when integer
    assert filter_number("-3.5x", signed=True, decimal=True) == "-3.5"


def test_the_widget_wires_validation_and_a_filtering_paste():
    try:
        import customtkinter as ctk
    except Exception as exc:                             # noqa: BLE001
        _skip(exc)
        return
    try:
        from panel.ctk_widgets import CTkNumericEntry, numeric_spinbox
        root = ctk.CTk()
        root.geometry("200x120+0+0")
        root.update()
    except Exception as exc:                             # noqa: BLE001
        _skip(exc)
        return
    try:
        entry = CTkNumericEntry(root)
        entry.pack()
        assert entry._entry.cget("validate") == "key", "typing validation not installed"

        spin = numeric_spinbox(root, from_=1, to=35, width=5)
        spin.pack()
        assert spin.cget("validate") == "key", "spinbox validation not installed"

        # A paste is filtered, not blocked, and it replaces the selection in place.
        root.clipboard_clear()
        root.clipboard_append("1a2!3 4b")
        entry._entry.delete(0, "end")
        entry._entry._numeric_paste()
        assert entry._entry.get() == "1234", entry._entry.get()

        entry._entry.delete(0, "end")
        entry._entry.insert(0, "9999")
        entry._entry.select_range(1, 3)
        root.clipboard_clear()
        root.clipboard_append("00")
        entry._entry._numeric_paste()
        assert entry._entry.get() == "9009", entry._entry.get()

        # Signed field keeps a leading minus through a paste.
        signed = CTkNumericEntry(root, signed=True)
        signed.pack()
        root.clipboard_clear()
        root.clipboard_append("-1x2y")
        signed._entry.delete(0, "end")
        signed._entry._numeric_paste()
        assert signed._entry.get() == "-12", signed._entry.get()
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
