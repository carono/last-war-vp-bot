r"""`panel.log` is sliced every twenty megabytes (#2660).

The mirror behind the log pane (`panel/runtime/log.py`) held one file for the whole life
of a profile and never trimmed it. On the live machine that was 914 MB in one account —
a record nothing can read: the web front-end seeds its tail by walking the file, and
every «что было ночью» means reading the whole of it.

What is pinned here:

  * a file that crosses the quantum is closed and reopened, and the slice sits beside it
    as `panel.log.1`;
  * the slices shift along — `.1` becomes `.2` — and only `BACKUPS` of them are kept;
  * dropping the oldest is SAID, never done quietly;
  * a panel that OPENS a file already over the quantum rotates it before it writes,
    rather than appending to a log that is already too big;
  * nothing is lost: what was written before a rotation is still in the slice.

Runs anywhere (no tkinter, no game):

    python3 tests/test_panel_log_rotation.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

TIER = "offline"     # no Tk, no game — see tools/run_tests.py

from panel.runtime.log import LogBus


def _bus(folder: str, quantum: int = 2048, backups: int = 2) -> LogBus:
    bus = LogBus(translate=lambda key, **fmt: key)
    bus.QUANTUM, bus.BACKUPS = quantum, backups
    bus.open_file(os.path.join(folder, "panel.log"))
    return bus


def _fill(bus: LogBus, n: int, mark: str = "x") -> None:
    for i in range(n):
        bus.append_file(f"[panel] {mark}{i} " + "-" * 100)


def test_a_full_file_is_sliced_and_the_slice_is_kept():
    with tempfile.TemporaryDirectory() as folder:
        bus = _bus(folder)
        _fill(bus, 18, mark="first")
        bus.close_file()
        slice_one = os.path.join(folder, "panel.log.1")
        assert os.path.exists(slice_one), "the full file was not sliced off"
        assert "first0" in open(slice_one, encoding="utf-8").read(), \
            "the slice does not hold what was written before the rotation"
        assert not os.path.exists(os.path.join(folder, "panel.log.2")), \
            "one quantum made two slices"
        assert os.path.getsize(os.path.join(folder, "panel.log")) < bus.QUANTUM, \
            "the live file was not started fresh"


def test_the_slices_shift_along_and_the_oldest_goes_with_a_word_about_it():
    with tempfile.TemporaryDirectory() as folder:
        bus = _bus(folder, backups=2)
        said: list = []
        bus.tap(said.append)
        _fill(bus, 40, mark="one")
        _fill(bus, 40, mark="two")
        _fill(bus, 40, mark="three")
        bus.close_file()
        assert os.path.exists(os.path.join(folder, "panel.log.1"))
        assert os.path.exists(os.path.join(folder, "panel.log.2"))
        assert not os.path.exists(os.path.join(folder, "panel.log.3")), \
            "more slices are kept than BACKUPS allows"
        assert any("log.rotated" in line for line in said), \
            "a rotation was not said in the log"
        assert any("log.rotate.dropped" in line for line in said), \
            "the oldest slice was dropped in silence"


def test_a_log_already_over_the_quantum_is_rotated_before_the_session_writes():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "panel.log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("old\n" * 2000)
        bus = LogBus(translate=lambda key, **fmt: key)
        bus.QUANTUM, bus.BACKUPS = 2048, 2
        bus.open_file(path)
        bus.append_file("[panel] a new session")
        bus.close_file()
        assert "old" in open(path + ".1", encoding="utf-8").read(), \
            "the oversized log was not carried into a slice"
        fresh = open(path, encoding="utf-8").read()
        assert "a new session" in fresh and "old" not in fresh, \
            "the session went on appending to a file that was already too big"


def test_the_quantum_is_the_twenty_megabytes_that_was_asked_for():
    assert LogBus.QUANTUM == 20 * 1024 * 1024, "the quantum is not 20 MB"
    assert LogBus.BACKUPS >= 1, "nothing is kept beside the live file"


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
