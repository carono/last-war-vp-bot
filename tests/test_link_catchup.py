r"""Связь поднимается сама и быстро — правило, без игры (задача #1976).

The acceptance criterion the whole panel is judged by is one sentence: **a person starts
the game and nothing else.** Everything after that is the panel's job, and how long it
takes is a number, not an impression.

What is pinned here, all of it offline:

  * **nothing held ⇒ look again soon.** The watch has TWO fixed rates and nothing in
    between: `CATCH_SEC` while there is a client to catch, `WATCH_SEC` once one is held.
    No backoff, no doubling, no escalation — the failure mode this replaces is a wait
    that grows until «I started the game» means «some time this half hour» (#1910).
  * **the stamp is about THIS appearance.** A client that is not there clears it, so a
    client that comes back an hour later is timed from its own appearance.
  * **attaching does not stop the clock.** Green is the game SERVER answering, which is
    seconds after the hold is taken, and the number a person cares about is that one.
  * **the number is handed over ONCE.** The light is repainted every few seconds; the
    line that says «связь поднялась за N с» is said once per appearance.

    C:\Python312\python.exe tests\test_link_catchup.py
    python3 tests/test_link_catchup.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

# LOADED BY PATH, not as `panel.runtime.lua_service`: importing the package pulls in the
# window (`tkinter`), and the rule under test is about the link and not about a front-end.
# It is also what lets this run on a machine that has no Tk at all.
_spec = importlib.util.spec_from_file_location(
    "lw_lua_service", ROOT / "panel" / "runtime" / "lua_service.py")
lua_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lua_service)


class FakeDaemon:
    """The VM half, hand-wound: is a client there, is one held."""

    def __init__(self, present: bool = False, warm: bool = False) -> None:
        self.present, self.warm = present, warm

    def is_warm(self) -> bool:
        return self.warm

    def client_present(self) -> bool:
        return self.present


def _service(present: bool = False, warm: bool = False):
    """A service with no socket, no port and no game — only the two readings above."""
    svc = lua_service.LuaService.__new__(lua_service.LuaService)
    svc._daemon = FakeDaemon(present, warm)
    svc._seen_at = None
    return svc


class Clock:
    """A hand-wound clock: nothing here may depend on a test being quick."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _with_clock(svc, clock):
    lua_service.time.monotonic = clock                # noqa: SLF001 — the module's clock
    return svc


def test_nothing_held_means_look_again_soon():
    assert lua_service.CATCH_SEC < lua_service.WATCH_SEC
    assert _service(present=True, warm=False).catching() is True
    assert _service(present=False, warm=False).catching() is True


def test_a_client_that_is_held_stands_the_watch_down():
    assert _service(present=True, warm=True).catching() is False


def test_the_two_rates_never_grow():
    """Not a backoff: both are constants, and the fast one is a second or two."""
    assert 0.5 <= lua_service.CATCH_SEC <= 3.0
    assert isinstance(lua_service.CATCH_SEC, float)


def test_the_stamp_starts_when_a_client_appears():
    clock = Clock()
    svc = _with_clock(_service(present=True), clock)
    svc._mark_seen()
    clock.now += 12.0
    svc._mark_seen()                                  # still the same appearance
    assert round(svc.take_wait()) == 12


def test_a_client_that_is_gone_clears_the_stamp():
    clock = Clock()
    svc = _with_clock(_service(present=True), clock)
    svc._mark_seen()
    clock.now += 3600.0
    svc._daemon.present = False
    svc._mark_seen()                                  # gone: forget when it was here
    svc._daemon.present = True
    svc._mark_seen()                                  # here again: time THIS one
    clock.now += 4.0
    assert round(svc.take_wait()) == 4


def test_taking_hold_does_not_stop_the_clock():
    """Green is the SERVER answering, and that is some seconds past the attach."""
    clock = Clock()
    svc = _with_clock(_service(present=True), clock)
    svc._mark_seen()
    clock.now += 2.0
    svc._daemon.warm = True
    svc._mark_seen()                                  # held now — the stamp stands
    clock.now += 6.0
    assert round(svc.take_wait()) == 8


def test_the_number_is_handed_over_once():
    clock = Clock()
    svc = _with_clock(_service(present=True), clock)
    svc._mark_seen()
    clock.now += 5.0
    assert svc.take_wait() is not None
    assert svc.take_wait() is None                    # the line is said once, not per poll


def test_nothing_to_say_when_no_client_was_ever_seen():
    assert _service(present=False).take_wait() is None


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
