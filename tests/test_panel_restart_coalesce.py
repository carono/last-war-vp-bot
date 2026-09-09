r"""Several fixes cost the game ONE restart, not one each (#2678).

A restart costs a client. That is measured twice over: #2665 counted six of nine restarts
killing the game inside two minutes, and the live day of 2026-09-09 says the same from
the other end — 30 of 41 panel restarts were followed by a fresh client pid within ten
minutes, median 128 s. The person's report that day was «каждые 2 3 минуты вышибает
клиент», and the hours line up: 2 restarts/2 deaths at 10:00, 11/8 at 13:00.

Nothing in the code had regressed. What changed is the RATE — `CLAUDE.md` tells every
agent to restart the live panel after any fix, and several agents at once turn that into a
restart every three to five minutes.

So a press that arrives inside `COALESCE_SEC` of this process's boot is HELD, and because
every press re-arms the one named chain, ten presses inside that window are one restart.
What is pinned here:

  * a panel that has been up a long time restarts at its ordinary short delay;
  * one that has just come up waits out the rest of the window, and says so;
  * the wait is never SHORTER than the ordinary delay — the HTTP answer still has to be
    written before the process goes;
  * every press arms the SAME chain name, which is what makes ten of them one restart;
  * a boot stamp that cannot be read holds nobody.

    python3 tests/test_panel_restart_coalesce.py
    C:\Python312\python.exe tests\test_panel_restart_coalesce.py
"""
from __future__ import annotations

TIER = "offline"   # no Tk, no game — a stub runtime and a fake clock

import importlib
import sys
import time
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_pkg = sys.modules.setdefault("panel", types.ModuleType("panel"))
_pkg.__path__ = [str(_REPO / "panel")]
# `updates` falls back to the package's own version string when git cannot answer, and a
# bare namespace has none — one attribute is cheaper than executing `panel/__init__.py`,
# which draws.
if not hasattr(_pkg, "__version__"):
    _pkg.__version__ = "0.0.0-test"
_rt = sys.modules.setdefault("panel.runtime", types.ModuleType("panel.runtime"))
_rt.__path__ = [str(_REPO / "panel" / "runtime")]
pc = importlib.import_module("panel.runtime.panel_control")


class Tick:
    THREADED = True

    def __init__(self) -> None:
        self.armed: list = []

    def arm(self, name, delay_ms, func) -> None:
        self.armed.append((name, int(delay_ms), func))


class Rt:
    """The three things `request` touches on a windowless panel."""

    def __init__(self) -> None:
        self.root = None
        self.tick = Tick()
        self.said: list = []

    def say(self, tag, key, **fmt) -> None:
        self.said.append((key, fmt))


def _booted(secs_ago: float):
    """Pretend this process came up ``secs_ago`` seconds ago."""
    mod = importlib.import_module("panel.runtime.updates")
    was = dict(getattr(mod, "_BOOT", {}))
    mod._BOOT.clear()
    mod._BOOT.update({"pid": 1, "at": time.time() - secs_ago, "head": "0" * 8})
    return mod, was


def _press():
    rt = Rt()
    pc.set_handler(lambda: None)
    try:
        return rt, pc.request(rt)
    finally:
        pc.set_handler(None)


def test_a_long_lived_panel_restarts_at_once():
    mod, was = _booted(pc.COALESCE_SEC + 60)
    try:
        rt, out = _press()
        assert out["ok"] and not out["held"], out
        assert out["delay_ms"] == pc.DELAY_MS
        assert rt.said[0][0] == "log.panel.restarting"
    finally:
        mod._BOOT.clear(); mod._BOOT.update(was)


def test_a_panel_that_just_came_up_waits_out_the_window():
    mod, was = _booted(30.0)
    try:
        rt, out = _press()
        assert out["held"] is True, "the restart went straight through"
        left = out["delay_ms"] / 1000.0
        assert pc.COALESCE_SEC - 40 < left <= pc.COALESCE_SEC - 20, left
        assert rt.said[0][0] == "log.panel.restart_held", rt.said
        assert "seconds" in rt.said[0][1], "the line does not say how long"
    finally:
        mod._BOOT.clear(); mod._BOOT.update(was)


def test_the_hold_is_never_shorter_than_the_ordinary_delay():
    mod, was = _booted(pc.COALESCE_SEC - 0.2)
    try:
        _rt, out = _press()
        assert out["delay_ms"] >= pc.DELAY_MS, out
    finally:
        mod._BOOT.clear(); mod._BOOT.update(was)


def test_ten_presses_are_one_restart():
    """The whole point: they all re-arm the ONE named chain."""
    mod, was = _booted(10.0)
    try:
        rt = Rt()
        pc.set_handler(lambda: None)
        try:
            for _ in range(10):
                pc.request(rt)
        finally:
            pc.set_handler(None)
        names = {name for name, _ms, _f in rt.tick.armed}
        assert names == {pc.TICK}, f"a press queued a chain of its own: {names}"
    finally:
        mod._BOOT.clear(); mod._BOOT.update(was)


def test_no_boot_stamp_holds_nobody():
    mod, was = _booted(10.0)
    try:
        mod._BOOT.clear()
        mod._BOOT.update({"pid": 1, "at": 0, "head": ""})
        _rt, out = _press()
        assert out["delay_ms"] == pc.DELAY_MS and not out["held"]
    finally:
        mod._BOOT.clear(); mod._BOOT.update(was)


def test_the_window_is_longer_than_the_measured_death():
    """128 s is the median from a restart to a fresh client — a shorter window would let
    the next restart land on a client still coming back up."""
    assert pc.COALESCE_SEC >= 128.0


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
