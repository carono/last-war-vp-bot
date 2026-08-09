r"""The leaderboard collector says COUNTS, not players — and says them rarely (#1293).

The trigger «Собирать историю лидербордов» keeps `tools/scan_leaderboard.py` running
all day and the panel logged every line it printed. Two things came of that in a live
profile's panel.log: 5 115 «…running — N board(s) opened, M row(s) collected» ticks,
one every fifteen seconds, and 2 943 lines each carrying a player's NAME and UID. The
log was unreadable, and it is a file people send each other when something goes wrong.

The board data itself is not the problem and has not moved: it goes on being written
to the profile's own `leaderboard_history.db`, which never leaves the machine. What is
pinned here is the two halves of the fix:

  * the child, asked to be `--quiet`, prints no rows and one machine-readable marker
    per tick instead of the human one;
  * the panel, reading that marker, says the counts at once the first time and then no
    oftener than :data:`panel.runtime.schedule.LEADERBOARD_NOTE_SEC`.

No wire, no game, no npcap — the tool's argument parser and the panel's line reader::

    python3 tests/test_leaderboard_quiet.py
    C:\Python312\python.exe tests\test_leaderboard_quiet.py
"""
from __future__ import annotations

TIER = "ui"        # the panel half imports the runtime, which imports Tk

import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _schedule():
    """A bare `Schedule` with only what the line reader touches, and its log."""
    from panel.runtime.schedule import Schedule

    said: list = []
    sched = Schedule.__new__(Schedule)
    sched.rt = types.SimpleNamespace(
        say=lambda tag, key, **fmt: said.append((tag, key, fmt)))
    sched._lb_said, sched._lb_snapshots = 0.0, 0
    return sched, said


# -- the panel's side --------------------------------------------------------
def test_the_first_tick_is_said_and_the_rest_are_rolled_up():
    import panel.runtime.schedule as schedmod

    sched, said = _schedule()
    tick = f"{schedmod.LEADERBOARD_STAT}\tboards=2\trows=100\tsnapshots=1"
    assert sched._leaderboard_line(tick) is False, "the marker must be swallowed"
    assert len(said) == 1, said
    _tag, key, fmt = said[0]
    assert key == "triggers.log.leaderboard", key
    assert (fmt["boards"], fmt["rows"], fmt["saved"]) == (2, 100, 1), fmt

    for _ in range(240):                    # an hour of ticks, at one every 15 s
        sched._leaderboard_line(tick)
    assert len(said) == 1, "the tick line came back"

    # …and when the window is up, one line carrying what piled up inside it.
    sched._lb_said -= schedmod.LEADERBOARD_NOTE_SEC + 1
    sched._leaderboard_line(tick)
    assert len(said) == 2, said
    assert said[1][2]["saved"] == 241, said[1][2]   # 240 counted, plus this one


def test_a_line_that_is_not_a_tick_still_reaches_the_log():
    """The child's own start-up and errors are not machinery — they must be read."""
    sched, said = _schedule()
    assert sched._leaderboard_line("cannot open the SQLite history: locked") is None
    assert said == []


def test_a_garbled_tick_costs_that_field_and_nothing_else():
    import panel.runtime.schedule as schedmod

    sched, said = _schedule()
    sched._leaderboard_line(f"{schedmod.LEADERBOARD_STAT}\tboards=x\trows=7")
    assert said[0][2]["rows"] == 7, said
    assert said[0][2]["boards"] == 0, said


# -- the tool's side ---------------------------------------------------------
def test_the_collector_offers_quiet_and_the_panel_asks_for_it():
    """The flag exists, and the trigger's command line carries it.

    The command line is read out of `Schedule._spawn_leaderboard` with a stand-in
    children factory, so no capture is started and no platform check runs.
    """
    import re

    source = (_REPO_ROOT / "tools" / "scan_leaderboard.py").read_text(encoding="utf-8")
    assert '"--quiet"' in source, "the collector has no --quiet"
    assert "STAT_MARKER" in source, "the collector prints no machine-readable tick"

    spawned: list = []

    class _Mon:
        def __init__(self, cmd):
            self.cmd = cmd

        def start(self):
            return True

    from panel.runtime.schedule import Schedule

    sched = Schedule.__new__(Schedule)

    def _spawn(tag, cmd, **kw):
        spawned.append(cmd)
        return _Mon(cmd)

    sched.rt = types.SimpleNamespace(
        children=types.SimpleNamespace(spawn=_spawn, python=lambda: "python"),
        # The two knobs the capture narrowing reads (#1306).
        settings=types.SimpleNamespace(opt_bool=lambda _k: False,
                                       opt_str=lambda _k: ""),
        profiles=types.SimpleNamespace(leaderboard_db=lambda: "history.db"))
    sched._spawn_leaderboard(types.SimpleNamespace(name="leaderboard_collect"))
    assert spawned, "no child was spawned"
    assert "--quiet" in spawned[0], spawned[0]
    assert re.search(r"scan_leaderboard\.py$", str(spawned[0][2])), spawned[0]
    # …and this profile's boards only: the collector is a capture like any other, and
    # without narrowing every open profile filed every account's rows as its own.
    assert ("--client-own-session" in spawned[0]
            or "--client-user" in spawned[0]), spawned[0]


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
