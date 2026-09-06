r"""A launcher that is still working is waited for, never killed and never doubled (#2578).

Two numbers used to cancel each other out. A start into another account's session waits
`START_TIMEOUT_SEC` for the client, gives up saying «the launcher may still be updating»
and — correctly — leaves the launcher running. The next attempt then found that same
launcher aged exactly `START_TIMEOUT_SEC`, which was also `LAUNCHER_STALE_SEC`, called it
stuck and ended it. A build that needed longer than five minutes to download could
therefore never finish downloading: every attempt killed the previous attempt's progress.

Measured live on 2026-09-06 on a second account's session: twelve relaunches an hour for
fifteen hours, and not one of them ever produced a client.

Two behaviours are pinned, both about the same launcher:

  * a launcher that survives `clear_stale_launchers` is one to WAIT for — the launcher is
    single-instance, so a second start over it does nothing but write a line;
  * and the stale limit can never again be met by the start timeout, whatever a machine
    configures, because a value at or under it recreates the loop exactly.

    C:\Python312\python.exe tests\test_launcher_is_left_to_finish.py
    python3 tests/test_launcher_is_left_to_finish.py
"""
from __future__ import annotations

TIER = "offline"

import os
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools" / "lib"))

import game_client                                           # noqa: E402


def test_the_stale_limit_cannot_meet_the_start_timeout():
    assert game_client.launcher_stale_sec() > game_client.START_TIMEOUT_SEC, \
        "a launcher goes stale the moment a start gives up waiting for it"


def test_a_configured_limit_cannot_recreate_the_loop():
    before = os.environ.get("LW_LAUNCHER_STALE_SEC")
    os.environ["LW_LAUNCHER_STALE_SEC"] = "60"
    try:
        assert game_client.launcher_stale_sec() > game_client.START_TIMEOUT_SEC, \
            "a machine was allowed to configure the relaunch loop back in"
    finally:
        if before is None:
            os.environ.pop("LW_LAUNCHER_STALE_SEC", None)
        else:
            os.environ["LW_LAUNCHER_STALE_SEC"] = before


def test_a_bigger_limit_is_still_honoured():
    before = os.environ.get("LW_LAUNCHER_STALE_SEC")
    os.environ["LW_LAUNCHER_STALE_SEC"] = "9000"
    try:
        assert game_client.launcher_stale_sec() == 9000.0, \
            "the floor swallowed a value that was deliberately raised"
    finally:
        if before is None:
            os.environ.pop("LW_LAUNCHER_STALE_SEC", None)
        else:
            os.environ["LW_LAUNCHER_STALE_SEC"] = before


def test_a_young_launcher_is_waited_for_not_doubled():
    """The hop that starts a second launcher must not be reached at all."""
    said: list = []
    hopped: list = []
    waited: list = []
    saved = {name: getattr(game_client, name)
             for name in ("session_of", "session_pids_of", "launcher_pids",
                          "clear_stale_launchers", "_tools_on_path",
                          "_wait_for_client")}
    game_client.session_of = lambda _user: 3
    game_client.session_pids_of = lambda *_a, **_k: []
    game_client.launcher_pids = lambda _session=None: [4242]
    game_client.clear_stale_launchers = lambda **_k: 0
    game_client._tools_on_path = lambda: hopped.append("hop")
    game_client._wait_for_client = (
        lambda session, user, game_exe, timeout, say: waited.append(session) or 999)
    try:
        pid = game_client._start_in_session("someone", None, 300.0, "Game.exe",
                                            said.append)
    finally:
        for name, value in saved.items():
            setattr(game_client, name, value)

    assert not hopped, "a second launcher was started over one that was still working"
    assert waited == [3], "the surviving launcher's client was never waited for"
    assert pid == 999, f"the wait's answer was dropped: {pid}"
    assert any("already at work" in line for line in said), \
        f"nothing in the log says why no launcher was started: {said}"


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
