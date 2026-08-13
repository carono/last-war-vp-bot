r"""A capture's progress line prints when the numbers MOVED, never once a second (#1332).

Every passive capture prints one progress line per `--interval`, and nothing pans the
map by itself, so an idle stretch used to read like this in a live panel's log — the
same sentence, to the character, once a second for hours::

    12:32:33 [secret]   …running — server 1000, 246 map response(s), 51452 tile(s), …
    12:32:34 [secret]   …running — server 1000, 246 map response(s), 51452 tile(s), …
    12:32:35 [secret]   …running — server 1000, 246 map response(s), 51452 tile(s), …

`map_capture.ProgressTicker` is the one rule for all of them (the secret-task capture
had grown its own; the ghost, treasure, player, truck and tile-dump ones had none):

  * the first tick speaks, so a capture that has found nothing still says so once;
  * a tick whose numbers are unchanged says nothing at all;
  * a tick whose numbers moved speaks;
  * and standing still for `PROGRESS_HEARTBEAT_SEC` speaks anyway, so a capture nobody
    is panning for is alive rather than silent.

The line itself is unchanged — same words, same fields, same order — so anything that
reads these lines (the panel's own filter, a person's eye) reads what it always did,
only less often.

No wire, no game, no npcap — the ticker, and the source of every capture that must be
using it::

    python3 tests/test_capture_progress_quiet.py
    C:\Python312\python.exe tests\test_capture_progress_quiet.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import map_capture                                        # noqa: E402

#: Every capture that prints a periodic progress line. The panel runs the first three
#: as children; the rest are hand-run, and one rule means one rule.
_CAPTURES = (
    "tools/secret_task_capture.py",
    "tools/dev/secret_mission_capture.py",
    "tools/dev/treasure_capture.py",
    "tools/scan_players.py",
    "tools/dev/scan_trucks.py",
    "tools/dev/ghost_recon_tile_dump.py",
    "tools/lib/live_tshark.py",
    "tools/scan_leaderboard.py",
)

#: What a PROGRESS line is, in source: the one that carries the countdown («…12s left»
#: / «…running»). The end-of-run summary reports the same counts and must never be
#: gated — it is said once, and it is the whole point of the run.
_COUNTDOWN = "{left}"


# -- the rule itself ---------------------------------------------------------
def test_an_identical_tick_does_not_print_a_second_line():
    """THE BUG, in three lines: the same numbers, again and again, all silent."""
    ticker = map_capture.ProgressTicker()
    sig = (1000, 246, 51452, 217, 217, 0)

    assert ticker.due(sig, now=0.0) is True, "the first tick must speak"
    for second in range(1, 300):                 # five minutes of once-a-second ticks
        assert ticker.due(sig, now=float(second)) is False, f"tick {second} spoke"
    assert ticker.silent == 299, ticker.silent


def test_a_tick_that_moved_speaks_at_once():
    ticker = map_capture.ProgressTicker()
    assert ticker.due((0, 0), now=0.0) is True
    assert ticker.due((0, 0), now=1.0) is False
    assert ticker.due((1, 0), now=2.0) is True, "a number moved and nothing was said"
    assert ticker.silent == 0, "the swallowed count is per line, not per run"


def test_standing_still_still_proves_the_capture_is_alive():
    """The heartbeat — the whole point of not simply dropping the line for ever."""
    ticker = map_capture.ProgressTicker()
    sig = ("server unknown yet", 0, 0)
    assert ticker.due(sig, now=0.0) is True
    assert ticker.due(sig, now=map_capture.PROGRESS_HEARTBEAT_SEC - 1) is False
    assert ticker.due(sig, now=map_capture.PROGRESS_HEARTBEAT_SEC) is True
    # …and the heartbeat restarts from the line it just printed, not from the run.
    assert ticker.due(sig, now=map_capture.PROGRESS_HEARTBEAT_SEC + 1) is False


def test_the_heartbeat_is_minutes_not_seconds():
    """A heartbeat as fast as the tick would be the bug wearing a different hat."""
    assert 60 <= map_capture.PROGRESS_HEARTBEAT_SEC <= 3600, \
        map_capture.PROGRESS_HEARTBEAT_SEC


def test_a_state_change_may_reset_it():
    ticker = map_capture.ProgressTicker()
    sig = (7, 7)
    assert ticker.due(sig, now=0.0) is True
    assert ticker.due(sig, now=1.0) is False
    ticker.reset()
    assert ticker.due(sig, now=2.0) is True, "a reset ticker must speak its next tick"


# -- and every capture obeying it -------------------------------------------
def test_every_capture_gates_its_progress_line():
    """The line must be reachable only through the ticker, in all of them.

    Read off the source rather than run: starting a real capture needs npcap, a
    Windows interpreter and a game. What is checked is that the print carrying the
    countdown sits under a gate the ticker owns — `if changed:` or a direct
    `ticker.due(...)` — within the handful of lines above it.
    """
    for rel in _CAPTURES:
        source = (_REPO / rel).read_text(encoding="utf-8")
        assert "ProgressTicker" in source, f"{rel} does not use the shared rule"
        lines = source.splitlines()
        printed = [i for i, ln in enumerate(lines)
                   if _COUNTDOWN in ln and "print(" in "\n".join(
                       lines[max(0, i - 3):i + 1])]
        assert printed, f"{rel}: no progress line found — has it been renamed?"
        for i in printed:
            above = "\n".join(lines[max(0, i - 14):i + 1])
            assert re.search(r"ticker\.due\(|if changed\b|and changed\b", above), \
                f"{rel}:{i + 1} prints a progress line that no ticker gates"


def test_the_leaderboard_marker_is_not_gated():
    """The `--quiet` marker keeps its own beat — the PARENT rolls those up (#1293).

    Gating it here would lose the snapshot tally the panel counts off every tick, and
    the panel already says the counts no oftener than its own window allows.
    """
    source = (_REPO / "tools" / "scan_leaderboard.py").read_text(encoding="utf-8")
    body = source.split("STAT_MARKER}\\tboards=")[-1]
    assert body, "the marker print has moved"
    marker_at = source.index('print(f"{STAT_MARKER}')
    above = source[:marker_at].splitlines()[-8:]
    assert not any("ticker.due(" in ln for ln in above), \
        "the machine-readable marker must print on every tick"


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
