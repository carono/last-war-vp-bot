"""The «Send log to developer» dialog's testable core (panel/__main__.py).

The dialog itself is UI, but the tail-reader that feeds its preview is pure logic
— it must return the LAST N lines of a file, reading only the tail, and degrade
to "" for a missing/empty file. Checked here without Tk.
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import panel.__main__ as pm  # noqa: E402

_tail = pm.Panel._tail_debug_log


def test_tail_returns_the_last_lines():
    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "debug.log")
        Path(p).write_text("\n".join(f"line{i}" for i in range(500)) + "\n",
                           encoding="utf-8")
        out = _tail(p, 100).splitlines()
        assert len(out) == 100, len(out)
        assert out[0] == "line400" and out[-1] == "line499", (out[0], out[-1])


def test_tail_of_a_short_file_is_the_whole_file():
    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "debug.log")
        Path(p).write_text("a\nb\nc\n", encoding="utf-8")
        assert _tail(p, 100).splitlines() == ["a", "b", "c"]


def test_tail_of_missing_or_empty_is_blank():
    with tempfile.TemporaryDirectory() as d:
        assert _tail(str(Path(d) / "nope.log"), 100) == ""
        empty = Path(d) / "e.log"
        empty.write_text("", encoding="utf-8")
        assert _tail(str(empty), 100) == ""


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
