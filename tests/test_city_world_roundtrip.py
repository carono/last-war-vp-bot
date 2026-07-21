r"""Live integration test: the CITY <-> WORLD round trip, driven end to end.

This exercises the whole runtime bot stack against the *real* game, with no
computer vision anywhere:

    launch game -> wait CITY (from the TCP stream)
                -> go_to_world()  (static tap) -> wait WORLD (from the stream)
                -> go_to_base()   (static tap) -> wait CITY  (from the stream)

Every scene transition is read *passively* from the game's own network traffic
(``bot.state.LiveState`` bridges ``tools/live_tshark`` into a ``GameState``), and
every click is a fixed-coordinate touch on the shared map toggle button
(``bot.actions.navigation``). Nothing here looks at a screenshot.

It is Windows-only and needs the game plus Wireshark/npcap, so it *skips*
(exit code 2) rather than fails when those preconditions are absent — that keeps
it honest on a machine that can't run it. Run it explicitly on the game host:

    C:\Python312\python.exe tests\test_city_world_roundtrip.py
    C:\Python312\python.exe tests\test_city_world_roundtrip.py --launch   # cold start if needed

Exit codes: 0 = passed, 1 = failed, 2 = skipped (preconditions not met).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Make ``import bot`` work when run straight from the repo (no install needed).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bot.core import process
from bot.state import CaptureUnavailable, LiveState, Scene
from bot.actions import navigation


class Skip(Exception):
    """A precondition for the live test is missing; the test is inconclusive."""


# Passive scene detection depends on decisive traffic crossing the wire, which
# on an idle base can take a moment; the switches themselves are near-instant
# once the tap lands, so these are generous rather than tight.
_INITIAL_SCENE_TIMEOUT = 45.0   # first scene the stream reveals after start
_SWITCH_TIMEOUT = 20.0          # server ack of a City<->World switch
_LAUNCH_TIMEOUT = 300.0         # cold start ends on the base screen


def _log(msg: str) -> None:
    print(f"[roundtrip] {msg}", flush=True)


def _ensure_running(launch: bool) -> None:
    if process.is_game_running():
        _log("game already running")
        return
    if not launch:
        raise Skip("game is not running (pass --launch to cold-start it)")
    _log("game not running — launching")
    try:
        process.launch_game()
    except process.GameNotRunning as exc:
        raise Skip(f"cannot launch: {exc}") from exc
    deadline = time.monotonic() + _LAUNCH_TIMEOUT
    while time.monotonic() < deadline:
        if process.is_game_running():
            _log("game process is up")
            return
        time.sleep(2)
    raise Skip("game did not start within the launch timeout")


def run_roundtrip(launch: bool = False) -> None:
    """Drive and assert the full round trip. Raises Skip / AssertionError."""
    _ensure_running(launch)

    try:
        live = LiveState()
        live.start()
    except CaptureUnavailable as exc:
        raise Skip(f"live capture unavailable: {exc}") from exc

    try:
        # 1. Confirm the starting scene from the stream. The task starts in the
        #    base; if the game happens to be on the world map, normalise first.
        _log(f"waiting for a decisive scene (<= {_INITIAL_SCENE_TIMEOUT:.0f}s)…")
        if not (live.wait_for(Scene.CITY, timeout=_INITIAL_SCENE_TIMEOUT)
                or live.state.scene is Scene.WORLD):
            raise Skip(
                "no decisive traffic observed — the game must be online and "
                "active (idle bases can emit nothing for a while)")
        if live.state.scene is Scene.WORLD:
            _log("started on WORLD — going to base first to normalise")
            navigation.go_to_base(live.state, timeout=_SWITCH_TIMEOUT)
        assert live.wait_for(Scene.CITY, timeout=_SWITCH_TIMEOUT), (
            f"expected to start on CITY, state is {live.state.summary()}")
        _log(f"CITY confirmed: {live.state.summary()}")

        # 2. CITY -> WORLD via a static tap, confirmed from the stream.
        _log("go_to_world() …")
        ok = navigation.go_to_world(live.state, timeout=_SWITCH_TIMEOUT)
        assert ok and live.state.scene is Scene.WORLD, (
            f"go_to_world did not reach WORLD: {live.state.summary()}")
        _log(f"WORLD confirmed: {live.state.summary()}")

        # 3. WORLD -> CITY via a static tap, confirmed from the stream.
        _log("go_to_base() …")
        ok = navigation.go_to_base(live.state, timeout=_SWITCH_TIMEOUT)
        assert ok and live.state.scene is Scene.CITY, (
            f"go_to_base did not return to CITY: {live.state.summary()}")
        _log(f"CITY confirmed: {live.state.summary()}")

        _log("round trip OK")
    finally:
        live.stop()


# -- pytest hook (optional; skips cleanly when preconditions are absent) -------
def test_city_world_roundtrip():  # noqa: D103 - name is the pytest contract
    try:
        run_roundtrip(launch=False)
    except Skip as exc:
        try:
            import pytest
            pytest.skip(str(exc))
        except ImportError:
            import unittest
            raise unittest.SkipTest(str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", action="store_true",
                        help="cold-start the game if it is not already running")
    args = parser.parse_args()
    try:
        run_roundtrip(launch=args.launch)
    except Skip as exc:
        _log(f"SKIP: {exc}")
        return 2
    except AssertionError as exc:
        _log(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
